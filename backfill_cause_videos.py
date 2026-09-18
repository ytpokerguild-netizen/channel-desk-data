#!/usr/bin/env python3
"""既存の週次レポートに `cause_videos`（増減要因・全動画ぶん）を後から入れる一回きりのスクリプト。

なぜ要るか:
    `fetch.py` は 2026-09-18 から `cause_videos` を作りますが、**確定済みの週は作り直さない**
    ので、それより前の週には入りません。このスクリプトは `video_daily.json`（全動画×365日）
    から同じ計算をして、既存の週にだけ後から足します。

    ⚠ `ai_analysis` をはじめ、既存のキーは1つも触りません。`cause_videos` を足すだけです。
    ⚠ video_daily に日次が残っていない古い週は、埋められないのでスキップします（そう表示します）。

使い方:
    python3 backfill_cause_videos.py            # 表示するだけ（書き込まない）
    python3 backfill_cause_videos.py write      # data.json に書き込む
"""
import json, sys
from datetime import date, timedelta

CAUSE_KEEP = 8

def days(a, b):
    s = date.fromisoformat(a); e = date.fromisoformat(b)
    out = []
    while s <= e:
        out.append(s.isoformat()); s += timedelta(days=1)
    return set(out)

def week_views(vd, a, b):
    ds = days(a, b); out = {}
    for vid, rows in vd.items():
        v = sum(r.get("views", 0) for r in rows if r.get("date") in ds)
        if v > 0:
            out[vid] = v
    return out

def main():
    write = len(sys.argv) > 1 and sys.argv[1] == "write"
    raw = open("data.json", encoding="utf-8").read()
    d = json.loads(raw)
    assert json.dumps(d, ensure_ascii=False, separators=(",", ":")) == raw.rstrip("\n"), \
        "data.json の書式が想定と違います。中断します。"
    vd = json.load(open("video_daily.json", encoding="utf-8"))
    have = set()
    for rows in vd.values():
        have.update(r.get("date", "") for r in rows)
    oldest = min(have) if have else None
    meta = {v["video_id"]: v for v in d.get("videos", [])}

    done = skipped = 0
    for rep in d.get("weekly_reports", []):
        if rep.get("cause_videos"):
            continue
        ws, we = rep["week_start"], rep["week_end"]
        pws = (date.fromisoformat(ws) - timedelta(days=7)).isoformat()
        pwe = (date.fromisoformat(ws) - timedelta(days=1)).isoformat()
        if oldest and pws < oldest:
            print(f"  {ws}: video_daily に前週（{pws}〜）の日次が無いため埋められません")
            skipped += 1
            continue
        vw, vp = week_views(vd, ws, we), week_views(vd, pws, pwe)
        rows = []
        for vid in set(vw) | set(vp):
            w, p = vw.get(vid, 0), vp.get(vid, 0)
            rows.append({"id": vid, "t": meta.get(vid, {}).get("title", ""),
                         "pub": meta.get(vid, {}).get("published_at", ""),
                         "w": w, "p": p, "d": w - p})
        rows.sort(key=lambda x: x["d"], reverse=True)
        up = [x for x in rows if x["d"] > 0]
        dn = sorted([x for x in rows if x["d"] < 0], key=lambda x: x["d"])
        tot = (rep["channel"].get("views") or 0) - (rep["channel"].get("views_prev") or 0)
        rep["cause_videos"] = {
            "up": up[:CAUSE_KEEP], "down": dn[:CAUSE_KEEP],
            "up_other": sum(x["d"] for x in up[CAUSE_KEEP:]),
            "down_other": sum(x["d"] for x in dn[CAUSE_KEEP:]),
            "resid": tot - sum(x["d"] for x in rows),
            "up_count": len(up), "down_count": len(dn),
        }
        print(f"  {ws}: 増加 {len(up)}本 / 減少 {len(dn)}本 を記録"
              f"（その他: 増 {rep['cause_videos']['up_other']:+,} ／ 減 {rep['cause_videos']['down_other']:+,}"
              f" ／ 割り当てられないぶん {rep['cause_videos']['resid']:+,}）")
        done += 1

    print(f"\n埋めた週: {done} ／ 埋められなかった週: {skipped}")
    if write and done:
        open("data.json", "w", encoding="utf-8").write(
            json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        print("data.json に書き込みました。")
    elif not write:
        print("（表示しただけです。書き込むには `write` を付けて実行してください）")

if __name__ == "__main__":
    main()
