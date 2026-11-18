# -*- coding: utf-8 -*-
"""QgsMessageLog ヘルパ。

QGIS4 では QgsMessageLog.logMessage の level は Qgis.MessageLevel 必須。
旧来の整数レベル(0=Info/1=Warning/2=Critical)をここで変換する。
qgis を遅延 import するため QGIS 外でも import 自体は失敗しない
(実行時は print へフォールバック)。
"""


def log_message(message, tag="GEO-search-plugin", level=0):
    """QgsMessageLog.logMessage 相当。整数レベル可・失敗しても例外を投げない。"""
    try:
        from qgis.core import QgsMessageLog, Qgis
        if isinstance(level, int):
            level = {
                0: Qgis.MessageLevel.Info,
                1: Qgis.MessageLevel.Warning,
                2: Qgis.MessageLevel.Critical,
            }.get(level, level)
        QgsMessageLog.logMessage(str(message), tag, level)
    except Exception:  # nosec B110  # QGIS外/ログ出力失敗時はprintへ(設計上の許容)
        try:
            print(f"{tag}: {message}")
        except Exception:  # nosec B110  # 設計上の許容
            pass
