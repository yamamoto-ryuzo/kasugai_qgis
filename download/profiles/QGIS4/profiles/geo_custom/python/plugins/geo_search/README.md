> **QGIS Live Harness のプラグイン** — [QGIS Live Harness](https://yamamoto-ryuzo.github.io/qgis_live_harness/) · [プラグイン一覧](https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html) · [ドキュメント](https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_search/docs) · [リポジトリ](https://github.com/yamamoto-ryuzo/qgis_live_harness)

# GEO Search System (`geo_search`)

**📖 日本語ドキュメント: <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_search/docs>**
（インストール・使い方・仕様の詳細はこちら）

## Overview

A map search system for QGIS. Searches layers, files and PostGIS
databases by lot number, owner name and arbitrary attributes, and shows
results in per-layer tabs with paging and field selection.

## Features

- Lot-number / owner-name / generic attribute search across QGIS
  layers, files and PostGIS
- Per-layer result tabs with paging and configurable display fields
- Map-theme switching on search (with "before search" restore) and an
  additive display mode that overlays results on the current view
- Tab-level search/display field configuration UI; `setting.json`
  for site defaults
- English / Japanese UI; QGIS 4.x (Qt6) compatible

## Detailed documentation (EN)

- [SEARCH.md](SEARCH.md) — search subsystem design and configuration
- [THEMES.md](THEMES.md) — theme/display management subsystem

## Links

- Documentation (JA): <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_search/docs>
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
