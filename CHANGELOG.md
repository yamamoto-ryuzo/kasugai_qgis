# Changelog

## [2.0.2] - 2026-07-29

### Added
- EXE アイコン埋め込み（`build.rs`）
- ファビコン配信用エンドポイント
- ブラウザ自動起動機能
- 多重起動防止機能

### Changed
- Windows サブシステム化
- インストーラー・ショートカットを AGENT.md 仕様に合わせて整備
  - ショートカットに `--open-browser` オプションを付与
  - `RequestExecutionLevel` を `admin` に修正
- `update.json` を 2.0.2 に更新

## [2.0.1] - 2026-07-29

### Removed
- QGIS3 プロファイルサポートを削除
  - `download/profiles/QGIS4/profiles/geo_custom/QGIS/QGIS3.ini` を廃止

### Changed
- QGIS バージョン自動検出と QGIS4 プロファイル配信を一本化
- Web UI (`public/index.html`) を QGIS4 仕様に更新
- `index.md` ドキュメントを 2.0.1 仕様に更新
- `update.json` のバージョンを 2.0.1 に更新

## [2.0.0] - 2026-07-29

### Added
- AXUM ベースの HTTP API サーバー機能を追加
  - `GET /` — 操作 UI (`public/index.html`) を返す
  - `GET /health` — 生存確認
  - `GET /settings` / `POST /settings` — 設定読み書き
  - `GET /profiles` / `GET /projects` / `GET /qgis` — 選択候補一覧
  - `POST /launch` — QGIS 起動
  - `POST /reset` — プロファイル初期化
  - `GET /project-version` — プロジェクトファイルの QGIS バージョン取得
  - `GET /update` / `POST /update/apply` — 手動更新確認・適用
  - `GET /api/v1/server/info` — サーバー情報取得
  - `POST /api/v1/server/stop` — サーバー停止
- ブラウザベースの操作 UI (`public/index.html`)
  - タブ形式：起動 / 探索パス / 詳細設定 / 設定
  - プロファイル・QGIS バージョン・プロジェクトのドロップダウン選択
  - 生 JSON エディタによる `qgis_settings.json` 直接編集
  - `project_root` と API 待ち受けポートの編集・保存
  - サーバー停止ボタン
- 新しい CLI 引数 `--server` / `--port`（Tauri サイドカー対応）

### Changed
- API サーバーモードは `--server` オプションで有効化。未指定時は QGIS を通常起動する
- 待ち受けポートのデフォルトを 8500 に統一し、`qgis_settings.json` の `api_server_port` も参照
- `project_root` 解決時、対象フォルダ内に `qgis_settings.json` があれば再読み込み
- `reset_profiles` およびローカル自動同期の対象ディレクトリを `project_root` に統一

### Removed
- FLTK ベースの GUI を削除
- `fltk` 依存と `gui` feature を削除

## [1.4.1] - 2026-07-25

### Changed
- バージョンを 1.4.1 に更新

## [1.4.0] - 2026-07-25

### Added
- NSIS ベースの自動更新機能を追加
  - `qgis_settings.json` に `update_url` と `update_check` を設定することで、起動時にリモートの `update.json` を確認
  - 新しいバージョンがあれば NSIS インストーラーをダウンロードして実行し、自身を更新
  - 更新後は新しいプロセスを起動して終了する
- GitHub Pages 用の標準更新 URL を設定
  - `update_url`: `https://yamamoto-ryuzo.github.io/kasugai_qgis/update.json`
- `installer/setup.nsi`: 本体 `qgis_launcher.exe` のみを更新する軽量 NSIS インストーラースクリプト
- `installer/build.bat`: NSIS インストーラー生成バッチ
- `update.json`: GitHub Pages 配信用更新情報ファイル
- `download/kasugai_qgis_1.4.0_x64-setup.exe`: 初版リリース用 NSIS インストーラー

### Changed
- `download/qgis_settings.json` の例に `update_url` と `update_check` を追加

---

## [1.x.x] 以前

- QGIS / QField 起動ランチャー機能
- プロファイル・プロジェクト・QGIS バージョン選択 GUI
- ユーザーロール制御（Viewer / Editor / Administrator）
- クラウドドライブ自動割り当て（`drive_mappings`）
- ローカル自動同期（`local_sync` / `qgislocalsync.config`）
