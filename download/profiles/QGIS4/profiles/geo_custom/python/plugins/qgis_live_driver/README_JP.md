# QGIS Live Driver (`qgis_live_driver`)

実行中のQGISプロセスを**同じPC上のクライアント(AIツール等)から遠隔操作**するための、
UIを持たない制御専用プラグイン。
`python/plugins/` へのコピーだけで任意のQGISインストールに単独導入できる
(リポジトリ・Node不要)。

このプラグインは `QWebEngineView` を持たないため、
**WebEngineを使わない任意のQGIS環境・任意の他プラグイン**に対しても
`pyeval` 経由の遠隔操作面を提供できる。

- コマンド: `pyeval`(任意Python実行) / `screenshot` / `status` /
  `open_plugin` / `reload_plugin` / `bridge_call` + `plugin_id` 転送(hub)
- 接続面(4系統・全て同じdispatchへ): ファイルJSONL /
  HTTP REST `/api/*` / MCP Streamable HTTP `/mcp` / MCP stdio (`mcp_stdio.py`)

**詳細ドキュメント(コマンド一覧・制御範囲・RESTエンドポイント等):**
https://yamamoto-ryuzo.github.io/qgis_live_harness/driver.html

## 有効化

```powershell
# このリポジトリから(全プラグイン一括deploy)
powershell -ExecutionPolicy Bypass -File scripts/deploy-plugin.ps1 -Install

# または手動: このフォルダを python/plugins/qgis_live_driver/ へコピーし、
# QGISのプラグイン管理で有効化
```

### クイックスタート(初回)

1. プラグインを導入・有効化(上記)。
2. `プラグイン > QGIS Live Driver > Remote Control (localhost only)` をONにし
   警告を承認すると、接続に必要な全情報(MCP URL・トークン・
   レジストリパス・live dir)を載せた **Connection Info** ダイアログが
   自動で開く。以降は `プラグイン > QGIS Live Driver > Connection Info`
   でいつでも開き直せる。
3. 表示された設定をMCPクライアントへ貼り付ける:
   - **stdio**(推奨): 同梱 `mcp_stdio.py` を起動し、
     稼働中QGISセッションを自動検出するためポート/トークン設定は不要。
   - **Streamable HTTP**: `http://127.0.0.1:<port>/mcp` に
     表示の `Authorization: Bearer <token>` を付与。
   - プレーンRESTも `curl` 例として表示される。
4. (開発のみ) プラグインを `qgis_live_harness` リポジトリへ紐付けるには
   (Deploy Mode / ホットリロードに必要)、Connection Infoダイアログの
   **Harnessリポジトリを選択…** または `プラグイン > QGIS Live Driver >
   Deploy Mode` の **参照…** でリポジトリフォルダを指定する。
   パスはQSettingsへ保存され、marker・junction自動推定より優先される。

有効化は2経路(既定ではOFF・無害):

- **メニュートグル**: `プラグイン > QGIS Live Driver > リモート制御 (localhostのみ)`。
  初回ON時に警告ダイアログを表示し、QSettingsに保存されるため次回起動から自動有効。

なお本プラグインは **GeoSuite共有ツールバー** を作成し、先頭に
deployモードバッジ(開発モード/利用モードの常時表示)を載せる。
クリックするとDeploy Modeダイアログを開く。Harness管理下の
他プラグイン(geo_search等)のツールバー項目もこのツールバーに集約される。
- **環境変数**: `WEBENGINE_LIVE_DIR` 設定時は起動時に即座に有効(開発用途。
  `scripts/verify-in-qgis.ps1` が付与して起動する)。

## AI アシスタントパネル

`プラグイン > QGIS Live Driver > AI アシスタント` で、
**LLM APIを接続してQGISを対話操作するチャットドック**を開ける
(`ai_panel.py` + `ai_client.py`)。

- **プロバイダ**(コンボで選択。設定はプロバイダごとに別保存):
  - **OpenAI互換**: Chat Completions
    (`POST {base}/chat/completions` + function calling)。
    エンドポイントを変えれば Ollama (`http://localhost:11434/v1`)・
    LM Studio・OpenRouter・xAI Grok (`https://api.x.ai/v1`)・
    Mistral・Groq・DeepSeek等のローカル/互換サーバも使える。
    AWS Bedrock・Vertex AI等の独自API系も LiteLLM 等の
    OpenAI互換プロキシ経由なら接続できる
  - **Anthropic (Claude)**: Anthropic Messages API
    (`POST {base}/v1/messages`、tools = `input_schema`、
    認証は `x-api-key` + `anthropic-version`)。
    APIキーは Anthropic Console で発行。既定モデル `claude-sonnet-4-5`
  - **Gemini**: Google Gemini API
    (`POST {base}/models/{model}:generateContent` +
    functionDeclarations、認証は `x-goog-api-key`)。
    APIキーは AI Studio で発行。既定モデル `gemini-2.5-flash`
  - **Azure OpenAI**: Azure OpenAI Service の Chat Completions
    (`{resource}/openai/deployments/<deployment>/chat/completions
    ?api-version=…`、認証は `api-key` ヘッダ)。
    エンドポイントにはデプロイ先URLを、モデル欄にはデプロイ名を
    入れる。`api-version` は省略時 `2024-10-21`
  - **GitHub Copilot**: OpenAI互換のCopilot API
    (`POST {api}/chat/completions`)。**GitHub Copilotの契約が必要**。
    APIキー欄にはGitHubトークン(`gho_`/`ghu_`/`ghp_`…)を入れる。
    内部で `api.github.com/copilot_internal/v2/token` に交換し、
    応答の `endpoints.api` (individual/business/enterprise)へ送る。
    `v2/token` が応答しない環境では `copilot_internal/user` で
    API先だけを解決しGitHubトークンをそのままBearerに使う
    (`@github/copilot` CLIと同じ動作)に自動フォールバック。
    **「GitHubでサインイン」ボタン**でOAuthデバイスフローによる
    トークン取得もできる(既定のclient_idはVS Codeの公開OAuth App。
    `QGIS_LIVE_GITHUB_CLIENT_ID` で差し替え可)。
    エンドポイントを既定から変えた場合はトークン交換せず
    GitHubトークンをそのままBearerに使うため、
    copilot-api等の互換プロキシにも繋がる。
    **対応プラン**: Pro/Free/Business/Enterprise/EMU
    (Enterprise Managed Users。EMUはエンタープライズから
    Business/Enterpriseシートを付与された場合に使える)。
    Business/Enterprise/EMUでは `endpoints.api` が
    `api.business.`/`api.enterprise.githubcopilot.com` を返すため
    同じ経路で自動解決される。EMUではPAT発行が企業ポリシーで
    制限されうるため「GitHubでサインイン」(デバイスフロー)推奨。
    組織のCopilotモデルポリシーで無効化されたモデルは
    一覧・使用とも不可。IdP条件付きアクセス等の企業側制限は
    アプリ側では回避不可
- **モデル選択**: モデル欄は編集可コンボ。隣の「取得」ボタンで
  `GET {base}/models` から利用可能モデル一覧を取り込める
  (GeminiではgenerateContent非対応モデルを除外)。
  一覧は種別(テキスト/画像入力可・画像生成・埋め込み等)で
  グループ化され、各項目に価格(入力/出力, $/1Mトークン)を併記。
  価格はOpenRouter等が返す `pricing`/`modality`/`context_length`
  を優先し、無ければ主要モデルの既知価格表(参考値)を使う。
  既定エンドポイント利用時は「取得」前から推奨モデル一覧を表示。
  モデル欄の下に選択中モデルの種別・価格・コンテキスト長も出る
- **エージェント/スキル(指示書)**: Markdownファイル2系統で振る舞いを拡張:
  - **`~/.qgis-live/agents/*.md`** — 常時注入の指示書(役割・方針)。
    パネルの「エージェント」コンボで1件選択するとsystem promptに
    本文が注入される。「編集」ボタンで作成・編集・削除できる
    (複数定義して切替可能。チャットごとに選択も記憶される)
  - **`~/.qgis-live/skills/*.md`** — オンデマンドの手順書。
    プロンプトにはid+説明(+`use_when`)の一覧のみ載り、
    モデルが該当タスク時に `qgis_pyeval` の `open()` で本文を
    読む(常時注入しないのでトークン節約)。
    **設定方法はAPI設定の「スキル」行 — 全件がコンボに列挙され
    (選択不要・全件が自動で一覧に載る)、「編集」ダイアログで
    作成・編集・削除する**
  - 両者とも `<plugin>/<kind>/` にプラグイン同梱デフォルトを置け、
    ユーザ側の同名ファイルが優先される。書式: 先頭 `# `行=タイトル、
    次の非空行=説明文、その直後の `use_when: <使いどき>` 行
    (省略可。別名 when/when_to_use/用途/使いどき)=起動条件として
    プロンプト一覧に `use when:` で載る(同梱デフォルトは任意。
    現在の同梱品なし)
  - **AI自身も指示書を編集・選択できる**: `ai_list_instructions` /
    `ai_read_instruction` / `ai_save_instruction` /
    `ai_delete_instruction` に加え `ai_select_agent`(選択中
    エージェントの切替)をモデルに渡す。エージェント一覧は
    スキルと同様にid+説明がプロンプトに載るため、モデルが
    タスクに合うエージェントを自律選択できる。保存は常に
    ユーザ側へ書き、同梱品は同名保存で実質上書き(削除は
    ユーザ側のみ)。変更後はパネルのコンボも自動で再構築される
  - **「編集」ダイアログは非モーダル**: 開いている間もチャット
    入力欄は通常通り使える。ダイアログ下部のプロンプト欄に修正
    指示を書いて「AIに修正を依頼」すると、編集欄の本文と共に
    チャットのAIへ送られ、AIが `ai_save_instruction` で保存した
    結果が編集欄へ反映される(未保存の手編集がある間は上書き
    しない)。新規作成中に同名ファイルが保存された場合は
    そのファイルが選択状態になる
  - **チャット入力からも直接編集できる**: `/` で始まる入力はAPIへ
    送らずローカルコマンドとして実行される。`/agent`(一覧+現在値)、
    `/agent <名>`(切替)、`/agent <名> <本文>`(保存して選択)、
    `/skill`(一覧)、`/skill <名>`(本文表示)、`/skill <名> <本文>`
    (保存)。本文は2行目以降に改行して書ける。`/help` で一覧表示
  - **外部AIからも操作できる**: MCP/REST側の `qgis_instruction`
    ツール(op=list|read|save|delete)で、オーケストレーターが
    指示書を発見・編集可能(`QGIS_LIVE_TOOLS` の許可対象)
- **表示**: AI応答はMarkdownレンダリング(見出し/リスト/表/
  コードブロック)。「新しいチャット」で現在の会話を履歴コンボへ
  保存して新規開始。履歴コンボから過去チャットを開くと
  表示とコンテキストが復元され会話を継続できる。
  履歴は `~/.qgis-live/chats.json` に永続化され(最新50件)
  QGIS再起動後も残る。「↓」で表示中チャットをMarkdown保存、
  「✕」で表示中の履歴チャットを削除できる
- **送信/中断/再送**: Enter(または「送信」)で送信、
  Shift+Enterで改行。入力が空の間は「送信」は無効で、
  実行中はボタンが赤色の「■ 中断」に変わって
  往復の境界でループを止められる(進行中のAPI応答やツール実行
  そのものは完了を待つ)。「再送」は最後の質問+応答を取り消して
  同じ質問を送り直す。長い会話は古いターンから自動で切り詰める
  (MAX_HISTORY_CHARS)ためコンテキスト過大でAPIエラーにならない。
  右下にコンテキスト/コスト表示
  (`ctx 9k/128k (6%) · Σ13k · $0.0023`)。
  ctx は直近API応答のprompt_tokens実測値(未取得時は~付きで
  文字数÷3推定)、Σ はチャット毎の累計トークン、$ は
  価格情報があるモデルでの推定コスト(定額制のCopilot等では
  Σのみ表示)。usageとともにチャット履歴へ保存される
- **画像添付**: 入力欄へのクリップボード貼付(Ctrl+V)・
  画像ファイルのドラッグ&ドロップ・「📎」ボタンで画像を添付
  できる。サムネイルチップとして入力欄の上に並び、送信時に
  ユーザメッセージへ同梱される(履歴にも残り、後続ターンでも
  モデルが参照できる)。画像はPNGへ正規化し長辺2048pxに縮小して
  一時ファイルへ保存する。**画像非対応と推定されるモデル
  (一覧の「画像入力可」グループ外)選択中は添付できず**、
  📎ボタンも無効化される(手入力モデルは名前ヒントで推定)
- **確認モード**: 「ツール実行の前に確認する」をONにすると
  各ツール呼び出しで実行可否を都度確認する(任意コード実行の
  pyevalを自動で回したくない場合に)
- **ツール**: `mcp_http.TOOLS` と同じセット
  (`qgis_pyeval` / `qgis_screenshot` / `qgis_status` /
  `qgis_eval` / `qgis_devreload` / `qgis_open_plugin` /
  `qgis_reload_plugin` / `qgis_bridge_call` /
  `qgis_instruction`)に加え、指示書を
  読み書きするパネルローカルツール `ai_*`、および外部MCPサーバの
  ツール `mcp_*` をモデルに渡し、戻ってきたtool_callを
  `driver.submit()`(qgis_*)またはローカル実行(ai_*/mcp_*)で
  処理するエージェントループ(上限25往復)
- **外部MCPサーバ接続**: API設定の「MCP」行→「設定」で
  `~/.qgis-live/mcp_servers.json` を編集(Claude Desktop互換形式):
  ```json
  {"mcpServers": {
    "fs":  {"command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/work"]},
    "api": {"url": "http://localhost:3000/mcp",
            "headers": {"Authorization": "Bearer ..."}},
    "box": {"url": "https://mcp.box.com",
            "oauth": {"authorize_url":
                        "https://account.box.com/api/oauth2/authorize",
                      "token_url": "https://api.box.com/oauth2/token",
                      "client_id": "...", "client_secret": "...",
                      "redirect_uri": "http://127.0.0.1:8020/callback"}},
    "ccg": {"url": "https://example.com/mcp",
            "oauth": {"token_url": "https://example.com/oauth/token",
                      "client_id": "...", "client_secret": "...",
                      "extra": {"box_subject_type": "enterprise",
                                "box_subject_id": "..."}}}
  }}
  ```
  `command`=stdioで子プロセス起動(Windowsではコンソール窓を出さない)、
  `url`=Streamable HTTP。
  **秘密値は資格情報ストアへ**: `oauth.client_secret` に平文を
  書いて保存するとOSの資格情報ストア(credential_store。
  APIキーと同じ保存先)へ自動で移され、設定ファイルには
  `"$store:mcp:<サーバ>:client_secret"` 参照だけが残る。
  ストア保存に失敗した場合はエラーになり平文では保存しない。
  `headers`/`env`/`oauth.client_id` の値も `"$store:<キー>"` と
  書けば接続時にストアから解決される(手動で参照を書く場合は
  資格情報ストアへ事前登録が必要)。平文のclient_secretが
  残っている既存設定は、設定ダイアログで再保存すれば移行される。
  認証は `headers` で固定値を渡すか、
  `oauth` で2種類のOAuthを使う:
  `authorize_url` あり=**authorization_code+PKCE**(初回送信時に
  ブラウザが開き同意画面、トークンは `~/.qgis-live/mcp_tokens.json`
  に保存して以降は refresh_token で自動更新。mcp.box.com等の
  ユーザー同意型サーバ用。redirect_uriはアプリ側に登録が必要)、
  `authorize_url` 無し=**client_credentials**(client_id+secret、
  `extra`でプロバイダ固有のformパラメータ)。
  401で1回リトライ。接続に失敗した場合はエラーと一緒に
  「①Redirect URIの登録 ②authorization_code有効 ③id/secret一致」
  の確認ガイドを表示する。
  mcp.box.com を使う場合はさらに Box側で Business プラン以上、
  Admin Console での MCP 有効化、Custom App で標準OAuth2
  (CCGのみのServer Appは不可)が必要。
  取得トークンは `~/.qgis-live/mcp_tokens.json` に平文保存される
  (アクセス/refreshトークンを含むため取り扱い注意)。
  初回送信時に接続・tools/listを行い、
  各ツールは `mcp_<サーバ>__<ツール>` としてモデルに公開される。
  設定を保存すると次の送信で再接続される。接続失敗したサーバは
  チャット欄にエラー表示され他サーバは継続する。
  注意: QGIS自身のドライバMCPエンドポイントを指定すると、
  tools/callがGUIスレッドdispatchを経由する自己参照になるため
  実用上は他サーバを指すこと
- **リモート制御トグルOFFでも動く**: パネル専用の内部LiveDriver
  (レジストリ・HTTP公開面なし)を使うため、外部公開を有効化せずに
  AI操作だけを試せる
- **画像送信**: `qgis_screenshot` の結果は `image_url` contentで、
  添付画像(貼付/📎)はユーザメッセージへ同梱されて画像として
  モデルへ送られる。画像非対応と推定されるモデルでは
  スクショ結果はテキスト(パス)のみ返され、添付自体もできない
- 設定(エンドポイント/モデル)はQSettingsに保存。
  **APIキーはOSの資格情報ストアに保存**(`credential_store.py`):
  WindowsはDPAPI(ブラウザのパスワード保存と同じユーザ紐付け暗号化)、
  macOSはキーチェーン、LinuxはSecret Service(secret-tool)。
  いずれも無い環境のみ `~/.qgis-live/ai-secrets.json`(600権限・平文)に
  フォールバック。パネルの「キー保存先」欄で現バックエンドを確認できる。
  **ストア書込み自体に失敗した場合はエラー表示し、平文では保存しない**

## セキュリティモデル(localhost限定)

`pyeval` は **任意コード実行** のため、全チャネルを以下で保護する:

- **127.0.0.1 バインドのみ** — 外部ネットワークからは到達不能
- **セッショントークン必須** — 起動ごとに自動生成。HTTPは
  `Authorization: Bearer` 等、commands.jsonl は各行の `token` フィールドで照合。
  トークンは `~/.qgis-live/<pid>-qgis_live_driver.json` (レジストリ)と
  `live_dir/token` にのみ書き出され、ユーザ限定ACLを適用
- **Host/Origin 検証** — HostまたはOriginがloopback以外を指すHTTP要求は拒否
  (DNSリバインド・ブラウザ経由のドライブバイ対策)
- `QGIS_LIVE_TOOLS` で公開コマンド種別を絞れる(例 `status,screenshot`)

**脅威モデルの境界**: トークンはユーザ専用ファイルに置くため、
同一ユーザ権限で任意コードを実行できるプロセスまでは防げない
(これはあらゆるlocalhostサービスの限界)。信頼境界はローカルユーザアカウント。

ローカルのMCPクライアント(`mcp_stdio.py` 等)はレジストリからトークンを
自動で読むため、利用側の手順は変わらない。

# 免責事項

本システムは個人のPCで作成・テストされたものです。  
ご利用によるいかなる損害も責任を負いません。

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>