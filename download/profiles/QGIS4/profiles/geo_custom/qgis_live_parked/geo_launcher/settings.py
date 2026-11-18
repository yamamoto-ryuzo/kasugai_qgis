# -*- coding: utf-8 -*-
"""geo_launcher の永続設定(QSettings)と定数。"""

import glob
import os

from qgis.PyQt.QtCore import QSettings

_PREFIX = "geo_launcher"

# kasugai_qgis 本体の既定インストール先(installer/setup.nsi の InstallDir)
DEFAULT_EXE = r"C:\kasugai\kasugai_qgis\qgis_launcher.exe"

# GitHub Pages で配信される配布物(kasugai_qgis/update.json の full_url と同じ)
SETUP_URL = ("https://yamamoto-ryuzo.github.io/kasugai_qgis/"
             "public/kasugai_qgis-setup.exe")
DOCS_URL = "https://yamamoto-ryuzo.github.io/kasugai_qgis/"


def _s():
    return QSettings()


def exe_path():
    """設定された qgis_launcher.exe のパス(未設定時は空文字)を返す。"""
    v = _s().value(_PREFIX + "/exe_path", "") or ""
    return str(v)


def set_exe_path(path):
    _s().setValue(_PREFIX + "/exe_path", str(path or ""))


def detect_exe():
    """qgis_launcher.exe の実在パスを返す。見つからなければ None。

    解決順: QSettings の明示指定 → 既定インストール先 →
    C:\\kasugai\\*\\qgis_launcher.exe の glob。
    """
    cand = [exe_path(), DEFAULT_EXE]
    for c in cand:
        if c and os.path.isfile(c):
            return os.path.normpath(c)
    for c in sorted(glob.glob(r"C:\kasugai\*\qgis_launcher.exe")):
        if os.path.isfile(c):
            return os.path.normpath(c)
    return None


def silent_install():
    """セットアップを /S でサイレント実行するか(既定: ON)。

    1クリックでインストールが完走するよう既定は true。
    NSIS ウィザードは待ちが発生するため、設定で明示的に OFF に
    した場合のみ表示する。
    """
    return str(_s().value(_PREFIX + "/silent_install", "true")) != "false"


def set_silent_install(flag):
    _s().setValue(_PREFIX + "/silent_install", "true" if flag else "false")


def current_settings():
    """UI/bridge 表示用の設定スナップショットを返す。"""
    return {
        "exe_path_setting": exe_path(),
        "exe_detected": detect_exe(),
        "silent_install": silent_install(),
        "setup_url": SETUP_URL,
        "docs_url": DOCS_URL,
    }


def save_settings(exe_path_value=None, silent_install_value=None):
    if exe_path_value is not None:
        set_exe_path(exe_path_value)
    if silent_install_value is not None:
        set_silent_install(silent_install_value)
