import argparse
import json
import os
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
ZIP_NAME = f"{PROJECT_NAME}.zip"
DEFAULT_PORT = 8500


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "-B", "--build", action="store_true")
    parser.add_argument("--installer", action="store_true")
    parser.add_argument("--release", action="store_true")
    args, tail = parser.parse_known_args()

    if tail and tail[0] == "--":
        tail = tail[1:]

    is_build = args.build or any(a in ("b", "B") for a in tail)
    extra = [a for a in tail if a not in ("b", "B")]

    if args.release:
        return run_release(extra)
    if is_build:
        rc = cargo_build_release()
        if rc != 0:
            return rc
        rc = build_zip()
        if rc != 0:
            return rc
        return build_installer()
    if args.installer:
        rc = cargo_build_release()
        if rc != 0:
            return rc
        return build_installer()

    return cargo_run(extra)


if __name__ == "__main__":
    sys.exit(main())