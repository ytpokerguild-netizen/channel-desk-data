#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify_archive_input.py — 動画アーカイブに行が増えたら、企画タイプ／ナレーターの入力を LINE で頼む

なぜ要るか:
  企画タイプとナレーターは**人が手で入れるしかない列**です。入れ忘れると
  企画タイプ別・ナレーター別の集計から**黙って抜けます**（画面は普通に出るので気づけない）。
  増えたその日に頼むのがいちばん忘れません（2026-08-14 運営者の依頼）。

★ 2026-08-18 変更: 判定を「YouTube に動画が増えた」→「動画アーカイブに行が増えた」にしました。
  行そのものは Apps Script（投稿計画表にバウンド、`syncArchiveFromData`）が1時間おきに足します。
  YouTube 側で判定していたころは、**行がまだ無いのに「入れてください」と頼む**ことがあり、
  頼まれた人が開いても入れる場所がありませんでした。行が出てから頼めば、必ず入れられます。

  ⚠⚠ **この変更で、`syncArchiveFromData` が止まるとこの通知は永久に黙ります。**
    行が増えないので「増えた0本」が常に成立するためです。**しかもエラーになりません。**
    **見張りは朝ブリーフの「⏳ まだ行が無い N本」だけです**（`morning_brief.py`）。
    **片方だけ元に戻さないでください。** 戻すなら両方です。

使い方（daily_fetch.yml から）:
    python notify_archive_input.py

  ⚠ **data.json をコミットする前に**実行してください。
    「前回の動画アーカイブ」を `git show HEAD:data.json` から読んでいるので、
    コミット後に走らせると増分が0本になり、永久に何も送らなくなります。

送らない条件（どれも正常終了）:
  * 動画アーカイブに増えた行が1つも無い
  * 前回の data.json が読めない（初回・履歴なし）→ **全部を新規と誤認しないため何もしない**
  * LINE_CHANNEL_TOKEN / LINE_GROUP_ID が未設定 → line_notify 側でスキップ
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


def count_recent(data):
    """直近 RECENT_DAYS の動画を2つに分けて数える。

    ⚠ **この数え方は `morning_brief.py` にも同じものが書いてあります。
      片方だけ変えると本数が食い違い、どちらが正しいか分からなくなります。**

    戻り値 (empty, norow):
      empty : 動画アーカイブに**行はあるが**、企画タイプ／ナレーターが空 → **人が入れる**
      norow : 動画アーカイブに**行がまだ無い** → **syncArchiveFromData 待ち。人には入れられない**

    この2つは原因も打ち手も別です。混ぜて1つの数字にすると、
    「入れてください」と頼まれた人が開いても入れる場所が無い、が起きます。
    """
    archive = data.get("video_archive") or {}
    limit = (date.today() - timedelta(days=RECENT_DAYS)).isoformat()
    empty = norow = 0
    for v in data.get("videos", []):
        pub = (v.get("published_at") or "")[:10]
        if pub and pub < limit:
            continue
        vid = v.get("video_id")
        if vid not in archive:
            norow += 1
        elif not _filled(archive, vid):
            empty += 1
    return empty, norow


def build_message(new_rows, titles, empty):
    lines = [f"🎬 動画アーカイブに {len(new_rows)}行 増えました。",
             "投稿計画表の「動画アーカイブ」タブに、"
             "企画タイプとナレーターの入力をお願いします。", ""]
    for vid in new_rows[:MAX_LIST]:
        pub, title = titles.get(vid, ("", vid))
        pub = pub[:10].replace("-", "/")[5:]
        lines.append(f"・{pub} {title[:36]}".rstrip())
    if len(new_rows) > MAX_LIST:
        lines.append(f"・ほか{len(new_rows) - MAX_LIST}行")
    lines.append("")
    if empty:
        lines.append(f"未入力は全部で {empty}本 です（直近{RECENT_DAYS}日）。")
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

    # ★ 判定は「動画アーカイブの行」で行う（2026-08-18 変更。上の docstring を読むこと）。
    #   ⚠ videos（YouTube側）で判定しないこと。行が無いのに入力を頼むことになります。
    prev_rows = set(prev.get("video_archive") or {})
    cur_rows  = cur.get("video_archive") or {}
    new_rows  = [vid for vid in cur_rows if vid not in prev_rows]
    if not new_rows:
        print("動画アーカイブに増えた行はありません")
        return 0

    # タイトルと公開日は videos 側から引く（動画アーカイブは type/narrator しか持っていない）
    titles = {v.get("video_id"): ((v.get("published_at") or ""), (v.get("title") or ""))
              for v in cur.get("videos", [])}
    # 公開が新しい順に並べる（本文の見た目のため。判定には使っていない）
    new_rows.sort(key=lambda vid: titles.get(vid, ("", ""))[0], reverse=True)

    empty, _norow = count_recent(cur)
    msg = build_message(new_rows, titles, empty)
    print(msg)
    try:
        from line_notify import send_line
        send_line(msg)
    except Exception as e:
        print(f"[WARN] LINE 通知に失敗しました: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
