#!/usr/bin/env python3
"""
check_staleness.py — data.json の meta.fetched_at を検査し、
24時間を超えて更新されていなければ LINE 通知する。

既存ワークフロー（daily_fetch.yml）の成功後ステップから実行する想定。
引数 --file <path> で対象を切り替え可能（省略時は ./data.json）。
"""
import sys, json
from datetime import datetime, timezone
from line_notify import send_line

DASH = "https://ytpokerguild-netizen.github.io/channel-desk-data/"
STALE_HOURS = 24


def main():
    path = "data.json"
    if "--file" in sys.argv:
        path = sys.argv[sys.argv.index("--file") + 1]

    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"[WARN] {path} 読み込み失敗: {e}")
        return

    fa = d.get("meta", {}).get("fetched_at")
    if not fa:
        print("[WARN] meta.fetched_at がありません")
        return

    try:
        dt = datetime.fromisoformat(fa)
    except Exception:
        print(f"[WARN] fetched_at の解析失敗: {fa}")
        return

    hrs = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if hrs > STALE_HOURS:
        send_line(
            f"⚠️ CHANNEL DESK: データが約{int(hrs)}時間更新されていません。\n"
            f"（最終取得: {fa[:16].replace('T', ' ')} UTC）\n"
            f"自動更新パイプラインの確認をお願いします。\n{DASH}"
        )
    else:
        print(f"[OK] データ鮮度 正常（{hrs:.1f}時間前）")


if __name__ == "__main__":
    main()
