# YouTubeチャンネル分析ダッシュボード構築プロンプト

使い方: ■ を新チャンネルの値に置き換えて、このファイルごと新しいチャットに読み込ませる。
参考実装（完成品）: `~/Downloads/channel-desk-data`（りいポーカーチャンネル用）

---

## 依頼内容

YouTubeチャンネルのアナリティクスダッシュボード自動更新システムを構築してほしい。
参考実装 `~/Downloads/channel-desk-data` の fetch.py / index.html / daily_fetch.yml をベースに、下記チャンネル用に作り直すこと。

## 対象チャンネル（置き換える）

| 項目 | 値 |
|---|---|
| チャンネルID | ■（UCで始まるID） |
| チャンネル名 | ■ |
| GitHubリポジトリ | ■（例: xxx/channel-desk-yyy、公開・GitHub Pages有効） |
| ローカルフォルダ | ■（例: ~/Downloads/channel-desk-yyy） |
| 管理Googleアカウント | ■ |

## 事前準備（人間側で用意）

1. Google Cloud プロジェクト作成、**YouTube Data API v3** と **YouTube Analytics API** を有効化
2. **APIキー**を発行
3. **OAuthクライアント**（アプリの種類: デスクトップ）を作成 → `client_secret.json` をフォルダに保存
4. **OAuth同意画面を「本番環境に公開」**にする（テストモードだと refresh token が7日で失効する。最重要）
5. GitHubリポジトリ作成、Settings → Pages で main ブランチ配信を有効化

## セキュリティルール（必ず守ること）

- 認証情報（パスワード・secret・refresh_token）はチャットに出力しない
- `token.json` / `client_secret.json` は .gitignore に入れローカルのみ
- 各フェーズ末で「できたこと / 詰まったこと / 次にやること」を3行報告 → ユーザー確認 → 次へ

## 構築手順

1. 参考リポジトリから `fetch.py` `index.html` `.github/workflows/daily_fetch.yml` `auth.py` `verify_token.py` `.gitignore` をコピーし、CHANNEL_ID・チャンネル名・SPREADSHEET_ID（投稿計画を使う場合）を新チャンネル用に置換
2. OAuth認証を実施（下記「OAuth認証の正しいやり方」参照）
3. `verify_token.py` で **token が対象チャンネルIDを指すことを必ず検証**
4. `YOUTUBE_API_KEY=<キー> python3 fetch.py` を実行し data.json の全キーが埋まることを確認
5. git push → GitHub Secrets 設定 → Actions 手動実行（Run workflow）で動作確認

## OAuth認証の正しいやり方（前回の最大のハマりポイント）

- `channel==MINE` は「OAuth同意画面の**アカウント選択で選んだチャンネル**」を指す
- Brand Account（ブランドアカウント）のチャンネルの場合、ログイン後に出る
  「アカウントまたはブランドアカウントを選択」画面で**対象チャンネルを選ぶこと**。
  Googleアカウント本体を選ぶと個人チャンネルのデータになる
- **表示名が紛らわしい**ことがある（例: 前回は「ポーカー」という表示が正解だった）。
  どれが正解か分からなければ順に試し、**認証のたびに `channels?part=snippet&mine=true` でチャンネルIDを検証**する
- 認証は「対象チャンネルにログイン済みの**Chromeプロファイル**」で行うこと
- 参考実装の `auth.py` は Claude連携版: ブラウザを開かず認証URLを `auth_url.txt` に書き出し、
  認証後に自動でチャンネルIDを検証、不一致なら自動で再試行URLを発行する。
  `TARGET` 定数を新チャンネルIDに書き換えて使う。依存は `pip install google-auth-oauthlib`（venv推奨）

## YouTube API の制約（コードに反映済み・変更禁止）

1. 動画リストは `search.list` ではなく **`playlistItems`（playlistId = "UU"+チャンネルIDの3文字目以降）** を使う（search.list は取りこぼす）
2. Analytics の `dimensions=day` は pageToken 非対応 → **180日チャンク分割**で全期間取得
3. `impressions` / `impressionClickThroughRate` は `dimensions=video` と併用不可（400エラー）
4. `channel==<ID>` の直指定は 403（Content Owner権限が必要）。必ず `channel==MINE`＋正しい認証で
5. テストモードのOAuthクライアントは refresh token が7日失効 → 本番公開必須

## GitHub Secrets（Settings → Secrets and variables → Actions）

| Secret名 | 値 |
|---|---|
| `YOUTUBE_API_KEY` | APIキー |
| `REFRESH_TOKEN` | token.json の refresh_token |
| `OAUTH_CLIENT_ID` | client_secret.json の client_id |
| `OAUTH_CLIENT_SECRET` | client_secret.json の client_secret |

クリップボードへのコピーは:
`python3 -c "import json;print(json.load(open('token.json'))['refresh_token'],end='')" | pbcopy`

## push が rejected になった場合（Actions bot が先行コミット）

```bash
git fetch origin
git merge --ff-only origin/main   # だめなら merge 後に
git checkout <自分のコミット> -- data.json   # data.json はローカル版を正とする
```

※ data.json を通常マージすると行単位で混ざり壊れるので注意。必ずどちらか一方を採用する。

## 完了条件

- `verify_token.py` → `OK <対象チャンネルID>`
- data.json: analytics_daily が開設日〜前日まで / video_period 4期間 / video_daily・videos が動画数分
- GitHub Actions「Daily Fetch」手動実行が成功し、bot が data.json をコミットする
- GitHub Pages のダッシュボードに実データが表示される
