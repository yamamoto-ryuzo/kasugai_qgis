# 変更履歴(Changelog)

## 4.35.3

- plugins.qgis.org 再アップロード用バージョンバンプ(同一バージョン番号はサイト側で重複不可のため)。内容は 4.35.2 のスキャン対応修正と同一

## 4.35.2

- **plugins.qgis.org セキュリティスキャン対応** — サイト側は全有効テスト(-t)で bandit を走査するため、B110/B112 の `# nosec` 漏れ/ID誤り(continue系はB112)を修正(panel.py×5・plugin.py)。スキャナ設定ファイル(.bandit/.flake8)は `-t` との衝突(Non-exclusive include/exclude)を避けるためZIP非同梱へ方針転換

- **QGIS 4.2.3 対応: `QgsMapLayer.attribution()` の非推奨警告を解消** — QGIS 3.38+ で非推奨となった `layer.attribution()` を、`serverProperties().attribution()` 優先＋旧 API フォールバックの二段構えに変更（`kasugai_export._attribution`）。live_kasc/kasugai_export 双方の経路で QGIS 4.2.3 実行時の deprecation warning が 0 になることを確認

- **Live View で QML シンボル画像が表示されない問題を修正** — `/live/style` が返す .qml のシンボル画像参照（svgmarker/rastermarker/svgfill 等）はローカルパス（`C:/…/3503.svg`）のままだったため、Canvas 側が `/live/<name>.svg` へ相対解決して全件 404 になっていた。`live_kasc._rewrite_qml_assets_live` を新設し、参照を実ファイル解決のうえ `http://127.0.0.1:<port>/live/file/<encoded-abs-path>` へ書き換えるよう変更（エクスポート経路 `_export_qml_assets` の canvas_data/ 複製に相当する live 版）。あわせて `server_manager._live_file_allowed` の許可判定へ「QGIS SVG 検索パスまたはプロジェクトディレクトリ配下の実ファイル」を追加（従来のレイヤソース+sidecar に加え、対象外パスは引き続き 403）。verify-live-view スキル＋`web/verify/results/probe-live-view.mjs`（Canvas 側）で全6エンジン実機検証 41/41 PASS を確認

- **ベースマップ未選択時に Canvas 側へ「ベースマップなし」を伝搬** — QGIS で表示中のベースマップが 1 つも無い(背景図グループ OFF・base: 候補が全て `| off`)場合でも、`.kasc` 末尾に必ず追加される既定候補行(地理院標準地図等・off 無し)が Canvas 側で「最初の選択肢」として自動選択され、QGIS=なし/Canvas=標準地図 の不整合になっていた。`live_kasc`(/live/kasc)と `kasugai_export`(エクスポート)の両方で、表示中のベースマップが無い時は `base: ベースマップなし | none` モード行を出力するよう変更。Canvas 全エンジンで「ベースマップなし」が初期選択され、Live でのベースマップ ON/OFF 切替も rev 更新→再取得で正しく追従する(実機確認: 背景図 OFF→`base: | none` 出力・ON→該当行の `| off` 解除)

- **リリース前 lint 整合: flake8 findings=0 を回復** — 4.35.x の変更で混入した E127/E128/E131(継続行インデント)・E271(余分な空白)・E741(変数名 `l`)・F841(未使用 `numeric`)を実修正(動作変更なし)。bandit/detect-secrets は指摘0を確認

- **docs/spec.html をタブ別構成へ再編成** — 冒頭に「0. 概要」（プラグイン全体像・2本柱=サーバレス Web 配信/Canvas Live View・組み込み HTTP サーバ・タブ構成表）を新設し、以降を実装タブ（`panel_base.ui` の tabWidget_main）ごとの節へ再編: §1 Web（旧§15 エクスポート全体＋HTTP サーバグループ）・§2 Live（旧§15 Live View 節＋Live タブ UI 記述）・§3 Layers（カスタムレイヤ＋レイヤ別オプション）・§4 Filter（新規: サイト共通フィルタの自動適用仕様）・§5 XYZ（新規: 自動/手動焼き付け・Basemap Groups）・§6 Other（テーマ/パーマリンク/共有・/screenshot）・§7 パネル下部（External Control・設定）。共通仕様は §8 API・§9 廃止機能・§10 CRS・§11-14 へ移管。あわせて SPEC.md（英語ミラー）を同構成へ追随、getting-started/technical の旧 §15 参照を新アンカーへ修正

- **docs/use/ に「使い方」ページ群を新設し、タブ別仕様を各ページへ集約** — タブ別機能を KASUGAI Canvas docs/use/ と同じ流れ（各ページが「使い方 → 設定・ツール仕様 → 関連仕様」、節内は機能ごとの h3）で `use/1-1-Webタブ`〜`use/1-7-パネル下部` の7ページへ分割し、spec.html のタブ別節（§1〜§7、図1〜図9を含む完全仕様）を各ページの「設定・ツール仕様」節へ移動。spec.html は目的・概要（図A〜C の全体フロー図＋図一覧を追加）とタブ横断の共通仕様（§8〜§13: API・CRS・セキュリティ・QA・ファイル構成・履歴）のみを収録する構成へ。なお「9. 廃止された機能」節は削除済み。左ナビの「タブ別機能」セクションはタブごとの項目（`1. Web タブ` 等）＋機能名の子リンク（`1-1 エクスポート・出力設定` 等、「使い方」節の h3 から自動抽出）で、関連する資料ページも各タブ配下へ集約（主な機能・マルチエンジン→Web タブ、外部連携方針→Other タブ、技術資料→パネル下部）。「資料」セクションはライセンスのみ残し、連携構成図は「概要」へ移動。各資料ページの連番タイトル（`N. `）は廃止。`build-plugin-docs.py` に `use_tabs`（docs/use/*.html の列挙＋h3 子リンク＋extra 資料配下化）とサブディレクトリ対応（nav.js のリンクを `document.currentScript` 基準の絶対パス化・isActive 判定の正規化・子リンクのアクティブ表示）を追加し、全プラグイン nav.js を同型再生成。index.html に使い方カードを追加

## 4.35.1

- **▶ WebView の処理順を「エクスポート→route変換→起動」に厳格化** — CDN モード→route の変換を `plugin.py`(エクスポート前)から `bridge.kasugaiExport` 内の `export_kasugai_project` 完了直後へ移動。ブラウザ起動が必ずエクスポート完了後に来る構造をコード上でも明示し、「起動が先行して古い .kasc が開かれる」経路が存在しないことを保証。`route='hosted'` 入力時の `canvas`→kasugai / FILE→local 解決は bridge 内で行われ、応答 `route` は解決結果を返す。`canvas` モードで Canvas 未検出時はエクスポート完了後にインストール導線へ合流する動作を維持(理由メッセージも解決 route ベースに修正)

## 4.35.0

- **CDN コンボをエンジン供給元モードとして統一(`local` モード追加)** — Web タブ「CDN:」コンボに第4モード `local` を追加し、Live View のエンジン配信元はこのコンボの選択に完全従属するよう変更。`stable`/`unstable`/カスタム http(s) URL = ホスト版エンジン(kasugai-canvas-web 等。アプリ未導入でも完結・既定)、`canvas` = 稼働中の Canvas アプリ(:8510)を直接使用(▶ Canvas と同じアプリ経路・未検出時はインストール導線/警告)、**web/ フォルダのファイルパス = FILE モード**(geo_webview サーバがそのツリーを /<engine>/ で静的配信。開発時・閉鎖ネットワーク向けに任意の web/ を直指定)。アプリ未導入前提のシンプル構成が既定動作。4.34.2 で入れた3段自動検出を廃止しモード明示型へ置き換え。ローカル系モードで配信元が見つからない場合は警告通知。エクスポートZIP名は `kasugai_canvas_local.zip`。**▶ Canvas ボタンを「Install KASUGAI Canvas」(常時インストール専用)に変更** — 起動経路は `canvas` モード + ▶ WebView に一本化し、ボタンは再インストール/修復の役割のみ(完了後は従来通り登録・ブラウザ起動へ合流)。**「Admin」ボタンを「Canvas Customize」(CANVASカスタマイズ)に改名** — 機能は同じ(稼働中アプリの /admin/ UI設定画面を開く)。**CDN コンボの選択肢を `stable`/`unstable`/`canvas`/`url`/`file` の5モード化**し、Install ボタン下に **URL/パス表示欄+「…」選択ボタン** を追加 — `url`/`file` は実値を `kasugai_hosted_value` に別保存(表示欄で編集・参照)、他モードは解決先を読取専用表示。直書きURL/パスの旧形式も互換受理

## 4.34.2

- **Live View のエンジン配信元を3段チェーン化(アプリなし完結)** — `open_external_live_view` の URL が従来は常に本プラグインサーバ(:8089)の `/<engine>/` 静的フォールバック(インストール済み `web/` のスナップショット)を使っていたため、アプリ更新が 3DVIEW へ反映されず、またアプリ未導入環境ではそもそも開けなかった。以下の優先順で解決するよう変更: (1) 稼働中の Canvas アプリ(`detect_kasugai` で検出) → `http://127.0.0.1:8510/<engine>/`(アプリの web/ は自動更新に追随・一体運用の本来経路)、(2) アプリ未起動・インストール済み → 従来の `/<engine>/` 静的配信(オフラインでも動作)、(3) アプリ未導入 → ホスト版エンジン `hosted_engine_base()`(kasugai-canvas-web、**Web タブの CDN コンボのチャンネル stable/unstable/カスタムURL がそのままモードとして効く**)。これにより「CDN エンジン + :8089 live API」で **Canvas アプリ未導入でもライブビューが完結**する。live API はいずれの段でも本サーバ(:8089)を指し、CORS(hosted/ループバック許可済み)・Private Network Access プリフライト共に対応済み

## 4.34.1

- **`/live/features` の既定地物数を 2000→10000 へ引き上げ** — `limit=` 未指定時の既定値を変更(上限 20000 は据置)。Canvas 側の live クエリ(addLiveLayer・範囲追従再取得)も同値へ統一。`offset=` ページングと併用で 20000 超のレイヤも継続取得可能

## 4.34.0

- **「Follow Canvas view」(Canvas へ追従)チェックを Live タブへ追加** — `POST /live/camera`(Canvas 視点→QGIS キャンバス)は従来無条件で適用されていたが、第3の制御フラグ `qgis_follow`(QSettings `kasugai_live_qgis_follow`・既定 true=従来動作維持)でゲートするようにした。OFF 時は camera POST を受けても `applied:{enabled:false}` を返すだけで QGIS キャンバスを動かさない。「Follow QGIS canvas」(Canvas→QGIS 追従)・「Show QGIS selection」と並ぶ Live タブの3つ目のチェックで、`GET /live/state` の `live.controls`・`POST /live/controls {qgis_follow?}`・bridge `liveSetControls(qgis_follow=)` の全経路で共通。i18n 9言語対応

## 4.33.0

- **Canvas Live 制御を QGIS 側へ集約(パネル「Live」タブ新設)** — これまで Canvas 側の「QGIS Live」パネルにあった操作(追従チェック/選択表示チェック/レイヤ追加)を geo_webview パネルへ移設し、QGIS 側を正とする構成に統一。Live タブは `tabWidget_main` の Web タブ直後へ動的挿入(`panel.py` コード生成・panel_base.ui 変更不要)。構成: エンジン選択コンボ+「Open Live View」(`/live/kasc` 経路・`open_external_live_view`)、「Follow QGIS canvas」「Show QGIS selection」チェック、ベクターレイヤ選択コンボ+「Add to Canvas」、ステータスラベル
- **制御フラグの正を QSettings に集約** — `live_sync.live_controls()`/`set_live_controls()` が `kasugai_live_follow`(既定 false)/`kasugai_live_selection`(既定 true) を QSettings へ永続化。`GET /live/state` の `live.controls`・`POST /live/controls`・bridge・パネルの全経路で同じ値を返し、変更時は `server_manager.on_live_controls_changed` フックでパネル表示へ逆同期する
- **`POST /live/controls` エンドポイント追加** — body `{follow?:bool, selection?:bool, add?:"<kasc title>"}`。follow/selection は QSettings へ、add は `live.add_layers` キュー(seq 連番・直近50件保持)へ積む。Canvas 側は 400ms ポーリングの `/live/state` から controls を読み、未処理 seq の add_layers を検出して `/live/features` 範囲読み込みでレイヤ化する
- **bridge メソッド追加** — `liveControls`(現在値)/`liveSetControls`(更新・payload または follow/selection 引数)/`liveAddToCanvas`(レイヤ追加キュー投入)。AI エージェントからも Canvas 追従・選択表示・レイヤ追加を操作可能
- **Canvas 側変更(kasugai_canvas リポジトリ)** — `web/shared/live-panel.js` は接続バッジのみに退化(操作 UI 撤去)、`web/shared/live.js` が controls 適用+add_layers 処理を担う。複数 Canvas ビューア接続時は制御が一律適用される点に注意(通常の非 live アプリは無関係)

## 4.32.1

- **「▶ WebView」ボタンを「Admin」と同じ幅に揃えた** — パネル「Web配信(サーバレス)」のエンジン選択行(`Engine:` ラベル+コンボ+`▶ WebView`)と起動行(`▶ Canvas`/`Admin`)を1つの `QGridLayout`(等幅2列)へ統合。左列は `Engine:` ラベル+エンジンコンボの入れ子レイアウトとし、右列の `▶ WebView` が下段 `Admin` と同一列幅・右端揃いになるよう修正(従来はラベル分だけ右側が狭く不揃いだった)

## 4.32.0

- **ライブモードでベクターをネイティブ形式のまま配信** — `/live/kasc` は従来全ベクターを `geojson:` 行 + `/live/features`(GeoJSON オンデマンド配信・既定上限2000件)へ一律変換していたが、WebGIS としての形式別性能を測るため原本形式を維持するよう変更。ファイル/URL ソースは `_native_ref` と同じ判定で `gpkg:`/`geojson:`/`geoparquet:`/`flatgeobuf:`/`shp:`/`kml:`/`gpx:`/`topojson:`/`duckdb:`(CSV/TSV・subset 付き Parquet) 行を出力し、ローカルファイルは新エンドポイント `GET /live/file/<urlencoded-abs-path>` 経由で原本を直接配信(コピー無し・`where=`/各種オプション・`style=` は従来通り)。ファイルを持たないソース(メモリ/PostGIS/再投影必要等)のみ `/live/features` へフォールバックし、URL に `limit=20000`(サーバ上限)を明示
- **`GET /live/file/` エンドポイント追加** — 現在プロジェクトのレイヤソース実パス(`_source_path` 解決)と Shapefile sidecar(.dbf/.shx/.prj 等・`foo.shp.xml` 含む)・SQLite `-wal`/`-shm` のみを許可するホワイトリスト方式で、それ以外のパスは 403。`Range: bytes=` 単一範囲に対応し FlatGeobuf/GeoParquet の範囲読み(206 Partial Content)が動く。gpkg:/flatgeobuf: の `bbox=auto` 表示範囲連動絞り込みもネイティブ行のまま機能する
- **編集中レイヤはライブ表示から除外** — `isEditable()` のレイヤは原本ファイルに未保存編集が反映されず、かつ GeoJSON 全件転送は大レイヤで重いため、ライブ kasc から除外(`# skipped:` 注記付き)する運用とした。編集終了(保存/ロールバック)で自動復帰
- **Canvas 側修正(kasugai_canvas リポジトリ)** — `/live/features` 応答のエンベロープ `{ok, geojson:{...}}` が `normalizeGeoJsonToFeatureCollection` で空に正規化され、従来の geojson: 行が**地物0件を描画**していた問題を修正(`.geojson` メンバーの再帰アンラップ。shared/vector-load.js・全エンジン共通)

## 4.31.0

- **「3D Canvas View」ドックを廃止し外部ブラウザに一本化** — QGIS 4.x は QTBUG-139109 対策の `QQuickWindow::setGraphicsApi(Software)` により埋め込み WebView で WebGL が使えないことが確定したため、半機能の埋め込みドック(WebGL 不要エンジン表示+WebGL 系の外部委譲)を撤去。live 表示は「Open Canvas Live View」アクションまたは bridge `liveView`(旧 `live3dView`)で既定ブラウザを開く構成に統一(フル WebGL/Cesium・同一 live セッション)。QGIS 内の「ざっと確認」は外部ブラウザ側に集約される
- **bridge `live3dView` → `liveView` に rename** — action は `open`(既定。`external` 同義)/`status`、第2引数 `engine` でエンジン指定可。ドック制御系(close/reload)は撤去
- **QTWEBENGINE_* env 正規化を撤去** — 埋め込み WebEngineView が唯一の利用者だったため、`QTWEBENGINE_DISABLE_SANDBOX`/`QTWEBENGINE_CHROMIUM_FLAGS` のプロセス env 書き換えを削除(live3d_dock.py と共に)
- `/live/*` エンドポイント(kasc/style/features/live.json/render)・live_sync の `view_active`・カメラ双方向同期は無変更で継続
- **アイコンを役割別に刷新** — 本体 `icon.png` は「WebGIS への窓口」の地球+ピンに描き替え(既存ピンの系譜を継承)、「Open Canvas Live View」には「QGIS のリアルタイム3Dの窓口」の等角キューブ+ライブドットの専用アイコン `icon_live_view.png` を新設
- **全 HTTP 応答に `Cache-Control: no-cache` を付与** — 従来は応答にキャッシュ系ヘッダが無く、ブラウザが shared/live.js 等のモジュールをヒューリスティックキャッシュしてプラグイン/Canvas 更新が即反映されない事態があった。ETag/Last-Modified を出さないため no-cache が毎回の再取得を強制する
- **「Open Canvas Live View」を専用ウィンドウ起動に変更** — Chrome/Edge の `--app=<url>` モード(アドレスバー・タブなしのアプリ風ウィンドウ)で開き、「QGIS 専用ビューア」としてタブに紛れない形にした。検出順は Edge(ProgramFiles(x86)/ProgramFiles)→Chrome(ProgramFiles/x86/LocalAppData)。見つからない環境では従来通り既定ブラウザの通常タブへフォールバック

## 4.30.0

- **「3D Canvas View」ドックを追加** — KASUGAI Canvas を QGIS 内へ埋め込む live ビュー。QGIS 標準の「新規3Dマップビュー」(`Qgs3DMapCanvas`)と同じドックポジションに据え、2D メインキャンバス(Qt6)はそのまま存続させる構成。メニュー/ツールバーからトグル表示(既定 Right ドック)
- **埋め込み WebGL 不可への対応(実機検証で判明した QGIS 4.x 仕様)** — QGIS は QTBUG-139109 対策として `QQuickWindow::setGraphicsApi(Software)` を起動時に実行しており、QtWebEngine の in-process GPU 初期化が失敗して **QGIS 内蔵 WebView では WebGL が使えない**(Cesium/MapLibre は初期化不可)。このため以下のマルチエンジン連携構成とした:
  - ドックは初回ロード後に `webgl2` コンテキストをプローブし、WebGL 不可を検出すると Cesium(3D)を外部ブラウザで自動オープン(フル WebGL + live 連携)し、埋め込みドックは WebGL 不要の Leaflet(2D live ビュー)へ切替+メッセージバー通知
  - ドック内 Canvas アプリのマルチエンジン切替は維持。ページ内から WebGL 必須エンジン(cesium/maplibre)への遷移が要求された場合は `acceptNavigationRequest` でキャンセルし、同じ live セッション URL を外部ブラウザへ委譲(`externalEngineRequested` シグナル)。leaflet/openlayers/gsimaps/navara は埋め込みのまま動作
  - レンダラ即死対策として `QTWEBENGINE_DISABLE_SANDBOX=1` を engine 初期化前に設定(QGIS 環境では Chromium サンドボックス起動が DLL_NOT_FOUND で失敗)。また起動スクリプトが `QTWEBENGINE_CHROMIUM_FLAGS` に含める `--disable-gpu`/`--disable-gpu-compositing` は WebGL を死なせるため除去する(`--no-sandbox` 等は温存)
- **live ネイティブモード(エクスポート不要)** — 新エンドポイント:
  - `GET /live/kasc`: 現在のレイヤツリー・表示状態から .kasc をオンデマンド生成(ファイル出力なし)。ベクターは `geojson:` 行が `/live/features`(GeoJSON オンデマンド配信)・`style=` が `/live/style`(.qml オンデマンド)を参照し、subsetString・スタイルは常に現在値が出る
  - `GET /live/style?layer=<title>&name=<style>`: レイヤの現在スタイル/名前付きスタイルを .qml XML で返す(theme 行の `;style=` もこのURLを参照)
  - `GET /live/live.json`: shared/live.js の live.json ポーリング規約を live ネイティブ経路で再現(rev/changed/full を `/live/state` と同一のサーバ状態から返す)
  - Canvas ネイティブ未対応ラスタ(GDAL ラスタ等)は `/live/render`(QGIS 描画 PNG)の `image:` 行として出力し視覚再現を担保。XYZ/WMS/WMTS・3D Tiles(URL)・ベクタータイル(URL)はネイティブ行で出力
- **live_sync の `view_active` ゲート追加** — `kasugai_live_sync` 設定が OFF でも、3D Canvas View が開いている間は変更監視を動かし、エクスポート先が無い場合は差分エクスポートを行わず `live_update(changed, full=)` で rev だけ進める(Canvas 側が rev 検出 → `/live/kasc` 再取得で反映)。ドックを閉じると監視は従来の設定値へ戻る
- **bridge `live3dView` 追加** — `open`/`close`/`status`/`reload`/`external` で AI・外部からドックと外部 live ビューを制御可能(`external` は第2引数 `engine` でエンジン指定可)
- **「Open Canvas Live View」アクション追加** — ドックを経由せず外部ブラウザで live セッションを1アクションで開く(QGIS+Canvas の2画面運用)。開いた時点で live 監視を `view_active` にして以後有効のままにするため、ドックを閉じても外部ビュー側の同期は継続する
- QtWebEngineWidgets が無い環境では外部ブラウザで同じ URL を開くフォールバック

## 4.29.1

- **GeoJSON 変換で 255 文字超の文字列フィールドがあるレイヤが全層エクスポート失敗する不具合を修正** — `QgsVectorFileWriter` はソースのフィールド定義(幅/精度)をそのまま使うため、GPKG 由来の `VARCHAR(255)` 等の幅制限が GeoJSON(幅の概念なし)書き出しで強制され「文字列の長さ N はフィールドの上限(255)を超えています」で変換エラーになっていた。GeoJSON 出力時は幅を除いた memory レイヤへ実体化してから書き出すよう修正(Lizmap demo `events.qgs` の `montpellier_events`(description 列が最大 1157 文字)で検出・1151 地物の出力を確認)

## 4.29.0

- **「XYZ」タブを新設**(Filter タブの直後) — XYZ 関連設定を1か所へ集約:
  - ベクター→XYZ 焼き付け設定(「XYZ tiles」チェック+Zoom 範囲)を Web タブから移設(QSettings `kasugai_xyz_tiles`/`kasugai_xyz_zmin`/`kasugai_xyz_zmax` と従来通り同期)
  - ベースマップグループ追加名エディットを移設(設定ダイアログ「Basemap Groups」と同じ QSettings `kasugai_basemap_groups` を読み書き)
- **「Standalone XYZ export」追加(独立機能)** — **出力対象はレイヤパネルで選択中のレイヤに固定**(タブ内にその旨を明示し、一覧は選択へ自動追従)。`.kasc` 出力と同じ QGIS レンダラ焼き付け経路(`_render_vector_xyz`)で `<出力先>/xyz_tiles/<slug>/{z}/{x}/{y}.png` へ出力し、単体確認用の Leaflet `index.html` を各レイヤへ生成。`.kasc` エクスポートとは独立して動作し、ベクター以外のラスタ/WMS レイヤも再焼き付けできる。「Add baked tiles to the project」で焼き付け結果を `type=xyz` の file:// ラスタレイヤとしてプロジェクトへ追加し地図上で即確認できる。ズーム範囲はタブ上部の設定に従う(未指定は縮尺連動+タイル数上限の自動)。出力先は `/export-data/` 配信ルート配下のため HTTP サーバ稼働時は `/export-data/xyz_tiles/<slug>/index.html` でブラウザ確認も可能
  - 一覧の `render` 列でレイヤ別に `xyz`(常にタイル化)/`vector`(タイル化しない)/`auto`(自動)を編集でき、レイヤ customProperty `kasugai_render` へ保存(.kasc 出力の自動判定でも使用)
  - 対象は「Selected: <レイヤ名>」の1行表示のみ(一覧UIは持たない)。選択変更・レイヤ追加/除去・タブ表示で自動追従。未選択時はアクティブレイヤへフォールバック。レイヤ別焼き付け上書きは `kasugai_render` レイヤプロパティ(xyz/vector/空=auto)で指定可(.kasc 出力と共通)
- **bridge `xyzExport` 追加** — 上記と同経路を API 化。`layers`(レイヤ名/ID の文字列またはリスト、省略時はレイヤパネルで選択中のレイヤ=UI と同じ)・`zmin`/`zmax`・`out_dir`・`add_to_project` を指定可
- i18n 9言語(de/es/fr/hi/it/ja/pt/ru/zh)へ XYZ タブ関連文字列を追加

## 4.28.0

- **Filter タブのフィールド/サイト切替時のチェック状態を実態に一致させるよう修正** — 従来は旧フィールドのチェック値をそのまま引き継ぎ「表示と選択が異なる」状態になっていた。切替時は適用済み subsetString から再シード(同フィールド適用中→その値のみ、`1=0`→0件、無し/別フィールド→全チェック)
- **Filter タブの複数選択で「チェックした値だけが表示される」に統一** — 従来の「0件選択=フィルタ解除=全表示」は全選択と全解除が同じ見た目になり分かりにくかった。0件選択は IN で subsetString `1=0`(全地物非表示)・NOT IN で解除(全表示)として即適用し、全選択/全解除で地図が正反対に変化するよう変更(Canvas フィルタタブと同仕様)
- **Canvas 側フィルタ操作のライブ同期エコーを修正** — `/live/writeback`(Canvas→QGIS)適用中の変更検出抑止を with ブロック終了後 2 秒の時間窓にも拡張し、setSubsetString 後に遅れて発火するシグナルが `_mark`→再エクスポート→`liveSync` push の往復を起こさないようにした。また writeback 適用時に `where=` を `_filter_panel_state` へも同期し、再エクスポートで古い `filter_values` が出力されて Canvas 側フィルタタブの選択を巻き戻す問題を防止(全解除→値クリア、IN/NOT IN 式→values 更新)

- 「Filter」タブ追加: レイヤ/数値フィールド(ドロップダウン)/演算子(= != < <= > >=)/値 を選んでレイヤフィルタ(subset string)を適用・解除。地図表示とエクスポートデータに反映
  - SITE(グループ)単位で共通属性を一覧しサイト内全レイヤへ一括適用。数値フィールドは数値比較、非数値フィールドは = / != + 既存値ドロップダウン。「Multi-select」で複数値のチェックリスト + IN / NOT IN に切替可能(「全選択」「全解除」ボタン付き)
  - **選択時点で即適用**(「適用」ボタン廃止) — 値・演算子・複数選択の変更でその場で subset string を適用(テキスト入力はデバウンス)。サイト/フィールドの選択自体では適用しない。値0件(全解除/入力クリア)はフィルタ解除として即反映。選択が即座に subsetString + `filter_*` エクスポート状態へ反映され、Canvas 側のデフォルトと一致する
  - フィールドコンボ再構築時のシグナルカスケードで複数選択チェックが消える不具合を修正(blockSignals 追加 — タブ切替/サイト再読込で `filter_values` が欠落する原因だった)
  - Filter タブの選択状態を `plugin:` 行の `filter_site=`/`filter_field=`/`filter_multi=`/`filter_op=`/`filter_values=`/`filter_value=` として出力し、Canvas 側「フィルタ」タブの初期選択として復元される
  - フィルタ適用レイヤのベクター変換(GeoJSON/FlatGeobuf/GeoParquet)で、where-eval 対応式はデータへの焼き込みをやめ全地物を出力し `| where=` を付与 — Canvas 側でフィルタタブから値の再列挙・絞り替えが可能に。非対応式は従来通り焼き込み

- Layers タブ EDIT テーブルのチェック列を `LIST`/`表示` の2列に分離 — `LIST`=Canvas へ引き継ぐか(外すと `kasugai_export='off'` で .kasc に出力しない)、`表示`=Canvas での初期表示(外すと `kasugai_vis='off'` で `| off` = 引き継ぐがレイヤ一覧にチェック無しで表示)。`kasugai_vis` は QGIS 上の非表示レイヤにも適用され visible_only スキップより優先して `| off` で出力。一覧から隠す `list=off` は従来通り opts/プロパティで指定可能
- カスタムレイヤタブの凡例を `legend_order=asc|desc|reverse|ラベル列挙`（opts 列・`kasugai_opts`）で並び替え可能に。VIEW は凡例アイコン/項目も表示（非表示・list=off レイヤは非表示）。Layers タブは分類凡例をレイヤ行の子として表示。VIEW モードでメンバー/凡例項目を選択し ▲▼ ボタンで並び替えると `order=`/`legend_order=` がレイヤへ自動保存される

- **カスタムレイヤタブ(custom-layer)+レイヤ別 .kasc オプション対応**。
  パネルに「Layers」タブを新設し、レイヤごとの .kasc オプションを
  テーブルで設定できる(値はレイヤ customProperty へ保存、
  エクスポート時に `| key=value` として出力):
  `site`=グループ名(グレー表示=グループ名の自動値・`-` で強制未割当)/
  `order`=グループ内順位/`list`=一覧非表示(list=off)/`opts`=任意の追加
  key=value。タブ冒頭の「Custom layers tab」チェック
  (QSettings `kasugai_site_control`)ON でレイヤツリーのグループ名を
  `site=<グループ>` として一括付与し、`site=` 付きレイヤがあれば
  `plugin: custom-layer | name=レイヤ | url=canvas_data/custom-layer.js | before=layers-panel`
  行と同梱プラグインJS(`assets/custom-layer.js` → `canvas_data/` 複製)
  を出力する(customProperty 個別指定でも site= が出ればプラグイン行
  は出る)。Canvas 側では site= は custom-layer タブ(表示名
  「レイヤ」)専用の集約キーで標準レイヤタブには全レイヤが表示され
  (list=off のみ標準一覧から隠れる。タブ名が重複するため組み込み
  側は「システムレイヤ」に自動改称される)、custom-layer タブで
  グループごとの一括 on/off とメンバー凡例の表示・シンボル別
  on/off ができる(url= プロジェクト相対のため CDN/静的ホスト・
  全エンジンで動作)。`kasugaiExport` に `site_control` 引数を追加
  (既定=QSettings 参照)
- **「▶ Canvas」ボタンが毎回再エクスポートするよう変更**。
  従来は既存の出力物をそのまま登録・表示するだけだったが、
  押すたびに最新のレイヤ状態(名称・可視・customProperty
  オプション)が Canvas に反映されるようになった

## 4.27.0

- **パネル「Web」タブ化**。最上段にあった「Web配信(サーバレス)」
  (`groupBox_webdist`)と「HTTPサーバー」(`groupBox_server`)の
  2グループを、既存タブ(テーマ/パーマリンク/共有)の先頭へ追加した
  「Web」タブ内へ移動し、既定表示タブに変更。パネル全体が
  タブウィジェットに統一され、起動時はメイン機能の Web タブが開く。
  説明ラベルは短文へ簡略化し、Expanding 化+右側スペーサー撤去で
  行幅いっぱいに表示(従来は Preferred ラベルが Expanding スペーサーに
  押されて画面途中で早めに折り返されていた)。ボタン行を
  「エクスポート | ZIP」「出力先パス | ↺ | 📁」の2行へ整理
  (ZIP は CDN 行からエクスポート行へ移動)。「Admin」ボタンは
  稼働中の Canvas アプリ(8510)検出時のみ有効化し、未稼働時は
  グレーアウト(「▶ Canvas」はインストール済み exe を自動起動
  できるため従来どおり常時有効。起動直後に Admin の有効化を
  再判定)。管理画面が無い旧 Canvas(7.1.0 以前=V8 未収録)では
  /admin/ が 404 になるため、HEAD 事前確認で 404 ページを開かず
  「Canvas を更新」の通知を出す。エンジン行は「エンジン選択 | ▶ WebView」に絞り、
  「▶ Canvas | Admin」は次行へ移動。i18n カタログ9言語に
  "Web" と新説明文を追加(旧長文キーは削除)

## 4.26.2

- **plugins.qgis.org セキュリティスキャン指摘対応**(4.26.1 がサイト
  スキャンでブロックされた原因の修正)。全て `reearth_cms.py`:
  - B105×2: `ENV_TOKEN`/`SKEY_TOKEN` は環境変数名・QSettingsキー名
    という文字列定数であり秘密値ではないため `# nosec B105` で明示
  - B310: CMS API 呼出し url に `http`/`https` スキーム検証を追加し
    `urllib.request.urlopen` へ `# nosec B310` を明示
  - B110×2: QGIS 外 import 失敗時フォールバックの `except: pass`
    2 箇所へ `# nosec B110` を明示

## 4.26.1


- **QGIS クラッシュ修正(スレッドセーフティ)**。
  `GET /live/state`・`GET /present/state` がワーカースレッド上で
  `iface.mapCanvas().mapSettings()` 等の GUI オブジェクトへ直接アクセスし、
  ポーリング時に access violation で QGIS 本体がクラッシュする問題を修正。
  `_canvas_state_dict()` の呼出しを既存の `_main_invoker.call()`
  (GUI スレッド同期実行)経由に変更

## 4.26.0

- **エクスポート進捗表示(件数ベース)**。
  `export_kasugai_project` / bridge `kasugaiExport` に
  `progress_cb(done, total, name)` を追加し、レイヤツリー走査の
  各レイヤ処理開始時に「何件目/全何件・対象名」を通知
  (全件完了時は `(total, total, '')`)。パネルのエクスポート/
  起動ボタンでは QProgressDialog に「レイヤーを変換中 N/M: 名前」
  とバーをリアルタイム表示し、Cancel で `ExportCancelled` による
  中断も可能。`GET /kasugai` 経路は GUI を持たないため
  QgsMessageLog へ同形式の進捗を記録する

## 4.25.1

- **ヘルプ「?」ボタンの遷移先を GitHub Pages 化**。
  Web配信グループの「?」が開く URL を GitHub ツリー
  (`github.com/.../tree/master/qgis-plugin/geo_webview/docs`)から
  GitHub Pages のドキュメントサイト
  (`yamamoto-ryuzo.github.io/qgis_live_harness/qgis-plugin/geo_webview/docs/`)
  へ変更。index.html+左サイドバーナビ付きの整形済みページが
  そのまま開く

## 4.25.0

- **「表示中のみ変換」チェックをパネル/設定ダイアログに追加**。
  Web配信グループの Format 行の下に `Visible data only (faster)`
  チェックを追加し、設定ダイアログの Vector Export Format 内にも
  同名チェックを配置。QSettings `kasugai_visible_data_only`
  (初期値 ON)で両者を同期し、v4.23.0 の非表示レイヤ出力省略を
  GUI から切替できる。OFF にすると非表示レイヤも `| off` 行として
  従来通り全データを変換・複製する(プロジェクト丸ごと引越し用途)。
  `export_kasugai_project` / bridge `kasugaiExport` の
  `visible_data_only` 既定値を `None`(=設定値に従う)に変更し、
  明示指定は引き続き当該エクスポートのみ上書きとして機能する

## 4.24.0

- **KASUGAI Canvas UI 設定管理画面への入口をパネルに追加**。
  「Admin」ボタンからブラウザで `web/admin/ui-config-admin.html`
  (ローカルアプリ専用・既定 port 8510・CDN 非配信)を開き、
  エンジン別の UI 表示/非表示・コントロール初期値・起動タブを
  設定できる。Canvas サーバ未稼働時は通知して開かない。
  bridge `openKasugaiAdmin` からも同じ操作を呼べる(AI 制御対応)

## 4.23.0

- **非表示レイヤを .kasc に出力しない高速化**。
  `export_kasugai_project` / bridge `kasugaiExport` に
  `visible_data_only`(既定 ON)を追加。`| off` で出力される
  非表示レイヤ(`hidden_as_off=True` またはマップテーマ存在時)は
  レイヤ行を一切出力せず `skipped` へ記録する。
  Canvas のレイヤ一覧に読み込めない「未読込」エントリが残らず、
  データ変換・canvas_data/ へのコピー・スタイル書き出しの
  コストも掛からない。背景図グループ内の XYZ タイルなど
  `base:` 候補のみ従来通り `| off` 付きで出力する。
  `visible_data_only=False` で非表示レイヤも `| off` 行として
  全データを変換・複製する従来動作(プロジェクト丸ごと引越し用)
  に戻せる。
  あわせて `theme:` 行は .kasc に実際に出力されたレイヤのみを対象に
  するよう修正(出力対象外レイヤへの無効な参照を防ぐ)

## 4.22.0

- **Qt6 クラッシュ対策: ボタンイベント内の重い同期処理と messageBar 通知を次イベントループへ遅延**。
  `clicked` は `QAbstractButton::mouseReleaseEvent` 内で発火するため、
  「Export」「ZIP」「▶ Canvas」「▶ WebView」が行う同期エクスポート+
  `pushMessage`(QgsMessageBarItem 生成時のスタイルシート/アイコン解決)
  がイベント処理中に走り、Qt6 環境でアクセス違反を起こすことがあった。
  該当ボタンのハンドラを `QTimer.singleShot(0)` で次ティックへ送り、
  全 `pushMessage` 呼出し(40箇所)を `_push_message` ラッパー経由の
  遅延通知へ置き換え(QGIS 本体の Qt6 イベントハンドラ対策と同じ
  キューイング方針)。ラッパーは context=mainWindow 付き
  `singleShot` で呼出しスレッドに関わらず GUI スレッド実行を保証し、
  非対応環境では無 context `singleShot`→従来の即時通知へ順に退避する
- **修正: `image:` 行のタイトルが `{0}` リテラルのまま出力される不具合**。
  ラスタ PNG 焼き込み(baked)行の `.format` が末尾文字列にのみ
  適用されており、`.kasc` の image: 行タイトルが `{0}` になっていた
- **ベクター出力形式に `geojson`(WEB連携)モードを追加**。`native`/
  `recommended` に続く第3モードとして、全ベクター(FlatGeobuf/GeoParquet
  ソース・WFS/メモリ等を含む)を GeoJSON(EPSG:4326) へ変換し
  `canvas_data/` へ `geojson:` 行として配置する。`canvas_data/` が
  オープン標準の GeoJSON のみになるため KASUGAI Canvas 以外の
  WebGIS・GIS ツールでもそのまま読み込める相互運用向けモード。
  切替経路は既存と同じ4系統(パネル Format コンボ・設定ダイアログ
  Vector Export Format・`GET /kasugai?fmt=geojson`・bridge
  `kasugaiExport(vector_format='geojson')`、永続キーは共通の
  `kasugai_vector_format`)。GEOJSON 固定出力のため FlatGeobuf→
  Parquet のドライバフォールバックは使わない。
  UI ラベル `geojson (WEB interop → GeoJSON)`・ツールチップ・
  設定ダイアログの3モード説明文を i18n 9言語カタログへ登録し、
  SPEC.md・docs/spec.html・skills/webgis-convert.md・panel_base.ui を
  3モード記述へ同期(kasugai_canvas 側 docs/data-recommend.html の
  WEB連携ルートも「予定」から実装済みへ更新)
- **出力データフォルダを `canvas_data/` に統一**。従来 `link_files` の値で
  分かれていた出力先（`link_files=False` のサーバレス配布=`DATA/`、
  `link_files=True` の複写なしWeb化=`canvas_data/`）を、両モード共通で
  `canvas_data/` へ一本化。KASUGAI Canvas 本体のプロジェクト構造
  `projects/<id>/canvas_data/` とも一致するようになった。
  `.kasc` 内のデータ参照は `canvas_data/...` で出力され、旧 `DATA/` 構成の
  プロジェクトは Canvas 側（`/api/files`・参照解決・納品ローカル化）が
  後方互換で読む。あわせて SPEC.md・docs/・i18n・スキル・panel_base.ui・
  metadata.txt・verify 資産の `DATA/` 表記を `canvas_data/` へ同期
- ドキュメント修正: ネイティブ参照できないベクターの変換先は 4.17.0 以降
  **FlatGeobuf(EPSG:4326・空間インデックス付き) が第1候補**(非搭載時 Parquet、
  失敗時 GeoJSON フォールバック)だが、`docs/spec.html`/`SPEC.md` の
  .kasc 行生成規則表・`docs/technical.html`・bridge `kasugaiExport` docstring が
  旧「GeoJSON 変換」記述のままだったのを実装へ整合。
  `skills/webgis-convert.md` の where-eval 非対応時の回り先も同様に修正。
  あわせて `kasugai_export.py` の `_native_ref` docstring・関連コメントの
  「GeoJSON 再エクスポート/変換」表記をフォールバック変換の実態へ揃えた
  (kasugai_canvas 側 `docs/data-recommend.html` の WEBVIEW連携図も同期修正)

## 4.21.0

- **`embed_gpkg_style` を廃止しスタイル配布を .qml+`style=` の1系統に統一**。
  GPKG の `layer_styles` テーブルへ既定スタイルを書き込む
  opt-in 経路(元 .gpkg ファイルを更新する副作用があった)を
  `export_kasugai_project`・bridge `kasugaiExport` の引数ごと撤去
  (`_native_ref` の embed_style 引数・`_embed_gpkg_style` 関数も削除)。
  スタイルは全データ形式で `DATA/<slug>.qml`+`| style=` に一本化。
  既存コードで embed_gpkg_style を指定していた呼出しは引数削除に注意
- **パネルにベクター出力形式の直接切替を追加**。Web Distribution
  グループの Export 行の下に **Format:** コンボ
  (`comboBox_vector_format`)を新設し、
  `native (reference as-is)` / `recommended (FlatGeobuf → DATA/)`
  をドロップダウンで即切替できるようにした。
  設定ダイアログの Vector Export Format と同じ
  `kasugai_vector_format` を読み書きするため双方向に同期する
  (4.20.0 で追加した推奨形式スイッチの第4の切替経路)。
  選択は `on_vector_format_changed` →
  `kasugai_export.set_vector_export_mode()` で即保存され、
  Export ボタン・`/kasugai`(fmt 未指定時)・bridge の全経路に効く
- あわせて 4.20.0 で未登録だった設定ダイアログの
  Vector Export Format 関連文字列を i18n カタログ(9言語)へ登録
- `docs/spec.html`/`SPEC.md` に「ベクター出力形式(native/recommended)」
  「.qml スタイル出力」の2節を追加。推奨形式スイッチの4切替経路・
  永続/一時上書きの違い、.qml がデータ形式と独立に全モードで
  `| style=DATA/x.qml` 付きで出力される仕様を明文化


## 4.20.0

- **ベクター出力の「推奨形式スイッチ」(vector_format)を追加**。
  エクスポート全体を「推奨形式へ変換して DATA/ へ配置」するモードを
  3経路で切替可能にした
  - 設定ダイアログ新設 **Vector Export Format** グループ
    (`kasugai_vector_format`、ON/OFF の変換ルールを併記表示)
  - `GET /kasugai?fmt=recommended|native`
    （応答 JSON に `vector_format` を含む）
  - bridge `kasugaiExport(vector_format='recommended')`
  - **ON(recommended)**: gpkg/geojson/shp/csv/kml/wfs 等のソースを
    すべて FlatGeobuf へ EPSG:4326 で変換し DATA/ へ配置
    (`flatgeobuf:` 行。Canvas では `bbox=auto` の空間インデックス
    +Range 範囲読みが効く)。既に FlatGeobuf/GeoParquet のソースは
    `flatgeobuf:`/`geoparquet:`/`duckdb:+format=parquet` 参照を維持。
    subsetString・fields/where/limit は変換データへ焼き込み
  - **OFF(native・既定)**: 従来どおり読めるソースはそのまま参照
  - `export_kasugai_project` に `vector_format` 引数を追加
    (None は QSettings 解決)。`verify/features.json` に5件登録
- `skills/webgis-convert.md` に推奨形式スイッチの切替経路と
  変換ルールを追記


## 4.19.2

- `kascImport` の `bbox=` 判定を修正。`bbox=auto`/`bbox=off` 等の
  表示範囲連動クエリ指定(`gpkg:`/`duckdb:`/`flatgeobuf:`)を描画範囲制限
  の4数値として誤解して警告を出していたのを、モード値として除外するよう修正
  （Canvas 側で `flatgeobuf:` に `bbox=auto` 既定 ON の空間インデックス
  +Range 範囲読みが追加されたことへの同期）
- `skills/webgis-convert.md` の FlatGeobuf 行を更新:
  `bbox=auto` 既定 ON（表示範囲のみ部分読み）・`bbox=off` で全件、
  索引なし・Range 非対応サーバーは全件へフォールバックを明記


## 4.19.1

- `kascInspect`/`kascImport` の Canvas 専用オプション未適用報告を拡充。
  Canvas 側(CesiumJS 監査対応)で追加された `3dtiles:` の
  `tilestyle`/`tilecolor`/`tileshow`/`tilepointsize`/`sse`/`edl`、
  ベクター行の `scaledist`/`transldist`/`pixoffdist`/`splitdir`/
  `strot`/`subregion`、`wms:` の `infoformat` を、
  QGIS へ未適用のまま警告列挙する対象へ追加

## 4.19.0

- **QML 内ユーザー関数を組込み式へ自動展開**して出力。
  geo_userfunc 側で `@qgsfunction` 関数の docstring に
  `@expr: <式テンプレート>` を宣言すると、`saveNamedStyle` /
  テーマスタイル(`xmlData`)で出力した `.qml` を後処理し、
  DD `expression`・ルール `filter`・ラベル `fieldName`
  (isExpression)・`geometryModifier`・`weight_expression` 内の
  呼出しを `QgsExpression` ノードスパン単位で宣言式へ書き換える。
  配布 `.kasc`+`DATA/` が Canvas の関数実装なしに自己完結する
  （宣言の無い関数は従来通り残り、Canvas 側で警告+フォールバック）
  - 第一号: `line_width(0.2,0.08,15000,@map_scale)` →
    `clamp(0.08, 0.2*15000/@map_scale, 0.2)`
  - bridge `geo_userfunc.expansions()` で展開テーブルを取得

## 4.18.0

- **`.kasc` をプロジェクトファイル隣へ出力する「複写なし Web化」
  (link_files) を既定化**。`export_kasugai_project` に
  `link_files=True`(既定)を追加:
  - 出力先の優先順位: 明示 out_dir > QSettings
    ``kasugai_output_path`` > (link 時)プロジェクトファイル
    (.qgs/.qgz)のフォルダ > 既定出力先。保存済みプロジェクトは
    ``<プロジェクトdir>/kasugai_canvas.kasc`` に直接出力
  - 参照可能なデータは**原本を複写せず相対パスで参照**:
    プロジェクトdir配下は ``near.geojson`` 形式、1階層上
    (ワークスペース)は ``../up.gpkg`` 形式(Canvas サーバの外部
    プロジェクト @parent 解決で配信)。Shapefile/3D Tiles/ローカル
    XYZ ツリーも原本の場所をそのまま参照
  - 相対化できないファイル(2階層以上上・別ドライブ)と変換が必要な
    データのみ ``canvas_data/`` サブフォルダへ出力(従来の DATA/ の
    代替)。.qml スタイルも canvas_data/ へ
  - link 時のエンジン起動HTML(emit_launchers)は既定 OFF
    (サーバレス配布用途のみ・明示 True で生成可)
  - ``link_files=False`` で従来互換(out_dir/DATA/ へ全複写)
  - `existing_export` はプロジェクト隣接 .kasc も探索
  - bridge ``kasugaiExport`` に ``link_files`` 引数を追加
  - Canvas 側 `shared/kasc.js` も対応: 外部プロジェクトの ``..``
    参照を ``@parent`` へ変換し Cesium 以外のエンジンでも
    プロジェクト外の原本参照を配信できるようにした

## 4.17.0

- **`.kasc` ネイティブ参照の形式拡大＋フォールバック変換先を
  FlatGeobuf へ変更**。Canvas 対応形式(ogrsql: 行まで)を
  `_native_ref` が直接参照するよう拡張:
  - 新規ネイティブ参照: `.kml`/`.kmz`(`kml:`)、`.gpx`(`gpx:`)、
    `.topojson`(`.json`/`topojson=`)、`.czml`、`.igc`、
    `.gml`、`.zip`(Shapefile ZIP→`shp:`)、`.sqlite`/`db`/`mdb`→`ogrsql:`
  - Shapefile: `.shp` 指定時は `.dbf`/`.shx`/`.prj` 等の
    sidecar 一式を DATA/ へ複製して `shp:` 行を出力
  - QGIS `WFS` プロバイダレイヤ → `wfs:` 行(URL+typename を
    プロバイダ URI から再構成、version=2.0.0 既定)
  - リモート http(s)/vsicurl も同形式を直参照
  - `_export_geojson` → `_export_vector` に汎用化し、
    フォールバック変換先を FlatGeobuf(空間インデックス付き・
    GeoJSON より軽量・全エンジン対応)を第1候補へ変更。
    ドライバ非搭載/失敗時は Parquet→GeoJSON の順でフォールバック。
    `fields`/`where`/`limit` の焼き込みも同じ経路で行う
  - `kasc_import.py` も新行タイプ(`gpx`/`topojson`/`czml`/`esrijson`/
    `geojsonl`/`wkt`/`wkb`/`igc`/`polyline`/`gml` 等)をパース対象に追加
    (ogr で読めるものは QGIS レイヤ化、読めないものは skipped 報告)

## 4.16.0

- **`.kasc` エクスポートの属性フィールド選択・行フィルタ・地物数上限**
  (Issue #14)。bridge `kasugaiExport` と
  `export_kasugai_project` に `fields`/`where`/`limit` 引数を追加。
  いずれも全レイヤ共通値、または `{レイヤ名 or レイヤID: 値}` の
  レイヤ毎 dict を受け付ける(QGIS「ベクタレイヤを保存」ダイアログの
  フィールド選択、ogr2ogr の `-select`/`-where`/`-limit` 相当)。
  - `fields`: 出力する属性列名のリスト(カンマ区切り文字列も可)。
    `DATA/*.geojson` の properties が選択列のみになる。
    存在しない列名はそのレイヤを errors へ記録して除外
  - `where`: QgsExpression 式で出力地物を絞る。レイヤの
    プロバイダフィルタ(subsetString)とは AND 適用。
    式のパースエラーは errors へ記録してそのレイヤを除外
  - `limit`: レイヤ毎の出力地物数上限(1以上の整数。
    大容量レイヤの配信サイズ制御用)
  - いずれかを指定したベクターレイヤはネイティブ参照
    (`gpkg:`/`geojson:` 等)を使わず、QgsFeatureRequest+materialize で
    条件適用済みの地物を GeoJSON 変換で焼き込む。どのソース形式でも
    フィルタが出力データへ確実に反映される
    (.kasc 行形式・Canvas 側の変更は不要)
  - `layers` 結果の各レイヤ辞書に `filter` キーで適用条件を返す

## 4.15.0

- **Re:Earth CMS 連携を追加**(`reearth_cms.py` 新設、Issue #11)。
  Integration API(`https://api.cms.reearth.io/api`)を使い、
  ベクタレイヤを CMS アイテムとして登録(Phase 1)し、
  `.kasc`+`DATA/` 出力物を ZIP 化して CMS アセットとして
  アップロード・公開(Phase 2、assets.cms.reearth.io 公開URL取得)できる。
  bridge メソッド: `cmsStatus`/`cmsSettings`/`cmsSchema`/
  `cmsRegisterLayer`(属性→フィールドkey マッピングは同名自動対応＋
  dict 指定。`geometry_key` で地物ジオメトリを EPSG:4326 GeoJSON
  geometry として格納、`publish` で即公開)/`cmsUploadKasc`。
  インテグレーショントークンは環境変数 `REEARTH_CMS_TOKEN` 優先、
  未設定時は QSettings `reearth_cms_token`。bridge はトークン値を
  返さない(リポジトリへのコミット禁止)。読み取り側(CMSアイテムの
  レイヤ読み込み等)は kasugai_canvas#132 が担う
- **`ogrsql:` 行タイプの取り込みに対応**(`kasc_import.py`)。
  Canvas 側で新設された OGR SQL SELECT 行(`ogrsql:タイトル|SELECT ...`)を
  QGIS 側でもネイティブに復元する。`ogr.ExecuteSQL(dialect="OGRSQL")` を
  QGIS 内の GDAL で直接実行し、結果を memory プロバイダのベクターレイヤー
  として追加する。FROM 参照は QGIS プロジェクトレイヤー(表示名/レイヤーID)・
  `'ds'.'layer'` 形式・DATA/ 相対パス・http(s) URL(/vsicurl/)を解決し、
  クエリ末尾の Canvas オプション(`| off`/`| attr=`/`| render=` 等)は
  実行前に除去する。QGIS4 の `QgsGeometry().fromWkb`(インスタンスメソッド)・
  `ogr.Open`(OpenEx 非対応)に準拠
- **`where=` を「行の最終オプション・値は改行まで」の厳格規約へ変更**。
  式中に `|`(`||` 連結・`'a|b'` リテラル等)を含む subsetString も
  そのまま `where=` へ出力できるようになった(従来は `|` 含有で
  GeoJSON 変換へ逃がしていた)。`off` や他の `key=value` は
  `where=` より前に置く。`view:` の `;where=` は対象外(値に `|` 不可)。
  where-eval.js(クライアント評価)は `||` 文字列連結に対応済みのため
  `||` 含む式も `geojson:`/`flatgeobuf:`/`geoparquet:` でそのまま送出する
  (単独 `|` のビット演算・`%` 剰余は非対応のまま GeoJSON 焼き込み。
  `gpkg:`/`duckdb:` は SQL 評価でいずれもそのまま渡る)。
  書き出し順も `where=` を必ず行末に出すよう整理した
  (kasc_import.py 側も行末規約で `|` 含む式を復元)
- レイヤーフィルタ(subsetString)の `where=` 送出を全ネイティブ形式へ拡大。
  従来 `gpkg:`/`duckdb:` 系のみだった `where=` を
  `geojson:`/`flatgeobuf:`/`geoparquet:`(URL)行にも発行する
  (Canvas 側 shared/where-eval.js の OGR SQL WHERE句準拠クライアント
  評価。ローカル/URL・GeoJSON/FGB を含む全分岐で統一)。
  where-eval が解釈できない式(サブクエリ・未対応関数・QGIS式記法)は
  従来通り GeoJSON 変換でフィルタを地物へ焼き込む。
  ローカル Parquet は従来通り `duckdb:+format=parquet+where=` で SQL 評価
- kasc_import.py のメタ行タイプに `view:`/`html:`/`portal:`/`link:` を追加。
  `portal: … | html=ファイル/URL` のポータル全体HTML指定と
  HTML内 `data-view=`/`data-link=`/`data-cam=`/`data-base=`/`data-clear`/`data-close` の
  GIS操作属性も Canvas 側で実装済み(全エンジン共通の shared/portal.js で動作)
  Canvas 側の新行形式(ポータル開始画面・目的別ビューカード)を
  .kasc 逆取り込み時にレイヤ行と誤認しないよう読み飛ばし対象へ登録
- `skills/webgis-convert.md` を追加(geo_driver から移動)。
  geo_driver の同梱指示書集約がプラグイン別 `skills/` 対応になったため、
  KASUGAI Canvas 向け変換・kasugaiExport の手順書は本プラグインの責務として同梱する

## 4.14.0

- **`.kasc` 逆取り込み機能を追加**(kasc_import.py + bridge
  `kascInspect`/`kascImport`)。`kasugaiExport` の逆方向として、
  `.kasc+DATA/`(ローカルパスまたは http(s) URL)を QGIS プロジェクトへ
  再構成する。`xyz:`/`base:`→XYZラスタ、`wms:`/`wmts:`→WMSラスタ、
  `geojson:`/`gpkg:`/`geoparquet:`/`flatgeobuf:`/`shp:`/`kml:`→
  ベクター(ogr)、`duckdb:`/`csv:`/`tsv:`→delimitedtext(ローカル)または
  ogr、`mvt:`/`pmtiles:`→ベクタータイル、`3dtiles:`→TiledScene、
  `geotiff:`/`image:`→ラスタ、`fly_geojson:`→ベクター。
  `style=`(.qml・リモートは一時DL)・`minScale=`/`maxScale=`・
  `opacity=`・`where=`→subsetString・`attr=`/`出典`→attribution・
  タイトルの `/` → レイヤツリーグループ(`//` は排他グループ)・
  `| off`・`group:` 折りたたみ・`theme:` → マップテーマ・
  `bookmark:` → bookmarks.xml インポート・`cam:` → キャンバス
  中心/縮尺(送出側近似式 h=scale*0.2 の逆算)/回転を復元する。
  `bbox=` は Canvas の描画範囲制限として、
  setMapClippingRegion のあるQGIS系ではクリッピング領域、
  無い系(QGIS4)ではラスタの setExtent(レイヤCRSへ変換した矩形)
  へフォールバック適用する(ベクターは未対応として警告)。
  theme: のレイヤ照合は NFKC 正規化+リーフ名でも行い、
  空テーマは `レイヤ指定なし` と区別して警告する。
  `kascInspect` はプロジェクトを変更しない dry run(集計+参照解決)。
  応答は `added`/`skipped`(理由付き)/`warnings`(Canvas専用オプション=
  extrude/time等の未適用を列挙)を返す。既存 WebGIS → QGIS →
  再エクスポートの変換パイプラインの往路として、AIスキル
  `webgis-import` から呼ばれる想定
- `kascImport` に **`replace` オプション**(既定 False)を追加。
  取込レイヤへ `kasc_source` カスタムプロパティ(正規化した
  source キー)を付与し、replace=True では同キーの前回取込
  レイヤと取込専用に作成した空グループを除去してから取り込む
  冪等モード(応答 `replaced` に除去数)。同じ .kasc の
  再取り込みで重複しない
- **同梱 AI スキルを `skills/` に配置**(geo_driver の集約拡張で
  `qgis-plugin/<id>/skills/*.md` が全プラグインから読めるようになった
  ため責務プラグイン側へ移設): `skills/webgis-convert.md`
  (geo_driver から移動・Canvas 向け形式変換の手順書)と
  `skills/webgis-import.md`(新規・既存 WebGIS/.kasc の QGIS 取り込み
  手順書。`kascInspect`/`kascImport` と汎用 Web ソースの
  pyeval レシピを記載)の2本

## 4.13.1

- 個別利用時にGeoSuiteツールバーが表示されない不具合を修正。
  `_geo_toolbar()` に `ensure_visible` 引数を追加し、項目追加経路では
  ツールバーの可視状態を保証するようにした(ドライバ非稼働の個別利用では
  表示を強制する経路が無く、保存済みウィンドウ状態等でツールバーが
  非表示のままになり得た)。unload時のremoveAction経路は従来通り
  表示状態を変更しない

## 4.13.0

- Navara エンジン対応: KASUGAI Canvas の `navara` エンジン
  (`web/navara/`、.kasc 再生対応済み)を起動エンジンとして選択可能にした。
  `VALID_ENGINES`/`_LAUNCHER_ENGINES`・パネルの Engine コンボ・
  エンジン起動 HTML(`navara.html`・index.html のリンク一覧)・
  bridge `openExternal("navara")`・`/kasugai?engine=navara` が利用可能。
- metadata.txt の `tags` に `navara`/`gsimap`/`leaflet` を追加
  (plugins.qgis.org のタグ一覧を Canvas エンジン一式に合わせた)。
- パネル説明文・README/SPEC のエンジン列挙に Navara を追記
  (i18n 9言語カタログも同期)。

## 4.12.4

- plugins.qgis.org セキュリティスキャン対応: `except ... continue` 6箇所
  (kasugai_export.py 1箇所・server_manager.py 5箇所)のインライン抑制が
  `# nosec B110`(try/except/pass 用のID)になっており B112
  (try/except/continue)が抑制されず、4.12.3 がサイトスキャンで
  ブロックされていた問題を修正(`# nosec B112` へ訂正)。
- QGIS core から撤去され認識されなくなった非推奨フラグ `supportsQt6` を
  metadata.txt から削除(アップロード時の deprecation 警告対応。
  QGIS4 対応判定は qgisMinimumVersion/qgisMaximumVersion の範囲で行われる)。

## 4.12.3

- 公開前の実機動作確認で発見した不具合を修正: `_tree_layers()` が
  4.12.2 で 4 要素タプル `(layer, groups, visible, node)` を返すように
  なった際、更新漏れした 3 要素アンパック 6 箇所
  (kasugai_export の base:XYZ 検出・theme: 行生成 2 箇所、
  live_sync のタイトル写像、server_manager の writeback 解決・
  タイトル写像)により `kasugaiExport` が
  "too many values to unpack (expected 3)" で失敗していた問題を修正。
  あわせて kasugai_export.py の既存 flake8 E306 指摘を解消。


## 4.12.2

- QGIS レイヤツリーの凡例ノード順・ユーザーラベル・凡例表示名を
  `legendnode:` メタ行として出力し、グループの checked/unchecked/partial
  (中間)状態を `group:` 行の `checked=` オプションで出力するようにした(#63)。


## 4.12.1

- mvt:/pmtiles: 行タイプに対応した Canvas 向けに、QgsVectorTileLayer の
  XYZ テンプレート/TileJSON/PMTiles URL を mvt:/pmtiles: 行として出力するようにした
  (ローカル .mbtiles 等 URL 参照できないものは従来どおり理由付き skipped)。
  併せて未対応レイヤ種別の skipped 理由表記を整理済み(#50 方針)。


このファイルでは geo_webview プラグインの主な変更点を記録します。

記法は [Keep a Changelog](https://keepachangelog.com/ja/1.0.0/) に基づき、
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) に準拠します。

## バージョン形式: VA.B.C

- **A**: QGIS コア更新やプラグインアーキテクチャ大幅変更などのメジャー変更
- **B**: UI 変更・新機能追加・中規模な機能拡張
- **C**: 軽微な不具合修正・小改善・プロファイル/プラグインの微修正

## [4.12.0] - 2026-11-08

### Added

- **Live Driver MCP リレー(CDN ホスト版 AI チャット向け)**: 新エンドポイント
  `GET /live/mcp-discover`・`POST /live/mcp`(`live_mcp.py`)。
  KASUGAI Canvas の AI チャットはローカルアプリ(:8510)では
  `/api/qgis-live/mcp` リレー経由で Live Driver の MCP ツール
  (`qgis_pyeval`/`qgis_bridge_call`/`qgis_screenshot` 等)を使えるが、
  CDN ホスト版には相当するバックエンドが無かった。geo_webview の
  内蔵サーバは既に CORS + Private Network Access 対応済みのため、
  その経路に Live Driver `/mcp` へのリレーを載せて CDN からも
  同じツール群(Processing 解析・他プラグインの bridge_call 含む)へ
  到達できるようにした。
  - `GET /live/mcp-discover`: `~/.qgis-live/` レジストリを走査して
    稼働中セッションを検出し、ブラウザが登録すべきリレー URL
    (このサーバ自身の `/live/mcp`)を返す。トークンは返さない
  - `POST /live/mcp`: 検出したセッションの `/mcp` へ JSON-RPC を
    転送。トークンはレジストリから読みサーバ側で付与する
    (ブラウザは持たない)。セッション解決は毎回行うため QGIS 再起動で
    ポート・トークンが変わっても自動追随。`Mcp-Session-Id` を往復伝播
  - セキュリティ: `pyeval`=任意コード実行が乗るため **TCP ピアが
    loopback の接続のみ許可**(他の `/live/*` より露出が大きい)。
    ブラウザ発は既存 CORS 許可リストで制限され、応答ヘッダに
    `Access-Control-Expose-Headers: Mcp-Session-Id` を追加して
    セッション ID を JS から読めるようにした

## [4.11.0] - 2026-11-08

### Added

- **ライブ連携 逆方向オーサリング(.kasc → QGIS 書き戻し)**: 新エンドポイント
  `POST /live/writeback`。Canvas インスペクタでの表示/テーマ/フィルタ変更を
  `{layers:[{title,visible,where?}], theme?}` として受け取り、
  QGIS プロジェクトへ反映する。
  - `visible` → レイヤツリーのチェック状態(表示時は祖先グループもON)
  - `where` → ベクターレイヤの subsetString(空文字=解除)
  - `theme` → 同名マップテーマがあれば可視性+記録済みスタイルを一括適用
  - 適用中は `LiveSyncController.suppress()` で変更検出を抑止し、
    Canvas 由来の編集が再エクスポートとして Canvas へ往復しないようにした
- **ライブ連携 地物投入(Canvas → QGIS)**: 新エンドポイント
  `POST /live/features`。`{name, geojson, replace?}` の
  GeoJSON(FeatureCollection|Feature[])をスクラッチ(memory)レイヤとして
  プロジェクトへ投入する。ジオメトリ型混在は型ごとに分割、属性は
  `QgsJsonUtils` でフィールド化し、レイヤツリー先頭の「Canvas」
  グループへ追加。`kasugai_live_name` カスタムプロパティで同名再送を
  置換(既定 replace=true)。投入は通常のプロジェクト変更として
  live sync の差分エクスポートで Canvas へ往復する
- **bridge 新メソッド**: `liveWriteback(payload)` /
  `liveAddFeatures(name, geojson, replace)` —
  上記と同じ適用ロジックを bridge_call / MCP から実行可能
- **QGIS → Canvas 選択同期**: レイヤの selectionChanged を監視し
  `{layers:[{layer,ids,count}],rev}` を `_live.qgis_selection` 経由で
  `GET /live/state` に公開 + 稼働中 Canvas へ liveSync プッシュ
- **オンデマンド配信 API**:
  - `GET /live/layers` — kasc タイトル付きレイヤカタログ
  - `GET /live/features?layer=&bbox=&pt=&tol=&limit=&offset=` —
    範囲/地点指定の地物配信(GeoJSON+`_display`)
  - `GET /live/selection` — QGIS 側選択地物の GeoJSON
  - `GET /live/render?bbox=&w=&h=&layers=&bg=transparent` —
    EPSG:4326 範囲のマップ描画PNG(Canvas「QGIS描画」フォールバック用)

## [4.10.0] - 2026-11-07

### Added

- **QGIS4 3Dグローブビュー対応**: `<mapViewDocks3D>` のグローブビュー
  (シーンCRSが地心系 = `project.crs().toGeocentricCrs()`、
  通常 EPSG:4978)を正しく出力するようになった。
  - ビューごとの `<qgis3d><crs>` を読んでシーンCRSを解決
    (従来は常に `project.crs()` で変換していたため、シーンCRSと
    プロジェクトCRSが異なる場合に位置がずれていた)。
    地心系は `QgsCoordinateReferenceSystem.type()==Geocentric` で
    判定し、注視点の ECEF 座標を測地座標へ変換してカメラ位置を
    求める(非WGS84の地心系は EPSG:4979 経由)
  - グローブビューは `scene3d:` 行へ `globe=on` を付与
- **3Dアニメーション → FLYルート出力**: 3Dビューの
  `<animation3d>` キーフレーム(注視点+dist/pitch/yaw+時刻)から
  各時刻のカメラ位置を計算し、カメラ軌道を
  `fly_geojson:` 行 + `DATA/anim3d_<slug>.geojson` として出力。
  speed はカメラ軌道の3D総延長÷アニメーション時間(m/s)、
  `properties.fly` に speed/step/view=camera、`properties` に
  `source="qgis3dAnimation"`・`keyframes`・`duration` を埋め込む
  (キーフレーム2個未満は出力しない)

### Fixed

- **3Dビューのカメラ姿勢変換を QgsCameraPose 準拠へ修正**:
  QGIS ソース(`QgsCameraPose::updateCamera`/`updateCameraGlobe`・
  `rotationFromPitchHeadingAngles`)からカメラ位置を再導出し、
  従来の変換が高さと水平距離を入れ替えて出力していた問題を修正。
  - 正: 高さ=`dist·cos(pitch)`、水平距離=`dist·sin(pitch)`、
    カメラは注視点の方位 `(180−yaw)`° に位置
    (QGIS yaw は反時計回り正方向のため視線方位は `360−yaw`)
  - 出力 `p=` を QGIS pitch(0=真俯瞰・90=水平)から
    Cesium pitch(`pitch−90`)へ変換(従来の `p=−pitch` では
    俯瞰ビューが水平視点になっていた)
  - `zMap`(注視点の高さ)をカメラ高へ加算(従来は無視)

## [4.9.0] - 2026-11-07

### Added

- **ライブ双方向連携 (live sync)**: Canvas を QGIS のライブ連動ビュー化。
  - QSettings `kasugai_live_sync` / bridge `liveSyncStart` で有効化すると、
    レイヤ編集(地物追加/削除・ジオメトリ/属性変更)・スタイル変更・
    レイヤ追加/削除・ツリー可視性変更を 1.2 秒デバウンスで検出し、
    最後のエクスポート先へ**差分エクスポート**(未変更レイヤの
    GeoJSON/.qml/焼き付けPNG 書き出しを省略)する。構造変更時は全再出力。
  - エクスポート時 `.kasc` に `live: <base URL>` 行と `live.json`
    マニフェスト({rev, updated, changed})を出力。Canvas 側は
    live.json ポーリングまたは /api/command の `liveSync` プッシュで
    即時反映し、テキスト不変時は変更レイヤのみ再読込する。
  - **逆方向(Canvas → QGIS)**: 新エンドポイント
    `POST /live/camera`(Canvas カメラ → QGIS キャンバス中心/縮尺/回転)、
    `POST /live/selection`(Canvas 地物選択 → QGIS レイヤ選択。
    ids/bbox/点+buffer_m 指定)。`GET /live/state` が連携状態+
    キャンバス状態を返す。POST は /live/* のみ許可(CORS 既存許可リスト)。
  - bridge: `liveSyncStatus`/`liveSyncStart`/`liveSyncStop`/`liveSyncFlush`。

## [4.8.0] - 2026-11-07

### Added

- アトラス有効な印刷レイアウト → Canvas FLY ルート出力
  (`.kasc` エクスポート・bridge `kasugaiExport` の
  `emit_atlas=True`、既定 ON):
  - 各アトラスページの表示範囲(参照地図の extent)を巡回する
    `fly_geojson:` 行 + `DATA/atlas_<slug>.geojson` を生成。
    LineString 座標の Z 値にページ範囲を収める正典カメラ高を
    焼き込み、`properties.heightReference="MSL"` で
    Cesium 側の地形加算を抑止。ページ名一覧は
    `properties.pages`、速度・pitch(-85)・step 等は
    `properties.fly` へも埋め込む(リロード後も復元)
  - ページ順はアトラスのソート/フィルタを反映
    (`atlas.seekTo` 順)。レイアウト名は `Atlas: <名>` の
    ルートタイトルになる
  - Canvas 側: 2D プレイヤー(shared/player-api.js)で
    点ごとの高度を zoom ではなく height として渡すよう修正し、
    可変縮尺のページ巡回に対応。`fly_geojson` を
    NON_LAYER_TYPES に追加(テーマ適用でルートが `| off` に
    なる既存不具合の修正)
  - 印刷レイアウト本体の PDF 出力は従来どおり `/layouts`・
    `/layout-pdf`(Canvas 印刷ダイアログの「QGIS レイアウトPDF」)
    で、アトラスは全ページが 1 PDF に出力される

## [4.7.1] - 2026-11-07

### Added

- `.kasc` エクスポートの WMS/WMTS・グループ対応を強化:
  - `wms:` 行に `version=` を追加(ソースURIにバージョン指定がある
    場合のみ)。Canvas の GetMap 組み立てが 1.3.0→`CRS=` /
    それ以外→`SRS=` を正しく使い分けられるようになる
  - レイヤツリーの相互排他グループ(チェックで1つだけ表示)を
    Canvas の排他グループ指定どおり直系レイヤのタイトルを
    `親//レイヤ` の `//` 区切りで出力。Canvas 側では排他ラジオ
    グループとして再現される

## [4.7.0] - 2026-11-07

### Added

- QGIS 3Dビュー設定の反映を拡充(kasugai_canvas #60 対応):
  - `terrain:` 行に `generator=`(地形ジェネレータ種別)/`offset=`
    (elevation-offset)/`shading=on`(地形陰影)を追加。
    generator=flat は Canvas(Cesium)側で地形OFFとして反映
  - 新規 `scene3d:` 行: 3Dシーンの背景色(`background=#RRGGBB`・
    白以外)・スカイボックス(`skybox=on`)・影(`shadows=on`)・
    スクリーンスペースAO(`ao=on`)・Eye Dome Lighting(`edl=on`)を
    非既定値のみ出力。Canvas は背景色→シーン背景+空非表示、
    skybox→既定星空復帰、shadows→shadowMap 有効化として反映
  - 新規 `light:` 行: 平行光源(directional-light)をシーン座標の
    光源方向ベクトル(x=東,y=上,z=南)から方位/仰角へ変換し
    `az=`/`el=`/`intensity=`/`color=` として出力。
    Canvas は先頭カメラプリセットの ENU→ECEF 変換で
    `scene.light`(DirectionalLight)へ反映し地形ライティングを有効化
  - ベクターレイヤの3Dレンダラ立ち上げ(QgsVectorLayer3DRenderer の
    ポリゴン/ラインシンボル)をベクター行の `| extrude=<m>`・
    `| z=<m>` オプションとして出力。Canvas(Cesium)側で polygon の
    height/extrudedHeight へ反映(render=primitive 経路では無効)
- 残り未対応: QGIS スカイボックスのテクスチャ画像・点群3Dレンダラ・
  ポイントライト・3Dアニメーション(keyframes)

## [4.6.2] - 2026-11-07

### Fixed

- `embed_gpkg_style=True` で GPKG への layer_styles 書き込みが
  DATA/ へのコピー**後**に行われ、配布コピーにスタイルが含まれない
  問題を修正(4.6.1 と同類の「スタイルが配布物へ届かない」不具合)。
  埋め込みをコピー前に移動し、同一 GPKG の複数レイヤでは既存の
  配布コピーを同一名で上書き再コピーして全レイヤ分を反映するようにした。
  http(s) URL 参照の GPKG には書き込めないため対象外に変更
  (これまで警告なしで常に失敗していた)。temp GPKG の実機検証で
  配布コピーに全レイヤ分の layer_styles 行が入ることを確認
- QML 関連コードで QGIS 4.0 実機検証により到達不能と判明した
  理由不明のフォールバックを除去:
  `QgsSymbolLayerUtils.svgSymbolNameToPath` の1引数呼出し
  (2引数必須のため必ず TypeError→手動検索へ落ちていただけ)、
  同関数の外側 try/except と svg_paths 手動検索ループ
  (QGIS 側が同じパスを検索済みで重複)、
  `QgsMapLayerStyle.xmlData()` の非 str 分岐(常に str)、
  MapThemeLayerRecord の callable/getattr 防御分岐
  (`layer()`=メソッド・`usingCurrentStyle`/`currentStyle`=属性と実測)、
  `saveStyleToDatabase` の tuple 戻り値分岐(str のみ返す)。
  テーマのスタイル記録取得失敗は黙って捨てず warnings へ記録するよう変更

## [4.6.1] - 2026-11-07

### Fixed

- テーマ別名前付きスタイル `DATA/<slug>__<theme>.qml` のシンボル画像
  (SVG/ラスタ) が絶対パスのまま残り Canvas 側で解決できなかった問題を修正。
  テーマスタイルも `_export_qml_assets` を通し、参照を DATA/ 内の
  ファイル名へ書き換えるよう接続（実機検証で DM_1__2.qml の絶対パスが
  `DM_1_*.svg` 相対名へ書き換わることを確認）。

## [4.6.0] - 2026-11-07

- マップテーマのスタイル再現を強化: テーマが記録するレイヤー別の
  名前付きスタイル(MapThemeRecord.LayerRecord.styleName)を
  `DATA/<slug>__<theme>.qml` として出力し、`theme:` 行の該当タイトルに
  `;style=` を付与する。QGIS でテーマ別にスタイルを切り替えている
  プロジェクトを Canvas 側でも再現できる(kasugai_canvas 側が
  テーマ適用時に .qml を差し替え)
- .kasc 行と出力ファイルの紐付けは従来どおり slug 規則
  (`<slug>__<theme-slug>.qml`)

## [4.5.0] - 2026-11-07

- KASUGAI Canvas 連携エクスポートの再現度を強化(kasugai_canvas Issues #49-61 対応):
  - 時間対応レイヤ(QgsTemporal)を `time=`/`time_end=` オプションへ自動出力(#57)
  - ベクターレイヤの不透明度を `opacity=` として全ベクター行へ出力(#58)
  - レイヤ/地物ブレンドモード・未対応レンダラ(2.5D/反転ポリゴン/
    ジオメトリジェネレータ等)を warnings へ明示(#54/#58)
  - ヒートマップ/ポイントクラスタ/ポイント変位レンダラを Canvas 側の
    `heat=on`/`cluster=on` へマッピング(#54)
  - WMTS レイヤ(tileMatrixSet を持つ wms ソース)を `wmts:` 行として出力(#51)
  - 非GeoTIFFラスタ(JPEG/PNG/VRT/IMG/SDAT/GRIB 等)と再現不能なレンダラ設定
    (疑似カラー/ヒルシェード/ストレッチ/パレット)を QGIS で描画済み PNG へ
    焼き付け `image:` 行として出力(#52/#53)。multibandcolor のバンド選択は
    `bands=` として出力
  - 対象外レイヤ種別(メッシュ/ベクタータイル/点群/アノテーション/
    プラグイン/グループ)の skipped 理由を和訳で明示(#50)
  - レイヤーツリー詳細状態: グループ折りたたみを `group:` 行、
    カスタムレイヤー順(hasCustomLayerOrder)を行順で出力(#59)
  - 保存済み3Dビューを `cam:QGIS3D <名前>` 行(dist/pitch/yaw→位置・姿勢逆算)
    と `terrain:` 行(垂直誇張)として出力(#60)
  - プロジェクト保存時の自動再エクスポートを追加(#61)。
    QSettings `kasugai_auto_export` を true にすると projectSaved 直後に
    kasugaiExport(open_app=True) 相当を遅延実行し Canvas へ即時反映

## [4.4.0] - 2026-11-07

- レイヤの「縮尺による表示」設定（`hasScaleBasedVisibility` +
  `minimumScale`/`maximumScale`）を `.kasc` 行へ `| minScale=` / `| maxScale=`
  として出力するようにした。ベクター（geojson/gpkg/geoparquet/flatgeobuf/
  duckdb）、3dtiles、xyz/base、wms、geotiff の全レイヤ行が対象。
  KASUGAI Canvas 側で QGIS と同じ縮尺範囲（minScale=引き側限界→ズーム下限、
  maxScale=寄り側限界→ズーム上限）の表示/非表示として再現される。

## [4.3.0] - 2026-11-07

- GDAL ラスタレイヤ（GeoTIFF/COG）を `geotiff:` 行として `.kasc` に出力するようにした。
  ローカルの `.tif`/`.tiff`/`.gtif` は `DATA/` へ複製して相対参照し、
  `http(s)`/`/vsicurl/` の COG URL はそのまま参照する。
  レイヤ不透明度は `opacity=` へ、出典は `attr=` へ引き継ぐ。
  再生は KASUGAI Canvas（Cesium エンジン）の geotiff.js デコードで行い、
  EPSG:4326/3857 はタイル LOD、それ以外の座標系は四隅再投影のオーバーレイ描画となる。
  これまでは XYZ/WMS/3dtiles 以外のラスタがスキップ対象だった

## [Unreleased]

- `.kasc` 既定ベースマップ群の `淡色地図`/`全国最新写真`（GSI `pale`/`seamlessphoto`）に
  `minZoom=2` と `bbox=122,19,155,47` を追加。両タイルはズーム 2 未満および
  日本周辺の範囲外が存在せず、Canvas 側で global 表示時に大量の 404 タイル要求が
  発生していた（Cesium エンジン側でも `base:` 行の `minZoom`/`bbox` 解釈を実装済み）

## [4.2.2] - 2026-11-07 Canvas 連携のループバックアドレスを 127.0.0.1 へ統一

- Canvas 検出・登録・コマンド送信・生成URL の接続先を `localhost` から
  `127.0.0.1` へ統一。Canvas 本体・バックエンド検出・起動HTMLは
  一貫して `127.0.0.1:8510` を使う設計のため、`localhost` が `::1` 優先で
  解決される環境で `[::1]:8510` の無関係なサービスへ接続してしまい、
  検出失敗→`via: qgis-http` への静かなフォールバックが発生し得た
  （`detect_kasugai`/`register_kasugai_project`/`kasugai_command`/
  `build_kasugai_url`/`build_local_view_url`/`build_hosted_view_url`）
- 併せて Canvas 側(web/)も修正: `switchProject` がページ読込後に
  `/api/projects/register` で登録された外部プロジェクトを一覧未反映で
  「プロジェクトが見つかりません」としていた問題を解消
  （切替前にマニフェスト再読込するよう各エンジンで対応）

## [4.2.1] - 2026-11-06 未読込・破損レイヤのエクスポート対応

- `.kasc`+`DATA/` エクスポート(`export_kasugai_project`)で、レイヤツリー上
  `layer()` が `None` の未読込レイヤを黙って落としていた問題を修正。
  `_tree_layers()` がプロジェクトファイル(.qgs/.qgz)内の `<maplayer>`
  定義を layerId で照合して `readLayerXml` で再生成・再登録
  (スタイル等のプロジェクト設定も復元)し、layerTreeRegistryBridge/
  `resolveReferences` でノードへ解決させて本来のツリー位置で出力する。
  解決不能なものは skipped に「(未読込レイヤ)」として記録
- `isValid()` が False の破損レイヤ(読込時にソース未達等)も
  `setDataSource` で同一ソースの再オープンを試みる。復旧できたものは
  warnings に「破損レイヤを再読込」、不能なものは skipped に
  「(破損レイヤ)」として記録

## [4.2.0] - 2026-10-28 GSI Maps エンジン対応

- KASUGAI Canvas の `gsimaps`(地理院地図)エンジンを起動エンジンの
  選択肢に追加(`VALID_ENGINES`・`normalize_engine`)
  - `GET /kasugai?engine=gsimaps`・bridge `kasugaiExport`/`openExternal`・
    `setSettings(kasugai_engine)`・パネルの `Engine:` コンボで選択可
  - エクスポート時に `gsimaps.html` 起動ページも生成
    (`_LAUNCHER_ENGINES` に追加、`index.html` のエンジン一覧にも掲載)
- README/SPEC(英・日)/metadata.txt のエンジン列挙を5エンジンへ更新
- 内蔵 HTTP サーバーの CORS を許可リスト方式へ強化: 全応答で
  `Access-Control-Allow-Origin: *` を返していたのを、file://(null)・
  ホスト版エンジン(github.io・設定のカスタムURL)・ループバックの
  オリジンのみへエコーに変更。OPTIONS の Private Network Access 応答も
  許可オリジンのみ返し、任意サイトからのローカルデータ読み取りを遮断

## [4.1.0] - 2026-10-28 印刷レイアウト PDF 出力エンドポイント

- 内蔵 HTTP サーバーに印刷レイアウト関連の2エンドポイントを追加
  (KASUGAI Canvas 印刷ダイアログの「QGISレイアウトでPDF出力」が利用):
  - `GET /layouts` — プロジェクトの印刷レイアウト一覧を JSON で返す
    (`{ok, layouts:[{name,pages,w_mm,h_mm}]}`)
  - `GET /layout-pdf` — `QgsLayoutExporter` で印刷レイアウトを PDF 出力。
    `?layout=<name>` 省略時は先頭のレイアウト、`?dpi=` で 72–600(既定300)
- レイアウト操作は新設 `_MainThreadInvoker` で GUI スレッドへキューイング
  して実行(HTTPワーカースレッドからの直接呼出しを回避)、PDF出力は
  `_layout_lock` で直列化。一時PDFは送信前に削除
- SPEC.md / SPEC_JP.md のエンドポイント一覧を更新

## [4.0.4] - 2026-10-28 サイトスキャン指摘対応

- `kasugai_export._export_qml_assets()` の .qml パースを stdlib
  `xml.etree.ElementTree` から vendored `defusedxml.ElementTree` へ切替
  (B405/B314 指摘をコード側で解消。geo_import と同じく ElementTree
  facade のみ同梱: `__init__.py`/`common.py`/`ElementTree.py`/`LICENSE`)
- 配布ZIPダウンロード `_download()` に https スキーム検証を追加し、
  `kasugai_download_url()` も https のみ採用へ(B310 指摘に対し
  # nosec の位置を修正した上で実コードでも http を拒否)
- `server_manager.py`(カーソル追跡イベントフィルタ)と
  `settings_dialog.py`(レジストリ自動検出)の try/except/pass に
  # nosec B110 と理由コメントを明示
- `.bandit` に `exclude = defusedxml` と B405 スキップを追加、
  `.flake8` に `defusedxml/*.py` の per-file-ignores を追加

## [4.0.3] - 2026-10-27 配布前チェックの lint findings 0 化

- flake8(プラグイン同梱 `.flake8` 設定)で残っていた 4 findings を解消:
  - `plugin.py` の未使用 import `from qgis.core import Qgis` を除去(F401)
  - `panel.py` のツールチップ翻訳呼出し2件の継続行インデントを修正(E128)
  - `kasugai_export.py` の過剰な空行を整理(E303)
- 機能変更なし(配布 ZIP 作成前の plugins.qgis.org スキャン相当
  チェック通過のための整理)

## [4.0.2] - 2026-10-27 生成HTMLのロケール対応とカタログ整理

- エクスポート起動HTML(`index.html`・`<engine>.html`)を
  日本語ベタ書き(`lang="ja"`固定)から英語ソース＋`__T_*__`
  トークン方式へ改修。`kasugai_export._localize_page()` が
  `i18n_json.translate_text()` で `geo_webview.page` コンテキストを
  引き、QGISのUI言語に追従した起動HTMLを出力する
  (未対応言語は従来通り英語)。JS内メッセージも同一仕組みで置換
- `/present` 共有ページの表示文字列(操作ヒント・ナビボタン
  title/tooltip・HUDラベル・独立ビュー表示)を同じ仕組みで
  ローカライズ(`server_manager._localize_page()`)
- `i18n/*.json` 9言語へ `geo_webview.page` コンテキスト41キーを追加
- ソースから参照されなくなった旧文言のカタログキー39件を除去
  (旧「▶ Open」・`+ kasugai_canvas.zip` 時代のツールチップ・
  削除済み OGC/ビューア経路のメッセージ・旧インストール通知等)
- なお `panel.py` のエンジンコンボ再構成(`addItem("Cesium (3D)")` 等)
  と `ZIP`/`📁` ボタンラベルは tr() 未マークのまま(固有名詞のため
  実害なし)

## [4.0.1] - 2026-10-27 KASUGAI 出力 UI の未翻訳文字列を9言語カタログへ追記

- `i18n_tool.py check` で検出されたカタログ未登録26キー
  (実行時は全言語で英語フォールバックしていた)を
  `i18n/*.json` 9言語全てへ追記:
  - `geo_webview` コンテキスト 19件:
    「▶ Canvas」「▶ WebView」ボタン、Export/ZIP/📁/↺/? の
    ツールチップ、保存先選択ダイアログと成否メッセージ、
    起動フォールバック通知(`Exported to {0}. {1}` /
    `KASUGAI Canvas is not running…` / `Local delivery…` /
    `Serverless delivery…` / `No engine available…`)等
  - `QMapPermalinkPanelBase` コンテキスト 7件
    (panel_base.ui 側の同一文字列)
- 翻訳は ja/de/es/fr/it/pt/ru/zh/hi を作成。`{0}`/`{1}`/
  `<channel>` 等のプレースホルダと製品名は保持
- なお `kasugai_export.py` の起動HTMLテンプレート
  (`_ENGINE_LAUNCHER_HTML`/`_LAUNCHER_INDEX_HTML`)は
  `lang="ja"` 固定の日本語ベタ書きのまま残存(生成HTMLの
  `translate_text` 化は別途対応が必要)

## [4.0.0] - 2026-10-27 マルチエンジンを主軸としたメジャー更新

主な変更: **マルチエンジン**（Cesium / MapLibre / OpenLayers / Leaflet）
対応を本プラグインの主軸として確立し、配信アーキテクチャと
ドキュメントをこれを中心に全面再構成した。

- マルチエンジン配信アーキテクチャの確立:
  - 同じ `.kasc`+`DATA/` を4エンジンで再生（`?engine=` / `<engine>.html`）
  - エンジン本体は GitHubPages CDN（kasugai-canvas-web、
    `stable`/`unstable` チャンネル）から配信し、
    データのみ自ホスト/WebGIS から供給する構成を既定化
  - 起動HTMLはローカル探索（`./ ../ ../../ /`）→ ホスト版への
    フォールバックで CDN/同梱の混在にも対応
- パネルを3行構成に整理（保存行/CDN行/起動行）し、
  【エクスポート】【ZIP】【▶ WebView】【▶ Canvas】を機能の柱として明確化
- 専用ドキュメントサイトを新設: `docs/`（index + architecture /
  features / engines / getting-started / technical / license）。
  正式ドキュメントは本サイトとし、`DOC_JP.md` を生成元として
  `scripts/build_geo_webview_docs.py` で自動生成
  （左サイドバー目次・Mermaid 構成図・3本柱カード）。
  README は最小構成（概要＋リンク＋クイックスタート）へ縮小
- 配布 ZIP から `docs/` を除外（build-plugin-zip.py の除外強化）
- パネル「Web配信」グループの枠上（右上）に `?` ヘルプボタンを追加:
  ドキュメントサイト（GitHub Pages）をブラウザで開く

## [3.37.0] - 2026-10-27 ZIP をダウンロード方式へ変更（エクスポート時生成を廃止）

- パネル【エクスポート】で `kasugai_canvas.zip` を生成しなくなった
  （`.kasc`+`DATA/`+`<engine>.html`+`index.html` のみ出力。
  bridge `kasugaiExport(emit_zip=True)` は従来通りZIP生成可）
- パネルに【ZIP】ボタンを追加（CDN 行に配置）: エクスポート物一式を
  `kasugai_canvas_<チャンネル>.zip` としてブラウザでダウンロードする
  （ファイル名は CDN コンボのチャンネルを反映。例 stable →
  `kasugai_canvas_stable.zip`、カスタムURLは末尾パス要素）
- `/export-data/kasugai_canvas*.zip` はファイル未生成でも
  オンデマンドで ZIP を固めて返すようにした
  （`Content-Disposition: attachment` 付き。常に直近エクスポートの最新内容。
  エクスポート実行時は残存した旧ZIPを除去して陳腐化を防止）
- 出力される `index.html` に「パッケージ ZIP」セクションを追加
  （サーバレス WEB 配信経路の下。HTTP 配信時のみ有効）
- README/README_JP: 連携構成図を最終形に整理
  （外部HTTPサーバー→WebGIS 改名、ZIP ダウンロード→静的ホスト/Re:Earth
  の2系統配線、CDN→WebGIS 配線追加、サブグラフ順序整理、
  ArcGIS ノード簡素化）＋ セクション4「WebGIS」に
  外部ホスト配信の2パターン（CDN 利用/同一ホスト同梱）比較を追記
