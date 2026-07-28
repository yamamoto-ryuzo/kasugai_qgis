# kasugai_qgis

QGIS / QField 起動用ランチャー（Rust + AXUM）。v2.0.0 からは Web UI（ブラウザ）/ HTTP API / CLI で操作します。

- ドキュメント・ダウンロード: <https://yamamoto-ryuzo.github.io/kasugai_qgis/>
- 初回インストーラー: [kasugai_qgis-setup.exe](https://yamamoto-ryuzo.github.io/kasugai_qgis/public/kasugai_qgis-setup.exe)
- ライセンス: [GPL-3.0-only](LICENSE)

## 主な機能

- QGIS / QField の Web UI / CLI 起動
- プロファイル・プロジェクト・QGIS バージョンの切り替え
- ユーザーロール制御（Viewer / Editor / Administrator）
- クラウドドライブ自動割り当て（`drive_mappings`）
- ローカル自動同期（`local_sync`）
- NSIS ベースの自動更新
- Tauri サイドカーとして利用可能な AXUM HTTP API（`--server`）

詳細は [GitHub Pages](https://yamamoto-ryuzo.github.io/kasugai_qgis/) を参照してください。
