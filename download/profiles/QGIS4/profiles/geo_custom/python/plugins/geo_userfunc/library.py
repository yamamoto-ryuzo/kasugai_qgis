# -*- coding: utf-8 -*-
"""geo_userfunc 関数ライブラリ。

<profile>/python/geo_userfunc/ 配下の *.py をスキャンし、ASTで型分類して登録する。

  - @qgsfunction デコレータ付き関数 → exec 時に式エンジンへ自動登録(関数型)
  - openProject / saveProject / closeProject → iface/QgsProject の信号へ接続
    (フック型マクロ)
  - main(context) → 手動実行マクロとして run/メニュー/bridge の対象にする

manifest.json でファイル単位の有効/無効を永続化する。

ライブラリdirは初回起動時に同梱の functions/ からシードされる
(以降はライブラリdirが稼働正本。同梱側を更新しても自動上書きしない。
upstream 追従は update_from_upstream() で明示的に行う)。

ファイルの exec はGUIスレッドで行われる。登録・解除ともに
QgsExpression.registerFunction/unregisterFunction と信号の connect/
disconnect で対称に行い、reload で差し替え可能にする。
"""

import ast
import json
import os
import shutil
import traceback

from qgis.core import (
    QgsApplication,
    QgsExpression,
    QgsMessageLog,
    QgsProject,
    Qgis,
)

PLUGIN_ID = "geo_userfunc"
HOOK_NAMES = ("openProject", "saveProject", "closeProject")
SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "functions")
MANIFEST_FILE = "manifest.json"
SOURCES_FILE = "sources.json"
LOG_TAG = "geo_userfunc"


def library_dir():
    """稼働ライブラリdir(<profile>/python/geo_userfunc/)を返す。"""
    return os.path.join(
        QgsApplication.qgisSettingsDirPath(), "python", PLUGIN_ID)


def _log(msg, level=Qgis.MessageLevel.Warning):
    QgsMessageLog.logMessage(str(msg), LOG_TAG, level)


def _is_qgsfunction_decorator(dec):
    """デコレータノードが qgsfunction / qgsfunction(...) かを判定。"""
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Name):
        return dec.id == "qgsfunction"
    if isinstance(dec, ast.Attribute):
        return dec.attr == "qgsfunction"
    return False


def _kw_str(call, name):
    """Callノードのキーワード引数(文字列定数)を取り出す。"""
    if not isinstance(call, ast.Call):
        return None
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            if isinstance(kw.value.value, str):
                return kw.value.value
    return None


def analyze_source(src, path="<string>"):
    """ソースをAST解析し、関数/フック/マクロの定義を返す。

    戻り値:
      {"ok": bool, "error": str|None,
       "functions": [{name, register_name, group, signature, doc}],
       "hooks": [openProject...], "has_main": bool,
       "types": ["expression"|"hook"|"macro"...]}
    """
    info = {"ok": True, "error": None, "functions": [], "hooks": [],
            "has_main": False, "types": []}
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as e:
        info["ok"] = False
        info["error"] = "SyntaxError: {0} (line {1})".format(e.msg, e.lineno)
        return info

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        try:
            sig = "{0}({1})".format(node.name, ast.unparse(node.args))
        except Exception:
            sig = node.name + "(...)"
        doc = ast.get_docstring(node) or ""

        for dec in node.decorator_list:
            if _is_qgsfunction_decorator(dec):
                reg_name = _kw_str(dec, "name") or node.name
                info["functions"].append({
                    "name": node.name,
                    "register_name": reg_name,
                    "group": _kw_str(dec, "group") or "Custom",
                    "signature": sig,
                    "doc": doc.split("\n")[0] if doc else "",
                })
                break

        if node.name in HOOK_NAMES:
            info["hooks"].append(node.name)
        if node.name == "main":
            info["has_main"] = True
            info["macro_doc"] = doc.split("\n")[0] if doc else ""
            info["macro_signature"] = sig

    if info["functions"]:
        info["types"].append("expression")
    if info["hooks"]:
        info["types"].append("hook")
    if info["has_main"]:
        info["types"].append("macro")
    return info


class FileEntry:
    """ライブラリ内の1ファイルの状態。"""

    def __init__(self, path):
        self.path = path
        self.file = os.path.basename(path)
        self.stem = os.path.splitext(self.file)[0]
        self.enabled = True
        self.info = None          # analyze_source の結果
        self.error = None         # exec 時のエラー
        self.ns = None            # exec 後の名前空間
        self.expr_names = []      # 登録した式関数名
        self.connections = []     # (signal, slot) の配線済みペア

    def describe(self):
        return {
            "file": self.file,
            "name": self.stem,
            "enabled": self.enabled,
            "types": (self.info or {}).get("types", []),
            "functions": (self.info or {}).get("functions", []),
            "hooks": (self.info or {}).get("hooks", []),
            "has_main": bool((self.info or {}).get("has_main")),
            "macro_doc": (self.info or {}).get("macro_doc", ""),
            "parse_error": (self.info or {}).get("error"),
            "error": self.error,
        }


class FunctionLibrary:
    """ライブラリdirの走査・登録・解除を司る。"""

    def __init__(self, iface):
        self.iface = iface
        self.dir = library_dir()
        self.entries = {}  # file -> FileEntry

    # ---------- シード ----------

    def seed(self):
        """同梱 functions/ をライブラリdirへ初回コピーする(既存は上書きしない)。"""
        os.makedirs(self.dir, exist_ok=True)
        if not os.path.isdir(SEED_DIR):
            return
        for name in os.listdir(SEED_DIR):
            src = os.path.join(SEED_DIR, name)
            dst = os.path.join(self.dir, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except OSError as e:
                    _log("seed copy failed {0}: {1}".format(name, e))

    # ---------- manifest ----------

    def _manifest_path(self):
        return os.path.join(self.dir, MANIFEST_FILE)

    def _load_manifest(self):
        try:
            with open(self._manifest_path(), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):  # nosec B110  # 設計上の許容
            pass
        return {}

    def _save_manifest(self, data):
        try:
            with open(self._manifest_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            _log("manifest save failed: {0}".format(e))

    def set_enabled(self, file_name, enabled):
        """ファイルの有効/無効をmanifestへ保存する(reloadは呼び出し側)。"""
        data = self._load_manifest()
        data.setdefault("enabled", {})[file_name] = bool(enabled)
        self._save_manifest(data)

    # ---------- スキャン/ロード ----------

    def scan(self):
        """ライブラリdirを走査して FileEntry 一覧を作る(未exec)。"""
        manifest = self._load_manifest().get("enabled", {})
        entries = {}
        if os.path.isdir(self.dir):
            for name in sorted(os.listdir(self.dir)):
                if not name.endswith(".py") or name.startswith(("_", ".")):
                    continue
                entry = FileEntry(os.path.join(self.dir, name))
                entry.enabled = bool(manifest.get(name, True))
                entries[name] = entry
        self.entries = entries
        return entries

    def load_all(self):
        """有効ファイルを解析・exec・登録する。"""
        if not self.entries:
            self.scan()
        for entry in self.entries.values():
            if not entry.enabled:
                continue
            self._load_entry(entry)

    def _load_entry(self, entry):
        try:
            with open(entry.path, encoding="utf-8") as f:
                src = f.read()
        except OSError as e:
            entry.error = "read error: {0}".format(e)
            return

        entry.info = analyze_source(src, entry.path)
        if not entry.info["ok"]:
            entry.error = entry.info["error"]
            return

        ns = {
            "__name__": "{0}_lib.{1}".format(PLUGIN_ID, entry.stem),
            "__file__": entry.path,
            "iface": self.iface,
        }
        try:
            exec(compile(src, entry.path, "exec"), ns)  # nosec B102  # ユーザーコードの実行が本プラグインの主目的
        except Exception:
            entry.error = traceback.format_exc(limit=3)
            _log("exec failed {0}:\n{1}".format(entry.file, entry.error))
            return
        entry.ns = ns

        # @qgsfunction はデコレータ実行時に QgsExpression へ登録済み。
        # 解除に備えて登録名を記録する。
        entry.expr_names = [f["register_name"]
                            for f in entry.info["functions"]]

        # フックの信号配線
        for hook in entry.info["hooks"]:
            fn = ns.get(hook)
            if not callable(fn):
                continue
            conn = self._connect_hook(hook, fn)
            if conn is not None:
                sig, slot = conn
                try:
                    sig.connect(slot)
                    entry.connections.append((sig, slot))
                except Exception as e:
                    _log("hook connect failed {0}:{1}: {2}"
                         .format(entry.file, hook, e))
            else:
                _log("no signal for hook {0} ({1})".format(hook, entry.file))

    def _connect_hook(self, hook, fn):
        """hook名に対応する信号と接続用slotを返す。無ければNone。

        対応:
          openProject  → iface.projectRead(プロジェクト読込後)
          saveProject  → QgsProject.projectSaved(保存後)
                         無い環境では writeProject(保存書込時)へフォールバック
          closeProject → QgsProject.cleared(プロジェクト解放時)
                         無い環境では iface.newProjectCreated へフォールバック
        引数付き信号は slot で包んで hook関数(無引数規約)を呼ぶ。
        """
        if hook == "openProject":
            sig = getattr(self.iface, "projectRead", None)
            return (sig, (lambda *a: fn())) if sig is not None else None
        proj = QgsProject.instance()
        if hook == "saveProject":
            sig = getattr(proj, "projectSaved", None)
            if sig is not None:
                return (sig, (lambda *a: fn()))
            sig = getattr(proj, "writeProject", None)
            return (sig, (lambda *a: fn())) if sig is not None else None
        if hook == "closeProject":
            sig = getattr(proj, "cleared", None)
            if sig is None:
                sig = getattr(self.iface, "newProjectCreated", None)
            return (sig, (lambda *a: fn())) if sig is not None else None
        return None

    # ---------- 解除 ----------

    def unload_all(self):
        """登録した式関数を外し、信号配線を切断する。"""
        for entry in self.entries.values():
            for name in entry.expr_names:
                try:
                    QgsExpression.unregisterFunction(name)
                except Exception as e:
                    _log("unregisterFunction {0}: {1}".format(name, e))
            for sig, slot in entry.connections:
                try:
                    sig.disconnect(slot)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            entry.expr_names = []
            entry.connections = []
            entry.ns = None

    def reload(self):
        """全解除 → 再走査 → 再登録。"""
        self.unload_all()
        self.scan()
        self.load_all()
        return self.describe()

    # ---------- 実行 ----------

    def make_context(self, layer_id=None, feature_id=None, args=None):
        """マクロ main(context) に渡すコンテキストを組み立てる。"""
        try:
            from qgis.utils import plugins
        except Exception:
            plugins = {}
        layer = None
        if layer_id:
            layer = QgsProject.instance().mapLayer(str(layer_id))
        return {
            "iface": self.iface,
            "plugins": plugins,
            "layer": layer,
            "layer_id": layer_id,
            "feature_id": feature_id,
            "args": args or {},
        }

    def find_macro(self, name):
        """ファイル名/stemで main を持つ有効エントリを探す。"""
        s = str(name or "").strip()
        for entry in self.entries.values():
            if entry.enabled and entry.ns and entry.info["has_main"]:
                if s in (entry.file, entry.stem):
                    return entry
        for entry in self.entries.values():  # 部分一致フォールバック
            if entry.enabled and entry.ns and entry.info["has_main"]:
                if s and s in entry.stem:
                    return entry
        return None

    def run_macro(self, name, context):
        """ライブラリ内マクロの main(context) を実行して結果を返す。"""
        entry = self.find_macro(name)
        if entry is None:
            return {"ok": False, "error": "unknown macro: {0}".format(name)}
        fn = entry.ns.get("main")
        if not callable(fn):
            return {"ok": False,
                    "error": "{0} has no callable main()".format(entry.file)}
        try:
            result = fn(context)
        except Exception:
            err = traceback.format_exc(limit=5)
            _log("macro {0} failed:\n{1}".format(entry.file, err))
            return {"ok": False, "error": err}
        return {"ok": True, "result": result, "file": entry.file}

    # ---------- ファイル管理 ----------

    def _resolve_new_path(self, name):
        """保存用のファイルパスを解決する(.py補完・dir内限定)。"""
        base = os.path.basename(str(name or "").strip())
        if not base:
            return None
        if not base.endswith(".py"):
            base += ".py"
        if base.startswith(("_", ".")):
            return None
        return os.path.join(self.dir, base)

    def read_file(self, name):
        path = self._resolve_new_path(name)
        if path is None or not os.path.isfile(path):
            return {"ok": False, "error": "file not found: {0}".format(name)}
        with open(path, encoding="utf-8") as f:
            return {"ok": True, "file": os.path.basename(path), "source": f.read()}

    def save_file(self, name, source):
        """構文検証してからライブラリdirへ保存する。"""
        path = self._resolve_new_path(name)
        if path is None:
            return {"ok": False, "error": "invalid file name: {0}".format(name)}
        info = analyze_source(source, path)
        if not info["ok"]:
            return {"ok": False, "error": info["error"], "analysis": info}
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
        except OSError as e:
            return {"ok": False, "error": "write failed: {0}".format(e)}
        return {"ok": True, "file": os.path.basename(path), "analysis": info}

    def delete_file(self, name):
        path = self._resolve_new_path(name)
        if path is None or not os.path.isfile(path):
            return {"ok": False, "error": "file not found: {0}".format(name)}
        try:
            os.remove(path)
        except OSError as e:
            return {"ok": False, "error": "delete failed: {0}".format(e)}
        return {"ok": True, "file": os.path.basename(path)}

    # ---------- upstream 更新 ----------

    def update_from_upstream(self):
        """sources.json のURLからファイルを再取得して上書きする。

        各URLをダウンロード→構文検証→書込。失敗したファイルは
        既存を維持したまま結果に報告する。reload は呼び出し側で行う。
        """
        import urllib.request
        import urllib.parse

        results = []
        for base in (self.dir, SEED_DIR):
            spath = os.path.join(base, SOURCES_FILE)
            if not os.path.isfile(spath):
                continue
            try:
                with open(spath, encoding="utf-8") as f:
                    sources = json.load(f)
            except (OSError, ValueError) as e:
                results.append({"source": spath, "ok": False,
                                "error": "bad sources.json: {0}".format(e)})
                continue
            for item in sources if isinstance(sources, list) else []:
                url = item.get("url")
                fname = os.path.basename(item.get("file") or "")
                if not url or not fname:
                    continue
                try:
                    if urllib.parse.urlparse(url).scheme.lower() not in ("http", "https"):
                        raise ValueError("unsupported URL scheme")
                    with urllib.request.urlopen(url, timeout=15) as r:  # nosec B310  # 直上でhttp/httpsスキームを検証済み
                        src = r.read().decode("utf-8")
                except Exception as e:
                    results.append({"file": fname, "ok": False,
                                    "error": "download failed: {0}".format(e)})
                    continue
                info = analyze_source(src, fname)
                if not info["ok"]:
                    results.append({"file": fname, "ok": False,
                                    "error": info["error"]})
                    continue
                dst = os.path.join(self.dir, fname)
                try:
                    with open(dst, "w", encoding="utf-8") as f:
                        f.write(src)
                except OSError as e:
                    results.append({"file": fname, "ok": False,
                                    "error": "write failed: {0}".format(e)})
                    continue
                results.append({"file": fname, "ok": True,
                                "types": info["types"]})
        return results

    # ---------- 記述 ----------

    def describe(self):
        return {
            "dir": self.dir,
            "seed_dir": SEED_DIR,
            "files": [e.describe() for e in self.entries.values()],
            "expression_functions": [
                f["register_name"]
                for e in self.entries.values()
                if e.enabled and e.ns
                for f in e.info["functions"]
            ],
            "wired_hooks": [
                {"file": e.file, "hooks": e.info["hooks"]}
                for e in self.entries.values()
                if e.enabled and e.ns and e.info["hooks"]
            ],
        }
