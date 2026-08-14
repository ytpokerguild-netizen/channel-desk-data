#!/usr/bin/env python3
"""
morning_brief.py — 毎朝の LINE ブリーフ。

公開済みの data.json を読み、
  ・視聴回数（確定最新日 vs 直近7日平均）
  ・登録者純増（gained − lost）
を判定してグループへ送信する。

判定記号: 🟢 好調 / 🟡 標準 / 🔴 要改善 / ⚪ 判定なし
※ 推定値・欠損・確定前のデータには 🟢🟡🔴 を出さない（フロントの色ガードと同じ思想）。
   ・視聴回数/登録者純増は analytics_daily の確定値のみ使用 → 常に判定可
"""
import json
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

    # 3) 動画アーカイブの未入力（企画タイプ・ナレーター）
    # 入れ忘れると企画タイプ別・ナレーター別の集計から黙って抜けるので、残っている間は毎朝出す。
    # ⚠ 直近180日ぶんだけ数える（全期間だと 2022 年のテスト動画1本がずっと残る）。
    #   数え方は notify_archive_input.py と同じにしてあります。片方だけ変えると本数が食い違います。
    arc = d.get("video_archive") or {}
    limit = (date.today() - timedelta(days=180)).isoformat()
    miss = 0
    for v in d.get("videos", []):
        pub = (v.get("published_at") or "")[:10]
        if pub and pub < limit:
            continue
        a = arc.get(v.get("video_id")) or {}
        if not (a.get("type") or "").strip() or not (a.get("narrator") or "").strip():
            miss += 1
    if miss:
        lines.append(f"📝 企画タイプ／ナレーターの未入力 {miss}本（投稿計画表の動画アーカイブ）")

    # 「新作初速」は 2026-08-07 に廃止。
    # 理由: 最新1本だけを対象にする設計と「ほぼ毎日投稿 + 確定値2〜4日ラグ」が噛み合わず、
    # 直近60日で一度も算出できていなかった（毎朝「⚪ 新作初速 集計待ち」を送り続けていた）。
    # 復活させるなら対象を「確定済みで判定できる最新の1本」に変える必要がある。旧実装は git 履歴にある。

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
