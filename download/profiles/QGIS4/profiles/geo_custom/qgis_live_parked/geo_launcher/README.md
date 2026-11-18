# geo_launcher

QGIS plugin that installs/uninstalls and opens the [kasugai_qgis](https://github.com/yamamoto-ryuzo/kasugai_qgis) launcher (Rust/Axum) from inside QGIS.

## Design principle

kasugai_qgis is a *launcher*: its job ends the moment it starts QGIS (it exits automatically after `/launch`). This plugin therefore manages **installation and handoff only** — it does not start or keep the launcher's API server alive.

## Features

- **Install / Reinstall** — downloads `kasugai_qgis-setup.exe` from GitHub Pages and runs it (silent `/S` optional). Large primary button.
- **Uninstall** — runs `uninstall.exe` next to `qgis_launcher.exe` (silent `/S` optional). Large primary button.
- **Open Launcher** — starts `qgis_launcher.exe` in GUI mode (WebView2 window); the user picks profile/project there, the launcher starts a new QGIS and exits by itself.
- **Status** — detected exe path, version (`qgis_launcher.exe --version`), and whether *this* QGIS was started via the launcher (`PORTAL_USERROLE` role, injected by the launcher into the QGIS process).
- **Settings** — exe path override, silent install.
- **AI bridge** — full remote control via `geo_driver` `bridge_call` / `describe_plugins`.

## Install detection

`qgis_launcher.exe` is resolved in this order:

1. QSettings `geo_launcher/exe_path`
2. `C:\kasugai\kasugai_qgis\qgis_launcher.exe` (NSIS default InstallDir)
3. `C:\kasugai\*\qgis_launcher.exe` glob

## Usage

- Toolbar (GeoSuite) icon or `Plugins > geo_launcher > Kasugai QGIS Launcher` opens the status panel
- `Plugins > geo_launcher > Open Launcher` opens the launcher's GUI window directly
- `Settings...` configures exe path / silent install

## Bridge API

`plugins['geo_launcher'].bridge.<method>` via `bridge_call`:

`pluginInfo` / `status` / `isInstalled` / `launch` / `install(silent)` / `installStatus` / `uninstall(silent)` / `getSettings` / `setSettings` / `openDialog` / `openSettings` / `openDocs`

Example (MCP): `qgis_bridge_call pluginId="geo_launcher" method="install"`

## License

GPL-3.0
