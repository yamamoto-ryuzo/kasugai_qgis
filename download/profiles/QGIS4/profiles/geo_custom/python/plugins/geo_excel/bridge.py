# -*- coding: utf-8 -*-
"""geo_excel を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、geo_driver の
bridge_call コマンド(ファイルJSONL / REST /api/cmd / MCP qgis_bridge_call)
から ``qgis.utils.plugins['geo_excel'].bridge.<method>(*args)`` が
プロセス内で直接呼ばれる。

各メソッドは JSON 文字列を返す(bridge_call 側で構造化される)。
ドメインエラー(スクリプト不明・前提未充足等)は ``{"ok": false, "error": ...}``
を返し、予期しない例外は呼び出し元(driver の {"error": traceback})に委ねる。

run() は GUI スレッドで同期的に実行され、Excel起動・帳票生成の時間分だけ
ブロックする(メニュー実行と同じ性質)。スクリプト内の modal QMessageBox
(上書き確認/続行確認/完了通知)は実行中だけ自動応答に差し替える:
confirm=False なら確認系は Cancel(=中断)として安全側に倒す。
また iface.messageBar().pushCritical の呼出は実行中だけ収集して
messages として返す(メッセージバー自体にも表示される)。

例(MCP): qgis_bridge_call pluginId="geo_excel" method="run" args=["list"]
"""

import inspect
import json
import os
import re
import zipfile
from xml.sax.saxutils import unescape

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (QgsExpression, QgsExpressionContext,
                       QgsExpressionContextUtils, QgsProject, QgsVectorLayer)

from . import settings as _settings

# レイヤ変数の既知キー(scripts側の定義と対応)
_SCRIPT_DEFS = [
    {
        "id": "list",
        "file": "exportList.py",
        "title": "一覧帳票を出力 (アクティブレイヤ)",
        "needs_selection": False,
        "vars": ["xlsout_list_template_path", "xlsout_list_output_path_fixed",
                 "xlsout_list_output_path_variable"],
        "description": "アクティブレイヤ全地物を一覧帳票として出力する",
    },
    {
        "id": "single",
        "file": "exportSingle.py",
        "title": "単票を出力 (選択地物)",
        "needs_selection": True,
        "vars": ["xlsout_template_path", "xlsout_output_path_fixed",
                 "xlsout_output_path_variable", "dpi(任意,既定200)"],
        "description": "選択地物ごとに単票を出力する",
    },
    {
        "id": "bulk",
        "file": "exportSingleBulk.py",
        "title": "単票を一括出力 (選択地物または全地物)",
        "needs_selection": False,
        "vars": ["xlsout_template_path", "xlsout_output_path_fixed",
                 "xlsout_output_path_variable", "dpi(任意,既定200)"],
        "description": "選択地物(2件以上)または全地物の単票を一括出力する",
    },
]


class _DialogAutoReply:
    """exec中だけ QMessageBox の modal メソッドを自動応答に差し替える。

    - question → confirm=True なら Ok(上書き/続行)、False なら Cancel(中断)
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
            return QMessageBox.StandardButton.Ok if self.confirm else QMessageBox.StandardButton.Cancel

        for name in self._NAMES:
            self._orig[name] = getattr(QMessageBox, name)
            setattr(QMessageBox, name,
                    staticmethod(_question if name == "question" else _ok))
        return self

    def __exit__(self, *exc):
        for name, fn in self._orig.items():
            setattr(QMessageBox, name, fn)
        return False


class GeoExcelBridge:
    """``plugins['geo_excel'].bridge`` にぶら下げるAI向けAPI。"""

    NAME = "Excel帳票出力 (geo_excel)"
    SUMMARY = ("ベクターレイヤの属性情報をExcel帳票として出力する。"
               "アクティブレイヤのレイヤ変数(xlsout_*)でテンプレートと"
               "出力先を指定し、一覧帳票・単票・単票一括の3種を実行できる。"
               "実行には win32com(pywin32) と Excel が必要。")
    WHEN_TO_USE = [
        "アクティブレイヤの全地物をExcel一覧帳票に出力したい",
        "選択した地物の属性をExcel単票テンプレートへ差し込み出力したい",
        "選択地物または全地物の単票を一括出力したい",
        "帳票出力用レイヤ変数(xlsout_*)の設定状況を確認・変更したい",
        "帳票出力に必要な既定値(出力先・テンプレート)を自動設定したい",
        "帳票出力前にテンプレート・出力先・選択地物の前提を検証したい",
        "テンプレートのプレースホルダがどのフィールドに対応するか確認したい",
    ]
    METHOD_DOCS = {
        "run": {
            "description":
                "帳票スクリプトを実行する。scriptは list|single|bulk|"
                "ファイル名|index。singleは選択地物または feature_id 指定。"
                "confirm=True で上書き/続行確認にOk応答(既定False=中断)。"
                "Excel起動・生成中はGUIスレッドをブロックする。",
            "example": {"method": "run", "args": ["list", None, True]},
        },
        "status": {
            "description":
                "アクティブレイヤ・選択地物数・win32com利用可否・"
                "レイヤ変数設定状況を返す。",
            "example": {"method": "status", "args": []},
        },
        "listScripts": {
            "description":
                "実行可能な帳票スクリプト一覧(id/ファイル/要選択/"
                "必要レイヤ変数)を返す。",
            "example": {"method": "listScripts", "args": []},
        },
        "layerVariables": {
            "description":
                "対象レイヤ(既定=アクティブ)の xlsout_*/dpi レイヤ変数を返す。",
            "example": {"method": "layerVariables", "args": []},
        },
        "setLayerVariables": {
            "description":
                "対象レイヤ(既定=アクティブ)にレイヤ変数を設定する。"
                "{変数名: 値}。値Noneで削除。",
            "example": {"method": "setLayerVariables",
                        "args": [{"xlsout_output_path_fixed": "C:/out"}]},
        },
        "settings": {
            "description":
                "既定設定(出力先=ドキュメント/geo_excel等・QSettings)と"
                "環境チェック(win32com/Excel登録/出力先)・必要物の列挙を返す。",
            "example": {"method": "settings", "args": []},
        },
        "applyDefaults": {
            "description":
                "対象レイヤ(既定=アクティブ)の不足レイヤ変数へ既定値を適用する。"
                "script省略で全スクリプト分。出力先フォルダの作成と"
                "テンプレート自動生成も行う。",
            "example": {"method": "applyDefaults", "args": []},
        },
        "checkExcel": {
            "description":
                "Excelを実際にCOM起動して検証する(数秒ブロック)。"
                "既存ExcelインスタンスがあればQuitしない。",
            "example": {"method": "checkExcel", "args": []},
        },
        "openSettings": {
            "description": "設定ダイアログを開く。",
            "example": {"method": "openSettings", "args": []},
        },
        "setSettings": {
            "description":
                "既定設定を保存する。対応キー: output_dir/dpi/"
                "template_list/template_single/auto_apply。",
            "example": {"method": "setSettings",
                        "args": [{"output_dir": "C:/out", "dpi": "300"}]},
        },
        "validateRun": {
            "description":
                "帳票スクリプトを実行せず前提条件を検証する。レイヤ変数の"
                "充足・テンプレート実在・出力先・dpi・選択地物をchecks/"
                "errors/warningsとして構造化して返し、テンプレートの"
                "プレースホルダとフィールドの対応表(field_mapping)も含む。"
                "ready=True の時のみ run() が成功する見込み。",
            "example": {"method": "validateRun", "args": ["single"]},
        },
        "fieldMapping": {
            "description":
                "テンプレート内の ##Attach::/##ListInsert::/"
                "##AttachFitImage:: プレースホルダとレイヤフィールドの"
                "対応表を返す。未解決プレースホルダは unresolved に列挙。",
            "example": {"method": "fieldMapping", "args": ["single"]},
        },
        "regenerateTemplates": {
            "description":
                "対象レイヤ(既定=アクティブ)の自動生成テンプレートを"
                "再生成する(ユーザー指定テンプレートは上書きしない)。"
                "生成後に不足変数へ既定値を適用する。",
            "example": {"method": "regenerateTemplates", "args": []},
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

    def _layer(self, layer_id=None):
        """対象レイヤを解決する。layer_id省略時はアクティブレイヤ。"""
        if layer_id:
            layer = QgsProject.instance().mapLayer(str(layer_id))
        else:
            layer = self._plugin.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            return None
        return layer

    @staticmethod
    def _script_entry(script):
        """script指定(id/ファイル名/index)をスクリプト定義に解決する。"""
        if isinstance(script, bool):
            return None
        if isinstance(script, int):
            return (_SCRIPT_DEFS[script]
                    if -len(_SCRIPT_DEFS) <= script < len(_SCRIPT_DEFS)
                    else None)
        s = str(script or "").strip().lower()
        for d in _SCRIPT_DEFS:
            if s in (d["id"], d["file"].lower()):
                return d
        for d in _SCRIPT_DEFS:  # 部分一致フォールバック
            if s and (s in d["file"].lower() or s in d["id"]):
                return d
        return None

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
                "signature": f"{name}{inspect.signature(fn)}",
                "description": doc.split("\n")[0] if doc else "",
            }
            extra = self.METHOD_DOCS.get(name) or {}
            if extra.get("description"):
                entry["description"] = extra["description"]
            if extra.get("example"):
                entry["example"] = extra["example"]
            out.append(entry)
        return out

    def _variables(self, layer):
        scope = QgsExpressionContextUtils.layerScope(layer)
        names = set(scope.variableNames()) if scope is not None else set()
        known = {"dpi"}
        for d in _SCRIPT_DEFS:
            known.update(v for v in d["vars"] if "(" not in v)
        targets = sorted(n for n in names
                         if n.startswith("xlsout") or n == "dpi")
        # 未定義の既知キーも None で出して設定漏れを見やすくする
        out = {}
        for n in sorted(known | set(targets)):
            out[n] = scope.variable(n) if n in names else None
        return out

    # ---------- bridge メソッド(JSON文字列を返す) ----------

    def pluginInfo(self):
        """プラグインの自己記述(id/summary/when_to_use/methods)を返す。"""
        return self._ok({
            "id": "geo_excel",
            "name": self.NAME,
            "summary": self.SUMMARY,
            "when_to_use": list(self.WHEN_TO_USE),
            "invoke": {"type": "bridge_call", "plugin_id": "geo_excel",
                       "method": "<method>", "args": []},
            "methods": self._method_catalog(),
            "state": {
                "scriptCount": len(_SCRIPT_DEFS),
                "win32com": self._win32com_available(),
            },
        })

    def status(self):
        """実行時状態(アクティブレイヤ・選択数・依存環境)を返す。"""
        layer = self._plugin.iface.activeLayer()
        info = {"active_layer": None, "selection": 0,
                "win32com": self._win32com_available()}
        if isinstance(layer, QgsVectorLayer):
            info["active_layer"] = {"id": layer.id(), "name": layer.name()}
            info["selection"] = layer.selectedFeatureCount()
            info["variables"] = self._variables(layer)
        return self._ok(info)

    def listScripts(self):
        """帳票スクリプト一覧を返す。"""
        return self._ok({"scripts": [dict(d, index=i)
                                     for i, d in enumerate(_SCRIPT_DEFS)]})

    def layerVariables(self, layer_id=None):
        """対象レイヤの xlsout_*/dpi レイヤ変数を返す。"""
        layer = self._layer(layer_id)
        if layer is None:
            return self._err("vector layer not found or not active")
        return self._ok({"layer_id": layer.id(), "layer": layer.name(),
                         "variables": self._variables(layer)})

    def setLayerVariables(self, variables, layer_id=None):
        """レイヤ変数を設定する。{変数名: 値}、値Noneで削除。"""
        layer = self._layer(layer_id)
        if layer is None:
            return self._err("vector layer not found or not active")
        if not isinstance(variables, dict):
            return self._err("variables must be an object {name: value}")
        for k, v in variables.items():
            QgsExpressionContextUtils.setLayerVariable(layer, str(k), v)
        return self._ok({"layer_id": layer.id(), "layer": layer.name(),
                         "variables": self._variables(layer)})

    def run(self, script="list", feature_id=None, confirm=False):
        """帳票スクリプトを実行する(結果・メッセージを返す)。"""
        entry = self._script_entry(script)
        if entry is None:
            return self._err(
                f"unknown script: {script} "
                f"(use {[d['id'] for d in _SCRIPT_DEFS]})")
        layer = self._layer()
        if layer is None:
            return self._err("no active vector layer")
        if not self._win32com_available():
            return self._err("win32com (pywin32) is not available")

        if entry["needs_selection"]:
            if feature_id is not None:
                fids = [int(feature_id)]
            else:
                fids = list(layer.selectedFeatureIds())
            if not fids:
                return self._err(
                    "no feature_id and no selected features "
                    f"(layer {layer.name()})")
        else:
            fids = [None]

        results = []
        with _DialogAutoReply(confirm) as dlg:
            msgs = self._capture_messagebar(dlg.messages)
            try:
                for fid in fids:
                    r = self._plugin._exec_script(entry["file"],
                                                  layer.id(), fid)
                    ns = r.get("ns") or {}
                    results.append({
                        "fid": fid,
                        "ok": bool(r.get("ok")),
                        "error": r.get("error"),
                        "executed": bool(ns.get("excel_result")),
                        "output": (ns.get("output_path")
                                   or ns.get("output_path_fixed")),
                    })
            finally:
                msgs()
        return self._ok({
            "script": entry["id"],
            "layer": layer.name(),
            "layer_id": layer.id(),
            "results": results,
            "messages": dlg.messages,
        })

    # ---------- ドライラン検証・フィールドマッピング ----------

    _PLACEHOLDER_RE = re.compile(
        r"##(AttachFitImage|Attach|ListInsert)::([^<]+)")

    @staticmethod
    def _raw_variable(layer, name):
        """レイヤ変数の生値を返す(未定義なら None)。"""
        scope = QgsExpressionContextUtils.layerScope(layer)
        if scope is None or name not in set(scope.variableNames()):
            return None
        return scope.variable(name)

    @staticmethod
    def _expr_context(layer, feature):
        """帳票スクリプトの make_expression_context と同じ評価コンテキスト。"""
        ctx = QgsExpressionContext()
        ctx.appendScope(QgsExpressionContextUtils.globalScope())
        ctx.appendScope(QgsExpressionContextUtils.projectScope(
            QgsProject.instance()))
        ctx.appendScope(QgsExpressionContextUtils.layerScope(layer))
        if feature is not None:
            ctx.setFields(layer.fields())
            ctx.setFeature(feature)
        return ctx

    def _eval_variable(self, raw, layer, feature):
        """create_expression+evaluate と同規則でレイヤ変数値を評価する。

        式でない文字列(パス等)はそのまま返す。式の評価に失敗した
        場合は None を返す(スクリプト側では変数なし扱いで中断する)。
        """
        text = str(raw)
        exp = QgsExpression(text)
        if exp.hasParserError():
            return text
        if not (exp.referencedColumns() or exp.referencedFunctions()
                or exp.referencedVariables()):
            return text
        value = exp.evaluate(self._expr_context(layer, feature))
        if exp.hasEvalError() or value is None:
            return None
        return str(value)

    @staticmethod
    def _normalize_path(value):
        """帳票スクリプトと同じ規則でパスを正規化する(相対=プロジェクトdir)。"""
        p = str(value)
        if os.path.isabs(p):
            return p.replace("\\\\\\\\", "\\\\")
        base = os.path.dirname(str(QgsProject.instance().fileName()))
        return os.path.abspath(os.path.join(base, p))

    def _template_placeholders(self, template_path):
        """xlsx内の ##Attach::/##ListInsert::/##AttachFitImage:: を列挙する。"""
        found = {}
        with zipfile.ZipFile(str(template_path)) as z:
            for name in z.namelist():
                if (name != "xl/sharedStrings.xml"
                        and not name.startswith("xl/worksheets/")):
                    continue
                try:
                    text = z.read(name).decode("utf-8", "replace")
                except Exception:  # nosec B112  # 設計上の許容
                    continue
                for m in self._PLACEHOLDER_RE.finditer(text):
                    kind = m.group(1)
                    value = unescape(m.group(2)).strip()
                    key = (kind, value)
                    if key not in found:
                        found[key] = {"kind": kind, "value": value,
                                      "count": 0}
                    found[key]["count"] += 1
        return list(found.values())

    @staticmethod
    def _map_placeholder(ph, layer):
        """プレースホルダ1件をレイヤフィールド/式/マップテーマと照合する。"""
        kind, value = ph["kind"], ph["value"]
        if kind == "AttachFitImage":
            theme = value.split("::")[0].strip()
            ph["theme"] = theme
            themes = QgsProject.instance().mapThemeCollection().mapThemes()
            ph["resolved"] = theme in themes
            if not ph["resolved"]:
                ph["reason"] = f"map theme not found: {theme}"
            return ph
        expr = value.split("::")[0].strip()
        ph["field"] = expr
        if layer.fields().indexOf(expr) >= 0:
            ph["resolved"] = True
            ph["via"] = "field"
            return ph
        exp = QgsExpression(expr)
        if exp.hasParserError():
            ph["resolved"] = False
            ph["reason"] = f"invalid expression: {exp.parserErrorString()}"
            return ph
        missing = [c for c in exp.referencedColumns()
                   if layer.fields().indexOf(c) < 0]
        ph["via"] = "expression"
        if missing:
            ph["resolved"] = False
            ph["reason"] = f"unknown fields: {missing}"
        else:
            ph["resolved"] = True
        return ph

    def _field_mapping(self, layer, template_path):
        """テンプレートのプレースホルダ対応表を組み立てる。"""
        mapping = [self._map_placeholder(ph, layer)
                   for ph in self._template_placeholders(template_path)]
        unresolved = [p for p in mapping if not p.get("resolved")]
        return {"template": template_path,
                "layer_fields": [f.name() for f in layer.fields()],
                "placeholders": mapping,
                "unresolved": unresolved}

    def fieldMapping(self, script="single", layer_id=None):
        """テンプレートのプレースホルダとフィールドの対応表を返す。"""
        entry = self._script_entry(script)
        if entry is None:
            return self._err(
                f"unknown script: {script} "
                f"(use {[d['id'] for d in _SCRIPT_DEFS]})")
        layer = self._layer(layer_id)
        if layer is None:
            return self._err("vector layer not found or not active")
        spec = _settings.SCRIPT_VARS.get(entry["file"], {})
        tpl_var = (spec.get("required") or [None])[0]
        raw = self._raw_variable(layer, tpl_var) if tpl_var else None
        if not raw:
            return self._err(f"layer variable {tpl_var} is not set")
        sample = self._sample_feature(layer, None)
        evaluated = self._eval_variable(raw, layer, sample) or str(raw)
        path = self._normalize_path(evaluated)
        if not os.path.isfile(path):
            return self._err(f"template file not found: {path}")
        result = self._field_mapping(layer, path)
        result.update({"script": entry["id"], "layer": layer.name(),
                       "layer_id": layer.id(),
                       "template_variable": tpl_var})
        return self._ok(result)

    @staticmethod
    def _sample_feature(layer, feature_id):
        """評価用の代表地物を返す(feature_id→先頭選択→先頭地物)。"""
        if feature_id is not None:
            f = layer.getFeature(int(feature_id))
            return f if f.isValid() else None
        ids = sorted(layer.selectedFeatureIds())
        if ids:
            f = layer.getFeature(ids[0])
            return f if f.isValid() else None
        for f in layer.getFeatures():
            return f if f.isValid() else None
        return None

    def validateRun(self, script="list", layer_id=None, feature_id=None):
        """帳票スクリプトを実行せず前提条件を検証する(ドライラン)。"""
        entry = self._script_entry(script)
        if entry is None:
            return self._err(
                f"unknown script: {script} "
                f"(use {[d['id'] for d in _SCRIPT_DEFS]})")
        spec = _settings.SCRIPT_VARS.get(entry["file"], {})
        required = list(spec.get("required", []))
        optional = list(spec.get("optional", []))
        checks, errors, warnings = [], [], []

        def check(cid, ok, message=None, **extra):
            item = {"check": cid, "ok": bool(ok)}
            if message:
                item["message"] = str(message)
            item.update(extra)
            checks.append(item)
            return bool(ok)

        layer = self._layer(layer_id)
        check("active_layer", layer is not None,
              "no vector layer (not found or not active)"
              if layer is None else layer.name())
        if not check("win32com", self._win32com_available(),
                     "pywin32 (win32com) is required"):
            errors.append("win32com (pywin32) is not available")
        else:
            checks[-1].pop("message", None)
        if layer is None:
            errors.append("no target vector layer")
            return self._ok({"script": entry["id"], "ready": False,
                             "checks": checks, "errors": errors,
                             "warnings": warnings})

        selected = layer.selectedFeatureCount()
        sample = self._sample_feature(layer, feature_id)
        if feature_id is not None:
            check("feature_id", sample is not None,
                  f"feature_id={feature_id}", feature_id=feature_id)
            if sample is None:
                errors.append(
                    f"feature_id {feature_id} not found in {layer.name()}")
        if entry["needs_selection"]:
            if sample is None:
                check("selection", False,
                      "no feature_id and no selected features")
                errors.append(
                    "no feature selected (requires a selected feature "
                    "or feature_id)")
            else:
                check("selection", True, selected=selected)
        else:
            check("selection", True, selected=selected,
                  message=("all features are used"
                           if not selected else None))

        auto_apply = _settings.auto_apply_enabled()
        # 変数評価の地物コンテキストはスクリプト側の規則に合わせる
        # (single/bulk は地物上で評価、list はレイヤスコープのみ)
        eval_feature = sample if spec.get("kind") == "single" else None
        evaluated = {}
        for name in required + optional:
            raw = self._raw_variable(layer, name)
            if raw in (None, ""):
                if name in required:
                    if auto_apply:
                        warnings.append(
                            f"layer variable {name} is not set "
                            "(a default will be applied at run)")
                        check(f"variable:{name}", True, "not set; "
                              "auto_apply supplies a default",
                              variable=name)
                    else:
                        errors.append(f"layer variable {name} is not set")
                        check(f"variable:{name}", False, "not set",
                              variable=name)
                else:
                    check(f"variable:{name}", True, "not set (optional)",
                          variable=name)
                continue
            val = self._eval_variable(raw, layer, eval_feature)
            evaluated[name] = val
            if val in (None, ""):
                check(f"variable:{name}", False,
                      f"evaluates to empty: {raw}", variable=name,
                      value=str(raw))
                errors.append(
                    f"layer variable {name} evaluated empty: {raw}")
            else:
                check(f"variable:{name}", True, variable=name,
                      value=str(raw), evaluated=val)

        keys = required + [None, None, None]
        tpl_var, out_var, name_var = keys[0], keys[1], keys[2]
        template_path = None
        if tpl_var and evaluated.get(tpl_var):
            template_path = self._normalize_path(evaluated[tpl_var])
            if not check("template_exists",
                         os.path.isfile(template_path),
                         template_path, path=template_path):
                errors.append(f"template file not found: {template_path}")
        if out_var and evaluated.get(out_var):
            outdir = self._normalize_path(evaluated[out_var])
            ok_dir = os.path.isdir(outdir)
            if not check("output_dir", ok_dir,
                         None if ok_dir
                         else f"output folder does not exist: {outdir}",
                         path=outdir):
                errors.append(f"output folder does not exist: {outdir}")
            else:
                check("output_writable", os.access(outdir, os.W_OK),
                      path=outdir)
        if name_var and name_var in evaluated:
            check("output_name", bool(evaluated.get(name_var)),
                  str(evaluated.get(name_var) or "evaluates to empty"),
                  value=evaluated.get(name_var))

        if "dpi" in evaluated:
            dv = evaluated.get("dpi")
            if not check("dpi", bool(dv) and str(dv).isdecimal(),
                         f"must be a positive integer: {dv}"):
                errors.append(f"layer variable dpi is invalid: {dv}")
        else:
            check("dpi", True, "not set; default 200 is used", value=200)

        field_mapping = None
        if template_path and os.path.isfile(template_path):
            try:
                field_mapping = self._field_mapping(layer, template_path)
                for p in field_mapping["unresolved"]:
                    warnings.append(
                        f"placeholder {p['kind']}::{p['value']} is "
                        f"unresolved: {p.get('reason', 'no matching field')}")
            except Exception as e:  # noqa: BLE001
                warnings.append(f"could not inspect template: {e}")

        return self._ok({
            "script": entry["id"],
            "ready": not errors,
            "layer": {"id": layer.id(), "name": layer.name()},
            "selected": selected,
            "auto_apply": auto_apply,
            "checks": checks,
            "errors": errors,
            "warnings": warnings,
            "field_mapping": field_mapping,
        })

    # ---------- 既定設定・環境 ----------

    def settings(self):
        """既定設定・環境チェック・必要物の列挙を返す。"""
        info = {
            "environment": _settings.environment_report(),
            "defaults": _settings.current_settings(),
            "requirements": _settings.requirements(),
            "script_variables": _settings.script_variable_spec(),
        }
        layer = self._layer()
        if layer is not None:
            info["layer"] = {"id": layer.id(), "name": layer.name()}
            info["layer_variables"] = self._variables(layer)
        return self._ok(info)

    def applyDefaults(self, layer_id=None, script=None):
        """不足レイヤ変数へ既定値を適用する(script省略で全スクリプト)。"""
        layer = self._layer(layer_id)
        if layer is None:
            return self._err("vector layer not found or not active")
        if script is None:
            files = list(_settings.SCRIPT_VARS)
        else:
            entry = self._script_entry(script)
            if entry is None:
                return self._err(f"unknown script: {script}")
            files = [entry["file"]]
        applied, errors = {}, []
        for f in files:
            rep = _settings.ensure_layer_variables(layer, f)
            applied.update(rep["applied"])
            errors.extend(rep["errors"])
        return self._ok({"layer_id": layer.id(), "layer": layer.name(),
                         "applied": applied, "errors": errors,
                         "variables": self._variables(layer)})

    def checkExcel(self):
        """Excelを実際にCOM起動して検証する(数秒ブロックする)。"""
        rep = _settings.check_excel_launch()
        if rep.get("ok"):
            return self._ok(rep)
        return self._err(rep.get("error", "Excel launch check failed"))

    def openSettings(self):
        """設定ダイアログを開く。"""
        dlg = self._plugin.open_settings()
        return self._ok({"opened": dlg is not None})

    def setSettings(self, settings=None):
        """既定設定を保存する(output_dir/dpi/テンプレート/auto_apply)。"""
        settings = dict(settings or {})
        allowed = {"output_dir", "dpi", "template_list", "template_single",
                   "auto_apply"}
        unknown = [k for k in settings if k not in allowed]
        if unknown:
            return self._err(f"unknown keys: {unknown} "
                             f"(allowed: {sorted(allowed)})")
        applied = {}
        for k, v in settings.items():
            if k == "auto_apply":
                v = bool(v)
            elif v is not None:
                v = str(v)
            applied[k] = v
        _settings.save_settings(
            output_dir_value=applied.get("output_dir"),
            dpi=applied.get("dpi"),
            template_list=applied.get("template_list"),
            template_single=applied.get("template_single"),
            auto_apply=applied.get("auto_apply"))
        return self._ok({"applied": applied,
                         "settings": _settings.current_settings()})

    def regenerateTemplates(self, layer_id=None):
        """自動生成テンプレートを再生成し不足変数へ既定値を適用する。"""
        layer = self._layer(layer_id)
        if layer is None:
            return self._err("vector layer not found or not active")
        done, skipped, errors = [], [], []
        for kind in ("list", "single"):
            if _settings.configured_template(kind):
                skipped.append(kind)
                continue  # ユーザー指定テンプレートは上書きしない
            path = _settings.generated_template_path(kind, layer)
            try:
                _settings.generate_template(path, layer, kind)
                done.append(path)
            except Exception as e:
                errors.append({"kind": kind, "error": str(e)})
        applied, apply_errors = {}, []
        for f in list(_settings.SCRIPT_VARS):
            rep = _settings.ensure_layer_variables(layer, f)
            applied.update(rep["applied"])
            apply_errors.extend(rep["errors"])
        if errors:
            return self._err(
                f"template generation failed: {errors}")
        return self._ok({"generated": done, "skipped": skipped,
                         "applied": applied, "errors": apply_errors,
                         "variables": self._variables(layer)})

    # ---------- 実行環境 ----------

    @staticmethod
    def _win32com_available():
        try:
            import win32com.client  # noqa: F401
            return True
        except Exception:
            return False

    def _capture_messagebar(self, sink):
        """messageBar().pushCritical を収集に回す差し替えを試みる。

        戻り値は restore 関数。SIPオブジェクトへ属性設定できない環境では
        何もしない(no-op restore)。元のpushCriticalも呼ぶので
        ユーザー表示は維持される。
        """
        try:
            bar = self._plugin.iface.messageBar()
            orig = bar.pushCritical
        except Exception:
            return lambda: None

        def _push(title, text):
            sink.append({"level": "critical",
                         "title": str(title), "text": str(text)})
            try:
                orig(title, text)
            except Exception:  # nosec B110  # 設計上の許容
                pass

        try:
            bar.pushCritical = _push
        except Exception:
            return lambda: None

        def _restore():
            try:
                bar.pushCritical = orig
            except Exception:  # nosec B110  # 設計上の許容
                pass

        return _restore
