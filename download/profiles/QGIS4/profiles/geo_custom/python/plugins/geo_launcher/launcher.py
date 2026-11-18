# -*- coding: utf-8 -*-
"""kasugai_qgis ランチャーとのやり取りをまとめた実行プリミティブ層。

kasugai_qgis は QGIS を「起動するための器」であり、QGIS を起動すると
本体は自動終了する設計(POST /launch 後にサーバ停止、GUI 窓も閉じる)。
したがってこのプラグインは API サーバを起動・維持する機能を持たず、
以下に限定する:

- 検出: settings.detect_exe() に委譲
- バージョン: `qgis_launcher.exe --version` を起動して即終了させて取得
- 起動経由判定: 本体が QGIS 子プロセスへ注入する PORTAL_USERROLE を見る
- 起動: QProcess.startDetached (引数なし=GUI モード→WebView2 窓。
  窓内で「起動」を押すと本体が新しい QGIS を立てて自動終了する)
- インストール: QNetworkAccessManager で setup.exe を非同期 DL し、
  完了後にインストーラーを startDetached で実行(/S でサイレント可)
- アンインストール: インストール先の uninstall.exe を実行

GUI スレッドを長時間占有する処理は Installer 側で Qt 非同期化している。
"""

import os
import re
import tempfile

from qgis.PyQt.QtCore import QObject, QProcess, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsNetworkAccessManager

from . import settings


class LauncherError(Exception):
    """ドメインエラー(bridge では {"ok": false, "error": ...} に写す)。"""


# ---- 検出/状態 -------------------------------------------------------------

def exe_version(exe=None):
    """`qgis_launcher.exe --version` の出力からバージョン文字列を取り出す。

    clap 製なので --version を表示して即終了する。GUI スレッドで呼んでも
    実質の待ち時間はごく短い(上限 10 秒)。
    """
    exe = exe or settings.detect_exe()
    if not exe:
        return None
    p = QProcess()
    p.start(exe, ["--version"])
    if not p.waitForFinished(10000) or p.exitCode() != 0:
        return None
    out = bytes(p.readAllStandardOutput()).decode("utf-8", "replace").strip()
    m = re.search(r"\d+\.\d+\.\d+[\w.\-+]*", out)
    return m.group(0) if m else (out or None)


def launched_via_role():
    """この QGIS が kasugai_qgis 経由で起動した場合、その role を返す。

    本体は QGIS 起動時に cmd.env("PORTAL_USERROLE", role) を注入する
    (src/main.rs)。直接起動した QGIS では環境変数が存在しないので None。
    """
    v = os.environ.get("PORTAL_USERROLE") or ""
    return v or None


# ---- 起動/アンインストール --------------------------------------------------

def launch():
    """qgis_launcher.exe を GUI モード(WebView2 窓)で startDetached 起動する。

    窓内でユーザーが「起動」を押すと本体が新しい QGIS を立てて自動終了する
    (本体側の責務。プラグインはサーバのライフサイクルを管理しない)。
    """
    exe = settings.detect_exe()
    if not exe:
        raise LauncherError(
            "qgis_launcher.exe not found (install it or set the path in "
            "Settings)")
    if not QProcess.startDetached(exe, [], os.path.dirname(exe)):
        raise LauncherError("failed to start: {}".format(exe))
    return {"ok": True, "exe": exe}


def _run_setup_exe(path, args):
    """セットアップ/アンインストーラー exe を起動する。

    引数あり(サイレント等)は startDetached、引数なしは ShellExecute
    (QDesktopServices.openUrl) にする。startDetached で GUI インストーラーを
    起動するとフォアグラウンド権を取れず QGIS ウィンドウの後ろに隠れて
    ユーザーが完了できない事があるため、窓を出す起動はシェル経由に揃える。
    """
    if args:
        return QProcess.startDetached(path, args)
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(path)))


def run_installer(installer_path, silent=None):
    """DL 済みのセットアップを実行する。"""
    silent = settings.silent_install() if silent is None else bool(silent)
    args = ["/S"] if silent else []
    if not _run_setup_exe(installer_path, args):
        raise LauncherError(
            "failed to start installer: {}".format(installer_path))
    return {"ok": True, "installer": installer_path, "silent": silent}


def find_uninstaller(exe=None):
    """インストール先の uninstall.exe を返す。見つからなければ None。"""
    exe = exe or settings.detect_exe()
    if not exe:
        return None
    path = os.path.join(os.path.dirname(exe), "uninstall.exe")
    return path if os.path.isfile(path) else None


def uninstall(silent=None):
    """アンインストーラー(uninstall.exe)を startDetached で実行する。"""
    un = find_uninstaller()
    if not un:
        raise LauncherError(
            "uninstall.exe not found (next to qgis_launcher.exe)")
    silent = settings.silent_install() if silent is None else bool(silent)
    args = ["/S"] if silent else []
    if not _run_setup_exe(un, args):
        raise LauncherError(
            "failed to start uninstaller: {}".format(un))
    return {"ok": True, "uninstaller": un, "silent": silent}


# ---- インストーラーダウンロード(Qt非同期) ------------------------------------

class Installer(QObject):
    """setup.exe の DL→インストーラー起動を Qt 非同期で行う。

    状態は status() で参照でき、bridge の installStatus() からも読める。
    phase: idle | downloading | running_installer | done | error
    """

    progress = pyqtSignal(int, int)     # received, total(-1=不明)
    phaseChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # QGIS側のプロキシ/SSL設定を継承する共有インスタンスを使う
        # (素のQNetworkAccessManagerはQGISのプロキシ設定を拾わない)
        self._nam = QgsNetworkAccessManager.instance()
        self._reply = None
        self._proc = None
        self._file = None
        self._phase = "idle"
        self._received = 0
        self._total = -1
        self._error = ""
        self._path = ""
        self._silent = False
        self._autorun = True
        self._retry = 0

    def status(self):
        return {"phase": self._phase, "received": self._received,
                "total": self._total, "error": self._error,
                "path": self._path}

    def _set_phase(self, phase):
        self._phase = phase
        self.phaseChanged.emit(phase)

    def start(self, silent=None, autorun=True):
        """DL を開始する。autorun=True なら完了後にインストーラーを起動。"""
        if self._phase == "downloading":
            return self.status()
        self._silent = (settings.silent_install() if silent is None
                        else bool(silent))
        self._autorun = bool(autorun)
        self._received = 0
        self._total = -1
        self._error = ""
        self._path = os.path.join(tempfile.gettempdir(),
                                  "kasugai_qgis-setup.exe")
        self._retry = 0
        try:
            self._file = open(self._path, "wb")
        except OSError as e:
            self._error = str(e)
            self._set_phase("error")
            return self.status()
        self._begin_download()
        return self.status()

    def _begin_download(self):
        req = QNetworkRequest(QUrl(settings.SETUP_URL))
        # Qt は既定で Accept-Encoding: gzip を送るため、GitHub Pages が
        # Content-Encoding: gzip で応答し Qt 側の透過伸張により
        # downloadProgress の total が -1(進捗%不明)になる。
        # identity を要求して Content-Length を確実に受け取る
        req.setRawHeader(b"Accept-Encoding", b"identity")
        # 共有ネットワークキャッシュの空/中断済みエントリで
        # HTTP200・0バイト応答になることがあるため常にネットワーク経由に
        req.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.AlwaysNetwork)
        # 27MB のバイナリはキャッシュに残さない
        req.setAttribute(
            QNetworkRequest.Attribute.CacheSaveControlAttribute, False)
        self._reply = self._nam.get(req)
        self._reply.downloadProgress.connect(self._on_progress)
        self._reply.readyRead.connect(self._on_ready_read)
        self._reply.finished.connect(self._on_finished)
        self._set_phase("downloading")

    def abort(self):
        if self._reply is not None:
            self._reply.abort()

    def _on_progress(self, received, total):
        self._received = int(received)
        self._total = int(total)
        self.progress.emit(self._received, self._total)

    def _on_ready_read(self):
        if self._file is not None and self._reply is not None:
            self._file.write(bytes(self._reply.readAll()))

    def _on_finished(self):
        reply, self._reply = self._reply, None
        if self._file is not None:
            self._file.close()
            self._file = None
        err = reply.error() if reply is not None else None
        status = None
        if reply is not None:
            status = reply.attribute(
                QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            reply.deleteLater()
        # QNetworkReply.NoError == 0
        if err not in (None, QNetworkReply.NetworkError.NoError) \
                or self._received <= 0:
            # 0バイト・NoError(空応答/キャッシュ起因)は自動リトライ
            if self._received <= 0 and self._retry < 2:
                self._retry += 1
                if self._file is not None:
                    self._file.seek(0)
                    self._file.truncate(0)
                self._begin_download()
                return
            detail = []
            if reply is not None:
                detail.append("{} ({})".format(
                    reply.errorString(),
                    QNetworkReply.NetworkError(err).name
                    if err is not None else "?"))
            if status is not None:
                detail.append("HTTP {}".format(status))
            self._error = "download failed: {}".format(
                ", ".join(detail) or "no data")
            try:
                os.remove(self._path)
            except OSError:
                pass
            self._set_phase("error")
            return
        if not self._autorun:
            self._set_phase("done")
            return
        if self._silent:
            # /S は GUI を持たないため QProcess で終了を追跡する
            self._proc = QProcess(self)
            self._proc.finished.connect(self._on_installer_done)
            self._proc.start(self._path, ["/S"])
            if not self._proc.waitForStarted(5000):
                self._error = "failed to start installer: {}".format(
                    self._path)
                self._set_phase("error")
                return
            self._set_phase("running_installer")
            return
        try:
            # 非サイレントは ShellExecute でウィザードへ引き渡し=この時点で完了
            run_installer(self._path, False)
        except LauncherError as e:
            self._error = str(e)
            self._set_phase("error")
            return
        self._set_phase("done")

    def _on_installer_done(self, code, _status):
        if code != 0:
            self._error = "installer exited with code {}".format(code)
            self._set_phase("error")
        else:
            self._set_phase("done")
