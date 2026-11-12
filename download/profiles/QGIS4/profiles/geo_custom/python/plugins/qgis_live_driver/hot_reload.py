"""開発用ホットリロード(手動)。

メニュー「プラグイン > QGIS Live Driver > ホットリロード」から、
開発対象のプラグインを手動で sys.modules 掃除+reloadPlugin
(+open_dialog再表示)する。QGIS再起動・deployは不要。

候補のプラグインidは、deploy先の各プラグインのrealpathが
<repo>/qgis-plugin/<id> に解決されるもの(junction配置)のみ。
実体配置(利用モード)やサードパーティプラグインは対象にしない。
"""

import os

try:
    from qgis.PyQt.QtCore import QCoreApplication
except ImportError:
    QCoreApplication = None

CTRL_ID = "qgis_live_driver"


def dev_plugin_ids(own_file):
    """ホットリロード候補のプラグインid一覧を返す。

    deploy先の各プラグインのrealpathが <repo>/qgis-plugin/ 配下に
    解決されるもの(junction配置)のid順。該当なしなら空。
    """
    deployed_dir = os.path.dirname(os.path.abspath(own_file))
    plugins_root = os.path.dirname(deployed_dir)
    ids = []
    try:
        for d in os.listdir(plugins_root):
            p = os.path.join(plugins_root, d)
            if not os.path.isdir(p):
                continue
            try:
                src = os.path.dirname(os.path.realpath(p))
            except Exception:  # nosec B112  # 設計上の許容
                continue
            if os.path.basename(src) == "qgis-plugin":
                ids.append(d)
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return sorted(ids)


def reload_plugins(ids, notify=None):
    """プラグインid群を順にリロードする。

    制御面の qgis_live_driver は最後(送信経路を先に殺さないため)。
    自プラグイン自身のリロードも可能(呼出中フレームは有効なまま)。
    notify は (level, msg) を受けるコールバック(level="info"/"warn")。
    """
    notify = notify or (lambda level, msg: None)
    for pid in sorted(ids, key=lambda p: (p == CTRL_ID, p)):
        try:
            from .live_driver import reload_plugin_now
            res = reload_plugin_now(pid)
            notify("info", QCoreApplication.translate(
                "qgis_live_driver", "Hot Reload: {0}").format(pid)
                + (QCoreApplication.translate(
                    "qgis_live_driver", " (dialog reopened)")
                   if res.get("opened") else ""))
        except Exception:
            notify("warn", QCoreApplication.translate(
                "qgis_live_driver", "Hot Reload failed: {0}").format(pid))
