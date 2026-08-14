#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify_archive_input.py — 新しい動画が増えたら、企画タイプ／ナレーターの入力を LINE で頼む

なぜ要るか:
  企画タイプとナレーターは**人が手で入れるしかない列**です。入れ忘れると
  企画タイプ別・ナレーター別の集計から**黙って抜けます**（画面は普通に出るので気づけない）。
  増えたその日に頼むのがいちばん忘れません（2026-08-14 運営者の依頼）。

使い方（daily_fetch.yml から）:
    python notify_archive_input.py

  ⚠ **data.json をコミットする前に**実行してください。
    「前回の動画一覧」を `git show HEAD:data.json` から読んでいるので、
    コミット後に走らせると新作が0本になり、永久に何も送らなくなります。

送らない条件（どれも正常終了）:
  * 新しい動画が1本も無い
  * 前回の data.json が読めない（初回・履歴なし）→ **全部を新作と誤認しないため何もしない**
  * LINE_CHANNEL_TOKEN / LINE_GROUP_ID が未設定 → line_notify 側でスキップ

⚠ 行そのものは Apps Script（投稿計画表にバウンド、`syncArchiveFromData`）が
  1時間おきに data.json を見て 動画アーカイブ に追加します。
  この通知のほうが先に届くことがあるので、本文でその旨を伝えています。
"""
import json
import subprocess
import sys
from datetime import date, datetime, timedelta

DATA_FILE = "data.json"

# 投稿計画表の「動画アーカイブ」タブ。
# ⚠ シートIDと gid は fetch.py の SPREADSHEET_ID / ARCHIVE_GID と同じものです。
#   差し替えるときは両方直してください。
ARCHIVE_URL = ("https://docs.google.com/spreadsheets/d/"
               "1Xqxx4vnKfQVQ_qEx8T3tpAA9_vD1uBfihdvWPfHVdmI/edit#gid=1927840516")

# 未入力の本数を数える対象期間。
# ⚠ 全期間で数えると 2022 年のテスト動画1本がずっと残り、毎回「未入力1本」と出てしまう。
#   古すぎるものは実務上もう埋めないので、直近ぶんだけ数える。
RECENT_DAYS = 180

MAX_LIST = 5   # 本文に並べる新作のタイトル数


def load_prev():
    """直前のコミットの data.json を読む。読めなければ None。"""
    try:
        r = subprocess.run(["git", "show", "HEAD:" + DATA_FILE],
                           capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout)
    except Exception as e:
        print(f"[WARN] 前回の {DATA_FILE} を読めません: {e}")
        return None


def _filled(archive, vid):
    """企画タイプとナレーターが**両方**入っていれば True"""
    a = archive.get(vid) or {}
    return bool((a.get("type") or "").strip()) and bool((a.get("narrator") or "").strip())


def missing_recent(data):
    """直近 RECENT_DAYS に公開されたもののうち、企画タイプ／ナレーターが未入力の動画"""
    archive = data.get("video_archive") or {}
    limit = (date.today() - timedelta(days=RECENT_DAYS)).isoformat()
    out = []
    for v in data.get("videos", []):
        pub = (v.get("published_at") or "")[:10]
        if pub and pub < limit:
            continue
        if not _filled(archive, v.get("video_id")):
            out.append(v)
    return out


def build_message(new_videos, missing):
    lines = [f"🎬 新しい動画が {len(new_videos)}本 増えました。",
             "投稿計画表の「動画アーカイブ」タブに、"
             "企画タイプとナレーターの入力をお願いします。", ""]
    for v in new_videos[:MAX_LIST]:
        pub = (v.get("published_at") or "")[:10].replace("-", "/")[5:]
        title = (v.get("title") or "")[:36]
        lines.append(f"・{pub} {title}")
    if len(new_videos) > MAX_LIST:
        lines.append(f"・ほか{len(new_videos) - MAX_LIST}本")
    lines.append("")
    if missing:
        lines.append(f"未入力は全部で {len(missing)}本 です（直近{RECENT_DAYS}日）。")
    lines.append("※ 行はスクリプトが1時間おきに自動で足します。"
                 "まだ出ていなければ少し待ってください。")
    lines.append("")
    lines.append(ARCHIVE_URL)
    return "\n".join(lines)


def main():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            cur = json.load(f)
    except Exception as e:
        print(f"[SKIP] {DATA_FILE} を読めません: {e}")
        return 0

    prev = load_prev()
    if prev is None:
        print("[SKIP] 前回の data.json が読めないので、今回は送りません")
        return 0

    prev_ids = {v.get("video_id") for v in prev.get("videos", [])}
    new_videos = [v for v in cur.get("videos", [])
                  if v.get("video_id") not in prev_ids]
    if not new_videos:
        print("新しい動画はありません")
        return 0

    # 公開が新しい順に並べる（本文の見た目のため。判定には使っていない）
    new_videos.sort(key=lambda v: (v.get("published_at") or ""), reverse=True)

    msg = build_message(new_videos, missing_recent(cur))
    print(msg)
    try:
        from line_notify import send_line
        send_line(msg)
    except Exception as e:
        print(f"[WARN] LINE 通知に失敗しました: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
