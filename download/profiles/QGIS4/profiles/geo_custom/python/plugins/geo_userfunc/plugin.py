# -*- coding: utf-8 -*-
"""geo_userfunc プラグイン本体。

ユーザー定義Pythonコードのライブラリ管理プラグイン。

- library.FunctionLibrary: <profile>/python/geo_userfunc/ の *.py を
  AST分類して式エンジン登録・フック配線・マクロ化する
- registry.MacroRegistry: 他プラグインがマクロを登録する共有窓口
  (GeoSuite/layer_org と同じ共有プリミティブ型。plugin.registry として公開)
- bridge.GeoUserfuncBridge: AI/外部制御 I/F(bridge_call 経由)
- manager_dialog: 関数一覧・有効化・編集・再読込・upstream更新の管理UI

他プラグインからの登録は2経路:
  pull: 本プラグインの initGui が plugins[*].register_user_functions(registry)
        規約メソッドを探索して呼ぶ
  push: 他プラグインの initGui が plugins['geo_userfunc'].registry を直接呼ぶ
        (geo_userfunc 未ロード時は各プラグインが自前メニューへフォールバック)
"""

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar
from qgis.core import QgsMessageLog, Qgis

from .bridge import GeoUserfuncBridge
from .i18n_json import install_translator
from .library import FunctionLibrary, PLUGIN_ID
from .registry import MacroRegistry

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_TAG = "geo_userfunc"


def _log(msg, level=Qgis.MessageLevel.Warning):
    QgsMessageLog.logMessage(str(msg), LOG_TAG, level)


class plugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.macro_actions = {}   # macro_id -> QAction(メニュー表示用)
        self.menu_name = "&geo_userfunc"
        self._init_language()

        self.library = FunctionLibrary(iface)
        self.registry = MacroRegistry(iface)
        # qgis_live_driver の bridge_call / describe_plugins 経由で
        # AI・外部制御から使われるAPI (plugins['geo_userfunc'].bridge)
        self.bridge = GeoUserfuncBridge(self)
        self._manager = None

    @staticmethod
    def tr(message):
        return QCoreApplication.translate(PLUGIN_ID, message)

    def _init_language(self):
        """QGISの言語設定に合わせて i18n/<lang>.json を載せる。"""
        self.translator = install_translator(PLUGIN_DIR)

    # ---- GeoSuite共有ツールバー ------------------------------------------
    def _geo_toolbar(self):
        """GeoSuite共有ツールバーをfind-or-createで返す。"""
        tb = self.iface.mainWindow().findChild(QToolBar, "GeoSuite")
        if tb is None:
            tb = self.iface.addToolBar("GeoSuite")
            tb.setObjectName("GeoSuite")
        return tb

    # ---- GUI --------------------------------------------------------------
    def initGui(self):
        manager_action = QAction(
            QIcon(os.path.join(PLUGIN_DIR, "icon.png")),
            self.tr("User function library..."), self.iface.mainWindow())
        manager_action.triggered.connect(self.open_manager)
        self.iface.addPluginToMenu(self.menu_name, manager_action)
        self._geo_toolbar().addAction(manager_action)
        self.actions.append(manager_action)

        # 共有レジストリの変更でマクロメニューを再構築
        self.registry.on_changed(self._sync_macro_menu)

        # ライブラリをロード(式関数登録・フック配線・マクロ収集)
        try:
            self.library.seed()
            self.library.load_all()
        except Exception as e:
            _log("library load failed: {0}".format(e))

        # pull経路: 既ロードの他プラグインが register_user_functions を
        # 持っていれば共有レジストリへ登録させる
        self._discover_plugin_macros()
        self._sync_macro_menu()

    def unload(self):
        self.library.unload_all()
        for action in list(self.macro_actions.values()):
            self.iface.removePluginMenu(self.menu_name, action)
        self.macro_actions = {}
        for action in self.actions:
            self.iface.removePluginMenu(self.menu_name, action)
            self._geo_toolbar().removeAction(action)
        self.actions = []
        if self._manager is not None:
            self._manager.close()
            self._manager = None

    # ---- 他プラグイン連携 -------------------------------------------------
    def _discover_plugin_macros(self):
        """register_user_functions(registry) を持つ他プラグインを探索する。"""
        try:
            from qgis.utils import plugins
        except Exception:
            return
        for pid, p in list(plugins.items()):
            if pid == PLUGIN_ID:
                continue
            fn = getattr(p, "register_user_functions", None)
            if callable(fn):
                try:
                    fn(self.registry)
                except Exception as e:
                    _log("register_user_functions failed ({0}): {1}"
                         .format(pid, e))

    def _sync_macro_menu(self):
        """レジストリ+ライブラリのマクロをメニューへ反映する。"""
        want = {}
        for m in self.registry.entries():
            want[m["id"]] = m["title"]
        for e in self.library.entries.values():
            if e.enabled and e.info and e.info.get("has_main"):
                title = e.info.get("macro_doc") or e.stem
                want["lib." + e.stem] = "{0} [{1}]".format(title, e.file)

        for mid in list(self.macro_actions):
            if mid not in want:
                self.iface.removePluginMenu(
                    self.menu_name, self.macro_actions.pop(mid))
        for mid, title in want.items():
            if mid in self.macro_actions:
                continue
            action = QAction(title, self.iface.mainWindow())
            action.triggered.connect(
                lambda checked=False, m=mid: self.run_macro(m))
            self.iface.addPluginToMenu(self.menu_name, action)
            self.macro_actions[mid] = action

    def run_macro(self, macro_id):
        """メニューからのマクロ実行。"""
        context = self.library.make_context()
        if macro_id.startswith("lib."):
            return self.library.run_macro(macro_id[4:], context)
        return self.registry.run(macro_id, context)

    # ---- 管理ダイアログ -----------------------------------------------------
    def open_manager(self):
        """管理ダイアログを開く(既にあれば前面に出す)。"""
        from .manager_dialog import GeoUserfuncManagerDialog

        if self._manager is None:
            self._manager = GeoUserfuncManagerDialog(
                self, self.iface.mainWindow())
        else:
            self._manager.refresh()
        self._manager.show()
        self._manager.raise_()
        self._manager.activateWindow()
        return self._manager
