# 地名・住所への地図移動(geo_search searchAddress)

地名・住所・施設名・座標で地図ビューを移動する手順。
use_when: ユーザーが「◯◯へ移動」「◯◯にズーム」「◯◯を表示」「◯◯へ飛んで」など、場所を指定した地図移動を依頼したとき

## 基本方針

- 場所名での移動は `qgis_bridge_call` → `plugin_id="geo_search"`、
  `method="searchAddress"` を使う。ジオコーディング(既定=国土地理院 gsi)
  → 結果ポイントの地図表示 → ズームまで一括で行い、CRS変換も内部で処理される
- 座標をハードコードした setCenter は避ける。プロバイダが実際の位置を引くため
  「東京」「富士山」「東京タワー」等のあいまい指定もそのまま query へ渡せる
- 座標文字列(`35.6,139.7`・DMS・北緯/東経表記)もそのまま query に渡せる
  (ジオコーディングを通らず直接地点化される)

## searchAddress の引数

| 引数 | 既定 | 意味 |
|---|---|---|
| `query` | (必須) | 住所・地名・施設名、または座標文字列 |
| `provider` | 住所検索タブの設定(通常 gsi) | `gsi`(国土地理院・キー不要)/`osm`(Nominatim)/`google`/`yahoo`(要キー) |
| `zoom` | `true` | 先頭候補へズームするか |
| `createLayer` | 住所検索タブの設定 | `false` で結果スクラッチレイヤをプロジェクトへ追加しない |

```text
qgis_bridge_call geo_search searchAddress ["東京"]
qgis_bridge_call geo_search searchAddress ["東京都渋谷区宇田川町", "gsi"]
qgis_bridge_call geo_search searchAddress ["35.6812,139.7671"]
```

戻り値: `{ok, provider, count, results[{title,address,latitude,longitude}], zoomed}`

- 日本の住所・地名は gsi が最適。海外施設名で候補が薄い場合は osm を試す
- geo_search 未ロードの場合のみ pyeval 直操作へフォールバック(下記)

## 直接 canvas を動かす場合(フォールバック)

`QgsMapCanvas` に「ズームレベル」の API は無い(`setZoomLevel` は存在しない)。
以下を使う:

- `canvas.setCenter(QgsPointXY)` — 中心移動(**キャンバスCRSの座標**が必要)
- `canvas.zoomScale(50000)` — 縮尺分母で指定(1:50,000)
- `canvas.zoomByFactor(0.5)` — 相対ズーム
- `canvas.setExtent(QgsRectangle)` / `canvas.zoomToFeatureExtent(rect)` — 範囲指定
- `canvas.zoomToSelected(layer)` — 選択地物へフィット

緯度経度(EPSG:4326)で中心を動かすにはキャンバスCRSへの変換が必須
(平面直角等のプロジェクトで未変換だと別の場所へ飛ぶ):

```python
from qgis.core import (QgsPointXY, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsProject)

canvas = iface.mapCanvas()
xform = QgsCoordinateTransform(
    QgsCoordinateReferenceSystem("EPSG:4326"),
    canvas.mapSettings().destinationCrs(),
    QgsProject.instance())
canvas.setCenter(xform.transform(QgsPointXY(139.6917, 35.6895)))
canvas.zoomScale(50000)   # 1:50,000
canvas.refresh()
result = "moved"
```

- pyeval で値を返すには最後に `result` 変数へ代入する(未代入だと null)
- 移動後は `qgis_screenshot` で見た目を確認すると確実
