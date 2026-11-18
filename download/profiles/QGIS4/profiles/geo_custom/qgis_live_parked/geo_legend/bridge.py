# -*- coding: utf-8 -*-
"""geo_legend（upstream: QGIS-legendView）を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、geo_driver の
bridge_call コマンド(ファイルJSONL / REST /api/cmd / MCP qgis_bridge_call)
から ``qgis.utils.plugins['geo_legend'].bridge.<method>(*args)``
がプロセス内で直接呼ばれる。

各メソッドは JSON 文字列を返す(bridge_call 側で構造化される)。
ドメインエラー(ドック未オープン・データセット不明等)は
``{"ok": false, "error": ...}`` を返し、予期しない例外は呼び出し元
(driver の {"error": traceback})に委ねる。いずれも GUI スレッドで
同期的に実行される。

例(MCP): qgis_bridge_call pluginId="geo_legend" method="legend"
"""

import inspect
import json
import os
import tempfile
import time

from qgis.core import (QgsCategorizedSymbolRenderer,
                       QgsExpressionContextUtils, QgsFillSymbol,
                       QgsGraduatedSymbolRenderer, QgsLayoutExporter,
                       QgsLayoutItemLegend, QgsLayoutItemMap,
                       QgsLayoutSize, QgsLineSymbol, QgsMarkerSymbol,
                       QgsPrintLayout, QgsProject, QgsRendererCategory,
                       QgsRendererRange, QgsRuleBasedRenderer,
                       QgsSingleSymbolRenderer, QgsStyle, QgsUnitTypes,
                       QgsWkbTypes)
from qgis.PyQt.QtCore import QModelIndex, QRectF, Qt
from qgis.PyQt.QtGui import QColor


class LegendViewBridge:
    """``plugins['geo_legend'].bridge`` にぶら下げるAI向けAPI。"""

    NAME = "凡例ビュー (geo_legend)"
    SUMMARY = ("レイヤの凡例(シンボル一覧)の表示と作成。ドックパネルに"
               "コンパクトな凡例を表示するほか、個別値分類・数値階級・"
               "ルールベースのシンボル凡例をレンダラとして作成し、"
               "印刷レイアウトへの凡例アイテム追加や凡例画像(PNG)の"
               "出力もできる。対象レイヤは legend_* プロジェクト変数で"
               "登録したレイヤと現在のアクティブレイヤから選択。"
               "不透明度・名前付きスタイルの切替も可能。")
    WHEN_TO_USE = [
        "レイヤの凡例(シンボルとラベル)を確認したい",
        "凡例ドックを開いて対象レイヤを切り替えたい",
        "レイヤの不透明度や名前付きスタイルを変更したい",
        "現在レイヤを legend_* プロジェクト変数へ登録したい",
        "登録済みの legend_* 変数を確認したい",
        "属性値で分類・階級区分・ルールベースの凡例(シンボル)を作成したい",
        "現在のレンダラ(凡例)の内容を取得・確認したい",
        "印刷レイアウトに凡例アイテムを追加したい",
        "凡例だけの画像(PNG)を出力したい",
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
        "legendSpec": {
            "description":
                "レイヤの現在のレンダラ(凡例)定義を返す。type(singleSymbol/"
                "categorizedSymbol/graduatedSymbol/RuleRenderer等)と"
                "凡例項目(label/value/lower-upper/filter/color)を含む。"
                "layerはlayer_id/レイヤ名、省略時はアクティブレイヤ。",
            "example": {"method": "legendSpec", "args": []},
        },
        "applyCategories": {
            "description":
                "属性フィールドの個別値で分類するレンダラを作成し凡例を作る。"
                "field=分類フィールド名(必須)、ramp=配色ランプ名"
                "(QgsStyleのカラーランプ。既定Spectral)、labels/colorsで"
                "個別上書き可。layer省略時はアクティブレイヤ。",
            "example": {"method": "applyCategories",
                        "args": [None, "地目", "Spectral"]},
        },
        "applyGraduated": {
            "description":
                "数値フィールドを階級区分するレンダラを作成し凡例を作る。"
                "classes=階級数(2-20,既定5)、method='equal'(等間隔)/"
                "'quantile'(分位数)、ramp=配色ランプ名。",
            "example": {"method": "applyGraduated",
                        "args": [None, "population", 5, "Viridis", "equal"]},
        },
        "applyRules": {
            "description":
                "ルールベースレンダラを作成し凡例を作る。rulesは"
                "[{\"filter\":\"\\\"field\\\" < 10\",\"label\":\"小\","
                "\"color\":\"#ff0000\"}]形式。省略可キー: "
                "width=線幅(既定mm)/width_unit='mm'|'pixels'|'map_units'|"
                "'meters'(実世界幅)、min_scale/max_scale=縮尺分母の"
                "表示範囲(ルールは min_scale < 分母 <= max_scale で"
                "有効。min_scale=詳細側の排他下限、max_scale=広域側の"
                "包含上限。縮尺帯の幅切替ルールが作れる)。"
                "filter省略はmin/max_scale指定時のみ可。"
                "else_labelでその他ルール追加。",
            "example": {"method": "applyRules",
                        "args": [None, [{"filter": "\"n\" >= 10",
                                         "label": "大",
                                         "color": "#e31a1c",
                                         "width": 0.5}]]},
        },
        "applySingleSymbol": {
            "description":
                "単一シンボルレンダラに戻す(凡例を1項目化)。"
                "color='#rrggbb'で色指定可。",
            "example": {"method": "applySingleSymbol",
                        "args": [None, "#1f78b4"]},
        },
        "addLayoutLegend": {
            "description":
                "印刷レイアウトに凡例アイテム(QgsLayoutItemLegend)を追加する。"
                "layout=レイアウト名(省略時は'AI凡例'を新規作成)。"
                "x/y/w/hはmm。layers=[layer_id/名…]で凡例対象を限定"
                "(省略時は全レイヤ)。linked_map=地図アイテムの表示名/idで"
                "連動、filter_by_map=Trueで地図範囲内に限定。",
            "example": {"method": "addLayoutLegend",
                        "args": ["A4縦", "凡例", 195, 10, None, None]},
        },
        "exportLegendImage": {
            "description":
                "凡例だけの画像(PNG)を出力する。path=出力先"
                "(省略時は一時フォルダ)。layers=[id/名…]で対象限定、"
                "title=凡例タイトル、dpi=解像度(既定96)。",
            "example": {"method": "exportLegendImage",
                        "args": [None, None, "凡例", 150]},
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

    def _cur_layer(self, dock):
        """dock.currentLayer が生存していれば返す。

        レイヤ削除後もドックが旧参照を保持し、QObject メソッド呼出しで
        RuntimeError("wrapped C/C++ object ... has been deleted")に
        なるのを防ぐ。
        """
        layer = getattr(dock, "currentLayer", None)
        if layer is None:
            return None
        try:
            layer.id()
        except RuntimeError:
            return None
        return layer

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
            "id": "geo_legend",
            "name": self.NAME,
            "summary": self.SUMMARY,
            "when_to_use": list(self.WHEN_TO_USE),
            "invoke": {"type": "bridge_call",
                       "plugin_id": "geo_legend",
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
            layer = self._cur_layer(dock)
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
        layer = self._cur_layer(dock)
        return self._ok({"selected": idx,
                         "layer": layer.name() if layer is not None else None})

    def legend(self):
        """選択中レイヤの凡例項目一覧を返す。"""
        dock, err = self._require_dock()
        if err:
            return err
        layer = self._cur_layer(dock)
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
        if self._cur_layer(dock) is None:
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
        layer = self._cur_layer(dock)
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
        layer = self._cur_layer(dock)
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
        layer = self._cur_layer(dock)
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

    # ---------- 凡例作成(レンダラ/レイアウト凡例/画像出力) ----------

    def _find_layer(self, sel):
        """layer_id/レイヤ名/None(=アクティブ)からレイヤを解決する。"""
        proj = QgsProject.instance()
        if sel is None:
            return self._plugin.iface.activeLayer()
        layer = proj.mapLayer(str(sel))
        if layer is None:
            matches = proj.mapLayersByName(str(sel))
            layer = matches[0] if matches else None
        return layer

    @staticmethod
    def _symbol_cls(layer):
        gt = layer.geometryType()
        if gt == QgsWkbTypes.GeometryType.PointGeometry:
            return QgsMarkerSymbol
        if gt == QgsWkbTypes.GeometryType.LineGeometry:
            return QgsLineSymbol
        return QgsFillSymbol

    @staticmethod
    def _ramp(name=None):
        style = QgsStyle.defaultStyle()
        ramp = style.colorRamp(str(name)) if name else None
        if ramp is None:
            for cand in ("Spectral", "Viridis", "RdYlGn"):
                ramp = style.colorRamp(cand)
                if ramp is not None:
                    break
        if ramp is None:
            ramps = style.colorRampNames()
            ramp = style.colorRamp(ramps[0]) if ramps else None
        return ramp

    @classmethod
    def _sym_color(cls, symbol):
        try:
            return cls._attr(symbol, "color").name()
        except Exception:  # 設計上の許容  # nosec B110
            return None

    @classmethod
    def _sym_width(cls, symbol):
        """線幅(線シンボル)または輪郭幅(塗りシンボル)を返す。"""
        try:
            if isinstance(symbol, QgsLineSymbol):
                return cls._attr(symbol, "width")
            if isinstance(symbol, QgsFillSymbol):
                return cls._attr(symbol, "strokeWidth")
        except Exception:  # 設計上の許容  # nosec B110
            pass
        return None

    @staticmethod
    def _attr(obj, name, default=None):
        """QGIS4 で property/method が揺れる属性を両対応で取る。"""
        v = getattr(obj, name, default)
        return v() if callable(v) else v

    def _find_layout(self, name, create=False):
        mgr = QgsProject.instance().layoutManager()
        if name is None:
            if not create:
                layouts = mgr.printLayouts()
                return layouts[0] if layouts else None, None
            base = "AI凡例"
            name = base
            i = 2
            while mgr.layoutByName(name) is not None:
                name = f"{base}{i}"
                i += 1
        layout = mgr.layoutByName(str(name))
        if layout is None:
            if not create:
                return None, self._err(
                    f"layout not found: {name!r}")
            layout = QgsPrintLayout(QgsProject.instance())
            layout.initializeDefaults()
            layout.setName(str(name))
            mgr.addLayout(layout)
        return layout, None

    def _legend_layers(self, legend, layers):
        """凡例モデルの対象レイヤを限定する(None=全レイヤ自動)。"""
        if not layers:
            return None
        resolved = []
        for sel in layers:
            lyr = self._find_layer(sel)
            if lyr is None:
                return f"layer not found: {sel!r}"
            resolved.append(lyr)
        legend.setAutoUpdateModel(False)
        root = legend.model().rootGroup()
        root.removeAllChildren()
        for lyr in resolved:
            root.addLayer(lyr)
        return None

    def _legend_item_labels(self, legend):
        model = legend.model()
        out = []

        def walk(parent, depth):
            for r in range(model.rowCount(parent)):
                child = model.index(r, 0, parent)
                if not child.isValid():
                    continue
                out.append("  " * depth + str(
                    model.data(child, Qt.ItemDataRole.DisplayRole)))
                if depth < 2:
                    walk(child, depth + 1)

        walk(QModelIndex(), 0)
        return out

    def legendSpec(self, layer=None):
        """レイヤの現在のレンダラ(凡例)定義を返す。"""
        lyr = self._find_layer(layer)
        if lyr is None:
            return self._err("layer not found")
        ren = lyr.renderer() if hasattr(lyr, "renderer") else None
        info = {"layer": lyr.name(), "layer_id": lyr.id(),
                "renderer": ren.type() if ren is not None else None}
        if ren is None:
            return self._ok(info)
        items = []
        if isinstance(ren, QgsCategorizedSymbolRenderer):
            info["field"] = self._attr(ren, "classAttribute")
            for c in ren.categories():
                items.append({
                    "label": self._attr(c, "label"),
                    "value": None if self._attr(c, "value") is None
                    else str(self._attr(c, "value")),
                    "color": self._sym_color(self._attr(c, "symbol"))})
        elif isinstance(ren, QgsGraduatedSymbolRenderer):
            info["field"] = self._attr(ren, "classAttribute")
            for rg in ren.ranges():
                items.append({
                    "label": self._attr(rg, "label"),
                    "lower": self._attr(rg, "lowerValue"),
                    "upper": self._attr(rg, "upperValue"),
                    "color": self._sym_color(self._attr(rg, "symbol"))})
        elif isinstance(ren, QgsRuleBasedRenderer):
            def walk(rule, out):
                for ch in rule.children():
                    out.append({
                        "label": self._attr(ch, "label"),
                        "filter": self._attr(ch, "filterExpression"),
                        "else": self._attr(ch, "isElse"),
                        "min_scale": self._attr(ch, "minimumScale"),
                        "max_scale": self._attr(ch, "maximumScale"),
                        "width": self._sym_width(
                            self._attr(ch, "symbol")),
                        "color": self._sym_color(self._attr(ch, "symbol"))})
                    walk(ch, out)
            walk(ren.rootRule(), items)
        else:
            sym = self._attr(ren, "symbol")
            items.append({"label": "", "color": self._sym_color(sym)})
        info["items"] = items
        try:
            info["legend_items"] = [self._attr(it, "label")
                                    for it in ren.legendSymbolItems()]
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return self._ok(info)

    def applyCategories(self, layer=None, field=None, ramp=None,
                        labels=None, colors=None):
        """個別値分類レンダラを作成し凡例を作る。"""
        lyr = self._find_layer(layer)
        if lyr is None:
            return self._err("layer not found")
        if not field:
            return self._err("field required")
        if not hasattr(lyr, "fields") or \
                lyr.fields().indexOf(str(field)) < 0:
            return self._err(f"field not found: {field!r} "
                             f"(have: {[f.name() for f in lyr.fields()]})")
        vals = {f[str(field)] for f in lyr.getFeatures()}
        vals = sorted(vals, key=lambda v: (v is None, str(v)))
        if len(vals) > 256:
            return self._err(
                f"too many unique values ({len(vals)} > 256); "
                "use applyGraduated or applyRules")
        color_ramp = self._ramp(ramp)
        sym_cls = self._symbol_cls(lyr)
        n = max(len(vals) - 1, 1)
        cats = []
        for i, v in enumerate(vals):
            sym = sym_cls.createSimple({})
            if colors and i < len(colors):
                sym.setColor(QColor(str(colors[i])))
            elif color_ramp is not None:
                sym.setColor(color_ramp.color(i / n))
            label = None
            if labels and i < len(labels):
                label = str(labels[i])
            elif v is None:
                label = "(NULL)"
            else:
                label = str(v)
            cats.append(QgsRendererCategory(v, sym, label))
        lyr.setRenderer(QgsCategorizedSymbolRenderer(str(field), cats))
        lyr.triggerRepaint()
        return self.legendSpec(lyr.id())

    def applyGraduated(self, layer=None, field=None, classes=5,
                       ramp=None, method="equal"):
        """数値フィールドの階級区分レンダラを作成し凡例を作る。"""
        lyr = self._find_layer(layer)
        if lyr is None:
            return self._err("layer not found")
        if not field:
            return self._err("field required")
        if not hasattr(lyr, "fields") or \
                lyr.fields().indexOf(str(field)) < 0:
            return self._err(f"field not found: {field!r} "
                             f"(have: {[f.name() for f in lyr.fields()]})")
        nums = sorted(v for v in
                      (f[str(field)] for f in lyr.getFeatures())
                      if isinstance(v, (int, float))
                      and not isinstance(v, bool))
        if not nums:
            return self._err(f"no numeric values in field: {field!r}")
        classes = max(2, min(int(classes or 5), 20))
        method = str(method or "equal").lower()
        if method == "quantile":
            edges = [nums[0]]
            for i in range(1, classes):
                edges.append(nums[min(int(i * len(nums) / classes),
                                      len(nums) - 1)])
            edges.append(nums[-1])
        else:
            lo, hi = nums[0], nums[-1]
            step = (hi - lo) / classes if hi > lo else 1
            edges = [lo + step * i for i in range(classes + 1)]

        def fmt(v):
            return f"{v:g}" if isinstance(v, float) else str(v)

        color_ramp = self._ramp(ramp)
        sym_cls = self._symbol_cls(lyr)
        ranges = []
        for i in range(classes):
            lo_e, hi_e = edges[i], edges[i + 1]
            sym = sym_cls.createSimple({})
            if color_ramp is not None:
                sym.setColor(color_ramp.color(
                    i / max(classes - 1, 1)))
            ranges.append(QgsRendererRange(
                lo_e, hi_e, sym, f"{fmt(lo_e)} - {fmt(hi_e)}"))
        lyr.setRenderer(
            QgsGraduatedSymbolRenderer(str(field), ranges))
        lyr.triggerRepaint()
        return self.legendSpec(lyr.id())

    @staticmethod
    def _width_unit(name):
        """単位名 → QgsUnitTypes.RenderUnit。"""
        m = {
            "mm": "RenderMillimeters",
            "pixels": "RenderPixels", "px": "RenderPixels",
            "map_units": "RenderMapUnits",
            "meters": "RenderMetersInMapUnits",
            "m": "RenderMetersInMapUnits",
        }
        attr = m.get(str(name or "mm").lower(), m["mm"])
        try:
            return getattr(QgsUnitTypes, attr)
        except AttributeError:
            return getattr(QgsUnitTypes.RenderUnit, attr)

    @staticmethod
    def _set_sym_width(sym, width, unit_name="mm"):
        """シンボル各レイヤへ幅を設定(線=setWidth、塗り輪郭=setStrokeWidth)。"""
        unit = LegendViewBridge._width_unit(unit_name)
        for i in range(sym.symbolLayerCount()):
            sl = sym.symbolLayer(i)
            if hasattr(sl, "setWidth"):
                sl.setWidth(float(width))
                if hasattr(sl, "setWidthUnit"):
                    sl.setWidthUnit(unit)
            if hasattr(sl, "setStrokeWidth"):
                sl.setStrokeWidth(float(width))
                if hasattr(sl, "setStrokeWidthUnit"):
                    sl.setStrokeWidthUnit(unit)

    def applyRules(self, layer=None, rules=None, else_label=None):
        """ルールベースレンダラを作成し凡例を作る。

        rules の各 spec: {"filter", "label", "color",
          "width", "width_unit", "min_scale", "max_scale"}
        filter は min_scale/max_scale 指定時に省略可。
        """
        lyr = self._find_layer(layer)
        if lyr is None:
            return self._err("layer not found")
        if not rules:
            return self._err(
                "rules required: "
                "[{\"filter\": \"\\\"f\\\" > 0\", \"label\": \"..\", "
                "\"color\": \"#rrggbb\"}]")
        sym_cls = self._symbol_cls(lyr)
        root = QgsRuleBasedRenderer.Rule(None)
        for spec in rules:
            if not isinstance(spec, dict):
                return self._err(f"invalid rule: {spec!r}")
            has_scale = (spec.get("min_scale") is not None
                         or spec.get("max_scale") is not None)
            if not spec.get("filter") and not has_scale:
                return self._err(
                    f"invalid rule (need 'filter' or scale): {spec!r}")
            sym = sym_cls.createSimple({})
            if spec.get("color"):
                sym.setColor(QColor(str(spec["color"])))
            if spec.get("width") is not None:
                self._set_sym_width(
                    sym, spec["width"], spec.get("width_unit"))
            # ctor位置引数はビルドにより型解釈が揺れるため setter で設定
            rule = QgsRuleBasedRenderer.Rule(sym)
            if spec.get("filter"):
                rule.setFilterExpression(str(spec["filter"]))
            if spec.get("label") is not None:
                rule.setLabel(str(spec["label"]))
            elif spec.get("filter"):
                rule.setLabel(str(spec["filter"]))
            for spec_key, setter in (("min_scale", "setMinimumScale"),
                                     ("max_scale", "setMaximumScale")):
                if spec.get(spec_key) is not None:
                    fn = getattr(rule, setter, None)
                    if callable(fn):
                        try:
                            fn(int(spec[spec_key]))
                        except TypeError:
                            fn(float(spec[spec_key]))
            root.appendChild(rule)
        if else_label:
            sym = sym_cls.createSimple({})
            else_rule = QgsRuleBasedRenderer.Rule(sym)
            else_rule.setLabel(str(else_label))
            is_else = getattr(else_rule, "setIsElse", None)
            if callable(is_else):
                is_else(True)
            root.appendChild(else_rule)
        lyr.setRenderer(QgsRuleBasedRenderer(root))
        lyr.triggerRepaint()
        return self.legendSpec(lyr.id())

    def applySingleSymbol(self, layer=None, color=None):
        """単一シンボルレンダラに戻す。"""
        lyr = self._find_layer(layer)
        if lyr is None:
            return self._err("layer not found")
        sym = self._symbol_cls(lyr).createSimple({})
        if color:
            sym.setColor(QColor(str(color)))
        lyr.setRenderer(QgsSingleSymbolRenderer(sym))
        lyr.triggerRepaint()
        return self.legendSpec(lyr.id())

    def addLayoutLegend(self, layout=None, title="凡例", x=None, y=None,
                        w=None, h=None, layers=None, linked_map=None,
                        filter_by_map=False):
        """印刷レイアウトに凡例アイテムを追加する。"""
        lay, err = self._find_layout(layout, create=layout is None)
        if err:
            return err
        legend = QgsLayoutItemLegend(lay)
        if title:
            legend.setTitle(str(title))
        lay.addLayoutItem(legend)
        err = self._legend_layers(legend, layers)
        if err:
            lay.removeLayoutItem(legend)
            return self._err(err)
        if linked_map is not None:
            target = None
            for it in lay.items():
                if not isinstance(it, QgsLayoutItemMap):
                    continue
                if str(linked_map) in (it.id(), it.displayName(), ""):
                    target = it
                    break
                if target is None:
                    target = it
            if target is None:
                lay.removeLayoutItem(legend)
                return self._err(
                    f"map item not found: {linked_map!r}")
            legend.setLinkedMap(target)
            if filter_by_map:
                legend.setLegendFilterByMapEnabled(True)
        pos_x = float(x) if x is not None else 10.0
        pos_y = float(y) if y is not None else 10.0
        if w is None or h is None:
            legend.setResizeToContents(True)
            legend.attemptSetSceneRect(QRectF(pos_x, pos_y,
                                              float(w or 60),
                                              float(h or 80)))
            legend.refreshItemSize()
        else:
            legend.attemptSetSceneRect(
                QRectF(pos_x, pos_y, float(w), float(h)))
        if not legend.id():
            legend.setId(f"legend_{int(time.time())}")
        return self._ok({
            "layout": lay.name(),
            "legend_id": legend.id(),
            "title": legend.title(),
            "pos": [legend.scenePos().x(), legend.scenePos().y()],
            "size": [legend.rect().width(), legend.rect().height()],
            "items": self._legend_item_labels(legend),
        })

    def exportLegendImage(self, path=None, layers=None, title="凡例",
                          dpi=96):
        """凡例だけの画像(PNG)を出力する。"""
        mgr = QgsProject.instance().layoutManager()
        name = "__geo_legend_export__"
        old = mgr.layoutByName(name)
        if old is not None:
            mgr.removeLayout(old)
        lay = QgsPrintLayout(QgsProject.instance())
        lay.initializeDefaults()
        lay.setName(name)
        mgr.addLayout(lay)
        try:
            legend = QgsLayoutItemLegend(lay)
            if title:
                legend.setTitle(str(title))
            lay.addLayoutItem(legend)
            err = self._legend_layers(legend, layers)
            if err:
                return self._err(err)
            legend.setResizeToContents(True)
            legend.attemptSetSceneRect(QRectF(2, 2, 60, 80))
            legend.refreshItemSize()
            rect = legend.rect()
            page = lay.pageCollection().page(0)
            page.setPageSize(QgsLayoutSize(
                rect.width() + 4, rect.height() + 4,
                QgsUnitTypes.LayoutUnit.LayoutMillimeters))
            if not path:
                path = os.path.join(
                    tempfile.gettempdir(),
                    f"legend_{int(time.time())}.png")
            path = str(path)
            settings = QgsLayoutExporter.ImageExportSettings()
            settings.dpi = float(dpi or 96)
            st = QgsLayoutExporter(lay).exportToImage(path, settings)
            ok = (int(st) == 0 and os.path.exists(path))
            return self._ok({
                "path": path, "exported": ok,
                "status": str(st),
                "bytes": os.path.getsize(path) if ok else 0,
                "items": self._legend_item_labels(legend),
            }) if ok else self._err(f"export failed: {st}")
        finally:
            mgr.removeLayout(lay)
