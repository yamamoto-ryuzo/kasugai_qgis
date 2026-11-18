# -*- coding: utf-8 -*-
"""geo_launcher を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、geo_driver の
bridge_call コマンド(ファイルJSONL / REST /api/cmd / MCP qgis_bridge_call)
から ``qgis.utils.plugins['geo_launcher'].bridge.<method>(*args)`` が
プロセス内で直接呼ばれる。

各メソッドは JSON 文字列を返す(bridge_call 側で構造化される)。
ドメインエラー(未インストール等)は ``{"ok": false, "error": ...}`` を返し、
予期しない例外は呼び出し元(driver の {"error": traceback})に委ねる。

kasugai_qgis は QGIS を起動すると自動終了する設計のため、bridge は
ランチャー API サーバの起動・維持・中継機能を持たない。
install/uninstall/launch(GUI 窓オープン)に限定される。

例(MCP): qgis_bridge_call pluginId="geo_launcher" method="status"
"""

import inspect
import json

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

from . import launcher, settings


class GeoLauncherBridge:
    """``plugins['geo_launcher'].bridge`` にぶら下げるAI向けAPI。"""

    NAME = "kasugai_qgis ランチャー連携 (geo_launcher)"
    SUMMARY = (
        "Rust/Axum 製の QGIS/QField 起動ランチャー kasugai_qgis を "
        "QGIS 内からインストール/アンインストール/起動する。"
        "未インストールなら GitHub Pages の setup.exe を DL して"
        "インストール実行、インストール済みなら GUI 窓(WebView2)を開き"
        "プロファイル/プロジェクトを選んで QGIS を起動させられる"
        "(起動後ランチャーは自動終了)。この QGIS がランチャー経由で"
        "起動したか(PORTAL_USERROLE)も返す。")
    WHEN_TO_USE = [
        "kasugai_qgis ランチャーがインストールされているか確認したい",
        "kasugai_qgis をインストール(または再インストール)したい",
        "kasugai_qgis をアンインストールしたい",
        "ランチャーの GUI 窓を開いてユーザーに起動操作を任せたい",
        "この QGIS がランチャー経由で起動したか確認したい",
        "ランチャー側の設定(exeパス/サイレント)を確認・変更したい",
    ]
    METHOD_DOCS = {
        "status": {
            "description":
                "インストール状態・バージョン・このQGISの起動経由・"
                "インストーラ進捗・設定値を返す。",
            "example": {"method": "status", "args": []},
        },
        "isInstalled": {
            "description": "qgis_launcher.exe が検出できるか返す。",
            "example": {"method": "isInstalled", "args": []},
        },
        "launch": {
            "description":
                "qgis_launcher.exe を GUI モード(WebView2 窓)で起動する。"
                "startDetached で即時復帰。窓内で「起動」を押すと本体が"
                "新しい QGIS を立てて自動終了する。",
            "example": {"method": "launch", "args": []},
        },
        "install": {
            "description":
                "setup.exe を非同期 DL し、完了後にインストーラーを起動する。"
                "silent=True で /S サイレント実行(既定は設定値)。"
                "進捗は installStatus() で参照。",
            "example": {"method": "install", "args": []},
        },
        "installStatus": {
            "description":
                "インストール処理の状態(phase/received/total/error)を返す。"
                "phase: idle|downloading|running_installer|done|error。",
            "example": {"method": "installStatus", "args": []},
        },
        "uninstall": {
            "description":
                "アンインストーラー(uninstall.exe)を起動する。"
                "silent=True で /S サイレント実行(既定は設定値)。",
            "example": {"method": "uninstall", "args": []},
        },
        "getSettings": {
            "description":
                "プラグイン設定(exeパス/サイレントインストール等)を返す。",
            "example": {"method": "getSettings", "args": []},
        },
        "setSettings": {
            "description":
                "プラグイン設定を保存する。対応キー: exe_path/"
                "silent_install。",
            "example": {"method": "setSettings",
                        "args": [{"silent_install": True}]},
        },
        "openDialog": {
            "description":
                "状態パネル(インストール/アンインストール/起動)を開く。",
            "example": {"method": "openDialog", "args": []},
        },
        "openSettings": {
            "description": "設定ダイアログを開く。",
            "example": {"method": "openSettings", "args": []},
        },
        "openDocs": {
            "description":
                "kasugai_qgis のドキュメントサイトをブラウザで開く。",
            "example": {"method": "openDocs", "args": []},
        },
    }

    def __init__(self, plugin):
        self._plugin = plugin

    # ---------- 内部ヘルパ ----------
    @staticmethod
    def _ok(payload=None):
        obj = {"ok": True}
        if payload:
            obj.update(payload)
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def _err(msg):
        return json.dumps({"ok": False, "error": str(msg)},
                          ensure_ascii=False)

    def _method_catalog(self):
        out = []
        for name in sorted(dir(self)):
            if name.startswith("_") or name == "pluginInfo":
                continue
            fn = getattr(self, name)
            if not callable(fn):
                continue
            doc = inspect.getdoc(fn) or ""
            entry = {
                "name": name,
                "signature": f"{name}{inspect.signature(fn)}",
                "description": doc.split("\n")[0] if doc else "",
            }
            extra = self.METHOD_DOCS.get(name) or {}
            if extra.get("description"):
                entry["description"] = extra["description"]
            if extra.get("example"):
                entry["example"] = extra["example"]
            out.append(entry)
        return out

    # ---------- bridge メソッド(JSON文字列を返す) ----------

    def pluginInfo(self):
        """プラグインの自己記述(id/summary/when_to_use/methods)を返す。"""
        return self._ok({
            "id": "geo_launcher",
            "name": self.NAME,
            "summary": self.SUMMARY,
            "when_to_use": list(self.WHEN_TO_USE),
            "invoke": {"type": "bridge_call",
                       "plugin_id": "geo_launcher",
                       "method": "<method>", "args": []},
            "methods": self._method_catalog(),
            "state": {
                "installed": settings.detect_exe() is not None,
                "launched_via_launcher":
                    launcher.launched_via_role() is not None,
            },
        })

    def status(self):
        """インストール/起動経由/設定の総合状態を返す。"""
        exe = settings.detect_exe()
        return self._ok({
            "installed": exe is not None,
            "exe": exe,
            "version": launcher.exe_version(exe) if exe else None,
            "launched_via_launcher":
                launcher.launched_via_role() is not None,
            "launch_role": launcher.launched_via_role(),
            "installer": self._plugin.installer.status(),
            "settings": settings.current_settings(),
        })

    def isInstalled(self):
        exe = settings.detect_exe()
        return self._ok({"installed": exe is not None, "exe": exe,
                         "version": launcher.exe_version(exe)})

    def launch(self):
        """ランチャーを GUI モード(WebView2 窓)で起動する。"""
        try:
            return self._ok(launcher.launch())
        except launcher.LauncherError as e:
            return self._err(e)

    def install(self, silent=None):
        """setup.exe を DL→インストーラー起動(非同期。installStatus で追跡)。"""
        st = self._plugin.installer.start(silent=silent)
        return self._ok(st)

    def installStatus(self):
        return self._ok(self._plugin.installer.status())

    def uninstall(self, silent=None):
        """アンインストーラーを起動する。"""
        if not launcher.find_uninstaller():
            return self._err("uninstall.exe not found")
        try:
            return self._ok(launcher.uninstall(silent))
        except launcher.LauncherError as e:
            return self._err(e)

    def getSettings(self):
        return self._ok(settings.current_settings())

    def setSettings(self, new_settings=None):
        """設定を保存する(exe_path/silent_install)。"""
        new_settings = dict(new_settings or {})
        allowed = {"exe_path", "silent_install"}
        unknown = [k for k in new_settings if k not in allowed]
        if unknown:
            return self._err(
                "unknown keys: {} (allowed: {})".format(
                    unknown, sorted(allowed)))
        settings.save_settings(
            exe_path_value=new_settings.get("exe_path"),
            silent_install_value=new_settings.get("silent_install"))
        return self._ok({"settings": settings.current_settings()})

    def openDialog(self):
        dlg = self._plugin.open_dialog()
        return self._ok({"opened": dlg is not None})

    def openSettings(self):
        dlg = self._plugin.open_settings()
        return self._ok({"opened": dlg is not None})

    def openDocs(self):
        return self._ok({
            "opened": QDesktopServices.openUrl(QUrl(settings.DOCS_URL)),
            "url": settings.DOCS_URL})
