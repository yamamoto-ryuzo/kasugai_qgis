# -*- coding: utf-8 -*-
"""geo_launcher の状態パネル(インストール/アンインストール/起動)。

このプラグインの本質は「kasugai_qgis をインストール/アンインストールする
こと」であり、起動済みランチャーのサーバ管理は持たない(QGIS を起動
すれば本体は自動終了する設計のため)。
"""

from qgis.PyQt.QtCore import Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from . import launcher, settings


class GeoLauncherDialog(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self._plugin = plugin
        self.tr = plugin.tr
        self.setWindowTitle(self.tr("Kasugai QGIS Launcher"))
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)

        # ---- 基本操作(インストール/アンインストールの大ボタン) ----
        row = QHBoxLayout()
        self.btn_install = QPushButton(
            self.tr("Install / Reinstall..."), self)
        self.btn_install.clicked.connect(self._install)
        self.btn_uninstall = QPushButton(self.tr("Uninstall..."), self)
        self.btn_uninstall.clicked.connect(self._uninstall)
        for b, color in ((self.btn_install, "#16a34a"),
                         (self.btn_uninstall, "#dc2626")):
            b.setMinimumHeight(44)
            b.setStyleSheet(
                "QPushButton { background-color: %s; color: white;"
                " font-weight: bold; font-size: 13px; border-radius: 6px; }"
                "QPushButton:disabled { background-color: #9ca3af; }"
                % color)
            row.addWidget(b)
        lay.addLayout(row)

        # ---- インストール状態 ----
        box_inst = QGroupBox(self.tr("Installation"), self)
        form = QFormLayout(box_inst)
        self.lbl_exe = QLabel("-", box_inst)
        self.lbl_exe.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_ver = QLabel("-", box_inst)
        self.lbl_via = QLabel("-", box_inst)
        form.addRow(self.tr("Launcher:"), self.lbl_exe)
        form.addRow(self.tr("Version:"), self.lbl_ver)
        form.addRow(self.tr("This QGIS:"), self.lbl_via)
        self.lbl_note = QLabel(
            self.tr("The launcher exits automatically after it "
                    "starts QGIS."), box_inst)
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet("color: #6b7280; font-size: 11px;")
        form.addRow(self.lbl_note)
        lay.addWidget(box_inst)

        # ---- 操作 ----
        row = QHBoxLayout()
        self.btn_launch = QPushButton(self.tr("Open Launcher"), self)
        self.btn_launch.clicked.connect(self._launch)
        self.btn_settings = QPushButton(self.tr("Settings..."), self)
        self.btn_settings.clicked.connect(self._open_settings)
        self.btn_docs = QPushButton(self.tr("Docs"), self)
        self.btn_docs.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(settings.DOCS_URL)))
        for b in (self.btn_launch, self.btn_settings, self.btn_docs):
            row.addWidget(b)
        lay.addLayout(row)

        self.progress = QProgressBar(self)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close,
                              parent=self)
        bb.rejected.connect(self.reject)
        btn_refresh = bb.addButton(
            self.tr("Refresh"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_refresh.clicked.connect(self.refresh)
        lay.addWidget(bb)

        # インストーラーの進捗シグナル
        inst = self._plugin.installer
        inst.progress.connect(self._on_dl_progress)
        inst.phaseChanged.connect(lambda _p: self.refresh())

        # インストーラー実行中(DL中/セットアップ実行中)だけ軽くポーリングし、
        # サイレントインストール完了後に検出状態が更新されるようにする
        self._poll = QTimer(self)
        self._poll.setInterval(2000)
        self._poll.timeout.connect(self.refresh)
        self._poll_ticks = 0

        self.refresh()

    # ---- 状態表示 ----
    def refresh(self):
        exe = settings.detect_exe()
        self.lbl_exe.setText(exe or self.tr("(not installed)"))
        ver = launcher.exe_version(exe) if exe else None
        self.lbl_ver.setText(ver or self.tr("(unknown)"))
        role = launcher.launched_via_role()
        self.lbl_via.setText(
            self.tr("via launcher (role: {0})").format(role) if role
            else self.tr("direct start"))
        self.btn_uninstall.setEnabled(launcher.find_uninstaller(exe)
                                      is not None)
        self.btn_launch.setEnabled(exe is not None)

        st = self._plugin.installer.status()
        phase = st.get("phase")
        if phase in ("downloading", "running_installer"):
            # 最大 ~2 分だけポーリング(サイレントインストール完了検出用)
            self._poll_ticks += 1
            if self._poll_ticks <= 60 and not self._poll.isActive():
                self._poll.start()
        else:
            self._poll_ticks = 0
            if self._poll.isActive():
                self._poll.stop()
        if phase == "downloading":
            received = int(st.get("received") or 0)
            total = int(st.get("total") or 0)
            self.progress.setVisible(True)
            if total > 0:
                self.progress.setMaximum(total)
                self.progress.setValue(received)
                self.progress.setFormat(self.tr("Downloading... %p%"))
            else:
                # Content-Length 無し(GitHub Pages)では MB 表示に切替
                self.progress.setMaximum(0)
                self.progress.setFormat(
                    self.tr("Downloading... {0} MB").format(
                        round(received / 1048576, 1)))
        elif phase == "running_installer":
            self.progress.setVisible(True)
            self.progress.setMaximum(0)
            self.progress.setFormat(self.tr("Running installer..."))
        elif phase == "error":
            self.progress.setVisible(True)
            self.progress.setMaximum(100)
            self.progress.setValue(0)
            self.progress.setFormat(
                self.tr("Error: {0}").format(st.get("error") or ""))
        else:
            self.progress.setVisible(False)

    def _on_dl_progress(self, _recv, _total):
        if self._plugin.installer.status().get("phase") == "downloading":
            self.refresh()

    def _warn(self, msg):
        self.iface_bar().pushCritical("geo_launcher", msg)

    def iface_bar(self):
        return self._plugin.iface.messageBar()

    # ---- 操作 ----
    def _launch(self):
        try:
            launcher.launch()
        except launcher.LauncherError as e:
            self._warn(str(e))
        self.refresh()

    def _install(self):
        r = QMessageBox.question(
            self, "geo_launcher",
            self.tr("Download the kasugai_qgis installer and run it?"))
        if r != QMessageBox.StandardButton.Yes:
            return
        self._poll_ticks = 0
        self._plugin.installer.start()
        self.refresh()

    def _uninstall(self):
        if not launcher.find_uninstaller():
            self._warn(self.tr("uninstall.exe not found."))
            return
        r = QMessageBox.question(
            self, "geo_launcher",
            self.tr("Uninstall kasugai_qgis? "
                    "This removes the installed launcher."))
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            launcher.uninstall()
        except launcher.LauncherError as e:
            self._warn(str(e))
        # サイレントアンインストールは数秒かかるため段階的に再描画
        for ms in (1500, 4000, 8000):
            QTimer.singleShot(ms, self.refresh)

    def _open_settings(self):
        self._plugin.open_settings()

    def closeEvent(self, e):
        if self._poll.isActive():
            self._poll.stop()
        super().closeEvent(e)
