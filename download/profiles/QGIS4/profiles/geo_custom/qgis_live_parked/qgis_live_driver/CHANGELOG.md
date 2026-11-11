# Changelog — qgis_live_driver

このプラグインの変更履歴。Keep a Changelog 準拠。
バージョンは `metadata.txt` の `version` と同期させる。

## [0.15.1] - Unreleased

### Added

- GeoSuiteツールバーに AI アシスタント(チャット)起動ボタンを追加。
  モードバッジの右隣に常駐し、クリックで既存の AI アシスタント
  ドックを開く/前面化する。ツールバー上に AI 関連のエントリ点が
  無かったための追加で、メニューからの起動と同じパネルを使う。
  アイコンは同梱 `icon_ai.png`("AI"グリフ)を使用

### Changed

- deployモード判定を「配置実態(junction/dir)優先」に変更。
  宣言markerは未配置時の補完と乖離検出(`deploy_state` の
  `declared`/`diverged`)に使い、古い宣言で実態を上書きしない。
  Deploy Modeダイアログは宣言と実態が乖離している場合に
  `(declared: ...)` を併記する

### Fixed

- Deploy Modeダイアログのモード切替が、QGIS内のPATHに `powershell` が
  無い環境(OSGeo4W系の最小PATH)で `[WinError 2]` 失敗する問題を修正。
  `switch_mode()` が `%SystemRoot%\System32\WindowsPowerShell\v1.0\
  powershell.exe` のフルパスを優先使用するようになった
- モードバッジ: 利用モードはテキスト表示から歯車アイコン
  (`/mActionOptions.svg`)のみの非侵襲表示に変更(ツールチップには
  モード名を表示)

### Security

- plugins.qgis.org セキュリティスキャン対応: `urlopen` 全5箇所に
  `_require_http_scheme` による http/https スキーム検証を追加
  (file:等のスキームを拒否)
- ログパスのフォールバックを `/tmp` ハードコードから
  `tempfile.gettempdir()` に変更
- `pyeval` の `eval` は任意Python実行が主目的のため
  `# nosec B307` で明示抑制
- try/except/pass|continue 65箇所に `# nosec B110/B112` を付与
  (設計上の許容を明示。サイトスキャンの指摘対応)
- subprocessの部分パス起動を解消: `icacls`/`security`/`secret-tool`
  を `shutil.which()`(無ければ `%SystemRoot%\System32` フォールバック)
  でフルパス解決するよう変更。意図通りの呼出し(subprocessの
  リスト引数・ユーザ設定MCPコマンド・検証済みモード引数、および
  URL/プレースホルダ文字列のB105誤検知)には `# nosec` を付与し、
  `.bandit` 非適用のスキャンでも指摘が出ないようにした

### Maintenance

- flake8指摘を整理: bare `except:` を `except Exception:` に修正、
  `def f(): ...` 単一行定義を展開、未使用変数を整理。
  残る長行E501は同梱 `.flake8` 設定で明示抑制
- LOW指摘(try/except/pass、subprocess系監査ヒント、
  ハードコード文字列の誤検知等)はレビュー済みとして同梱
  `.bandit` 設定で抑制

## [0.15.0] - 2026-10-19

### Added

- **GeoSuite共有ツールバー**(`geo_toolbar.py`):
  管理対象プラグインのツールバー項目を1本の
  `QToolBar`(objectName="GeoSuite")に集約する。
  find-or-create方式のためどのプラグインが先に有効化されても
  同じツールバーに載る(ドライバ非依存で各プラグインが
  同形の小ヘルパを持つ)。ドライバ有効中は常時表示を強制
  (toggleViewAction無効化+定期再表示)。geo_search/geo_webview/geo_report/
  geo_import/QGIS-legendView-main がプラグインツールバーから
  GeoSuiteへ移行(geo_excelはツールバー項目を持たない)。
- **モードバッジ**(ツールバー先頭の常時表示):
  現在のdeployモードを「開発モード/利用モード」等のテキスト
  ボタンとして常時表示(dev=「開発モード」の赤背景白文字で注意喚起、
  use=歯車アイコンのみで非侵襲表示)。
  5秒毎に `deploy_state()` で自動更新し、クリックすると
  Deploy Modeダイアログを開く。i18n 9言語対応

## [0.14.0] - 2026-10-19

### Added

- **Deploy Mode ダイアログ**(`mode_switch.py`):
  `プラグイン > QGIS Live Driver > Deploy Mode` から
  deployモードを明示切替できる。開発モード(junction=repo優先)と
  利用モード(copy=スナップショット)の切替は harness側の
  `deploy-plugin.ps1` を起動して行い、モード宣言marker
  `profiles/<profile>/qgis_live_mode.json` の `repo` キーから
  copy配置中でもスクリプトを解決する。ダイアログは宣言モードと
  各プラグインの実配置形態(junction/dir/未配置)を一覧表示し、
  「切替後にプラグインをリロード」(既定ON)で非ドライバの
  プラグインをその場で反映する。bridgeメソッド `deployMode()`
  で状態を読取専用で公開(切替自体はUI操作のみ)。
  dev化時に既存の実体プラグインは `qgis_live_parked/<id>` へ退避され、
  use化時に復元される(退避無しなら未配置のまま)。利用版の
  新規配置・更新は「現在のrepoを利用版としてインストール」
  ボタン(`deploy-plugin.ps1 -Install`=リリース操作)から行う。
  退避中のプラグインは一覧に `(+parked)` と表示される。
  UI文字列は9言語カタログへ追加済み

## [0.13.0] - 2026-10-19

### Added

- **レイヤ整理サービス `layer_org`**(`layer_org.py`):
  プラグイン横断で追加レイヤの表示を標準化する共有サービス。
  `plugins['qgis_live_driver'].layer_org.place_all([(layer, ctx)])`
  で、プロファイルJSONのルールに従いレイヤをグループ配置・
  リネーム・.qmlスタイル適用する。プロファイルは
  `<plugin>/layer_org/*.json`(同梱デフォルト) +
  `~/.qgis-live/layer_org/*.json`(ユーザ/業界別、同名優先)の
  2階層で、アクティブは QSettings
  `qgis_live_driver/layer_org/profile`。match条件(format/ext/
  provider/layer_type/geom/plugin/name_re/dataset_re/url_re/tags)
  を全キーANDで先勝ち評価し、`root`/`fallback`/`rename`/`style`/
  `top`/`collapsed` を適用する。同梱 `default.json` は
  サービス系・ベクタ(geometry別)・ラスタの汎用配置。
  bridgeメソッド `layerOrgProfiles`/`layerOrgRules`/
  `setLayerOrgProfile`/`organizeLayers`(dry対応)/`placeLayer` を
  追加し `bridge_call`/`describe_plugins` から到達可能。
  geo_import は読込で追加したレイヤを自動でこのサービスに渡す
  (ドライバ未ロード・プロファイル無効時は従来のflat追加に
  フォールバック)

### Changed

- 翻訳方式を `i18n/<lang>.json` に移行(Harness横断の方針変更)。
  `.ts`/`.qm` を廃止し `{"context": {"英語ソース": "翻訳"}}` の
  JSONカタログを新設。`i18n_json.py`(全プラグイン共通ローダ)の
  `install_translator()` で起動時ロードに統一。
  `QT_TRANSLATE_NOOP` 含む全翻訳経路は無改変で動作。

## [0.12.0] - 2026-10-18

### Added

- 採用言語セット(AGENTS.md)に合わせ de/es/fr/hi/it/pt/ru/zh の
  翻訳カタログ(`i18n/qgis_live_driver_<lang>.ts`/`.qm`)を追加
  (各164メッセージ)。ja と合わせ全9言語を同梱。

## [0.11.0] - 2026-10-18

### Added

- **国際化(i18n)対応**: UI文字列を英語ソースに統一し、Qt翻訳
  (`.ts`/`.qm`)経路を整備。`i18n/qgis_live_driver_ja.ts`/`.qm` を新設
  (164メッセージ全訳)。`__init__.py` で `QTranslator` を起動時に
  ロードし、UIロケールに応じて日本語表示に切り替わる。
  AIパネル・MCP設定ダイアログ・メニュー項目も翻訳対象化
  (`QCoreApplication.translate` / `QT_TRANSLATE_NOOP` 使用)。
- `README.md` を英語版に刷新し、日本語ドキュメントを `README_JP.md` に分離。

### Changed

- **ホットリロードの対象を `<repo>/qgis-plugin/` 内のプラグインに限定**
  (`hot_reload.py`): これまでは plugin.config.json のidを優先し、
  発見できない場合はロード中の全プラグイン(サードパーティ含む)を
  候補にしていた。deploy先の各プラグインのrealpathが
  `<repo>/qgis-plugin/` 配下に解決されるもの(junction配置)だけを
  候補とし、該当がない環境(-Copy配置や通常利用)では候補なし
  (「すべて再読込」も非表示)とする

## [0.10.0] - 2026-10-18

### Added

- **AIパネル表示状態の永続化**(`__init__.py`):
  AIパネルが開いている状態でホットリロード(またはQGIS再起動)
  しても自動で開き直す。表示状態は `qgis_live_driver/ai_panel_open`
  に保存し、ドックを閉じた状態なら閉じたまま復元する。
  ai_panel.py/ai_client.py のUI開発をホットリロードで回す場合に
  パネルを開き直す手間がなくなる
- **AIアシスタントの画像添付**(`ai_panel.py`+`ai_client.py`):
  入力欄へのクリップボード貼付(Ctrl+V)・画像ファイルの
  ドラッグ&ドロップ・「📎」ボタン(ファイルダイアログ)で画像を
  添付できる。添付画像はPNGへ正規化(長辺2048pxに縮小)して
  tempへ保存し、サムネイルチップとして入力欄の上に表示・個別
  削除できる。送信時はユーザメッセージへ同梱され(OpenAIは
  image_url content配列、GeminiはinlineData)、チャット表示と
  履歴にも残るため後続ターンでモデルが参照できる。
  画像のみ(テキスト無し)の送信・「再送」での画像復帰にも対応

### Removed

- **「スクリーンショットを画像として送信」チェックボックスを廃止**:
  画像送信は選択モデルの画像対応推定で自動判定するようになった。
  「画像入力可」グループ外(取得一覧の非vision・手入力の非vision名)
  モデル選択中は画像の添付自体ができず(📎ボタンも無効化)、
  スクショ結果はテキスト(パス)のみモデルへ返される

## [0.9.0] - 2026-10-18

### Added

- **メニュー「ホットリロード」サブメニュー**(`hot_reload.py` 新設):
  「プラグイン > QGIS Live Driver > ホットリロード」に開発対象
  プラグインの一覧を出し、選んだプラグインを sys.modules 掃除
  +reloadPlugin(+open_dialog再表示)で手動リロードする。
  QGIS再起動・deploy不要。候補はjunction配置時に自プラグインの
  realpathからrepoを辿った `plugin.config.json` のid順、
  発見できない環境ではロード中の全プラグイン。「すべて再読込」で
  一括リロードも可(制御面の qgis_live_driver は最後。
  自プラグイン自身のリロードも可能)。一覧はメニューを開くたびに
  再構築するため plugin.config.json やロード状態の変化に追従する
- `live_driver.reload_plugin_now()`: reload_pluginコマンドの中身を
  モジュール関数化しホットリロードと共通化

## [0.8.0] - 2026-10-18

### Added

- **指示書ヘッダーの `use_when:` フィールド**(`ai_client.py`):
  agents/skills の .md で、タイトル・説明文の直後に
  `use_when: <使いどき>`(別名 when/when_to_use/用途/使いどき、
  省略可)を書けるようにした。値はプロンプトの Agents/Skills
  一覧と `ai_list_instructions` の出力に `use when:` として載り、
  モデルが「いつ使う指示書か」を見て選択できる。
  `ai_save_instruction` のフォーマット説明・パネルのコンボ
  ツールチップ・編集ダイアログのヒント文も同書式に合わせた

## [0.7.4] - 2026-10-18

### Removed

- **同梱スキル `skills/qgis-basics.md` を削除**: pyeval基本レシピの
  内容がモデルの誤動作(動作エラー)の原因になっていたため同梱を
  止めた。`<plugin>/skills/` の同梱デフォルト機構自体は残るため、
  必要ならユーザ側 `~/.qgis-live/skills/` または将来の同梱品で
  手順書を提供できる

## [0.7.3] - 2026-10-18

### Changed

- **Enterで送信、Shift+Enterで改行に変更**(`ai_panel.py`):
  一般的なAIチャットUIに合わせ送信キーをCtrl+EnterからEnterへ
  変更(Ctrl+Enterでも送信可)。IME変換中の確定Enterでは
  送信しない。指示書編集ダイアログの「AIに修正を依頼」欄も同様
- **送信ボタンで状態を表示**(`ai_panel.py`): 待機中は「送信」
  (入力が空の間は無効)、実行中は赤色の「■ 中断」に変わり、
  考え中か入力受付中かがボタンで分かるようにした。
  送信確定時点で即座に中断表示+即再描画するため、Enter押下の
  応答が速い。中断クリック時は「中断中…」(無効)に変わり
  要求が受理されたことが分かる
- **指示書編集中のチャット入力欄を解放**(`ai_panel.py`):
  「編集」ダイアログを開いてもチャット入力欄を指示書本文の
  編集欄に乗っ取らなくなった。開いている間も通常通りAIへ
  メッセージを送れる(送信ボタンは「送信」のまま)

### Added

- **指示書編集ダイアログの「AIに修正を依頼」欄**(`ai_panel.py`):
  ダイアログ下部のプロンプト欄に修正指示を書いて送ると、
  編集欄の本文と共にチャットのAIへ送られ、AIが
  `ai_save_instruction` で保存した結果が編集欄へ反映される
  (未保存の手編集がある間は上書きしない。新規作成中に同名
  ファイルが現れたら選択状態にする)

### Fixed

- **起動の度にモデルが旧選択へ戻る問題**(`ai_panel.py`):
  保存済みモデルが推奨一覧に無い場合、コンボの表示は保存値でも
  currentIndexが先頭の有効項目(例: gemini-2.5-flash)を指したままに
  なり、`_current_model` が `currentData()` を無条件に返すため
  保存時・送信時に旧モデルへ書き戻されていた。
  itemDataは表示テキストがその項目のIDと一致する時だけ信用する
  ように修正
- **Gemini既定モデルの陳腐化**(`ai_client.py`):
  `gemini-2.5-flash` がAPI側で廃止(404)となったため、既定を
  `gemini-3.8-flash` に更新。推奨モデル一覧も3.x系へ更新

## [0.7.2] - 2026-10-18

### Added

- **指示書編集ダイアログのスクロール同期**(`ai_panel.py`):
  編集(Markdown)ペインと表示ペインのスクロール位置を比率で
  相互に追従させる。setMarkdown による表示側の先頭巻き戻しで
  編集側が巻き戻らないよう、レンダリング中の逆方向同期を抑止し
  描画後に編集側の位置へ合わせ直す
- **チャット入力からの指示書編集**(`ai_panel.py`): `/` で始まる
  入力をAPIへ送らずローカルコマンドとして実行する。
  `/agent`(一覧+現在値)/`/agent <名>`(切替)/
  `/agent <名> <本文>`(保存して選択)、`/skill`(一覧)/
  `/skill <名>`(本文表示)/`/skill <名> <本文>`(保存)、
  `/help`(使い方)。本文は2行目以降に改行して書ける。
  不明な `/` コマンドは従来通りAPIへ送られる
- **指示書編集モード**(`ai_panel.py`): 「編集」ダイアログを
  非モーダル化し、開いている間はチャット入力欄をその指示書本文の
  編集欄にする。入力欄⇄ダイアログ編集欄を双方向同期し
  (ライブプレビューも即時反映)、Ctrl+Enter/「保存」ボタンで保存。
  プレースホルダに編集中対象を表示し、ダイアログを閉じると
  入力欄は通常モード+編集前の下書きに戻る

### Fixed

- **MCP設定の空欄保存を許可**(`ai_client.py`+`ai_panel.py`):
  外部MCPサーバ設定を空にして保存すると「JSONが不正です」の
  エラーになりMCPを無効化できなかった。空欄は
  `{"mcpServers": {}}` に正規化して保存し、MCPサーバなし
  (未設定)として扱う。ダイアログの説明文にも追記。
  あわせて client_secret 移行の通知が、空欄保存のような
  正規化でも誤って出ないよう `$store:` 参照の増加時に限定した
- **OAuth認証待ちの中断が効かない問題**(`ai_client.py`+`ai_panel.py`):
  MCP接続のauthorization_codeフローがブラウザ応答を最長180秒
  ポーリング待機する間、「中断」ボタンが観測されずパネルが
  「中断中…」のまま戻らなかった。`is_aborted` コールバックを
  `mcp_discover`→`McpSession`→`_McpHttp`→`_oauth_authorize`
  へ伝播させ、待機ループとサーバ接続ループを即座に打ち切る。
  中断時は `_mcp_done` を未接続へ戻し次の送信で再ディスカバリする
- **IME変換中のプレースホルダ重なり**(`ai_panel.py`):
  `QPlainTextEdit` は変換中(preedit)もdocumentが空のままのため、
  日本語入力開始時にplaceholderが未確定文字列と重なって描画され
  ていた。`_Input` で変換中はplaceholderを消し、確定/フォーカス
  アウトで復元するようにした

## [0.7.1] - 2026-10-18

### Added

- **外部MCPの秘密値を資格情報ストアへ**(`ai_client.py`):
  `mcp_servers.json` の `oauth.client_secret` に平文が書かれた
  まま保存するとOSの資格情報ストア(credential_store。
  APIキーと同じ保存先)へ自動で移行し、設定ファイルには
  `"$store:mcp:<サーバ>:client_secret"` 参照だけを残す。
  ストア保存に失敗した場合はエラーとし平文では保存しない
  (APIキーと同じ方針)。`headers`/`env`/`oauth.client_id`
  の値も `"$store:<キー>"` 記法で接続時にストアから解決される。
  設定ダイアログは移行後のJSONを表示して通知し、
  client_secret 未指定時は Basic 認証を付けず
  `client_id` をボディへ送る public client として動作する

## [0.7.0] - 2026-10-18

### Added

- **エージェント/スキル(指示書ファイル)**(`ai_client.py`+`ai_panel.py`):
  `~/.qgis-live/agents/*.md` は常時注入の指示書でパネルのコンボで
  選択(複数定義・切替・チャットごとの記憶に対応)。
  `~/.qgis-live/skills/*.md` はオンデマンドの手順書で
  一覧のみプロンプトに載せ、モデルが `qgis_pyeval` の `open()` で
  本文を読む(progressive disclosure)。両者とも「編集」ダイアログ
  (種別コンボでエージェント/スキル切替、編集/表示の2ペイン分割・
  入力中Markdownのライブプレビュー)から作成/編集/削除でき、
  `<plugin>/<kind>/` の同梱デフォルトはユーザ側同名ファイルが優先。
  同梱例として `skills/qgis-basics.md` を追加
- **AI自身による指示書の編集・選択**(`ai_client.py`):
  パネルローカルツール `ai_list_instructions` /
  `ai_read_instruction` / `ai_save_instruction` /
  `ai_delete_instruction` / `ai_select_agent`(保存は常に
  ユーザ側、同梱品は削除不可・同名保存で上書き)。
  エージェント一覧もid+説明+[active]マークでプロンプトに載せ、
  モデルが自律選択可能。保存依頼時は意図からagents/skillsを
  判別して理由を案内する指針をプロンプトに明記。
  外部オーケストレーター向けにMCP/RESTの `qgis_instruction`
  ツール(op=list|read|save|delete)も公開
- **外部MCPサーバ接続(MCPクライアント)**(`ai_client.py`):
  stdlibのみのMCPクライアントを追加。設定は
  `~/.qgis-live/mcp_servers.json`(Claude Desktop互換)、
  `command`=stdio子プロセス / `url`=Streamable HTTP(JSON/SSE両対応、
  Mcp-Session-Id追従)。HTTP側の認証は `headers` 固定値のほか
  `oauth` で authorization_code+PKCE(authorize_url指定時。
  ブラウザ同意→localhostコールバック受信→トークンを
  mcp_tokens.json へ永続化・refresh_token自動更新)と
  client_credentials(token_urlのみ指定時、client_id/secret、
  extraでプロバイダ固有formパラメータ)の両方に対応。
  401で1回リトライ。接続/認証エラー時はアプリ側設定の確認ガイド
  (Redirect URI登録・authorization_code有効・id/secret一致)を表示。
  発見ツールは `mcp_<サーバ>__<ツール>` に
  マングリングしてfunction callingへ混入し、パネルがセッション
  経由でローカル実行。API設定に「MCP」行(状態表示+設定ダイアログ、
  ダイアログには接続例BOXと「例をエディタへ挿入」ボタン付き)、
  保存時に次回送信で再接続。接続失敗はサーバごとに分離して表示
- **運用機能**(`ai_panel.py`+`ai_client.py`):
  実行中の中断ボタン(往復境界で停止)、最後の質問の「再送」、
  ツール実行前の確認モード(チェックONで都度Yes/No)、
  会話履歴のコンテキスト上限(古いターンから切詰め)、
  右下の使用量/累計コスト表示(API応答のusage実測値を
  チャット毎に累積・ctx=直近prompt_tokens実測または文字数推定)、
  チャット履歴の `~/.qgis-live/chats.json` への永続化(最新50件)、
  表示中チャットのMarkdown保存(↓)と履歴削除(✕)

### Changed

- API設定の表示切替トグルを⚙アイコンボタンに簡略化

## [0.6.0] - 2026-10-18

### Added

- **AIアシスタントに GitHub Copilot プロバイダを追加**(`ai_client.py` の
  `CopilotProvider`)。メッセージ形式はOpenAI互換だが、認証はAPIキー欄の
  GitHubトークン(`gho_`/`ghu_`/`ghp_`…)を
  `api.github.com/copilot_internal/v2/token` で短期トークンに交換し、
  応答の `endpoints.api`(individual/business/enterprise)へ送る
  (トークンは期限切れ前までキャッシュ)。**対応プランは
  Pro/Free/Business/Enterprise/EMU** — Business/Enterprise/EMUでは
  `endpoints.api` がプラン別API先を返すため同じ経路で自動解決
  (EMUのPAT制限時はデバイスフローを利用)。`v2/token` が応答しない環境では
  `copilot_internal/user` でAPI先を解決しGitHubトークンをそのまま
  Bearerに使う(`@github/copilot` CLI方式)フォールバック付き。
  GitHub Copilotの契約が必要で、エンドポイントはVS Codeの
  Copilot Chatと同じ内部APIを使う点に注意
- **「GitHubでサインイン」ボタン**(`ai_panel.py`): copilot選択時のみ
  表示され、OAuthデバイスフローでGitHubトークンを取得してAPIキー欄と
  OS資格情報ストアへ保存。既定のclient_idはVS Codeの公開OAuth Appで、
  同意画面には「Visual Studio Code」と表示される。
  `QGIS_LIVE_GITHUB_CLIENT_ID` で独自OAuth Appに差し替え可
- Copilotの `GET {api}/models` 応答(`capabilities.type`/`policy.state`/
  `supports.vision`/`limits.max_context_window_tokens`)をパネルの
  モデル一覧(種別・コンテキスト長付き)にマッピング
- エンドポイントを既定から変更した場合はトークン交換せずGitHubトークンを
  そのままBearerに使うため、copilot-api等の互換プロキシにも接続可能
- **AI応答のMarkdownレンダリング**(`ai_panel.py`): アシスタントの
  メッセージを `QTextDocument.setMarkdown()` で変換して表示し、
  見出し・リスト・表・コードブロックが整形される。
  user/tool/error表示は従来通りエスケープ済みテキスト
- **チャット履歴**(`ai_panel.py`): 「新しいチャット」ボタンで現在の
  会話を履歴コンボへ保存し新規開始(コンテキストもリセット)。
  履歴コンボから過去チャットを選ぶと表示内容と会話コンテキストが
  復元され、そのまま会話を継続できる。セッションはQGIS起動中のみ
  メモリ保持(永続化はしない)
- **ドックのタブ化**(`ai_panel.py`): パネル追加時に同じドック領域へ
  表示中ドックがあれば `tabifyDockWidget` でタブ化し、
  縦分割せずレイヤパネル等とタブで重なる(QGISプラグインの標準的な
  振る舞い)
- **API設定の表示切替**(`ai_panel.py`): 「新しいチャット」左の
  「設定」トグルボタンでAPI設定ボックスを表示/非表示。
  状態はQSettingsに保存。初回はAPIキー未設定時のみ開く

## [0.5.0] - 2026-10-18

### Added

- **汎用ブリッジ `_GenericBridge`**(`live_driver.py`): `plugin.bridge` を
  持たないプラグインに `bridge_call` が自動フォールバックする共通制御面。
  `pluginInfo`/`status`/`actions`/`trigger`/`run`/`openDialog`/
  `closeDialog` を提供し、`run`/`trigger` は QTimer.singleShot(0) で
  非同期発火するため対象がmodalダイアログを開いてもコマンド応答は
  ブロックされない。サードパーティ製プラグイン(mmqgis等)も
  repo外改変なしでAIから操作できる
- `describe_plugins` がbridge未搭載プラグインにも汎用アダプタ経由の
  metadata由来の自己記述を載せる(`generic: true` フラグ付き)。
  全ロード済みプラグインがカタログ上で発見・操作可能になった
- `bridge.py`(`QgisLiveBridge`)を新設しドライバ自身の `plugin.bridge`
  に配線。`pluginInfo`/`status` でコマンド面と稼働状態を自己記述

## [0.4.0] - 2026-10-18

### Added

- `describe_plugins` コマンドを追加。ロード済み全プラグインを列挙し、
  `bridge` を持つプラグインは各 `pluginInfo()` の自己記述
  (id/name/summary/when_to_use/invoke/methods/state)を集約した
  AI向けカタログを返す。`status` のプラグイン情報に `bridge`
  フラグも追加
- `mcp_http.py` / `mcp_stdio.py` のTOOLSに `qgis_describe_plugins`
  を追加(REST `/api/tools`・MCP `/mcp`・stdio shim全面で公開)

## [0.3.0] - 2026-10-18

### Added

- **AIアシスタントパネル**(`ai_panel.py` + `ai_client.py`)。
  `プラグイン > QGIS Live Driver > AI アシスタント` で開くチャット型
  エージェントドック。OpenAI互換(`/chat/completions` + function
  calling)とGemini(`generateContent` + functionDeclarations)を接続し、
  `mcp_http.TOOLS` と同じツール群を `driver.submit()` 経由でループ実行。
  リモート制御OFF時はパネル専用内部ドライバで動作
- APIキーはOS資格情報ストアに保存(`credential_store.py`:
  Windows=DPAPI / macOS=キーチェーン / Linux=Secret Service、
  フォールバックは600権限ファイル)
- モデル欄は編集可コンボ+「取得」ボタンで `GET {base}/models` から
  モデル一覧を取込み(種別グルーピング+価格表示)

## [0.2.0] - 2026-10-18

### Added

- 公開向けハードニング。HTTP REST `/api/*`・MCP Streamable HTTP
  `/mcp`・同梱stdio shim(`mcp_stdio.py`)の3接続面を追加し、
  ファイルJSONLと同じdispatchへ統合
- 全チャネルでセッショントークン認証を必須化(live_dir/token・
  レジストリJSONともユーザ限定ACL)。`QGIS_LIVE_API_KEY` /
  `QGIS_LIVE_TOOLS` envで公開範囲を制御
- ハブコマンド追加: `status` / `open_plugin` / `reload_plugin` /
  `bridge_call` + `plugin_id` 転送(`reply`注入で呼出元へ結果返却)

## [0.1.0] - 2026-10-18

### Added

- 初版。WebEngineを持たない制御専用プラグインとして、
  `WEBENGINE_LIVE_DIR/qgis-<pid>/<plugin_id>/` の
  commands.jsonl/results.jsonl ファイル経由で `pyeval` /
  `screenshot` を提供
