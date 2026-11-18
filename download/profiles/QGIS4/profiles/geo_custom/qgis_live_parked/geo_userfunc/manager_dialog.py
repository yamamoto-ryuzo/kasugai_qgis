# -*- coding: utf-8 -*-
"""geo_userfunc 管理ダイアログ。

ライブラリ(<profile>/python/geo_userfunc/)内の関数ファイルを
一覧・有効化・編集・再読込・upstream更新するQt Widgetsダイアログ。
下段に他プラグインが共有レジストリへ登録したマクロを表示する。

文字列は QCoreApplication.translate("geo_userfunc", ...) に統一し
i18n/<lang>.json の context "geo_userfunc" に集約する。
"""

import os

from qgis.PyQt.QtCore import QCoreApplication, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

CTX = "geo_userfunc"


def _tr(msg):
    return QCoreApplication.translate(CTX, msg)


class _FunctionEditDialog(QDialog):
    """1ファイルのソース編集ダイアログ(構文検証付き保存)。"""

    def __init__(self, plugin, file_name, parent=None):
        super().__init__(parent)
        self._plugin = plugin
        self._file = file_name
        self.setWindowTitle(
            "{0} — {1}".format(file_name, _tr("Edit function")))
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.editor)

        self.status = QLabel("")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        r = plugin.library.read_file(file_name)
        if r.get("ok"):
            self.editor.setPlainText(r["source"])
        else:
            self.status.setText(r.get("error", ""))

    def _save(self):
        r = self._plugin.library.save_file(
            self._file, self.editor.toPlainText())
        if r.get("ok"):
            self.status.setText(_tr("Saved. Apply with Reload."))
        else:
            self.status.setText(r.get("error", ""))
            QMessageBox.warning(self, _tr("geo_userfunc"),
                                r.get("error", ""))


class GeoUserfuncManagerDialog(QDialog):
    """ユーザー関数ライブラリの管理ダイアログ。"""

    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self._plugin = plugin
        self.iface = plugin.iface
        self.setWindowTitle(_tr("geo_userfunc — user function library"))
        self.resize(820, 560)

        layout = QVBoxLayout(self)

        self.dir_label = QLabel()
        layout.addWidget(self.dir_label)

        # ---- ライブラリのファイル一覧 ----
        box = QGroupBox(_tr("Library files"))
        vb = QVBoxLayout(box)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            _tr("Enabled"), _tr("File"), _tr("Type"), _tr("Contents / error")])
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        vb.addWidget(self.table)
        layout.addWidget(box)

        # ---- 共有レジストリ(他プラグイン登録分) ----
        rbox = QGroupBox(_tr("Registered by other plugins"))
        rvb = QVBoxLayout(rbox)
        self.reg_table = QTableWidget(0, 3)
        self.reg_table.setHorizontalHeaderLabels(
            [_tr("ID"), _tr("Title"), _tr("Source plugin")])
        self.reg_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.reg_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        rvb.addWidget(self.reg_table)
        layout.addWidget(rbox)

        # ---- 操作ボタン ----
        row = QHBoxLayout()
        for label, slot in (
            ("Reload", self._reload),
            ("New file...", self._new_file),
            ("Edit...", self._edit_selected),
            ("Open folder", self._open_folder),
            ("Fetch from URL...", self._fetch_url),
            ("Update from upstream", self._update_upstream),
        ):
            b = QPushButton(_tr(label))
            b.clicked.connect(slot)
            row.addWidget(b)
        layout.addLayout(row)

        self.status = QLabel("")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._loading = False
        self.refresh()

    # ---- 表示更新 -----------------------------------------------------------

    def refresh(self):
        lib = self._plugin.library
        self.dir_label.setText("{0}: {1}".format(_tr("Library dir"), lib.dir))

        self._loading = True
        try:
            self.table.setRowCount(0)
            for e in lib.entries.values():
                row = self.table.rowCount()
                self.table.insertRow(row)

                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                             | Qt.ItemFlag.ItemIsEnabled)
                chk.setCheckState(
                    Qt.CheckState.Checked if e.enabled
                    else Qt.CheckState.Unchecked)
                chk.setData(Qt.ItemDataRole.UserRole, e.file)
                self.table.setItem(row, 0, chk)

                self.table.setItem(row, 1, QTableWidgetItem(e.file))
                types = ", ".join(e.describe()["types"]) or "-"
                self.table.setItem(row, 2, QTableWidgetItem(types))

                if e.error or (e.info and e.info.get("error")):
                    detail = e.error or e.info["error"]
                elif e.info:
                    parts = [f["register_name"]
                             for f in e.info["functions"]]
                    parts += ["hook:" + h for h in e.info["hooks"]]
                    if e.info.get("has_main"):
                        parts.append("main()")
                    detail = ", ".join(parts) or "(no exports)"
                else:
                    detail = "(disabled)"
                self.table.setItem(row, 3, QTableWidgetItem(detail))
        finally:
            self._loading = False

        self.reg_table.setRowCount(0)
        for m in self._plugin.registry.describe():
            row = self.reg_table.rowCount()
            self.reg_table.insertRow(row)
            self.reg_table.setItem(row, 0, QTableWidgetItem(m["id"]))
            self.reg_table.setItem(row, 1, QTableWidgetItem(m["title"]))
            self.reg_table.setItem(
                row, 2, QTableWidgetItem(m.get("plugin_id") or ""))

    def _on_item_changed(self, item):
        if self._loading or item.column() != 0:
            return
        file_name = item.data(Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == Qt.CheckState.Checked
        self._plugin.library.set_enabled(file_name, enabled)
        self.status.setText(
            _tr("{0}: {1} (apply with Reload)").format(
                file_name,
                _tr("enabled") if enabled else _tr("disabled")))

    # ---- 操作 ---------------------------------------------------------------

    def _selected_file(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        return item.text() if item else None

    def _reload(self):
        _ = self._plugin.library.reload()
        self._plugin._sync_macro_menu()
        self.refresh()
        self.status.setText(_tr("Reloaded."))

    def _new_file(self):
        name, ok = QInputDialog.getText(
            self, _tr("New function file"), _tr("File name (.py):"),
            QLineEdit.EchoMode.Normal, "")
        if not ok or not name.strip():
            return
        r = self._plugin.library.save_file(
            name.strip(),
            "from qgis.core import *\nfrom qgis.gui import *\n\n")
        if r.get("ok"):
            self._plugin.library.scan()
            self.refresh()
            _FunctionEditDialog(self._plugin, r["file"], self).exec()
        else:
            QMessageBox.warning(self, "geo_userfunc", r.get("error", ""))

    def _edit_selected(self):
        name = self._selected_file()
        if not name:
            return
        _FunctionEditDialog(self._plugin, name, self).exec()
        self.refresh()

    def _open_folder(self):
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(self._plugin.library.dir))

    def _fetch_url(self):
        url, ok = QInputDialog.getText(
            self, _tr("Fetch function file"),
            _tr("URL of a .py file:"), QLineEdit.EchoMode.Normal, "")
        if not ok or not url.strip():
            return
        import urllib.request
        import urllib.parse
        url = url.strip()
        if urllib.parse.urlparse(url).scheme.lower() not in ("http", "https"):
            QMessageBox.warning(self, "geo_userfunc",
                                _tr("Only http/https URLs are allowed."))
            return
        try:
            with urllib.request.urlopen(url, timeout=15) as r:  # nosec B310  # 直上でhttp/httpsスキームを検証済み
                src = r.read().decode("utf-8")
        except Exception as e:
            QMessageBox.warning(self, "geo_userfunc", str(e))
            return
        fname = os.path.basename(url.strip().split("?")[0]) or "fetched.py"
        res = self._plugin.library.save_file(fname, src)
        if res.get("ok"):
            self._plugin.library.reload()
            self.refresh()
            self.status.setText(_tr("Fetched {0}.").format(res["file"]))
        else:
            QMessageBox.warning(self, "geo_userfunc", res.get("error", ""))

    def _update_upstream(self):
        results = self._plugin.library.update_from_upstream()
        if not results:
            self.status.setText(_tr("No upstream sources (sources.json)."))
            return
        self._plugin.library.reload()
        self.refresh()
        ok = sum(1 for r in results if r.get("ok"))
        self.status.setText(
            _tr("Upstream update: {0}/{1} files.").format(ok, len(results)))
