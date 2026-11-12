"""配布バンドルのプラグインを qgis-plugin リポジトリと同期する。

qgis-plugin/<id> を正本として、
download/profiles/*/profiles/*/python/plugins/<id> へミラーコピーする。
正本の解決順:
  1. KASUGAI_HARNESS_DIR 環境変数 → <dir>/qgis-plugin
  2. <harness>/qgis-plugin/kasugai_qgis 配置（親ディレクトリ名が qgis-plugin）
  3. 兄弟リポジトリ <親>/qgis_live_harness/qgis-plugin（単体 clone 配置）

- 同期対象: バンドル側に既に存在し、かつ正本側に metadata.txt を持つ
  プラグインのみ（サードパーティ製や同梱専用プラグインは触らない）
- 正本の定義: harness git が追跡するファイル。
  untracked なワーキングツリー残留物（__pycache__、実行時キャッシュ、
  プロファイルコピーが junction 越しに注入した旧版ファイル等）は含めない。
  git が使えない環境（単体 clone）では rglob + 除外リストで近似する
- ミラー方式: バンドル側ディレクトリを削除してからコピーするため、
  repo で削除・改名されたファイルはバンドルからも消える

使い方:
    python scripts/sync_bundle_plugins.py           # 同期実行
    python scripts/sync_bundle_plugins.py --check   # 差分確認のみ（変更しない）
"""

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _resolve_harness():
    """(qgis-plugin 正本ディレクトリ, harness ルート) を返す。見つからなければ (None, None)。"""
    env = os.environ.get("KASUGAI_HARNESS_DIR")
    if env and (Path(env) / "qgis-plugin").is_dir():
        return Path(env) / "qgis-plugin", Path(env)
    if ROOT.parent.name == "qgis-plugin":
        return ROOT.parent, ROOT.parent.parent
    qp = ROOT.parent / "qgis_live_harness" / "qgis-plugin"
    if qp.is_dir():
        return qp, qp.parent
    return None, None


PLUGIN_SRC_ROOT, HARNESS_ROOT = _resolve_harness()
PROFILES_ROOT = ROOT / "download" / "profiles"

EXCLUDE_DIRS = {
    ".git", ".github", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", ".idea", ".vscode",
}
EXCLUDE_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    # 実行時キャッシュ（geo_import がプロジェクトフォルダに生成する）
    "ckan_cache.db",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp"}


def is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    name = path.name
    if name in EXCLUDE_FILES or path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return False


def git_tracked_files(src: Path):
    """harness git が src 配下で追跡するファイルの相対パス一覧。

    git が使えない／リポジトリ外なら None。追跡対象が1件も無ければ
    空リスト（= 正本に含めるべきファイルが無い、ではなくフォールバックへ）。
    """
    if HARNESS_ROOT is None:
        return None
    try:
        rel = src.relative_to(HARNESS_ROOT)
    except ValueError:
        return None
    try:
        r = subprocess.run(
            ["git", "-C", str(HARNESS_ROOT), "ls-files", "-z", "--", str(rel)],
            capture_output=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    prefix = rel.as_posix() + "/"
    out = []
    for raw in r.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if raw.startswith(prefix):
            rel = Path(raw[len(prefix):])
            if not is_excluded(rel):
                out.append(rel)
    return out or None


def iter_src_files(src: Path):
    """正本として同梱するファイルの相対パスを列挙する。

    harness git の追跡ファイルを優先し、使えなければ rglob + 除外リスト。
    """
    tracked = git_tracked_files(src)
    if tracked is not None:
        yield from sorted(tracked)
        return
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if is_excluded(rel):
            continue
        if p.is_file() or p.is_symlink():
            yield rel


def read_version(plugin_dir: Path) -> str:
    meta = plugin_dir / "metadata.txt"
    if not meta.exists():
        return "?"
    for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lower().startswith("version"):
            return line.split("=", 1)[1].strip()
    return "?"


def copy_plugin(src: Path, dst: Path):
    """src を dst へミラーコピーする（dst は一旦削除）。"""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    if git_tracked_files(src) is not None:
        # git 追跡ファイルのみ（untracked の残留物は同梱しない）
        for rel in iter_src_files(src):
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, target)
        return

    def ignore(_dir, names):
        out = []
        for n in names:
            p = Path(_dir) / n
            if n in EXCLUDE_DIRS or n in EXCLUDE_FILES or p.suffix.lower() in EXCLUDE_SUFFIXES:
                out.append(n)
        return out

    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)


def diff_summary(src: Path, dst: Path):
    """src 基準で copy/update/delete の件数を数える。"""
    src_files = {rel for rel in iter_src_files(src)}
    dst_files = set()
    if dst.exists():
        for p in dst.rglob("*"):
            if p.is_file():
                dst_files.add(p.relative_to(dst))

    add = src_files - dst_files
    delete = dst_files - src_files
    update = {
        rel for rel in (src_files & dst_files)
        if not filecmp.cmp(src / rel, dst / rel, shallow=False)
    }
    return add, update, delete


def find_bundle_plugin_dirs():
    """バンドル内の python/plugins ディレクトリを列挙する。

    2レイアウト両対応: download/profiles/QGIS<ver>/profiles/<name>/... と
    バージョン別フォルダの無い download/profiles/<name>/...（直下共通）。
    """
    if not PROFILES_ROOT.exists():
        return
    seen = set()
    for plugins_dir in sorted(PROFILES_ROOT.glob("*/profiles/*/python/plugins")):
        seen.add(plugins_dir)
    for plugins_dir in sorted(PROFILES_ROOT.glob("*/python/plugins")):
        seen.add(plugins_dir)
    for plugins_dir in sorted(seen):
        if plugins_dir.is_dir():
            yield plugins_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="差分を表示するだけで変更しない")
    args = parser.parse_args()

    synced = skipped = 0
    found_src = False

    plugin_dirs = find_bundle_plugin_dirs() if PLUGIN_SRC_ROOT is not None else ()
    for plugins_dir in plugin_dirs:
        for dst in sorted(plugins_dir.iterdir()):
            if not dst.is_dir():
                continue
            src = PLUGIN_SRC_ROOT / dst.name
            if not (src / "metadata.txt").exists():
                continue
            found_src = True
            src_ver = read_version(src)
            dst_ver = read_version(dst)
            add, update, delete = diff_summary(src, dst)
            if not add and not update and not delete:
                print(f"  = {dst.name} ({src_ver}) 差分なし")
                skipped += 1
                continue
            print(f"  ~ {dst.name}: {dst_ver} -> {src_ver} "
                  f"(+{len(add)} 変更{len(update)} 削除{len(delete)})")
            if not args.check:
                copy_plugin(src, dst)
            synced += 1

    if not found_src:
        print("同期対象なし: qgis-plugin 正本が見つかりません"
              "（KASUGAI_HARNESS_DIR で harness ルートを指定できます）")
        return 0

    verb = "同期予定" if args.check else "同期完了"
    print(f"{verb}: {synced} プラグイン（差分なし {skipped}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
