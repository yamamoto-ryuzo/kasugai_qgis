# -*- coding: utf-8 -*-
"""geo_userfunc - ユーザー関数ライブラリ管理プラグイン"""


def classFactory(iface):  # pylint: disable=invalid-name
    from .plugin import plugin

    return plugin(iface)
