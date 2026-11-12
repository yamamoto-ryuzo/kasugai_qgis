# kasugai_qgis

QGIS / QField 起動用ランチャー（Rust + AXUM）。v2.0.0 からは Web UI / HTTP API で操作します。スタンドアロン起動時の UI は内蔵 WebView2 ウィンドウに `http://127.0.0.1:8500/` を表示します（要 WebView2 Runtime）。

- ドキュメント・ダウンロード: <https://yamamoto-ryuzo.github.io/kasugai_qgis/>
- 初回インストーラー: [kasugai_qgis-setup.exe](https://yamamoto-ryuzo.github.io/kasugai_qgis/public/kasugai_qgis-setup.exe)
- ライセンス: [GPL-3.0-only](LICENSE)

## 主な機能

- QGIS / QField の Web UI 起動
- プロファイル・プロジェクト・QGIS バージョンの切り替え
- ユーザーロール制御（Viewer / Editor / Administrator）
- クラウドドライブ自動割り当て（`drive_mappings`）
- ローカル自動同期（`local_sync`）
- NSIS ベースの自動更新
- 外部連携可能な AXUM HTTP API（URI 位置引数つき起動でヘッドレス動作）

詳細は [GitHub Pages](https://yamamoto-ryuzo.github.io/kasugai_qgis/) を参照してください。

# 免責事項

本システムは個人のPCで作成・テストされたものです。  
ご利用によるいかなる損害も責任を負いません。

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>
