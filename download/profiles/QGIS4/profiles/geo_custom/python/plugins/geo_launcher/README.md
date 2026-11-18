> **QGIS Live Harness のプラグイン** — [QGIS Live Harness](https://yamamoto-ryuzo.github.io/qgis_live_harness/) · [プラグイン一覧](https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html) · [ドキュメント](https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_launcher/docs) · [リポジトリ](https://github.com/yamamoto-ryuzo/qgis_live_harness)

# geo_launcher

**📖 日本語ドキュメント: <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_launcher/docs>**
（インストール・使い方・仕様の詳細はこちら）

## Overview

QGIS plugin that installs/uninstalls and opens the
[kasugai_qgis](https://github.com/yamamoto-ryuzo/kasugai_qgis) launcher
(Rust/Axum) from inside QGIS. The launcher itself exits right after it
starts QGIS, so this plugin only manages installation and handoff —
it does not keep the launcher alive.

## Features

- **Install / Reinstall** — downloads `kasugai_qgis-setup.exe` and runs
  it (silent `/S` option)
- **Uninstall** — runs `uninstall.exe` next to `qgis_launcher.exe`
- **Open Launcher** — starts `qgis_launcher.exe` in GUI mode (WebView2)
- **Status** — detected exe path, version, and whether this QGIS was
  launched via the launcher (`PORTAL_USERROLE`)
- Full remote control via `geo_driver` `bridge_call` / `describe_plugins`

## Links

- Documentation (JA): <https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_launcher/docs>
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
