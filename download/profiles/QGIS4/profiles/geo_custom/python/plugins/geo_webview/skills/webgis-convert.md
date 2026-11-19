# WebGIS向けデータ形式変換・レイヤ追加(KASUGAI Canvas)

QGIS 内のデータを KASUGAI Canvas(.kasc+canvas_data/)で最適に再生できる形式へ変換し、レイヤ追加まで行う手順。
use_when: ユーザーがデータ形式の変換・レイヤ追加・WebGIS/Canvas 向けのデータ準備・公開用データ作成を依頼したとき

## 基本方針(サーバレス優先)

- **変換サーバーを立てない**。変換は QGIS 内の processing(GDAL/ネイティブ)で完結させ、出力は「静的ホスティング+ブラウザ内デコード」できる形式を選ぶ
- KASUGAI Canvas はエンジン本体を CDN(kasugai-canvas-web)からも読めるため、**データ側も静的ファイルだけで配信できる**のが理想形
- 変換後のレイヤ追加までは `qgis_pyeval`、WebGIS への送出・起動は `qgis_bridge_call` → geo_webview `kasugaiExport` を使う

## 形式選定表

変換先は用途と規模で決める。「そのまま置いて Canvas が読める形式」を優先し、安易に GeoJSON 化しない。

### ベクター出力形式スイッチ(vector_format)

エクスポート全体のベクター出力方針を切り替えるモード。
パネルの **Format:** コンボ、設定ダイアログの
**Vector Export Format** コンボ(`kasugai_vector_format`)、
`GET /kasugai?fmt=native|recommended|geojson`、
bridge `kasugaiExport(vector_format=...)` の4経路で切替。

- **recommended**: gpkg/geojson/shp/csv/kml/wfs 等のソースは
  すべて FlatGeobuf へ EPSG:4326 で変換し canvas_data/ へ配置(`flatgeobuf:` 行)。
  既に FlatGeobuf/GeoParquet のソースは参照維持
  (`flatgeobuf:`/`geoparquet:`/`duckdb:+format=parquet` 行)。
  subsetString・fields/where/limit は変換データへ焼き込まれる
- **native(既定)**: 読めるソースはそのまま参照
  (`gpkg:`/`geojson:`/`shp:`/`wfs:`/`duckdb:` 行)、
  非ネイティブ形式のみ FlatGeobuf 変換
- **geojson(WEB連携)**: 全ベクター(FGB/GeoParquet ソース含む)を
  GeoJSON(EPSG:4326)へ変換し canvas_data/ へ `geojson:` 行で配置。
  canvas_data/ が全て GeoJSON になるため Canvas 以外の WebGIS・
  GIS ツールでもそのまま読める相互運用向けモード

| ソース/目的 | 推奨出力 | .kasc 行 | 理由 |
|---|---|---|---|
| 小〜中規模ベクター(数千地物) | FlatGeobuf(.fgb) — **既定フォールバック** | `flatgeobuf:` | エクスポート既定の変換先。空間インデックス付きバイナリで GeoJSON より小さく速い。ドライバ非搭載時は Parquet→GeoJSON の順にフォールバック。**`bbox=auto` が既定 ON**で表示範囲のみをインデックス+HTTP Range で読むクエリ系。全件描画したい場合は `bbox=off` を付ける |
| 中〜大規模ベクター(数万地物〜) | **GeoParquet(.parquet)** or FlatGeobuf(.fgb) | `geoparquet:`/`flatgeobuf:` | ブラウザ内バイナリデコードで速い・変換不要で置くだけ。GeoJSON 化は避ける。`flatgeobuf:` は `bbox=auto` 既定 ON で空間インデックス+Range の範囲読み(索引なし・Range 非対応サーバーは全件へフォールバック)、`geoparquet:` は全件読み込み(範囲読みは `duckdb:` 経路) |
| 大規模+条件絞込み/範囲連動 | GeoParquet + `duckdb:` | `duckdb:`(where=/bbox=auto) | 「見ている範囲だけ読む」。DuckDB-WASM 初回ロード約60MBは SW キャッシュで緩和 |
| 正データ管理・複数テーブル共有 | GeoPackage(.gpkg) | `gpkg:`+`table=` | sql.js Worker が直接読む。**地理座標系(EPSG:4326等)必須** |
| CSV/TSV(緯度経度/WKT列) | そのまま or .csv複製 | `duckdb:`+`lon=`/`lat=`/`geom=` | delimitedtext の xField/yField/wktField を継承 |
| ローカルラスタ(DEM/オルソ等) | XYZタイル か COG | `xyz:`/`geotiff:` | **エクスポートはローカルラスタを skipped する**ので事前にタイル化/COG化が必要 |
| WMSラスタ | そのまま(URL) | `wms:` | 接続URIから自動で行生成 |
| 3Dモデル/点群/建物 | 3D Tiles | `3dtiles:` | http(s)はURL参照、ローカルはcanvas_data/へ複製(1GiB上限) |
| フィルタ(subsetString)付き | 形式ごとに維持 | `where=`(gpkg/duckdbはSQL実行、geojson/geoparquet/flatgeobufはCanvas側where-eval.jsのOGR SQL WHERE句評価) / `duckdb:`(ローカルparquet) / `ogrsql:`(WHERE句に留まらずSELECT全文が必要な場合。QGIS検出時はGDAL本体のogr.ExecuteSQLで実行) / FlatGeobuf変換(where-eval非対応式のみ・フォールバック時GeoJSON) | フィルタを変質させない経路を選ぶ。`where=` は全ベクター行で利用可(式は OGR SQL WHERE 句)。**where= は行の最終オプションで値は改行まで**(式中の `|`・`||` 可。off や他 key=value は where= の前に置く)。`||` 連結は where-eval 対応済みで geojson/fgb/geoparquet でもそのまま送出。単独 `|`(ビット演算)・`%` は where-eval 非対応のため FlatGeobuf 変換へ回る |
| 非地理座標系(平面直角等) | **EPSG:4326へ必ず再投影** | — | `gpkg:`ネイティブ参照もGeoJSON変換も地理座標系が前提 |

## 変換→レイヤ追加のレシピ(qgis_pyeval)

`processing.run` は GUI スレッドで同期実行。大きいデータは QGIS が一時的に固まる旨をユーザーに断る。

```python
import processing
from qgis.core import QgsVectorLayer, QgsProject, QgsCoordinateReferenceSystem

# 1) 形式変換(拡張子で出力ドライバが決まる。GeoParquetはGDAL3.5+)
processing.run("native:savefeatures", {
    "INPUT": "ソースレイヤ名またはパス",
    "OUTPUT": "C:/out/layer.parquet",   # .gpkg/.geojson/.fgb も可
})

# 2) 座標系が非地理座標系なら先に EPSG:4326 へ
processing.run("native:reprojectlayer", {
    "INPUT": "...",
    "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:4326"),
    "OUTPUT": "C:/out/layer_4326.parquet",
})

# 3) ラスタ→XYZタイル(エクスポート対象にする唯一のローカルラスタ経路)
processing.run("native:tilesxyzdirectory", {
    "EXTENT": "xmin,ymin,xmax,ymax", "ZOOM_MIN": 8, "ZOOM_MAX": 16,
    "DPI": 96, "OUTPUT_DIRECTORY": "C:/out/tiles",
})

# 4) レイヤ追加
lyr = QgsVectorLayer("C:/out/layer.parquet", "名称", "ogr")
QgsProject.instance().addMapLayer(lyr)
```

- **追加後の整理**: `qgis_bridge_call` → geo_driver `placeLayer`/`organizeLayers` で layer_org サービスの標準配置(グループ・リネーム・.qml適用)を使う。WebGIS 側のグループ/凡例構成にそのまま反映される

## 凡例・テキスト再現性の制約(Canvas 側)

Canvas の .qml コンパイラ(web/shared/qml-style.js)の対応範囲。**再現したい表現がこの範囲を外れるなら、QGIS 側で単純化してからエクスポートする**:

- **レンダラ**: 単一/分類(categorized)/段階(graduated)/ルールベースは対応。`invertedPolygon`は近似、`heatmap`は対応エンジンのみ、`pointDisplacement`は中心点近似、その他(25d等)は既定スタイルへフォールバック
- **シンボル**: SvgMarker 等の画像は canvas_data/ へ複製されるが、パス解釈不能なものはフォールバック。`AnimatedMarker`=先頭フレーム静止画。`GeometryGenerator` は常用関数(buffer/translate/centroid/exterior_ring/boundary/convex_hull/envelope)のみ近似、それ以外はスキップ
- **ラベル**: 配置は重心/周囲の近似。`mergeLines`・未配置表示・HTML書式・タブストップ・縦書き(水平代替)・fontSizeMapUnitScale(固定値近似)・ラベル背景画像(矩形代替)・ブレンドモードは未対応/近似。**複雑な注記は QGIS 側で単純化するか、文字列入れ替え前に確定させる**
- **縮尺表示**: レイヤの「縮尺による表示」は `minScale=`/`maxScale=` としてそのまま維持される。WebGIS でも同じ切替になるので、変換時に適切な縮尺帯を設定しておく
- **データ定義プロパティ**: 式の一部のみ評価可。複雑な式は事前に静的な値へ置き換える

## エンジン選択(kasugaiExport の engine 引数)

Canvas のエンジンは `cesium`/`maplibre`/`openlayers`/`leaflet`/`gsimaps`/`navara`。ライブラリ自体の一般知識は前提としてよいが、**エンジン別の .kasc 対応差は KASUGAI Canvas 固有**なので以下に従う:

- **`cesium`(既定・推奨)**: QML 再現が最も忠実(`qml-style.js`+`cesium/qml-render.js`、ラベルデクラッター付)。`3dtiles:`/`terrain:`/`scene3d:`/`cam:` の pitch・heading は **cesium 専用**。
  起動時ポータル(`portal:`/`html:`/`view:`/`link:` 行=開始画面+目的別ビューカード+外部リンクカード)は **全エンジン対応**(cesium/maplibre/openlayers/leaflet/gsimaps/navara)。`view:` は .kasc 直接記述で定義し `;where=`/`;style=`・`cam=`/`base=`/`desc=`/`img=` を束ね、`link:` は `url=` で外部サイトカードになる。`portal: … | html=ファイル/URL` でポータル全体を1つのHTMLで構成するフルカスタムモードもあり(HTML内の `data-view=ビュー名`/`data-link=URL`/`data-cam=カメラ名`/`data-base=背景名`/`data-clear`/`data-close` 属性がGIS操作として動く)(export 側の自動生成は未対応・.kasc を編集して作る。gsimaps/navara は `;style=` 未対応等の機能差あり)
- **`maplibre`**: ベクタータイル主体なら選択肢。2D QML 適用+ラベル焼き込み(`bakeQmlLabels`)
- **`openlayers`/`leaflet`**: 2D 汎用/軽量。QML は qml-2d.js 経由で近似度は cesium より低い(leaflet はマーカーを canvas 描画)
- **`gsimaps`/`navara`**: 地理院地図系・産総研系のニッチエンジン。凡例/スタイルの対応は限定的。指定された場合のみ使い、能力差をユーザーへ断る

迷ったら `cesium`。2D専用・軽量重視・エンジン固定の要件が明示された時だけ他を選ぶ。

## 高速化チェックリスト

大きい/重いデータは「形式」だけでなく、データ削減・描画抑制・転送最適化の3方向で対処する。

### データ量の削減(QGIS 側の前処理)

- **ジオメトリ簡略化**: `native:simplifygeometries`(tolerance は表示縮尺に合わせる)。境界線系の GeoJSON 化では効果が大きい
- **不要列の削除**: `native:retainfields` で凡例・ラベル・検索に使う列だけ残す。属性列は転送量とパース時間に直結
- **座標精度**: `native:savefeatures` の layerOptions(`COORDINATE_PRECISION=5` 程度=約1m)で GeoJSON を軽くできる(GDAL 側オプション)
- **空間ソート**: GeoParquet/FlatGeobuf を書く前に地域順・ヒルベルト的な並びにすると duckdb: 範囲絞込みやタイル描画の局所性が上がる
- **FlatGeobuf は空間インデックス必須** — インデックスがあると HTTP Range リクエストで「見る範囲だけ」読める(GDAL は既定で書く)。PMTiles/COG も同様に Range 対応ホスト前提
- **超大規模ベクターはベクタータイル化**: `native:vectortilesmbtiles`/`native:vectortilesxyz` で mbtiles/ディレクトリタイル化 → `mvt:`/`pmtiles:` 行。数万〜の描画をタイル配信に逃がす最終手段

### 描画側の抑制(.kasc オプション。エクスポート後の行編集またはCanvas側機能)

- **`cluster=on`**: 密集ポイントは件数バッジでクラスタ表示(cesium。QML の pointCluster からも自動ON。Leaflet は `clusterradius=`/`clusterdisableat=`/`clustercoverage=off`/`clusterspiderfy=off`/`clusterchunked=on` で調整可・QML tolerance も引き継ぐ)
- **`heat=`**: ポイント密度が主題ならヒートマップ化で個別描画を省略(Leaflet は `heatradius=`/`heatblur=`/`heatminopacity=`/`heatmaxzoom=`/`heatmax=`/`heatgradient=` で調整可・QML heatmapRenderer の radius/weight_expression/maximum_value/colorramp を引き継ぐ)
- **Leaflet 固有**: `renderer=canvas`(L.canvas 切替・大量地物)・`fillrule=`・`smoothfactor=`・`noclip=`・`classname=`(ベクター)、`tms=`/`detectretina=`/`zoomoffset=`/`subdomains=`/`errortileurl=`/`nowrap=`/`crossorigin=`/`referrerpolicy=`(タイル系)、`uppercase=`/`crs=EPSG4326`(wms:)、`alt=`/`interactive=`/`erroroverlayurl=`(image:)。地図初期値は URL `?zoomsnap=/zoomdelta=/minzoom=/maxzoom=/maxbounds=/worldcopyjump=/prefercanvas=`。詳細は Canvas `docs/use/6-2-インスペクター.html`
- **MapLibre 固有**: ラスタ系行(`base:`/`xyz:`/`wms:`/`wmts:`/`image:`)に色調整 opts — `brightness=`(-1..1 ショートハンド)/`brightness-min=`/`brightness-max=`/`contrast=`/`hue=`/`saturation=`/`resampling=linear|nearest`/`fade-duration=`。`terrain:` 行は `exaggeration=` に加え `url=`(TileJSON または `{z}/{x}/{y}` テンプレート)+`encoding=`、`shading=on|relief|both`(DEM 共有の hillshade/color-relief レイヤ。3D地形なしでも可)、`generator=flat` を解釈。`light:` 行(az=/el=/intensity=/color=)は `map.setLight` へ反映(hillshade/fill-extrusion の照明)。表示設定に地球儀投影(globe)切替・陰影/段彩トグルあり、`scene3d:` の `background=` は globe 時の sky-color へ反映
- **`bbox=`/`bounds=`/`extent=`**: 描画範囲を限定して範囲外のタイル取得・描画を止める
- **`minZoom=`/`maxZoom=`**(タイル系)と **`minScale=`/`maxScale=`**(レイヤ縮尺): 見せる範囲・縮尺帯を絞る。重いレイヤと軽いレイヤを縮尺で切替える構成が最も効く
- **ラベル**: cesium はデクラッター内蔵。逆に全件ラベルは重いので、ラベル用レイヤと地物レイヤを分けて縮尺帯で切替

### 転送・配信の最適化

- **バイナリ形式優先**: GeoJSON はテキスト解析が重い。GeoParquet/FlatGeobuf/PMTiles は転送量・デコード共に軽い
- **タイル画像の形式**: 写真系は JPEG、線画・透過ありは PNG(`format=`/`transparent=`)
- **Range リクエスト対応ホスト**を選ぶ: FlatGeobuf/PMTiles/COG/duckdb: の効果は Range 対応(GitHub Pages/S3/CloudFront 等)が前提。Range 非対応だと全量ダウンロードになる

## 送出・検証ループ

1. 変換→追加→(必要なら placeLayer で整理)
2. `qgis_bridge_call` → geo_webview `kasugaiExport(engine="cesium", open_app=True)` などでエクスポート&起動
3. **応答の `warnings`/`skipped` を必ず確認** — 未対応レンダラ・解決不能なシンボル・スキップされたレイヤがここに出る。残っていれば変換側を調整して再エクスポート
4. `qgis_screenshot` または Canvas 側で表示確認(色・凡例・ラベル・縮尺帯)

## サイズ・配信の目安

- **GitHub Pages 等の静的ホスト: 1ファイル100MB 上限**。大きいデータは URL 直参照かタイル化/分割する
- ローカル 3D Tiles / XYZ タイルの canvas_data/ 複製: **1GiB 上限**(超過は skipped)
- DuckDB-WASM 初回ロード約60MBは Service Worker がブラウザ内に永続キャッシュするため、2回目以降は軽い
- 完全サーバレス公開: エクスポート物を静的ホスト(例: kasugai_canvas_webGIS)へ置き、CDN 版エンジンを `…/<channel>/<engine>/?kasc=<.kasc URL>` で開く
