# -*- coding: utf-8 -*-
"""
Qt6 imports for QGIS Plugin (QGIS4以降専用)
"""

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt, pyqtSignal, QSize, QVariant
from qgis.PyQt.QtGui import QIcon, QBrush, QPixmap, QImage, QFont
from qgis.PyQt.QtWidgets import (QAction, QDockWidget, QTableWidget, QTableWidgetItem,
                                 QApplication, QWidget, QHeaderView, QMessageBox, QLabel, QStyle,
                                 QAbstractItemView)
from qgis.PyQt import QtGui, QtWidgets, uic


# Alignment constants (Qt6 enum style)
AlignHCenter = Qt.AlignmentFlag.AlignHCenter
AlignVCenter = Qt.AlignmentFlag.AlignVCenter
AlignCenter = Qt.AlignmentFlag.AlignCenter
AlignLeft = Qt.AlignmentFlag.AlignLeft
AlignRight = Qt.AlignmentFlag.AlignRight
AlignTop = Qt.AlignmentFlag.AlignTop
AlignBottom = Qt.AlignmentFlag.AlignBottom

QtOrientation = Qt.Orientation

WA_DeleteOnClose = Qt.WidgetAttribute.WA_DeleteOnClose
RightDockWidgetArea = Qt.DockWidgetArea.RightDockWidgetArea
PM_ListViewIconSize = QStyle.PixelMetric.PM_ListViewIconSize

NoSelection = QAbstractItemView.SelectionMode.NoSelection
SingleSelection = QAbstractItemView.SelectionMode.SingleSelection
MultiSelection = QAbstractItemView.SelectionMode.MultiSelection
ExtendedSelection = QAbstractItemView.SelectionMode.ExtendedSelection
ContiguousSelection = QAbstractItemView.SelectionMode.ContiguousSelection


def setLabelAlignment(label):
    """Qt6 alignment setting"""
    label.setAlignment(AlignHCenter | AlignVCenter)


def createSymbolPreview(symbol, size):
    """Symbol preview creation - 95% of frame size"""
    try:
        from qgis.core import QgsSymbolLayerUtils
        enhanced_size = QSize(int(size.width() * 0.95), int(size.height() * 0.95))
        return QgsSymbolLayerUtils.symbolPreviewPixmap(symbol, enhanced_size)
    except Exception:
        return QPixmap(size)


def translate(context, text, disambig=None):
    """Qt6 translation function"""
    return QCoreApplication.translate(context, text, disambig)
