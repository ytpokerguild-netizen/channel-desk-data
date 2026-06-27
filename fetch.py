#!/usr/bin/env python3
"""
CHANNEL DESK — データ取得スクリプト (フェーズ2)
毎朝 GitHub Actions から実行する。data.json を生成してコミット。

【ローカル実行】
  python fetch.py
  → ~/Downloads/token.json と client_secret.json を使う（diag.py と同じ）

【GitHub Actions 実行】
  環境変数から読む（Secrets に登録）:
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    GOOGLE_REFRESH_TOKEN

出力: data.json（データ契約 v1）
"""

import json
import os
import sys
from datetime import date, timedelta, datetime, timezone

# ──────────────────────────────────────────
# 設定
# ──────────────────────────────────────────
DATA_THROUGH_LAG = 3        # 何日遅れで取得するか（Analytics確定ラグ）
HISTORY_DAYS     = 365      # 初回: 何日分の日次を遡るか
CHANNEL_ID       = "MINE"   # 自社チャンネル（変更不要）
OUTPUT_FILE      = "data.json"
TOKEN_FILE       = os.path.expanduser("~/Downloads/token.json")
SECRET_FILE      = os.path.expanduser("~/Downloads/client_secret.json")

SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# ──────────────────────────────────────────
# 認証
# ──────────────────────────────────────────
def get_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    # GitHub Actions: 環境変数から直接組み立て
    client_id     = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")

    if client_id and client_secret and refresh_token:
        print("[AUTH] 環境変数からクレデンシャルを読み込み")
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return creds

    # ローカル: token.json から読み込み
    if not os.path.exists(TOKEN_FILE):
        print(f"[ERROR] {TOKEN_FILE} が見つかりません。先に diag.py を実行してトークンを取得してください。")
        sys.exit(1)

    print(f"[AUTH] {TOKEN_FILE} からクレデンシャルを読み込み")
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


# ──────────────────────────────────────────
# YouTube Analytics API ヘルパー
# ──────────────────────────────────────────
def query(service, metrics, dimensions, start_date, end_date, sort=None, max_results=None):
    params = dict(
        ids=f"channel=={CHANNEL_ID}",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics=metrics,
        dimensions=dimensions,
    )
    if sort:        params["sort"]       = sort
    if max_results: params["maxResults"] = max_results
    resp = service.reports().query(**params).execute()
    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    rows    = resp.get("rows", []) or []
    return headers, rows


def to_dict(headers, row):
    return dict(zip(headers, row))


def safe_int(v):   return int(v)   if v is not None else 0
def safe_float(v): return float(v) if v is not None else 0.0


# ──────────────────────────────────────────
# 既存 data.json を読み込んで差分取得に使う
# ──────────────────────────────────────────
def load_existing():
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def determine_fetch_range(existing):
    end   = date.today() - timedelta(days=DATA_THROUGH_LAG)
    if existing and existing.get("meta", {}).get("data_through"):
        last = date.fromisoformat(existing["meta"]["data_through"])
        # 最終取得日の翌日から（重複なし）
        start = last + timedelta(days=1)
    else:
        start = end - timedelta(days=HISTORY_DAYS - 1)
    return start, end


# ──────────────────────────────────────────
# 取得ロジック
# ──────────────────────────────────────────
def fetch_daily(service, start, end):
    """日次チャンネル指標"""
    print(f"[FETCH] 日次指標: {start} ～ {end}")
    rows_out = []

    # 基本指標
    headers, rows = query(
        service,
        metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,likes,comments",
        dimensions="day",
        start_date=start, end_date=end, sort="day",
    )
    base = {r[0]: to_dict(headers, r) for r in rows}  # date -> dict

    # 収益（失敗しても続行）
    rev_by_date = {}
    try:
        h2, r2 = query(service,
            metrics="estimatedRevenue",
            dimensions="day",
            start_date=start, end_date=end, sort="day",
        )
        for row in r2:
            d = to_dict(h2, row)
            rev_by_date[d["day"]] = d.get("estimatedRevenue", 0)
    except Exception as e:
        print(f"[WARN] 収益取得失敗（スキップ）: {e}")

    for dt, d in sorted(base.items()):
        rows_out.append({
            "date":               dt,
            "views":              safe_int(d.get("views", 0)),
            "watch_minutes":      safe_int(d.get("estimatedMinutesWatched", 0)),
            "subscribers_gained": safe_int(d.get("subscribersGained", 0)),
            "subscribers_lost":   safe_int(d.get("subscribersLost", 0)),
            "likes":              safe_int(d.get("likes", 0)),
            "comments":           safe_int(d.get("comments", 0)),
            "revenue_jpy":        round(safe_float(rev_by_date.get(dt, 0)) * 150),  # USD→JPY概算
        })
    return rows_out


def fetch_videos(service, start, end, top_n=50):
    """動画別指標（上位N本）"""
    print(f"[FETCH] 動画別: {start} ～ {end}  (上位{top_n}本)")
    try:
        headers, rows = query(service,
            metrics="views,estimatedMinutesWatched,likes,comments",
            dimensions="video",
            start_date=start, end_date=end,
            sort="-views", max_results=top_n,
        )
    except Exception as e:
        print(f"[WARN] 動画別取得失敗: {e}")
        return []

    # 動画タイトル取得（YouTube Data API v3）
    video_ids = [to_dict(headers, r)["video"] for r in rows]
    titles = fetch_titles(service._http, video_ids)

    out = []
    for row in rows:
        d = to_dict(headers, row)
        vid = d["video"]
        # 収益は動画別では省略（チャンネルレベルのみ）
        out.append({
            "video_id":      vid,
            "title":         titles.get(vid, ""),
            "views":         safe_int(d.get("views", 0)),
            "watch_minutes": safe_int(d.get("estimatedMinutesWatched", 0)),
            "likes":         safe_int(d.get("likes", 0)),
            "comments":      safe_int(d.get("comments", 0)),
        })
    return out


def fetch_titles(authorized_http, video_ids):
    """YouTube Data API v3 でタイトルを取得"""
    from googleapiclient.discovery import build
    if not video_ids:
        return {}
    try:
        yt = build("youtube", "v3", http=authorized_http)
        titles = {}
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i+50]
            resp  = yt.videos().list(part="snippet", id=",".join(chunk)).execute()
            for item in resp.get("items", []):
                titles[item["id"]] = item["snippet"]["title"]
        return titles
    except Exception as e:
        print(f"[WARN] タイトル取得失敗: {e}")
        return {}


def fetch_breakdown(service, start, end):
    """デバイス・国・トラフィックソース別集計"""
    print(f"[FETCH] ブレイクダウン: {start} ～ {end}")
    result = {"device": [], "country": [], "traffic_source": []}

    # デバイス
    try:
        h, rows = query(service,
            metrics="views,estimatedMinutesWatched",
            dimensions="deviceType",
            start_date=start, end_date=end, sort="-views",
        )
        for r in rows:
            d = to_dict(h, r)
            result["device"].append({
                "type":          d["deviceType"],
                "views":         safe_int(d.get("views", 0)),
                "watch_minutes": safe_int(d.get("estimatedMinutesWatched", 0)),
            })
    except Exception as e:
        print(f"[WARN] デバイス取得失敗: {e}")

    # 国
    try:
        h, rows = query(service,
            metrics="views,estimatedMinutesWatched",
            dimensions="country",
            start_date=start, end_date=end, sort="-views", max_results=30,
        )
        for r in rows:
            d = to_dict(h, r)
            result["country"].append({
                "code":          d["country"],
                "views":         safe_int(d.get("views", 0)),
                "watch_minutes": safe_int(d.get("estimatedMinutesWatched", 0)),
            })
    except Exception as e:
        print(f"[WARN] 国別取得失敗: {e}")

    # トラフィックソース
    try:
        h, rows = query(service,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType",
            start_date=start, end_date=end, sort="-views",
        )
        for r in rows:
            d = to_dict(h, r)
            result["traffic_source"].append({
                "type":          d["insightTrafficSourceType"],
                "views":         safe_int(d.get("views", 0)),
                "watch_minutes": safe_int(d.get("estimatedMinutesWatched", 0)),
            })
    except Exception as e:
        print(f"[WARN] トラフィックソース取得失敗: {e}")

    return result


# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────
def main():
    from googleapiclient.discovery import build

    creds   = get_credentials()
    service = build("youtubeAnalytics", "v2", credentials=creds)

    existing = load_existing()
    start, end = determine_fetch_range(existing)

    if start > end:
        print(f"[INFO] 差分なし（data_through={end} は最新）。終了。")
        return

    print(f"\n取得範囲: {start} ～ {end}  ({(end - start).days + 1}日分)")

    # --- 日次（差分追記） ---
    new_daily = fetch_daily(service, start, end)
    if existing:
        merged_daily = existing.get("daily", []) + new_daily
        # 重複除去・ソート
        seen = {}
        for row in merged_daily:
            seen[row["date"]] = row
        merged_daily = sorted(seen.values(), key=lambda r: r["date"])
    else:
        merged_daily = new_daily

    # --- 動画別・ブレイクダウンは全期間で再取得（最新状態に上書き） ---
    full_start = date.fromisoformat(merged_daily[0]["date"]) if merged_daily else start
    videos     = fetch_videos(service, full_start, end)
    breakdown  = fetch_breakdown(service, full_start, end)

    # --- チャンネルIDを取得 ---
    try:
        from googleapiclient.discovery import build as yt_build
        yt = yt_build("youtube", "v3", credentials=creds)
        ch = yt.channels().list(part="id", mine=True).execute()
        channel_id = ch["items"][0]["id"] if ch.get("items") else "MINE"
    except Exception:
        channel_id = "MINE"

    # --- 書き出し ---
    data = {
        "meta": {
            "channel_id":   channel_id,
            "fetched_at":   datetime.now(timezone.utc).isoformat(),
            "data_through": str(end),
            "since":        str(merged_daily[0]["date"]) if merged_daily else str(start),
        },
        "daily":     merged_daily,
        "videos":    videos,
        "breakdown": breakdown,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {OUTPUT_FILE} を書き出しました")
    print(f"   日次: {len(merged_daily)}日分  動画: {len(videos)}本")
    print(f"   デバイス: {len(breakdown['device'])}種  国: {len(breakdown['country'])}件  流入: {len(breakdown['traffic_source'])}種")


if __name__ == "__main__":
    main()
