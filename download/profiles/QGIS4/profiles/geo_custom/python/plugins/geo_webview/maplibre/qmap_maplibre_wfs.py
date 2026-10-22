"""WFS helper utilities for QMapPermalink MapLibre HTML generation.

This module extracts and normalizes WFS-related parameters used by the
MapLibre HTML generator. It uses QGIS API directly to convert layer styles
to MapLibre GL JS format.
"""

# Public API exported by this module
__all__ = [
    'prepare_wfs_for_maplibre',
    'qgis_layer_to_maplibre_style',
]

from typing import Dict, Any, List


def prepare_wfs_for_maplibre(permalink_text: str, wfs_typename: str = None) -> Dict[str, Any]:
    """Prepare and validate WFS-related variables for MapLibre HTML.

    This function extracts a typename from the provided permalink (unless
    `wfs_typename` is explicitly provided), url-encodes it for WFS queries,
    and — when running inside QGIS — attempts to normalize it to a canonical
    QGIS layer id. The returned dict contains the values expected by the
    MapLibre HTML template generator.

    Parameters
    ----------
    permalink_text : str
        The permalink/URL that may include query parameters such as
        `typename`/`typenames`.
    wfs_typename : Optional[str]
        Optional explicit typename to use instead of extracting from the
        permalink.

    Returns
    -------
    Dict[str, Any]
        Dictionary containing keys used by the MapLibre generator.

    Raises
    ------
    ValueError
        When no typename can be determined or when QGIS-specific validation
        fails (running inside QGIS).
    """
    from urllib.parse import quote as _quote, urlparse as _urlparse, parse_qs as _parse_qs
    import json as _jsonmod

    _final_typename = None
    if wfs_typename and str(wfs_typename).strip():
        _final_typename = str(wfs_typename)
    else:
        try:
            _p = _urlparse(permalink_text)
            _qs = _parse_qs(_p.query)
            for k in ('typename', 'typenames', 'TYPENAME', 'TYPENAMES', 'layer', 'layers', 'type', 'typeName'):
                if k in _qs and _qs[k]:
                    _final_typename = _qs[k][0]
                    break
        except Exception:
            _final_typename = None

    if not _final_typename:
        # No typename provided — return a benign response so callers can still
        # generate a MapLibre HTML without WFS layers. Use the local WMTS
        # style endpoint so base map tiles are always available.
        local_style = "/maplibre-style"
        return {
            'final_typename': None,
            'wfs_typename': '',
            'wfs_query_url': '',
            'wfs_source_id': '',
            'wfs_layer_id': '',
            'wfs_label_id': '',
            'wfs_layer_title': '',
            'wfs_label_title': '',
            'wfs_source_id_js': _jsonmod.dumps(''),
            'wfs_layer_id_js': _jsonmod.dumps(''),
            'wfs_label_id_js': _jsonmod.dumps(''),
            'wfs_layer_title_js': _jsonmod.dumps(''),
            'wfs_label_title_js': _jsonmod.dumps(''),
            'style_url': local_style,
            'mapbox_layers': [],
            'style_json': None,
            'wfs_layers_js': '',
        }

    _wfs_typename = _quote(_final_typename)
    _wfs_query_url = f"/wfs?SERVICE=WFS&REQUEST=GetFeature&TYPENAMES={_wfs_typename}&OUTPUTFORMAT=application/json&MAXFEATURES=1000"

    # Try to normalize to canonical QGIS layer id when QGIS is available
    from qgis.core import QgsProject
    from urllib.parse import unquote_plus

    try:
        decoded_try = unquote_plus(_final_typename)
    except Exception:
        decoded_try = _final_typename

    found = None
    layers_map = QgsProject.instance().mapLayers()

    if _final_typename in layers_map:
        found = _final_typename
    elif decoded_try in layers_map:
        found = decoded_try

    if not found:
        for lid, layer in layers_map.items():
            try:
                if str(lid).lstrip('_') == _final_typename or str(lid).lstrip('_') == decoded_try:
                    found = lid
                    break
                if hasattr(layer, 'name') and (layer.name() == _final_typename or layer.name() == decoded_try):
                    found = lid
                    break
            except Exception:  # nosec B112  # 設計上の許容
                continue

    if not found:
        try:
            available = list(layers_map.keys())
        except Exception:
            available = []
        raise ValueError(f"WFS typename must be a canonical QGIS layer id (layer.id()). Provided: '{_final_typename}'. Available typenames: {available}")

    _final_typename = found
    _wfs_typename = _quote(_final_typename)
    _wfs_query_url = f"/wfs?SERVICE=WFS&REQUEST=GetFeature&TYPENAMES={_wfs_typename}&OUTPUTFORMAT=application/json&MAXFEATURES=1000"

    import json as _jsonmod

    _wfs_source_id = _final_typename
    _wfs_layer_id = f"{_wfs_source_id}_layer"
    _wfs_label_id = f"{_wfs_source_id}_label"
    _wfs_layer_title = f"WFS: {_final_typename}"
    _wfs_label_title = f"WFS: {_final_typename} (labels)"

    _wfs_source_id_js = _jsonmod.dumps(_wfs_source_id)
    _wfs_layer_id_js = _jsonmod.dumps(_wfs_layer_id)
    _wfs_label_id_js = _jsonmod.dumps(_wfs_label_id)
    _wfs_layer_title_js = _jsonmod.dumps(_wfs_layer_title)
    _wfs_label_title_js = _jsonmod.dumps(_wfs_label_title)

    # 初回も追加も同一JS関数で処理するため、スタイルURLは常にベースのみを指す
    # （WFSレイヤはクライアント側で /maplibre-style?typename=... を個別取得・注入）
    # 相対パスにして現在のホスト/ポートを利用
    style_url = "/maplibre-style"

    mapbox_layers = []
    style_json = None
    wfs_layers_js = ""

    return {
        'final_typename': _final_typename,
        'wfs_typename': _wfs_typename,
        'wfs_query_url': _wfs_query_url,
        'wfs_source_id': _wfs_source_id,
        'wfs_layer_id': _wfs_layer_id,
        'wfs_label_id': _wfs_label_id,
        'wfs_layer_title': _wfs_layer_title,
        'wfs_label_title': _wfs_label_title,
        'wfs_source_id_js': _wfs_source_id_js,
        'wfs_layer_id_js': _wfs_layer_id_js,
        'wfs_label_id_js': _wfs_label_id_js,
        'wfs_layer_title_js': _wfs_layer_title_js,
        'wfs_label_title_js': _wfs_label_title_js,
        'style_url': style_url,
        'mapbox_layers': mapbox_layers,
        'style_json': style_json,
        'wfs_layers_js': wfs_layers_js,
    }


def qgis_layer_to_maplibre_style(layer_id: str, source_id: str = None) -> List[Dict[str, Any]]:
    """Convert QGIS layer style to MapLibre GL JS style layers using QGIS API directly.

    Parameters
    ----------
    layer_id : str
        QGIS layer ID
    source_id : str, optional
        MapLibre source ID to reference. If None, uses layer_id.

    Returns
    -------
    List[Dict[str, Any]]
        List of MapLibre layer definitions
    """
    try:
        from qgis.core import (
            QgsProject,
            QgsSingleSymbolRenderer, QgsCategorizedSymbolRenderer, QgsGraduatedSymbolRenderer
        )
    except ImportError:
        return []

    if source_id is None:
        source_id = layer_id

    project = QgsProject.instance()
    layer = project.mapLayer(layer_id)

    if not layer or not hasattr(layer, 'renderer'):
        return []

    renderer = layer.renderer()
    geometry_type = layer.geometryType()
    layers = []

    # Debug logging
    try:
        from qgis.core import QgsMessageLog, Qgis
        QgsMessageLog.logMessage(f'🔍 Layer: {layer.name()}, Geometry: {geometry_type}, Renderer: {type(renderer).__name__}', 'QMapPermalink', Qgis.MessageLevel.Info)
    except Exception:  # nosec B110  # 設計上の許容
        pass

    # Get renderer type
    if isinstance(renderer, QgsSingleSymbolRenderer):
        # Single symbol - one layer
        symbol = renderer.symbol()
        maplibre_layer = _convert_symbol_to_maplibre(symbol, source_id, geometry_type, len(layers))
        if maplibre_layer:
            layers.extend(maplibre_layer)

    elif isinstance(renderer, QgsCategorizedSymbolRenderer):
        # Categorized - multiple layers with filters
        for category in renderer.categories():
            symbol = category.symbol()
            value = category.value()
            field = renderer.classAttribute()

            maplibre_layer = _convert_symbol_to_maplibre(symbol, source_id, geometry_type, len(layers))
            if maplibre_layer:
                # Add filter for this category
                for layer_def in maplibre_layer:
                    # Try to convert value to number if possible
                    try:
                        numeric_value = float(value)
                        if numeric_value == int(numeric_value):
                            numeric_value = int(numeric_value)
                        layer_def['filter'] = ['==', ['get', field], numeric_value]
                    except (ValueError, TypeError):
                        layer_def['filter'] = ['==', ['get', field], str(value)]
                layers.extend(maplibre_layer)

    elif isinstance(renderer, QgsGraduatedSymbolRenderer):
        # Graduated - multiple layers with range filters
        for range_item in renderer.ranges():
            symbol = range_item.symbol()
            lower = range_item.lowerValue()
            upper = range_item.upperValue()
            field = renderer.classAttribute()

            maplibre_layer = _convert_symbol_to_maplibre(symbol, source_id, geometry_type, len(layers))
            if maplibre_layer:
                # Add range filter
                for layer_def in maplibre_layer:
                    try:
                        lower_val = float(lower)
                        upper_val = float(upper)
                        layer_def['filter'] = ['all', ['>=', ['get', field], lower_val], ['<', ['get', field], upper_val]]
                    except (ValueError, TypeError):  # nosec B110  # 設計上の許容
                        pass
                layers.extend(maplibre_layer)

    return layers


def _convert_symbol_to_maplibre(symbol, source_id: str, geometry_type, base_index: int = 0) -> List[Dict[str, Any]]:
    """Convert QgsSymbol to MapLibre layer definition(s).

    Parameters
    ----------
    symbol : QgsSymbol
        QGIS symbol to convert
    source_id : str
        MapLibre source ID
    geometry_type : QgsWkbTypes.GeometryType
        Geometry type (Point, Line, Polygon)
    base_index : int
        Base index for layer ID generation (not used, kept for compatibility)

    Returns
    -------
    List[Dict[str, Any]]
        List of MapLibre layer definitions (may be multiple for polygon with outline)
    """
    try:
        from qgis.core import (
            QgsWkbTypes,
            QgsSimpleMarkerSymbolLayer, QgsSimpleLineSymbolLayer, QgsSimpleFillSymbolLayer,
            QgsUnitTypes
        )
    except ImportError:
        return []

    if not symbol:
        return []

    # Debug logging
    try:
        from qgis.core import QgsMessageLog, Qgis
        geom_name = {QgsWkbTypes.GeometryType.PointGeometry: 'Point', QgsWkbTypes.GeometryType.LineGeometry: 'Line', QgsWkbTypes.GeometryType.PolygonGeometry: 'Polygon'}.get(geometry_type, 'Unknown')
        QgsMessageLog.logMessage(f'🔍 Converting symbol for {source_id}, geometry={geom_name}, symbol_layers={symbol.symbolLayerCount()}', 'QMapPermalink', Qgis.MessageLevel.Info)
    except Exception:  # nosec B110  # 設計上の許容
        pass

    layers = []
    # Use internal counter starting from 0 for consistent layer IDs
    layer_index = 0

    # Helper: convert QGIS render units to pixels for widths/sizes
    def _to_px(val: float, unit) -> float:
        try:
            # mm -> px (96dpi): 1mm ≒ 3.78px
            if unit == QgsUnitTypes.RenderMillimeters:
                return float(val) * 3.78
            # pixels -> px
            if unit == QgsUnitTypes.RenderPixels:
                return float(val)
            # points (1/72 inch) -> px (96dpi): 1pt = 96/72 = 1.333...
            if unit == QgsUnitTypes.RenderPoints:
                return float(val) * (96.0 / 72.0)
            # map units or others: fallback to raw (may look scale-dependent)
            return float(val)
        except Exception:
            return float(val) if isinstance(val, (int, float)) else 0.0

    # Get the first symbol layer (main style)
    if symbol.symbolLayerCount() > 0:
        symbol_layer = symbol.symbolLayer(0)

        if geometry_type == QgsWkbTypes.GeometryType.PointGeometry:
            # Point geometry - create circle layer
            paint = {}
            layout = {}

            if isinstance(symbol_layer, QgsSimpleMarkerSymbolLayer):
                # Fill color
                color = symbol_layer.color()
                if color.isValid():
                    paint['circle-color'] = color.name()
                    paint['circle-opacity'] = color.alphaF()

                # Stroke
                stroke_color = symbol_layer.strokeColor()
                if stroke_color.isValid():
                    paint['circle-stroke-color'] = stroke_color.name()
                    paint['circle-stroke-opacity'] = stroke_color.alphaF()
                    try:
                        sw = symbol_layer.strokeWidth()
                        swu = getattr(symbol_layer, 'strokeWidthUnit', lambda: QgsUnitTypes.RenderMillimeters)()
                        converted_sw = _to_px(sw, swu)
                        paint['circle-stroke-width'] = converted_sw
                        try:
                            from qgis.core import QgsMessageLog, Qgis
                            QgsMessageLog.logMessage(f'🔍 Point stroke width raw={sw} unit={swu} -> px={converted_sw}', 'QMapPermalink', Qgis.MessageLevel.Info)
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                    except Exception:
                        paint['circle-stroke-width'] = symbol_layer.strokeWidth()

                # Size
                try:
                    sz = symbol_layer.size()  # diameter in render units
                    szu = getattr(symbol_layer, 'sizeUnit', lambda: QgsUnitTypes.RenderMillimeters)()
                    px = _to_px(sz, szu)
                    paint['circle-radius'] = px / 2.0
                    try:
                        from qgis.core import QgsMessageLog, Qgis
                        QgsMessageLog.logMessage(f'🔍 Point size raw={sz} unit={szu} -> diameter_px={px} radius_px={px / 2.0}', 'QMapPermalink', Qgis.MessageLevel.Info)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                except Exception:
                    paint['circle-radius'] = symbol_layer.size() / 2

            layers.append({
                'id': f"{source_id}_circle_{layer_index}",
                'type': 'circle',
                'source': source_id,
                'paint': paint,
                'layout': layout
            })
            layer_index += 1

        elif geometry_type == QgsWkbTypes.GeometryType.LineGeometry:
            # Line geometry
            paint = {}
            layout = {}

            if isinstance(symbol_layer, QgsSimpleLineSymbolLayer):
                # Color
                color = symbol_layer.color()
                if color.isValid():
                    paint['line-color'] = color.name()
                    paint['line-opacity'] = color.alphaF()

                # Width
                try:
                    w = symbol_layer.width()
                    wu = getattr(symbol_layer, 'widthUnit', lambda: QgsUnitTypes.RenderMillimeters)()
                    converted_w = _to_px(w, wu)
                    paint['line-width'] = converted_w
                    try:
                        from qgis.core import QgsMessageLog, Qgis
                        QgsMessageLog.logMessage(f'🔍 Line width raw={w} unit={wu} -> px={converted_w}', 'QMapPermalink', Qgis.MessageLevel.Info)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                except Exception:
                    paint['line-width'] = symbol_layer.width()

                # Join and cap styles
                pen_join_style = symbol_layer.penJoinStyle()
                if pen_join_style == 0x40:  # Qt.PenJoinStyle.MiterJoin
                    layout['line-join'] = 'miter'
                elif pen_join_style == 0x80:  # Qt.PenJoinStyle.BevelJoin
                    layout['line-join'] = 'bevel'
                elif pen_join_style == 0x100:  # Qt.PenJoinStyle.RoundJoin
                    layout['line-join'] = 'round'

                pen_cap_style = symbol_layer.penCapStyle()
                if pen_cap_style == 0x00:  # Qt.PenCapStyle.FlatCap
                    layout['line-cap'] = 'butt'
                elif pen_cap_style == 0x10:  # Qt.PenCapStyle.SquareCap
                    layout['line-cap'] = 'square'
                elif pen_cap_style == 0x20:  # Qt.PenCapStyle.RoundCap
                    layout['line-cap'] = 'round'

            layers.append({
                'id': f"{source_id}_line_{layer_index}",
                'type': 'line',
                'source': source_id,
                'paint': paint,
                'layout': layout
            })
            layer_index += 1

        elif geometry_type == QgsWkbTypes.GeometryType.PolygonGeometry:
            # Polygon geometry - may have fill and/or outline

            if isinstance(symbol_layer, QgsSimpleFillSymbolLayer):
                # Fill
                fill_color = symbol_layer.color()
                has_fill = fill_color.isValid() and fill_color.alpha() > 0

                # Debug logging for polygon fill
                try:
                    from qgis.core import QgsMessageLog, Qgis
                    stroke_color = symbol_layer.strokeColor()
                    QgsMessageLog.logMessage(
                        f'🔍 Polygon: fill={fill_color.name() if fill_color.isValid() else "invalid"} '
                        f'alpha={fill_color.alpha()}, stroke={stroke_color.name() if stroke_color.isValid() else "invalid"} '
                        f'alpha={stroke_color.alpha()}, width={symbol_layer.strokeWidth()}',
                        'QMapPermalink', Qgis.MessageLevel.Info
                    )
                except Exception:  # nosec B110  # 設計上の許容
                    pass

                if has_fill:
                    paint = {
                        'fill-color': fill_color.name(),
                        'fill-opacity': fill_color.alphaF()
                    }
                    layers.append({
                        'id': f"{source_id}_fill_{layer_index}",
                        'type': 'fill',
                        'source': source_id,
                        'paint': paint,
                        'layout': {}
                    })
                    layer_index += 1

                # Outline
                stroke_color = symbol_layer.strokeColor()
                if stroke_color.isValid() and stroke_color.alpha() > 0:
                    paint = {
                        'line-color': stroke_color.name(),
                        'line-opacity': stroke_color.alphaF(),
                        'line-width': _to_px(symbol_layer.strokeWidth(), getattr(symbol_layer, 'strokeWidthUnit', lambda: QgsUnitTypes.RenderMillimeters)())
                    }
                    try:
                        sw_raw = symbol_layer.strokeWidth()
                        sw_unit = getattr(symbol_layer, 'strokeWidthUnit', lambda: QgsUnitTypes.RenderMillimeters)()
                        sw_px = _to_px(sw_raw, sw_unit)
                        from qgis.core import QgsMessageLog, Qgis
                        QgsMessageLog.logMessage(f'🔍 Polygon outline stroke raw={sw_raw} unit={sw_unit} -> px={sw_px}', 'QMapPermalink', Qgis.MessageLevel.Info)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass

                    layout = {}
                    pen_join_style = symbol_layer.penJoinStyle()
                    if pen_join_style == 0x40:  # Qt.PenJoinStyle.MiterJoin
                        layout['line-join'] = 'miter'
                    elif pen_join_style == 0x80:  # Qt.PenJoinStyle.BevelJoin
                        layout['line-join'] = 'bevel'
                    elif pen_join_style == 0x100:  # Qt.PenJoinStyle.RoundJoin
                        layout['line-join'] = 'round'

                    layers.append({
                        'id': f"{source_id}_line_{layer_index}",
                        'type': 'line',
                        'source': source_id,
                        'paint': paint,
                        'layout': layout
                    })
                    layer_index += 1

    return layers
