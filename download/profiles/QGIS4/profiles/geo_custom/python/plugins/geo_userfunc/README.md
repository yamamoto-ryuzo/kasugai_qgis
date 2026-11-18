> **QGIS Live Harness のプラグイン** — [QGIS Live Harness](https://yamamoto-ryuzo.github.io/qgis_live_harness/) · [プラグイン一覧](https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html) · [ドキュメント](https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_userfunc/docs) · [リポジトリ](https://github.com/yamamoto-ryuzo/qgis_live_harness)

# geo_userfunc

**📖 日本語ドキュメント: <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_userfunc/docs>**
（インストール・使い方・仕様の詳細はこちら）

## Overview

Library manager for user-defined Python code in QGIS. `*.py` files in
`<profile>/python/geo_userfunc/` are classified by AST analysis and
registered by type: `@qgsfunction` functions go to the expression
engine, `openProject`/`saveProject`/`closeProject` hooks are wired to
project signals, and `main(context)` macros become menu/bridge targets.

## Features

- User function/macro library with enable/disable, edit, reload and
  fetch-from-URL management dialog
- Shared registry so other plugins' macros are managed in one place
- AI can discover, author, register and verify functions via `geo_driver`
  `bridge_call` (`listFunctions` / `listMacros` / `run` /
  `evalExpression` / `saveFunction` / `reload` / ...)

## Links

- Documentation (JA): <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_userfunc/docs>
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
