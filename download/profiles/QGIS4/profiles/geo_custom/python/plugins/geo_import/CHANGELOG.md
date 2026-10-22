2.10.6 PyQt import 修正・レガシー残骸削除
- vendored pyperclip の Qt クリップボードバックエンドを
  PyQt5/PyQt4 から qgis.PyQt へ変更(QGIS4/Qt6 では PyQt5 の
  直接 import がブロックされるため。qtpy 優先は維持)
- 不要ファイルを削除:
  - scripts/run-env-linux.sh(QGIS 2.0 時代の Linux 環境設定)
  - INSTALL_INSTRUCTIONS.md(QGIS 3.x・旧プラグイン名の陳腐化手順書)
  - future-plan.md(実装と無関係な構想メモ)
  - packages.json / groups.json(ローカルフォルダ索引のサンプル残骸。
    プラグイン dir 自身を走査した自動生成物でコードから未参照)
  - ckan_cache.db(誤コミットされた実行時キャッシュ)
  - icon64.png(未参照)
  - zip_ckan_browser_dialog.py(存在しないファイルをzip化する
    dead dev ツール)

2.10.5 vendored defusedxml へ切替
- サイトスキャンの ElementTree 指摘(B405)をコード側で解消。
  # nosec 抑制ではなく defusedxml 0.7.1 を vendored 同梱し
  (pyperclip と同じくプラグイン配下に配置)実体宣言・外部参照を
  パーサ層で拒否する方式へ変更。
  - defusedxml/ には ElementTree facade のみ同梱
    (__init__.py/common.py/ElementTree.py/LICENSE)。
    defuse_stdlib() と他 facade は QGIS との相性問題
    (stdlib XML monkey-patch が qgis.PyQt.uic.loadUiType を
    壊す。qgis2web upstream で実害あり)とスキャン指摘回避の
    ため意図的に除外
  - 既存の _reject_unsafe_xml 事前ガードも維持(defense in depth。
    エラー型も従来どおり ParseError で揃える)
  - xml_attribute_loader._parse_xml_with_encoding は
    (tree, root) から root 単独返しに変更
    (defusedxml.ElementTree は ElementTree クラスを
    再エクスポートしないため。呼出し側は None 判定のみで
    tree を未使用だった)
- .bandit に exclude = defusedxml を追加(vendored コードを
  スキャン対象外に。defusedxml 内部が stdlib xml.* を
  import するのは facade の性質上当然のため)
- .flake8 の per-file-ignores に defusedxml/*.py を追加

2.10.4 サイトスキャン指摘対応
- ElementTree import 3箇所に # nosec B314 を付与
  (全て _reject_unsafe_xml で DOCTYPE/ENTITY を拒否済み。
  QGIS環境に defusedxml が無いため stdlib ET + ガードで対応)
- assert を実修正: httpcall.py の型チェック2箇所を
  TypeError raise に変換(-Oでも有効)。pyperclip の2箇所は
  等価のifチェックに置き換え(空なら''を返す)
- subprocess/Popen/startfile 18箇所に # nosec B603/B606/B607
  を付与(pyperclipのOS別クリップボードバックエンドと
  junction作成/ファイル・フォルダを開く意図的なOS操作)

2.10.3 try/except/pass の nosec 明示
- try/except/pass|continue 40箇所に # nosec B110/B112 を付与
  (設計上の許容を明示。サイトスキャンの指摘対応)

2.10.2 Qt6互換性チェック対応
- 非スコープ列挙型59箇所をスコープ化:
  Qgis.*→Qgis.MessageLevel.*(geo_import_dialog/geo_import_main/
  settings/util/xml_attribute_loader)

2.10.1 plugins.qgis.org セキュリティスキャン対応
- junction作成の `mklink` 呼出しから `shell=True` を除去
  (リスト形式で cmd /c を直接起動するためshell解釈を経由しない)
- XMLパース4箇所(WMS GetCapabilities / 属性XMLローダ /
  XML診断ツール×2)に DOCTYPE/ENTITY 宣言の拒否ガードを追加
  (XXE・entity展開攻撃対策)
- キャッシュキー/ファイル名短縮用の md5/sha1 計8箇所に
  `usedforsecurity=False` を付与(非セキュリティ用途の明示)
- LOW指摘(try/except/pass、subprocess系監査ヒント、
  vendored pyperclip 等)はレビュー済みとして同梱 `.bandit` 設定で抑制
- flake8指摘を整理: `CkanConnector.__check_connection` の重複
  デッド定義を削除(後勝ちの有効版を温存)、
  `httpcall` の `QNR_TIMEOUT_ERROR` 未修飾参照を `self.` 付きに修正、
  `.format` 引数が出力に反映されないログ4箇所を修正、
  bare `except:` を `except Exception:` に修正。
  vendored pyperclip の指摘は同梱 `.flake8` 設定で明示抑制

2.10.0 死んでいるCKANサーバーの明示表示 + GSJ Linked Data/TileJSON対応強化
- GSJ Linked Data マップ情報(JSON)対応強化:
  地質調査総合センターデータカタログの「マップ情報（JSON）」リソース
  (産総研GSJ Linked Data, data_type=GSJMAP / @type=Gsjmap)を
  実地図レイヤとして取り込めるようにした。
  - `page[].tile_xyz_template` で地図本体をXYZタイルレイヤとして追加
    (無い場合は `wms_name`+`wms_capabilities` のWMSにフォールバック)。
    レイヤ名は `title_j`/`title_e` 優先、複数page・副題時はサフィックス付与。
  - `page[].section[].geojson`(JSON文字列で格納)を正しくデコードして
    .geojson化しベクタレイヤ追加(旧実装は文字列をそのまま
    json.dumpし無効なファイルになっていた)。
  - `downloadData` のURLキーを `@id` からも取得(旧実装の
    url/downloadUrl探索では実JSONで0件)。自動ダウンロードはせず
    `download_links.html`(リンク付き一覧表)に一覧化(同一ファイルは
    カタログ側に個別リソースとして存在するため)。
  - `page[0].bbox` へキャンバスをズーム。
- TileJSONリソース(`tiles[]`を持つJSON)に対応: `tiles[0]`をXYZレイヤ化
  (webpのみの場合は `properties.alternate_tile_templates` の
  png/xyzを優先)。`minzoom`/`maxzoom`をzmin/zmaxに反映、`bounds`へズーム。
- データセット詳細ペインをHTML化: タイトル見出し+項目テーブル化し、
  notes内のURL・author/maintainerのメールをリンク化
  (setOpenExternalLinksで外部ブラウザ/メーラ起動)。
  新規翻訳キー `Organization`/`Author`/`Maintainer`/`License` を
  全9言語に登録。
- Qt6クラッシュ修正: `load_resource_clicked` 内の
  `QtWidgets.qApp.processEvents()`(Qt5名残・Qt6に存在しない)を
  `QApplication.processEvents()` に置換(ダウンロード開始時に
  AttributeErrorで中断していた)。
- 接続失敗したサーバーを `Settings.server_errors` として
  `ckan_servers.json` に `{url: {error, time}}` で永続記録し、
  セッションをまたいで「死んでいる」状態を明示する。
- メインダイアログ: サーバーラベル(IDC_lblApiUrl)で失敗サーバーを
  赤・取り消し線+「(Unreachable)」表示(ツールチップにエラー内容)、
  結果ラベルにも「/ Unreachable: <server>」を付記。
  検索成功時は記録を自動消去(復活検知)。
- データプロバイダ選択ダイアログ: 前回接続失敗の記録がある
  サーバー行を赤背景+ツールチップ「Last connection failed: ...」で表示。
- bridge `status` の `settings` に `server_errors` を追加。
- 新規翻訳キー `Unreachable` / `Last connection failed: {0}` を
  全9言語に登録。

2.9.0 複数CKANサーバー横断検索 + 免責ダイアログ本文の消失を修正
- 複数CKANサーバー横断検索: データプロバイダ選択ダイアログで複数サーバーの
  同時選択を許可し、検索を `Settings.selected_ckan_urls`/
  `active_server_urls()` の全サーバーへ扇出する。
  `CkanConnector.get_groups`/`package_search` が `api_url` 引数を受け
  従来の単一 `ckan_url` と後方互換。カテゴリ(group)チェック時は
  サーバーごとの保有グループでfqを絞り込み、対象グループを1つも
  持たないサーバーは0件スキップ(緩い和集合ではなく厳密な横断)。
  `group_list` が文字列名リストを返すサーバーにも対応。
  bridge `settings` に `ckan_urls`(アクティブURL一覧)を追加
- 免責ダイアログ本文の消失を修正: `geo_import_dialog_disclaimer.py` の
  `IDC_brInfo` は `py_disc_info_html` キーで `setHtml` するが、
  ja/de/es/hi/it/pt/ru/zh は見出し語のみ・fr のみ全文HTML
  (upstream由来の独語本文)という不整合だった。
  ソース文字列をプレースホルダキーから実際の英語HTMLに改め、
  全9言語に全文翻訳を登録。英語フォールバックでも本文が表示される
  (従来は英語ではキー名 `py_disc_info_html` がそのまま表示された)

2.8.2 カタログ内の未翻訳プレースホルダ値を補完
- キーがそのまま値に残っていたカタログ項目(画面上にキー名が表示される
  状態)を全9言語で翻訳: `dlg_base_btn_select_dataprovider`/
  `dlg_base_current_server`/`dlg_base_lbl_cache_dir`/
  `dlg_base_lbl_plugin_version`/`dlg_dataproviders_btn_browse_local` 他、
  DataProviders/Disclaimer/Settings ダイアログの `dlg_*` キー群と
  `py_dlg_data_providers_*`/`py_dlg_set_info_*` 系メッセージ。
- de/es で未翻訳だった `dlg_base_*` キー群と、ja/fr で英語のままだった
  `All`/`Select All`/`Clear Selection`/`Data Format`/`Refresh SQLite` 等も補完。

2.8.1 カタログ未登録の翻訳キー21件を補完 + Deleteアクション翻訳化
- `GeoImport` context で translate されていたが全カタログ未登録だった
  キー形式ソース(cc_api_not_accessible/cc_connection_timeout/
  cc_download_error/cc_invalid_json/cc_server_fault/cc_url_error/
  cc_wrong_api/geo_import/&geo_import/geo_import_settings/
  py_dlg_base_*/py_dlg_set_* 計21件)に全9言語の翻訳を追加。
- データプロバイダ一覧の `Delete` コンテキストアクションを
  `QCoreApplication.translate('GeoImport', 'Delete')` 化し登録。

2.8.0 翻訳方式を `i18n/<lang>.json` に移行 + レイヤ整理連携
- `.ts`/`.qm`・`.pro`・`generate_qm.py`・`update_translations.py`・
  `TRANSLATION.md`・`scripts/*-strings.sh`・i18n補助スクリプト群を廃止。
  `{"context": {"英語ソース": "翻訳"}}` のJSONカタログを新設し、
  `i18n_json.py`(全プラグイン共通ローダ)の `install_translator()` で
  起動時ロードに集約(CKANBrowser_*.qmレガシー探索とenフォールバックの
  二重installを廃止)。言語セットを共通9言語(de/es/fr/hi/it/ja/pt/ru/zh)に
  統一し en/fi カタログを廃止。
- `GeoImport` contextの未登録5メッセージ(SQLiteキャッシュ等)を全9言語で補完。
- レイヤ整理連携: `load_resource_clicked` で追加したレイヤを
  `layersAdded` で収集し、`qgis_live_driver` の `layer_org` サービス
  (プロファイルのルールでグループ配置・リネーム・スタイル適用)へ渡す。
  ドライバ未ロード・プロファイル無効時は従来どおりプロジェクト直下に
  flat追加。bridge `loadSelected` の応答に `organized` レポートを同梱。

2.7.0 カタログ取得のデフォルトをネットワーク直接参照に変更
- これまで検索・一覧はローカルSQLiteキャッシュ(Refresh SQLiteでの一括ダウンロード)
  を前提としていたが、デフォルトをCKAN APIへの直接問い合わせ(ネットワークモード)
  に変更。サイト切替時・検索時に一括ダウンロードを行わない。
- ローカルダウンロード(SQLiteキャッシュ)はオプション化:
  - メイン画面の「Use local download for this site」チェックでサイト単位に選択可
    (`ckan_servers.json` の `local_cache_sites` にURL単位で保持)。
    ON時は既存キャッシュがあればそれを利用し、無ければ一括ダウンロードを実行。
    「Refresh SQLite」ボタン押下でもそのサイトのローカル利用が自動ONになる。
  - 設定ダイアログの「Use local download for all sites」で全サイト一括指定可
    (サイト個別設定より優先。QSettings `geo_import/use_local_cache_all`)。
- ネットワークモードではカテゴリ一覧を `group_list` APIから取得し、
  `package_search` の `fq=groups:` フィルタを実装してカテゴリ絞り込みに対応。
- データプロバイダ画面のサーバー一覧でローカル利用サイトに `[local]` マーカー表示。
- bridge `status()` に `use_local_cache_all` / `local_cache_sites` /
  `current_site_local_cache` を追加。
- ローカルフォルダ型サーバー(LOCAL type/local://file://)は従来通り常にローカル扱い。

2.6.0 国際化(i18n)対応
- UI・ログ文字列を英語ソースに統一し、翻訳コンテキストを `GeoImport` に正規化
  (`Util`/`self.util` 等の不一致コンテキストを解消しカタログが実行時に適用されるようにした)。
- 表示用文字列「すべて」(formatフィルタ)を `translate('GeoImport', 'All')` に統一し、
  比較ロジックと表示を一致させた。
- `i18n` カタログを再生成し日本語113メッセージ全訳、`geo_import_ja.qm` を再コンパイル。
  他言語(de/en/es/fi/fr/hi/it/pt/ru/zh)は既存訳を継承・英語フォールバック。
- XML属性テーブルローダ・CSV診断等のユーザー向けメッセージを翻訳対象化。

2.5.0 QGIS4以降への対応宣言
- `metadata.txt` の `qgisMinimumVersion` を 3.40 → 4.0 に更新
  (QGIS4以降専用。`qgisMaximumVersion=4.99`・`supportsQt6`は継続)
- バージョン表記をV接頭辞なしに統一(V2.5.0 → 2.5.0。CHANGELOG旧エントリ・metadata内changelogのV接頭辞も全除去)
- 残存していたQt5向けフォールバック・非スコープenumを除去しQt6専用コードに統一
  (`update_translations.py` は pylupdate6 専用に更新)

2.4.0 QGIS Live Harness: AI/外部制御ブリッジ追加
- `bridge.py`(`GeoImportBridge`)を新設し `plugin.bridge` に配線。
  `qgis_live_driver` の `bridge_call`(ファイルJSONL / REST /api/cmd /
  MCP `qgis_bridge_call` / AIアシスタントパネル)と `describe_plugins`
  カタログから利用可能。メソッド(JSON文字列返却):
  `pluginInfo` / `status` / `openDialog` / `closeDialog` / `openSettings` /
  `search` / `results` / `selectResult` / `resources` / `checkResources` /
  `loadSelected`
- `openDialog` は plugin.run() の `dlg.exec()` とは別に非modalの
  `show()` で開く(呼出が即応答するため)。`search` のデータセット取得は
  内部QThreadで非同期のため `results()` で結果を取得する。
  `loadSelected` 中の警告系modal QMessageBoxは自動Ok応答に差し替え、
  メッセージを収集して返す
- 機能変更なし(UI操作は従来通り)

2.3.46 QGIS Live Harness への組み込み
- `qgis-plugin/geo_import` として管理し、upstreamリポジトリ `C:\devin\geo_import\geo_import` はHarness側フォルダへのjunctionとして同期
- プラグイン内文書を整備（README.md / CHANGELOG.md / INSTALL_INSTRUCTIONS.md / TRANSLATION.md / future-plan.md を同梱）
- 機能変更なし

2.3.0 ローカルフォルダのJSONキャッシュ処理を改善
- ローカルフォルダ利用時、packages.json/groups.jsonの生成・読み込みをキャッシュディレクトリで一元管理
- フォルダ内にJSONを残さず、SQLiteキャッシュと同じ場所に保存・参照する方式に変更
- 既存のローカルJSONも初回のみキャッシュにコピーし、以降はキャッシュ優先で動作

2.2.0 XMLファイル属性テーブル読み込み機能を追加  
- XMLファイルを属性テーブル（ジオメトリなし）として読み込み可能
- 複数XMLファイルのタイプ別自動マージ機能
- 国土交通省XML形式の自動検出と最適化処理
- DTD、名前空間、ルート要素による高精度なXMLタイプ識別
- エンコーディング問題の自動解決（Shift_JIS、UTF-8等に対応）
- CSV等と同様の統合データロード機能

2.1.0 ローカルフォルダスキャン機能を拡張  
- 拡張子制限を撤廃し、除外対象以外のすべてのファイルをデータベース化  
- システムファイル・一時ファイル・実行ファイルのみを除外する包括的アプローチに変更  
- 将来の新しいファイル形式に自動対応

2.0.0 ロカールフォルダに対応  
1.4.8 ダウンロード先のフォルダ名を人間でも分かりやすく修正  
1.4.0 CKAN以外のサーバー対応へ移行準備（サーバー一覧へサーバー種類を追加）   
1.3.0 全選択対応  
1.2.0 WMS対応  
1.1.0 XYZ対応  
1.0.0 QGIS用データカタログ統合プラグイン yamamoto版 初版公開  
- ローカルSQLiteキャッシュ検索時もカテゴリ（グループ）フィルタが有効
- CSVファイルの区切り文字自動判定（カンマ・セミコロン・タブ・コロン・スペース対応）
- CSVファイルの文字コード自動判定（UTF-8/CP932）とQGISレイヤ追加時のencoding自動指定
- CSVに緯度経度カラムがあれば自動でポイントジオメトリ化
- UIの一部改善

