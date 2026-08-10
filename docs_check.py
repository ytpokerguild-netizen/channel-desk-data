#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引き継ぎ書類の更新漏れを検出する（GitHub Actions 用）

引き継ぎ書類の**正本は Dropbox**にあり、GitHub からは見えません。
そこで「変更履歴.md」を機械が読める代わりの印として使い、次の2つを見ます。

  push     人の手でコードを変えた push なのに 変更履歴.md が更新されていない
  pending  変更履歴.md に「未反映」の行が残っている（Dropbox 側の更新漏れ）

使い方:
    python docs_check.py push      # 環境変数 BEFORE / AFTER を使う（docs_guard.yml から）
    python docs_check.py pending   # 変更履歴.md を読むだけ（daily_fetch.yml から）

どちらも LINE_CHANNEL_TOKEN / LINE_GROUP_ID があれば LINE に通知します。
未設定なら表示だけして正常終了します（他のアカウントで動かしても壊れない）。

終了コード:
    push    … 漏れがあれば 1（Actions を赤くして気づけるようにする）
    pending … 常に 0（通知が目的。データ更新を失敗扱いにしない）
"""
import os
import re
import subprocess
import sys

CHANGELOG = "変更履歴.md"

# 自動生成ファイル。これだけの変更なら履歴を書かなくてよい
AUTO_FILES = {
    "data.json",        # fetch.py が3時間おきに書く
    "video_daily.json", # 同上
    "ops.json",         # fetch_ops.py が運営ログから作る
    "trigger.txt",      # 即時更新の合図
}

BOT_MAILS = {"github-actions[bot]@users.noreply.github.com"}
ZERO = "0" * 40


def git(*args):
    # core.quotepath=false … 日本語のファイル名を \345\244… にエスケープさせない
    # （「変更履歴.md」を見つけられなくなるため。ここを外すと必ず壊れる）
    return subprocess.run(["git", "-c", "core.quotepath=false", *args],
                          capture_output=True, text=True).stdout.strip()


def notify(text):
    print(text)
    try:
        from line_notify import send_line
        send_line(text)
    except Exception as e:  # LINE が落ちていてもチェック結果は残す
        print(f"[WARN] LINE 通知に失敗しました: {e}")


# ──────────────────────────────────────────────────────────
def check_push():
    before, after = os.environ.get("BEFORE", ""), os.environ.get("AFTER", "HEAD")
    if not before or before == ZERO:
        before = after + "~1"
    rng = f"{before}..{after}"
    if git("rev-parse", "--verify", "--quiet", before) == "":
        print(f"[SKIP] 比較元 {before} が見つかりません")
        return 0

    mails = [m for m in git("log", "--format=%ae", rng).splitlines() if m]
    if mails and all(m in BOT_MAILS for m in mails):
        print("[SKIP] 自動コミットのみです")
        return 0

    changed = [f for f in git("diff", "--name-only", rng).splitlines() if f]
    if not changed:
        print("[SKIP] 変更ファイルがありません")
        return 0
    code = [f for f in changed if f not in AUTO_FILES]
    print("変更されたファイル: " + " / ".join(changed))
    if not code:
        print("[OK] 自動生成ファイルだけの変更です")
        return 0
    if CHANGELOG in changed:
        print(f"[OK] {CHANGELOG} も同じ push で更新されています")
        return 0

    notify("⚠️ CHANNEL DESK: コードを変更した push で 変更履歴.md が更新されていません。\n"
           "変更: " + " / ".join(code[:6]) + ("…" if len(code) > 6 else "") + "\n"
           "変更履歴.md に1行足して、Dropbox の引き継ぎ書類も直してください。\n"
           "https://github.com/ytpokerguild-netizen/channel-desk-data/blob/main/%E5%A4%89%E6%9B%B4%E5%B1%A5%E6%AD%B4.md")
    return 1


# ──────────────────────────────────────────────────────────
def pending_rows():
    """変更履歴.md の表から「反映」列が未反映の行を拾う"""
    if not os.path.exists(CHANGELOG):
        return None
    out = []
    with open(CHANGELOG, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 4 or all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                continue
            if cells[0] in ("日付", ""):
                continue
            if "未" in cells[3]:
                out.append((cells[0], cells[1]))
    return out


def check_pending():
    rows = pending_rows()
    if rows is None:
        print(f"[SKIP] {CHANGELOG} がありません")
        return 0
    if not rows:
        print("[OK] 引き継ぎ書類の反映漏れはありません")
        return 0
    lines = "\n".join(f"・{d} {t}" for d, t in rows[:5])
    more = f"\nほか {len(rows) - 5} 件" if len(rows) > 5 else ""
    notify(f"📝 CHANNEL DESK: 引き継ぎ書類に反映していない変更が {len(rows)} 件あります。\n{lines}{more}\n"
           "Dropbox の引き継ぎ書類を直したら、変更履歴.md の「反映」列を 済 にしてください。")
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "push":
        return check_push()
    if mode == "pending":
        return check_pending()
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
