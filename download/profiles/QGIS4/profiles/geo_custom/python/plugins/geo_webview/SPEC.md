# geo_webview — Specification

[日本語: docs/spec.html](https://github.com/yamamoto-ryuzo/qgis_live_harness/blob/master/qgis-plugin/geo_webview/docs/spec.html)

This specification formalizes the features described in the repository README and CHANGELOG. It is organized to match the Japanese `docs/spec.html`: an **overview** first, then per-**panel-tab** sections (Web / Live / Layers / Filter / XYZ / Other, plus the panel footer), and finally cross-tab common specifications (HTTP API, CRS, security, testing, file mapping). It targets implementers, operators and testers of the `geo_webview` plugin.

Purpose and scope
- Purpose: Define the expected behavior of the `geo_webview` plugin for implementation, operation and testing.
- Scope: **serverless web distribution (main feature)** — exporting the open QGIS project as `.kasc`+`canvas_data/` for the KASUGAI Canvas multi-engine players (Cesium/MapLibre/OpenLayers/Leaflet/GSI Maps/Navara); Canvas Live View (`/live/*` bidirectional sync); the embedded HTTP server (`/kasugai`, `/export-data/`, `/present`, `/screenshot`, permalink reception) as the supporting side; permalink generation/navigation, theme application, site filter / XYZ tile baking / custom-layer tab, External Control behavior, CRS policy, and security/operational considerations.

## 0. Overview — the whole picture

`geo_webview` is the **bridge plugin between QGIS and KASUGAI Canvas** (a multi-engine WebGIS: Cesium/MapLibre/OpenLayers/Leaflet/GSI Maps/Navara). It provides two pillars for showing the current QGIS project in Canvas:

1. **Serverless web distribution (export)** — writes the project layer tree as a `.kasc`+`canvas_data/` package playable on any static host or the Canvas app (§1 Web tab).
2. **Canvas Live View (bidirectional sync)** — `GET /live/kasc` generates the .kasc on demand from the live project (no export needed), and edits/view/selection/visibility sync both ways (§2 Live tab).

Canvas is not merely a web player for QGIS — it also serves as the **fast main viewer for heavy content such as 3D Tiles** (QGIS = edit/generate, Canvas = display). Since QGIS4's embedded WebView cannot run WebGL, display is consolidated to an external browser (the embedded dock was removed in v4.31).

Both pillars share a single **embedded HTTP server** (default ports 8089-8099, bound to `0.0.0.0` for designed LAN sharing) that serves export files (`/export-data/`), the live API (`/live/*`), screen sharing (`/present`/`/screenshot`), permalink reception (`/qgis-map`) and the Canvas `web/` fallback (`/<engine>/`). See §8 for the endpoint list.

Panel tab layout (`panel_base.ui` `tabWidget_main`, tabs on the bottom edge; the Live tab is generated in code and inserted right after Web):

| Tab | Role | Spec |
|---|---|---|
| **Web** | .kasc export, Canvas launch, HTTP server control (main serverless distribution UI) | §1 |
| **Live** | Resident Live View launch + bidirectional controls (follow/selection/qgis_follow, Add to Canvas) | §2 |
| **Layers** | Per-layer .kasc options (site/order/list/opts) and the custom-layer tab | §3 |
| **Filter** | Apply a common attribute filter (subset string) to every layer of a site | §4 |
| **XYZ** | Vector→XYZ tile baking (auto/manual) and basemap groups | §5 |
| **Other** | Map themes, permalink generation/navigation, presentation sharing (`/present`), MAC auth | §6 |
| (footer, outside tabs) | External Control toggle, settings dialog (gear) | §7 |

## 1. Web tab — serverless web distribution (main feature)

The Web tab contains two groups:

- **Web Distribution (Serverless)** (`groupBox_webdist`) — `?` help, `Export` (files only), `ZIP` (download the export package), output-dir select/reset/open, **Format:** combo (native/recommended/geojson), **Visible data only** checkbox, **CDN:** combo (stable/unstable/canvas/custom) + custom (URL/FILE) field + `…` browse, **Engine:** combo (6 engines), `▶ WebView` (export→launch in browser), `Install KASUGAI Canvas`, `Canvas Customize` (the app's `/admin/` UI settings screen).
- **HTTP Server** (`groupBox_server`) — server status, `Enable` toggle, port spinbox (default 8089), `:80`/`:443` presets, `Check` (reachability diagnostics + firewall rule).

Launch routes: panel (`Export` = files only / `▶ WebView` = export→resolve CDN mode→launch, following the `CDN:` combo: `stable`/`unstable` = hosted kasugai-canvas-web engine, `canvas` = running Canvas app :8510, `custom` = custom http(s) URL or local web/ folder served at `/<engine>/`), `GET /kasugai`, and bridge `kasugaiExport`, with the `via` fallback chain (Canvas registration → `qgis-http` static serving → `hosted` → output only). Details: JA mirror §1 below.

- Embedded HTTP server (supporting): provides `/kasugai` `/export-data/` `/present` `/present/state` `/screenshot` `/received` `/layouts` `/layout-pdf` `/live/state` `GET /live/mcp-discover` `POST /live/mcp` `POST /live/camera` `POST /live/selection` `POST /live/writeback` `POST /live/features` `POST /live/controls` `GET /live/file/<path>` (OGC services removed in v3.29.0).

## 2. Live tab — Canvas Live View

The Live tab (`panel.py: _build_live_tab`, inserted after Web) holds the **Canvas Live** group: engine combo + `Open Live View`, `Follow QGIS canvas` / `Show QGIS selection` / `Follow Canvas view` checkboxes (`live.controls`, source of truth = QSettings), a layer combo + `Add to Canvas`, and a status label.

- **Live bidirectional sync (v4.9.0)**: opt-in via QSettings `kasugai_live_sync` or bridge `liveSyncStart/Stop/Status/Flush` (`live_sync.py`). Layer edits/style/tree changes are debounced (1.2s) into a **delta re-export** (`export_kasugai_project(changed=…)` skips data/style file writes for unchanged layers; structural changes fall back to full export). Exports emit a `live: <base URL>` kasc line + `live.json` manifest ({rev, updated, changed:[{title,data,style}]}). Canvas polls `live.json` or receives a `liveSync` push via `/api/command` and reloads only changed layers when the .kasc text is unchanged. Reverse direction: `POST /live/camera` (Canvas view → canvas center/scale/rotation; accepts {lon,lat,zoom|scale|height,heading} or {bbox}; applied only while `live.controls.qgis_follow` is on — "Follow Canvas view" panel checkbox, default on — otherwise returns {applied:{enabled:false}}) and `POST /live/selection` (Canvas pick → QGIS layer select by ids/bbox/point+buffer_m), `POST /live/writeback` (Canvas visibility/filter/theme → QGIS project), `POST /live/features` (GeoJSON → scratch layers). The Live View engine URL (`Open Canvas Live View` / bridge `liveView` → `plugin.py:_live_url`) follows the Web tab `CDN:` combo mode: hosted modes (`stable`/`unstable`/custom http(s) URL) open the hosted engine + `/live/kasc` (no Canvas install needed); `canvas` uses the running Canvas app directly (:8510); a local **web/ folder path (FILE mode)** makes this server statically deliver that tree at `/<engine>/` (development / closed networks). `GET /live/state` returns sync state + canvas state (+ `live.qgis_selection` pushed on QGIS-side selection). On-demand GET APIs: `GET /live/layers` (catalog with kasc titles), `GET /live/features` (GeoJSON by layer/bbox/pt/limit — default 10000, max 20000, `offset=` paging), `GET /live/selection` (QGIS selection as GeoJSON), `GET /live/render` (EPSG:4326 bbox → PNG), `GET /live/style` (.qml on demand), `GET /live/file/<path>` (native source files).
- **Reverse authoring / data injection (v4.11.0)**: `POST /live/writeback` applies Canvas inspector state back to the project — `{layers:[{title,visible,where?}], theme?}`; `title` resolves via the same kasc-title normalization as selection, `visible` toggles the layer-tree node check (ancestors enabled when showing), `where` updates the vector provider subsetString, and `theme` applies a same-named map theme when present. Applied inside `LiveSyncController.suppress()` so the writeback does not trigger a redundant re-export. `POST /live/features` injects `{name, geojson: FeatureCollection|Feature[], replace?}` as memory scratch layer(s) — mixed geometry types are split, properties become fields via `QgsJsonUtils`, layers are tagged with custom property `kasugai_live_name` and added under a top "Canvas" layer-tree group; `replace` (default true) removes previously injected layers of the same name. The same logic is exposed to AI as bridge `liveWriteback(payload)` / `liveAddFeatures(name, geojson, replace)`.
- **Live Driver MCP relay (v4.12.0)**: `live_mcp.py`. Lets the CDN-hosted KASUGAI Canvas AI chat reach the QGIS Live Driver MCP tools (`qgis_pyeval` / `qgis_bridge_call` / `qgis_screenshot` …, including Processing analysis and other plugins' bridge methods) without the :8510 local app — the driver's `/mcp` itself is CORS-less + Bearer-protected and cannot be fetched directly from a browser. `GET /live/mcp-discover` scans the `~/.qgis-live/` registry and returns the relay URL to register (`http://127.0.0.1:<port>/live/mcp`); `POST /live/mcp` resolves the session on every request (auto-follows QGIS restarts) and forwards the JSON-RPC with the registry token attached server-side, propagating `Mcp-Session-Id` both ways (`Access-Control-Expose-Headers` added to the CORS response). Because `pyeval` is arbitrary code execution, the relay accepts **loopback TCP peers only** (unlike the other `/live/*` endpoints); browser-originated traffic is additionally constrained by the existing CORS allowlist.

## 3. Layers tab — custom-layer and per-layer options

Per-layer .kasc options editable in the layer table (`treeWidget_kasugai_layers`), persisted as layer customProperties and emitted as `| key=value` on each layer line: `site` (`kasugai_site` → `site=<name>`; group name auto-applied while the **Custom layers tab** checkbox is on), `order` (`kasugai_order` → `order=<n>`, set via the VIEW-mode ▲▼ buttons), `list` (`kasugai_list` → `list=off` hides the row from layer lists while still drawing the map), `opts` (`kasugai_opts` → arbitrary `key=value` additions such as `opacity=0.5 heat=on` or `legend_order=`). EDIT/VIEW buttons switch the table between option editing and output-preview/ordering.

When the **Custom layers tab** checkbox (QSettings `kasugai_site_control`, default OFF) is on, every `site=` layer additionally triggers a `plugin: custom-layer` line + `canvas_data/custom-layer.js` copy. On Canvas, `site=` layers are grouped into a dedicated custom tab (shown as "レイヤ") with per-group on/off and per-symbol legend toggles, while the standard tab keeps all layers (renamed "System layers"; use `list=off` to hide rows there). The `plugin:` line also carries the Filter tab selection as `filter_*` options (§4), which becomes the Canvas "フィルタ" tab's initial selection. Switch routes: panel checkbox / settings dialog (persistent), bridge `kasugaiExport(site_control=…)` (per-call). Details: JA mirror §3.

## 4. Filter tab — site common filter

The Filter tab (`panel.py: _init_kasugai_filter_ui`) applies a **common attribute filter (subset string) to all vector layers of a site** — sites resolved by the same rule as the Layers tab (`kasugai_site` customProperty / auto group names; ungrouped layers go to "その他"). The filter affects both the map display and exported data (a subsetString is carried to `where=` in .kasc rows).

- **Site:** combo lists site names (refreshed whenever the tab opens).
- **Field:** combo lists only attribute fields **common to all member layers** (numeric-in-all is suffixed `(num)`); shows `No common field` when none.
- **Condition row (auto-switched):** numeric fields get operators `= != < <= > >=` + a number input; text fields get `= !=` + a value combo of existing values. The **Multiple selection** checkbox switches to `IN`/`NOT IN` + a checklist of values (with select-all/none buttons).
- **Auto-apply:** the filter is applied as soon as site+field+value are complete (no apply button; text input is debounced 350 ms). An empty `IN` selection becomes the constant-false `1=0` (excludes everything); empty `NOT IN` clears the filter. Incomplete selections never apply.
- **Clear** removes the subset string from all site layers.
- **Export integration:** the selection state is continuously synced to `kasugai_export.set_filter_panel_state()` and emitted as `filter_*` options on the `plugin: custom-layer` line — the Canvas "フィルタ" tab's initial selection (see §3).

## 5. XYZ tab — tile baking and basemap groups

Three groups:

- **Vector → XYZ tile bake** — `XYZ tiles (faster display)` checkbox (QSettings `kasugai_xyz_tiles`, default ON) + zoom `zmin`/`zmax` (`kasugai_xyz_zmin`/`kasugai_xyz_zmax`, default 1-15): during .kasc export, vector layers that would be too heavy (large/feature-dense or complex styles) are baked to XYZ tile images by the QGIS renderer into `<slug>_xyz/` ({z}/{x}/{y}.png + index.html) under canvas_data/ and emitted as `xyz:` rows. Per-layer override: layer customProperty `kasugai_render` (`xyz` = always bake / `vector` = never bake / `auto`·blank = automatic). The zoom range is intersected with layer scale-visibility and clamped by a tile-count cap. Note: Canvas-side filters (`where=`/attribute filtering) do not affect the baked tile image.
- **Basemap Groups** — `lineEdit_xyz_basemap_groups` (QSettings `kasugai_basemap_groups`, comma-separated): additional layer-tree group names whose XYZ layers are all emitted as `base:` rows (basemap candidates), in addition to the built-in 背景図/ベースマップ/basemap names.
- **Standalone XYZ export** — `Export XYZ` bakes the layers selected in the QGIS Layers panel to `<output dir>/xyz_tiles/<layer>/` + index.html (empty tiles skipped; each also viewable at `/export-data/xyz_tiles/<slug>/index.html`). `Add baked tiles to the project as XYZ layers` (default ON) registers each tile tree as a `type=xyz` `file://` raster layer for canvas verification; `📁` opens the `xyz_tiles/` root.

## 6. Other tab — theme, permalink, share

- **Theme group** — theme combo (`comboBox_themes`, incl. `-- No Theme (Position Only) --`) selects the map theme applied on navigation; `Save Theme` stores current layer visibility/styles as a new theme. The `theme` permalink parameter applies a named theme on navigation and is exported as `.kasc` `theme:` lines without altering the project; missing themes fall back to no-theme (position only).
- **Permalink group** — `Generate Permalink` builds an HTTP permalink for the current view (center `x`/`y`, `scale`, `rotation`, `theme`) on the `/qgis-map` path; `URLCopy` copies it; `Navigate` jumps QGIS to a pasted permalink. `/qgis-map` returns no HTML — it is the URL path used for reception history and External Control navigation (built-in viewers removed in v3.24.0). Recommended params: `x` (longitude or projected X), `y` (latitude or Y), `scale` (preferred over `zoom`), `crs` (default EPSG:4326), `rotation`, `theme`. Example: `http://localhost:8089/qgis-map?x=139.01234&y=35.12345&scale=1000.0&rotation=0.00`. Short form (`x=139&y=35`) is allowed.
- **Share group** (`groupBox_sharing`, added dynamically into `tab_share`) — `Presentation Share` opens the `/present` canvas-mirror page and copies the LAN URL; the received-permalink combo shows the latest 10 received links and copies a selection into the navigate field; `MAC address authentication` + the MAC list restrict HTTP server access to registered client MACs (empty = deny all).
- **`/screenshot` rendering contract** — renders the current canvas MapSettings via `QgsMapRendererParallelJob` (canvas rotation included); `w`/`h` clamped to 4096 px; serialized by `_render_lock`, 30 s timeout. Viewer zoom (per-client, stateless): `extent=` literal setExtent range; `screen=` on-screen region (inverse-rotated under canvas rotation); `bbox=cx,cy,fw,fh` fraction-of-image zoom of a base render (`base=`+`bw`/`bh` for chained zoom); `rot=` explicit render rotation. Response headers `X-Map-Extent` and `X-Map-Corners`. `/present` requests `rot=0` renders and reproduces canvas rotation as view rotation (re-render on `moveend`).

## 7. Panel footer (outside tabs) — External Control & settings

- **External Control** (`checkBox_external_control`) — when enabled, URLs received from outside (e.g. `/qgis-map` links) are parsed per the permalink format (§6) and QGIS is navigated via `navigate_from_http`; a URL received before panel startup may auto-apply depending on settings. Security: keep the explicit ON/OFF toggle and log source/timestamp.
- **Settings dialog** (gear button, `settings_dialog.py`) — KASUGAI Canvas install dir, hosted channel (`kasugai_hosted_channel`/`kasugai_hosted_value`), Basemap Groups (`kasugai_basemap_groups`), Vector Export Format (`kasugai_vector_format` + Visible data only); all read/write the same QSettings as the panel controls.

## 8. HTTP API reference

- `GET /kasugai` — `.kasc`+`canvas_data/` export + Canvas registration. Accepts `engine=` (cesium|maplibre|openlayers|leaflet|gsimaps|navara, default cesium) and `install=1` (fetch distribution ZIP when not found). JSON response `{ok,url,via,dir,layers,tiles,engine}` (§1).
- `GET /live/*` — Live View API (`/live/kasc` `/live/features` `/live/file/` `/live/style` `/live/render` `/live/live.json` `/live/state` `/live/controls` `/live/camera` `/live/selection` `/live/writeback` `/live/mcp-discover` `/live/mcp`; §2).
- `GET /export-data/<rel>` — serves files under the latest export directory (.kasc/canvas_data/, launcher HTMLs, xyz_tiles/).
- `GET /<engine>/...` — statically serves the installed KASUGAI Canvas `web/` (fallback resolution for non-endpoint paths).
- `GET /present` `/present/state` `/screenshot` — window-share page, canvas state JSON, canvas PNG (§6).
- `GET /layouts` — project print layout list JSON `{ok,layouts:[{name,pages,w_mm,h_mm}]}` (used by the KASUGAI Canvas print dialog).
- `GET /layout-pdf` — exports a print layout to PDF via `QgsLayoutExporter` (`layout=<name>` optional, defaults to first layout; `dpi=` 72–600, default 300). Runs on the GUI thread via a queued invoker; serialized by `_layout_lock`.
- `GET /received` — received permalink history HTML.
- `GET /qgis-map` — permalink URL path. Returns no HTML; used for reception history and External Control navigation (§6/§7).
- `HEAD /export-data/` and `/<engine>/` — engine auto-detection probes of launcher HTMLs (static serving only).
- `OPTIONS` — CORS + Private Network Access preflight (for hosted engine https→localhost fetches).

Common behavior:
- The server attempts ports in the default range `8089-8099` to bind.
- The server binds to `0.0.0.0`, so LAN sharing is a designed use case. URLs shown to the user — the Presentation Share button, the panel server-status label, the server-start message, and bridge `openPresent`/`serverStatus`/`startServer` responses (`network_url`) — prefer `http://<LAN-IP>:<port>` so external PCs can connect directly; `localhost` is only the fallback when no LAN IP is found. The share button also copies the URL to the clipboard. If an external PC cannot reach the port, use Check Access diagnostics / the firewall-rule button.
- POST is only accepted under `/live/`; `OPTIONS` is answered as CORS + Private Network Access preflight.

## 9. Removed features

- **Built-in generated viewers (removed in v3.24.0)** — former `/qgis-map`, `/maplibre`, `/map3d` HTML viewers; viewing is consolidated into KASUGAI Canvas (§1).
- **OGC services (removed in v3.29.0)** — WMS/WMTS・XYZ/WFS/`/maplibre-style` endpoints and internals (`wms_service.py`, `wmts_service.py`, `wfs_service.py`, `sld_renderer.py`, `maplibre/`, ANGLE pipeline, WFS/WMTS caches). See git history.
- **Google Maps / Earth integration (removed in v3.30.0)** — URL generation/parsing (`_build_google_maps_url`, `_build_google_earth_url`, `_parse_google_maps_at_url`, `_parse_google_earth_url`), panel external-launch buttons, bridge `googleMapsUrl`/`googleEarthUrl`/`openExternal` Google support. Google Earth links now live on the KASUGAI Canvas basemap control. See git history.

## 10. CRS policy

- `.kasc` vector exports are normalized to `EPSG:4326` (native GPKG/Parquet/FGB references are handled client-side).
- Default permalink CRS when omitted is `EPSG:4326`.
- Coordinate conversion uses `QgsCoordinateTransform`; some projects may need external proj definitions.

## 11. Security and operations

- Default design allows external access; production deployments must restrict access via firewall or reverse proxy (the Share group's MAC authentication is also available, §6).
- `External Control` allows remote navigation; limit to trusted networks or require explicit approval flows.
- Enforce size limits on `/screenshot` requests (clamped to 4096 px per side).
- Keep logs with source IP, timestamp and action.

## 12. Test & QA

Automated test candidates
- Unit tests for `server_manager.py` (port selection & binding behavior) and URL parsing.

Manual test steps
1. Install plugin in QGIS.
2. `Export` writes `.kasc`+`canvas_data/`; choose the engine in the panel `Engine:` combo and press `▶ WebView` to verify the browser opens that engine (export→launch in one shot, same fallback as `/kasugai`; an export prompt appears when nothing was exported).
3. Enable `External Control` and, from another host (or the same host), request `/qgis-map?x=...&y=...&scale=...` — confirm QGIS navigates.
4. Confirm `/screenshot` returns a canvas PNG and `/present` opens the share page.

CI note: QGIS modules (`qgis.core`, `PyQt6`) will not be available in typical CI; mock them where needed.

## 13. Implementation-file mapping

- `plugin.py` — main plugin logic, permalink/navigation, panel event wiring.
- `panel.py` — panel UI (web distribution group, Live tab generation, Layers/Filter/XYZ tabs, sharing group, External Control toggle).
- `panel_base.ui` — Qt Designer UI (tabWidget_main: Web/Layers/Filter/XYZ/Other + footer External Control).
- `server_manager.py` — embedded HTTP server start/stop and routing (`/kasugai` `/export-data/` `/live/*` `/present` `/present/state` `/screenshot` `/received` `/layouts` `/layout-pdf` `/<engine>/` …).
- `http_server.py` — low-level HTTP response helpers.
- `kasugai_export.py` — `.kasc`+`canvas_data/` generation, XYZ baking, launcher HTML, project registration, command sending, fallback URL building.
- `live_kasc.py` `live_sync.py` `live_mcp.py` — Live View on-demand .kasc, edit-delta detection, MCP relay.
- `kasc_import.py` — `.kasc` → QGIS project reconstruction (bridge `kascInspect`/`kascImport`).
- `scale_zoom.py` — scale/zoom conversion.
- `settings_dialog.py` — settings dialog (KASUGAI install dir, hosted channel, Basemap Groups, Vector Export Format).
- `bridge.py` — AI/external control bridge (`kasugaiExport` etc.).

## 14. Changelog highlights

- V2.x → V3.x changes summarize theme and rotation support.
- v3.24.0 removed the built-in generated viewers (`/qgis-map`/`/maplibre`/`/map3d` HTML).
- v3.29.0 removed the OGC services (WMS/WMTS/XYZ/WFS, `/maplibre-style`).
- v3.30.0 removed Google Maps / Earth integration.
- v4.30.0+ added the resident Canvas Live View (`/live/kasc` on-demand generation, no export needed); v4.31 removed the embedded dock.

Notes
- After making server-side code changes, restart QGIS or the plugin process to reload module code; long-running Python processes do not auto-reload.

This file mirrors the Japanese `docs/spec.html`. If you modify the Japanese spec again, regenerate this English file to keep both versions in sync.

---
## §1 Web タブ — KASUGAI Canvas 連携（送出）詳細

QGIS プロジェクトのレイヤツリーを、KASUGAI Canvas のプロジェクト
（`.kasc` + `canvas_data/`）として書き出す機能。実体は `kasugai_export.py`。

### 起動経路

| 経路 | 呼び出し | 用途 |
|---|---|---|
| パネルボタン | `▶ WebView` ボタン (`plugin.py: on_kasugai_launch_clicked('hosted')`) | 人手操作。エクスポート→route 変換→ブラウザ起動まで一発。パネルの `Engine:` コンボで起動エンジンを選択（QSettings `kasugai_engine` に保存）。`CDN:` コンボでエンジン供給元モードを選択（`stable`/`unstable`=ホスト版 kasugai-canvas-web・`canvas`=稼働中 Canvas アプリ(:8510)・カスタム http(s) URL・web/ フォルダのファイルパス=FILE モード（本サーバがそのツリーを /<engine>/ 配信）。QSettings `kasugai_hosted_channel` に保存・設定ダイアログと共通）。`Install KASUGAI Canvas` ボタンは常時インストール専用、`Canvas Customize` はアプリの /admin/ UI設定画面を開く |
| パネルボタン | `Export` ボタン (`plugin.py: on_kasugai_export_clicked`) | 人手操作（ファイル出力のみ。Canvas 起動・登録はしない。ZIP は生成しない） |
| パネルボタン | `ZIP` ボタン (`plugin.py: on_kasugai_zip_clicked`) | エクスポート物一式を `kasugai_canvas_<チャンネル>.zip` としてブラウザダウンロード。`/export-data/` がオンデマンドで ZIP を生成して返す（要 HTTP サーバー稼働）。CDN コンボのチャンネルがファイル名に反映される |
| HTTP | `GET http://localhost:8089/kasugai` (server_manager._handle_kasugai) | 外部アプリ・AI からの一発起動。`?engine=` で起動エンジン指定可。応答は `{ok,url,via,dir,layers,tiles,engine}` JSON |
| Bridge | `bridge_call` の `kasugaiExport(output_dir, open_app, native_formats, hidden_as_off, emit_themes, emit_bookmarks, emit_launchers, engine, install, route, use_existing, emit_atlas, link_files, vector_format, visible_data_only, progress_cb, site_control)` | Live Driver 経由の AI 制御（MCP `qgis_bridge_call` / REST `/api/cmd` / JSONL）。`use_existing=True` で再エクスポートせず既存の `.kasc` のみ使用（未出力なら `code=not_exported`） |

### 出力フォルダ構成

```
<out_dir>/                    # 既定: <ドキュメント>/kasugai_canvas_qgis
├─ kasugai_canvas.kasc        # インスペクタ設定(外部プロジェクト登録対象)
├─ project.json               # {"title": ...}
├─ index.html + <engine>.html # 起動ランチャ(emit_launchers 時)
├─ bookmarks.xml              # qgis_bookmarks 形式(emit_bookmarks 時)
├─ live.json                  # live 連携マニフェスト(live_sync 時)
└─ canvas_data/
   ├─ *.geojson               # geojson モード変換 / 変換失敗時の最終フォールバック(EPSG:4326)
   ├─ *.fgb                   # recommended 変換 / ネイティブ参照の FGB(複製)
   ├─ *.gpkg                  # ネイティブ参照の GPKG(複製)
   ├─ *.parquet               # ネイティブ参照の Parquet(複製) / FGB ドライバ無し時の変換先
   ├─ *.shp + sidecars        # ネイティブ参照(.dbf/.shx/.prj 等を一式複製)
   ├─ *.csv / *.tsv           # duckdb: 参照の区切りテキスト(複製)
   ├─ *.gpx/.kml/.topojson 等 # その他ネイティブ参照の複製(_NATIVE_KINDS)
   ├─ *.tif / *.tiff          # geotiff: 行のローカル GeoTIFF/COG(複製)
   ├─ *.png                   # image: 行のラスタ焼き付け PNG(非 GeoTIFF・再現不能レンダラ)
   ├─ <dir>/                  # ローカル 3D Tiles / ローカル XYZ タイルの複製(1GiB 上限)
   ├─ <slug>_xyz/             # 大規模・複雑スタイルのベクター焼き付け XYZ({z}/{x}/{y}.png + index.html、§5)
   ├─ anim3d_*.geojson        # 3D ビューアニメーションのカメラ軌道(fly_geojson: 行)
   ├─ atlas_*.geojson         # アトラス巡回パス(fly_geojson: 行)
   ├─ *.qml                   # 各ベクターの QGIS スタイル(<slug>__<theme>.qml = テーマ別名付きスタイル)
   ├─ *.svg / *.png 等        # .qml が参照するシンボル画像(QGIS 内蔵SVG・ローカル画像の複製)
   └─ custom-layer.js         # site= 出力時の custom-layer プラグイン JS(§3)
```

起動 HTML（`index.html`・`<engine>.html`）は `?kasc=<.kasc URL>` 付きで対応
エンジンへ転送し、エンジン本体を `./ ../ ../../ /` の順に自動探索
（`CANVAS_BASE` で差し替え可。エンジン未検出時は `HOSTED_BASE` のホスト版
エンジンへ誘導）。

### .kasc 行の生成規則

| QGIS 側 | .kasc 行 | 備考 |
|---|---|---|
| GPKG ソース(地理座標系) | `gpkg: グループ/名 | canvas_data/x.gpkg | on | table=<表> | style=canvas_data/x.qml` | ファイルを canvas_data/ へ複製。複数テーブルは1ファイルを共有 |
| GeoJSON/Parquet/FGB ソース | `geojson:` / `geoparquet:` / `flatgeobuf:` 参照行 | ローカルは複製、http(s) は URL をそのまま記述 |
| CSV/TSV(delimitedtext・ogr) | `duckdb: 名 | canvas_data/x.csv | on | format=csv | lon=<列> | lat=<列>` | ジオメトリ列は `geom=`。delimitedtext は URI の xField/yField/wktField を引き継ぎ、ogr CSV はヘッダから推定。delimitedtext で非地理座標系の場合は FlatGeobuf 変換(フォールバック時 GeoJSON) |
| フィルタ(subsetString)付き GPKG | `gpkg: … | where=<フィルタ>` | ネイティブ参照のままフィルタ維持(SQL 評価) |
| フィルタ付き GeoJSON/FGB・URL Parquet | `geojson:`/`flatgeobuf:`/`geoparquet:` … `| where=<フィルタ>` | Canvas 側 where-eval.js のクライアント評価(OGR SQL WHERE句準拠・`||` 連結対応)。評価器が扱えない式(単独 `|`・`%` 等)は FlatGeobuf 変換でフィルタを地物へ焼き込む(フォールバック時 GeoJSON) |
| フィルタ付き Parquet(ローカル) | `duckdb: 名 | canvas_data/x.parquet | on | format=parquet | where=<フィルタ>` | duckdb: へ切替えて SQL 評価 |
| 3D Tiles レイヤ(QgsTiledSceneLayer) | `3dtiles: グループ/名 | <tileset.json URL or canvas_data/x/tileset.json> | on` | http(s) は URL 参照、ローカルはディレクトリごと canvas_data/ へ複製(1GiB 上限・超過は skipped) |
| XYZ タイルラスタ | `xyz:` 行。表示中の**最下段**のみ `base:` 行（既定ベースマップとして既定群の先頭に置く）。「背景図」「ベースマップ」「basemap」名のグループ内にある XYZ は位置・表示状態に関わらず全て `base:` 行（ベースマップ候補）として登録し、グループ名はタイトルから外す（配下のサブグループは残し、Canvas のベースマップ選択でグループ化表示される）。非表示の候補は `| off` 付きで出力。グループ名は XYZ タブの Basemap Groups（QSettings `kasugai_basemap_groups`・カンマ区切り、§5）で追加可能 | zmin/zmax → minZoom=/maxZoom=。不透明度は opacity=、限定範囲は bbox=西経,南緯,東経,北緯。縮尺表示は minScale=/maxScale= |
| XYZ ローカルテンプレート | `xyz:` 行(canvas_data/<dir>/{z}/{x}/{y}.png) | `file:///…/{z}/{x}/{y}.png` はタイルツリーごと canvas_data/ へ複製(1GiB 上限・超過は skipped) |
| WMS ラスタ(type=xyz 以外) | `wms: グループ/名 | <エンドポイントURL> | on | layers=, styles=, format=` | QGIS の WMS 接続 URI から url=/layers=/styles=/format= を抽出。Canvas 側が GetMap を 256px タイルへ分解して要求 |
| その他ベクター(SHP/PostGIS/WFS/メモリ等)・非地理座標系 | FlatGeobuf(EPSG:4326・空間インデックス付き)へ変換して canvas_data/ へ `flatgeobuf:` 行 | ドライバ非搭載時は Parquet、変換失敗時は GeoJSON へフォールバック。再投影は warnings に記録 |
| 属性テーブルのみ(NoGeometry)・ローカルラスタ・ベクタータイル・メッシュ・点群・アノテーション等 | 出力せず `skipped` に種別/理由付きで記録 | |
| 非表示レイヤ | `hidden_as_off=True` またはマップテーマ存在時に `| off` 付きで出力。`visible_data_only=True`（QSettings `kasugai_visible_data_only`、既定 ON）ではレイヤ行を一切出力せず skipped（背景図グループの `base:` 候補のみ従来通り出力・高速化）。`visible_data_only=False` で `| off` 行として全データを変換・複製する従来動作 | 既定(visible_only=True)では除外 |
| キャンバス | `cam:` 行(中心座標+概算高度+回転) | |
|| 保存済み3Dビュー(ローカル/グローブ) | `cam:QGIS3D <名>|lat|lon|h=|p=|d=` 行(注視点+dist/pitch/yaw→ENUオフセットでカメラ位置逆算: 高さ=dist·cos(pitch)・水平=dist·sin(pitch)・視線方位=360-yaw・p=pitch-90) + `terrain:` 行(垂直誇張/オフセット/陰影/ジェネレータ) + `scene3d:` 行(背景色/スカイボックス/影/SSAO/EDL・グローブは globe=on) + `light:` 行(平行光源の方位・仰角・強度・色) | 3Dビューが存在する場合のみ出力。シーンCRSはビューごとの `<qgis3d><crs>` を解決し、地心系(QGIS4グローブ・EPSG:4978等)はECEF→測地変換で対応。既定値相当の項目は省略 |
|| 3Dビューのアニメーション(`<animation3d>`キーフレーム) | `fly_geojson: QGIS3D <名> | canvas_data/anim3d_<slug>.geojson | speed=<m/s> | view=camera | step=<m>` 行 + カメラ軌道の LineString GeoJSON | 各キーフレーム(注視点+dist/pitch/yaw+時刻)のカメラ位置を計算してカメラ軌道にする。speed=軌道3D総延長÷アニメ時間。キーフレーム2個未満は出力しない |
| ベクターの3Dレンダラ(立ち上げ) | ベクター行へ `| extrude=<m>`(立ち上げ高さ)・`| z=<m>`(基準高さオフセット) を付与 | QgsVectorLayer3DRenderer のポリゴン/ラインシンボル。Canvas(Cesium)側で polygon の height/extrudedHeight へ反映 |
| ブックマーク | `bookmarks.xml`(qgis_bookmarks形式・EPSG:4326正規化) + `bookmark:` 行(プロジェクト+アプリケーション両方) | `emit_bookmarks=False` で抑制。Canvas 側が XML を読み込みカメラプリセットへ展開する |
| アトラス有効な印刷レイアウト | `fly_geojson: Atlas: <レイアウト名> | canvas_data/atlas_<slug>.geojson | speed= | pitch=-85 | height=0 | view=camera | step=` 行 | `emit_atlas=False` で抑制(v4.8.0〜)。各アトラスページの表示範囲(参照地図 extent)を巡回するプレゼン用フライパス。座標Z値にページを収めるカメラ高(楕円体高)を焼き込み、`properties.heightReference="MSL"` で地形加算を抑止、ページ名一覧は `properties.pages` へ。地図回転付きは warnings に記録のみ |

その他: `attr=` に QGIS レイヤの出典(attribution)を引き継ぐ。
`where=` は行の**最終オプション**で、値は改行までが式
(`||` 連結・`'a|b'` リテラル等の `|` を含んでよい)。
where-eval.js は `||` 連結に対応済み(単独 `|`・`%` は非対応)。
`off` や他の `key=value` は `where=` より前に置く。
`view:` の `;where=` は行内トークンのため対象外(値に `|` は書けない)。
全レイヤ行で `minScale=`/`maxScale=` に QGIS の「縮尺による表示」
(minimumScale=引き側限界・maximumScale=寄り側限界)を出力する。
Canvas 側は同じ範囲で表示/非表示を切り替える。
`.qml` 書き出し後、シンボルレイヤが参照する画像(SvgMarker/RasterMarker/
SVGFill/RasterFill 等の `name`/`imageFile`/`svgFile`/`file`)を実ファイルへ
解決して canvas_data/ へ複製し、.qml 内の参照を canvas_data/ 内のファイル名へ書き換える
(QGIS 内蔵SVGの `transport/…` 等の相対名は `QgsApplication.svgPaths()` で
解決。http(s)/data/base64: 参照はそのまま維持。解決不能は warnings 記録)。
`sql:` 行は QGIS 側に対応する任意クエリソースが無いため出力しない
（クエリ系は `duckdb:` の宣言的オプションで網羅する）。

### ベクター出力形式（native / recommended / geojson）

ベクターレイヤの出力方針を切り替える「推奨形式スイッチ」
（QSettings `kasugai_vector_format`、既定 `native`）。
切替は4経路あり、パネル/設定ダイアログは永続設定を読み書きし、
URL/bridge は当該エクスポートだけの一時上書き（いずれも相互に同期）:

- パネルの **Format:** コンボ
  （`native (reference as-is)` / `recommended (FlatGeobuf → canvas_data/)` / `geojson (WEB interop → GeoJSON)`）— 永続
- 設定ダイアログの **Vector Export Format** コンボ — 永続
- `GET /kasugai?fmt=recommended|native|geojson` — そのリクエストのみ上書き
  （応答 JSON に `vector_format` を含む）
- bridge `kasugaiExport(vector_format='recommended'|'native'|'geojson')` — 呼出しのみ上書き

| モード | ベクターの扱い |
|---|---|
| `native`（既定） | 読めるソースはそのまま参照（`gpkg:`/`geojson:`/`shp:`/`wfs:`/`duckdb:`/`flatgeobuf:`/`geoparquet:` 行）。非ネイティブ形式のみ変換（上表のフォールバック） |
| `recommended` | FlatGeobuf/GeoParquet 以外の全ソースを FlatGeobuf（EPSG:4326・空間インデックス付き）へ変換し canvas_data/ へ `flatgeobuf:` 行で配置。既に FlatGeobuf/GeoParquet のソースは参照を維持（`flatgeobuf:`/`geoparquet:`/`duckdb:+format=parquet` 行）。subsetString・fields/where/limit は変換データへ焼き込み。Canvas 側では `bbox=auto` の範囲読みが効く（`flatgeobuf:` は空間インデックス+Range、`geoparquet:` は covering.bbox 列または行グループ geospatial statistics による部分読み。いずれも無いファイルは全件へフォールバック） |
| `geojson`（WEB連携） | 全ベクター（FlatGeobuf/GeoParquet ソース含む・WFS/メモリ等も）を GeoJSON（EPSG:4326）へ変換し canvas_data/ へ `geojson:` 行で配置。canvas_data/ がオープン標準の GeoJSON のみになるため、KASUGAI Canvas 以外の WebGIS・GIS ツールでもそのまま読み込める相互運用向けモード |

変換ドライバは FlatGeobuf が第1候補（非搭載環境は Parquet）で、
変換失敗時は GeoJSON(EPSG:4326) へフォールバックする（native モードの非ネイティブ変換と同じ経路）。
`geojson` モードは GeoJSON 固定（ドライバ切替なし）。

### 非表示レイヤの出力省略（表示中のみ変換）

非表示レイヤ（`hidden_as_off=True` またはマップテーマ存在時に
`| off` で出力されるレイヤ）を .kasc のレイヤ行へ一切出力しない
高速化スイッチ（QSettings `kasugai_visible_data_only`、既定 ON）。
Canvas のレイヤ一覧に非表示レイヤが並ばず、データ変換・
canvas_data/ へのコピー・スタイル書き出しのコストも掛からない。
背景図グループ内の XYZ タイルなど `base:` 候補のみ従来通り
`| off` 付きで出力する（ベースマップ選択の候補）。スキップされた
レイヤは Canvas で表示に切り替えられない（`skipped` に理由付きで
記録）。`theme:` 行は実際に出力されたレイヤのみを対象とする。
OFF で従来通り非表示レイヤも `| off` 行として全データを変換・
複製する（プロジェクトの丸ごと引越し用途）。

切替経路（パネル/設定ダイアログは永続設定を読み書き、
bridge/API 引数は当該エクスポートだけの一時上書き）:

- パネルの **Visible data only (faster)** チェック — 永続
- 設定ダイアログの **Vector Export Format** 内にある同名チェック — 永続
- bridge `kasugaiExport(visible_data_only=True|False)` — 呼出しのみ上書き
- `export_kasugai_project(visible_data_only=…)` — 呼出しのみ上書き

### エクスポート進捗（progress_cb）

`export_kasugai_project` / bridge `kasugaiExport` に
`progress_cb(done, total, name)` を渡すと、レイヤツリー走査の
各レイヤ処理開始時に「何件目/全何件・対象名」を通知する
（全件完了時は `(total, total, '')`）。パネルのエクスポート/
起動ボタンは QProgressDialog に「レイヤーを変換中 N/M: 名前」
とバーを表示し、Cancel 押下で `ExportCancelled` を送出して
中断できる（bridge は `code: 'cancelled'` で返す）。
`GET /kasugai` 経路は GUI を持たないため同形式の進捗を
QgsMessageLog へ記録する。

### .qml スタイル出力

スタイル（.qml）はベクターデータ形式とは**独立**で、
native/recommended/geojson のどのモードでも同じ扱い:

- 出力される全ベクターレイヤについて `layer.saveNamedStyle()` で
  `canvas_data/<slug>.qml` を書き出し、.kasc 行へ
  `| style=canvas_data/<slug>.qml` を付与する。
  ネイティブ参照行（`gpkg:`/`flatgeobuf:` 等）でも
  変換行（`flatgeobuf:`/`geojson:`）でも付き方は同じ
- .qml の中身は `<renderer-v2>`（シンボル）・
  `<labeling>`/`<text-style>`（ラベル）・時間設定等の QGIS レンダラ定義。
  Canvas 側は `qml-style.js`+`<engine>/qml-render.js` が
  これをエンジン描画へコンパイルする（データ形式ではなくスタイル再現の責務）
- ユーザー定義関数（geo_userfunc の `@qgsfunction`）を含む式属性は
  書き出し時に宣言式へ展開する（配布物を組込み関数のみにする）
- シンボル画像（SvgMarker/RasterMarker/SVGFill/RasterFill 等）の参照は
  canvas_data/ へ複製し .qml 内パスを書き換える（前述「その他」の通り）
- 差分エクスポート（`changed`）では style 変更のあったレイヤのみ
  .qml を再書き出しし、未変更レイヤは既存 .qml を再利用する

スタイルの配布経路は `.qml`+`style=` の1系統に統一
（v4.21.0 で GPKG `layer_styles` への書き込み経路
`embed_gpkg_style` は廃止）。

### KASUGAI 側への反映

起動中の KASUGAI ローカルサーバー（`KASUGAI_CANVAS_PORT`、既定 8510）が
あれば `POST /api/projects/register` で外部プロジェクト登録し、
`POST /api/command` の `switchProject` で表示を切り替える。

Canvas が使えない場合は次の順でフォールバックする
（`/kasugai`・`kasugaiExport` とも応答の `via` で供給元を返す）:

| `via` | 条件 | URL |
|---|---|---|
| `kasugai` | Canvas 稼働（or exe/関連付けで起動成功） | `http://127.0.0.1:8510/<engine>/?project=<id>` |
| `qgis-http` | Canvas 未起動だが **インストール済み** `web/` あり | `http://localhost:<port>/<engine>/?kasc=<export-data URL>` |
| `hosted` | Canvas **未インストール**（要インターネット） | `https://yamamoto-ryuzo.github.io/kasugai-canvas-web/<channel>/<engine>/?kasc=<export-data URL>` |
| `null` | いずれも不可 | 出力のみ成功 |

- `qgis-http`: geo_webview の HTTP サーバーが **エンドポイントに一致しなかった
  パスをインストール済み Canvas の `web/` 配下へ静的解決**する
  （`find_kasugai_web_dir()`）。同一オリジンのため混在コンテンツ問題なし
- `hosted`: エンジン本体は `kasugai-canvas-web`（GitHub Pages）から取得し、
  `.kasc`+`canvas_data/` は本サーバーの `/export-data/` から読む。https→localhost
  の fetch は Chrome Private Network Access 対象のため、サーバーは
  `OPTIONS` プリフライトに `Access-Control-Allow-Private-Network: true` で
  応答する。モードは設定 `kasugai_hosted_channel`
  （`stable`/`unstable`/カスタムURL、既定 `stable`）で、
  パネルの `CDN:` コンボ（stable/unstable/canvas/custom + 「カスタム（URL/FILE）」欄の実値 `kasugai_hosted_value`）または設定ダイアログから変更する
- エンジン起動HTML は `HEAD` メソッドで `<engine>/index.html` を自動探索する
  ため、サーバーは `HEAD`（静的配信のみ）にも応答する

### AI からの操作

- Live Driver の `qgis_bridge_call`（MCP/REST/JSONL）で
  `kasugaiExport` を呼ぶ — 推奨（引数制御可能・JSON 応答）
- または `GET /kasugai` を直接 HTTP で呼ぶ
- KASUGAI 側の WebView プラグイン `qgis-import`
  （kasugai_canvas `web/PLUGIN/`）の「QGISから取り込み」ボタンも
  同じ `/kasugai` を呼ぶ薄い実装

---
## §3 Layers タブ — カスタムレイヤタブとレイヤ別オプション

レイヤごとの .kasc オプションを設定するタブ。値はレイヤ customProperty へ
保存され、エクスポート時にレイヤ行の `| key=value` として出力される
（グレー表示=自動値、空欄に戻すと自動値へ復帰）。

| 列 | customProperty | .kasc 出力 |
|---|---|---|
| site | `kasugai_site` | `site=<箇所名>`（`-`/空=強制未割当。空欄＋チェックONでグループ名を自動付与） |
| order | `kasugai_order` | `order=<数値>`（同一 site 内の順序。小さいほど最前面。VIEW モードの ▲▼ ボタンで設定） |
| list | `kasugai_list` | `list=off`（レイヤ一覧から非表示・標準/カスタムとも。地図は描画） |
| opts | `kasugai_opts` | 任意の `key=value` を空白/パイプ区切りで追加（例 `opacity=0.5 heat=on`）。`legend_order=asc|desc|reverse|ラベル列挙` でカスタムタブの凡例順を変更可 |

**Custom layers tab** チェック（QSettings `kasugai_site_control`、既定 OFF）
を ON にすると、レイヤツリーのグループ名を `site=<グループ階層>` として
グループ内全レイヤへ自動付与する。`site=` 付きレイヤが1件でも出力されれば
`assets/custom-layer.js` を `canvas_data/` へ複製して
`plugin: custom-layer | name=レイヤ | url=canvas_data/custom-layer.js | before=layers-panel`
行を書く（チェックOFFでも customProperty 指定の site= だけは有効かつ
プラグイン行が出る）。`plugin:` 行には Filter タブの選択状態が
`filter_*` オプションとして付記される（§4）。

---
## §4 Filter タブ — サイト共通フィルタ

site（Layers タブの site= 解決規則と同一、グループ無しは「その他」）内の
**全ベクターレイヤへ共通の属性フィルタ（subset string）を一括適用**する。
地図表示とエクスポートデータ（subsetString は `where=` へ引き継がれる）の
両方に反映される。

- **Site:** コンボ — site 名の一覧（タブを開くたび最新化）
- **Field:** コンボ — メンバー全レイヤに共通する属性フィールドのみ列挙
  （全レイヤで数値型は `(num)` 付記）。無ければ `No common field`
- **条件行（自動切替）** — 数値型は `= != < <= > >=`＋数値入力、
  文字列型は `= !=`＋値コンボ。**Multiple selection** で
  `IN`/`NOT IN`＋値チェックリスト（全選択/全解除）へ切替
- **自動適用** — site+field+値（複数選択時はチェック1件以上）が揃った
  時点で即適用（テキスト入力は 350ms デバウンス）。0件の `IN` は
  常偽式 `1=0`、0件の `NOT IN` はフィルタ解除
- **Clear** — サイト内全レイヤの subset string を解除
- **エクスポート連携** — 選択状態は
  `kasugai_export.set_filter_panel_state()` へ随時同期され、
  `plugin: custom-layer` 行の `filter_site=`/`filter_field=`/`filter_multi`/
  `filter_op=`/`filter_value=`/`filter_values=` として出力
  （Canvas 側「フィルタ」タブの初期選択）

---
## §5 XYZ タブ — タイル焼き付け・ベースマップ

- **Vector → XYZ tile bake** — `XYZ tiles (faster display)` チェック
  （QSettings `kasugai_xyz_tiles`、既定 ON）＋ Zoom zmin/zmax
  （`kasugai_xyz_zmin`/`kasugai_xyz_zmax`、既定 1-15）: .kasc エクスポート時に
  大規模・複雑スタイルのベクターを QGIS レンダラで `<slug>_xyz/`
  へ焼き付け `xyz:` 行で出す。レイヤ customProperty `kasugai_render`
  （`xyz`=必ず / `vector`=しない / `auto`・空=自動）で個別指定可。
  Canvas 側フィルタ（`where=`）は焼き付け画像に反映されない
- **Basemap Groups** — `kasugai_basemap_groups`（カンマ区切り）で
  ベースマップ候補グループ名を追加。該当グループ内の XYZ は全て
  `base:` 行として出力
- **Standalone XYZ export** — `Export XYZ` がレイヤパネルで選択中の
  レイヤを `<出力先>/xyz_tiles/<layer>/` へ別経路で焼き付け
  （index.html ビューア付き）。`Add baked tiles to the project`（既定 ON）
  で `type=xyz` ラスタレイヤとしてプロジェクトへ追加。`📁` で
  `xyz_tiles/` を開く

---
## §6 Other タブ — テーマ・パーマリンク・共有

- **Theme** — テーマ選択コンボと `Save Theme`。`theme` パラメータは
  ナビゲーション時に適用（プロジェクト自体は変更しない）し、
  `.kasc` へ `theme:` 行として出力。未存在テーマは No Theme
  （位置のみ適用）へフォールバック
- **Permalink** — `Generate Permalink`/`URLCopy`/`Navigate`。
  パラメータは `x`/`y`/`scale`/`crs`(既定 EPSG:4326)/`rotation`/`theme`
  （`scale` 優先、`zoom` は内部推定）。`/qgis-map` は HTML を返さず
  受領記録・External Control ナビゲートの URL パス
- **Share** — `Presentation Share`（`/present` ページ + URL コピー）、
  受領履歴コンボ（最新10件、`/received`）、MAC 認証
- **/screenshot** — `w`/`h`（4096px クランプ）・`extent`/`screen`/`bbox`/
  `rot` の視聴者ズーム。`X-Map-Extent`/`X-Map-Corners` 応答ヘッダ。
  `_render_lock` 直列化・30秒タイムアウト

---
## §7 パネル下部 — External Control・設定

- `External Control` チェックが有効なら、外部から受信した URL を
  自動適用して QGIS をナビゲート（`navigate_from_http`）。
  パラメータは §6 のパーマリンク形式に準じる。ON/OFF トグルを持ち、
  受信元・実行時刻のログ記録を推奨
- 設定ダイアログ（歯車）— KASUGAI インストール先・ホスト版チャンネル・
  Basemap Groups・Vector Export Format（＋Visible data only）を管理。
  パネル側と同じ QSettings を読み書き

---
## §10 セキュリティ・運用上の注意
- デフォルトで外部アクセスを許す設計だが、公開環境ではファイアウォールやプロキシでアクセス制御を厳格に行うこと。
- `External Control` を有効にしていると任意の外部URLで QGIS の表示が書き換わるため、信頼できるネットワーク内または追加の承認フローを用いることを強く推奨。
- ログを適切に出力し、受信元IP・タイムスタンプ・実行アクションを残す運用を推奨。

---
## §11 テスト・QA 手順
自動テスト候補:
- `server_manager.py` のユニットテスト: ポート選定・バインド挙動のモックテスト。
- URL パーサ（内部形式）の単体テスト（複数フォーマットのケース）。

手動テスト手順（QGIS 実環境）:
1. QGIS を起動しプラグインをインストール。
2. `Export` で `.kasc`+`canvas_data/` を出力し、パネルの `Engine:` でエンジンを選び `▶ WebView` を押してブラウザでそのエンジンが開くことを確認（出力→ブラウザ起動まで一発。未出力時はエクスポートを促すメッセージが出る）。
3. `External Control` を ON にして、別ホスト（または同一ホスト）から `/qgis-map?x=...&y=...&scale=...` にアクセスして QGIS がジャンプすることを確認。
4. `/screenshot` でキャンバス PNG が返ることを確認。
5. `/present` ページがブラウザで開くことを確認。

テスト注意:
- CI 環境では `qgis.core` や `PyQt6` が無いため、これらをモックするかローカルでの手動確認が必要。

---
## §12 実装ファイルと責務マッピング
- `plugin.py` — メインプラグインロジック、パーマリンク/ナビゲート、パネルイベント配線。
- `panel.py` — パネル UI 実装（Web配信グループ、Live タブ動的生成、Layers/Filter/XYZ 各タブ、共有グループ、外部制御トグル等）。
- `panel_base.ui` — Qt Designer の UI 定義（tabWidget_main: Web/Layers/Filter/XYZ/Other + 下部 External Control）。
- `server_manager.py` — 組み込み HTTP サーバーの起動/停止・ルーティング（`/kasugai` `/export-data/` `/live/*` `/present` `/present/state` `/screenshot` `/received` `/layouts` `/layout-pdf` `/<engine>/` 等）。
- `http_server.py` — HTTP 応答の低水準送信ユーティリティ。
- `kasugai_export.py` — KASUGAI Canvas 連携（`.kasc`+`canvas_data/` 生成、XYZ 焼き付け、起動HTML生成、プロジェクト登録、コマンド送信、フォールバックURL構築）。
- `live_kasc.py` `live_sync.py` `live_mcp.py` — Live View の .kasc オンデマンド生成・編集差分検出・MCP リレー。
- `kasc_import.py` — .kasc → QGIS プロジェクト再構成（bridge `kascInspect`/`kascImport`）。
- `scale_zoom.py` — スケール/ズーム換算。
- `settings_dialog.py` — 設定ダイアログ（KASUGAI インストール先・ホスト版チャンネル・Basemap Groups・Vector Export Format）。
- `bridge.py` — AI/外部制御用ブリッジ（`kasugaiExport` 等）。

---
## §13 変更履歴の要約（V2/V3 ハイライト）
- V2.0.0: WMS サポートと外部アクセス（0.0.0.0 バインド）を追加。
- V2.6.0: 投影定義と軸順情報を生成 HTML に埋め込み、座標表示の精度向上。
- V2.8.0: External Control の自動ナビゲート追加。
- V2.10.0: Google Earth `y` トークン対応とスケール推定の改善。
- V2.12.0: テーマ対応 WMS 出力（仮想マップビュー）。
- V2.13.0: WMTS タイルエンドポイント、MapLibre 改善（pitch トグル、zoom clamp 解除）。
- V3.0.0: MapLibre WFS + QGIS スタイル注入の安定化、ベーススタイルの相対URL化、ブラシ無しポリゴンの正しい境界線表示、単位正規化（mm/pt→px）を確立。

- V3.1.0: WMTS キャッシュ導入
  - サーバ側で WMTS タイルのキャッシュを有効化しました。キャッシュは各 "identity" ごとに分離され、identity は表示中のレイヤ識別子（layer ID）と各レイヤに適用されるスタイル識別子（style ID）を決定的に組み合わせた JSON を sha1 ハッシュ化し、その先頭 12 文字（short hash）を採用して生成されます。
  - GetCapabilities の ResourceURL / ServiceMetadataURL に `?v=<identity_short>` を付与することで、クライアントが現在サーバ側で有効な identity を検出できるようにしました。
  - クライアント（MapLibre）は画面移動（moveend）時に GetCapabilities を再取得し、identity が変化していれば WMTS タイルソースのみを差し替えて新しいタイルを取得する挙動を推奨します（WFS やスタイル全体の再読み込みは不要）。
  - この仕組みにより、サーバ側で表示用レイヤやスタイルが変更された際に WMTS のみを効率的に更新・無効化でき、WFS の重複登録や全スタイル再適用に起因する副作用を避けられます。

---
## 付録: 代表的なサンプル URL
- パーマリンク（位置）:
  `http://localhost:8089/qgis-map?x=139.7594&y=35.6837&scale=1000.0`
- キャンバスPNG:
  `http://localhost:8089/screenshot`
- KASUGAI エクスポート:
  `http://localhost:8089/kasugai?engine=cesium`
