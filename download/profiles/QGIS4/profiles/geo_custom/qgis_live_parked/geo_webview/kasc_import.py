# -*- coding: utf-8 -*-
"""KASUGAI Canvas プロジェクト(.kasc)の QGIS への逆取り込み。

`kasugai_export.py` が送出する .kasc 行形式を解析し、QGIS の
レイヤツリー・スタイル(.qml)・縮尺表示・グループ・カメラを復元する。
「既存 WebGIS(.kasc+DATA/) → QGIS」経路の実体で、再送出
(kasugaiExport)と組み合わせると WebGIS → Canvas の変換に使える。

- ``parse_kasc(text)`` — .kasc テキストを構造化 dict へ。
  KASUGAI Canvas 側 web/shared/kasc.js と同じ規則
  (``type: タイトル | URL | on/off | key=value | 出典``)で解釈する。
  stdlib のみで動作(pytest 対象)
- ``inspect_kasc(source)`` — パース+参照解決のみ(副作用なし・dry run)
- ``import_kasc(source, ...)`` — QGIS プロジェクトへレイヤを再構成。
  PyQGIS 依存は関数内importに閉じ込め、本モジュールは stdlib のみで
  import 可能
"""

import os
import re
import tempfile
import unicodedata
import urllib.parse
import urllib.request

# doc.layers に入る行タイプ(web/shared/kasc.js と同一集合)
_LAYER_TYPES = frozenset([
    "xyz", "tile", "geojson", "layer", "geoparquet", "parquet",
    "flatgeobuf", "fgb", "gpkg", "geopackage", "csv", "tsv", "duckdb",
    "sql", "wms", "wmts", "kml", "kmz", "wfs", "shp", "shapefile",
    "image", "mvt", "pmtiles", "geotiff", "tiff", "cog", "3dtiles",
    "fly_geojson", "model", "pointcloud", "ept", "copc",
])

# 解析はするが QGIS レイヤ化しないメタ行(報告用)
_META_TYPES = frozenset([
    "cam", "background", "info", "legend", "theme", "legendnode",
    "bookmark", "cloud", "plugin", "yahooappid", "title",
    "group", "terrain", "scene3d", "light", "live",
    "default_style", "defaultstyle",
])

_BOOL_RE = re.compile(r"^(on|off|true|false)$", re.IGNORECASE)
_KV_RE = re.compile(r"^([A-Za-z_][\w.-]*)\s*=\s*(.*)$")

# http(s)/プロトコル参照とみなす接頭辞(相対解決しない)
_ABS_RE = re.compile(
    r"^(https?://|file://|/vsicurl/|data:|cloud:|localfs:|pmtiles://|"
    r"qgis-map|\\\\|[A-Za-z]:[\\/])", re.IGNORECASE)


def _classify_parts(parts, item):
    """kasc.js classifyParts 相当。

    on/off/true/false → visible、key=value → opts(キー小文字化)、
    それ以外の最初のトークン → attr(出典)、残り → opts['extra']。
    """
    item["opts"] = {}
    item["attr"] = ""
    item["visible"] = True
    for part in parts:
        if not part:
            continue
        if _BOOL_RE.match(part):
            item["visible"] = not re.match(
                r"^(off|false)$", part, re.IGNORECASE)
            continue
        kv = _KV_RE.match(part)
        if kv:
            item["opts"][kv.group(1).lower()] = kv.group(2)
            continue
        if not item["attr"]:
            item["attr"] = part
        else:
            extra = item["opts"].get("extra")
            item["opts"]["extra"] = (extra + " | " + part
                                     if extra else part)
    return item


def _parse_cam(parts):
    """cam:名|緯度|経度|h=高さ|p=ピッチ|d=方位 → dict。"""
    cam = {"name": parts[0] if parts else "",
           "latitude": _f(parts[1]) if len(parts) > 1 else None,
           "longitude": _f(parts[2]) if len(parts) > 2 else None}
    for part in parts[3:]:
        kv = _KV_RE.match(part)
        if not kv:
            continue
        key, val = kv.group(1).lower(), _f(kv.group(2))
        if key == "h":
            cam["height"] = val
        elif key == "p":
            cam["pitch"] = val
        elif key == "d":
            cam["heading"] = val
    return cam


def _f(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_kasc(text):
    """.kasc テキストを構造化 dict へ変換する(stdlib のみ)。

    戻り値: ``{layers, bases, cams, bookmarks, themes, groups,
    title, background, info, legends, live, terrain, scene3d, lights,
    default_styles, unsupported}``。

    - ``layers``/``bases`` は出現順(order)を保持
    - レイヤ行は ``{type,title,url,visible,opts,attr,line}``
    - 未対応・メタ行は ``unsupported`` へ種別付きで記録
    """
    doc = {"layers": [], "bases": [], "cams": [], "bookmarks": [],
           "themes": [], "groups": [], "title": None,
           "background": None, "info": None, "legends": [],
           "live": None, "terrain": None, "scene3d": None,
           "lights": [], "default_styles": {}, "unsupported": []}
    order = 0
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        sep = line.find(":")
        if sep < 0:
            continue
        ltype = line[:sep].strip().lower()
        parts = [p.strip() for p in line[sep + 1:].split("|")]

        if ltype == "cam":
            doc["cams"].append(_parse_cam(parts))
            continue
        if ltype == "background":
            doc["background"] = parts[0] if parts else None
            continue
        if ltype == "info":
            doc["info"] = ("|".join(parts[1:]) or parts[0]) if parts else None
            continue
        if ltype == "legend":
            doc["legends"].append({
                "title": parts[0] if len(parts) > 1 else None,
                "url": parts[1] if len(parts) > 1 else parts[0]})
            continue
        if ltype == "bookmark":
            doc["bookmarks"].append({
                "title": parts[0] if len(parts) > 1 else None,
                "url": parts[1] if len(parts) > 1 else parts[0]})
            continue
        if ltype == "theme":
            layers, styles = [], {}
            for tok in parts[1:]:
                if not tok:
                    continue
                semi = tok.find(";style=")
                if semi >= 0:
                    t = tok[:semi]
                    rel = tok[semi + len(";style="):].strip()
                    layers.append(t)
                    if t and rel:
                        styles[t.strip()] = rel
                else:
                    layers.append(tok)
            doc["themes"].append({"name": parts[0] if parts else "",
                                  "layers": layers, "styles": styles,
                                  "line": line})
            continue
        if ltype == "group":
            check = None
            for p in parts[2:]:
                m = re.match(r"^checked\s*=\s*(.+)$", p, re.IGNORECASE)
                if m:
                    check = m.group(1).strip().lower()
            doc["groups"].append({
                "path": parts[0] if parts else "",
                "collapsed": bool(
                    parts and re.match(
                        r"^(collapsed|off|false)$", parts[1] or "",
                        re.IGNORECASE)),
                "check": check, "line": line})
            continue
        if ltype == "title":
            doc["title"] = line[sep + 1:].strip() or None
            continue
        if ltype == "live":
            doc["live"] = {"url": parts[0] if parts else "",
                           "follow": any(
                               re.match(r"^follow$", p, re.IGNORECASE)
                               for p in parts[1:]),
                           "line": line}
            continue
        if ltype in ("terrain", "scene3d", "light"):
            item = _classify_parts(
                parts[1:], {"type": ltype,
                            "title": parts[0] if parts else "",
                            "url": "", "line": line})
            if ltype == "terrain":
                doc["terrain"] = item
            elif ltype == "scene3d":
                doc["scene3d"] = item
            else:
                doc["lights"].append(item)
            continue
        if ltype in ("default_style", "defaultstyle"):
            if parts:
                spec = {"kind": parts[0], "values": {}}
                for kv in parts[1:]:
                    m = _KV_RE.match(kv)
                    if m:
                        spec["values"][m.group(1).lower()] = m.group(2)
                doc["default_styles"][spec["kind"]] = spec["values"]
            continue

        item = _classify_parts(
            parts[1:] if ltype == "sql" else parts[2:],
            {"type": ltype,
             "title": parts[0] if parts else "",
             "url": ("|".join(parts[1:]) if ltype == "sql"
                     else (parts[1] if len(parts) > 1 else "")),
             "line": line})
        item["_idx"] = order
        order += 1
        if ltype == "base":
            mode = parts[1].lower() if len(parts) > 1 else ""
            if mode in ("transparent", "none"):
                item["mode"] = mode
            doc["bases"].append(item)
            continue
        if ltype in _LAYER_TYPES:
            doc["layers"].append(item)
            continue
        # レイヤ行でも既知メタ行でもないものは unsupported へ
        item["reason"] = ("未知/メタ行タイプ" if ltype not in _META_TYPES
                          else "メタ行(QGISレイヤ化対象外)")
        doc["unsupported"].append(item)
    return doc


def _read_source(source, timeout=15):
    """.kasc を読み (text, base_dir) を返す。base は DATA/ 相対解決用。"""
    src = str(source or "").strip()
    if re.match(r"^https?://", src):
        req = urllib.request.Request(
            src, headers={"User-Agent": "geo_webview-kasc_import"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
            text = r.read().decode("utf-8", "replace")
        return text, src.rsplit("/", 1)[0] + "/"
    path = os.path.abspath(src)
    if not os.path.isfile(path):
        raise FileNotFoundError(f".kasc が見つからない: {src}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read(), os.path.dirname(path)


def resolve_ref(ref, base):
    """DATA/x.gpkg 等の相対参照を base(.kasc の所在)から絶対化する。"""
    r = str(ref or "").strip()
    if not r:
        return ""
    if _ABS_RE.match(r):
        if r.lower().startswith("file:///"):
            return urllib.parse.unquote(r[8:])
        return r
    if base and re.match(r"^https?://", base):
        return urllib.parse.urljoin(base, r)
    return os.path.normpath(os.path.join(base or "", r))


def _is_remote(ref):
    return bool(re.match(r"^https?://", str(ref or "")))


def _ogr_source(ref):
    """ogr 用ソース文字列。http(s)は /vsicurl/ 経由。"""
    if _is_remote(ref):
        return "/vsicurl/" + ref
    return ref


def inspect_kasc(source, timeout=15):
    """.kasc を解析し参照を解決した一覧を返す(QGIS副作用なし)。"""
    text, base = _read_source(source, timeout=timeout)
    doc = parse_kasc(text)
    counts = {}
    for it in doc["layers"] + doc["bases"]:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
    return {
        "ok": True, "source": source, "base": base,
        "title": doc["title"], "counts": counts,
        "layers": [{
            "type": it["type"], "title": it["title"],
            "ref": resolve_ref(it["url"], base),
            "visible": it["visible"], "opts": it["opts"],
            "attr": it["attr"]} for it in doc["layers"]],
        "bases": [{
            "title": it["title"], "ref": resolve_ref(it["url"], base),
            "visible": it["visible"], "mode": it.get("mode")}
            for it in doc["bases"]],
        "groups": [g["path"] for g in doc["groups"]],
        "cams": doc["cams"],
        "themes": [{"name": t["name"], "layers": t["layers"]}
                   for t in doc["themes"]],
        "bookmarks": [b["url"] for b in doc["bookmarks"]],
        "unsupported": [{"type": it["type"], "title": it["title"],
                         "reason": it.get("reason", "")}
                        for it in doc["unsupported"]],
    }


# ---------------------------------------------------------------------------
# QGIS 依存部(以下は全て関数内importに閉じ込め)
# ---------------------------------------------------------------------------

def _title_leaf(title):
    """'g1/g2/名' → リーフ名。'//' (排他グループ) も分割対象。"""
    t = str(title or "").replace("//", "/")
    return t.split("/")[-1].strip() or str(title or "layer")


def _norm_title(s):
    """タイトル照合用の正規化(NFKC + 連続空白を1つへ)。"""
    return re.sub(r"\s+", " ",
                  unicodedata.normalize("NFKC", str(s or ""))).strip()


def _source_key(source):
    """replace 判定用の正規化キー(ローカルは絶対パスを小文字化)。"""
    src = str(source or "").strip()
    if _is_remote(src):
        return src
    return os.path.normcase(os.path.abspath(src))


def _title_groups(title):
    """'g1/g2/名' → ['g1','g2']。"""
    t = str(title or "").replace("//", "/")
    parts = [p.strip() for p in t.split("/") if p.strip()]
    return parts[:-1]


def _exclusive_groups(title):
    """'g1//g2/名' → 排他扱いの親グループ名一覧(//直前の末端名)。"""
    parts = str(title or "").split("//")
    if len(parts) < 2:
        return []
    out = []
    for p in parts[:-1]:
        seg = [s.strip() for s in p.split("/") if s.strip()]
        if seg:
            out.append(seg[-1])
    return out


def _build_vector(item, base, warnings):
    """ベクター行 → (QgsVectorLayer, src_desc)。不可時 None。"""
    from qgis.core import QgsVectorLayer
    t = item["type"]
    ref = resolve_ref(item["url"], base)
    o = item["opts"]
    leaf = _title_leaf(item["title"])
    if t == "sql":
        return None, "sql: 行は QGIS 側の対応ソースなし"
    src = None
    if t in ("gpkg", "geopackage"):
        src = _ogr_source(ref)
        if o.get("table"):
            src += "|layername={0}".format(o["table"])
    elif t in ("duckdb", "csv", "tsv"):
        fmt = (o.get("format") or t).lower()
        is_text = fmt in ("csv", "tsv") or \
            ref.lower().endswith((".csv", ".tsv"))
        if is_text and not _is_remote(ref):
            # ローカル CSV/TSV → delimitedtext プロバイダ
            q = {"type": "csv", "crs": "EPSG:4326",
                 "detectTypes": "yes"}
            if o.get("geom"):
                q["geomType"] = "wkt"
                q["wktField"] = o["geom"]
            elif o.get("lon") and o.get("lat"):
                q["geomType"] = "point"
                q["xField"] = o["lon"]
                q["yField"] = o["lat"]
            else:
                q["geomType"] = "none"
            if fmt == "tsv" or ref.lower().endswith(".tsv"):
                q["delimiter"] = "\t"
            src = "file:///{0}?{1}".format(
                ref.replace("\\", "/"),
                urllib.parse.urlencode(q))
        else:
            # parquet/リモートCSV → ogr(GeoParquetはGDAL3.5+)
            src = _ogr_source(ref)
            if is_text and _is_remote(ref):
                warnings.append(
                    "{0}: リモートCSVはogr経由(列解釈は限定的)".format(
                        leaf))
    elif t == "wfs":
        src = "WFS:" + ref
    else:
        # geojson/layer/geoparquet/parquet/flatgeobuf/fgb/shp/kml/kmz/
        # fly_geojson — 全て ogr で読める
        src = _ogr_source(ref)
    if src is None:
        return None, "{0} は未対応".format(t)
    layer = QgsVectorLayer(src, leaf, "ogr")
    return layer, src


def _build_raster(item, base, warnings):
    """ラスタ/タイル行 → (QgsMapLayer, src_desc)。不可時 (None, 理由)。"""
    from qgis.core import (QgsRasterLayer, QgsVectorTileLayer,
                           QgsTiledSceneLayer, QgsPointCloudLayer,
                           QgsRectangle, QgsCoordinateReferenceSystem)
    t = item["type"]
    ref = resolve_ref(item["url"], base)
    o = item["opts"]
    leaf = _title_leaf(item["title"])
    enc = urllib.parse.quote(ref, safe="")
    if t in ("xyz", "tile", "base"):
        uri = "type=xyz&url={0}".format(enc)
        if o.get("minzoom") is not None:
            uri += "&zmin={0}".format(int(_f(o["minzoom"]) or 0))
        if o.get("maxzoom") is not None:
            uri += "&zmax={0}".format(int(_f(o["maxzoom"]) or 0))
        return QgsRasterLayer(uri, leaf, "wms"), uri
    if t == "wms":
        q = {"crs": "EPSG:3857",
             "format": o.get("format", "image/png"),
             "layers": o.get("layers", ""),
             "styles": o.get("styles", ""),
             "url": ref}
        if o.get("version"):
            q["version"] = o["version"]
        uri = "&".join("{0}={1}".format(k, v) for k, v in q.items())
        return QgsRasterLayer(uri, leaf, "wms"), uri
    if t == "wmts":
        q = {"crs": "EPSG:3857",
             "format": o.get("format", "image/png"),
             "layers": o.get("layer", o.get("layers", "")),
             "styles": o.get("style", o.get("styles", "")),
             "tileMatrixSet": o.get("tilematrixset", ""),
             "tileDimensions": o.get("tilesize", "256"),
             "url": ref}
        uri = "&".join("{0}={1}".format(k, v)
                       for k, v in q.items() if v != "")
        return QgsRasterLayer(uri, leaf, "wms"), uri
    if t in ("mvt", "pmtiles"):
        ptype = "pmtiles" if (t == "pmtiles"
                              or ref.lower().endswith(".pmtiles")) \
            else "xyz"
        uri = "type={0}&url={1}".format(ptype, enc)
        if o.get("minzoom") is not None:
            uri += "&zmin={0}".format(int(_f(o["minzoom"]) or 0))
        if o.get("maxzoom") is not None:
            uri += "&zmax={0}".format(int(_f(o["maxzoom"]) or 0))
        return QgsVectorTileLayer(uri, leaf), uri
    if t == "3dtiles":
        return QgsTiledSceneLayer(ref, leaf, "tiledscene"), ref
    if t in ("geotiff", "tiff", "cog"):
        src = ("/vsicurl/" + ref) if _is_remote(ref) else ref
        return QgsRasterLayer(src, leaf, "gdal"), src
    if t == "image":
        src = ref if not _is_remote(ref) else ref
        lyr = QgsRasterLayer(src, leaf, "gdal")
        bbox = o.get("bbox")
        if bbox and lyr.isValid():
            try:
                w, s, e, n = [float(v) for v in bbox.split(",")]
                lyr.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
                lyr.setExtent(QgsRectangle(w, s, e, n))
            except Exception:
                warnings.append(
                    "{0}: image: の bbox 適用に失敗".format(leaf))
        elif not bbox:
            warnings.append(
                "{0}: image: は bbox なし(位置合わせできない)".format(
                    leaf))
        return lyr, src
    if t in ("ept", "copc", "pointcloud"):
        provider = "copc" if ref.lower().endswith(".copc.laz") else "ept"
        return QgsPointCloudLayer(ref, leaf, provider), ref
    return None, "{0} は未対応のタイル/ラスタタイプ".format(t)


def _apply_common(layer, item, base, warnings, tmp_files):
    """style=/minScale=/maxScale=/opacity=/where=/attr をレイヤへ適用。"""
    o = item["opts"]
    leaf = _title_leaf(item["title"])
    attr = item.get("attr") or o.get("attr")
    if attr:
        try:
            layer.setAttribution(attr)
        except Exception:  # nosec B110  # 設計上の許容
            pass
    if o.get("where"):
        try:
            layer.setSubsetString(o["where"])
        except Exception as e:
            warnings.append("{0}: where= 適用失敗 {1}".format(leaf, e))
    try:
        if o.get("opacity") is not None:
            layer.setOpacity(max(0.0, min(1.0, _f(o["opacity"]) or 1.0)))
    except Exception:  # nosec B110  # 設計上の許容
        pass
    try:
        lo = _f(o.get("minscale"))
        hi = _f(o.get("maxscale"))
        if lo or hi:
            layer.setScaleBasedVisibility(True)
            if lo:
                layer.setMinimumScale(lo)
            if hi:
                layer.setMaximumScale(hi)
    except Exception:  # nosec B110  # 設計上の許容
        pass
    style_ref = o.get("style")
    if style_ref:
        path = resolve_ref(style_ref, base)
        try:
            if _is_remote(path):
                local = _fetch_to_temp(path, tmp_files)
            else:
                local = path
            if local and os.path.isfile(local):
                res = layer.loadNamedStyle(local)
                # 戻り値は版で (str,bool)/(bool,str) が揺れるため
                # bool要素を成否・str要素をメッセージとして取り出す
                ok = next(
                    (x for x in res if isinstance(x, bool)), True)
                msg = next(
                    (x for x in res if isinstance(x, str)), "")
                if not ok:
                    warnings.append(
                        "{0}: .qml 適用失敗 {1}".format(leaf, msg))
            else:
                warnings.append(
                    "{0}: .qml が見つからない: {1}".format(
                        leaf, style_ref))
        except Exception as e:
            warnings.append("{0}: style 適用失敗 {1}".format(leaf, e))
    # bbox= は Canvas 側の描画範囲制限 → QGIS のマップクリッピング
    # 領域へ変換(image: では bbox= が位置合わせ用なので除外)
    if o.get("bbox") is not None and item.get("type") != "image":
        _apply_bbox_clip(layer, o["bbox"], leaf, warnings)
    # Canvas専用オプション(3D立上げ・時間・heat/cluster等)は
    # QGIS に直接対応が無い → 未適用として報告のみ
    for k in ("extrude", "z", "time", "time_end", "time_span",
              "heat", "cluster"):
        if o.get(k) is not None:
            warnings.append(
                "{0}: {1}= はCanvas専用(未適用)".format(leaf, k))


def _apply_bbox_clip(layer, bbox, leaf, warnings):
    """bbox=minx,miny,maxx,maxy(EPSG:4326) を描画範囲制限へ変換。

    layer.setMapClippingRegion が使えるQGIS系(QGIS3)はクリッピング
    領域へ。無い系(QGIS4)はラスタなら layer.setExtent(レイヤCRSへ
    変換した矩形)へフォールバック。ベクターの範囲制限は未対応。
    """
    try:
        from qgis.core import (QgsCoordinateReferenceSystem,
                               QgsCoordinateTransform, QgsGeometry,
                               QgsProject, QgsRasterLayer,
                               QgsRectangle)
        vals = [float(v) for v in str(bbox).split(",")]
        if len(vals) != 4:
            raise ValueError("bbox は4数値(minX,minY,maxX,maxY)")
        w, s, e, n = vals
        rect = QgsRectangle(w, s, e, n)
        src = QgsCoordinateReferenceSystem("EPSG:4326")
        dst = layer.crs()
        if hasattr(layer, "setMapClippingRegion"):
            from qgis.core import QgsMapClippingRegion
            geom = QgsGeometry.fromRect(rect)
            if dst.isValid() and src != dst:
                geom.transform(QgsCoordinateTransform(
                    src, dst, QgsProject.instance()))
            try:
                layer.setMapClippingRegion(QgsMapClippingRegion(geom))
            except TypeError:
                # QGIS3の2引数(geometry, crs)版との互換
                layer.setMapClippingRegion(
                    QgsMapClippingRegion(geom, src))
        elif isinstance(layer, QgsRasterLayer):
            if dst.isValid() and src != dst:
                rect = QgsCoordinateTransform(
                    src, dst, QgsProject.instance()) \
                    .transformBoundingBox(rect)
            layer.setExtent(rect)
        else:
            warnings.append(
                "{0}: bbox= ベクターの描画範囲制限は未対応".format(
                    leaf))
    except Exception as e:
        warnings.append(
            "{0}: bbox= 適用失敗 {1}".format(leaf, e))


def _fetch_to_temp(url, tmp_files):
    """http(s)リソースを一時ファイルへ保存し、そのパスを返す。"""
    suffix = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".tmp"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    req = urllib.request.Request(
        url, headers={"User-Agent": "geo_webview-kasc_import"})
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
        with open(path, "wb") as f:
            f.write(r.read())
    tmp_files.append(path)
    return path


def _is_group_node(node):
    from qgis.core import QgsLayerTreeNode
    return node.nodeType() == QgsLayerTreeNode.NodeGroup


def _find_group(root, path_parts):
    """ルートからパスを辿ってグループノードを探す(無ければ None)。"""
    node = root
    for name in path_parts:
        found = None
        for ch in node.children():
            if _is_group_node(ch) and ch.name() == name:
                found = ch
                break
        if found is None:
            return None
        node = found
    return node


_TAG = "kasc_source"


def _ensure_group(root, path_parts, exclusive_names=None, tag=None):
    """グループパスを find-or-create で辿る。

    tag 指定時は「新規作成した」グループノードのみカスタム
    プロパティ _TAG=tag を付ける(replace 時の除去対象識別用。
    既存=ユーザ由来のグループは汚さない)。
    """
    node = root
    for name in path_parts:
        found = None
        for ch in node.children():
            if _is_group_node(ch) and ch.name() == name:
                found = ch
                break
        if found is None:
            found = node.addGroup(name)
            if tag:
                try:
                    found.setCustomProperty(_TAG, tag)
                except Exception:  # nosec B110  # QGIS版差異の許容
                    pass
        node = found
    if exclusive_names and node is not None:
        try:
            if node.name() in exclusive_names:
                node.setIsMutuallyExclusive(True)
        except Exception:  # nosec B110  # QGIS版差異の許容
            pass
    return node


def _remove_previous(proj, root, key):
    """前回同ソースで取り込んだレイヤ/空グループを除去する。

    レイヤ側は QgsMapLayer.customProperty(_TAG)、グループ側は
    ノード customProperty(_TAG)(=作成時タグのみ)で識別する。
    マップテーマは参照切れになるだけなので残す。
    戻り値は除去したレイヤ数。
    """
    removed = 0
    for lid, lyr in list(proj.mapLayers().items()):
        try:
            if lyr.customProperty(_TAG) == key:
                proj.removeMapLayer(lid)
                removed += 1
        except Exception:  # nosec B110  # 設計上の許容
            pass
    # 取込由来の空グループを下から順に掃除(親が先に空になるため
    # 深い側から削除できるよう再帰的に処理)

    def _prune(node):
        for ch in list(node.children()):
            if _is_group_node(ch):
                _prune(ch)
                try:
                    if (ch.customProperty(_TAG) == key
                            and not ch.children()):
                        node.removeChildNode(ch)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
    _prune(root)
    return removed


def import_kasc(source, iface=None, add_to_project=True,
                only_visible=False, apply_camera=True,
                group_prefix=None, replace=False, timeout=15):
    """.kasc を QGIS プロジェクトへ再構成する(GUIスレッド前提)。

    source: .kasc のローカルパス or http(s) URL
    add_to_project: True でレイヤをプロジェクトへ追加(False=生成のみ)
    only_visible: True で ``| off`` 行を取り込まない
    apply_camera: True で cam: 行(中心/縮尺/回転)をキャンバスへ適用
    group_prefix: 指定時は全レイヤをその名前のルートグループ配下へ
    replace: True で同じ source で前回取り込んだレイヤ(とそれ用に
        作られた空グループ)を除去してから取り込む(=冪等な再取込)

    戻り値: {ok, added[{title,type,layer_id}], skipped[{title,reason}],
    warnings[], groups[], themes[], cam{applied}, bases, replaced,
    source, base}
    """
    from qgis.core import (QgsCoordinateReferenceSystem,
                           QgsCoordinateTransform, QgsPointXY,
                           QgsProject)

    text, base = _read_source(source, timeout=timeout)
    doc = parse_kasc(text)
    report = {"ok": True, "source": source, "base": base,
              "title": doc["title"], "added": [], "skipped": [],
              "warnings": [], "groups": [], "themes": [],
              "cam": None, "bases": 0, "replaced": 0}
    warnings = report["warnings"]
    tmp_files = []

    proj = QgsProject.instance()
    skey = _source_key(source)
    if replace and add_to_project:
        report["replaced"] = _remove_previous(
            proj, proj.layerTreeRoot(), skey)
    root = proj.layerTreeRoot()
    if group_prefix:
        root = _ensure_group(
            root, [str(group_prefix)], tag=skey)

    # グループ挿入位置の記録(nodeごとの次index)
    pos = {}

    def _insert(node_parent, layer, visible):
        idx = pos.get(id(node_parent), 0)
        node_parent.insertLayer(idx, layer)
        pos[id(node_parent)] = idx + 1
        if not visible:
            try:
                node_parent.findLayer(layer.id()) \
                    .setItemVisibilityChecked(False)
            except Exception:  # nosec B110  # 設計上の許容
                pass

    try:
        for item in doc["layers"]:
            if only_visible and not item["visible"]:
                report["skipped"].append(
                    {"title": item["title"], "reason": "| off"})
                continue
            t = item["type"]
            try:
                if t in ("geojson", "layer", "geoparquet", "parquet",
                         "flatgeobuf", "fgb", "gpkg", "geopackage",
                         "csv", "tsv", "duckdb", "sql", "kml", "kmz",
                         "wfs", "shp", "shapefile", "fly_geojson"):
                    layer, desc = _build_vector(item, base, warnings)
                else:
                    layer, desc = _build_raster(item, base, warnings)
            except Exception as e:
                layer, desc = None, "{0}: {1}".format(t, e)
            if layer is None:
                report["skipped"].append(
                    {"title": item["title"], "reason": str(desc)})
                continue
            if not layer.isValid():
                report["skipped"].append(
                    {"title": item["title"],
                     "reason": "ソースを開けない: {0}".format(desc)})
                continue
            _apply_common(layer, item, base, warnings, tmp_files)
            if add_to_project:
                layer.setCustomProperty(_TAG, skey)
                proj.addMapLayer(layer, False)
                gpath = _title_groups(item["title"])
                excl = _exclusive_groups(item["title"])
                gnode = (_ensure_group(root, gpath, excl, tag=skey)
                         if gpath else root)
                _insert(gnode, layer, item["visible"])
            report["added"].append(
                {"title": item["title"], "type": t,
                 "layer_id": layer.id()})

        # base: 行は最下段(先勝ちの1枚目が既定ベースマップ)
        base_inserted = 0
        for item in doc["bases"]:
            if item.get("mode") in ("transparent", "none"):
                continue
            if only_visible and not item["visible"]:
                continue
            try:
                layer, desc = _build_raster(
                    dict(item, type="xyz"), base, warnings)
            except Exception as e:
                layer, desc = None, str(e)
            if layer is None or not layer.isValid():
                report["skipped"].append(
                    {"title": item["title"],
                     "reason": "base を開けない"})
                continue
            _apply_common(layer, item, base, warnings, tmp_files)
            if add_to_project:
                layer.setCustomProperty(_TAG, skey)
                proj.addMapLayer(layer, False)
                gpath = _title_groups(item["title"])
                gnode = (_ensure_group(root, gpath, tag=skey) if gpath
                         else root)
                # base はグループ末尾(=下側)へ
                gnode.addLayer(layer)
                if not item["visible"]:
                    try:
                        gnode.findLayer(layer.id()) \
                            .setItemVisibilityChecked(False)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
            base_inserted += 1
        report["bases"] = base_inserted

        # group: 行の折りたたみ状態を反映
        for g in doc["groups"]:
            path = [p.strip() for p in str(g["path"] or "").split("/")
                    if p.strip()]
            if not path:
                continue
            node = _find_group(root, path)
            if node is not None:
                try:
                    node.setExpanded(not g["collapsed"])
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            report["groups"].append(g["path"])

        # theme: 行 → マップテーマとして再構成(タイトル一致分のみ)
        if doc["themes"]:
            try:
                _apply_themes(doc, proj, root, warnings, report)
            except Exception as e:
                warnings.append("theme 復元失敗: {0}".format(e))

        # bookmark: → bookmarks.xml をインポート(対応APIがある場合)
        for b in doc["bookmarks"]:
            url = b.get("url")
            if not url:
                continue
            path = resolve_ref(url, base)
            try:
                if _is_remote(path):
                    path = _fetch_to_temp(path, tmp_files)
                mgr = proj.bookmarkManager()
                if hasattr(mgr, "importFromFile"):
                    mgr.importFromFile(path)
                    report.setdefault("bookmarks", 0)
                    report["bookmarks"] += 1
                else:
                    warnings.append(
                        "bookmarks.xml のインポートは未対応のQGIS API")
            except Exception as e:
                warnings.append(
                    "bookmark 読込失敗 {0}: {1}".format(url, e))

        # cam: → キャンバス中心/縮尺/回転を復元
        cam = next(
            (c for c in doc["cams"]
             if c.get("latitude") is not None
             and c.get("longitude") is not None), None)
        if cam and apply_camera:
            try:
                cv = iface.mapCanvas() if iface is not None else None
            except Exception:  # nosec B110  # 設計上の許容
                cv = None
            if cv is not None:
                dst = cv.mapSettings().destinationCrs()
                tr = QgsCoordinateTransform(
                    QgsCoordinateReferenceSystem("EPSG:4326"), dst,
                    proj)
                pt = tr.transform(
                    QgsPointXY(cam["longitude"], cam["latitude"]))
                cv.setCenter(pt)
                h = cam.get("height")
                if h:
                    # 送出側 _camera_line の近似式 scale*0.2 の逆算
                    cv.zoomScale(max(1.0, float(h) / 0.2))
                d = cam.get("heading")
                if d is not None:
                    cv.setRotation(float(d) % 360)
                cv.refresh()
                report["cam"] = {"applied": True, "name": cam["name"]}
            else:
                report["cam"] = {"applied": False,
                                 "reason": "canvas なし"}
        elif cam:
            report["cam"] = {"applied": False,
                             "reason": "apply_camera=False"}
        for it in doc["unsupported"]:
            report["skipped"].append(
                {"title": it.get("title") or it["type"],
                 "reason": it.get("reason", "未対応行")})
    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:  # nosec B110  # 設計上の許容
                pass
    return report


def _apply_themes(doc, proj, root, warnings, report):
    """theme: 行をマップテーマとして登録する(タイトル一致分のみ)。"""
    from qgis.core import QgsMapThemeCollection
    coll = proj.mapThemeCollection()
    if coll is None:
        warnings.append("mapThemeCollection が無い")
        return
    # プロジェクト内レイヤをタイトル(フルパス+リーフ名、
    # NFKC正規化キー)で索引。.kasc 側の表記揺れ(全半角・空白・
    # グループパス有無)を吸収する
    title_map = {}
    for lid, lyr in proj.mapLayers().items():
        node = root.findLayer(lid)
        if node is None:
            continue
        names = {lyr.name()}
        # ツリーパスを復元してフルタイトルも索引に入れる
        path = []
        p = node.parent()
        while p is not None and p != root:
            path.insert(0, p.name())
            p = p.parent()
        if path:
            names.add("/".join(path + [lyr.name()]))
        for n in names:
            title_map.setdefault(_norm_title(n), lyr)
    for theme in doc["themes"]:
        name = theme["name"] or "imported"
        wanted = set()
        for t in theme["layers"]:
            if not t:
                continue
            wanted.add(_norm_title(t))
            wanted.add(_norm_title(_title_leaf(t)))
        wanted.discard("")
        if not wanted:
            warnings.append(
                "theme '{0}': レイヤ指定なし(空テーマ)".format(name))
            continue
        record = QgsMapThemeCollection.MapThemeRecord()
        try:
            record.setHasCheckedStateInfo(True)
        except Exception:  # nosec B110  # QGIS版差異の許容
            pass
        any_hit = False
        for lid, lyr in proj.mapLayers().items():
            checked = _norm_title(lyr.name()) in wanted or any(
                title_map.get(t) is lyr for t in wanted)
            if checked:
                any_hit = True
            try:
                lr = QgsMapThemeCollection.MapThemeLayerRecord(
                    lyr, checked)
            except TypeError:
                lr = QgsMapThemeCollection.MapThemeLayerRecord(lyr)
                try:
                    lr.isVisible = bool(checked)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            record.addLayerRecord(lr)
        if not any_hit:
            warnings.append(
                "theme '{0}': タイトル一致レイヤ無し".format(name))
            continue
        coll.insert(name, record)
        report["themes"].append(name)
