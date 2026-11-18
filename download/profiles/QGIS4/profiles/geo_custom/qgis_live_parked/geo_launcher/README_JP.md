# geo_launcher

[kasugai_qgis](https://github.com/yamamoto-ryuzo/kasugai_qgis) ランチャー(Rust/Axum 製)を QGIS 内からインストール/アンインストール・起動するためのプラグイン。

## 設計方針

kasugai_qgis は「QGIS を起動するための器」であり、QGIS を起動すれば本体は自動終了する(`/launch` 後にサーバ停止)。したがってこのプラグインは**インストールと引き継ぎのみ**を管理し、ランチャーの API サーバを起動・維持する機能は持たない。

## 機能

- **インストール / 再インストール** — GitHub Pages から `kasugai_qgis-setup.exe` をダウンロードして実行(`/S` サイレント可)。目立つ大ボタン。
- **アンインストール** — `qgis_launcher.exe` 隣の `uninstall.exe` を実行(`/S` 可)。目立つ大ボタン。
- **ランチャーを開く** — `qgis_launcher.exe` を GUI モード(WebView2 ウィンドウ)で起動。窓内でプロファイル/プロジェクトを選ぶと、本体が新しい QGIS を起動して自動終了する。
- **状態表示** — 検出した exe パス、バージョン(`qgis_launcher.exe --version`)、この QGIS がランチャー経由で起動したか(`PORTAL_USERROLE` のロール。本体が QGIS プロセスへ注入)。
- **設定** — exe パス上書き・サイレントインストール。
- **AI ブリッジ** — `geo_driver` の `bridge_call` / `describe_plugins` 経由で全機能を遠隔操作可能。

## インストール検出

`qgis_launcher.exe` は以下の順で解決:

1. QSettings `geo_launcher/exe_path`
2. `C:\kasugai\kasugai_qgis\qgis_launcher.exe`(NSIS 既定 InstallDir)
3. `C:\kasugai\*\qgis_launcher.exe` の glob

## 使い方

- GeoSuite ツールバーアイコン、または `プラグイン > geo_launcher > Kasugai QGIS Launcher` で状態パネルを開く
- `プラグイン > geo_launcher > ランチャーを開く` でランチャーの GUI ウィンドウを直接開く
- `設定...` で exe パス / サイレントインストールを設定

## Bridge API

`plugins['geo_launcher'].bridge.<method>`(`bridge_call` 経由):

`pluginInfo` / `status` / `isInstalled` / `launch` / `install(silent)` / `installStatus` / `uninstall(silent)` / `getSettings` / `setSettings` / `openDialog` / `openSettings` / `openDocs`

例(MCP): `qgis_bridge_call pluginId="geo_launcher" method="install"`

## ライセンス

GPL-3.0
