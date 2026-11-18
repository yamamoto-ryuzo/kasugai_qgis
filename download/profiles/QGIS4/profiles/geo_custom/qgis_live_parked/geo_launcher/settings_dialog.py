# -*- coding: utf-8 -*-
"""geo_launcher の設定ダイアログ(exe パス/サイレントインストール)。"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from . import settings


class GeoLauncherSettingsDialog(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self._plugin = plugin
        self.tr = plugin.tr
        self.setWindowTitle(self.tr("geo_launcher Settings"))

        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self.edit_exe = QLineEdit(self)
        self.edit_exe.setPlaceholderText(settings.DEFAULT_EXE)
        btn_browse = QPushButton(self.tr("Browse..."), self)
        btn_browse.clicked.connect(self._browse)
        w = QWidget(self)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.edit_exe)
        h.addWidget(btn_browse)
        form.addRow(self.tr("qgis_launcher.exe path:"), w)
        self.lbl_detect = QLabel(self)
        self.lbl_detect.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(self.tr("Detected:"), self.lbl_detect)

        self.chk_silent = QCheckBox(
            self.tr("Run installer silently (/S)"), self)
        form.addRow(self.chk_silent)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel, parent=self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.refresh()

    def refresh(self):
        self.edit_exe.setText(settings.exe_path())
        det = settings.detect_exe()
        self.lbl_detect.setText(det or self.tr("(not found)"))
        self.chk_silent.setChecked(settings.silent_install())

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select qgis_launcher.exe"),
            os.path.dirname(settings.detect_exe() or settings.DEFAULT_EXE),
            "qgis_launcher.exe (qgis_launcher.exe);;All files (*)")
        if path:
            self.edit_exe.setText(path)

    def _save(self):
        settings.save_settings(
            exe_path_value=self.edit_exe.text().strip(),
            silent_install_value=self.chk_silent.isChecked())
        self.accept()
