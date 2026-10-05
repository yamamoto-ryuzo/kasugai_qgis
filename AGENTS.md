# AGENTS.md

AI エージェントがこのリポジトリで作業する際のルール。

## プロジェクト概要

- Rust (Axum) 製の QGIS ランチャー。`--server` で HTTP API サーバー（既定ポート 8500）と Web UI を提供する
- Web UI は `public/index.html`。`include_str!` で EXE に埋め込まれるため、UI 変更の反映には再ビルドが必要
- バージョンは `Cargo.toml` が唯一の正。`run.py` が `setup.nsi` / `update.json` / `qgis_settings.json` に自動同期する

## ビルド・実行

- 型チェック: `cargo check`
- 開発実行（サーバーモード + ブラウザ自動オープン）: `python run.py`
- リリース一式ビルド: `python run.py --build`
- バージョンアップ + リリースビルド: `python run.py --bump X.Y.Z`
- git タグ作成: `python run.py --tag`

## テスト

- **Web UI の動作確認は必ず Playwright で行うこと**
  - `python run.py`（または `cargo run -- --server`）でサーバーを起動し、`http://127.0.0.1:8500/` に対して Playwright でブラウザ操作・検証を行う
  - 確認対象の例: タブ切り替え、各フォームの表示順・初期値、起動/保存ボタンの挙動、ステータス表示
  - 目視やスクリーンショット貼り付けだけで完了とせず、Playwright による操作で実際の挙動を検証する
- API 単体の確認は `curl` 等で `/health`, `/settings`, `/launch` などを叩いてもよいが、UI に関わる変更は Playwright での確認を必須とする
- 注意: `POST /launch` を実行するとサーバーは QGIS 起動後に自動停止する（v2.0.5 以降）。テスト時はサーバーの再起動が必要になる場合がある

## 言語方針

- **リポジトリの基本言語は日本語**とする。ドキュメント・コードコメント・`public/index.html` のリテラルテキスト（`data-i18n` 適用前の初期表示）は日本語で記述する
- **アプリの翻訳（i18n）の基準言語は英語**とする。`public/i18n/en.json` がフォールバック辞書であり、`t()` はキー未登録時に en の値を返す
- 新しい翻訳キーを追加するときは `en.json` を正本として先に追加し、全言語の辞書（`public/i18n/*.json`）でキー数を一致させる
- 対応言語は `public/i18n.js` の `SUPPORTED_LANGUAGES` で管理。言語追加は同配列と辞書ファイルの追加に加え、`src/main.rs` の `/i18n/<lang>.json` 配信ルートの登録が必要（辞書は `include_str!` で EXE に埋め込まれる）
- UI に文言を追加するときは `data-i18n` / `data-i18n-ph` / `data-i18n-args` 属性、または JS 内で `t('key', {params})` を使う。動的生成要素は描画後に `applyI18n()` を呼ぶ（`renderRawForm()` 内で実施済み）

## リリース手順

1. `python run.py --bump X.Y.Z` でバージョン更新 + ビルド一式生成（整合性チェックまで自動実行）
2. `CHANGELOG.md` に変更内容を追記
3. コミット後、`python run.py --tag` でタグ作成し、`git push origin main --follow-tags`
