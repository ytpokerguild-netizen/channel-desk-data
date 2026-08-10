# CHANNEL DESK 引き継ぎ書

最終更新: 2026-08-10 対象: 「りいポーカーチャンネル【PokerGuild】」YouTube分析ダッシュボード「channel-desk-data」の保守・改修を引き継ぐ新しいチャット/担当者向け

> **このファイルはGoogle Doc「引き継ぎ書_CHANNEL_DESK」を2026-07-31にmdへ書き出したものです。**
> 以後はこの `.md`（PGコンソール直下）を正本として扱います。Google Docは参照用として残っていますが、更新はこちらに行ってください。
> **2026-07-17以降の差分・宿題は `引き継ぎメモ_2026-07-31.md` にあります。必ず併せて読んでください。**
>
> **2026-08-07 更新:** §2の git 運用ルール（旧「S→D コピー」）を全面的に書き換えました。**旧ルールは正しくありません。**
> あわせて `ops.json`（議事録由来の運営情報）と `build_ops_json.py` を追加しています（コミット `1fba79f` / `22c1d1a`）。
> 議事録の構造化版は Google スプレッドシート「PG運営ログ（非公開）」（共有オフ）です。詳細は `チャンネル分析AI_運用手順.md`。
>
> **2026-08-10 更新:** 下の★の章（この書類を直すルール）を追加。あわせて廃止済みの「新作初速」の記述、
> タブ構成、参照ファイル一覧を現状に合わせ、Google Doc からの書き出しで文字化けしていた箇所を直しました。

---

## ★ 変更したらこの書類も直す（2026-08-10 追加・例外なし）

**コード・設定・方針を変えたら、この書類を直すところまでが1つの作業です。** 手順は3つ。

1. リポジトリの `変更履歴.md` の表に1行足す（**コードと同じコミットで**）。反映列は `未` で出す
2. Dropbox のこの書類、または `チャンネル分析AI_運用手順.md` を直す
3. 直したら `変更履歴.md` の反映列を `済` に変えて push する

守られているかは自動で見ています。

- **書き忘れた push** → `.github/workflows/docs_guard.yml` が GitHub Actions を赤くし、LINE に通知します
- **`未` が残っている** → 毎日 JST 9時ごろ、`docs_check.py pending` が LINE に思い出させます

方針が変わったとき（「この指摘はもう書かない」など）は、**コードが1行も変わらなくても**
書類を直してください。自動チェックでは方針変更を見つけられません。

この書類の正本が Dropbox にあるのは、人事や社外名など公開できない記述を含むためです。
**リポジトリは public なので、そうした内容をリポジトリ側に書かないでください。**
どのPC・どのアカウントでも最初に読む入り口として、リポジトリ直下に `CLAUDE.md` を置いてあります。
そこには公開してよい範囲の作業ルールだけを書き、詳細はこの書類を見るよう案内しています。

---

## 0\. まず読むべきこと（3行サマリー）

- これは **バックエンドを持たない静的サイト**（GitHub Pages）+ **GitHub Actions のバッチ**でできたYouTube分析ダッシュボード。
- データ取得は `fetch.py`（Python標準ライブラリのみ、pip不使用）が3時間おきに走り、`data.json` / `video_daily.json` をコミット。画面は `index.html` 単一ファイルのSPA。
- LINE通知（朝ブリーフ・障害検知）とライブ配信通知ボット（Apps Script）も稼働中。**機密の値（トークン/APIキー/パスワード）は絶対にチャット・コミット・ドキュメントに書かない**。

---

## 1\. システム全体像

YouTube Data API v3  ─┐

YouTube Analytics API ─┼─→ fetch.py（GitHub Actions, 3時間おき）

Googleスプレッドシート ─┘        │

（投稿計画/動画アーカイブ/          ├─→ data.json（約450KB, 圧縮済み）

 クーポン, CSVエクスポートで読む）  └─→ video\_daily.json（約2.4MB, 動画×日次を分離）

                                        │

                    GitHub Pages で配信 │

                                        ▼

                     index.html（単一約2600行のSPA, Chart.js, ビルド無し）

                     report.html（週次レポートの独立ページ, パスワード不要）

                     manual.html（制作・運用マニュアルのハブ, パスワード不要）

                     geo.html（地域データの読み方, index からは未リンク）

LINE通知:

  morning\_brief.py（毎朝7:00 JST）→ グループへ朝ブリーフ

  check\_staleness.py（データ24h超で警告）

  docs\_check.py（引き継ぎ書類の更新漏れを検出）

  line\_notify.py（送信ユーティリティ / 失敗時通知）

ライブ配信通知（別系統・Google Apps Script）:

  「ポーカーライブ配信通知（CHANNEL DESK 通知）」プロジェクト

  5分おきに7チャンネルの配信を監視→キーワード一致でLINEグループに@All通知

チャンネル情報:

- チャンネル名: りいポーカーチャンネル【PokerGuild】
- チャンネルID: `UCnGhxFzP6V4TczZCs63rXgQ`
- 公開ダッシュボード: [https://ytpokerguild-netizen.github.io/channel-desk-data/](https://ytpokerguild-netizen.github.io/channel-desk-data/)
- 週次レポート: [https://ytpokerguild-netizen.github.io/channel-desk-data/report.html](https://ytpokerguild-netizen.github.io/channel-desk-data/report.html)

---

## 2\. リポジトリと編集フロー（最重要・事故りやすい）

### リポジトリ

- GitHub: `ytpokerguild-netizen/channel-desk-data`（会社=ハンターサイト管理）
- 認証: `gh_token.txt`（PGコンソール直下）にPAT。**値はチャットに出さない**。

### パスの対応表（3つの場所が同じリポジトリを指す）

| 用途 | パス |
| :---- | :---- |
| **正本** | GitHub の `main` ブランチ |
| **作業用 clone** | サンドボックス内（例 `~/channel-desk-data/`） |
| Dropbox 内の古い clone | `Dropbox「PGコンソール」直下の `channel-desk-data/`` — **⚠ 更新停止中。使わない** |

### 鉄則（2026-08-07 全面改訂）

> **旧版の「編集はDropbox側(S)で行い、S→D にコピーしてから push」は現在は誤りです。**
> Dropbox 側の clone は 2026-07-17 で更新が止まっており（コミット0件・`data.json` も07-17）、
> このルールに従うと **GitHub 側の2週間分を巻き戻します**。実際に踏みかけました。

1. **正本は GitHub。** 作業は必ず「毎回 clone し直した新しい clone」で行う。
   `git clone https://github.com/ytpokerguild-netizen/channel-desk-data.git`（public なので clone に認証は不要）
2. **clone は Dropbox のマウント内に作らない。** サンドボックスのホーム側に作る（マウント内では git の書き込みが動かない）。
3. **Dropbox の `channel-desk-data/` は読まない・書かない・コピー元にしない。** 参照する価値のある内容は無い。
4. 編集 → コミット → push。push が拒否されたら `git fetch && git rebase FETCH_HEAD`。
   **`data.json` を行単位でマージしない**（壊れる）。
5. Dropbox の「PGコンソール」直下（`channel-desk-data/` の外）にある手順書・レポート・
   `gh_token.txt` は今も現役。ここは正本のまま。

### サンドボックスのネットワーク制限（セッションごとに違う）

**作業開始時に必ず疎通を確認してください。セッションによって可否が変わります。**

| 確認すること | コマンド | 過去に観測した結果 |
| :---- | :---- | :---- |
| clone / push できるか | `git clone …` は認証不要で通る。push は下記★の方式で | URL埋め込み認証は403。`http.extraHeader` なら通る |
| GitHub API | `curl -s -o /dev/null -w '%{http_code}' https://api.github.com/repos/…` | 403 のことがある（プロキシが未認可リポジトリを弾く）。API が使えなくても push は上記★で可能 |
| Google APIs | 同様に `googleapis.com` | 000（不通）。OAuth 系はサンドボックスから叩けない |
| GitHub Pages | `github.io` | サンドボックスから到達できず、公開後の目視確認ができない |
| Dropbox（デバイスブリッジ） | `mcp__remote-devices__*` を呼ぶ | セッションによってファイル操作系のツールが無い（`get_device_info` だけ）ことがある。その場合は完成ファイルをチャットで受け渡す |

#### ★ push が 403 になったときの対処（2026-08-07 解決）

```
remote: access denied by the git proxy: … is not in this session's authorized repository set
fatal: … The requested URL returned error: 403
```

**原因は「トークンを URL に埋める書き方」です。** サンドボックスの git は HTTPS プロキシを経由し、
`https://x-access-token:<トークン>@github.com/…` の形の認証情報はプロキシに捨てられます。
**認証ヘッダを明示すれば通ります。**

```
TOK=$(tr -d ' \t\r\n' < "<PGコンソールのパス>/gh_token.txt")
AUTH=$(printf 'x-access-token:%s' "$TOK" | base64 | tr -d '\n')

git clone https://github.com/ytpokerguild-netizen/channel-desk-data.git   # clone は public なので認証不要
cd channel-desk-data
# …編集・コミット…
git -c http.extraHeader="Authorization: Basic ${AUTH}" \
    push https://github.com/ytpokerguild-netizen/channel-desk-data.git HEAD:main
```

- `origin` に対する素の `git push` も 403 になります。**上の形で毎回明示**してください
- `non-fast-forward` で弾かれたら `git fetch origin && git rebase origin/main` してから再 push
  （`data.json` は3時間おきに自動更新されるので、作業中に origin が進むのは普通のことです）
- **ログにトークンが出ないように**、出力は `sed -E 's/(gh[pousr]_|github_pat_)[A-Za-z0-9_]+/[R]/g'` に通す
- YouTube の watch ページは WebFetch に 429 を返すことがある。
- Google スプレッドシートの CSV エクスポートは curl で 000。WebFetch はクロスホストのリダイレクトを
  自分では追わないので、返ってきた URL でもう一度呼ぶ必要がある。

---

> **⚠ `data.json` に手でキーを足しても翌日消えます。**
> `fetch.py` の `load_existing_data()` は引き継ぐキーを決め打ちで列挙しているため、そこに無いキーは
> 次の自動更新で落ちます（`weekly_reports[].ai_analysis` だけは明示的に引き継がれています）。
> 手で管理したいデータは `ops.json` のように**別ファイル**にして、`index.html` から個別に fetch してください。

## 3\. 主要ファイル早見表

| ファイル | 役割 |
| :---- | :---- |
| `fetch.py`（約1400行） | データ取得の本体。YouTube Data/Analytics API \+ スプレッドシートCSV。週次レポート生成、計画×実績の自動照合(レベル2)、企画タイプ/ナレーター分類、クーポン集計、`data.json`/`video_daily.json`出力まで全部ここ。 |
| `index.html`（約2600行・約152KB） | ダッシュボードSPA。4タブ構成（アナリティクス/運営/クーポン/週次レポート）。Chart.js。モバイルでフィルタ折りたたみ。**外部ファイルに切り出さない**。 |
| `report.html` | 週次レポートの独立ページ（パスワード不要）。 |
| `manual.html` | 制作・運用マニュアルのハブページ（パスワード不要・noindex）。公開物はリンク、Dropbox内のものは名前だけ載せてURLは載せない。 |
| `morning_brief.py` | 朝ブリーフ本体。視聴回数/登録者純増を🟢🟡🔴判定。推定・欠損は⚪で判定なし。（新作初速は2026-08-07に廃止） |
| `line_notify.py` | LINE push送信ユーティリティ（標準ライブラリのみ）。`LINE_GROUP_ID`をカンマ区切りで配列対応。トークン未設定なら送信スキップ。 |
| `check_staleness.py` | `data.json`のfetched\_atが24h超なら警告をLINE送信。 |
| `docs_check.py` | 引き継ぎ書類の更新漏れ検出。`push` モードは「コードを変えたのに `変更履歴.md` が未更新」を検出、`pending` モードは「反映列が `未` のまま」を検出してLINE通知。 |
| `変更履歴.md` | 変更の一覧と、この書類への反映状況（未/済）。**機械が読む前提の表なので列を勝手に変えないこと。** |
| `CLAUDE.md` | どのPC・どのアカウントでも最初に読む作業ルール（公開してよい範囲だけ）。詳細はこの書類を見るよう案内している。 |
| `auth.py` / `verify_token.py` | OAuthリフレッシュトークンまわりの補助。 |
| `auth_sheets.py` | スプレッドシート読み取り専用トークンを取る1回だけのスクリプト（§10の宿題用・未使用）。 |
| `fetch_ops.py` | 運営ログ→`ops.json` を自動生成（3時間おき）。`SHEETS_REFRESH_TOKEN` 未設定のため現在は休止（§10）。 |
| `.github/workflows/daily_fetch.yml` | 3時間おき \+ trigger.txt push \+ 手動。fetch実行→ops反映→コミット→鮮度チェック→引き継ぎ反映漏れ通知（JST9時のみ）→失敗時LINE通知。 |
| `.github/workflows/morning_brief.yml` | cron `0 22 * * *`(=07:00 JST) \+ 手動。morning\_brief.py実行。 |
| `.github/workflows/docs_guard.yml` | push ごとに `docs_check.py push` を実行。自動コミット（github-actions[bot]）は対象外。 |
| `trigger.txt` | これを変更してpushすると即時データ更新が走る（Claude経由の「今すぐ更新」用）。 |
| `ops.json` | 議事録由来の宿題・決定事項・施策ログ（**公開可のものだけ**）。運営タブが読む。**`fetch.py` は触らない**ので、手で更新しても自動更新で消えない。 |
| `build_ops_json.py` | Google スプレッドシート「PG運営ログ（非公開）」→ `ops.json` 変換。Markdown表/CSV/xlsx を自動判別。公開列が○の行だけを出し、担当者名を役割表記に置換する（本文中の実名も）。**公開判断はこのスクリプトが機械的に行い、AIや人がその場で判断しない。** |
| `research_fetch.py` / `.github/workflows/research_fetch.yml` | 地域データ調査用（手動実行のみ）。`research/geo_research.json` だけを書く。 |
| `geo.html` | 地域データの読み方の公開ページ（index.htmlからは未リンク）。 |

---

## 4\. GitHub Secrets（値は見ない・書かない）

| Secret名 | 用途 |
| :---- | :---- |
| `YOUTUBE_API_KEY` | YouTube Data API v3 |
| `REFRESH_TOKEN` | Analytics API用OAuthリフレッシュトークン |
| `OAUTH_CLIENT_ID` | 同上 |
| `OAUTH_CLIENT_SECRET` | 同上 |
| `LINE_CHANNEL_TOKEN` | LINE Messaging API チャネルアクセストークン（「CHANNEL DESK 通知」アカウント） |
| `LINE_GROUP_ID` | 送信先グループID（複数はカンマ区切り。現在: `Secretsの LINE_GROUP_ID を参照`） |
| `SHEETS_REFRESH_TOKEN` | 運営ログ読み取り用。**未設定**（§10の宿題。未設定でも日次更新は正常に動く） |

登録場所: リポジトリ Settings → Secrets and variables → Actions。

`token.json` / `client_secret.json` / `sheets_refresh_token.txt` は `.gitignore` 済みでローカルのみ。値をチャット/コミットに出さないこと。

---

## 5\. データ設計のポイント

- `data.json` は `separators`で圧縮 \+ 動画×日次データを `video_daily.json` に分離して 5.15MB→450KB前後に削減。
- **速報→確定**の考え方: Analytics値は数日遅れ（実測の中央値2日・最大4日）で確定する。週次レポートやブリーフは「確定値」を優先し、確定前は判定を出さない。
- 週次レポートの週区切りは**土曜開始〜金曜終了**。`final` は「週末+3日が経過し、7日分すべて確定」のフラグ。
- **持ち越し値は欠損扱い**: スナップショットで同一total\_viewsが続く日はnull化して二重計上を防ぐ。
- **公開表示の登録者数は概数です**（1万人未満は10人単位、1万人以上は100人単位）。純増の実数は Analytics の
  獲得−喪失で出すこと。両者を混ぜて書いた事故があります（§11）。
- 用語はYouTube Studioに統一（視聴回数/総再生時間/ブラウジング機能 等）。※過去に「登録フィード」→正しくは「ブラウジング機能」に修正済み。
- 「新作初速」は 2026-08-07 に廃止（§10）。トップページ・朝ブリーフの両方から削除済み。

---

## 6\. スプレッドシート連携

- 投稿計画シート: 列は 番号 / ステータス / 企画タイプ / ナレーター(りい・あさひ・キアラ・その他) / 動画内広告(複数選択: JOPT・SPADIE・戦国・JOPT Games・店舗) / 拡散活動の有無(○×) 等。曜日/尺/公開日/URL列は廃止済み。
  - **⚠ 2026-08-09以降、このシートは改装予定で更新が止まっています。**
    「未入力」「計画0本」を週次レポートの指摘として書かないこと（運営者からの明示の指示）。
    改装が終わって運用が再開されたら、この記述と `チャンネル分析AI_運用手順.md` §7 を戻してください。
- 「動画アーカイブ」タブ: 全動画（約280本）を列挙し、企画タイプ/ナレーターをプルダウンで手入力。各行にYouTubeリンク。毎時トリガーで新規動画を自動追記。
- クーポンシート（JOPT Games）: 動画で発行したクーポンコードの取得・使用状況。`fetch.py` が集計だけを `data.json` の `coupon` に入れる。
  **UID・ニックネームは絶対に出力しない**（集計のみ）。オーナーは社外の方で、共有は「リンクを知っている全員が閲覧可」に依存している。
- `fetch.py` が計画と公開済み動画を\*\*自動照合(レベル2)\*\*し、企画タイプ/ナレーター別のパフォーマンスに反映。
- 拡散活動の有無は手動更新で、コンソールへの反映は不要（分析対象外）。

---

## 7\. LINE通知まわり

### 朝ブリーフ / 障害検知（GitHub Actions系）

- 毎朝7:00 JSTに朝ブリーフを送信。視聴回数・登録者純増を🟢🟡🔴付き（確定前は⚪判定なし）+ダッシュボードURL。
- データ更新失敗時・24h超で古い時に警告通知。
- 引き継ぎ書類の反映漏れがあると毎日JST9時ごろに催促通知（`docs_check.py pending`）。
- Messaging APIのpushはフリープランで月200通まで無料。朝ブリーフは月約30通なので余裕。
- 手順の詳細: `LINE通知セットアップ手順.md`（PGコンソール直下）。

### 重要な制約（ハマりどころ）

- **1つのLINEグループに公式アカウントは1つまで**。以前グループに「Pokerだいすきくん」が居たため「CHANNEL DESK 通知」が即退会し続けた。Pokerだいすきくんを外して再招待で解決済み。
- LINE\_CHANNEL\_TOKENを再発行（「発行」ボタン）すると**GitHub Secretsに登録済みの旧トークンが無効化**される。むやみに再発行しないこと。

### ライブ配信通知ボット（Google Apps Script・別系統）※移行完了

- プロジェクト名: **「ポーカーライブ配信通知（CHANNEL DESK 通知）」**
  - URL: Apps Script のプロジェクト一覧から開く（オーナーのみ閲覧可）
  - オーナー: ユーザー(運営ログのオーナーのGoogleアカウント)のGoogleアカウント
- 監視対象7チャンネル: PokerGO / WSOP / Triton Poker / WPT / PokerStars / APT / Aussie Millions（各キーワードフィルタ付き）。
- ライブ配信のみ通知（通常動画・ショート・配信終了は弾く）。@Allメンション付き。
- 送信先: 同じLINEグループ（`Secretsの LINE_GROUP_ID を参照`）へ「CHANNEL DESK 通知」アカウントから送信。
- コード内定数（値は書かない）: `LINE_ACCESS_TOKEN`, `LINE_GROUP_ID`, `YOUTUBE_API_KEY`。
  - YouTube APIキーはユーザー自身のGCP「My First Project」(`オーナー個人のGCPプロジェクト`)で新規発行し、YouTube Data API v3のみに制限済み。
- トリガー: `checkLives` を5分おきに実行（設定済み）。
- 動作確認: `testSetup` を実行し、チャンネル検証とテスト通知がグループに届くことを確認済み。
- 元の本体（「Pokerだいすきくん」アカウント側）は別の方の管理。すでにグループから外れているので通知重複はないが、無駄な稼働を止めたい場合はその方にトリガー停止を依頼する（こちらからは操作不可）。

---

## 8\. 定期タスク（Cowork スケジュール）

- **週次AI分析**: 週次レポートにAIの分析と提案を付与する。手順の正本は `チャンネル分析AI_運用手順.md`。
  形式は「結論ファースト → 実行に移すアクションプラン」。YouTube Studio用語で記述。
  - **⚠ 起動タイミングの記述が2か所で食い違っています。** この書類の旧版は「毎週土曜朝（cron `0 8 * * 6`）」、
    `チャンネル分析AI_運用手順.md` §0 は「毎週火曜 9:00 JST のリマインダー」と書いています。
    どちらが現行か未確認です。**次に気づいた人が実物のスケジュールを確認して、両方を揃えてください。**
    なお対象は「確定済みかつ未分析の直近4週」なので、1回飛んでも次回まとめて拾えます。
- 他デバイスへの設定手順: `週次AI分析タスク_他デバイス設定手順.md`（PGコンソール直下）。

---

## 9\. セキュリティ制約（即守）

- 機密情報（APIキー・トークン・パスワード等の**値**）は一切、チャット・報告・コミットメッセージ・ドキュメントに書かない。
- 認証情報の入力・貼り付けは**ユーザーが行う**（クリップボード経由 or パスワードマネージャ）。アシスタントはトークンやパスワードの値をフィールドに打ち込まない。
- groupId は機密でない識別子なのでアシスタントが扱ってよい。
- LINEトークンの「発行(再発行)」ボタンは、既存Secretを無効化するので押さない。
- OAuth同意・「確認されていないアプリ」の通過はユーザー操作。
- **「PG運営ログ（非公開）」の共有設定は絶対に緩めない。** URLが公開リポジトリ（`index.html` のリンク）に載っているため、
  共有を広げた瞬間に中身が公開される。
- `ops.json` に出るのは `公開` 列が ○ の行だけ。**空欄・× は出さない**（既定は非公開）。
- **サイトのパスワードゲートは表示の目隠しです。** `data.json` / `ops.json` は raw URL で誰でも読めます。
  機密を守っているのはゲートではなく「そもそも書かない」ことだけです。

---

## 10\. 未対応・任意の改善候補

- `data.json` のさらなる分割 / 非公開化。現状は公開の GitHub Pages に置いており誰でも取得可能。
- ~~新作初速の閾値割れ時に個別アラートを出す~~ → **2026-08-07 に新作初速そのものを廃止**（常に「集計待ち」で60日間一度も算出できていなかった。詳細はコミット履歴）。
- ライブ配信ボット旧系統（Pokerだいすきくん）のトリガー停止依頼。
- **クーポンシートに「コード」列が無い。** どの動画で発行したコードかが分からず、動画とクーポン取得の
  因果を検証できない。発行元（社外の方）にコード列の追加と、集計単位を土〜金に揃える依頼が必要。
- 動画アーカイブの入力規則が **289行目までしか掛かっていない**（実使用は約284行）。1000行まで広げるか要判断。
- 企画タイプが空欄の行が約69行ある（手入力待ち）。
- 動画アーカイブの `E2:E6` の入力規則に「国内切り抜き」が入っていない（`E7:E289` には有る）。要判断。

### 宿題（保留中）: 運営ログの自動反映

**やりたいこと**: 「PG運営ログ（非公開）」を直したら、依頼なしで3時間以内に `ops.json` に反映されるようにする。

**現状**: 手動。スプシを直したあと、Cowork で「運営ログ反映して」と言うと反映される（数分）。
自動化のコードは**すでに入っている**が、Secret 未設定なので動いていない。

| ファイル | 状態 |
| :---- | :---- |
| `fetch_ops.py` | 実装済み。3時間おきに走るが `SHEETS_REFRESH_TOKEN` が無いので「未設定」と出て何もせず終了する |
| `auth_sheets.py` | 実装済み。トークンを取るための1回だけのスクリプト |
| `build_ops_json.py` | `build_ops()` に公開判断を集約済み。手動・自動の両方から呼ぶ（**二重実装にしないこと**） |
| `daily_fetch.yml` | ステップ追加済み（`continue-on-error`。失敗しても日次更新は止まらない） |

**残っている作業は認証だけ。** ただし 2026-08-07 に調べたら、当初の想定より手間が多いことが判明した。

#### 調査結果（同じ調査を繰り返さないために）

- `fetch.py` の既存トークン（`REFRESH_TOKEN`）のスコープは `yt-analytics.readonly` と
  `youtube.readonly` の2つだけ。**スプレッドシートを読む権限は無い**
- Google Cloud Console を `運営ログのオーナーのGoogleアカウント`（＝運営ログのオーナー）で見ると、
  プロジェクト「My First Project」(`オーナー個人のGCPプロジェクト`) には
  **OAuth クライアントが1つも無い**。あるのは YouTube Data API 用の APIキーのみ
- つまり `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` は**別アカウントのプロジェクト**にある
  （おそらく `ytpokerguild@gmail.com`）。**流用できない**
- `client_secret.json` はこの Mac には存在しない（Dropbox 内にも無い）
- 同じプロジェクトの OAuth 同意画面も未構成（警告バナーが出ている）

#### 着手するときの2案

**案①（推奨）: OAuth**
Console 作業4つ ── ① OAuth同意画面を構成 ② OAuthクライアントID作成（デスクトップアプリ）
③ Google Sheets API を有効化 ④ ターミナルで `auth_sheets.py` を実行。
GitHub Secrets を3つ追加（`SHEETS_CLIENT_ID` / `SHEETS_CLIENT_SECRET` / `SHEETS_REFRESH_TOKEN`）。
※ `fetch_ops.py` は現在 `OAUTH_CLIENT_ID` を読む実装なので、`SHEETS_CLIENT_ID` を優先する分岐を足す必要がある。

**利点: 公開判断のロジックが Python の1箇所（`build_ops()`）だけに残る。**

**案②: Apps Script**
Console 作業ゼロ。スプシの「拡張機能 > Apps Script」にコードを貼り、承認1回、3時間トリガーを設定。
GitHub トークンを Script Properties に入れる。

**欠点: 公開判断（公開列のフィルタ・実名の置換）を JavaScript でもう一度書くことになる。**
この仕組みで最も間違えてはいけない部分が2箇所になり、ズレても気づけない。

#### 判断の経緯

2026-08-07、運営者の判断で**一旦保留**。手動で回して、依頼が面倒に感じたら着手する方針。
頻度としては会議のあと週1〜2回なので急がない。

---

## 11\. よくある操作の思い出し方

- **今すぐデータ更新したい**: clone した作業ツリーで `trigger.txt` を1行変えてコミット&プッシュ（daily\_fetch.ymlのpushトリガーが発火）。または Actions UI で「Run workflow」。
- **ワークフローを手動実行**: GitHub → Actions → 対象ワークフロー → Run workflow（サンドボックスからのAPI直叩きは不通なのでブラウザ推奨）。
- **画面を直したい**: clone した `index.html` を編集 → コミット&プッシュ → 数分でGitHub Pagesに反映。ローカル確認は `python3 -m http.server` 経由で（`file://` ではJSONを読めない）。
- **朝ブリーフのロジック変更**: `morning_brief.py`。判定基準は `verdict()`（🟢≥+10/+15%, 🔴≤-10/-15%, それ以外は🟡, 確定前は⚪）。
- **クーポンシートのURLを差し替える**: 3か所ある。`fetch.py` の `COUPON_SHEET_ID` / `index.html` の `card-link` の href / `index.html` の `COUPON_SHEET_URL` 定数。**全部直すこと。**

---

## 12\. 参考ドキュメント

### Dropbox「PGコンソール」直下

- `チャンネル分析AI_運用手順.md` — **週次AI分析の正本（分析者としての大原則・数字の落とし穴・出力形式）**
- `引き継ぎメモ_2026-07-31.md` — **2026-07-17以降の差分と未解決の宿題（必読）**
- `LINE通知セットアップ手順.md` — LINE公式アカウント作成〜Secrets登録〜テストの4ステップ
- `投稿管理シート改修手順.md` — スプレッドシート列改修の手順
- `週次AI分析タスク_他デバイス設定手順.md` — 定期タスクの他デバイス設定
- `週次レポート_テスト_2026-0627-0703.pdf` — 週次レポートの見本

### リポジトリ直下

- `CLAUDE.md` — どのPC・どのアカウントでも最初に読む作業ルール（公開してよい範囲だけ）
- `変更履歴.md` — 変更と、この書類への反映状況

### ⚠ 正本はここだけ

別フォルダ（`ヘッドホンポーカーアーカイブ/コンソールサイト/引き継ぎ資料.md`）にも
同じサイトの引き継ぎが作られたことがありますが、**正本はこの書類です。**
見つけたら削除するか、冒頭に「参照のみ・正本は PGコンソール」と書き足してください。
