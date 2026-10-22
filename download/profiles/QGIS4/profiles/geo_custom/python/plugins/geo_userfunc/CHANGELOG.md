# CHANGELOG — geo_userfunc

## 1.0.4

- GeoSuiteツールバーの管理アクションをアイコン表示に変更。
  `icon.png`(ƒ(x)グリフ)を同梱してQActionへ設定し、
  テキスト表示だったツールバーボタンをアイコンボタン化。
  metadata.txt にも icon= を登録(配布サイト表示用)

## 1.0.3

- try/except/pass 3箇所に # nosec B110 を付与(設計上の許容を明示)

## 1.0.2

- Qt6互換性チェック対応: 非スコープ列挙型をスコープ化
  (Qgis.*→Qgis.MessageLevel.* 等2箇所)

## 1.0.1

- **plugins.qgis.org セキュリティスキャン対応**:
  `sources.json` の upstream 更新(`library.py`)と管理ダイアログの
  URL取得(`manager_dialog.py`)の `urlopen` に http/https スキーム
  検証を追加(file:等のスキームを拒否)。
  ユーザーコード実行の `exec` は主目的のため `# nosec B102` で明示抑制
- LOW指摘(try/except/pass)はレビュー済みとして同梱 `.bandit`
  設定で抑制
- flake8指摘を整理: bare `except:` を `except Exception:` に修正、
  未使用変数を整理。seed同梱の functions/user_functions.py
  (upstream由来、星importがAPI面)の指摘は同梱 `.flake8` 設定で明示抑制

## 1.0.0

- 初版。ユーザー定義Pythonコードのライブラリ管理プラグイン
- `<profile>/python/geo_userfunc/` の `*.py` をASTで型分類:
  - `@qgsfunction` → 式エンジンへ登録(関数型)
  - `openProject`/`saveProject`/`closeProject` → プロジェクト信号へ配線(フック型)
  - `main(context)` → 手動実行マクロ(メニュー/bridge run)
- 共有レジストリ(`plugin.registry`)で他プラグインのマクロを一元管理
  (pull: `register_user_functions(registry)` 規約の探索 / push: 直接登録)
- bridge(`GeoUserfuncBridge`)でAI制御にフル対応:
  `listFunctions`/`listMacros`/`run`/`evalExpression`/`readFunction`/
  `saveFunction`/`deleteFunction`/`setEnabled`/`reload`/
  `updateFromUpstream`/`status`/`openManager`
- 管理ダイアログ(一覧/有効化/編集/フォルダ表示/URL取得/upstream更新)、
  GeoSuite共有ツールバーに起動アクションを集約
- 初期ライブラリとして QGIS_user_function(upstream)の `python` を
  `user_functions.py` として同梱・初回シード
  (sources.json による upstream 追従更新対応)
