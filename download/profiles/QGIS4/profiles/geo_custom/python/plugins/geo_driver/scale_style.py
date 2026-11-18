"""スケール連動の標準線幅サービス(ScaleStyler)。

GISではCADと異なり、線幅をスケールに連動させられる:

- ``mm``       : 紙面/画面幅(mm)。現在縮尺に適した幅を標準テーブルから選ぶ
- ``meters``   : 地物の実幅(m)で描画。ズームで見た目の太さが変わる
                 (QgsUnitTypes.RenderMetersInMapUnits。CRS非依存の実メートル)
- ``rules``    : 縮尺帯ごとに幅の異なるルールベースレンダラを生成し、
                 縮尺変化で自動的に幅が切り替わる

標準線幅テーブルはプロファイルJSONで管理(layer_orgと同じ2階層):
  同梱   : <plugin>/scale_style/*.json    (読み取り専用デフォルト)
  ユーザ : ~/.qgis-live/scale_style/*.json (QGIS_LIVE_REGISTRY準拠、同名優先)

アクティブプロファイルは QSettings "geo_driver/scale_style/profile"
(stem名、既定 "default")。

プロファイルJSONスキーマ:
  {
    "name": "default",
    "description": "...",
    "scale_bands": [            // 縮尺分母の昇順(小さい=詳細側)。先勝ち
      {"max": 2500,   "label": "1:2,500迄",   "factor": 1.5},
      {"max": 25000,  "label": "〜1:25,000",  "factor": 1.0},
      {"max": null,   "label": "1:250,000〜", "factor": 0.4}
    ],
    "categories": [             // 先勝ち。matchキーはlayer_orgと同じ
      {"key": "road_major",
       "match": {"name_re": "国道|主要|trunk|primary", "geom": "line"},
       "base_mm": 0.55,         // 基準帯(factor=1.0)での紙面幅mm
       "real_width_m": 13.0},   // meters モードの実世界幅(省略可)
      {"key": "default", "match": {}, "base_mm": 0.3}
    ]
  }

GUIスレッド前提のQGIS操作は全てメソッド内importに閉じ込め、
このモジュール自体は stdlib のみでimport可能(unit test対象)。
"""

import json
import os

from .layer_org import _match_all, layer_attrs

_SETTING_PROFILE = "geo_driver/scale_style/profile"
_DEFAULT_PROFILE = "default"


def _registry_dir():
    return os.environ.get(
        "QGIS_LIVE_REGISTRY",
        os.path.join(os.path.expanduser("~"), ".qgis-live"))


def profiles_dir():
    """ユーザ定義プロファイル置き場 ~/.qgis-live/scale_style/。"""
    return os.path.join(_registry_dir(), "scale_style")


def _bundled_dir():
    """プラグイン同梱のデフォルトプロファイル dir。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "scale_style")


def list_profiles():
    """利用可能なプロファイル一覧。[{id,name,description,builtin,path}]。

    bundled→user の順に走査し、同名(stem)はユーザ側が上書き。
    """
    out = {}
    for d, builtin in ((_bundled_dir(), True), (profiles_dir(), False)):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith(".json"):
                continue
            stem = f[:-5]
            if not builtin or stem not in out:
                p = os.path.join(d, f)
                name, desc = stem, ""
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        meta = json.load(fh)
                    name = meta.get("name") or stem
                    desc = meta.get("description") or ""
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                out[stem] = {"id": stem, "name": name, "description": desc,
                             "path": p, "builtin": builtin}
    return [out[k] for k in sorted(out)]


def load_profile(name):
    """プロファイルid → (dict, path)。見つからなければ (None, None)。"""
    for p in list_profiles():
        if p["id"] == name:
            try:
                with open(p["path"], "r", encoding="utf-8") as f:
                    prof = json.load(f)
            except Exception:
                return None, None
            prof["_path"] = p["path"]
            prof["_dir"] = os.path.dirname(p["path"])
            prof["id"] = name
            return prof, p["path"]
    return None, None


def band_for_scale(prof, scale):
    """縮尺分母に対応する scale_bands エントリを返す(先勝ち)。

    band["max"]=上限(排他)。max=None は「それ以上全部」。
    scale=None(不明)は factor=1.0 の基準帯(無ければ先頭)を返す。
    """
    bands = prof.get("scale_bands") or []
    if scale is None:
        for b in bands:
            if b.get("factor") == 1.0:
                return b
        return bands[0] if bands else None
    try:
        s = float(scale)
    except (TypeError, ValueError):
        return band_for_scale(prof, None)
    prev = None
    for b in bands:
        mx = b.get("max")
        if mx is None or s < float(mx):
            return b
        prev = b
    return bands[-1] if bands else prev


def match_category(prof, attrs):
    """categories を先頭から評価し最初に一致したカテゴリを返す。"""
    for cat in prof.get("categories") or []:
        if _match_all(cat.get("match") or {}, attrs):
            return cat
    return None


def mm_to_meters(width_mm, scale):
    """紙面mm → 地物実幅m (scale=縮尺分母)。scale不明ならNone。"""
    try:
        return round(float(width_mm) * float(scale) / 1000.0, 3)
    except (TypeError, ValueError):
        return None


def suggested_mm(prof, cat, scale):
    """カテゴリの base_mm に縮尺帯 factor を掛けた推奨mm幅を返す。

    @returns (width_mm, band) — band は band_for_scale() の結果。
    """
    band = band_for_scale(prof, scale)
    base = float((cat or {}).get("base_mm") or 0.3)
    factor = float((band or {}).get("factor") or 1.0)
    w = round(base * factor, 2)
    return max(0.05, min(w, 10.0)), band


_UNIT_NAMES = {
    "mm": "RenderMillimeters",
    "pixels": "RenderPixels",
    "px": "RenderPixels",
    "map_units": "RenderMapUnits",
    "meters": "RenderMetersInMapUnits",
    "m": "RenderMetersInMapUnits",
}


def _qgis_unit(name, default="mm"):
    """単位名 → QgsUnitTypes.RenderUnit。"""
    from qgis.core import QgsUnitTypes
    attr = _UNIT_NAMES.get(str(name or default).lower(),
                           _UNIT_NAMES[default])
    # Qt6(scoped enum)では RenderUnit.<name>、フラット公開なら直接
    try:
        return getattr(QgsUnitTypes, attr)
    except AttributeError:
        return getattr(QgsUnitTypes.RenderUnit, attr)


def _set_symbol_width(symbol, width, unit_name="mm"):
    """シンボル内の各シンボルレイヤへ幅を設定する。

    線/マーカーは setWidth+setWidthUnit、塗りつぶしの輪郭は
    setStrokeWidth+setStrokeWidthUnit を使う。
    """
    unit = _qgis_unit(unit_name)
    for i in range(symbol.symbolLayerCount()):
        sl = symbol.symbolLayer(i)
        if hasattr(sl, "setWidth"):
            sl.setWidth(float(width))
            if hasattr(sl, "setWidthUnit"):
                sl.setWidthUnit(unit)
        if hasattr(sl, "setStrokeWidth"):
            sl.setStrokeWidth(float(width))
            if hasattr(sl, "setStrokeWidthUnit"):
                sl.setStrokeWidthUnit(unit)


def renderer_symbols(renderer):
    """レンダラが保持する全シンボルを列挙する。"""
    from qgis.core import (QgsCategorizedSymbolRenderer,
                           QgsGraduatedSymbolRenderer,
                           QgsRuleBasedRenderer,
                           QgsSingleSymbolRenderer)
    if renderer is None:
        return []
    if isinstance(renderer, QgsSingleSymbolRenderer):
        return [renderer.symbol()]
    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        return [c.symbol() for c in renderer.categories()]
    if isinstance(renderer, QgsGraduatedSymbolRenderer):
        return [r.symbol() for r in renderer.ranges()]
    if isinstance(renderer, QgsRuleBasedRenderer):
        out = []

        def walk(rule):
            if rule.symbol() is not None:
                out.append(rule.symbol())
            for ch in rule.children():
                walk(ch)

        walk(renderer.rootRule())
        return out
    try:
        from qgis.core import QgsRenderContext
        return list(renderer.symbols(QgsRenderContext()))
    except Exception:  # nosec B110  # 設計上の許容
        return []


def _symbol_color(symbol):
    try:
        return symbol.color().name()
    except Exception:  # nosec B110  # 設計上の許容
        return None


class ScaleStyler:
    """レイヤ線幅を標準テーブル+スケールで決める共有サービス。

    bridge や他プラグインから plugins['geo_driver'].scale_style
    経由で使う。プロファイル無効/不在でも静かにエラーdictを返す。
    """

    # ---------- プロファイル解決 ----------

    def active_profile_name(self):
        try:
            from qgis.PyQt.QtCore import QSettings
            v = QSettings().value(_SETTING_PROFILE, _DEFAULT_PROFILE)
            return str(v or _DEFAULT_PROFILE)
        except Exception:
            return _DEFAULT_PROFILE

    def set_active_profile(self, name):
        prof, _ = load_profile(str(name or ""))
        if prof is None:
            return {"ok": False,
                    "error": f"profile not found: {name}",
                    "profiles": [p["id"] for p in list_profiles()]}
        try:
            from qgis.PyQt.QtCore import QSettings
            QSettings().setValue(_SETTING_PROFILE, str(name))
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return {"ok": True, "active": str(name)}

    def profile(self, name=None):
        prof, _ = load_profile(name or self.active_profile_name())
        if prof is None or prof.get("enabled") is False:
            return None
        return prof

    def describe(self, name=None):
        """bridge表示用のプロファイル要約。"""
        prof, path = load_profile(name or self.active_profile_name())
        if prof is None:
            return None
        return {
            "id": prof.get("id"), "name": prof.get("name"),
            "description": prof.get("description"),
            "path": path,
            "enabled": prof.get("enabled") is not False,
            "scale_bands": prof.get("scale_bands") or [],
            "categories": [
                {"key": c.get("key"),
                 "match": c.get("match") or {},
                 "base_mm": c.get("base_mm"),
                 "real_width_m": c.get("real_width_m")}
                for c in prof.get("categories") or []],
        }

    # ---------- 推奨値計算 ----------

    @staticmethod
    def canvas_scale():
        """現在の地図キャンバス縮尺分母(取得不可ならNone)。"""
        try:
            from qgis.utils import iface
            return iface.mapCanvas().scale()
        except Exception:  # nosec B110  # 設計上の許容
            return None

    def categorize(self, layer, ctx=None):
        """レイヤ名/属性からカテゴリを推定する。"""
        prof = self.profile()
        attrs = layer_attrs(layer, ctx)
        cat = match_category(prof or {}, attrs)
        return (cat.get("key") if cat else None), cat

    def suggest(self, layer=None, category=None, scale=None,
                profile_name=None):
        """推奨線幅を返す。scale省略時は現在のキャンバス縮尺。

        @returns dict: {category, scale, band, base_mm, factor,
                        width_mm, real_width_m, width_m_equiv}
        """
        prof = self.profile(profile_name)
        if prof is None:
            return {"ok": False,
                    "error": "profile not found or disabled"}
        cat = None
        if category:
            for c in prof.get("categories") or []:
                if c.get("key") == category:
                    cat = c
                    break
            if cat is None:
                return {"ok": False,
                        "error": f"category not found: {category}",
                        "categories": [c.get("key") for c in
                                       prof.get("categories") or []]}
        elif layer is not None:
            cat = match_category(prof, layer_attrs(layer))
        if cat is None:
            cat = next((c for c in prof.get("categories") or []
                        if c.get("key") == "default"), None)
        if cat is None:
            return {"ok": False, "error": "no matching category"}
        s = scale if scale is not None else self.canvas_scale()
        w_mm, band = suggested_mm(prof, cat, s)
        real_m = cat.get("real_width_m")
        if real_m is None:
            real_m = mm_to_meters(w_mm, s)
        return {"ok": True,
                "category": cat.get("key"),
                "scale": s,
                "band": (band or {}).get("label"),
                "base_mm": cat.get("base_mm"),
                "factor": (band or {}).get("factor"),
                "width_mm": w_mm,
                "real_width_m": real_m,
                "width_m_equiv": mm_to_meters(w_mm, s)}

    # ---------- 適用(QGIS依存) ----------

    @staticmethod
    def _find_layer(sel):
        """layer_id/レイヤ名/None(=アクティブ)からレイヤを解決する。"""
        from qgis.core import QgsProject
        from qgis.utils import iface
        if sel is None:
            return iface.activeLayer()
        proj = QgsProject.instance()
        layer = proj.mapLayer(str(sel))
        if layer is None:
            matches = proj.mapLayersByName(str(sel))
            layer = matches[0] if matches else None
        return layer

    @staticmethod
    def _is_strokable(layer):
        """線幅を設定し得るレイヤ(線 or ポリゴン輪郭)か。"""
        from qgis.core import QgsWkbTypes
        try:
            gt = QgsWkbTypes.geometryType(layer.wkbType())
        except Exception:
            return False
        return int(gt) in (
            int(QgsWkbTypes.GeometryType.LineGeometry),
            int(QgsWkbTypes.GeometryType.PolygonGeometry))

    def apply(self, layer, mode="mm", category=None, scale=None,
              profile_name=None, dry=False):
        """レイヤのレンダラに標準線幅を適用する。

        mode:
          "mm"     — 推奨mm幅を現縮尺向けに固定設定
          "meters" — 実世界幅(m)で設定(ズーム連動)
          "rules"  — 縮尺帯ルールレンダラを生成(幅が縮尺で自動切替)
        dry=True で適用せず予定内容のみ返す。
        """
        mode = str(mode or "mm").lower()
        if mode in ("map_units", "m", "real"):
            mode = "meters"
        if mode not in ("mm", "meters", "rules"):
            return {"ok": False,
                    "error": f"unknown mode: {mode} "
                             "(mm|meters|rules)"}
        if not self._is_strokable(layer):
            return {"ok": False,
                    "error": "layer is not a line/polygon vector layer"}
        ren = layer.renderer() if hasattr(layer, "renderer") else None
        if ren is None:
            return {"ok": False, "error": "layer has no renderer"}

        if mode == "rules":
            return self._apply_rules(layer, category, profile_name, dry)

        sug = self.suggest(layer=layer, category=category,
                           scale=scale, profile_name=profile_name)
        if not sug.get("ok"):
            return sug
        symbols = renderer_symbols(ren)
        if not symbols:
            return {"ok": False, "error": "renderer has no symbols"}
        applied = {"mode": mode, "suggest": sug,
                   "symbols": len(symbols)}
        if mode == "mm":
            applied["width_mm"] = sug["width_mm"]
        else:
            m = sug["real_width_m"]
            if m is None:
                return {"ok": False,
                        "error": "no real width for category; "
                                 "use mode=mm or pass scale"}
            applied["width_m"] = m
        if not dry:
            if mode == "mm":
                for sym in symbols:
                    _set_symbol_width(sym, applied["width_mm"], "mm")
            else:
                for sym in symbols:
                    _set_symbol_width(sym, applied["width_m"], "meters")
            layer.triggerRepaint()
        return {"ok": True, "layer": layer.name(), **applied}

    def _apply_rules(self, layer, category, profile_name, dry):
        """縮尺帯ルールレンダラを生成・適用する。"""
        prof = self.profile(profile_name)
        if prof is None:
            return {"ok": False, "error": "profile not found or disabled"}
        attrs = layer_attrs(layer)
        cat = (next((c for c in prof.get("categories") or []
                     if c.get("key") == category), None)
               if category else match_category(prof, attrs))
        if cat is None:
            cat = next((c for c in prof.get("categories") or []
                        if c.get("key") == "default"), None)
        if cat is None:
            return {"ok": False, "error": "no matching category"}
        base_mm = float(cat.get("base_mm") or 0.3)
        bands = prof.get("scale_bands") or []
        if not bands:
            return {"ok": False, "error": "profile has no scale_bands"}

        # 現シンボルの色を引き継ぐ
        color = None
        syms = renderer_symbols(layer.renderer())
        if syms:
            color = _symbol_color(syms[0])

        specs, prev = [], 0
        for b in bands:
            mx = b.get("max")
            w = round(base_mm * float(b.get("factor") or 1.0), 2)
            w = max(0.05, min(w, 10.0))
            label = f"{b.get('label') or ('1:' + str(mx))} ({w:g}mm)"
            # 帯のactive範囲は min_scale < 縮尺分母 <= max_scale
            # (min_scale=詳細側の排他下限、max_scale=広域側の包含上限)
            specs.append({"label": label,
                          "min_scale": int(prev) if prev else 0,
                          "max_scale": int(mx) if mx else 0,
                          "width": w,
                          "color": color})
            prev = mx
        if dry:
            return {"ok": True, "mode": "rules", "dry": True,
                    "category": cat.get("key"), "rules": specs}

        # geo_legend がロード済みなら applyRules へ委譲(凡例作成の
        # オーナー)。未ロード/失敗時は内部実装へフォールバック
        try:
            import qgis.utils
            gl = qgis.utils.plugins.get("geo_legend")
            br = getattr(gl, "bridge", None)
            if br is not None:
                res = json.loads(
                    br.applyRules(layer.id(), specs))
                if res.get("ok"):
                    res["delegated"] = "geo_legend.applyRules"
                    res["category"] = cat.get("key")
                    return res
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return self._apply_rules_local(layer, specs, cat)

    def _apply_rules_local(self, layer, specs, cat):
        """geo_legend非依存のルールレンダラ構築(フォールバック)。"""
        from qgis.core import QgsRuleBasedRenderer, QgsWkbTypes
        gt = QgsWkbTypes.geometryType(layer.wkbType())
        sym_cls = {
            int(QgsWkbTypes.GeometryType.PointGeometry):
                __import__("qgis.core", fromlist=["QgsMarkerSymbol"])
                .QgsMarkerSymbol,
            int(QgsWkbTypes.GeometryType.LineGeometry):
                __import__("qgis.core", fromlist=["QgsLineSymbol"])
                .QgsLineSymbol,
        }.get(int(gt))
        if sym_cls is None:
            from qgis.core import QgsFillSymbol
            sym_cls = QgsFillSymbol
        from qgis.PyQt.QtGui import QColor
        root = QgsRuleBasedRenderer.Rule(None)
        for spec in specs:
            sym = sym_cls.createSimple({})
            if spec.get("color"):
                sym.setColor(QColor(str(spec["color"])))
            _set_symbol_width(sym, spec["width"], "mm")
            # Rule ctor: (symbol, maximumScale, minimumScale, filterExp,
            #             label)。active範囲は min<scale<=max
            root.appendChild(QgsRuleBasedRenderer.Rule(
                sym, int(spec.get("max_scale") or 0),
                int(spec.get("min_scale") or 0), "",
                str(spec.get("label") or "")))
        layer.setRenderer(QgsRuleBasedRenderer(root))
        layer.triggerRepaint()
        return {"ok": True, "mode": "rules",
                "category": cat.get("key"),
                "delegated": None, "rules": specs}
