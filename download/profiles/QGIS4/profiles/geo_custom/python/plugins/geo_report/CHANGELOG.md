# Changelog - QGIS Layout Item Selector

バージョン表記: VA.B.C
- 例: V2.0.0（A=2, B=0, C=0）

## V2.9.5 bridge経由のAI操作を全機能へ拡張
- bridge.py: 標準レイアウト(listStandardLayouts/addStandardLayout)・
  再読込(refresh)・レイアウト情報(layoutInfo)・保存済みプロパティ一覧
  (listPropertyFiles)・レイアウト操作(removeLayout/renameLayout/
  duplicateLayout/createLayout)を追加

## バージョン番号の意味
- **A**: QGIS本体のバージョンアップに伴う本体の修正
- **B**: UIの変更（プラグインの追加等含む）、本体の機能追加
- **C**: プロファイル・プラグイン、本体の修正

---

## 変更履歴

### V2.9.4 翻訳カタログの欠落分を補完
- i18n/ 各言語JSON(de/es/fr/hi/it/pt/ru/zh)に ja のみに存在した
  55キーの訳文を追加し、全言語でカタログキー数を一致させた
  (geo_report コンテキスト=レイアウトアイテム管理ダイアログのUI文言)

### V2.9.3 try/except/pass の nosec 明示
- plugins.qgis.org スキャンで指摘された `try/except/pass|continue`
  43箇所に `# nosec B110/B112` を付与(GUIクラッシュ回避の
  設計上許容パターンを明示。`.bandit` はZIP非同梱のため
  インライン抑制で対応)

### V2.9.2 Qt6/Qt6互換性チェック対応
- plugins.qgis.org の Qt6 compatibility チェックで指摘された
  非スコープ列挙型35箇所を修正:
  `Qgis.Info`等→`Qgis.MessageLevel.*`、
  `QgsWkbTypes.PolygonGeometry`→`QgsWkbTypes.GeometryType.PolygonGeometry`、
  `QFormLayout.*Role`→`QFormLayout.ItemRole.*`、
  `QgsUnitTypes.LayoutMillimeters`→`QgsUnitTypes.LayoutUnit.LayoutMillimeters`

### V2.9.1 plugins.qgis.org セキュリティスキャン対応
- LOW指摘(try/except/pass|continue、subprocess import)は
  レビュー済みの常套パターンとして同梱 `.bandit` 設定で抑制
  (ZIP内検出により "Validated (configured)" ステータス想定)
- flake8指摘を整理: `PrintAreaMoveTool` 内の重複メソッド定義と
  `LayoutSelectorDialog` 内に残存していた別ツールのデッドコピーを
  削除(いずれも後勝ちの有効定義のみが動作していたデッドコード)、
  bare `except:` を `except Exception:` に修正、未使用変数を整理。
  plugin構造由来のE402・長行E501は同梱 `.flake8` 設定で明示抑制

### V2.9.0 角度0度リセットボタン追加(issue #4)
- 「角度:」ラベルの右に `0°` ボタンを追加。クリックで
  `angle_spin` を 0.0 にセット(印刷範囲表示中は
  `valueChanged`→`_refresh_print_area` 経由で即再描画)。
- ツールチップ `Reset angle to 0°` を新規翻訳キーとして
  全9言語のi18nカタログに登録。
- `ui/main_dialog.ui`(未使用のミラー)にも同じボタンを反映。

### V2.8.1 スケール/角度変更時の印刷範囲消滅を修正(issue #2続報)
- `scale_spin`/`angle_spin` の `valueChanged` がトグル型の
  `show_print_area_on_map` に直接接続されていたため、表示中に
  値を変えるたびに印刷範囲が消去(次の変更で再表示)を繰り返していた。
  新設の `_refresh_print_area` に切り替え、表示中は同じ中心で
  描き直し、非表示時は何もしない挙動に変更。
- 再描画はドラッグ移動済みの枠中心を維持し、描き直し時の
  キャンバス中心への再パンと「Print area removed.」メッセージを抑止。
- `QgsMapCanvas.rotationChanged` を `_refresh_print_area` に接続し、
  印刷範囲の表示中にキャンバスを回転しても枠が画面に沿った
  向き(見た目の回転=角度入力値)を維持するようにした。

### V2.8.0 レイアウトマネージャ起動ボタン + 一覧の自動再読込(issue #3)
- レイアウト一覧の下に「Open Layout Manager」ボタンを追加。
  `iface.actionLayoutManager()` でQGIS標準のレイアウトマネージャを開き、
  レイアウトの削除・複製・名前変更ができる(未対応環境では
  `QgsLayoutManagerDialog` を直接起動するフォールバック付き)。
- `QgsLayoutManager` の `layoutAdded`/`layoutRemoved`/`layoutRenamed`
  シグナルを `reload_layout_list()` に接続し、レイアウトマネージャや
  プロジェクト操作などパネル外での構成変更を一覧へ自動反映する。
- `reload_layout_list()` は選択中レイアウトを名前で復元する。
  選択中レイアウトが削除されていた場合は選択解除・ボタン無効化・
  印刷範囲ラバーバンドの消去を行う(削除済みC++オブジェクト参照対策)。
- bridgeに `manageLayouts` を追加(モーダルブロック回避のため
  `QTimer.singleShot` で非同期起動)。「Open Layout Manager」の訳は
  既存カタログ(MainDialog context)を全9言語で流用。
- キャンバス自体が回転している場合の印刷範囲表示を修正(issue #2続報):
  印刷枠(RubberBand)の回転角と `QgsLayoutItemMap.mapRotation` に
  `canvas.rotation()` を加算し、画面が回転していても印刷枠が
  見た目上回転していない(画面に沿った)矩形になるようにした。
  印刷結果も画面表示と同じ向きになる。
  あわせて QGIS4 で `QgsRubberBand.reset(True)` が TypeError になる
  呼び出しを `reset()` に修正(消去済み枠が残る問題の防止)。

### V2.7.1 標準レイアウトをA0〜A4縦横の10種に拡充(issue #1)
- 同梱 `composer/*.qpt` を A3/A4 の2種(横向き)から、
  A0〜A4(横・従来どおり無印が横向き) + A0縦〜A4縦(縦向き) の全10種に拡充。
- 各テンプレートは用紙いっぱいの地図アイテムを持つ。
  地図アイテムの保管extentのアスペクト比を用紙に合わせた
  (不一致だとloadFromTemplate時に地図が縮小されるため)。
- レイアウト0件時の自動インポート・「Add Standard Layout」ボタンの
  選択肢は全10種になる。

### V2.7.0 標準レイアウト追加ボタン + 回転時の印刷範囲・スケール計算の修正
- 「Add Standard Layout」ボタンをレイアウト一覧の下に追加。
  同梱 `composer/*.qpt`(A4/A3)を選択してプロジェクトへ追加できる。
  同名レイアウトは連番でユニーク化し、追加後は一覧を再読込して選択。
  レイアウト0件時の自動インポートは従来どおり。
  新規翻訳キー4件を全9言語に登録。
- 回転時の印刷範囲の不正を修正(issue #2):
  `PrintAreaMoveTool` で印刷範囲をドラッグ移動した際、
  回転済み矩形の外接矩形(AABB)を `QgsLayoutItemMap.setExtent` に
  渡していたため、印刷範囲が実表示より大きくなっていた。
  extent は回転前の表示領域(中心移動のみの矩形)を設定し、
  回転は `setMapRotation` に任せるよう修正。
- キャンバス回転時のスケール自動計算の不正を修正:
  `canvas.extent()` は回転時に回転領域の外接矩形を返すため、
  `mapUnitsPerPixel × キャンバスのピクセル数` で実際の表示幅・高さを
  求めるよう変更(回転0時と同じ縮尺が得られる)。

### V2.6.1 undoコマンド名の翻訳化
- レイアウトプロパティ一括適用の undo コマンド名
  `レイアウトプロパティ一括適用` を
  `QCoreApplication.translate('geo_report', "Apply layout properties")` 化し、
  全9言語で登録。

### V2.6.0 翻訳方式を `i18n/<lang>.json` に移行
- `.ts`/`.qm` を廃止し、`{"context": {"英語ソース": "翻訳"}}` の
  JSONカタログを新設。`i18n_json.py`(全プラグイン共通ローダ)の
  `install_translator()` で起動時ロードに統一
  (`__init__.py` と `plugin.py` の二重installを解消)。
- 言語セットを共通9言語(de/es/fr/hi/it/ja/pt/ru/zh)に統一し en を廃止。
- `geo_report` context の未登録4メッセージ(Size/Modified/bytes等)を
  全9言語で補完。

### V2.5.0 国際化(i18n)対応
- ハードコードされていた日本語UI文字列を英語ソースに変換し、
  `QCoreApplication.translate('geo_report', ...)` による翻訳呼出に統一。
- `i18n` カタログを再生成し日本語91メッセージ全訳、`geo_report_ja.qm` を再コンパイル。
- ログ出力も英語ソース化。

### V2.4.0 QGIS4以降への対応宣言

- `metadata.txt` の `qgisMinimumVersion` を 3.40 → 4.0 に更新
  (QGIS4以降専用。`qgisMaximumVersion=4.99`・`supportsQt6`は継続)
- 残存していたQt5向けフォールバック・非スコープenum・`exec_()`・`PyQt6`直接import分岐を除去しQt6専用コードに統一

### V2.3.0 QGIS Live Harness: AI/外部制御ブリッジ追加

- `bridge.py`(`GeoReportBridge`)を新設し `plugin.bridge` に配線。
  `qgis_live_driver` の `bridge_call`(ファイルJSONL / REST /api/cmd /
  MCP `qgis_bridge_call` / AIアシスタントパネル)と `describe_plugins`
  カタログから利用可能。メソッド(JSON文字列返却):
  `pluginInfo` / `status` / `openPanel` / `closePanel` / `listLayouts` /
  `selectLayout` / `printOptions`(scale・angle) / `showPrintArea` /
  `listItems` / `itemProperties` / `setItemProperties` /
  `saveLayoutProperties` / `loadLayoutProperties` / `openLayoutManager`
- `save/loadLayoutProperties` はファイルダイアログを通さずパス指定で
  直接JSON読み書きするため、modalで呼出をブロックしない
- 機能変更なし(UI操作は従来通り)


### V2.2.7（2026-10-18）
- QGIS Live Harness (`qgis-plugin/geo_report`) への組み込み
  - upstreamリポジトリ `C:\devin\geo_report\geo_report` はHarness側フォルダへのjunctionとして同期
- プラグイン内文書を整備（README.md / CHANGELOG.md / image.png を同梱）
- 機能変更なし

### V2.1.0（2025-07-24）
- 印刷範囲の回転角度をレイアウト本体（QgsLayoutItemMap等）に反映する機能を追加

### V2.0.0（2025-07-19）
- バージョン表記を2.0.0に更新
- 印刷範囲の回転・移動時の中心座標維持ロジックを改善
- コード整理・安定性向上

### V1.2.0
- UI改善：レイアウトリスト・レイアウト情報タブに印刷サイズ（縦横）を表示
- プロパティ編集機能の強化

### V1.1.0
- レイアウトアイテムのプロパティ保存・読込機能追加

### V1.0.0
- 初版リリース
