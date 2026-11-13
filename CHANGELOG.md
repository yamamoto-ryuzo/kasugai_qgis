# Changelog

## [Unreleased]

### Added
- Web UI: 各要素にホバー時のポップアップ説明（ツールチップ）を追加。`i18n.js` に `data-i18n-title` 属性による title 属性の翻訳機能を追加し、全タブ・フォーム・ボタン（動的生成される drive_mappings パネル・path_aliases 行を含む）に説明文を設定
- Web UI: フォルダパス入力欄に「参照…」ボタンを追加し、`GET /api/pick-folder`（`rfd` によるネイティブのフォルダ選択ダイアログ）でフォルダを選択可能に。対象は sync_src / sync_dst / local_cache / robocopy_src / project_root / パスエイリアス
- Web UI: `GET /api/drive-letters` を追加し、drive_mappings の `drive` を未使用ドライブレターのドロップダウンで選択可能に（設定済みレターは使用中でも候補に残る）
- Web UI: ヘッダー右上に「ヘルプ」リンクを追加し、`GET /api/open-docs` でドキュメントサイト（GitHub Pages）を既定ブラウザで開けるようにした
- Web UI: path_aliases サブタブに用途説明（名前付きパス置換・BOX 既定値・環境変数可）を追加
- パスエイリアス画面を「クラウドパス」ステータスページに変更。BOX Drive / OneDrive（個人・法人）/ Google Drive for Desktop / SharePoint（ライブラリ）の準備手順・エイリアス基準・この PC で検出された実際の解決結果を `GET /api/cloud-paths` で表示（ユーザー編集 UI は廃止、path_aliases は生 JSON でのみ編集）
- `resolve_path` の組み込みエイリアスを拡張（既存の BOX に加え ONEDRIVE=%OneDrive%、ONEDRIVECOMMERCIAL=%OneDriveCommercial%、GDRIVE=検出した Google ドライブのマイドライブ）。path_aliases の同名定義で上書き可能
- Web UI: local_sync サブタブに起動時ミラー同期の仕組みを説明する注記を追加し、各フィールドラベル・ツールチップを実態に即した文言に修正。sync_src / sync_dst が空白の場合 project_root を使うことをプレースホルダで明示。推奨利用方法（同期先をドライブ割当して QGIS の参照先にすると誤編集も次回起動でリセットされる）を注記と docs/local-sync.html に明記

### Changed
- local_sync: バージョン判定による差分同期を廃止し、汎用のフォルダミラー（SYNC_SRC → SYNC_DST を robocopy /MIR、EXCLUDE_DIRS で除外）に簡素化。`qfield_version` / `qgis_version` / `portable_profile_version` の設定キーと `qgislocalsync.config` の `QFIELD_VERSION` / `QGIS_VERSION` / `PORTABLE_PROFILE_VERSION` は廃止（解釈されなくなる）。QField*/QGIS*/portable_profile の特別扱いと LOCAL_QFIELD_VERSION / LOCAL_QGIS_VERSION / portable.ver の読み書き、kasugai_qgis_version による自己更新判定を削除。Web UI からもバージョン入力欄を撤去
- Web UI: 未翻訳だった要素を i18n 化。詳細設定タブの各フィールドラベルと起動タブのロール選択肢（Viewer / Editor / Administrator）を10言語辞書に登録
- Web UI: 表示文言の規約を統一。ナビゲーション（タブ・サブタブ）とフィールドラベルは自然な訳文のみを表示し、JSON キー名はツールチップ先頭の `key:` 表記で確認できるようにした
- Web UI: `mode`（subst / sync / mount）をドロップダウン化し、`read_only` は mount 選択時のみ有効（他モードではグレーアウト）に変更。drive_mappings パネル内に subst 系と rclone 系フィールドの区切り線を追加
- Web UI: path_aliases が空のとき空の入力行を1つ表示するように変更

### Fixed
- Web UI: drive 未入力のパネルでモード等を変更すると入力中の値が初期化される問題を、下書き（driveDrafts）として保持するよう修正

## [2.5.5] - 2026-11-13

### Fixed
- 配布プロファイルのシード元を exe 直下の `profiles/` に固定。これまで `resolved_settings_dir`（実効 `qgis_settings.json` の所在）の `profiles/` を使っていたため、`project_root` が共有ドライブ上にあり `qgis_settings.json` を含む環境では `project_root\profiles` が配布元となり、インストーラーで更新した `$INSTDIR\profiles` が `%APPDATA%` へ反映されなかった。起動時シード・バンドルプラグイン同期・「プロファイル強制更新」(reset) のすべてで exe 直下を正本とするよう修正し、解決した配布元パスを起動ログに出力するようにした

## [2.5.4] - 2026-11-13

### Added
- 起動時に配布バンドル同梱プラグインをインストール済みプロファイルへバージョン同期する機能を追加。`profiles/<QGIS*>/profiles/<name>/python/plugins/<id>` の `metadata.txt` バージョンを比較し、バンドル版が新しい場合のみそのプラグインをミラー上書き（削除→再コピー）する。junction/symlink 配置（ハーネス開発モード）は外部管理のため対象外。あわせて `[PythonPlugins]` に有効化キーが無いプラグインを `=true` で追記する（既存の `=false` は尊重）
- `run.py --bump X.Y.Z --full-update` オプションを追加。`update.json` の `full=true` を設定し、既存インストールが差分 EXE ではなく全体インストーラー（プロファイル等のデータ込み）を取得するようにする。`download/` 配下を更新したリリースで指定する

### Changed
- 全体インストーラーが `$INSTDIR\profiles` を配置する前に旧バンドルを削除するように変更（配布物から消えたファイルが残存しない）

## [2.5.3] - 2026-11-13

### Changed
- 配布プロファイル（`download/profiles/QGIS4/profiles/geo_custom`）を現行プロファイルへ更新。qfieldsync・Qgis2threejs を新規同梱し、QGIS4.ini のプラグイン有効フラグを更新（qgis_live_driver/geo_excel/geo_userfunc が新規インストール時から有効になる）

## [2.5.2] - 2026-11-13

### Fixed
- プロジェクト選択が空になる問題を修正。`project_root` が `Q:\` 等のドライブルートの場合 `/projects` が `Q:\\dir\file.qgs` のような二重区切りパスを返し、保存済み `current_project`（`Q:\dir\file.qgs`）と文字列が一致せず復元に失敗していた。`/projects` の返却パスを `components()` で正規化し、あわせて保存値が選択肢に一致しない/未設定の場合は先頭候補を自動選択するようにした

## [2.5.1] - 2026-11-13

### Changed
- `POST /launch` 実行時に起動選択（プロファイル・ロール・QGIS 実行ファイル・プロジェクト）を `qgis_settings.json` へ自動保存するようにした。従来は「起動設定を保存」ボタンを押した場合のみ `current_project` が記録されていたため、次回起動時にプロジェクト選択が毎回空になっていた。起動に成功した時点の選択が次回起動の初期値になる

## [2.5.0] - 2026-11-13

### Fixed
- Web UI: `i18n.js` の読み込みに失敗した場合（サーバー再起動直後にキャッシュのページが描画された場合等）に初期化スクリプト全体が停止し、言語セレクタを含む全ドロップダウンが空になる問題を修正。`i18n.js` 未読込時は `/health` の復旧を待ってページを自動リロードし、初期データ読み込み（`initI18n` + `reloadAll`）も最大30回リトライするようにした
- 配布設定 `download/qgis_settings.json` の `current_project` が表示用文字列になっていたのを実パスに修正

### Changed
- GUI 起動時のサーバー起動待ちを `GET /health` ポーリング（最大60秒）から mpsc チャネルによる bind 完了通知（最大90秒）へ変更。同一プロセス内のスレッド間起動なのに HTTP ポーリングしていた冗長さを解消し、ポート奪取リトライ込みの待ち時間にも余裕を持たせた
- GUI 表示を WebView2 専用に変更し、既定ブラウザへのフォールバックを廃止（`opener` 依存・WebView2 Runtime 検出ロジックを削除。Runtime 非搭載時はエラーメッセージを出して終了）
- WebView2 ウィンドウを 1200×850 から 800×850 に縮小（コンテンツの max-width:720px に合わせ、右側の余白を解消）
- `copy_profiles_at_startup` を簡素化: インストール済み QGIS のバージョン検出と `profiles\QGIS{major}\` ソース解決を廃止し、起動フォルダの `profiles\` 直下を `%APPDATA%\QGIS\` へそのままコピーする方式に変更（`profiles\QGIS4\` → `%APPDATA%\QGIS\QGIS4\`）。`startup.py` 掃除の走査先を `<ver>\profiles\<name>\python\startup.py`（QGIS が実際に読む階層）に修正
- ドキュメントを `index.md` から `docs/` 配下の静的サイトへ移行（左サイドバーナビ + ページ分割 + Mermaid 起動フロー図）。ルート `index.html` は `docs/` へのリダイレクトに変更

### Added
- `LICENSE`（GPL-3.0）と `THIRD_PARTY_LICENSES.md`（依存・同梱ソフトウェアのライセンス一覧。商用利用可否の整理を含む）を追加

### Fixed
- 配布プロファイルのコピー元を `project_root` 基準から `resolved_settings_dir`（実効 `qgis_settings.json` のあるディレクトリ＝インストール先）へ統一。`project_root` をプロジェクト用ドライブ等の別ディレクトリに設定している環境で `<project_root>\profiles` が見つからずシードがスキップされ、`--profile` が空の新規プロファイルを指していた問題を修正（`GET /profiles` の列挙元と一致させた）。`POST /reset` の再コピー元も同様に統一

### Removed
- CLI モード（`--cli`）を廃止。CLI 起動専用だった `--profile` / `--qgis-executable` / `--dev` 引数もあわせて削除し、QGIS の起動は Web UI / HTTP API（`POST /launch`）経路に統一
- ヘッドレス API サーバーモード専用の `--server` 引数を廃止。通常起動は常に WebView2 ウィンドウを開き、ヘッドレス起動は URI 位置引数に統一
- `kasugai-qgis:` カスタムプロトコル（HKCU レジストリ登録・「停止後に残ったブラウザタブからの再起動」経路）を廃止。Web UI の「ランチャーを再起動」ボタンとプロトコル遷移・`/health` ポーリング復帰ロジックも削除。外部からの起動は呼び出し側が `qgis_launcher.exe <URI>` を spawn する方式に統一（URI 位置引数はヘッドレス化トリガーとして存続）
- デバッグ用の `--list-qgis` 引数を廃止（検出一覧は Web UI / `GET /qgis` で確認可能）
- `--open-browser` 引数を廃止（GUI 起動が既定動作のため no-op 化していた。インストーラーのショートカット・完了ページ・更新後再起動からも除去）
- QGIS Live Harness 連携の開発モード（`dev_mode` 設定・起動タブの「開発モード」チェックボックス・`WEBENGINE_*` 環境変数注入）と `GET /live-sessions`（稼働セッション表示）を廃止。harness 連携は手動で環境変数を設定して行う運用とする

## [2.3.0] - 2026-10-22

### Changed
- スタンドアロン起動時の UI 表示を既定ブラウザ（`opener`）から内蔵 WebView2 ウィンドウ（wry/tao）へ変更。既定ブラウザの関連付けに依存せず確実に起動し、ウィンドウを閉じるとサーバーごと終了する。WebView2 Runtime 非搭載環境のみ従来通り既定ブラウザへフォールバック
- 引数なし起動でも UI ウィンドウが開くようにした（従来はサーバーのみ起動して何も表示されなかった）
- `kasugai-qgis:` プロトコル経由の起動は従来通りヘッドレス（ウィンドウを開かない）。残ったタブ・KASUGAI 埋め込みペインが自ら `/health` をポーリングして復帰する方式を維持

### Added
- QGIS Live Harness 連携の開発モード（`dev_mode` 設定 / 起動タブの「開発モード」チェックボックス / CLI `--dev`）。QGIS 起動時に `QTWEBENGINE_REMOTE_DEBUGGING`・`QTWEBENGINE_CHROMIUM_FLAGS`・`WEBENGINE_AUTOOPEN`・`WEBENGINE_LIVE_DIR`・`WEBENGINE_LOG_PATH` を注入し、junction 配置（dev モード）確定時のみ `WEBENGINE_DEV_SRC` も立てる。harness ルートは `KASUGAI_HARNESS_DIR` または exe 祖先の `qgis-plugin/qgis_live_driver/metadata.txt` から検出
- `GET /live-sessions`：`~/.qgis-live` レジストリから稼働中の qgis_live_driver セッションを返し、起動タブに稼働中 PID を表示（i18n キー `label_dev_mode` / `live_session_active` / `live_session_none` を全10言語に追加）
- `scripts/sync_bundle_plugins.py`：`<harness>/qgis-plugin/kasugai_qgis` 配置時、同梱プラグイン（geo_search・geo_webview・geo_report・geo_import・QGIS-legendView-main）を repo 側の正本へミラー同期。`run.py --build` に統合、`--sync-plugins` で単独実行も可

### Changed
- `download/profiles` 同梱の repo 管理プラグインを repo 側の最新へ更新（geo_search 3.3.2→4.4.0、geo_webview 3.10.3→3.17.0、geo_report 2.2.6→2.9.0、geo_import V2.3.45→2.10.0、QGIS-legendView-main 2.0.16→2.6.1）

### Fixed
- `--cli` 起動時に配布プロファイルのコピー（`copy_profiles_at_startup`）が実行されず、未シード環境で `--profile` が空プロファイルを指していた問題を修正
- `GET /profiles` が配布側 `profiles/QGIS{major}` バージョン別コンテナや空ディレクトリをプロファイル名として誤列挙していた問題を修正（`QGIS{major}/profiles/` 内を実プロファイルとして列挙）
- `GET /live-sessions` で dead セッションの stale レジストリ（`~/.qgis-live/*.json`）を自動削除するようにした（起動直後120秒以内のファイルは誤削除防止のため保持）

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
- インストーラー・ショートカットを AGENTS.md 仕様に合わせて整備
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
