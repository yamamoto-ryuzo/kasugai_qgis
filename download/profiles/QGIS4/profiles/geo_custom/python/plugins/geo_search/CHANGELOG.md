# V4.5.2 住所検索の結果精度改善と20件ページング化
- geocode.py: GSI AddressSearch の応答をクライアント側で関連度順に
  リランク(完全一致>前方一致>部分一致>その他。同位はタイトルが
  短いもの優先)。API の生順はデータセット順であり「東京」等では
  「〜町東」「〜市東区」の町字候補が先頭に並ぶため、先頭5件だけ
  切り出すと無関係な地名しか見えない問題を修正
- geocode.py: 行政区画接尾辞(都道府県市区町村郡)を持たない短い入力
  (2〜10文字・数字なし)は "<q>都" の補完リクエストを1本追加し、
  「東京都」「札幌市」「東京都台東区秋葉原」のような行政区画レベルの
  候補を拾って結果先頭へマージ(GSIのみ)
- geocode.py: `search(limit=None)` で全件返却を追加(既定は
  RESULT_LIMIT=20 件)。OSM Nominatim の limit=20、
  Google Places の pageSize=20 も追随
- geocode.py・searchfeature.py・resultdialog.py・plugin.py:
  **取得・地物化をページ単位で行う巨大結果対応**。住所検索タブは
  geocode.search で全アイテムを保持し、新設 AddressFeaturePager が
  ResultDialog のページング(既定20件/頁・タブ設定 "PageLimit"
  で変更可)に応じて必要分だけメモリレイヤへ追記・地物化する。
  「東京」等で1000件超の候補が返っても初期表示は先頭1ページ分のみ
  地物化し、ページを進めるほど全件に到達できる。行番号ラベルが
  最終ページで実行数とずれる既存バグも修正
- geocode.py: `addFeatures` は (bool, 追加後地物リスト) を返し
  渡したオブジェクト側には fid が反映されないため、結果地物の
  id() が未定義→選択行のズームが「範囲を決定できませんでした」に
  なる不具合を、返却地物を使う _add_features ヘルパで修正

# V4.5.1 住所検索タブのスクラッチレイヤ作成チェックを角度/縮尺行へ移動
- widget/searchwidget.py: SearchAddressWidget の
  「スクラッチレイヤを作成」チェックを入力行(プロバイダ/住所入力の
  右端)から角度/縮尺表示行の後ろへ移動。入力行が狭い環境でも
  入力欄が潰れないようにするレイアウト調整

# V4.5.0 住所検索(ジオコーディング)タブを追加
- geocode.py: KASUGAI Canvas(kasugai_canvas/web)の searchProviders /
  parseCoordinateQuery を移植。gsi(国土地理院・既定)・google
  (Geocoding+Placesハイブリッド・要ApiKey)・yahoo(要YahooAppId)・
  osm(Nominatim) の4プロバイダを QgsBlockingNetworkRequest で同期呼出し
  (QGISプロキシ/認証設定を継承・15秒タイムアウト)。キーはタブ設定
  "ApiKey"/"YahooAppId" または環境変数 GOOGLE_MAPS_API_KEY/YAHOO_APPID
- searchfeature.py: SearchAddressFeature を追加。結果を EPSG:4326
  メモリレイヤ「geo_search 住所検索」(title/address/provider/lon/lat)
  のポイント地物として保持するため、既存の結果ダイアログ・地物選択・
  ズーム機構がそのまま利用できる
- widget/searchwidget.py: SearchAddressWidget を追加
  (プロバイダ選択コンボ+1行入力。キー未設定の google/yahoo は
  CANVAS と同じく選択不可にする)
- タブTitle "住所検索"(別名 "Address Search"/"address_search")で
  create_page/フィーチャ生成を配線。座標直入力(35.6,139.7・DMS・
  北緯/東経表記)はジオコーディングを通さず直接地点化
- bridge.py: searchAddress(query, provider, zoom) を追加。
  タブ設定不要でジオコーディング→メモリレイヤ表示→ズームまで実行
- widget/searchwidget.py・searchfeature.py・geocode.py・bridge.py:
  **スクラッチレイヤ作成のON/OFF**を追加。タブ上の
  「スクラッチレイヤを作成」チェック(既定ON、タブ設定
  "CreateScratch"で初期値変更可)をOFFにすると結果を
  プロジェクト非登録のメモリレイヤへ書き込み、レイヤパネルに
  スクラッチを残さない。bridge 側も searchAddress の
  createLayer 引数で制御可能
- setting.json: 既定タブに「住所検索」(Provider=gsi)を追加
- i18n/ 9言語に住所検索関連の訳文を追加

# [Unreleased]
- prompts/search-features.md: **同梱おすすめプロンプト「地物の
  検索」**を追加。geo_driver の prompts 種別(チャット入力欄へ
  挿入する定型文)がプラグイン別 `prompts/` 集約に対応したため、
  属性検索の定型指示を本プラグインに同梱する
- skills/navigate-to-place.md: **同梱スキル「地名・住所への地図
  移動」**を追加。「◯◯へ移動」系の指示では searchAddress
  bridge(ジオコーディング+スクラッチ表示+ズーム+CRS変換込み)を
  優先し、直操作が必要な場合の QgsMapCanvas API(ズームレベル
  ではなく縮尺分母指定・EPSG:4326はキャンバスCRSへ変換)を
  手順書化した

# V4.4.10 bridgeのレイヤ参照を削除済みC++ラッパー対策で安全化
- bridge.py: 検索結果一覧・タブ一覧・zoom・タブ定義で参照する
  `layer.name()`/`layer.id()` を `_layer_name()`/`_layer_id()`
  ヘルパ経由に変更。削除済みQgsMapLayerのC++ラッパー(sip deleted)
  へアクセスして RuntimeError になるケースを握り潰し、
  None を返すようにした

# V4.4.9 Qt5/Qt6 互換シム(qt_compat)を除去
- qt_compat.py を削除。qgis.PyQt/PyQt6/PySide6 を候補探索する動的
  ローダーと、QgsMessageLog.logMessage へ旧整数レベル(0/1/2)を許容
  させる monkey-patch を廃止し、整数レベル変換だけを行う
  log.py の log_message() ラッパへ集約
  (plugin/searchdialog/resultdialog/searchfeature/settingsdialog/
  theme/utils の呼出しを機械置換)。Qt import は全て qgis.PyQt 直接使用

# V4.4.8 個別利用時にGeoSuiteツールバーが表示されない不具合を修正
- plugin.py: `_geo_toolbar()` に `ensure_visible` 引数を追加し、
  項目追加経路ではツールバーの可視状態を保証するようにした
  (ドライバ非稼働の個別利用では表示を強制する経路が無く、
  保存済みウィンドウ状態等でツールバーが非表示のままになり得た)。
  unload時のremoveAction経路は従来通り表示状態を変更しない

# V4.4.7 bridge経由のAI操作を全機能へ拡張
- bridge.py: 設定ダイアログ(openSettings)・タブ設定の書込み
  (setTabSetting/addTab)・結果ダイアログのページ移動(resultPage)・
  表示モード切替(resultDisplayMode)を追加

# V4.4.6 翻訳カタログの欠落分を補完
- i18n/ 各言語JSON(de/es/fr/hi/it/pt/ru/zh)に ja のみに存在した
  121キーの訳文を追加し、全言語でカタログキー数を一致させた
  (Dialog/ResultDialog/SearchDialog/SettingsDialog/plugin コンテキスト。
  縮尺値・記号・geo_search_json 等は全言語同一値)

# V4.4.5 全レイヤ/表示レイヤ検索が常に0件になる不具合を修正
- resultdialog.py: `set_features_by_layer` 内でモジュール先頭のimport済み
  `QCoreApplication` を関数内で再importしていたため、関数スコープの
  ローカル変数扱いとなり import 行前の使用箇所で UnboundLocalError が
  発生。例外が show_features の catch に吸収され `set_features([],[])`
  (空タブ)にフォールバックし、全レイヤ/表示レイヤ検索の結果が常に
  表示されなかった(選択もズームも不可)のを修正。
- bridge.py: `_zoom_to_results` がレイヤCRSのbboxをキャンバスCRSへ
  変換せず `zoomToFeatureExtent` へ渡していたため、CRS不一致
  (例: レイヤ=EPSG:4326 / キャンバス=EPSG:3857)時に誤った場所へ
  ズームしていたのを修正(地物ごとに変換してから結合)。

# V4.4.4 ドキュメントのSecret検出対応
- SEARCH.md/SEARCH_JP.md の接続設定例で Password 値が実値に
  見える文字列("Password"/"パスワード")だったため、シークレット
  スキャンで「Potential Secret Keyword」検出となったのを修正。
  同ファイル内の他例と同じ "..." プレースホルダに統一

# V4.4.3 try/except/pass の nosec 明示
- 584箇所に # nosec B110/B112 を付与(設計上の許容を明示)

# V4.4.2 Qt6互換性チェック対応
- 非スコープ列挙型をスコープ化(Qgis.*→Qgis.MessageLevel.*、
  qt_compat.py含む2箇所)

# V4.4.1 plugins.qgis.org セキュリティスキャン対応
- `get_codes` の PostgreSQL クエリでテーブル/カラム識別子を
  `"`→`""` エスケープする `quote_ident` を導入
  (識別子経由のSQLインジェクション対策)
- LOW指摘(try/except/pass|continue)はレビュー済みの常套パターン
  として同梱 `.bandit` 設定で抑制
- flake8指摘を整理: 関数内の冗長な再importを削除、bare `except:`
  を `except Exception:` に修正、未使用変数を整理。
  残る長行E501は同梱 `.flake8` 設定で明示抑制

# V4.4.0 ユーザーテーマ保存バグ修正 + 検索対象水平回転モード
- `theme.save_user_theme` が常に空の `entries` を出力するバグを修正
  (スナップショット名なしで `collect_visible_layer_snapshot` を呼び、
  存在しない `None` キーを読み戻していたため。内部キー
  `__user_theme_save__` で保存→読み戻すよう修正)。issue #20 の
  ユーザーテーマ保存/読込(`.usertheme.json`・設定ダイアログ・
  bridge `saveUserTheme`/`loadUserTheme`)が実際に機能するようになった。
- issue #10: 検索時に検索対象を水平に回転するモードを追加。
  タブ設定で `rotateMode: "horizontal"`(または `"feature"`/`"target"`、
  もしくは `rotateHorizontal: true`)を指定すると、検索対象地物の
  全頂点の主成分分析(主軸方位)から水平化に必要な角度を計算し、
  ナビゲーション後に `canvas.setRotation` で適用する。
  レイヤCRSとキャンバスCRSが異なる場合は変換してから評価。
  未指定時は従来の固定値 `angle` 動作。
- `SEARCH.md`/`SEARCH_JP.md` に `rotateMode` 設定キーを追記。

# V4.3.1 utils.py のQMessageBox翻訳化
- `utils.py` の JSON エントリ削除処理の警告/情報/書き込みエラー
  QMessageBox(英語直書き5箇所)を
  `QCoreApplication.translate("Dialog", ...)` 化し、
  `Dialog` context に8ソースを全9言語で登録。

# V4.3.0 翻訳方式を `i18n/<lang>.json` に移行
- `.ts`/`.qm` を廃止し、`{"context": {"英語ソース": "翻訳"}}` の
  JSONカタログを新設。`i18n_json.py`(全プラグイン共通ローダ)の
  `install_translator()` で起動時ロードに統一。
- `SearchWidget` context の未登録12メッセージ(角度/縮尺表示・
  検索方式ラベル等)を全9言語で補完。

# V4.2.0 国際化(i18n)対応
- UI文字列を英語ソースに統一(`dialog.ui`/`result.ui`・各ダイアログコード)。
  `self.tr()`/`QCoreApplication.translate` で抽出可能な翻訳呼出に置き換え。
- `i18n/ja.ts` を再生成し全131メッセージに日本語訳を設定、`ja.qm` を再コンパイル。
  他言語カタログは既存訳を継承し、未訳分は英語にフォールバック。
- 表示文字列「すべて」と内部フォーマット値を分離し、保存設定との互換性を維持。
- `README.md` は英語、`README_JP.md` は日本語の2言語ドキュメント構成を維持。
- 修正(翻訳導入で顕在化): `resultdialog.py` の `QCoreApplication` 未importによる
  `NameError`(プラグイン起動失敗)と、`_init_language` の `QTranslator` が
  ローカル変数でGCされて翻訳が無効化される問題を修正(`self.translator` に保持)。

# V4.1.0 AI/外部制御用ブリッジ(QGIS Live Harness)
- `bridge.py`(`GeoSearchBridge`)を追加し `plugin.bridge` に配線。`geo_driver` の `bridge_call` コマンド(ファイルJSONL / REST / MCP)から全機能を呼び出せる。
- メソッド: `pluginInfo` / `status` / `listTabs` / `selectTab` / `search` / `results` / `zoom` / `openDialog` / `closeDialog` / `searchOptions`(pan_mode・fixed_scale・show_layer_name) / `tabOptions`(地番=完全一致|あいまい・字コード、所有者=対象フィールド・一致方式) / `suggest` / `listThemes`・`applyTheme`・`themeAdditive` / `saveUserTheme`・`loadUserTheme` / `getSettings`・`setSettings` / `tabSetting`・`addTabFromCurrentLayer`・`removeTab`・`reloadDialog`。`search` は `options` 引数で検索オプションを事前適用できる。
- `pluginInfo()` は標準自己記述スキーマ(id/name/summary/when_to_use/invoke/methods/state)を返し、ドライバの `describe_plugins` カタログでAIが用途・呼び方を発見できる。
- 残存していたQt5向けフォールバック・非スコープenum・`exec_()`を除去しQt6専用コードに統一

# V4.0.0 QGIS 4.0+ / Qt6 専用化
- QGIS 4.0以上に対応し、QGIS 3.xおよび不要となったQt5 (PyQt5 / PySide2) への互換コードを整理・削除しました。
- 互換レイヤー（`qt_compat.py`）を整理し、QDialogなどのダイアログ実行処理をQt6に合わせて `exec()` の呼び出しにシンプル化しました。
- 実行時に不要な開発・管理用ファイル（古いZIP、バッチファイル、PyQt5関連の不要な設定ファイル、Pipfile等）を削除しました。
- 各種ドキュメント（README_JP.md / README.md）を更新し、QGIS 4.0+ / Qt6 専用モデルとしての表記を最適化しました。

# V3.2.0 検索結果表示の機能強化
- 検索結果表示の操作性・可読性を改善（列幅自動調整・列最小幅・最終列ストレッチの強化）。
- フォーム表示を追加  

# V3.1.0 カテゴリ凡例のカテゴリマージ対応
- カテゴリレンダラーの凡例復元時、保存時と復元時でカテゴリ構成が異なる場合でも、値の分割・複数キー対応によりカテゴリマージ（部分一致）で可視化を再現する仕様に対応。
- THEMES.mdに仕様説明を追記。

# CHANGELOG

## V3.3.0 設定ソースの多様化（setting.json / project variable / geo_search_json）
- 設定ソースが3種類（プラグイン同梱の `setting.json`、プロジェクト変数 `GEO-search-plugin`、外部ファイル参照 `geo_search_json`）を統合して読み込む実装を完成しました。
- 各タブ設定へ読み込み元の情報（`_source`）と読み込み時のインデックス（`_source_index`）を注釈として付与し、設定編集・削除時の対象特定を容易にしました。
- 設定編集・削除フローを強化し、外部ファイル/プロジェクト変数の個別更新とバックアップ作成を行うようにしました。
- UI: タブのソース表示にインデックスを併記するように改善（例: `[setting.json #3]`）。
- いくつかの競合編集ケースでの堅牢性向上（Titleベースのフォールバック削除、ファイル書換時の原子操作）。


## Versioning: VA.B.C
- A: QGIS本体またはプラグインのバージョンアップに伴う本体の修正
- B: UIの変更（プラグインの追加等含む）、本体の簡易な機能追加
- C: プロファイル・プラグイン、本体の修正

---
V2.36.0 検索レイヤを表示にする機能追加。
V2.37.0 Qt6 対応と安定化
- Qt6 (QGIS 3.44+) 環境での互換性対応を追加（`supportsQt6 = True` を metadata に追加）
- `geo_search/qt_compat.py` に Qt5/6 差分の shim と小さな互換パッチを追加
- PyQt インポートを `qgis.PyQt` 経由に正規化
- 結果表示ダイアログの列幅とヘッダー処理を改善（ResizeToContents + 最低幅設定 + 最終列ストレッチ）
- create_zip.py を改善し、ZIP 作成・乾燥実行モードと除外パターンを追加
- 一部環境で再現する UI 描画の初期化タイミング問題に対する防御的処理を追加

V2.35.0 検索対象レイヤ名が複数同一名称である場合は、複数レイヤ検索に対応。  
V2.34.0 検索設定に「スケール」指定を導入。    
V2.33.0 検索設定に「角度」指定を導入。  
V2.32.0 UIのコンボボックスで選択可能な複数モード（ズームto選択、中心パン、固定スケール、アニメーションパン、選択のみ）を導入。  
V2.31.0 フィールド検索での数値フィールド対応を実装（数値入力時に数値型フィールドも検索対象に含める）。  
V2.30.0 ツールバーの起動ボタンの右側にテーマドロップダウンを追加。   
V2.29.0 プラグイン起動時に現在の表示状態を「検索前」というテーマ名で自動保存する機能を追加。  
V2.28.0 検索タブごとにQGISマップテーマ（selectTheme）を選択・適用できる機能を追加。タブ設定編集ダイアログでテーマ指定が可能に。  
V2.27.4 全角英数字の半角変換機能の再構築  
V2.27.0 一つの検索ボックスに対して、複数のフィールドを検索対象機能追加  
V2.26.0 プロジェクト変数の設定_検索対象選択機能追加  
V2.25.0 プロジェクト変数の設定_表示内容選択機能追加  
V2.24.0 プロジェクト変数の設定編集機能追加  
V2.23.0 現在のレイヤを検索対象検索追加  
V2.22.0 表示レイヤ・全レイヤ検索追加  
V2.21.0 カレントレイヤ検索追加  
V2.20.1  
- 多言語対応（英語、フランス語、ドイツ語、スペイン語、イタリア語、ポルトガル語、日本語、中国語、ロシア語、ヒンディー語）  
- QGISの言語設定に応じてUI自動切替  
- create_zip.pyによる最小限ZIP自動生成
- ZIP作成時にmetadata.txtのバージョン自動更新
- 旧バージョンZIP自動削除
V2.20.0  
- QGISプラグインの基本機能実装
- 地番検索・所有者検索・通常検索UI
- 設定ファイルによる検索項目管理

- 検索結果ダイアログ・サジェスト機能

