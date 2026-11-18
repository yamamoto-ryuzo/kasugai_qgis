# geo_webview — Serverless web distribution for QGIS (multi-engine)

Exports the open QGIS project as a `.kasc`+`DATA/` package playable on the
KASUGAI Canvas multi-engines (Cesium / MapLibre / OpenLayers / Leaflet / GSI Maps / Navara).
The output runs on plain static hosting.

## Documentation

- **[geo_webview documentation (GitHub Pages)](https://yamamoto-ryuzo.github.io/qgis_live_harness/geo_webview/)** —
  integration architecture, features, multi-engine, getting started, technical reference
  (Japanese; the HTML under `docs/` is the official documentation — also reachable via the panel `?` button)
- [INTEGRATION.md](INTEGRATION.md) / [INTEGRATION_JP.md](INTEGRATION_JP.md) — external client integration policy (Re:Earth / ArcGIS)
- [SPEC.md](SPEC.md) / [SPEC_JP.md](SPEC_JP.md) — `.kasc` line spec, API and bridge reference
- [CHANGELOG.md](CHANGELOG.md) — change history

## Quick start

1. Place this folder under QGIS's `python/plugins/` and enable the plugin
2. Panel **Web Distribution** → 【Export】writes `.kasc`+`DATA/`+`<engine>.html`+`index.html`
3. 【▶Canvas】/【▶WebView】for instant preview, 【ZIP】to download `kasugai_canvas_<ch>.zip` for a static host or a CMS

License: GPL-3.0 (see [LICENSE](LICENSE))

## Disclaimer

This system was created and tested on a personal computer.  
We accept no liability for any damage arising from its use.

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>
