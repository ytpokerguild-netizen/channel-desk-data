#!/usr/bin/env python3
"""
CHANNEL DESK — データ取得スクリプト v2
YouTube Data API v3 (APIキー方式) でりいポーカーチャンネルのデータを取得する。

【ローカルテスト】
  export YOUTUBE_API_KEY="AIza..."
  python3 fetch.py

【GitHub Actions】
  Secret: YOUTUBE_API_KEY を登録すること
"""

import json
import os
import sys
from datetime import date, datetime, timezone
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

CHANNEL_ID  = "UCnGhxFzP6V4TczZCs63rXgQ"   # りいポーカーチャンネル
OUTPUT_FILE = "data.json"

# ──────────────────────────────────────────
# APIキー取得
# ──────────────────────────────────────────
def get_api_key():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("[ERROR] 環境変数 YOUTUBE_API_KEY が設定されていません。")
        print("  ローカル: export YOUTUBE_API_KEY='AIza...'")
        sys.exit(1)
    return key


# ──────────────────────────────────────────
# YouTube Data API v3 ヘルパー
# ──────────────────────────────────────────
def yt_get(endpoint, params):
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?" + urlencode(params)
    try:
        with urlopen(url) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = json.loads(e.read())
        print(f"[ERROR] HTTP {e.code}: {json.dumps(body, ensure_ascii=False)}")
        sys.exit(1)


# ──────────────────────────────────────────
# チャンネル統計
# ──────────────────────────────────────────
def fetch_channel_stats(api_key):
    data = yt_get("channels", {
        "part": "statistics,snippet",
        "id":   CHANNEL_ID,
        "key":  api_key,
    })
    if not data.get("items"):
        print(f"[ERROR] チャンネルが見つかりません: {CHANNEL_ID}")
        sys.exit(1)
    item  = data["items"][0]
    stats = item["statistics"]
    return {
        "title":       item["snippet"]["title"],
        "subscribers": int(stats.get("subscriberCount", 0)),
        "total_views": int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
    }


# ──────────────────────────────────────────
# 動画リスト（最大200本、新しい順）
# ──────────────────────────────────────────
def fetch_video_ids(api_key, max_videos=200):
    ids = []
    page_token = None
    while len(ids) < max_videos:
        params = {
            "part":       "id",
            "channelId":  CHANNEL_ID,
            "maxResults": 50,
            "order":      "date",
            "type":       "video",
            "key":        api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        data       = yt_get("search", params)
        ids       += [item["id"]["videoId"] for item in data.get("items", [])]
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_videos]


def fetch_video_details(api_key, video_ids):
    items = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        data  = yt_get("videos", {
            "part": "snippet,statistics",
            "id":   ",".join(chunk),
            "key":  api_key,
        })
        items.extend(data.get("items", []))

    videos = []
    for item in items:
        s = item.get("statistics", {})
        videos.append({
            "video_id":      item["id"],
            "title":         item["snippet"]["title"],
            "published_at":  item["snippet"]["publishedAt"][:10],
            "views":         int(s.get("viewCount",    0)),
            "likes":         int(s.get("likeCount",    0)),
            "comments":      int(s.get("commentCount", 0)),
            "watch_minutes": 0,   # YouTube Analytics APIのみ
            "revenue_jpy":   0,   # YouTube Analytics APIのみ
        })
    # 再生数降順
    videos.sort(key=lambda v: v["views"], reverse=True)
    return videos


# ──────────────────────────────────────────
# 既存 data.json を読み込む
# ──────────────────────────────────────────
def load_existing():
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None


# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────
def main():
    api_key = get_api_key()

    print(f"[INFO] チャンネル: {CHANNEL_ID}")

    # チャンネル統計
    ch = fetch_channel_stats(api_key)
    print(f"[FETCH] {ch['title']}: 登録者 {ch['subscribers']:,} / 総再生 {ch['total_views']:,}")

    # 動画リスト
    print("[FETCH] 動画リスト取得中...")
    ids    = fetch_video_ids(api_key)
    print(f"[FETCH] 動画 {len(ids)} 本の詳細取得中...")
    videos = fetch_video_details(api_key, ids)

    # 日次スナップショット（累積値を毎日1行追加）
    existing = load_existing()
    today    = str(date.today())

    snapshot = {
        "date":               today,
        "subscribers":        ch["subscribers"],
        "total_views":        ch["total_views"],
        "video_count":        ch["video_count"],
        # 以下は Analytics API なしでは取得不可（0固定）
        "views":              0,
        "watch_minutes":      0,
        "subscribers_gained": 0,
        "subscribers_lost":   0,
        "likes":              0,
        "comments":           0,
        "revenue_jpy":        0,
    }

    if existing:
        daily = existing.get("daily", [])
        if daily and daily[-1]["date"] == today:
            daily[-1] = snapshot   # 同日は上書き
        else:
            daily.append(snapshot)
    else:
        daily = [snapshot]

    # 書き出し
    data = {
        "meta": {
            "channel_id":    CHANNEL_ID,
            "channel_title": ch["title"],
            "fetched_at":    datetime.now(timezone.utc).isoformat(),
            "data_through":  today,
            "since":         daily[0]["date"] if daily else today,
            "data_source":   "youtube_data_api_v3",
            "note":          "watch_minutes/revenue_jpyはAnalytics API必要のため0。dailyは累積スナップショット。",
        },
        "daily":     daily,
        "videos":    videos,
        "breakdown": {"device": [], "country": [], "traffic_source": []},
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {OUTPUT_FILE} を書き出しました")
    print(f"   スナップショット: {len(daily)} 日分 / 動画: {len(videos)} 本")


if __name__ == "__main__":
    main()
