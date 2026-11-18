# CHANGELOG — geo_userfunc

## 1.0.9

- 同梱関数に `line_width(base, minimum, ref_scale, scale)` を追加。
  縮尺連動の線幅(mm)を返す式関数で、基準縮尺では base mm、
  ズームアウトで base*ref_scale/scale に反比例・minimum で打止め、
  ズームイン側は base で頭打ち
  (`clamp(minimum, base*ref_scale/scale, base)` と等価)。
  KASUGAI Canvas の `EXPR_FUNCS.line_width` と同一の縮尺則で、
  `.kasc` エクスポート QML の `line_width(...)` DD が
  QGIS・Canvas 両側で同じ値に評価される
- **組込み式展開宣言 `@expr:`** を導入。`@qgsfunction` 関数の
  docstring に `@expr: <式テンプレート>`（`{引数名}` プレースホルダ付き）
  を書くと、`analyze_source` が `params`(位置引数名)と `expr` を抽出し、
  bridge `expansions()` で
  `{register_name: {args, expr, file}}` として公開する。
  geo_webview の QML エクスポートがこれを使って QML 内の
  ユーザー関数呼出しを組込み式へ書き換える
  （配布物を Canvas 関数実装不要の自己完結形にするため）

## 1.0.8

- **実行履歴**: bridge `run`/`evalExpression` の呼出を関数名・引数・
  ok/エラー・所要時間(ms)付きで `<profile>/geo_userfunc_history.jsonl`
  へ記録し、bridge `history(fn, limit)` で新しい順に参照できる
- **単体テスト実行**: bridge `testFunction(name, cases=[{args,expect}])`
  で式関数(`name(args...)` の式評価)/マクロ(`context['args']` 経由の
  main 実行)を複数ケースまとめて実行し pass/fail 表を返す。
  管理ダイアログに Test/history ペイン(対象名・cases JSON・
  Run tests/Show history・結果表示)を追加
- **依存情報**: bridge `dependencies(name)` でライブラリ内ファイルが
  参照する他プラグイン(`plugins['id'].bridge.m()`・束縛変数経由含む)を
  AST から抽出し `{plugin_id: {methods:[...]}}` で返す
- 純粋ロジックは QGIS 非依存の `history.py`(JSONL読書)と
  `deps.py`(AST抽出)に分離し単体テスト可能にした

## 1.0.7

- 個別利用時にGeoSuiteツールバーが表示されない不具合を修正。
  `_geo_toolbar()` に `ensure_visible` 引数を追加し、項目追加経路では
  ツールバーの可視状態を保証するようにした(ドライバ非稼働の個別利用では
  表示を強制する経路が無く、保存済みウィンドウ状態等でツールバーが
  非表示のままになり得た)。unload時のremoveAction経路は従来通り
  表示状態を変更しない

## 1.0.6

- bridge.py: URLからの関数取得(fetchFromUrl)・sources.json管理
  (listSources/addSource/removeSource)・ライブラリフォルダ表示
  (openLibraryDir)を追加し、管理ダイアログの全操作を
  bridge_callから可能にした

## 1.0.5

- i18n/ に ja.json しか無かった状態から de/es/fr/hi/it/pt/ru/zh
  の8言語JSONを新規作成し、ja の31キーすべてに訳文を追加
  (geo_userfunc コンテキスト=関数ライブラリ管理ダイアログのUI文言)

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
