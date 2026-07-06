from qgis.PyQt.QtCore import QSettings, QTranslator, qVersion, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsMessageLog, Qgis
from .geo_import_dialog import GeoImportDialog
from .geo_import_dialog_settings import GeoImportDialogSettings
import os.path
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
        QgsMessageLog.logMessage('__init__', self.settings.DLG_CAPTION, Qgis.Info)
        QSettings().setValue("geo_import/isopen", False)
        self.iface = iface

        # プラグインディレクトリを初期化し、リソースファイルのパスを構築
        self.plugin_dir = os.path.dirname(__file__)
        QgsMessageLog.logMessage(u'plugin directory: {}'.format(self.plugin_dir), self.settings.DLG_CAPTION, Qgis.Info)

        # ロケールを初期化（安全に取得）
        locale_value = QSettings().value('locale/userLocale', 'en_US')
        if locale_value and len(locale_value) >= 2:
            locale = locale_value[0:2]
        else:
            locale = 'en'
        QgsMessageLog.logMessage(u'locale: {}'.format(locale), self.settings.DLG_CAPTION, Qgis.Info)
        # Use geo_import_*.qm naming convention
        locale_path_geo = os.path.join(
            self.plugin_dir,
            'i18n',
            'geo_import_{}.qm'.format(locale))

        locale_path_legacy = os.path.join(
            self.plugin_dir,
            'i18n',
            'CKANBrowser_{}.qm'.format(locale))

        locale_path_geo_en = os.path.join(
            self.plugin_dir,
            'i18n',
            'geo_import_en.qm'
        )

        locale_path_legacy_en = os.path.join(
            self.plugin_dir,
            'i18n',
            'CKANBrowser_en.qm'
        )

        # Choose which English fallback to use if present
        if os.path.exists(locale_path_geo_en):
            locale_path_en = locale_path_geo_en
        else:
            locale_path_en = locale_path_legacy_en

        # Decide which file to use for the chosen locale
        if os.path.exists(locale_path_geo):
            locale_path = locale_path_geo
        elif os.path.exists(locale_path_legacy):
            locale_path = locale_path_legacy
        else:
            # current locale file not found -> fall back to English
            locale = 'en'
            if os.path.exists(locale_path_geo_en):
                locale_path = locale_path_geo_en
            else:
                locale_path = locale_path_legacy_en

        # ロケールが英語でない場合、未翻訳要素用のフォールバックとして英語を追加でロード
        if locale != 'en':
            QgsMessageLog.logMessage(u'loading "en" fallback: {}'.format(locale_path_en), self.settings.DLG_CAPTION, Qgis.Info)
            self.translator_en = QTranslator()
            self.translator_en.load(locale_path_en)
            if not QCoreApplication.installTranslator(self.translator_en):
                QgsMessageLog.logMessage(u'could not install translator: {}'.format(locale_path_en), self.settings.DLG_CAPTION, Qgis.Critical)
            else:
                QgsMessageLog.logMessage(u'locale "en" installed', self.settings.DLG_CAPTION, Qgis.Info)

        # ロケールに応じた翻訳をロード
        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            if not QCoreApplication.installTranslator(self.translator):
                QgsMessageLog.logMessage(u'could not install translator: {}'.format(locale_path), self.settings.DLG_CAPTION, Qgis.Critical)
            else:
                QgsMessageLog.logMessage(u'locale "{}" installed'.format(locale), self.settings.DLG_CAPTION, Qgis.Info)

        # 設定をロード
        self.settings.load()
        self.util = Util(self.settings, self.iface.mainWindow())

        # インスタンス属性を宣言
        self.actions = []
        self.menu = self.util.tr(u'&geo_import')
        self.toolbar = self.iface.addToolBar(u'geo_import')
        self.toolbar.setObjectName(u'geo_import')


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
            text=self.util.tr(u'geo_import'),
            callback=self.run,
            parent=self.iface.mainWindow()
        )
        
        icon_settings = os.path.join(os.path.dirname(__file__), 'icon-settings.png')
        
        self.add_action(
            icon_settings,
            text=self.util.tr(u'geo_import_settings'),
            callback=self.open_settings,
            parent=self.iface.mainWindow()
        )

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        # QGISのGUIからプラグインメニュー項目とアイコンを削除する
        # 全てのアクションをメニューとツールバーから削除
        for action in self.actions:
            self.iface.removePluginMenu(
                self.util.tr(u'&geo_import'),
                action)
            self.iface.removeToolBarIcon(action)

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
            #self.dlg.open()
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