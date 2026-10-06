# Changelog

## [2.2.1] - 2026-10-07

### Changed
- 「Axum サーバーを停止」ボタンを赤色に変更し、誤操作しにくい見た目にした
- サーバー停止の確認ダイアログに「停止するとこの画面は操作できなくなる」旨を追記（全10言語）
- サーバー停止後の案内画面を「再起動するか閉じるか」の選択肢が分かる文言に更新（全10言語）

## [2.2.0] - 2026-10-06

### Added
- カスタムプロトコル `kasugai-qgis:` を HKCU に自己登録し、サーバー停止後に残ったブラウザタブからランチャーを再起動できるようにした
  - サーバー未接続時に「ランチャーを再起動」ボタンを表示し、起動後は `/health` をポーリングしてタブを自動リロード
  - プロトコル URI は `Args` の位置引数 `uri` で受け取り、トリガーとしてのみ使用
- サーバー停止後にタブを `window.close()` で閉じる試行を追加。ブラウザにブロックされた場合は「このタブは閉じて構いません」の案内画面へ置き換え（QGIS 起動後 / サーバー停止ボタン / 更新適用の3経路）

### Changed
- サーバー未接続時のエラーメッセージを生の `Failed to fetch` から分かりやすい案内文へ変更（i18n キー `status_server_unreachable` を全10言語に追加）

### Fixed
- `qgis_settings.json` の `QgisSettings` への変換失敗がサイレントにデフォルト値へフォールバックしていた問題を修正し、ファイルパスと理由を stderr に出力するようにした

## [2.1.0] - 2026-10-06

### Added
- Web UI の多言語対応（i18n）を導入
  - `public/i18n.js` と 10 言語の辞書（en 正本 / ja, zh, zh-tw, ko, es, fr, de, pt, ru）
  - タブバーに言語切替セレクタを追加（localStorage で永続化、初期値はブラウザ言語から検出）
- AGENTS.md を追加（作業ルール・テスト手順・言語方針）

### Changed
- 起動タブのフィールド順を プロジェクト→プロジェクトファイルバージョン→QGIS バージョン に変更
- プロジェクトのバージョンに一致する QGIS が無い場合、メッセージを出してシステム既定（.qgs 関連付け）へフォールバックする旨を明示

### Fixed
- QGIS バージョンが未選択になる問題を修正（レジストリ取得の 8.3 短縮パスを正規化し、設定値が選択肢に一致しない場合は先頭を選択）
- `GET /update` が tokio パニックで空応答になる問題を修正（`check_nsis_update` を `spawn_blocking` へ移動）

## [2.0.5] - 2026-10-06

### Changed
- QGIS 起動後（`POST /launch`）にランチャーサーバーを自動停止するように変更
- Web UI の起動時メッセージをサーバー自動停止の案内に更新

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
