"""
Qt6 モジュールローダー (QGIS4/Qt6 前提、QGIS の qgis.PyQt を優先)

静的解析環境や QGIS がインポートできない環境でも解析/テストが走るよう、
動的にインポートする実装にしてある。また QgsMessageLog.logMessage に
旧来の整数レベル(0/1/2)を許容する monkey-patch を提供する。
"""
import importlib


def _import_module_candidates(candidates):
    """リスト中のモジュール名を順に試し、最初に import できたモジュールを返す。"""
    for name in candidates:
        try:
            return importlib.import_module(name)
        except Exception:  # nosec B112  # 設計上の許容
            continue
    return None


# Qt モジュール群を取得 (qgis.PyQt を優先)
QtCore = _import_module_candidates(['qgis.PyQt.QtCore', 'PyQt6.QtCore', 'PySide6.QtCore'])
QtGui = _import_module_candidates(['qgis.PyQt.QtGui', 'PyQt6.QtGui', 'PySide6.QtGui'])
QtWidgets = _import_module_candidates(['qgis.PyQt.QtWidgets', 'PyQt6.QtWidgets', 'PySide6.QtWidgets'])
uic = _import_module_candidates(['qgis.PyQt.uic', 'PyQt6.uic'])

# Qt のバージョン情報
QT_VERSION = (0, 0, 0)
if QtCore is not None:
    try:
        _qt_version = [int(v) for v in QtCore.qVersion().split('.') if v.isdigit()]
        QT_VERSION = tuple(_qt_version)
    except Exception:  # nosec B110  # 設計上の許容
        pass


# Signal alias: pyqtSignal / Signal のどちらかを使う
Signal = None
if QtCore is not None:
    Signal = getattr(QtCore, 'pyqtSignal', None) or getattr(QtCore, 'Signal', None)


__all__ = ['QtCore', 'QtGui', 'QtWidgets', 'uic', 'QT_VERSION', 'Signal']


# Monkey-patch QgsMessageLog.logMessage to accept legacy integer levels (0/1/2)
try:
    from qgis.core import QgsMessageLog, Qgis
    _orig_log = getattr(QgsMessageLog, 'logMessage', None)

    def _patched_log_message(message, tag='', level=None):
        try:
            # map legacy ints to Qgis.MessageLevel
            if isinstance(level, int):
                level = {0: Qgis.MessageLevel.Info, 1: Qgis.MessageLevel.Warning, 2: Qgis.MessageLevel.Critical}.get(level, level)
            if level is None:
                level = Qgis.MessageLevel.Info
        except Exception:  # nosec B110  # 設計上の許容
            # fallback: leave level as-is
            pass
        try:
            if _orig_log is not None:
                return _orig_log(message, tag, level)
        except Exception:
            # best-effort: print to stdout
            try:
                print(f"{tag}: {message}")
            except Exception:  # nosec B110  # 設計上の許容
                pass

    try:
        setattr(QgsMessageLog, 'logMessage', _patched_log_message)
    except Exception:  # nosec B110  # 設計上の許容
        # ignore if we cannot patch
        pass
except Exception:  # nosec B110  # 設計上の許容
    # qgis not available in this environment; ignore
    pass
