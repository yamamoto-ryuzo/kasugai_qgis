use std::env;
use std::path::PathBuf;

/// OS上のQGIS4プロファイルが保存されている可能性のあるディレクトリパス一覧を取得する
pub fn get_qgis_profile_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Ok(appdata) = env::var("APPDATA") {
        paths.push(PathBuf::from(&appdata).join("QGIS").join("QGIS4"));
    }
    paths
}
