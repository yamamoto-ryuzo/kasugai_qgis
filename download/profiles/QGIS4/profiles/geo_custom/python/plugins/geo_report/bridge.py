# -*- coding: utf-8 -*-
"""geo_report を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、qgis_live_driver の
bridge_call コマンド(ファイルJSONL / REST /api/cmd / MCP qgis_bridge_call)
から ``qgis.utils.plugins['geo_report'].bridge.<method>(*args)`` が
プロセス内で直接呼ばれる。

各メソッドは JSON 文字列を返す(bridge_call 側で構造化される)。
ドメインエラー(レイアウト/アイテム不明・パネル未オープン等)は
``{"ok": false, "error": ...}`` を返し、予期しない例外は呼び出し元
(driver の {"error": traceback})に委ねる。いずれも GUI スレッドで
同期的に実行される。

save/loadLayoutProperties はプラグイン本来のファイルダイアログを通さず
パス指定で直接JSONを読み書きするため、modalでブロックしない。

例(MCP): qgis_bridge_call pluginId="geo_report" method="listLayouts"
"""

import inspect
import json
import os

from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject

_USER_ROLE = Qt.ItemDataRole.UserRole


class GeoReportBridge:
    """``plugins['geo_report'].bridge`` にぶら下げるAI向けAPI。"""

    NAME = "帳票レイアウト管理 (geo_report)"
    SUMMARY = ("プロジェクトの印刷レイアウトをドックパネルで管理する。"
               "レイアウト選択・印刷範囲の地図上表示(スケール/角度指定)・"
               "レイアウトアイテム(ラベル/地図/画像)のプロパティ参照・変更・"
               "プロパティのJSON保存/復元ができる。")
    WHEN_TO_USE = [
        "プロジェクトの印刷レイアウト一覧を確認したい",
        "レイアウトを選択して印刷範囲を地図キャンバスに表示したい",
        "レイアウトアイテム(テキスト/地図/画像)の位置・サイズ・表示を確認・変更したい",
        "レイアウトプロパティをJSONへ保存/復元したい",
        "レイアウトデザイナ(レイアウトマネージャ)を開きたい",
        "レイアウトを削除・名前変更・複製したい(QGISレイアウトマネージャ)",
    ]
    METHOD_DOCS = {
        "openPanel": {
            "description":
                "レイアウト選択ドックパネルを開く(plugin.run()相当)。"
                "レイアウトが無ければ composer/*.qpt をプロジェクトへ登録する。",
            "example": {"method": "openPanel", "args": []},
        },
        "closePanel": {
            "description": "ドックパネルを閉じる(印刷範囲表示も解除される)。",
            "example": {"method": "closePanel", "args": []},
        },
        "listLayouts": {
            "description":
                "プロジェクトの印刷レイアウト一覧(index/名前/ページ数/"
                "地図アイテム数/選択中)を返す。",
            "example": {"method": "listLayouts", "args": []},
        },
        "selectLayout": {
            "description":
                "レイアウトを選択する(index/名前)。パネル未オープン時は自動で開く。"
                "選択すると印刷範囲が地図に表示されスケールが自動計算される。",
            "example": {"method": "selectLayout", "args": ["A4縦"]},
        },
        "printOptions": {
            "description":
                "印刷範囲のスケール・角度を取得/設定する。"
                "{scale, angle} を渡すと設定(印刷範囲表示に反映)。",
            "example": {"method": "printOptions",
                        "args": [{"scale": 2500, "angle": 0}]},
        },
        "showPrintArea": {
            "description":
                "印刷範囲の地図上表示を切り替える。visible=Trueで表示/"
                "Falseで消去。",
            "example": {"method": "showPrintArea", "args": [True]},
        },
        "listItems": {
            "description":
                "選択中レイアウトのアイテム一覧(index/uuid/名前/タイプ/"
                "可視/位置・サイズ)を返す。",
            "example": {"method": "listItems", "args": []},
        },
        "itemProperties": {
            "description":
                "アイテムのプロパティを返す。itemはindex/uuid/id/表示名、"
                "省略時は選択中アイテム。",
            "example": {"method": "itemProperties", "args": ["title_label"]},
        },
        "setItemProperties": {
            "description":
                "アイテムのプロパティを適用する。{id, visible, position:{x,y},"
                " size:{w,h}, text等} をpropertiesに渡す(部分適用可)。",
            "example": {"method": "setItemProperties",
                        "args": ["title_label", {"text": "新しいタイトル"}]},
        },
        "saveLayoutProperties": {
            "description":
                "選択中レイアウトの全アイテムプロパティをJSONへ保存。"
                "path省略時は ~/QGIS_Layouts/<レイアウト名>_layout_properties.json。",
            "example": {"method": "saveLayoutProperties", "args": []},
        },
        "loadLayoutProperties": {
            "description":
                "JSONからプロパティを読み込み選択中レイアウトへ適用する"
                "(uuid優先・順序フォールバックでアイテム対応)。",
            "example": {"method": "loadLayoutProperties",
                        "args": ["C:/path/to/props.json"]},
        },
        "openLayoutManager": {
            "description":
                "選択中レイアウトをQGISレイアウトデザイナで開く。",
            "example": {"method": "openLayoutManager", "args": []},
        },
        "manageLayouts": {
            "description":
                "QGIS標準レイアウトマネージャ(レイアウトの削除・名前変更・"
                "複製が可能)を開く。操作はパネル一覧へ自動反映される。",
            "example": {"method": "manageLayouts", "args": []},
        },
        "listStandardLayouts": {
            "description":
                "同梱 composer/*.qpt の標準レイアウトテンプレート一覧を返す。",
            "example": {"method": "listStandardLayouts", "args": []},
        },
        "addStandardLayout": {
            "description":
                "標準レイアウトテンプレート(composer/*.qpt)をプロジェクトへ"
                "追加する。name省略時は一覧のみ返す。同名は連番でユニーク化。",
            "example": {"method": "addStandardLayout", "args": ["A4縦"]},
        },
        "refresh": {
            "description":
                "アイテム情報とレイアウト情報を再読込する"
                "(Refresh Item Infoボタン相当)。",
            "example": {"method": "refresh", "args": []},
        },
        "layoutInfo": {
            "description":
                "選択中レイアウトの情報テキスト(ページ数・サイズ・"
                "全アイテム一覧)を返す。",
            "example": {"method": "layoutInfo", "args": []},
        },
        "listPropertyFiles": {
            "description":
                "保存済みレイアウトプロパティJSON一覧"
                "(~/QGIS_Layouts/*.json)を返す。",
            "example": {"method": "listPropertyFiles", "args": []},
        },
        "removeLayout": {
            "description":
                "レイアウトをプロジェクトから削除する(index/名前)。"
                "注意:確認なしで実際に削除する。",
            "example": {"method": "removeLayout", "args": ["A4縦"]},
        },
        "renameLayout": {
            "description":
                "レイアウトの名前を変更する(index/名前 + new_name)。",
            "example": {"method": "renameLayout",
                        "args": ["A4縦", "A4縦_改"]},
        },
        "duplicateLayout": {
            "description":
                "レイアウトを複製する(index/名前、任意で新しい名前)。",
            "example": {"method": "duplicateLayout",
                        "args": ["A4縦", "A4縦_copy"]},
        },
        "createLayout": {
            "description":
                "空の印刷レイアウトを新規作成する(name)。",
            "example": {"method": "createLayout", "args": ["新規図面"]},
        },
        "status": {
            "description":
                "パネル開閉・選択レイアウト・スケール/角度・印刷範囲表示の"
                "実行時状態を返す。",
            "example": {"method": "status", "args": []},
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

    def _dialog(self):
        return getattr(self._plugin, "dialog", None)

    def _dock(self):
        return getattr(self._plugin, "dock_widget", None)

    def _ensure_panel(self):
        """パネル(ダイアログ)が無ければ開く。dlgを返す。"""
        dlg = self._dialog()
        if dlg is None:
            self._plugin.run()
            dlg = self._dialog()
        return dlg

    def _find_item(self, dlg, item):
        """item指定(index/uuid/id/表示名)をレイアウトアイテムに解決する。"""
        items = dlg.get_valid_layout_items()
        if item is None:
            cur = dlg.items_tree.currentItem()
            if cur is not None:
                data = cur.data(0, _USER_ROLE)
                if data is not None:
                    return data
            return items[0] if items else None
        if isinstance(item, bool):
            return None
        if isinstance(item, int):
            return items[item] if -len(items) <= item < len(items) else None
        s = str(item)
        for it in items:  # uuid / id / 表示名で照合
            for cand in (getattr(it, "uuid", lambda: None)(),
                         getattr(it, "id", lambda: None)(),
                         dlg.get_item_display_name(it)):
                if cand and str(cand) == s:
                    return it
        for it in items:  # 部分一致フォールバック
            if s in dlg.get_item_display_name(it):
                return it
        return None

    def _method_catalog(self):
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

    # ---------- bridge メソッド(JSON文字列を返す) ----------

    def pluginInfo(self):
        """プラグインの自己記述(id/summary/when_to_use/methods)を返す。"""
        return self._ok({
            "id": "geo_report",
            "name": self.NAME,
            "summary": self.SUMMARY,
            "when_to_use": list(self.WHEN_TO_USE),
            "invoke": {"type": "bridge_call", "plugin_id": "geo_report",
                       "method": "<method>", "args": []},
            "methods": self._method_catalog(),
            "state": {
                "panel": self._dock() is not None,
                "panelVisible": bool(self._dock() is not None
                                     and self._dock().isVisible()),
            },
        })

    def status(self):
        """パネル・選択レイアウト・印刷範囲表示の状態を返す。"""
        dlg = self._dialog()
        dock = self._dock()
        info = {
            "panel": dock is not None,
            "panelVisible": bool(dock is not None and dock.isVisible()),
            "layout": None,
            "printAreaVisible": bool(
                getattr(dlg, "_print_area_rubberband", None)),
        }
        if dlg is not None and getattr(dlg, "current_layout", None) is not None:
            info["layout"] = dlg.current_layout.name()
            info["scale"] = dlg.scale_spin.value()
            info["angle"] = dlg.angle_spin.value()
            info["itemCount"] = len(dlg.get_valid_layout_items())
        mgr = QgsProject.instance().layoutManager()
        info["layoutCount"] = len(mgr.layouts()) if mgr is not None else 0
        return self._ok(info)

    def openPanel(self):
        """レイアウト選択ドックパネルを開く。"""
        dlg = self._ensure_panel()
        if dlg is None:
            return self._err("could not open panel "
                             "(no layouts and no composer/*.qpt)")
        dock = self._dock()
        if dock is not None:
            dock.show()
            dock.raise_()
        return self._ok({"panelVisible": bool(dock and dock.isVisible())})

    def closePanel(self):
        """ドックパネルを閉じる。"""
        dock = self._dock()
        if dock is not None:
            dock.close()
        return self._ok({"panelVisible": False})

    def listLayouts(self):
        """プロジェクトの印刷レイアウト一覧を返す。"""
        mgr = QgsProject.instance().layoutManager()
        layouts = mgr.layouts() if mgr is not None else []
        dlg = self._dialog()
        cur = getattr(dlg, "current_layout", None) if dlg is not None else None
        out = []
        for i, ly in enumerate(layouts):
            maps = [it for it in ly.items()
                    if it.__class__.__name__ == "QgsLayoutItemMap"]
            out.append({
                "index": i,
                "name": ly.name(),
                "pages": ly.pageCollection().pageCount(),
                "mapItems": len(maps),
                "selected": ly is cur,
            })
        return self._ok({"layouts": out})

    def selectLayout(self, layout):
        """レイアウトを選択する(index/名前)。"""
        dlg = self._ensure_panel()
        if dlg is None:
            return self._err("panel could not be opened")
        lw = dlg.layout_list
        row = None
        if isinstance(layout, bool):
            return self._err("invalid layout selector")
        if isinstance(layout, int):
            row = layout if -lw.count() <= layout < lw.count() else None
        else:
            s = str(layout)
            for i in range(lw.count()):
                if lw.item(i).text().startswith(s) or s in lw.item(i).text():
                    row = i
                    break
        if row is None:
            return self._err(f"layout not found: {layout}")
        lw.setCurrentRow(row)  # → on_layout_selected
        cur = getattr(dlg, "current_layout", None)
        return self._ok({"selected": row,
                         "layout": cur.name() if cur is not None else None})

    def printOptions(self, options=None):
        """スケール・角度の取得/設定。{scale, angle} を渡すと設定。"""
        dlg = self._dialog()
        if dlg is None:
            return self._err("panel not open")
        if isinstance(options, dict):
            if "scale" in options and options["scale"] is not None:
                dlg.scale_spin.setValue(float(options["scale"]))
            if "angle" in options and options["angle"] is not None:
                dlg.angle_spin.setValue(float(options["angle"]))
        return self._ok({"scale": dlg.scale_spin.value(),
                         "angle": dlg.angle_spin.value()})

    def showPrintArea(self, visible=True):
        """印刷範囲の地図上表示を切り替える。"""
        dlg = self._ensure_panel()
        if dlg is None:
            return self._err("panel could not be opened")
        if getattr(dlg, "current_layout", None) is None:
            return self._err("no layout selected")
        shown = bool(getattr(dlg, "_print_area_rubberband", None))
        if shown != bool(visible):
            dlg.show_print_area_on_map()  # トグル
        return self._ok({"printAreaVisible":
                         bool(getattr(dlg, "_print_area_rubberband", None))})

    def listItems(self):
        """選択中レイアウトのアイテム一覧を返す。"""
        dlg = self._dialog()
        if dlg is None or getattr(dlg, "current_layout", None) is None:
            return self._err("no layout selected (open panel + selectLayout)")
        out = []
        for i, it in enumerate(dlg.get_valid_layout_items()):
            pos, size = dlg.get_item_position_size(it)
            out.append({
                "index": i,
                "uuid": it.uuid() if hasattr(it, "uuid") else None,
                "id": it.id() if hasattr(it, "id") else None,
                "name": dlg.get_item_display_name(it),
                "type": it.__class__.__name__,
                "visible": dlg.get_item_visibility(it),
                "position": pos,
                "size": size,
            })
        return self._ok({"layout": dlg.current_layout.name(),
                         "items": out})

    def itemProperties(self, item=None):
        """アイテムのプロパティを返す。"""
        dlg = self._dialog()
        if dlg is None or getattr(dlg, "current_layout", None) is None:
            return self._err("no layout selected")
        it = self._find_item(dlg, item)
        if it is None:
            return self._err(f"item not found: {item}")
        try:
            props = dlg.collect_item_properties(it)
        except Exception as e:
            return self._err(f"collect failed: {e}")
        return self._ok({"name": dlg.get_item_display_name(it),
                         "properties": props})

    def setItemProperties(self, item, properties):
        """アイテムのプロパティを部分適用する。"""
        dlg = self._dialog()
        if dlg is None or getattr(dlg, "current_layout", None) is None:
            return self._err("no layout selected")
        if not isinstance(properties, dict):
            return self._err("properties must be an object")
        it = self._find_item(dlg, item)
        if it is None:
            return self._err(f"item not found: {item}")
        data = {"item_type": it.__class__.__name__, "properties": properties}
        try:
            dlg.apply_properties_to_item_silent(it, data)
            dlg.current_layout.refresh()
            dlg.load_layout_items()
        except Exception as e:
            return self._err(f"apply failed: {e}")
        return self._ok({"applied": dlg.get_item_display_name(it)})

    def saveLayoutProperties(self, path=None):
        """選択中レイアウトのアイテムプロパティをJSONへ保存。"""
        dlg = self._dialog()
        if dlg is None or getattr(dlg, "current_layout", None) is None:
            return self._err("no layout selected")
        props = dlg.collect_layout_properties()
        if not path:
            folder = os.path.join(os.path.expanduser("~"), "QGIS_Layouts")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(
                folder, f"{dlg.current_layout.name()}_layout_properties.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(props, f, ensure_ascii=False, indent=2)
        return self._ok({"path": path,
                         "items": len(props.get("items", []))})

    def loadLayoutProperties(self, path):
        """JSONからプロパティを読み込み選択中レイアウトへ適用。"""
        dlg = self._dialog()
        if dlg is None or getattr(dlg, "current_layout", None) is None:
            return self._err("no layout selected")
        if not path:
            return self._err("path required")
        with open(path, "r", encoding="utf-8") as f:
            props = json.load(f)
        if not dlg.validate_layout_properties(props):
            return self._err("invalid layout properties file")
        applied = dlg.apply_layout_properties(props)
        dlg.load_layout_items()
        dlg.load_layout_info()
        return self._ok({"applied": applied,
                         "items": len(props.get("items", []))})

    def openLayoutManager(self):
        """選択中レイアウトをレイアウトデザイナで開く。"""
        dlg = self._dialog()
        if dlg is None or getattr(dlg, "current_layout", None) is None:
            return self._err("no layout selected")
        dlg.open_layout_manager()
        return self._ok({"layout": dlg.current_layout.name()})

    def manageLayouts(self):
        """QGISレイアウトマネージャ(削除・名前変更・複製が可能)を開く。"""
        from qgis.PyQt.QtCore import QTimer
        dlg = self._ensure_panel()
        if dlg is None:
            return self._err("panel could not be opened")
        # モーダルダイアログなので呼出をブロックしないよう非同期起動する
        QTimer.singleShot(0, dlg.open_layout_manager_dialog)
        return self._ok({"launched": True})

    # ---------- 標準レイアウト / レイアウト情報 ----------

    @staticmethod
    def _composer_qpt_files():
        import glob
        composer_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'composer')
        return sorted(glob.glob(os.path.join(composer_dir, '*.qpt')))

    def listStandardLayouts(self):
        """同梱 composer/*.qpt の標準レイアウト名一覧を返す。"""
        names = [os.path.splitext(os.path.basename(p))[0]
                 for p in self._composer_qpt_files()]
        return self._ok({"templates": names})

    def addStandardLayout(self, name=None):
        """標準レイアウトテンプレートをプロジェクトへ追加する。"""
        import glob
        from qgis.core import QgsReadWriteContext, QgsPrintLayout
        from qgis.PyQt.QtXml import QDomDocument
        qpt_files = self._composer_qpt_files()
        names = [os.path.splitext(os.path.basename(p))[0]
                 for p in qpt_files]
        if not names:
            return self._err("no standard layout templates found")
        if name is None:
            return self._ok({"templates": names,
                             "note": "pass a template name to add"})
        s = str(name)
        match = None
        for i, n in enumerate(names):
            if n == s:
                match = i
                break
        if match is None:
            for i, n in enumerate(names):  # 部分一致フォールバック
                if s in n:
                    match = i
                    break
        if match is None:
            return self._err(f"template not found: {name!r} "
                             f"(available: {names})")
        qpt_path = qpt_files[match]
        try:
            with open(qpt_path, encoding='utf-8') as f:
                doc = QDomDocument()
                doc.setContent(f.read())
            project = QgsProject.instance()
            mgr = project.layoutManager()
            layout = QgsPrintLayout(project)
            layout.initializeDefaults()
            res = layout.loadFromTemplate(doc, QgsReadWriteContext())
            ok = bool(res[1]) if isinstance(res, (tuple, list)) \
                and len(res) > 1 else bool(res)
            if not ok:
                return self._err("loadFromTemplate failed")
            existing = {ly.name() for ly in mgr.layouts()}
            new_name = names[match]
            i = 2
            while new_name in existing:
                new_name = f"{names[match]}_{i}"
                i += 1
            layout.setName(new_name)
            mgr.addLayout(layout)
        except Exception as e:
            return self._err(f"import failed: {e}")
        # パネルが開いていれば一覧と選択を更新
        dlg = self._dialog()
        if dlg is not None:
            try:
                dlg.reload_layout_list()
                for row in range(dlg.layout_list.count()):
                    it = dlg.layout_list.item(row)
                    if it is not None and it.data(_USER_ROLE) is layout:
                        dlg.layout_list.setCurrentRow(row)
                        break
            except Exception:  # nosec B110  # 設計上の許容
                pass
        return self._ok({"added": new_name, "template": names[match]})

    def refresh(self):
        """アイテム情報とレイアウト情報を再読込する。"""
        dlg = self._dialog()
        if dlg is None:
            return self._err("panel not open")
        if getattr(dlg, "current_layout", None) is not None:
            dlg.load_layout_items()
            dlg.load_layout_info()
        return self._ok({"layoutCount": dlg.layout_list.count(),
                         "layout": (dlg.current_layout.name()
                                    if getattr(dlg, "current_layout", None)
                                    is not None else None)})

    def layoutInfo(self):
        """選択中レイアウトの情報テキストを返す。"""
        dlg = self._dialog()
        if dlg is None or getattr(dlg, "current_layout", None) is None:
            return self._err("no layout selected")
        dlg.load_layout_info()
        text = ""
        if getattr(dlg, "info_text", None) is not None:
            try:
                text = dlg.info_text.toPlainText()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        return self._ok({"layout": dlg.current_layout.name(), "info": text})

    def listPropertyFiles(self):
        """~/QGIS_Layouts の保存済みプロパティJSON一覧を返す。"""
        folder = os.path.join(os.path.expanduser("~"), "QGIS_Layouts")
        files = []
        if os.path.isdir(folder):
            for fn in sorted(os.listdir(folder)):
                if fn.lower().endswith('.json'):
                    p = os.path.join(folder, fn)
                    files.append({
                        "file": fn, "path": p,
                        "size": os.path.getsize(p),
                        "mtime": os.path.getmtime(p)})
        return self._ok({"folder": folder, "files": files})

    # ---------- レイアウト操作(マネージャ相当) ----------

    def _find_layout(self, layout):
        """index/名前をレイアウトオブジェクトに解決する。"""
        mgr = QgsProject.instance().layoutManager()
        layouts = mgr.layouts() if mgr is not None else []
        if isinstance(layout, bool):
            return None, layouts
        if isinstance(layout, int):
            return (layouts[layout]
                    if -len(layouts) <= layout < len(layouts)
                    else None), layouts
        s = str(layout)
        for ly in layouts:
            if ly.name() == s:
                return ly, layouts
        for ly in layouts:
            if s in ly.name():
                return ly, layouts
        return None, layouts

    def removeLayout(self, layout):
        """レイアウトを削除する(確認なし)。"""
        ly, layouts = self._find_layout(layout)
        if ly is None:
            return self._err(f"layout not found: {layout!r} "
                             f"(have: {[x.name() for x in layouts]})")
        name = ly.name()
        QgsProject.instance().layoutManager().removeLayout(ly)
        return self._ok({"removed": name})

    def renameLayout(self, layout, new_name):
        """レイアウト名を変更する。"""
        ly, layouts = self._find_layout(layout)
        if ly is None:
            return self._err(f"layout not found: {layout!r}")
        new_name = str(new_name or "").strip()
        if not new_name:
            return self._err("new_name is empty")
        mgr = QgsProject.instance().layoutManager()
        # 同名チェック(QGISは重複名を許容しない)
        if any(x.name() == new_name for x in mgr.layouts()):
            return self._err(f"name already in use: {new_name!r}")
        old = ly.name()
        # QgsLayoutManager.renameLayout が無い環境は setName で代替
        try:
            mgr.renameLayout(ly, new_name)
        except Exception:
            ly.setName(new_name)
        return self._ok({"renamed": old, "name": ly.name()})

    def duplicateLayout(self, layout, new_name=None):
        """レイアウトを複製する。"""
        ly, _layouts = self._find_layout(layout)
        if ly is None:
            return self._err(f"layout not found: {layout!r}")
        mgr = QgsProject.instance().layoutManager()
        dup = mgr.duplicateLayout(
            ly, str(new_name) if new_name else (ly.name() + "_copy"))
        if dup is None:
            return self._err("duplicateLayout failed")
        return self._ok({"duplicated": ly.name(), "name": dup.name()})

    def createLayout(self, name):
        """空の印刷レイアウトを新規作成する。"""
        from qgis.core import QgsPrintLayout
        name = str(name or "").strip()
        if not name:
            return self._err("name is empty")
        project = QgsProject.instance()
        mgr = project.layoutManager()
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(mgr.generateUniqueTitle(name)
                       if hasattr(mgr, "generateUniqueTitle") else name)
        mgr.addLayout(layout)
        return self._ok({"created": layout.name()})
