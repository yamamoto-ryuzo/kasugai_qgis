# startup.py - QGIS起動時に自動実行されるスクリプト
# PORTAL_USERROLE 環境変数からユーザーロールを取得し、ロールに応じた設定を行う。
# ロール: Viewer / Editor / Administrator
#
# 動作タイミング:
#   1. 起動後500ms: UI制御 + QGISグローバル変数 'userrole' に設定
#   2. プロジェクト読み込みのたびに: Viewer の場合は全レイヤーを読み取り専用に設定

import os
from qgis.core import (
    QgsProject, QgsMessageLog, Qgis,
    QgsExpressionContextUtils, QgsVectorLayer
)
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QToolBar


def _get_role():
    """QGISグローバル変数 -> 環境変数の優先順でロールを返す"""
    role = QgsExpressionContextUtils.globalScope().variable('userrole')
    if not role:
        role = os.environ.get("PORTAL_USERROLE", "Viewer").strip()
    return role or "Viewer"


def set_all_layers_readonly():
    from qgis.utils import iface
    project = QgsProject.instance()
    layers = project.mapLayers().values()
    success_count = 0
    error_count = 0
    for layer in layers:
        if isinstance(layer, QgsVectorLayer):
            try:
                layer.setReadOnly(True)
                edit_form_config = layer.editFormConfig()
                for field_index in range(layer.fields().count()):
                    edit_form_config.setReadOnly(field_index, True)
                layer.setEditFormConfig(edit_form_config)
                success_count += 1
            except Exception as e:
                error_count += 1
                QgsMessageLog.logMessage(
                    f"{layer.name()} 設定エラー: {e}", "Portal", Qgis.Warning
                )
        else:
            QgsMessageLog.logMessage(
                f"{layer.name()} はベクターレイヤーではないためスキップします",
                "Portal", Qgis.Info
            )
    message = f"{success_count}個のレイヤーを読み取り専用に設定しました。"
    if error_count > 0:
        message += f" {error_count}個のレイヤーでエラーが発生しました。"
    iface.messageBar().pushMessage("情報", message, level=Qgis.Info, duration=5)


def on_project_read():
    """プロジェクト読み込み時に実行 - Viewer の場合は全レイヤーをロック"""
    role = _get_role()
    QgsMessageLog.logMessage(f"on_project_read: role={role}", "Portal", Qgis.Info)
    if role.lower() == 'viewer':
        set_all_layers_readonly()


def apply_role_settings():
    from qgis.utils import iface
    if iface is None:
        return

    role = os.environ.get("PORTAL_USERROLE", "Viewer").strip()
    QgsMessageLog.logMessage(f"Portal role: {role}", "Portal", Qgis.Info)

    # QGISグローバル変数にもセット（プロジェクト式・on_project_read で参照可能にする）
    QgsExpressionContextUtils.setGlobalVariable('userrole', role)

    try:
        if role.lower() == "viewer":
            # 編集ツールバーを非表示
            toolbar = iface.mainWindow().findChild(QToolBar, "mDigitizeToolBar")
            if toolbar:
                toolbar.setVisible(False)
            # 編集モードへの切り替えを無効化
            iface.actionToggleEditing().setEnabled(False)
            iface.actionSaveEdits().setEnabled(False)

        elif role.lower() in ("editor", "administrator"):
            # 編集ツールバーを表示（Viewer から切り替えた場合に非表示になっている可能性がある）
            toolbar = iface.mainWindow().findChild(QToolBar, "mDigitizeToolBar")
            if toolbar:
                toolbar.setVisible(True)
            # 編集ツールを有効にする
            iface.actionToggleEditing().setEnabled(True)
            iface.actionSaveEdits().setEnabled(True)

    except Exception as e:
        QgsMessageLog.logMessage(f"startup.py error: {e}", "Portal", Qgis.Warning)

    # プロジェクト読み込みのたびにレイヤー制御を適用
    iface.projectRead.connect(on_project_read)
    iface.initializationCompleted.connect(on_project_read)


# iface が利用可能になるまで少し待ってから実行
try:
    QTimer.singleShot(500, apply_role_settings)
except Exception as e:
    QgsMessageLog.logMessage(f"startup.py init error: {e}", "Portal", Qgis.Warning)
