from qgis.PyQt import QtWidgets, QtCore
import os
import tempfile

from qgis.PyQt.QtGui import QIcon


class SettingsDialog(QtWidgets.QDialog):
    """Settings dialog for KASUGAI Canvas integration configuration"""

    def __init__(self, parent=None):
        super(SettingsDialog, self).__init__(parent)
        self.setWindowTitle(QtCore.QCoreApplication.translate('geo_webview', "Settings"))
        self.setMinimumWidth(600)
        try:
            icon_path = os.path.join(os.path.dirname(__file__), 'icon', 'setting.png')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:  # nosec B110  # 設計上の許容
            pass

        # Initialize QSettings for persistent storage
        self.settings = QtCore.QSettings('GeoWebView', 'geo_webview')

        # Main layout
        layout = QtWidgets.QVBoxLayout()

        # Title
        title = QtWidgets.QLabel(QtCore.QCoreApplication.translate('geo_webview', "KASUGAI Canvas"))
        title.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(title)

        # KASUGAI Canvas install location (serverless export target)
        kasugai_group = QtWidgets.QGroupBox(QtCore.QCoreApplication.translate('geo_webview', "KASUGAI Canvas Install Location"))
        kasugai_layout = QtWidgets.QVBoxLayout()

        kasugai_path_layout = QtWidgets.QHBoxLayout()
        kasugai_path_label = QtWidgets.QLabel(QtCore.QCoreApplication.translate('geo_webview', "Install Path:"))
        self.kasugai_install_input = QtWidgets.QLineEdit()
        self.kasugai_install_input.setReadOnly(True)
        kasugai_path_layout.addWidget(kasugai_path_label)
        kasugai_path_layout.addWidget(self.kasugai_install_input)
        kasugai_layout.addLayout(kasugai_path_layout)

        kasugai_button_layout = QtWidgets.QHBoxLayout()
        btn_kasugai_browse = QtWidgets.QPushButton(QtCore.QCoreApplication.translate('geo_webview', "Browse..."))
        btn_kasugai_browse.clicked.connect(self._browse_kasugai_install)
        kasugai_button_layout.addWidget(btn_kasugai_browse)

        btn_kasugai_clear = QtWidgets.QPushButton(QtCore.QCoreApplication.translate('geo_webview', "Clear"))
        btn_kasugai_clear.setToolTip(QtCore.QCoreApplication.translate('geo_webview', "Export to the standalone output directory instead"))
        btn_kasugai_clear.clicked.connect(self._clear_kasugai_install)
        kasugai_button_layout.addWidget(btn_kasugai_clear)
        kasugai_button_layout.addStretch()
        kasugai_layout.addLayout(kasugai_button_layout)

        kasugai_info = QtWidgets.QLabel(
            QtCore.QCoreApplication.translate('geo_webview',
                                              "When set, KASUGAI export writes .kasc+DATA/ into "
                                              "<install>/QGIS_projects/<project>/ (kept separate from Canvas's own projects/) "
                                              "and registers it via the local API.")
        )
        kasugai_info.setWordWrap(True)
        kasugai_info.setStyleSheet("color: #666;")
        kasugai_layout.addWidget(kasugai_info)

        kasugai_group.setLayout(kasugai_layout)
        layout.addWidget(kasugai_group)

        # Hosted engine channel (kasugai-canvas-web)
        hosted_group = QtWidgets.QGroupBox(QtCore.QCoreApplication.translate('geo_webview', "Hosted Engine (kasugai-canvas-web)"))
        hosted_layout = QtWidgets.QVBoxLayout()
        hosted_row = QtWidgets.QHBoxLayout()
        hosted_label = QtWidgets.QLabel(QtCore.QCoreApplication.translate('geo_webview', "Channel:"))
        self.kasugai_hosted_combo = QtWidgets.QComboBox()
        self.kasugai_hosted_combo.setEditable(True)
        self.kasugai_hosted_combo.addItems(['stable', 'unstable'])
        self.kasugai_hosted_combo.setToolTip(
            QtCore.QCoreApplication.translate(
                'geo_webview',
                "Engine channel used when KASUGAI Canvas is not installed. "
                "'stable'/'unstable' or a custom base URL ending with '/'."))
        self.kasugai_hosted_combo.currentTextChanged.connect(
            self._hosted_channel_changed)
        hosted_row.addWidget(hosted_label)
        hosted_row.addWidget(self.kasugai_hosted_combo)
        hosted_layout.addLayout(hosted_row)
        hosted_info = QtWidgets.QLabel(
            QtCore.QCoreApplication.translate(
                'geo_webview',
                "Fallback when KASUGAI Canvas is not installed: the hosted "
                "engine reads .kasc+DATA/ served by this plugin's HTTP server."))
        hosted_info.setWordWrap(True)
        hosted_info.setStyleSheet("color: #666;")
        hosted_layout.addWidget(hosted_info)
        hosted_group.setLayout(hosted_layout)
        layout.addWidget(hosted_group)

        # Basemap group names (.kasc export)
        bm_group = QtWidgets.QGroupBox(
            QtCore.QCoreApplication.translate('geo_webview', "Basemap Groups"))
        bm_layout = QtWidgets.QVBoxLayout()
        bm_row = QtWidgets.QHBoxLayout()
        bm_label = QtWidgets.QLabel(
            QtCore.QCoreApplication.translate('geo_webview', "Additional names:"))
        self.kasugai_basemap_groups_input = QtWidgets.QLineEdit()
        self.kasugai_basemap_groups_input.setPlaceholderText(
            QtCore.QCoreApplication.translate(
                'geo_webview', "e.g. 背景, Basemaps, Base Map"))
        self.kasugai_basemap_groups_input.setToolTip(
            QtCore.QCoreApplication.translate(
                'geo_webview',
                "Comma-separated layer-tree group names treated as basemaps "
                "(in addition to the built-in 背景図 / ベースマップ / basemap)."))
        self.kasugai_basemap_groups_input.editingFinished.connect(
            self._basemap_groups_changed)
        bm_row.addWidget(bm_label)
        bm_row.addWidget(self.kasugai_basemap_groups_input)
        bm_layout.addLayout(bm_row)
        bm_info = QtWidgets.QLabel(
            QtCore.QCoreApplication.translate(
                'geo_webview',
                "XYZ tile layers inside a layer-tree group with one of these "
                "names are exported as basemap entries (base:) instead of "
                "regular layers. Sub-groups are kept for grouped display."))
        bm_info.setWordWrap(True)
        bm_info.setStyleSheet("color: #666;")
        bm_layout.addWidget(bm_info)
        bm_group.setLayout(bm_layout)
        layout.addWidget(bm_group)

        layout.addStretch()

        # Close button
        btn_close = QtWidgets.QPushButton(QtCore.QCoreApplication.translate('geo_webview', "Close"))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

        self.setLayout(layout)

        # Load saved settings
        self._load_settings()

    def showEvent(self, event):
        """Refresh settings when dialog is shown to reflect latest values"""
        super().showEvent(event)
        self._load_settings()

    def _load_settings(self):
        """Load saved settings from QSettings and display them dynamically"""
        # KASUGAI Canvas install location
        install_path = self.settings.value('kasugai_install_path', '') or ''
        install_path = str(install_path).strip()
        if install_path and install_path != '__default__' and os.path.isdir(install_path):
            self.kasugai_install_input.setText(install_path)
            self._kasugai_install_path = install_path
        else:
            # 設定未登録でもレジストリ(インストーラ登録)から検出できれば表示する
            detected = ''
            try:
                from . import kasugai_export
                detected = kasugai_export._registry_install_dir() or ''
            except Exception:  # nosec B110  # レジストリ自動検出は任意機能・失敗時は [Not set] 表示のみ
                pass
            if detected:
                self.kasugai_install_input.setText(
                    QtCore.QCoreApplication.translate('geo_webview', "[Auto-detected] {0}").format(detected))
            else:
                self.kasugai_install_input.setText(
                    QtCore.QCoreApplication.translate('geo_webview', "[Not set] export to output directory"))
            self._kasugai_install_path = ''
            if install_path and install_path != '__default__':
                self.settings.setValue('kasugai_install_path', '')

        # Hosted engine channel
        ch = str(self.settings.value('kasugai_hosted_channel', '')
                 or '').strip() or 'stable'
        self.kasugai_hosted_combo.setCurrentText(ch)

        # Additional basemap group names
        self.kasugai_basemap_groups_input.setText(
            str(self.settings.value('kasugai_basemap_groups', '') or ''))

    def _basemap_groups_changed(self):
        """追加のベースマップグループ名(カンマ区切り)を保存する。"""
        self.settings.setValue(
            'kasugai_basemap_groups',
            str(self.kasugai_basemap_groups_input.text() or '').strip())

    def _hosted_channel_changed(self, text):
        """ホスト版エンジンのチャンネル変更を保存する。"""
        self.settings.setValue(
            'kasugai_hosted_channel', str(text or '').strip() or 'stable')

    def _browse_kasugai_install(self):
        """Select KASUGAI Canvas install directory; export lands in <dir>/projects/."""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            QtCore.QCoreApplication.translate('geo_webview', "Select KASUGAI Canvas Install Directory"),
            self._kasugai_install_path or tempfile.gettempdir()
        )
        if folder:
            self.kasugai_install_input.setText(folder)
            self._kasugai_install_path = folder
            self.settings.setValue('kasugai_install_path', folder)

    def _clear_kasugai_install(self):
        """Unset install dir: fall back to the standalone output directory."""
        self.kasugai_install_input.setText(
            QtCore.QCoreApplication.translate('geo_webview', "[Not set] export to output directory"))
        self._kasugai_install_path = ''
        self.settings.setValue('kasugai_install_path', '')
