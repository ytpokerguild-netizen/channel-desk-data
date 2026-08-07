#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""運営ログ（非公開スプレッドシート）→ ops.json を自動生成する（GitHub Actions 用）

3時間おきの daily_fetch から呼ばれる。スプレッドシートを直せば、依頼しなくても
最大3時間でダッシュボードに反映される。

必要な環境変数（GitHub Secrets）:
    SHEETS_REFRESH_TOKEN   スプレッドシート読み取り専用のリフレッシュトークン
    OAUTH_CLIENT_ID        既存のものを流用
    OAUTH_CLIENT_SECRET    既存のものを流用

設計の要点:
  * **既存の REFRESH_TOKEN（YouTube用）には一切触らない。** 別トークン・別Secretにしている。
    こちらが壊れても日次のデータ更新は止まらない。
  * SHEETS_REFRESH_TOKEN が無いときは「未設定」と表示して**正常終了**する（導入前でも失敗にしない）。
  * 読み取りや検証に失敗した場合は **ops.json を書き換えずに** 異常終了する。
    シートを壊してしまったときに、公開側の中身が消えたり漏れたりしないようにするため。
  * 公開判断（公開列のフィルタ・実名の置換）は build_ops_json.py の関数をそのまま使う。
    ロジックを二重に持たない。
  * Python 標準ライブラリのみ（fetch.py と同じ方針）。
"""
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from build_ops_json import OpsError, build_ops, norm, report, write_ops

SPREADSHEET_ID = "1v--hBNlRU431gr-4DX4fm9L1Xr6w28-Hv93ufo-w-wo"  # PG運営ログ（非公開）
OUTPUT = "ops.json"

# 取りに行くシートと範囲。範囲は余裕を持たせる（行が増えても取り漏らさないように）
RANGES = [
    ("宿題",       "宿題!A1:F1000"),
    ("決定事項",   "決定事項!A1:C1000"),
    ("施策",       "施策!A1:D1000"),
    ("担当マスタ", "担当マスタ!A1:C1000"),
]


def get_access_token():
    rt = os.environ.get("SHEETS_REFRESH_TOKEN")
    cid = os.environ.get("OAUTH_CLIENT_ID")
    cs = os.environ.get("OAUTH_CLIENT_SECRET")
    if not rt:
        return None  # 未設定 → 呼び出し側でスキップ
    if not (cid and cs):
        raise OpsError("OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET が設定されていません")
    data = urlencode({
        "client_id": cid, "client_secret": cs,
        "refresh_token": rt, "grant_type": "refresh_token",
    }).encode()
    req = Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
    except HTTPError as e:
        # エラー本文にトークンは含まれないが、念のため要点だけ出す
        try:
            err = json.loads(e.read()).get("error", "")
        except Exception:
            err = ""
        raise OpsError(f"アクセストークンの取得に失敗しました（HTTP {e.code} {err}）。"
                       "SHEETS_REFRESH_TOKEN が失効している可能性があります")
    except URLError as e:
        raise OpsError(f"oauth2.googleapis.com に到達できません: {e.reason}")
    tok = body.get("access_token")
    if not tok:
        raise OpsError("アクセストークンが返ってきませんでした")
    scope = body.get("scope", "")
    if "spreadsheets" not in scope:
        raise OpsError(f"このトークンにスプレッドシートの権限がありません（scope: {scope}）")
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
            print("[SKIP] SHEETS_REFRESH_TOKEN が未設定です。ops.json は更新しません。")
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
