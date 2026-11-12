# THIRD_PARTY_LICENSES

このドキュメントは、本リポジトリが依存・同梱するサードパーティソフトウェアのライセンスをまとめたものです。

## 本リポジトリ

GNU General Public License v3.0 (GPL-3.0-only) — [LICENSE](LICENSE)

## 商用利用可否の整理（要約）

**結論: 商用利用を妨げるプロプライエタリな制限付きライセンスはありません。すべてフリーのライセンスで構成されています。**

| 区分 | ライセンス種別 | 商用利用 |
|---|---|---|
| Rust 依存クレート | MIT / Apache-2.0 | ✅ 制限なし |
| 同梱 QGIS プラグイン | GPL-2.0 / GPL-3.0 / MIT | ✅ 商用利用可（GPL は再配布時にソース提供・告知義務） |
| QGIS / QField | GPL-2.0 以降 | ✅ 別途インストールの独立ソフト。起動するだけなので本体へのコピーレフト波及なし |
| rclone | MIT | ✅ 制限なし |
| WinFsp | GPL-3.0 + FLOSS 特例（別途商用ライセンスあり） | ⚠️ `mode=mount` 時のみ必要。商用利用でも無料。有料化（商用ライセンス）が必要なのは、クローズドソース製品に WinFsp を組み込んで配布する場合のみ（組織 $6,000/3年・個人 $2,400/3年） |
| WebView2 Runtime | Microsoft プロプライエタリ（無償） | ✅ 無償利用・再配布可。オープンソースではない点のみ留意 |
| NSIS（インストーラー） | zlib/libpng | ✅ 制限なし |

注意点:
- **GPL コンポーネント**（本体含む）は商用利用自体は可能ですが、**再配布時にソース提供・ライセンス表示が必須**です。プロプライエタリな製品として販売したい場合は GPL 部分を閉じられないため実質不可です（本リポジトリ自体が GPL-3.0 のため、この点は全体に適用されます）。
- **同梱プラグインは Python ソースのまま配布**されるため、GPL のソース提供要件は自動的に満たされます。
- **WinFsp** は GPLv3 + FLOSS 特例のデュアル構成です。利用者が個別にインストールする場合は商用利用でも無料です。FLOSS ソフトウェア（GPL 等）であれば無改変のインストーラを同梱配布することも特例で許容されます（著作権表示 + リポジトリリンクの条件付き）。有料の商用ライセンス（組織 $6,000/3年、個人 $2,400/3年）が必要になるのは、**クローズドソース製品**に WinFsp を組み込んで配布する場合だけです。

  > ※ クローズドソース製品 = ソースコードを公開せず、コンパイル済み実行ファイルのみを配布するプロプライエタリなソフトウェア製品（例: Microsoft Office 等）。kasugai_qgis は GPL-3.0 でソース公開済みのオープンソース（FLOSS）なので該当しません。

## 依存ライブラリ（Rust クレート）

`Cargo.toml` で管理されるビルド時依存。配布バイナリに静的に組み込まれます。

| クレート | ライセンス | 用途 |
|---|---|---|
| serde / serde_json | MIT / Apache-2.0 | 設定 JSON の読み書き |
| axum | MIT | HTTP API ルーティング・ハンドラ |
| tokio | MIT | 非同期ランタイム |
| tower-http | MIT | CORS ミドルウェア |
| clap | MIT / Apache-2.0 | CLI 引数パース |
| reqwest | MIT / Apache-2.0 | HTTP クライアント（更新チェック・ダウンロード） |
| wry | Apache-2.0 / MIT | WebView2 ウィンドウ（GUI モード） |
| tao | Apache-2.0 / MIT | ウィンドウ・イベントループ |
| winreg | MIT | レジストリ参照（QGIS 検出） |
| mslnk | MIT | ショートカット解決 |
| quick-xml | MIT | .qgs プロジェクト解析 |
| zip | Apache-2.0 / MIT | .qgz（ZIP）展開読み取り |
| sha2 | MIT / Apache-2.0 | 更新インストーラの SHA-256 検証 |

各クレートのライセンス本文は crates.io / docs.rs の当該パッケージページ、または `cargo license` 等の出力で確認できます。

## 別途インストールが必要なソフトウェア

| ソフトウェア | ライセンス | 備考 |
|---|---|---|
| QGIS | GPL v2 以降 | qgis_launcher とは独立したソフトウェア。本ランチャーは起動のみ行う |
| QField | GPL v2 以降 | 同上 |
| rclone | MIT | `drive_mappings` の `sync`/`mount` モード利用時のみ必要 |
| WinFsp | GPL v3 / 商用 | `mode=mount`（rclone mount）利用時のみ必要 |
| WebView2 Runtime | Microsoft プロプライエタリ（無償） | GUI モード利用時に必要。未導入時は起動エラー |

## 同梱 QGIS プラグイン

`download/profiles/*/profiles/*/python/plugins/` に同梱。各プラグインのライセンスは同梱 `metadata.txt` / `LICENSE` を正とします（以下は同梱物から確認した実値）。

| プラグイン | ライセンス | 備考 |
|---|---|---|
| geo_excel | GPL-3.0 | 本リポジトリ管理（QGIS Live Harness 由来） |
| geo_import | MIT | 同上 |
| geo_report | GPL-3.0 | 同上 |
| geo_search | GPL-3.0 | 同上 |
| geo_userfunc | GPL-3.0 | 同上 |
| geo_webview | GPL-3.0 | 同上 |
| qgis_live_driver | 本リポジトリ管理 | QGIS Live Harness の制御プラグイン |
| QGIS-legendView-main | GPL-3.0 | upstream: QGIS-legendView |
| StreetView | GPL-3.0 | upstream: saccon/streetview-plugin |
| ImportPhotos | GPL-3.0 | upstream: KIOS-Research/ImportPhotos |
| menu_from_project | GPL-2.0 | upstream: aeag/MenuFromProject-Qgis-Plugin |
| mmqgis | GPL-2.0 | upstream: michaelminn/mmqgis |
| mojxml_plugin | GPL-2.0 | upstream: MIERUNE/qgis-mojxml-plugin |
| plateau_plugin | GPL-2.0 | upstream: Project-PLATEAU/plateau-qgis-plugin |
| plugin_reloader | GPL-3.0 | upstream: borysiasty/plugin_reloader |
| qfieldsync | GPL-3.0 | upstream: opengisch/QFieldSync |
| Qgis2threejs | GPL-2.0 | upstream: minorua/Qgis2threejs |
| qgis2web | GPL-2.0 | upstream: qgis2web/qgis2web |
| QuickDEM4JP | GPL-2.0 | upstream: MIERUNE/QuickDEM4JP |
| searchlayers | GPL-2.0 | upstream: hamiltoncj/qgis-searchlayers-plugin |

QGIS プラグインは一般に GPL v2 以降で配布されますが、正確な条件は各プラグインの `metadata.txt`（`license=` 行）および upstream リポジトリを参照してください。
