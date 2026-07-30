import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

APP_NAME = "qgis_launcher"
PROJECT_NAME = "kasugai_qgis"
ROOT = Path(__file__).resolve().parent
DOWNLOAD_DIR = ROOT / "download"
PUBLIC_DIR = ROOT / "public"
INSTALLER_DIR = ROOT / "installer"
CARGO_TOML = ROOT / "Cargo.toml"
NSI_FILE = INSTALLER_DIR / "setup.nsi"
UPDATE_JSON = ROOT / "update.json"
SETTINGS_JSON = DOWNLOAD_DIR / "qgis_settings.json"
ZIP_NAME = f"{PROJECT_NAME}.zip"
UPDATE_EXE_NAME = f"{PROJECT_NAME}-update.exe"
SETUP_EXE_NAME = f"{PROJECT_NAME}-setup.exe"
DEFAULT_PORT = 8500


# ---------------------------------------------------------------------------
# バージョン整合性
#
# 配布物のバージョンがずれると「更新しても実行中バージョンが上がらない」状態になり、
# 更新の無限ループを招く。Cargo.toml のバージョンを唯一の正とし、
# setup.nsi / update.json / qgis_settings.json をビルド時に自動同期する。
# ---------------------------------------------------------------------------


def read_cargo_version():
    text = CARGO_TOML.read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not m:
        raise RuntimeError("Cargo.toml から version を読み取れませんでした")
    return m.group(1)


def set_cargo_version(version):
    text = CARGO_TOML.read_text(encoding="utf-8")
    new_text, n = re.subn(r'(?m)^(version\s*=\s*")[^"]+(")', rf"\g<1>{version}\g<2>", text, count=1)
    if n != 1:
        raise RuntimeError("Cargo.toml の version を書き換えられませんでした")
    CARGO_TOML.write_text(new_text, encoding="utf-8")
    print(f"Cargo.toml: version = {version}")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def sync_nsi_version(version):
    text = NSI_FILE.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'(!define\s+PRODUCT_VERSION\s+")[^"]+(")', rf"\g<1>{version}\g<2>", text, count=1
    )
    if n != 1:
        raise RuntimeError("setup.nsi の PRODUCT_VERSION を書き換えられませんでした")
    if new_text != text:
        NSI_FILE.write_text(new_text, encoding="utf-8")
    print(f"setup.nsi: PRODUCT_VERSION = {version}")


def sync_settings_version(version):
    if not SETTINGS_JSON.exists():
        return
    text = SETTINGS_JSON.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'("kasugai_qgis_version"\s*:\s*")[^"]*(")', rf"\g<1>{version}\g<2>", text, count=1
    )
    if n == 1 and new_text != text:
        SETTINGS_JSON.write_text(new_text, encoding="utf-8")
        print(f"qgis_settings.json: kasugai_qgis_version = {version}")


def sync_update_json(version):
    """ビルド済みインストーラーの実体に合わせて update.json を書き出す。

    version と実際に配布される EXE がずれないよう、必ずインストーラー生成後に呼ぶこと。
    """
    update_exe = PUBLIC_DIR / UPDATE_EXE_NAME
    setup_exe = PUBLIC_DIR / SETUP_EXE_NAME
    if not update_exe.exists() or not setup_exe.exists():
        print("WARNING: インストーラーが見つからないため update.json は更新しません。")
        return 0

    data = {}
    if UPDATE_JSON.exists():
        try:
            data = json.loads(UPDATE_JSON.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    notes = data.get("notes") or ""
    if version not in notes:
        notes = f"Kasugai QGIS Launcher {version}"

    data.update(
        {
            "version": version,
            "url": data.get("url")
            or f"https://yamamoto-ryuzo.github.io/{PROJECT_NAME}/public/{UPDATE_EXE_NAME}",
            "full_url": data.get("full_url")
            or f"https://yamamoto-ryuzo.github.io/{PROJECT_NAME}/public/{SETUP_EXE_NAME}",
            "full": bool(data.get("full", False)),
            "signature": data.get("signature"),
            "sha256": sha256_of(update_exe),
            "full_sha256": sha256_of(setup_exe),
            "notes": notes,
        }
    )
    UPDATE_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"update.json: version = {version} (sha256 を再計算しました)")
    return 0


def verify_release_consistency(version):
    """配布物のバージョン整合性を最終確認する。不一致なら 1 を返す。"""
    errors = []
    nsi = NSI_FILE.read_text(encoding="utf-8")
    m = re.search(r'!define\s+PRODUCT_VERSION\s+"([^"]+)"', nsi)
    if not m or m.group(1) != version:
        errors.append(f"setup.nsi PRODUCT_VERSION={m.group(1) if m else '?'} != {version}")

    if UPDATE_JSON.exists():
        data = json.loads(UPDATE_JSON.read_text(encoding="utf-8"))
        if data.get("version") != version:
            errors.append(f"update.json version={data.get('version')} != {version}")
        update_exe = PUBLIC_DIR / UPDATE_EXE_NAME
        if update_exe.exists() and data.get("sha256") != sha256_of(update_exe):
            errors.append("update.json sha256 が public の更新用 EXE と一致しません")

    if errors:
        print("ERROR: バージョン整合性チェックに失敗しました（更新ループの原因になります）")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"バージョン整合性 OK: {version}")
    return 0


def find_makensis():
    candidates = [
        os.environ.get("NSISDIR"),
        r"C:\nsis",
        r"C:\Program Files\NSIS",
        r"C:\Program Files (x86)\NSIS",
    ]
    for base in candidates:
        if not base:
            continue
        exe = Path(base) / "makensis.exe"
        if exe.exists():
            return str(exe)
    found = shutil.which("makensis")
    return found


def get_port(extra):
    for i, a in enumerate(extra):
        if a == "--port" and i + 1 < len(extra):
            try:
                return int(extra[i + 1])
            except ValueError:
                break
    for src in [ROOT / "qgis_settings.json", DOWNLOAD_DIR / "qgis_settings.json"]:
        if src.exists():
            try:
                with open(src, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("api_server_port"):
                    return int(data["api_server_port"])
            except Exception:
                pass
    return DEFAULT_PORT


def open_browser_when_ready(port):
    url = f"http://127.0.0.1:{port}/"
    health = f"http://127.0.0.1:{port}/health"

    def wait_and_open():
        for _ in range(240):
            try:
                with urllib.request.urlopen(health, timeout=1) as r:
                    if r.getcode() == 200:
                        webbrowser.open(url, new=2)
                        return
            except Exception:
                pass
            time.sleep(0.5)

    threading.Thread(target=wait_and_open, daemon=True).start()


def cargo_run(extra=None):
    extra = extra or []
    if "--server" not in extra:
        extra = ["--server", *extra]
    open_browser_when_ready(get_port(extra))
    return subprocess.run(["cargo", "run", "--", *extra], cwd=ROOT).returncode


def cargo_build_release():
    return subprocess.run(["cargo", "build", "--release"], cwd=ROOT).returncode


def build_zip():
    PUBLIC_DIR.mkdir(exist_ok=True)
    target_exe = ROOT / "target" / "release" / f"{APP_NAME}.exe"
    if not target_exe.exists():
        print(f"ERROR: {target_exe} not found. Run release build first.")
        return 1

    settings = DOWNLOAD_DIR / "qgis_settings.json"
    if not settings.exists():
        print(f"ERROR: {settings} not found.")
        return 1

    zip_path = PUBLIC_DIR / ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()

    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / PROJECT_NAME
        stage.mkdir()

        shutil.copy2(target_exe, stage / f"{APP_NAME}.exe")
        shutil.copy2(settings, stage / "qgis_settings.json")
        for name in [
            "qgislocalsync.config.example",
            "qgis_settings_override.json.example",
            "qgis_settings_USERNAME.json.example",
        ]:
            src = DOWNLOAD_DIR / name
            if src.exists():
                shutil.copy2(src, stage / name)

        for folder in ["ini", "profiles", "ProjectFiles"]:
            src = DOWNLOAD_DIR / folder
            if src.exists():
                shutil.copytree(src, stage / folder, dirs_exist_ok=True)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in stage.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(stage.parent))

    print(f"Done: {zip_path}")
    return 0


def build_installer():
    makensis = find_makensis()
    if not makensis:
        print("WARNING: makensis.exe not found. Skipping installer build.")
        return 0

    target_exe = ROOT / "target" / "release" / f"{APP_NAME}.exe"
    if not target_exe.exists():
        print(f"ERROR: {target_exe} not found. Run release build first.")
        return 1

    settings = DOWNLOAD_DIR / "qgis_settings.json"
    if not settings.exists():
        print(f"ERROR: {settings} not found.")
        return 1

    PUBLIC_DIR.mkdir(exist_ok=True)

    for args in (["/INPUTCHARSET", "UTF8", "setup.nsi"],
                 ["/INPUTCHARSET", "UTF8", "/DUPDATE_ONLY", "setup.nsi"]):
        rc = subprocess.run([makensis, *args], cwd=INSTALLER_DIR).returncode
        if rc != 0:
            print(f"ERROR: makensis failed with code {rc}")
            return rc

    print(f"Done: {PUBLIC_DIR / f'{PROJECT_NAME}-setup.exe'}")
    print(f"Done: {PUBLIC_DIR / f'{PROJECT_NAME}-update.exe'}")
    return 0


def run_release(extra=None):
    extra = extra or []
    if "--server" not in extra:
        extra = ["--server", *extra]
    open_browser_when_ready(get_port(extra))
    exe = ROOT / "target" / "release" / f"{APP_NAME}.exe"
    if not exe.exists():
        print(f"ERROR: {exe} not found. Run release build first.")
        return 1
    return subprocess.run([str(exe), *extra], cwd=ROOT).returncode


def build_release_bundle(with_zip=True):
    """リリース一式をビルドし、バージョン情報を同期する。"""
    version = read_cargo_version()
    print(f"=== リリースビルド {version} ===")
    # インストーラーに焼き込まれるバージョンを先に合わせる
    sync_nsi_version(version)
    sync_settings_version(version)

    rc = cargo_build_release()
    if rc != 0:
        return rc
    if with_zip:
        rc = build_zip()
        if rc != 0:
            return rc
    rc = build_installer()
    if rc != 0:
        return rc
    if not (PUBLIC_DIR / UPDATE_EXE_NAME).exists() or not (PUBLIC_DIR / SETUP_EXE_NAME).exists():
        print("WARNING: インストーラー未生成のため update.json の同期と整合性チェックを省略します。")
        return 0
    # 実際に生成された EXE を元に update.json を更新する
    rc = sync_update_json(version)
    if rc != 0:
        return rc
    return verify_release_consistency(version)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "-B", "--build", action="store_true")
    parser.add_argument("--installer", action="store_true")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--bump", metavar="VERSION",
                        help="バージョンを更新してリリース一式をビルドする（例: --bump 2.1.0）")
    parser.add_argument("--check-version", action="store_true",
                        help="バージョン整合性のみ確認する")
    args, tail = parser.parse_known_args()

    if tail and tail[0] == "--":
        tail = tail[1:]

    is_build = args.build or any(a in ("b", "B") for a in tail)
    extra = [a for a in tail if a not in ("b", "B")]

    if args.check_version:
        return verify_release_consistency(read_cargo_version())
    if args.bump:
        if not re.fullmatch(r"\d+\.\d+\.\d+", args.bump):
            print("ERROR: バージョンは X.Y.Z 形式で指定してください")
            return 1
        set_cargo_version(args.bump)
        return build_release_bundle()
    if args.release:
        return run_release(extra)
    if is_build:
        return build_release_bundle()
    if args.installer:
        return build_release_bundle(with_zip=False)

    return cargo_run(extra)


if __name__ == "__main__":
    sys.exit(main())