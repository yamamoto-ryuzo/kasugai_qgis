# QGIS Data Catalog Integration（Catalog Integration）

本プラグイン「QGIS Data Catalog Integration（Catalog Integration）」は、オリジナルの「データカタログ統合」プラグインをベースに、機能拡張・改良を加えたものです。データカタログ統合 の思想と実装を継承しつつ、より多様なデータカタログやQGISとの統合を目指しています。

This plugin, "QGIS Data Catalog Integration (Catalog Integration)", is based on the original "データカタログ統合" plugin, with enhanced and extended features. It inherits the philosophy and implementation of データカタログ統合, aiming for broader data catalog integration and deeper QGIS integration.
# QGIS Data Catalog Integration (Catalog Integration)


# 開発方針 / Development Policy
東京オープンデータハッカソンへの参加をきっかけに、東京オープンデータをQGISで検索・変換・取り込み・装飾まで簡単にできるよう機能強化を行います。
https://odhackathon.metro.tokyo.lg.jp/

Inspired by participation in the Tokyo Open Data Hackathon (Visualization Division), this version aims to make it easier to search, convert, import, and style Tokyo open data in QGIS through enhanced features.
https://odhackathon.metro.tokyo.lg.jp/

　【参考：CKAN】  
・DATA GO.JP:https://www.data.go.jp/data/api/3  
・G空間情報センター: https://www.geospatial.jp/ckan/api/3  
・東京都オープンデータカタログサイト：https://catalog.data.metro.tokyo.lg.jp/api/3  
・地質調査総合センターデータカタログ：https://data.gsj.jp/gkan/api/3  
・姫路市・播磨圏域連携中枢都市圏オープンデータカタログサイト：https://city.himeji.gkan.jp/gkan/api/3  
・ビッグデータ&オープンデータ・イニシアティブ九州：https://data.bodik.jp/  

## 概要 / Overview

QGIS用データカタログ統合プラグイン（QGIS Data Catalog Integration / Catalog Integration）の拡張・修正版です。
CKAN等のオープンデータポータルからデータセットを検索・取得し、QGIS上で活用できます。

This is an enhanced and modified version of the QGIS Data Catalog Integration (Catalog Integration) plugin for QGIS.
You can search and download datasets from CKAN and other open data portals and use them in QGIS.


## 主な追加・修正機能 / Main Added & Improved Features
- ローカルSQLiteキャッシュ検索時もカテゴリ（グループ）フィルタが有効
    - Category (group) filter is available even when searching local SQLite cache
- CSVファイルの区切り文字自動判定（カンマ・セミコロン・タブ・コロン・スペース対応）
    - Automatic delimiter detection for CSV files (comma, semicolon, tab, colon, space)
- CSVファイルの文字コード自動判定（UTF-8/CP932）とQGISレイヤ追加時のencoding自動指定
    - Automatic encoding detection for CSV files (UTF-8/CP932) and auto-setting when adding as QGIS layer
- CSVに緯度経度カラムがあれば自動でポイントジオメトリ化
    - Automatic point geometry creation if latitude/longitude columns exist in CSV
- UIの一部改善
    - Some UI improvements
- GSJ(産総研地質調査総合センター)Linked Dataの「マップ情報（JSON）」・TileJSONリソースをXYZ地図タイルレイヤとして直接追加(埋め込み断面図GeoJSONも展開)
    - GSJ Linked Data "map info (JSON)" and TileJSON resources are added directly as XYZ tile layers (embedded section GeoJSON is also extracted)
- バージョン・更新履歴は `metadata_yamamoto.txt`, `Changlog_yamamoto.txt` で管理
    - Version and changelog are managed in `metadata_yamamoto.txt` and `Changlog_yamamoto.txt`

## V2.3.0 ローカルフォルダのJSONキャッシュ処理を改善
- ローカルフォルダ利用時、packages.json/groups.jsonの生成・読み込みをキャッシュディレクトリで一元管理
- フォルダ内にJSONを残さず、SQLiteキャッシュと同じ場所に保存・参照する方式に変更
- 既存のローカルJSONも初回のみキャッシュにコピーし、以降はキャッシュ優先で動作

## 使い方 / How to Use
1. QGISで本プラグインを有効化
    - Enable this plugin in QGIS
2. CKANサーバを選択し、検索・カテゴリ・データ形式で絞り込み
    - Select a CKAN server, filter by search, category, and data format
3. データセットを選択し、リソースをダウンロード・地図に追加
    - Select a dataset, download resources, and add them to the map
4. CSVの場合は自動で区切り文字・文字コード・ジオメトリ判定
    - For CSV, delimiter, encoding, and geometry are detected automatically


## ローカル (LOCAL) フォルダの仕様 / LOCAL folder support

このプラグインはローカルフォルダ内の CKAN 互換 JSON を CKAN と同様に扱えます。ローカルフォルダを手元のデータセットとして登録すると、SQLite キャッシュを生成して通常の検索・ダウンロード・取り込みフローで利用できます。

- 登録方法:
    - 「データプロバイダ」ダイアログの手動 URL 欄にローカルパスを入力して接続を追加します。UI 上には手入力のほか、QLineEdit 内の「Browse folder...」アクションと、入力欄横の「ローカルフォルダ選択」ボタンのいずれでもフォルダ選択できます。
    - 入力例:
        - Windows: `C:\data\local_ckan`、`file:///C:/data/local_ckan`、`local://C:/data/local_ckan`
        - POSIX: `/home/user/local_ckan`、`file:///home/user/local_ckan`、`local:///home/user/local_ckan`
    - 名前をつけて保存すると `custom_servers` に `{"url": "<path>", "type": "LOCAL"}` として保存されます。

- サポートされるローカル指定:
    - 直接のディレクトリパス
    - `file://` スキーム
    - `local://` スキーム

- 期待するフォルダ構成（いずれか）:
    1. 単一ファイル方式
         - `<local_folder>/packages.json` — CKAN の package 配列（複数パッケージの配列）
         - `<local_folder>/groups.json` — （任意）グループ（カテゴリ）配列
    2. ファイル分割方式
         - `<local_folder>/packages/` ディレクトリ配下に各パッケージを表す個別の `.json` ファイル
         - `<local_folder>/groups.json` — （任意）グループ（カテゴリ）配列

- JSON の想定スキーマ:
    - `package` オブジェクトは CKAN の package と互換であること（少なくとも `id`, `title`/`name`, `resources` 配列を含むことが望ましい）。
    - `resources` 配列の各要素は `id`, `name`/`title`, `format`, `url` 等のフィールドを持つことが望ましい。

- 自動生成・空フォルダ時の挙動:
    - `packages.json` が存在しない場合、プラグインは `packages/` 以下やルートのデータファイルから自動で `packages.json`（と `groups.json`）を生成し、生成したファイルはフォルダ内に保存されます（再取得時に上書きされることがあります）。
    - 自動生成でもデータが見つからない（完全に空のフォルダ）の場合は、最小の空配列を入れた `packages.json` を作成し、空の SQLite キャッシュ DB を作成します。このときユーザには情報ダイアログが表示されます（例: 「フォルダは空でした。空の索引を作成しました: <folder>」）。
    - テスト接続では、ローカルフォルダは存在するかどうかのみで成功とみなします（JSON の有無は不要です）。

- 運用上の注意（必ずお読みください）:
    - **変更の反映:** ローカルの `packages.json` やリソースファイルを手動で編集した場合、プラグインはキャッシュディレクトリに保存されたキャッシュファイル（`ckan_cache_<hash>_packages.json` や `.db`）を優先して使用します。編集内容を反映させるには、プラグインの `Refresh`（再取得）操作を実行してください。自動で即時反映されるわけではありません。
    - **Box/OneDrive 等クラウドドライブ:** Box Drive、OneDrive、Google Drive 等のクラウド同期フォルダはファイルロックや遅延同期が起きる場合があります。これらのフォルダをソースとして使用する際は、ファイルがローカルに確実に同期されていることを確認してください。読み込みエラーやタイムアウトが発生した場合、プラグインは専用の例外処理とメッセージを表示します。
    - **キャッシュ重複の可能性:** 同じフォルダでも指定方法（`local://C:/data`、`file:///C:/data`、`C:\data`）が異なると、それぞれ別個のキャッシュが `cache_dir` に作成されることがあります。ディスク容量や管理の観点から、同一フォルダは一貫した表記で登録することを推奨します。
    - **権限と読み取り可能性:** プラグインは指定フォルダへの読み取り権限が必要です。アクセス権限が不足している場合、キャッシュ生成や自動検出に失敗します。
    - **トラブルシューティング:** 問題が発生した場合は、`cache_dir` 内の `ckan_cache_<hash>_packages.json` とログ出力（QGIS メッセージログ）を確認してください。ローカル読み込みの詳細なエラーはメッセージダイアログやログに出力されます。

- SQLite キャッシュと配置:
    - 通常はプラグイン設定の `cache_dir` 以下に DB ファイルが作成されます（設定が無い場合は Downloads/Catalog Integration 等にフォールバックします）。
    - 実装上はローカルソースでもキャッシュ DB は `cache_dir` に作られるようになっており、プラグインはローカルフォルダ内に DB を作成しない設計です。

- ローカル検索の挙動:
    - ローカルフォルダ指定の場合、まず `packages.json` を優先読み込みします。存在しない場合は自動生成を試み、その後キャッシュを生成して通常の検索・フィルタが利用可能になります。

- 注意事項:
    - ローカル JSON は CKAN の形式に準拠していることが望ましい。形式が異なる場合、期待通りに読み込めないことがあります。
    - 自動生成の際は、システムファイルや一時ファイルを除く**すべてのファイル**をスキャンして package を作成します。従来の拡張子制限を撤廃し、QGISで対応可能なあらゆる形式（および将来の新形式）に自動対応します。除外されるのは一時ファイル（`.tmp`, `.bak`, `.log`等）、システムファイル（`thumbs.db`, `.DS_Store`等）、実行ファイル（`.exe`, `.dll`等）のみです。

- 最小の `packages.json` 例:

```json
[{
    "id": "pkg-001",
    "title": "sample-data",
    "resources": [
        {
            "id": "res-001",
            "name": "sample-csv",
            "format": "csv",
            "url": "https://example.com/data/sample.csv"
        }
    ]
}]
```

この仕様に合わせたローカルデータを用意すれば、CKAN サーバと同様の操作でデータを検索・取り込みできます。


## 注意事項 / Notes
- QGIS 3.x/4.x対応
    - Supports QGIS 3.x/4.x
- 旧バージョンとの互換性に注意
    - Be careful about compatibility with older versions
- 詳細なバージョン履歴は `Changlog_yamamoto.txt` を参照
    - See `Changlog_yamamoto.txt` for detailed version history


## 保存ルール / Save rules

ダウンロードしたデータはプラグインのキャッシュディレクトリ配下に保存されます。ディレクトリ構成は可読性と一意性の両立を意図して次のルールに従います。

- 全体構成:
    - <cache_dir>/<safe_host>_<hash>/<safe_package>_<package_id>/<safe_resource>_<resource_id>/<file>
    - `cache_dir` はプラグイン設定(`geo_import/cache_dir`)で指定されたディレクトリ。未設定時の既定値は `~/.geo_import_cache`（キャッシュDB作成処理では環境により `Downloads/Catalog Integration` にフォールバックする場合があります）。
        - `safe_host` は CKAN API URL のホスト部分（例: `catalog.data.metro.tokyo.lg.jp`）をファイル名に安全化した文字列。
        - `hash` はサーバーURL全体の SHA1 ハッシュの先頭8文字で、同一ホスト上でパスやポートが異なる複数インスタンスを区別するために付与されます。
        - `safe_package` はパッケージの `title`（無ければ `name`）を safe 化した文字列。
        - `package_id` は CKAN の `package['id']`（通常 UUID）で一意性を担保します。
        - `safe_resource` はリソースの `name`（無ければ `title`）を safe 化した文字列。
        - `resource_id` は CKAN の `resource['id']`（通常 UUID）。
        - `<file>` はリソースの URL から取得したファイル名（basename）。必要に応じてファイル名の安全化が行われます。

- safe 化について:
    - `util.safe_filename()` による正規化を行い、Unicode 正規化、禁止文字の置換、連続アンダースコアの縮約、長さ制限等を適用します。

- 例:
    - サーバー `https://catalog.data.metro.tokyo.lg.jp/api/3/`、パッケージ `人口統計 2019`（id=`42b6...`）、リソース `population-csv`（id=`d5ea...`）で CSV を取得すると:
        - `~/.geo_import_cache/catalog.data.metro.tokyo.lg.jp_1a2b3c4d/人口統計_42b6.../population-csv_d5ea.../population.csv`

このルールにより、同じホスト内の複数インスタンスや同名パッケージ・リソースの衝突を避けつつ、人間にも判別しやすいフォルダ構成を実現しています。


## 主な改修PYファイル / Main Modified Python Files
- `geo_import_dialog.py`（UI・検索・カテゴリ・リソース処理）
    - UI, search, category, resource handling
- `util.py`（CSV自動判定・レイヤ追加・各種ユーティリティ）
    - CSV auto-detection, layer addition, utilities


## バージョン・更新履歴 / Version & Changelog
- バージョン情報は `metadata_yamamoto.txt` を参照
    - See `metadata_yamamoto.txt` for version info
- 更新履歴は `Changlog_yamamoto.txt` を参照
    - See `Changlog_yamamoto.txt` for changelog


## 連絡先 / Contact
- GitHub: [yamamoto-ryuzo](https://github.com/yamamoto-ryuzo)

## 免責事項

本システムは個人のPCで作成・テストされたものです。  
ご利用によるいかなる損害も責任を負いません。

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>





