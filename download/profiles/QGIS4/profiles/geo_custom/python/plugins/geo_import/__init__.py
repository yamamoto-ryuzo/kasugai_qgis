# -*- coding: utf-8 -*-
"""
/***************************************************************************
 データカタログ統合
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


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load GeoImport class from file GeoImport.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    # プラグインのメインクラスをロードして返す
    # QGISインターフェースを受け取り、GeoImportインスタンスを初期化する
    from .geo_import_main import GeoImport
    return GeoImport(iface)
