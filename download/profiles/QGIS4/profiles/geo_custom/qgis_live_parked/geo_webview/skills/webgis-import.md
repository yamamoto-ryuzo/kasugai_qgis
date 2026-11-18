# 既存 WebGIS の QGIS への取り込み

既存の WebGIS(KASUGAI Canvas の .kasc+DATA/、XYZ/WMS/WFS 等の Web 地図ソース、MapLibre style.json)を QGIS プロジェクトへ再構成し、kasugaiExport で Canvas へ再送出する手順。
use_when: ユーザーが既存 WebGIS/.kasc の QGIS への取り込み・変換・Canvas への移行を依頼したとき

## 基本方針

- **QGIS を「万能アダプタ」として使う**。Web 側のソースはほぼ GDAL/OGR か QgsRasterLayer/QgsVectorLayer/QgsVectorTileLayer/QgsTiledSceneLayer で読める
- 取り込み → 確認/調整 → `kasugaiExport` で再送出、が「既存 WebGIS → KASUGAI Canvas」変換の往路。往路の形式変換・スタイル制約は `webgis-convert` スキルに従う
- `.kasc` が正本の場合は専用ブリッジ(`kascInspect`/`kascImport`)を最優先で使う。個別ソースの拾い上げは `qgis_pyeval` レシピで対応

## .kasc+DATA/ の取り込み(最優先)

```
qgis_bridge_call plugin_id="geo_webview" method="kascInspect"
                 args=["<.kasc パス or URL>"]
```
dry run。行タイプ別集計・参照解決・未対応行を確認してから実行する。

```
qgis_bridge_call plugin_id="geo_webview" method="kascImport"
                 args=[{"source": "<.kasc パス or URL>",
                        "add_to_project": true,
                        "only_visible": false,
                        "apply_camera": true,
                        "group_prefix": "取込み",
                        "replace": true}]
```

- **`replace: true` を推奨** — 同じ .kasc の再取り込みで前回分が残らない(取込レイヤは `kasc_source` カスタムプロパティで識別され、前回分+空の取込グループを除去してから追加。応答の `replaced` に除去数)。`false` なら従来通り追加重複する

復元されるもの:

- **レイヤ**: `xyz:`/`base:`→XYZ、`wms:`/`wmts:`→WMS、`geojson:`/`gpkg:`/`geoparquet:`/`flatgeobuf:`/`shp:`/`kml:`→ベクター、`duckdb:`/`csv:`/`tsv:`→delimitedtext(ローカル)、`mvt:`/`pmtiles:`→ベクタータイル、`3dtiles:`→TiledScene、`geotiff:`/`image:`→ラスタ、`fly_geojson:`→ベクター
- **表示設定**: `style=`(.qml・リモートは一時DLで適用)・`minScale=`/`maxScale=`(縮尺表示)・`opacity=`・`where=`→subsetString・`attr=`/裸出典→attribution・`bbox=`→マップクリッピング領域・`| off`・タイトルの `/` → グループ(`//`=排他)・`group:` 折りたたみ・`theme:`→マップテーマ(タイトルはNFKC正規化+リーフ名照合)・`bookmark:`→ブックマーク・`cam:`→キャンバス中心/縮尺/回転
- 応答の `skipped`/`warnings` を必ず確認 — Canvas専用オプション(extrude/time/heat/cluster)は未適用として列挙される

## .kasc 以外の Web ソース(qgis_pyeval レシピ)

```python
from qgis.core import (QgsRasterLayer, QgsVectorLayer,
                       QgsVectorTileLayer, QgsTiledSceneLayer,
                       QgsProject, QgsRectangle, QgsCoordinateReferenceSystem)
from urllib.parse import quote

# XYZ タイル(url内&はエンコード必須。{z}は%7Bz%7Dでも可)
lyr = QgsRasterLayer(
    "type=xyz&url={0}&zmin=2&zmax=18".format(
        quote("https://example.com/{z}/{x}/{y}.png", safe="")),
    "背景図", "wms")

# WMS(uri は url= を最後に)
QgsRasterLayer(
    "crs=EPSG:3857&format=image/png&layers=ortho&styles=&url=https://example.com/wms",
    "オルソ", "wms")

# WFS(ogr経路)
QgsVectorLayer("WFS:https://example.com/wfs", "地物", "ogr")

# ArcGIS REST(FeatureServer/MapServer)
QgsVectorLayer(
    "url='https://example.com/arcgis/rest/services/X/FeatureServer/0'",
    "フィーチャ", "arcgisfeatureserver")
QgsRasterLayer(
    "crs=EPSG:3857&format=PNG32&url=https://example.com/arcgis/rest/services/X/MapServer",
    "マップ", "arcgismapserver")

# ベクタータイル(MVT/PMTiles)
QgsVectorTileLayer(
    "type=xyz&url={0}&zmin=0&zmax=14".format(quote("https://example.com/{z}/{x}/{y}.mvt", safe="")),
    "MVT")

# 3D Tiles / 点群
QgsTiledSceneLayer("https://example.com/tileset.json", "建物", "tiledscene")
QgsPointCloudLayer("https://example.com/ept.json", "点群", "ept")

QgsProject.instance().addMapLayer(lyr)
```

- **MapLibre `style.json`**: `sources` エントリごとに上の行を作る(raster→XYZ、vector→MVT、geojson→QgsVectorLayer)。`layers` の paint プロパティは QGIS シンボロジへ近似する(単純な fill/line/circle 色・幅のみ。`interpolate`/`match` 式は最頻値へ畳み込むか単一化)。複雑なスタイルは近似でよい旨ユーザーへ断る
- **縮尺表示**: Web 側のズーム帯(minzoom/maxzoom)は分母へ換算して `setScaleBasedVisibility(True)`+`setMinimumScale`/`setMaximumScale`。概算 `scale ≈ 559082264 / 2^zoom`(EPSG:3857・96dpi)
- 追加後は `qgis_bridge_call` → geo_driver `placeLayer`/`organizeLayers` で layer_org 標準配置へ載せる

## 検証と再送出

1. 取り込み → `qgis_screenshot` で元の WebGIS と見比べ(色・順序・表示)
2. `kascInspect`/`kascImport` の `skipped`/`warnings` を確認し、未対応ソースは個別レシピで補う
3. `qgis_bridge_call` → geo_webview `kasugaiExport` で `.kasc`+`DATA/` へ再送出(`webgis-convert` スキルの形式選定表・凡例/テキスト制約に従う)
4. 往復差分(失われたオプション・近似されたスタイル)をユーザーへ報告
