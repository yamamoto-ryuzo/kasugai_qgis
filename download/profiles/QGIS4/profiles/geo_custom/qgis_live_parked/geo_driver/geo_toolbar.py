"""GeoSuite共有ツールバー。

管理対象プラグインのツールバー項目を1本の QToolBar(objectName="GeoSuite")
に集約する。各プラグインは find-or-create で共有するため、どのプラグインが
先に有効化されても同じツールバーに載る。

他プラグインはドライバ非依存で動く必要があるため、このfind-or-create
ロジックは各プラグイン側に同形の小ヘルパとして複製してある
(i18n_json.py の複製と同じ方針)。ドライバ自身はこのモジュールを使い、
先頭にモードバッジ(開発モード/利用モードの常時表示)を載せる。
"""

TOOLBAR_NAME = "GeoSuite"


def geo_suite_toolbar(iface, ensure_visible=True):
    """GeoSuiteツールバーを返す。無ければ作成する。

    ensure_visible=True(既定)では可視状態を保証する。
    項目追加経路では必ず True のまま使い、ドライバ非稼働の
    個別利用でもツールバーが表示されるようにする。
    unload時のremoveAction経路など表示を変えたくない場合は
    False を渡す。
    """
    from qgis.PyQt.QtWidgets import QToolBar
    tb = iface.mainWindow().findChild(QToolBar, TOOLBAR_NAME)
    if tb is None:
        tb = iface.addToolBar(TOOLBAR_NAME)
        tb.setObjectName(TOOLBAR_NAME)
    if ensure_visible:
        tb.setVisible(True)
    return tb
