# Changelog — geo_driver

このプラグインの変更履歴。Keep a Changelog 準拠。
バージョンは `metadata.txt` の `version` と同期させる。

## [1.0.6] - 2026-11-24

### Fixed

- QGIS 終了時の `unload()` で access violation になるクラッシュ報告
  (旧ID `qgis_live_driver` 0.15.3 の `self._hot_menu.menuAction()`)を
  受けた再発行。新版では 1.0.1 の `_qt_dead` 判定 + 遅延除去で
  防御済みのためコード変更はなく、旧IDプラグインの残置が
  原因であることを確認・除去した環境での検証済みリリース

## [1.0.5] - 2026-11-24

### Fixed

- plugins.qgis.org 再アップロード用バージョンバンプ(同一バージョン番号はサイト側で重複不可のため)。内容は 1.0.4 のスキャン対応修正と同一

## [1.0.4] - 2026-11-23

### Fixed
- **QgisApp 構築中に live コマンドが実行されて QGIS がクラッシュする
  問題を修正** — `LiveDriver` の QTimer ポーリングは QgisApp
  コンストラクタ内の `processEvents`(スプラッシュ進行)でも発火
  し得るため、起動完了前に HTTP 経由(submit)の pyeval が
  `addMapLayer` 等を実行すると、layerAdded 系シグナルのスロットが
  未生成のドック(temporal controller 等)を触って access violation
  になっていた(QGIS 4.0.1 で実測)。`_poll` 冒頭に初期化完了ゲート
  (メインウィンドウ `isVisible()` + `iface.initializationCompleted`)
  を追加し、ready 前のコマンドはキューに滞留させて初期化完了後に
  実行する。起動後のホットリロードでは即 ready のため既存動作不変

## [1.0.3] - 2026-11-21

### Added
- `__init__._sweep_stale_registry()`: 起動時に `~/.qgis-live/` の
  死んだ pid の registry JSON(`<pid>-<plugin>.json`)を掃除。
  強制終了で `_stop()` が走らず残った検出ファイルを、検出側が
  順に probe してタイムアウトが積み上がる問題の恒久対策
  (ai-chat検証 ISSUE-4)。pid 流用時は保守的に残す
- `live_driver.submit()` タイムアウト応答に `busy`(実行中コマンドの
  id/type/開始時刻)と `queued`(滞留数)を追加、`status` 応答にも同項目を
  追加。長時間コマンドで後続が飢餓した際の診断を可能にする
  (ai-chat検証 ISSUE-3。GUIスレッド実行のプリエンプトは安全に
  行えないため可視化までとし、回復は外部再起動の既存方針を維持)

## [1.0.2] - 2026-11-21

### Fixed
- layer_org._move_to_group: レイヤ移動の clone→remove→insert 順を
  insert→remove に修正。元ノード除去が先だと
  QgsLayerTreeRegistryBridge が「最後のツリーノード消失」と判定し
  イベント処理後にマップレイヤ本体まで削除していた
  (geo_import 等からの追加レイヤが placed 報告後に消失する実害あり。
  docstring が記述する本来の順序にコードを合わせた)。

## [1.0.1] - 2026-11-20

### Fixed
- unload のメニュー除去(`_menu_cleanup`)で、遅延実行までに Qt 側が
  破棄済みの QAction/QMenu ラッパーへ `removePluginMenu` /
  `menuAction` / `deleteLater` を呼ばないよう `_qt_dead` 判定を追加。
  破棄済みオブジェクトへの呼出しは Python 例外ではなく access
  violation となり QGIS ごとクラッシュするため(実績: 旧世代
  qgis_live_driver 0.15.3 が `self._hot_menu.menuAction()` で
  QGIS を落とした件。新版は遅延化済みだが同一経路を防御)。

## [1.0.0] - 2026-11-20

### Added
- ai_panel.py / devin_tasks.py: **エージェントCLI依存の可視化と
  自動インストール**。Devin/Copilot 系(【ACP】・【ブリッジ】)を選ぶと
  プロバイダ行の下に検出状況行を表示し、CLI未検出時は「Install」
  ボタンから確認ダイアログ経由で公式手順の自動インストールを
  実行する(Devin=setup.ps1/install.sh、Copilot=winget→npm→
  GitHub Releases直接DLで `~/.qgis-live/bin` へ配置、ワーカー
  スレッド実行・進捗はチャット欄へ)。Devin は credentials.toml
  (windsurf_api_key)の有無、Copilot はログイン要否も併記。
  カスタム【ACP】はエンドポイント欄の起動コマンド先頭を
  リアルタイム検証する(自動インストールはしない)。
  検出は `devin_tasks.cli_status()`、インストールは
  `devin_tasks.install_cli()`。CLI検索はプロセスPATHに加えて
  Windowsレジストリの最新User/Machine PATHも見るため、
  QGIS起動後にインストールされたCLIも再起動なしで検出できる。
  devin.exe の既定検索先に単体CLI配置先
  `%LOCALAPPDATA%\devin\cli\bin` と `~/.qgis-live/bin` を追加
- ai_client.py: SYSTEM_PROMPT の Guidelines に地名移動の指針を
  追加。「場所名への移動は geo_search の searchAddress を優先」
  「QgsMapCanvas にズームレベルAPIは無く zoomScale(縮尺分母)/
  setExtent/zoomByFactor/zoomToFeatureExtent を使い、EPSG:4326 の
  緯度経度はキャンバスCRSへ変換してから setCenter」ことを明記。
  モデルが不存在の setZoomLevel を試し座標をハードコードする
  誤りを防ぐ
- ai_client.py / ai_panel.py / live_driver.py / mcp_http.py:
  **指示書の第3種別 `prompts`(おすすめプロンプト)**を追加。
  パネル入力行の「おすすめ…」コンボから選ぶとファイル本文が
  入力欄へ挿入され、✎ボタン・`/prompt` コマンド・
  指示書エディタ(kind=Prompts)・`ai_*`/`qgis_instruction`
  ツール(kind=prompts)で作成・編集できる。配置は agents/
  skills と同じ bundled `<plugin>/prompts/*.md` + ユーザ
  `~/.qgis-live/prompts/*.md` 上書きモデル。同梱の定型指示は
  レイヤ整理・標準線幅・画像保存・状態診断(geo_driver)、
  凡例作成(geo_legend)、地物検索(geo_search)の6件
- ai_client.py: **同梱指示書(skills/agents)を全管理プラグインから
  集約**するように拡張。従来は `geo_driver/skills|agents/` のみだったが、
  `qgis-plugin/<id>/skills|agents/*.md` を持つ全プラグイン
  (geo_legend/geo_webview等)をスキャンするため、ドメインごとの
  手順書を責務プラグイン側に同梱できる。
  `ai_list_instructions`/`list_skills` の結果メタデータに
  `when`(use_when ヘッダ行)を追加し、モデルがスキル選択の
  判断材料を取得できるようにした。
  併せて `skills/webgis-convert.md` を geo_webview 側へ移動
  (KASUGAI Canvas は geo_webview の責務のため)
- scale_style.py + scale_style/default.json: **スケール連動の
  標準線幅サービス**を追加。CADと異なりGISでは線幅を縮尺に連動
  できるため、カテゴリ×縮尺帯の標準幅テーブルをプロファイルJSON
  で管理し(layer_orgと同型: 同梱 + `~/.qgis-live/scale_style/`
  のユーザ上書き、QSettingsで切替)、bridgeメソッド
  `scaleStyleProfiles`/`scaleStyleTable`/`setScaleStyleProfile`/
  `suggestScaleWidth`/`applyScaleWidth` を追加。
  `applyScaleWidth` の mode: `mm`=現縮尺向けの紙面幅を固定設定、
  `meters`=実世界幅(m・RenderMetersInMapUnits)でズーム連動、
  `rules`=縮尺帯ごとに幅が切替わるルールベースレンダラを生成
  (geo_legend ロード時はその `applyRules` へ委譲、
  未ロード時は内部実装へフォールバック)。カテゴリはレイヤ名/
  geomで推定し、`road_major`/`river`/`boundary`/`contour` 等を
  同梱プロファイルが提供。`status()` にもアクティブ
  プロファイルを載せた。併せて同梱スキル
  `skills/scale-line-width.md` を追加し、AIチャットが
  線幅依頼時に手順をオンデマンド参照できるようにした
- devin_tasks.py + mcp_http.py/live_driver.py: **Devin CLI 委譲ツール**
  `qgis_devin_run`/`qgis_devin_status`/`qgis_devin_result`/
  `qgis_devin_abort` を追加。Devinセッションを
  バックグラウンドタスクとして起動し、task_id で状態ポーリング・
  ログ取得・killできる。AIパネル・MCP・RESTの全経路から利用可。
  エンジンは `engine` 引数で選択:
  `acp`=`devin acp` をJSON-RPC駆動(IDE認証を共有するため
  `devin auth login` 不要。session/load による再開、
  session/request_permission 自動応答、permission_mode→
  session/set_mode 写像 dangerous→bypass)、
  `print`=`devin -p`(`devin auth login` 必須。
  `--respect-workspace-trust false`/`--prompt-file`/`-r`/`--model`
  対応)、`auto`(既定)=IDE認証があればacp・無ければprint
- ai_client.py/ai_panel.py: **Devinをプロバイダとして追加**。
  プロバイダ一覧の各項目に接続方式の種別タグ(【API】/【ACP】/
  【ブリッジ】)を付与し、Devinを2形態で提供:
  `devin_acp`(Devin【ACP】)=`devin acp` 常駐セッションをチャット
  エンジンにし、Devin自身がツールループを回す
  (devin_tasks.AcpSession: initialize→authenticate(IDE認証共有)→
  session/new|load→session/prompt、session/cancel による中断、
  geo_driver自身の /mcp をMCPサーバとして注入するため
  DevinからQGIS操作も可能。エンドポイント欄=作業dir、
  APIキー不要)。`devin_bridge`(Devin【ブリッジ】)=OpenAI互換
  チャットへ qgis_devin_* ツール委譲指示を注入する疑似
  プロバイダ(ツールループは従来どおりパネル側)。
  `copilot_acp`(GitHub Copilot【ACP】)=`copilot --acp --stdio`
  セッションを同じ機構で駆動(認証はCLI側のghログインに委譲、
  authMethods提示時はbest-effortでauthenticateを試行)。
  `copilot_bridge`(GitHub Copilot【ブリッジ】)=OpenAI互換
  チャットへ qgis_copilot_* ツール委譲指示を注入する疑似
  プロバイダ。コンボ各項目に種別説明ツールチップを付与し、
  プロバイダ欄の「?」ボタンで3種別の違いをポップアップ表示
- devin_tasks.py + mcp_http.py/live_driver.py: **Copilot CLI
  委譲ツール** `qgis_copilot_run`/`qgis_copilot_status`/
  `qgis_copilot_result`/`qgis_copilot_abort` を追加
  (devin_tasks.run の agent 引数で共有。`copilot -p` は
  node+npm-loader.js 直接起動でcmdクォート問題を回避、
  dangerous=COPILOT_ALLOW_ALL=true で全ツール許可+dir信頼、
  -r でセッション再開。acp engine も同ワーカーで対応)

### Fixed
- live_driver.py / qgis-session.mjs: **リロード時の「open_dialog
  再表示」で管理用ダイアログまで勝手に開く問題**を修正。
  `reload_plugin_now` とフォールバック `reloadCode` は
  `open_dialog` を持つ全プラグインへ無条件で open_dialog() を
  呼んでいたが、プラグイン側が `open_dialog_on_reload = False`
  を定義した場合は再表示をスキップするよう opt-out を追加。
  geo_launcher(インストール管理窓)が本フラグを利用する。
  `open_plugin` コマンドは「開け」の明示要求なので従来通り
  無条件で開く
- ai_panel.py: **ツール出力の長い1行(例: `qgis_pyeval` のJSON引数)
  でドックの横幅が勝手に広がる問題**を修正。tool出力は `<pre>`
  (改行不能ブロック)で描画されるため QTextDocument の
  idealWidth が膨張し、QTextBrowser の sizeHint 経由でドックが
  押し広げられていた。ビューの横方向 sizePolicy を Ignored に
  してコンテンツ幅をレイアウトへ伝えないようにし、はみ出る分は
  ビュー内の横スクロールに委ねる。併せて添付画像サムネイルを
  scaled(220x44, KeepAspectRatio)に変更し、横長パノラマ画像でも
  attach行がドックを押し広げないようにした
- __init__.py: **ホットリロード経由の reloadPlugin で access
  violation になるクラッシュ**を修正。QMenu の triggered ハンドラ内で
  `unload()` が `iface.removePluginMenu` を呼ぶと、ポップアップ処理中の
  メニュー階層を書き換えて Qt 内部で落ちる(実績: 旧ID `qgis_live_driver`
  のホットリロード「すべて再読込」からの geo_driver 再読込)。
  `_defer_hot_reload` でリロード実行自体を `QTimer.singleShot(0)` で
  イベント完了後へ遅延し、さらに `unload()`/`initGui` のプラグイン
  メニュー操作(removePluginMenu・sweep)も `_defer_menu_cleanup` で
  遅延実行に変更。遅延 sweep が新世代アクションを誤削除しないよう
  `_sweep_menu_actions` は現行自身のオブジェクトを参照一致で除外する
- live_driver.py: **`bridge_call` の kwargs 形式引数を正規化**する
  `_bridge_args` を追加。モデルが `args=[{"k": v,...}]` や
  `args={"k": v}`、`args=[pos..., {"k": v}]` 形式で呼んだ場合、
  末尾辞書のキーが未バインドのパラメータ名に収まるときのみ
  kwargs として展開する(従来は `fn(*args)` で辞書がそのまま
  先頭位置引数に渡り "layer not found" 等で失敗していた)。
  普通の dict 引数(geo_report.setItemProperties 等)は
  キー不一致で従来通り位置引数として渡る
- __init__.py: **ホットリロード/reloadPlugin 後に
  `プラグイン > QGIS Live Driver` サブメニューが空になる問題**
  を修正。旧世代 `unload()` がキューイングした遅延
  `_menu_cleanup` は新世代 `initGui()` のアクション追加
  「後」に実行されるが、旧インスタンスは自アクション参照を
  unload で None に済みのため、`_sweep_menu_actions` の
  「現行自身を参照一致で除外」が機能せず、テキスト一致で
  新世代の全アクションを `removeAction`+`deleteLater` していた。
  モジュール再読込をまたぐ世代識別として `_MENU_OWNER_PROP`
  トークンを導入し、initGui で発行したトークンを mainWindow
  (プロセス内不変のQtオブジェクト)と追加する各 QAction/
  ホットリロード QMenu の menuAction に刻印。sweep は
  現行トークン所有の項目を除外し、無刻印(旧版の孤児)や
  死んだ世代の刻印のみ従来通り除去する
- ai_client.py: Copilot で `/chat/completions` を受け付けない
  **Responses API 専用モデル(GPT-6 系等)が送信エラーになる問題**
  を修正。`GET /models` の `supported_endpoints` で事前判別し、
  未判別のモデルは `model_not_supported` エラーから自動で
  `POST {api}/responses` へフォールバック・学習する。
  内部メッセージ列は従来どおり chat 形式で保持し、送信時にのみ
  Responses 形式(instructions/input/function_call/
  function_call_output)へ変換する

### Changed
- ai_panel.py: **API設定ボックス右上に「ヘルプ」リンクを追加**。
  GitHub Pages上の `qgis-plugin/geo_driver/docs/index.html`
  へブラウザで飛べるプラグイン全体のヘルプ導線
  (「?」ボタンの Docs と同じ `_open_docs()` を使用。
  API設定を畳んでいる時はボックスごと非表示)
- ai_panel.py: **「?」(プロバイダ種別ヘルプ)にドキュメントリンクを
  追加**。従来の種別説明ダイアログに「ドキュメントを開く」ボタンを
  追加し、プラグイン同梱 `docs/index.html`(AIパネル節アンカー付き)を
  ブラウザで開けるようにした(同梱docsが無い環境ではサイト側
  driver.html へフォールバック)
- ai_panel.py: **ツール実行確認を明示選択式のコンボ化**。
  「ツール実行の前に確認する」チェックボックスを廃止し、
  「ツール呼出」コンボ(**自動実行**(既定) / 呼出前に確認)へ
  置き換えた。保存キー `geo_driver/ai_confirm` は同じ真偽値で
  互換維持(旧設定のONは「呼出前に確認」として復元される)
- **プラグイン ID を `qgis_live_driver` → `geo_driver` にリネーム**
  (`geo_` シリーズ統一)。フォルダ名・metadata の name・
  ブリッジ `pluginId`・`<pid>-geo_driver.json` レジストリ・
  ホットリロード `CTRL_ID`・`tr` コンテキスト・
  QSettings プレフィックスを新IDへ移行。機能変更なし

## [0.16.3] - 2026-11-19

### Fixed
- live_driver.py: **ホットリロード/reload_plugin で qrc リソース
  モジュールを `sys.modules` から掃除していた問題**を修正。
  `qRegisterResourceData` はバッファをコピーせずポインタ保持する
  ため、pyrcc 生成モジュール(`resources`/`resources_rc`/`*_rc`)が
  GC されると Qt グローバルリソースリストにダングリングノードが
  残り、以後のあらゆる `":/"` パスの `QFile::open`(ドック
  タイトルバー等の standardIcon 解決)が `QResource::fileName` で
  access violation する(QGIS 4.0.1/Qt 6.8.1 実績)。掃除対象から
  `resources` および `_rc` 末尾のモジュールを除外し、
  geo_legend/geo_import 側の `resources_rc.py` でも登録バッファを
  `sys._qgis_pinned_qrc` に固定する対策を併施(QGIS 側の
  unloadPlugin による modules 掃除経路もカバー)

## [0.16.2] - 2026-11-16

### Added
- live_driver.py / bridge.py / mcp_http.py / ai_panel.py:
  **制御コマンドの監査ログ永続化**。`_handle` を通る全コマンド
  (ファイルJSONL/REST `/api/*`/MCP/AIパネル)を
  `~/.qgis-live/audit-<date>.jsonl`(QGIS_LIVE_REGISTRY準拠)へ
  追記する。レコードは ts/id/type/plugin_id/method/args要約/
  origin(呼出経路)/ok/所要ms を持ち、token・api_key・password
  等のsecrets系キーはマスク、セッショントークンは記録しない。
  ファイル経由のトークン不一致(unauthorized)も監査対象。
  他プラグインへの転送コマンドは転送元で1件だけ記録する。
  日次ローテーションに加え、QSettings `geo_driver/audit/*` で
  有効化・ファイルサイズ上限(既定5MB・超過時は時刻付き世代へ
  退避)・保持世代数(既定14)を管理できる。参照は新規bridge
  メソッド `auditLog(n, filter)`(フィールド一致dict/部分一致
  文字列)と `auditSettings(enabled, max_bytes, max_files)`。


## [0.15.3] - 2026-11-12

### Changed
- geo_toolbar.py: `geo_suite_toolbar()` に `ensure_visible` 引数を追加
  (既定Trueで可視状態を保証)。各プラグイン側の同形ヘルパも同仕様に揃え、
  個別利用=ドライバ非稼働でもGeoSuiteツールバーが表示されるようにした。
  表示を変えたくない経路(unload時のremoveAction等)はFalseを渡す

## [0.15.2] - 2026-11-07

### Added
- bridge.py: AIパネル(openAiPanel)・接続情報(openConnInfo)・
  Deploy Modeダイアログ(openDeployMode)・ホットリロード
  (listDevPlugins/hotReload)・リモート制御切替(remoteControl)を
  bridgeメソッドとして追加し、ドライバ自身の全機能を
  bridge_callからも操作可能にした

## [0.15.1] - 2026-11-07

### Added

- AIアシスタントパネルのプロバイダに **Anthropic(Claude)** と
  **Azure OpenAI** を追加。AnthropicはMessages API
  (`POST /v1/messages`, `x-api-key`+`anthropic-version`,
  tools=`input_schema`, tool_use/tool_resultブロック)をネイティブ実装し、
  モデル一覧は `GET /v1/models` のページング対応、usageは
  `input_tokens`/`output_tokens` を集計。Azure OpenAIはOpenAI互換の
  Chat Completionsを `api-key` ヘッダ+
  `…/openai/deployments/<deployment>/chat/completions?api-version=`
  (既定 `2024-10-21`)で送り、「取得」は `/openai/deployments` 一覧
  (不可時は `/openai/models` にフォールバック)。
  Grok/Mistral/Groq/DeepSeek等は従来どおりOpenAI互換プロバイダの
  エンドポイント変更で利用可能
- GeoSuiteツールバーに AI アシスタント(チャット)起動ボタンを追加。
  モードバッジの右隣に常駐し、クリックで既存の AI アシスタント
  ドックを開く/前面化する。ツールバー上に AI 関連のエントリ点が
  無かったための追加で、メニューからの起動と同じパネルを使う。
  アイコンは同梱 `icon_ai.png`("AI"グリフ)を使用
- **Connection Infoダイアログ**(新規 `connection_info.py`):
  `プラグイン > QGIS Live Driver > Connection Info` から開く。
  最上段にHarnessリポジトリ行(パス表示+コピー+「選択…」+「更新」)と
  リモート制御の状態を常時表示し、内容はタブで分割:
  `MCP`(エンドポイントURL+stdio/Streamable HTTPの設定JSON)、
  `REST`(API base+curl例)、`Session`(レジストリ/live dir/トークンを
  行ごとにコピー可能なフィールドで)。リモート制御OFF時は有効化手順と
  stdio shim設定のみ表示。トグルON直後にも自動表示され、
  初回利用者の「次に繋ぐ方法」を案内する
- **harness repoの指定経路**: 単体install(marker/junction無し)では
  `repo_root()` がrepoを解決できず Deploy Mode が使えなかったため、
  QSettings `geo_driver/harness_repo` による明示指定を追加
  (解決順: QSettings > marker.repo > junction推定)。
  Deploy Modeダイアログ上部にrepo行+「参照…」ボタン、
  Connection Infoダイアログにもrepo表示+「選択…」ボタンを設置。
  指定すれば単体installからでも「開発モードへ切替」で
  deploy-plugin.ps1 による junction 化へ進める
- stdio shim(`mcp_stdio.py`)のツール一覧に `qgis_instruction` を追加
  (HTTP側 `/mcp` と同一。op=list|read|save|delete)
- ホットリロードメニューが空の時は無効化した
  「(no development plugins)」プレースホルダを表示

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
- `mcp_stdio.py` のdocstringを現仕様に修正
  (有効化条件を `WEBENGINE_LIVE_DIR` 前提の記述から
  「Remote Control の有効化」へ)

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
  geo_import/geo_legend がプラグインツールバーから
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
  `plugins['geo_driver'].layer_org.place_all([(layer, ctx)])`
  で、プロファイルJSONのルールに従いレイヤをグループ配置・
  リネーム・.qmlスタイル適用する。プロファイルは
  `<plugin>/layer_org/*.json`(同梱デフォルト) +
  `~/.qgis-live/layer_org/*.json`(ユーザ/業界別、同名優先)の
  2階層で、アクティブは QSettings
  `geo_driver/layer_org/profile`。match条件(format/ext/
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
  翻訳カタログ(`i18n/geo_driver_<lang>.ts`/`.qm`)を追加
  (各164メッセージ)。ja と合わせ全9言語を同梱。

## [0.11.0] - 2026-10-18

### Added

- **国際化(i18n)対応**: UI文字列を英語ソースに統一し、Qt翻訳
  (`.ts`/`.qm`)経路を整備。`i18n/geo_driver_ja.ts`/`.qm` を新設
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
  しても自動で開き直す。表示状態は `geo_driver/ai_panel_open`
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
  一括リロードも可(制御面の geo_driver は最後。
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
