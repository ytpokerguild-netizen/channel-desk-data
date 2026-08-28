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

# §7 は「400〜700字程度」でしたが、2026-08-17 に**下限を 250字**へ下げました。
# 理由: オーナーの方針で「データを述べる文章を減らし、その分をチャートで見せる。
#       まとめと考察には文章を使う」に変わり、**数字が本文からチャートへ移った**ためです。
# ⚠ 上限は動かしていません。長いほうは相変わらず読まれません。
# ⚠ 下限を下げたぶん「考察が1つも無い」ケースを拾えなくなるので、
#   **中身が考察になっているかは人が読んでください。**この検査は形しか見ません。
BODY_MIN = 250      # §7 の下限（2026-08-17 に 400 から変更）
BODY_MAX = 700      # §7 の上限
BODY_WARN_OVER  = 760
BODY_WARN_UNDER = 220

# 本文の冒頭に書かない言い回し。レポート上部のバッジと重複する（2026-08-17 運営者の指示）
STATUS_PHRASES = ("確定した確定値", "分すべて確定", "まだ確定していません", "速報値です")

# ★ 2026-08-28 追加（外部レビュー4回目 §3）→ **同日 運営者の指示で「必須」をやめました。**
# `owner_decision` … 判断不要／要確認／要承認 の3つだけ。
#   ⚠⚠ **いまレポートのどこにも表示していません。**冒頭にあった「次週の確認／運用変更／
#     オーナー判断」の3行は、運営者の指示で削除しました（04 次週のアクションと内容が重複していた）。
#   したがってこの検査は **「入っていれば形を見る」だけ**で、**未設定は違反ではありません。**
#   ⚠ 表示を復活させないまま「必須」に戻さないこと。**誰も見ない項目のために LINE が鳴り続けます。**
#   もう一度冒頭に出すことになったら、そのときに必須へ戻してください。そのための基準:
#     判断不要 … 既存方針・承認済み予算内／外部への新しい約束なし／取り返しがつく／
#                オーナーが選ばないと進められない事項が無い
#     要確認   … 意見が欲しいが、回答を待たずに現行運用は継続できる。**確認事項は1つに絞る**
#     要承認   … 未承認の費用／契約・発注・採用・外注／本数や制作体制の大きな変更／
#                KPI・方針の変更／対外発表・スポンサーへの約束／元に戻しにくい変更
#                → **何を承認してほしいか・推奨案・費用または影響・いつまでに必要か** を必ず添える
#     集約: 要承認が1件でもあれば要承認 ＞ 要確認が1件以上なら要確認 ＞ それ以外は判断不要
OWNER_DECISIONS = ("判断不要", "要確認", "要承認")

# `suggestions[].kind` … 打ち手の種別。**この4つから増やさないこと**（同 §2）。
#   実行=制作/投稿/導線を実際に変える｜検証=継続するかを確かめる｜
#   分析=既存データを分解する｜計測整備=欠損・タグ・掲出日などを整える
#   ⚠ 「共有」「報告」「承認」は種別ではありません。owner_decision で扱います。
ACTION_KINDS = ("実行", "検証", "分析", "計測整備")


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
    else:
        # 種別は4つだけ。⚠ 推測で付けないこと（当たらない週が必ず出ます）
        bad_kinds = [s.get("kind") for s in sug
                     if s.get("kind") and s.get("kind") not in ACTION_KINDS]
        if bad_kinds:
            out.append(f"suggestions[].kind が範囲外（{'/'.join(map(str, bad_kinds))}）。"
                       f"使えるのは {'・'.join(ACTION_KINDS)} だけ")

    # ★ オーナー判断。⚠ **未設定は違反にしません**（いまレポートに表示していないため）。
    #   入っているときだけ、書き方が基準どおりかを見ます。
    od = (a.get("owner_decision") or "").strip()
    if not od:
        pass
    elif not od.startswith(OWNER_DECISIONS):
        out.append(f"owner_decision が「{od[:20]}」。"
                   f"{'／'.join(OWNER_DECISIONS)} のいずれかで書き始めてください")
    elif od.startswith("要承認") and len(od) < 20:
        # 要承認は「何を・推奨案・費用または影響・期限」を添える決まり
        out.append("owner_decision が要承認なのに説明が短い。"
                   "何を承認してほしいか／推奨案／費用または影響／いつまでに必要か を書いてください")
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
