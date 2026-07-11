#!/usr/bin/env python3
"""
fetch.py — りいポーカーチャンネル CHANNEL DESK データ取得スクリプト
YouTube Data API v3 + YouTube Analytics API v2

取得データ:
  - チャンネル統計（日次スナップショット蓄積）
  - 動画リスト + 現在の stats
  - 動画別 views スナップショット（毎日記録 → 伸び率計算に使用）
  - Analytics: チャンネル日次（views / 視聴時間 / 登録者増減）
  - Analytics: 動画別期間合計 7/28/90/365 日（views / 視聴時間 / 平均視聴時間 / CTR）
  - Analytics: チャンネル追加（CTR / トラフィックソース / 国別 / 新規vsリピーター）

GitHub Actions での認証:
  REFRESH_TOKEN, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET を Secrets に設定すると
  自動で OAuth トークンを取得し Analytics API を叩く。
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
SNAPSHOT_KEEP_DAYS = 90   # video_snapshots 保持日数
MAX_VIDEOS         = 500  # 動画取得上限

# 投稿計画スプレッドシート（公開 CSV エクスポート）
SPREADSHEET_ID = "1Xqxx4vnKfQVQ_qEx8T3tpAA9_vD1uBfihdvWPfHVdmI"
SHEET_GID      = "574456276"  # 投稿管理タブ

# ──────────────────────────────────────────────────────────
# Google スプレッドシート: 投稿計画（CSV エクスポート、認証不要）
# ──────────────────────────────────────────────────────────
def fetch_post_plan():
    """Google スプレッドシートから投稿計画を取得（公開 CSV、OAuth 不要）"""
    import csv, io
    url = (f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
           f"/export?format=csv&gid={SHEET_GID}")
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8-sig")
    except Exception as e:
        print(f"  [WARN] スプレッドシート取得失敗: {e}")
        return []

    reader    = csv.reader(io.StringIO(content))
    rows      = list(reader)

    # ヘッダー行を探す（"投稿予定日" を含む行）
    header_idx = None
    for i, row in enumerate(rows):
        if row and "投稿予定日" in row[0]:
            header_idx = i
            break
    if header_idx is None:
        print("  [WARN] ヘッダー行が見つかりません")
        return []

    headers = [h.strip() for h in rows[header_idx]]
    result  = []
    for row in rows[header_idx + 1:]:
        if not any(c.strip() for c in row):
            continue  # 空行スキップ
        while len(row) < len(headers):
            row.append("")
        item = {headers[j]: row[j].strip() for j in range(len(headers)) if headers[j]}
        if item.get("投稿予定日"):  # 日付がある行のみ
            result.append(item)

    print(f"  {len(result)} 件取得")
    return result

# ──────────────────────────────────────────────────────────
# YouTube Data API v3 ヘルパー
# ──────────────────────────────────────────────────────────
def get_api_key():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("[ERROR] 環境変数 YOUTUBE_API_KEY が設定されていません。")
        sys.exit(1)
    return key

def yt_get(endpoint, params):
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?" + urlencode(params)
    try:
        with urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = json.loads(e.read())
        print(f"[ERROR] HTTP {e.code}: {json.dumps(body, ensure_ascii=False)}")
        return None

# ──────────────────────────────────────────────────────────
# チャンネル統計
# ──────────────────────────────────────────────────────────
def fetch_channel_stats(api_key):
    data = yt_get("channels", {
        "part": "statistics,snippet",
        "id":   CHANNEL_ID,
        "key":  api_key,
    })
    if not data or not data.get("items"):
        print(f"[ERROR] チャンネルが見つかりません: {CHANNEL_ID}")
        sys.exit(1)
    item  = data["items"][0]
    stats = item["statistics"]
    return {
        "title":        item["snippet"]["title"],
        "subscribers":  int(stats.get("subscriberCount", 0)),
        "total_views":  int(stats.get("viewCount",       0)),
        "video_count":  int(stats.get("videoCount",      0)),
        "published_at": item["snippet"]["publishedAt"][:10],  # チャンネル開設日
    }

# ──────────────────────────────────────────────────────────
# 動画リスト
# ──────────────────────────────────────────────────────────
def fetch_video_ids(api_key, max_videos=MAX_VIDEOS):
    """アップロードプレイリスト（UU...）経由で全動画IDを取得。
    search.list は取りこぼしが発生するため playlistItems を使用（quota も約1/100）。"""
    playlist_id = "UU" + CHANNEL_ID[2:]
    ids, page_token = [], None
    while len(ids) < max_videos:
        params = {
            "part": "contentDetails", "playlistId": playlist_id,
            "maxResults": 50, "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        data = yt_get("playlistItems", params)
        if not data:
            break
        ids       += [it["contentDetails"]["videoId"] for it in data.get("items", [])]
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_videos]

def fetch_video_details(api_key, video_ids):
    items = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        data  = yt_get("videos", {
            "part": "snippet,statistics,contentDetails",
            "id":   ",".join(chunk),
            "key":  api_key,
        })
        if data:
            items.extend(data.get("items", []))

    videos = []
    for item in items:
        s  = item.get("statistics",     {})
        cd = item.get("contentDetails", {})
        dur_raw = cd.get("duration", "PT0S")  # ISO 8601 duration
        dur_sec = _parse_iso_duration(dur_raw)
        videos.append({
            "video_id":     item["id"],
            "title":        item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"][:10],
            "views":        int(s.get("viewCount",    0)),
            "likes":        int(s.get("likeCount",    0)),
            "comments":     int(s.get("commentCount", 0)),
            "duration_sec": dur_sec,
        })
    return sorted(videos, key=lambda v: v["views"], reverse=True)

def _parse_iso_duration(dur):
    """PT#H#M#S → 秒数"""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
    if not m:
        return 0
    h, mn, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mn * 60 + s

# ──────────────────────────────────────────────────────────
# 動画 views スナップショット（Data API — OAuth 不要）
# ──────────────────────────────────────────────────────────
def fetch_video_snapshot(api_key, video_ids):
    """現在の動画別再生数スナップショット → {vid_id: views}"""
    snapshot = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        data  = yt_get("videos", {
            "part": "statistics",
            "id":   ",".join(chunk),
            "key":  api_key,
        })
        if data:
            for item in data.get("items", []):
                snapshot[item["id"]] = int(item.get("statistics", {}).get("viewCount", 0))
    return snapshot

# ──────────────────────────────────────────────────────────
# OAuth2 トークン管理
# ──────────────────────────────────────────────────────────
def load_access_token():
    """
    優先度:
      1. 環境変数 REFRESH_TOKEN + OAUTH_CLIENT_ID + OAUTH_CLIENT_SECRET
         （GitHub Actions モード: 毎回リフレッシュ）
      2. token.json（ローカルモード）
    """
    # GitHub Actions モード
    refresh_token  = os.environ.get("REFRESH_TOKEN")
    client_id      = os.environ.get("OAUTH_CLIENT_ID")
    client_secret  = os.environ.get("OAUTH_CLIENT_SECRET")

    if refresh_token and client_id and client_secret:
        print("[INFO] 環境変数から OAuth トークン取得中...")
        return _exchange_refresh_token(refresh_token, client_id, client_secret)

    # ローカルモード
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
        # client info を token.json または client_secret.json から取得
        ci = tok.get("client_id")
        cs_val = tok.get("client_secret")
        if (not ci or not cs_val) and os.path.exists(CLIENT_SECRET_FILE):
            with open(CLIENT_SECRET_FILE, encoding="utf-8") as f:
                cs_json = json.load(f)
            info   = cs_json.get("installed") or cs_json.get("web") or {}
            ci     = ci     or info.get("client_id")
            cs_val = cs_val or info.get("client_secret")

        if ci and cs_val:
            new_token = _exchange_refresh_token(refresh_token, ci, cs_val)
            if new_token:
                # token.json を更新
                tok["token"] = tok["access_token"] = new_token
                tok["expiry"] = (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat()
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    json.dump(tok, f, ensure_ascii=False, indent=2)
                print("[INFO] アクセストークン更新完了")
                return new_token

    return access_token

def _exchange_refresh_token(refresh_token, client_id, client_secret):
    """refresh_token → 新しい access_token"""
    data = urlencode({
        "client_id":     client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    }).encode()
    req = Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            token = result.get("access_token")
            scope = result.get("scope", "")
            print(f"[INFO] トークンスコープ: {scope}")
            return token
    except Exception as e:
        print(f"[WARN] OAuth トークン交換失敗: {e}")
        return None

# ──────────────────────────────────────────────────────────
# YouTube Analytics API v2 ヘルパー
# ──────────────────────────────────────────────────────────
def analytics_get(access_token, params):
    url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urlencode(params)
    req = Request(url)
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            if "rows" not in body:
                print(f"[DEBUG] Analytics rows なし: {json.dumps(body, ensure_ascii=False)[:300]}")
            return body
    except HTTPError as e:
        body = json.loads(e.read())
        err  = body.get("error", {})
        print(f"[ERROR] Analytics HTTP {e.code}: {err.get('message', str(body))}")
        return None
    except Exception as e:
        print(f"[ERROR] Analytics リクエスト失敗: {e}")
        return None

# ──────────────────────────────────────────────────────────
# Analytics: チャンネル日次（views / 視聴時間 / 登録者増減）
# ──────────────────────────────────────────────────────────
def fetch_channel_analytics_daily(access_token, start_date, end_date):
    """
    チャンネル日次データ → [{date, views, watch_min, subs_gained, subs_lost}]
    Analytics API は dimensions=day で pageToken を返さない（maxResults=200 が実質上限）。
    180日チャンクに分割して全期間を取得する。
    """
    result   = []
    s        = date.fromisoformat(start_date)
    e        = date.fromisoformat(end_date)
    chunk    = 180   # 200 未満で余裕を持たせる

    while s <= e:
        ce     = min(s + timedelta(days=chunk - 1), e)
        params = {
            "ids":        f"channel=={CHANNEL_ID}",
            "dimensions": "day",
            "metrics":    "views,estimatedMinutesWatched,subscribersGained,subscribersLost",
            "startDate":  s.isoformat(),
            "endDate":    ce.isoformat(),
            "sort":       "day",
            "maxResults": 200,
        }
        data = analytics_get(access_token, params)
        if data and "rows" in data:
            for row in data["rows"]:
                result.append({
                    "date":        row[0],
                    "views":       int(float(row[1])),
                    "watch_min":   int(float(row[2])),
                    "subs_gained": int(float(row[3])),
                    "subs_lost":   int(float(row[4])),
                })
        s = ce + timedelta(days=1)

    return result

# ──────────────────────────────────────────────────────────
# Analytics: 動画別期間合計（pageToken ページング、startIndex 廃止）
# ──────────────────────────────────────────────────────────
def fetch_video_period(access_token, days):
    """
    指定日数の動画別合計 → {vid_id: {views, watch_min, avg_dur_sec}}
    dimensions=video は v2 で pageToken によるページングを使用
    """
    end_date   = (date.today() - timedelta(days=1)).isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    print(f"  {days}日間 ({start_date}〜{end_date})", end=" ... ", flush=True)

    result     = {}
    page_token = None

    while True:
        params = {
            "ids":        f"channel=={CHANNEL_ID}",
            "dimensions": "video",
            "metrics":    "views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
            "startDate":  start_date,
            "endDate":    end_date,
            "sort":       "-views",
            "maxResults": 200,
        }
        if page_token:
            params["pageToken"] = page_token

        data = analytics_get(access_token, params)
        if not data or "rows" not in data:
            break

        for row in data["rows"]:
            vid_id = row[0]
            result[vid_id] = {
                "views":       int(float(row[1])),
                "watch_min":   int(float(row[2])),
                "avg_dur_sec": int(float(row[3])),
                "subs_gained": int(float(row[4])) if len(row) > 4 else 0,
            }

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    print(f"{len(result)} 本")
    return result

# ──────────────────────────────────────────────────────────
# Analytics: 動画別日次データ（上位 N 本、過去 days 日）
# ──────────────────────────────────────────────────────────
def fetch_video_daily_all(access_token, all_video_ids, days=365):
    """
    全動画の日別再生数を取得（days 日分）。
    Returns: {vid_id: [{date, views, watch_min}]}
    """
    import time

    end_date   = (date.today() - timedelta(days=1)).isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    total      = len(all_video_ids)

    print(f"  動画別日次 {days}日 × {total} 本 (API {total}回)...")

    result = {}
    for i, vid_id in enumerate(all_video_ids):
        if (i+1) % 50 == 0 or i+1 == total:
            print(f"    [{i+1}/{total}]", flush=True)
        data = analytics_get(access_token, {
            "ids":        f"channel=={CHANNEL_ID}",
            "dimensions": "day",
            "filters":    f"video=={vid_id}",
            "metrics":    "views,estimatedMinutesWatched",
            "startDate":  start_date,
            "endDate":    end_date,
            "sort":       "day",
            "maxResults": 400,
        })
        if data and data.get("rows"):
            result[vid_id] = [
                {"date": row[0], "views": int(float(row[1])), "watch_min": int(float(row[2]))}
                for row in data["rows"]
            ]
        # レート制限対策: 0.1秒待機
        time.sleep(0.1)

    print(f"  完了: {len(result)} 本 / {total} 本にデータあり")
    return result

# ──────────────────────────────────────────────────────────
# Analytics: チャンネル追加データ（28日）
#   - CTR / インプレッション / 平均視聴率
#   - トラフィックソース
#   - 国別視聴 Top10
#   - 新規 vs リピーター（subscribedStatus）
# ──────────────────────────────────────────────────────────
TRAFFIC_SOURCE_LABELS = {
    "0":  "直接/不明",
    "1":  "広告",
    "3":  "ブラウズ機能",
    "4":  "チャンネルページ",
    "5":  "外部サイト",
    "7":  "Google 検索",
    "8":  "その他",
    "9":  "YouTube 検索",
    "10": "動画関連",
    "11": "再生リスト",
    "14": "アノテーション",
    "17": "プロモーション",
    "18": "エンドスクリーン",
    "19": "通知",
    "20": "再生リストページ",
    "21": "チャンネルページ",
    "22": "登録フィード",
}

def fetch_channel_extra_analytics(access_token, days=28, shorts_ids=None):
    """
    チャンネル追加 Analytics（28日間）
    Returns dict with keys: ctr, traffic_sources, traffic_sources_shorts, top_countries, subscribed_status, jp_daily
    shorts_ids: ショート動画のvideo_idリスト（指定時はショート限定の流入経路も取得）
    """
    end_date   = (date.today() - timedelta(days=1)).isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    result     = {"period_days": days, "start_date": start_date, "end_date": end_date}

    # ── CTR / インプレッション（dimensions=day が必要な指標はdimension付きで取得）──
    data = analytics_get(access_token, {
        "ids":        f"channel=={CHANNEL_ID}",
        "dimensions": "day",
        "metrics":    "views,estimatedMinutesWatched,averageViewPercentage",
        "startDate":  start_date,
        "endDate":    end_date,
        "sort":       "day",
        "maxResults": 200,
    })
    if data and data.get("rows"):
        rows = data["rows"]
        total_views    = sum(int(float(r[1])) for r in rows)
        total_min      = sum(int(float(r[2])) for r in rows)
        avg_view_pct   = round(sum(float(r[3]) for r in rows) / len(rows), 1) if rows else 0
        result["ctr"] = {
            "views":        total_views,
            "impressions":  0,        # impressions は dimensions=video 等がないと取得不可
            "ctr_pct":      0.0,      # CTR も同様
            "avg_view_pct": avg_view_pct,
        }
        print(f"  再生数({days}日): {total_views:,}  平均視聴率: {avg_view_pct}%")
    else:
        print("  [WARN] CTR データ取得失敗")

    # ── トラフィックソース ──
    data = analytics_get(access_token, {
        "ids":        f"channel=={CHANNEL_ID}",
        "dimensions": "insightTrafficSourceType",
        "metrics":    "views,estimatedMinutesWatched",
        "startDate":  start_date,
        "endDate":    end_date,
        "sort":       "-views",
        "maxResults": 20,
    })
    if data and data.get("rows"):
        result["traffic_sources"] = [
            {
                "source_type": row[0],
                "label":  TRAFFIC_SOURCE_LABELS.get(str(row[0]), f"その他({row[0]})"),
                "views":      int(float(row[1])),
                "watch_min":  int(float(row[2])),
            }
            for row in data["rows"]
        ]
        print(f"  トラフィックソース: {len(result['traffic_sources'])} 種")
    else:
        print("  [WARN] トラフィックソース取得失敗")

    # ── ショート動画限定の流入経路（video ID フィルタ、上限500本）──
    if shorts_ids:
        data = analytics_get(access_token, {
            "ids":        f"channel=={CHANNEL_ID}",
            "dimensions": "insightTrafficSourceType",
            "metrics":    "views,estimatedMinutesWatched",
            "filters":    "video==" + ",".join(shorts_ids[:500]),
            "startDate":  start_date,
            "endDate":    end_date,
            "sort":       "-views",
            "maxResults": 20,
        })
        if data and data.get("rows"):
            result["traffic_sources_shorts"] = [
                {
                    "source_type": row[0],
                    "label":  TRAFFIC_SOURCE_LABELS.get(str(row[0]), f"その他({row[0]})"),
                    "views":      int(float(row[1])),
                    "watch_min":  int(float(row[2])),
                }
                for row in data["rows"]
            ]
            print(f"  ショート限定トラフィック: {len(result['traffic_sources_shorts'])} 種 ({len(shorts_ids)} 本対象)")
        else:
            print("  [WARN] ショート限定トラフィック取得失敗")

    # ── 国別 Top15 ──
    # ※ province ディメンションは US のみ対応のため country ディメンションを使用
    data = analytics_get(access_token, {
        "ids":        f"channel=={CHANNEL_ID}",
        "dimensions": "country",
        "metrics":    "views,estimatedMinutesWatched",
        "startDate":  start_date,
        "endDate":    end_date,
        "sort":       "-views",
        "maxResults": 15,
    })
    if data and data.get("rows"):
        result["top_countries"] = [
            {
                "country":   row[0],
                "views":     int(float(row[1])),
                "watch_min": int(float(row[2])),
            }
            for row in data["rows"]
        ]
        print(f"  国別Top5: {[r['country'] for r in result['top_countries'][:5]]}")
    else:
        print("  [WARN] 国別データ取得失敗")

    # ── 日本国内の日次推移（filters=country==JP）──
    data = analytics_get(access_token, {
        "ids":        f"channel=={CHANNEL_ID}",
        "dimensions": "day",
        "filters":    "country==JP",
        "metrics":    "views,estimatedMinutesWatched",
        "startDate":  start_date,
        "endDate":    end_date,
        "sort":       "day",
        "maxResults": 200,
    })
    if data and data.get("rows"):
        result["jp_daily"] = [
            {"date": row[0], "views": int(float(row[1])), "watch_min": int(float(row[2]))}
            for row in data["rows"]
        ]
        print(f"  日本国内 日次: {len(result['jp_daily'])} 日分")
    else:
        print("  [WARN] 日本国内 日次データ取得失敗")

    # ── 日本国内 都市別 Top25（city ディメンションは2022年以降のデータで利用可）──
    data = analytics_get(access_token, {
        "ids":        f"channel=={CHANNEL_ID}",
        "dimensions": "city",
        "filters":    "country==JP",
        "metrics":    "views,estimatedMinutesWatched",
        "startDate":  start_date,
        "endDate":    end_date,
        "sort":       "-views",
        "maxResults": 25,
    })
    if data and data.get("rows"):
        result["jp_cities"] = [
            {"city": row[0], "views": int(float(row[1])), "watch_min": int(float(row[2]))}
            for row in data["rows"]
        ]
        print(f"  日本国内 都市別: {len(result['jp_cities'])} 都市 (首位: {result['jp_cities'][0]['city']})")
    else:
        print("  [WARN] 日本国内 都市別データ取得失敗")

    # ── 新規 vs リピーター ──
    data = analytics_get(access_token, {
        "ids":        f"channel=={CHANNEL_ID}",
        "dimensions": "subscribedStatus",
        "metrics":    "views,estimatedMinutesWatched",
        "startDate":  start_date,
        "endDate":    end_date,
    })
    if data and data.get("rows"):
        result["subscribed_status"] = {
            row[0]: {
                "views":     int(float(row[1])),
                "watch_min": int(float(row[2])),
            }
            for row in data["rows"]
        }
        sub   = result["subscribed_status"].get("SUBSCRIBED",   {}).get("views", 0)
        unsub = result["subscribed_status"].get("UNSUBSCRIBED", {}).get("views", 0)
        total = sub + unsub
        if total > 0:
            print(f"  登録者: {sub/total*100:.0f}%  非登録者: {unsub/total*100:.0f}%")
    else:
        print("  [WARN] 登録者別データ取得失敗")

    return result

# ──────────────────────────────────────────────────────────
# Analytics: 動画別追加分析（国別 / 登録者別）上位 N 本
# ──────────────────────────────────────────────────────────
def fetch_video_extra_analytics(access_token, top_video_ids, days=365):
    """
    動画別の国別視聴 Top5 / 新規vsリピーター / 流入経路 を取得。
    - 国別・登録者別・流入経路: filters=video==VID_ID + dimensions=insightTrafficSourceType
    top_video_ids: 取得対象の video_id リスト（上位 N 本）
    Returns: {vid_id: {top_countries, subscribed_status, traffic_sources}}
    """
    import time

    end_date   = (date.today() - timedelta(days=1)).isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    n = len(top_video_ids)
    print(f"  {n} 本 × 3指標 ({start_date}〜{end_date})...")

    result = {}
    for i, vid_id in enumerate(top_video_ids):
        r = {}

        # 国別 Top8（province は US 専用のため country に変更）
        data = analytics_get(access_token, {
            "ids":        f"channel=={CHANNEL_ID}",
            "dimensions": "country",
            "filters":    f"video=={vid_id}",
            "metrics":    "views",
            "startDate":  start_date,
            "endDate":    end_date,
            "sort":       "-views",
            "maxResults": 8,
        })
        if data and data.get("rows"):
            r["top_countries"] = [
                {"country": row[0], "views": int(float(row[1]))}
                for row in data["rows"]
            ]
        time.sleep(0.1)

        # 登録者別（新規 vs リピーター）
        data = analytics_get(access_token, {
            "ids":        f"channel=={CHANNEL_ID}",
            "dimensions": "subscribedStatus",
            "filters":    f"video=={vid_id}",
            "metrics":    "views",
            "startDate":  start_date,
            "endDate":    end_date,
        })
        if data and data.get("rows"):
            r["subscribed_status"] = {
                row[0]: int(float(row[1]))
                for row in data["rows"]
            }
        time.sleep(0.1)

        # 流入経路 Top8（insightTrafficSourceType + filters=video==VID_ID）
        data = analytics_get(access_token, {
            "ids":        f"channel=={CHANNEL_ID}",
            "dimensions": "insightTrafficSourceType",
            "filters":    f"video=={vid_id}",
            "metrics":    "views",
            "startDate":  start_date,
            "endDate":    end_date,
            "sort":       "-views",
            "maxResults": 8,
        })
        if data and data.get("rows"):
            r["traffic_sources"] = [
                {"source_type": row[0], "views": int(float(row[1]))}
                for row in data["rows"]
            ]
        time.sleep(0.1)

        if r:
            result[vid_id] = r

        if (i + 1) % 10 == 0 or i + 1 == n:
            print(f"    [{i+1}/{n}]", flush=True)

    print(f"  完了: {len(result)} 本にデータ取得")
    return result

# ──────────────────────────────────────────────────────────
# 週次レポート（毎週 土〜金 JST。土曜朝の実行で速報生成 → 確定値が揃い次第更新）
# ──────────────────────────────────────────────────────────
WEEKLY_REPORT_BACKFILL_WEEKS = 8    # 遡って生成する週数
WEEKLY_REPORT_KEEP           = 26   # 保持する週数

def _jst_today():
    """JST の今日（Actions は UTC で動くため明示変換）"""
    return (datetime.now(timezone.utc) + timedelta(hours=9)).date()

def _interp_cum(daily_rows, key, target):
    """daily の累積値（total_views / subscribers）を日付 target で線形補間。範囲外は None"""
    pts = sorted(
        (date.fromisoformat(r["date"]), r[key])
        for r in daily_rows if r.get(key)
    )
    if not pts or target < pts[0][0] or target > pts[-1][0]:
        return None
    prev = pts[0]
    for p in pts:
        if p[0] == target:
            return p[1]
        if p[0] > target:
            span = (p[0] - prev[0]).days
            if span <= 0:
                return p[1]
            frac = (target - prev[0]).days / span
            return prev[1] + (p[1] - prev[1]) * frac
        prev = p
    return pts[-1][1]

def fetch_week_traffic(access_token, start, end):
    """指定期間の流入経路・登録者別 views を取得"""
    import time
    out = {}
    data = analytics_get(access_token, {
        "ids":        f"channel=={CHANNEL_ID}",
        "dimensions": "insightTrafficSourceType",
        "metrics":    "views",
        "startDate":  start,
        "endDate":    end,
        "sort":       "-views",
        "maxResults": 10,
    })
    if data and data.get("rows"):
        out["traffic_sources"] = [
            {"source_type": row[0], "views": int(float(row[1]))}
            for row in data["rows"]
        ]
    time.sleep(0.1)
    data = analytics_get(access_token, {
        "ids":        f"channel=={CHANNEL_ID}",
        "dimensions": "subscribedStatus",
        "metrics":    "views",
        "startDate":  start,
        "endDate":    end,
    })
    if data and data.get("rows"):
        out["subscribed_status"] = {row[0]: int(float(row[1])) for row in data["rows"]}
    time.sleep(0.1)
    return out

def _parse_plan_date(s):
    """'2026/6/1' 形式 → date。失敗は None"""
    try:
        p = [int(x) for x in str(s).strip().split("/")]
        if len(p) == 3:
            return date(p[0], p[1], p[2])
    except Exception:
        pass
    return None

# ──────────────────────────────────────────────────────────
# 投稿計画 × YouTube実績 の自動照合
# ──────────────────────────────────────────────────────────
def _norm_title(s):
    """タイトル正規化（全半角統一・空白除去・小文字化）"""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    return "".join(ch for ch in s if not ch.isspace())

def match_post_plan(post_plan, videos):
    """計画行と公開済み動画を自動照合し、行に _matched_* フィールドを付与する。
    優先順位: 1) URL列のvideo_id完全一致（列があれば） 2) タイトル類似度×予定日±7日
    シート側のステータス更新に依存せず「実際に投稿されたか」を判定するための仕組み。"""
    import re, difflib

    vids = []
    for v in videos:
        pub = (v.get("published_at") or "")[:10]
        vids.append((v, pub, _norm_title(v.get("title"))))

    used = set()
    for row in post_plan:
        for k in ("_matched_video_id", "_matched_published_at", "_matched_title",
                  "_matched_duration_sec", "_delay_days", "_match_method"):
            row.pop(k, None)

        pd_ = _parse_plan_date(row.get("投稿予定日", ""))
        best, method = None, None

        # 1) URL列（残っていれば最優先・確実）
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", row.get("URL") or "")
        if m:
            for v, pub, nt in vids:
                if v["video_id"] == m.group(1):
                    best, method = (v, pub), "url"
                    break

        # 2) タイトル類似度 × 予定日近傍（±7日）
        if best is None and row.get("タイトル") and pd_:
            nt_plan = _norm_title(row["タイトル"])
            cands = []
            for v, pub, nt in vids:
                if not pub or v["video_id"] in used:
                    continue
                try:
                    dd = abs((date.fromisoformat(pub) - pd_).days)
                except Exception:
                    continue
                if dd > 7:
                    continue
                ratio = difflib.SequenceMatcher(None, nt_plan, nt).ratio()
                if ratio >= 0.60:
                    cands.append((ratio, -dd, v, pub))
            if cands:
                cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
                _, _, v, pub = cands[0]
                best, method = (v, pub), "title"

        if best:
            v, pub = best
            used.add(v["video_id"])
            row["_matched_video_id"]     = v["video_id"]
            row["_matched_published_at"] = pub
            row["_matched_title"]        = v.get("title", "")
            row["_matched_duration_sec"] = v.get("duration_sec")
            row["_match_method"]         = method
            if pd_ and pub:
                try:
                    row["_delay_days"] = (date.fromisoformat(pub) - pd_).days
                except Exception:
                    pass
    return post_plan

def build_weekly_report(week_start, week_end, *, daily, analytics_daily,
                        video_daily, videos, post_plan, week_extra, prev_week_extra):
    """1週分（土〜金）のレポートを組み立てる"""
    ws, we   = week_start, week_end
    pws, pwe = ws - timedelta(days=7), we - timedelta(days=7)
    ad = {r["date"]: r for r in analytics_daily}

    def win_days(s, e):
        return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]

    def sum_ad(s, e):
        rows = [ad[d] for d in win_days(s, e) if d in ad]
        return {
            "views":       sum(r.get("views", 0)       for r in rows),
            "watch_min":   sum(r.get("watch_min", 0)   for r in rows),
            "subs_gained": sum(r.get("subs_gained", 0) for r in rows),
            "subs_lost":   sum(r.get("subs_lost", 0)   for r in rows),
            "days":        len(rows),
        }

    cur, prv = sum_ad(ws, we), sum_ad(pws, pwe)

    # 実測（daily スナップショット補間）による速報値
    def snap_diff(key, s, e):
        a = _interp_cum(daily, key, s - timedelta(days=1))
        b = _interp_cum(daily, key, e)
        if a is None or b is None:
            return None
        return int(round(b - a))

    # 動画別の週間 views（video_daily を期間合計）
    def video_week(s, e):
        dset = set(win_days(s, e))
        out = {}
        for vid, rows in video_daily.items():
            v = sum(r.get("views", 0) for r in rows if r.get("date") in dset)
            if v > 0:
                out[vid] = v
        return out

    vw, vw_prev = video_week(ws, we), video_week(pws, pwe)
    vmeta = {v["video_id"]: v for v in videos}
    top_videos = [{
        "video_id":        vid,
        "title":           vmeta.get(vid, {}).get("title", ""),
        "published_at":    vmeta.get(vid, {}).get("published_at", ""),
        "views_week":      vw[vid],
        "views_prev_week": vw_prev.get(vid, 0),
    } for vid in sorted(vw, key=vw.get, reverse=True)[:10]]

    # 週内に公開された動画
    new_videos = sorted([{
        "video_id":     v["video_id"],
        "title":        v["title"],
        "published_at": v["published_at"],
        "views_total":  v.get("views", 0),
    } for v in videos
        if ws.isoformat() <= (v.get("published_at") or "")[:10] <= we.isoformat()],
        key=lambda v: v["published_at"])

    # 投稿計画の進捗（自動照合結果があればそれを優先して投稿済み判定）
    planned = []
    for row in post_plan:
        pd_ = _parse_plan_date(row.get("投稿予定日", ""))
        if pd_ and ws <= pd_ <= we:
            planned.append({
                "date":    pd_.isoformat(),
                "title":   row.get("タイトル", ""),
                "status":  row.get("ステータス", ""),
                "owner":   row.get("担当", ""),
                "type":     row.get("企画タイプ", ""),
                "narrator": row.get("ナレーター", ""),
                "ads":      row.get("動画内広告", ""),
                "matched": bool(row.get("_matched_video_id")),
                "video_id": row.get("_matched_video_id", ""),
                "published_at": row.get("_matched_published_at", ""),
                "delay_days":   row.get("_delay_days"),
            })
    posted_cnt = sum(1 for p in planned if p["matched"] or "済" in p["status"])

    report = {
        "week_start":     ws.isoformat(),
        "week_end":       we.isoformat(),
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "confirmed_days": cur["days"],
        "channel": {
            "views":           cur["views"],
            "views_prev":      prv["views"],
            "views_snap":      snap_diff("total_views", ws, we),
            "views_snap_prev": snap_diff("total_views", pws, pwe),
            "watch_min":       cur["watch_min"],
            "watch_min_prev":  prv["watch_min"],
            "subs_net":        snap_diff("subscribers", ws, we),
            "subs_net_prev":   snap_diff("subscribers", pws, pwe),
            "subs_gained":     cur["subs_gained"],
            "subs_lost":       cur["subs_lost"],
            "subscribers_end": _interp_cum(daily, "subscribers", we),
        },
        "top_videos": top_videos,
        "new_videos": new_videos,
        "post_plan":  {"planned": len(planned), "posted": posted_cnt, "items": planned},
    }
    if week_extra:
        report["traffic_sources"]   = week_extra.get("traffic_sources", [])
        report["subscribed_status"] = week_extra.get("subscribed_status", {})
    if prev_week_extra:
        report["traffic_sources_prev"]   = prev_week_extra.get("traffic_sources", [])
        report["subscribed_status_prev"] = prev_week_extra.get("subscribed_status", {})
    return report

def update_weekly_reports(weekly_reports, access_token, *, daily, analytics_daily,
                          video_daily, videos, post_plan):
    """完了した週（土〜金）のレポートを生成・更新して返す。
    確定値が揃う（週末+3日）までは速報として毎日更新し、揃ったら final=True で固定。"""
    today_j = _jst_today()
    days_since_sat = (today_j.weekday() - 5) % 7          # 土曜=5
    cur_week_start = today_j - timedelta(days=days_since_sat)
    last_end       = cur_week_start - timedelta(days=1)   # 直近の完了週の金曜
    existing = {r["week_start"]: r for r in weekly_reports}

    extra_cache = {}
    def get_extra(s, e):
        key = s.isoformat()
        if key in extra_cache:
            return extra_cache[key]
        r = existing.get(key)
        if r and r.get("final") and "traffic_sources" in r:
            extra_cache[key] = {
                "traffic_sources":   r["traffic_sources"],
                "subscribed_status": r.get("subscribed_status", {}),
            }
        elif access_token:
            extra_cache[key] = fetch_week_traffic(access_token, s.isoformat(), e.isoformat())
        else:
            extra_cache[key] = {}
        return extra_cache[key]

    for i in range(WEEKLY_REPORT_BACKFILL_WEEKS):
        we = last_end - timedelta(days=7 * i)
        ws = we - timedelta(days=6)
        key = ws.isoformat()
        old = existing.get(key)
        if old and old.get("final"):
            continue
        rep = build_weekly_report(
            ws, we,
            daily=daily, analytics_daily=analytics_daily, video_daily=video_daily,
            videos=videos, post_plan=post_plan,
            week_extra=get_extra(ws, we),
            prev_week_extra=get_extra(ws - timedelta(days=7), we - timedelta(days=7)),
        )
        # AI分析(別プロセスが書き込む)は再生成時も引き継ぐ
        if old and old.get("ai_analysis"):
            rep["ai_analysis"] = old["ai_analysis"]
        # 確定条件: 日付経過 + Analytics が7日分揃っている + (トークンありなら流入経路も取得済み)
        rep["final"] = (
            today_j >= we + timedelta(days=3)
            and rep.get("confirmed_days", 0) >= 7
            and (not access_token or "traffic_sources" in rep)
        )
        existing[key] = rep
        print(f"  {ws}〜{we}: {'確定' if rep['final'] else '速報'}生成")

    reports = sorted(existing.values(), key=lambda r: r["week_start"])
    return reports[-WEEKLY_REPORT_KEEP:]

# ──────────────────────────────────────────────────────────
# 既存 data.json 読み込み
# ──────────────────────────────────────────────────────────
def load_existing_data():
    if not os.path.exists(OUTPUT_FILE):
        return [], [], [], {}, {}, {}, [], {}, [], []

    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            ex = json.load(f)

        daily = [
            d for d in ex.get("daily", [])
            if d.get("subscribers", 0) > 0 or d.get("total_views", 0) > 0
        ]
        analytics_daily       = ex.get("analytics_daily",       [])
        video_snapshots       = ex.get("video_snapshots",       [])
        video_period          = ex.get("video_period",          {})
        analytics_extra       = ex.get("analytics_extra",       {})
        video_daily           = ex.get("video_daily",           {})
        post_plan             = ex.get("post_plan",             [])
        video_analytics_extra = ex.get("video_analytics_extra", {})
        prev_videos           = ex.get("videos",                [])
        weekly_reports        = ex.get("weekly_reports",        [])

        return daily, analytics_daily, video_snapshots, video_period, analytics_extra, video_daily, post_plan, video_analytics_extra, prev_videos, weekly_reports

    except Exception as e:
        print(f"[WARN] 既存データ読み込み失敗: {e}")
        return [], [], [], {}, {}, {}, [], {}, [], []

# ──────────────────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────────────────
def main():
    api_key = get_api_key()
    today   = date.today().isoformat()

    # ── チャンネル統計 ──
    print("[1/6] チャンネル統計を取得中...")
    ch = fetch_channel_stats(api_key)
    print(f"  登録者: {ch['subscribers']:,}  総再生数: {ch['total_views']:,}  動画: {ch['video_count']}")

    # ── 動画リスト ──
    print("[2/6] 動画リストを取得中...")
    ids    = fetch_video_ids(api_key)
    videos = fetch_video_details(api_key, ids)
    print(f"  {len(videos)} 本取得")

    # ── 既存データ読み込み ──
    daily, analytics_daily, video_snapshots, video_period, analytics_extra, video_daily, post_plan, video_analytics_extra, prev_videos, weekly_reports = load_existing_data()

    # videos が空の場合は前回データを保持（API エラー・クォータ超過対策）
    if not videos and prev_videos:
        print(f"  [WARN] 動画リスト取得失敗 — 前回データ {len(prev_videos)} 本を保持")
        videos = prev_videos
        ids    = [v["video_id"] for v in videos]
    print(f"[INFO] 既存: チャンネル {len(daily)} 日 / Analytics {len(analytics_daily)} 日 / スナップショット {len(video_snapshots)} 日")

    # ── チャンネル日次スナップショット更新 ──
    daily = [d for d in daily if d["date"] != today]
    daily.append({
        "date":        today,
        "subscribers": ch["subscribers"],
        "total_views": ch["total_views"],
        "video_count": ch["video_count"],
    })
    daily.sort(key=lambda d: d["date"])

    # ── 動画 views スナップショット更新 ──
    print("[3/6] 動画スナップショットを取得中...")
    snap_views = fetch_video_snapshot(api_key, ids)
    # 既存から今日分を除去して追加
    video_snapshots = [s for s in video_snapshots if s["date"] != today]
    video_snapshots.append({"date": today, "v": snap_views})
    video_snapshots.sort(key=lambda s: s["date"])
    # 古いデータを削除
    cutoff = (date.today() - timedelta(days=SNAPSHOT_KEEP_DAYS)).isoformat()
    video_snapshots = [s for s in video_snapshots if s["date"] >= cutoff]
    print(f"  {len(snap_views)} 本スナップショット完了 / 保持: {len(video_snapshots)} 日分")

    # ── Analytics API ──
    access_token = load_access_token()
    if access_token:
        print("[INFO] OAuth2 トークン OK")

        # チャンネル Analytics 日次（チャンネル開設日〜昨日、全期間）
        print("[4/7] チャンネル Analytics 日次を取得中（全期間）...")
        anal_start = ch.get("published_at", "2020-01-01")  # チャンネル開設日
        anal_end   = (date.today() - timedelta(days=1)).isoformat()
        new_daily  = fetch_channel_analytics_daily(access_token, anal_start, anal_end)
        if new_daily:
            # マージ（日付ベースで上書き）
            anal_map = {d["date"]: d for d in analytics_daily}
            for d in new_daily:
                anal_map[d["date"]] = d
            analytics_daily = sorted(anal_map.values(), key=lambda x: x["date"])
            print(f"  {len(analytics_daily)} 日分")
        else:
            print("  [WARN] チャンネル Analytics 日次取得失敗")

        # 動画別期間合計（7/28/90/365日）
        print("[5/7] 動画別期間合計を取得中...")
        periods = [7, 28, 90, 365]
        new_period = {}
        for days in periods:
            result = fetch_video_period(access_token, days)
            if result:
                new_period[str(days)] = result
        if new_period:
            video_period = new_period
        else:
            print("  [WARN] 動画別期間合計取得失敗 — 前回データを保持")

        # 動画別日次データ（全動画 × 365日）
        print("[6/7] 動画別日次データを取得中...")
        new_video_daily = fetch_video_daily_all(access_token, ids, days=365)
        if new_video_daily:
            video_daily = new_video_daily
        else:
            print("  [WARN] 動画別日次取得失敗 — 前回データを保持")

        # チャンネル追加 Analytics（CTR / トラフィック / 国別 / 登録者別）
        print("[7/9] チャンネル追加 Analytics を取得中...")
        shorts_ids = [v["video_id"] for v in videos if (v.get("duration_sec") or 0) <= 180]
        new_extra = fetch_channel_extra_analytics(access_token, days=28, shorts_ids=shorts_ids)
        if new_extra:
            analytics_extra = new_extra
        else:
            print("  [WARN] 追加 Analytics 取得失敗 — 前回データを保持")

        # 動画別追加分析（国別 / 登録者別）上位 30 本
        print("[8/9] 動画別追加分析を取得中（国別 / 新規vsリピーター）...")
        # 365日の視聴数上位 30 本を対象
        p365 = video_period.get("365", {})
        top_ids = sorted(p365.keys(), key=lambda v: p365[v].get("views", 0), reverse=True)[:30]
        if not top_ids:
            # video_period が空なら videos から上位を選ぶ
            top_ids = [v["video_id"] for v in videos[:30]]
        new_vextra = fetch_video_extra_analytics(access_token, top_ids, days=365)
        if new_vextra:
            video_analytics_extra = new_vextra
        else:
            print("  [WARN] 動画別追加分析取得失敗 — 前回データを保持")

    else:
        print("[WARN] OAuth トークンなし → Analytics スキップ（Data API のみ）")
        print("  GitHub Secrets に REFRESH_TOKEN / OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET を設定してください")

    # ── 投稿計画（Google スプレッドシート）──
    print("[9/9] 投稿計画スプレッドシートを取得中...")
    new_post_plan = fetch_post_plan()
    if new_post_plan:
        post_plan = new_post_plan
    else:
        print("  [WARN] 取得失敗 — 前回データを保持")

    # ── 計画 × 実績の自動照合（シートのステータス更新に依存しない投稿済み判定）──
    try:
        post_plan = match_post_plan(post_plan, videos)
        matched = sum(1 for r in post_plan if r.get("_matched_video_id"))
        print(f"  自動照合: {matched}/{len(post_plan)} 行が公開動画と一致")
    except Exception as e:
        print(f"  [WARN] 自動照合失敗 — 照合なしで続行: {e}")

    # ── 週次レポート（土〜金、速報→確定で自動更新）──
    print("[10/10] 週次レポートを生成中...")
    try:
        weekly_reports = update_weekly_reports(
            weekly_reports, access_token,
            daily=daily, analytics_daily=analytics_daily,
            video_daily=video_daily, videos=videos, post_plan=post_plan,
        )
    except Exception as e:
        print(f"  [WARN] 週次レポート生成失敗 — 前回データを保持: {e}")

    # ── データ書き出し ──
    print("data.json を書き出し中...")
    output = {
        "meta": {
            "channel_id":    CHANNEL_ID,
            "channel_title": ch["title"],
            "fetched_at":    datetime.now(timezone.utc).isoformat(),
            "data_through":  today,
            "since":         daily[0]["date"] if daily else today,
            "snapshot_days": len(video_snapshots),
        },
        "daily":            daily,           # チャンネル日次スナップショット
        "analytics_daily":  analytics_daily, # Analytics 日次（views/視聴時間/登録者増減）
        "video_snapshots":  video_snapshots, # 動画別 views スナップショット（毎日）
        "video_period":     video_period,    # 動画別期間合計 {"7":{vid:{views,watch_min,avg_dur_sec,impressions,ctr}}}
        "analytics_extra":  analytics_extra, # CTR/トラフィック/国別/登録者別（28日）
        "video_daily":           video_daily,           # 動画別日次（全動画 × 365日）{vid_id:[{date,views,watch_min}]}
        "video_analytics_extra": video_analytics_extra, # 動画別追加分析（国別/登録者別）上位30本
        "videos":                videos,                # 動画メタデータ + 現在 stats
        "post_plan":             post_plan,             # 投稿計画（Google スプレッドシート）
        "weekly_reports":        weekly_reports,        # 週次レポート（土〜金、最大26週）
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] {OUTPUT_FILE} 書き出し完了")
    print(f"  チャンネルスナップ: {len(daily)} 日 / Analytics日次: {len(analytics_daily)} 日")
    print(f"  動画スナップ: {len(video_snapshots)} 日 / 動画期間データ: {list(video_period.keys())}")
    extra_ctr = analytics_extra.get("ctr", {})
    print(f"  追加Analytics: CTR={extra_ctr.get('ctr_pct','N/A')}%  トラフィック={len(analytics_extra.get('traffic_sources',[]))}種  国={len(analytics_extra.get('top_countries',[]))}")
    print(f"  動画数: {len(videos)}")
    print(f"  動画別追加分析: {len(video_analytics_extra)} 本")
    print(f"  投稿計画: {len(post_plan)} 件")
    print(f"  週次レポート: {len(weekly_reports)} 週分")

if __name__ == "__main__":
    main()
