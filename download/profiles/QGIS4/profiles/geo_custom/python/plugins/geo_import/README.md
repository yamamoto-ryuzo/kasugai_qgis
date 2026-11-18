> **QGIS Live Harness のプラグイン** — [QGIS Live Harness](https://yamamoto-ryuzo.github.io/qgis_live_harness/) · [プラグイン一覧](https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html) · [ドキュメント](https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_import/docs) · [リポジトリ](https://github.com/yamamoto-ryuzo/qgis_live_harness)

# QGIS Data Catalog Integration (`geo_import`)

**📖 日本語ドキュメント: <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_import/docs>**
（インストール・使い方・仕様の詳細はこちら）

## Overview

An enhanced version of the QGIS Data Catalog Integration plugin.
Searches CKAN and other open-data portals (data.go.jp, G-Space
Information Center, Tokyo Metropolitan open data catalog, GSJ Linked
Data, etc.) and adds datasets directly to QGIS.

## Features

- Search/filter datasets on CKAN portals by keyword, category and format
- Local folder / SQLite cache with category filtering
- Automatic CSV delimiter detection (comma/semicolon/tab/colon/space)
  and encoding detection (UTF-8/CP932)
- Automatic point geometry creation from lat/lon CSV columns
- GSJ Linked Data "map info (JSON)" / TileJSON resources added as XYZ
  tile layers
- Added layers are handed to the layer_org service (flat fallback when
  `geo_driver` is not loaded)

## Links

- Documentation (JA): <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_import/docs>
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
