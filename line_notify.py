#!/usr/bin/env python3
"""
line_notify.py — LINE Messaging API 通知ユーティリティ（Python 標準ライブラリのみ）

環境変数:
  LINE_CHANNEL_TOKEN : チャネルアクセストークン（長期）
  LINE_GROUP_ID      : 送信先グループID。カンマ区切りで複数指定可（配列扱い）

使い方:
  python line_notify.py "メッセージ本文"
  echo "本文" | python line_notify.py

トークンやグループIDが未設定の場合は送信せずスキップ（CI を失敗させない）。
"""
import os, sys, json
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PUSH_URL = "https://api.line.me/v2/bot/message/push"


def group_ids():
    """LINE_GROUP_ID をカンマ区切りで分割して配列で返す（将来の複数送信先対応）。"""
    raw = os.environ.get("LINE_GROUP_ID", "")
    return [g.strip() for g in raw.split(",") if g.strip()]


def send_line(text):
    """全グループへ push message を送信。成功で True。未設定時はスキップして False。"""
    token = os.environ.get("LINE_CHANNEL_TOKEN")
    if not token:
        print("[SKIP] LINE_CHANNEL_TOKEN 未設定 — 送信スキップ")
        return False
    ids = group_ids()
    if not ids:
        print("[SKIP] LINE_GROUP_ID 未設定 — 送信スキップ")
        return False

    text = (text or "").strip()[:4900]  # LINE のテキスト上限 5000 に余裕
    ok = True
    for gid in ids:
        body = json.dumps({
            "to": gid,
            "messages": [{"type": "text", "text": text}],
        }).encode("utf-8")
        req = Request(PUSH_URL, data=body, headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        })
        try:
            with urlopen(req, timeout=20) as r:
                print(f"[OK] LINE送信 {gid[:8]}… status={r.status}")
        except HTTPError as e:
            print(f"[ERROR] LINE送信失敗 {gid[:8]}…: {e.code} {e.read().decode('utf-8', 'ignore')[:200]}")
            ok = False
        except Exception as e:
            print(f"[ERROR] LINE送信失敗 {gid[:8]}…: {e}")
            ok = False
    return ok


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    if msg and msg.strip():
        send_line(msg)
    else:
        print("[SKIP] メッセージ本文が空です")
