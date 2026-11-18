# CHANGELOG — geo_launcher

## [Unreleased]

- 修正: リロード/ホットリロードのたびに管理ダイアログが勝手に
  前面へ出る問題 — plugin に `open_dialog_on_reload = False` を
  追加し、ドライバ側の「open_dialog 再表示」規約から opt-out。
  表示はツールバー/メニュー/bridge `openDialog`/`open_plugin` の
  明示操作のみとなる(geo_driver 側も同フラグを参照するよう
  同時修正)

## 1.1.2

- 変更: プラグイン ID を `kasugai_launcher` → `geo_launcher` にリネーム
  (`geo_` シリーズ統一)。フォルダ名・ブリッジ `pluginId`・
  QSettings プレフィックス・`tr` コンテキスト・i18n カタログの
  トップキーを新IDへ移行。旧 `kasugai_launcher/*` の QSettings 値は
  残置されるが読み込みはされない。機能変更なし

## 1.1.1

- 修正: インストールが完了しない問題 — 非サイレント時に `QProcess.startDetached` で起動した NSIS ウィザードがフォアグラウンド権を取れず QGIS の後ろに隠れていた。窓を出す起動は `QDesktopServices.openUrl`(ShellExecute)に変更
- 変更: `silent_install` の既定を ON(「インストール」1クリックで DL→導入まで完走。設定で OFF に戻せば従来通りウィザード表示)
- 修正: サイレントインストール後にプログレスバーが「実行中」のまま残る問題 — `/S` は `QProcess` で終了を追跡し `done` に遷移(非0終了はエラー表示)。非サイレントはウィザードへ引き渡した時点で `done`
- 修正: DL が HTTP200・0バイトで失敗する問題 — GitHub Pages が `Accept-Encoding: gzip` に `Content-Encoding: gzip` で応答し Qt の透過伸張で total=-1 となっていた。`Accept-Encoding: identity` を要求して Content-Length を確実に受け取り進捗%表示を可能に
- 修正: 共有ネットワークキャッシュの空/中断済みエントリによる 0 バイト応答対策(`CacheLoadControl.AlwaysNetwork` + `CacheSaveControl=False`)と 0 バイト・NoError 時の自動リトライ(最大2回)
- 改善: DL 中の進捗は `Content-Length` 無し(GitHub Pages)の場合 MB 表示に切替
- 改善: DL/セットアップ実行中のみ 2 秒ポーリングし、サイレント導入完了後に検出状態が自動更新されるようにした

## 1.1.0

- 設計見直し: kasugai_qgis は QGIS 起動後に自動終了する器なので、
  プラグインの責務を「インストール/アンインストールと GUI 窓オープン」に限定
- 撤去: API サーバ関連機能一式(headless 起動・Web UI オープン・サーバ停止・
  サーバ状態表示・更新チェック/適用・port/launch_mode 設定・ポーリングタイマー)
- 追加: 「この QGIS」の起動経由表示(`PORTAL_USERROLE` でランチャー経由か判定、
  ロール名を表示)と「ランチャーは QGIS 起動後に自動終了する」旨の注記
- 変更: バージョン表示を `qgis_launcher.exe --version` 実行で取得
  (qgis_settings.json では確実に取れなかったため)
- bridge を 12 メソッドに整理(撤去: isRunning/serverInfo/openUi/
  checkUpdate/applyUpdate/stopServer、setSettings 対応キーは
  exe_path/silent_install のみ)
- i18n カタログを現行キーセット(30 キー)に再生成

## 1.0.1

- インストール/アンインストールをダイアログ最上段の大ボタン化(緑/赤)
- アンインストール追加: `uninstall.exe` を起動(`/S` 可)。稼働中サーバは確認後に停止→起動。bridge `uninstall` も追加
- 修正: Qt6 で `Qt.TextSelectableByMouse` が無いため `Qt.TextInteractionFlag.TextSelectableByMouse` へ
- 修正: セットアップ DL を `QNetworkAccessManager` → `QgsNetworkAccessManager.instance()` に変更(QGIS のプロキシ/SSL 設定を継承。素の NAM では DL が "未知のエラー" で失敗していた)
- DL 失敗時のエラー詳細化(QNetworkReply エラー名 + HTTP ステータス)

## 1.0.0

- 初版。kasugai_qgis ランチャー(Rust/Axum、既定 port 8500)を QGIS から管理
- 検出: QSettings → `C:\kasugai\kasugai_qgis\qgis_launcher.exe` → glob
- インストール: GitHub Pages の `kasugai_qgis-setup.exe` を QNetworkAccessManager で非同期 DL → インストーラー起動(`/S` サイレント可)
- 起動: GUI(WebView2)/ headless(URI 位置引数で API サーバのみ)の 2 モード
- Web UI オープン(未起動時は headless 起動→ヘルスポーリング→ブラウザ)
- サーバ停止・更新チェック/適用(`/update`・`/update/apply` 中継)
- AI 制御ブリッジ(bridge.py): status/launch/openUi/install/installStatus/checkUpdate/applyUpdate/stopServer/getSettings/setSettings/openDialog/openSettings/openDocs
- i18n: en ソース + ja/de/es/fr/hi/it/pt/ru/zh の 9 言語カタログ
- GeoSuite 共有ツールバーへアイコン集約
