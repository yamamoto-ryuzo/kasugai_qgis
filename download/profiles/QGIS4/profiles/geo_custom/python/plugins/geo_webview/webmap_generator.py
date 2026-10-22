"""Minimal QMapWebMapGenerator

            var newUrl = window.location.origin + window.location.pathname + (search ? ('?' + search) : '');
            try{ newUrl = newUrl + window.location.hash; }catch(e){}
fullscreen OpenLayers HTML page pointing to the plugin's WMS. The HTML
is constructed with simple string concatenation to avoid brace-escaping
issues when embedding JavaScript.
"""

import math
import os
from typing import Any, Dict

try:
    from .i18n_json import translate_text as _translate_text, lang_code as _lang_code
except Exception:  # QGIS外・直接import時のフォールバック
    _translate_text = None
    _lang_code = None


def _pt(source: str) -> str:
    """生成HTML用の文字列を geo_webview.page カタログから翻訳する。"""
    if _translate_text is None:
        return source
    try:
        return _translate_text(os.path.dirname(os.path.abspath(__file__)), 'geo_webview.page', source)
    except Exception:
        return source


def _ptj(source: str) -> str:
    """_pt の結果を JS 文字列リテラル(クォート込み)として返す。"""
    try:
        import json
        return json.dumps(_pt(source), ensure_ascii=False)
    except Exception:
        return '""'


def _page_lang() -> str:
    try:
        return _lang_code() if _lang_code is not None else 'en'
    except Exception:
        return 'en'


# Safe logging: prefer QGIS message log when available, fallback to print
def _qmp_log(msg: str, level='INFO'):
    try:
        # QGIS 3.x: use QgsMessageLog or Qgis
        try:
            from qgis.core import QgsMessageLog, Qgis
            sev = Qgis.MessageLevel.Info
            if isinstance(level, str):
                lvl = level.upper()
                if lvl == 'WARN' or lvl == 'WARNING':
                    sev = Qgis.MessageLevel.Warning
                elif lvl == 'ERROR':
                    sev = Qgis.MessageLevel.Critical
            try:
                QgsMessageLog.logMessage(str(msg), 'QMapPermalink', sev)
                return
            except Exception:  # nosec B110  # 設計上の許容
                pass
        except Exception:  # nosec B110  # 設計上の許容
            # cannot import qgis.core here
            pass
        # fallback to QgsApplication.messageLog if present
        try:
            import qgis
            if hasattr(qgis, 'utils'):
                print(msg)
                return
        except Exception:  # nosec B110  # 設計上の許容
            pass
    except Exception:  # nosec B110  # 設計上の許容
        pass
    # final fallback
    try:
        print(msg)
    except Exception:  # nosec B110  # 設計上の許容
        pass


class QMapWebMapGenerator:
    """Simplified web map generator that assumes EPSG:3857 on the client.

    This generator produces a minimal OpenLayers page which ALWAYS uses
    EPSG:3857 for view/projection and expects incoming center coordinates
    (and bookmarks) to already be in EPSG:3857.
    """

    def __init__(self, owner: Any = None):
        self.owner = owner

    # ----------------------------------------------------------------------
    # OpenLayers + Cesium 2画面3Dページ
    # ----------------------------------------------------------------------
    def generate_ol_cesium_page(self, navigation_data: Dict[str, Any], server_host: str = 'localhost:8089') -> str:
        """左にOpenLayers(2D)・右にCesium(3D)を並べた同期ビューページを生成する。

        OL側は /wms の ImageWMS ソース、Cesium側は OSM 背景 + /wms の
        WebMapServiceImageryProvider オーバーレイ。どちらかのビューが動いた場合、
        500ms周期で反対側へ位置/ズーム/回転を同期する。
        navigation_data: x3857/y3857/lon/lat/scale/rotation/zoom を持つdict
        """
        try:
            from .scale_zoom import estimate_zoom_from_scale_maplibre
        except Exception:
            estimate_zoom_from_scale_maplibre = None

        # 中心座標(EPSG:3857 / EPSG:4326)
        x3857 = navigation_data.get('x3857')
        y3857 = navigation_data.get('y3857')
        lon = navigation_data.get('lon')
        lat = navigation_data.get('lat')
        if x3857 is None or y3857 is None:
            x3857 = float(navigation_data.get('x') or 0.0)
            y3857 = float(navigation_data.get('y') or 0.0)
        if lon is None or lat is None:
            # EPSG:3857 -> EPSG:4326 の近似逆算
            lon = math.degrees(float(x3857) / 6378137.0)
            lat = math.degrees(
                2.0 * math.atan(math.exp(float(y3857) / 6378137.0))
                - math.pi / 2.0)
        scale = navigation_data.get('scale') or 10000
        zoom = navigation_data.get('zoom')
        if zoom is None:
            if estimate_zoom_from_scale_maplibre is not None:
                zoom = estimate_zoom_from_scale_maplibre(scale)
            else:
                zoom = math.log(591657527.591555 / float(scale), 2) - 1
        rotation_deg = float(navigation_data.get('rotation') or 0.0)
        rotation_rad = -rotation_deg * math.pi / 180.0

        # scale[m/px換算] -> Cesiumの概算カメラ高さ(FOV=60deg, viewport高600px想定)
        res = float(scale) * 0.00028
        height = res * 600.0 / (2.0 * math.tan(math.radians(30.0)))
        height = max(50.0, min(height, 20000000.0))

        wms_base = 'http://{0}/wms'.format(server_host)

        html_page = u'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="initial-scale=1"/>
<title>geo_webview - OpenLayers + Cesium 3D</title>
<link rel="stylesheet" href="https://unpkg.com/ol@8.1.0/ol.css"/>
<script>window.CESIUM_BASE_URL = 'https://unpkg.com/cesium@1.120.0/Build/Cesium/';</script>
<script src="https://unpkg.com/cesium@1.120.0/Build/Cesium/Cesium.js"></script>
<link rel="stylesheet" href="https://unpkg.com/cesium@1.120.0/Build/Cesium/Widgets/widgets.css"/>
<style>
html,body{{margin:0;padding:0;height:100%;overflow:hidden}}
#wrap{{display:flex;height:100%;width:100%}}
#olmap{{flex:1 1 50%;position:relative}}
#cesium{{flex:1 1 50%;position:relative}}
#divider{{width:4px;background:#444}}
</style>
</head>
<body>
<div id="wrap">
  <div id="olmap"></div>
  <div id="divider"></div>
  <div id="cesium"></div>
</div>
<script src="https://unpkg.com/ol@8.1.0/dist/ol.js"></script>
<script>
(function(){{
  var X3857 = {x3857}, Y3857 = {y3857};
  var LON = {lon}, LAT = {lat};
  var ZOOM = {zoom}, ROT = {rot_rad};
  var HEIGHT = {height};
  var WMS = '{wms}';

  // ---- OpenLayers (2D) ----
  var wmsSource = new ol.source.ImageWMS({{
    url: WMS,
    params: {{LAYERS: ''}},
    ratio: 1,
    serverType: 'qgis'
  }});
  var map = new ol.Map({{
    target: 'olmap',
    layers: [new ol.layer.Image({{source: wmsSource}})],
    view: new ol.View({{
      center: [X3857, Y3857],
      zoom: ZOOM,
      rotation: ROT,
      projection: 'EPSG:3857'
    }})
  }});
  window.qmap_ol_map = map;

  // ---- Cesium (3D) ----
  var viewer = null;
  try {{
    viewer = new Cesium.Viewer('cesium', {{
      baseLayer: new Cesium.ImageryLayer(
        new Cesium.UrlTemplateImageryProvider({{
          url: 'https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png'
        }})),
      baseLayerPicker: false, geocoder: false, timeline: false,
      animation: false, sceneModePicker: false,
      navigationHelpButton: false, homeButton: false,
      fullscreenButton: false, infoBox: false
    }});
  }} catch (e) {{
    try {{
      viewer = new Cesium.Viewer('cesium', {{
        imageryProvider: new Cesium.UrlTemplateImageryProvider({{
          url: 'https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png'
        }}),
        baseLayerPicker: false, geocoder: false, timeline: false,
        animation: false, sceneModePicker: false
      }});
    }} catch (e2) {{ viewer = null; }}
  }}
  window.qmap_cesium_viewer = viewer;

  if (viewer) {{
    // QGIS WMS を3D側へオーバーレイ
    try {{
      var provider = new Cesium.WebMapServiceImageryProvider({{
        url: WMS,
        layers: '',
        parameters: {{TRANSPARENT: 'TRUE', FORMAT: 'image/png'}},
        tileWidth: 512, tileHeight: 512
      }});
      viewer.imageryLayers.addImageryProvider(provider);
    }} catch (e) {{}}
    // 初期カメラ位置
    try {{
      viewer.camera.setView({{
        destination: Cesium.Cartesian3.fromDegrees(LON, LAT, HEIGHT),
        orientation: {{
          heading: -ROT,
          pitch: -Cesium.Math.PI_OVER_TWO,
          roll: 0.0
        }}
      }});
    }} catch (e) {{}}
  }}

  // ---- 双方向同期 (500ms周期、変更があった側を正とする) ----
  var lastOl = {{c: null, z: null, r: null}};
  var lastCe = {{lon: null, lat: null, h: null, heading: null}};
  var applying = false;

  function olSnapshot() {{
    var v = map.getView();
    var c = v.getCenter() || [X3857, Y3857];
    return {{c: c, z: v.getZoom(), r: v.getRotation()}};
  }}
  function ceSnapshot() {{
    if (!viewer) return null;
    var p = viewer.camera.positionCartographic;
    return {{
      lon: Cesium.Math.toDegrees(p.longitude),
      lat: Cesium.Math.toDegrees(p.latitude),
      h: p.height,
      heading: viewer.camera.heading
    }};
  }}
  function eqOl(a, b) {{
    return a && b && Math.abs(a.c[0]-b.c[0]) < 1e-6 &&
           Math.abs(a.c[1]-b.c[1]) < 1e-6 &&
           Math.abs(a.z-b.z) < 1e-6 && Math.abs(a.r-b.r) < 1e-9;
  }}
  function eqCe(a, b) {{
    return a && b && Math.abs(a.lon-b.lon) < 1e-9 &&
           Math.abs(a.lat-b.lat) < 1e-9 &&
           Math.abs(a.h-b.h) < 1e-3 && Math.abs(a.heading-b.heading) < 1e-9;
  }}

  function pushToCesium(s) {{
    if (!viewer) return;
    applying = true;
    try {{
      var lon = s.c[0] / 20037508.34 * 180.0;
      var lat = Math.atan(Math.exp(s.c[1] / 20037508.34 * Math.PI)) *
                360.0 / Math.PI - 90.0;
      var res = 156543.03392 / Math.pow(2, s.z);
      var h = res * 600.0 / (2.0 * Math.tan(Math.PI / 6.0));
      h = Math.max(50, Math.min(h, 20000000));
      viewer.camera.setView({{
        destination: Cesium.Cartesian3.fromDegrees(lon, lat, h),
        orientation: {{
          heading: -s.r,
          pitch: -Cesium.Math.PI_OVER_TWO,
          roll: 0.0
        }}
      }});
      lastCe = ceSnapshot();
    }} catch (e) {{}}
    applying = false;
  }}
  function pushToOl(s) {{
    applying = true;
    try {{
      var x = s.lon * 20037508.34 / 180.0;
      var y = Math.log(Math.tan((90 + s.lat) * Math.PI / 360.0)) /
              (Math.PI / 180.0);
      y = y * 20037508.34 / 180.0;
      var res = s.h * (2.0 * Math.tan(Math.PI / 6.0)) / 600.0;
      var z = Math.log(156543.03392 / res) / Math.LN2;
      z = Math.max(0, Math.min(z, 24));
      var v = map.getView();
      v.setCenter([x, y]);
      v.setZoom(z);
      v.setRotation(-s.heading);
      lastOl = olSnapshot();
    }} catch (e) {{}}
    applying = false;
  }}

  setInterval(function() {{
    if (applying) return;
    var ol = olSnapshot();
    var ce = ceSnapshot();
    if (!eqOl(ol, lastOl) && lastOl.c !== null) {{
      pushToCesium(ol); lastOl = olSnapshot();
    }} else if (ce && lastCe.lon !== null && !eqCe(ce, lastCe)) {{
      pushToOl(ce); lastCe = ceSnapshot();
    }} else {{
      lastOl = ol; if (ce) lastCe = ce;
    }}
  }}, 500);
  lastOl = olSnapshot();
  if (viewer) lastCe = ceSnapshot();
}})();
</script>
</body>
</html>'''.format(
            x3857=x3857, y3857=y3857, lon=lon, lat=lat,
            zoom=zoom, rot_rad=rotation_rad, height=height, wms=wms_base)
        return html_page

    def generate_wms_based_html_page(self, navigation_data: Dict[str, Any], image_width: int = 800, image_height: int = 600, server_port: int = 8089) -> str:
        """Return a minimal OpenLayers HTML page assuming EPSG:3857.

        navigation_data must contain: x, y (in EPSG:3857), optional scale, rotation, bookmarks
        """
        if not navigation_data:
            navigation_data = {}
        x = navigation_data.get('x', 0)
        y = navigation_data.get('y', 0)
        rotation_deg = navigation_data.get('rotation', 0)
        scale_value = navigation_data.get('scale', None)
        bookmarks = navigation_data.get('bookmarks', [])

        try:
            import json
            bookmarks_json = json.dumps(bookmarks)
        except Exception:
            bookmarks_json = '[]'

        # Prepare a translatable prompt label for the bookmarks select
        prompt_text = 'Select bookmark'
        # Prepare a translatable prompt label for the themes select
        prompt_theme_text = 'Select theme'
        try:
            # prefer plugin owner's translation if available
            if hasattr(self, 'owner') and self.owner is not None and hasattr(self.owner, 'tr'):
                try:
                    prompt_text = self.owner.tr(prompt_text)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                try:
                    prompt_theme_text = self.owner.tr(prompt_theme_text)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            else:
                # fallback to QCoreApplication translation
                try:
                    from qgis.PyQt.QtCore import QCoreApplication
                    prompt_text = QCoreApplication.translate('geo_webview', prompt_text)
                    prompt_theme_text = QCoreApplication.translate('geo_webview', prompt_theme_text)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        except Exception:
            # best effort only
            prompt_text = prompt_text

        try:
            import math
            if scale_value is None:
                zoom = 12
            else:
                sf = float(scale_value)
                baseScale = 591657527.591555
                zoom = max(1, int(math.log2(baseScale / sf))) if sf > 0 else 12
        except Exception:
            zoom = 12

        # prepare themes json
        try:
            import json as _jsonmod
            themes_json = _jsonmod.dumps(navigation_data.get('themes', []) if isinstance(navigation_data, dict) else [])
        except Exception:
            themes_json = '[]'

        # Render server-side option lists so selects work even if client JS fails
        try:
            import html as _html_mod
            themes_options = ''
            themes = navigation_data.get('themes', [])
            if isinstance(themes, (list, tuple)) and len(themes):
                for t in themes:
                    try:
                        themes_options += f"<option value=\"{_html_mod.escape(str(t))}\">{_html_mod.escape(str(t))}</option>"
                    except Exception:  # nosec B112  # 設計上の許容
                        continue

            bookmarks_options = ''
            try:
                if isinstance(bookmarks, (list, tuple)) and len(bookmarks):
                    for b in bookmarks:
                        try:
                            name = ''
                            if isinstance(b, dict):
                                name = str(b.get('name') or b.get('displayName') or '')
                            else:
                                name = str(getattr(b, 'name', '') or getattr(b, 'displayName', '') or '')
                            val = ''
                            # Use index as value if available
                            try:
                                val = str(bookmarks.index(b))
                            except Exception:
                                val = ''
                            bookmarks_options += f"<option value=\"{_html_mod.escape(val)}\">{_html_mod.escape(name)}</option>"
                        except Exception:  # nosec B112  # 設計上の許容
                            continue
            except Exception:
                bookmarks_options = ''
        except Exception:
            themes_options = ''
            bookmarks_options = ''

        port = int(server_port)

        # If an owner (plugin) was passed in, try to reuse its URL-building
        # utilities so the OpenLayers page and the panel produce identical
        # Google Maps / Google Earth links when possible.
        google_maps_url = None
        google_earth_url = None
        try:
            if hasattr(self, 'owner') and self.owner is not None:
                nav = {
                    'type': 'coordinates',
                    'x': x,
                    'y': y,
                    'scale': scale_value,
                    'crs': 'EPSG:3857',
                    'zoom': zoom,
                }
                if hasattr(self.owner, '_build_google_maps_url'):
                    try:
                        google_maps_url = self.owner._build_google_maps_url(nav)
                    except Exception:
                        google_maps_url = None
                if hasattr(self.owner, '_build_google_earth_url'):
                    try:
                        google_earth_url = self.owner._build_google_earth_url(nav)
                    except Exception:
                        google_earth_url = None
        except Exception:
            # best-effort only; fall back to client-side calculation
            google_maps_url = None
            google_earth_url = None

        head = (
            '  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ol@10.6.1/ol.css" type="text/css">'
            '  <script src="https://cdn.jsdelivr.net/npm/ol@10.6.1/dist/ol.js"></script>'
        )

        # Prepare server-side proj4 defs for any display CRS the generator knows about
        server_proj_defs = {}
        server_proj_meta = {}
        try:
            # gather candidate codes: navigation_data may include a desired display CRS
            codes_to_embed = set()
            _display_crs = None
            try:
                _display_crs = navigation_data.get('display_crs') or navigation_data.get('displayCRS') or navigation_data.get('display_epsg') or None
            except Exception:
                _display_crs = None

            def _norm_code(v):
                if v is None:
                    return None
                s = str(v).strip()
                if s.isdigit():
                    return 'EPSG:' + s
                if s.upper().startswith('EPSG'):
                    return s.upper()
                return s
            if _display_crs:
                nc = _norm_code(_display_crs)
                if nc:
                    codes_to_embed.add(nc)
            # always include web mercator
            codes_to_embed.add('EPSG:3857')
            # try to include project CRS from QGIS if available
            try:
                import qgis.core as qgc
                try:
                    proj = None
                    try:
                        # QgsProject may not be available in some contexts
                        from qgis.core import QgsProject
                        proj = QgsProject.instance()
                    except Exception:
                        proj = None
                    if proj is not None:
                        try:
                            pcrs = proj.crs()
                            if pcrs is not None:
                                ac = None
                                try:
                                    ac = pcrs.authid()
                                except Exception:
                                    ac = None
                                if ac:
                                    codes_to_embed.add(ac)
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                # function to get proj4 from QgsCoordinateReferenceSystem

                def _crs_to_proj4(code):
                    try:
                        crs = qgc.QgsCoordinateReferenceSystem(code)
                        proj4 = None
                        try:
                            proj4 = crs.toProj4()
                        except Exception:
                            try:
                                proj4 = crs.toProj4String()
                            except Exception:
                                proj4 = None
                        if not proj4:
                            try:
                                # fallback to WKT (less ideal)
                                proj4 = crs.toWkt()
                            except Exception:
                                proj4 = None
                        return proj4
                    except Exception:
                        return None

                for code in list(codes_to_embed):
                    try:
                        p = _crs_to_proj4(code)
                        if p:
                            server_proj_defs[code] = p
                            # attempt to detect axis order (xy or yx) for the CRS
                            try:
                                axis_order = 'unknown'
                                try:
                                    # Prefer WKT axis declarations when available
                                    w = None
                                    try:
                                        w = qgc.QgsCoordinateReferenceSystem(code).toWkt()
                                    except Exception:
                                        w = None
                                    if w and 'AXIS' in str(w).upper():
                                        try:
                                            import re
                                            m = re.search(r'AXIS\s*\[\s*"([^"]+)"', str(w), re.IGNORECASE)
                                            if m:
                                                an = m.group(1).lower()
                                                if 'lat' in an or 'north' in an:
                                                    axis_order = 'yx'
                                                else:
                                                    axis_order = 'xy'
                                        except Exception:
                                            axis_order = 'unknown'
                                except Exception:
                                    axis_order = 'unknown'
                                # fallback: inspect proj4/def string for geographic longlat
                                try:
                                    s = str(p)
                                    if axis_order == 'unknown' and ('longlat' in s or '+proj=longlat' in s or 'GEOGCS' in s):
                                        # conservative fallback: assume latitude/longitude order (yx)
                                        axis_order = 'yx'
                                except Exception:  # nosec B110  # 設計上の許容
                                    pass
                                server_proj_meta[code] = {'axis_order': axis_order}
                            except Exception:
                                try:
                                    server_proj_meta[code] = {'axis_order': 'unknown'}
                                except Exception:  # nosec B110  # 設計上の許容
                                    pass
                            try:
                                # classify whether this looks like a proj4 string or WKT
                                s = str(p).strip()
                                if s.startswith('+') or s.startswith('GEOGCS') or s.startswith('PROJCS') is False and s.startswith('[') is False and '+proj' in s:
                                    _qmp_log(f"[QMapPermalink] Found proj4 for {code}: {s}")
                                else:
                                    # fallback: print WKT
                                    _qmp_log(f"[QMapPermalink] Found WKT for {code}: {s[:200]}{'...' if len(s) > 200 else ''}")
                            except Exception:
                                try:
                                    _qmp_log(f"[QMapPermalink] Found definition for {code}")
                                except Exception:  # nosec B110  # 設計上の許容
                                    pass
                        else:
                            try:
                                _qmp_log(f"[QMapPermalink] No proj4/WKT available for {code}")
                            except Exception:  # nosec B110  # 設計上の許容
                                pass
                    except Exception:
                        try:
                            _qmp_log(f"[QMapPermalink] Error obtaining definition for {code}", level='ERROR')
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                        continue
                # additionally log the request's crs if present
                try:
                    req_crs = navigation_data.get('crs') if isinstance(navigation_data, dict) else None
                    if req_crs:
                        try:
                            rc = _norm_code(req_crs)
                            if rc:
                                if rc in server_proj_defs:
                                    _qmp_log(f"[QMapPermalink] Requested CRS {rc} definition present (serverProjDefs)")
                                else:
                                    # try to resolve via PyQGIS ad-hoc for logging
                                    try:
                                        p2 = _crs_to_proj4(rc)
                                        if p2:
                                            s2 = str(p2).strip()
                                            _qmp_log(f"[QMapPermalink] Requested CRS {rc} resolved ad-hoc: {s2[:200]}{'...' if len(s2) > 200 else ''}")
                                        else:
                                            _qmp_log(f"[QMapPermalink] Requested CRS {rc} could not be resolved via PyQGIS")
                                    except Exception:
                                        _qmp_log(f"[QMapPermalink] Requested CRS {rc} resolution attempt failed", level='WARN')
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                # Log project CRS authid (EPSG) for debugging (no UI impact)
                try:
                    try:
                        from qgis.core import QgsProject
                        proj = QgsProject.instance()
                    except Exception:
                        proj = None
                    if proj is not None:
                        try:
                            pcrs = proj.crs()
                            auth = None
                            try:
                                auth = pcrs.authid()
                            except Exception:
                                auth = None
                                if auth:
                                    try:
                                        _qmp_log(f'[QMapPermalink] Project CRS authid: {auth}')
                                    except Exception:  # nosec B110  # 設計上の許容
                                        pass
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            except Exception:
                # no qgis available; leave server_proj_defs empty
                server_proj_defs = {}
                server_proj_meta = {}
        except Exception:
            server_proj_defs = {}
            server_proj_meta = {}

        # Simple JS that assumes x/y are in EPSG:3857 and sets view projection accordingly
        js_template = (
            """
    const inputX = %s;
    const inputY = %s;
    let inputCRS = 'EPSG:3857';
    try{ var __urlParams = (typeof URLSearchParams !== 'undefined') ? new URLSearchParams(window.location.search) : null; if(__urlParams){ var __p = (__urlParams.get('crs') || __urlParams.get('epsg') || null); if(__p){ __p = String(__p).trim(); try{ if(/^[0-9]+$/.test(__p)){ inputCRS = 'EPSG:' + __p; } else { inputCRS = __p; } }catch(e){} } } }catch(e){}
    // expose server-side proj4 defs and metadata to the client as objects
    const serverProjDefs = %s;
    const serverProjMeta = %s;
    var displayCRS_global = null; try{ if(typeof __urlParams !== 'undefined' && __urlParams){ var dp = __urlParams.get('display_crs') || __urlParams.get('displayCRS') || __urlParams.get('display_epsg') || __urlParams.get('epsg'); if(dp){ dp = String(dp).trim(); displayCRS_global = (/^[0-9]+$/.test(dp) ? ('EPSG:' + dp) : dp); } } }catch(e){}
    // fallback: if no explicit displayCRS provided, use inputCRS (URL 'crs' param) when it's not web mercator
    try{ if(!displayCRS_global && typeof inputCRS !== 'undefined' && inputCRS && inputCRS !== 'EPSG:3857'){ displayCRS_global = inputCRS; } }catch(e){}
    // debug: expose serverProjDefs and displayCRS to console for troubleshooting
    try{ if(typeof console !== 'undefined' && console.log){ console.log('[QMapPermalink] serverProjDefs=', serverProjDefs); console.log('[QMapPermalink] displayCRS_global=', displayCRS_global); } }catch(e){}
    // if server provided a proj4 for displayCRS, register it (load proj4.js if needed)
    try{ if(displayCRS_global && serverProjDefs && serverProjDefs[displayCRS_global]){
      (function(){
        function _reg(){
          try{
            if(typeof proj4 === 'undefined'){
              var s=document.createElement('script');
              s.src='https://cdnjs.cloudflare.com/ajax/libs/proj4js/2.8.0/proj4.js';
              s.onload=_reg;
              document.head.appendChild(s);
              return;
            }
          }catch(e){}
          try{ if(typeof console !== 'undefined' && console.log){ console.log('[QMapPermalink] registering displayCRS_global=' + displayCRS_global); console.log('[QMapPermalink] def=', serverProjDefs[displayCRS_global]); } }catch(e){}
          try{ proj4.defs(displayCRS_global, serverProjDefs[displayCRS_global]); }catch(e){}
          try{ if(typeof ol !== 'undefined' && ol.proj){ try{ if(ol.proj.proj4 && typeof ol.proj.proj4.register === 'function'){ ol.proj.proj4.register(proj4); } else if(typeof ol.proj.setProj4 === 'function'){ ol.proj.setProj4(proj4); } }catch(e){} } }catch(e){}
        }
        _reg();
      })();
    } }catch(e){}
    const mapScale = %s;
    const rotationRad = (%s || 0) * Math.PI / 180;
    // rotation in degrees (initial value from server-provided navigation data)
    const rotationDeg = (rotationRad || 0) * 180 / Math.PI;
    const bookmarks = %s;
    const themes = %s;
    const serverGoogleMapsUrl = %s;
    const serverGoogleEarthUrl = %s;
    // prefer the configured server port (useful for testing). Use explicit IPv4 (127.0.0.1) to avoid IPv6 (::1) resolution issues.
        // Determine wms base URL: prefer page origin when usable, but when opened via file://
        // or when origin is not available, fall back to the configured serverPort on 127.0.0.1.
        // Always target the plugin's WMS server port to avoid mismatched origins
        // when serving the HTML from a separate static server. Using explicit IPv4.
        const wmsBase = (function(){
            try{ if(typeof serverPort !== 'undefined' && serverPort) return 'http://127.0.0.1:' + serverPort; }catch(e){}
            return 'http://127.0.0.1:8089';
        })();
        // Use a custom ImageCanvas source so we can draw server-provided PNGs into
        // a canvas and control rotation/oversampling/imageSmoothingQuality for
        // improved visual quality when rotating raster images client-side.
        const oversample = 2; // increase to 2 for 2x supersampling
        const wmsUrlBase = wmsBase + '/wms';

    // Base WMS layer (legacy behavior): keep server-rendered image as background
    // Base WMS: request without ANGLE — we'll perform rotation client-side in the overlay
    // Base WMS should be requested at 0°; we'll let OpenLayers rotate the view client-side
    const baseWmsSource = new ol.source.ImageWMS({ url: wmsBase + '/wms', params: { 'x': inputX, 'y': inputY, 'scale': mapScale, 'crs': inputCRS, 'ANGLE': rotationDeg }, serverType: 'qgis', crossOrigin: 'anonymous' });
    const baseMapLayer = new ol.layer.Image({ source: baseWmsSource });

    // High-quality ImageCanvas overlay removed per configuration. Use only the base WMS layer.
    try{ baseMapLayer.setZIndex(0); }catch(e){}
    const map = new ol.Map({ target: 'map', layers: [ baseMapLayer ], view: new ol.View({ center: [inputX, inputY], projection: 'EPSG:3857', zoom: %d, rotation: rotationRad }) });
    // Add rotate control (north marker). Client-side rotation is allowed but no overlay redraw is performed.
    map.addControl(new ol.control.Rotate({ tipLabel: '\u5317\u5411\u304d\u306b\u56de\u8ee2', resetNorthLabel: '\u5317\u5411\u304d\u306b\u30ea\u30bb\u30c3\u30c8', autoHide: false }));
    window.map = map;
    try{ window.baseWmsSource = baseWmsSource; }catch(e){}
    // Keep legacy wmsSource references working by aliasing to baseWmsSource
    try{ if(typeof window !== 'undefined'){ try{ window.wmsSource = baseWmsSource; }catch(e){} } }catch(e){}
    // Small ON/OFF control for the base WMS layer
    (function(){
        try{
            const controlDiv = document.createElement('div');
            controlDiv.style.position = 'absolute';
            controlDiv.style.top = '8px';
            controlDiv.style.right = '158px';
            controlDiv.style.background = 'rgba(255,255,255,0.85)';
            controlDiv.style.padding = '6px 8px';
            controlDiv.style.border = '1px solid rgba(0,0,0,0.1)';
            controlDiv.style.borderRadius = '4px';
            controlDiv.style.fontSize = '12px';
            controlDiv.style.zIndex = 1000;
            controlDiv.id = 'qmp-basewms-toggle';

            const cb2 = document.createElement('input');
            cb2.type = 'checkbox';
            cb2.id = 'qmp-basewms-checkbox';
            cb2.checked = true;
            cb2.style.marginRight = '6px';

            const lbl2 = document.createElement('label');
            lbl2.htmlFor = cb2.id;
            lbl2.textContent = 'Base WMS';

            controlDiv.appendChild(cb2);
            controlDiv.appendChild(lbl2);

            const mapContainer = document.getElementById('map') || document.body;
            try{
                if(mapContainer && getComputedStyle(mapContainer).position === 'static'){
                    mapContainer.style.position = 'relative';
                }
                mapContainer.appendChild(controlDiv);
            }catch(e){ document.body.appendChild(controlDiv); }

            cb2.addEventListener('change', function(){
                try{ baseMapLayer.setVisible(cb2.checked); }catch(e){}
            });

            window.toggleBaseWms = function(state){
                try{ baseMapLayer.setVisible(!!state); cb2.checked = !!state; }catch(e){}
            };
        }catch(e){ /* fail silently */ }
    })();
        // Add ScaleLine and realtime coords display (XY in map projection + Lat/Lon)
        try{ map.addControl(new ol.control.ScaleLine({ units: 'metric' })); }catch(e){}
        (function(){
            try{
                var coordsEl = null;
                try{ coordsEl = document.getElementById('qmp-coords'); }catch(e){ coordsEl = null; }
                map.on('pointermove', function(evt){
                    try{
                        if(evt.dragging) return;
                        var c = evt.coordinate;
                        if(!c) return;
                        var ix = (c[0]||0).toFixed(3);
                        var iy = (c[1]||0).toFixed(3);
                        var ll = ol.proj.toLonLat(c, 'EPSG:3857');
                        var lat = (ll && ll[1]) ? ll[1].toFixed(6) : '';
                        var lon = (ll && ll[0]) ? ll[0].toFixed(6) : '';
                        var scaleText = '';
                        try{
                            // Display: prefer the server-provided scale (mapScale) when present
                            // This only affects the textual display in the coords box; the
                            // map view/tiles are unchanged.
                            if(typeof mapScale !== 'undefined' && mapScale){
                                scaleText = '1:' + mapScale;
                            } else {
                                var view = map.getView();
                                var res = (view && typeof view.getResolution === 'function') ? view.getResolution() : null;
                                if(res !== null){
                                    var mpu = (view && view.getProjection && view.getProjection().getMetersPerUnit) ? view.getProjection().getMetersPerUnit() : 1;
                                    var dpi = 96;
                                    var scaleDen = Math.round(res * mpu * dpi / 0.0254);
                                    scaleText = '1:' + (scaleDen.toString());
                                }
                            }
                        }catch(e){}
                        if(coordsEl){
                            var crsLabel = (function(){ try{ var v = map.getView(); if(v && v.getProjection && typeof v.getProjection().getCode === 'function') return v.getProjection().getCode(); if(v && v.getProjection && v.getProjection().getCode) return v.getProjection().getCode(); }catch(e){} return 'EPSG:3857'; })();
                            var displayPart = '';
                            try{
                                if(typeof displayCRS_global !== 'undefined' && displayCRS_global && typeof ol !== 'undefined' && ol.proj){
                                    try{
                                        var viewp = map.getView();
                                        var viewProj = (viewp && viewp.getProjection && typeof viewp.getProjection().getCode === 'function') ? viewp.getProjection().getCode() : 'EPSG:3857';
                                        var t = null;
                                        try{ t = ol.proj.transform(c, viewProj, displayCRS_global); }catch(e){ try{ t = ol.proj.transform(c, 'EPSG:3857', displayCRS_global); }catch(e){ t = null; } }
                                        if(t && t.length>=2){
                                            try{
                                                var rawX = (t[0]||0);
                                                var rawY = (t[1]||0);
                                                // If the display CRS is geographic (degrees), show as Lat Lon (y x) with higher precision.
                                                var isGeographic = false;
                                                var serverAxisOrder = null;
                                                try{ if(typeof serverProjMeta !== 'undefined' && serverProjMeta && serverProjMeta[displayCRS_global] && serverProjMeta[displayCRS_global].axis_order){ serverAxisOrder = serverProjMeta[displayCRS_global].axis_order; } }catch(e){}
                                                try{
                                                    if(typeof ol !== 'undefined' && ol.proj && typeof ol.proj.get === 'function'){
                                                        try{ var pdef = ol.proj.get(displayCRS_global); if(pdef && typeof pdef.getUnits === 'function'){ var u = pdef.getUnits(); if(u === 'degrees') isGeographic = true; } }catch(e){}
                                                    }
                                                }catch(e){}
                                                // fallback: treat EPSG:4326 as geographic if detection failed
                                                try{ if(!isGeographic && String(displayCRS_global).toUpperCase().indexOf('4326') !== -1) isGeographic = true; }catch(e){}
                                                // if server provided axis_order info and it's 'yx' we should present Lat/Lon order
                                                var forceYX = (serverAxisOrder === 'yx');
                                                if(isGeographic || forceYX){
                                                    var latv = rawY.toFixed(6);
                                                    var lonv = rawX.toFixed(6);
                                                    displayPart = ' / LatLon(' + displayCRS_global + '):' + latv  + ' '+ lonv;
                                                } else {
                                                    var dx = rawX.toFixed(3);
                                                    var dy = rawY.toFixed(3);
                                                    displayPart = ' / XY(' + displayCRS_global + '):' + dx + ' ' + dy;
                                                }
                                            }catch(e){}
                                        }
                                    }catch(e){}
                                }
                            }catch(e){}
                            coordsEl.textContent = 'XY (' + crsLabel + '):' + ix  + ' ' + iy + displayPart + ' / LatLon(EPSG:4326):' + lat  + ' ' + lon + ' / Scale: ' + scaleText;
                        }
                    }catch(e){}
                });
            }catch(e){}
        })();
            """
        )
        js = js_template % (
            json_safe(x),
            json_safe(y),
            json_safe(server_proj_defs),
            json_safe(server_proj_meta),
            json_safe(scale_value),
            rotation_deg,
            bookmarks_json,
            themes_json,
            json_safe(google_maps_url),
            json_safe(google_earth_url),
            zoom,
        )
        # replace localhost port marker with actual port number
        try:
            js = js.replace('__QMP_LOCALHOST_PORT__', str(port))
        except Exception:  # nosec B110  # 設計上の許容
            pass

        # Add a small rotate-cycle button under the OL rotate control that
        # - on first click snaps arbitrary angle to the nearest of 0/90/180/270
        # - on subsequent clicks cycles through 0 -> 90 -> 180 -> 270 -> 0
        js += (
            "(function(){\n"
            "  try{\n"
            "    var angles = [0,90,180,270];\n"
            "    function toDeg(rad){ return ((rad||0) * 180 / Math.PI); }\n"
            "    function normDeg(d){ var r = ((d % 360) + 360) % 360; return r; }\n"
            "    // 角度は10進数（度）で扱う（例: 0, 90, 180, 270）。\n"
            "    function findNearestIdx(deg){ var min=1e9; var idx=0; for(var i=0;i<angles.length;i++){ var a=angles[i]; var d1=Math.abs(a-deg); var d2=Math.abs(a-deg+360); var d3=Math.abs(a-deg-360); var dd=Math.min(d1,d2,d3); if(dd<min){ min=dd; idx=i; } } return {idx:idx, diff:min}; }\n"
            "    function applyAngle(a){ try{ var rad = a * Math.PI / 180; try{ map.getView().animate({ rotation: rad, duration: 200 }); }catch(e){ try{ map.getView().setRotation(rad); }catch(e){} } if(window.wmsSource && typeof window.wmsSource.updateParams === 'function'){ window.wmsSource.updateParams({ 'ANGLE': a }); window.wmsSource.refresh(); } try{ window._getSendAngle = function(){ return a; }; }catch(e){} }catch(e){} }\n"
            "    function ensureButton(){\n"
            "      try{ var container = document.querySelector('.ol-rotate'); if(!container) return false; var btn = document.getElementById('qmp-rotate-cycle'); if(!btn){ btn = document.createElement('button'); btn.id = 'qmp-rotate-cycle'; btn.className = 'qmp-control'; btn.title = " + _ptj(
                'Rotate 0/90/180/270') + "; btn.textContent = '\u27f3'; btn.style.marginTop = '6px'; btn.style.padding = '4px 6px'; btn.style.fontSize = '12px'; btn.style.cursor = 'pointer'; container.parentNode.insertBefore(btn, container.nextSibling); } if(!btn._qmpAttached){ btn._qmpState = btn._qmpState || { lastIdx: null }; btn.addEventListener('click', function(){ try{ var view = map.getView(); var rad = 0; try{ rad = (typeof view.getRotation === 'function') ? view.getRotation() : (view.getRotation ? view.getRotation() : 0); }catch(e){ try{ rad = view.getRotation(); }catch(e){ rad = 0; } } var deg = normDeg(toDeg(rad)); var nearest = findNearestIdx(deg); var nearestIdx = nearest.idx; var nearestDiff = nearest.diff; var tol = 0.0001; if(nearestDiff <= tol){ // already at grid angle -> advance to next\n var next = (nearestIdx + 1) % angles.length; applyAngle(angles[next]); btn._qmpState.lastIdx = next; } else { // not on-grid -> snap to nearest unless last click already snapped to same nearest\n if(btn._qmpState.lastIdx === nearestIdx){ var next2 = (nearestIdx + 1) % angles.length; applyAngle(angles[next2]); btn._qmpState.lastIdx = next2; } else { applyAngle(angles[nearestIdx]); btn._qmpState.lastIdx = nearestIdx; } } }catch(e){} }); btn._qmpAttached = true; } return true; }catch(e){ return false; }\n"
            "    }\n"
            "    if(!ensureButton()){ try{ document.addEventListener('DOMContentLoaded', function(){ try{ ensureButton(); }catch(e){} }); }catch(e){} }\n"
            "  }catch(e){}\n"
            "})();\n"
        )

        # Append bookmark population and interaction script
        js += (
            "(function(){\n"
            "  try{\n"
            "    var themeSel = document.getElementById('qmp-themes');\n"
            "    try{ var urlParams = (typeof URLSearchParams !== 'undefined') ? new URLSearchParams(window.location.search) : null; }catch(e){ urlParams = null; }\n"
            "    if(themeSel && Array.isArray(themes) && themes.length){\n"
            "      try{\n"
            "        // Avoid duplicating options when server-side already rendered them.\n"
            "        // If only the prompt option exists (or none), append client-side; otherwise skip.\n"
            "        if(typeof themeSel.options === 'undefined' || themeSel.options.length <= 1){\n"
            "          themes.forEach(function(t){ try{ var opt = document.createElement('option'); opt.value = t; opt.text = t; themeSel.appendChild(opt);}catch(e){} });\n"
            "        }\n"
            "      }catch(e){}\n"
            "      try{ var initialTheme = urlParams ? urlParams.get('theme') : null; if(initialTheme && Array.isArray(themes) && themes.indexOf(initialTheme) !== -1){ themeSel.value = initialTheme; if(window.wmsSource && typeof window.wmsSource.updateParams === 'function'){ window.wmsSource.updateParams({ 'theme': initialTheme, 'ANGLE': (typeof _getSendAngle === 'function' ? _getSendAngle() : (typeof rotationDeg !== 'undefined' ? rotationDeg : 0)) }); } } }catch(e){}\n"
            "      themeSel.addEventListener('change', function(){\n"
            "        try{\n"
            "          var sel = this.value;\n"
            "          if(window.wmsSource && typeof window.wmsSource.updateParams === 'function'){\n"
            "            if(sel && sel !== '__prompt'){\n"
            "              window.wmsSource.updateParams({ 'theme': sel, 'ANGLE': (typeof _getSendAngle === 'function' ? _getSendAngle() : (typeof rotationDeg !== 'undefined' ? rotationDeg : 0)) });\n"
            "            } else {\n"
            "              window.wmsSource.updateParams({ 'ANGLE': (typeof _getSendAngle === 'function' ? _getSendAngle() : (typeof rotationDeg !== 'undefined' ? rotationDeg : 0)) });\n"
            "            }\n"
            "            window.wmsSource.refresh();\n"
            "          }\n"
            "          try{\n"
            "            if(urlParams){\n"
            "              if(sel && sel !== '__prompt') urlParams.set('theme', sel);\n"
            "              else urlParams.delete('theme');\n"
            "              var search = urlParams.toString();\n"
            "              var newUrl = window.location.origin + window.location.pathname + (search ? ('?' + search) : '') + window.location.hash;\n"
            "              if(window.history && typeof window.history.replaceState === 'function'){\n"
            "                window.history.replaceState(null, '', newUrl);\n"
            "              }\n"
            "            }\n"
            "          }catch(e){}\n"
            "        }catch(e){}\n"
            "      });\n"
            "    }\n"
            "    var sel = document.getElementById('qmp-bookmarks');\n"
            "    if(sel && Array.isArray(bookmarks) && bookmarks.length){\n"
            "      try{\n"
            "        // If server-side already rendered bookmark options (prompt + Home etc.), avoid adding duplicates.\n"
            "        if(typeof sel.options === 'undefined' || sel.options.length <= 2){\n"
            "          bookmarks.forEach(function(b,i){ try{ var opt = document.createElement('option'); opt.value = i; opt.text = b.name || ('Bookmark ' + (i+1)); sel.appendChild(opt);}catch(e){} });\n"
            "        }\n"
            "      }catch(e){}\n"
            "      sel.addEventListener('change', function(){ try{ if(this.value === '__home' || this.value === '__prompt'){ map.getView().animate({ center: [inputX, inputY], duration: 600 }); } else { var idx = parseInt(this.value); var b = bookmarks[idx]; if(b){ var bx = parseFloat(b.x || b.orig_x || b.lon || b.lng || 0); var by = parseFloat(b.y || b.orig_y || b.lat || 0); if(isFinite(bx) && isFinite(by)){ map.getView().animate({ center: [bx, by], duration: 600 }); try{ if(window.wmsSource && typeof window.wmsSource.updateParams === 'function'){ var up = { 'x': bx, 'y': by, 'crs': 'EPSG:3857', 'ANGLE': (typeof _getSendAngle === 'function' ? _getSendAngle() : (typeof rotationDeg !== 'undefined' ? rotationDeg : 0)) }; try{ if(typeof mapScale !== 'undefined' && mapScale !== null) up.scale = mapScale; }catch(e){} try{ var currentTheme = (document.getElementById('qmp-themes') ? document.getElementById('qmp-themes').value : null); if(currentTheme && currentTheme !== '__prompt'){ up.theme = currentTheme; } }catch(e){} window.wmsSource.updateParams(up); window.wmsSource.refresh(); } }catch(e){} } } } }catch(e){} try{ this.value = '__prompt'; }catch(e){} });\n"
            "    }\n"
            "  }catch(e){}\n"
            "})();\n"
        )

        # Add button handlers that open external viewers (Google Maps / Google Earth)
        js += (
            "(function(){\n"
            "  try{\n"
            "    var btnMap = document.getElementById('qmp-open-googlemaps');\n"
            "    if(btnMap){\n"
            "      btnMap.addEventListener('click', function(){\n"
            "        try{\n"
            "          var view = map.getView(); var c = view.getCenter(); var x=c[0], y=c[1];\n"
            "          var lon = (x / 20037508.34) * 180.0; var lat = (y / 20037508.34) * 180.0;\n"
            "          lat = 180.0 / Math.PI * (2.0 * Math.atan(Math.exp(lat * Math.PI / 180.0)) - Math.PI / 2.0);\n"
            "          var zoom = view.getZoom ? Math.round(view.getZoom()) : 12;\n"
            "          // prefer server-computed URL if available\n"
            "          if(typeof serverGoogleMapsUrl !== 'undefined' && serverGoogleMapsUrl){ var w = window.open(serverGoogleMapsUrl, '_blank'); if(!w){ alert(" + _ptj(
                'Popup blocked') + "); } return; }\n"
            "          var url = 'https://www.google.com/maps/@' + encodeURIComponent(lat) + ',' + encodeURIComponent(lon) + ',' + encodeURIComponent(zoom) + 'z';\n"
            "          var w = window.open(url, '_blank'); if(!w){ alert(" + _ptj('Popup blocked') + "); }\n"
            "        }catch(e){ console.error(e); }\n"
            "      });\n"
            "    }\n"
            "  }catch(e){}\n"
            "})();\n"
            "(function(){\n"
            "  try{\n"
            "    var btnEarth = document.getElementById('qmp-open-googleearth');\n"
            "    if(btnEarth){\n"
            "      btnEarth.addEventListener('click', function(){\n"
            "        try{\n"
            "          var view = map.getView(); var c = view.getCenter(); var x=c[0], y=c[1];\n"
            "          var lon = (x / 20037508.34) * 180.0; var lat = (y / 20037508.34) * 180.0;\n"
            "          lat = 180.0 / Math.PI * (2.0 * Math.atan(Math.exp(lat * Math.PI / 180.0)) - Math.PI / 2.0);\n"
            "          // prefer server-computed URL if available\n"
            "          if(typeof serverGoogleEarthUrl !== 'undefined' && serverGoogleEarthUrl){ var w = window.open(serverGoogleEarthUrl, '_blank'); if(!w){ alert(" + _ptj(
                'Popup blocked') + "); } return; }\n"
            "          // Use Google Earth Web search link (best-effort)\n"
            "          var url = 'https://earth.google.com/web/search/' + encodeURIComponent(lat) + ',' + encodeURIComponent(lon);\n"
            "          var w = window.open(url, '_blank'); if(!w){ alert(" + _ptj('Popup blocked') + "); }\n"
            "        }catch(e){ console.error(e); }\n"
            "      });\n"
            "    }\n"
            "  }catch(e){}\n"
            "})();\n"
            "(function(){\n"
            "  try{\n"
            "    var btn = document.getElementById('qmp-open-kasugai');\n"
            "    if(btn){\n"
            "      btn.addEventListener('click', function(){\n"
            "        try{\n"
            "          btn.disabled = true;\n"
            "          fetch('kasugai').then(function(r){ return r.json(); }).then(function(j){\n"
            "            if(j && j.ok && j.url){ var w = window.open(j.url, '_blank'); if(!w){ alert(" + _ptj('Popup blocked') + "); } }\n"
            "            else if(j && j.ok){ alert(" + _ptj('Exported KASUGAI project to') + " + ' ' + (j.dir || '')); }\n"
            "            else { alert(" + _ptj('KASUGAI export failed') + " + ': ' + ((j && j.error) || 'unknown')); }\n"
            "          }).catch(function(e){ alert(" + _ptj('KASUGAI export failed') + " + ': ' + e); })\n"
            "            .finally(function(){ btn.disabled = false; });\n"
            "        }catch(e){ console.error(e); btn.disabled = false; }\n"
            "      });\n"
            "    }\n"
            "  }catch(e){}\n"
            "})();\n"
        )

        html = (
            '<!doctype html>\n'
            '<html lang="' + _page_lang() + '">\n'
            '<head>' + '\n'
            '  <meta charset="utf-8">\n'
            '  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
            + head + '\n'
            '  <style>html,body{height:100%;margin:0;padding:0}#map{width:100vw;height:100vh}#qmp-left-controls{position:absolute;left:72px;top:10px;z-index:999;display:flex;flex-direction:column;gap:8px} #qmp-right-controls{position:absolute;right:35px;top:10px;z-index:999;display:flex;flex-direction:column;gap:6px} .qmp-control{background:#fff;border-radius:4px;padding:6px 8px;box-shadow:0 2px 6px rgba(0,0,0,0.15);font-size:13px;border:1px solid rgba(0,0,0,0.06)} /* coords box on bottom-right */ #qmp-coords{position:absolute;right:10px;bottom:10px;z-index:1000;background:rgba(255,255,255,0.95);padding:6px 8px;border-radius:4px;font-size:13px;border:1px solid rgba(0,0,0,0.08)} /* CORS warning */ #qmp-cors-warning{position:absolute;left:50%;top:20px;transform:translateX(-50%);z-index:1100;background:#fff5f5;border:1px solid #ffcccc;color:#660000;padding:10px 14px;border-radius:6px;display:none;max-width:80%;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,0.12)} </style>\n'
            '</head>\n'
            '<body>\n'
            '  <div id="map"></div>\n'
            '  <div id="qmp-left-controls">\n'
            '    <select id="qmp-themes" class="qmp-control" title="' + __import__('html').escape(_pt('Themes')) + '">' + (('<option value="__prompt" selected>%s</option>' % (
                __import__('html').escape(prompt_theme_text))) if True else '') + '\n' + (themes_options if 'themes_options' in locals() else '') + '</select>\n'
            '    <select id="qmp-bookmarks" class="qmp-control" title="' + __import__('html').escape(_pt('Bookmarks')) + '">' + (('<option value="__prompt" selected>%s</option>' % (__import__('html').escape(
                prompt_text))) if True else '') + '<option value="__home">' + __import__('html').escape(_pt('Home')) + '</option>\n' + (bookmarks_options if 'bookmarks_options' in locals() else '') + '</select>\n'
            '  </div>\n'
            '  <div id="qmp-right-controls">\n'
            '    <button id="qmp-rotate-cycle" class="qmp-control" title="Rotate 0/90/180/270">\u27f3</button>\n'
            '    <button id="qmp-open-googlemaps" class="qmp-control" title="' + __import__('html').escape(_pt('Open Google Maps')) + '">MAPS</button>\n'
            '    <button id="qmp-open-googleearth" class="qmp-control" title="' + __import__('html').escape(_pt('Open Google Earth')) + '">EARTH</button>\n'
            '    <button id="qmp-open-kasugai" class="qmp-control" title="' + __import__('html').escape(_pt('Open in KASUGAI Canvas')) + '">KASUGAI</button>\n'
            '  </div>\n'
            '  <div id="qmp-coords" class="qmp-control" aria-live="polite" role="status"></div>\n'
            '  <div id="qmp-cors-warning">' +
            _pt('A CORS error occurred while loading the WMS.<br>If you opened this HTML directly via file://, serve it with a simple HTTP server or set the Access-Control-Allow-Origin header on the WMS side.') + '</div>\n'
            '  <script>\n'
            f'    const serverPort = {server_port};\n'
            f'    ' + js + '\n'
            "    try{ /* show CORS warning if page loaded via file: */ if(typeof window !== \"undefined\" && window.location && window.location.protocol === 'file:'){ try{ var el=document.getElementById(\"qmp-cors-warning\"); if(el) el.style.display='block'; }catch(e){} } }catch(e){}\n"
            '  </script>\n'
            '</body>\n'
            '</html>\n'
        )

        return html


def json_safe(v):
    # simple serializer for numbers/strings used in small f-strings above
    try:
        import json
        return json.dumps(v)
    except Exception:
        return 'null'


def save_openlayers_html_to_file(html_content: str, server_port: int = 8089) -> str:
    """Save OpenLayers HTML to a file with date-time based folder structure.

    Args:
        html_content: The HTML content to save
        server_port: The port number of the QGIS HTTP server (unused, for compatibility)

    Returns the file path where the HTML was saved.
    Similar to MapLibre: saves to {base_path}/qmap_openlayers_{timestamp}/index.html
    """
    try:
        import os
        import tempfile
        from datetime import datetime

        try:
            from qgis.PyQt.QtCore import QSettings
            settings = QSettings('GeoWebView', 'geo_webview')
            saved_path = settings.value('openlayers_output_path', None)
        except Exception:
            saved_path = None

        # Determine output directory
        if saved_path is None or saved_path == '__default__':
            # Use system temp directory with base folder
            base_dir = tempfile.gettempdir()
            output_dir = os.path.join(base_dir, 'qmap_openlayers')
            # Create base folder if it doesn't exist
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                _qmp_log(f'[OpenLayers] Failed to create base directory {output_dir}: {e}', level='WARN')
        else:
            output_dir = saved_path
            # Create custom base folder if it doesn't exist
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                _qmp_log(f'[OpenLayers] Failed to create output directory {output_dir}: {e}', level='WARN')

        # Create timestamped subdirectory
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        timestamped_dir = os.path.join(output_dir, f'qmap_openlayers_{timestamp}')

        try:
            os.makedirs(timestamped_dir, exist_ok=True)
        except Exception as e:
            _qmp_log(f'[OpenLayers] Failed to create directory {timestamped_dir}: {e}', level='WARN')
            # Fallback to tempfile.mkdtemp
            try:
                timestamped_dir = tempfile.mkdtemp(prefix='qmap_openlayers_')
                _qmp_log(f'[OpenLayers] Fallback to temp directory: {timestamped_dir}')
            except Exception:
                _qmp_log('[OpenLayers] Failed to create any output directory', level='ERROR')
                raise

        # Write HTML file
        file_path = os.path.join(timestamped_dir, 'index.html')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        _qmp_log(f'[OpenLayers] HTML saved to {file_path}')
        return file_path
    except Exception as e:
        _qmp_log(f'[OpenLayers] Error saving HTML: {e}', level='ERROR')
        raise
