# geo_webview — QGIS をサーバレス Web 配信するプラグイン（マルチエンジン対応）

開いている QGIS プロジェクトを `.kasc`+`DATA/` パッケージに出力し、
KASUGAI Canvas のマルチエンジン（Cesium / MapLibre / OpenLayers / Leaflet / GSI Maps / Navara）で
再生する QGIS プラグイン。出力物は静的ホスティングだけで配信できます。

## ドキュメント

- **[geo_webview ドキュメント（GitHub Pages）](https://yamamoto-ryuzo.github.io/qgis_live_harness/geo_webview/)** —
  連携構成図・主な機能・マルチエンジン・導入ガイド・技術資料
  （正本はこのフォルダの `docs/` 配下の HTML。パネルの `?` ボタンからも開けます）
- [INTEGRATION_JP.md](INTEGRATION_JP.md) / [INTEGRATION.md](INTEGRATION.md) — 外部クライアント連携方針（Re:Earth・ArcGIS）
- [SPEC_JP.md](SPEC_JP.md) / [SPEC.md](SPEC.md) — `.kasc` 行仕様・API・bridge
- [CHANGELOG.md](CHANGELOG.md) — 変更履歴

## クイックスタート

1. このフォルダを QGIS の `python/plugins/` に配置し、プラグインを有効化
2. パネル「Web配信」で【Export】→ `.kasc`+`DATA/`+`<engine>.html`+`index.html` を出力
3. 【▶Canvas】/【▶WebView】で即表示、【ZIP】で `kasugai_canvas_<ch>.zip` をダウンロードして静的ホストや CMS へ配置

ライセンス: GPL-3.0（[LICENSE](LICENSE) 参照）

## 免責事項

本システムは個人のPCで作成・テストされたものです。  
ご利用によるいかなる損害も責任を負いません。

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>
