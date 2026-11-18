> **QGIS Live Harness の中核ドライバ** — [QGIS Live Harness](https://yamamoto-ryuzo.github.io/qgis_live_harness/) · [プラグイン一覧](https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html) · [ドキュメント](https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_driver/docs) · [リポジトリ](https://github.com/yamamoto-ryuzo/qgis_live_harness)

# QGIS Live Driver (`geo_driver`)

**📖 日本語ドキュメント: <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_driver/docs>**
（インストール・使い方・仕様の詳細はこちら）

## Overview

A UI-less, control-only plugin that lets clients on the **same PC** (AI
tools, etc.) remotely operate a running QGIS process. It exposes QGIS
internals (`iface`, `QgsProject`, map canvas) as automation primitives
over file-JSONL, REST (`/api/*`) and MCP (`/mcp`).

## Features

- `pyeval` / `eval` / `screenshot` / `devreload` / `bridge_call` /
  `describe_plugins` primitives for remote control of all managed plugins
- Embedded HTTP server (`/api/*` REST + `/mcp` Streamable HTTP) and
  bundled stdio MCP shim (`mcp_stdio.py`)
- Built-in AI assistant panel (OpenAI-compatible / Anthropic / Gemini /
  Azure OpenAI / GitHub Copilot / ACP agents) with tool-loop execution
- Hot reload of managed plugins, GeoSuite shared toolbar (mode badge),
  layer_org layer-organization service, Deploy Mode switching

## Links

- Documentation (JA): <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_driver/docs>
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
