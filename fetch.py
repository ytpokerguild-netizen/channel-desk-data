#!/usr/bin/env python3
"""
fetch.py — りいポーカーチャンネル CHANNEL DESK データ取得スクリプト
YouTube Data API v3 + YouTube Analytics API v2
"""

import json, os, sys
from datetime import date, datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.parse   import urlencode
from urllib.error   import HTTPError

CHANNEL_ID         = "UCnGhxFzP6V4TczZCs63rXgQ"
OUTPUT_FILE        = "data.json"
TOKEN_FILE         = "token.json"
CLIENT_SECRET_FILE = "client_secret.json"

# ─────────────────────────────────────────
# YouTube Data API v3 ヘルパー
# ─────────────────────────────────────────
def get_api_key():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("[ERROR] 環境変数 YOUTUBE_API_KEY が設定されていません。")
        sys.exit(1)
    return key

def yt_get(endpoint, params):
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?" + urlencode(params)
    try:
        with urlopen(url) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = json.loads(e.read())
        print(f"[ERROR] HTTP {e.code}: {json.dumps(body, ensure_ascii=False)}")
        sys.exit(1)

# ─────────────────────────────────────────
# チャンネル統計
# ─────────────────────────────────────────
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

# ─────────────────────────────────────────
# 動画リスト（最大200本、新しい順）
# ─────────────────────────────────────────
def fetch_video_ids(api_key, max_videos=200):
    ids, page_token = [], None
    while len(ids) < max_videos:
        params = {
            "part": "id", "channelId": CHANNEL_ID,
            "maxResults": 50, "order": "date", "type": "video", "key": api_key,
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
            "watch_minutes": 0,
            "revenue_jpy":   0,
        })
    return sorted(videos, key=lambda v: v["views"], reverse=True)

# ─────────────────────────────────────────
# OAuth2 トークン管理
# ─────────────────────────────────────────
def load_access_token():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, encoding="utf-8") as f:
        tok = json.load(f)

    access_token  = tok.get("token") or tok.get("access_token")
    refresh_token = tok.get("refresh_token")
    expiry_str    = tok.get("expiry") or tok.get("token_expiry")

    expired = False
    if expiry_str:
        try:
            exp_dt  = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            expired = (exp_dt - datetime.now(timezone.utc)) < timedelta(minutes=5)
        except Exception:
            expired = True

    if (not access_token or expired) and refresh_token:
        access_token = _refresh_token(tok, refresh_token)

    return access_token

def _refresh_token(tok_data, refresh_token):
    client_id     = tok_data.get("client_id")
    client_secret = tok_data.get("client_secret")

    if (not client_id or not client_secret) and os.path.exists(CLIENT_SECRET_FILE):
        with open(CLIENT_SECRET_FILE, encoding="utf-8") as f:
            cs = json.load(f)
        info          = cs.get("installed") or cs.get("web") or {}
        client_id     = client_id     or info.get("client_id")
        client_secret = client_secret or info.get("client_secret")

    if not client_id or not client_secret:
        print("[WARN] client 情報不明 → トークン更新スキップ")
        return tok_data.get("token") or tok_data.get("access_token")

    data = urlencode({
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    }).encode()
    req = Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    try:
        with urlopen(req) as resp:
            new          = json.loads(resp.read())
            access_token = new["access_token"]
            tok_data["token"] = tok_data["access_token"] = access_token
            tok_data["expiry"] = (
                datetime.now(timezone.utc) + timedelta(seconds=new.get("expires_in", 3600))
            ).isoformat()
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump(tok_data, f, ensure_ascii=False, indent=2)
            print("[INFO] アクセストークン更新完了")
            return access_token
    except Exception as e:
        print(f"[WARN] トークン更新失敗: {e}")
        return tok_data.get("token") or tok_data.get("access_token")

# ─────────────────────────────────────────
# YouTube Analytics API v2
# ─────────────────────────────────────────
def analytics_get(access_token, params):
    url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urlencode(params)
    req = Request(url)
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = json.loads(e.read())
        print(f"[ERROR] Analytics API HTTP {e.code}: {json.dumps(body, ensure_ascii=False)}")
        return None

def fetch_video_views_day(access_token, target_date):
    """指定日の動画別再生数 → {video_id: views}"""
    result, start_idx = {}, 1
    while True:
        data = analytics_get(access_token, {
            "ids": "channel==MINE", "dimensions": "video", "metrics": "views",
            "startDate": target_date, "endDate": target_date,
            "sort": "-views", "maxResults": 500, "startIndex": start_idx,
        })
        if not data or "rows" not in data:
            break
        for row in data["rows"]:
            if int(row[1]) > 0:
                result[row[0]] = int(row[1])
        if len(data["rows"]) < 500:
            break
        start_idx += 500
    return result

def fetch_video_views_range(access_token, start_date, end_date):
    """期間の動画×日次再生数 → {video_id: [{date, views}]}"""
    result, start_idx = {}, 1
    while True:
        data = analytics_get(access_token, {
            "ids": "channel==MINE", "dimensions": "video,day", "metrics": "views",
            "startDate": start_date, "endDate": end_date,
            "sort": "day,-views", "maxResults": 1000, "startIndex": start_idx,
        })
        if not data or "rows" not in data:
            break
        for row in data["rows"]:
            vid_id, day, views = row[0], row[1], int(row[2])
            if views > 0:
                result.setdefault(vid_id, []).append({"date": day, "views": views})
        if len(data["rows"]) < 1000:
            break
        start_idx += 1000
    return result

# ─────────────────────────────────────────
# 既存 data.json 読み込み
# ─────────────────────────────────────────
def load_existing_data():
    if not os.path.exists(OUTPUT_FILE):
        return [], [], {}
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            ex = json.load(f)
        snapshots = [
            d for d in ex.get("daily", [])
            if "subscribers" in d and d.get("subscribers", 0) > 0
        ]
        return snapshots, ex.get("analytics_daily_views", []), ex.get("video_daily_views", {})
    except Exception as e:
        print(f"[WARN] 既存データの読み込みに失敗: {e}")
        return [], [], {}

# ─────────────────────────────────────────
# メイン
# ─────────────────────────────────────────
def main():
    # --backfill DAYS オプション
    backfill_days = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--backfill":
            try:
                backfill_days = int(args[i + 1])
            except (IndexError, ValueError):
                backfill_days = 365

    api_key = get_api_key()
    today   = date.today().isoformat()

    print("[INFO] チャンネル統計を取得中...")
    ch = fetch_channel_stats(api_key)
    print(f"  登録者: {ch['subscribers']:,}  総再生数: {ch['total_views']:,}  動画: {ch['video_count']}")

    print("[INFO] 動画リストを取得中...")
    ids    = fetch_video_ids(api_key)
    videos = fetch_video_details(api_key, ids)
    print(f"  {len(videos)} 本取得")

    snapshots, analytics_daily_views, video_daily_views = load_existing_data()
    print(f"[INFO] 既存スナップショット: {len(snapshots)} 日分")

    # 本日スナップショット追加
    daily = [d for d in snapshots if d["date"] != today]
    daily.append({
        "date": today, "subscribers": ch["subscribers"],
        "total_views": ch["total_views"], "video_count": ch["video_count"],
    })
    daily.sort(key=lambda d: d["date"])

    # ── Analytics API: 動画別日次再生数 ──────────────
    access_token = load_access_token()
    if access_token:
        if backfill_days:
            start = (date.today() - timedelta(days=backfill_days)).isoformat()
            end   = (date.today() - timedelta(days=1)).isoformat()
            print(f"[INFO] 動画別Analytics バックフィル中... ({start} 〜 {end})")
            bulk = fetch_video_views_range(access_token, start, end)
            for vid_id, entries in bulk.items():
                if vid_id not in video_daily_views:
                    video_daily_views[vid_id] = []
                existing_dates = {e["date"] for e in video_daily_views[vid_id]}
                for entry in entries:
                    if entry["date"] not in existing_dates:
                        video_daily_views[vid_id].append(entry)
                video_daily_views[vid_id].sort(key=lambda x: x["date"])
            print(f"  {len(bulk)} 本分バックフィル完了")
        else:
            yesterday  = (date.today() - timedelta(days=1)).isoformat()
            need_fetch = True
            if video_daily_views:
                sample_dates = {
                    e["date"]
                    for entries in list(video_daily_views.values())[:5]
                    for e in entries
                }
                if yesterday in sample_dates:
                    need_fetch = False

            if need_fetch:
                print(f"[INFO] 動画別Analytics取得中... ({yesterday})")
                dv = fetch_video_views_day(access_token, yesterday)
                if dv:
                    for vid_id, views in dv.items():
                        if vid_id not in video_daily_views:
                            video_daily_views[vid_id] = []
                        existing_dates = {e["date"] for e in video_daily_views[vid_id]}
                        if yesterday not in existing_dates:
                            video_daily_views[vid_id].append({"date": yesterday, "views": views})
                            video_daily_views[vid_id].sort(key=lambda x: x["date"])
                    print(f"  {len(dv)} 本分取得完了")
                else:
                    print("[WARN] 動画別Analytics取得失敗")
            else:
                print(f"[INFO] 動画別Analytics: {yesterday} 取得済 → スキップ")
    else:
        print("[WARN] token.json なし → 動画別Analytics取得スキップ")

    # データ書き出し
    data = {
        "meta": {
            "channel_id":    CHANNEL_ID,
            "channel_title": ch["title"],
            "fetched_at":    datetime.now(timezone.utc).isoformat(),
            "data_through":  today,
            "since":         daily[0]["date"] if daily else today,
            "data_source":   "youtube_data_api_v3",
            "note":          "daily はスナップショット蓄積。video_daily_views は Analytics API v2 取得。",
        },
        "daily":                  daily,
        "analytics_daily_views":  analytics_daily_views,
        "video_daily_views":      video_daily_views,
        "videos":                 videos,
        "breakdown":              {"device": [], "country": [], "traffic_source": []},
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] {OUTPUT_FILE} を書き出しました")
    print(f"  スナップショット: {len(daily)} 日分 / 動画: {len(videos)} 本")
    if video_daily_views:
        total_e = sum(len(v) for v in video_daily_views.values())
        print(f"  動画別日次データ: {len(video_daily_views)} 本 / {total_e} レコード")

if __name__ == "__main__":
    main()
