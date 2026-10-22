# -*- coding: utf-8 -*-
"""
/***************************************************************************
 geo_report - Layout Item Selector
                                 A QGIS plugin
 Comprehensive layout management plugin for efficient map production workflows
                              -------------------
        begin                : 2025-12-14
        version              : 2.2.0
        git sha              : $Format:%H$
        copyright            : (C) 2025 by yamamoto-ryuzo
        email                : ryu@yamakun.net
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

"""
Python コメント（操作説明）は日本語で記述
UI に表示されるテキストは英語で QCoreApplication.translate('geo_report', ...) でラップ
"""

from qgis.gui import QgsMapTool
import json
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import (QAction, QDialog, QVBoxLayout, QListWidget, QListWidgetItem,
                                 QPushButton, QHBoxLayout, QSplitter, QTextEdit, QLabel,
                                 QTreeWidget, QTreeWidgetItem, QLineEdit,
                                 QSpinBox, QDoubleSpinBox, QCheckBox, QFormLayout,
                                 QTabWidget, QWidget, QScrollArea, QFileDialog, QMessageBox,
                                 QDockWidget, QTabBar, QToolBar)
from qgis.core import (QgsProject, QgsLayoutItem, Qgis, QgsLayoutPoint,
                       QgsLayoutSize, QgsUnitTypes, QgsPointXY, QgsRectangle, QgsGeometry,
                       QgsWkbTypes, QgsMessageLog)
import os.path
import os


# Initialize Qt resources from file resources.py
try:
    from . import resources
except ImportError:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
    pass

USER_ROLE = Qt.ItemDataRole.UserRole
LEFT_DOCK_WIDGET_AREA = Qt.DockWidgetArea.LeftDockWidgetArea

# ログ出力関数


def log_message(message, level=Qgis.MessageLevel.Info):
    """QGIS のログメッセージタブに出力"""
    QgsMessageLog.logMessage(message, 'geo_report', level)


# --- 印刷範囲移動ツール（QgsMapToolサブクラス） ---
class PrintAreaMoveTool(QgsMapTool):
    """
    印刷範囲（RubberBand）をマウスでドラッグして移動できるツール
    """

    def __init__(self, canvas, rubberband, map_item, width_map, height_map, iface, parent_dialog):
        """
        初期化

        Args:
            canvas: QGIS マップキャンバス
            rubberband: 印刷範囲を表示するゴムバンド
            map_item: QgsLayoutItemMap インスタンス
            width_map: 地図アイテムの幅（座標単位）
            height_map: 地図アイテムの高さ（座標単位）
            iface: QGIS インターフェース
            parent_dialog: 親ダイアログ
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.rb = rubberband
        self.map_item = map_item
        self.width_map = width_map
        self.height_map = height_map
        self.iface = iface
        self.parent_dialog = parent_dialog
        self.dragging = False
        self.start_pos = None
        self.orig_center = None

    def canvasPressEvent(self, event):
        pos = self.canvas.getCoordinateTransform().toMapCoordinates(event.pos().x(), event.pos().y())
        geom = self.rb.asGeometry()
        if geom and geom.contains(QgsPointXY(pos)):
            self.dragging = True
            self.start_pos = pos
            self.orig_center = geom.centroid().asPoint()
        else:
            self.dragging = False

    def canvasMoveEvent(self, event):
        if not self.dragging:
            return
        pos = self.canvas.getCoordinateTransform().toMapCoordinates(event.pos().x(), event.pos().y())
        dx = pos.x() - self.start_pos.x()
        dy = pos.y() - self.start_pos.y()
        new_center = QgsPointXY(self.orig_center.x() + dx, self.orig_center.y() + dy)
        self._move_rubberband(new_center)

    def canvasReleaseEvent(self, event):
        if not self.dragging:
            return
        pos = self.canvas.getCoordinateTransform().toMapCoordinates(event.pos().x(), event.pos().y())
        dx = pos.x() - self.start_pos.x()
        dy = pos.y() - self.start_pos.y()
        new_center = QgsPointXY(self.orig_center.x() + dx, self.orig_center.y() + dy)
        # 角度を維持してrubberbandを移動
        self._move_rubberband(new_center)

        # QgsLayoutItemMapの範囲も、角度を維持して中心座標を移動
        w = self.width_map
        h = self.height_map
        # 角度取得（親ダイアログのangle_spinから）
        angle = 0.0
        if hasattr(self.parent_dialog, 'angle_spin'):
            angle = self.parent_dialog.angle_spin.value()
        # キャンバス自体の回転を加算し、画面上で回転していない矩形にする
        try:
            angle += float(self.canvas.rotation())
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass
        # QgsLayoutItemMapのextentは「回転前の表示領域」を表す。
        # 回転後の外接矩形(AABB)を渡すと印刷範囲が実表示より大きくなるため、
        # 回転なしの矩形(中心移動のみ)を設定し、回転はmapRotationに任せる。
        new_extent = QgsRectangle(
            new_center.x() - w / 2, new_center.y() - h / 2,
            new_center.x() + w / 2, new_center.y() + h / 2)
        if hasattr(self.map_item, 'setExtent'):
            self.map_item.setExtent(new_extent)
            # 地図内容の回転も維持
            if hasattr(self.map_item, 'setMapRotation'):
                self.map_item.setMapRotation(angle)
            if hasattr(self.map_item, 'refresh'):
                self.map_item.refresh()
        self.dragging = False
        self.iface.messageBar().pushMessage(
            QCoreApplication.translate('geo_report', "Information"), QCoreApplication.translate('geo_report', "Print area moved (angle preserved)"), level=Qgis.MessageLevel.Info, duration=2
        )

    def _move_rubberband(self, center):
        import math
        w = self.width_map
        h = self.height_map
        # 角度（度→ラジアン）
        angle = 0.0
        if hasattr(self.parent_dialog, 'angle_spin'):
            angle = self.parent_dialog.angle_spin.value()
        # キャンバス自体の回転を加算し、画面上で回転していない矩形にする
        try:
            angle += float(self.canvas.rotation())
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass
        theta = math.radians(angle)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        # 中心基準の矩形4頂点
        local_points = [
            (-w / 2, h / 2),  # 左上
            (w / 2, h / 2),  # 右上
            (w / 2, -h / 2),  # 右下
            (-w / 2, -h / 2),  # 左下
            (-w / 2, h / 2),  # 閉じる
        ]
        # 回転行列で回転し、中心座標を加算

        def rotate_point(x, y):
            return (
                center.x() + x * cos_t - y * sin_t,
                center.y() + x * sin_t + y * cos_t
            )
        rotated_points = [QgsPointXY(*rotate_point(x, y)) for (x, y) in local_points]
        self.rb.setToGeometry(QgsGeometry.fromPolygonXY([rotated_points]), None)


# -*- coding: utf-8 -*-
"""
/***************************************************************************
 geo_report - Layout Item Selector
                                 A QGIS plugin
 Comprehensive layout management plugin for efficient map production workflows
                              -------------------
        begin                : 2025-12-14
        version              : 2.2.0
        git sha              : $Format:%H$
        copyright            : (C) 2025 by yamamoto-ryuzo
        email                : ryu@yamakun.net
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

# 以下は上の統一された imports セクションで既に読み込まれているため削除


class GeoReport:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # 翻訳は __init__.py の _setup_language() で install 済み
        # Declare instance attributes
        self.actions = []
        self.menu = 'geo_report'
        self.first_start = None

        # パネルオブジェクト
        self.dialog = None
        self.dock_widget = None

        # AI/外部制御用ブリッジ。qgis_live_driver の bridge_call コマンドが
        # qgis.utils.plugins['geo_report'].bridge をプロセス内で直接呼ぶため、
        # ファイルJSONL/REST/MCP(qgis_bridge_call)の全経路から制御できる
        try:
            from .bridge import GeoReportBridge
            self.bridge = GeoReportBridge(self)
        except Exception:
            self.bridge = None

        # 起動ログ
        try:
            log_message('GeoReport plugin initialized')
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass

    def add_action(
            self,
            icon_path,
            text,
            callback,
            enabled_flag=True,
            add_to_menu=True,
            add_to_toolbar=True,
            status_tip=None,
            whats_this=None,
            parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # 共有ツールバーGeoSuiteに追加
            self._geo_toolbar().addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def _geo_toolbar(self):
        """GeoSuite共有ツールバーをfind-or-createで返す。"""
        tb = self.iface.mainWindow().findChild(QToolBar, "GeoSuite")
        if tb is None:
            tb = self.iface.addToolBar("GeoSuite")
            tb.setObjectName("GeoSuite")
        return tb

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        # アイコンパスを設定（リソースパスと代替パス）
        icon_path = ':/plugins/layout_item_selector/icon.png'

        # フォールバック用のアイコンパス
        import os
        fallback_icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')

        # アイコンが存在するかチェック
        icon = QIcon(icon_path)
        if icon.isNull():
            # リソースからロードできない場合は直接ファイルパスを使用
            icon = QIcon(fallback_icon_path)
            if not icon.isNull():
                icon_path = fallback_icon_path

        self.add_action(
            icon_path,
            text=QCoreApplication.translate('geo_report', 'Layout Selection'),
            callback=self.run,
            parent=self.iface.mainWindow())

        try:
            log_message('GeoReport plugin GUI registered')
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass

        # will be set False in run()
        self.first_start = True

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.menu,
                action)
            self._geo_toolbar().removeAction(action)

        # パネルを削除
        if self.dock_widget:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None

    def _on_dock_visibility_changed(self, visible):
        """ドックウィジェットの表示状態が変更されたときの処理"""
        if not visible:
            # パネルが非表示になったときに印刷枠を削除し、ボタンをShowにする
            log_message("Panel hidden; removing print area.", Qgis.MessageLevel.Info)
            if hasattr(self, 'dialog') and self.dialog:
                try:
                    self.dialog._remove_print_area_rubberband()
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass
                try:
                    btn = getattr(self.dialog, 'show_print_area_button', None)
                    if btn and hasattr(btn, 'setText'):
                        btn.setText(QCoreApplication.translate('geo_report', "Show Print Area on Map"))
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass
                try:
                    self.dialog._print_area_visible = False
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass
        else:
            # パネルが表示されたときは必ずボタンをHideにして印刷枠を復元する
            log_message("Panel shown; attempting to restore print area.", Qgis.MessageLevel.Info)
            if hasattr(self, 'dialog') and self.dialog:
                try:
                    btn = getattr(self.dialog, 'show_print_area_button', None)
                    if btn and hasattr(btn, 'setText'):
                        btn.setText(QCoreApplication.translate('geo_report', "Hide Print Area"))
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass
                try:
                    if not getattr(self.dialog, '_print_area_rubberband', None):
                        # ボタン経由で表示
                        btn = getattr(self.dialog, 'show_print_area_button', None)
                        if btn and hasattr(btn, 'click'):
                            try:
                                btn.click()
                            except Exception:
                                try:
                                    self.dialog.show_print_area_on_map()
                                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                                    pass
                        else:
                            try:
                                self.dialog.show_print_area_on_map()
                            except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                                pass
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass

    def run(self):
        """Run method that performs all the real work"""
        try:
            self.show_layout_selector()
        except Exception as e:
            import traceback
            error_msg = f"plugin startup error: {e}\n{traceback.format_exc()}"
            log_message(error_msg, Qgis.MessageLevel.Critical)
            self.iface.messageBar().pushCritical(
                "geo_report",
                QCoreApplication.translate('geo_report', "Error: {}").format(str(e))
            )

    def show_layout_selector(self):
        """レイアウト選択パネルを表示（ドックウィジェット）"""
        log_message("show_layout_selector started", Qgis.MessageLevel.Info)
        import glob
        import os
        from qgis.core import QgsReadWriteContext, QgsPrintLayout
        from qgis.PyQt.QtXml import QDomDocument
        project = QgsProject.instance()
        layout_manager = project.layoutManager()
        layouts = layout_manager.layouts()
        if not layouts:
            # composerフォルダ内の全qptをインポート（QgsLayoutImporterが使えない場合はloadFromTemplateで代用）
            composer_dir = os.path.join(self.plugin_dir, 'composer')
            qpt_files = glob.glob(os.path.join(composer_dir, '*.qpt'))
            imported = 0
            for qpt_path in qpt_files:
                layout_name = os.path.splitext(os.path.basename(qpt_path))[0]
                layout = QgsPrintLayout(project)
                layout.initializeDefaults()
                try:
                    with open(qpt_path, encoding='utf-8') as f:
                        template_content = f.read()
                    doc = QDomDocument()
                    doc.setContent(template_content)
                    context = QgsReadWriteContext()
                    layout.loadFromTemplate(doc, context)
                    if hasattr(layout, 'setName'):
                        layout.setName(layout_name)
                    else:
                        layout.name = layout_name
                    layout_manager.addLayout(layout)
                    imported += 1
                except Exception:
                    self.iface.messageBar().pushMessage(
                        QCoreApplication.translate('geo_report', "Warning"),
                        QCoreApplication.translate('geo_report', "Import failed") + f": {qpt_path}",
                        level=Qgis.MessageLevel.Warning,
                        duration=5
                    )
            # qpt登録後に必ず再取得
            layouts = layout_manager.layouts()
            if imported == 0:
                self.iface.messageBar().pushMessage(
                    QCoreApplication.translate('geo_report', "Warning"),
                    QCoreApplication.translate('geo_report', "Could not add layouts from composer folder."),
                    level=Qgis.MessageLevel.Warning,
                    duration=3
                )
                return
        if not layouts:
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Warning"),
                QCoreApplication.translate('geo_report', "Could not add layouts from composer folder."),
                level=Qgis.MessageLevel.Warning,
                duration=3
            )
            return
        log_message(f"creating LayoutSelectorDialog (layouts: {len(layouts)})", Qgis.MessageLevel.Info)
        try:
            # パネルが既に存在する場合は表示するだけ
            if self.dock_widget is None:
                # レイアウト選択ダイアログを作成
                self.dialog = LayoutSelectorDialog(layouts, self.iface)
                log_message("LayoutSelectorDialog created", Qgis.MessageLevel.Info)

                # ドックウィジェットを作成（UI 表示名は英語、翻訳対象）
                # タブ名が長かったため短縮して表示する
                self.dock_widget = QDockWidget(QCoreApplication.translate('geo_report', "report"), self.iface.mainWindow())
                self.dock_widget.setWidget(self.dialog)
                self.dock_widget.setObjectName("GeoReportLayoutSelectorPanel")

                # パネルが閉じられたときに印刷枠を削除
                self.dock_widget.visibilityChanged.connect(self._on_dock_visibility_changed)

                # 左エリアの既存のドックウィジェットを探してタブ化
                # 既存の中で「最後に見つかった（表示上は右/上位になる）」パネルをターゲットにする
                target_dock = None
                left_docks = []
                for widget in self.iface.mainWindow().findChildren(QDockWidget):
                    area = self.iface.mainWindow().dockWidgetArea(widget)
                    try:
                        if area == LEFT_DOCK_WIDGET_AREA and widget.isVisible():
                            left_docks.append(widget)
                    except Exception:  # nosec B112  # 例外は握り潰してGUIを継続(設計上の許容)
                        continue
                if left_docks:
                    # 左側ドック群のうち「高さ（ピクセル）が最大」のウィジェットをターゲットにする
                    # frameGeometry().height() を優先的に使用し、取得できない場合は widget.size().height() を参照
                    def _height(w):
                        try:
                            h = w.frameGeometry().height()
                            if h:
                                return h
                        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                            pass
                        try:
                            return w.size().height()
                        except Exception:
                            return 0

                    try:
                        target_dock = max(left_docks, key=_height)
                    except Exception:
                        target_dock = left_docks[0]

                if target_dock:
                    # 既存のドックが見つかった場合、タブ化して追加
                    self.iface.addDockWidget(LEFT_DOCK_WIDGET_AREA, self.dock_widget)
                    # ターゲットドックにタブとして追加
                    self.iface.mainWindow().tabifyDockWidget(target_dock, self.dock_widget)
                    # タブバー上で新しく追加したタブを先頭（上位）に移動する
                    try:
                        title = self.dock_widget.windowTitle()
                        moved = False
                        for tabbar in self.iface.mainWindow().findChildren(QTabBar):
                            for idx in range(tabbar.count()):
                                try:
                                    if tabbar.tabText(idx) == title:
                                        # moveTab(from, to)
                                        try:
                                            # move the tab to the rightmost position
                                            tabbar.moveTab(idx, tabbar.count() - 1)
                                        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                                            pass
                                        moved = True
                                        break
                                except Exception:  # nosec B112  # 例外は握り潰してGUIを継続(設計上の許容)
                                    continue
                            if moved:
                                break
                    except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                        pass
                else:
                    # 既存のドックがない場合は通常追加
                    self.iface.addDockWidget(LEFT_DOCK_WIDGET_AREA, self.dock_widget)

                # 作成したパネルをアクティブに
                self.dock_widget.raise_()

                log_message("dock widget created (tabbed)", Qgis.MessageLevel.Info)
            else:
                # 既存のパネルを表示/非表示を切り替え
                if self.dock_widget.isVisible():
                    self.dock_widget.hide()
                else:
                    self.dock_widget.show()
                    self.dock_widget.raise_()
                    self.dock_widget.activateWindow()

        except Exception as e:
            import traceback
            error_msg = f"LayoutSelectorDialog creation failed: {e}\n{traceback.format_exc()}"
            log_message(error_msg, Qgis.MessageLevel.Critical)
            raise
        log_message("panel shown", Qgis.MessageLevel.Info)


class LayoutSelectorDialog(QDialog):
    def _remove_print_area_rubberband(self, silent=False):
        # rubberbandが存在する場合のみ削除
        rb = getattr(self, '_print_area_rubberband', None)
        if rb:
            print(f"[DEBUG] rubberband removal start: {rb}")
            try:
                # rubberbandをcanvasから明示的に削除
                if hasattr(rb, 'hide'):
                    rb.hide()
                if hasattr(rb, 'canvas'):
                    canvas = rb.canvas()
                    if hasattr(canvas, 'scene'):
                        try:
                            canvas.scene().removeItem(rb)
                            print("[DEBUG] scene.removeItem executed")
                        except Exception as e:
                            print(f"[DEBUG] scene.removeItem failed: {e}")
                try:
                    rb.reset()
                    print("[DEBUG] rubberband.reset() executed")
                except Exception as e:
                    print(f"[DEBUG] rubberband reset failed: {e}")
                # 削除メッセージを表示(描き直し時は抑止)
                if not silent and hasattr(self, 'iface') and hasattr(self.iface, 'messageBar'):
                    self.iface.messageBar().pushMessage(
                        QCoreApplication.translate('geo_report', "Information"), QCoreApplication.translate('geo_report', "Print area removed."), level=Qgis.MessageLevel.Info, duration=3
                    )
            except Exception as e:
                print(f"[DEBUG] rubberband removal exception: {e}")
            self._print_area_rubberband = None

            # 印刷範囲移動ツールも解除
            if hasattr(self, '_print_area_move_tool'):
                try:
                    if hasattr(self.iface, 'mapCanvas'):
                        canvas = self.iface.mapCanvas()
                        if hasattr(canvas, 'unsetMapTool'):
                            canvas.unsetMapTool(self._print_area_move_tool)
                        elif hasattr(canvas, 'setMapTool'):
                            canvas.setMapTool(None)
                except Exception as e:
                    print(f"[DEBUG] map tool release exception: {e}")
                self._print_area_move_tool = None
        else:
            print("[DEBUG] rubberband removal: nothing to remove")

    def closeEvent(self, event):
        self._remove_print_area_rubberband()
        try:
            if hasattr(self.iface, 'mapCanvas'):
                canvas = self.iface.mapCanvas()
                canvas.refresh()
                if hasattr(canvas, 'unsetMapTool'):
                    canvas.unsetMapTool(None)
                elif hasattr(canvas, 'setMapTool'):
                    canvas.setMapTool(None)
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass
        # パネルの場合は非表示にするだけで、削除しない
        event.ignore()  # closeイベントを無視（パネル非表示）
        if hasattr(self, 'parent') and isinstance(self.parent(), QDockWidget):
            self.parent().hide()
        super().closeEvent(event)

    def reject(self):
        self._remove_print_area_rubberband()
        # rubberband消去を即時反映し、map toolも解除
        try:
            if hasattr(self.iface, 'mapCanvas'):
                canvas = self.iface.mapCanvas()
                canvas.refresh()
                # RubberBandの残像を消すためにmap toolをNoneに
                if hasattr(canvas, 'unsetMapTool'):
                    canvas.unsetMapTool(None)
                elif hasattr(canvas, 'setMapTool'):
                    canvas.setMapTool(None)
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass
        # パネルの場合は非表示にするだけで、削除しない
        if hasattr(self, 'parent') and isinstance(self.parent(), QDockWidget):
            self.parent().hide()
        else:
            super().reject()

    def accept(self):
        self._remove_print_area_rubberband()
        try:
            if hasattr(self.iface, 'mapCanvas'):
                canvas = self.iface.mapCanvas()
                canvas.refresh()
                if hasattr(canvas, 'unsetMapTool'):
                    canvas.unsetMapTool(None)
                elif hasattr(canvas, 'setMapTool'):
                    canvas.setMapTool(None)
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass
        # パネルの場合は非表示にするだけで、削除しない
        if hasattr(self, 'parent') and isinstance(self.parent(), QDockWidget):
            self.parent().hide()
        else:
            super().accept()


# --- 印刷範囲移動ツール（QgsMapToolサブクラス）をファイル先頭に定義 ---

    """レイアウト選択ダイアログ"""

    def __init__(self, layouts, iface):
        super().__init__()
        self.layouts = layouts
        self.iface = iface
        self.current_layout = None
        self.init_ui()
        # キャンバス回転時は表示中の印刷枠を描き直し、画面に沿った向きを維持する
        try:
            self.iface.mapCanvas().rotationChanged.connect(self._refresh_print_area)
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass

    def init_ui(self):
        """UIを初期化"""
        self.setWindowTitle(QCoreApplication.translate('geo_report', "Layout Selection & Item Management"))
        self.setModal(False)  # モデルレスにして他の操作も可能にする
        # パネル化のためresize()は不要（パネルサイズはQGISが管理）

        # メインレイアウト（垂直）
        main_layout = QVBoxLayout()

        # 上部：左側（レイアウトリスト）+ 右側（ボタン類 + アイテムリスト）
        top_layout = QHBoxLayout()

        # 左側パネル - レイアウトリスト
        left_panel = QWidget()
        left_layout = QVBoxLayout()

        layout_label = QLabel(QCoreApplication.translate('geo_report', "Layout List:"))
        left_layout.addWidget(layout_label)

        self.layout_list = QListWidget()

        # レイアウト選択時にアイテム情報を更新
        self.layout_list.currentItemChanged.connect(self.on_layout_selected)
        self.layout_list.itemDoubleClicked.connect(self.open_layout_manager)

        self.reload_layout_list()
        left_layout.addWidget(self.layout_list)

        # レイアウトマネージャ等パネル外での追加・削除・名前変更を一覧へ自動反映
        self._connect_layout_manager_signals()

        # 標準レイアウト追加ボタン(空のプロジェクト向けにcomposer/*.qptを追加)
        self.add_std_layout_button = QPushButton(
            QCoreApplication.translate('geo_report', "Add Standard Layout"))
        self.add_std_layout_button.clicked.connect(self.add_standard_layout)
        left_layout.addWidget(self.add_std_layout_button)

        # レイアウトマネージャ起動ボタン(削除・複製・名前変更はQGIS標準機能で行う)
        self.layout_manager_button = QPushButton(
            QCoreApplication.translate('geo_report', "Open Layout Manager"))
        self.layout_manager_button.clicked.connect(self.open_layout_manager_dialog)
        left_layout.addWidget(self.layout_manager_button)

        # --- スケール入力欄を追加 ---
        scale_layout = QHBoxLayout()
        scale_label = QLabel(QCoreApplication.translate('geo_report', "Scale:"))
        scale_layout.addWidget(scale_label)

        class ScaleSpinBox(QDoubleSpinBox):
            def stepBy(self, steps):
                import math
                value = self.value()
                step = max(1, value * 0.05)
                value += step * steps
                # 有効数字2桁で丸める
                if value > 0:
                    digits = int(math.floor(math.log10(abs(value))))
                    rounded = round(value, -digits + 1)
                else:
                    rounded = value
                self.setValue(rounded)

        self.scale_spin = ScaleSpinBox()
        self.scale_spin.setDecimals(2)
        self.scale_spin.setRange(1, 100000000)
        self.scale_spin.setValue(1000.0)
        self.scale_spin.setSingleStep(100.0)  # 実際のステップはstepByで制御
        # スケール値が変更されたときに印刷範囲を描き直す(表示中のみ)
        self.scale_spin.valueChanged.connect(self._refresh_print_area)
        scale_layout.addWidget(self.scale_spin)
        left_layout.addLayout(scale_layout)

        # --- 角度入力欄を追加 ---
        angle_layout = QHBoxLayout()
        angle_label = QLabel(QCoreApplication.translate('geo_report', "Angle:"))
        angle_layout.addWidget(angle_label)
        # 角度を0度へリセットする小ボタン(issue #4)
        self.angle_reset_button = QPushButton("0°")
        self.angle_reset_button.setToolTip(
            QCoreApplication.translate('geo_report', "Reset angle to 0°"))
        self.angle_reset_button.setFixedWidth(40)
        self.angle_reset_button.clicked.connect(
            lambda: self.angle_spin.setValue(0.0))
        angle_layout.addWidget(self.angle_reset_button)
        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setDecimals(2)
        self.angle_spin.setRange(-360.0, 360.0)
        self.angle_spin.setValue(0.0)
        self.angle_spin.setSingleStep(1.0)
        angle_layout.addWidget(self.angle_spin)
        left_layout.addLayout(angle_layout)
        # 角度値が変更されたときに印刷範囲を描き直す(表示中のみ)
        self.angle_spin.valueChanged.connect(self._refresh_print_area)

        left_panel.setLayout(left_layout)
        left_panel.setMaximumWidth(250)

        # 右側パネル - 垂直分割（アイテムリスト + ボタン類）
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # アイテムリスト（上部）
        items_widget = QWidget()
        items_layout = QVBoxLayout()

        items_label = QLabel(QCoreApplication.translate('geo_report', "Layout Items:"))
        items_layout.addWidget(items_label)

        self.items_tree = QTreeWidget()
        self.items_tree.setHeaderLabels([
            QCoreApplication.translate('geo_report', "Item Name"),
            QCoreApplication.translate('geo_report', "Type"),
            QCoreApplication.translate('geo_report', "Visible")
        ])
        self.items_tree.currentItemChanged.connect(self.on_item_selected)
        # ダブルクリックでプロパティを直接編集画面に移動
        self.items_tree.itemDoubleClicked.connect(self.focus_on_properties)
        # カラム幅を調整
        self.items_tree.setColumnWidth(0, 150)  # アイテム名
        self.items_tree.setColumnWidth(1, 80)   # タイプ
        self.items_tree.setColumnWidth(2, 60)   # 表示
        items_layout.addWidget(self.items_tree)

        items_widget.setLayout(items_layout)
        right_splitter.addWidget(items_widget)

        # ボタン類（下部）
        buttons_widget = QWidget()
        button_layout = QVBoxLayout()

        self.show_print_area_button = QPushButton(QCoreApplication.translate('geo_report', "Show Print Area on Map"))
        self.show_print_area_button.clicked.connect(self.show_print_area_on_map)
        self.show_print_area_button.setEnabled(False)
        button_layout.addWidget(self.show_print_area_button)

        self.refresh_button = QPushButton(QCoreApplication.translate('geo_report', "Refresh Item Info"))
        self.refresh_button.clicked.connect(self.refresh_item_info)
        self.refresh_button.setEnabled(False)
        button_layout.addWidget(self.refresh_button)

        # レイアウト全体の保存・読み込みボタン
        self.save_layout_button = QPushButton(QCoreApplication.translate('geo_report', "Save Layout"))
        self.save_layout_button.clicked.connect(self.save_layout_properties)
        self.save_layout_button.setEnabled(False)
        button_layout.addWidget(self.save_layout_button)

        self.load_layout_button = QPushButton(QCoreApplication.translate('geo_report', "Load Layout"))
        self.load_layout_button.clicked.connect(self.load_layout_properties)
        self.load_layout_button.setEnabled(False)
        button_layout.addWidget(self.load_layout_button)

        button_layout.addStretch()

        # レポート作成ボタン（最下部、高さ2倍）
        self.open_button = QPushButton(QCoreApplication.translate('geo_report', "Create Report"))
        self.open_button.clicked.connect(self.open_layout_manager)
        self.open_button.setEnabled(False)
        self.open_button.setMinimumHeight(60)  # 高さを2倍に
        button_layout.addWidget(self.open_button)
        buttons_widget.setLayout(button_layout)
        right_splitter.addWidget(buttons_widget)
        right_splitter.setSizes([150, 150])

        # 上部レイアウトに左右を追加
        top_layout.addWidget(left_panel)
        top_layout.addWidget(right_splitter)

        # プロパティパネル（下部全幅）- タブ化
        properties_container = QWidget()
        properties_container_layout = QVBoxLayout()

        # タブウィジェット
        tab_widget = QTabWidget()

        # プロパティタブ
        properties_widget = QWidget()
        properties_layout = QVBoxLayout()
        properties_label = QLabel(QCoreApplication.translate('geo_report', "Selected Item Properties:"))
        properties_layout.addWidget(properties_label)
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        self.properties_form = QFormLayout()
        scroll_widget.setLayout(self.properties_form)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        properties_layout.addWidget(scroll_area)
        properties_widget.setLayout(properties_layout)

        # レイアウト情報タブ
        info_widget = QWidget()
        info_layout = QVBoxLayout()
        info_label = QLabel(QCoreApplication.translate('geo_report', "Layout Information:"))
        info_layout.addWidget(info_label)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        info_layout.addWidget(self.info_text)
        info_widget.setLayout(info_layout)

        # タブ追加
        self.tab_widget = tab_widget
        tab_widget.addTab(properties_widget, QCoreApplication.translate('geo_report', "Item Properties"))
        tab_widget.addTab(info_widget, QCoreApplication.translate('geo_report', "Layout Info"))
        try:
            tab_widget.currentChanged.connect(self.on_tab_changed)
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass

        properties_container_layout.addWidget(tab_widget)

        # Apply Properties ボタン
        properties_buttons_layout = QHBoxLayout()
        update_properties_btn = QPushButton(QCoreApplication.translate('geo_report', "Apply Properties"))
        update_properties_btn.clicked.connect(self.update_item_properties)
        properties_buttons_layout.addWidget(update_properties_btn)
        properties_container_layout.addLayout(properties_buttons_layout)

        properties_container.setLayout(properties_container_layout)

        # メインレイアウトに追加
        main_layout.addLayout(top_layout, 1)  # 上部
        main_layout.addWidget(properties_container, 1)  # 下部全幅

        self.setLayout(main_layout)
        # 最初のレイアウトを選択
        if self.layout_list.count() > 0:
            self.layout_list.setCurrentRow(0)

    def _layout_size_str(self, qgs_layout):
        """レイアウト一覧表示用のサイズ文字列(「297.0×210.0mm」等)を返す"""
        try:
            map_items = [item for item in qgs_layout.items() if item.__class__.__name__ == 'QgsLayoutItemMap']
            if map_items:
                def map_item_area(m):
                    if hasattr(m, 'sizeWithUnits'):
                        s = m.sizeWithUnits()
                        return s.width() * s.height()
                    return 0
                max_map_item = max(map_items, key=map_item_area)
                if hasattr(max_map_item, 'sizeWithUnits'):
                    s = max_map_item.sizeWithUnits()
                    width = s.width()
                    height = s.height()
                    if height >= width:
                        return f"（{height:.1f}×{width:.1f}mm）"
                    else:
                        return f"（{width:.1f}×{height:.1f}mm）"
                return ""
            page_collection = qgs_layout.pageCollection()
            if page_collection.pageCount() > 0:
                page = page_collection.page(0)
                width = page.pageSize().width()
                height = page.pageSize().height()
                if height >= width:
                    return f"（{height:.1f}×{width:.1f}mm）"
                else:
                    return f"（{width:.1f}×{height:.1f}mm）"
            return ""
        except Exception:
            return ""

    def reload_layout_list(self):
        """プロジェクトのレイアウト一覧を再取得してリストを再構築する。

        選択中レイアウトは名前で復元する。選択中レイアウト自体が
        削除されていた場合は選択解除・ボタン無効化・印刷範囲を消去する。
        """
        # 選択中レイアウト名を保持(削除済みC++オブジェクトはRuntimeError)
        cur = getattr(self, 'current_layout', None)
        had_selection = cur is not None
        prev_name = None
        if cur is not None:
            try:
                prev_name = cur.name()
            except RuntimeError:
                prev_name = None
        self.layouts = QgsProject.instance().layoutManager().layouts()
        restored = False
        self.layout_list.blockSignals(True)
        self.layout_list.clear()
        for qgs_layout in self.layouts:
            size_str = self._layout_size_str(qgs_layout)
            item = QListWidgetItem(f"{qgs_layout.name()} {size_str}")
            item.setData(USER_ROLE, qgs_layout)
            self.layout_list.addItem(item)
        # QListViewはclear後の再構築で遅延の自動選択を内部キューイングし、
        # 次のsetCurrentIndex系呼出時にフラッシュされる。ここで抑止状態の
        # ままフラッシュしておき、遅延発火による意図しない選択を防ぐ
        self.layout_list.setCurrentItem(None)
        if prev_name is not None:
            # 同名レイアウトが残っていれば選択を復元(シグナル抑止で再選択のみ)
            for row, qgs_layout in enumerate(self.layouts):
                if qgs_layout.name() == prev_name:
                    self.layout_list.setCurrentRow(row)
                    restored = True
                    break
        self.layout_list.blockSignals(False)
        if had_selection and not restored:
            # 選択中レイアウトが削除された → 関連状態を全てクリア
            self.current_layout = None
            self._remove_print_area_rubberband()
            self.clear_item_info()
            for btn in (self.open_button, self.refresh_button,
                        self.show_print_area_button, self.save_layout_button,
                        self.load_layout_button):
                try:
                    btn.setEnabled(False)
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass

    def _connect_layout_manager_signals(self):
        """layoutManagerの追加/削除/名前変更シグナルで一覧を自動再読込する"""
        mgr = QgsProject.instance().layoutManager()
        if mgr is None:
            return
        for sig_name in ("layoutAdded", "layoutRemoved", "layoutRenamed"):
            try:
                getattr(mgr, sig_name).connect(self._on_layouts_changed)
            except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                pass

    def _on_layouts_changed(self, *args):
        """レイアウト構成の変更時に一覧を再読込する"""
        try:
            self.reload_layout_list()
        except RuntimeError:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            # ダイアログ破棄後にシグナルが来た場合等は何もしない
            pass

    def open_layout_manager_dialog(self):
        """QGIS標準レイアウトマネージャ(削除・複製・名前変更が可能)を開く"""
        opened = False
        # ifaceのアクション名はQGISバージョンで2系統ある
        for attr in ("actionShowLayoutManager", "actionLayoutManager"):
            try:
                action = getattr(self.iface, attr, None)
                action = action() if callable(action) else action
                if action is not None:
                    action.trigger()
                    opened = True
                    break
            except Exception:  # nosec B112  # 例外は握り潰してGUIを継続(設計上の許容)
                continue
        if not opened:
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Error"),
                QCoreApplication.translate('geo_report', "Error: {}").format(
                    "layout manager action not found"),
                level=Qgis.MessageLevel.Critical, duration=5)
            return
        # モーダル閉鎖後(非モーダルなら即時)に一覧を再読込
        self.reload_layout_list()

    def add_standard_layout(self):
        """同梱 composer/*.qpt の標準レイアウトをプロジェクトへ追加する"""
        import glob
        import os
        from qgis.core import QgsReadWriteContext, QgsPrintLayout
        from qgis.PyQt.QtXml import QDomDocument
        from qgis.PyQt.QtWidgets import QInputDialog
        composer_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'composer')
        qpt_files = sorted(glob.glob(os.path.join(composer_dir, '*.qpt')))
        if not qpt_files:
            QMessageBox.warning(
                self,
                QCoreApplication.translate('geo_report', "Add Standard Layout"),
                QCoreApplication.translate('geo_report', "No standard layout templates were found."))
            return
        names = [os.path.splitext(os.path.basename(p))[0] for p in qpt_files]
        name, ok = QInputDialog.getItem(
            self,
            QCoreApplication.translate('geo_report', "Add Standard Layout"),
            QCoreApplication.translate('geo_report', "Select a standard layout:"),
            names, 0, False)
        if not ok or not name:
            return
        qpt_path = qpt_files[names.index(name)]
        try:
            with open(qpt_path, encoding='utf-8') as f:
                template_content = f.read()
            doc = QDomDocument()
            doc.setContent(template_content)
            project = QgsProject.instance()
            layout_manager = project.layoutManager()
            layout = QgsPrintLayout(project)
            layout.initializeDefaults()
            res = layout.loadFromTemplate(doc, QgsReadWriteContext())
            # QGIS4では(items, ok)タプル、QGIS3ではboolを返す
            if isinstance(res, (tuple, list)):
                ok = bool(res[1]) if len(res) > 1 else bool(res[0])
            else:
                ok = bool(res)
            if not ok:
                raise RuntimeError('loadFromTemplate failed')
            # 同名レイアウトがあれば連番でユニーク化
            existing = {ly.name() for ly in layout_manager.layouts()}
            new_name = name
            i = 2
            while new_name in existing:
                new_name = f"{name}_{i}"
                i += 1
            layout.setName(new_name)
            layout_manager.addLayout(layout)
        except Exception as e:
            QMessageBox.warning(
                self,
                QCoreApplication.translate('geo_report', "Add Standard Layout"),
                QCoreApplication.translate('geo_report', "Import failed") + f": {e}")
            return
        self.reload_layout_list()
        # 追加したレイアウトを選択状態にする
        for row in range(self.layout_list.count()):
            it = self.layout_list.item(row)
            if it is not None and it.data(USER_ROLE) is layout:
                self.layout_list.setCurrentRow(row)
                break
        self.iface.messageBar().pushMessage(
            QCoreApplication.translate('geo_report', "Information"),
            QCoreApplication.translate('geo_report', "Standard layout added: {}").format(new_name),
            level=Qgis.MessageLevel.Info, duration=3)

    def retranslate_tabs(self):
        """Retranslate tab titles (call on language change)"""
        if hasattr(self, 'tab_widget'):
            self.tab_widget.setTabText(0, QCoreApplication.translate('geo_report', "Item Properties"))
            self.tab_widget.setTabText(1, QCoreApplication.translate('geo_report', "Layout Info"))

    def on_tab_changed(self, index):
        """タブが切り替わったときの処理。
        プロパティタブ(インデックス0)を離れる場合は印刷範囲を削除してボタンを「Show」に。
        戻る場合はボタンを「Hide」にして印刷範囲を再表示します。
        """
        try:
            # leaving properties tab
            if index != 0:
                if getattr(self, '_print_area_rubberband', None):
                    try:
                        self._remove_print_area_rubberband()
                    except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                        pass
                try:
                    if hasattr(self, 'show_print_area_button'):
                        self.show_print_area_button.setText(QCoreApplication.translate('geo_report', "Show Print Area on Map"))
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass
                try:
                    self._print_area_visible = False
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass
            else:
                # returning to properties tab: set button to Hide and restore
                try:
                    if hasattr(self, 'show_print_area_button'):
                        self.show_print_area_button.setText(QCoreApplication.translate('geo_report', "Hide Print Area"))
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass
                if not getattr(self, '_print_area_rubberband', None):
                    try:
                        # use button click to ensure same side-effects
                        btn = getattr(self, 'show_print_area_button', None)
                        if btn and hasattr(btn, 'click'):
                            btn.click()
                        else:
                            self.show_print_area_on_map()
                    except Exception:
                        try:
                            self.show_print_area_on_map()
                        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                            pass
                try:
                    self._print_area_visible = True
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass

    def on_layout_selected(self, current, previous):
        """レイアウトが選択された時の処理"""
        if current is None:
            self.current_layout = None
            self.open_button.setEnabled(False)
            self.refresh_button.setEnabled(False)
            self.show_print_area_button.setEnabled(False)
            self.save_layout_button.setEnabled(False)
            self.load_layout_button.setEnabled(False)
            self.clear_item_info()
            return

        self.current_layout = current.data(USER_ROLE)
        self.open_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.show_print_area_button.setEnabled(True)
        self.save_layout_button.setEnabled(True)
        self.load_layout_button.setEnabled(True)
        self.load_layout_items()
        self.load_layout_info()

        # 表示範囲の80%が印刷範囲となるようにスケールを自動計算
        map_items = [item for item in self.current_layout.items() if item.__class__.__name__ == 'QgsLayoutItemMap']
        if map_items and hasattr(map_items[0], 'setScale'):
            import math
            # 地図キャンバスの表示範囲
            # キャンバス回転時は extent() が回転表示領域の外接矩形を返すため、
            # mapUnitsPerPixel × 画面ピクセル数で実際の表示幅・高さを求める
            canvas = self.iface.mapCanvas()
            try:
                mupp = canvas.mapSettings().mapUnitsPerPixel()
                canvas_width = canvas.width() * mupp
                canvas_height = canvas.height() * mupp
            except Exception:
                extent = canvas.extent()
                canvas_width = extent.width()
                canvas_height = extent.height()
            # レイアウトのページサイズ（mm）
            try:
                page_collection = self.current_layout.pageCollection()
                if page_collection.pageCount() > 0:
                    page = page_collection.page(0)
                    page_width_mm = page.pageSize().width()
                    page_height_mm = page.pageSize().height()
                else:
                    page_width_mm = 210
                    page_height_mm = 297
            except Exception:
                page_width_mm = 210
                page_height_mm = 297

            # スケール計算（縦横別々に計算し、小さい方を採用＝全体が表示範囲に収まる）
            scale_w = (canvas_width * 1000.0) / (page_width_mm * 1.2) if page_width_mm > 0 else 1000.0
            scale_h = (canvas_height * 1000.0) / (page_height_mm * 1.2) if page_height_mm > 0 else 1000.0
            new_scale = min(scale_w, scale_h)
            # 有効数字2桁で丸める
            if new_scale > 0:
                digits = int(math.floor(math.log10(abs(new_scale))))
                rounded_scale = round(new_scale, -digits + 1)
            else:
                rounded_scale = new_scale
            map_items[0].setScale(rounded_scale)
            self.scale_spin.setValue(rounded_scale)
            # レイアウト選択時は必ず印刷範囲を表示（既存のrubberbandは削除してから表示）
            if hasattr(self, '_print_area_rubberband') and self._print_area_rubberband:
                self._remove_print_area_rubberband()
            self.show_print_area_on_map()

    def show_print_area_on_map(self, *_args, center=None):
        from qgis.gui import QgsRubberBand
        """選択中レイアウトの印刷範囲（ページサイズ・スケール考慮）を地図キャンバスに表示/非表示切り替え。
        centerにQgsPointXYを渡すとキャンバス中心ではなくその位置に枠を作る(再描画用)。"""
        # 既存のrubberbandがある場合は非表示にして終了（トグル）
        if hasattr(self, '_print_area_rubberband') and self._print_area_rubberband:
            self._remove_print_area_rubberband()
            # ボタンテキストを「表示」に変更
            self.show_print_area_button.setText(QCoreApplication.translate('geo_report', "Show Print Area on Map"))
            return

        # スケール・角度値を取得
        scale = self.scale_spin.value() if hasattr(self, 'scale_spin') else None
        angle = self.angle_spin.value() if hasattr(self, 'angle_spin') else 0.0

        if not self.current_layout:
            return

        # 地図アイテム(QgsLayoutItemMap)を探す
        map_items = [item for item in self.current_layout.items() if item.__class__.__name__ == 'QgsLayoutItemMap']
        if not map_items:
            return

        map_item = map_items[0]  # 先頭の地図アイテムを使う

        # スケール欄の値を取得して設定
        scale = self.scale_spin.value()
        if hasattr(map_item, 'setScale'):
            map_item.setScale(scale)

        # レイアウトのページサイズ（mm）を取得
        try:
            page_collection = self.current_layout.pageCollection()
            if page_collection.pageCount() > 0:
                page = page_collection.page(0)
                page_width_mm = page.pageSize().width()
                page_height_mm = page.pageSize().height()
            else:
                return
        except Exception:
            return

        # mm → m
        _ = page_width_mm / 1000.0
        _ = page_height_mm / 1000.0

        # 最大の地図アイテム(QgsLayoutItemMap)のサイズから幅・高さを取得し、スケールで地物座標単位に変換
        map_items = [item for item in self.current_layout.items() if item.__class__.__name__ == 'QgsLayoutItemMap']
        if map_items:
            def map_item_area(m):
                if hasattr(m, 'sizeWithUnits'):
                    s = m.sizeWithUnits()
                    return s.width() * s.height()
                return 0
            max_map_item = max(map_items, key=map_item_area)
            if hasattr(max_map_item, 'sizeWithUnits'):
                s = max_map_item.sizeWithUnits()
                # mm → m → 地物座標単位（スケール反映）
                width_map = (s.width() / 1000.0) * scale
                height_map = (s.height() / 1000.0) * scale
            else:
                width_map = (page_width_mm / 1000.0) * scale
                height_map = (page_height_mm / 1000.0) * scale
        else:
            width_map = (page_width_mm / 1000.0) * scale
            height_map = (page_height_mm / 1000.0) * scale

        # 画面（地図キャンバス）の中心座標を取得
        # 再描画(center指定)時はドラッグ移動済みの枠中心を維持する
        canvas = self.iface.mapCanvas()
        if center is not None:
            cx = center.x()
            cy = center.y()
        else:
            canvas_center = canvas.extent().center()
            cx = canvas_center.x()
            cy = canvas_center.y()

        # キャンバス自体が回転している場合はその角度を加算し、
        # 印刷枠が画面上で回転していない(画面に沿った)矩形になるようにする。
        # mapRotationにも同じ角度が入るため印刷結果は画面表示と同じ向きになる。
        try:
            angle += float(canvas.rotation())
        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass

        # 矩形の四隅を計算（画面中心基準）
        import math
        cx = float(cx)
        cy = float(cy)
        w = width_map
        h = height_map
        # 角度（度→ラジアン）
        theta = math.radians(angle)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        # 中心基準の矩形4頂点
        local_points = [
            (-w / 2, h / 2),  # 左上
            (w / 2, h / 2),  # 右上
            (w / 2, -h / 2),  # 右下
            (-w / 2, -h / 2),  # 左下
            (-w / 2, h / 2),  # 閉じる
        ]
        # 回転行列で回転し、中心座標を加算

        def rotate_point(x, y):
            return (
                cx + x * cos_t - y * sin_t,
                cy + x * sin_t + y * cos_t
            )
        rotated_points = [QgsPointXY(*rotate_point(x, y)) for (x, y) in local_points]

        # 地図アイテム(QgsLayoutItemMap)をすべて検索し、スケール・回転・印刷範囲を画面中心に設定
        map_items = [item for item in self.current_layout.items() if item.__class__.__name__ == 'QgsLayoutItemMap']

        # 画面中心を基準にした印刷範囲を計算（回転なしの矩形）
        xmin = cx - width_map / 2
        xmax = cx + width_map / 2
        ymin = cy - height_map / 2
        ymax = cy + height_map / 2
        new_extent = QgsRectangle(xmin, ymin, xmax, ymax)

        for m in map_items:
            # 印刷範囲を画面中心にリセット
            if hasattr(m, 'setExtent'):
                m.setExtent(new_extent)
            # setScaleでスケールを反映
            if hasattr(m, 'setScale'):
                m.setScale(scale)
            # setMapRotationで地図内容の回転角度を反映
            if hasattr(m, 'setMapRotation'):
                m.setMapRotation(angle)
            if hasattr(m, 'refresh'):
                m.refresh()

        # 印刷範囲の中心に地図キャンバスを移動（再描画時は現在の表示位置を維持）
        if center is None:
            canvas.setCenter(QgsPointXY(cx, cy))
        canvas.refresh()

        # QgsRubberBandで回転した矩形を描画
        rb = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.PolygonGeometry)
        rb.setColor(QColor(255, 0, 0, 100))  # 半透明赤
        rb.setWidth(2)
        rb.setToGeometry(QgsGeometry.fromPolygonXY([rotated_points]), None)
        # 既存rubberbandがあれば削除してから新規セット
        if hasattr(self, '_print_area_rubberband') and self._print_area_rubberband:
            try:
                old_rb = self._print_area_rubberband
                if hasattr(old_rb, 'hide'):
                    old_rb.hide()
                if hasattr(old_rb, 'canvas'):
                    canvas2 = old_rb.canvas()
                    if hasattr(canvas2, 'scene'):
                        try:
                            canvas2.scene().removeItem(old_rb)
                        except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                            pass
                old_rb.reset()
            except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                pass
        self._print_area_rubberband = rb
        print(f"[DEBUG] new rubberband created: {rb}")
        # 情報メッセージの表示は削除

        # 印刷範囲rubberbandをマウスで移動できるようにするツールを有効化（UIには影響しない）
        self._print_area_move_tool = PrintAreaMoveTool(canvas, rb, map_item, width_map, height_map, self.iface, self)
        canvas.setMapTool(self._print_area_move_tool)

        # ボタンテキストを「非表示」に変更
        self.show_print_area_button.setText(QCoreApplication.translate('geo_report', "Hide Print Area"))

    def _refresh_print_area(self, *_args):
        """スケール・角度の変更やキャンバス回転時に、表示中の印刷枠を現在の設定で描き直す。
        印刷枠が非表示なら何もしない(トグルにはしない)。"""
        rb = getattr(self, '_print_area_rubberband', None)
        if not rb:
            return
        center = None
        try:
            geom = rb.asGeometry()
            if geom:
                center = geom.centroid().asPoint()
        except Exception:
            center = None
        self._remove_print_area_rubberband(silent=True)
        self.show_print_area_on_map(center=center)

    def load_layout_items(self):
        """レイアウトアイテムを読み込む"""
        if not self.current_layout:
            return

        self.items_tree.clear()

        # レイアウトからすべてのアイテムを取得
        items = self.current_layout.items()

        # デバッグ情報を追加
        total_items = len(items)
        valid_items = 0

        for item in items:
            try:
                item_class = item.__class__.__name__
                has_display_name = hasattr(item, 'displayName')
                has_uuid = hasattr(item, 'uuid')
                is_layout_item = isinstance(item, QgsLayoutItem)
                print(f"item: {item_class}, QgsLayoutItem: {is_layout_item}, displayName: {has_display_name}, uuid: {has_uuid}")
                if self.is_valid_layout_item_relaxed(item):
                    valid_items += 1
                    tree_item = QTreeWidgetItem()
                    display_name = self.get_item_display_name(item)
                    item_type = self.get_item_type_name(item)
                    visibility = self.get_item_visibility(item)
                    tree_item.setText(0, display_name)
                    tree_item.setText(1, item_type)
                    tree_item.setText(2, visibility)
                    tree_item.setData(0, USER_ROLE, item)
                    # 非表示アイテムは薄いグレーで表示
                    if visibility == "Hidden":
                        for col in range(3):
                            tree_item.setForeground(col, Qt.GlobalColor.gray)
                    self.items_tree.addTopLevelItem(tree_item)
            except Exception as e:
                print(f"item processing error: {e}")
                continue

        print(f"total items: {total_items}, valid items: {valid_items}")

        # アイテムが見つからない場合のメッセージ
        if valid_items == 0 and total_items > 0:
            placeholder_item = QTreeWidgetItem()
            placeholder_item.setText(0, QCoreApplication.translate('geo_report', "No items found ({0} objects detected)").format(total_items))
            placeholder_item.setText(1, QCoreApplication.translate('geo_report', "Information"))
            self.items_tree.addTopLevelItem(placeholder_item)

    def refresh_layout_items_with_selection(self, selected_layout_item):
        """選択されたアイテムを保持しながらレイアウトアイテムを更新"""
        # 現在選択されているアイテムのUUIDを保存
        selected_uuid = None
        if selected_layout_item and hasattr(selected_layout_item, 'uuid'):
            selected_uuid = selected_layout_item.uuid()

        # アイテム一覧を再読み込み
        self.load_layout_items()

        # 選択を復元
        if selected_uuid:
            self.restore_item_selection(selected_uuid)

    def restore_item_selection(self, target_uuid):
        """指定されたUUIDのアイテムを選択状態に復元"""
        for i in range(self.items_tree.topLevelItemCount()):
            tree_item = self.items_tree.topLevelItem(i)
            layout_item = tree_item.data(0, USER_ROLE)

            if layout_item and hasattr(layout_item, 'uuid'):
                if layout_item.uuid() == target_uuid:
                    # アイテムを選択
                    self.items_tree.setCurrentItem(tree_item)
                    # プロパティを再表示
                    self.load_item_properties(layout_item)
                    print(f"restoring selection: {tree_item.text(0)}")
                    return

        print("failed to restore selection: target item not found")

    def is_valid_layout_item_relaxed(self, item):
        """より緩い条件でのレイアウトアイテムチェック"""
        try:
            # 基本的なオブジェクトチェック
            if item is None:
                return False

            # 除外すべきクラスをチェック
            class_name = item.__class__.__name__
            excluded_classes = [
                'QgsLayoutUndoCommand',
                'QGraphicsRectItem',
                'QGraphicsItem'
            ]

            if class_name in excluded_classes:
                return False

            # QgsLayoutItemの基本的なチェック
            return hasattr(item, '__class__') and 'QgsLayout' in class_name
        except Exception:
            return False

    def get_item_display_name(self, item):
        """アイテムの表示名を取得"""
        try:
            # 複数の方法でアイテム名を取得
            if hasattr(item, 'displayName') and item.displayName():
                return item.displayName()
            elif hasattr(item, 'id') and item.id():
                return item.id()
            elif hasattr(item, 'uuid'):
                return f"Item{item.uuid()[:8]}"
            else:
                return f"{item.__class__.__name__}"
        except Exception:
            return "Unknown Item"

    def get_item_visibility(self, item):
        """アイテムの表示状態を取得"""
        try:
            if hasattr(item, 'isVisible'):
                return "Visible" if item.isVisible() else "Hidden"
            else:
                return "Unknown"
        except Exception:
            return "Unknown"

    def get_item_position_size(self, item):
        """アイテムの位置とサイズを取得"""
        try:
            pos_info = "N/A"
            size_info = "N/A"

            if hasattr(item, 'positionWithUnits'):
                pos = item.positionWithUnits()
                pos_info = f"{pos.x():.1f}, {pos.y():.1f}"

            if hasattr(item, 'sizeWithUnits'):
                size = item.sizeWithUnits()
                size_info = f"{size.width():.1f}×{size.height():.1f}"

            return pos_info, size_info
        except Exception:
            return "N/A", "N/A"

    def is_valid_layout_item(self, item):
        """有効なレイアウトアイテムかどうかをチェック"""
        try:
            # QgsLayoutItemかどうかをチェック
            if not isinstance(item, QgsLayoutItem):
                return False

            # 必要なメソッドがあるかチェック
            if not hasattr(item, 'displayName') or not hasattr(item, 'uuid'):
                return False

            # 除外すべきクラスをチェック
            class_name = item.__class__.__name__
            excluded_classes = [
                'QgsLayoutUndoCommand',
                'QgsLayoutItemPage',
                'QGraphicsRectItem',
                'QGraphicsItem'
            ]

            if class_name in excluded_classes:
                return False

            return True
        except Exception:
            return False

    def get_item_type_name(self, item):
        """アイテムタイプの日本語名を取得"""
        try:
            # QgsLayoutItemのタイプを文字列で取得
            type_name = item.__class__.__name__
            # クラス名からタイプを判定
            type_map = {
                'QgsLayoutItemGroup': "Group",
                'QgsLayoutItemPage': "Page",
                'QgsLayoutItemMap': "Map",
                'QgsLayoutItemPicture': "Picture",
                'QgsLayoutItemLabel': "Label",
                'QgsLayoutItemLegend': "Legend",
                'QgsLayoutItemScaleBar': "Scale Bar",
                'QgsLayoutItemShape': "Shape",
                'QgsLayoutItemPolygon': "Polygon",
                'QgsLayoutItemPolyline': "Polyline",
                'QgsLayoutItemAttributeTable': "Table",
                'QgsLayoutItemHtml': "HTML",
                'QgsLayoutItemFrame': "Frame",
            }
            return type_map.get(type_name, f"Item({type_name})")
        except AttributeError:
            return "Unknown"

    def on_item_selected(self, current, previous):
        # タブタイトルも毎回再翻訳（QGISの言語切替時に即時反映したい場合）
        self.retranslate_tabs()
        """アイテムが選択された時の処理"""
        if current is None:
            self.clear_properties_form()
            return

        item = current.data(0, USER_ROLE)
        if item:
            # すぐにプロパティを表示
            self.load_item_properties(item)
            # アイテム名をウィンドウタイトルに反映（オプション）
            item_name = current.text(0)
            self.setWindowTitle(QCoreApplication.translate('geo_report', "Layout Selection & Item Management") + f" - {item_name}")
        else:
            self.setWindowTitle(QCoreApplication.translate('geo_report', "Layout Selection & Item Management"))

    def load_item_properties(self, item):
        """アイテムのプロパティを読み込む"""
        # プロパティフォームをクリア
        self.clear_properties_form()

        if not item:
            return

        try:
            # 基本プロパティ
            if hasattr(item, 'uuid'):
                self.add_property_field(QCoreApplication.translate('geo_report', "ID"), item.uuid(), readonly=True)
            if hasattr(item, 'displayName'):
                self.add_property_field(QCoreApplication.translate('geo_report', "Display Name"), item.displayName() or "")
            if hasattr(item, 'isVisible'):
                self.add_property_field(QCoreApplication.translate('geo_report', "Visible"), item.isVisible(), field_type="checkbox")
            # 位置とサイズ
            if hasattr(item, 'positionWithUnits') and hasattr(item, 'sizeWithUnits'):
                pos = item.positionWithUnits()
                size = item.sizeWithUnits()
                self.add_property_field(QCoreApplication.translate('geo_report', "X Position (mm)"), pos.x(), field_type="double")
                self.add_property_field(QCoreApplication.translate('geo_report', "Y Position (mm)"), pos.y(), field_type="double")
                self.add_property_field(QCoreApplication.translate('geo_report', "Width (mm)"), size.width(), field_type="double")
                self.add_property_field(QCoreApplication.translate('geo_report', "Height (mm)"), size.height(), field_type="double")
            # 回転
            if hasattr(item, 'itemRotation'):
                self.add_property_field(QCoreApplication.translate('geo_report', "Rotation Angle"), item.itemRotation(), field_type="double")

            # アイテム固有のプロパティ
            if hasattr(item, '__class__'):
                class_name = item.__class__.__name__
                if class_name == 'QgsLayoutItemLabel':
                    self.add_label_properties(item)
                elif class_name == 'QgsLayoutItemMap':
                    self.add_map_properties(item)
                elif class_name == 'QgsLayoutItemPicture':
                    self.add_picture_properties(item)

        except AttributeError as e:
            # プロパティにアクセスできない場合のエラーハンドリング
            self.add_property_field(QCoreApplication.translate('geo_report', "Error"), QCoreApplication.translate('geo_report', "Cannot load properties: ") + str(e), readonly=True)

    def add_label_properties(self, label_item):
        """ラベルアイテムのプロパティを追加"""
        try:
            if hasattr(label_item, 'text'):
                self.add_property_field(QCoreApplication.translate('geo_report', "Text"), label_item.text())
            # フォントサイズなど他のプロパティも追加可能
            if hasattr(label_item, 'font'):
                font = label_item.font()
                self.add_property_field(QCoreApplication.translate('geo_report', "Font Size"), font.pointSize(), field_type="int")
        except AttributeError:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass

    def add_map_properties(self, map_item):
        """地図アイテムのプロパティを追加"""
        try:
            self.add_property_field(QCoreApplication.translate('geo_report', "Scale"), map_item.scale(), field_type="double")
            # 他の地図プロパティも追加可能
        except AttributeError:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass

    def add_picture_properties(self, picture_item):
        """画像アイテムのプロパティを追加"""
        try:
            self.add_property_field(QCoreApplication.translate('geo_report', "Image Path"), picture_item.picturePath())
            # 他の画像プロパティも追加可能
        except AttributeError:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
            pass

    def add_property_field(self, label, value, field_type="text", readonly=False):
        """プロパティフィールドを追加"""
        if field_type == "text":
            widget = QLineEdit(str(value))
            widget.setReadOnly(readonly)
            if not readonly:
                widget.textChanged.connect(self.on_property_changed)
        elif field_type == "double":
            widget = QDoubleSpinBox()
            widget.setDecimals(2)
            widget.setRange(-999999, 999999)
            widget.setValue(float(value))
            widget.setReadOnly(readonly)
            if not readonly:
                widget.valueChanged.connect(self.on_property_changed)
        elif field_type == "int":
            widget = QSpinBox()
            widget.setRange(-999999, 999999)
            widget.setValue(int(value))
            widget.setReadOnly(readonly)
            if not readonly:
                widget.valueChanged.connect(self.on_property_changed)
        elif field_type == "checkbox":
            widget = QCheckBox()
            widget.setChecked(bool(value))
            widget.setEnabled(not readonly)
            if not readonly:
                widget.toggled.connect(self.on_property_changed)
        else:
            widget = QLineEdit(str(value))
            widget.setReadOnly(readonly)
            if not readonly:
                widget.textChanged.connect(self.on_property_changed)

        widget.setProperty("property_name", label)
        self.properties_form.addRow(label + ":", widget)

    def focus_on_properties(self, item, column):
        """アイテムダブルクリック時にプロパティエリアにフォーカス"""
        # プロパティフォームの最初の編集可能フィールドにフォーカス
        for i in range(self.properties_form.rowCount()):
            field_item = self.properties_form.itemAt(i, QFormLayout.ItemRole.FieldRole)
            if field_item and field_item.widget():
                widget = field_item.widget()
                if hasattr(widget, 'setFocus') and not widget.isReadOnly() if hasattr(widget, 'isReadOnly') else True:
                    widget.setFocus()
                    break

    def on_property_changed(self):
        """プロパティが変更された時の処理（リアルタイム更新のための準備）"""
        # 将来的にリアルタイム更新を実装する場合のプレースホルダー
        pass

    def clear_properties_form(self):
        """プロパティフォームをクリア"""
        # QFormLayoutが削除済みの場合は何もしない（Qt6ではqgis.PyQtを使用）
        from qgis.PyQt.QtWidgets import QFormLayout
        if not hasattr(self, 'properties_form') or not isinstance(self.properties_form, QFormLayout):
            return
        try:
            # wrapped C/C++ object of type QFormLayout has been deleted 対策
            _ = self.properties_form.count()
        except RuntimeError:
            return
        while self.properties_form.count():
            child = self.properties_form.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def update_item_properties(self):
        """アイテムのプロパティを更新"""
        current_item = self.items_tree.currentItem()
        if not current_item:
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Warning"), QCoreApplication.translate('geo_report', "Please select an item."),
                level=Qgis.MessageLevel.Warning, duration=3
            )
            return

        layout_item = current_item.data(0, USER_ROLE)
        if not layout_item or not isinstance(layout_item, QgsLayoutItem):
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Warning"), QCoreApplication.translate('geo_report', "No valid layout item selected."),
                level=Qgis.MessageLevel.Warning, duration=3
            )
            return

        try:
            print(f"property update started: {layout_item.__class__.__name__}")

            # レイアウトの変更を開始（undo/redoサポート）
            self.current_layout.undoStack().beginCommand(layout_item, QCoreApplication.translate('geo_report', "Update Item Properties"))

            # 更新フラグ
            updated = False

            # フォームから値を取得して適用
            for i in range(self.properties_form.rowCount()):
                label_item = self.properties_form.itemAt(i, QFormLayout.ItemRole.LabelRole)
                field_item = self.properties_form.itemAt(i, QFormLayout.ItemRole.FieldRole)

                if label_item and field_item:
                    label_text = label_item.widget().text().replace(":", "")
                    widget = field_item.widget()

                    print(f"processing property: {label_text}")

                    # プロパティに応じて値を設定
                    if label_text == QCoreApplication.translate('geo_report', "Display Name") and hasattr(layout_item, 'setId'):
                        # 表示名の代わりにIDを設定
                        old_id = layout_item.id()
                        new_id = widget.text()
                        if old_id != new_id:
                            layout_item.setId(new_id)
                            updated = True
                            print(f"ID updated: '{old_id}' -> '{new_id}'")

                    elif label_text == QCoreApplication.translate('geo_report', "Visible") and hasattr(layout_item, 'setVisibility'):
                        old_visibility = layout_item.isVisible()
                        new_visibility = widget.isChecked()
                        if old_visibility != new_visibility:
                            layout_item.setVisibility(new_visibility)
                            updated = True
                            print(f"visibility updated: {old_visibility} -> {new_visibility}")

                    elif label_text in [QCoreApplication.translate('geo_report', "X Position (mm)"), QCoreApplication.translate('geo_report', "Y Position (mm)")]:
                        # 位置の更新は座標をまとめて処理
                        if hasattr(layout_item, 'attemptMove'):
                            pos = layout_item.positionWithUnits()
                            if label_text == QCoreApplication.translate('geo_report', "X Position (mm)"):
                                new_x = widget.value()
                                if abs(pos.x() - new_x) > 0.01:  # 小数点誤差を考慮
                                    new_pos = QgsLayoutPoint(new_x, pos.y(), QgsUnitTypes.LayoutUnit.LayoutMillimeters)
                                    layout_item.attemptMove(new_pos)
                                    updated = True
                                    print(f"X updated: {pos.x():.2f} -> {new_x}")
                            elif label_text == QCoreApplication.translate('geo_report', "Y Position (mm)"):
                                new_y = widget.value()
                                if abs(pos.y() - new_y) > 0.01:  # 小数点誤差を考慮
                                    new_pos = QgsLayoutPoint(pos.x(), new_y, QgsUnitTypes.LayoutUnit.LayoutMillimeters)
                                    layout_item.attemptMove(new_pos)
                                    updated = True
                                    print(f"Y updated: {pos.y():.2f} -> {new_y}")

                    elif label_text == QCoreApplication.translate('geo_report', "Rotation Angle") and hasattr(layout_item, 'setItemRotation'):
                        old_rotation = layout_item.itemRotation()
                        new_rotation = widget.value()
                        if abs(old_rotation - new_rotation) > 0.01:
                            layout_item.setItemRotation(new_rotation)
                            updated = True
                            print(f"rotation updated: {old_rotation:.2f} -> {new_rotation}")

                    elif label_text == QCoreApplication.translate('geo_report', "Text") and hasattr(layout_item, 'setText'):
                        # ラベルテキストの更新
                        old_text = layout_item.text() if hasattr(layout_item, 'text') else ""
                        new_text = widget.text()
                        if old_text != new_text:
                            print(f"text update started: '{old_text}' -> '{new_text}'")
                            layout_item.setText(new_text)
                            updated = True

                            # テキスト更新後の特別処理
                            if hasattr(layout_item, 'adjustSizeToText'):
                                layout_item.adjustSizeToText()
                            if hasattr(layout_item, 'refresh'):
                                layout_item.refresh()

                            # 更新後のテキストを確認
                            updated_text = layout_item.text() if hasattr(layout_item, 'text') else ""
                            print(f"text update completed: '{updated_text}'")

                    elif label_text == QCoreApplication.translate('geo_report', "Font Size") and hasattr(layout_item, 'setFont'):
                        old_font = layout_item.font()
                        new_size = int(widget.value())
                        if old_font.pointSize() != new_size:
                            font = layout_item.font()
                            font.setPointSize(new_size)
                            layout_item.setFont(font)
                            updated = True
                            print(f"font size updated: {old_font.pointSize()} -> {new_size}")

                            # フォント変更後の特別な更新処理
                            if hasattr(layout_item, 'adjustSizeToText'):
                                layout_item.adjustSizeToText()

                    elif label_text == QCoreApplication.translate('geo_report', "Scale") and hasattr(layout_item, 'setScale'):
                        old_scale = layout_item.scale()
                        new_scale = widget.value()
                        if abs(old_scale - new_scale) > 0.01:
                            layout_item.setScale(new_scale)
                            updated = True
                            print(f"scale updated: {old_scale} -> {new_scale}")

                    elif label_text == QCoreApplication.translate('geo_report', "Image Path") and hasattr(layout_item, 'setPicturePath'):
                        old_path = layout_item.picturePath()
                        new_path = widget.text()
                        if old_path != new_path:
                            layout_item.setPicturePath(new_path)
                            updated = True
                            print(f"image path updated: '{old_path}' -> '{new_path}'")

            # 更新があった場合のみ処理を続行
            if updated:
                # アイテム固有の更新処理
                item_class = layout_item.__class__.__name__
                if item_class == 'QgsLayoutItemLabel':
                    # ラベルアイテムの特別な更新処理
                    if hasattr(layout_item, 'refresh'):
                        layout_item.refresh()
                elif item_class == 'QgsLayoutItemMap':
                    # 地図アイテムの特別な更新処理
                    if hasattr(layout_item, 'refresh'):
                        layout_item.refresh()
                elif item_class == 'QgsLayoutItemPicture':
                    # 画像アイテムの特別な更新処理
                    if hasattr(layout_item, 'refresh'):
                        layout_item.refresh()

                # アイテムの再描画を強制
                if hasattr(layout_item, 'update'):
                    layout_item.update()
                if hasattr(layout_item, 'invalidateCache'):
                    layout_item.invalidateCache()

                # レイアウト全体を更新
                self.current_layout.refresh()
                if hasattr(self.current_layout, 'updateBounds'):
                    self.current_layout.updateBounds()

                # レイアウトの変更を終了
                self.current_layout.undoStack().endCommand()

        # 成功メッセージの表示は削除

                # アイテム一覧を更新（選択を保持）
                self.refresh_layout_items_with_selection(layout_item)

                print("property update completed")
            else:
                # 変更がない場合はundoコマンドをキャンセル
                self.current_layout.undoStack().cancelCommand()
                # 情報メッセージの表示は削除
                print("no changes")

        except Exception as e:
            # エラーが発生した場合はundoコマンドをキャンセル
            try:
                self.current_layout.undoStack().cancelCommand()
            except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                pass

            print(f"property update error: {e}")
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Error"), QCoreApplication.translate('geo_report', "Failed to update properties: {}").format(str(e)),
                level=Qgis.MessageLevel.Critical, duration=5
            )

    def save_layout_properties(self):
        """レイアウト全体のアイテムプロパティをファイルに保存"""
        if not self.current_layout:
            return

        try:
            # デフォルトフォルダを設定（ホームディレクトリのQGIS_Layoutsフォルダ）
            default_folder = os.path.join(os.path.expanduser("~"), "QGIS_Layouts")

            # デフォルトフォルダが存在しない場合は作成
            if not os.path.exists(default_folder):
                os.makedirs(default_folder)
                # 情報メッセージの表示は削除

            # レイアウト名を取得してデフォルトファイル名を作成
            layout_name = self.current_layout.name()
            default_filename = f"{layout_name}_layout_properties.json"
            default_filepath = os.path.join(default_folder, default_filename)

            # ファイル保存ダイアログ
            filename, _ = QFileDialog.getSaveFileName(
                self,
                QCoreApplication.translate('geo_report', "Save Layout Properties File"),
                default_filepath,
                QCoreApplication.translate('geo_report', "JSON Files (*.json);;All Files (*)")
            )

            if not filename:
                return

            # レイアウト全体のプロパティを収集
            layout_properties = self.collect_layout_properties()

            # JSONファイルに保存
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(layout_properties, f, ensure_ascii=False, indent=2)

            # 成功メッセージの表示は削除

        except Exception as e:
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Error"), QCoreApplication.translate('geo_report', "Failed to save layout properties: {}").format(str(e)),
                level=Qgis.MessageLevel.Critical, duration=5
            )

    def load_layout_properties(self):
        """ファイルからレイアウト全体のプロパティを読み込んで適用"""
        if not self.current_layout:
            return

        try:
            # デフォルトフォルダを設定（ホームディレクトリのQGIS_Layoutsフォルダ）
            default_folder = os.path.join(os.path.expanduser("~"), "QGIS_Layouts")

            # デフォルトフォルダが存在しない場合は作成
            if not os.path.exists(default_folder):
                os.makedirs(default_folder)
                # 情報メッセージの表示は削除

            # フォルダ内のJSONファイル一覧を取得
            json_files = []
            if os.path.exists(default_folder):
                for file in os.listdir(default_folder):
                    if file.lower().endswith('.json'):
                        json_files.append(file)

            # ファイルが見つからない場合は通常のファイルダイアログを表示
            if not json_files:
                filename, _ = QFileDialog.getOpenFileName(
                    self,
                    QCoreApplication.translate('geo_report', "Load Layout Properties File (No files in default folder)"),
                    default_folder,
                    QCoreApplication.translate('geo_report', "JSON Files (*.json);;All Files (*)")
                )

                if not filename:
                    return
            else:
                # ファイル選択ダイアログを作成
                dialog = LayoutFileSelectDialog(default_folder, json_files, self)
                dialog_result = dialog.exec()
                if dialog_result != QDialog.DialogCode.Accepted:
                    return

                selected_file = dialog.get_selected_file()
                if not selected_file:
                    return

                # フルパスかファイル名かを判定
                if os.path.isabs(selected_file):
                    # フルパスの場合はそのまま使用
                    filename = selected_file
                else:
                    # ファイル名のみの場合はパスを結合
                    filename = os.path.join(default_folder, selected_file)

            # JSONファイルから読み込み
            with open(filename, 'r', encoding='utf-8') as f:
                layout_properties = json.load(f)

            # レイアウトプロパティの検証
            if not self.validate_layout_properties(layout_properties):
                return

            # アイテム数の確認
            saved_items_count = len(layout_properties.get('items', []))
            current_items = self.get_valid_layout_items()
            current_items_count = len(current_items)

            if saved_items_count != current_items_count:
                reply = QMessageBox.question(
                    self,
                    QCoreApplication.translate('geo_report', "Item Count Mismatch"),
                    QCoreApplication.translate('geo_report', "Saved item count ({}) and current layout item count ({}) are different.\n\nDo you want to apply within possible range?").format(
                        saved_items_count, current_items_count),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )

                if reply == QMessageBox.StandardButton.No:
                    return

            # レイアウトプロパティを適用
            _ = self.apply_layout_properties(layout_properties)

            # アイテム一覧を更新
            self.load_layout_items()
            self.load_layout_info()

            # 成功メッセージの表示は削除

        except FileNotFoundError:
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Error"), QCoreApplication.translate('geo_report', "File not found."),
                level=Qgis.MessageLevel.Critical, duration=5
            )
        except json.JSONDecodeError:
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Error"), QCoreApplication.translate('geo_report', "Failed to parse JSON file."),
                level=Qgis.MessageLevel.Critical, duration=5
            )
        except Exception as e:
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Error"), QCoreApplication.translate('geo_report', "Failed to load layout properties: {}").format(str(e)),
                level=Qgis.MessageLevel.Critical, duration=5
            )

    def collect_layout_properties(self):
        """レイアウト全体のプロパティを収集"""
        from datetime import datetime

        layout_properties = {
            'layout_name': self.current_layout.name(),
            'save_timestamp': datetime.now().isoformat(),
            'page_count': self.current_layout.pageCollection().pageCount(),
            'items': []
        }

        # ページ情報を追加
        pages_info = []
        for i in range(self.current_layout.pageCollection().pageCount()):
            page = self.current_layout.pageCollection().page(i)
            pages_info.append({
                'page_number': i + 1,
                'width': page.pageSize().width(),
                'height': page.pageSize().height()
            })
        layout_properties['pages'] = pages_info

        # 有効なレイアウトアイテムを取得
        valid_items = self.get_valid_layout_items()

        # 各アイテムのプロパティを収集
        for item in valid_items:
            try:
                item_properties = self.collect_item_properties(item)
                # レイアウト内での順序情報を追加
                item_properties['layout_order'] = len(layout_properties['items'])
                layout_properties['items'].append(item_properties)
            except Exception as e:
                print(f"item property collection error: {e}")
                continue

        print(f"layout properties collected: {len(layout_properties['items'])} items")
        return layout_properties

    def get_valid_layout_items(self):
        """有効なレイアウトアイテムのリストを取得"""
        if not self.current_layout:
            return []

        items = self.current_layout.items()
        valid_items = []

        for item in items:
            if self.is_valid_layout_item_relaxed(item):
                valid_items.append(item)

        return valid_items

    def validate_layout_properties(self, layout_properties):
        """レイアウトプロパティファイルの妥当性をチェック"""
        try:
            # 必須フィールドのチェック
            required_fields = ['layout_name', 'items']
            for field in required_fields:
                if field not in layout_properties:
                    return False

            # itemsが配列かチェック
            if not isinstance(layout_properties['items'], list):
                return False

            # 各アイテムの基本構造をチェック
            for item_data in layout_properties['items']:
                if not isinstance(item_data, dict):
                    return False
                if 'item_type' not in item_data:
                    return False
                if 'properties' not in item_data:
                    return False

            return True
        except Exception:
            return False

    def apply_layout_properties(self, layout_properties):
        """レイアウト全体にプロパティを適用"""
        if not self.current_layout:
            return 0

        try:
            # レイアウトの変更を開始
            self.current_layout.undoStack().beginCommand(self.current_layout, QCoreApplication.translate('geo_report', "Apply layout properties"))

            applied_count = 0
            current_items = self.get_valid_layout_items()
            saved_items = layout_properties['items']

            # アイテムのマッチング方法を選択
            matching_method = self.determine_matching_method(current_items, saved_items)

            for i, saved_item_data in enumerate(saved_items):
                try:
                    # 対応するアイテムを見つける
                    target_item = self.find_matching_item(current_items, saved_item_data, i, matching_method)

                    if target_item:
                        # プロパティを適用
                        self.apply_properties_to_item_silent(target_item, saved_item_data)
                        applied_count += 1
                        print(f"property applied: {target_item.__class__.__name__}")
                    else:
                        print(f"no matching item found: {saved_item_data.get('item_type', 'Unknown')}")

                except Exception as e:
                    print(f"item property apply error: {e}")
                    continue

            # レイアウト全体を更新
            self.current_layout.refresh()
            if hasattr(self.current_layout, 'updateBounds'):
                self.current_layout.updateBounds()

            # 変更を確定
            self.current_layout.undoStack().endCommand()

            print(f"layout properties applied: {applied_count}/{len(saved_items)} items")
            return applied_count

        except Exception as e:
            try:
                self.current_layout.undoStack().cancelCommand()
            except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                pass
            raise e

    def determine_matching_method(self, current_items, saved_items):
        """アイテムのマッチング方法を決定"""
        # UUID によるマッチングを優先
        current_uuids = set()
        saved_uuids = set()

        for item in current_items:
            if hasattr(item, 'uuid'):
                current_uuids.add(item.uuid())

        for item_data in saved_items:
            uuid = item_data.get('properties', {}).get('uuid')
            if uuid:
                saved_uuids.add(uuid)

        # UUIDの一致率を計算
        uuid_match_rate = len(current_uuids & saved_uuids) / max(len(current_uuids), len(saved_uuids), 1)

        if uuid_match_rate > 0.5:
            return 'uuid'
        else:
            return 'order'  # 順序による対応

    def find_matching_item(self, current_items, saved_item_data, index, matching_method):
        """保存されたアイテムデータに対応する現在のアイテムを見つける"""
        if matching_method == 'uuid':
            # UUIDによるマッチング
            saved_uuid = saved_item_data.get('properties', {}).get('uuid')
            if saved_uuid:
                for item in current_items:
                    if hasattr(item, 'uuid') and item.uuid() == saved_uuid:
                        return item

        # 順序によるマッチング（フォールバック）
        if index < len(current_items):
            return current_items[index]

        # タイプによるマッチング（最後の手段）
        saved_item_type = saved_item_data.get('item_type')
        if saved_item_type:
            for item in current_items:
                if item.__class__.__name__ == saved_item_type:
                    return item

        return None

    def apply_properties_to_item_silent(self, item, item_data):
        """アイテムにプロパティを適用（エラーを内部で処理）"""
        try:
            props = item_data['properties']

            # 基本プロパティの適用
            if 'id' in props and hasattr(item, 'setId'):
                new_id = props['id']
                if new_id and item.id() != new_id:
                    item.setId(new_id)

            if 'visible' in props and hasattr(item, 'setVisibility'):
                new_visibility = props['visible']
                if item.isVisible() != new_visibility:
                    item.setVisibility(new_visibility)

            # 位置の適用
            if 'position' in props and hasattr(item, 'attemptMove'):
                pos_data = props['position']
                new_pos = QgsLayoutPoint(pos_data['x'], pos_data['y'], QgsUnitTypes.LayoutUnit.LayoutMillimeters)
                item.attemptMove(new_pos)

            # サイズの適用
            if 'size' in props and hasattr(item, 'attemptResize'):
                size_data = props['size']
                new_size = QgsLayoutSize(size_data['width'], size_data['height'], QgsUnitTypes.LayoutUnit.LayoutMillimeters)
                item.attemptResize(new_size)

            # 回転の適用
            if 'rotation' in props and hasattr(item, 'setItemRotation'):
                new_rotation = props['rotation']
                if abs(item.itemRotation() - new_rotation) > 0.01:
                    item.setItemRotation(new_rotation)

            # アイテム固有のプロパティを適用
            item_type = item.__class__.__name__
            if item_type == 'QgsLayoutItemLabel':
                self.apply_label_properties(item, props)
            elif item_type == 'QgsLayoutItemMap':
                self.apply_map_properties(item, props)
            elif item_type == 'QgsLayoutItemPicture':
                self.apply_picture_properties(item, props)

            # アイテムの更新
            if hasattr(item, 'refresh'):
                item.refresh()
            if hasattr(item, 'update'):
                item.update()
            if hasattr(item, 'invalidateCache'):
                item.invalidateCache()

        except Exception as e:
            print(f"item property apply error (silent): {e}")
            # エラーがあっても処理を続行

    def apply_label_properties(self, label_item, props):
        """ラベルアイテムにプロパティを適用"""
        updated = False
        try:
            if 'text' in props and hasattr(label_item, 'setText'):
                current_text = label_item.text() if hasattr(label_item, 'text') else ""
                new_text = props['text']
                if current_text != new_text:
                    label_item.setText(new_text)
                    updated = True
                    if hasattr(label_item, 'adjustSizeToText'):
                        label_item.adjustSizeToText()

            if 'font' in props and hasattr(label_item, 'setFont'):
                font_data = props['font']
                current_font = label_item.font()
                new_font = label_item.font()

                font_changed = False
                if 'family' in font_data and current_font.family() != font_data['family']:
                    new_font.setFamily(font_data['family'])
                    font_changed = True
                if 'size' in font_data and current_font.pointSize() != font_data['size']:
                    new_font.setPointSize(font_data['size'])
                    font_changed = True
                if 'bold' in font_data and current_font.bold() != font_data['bold']:
                    new_font.setBold(font_data['bold'])
                    font_changed = True
                if 'italic' in font_data and current_font.italic() != font_data['italic']:
                    new_font.setItalic(font_data['italic'])
                    font_changed = True

                if font_changed:
                    label_item.setFont(new_font)
                    updated = True
                    if hasattr(label_item, 'adjustSizeToText'):
                        label_item.adjustSizeToText()

        except Exception as e:
            print(f"label property apply error: {e}")

        return updated

    def apply_map_properties(self, map_item, props):
        """地図アイテムにプロパティを適用"""
        updated = False
        try:
            if 'scale' in props and hasattr(map_item, 'setScale'):
                current_scale = map_item.scale()
                new_scale = props['scale']
                if abs(current_scale - new_scale) > 0.01:
                    map_item.setScale(new_scale)
                    updated = True
        except Exception as e:
            print(f"map property apply error: {e}")

        return updated

    def apply_picture_properties(self, picture_item, props):
        """画像アイテムにプロパティを適用"""
        updated = False
        try:
            if 'picture_path' in props and hasattr(picture_item, 'setPicturePath'):
                current_path = picture_item.picturePath()
                new_path = props['picture_path']
                if current_path != new_path:
                    picture_item.setPicturePath(new_path)
                    updated = True
        except Exception as e:
            print(f"picture property apply error: {e}")

        return updated

    def refresh_item_info(self):
        """アイテム情報を更新"""
        if self.current_layout:
            self.load_layout_items()
            self.load_layout_info()
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Information"), QCoreApplication.translate('geo_report', "Item information has been updated."),
                level=Qgis.MessageLevel.Info, duration=2
            )

    def clear_item_info(self):
        """アイテム情報をクリア"""
        self.items_tree.clear()
        self.info_text.clear()
        self.clear_properties_form()

    def open_layout_manager(self):
        """選択されたレイアウトでレイアウトマネージャを開く"""
        if not self.current_layout:
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate('geo_report', "Warning"), QCoreApplication.translate('geo_report', "Please select a layout."),
                level=Qgis.MessageLevel.Warning, duration=3
            )
            return

        # レイアウトマネージャ（デザイナー）を開く
        self.iface.openLayoutDesigner(self.current_layout)
        # パネル化したので、self.accept()を呼ばない（パネルを閉じない）

    def load_layout_info(self):
        """レイアウト情報を読み込む"""
        if not self.current_layout:
            self.info_text.clear()
            return

        items = self.current_layout.items()
        total_items = len(items)

        info_lines = [
            QCoreApplication.translate('geo_report', "Layout Name: ") + f"{self.current_layout.name()}",
            QCoreApplication.translate('geo_report', "Page Count: ") + f"{self.current_layout.pageCollection().pageCount()}",
            QCoreApplication.translate('geo_report', "Total Objects: ") + f"{total_items}",
            "",
            QCoreApplication.translate('geo_report', "Page Information:")
        ]

        # ページ情報
        for i in range(self.current_layout.pageCollection().pageCount()):
            page = self.current_layout.pageCollection().page(i)
            info_lines.append(QCoreApplication.translate('geo_report', "  Page ") + f"{i + 1}: {page.pageSize().width():.1f} x {page.pageSize().height():.1f} mm")

        info_lines.extend([
            "",
            QCoreApplication.translate('geo_report', "All Objects List:")
        ])

        # すべてのアイテム情報（デバッグ用）
        for i, item in enumerate(items):
            try:
                class_name = item.__class__.__name__
                has_display_name = hasattr(item, 'displayName')
                has_uuid = hasattr(item, 'uuid')
                is_layout_item = isinstance(item, QgsLayoutItem)

                info_lines.append(f"  {i + 1}. {class_name}")
                info_lines.append(f"     - QgsLayoutItem: {is_layout_item}")
                info_lines.append(f"     - displayName: {has_display_name}")
                info_lines.append(f"     - uuid: {has_uuid}")

                if has_display_name:
                    try:
                        display_name = item.displayName()
                        info_lines.append("     - " + QCoreApplication.translate('geo_report', "Name: ") + f"{display_name}")
                    except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                        pass

            except Exception as e:
                info_lines.append(f"  {i + 1}. " + QCoreApplication.translate('geo_report', "Error: {0}").format(e))

        self.info_text.setText("\n".join(info_lines))

    def collect_item_properties(self, item):
        """アイテムのプロパティを収集してディクショナリとして返す"""
        properties = {
            'item_type': item.__class__.__name__,
            'timestamp': 'Saved at',
            'properties': {}
        }

        try:
            # 基本プロパティ
            if hasattr(item, 'uuid'):
                properties['properties']['uuid'] = item.uuid()
            if hasattr(item, 'displayName'):
                properties['properties']['display_name'] = item.displayName() or ""
            if hasattr(item, 'id'):
                properties['properties']['id'] = item.id() or ""
            if hasattr(item, 'isVisible'):
                properties['properties']['visible'] = item.isVisible()

            # 位置とサイズ
            if hasattr(item, 'positionWithUnits'):
                pos = item.positionWithUnits()
                properties['properties']['position'] = {
                    'x': pos.x(),
                    'y': pos.y(),
                    'units': pos.units()
                }

            if hasattr(item, 'sizeWithUnits'):
                size = item.sizeWithUnits()
                properties['properties']['size'] = {
                    'width': size.width(),
                    'height': size.height(),
                    'units': size.units()
                }

            # 回転
            if hasattr(item, 'itemRotation'):
                properties['properties']['rotation'] = item.itemRotation()

            # アイテム固有のプロパティ
            item_type = item.__class__.__name__
            if item_type == 'QgsLayoutItemLabel':
                self.collect_label_properties(item, properties)
            elif item_type == 'QgsLayoutItemMap':
                self.collect_map_properties(item, properties)
            elif item_type == 'QgsLayoutItemPicture':
                self.collect_picture_properties(item, properties)

        except Exception as e:
            print(f"property collection error: {e}")

        return properties

    def collect_label_properties(self, label_item, properties):
        """ラベルアイテムのプロパティを収集"""
        try:
            if hasattr(label_item, 'text'):
                properties['properties']['text'] = label_item.text()
            if hasattr(label_item, 'font'):
                font = label_item.font()
                properties['properties']['font'] = {
                    'family': font.family(),
                    'size': font.pointSize(),
                    'bold': font.bold(),
                    'italic': font.italic()
                }
        except Exception as e:
            print(f"label property collection error: {e}")

    def collect_map_properties(self, map_item, properties):
        """地図アイテムのプロパティを収集"""
        try:
            if hasattr(map_item, 'scale'):
                properties['properties']['scale'] = map_item.scale()
        except Exception as e:
            print(f"map property collection error: {e}")

    def collect_picture_properties(self, picture_item, properties):
        """画像アイテムのプロパティを収集"""
        try:
            if hasattr(picture_item, 'picturePath'):
                properties['properties']['picture_path'] = picture_item.picturePath()
        except Exception as e:
            print(f"picture property collection error: {e}")


class LayoutFileSelectDialog(QDialog):
    """レイアウトファイル選択ダイアログ"""

    def __init__(self, folder_path, json_files, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.json_files = json_files
        self.selected_file = None
        self.init_ui()

    def init_ui(self):
        """UIを初期化"""
        self.setWindowTitle(QCoreApplication.translate('geo_report', "Select Layout Property File"))
        self.setModal(True)
        self.resize(500, 400)

        layout = QVBoxLayout()

        # フォルダパス表示
        folder_label = QLabel(QCoreApplication.translate('geo_report', "Folder: ") + self.folder_path)
        folder_label.setWordWrap(True)
        layout.addWidget(folder_label)

        # ファイル一覧
        files_label = QLabel(QCoreApplication.translate('geo_report', "Available Layout Property Files:"))
        layout.addWidget(files_label)

        self.file_list = QListWidget()

        # ファイル情報を表示
        for file in self.json_files:
            try:
                file_path = os.path.join(self.folder_path, file)
                # ファイルの詳細情報を取得
                file_size = os.path.getsize(file_path)
                file_time = os.path.getmtime(file_path)

                from datetime import datetime
                time_str = datetime.fromtimestamp(file_time).strftime("%Y-%m-%d %H:%M")

                # JSONファイルからレイアウト名を取得（可能な場合）
                layout_name = ""
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if 'layout_name' in data:
                            layout_name = f" (Layout: {data['layout_name']})"
                except Exception:  # nosec B110  # 例外は握り潰してGUIを継続(設計上の許容)
                    pass

                # リストアイテムを作成
                item_text = f"{file}{layout_name}\n  {QCoreApplication.translate('geo_report', 'Size')}: {file_size:,} {QCoreApplication.translate('geo_report', 'bytes')}, {QCoreApplication.translate('geo_report', 'Modified')}: {time_str}"
                item = QListWidgetItem(item_text)
                item.setData(USER_ROLE, file)
                self.file_list.addItem(item)

            except Exception:
                # エラーがあってもファイル名だけは表示
                item = QListWidgetItem(f"{file} ({QCoreApplication.translate('geo_report', 'Error getting information')})")
                item.setData(USER_ROLE, file)
                self.file_list.addItem(item)

        # ダブルクリックで選択
        self.file_list.itemDoubleClicked.connect(self.on_file_double_clicked)

        layout.addWidget(self.file_list)

        # ボタン
        button_layout = QHBoxLayout()

        self.ok_button = QPushButton(QCoreApplication.translate('geo_report', "Select"))
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setEnabled(False)
        button_layout.addWidget(self.ok_button)

        self.cancel_button = QPushButton(QCoreApplication.translate('geo_report', "Cancel"))
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        self.browse_button = QPushButton(QCoreApplication.translate('geo_report', "Browse Other Folder..."))
        self.browse_button.clicked.connect(self.browse_other_folder)
        button_layout.addWidget(self.browse_button)

        layout.addLayout(button_layout)

        # ファイル選択時にOKボタンを有効化
        self.file_list.currentItemChanged.connect(self.on_selection_changed)

        self.setLayout(layout)

        # 最初のファイルを選択
        if self.file_list.count() > 0:
            self.file_list.setCurrentRow(0)

    def on_selection_changed(self, current, previous):
        """選択が変更された時の処理"""
        if current:
            self.selected_file = current.data(USER_ROLE)
            self.ok_button.setEnabled(True)
        else:
            self.selected_file = None
            self.ok_button.setEnabled(False)

    def on_file_double_clicked(self, item):
        """ファイルがダブルクリックされた時の処理"""
        self.selected_file = item.data(USER_ROLE)
        self.accept()

    def browse_other_folder(self):
        """他のフォルダを参照"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            QCoreApplication.translate('geo_report', "Select Layout Property File"),
            self.folder_path,
            QCoreApplication.translate('geo_report', "JSON Files (*.json);;All Files (*)")
        )

        if filename:
            self.selected_file = filename  # フルパスを保存
            self.accept()

    def get_selected_file(self):
        """選択されたファイルを取得"""
        return self.selected_file
