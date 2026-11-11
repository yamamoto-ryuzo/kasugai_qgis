# geo_excel

[QGIS-exportExcel](https://github.com/yamamoto-ryuzo/QGIS-exportExcel) の
レイヤアクション用スクリプト群を、**QGISプラグインとしてメニューから実行できる**
ようにした簡易ラッパープラグイン(QGIS Live Harness 組み込み用)。

## 使い方(プラグインとして)

1. 対象のベクターレイヤをアクティブにする(単票出力は地物も選択)
2. メニュー `プラグイン → geo_excel` から実行:
   - **一覧帳票を出力 (アクティブレイヤ)** — `exportList.py` 相当
   - **単票を出力 (選択地物)** — `exportSingle.py` 相当(選択地物ごとに実行)
   - **単票を一括出力 (選択地物または全地物)** — `exportSingleBulk.py` 相当
   - **Settings...** — 設定ダイアログ(後述)
3. レイヤ変数(`xlsout_*`)の設定方法は下記の upstream 説明と同じ。
   未設定でも実行時に既定値が自動適用される(次節)

実行時に `[% @layer_id %]`(アクティブレイヤ)/`[% $id %]`(選択地物)を自動置換する。
スクリプト本体は upstream 無改変で同梱し、exec直前に `PyQt5`→`qgis.PyQt`、
`Qt.WaitCursor`→`Qt.CursorShape.WaitCursor` の Qt6 向け書き換えのみ行う。

**前提**: `win32com`(pywin32)と Excel がインストール済みであること。

## 既定値と設定ダイアログ(すぐに動くための設定)

レイヤ変数 `xlsout_*` が未設定のレイヤでも、実行時に既定値を自動適用する
(`settings.py`。無効化は設定ダイアログまたは QSettings
`geo_excel/auto_apply`)。既定値:

- `xlsout_*_output_path_fixed` → **`<ドキュメント>/geo_excel`**
  (`QStandardPaths.DocumentsLocation` で取得。環境依存パスを持たない汎用既定)
- `xlsout_output_path_variable` → `concat('<レイヤ名>_', $id, '.xlsx')`
  (一覧は `<レイヤ名>_list.xlsx`)
- `xlsout_*_template_path` → 未指定なら `<出力先>/templates/
  <レイヤ名>_<種別>_template.xlsx` に、レイヤのフィールド名を埋め込んだ
  最小構成のxlsx雛形(`##Attach::`/`##ListInsert::`)を自動生成
- `dpi` → 未指定時はスクリプト側既定(200)

メニュー `Settings...` で開く設定ダイアログ(`settings_dialog.py`)は
以下を1画面に集約する:

- **環境チェック**: pywin32(win32com) import可否 / Excel COM登録
  (レジストリ確認+「起動テスト」で実起動検証) / ドキュメント・
  出力先フォルダパス
- **既定値の編集**: 出力先フォルダ・DPI・一覧/単票テンプレート指定・
  自動適用の有無(QSettings `geo_excel/*` に保存)
- **アクティブレイヤの変数**: `xlsout_*`/`dpi` の現在値を表で編集し
  「保存」でレイヤへ書き込み。「不足変数へ既定値を適用」
  「自動テンプレートを再生成」ボタンあり
- **必要なもの**: 実行要件(Excel・pywin32・テンプレートの
  プレースホルダ記法・`##AttachFitImage::` にはマップテーマ必要等)を列挙

## AI/外部制御 API(bridge)

`plugins['geo_excel'].bridge`(`GeoExcelBridge`)経由で、QGIS Live Driver の
`bridge_call` / `describe_plugins`(MCP `qgis_bridge_call`・REST・
AIアシスタントパネル)から操作できる。メソッドはJSON文字列を返す:

- `pluginInfo()` / `status()` — 自己記述・実行時状態(アクティブレイヤ/選択数/win32com有無/変数設定状況)
- `listScripts()` — 帳票スクリプト一覧(id/ファイル/要選択/必要レイヤ変数)
- `layerVariables(layer_id)` / `setLayerVariables(vars, layer_id)` — `xlsout_*`/`dpi` レイヤ変数の取得/設定
- `settings()` — 既定設定(QSettings)・環境チェック・必要物の列挙を返す
- `applyDefaults(layer_id=None, script=None)` — 不足レイヤ変数へ既定値を適用
  (出力先フォルダ作成・テンプレート自動生成含む)
- `checkExcel()` — Excelを実際にCOM起動して検証(既存ExcelはQuitしない)
- `openSettings()` — 設定ダイアログを開く
- `run(script, feature_id=None, confirm=False)` — 帳票実行。
  `script` は `list`/`single`/`bulk`/ファイル名/index。`single` は選択地物
  または `feature_id` 指定。スクリプト内の modal QMessageBox は実行中だけ
  自動応答に差し替わり、`confirm=True` で上書き/続行にOk応答
  (既定False=中断)。実行結果(`excel_result`/`output_path`)と収集した
  メッセージを返す。Excel生成中はGUIスレッドをブロックする

例: `qgis_bridge_call pluginId="geo_excel" method="run" args=["list", null, true]`

---

以下は upstream (QGIS-exportExcel) のREADMEです。

# QGIS-exportExcel

このリポジトリは、QGIS からベクターレイヤの属性情報を Excel 帳票として出力するための Python スクリプト群を提供します。

# 各スクリプトの概要

## exportList.py
- ベクターレイヤの「レイヤスコープ」アクションとして利用する一覧帳票出力用スクリプトです。
- レイヤ変数でテンプレートパスや出力先ディレクトリを指定し、全地物の情報を Excel テンプレートに出力します。
- テンプレート内の `##ListInsert::フィールド名` で繰り返し出力が可能です。

### 使用方法
1. QGISの対象レイヤのレイヤ変数に以下を設定します。
   - `xlsout_list_template_path` : Excelテンプレートファイルのパス
   - `xlsout_list_output_path_fixed` : 出力先ディレクトリパス
   - `xlsout_list_output_path_variable` : 出力ファイル名やサブディレクトリ名（式やフィールド参照も可）
2. テンプレートExcelに `##ListInsert::フィールド名` を記述します。
3. レイヤアクションに `exportList.py` を登録し、アクションフィールドとして `[% @layer_id %]` を渡します。
4. アクション実行で帳票が出力されます。

---

## exportSingle.py
- ベクターレイヤの「地物スコープ」アクションとして利用する単票（単体）帳票出力用スクリプトです。
- 選択した1つの地物の属性値を Excel テンプレートに出力します。
- テンプレート内の `##Attach::フィールド名` で属性値を差し込みます。

### 使用方法
1. QGISの対象レイヤのレイヤ変数に以下を設定します。
   - `xlsout_template_path` : Excelテンプレートファイルのパス
   - `xlsout_output_path_fixed` : 出力先ディレクトリパス
   - `xlsout_output_path_variable` : 出力ファイル名（式やフィールド参照も可）
2. テンプレートExcelに `##Attach::フィールド名` を記述します。
3. レイヤアクションに `exportSingle.py` を登録し、アクションフィールドとして `[% @layer_id %]` `[% $id %]` を渡します。
4. アクション実行で帳票が出力されます。

---

## exportSingleBulk.py
- ベクターレイヤの「地物スコープ」アクションとして利用する単票一括出力用スクリプトです。
- 選択地物または全地物について、個別の Excel ファイルを一括出力します。
- 画像貼付やテーマ切替、縮尺指定などにも対応しています。

### 使用方法
1. QGISの対象レイヤのレイヤ変数に以下を設定します。
   - `xlsout_template_path` : Excelテンプレートファイルのパス
   - `xlsout_output_path_fixed` : 出力先ディレクトリパス
   - `xlsout_output_path_variable` : 出力ファイル名（式やフィールド参照も可）
2. テンプレートExcelに `##Attach::フィールド名` や `##AttachFitImage::テーマ名::縮尺` を記述します。
3. レイヤアクションに `exportSingleBulk.py` を登録し、アクションフィールドとして `[% @layer_id %]` `[% $id %]` を渡します。
4. アクション実行で選択地物または全地物分の帳票が一括出力されます。

---

# 共通の使い方

1. QGIS プロジェクトで対象レイヤに必要なレイヤ変数を設定します。
2. Excel テンプレートファイルを用意し、差し込みたい箇所に `##Attach::フィールド名` や `##ListInsert::フィールド名` を記述します。
3. レイヤのアクションにスクリプトを登録し、必要なフィールド（例: `[% @layer_id %]`, `[% $id %]`）を渡すようにします。
4. アクションを実行すると、指定の出力先に Excel 帳票が作成されます。

# 注意事項

- Excel の自動操作には Windows 環境と `win32com.client` が必要です。
- 出力先ディレクトリは事前に作成しておく必要があります（一部スクリプトでは自動作成）。
- テンプレートや出力先パスは絶対パス・相対パスどちらも利用可能ですが、パス区切り文字に注意してください（`\\` 推奨）。
- 画像貼付や地図テーマ切替には QGIS のマップテーマ機能を利用します。

# 参考

- 各スクリプトの先頭コメントや関数コメントも参照してください。
- QGIS のバージョンや Python 環境によっては動作しない場合があります。

初期バージョンの開発業者：オービタルネット　https://www.orbitalnet.jp/  
2023/02/01 QDATE,QDATETIMEへの対応しました。

# 免責事項

本システムは個人のPCで作成・テストされたものです。  
ご利用によるいかなる損害も責任を負いません。

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>
