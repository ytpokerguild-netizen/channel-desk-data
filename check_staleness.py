#!/usr/bin/env python3
"""
check_staleness.py — data.json の meta.fetched_at を検査し、
一定時間を超えて更新されていなければ LINE 通知する。

★ 2026-08-28 に置き場所と閾値を変えました。触る前に読んでください。

⚠⚠ **このスクリプトを daily_fetch.yml の中に戻さないこと。**
  2026-08-28 まで、これは daily_fetch.yml の「取得が成功したあと」のステップから呼ばれていました。
  **その位置では原理的に鳴りません。**取得が成功した直後は fetched_at が0時間前だからです。
  毎回 `[OK] データ鮮度 正常（0.0時間前）` を出すだけで、1度も通知したことがありませんでした。
  しかも `if: success()` が付いていたので、取得が動かなければステップごと実行されません。
  **いちばん知りたい「取得が止まった」ときに、いちばん確実に黙る**作りでした。
  2026-08-28 に取得が9時間止まったとき、誰にも知らされず運営者が自分で気づきました。
  → いまは `staleness_guard.yml`（取得とは独立したワークフロー）から呼んでいます。

⚠ 閾値を24時間に戻さないこと。取得は3時間おきなので、24時間は「8回連続で飛んだ」状態です。
  上の事故（9時間）は24時間では鳴りませんでした。既定を **8時間**（＝2回以上連続で飛んだ状態）に
  下げてあります。環境変数 STALE_HOURS で上書きできます。
⚠ 逆に短くしすぎないこと。GitHub の schedule はふだんでも 0.5時間ほど遅れます。

引数 --file <path> で対象を切り替え可能（省略時は ./data.json）。
"""
import os, sys, json
from datetime import datetime, timezone
from line_notify import send_line

DASH = "https://ytpokerguild-netizen.github.io/channel-desk-data/"
STALE_HOURS = float(os.environ.get("STALE_HOURS") or 8)


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
        # ⚠ 金額は書かないこと（LINE通知の決まり）。
        # ★ 「失敗した」ではなく「動いていない」と書いています。2026-08-28 の事故では
        #   411回すべて success で、実行そのものが発火していませんでした。
        #   「失敗を探してください」と書くと、成功ログを見て「異常なし」と判断してしまいます。
        send_line(
            f"⚠️ CHANNEL DESK: データが約{int(hrs)}時間更新されていません"
            f"（3時間おきの予定に対して{int(hrs//3)}回ぶん）。\n"
            f"最終取得: {fa[:16].replace('T', ' ')} UTC\n"
            f"まず Actions の Daily YouTube Analytics Fetch を見てください。"
            f"**失敗ではなく「実行そのものが無い」ことがあります。**\n"
            f"手動実行（Run workflow）で追いつかせられます。\n{DASH}"
        )
        print(f"[NG] データが {hrs:.1f}時間前のままです（閾値 {STALE_HOURS}時間）")
    else:
        print(f"[OK] データ鮮度 正常（{hrs:.1f}時間前 / 閾値 {STALE_HOURS}時間）")


if __name__ == "__main__":
    main()
