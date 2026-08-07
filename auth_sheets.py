#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スプレッドシート読み取り専用のリフレッシュトークンを取得する（1回だけ実行）

GitHub Actions が「PG運営ログ（非公開）」を読めるようにするためのものです。
**既存の REFRESH_TOKEN（YouTube用）には一切触りません。** 別のトークンを新しく作ります。

━━ 使い方 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. このファイルを client_secret.json と同じフォルダに置いて実行する

         python3 auth_sheets.py

  2. 表示された URL をブラウザで開き、**運営ログのオーナーのアカウント
     （korekiite@gmail.com）** でログインして許可する
     ※「確認されていないアプリ」と出たら「詳細」→「安全ではないページに移動」で進む

  3. 完了すると sheets_refresh_token.txt が作られます。中の文字列をコピーして、
     GitHub の Secrets に登録してください

         https://github.com/ytpokerguild-netizen/channel-desk-data/settings/secrets/actions
         → New repository secret
         Name:   SHEETS_REFRESH_TOKEN
         Secret: （コピーした文字列）

  4. 登録できたら sheets_refresh_token.txt は削除してください
     （.gitignore に入れてあるのでコミットはされません）

━━ 補足 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  * 要求する権限は spreadsheets.readonly（読み取り）だけです。書き込みはできません
  * スプレッドシートの共有設定は変えなくて構いません。自分のシートを自分で読むだけです
  * 標準ライブラリだけで動きます（pip install は不要）
"""
import http.server
import json
import os
import socketserver
import sys
import threading
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
PORT = 8765                      # auth.py と同じポート（OAuthクライアントに登録済みのはず）
REDIRECT = f"http://localhost:{PORT}/"
OUT = "sheets_refresh_token.txt"

_code = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _code["code"] = (q.get("code") or [None])[0]
        _code["error"] = (q.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("<h2>完了しました</h2><p>このタブを閉じて、ターミナルに戻ってください。</p>"
               if _code["code"] else
               f"<h2>失敗しました</h2><p>{_code.get('error') or '不明なエラー'}</p>")
        self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'>{msg}</body></html>".encode())

    def log_message(self, *a):
        pass


def main():
    if not os.path.exists("client_secret.json"):
        sys.exit("client_secret.json が見つかりません。\n"
                 "このスクリプトは client_secret.json と同じフォルダで実行してください。")
    with open("client_secret.json", encoding="utf-8") as f:
        cfg = json.load(f)
    info = cfg.get("installed") or cfg.get("web") or {}
    client_id, client_secret = info.get("client_id"), info.get("client_secret")
    if not (client_id and client_secret):
        sys.exit("client_secret.json の形式が想定と違います（client_id / client_secret が読めません）")

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",       # 必ず refresh_token を返させる
    })

    print("\n" + "=" * 70)
    print("下の URL をブラウザで開いて、korekiite@gmail.com で許可してください。")
    print("=" * 70)
    print(auth_url)
    print("=" * 70 + "\n待っています…（Ctrl+C で中止）\n")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("localhost", PORT), Handler) as httpd:
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            while "code" not in _code and "error" not in _code:
                threading.Event().wait(0.3)
        except KeyboardInterrupt:
            sys.exit("\n中止しました。")
        httpd.shutdown()

    if not _code.get("code"):
        sys.exit(f"認証が拒否されました: {_code.get('error')}")

    data = urllib.parse.urlencode({
        "code": _code["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tok = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"トークン交換に失敗しました（HTTP {e.code}）: {e.read().decode(errors='replace')[:300]}")

    rt = tok.get("refresh_token")
    if not rt:
        sys.exit("refresh_token が返ってきませんでした。ブラウザで一度権限を取り消してから再実行してください:\n"
                 "  https://myaccount.google.com/permissions")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(rt)
    os.chmod(OUT, 0o600)

    print("成功しました。")
    print(f"  スコープ: {tok.get('scope')}")
    print(f"  保存先:   {os.path.abspath(OUT)}")
    print("\n次にやること")
    print("  1. 上のファイルを開いて中の文字列をコピー")
    print("  2. https://github.com/ytpokerguild-netizen/channel-desk-data/settings/secrets/actions")
    print("     → New repository secret / Name: SHEETS_REFRESH_TOKEN")
    print("  3. 登録できたら sheets_refresh_token.txt を削除")


if __name__ == "__main__":
    main()
