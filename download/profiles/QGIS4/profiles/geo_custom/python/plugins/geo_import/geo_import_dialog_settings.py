# -*- coding: utf-8 -*-
"""
/***************************************************************************
 QGIS Data Catalog Integration / Catalog Integration
                                 A QGIS plugin
 Download and display CKAN enabled Open Data Portals
                              -------------------
        begin                : 2014-10-24
        git sha              : $Format:%H$
        copyright            : (C) 2014 by BergWerk GIS
        email                : wb@BergWerk-GIS.at
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
from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt import QtGui, uic
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog, QVBoxLayout, QDialogButtonBox
from collections import OrderedDict
from .util import Util
from .ckanconnector import CkanConnector
import json

try:
    from qgis.gui import QgsAuthConfigSelect
except ImportError:
    QgsAuthConfigSelect = None


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'geo_import_dialog_settings.ui'))


class GeoImportDialogSettings(QDialog, FORM_CLASS):
    @staticmethod
    def tr(message):
        """翻訳用のtr()メソッド"""
        return QCoreApplication.translate('GeoImport', message)
    
    def __init__(self, settings, iface, parent=None):
        """Constructor."""
        super(GeoImportDialogSettings, self).__init__(parent)
        # Qt Designerで作成したUIファイルからユーザーインターフェースを設定
        # setupUi実行後は、self.<オブジェクト名>でDesignerのオブジェクトにアクセス可能
        # 自動接続スロットも利用可能
        self.setupUi(self)
        self.iface = iface
        self.main_win = parent
        self.settings = settings
        self.util = Util(self.settings, self.main_win)

        self.IDC_leCacheDir.setText(self.settings.cache_dir)
        self.IDC_chkbox_show_debug_info.setChecked(self.settings.debug)

        if QgsAuthConfigSelect is None:
            self.IDC_leAuthCfg.hide()
            self.IDC_bAuthCfgClear.hide()
            self.IDC_bAuthCfgEdit.hide()
            self.IDC_lblAuthCfg.hide()
            self.IDC_cbAuthPropagate.hide()
        else:
            if self.settings.authcfg:
                self.IDC_leAuthCfg.setText(self.settings.authcfg)
                self.IDC_cbAuthPropagate.setChecked(self.settings.auth_propagate)
            else:
                self.IDC_cbAuthPropagate.setChecked(False)

        self.cc = CkanConnector(self.settings, self.util)

    def select_cache_dir(self):
        cache_dir = QFileDialog.getExistingDirectory(
            self.main_win,
            self.settings.DLG_CAPTION,
            self.settings.cache_dir,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )
        if '' == cache_dir:
            self.util.msg_log_debug('no cachedir selected')
        else:
            self.IDC_leCacheDir.setText(cache_dir)

    def cancel(self):
        QDialog.reject(self)

    def save(self):
        cache_dir = self.IDC_leCacheDir.text()
        if self.util.check_dir(cache_dir) is False:
            self.util.dlg_warning(
                self.util.tr(u'py_dlg_set_warn_cache_not_use').format(self.settings.cache_dir)
            )
            return

        self.settings.cache_dir = cache_dir
        self.settings.debug = self.IDC_chkbox_show_debug_info.isChecked()

        authcfg = self.IDC_leAuthCfg.text()
        self.settings.authcfg = authcfg
        self.settings.auth_propagate = self.IDC_cbAuthPropagate.isChecked()

        self.settings.save()

        QDialog.accept(self)

    def help_cache_dir(self):
        self.util.dlg_information(self.util.tr(u'dlg_set_tool_cache'))

    def authcfg_clear(self):
         self.IDC_leAuthCfg.clear()

    def authcfg_edit(self):
        dlg = QDialog(None)
        dlg.setWindowTitle(self.util.tr("Select Authentication"))
        layout = QVBoxLayout(dlg)

        acs = QgsAuthConfigSelect(dlg)
        if self.IDC_leAuthCfg.text():
            acs.setConfigId(self.IDC_leAuthCfg.text())
        layout.addWidget(acs)

        buttonbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal, dlg
        )

        layout.addWidget(buttonbox)
        buttonbox.accepted.connect(dlg.accept)
        buttonbox.rejected.connect(dlg.close)

        dlg.setLayout(layout)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)

        if dlg.exec():
            self.IDC_leAuthCfg.setText(acs.configId())
            self.cc.auth_cfg = acs.configId()
