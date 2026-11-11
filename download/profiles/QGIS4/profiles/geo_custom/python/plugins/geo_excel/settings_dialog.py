# -*- coding: utf-8 -*-
"""geo_excel 設定ダイアログ。

プラグインが「すぐに動く」ために必要なものを一覧し、
  - 環境チェック(pywin32 / Excel COM登録 / 出力先)
  - 既定値(QSettings: 出力先=マイドキュメント/geo_excel, dpi,
    テンプレート指定, 自動適用の有無)
  - アクティブレイヤのレイヤ変数(xlsout_*)の確認・編集・既定値適用
を1つのUIにまとめるQt Widgetsダイアログ。

文字列は QCoreApplication.translate("geo_excel", ...) に統一し
i18n/<lang>.json の context "geo_excel" に集約する。
"""

import os

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsExpressionContextUtils, QgsVectorLayer

from . import settings


class GeoExcelSettingsDialog(QDialog):
    """geo_excel の既定設定とレイヤ変数を管理するダイアログ。"""

    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self._plugin = plugin
        self.iface = plugin.iface
        self.setWindowTitle(QCoreApplication.translate("geo_excel", "geo_excel settings"))
        self.resize(720, 640)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_env_group())
        layout.addWidget(self._build_defaults_group())
        layout.addWidget(self._build_layer_group())
        layout.addWidget(self._build_requirements_group())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            QCoreApplication.translate("geo_excel", "Save"))
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(
            QCoreApplication.translate("geo_excel", "Close"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh()

    # ---- UI構築 --------------------------------------------------------------
    def _build_env_group(self):
        box = QGroupBox(QCoreApplication.translate("geo_excel", "Environment"))
        form = QFormLayout(box)

        self.lbl_win32com = QLabel()
        form.addRow("pywin32 (win32com)", self.lbl_win32com)

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        self.lbl_excel = QLabel()
        btn_check = QPushButton(QCoreApplication.translate("geo_excel", "Launch test"))
        btn_check.clicked.connect(self._check_excel_launch)
        h.addWidget(self.lbl_excel, 1)
        h.addWidget(btn_check)
        form.addRow("Excel", row)

        self.lbl_documents = QLabel()
        self.lbl_documents.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(QCoreApplication.translate("geo_excel", "Documents folder"), self.lbl_documents)

        self.lbl_outdir_status = QLabel()
        self.lbl_outdir_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(QCoreApplication.translate("geo_excel", "Output folder"), self.lbl_outdir_status)
        return box

    def _build_defaults_group(self):
        box = QGroupBox(QCoreApplication.translate("geo_excel", "Defaults (saved in QGIS settings)"))
        form = QFormLayout(box)

        self.edit_outdir = QLineEdit()
        self.edit_outdir.setPlaceholderText(settings.documents_dir()
                                            + os.sep + "geo_excel")
        form.addRow(QCoreApplication.translate("geo_excel", "Output folder"),
                    self._with_browse(self.edit_outdir, directory=True))

        self.edit_dpi = QLineEdit()
        self.edit_dpi.setPlaceholderText(QCoreApplication.translate("geo_excel", "200 (script default)"))
        self.edit_dpi.setToolTip(
            QCoreApplication.translate("geo_excel", "DPI for map images embedded by ##AttachFitImage::. "
                                       "Empty = 200."))
        form.addRow(QCoreApplication.translate("geo_excel", "DPI (map image)"), self.edit_dpi)

        self.edit_tpl_list = QLineEdit()
        self.edit_tpl_list.setPlaceholderText(QCoreApplication.translate("geo_excel", "(auto-generate)"))
        self.edit_tpl_list.setToolTip(
            QCoreApplication.translate("geo_excel", "Excel template for the list report. "
                                       "Empty = auto-generate from layer fields."))
        form.addRow(QCoreApplication.translate("geo_excel", "List report template"),
                    self._with_browse(self.edit_tpl_list))

        self.edit_tpl_single = QLineEdit()
        self.edit_tpl_single.setPlaceholderText(QCoreApplication.translate("geo_excel", "(auto-generate)"))
        self.edit_tpl_single.setToolTip(
            QCoreApplication.translate("geo_excel", "Excel template for single/bulk reports. "
                                       "Empty = auto-generate from layer fields."))
        form.addRow(QCoreApplication.translate("geo_excel", "Single report template"),
                    self._with_browse(self.edit_tpl_single))

        self.chk_auto_apply = QCheckBox(
            QCoreApplication.translate("geo_excel", "Fill missing layer variables with these defaults when running"))
        form.addRow(self.chk_auto_apply)
        return box

    def _build_layer_group(self):
        box = QGroupBox(QCoreApplication.translate("geo_excel", "Active layer variables"))
        v = QVBoxLayout(box)

        self.lbl_layer = QLabel()
        v.addWidget(self.lbl_layer)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [QCoreApplication.translate("geo_excel", "Variable"), QCoreApplication.translate("geo_excel", "Value"), QCoreApplication.translate("geo_excel", "Used by")])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setToolTip(
            QCoreApplication.translate("geo_excel", "Edit values and press Save to write them to the layer. "
                                       "Clearing a value removes the variable."))
        v.addWidget(self.table)

        row = QHBoxLayout()
        btn_apply = QPushButton(QCoreApplication.translate("geo_excel", "Apply defaults to missing variables"))
        btn_apply.clicked.connect(self._apply_defaults)
        btn_regen = QPushButton(QCoreApplication.translate("geo_excel", "Regenerate auto template"))
        btn_regen.clicked.connect(self._regen_templates)
        btn_refresh = QPushButton(QCoreApplication.translate("geo_excel", "Refresh"))
        btn_refresh.clicked.connect(self.refresh)
        row.addWidget(btn_apply)
        row.addWidget(btn_regen)
        row.addWidget(btn_refresh)
        row.addStretch(1)
        v.addLayout(row)
        return box

    def _build_requirements_group(self):
        box = QGroupBox(QCoreApplication.translate("geo_excel", "Requirements"))
        v = QVBoxLayout(box)
        text = QLabel("\n".join("- " + r for r in settings.requirements()))
        text.setWordWrap(True)
        text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(text)
        return box

    def _with_browse(self, edit, directory=False):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        btn = QPushButton(QCoreApplication.translate("geo_excel", "Browse..."))
        if directory:
            btn.clicked.connect(
                lambda: self._browse_dir(edit))
        else:
            btn.clicked.connect(
                lambda: self._browse_file(edit))
        h.addWidget(edit, 1)
        h.addWidget(btn)
        return row

    def _browse_dir(self, edit):
        start = edit.text() or settings.output_dir()
        path = QFileDialog.getExistingDirectory(
            self, QCoreApplication.translate("geo_excel", "Select output folder"), start)
        if path:
            edit.setText(path)

    def _browse_file(self, edit):
        start = edit.text() or settings.output_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, QCoreApplication.translate("geo_excel", "Select Excel template"), start,
            QCoreApplication.translate("geo_excel", "Excel files (*.xlsx *.xlsm *.xls);;All files (*)"))
        if path:
            edit.setText(path)

    # ---- 表示更新 --------------------------------------------------------------
    def refresh(self):
        env = settings.environment_report()
        self.lbl_win32com.setText(
            QCoreApplication.translate("geo_excel", "OK") if env["win32com"] else QCoreApplication.translate("geo_excel", "Not installed"))
        self.lbl_excel.setText(
            QCoreApplication.translate("geo_excel", "Registered") if env["excel_registered"]
            else QCoreApplication.translate("geo_excel", "Not detected"))
        self.lbl_documents.setText(env["documents_dir"])
        self.lbl_outdir_status.setText(
            env["output_dir"]
            + ("" if env["output_dir_exists"]
               else " " + QCoreApplication.translate("geo_excel", "(will be created)")))

        conf = settings.current_settings()
        self.edit_outdir.setText(conf["output_dir"])
        self.edit_dpi.setText(conf["dpi"])
        self.edit_tpl_list.setText(conf["template_list"])
        self.edit_tpl_single.setText(conf["template_single"])
        self.chk_auto_apply.setChecked(conf["auto_apply"])

        self._refresh_layer_table()

    def _refresh_layer_table(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            self.lbl_layer.setText(QCoreApplication.translate("geo_excel", "No active vector layer"))
            self.table.setRowCount(0)
            return
        self._layer = layer
        self.lbl_layer.setText(layer.name())

        scope = QgsExpressionContextUtils.layerScope(layer)
        names = set(scope.variableNames()) if scope is not None else set()

        used_by = {}
        for script_file, spec in settings.SCRIPT_VARS.items():
            for name in spec["required"]:
                used_by.setdefault(name, set()).add(script_file + " *")
            for name in spec["optional"]:
                used_by.setdefault(name, set()).add(script_file)

        self.table.setRowCount(len(settings.KNOWN_VARIABLES))
        for row, name in enumerate(settings.KNOWN_VARIABLES):
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)

            value = scope.variable(name) if name in names else ""
            self.table.setItem(row, 1, QTableWidgetItem(str(value or "")))

            users = sorted(used_by.get(name, ()))
            uitem = QTableWidgetItem(", ".join(users))
            uitem.setFlags(uitem.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 2, uitem)

    # ---- 操作 ------------------------------------------------------------------
    def _check_excel_launch(self):
        self.lbl_excel.setText(QCoreApplication.translate("geo_excel", "Checking..."))
        rep = settings.check_excel_launch()
        if rep.get("ok"):
            self.lbl_excel.setText(
                QCoreApplication.translate("geo_excel", "OK (version {0})").format(rep.get("version", "?")))
        else:
            self.lbl_excel.setText(
                QCoreApplication.translate("geo_excel", "Failed: {0}").format(rep.get("error", "")))

    def _apply_defaults(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            self.iface.messageBar().pushCritical(
                "geo_excel", QCoreApplication.translate("geo_excel", "Please activate a vector layer."))
            return
        applied, errors = {}, []
        for script_file in settings.SCRIPT_VARS:
            rep = settings.ensure_layer_variables(layer, script_file)
            applied.update(rep["applied"])
            errors.extend(rep["errors"])
        self._refresh_layer_table()
        if applied:
            self.iface.messageBar().pushInfo(
                "geo_excel",
                QCoreApplication.translate("geo_excel", "Applied defaults: {0}").format(", ".join(sorted(applied))))
        if errors:
            QMessageBox.warning(
                self, "geo_excel",
                QCoreApplication.translate("geo_excel", "Could not set: {0}").format(", ".join(errors)))

    def _regen_templates(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            self.iface.messageBar().pushCritical(
                "geo_excel", QCoreApplication.translate("geo_excel", "Please activate a vector layer."))
            return
        done = []
        for kind in ("list", "single"):
            if settings.configured_template(kind):
                continue  # ユーザー指定テンプレートは上書きしない
            path = settings.generated_template_path(kind, layer)
            try:
                settings.generate_template(path, layer, kind)
                done.append(path)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "geo_excel", QCoreApplication.translate("geo_excel", "Template generation failed: {0}\n{1}").format(path, e))
        if done:
            self.iface.messageBar().pushInfo(
                "geo_excel",
                QCoreApplication.translate("geo_excel", "Generated template: {0}").format(", ".join(done)))
            self._apply_defaults()

    def _save(self):
        settings.save_settings(
            output_dir_value=self.edit_outdir.text(),
            dpi=self.edit_dpi.text(),
            template_list=self.edit_tpl_list.text(),
            template_single=self.edit_tpl_single.text(),
            auto_apply=self.chk_auto_apply.isChecked())

        layer = self.iface.activeLayer()
        if isinstance(layer, QgsVectorLayer):
            for row in range(self.table.rowCount()):
                name_item = self.table.item(row, 0)
                value_item = self.table.item(row, 1)
                if not name_item or not value_item:
                    continue
                name = name_item.text()
                value = value_item.text().strip()
                scope = QgsExpressionContextUtils.layerScope(layer)
                exists = (scope is not None
                          and name in set(scope.variableNames()))
                if value:
                    QgsExpressionContextUtils.setLayerVariable(
                        layer, name, value)
                elif exists:
                    # 空欄=変数を削除して未設定に戻す
                    layer.expressionContextScope().removeVariable(name)
        self.refresh()
        self.iface.messageBar().pushInfo(
            "geo_excel", QCoreApplication.translate("geo_excel", "Settings saved."))
