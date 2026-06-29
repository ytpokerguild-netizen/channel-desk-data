#!/usr/bin/env python3
"""
CHANNEL DESK — データ取得スクリプト v3
YouTube Data API v3 (APIキー方式) でりいポーカーチャンネルのデータを取得する。
daily配列にスナップショットを日付でdedup・蓄積する（デルタ/ゼロ埋め行は除去）。

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

CHANNEL_ID  = "UCnGhxFzP6V4TczZCs63rXgQ"  # りいポーカーチャンネル
OUTPUT_FILE = "data.json"

# ──────────────────────────────────────────
# APIキー取得
# ──────────────────────────────────────────
def get_api_key():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("[ERROR] 環境変数 YOUTUBE_API_KEY が設定されていません。")
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
        "total_views": int(stats.get("viewCount",       0)),
        "video_count": int(stats.get("videoCount",      0)),
    }

# ──────────────────────────────────────────
# 動画リスト（最大200本、新しい順）
# ──────────────────────────────────────────
def fetch_video_ids(api_key, max_videos=200):
    ids        = []
    page_token = None
    while len(ids) < max_videos:
        params = {
            "part":      "id",
            "channelId": CHANNEL_ID,
            "maxResults": 50,
            "order":     "date",
            "type":      "video",
            "key":       api_key,
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
            "video_id":     item["id"],
            "title":        item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"][:10],
            "views":        int(s.get("viewCount",    0)),
            "likes":        int(s.get("likeCount",    0)),
            "comments":     int(s.get("commentCount", 0)),
            "watch_minutes": 0,  # YouTube Analytics API のみ
            "revenue_jpy":   0,  # YouTube Analytics API のみ
        })
    return sorted(videos, key=lambda v: v["views"], reverse=True)

# ──────────────────────────────────────────
# 既存 data.json からスナップショットを読み込む
# （subscribersフィールドを持つ行のみ保持。デルタ形式は除去）
# ──────────────────────────────────────────
def load_existing_snapshots():
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
        snapshots = [
            d for d in existing.get("daily", [])
            if "subscribers" in d and d.get("subscribers", 0) > 0
        ]
        return snapshots
    except Exception as e:
        print(f"[WARN] 既存データの読み込みに失敗: {e}")
        return []

# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────
def main():
    api_key = get_api_key()
    today   = date.today().isoformat()

    print(f"[INFO] チャンネル統計を取得中...")
    ch = fetch_channel_stats(api_key)
    print(f"  登録者: {ch['subscribers']:,}  総再生: {ch['total_views']:,}  動画: {ch['video_count']}")

    print(f"[INFO] 動画リストを取得中...")
    ids    = fetch_video_ids(api_key)
    videos = fetch_video_details(api_key, ids)
    print(f"  動画 {len(videos)} 本取得")

    # 既存スナップショットを読み込み（デルタ形式・ゼロ埋め行を除去）
    existing = load_existing_snapshots()
    print(f"[INFO] 既存スナップショット: {len(existing)} 日分")

    # 今日以外を保持し、今日分を追加（上書き）
    daily = [d for d in existing if d["date"] != today]
    daily.append({
        "date":        today,
        "subscribers": ch["subscribers"],
        "total_views": ch["total_views"],
        "video_count": ch["video_count"],
    })
    daily.sort(key=lambda d: d["date"])

    data = {
        "meta": {
            "channel_id":    CHANNEL_ID,
            "channel_title": ch["title"],
            "fetched_at":    datetime.now(timezone.utc).isoformat(),
            "data_through":  today,
            "since":         daily[0]["date"] if daily else today,
            "data_source":   "youtube_data_api_v3",
            "note":          "daily はスナップショット蓄積。watch_minutes/revenue_jpy は Analytics API 必要のため常に0。",
        },
        "daily":     daily,
        "videos":    videos,
        "breakdown": {"device": [], "country": [], "traffic_source": []},
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] {OUTPUT_FILE} を書き出しました")
    print(f"  スナップショット: {len(daily)} 日分 / 動画: {len(videos)} 本")

if __name__ == "__main__":
    main()
