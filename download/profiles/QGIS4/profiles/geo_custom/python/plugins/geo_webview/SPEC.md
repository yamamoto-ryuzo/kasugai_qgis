# geo_webview — Specification

[日本語版はこちら / Japanese: `SPEC_JP.md`](SPEC_JP.md)

This specification formalizes the features described in the repository README and CHANGELOG, organized by capability. It targets implementers, operators and testers of the `geo_webview` plugin.

Purpose and scope
- Purpose: Define the expected behavior of the `geo_webview` plugin for implementation, operation and testing.
- Scope: **serverless web distribution (main feature)** — exporting the open QGIS project as `.kasc`+`DATA/` for the KASUGAI Canvas multi-engine players (Cesium/MapLibre/OpenLayers/Leaflet/GSI Maps/Navara); the embedded HTTP server (`/kasugai`, `/export-data/`, `/present`, `/screenshot`, permalink reception) as the supporting side; permalink generation/navigation, theme application, External Control behavior, CRS policy, and security/operational considerations.

1. Feature overview
- **Serverless web distribution (main)**: export the open QGIS project as a `.kasc`+`DATA/` package playable on the KASUGAI Canvas engines (Cesium/MapLibre/OpenLayers/Leaflet/GSI Maps/Navara). Placing the output plus the engine on a static host delivers the map without any server. Launch routes: panel (`Export` = files only / `▶ Open` = register+launch), `GET /kasugai`, and bridge `kasugaiExport`, with a 3-tier fallback (Canvas registration → static serving by this server → hosted engine). See §15.
- Embedded HTTP server (supporting): provides `/kasugai` `/export-data/` `/present` `/present/state` `/screenshot` `/received` `/layouts` `/layout-pdf` `/live/state` `GET /live/mcp-discover` `POST /live/mcp` `POST /live/camera` `POST /live/selection` `POST /live/writeback` `POST /live/features` (OGC services removed in v3.29.0).
- **Live bidirectional sync (v4.9.0)**: opt-in via QSettings `kasugai_live_sync` or bridge `liveSyncStart/Stop/Status/Flush` (`live_sync.py`). Layer edits/style/tree changes are debounced (1.2s) into a **delta re-export** (`export_kasugai_project(changed=…)` skips data/style file writes for unchanged layers; structural changes fall back to full export). Exports emit a `live: <base URL>` kasc line + `live.json` manifest ({rev, updated, changed:[{title,data,style}]}). Canvas polls `live.json` or receives a `liveSync` push via `/api/command` and reloads only changed layers when the .kasc text is unchanged. Reverse direction: `POST /live/camera` (Canvas view → canvas center/scale/rotation; accepts {lon,lat,zoom|scale|height,heading} or {bbox}) and `POST /live/selection` (Canvas pick → QGIS layer select by ids/bbox/point+buffer_m), `POST /live/writeback` (Canvas visibility/filter/theme → QGIS project), `POST /live/features` (GeoJSON → scratch layers). `GET /live/state` returns sync state + canvas state (+ `live.qgis_selection` pushed on QGIS-side selection). On-demand GET APIs: `GET /live/layers` (catalog with kasc titles), `GET /live/features` (GeoJSON by layer/bbox/pt/limit), `GET /live/selection` (QGIS selection as GeoJSON), `GET /live/render` (EPSG:4326 bbox → PNG, bg=transparent, optional layer subset — used by Canvas "QGIS render" fallback overlay). POST is accepted only under `/live/` (existing CORS allowlist applies).
- **Reverse authoring / data injection (v4.11.0)**: `POST /live/writeback` applies Canvas inspector state back to the project — `{layers:[{title,visible,where?}], theme?}`; `title` resolves via the same kasc-title normalization as selection, `visible` toggles the layer-tree node check (ancestors enabled when showing), `where` updates the vector provider subsetString, and `theme` applies a same-named map theme when present. Applied inside `LiveSyncController.suppress()` so the writeback does not trigger a redundant re-export. `POST /live/features` injects `{name, geojson: FeatureCollection|Feature[], replace?}` as memory scratch layer(s) — mixed geometry types are split, properties become fields via `QgsJsonUtils`, layers are tagged with custom property `kasugai_live_name` and added under a top "Canvas" layer-tree group; `replace` (default true) removes previously injected layers of the same name. The same logic is exposed to AI as bridge `liveWriteback(payload)` / `liveAddFeatures(name, geojson, replace)`.
- **Live Driver MCP relay (v4.12.0)**: `live_mcp.py`. Lets the CDN-hosted KASUGAI Canvas AI chat reach the QGIS Live Driver MCP tools (`qgis_pyeval` / `qgis_bridge_call` / `qgis_screenshot` …, including Processing analysis and other plugins' bridge methods) without the :8510 local app — the driver's `/mcp` itself is CORS-less + Bearer-protected and cannot be fetched directly from a browser. `GET /live/mcp-discover` scans the `~/.qgis-live/` registry and returns the relay URL to register (`http://127.0.0.1:<port>/live/mcp`); `POST /live/mcp` resolves the session on every request (auto-follows QGIS restarts) and forwards the JSON-RPC with the registry token attached server-side, propagating `Mcp-Session-Id` both ways (`Access-Control-Expose-Headers` added to the CORS response). Because `pyeval` is arbitrary code execution, the relay accepts **loopback TCP peers only** (unlike the other `/live/*` endpoints); browser-originated traffic is additionally constrained by the existing CORS allowlist.
- Permalink generation: create HTTP permalinks for the current QGIS view (center coordinates, scale, rotation, theme, etc.) on the `/qgis-map` path for copying or opening in browsers. `/qgis-map` returns no HTML — it is the URL path used for reception history and External Control navigation (built-in viewers removed in v3.24.0).
- Theme support: apply a named map theme on navigation (permalink `theme` parameter) and export theme lines (`.kasc` `theme:`) without altering project files.
- External Control: accept requests (for example to `/qgis-map` or `/wms`) and, when permitted, navigate QGIS accordingly.

2. API / Endpoints (high-level)
- `GET /kasugai` — `.kasc`+`DATA/` export + Canvas registration. Accepts `engine=` (cesium|maplibre|openlayers|leaflet|gsimaps|navara, default cesium) and `install=1` (fetch distribution ZIP when not found). JSON response `{ok,url,via,dir,layers,tiles,engine}`.
- `GET /export-data/<rel>` — serves files under the latest export directory (.kasc/DATA/, launcher HTMLs).
- `GET /<engine>/...` — statically serves the installed KASUGAI Canvas `web/` (fallback resolution for non-endpoint paths).
- `GET /present` `/present/state` `/screenshot` — window-share page, canvas state JSON, canvas PNG.
- `GET /layouts` — project print layout list JSON `{ok,layouts:[{name,pages,w_mm,h_mm}]}` (used by the KASUGAI Canvas print dialog).
- `GET /layout-pdf` — exports a print layout to PDF via `QgsLayoutExporter` (`layout=<name>` optional, defaults to first layout; `dpi=` 72–600, default 300). Runs on the GUI thread via a queued invoker; serialized by `_layout_lock`.
- `GET /received` — received permalink history HTML.
- `GET /qgis-map` — permalink URL path. Returns no HTML; used for reception history and External Control navigation.
- `HEAD /export-data/` and `/<engine>/` — engine auto-detection probes of launcher HTMLs (static serving only).
- `OPTIONS` — CORS + Private Network Access preflight (for hosted engine https→localhost fetches).

Common behavior:
- The server attempts ports in the default range `8089-8099` to bind.
- The server binds to `0.0.0.0`, so LAN sharing is a designed use case. URLs shown to the user — the Presentation Share button, the panel server-status label, the server-start message, and bridge `openPresent`/`serverStatus`/`startServer` responses (`network_url`) — prefer `http://<LAN-IP>:<port>` so external PCs can connect directly; `localhost` is only the fallback when no LAN IP is found. The share button also copies the URL to the clipboard. If an external PC cannot reach the port, use Check Access diagnostics / the firewall-rule button.

3. Permalink format and parameters
Recommended fields
- `x` : longitude (or X in project CRS)
- `y` : latitude (or Y in project CRS)
- `scale` : QGIS scale (e.g. `1000.0`)
- `crs` : if omitted, interpreted as `EPSG:4326`.
- `rotation` : rotation in degrees
- `theme` : map theme name (applied when present)

Example:
```
http://localhost:8089/qgis-map?x=139.01234&y=35.12345&scale=1000.0&rotation=0.00
```

Short form: values can be simplified (e.g. `x=139&y=35&scale=1000.0`) for presentation purposes.

Conversion rules:
- `scale` has priority when specified.
- `zoom` is estimated for web-map compatibility, but `scale` takes precedence.

4. Web distribution (KASUGAI Canvas export)

The plugin's built-in generated viewers (former `/qgis-map`, `/maplibre`,
`/map3d`) were **removed in v3.24.0** — viewing is consolidated into
KASUGAI Canvas. Web distribution now centers on the `.kasc`+`DATA/`
export; see §15 for details.

- Output: `kasugai_canvas.kasc`, `index.html`, `<engine>.html` ×6 (cesium/maplibre/openlayers/leaflet/gsimaps/navara), `project.json`, `bookmarks.xml`, `DATA/` (GeoJSON / native formats / .qml / copied tiles).
- Launcher HTMLs: redirect to the engine with `?kasc=<.kasc URL>` and auto-detect the engine in `./ ../ ../../ /` order (`CANVAS_BASE` overrides; when no engine is found they link to the hosted engine at `HOSTED_BASE`).

## 5–9. OGC services (removed in v3.29.0)

The WMS / WMTS・XYZ / WFS / `/maplibre-style` endpoints and their
internals (`wms_service.py`, `wmts_service.py`, `wfs_service.py`,
`sld_renderer.py`, `maplibre/`, ANGLE pipeline, WFS/WMTS caches)
were removed in v3.29.0. The plugin focuses on serverless
distribution (`.kasc`+`DATA/` export plus `/export-data/` serving).
See git history for the removed implementations.

## 10. Google Maps / Earth integration (removed in v3.30.0)

The Google Maps / Google Earth URL generation and parsing feature
(`_build_google_maps_url`, `_build_google_earth_url`,
`_parse_google_maps_at_url`, `_parse_google_earth_url`, the panel's
external-launch buttons, and the bridge `googleMapsUrl` /
`googleEarthUrl` / `openExternal` Google support) was removed in
v3.30.0. Google Earth links now live on the KASUGAI Canvas side
(basemap control). See git history for the removed implementations.

11. External Control parsing and behavior
- When `External Control` is enabled, received URLs are parsed and QGIS is navigated using `navigate_from_http`.
- If a URL was received prior to panel startup, the panel may auto-apply navigation depending on settings.
- Security: automatic navigation should be toggleable and logged (source IP and timestamp).

12. Theme support
- `theme` parameter applies a named map theme on navigation; `.kasc` also emits `theme:` lines.
- Only existing named themes are supported; missing themes fall back to no-theme behavior.

13. Rendering (`/screenshot`)
- `/screenshot` renders the current canvas MapSettings via `QgsMapRendererParallelJob` (canvas rotation included).
- Output size via `w`/`h` (clamped to 4096 px); rendering is serialized by `_render_lock` and times out after 30 s.
- Viewer zoom (per-client, stateless): `extent=xmin,ymin,xmax,ymax` renders that canvas-CRS range (literal `setExtent`, for re-rendering a previous `X-Map-Extent`); `screen=xmin,ymin,xmax,ymax` renders the region the client wants on screen — under canvas rotation it is internally converted to the inverse-rotated bounding rect so the rotated image covers the requested screen area; `bbox=cx,cy,fw,fh` renders a fraction-of-image window (center `cx,cy`, size `fw,fh` in 0..1) of a base image — the canvas render by default, or `base=<extent>`+`bw`/`bh` for chained zoom; `rot=<deg>` overrides the render rotation (`rot=0` = north-up image). Response headers: `X-Map-Extent` (actual `setExtent` range) and `X-Map-Corners` (world coordinates of the image's TL/TR/BL corners). `/present` is an OpenLayers (bundled `vendor/ol`) page: renders are requested with `rot=0` and the canvas rotation is reproduced as view rotation, so all gestures stay consistent in the rotated frame; re-renders happen on `moveend`.

14. CRS policy
- `.kasc` vector exports are normalized to `EPSG:4326` (native GPKG/Parquet/FGB references are handled client-side).
- Default permalink CRS when omitted is `EPSG:4326`.

15. Security and operations
- Default design allows external access; production deployments must restrict access via firewall or reverse proxy.
- `External Control` allows remote navigation; limit to trusted networks or require explicit approval flows.
- Enforce size limits on `/screenshot` requests (clamped to 4096 px per side).

16. Test & QA
Automated test candidates
- Unit tests for `server_manager.py` (port selection & binding behavior) and URL parsing.

Manual test steps
1. Install plugin in QGIS and enable `External Control`.
2. From another host, request `/qgis-map?x=...&y=...&scale=...` and confirm QGIS navigates.
3. Confirm `/screenshot` returns a canvas PNG and `/present` opens the share page.

CI note: QGIS modules (`qgis.core`, `PyQt5`) will not be available in typical CI; mock them where needed.

17. Implementation-file mapping
- `plugin.py` — main plugin logic and utilities.
- `panel.py` — panel UI and navigation controls.
- `panel_base.ui` — Qt Designer UI file.
- `server_manager.py` — embedded HTTP server start/stop and routing.
- `http_server.py` — low-level HTTP response helpers.
- `kasugai_export.py` — `.kasc`+`DATA/` export, registration and fallback URL building.
- `bridge.py` — AI/external control bridge.

18. Changelog highlights
- V2.x → V3.x changes summarize theme and rotation support.
- v3.24.0 removed the built-in generated viewers (`/qgis-map`/`/maplibre`/`/map3d` HTML).
- v3.29.0 removed the OGC services (WMS/WMTS/XYZ/WFS, `/maplibre-style`).

Notes
- After making server-side code changes, restart QGIS or the plugin process to reload module code; long-running Python processes do not auto-reload.

This file mirrors the Japanese `SPEC_JP.md`. If you modify `SPEC_JP.md` again, regenerate this English file to keep both versions in sync.
## 14. 投影 (CRS) ポリシー
- `.kasc` エクスポートのベクターは EPSG:4326 に正規化して出力する（ネイティブ参照の GPKG/Parquet/FGB はクライアント側で処理）。
- WMS は複数 CRS を受け付け、要求 CRS に従ってレンダリングする。
- `crs` を指定しないパーマリンクは `EPSG:4326` として解釈される。
- 座標変換は `QgsCoordinateTransform` を利用。プロジェクトによっては外部の proj 定義が必要となる場合がある。

---
## 15. KASUGAI Canvas 連携（送出）

QGIS プロジェクトのレイヤツリーを、KASUGAI Canvas のプロジェクト
（`.kasc` + `DATA/`）として書き出す機能。実体は `kasugai_export.py`。

### 起動経路

| 経路 | 呼び出し | 用途 |
|---|---|---|
| パネルボタン | `▶ Canvas` / `▶ WebView` ボタン (`plugin.py: on_kasugai_launch_clicked`) | 人手操作。パネルの `Engine:` コンボで起動エンジンを選択（QSettings `kasugai_engine` に保存）。`▶ Canvas`（route=`kasugai`）は**再エクスポートせず**既存の `.kasc` を登録・ブラウザ起動（未出力時はエクスポートを促すメッセージ）。Canvas 未検出時はボタンが「Install KASUGAI Canvas」表示となり、クリックでセットアップ(NSIS・.kasc 関連付けあり)/ポータブルZIP(展開のみ)を選んでバックグラウンドインストール後に起動へ合流。`▶ WebView`（route=`hosted`）は bridge `kasugaiExport(open_app=True)` と同じく出力→フォールバック→ブラウザ起動まで行う。CDN 行の `CDN:` コンボ（編集可、ZIP ボタンと同じ行）でホスト版チャンネルを選択（`stable`/`unstable`/カスタムURL、QSettings `kasugai_hosted_channel` に保存・設定ダイアログと共通） |
| パネルボタン | `Export` ボタン (`plugin.py: on_kasugai_export_clicked`) | 人手操作（ファイル出力のみ。Canvas 起動・登録はしない。ZIP は生成しない） |
| パネルボタン | `ZIP` ボタン (`plugin.py: on_kasugai_zip_clicked`) | エクスポート物一式を `kasugai_canvas_<チャンネル>.zip` としてブラウザダウンロード。`/export-data/` がオンデマンドで ZIP を生成して返す（要 HTTP サーバー稼働）。CDN コンボのチャンネルがファイル名に反映される |
| HTTP | `GET http://localhost:8089/kasugai` (server_manager._handle_kasugai) | 外部アプリ・AI からの一発起動。`?engine=` で起動エンジン指定可。応答は `{ok,url,via,dir,layers,tiles,engine}` JSON |
| Bridge | `bridge_call` の `kasugaiExport(output_dir, open_app, native_formats, hidden_as_off, embed_gpkg_style, emit_themes, emit_bookmarks, emit_launchers, engine, install, route, use_existing, emit_atlas)` | Live Driver 経由の AI 制御（MCP `qgis_bridge_call` / REST `/api/cmd` / JSONL）。`use_existing=True` で再エクスポートせず既存の `.kasc` のみ使用（未出力なら `code=not_exported`） |

### 出力フォルダ構成

```
<out_dir>/                    # 既定: <ドキュメント>/kasugai_canvas_qgis
├─ kasugai_canvas.kasc        # インスペクタ設定(外部プロジェクト登録対象)
├─ project.json               # {"title": ...}
└─ DATA/
   ├─ *.geojson               # 変換が必要だったベクター(EPSG:4326)
   ├─ *.gpkg                  # ネイティブ参照の GPKG(複製)
   ├─ *.parquet / *.fgb       # ネイティブ参照の Parquet/FGB(複製)
   ├─ *.csv / *.tsv           # duckdb: 参照の区切りテキスト(複製)
   ├─ <dir>/                  # ローカル 3D Tiles / ローカル XYZ タイルの複製(1GiB 上限)
   ├─ *.qml                   # 各ベクターレイヤの QGIS スタイル
   └─ *.svg / *.png 等        # .qml が参照するシンボル画像(QGIS 内蔵SVG・ローカル画像の複製)
```

### .kasc 行の生成規則

| QGIS 側 | .kasc 行 | 備考 |
|---|---|---|
| GPKG ソース(地理座標系) | `gpkg: グループ/名 | DATA/x.gpkg | on | table=<表> | style=DATA/x.qml` | ファイルを DATA/ へ複製。複数テーブルは1ファイルを共有 |
| GeoJSON/Parquet/FGB ソース | `geojson:` / `geoparquet:` / `flatgeobuf:` 参照行 | ローカルは複製、http(s) は URL をそのまま記述 |
| CSV/TSV(delimitedtext・ogr) | `duckdb: 名 | DATA/x.csv | on | format=csv | lon=<列> | lat=<列>` | ジオメトリ列は `geom=`。delimitedtext は URI の xField/yField/wktField を引き継ぎ、ogr CSV はヘッダから推定。delimitedtext で非地理座標系の場合は GeoJSON 変換 |
| フィルタ(subsetString)付き GPKG | `gpkg: … | where=<フィルタ>` | ネイティブ参照のままフィルタ維持 |
| フィルタ付き Parquet | `duckdb: 名 | DATA/x.parquet | on | format=parquet | where=<フィルタ>` | `geoparquet:` には where= が無いため duckdb: に切替 |
| フィルタ付き GeoJSON/FGB | GeoJSON(EPSG:4326)へ変換して `geojson:` 行 | フィルタを地物に反映して出力 |
| 3D Tiles レイヤ(QgsTiledSceneLayer) | `3dtiles: グループ/名 | <tileset.json URL or DATA/x/tileset.json> | on` | http(s) は URL 参照、ローカルはディレクトリごと DATA/ へ複製(1GiB 上限・超過は skipped) |
| XYZ タイルラスタ | `xyz:` 行。表示中の**最下段**のみ `base:` 行（既定ベースマップとして既定群の先頭に置く）。「背景図」「ベースマップ」「basemap」名のグループ内にある XYZ は位置・表示状態に関わらず全て `base:` 行（ベースマップ候補）として登録し、グループ名はタイトルから外す（配下のサブグループは残し、Canvas のベースマップ選択でグループ化表示される）。非表示の候補は `| off` 付きで出力。グループ名は設定ダイアログの Basemap Groups（QSettings `kasugai_basemap_groups`・カンマ区切り）で追加可能 | zmin/zmax → minZoom=/maxZoom=。不透明度は opacity=、限定範囲は bbox=西経,南緯,東経,北緯。縮尺表示は minScale=/maxScale= |
| XYZ ローカルテンプレート | `xyz:` 行(DATA/<dir>/{z}/{x}/{y}.png) | `file:///…/{z}/{x}/{y}.png` はタイルツリーごと DATA/ へ複製(1GiB 上限・超過は skipped) |
| WMS ラスタ(type=xyz 以外) | `wms: グループ/名 | <エンドポイントURL> | on | layers=, styles=, format=` | QGIS の WMS 接続 URI から url=/layers=/styles=/format= を抽出。Canvas 側が GetMap を 256px タイルへ分解して要求 |
| その他ベクター(SHP/PostGIS/WFS/メモリ等)・非地理座標系 | GeoJSON(EPSG:4326)へ変換して `geojson:` 行 | 再投影は warnings に記録 |
| 属性テーブルのみ(NoGeometry)・ローカルラスタ・ベクタータイル・メッシュ・点群・アノテーション等 | 出力せず `skipped` に種別/理由付きで記録 | |
| 非表示レイヤ | `hidden_as_off=True` 時のみ `| off` 付きで出力 | 既定(visible_only=True)では除外 |
| キャンバス | `cam:` 行(中心座標+概算高度+回転) | |
|| 保存済み3Dビュー(ローカル/グローブ) | `cam:QGIS3D <名>|lat|lon|h=|p=|d=` 行(注視点+dist/pitch/yaw→ENUオフセットでカメラ位置逆算: 高さ=dist·cos(pitch)・水平=dist·sin(pitch)・視線方位=360-yaw・p=pitch-90) + `terrain:` 行(垂直誇張/オフセット/陰影/ジェネレータ) + `scene3d:` 行(背景色/スカイボックス/影/SSAO/EDL・グローブは globe=on) + `light:` 行(平行光源の方位・仰角・強度・色) | 3Dビューが存在する場合のみ出力。シーンCRSはビューごとの `<qgis3d><crs>` を解決し、地心系(QGIS4グローブ・EPSG:4978等)はECEF→測地変換で対応。既定値相当の項目は省略 |
|| 3Dビューのアニメーション(`<animation3d>`キーフレーム) | `fly_geojson: QGIS3D <名> | DATA/anim3d_<slug>.geojson | speed=<m/s> | view=camera | step=<m>` 行 + カメラ軌道の LineString GeoJSON | 各キーフレーム(注視点+dist/pitch/yaw+時刻)のカメラ位置を計算してカメラ軌道にする。speed=軌道3D総延長÷アニメ時間。キーフレーム2個未満は出力しない |
| ベクターの3Dレンダラ(立ち上げ) | ベクター行へ `| extrude=<m>`(立ち上げ高さ)・`| z=<m>`(基準高さオフセット) を付与 | QgsVectorLayer3DRenderer のポリゴン/ラインシンボル。Canvas(Cesium)側で polygon の height/extrudedHeight へ反映 |
| ブックマーク | `bookmarks.xml`(qgis_bookmarks形式・EPSG:4326正規化) + `bookmark:` 行(プロジェクト+アプリケーション両方) | `emit_bookmarks=False` で抑制。Canvas 側が XML を読み込みカメラプリセットへ展開する |
| アトラス有効な印刷レイアウト | `fly_geojson: Atlas: <レイアウト名> | DATA/atlas_<slug>.geojson | speed= | pitch=-85 | height=0 | view=camera | step=` 行 | `emit_atlas=False` で抑制(v4.8.0〜)。各アトラスページの表示範囲(参照地図 extent)を巡回するプレゼン用フライパス。座標Z値にページを収めるカメラ高(楕円体高)を焼き込み、`properties.heightReference="MSL"` で地形加算を抑止、ページ名一覧は `properties.pages` へ。地図回転付きは warnings に記録のみ |

その他: `attr=` に QGIS レイヤの出典(attribution)を引き継ぐ。
全レイヤ行で `minScale=`/`maxScale=` に QGIS の「縮尺による表示」
(minimumScale=引き側限界・maximumScale=寄り側限界)を出力する。
Canvas 側は同じ範囲で表示/非表示を切り替える。
`.qml` 書き出し後、シンボルレイヤが参照する画像(SvgMarker/RasterMarker/
SVGFill/RasterFill 等の `name`/`imageFile`/`svgFile`/`file`)を実ファイルへ
解決して DATA/ へ複製し、.qml 内の参照を DATA/ 内のファイル名へ書き換える
(QGIS 内蔵SVGの `transport/…` 等の相対名は `QgsApplication.svgPaths()` で
解決。http(s)/data/base64: 参照はそのまま維持。解決不能は warnings 記録)。
`embed_gpkg_style=True` なら `saveStyleToDatabase` で GPKG の
`layer_styles` にも既定スタイルを保存する(**元ファイルを更新する**。
保存は DATA/ へのコピー前に行うため配布コピーにも layer_styles が
含まれ、同一 GPKG の複数レイヤも全レイヤ分が入る。
対象はローカル GPKG のみで、http(s) URL 参照の GPKG は対象外)。
`sql:` 行は QGIS 側に対応する任意クエリソースが無いため出力しない
（クエリ系は `duckdb:` の宣言的オプションで網羅する）。

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
  `.kasc`+`DATA/` は本サーバーの `/export-data/` から読む。https→localhost
  の fetch は Chrome Private Network Access 対象のため、サーバーは
  `OPTIONS` プリフライトに `Access-Control-Allow-Private-Network: true` で
  応答する。チャンネルは設定 `kasugai_hosted_channel`
  （`stable`/`unstable`/カスタムURL、既定 `stable`）で、
  パネルの `CDN:` コンボまたは設定ダイアログから変更する
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
## 16. セキュリティ・運用上の注意
- デフォルトで外部アクセスを許す設計だが、公開環境ではファイアウォールやプロキシでアクセス制御を厳格に行うこと。
- `External Control` を有効にしていると任意の外部URLで QGIS の表示が書き換わるため、信頼できるネットワーク内または追加の承認フローを用いることを強く推奨。
- ログを適切に出力し、受信元IP・タイムスタンプ・実行アクションを残す運用を推奨。

---
## 17. テスト・QA 手順
自動テスト候補:
- `server_manager.py` のユニットテスト: ポート選定・バインド挙動のモックテスト。
- URL パーサ（内部形式）の単体テスト（複数フォーマットのケース）。

手動テスト手順（QGIS 実環境）:
1. QGIS を起動しプラグインをインストール。
2. `Export` で `.kasc`+`DATA/` を出力し、パネルの `Engine:` でエンジンを選び `▶ Canvas` を押してブラウザでそのエンジンが開くことを確認（未出力時はエクスポートを促すメッセージが出る）。`▶ WebView` は出力→ブラウザ起動まで一発で行う（`/kasugai` と同じフォールバックが働く）。
3. `External Control` を ON にして、別ホスト（または同一ホスト）から `/qgis-map?x=...&y=...&scale=...` にアクセスして QGIS がジャンプすることを確認。
4. `/screenshot` でキャンバス PNG が返ることを確認。
5. `/present` ページがブラウザで開くことを確認。

テスト注意:
- CI 環境では `qgis.core` や `PyQt5` が無いため、これらをモックするかローカルでの手動確認が必要。

---
## 18. 実装ファイルと責務マッピング
- `plugin.py` — メインプラグインロジック、パーマリンク/ナビゲート、パネルイベント配線。
- `panel.py` — パネル UI 実装（Web配信グループ、ナビゲート、生成、外部制御トグル等）。
- `panel_base.ui` — Qt Designer の UI 定義。
- `server_manager.py` — 組み込み HTTP サーバーの起動/停止・ルーティング（`/kasugai` `/export-data/` `/present` `/present/state` `/screenshot` `/received` `/layouts` `/layout-pdf` `/<engine>/` 等）。
- `http_server.py` — HTTP 応答の低水準送信ユーティリティ。
- `kasugai_export.py` — KASUGAI Canvas 連携（`.kasc`+`DATA/` 生成、起動HTML生成、プロジェクト登録、コマンド送信、フォールバックURL構築）。
- `scale_zoom.py` — スケール/ズーム換算。
- `settings_dialog.py` — 設定ダイアログ（KASUGAI インストール先・ホスト版チャンネル・Basemap Groups）。
- `bridge.py` — AI/外部制御用ブリッジ（`kasugaiExport` 等）。

---
## 19. 変更履歴の要約（V2/V3 ハイライト）
- V2.0.0: WMS サポートと外部アクセス（0.0.0.0 バインド）を追加。
- V2.6.0: 投影定義と軸順情報を生成 HTML に埋め込み、座標表示の精度向上。
- V2.8.0: External Control の自動ナビゲート追加。
- V2.10.0: Google Earth `y` トークン対応とスケール推定の改善。
- V2.12.0: テーマ対応 WMS 出力（仮想マップビュー）。
- V- V3.0.0: MapLibre WFS + QGIS スタイル注入の安定化、ベーススタイルの相対URL化、ブラシ無しポリゴンの正しい境界線表示、単位正規化（mm/pt→px）を確立。

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
