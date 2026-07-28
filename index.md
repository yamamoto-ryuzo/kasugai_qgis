# QGIS Launcher (qgis_launcher)

[インストーラーはこちらから](https://yamamoto-ryuzo.github.io/kasugai_qgis/public/kasugai_qgis-setup.exe)

![alt text](https://yamamoto-ryuzo.github.io/kasugai_qgis/images/qgis_launcher.png)
![alt text](https://yamamoto-ryuzo.github.io/kasugai_qgis/images/qgis_launcher_info.png)

> **v2.0.0 以降**: FLTK GUI は削除され、Web UI（ブラウザ）+ AXUM HTTP API に移行しました。本ドキュメントの画面イメージは旧 FLTK 版のものです。

## 目次

- [画面構成](#画面構成)
- [導入・起動方法](#導入起動方法)
- [自動更新](#自動更新)
- [qgis_settings.json 制御](#qgis_settingsjson-制御)
- [ユーザーロール制御](#ユーザーロール制御)
- [クラウドドライブ自動割り当て（drive_mappings）](#クラウドドライブ自動割り当てdrive_mappings)
- [ローカル自動同期（KASUGAI/yr-qgis-launcher 方式）](#ローカル自動同期kasugaiyr-qgis-launcher-方式)
- [ライセンス](#ライセンス)
- [CHANGELOG](#changelog)
- [免責事項](#免責事項)

## 画面構成

以下はランチャーの実際のメイン画面構成を要素単位で整理したものです（左上から順に操作を行い、下部で状態確認や操作を行うレイアウトを想定しています）。

- 概要: 起動設定（プロファイル / プロジェクトパス / QGIS Version）に基づいて QGIS / QField を起動するデスクトップランチャーです。設定は `qgis_settings.json`（構造は `QgisSettings`）に保存され、Web UIまたは CLI モードで操作できます。

### メイン要素

- プロファイル（ドロップダウン）
  - 説明: 使用する QGIS プロファイルを選択します。
  - 備考: 設定基準フォルダの `profiles` と `%APPDATA%` 以下を自動検出します。

- プロジェクト（ドロップダウン）
  - 説明: `project_path` に設定された候補（ファイルまたはフォルダ）から起動する `.qgs` / `.qgz` を選択します。
  - 表示: 「親フォルダ名 - ファイル名」（例: `ProjectFiles - ProjectFile.qgs`）。

- プロジェクト・バージョン
  - 説明:  `Project File Version` を表示します。この項目は選択したプロジェクトファイルがどの QGIS バージョンで作成されたかを示します。

- QGIS Version（ドロップダウン）
  - 説明: システム上で検出した QGIS 実行ファイルを一覧表示します。複数バージョンがある場合は起動時に選択可能です。
  - 補足: 選択したプロジェクトファイルの `version` 属性に基づき、同バージョンの QGIS 実行ファイルを自動で初期選択します（Web UI のドロップダウンでいつでも手動変更可能）。

- ユーザーロール（ドロップダウン）
  - 説明: `Viewer` / `Editor` / `Administrator` のいずれかを選択します。選択したロールは QGIS 起動時に `--customizationfile` / `--globalsettingsfile` / `--code` で渡され、QGIS 内の UI 表示やレイヤーの編集可否に反映されます。
  - 備考: 詳細な振る舞い（どの設定ファイルが渡されるか等）は下部の「ユーザーロール制御」セクションに記載しています。


- ボタン類（下部）
  - `Launch QGIS`: 選択中の設定で QGIS を起動します。
  - `Reset Profiles`: 配布プロファイルを再配布／強制上書きする操作用（モーダルで進捗表示）。

- 状態表示領域
  - 説明: QGIS 実行ファイル検出や起動ログ、エラーメッセージなどを短く表示する領域です。

### 動作方針（重要）

- `project_path` は設定上の候補一覧です。Web UI 上でプロジェクトを選択しても `project_path` 自体は書き換わりません。選択は `current_project` に保存され、次回起動時の初期選択に使われます。
- `Project File Version` は **選択されたファイルのみ** を解析して表示します（範囲を限定することで最小限の負荷を確保）。
- `.qgz` の取り扱い: ランチャーは `.qgz` を一時展開せずに ZIP を読み取り、最初に見つかった `.qgs` を解析してバージョン情報を抽出します。
- 解析結果キャッシュ: 取得したバージョン文字列は内部キャッシュに保存し、ファイルの最終更新時刻が変わらない限り再解析しません（表示の高速化）。
- CLI モード（`--cli`）: Web UI を起動せず設定に基づいて直接 QGIS を起動します。

これにより、ユーザーは画面上で起動に必要な項目を左上から順に設定し、下部で状態確認・起動操作を行えるようになります。

- Web UI: デフォルトでは簡易 Web UIを起動します。Web UI はプルダウンでプロファイル、プロジェクト、QGIS バージョンを選択して「Launch QGIS」で起動します。プロファイル候補は `%APPDATA%` 下の QGIS プロファイルパス（`get_qgis_profile_paths()`）と、設定基準フォルダ配下の `profiles` フォルダを参照します。プロジェクト候補は `project_path` に指定されたファイル／フォルダを上記ルールで解決して列挙します。QGIS / QField の実行ファイル候補はシステム上の標準インストール箇所やポータブル配布を探索して自動検出します。

### QGIS バージョン別プロファイル配信

設定基準フォルダ配下の `profiles` フォルダに `QGIS3\` / `QGIS4\` サブフォルダを作成することで、インストール済みの QGIS バージョンごとに専用プロファイルを自動配信できます。

- **コピーのタイミング**: EXE 起動時に自動実行されます（「Launch QGIS」ボタン押下前）。コピー先にファイルが既に存在する場合はスキップされるため、複数回起動しても無駄なコピーは発生しません。
- **Web UI の挙動**: Web UI で起動した場合、起動処理（`SUBST` によるドライブ割当てやプロファイルの配布コピー）はバックグラウンドで実行され、モーダルの進捗ウィンドウ（メッセージ + プログレスバー）で進捗を確認できます。CLI 起動では従来どおりコンソールログのみが出力されます。
- **備考**: プロファイルの初期化（配布コピー）は設定で `project_root` が指定されている場合はそのディレクトリを基準に行われます。未指定時は設定ファイル所在フォルダ（通常は EXE の親フォルダ）を使用します。
- **バージョン自動検出**: システムにインストールされている全 QGIS を自動検出し（`ProgramFiles`、`C:\OSGeo4W`、レジストリ等を探索）、検出したメジャーバージョンごとにコピーを行います。QGIS 3 と QGIS 4 が両方インストールされている場合は両方に同時にコピーされます。
- バージョンの判定はインストールフォルダ名から行います（例: `QGIS 3.44.8` → バージョン 3）。
- `QGIS3\` / `QGIS4\` フォルダが存在しない場合は `profiles\` 直下（共通）を全バージョンに使用します。
- バージョン検出の判定順位: パス中に `QGIS 4` / `QGIS4` → バージョン 4。`QGIS 3` / `QGIS3` → バージョン 3。検出不能な場合は `profiles\` 直下を使用。

フォルダ構成例:

```
(設定基準フォルダ)/
  profiles/
    QGIS3/
      geo_custom/    ← QGIS 3.x 用プロファイル → %APPDATA%\QGIS\QGIS3\ へコピー
    QGIS4/
      geo_custom/    ← QGIS 4.x 用プロファイル → %APPDATA%\QGIS\QGIS4\ へコピー
```

> **注意**: コピー先に既存ファイルがある場合は上書きしません（ユーザーの設定変更を保護）。配信ファイルを更新してユーザー側に反映させたい場合は、コピー先の該当ファイルを削除してから再起動してください。
>
> ランチャーの Web UI には「Reset Profiles」ボタンがあり、配布プロファイルの再コピーと既存プロファイルの強制削除を一括で実行できます。実行中はメッセージとプログレスバーを備えたモーダル風ウィンドウで進捗を確認でき、完了すると自動で閉じてメインウィンドウに結果が表示されます。大量のファイル削除／コピーを伴う処理のため、完了まで時間がかかる場合があります。

### CLI モード

- `--cli` を指定すると Web UI を起動せずに CLI モードで動作します。
- 現状、`Reset Profiles` は Web UI 操作用の機能として提供しています（Web UI 起動時に利用可能）。

## qgis_settings.json 制御
### 適用順序は次のとおりです：

```
qgis_settings.json              ①ベース設定
  ↓
qgis_settings_override.json     ②全ユーザー強制オーバーライド（任意）
  ↓
qgis_settings_{USERNAME}.json   ③ユーザー個別オーバーライド（任意）← 最終適用
```

③が最後に適用されるため、ユーザー個別設定（③）は全ユーザー強制オーバーライド（②）より優先されます。

### ファイル配置例

```
C:\qgis_launcher\
  qgis_settings.json              ← 全員共通のベース設定
  qgis_settings_override.json     ← 全ユーザーに強制適用（任意）
  qgis_settings_yamamoto.json     ← yamamoto ユーザーのみ上書き（任意）
```

### `project_root`（新しいオプション）

ランチャーは設定内の `project_path` を解決する際に基準となるルートフォルダを使用します。`project_root` を `qgis_settings.json` に追加すると、相対パスの解決基準を明示的に指定できます。未指定の場合は従来どおり設定ファイルの所在フォルダ（通常は EXE の親フォルダ）が基準となります。

例:

```json
{
  "project_root": "Q:/",
  "project_path": [
    "data_projects",
    "other_projects/ProjectFile.qgs"
  ]
}
```

挙動:
- `project_root` が絶対パスならそのまま使用されます（ドライブ指定 `Q:/...` 等）。
- `project_root` が相対パスなら設定ファイルの所在フォルダに対して結合して解決されます。
- `project_path` の各エントリが相対パスの場合はこの `project_root` を基準に探索されます。

注意: JSON 内の Windows パスはバックスラッシュを `\\` でエスケープするか、スラッシュ (`/`) を使用してください。ランチャーには入力時にバックスラッシュ補正処理が入っていますが、明示的にエスケープすることを推奨します。


### 全ユーザー強制オーバーライド（qgis_settings_override.json）

`qgis_settings.json` と同じディレクトリに `qgis_settings_override.json` を置くと、**ユーザー名に関係なくすべてのユーザーに対して**設定を強制上書きできます。

#### マージ動作

マージルールはユーザーオーバーライドと同じです：

| キー | マージ方式 |
|---|---|
| `drive_mappings` | `drive` キーで既存エントリを照合してフィールド単位で上書き（未指定フィールドは維持） |
| `path_aliases` | マップキー単位でマージ（未指定キーは維持） |
| その他のキー | 値ごと置き換え |

#### 用途例

特定の `profile` を全員に強制したい場合：

```json
{
  "profile": "corporate_profile"
}
```

特定のドライブマウントを全員に強制追加したい場合（他のフィールドはベースのまま）:

```json
{
  "drive_mappings": [
    {
      "drive": "S:",
      "mode": "subst",
      "local_cache": "C:\\shared_data"
    }
  ]
}
```

サンプルファイル: [qgis_launcher/download/qgis_settings_override.json.example](https://yamamoto-ryuzo.github.io/kasugai_qgis/download/qgis_settings_override.json.example)
### ユーザーごとの設定オーバーライド（qgis_settings_{USERNAME}.json）

BOX のフォルダ階層はユーザーによって異なる場合があります。`qgis_settings.json` と同じディレクトリに `qgis_settings_{Windowsログイン名}.json` を置くと、全員共通のベース設定を上書きできます。

#### ファイル命名規則

```
C:\qgis_launcher\
  qgis_settings.json              ← 全員共通のベース設定
  qgis_settings_tanaka.json       ← tanaka ユーザーのみ上書き
  qgis_settings_yamamoto.json     ← yamamoto ユーザーのみ上書き
```

`{USERNAME}` は Windows の `%USERNAME%` 環境変数（ログインユーザー名）と一致させてください。

#### マージ動作

| キー | マージ方式 |
|---|---|
| `drive_mappings` | `drive` キーで既存エントリを照合してフィールド単位で上書き（未指定フィールドはベースを維持） |
| `path_aliases` | マップキー単位でマージ（未指定キーはベースを維持） |
| その他のキー | 値ごと置き換え |

#### オーバーライドファイルの例

`robocopy_src` だけを変えたい場合（他のフィールドはベースのまま）:

```json
{
  "drive_mappings": [
    {
      "drive": "Q:",
      "robocopy_src": "BOX:\\MyFolder\\Geo_Portal"
    }
  ]
}
```

`path_aliases` の BOX パスだけをユーザーごとに変えたい場合:

```json
{
  "path_aliases": {
    "BOX": "D:\\Box"
  }
}
```

サンプルファイル: [qgis_launcher/download/qgis_settings_USERNAME.json.example](qgis_launcher/download/qgis_settings_USERNAME.json.example)

---
## ユーザーロール制御

Web UI の「User Role」ドロップダウンで `Viewer` / `Editor` / `Administrator` を選択すると、QGIS の UI がロールに応じて制限されます。

### 仕組み

QGIS 起動時に以下の 3 つの引数が自動で設定されます：

| 引数 | ファイル | 内容 |
|---|---|---|
| `--customizationfile` | `ini/<role>.xml`（QGIS4） または `ini/<role>.ini`（QGIS3） | ランチャーが QGIS 実行ファイルパスからメジャーバージョンを判定し、QGIS4 では `.xml`（Customization XML）を、QGIS3 では `.ini` をそれぞれ必ず渡します（フォールバックは行いません）。 |
| `--globalsettingsfile` | `ini/qgis_global_settings.ini` | `userrole` を QGIS グローバル変数として設定（プロジェクト式 `@userrole` で参照可能）。ランチャーはこのファイルを生成して渡します。 |
| `--code` | `ini/startup.py` | 起動後に動的制御（ツールバー表示・レイヤーのReadOnly設定）|

```
qgis.exe --profile geo_custom
         --customizationfile   ini/Viewer.xml  # QGIS4 の場合
         --customizationfile   ini/Viewer.ini  # QGIS3 の場合
         --globalsettingsfile  ini/qgis_global_settings.ini
         --code                ini/startup.py
```

ランチャーは子プロセスの環境に `PORTAL_USERROLE` を注入します（`launch_qgis` が `cmd.env("PORTAL_USERROLE", role)` を設定）。`startup.py` は QGIS グローバル変数 `userrole` を参照し、存在しなければ `PORTAL_USERROLE` を参照するため、両者を併用することで確実にロール情報を伝達します。

### ロールごとの制御内容

| ロール | カスタマイズファイル（QGIS4 / QGIS3） | UI 制御 | レイヤー |
|---|---|---|---|
| **Viewer** | `Viewer.xml`（QGIS4 / 推奨） / `Viewer.ini`（QGIS3） | 編集メニュー・編集ツールバーを非表示 | プロジェクト読み込み時に全ベクターレイヤーを ReadOnly に設定 |
| **Editor** | `Editor.xml`（QGIS4） / `Editor.ini`（QGIS3） | プロジェクト新規作成・保存メニューを非表示（編集操作は許可） | 制限なし |
| **Administrator** | `Administrator.xml`（QGIS4） / `Administrator.ini`（QGIS3） | 制限なし | 制限なし |

基本は QGIS4 を想定しており、ランチャーは QGIS の実行ファイルパスからメジャーバージョンを判定して、可能な限り QGIS4 用の `*.xml`（Customization XML）を渡します。QGIS3 を使用する環境では `*.ini` を渡します。現在の実装ではメジャーバージョンに応じて必ず適切な拡張子を使用し、フォールバックは行いません。

### ファイル構成

```
qgis_launcher.exe と同階層/
  ini/
    Viewer.xml                  ← QGIS4 用 Customization XML（推奨）
    Viewer.ini                  ← QGIS3 用 INI フォーマット（互換）
    Editor.xml
    Editor.ini
    Administrator.xml
    Administrator.ini
    qgis_global_settings.ini    ← 起動のたびに自動生成（userrole を記録）
    startup.py                  ← QGIS 起動後に自動実行されるスクリプト
```

> **注意**: `ini/` フォルダが実行ファイルと同階層に存在しない場合、ロール制御はスキップされます（エラーにはなりません）。

### startup.py の動作タイミング

| タイミング | 処理 |
|---|---|
| 起動後 500ms | UI 制御（ツールバー表示/非表示、ボタンの有効/無効）|
| プロジェクト読み込みのたびに | Viewer の場合、全ベクターレイヤーを ReadOnly に設定 |

- 設定ファイルの探索と優先度:
	- ランチャー実行時の設定基準フォルダは **`qgis_launcher.exe` と同じディレクトリ** になります。
	- ※以前のバージョンで存在した `C:\qgis_launcher` への固定フォールバックや、JSON内部での絶対パス指定は廃止され、常に「EXEの配置場所」ベースでポータブルに動作するようになりました。

- プロファイル選択の優先順位:
	1. `qgis_settings.json` の `profile` が空でない場合はそれを使用
	2. そうでなければ CLI の `--profile` 引数
	3. それでも無ければ `default` を使用

- QGIS 実行ファイルパスの優先順位（重要）:
	1. CLI 引数 `--qgis_executable`（明示指定）
	2. `qgis_settings.json` の `qgis_executable` フィールド
	3. レジストリやファイル関連付けからの自動検出（`find_qgis_path_from_registry()`）
	4. 見つからない場合はエラーで終了します（実装上、レジストリ検出に失敗すると起動を中止します）。

- ビルド・実行例:

```powershell
cd qgis_launcher
cargo build --release
# ランチャー（デフォルトは Web UI を起動）
cargo run --release
# CLI モードで即座に起動
cargo run --release -- --cli
``` 

- 備考: `Cargo.toml` は `axum`、`tokio`、`tower-http` を利用したヘッドレス API サーバー構成になっており、FLTK や `gui` feature は削除されています。Web UI は `public/index.html` に同梱されています。

---
## クラウドドライブ自動割り当て（drive_mappings）

※注意: Web ポータル（ブラウザ）側では `rclone` を実行してマウントする処理は行いません。
`drive_mappings` 設定は互換性のため読み書き・保持しますが、実際のドライブ割り当てや rclone の起動は
ローカルの `qgis_launcher` 実行環境（ランチャー）側でのみ行われます。ランチャーを使用しない環境ではこの設定は無視されます。

QGIS 起動前に任意のフォルダをドライブレターへ自動割り当てする機能です。
追加インストール不要の `subst` モードを採用しています。

**対応クラウドストレージ**: BOX Drive / OneDrive / Google Drive for Desktop など、ローカルフォルダとして同期されるすべてのクラウドストレージに対応します。

### ドライブ構成と役割（BOX の例）

```
BOX Drive (BOX:\Geo_Portal = %USERPROFILE%\Box\Geo_Portal)
    │
    │  robocopy /MIR（起動時に自動実行）
    │  ← BOX → ローカルの一方向コピー
    ▼
ローカルキャッシュ (C:\qgis_cache\master)
    │
    │  subst
    ▼
  Q:  参照用・高速読み取り専用

BOX Drive (BOX:\Geo_Portal = %USERPROFILE%\Box\Geo_Portal)
    │
    │  subst
    ▼
  R:  編集用・BOX Drive アプリが BOX へ自動同期
```

| ドライブ | 書き込み先 | BOX への反映 | 用途 |
|---|---|---|---|
| Q: | ローカル SSD | **されない** | QGIS 高速参照専用。起動時に robocopy でキャッシュを最新化 |
| R: | BOX Drive フォルダ | BOX Drive アプリが自動同期 | データ編集・保存 |

QGIS プロジェクトファイル（.qgs）のデータソースパスを `Q:\data\道路.gpkg` のように
ドライブレターで統一でき、チーム全員が同じ `.qgs` ファイルを共有できます。

> **注意**: Q: に直接保存したデータは BOX へ反映されません。編集・保存は R: を使用してください。

### qgis_settings.json の設定例

```json
{
  "path_aliases": {
    "BOX": "%USERPROFILE%\\Box",
    "OneDrive": "%OneDrive%",
    "SharePoint": "%OneDriveCommercial%\\<サイト名>\\Geo_Portal",
    "OneDriveBiz": "%OneDriveCommercial%",
    "GoogleDrive": "G:\\マイドライブ"
  },
  "drive_mappings": [
    {
      "drive": "Q:",
      "mode": "subst",
      "local_cache": "C:\\qgis_cache\\master",
      "robocopy_src": "BOX:\\Geo_Portal",
      "robocopy_exclude": ["secret-folder", "private-data"]
    },
    {
      "drive": "R:",
      "mode": "subst",
      "local_cache": "BOX:\\Geo_Portal"
    }
  ]
}
```

| フィールド | 説明 |
|---|---|
| `drive` | 割り当て先ドライブレター（例: `Q:`） |
| `mode` | `subst`（省略時は `subst`） |
| `local_cache` | 割り当て元フォルダのパス（必須。`BOX:\\path` ・ `%VAR%` 記法対応） |
| `robocopy_src` | 指定時は起動時に `robocopy /MIR` で `local_cache` へミラーリング（`BOX:\\path` ・ `%VAR%` 記法対応）。**コピー方向は `robocopy_src` → `local_cache` の一方向** |
| `robocopy_exclude` | robocopy の除外サブフォルダ名の配列（例: `["secret-folder", "private-data"]`）|

`path_aliases` ではエイリアス名（2文字以上）をパスにマッピングできます。`BOX` は未定義時のデフォルトで `%USERPROFILE%\Box` に解決されます。OneDrive / Google Drive 等も同様に定義できます。

| 記法例 | 展開後 |
|---|---|
| `BOX:\Geo_Portal` | `C:\Users\<ユーザ>\Box\Geo_Portal`（`BOX` エイリアス展開） |
| `OneDrive:\Documents` | `C:\Users\<ユーザ>\OneDrive\Documents`（`%OneDrive%` 展開） |
| `OneDriveBiz:\Geo_Portal` | `C:\Users\<ユーザ>\OneDrive - 会社名\Geo_Portal`（`%OneDriveCommercial%` 展開） |
| `GoogleDrive:\Geo_Portal` | `G:\マイドライブ\Geo_Portal`（Google Drive のドライブレターを指定） |
| `%USERPROFILE%\Box\Geo_Portal` | `C:\Users\<ユーザ>\Box\Geo_Portal` |
| `C:\qgis_cache\master` | そのまま |

### 事前準備

**使用するクラウドストレージに応じて以下を設定してください。**

| クラウド | 準備 | エイリアスの基準 |
|---|---|---|
| **BOX Drive** | BOX Drive アプリをインストール、対象フォルダをオフライン同期（常にこのデバイス上に保持）に設定 | `%USERPROFILE%\Box`（デフォルト、または `path_aliases` で変更） |
| **OneDrive（個人）** | OneDrive アプリが動作していれば `%OneDrive%` 環境変数が自動設定される | `%OneDrive%` |
| **OneDrive（法人/Microsoft 365）** | サインイン後に `%OneDriveCommercial%` 環境変数が自動設定される | `%OneDriveCommercial%` |
| **Google Drive for Desktop** | Google Drive for Desktop をインストール、ドライブレター（例: `G:`）を確認 | `G:\マイドライブ`（ドライブレターは環境により異なるため `path_aliases` で指定） |
| **SharePoint（ライブラリ）** | ブラウザで対象の SharePoint サイトのドキュメントライブラリを開き「同期」をクリックして OneDrive と同期してください。同期後に作成されるローカルフォルダ（通常は `%OneDriveCommercial%` 以下）を `path_aliases` に設定してください（例: `%OneDriveCommercial%\\<サイト名>\\Geo_Portal`）。 | `%OneDriveCommercial%\\<サイト名>\\Geo_Portal` |

- Q: の `local_cache`（`C:\qgis_cache\master` 等）は初回起動時に自動作成されます。
- OneDrive は会社名がパスに含まれる（例: `OneDrive - 株式会社XXX`）ため、ユーザーごとにパスが異なる場合があります。その場合は[ユーザーオーバーライド](#ユーザーごとの設定オーバーライドqgis_settingsusername.json)で `path_aliases` を上書きしてください。

---

## ローカル自動同期（KASUGAI/yr-qgis-launcher 方式）

`qgis_launcher.exe` と同じフォルダに `qgislocalsync.config` を配置すると、起動時に自動でローカル同期を行います。これは KASUGAI（yr-qgis-launcher）の `local-launcher.bat` と同等の機能です。Web UI 下部の **Update** ボタンから手動で再実行することもできます。

### 仕組み

- `SYNC_SRC` → `SYNC_DST` へ、トップレベルのファイル・フォルダを `robocopy /MIR` でミラー同期します。
- `QField*` / `QGIS*` フォルダはバージョン文字列を比較し、変更がある場合のみ同期します。
- `portable_profile` フォルダも同様に `portable.ver` と比較して変更時のみ同期します。

### 設定ファイル（`qgislocalsync.config`）

```ini
# 同期元フォルダ（環境変数も利用可能）
SYNC_SRC=C:\github\yr-qgis-launcher

# 同期先フォルダ（環境変数も利用可能）
SYNC_DST=C:\qgis-local-launcher

# QField バージョン（任意文字列可）
QFIELD_VERSION=3.4.2

# QGIS バージョン（任意文字列可）
QGIS_VERSION=3.42.0

# ポータブルプロファイルのバージョン（任意文字列可）
PORTABLE_PROFILE_VERSION=1.0.0

# 除外フォルダ（スペース区切り）
EXCLUDE_DIRS=secret-folder private-data
```

| キー | 説明 |
|---|---|
| `SYNC_SRC` | 同期元フォルダ。クラウドストレージやネットワークドライブ上のマスターを指定できます。 |
| `SYNC_DST` | 同期先フォルダ。ローカル SSD 等を推奨します。 |
| `QFIELD_VERSION` | QField ポータブル版のバージョン文字列。`SYNC_DST/LOCAL_QFIELD_VERSION` と比較されます。 |
| `QGIS_VERSION` | QGIS ポータブル版のバージョン文字列。`SYNC_DST/LOCAL_QGIS_VERSION` と比較されます。 |
| `PORTABLE_PROFILE_VERSION` | 配布プロファイルのバージョン文字列。`SYNC_DST/portable.ver` と比較されます。 |
| `EXCLUDE_DIRS` | トップレベル同期で除外するフォルダ名（スペース区切り）。 |

### `qgis_settings.json` からの上書き

`qgislocalsync.config` が無い、または一部のキーが未指定の場合、`qgis_settings.json` の `local_sync` セクションをフォールバックとして使用できます。ただし `qgislocalsync.config` の値が優先されます。

```json
{
  "local_sync": {
    "sync_src": "C:\\github\\yr-qgis-launcher",
    "sync_dst": "C:\\qgis-local-launcher",
    "qfield_version": "3.4.2",
    "qgis_version": "3.42.0",
    "exclude_dirs": ["secret-folder", "private-data"],
    "portable_profile_version": "1.0.0"
  }
}
```

サンプルファイル: [download/qgislocalsync.config.example](download/qgislocalsync.config.example)

---

## ライセンス

### このリポジトリ

GNU General Public License v3.0 (GPL-3.0-only) — 詳細は [LICENSE](LICENSE) を参照してください。

### 同梱・依存ソフトウェアのライセンス

| ソフトウェア | ライセンス | 配布 | 備考 |
|---|---|---|---|
| **Web UI / HTTP サーバー** (Axum / Tokio / tower-http) | MIT / Apache-2.0 | 依存 | `Cargo.toml` で指定 |
| **Axum** | MIT | 依存 | HTTP ルーティング・ハンドラ |
| **Tower/Tower-HTTP** | MIT | 依存 | CORS ミドルウェア等 |
| **QGIS** | GPL v2 以降 | 別途インストール | qgis_launcher とは独立したソフトウェア |
| **StreetView (QGIS plugin)** | GPL v2 以降 | 同梱あり | `download/profiles/.../plugins/StreetView` に含まれる |

同梱・依存コンポーネントの詳細は [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) を参照してください。

### 同梱配布する場合のパッケージ構成

```
配布パッケージの構成例:
  qgis_launcher.exe
  qgis_settings.json
```

---

## 導入・起動方法

### 初回導入（インストーラー版：推奨）

NSIS インストーラー `kasugai_qgis-setup.exe` を使って、`C:\Kasugai\kasugai_qgis\` へ自動的にインストールできます。

1. インストーラーをダウンロード
   - [kasugai_qgis-setup.exe](https://yamamoto-ryuzo.github.io/kasugai_qgis/public/kasugai_qgis-setup.exe)
2. ダウンロードした `kasugai_qgis-setup.exe` を実行
   - インストール先はデフォルトで `C:\Kasugai\kasugai_qgis\` です
   - インストール先フォルダはインストール時に変更できます
   - `C:\Kasugai` フォルダが存在し、ユーザーが書き込み可能であれば管理者権限は不要です
   - スタートメニューにショートカットが作成されます
3. インストールフォルダ内の `qgis_launcher.exe` をダブルクリックで起動

#### サイレントインストール

コマンドラインから以下のように実行すると、画面を表示せずにインストールできます。

```batch
kasugai_qgis-setup.exe /S /D=C:\Kasugai\kasugai_qgis
```

### ZIP 版（インストール権限がない場合）

インストーラーの実行権限がない場合は、配布用 ZIP を任意のフォルダに展開して使用できます。

1. ZIP をダウンロード
   - [kasugai_qgis.zip](https://yamamoto-ryuzo.github.io/kasugai_qgis/public/kasugai_qgis.zip)
2. 任意のユーザー書き込み可能なフォルダ（例: `%USERPROFILE%\kasugai_qgis\` や `%LOCALAPPDATA%\kasugai_qgis\`）に展開
3. 展開したフォルダ内の `qgis_launcher.exe` をダブルクリックで起動

> 注意: ZIP 版はスタートメニューショートカットを作成しません。必要に応じて手動でショートカットを作成してください。

### 推奨フォルダ構成

```
C:\Kasugai\kasugai_qgis\
  qgis_launcher.exe
  qgis_settings.json
  ini\                 # ユーザーロール制御用（必要に応じて）
  profiles\            # 配布プロファイル（必要に応じて）
```

### 起動方法

- **Web UI 起動**: `qgis_launcher.exe` を実行
- **CLI 起動**: `qgis_launcher.exe --cli`
- **設定ファイルの所在**: `qgis_launcher.exe` と同じフォルダの `qgis_settings.json` を読み込みます

---

## 自動更新

`qgis_settings.json` に以下を設定すると、`qgis_launcher.exe` 起動時に自動で更新を確認します。

```json
{
  "update_url": "https://yamamoto-ryuzo.github.io/kasugai_qgis/update.json",
  "update_check": true
}
```

### 通常更新と全体更新

配布物は 2 種類あり、更新の内容によって使い分けます。

| 種類 | ファイル | 内容 | 用途 |
| --- | --- | --- | --- |
| 全体版 | `kasugai_qgis-setup.exe` | EXE 本体 + ini/profiles/ProjectFiles 等のデータ一式 | 初期インストール・全体更新 |
| EXEのみ版 | `kasugai_qgis-update.exe` | EXE 本体のみ（既存データは変更しない） | 通常のバージョンアップ |

`update.json` の形式:

```json
{
  "version": "1.4.1",
  "url": "https://yamamoto-ryuzo.github.io/kasugai_qgis/public/kasugai_qgis-update.exe",
  "full_url": "https://yamamoto-ryuzo.github.io/kasugai_qgis/public/kasugai_qgis-setup.exe",
  "full": false,
  "notes": "Kasugai QGIS Launcher 1.4.1"
}
```

- 通常は `full: false` のままとし、自動更新では `url` の EXE のみ版が使われます（軽量・ユーザーデータに影響なし）
- データも含めて更新したい特殊なリリースでは `full: true` にすると、`full_url` の全体版がダウンロード・実行されます

### 更新の流れ

1. 起動時に `update_url` の JSON を取得
2. リモートの `version` と現在のバージョンを比較
3. リモートの方が新しければ、`full` が `false` なら `url`（EXE のみ版）、`true` なら `full_url`（全体版）の NSIS インストーラーをダウンロード
4. ダウンロードしたインストーラーを `/S /D=<インストールフォルダ>` でサイレント実行
5. インストーラーが `qgis_launcher.exe` を上書き後、新しい exe を起動して終了

### リリース時の更新手順

1. `Cargo.toml` の `version` を更新
2. `installer/setup.nsi` の `PRODUCT_VERSION` を更新
3. `update.json` の `version` を更新（データ込みの全体更新にしたい場合のみ `full: true` を設定）
4. `cargo build --release`
5. `cd installer && build.bat` で `..\public\kasugai_qgis-setup.exe`（全体版）、`..\public\kasugai_qgis-update.exe`（EXEのみ版）、`..\public\kasugai_qgis.zip` を生成
6. GitHub に push して GitHub Pages に反映

### 注意

- 自動更新は `update_check: true` かつ `update_url` が有効な場合のみ動作します
- 更新確認に失敗しても、ランチャーは通常起動します（ネット不通時も安全）
- 通常更新（EXEのみ版）は本体 `qgis_launcher.exe` のみを更新します。プロファイル・プラグイン等は `local_sync` 機能または全体更新（`full: true`）で更新してください
- 全体更新でも `qgis_settings.json` は初回のみ配置されるため、ユーザー設定は上書きされません

---

## CHANGELOG

主な変更履歴は [CHANGELOG.md](CHANGELOG.md) を参照してください。

## 免責事項

本システムは個人のPCで作成・テストされたものです。  
ご利用によるいかなる損害も責任を負いません。  

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>



