# -*- coding: utf-8 -*-
"""クリップボードヘルパ。

QGIS 内では QApplication.clipboard() が全プラットフォームで使えるため、
外部クリップボードライブラリは不要。
"""

from qgis.PyQt.QtWidgets import QApplication


def copy(text):
    """テキストをシステムクリップボードへコピーする。"""
    app = QApplication.instance()
    if app is not None:
        app.clipboard().setText("" if text is None else str(text))
