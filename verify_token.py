#!/usr/bin/env python3
"""token.json がどのチャンネルを指しているか確認するスクリプト"""
import json, urllib.request, urllib.parse

t = json.load(open("token.json"))
data = urllib.parse.urlencode({
    "client_id": t["client_id"],
    "client_secret": t["client_secret"],
    "refresh_token": t["refresh_token"],
    "grant_type": "refresh_token",
}).encode()
tok = json.load(urllib.request.urlopen(
    urllib.request.Request("https://oauth2.googleapis.com/token", data=data)))["access_token"]

req = urllib.request.Request(
    "https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true",
    headers={"Authorization": "Bearer " + tok})
res = json.load(urllib.request.urlopen(req))
for it in res.get("items", []):
    ok = it["id"] == "UCnGhxFzP6V4TczZCs63rXgQ"
    print(("OK  " if ok else "NG  ") + it["id"], "/", it["snippet"]["title"],
          "/ 登録者:", it["statistics"].get("subscriberCount"))
if not res.get("items"):
    print("NG  チャンネルが取得できませんでした")
