"""qgis_live_driver 自身のAI向けブリッジ。

ドライバ自身の機能は LiveDriver のコマンド面(pyeval/status/bridge_call等)
として全経路から既に呼べるため、ここでは describe_plugins カタログ用の
自己記述と稼働状態の報告だけを提供する。
"""

import json
import os

_PLUGIN_ID = "qgis_live_driver"

_COMMANDS = [
    {"name": "pyeval", "signature": "pyeval(code)",
     "description": "QGISプロセス内で任意Pythonを実行(iface/QgsProject等にアクセス可)"},
    {"name": "eval", "signature": "eval(code)",
     "description": "WebEngineプラグインのページ内でJS実行(view必須)"},
    {"name": "status", "signature": "status()",
     "description": "ドライバ・ロード中プラグイン・bridge有無の一覧"},
    {"name": "describe_plugins", "signature": "describe_plugins()",
     "description": "全プラグインのAI利用可能機能カタログ(pluginInfo集約)"},
    {"name": "bridge_call", "signature": "bridge_call(plugin_id, method, args)",
     "description": "プラグインのbridgeメソッドを直接呼ぶ"
                    "(bridge未搭載プラグインは汎用アダプタが応答)"},
    {"name": "open_plugin", "signature": "open_plugin(plugin_id)",
     "description": "プラグインをロード+run()で開く"},
    {"name": "reload_plugin", "signature": "reload_plugin(plugin_id)",
     "description": "プラグインを再読み込み(junction配置ならコード即反映)"},
    {"name": "screenshot", "signature": "screenshot(target, path)",
     "description": "地図キャンバス/mainwindow/dockのPNG撮影"},
]


class QgisLiveBridge:
    """QGIS Live Driver の自己記述ブリッジ。

    メソッドはJSON文字列を返す(他プラグインのbridgeと同じ契約)。
    """

    def __init__(self, plugin):
        self._plugin = plugin

    @staticmethod
    def _ok(payload=None):
        obj = {"ok": True}
        if payload:
            obj.update(payload)
        return json.dumps(obj, ensure_ascii=False)

    def pluginInfo(self):
        """describe_plugins カタログ用の標準自己記述。"""
        return self._ok({
            "id": _PLUGIN_ID,
            "name": "QGIS Live Driver",
            "summary": "QGISプロセス内の遠隔制御ハブ。pyeval/status/"
                       "bridge_call/describe_plugins等をファイルJSONL・"
                       "REST・MCPの全経路で提供する。layer_org サービスで"
                       "追加レイヤのグループ整理・命名を標準化できる",
            "when_to_use": [
                "QGIS内部(iface/QgsProject/地物/レイヤ)を直接操作・検査したい",
                "他プラグインの機能をbridge_callで呼び出したい",
                "地図キャンバスやウィンドウのスクリーンショットが欲しい",
                "プラグインのロード・再読み込みを行いたい",
                "取り込んだレイヤをルールでグループ整理・リネームしたい",
            ],
            "invoke": {"type": "command",
                       "note": "bridge_callではなくドライバのコマンド面"
                               "(qgis_pyeval等のMCPツール)を使う",
                       "commands": _COMMANDS},
            "methods": [
                {"name": "pluginInfo", "signature": "pluginInfo()",
                 "description": "この自己記述を返す"},
                {"name": "status", "signature": "status()",
                 "description": "ドライバ稼働状態(live_dir/http_port/pid)"},
                {"name": "deployMode", "signature": "deployMode()",
                 "description": "deployモード(dev/use)と各プラグインの"
                                "配置形態(junction/dir)を返す(読取専用)"},
                {"name": "layerOrgProfiles",
                 "signature": "layerOrgProfiles()",
                 "description": "レイヤ整理プロファイル一覧とアクティブ"
                                "(~/.qgis-live/layer_org/*.json + 同梱)"},
                {"name": "layerOrgRules",
                 "signature": "layerOrgRules(profile=None)",
                 "description": "プロファイルのルール一覧を返す"
                                "(省略時=アクティブ)"},
                {"name": "setLayerOrgProfile",
                 "signature": "setLayerOrgProfile(name)",
                 "description": "アクティブプロファイルを切替(QSettings永続化)"},
                {"name": "organizeLayers",
                 "signature": "organizeLayers(profile=None, dry=False)",
                 "description": "全レイヤをルールで再配置(dry=Trueでプレビュー)"},
                {"name": "placeLayer",
                 "signature": "placeLayer(layer_id=None, ctx=None)",
                 "description": "単一レイヤをルールへ配置"
                                "(省略時=アクティブレイヤ)"},
                {"name": "openAiPanel",
                 "signature": "openAiPanel()",
                 "description": "AIアシスタントパネル(ドック)を開く"},
                {"name": "openConnInfo",
                 "signature": "openConnInfo()",
                 "description": "接続情報ダイアログ(MCP/REST接続先)を開く"},
                {"name": "openDeployMode",
                 "signature": "openDeployMode()",
                 "description": "Deploy Mode切替ダイアログを開く"
                                "(切替はダイアログ上のUI操作)"},
                {"name": "listDevPlugins",
                 "signature": "listDevPlugins()",
                 "description": "ホットリロード対象(junction配置の開発中"
                                "プラグインID)を返す"},
                {"name": "hotReload",
                 "signature": "hotReload(plugin_ids=None)",
                 "description": "開発中プラグインをsys.modules掃除+"
                                "reloadPluginで即再読込(省略時=全対象)"},
                {"name": "remoteControl",
                 "signature": "remoteControl(enabled=None)",
                 "description": "リモート制御(ファイルJSONL/HTTP面)の"
                                "有効状態を取得/設定する"},
            ],
        })

    @staticmethod
    def _err(msg):
        return json.dumps({"ok": False, "error": str(msg)},
                          ensure_ascii=False)

    def status(self):
        """ドライバの稼働状態を返す。"""
        d = self._plugin.driver
        org = getattr(self._plugin, "layer_org", None)
        return self._ok({
            "id": _PLUGIN_ID,
            "pid": os.getpid(),
            "remote_enabled": d is not None,
            "live_dir": getattr(d, "dir", None),
            "http_port": getattr(d, "http_port", None),
            "commands": [c["name"] for c in _COMMANDS],
            "layer_org": (org.active_profile_name()
                          if org is not None else None),
        })

    def deployMode(self):
        """deployモード(dev/use)と各プラグイン配置形態を返す(読取専用)。

        切替は人が行う操作のため読取のみ公開(切替はメニューの
        Deploy Mode ダイアログ、または npm run deploy / deploy:use / deploy:install)。
        """
        try:
            from .mode_switch import deploy_state
            own = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "__init__.py")
            return self._ok(deploy_state(own))
        except Exception as e:
            return self._err(f"deployMode failed: {e}")

    # ---- レイヤ整理(layer_org) ----

    def _org(self):
        return getattr(self._plugin, "layer_org", None)

    def layerOrgProfiles(self):
        """利用可能なレイヤ整理プロファイル一覧とアクティブを返す。"""
        from . import layer_org as lo
        org = self._org()
        return self._ok({
            "profiles": lo.list_profiles(),
            "active": (org.active_profile_name()
                       if org is not None else None),
        })

    def layerOrgRules(self, profile=None):
        """プロファイルのルール一覧を返す(省略時=アクティブ)。"""
        org = self._org()
        if org is None:
            return self._err("layer_org not available")
        desc = org.describe(profile)
        if desc is None:
            return self._err(
                f"profile not found or disabled: "
                f"{profile or org.active_profile_name()}")
        return self._ok(desc)

    def setLayerOrgProfile(self, name):
        """アクティブな整理プロファイルを切り替える(QSettings永続化)。"""
        org = self._org()
        if org is None:
            return self._err("layer_org not available")
        return json.dumps(org.set_active_profile(name),
                          ensure_ascii=False)

    def organizeLayers(self, profile=None, dry=False):
        """プロジェクト内の全レイヤをプロファイルのルールで再配置する。

        dry=True で移動せず適用結果の予定だけを返す(プレビュー)。
        """
        org = self._org()
        if org is None:
            return self._err("layer_org not available")
        rep = org.organize_project(profile_name=profile,
                                   dry=bool(dry))
        return self._ok(rep)

    def placeLayer(self, layer_id=None, ctx=None):
        """単一レイヤを整理ルールへ配置する。

        layer_id 省略時はアクティブレイヤ。ctx は
        {"plugin_id","dataset","resource","format","url"} 等のdict。
        """
        org = self._org()
        if org is None:
            return self._err("layer_org not available")
        from qgis.core import QgsProject
        from qgis.utils import iface
        layer = None
        if layer_id:
            layer = QgsProject.instance().mapLayer(str(layer_id))
        if layer is None:
            layer = iface.activeLayer() if iface is not None else None
        if layer is None:
            return self._err("no layer (pass layer_id or activate one)")
        rep = org.place_all([(layer, dict(ctx or {}))])
        return self._ok(rep)

    # ---- ドライバ自身のUI/運用 ----

    def openAiPanel(self):
        """AIアシスタントパネルを開く。"""
        self._plugin._open_ai_panel()
        panel = getattr(self._plugin, "_ai_panel", None)
        return self._ok({"opened": panel is not None,
                         "visible": bool(panel is not None
                                         and panel.isVisible())})

    def openConnInfo(self):
        """接続情報ダイアログを開く。"""
        self._plugin._open_conn_info()
        return self._ok({"opened": True})

    def openDeployMode(self):
        """Deploy Mode切替ダイアログを開く(切替はUI操作のみ)。"""
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(0, self._plugin._open_mode_dialog)
        return self._ok({"launched": True})

    def listDevPlugins(self):
        """ホットリロード対象(開発モード配置のプラグインID)を返す。"""
        try:
            from .hot_reload import dev_plugin_ids
            own = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "__init__.py")
            return self._ok({"plugin_ids": dev_plugin_ids(own)})
        except Exception as e:
            return self._err(f"dev_plugin_ids failed: {e}")

    def hotReload(self, plugin_ids=None):
        """開発中プラグインを再読込する(省略時=全対象、driverは最後)。

        junction配置(repo優先)のみ対象。reload_pluginコマンドより
        sys.modules掃除込みの完全再読込になる。
        """
        try:
            from .hot_reload import dev_plugin_ids, reload_plugins
            own = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "__init__.py")
            ids = plugin_ids or dev_plugin_ids(own)
            if isinstance(ids, str):
                ids = [ids]
            reload_plugins(list(ids), notify=None)
            return self._ok({"reloaded": list(ids)})
        except Exception as e:
            return self._err(f"hotReload failed: {e}")

    def remoteControl(self, enabled=None):
        """リモート制御の有効状態を取得/設定する。

        enabled=TrueでファイルJSONL/HTTP面を開始、Falseで停止。
        有効化時の確認ダイアログは出さない(呼出側の判断で実行)。
        注意:Falseにすると以後の遠隔コマンドは届かなくなる。
        """
        p = self._plugin
        if enabled is not None:
            if enabled and p.driver is None:
                p._set_setting(True)
                p._start(p._default_live_base())
                if p.driver is None:
                    p._set_setting(False)
            elif not enabled and p.driver is not None:
                p._set_setting(False)
                p._stop()
            try:
                p._sync_action()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        d = p.driver
        return self._ok({"enabled": d is not None,
                         "live_dir": getattr(d, "dir", None),
                         "http_port": getattr(d, "http_port", None)})
