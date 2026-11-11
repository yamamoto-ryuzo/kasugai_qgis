# Changelog

All notable changes to the QGIS Legend View plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.6.4] - 2026-10-21

### Maintenance
- try/except/pass 5箇所に # nosec B110 を付与(設計上の許容を明示)

## [2.6.3] - 2026-10-21

### Fixed
- Qt6互換性チェック対応: 非スコープ列挙型をスコープ化
  (Qgis.*→Qgis.MessageLevel.* 等3箇所)

## [2.6.2] - 2026-10-21

### Security
- plugins.qgis.org セキュリティスキャン対応: LOW指摘
  (try/except/pass)はレビュー済みの常套パターンとして
  同梱 `.bandit` 設定で抑制(ZIP内検出により
  "Validated (configured)" ステータス想定)

### Maintenance
- flake8指摘を整理: bare `except:` を `except Exception:` に、
  `== None`/`not x is None` を `is None`/`is not None` に修正、
  未使用import除去。残る慣習的指摘(長行E501、qt_compat/
  resources_rcの星import等)は同梱 `.flake8` 設定で明示抑制

## [2.6.1] - 2026-10-19

### Changed
- `create_zip.py` が metadata.txt changelog に挿入する日本語プレースホルダ
  `(ここに変更内容を記載)` を英語 `(describe changes here)` に変更。

## [2.6.0] - 2026-10-19

### Changed
- 翻訳方式を `i18n/<lang>.json` に移行(Harness横断の方針変更)。
  `.ts`/`.qm`・`i18n/LegendView.pro`・Makefileのtrans系ターゲットを廃止し、
  `{"context": {"英語ソース": "翻訳"}}` のJSONカタログを新設。
  `i18n_json.py`(全プラグイン共通ローダ)の `install_translator()` で
  起動時ロードに統一。

## [2.5.0] - 2026-10-18

### Added
- 採用言語セット(AGENTS.md)に合わせ hi/pt/ru の翻訳カタログ
  (`i18n/LegendView_<lang>.ts`/`.qm`)を追加。既存の
  de/es/fr/it/ja/zh と合わせ全9言語を同梱。

## [2.4.0] - 2026-10-18

### Changed
- 翻訳カタログ(`.ts`)を最新ソースから再抽出し、日本語および
  既存言語(de/es/fr/it/zh)の全メッセージを翻訳済みに更新。
  各言語の `.qm` を再コンパイル。

## [2.3.0] - 2026-10-18

### Changed
- ドックウィジェットの追加時、同じドックエリア(右側)に既存パネルが
  あれば `QMainWindow.tabifyDockWidget` でタブ化して追加するように変更
  (`restoreState` → `tabifyWithExistingDock` 新設。
  可視ドックを優先し、非表示のみの場合はそれにタブ化。
  既存パネルが無ければ従来通り単独追加。
  QGIS保存状態の復元に成功した場合やフローティング時は対象外)

## [2.2.0] - 2026-10-18

### Changed
- `metadata.txt` の `qgisMinimumVersion` を 3.40 → 4.0 に更新
  (QGIS4以降専用。`qgisMaximumVersion=4.99`・`supportsQt6`は継続)。
  説明文の対応範囲表記も QGIS 4.x に修正

### Removed
- **Qt5サポートを完全削除**: `qt_compat.py` をQt6専用に書き換え、
  PyQt5フォールバック・バージョン分岐(`is_qt5`/`is_qt6`)を除去。
  `qt_compat_new.py`・`resources_rc_qt5.py`・`resources_rc_qt5_test.py`・
  `metadata_qt6_only.txt` を削除。非スコープenum
  (`Qt.transparent`/`Qt.ItemIsEditable`)もQt6 enum形式に修正
- `version.py`/`version_manager.py` の互換性情報をQGIS4/Qt6専用に更新
- 旧upstream由来の `README.txt` / `README.html` を削除(README.md に統合済みのため不要)
  (version.py の値が古かったため 2.2.0 に同期)

## [2.1.0] - 2026-10-18

### Added
- AI/外部制御用ブリッジ(`bridge.py` の `LegendViewBridge`)を新設し
  `plugin.bridge` に配線。`qgis_live_driver` の `bridge_call`
  (ファイルJSONL / REST /api/cmd / MCP `qgis_bridge_call` /
  AIアシスタントパネル)と `describe_plugins` カタログから利用可能。
  メソッド(JSON文字列返却): `pluginInfo` / `status` / `openDock` /
  `closeDock` / `listDatasets` / `selectDataset` / `legend` /
  `opacity` / `listStyles` / `setStyle` / `selectCurrentLayer` /
  `registerCurrentLayer` / `legendVariables`
- 機能変更なし(UI操作は従来通り)

## [2.0.17] - 2026-10-18

### Changed
- QGIS Live Harness (`qgis-plugin/QGIS-legendView-main`) への組み込み
  - upstreamは「repoルート=プラグイン」構造のため `C:\devin\QGIS-legendView` のcloneとコピーで同期
- 機能変更なし（ドキュメント・管理構成のみ）

## [2.0.2] - 2025-07-20

### Changed
- Currentボタンの幅を1.5倍に拡大
- legend_view_dockwidget_base.uiのUI調整
- 各言語翻訳ファイルの構造修正・再生成（.ts/.qm）
- ドイツ語・イタリア語翻訳ファイルの再構築
- lreleaseによる全言語の.qm再生成
- 最新の翻訳・UI修正を反映したZIPパッケージ作成

### Fixed
- 多言語翻訳抽出・反映の不具合修正
- .tsファイルの重複・壊れたXML宣言の整理
- Currentボタンの翻訳が抽出されない問題の修正

### Added
- CHANGELOG.mdのバージョン管理手順明記
- バージョン管理スクリプトの利用例をREADME等に追記

---

## [Unreleased]

## [2.0.1] - 2025-07-13

### Fixed
- Added missing LICENSE file to plugin package
- Added README.md to plugin package for better documentation
- Enhanced ZIP package validation system

### Added
- Plugin package validator script (validate_package.py)
- Comprehensive package validation with error reporting
- Improved packaging system with all required files

## [2.0.0] - 2025-07-13

### Added
- Qt5/Qt6 compatibility support
- Multi-language support (Japanese and English)
- Python-based translation fallback system
- Automatic Qt version detection
- Comprehensive version management system
- Improved error handling and robustness

### Changed
- Default interface language changed to Japanese
- Enhanced translation system with fallback mechanisms
- Improved compatibility across QGIS versions (3.0 to 3.30+)
- Updated plugin architecture for better maintainability

### Technical Improvements
- Added `qt_compat.py` for Qt version compatibility
- Implemented `version.py` for centralized version management
- Added `translations.py` for Python-based translation fallback
- Enhanced ZIP packaging system with version awareness

### Fixed
- Translation issues in Japanese interface
- Qt version compatibility problems
- Plugin loading errors in different QGIS versions

## [1.0.0] - 2020-10-28

### Added
- Initial release
- Basic legend display functionality
- Dockable widget interface
- Project variable-based layer selection
- Support for vector and raster layers
- Opacity control
- Named style support

### Features
- Display selected layer legends in a compact widget
- Configure display order using project variables
- Support for various layer types and symbology
- Integration with QGIS layer tree

---

## Version Format

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** version for incompatible API changes
- **MINOR** version for backward-compatible functionality additions  
- **PATCH** version for backward-compatible bug fixes

Additional labels for pre-release and build metadata:
- **alpha**, **beta**, **rc** for pre-release versions
- **build** metadata for development builds
