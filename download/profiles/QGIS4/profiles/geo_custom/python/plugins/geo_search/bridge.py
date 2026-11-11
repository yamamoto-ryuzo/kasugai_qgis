# -*- coding: utf-8 -*-
"""geo_search を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、qgis_live_driver の
bridge_call コマンド(ファイルJSONL / REST /api/cmd / MCP qgis_bridge_call)
から ``qgis.utils.plugins['geo_search'].bridge.<method>(*args)`` が
プロセス内で直接呼ばれる。WebChannel は通らないためレンダラー飢餓の
影響を受けない(Qt Widgets プラグインにはWebChannel自体が無い)。

各メソッドは JSON 文字列を返す(bridge_call 側で構造化される)。
ドメインエラー(タブ不明・ウィジェット無し等)は ``{"ok": false, "error": ...}``
を返し、予期しない例外は呼び出し元(driver の {"error": traceback})に委ねる。
いずれも GUI スレッドで同期的に実行される。検索はプラグインの検索ボタン
押下と同じ経路(show_features)を通るため、巨大レイヤではその分ブロックする。

例(MCP): qgis_bridge_call pluginId="geo_search" method="search" args=["テスト"]
"""

import inspect
import json

from qgis.PyQt.QtCore import QCoreApplication

from .constants import DEFAULT_GROUP_NAME


def _jsonable(v):
    """QgsFeatureの属性値などをJSON化可能な値に変換する。"""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    try:
        from qgis.core import NULL
        if v is NULL:
            return None
    except Exception:  # nosec B110  # 設計上の許容
        pass
    try:
        from qgis.PyQt.QtCore import QDate, QDateTime, QTime, QByteArray, Qt
        if isinstance(v, (QDate, QDateTime, QTime)):
            return v.toString(Qt.DateFormat.ISODate)
        if isinstance(v, QByteArray):
            return bytes(v).decode("utf-8", "replace")
    except Exception:  # nosec B110  # 設計上の許容
        pass
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    try:
        return str(v)
    except Exception:
        return repr(v)


def _tr(context, message):
    """Translate a UI message via the plugin's installed translators."""
    try:
        from qgis.PyQt.QtCore import QCoreApplication
        return QCoreApplication.translate(context, message)
    except Exception:
        return message


class GeoSearchBridge:
    """``plugins['geo_search'].bridge`` にぶら下げるAI向けAPI。

    保有するのはプラグインインスタンスへの参照のみ。ダイアログが
    再作成(on_project_saved等)されても最新の状態を読みに行く。
    """

    # AI向け自己記述。ドライバの describe_plugins カタログが pluginInfo()
    # 経由でこれを集約する。メソッド仕様は signature/docstring から
    # 自動生成し、METHOD_DOCS で補足する。
    NAME = "地図検索 (geo_search)"
    SUMMARY = ("レイヤ内の地物を属性値で検索し、結果一覧の表示と"
               "地図ズーム・地物選択を行う。検索対象は設定済みの検索タブ"
               "(カレントレイヤ/全レイヤ/プロジェクト定義)で決まる。")
    WHEN_TO_USE = [
        "地名・施設名・市区町村名など属性値で地物を探したい",
        "検索結果へ地図をズームしたい・結果地物を選択したい",
        "検索タブ(検索対象レイヤ/フィールドの定義)を確認・切り替え・追加/削除したい",
        "マップテーマ(レイヤ表示状態プリセット)の一覧・切替・追加表示をしたい",
        "現在の表示状態をユーザーテーマとして保存/復元したい",
        "検索設定(geo_search_json・タブ設定)を確認・変更したい",
        "地番検索(完全一致/あいまい・字コード)や所有者検索(対象フィールド・一致方式)を使いたい",
    ]
    METHOD_DOCS = {
        "search": {
            "description":
                "検索を実行して結果(レイヤ別・属性・centroid)を返し、"
                "結果へズーム+選択する。queryはstr(先頭入力欄)/"
                "list(各入力欄)/dict({フィールド名or ViewName: 値})。"
                "tabはindex/タイトル/{group,title}、省略時は現在タブ。",
            "example": {"method": "search",
                        "args": [{"市区町村名": "渋谷区"}, "市区町村"]},
        },
        "listTabs": {
            "description":
                "検索タブの一覧(index/グループ/タイトル/対象レイヤ/"
                "検索フィールド/現在選択)を返す。",
            "example": {"method": "listTabs", "args": []},
        },
        "selectTab": {
            "description":
                "検索タブを選択する。tabはindex/タイトル/{group,title}。",
            "example": {"method": "selectTab", "args": ["市区町村"]},
        },
        "results": {
            "description":
                "直近の検索結果を再取得する(再検索はしない)。",
            "example": {"method": "results", "args": []},
        },
        "zoom": {
            "description":
                "検索結果の地物へズームする。feature_ids省略時は"
                "指定タブ(既定0)の全件。",
            "example": {"method": "zoom", "args": [[34600], 0]},
        },
        "openDialog": {
            "description": "検索ダイアログを開く/前面に出す。",
            "example": {"method": "openDialog", "args": []},
        },
        "closeDialog": {
            "description": "検索・結果ダイアログを閉じる。",
            "example": {"method": "closeDialog", "args": []},
        },
        "status": {
            "description":
                "現在のタブ・入力値・結果概要などの実行時状態を返す。",
            "example": {"method": "status", "args": []},
        },
        "searchOptions": {
            "description":
                "検索オプション取得/設定。pan_mode(0フィット/1パン/4固定縮尺"
                "/5アニメーション/6選択のみ)・fixed_scale・show_layer_name"
                "を全タブへ適用。",
            "example": {"method": "searchOptions",
                        "args": [{"pan_mode": 6}]},
        },
        "tabOptions": {
            "description":
                "タブ固有コントロール取得/設定。地番検索: match=exact|fuzzy"
                "・aza_code(字コード選択)。所有者検索: fields=[対象名]・"
                "match_mode=partial|forward。",
            "example": {"method": "tabOptions",
                        "args": [None, {"match": "fuzzy"}]},
        },
        "suggest": {
            "description":
                "検索フィールドのユニーク値一覧(サジェスト相当)を返す。",
            "example": {"method": "suggest",
                        "args": ["市区町村", "市区町村名"]},
        },
        "listThemes": {
            "description":
                "マップテーマ一覧・グループ・現在選択・追加表示モードを返す。",
            "example": {"method": "listThemes", "args": []},
        },
        "applyTheme": {
            "description":
                "マップテーマを適用する。additive指定で追加表示モードも変更。",
            "example": {"method": "applyTheme",
                        "args": ["検索前", False]},
        },
        "themeAdditive": {
            "description":
                "テーマ追加表示モード取得/設定(True=現在表示にunion追加)。",
            "example": {"method": "themeAdditive", "args": [True]},
        },
        "saveUserTheme": {
            "description":
                "現在の表示状態をユーザーテーマJSONに保存"
                "(path省略時<プロジェクトdir>/themes/)。",
            "example": {"method": "saveUserTheme", "args": []},
        },
        "loadUserTheme": {
            "description": "ユーザーテーマJSONを読み込んで適用する。",
            "example": {"method": "loadUserTheme",
                        "args": ["C:/path/to/x.usertheme.json"]},
        },
        "getSettings": {
            "description":
                "設定由来(setting.json/プロジェクト変数/geo_search_json)"
                "と値を返す。",
            "example": {"method": "getSettings", "args": []},
        },
        "setSettings": {
            "description":
                "geo_search_json パスを設定(プロジェクト変数+env)。"
                "既定でダイアログ再構築。",
            "example": {"method": "setSettings",
                        "args": [{"geo_search_json": "C:/conf/tabs.json"}]},
        },
        "tabSetting": {
            "description": "指定タブの設定JSON(由来情報含む)を返す。",
            "example": {"method": "tabSetting", "args": ["市区町村"]},
        },
        "addTabFromCurrentLayer": {
            "description":
                "アクティブレイヤを検索タブとしてプロジェクト変数に追加"
                "しダイアログ再構築。",
            "example": {"method": "addTabFromCurrentLayer", "args": []},
        },
        "removeTab": {
            "description":
                "検索タブを設定ソース(setting.json/geo_search_json/"
                "プロジェクト変数)から削除し再構築。注意:設定を実際に変更する。",
            "example": {"method": "removeTab", "args": ["タブ名"]},
        },
        "reloadDialog": {
            "description": "検索ダイアログを再構築(設定変更の反映用)。",
            "example": {"method": "reloadDialog", "args": []},
        },
        "openSettings": {
            "description":
                "設定ダイアログ(geo_search_json適用・ユーザテーマ保存/読込)"
                "を非modalで開く。",
            "example": {"method": "openSettings", "args": []},
        },
        "setTabSetting": {
            "description":
                "既存タブの設定JSONを更新して由来ソースへ書き戻す"
                "(configボタンの編集ダイアログ相当)。configはdictで"
                "既存設定へマージする。注意:設定を実際に変更する。",
            "example": {"method": "setTabSetting",
                        "args": ["市区町村",
                                 {"SearchField": {"Field": "name"}}]},
        },
        "addTab": {
            "description":
                "任意のタブ定義dictを検索タブとして追加する。"
                "targetは 'project'(既定)/'setting_json'/'geo_search_json'。",
            "example": {"method": "addTab",
                        "args": [{"Title": "新規", "group": "各種レイヤ",
                                  "Layer": {"LayerType": "Name",
                                            "Name": "layer1"},
                                  "SearchField": {}, "ViewFields": []}]},
        },
        "resultPage": {
            "description":
                "結果ダイアログの表示ページを取得/設定する(1始まり)。",
            "example": {"method": "resultPage", "args": [2]},
        },
        "resultDisplayMode": {
            "description":
                "結果ダイアログの表示モードを取得/設定する"
                "('table'/'form')。",
            "example": {"method": "resultDisplayMode", "args": ["form"]},
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

    def _flat_tabs(self):
        """検索タブをフラット列挙する(グループ化UIの有無を吸収)。

        各entry: {"index", "group", "main_index", "child_index", "feature"}
        """
        p = self._plugin
        dlg = self._dialog()
        groups = getattr(dlg, "tab_groups", None) if dlg is not None else None
        entries = []
        if groups:
            for gi, gname in enumerate(groups.keys()):
                feats = (p._search_group_features or {}).get(gname, [])
                for ci, f in enumerate(feats):
                    entries.append({
                        "index": len(entries), "group": gname,
                        "main_index": gi, "child_index": ci,
                        "feature": f,
                    })
        else:
            for ci, f in enumerate(getattr(p, "_search_features", []) or []):
                entries.append({
                    "index": ci, "group": None,
                    "main_index": ci, "child_index": ci,
                    "feature": f,
                })
        return entries

    def _find_tab(self, tab):
        """tab指定(None/int/タイトルstr/{group,title}dict)をタブentryに解決する。"""
        entries = self._flat_tabs()
        if not entries:
            return None
        if tab is None:
            cur = getattr(self._plugin, "current_feature", None)
            for e in entries:
                if e["feature"] is cur:
                    return e
            return entries[0]
        if isinstance(tab, bool):
            return None
        if isinstance(tab, int):
            return entries[tab] if -len(entries) <= tab < len(entries) else None
        if isinstance(tab, dict):
            want_g, want_t = tab.get("group"), tab.get("title")
            for e in entries:
                if want_t is not None and getattr(e["feature"], "title", None) != want_t:
                    continue
                if want_g is not None and e["group"] != want_g:
                    continue
                return e
            return None
        s = str(tab)
        for e in entries:  # タイトル完全一致を優先
            if getattr(e["feature"], "title", None) == s:
                return e
        for e in entries:  # 部分一致フォールバック
            if s in str(getattr(e["feature"], "title", "") or ""):
                return e
        return None

    def _activate(self, entry):
        """タブを選択し plugin.current_feature を切り替える。"""
        p = self._plugin
        dlg = self._dialog()
        groups = getattr(dlg, "tab_groups", None) or {}
        if entry["group"] is not None and entry["group"] in groups:
            mi, ci = entry["main_index"], entry["child_index"]
            try:
                if dlg.tabWidget.currentIndex() != mi:
                    dlg.tabWidget.setCurrentIndex(mi)   # → change_tab_group
                else:
                    p.change_tab_group(mi)              # 同indexは手動同期
            except Exception:  # nosec B110  # 設計上の許容
                pass
            child = groups[entry["group"]]
            try:
                if child.currentIndex() != ci:
                    child.setCurrentIndex(ci)           # → change_search_feature
            except Exception:  # nosec B110  # 設計上の許容
                pass
            if p.current_feature is not entry["feature"]:
                p.change_search_feature(ci)
        else:
            idx = entry["child_index"]
            try:
                if dlg.tabWidget.currentIndex() != idx:
                    dlg.tabWidget.setCurrentIndex(idx)  # → change_search_feature
            except Exception:  # nosec B110  # 設計上の許容
                pass
            if p.current_feature is not entry["feature"]:
                p.change_search_feature(idx)
        return p.current_feature

    def _set_widget_values(self, feat, query):
        """検索入力ウィジェットへ値を設定する。

        query: str → 先頭ウィジェットへ
               list → 各ウィジェットへ順に
               dict → {"フィールド名 or ViewName or 番号": 値} を対応ウィジェットへ
        いずれも最初に全ウィジェットをクリアする(前回入力の残存防止)。
        """
        widgets = list(getattr(getattr(feat, "widget", None),
                               "search_widgets", []) or [])
        if not widgets:
            return self._err("no search widgets on current tab")
        for w in widgets:
            try:
                w.setText("")
            except Exception:  # nosec B110  # 設計上の許容
                pass
        unmatched = []
        if isinstance(query, dict):
            fields = getattr(feat, "fields", []) or []
            # ウィジェットの表示ラベル("市区町村名: " 等)でも照合できるようにする。
            # 全フィールド検索(SearchField={})はsetting側が空dictで名前を持たないため
            # ラベル "All" が実質の名前になる
            labels = getattr(getattr(feat, "widget", None), "labels", []) or []
            label_texts = []
            for lb in labels:
                try:
                    label_texts.append(str(lb.text()).rstrip(": ").strip())
                except Exception:
                    label_texts.append("")
            for k, v in query.items():
                matched = False
                key = str(k)
                for i in range(len(widgets)):
                    names = set()
                    field = fields[i] if i < len(fields) else None
                    if isinstance(field, dict):
                        for fk in ("Field", "ViewName"):
                            fv = field.get(fk)
                            if fv:
                                names.add(str(fv))
                        if not field or field.get("all"):
                            names.update(("all", "All"))
                    if i < len(label_texts) and label_texts[i]:
                        names.add(label_texts[i])
                    if key in names:
                        widgets[i].setText("" if v is None else str(v))
                        matched = True
                        break
                if not matched:
                    try:
                        widgets[int(k)].setText("" if v is None else str(v))
                        matched = True
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                if not matched:
                    unmatched.append(key)
        elif isinstance(query, (list, tuple)):
            for w, v in zip(widgets, query):
                w.setText("" if v is None else str(v))
        else:
            widgets[0].setText("" if query is None else str(query))
        if unmatched:
            return self._err(f"unmatched field keys: {unmatched}")
        return None

    def _serialize_result_tabs(self, feat, max_features):
        """result_dialog._tabs をJSON構造に変換する。返値 (layers, total)。"""
        rd = getattr(feat, "result_dialog", None)
        tabs = getattr(rd, "_tabs", []) if rd is not None else []
        try:
            cap = max(0, int(max_features))
        except Exception:
            cap = 200
        out, total = [], 0
        for t in tabs or []:
            feats = list(t.get("features") or [])
            layer = t.get("layer")
            fields = t.get("fields") or []
            total += len(feats)
            names = [f.name() if hasattr(f, "name") else str(f)
                     for f in fields]
            items = [self._feature_to_dict(f, layer, names)
                     for f in feats[:cap]]
            out.append({
                "layer": layer.name() if hasattr(layer, "name") else None,
                "layer_id": (layer.id() if layer is not None
                             and hasattr(layer, "id") else None),
                "count": len(feats),
                "features": items,
            })
        return out, total

    @staticmethod
    def _feature_to_dict(f, layer, names):
        attrs = {}
        try:
            vals = f.attributes() or []
            lfields = list(layer.fields()) if layer is not None else []
            use = names or [lf.name() for lf in lfields]
            idx_by_name = {lf.name(): i for i, lf in enumerate(lfields)}
            for n in use:
                i = idx_by_name.get(n)
                if i is not None and i < len(vals):
                    attrs[n] = _jsonable(vals[i])
        except Exception:  # nosec B110  # 設計上の許容
            pass
        entry = {"id": f.id(), "attrs": attrs}
        try:
            g = f.geometry()
            if g is not None and not g.isEmpty():
                pt = g.centroid().asPoint()
                entry["centroid"] = [pt.x(), pt.y()]
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return entry

    def _zoom_to_results(self, feat):
        """全結果タブの地物を選択し、結合bboxへズームする。"""
        from qgis.core import (QgsRectangle, QgsCoordinateTransform,
                               QgsProject)
        canvas = self._plugin.iface.mapCanvas()
        try:
            canvas_crs = canvas.mapSettings().destinationCrs()
        except Exception:  # nosec B110  # 設計上の許容
            canvas_crs = None
        project = QgsProject.instance()
        rd = getattr(feat, "result_dialog", None)
        tabs = getattr(rd, "_tabs", []) if rd is not None else []
        rect = None
        for t in tabs or []:
            layer = t.get("layer")
            # レイヤCRS→キャンバスCRSの変換(違えば)
            transform = None
            if layer is not None and canvas_crs is not None:
                try:
                    layer_crs = layer.crs()
                    if (layer_crs is not None and layer_crs.isValid()
                            and layer_crs != canvas_crs):
                        transform = QgsCoordinateTransform(
                            layer_crs, canvas_crs, project)
                except Exception:  # nosec B110  # 設計上の許容
                    transform = None
            ids = []
            for f in (t.get("features") or []):
                try:
                    ids.append(f.id())
                    g = f.geometry()
                    if g is None or g.isEmpty():
                        continue
                    r = g.boundingBox()
                    if transform is not None:
                        r = transform.transformBoundingBox(r)
                    if rect is None:
                        rect = QgsRectangle(r)
                    else:
                        rect.combineExtentWith(r)
                except Exception:  # nosec B112  # 設計上の許容
                    continue
            if layer is not None and ids:
                try:
                    layer.selectByIds(ids)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        if rect is None or rect.isNull():
            return False
        if rect.width() == 0 and rect.height() == 0:
            canvas.setCenter(rect.center())  # 点のみ: 中心へパン
        else:
            canvas.zoomToFeatureExtent(rect)
        canvas.refresh()
        return True

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

    # ---------- bridge メソッド(JSON文字列を返す) ----------

    def pluginInfo(self):
        """プラグインの自己記述(id/summary/when_to_use/methods)を返す。

        describe_plugins カタログがこれを集約する。AIは summary と
        when_to_use で利用可否を判断し、methods の signature/example
        に従って bridge_call で呼ぶ。
        """
        dlg = self._dialog()
        return self._ok({
            "id": "geo_search",
            "name": self.NAME,
            "summary": self.SUMMARY,
            "when_to_use": list(self.WHEN_TO_USE),
            "invoke": {"type": "bridge_call", "plugin_id": "geo_search",
                       "method": "<method>", "args": []},
            "methods": self._method_catalog(),
            "state": {
                "dialog": dlg is not None,
                "dialogVisible": bool(dlg is not None and dlg.isVisible()),
                "tabCount": len(self._flat_tabs()),
            },
        })

    def status(self):
        p = self._plugin
        dlg = self._dialog()
        cur = getattr(p, "current_feature", None)
        entries = self._flat_tabs()
        cur_e = next((e for e in entries if e["feature"] is cur), None)
        inputs = []
        if cur is not None:
            for w in getattr(getattr(cur, "widget", None),
                             "search_widgets", []) or []:
                try:
                    inputs.append(w.text())
                except Exception:
                    inputs.append(None)
        result_tabs = []
        rd = getattr(cur, "result_dialog", None) if cur is not None else None
        for t in getattr(rd, "_tabs", []) or []:
            layer = t.get("layer")
            result_tabs.append({
                "layer": layer.name() if hasattr(layer, "name") else None,
                "count": len(t.get("features") or []),
            })
        return self._ok({
            "dialog": dlg is not None,
            "dialogVisible": bool(dlg is not None and dlg.isVisible()),
            "resultVisible": bool(rd is not None and rd.isVisible()),
            "currentTab": ({
                "index": cur_e["index"], "group": cur_e["group"],
                "title": getattr(cur, "title", None),
            } if cur_e else None),
            "inputs": inputs,
            "resultTabs": result_tabs,
        })

    def listTabs(self):
        out = []
        for e in self._flat_tabs():
            f = e["feature"]
            s = getattr(f, "setting", {}) or {}
            layer = s.get("Layer")
            out.append({
                "index": e["index"],
                "group": e["group"],
                "title": getattr(f, "title", s.get("Title")),
                "layer": ({
                    "type": layer.get("LayerType"),
                    "name": layer.get("Name"),
                } if isinstance(layer, dict) else None),
                "searchFields": _jsonable(getattr(f, "fields", []) or []),
                "current": self._plugin.current_feature is f,
            })
        return self._ok({"tabs": out})

    def selectTab(self, tab=None):
        if self._dialog() is None:
            return self._err("dialog not initialized")
        entry = self._find_tab(tab)
        if entry is None:
            return self._err(f"tab not found: {tab!r} "
                             f"(use listTabs to enumerate)")
        feat = self._activate(entry)
        return self._ok({
            "selected": {
                "index": entry["index"], "group": entry["group"],
                "title": getattr(entry["feature"], "title", None),
            },
            "current": getattr(feat, "title", None),
        })

    def search(self, query="", tab=None, show=True, zoom=True,
               max_features=200, options=None):
        """検索を実行する(検索ボタン押下と同じ show_features 経路)。

        query: str=先頭入力欄 / list=各入力欄 / dict={フィールド名 or ViewName: 値}
        tab:   int(フラットindex) / タイトルstr / {"group","title"}dict。省略=現在タブ
        show:  Falseなら結果ダイアログを出さない
        zoom:  Trueなら結果bboxへズーム+地物選択(デフォルトTrue)
        options: {"pan_mode","fixed_scale","show_layer_name"} を事前適用
        """
        if options:
            applied = self._apply_search_options(options)
            if isinstance(applied, str):
                return applied
        p = self._plugin
        if self._dialog() is None:
            return self._err("dialog not initialized (run openDialog first "
                             "or check setting.json)")
        if tab is not None:
            entry = self._find_tab(tab)
            if entry is None:
                return self._err(f"tab not found: {tab!r} "
                                 "(use listTabs to enumerate)")
            self._activate(entry)
        feat = getattr(p, "current_feature", None)
        if feat is None:
            return self._err("no active search feature")
        err = self._set_widget_values(feat, query)
        if err is not None:
            return err
        feat.show_features()
        layers, total = self._serialize_result_tabs(feat, max_features)
        zoomed = self._zoom_to_results(feat) if zoom and total else False
        if not show:
            try:
                feat.result_dialog.hide()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        cur = self._find_tab(None)
        return self._ok({
            "tab": ({
                "index": cur["index"], "group": cur["group"],
                "title": getattr(cur["feature"], "title", None),
            } if cur else None),
            "total": total,
            "layers": layers,
            "zoomed": zoomed,
        })

    def results(self, max_features=200):
        """直近の検索結果を返す(再検索はしない)。"""
        feat = getattr(self._plugin, "current_feature", None)
        if feat is None:
            return self._err("no active search feature")
        layers, total = self._serialize_result_tabs(feat, max_features)
        rd = getattr(feat, "result_dialog", None)
        return self._ok({
            "total": total,
            "layers": layers,
            "resultVisible": bool(rd is not None and rd.isVisible()),
        })

    def zoom(self, feature_ids=None, tab_index=0):
        """結果地物へズームする。feature_ids省略時はそのタブの全件。"""
        feat = getattr(self._plugin, "current_feature", None)
        if feat is None:
            return self._err("no active search feature")
        rd = getattr(feat, "result_dialog", None)
        tabs = getattr(rd, "_tabs", []) if rd is not None else []
        try:
            ti = int(tab_index or 0)
        except Exception:
            ti = 0
        if ti < 0 or ti >= len(tabs):
            return self._err(f"result tab_index out of range: {ti} "
                             f"(tabs={len(tabs)})")
        layer = tabs[ti].get("layer") or getattr(feat, "layer", None)
        ids = feature_ids
        if not ids:
            ids = [f.id() for f in (tabs[ti].get("features") or [])]
        elif not isinstance(ids, (list, tuple)):
            ids = [ids]
        feat.zoom_features(ids, layer=layer)
        return self._ok({
            "zoomed": len(ids),
            "layer": layer.name() if hasattr(layer, "name") else None,
        })

    # ---------- 検索オプション / テーマ / 設定 / タブ管理 ----------

    _PAN_MODE_INDEX = [0, 1, 4, 5, 6]  # panModeComboBox index→内部mode

    def _all_features(self):
        """全検索フィーチャ(フラット+グループ)を重複なく返す。"""
        p = self._plugin
        seen, out = set(), []
        for f in getattr(p, "_search_features", []) or []:
            if id(f) not in seen:
                seen.add(id(f))
                out.append(f)
        for flist in (getattr(p, "_search_group_features", {}) or {}).values():
            for f in flist or []:
                if id(f) not in seen:
                    seen.add(id(f))
                    out.append(f)
        return out

    def _apply_search_options(self, options):
        """pan_mode/fixed_scale/show_layer_name を全フィーチャへ反映し、
        ダイアログの対応コントロールも同期する。"""
        opts = dict(options or {})
        applied = {}
        if "pan_mode" in opts:
            try:
                m = int(opts["pan_mode"])
            except Exception:
                return self._err(f"invalid pan_mode: {opts['pan_mode']!r}")
            if m not in self._PAN_MODE_INDEX:
                return self._err(
                    f"invalid pan_mode {m}: allowed {self._PAN_MODE_INDEX} "
                    "(0=選択フィット/1=中心パン/4=固定縮尺/5=アニメーション/6=選択のみ)")
            for f in self._all_features():
                setattr(f, "pan_mode", m)
            cmb = getattr(self._dialog(), "panModeComboBox", None)
            if cmb is not None:
                try:
                    cmb.blockSignals(True)
                    cmb.setCurrentIndex(self._PAN_MODE_INDEX.index(m))
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                finally:
                    try:
                        cmb.blockSignals(False)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
            applied["pan_mode"] = m
        if "fixed_scale" in opts:
            v = opts["fixed_scale"]
            if v is not None:
                try:
                    v = int(str(v).replace(",", "").replace("1:", ""))
                except Exception:
                    return self._err(f"invalid fixed_scale: {opts['fixed_scale']!r}")
            for f in self._all_features():
                setattr(f, "fixed_scale", v)
            cmb = getattr(self._dialog(), "scaleComboBox", None)
            if cmb is not None:
                try:
                    cmb.blockSignals(True)
                    cmb.setCurrentText(
                        QCoreApplication.translate("Dialog", "Auto (unspecified)") if v is None else f"1:{v:,}")
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                finally:
                    try:
                        cmb.blockSignals(False)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
            applied["fixed_scale"] = v
        if "show_layer_name" in opts:
            b = bool(opts["show_layer_name"])
            for f in self._all_features():
                setattr(f, "show_layer_name", b)
            cbx = getattr(self._dialog(), "showLayerCheckBox", None)
            if cbx is not None:
                try:
                    cbx.setChecked(b)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            applied["show_layer_name"] = b
        return applied

    def searchOptions(self, options=None):
        """検索オプションを取得/設定する(設定時は全タブへ適用)。

        options(dict):
          pan_mode: 0=選択地物にフィット / 1=中心へパン(縮尺維持) /
                    4=固定縮尺 / 5=アニメーションパン / 6=選択のみ
          fixed_scale: 固定縮尺の分母(例 5000)。Noneで自動
          show_layer_name: 結果の「レイヤ表示」チェック相当
        """
        if options:
            applied = self._apply_search_options(options)
            if isinstance(applied, str):
                return applied
        cur = self._find_tab(None)
        feat = cur["feature"] if cur else None
        dlg = self._dialog()
        cmb = getattr(dlg, "panModeComboBox", None)
        scale_cmb = getattr(dlg, "scaleComboBox", None)
        cbx = getattr(dlg, "showLayerCheckBox", None)
        return self._ok({
            "pan_mode": getattr(feat, "pan_mode", None),
            "pan_modes": {
                "0": QCoreApplication.translate("Dialog", "Zoom to fit selection"),
                "1": QCoreApplication.translate("Dialog", "Pan to center (keep zoom)"),
                "4": QCoreApplication.translate("Dialog", "Show at fixed scale"),
                "5": QCoreApplication.translate("Dialog", "Animated pan"),
                "6": QCoreApplication.translate("Dialog", "Select only (no view change)"),
            },
            "fixed_scale": getattr(feat, "fixed_scale", None),
            "show_layer_name": getattr(feat, "show_layer_name", None),
            "ui": {
                "panModeIndex": (cmb.currentIndex()
                                 if cmb is not None else None),
                "scaleText": (scale_cmb.currentText()
                              if scale_cmb is not None else None),
                "showLayer": (cbx.isChecked()
                              if cbx is not None else None),
            },
        })

    def tabOptions(self, tab=None, options=None):
        """タブ固有の検索コントロールを取得/設定する。

        options(dict、設定したいキーのみ):
          match: "exact"|"fuzzy"          地番検索の完全一致/あいまい
          fields: ["ViewName", ...]       所有者検索の対象フィールド
          match_mode: "partial"|"forward" 所有者検索の部分一致/前方一致
          aza_code: "字コード"            地番コードテーブルの行選択
        """
        entry = self._find_tab(tab)
        if entry is None:
            return self._err(f"tab not found: {tab!r}")
        feat = self._activate(entry)
        widget = getattr(feat, "widget", None)
        if widget is None:
            return self._err("tab has no search widget")
        opts = dict(options or {})
        applied = {}
        # 地番検索: 完全一致/あいまい
        if hasattr(widget, "perfect_button") and "match" in opts:
            try:
                widget.perfect_button.setChecked(opts["match"] != "fuzzy")
                widget.about_button.setChecked(opts["match"] == "fuzzy")
                applied["match"] = opts["match"]
            except Exception as e:
                return self._err(f"set match failed: {e}")
        # 所有者検索: フィールド選択・一致方式
        if hasattr(widget, "check_list"):
            if "fields" in opts:
                want = {str(v) for v in (opts["fields"] or [])}
                for btn in widget.check_list:
                    try:
                        btn.setChecked(btn.text() in want)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                applied["fields"] = sorted(want)
            if "match_mode" in opts:
                try:
                    partial = opts["match_mode"] != "forward"
                    widget.forward_button.setChecked(partial)
                    widget.parts_button.setChecked(not partial)
                    applied["match_mode"] = opts["match_mode"]
                except Exception as e:
                    return self._err(f"set match_mode failed: {e}")
        # 地番検索: 字コードテーブル選択
        table = getattr(widget, "code_table", None)
        if table is not None and "aza_code" in opts:
            code = str(opts["aza_code"])
            hit = False
            for r in range(table.rowCount()):
                texts = []
                for c in range(table.columnCount()):
                    it = table.item(r, c)
                    texts.append(it.text() if it is not None else "")
                if code in texts or (texts and texts[0] == code):
                    try:
                        table.selectRow(r)  # → set_aza_code が入力欄へ反映
                        hit = True
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                    break
            if not hit:
                return self._err(f"aza_code not in code table: {code!r}")
            applied["aza_code"] = code
        # ---- 現在値 ----
        state = {"type": "text", "applied": applied}
        if hasattr(widget, "perfect_button"):
            state["type"] = "tiban"
            state["match"] = ("fuzzy" if widget.about_button.isChecked()
                              else "exact")
        if hasattr(widget, "check_list"):
            state["type"] = "owner"
            state["fields"] = [
                b.text() for b in widget.check_list if b.isChecked()]
            state["match_mode"] = (
                "partial" if widget.forward_button.isChecked()
                else "forward")
            state["available_fields"] = [
                b.text() for b in widget.check_list]
        if table is not None:
            rows = []
            for r in range(table.rowCount()):
                rows.append([
                    (table.item(r, c).text()
                     if table.item(r, c) is not None else "")
                    for c in range(table.columnCount())])
            state["code_table"] = rows
            sel = table.selectedItems()
            state["aza_code_selected"] = sel[0].text() if sel else None
        return self._ok(state)

    def suggest(self, tab=None, field=None, limit=200):
        """検索フィールドのユニーク値一覧(サジェスト相当)を返す。

        field: ViewNameまたはField名。省略時は全フィールド分を返す。
        """
        entry = self._find_tab(tab)
        if entry is None:
            return self._err(f"tab not found: {tab!r}")
        feat = entry["feature"]
        layer = getattr(feat, "layer", None)
        if layer is None:
            return self._err("tab has no layer")
        from .utils import unique_values
        out = {}
        for fdef in getattr(feat, "fields", []) or []:
            fname = fdef.get("Field") if isinstance(fdef, dict) else None
            if not fname:
                continue
            vname = fdef.get("ViewName") or fname
            if field and field not in (fname, vname):
                continue
            try:
                out[vname] = _jsonable(
                    list(unique_values(layer, fname))[:limit])
            except Exception:
                out[vname] = []
        if field and not out:
            return self._err(f"field not found: {field!r} "
                             f"(use listTabs to see fields)")
        return self._ok({"fields": out})

    def _theme_collection(self):
        from qgis.core import QgsProject
        project = QgsProject.instance()
        return project, project.mapThemeCollection()

    def listThemes(self):
        """マップテーマ一覧・グループ・現在選択・追加表示モードを返す。"""
        p = self._plugin
        _, tc = self._theme_collection()
        names = []
        for t in tc.mapThemes() or []:
            if isinstance(t, str):
                names.append(t)
            else:
                n = getattr(t, "name", None)
                names.append(n() if callable(n) else (n or str(t)))
        try:
            from .theme import group_themes
            grouped = group_themes(names)
            groups = {str(k): v for k, v in grouped.items()}
        except Exception:
            groups = {}
        cur = None
        cmb = getattr(p, "theme_combobox", None)
        if cmb is not None:
            try:
                txt = cmb.currentText()
                cur = txt if txt and txt != QCoreApplication.translate("plugin", "Select theme") else None
            except Exception:  # nosec B110  # 設計上の許容
                pass
        return self._ok({
            "themes": names,
            "groups": groups,
            "current": cur,
            "additive": bool(getattr(p, "_theme_additive_mode", False)),
        })

    def applyTheme(self, name, additive=None):
        """マップテーマを適用する。additive指定時は追加表示モードも変更。"""
        p = self._plugin
        project, tc = self._theme_collection()
        names = [t if isinstance(t, str)
                 else getattr(t, "name", lambda: str(t))()
                 for t in tc.mapThemes() or []]
        if name not in names:
            return self._err(f"theme not found: {name!r} "
                             f"(available: {names})")
        if additive is not None:
            self.themeAdditive(additive)
        root = project.layerTreeRoot()
        try:
            model = p.iface.layerTreeView().layerTreeModel()
        except Exception:
            model = None
        try:
            from .theme import apply_theme
            apply_theme(tc, name, root, model,
                        additive=bool(getattr(p, "_theme_additive_mode",
                                              False)))
        except Exception as e:
            return self._err(f"apply_theme failed: {e}")
        # コンボの表示も合わせる(activatedは発火しない)
        cmb = getattr(p, "theme_combobox", None)
        if cmb is not None:
            try:
                cmb.blockSignals(True)
                cmb.setCurrentText(name)
            except Exception:  # nosec B110  # 設計上の許容
                pass
            finally:
                try:
                    cmb.blockSignals(False)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        return self._ok({"applied": name,
                         "additive": bool(getattr(
                             p, "_theme_additive_mode", False))})

    def themeAdditive(self, enabled=None):
        """テーマ適用の追加表示モードを取得/設定する。

        enabled: True=選択テーマのレイヤを現在表示に追加(union) /
                 False=通常上書き
        """
        p = self._plugin
        if enabled is not None:
            action = getattr(p, "additive_theme_action", None)
            if action is not None:
                try:
                    action.setChecked(bool(enabled))
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            # actionが無い/発火しない場合の保険として直接も設定
            try:
                p._on_additive_toggled(bool(enabled))
            except Exception:
                setattr(p, "_theme_additive_mode", bool(enabled))
        return self._ok({
            "additive": bool(getattr(p, "_theme_additive_mode", False))})

    def saveUserTheme(self, path=None):
        """現在の表示状態をユーザーテーマJSON(.usertheme.json)に保存する。"""
        import os
        from qgis.core import QgsProject
        project = QgsProject.instance()
        if not path:
            proj_file = project.fileName() or ""
            if not proj_file:
                return self._err("project not saved; pass explicit path")
            base = os.path.splitext(os.path.basename(proj_file))[0]
            path = os.path.join(
                os.path.dirname(proj_file), "themes",
                f"{base}__user_theme.usertheme.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        try:
            from . import theme as theme_mod
            ok = theme_mod.save_user_theme(path)
        except Exception as e:
            return self._err(f"save_user_theme failed: {e}")
        if not ok:
            return self._err("save_user_theme returned False")
        return self._ok({"saved": path})

    def loadUserTheme(self, path):
        """ユーザーテーマJSONを読み込んで現在のプロジェクトに適用する。"""
        try:
            from . import theme as theme_mod
            data = theme_mod.load_user_theme(path)
            if not data:
                return self._err(f"failed to read user theme: {path}")
            applied = theme_mod.apply_user_theme(data)
        except Exception as e:
            return self._err(f"load/apply user theme failed: {e}")
        return self._ok({"loaded": path,
                         "applied_layers": len(applied or [])})

    def getSettings(self):
        """検索設定の由来(ファイル/プロジェクト変数/env)と値を返す。"""
        import os
        from qgis.core import QgsProject, QgsExpressionContextUtils
        project = QgsProject.instance()
        scope = QgsExpressionContextUtils.projectScope(project)
        pv_tabs = scope.variable("GEO-search-plugin")
        pv_json = scope.variable("geo_search_json")
        env_json = os.environ.get("geo_search_json")
        counts = {}
        for e in self._flat_tabs():
            src = (getattr(e["feature"], "setting", {}) or {}).get(
                "_source") or "unknown"
            counts[src] = counts.get(src, 0) + 1
        return self._ok({
            "geo_search_json": {
                "env": env_json,
                "project_variable": pv_json,
            },
            "config_variable": {
                "name": "GEO-search-plugin",
                "inline": bool(pv_tabs and str(pv_tabs).strip()[:1]
                               in "{["),
                "value": (pv_tabs if pv_tabs and
                          len(str(pv_tabs)) < 2000 else
                          (f"<{len(str(pv_tabs))} chars>" if pv_tabs
                           else pv_tabs)),
            },
            "setting_json": os.path.join(
                os.path.dirname(__file__), "setting.json"),
            "tab_sources": counts,
        })

    def setSettings(self, settings=None, rebuild=True):
        """geo_search_json(検索設定JSONのパス)を設定する。

        settings(dict): {"geo_search_json": "<path>"}
        rebuild: Trueなら検索ダイアログを再構築して即時反映
        """
        settings = dict(settings or {})
        if "geo_search_json" not in settings:
            return self._err("supported keys: geo_search_json")
        import os
        from qgis.core import QgsProject
        from .utils import set_project_variable
        project = QgsProject.instance()
        path = str(settings["geo_search_json"]).strip()
        save_val = path
        try:
            proj_file = project.fileName() or ""
            proj_dir = os.path.dirname(proj_file) if proj_file else ""
            if proj_dir:
                abs_path = os.path.abspath(path)
                abs_proj = os.path.abspath(proj_dir)
                try:
                    if os.path.commonpath([abs_proj, abs_path]) == abs_proj:
                        save_val = os.path.relpath(abs_path, abs_proj)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        except Exception:  # nosec B110  # 設計上の許容
            pass
        set_project_variable(project, "geo_search_json", save_val)
        os.environ["geo_search_json"] = path
        out = {"geo_search_json": path, "saved_as": save_val}
        if rebuild:
            out["rebuilt"] = self._rebuild_dialog()
        return self._ok(out)

    def reloadDialog(self, show=True):
        """検索ダイアログを再構築する(設定・タブ変更の反映用)。"""
        ok = self._rebuild_dialog(show=show)
        if not ok:
            return self._err("rebuild failed")
        return self._ok({"tabCount": len(self._flat_tabs())})

    def _rebuild_dialog(self, show=True):
        p = self._plugin
        dlg = self._dialog()
        if dlg is not None:
            try:
                dlg.close()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        try:
            p.create_search_dialog()
        except Exception:
            return False
        if show:
            try:
                p.run()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        return self._dialog() is not None

    def tabSetting(self, tab=None):
        """検索タブの設定JSON(由来_source/_source_index含む)を返す。"""
        entry = self._find_tab(tab)
        if entry is None:
            return self._err(f"tab not found: {tab!r}")
        return self._ok({
            "index": entry["index"],
            "group": entry["group"],
            "title": getattr(entry["feature"], "title", None),
            "setting": _jsonable(
                getattr(entry["feature"], "setting", {}) or {}),
        })

    def addTabFromCurrentLayer(self, title=None, rebuild=True):
        """現在のアクティブレイヤを検索タブとして追加する。

        プロジェクト変数 GEO-search-plugin(インラインJSON)へ追記し、
        ダイアログを再構築する。確認ダイアログは出さない。
        """
        from qgis.core import QgsProject, QgsExpressionContextUtils
        from .utils import set_project_variable
        p = self._plugin
        layer = p.iface.activeLayer()
        if layer is None:
            return self._err("no active layer")
        layer_name = layer.name() if hasattr(layer, "name") else str(layer)
        tab_def = {
            "group": DEFAULT_GROUP_NAME,
            "Title": title or layer_name,
            "Layer": {"LayerType": "Name", "Name": layer_name},
            "SearchField": {},
            "ViewFields": [],
        }
        project = QgsProject.instance()
        scope = QgsExpressionContextUtils.projectScope(project)
        raw = scope.variable("GEO-search-plugin")
        data = {"SearchTabs": [tab_def]}
        if raw:
            txt = str(raw).strip()
            if txt[:1] in "{[":
                try:
                    existing = json.loads(txt)
                    if isinstance(existing, dict) and isinstance(
                            existing.get("SearchTabs"), list):
                        existing["SearchTabs"].append(tab_def)
                        data = existing
                    elif isinstance(existing, list):
                        existing.append(tab_def)
                        data = existing
                    elif isinstance(existing, dict):
                        data = {"SearchTabs": [existing, tab_def]}
                except Exception:  # nosec B110  # 設計上の許容
                    pass  # パース不能なら新規書き込み(ファイルパス等)
            else:
                return self._err(
                    "project variable 'GEO-search-plugin' is a file path; "
                    "use tabConfig editing on that file instead")
        ok = set_project_variable(project, "GEO-search-plugin",
                                  json.dumps(data, ensure_ascii=False))
        if not ok:
            return self._err("failed to write project variable")
        out = {"added": tab_def["Title"], "layer": layer_name}
        if rebuild:
            out["rebuilt"] = self._rebuild_dialog()
        return self._ok(out)

    def removeTab(self, tab=None, rebuild=True):
        """検索タブを設定ソースから削除し、ダイアログを再構築する。

        タブの由来(_source)に応じて setting.json / geo_search_json
        ファイル / プロジェクト変数 から対応エントリを除去する。
        確認ダイアログは出さない(呼び出し側の判断で実行)。
        """
        import os
        from qgis.core import QgsProject, QgsExpressionContextUtils
        from .utils import remove_entry_from_json_file, set_project_variable
        entry = self._find_tab(tab)
        if entry is None:
            return self._err(f"tab not found: {tab!r}")
        feat = entry["feature"]
        setting = getattr(feat, "setting", {}) or {}
        title = getattr(feat, "title", None) or setting.get("Title")
        src = setting.get("_source")
        src_idx = setting.get("_source_index")
        try:
            src_idx = int(src_idx) if src_idx is not None else None
        except Exception:
            src_idx = None
        removed_from = None
        if src == "setting.json" or (
                src is None and entry["group"] == "各種レイヤ"):
            path = os.path.join(os.path.dirname(__file__), "setting.json")
            if not os.path.exists(path):
                return self._err("setting.json not found")
            if not remove_entry_from_json_file(path, title=title,
                                               src_idx=src_idx):
                return self._err("failed to remove from setting.json")
            removed_from = "setting.json"
        else:
            # geo_search_json ファイル優先、無ければプロジェクト変数
            path = os.environ.get("geo_search_json")
            project = QgsProject.instance()
            scope = QgsExpressionContextUtils.projectScope(project)
            if not path:
                pv = scope.variable("geo_search_json")
                if pv:
                    path = pv
                    if not os.path.isabs(path):
                        proj_dir = os.path.dirname(
                            project.fileName() or "")
                        path = os.path.join(proj_dir, path) \
                            if proj_dir else path
            raw = scope.variable("GEO-search-plugin")
            if src == "geo_search_json" and path and os.path.exists(path):
                if not remove_entry_from_json_file(path, title=title,
                                                   src_idx=src_idx):
                    return self._err(f"failed to remove from {path}")
                removed_from = path
            elif raw and str(raw).strip()[:1] in "{[":
                try:
                    data = json.loads(str(raw))
                except Exception:
                    return self._err("cannot parse project variable")
                tabs = (data.get("SearchTabs")
                        if isinstance(data, dict) else data)
                if not isinstance(tabs, list):
                    return self._err("project variable has no tab list")
                hit = None
                for i, it in enumerate(tabs):
                    if isinstance(it, dict) and it.get("Title") == title:
                        hit = i
                        break
                if hit is None:
                    return self._err(f"tab entry not found in project "
                                     f"variable: {title!r}")
                del tabs[hit]
                set_project_variable(
                    project, "GEO-search-plugin",
                    json.dumps(data, ensure_ascii=False))
                removed_from = "project variable"
            elif path and os.path.exists(path):
                if not remove_entry_from_json_file(path, title=title,
                                                   src_idx=src_idx):
                    return self._err(f"failed to remove from {path}")
                removed_from = path
            else:
                return self._err(
                    f"cannot resolve source for tab {title!r} "
                    f"(_source={src!r})")
        out = {"removed": title, "from": removed_from}
        if rebuild:
            out["rebuilt"] = self._rebuild_dialog()
        return self._ok(out)

    # ---------- 設定ダイアログ / タブ設定の書込み / 結果表示 ----------

    def openSettings(self):
        """設定ダイアログを非modalで開く。"""
        from qgis.PyQt.QtCore import QTimer
        p = self._plugin
        QTimer.singleShot(0, p.open_settings_dialog)
        return self._ok({"opened": True})

    @staticmethod
    def _resolve_tab_source(setting):
        """タブ設定の由来ソースを解決する。"""
        import os
        from qgis.core import QgsProject, QgsExpressionContextUtils
        src = (setting or {}).get("_source")
        src_idx = (setting or {}).get("_source_index")
        try:
            src_idx = int(src_idx) if src_idx is not None else None
        except Exception:
            src_idx = None
        if src == "setting.json":
            return ("file", os.path.join(os.path.dirname(__file__),
                                         "setting.json"), src_idx)
        project = QgsProject.instance()
        if src == "geo_search_json":
            path = os.environ.get("geo_search_json")
            if not path:
                pv = QgsExpressionContextUtils.projectScope(
                    project).variable("geo_search_json")
                if pv:
                    path = pv
                    if not os.path.isabs(path):
                        proj_dir = os.path.dirname(project.fileName() or "")
                        path = os.path.join(proj_dir, path) \
                            if proj_dir else path
            if path and os.path.exists(path):
                return ("file", path, src_idx)
        return ("project", None, src_idx)

    @staticmethod
    def _load_tab_container(path):
        """タブ定義ファイルを読み(コンテナobj, タブlist)を返す。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("SearchTabs"), list):
            return data, data["SearchTabs"]
        if isinstance(data, list):
            return None, data
        return data, []

    @staticmethod
    def _find_in_container(tabs, title, src_idx):
        if src_idx is not None and 0 <= src_idx < len(tabs):
            return src_idx
        for i, it in enumerate(tabs):
            if isinstance(it, dict) and it.get("Title") == title:
                return i
        return None

    def setTabSetting(self, tab=None, config=None, rebuild=True):
        """既存タブの設定JSONを更新して由来ソースへ書き戻す。

        config(dict) は既存設定へマージされる(Title/Layer/SearchField/
        ViewFields/group 等)。由来はタブの _source で決まり、
        project variable / setting.json / geo_search_json へ書き戻す。
        """
        import os
        from qgis.core import QgsProject, QgsExpressionContextUtils
        from .utils import set_project_variable
        entry = self._find_tab(tab)
        if entry is None:
            return self._err(f"tab not found: {tab!r}")
        feat = entry["feature"]
        old = dict(getattr(feat, "setting", {}) or {})
        if not isinstance(config, dict):
            return self._err("config must be an object")
        title = old.get("Title") or getattr(feat, "title", None)
        new_cfg = dict(old)
        new_cfg.pop("_source", None)
        new_cfg.pop("_source_index", None)
        new_cfg.update(config)
        kind, path, src_idx = self._resolve_tab_source(old)
        written = None
        if kind == "file":
            container, tabs = self._load_tab_container(path)
            idx = self._find_in_container(tabs, title, src_idx)
            if idx is None:
                tabs.append(new_cfg)
            else:
                tabs[idx] = new_cfg
            out = container if container is not None else tabs
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            written = path
        else:
            project = QgsProject.instance()
            scope = QgsExpressionContextUtils.projectScope(project)
            raw = scope.variable("GEO-search-plugin")
            data = None
            if raw and str(raw).strip()[:1] in "{[":
                try:
                    data = json.loads(str(raw))
                except Exception:
                    data = None
            if isinstance(data, dict) and isinstance(
                    data.get("SearchTabs"), list):
                tabs = data["SearchTabs"]
            elif isinstance(data, list):
                tabs = data
            else:
                data, tabs = {}, []
            idx = self._find_in_container(tabs, title, src_idx)
            if idx is None:
                tabs.append(new_cfg)
            else:
                tabs[idx] = new_cfg
            out = data if data else tabs
            if not set_project_variable(
                    project, "GEO-search-plugin",
                    json.dumps(out, ensure_ascii=False)):
                return self._err("failed to write project variable")
            written = "project variable"
        out = {"updated": title, "to": written}
        if rebuild:
            out["rebuilt"] = self._rebuild_dialog()
        return self._ok(out)

    def addTab(self, config, target="project", rebuild=True):
        """任意のタブ定義dictを検索タブとして追加する。

        target: 'project'(既定)=プロジェクト変数 /
                'setting_json'=同梱setting.json /
                'geo_search_json'=geo_search_jsonファイル
        """
        import os
        from qgis.core import QgsProject, QgsExpressionContextUtils
        from .utils import set_project_variable
        if not isinstance(config, dict) or not config.get("Title"):
            return self._err("config must be an object with Title")
        new_cfg = dict(config)
        target = str(target or "project")
        if target == "setting_json":
            path = os.path.join(os.path.dirname(__file__), "setting.json")
            container, tabs = (self._load_tab_container(path)
                               if os.path.exists(path)
                               else ({"SearchTabs": []}, []))
            if container is not None and "SearchTabs" in container:
                tabs = container["SearchTabs"]
            tabs.append(new_cfg)
            out = container if container is not None else tabs
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            written = path
        elif target == "geo_search_json":
            path = os.environ.get("geo_search_json")
            project = QgsProject.instance()
            if not path:
                pv = QgsExpressionContextUtils.projectScope(
                    project).variable("geo_search_json")
                if pv:
                    path = pv
                    if not os.path.isabs(path):
                        proj_dir = os.path.dirname(project.fileName() or "")
                        path = os.path.join(proj_dir, path) \
                            if proj_dir else path
            if not path:
                return self._err("geo_search_json path not configured "
                                 "(use setSettings first)")
            if os.path.exists(path):
                container, tabs = self._load_tab_container(path)
            else:
                container, tabs = {"SearchTabs": []}, []
            if container is not None and "SearchTabs" in container:
                tabs = container["SearchTabs"]
            tabs.append(new_cfg)
            out = container if container is not None else tabs
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            written = path
        else:
            project = QgsProject.instance()
            scope = QgsExpressionContextUtils.projectScope(project)
            raw = scope.variable("GEO-search-plugin")
            data = None
            if raw and str(raw).strip()[:1] in "{[":
                try:
                    data = json.loads(str(raw))
                except Exception:
                    data = None
            if isinstance(data, dict) and isinstance(
                    data.get("SearchTabs"), list):
                tabs = data["SearchTabs"]
            elif isinstance(data, list):
                tabs = data
            else:
                data, tabs = {}, []
            tabs.append(new_cfg)
            out = data if data else tabs
            if not set_project_variable(
                    project, "GEO-search-plugin",
                    json.dumps(out, ensure_ascii=False)):
                return self._err("failed to write project variable")
            written = "project variable"
        out = {"added": new_cfg.get("Title"), "to": written}
        if rebuild:
            out["rebuilt"] = self._rebuild_dialog()
        return self._ok(out)

    def _result_dialog(self):
        feat = getattr(self._plugin, "current_feature", None)
        return getattr(feat, "result_dialog", None) if feat is not None \
            else None

    def resultPage(self, page=None):
        """結果ダイアログの表示ページを取得/設定する(1始まり)。"""
        rd = self._result_dialog()
        if rd is None:
            return self._err("no result dialog")
        if page is not None:
            try:
                page = int(page)
            except Exception:
                return self._err(f"invalid page: {page!r}")
            if page < 1 or page > rd.pageBox.maximum():
                return self._err(
                    f"page out of range: {page} "
                    f"(1..{rd.pageBox.maximum()})")
            rd.pageBox.setValue(page)  # → move_page
        return self._ok({"page": rd.pageBox.value(),
                         "page_count": rd.pageBox.maximum(),
                         "tab": rd.tabWidget.currentIndex()})

    def resultDisplayMode(self, mode=None):
        """結果ダイアログの表示モードを取得/設定する('table'/'form')。"""
        rd = self._result_dialog()
        if rd is None:
            return self._err("no result dialog")
        if mode is not None:
            mode = str(mode).lower()
            if mode not in ("table", "form"):
                return self._err("mode must be 'table' or 'form'")
            if getattr(rd, "display_mode", "table") != mode:
                rd._toggle_display_mode()
        return self._ok({"mode": getattr(rd, "display_mode", "table"),
                         "visible": bool(rd.isVisible())})

    def openDialog(self):
        p = self._plugin
        if self._dialog() is None:
            return self._err("dialog not initialized")
        p.run()
        dlg = self._dialog()
        return self._ok({"visible": bool(dlg is not None and dlg.isVisible())})

    def closeDialog(self):
        dlg = self._dialog()
        if dlg is not None:
            try:
                dlg.close()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        for e in self._flat_tabs():
            rd = getattr(e["feature"], "result_dialog", None)
            if rd is not None:
                try:
                    rd.hide()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        return self._ok()
