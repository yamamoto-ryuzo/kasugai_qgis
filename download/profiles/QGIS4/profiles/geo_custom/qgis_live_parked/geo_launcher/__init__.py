# -*- coding: utf-8 -*-
"""geo_launcher - kasugai_qgis ランチャーのインストール/起動/連携"""


def classFactory(iface):  # pylint: disable=invalid-name
    from .plugin import plugin

    return plugin(iface)
