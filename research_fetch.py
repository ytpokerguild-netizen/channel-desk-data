#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research_fetch.py — 地域データ（city ディメンション）の性質を調べる調査用スクリプト

目的:
  ダッシュボードの「日本国内 都市別」で大阪が人口比2.5倍に出る現象が、
  実在する視聴者分布なのか、IPジオロケーション由来の計測アーティファクトなのかを判定する。

本番バッチ（fetch.py / daily_fetch.yml）には一切触らない。
出力は research/geo_research.json のみ。data.json / video_daily.json は書き換えない。

YouTube Analytics API の city レポートの制約（公式ドキュメント準拠）:
  - dimensions: city（必須） + creatorContentType / country / province / subscribedStatus（任意）
                + day または month（0か1つ）
  - deviceType や insightTrafficSourceType とは組み合わせ不可
  - filters: country / province / continent / subContinent から0〜1つ、video / group から0〜1つ
  - maxResults は 250 以下（必須指定）、sort は views か estimatedMinutesWatched
"""

import json, os, sys
from datetime import date, timedelta
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import HTTPError

CHANNEL_ID = "UCnGhxFzP6V4TczZCs63rXgQ"
OUT_DIR = "research"
OUT_FILE = os.path.join(OUT_DIR, "geo_research.json")

# 題材の海外/国内分類キーワード（タイトルから判定）
KW_DOMESTIC = ["JOPT", "日本一", "日本選手権", "KKPoker", "戦国", "SPADIE", "アミューズ", "国内"]
KW_OVERSEAS = ["WSOP", "WSOp", "Triton", "TRITON", "TRiton", "EPT", "WPT",
               "PokerStars", "ポーカースターズ", "APT", "Aussie"]


# ──────────────────────────────────────────────
# 認証（fetch.py と同じ方式・環境変数のみ）
# ──────────────────────────────────────────────
def get_access_token():
    rt = os.environ.get("REFRESH_TOKEN")
    ci = os.environ.get("OAUTH_CLIENT_ID")
    cs = os.environ.get("OAUTH_CLIENT_SECRET")
    if not (rt and ci and cs):
        print("[FATAL] REFRESH_TOKEN / OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET が未設定")
        return None
    data = urlencode({
        "client_id": ci, "client_secret": cs,
        "refresh_token": rt, "grant_type": "refresh_token",
    }).encode()
    req = Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read()).get("access_token")
    except Exception as e:
        print(f"[FATAL] OAuth トークン交換失敗: {e}")
        return None


def analytics_get(access_token, params, label=""):
    url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urlencode(params)
    req = Request(url)
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read())
            n = len(body.get("rows") or [])
            print(f"  [OK] {label}: {n} 行")
            return body
    except HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        print(f"  [ERROR] {label}: HTTP {e.code} {msg}")
        return {"_error": f"HTTP {e.code}: {msg}"}
    except Exception as e:
        print(f"  [ERROR] {label}: {e}")
        return {"_error": str(e)}


def rows_of(body):
    if not body or "_error" in body:
        return None
    return body.get("rows") or []


# ──────────────────────────────────────────────
# 動画の題材分類（既存 data.json のタイトルから）
# ──────────────────────────────────────────────
def classify_videos(top_n=15):
    try:
        with open("data.json", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"[WARN] data.json 読み込み失敗: {e}")
        return [], []
    dom, ovs = [], []
    for v in d.get("videos", []):
        t = v.get("title") or ""
        hit_d = any(k in t for k in KW_DOMESTIC)
        hit_o = any(k in t for k in KW_OVERSEAS)
        if hit_d and not hit_o:
            dom.append(v)
        elif hit_o and not hit_d:
            ovs.append(v)
        # 両方ヒット / どちらも無しは曖昧なので除外
    dom.sort(key=lambda v: -(v.get("views") or 0))
    ovs.sort(key=lambda v: -(v.get("views") or 0))
    return dom[:top_n], ovs[:top_n]


# ──────────────────────────────────────────────
def main():
    token = get_access_token()
    if not token:
        sys.exit(1)

    end = (date.today() - timedelta(days=2)).isoformat()   # 確定寄りに2日引く
    s28 = (date.fromisoformat(end) - timedelta(days=27)).isoformat()
    s365 = (date.fromisoformat(end) - timedelta(days=364)).isoformat()
    s180 = (date.fromisoformat(end) - timedelta(days=179)).isoformat()

    out = {
        "generated_at": date.today().isoformat(),
        "window": {"end": end, "start_28d": s28, "start_180d": s180, "start_365d": s365},
        "api_constraints_note": "city は deviceType / insightTrafficSourceType と組み合わせ不可。"
                                "city レポートは maxResults<=250、sort 必須。",
    }
    base = {"ids": f"channel=={CHANNEL_ID}", "endDate": end}

    # ① 都市 Top250（28日）— 帰属率と全都市分布。averageViewPercentage で都市別の視聴質も見る
    print("① 都市別 Top250（28日）")
    b = analytics_get(token, {**base, "startDate": s28, "dimensions": "city",
                              "filters": "country==JP",
                              "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
                              "sort": "-views", "maxResults": 250}, "cities_28d_top250")
    out["cities_28d"] = {"columns": ["city", "views", "watch_min", "avg_dur_sec", "avg_view_pct"],
                         "rows": rows_of(b), "error": b.get("_error") if b else "no response"}

    # ② 都市 Top250（365日）— 長期でも同じ構造かの確認
    print("② 都市別 Top250（365日）")
    b = analytics_get(token, {**base, "startDate": s365, "dimensions": "city",
                              "filters": "country==JP",
                              "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
                              "sort": "-views", "maxResults": 250}, "cities_365d_top250")
    out["cities_365d"] = {"columns": ["city", "views", "watch_min", "avg_dur_sec", "avg_view_pct"],
                          "rows": rows_of(b), "error": b.get("_error") if b else "no response"}

    # ③ 日本全体の総視聴（帰属率の分母）
    print("③ 日本全体 総視聴（28日 / 365日）")
    for key, st in (("jp_total_28d", s28), ("jp_total_365d", s365)):
        b = analytics_get(token, {**base, "startDate": st, "dimensions": "country",
                                  "filters": "country==JP",
                                  "metrics": "views,estimatedMinutesWatched"}, key)
        out[key] = {"rows": rows_of(b), "error": b.get("_error") if b else "no response"}

    # ④ 都市 × 登録状況（28日）— 大阪が「濃い視聴者集団」か「全国の寄せ集め」かの行動テスト
    print("④ 都市 × 登録状況（28日）")
    b = analytics_get(token, {**base, "startDate": s28, "dimensions": "city,subscribedStatus",
                              "filters": "country==JP",
                              "metrics": "views,estimatedMinutesWatched",
                              "sort": "-views", "maxResults": 250}, "city_x_subscribedStatus")
    out["city_x_sub_28d"] = {"columns": ["city", "subscribedStatus", "views", "watch_min"],
                             "rows": rows_of(b), "error": b.get("_error") if b else "no response"}

    # ⑤ 都市 × 月（180日）— 月単位の推移。28日ローリングより素の時系列に近い
    print("⑤ 都市 × 月（180日）")
    b = analytics_get(token, {**base, "startDate": s180, "dimensions": "city,month",
                              "filters": "country==JP",
                              "metrics": "views",
                              "sort": "-views", "maxResults": 250}, "city_x_month")
    out["city_x_month_180d"] = {"columns": ["city", "month", "views"],
                                "rows": rows_of(b), "error": b.get("_error") if b else "no response"}

    # ⑥ 参考: 全国のデバイス構成（city とは組み合わせられないので単独）
    print("⑥ 参考: デバイス構成（28日・日本）")
    b = analytics_get(token, {**base, "startDate": s28, "dimensions": "deviceType",
                              "filters": "country==JP",
                              "metrics": "views,estimatedMinutesWatched"}, "deviceType_national")
    out["device_national_28d"] = {"columns": ["deviceType", "views", "watch_min"],
                                  "rows": rows_of(b), "error": b.get("_error") if b else "no response"}

    # ⑦ 動画別 × 都市（365日）— 国内題材 vs 海外題材で大阪比率が変わるかの決定的テスト
    dom, ovs = classify_videos(top_n=15)
    print(f"⑦ 動画別 × 都市: 国内題材 {len(dom)}本 / 海外題材 {len(ovs)}本")
    out["video_classification"] = {
        "domestic": [{"video_id": v["video_id"], "title": v["title"], "views_total": v.get("views")} for v in dom],
        "overseas": [{"video_id": v["video_id"], "title": v["title"], "views_total": v.get("views")} for v in ovs],
        "keywords": {"domestic": KW_DOMESTIC, "overseas": KW_OVERSEAS},
    }
    per_video = {}
    for label, lst in (("domestic", dom), ("overseas", ovs)):
        for v in lst:
            vid = v["video_id"]
            b = analytics_get(token, {**base, "startDate": s365, "dimensions": "city",
                                      "filters": f"country==JP;video=={vid}",
                                      "metrics": "views",
                                      "sort": "-views", "maxResults": 50},
                              f"{label}:{vid}")
            per_video[vid] = {"class": label, "title": v["title"],
                              "rows": rows_of(b), "error": b.get("_error") if b else "no response"}
    out["per_video_cities_365d"] = {"columns": ["city", "views"], "videos": per_video}

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n[DONE] {OUT_FILE} を書き出しました")

    # ざっくりサマリーをログに出す（判定はチャット側で行う）
    rows = out["cities_28d"].get("rows") or []
    if rows:
        tot = sum(int(float(r[1])) for r in rows)
        osaka = next((int(float(r[1])) for r in rows if r[0] == "Osaka"), 0)
        jp = out.get("jp_total_28d", {}).get("rows") or []
        jpv = int(float(jp[0][1])) if jp else 0
        print(f"[SUMMARY] 28日 都市数={len(rows)} 都市計={tot:,} 日本計={jpv:,} "
              f"帰属率={100*tot/jpv:.1f}% 大阪={osaka:,} ({100*osaka/tot:.2f}%)" if jpv else
              f"[SUMMARY] 28日 都市数={len(rows)} 都市計={tot:,} 大阪={osaka:,}")


if __name__ == "__main__":
    main()
