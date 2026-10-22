# -*- coding: utf-8 -*-
"""
/***************************************************************************
 GeoWebViewPanel
                                 A QGIS plugin
 Navigate QGIS map views through external permalink system - Panel Version
                             -------------------
        begin                : 2025-10-05
        git sha              : $Format:%H$
        copyright            : (C) 2025 by yamamoto-ryuzo
        email                :
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDockWidget, QWidget
from qgis.PyQt.QtCore import Qt, QSize, QCoreApplication
from qgis.PyQt.QtGui import QGuiApplication, QIcon

# UIファイルのパスを指定
FORM_CLASS = None
try:
    FORM_CLASS, _ = uic.loadUiType(os.path.join(
        os.path.dirname(__file__), 'panel_base.ui'))
except Exception:
    # Defer UI loading errors to runtime. Keep FORM_CLASS as None so the
    # module can be imported in environments where Qt/PyQt or uic is not
    # available (for example when running static analysis or tests).
    FORM_CLASS = None


class GeoWebViewPanel(QDockWidget):
    """geo_webviewのパネルクラス

    Qt Designerで作成されたUIファイルを読み込んでドッキング可能なパネルとして表示
    """

    def __init__(self, parent=None):
        """コンストラクタ

        Args:
            parent: 親ウィジェット
        """
        super(GeoWebViewPanel, self).__init__(parent)

        # パネルのタイトルを設定
        self.setWindowTitle("GeoWebView")

        # ドッキングエリアを設定（左側を優先、右側も可能）
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        # 内部ウィジェットを作成
        self.widget = QWidget()
        # If FORM_CLASS could not be loaded (e.g. uic unavailable), create a
        # minimal fallback UI so the plugin can still import and display a
        # helpful message instead of failing entirely.
        if FORM_CLASS is None:
            self.ui = None
            try:
                # Create a minimal placeholder UI
                from qgis.PyQt.QtWidgets import QLabel, QVBoxLayout
                layout = QVBoxLayout()
                label = QLabel(self.tr("Could not load the UI file. Please consider reinstalling the plugin."))
                layout.addWidget(label)
                self.widget.setLayout(layout)
            except Exception:  # nosec B110  # 設計上の許容
                # If even Qt widgets are not available, leave widget empty
                pass
        else:
            self.ui = FORM_CLASS()
            self.ui.setupUi(self.widget)

        # 直接アクセス用のプロパティを追加（ui が None の場合は None を代入）
        self.pushButton_generate = getattr(self.ui, 'pushButton_generate', None)
        self.pushButton_navigate = getattr(self.ui, 'pushButton_navigate', None)
        self.pushButton_copy = getattr(self.ui, 'pushButton_copy', None)
        # newly added UI elements
        self.pushButton_clipboard = getattr(self.ui, 'pushButton_clipboard', None)
        self.pushButton_paste = getattr(self.ui, 'pushButton_paste', None)
        self.pushButton_open = getattr(self.ui, 'pushButton_open', None)
        # MapLibre button (added in UI)
        self.pushButton_maplibre = getattr(self.ui, 'pushButton_maplibre', None)
        self.pushButton_settings = getattr(self.ui, 'pushButton_settings', None)
        self.lineEdit_permalink = getattr(self.ui, 'lineEdit_permalink', None)
        self.lineEdit_navigate = getattr(self.ui, 'lineEdit_navigate', None)
        self.label_server_status = getattr(self.ui, 'label_server_status', None)
        self.comboBox_themes = getattr(self.ui, 'comboBox_themes', None)

        # Google Maps/Earth用のUI要素
        self.pushButton_google_maps = getattr(self.ui, 'pushButton_google_maps', None)
        self.pushButton_google_earth = getattr(self.ui, 'pushButton_google_earth', None)
        # KASUGAI Canvas エクスポートボタン
        self.pushButton_kasugai = getattr(self.ui, 'pushButton_kasugai', None)
        # HTTP server toggle checkbox (added to UI)
        self.checkBox_server_toggle = getattr(self.ui, 'checkBox_server_toggle', None)
        # External control checkbox (new in UI)
        self.checkBox_external_control = getattr(self.ui, 'checkBox_external_control', None)
        # Port number spinbox (new in UI)
        self.spinBox_port = getattr(self.ui, 'spinBox_port', None)
        # Check access button (new in UI)
        self.pushButton_check_access = getattr(self.ui, 'pushButton_check_access', None)
        # Standard port buttons (new in UI)
        self.pushButton_port_80 = getattr(self.ui, 'pushButton_port_80', None)
        self.pushButton_port_443 = getattr(self.ui, 'pushButton_port_443', None)

        # 共有/プレゼンテーション/3D/MAC認証の追加UI(動的生成)
        self.groupBox_sharing = None
        self.pushButton_present = None
        self.pushButton_map3d = None
        self.comboBox_received = None
        self.checkBox_mac_auth = None
        self.lineEdit_mac_auth = None
        try:
            self._build_sharing_group()
        except Exception:  # nosec B110  # 設計上の許容
            pass

        # ウィジェットを設定
        self.setWidget(self.widget)

        # パネルのサイズを設定（左側パネルに適したサイズ）
        self.setMinimumWidth(250)
        self.setMaximumWidth(400)

        # パネルの特徴を設定
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable |
                         QDockWidget.DockWidgetFeature.DockWidgetClosable)

        # UI要素を翻訳
        self.translate_ui()

        # 設定ボタンのアイコンを読み込み、枠付きスタイルを適用
        try:
            if self.pushButton_settings is not None:
                try:
                    icon_path = os.path.join(os.path.dirname(__file__), 'icon', 'setting.png')
                    if os.path.exists(icon_path):
                        self.pushButton_settings.setIcon(QIcon(icon_path))
                        self.pushButton_settings.setIconSize(QSize(20, 20))
                    # add framed look similar to ICO frame
                    self.pushButton_settings.setStyleSheet('border:1px solid #888; border-radius:4px; padding:2px;')
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                # connect to placeholder settings dialog opener
                try:
                    from .settings_dialog import SettingsDialog

                    def _open_settings():
                        try:
                            dlg = SettingsDialog(self)
                            dlg.exec()
                        except Exception:  # nosec B110  # 設計上の許容
                            pass

                    self.pushButton_settings.clicked.connect(_open_settings)
                except Exception:  # nosec B110  # 設計上の許容
                    # no settings dialog available; ignore
                    pass
        except Exception:  # nosec B110  # 設計上の許容
            pass

        # クリップボード関連のシグナルを接続
        try:
            _ = QGuiApplication.clipboard()
            if self.pushButton_clipboard is not None:
                # コピー: 現在の permalink テキストをクリップボードへ
                self.pushButton_clipboard.clicked.connect(self._on_copy_permalink_to_clipboard)
            if self.pushButton_paste is not None:
                # 貼り付け: クリップボードから navigate テキストボックスへ
                self.pushButton_paste.clicked.connect(self._on_paste_from_clipboard)
        except Exception:  # nosec B110  # 設計上の許容
            # Qt 環境が利用できない場合は無視
            pass

    def translate_ui(self):
        """UI要素のテキストを翻訳"""
        # NOTE: i18n/<lang>.json のコンテキスト 'geo_webview' に対応させるため
        # ラッパー関数ではなく QCoreApplication.translate を直接呼ぶこと
        from qgis.PyQt.QtCore import QCoreApplication

        # グループボックスのタイトル
        if hasattr(self.ui, 'groupBox_server'):
            self.ui.groupBox_server.setTitle(QCoreApplication.translate('geo_webview', "HTTP Server Status"))
        if hasattr(self.ui, 'groupBox_generate'):
            self.ui.groupBox_generate.setTitle(QCoreApplication.translate('geo_webview', "Generate Permalink"))
        if hasattr(self.ui, 'groupBox_permalink'):
            self.ui.groupBox_permalink.setTitle(QCoreApplication.translate('geo_webview', "Current Permalink"))
        if hasattr(self.ui, 'groupBox_navigate'):
            self.ui.groupBox_navigate.setTitle(QCoreApplication.translate('geo_webview', "Navigate to Location"))

        # ラベル
        if hasattr(self.ui, 'label_generate_info'):
            self.ui.label_generate_info.setText(QCoreApplication.translate('geo_webview', "Generate a permalink for the current map view"))
        if hasattr(self.ui, 'label_theme_selection'):
            self.ui.label_theme_selection.setText(QCoreApplication.translate('geo_webview', "Theme/Layer State:"))
        if hasattr(self.ui, 'label_navigate_info'):
            self.ui.label_navigate_info.setText(QCoreApplication.translate('geo_webview', "Enter a permalink to navigate"))

        # Buttons now include the icon/label together; set button texts instead
        if hasattr(self.ui, 'pushButton_google_maps'):
            self.ui.pushButton_google_maps.setText(QCoreApplication.translate('geo_webview', "🗺️ Google Maps"))
        if hasattr(self.ui, 'pushButton_google_earth'):
            self.ui.pushButton_google_earth.setText(QCoreApplication.translate('geo_webview', "🌍 Google Earth"))
        if hasattr(self.ui, 'pushButton_kasugai'):
            self.ui.pushButton_kasugai.setText(QCoreApplication.translate('geo_webview', "KASUGAI"))

        # ボタン
        if hasattr(self.ui, 'pushButton_generate'):
            self.ui.pushButton_generate.setText(QCoreApplication.translate('geo_webview', "Generate Permalink"))
        if hasattr(self.ui, 'pushButton_copy'):
            self.ui.pushButton_copy.setText(QCoreApplication.translate('geo_webview', "URLCopy"))
        if hasattr(self.ui, 'pushButton_open'):
            self.ui.pushButton_open.setText(QCoreApplication.translate('geo_webview', "OpenLayers"))
        if hasattr(self.ui, 'pushButton_navigate'):
            self.ui.pushButton_navigate.setText(QCoreApplication.translate('geo_webview', "Navigate"))

        # プレースホルダーテキスト
        if hasattr(self.ui, 'lineEdit_permalink'):
            self.ui.lineEdit_permalink.setPlaceholderText(QCoreApplication.translate('geo_webview', "Generated permalink will appear here"))
        if hasattr(self.ui, 'lineEdit_navigate'):
            self.ui.lineEdit_navigate.setPlaceholderText(QCoreApplication.translate('geo_webview', "Paste permalink here"))

        # コンボボックスの項目
        if hasattr(self.ui, 'comboBox_themes'):
            # 既存の項目をクリアして翻訳済みの項目を追加
            self.ui.comboBox_themes.clear()
            self.ui.comboBox_themes.addItem(QCoreApplication.translate('geo_webview', "-- No Theme (Position Only) --"), "__no_theme__")
            # ツールチップも翻訳
            self.ui.comboBox_themes.setToolTip(QCoreApplication.translate('geo_webview', "Select theme option: no theme (position only) or specific theme"))
        # External control checkbox
        if hasattr(self.ui, 'checkBox_external_control'):
            self.ui.checkBox_external_control.setText(QCoreApplication.translate('geo_webview', "External Control"))
            self.ui.checkBox_external_control.setToolTip(QCoreApplication.translate('geo_webview', "When enabled, map view can be updated by external URLs"))

    def update_server_status(self, port, running):
        """サーバーステータスを更新

        Args:
            port: サーバーポート番号
            running: サーバーが実行中かどうか
        """
        if running:
            status_text = QCoreApplication.translate('geo_webview', "HTTP Server: Running on http://localhost:{0}").format(port)
            style = "color: green; font-weight: bold;"
        else:
            status_text = QCoreApplication.translate('geo_webview', "HTTP Server: Stopped")
            style = "color: red; font-weight: bold;"

        self.label_server_status.setText(status_text)
        self.label_server_status.setStyleSheet(style)

        # Update spinBox_port to reflect current port
        try:
            if self.spinBox_port is not None:
                self.spinBox_port.blockSignals(True)
                self.spinBox_port.setValue(int(port))
                self.spinBox_port.blockSignals(False)
        except Exception:  # nosec B110  # 設計上の許容
            pass

        # Keep checkbox in sync if present
        try:
            if self.checkBox_server_toggle is not None:
                # block signals to avoid recursive calls
                self.checkBox_server_toggle.blockSignals(True)
                self.checkBox_server_toggle.setChecked(bool(running))
                self.checkBox_server_toggle.blockSignals(False)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        # keep external control checkbox untouched here (no server relation)
        try:
            if self.checkBox_external_control is not None:
                # ensure it's boolean
                self.checkBox_external_control.blockSignals(True)
                self.checkBox_external_control.setChecked(bool(getattr(self.checkBox_external_control, 'isChecked', lambda: False)()))
                self.checkBox_external_control.blockSignals(False)
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _build_sharing_group(self):
        """共有/プレゼンテーション関連のウィジェットを動的に追加する。

        .ui ファイルを変更せず、メインの verticalLayout 末尾に
        groupBox を追加する。利用不可能な環境では何もしない。
        """
        from qgis.PyQt.QtWidgets import (
            QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton,
            QComboBox, QCheckBox, QLineEdit)
        tr = QCoreApplication.translate
        group = QGroupBox(tr('geo_webview', 'Sharing / Presentation'))
        vbox = QVBoxLayout(group)

        row1 = QHBoxLayout()
        self.pushButton_present = QPushButton(
            tr('geo_webview', 'Presentation Share'))
        self.pushButton_present.setToolTip(tr(
            'geo_webview',
            'Open a page that mirrors the QGIS canvas for window sharing'))
        self.pushButton_map3d = QPushButton(
            tr('geo_webview', '3D (OL+Cesium)'))
        self.pushButton_map3d.setToolTip(tr(
            'geo_webview',
            'Open a two-pane OpenLayers + Cesium synchronized 3D view'))
        row1.addWidget(self.pushButton_present)
        row1.addWidget(self.pushButton_map3d)
        vbox.addLayout(row1)

        self.comboBox_received = QComboBox()
        self.comboBox_received.setToolTip(tr(
            'geo_webview',
            'Permalinks received from clients (latest 10). '
            'Selecting an entry copies it into the navigate field.'))
        vbox.addWidget(self.comboBox_received)

        self.checkBox_mac_auth = QCheckBox(
            tr('geo_webview', 'MAC address authentication'))
        self.checkBox_mac_auth.setToolTip(tr(
            'geo_webview',
            'When enabled, only registered client MAC addresses may access '
            'the HTTP server.'))
        vbox.addWidget(self.checkBox_mac_auth)
        self.lineEdit_mac_auth = QLineEdit()
        self.lineEdit_mac_auth.setPlaceholderText(tr(
            'geo_webview',
            'Allowed MAC addresses (comma separated). Empty = deny all'))
        vbox.addWidget(self.lineEdit_mac_auth)

        self.groupBox_sharing = group
        try:
            layout = self.widget.layout()
            if layout is not None:
                layout.addWidget(group)
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def update_received_history(self, entries):
        """受領パーマリンク履歴コンボを更新する(選択状態を維持)。"""
        combo = self.comboBox_received
        if combo is None:
            return
        try:
            current_url = None
            if combo.count() > 0 and combo.currentIndex() >= 0:
                current_url = combo.itemData(combo.currentIndex())
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(
                QCoreApplication.translate(
                    'geo_webview', '-- received permalinks --'), None)
            for ent in entries or []:
                url = ent.get('url') or ''
                label = '{0} {1} {2}'.format(
                    ent.get('time', ''), ent.get('client', ''),
                    ent.get('ua', '') or url[:60])
                combo.addItem(label, url)
            if current_url:
                idx = combo.findData(current_url)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(0)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        finally:
            try:
                combo.blockSignals(False)
            except Exception:  # nosec B110  # 設計上の許容
                pass

    def set_server_toggle_handler(self, handler):
        """外部からトグルのハンドラを設定する

        handler: function(checked: bool) -> None
        """
        if self.checkBox_server_toggle is None:
            return
        try:
            # connect stateChanged -> handler
            self.checkBox_server_toggle.stateChanged.connect(lambda state: handler(bool(state)))
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def set_external_control_handler(self, handler):
        """外部制御トグルのハンドラを設定する

        handler: function(checked: bool) -> None
        """
        if self.checkBox_external_control is None:
            return
        try:
            self.checkBox_external_control.stateChanged.connect(lambda state: handler(bool(state)))
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def set_port_change_handler(self, handler):
        """ポート番号変更のハンドラを設定する

        handler: function(port: int) -> None
        """
        if self.spinBox_port is None:
            return
        try:
            self.spinBox_port.valueChanged.connect(lambda value: handler(int(value)))
        except Exception:  # nosec B110  # 設計上の許容
            pass

    # --- Clipboard handlers ---
    def _on_copy_permalink_to_clipboard(self):
        """lineEdit_permalink の内容をシステムクリップボードにコピーする"""
        try:
            text = ''
            if hasattr(self, 'lineEdit_permalink') and self.lineEdit_permalink is not None:
                text = self.lineEdit_permalink.text() or ''
            QGuiApplication.clipboard().setText(text)
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _on_paste_from_clipboard(self):
        """クリップボードからテキストを取得して lineEdit_navigate に貼り付ける"""
        try:
            cb = QGuiApplication.clipboard()
            text = cb.text() if cb is not None else ''
            if hasattr(self, 'lineEdit_navigate') and self.lineEdit_navigate is not None:
                self.lineEdit_navigate.setText(text)
        except Exception:  # nosec B110  # 設計上の許容
            pass
