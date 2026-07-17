#!/usr/bin/env python3
"""
morning_brief.py — 毎朝の LINE ブリーフ。

公開済みの data.json / video_daily.json を読み、
  ・視聴回数（確定最新日 vs 直近7日平均）
  ・登録者純増（gained − lost）
  ・最新公開動画の初速（過去20本の同一経過日数窓の中央値比）
を判定してグループへ送信する。

判定記号: 🟢 好調 / 🟡 標準 / 🔴 要改善 / ⚪ 判定なし
※ 推定値・欠損・確定前のデータには 🟢🟡🔴 を出さない（フロントの色ガードと同じ思想）。
   ・視聴回数/登録者純増は analytics_daily の確定値のみ使用 → 常に判定可
   ・新作初速は video_daily の確定行が無ければ ⚪「集計待ち」
"""
import json, statistics
from datetime import date, datetime, timezone, timedelta
from urllib.request import urlopen, Request
from line_notify import send_line

BASE = "https://ytpokerguild-netizen.github.io/channel-desk-data/"
STALE_HOURS = 24


def fetch_json(name):
    url = BASE + name + "?t=" + str(int(datetime.now().timestamp()))
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def fmt(n):
    n = round(n)
    if abs(n) >= 10000:
        s = f"{n/10000:.1f}".rstrip("0").rstrip(".")
        return s + "万"
    return f"{n:,}"


def mdslash(iso):
    """'2026-07-14' -> '7/14'"""
    y, m, d = iso.split("-")
    return f"{int(m)}/{int(d)}"


def days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def verdict(pct, up=10, down=-10, good_up=None, bad_down=None):
    """割合(%)から 🟢/🟡/🔴 を返す。"""
    up_th = good_up if good_up is not None else up
    down_th = bad_down if bad_down is not None else down
    if pct >= up_th:
        return "🟢"
    if pct <= down_th:
        return "🔴"
    return "🟡"


def build_message():
    d = fetch_json("data.json")
    try:
        vd = fetch_json("video_daily.json")
    except Exception:
        vd = {}

    header = "📊 CHANNEL DESK 朝ブリーフ（" + mdslash(date.today().isoformat()) + "）"

    # 鮮度チェック
    stale = ""
    fa = d.get("meta", {}).get("fetched_at")
    if fa:
        try:
            hrs = (datetime.now(timezone.utc) - datetime.fromisoformat(fa)).total_seconds() / 3600
            if hrs > STALE_HOURS:
                stale = f"⚠️ データが約{int(hrs)}時間更新されていません\n\n"
        except Exception:
            pass

    ad = [x for x in d.get("analytics_daily", []) if x.get("views", 0) > 0]
    if len(ad) < 9:
        return stale + header + "\n\nデータが不足しています。\n\n▶ " + BASE

    latest = ad[-1]
    base_date = latest["date"]
    prior7 = ad[-8:-1]
    today_iso = date.today().isoformat()
    lag = days_between(base_date, today_iso)

    lines = []

    # 1) 視聴回数
    avgv = sum(x["views"] for x in prior7) / len(prior7)
    pv = (latest["views"] - avgv) / avgv * 100 if avgv else 0
    lines.append(f"{verdict(pv)} 視聴回数 {fmt(latest['views'])}回（{pv:+.0f}% vs 7日平均）")

    # 2) 登録者純増
    g = latest.get("subs_gained", 0)
    l = latest.get("subs_lost", 0)
    net = g - l
    basenet = sum((x.get("subs_gained", 0) - x.get("subs_lost", 0)) for x in prior7) / len(prior7)
    pn = (net - basenet) / abs(basenet) * 100 if basenet else 0
    lines.append(f"{verdict(pn)} 登録者純増 {net:+d}人（内訳 +{g}/-{l}）")

    # 3) 新作初速（分子・分母とも video_daily の同一確定窓）
    vids = sorted(
        [v for v in d.get("videos", []) if v.get("published_at")],
        key=lambda v: v["published_at"], reverse=True,
    )
    newest = next((v for v in vids if days_between(v["published_at"][:10], today_iso) <= 4), None)
    if newest:
        pub = newest["published_at"][:10]
        win = days_between(pub, base_date) + 1  # 公開日〜確定基準日までの日数
        rows = [r for r in vd.get(newest["video_id"], []) if pub <= r["date"] <= base_date]
        if win >= 1 and rows:
            num = sum(r["views"] for r in rows)
            olds = [v for v in vids
                    if v is not newest and days_between(v["published_at"][:10], base_date) > win + 1][:20]
            samples = []
            for v in olds:
                vp = v["published_at"][:10]
                co = (date.fromisoformat(vp) + timedelta(days=win - 1)).isoformat()
                s = sum(r["views"] for r in vd.get(v["video_id"], []) if vp <= r["date"] <= co)
                if s > 0:
                    samples.append(s)
            if samples:
                med = statistics.median(samples)
                r = (num - med) / med * 100 if med else 0
                sym = verdict(r, good_up=15, bad_down=-15)
                lines.append(f"{sym} 新作初速 {fmt(num)}回（公開{win}日目・中央値比{r:+.0f}%）")
            else:
                lines.append(f"⚪ 新作初速 {fmt(num)}回（比較対象不足）")
        else:
            lines.append(f"⚪ 新作初速 集計待ち（{mdslash(pub)}公開・確定データ未着）")
    else:
        lines.append("⚪ 新作初速 直近4日の新規投稿なし")

    lag_note = f"・確定値は{lag}日遅れ" if lag > 2 else ""
    body = (
        header + "\n"
        + f"基準日: {mdslash(base_date)}（確定{lag_note}）\n\n"
        + "\n".join(lines)
        + "\n\n▶ " + BASE
    )
    return stale + body


def main():
    msg = build_message()
    print(msg)
    send_line(msg)


if __name__ == "__main__":
    main()
