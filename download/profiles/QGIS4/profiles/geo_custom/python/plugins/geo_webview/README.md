> **QGIS Live Harness のプラグイン** — [QGIS Live Harness](https://yamamoto-ryuzo.github.io/qgis_live_harness/) · [プラグイン一覧](https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html) · [ドキュメント](https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_webview/docs) · [リポジトリ](https://github.com/yamamoto-ryuzo/qgis_live_harness)

# geo_webview — Serverless web distribution for QGIS (multi-engine)

**📖 日本語ドキュメント: <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_webview/docs>**
（インストール・使い方・仕様の詳細はこちら。パネルの `?` ボタンからも開けます）

## Overview

Exports the open QGIS project as a `.kasc`+`canvas_data/` package playable on
the KASUGAI Canvas multi-engines (Cesium / MapLibre / OpenLayers /
Leaflet / GSI Maps / Navara). The output runs on plain static hosting —
no server-side code required.

## Features

- Layer-tree export to `.kasc`+`canvas_data/` (GeoJSON / native GPKG・GeoJSON・
  GeoParquet・FlatGeobuf references, `.qml` styles, XYZ tiles)
- Register & switch projects on a running KASUGAI Canvas (port 8510)
- Embedded HTTP server (default 8089): `/kasugai` export entry,
  `/export-data/` static delivery, `/present`・`/screenshot` sharing,
  `/live/*` live two-way sync, permalink reception (`/qgis-map`)
- Permalinks that restore map state (center, scale, layers, themes)
- AI bridge (`kasugaiExport` / `kascInspect` / `kascImport`) for remote
  control via `geo_driver`

## Detailed documentation (EN)

- [SPEC.md](SPEC.md) — `.kasc` line spec, API and bridge reference
- [INTEGRATION.md](INTEGRATION.md) — external client integration policy
  (Re:Earth / ArcGIS)

## Links

- Documentation (JA): <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_webview/docs>
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- License: GPL-3.0 ([LICENSE](LICENSE))

## Disclaimer

This software was created and tested on a personal PC.
No liability is accepted for any damages arising from its use.

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>
