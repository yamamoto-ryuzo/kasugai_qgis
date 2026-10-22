# -*- coding: utf-8 -*-
"""geo_userfunc を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、qgis_live_driver の
bridge_call コマンド(ファイルJSONL / REST /api/cmd / MCP qgis_bridge_call)
から ``qgis.utils.plugins['geo_userfunc'].bridge.<method>(*args)`` が
プロセス内で直接呼ばれる。

各メソッドは JSON 文字列を返す(bridge_call 側で構造化される)。
ドメインエラー(関数不明・構文エラー等)は ``{"ok": false, "error": ...}``
を返し、予期しない例外は呼び出し元(driver の {"error": traceback})に委ねる。

AIからの主な利用ループ:
  listFunctions()        → 関数/フック/マクロの発見(署名・doc付き)
  evalExpression()       → 式関数の試行(例: zen2han('ＡＢＣ'))
  run()                  → マクロの実行
  saveFunction()         → 新規関数の作成(compile検証→保存)
  reload()               → 変更の反映(再スキャン+再登録)
  updateFromUpstream()   → sources.json のURLから最新版を取得
"""

import inspect
import json
import os

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeatureRequest,
    QgsProject,
    QgsVectorLayer,
)


class _DialogAutoReply:
    """exec中だけ QMessageBox の modal メソッドを自動応答に差し替える。

    geo_excel.bridge と同じパターン:
    - question → confirm=True なら Ok、False なら Cancel(中断)
    - information/critical/warning → メッセージを収集して即 Ok
    """

    _NAMES = ("information", "question", "warning", "critical")

    def __init__(self, confirm):
        self.confirm = bool(confirm)
        self.messages = []
        self._orig = {}

    def _capture(self, title, text):
        self.messages.append({"title": str(title), "text": str(text)})

    def __enter__(self):
        def _ok(*a):
            self._capture(a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else "")
            return QMessageBox.StandardButton.Ok

        def _question(*a):
            self._capture(a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else "")
            return (QMessageBox.StandardButton.Ok if self.confirm
                    else QMessageBox.StandardButton.Cancel)

        for name in self._NAMES:
            self._orig[name] = getattr(QMessageBox, name)
            setattr(QMessageBox, name,
                    staticmethod(_question if name == "question" else _ok))
        return self

    def __exit__(self, *exc):
        for name, fn in self._orig.items():
            setattr(QMessageBox, name, fn)
        return False


class GeoUserfuncBridge:
    """``plugins['geo_userfunc'].bridge`` にぶら下げるAI向けAPI。"""

    NAME = "ユーザー関数ライブラリ (geo_userfunc)"
    SUMMARY = ("ユーザー定義Pythonコードのライブラリ管理。"
               "@qgsfunction式関数の式エンジン登録、"
               "openProject/saveProject/closeProjectフックの信号配線、"
               "main(context)マクロのメニュー/bridge実行を行う。"
               "他プラグイン(geo_excel等)が登録したマクロも一元管理する。")
    WHEN_TO_USE = [
        "式で使えるユーザー関数(zen2han等)を登録・確認したい",
        "プロジェクトの開閉・保存時に動くフックを管理したい",
        "main(context) 形式のユーザーマクロを実行したい",
        "AIが新しいユーザー関数を作成してQGISへ即登録したい",
        "geo_excel等の他プラグインのマクロを一覧・実行したい",
        "upstreamリポジトリから関数定義を更新したい",
    ]
    METHOD_DOCS = {
        "listFunctions": {
            "description":
                "ライブラリ内ファイルの一覧(型/関数/フック/有効状態/エラー)と"
                "登録済み式関数名を返す。",
            "example": {"method": "listFunctions", "args": []},
        },
        "listMacros": {
            "description":
                "実行可能なマクロ一覧。ライブラリ内 main() 持ちファイルと"
                "他プラグインが共有レジストリに登録したものを含む。",
            "example": {"method": "listMacros", "args": []},
        },
        "run": {
            "description":
                "マクロを実行する。nameは macro_id / ファイル名 / stem。"
                "context に layer_id/feature_id/args を渡せる。"
                "confirm=True で確認ダイアログにOk応答(既定False=中断)。"
                "実行中はGUIスレッドをブロックする。",
            "example": {"method": "run",
                        "args": ["geo_excel.exportSingle", None, 1]},
        },
        "evalExpression": {
            "description":
                "式を評価して結果を返す。式関数(zen2han等)の確認用。"
                "layer_id/feature_id でスコープと地物を指定可能。",
            "example": {"method": "evalExpression",
                        "args": ["zen2han('ＡＢＣ１２３')"]},
        },
        "readFunction": {
            "description": "ライブラリ内ファイルのソースを返す。",
            "example": {"method": "readFunction", "args": ["user_functions.py"]},
        },
        "saveFunction": {
            "description":
                "ファイルをライブラリへ保存する。保存前に構文検証し、"
                "失敗時は書き込まずエラーを返す。反映にはreload()が必要。",
            "example": {"method": "saveFunction",
                        "args": ["my_func.py",
                                 "from qgis.core import *\n"
                                 "@qgsfunction(args='auto', group='ユーザー関数')\n"
                                 "def f(v, feature, parent):\n    return v"]},
        },
        "deleteFunction": {
            "description": "ライブラリ内ファイルを削除する。",
            "example": {"method": "deleteFunction", "args": ["my_func.py"]},
        },
        "setEnabled": {
            "description":
                "ファイルの有効/無効を切り替える(manifest永続化)。"
                "反映にはreload()が必要。",
            "example": {"method": "setEnabled", "args": ["user_functions.py", True]},
        },
        "reload": {
            "description":
                "ライブラリを再スキャンして全再登録する(式関数の差し替え・"
                "フック再配線)。変更後の状態を返す。",
            "example": {"method": "reload", "args": []},
        },
        "updateFromUpstream": {
            "description":
                "sources.json に定義されたURLからファイルを再取得して上書きする。"
                "構文検証を通ったものだけ保存し、最後にreloadする。",
            "example": {"method": "updateFromUpstream", "args": []},
        },
        "status": {
            "description":
                "ライブラリdir・ファイル数・登録済み式関数・配線済みフック・"
                "共有レジストリの登録数を返す。",
            "example": {"method": "status", "args": []},
        },
        "openManager": {
            "description": "管理ダイアログを開く。",
            "example": {"method": "openManager", "args": []},
        },
    }

    def __init__(self, plugin):
        self._plugin = plugin

    # ---------- 内部ヘルパ ----------

    @staticmethod
    def _ok(payload=None):
        obj = {"ok": True}
        if payload:
            obj.update(payload)
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def _err(msg):
        return json.dumps({"ok": False, "error": str(msg)},
                          ensure_ascii=False)

    def _method_catalog(self):
        """公開メソッドの仕様一覧(signature+docstring+METHOD_DOCS)。"""
        out = []
        for name in sorted(dir(self)):
            if name.startswith("_") or name == "pluginInfo":
                continue
            fn = getattr(self, name)
            if not callable(fn):
                continue
            doc = inspect.getdoc(fn) or ""
            entry = {
                "name": name,
                "signature": "{0}{1}".format(name, inspect.signature(fn)),
                "description": doc.split("\n")[0] if doc else "",
            }
            extra = self.METHOD_DOCS.get(name) or {}
            if extra.get("description"):
                entry["description"] = extra["description"]
            if extra.get("example"):
                entry["example"] = extra["example"]
            out.append(entry)
        return out

    # ---------- bridge メソッド(JSON文字列を返す) ----------

    def pluginInfo(self):
        """プラグインの自己記述(id/summary/when_to_use/methods)を返す。"""
        lib = self._plugin.library
        return self._ok({
            "id": "geo_userfunc",
            "name": self.NAME,
            "summary": self.SUMMARY,
            "when_to_use": list(self.WHEN_TO_USE),
            "invoke": {"type": "bridge_call", "plugin_id": "geo_userfunc",
                       "method": "<method>", "args": []},
            "methods": self._method_catalog(),
            "state": {
                "libraryDir": lib.dir,
                "fileCount": len(lib.entries),
                "registryCount": len(self._plugin.registry.entries()),
            },
        })

    def status(self):
        """ライブラリの実行時状態を返す。"""
        d = self._plugin.library.describe()
        return self._ok({
            "dir": d["dir"],
            "fileCount": len(d["files"]),
            "enabledCount": sum(1 for f in d["files"] if f["enabled"]),
            "expressionFunctions": d["expression_functions"],
            "wiredHooks": d["wired_hooks"],
            "registryMacros": self._plugin.registry.describe(),
        })

    def listFunctions(self):
        """ライブラリ内ファイルの一覧と登録済み式関数を返す。"""
        return self._ok(self._plugin.library.describe())

    def listMacros(self):
        """実行可能マクロ一覧(ライブラリ内+登録済み)を返す。"""
        local = []
        for e in self._plugin.library.entries.values():
            if e.enabled and e.info and e.info.get("has_main"):
                local.append({
                    "id": e.stem,
                    "file": e.file,
                    "source": "library",
                    "title": e.info.get("macro_doc") or e.stem,
                    "signature": e.info.get("macro_signature", "main(context)"),
                })
        registered = []
        for m in self._plugin.registry.describe():
            m = dict(m)
            m["source"] = m.get("plugin_id") or "plugin"
            registered.append(m)
        return self._ok({"library": local, "registered": registered})

    def run(self, name, layer_id=None, feature_id=None, args=None, confirm=False):
        """マクロを実行する。共有レジストリ優先、次にライブラリ内。"""
        context = self._plugin.library.make_context(layer_id, feature_id, args)
        with _DialogAutoReply(confirm) as dlg:
            reg = self._plugin.registry
            if reg.get(name) is not None:
                result = reg.run(name, context)
            else:
                result = self._plugin.library.run_macro(name, context)
        if isinstance(result, dict):
            result["messages"] = dlg.messages
            result.setdefault("ok", True)
            if result.get("ok"):
                return self._ok(result)
            return self._err(result.get("error", "macro failed"))
        return self._ok({"result": result, "messages": dlg.messages})

    def evalExpression(self, expression, layer_id=None, feature_id=None):
        """式を評価して結果を返す。式関数の動作確認用。"""
        ctx = QgsExpressionContext()
        ctx.appendScope(QgsExpressionContextUtils.globalScope())
        ctx.appendScope(
            QgsExpressionContextUtils.projectScope(QgsProject.instance()))
        layer = None
        if layer_id:
            layer = QgsProject.instance().mapLayer(str(layer_id))
        if layer is None:
            layer = self._plugin.iface.activeLayer()
        if isinstance(layer, QgsVectorLayer):
            ctx.appendScope(QgsExpressionContextUtils.layerScope(layer))
            if feature_id is not None:
                feat = layer.getFeature(QgsFeatureRequest(int(feature_id)))
                if feat.isValid():
                    ctx.setFeature(feat)
                else:
                    return self._err(
                        "feature {0} not found in layer {1}".format(
                            feature_id, layer.name()))
        expr = QgsExpression(str(expression))
        expr.prepare(ctx)
        if expr.hasParserError():
            return self._err("parser error: {0}".format(expr.parserErrorString()))
        value = expr.evaluate(ctx)
        if expr.hasEvalError():
            return self._err("eval error: {0}".format(expr.evalErrorString()))
        if not isinstance(value, (str, int, float, bool, type(None))):
            value = str(value)
        return self._ok({"value": value, "expression": str(expression)})

    def readFunction(self, name):
        """ライブラリ内ファイルのソースを返す。"""
        r = self._plugin.library.read_file(name)
        return self._ok(r) if r.get("ok") else self._err(r.get("error"))

    def saveFunction(self, name, source):
        """構文検証してからライブラリへ保存する。反映はreload()。"""
        r = self._plugin.library.save_file(name, source)
        if not r.get("ok"):
            return self._err(r.get("error"))
        return self._ok({"file": r["file"], "analysis": r["analysis"]})

    def deleteFunction(self, name):
        """ライブラリ内ファイルを削除する。反映はreload()。"""
        r = self._plugin.library.delete_file(name)
        if not r.get("ok"):
            return self._err(r.get("error"))
        self.reload()
        return self._ok({"file": r["file"], "reloaded": True})

    def setEnabled(self, name, enabled=True):
        """ファイルの有効/無効をmanifestへ保存してreloadする。"""
        lib = self._plugin.library
        file_name = os.path.basename(str(name))
        if file_name not in lib.entries:
            return self._err("unknown file: {0}".format(name))
        lib.set_enabled(file_name, enabled)
        d = lib.reload()
        return self._ok({"file": file_name, "enabled": bool(enabled),
                         "files": d["files"]})

    def reload(self):
        """ライブラリを再スキャンして全再登録する。"""
        d = self._plugin.library.reload()
        return self._ok({"files": d["files"],
                         "expressionFunctions": d["expression_functions"],
                         "wiredHooks": d["wired_hooks"]})

    def updateFromUpstream(self):
        """sources.json のURLからファイルを再取得してreloadする。"""
        results = self._plugin.library.update_from_upstream()
        if not results:
            return self._err("no sources.json found")
        d = self._plugin.library.reload()
        return self._ok({"results": results, "files": d["files"]})

    def openManager(self):
        """管理ダイアログを開く。"""
        dlg = self._plugin.open_manager()
        return self._ok({"opened": dlg is not None})
