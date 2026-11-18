> **QGIS Live Harness のプラグイン** — [QGIS Live Harness](https://yamamoto-ryuzo.github.io/qgis_live_harness/) · [プラグイン一覧](https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html) · [ドキュメント](https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_excel/docs) · [リポジトリ](https://github.com/yamamoto-ryuzo/qgis_live_harness)

# geo_excel

**📖 日本語ドキュメント: <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_excel/docs>**
（インストール・使い方・仕様の詳細はこちら）

## Overview

A lightweight wrapper plugin that turns the layer-action scripts from
[QGIS-exportExcel](https://github.com/yamamoto-ryuzo/QGIS-exportExcel)
into a proper QGIS plugin: run Excel report outputs for the active layer
or selected features directly from the plugin menu.

## Features

- Run bundled report scripts on the active layer / selected features
  (`[% @layer_id %]` / `[% $id %]` substitution at run time)
- Layer variables (`xlsout_*`, dpi) and settings dialog for defaults
- Shared-registry integration with `geo_userfunc` (report macros are
  registered in the common macro registry when it is loaded)
- Full remote control via `geo_driver` `bridge_call` / `describe_plugins`

## Requirements

Windows + Microsoft Excel + `pywin32` (win32com)

## Links

- Documentation (JA): <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_excel/docs>
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
