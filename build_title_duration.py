#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""尺とタイトル文言が伸びに効くかを集計して title_duration.json を書きます。

    python3 build_title_duration.py --from 2026-05-01 --to 2026-11-30 --weeks 2026-11-02

⚠ この分析は 2026-11-06 の「サムネイルと尺の関係」の作り直しです。
  元版は **サムネイルの文言**（`thumb_text.json`・145本を目視で書き写したもの）を使っていましたが、
  そのファイルは失われ、サムネイル画像の取得経路（i.ytimg.com）も塞がれていて復元できません。
  **この版は data.json にある「タイトルの文言」で代用しています。サムネとタイトルは別物です。**
  結論の向きは元版と一致しましたが（下の「元版との対照」）、同じものを測ってはいません。

⚠ `weeks` に入れた週でしかページが出ません。週を足すときはここを足して流し直してください。
⚠ 倍率は「公開28日の視聴 ÷ 同じ公開月の中央値」です。**月内の相対位置しか見ていません。**
  月をまたいだ水準の比較には使えません。
"""
import json, re, math, argparse, statistics as st
from datetime import date, timedelta

# タイトルに出てくる文言の型。⚠ 増やすなら report.html の表の行も一緒に増やすこと。
PATTERNS = {
    "手札・役": r"(AA|KK|QQ|JJ|TT|AK|AQ|AJ|KQ|[2-9]{2}|クアッズ|フルハウス|ストレートフラッシュ|ストフラ"
                r"|スリーカード|ツーペア|フラッシュ|ストレート|セット|バッドビート|ロイヤル|ポケット|オーバーペア)",
    "人物名":   r"(ヨコサワ|ナーツ|アントニー|田中圭|たかし|日本人|プロ)",
    "金額":     r"(億|万円|\d+円|\$|ドル)",
    "問いかけ": r"(\？|\?|どうする|できる|降り|あなた)",
    "驚きの言葉": r"(まさか|ヤバ|エグ|史上|伝説|激レア|ありえない|最悪|奇跡|神|wwww|‼)",
    "大会名":   r"(WSOP|JOPT|Triton|EPT|WPT|SPADIE|GGMillion)",
}
# 尺の区分。⚠ 変えるなら report.html の注記も直すこと。
BANDS = [("〜45秒", 0, 45), ("46〜60秒", 46, 60), ("61〜90秒", 61, 90), ("91秒〜", 91, 10**9)]
# 交絡を外すときに落とす型。中身の違いが尺の差に化けるのを防ぎます（元版と同じ考え方）。
CONTROL_OFF = ["手札・役", "人物名", "大会名"]


def band_of(sec):
    for name, lo, hi in BANDS:
        if lo <= sec <= hi:
            return name
    return BANDS[-1][0]


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    rx = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: xs[i]))}
    ry = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: ys[i]))}
    a = [rx[i] for i in range(n)]
    b = [ry[i] for i in range(n)]
    ma, mb = st.mean(a), st.mean(b)
    num = sum((p - ma) * (q - mb) for p, q in zip(a, b))
    den = math.sqrt(sum((p - ma) ** 2 for p in a) * sum((q - mb) ** 2 for q in b))
    return round(num / den, 3) if den else None


def window_views(daily, pub, lo, hi):
    days = {(pub + timedelta(days=i)).isoformat() for i in range(lo, hi + 1)}
    return sum(r["views"] for r in daily if r["date"] in days)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--daily", default="video_daily.json")
    ap.add_argument("--out", default="title_duration.json")
    ap.add_argument("--from", dest="dfrom", default="2026-05-01")
    ap.add_argument("--to", dest="dto", default="2026-11-30")
    ap.add_argument("--weeks", nargs="*", default=[], help="このページを出す週（week_start）")
    a = ap.parse_args()

    data = json.load(open(a.data, encoding="utf-8"))
    vdaily = json.load(open(a.daily, encoding="utf-8"))
    last = max(r["date"] for rows in vdaily.values() for r in rows)

    rows = []
    skipped = {"日別データなし": 0, "28日未経過": 0, "尺が無い": 0}
    for v in data["videos"]:
        pub_s = v["published_at"][:10]
        if not (a.dfrom <= pub_s <= a.dto):
            continue
        vid = v["video_id"]
        if vid not in vdaily:
            skipped["日別データなし"] += 1
            continue
        pub = date.fromisoformat(pub_s)
        if (pub + timedelta(days=27)).isoformat() > last:
            skipped["28日未経過"] += 1
            continue
        dur = v.get("duration_sec") or 0
        if dur <= 0:
            skipped["尺が無い"] += 1
            continue
        r = {"id": vid, "pub": pub_s, "mon": pub_s[:7], "dur": dur,
             "v28": window_views(vdaily[vid], pub, 0, 27),
             "v7": window_views(vdaily[vid], pub, 0, 6)}
        for k, p in PATTERNS.items():
            r[k] = bool(re.search(p, v["title"], re.I))
        rows.append(r)

    # 同じ公開月の中央値で割る。⚠ 月ごとの水準差を消すための処理です。
    months = {}
    for m in sorted({r["mon"] for r in rows}):
        g = [r["v28"] for r in rows if r["mon"] == m]
        g7 = [r["v7"] for r in rows if r["mon"] == m]
        months[m] = {"n": len(g), "median": st.median(g), "mean": round(st.mean(g)),
                     "median7": st.median(g7),
                     "mean_over_median": round(st.mean(g) / st.median(g), 2) if st.median(g) else None}
    for r in rows:
        r["mult"] = r["v28"] / months[r["mon"]]["median"]
        r["mult7"] = r["v7"] / months[r["mon"]]["median7"] if months[r["mon"]]["median7"] else None

    def summarize(sel):
        g = [r["mult"] for r in rows if sel(r)]
        if not g:
            return None
        return {"n": len(g), "median": round(st.median(g), 2), "mean": round(st.mean(g), 2)}

    duration_all = [{"band": b, **(summarize(lambda r, b=b: band_of(r["dur"]) == b) or {"n": 0})}
                    for b, _, _ in BANDS]
    ctrl = lambda r: not any(r[k] for k in CONTROL_OFF)
    duration_ctrl = [{"band": b, **(summarize(lambda r, b=b: band_of(r["dur"]) == b and ctrl(r)) or {"n": 0})}
                     for b, _, _ in BANDS]
    words = []
    for k in PATTERNS:
        yes, no = summarize(lambda r, k=k: r[k]), summarize(lambda r, k=k: not r[k])
        if yes and no:
            words.append({"word": k, "yes": yes, "no": no,
                          "ratio": round(yes["median"] / no["median"], 2) if no["median"] else None})
    words.sort(key=lambda w: -(w["ratio"] or 0))

    recent = sorted({r["mon"] for r in rows})[-1] if rows else None
    out = {
        "generated_at": date.today().isoformat(),
        "builder": "build_title_duration.py",
        "source": "data.json(videos.title / duration_sec) + video_daily.json",
        "basis": "公開28日の視聴 ÷ 同じ公開月の中央値",
        "range": {"from": a.dfrom, "to": a.dto, "daily_last": last},
        "n": len(rows), "skipped": skipped,
        "months": months,
        "duration_all": duration_all,
        "duration_controlled": duration_ctrl,
        "control_off": CONTROL_OFF,
        "controlled_n": sum(1 for r in rows if ctrl(r)),
        "words": words,
        "spearman_duration": spearman([r["dur"] for r in rows], [r["mult"] for r in rows]),
        "recent_month": recent,
        "recent_month_n": months[recent]["n"] if recent else 0,
        "weeks": list(a.weeks),
        "caveat": "サムネイルの文言ではなくタイトルの文言です。サムネイルの画像は取得できないため測れていません。",
    }
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{a.out} を書きました。対象 {len(rows)}本 / 統制後 {out['controlled_n']}本 / weeks={out['weeks']}")
    for d in duration_all:
        print(f"  {d['band']:8} {d.get('n',0):3}本 中央値 {d.get('median','-')}倍")
    for w in words:
        print(f"  {w['word']:6} 有 {w['yes']['n']:3}本 {w['yes']['median']}倍 / 無 {w['no']['n']:3}本 {w['no']['median']}倍")


if __name__ == "__main__":
    main()
