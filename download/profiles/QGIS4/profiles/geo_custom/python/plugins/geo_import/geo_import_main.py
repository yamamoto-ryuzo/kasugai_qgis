from qgis.PyQt.QtCore import QSettings, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar
from qgis.core import QgsMessageLog, Qgis
from .geo_import_dialog import GeoImportDialog
from .geo_import_dialog_settings import GeoImportDialogSettings
import os.path
from .i18n_json import install_translator
from .settings import Settings
from .util import Util


class GeoImport:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # 設定クラスを初期化して、プラグイン全体で使用する設定を管理
        self.settings = Settings()
        QgsMessageLog.logMessage('__init__', self.settings.DLG_CAPTION, Qgis.MessageLevel.Info)
        QSettings().setValue("geo_import/isopen", False)
        self.iface = iface

        # プラグインディレクトリを初期化し、リソースファイルのパスを構築
        self.plugin_dir = os.path.dirname(__file__)
        QgsMessageLog.logMessage(u'plugin directory: {}'.format(self.plugin_dir), self.settings.DLG_CAPTION, Qgis.MessageLevel.Info)

        # 言語を初期化(i18n/<lang>.json をQGISの言語設定に合わせて載せる)
        self.translator = install_translator(self.plugin_dir)

        # 設定をロード
        self.settings.load()
        self.util = Util(self.settings, self.iface.mainWindow())

        # インスタンス属性を宣言
        self.actions = []
        self.menu = QCoreApplication.translate('GeoImport', u'&geo_import')
        # 共有ツールバーGeoSuiteに集約(無ければ作成)
        self.toolbar = self.iface.mainWindow().findChild(QToolBar, u'GeoSuite')
        if self.toolbar is None:
            self.toolbar = self.iface.addToolBar(u'GeoSuite')
            self.toolbar.setObjectName(u'GeoSuite')

        # AI/外部制御用ブリッジ。qgis_live_driver の bridge_call コマンドが
        # qgis.utils.plugins['geo_import'].bridge をプロセス内で直接呼ぶため、
        # ファイルJSONL/REST/MCP(qgis_bridge_call)の全経路から制御できる
        try:
            from .bridge import GeoImportBridge
            self.bridge = GeoImportBridge(self)
        except Exception:
            self.bridge = None

    def add_action(
            self,
            icon_path,
            text,
            callback,
            enabled_flag=True,
            add_to_menu=True,
            add_to_toolbar=True,
            status_tip=None,
            whats_this=None,
            parent=None):
        """Add a toolbar icon to the InaSAFE toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """
        # アイコンとアクションを作成し、ツールバーやメニューに追加
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # ツールバーにアクションを追加
            self.toolbar.addAction(action)

        if add_to_menu:
            # プラグインメニューにアクションを追加
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        # QGISのGUI内にメニューエントリとツールバーアイコンを作成

        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')

        self.add_action(
            icon_path,
            text=QCoreApplication.translate('GeoImport', u'geo_import'),
            callback=self.run,
            parent=self.iface.mainWindow()
        )

        icon_settings = os.path.join(os.path.dirname(__file__), 'icon-settings.png')

        self.add_action(
            icon_settings,
            text=QCoreApplication.translate('GeoImport', u'geo_import_settings'),
            callback=self.open_settings,
            parent=self.iface.mainWindow()
        )

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        # QGISのGUIからプラグインメニュー項目とアイコンを削除する
        # 全てのアクションをメニューとツールバーから削除
        for action in self.actions:
            self.iface.removePluginMenu(
                QCoreApplication.translate('GeoImport', u'&geo_import'),
                action)
            self.toolbar.removeAction(action)

    def run(self):
        """Run method that performs all the real work"""
        # プラグインのメイン処理を実行する
        # データカタログブラウザダイアログを表示し、ユーザーがデータを検索・追加できるようにする

        # ダイアログが既に開いているかチェック（二重起動防止）
        is_open = QSettings().value("geo_import/isopen", False)
        # Pythonはほとんど全てをTrueとして扱うため、明示的にboolに変換
        self.util.msg_log_debug(u'isopen: {0}'.format(is_open))

        # 文字列比較 - WindowsとLinuxは文字列として、Macはboolとして扱うため
        # 文字列をboolに変換する
        if isinstance(is_open, str):
            is_open = self.util.str2bool(is_open)

        if is_open:
            self.util.msg_log_debug(u'Dialog already opened')
            return

        # auf URL testen
        dir_check = self.util.check_dir(self.settings.cache_dir)
        api_url_check = self.util.check_api_url(self.settings.ckan_url)
        if dir_check is False or api_url_check is False:
            dlg = GeoImportDialogSettings(self.settings, self.iface, self.iface.mainWindow())
            dlg.show()
            result = dlg.exec()
            if result != 1:
                return

#         self.util.msg_log('cache_dir: {0}'.format(self.settings.cache_dir))

        try:
            QSettings().setValue("geo_import/isopen", True)
            self.dlg = GeoImportDialog(self.settings, self.iface, self.iface.mainWindow())

            # show the dialog
            self.dlg.show()
            # self.dlg.open()
            # Run the dialog event loop
            result = self.dlg.exec()
            # See if OK was pressed
            if result:
                pass
        finally:
            QSettings().setValue("geo_import/isopen", False)

    def open_settings(self):
        # 設定ダイアログを開く
        dlg = GeoImportDialogSettings(self.settings, self.iface, self.iface.mainWindow())
        dlg.show()
        dlg.exec()
