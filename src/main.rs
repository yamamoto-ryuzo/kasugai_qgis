#![cfg_attr(feature = "gui", windows_subsystem = "windows")]

use clap::Parser;
use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::os::windows::process::CommandExt;
use serde::{Deserialize, Serialize};
use winreg::enums::*;

/// 子プロセスのコンソールウィンドウを非表示にする Windows フラグ
const CREATE_NO_WINDOW: u32 = 0x08000000;
use winreg::RegKey;
#[cfg(feature = "gui")]
use fltk::misc::Progress;
use quick_xml::Reader;
use quick_xml::events::Event;
use quick_xml::name::QName;
use std::sync::{Arc, Mutex};
use std::time::SystemTime;
use zip::ZipArchive;
use std::io::Read;

#[cfg(feature = "gui")]
use fltk::{prelude::*, *};
#[cfg(feature = "gui")]
use fltk::enums::Align;

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
/// 例: "QGIS 3.44.8" -> Some("3") , "qgis 4.0.0" -> Some("4")
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

    /// コマンドラインモードで動作する（指定がなければ GUI を起動）
    #[arg(long, default_value_t = false)]
    cli: bool,

    /// 検出されるQGIS一覧を出力して終了する（デバッグ用）
    #[arg(long, default_value_t = false)]
    list_qgis: bool,

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
    if let Ok(data) = fs::read_to_string(path) {
        // 読み込み時に常にバックスラッシュを事前修正してからパースする。
        // Accept either string or array for `project_path` for backward compatibility.
        let fixed = fix_backslashes_in_json(&data);
        if let Ok(mut v) = serde_json::from_str::<serde_json::Value>(&fixed) {
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
            if let Ok(s) = serde_json::from_value::<QgisSettings>(v) {
                return s;
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
/// `qgislocalsync.config` が存在する場合はそちらを優先し、
/// JSON の `local_sync` は未指定項目のフォールバックとして使用する。
fn resolve_local_sync_config(settings: &QgisSettings, settings_dir: &str) -> Option<LocalSyncConfig> {
    let json_cfg = settings.local_sync.as_ref()?;
    let file_cfg = read_qgislocalsync_config(settings_dir);
    if file_cfg.is_none() {
        return Some(json_cfg.clone());
    }
    let mut file = file_cfg.unwrap();
    if file.sync_src.is_none() { file.sync_src = json_cfg.sync_src.clone(); }
    if file.sync_dst.is_none() { file.sync_dst = json_cfg.sync_dst.clone(); }
    if file.qfield_version.is_none() { file.qfield_version = json_cfg.qfield_version.clone(); }
    if file.qgis_version.is_none() { file.qgis_version = json_cfg.qgis_version.clone(); }
    if file.exclude_dirs.is_empty() { file.exclude_dirs = json_cfg.exclude_dirs.clone(); }
    if file.portable_profile_version.is_none() { file.portable_profile_version = json_cfg.portable_profile_version.clone(); }
    Some(file)
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

/// KASUGAI/yr-qgis-launcher 方式のローカル自動同期を実行する。
/// SYNC_SRC → SYNC_DST へ、QField*/QGIS* フォルダはバージョン文字列比較で差分がある場合のみ同期する。
fn run_local_sync(settings: &QgisSettings, settings_dir: &str, sender: Option<&std::sync::mpsc::Sender<String>>) {
    let Some(config) = resolve_local_sync_config(settings, settings_dir) else { return; };
    let Some(src) = config.sync_src.as_ref() else { return; };
    let Some(dst) = config.sync_dst.as_ref() else { return; };

    let src = expand_env_vars(&resolve_path(src, &settings.path_aliases));
    let dst = expand_env_vars(&resolve_path(dst, &settings.path_aliases));

    let msg = format!("local_sync: {} → {}", src, dst);
    if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
    println!("{}", msg);

    if !PathBuf::from(&src).exists() {
        let msg = format!("local_sync: SYNC_SRC '{}' が見つかりません。スキップします。", src);
        if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
        eprintln!("{}", msg);
        return;
    }
    if let Err(e) = fs::create_dir_all(&dst) {
        let msg = format!("local_sync: SYNC_DST 作成失敗 ({}): {}", dst, e);
        if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
        eprintln!("{}", msg);
        return;
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

    let msg = "local_sync: 完了".to_string();
    if let Some(s) = sender { let _ = s.send(format!("MSG:{}", msg)); }
    println!("{}", msg);
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

#[cfg(feature = "gui")]
fn get_available_profiles(_settings_dir: &str, current_val: &str) -> Vec<String> {
    let mut profiles = Vec::new();
    if !current_val.is_empty() {
        profiles.push(current_val.to_string());
    }
    
    // 1. APPDATA 以下の既存の QGIS プロファイルを検索する
    // QGIS の実際のプロファイルは通常 `%APPDATA%/QGIS/QGISx/profiles/<name>` にあるため
    // まず `profiles` サブフォルダを優先して列挙し、存在しなければ互換性のために直下を列挙する。
    for p in qgis_launcher::get_qgis_profile_paths() {
        let probe = p.join("profiles");
        if probe.exists() {
            if let Ok(entries) = fs::read_dir(&probe) {
                for entry in entries.flatten() {
                    if let Ok(ft) = entry.file_type() {
                        if ft.is_dir() {
                            if let Ok(name) = entry.file_name().into_string() {
                                if !profiles.contains(&name) {
                                    profiles.push(name);
                                }
                            }
                        }
                    }
                }
            }
        } else {
            if let Ok(entries) = fs::read_dir(&p) {
                for entry in entries.flatten() {
                    if let Ok(ft) = entry.file_type() {
                        if ft.is_dir() {
                            if let Ok(name) = entry.file_name().into_string() {
                                // 直下を読む場合、誤って 'profiles' というディレクトリ名を
                                // プロファイル名として表示してしまうことがあるため除外する。
                                if name.eq_ignore_ascii_case("profiles") {
                                    continue;
                                }
                                if !profiles.contains(&name) {
                                    profiles.push(name);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // NOTE: Only enumerate immediate subfolders under `%APPDATA%/QGIS/QGISx/profiles`.
    // Do not fallback to listing `%APPDATA%/QGIS/QGISx` itself and do not scan
    // the distribution `settings_dir/profiles` here — this keeps the list limited
    // to actual QGIS profile folders managed by the installation.
    for p in qgis_launcher::get_qgis_profile_paths() {
        let probe = p.join("profiles");
        if probe.exists() {
            if let Ok(entries) = fs::read_dir(&probe) {
                for entry in entries.flatten() {
                    if let Ok(ft) = entry.file_type() {
                        if ft.is_dir() {
                            if let Ok(name) = entry.file_name().into_string() {
                                if !profiles.contains(&name) {
                                    profiles.push(name);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    profiles
}

#[cfg(feature = "gui")]
/// ファイルの絶対パスから GUI 表示名「親フォルダ名 - ファイル名」を生成する。
/// ルートレベル（C:\ 直下など）の場合はドライブ文字を親名として使用。
fn display_name_for(abs_path: &str) -> String {
    let pb = PathBuf::from(abs_path);
    let fname = match pb.file_name().and_then(|n| n.to_str()) {
        Some(s) => s.to_string(),
        None => return abs_path.to_string(),
    };
    let parent = match pb.parent() {
        Some(p) => p,
        None => return fname,
    };
    // 通常フォルダ: 末尾コンポーネント名を使用
    if let Some(dir_name) = parent.file_name().and_then(|n| n.to_str()) {
        return format!("{} - {}", dir_name, fname);
    }
    // ルート（C:\ など）: ドライブ文字を使用
    let root = parent.to_str().unwrap_or("").trim_end_matches(['/', '\\']);
    if !root.is_empty() {
        format!("{} - {}", root, fname)
    } else {
        fname
    }
}

#[cfg(feature = "gui")]
/// GUI 用プロジェクト一覧を返す。
/// 戻り値: (表示名, 実絶対パス) のペアのリスト
/// - 拡張子 .qgs/.qgz → ファイル指定: 存在すれば1エントリ追加
/// - それ以外          → フォルダ指定: 直下の .qgs/.qgz を列挙して追加
fn get_available_projects(project_root: &str, current_val: &Vec<String>) -> Vec<(String, String)> {
    let mut projects: Vec<(String, String)> = Vec::new();
    let base = PathBuf::from(project_root);

    for path_str in current_val {
        let path_str = path_str.trim();
        if path_str.is_empty() {
            continue;
        }

        let pb = PathBuf::from(path_str);
        let lower = path_str.to_lowercase();
        let is_qgis_file = lower.ends_with(".qgs") || lower.ends_with(".qgz");

        // 絶対パスはそのまま、相対パスはランチャー実行フォルダ基準で解決
        let effective = if pb.is_absolute() { pb.clone() } else { base.join(&pb) };

        if is_qgis_file {
            // ファイル指定: 存在すれば追加
            if effective.is_file() {
                let actual = effective.to_string_lossy().to_string();
                let display = display_name_for(&actual);
                if !projects.iter().any(|(_, a)| a == &actual) {
                    projects.push((display, actual));
                }
            }
        } else {
            // フォルダ指定: 直下の .qgs/.qgz を列挙
            if effective.is_dir() {
                if let Ok(entries) = fs::read_dir(&effective) {
                    let mut file_entries: Vec<_> = entries.flatten()
                        .filter(|e| e.file_type().map(|ft| ft.is_file()).unwrap_or(false))
                        .filter(|e| {
                            let name = e.file_name().to_string_lossy().to_lowercase();
                            name.ends_with(".qgs") || name.ends_with(".qgz")
                        })
                        .collect();
                    file_entries.sort_by_key(|e| e.file_name());
                    for entry in file_entries {
                        let actual = effective.join(entry.file_name()).to_string_lossy().to_string();
                        let display = display_name_for(&actual);
                        if !projects.iter().any(|(_, a)| a == &actual) {
                            projects.push((display, actual));
                        }
                    }
                }
            }
        }
    }
    projects
}

#[cfg(feature = "gui")]
/// コンボボックスを更新し、プロジェクトの (表示名, 実パス) マッピングを返す
fn update_choices(
    profile_in: &mut misc::InputChoice,
    project_in: &mut misc::InputChoice,
    project_root: &str,
    current_profile: &str,
    current_project: &Vec<String>,
) -> Vec<(String, String)> {
    profile_in.clear();
    for p in get_available_profiles(project_root, current_profile) {
        profile_in.add(&p);
    }
    project_in.clear();
    let project_map = get_available_projects(project_root, current_project);
    for (display, _) in &project_map {
        project_in.add(display);
    }
    project_map
}

#[cfg(feature = "gui")]
fn run_gui() {
    let app = app::App::default();

    // --- ウィンドウ ---
    let version = env!("CARGO_PKG_VERSION");
    let title_text = format!("QGIS Launcher v{}", version);
    let mut wind = window::Window::new(200, 150, 500, 360, title_text.as_str());
    wind.set_color(enums::Color::from_rgb(245, 245, 245));

    // --- タイトル ---
    let mut title = frame::Frame::new(0, 8, 500, 30, "");
    title.set_label(&title_text);
    title.set_label_size(18);
    title.set_label_color(enums::Color::from_rgb(40, 80, 160));

    // --- ラベル + 入力フィールド (x=20, 各行 y を固定) ---
    let lw = 120; // ラベル幅
    let iw = 340; // 入力幅
    let lx = 20;
    let ix = lx + lw + 8;
    let row_h = 28;

    let y1 = 52;
    let mut profile_label = frame::Frame::new(lx, y1, lw, row_h, "Profile:");
    profile_label.set_align(Align::Right | Align::Inside);
    profile_label.set_label_size(13);
    let mut profile_in = misc::InputChoice::new(ix, y1, iw, row_h, "");

    let y2 = y1 + row_h + 14;
    let mut project_label = frame::Frame::new(lx, y2, lw, row_h, "Project Path:");
    project_label.set_align(Align::Right | Align::Inside);
    project_label.set_label_size(13);
    let mut project_in = misc::InputChoice::new(ix, y2, iw, row_h, "");

    // Project File Version を Project Path の直下に配置
    let y3 = y2 + row_h + 14;
    let mut proj_ver_label = frame::Frame::new(lx, y3, lw, row_h, "Project File Version:");
    proj_ver_label.set_align(Align::Right | Align::Inside);
    proj_ver_label.set_label_size(13);
    let mut proj_ver_frame = frame::Frame::new(ix, y3, iw, row_h, "");
    proj_ver_frame.set_label_size(13);

    // QGIS Version はその下に置く
    let y3b = y3 + row_h + 14;
    let mut version_label = frame::Frame::new(lx, y3b, lw, row_h, "QGIS Version:");
    version_label.set_align(Align::Right | Align::Inside);
    version_label.set_label_size(13);
    let mut version_in = misc::InputChoice::new(ix, y3b, iw, row_h, "");

    let y4 = y3b + row_h + 14;
    let mut role_label = frame::Frame::new(lx, y4, lw, row_h, "User Role:");
    role_label.set_align(Align::Right | Align::Inside);
    role_label.set_label_size(13);
    let mut role_in = misc::InputChoice::new(ix, y4, iw, row_h, "");
    role_in.add("Viewer");
    role_in.add("Editor");
    role_in.add("Administrator");

    // --- 区切り線 ---
    let sep_y = y4 + row_h + 14;
    let mut sep = frame::Frame::new(20, sep_y, 460, 2, "");
    sep.set_frame(enums::FrameType::ThinDownBox);

    // --- ステータス ---
    let status_y = sep_y + 8;
    let mut status = frame::Frame::new(20, status_y, 460, 22, "");
    status.set_align(Align::Center | Align::Inside);
    status.set_label_size(12);
    status.set_label_color(enums::Color::from_rgb(100, 100, 100));

    // --- ボタン ---
    let btn_y = status_y + 28;
    let btn_w = 140;
    let btn_h = 36;
    let gap = 12;
    let total_w = btn_w * 3 + gap * 2;
    let left = (500 - total_w) / 2; // 中央配置の左端
    let mut reset_btn = button::Button::new(left, btn_y, btn_w, btn_h, "Reset Profiles");
    let mut update_btn = button::Button::new(left + btn_w + gap, btn_y, btn_w, btn_h, "Update");
    let mut launch_btn = button::Button::new(left + (btn_w + gap) * 2, btn_y, btn_w, btn_h, "Launch QGIS");
    // 起動処理が完了するまで Launch / Update を押せないようにする
    launch_btn.deactivate();
    update_btn.deactivate();

    wind.end();
    wind.show();

    // initial values
    let settings_dir = get_default_settings_dir();
    let settings = get_current_settings(&settings_dir);
    // resolved settings dir (same logic as main)
    let resolved_settings_dir = {
        let p = get_settings_path(&settings_dir);
        p.parent().map(|d| d.to_string_lossy().to_string()).unwrap_or_else(|| settings_dir.clone())
    };

    // 設定内の project_root があればそれを優先して使用
    let project_root_dir = compute_project_root(&settings, &resolved_settings_dir);
    // 起動時: ドライブ割当てやプロファイル配布をバックグラウンドで実行し、
    // GUI で進捗モーダルを表示する。既定の初期表示は即時に行い、完了時に再読み込みする。
    let (s_start, r_start) = std::sync::mpsc::channel::<String>();
    let mut pwin = window::Window::new(220, 180, 360, 120, "Initializing...");
    let mut pframe = frame::Frame::new(12, 12, 336, 24, "Preparing startup tasks...");
    let mut pbar = Progress::new(12, 44, 336, 20, "");
    pbar.set_maximum(100.0);
    pbar.set_minimum(0.0);
    pbar.set_value(0.0);
    pwin.show();

    // クローンして UI スレッドで更新できるようにする
    let mut profile_in_for_startup = profile_in.clone();
    let mut project_in_for_startup = project_in.clone();
    let mut status_for_startup = status.clone();
    let mut launch_btn_for_startup = launch_btn.clone();
    let mut update_btn_for_startup = update_btn.clone();
    // クローンして move に備える（クロージャが settings を動かさないようにする）
    let settings_profile_clone = settings.profile.clone();
    let settings_project_path_clone = settings.project_path.clone();
    let project_root_for_closure = project_root_dir.clone();

    // バックグラウンドで mount/copy を実行
    let sd = project_root_dir.clone();
    let settings_for_thread = settings.clone();
    let sync_config_dir = resolved_settings_dir.clone();
    std::thread::spawn(move || {
        let _ = s_start.send("MSG:Start".to_string());
        // KASUGAI/yr-qgis-launcher 方式のローカル自動同期
        run_local_sync(&settings_for_thread, &sync_config_dir, Some(&s_start));
        // SUBST / robocopy
        mount_drive_mappings(&settings_for_thread.drive_mappings, &settings_for_thread, Some(&s_start));
        // プロファイル配布
        copy_profiles_at_startup(&sd, Some(&s_start));
        let _ = s_start.send("DONE".to_string());
    });

    // 初期表示: まず既存情報で選択肢を埋める
    let project_map = update_choices(&mut profile_in, &mut project_in, &project_root_dir, &settings_profile_clone, &settings_project_path_clone);
    // クロージャ用にクローンを用意（move しても元を保持するため）
    let settings_profile_for_closure = settings_profile_clone.clone();
    let settings_project_path_for_closure = settings_project_path_clone.clone();
    // UI スレッドでチャネルをポーリングして進捗と完了を処理
    app::add_idle3(move |_| {
        while let Ok(msg) = r_start.try_recv() {
            if msg == "DONE" {
                pframe.set_label("Initialization complete.");
                pframe.redraw();
                pbar.set_value(100.0);
                pbar.redraw();
                pwin.hide();
                // 初期化完了: Launch / Update ボタンを有効化
                launch_btn_for_startup.activate();
                update_btn_for_startup.activate();
                // 完了時に選択肢を再読み込み
                let _ = update_choices(&mut profile_in_for_startup, &mut project_in_for_startup, &project_root_for_closure, &settings_profile_for_closure, &settings_project_path_for_closure);
                status_for_startup.set_label("Initialization complete.");
                status_for_startup.redraw();
            } else if msg.starts_with("ERR:") {
                let e = msg.trim_start_matches("ERR:");
                pframe.set_label(&format!("Init failed: {}", e));
                pframe.redraw();
                pwin.hide();
                status_for_startup.set_label(&format!("Init failed: {}", e));
                status_for_startup.redraw();
            } else if msg.starts_with("PROG:") {
                if let Ok(v) = msg[5..].parse::<f64>() { pbar.set_value(v); pbar.redraw(); }
            } else if msg.starts_with("MSG:") {
                let m = &msg[4..];
                pframe.set_label(m);
                pframe.redraw();
            }
        }
    });
    role_in.set_value(settings.userrole.as_deref().unwrap_or("Viewer"));
    profile_in.set_value(&settings_profile_clone);
    // 初期表示: current_project（前回選択）を優先し、なければ project_path[0] を使用
    {
        let init_raw = settings.current_project.as_deref()
            .filter(|s| !s.is_empty())
            .or_else(|| settings.project_path.first().map(|s| s.as_str()));
        if let Some(first_raw) = init_raw {
            let first_pb = PathBuf::from(first_raw);
            let first_effective = if first_pb.is_absolute() {
                first_pb.to_string_lossy().to_string()
            } else {
                PathBuf::from(&project_root_dir).join(first_raw).to_string_lossy().to_string()
            };
            let display = project_map.iter()
                .find(|(_, actual)| *actual == first_effective)
                .or_else(|| {
                    let prefix_s = format!("{}/",  first_effective.trim_end_matches(['/', '\\']));
                    let prefix_b = format!("{}\\", first_effective.trim_end_matches(['/', '\\']));
                    project_map.iter().find(|(_, actual)| {
                        actual.starts_with(&prefix_s) || actual.starts_with(&prefix_b)
                    })
                })
                .map(|(d, _)| d.clone())
                .unwrap_or_else(|| display_name_for(&first_effective));
            project_in.set_value(&display);
        } else {
            project_in.set_value("");
        }
    }

    // バージョン解析キャッシュを先に作成し、プロジェクトのバージョンを取得してから
    // QGIS 実行ファイル候補を列挙することで、初期選択に反映できるようにする。
    let version_cache: VersionCache = Arc::new(Mutex::new(std::collections::HashMap::new()));
    // 初期表示用の選択中プロジェクトを解決して、バージョンを先に取得しておく
    let initial_display = project_in.value().unwrap_or_default();
    let initial_actual = project_map.iter()
        .find(|(d, _)| d == &initial_display)
        .map(|(_, a)| a.clone())
        .unwrap_or(initial_display.clone());
    let initial_project_version = if !initial_actual.is_empty() {
        let v = get_project_version_cached(&initial_actual, &version_cache);
        v
    } else { None };

    let available_versions = get_available_qgis_versions();
    for (name, _) in &available_versions {
        version_in.add(name);
    }

    

    // 優先ルール:
    // 1) settings.qgis_executable が指定されていればそれを表示
    // 2) それ以外でプロジェクトバージョンが取得でき、マッチする候補があればそれを初期選択
    // 3) どれもなければ最初の候補
    // まず設定値／候補のいずれかを表示
    if let Some(exe) = &settings.qgis_executable {
        let exe_pb = PathBuf::from(exe);
        if exe_pb.exists() {
            if let Some((name, _)) = available_versions.iter().find(|(_, path)| path == exe) {
                version_in.set_value(name);
            } else {
                version_in.set_value(exe);
            }
        } else {
            // 設定に残っている実行ファイルのパスが存在しない場合は無視する
            if let Some((name, _)) = available_versions.first() {
                version_in.set_value(name);
            }
        }
    } else if let Some((name, _)) = available_versions.first() {
        version_in.set_value(name);
    }

    // プロジェクトバージョンが得られている場合、保存済み選択がプロジェクトの major を含まない
    // 場合は自動選択で上書きする
    if let Some(ver) = &initial_project_version {
        if let Some((match_name, _)) = find_matching_available_for_project(ver, &available_versions) {
            let proj_major = ver.split('.').next().unwrap_or("").to_lowercase();
            let current_sel = version_in.value().unwrap_or_default();
            let current_sel_major = extract_major(&current_sel.to_lowercase()).unwrap_or_default();
            if current_sel.is_empty() || current_sel_major != proj_major {
                version_in.set_value(&match_name);
            }
        }
    }

    // プロジェクト選択が変わったとき、選択された1つだけを解析してバージョン表示を更新する。
    // 解析は最小限: 選択されたプロジェクトファイル1つのみを対象にする。
    {
        let project_map_for_closure = project_map.clone();
        let _project_map_for_init = project_map.clone();
        let mut project_in_for_closure = project_in.clone();
        let mut proj_ver_for_closure = proj_ver_frame.clone();
        let mut proj_ver_for_init = proj_ver_frame.clone();
        let cache_for_closure = version_cache.clone();

        let available_versions_for_closure = available_versions.clone();
        let mut version_in_for_closure = version_in.clone();
        project_in_for_closure.set_callback(move |w| {
            let display = w.value().unwrap_or_default();
            let actual = project_map_for_closure.iter()
                .find(|(d, _)| d == &display)
                .map(|(_, a)| a.clone())
                .unwrap_or(display.clone());

            if actual.to_lowercase().ends_with(".qgz") || actual.to_lowercase().ends_with(".qgs") {
                        if let Some(ver) = get_project_version_cached(&actual, &cache_for_closure) {
                        proj_ver_for_closure.set_label(&ver);
                        if let Some((name, _)) = find_matching_available_for_project(&ver, &available_versions_for_closure) {
                            let proj_major = ver.split('.').next().unwrap_or("").to_lowercase();
                            let current_sel = version_in_for_closure.value().unwrap_or_default();
                            let current_sel_major = extract_major(&current_sel.to_lowercase()).unwrap_or_default();
                            if current_sel_major != proj_major {
                                version_in_for_closure.set_value(&name);
                            }
                        }
                    } else {
                        proj_ver_for_closure.set_label("");
                    }
            } else {
                proj_ver_for_closure.set_label("");
            }
        });

        // 初期表示用に一度ラベルをセットしておく（先に取得済みの initial_project_version を使用）
        if let Some(ver) = &initial_project_version {
            proj_ver_for_init.set_label(ver);
        }
    }

    // Reset
    {
        let _profile_in = profile_in.clone();
        let _project_in = project_in.clone();
        let status = status.clone();
        // project_root_dir を優先して使用する。未指定時は resolved_settings_dir にフォールバック。
        // これにより起動時の copy_profiles_at_startup と同じパスから配布プロファイルを参照できる。
        let reset_profiles_dir = project_root_dir.clone();
        reset_btn.set_callback(move |_| {
            // FLTK チャネルでバックグラウンドの処理からメッセージを受け取り UI を更新する
            let (s, r) = std::sync::mpsc::channel::<String>();

            // 進捗ウィンドウ
            let mut pwin = window::Window::new(220, 180, 360, 120, "Reset Profiles");
            let mut pframe = frame::Frame::new(12, 12, 336, 24, "Preparing...");
            let mut pbar = Progress::new(12, 44, 336, 20, "");
            pbar.set_maximum(100.0);
            pbar.set_minimum(0.0);
            pbar.set_value(0.0);
            pwin.show();

            // バックグラウンドで削除・再構築を実行
            let sd = reset_profiles_dir.clone();
            std::thread::spawn(move || {
                // 送信用ユーティリティ
                let _ = s.send("MSG:Start".to_string());
                let res = reset_profiles_with_report(&sd, &s);
                match res {
                    Ok(_) => { let _ = s.send("DONE".to_string()); }
                    Err(e) => { let _ = s.send(format!("ERR:{}", e)); }
                }
            });

            // UI スレッドでチャネルをポーリングして表示を更新
            let mut status_for_idle = status.clone();
            app::add_idle3(move |_| {
                while let Ok(msg) = r.try_recv() {
                    if msg == "DONE" {
                        pframe.set_label("Profiles reset and rebuilt.");
                        pframe.redraw();
                        pbar.set_value(100.0);
                        pbar.redraw();
                        pwin.hide();
                        // メインウィンドウのステータス表示を更新
                        status_for_idle.set_label("Profiles reset and rebuilt.");
                        status_for_idle.redraw();
                    } else if msg.starts_with("ERR:") {
                        let e = msg.trim_start_matches("ERR:");
                        pframe.set_label(&format!("Reset failed: {}", e));
                        pframe.redraw();
                        pwin.hide();
                        status_for_idle.set_label(&format!("Reset failed: {}", e));
                        status_for_idle.redraw();
                    } else if msg.starts_with("PROG:") {
                        if let Ok(v) = msg[5..].parse::<f64>() { pbar.set_value(v); pbar.redraw(); }
                    } else if msg.starts_with("MSG:") {
                        let m = &msg[4..];
                        pframe.set_label(m);
                        pframe.redraw();
                    }
                }
            });
        });
    }

    // Update
    {
        let settings = settings.clone();
        let sync_config_dir = resolved_settings_dir.clone();
        let status = status.clone();
        let mut reset_btn_outer = reset_btn.clone();
        let mut launch_btn_outer = launch_btn.clone();
        update_btn.set_callback(move |update_btn_self| {
            let (s, r) = std::sync::mpsc::channel::<String>();

            // 進捗ウィンドウ
            let mut pwin = window::Window::new(220, 180, 360, 120, "Update");
            let mut pframe = frame::Frame::new(12, 12, 336, 24, "Updating local files...");
            let mut pbar = Progress::new(12, 44, 336, 20, "");
            pbar.set_maximum(100.0);
            pbar.set_minimum(0.0);
            pbar.set_value(0.0);
            pwin.show();

            // 操作重複防止のためボタンを無効化
            let reset_was_active = reset_btn_outer.active();
            let launch_was_active = launch_btn_outer.active();
            let update_was_active = update_btn_self.active();
            reset_btn_outer.deactivate();
            update_btn_self.deactivate();
            launch_btn_outer.deactivate();

            // idle ハンドラ用にクローンを作成
            let mut reset_btn_for_idle = reset_btn_outer.clone();
            let mut update_btn_for_idle = update_btn_self.clone();
            let mut launch_btn_for_idle = launch_btn_outer.clone();
            let mut status_for_idle = status.clone();

            // バックグラウンドでローカル同期を実行
            let settings = settings.clone();
            let sync_config_dir = sync_config_dir.clone();
            std::thread::spawn(move || {
                let _ = s.send("MSG:Start".to_string());
                run_local_sync(&settings, &sync_config_dir, Some(&s));
                let _ = s.send("DONE".to_string());
            });

            // UI スレッドでチャネルをポーリングして進捗と完了を処理
            app::add_idle3(move |_| {
                while let Ok(msg) = r.try_recv() {
                    if msg == "DONE" {
                        pframe.set_label("Update complete.");
                        pframe.redraw();
                        pbar.set_value(100.0);
                        pbar.redraw();
                        pwin.hide();
                        if reset_was_active { reset_btn_for_idle.activate(); }
                        if launch_was_active { launch_btn_for_idle.activate(); }
                        if update_was_active { update_btn_for_idle.activate(); }
                        status_for_idle.set_label("Update complete.");
                        status_for_idle.redraw();
                    } else if msg.starts_with("ERR:") {
                        let e = msg.trim_start_matches("ERR:");
                        pframe.set_label(&format!("Update failed: {}", e));
                        pframe.redraw();
                        pwin.hide();
                        if reset_was_active { reset_btn_for_idle.activate(); }
                        if launch_was_active { launch_btn_for_idle.activate(); }
                        if update_was_active { update_btn_for_idle.activate(); }
                        status_for_idle.set_label(&format!("Update failed: {}", e));
                        status_for_idle.redraw();
                    } else if msg.starts_with("PROG:") {
                        if let Ok(v) = msg[5..].parse::<f64>() { pbar.set_value(v); pbar.redraw(); }
                    } else if msg.starts_with("MSG:") {
                        let m = &msg[4..];
                        pframe.set_label(m);
                        pframe.redraw();
                    }
                }
            });
        });
    }

    // Launch
    {
        let profile_in = profile_in.clone();
        let project_in = project_in.clone();
        let version_in = version_in.clone();
        let role_in = role_in.clone();
        let _status = status.clone();
        let available_versions = available_versions.clone();
        // 表示名→実パスのマッピングをクロージャにムーブ
        let project_map = project_map.clone();
        launch_btn.set_callback(move |_| {
            let project_display = project_in.value().unwrap_or_default();
            let profile_val = profile_in.value().unwrap_or_default();
            let version_val = version_in.value().unwrap_or_default();
            let role_val = role_in.value().unwrap_or_else(|| "Viewer".to_string());
            
            let exe_path = available_versions.iter()
                .find(|(name, _)| name == &version_val)
                .map(|(_, path)| path.clone())
                .unwrap_or(version_val.clone());

            // 表示名から実パスを解決（手入力の場合はそのまま使用）
            let project_actual = project_map.iter()
                .find(|(display, _)| display == &project_display)
                .map(|(_, actual)| actual.clone())
                .unwrap_or_else(|| project_display.clone());

            // 設定の保存（project_path は JSON を変更しない — 選択プロジェクトは current_project に保存）
            let mut current = get_current_settings(&settings_dir);
            current.profile = profile_val.clone();
            // current.project_path はそのまま維持（JSONのプロジェクト一覧を上書きしない）
            current.qgis_executable = Some(exe_path.clone());
            current.userrole = Some(role_val.clone());
            current.current_project = Some(project_actual.clone());
            let _ = save_settings(&settings_dir, &current);

            // 今回選択されたプロジェクトのみを QGIS に渡す
            let selected_project = vec![project_actual.clone()];
            launch_qgis(&profile_val, &selected_project, &project_root_dir, &exe_path, &role_val);
            // QGIS 起動後にランチャーを終了
            std::process::exit(0);
        });
    }

    app.run().unwrap();
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
    let settings = get_current_settings(&settings_dir);

    // get_settings_path と同じフォールバックロジックで実際の settings_dir を解決する
    let resolved_settings_dir = {
        let p = get_settings_path(&settings_dir);
        p.parent().map(|d| d.to_string_lossy().to_string()).unwrap_or_else(|| settings_dir.clone())
    };

    // 設定内の project_root があればそれを解決して使用
    let project_root_dir = compute_project_root(&settings, &resolved_settings_dir);

    let profile_to_use = if !settings.profile.trim().is_empty() {
        settings.profile.clone()
    } else if !args.profile.trim().is_empty() {
        args.profile.clone()
    } else {
        "default".to_string()
    };

    #[cfg(feature = "gui")]
    if !args.cli {
        run_gui();
        return;
    }

    // KASUGAI/yr-qgis-launcher 方式のローカル自動同期（CLI モード）
    run_local_sync(&settings, &resolved_settings_dir, None);

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

    let exe_path = if command_string.starts_with('"') {
        command_string.split('"').nth(1).unwrap_or(&command_string)
    } else {
        command_string.split_whitespace().next().unwrap_or(&command_string)
    };

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

/// EXE 起動時: インストール済みQGISのバージョンを検出し、対応するプロファイルフォルダをコピーする
/// profiles\QGIS3\ → APPDATA\QGIS\QGIS3\
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

    // インストール済みQGISのメジャーバージョンを収集
    let installed = get_available_qgis_versions();
    let mut major_versions: Vec<u32> = installed.iter()
        .filter_map(|(_, exe)| {
            let lower = exe.to_lowercase();
            for major in [4u32, 3u32] {
                let patterns = [
                    format!("qgis {}", major),
                    format!("qgis{}", major),
                    format!("\\{}.", major),
                ];
                if patterns.iter().any(|p| lower.contains(p.as_str())) {
                    return Some(major);
                }
            }
            None
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
#[allow(dead_code)]
fn reset_profiles(settings_dir: &str) -> Result<(), String> {
    let base_profiles = PathBuf::from(settings_dir).join("profiles");
    if !base_profiles.exists() {
        return Err("distribution profiles not found".to_string());
    }

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

    // コピーして再構築
    copy_profiles_at_startup(settings_dir, None);
    Ok(())
}

/// reset_profiles の処理を行いながら `sender` に進捗・メッセージを送る。
fn reset_profiles_with_report(settings_dir: &str, sender: &std::sync::mpsc::Sender<String>) -> Result<(), String> {
    let base_profiles = PathBuf::from(settings_dir).join("profiles");
    if !base_profiles.exists() {
        let _ = sender.send("MSG:distribution profiles not found".to_string());
        return Err("distribution profiles not found".to_string());
    }

    let all_profile_paths = qgis_launcher::get_qgis_profile_paths();
    // 事前に削除対象の数を数えて進捗を出す
    let mut targets = Vec::new();
    for p in &all_profile_paths {
        let probe = p.join("profiles");
        if probe.exists() {
            if let Ok(entries) = fs::read_dir(&probe) {
                for entry in entries.flatten() {
                    if entry.file_type().map(|ft| ft.is_dir()).unwrap_or(false) {
                        targets.push(entry.path());
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
                        targets.push(entry.path());
                    }
                }
            }
        }
    }

    let total = targets.len().max(1) as f64;
    for (i, path) in targets.into_iter().enumerate() {
        let label = format!("Deleting {:?}", path.file_name().unwrap_or_default());
        let _ = sender.send(format!("MSG:{}", label));
        if let Err(e) = fs::remove_dir_all(&path) {
            let _ = sender.send(format!("MSG:failed to remove {:?}: {}", path, e));
        }
        let perc = ((i + 1) as f64) / total * 50.0; // 削除フェーズは0-50%
        let _ = sender.send(format!("PROG:{}", perc));
    }

    // コピー（再構築）開始
    let _ = sender.send("MSG:Rebuilding profiles...".to_string());
    // copy_profiles_at_startup は sender を受け取れるので、ここでは報告用 sender を渡す
    copy_profiles_at_startup(settings_dir, Some(sender));
    let _ = sender.send(format!("PROG:{}", 90.0));

    // 最終処理
    let _ = sender.send("MSG:Finalizing...".to_string());
    let _ = sender.send(format!("PROG:{}", 98.0));
    Ok(())
}

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

/// QGIS 実行パスを元に、ロール用カスタマイズファイルを選択して返す。
/// 挙動:
/// - QGIS4 と推定される場合は `<role>.xml` を最優先で使用し、存在しなければ `<role>.ini` を使用します。
/// - QGIS3（またはそれ以外）の場合は `<role>.ini` を最優先で使用し、存在しなければ `<role>.xml` を使用します。
fn get_role_customization_path(role: &str, qgis_path: &str) -> Option<PathBuf> {
    let exe_dir = env::current_exe().ok()?.parent().map(|d| d.to_path_buf())?;
    let ini_dir = exe_dir.join("ini");

    // 判定: qgis_path による QGIS4 推定
    let q = qgis_path.to_lowercase();
    let looks_like_qgis4 = q.contains("qgis4") || q.contains("qgis 4") || q.contains("qgis-4") || q.contains("qgis40") || q.contains("qgis-qt6");
    if looks_like_qgis4 {
        // QGIS4: 必ず .xml を使用。存在しなければ None を返す（フォールバックなし）。
        let p_xml = ini_dir.join(format!("{}.xml", role));
        if p_xml.exists() { return Some(p_xml); }
        println!("QGIS4 用ロールカスタマイズが見つかりません (期待: {}): dir={:?}", p_xml.display(), ini_dir);
        return None;
    } else {
        // QGIS3: 必ず .ini を使用。存在しなければ None を返す（フォールバックなし）。
        let p_ini = ini_dir.join(format!("{}.ini", role));
        if p_ini.exists() { return Some(p_ini); }
        println!("QGIS3 用ロールカスタマイズが見つかりません (期待: {}): dir={:?}", p_ini.display(), ini_dir);
        return None;
    }
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

    // --customizationfile: QGIS のバージョンに応じて XML/INI を選択して渡す
    let customization_ini: Option<PathBuf> = get_role_customization_path(role, &qgis_path);

    // --globalsettingsfile: userrole を QGIS グローバル変数として渡すための ini を生成
    let global_settings_ini: Option<PathBuf> = write_global_settings_ini(role);

    // 実行フォルダ/ini/startup.py のパスを取得（存在する場合のみ --code に渡す）
    let startup_script: Option<PathBuf> = env::current_exe().ok()
        .and_then(|p| p.parent().map(|d| d.join("ini").join("startup.py")))
        .filter(|p| p.exists());

    // 判定: qgis_path による QGIS4 推定（再利用）
    let q = qgis_path.to_lowercase();
    let is_qgis4 = q.contains("qgis4") || q.contains("qgis 4") || q.contains("qgis-4") || q.contains("qgis40") || q.contains("qgis-qt6");

    // Helper to spawn one process with optional project
    let spawn_with_project = |maybe_project: Option<PathBuf>| {
        let mut cmd = Command::new(&qgis_path);
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
                // QGIS3 向けの互換性: 古い起動スクリプトでは `--project <path>` を使用していた。
                // QGIS4 では位置引数でも可な場合が多いため、QGIS3 では `--project` を明示的に渡す。
                if is_qgis4 {
                    cmd.arg(s);
                } else {
                    cmd.arg("--project").arg(s);
                }
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

type VersionCache = Arc<Mutex<std::collections::HashMap<String, (SystemTime, String)>>>;

fn get_project_version_cached(path: &str, cache: &VersionCache) -> Option<String> {
    let key = path.to_string();
    let mtime = std::fs::metadata(path).and_then(|m| m.modified()).ok();

    // check cache
    {
        let lock = cache.lock().unwrap();
        if let Some((cached_mtime, ver)) = lock.get(&key) {
            if let Some(m) = mtime {
                if &m == cached_mtime {
                    return Some(ver.clone());
                }
            } else {
                return Some(ver.clone());
            }
        }
    }

    // compute
    if let Some(ver) = get_project_file_version(path) {
        let mut lock = cache.lock().unwrap();
        lock.insert(key, (mtime.unwrap_or(SystemTime::UNIX_EPOCH), ver.clone()));
        Some(ver)
    } else {
        None
    }
}
