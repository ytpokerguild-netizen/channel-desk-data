#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""週次AI分析が運用手順 §7 の形を守っているか確かめる（GitHub Actions 用）

なぜ要るか:
  このプロジェクトは、書類の更新漏れ・データの鮮度・シートが読めない・未入力を
  すべて自動で見張っています。**週次AI分析の中身だけ、誰も数えていませんでした。**
  その結果、運用手順 §7 が「本文 400〜700字程度」と決めていたのに、
  2026-08-08 週で 2,586字（3.7倍）まで伸びていたことに、公開するまで誰も気づけませんでした。
  7月まで7週連続で守れていたので、**実績があっても人は気づけない**という例です。

  さらに調べたところ、**当時 9週すべてが §7 のどこかに違反**していました。
  6週は `headline` が無く（ダッシュボード最上部のバナーとPDFの結論欄が空）、
  2週は字数超過でした。1つも合っていなかったのに、通知は1度も出ていません。

見るもの（運用手順 §7）:
  * 本文が長すぎないか        … 400〜700字程度。余裕を見て 760字で警告する
  * `headline` があるか       … **必須**。ダッシュボード最上部のバナーに出る
  * `suggestions` の形        … `{title, actions}`。文字列の配列は旧式
  * 本文に ⚠ の注記が無いか   … 2026-08-17 オーナーの指示。注記は運用手順 §3 に置く
  * 確定状況の一文が無いか    … 「7日分すべて確定した確定値。」等。バッジと重複する

使い方:
    python check_report_format.py          # 表示するだけ。違反があれば終了コード 1
    python check_report_format.py notify    # LINE にも通知する。終了コードは常に 0

  LINE_CHANNEL_TOKEN / LINE_GROUP_ID が未設定なら表示だけして正常終了します
  （他のアカウントで動かしても壊れない）。

⚠ この検査は「形」しか見ません。中身が正しいかは人が読むしかありません。
"""
import json
import sys

DATA_FILE = "data.json"

BODY_MIN = 400      # §7 の下限
BODY_MAX = 700      # §7 の上限
# §7 は「400〜700字**程度**」なので、上下に1割弱の幅を見てから警告する。
# ⚠ この幅を広げないこと。広げるほど「守れているのに気づけない」状態に戻ります。
BODY_WARN_OVER  = 760
BODY_WARN_UNDER = 350

# 本文の冒頭に書かない言い回し。レポート上部のバッジと重複する（2026-08-17 運営者の指示）
STATUS_PHRASES = ("確定した確定値", "分すべて確定", "まだ確定していません", "速報値です")


def load_weeks():
    with open(DATA_FILE, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("weekly_reports", [])


def check_week(w):
    """1週ぶんを見て、違反の一覧を返す（空なら準拠）"""
    a = w.get("ai_analysis")
    if not a:
        # 分析がまだ無いのは違反ではない（確定待ち・未分析はバナー側の仕事）
        return []
    out = []
    body = a.get("analysis") or ""
    if len(body) > BODY_WARN_OVER:
        out.append(f"本文が{len(body)}字（上限{BODY_MAX}字の{len(body)/BODY_MAX:.1f}倍）")
    elif len(body) < BODY_WARN_UNDER:
        out.append(f"本文が{len(body)}字（下限{BODY_MIN}字に届いていない）")
    if not (a.get("headline") or "").strip():
        out.append("headline が無い（バナーとPDFの結論欄が空になる）")
    sug = a.get("suggestions") or []
    if not sug:
        out.append("suggestions が無い")
    elif any(not isinstance(s, dict) for s in sug):
        out.append("suggestions が旧式（文字列の配列）。{title, actions} に直す")
    if "⚠" in body:
        out.append("本文に ⚠ の注記が入っている（注記は運用手順 §3 に置く）")
    head = body[:60]
    for p in STATUS_PHRASES:
        if p in head:
            out.append(f"冒頭に確定状況の一文がある（「{p}」）。上部のバッジと重複する")
            break
    return out


def notify(msg):
    print(msg)
    try:
        from line_notify import send_line
        send_line(msg)
    except Exception as e:
        print(f"[WARN] LINE 通知に失敗しました: {e}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        weeks = load_weeks()
    except Exception as e:
        print(f"[SKIP] {DATA_FILE} を読めません: {e}")
        return 0

    bad = []
    checked = 0
    for w in weeks:
        if not w.get("ai_analysis"):
            continue
        checked += 1
        probs = check_week(w)
        if probs:
            bad.append((w["week_start"], probs))

    if not bad:
        print(f"[OK] 週次AI分析は運用手順 §7 の形を守っています（{checked}週を確認）")
        return 0

    print(f"[NG] {len(bad)} / {checked} 週が運用手順 §7 に違反しています")
    for ws, probs in bad:
        for p in probs:
            print(f"  {ws}  {p}")

    if mode == "notify":
        lines = "\n".join(f"・{ws} {probs[0]}" for ws, probs in bad[:4])
        more = f"\nほか {len(bad) - 4} 週" if len(bad) > 4 else ""
        notify(f"📐 CHANNEL DESK: 週次AI分析が運用手順 §7 の形から外れています（{len(bad)}/{checked}週）。\n"
               f"{lines}{more}\n"
               "直し方は チャンネル分析AI_運用手順.md §7 を見てください。")
        return 0     # 通知が目的。データ更新を失敗扱いにしない
    return 1


if __name__ == "__main__":
    sys.exit(main())
