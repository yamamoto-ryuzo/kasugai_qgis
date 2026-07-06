use std::env;
use std::path::PathBuf;

/// OS上のQGISプロファイルが保存されている可能性のあるディレクトリパス一覧を取得する
pub fn get_qgis_profile_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Ok(appdata) = env::var("APPDATA") {
        let bases = ["QGIS3", "QGIS4"];
        for base in &bases {
            paths.push(PathBuf::from(&appdata).join("QGIS").join(base));
        }
    }
    paths
}
