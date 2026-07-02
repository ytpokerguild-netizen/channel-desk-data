#!/usr/bin/env python3
"""OAuth 再認証スクリプト（Claude 連携版）
- ブラウザを自動で開かず、認証URLを auth_url.txt に書き出す（Claude が開いて操作）
- 認証完了後、トークンが指すチャンネルを自動検証
- りいポーカーチャンネル（UCnGhx...）なら token.json を保存して終了
- 別チャンネルなら新しいURLを書き出して再試行
"""
import json, http.server, urllib.parse, urllib.request
from google_auth_oauthlib.flow import Flow

TARGET = "UCnGhxFzP6V4TczZCs63rXgQ"
SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly",
          "https://www.googleapis.com/auth/youtube.readonly"]
PORT = 8765

def verify(creds):
    req = urllib.request.Request(
        "https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true",
        headers={"Authorization": "Bearer " + creds.token})
    res = json.load(urllib.request.urlopen(req))
    items = res.get("items", [])
    if not items:
        return None, "チャンネル取得失敗", ""
    it = items[0]
    return it["id"], it["snippet"]["title"], it["statistics"].get("subscriberCount", "?")

for attempt in range(1, 6):
    flow = Flow.from_client_secrets_file(
        "client_secret.json", scopes=SCOPES,
        redirect_uri=f"http://localhost:{PORT}/")
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    with open("auth_url.txt", "w") as f:
        f.write(auth_url)
    print(f"[試行{attempt}] 認証URLを auth_url.txt に書き出しました。ブラウザでの認証を待っています...")

    code_holder = {}
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code_holder["code"] = q.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("認証を受け付けました。このタブは閉じてOKです。".encode())
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("localhost", PORT), H)
    srv.handle_request()
    srv.server_close()
    if not code_holder.get("code"):
        print("認証コードが取得できませんでした。再試行します。")
        continue

    flow.fetch_token(code=code_holder["code"])
    creds = flow.credentials
    cid, title, subs = verify(creds)
    print(f"このトークンが指すチャンネル: {cid} / {title} / 登録者: {subs}")

    if cid == TARGET:
        with open("token.json", "w") as f:
            json.dump({
                "token":         creds.token,
                "refresh_token": creds.refresh_token,
                "client_id":     creds.client_id,
                "client_secret": creds.client_secret,
                "expiry":        creds.expiry.isoformat() if creds.expiry else None,
            }, f, indent=2)
        with open("auth_result.txt", "w") as f:
            f.write(f"OK {cid} {title} subs={subs}")
        print("正しいチャンネルです。token.json を保存しました。完了。")
        break
    else:
        with open("auth_result.txt", "w") as f:
            f.write(f"NG {cid} {title} subs={subs}")
        print("別チャンネルでした。新しいURLで再試行します。")
else:
    print("5回試行しましたが正しいチャンネルに到達できませんでした。")
