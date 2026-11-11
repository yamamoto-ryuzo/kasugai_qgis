# -*- coding: utf-8 -*-
"""geo_excel の既定設定(QSettings)・環境チェック・テンプレート自動生成。

「すぐに動く」ためのデフォルト:
  - 出力先: <ドキュメント>/geo_excel (QStandardPaths.DocumentsLocation。
    個人環境に依存しない汎用パス。QSettings で変更可)
  - テンプレート: 未指定なら <出力先>/templates/ へアクティブレイヤの
    フィールドから最小限の ##Attach:: / ##ListInsert:: 雛形xlsxを自動生成
  - dpi: 未指定時はスクリプト側既定(200)。QSettings で上書き可
  - 自動適用: geo_excel/auto_apply (既定 True)。実行時に不足している
    レイヤ変数(xlsout_*)を既定値で補う

このモジュールは plugin.py(実行前の自動適用)・settings_dialog.py(UI)・
bridge.py(AI向けAPI)の3箇所から共有される。
"""

import os
import re
import zipfile
from xml.sax.saxutils import escape

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QStandardPaths
from qgis.core import QgsExpressionContextUtils


# ---- QSettings キー ---------------------------------------------------------
KEY_OUTPUT_DIR = "geo_excel/output_dir"
KEY_DPI = "geo_excel/dpi"
KEY_TEMPLATE_LIST = "geo_excel/template_list"
KEY_TEMPLATE_SINGLE = "geo_excel/template_single"
KEY_AUTO_APPLY = "geo_excel/auto_apply"

# 帳票スクリプトごとの必須/任意レイヤ変数と帳票種別
SCRIPT_VARS = {
    "exportList.py": {
        "required": ["xlsout_list_template_path",
                     "xlsout_list_output_path_fixed",
                     "xlsout_list_output_path_variable"],
        "optional": [],
        "kind": "list",
    },
    "exportSingle.py": {
        "required": ["xlsout_template_path",
                     "xlsout_output_path_fixed",
                     "xlsout_output_path_variable"],
        "optional": ["dpi"],
        "kind": "single",
    },
    "exportSingleBulk.py": {
        "required": ["xlsout_template_path",
                     "xlsout_output_path_fixed",
                     "xlsout_output_path_variable"],
        "optional": ["dpi"],
        "kind": "single",
    },
}

# 全スクリプトで使われる既知レイヤ変数(UI一覧用)
KNOWN_VARIABLES = sorted({
    v for spec in SCRIPT_VARS.values() for v in spec["required"]
} | {"dpi"})

_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# ---- 設定値 ------------------------------------------------------------------
def documents_dir():
    """OSのドキュメントフォルダを返す(取得不可なら ~/Documents)。"""
    path = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation)
    if not path:
        path = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.normpath(path)


def setting(key, default=""):
    value = QSettings().value(key, None)
    return default if value is None else str(value)


def set_setting(key, value):
    """空文字/Noneはキー自体を削除(=デフォルトに戻す)。"""
    s = QSettings()
    if value is None or str(value) == "":
        s.remove(key)
    else:
        s.setValue(key, value)


def output_dir():
    """帳票の既定出力先。既定は <ドキュメント>/geo_excel。"""
    configured = setting(KEY_OUTPUT_DIR)
    if configured:
        return os.path.normpath(configured)
    return os.path.join(documents_dir(), "geo_excel")


def auto_apply_enabled():
    return setting(KEY_AUTO_APPLY, "1").lower() in ("1", "true", "yes", "on")


def current_settings():
    """UI/bridge表示用の現在の既定値セット。"""
    return {
        "output_dir": output_dir(),
        "output_dir_configured": bool(setting(KEY_OUTPUT_DIR)),
        "dpi": setting(KEY_DPI),
        "template_list": setting(KEY_TEMPLATE_LIST),
        "template_single": setting(KEY_TEMPLATE_SINGLE),
        "auto_apply": auto_apply_enabled(),
    }


def save_settings(output_dir_value=None, dpi=None, template_list=None,
                  template_single=None, auto_apply=None):
    """UIからまとめて保存。Noneの項目は変更しない。"""
    if output_dir_value is not None:
        set_setting(KEY_OUTPUT_DIR, output_dir_value.strip())
    if dpi is not None:
        set_setting(KEY_DPI, dpi.strip())
    if template_list is not None:
        set_setting(KEY_TEMPLATE_LIST, template_list.strip())
    if template_single is not None:
        set_setting(KEY_TEMPLATE_SINGLE, template_single.strip())
    if auto_apply is not None:
        set_setting(KEY_AUTO_APPLY, "1" if auto_apply else "0")


# ---- 環境チェック ------------------------------------------------------------
def win32com_available():
    try:
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False


def excel_registered():
    """ExcelのCOM登録(HKCR\\Excel.Application)の有無をレジストリで確認。

    Excelを起動しない軽量チェック。実起動確認は check_excel_launch()。
    """
    try:
        import winreg
    except ImportError:
        return False
    for subkey in (r"Excel.Application\CurVer", r"Excel.Application"):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, subkey):
                return True
        except OSError:  # nosec B112  # 設計上の許容
            continue
    return False


def check_excel_launch():
    """Excelを実際にCOM起動して検証する(既存インスタンスがあれば再利用しQuitしない)。"""
    try:
        import win32com.client
    except Exception as e:
        return {"ok": False, "error": f"win32com: {e}"}
    try:
        try:
            app = win32com.client.GetObject(Class="Excel.Application")
            return {"ok": True, "version": str(app.Version), "launched": False}
        except Exception:
            app = win32com.client.Dispatch("Excel.Application")
            version = str(app.Version)
            try:
                app.DisplayAlerts = False
                app.Quit()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            return {"ok": True, "version": version, "launched": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def environment_report():
    """設定UI/bridge用の環境サマリ。"""
    return {
        "win32com": win32com_available(),
        "excel_registered": excel_registered(),
        "documents_dir": documents_dir(),
        "output_dir": output_dir(),
        "output_dir_exists": os.path.isdir(output_dir()),
        "auto_apply": auto_apply_enabled(),
    }


def requirements():
    """実行に必要なものの列挙(UIの案内文とbridgeの情報用)。"""
    return [
        QCoreApplication.translate("geo_excel", "Windows Excel (automated via win32com/pywin32 COM)"),
        QCoreApplication.translate("geo_excel", "pywin32 (win32com.client) importable from the QGIS Python"),
        QCoreApplication.translate("geo_excel", "A vector layer (list/bulk: active layer; single: also needs a selected feature)"),
        QCoreApplication.translate("geo_excel", "An Excel template containing placeholders: ##Attach::<field>, "
                                   "##ListInsert::<field>, ##AttachFitImage::<theme>::<scale> "
                                   "(auto-generated when not configured)"),
        QCoreApplication.translate("geo_excel", "Layer variables xlsout_* (set here or in Layer Properties > Variables)"),
        QCoreApplication.translate("geo_excel", "A map theme in the project, when using ##AttachFitImage::"),
    ]


def script_variable_spec():
    """帳票スクリプトごとの必須/任意レイヤ変数定義を返す。"""
    return {f: {"required": list(s["required"]),
                "optional": list(s["optional"]),
                "kind": s["kind"]}
            for f, s in SCRIPT_VARS.items()}


# ---- 既定値の生成 ------------------------------------------------------------
def _safe_name(text):
    """ファイル名に使えない文字を _ に置換する。"""
    name = _BAD_FILENAME_CHARS.sub("_", str(text or "")).strip(" .")
    return name or "report"


def _expr_string_literal(text):
    """QGIS式の文字列リテラルに埋め込めるようシングルクォートを退避。"""
    return str(text).replace("'", "''")


def generated_template_path(kind, layer):
    """自動生成テンプレートのパス: <出力先>/templates/<レイヤ名>_<種別>.xlsx"""
    base = _safe_name(layer.name()) if layer is not None else "layer"
    return os.path.join(output_dir(), "templates",
                        f"{base}_{kind}_template.xlsx")


def configured_template(kind):
    """QSettingsのテンプレート指定(未設定なら空文字)。"""
    return setting(KEY_TEMPLATE_LIST if kind == "list" else KEY_TEMPLATE_SINGLE)


def _default_variables(layer, kind, errors):
    """スクリプト種別ごとの既定レイヤ変数値を組み立てる。"""
    out_dir = output_dir()
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        errors.append(f"{out_dir}: {e}")

    template = configured_template(kind)
    if not template:
        template = generated_template_path(kind, layer)
        if not os.path.exists(template):
            try:
                generate_template(template, layer, kind)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{template}: {e}")

    base = _safe_name(layer.name())
    if kind == "list":
        variables = {
            "xlsout_list_template_path": template,
            "xlsout_list_output_path_fixed": out_dir,
            "xlsout_list_output_path_variable": f"{base}_list.xlsx",
        }
    else:
        variables = {
            "xlsout_template_path": template,
            "xlsout_output_path_fixed": out_dir,
            "xlsout_output_path_variable":
                f"concat('{_expr_string_literal(base)}_', $id, '.xlsx')",
        }
    dpi = setting(KEY_DPI)
    if dpi:
        variables["dpi"] = dpi
    return variables


def ensure_layer_variables(layer, script_file):
    """不足している必須レイヤ変数へ既定値を適用する。

    Parameters
      layer -- 対象ベクターレイヤ
      script_file -- "exportList.py" 等のファイル名

    Returns
      {"applied": {name: value}, "errors": [msg]}。既設定の変数は触らない。
    """
    spec = SCRIPT_VARS.get(script_file)
    if spec is None:
        return {"applied": {}, "errors": [f"unknown script: {script_file}"]}

    scope = QgsExpressionContextUtils.layerScope(layer)
    existing = set(scope.variableNames()) if scope is not None else set()

    errors = []
    defaults = _default_variables(layer, spec["kind"], errors)
    applied = {}
    for name in spec["required"] + spec["optional"]:
        current = scope.variable(name) if name in existing else None
        value = defaults.get(name)
        if current in (None, ""):
            if value:
                QgsExpressionContextUtils.setLayerVariable(layer, name, value)
                applied[name] = value
            elif name in spec["required"]:
                errors.append(name)
    return {"applied": applied, "errors": errors}


# ---- 最小xlsxテンプレート生成 -------------------------------------------------
def _col_letter(n):
    """1始まりの列番号をA,B,...,AA等に変換する。"""
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def write_xlsx(path, rows, sheet_name="Sheet1"):
    """最小構成のxlsxを生成する(inlineStrセルのみ)。

    rows -- セル値(文字列)の二次元リスト。
    スクリプトが ws.Cells.Find(LookIn=xlValues) で検索できるよう
    プレースホルダはセル値として埋め込む。
    """
    row_xml = []
    for r, row in enumerate(rows, 1):
        cells = "".join(
            f'<c r="{_col_letter(c)}{r}" t="inlineStr">'
            f'<is><t>{escape(str(v))}</t></is></c>'
            for c, v in enumerate(row, 1))
        row_xml.append(f'<row r="{r}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>')

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types">'
        '<Default Extension="rels" ContentType="application/vnd.'
        'openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>')
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
        '2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" '
        'r:id="rId1"/></sheets></workbook>')
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>')

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


def generate_template(path, layer, kind):
    """レイヤのフィールドから最小限の帳票テンプレートxlsxを生成する。

    kind -- "list"(##ListInsert::) or "single"(##Attach::)
    """
    fields = ([f.name() for f in layer.fields()]
              if layer is not None else []) or ["id"]
    if kind == "list":
        rows = [fields, [f"##ListInsert::{n}" for n in fields]]
    else:
        rows = ([[QCoreApplication.translate("geo_excel", "Field"), QCoreApplication.translate("geo_excel", "Value")]]
                + [[n, f"##Attach::{n}"] for n in fields])
    return write_xlsx(path, rows)
