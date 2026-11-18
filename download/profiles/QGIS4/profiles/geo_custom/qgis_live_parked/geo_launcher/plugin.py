# -*- coding: utf-8 -*-
"""geo_launcher プラグイン本体。

kasugai_qgis ランチャー(Rust/Axum 製)を QGIS 内から管理する。
ランチャー本体は QGIS を起動すると自動終了する設計なので、
このプラグインの責務はインストール/アンインストールと GUI 窓の
オープンに限定される(API サーバの起動・維持は行わない):

- 未インストール時は GitHub Pages 配布の setup.exe を DL して実行
- インストール済みなら qgis_launcher.exe を GUI モードで起動
  (WebView2 窓でプロファイル/プロジェクトを選んで QGIS 起動→本体終了)
- 起動経由表示: PORTAL_USERROLE でランチャー経由起動かを表示

ツールバー項目は GeoSuite 共有ツールバー(find-or-create)へ集約する。
"""

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar

from . import launcher
from .bridge import GeoLauncherBridge
from .i18n_json import install_translator
from .launcher import Installer

PLUGIN_DIR = os.path.dirname(__file__)


class plugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.menu_name = "&geo_launcher"
        self.toolbar = None
        self._dialog = None
        self._settings_dialog = None
        self.translator = install_translator(PLUGIN_DIR)
        # setup.exe の非同期 DL→インストーラー起動を担う共有インスタンス
        self.installer = Installer(self.iface.mainWindow())
        # geo_driver の bridge_call / describe_plugins 経由で
        # AI・外部制御から使われるAPI (plugins['geo_launcher'].bridge)
        self.bridge = GeoLauncherBridge(self)

    @staticmethod
    def tr(message):
        return QCoreApplication.translate("geo_launcher", message)

    # ---- GUI --------------------------------------------------------------
    def initGui(self):
        icon = QIcon(os.path.join(PLUGIN_DIR, "icon.png"))

        # 共有ツールバー GeoSuite に集約(無ければ作成)。
        # 個別利用=ドライバ非稼働でも可視状態を保証する
        self.toolbar = self.iface.mainWindow().findChild(QToolBar, "GeoSuite")
        if self.toolbar is None:
            self.toolbar = self.iface.addToolBar("GeoSuite")
            self.toolbar.setObjectName("GeoSuite")
        self.toolbar.setVisible(True)

        act = QAction(icon, self.tr("Kasugai QGIS Launcher"),
                      self.iface.mainWindow())
        act.setStatusTip(self.tr(
            "Install/uninstall the kasugai_qgis launcher and open it"))
        act.triggered.connect(self.open_dialog)
        self.toolbar.addAction(act)
        self.iface.addPluginToMenu(self.menu_name, act)
        self.actions.append(act)

        act_launch = QAction(self.tr("Open Launcher"),
                             self.iface.mainWindow())
        act_launch.triggered.connect(self.open_launcher)
        self.iface.addPluginToMenu(self.menu_name, act_launch)
        self.actions.append(act_launch)

        act_settings = QAction(self.tr("Settings..."),
                               self.iface.mainWindow())
        act_settings.triggered.connect(self.open_settings)
        self.iface.addPluginToMenu(self.menu_name, act_settings)
        self.actions.append(act_settings)

    def unload(self):
        for a in self.actions:
            self.iface.removePluginMenu(self.menu_name, a)
            if self.toolbar is not None:
                self.toolbar.removeAction(a)
        self.actions = []
        for dlg in (self._dialog, self._settings_dialog):
            if dlg is not None:
                dlg.close()
        self._dialog = None
        self._settings_dialog = None
        self.installer.abort()

    # ---- 操作 ---------------------------------------------------------
    def open_dialog(self):
        """状態パネルを開く(既にあれば前面に出す)。"""
        from .dialog import GeoLauncherDialog

        if self._dialog is None:
            self._dialog = GeoLauncherDialog(
                self, self.iface.mainWindow())
        else:
            self._dialog.refresh()
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
        return self._dialog

    def open_settings(self):
        from .settings_dialog import GeoLauncherSettingsDialog

        if self._settings_dialog is None:
            self._settings_dialog = GeoLauncherSettingsDialog(
                self, self.iface.mainWindow())
        else:
            self._settings_dialog.refresh()
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()
        return self._settings_dialog

    def open_launcher(self):
        """qgis_launcher.exe を GUI モード(WebView2 窓)で起動する。

        窓内でユーザーがプロファイル/プロジェクトを選び「起動」を押すと、
        本体が新しい QGIS を立てて自動終了する(本体側の責務)。
        """
        try:
            launcher.launch()
            return True
        except launcher.LauncherError as e:
            self.iface.messageBar().pushCritical("geo_launcher", str(e))
            return False
