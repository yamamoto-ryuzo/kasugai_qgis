# V4.4.5 全レイヤ/表示レイヤ検索が常に0件になる不具合を修正
- resultdialog.py: `set_features_by_layer` 内でモジュール先頭のimport済み
  `QCoreApplication` を関数内で再importしていたため、関数スコープの
  ローカル変数扱いとなり import 行前の使用箇所で UnboundLocalError が
  発生。例外が show_features の catch に吸収され `set_features([],[])`
  (空タブ)にフォールバックし、全レイヤ/表示レイヤ検索の結果が常に
  表示されなかった(選択もズームも不可)のを修正。
- bridge.py: `_zoom_to_results` がレイヤCRSのbboxをキャンバスCRSへ
  変換せず `zoomToFeatureExtent` へ渡していたため、CRS不一致
  (例: レイヤ=EPSG:4326 / キャンバス=EPSG:3857)時に誤った場所へ
  ズームしていたのを修正(地物ごとに変換してから結合)。

# V4.4.4 ドキュメントのSecret検出対応
- SEARCH.md/SEARCH_JP.md の接続設定例で Password 値が実値に
  見える文字列("Password"/"パスワード")だったため、シークレット
  スキャンで「Potential Secret Keyword」検出となったのを修正。
  同ファイル内の他例と同じ "..." プレースホルダに統一

# V4.4.3 try/except/pass の nosec 明示
- 584箇所に # nosec B110/B112 を付与(設計上の許容を明示)

# V4.4.2 Qt6互換性チェック対応
- 非スコープ列挙型をスコープ化(Qgis.*→Qgis.MessageLevel.*、
  qt_compat.py含む2箇所)

# V4.4.1 plugins.qgis.org セキュリティスキャン対応
- `get_codes` の PostgreSQL クエリでテーブル/カラム識別子を
  `"`→`""` エスケープする `quote_ident` を導入
  (識別子経由のSQLインジェクション対策)
- LOW指摘(try/except/pass|continue)はレビュー済みの常套パターン
  として同梱 `.bandit` 設定で抑制
- flake8指摘を整理: 関数内の冗長な再importを削除、bare `except:`
  を `except Exception:` に修正、未使用変数を整理。
  残る長行E501は同梱 `.flake8` 設定で明示抑制

# V4.4.0 ユーザーテーマ保存バグ修正 + 検索対象水平回転モード
- `theme.save_user_theme` が常に空の `entries` を出力するバグを修正
  (スナップショット名なしで `collect_visible_layer_snapshot` を呼び、
  存在しない `None` キーを読み戻していたため。内部キー
  `__user_theme_save__` で保存→読み戻すよう修正)。issue #20 の
  ユーザーテーマ保存/読込(`.usertheme.json`・設定ダイアログ・
  bridge `saveUserTheme`/`loadUserTheme`)が実際に機能するようになった。
- issue #10: 検索時に検索対象を水平に回転するモードを追加。
  タブ設定で `rotateMode: "horizontal"`(または `"feature"`/`"target"`、
  もしくは `rotateHorizontal: true`)を指定すると、検索対象地物の
  全頂点の主成分分析(主軸方位)から水平化に必要な角度を計算し、
  ナビゲーション後に `canvas.setRotation` で適用する。
  レイヤCRSとキャンバスCRSが異なる場合は変換してから評価。
  未指定時は従来の固定値 `angle` 動作。
- `SEARCH.md`/`SEARCH_JP.md` に `rotateMode` 設定キーを追記。

# V4.3.1 utils.py のQMessageBox翻訳化
- `utils.py` の JSON エントリ削除処理の警告/情報/書き込みエラー
  QMessageBox(英語直書き5箇所)を
  `QCoreApplication.translate("Dialog", ...)` 化し、
  `Dialog` context に8ソースを全9言語で登録。

# V4.3.0 翻訳方式を `i18n/<lang>.json` に移行
- `.ts`/`.qm` を廃止し、`{"context": {"英語ソース": "翻訳"}}` の
  JSONカタログを新設。`i18n_json.py`(全プラグイン共通ローダ)の
  `install_translator()` で起動時ロードに統一。
- `SearchWidget` context の未登録12メッセージ(角度/縮尺表示・
  検索方式ラベル等)を全9言語で補完。

# V4.2.0 国際化(i18n)対応
- UI文字列を英語ソースに統一(`dialog.ui`/`result.ui`・各ダイアログコード)。
  `self.tr()`/`QCoreApplication.translate` で抽出可能な翻訳呼出に置き換え。
- `i18n/ja.ts` を再生成し全131メッセージに日本語訳を設定、`ja.qm` を再コンパイル。
  他言語カタログは既存訳を継承し、未訳分は英語にフォールバック。
- 表示文字列「すべて」と内部フォーマット値を分離し、保存設定との互換性を維持。
- `README.md` は英語、`README_JP.md` は日本語の2言語ドキュメント構成を維持。
- 修正(翻訳導入で顕在化): `resultdialog.py` の `QCoreApplication` 未importによる
  `NameError`(プラグイン起動失敗)と、`_init_language` の `QTranslator` が
  ローカル変数でGCされて翻訳が無効化される問題を修正(`self.translator` に保持)。

# V4.1.0 AI/外部制御用ブリッジ(QGIS Live Harness)
- `bridge.py`(`GeoSearchBridge`)を追加し `plugin.bridge` に配線。`qgis_live_driver` の `bridge_call` コマンド(ファイルJSONL / REST / MCP)から全機能を呼び出せる。
- メソッド: `pluginInfo` / `status` / `listTabs` / `selectTab` / `search` / `results` / `zoom` / `openDialog` / `closeDialog` / `searchOptions`(pan_mode・fixed_scale・show_layer_name) / `tabOptions`(地番=完全一致|あいまい・字コード、所有者=対象フィールド・一致方式) / `suggest` / `listThemes`・`applyTheme`・`themeAdditive` / `saveUserTheme`・`loadUserTheme` / `getSettings`・`setSettings` / `tabSetting`・`addTabFromCurrentLayer`・`removeTab`・`reloadDialog`。`search` は `options` 引数で検索オプションを事前適用できる。
- `pluginInfo()` は標準自己記述スキーマ(id/name/summary/when_to_use/invoke/methods/state)を返し、ドライバの `describe_plugins` カタログでAIが用途・呼び方を発見できる。
- 残存していたQt5向けフォールバック・非スコープenum・`exec_()`を除去しQt6専用コードに統一

# V4.0.0 QGIS 4.0+ / Qt6 専用化
- QGIS 4.0以上に対応し、QGIS 3.xおよび不要となったQt5 (PyQt5 / PySide2) への互換コードを整理・削除しました。
- 互換レイヤー（`qt_compat.py`）を整理し、QDialogなどのダイアログ実行処理をQt6に合わせて `exec()` の呼び出しにシンプル化しました。
- 実行時に不要な開発・管理用ファイル（古いZIP、バッチファイル、PyQt5関連の不要な設定ファイル、Pipfile等）を削除しました。
- 各種ドキュメント（README_JP.md / README.md）を更新し、QGIS 4.0+ / Qt6 専用モデルとしての表記を最適化しました。

# V3.2.0 検索結果表示の機能強化
- 検索結果表示の操作性・可読性を改善（列幅自動調整・列最小幅・最終列ストレッチの強化）。
- フォーム表示を追加  

# V3.1.0 カテゴリ凡例のカテゴリマージ対応
- カテゴリレンダラーの凡例復元時、保存時と復元時でカテゴリ構成が異なる場合でも、値の分割・複数キー対応によりカテゴリマージ（部分一致）で可視化を再現する仕様に対応。
- THEMES.mdに仕様説明を追記。

# CHANGELOG

## V3.3.0 設定ソースの多様化（setting.json / project variable / geo_search_json）
- 設定ソースが3種類（プラグイン同梱の `setting.json`、プロジェクト変数 `GEO-search-plugin`、外部ファイル参照 `geo_search_json`）を統合して読み込む実装を完成しました。
- 各タブ設定へ読み込み元の情報（`_source`）と読み込み時のインデックス（`_source_index`）を注釈として付与し、設定編集・削除時の対象特定を容易にしました。
- 設定編集・削除フローを強化し、外部ファイル/プロジェクト変数の個別更新とバックアップ作成を行うようにしました。
- UI: タブのソース表示にインデックスを併記するように改善（例: `[setting.json #3]`）。
- いくつかの競合編集ケースでの堅牢性向上（Titleベースのフォールバック削除、ファイル書換時の原子操作）。


## Versioning: VA.B.C
- A: QGIS本体またはプラグインのバージョンアップに伴う本体の修正
- B: UIの変更（プラグインの追加等含む）、本体の簡易な機能追加
- C: プロファイル・プラグイン、本体の修正

---
V2.36.0 検索レイヤを表示にする機能追加。
V2.37.0 Qt6 対応と安定化
- Qt6 (QGIS 3.44+) 環境での互換性対応を追加（`supportsQt6 = True` を metadata に追加）
- `geo_search/qt_compat.py` に Qt5/6 差分の shim と小さな互換パッチを追加
- PyQt インポートを `qgis.PyQt` 経由に正規化
- 結果表示ダイアログの列幅とヘッダー処理を改善（ResizeToContents + 最低幅設定 + 最終列ストレッチ）
- create_zip.py を改善し、ZIP 作成・乾燥実行モードと除外パターンを追加
- 一部環境で再現する UI 描画の初期化タイミング問題に対する防御的処理を追加

V2.35.0 検索対象レイヤ名が複数同一名称である場合は、複数レイヤ検索に対応。  
V2.34.0 検索設定に「スケール」指定を導入。    
V2.33.0 検索設定に「角度」指定を導入。  
V2.32.0 UIのコンボボックスで選択可能な複数モード（ズームto選択、中心パン、固定スケール、アニメーションパン、選択のみ）を導入。  
V2.31.0 フィールド検索での数値フィールド対応を実装（数値入力時に数値型フィールドも検索対象に含める）。  
V2.30.0 ツールバーの起動ボタンの右側にテーマドロップダウンを追加。   
V2.29.0 プラグイン起動時に現在の表示状態を「検索前」というテーマ名で自動保存する機能を追加。  
V2.28.0 検索タブごとにQGISマップテーマ（selectTheme）を選択・適用できる機能を追加。タブ設定編集ダイアログでテーマ指定が可能に。  
V2.27.4 全角英数字の半角変換機能の再構築  
V2.27.0 一つの検索ボックスに対して、複数のフィールドを検索対象機能追加  
V2.26.0 プロジェクト変数の設定_検索対象選択機能追加  
V2.25.0 プロジェクト変数の設定_表示内容選択機能追加  
V2.24.0 プロジェクト変数の設定編集機能追加  
V2.23.0 現在のレイヤを検索対象検索追加  
V2.22.0 表示レイヤ・全レイヤ検索追加  
V2.21.0 カレントレイヤ検索追加  
V2.20.1  
- 多言語対応（英語、フランス語、ドイツ語、スペイン語、イタリア語、ポルトガル語、日本語、中国語、ロシア語、ヒンディー語）  
- QGISの言語設定に応じてUI自動切替  
- create_zip.pyによる最小限ZIP自動生成
- ZIP作成時にmetadata.txtのバージョン自動更新
- 旧バージョンZIP自動削除
V2.20.0  
- QGISプラグインの基本機能実装
- 地番検索・所有者検索・通常検索UI
- 設定ファイルによる検索項目管理

- 検索結果ダイアログ・サジェスト機能

