#![windows_subsystem = "windows"]

use clap::Parser;
use std::collections::{HashMap, HashSet};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::os::windows::process::CommandExt;
use std::sync::{Arc, Mutex};
use serde::{Deserialize, Serialize};
use winreg::enums::*;

/// 子プロセスのコンソールウィンドウを非表示にする Windows フラグ
const CREATE_NO_WINDOW: u32 = 0x08000000;
use winreg::RegKey;
use quick_xml::Reader;
use quick_xml::events::Event;
use quick_xml::name::QName;
use zip::ZipArchive;
use std::io::Read;
use axum::{extract::{Query, State}, http::{header, StatusCode}, response::{Html, IntoResponse}, routing::{get, post}, Json, Router};
use tower_http::cors::CorsLayer;


#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct RcloneMount {
    pub remote: Option<String>,
    pub drive: String,
    #[serde(default)]
    pub read_only: bool,
    /// "subst"（デフォルト）/ "sync" / "mount"
    pub mode: Option<String>,
    /// ドライブに割り当てるローカルフォルダ（例: "C:\\qgis_cache\\master"）
    pub local_cache: Option<String>,
    /// robocopy のコピー元フォルダ。指定時は subst 前に robocopy を実行
    pub robocopy_src: Option<String>,
    /// robocopy で除外するサブフォルダ名のリスト（例: ["secret-folder", "private-data"]）
    #[serde(default)]
    pub robocopy_exclude: Vec<String>,
    // mount モード用オプション
    pub vfs_cache_mode: Option<String>,
    pub vfs_cache_max_age: Option<String>,
    pub vfs_cache_max_size: Option<String>,
    pub vfs_cache_poll_interval: Option<String>,
    pub vfs_write_back: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct LocalSyncConfig {
    /// 同期元フォルダ（KASUGAI/yr-qgis-launcher の SYNC_SRC に相当）
    pub sync_src: Option<String>,
    /// 同期先フォルダ（KASUGAI/yr-qgis-launcher の SYNC_DST に相当）
    pub sync_dst: Option<String>,
    /// QField バージョン文字列（qgislocalsync.config の QFIELD_VERSION と等価）
    pub qfield_version: Option<String>,
    /// QGIS バージョン文字列（qgislocalsync.config の QGIS_VERSION と等価）
    pub qgis_version: Option<String>,
    /// 除外フォルダ名リスト（qgislocalsync.config の EXCLUDE_DIRS と等価）
    #[serde(default)]
    pub exclude_dirs: Vec<String>,
    /// ポータブルプロファイルのバージョン文字列（portable.ver 対応）
    pub portable_profile_version: Option<String>,
}

impl Default for LocalSyncConfig {
    fn default() -> Self {
        Self {
            sync_src: None,
            sync_dst: None,
            qfield_version: None,
            qgis_version: None,
            exclude_dirs: Vec::new(),
            portable_profile_version: None,
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct QgisSettings {
    pub profile: String,
    pub project_path: Vec<String>,
    pub qgis_executable: Option<String>,
    pub reearth_url: Option<String>,
    pub box_url: Option<String>,
    #[serde(default)]
    pub drive_mappings: Vec<RcloneMount>,
    /// パスエイリアス表。キーが "BOX" なら "BOX:\\path" と書ける。
    /// デフォルト: {"BOX": "%USERPROFILE%\\Box"}
    #[serde(default)]
    pub path_aliases: HashMap<String, String>,
    /// ユーザーロール: "Viewer" / "Editor" / "Administrator"
    pub userrole: Option<String>,
    /// 最後に選択したプロジェクトの絶対パス（次回起動時の初期選択に使用）
    #[serde(default)]
    pub current_project: Option<String>,
    /// プロジェクト解決用のルートフォルダ。相対パス指定時の基準となる。
    /// 省略時は settings.json の所在フォルダ（デフォルト）を使用する。
    #[serde(default)]
    pub project_root: Option<String>,
    /// KASUGA-QGIS ランチャー本体のバージョン。
    /// SYNC_SRC 側の qgis_settings.json に記述しておくことで、配布元のバージョンアップを検知できる。
    #[serde(default)]
    pub kasugai_qgis_version: Option<String>,
    /// NSIS インストーラー方式の自動更新 JSON エンドポイント URL。
    /// 例: "https://example.com/kasugai_qgis/update.json"
    #[serde(default)]
    pub update_url: Option<String>,
    /// 自動更新チェックを有効にするか。省略時は update_url が設定されていれば有効。
    #[serde(default)]
    pub update_check: Option<bool>,
    /// API サーバー待ち受けポート。省略時は 8500。
    #[serde(default)]
    pub api_server_port: Option<u16>,
    /// KASUGAI/yr-qgis-launcher 方式のローカル自動同期設定。
    /// qgislocalsync.config が存在する場合はそちらを優先して読み込む。
    #[serde(default)]
    pub local_sync: Option<LocalSyncConfig>,
}

impl Default for QgisSettings {
    fn default() -> Self {
        Self {
            profile: "".to_string(),
            project_path: Vec::new(),
            qgis_executable: None,
            reearth_url: None,
            box_url: None,
            drive_mappings: Vec::new(),
            path_aliases: HashMap::new(),
            userrole: None,
            current_project: None,
            project_root: None,
            kasugai_qgis_version: None,
            update_url: None,
            update_check: None,
            api_server_port: None,
            local_sync: None,
        }
    }
}

/// 設定の `project_root` を解決して返す。
/// - `settings.project_root` が指定されていればエイリアス/環境変数を展開し、
///   絶対パスであればそのまま、相対パスなら `resolved_settings_dir` に対して結合する。
/// - 未指定なら `resolved_settings_dir` を返す。
fn compute_project_root(settings: &QgisSettings, resolved_settings_dir: &str) -> String {
    if let Some(ref r) = settings.project_root {
        if !r.trim().is_empty() {
            // パスエイリアスと環境変数展開
            let expanded = resolve_path(r, &settings.path_aliases);
            let expanded = expand_env_vars(&expanded);
            // ドライブのみ指定 (例: "C:") を受け入れるため正規化
            let expanded = normalize_drive_root(&expanded);
            let pb = PathBuf::from(&expanded);
            if pb.is_absolute() {
                return expanded;
            } else {
                return PathBuf::from(resolved_settings_dir).join(pb).to_string_lossy().to_string();
            }
        }
    }
    resolved_settings_dir.to_string()
}

/// ドライブのみ指定 (例: "C:" または "c:") をルート形式 "C:\\" に正規化する。
fn normalize_drive_root(s: &str) -> String {
    let t = s.trim();
    let mut chars = t.chars();
    if let (Some(c1), Some(c2)) = (chars.next(), chars.next()) {
        if c1.is_ascii_alphabetic() && c2 == ':' {
            let rest = &t[2..];
            // 残りが空、またはスラッシュ/バックスラッシュのみならドライブルートとみなす
            if rest.is_empty() || rest.chars().all(|ch| ch == '/' || ch == '\\') {
                return format!("{}:\\\\", c1.to_ascii_uppercase());
            }
        }
    }
    s.to_string()
}

fn get_default_settings_dir() -> String {
    env::current_exe()
        .map(|p| p.parent().unwrap().to_string_lossy().into_owned())
        .unwrap_or_else(|_| ".".to_string())
}

// debug logging to file removed

/// 文字列から最初に現れる連続する数字列を抜き出してメジャーバージョンとする。
/// 例: "QGIS 4.0.0" -> Some("4")
fn extract_major(s: &str) -> Option<String> {
    let bs = s.as_bytes();
    let mut i = 0usize;
    while i < bs.len() {
        let c = bs[i] as char;
        if c.is_ascii_digit() {
            let start = i;
            i += 1;
            while i < bs.len() {
                let c2 = bs[i] as char;
                if c2.is_ascii_digit() {
                    i += 1;
                } else {
                    break;
                }
            }
            return Some(String::from_utf8_lossy(&bs[start..i]).to_string());
        }
        i += 1;
    }
    None
}

/// 文字列中から先頭に現れる数字ドット区切りのセグメントを抽出し、
/// 最大3セグメント (major, minor, patch) を返す。
/// 例: "4.0.0-Norrköping" -> vec!["4","0","0"]
fn parse_version_parts(s: &str) -> Vec<String> {
    let mut parts: Vec<String> = Vec::new();
    let bytes = s.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        if (bytes[i] as char).is_ascii_digit() {
            // parse first number
            let start = i;
            while i < bytes.len() && (bytes[i] as char).is_ascii_digit() { i += 1; }
            parts.push(String::from_utf8_lossy(&bytes[start..i]).to_string());
            // try to parse subsequent .number segments up to 2 more
            for _ in 0..2 {
                if i < bytes.len() && bytes[i] as char == '.' {
                    // peek ahead for digits
                    let mut j = i + 1;
                    if j < bytes.len() && (bytes[j] as char).is_ascii_digit() {
                        let start2 = j;
                        while j < bytes.len() && (bytes[j] as char).is_ascii_digit() { j += 1; }
                        parts.push(String::from_utf8_lossy(&bytes[start2..j]).to_string());
                        i = j;
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
            break;
        }
        i += 1;
    }
    parts
}

/// QGIS起動用ランチャー
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// スタートアップに登録する

    /// 適用する環境設定プロファイル名
    #[arg(short, long, default_value = "geo_custom")]
    profile: String,

    /// コマンドラインモードで QGIS を起動する
    #[arg(long, default_value_t = false)]
    cli: bool,

    /// 検出されるQGIS一覧を出力して終了する（デバッグ用）
    #[arg(long, default_value_t = false)]
    list_qgis: bool,

    /// API サーバーモードで動作する（Tauri サイドカー用）
    #[arg(long, default_value_t = false)]
    server: bool,

    /// API サーバーが待ち受けるポート（未指定時は qgis_settings.json の api_server_port、それも未指定時は 8500）
    #[arg(long)]
    port: Option<u16>,

    /// 起動後に既定のブラウザで UI を開く
    #[arg(long, default_value_t = false)]
    open_browser: bool,

    /// 更新チェックを完全に無効化する（更新直後の再起動時に使用し、更新ループを防ぐ）
    #[arg(long, default_value_t = false)]
    no_update_check: bool,

    /// QGISの実行ファイルパス（指定がなければ自動検出）
    #[arg(long)]
    qgis_executable: Option<String>,
}

fn get_settings_path(custom_dir: &str) -> PathBuf {
    let target_dir = PathBuf::from(custom_dir);
    let target_path = target_dir.join("qgis_settings.json");

    if target_dir.exists() {
        return target_path;
    }

    let mut path = env::current_exe().unwrap_or_else(|_| PathBuf::from("."));
    path.pop();
    path.join("qgis_settings.json")
}

/// JSON文字列値内の不正な単一バックスラッシュを \\ に修正する。
/// Windowsのエクスプローラからコピーしたパス ("C:\foo" 等) に対応。
fn fix_backslashes_in_json(text: &str) -> String {
    // JSON文字列リテラルを1つずつ処理し、有効なエスケープ以外の \ を \\ に置換する
    let mut result = String::with_capacity(text.len());
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        if c != '"' {
            result.push(c);
            continue;
        }
        // 文字列リテラルの開始
        result.push('"');
        loop {
            match chars.next() {
                None => break,
                Some('"') => { result.push('"'); break; }
                Some('\\') => {
                    match chars.peek().copied() {
                        // 有効な JSON エスケープ: " \ / b f n r t u → 両文字を消費して出力
                        Some('"') | Some('\\') | Some('/') |
                        Some('b') | Some('f') | Some('n') | Some('r') | Some('t') | Some('u') => {
                            let next = chars.next().unwrap();
                            result.push('\\');
                            result.push(next);
                        }
                        // 無効なエスケープ → \\ に変換（次文字は消費しない）
                        _ => {
                            result.push('\\');
                            result.push('\\');
                        }
                    }
                }
                Some(other) => { result.push(other); }
            }
        }
    }
    result
}

/// ユーザーオーバーライド用 JSON ファイルを探して、ベース JSON Value にマージする。
/// ファイル名: qgis_settings_{USERNAME}.json（例: qgis_settings_yamamoto.json）
/// 存在しない場合は base をそのまま返す。
/// マージはシャロー: オーバーライド側のトップレベルキーがベースを上書き。
fn apply_user_override(base_dir: &str, base: serde_json::Value) -> serde_json::Value {
    let username = env::var("USERNAME").unwrap_or_default();
    if username.is_empty() {
        return base;
    }
    let override_path = PathBuf::from(base_dir).join(format!("qgis_settings_{}.json", username));
    if !override_path.exists() {
        return base;
    }
    apply_override_value(base, &override_path)
}

/// 無条件オーバーライド用 JSON ファイル（qgis_settings_override.json）を
/// ユーザー名に関係なく常に適用する。
/// （実装注）この関数はベース設定の直後に適用され、ユーザー個別上書きより先に処理されます。
fn apply_force_override(base_dir: &str, base: serde_json::Value) -> serde_json::Value {
    let override_path = PathBuf::from(base_dir).join("qgis_settings_override.json");
    if !override_path.exists() {
        return base;
    }
    // apply_user_override と同じマージロジックを再利用
    apply_override_value(base, &override_path)
}

/// apply_user_override / apply_force_override 共通のマージ処理
fn apply_override_value(mut base: serde_json::Value, override_path: &PathBuf) -> serde_json::Value {
    if let Ok(data) = fs::read_to_string(override_path) {
        let fixed = fix_backslashes_in_json(&data);
        if let Ok(override_val) = serde_json::from_str::<serde_json::Value>(&fixed) {
            if let (Some(base_obj), Some(over_obj)) = (base.as_object_mut(), override_val.as_object()) {
                for (k, v) in over_obj {
                    match k.as_str() {
                        "path_aliases" => {
                            if let Some(over_map) = v.as_object() {
                                let base_map = base_obj
                                    .entry(k)
                                    .or_insert_with(|| serde_json::Value::Object(serde_json::Map::new()));
                                if let Some(bm) = base_map.as_object_mut() {
                                    for (ak, av) in over_map {
                                        bm.insert(ak.clone(), av.clone());
                                    }
                                }
                            }
                        }
                        "drive_mappings" => {
                            if let Some(over_mounts) = v.as_array() {
                                let base_mounts = base_obj
                                    .entry(k)
                                    .or_insert_with(|| serde_json::Value::Array(vec![]));
                                if let Some(bm) = base_mounts.as_array_mut() {
                                    for om in over_mounts {
                                        let over_drive = om.get("drive").and_then(|d| d.as_str());
                                        if let Some(drive) = over_drive {
                                            if let Some(base_entry) = bm.iter_mut().find(|e| {
                                                e.get("drive").and_then(|d| d.as_str()) == Some(drive)
                                            }) {
                                                if let (Some(be), Some(oe)) =
                                                    (base_entry.as_object_mut(), om.as_object())
                                                {
                                                    for (fk, fv) in oe {
                                                        be.insert(fk.clone(), fv.clone());
                                                    }
                                                }
                                            } else {
                                                bm.push(om.clone());
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        _ => {
                            base_obj.insert(k.clone(), v.clone());
                        }
                    }
                }
            }
        }
    }
    base
}

fn get_current_settings(custom_dir: &str) -> QgisSettings {
    let path = get_settings_path(custom_dir);
    if let Ok(data) = fs::read_to_string(&path) {
        // 読み込み時に常にバックスラッシュを事前修正してからパースする。
        // Accept either string or array for `project_path` for backward compatibility.
        let fixed = fix_backslashes_in_json(&data);
        match serde_json::from_str::<serde_json::Value>(&fixed) {
            Ok(mut v) => {
                // 無条件オーバーライドファイルをマージする（ベースの直後に適用）
                v = apply_force_override(custom_dir, v);
                // ユーザーオーバーライドファイルをマージする（最終適用）
                v = apply_user_override(custom_dir, v);
                if let Some(p) = v.get("project_path") {
                    if p.is_string() {
                        let s = p.as_str().unwrap_or("");
                        v["project_path"] = serde_json::Value::Array(vec![serde_json::Value::String(s.to_string())]);
                    }
                }
                // kasugai_qgis_version を数値でも受け付ける（文字列に正規化）
                if let Some(ver) = v.get("kasugai_qgis_version") {
                    if ver.is_number() {
                        let s = ver.to_string();
                        v["kasugai_qgis_version"] = serde_json::Value::String(s);
                    }
                }
                if let Ok(s) = serde_json::from_value::<QgisSettings>(v) {
                    return s;
                }
            }
            Err(e) => {
                eprintln!("qgis_settings.json parse error ({}): {}", path.display(), e);
            }
        }
        QgisSettings::default()
    } else {
        QgisSettings::default()
    }
}

fn save_settings(custom_dir: &str, s: &QgisSettings) -> Result<(), String> {
    let p = get_settings_path(custom_dir);
    if let Some(parent) = p.parent() {
        if !parent.exists() {
            fs::create_dir_all(parent).map_err(|e| format!("dir create error: {}", e))?;
        }
    }
    // Serialize the struct to a JSON Value so we can merge with any existing
    // settings file and preserve unknown or legacy keys (e.g. project_root).
    let new_val = serde_json::to_value(s).map_err(|e| e.to_string())?;

    // If an existing file exists and is valid JSON, merge: keys from `new_val`
    // overwrite existing ones, but keys present only in the existing file are
    // preserved. This prevents accidental removal of fields not present in
    // the current struct definition.
    let merged_val = if p.exists() {
        match fs::read_to_string(&p) {
            Ok(existing_text) => {
                let fixed = fix_backslashes_in_json(&existing_text);
                if let Ok(mut existing_val) = serde_json::from_str::<serde_json::Value>(&fixed) {
                    if let (Some(ex_obj), Some(new_obj)) = (existing_val.as_object_mut(), new_val.as_object()) {
                        for (k, v) in new_obj {
                            ex_obj.insert(k.clone(), v.clone());
                        }
                        serde_json::Value::Object(ex_obj.clone())
                    } else {
                        new_val
                    }
                } else {
                    new_val
                }
            }
            Err(_) => new_val,
        }
    } else {
        new_val
    };

    let data = serde_json::to_string_pretty(&merged_val).map_err(|e| e.to_string())?;
    fs::write(&p, data).map_err(|e| e.to_string())
}

/// `qgislocalsync.config`（KASUGAI/yr-qgis-launcher 形式、key=value）を読み込み、
/// `LocalSyncConfig` として返す。ファイルが無ければ None。
fn read_qgislocalsync_config(settings_dir: &str) -> Option<LocalSyncConfig> {
    let p = PathBuf::from(settings_dir).join("qgislocalsync.config");
    if !p.exists() {
        return None;
    }
    let text = fs::read_to_string(&p).ok()?;
    let mut cfg = LocalSyncConfig::default();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') || line.starts_with(';') {
            continue;
        }
        if let Some((key, val)) = line.split_once('=') {
            let key = key.trim();
            let val = val.trim();
            match key {
                "SYNC_SRC" => cfg.sync_src = Some(val.to_string()),
                "SYNC_DST" => cfg.sync_dst = Some(val.to_string()),
                "QFIELD_VERSION" => cfg.qfield_version = Some(val.to_string()),
                "QGIS_VERSION" => cfg.qgis_version = Some(val.to_string()),
                "EXCLUDE_DIRS" => {
                    cfg.exclude_dirs = val
                        .split_whitespace()
                        .map(|s| s.to_string())
                        .filter(|s| !s.is_empty())
                        .collect();
                }
                "PORTABLE_PROFILE_VERSION" => cfg.portable_profile_version = Some(val.to_string()),
                _ => {}
            }
        }
    }
    Some(cfg)
}

/// JSON 設定と `qgislocalsync.config` を統合する。
/// まず settings_dir 内の qgislocalsync.config、または JSON の local_sync をベースとし、
/// その SYNC_SRC 先にある qgislocalsync.config からバージョン情報を上書き取得する。
/// これにより、サーバー側（SYNC_SRC）で qgislocalsync.config のバージョンを更新すると
/// クライアント側でも Update 有効化を検知できる。
fn resolve_local_sync_config(settings: &QgisSettings, settings_dir: &str) -> Option<LocalSyncConfig> {
    let json_cfg = settings.local_sync.as_ref()?.clone();
    let mut file = read_qgislocalsync_config(settings_dir).unwrap_or_else(|| json_cfg.clone());
    // ローカルファイルが無い項目は JSON の local_sync をフォールバック
    if file.sync_src.is_none() { file.sync_src = json_cfg.sync_src.clone(); }
    if file.sync_dst.is_none() { file.sync_dst = json_cfg.sync_dst.clone(); }
    if file.qfield_version.is_none() { file.qfield_version = json_cfg.qfield_version.clone(); }
    if file.qgis_version.is_none() { file.qgis_version = json_cfg.qgis_version.clone(); }
    if file.exclude_dirs.is_empty() { file.exclude_dirs = json_cfg.exclude_dirs.clone(); }
    if file.portable_profile_version.is_none() { file.portable_profile_version = json_cfg.portable_profile_version.clone(); }

    // サーバー側（SYNC_SRC）の qgislocalsync.config からバージョン情報を上書き
    if let Some(src) = file.sync_src.as_ref() {
        let src_path = expand_env_vars(&resolve_path(src, &settings.path_aliases));
        if let Some(server_cfg) = read_qgislocalsync_config(&src_path) {
            if server_cfg.qfield_version.is_some() { file.qfield_version = server_cfg.qfield_version; }
            if server_cfg.qgis_version.is_some() { file.qgis_version = server_cfg.qgis_version; }
            if server_cfg.portable_profile_version.is_some() { file.portable_profile_version = server_cfg.portable_profile_version; }
            if !server_cfg.exclude_dirs.is_empty() { file.exclude_dirs = server_cfg.exclude_dirs; }
            // SYNC_SRC 内の qgislocalsync.config には SYNC_DST は通常指定しないが、
            // 指定されていてもローカル側の設定を優先する。
            if file.sync_dst.is_none() { file.sync_dst = server_cfg.sync_dst; }
        }
    }
    Some(file)
}

/// JSON 値から文字列としてバージョン値を取り出す（文字列・数値両対応）。
fn version_value_as_string(value: &serde_json::Value) -> Option<String> {
    if let Some(s) = value.as_str() {
        return Some(s.to_string());
    }
    if value.is_number() {
        return Some(value.to_string());
    }
    None
}

/// KASUGA-QGIS ランチャー本体の配布元バージョンを取得する。
/// まず SYNC_SRC 側の qgis_settings.json を読み、kasugai_qgis_version を優先する。
/// SYNC_SRC 側のファイルが無いか値が無ければ、ローカルの qgis_settings.json の値を返す。
fn resolve_kasugai_qgis_version(settings: &QgisSettings, settings_dir: &str) -> Option<String> {
    // まずは local_sync / qgislocalsync.config から SYNC_SRC を解決
    let sync_src = resolve_local_sync_config(settings, settings_dir)
        .and_then(|c| c.sync_src)?;
    let src_path = expand_env_vars(&resolve_path(&sync_src, &settings.path_aliases));
    let server_settings_path = PathBuf::from(&src_path).join("qgis_settings.json");
    if server_settings_path.exists() {
        if let Ok(text) = fs::read_to_string(&server_settings_path) {
            let fixed = fix_backslashes_in_json(&text);
            match serde_json::from_str::<serde_json::Value>(&fixed) {
                Ok(value) => {
                    if let Some(ver) = value.get("kasugai_qgis_version").and_then(version_value_as_string) {
                        return Some(ver);
                    }
                }
                Err(e) => {
                    eprintln!("SYNC_SRC qgis_settings.json parse error ({}): {}", server_settings_path.display(), e);
                }
            }
        }
    }
    settings.kasugai_qgis_version.clone()
}

/// 同期先のバージョンファイルを読み込む。ファイルが無ければ空文字列を返す。
fn read_version_file(dir: &str, filename: &str) -> String {
    let p = PathBuf::from(dir).join(filename);
    fs::read_to_string(&p).unwrap_or_default().trim().to_string()
}

/// 同期先のバージョンファイルに書き込む。
fn write_version_file(dir: &str, filename: &str, value: &str) {
    let p = PathBuf::from(dir).join(filename);
    if let Err(e) = fs::write(&p, value) {
        eprintln!("local_sync: バージョンファイル書き込み失敗 ({}): {}", p.display(), e);
    }
}

/// `src` 直下のフォルダ名で prefix に一致するものを列挙する（大文字小文字区別なし）。
fn find_prefixed_folders(src: &str, prefix: &str) -> Vec<String> {
    let mut result = Vec::new();
    if let Ok(entries) = fs::read_dir(src) {
        for entry in entries.flatten() {
            if let Ok(ft) = entry.file_type() {
                if ft.is_dir() {
                    let name = entry.file_name().to_string_lossy().to_string();
                    if name.to_lowercase().starts_with(&prefix.to_lowercase()) {
                        result.push(name);
                    }
                }
            }
        }
    }
    result
}

/// KASUGAI/yr-qgis-launcher 方式のローカル同期が必要かどうかを判定する。
/// qgislocalsync.config / JSON local_sync の設定に基づき、SYNC_SRC の存在、
/// QField*/QGIS*/portable_profile のバージョン差分、SYNC_DST の未作成を判定する。
fn local_sync_needed(settings: &QgisSettings, settings_dir: &str) -> bool {
    let Some(config) = resolve_local_sync_config(settings, settings_dir) else { return false; };
    let Some(src) = config.sync_src.as_ref() else { return false; };
    let Some(dst) = config.sync_dst.as_ref() else { return false; };

    let src = expand_env_vars(&resolve_path(src, &settings.path_aliases));
    let dst = expand_env_vars(&resolve_path(dst, &settings.path_aliases));

    if !PathBuf::from(&src).exists() {
        return false;
    }
    if !PathBuf::from(&dst).exists() {
        return true;
    }

    let qfield_folders = find_prefixed_folders(&src, "QField");
    if let Some(qfield_ver) = config.qfield_version.as_ref() {
        let local_ver = read_version_file(&dst, "LOCAL_QFIELD_VERSION");
        if local_ver != *qfield_ver && !qfield_folders.is_empty() {
            return true;
        }
    }

    let qgis_folders = find_prefixed_folders(&src, "QGIS");
    if let Some(qgis_ver) = config.qgis_version.as_ref() {
        let local_ver = read_version_file(&dst, "LOCAL_QGIS_VERSION");
        if local_ver != *qgis_ver && !qgis_folders.is_empty() {
            return true;
        }
    }

    if let Some(pp_ver) = config.portable_profile_version.as_ref() {
        let local_ver = read_version_file(&dst, "portable.ver");
        let folder = "portable_profile";
        let s = PathBuf::from(&src).join(folder).to_string_lossy().to_string();
        if local_ver != *pp_ver && PathBuf::from(&s).exists() {
            return true;
        }
    }

    // KASUGA-QGIS ランチャー本体のバージョン判定
    if let Some(ver) = resolve_kasugai_qgis_version(settings, settings_dir) {
        let local_ver = read_version_file(&dst, "LOCAL_KASUGAI_QGIS_VERSION");
        if local_ver != ver {
            return true;
        }
    }

    // トップレベル同期が必要かは robocopy で判定するため、
    // ここではバージョン管理対象フォルダの差分と SYNC_DST の未作成のみで判定する。
    false
}

/// KASUGAI/yr-qgis-launcher 方式のローカル自動同期を実行する。
/// SYNC_SRC → SYNC_DST へ、QField*/QGIS* フォルダはバージョン文字列比較で差分がある場合のみ同期する。
/// 戻り値: 同期を実行した場合は true、アップデートが不要でスキップした場合は false。
fn run_local_sync(settings: &QgisSettings, settings_dir: &str, sender: Option<&std::sync::mpsc::Sender<String>>) -> bool {
    if !local_sync_needed(settings, settings_dir) {
        let msg = "local_sync: アップデートは不要です。";
        if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
        println!("{}", msg);
        return false;
    }

    let config = resolve_local_sync_config(settings, settings_dir).unwrap();
    let src = config.sync_src.as_ref().unwrap();
    let dst = config.sync_dst.as_ref().unwrap();

    let src = expand_env_vars(&resolve_path(src, &settings.path_aliases));
    let dst = expand_env_vars(&resolve_path(dst, &settings.path_aliases));

    let msg = format!("local_sync: {} → {}", src, dst);
    if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
    println!("{}", msg);

    if !PathBuf::from(&src).exists() {
        let msg = format!("local_sync: SYNC_SRC '{}' が見つかりません。スキップします。", src);
        if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
        eprintln!("{}", msg);
        return false;
    }
    if let Err(e) = fs::create_dir_all(&dst) {
        let msg = format!("local_sync: SYNC_DST 作成失敗 ({}): {}", dst, e);
        if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
        eprintln!("{}", msg);
        return false;
    }

    // QField*/QGIS* フォルダを予め列挙して /XD 用の固定名リストを作る
    let qfield_folders = find_prefixed_folders(&src, "QField");
    let qgis_folders = find_prefixed_folders(&src, "QGIS");

    // トップレベル同期: ファイルとサブフォルダを含むが QField*/QGIS*/EXCLUDE_DIRS は除外
    let mut top_excludes: Vec<String> = config.exclude_dirs.clone();
    for f in &qfield_folders { if !top_excludes.contains(f) { top_excludes.push(f.clone()); } }
    for f in &qgis_folders { if !top_excludes.contains(f) { top_excludes.push(f.clone()); } }
    run_robocopy_local(&src, &dst, &top_excludes, sender, "トップレベル");

    // QField* フォルダのバージョン判定同期
    if let Some(qfield_ver) = config.qfield_version.as_ref() {
        let local_ver = read_version_file(&dst, "LOCAL_QFIELD_VERSION");
        if local_ver != *qfield_ver && !qfield_folders.is_empty() {
            let msg = format!("local_sync: QField 更新 ({} → {})", local_ver, qfield_ver);
            if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
            println!("{}", msg);
            for folder in &qfield_folders {
                let s = PathBuf::from(&src).join(folder).to_string_lossy().to_string();
                let d = PathBuf::from(&dst).join(folder).to_string_lossy().to_string();
                if PathBuf::from(&s).exists() {
                    run_robocopy_local(&s, &d, &config.exclude_dirs, sender, &format!("QField {}", folder));
                }
            }
            write_version_file(&dst, "LOCAL_QFIELD_VERSION", qfield_ver);
        }
    }

    // QGIS* フォルダのバージョン判定同期
    if let Some(qgis_ver) = config.qgis_version.as_ref() {
        let local_ver = read_version_file(&dst, "LOCAL_QGIS_VERSION");
        if local_ver != *qgis_ver && !qgis_folders.is_empty() {
            let msg = format!("local_sync: QGIS 更新 ({} → {})", local_ver, qgis_ver);
            if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
            println!("{}", msg);
            for folder in &qgis_folders {
                let s = PathBuf::from(&src).join(folder).to_string_lossy().to_string();
                let d = PathBuf::from(&dst).join(folder).to_string_lossy().to_string();
                if PathBuf::from(&s).exists() {
                    run_robocopy_local(&s, &d, &config.exclude_dirs, sender, &format!("QGIS {}", folder));
                }
            }
            write_version_file(&dst, "LOCAL_QGIS_VERSION", qgis_ver);
        }
    }

    // ポータブルプロファイルのバージョン判定同期
    if let Some(pp_ver) = config.portable_profile_version.as_ref() {
        let local_ver = read_version_file(&dst, "portable.ver");
        let folder = "portable_profile";
        let s = PathBuf::from(&src).join(folder).to_string_lossy().to_string();
        if local_ver != *pp_ver && PathBuf::from(&s).exists() {
            let msg = format!("local_sync: portable_profile 更新 ({} → {})", local_ver, pp_ver);
            if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
            println!("{}", msg);
            let d = PathBuf::from(&dst).join(folder).to_string_lossy().to_string();
            run_robocopy_local(&s, &d, &config.exclude_dirs, sender, "portable_profile");
            write_version_file(&dst, "portable.ver", pp_ver);
        }
    }

    // KASUGA-QGIS ランチャー本体のバージョンを記録
    if let Some(ver) = resolve_kasugai_qgis_version(settings, settings_dir) {
        write_version_file(&dst, "LOCAL_KASUGAI_QGIS_VERSION", &ver);
    }

    let msg = "local_sync: 完了".to_string();
    if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
    println!("{}", msg);
    true
}

/// robocopy を用いた 1 フォルダ同期。/E でサブディレクトリ含む、/MIR でミラー。
fn run_robocopy_local(src: &str, dst: &str, exclude: &[String], sender: Option<&std::sync::mpsc::Sender<String>>, label: &str) {
    if !PathBuf::from(src).exists() {
        let msg = format!("local_sync: {}: コピー元 '{}' が見つかりません。", label, src);
        if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
        eprintln!("{}", msg);
        return;
    }
    if let Err(e) = fs::create_dir_all(dst) {
        let msg = format!("local_sync: {}: コピー先作成失敗 ({}): {}", label, dst, e);
        if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
        eprintln!("{}", msg);
        return;
    }
    let msg = format!("local_sync: {}: {} → {}", label, src, dst);
    if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
    println!("{}", msg);

    let mut cmd = Command::new("robocopy");
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd.args([src, dst, "/MIR", "/MT:8", "/R:1", "/W:0", "/NP"]);
    if !exclude.is_empty() {
        cmd.arg("/XD");
        for dir in exclude {
            cmd.arg(dir);
        }
    }
    match cmd.status() {
        Ok(s) => {
            let code = s.code().unwrap_or(-1);
            if code < 8 {
                println!("local_sync: {}: 完了 (exit {})", label, code);
            } else {
                let msg = format!("local_sync: {}: robocopy エラー終了 (exit {})", label, code);
                if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
                eprintln!("{}", msg);
            }
        }
        Err(e) => {
            let msg = format!("local_sync: {}: robocopy 起動エラー: {}", label, e);
            if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
            eprintln!("{}", msg);
        }
    }
}






/// NSIS インストーラー方式の更新情報。
/// url は通常更新用（EXE のみの kasugai_qgis-update.exe）、
/// full_url は全体更新用（データ込みの kasugai_qgis-setup.exe）を指す。
/// full が true の場合は full_url を使って全体更新を行う。
#[derive(Debug, Clone)]
#[allow(dead_code)]
struct NsisUpdateInfo {
    version: String,
    url: String,
    full_url: Option<String>,
    full: bool,
    signature: Option<String>,
    /// 通常更新用 EXE の SHA-256（16進、大文字小文字は問わない）
    sha256: Option<String>,
    /// 全体更新用 EXE の SHA-256
    full_sha256: Option<String>,
    notes: Option<String>,
}

/// バージョン文字列 a が b より新しければ true を返す。
/// 数値として比較し、不足セグメントは 0 扱いとする。
fn version_is_newer(a: &str, b: &str) -> bool {
    let a_parts = parse_version_parts(a);
    let b_parts = parse_version_parts(b);
    for i in 0..3 {
        let an = a_parts.get(i).and_then(|s| s.parse::<u64>().ok()).unwrap_or(0);
        let bn = b_parts.get(i).and_then(|s| s.parse::<u64>().ok()).unwrap_or(0);
        if an != bn {
            return an > bn;
        }
    }
    false
}

/// 同一バージョンへの更新を試行できる最大回数。
/// これを超えた場合は「更新しても実行中バージョンが変わらない」状態と判断し、
/// 無限ループを避けるため更新を中断する。
const MAX_UPDATE_ATTEMPTS: u32 = 1;
/// 試行回数を使い切ったあと、再試行を許可するまでの待機秒数（24 時間）。
const UPDATE_RETRY_COOLDOWN_SECS: u64 = 24 * 60 * 60;

/// 更新試行の記録。無限ループ防止の要。
/// 更新を適用すると新しい EXE が自動起動するため、記録なしでは
/// 「更新 → 再起動 → また更新」が延々と繰り返される危険がある。
#[derive(Serialize, Deserialize, Debug, Clone, Default)]
struct UpdateState {
    /// 直近に更新を試行した対象バージョン
    #[serde(default)]
    last_attempt_version: Option<String>,
    /// 直近の試行時刻（UNIX 秒）
    #[serde(default)]
    last_attempt_epoch: Option<u64>,
    /// 同一バージョンへの連続試行回数
    #[serde(default)]
    attempt_count: u32,
    /// 試行を開始した時点で実行していたバージョン
    #[serde(default)]
    attempt_from_version: Option<String>,
}

fn now_epoch_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// 更新試行記録の保存先。
/// インストーラーに削除・上書きされないよう、インストール先ではなく
/// %LOCALAPPDATA%\kasugai_qgis\update_state.json に置く。
fn update_state_path() -> Option<PathBuf> {
    let base = env::var("LOCALAPPDATA").ok().filter(|s| !s.trim().is_empty())?;
    Some(PathBuf::from(base).join("kasugai_qgis").join("update_state.json"))
}

fn load_update_state() -> UpdateState {
    update_state_path()
        .and_then(|p| fs::read_to_string(p).ok())
        .and_then(|s| serde_json::from_str::<UpdateState>(&s).ok())
        .unwrap_or_default()
}

fn save_update_state(state: &UpdateState) {
    let Some(path) = update_state_path() else { return };
    if let Some(parent) = path.parent() {
        if let Err(e) = fs::create_dir_all(parent) {
            eprintln!("更新状態フォルダ作成失敗: {}", e);
            return;
        }
    }
    match serde_json::to_string_pretty(state) {
        Ok(s) => {
            if let Err(e) = fs::write(&path, s) {
                eprintln!("更新状態保存失敗 ({}): {}", path.display(), e);
            }
        }
        Err(e) => eprintln!("更新状態シリアライズ失敗: {}", e),
    }
}

/// 記録済みの更新試行が完了しているかを判定する。
/// 実行中バージョンが対象バージョンに到達していれば更新成功とみなし、記録を消す。
fn reconcile_update_state() -> UpdateState {
    let state = load_update_state();
    let current = env!("CARGO_PKG_VERSION");
    if let Some(ref target) = state.last_attempt_version {
        if !version_is_newer(target, current) {
            println!("更新完了を確認しました (current={}, target={})", current, target);
            let cleared = UpdateState::default();
            save_update_state(&cleared);
            return cleared;
        }
    }
    state
}

/// 対象バージョンへの更新を試行してよいかを判定する。
/// 試行不可の場合は理由メッセージを Err で返す。
fn check_update_attempt_allowed(version: &str) -> Result<(), String> {
    let state = reconcile_update_state();
    if state.last_attempt_version.as_deref() != Some(version) {
        return Ok(());
    }
    if state.attempt_count < MAX_UPDATE_ATTEMPTS {
        return Ok(());
    }
    let elapsed = now_epoch_secs().saturating_sub(state.last_attempt_epoch.unwrap_or(0));
    if elapsed >= UPDATE_RETRY_COOLDOWN_SECS {
        return Ok(());
    }
    Err(format!(
        "バージョン {} への更新は既に {} 回試行済みですが、実行中のバージョンは {} のままです。\
         更新ループを避けるため中断しました。配布されている更新用インストーラーが古い可能性があります。\
         （{} 秒後に再試行可能。強制実行も可能です）",
        version,
        state.attempt_count,
        env!("CARGO_PKG_VERSION"),
        UPDATE_RETRY_COOLDOWN_SECS.saturating_sub(elapsed)
    ))
}

/// 更新試行を記録する。同一バージョンなら回数を加算し、別バージョンなら 1 から数え直す。
fn record_update_attempt(version: &str) {
    let mut state = load_update_state();
    let same = state.last_attempt_version.as_deref() == Some(version);
    state.attempt_count = if same { state.attempt_count.saturating_add(1) } else { 1 };
    state.last_attempt_version = Some(version.to_string());
    state.last_attempt_epoch = Some(now_epoch_secs());
    state.attempt_from_version = Some(env!("CARGO_PKG_VERSION").to_string());
    save_update_state(&state);
}

/// 更新チェック・ダウンロード用の HTTP クライアントを生成する（タイムアウト付き）。
fn update_http_client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .connect_timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| format!("HTTP クライアント作成失敗: {}", e))
}

/// NSIS 更新 JSON エンドポイントを確認し、新しい版があれば情報を返す。
fn check_nsis_update(settings: &QgisSettings) -> Result<Option<NsisUpdateInfo>, String> {
    let update_url = match settings.update_url.as_ref() {
        Some(u) if !u.trim().is_empty() => u.trim(),
        _ => return Ok(None),
    };

    if !settings.update_check.unwrap_or(true) {
        return Ok(None);
    }

    let current = env!("CARGO_PKG_VERSION");

    let client = update_http_client()?;
    let resp = client.get(update_url)
        .send()
        .map_err(|e| format!("update.json 取得失敗: {}", e))?
        .json::<serde_json::Value>()
        .map_err(|e| format!("update.json パース失敗: {}", e))?;

    let version = resp.get("version")
        .and_then(|v| v.as_str())
        .ok_or("update.json に version がありません")?;
    let url = resp.get("url")
        .and_then(|v| v.as_str())
        .ok_or("update.json に url がありません")?;
    let full_url = resp.get("full_url").and_then(|v| v.as_str()).map(|s| s.to_string());
    let full = resp.get("full").and_then(|v| v.as_bool()).unwrap_or(false);

    if !version_is_newer(version, current) {
        println!("NSIS更新: 最新版です (current={}, latest={})", current, version);
        return Ok(None);
    }

    Ok(Some(NsisUpdateInfo {
        version: version.to_string(),
        url: url.to_string(),
        full_url,
        full,
        signature: resp.get("signature").and_then(|v| v.as_str()).map(|s| s.to_string()),
        sha256: resp.get("sha256").and_then(|v| v.as_str()).map(|s| s.to_string()),
        full_sha256: resp.get("full_sha256").and_then(|v| v.as_str()).map(|s| s.to_string()),
        notes: resp.get("notes").and_then(|v| v.as_str()).map(|s| s.to_string()),
    }))
}




/// ファイルを一時フォルダにダウンロードする。
fn download_installer(url: &str, dest: &std::path::Path) -> Result<(), String> {
    let client = update_http_client()?;
    let bytes = client.get(url)
        .send()
        .map_err(|e| format!("インストーラー取得失敗 ({}): {}", url, e))?
        .bytes()
        .map_err(|e| format!("インストーラー読み込み失敗: {}", e))?;
    std::fs::write(dest, bytes)
        .map_err(|e| format!("インストーラー書き込み失敗 ({}): {}", dest.display(), e))?;
    Ok(())
}


/// インストール先フォルダ（現在の実行ファイルの親フォルダ）を返す。
fn current_install_dir() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(std::env::temp_dir)
}

/// NSIS インストーラーを起動し、本体を終了する。
fn run_nsis_installer_and_exit(installer: &std::path::Path, install_dir: &str) {
    let install_dir_trimmed = install_dir.trim_end_matches('\\');
    let mut cmd = Command::new(installer);
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd.arg("/S");
    // NSIS /D は最後の引数で、パスに空白があってもクォートを含めてはいけない
    cmd.raw_arg(format!("/D={}", install_dir_trimmed));
    cmd.stdin(Stdio::null());
    cmd.stdout(Stdio::null());
    cmd.stderr(Stdio::null());

    match cmd.spawn() {
        Ok(_) => {
            println!("NSIS更新: インストーラーを起動しました。終了します。");
            std::process::exit(0);
        }
        Err(e) => {
            eprintln!("NSIS更新: インストーラー起動失敗: {}", e);
        }
    }
}

/// 更新の適用準備（ガード確認・ダウンロード・SHA-256 検証）を行う。
/// 成功時は (インストーラーのパス, 対象バージョン, 更新種別) を返す。
/// 実際のインストーラー起動・プロセス終了は呼び出し側が行う。
///
/// 起動時に自動実行してはならない。更新後は新しい EXE が自動起動するため、
/// 自動実行すると「更新 → 再起動 → 更新」のループになる。適用はユーザー操作起点のみ。
fn prepare_nsis_update(settings: &QgisSettings, force: bool) -> Result<(PathBuf, String, &'static str), String> {
    let info = check_nsis_update(settings)?.ok_or_else(|| "更新はありません".to_string())?;
    let current = env!("CARGO_PKG_VERSION");

    // 無限ループガード: 同一バージョンへの更新を繰り返していないか確認する
    if force {
        println!("NSIS更新: force 指定のためループガードを無視します");
    } else {
        check_update_attempt_allowed(&info.version)?;
    }

    // full が true かつ full_url がある場合は全体更新（データ込み）、
    // それ以外は通常更新（EXE のみ）を行う。
    let (download_url, expected_sha256, kind) = match (info.full, info.full_url.as_ref()) {
        (true, Some(full_url)) => (full_url.as_str(), info.full_sha256.as_ref(), "全体更新"),
        (true, None) => {
            eprintln!("NSIS更新: full=true ですが full_url がありません。通常更新を行います。");
            (info.url.as_str(), info.sha256.as_ref(), "通常更新")
        }
        _ => (info.url.as_str(), info.sha256.as_ref(), "通常更新"),
    };
    println!("NSIS更新({}): {} → {}", kind, current, info.version);

    let temp = std::env::temp_dir().join("kasugai_qgis_setup.exe");
    download_installer(download_url, &temp)?;

    // 壊れたダウンロードをインストールすると更新が反映されずループの原因になるため検証する
    if let Some(expected) = expected_sha256.map(|s| s.trim()).filter(|s| !s.is_empty()) {
        verify_sha256(&temp, expected)?;
        println!("NSIS更新: SHA-256 検証 OK");
    } else {
        eprintln!("NSIS更新: update.json に sha256 がないため検証を省略します");
    }

    // ここまで来たら実際に適用するので試行を記録する（ループガードの根拠）
    record_update_attempt(&info.version);

    Ok((temp, info.version, kind))
}

/// ダウンロードしたファイルの SHA-256 を検証する。
fn verify_sha256(path: &std::path::Path, expected: &str) -> Result<(), String> {
    use sha2::{Digest, Sha256};
    let bytes = fs::read(path).map_err(|e| format!("検証用の読み込み失敗 ({}): {}", path.display(), e))?;
    let actual = format!("{:x}", Sha256::digest(&bytes));
    if actual.eq_ignore_ascii_case(expected) {
        Ok(())
    } else {
        Err(format!("SHA-256 が一致しません (expected={}, actual={})", expected, actual))
    }
}

fn main() {
    let args = Args::parse();

    // デバッグ: 検出される QGIS 一覧を出力して終了
    if args.list_qgis {
        if let Some(reg) = find_qgis_path_from_registry() {
            println!("Registry default path: {}", reg);
        } else {
            println!("Registry default path: <none>");
        }
        let avail = get_available_qgis_versions();
        println!("Detected QGIS installations (count={}):", avail.len());
        for (n, p) in avail {
            println!("- {} => {}", n, p);
        }
        return;
    }

    // 実行ファイルのフォルダをカレントディレクトリに設定する
    if let Ok(exe_path) = env::current_exe() {
        if let Some(parent) = exe_path.parent() {
            if let Err(e) = env::set_current_dir(parent) {
                eprintln!("カレントディレクトリ設定失敗: {}", e);
            }
        }
    }

    let settings_dir = get_default_settings_dir();
    let mut settings = get_current_settings(&settings_dir);

    // get_settings_path と同じフォールバックロジックで実際の settings_dir を解決する
    let mut resolved_settings_dir = {
        let p = get_settings_path(&settings_dir);
        p.parent().map(|d| d.to_string_lossy().to_string()).unwrap_or_else(|| settings_dir.clone())
    };

    // 設定内の project_root があればそれを解決して使用
    let mut project_root_dir = compute_project_root(&settings, &resolved_settings_dir);

    // project_root 内にも qgis_settings.json がある場合はそちらを優先して読み込む
    let project_settings_json = PathBuf::from(&project_root_dir).join("qgis_settings.json");
    if project_root_dir.to_lowercase() != resolved_settings_dir.to_lowercase()
        && project_settings_json.exists()
    {
        settings = get_current_settings(&project_root_dir);
        resolved_settings_dir = project_root_dir.clone();
        project_root_dir = compute_project_root(&settings, &resolved_settings_dir);
    }

    // 更新は起動時に自動適用しない（適用直後の再起動で再び更新が走り、無限ループになるため）。
    // 起動時は直近の更新試行が成功したかを照合するだけに留め、
    // 実際の適用は UI からのユーザー操作（POST /update/apply）でのみ行う。
    let update_check_enabled = !args.no_update_check
        && settings.update_check.unwrap_or(true)
        && settings.update_url.as_deref().map(|u| !u.trim().is_empty()).unwrap_or(false);
    if args.no_update_check {
        println!("更新チェック: --no-update-check が指定されたため無効です");
    }
    reconcile_update_state();

    let profile_to_use = if !settings.profile.trim().is_empty() {
        settings.profile.clone()
    } else if !args.profile.trim().is_empty() {
        args.profile.clone()
    } else {
        "default".to_string()
    };

    if !args.cli || args.open_browser || args.server {
        let server_port = args.port.unwrap_or(settings.api_server_port.unwrap_or(8500));
        mount_drive_mappings(&settings.drive_mappings, &settings, None);
        copy_profiles_at_startup(&project_root_dir, None);
        run_local_sync(&settings, &project_root_dir, None);
        run_api_server_sync(server_port, &resolved_settings_dir, &project_root_dir, args.open_browser, update_check_enabled);
        return;
    }


    // KASUGAI/yr-qgis-launcher 方式のローカル自動同期（CLI モード）
    run_local_sync(&settings, &project_root_dir, None);

    // CLI 起動
    let mut qgis_exe = if let Some(exe) = &args.qgis_executable {
        exe.clone()
    } else if let Some(exe) = &settings.qgis_executable {
        // 設定に残っているパスが実際に存在するか確認する
        if PathBuf::from(exe).exists() {
            exe.clone()
        } else {
            "".to_string()
        }
    } else {
        "".to_string()
    };

    // CLI/非GUI 時: qgis_exe が指定されていない場合、プロジェクトのバージョンに合う
    // インストール済み QGIS を自動選択する。選択はあくまでフォールバックで、明示指定が優先。
    // プロジェクト候補: current_project を優先し、なければ project_path[0]
    if args.qgis_executable.is_none() {
        let proj_candidate = settings.current_project.as_deref()
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string())
            .or_else(|| settings.project_path.first().cloned());
        if let Some(proj) = proj_candidate {
            let effective = if PathBuf::from(&proj).is_absolute() {
                proj.clone()
            } else {
                PathBuf::from(&settings_dir).join(&proj).to_string_lossy().to_string()
            };
            if let Some(ver) = get_project_file_version(&effective) {
                let proj_major = ver.split('.').next().unwrap_or("").to_lowercase();
                let avail = get_available_qgis_versions();
                if let Some((_name, path)) = find_matching_available_for_project(&ver, &avail) {
                    if qgis_exe.is_empty() {
                        qgis_exe = path;
                    } else {
                        // 既に設定値がある場合、設定されている実行ファイルパスのメジャーを抽出して
                        // プロジェクトのメジャーと比較し、異なれば上書きする
                        let ql = qgis_exe.to_lowercase();
                        let ql_major = extract_major(&ql).unwrap_or_default();
                        if ql_major != proj_major {
                            qgis_exe = path;
                        }
                    }
                }
            }
        }
    }

    let userrole = settings.userrole.as_deref().unwrap_or("Viewer").to_string();
    println!("起動: プロファイル '{}' でQGISを起動します...", profile_to_use);
    launch_qgis(&profile_to_use, &settings.project_path, &project_root_dir, &qgis_exe, &userrole);
}

/// コマンド文字列から最初のトークン（実行ファイルパス）を取り出す。
/// クォートに対応し、空白を含むパスも正しく解析する。
fn extract_first_command_token(s: &str) -> Option<&str> {
    let s = s.trim();
    if s.is_empty() {
        return None;
    }
    if s.starts_with('"') {
        // クォートされたパス: 閉じクォートまで
        for (i, c) in s[1..].char_indices() {
            if c == '"' {
                return Some(&s[1..1 + i]);
            }
        }
        // 閉じクォートがない場合は末尾まで
        Some(&s[1..])
    } else {
        // 非クォート: 最初の空白まで
        s.split_whitespace().next()
    }
}

fn find_qgis_path_from_registry() -> Option<String> {
    println!("レジストリからQGISのパスを検索中...");
    let hkcr = RegKey::predef(HKEY_CLASSES_ROOT);

    let prog_id = match hkcr.open_subkey(r".qgs") {
        Ok(key) => match key.get_value::<String, _>("") {
            Ok(val) => val,
            Err(e) => {
                eprintln!(".qgs の ProgID 取得に失敗: {}", e);
                return None;
            }
        },
        Err(e) => {
            eprintln!(".qgs キーが見つかりません: {}", e);
            return None;
        }
    };

    let cmd_path = format!(r"{}\\shell\\open\\command", prog_id);
    let command_string = match hkcr.open_subkey(&cmd_path) {
        Ok(key) => match key.get_value::<String, _>("") {
            Ok(val) => val,
            Err(e) => {
                eprintln!("{} の既定値取得に失敗: {}", cmd_path, e);
                return None;
            }
        },
        Err(e) => {
            eprintln!("{} キーが見つかりません: {}", cmd_path, e);
            return None;
        }
    };

    let exe_path = extract_first_command_token(&command_string).unwrap_or(&command_string);

    let exe_str = exe_path.to_string();
    if exe_str.is_empty() {
        None
    } else {
        // レジストリに記録されているパスが実際に存在するか確認する。
        // 存在しない場合はシステム既定として扱わない。
        let pb = PathBuf::from(&exe_str);
        if pb.exists() {
            Some(exe_str)
        } else {
            eprintln!("レジストリで見つかったQGISパスが存在しません: {}", exe_str);
            None
        }
    }
}

/// rclone.exe のパスを解決する。
/// 検索順:
///   1. qgis_launcher.exe と同じフォルダ
///   2. システム PATH
fn find_rclone_exe() -> Option<String> {
    // 1. qgis_launcher.exe と同じフォルダ
    if let Ok(exe) = env::current_exe() {
        if let Some(parent) = exe.parent() {
            let candidate = parent.join("rclone.exe");
            if candidate.is_file() {
                println!("rclone: EXEフォルダから発見: {:?}", candidate);
                return Some(candidate.to_string_lossy().to_string());
            }
        }
    }

    // 2. システム PATH
    if Command::new("rclone").arg("version").output().is_ok() {
        println!("rclone: システムPATHから使用します。");
        return Some("rclone".to_string());
    }

    eprintln!("rclone: rclone.exe が見つかりません。");
    eprintln!("  → rclone.exe を qgis_launcher.exe と同じフォルダに置いてください。");
    eprintln!("  → ダウンロード: https://rclone.org/downloads/");
    None
}

/// パス文字列内の %VAR_NAME% を環境変数値に展開する（展開後の値にさらに %VAR% が含まれる場合も再展開）
fn expand_env_vars(s: &str) -> String {
    let mut result = s.to_string();
    for _ in 0..10 {
        let prev = result.clone();
        let mut output = String::new();
        let mut i = 0;
        while i < result.len() {
            if let Some(start) = result[i..].find('%') {
                let abs_start = i + start;
                output.push_str(&result[i..abs_start]);
                if let Some(end) = result[abs_start + 1..].find('%') {
                    let abs_end = abs_start + 1 + end;
                    let var_name = &result[abs_start + 1..abs_end];
                    let replacement = env::var(var_name)
                        .unwrap_or_else(|_| format!("%{}%", var_name));
                    output.push_str(&replacement);
                    i = abs_end + 1;
                } else {
                    output.push_str(&result[abs_start..]);
                    i = result.len();
                }
            } else {
                output.push_str(&result[i..]);
                break;
            }
        }
        result = output;
        if result == prev {
            break;
        }
    }
    result
}

/// パスエイリアスを適用した後に環境変数展開を行う。
/// "BOX:\\path" など 2文字以上のエイリアス名:path 形式を変換する。
/// エイリアスは settings.path_aliases で定義。
/// "BOX" が未定義の場合のデフォルト: %USERPROFILE%\Box
fn resolve_path(s: &str, aliases: &HashMap<String, String>) -> String {
    // "ALIAS:\\..." または "ALIAS:/..." 形式を検出（2文字以上 = ドライブレターでない）
    let resolved = if let Some(colon_pos) = s.find(':') {
        let prefix = &s[..colon_pos];
        // 単一英字文字（標準ドライブレター）はエイリアスとして扱わない
        if prefix.len() >= 2 && prefix.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
            let alias_upper = prefix.to_uppercase();
            let alias_root = if let Some(v) = aliases.get(&alias_upper) {
                v.clone()
            } else if alias_upper == "BOX" {
                // BOX のデフォルト: %USERPROFILE%\Box
                let user_profile = env::var("USERPROFILE").unwrap_or_else(|_| "C:\\Users\\user".to_string());
                format!("{}\\Box", user_profile)
            } else {
                return expand_env_vars(s);
            };
            let rest = &s[colon_pos + 1..];
            let rest = rest.trim_start_matches(['\\', '/']);
            if rest.is_empty() {
                alias_root
            } else {
                format!("{}\\{}", alias_root.trim_end_matches(['\\', '/']), rest)
            }
        } else {
            s.to_string()
        }
    } else {
        s.to_string()
    };
    expand_env_vars(&resolved)
}

/// `drive_mappings` の設定に従ってマウント / 同期を起動する。
fn mount_drive_mappings(mounts: &[RcloneMount], settings: &QgisSettings, sender: Option<&std::sync::mpsc::Sender<String>>) {
    if mounts.is_empty() {
        return;
    }
    // subst モードは rclone 不要なので先に処理する
    for m in mounts {
        if m.mode.as_deref().unwrap_or("subst") == "subst" {
            subst_drive(m, &settings.path_aliases, sender);
        }
    }
    // sync / mount モードは rclone が必要
    let needs_rclone = mounts.iter().any(|m| {
        matches!(m.mode.as_deref().unwrap_or("subst"), "sync" | "mount")
    });
    if !needs_rclone {
        return;
    }
    let rclone_path = match find_rclone_exe() {
        Some(p) => p,
        None => return,
    };
    for m in mounts {
        match m.mode.as_deref().unwrap_or("subst") {
            "sync"  => sync_drive(m, &rclone_path, sender),
            "mount" => mount_drive(m, &rclone_path, sender),
            _ => {}  // subst は上で処理済み
        }
    }
}

/// robocopy でコピー元からローカルキャッシュへミラーリング
fn run_robocopy(src: &str, dst: &str, exclude: &[String], aliases: &HashMap<String, String>) {
    let src = resolve_path(src, aliases);
    let dst = resolve_path(dst, aliases);
    let src = src.as_str();
    let dst = dst.as_str();
    if !PathBuf::from(src).exists() {
        eprintln!("robocopy: コピー元フォルダ '{}' が見つかりません。スキップします。", src);
        return;
    }
    if let Err(e) = fs::create_dir_all(dst) {
        eprintln!("robocopy: コピー先フォルダ作成失敗 ({}): {}", dst, e);
        return;
    }
    println!("robocopy: {} → {} コピー中...", src, dst);
    // /MIR: 完全ミラー（削除も反映）, /MT:8: 並列8スレッド, /R:1 /W:0: リトライ省略, /NP: 進捗表示なし
    let mut cmd = Command::new("robocopy");
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd.args([src, dst, "/MIR", "/MT:8", "/R:1", "/W:0", "/NP"]);
    // 除外フォルダ /XD フォルダ名...
    if !exclude.is_empty() {
        cmd.arg("/XD");
        for dir in exclude {
            cmd.arg(dir);
        }
    }
    let status = cmd.status();
    match status {
        // robocopy は成功時も exit code 1〜7 を返すため 8 以上をエラーとする
        Ok(s) => {
            let code = s.code().unwrap_or(-1);
            if code < 8 {
                println!("robocopy: 完了 (exit {})", code);
            } else {
                eprintln!("robocopy: エラー終了 (exit {})", code);
            }
        }
        Err(e) => eprintln!("robocopy 起動エラー: {}", e),
    }
}

/// subst モード: 指定フォルダをドライブに割り当てる（rclone不要・WinFsp不要）
fn subst_drive(m: &RcloneMount, aliases: &HashMap<String, String>, sender: Option<&std::sync::mpsc::Sender<String>>) {
    let folder = match &m.local_cache {
        Some(p) => resolve_path(p, aliases),
        None => {
            let msg = format!("subst: local_cache の指定が必要です (drive: {})", m.drive);
            if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
            eprintln!("{}", msg);
            return;
        }
    };
    // robocopy_src が指定されていれば subst の前にミラーリング
    if let Some(src) = &m.robocopy_src {
        if let Some(s) = sender { let _ = s.send(format!("MSG:Running robocopy for {}", m.drive)); }
        run_robocopy(src, &folder, &m.robocopy_exclude, aliases);
    }
    let check = if m.drive.ends_with(':') { format!("{}\\" , m.drive) } else { m.drive.clone() };
    if PathBuf::from(&check).exists() {
        if let Some(s) = sender { let _ = s.send(format!("MSG:{} is already assigned, reassigning", m.drive)); }
        println!("subst: {} は既に割り当て済み。いったん解除して再割当てします。", m.drive);
        // try to remove existing mapping via subst /D, ignore errors
        let _ = Command::new("cmd").args(["/C", "subst", &m.drive, "/D"]).status();
        // small wait to let OS release
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    if !PathBuf::from(&folder).exists() {
        let msg = format!("subst: フォルダ '{}' が見つかりません。", folder);
        if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
        eprintln!("{}", msg);
        return;
    }
    if let Some(s) = sender { let _ = s.send(format!("MSG:Assigning {} -> {}", m.drive, folder)); }
    match Command::new("subst").creation_flags(CREATE_NO_WINDOW).args([&m.drive, &folder]).status() {
        Ok(s) if s.success() => {
            if let Some(tx) = sender { let _ = tx.send(format!("MSG:subst {} -> {} assigned", m.drive, folder)); let _ = tx.send("PROG:20".to_string()); }
            println!("subst: {} → {} 割り当て完了", m.drive, folder)
        }
        Ok(_)  => {
            if let Some(tx) = sender { let _ = tx.send(format!("MSG:subst failed {} -> {}", m.drive, folder)); }
            eprintln!("subst 失敗: {} → {}", m.drive, folder)
        }
        Err(e) => {
            if let Some(tx) = sender { let _ = tx.send(format!("MSG:subst error {}: {}", m.drive, e)); }
            eprintln!("subst エラー: {}", e)
        },
    }
}

/// sync モード: rclone sync（BOX→ローカル）+ subst（WinFsp不要）
fn sync_drive(m: &RcloneMount, rclone_path: &str, sender: Option<&std::sync::mpsc::Sender<String>>) {
    let cache = match &m.local_cache {
        Some(p) => p.clone(),
        None => {
            let msg = format!("rclone: mode=sync の場合 local_cache の指定が必要です (drive: {})", m.drive);
            if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
            eprintln!("{}", msg);
            return;
        }
    };
    if let Err(e) = fs::create_dir_all(&cache) {
        if let Some(s) = sender { let _ = s.send(format!("MSG:failed to create cache {}: {}", cache, e)); }
        eprintln!("キャッシュフォルダ作成失敗 ({}): {}", cache, e);
        return;
    }
    // BOX → ローカルに同期（変更分のみ）
    let remote = match &m.remote {
        Some(r) => r.clone(),
        None => {
            let msg = format!("rclone sync: remote の指定が必要です (drive: {})", m.drive);
            if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
            eprintln!("{}", msg);
            return;
        }
    };
    if let Some(s) = sender { let _ = s.send(format!("MSG:rclone sync: {} -> {} starting", remote, cache)); }
    println!("rclone sync: {} → {} 同期中（変更分のみ）...", remote, cache);
    let mut cmd = Command::new(rclone_path);
    cmd.args(["sync", &remote, &cache]);
    match cmd.status() {
        Ok(s) if s.success() => println!("rclone sync: 完了"),
        Ok(_) => eprintln!("rclone sync: 失敗"),
        Err(e) => eprintln!("rclone sync エラー: {}", e),
    }
    // subst でドライブレターを割り当て（既存なら先に解除して再割当て）
    let check = if m.drive.ends_with(':') { format!("{}\\", m.drive) } else { m.drive.clone() };
    if PathBuf::from(&check).exists() {
        if let Some(s) = sender { let _ = s.send(format!("MSG:{} already assigned, reassigning", m.drive)); }
        println!("rclone: {} は既に割り当て済み。いったん解除して再割当てします。", m.drive);
        let _ = Command::new("cmd").args(["/C", "subst", &m.drive, "/D"]).status();
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    match Command::new("subst").creation_flags(CREATE_NO_WINDOW).args([&m.drive, &cache]).status() {
        Ok(s) if s.success() => println!("subst: {} → {} 完了", m.drive, cache),
        Ok(_) => eprintln!("subst 失敗: {} → {}", m.drive, cache),
        Err(e) => eprintln!("subst エラー: {}", e),
    }
}

/// mount モード: rclone mount（WinFsp必要）
fn mount_drive(m: &RcloneMount, rclone_path: &str, sender: Option<&std::sync::mpsc::Sender<String>>) {
    let check = if m.drive.ends_with(':') { format!("{}\\", m.drive) } else { m.drive.clone() };
    if PathBuf::from(&check).exists() {
        if let Some(s) = sender { let _ = s.send(format!("MSG:{} is already mounted, remounting", m.drive)); }
        println!("rclone: {} は既にマウント済みです。いったん解除して再マウントします。", m.drive);
        // attempt to remove existing mount point (mountvol /D), ignore errors
        let _ = Command::new("mountvol").args([&m.drive, "/D"]).status();
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    let mut cmd = Command::new(rclone_path);
    let remote = match &m.remote {
        Some(r) => r.clone(),
        None => {
            eprintln!("rclone mount: remote の指定が必要です (drive: {})", m.drive);
            return;
        }
    };
    cmd.args(["mount", &remote, &m.drive, "--no-console"]);
    if m.read_only {
        cmd.arg("--read-only");
    }
    if let Some(v) = &m.vfs_cache_mode { cmd.args(["--vfs-cache-mode", v]); }
    if let Some(v) = &m.vfs_cache_max_age { cmd.args(["--vfs-cache-max-age", v]); }
    if let Some(v) = &m.vfs_cache_max_size { cmd.args(["--vfs-cache-max-size", v]); }
    if let Some(v) = &m.vfs_cache_poll_interval { cmd.args(["--vfs-cache-poll-interval", v]); }
    if let Some(v) = &m.vfs_write_back { cmd.args(["--vfs-write-back", v]); }
    match cmd.spawn() {
        Ok(_) => {
            if let Some(s) = sender { let _ = s.send(format!("MSG:Starting rclone mount {} -> {}", remote, m.drive)); }
            println!("rclone: {} を {} にマウント開始しました。完了を待機中...", remote, m.drive);
            let mut mounted = false;
            for _ in 0..30 {
                std::thread::sleep(std::time::Duration::from_secs(1));
                if PathBuf::from(&check).exists() {
                    if let Some(s) = sender { let _ = s.send(format!("MSG:rclone mount {} complete", m.drive)); let _ = s.send("PROG:30".to_string()); }
                    println!("rclone: {} のマウント完了。", m.drive);
                    mounted = true;
                    break;
                }
            }
            if !mounted {
                if let Some(s) = sender { let _ = s.send(format!("MSG:rclone mount {} not finished within timeout", m.drive)); }
                eprintln!("rclone: {} のマウントが30秒以内に完了しませんでした。続行します。", m.drive);
            }
        },
        Err(e) => {
            if let Some(s) = sender { let _ = s.send(format!("MSG:rclone mount failed {} -> {}: {}", remote, m.drive, e)); }
            eprintln!("rclone マウント失敗 ({} -> {}): {}", remote, m.drive, e)
        },
    }
}

/// EXE 起動時: インストール済みQGIS4のプロファイルフォルダをコピーする
/// profiles\QGIS4\ → APPDATA\QGIS\QGIS4\
/// バージョン別フォルダが無い場合は profiles\ 直下を共通フォルダとして使用
fn copy_profiles_at_startup(settings_dir: &str, sender: Option<&std::sync::mpsc::Sender<String>>) {
    let base_profiles = PathBuf::from(settings_dir).join("profiles");
    if !base_profiles.exists() {
        if let Some(s) = sender {
            let _ = s.send("MSG:distribution profiles not found".to_string());
        }
        return;
    }

    // インストール済みQGIS4の存在を確認
    let installed = get_available_qgis_versions();
    let mut major_versions: Vec<u32> = installed.iter()
        .filter_map(|(_, exe)| {
            let lower = exe.to_lowercase();
            let major = 4u32;
            let patterns = [
                format!("qgis {}", major),
                format!("qgis{}", major),
                format!("\\{}.", major),
            ];
            if patterns.iter().any(|p| lower.contains(p.as_str())) {
                Some(major)
            } else {
                None
            }
        })
        .collect();
    major_versions.sort();
    major_versions.dedup();

    if major_versions.is_empty() {
        if let Some(s) = sender {
            let _ = s.send("MSG:no matching QGIS installations found".to_string());
        }
        return;
    }

    let all_profile_paths = qgis_launcher::get_qgis_profile_paths();
    let total = major_versions.len().max(1) as f64;
    for (idx, major) in major_versions.iter().enumerate() {
        let target = all_profile_paths.iter()
            .find(|p| p.to_string_lossy().to_lowercase().contains(&format!("qgis{}", major)));
        let target = match target {
            Some(t) => t,
            None => continue,
        };
        // ソース: profiles\QGIS{major}\ があればそちら、なければ profiles\ 直下
        let versioned_src = base_profiles.join(format!("QGIS{}", major));
        let source = if versioned_src.exists() { versioned_src } else { base_profiles.clone() };
        if !source.exists() {
            continue;
        }
        if let Err(e) = fs::create_dir_all(target) {
            if let Some(s) = sender {
                let _ = s.send(format!("MSG:failed to create target {:?}: {}", target, e));
            }
            continue;
        }
        if let Some(s) = sender {
            let _ = s.send(format!("MSG:Copying profiles from {:?} -> {:?}", source, target));
        }
        let _ = copy_dir_contents_skip(&source, target);

        // 進捗を送る（50%〜90% の範囲で割当）
        if let Some(s) = sender {
            let perc = 50.0 + ((idx as f64 + 1.0) / total) * 40.0;
            let _ = s.send(format!("PROG:{}", perc));
        }

        // startup.py は --code ini/startup.py で管理するため、
        // プロファイル配下に残っている古い startup.py を削除する（二重実行防止）
        if let Ok(entries) = fs::read_dir(target) {
            for entry in entries.flatten() {
                if entry.file_type().map(|ft| ft.is_dir()).unwrap_or(false) {
                    let startup = entry.path().join("python").join("startup.py");
                    if startup.exists() {
                        let _ = fs::remove_file(&startup);
                        println!("startup.py を削除（--code に一本化）: {:?}", startup);
                    }
                }
            }
        }
    }
}

/// 既存の QGIS プロファイルを強制削除してから配布プロファイルを再コピーする。
/// 削除対象は `%APPDATA%/QGIS/QGISx/profiles/*` または `%APPDATA%/QGIS/QGISx/*` の直下ディレクトリ。
fn reset_profiles(settings_dir: &str, sender: Option<&std::sync::mpsc::Sender<String>>) -> Result<(), String> {
    let base_profiles = PathBuf::from(settings_dir).join("profiles");
    if !base_profiles.exists() {
        return Err("distribution profiles not found".to_string());
    }

    if let Some(s) = sender { let _ = s.send("PROG:0".to_string()); }
    if let Some(s) = sender { let _ = s.send("MSG:既存プロファイルを削除しています".to_string()); }

    let all_profile_paths = qgis_launcher::get_qgis_profile_paths();
    for p in &all_profile_paths {
        let probe = p.join("profiles");
        if probe.exists() {
            if let Ok(entries) = fs::read_dir(&probe) {
                for entry in entries.flatten() {
                    if entry.file_type().map(|ft| ft.is_dir()).unwrap_or(false) {
                        let path = entry.path();
                        if let Err(e) = fs::remove_dir_all(&path) {
                            eprintln!("プロファイル削除失敗 {:?}: {}", path, e);
                        } else {
                            println!("削除: {:?}", path);
                        }
                    }
                }
            }
        } else {
            if let Ok(entries) = fs::read_dir(&p) {
                for entry in entries.flatten() {
                    if entry.file_type().map(|ft| ft.is_dir()).unwrap_or(false) {
                        if let Ok(name) = entry.file_name().into_string() {
                            if name.eq_ignore_ascii_case("profiles") { continue; }
                        }
                        let path = entry.path();
                        if let Err(e) = fs::remove_dir_all(&path) {
                            eprintln!("プロファイル削除失敗 {:?}: {}", path, e);
                        } else {
                            println!("削除: {:?}", path);
                        }
                    }
                }
            }
        }
    }

    if let Some(s) = sender { let _ = s.send("PROG:40".to_string()); }
    if let Some(s) = sender { let _ = s.send("MSG:配布プロファイルをコピーしています".to_string()); }

    // コピーして再構築
    copy_profiles_at_startup(settings_dir, sender);
    if let Some(s) = sender { let _ = s.send("PROG:100".to_string()); }
    Ok(())
}

/// reset_profiles の処理を行いながら `sender` に進捗・メッセージを送る。

/// 実行フォルダ/ini/<role>.ini のパスを返す。存在しない場合は None。
#[allow(dead_code)]
fn get_role_ini_path(role: &str) -> Option<PathBuf> {
    let exe_dir = env::current_exe().ok()?.parent().map(|d| d.to_path_buf())?;
    let p = exe_dir.join("ini").join(format!("{}.ini", role));
    if p.exists() { Some(p) } else {
        println!("ロールINIが見つかりません (スキップ): {:?}", p);
        None
    }
}

/// QGIS4 用のロールカスタマイズファイル `<role>.xml` を選択して返す。
/// QGIS4 以外はサポートしません。
fn get_role_customization_path(role: &str, _qgis_path: &str) -> Option<PathBuf> {
    let exe_dir = env::current_exe().ok()?.parent().map(|d| d.to_path_buf())?;
    let ini_dir = exe_dir.join("ini");

    // QGIS4: 必ず .xml を使用。存在しなければ None を返す（フォールバックなし）。
    let p_xml = ini_dir.join(format!("{}.xml", role));
    if p_xml.exists() { return Some(p_xml); }
    println!("QGIS4 用ロールカスタマイズが見つかりません (期待: {}): dir={:?}", p_xml.display(), ini_dir);
    None
}

/// qgis_global_settings.ini を一時生成し、パスを返す。
/// QGIS の --globalsettingsfile に渡すことで userrole を QGIS グローバル変数として設定する。
/// ファイルは実行フォルダ/ini/ に書き込む。
fn write_global_settings_ini(role: &str) -> Option<PathBuf> {
    let exe_dir = env::current_exe().ok()?.parent().map(|d| d.to_path_buf())?;
    let ini_dir = exe_dir.join("ini");
    if let Err(e) = fs::create_dir_all(&ini_dir) {
        eprintln!("ini ディレクトリ作成失敗: {}", e);
        return None;
    }
    let path = ini_dir.join("qgis_global_settings.ini");
    let content = format!("[Variables]\nuserrole={role}\n", role = role);
    match fs::write(&path, &content) {
        Ok(_) => { println!("グローバル設定INI書き込み: {:?}", path); Some(path) }
        Err(e) => { eprintln!("グローバル設定INI書き込み失敗: {}", e); None }
    }
}

/// project_path の単一エントリを実際の .qgs/.qgz ファイルパスに解決する。
/// - .qgs/.qgz 拡張子のパス → そのファイルが存在すれば返す
/// - フォルダパス            → 直下の .qgs/.qgz を昇順で列挙して最初を返す
/// - どちらも解決できない場合  → None（QGIS はプロジェクト未指定で起動）
fn resolve_project_to_file(path_str: &str, settings_dir: &str) -> Option<PathBuf> {
    if path_str.is_empty() {
        return None;
    }
    let pb = PathBuf::from(path_str);
    let lower = path_str.to_lowercase();
    let is_qgis_file = lower.ends_with(".qgs") || lower.ends_with(".qgz");

    // 絶対パスはそのまま、相対パスは settings_dir 基準で解決
    let candidates: Vec<PathBuf> = if pb.is_absolute() {
        vec![pb.clone()]
    } else {
        vec![pb.clone(), PathBuf::from(settings_dir).join(&pb)]
    };

    for effective in &candidates {
        if is_qgis_file {
            if effective.is_file() {
                return Some(effective.clone());
            }
        } else if effective.is_dir() {
            // フォルダ: 直下の .qgs/.qgz を昇順で列挙し最初を返す
            if let Ok(entries) = fs::read_dir(effective) {
                let mut files: Vec<_> = entries
                    .flatten()
                    .filter(|e| e.file_type().map(|ft| ft.is_file()).unwrap_or(false))
                    .filter(|e| {
                        let n = e.file_name().to_string_lossy().to_lowercase();
                        n.ends_with(".qgs") || n.ends_with(".qgz")
                    })
                    .collect();
                files.sort_by_key(|e| e.file_name());
                if let Some(first) = files.first() {
                    return Some(effective.join(first.file_name()));
                }
            }
            // フォルダに .qgs/.qgz がない場合はプロジェクト未指定で起動
            return None;
        }
    }
    None
}

fn launch_qgis(profile_name: &str, project_paths: &[String], project_root: &str, exe_path: &str, role: &str) {
    // QGISのパスを決定（プロファイルコピーは EXE 起動時に完了済み）
    let qgis_path = if exe_path.is_empty() {
        match find_qgis_path_from_registry() {
            Some(p) => p,
            None => {
                eprintln!("QGISの実行ファイルが見つかりませんでした。レジストリの関連付けを確認してください。");
                return;
            }
        }
    } else {
        exe_path.to_string()
    };

    // --customizationfile: QGIS4 用のカスタマイズ XML を渡す
    let customization_ini: Option<PathBuf> = get_role_customization_path(role, &qgis_path);

    // --globalsettingsfile: userrole を QGIS グローバル変数として渡すための ini を生成
    let global_settings_ini: Option<PathBuf> = write_global_settings_ini(role);

    // 実行フォルダ/ini/startup.py のパスを取得（存在する場合のみ --code に渡す）
    let startup_script: Option<PathBuf> = env::current_exe().ok()
        .and_then(|p| p.parent().map(|d| d.join("ini").join("startup.py")))
        .filter(|p| p.exists());

    // Helper to spawn one process with optional project
    let spawn_with_project = |maybe_project: Option<PathBuf>| {
        let qgis_lower = qgis_path.to_lowercase();
        let is_batch = qgis_lower.ends_with(".bat") || qgis_lower.ends_with(".cmd");
        let mut cmd = if is_batch {
            // .bat/.cmd は CreateProcessW から直接起動できないため cmd.exe 経由で実行
            let mut c = Command::new("cmd.exe");
            c.arg("/C").arg(&qgis_path);
            c
        } else {
            Command::new(&qgis_path)
        };
        // QGIS プロセスの作業ディレクトリを実行ファイルのフォルダに設定
        if let Ok(exe_path) = env::current_exe() {
            if let Some(parent) = exe_path.parent() {
                cmd.current_dir(parent);
            }
        }
        cmd.creation_flags(CREATE_NO_WINDOW);
        cmd.env("PORTAL_USERROLE", role);
        cmd.arg("--profile").arg(profile_name);
        if let Some(ref ini) = customization_ini {
            cmd.arg("--customizationfile").arg(ini);
        }
        if let Some(ref gs) = global_settings_ini {
            cmd.arg("--globalsettingsfile").arg(gs);
        }
        if let Some(ref script) = startup_script {
            cmd.arg("--code").arg(script);
        }
        if let Some(p) = maybe_project {
            if let Some(s) = p.to_str() {
                // QGIS4 ではプロジェクトパスを位置引数で渡す
                cmd.arg(s);
            }
        }
        match cmd.spawn() {
            Ok(_) => println!("QGISの起動リクエストに成功しました。"),
            Err(e) => eprintln!("QGISの起動に失敗しました: {}", e),
        }
    };

    if project_paths.is_empty() {
        spawn_with_project(None);
        return;
    }

    for path_str in project_paths {
        let effective_project = resolve_project_to_file(path_str.trim(), project_root);
        spawn_with_project(effective_project);
    }
}



fn copy_dir_contents_skip(src: &PathBuf, dst: &PathBuf) -> std::io::Result<()> {
    if !dst.exists() { fs::create_dir_all(dst)?; }
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        if file_type.is_dir() {
            if !to.exists() { fs::create_dir_all(&to)?; }
            copy_dir_contents_skip(&from, &to)?;
        } else if file_type.is_file() {
            if !to.exists() { fs::copy(&from, &to)?; }
        }
    }
    Ok(())
}

fn get_available_qgis_versions() -> Vec<(String, String)> {
    let mut versions = Vec::new();

    let default_path = find_qgis_path_from_registry();
    let mut default_base_dir = None;

    if let Some(p) = &default_path {
        let pb = PathBuf::from(p);
        let mut current = pb.as_path();
        while let Some(parent) = current.parent() {
            if let Some(name) = current.file_name().and_then(|n| n.to_str()) {
                if name.to_lowercase().starts_with("qgis") {
                    default_base_dir = Some(parent.to_path_buf());
                    break;
                }
            }
            current = parent;
        }
    }

    let mut base_dirs_to_check = Vec::new();
    if let Some(dir) = default_base_dir {
        base_dirs_to_check.push(dir);
    }
    if let Ok(pf) = env::var("ProgramFiles") {
        let pb = PathBuf::from(pf);
        if !base_dirs_to_check.contains(&pb) {
            base_dirs_to_check.push(pb);
        }
    }
    let osgeo4w = PathBuf::from(r"C:\OSGeo4W");
    if !base_dirs_to_check.contains(&osgeo4w) {
        base_dirs_to_check.push(osgeo4w);
    }

    for base_dir in base_dirs_to_check {
        if let Ok(entries) = fs::read_dir(&base_dir) {
            for entry in entries.flatten() {
                if let Ok(ft) = entry.file_type() {
                    if ft.is_dir() {
                        let name = entry.file_name().to_string_lossy().to_string();
                        let folder_path = entry.path();
                        
                        let lower_name = name.to_lowercase();
                        if lower_name.starts_with("qgis") {
                            let bin_dir = folder_path.join("bin");
                            let bat_path = bin_dir.join("qgis.bat");
                            let ltr_bat_path = bin_dir.join("qgis-ltr.bat");
                            let qt6_bat_path = bin_dir.join("qgis-qt6.bat");
                            let exe_path = bin_dir.join("qgis-bin.exe");

                            if bat_path.exists() {
                                versions.push((format!("{} (qgis.bat)", name), bat_path.to_string_lossy().to_string()));
                            }
                            if ltr_bat_path.exists() {
                                versions.push((format!("{} (qgis-ltr.bat)", name), ltr_bat_path.to_string_lossy().to_string()));
                            }
                            if qt6_bat_path.exists() {
                                versions.push((format!("{} (qgis-qt6.bat)", name), qt6_bat_path.to_string_lossy().to_string()));
                            }
                            if !bat_path.exists() && !ltr_bat_path.exists() && !qt6_bat_path.exists() && exe_path.exists() {
                                versions.push((format!("{} (qgis-bin.exe)", name), exe_path.to_string_lossy().to_string()));
                            }
                        } else if lower_name.starts_with("qfield") {
                            let qfield_exe = folder_path.join("usr").join("bin").join("qfield.exe");
                            if qfield_exe.exists() {
                                versions.push((format!("QFieldインストール版 {}", name), qfield_exe.to_string_lossy().to_string()));
                            }
                        }
                    }
                }
            }
        }
    }

    if let Ok(current_dir) = env::current_dir() {
        if let Ok(entries) = fs::read_dir(&current_dir) {
            for entry in entries.flatten() {
                if let Ok(ft) = entry.file_type() {
                    if ft.is_dir() {
                        let name = entry.file_name().to_string_lossy().to_string();
                        if name.to_lowercase().starts_with("qgis") {
                            let osgeo4w_root = entry.path().join("qgis");
                            let qgis_ltr_bat = osgeo4w_root.join("bin").join("qgis-ltr.bat");
                            let qgis_bat = osgeo4w_root.join("bin").join("qgis.bat");

                            if qgis_ltr_bat.exists() {
                                versions.push((format!("ポータブル版 {} (LTR)", name), qgis_ltr_bat.to_string_lossy().to_string()));
                            }
                            if qgis_bat.exists() && !qgis_ltr_bat.exists() {
                                versions.push((format!("ポータブル版 {}", name), qgis_bat.to_string_lossy().to_string()));
                            }
                        } else if name.to_lowercase().starts_with("qfield") {
                            let qfield_exe = entry.path().join("usr").join("bin").join("qfield.exe");
                            if qfield_exe.exists() {
                                versions.push((format!("QFieldポータブル版 {}", name), qfield_exe.to_string_lossy().to_string()));
                            }
                        }
                    }
                }
            }
        }
    }

    let mut unique_versions: Vec<(String, String)> = Vec::new();
    for v in versions {
        let p = v.1.to_lowercase();
        if !unique_versions.iter().any(|(_, path)| path.to_lowercase() == p) {
            unique_versions.push(v);
        }
    }

    if let Some(p) = &default_path {
        let mut found = false;
        
        let mut folder_name = String::new();
        let pb = PathBuf::from(p);
        let mut current = pb.as_path();
        while let Some(parent) = current.parent() {
            if let Some(name) = current.file_name().and_then(|n| n.to_str()) {
                let lower = name.to_lowercase();
                if (lower.starts_with("qgis") || lower.starts_with("qfield")) && !lower.ends_with(".bat") && !lower.ends_with(".exe") {
                    folder_name = name.to_string();
                    break;
                }
            }
            current = parent;
        }

        let filename = pb.file_name().and_then(|n| n.to_str()).unwrap_or("");
        let final_display_name = if !folder_name.is_empty() {
            format!("{} ({})", folder_name, filename)
        } else {
            "システム既定のQGIS".to_string()
        };

        for (name, path) in &mut unique_versions {
            if path.to_lowercase() == p.to_lowercase() {
                *name = format!("{} (システム既定)", final_display_name);
                found = true;
                break;
            }
        }
        if !found {
            unique_versions.insert(0, (format!("{} (システム既定)", final_display_name), p.clone()));
        }
    }

    unique_versions
}

/// 指定した .qgs/.qgz プロジェクトファイルの <qgis> ルート要素から
/// `version` 属性を抽出して返す。失敗した場合は None。
fn parse_qgs_version_from_str(xml: &str) -> Option<String> {
    let mut reader = Reader::from_str(xml);
    reader.trim_text(true);
    let mut buf = Vec::new();
    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(ref e)) | Ok(Event::Empty(ref e)) => {
                if e.name() == QName(b"qgis") {
                    for a in e.attributes().flatten() {
                        if a.key.as_ref() == b"version" {
                            if let Ok(val) = a.unescape_value() {
                                return Some(val.into_owned());
                            }
                        }
                    }
                    return None;
                }
            }
            Ok(Event::Eof) => break,
            Err(_) => break,
            _ => {}
        }
        buf.clear();
    }
    None
}

fn get_project_file_version(path: &str) -> Option<String> {
    let lower = path.to_lowercase();
    if lower.ends_with(".qgz") {
        // open as zip and find the first .qgs entry
        let f = std::fs::File::open(path).ok()?;
        let mut zip = ZipArchive::new(f).ok()?;
        for i in 0..zip.len() {
            if let Ok(mut file) = zip.by_index(i) {
                let name = file.name().to_lowercase();
                if name.ends_with(".qgs") {
                    let mut s = String::new();
                    if file.read_to_string(&mut s).is_ok() {
                        return parse_qgs_version_from_str(&s);
                    }
                }
            }
        }
        None
    } else {
        if let Ok(s) = std::fs::read_to_string(path) {
            parse_qgs_version_from_str(&s)
        } else {
            None
        }
    }
}

/// 指定されたプロジェクトのバージョン文字列に一致する
/// `get_available_qgis_versions()` のエントリを返す。
/// マッチはまず major.minor の部分一致を試し、次に major のみでフォールバックする。
fn find_matching_available_for_project(project_ver: &str, available: &Vec<(String, String)>) -> Option<(String, String)> {
    let pv = project_ver.trim();
    if pv.is_empty() { return None; }

    // 正規化して numeric parts を取得
    let pv_parts = parse_version_parts(pv);
    if pv_parts.is_empty() { return available.first().cloned(); }

    // まず major.minor の完全一致を試す（両方存在する場合）
    if pv_parts.len() >= 2 {
        let target_major = &pv_parts[0];
        let target_minor = &pv_parts[1];
        for (name, path) in available {
            let combined = format!("{} {}", name, path);
            let av_parts = parse_version_parts(&combined);
            if av_parts.len() >= 2 && &av_parts[0] == target_major && &av_parts[1] == target_minor {
                return Some((name.clone(), path.clone()));
            }
        }
    }

    // 次に major の一致を試す
    let target_major = &pv_parts[0];
    for (name, path) in available {
        let combined = format!("{} {}", name, path);
        let av_parts = parse_version_parts(&combined);
        if !av_parts.is_empty() && &av_parts[0] == target_major {
            return Some((name.clone(), path.clone()));
        }
    }

    // 最後に以前の文字列包含フォールバック（互換性保護）
    let cand = target_major.to_lowercase();
    for (name, path) in available {
        let name_l = name.to_lowercase();
        let path_l = path.to_lowercase();
        if name_l.contains(&cand) || path_l.contains(&cand) {
            return Some((name.clone(), path.clone()));
        }
    }
    
    // 一致するQGISが見つからなかった場合は None を返す（自動選択しない）
    None
}



#[derive(Clone)]
struct AppState {
    settings_dir: String,
    project_root_dir: String,
    progress: Arc<Mutex<Vec<String>>>,
    /// 更新チェックを行うか（--no-update-check や設定で無効化される）
    update_check_enabled: bool,
}

const UI_HTML: &str = include_str!("../public/index.html");

async fn ui_handler() -> Html<&'static str> {
    Html(UI_HTML)
}

fn run_api_server_sync(port: u16, settings_dir: &str, project_root_dir: &str, open_browser: bool, update_check_enabled: bool) {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(run_api_server(port, settings_dir, project_root_dir, open_browser, update_check_enabled));
}

async fn run_api_server(port: u16, settings_dir: &str, project_root_dir: &str, open_browser: bool, update_check_enabled: bool) {
    let state = AppState {
        settings_dir: settings_dir.to_string(),
        project_root_dir: project_root_dir.to_string(),
        progress: Arc::new(Mutex::new(Vec::new())),
        update_check_enabled,
    };
    let app = Router::new()
        .route("/", get(ui_handler))
        .route("/favicon.ico", get(favicon_handler))
        .route("/health", get(health))
        .route("/settings", get(get_settings_handler).post(post_settings_handler))
        .route("/qgis", get(list_qgis_handler))
        .route("/profiles", get(list_profiles_handler))
        .route("/projects", get(list_projects_handler))
        .route("/launch", post(launch_handler))
        .route("/reset", post(reset_profiles_handler))
        .route("/progress", get(progress_handler))
        .route("/project-version", get(project_version_handler))
        .route("/update", get(update_check_handler))
        .route("/update/apply", post(update_apply_handler))
        .route("/api/v1/server/stop", post(stop_server))
        .route("/api/v1/server/info", get(server_info))
        .route("/version", get(version_handler))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = std::net::SocketAddr::from((std::net::Ipv4Addr::LOCALHOST, port));
    let listener: tokio::net::TcpListener = 'bind: loop {
        match tokio::net::TcpListener::bind(addr).await {
            Ok(l) => break 'bind l,
            Err(e) => {
                let health_url = format!("http://127.0.0.1:{}/health", port);
                let existing = reqwest::get(&health_url)
                    .await
                    .map(|r| r.status().is_success())
                    .unwrap_or(false);
                if !existing {
                    eprintln!("ポート {} で起動できません: {}", port, e);
                    std::process::exit(1);
                }
                eprintln!("既にポート {} で起動しています。古いインスタンスを停止します。", port);
                let stop_url = format!("http://127.0.0.1:{}/api/v1/server/stop", port);
                let _ = reqwest::Client::new().post(&stop_url).send().await;
                for _ in 1..=60 {
                    tokio::time::sleep(std::time::Duration::from_millis(500)).await;
                    if let Ok(l) = tokio::net::TcpListener::bind(addr).await {
                        eprintln!("ポート {} を確保しました。新しいインスタンスを起動します。", port);
                        break 'bind l;
                    }
                }
                eprintln!("ポート {} の解放を待ちましたが、起動できません: {}", port, e);
                std::process::exit(1);
            }
        }
    };

    if open_browser {
        let open_url = format!("http://127.0.0.1:{}/", port);
        let health_url = format!("http://127.0.0.1:{}/health", port);
        tokio::spawn(async move {
            for _ in 0..60 {
                if let Ok(resp) = reqwest::get(&health_url).await {
                    if resp.status().is_success() {
                        let _ = opener::open(&open_url);
                        break;
                    }
                }
                tokio::time::sleep(std::time::Duration::from_millis(500)).await;
            }
        });
    }

    let local_addr = listener.local_addr().unwrap();
    println!("{}", serde_json::json!({ "port": local_addr.port() }));
    axum::serve(listener, app).await.unwrap();
}

const FAVICON_ICO: &[u8] = include_bytes!("../installer/app_icon.ico");

async fn favicon_handler() -> impl IntoResponse {
    ([(header::CONTENT_TYPE, "image/x-icon")], FAVICON_ICO)
}

async fn health() -> &'static str {
    "ok"
}

async fn stop_server() -> &'static str {
    tokio::spawn(async {
        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
        std::process::exit(0);
    });
    "ok"
}

async fn server_info(State(state): State<AppState>) -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "settings_dir": state.settings_dir,
        "project_root_dir": state.project_root_dir,
    }))
}

async fn version_handler() -> Json<serde_json::Value> {
    Json(serde_json::json!({ "version": env!("CARGO_PKG_VERSION") }))
}

async fn progress_handler(State(state): State<AppState>) -> Json<serde_json::Value> {
    let messages = state.progress.lock().unwrap().clone();
    Json(serde_json::json!({ "messages": messages }))
}

async fn get_settings_handler(State(state): State<AppState>) -> Result<Json<QgisSettings>, StatusCode> {
    let settings_dir = state.settings_dir;
    let settings = tokio::task::spawn_blocking(move || get_current_settings(&settings_dir))
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(settings))
}

#[derive(Deserialize)]
struct LaunchRequest {
    profile: String,
    project_paths: Vec<String>,
    executable: String,
    role: String,
}

async fn launch_handler(State(state): State<AppState>, Json(req): Json<LaunchRequest>) -> Result<Json<serde_json::Value>, StatusCode> {
    let project_root_dir = state.project_root_dir;
    let profile = req.profile;
    let project_paths = req.project_paths;
    let executable = req.executable;
    let role = req.role;
    tokio::task::spawn_blocking(move || {
        launch_qgis(&profile, &project_paths, &project_root_dir, &executable, &role);
    })
    .await
    .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(serde_json::json!({ "ok": true })))
}

#[derive(Serialize)]
struct QgisVersion {
    name: String,
    path: String,
}

async fn list_qgis_handler() -> Result<Json<Vec<QgisVersion>>, StatusCode> {
    let versions = tokio::task::spawn_blocking(get_available_qgis_versions)
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(versions.into_iter().map(|(n, p)| QgisVersion { name: n, path: p }).collect()))
}

async fn post_settings_handler(State(state): State<AppState>, Json(req): Json<QgisSettings>) -> Result<Json<serde_json::Value>, StatusCode> {
    let settings_dir = state.settings_dir;
    tokio::task::spawn_blocking(move || save_settings(&settings_dir, &req))
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?
        .map_err(|e| {
            eprintln!("settings save error: {}", e);
            StatusCode::INTERNAL_SERVER_ERROR
        })?;
    Ok(Json(serde_json::json!({ "ok": true })))
}

async fn reset_profiles_handler(State(state): State<AppState>) -> Result<Json<serde_json::Value>, StatusCode> {
    // 既存の進捗メッセージをクリア
    {
        let mut p = state.progress.lock().unwrap();
        p.clear();
    }

    let (tx, rx) = std::sync::mpsc::channel::<String>();
    let state2 = state.clone();
    let bridge = tokio::task::spawn_blocking(move || {
        while let Ok(msg) = rx.recv() {
            let mut p = state2.progress.lock().unwrap();
            p.push(msg);
        }
    });

    let project_root_dir = state.project_root_dir.clone();
    let reset = tokio::task::spawn_blocking(move || reset_profiles(&project_root_dir, Some(&tx)));

    let res = reset.await.map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    let _ = bridge.await;

    {
        let mut p = state.progress.lock().unwrap();
        p.push("MSG:done".to_string());
    }

    res.map_err(|e| {
        eprintln!("reset profiles error: {}", e);
        StatusCode::INTERNAL_SERVER_ERROR
    })?;
    Ok(Json(serde_json::json!({ "ok": true })))
}

#[derive(Deserialize)]
struct VersionQuery {
    path: String,
}

async fn project_version_handler(State(state): State<AppState>, Query(q): Query<VersionQuery>) -> Result<Json<serde_json::Value>, StatusCode> {
    let project_root_dir = state.project_root_dir;
    let path = q.path;
    let version = tokio::task::spawn_blocking(move || {
        resolve_project_to_file(&path, &project_root_dir)
            .and_then(|p| get_project_file_version(p.to_str().unwrap_or("")))
    })
    .await
    .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(serde_json::json!({ "version": version })))
}

async fn update_check_handler(State(state): State<AppState>) -> Result<Json<serde_json::Value>, StatusCode> {
    if !state.update_check_enabled {
        return Ok(Json(serde_json::json!({
            "available": false,
            "disabled": true,
            "current": env!("CARGO_PKG_VERSION")
        })));
    }
    let settings_dir = state.settings_dir;
    let settings = tokio::task::spawn_blocking(move || get_current_settings(&settings_dir))
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    let current = env!("CARGO_PKG_VERSION");
    match check_nsis_update(&settings) {
        Ok(None) => Ok(Json(serde_json::json!({ "available": false, "current": current }))),
        Ok(Some(info)) => {
            // 同一バージョンへの再試行が禁止されている場合は理由も返す（UI で警告表示）
            let blocked_reason = check_update_attempt_allowed(&info.version).err();
            Ok(Json(serde_json::json!({
                "available": true,
                "current": current,
                "version": info.version,
                "url": info.url,
                "full_url": info.full_url,
                "full": info.full,
                "notes": info.notes,
                "blocked": blocked_reason.is_some(),
                "blocked_reason": blocked_reason
            })))
        }
        Err(e) => {
            eprintln!("update check error: {}", e);
            Err(StatusCode::INTERNAL_SERVER_ERROR)
        }
    }
}

#[derive(Deserialize, Default)]
struct UpdateApplyRequest {
    /// ループガードを無視して強制的に更新する
    #[serde(default)]
    force: bool,
}

async fn update_apply_handler(
    State(state): State<AppState>,
    body: Option<Json<UpdateApplyRequest>>,
) -> Json<serde_json::Value> {
    if !state.update_check_enabled {
        return Json(serde_json::json!({
            "ok": false,
            "message": "更新チェックは無効化されています（--no-update-check または設定の update_check）"
        }));
    }
    let force = body.map(|Json(b)| b.force).unwrap_or(false);
    let settings_dir = state.settings_dir;

    // ダウンロードと検証までは同期的に行い、失敗理由を UI に返す。
    // インストーラー起動（＝プロセス終了）は応答を返した後に行う。
    let prepared = tokio::task::spawn_blocking(move || {
        let settings = get_current_settings(&settings_dir);
        prepare_nsis_update(&settings, force)
    })
    .await;

    match prepared {
        Ok(Ok((installer, version, kind))) => {
            tokio::task::spawn_blocking(move || {
                std::thread::sleep(std::time::Duration::from_secs(1));
                run_nsis_installer_and_exit(&installer, &current_install_dir().to_string_lossy());
            });
            Json(serde_json::json!({
                "ok": true,
                "version": version,
                "kind": kind,
                "message": format!("{}（{}）を開始しました。インストール完了後に自動で再起動します。", kind, version)
            }))
        }
        Ok(Err(e)) => {
            eprintln!("update apply error: {}", e);
            Json(serde_json::json!({ "ok": false, "message": e }))
        }
        Err(e) => {
            eprintln!("update apply join error: {}", e);
            Json(serde_json::json!({ "ok": false, "message": "更新処理の実行に失敗しました" }))
        }
    }
}

#[derive(Serialize)]
struct ProfileItem {
    name: String,
    path: String,
}

#[derive(Serialize)]
struct ProjectItem {
    display: String,
    path: String,
}

fn is_qgis_project(path: &std::path::Path) -> bool {
    let n = path.file_name().map(|s| s.to_string_lossy().to_lowercase()).unwrap_or_default();
    n.ends_with(".qgs") || n.ends_with(".qgz")
}

fn get_available_profiles(settings_dir: &str) -> Vec<ProfileItem> {
    let mut result = Vec::new();
    let mut names = HashSet::new();

    // 配布プロファイル
    let dist = PathBuf::from(settings_dir).join("profiles");
    if dist.exists() {
        if let Ok(entries) = fs::read_dir(&dist) {
            for e in entries.flatten() {
                if e.file_type().map(|ft| ft.is_dir()).unwrap_or(false) {
                    if let Some(n) = e.file_name().to_str() {
                        if names.insert(n.to_string()) {
                            result.push(ProfileItem { name: n.to_string(), path: e.path().to_string_lossy().to_string() });
                        }
                    }
                }
            }
        }
    }

    // システム上の QGIS プロファイル
    for base in qgis_launcher::get_qgis_profile_paths() {
        let probe = base.join("profiles");
        let dir = if probe.exists() { probe } else { base };
        if let Ok(entries) = fs::read_dir(&dir) {
            for e in entries.flatten() {
                if e.file_type().map(|ft| ft.is_dir()).unwrap_or(false) {
                    if let Some(n) = e.file_name().to_str() {
                        if names.insert(n.to_string()) {
                            result.push(ProfileItem { name: n.to_string(), path: e.path().to_string_lossy().to_string() });
                        }
                    }
                }
            }
        }
    }

    result.sort_by(|a, b| a.name.cmp(&b.name));
    result
}

fn get_available_projects(settings: &QgisSettings, project_root: &str) -> Vec<ProjectItem> {
    let mut result = Vec::new();
    let mut seen = HashSet::new();

    for src in &settings.project_path {
        let src = src.trim();
        if src.is_empty() { continue; }
        let expanded = expand_env_vars(&resolve_path(src, &settings.path_aliases));
        let pb = if PathBuf::from(&expanded).is_absolute() {
            PathBuf::from(&expanded)
        } else {
            PathBuf::from(project_root).join(&expanded)
        };

        if pb.is_file() && is_qgis_project(&pb) {
            if seen.insert(pb.clone()) {
                let display = pb.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_else(|| pb.to_string_lossy().to_string());
                result.push(ProjectItem { display, path: pb.to_string_lossy().to_string() });
            }
        } else if pb.is_dir() {
            if let Ok(entries) = fs::read_dir(&pb) {
                let mut files: Vec<_> = entries
                    .flatten()
                    .filter(|e| e.file_type().map(|ft| ft.is_file()).unwrap_or(false))
                    .filter(|e| is_qgis_project(&e.path()))
                    .collect();
                files.sort_by_key(|e| e.file_name());
                for f in files {
                    let path = pb.join(f.file_name());
                    if seen.insert(path.clone()) {
                        let display = format!("{}\\{}", pb.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default(), f.file_name().to_string_lossy());
                        result.push(ProjectItem { display, path: path.to_string_lossy().to_string() });
                    }
                }
            }
        }
    }

    result
}

async fn list_profiles_handler(State(state): State<AppState>) -> Result<Json<Vec<ProfileItem>>, StatusCode> {
    let settings_dir = state.settings_dir;
    let profiles = tokio::task::spawn_blocking(move || get_available_profiles(&settings_dir))
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(profiles))
}

async fn list_projects_handler(State(state): State<AppState>) -> Result<Json<Vec<ProjectItem>>, StatusCode> {
    let settings_dir = state.settings_dir.clone();
    let project_root_dir = state.project_root_dir;
    let projects = tokio::task::spawn_blocking(move || {
        let settings = get_current_settings(&settings_dir);
        get_available_projects(&settings, &project_root_dir)
    })
    .await
    .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(projects))
}
