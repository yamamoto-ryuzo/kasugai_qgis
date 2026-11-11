"""deployモード(dev/use)の切替UI。

メニュー「プラグイン > QGIS Live Driver > Deploy Mode」から、
開発モード(junction=repo優先)と利用モード(実体dir=退避版の復元)を
明示切替する。実際の切替はリポジトリ側の scripts/deploy-plugin.ps1 を
起動して行い、完了後にプラグインのリロードを任意で実行する。

モード宣言は profiles/<profile>/qgis_live_mode.json
({"mode":"dev"|"use","repo":"<harness repo>"})に書き出される。
宣言は意図の記録であり、モード判定は配置実態(junction/dir)が優先
される(未配置時のみ宣言で補う)。
実体dir配置(利用モード)でも marker.repo からスクリプトを解決できる。
dev化時は既存の実体プラグイン(利用版)を profiles/<profile>/
qgis_live_parked/<id> へ退避してからjunctionを張り、use化時は
junctionを外して退避版を復帰する(退避も既存実体も無ければ
未配置のまま=そのプラグインは利用されていなかった)。
repoからのcopyによる利用版の新規配置/更新は -Install(リリース操作)のみ。
junction失敗時にcopyへ自動フォールバックしない点はスクリプト側で保証済み。
"""

import json
import os
import subprocess  # nosec B404  # deploy-plugin.ps1起動に必要

CTRL_ID = "qgis_live_driver"
_MARK = "qgis_live_mode.json"
_REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


def profile_root(own_file):
    """deploy先 .../<profile>/python/plugins/<id>/<file> から
    profile rootを返す。"""
    p = os.path.abspath(own_file)
    for _ in range(4):
        p = os.path.dirname(p)
    return p


def _is_junction(path):
    """Windowsのjunction/reparse point判定(islinkはjunctionを拾わない)。"""
    try:
        st = os.stat(path, follow_symlinks=False)
        if getattr(st, "st_file_attributes", 0) & _REPARSE:
            return True
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return os.path.islink(path)


def read_marker(own_file):
    """モード宣言markerを読む。無ければ空dict。"""
    try:
        with open(os.path.join(profile_root(own_file), _MARK),
                  encoding="utf-8-sig") as f:
            m = json.load(f)
        if isinstance(m, dict):
            return m
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return {}


def repo_root(own_file):
    """harnessリポジトリのルートを返す。marker.repo優先、
    無ければjunctionのrealpath(.../qgis-plugin/<id>)から推定。"""
    m = read_marker(own_file).get("repo")
    if m and os.path.isdir(m):
        return m
    deployed = os.path.dirname(os.path.abspath(own_file))
    real = os.path.dirname(os.path.realpath(deployed))
    if os.path.basename(real) == "qgis-plugin":
        return os.path.dirname(real)
    return None


def managed_ids(own_file):
    """管理対象プラグインid一覧。repo側 plugin.config.json 優先、
    無ければjunction配置(realpathがqgis-plugin配下)のもの。"""
    root = repo_root(own_file)
    if root:
        try:
            with open(os.path.join(root, "plugin.config.json"),
                      encoding="utf-8-sig") as f:
                ids = json.load(f).get("id")
            if isinstance(ids, str):
                ids = [ids]
            if ids:
                return sorted(set(ids))
        except Exception:  # nosec B110  # 設計上の許容
            pass
    try:
        from .hot_reload import dev_plugin_ids
        return sorted(set(dev_plugin_ids(own_file) + [CTRL_ID]))
    except Exception:
        return [CTRL_ID]


def deploy_state(own_file):
    """現在のdeploy状態を返す。

    {mode, declared, actual, diverged, plugins:{id: junction|dir|missing},
     parked, repo, profile}
    mode は配置実態(actual)優先。実際に動くコードを決めるのは配置物
    なので、古い宣言で実態を上書きしない。未配置(none)の時だけ
    宣言markerで補う(use宣言=自動deploy抑制の意図を残すため)。
    宣言と実態が食い違う場合 diverged=True。
    """
    proot = profile_root(own_file)
    plugins_root = os.path.join(proot, "python", "plugins")
    parked_root = os.path.join(proot, "qgis_live_parked")
    forms = {}
    parked = {}
    for pid in managed_ids(own_file):
        p = os.path.join(plugins_root, pid)
        parked[pid] = os.path.isdir(os.path.join(parked_root, pid))
        if not os.path.isdir(p):
            forms[pid] = "missing"
        elif _is_junction(p):
            forms[pid] = "junction"
        else:
            forms[pid] = "dir"
    declared = read_marker(own_file).get("mode")
    if declared not in ("dev", "use"):
        declared = None
    vals = set(forms.values()) - {"missing"}
    if not vals:
        actual = "none"
    elif "junction" in vals and "dir" in vals:
        actual = "mixed"
    elif "junction" in vals:
        actual = "dev"
    else:
        actual = "use"
    mode = actual if actual != "none" else (declared or "none")
    return {
        "mode": mode,
        "declared": declared,
        "actual": actual,
        "diverged": declared is not None and declared != mode,
        "plugins": forms,
        "parked": parked,
        "repo": repo_root(own_file),
        "profile": os.path.basename(proot),
    }


def switch_mode(own_file, mode):
    """deploy-plugin.ps1を起動してモード切替する。(ok, output)を返す。"""
    root = repo_root(own_file)
    if not root:
        return False, "repo root not found (qgis_live_mode.json/repo不明)"
    ps1 = os.path.join(root, "scripts", "deploy-plugin.ps1")
    # QGIS(OSGeo4W系)環境はPATHが最小化され "powershell" を解決できない
    # ことがあるため、SystemRoot配下のフルパスを優先する
    exe = "powershell"
    if os.name == "nt":
        cand = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if os.path.isfile(cand):
            exe = cand
    args = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", ps1]
    if mode == "use":
        args.append("-Use")
    elif mode == "install":
        args.append("-Install")
    elif mode != "dev":
        return False, f"unknown mode: {mode}"
    kw = {"capture_output": True, "text": True, "timeout": 300}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(args, **kw)  # nosec B603  # exe/引数はホワイトリスト検証済み固定値
    except Exception as e:
        return False, str(e)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return r.returncode == 0, out


def show_dialog(iface, own_file, notify=None):
    """モード切替ダイアログをモーダル表示する。"""
    from qgis.PyQt.QtCore import QCoreApplication, Qt
    from qgis.PyQt.QtWidgets import (
        QApplication, QCheckBox, QDialog, QDialogButtonBox, QLabel,
        QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
        QVBoxLayout)

    def tr(s):
        return QCoreApplication.translate("qgis_live_driver", s)

    dlg = QDialog(iface.mainWindow())
    dlg.setWindowTitle(tr("Deploy Mode"))
    lay = QVBoxLayout(dlg)
    mode_label = QLabel(dlg)
    lay.addWidget(mode_label)
    table = QTableWidget(dlg)
    table.setColumnCount(2)
    table.setHorizontalHeaderLabels([tr("Plugin"), tr("Form")])
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    lay.addWidget(table)
    chk = QCheckBox(tr("Reload plugins after switch"), dlg)
    chk.setChecked(True)
    lay.addWidget(chk)
    note = QLabel(tr(
        "qgis_live_driver itself is reloaded via Hot Reload menu "
        "or QGIS restart."), dlg)
    note.setWordWrap(True)
    lay.addWidget(note)
    human_note = QLabel(tr(
        "[UI only] Mode switching is a manual operation — it cannot be "
        "invoked by AI or automation (no API/MCP path). "
        "deployMode() is read-only."), dlg)
    human_note.setWordWrap(True)
    lay.addWidget(human_note)
    btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close,
                            parent=dlg)
    dev_btn = QPushButton(tr("Switch to Development (junction)"), dlg)
    use_btn = QPushButton(tr("Switch to Usage (restore parked)"), dlg)
    inst_btn = QPushButton(
        tr("Install current repo as usage version (release)"), dlg)
    btns.addButton(dev_btn, QDialogButtonBox.ButtonRole.ActionRole)
    btns.addButton(use_btn, QDialogButtonBox.ButtonRole.ActionRole)
    btns.addButton(inst_btn, QDialogButtonBox.ButtonRole.ActionRole)
    btns.rejected.connect(dlg.reject)
    lay.addWidget(btns)
    dlg.resize(520, 340)

    def refresh():
        st = deploy_state(own_file)
        label = {
            "dev": tr("Development (junction: repository sources)"),
            "use": tr("Usage (restored version)"),
            "mixed": tr("Mixed"),
            "none": tr("Not deployed"),
        }.get(st["mode"], st["mode"] or "")
        text = tr("Current mode: {0}").format(label)
        if st.get("diverged") and st.get("declared"):
            dlabel = {
                "dev": tr("Development mode"),
                "use": tr("Usage mode"),
            }.get(st["declared"], st["declared"])
            text += " " + tr("(declared: {0})").format(dlabel)
        mode_label.setText(text)
        ids = list(st["plugins"])
        table.setRowCount(len(ids))
        for i, pid in enumerate(ids):
            table.setItem(i, 0, QTableWidgetItem(pid))
            form = st["plugins"][pid]
            if st.get("parked", {}).get(pid):
                form += " (+parked)"
            table.setItem(i, 1, QTableWidgetItem(form))
        table.resizeColumnsToContents()
        dev_btn.setEnabled(st["mode"] != "dev")
        use_btn.setEnabled(st["mode"] != "use")
        return st

    def do_switch(mode):
        if not deploy_state(own_file)["repo"]:
            QMessageBox.warning(
                dlg, "QGIS Live Driver",
                tr("Repository not found: cannot locate deploy-plugin.ps1"))
            return
        dev_btn.setEnabled(False)
        use_btn.setEnabled(False)
        inst_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok, out = switch_mode(own_file, mode)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            QMessageBox.warning(
                dlg, "QGIS Live Driver",
                tr("Mode switch failed") + "\n" + out[-2000:])
            inst_btn.setEnabled(True)
            refresh()
            return
        if chk.isChecked():
            # ドライバ自身は除く(このダイアログを抱えるプラグイン。
            # メニューのホットリロードかQGIS再起動で反映)
            ids = [p for p in deploy_state(own_file)["plugins"]
                   if p != CTRL_ID]
            try:
                from .hot_reload import reload_plugins
                reload_plugins(ids, notify=notify)
            except Exception:  # nosec B110  # 設計上の許容
                pass
        if notify:
            notify("info", tr("Deploy mode switched: {0}").format(mode))
        inst_btn.setEnabled(True)
        refresh()

    dev_btn.clicked.connect(lambda: do_switch("dev"))
    use_btn.clicked.connect(lambda: do_switch("use"))
    inst_btn.clicked.connect(lambda: do_switch("install"))
    refresh()
    dlg.exec()
