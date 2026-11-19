# 変更履歴(Changelog)

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
