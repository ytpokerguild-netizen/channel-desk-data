#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""運営ログ（非公開スプレッドシート）→ ops.json を自動生成する（GitHub Actions 用）

3時間おきの daily_fetch から呼ばれる。スプレッドシートを直せば、依頼しなくても
最大3時間でダッシュボードに反映される。

必要な環境変数（GitHub Secrets）: **どちらか一方でよい。SA を優先します。**

  ① サービスアカウント方式（推奨・2026-08-12〜）
    SHEETS_SA_KEY          サービスアカウントの鍵（JSON をそのまま貼る）

  ② リフレッシュトークン方式（旧・フォールバック）
    SHEETS_REFRESH_TOKEN   スプレッドシート読み取り専用のリフレッシュトークン
    SHEETS_CLIENT_ID       （無ければ OAUTH_CLIENT_ID にフォールバック）
    SHEETS_CLIENT_SECRET   （無ければ OAUTH_CLIENT_SECRET にフォールバック）

**なぜ ① を推すのか**（2026-08-12 の判断。同じ議論を繰り返さないために）
  * ②は**個人の Google アカウントに紐づく**ため、その人が抜けたり権限を取り消すと止まる。
    引き継ぎのたびに取り直しになる。
  * ②は OAuth 同意画面が「テスト」状態だと**リフレッシュトークンが7日で失効**する。
    本番公開が必須で、そこを忘れると1週間後に黙って止まる。
  * ①はプロジェクトに属するので**人が変わっても生き続け、期限も無い**。
  * ①の代償は `google-auth` への依存1つだけ（このファイルのみ。fetch.py は標準ライブラリのまま）。

設計の要点:
  * **既存の REFRESH_TOKEN（YouTube用）には一切触らない。** 別トークン・別Secretにしている。
    こちらが壊れても日次のデータ更新は止まらない。
  * どちらの Secret も無いときは「未設定」と表示して**正常終了**する（導入前でも失敗にしない）。
  * 読み取りや検証に失敗した場合は **ops.json を書き換えずに** 異常終了する。
    シートを壊してしまったときに、公開側の中身が消えたり漏れたりしないようにするため。
  * 公開判断（公開列のフィルタ・実名の置換）は build_ops_json.py の関数をそのまま使う。
    ロジックを二重に持たない。
  * Python 標準ライブラリのみ（fetch.py と同じ方針）。
"""
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from build_ops_json import OpsError, build_ops, norm, report, write_ops

SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"

SPREADSHEET_ID = "1v--hBNlRU431gr-4DX4fm9L1Xr6w28-Hv93ufo-w-wo"  # PG運営ログ（非公開）
OUTPUT = "ops.json"

# 取りに行くシートと範囲。範囲は余裕を持たせる（行が増えても取り漏らさないように）
RANGES = [
    ("宿題",       "宿題!A1:F1000"),
    ("決定事項",   "決定事項!A1:C1000"),
    ("施策",       "施策!A1:D1000"),
    ("担当マスタ", "担当マスタ!A1:C1000"),
]


def _post_token(data):
    """トークンエンドポイントに POST して JSON を返す。エラー文にトークンは出さない。"""
    req = Request(TOKEN_URL, data=urlencode(data).encode(), method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        try:
            body = json.loads(e.read())
            err = f"{body.get('error', '')} {body.get('error_description', '')}".strip()
        except Exception:
            err = ""
        raise OpsError(f"アクセストークンの取得に失敗しました（HTTP {e.code} {err}）")
    except URLError as e:
        raise OpsError(f"oauth2.googleapis.com に到達できません: {e.reason}")


def _token_from_service_account():
    """サービスアカウントの鍵からアクセストークンを取る（推奨経路）。

    鍵は個人ではなくプロジェクトに属するので、担当者が変わっても失効しない。
    ⚠ 鍵の中身（private_key）はログにも例外文にも出さないこと。
    """
    raw = (os.environ.get("SHEETS_SA_KEY") or "").strip()
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        raise OpsError("SHEETS_SA_KEY が JSON として読めません。"
                       "鍵ファイルの中身を丸ごと（{ から } まで）貼ってください")
    for k in ("client_email", "private_key", "token_uri"):
        if not info.get(k):
            raise OpsError(f"SHEETS_SA_KEY に {k} がありません。鍵ファイルの JSON をそのまま貼ってください")
    try:
        from google.auth import crypt
        from google.auth import jwt as google_jwt
    except ImportError:
        raise OpsError("google-auth が入っていません。"
                       "daily_fetch.yml の pip install ステップを確認してください")

    now = int(time.time())
    assertion = google_jwt.encode(crypt.RSASigner.from_service_account_info(info), {
        "iss":   info["client_email"],
        "scope": SCOPE,
        "aud":   info["token_uri"],
        "iat":   now,
        "exp":   now + 3600,
    })
    if isinstance(assertion, bytes):
        assertion = assertion.decode()

    body = _post_token({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion":  assertion,
    })
    tok = body.get("access_token")
    if not tok:
        raise OpsError("アクセストークンが返ってきませんでした（サービスアカウント）")
    # SA のレスポンスに scope は入らない。要求スコープは assertion 側で固定済み。
    print(f"  認証: サービスアカウント（{info['client_email']}）")
    return tok


def get_access_token():
    """スプレッドシート読み取り用のアクセストークンを取る。

    ① SHEETS_SA_KEY があればサービスアカウント方式（推奨）
    ② 無ければ従来のリフレッシュトークン方式にフォールバック
    ③ どちらも無ければ None（呼び出し側でスキップ）

    ⚠ `fetch.py` の OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET は **別アカウントの GCP プロジェクト**
    にあり、スプレッドシートの権限を持たない（引き継ぎ書 §10 の調査結果）。
    そのため ② では **SHEETS_CLIENT_ID / SHEETS_CLIENT_SECRET を優先**する。
    """
    tok = _token_from_service_account()
    if tok:
        return tok

    rt = os.environ.get("SHEETS_REFRESH_TOKEN")
    cid = os.environ.get("SHEETS_CLIENT_ID")    or os.environ.get("OAUTH_CLIENT_ID")
    cs  = os.environ.get("SHEETS_CLIENT_SECRET") or os.environ.get("OAUTH_CLIENT_SECRET")
    if not rt:
        return None  # 未設定 → 呼び出し側でスキップ
    if not (cid and cs):
        raise OpsError("SHEETS_CLIENT_ID / SHEETS_CLIENT_SECRET が設定されていません"
                       "（OAUTH_* でも代用できますが、スプレッドシートの権限が無い想定です）")
    body = _post_token({
        "client_id": cid, "client_secret": cs,
        "refresh_token": rt, "grant_type": "refresh_token",
    })
    tok = body.get("access_token")
    if not tok:
        raise OpsError("アクセストークンが返ってきませんでした。"
                       "SHEETS_REFRESH_TOKEN が失効している可能性があります"
                       "（同意画面が「テスト」状態だと7日で失効します）")
    scope = body.get("scope", "")
    if "spreadsheets" not in scope:
        raise OpsError(f"このトークンにスプレッドシートの権限がありません（scope: {scope}）")
    print("  認証: リフレッシュトークン（旧方式）")
    return tok


def fetch_sheets(token):
    qs = "&".join("ranges=" + quote(r, safe="") for _, r in RANGES)
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
           f"/values:batchGet?{qs}&valueRenderOption=FORMATTED_VALUE")
    req = Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
    except HTTPError as e:
        hint = ""
        if e.code == 403:
            hint = "（このアカウントに閲覧権限があるか確認してください）"
        elif e.code == 404:
            hint = "（スプレッドシートIDが違う可能性があります）"
        raise OpsError(f"スプレッドシートの読み取りに失敗しました（HTTP {e.code}）{hint}")
    except URLError as e:
        raise OpsError(f"sheets.googleapis.com に到達できません: {e.reason}")

    vrs = body.get("valueRanges", [])
    if len(vrs) != len(RANGES):
        raise OpsError(f"取得できた範囲の数が合いません（期待 {len(RANGES)} / 実際 {len(vrs)}）")

    sheets = {}
    for (name, _), vr in zip(RANGES, vrs):
        rows = vr.get("values", [])
        rows = [[norm(c) for c in r] for r in rows]
        rows = [r for r in rows if any(r)]
        if not rows:
            raise OpsError(f"[{name}] シートが空です")
        head = rows[0]
        # 末尾の空セルは省略されて返るので、行の長さをヘッダに合わせる
        sheets[name] = [
            {h: (r[i] if i < len(r) else "") for i, h in enumerate(head) if h}
            for r in rows[1:]
        ]
    return sheets


def main():
    try:
        token = get_access_token()
        if token is None:
            print("[SKIP] SHEETS_SA_KEY / SHEETS_REFRESH_TOKEN のどちらも未設定です。"
                  "ops.json は更新しません。")
            return 0
        sheets = fetch_sheets(token)
        ops, warnings = build_ops(sheets)
    except OpsError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        print("ops.json は書き換えていません。", file=sys.stderr)
        return 1

    # 中身が同じなら書かない（無駄なコミットを増やさない）
    old = None
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, "r", encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = None
    if old is not None:
        a = {k: v for k, v in old.items() if k != "updated_at"}
        b = {k: v for k, v in ops.items() if k != "updated_at"}
        if a == b:
            print("運営ログに変更はありません（ops.json はそのまま）")
            report(ops, warnings, OUTPUT)
            return 0

    write_ops(ops, OUTPUT)
    print("運営ログを反映しました。")
    report(ops, warnings, OUTPUT)
    if warnings:
        print("⚠ 警告があります。担当マスタの更新漏れか、社外名の混入を確認してください。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
