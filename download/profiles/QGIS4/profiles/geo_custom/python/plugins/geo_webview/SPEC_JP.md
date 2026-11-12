# geo_webview — 仕様書

この仕様書は `README.md` と `CHANGELOG.md` の内容に基づき、機能別に整理した正式な仕様を提供します。
対象リポジトリ: `geo_webview`（ルートに配置）。

## 目的と範囲
- 目的: geo_webview プラグインの機能を明確に仕様化し、実装・運用・テストの基準を定める。
- 範囲: サーバレス Web 配信（`.kasc`+`DATA/` エクスポート＝**主機能**）、組み込みHTTPサーバー（`/kasugai`・`/export-data/`・`/present`・`/screenshot`・パーマリンク受領＝補助）、パーマリンク生成・ナビゲート、テーマ適用、External Control の挙動、投影（CRS）ポリシー、セキュリティ/運用上の注意。

## 1. 機能概要
- **サーバレス Web 配信（主機能）**: 開いている QGIS プロジェクトを `.kasc`+`DATA/` パッケージとして出力し、KASUGAI Canvas のマルチエンジン（Cesium/MapLibre/OpenLayers/Leaflet/GSI Maps/Navara）で再生する。出力物＋エンジンを静的ホストへ置くだけで配信できる。起動経路はパネル（`Export`=ファイル出力のみ / `▶ Open`=登録・起動まで）・`GET /kasugai`・bridge `kasugaiExport` の3系統で、Canvas登録→本サーバ静的配信→ホスト版エンジンの3段フォールバックを持つ（§15）。
- 組み込み HTTP サーバー（補助）: `/kasugai` `/export-data/` `/present` `/present/state` `/screenshot` `/received` `/layouts` `/layout-pdf` を提供（v3.29.0 で OGC サービスは廃止）。
- パーマリンク生成: QGIS の現在表示（中心座標、scale、rotation、theme など）を HTTP パーマリンク（`/qgis-map` パス）として生成・コピー・開く。`/qgis-map` は HTML を返さず、受領記録・External Control ナビゲートの URL パスとして使う（v3.24.0 でプラグイン内蔵ビューアは廃止）。
- Theme サポート: `theme` パラメータのマップテーマをナビゲーション時に適用し、`.kasc` へ `theme:` 行として出力（プロジェクト自体は変更しない）。
- External Control: 外部からの `/qgis-map` や `/wms` を含むリクエストを受け、許可された場合に自動で QGIS をナビゲートする。
- レンダリング: `/screenshot` は現在のキャンバス MapSettings（回転含む）を `QgsMapRendererParallelJob` で複製描画し PNG を返す（`w`/`h` 指定・4096px クランプ・`_render_lock` 直列化・30秒タイムアウト）。

---
## 2. API / エンドポイント仕様（高水準）
- GET `/kasugai` — `.kasc`+`DATA/` エクスポート＋Canvas 登録。`engine=`（cesium|maplibre|openlayers|leaflet|gsimaps|navara、既定 cesium）・`install=1`（未検出時に配布ZIP取得）を受け付ける。応答 JSON `{ok,url,via,dir,layers,tiles,engine}`。
- GET `/export-data/<rel>` — 直近エクスポート出力先配下のファイル配信（.kasc/DATA/・起動HTML等）。
- GET `/<engine>/...` — インストール済み KASUGAI Canvas の `web/` を静的配信（エンドポイント不一致パスのフォールバック解決）。
- GET `/present` `/present/state` `/screenshot` — 画面共有ページ・キャンバス状態 JSON・キャンバス PNG。
- GET `/layouts` — プロジェクトの印刷レイアウト一覧 JSON `{ok,layouts:[{name,pages,w_mm,h_mm}]}`（KASUGAI Canvas 印刷ダイアログが参照）。
- GET `/layout-pdf` — `QgsLayoutExporter` で印刷レイアウトを PDF 出力（`layout=<name>` 省略時は先頭のレイアウト、`dpi=` 72–600・既定300）。キューイングで GUI スレッド実行・`_layout_lock` で直列化。
- GET `/received` — 受領パーマリンク履歴 HTML。
- GET `/qgis-map` — パーマリンク URL のパス。HTML は返さず、受領記録・External Control のナビゲートトリガとして使う。
- HEAD `/export-data/`・`/<engine>/` — ランチャー HTML のエンジン自動探索プローブ用（静的配信のみ応答）。
- OPTIONS — CORS+Private Network Access プリフライト（hosted エンジン https→localhost の fetch 用）。

共通的な振る舞い:
- サーバはデフォルトでポート範囲 8089-8099 を試行してバインドする。
- サーバは `0.0.0.0` にバインドし、LAN 共有は本機能の仕様。ユーザーへ見せるURL（プレゼン共有ボタン・パネルのサーバーステータス・起動時メッセージ・bridge `openPresent`/`serverStatus`/`startServer` の `network_url`）は外部PCが接続できるよう `http://<LAN-IP>:<port>` を優先表示し、LAN IP が取れない場合のみ `localhost` へフォールバックする。共有ボタンはURLをクリップボードへもコピーする。外部PCから届かない場合は Check Access 診断・ファイアウォールルール追加ボタンを使う。

---
## 3. パーマリンク形式とパラメータ
基本（推奨）
- `x` : 経度（または投影座標系の X）
- `y` : 緯度（または投影座標系の Y）
- `scale` : QGIS の scale（例: 1000.0）
- `crs` : 省略時は `EPSG:4326` として解釈。
- `rotation` : 表示の回転（度）
- `theme` : マップテーマ名（存在する場合に適用する）

例:
```
http://localhost:8089/qgis-map?x=139.01234&y=35.12345&scale=1000.0&rotation=0.00
```

短縮形式（プレゼン資料向け）
- 小数切り捨て等で `x=139&y=35&scale=1000.0` のように短くできる。

変換ルール:
- `scale` 指定があれば優先して適用。
- `zoom` は内部推定（Web マップ用の推定）で用いるが、基本は `scale` を優先。

---
## 4. Web 配信（KASUGAI Canvas エクスポート）

プラグイン内蔵の生成HTMLビューア（旧 `/qgis-map`・`/maplibre`・`/map3d`）は
**v3.24.0 で廃止**され、閲覧は KASUGAI Canvas に一本化された。
現在の Web 配信は `.kasc`+`DATA/` エクスポートが中核であり、詳細は §15 を参照。

- 生成物: `kasugai_canvas.kasc`・`index.html`・`<engine>.html`×6（cesium/maplibre/openlayers/leaflet/gsimaps/navara）・`project.json`・`bookmarks.xml`・`DATA/`（GeoJSON/ネイティブ形式/.qml/タイル複製）。
- 起動 HTML: `?kasc=<.kasc URL>` 付きで対応エンジンへ転送し、エンジン本体を `./ ../ ../../ /` の順に自動探索（`CANVAS_BASE` で差し替え可。エンジン未検出時は `HOSTED_BASE` のホスト版エンジンへ誘導）。

---
## 5–9. OGC サービス（v3.29.0 で廃止）

WMS / WMTS・XYZ / WFS・`/maplibre-style` の各エンドポイントと関連内部実装
（`wms_service.py`・`wmts_service.py`・`wfs_service.py`・`sld_renderer.py`・
`maplibre/`、ANGLE パイプライン、WFS/WMTS キャッシュ）は v3.29.0 で撤去。
プラグインはサーバレス配信（`.kasc`+`DATA/` 出力＋`/export-data/` 配信）に専念する。
旧実装の詳細は git 履歴を参照。


## 10. Google Maps / Google Earth 連携（v3.30.0 で廃止）

Google Maps / Google Earth の URL 生成・パース機能
（`_build_google_maps_url`・`_build_google_earth_url`・
`_parse_google_maps_at_url`・`_parse_google_earth_url`・パネルの外部
起動ボタン・bridge の `googleMapsUrl`/`googleEarthUrl`/`openExternal`
の Google 対応）は v3.30.0 で撤去。Google Earth へのリンクは
KASUGAI Canvas 側のベースマップコントロールが担う。
旧実装の詳細は git 履歴を参照。

---
## 11. External Control（外部制御）のパース優先度と挙動
- 機能: パネルの `External Control` が有効なら、外部から受信した URL を自動適用して QGIS をナビゲートする。
- パース優先度は上記 §6 に準じる。
- 動作:
  - 受信 URL をパースして `navigate_from_http` ルートを使い QGIS の表示を更新する。
  - パネル起動時に既に受信済みの URL がある場合は自動ナビゲートを実行（設定に依存）。
- セキュリティ: 自動ナビゲートは UX を上書きするため、明確な ON/OFF トグルを持ち、ログに受信元・実行時刻を記録することを推奨。

---
## 12. テーマ (Theme) サポート
- `theme` パラメータに指定されたマップテーマをナビゲーション時に適用する。プロジェクト自体の状態を変更しない。
- `theme` 値はプロジェクト内の既存マップテーマ名のみサポート。未存在の場合は No Theme（位置のみ適用）へフォールバック。
- スタイルのエクスポートでは QGIS バージョン差に備えて `exportNamedStyle` 等の呼び出しにフォールバックを用意。

---
## 13. レンダリング（/screenshot）とパフォーマンス
契約（contract）:
- 入力: `w`/`h`（または `width`/`height`）。省略時はキャンバスサイズ、上限 4096px。
- 出力: 現在のキャンバス表示と同等の PNG（回転・縮尺・表示中レイヤを反映）。
- 応答ヘッダ `X-Map-Extent`: 実際に setExtent した範囲（キャンバスCRS、
  `xmin,ymin,xmax,ymax`）。`X-Map-Corners`: 画像の左上/右上/左下の実座標
  （x,yを6値連結。回転時も画像の写る位置を正確に示す）。

視聴者ズーム（クライアント単位・ステートレス）:
- `extent=xmin,ymin,xmax,ymax` — setExtent リテラル値（直前の
  X-Map-Extent で同一描画を再現する用途）。
- `screen=xmin,ymin,xmax,ymax` — 画面上に見せたい領域。回転時は
  逆回転した外接矩形へ内部変換して描画（回転0では extent と同義）。
- `bbox=cx,cy,fw,fh` — ベース画像（既定=現在のキャンバス描画）に対する
  割合座標で中心(cx,cy)・表示幅高(fw,fh、0..1)を指定して部分描画。
  `base=<extent>`+`bw`/`bh` でベース画像を差し替え、ズーム表示を
  さらに拡大・移動する継続操作ができる（中心計算は `mapToPixel` 経由で
  回転に対応）。
- `rot=<deg>` — 描画回転の明示指定（`rot=0` で北向き描画）。
- `/present` は同梱OpenLayers(`vendor/ol`)ページ。描画は `rot=0` の
  北向きレンダリングを ImageStatic で配置し、キャンバス回転は
  `/present/state` 経由でビュー回転として再現するため、全ジェスチャが
  回転座標系で整合する（再描画は `moveend` 時のみ要求）。

実装:
- キャンバスの `QgsMapSettings` を複製し `QgsMapRendererParallelJob` で描画する
  （`server_manager._render_map_settings`）。GUI スレッドをブロックせず、
  HTTP ワーカースレッドから呼べる。
- 複数の `QgsMapRendererParallelJob` 同時実行は QGIS クラッシュを招くため
  `_render_lock` で直列化する。30秒でタイムアウト（ジョブを cancel）。

性能上の注意:
- 大きな出力サイズはメモリと CPU を要するため 4096px でクランプする。

---
## 14. 投影 (CRS) ポリシー
- `.kasc` エクスポートのベクターは EPSG:4326 に正規化して出力する（ネイティブ参照の GPKG/Parquet/FGB はクライアント側で処理）。
- `crs` を指定しないパーマリンクは `EPSG:4326` として解釈される。
- 座標変換は `QgsCoordinateTransform` を利用。プロジェクトによっては外部の proj 定義が必要となる場合がある。

---
## 15. KASUGAI Canvas 連携（送出）

QGIS プロジェクトのレイヤツリーを、KASUGAI Canvas のプロジェクト
（`.kasc` + `DATA/`）として書き出す機能。実体は `kasugai_export.py`。

### 起動経路

| 経路 | 呼び出し | 用途 |
|---|---|---|
| パネルボタン | `▶ Canvas` / `▶ WebView` ボタン (`plugin.py: on_kasugai_launch_clicked`) | 人手操作。パネルの `Engine:` コンボで起動エンジンを選択（QSettings `kasugai_engine` に保存）。`▶ Canvas`（route=`kasugai`）は**再エクスポートせず**既存の `.kasc` を登録・ブラウザ起動（未出力時はエクスポートを促すメッセージ）。Canvas 未検出時はボタンが「Install KASUGAI Canvas」表示となり、クリックでセットアップ(NSIS・.kasc 関連付けあり)/ポータブルZIP(展開のみ)を選んでバックグラウンドインストール後に起動へ合流。`▶ WebView`（route=`hosted`）は bridge `kasugaiExport(open_app=True)` と同じく出力→フォールバック→ブラウザ起動まで行う。CDN 行の `CDN:` コンボ（編集可、ZIP ボタンと同じ行）でホスト版チャンネルを選択（`stable`/`unstable`/カスタムURL、QSettings `kasugai_hosted_channel` に保存・設定ダイアログと共通） |
| パネルボタン | `Export` ボタン (`plugin.py: on_kasugai_export_clicked`) | 人手操作（ファイル出力のみ。Canvas 起動・登録はしない。ZIP は生成しない） |
| パネルボタン | `ZIP` ボタン (`plugin.py: on_kasugai_zip_clicked`) | エクスポート物一式を `kasugai_canvas_<チャンネル>.zip` としてブラウザダウンロード。`/export-data/` がオンデマンドで ZIP を生成して返す（要 HTTP サーバー稼働）。CDN コンボのチャンネルがファイル名に反映される |
| HTTP | `GET http://localhost:8089/kasugai` (server_manager._handle_kasugai) | 外部アプリ・AI からの一発起動。`?engine=` で起動エンジン指定可。応答は `{ok,url,via,dir,layers,tiles,engine}` JSON |
| Bridge | `bridge_call` の `kasugaiExport(output_dir, open_app, native_formats, hidden_as_off, embed_gpkg_style, emit_themes, emit_bookmarks, emit_launchers, engine, install, route, use_existing, emit_atlas)` | Live Driver 経由の AI 制御（MCP `qgis_bridge_call` / REST `/api/cmd` / JSONL）。`use_existing=True` で再エクスポートせず既存の `.kasc` のみ使用（未出力なら `code=not_exported`） |

### 出力フォルダ構成

```
<out_dir>/                    # 既定: <ドキュメント>/kasugai_canvas_qgis
├─ kasugai_canvas.kasc        # インスペクタ設定(外部プロジェクト登録対象)
├─ project.json               # {"title": ...}
└─ DATA/
   ├─ *.geojson               # 変換が必要だったベクター(EPSG:4326)
   ├─ *.gpkg                  # ネイティブ参照の GPKG(複製)
   ├─ *.parquet / *.fgb       # ネイティブ参照の Parquet/FGB(複製)
   ├─ *.csv / *.tsv           # duckdb: 参照の区切りテキスト(複製)
   ├─ <dir>/                  # ローカル 3D Tiles / ローカル XYZ タイルの複製(1GiB 上限)
   ├─ *.qml                   # 各ベクターレイヤの QGIS スタイル
   └─ *.svg / *.png 等        # .qml が参照するシンボル画像(QGIS 内蔵SVG・ローカル画像の複製)
```

### .kasc 行の生成規則

| QGIS 側 | .kasc 行 | 備考 |
|---|---|---|
| GPKG ソース(地理座標系) | `gpkg: グループ/名 | DATA/x.gpkg | on | table=<表> | style=DATA/x.qml` | ファイルを DATA/ へ複製。複数テーブルは1ファイルを共有 |
| GeoJSON/Parquet/FGB ソース | `geojson:` / `geoparquet:` / `flatgeobuf:` 参照行 | ローカルは複製、http(s) は URL をそのまま記述 |
| CSV/TSV(delimitedtext・ogr) | `duckdb: 名 | DATA/x.csv | on | format=csv | lon=<列> | lat=<列>` | ジオメトリ列は `geom=`。delimitedtext は URI の xField/yField/wktField を引き継ぎ、ogr CSV はヘッダから推定。delimitedtext で非地理座標系の場合は GeoJSON 変換 |
| フィルタ(subsetString)付き GPKG | `gpkg: … | where=<フィルタ>` | ネイティブ参照のままフィルタ維持 |
| フィルタ付き Parquet | `duckdb: 名 | DATA/x.parquet | on | format=parquet | where=<フィルタ>` | `geoparquet:` には where= が無いため duckdb: に切替 |
| フィルタ付き GeoJSON/FGB | GeoJSON(EPSG:4326)へ変換して `geojson:` 行 | フィルタを地物に反映して出力 |
| 3D Tiles レイヤ(QgsTiledSceneLayer) | `3dtiles: グループ/名 | <tileset.json URL or DATA/x/tileset.json> | on` | http(s) は URL 参照、ローカルはディレクトリごと DATA/ へ複製(1GiB 上限・超過は skipped) |
| XYZ タイルラスタ | `xyz:` 行。表示中の**最下段**のみ `base:` 行（既定ベースマップとして既定群の先頭に置く）。「背景図」「ベースマップ」「basemap」名のグループ内にある XYZ は位置・表示状態に関わらず全て `base:` 行（ベースマップ候補）として登録し、グループ名はタイトルから外す（配下のサブグループは残し、Canvas のベースマップ選択でグループ化表示される）。非表示の候補は `| off` 付きで出力。グループ名は設定ダイアログの Basemap Groups（QSettings `kasugai_basemap_groups`・カンマ区切り）で追加可能 | zmin/zmax → minZoom=/maxZoom=。不透明度は opacity=、限定範囲は bbox=西経,南緯,東経,北緯。縮尺表示は minScale=/maxScale= |
| XYZ ローカルテンプレート | `xyz:` 行(DATA/<dir>/{z}/{x}/{y}.png) | `file:///…/{z}/{x}/{y}.png` はタイルツリーごと DATA/ へ複製(1GiB 上限・超過は skipped) |
| WMS ラスタ(type=xyz 以外) | `wms: グループ/名 | <エンドポイントURL> | on | layers=, styles=, format=` | QGIS の WMS 接続 URI から url=/layers=/styles=/format= を抽出。Canvas 側が GetMap を 256px タイルへ分解して要求 |
| その他ベクター(SHP/PostGIS/WFS/メモリ等)・非地理座標系 | GeoJSON(EPSG:4326)へ変換して `geojson:` 行 | 再投影は warnings に記録 |
| 属性テーブルのみ(NoGeometry)・ローカルラスタ・ベクタータイル・メッシュ・点群・アノテーション等 | 出力せず `skipped` に種別/理由付きで記録 | |
| 非表示レイヤ | `hidden_as_off=True` 時のみ `| off` 付きで出力 | 既定(visible_only=True)では除外 |
| キャンバス | `cam:` 行(中心座標+概算高度+回転) | |
|| 保存済み3Dビュー(ローカル/グローブ) | `cam:QGIS3D <名>|lat|lon|h=|p=|d=` 行(注視点+dist/pitch/yaw→ENUオフセットでカメラ位置逆算: 高さ=dist·cos(pitch)・水平=dist·sin(pitch)・視線方位=360-yaw・p=pitch-90) + `terrain:` 行(垂直誇張/オフセット/陰影/ジェネレータ) + `scene3d:` 行(背景色/スカイボックス/影/SSAO/EDL・グローブは globe=on) + `light:` 行(平行光源の方位・仰角・強度・色) | 3Dビューが存在する場合のみ出力。シーンCRSはビューごとの `<qgis3d><crs>` を解決し、地心系(QGIS4グローブ・EPSG:4978等)はECEF→測地変換で対応。既定値相当の項目は省略 |
|| 3Dビューのアニメーション(`<animation3d>`キーフレーム) | `fly_geojson: QGIS3D <名> | DATA/anim3d_<slug>.geojson | speed=<m/s> | view=camera | step=<m>` 行 + カメラ軌道の LineString GeoJSON | 各キーフレーム(注視点+dist/pitch/yaw+時刻)のカメラ位置を計算してカメラ軌道にする。speed=軌道3D総延長÷アニメ時間。キーフレーム2個未満は出力しない |
| ベクターの3Dレンダラ(立ち上げ) | ベクター行へ `| extrude=<m>`(立ち上げ高さ)・`| z=<m>`(基準高さオフセット) を付与 | QgsVectorLayer3DRenderer のポリゴン/ラインシンボル。Canvas(Cesium)側で polygon の height/extrudedHeight へ反映 |
| ブックマーク | `bookmarks.xml`(qgis_bookmarks形式・EPSG:4326正規化) + `bookmark:` 行(プロジェクト+アプリケーション両方) | `emit_bookmarks=False` で抑制。Canvas 側が XML を読み込みカメラプリセットへ展開する |
| アトラス有効な印刷レイアウト | `fly_geojson: Atlas: <レイアウト名> | DATA/atlas_<slug>.geojson | speed= | pitch=-85 | height=0 | view=camera | step=` 行 | `emit_atlas=False` で抑制(v4.8.0〜)。各アトラスページの表示範囲(参照地図 extent)を巡回するプレゼン用フライパス。座標Z値にページを収めるカメラ高(楕円体高)を焼き込み、`properties.heightReference="MSL"` で地形加算を抑止、ページ名一覧は `properties.pages` へ。地図回転付きは warnings に記録のみ |

その他: `attr=` に QGIS レイヤの出典(attribution)を引き継ぐ。
全レイヤ行で `minScale=`/`maxScale=` に QGIS の「縮尺による表示」
(minimumScale=引き側限界・maximumScale=寄り側限界)を出力する。
Canvas 側は同じ範囲で表示/非表示を切り替える。
`.qml` 書き出し後、シンボルレイヤが参照する画像(SvgMarker/RasterMarker/
SVGFill/RasterFill 等の `name`/`imageFile`/`svgFile`/`file`)を実ファイルへ
解決して DATA/ へ複製し、.qml 内の参照を DATA/ 内のファイル名へ書き換える
(QGIS 内蔵SVGの `transport/…` 等の相対名は `QgsApplication.svgPaths()` で
解決。http(s)/data/base64: 参照はそのまま維持。解決不能は warnings 記録)。
`embed_gpkg_style=True` なら `saveStyleToDatabase` で GPKG の
`layer_styles` にも既定スタイルを保存する(**元ファイルを更新する**。
保存は DATA/ へのコピー前に行うため配布コピーにも layer_styles が
含まれ、同一 GPKG の複数レイヤも全レイヤ分が入る。
対象はローカル GPKG のみで、http(s) URL 参照の GPKG は対象外)。
`sql:` 行は QGIS 側に対応する任意クエリソースが無いため出力しない
（クエリ系は `duckdb:` の宣言的オプションで網羅する）。

### KASUGAI 側への反映

起動中の KASUGAI ローカルサーバー（`KASUGAI_CANVAS_PORT`、既定 8510）が
あれば `POST /api/projects/register` で外部プロジェクト登録し、
`POST /api/command` の `switchProject` で表示を切り替える。

Canvas が使えない場合は次の順でフォールバックする
（`/kasugai`・`kasugaiExport` とも応答の `via` で供給元を返す）:

| `via` | 条件 | URL |
|---|---|---|
| `kasugai` | Canvas 稼働（or exe/関連付けで起動成功） | `http://127.0.0.1:8510/<engine>/?project=<id>` |
| `qgis-http` | Canvas 未起動だが **インストール済み** `web/` あり | `http://localhost:<port>/<engine>/?kasc=<export-data URL>` |
| `hosted` | Canvas **未インストール**（要インターネット） | `https://yamamoto-ryuzo.github.io/kasugai-canvas-web/<channel>/<engine>/?kasc=<export-data URL>` |
| `null` | いずれも不可 | 出力のみ成功 |

- `qgis-http`: geo_webview の HTTP サーバーが **エンドポイントに一致しなかった
  パスをインストール済み Canvas の `web/` 配下へ静的解決**する
  （`find_kasugai_web_dir()`）。同一オリジンのため混在コンテンツ問題なし
- `hosted`: エンジン本体は `kasugai-canvas-web`（GitHub Pages）から取得し、
  `.kasc`+`DATA/` は本サーバーの `/export-data/` から読む。https→localhost
  の fetch は Chrome Private Network Access 対象のため、サーバーは
  `OPTIONS` プリフライトに `Access-Control-Allow-Private-Network: true` で
  応答する。チャンネルは設定 `kasugai_hosted_channel`
  （`stable`/`unstable`/カスタムURL、既定 `stable`）で、
  パネルの `CDN:` コンボまたは設定ダイアログから変更する
- エンジン起動HTML は `HEAD` メソッドで `<engine>/index.html` を自動探索する
  ため、サーバーは `HEAD`（静的配信のみ）にも応答する

### AI からの操作

- Live Driver の `qgis_bridge_call`（MCP/REST/JSONL）で
  `kasugaiExport` を呼ぶ — 推奨（引数制御可能・JSON 応答）
- または `GET /kasugai` を直接 HTTP で呼ぶ
- KASUGAI 側の WebView プラグイン `qgis-import`
  （kasugai_canvas `web/PLUGIN/`）の「QGISから取り込み」ボタンも
  同じ `/kasugai` を呼ぶ薄い実装

---
## 16. セキュリティ・運用上の注意
- デフォルトで外部アクセスを許す設計だが、公開環境ではファイアウォールやプロキシでアクセス制御を厳格に行うこと。
- `External Control` を有効にしていると任意の外部URLで QGIS の表示が書き換わるため、信頼できるネットワーク内または追加の承認フローを用いることを強く推奨。
- ログを適切に出力し、受信元IP・タイムスタンプ・実行アクションを残す運用を推奨。

---
## 17. テスト・QA 手順
自動テスト候補:
- `server_manager.py` のユニットテスト: ポート選定・バインド挙動のモックテスト。
- URL パーサ（内部形式）の単体テスト（複数フォーマットのケース）。
- `wmts` タイル座標→BBOX 変換のユニットテスト。

手動テスト手順（QGIS 実環境）:
1. QGIS を起動しプラグインをインストール。
2. `Export` で `.kasc`+`DATA/` を出力し、パネルの `Engine:` でエンジンを選び `▶ Canvas` を押してブラウザでそのエンジンが開くことを確認（未出力時はエクスポートを促すメッセージが出る）。`▶ WebView` は出力→ブラウザ起動まで一発で行う（`/kasugai` と同じフォールバックが働く）。
3. `External Control` を ON にして、別ホスト（または同一ホスト）から `/qgis-map?x=...&y=...&scale=...` にアクセスして QGIS がジャンプすることを確認。
4. `/screenshot` でキャンバス PNG が返ることを確認。
5. `/present` ページがブラウザで開くことを確認。

テスト注意:
- CI 環境では `qgis.core` や `PyQt5` が無いため、これらをモックするかローカルでの手動確認が必要。

---
## 18. 実装ファイルと責務マッピング
- `plugin.py` — メインプラグインロジック、パーマリンク/ナビゲート、パネルイベント配線。
- `panel.py` — パネル UI 実装（Web配信グループ、ナビゲート、生成、外部制御トグル等）。
- `panel_base.ui` — Qt Designer の UI 定義。
- `server_manager.py` — 組み込み HTTP サーバーの起動/停止・ルーティング（`/kasugai` `/export-data/` `/present` `/present/state` `/screenshot` `/received` `/layouts` `/layout-pdf` `/<engine>/` 等）。
- `http_server.py` — HTTP 応答の低水準送信ユーティリティ。
- `kasugai_export.py` — KASUGAI Canvas 連携（`.kasc`+`DATA/` 生成、起動HTML生成、プロジェクト登録、コマンド送信、フォールバックURL構築）。
- `scale_zoom.py` — スケール/ズーム換算。
- `settings_dialog.py` — 設定ダイアログ（KASUGAI インストール先・ホスト版チャンネル・Basemap Groups）。
- `bridge.py` — AI/外部制御用ブリッジ（`kasugaiExport` 等）。

---
## 19. 変更履歴の要約（V2/V3 ハイライト）
- V2.0.0: WMS サポートと外部アクセス（0.0.0.0 バインド）を追加。
- V2.6.0: 投影定義と軸順情報を生成 HTML に埋め込み、座標表示の精度向上。
- V2.8.0: External Control の自動ナビゲート追加。
- V2.10.0: Google Earth `y` トークン対応とスケール推定の改善。
- V2.12.0: テーマ対応 WMS 出力（仮想マップビュー）。
- V2.13.0: WMTS タイルエンドポイント、MapLibre 改善（pitch トグル、zoom clamp 解除）。
- V3.0.0: MapLibre WFS + QGIS スタイル注入の安定化、ベーススタイルの相対URL化、ブラシ無しポリゴンの正しい境界線表示、単位正規化（mm/pt→px）を確立。

- V3.1.0: WMTS キャッシュ導入
  - サーバ側で WMTS タイルのキャッシュを有効化しました。キャッシュは各 "identity" ごとに分離され、identity は表示中のレイヤ識別子（layer ID）と各レイヤに適用されるスタイル識別子（style ID）を決定的に組み合わせた JSON を sha1 ハッシュ化し、その先頭 12 文字（short hash）を採用して生成されます。
  - GetCapabilities の ResourceURL / ServiceMetadataURL に `?v=<identity_short>` を付与することで、クライアントが現在サーバ側で有効な identity を検出できるようにしました。
  - クライアント（MapLibre）は画面移動（moveend）時に GetCapabilities を再取得し、identity が変化していれば WMTS タイルソースのみを差し替えて新しいタイルを取得する挙動を推奨します（WFS やスタイル全体の再読み込みは不要）。
  - この仕組みにより、サーバ側で表示用レイヤやスタイルが変更された際に WMTS のみを効率的に更新・無効化でき、WFS の重複登録や全スタイル再適用に起因する副作用を避けられます。
