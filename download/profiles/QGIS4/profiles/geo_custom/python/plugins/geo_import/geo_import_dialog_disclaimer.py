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

from qgis.PyQt import QtGui, uic
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog
from .util import Util

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(
        os.path.dirname(__file__),
        'geo_import_dialog_disclaimer.ui'
    )
)


class GeoImportDialogDisclaimer(QDialog, FORM_CLASS):
    @staticmethod
    def tr(message):
        """翻訳用のtr()メソッド"""
        return QCoreApplication.translate('GeoImport', message)
    
    def __init__(self, settings, parent=None):
        """Constructor."""
        super(GeoImportDialogDisclaimer, self).__init__(parent)
        # Qt Designerで作成したUIファイルからユーザーインターフェースを設定
        # setupUi実行後は、self.<オブジェクト名>でDesignerのオブジェクトにアクセス可能
        # 自動接続スロットも利用可能
        self.setModal(True)
        self.setupUi(self)
        self.main_win = parent
        self.settings = settings
        self.util = Util(self.settings, self.main_win)
        
        logo_path = self.util.resolve(u'ckan_logo_big.png')
        self.IDC_lblLogo.setPixmap(QtGui.QPixmap(logo_path))
        self.IDC_brInfo.setOpenExternalLinks(True)
        self.IDC_brInfo.setHtml(self.util.tr('py_disc_info_html'))
