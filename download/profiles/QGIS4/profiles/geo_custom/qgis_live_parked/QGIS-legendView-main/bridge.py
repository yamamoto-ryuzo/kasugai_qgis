# -*- coding: utf-8 -*-
"""QGIS-legendView を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、qgis_live_driver の
bridge_call コマンド(ファイルJSONL / REST /api/cmd / MCP qgis_bridge_call)
から ``qgis.utils.plugins['QGIS-legendView-main'].bridge.<method>(*args)``
がプロセス内で直接呼ばれる。

各メソッドは JSON 文字列を返す(bridge_call 側で構造化される)。
ドメインエラー(ドック未オープン・データセット不明等)は
``{"ok": false, "error": ...}`` を返し、予期しない例外は呼び出し元
(driver の {"error": traceback})に委ねる。いずれも GUI スレッドで
同期的に実行される。

例(MCP): qgis_bridge_call pluginId="QGIS-legendView-main" method="legend"
"""

import inspect
import json

from qgis.core import QgsExpressionContextUtils, QgsProject


class LegendViewBridge:
    """``plugins['QGIS-legendView-main'].bridge`` にぶら下げるAI向けAPI。"""

    NAME = "凡例ビュー (QGIS-legendView)"
    SUMMARY = ("レイヤの凡例(シンボル一覧)をドックパネルに表示する。"
               "対象レイヤは legend_* プロジェクト変数で登録したレイヤと"
               "現在のアクティブレイヤから選択。不透明度・名前付きスタイルの"
               "切替も可能。")
    WHEN_TO_USE = [
        "レイヤの凡例(シンボルとラベル)を確認したい",
        "凡例ドックを開いて対象レイヤを切り替えたい",
        "レイヤの不透明度や名前付きスタイルを変更したい",
        "現在レイヤを legend_* プロジェクト変数へ登録したい",
        "登録済みの legend_* 変数を確認したい",
    ]
    METHOD_DOCS = {
        "openDock": {
            "description":
                "凡例ドックを開く(plugin.run()相当。トグルではなく常に開く)。",
            "example": {"method": "openDock", "args": []},
        },
        "closeDock": {
            "description": "凡例ドックを閉じる。",
            "example": {"method": "closeDock", "args": []},
        },
        "listDatasets": {
            "description":
                "凡例対象コンボの一覧(index/表示名/layer_id/選択中)を返す。"
                "legend_*変数登録レイヤ+アクティブレイヤが並ぶ。",
            "example": {"method": "listDatasets", "args": []},
        },
        "selectDataset": {
            "description":
                "凡例対象を選択する(index/表示名/layer_id)。"
                "選択で凡例表示が更新される。",
            "example": {"method": "selectDataset", "args": ["★ 市区町村 (Current)"]},
        },
        "legend": {
            "description":
                "選択中レイヤの凡例項目(シンボルラベル一覧)を返す。",
            "example": {"method": "legend", "args": []},
        },
        "opacity": {
            "description":
                "選択中レイヤの不透明度を取得/設定する(0.0-1.0)。",
            "example": {"method": "opacity", "args": [0.5]},
        },
        "listStyles": {
            "description":
                "選択中レイヤの名前付きスタイル一覧と現在のスタイルを返す。",
            "example": {"method": "listStyles", "args": []},
        },
        "setStyle": {
            "description":
                "選択中レイヤの名前付きスタイルを切り替える。",
            "example": {"method": "setStyle", "args": ["default"]},
        },
        "selectCurrentLayer": {
            "description":
                "凡例対象をQGISのアクティブレイヤに合わせる"
                "(Current Layerボタン相当)。",
            "example": {"method": "selectCurrentLayer", "args": []},
        },
        "registerCurrentLayer": {
            "description":
                "アクティブレイヤを legend_* プロジェクト変数として登録する"
                "(登録ボタン相当)。priorityで変数値(表示優先度)を指定可。",
            "example": {"method": "registerCurrentLayer", "args": [1]},
        },
        "registerLayer": {
            "description":
                "指定レイヤを legend_* プロジェクト変数として登録する。"
                "layer_id省略時はアクティブレイヤ。",
            "example": {"method": "registerLayer", "args": [None, 1]},
        },
        "setLegendVariable": {
            "description":
                "legend_* プロジェクト変数の値を編集する"
                "(変数一覧ダイアログのEdit相当)。",
            "example": {"method": "setLegendVariable",
                        "args": ["legend_層_市区町村", "2"]},
        },
        "deleteLegendVariable": {
            "description":
                "legend_* プロジェクト変数を削除する"
                "(変数一覧ダイアログのDelete相当)。",
            "example": {"method": "deleteLegendVariable",
                        "args": ["legend_層_市区町村"]},
        },
        "refresh": {
            "description":
                "凡例対象コンボを再構築する(レイヤ/変数変更の反映用)。",
            "example": {"method": "refresh", "args": []},
        },
        "legendVariables": {
            "description":
                "プロジェクト変数 legend_* の一覧(変数名/値/解決先レイヤ)を返す。",
            "example": {"method": "legendVariables", "args": []},
        },
        "status": {
            "description":
                "ドック開閉・選択中レイヤ・不透明度・凡例行数の状態を返す。",
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

    def _dock(self):
        return getattr(self._plugin, "dockwidget", None)

    def _require_dock(self):
        dock = self._dock()
        if dock is None:
            return None, self._err("dock not open (call openDock first)")
        return dock, None

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
        dock = self._dock()
        return self._ok({
            "id": "QGIS-legendView-main",
            "name": self.NAME,
            "summary": self.SUMMARY,
            "when_to_use": list(self.WHEN_TO_USE),
            "invoke": {"type": "bridge_call",
                       "plugin_id": "QGIS-legendView-main",
                       "method": "<method>", "args": []},
            "methods": self._method_catalog(),
            "state": {
                "dock": dock is not None,
                "dockVisible": bool(dock is not None and dock.isVisible()),
            },
        })

    def status(self):
        """ドック・選択レイヤ・凡例の状態を返す。"""
        p = self._plugin
        dock = self._dock()
        info = {
            "active": bool(getattr(p, "pluginIsActive", False)),
            "dock": dock is not None,
            "dockVisible": bool(dock is not None and dock.isVisible()),
        }
        if dock is not None:
            layer = getattr(dock, "currentLayer", None)
            info["layer"] = ({"id": layer.id(), "name": layer.name()}
                             if layer is not None else None)
            info["datasetIndex"] = dock.comboBox.currentIndex()
            info["legendRows"] = dock.tableWidget.rowCount()
            try:
                info["opacity"] = dock.mOpacityWidget.opacity()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        return self._ok(info)

    def openDock(self):
        """凡例ドックを開く。"""
        p = self._plugin
        if not getattr(p, "pluginIsActive", False) or p.dockwidget is None:
            p.run()
        dock = p.dockwidget
        if dock is None:
            return self._err("dock could not be created")
        dock.show()
        dock.raise_()
        return self._ok({"dockVisible": dock.isVisible()})

    def closeDock(self):
        """凡例ドックを閉じる。"""
        dock = self._dock()
        if dock is not None:
            dock.close()  # → closingPlugin → onClosePlugin
        return self._ok({"closed": True})

    def listDatasets(self):
        """凡例対象コンボの一覧を返す。"""
        dock, err = self._require_dock()
        if err:
            return err
        cb = dock.comboBox
        cur = cb.currentIndex()
        out = [{"index": i, "text": cb.itemText(i),
                "layer_id": cb.itemData(i), "selected": i == cur}
               for i in range(cb.count())]
        return self._ok({"datasets": out, "current": cur})

    def selectDataset(self, dataset):
        """凡例対象を選択する(index/表示名/layer_id)。"""
        dock, err = self._require_dock()
        if err:
            return err
        cb = dock.comboBox
        idx = None
        if isinstance(dataset, bool):
            return self._err("invalid dataset selector")
        if isinstance(dataset, int):
            idx = dataset if -cb.count() <= dataset < cb.count() else None
        else:
            s = str(dataset)
            for i in range(cb.count()):
                if cb.itemText(i) == s or cb.itemData(i) == s:
                    idx = i
                    break
            if idx is None:
                for i in range(cb.count()):
                    if s in cb.itemText(i):
                        idx = i
                        break
        if idx is None:
            return self._err(f"dataset not found: {dataset}")
        cb.setCurrentIndex(idx)  # → currentIndexChanged → showLegend
        layer = dock.currentLayer
        return self._ok({"selected": idx,
                         "layer": layer.name() if layer is not None else None})

    def legend(self):
        """選択中レイヤの凡例項目一覧を返す。"""
        dock, err = self._require_dock()
        if err:
            return err
        layer = getattr(dock, "currentLayer", None)
        if layer is None:
            return self._err("no layer selected")
        labels = []
        tw = dock.tableWidget
        if tw.isVisible() or tw.rowCount():
            for r in range(tw.rowCount()):
                itm = tw.item(r, 1)
                labels.append(itm.text() if itm is not None else None)
        else:
            lw = dock.listWidget
            for i in range(lw.count()):
                labels.append(lw.item(i).text())
        return self._ok({
            "layer": layer.name(), "layer_id": layer.id(),
            "type": layer.__class__.__name__,
            "items": labels,
        })

    def opacity(self, value=None):
        """選択中レイヤの不透明度を取得/設定する(0.0-1.0)。"""
        dock, err = self._require_dock()
        if err:
            return err
        if dock.currentLayer is None:
            return self._err("no layer selected")
        if value is not None:
            dock.mOpacityWidget.setOpacity(float(value))  # → opacityChanged
        try:
            cur = dock.mOpacityWidget.opacity()
        except Exception:
            cur = None
        return self._ok({"opacity": cur})

    def listStyles(self):
        """選択中レイヤの名前付きスタイル一覧を返す。"""
        dock, err = self._require_dock()
        if err:
            return err
        layer = getattr(dock, "currentLayer", None)
        if layer is None:
            return self._err("no layer selected")
        mgr = layer.styleManager()
        return self._ok({"styles": list(mgr.styles()),
                         "current": mgr.currentStyle()})

    def setStyle(self, name):
        """選択中レイヤの名前付きスタイルを切り替える。"""
        dock, err = self._require_dock()
        if err:
            return err
        layer = getattr(dock, "currentLayer", None)
        if layer is None:
            return self._err("no layer selected")
        if str(name) not in layer.styleManager().styles():
            return self._err(f"style not found: {name} "
                             f"(have: {layer.styleManager().styles()})")
        dock.changeNamedStyle(str(name))
        return self._ok({"style": str(name)})

    def selectCurrentLayer(self):
        """凡例対象をアクティブレイヤに合わせる。"""
        dock, err = self._require_dock()
        if err:
            return err
        dock.selectCurrentLayer()
        layer = dock.currentLayer
        return self._ok({"layer": layer.name() if layer is not None else None,
                         "datasetIndex": dock.comboBox.currentIndex()})

    def registerCurrentLayer(self, priority=None):
        """アクティブレイヤを legend_* プロジェクト変数として登録する。"""
        return self.registerLayer(None, priority)

    def registerLayer(self, layer_id=None, priority=None):
        """指定レイヤを legend_* プロジェクト変数として登録する。"""
        dock, err = self._require_dock()
        if err:
            return err
        p = self._plugin
        if layer_id is not None:
            layer = QgsProject.instance().mapLayer(str(layer_id))
            if layer is None:
                return self._err(f"layer not found: {layer_id!r}")
            p.iface.setActiveLayer(layer)
        if priority is not None:
            try:
                dock.prioritySpinBox.setValue(int(priority))
            except Exception:  # nosec B110  # 設計上の許容
                pass
        if p.iface.activeLayer() is None:
            return self._err("no active layer to register")
        dock.registerCurrentLayer()
        return self.legendVariables()

    def setLegendVariable(self, name, value):
        """legend_* プロジェクト変数の値を設定する。"""
        name = str(name or "").strip()
        if not name.startswith("legend_"):
            name = "legend_" + name
        ecs = QgsExpressionContextUtils.projectScope(QgsProject.instance())
        if name not in list(ecs.variableNames()):
            return self._err(f"variable not found: {name!r} "
                             "(use registerLayer to create)")
        QgsExpressionContextUtils.setProjectVariable(
            QgsProject.instance(), name, "" if value is None else str(value))
        self._refresh_combo()
        return self.legendVariables()

    def deleteLegendVariable(self, name):
        """legend_* プロジェクト変数を削除する。"""
        name = str(name or "").strip()
        if not name.startswith("legend_"):
            name = "legend_" + name
        ecs = QgsExpressionContextUtils.projectScope(QgsProject.instance())
        if name not in list(ecs.variableNames()):
            return self._err(f"variable not found: {name!r}")
        try:
            QgsExpressionContextUtils.removeProjectVariable(
                QgsProject.instance(), name)
        except Exception:
            QgsProject.instance().removeEntry('LegendView', name)
        self._refresh_combo()
        return self.legendVariables()

    def _refresh_combo(self):
        """凡例対象コンボを再構築する。"""
        dock = self._dock()
        if dock is not None:
            try:
                dock.comboBox.clear()
                dock.comboDataSet()
            except Exception:  # nosec B110  # 設計上の許容
                pass

    def refresh(self):
        """凡例対象コンボを再構築する。"""
        dock, err = self._require_dock()
        if err:
            return err
        self._refresh_combo()
        return self.listDatasets()

    def legendVariables(self):
        """legend_* プロジェクト変数の一覧を返す。"""
        ecs = QgsExpressionContextUtils.projectScope(QgsProject.instance())
        out = []
        for name in sorted(ecs.variableNames()):
            if not name.startswith("legend_"):
                continue
            layer = None
            dock = self._dock()
            if dock is not None:
                layer = dock.findLayerByVariableName(
                    name.replace("legend_", ""))
            out.append({
                "name": name,
                "value": ecs.variable(name),
                "layer": layer.name() if layer is not None else None,
                "layer_id": layer.id() if layer is not None else None,
            })
        return self._ok({"variables": out})
