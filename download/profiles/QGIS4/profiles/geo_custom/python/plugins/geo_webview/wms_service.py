
# -*- coding: utf-8 -*-
"""geo_webview WMS Service

WMS (Web Map Service) 機能を提供する専用クラス。
QGISキャンバスから地図画像を生成し、WMSプロトコルに対応。
"""

import os
import re
import multiprocessing
import threading
from typing import Optional, Dict, Any
from qgis.PyQt.QtCore import QSize, QEventLoop, QTimer


class GeoWebViewWMSService:
    """geo_webview用WMSサービスクラス

    WMS GetCapabilitiesおよびGetMapリクエストを処理し、
    QGISキャンバスから地図画像を生成します。
    """

    def __init__(self, iface, webmap_generator, server_port: int = 8089, force_epsg3857: bool = False,
                 max_render_workers: int = None, max_io_workers: int = None,
                 request_timeout_s: int = None, retry_count: int = None,
                 max_image_dimension: int = None, render_timeout_s: int = None):
        """WMSサービスを初期化

        Args:
            iface: QGISインターフェース
            webmap_generator: WebMapGeneratorインスタンス
            server_port: サーバーポート番号
            force_epsg3857: 任意のCRSを強制的にEPSG:3857として扱うかどうか
        """
        self.iface = iface
        self.webmap_generator = webmap_generator
        self.server_port = server_port
        self.force_epsg3857 = force_epsg3857

        # キャッシュ: 頻繁に使用されるレイヤー設定を保持
        self._layer_cache = {}  # {layer_id: {style_name: qml_string}}
        self._theme_cache = {}  # {theme_name: (layers, style_overrides)}
        # -- configurable defaults (can be passed to __init__ or via env vars)
        cpu_count = os.cpu_count() or multiprocessing.cpu_count() or 1
        self.max_render_workers = int(max_render_workers) if max_render_workers is not None else int(os.environ.get('QMAP_MAX_RENDER_WORKERS', max(1, int(cpu_count) - 1)))
        self.max_io_workers = int(max_io_workers) if max_io_workers is not None else int(os.environ.get('QMAP_MAX_IO_WORKERS', 20))
        self.request_timeout_s = int(request_timeout_s) if request_timeout_s is not None else int(os.environ.get('QMAP_REQUEST_TIMEOUT_S', 10))
        self.retry_count = int(retry_count) if retry_count is not None else int(os.environ.get('QMAP_RETRY_COUNT', 2))
        # max allowed image dimension (square side) to avoid memory explosion
        self.max_image_dimension = int(max_image_dimension) if max_image_dimension is not None else int(os.environ.get('QMAP_MAX_IMAGE_DIMENSION', 4096))
        # rendering timeout in seconds (used for QgsMapRendererParallelJob wait)
        self.render_timeout_s = int(render_timeout_s) if render_timeout_s is not None else int(os.environ.get('QMAP_RENDER_TIMEOUT_S', 30))
        # レンダリングはQgsProject/キャンバス設定に触れるため直列化する。
        # HTTPハンドラはスレッドプールで並列実行されるが、複数の
        # QgsMapRendererParallelJob の同時実行はQGISクラッシュを引き起こす
        self._render_lock = threading.Lock()

    def _safe_int(self, value, default: int) -> int:
        """文字列から安全にintに変換する。NaNや不正値は default を返す。"""
        try:
            # floatを経由して 'NaN' をはじく
            v = float(value)
            if v != v:  # NaN check
                return int(default)
            return int(v)
        except Exception:
            return int(default)

    def _get_canvas_extent_info(self) -> Dict[str, Any]:
        """QGISキャンバスから現在の範囲情報を取得"""
        try:
            canvas = self.iface.mapCanvas()
            if not canvas:
                return {}

            extent = canvas.extent()
            crs = canvas.mapSettings().destinationCrs()

            return {
                'extent': extent,
                'crs': crs.authid() if crs else 'EPSG:3857',
                'width': canvas.width(),
                'height': canvas.height()
            }
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"❌ Failed to get canvas extent info: {e}", "geo_webview", Qgis.MessageLevel.Warning)
            return {}

    def handle_wms_request(self, conn, params: Dict[str, list], host: Optional[str] = None) -> None:
        """WMSエンドポイントを処理 - パーマリンクパラメータにも対応"""

        # デバッグ情報

        # If this request contains standard WMS GetMap parameters (BBOX/CRS/WIDTH/HEIGHT/REQUEST=GetMap)
        # prefer handling it as a normal WMS GetMap. Only fall back to the permalink-style
        # (x/y/scale) processing when a standard GetMap is not present. This ensures
        # OpenLayers' ImageWMS requests (which include BBOX) are handled correctly and
        # the returned image aligns with OL's expected geographic extent.
        is_standard_getmap = False
        try:
            if 'REQUEST' in params and params.get('REQUEST'):
                if params.get('REQUEST', [''])[0].upper() == 'GETMAP':
                    is_standard_getmap = True
        except Exception:
            is_standard_getmap = False

        has_permalink_params = ('x' in params and 'y' in params and 'scale' in params)

        if not is_standard_getmap and has_permalink_params:
            # パーマリンクパラメータをWMSパラメータに変換してGetMapとして処理
            self._handle_permalink_as_wms_getmap(conn, params)
            return

        # 通常のWMSリクエストの処理
        request = params.get('REQUEST', [''])[0].upper()
        service = params.get('SERVICE', [''])[0].upper()

        if service != 'WMS':
            from . import http_server
            http_server.send_wms_error_response(conn, "InvalidParameterValue", "SERVICE parameter must be WMS")
            return

        if request == 'GETCAPABILITIES':
            self._handle_wms_get_capabilities(conn, params, host)
        elif request == 'GETMAP':
            self._handle_wms_get_map(conn, params)
        else:
            from . import http_server
            http_server.send_wms_error_response(conn, "InvalidRequest", f"Request {request} is not supported")

    def _handle_wms_get_capabilities(self, conn, params: Dict[str, list], host: Optional[str] = None) -> None:
        """WMS GetCapabilitiesリクエストを処理 - 動的な地図範囲に対応"""

        # QGISキャンバスから現在の範囲情報を取得
        extent_info = self._get_canvas_extent_info()

        # determine base host for OnlineResource. Prefer Host header if provided
        try:
            if host:
                base_host = host
            else:
                base_host = f"localhost:{self.server_port}"
        except Exception:
            base_host = f"localhost:{self.server_port}"
        # Build a more standards-friendly GetCapabilities response.
        # Use WMS namespace and include OWS namespace for Exception/Operations metadata.
        supported_crs = [
            "EPSG:3857",
            "EPSG:4326",
        ]

        # use canvas extent if available to populate geographic bbox
        geo_bbox = None
        try:
            if extent_info and 'extent' in extent_info and extent_info.get('crs', '').upper().endswith('4326'):
                # extent is already geographic
                ext = extent_info['extent']
                geo_bbox = (ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum())
            else:
                # default global geographic bbox
                geo_bbox = (-180, -90, 180, 90)
        except Exception:
            geo_bbox = (-180, -90, 180, 90)

        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<WMS_Capabilities version="1.3.0" xmlns="http://www.opengis.net/wms" xmlns:ows="http://www.opengis.net/ows" xmlns:xlink="http://www.w3.org/1999/xlink">
    <Service>
        <Name>WMS</Name>
        <Title>QMap</Title>
        <Abstract>Dynamic WMS service exposing the current QGIS map view</Abstract>
        <OnlineResource xlink:href="http://{base_host}/wms"/>
    </Service>
    <Capability>
        <Request>
            <GetCapabilities>
                <Format>text/xml</Format>
                <DCPType>
                    <HTTP>
                        <Get><OnlineResource xlink:href="http://{base_host}/wms"/></Get>
                        <Post><OnlineResource xlink:href="http://{base_host}/wms"/></Post>
                    </HTTP>
                </DCPType>
            </GetCapabilities>
            <GetMap>
                <Format>image/png</Format>
                <Format>image/jpeg</Format>
                <Format>image/png; mode=8bit</Format>
                <DCPType>
                    <HTTP>
                        <Get><OnlineResource xlink:href="http://{base_host}/wms"/></Get>
                        <Post><OnlineResource xlink:href="http://{base_host}/wms"/></Post>
                    </HTTP>
                </DCPType>
            </GetMap>
        </Request>
        <Exception>
            <Format>application/vnd.ogc.se_xml</Format>
            <Format>text/xml</Format>
        </Exception>
        <Layer>
            <Title>QMap</Title>
            <Abstract>Current QGIS map view exported by geo_webview</Abstract>
"""

        # add supported CRS entries
        for crs in supported_crs:
            xml_content += f"      <CRS>{crs}</CRS>\n"

        # add geographic bounding box
        xml_content += "      <EX_GeographicBoundingBox>\n"
        xml_content += f"        <westBoundLongitude>{geo_bbox[0]}</westBoundLongitude>\n"
        xml_content += f"        <eastBoundLongitude>{geo_bbox[2]}</eastBoundLongitude>\n"
        xml_content += f"        <southBoundLatitude>{geo_bbox[1]}</southBoundLatitude>\n"
        xml_content += f"        <northBoundLatitude>{geo_bbox[3]}</northBoundLatitude>\n"
        xml_content += "      </EX_GeographicBoundingBox>\n"

        # common BoundingBox entries (metric and geographic)
        xml_content += "      <BoundingBox CRS=\"EPSG:3857\" minx=\"-20037508.34\" miny=\"-20037508.34\" maxx=\"20037508.34\" maxy=\"20037508.34\"/>\n"
        xml_content += "      <BoundingBox CRS=\"EPSG:4326\" minx=\"-180\" miny=\"-90\" maxx=\"180\" maxy=\"90\"/>\n"

        # add per-project visible layers as nested Layer entries so clients can see available layer names
        try:
            visible_layers = self._get_visible_layers()
            for lyr in visible_layers:
                try:
                    lname = lyr.name()
                    lid = lyr.id()
                    xml_content += "      <Layer>\n"
                    xml_content += f"        <Name>{lid}</Name>\n"
                    xml_content += f"        <Title>{lname}</Title>\n"
                    # include supported CRS for each layer
                    for crs in supported_crs:
                        xml_content += f"        <CRS>{crs}</CRS>\n"
                    xml_content += "      </Layer>\n"
                except Exception:  # nosec B112  # 設計上の許容
                    continue
        except Exception:  # nosec B110  # 設計上の許容
            pass

        xml_content += "    </Layer>\n"
        xml_content += "  </Capability>\n"
        xml_content += "</WMS_Capabilities>"

        from . import http_server
        http_server.send_http_response(conn, 200, "OK", xml_content, content_type="text/xml; charset=utf-8")

    def _handle_wms_get_map(self, conn, params: Dict[str, list]) -> None:
        """WMS GetMapリクエストを処理 - 実際のQGIS地図画像を生成"""
        from qgis.core import QgsMessageLog, Qgis

        try:
            # WMSパラメータを解析
            width = self._safe_int(params.get('WIDTH', ['256'])[0], 256)
            height = self._safe_int(params.get('HEIGHT', ['256'])[0], 256)
            bbox = params.get('BBOX', [''])[0]
            # WMS version and CRS/SRS handling: accept both CRS (1.3.0) and SRS (1.1.1)
            wms_version = None
            if 'VERSION' in params and params.get('VERSION'):
                wms_version = params.get('VERSION', [''])[0]
            elif 'version' in params and params.get('version'):
                wms_version = params.get('version', [''])[0]
            else:
                wms_version = '1.3.0'

            # Prefer CRS (WMS 1.3.0) but fall back to SRS if provided. If neither
            # is present we must return a MissingParameterValue per OGC expectations.
            original_crs = None
            if 'CRS' in params and params.get('CRS'):
                original_crs = params.get('CRS', [''])[0]
            elif 'SRS' in params and params.get('SRS'):
                original_crs = params.get('SRS', [''])[0]
            if not original_crs:
                from . import http_server
                http_server.send_wms_error_response(conn, "MissingParameterValue", "CRS/SRS parameter is required for GetMap requests")
                return

            # テーマパラメータを取得（themeパラメータ）
            themes = params.get('theme', [''])[0] if 'theme' in params and params.get('theme') else None

            # WMS STYLES パラメータを取得（LAYERS に対応するカンマ区切り）
            styles_param = params.get('STYLES', [''])[0] if 'STYLES' in params and params.get('STYLES') else None

            # 新拡張: LABELS パラメータ (LAYERS に対応するカンマ区切りのラベルフィールド)
            labels_param = params.get('LABELS', [''])[0] if 'LABELS' in params and params.get('LABELS') else None

            # LAYERSパラメータを取得（WMSで要求される個別レイヤ指定）
            layers_param = params.get('LAYERS', [''])[0] if 'LAYERS' in params and params.get('LAYERS') else None

            # 回転パラメータを取得（WMS拡張: ANGLEパラメータ）
            rotation = 0.0
            if 'ANGLE' in params and params.get('ANGLE'):
                try:
                    rotation = float(params.get('ANGLE', ['0'])[0])
                except Exception as e:
                    rotation = 0.0
                    QgsMessageLog.logMessage(f"⚠️ Invalid ANGLE parameter: {e}, using 0°", "geo_webview", Qgis.MessageLevel.Warning)

            # Server returns the renderer's output image. Rotation is handled by the renderer.

            # If WMS 1.3.0 and CRS is EPSG:4326, axis order in BBOX is lat,lon (y,x)
            # so we need to swap coordinates when parsing. For other CRSs assume BBOX
            # is minx,miny,maxx,maxy.
            try:
                bbox_coords = [float(v) for v in bbox.split(',')] if bbox else []
                if bbox_coords and wms_version and str(wms_version).startswith('1.3') and original_crs and original_crs.upper().endswith('4326') and len(bbox_coords) == 4:
                    # incoming BBOX: miny,minx,maxy,maxx -> reorder to minx,miny,maxx,maxy
                    bbox = f"{bbox_coords[1]},{bbox_coords[0]},{bbox_coords[3]},{bbox_coords[2]}"
                else:
                    # keep as-is
                    bbox = ','.join(str(v) for v in bbox_coords) if bbox_coords else ''
            except Exception:  # nosec B110  # 設計上の許容
                # if parsing fails, keep original string
                pass
            # オプションで任意CRSを強制的にEPSG:3857として扱う
            if self.force_epsg3857:
                crs = 'EPSG:3857'
            else:
                crs = original_crs

            # リクエストで与えられたBBOXがある場合、必要なら元々のCRSからEPSG:3857に変換する
            # BBOXを変換するのは force_epsg3857 が無効な場合のみ
            if not self.force_epsg3857:
                try:
                    if bbox and original_crs and original_crs.upper() != 'EPSG:3857':
                        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
                        src_crs = QgsCoordinateReferenceSystem(original_crs)
                        tgt_crs = QgsCoordinateReferenceSystem('EPSG:3857')
                        if src_crs.isValid():
                            try:
                                coords = [float(x) for x in bbox.split(',')]
                                if len(coords) == 4:
                                    rect = QgsRectangle(coords[0], coords[1], coords[2], coords[3])
                                    transform = QgsCoordinateTransform(src_crs, tgt_crs, QgsProject.instance())
                                    rect = transform.transformBoundingBox(rect)
                                    bbox = f"{rect.xMinimum()},{rect.yMinimum()},{rect.xMaximum()},{rect.yMaximum()}"
                                    # Ensure the CRS variable matches the transformed BBOX coordinates
                                    crs = 'EPSG:3857'
                            except Exception as e:
                                QgsMessageLog.logMessage(f"⚠️ Failed to transform BBOX to EPSG:3857: {e}", "geo_webview", Qgis.MessageLevel.Warning)
                        else:
                            QgsMessageLog.logMessage(f"⚠️ Invalid source CRS: {original_crs}", "geo_webview", Qgis.MessageLevel.Warning)
                except Exception as e:
                    QgsMessageLog.logMessage(f"⚠️ BBOX transformation error: {e}", "geo_webview", Qgis.MessageLevel.Warning)

            # BBOXが指定されている場合、それを直接使用して画像を生成
            if bbox:
                try:
                    coords = [float(x) for x in bbox.split(',')]
                    if len(coords) == 4:
                        self._handle_wms_get_map_with_bbox(conn, bbox, crs, width, height, themes, rotation, layers_param, styles_param, labels_param)
                        return
                except Exception as e:
                    QgsMessageLog.logMessage(f"⚠️ Invalid BBOX format: {bbox}, error: {e}", "geo_webview", Qgis.MessageLevel.Warning)

            # BBOXが指定されていない場合、エラーレスポンスを返す
            from . import http_server
            http_server.send_wms_error_response(conn, "MissingParameterValue", "BBOX parameter is required for GetMap requests")

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            import traceback
            QgsMessageLog.logMessage(f"❌ WMS GetMap error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
            from . import http_server
            http_server.send_http_response(conn, 500, "Internal Server Error", f"WMS GetMap failed: {str(e)}")

    def _handle_wms_get_map_with_bbox(self, conn, bbox: str, crs: str, width: int, height: int, themes: str = None, rotation: float = 0.0, layers_param: str = None, styles_param: str = None, labels_param: str = None) -> None:
        """BBOX指定でWMS GetMapを処理

        Args:
            layers_param (str|None): カンマ区切りのレイヤID/名前（WMS LAYERS パラメータ）
        """
        from qgis.core import QgsMessageLog, Qgis

        try:
            # BBOXをパース
            coords = [float(x) for x in bbox.split(',')]
            if len(coords) != 4:
                raise ValueError(f"Invalid BBOX format: {bbox}")

            minx, miny, maxx, maxy = coords

            # 画像サイズの制限（設定または環境変数で上書き可能）
            max_dimension = int(self.max_image_dimension)
            if width > max_dimension or height > max_dimension:
                from . import http_server
                http_server.send_wms_error_response(conn, "InvalidParameterValue", f"Image dimensions too large. Maximum allowed: {max_dimension}x{max_dimension}")
                return

            # 独立レンダリングで画像を生成(複数スレッド同時レンダリング防止のため直列化)
            try:
                with self._render_lock:
                    image_data = self._render_map_image(width, height, bbox, crs, themes, rotation, layers_param, styles_param, labels_param)

                if image_data:
                    from . import http_server
                    # Return the renderer-produced PNG (rotation already applied by renderer)
                    # Use send_binary_response so Access-Control-Allow-Origin is included for CORS
                    try:
                        http_server.send_binary_response(conn, 200, "OK", image_data, "image/png")
                    except Exception:
                        # fallback to send_http_response if binary helper is unavailable
                        try:
                            http_server.send_http_response(conn, 200, "OK", image_data, content_type="image/png")
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                else:
                    from . import http_server
                    http_server.send_wms_error_response(conn, "InternalError", "Failed to generate map image")

            except Exception as e:
                import traceback
                QgsMessageLog.logMessage(f"❌ Map image generation error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
                from . import http_server
                http_server.send_wms_error_response(conn, "InternalError", f"Map generation failed: {str(e)}")

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            import traceback
            QgsMessageLog.logMessage(f"❌ WMS GetMap with BBOX error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
            from . import http_server
            http_server.send_http_response(conn, 500, "Internal Server Error", f"WMS GetMap processing failed: {str(e)}")

    def _handle_permalink_as_wms_getmap(self, conn, params: Dict[str, list]) -> None:
        """パーマリンクパラメータをWMS GetMapパラメータに変換して処理"""
        from qgis.core import QgsMessageLog, Qgis

        try:
            # パーマリンクパラメータを取得
            x = float(params.get('x', ['0'])[0])
            y = float(params.get('y', ['0'])[0])
            scale = float(params.get('scale', ['1000'])[0])
            crs = params.get('crs', ['EPSG:3857'])[0]
            width = self._safe_int(params.get('width', ['800'])[0], 800)
            height = self._safe_int(params.get('height', ['600'])[0], 600)
            rotation = float(params.get('rotation', ['0'])[0])

            # テーマパラメータを取得（パーマリンクから）
            theme = params.get('theme', [''])[0] if 'theme' in params else None

            # スケールからBBOXを計算
            # このプラグインでは外部インターフェースで渡される 'scale' は
            # 通常の縮尺分母（例: scale=1000 => 1:1000）として扱う想定です。
            # そのため解像度(m/px) = scale * 0.0254 / dpi を使って表示範囲を求めます。
            try:
                dpi = 96.0
                meters_per_inch = 0.0254
                pixels_per_meter = dpi / meters_per_inch
                map_width_m = (width / pixels_per_meter) * scale
                map_height_m = (height / pixels_per_meter) * scale
                half_width_meters = map_width_m / 2.0
                half_height_meters = map_height_m / 2.0
            except Exception:
                # フォールバック（以前の振る舞い）: scale を m/px として扱う
                half_width_meters = (width / 2) * scale
                half_height_meters = (height / 2) * scale

            minx = x - half_width_meters
            maxx = x + half_width_meters
            miny = y - half_height_meters
            maxy = y + half_height_meters

            bbox = f"{minx},{miny},{maxx},{maxy}"

            # WMS GetMapとして処理
            # No explicit LAYERS parameter for permalink — forward None
            self._handle_wms_get_map_with_bbox(conn, bbox, crs, width, height, theme, rotation, None)

        except Exception as e:
            import traceback
            QgsMessageLog.logMessage(f"❌ Permalink to WMS conversion error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
            from . import http_server
            http_server.send_http_response(conn, 500, "Internal Server Error", f"Permalink processing failed: {str(e)}")

    def _render_map_image(self, width, height, bbox, crs, themes=None, rotation=0.0, layers_param: str = None, styles_param: str = None, labels_param: str = None):
        """
        完全独立マップレンダリング

        Args:
            width (int): 画像幅
            height (int): 画像高さ
            bbox (str): "minx,miny,maxx,maxy" 形式の範囲
            crs (str): 座標系（例: "EPSG:4326"）
            rotation (float): 回転角度（度）、デフォルト0.0

        Returns:
            bytes: PNG画像データ（失敗時はNone）
        """
        try:
            from qgis.core import QgsMessageLog, Qgis

            QgsMessageLog.logMessage(
                f"🎨 WMS Independent Rendering: {width}x{height}, BBOX: {bbox}, CRS: {crs}, Themes: {themes}, Rotation: {rotation}°",
                "geo_webview", Qgis.MessageLevel.Info
            )

            # 1. 現在のキャンバスのマップ設定をベースにする
            map_settings = self._create_map_settings_from_canvas(width, height, crs, themes, layer_ids=layers_param, styles_param=styles_param)

            # Apply temporary labeling if LABELS param provided. We will restore originals after rendering.
            original_labeling_map = {}
            try:
                original_labeling_map = self._apply_temporary_labeling(map_settings, labels_param)
            except Exception:
                original_labeling_map = {}

            # 2. BBOXから表示範囲を設定
            # Require an explicit BBOX for independent rendering. Do not silently
            # fall back to the project extent; instead return None so the caller
            # can generate a proper WMS error response. This makes missing/invalid
            # BBOX handling explicit and debuggable.
            if not bbox:
                QgsMessageLog.logMessage("❌ Missing BBOX for independent rendering", "geo_webview", Qgis.MessageLevel.Warning)
                return None

            extent = self._parse_bbox_to_extent(bbox, crs)
            if not extent:
                QgsMessageLog.logMessage(f"❌ Failed to parse BBOX for independent rendering: {bbox}", "geo_webview", Qgis.MessageLevel.Warning)
                return None

            # For BBOX requests, prefer a fast path when rotation is zero (or extremely small):
            # simply render the requested extent at the requested size. For non-zero rotation
            # use the expanded-render -> inverse-rotate -> center-crop -> resample pipeline.
            # This preserves the unified behavior for rotated requests while avoiding the
            # heavy image-space processing when not needed.
            try:
                # parse original bbox coords
                coords = [float(x) for x in bbox.split(',')]
                if len(coords) != 4:
                    QgsMessageLog.logMessage(f"❌ Invalid BBOX for rotation handling: {bbox}", "geo_webview", Qgis.MessageLevel.Warning)
                    return None
                aminx, aminy, amaxx, amaxy = coords

                # center of original bbox
                cx = (aminx + amaxx) / 2.0
                cy = (aminy + amaxy) / 2.0

                import math as _math
                ang = float(rotation) * _math.pi / 180.0

                # If rotation is effectively zero, take the fast/simple render path
                if abs(ang) <= 1e-12:
                    try:
                        # set extent and output size to requested and render directly
                        map_settings.setExtent(self._parse_bbox_to_extent(bbox, crs))
                        map_settings.setOutputSize(QSize(width, height))
                        map_settings.setOutputDpi(96)
                        # avoid setting rotation (or set to 0 explicitly)
                        if hasattr(map_settings, 'setRotation'):
                            map_settings.setRotation(0.0)

                        image = self._execute_parallel_rendering(map_settings)
                        if not image or image.isNull():
                            QgsMessageLog.logMessage("❌ WMS rendering produced no image (fast path)", "geo_webview", Qgis.MessageLevel.Warning)
                            return None
                        png_data = self._save_image_as_png(image)
                        if png_data:
                            return png_data
                        QgsMessageLog.logMessage("❌ WMS rendering failed (fast path, png conversion)", "geo_webview", Qgis.MessageLevel.Warning)
                        return None
                    except Exception as e:
                        from qgis.core import QgsMessageLog, Qgis
                        QgsMessageLog.logMessage(f"❌ Fast-path rendering error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                        return None

                def _rot(px, py, cx, cy, a):
                    dx = px - cx
                    dy = py - cy
                    rx = dx * _math.cos(a) - dy * _math.sin(a)
                    ry = dx * _math.sin(a) + dy * _math.cos(a)
                    return cx + rx, cy + ry

                # rotated corners of original bbox
                corners = [
                    _rot(aminx, aminy, cx, cy, ang),
                    _rot(aminx, amaxy, cx, cy, ang),
                    _rot(amaxx, aminy, cx, cy, ang),
                    _rot(amaxx, amaxy, cx, cy, ang),
                ]
                bx_min = min([p[0] for p in corners])
                bx_max = max([p[0] for p in corners])
                by_min = min([p[1] for p in corners])
                by_max = max([p[1] for p in corners])

                # expanded extent (B) that fully contains rotated original bbox
                bminx, bminy, bmaxx, bmaxy = bx_min, by_min, bx_max, by_max

                # determine render size: to keep pixel density, scale render size by factor = max(B.width / A.width, B.height / A.height)
                aw = amaxx - aminx
                ah = amaxy - aminy
                bw = bmaxx - bminx
                bh = bmaxy - bminy
                if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
                    QgsMessageLog.logMessage("❌ Invalid geometry when computing expanded extent for rotation", "geo_webview", Qgis.MessageLevel.Warning)
                    return None

                # compute render size so that pixel-per-map-unit matches original requested mapping
                # クロップ後のサイズが要求サイズに近づくように、より正確に計算
                try:
                    # 要求されたピクセル密度を計算
                    pixels_per_map_x = float(width) / float(aw)
                    pixels_per_map_y = float(height) / float(ah)

                    # 拡大範囲のレンダリングサイズを計算（丸め誤差を最小化）
                    render_w = max(1, int(bw * pixels_per_map_x + 0.5))
                    render_h = max(1, int(bh * pixels_per_map_y + 0.5))
                except Exception:
                    # fallback to conservative scaling
                    scale_factor = max(bw / aw, bh / ah)
                    render_w = max(1, int(round(width * scale_factor)))
                    render_h = max(1, int(round(height * scale_factor)))

                # clamp render size to reasonable maximum to avoid memory explosion
                max_dimension = int(self.max_image_dimension)
                if render_w > max_dimension:
                    render_w = max_dimension
                if render_h > max_dimension:
                    render_h = max_dimension

                # configure map_settings for expanded extent and rotation
                from qgis.PyQt.QtCore import Qt
                map_settings.setExtent(self._parse_bbox_to_extent(f"{bminx},{bminy},{bmaxx},{bmaxy}", crs))
                map_settings.setOutputSize(QSize(render_w, render_h))
                map_settings.setOutputDpi(96)
                if hasattr(map_settings, 'setRotation'):
                    map_settings.setRotation(float(rotation))

                # perform rendering
                big_image = self._execute_parallel_rendering(map_settings)
                if not big_image or big_image.isNull():
                    QgsMessageLog.logMessage("❌ Rotated rendering produced no image", "geo_webview", Qgis.MessageLevel.Warning)
                    return None

                # Instead of attempting to map rotated coords to pixels (which is fragile
                # when renderer applies rotation), perform an image-space inverse rotation
                # then center-crop the region corresponding to the original bbox and resample.
                try:
                    from qgis.PyQt.QtGui import QTransform

                    # rotate whole image by -rotation to make content north-up
                    inv_transform = QTransform()
                    # rotate around image center
                    img_w0 = big_image.width()
                    img_h0 = big_image.height()
                    cx_img = img_w0 / 2.0
                    cy_img = img_h0 / 2.0
                    # translate to center, rotate, translate back
                    try:
                        inv_transform.translate(cx_img, cy_img)
                        inv_transform.rotate(-float(rotation))
                        inv_transform.translate(-cx_img, -cy_img)
                    except Exception:
                        # fallback: simple rotate
                        inv_transform = QTransform()
                        inv_transform.rotate(-float(rotation))
                    try:
                        # Normalize rotation to [0,360)
                        try:
                            deg_norm = (float(rotation) % 360 + 360) % 360
                        except Exception:
                            deg_norm = float(rotation)

                        # Fast paths for 90-degree multiples
                        if abs(deg_norm - 180.0) < 1e-6:
                            # 180° rotation can be executed as a mirror in both axes
                            try:
                                big_rotated = big_image.mirrored(True, True)
                            except Exception:
                                # fallback to general transform
                                big_rotated = big_image.transformed(inv_transform, Qt.TransformationMode.SmoothTransformation)
                        elif abs(deg_norm - 90.0) < 1e-6 or abs(deg_norm - 270.0) < 1e-6:
                            # 90/270 can use a transform but prefer FastTransformation for performance
                            try:
                                big_rotated = big_image.transformed(inv_transform, Qt.TransformationMode.FastTransformation)
                            except Exception:
                                try:
                                    big_rotated = big_image.transformed(inv_transform, Qt.TransformationMode.SmoothTransformation)
                                except Exception:
                                    big_rotated = big_image.transformed(inv_transform)
                        else:
                            # general arbitrary-angle inverse rotation (slower, high-quality)
                            try:
                                big_rotated = big_image.transformed(inv_transform, Qt.TransformationMode.SmoothTransformation)
                            except Exception:
                                big_rotated = big_image.transformed(inv_transform)
                    except Exception:
                        # final fallback: try general transform without explicit quality flag
                        try:
                            big_rotated = big_image.transformed(inv_transform)
                        except Exception:
                            big_rotated = big_image

                    # compute pixel-per-map-unit in the original big image
                    pixels_per_map_x = float(render_w) / float(bw)
                    pixels_per_map_y = float(render_h) / float(bh)

                    # compute crop size in pixels corresponding to original bbox A
                    # 要求サイズに正確に一致させる（丸め誤差を最小化）
                    crop_w_px = width
                    crop_h_px = height

                    # center-crop around image center (map center corresponds to image center)
                    img_w = big_rotated.width()
                    img_h = big_rotated.height()
                    cx_px = int(img_w // 2)
                    cy_px = int(img_h // 2)

                    px_min = int(cx_px - (crop_w_px // 2))
                    py_min = int(cy_px - (crop_h_px // 2))

                    # clamp
                    if px_min < 0:
                        px_min = 0
                    if py_min < 0:
                        py_min = 0
                    if px_min + crop_w_px > img_w:
                        crop_w_px = img_w - px_min
                    if py_min + crop_h_px > img_h:
                        crop_h_px = img_h - py_min

                    cropped = big_rotated.copy(px_min, py_min, crop_w_px, crop_h_px)

                    # 拡大縮小を避けるため、クロップサイズが要求サイズと一致するようにレンダリングサイズを調整済み
                    # もしサイズが若干異なる場合のみ、高品質でリサイズ
                    if cropped.width() != width or cropped.height() != height:
                        try:
                            scaled = cropped.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        except Exception:
                            scaled = cropped.scaled(width, height)
                        png_data = self._save_image_as_png(scaled)
                    else:
                        # サイズが一致する場合はそのまま使用（画質劣化なし）
                        png_data = self._save_image_as_png(cropped)
                except Exception as e:
                    QgsMessageLog.logMessage(f"❌ Rotated image post-processing failed: {e}", "geo_webview", Qgis.MessageLevel.Warning)
                    return None
                if png_data:
                    return png_data
                QgsMessageLog.logMessage("❌ Rotated WMS rendering failed (png conversion)", "geo_webview", Qgis.MessageLevel.Warning)
                return None

            except Exception as e:
                from qgis.core import QgsMessageLog, Qgis
                import traceback
                QgsMessageLog.logMessage(f"❌ Rotated rendering error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                QgsMessageLog.logMessage(f"❌ Traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
                return None

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            import traceback
            QgsMessageLog.logMessage(f"❌ WMS rendering error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
            return None
        finally:
            # restore any temporary labeling we applied
            try:
                if 'original_labeling_map' in locals() and original_labeling_map:
                    try:
                        self._restore_labeling(original_labeling_map)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
            except Exception:  # nosec B110  # 設計上の許容
                pass

    def _apply_label_rotation_only(self, map_settings, rotation):
        """ラベルのみを指定角度で回転させる（画像は回転させない）。

        map_settings のレイヤを巡回し、ラベルが有効なベクタレイヤについて
        現在の labeling オブジェクトを保存してから、一時的に回転設定を持つ
        新しいラベリングに差し替えます。戻すために {layer: original_labeling} の辞書を返します。
        """
        original_labelings = {}
        try:
            from qgis.core import QgsMessageLog, Qgis, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsPalLayerSettings

            layers = map_settings.layers()
            for layer in layers:
                try:
                    if isinstance(layer, QgsVectorLayer) and layer.labelsEnabled():
                        orig_labeling = layer.labeling()
                        original_labelings[layer] = orig_labeling

                        # 対応するラベリング型に応じて回転を適用
                        if isinstance(orig_labeling, QgsVectorLayerSimpleLabeling):
                            pal = orig_labeling.settings()
                            if pal:
                                pal_copy = QgsPalLayerSettings(pal)
                                pal_copy.rotation = rotation
                                new_labeling = QgsVectorLayerSimpleLabeling(pal_copy)
                                layer.setLabeling(new_labeling)
                            else:
                                QgsMessageLog.logMessage(f"⚠️ No PAL settings in labeling for layer '{layer.name()}'", "geo_webview", Qgis.MessageLevel.Warning)
                        else:
                            # 試しに QgsPalLayerSettings でラップして適用
                            try:
                                pal_try = QgsPalLayerSettings(orig_labeling)
                                pal_try.rotation = rotation
                                new_labeling = QgsVectorLayerSimpleLabeling(pal_try)
                                layer.setLabeling(new_labeling)
                            except Exception:
                                QgsMessageLog.logMessage(f"⚠️ Unsupported labeling type for layer '{layer.name()}': {type(orig_labeling)}", "geo_webview", Qgis.MessageLevel.Warning)
                except Exception as e:
                    from qgis.core import QgsMessageLog, Qgis
                    QgsMessageLog.logMessage(f"⚠️ Failed processing layer for label-only rotation: {e}", "geo_webview", Qgis.MessageLevel.Warning)

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            import traceback
            QgsMessageLog.logMessage(f"❌ _apply_label_rotation_only error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            QgsMessageLog.logMessage(f"❌ Traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)

        return original_labelings

    def _apply_temporary_labeling(self, map_settings, labels_param: str = None):
        """LABELS パラメータに基づき、レンダリング前に一時的にラベルを設定して有効化する

        戻り値: {layer: (original_labeling, original_enabled)} の辞書
        """
        originals = {}
        try:
            if not labels_param:
                return originals

            from qgis.core import QgsMessageLog, Qgis, QgsVectorLayer, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling

            fields = [s.strip() for s in str(labels_param).split(',')]
            layers = map_settings.layers()
            for idx, layer in enumerate(layers):
                try:
                    if not isinstance(layer, QgsVectorLayer):
                        continue

                    field = fields[idx] if idx < len(fields) else None
                    if not field:
                        continue

                    orig_labeling = None
                    orig_enabled = False
                    try:
                        orig_labeling = layer.labeling()
                    except Exception:
                        orig_labeling = None
                    try:
                        orig_enabled = bool(layer.labelsEnabled())
                    except Exception:
                        orig_enabled = False

                    originals[layer] = (orig_labeling, orig_enabled)

                    # create simple labeling using field
                    pal = QgsPalLayerSettings()
                    pal.enabled = True
                    pal.fieldName = field
                    # create simple labeling object
                    labeling = QgsVectorLayerSimpleLabeling(pal)
                    layer.setLabeling(labeling)
                    layer.setLabelsEnabled(True)

                    QgsMessageLog.logMessage(f"🔤 Temporarily enabled labels for '{layer.name()}' using field '{field}'", "geo_webview", Qgis.MessageLevel.Info)
                except Exception as e:
                    QgsMessageLog.logMessage(f"⚠️ Failed to apply temporary labeling for layer '{getattr(layer, 'name', lambda: '<unknown>')()}': {e}", "geo_webview", Qgis.MessageLevel.Warning)

        except Exception as e:
            try:
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(f"❌ _apply_temporary_labeling error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            except Exception:  # nosec B110  # 設計上の許容
                pass

        return originals

    def _restore_labeling(self, originals: dict):
        """Apply original labeling objects and enabled flags back to layers."""
        try:
            from qgis.core import QgsMessageLog, Qgis
            for layer, (orig_labeling, orig_enabled) in list(originals.items()):
                try:
                    # restore labeling and enabled flag
                    try:
                        layer.setLabeling(orig_labeling)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                    try:
                        layer.setLabelsEnabled(bool(orig_enabled))
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                except Exception as e:
                    QgsMessageLog.logMessage(f"⚠️ Failed to restore labeling for layer '{getattr(layer, 'name', lambda: '<unknown>')()}': {e}", "geo_webview", Qgis.MessageLevel.Warning)
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _create_map_settings_from_canvas(self, width, height, crs, themes=None, layer_ids: str = None, styles_param: str = None):
        """完全に独立した仮想マップビューを作成してWMS用のマップ設定を構築"""
        from qgis.core import (
            QgsMapSettings, QgsCoordinateReferenceSystem, QgsProject,
            QgsMessageLog, Qgis
        )
        from qgis.PyQt.QtXml import QDomDocument

        # 完全に新規のマップ設定を作成（可能ならキャンバスの mapSettings をコピーして
        # ラベルやその他の表示設定を保持する）
        canvas = None
        try:
            canvas = self.iface.mapCanvas()
        except Exception:
            canvas = None
        try:
            # Copy existing canvas settings to preserve per-layer labeling and other state
            map_settings = QgsMapSettings(canvas.mapSettings())
        except Exception:
            map_settings = QgsMapSettings()

        # Ensure requested output size and DPI override the copied settings
        try:
            map_settings.setOutputSize(QSize(width, height))
        except Exception:  # nosec B110  # 設計上の許容
            pass
        try:
            map_settings.setOutputDpi(96)
        except Exception:  # nosec B110  # 設計上の許容
            pass

        # レンダリング最適化設定を適用
        try:
            if hasattr(map_settings, 'setFlag'):
                # UseRenderingOptimization: レンダリング最適化を有効化
                try:
                    flag = getattr(QgsMapSettings, 'UseRenderingOptimization', None)
                    if flag is not None:
                        map_settings.setFlag(flag, True)
                except Exception:  # nosec B110  # 設計上の許容
                    pass

                # DrawEditingInfo を無効化(編集情報の描画をスキップ)
                try:
                    flag = getattr(QgsMapSettings, 'DrawEditingInfo', None)
                    if flag is not None:
                        map_settings.setFlag(flag, False)
                except Exception:  # nosec B110  # 設計上の許容
                    pass

                # RenderMapTile: タイルレンダリング最適化(タイル境界のクリップを最適化)
                try:
                    flag = getattr(QgsMapSettings, 'RenderMapTile', None)
                    if flag is not None:
                        map_settings.setFlag(flag, True)
                except Exception:  # nosec B110  # 設計上の許容
                    pass

                # Antialiasing: アンチエイリアスを有効化して高品質化(画質優先)
                try:
                    flag = getattr(QgsMapSettings, 'Antialiasing', None)
                    if flag is not None:
                        map_settings.setFlag(flag, True)
                except Exception:  # nosec B110  # 設計上の許容
                    pass

                # HighQualityImageTransforms: 高品質変換を有効化(画質優先)
                try:
                    flag = getattr(QgsMapSettings, 'HighQualityImageTransforms', None)
                    if flag is not None:
                        map_settings.setFlag(flag, True)
                except Exception:  # nosec B110  # 設計上の許容
                    pass

            # パスリゾルバを設定してキャッシュ効率化
            if hasattr(map_settings, 'setPathResolver'):
                try:
                    map_settings.setPathResolver(QgsProject.instance().pathResolver())
                except Exception:  # nosec B110  # 設計上の許容
                    pass

            # SimplifyGeometry: ジオメトリ簡略化を有効化(大きなベクターレイヤーの高速化)
            try:
                if hasattr(map_settings, 'setSimplifyMethod'):
                    from qgis.core import QgsVectorSimplifyMethod
                    simplify_method = QgsVectorSimplifyMethod()
                    simplify_method.setSimplifyHints(QgsVectorSimplifyMethod.GeometrySimplification)
                    simplify_method.setSimplifyAlgorithm(QgsVectorSimplifyMethod.Distance)
                    simplify_method.setTolerance(1.0)  # ピクセル単位の許容誤差
                    map_settings.setSimplifyMethod(simplify_method)
            except Exception:  # nosec B110  # 設計上の許容
                pass

        except Exception as e:
            QgsMessageLog.logMessage(f"⚠️ Rendering optimization setup failed: {e}", "geo_webview", Qgis.MessageLevel.Warning)

        # 座標系の設定
        if crs:
            target_crs = QgsCoordinateReferenceSystem(crs)
            if target_crs.isValid():
                map_settings.setDestinationCrs(target_crs)

        project = QgsProject.instance()

        # If explicit layer ids or names are provided (via WMS LAYERS param), prefer them.
        if layer_ids:
            try:
                ids = [s.strip() for s in str(layer_ids).split(',') if s.strip()]
                resolved_layers = []
                for lid in ids:
                    # first try as ID
                    lyr = project.mapLayer(lid) if hasattr(project, 'mapLayer') else None
                    if not lyr:
                        # fall back to lookup by name
                        try:
                            candidates = project.mapLayersByName(lid)
                            if candidates:
                                lyr = candidates[0]
                        except Exception:
                            lyr = None
                    if lyr and lyr.isValid():
                        resolved_layers.append(lyr)
                if resolved_layers:
                    map_settings.setLayers(resolved_layers)

                    # If STYLES parameter provided, attempt to apply per-layer styles
                    layer_style_overrides = {}
                    if styles_param:
                        try:
                            style_names = [s for s in str(styles_param).split(',')]
                        except Exception:
                            style_names = []

                        for idx, lyr in enumerate(resolved_layers):
                            style_name = ''
                            if idx < len(style_names):
                                try:
                                    style_name = style_names[idx].strip()
                                except Exception:
                                    style_name = ''

                            if not style_name:
                                continue

                            try:
                                cache_for_layer = self._layer_cache.setdefault(lyr.id(), {})
                                if style_name in cache_for_layer:
                                    layer_style_overrides[lyr.id()] = cache_for_layer[style_name]
                                    continue

                                style_manager = lyr.styleManager()
                                if style_name in style_manager.styles():
                                    try:
                                        original_style = style_manager.currentStyle()
                                    except Exception:
                                        original_style = None
                                    try:
                                        style_manager.setCurrentStyle(style_name)
                                        doc = QDomDocument()
                                        error_msg = lyr.exportNamedStyle(doc)
                                        if not error_msg:
                                            qml_string = doc.toString()
                                            layer_style_overrides[lyr.id()] = qml_string
                                            cache_for_layer[style_name] = qml_string
                                            QgsMessageLog.logMessage(
                                                f"✅ Applied style '{style_name}' to '{lyr.name()}'",
                                                "geo_webview", Qgis.MessageLevel.Info
                                            )
                                        else:
                                            QgsMessageLog.logMessage(
                                                f"⚠️ Style export failed for '{lyr.name()}': {error_msg}",
                                                "geo_webview", Qgis.MessageLevel.Warning
                                            )
                                    finally:
                                        if original_style is not None:
                                            try:
                                                style_manager.setCurrentStyle(original_style)
                                            except Exception:  # nosec B110  # 設計上の許容
                                                pass
                                else:
                                    QgsMessageLog.logMessage(
                                        f"⚠️ Style '{style_name}' not found for '{lyr.name()}'",
                                        "geo_webview", Qgis.MessageLevel.Warning
                                    )
                            except Exception as e:
                                QgsMessageLog.logMessage(
                                    f"⚠️ Applying style '{style_name}' to '{lyr.name()}' failed: {e}",
                                    "geo_webview", Qgis.MessageLevel.Warning
                                )

                    if layer_style_overrides:
                        # Preprocess QML strings: replace is_layer_visible('name') calls
                        # with literal 1/0 according to the requested LAYERS param.
                        try:
                            # raw layer id/name strings requested by the client
                            requested_names = ids if 'ids' in locals() else []

                            def _replace_vis_calls(qml_text: str) -> str:
                                if not isinstance(qml_text, str):
                                    return qml_text

                                def repl(m):
                                    nm = m.group(1)
                                    try:
                                        return '1' if nm in requested_names else '0'
                                    except Exception:
                                        return '0'

                                return re.sub(r"is_layer_visible\(\s*['\"]([^'\"]+)['\"]\s*\)", repl, qml_text)

                            for lid, qml in list(layer_style_overrides.items()):
                                try:
                                    new_qml = _replace_vis_calls(qml)
                                    if new_qml != qml:
                                        layer_style_overrides[lid] = new_qml
                                        QgsMessageLog.logMessage(
                                            f"🔧 Rewrote is_layer_visible() in style for layer {lid}",
                                            "geo_webview", Qgis.MessageLevel.Info
                                        )
                                except Exception as e:
                                    QgsMessageLog.logMessage(
                                        f"⚠️ Failed preprocessing QML for layer {lid}: {e}",
                                        "geo_webview", Qgis.MessageLevel.Warning
                                    )
                        except Exception:  # nosec B110  # 設計上の許容
                            pass

                    if layer_style_overrides:
                        try:
                            # Log detail about overrides for debugging renderer behavior
                            try:
                                keys = list(layer_style_overrides.keys())
                                summary = ", ".join([str(k) for k in keys])
                            except Exception:
                                summary = str(type(layer_style_overrides))
                            QgsMessageLog.logMessage(
                                f"🔍 Applying layerStyleOverrides: keys={summary}, count={len(layer_style_overrides)}",
                                "geo_webview", Qgis.MessageLevel.Info
                            )
                            map_settings.setLayerStyleOverrides(layer_style_overrides)
                            # attempt to read back what map_settings holds (if supported)
                            try:
                                current = map_settings.layerStyleOverrides()
                                try:
                                    cur_keys = list(current.keys())
                                    cur_summary = ", ".join([str(k) for k in cur_keys])
                                except Exception:
                                    cur_summary = str(type(current))
                                QgsMessageLog.logMessage(
                                    f"🔍 map_settings.layerStyleOverrides() keys={cur_summary}, count={len(current)}",
                                    "geo_webview", Qgis.MessageLevel.Info
                                )
                            except Exception:
                                QgsMessageLog.logMessage(
                                    "🔍 map_settings.layerStyleOverrides() not readable or unsupported in this QGIS version",
                                    "geo_webview", Qgis.MessageLevel.Warning
                                )
                        except Exception as e:
                            QgsMessageLog.logMessage(
                                f"⚠️ Failed to set layerStyleOverrides: {e}",
                                "geo_webview", Qgis.MessageLevel.Warning
                            )

                    QgsMessageLog.logMessage(
                        f"🎯 Using explicit LAYERS param: {len(resolved_layers)} layers",
                        "geo_webview", Qgis.MessageLevel.Info
                    )
                    return map_settings
            except Exception:  # nosec B110  # 設計上の許容
                pass

        # テーマが指定されている場合(キャッシュを利用)
        if themes:
            # キャッシュをチェック
            if themes in self._theme_cache:
                virtual_layers, layer_style_overrides = self._theme_cache[themes]
                map_settings.setLayers(virtual_layers)
                if layer_style_overrides:
                    map_settings.setLayerStyleOverrides(layer_style_overrides)
                QgsMessageLog.logMessage(
                    f"💾 Cache hit for theme '{themes}': {len(virtual_layers)} layers",
                    "geo_webview", Qgis.MessageLevel.Info
                )
                return map_settings

            map_theme_collection = project.mapThemeCollection()

            if themes in map_theme_collection.mapThemes():
                QgsMessageLog.logMessage(
                    f"🎨 Creating virtual map view for theme: {themes}",
                    "geo_webview", Qgis.MessageLevel.Info
                )

                # テーマの状態を取得
                theme_record = map_theme_collection.mapThemeState(themes)

                # 仮想マップビューのレイヤーリストとスタイルを準備
                virtual_layers = []
                layer_style_overrides = {}

                # 各レイヤーを処理
                for layer_record in theme_record.layerRecords():
                    layer = layer_record.layer()

                    if not layer or not layer.isValid():
                        continue

                    # 可視性チェック
                    if not layer_record.isVisible:
                        QgsMessageLog.logMessage(
                            f"🚫 Skip hidden: '{layer.name()}'",
                            "geo_webview", Qgis.MessageLevel.Info
                        )
                        continue

                    # 可視レイヤーをリストに追加
                    virtual_layers.append(layer)

                    # スタイルの取得と適用
                    style_name = layer_record.currentStyle if not layer_record.usingCurrentStyle else None

                    if style_name:
                        # 特定のスタイルを適用
                        style_manager = layer.styleManager()
                        if style_name in style_manager.styles():
                            # 現在のスタイルを一時保存
                            original_style = style_manager.currentStyle()

                            try:
                                # 指定スタイルに切り替え
                                style_manager.setCurrentStyle(style_name)

                                # スタイルをQML文字列として取得
                                doc = QDomDocument()
                                error_msg = layer.exportNamedStyle(doc)

                                if not error_msg:
                                    qml_string = doc.toString()
                                    layer_style_overrides[layer.id()] = qml_string
                                    QgsMessageLog.logMessage(
                                        f"✅ '{layer.name()}' -> style '{style_name}'",
                                        "geo_webview", Qgis.MessageLevel.Info
                                    )
                                else:
                                    QgsMessageLog.logMessage(
                                        f"⚠️ Style export failed for '{layer.name()}': {error_msg}",
                                        "geo_webview", Qgis.MessageLevel.Warning
                                    )
                            finally:
                                # 元のスタイルに戻す（プロジェクトに影響を与えない）
                                style_manager.setCurrentStyle(original_style)
                        else:
                            QgsMessageLog.logMessage(
                                f"⚠️ Style '{style_name}' not found for '{layer.name()}'",
                                "geo_webview", Qgis.MessageLevel.Warning
                            )
                    else:
                        # 現在のスタイルをそのまま使用
                        doc = QDomDocument()
                        error_msg = layer.exportNamedStyle(doc)

                        if not error_msg:
                            qml_string = doc.toString()
                            layer_style_overrides[layer.id()] = qml_string
                            QgsMessageLog.logMessage(
                                f"✅ '{layer.name()}' -> current style",
                                "geo_webview", Qgis.MessageLevel.Info
                            )

                # 仮想マップビューに設定を適用
                map_settings.setLayers(virtual_layers)

                if layer_style_overrides:
                    map_settings.setLayerStyleOverrides(layer_style_overrides)
                    QgsMessageLog.logMessage(
                        f"🎨 Virtual view: {len(virtual_layers)} layers, {len(layer_style_overrides)} styles applied",
                        "geo_webview", Qgis.MessageLevel.Info
                    )
                else:
                    QgsMessageLog.logMessage(
                        f"🎨 Virtual view: {len(virtual_layers)} layers (no style overrides)",
                        "geo_webview", Qgis.MessageLevel.Info
                    )

                # キャッシュに保存
                self._theme_cache[themes] = (virtual_layers, layer_style_overrides)
            else:
                # テーマが見つからない場合
                canvas_layers = canvas.mapSettings().layers() if canvas else []
                QgsMessageLog.logMessage(
                    f"⚠️ Theme '{themes}' not found, using canvas layers: {len(canvas_layers)} layers",
                    "geo_webview", Qgis.MessageLevel.Warning
                )
                if canvas_layers:
                    map_settings.setLayers(canvas_layers)
                else:
                    # キャンバスにもレイヤーがない場合はプロジェクトから取得
                    project_layers = []
                    layer_tree_root = project.layerTreeRoot()
                    for layer_tree_layer in layer_tree_root.findLayers():
                        if layer_tree_layer.isVisible():
                            layer = layer_tree_layer.layer()
                            if layer and layer.isValid():
                                project_layers.append(layer)
                    map_settings.setLayers(project_layers)
                    QgsMessageLog.logMessage(
                        f"📋 Fallback to {len(project_layers)} visible project layers",
                        "geo_webview", Qgis.MessageLevel.Info
                    )
        else:
            # テーマ指定なし：現在のキャンバスレイヤーを使用
            canvas_layers = canvas.mapSettings().layers() if canvas else []
            QgsMessageLog.logMessage(
                f"🎨 No theme specified, using canvas layers: {len(canvas_layers)} layers found",
                "geo_webview", Qgis.MessageLevel.Info
            )
            if canvas_layers:
                map_settings.setLayers(canvas_layers)
                # デバッグ: レイヤー名を表示
                layer_names = [layer.name() for layer in canvas_layers if layer]
                QgsMessageLog.logMessage(
                    f"📋 Canvas layers: {', '.join(layer_names)}",
                    "geo_webview", Qgis.MessageLevel.Info
                )
                # 追加診断: 各レイヤーのラベリング状態と QML に <labeling> が含まれるかをチェック
                try:
                    from qgis.PyQt.QtXml import QDomDocument
                    layer_style_overrides = {}
                    for layer in canvas_layers:
                        try:
                            lname = layer.name() if layer else '<none>'
                            lid = layer.id() if layer else '<none>'
                            labels_on = False
                            labeling_type = None
                            try:
                                labels_on = bool(layer.labelsEnabled())
                                labeling_obj = layer.labeling()
                                labeling_type = type(labeling_obj).__name__ if labeling_obj is not None else 'None'
                            except Exception:
                                labeling_type = 'error'

                            # Try exporting current style to see if QML contains <labeling>
                            qml_has_labeling = False
                            try:
                                doc = QDomDocument()
                                err = layer.exportNamedStyle(doc)
                                if not err:
                                    qml = doc.toString()
                                    if '<labeling' in qml or '<Labeling' in qml:
                                        qml_has_labeling = True
                                    # If canvas has no labels enabled but exported QML contains labeling,
                                    # prepare a layerStyleOverride so the renderer will draw labels
                                    if qml_has_labeling and not labels_on:
                                        try:
                                            # Preprocess QML for canvas layers: replace is_layer_visible('name')
                                            # with 1/0 according to canvas layer names so expressions evaluate server-side.
                                            try:
                                                requested_names = [ly.name() for ly in canvas_layers if ly]

                                                def _replace_vis_calls_canvas(qml_text: str) -> str:
                                                    if not isinstance(qml_text, str):
                                                        return qml_text

                                                    def repl(m):
                                                        nm = m.group(1)
                                                        try:
                                                            return '1' if nm in requested_names else '0'
                                                        except Exception:
                                                            return '0'

                                                    return re.sub(r"is_layer_visible\(\s*['\"]([^'\"]+)['\"]\s*\)", repl, qml_text)

                                                new_qml = _replace_vis_calls_canvas(qml)
                                                if new_qml != qml:
                                                    layer_style_overrides[layer.id()] = new_qml
                                                    QgsMessageLog.logMessage(
                                                        f"🔧 Rewrote is_layer_visible() in canvas style for layer {layer.id()}",
                                                        "geo_webview", Qgis.MessageLevel.Info
                                                    )
                                                else:
                                                    layer_style_overrides[layer.id()] = qml
                                            except Exception:
                                                layer_style_overrides[layer.id()] = qml
                                        except Exception:  # nosec B110  # 設計上の許容
                                            pass
                            except Exception:  # nosec B110  # 設計上の許容
                                pass

                            QgsMessageLog.logMessage(
                                f"🔎 Layer '{lname}' (id={lid}) labelsEnabled={labels_on} labeling_type={labeling_type} qml_has_labeling={qml_has_labeling}",
                                "geo_webview", Qgis.MessageLevel.Info
                            )
                        except Exception as e:
                            QgsMessageLog.logMessage(f"⚠️ Failed diagnosing layer labeling: {e}", "geo_webview", Qgis.MessageLevel.Warning)
                    # If we collected style overrides for canvas layers, apply them to map_settings
                    if layer_style_overrides:
                        try:
                            try:
                                keys = list(layer_style_overrides.keys())
                                summary = ", ".join([str(k) for k in keys])
                            except Exception:
                                summary = str(type(layer_style_overrides))
                            QgsMessageLog.logMessage(
                                f"🔍 Applying canvas layerStyleOverrides: keys={summary}, count={len(layer_style_overrides)}",
                                "geo_webview", Qgis.MessageLevel.Info
                            )
                            map_settings.setLayerStyleOverrides(layer_style_overrides)
                            try:
                                current = map_settings.layerStyleOverrides()
                                try:
                                    cur_keys = list(current.keys())
                                    cur_summary = ", ".join([str(k) for k in cur_keys])
                                except Exception:
                                    cur_summary = str(type(current))
                                QgsMessageLog.logMessage(
                                    f"🔍 map_settings.layerStyleOverrides() keys={cur_summary}, count={len(current)}",
                                    "geo_webview", Qgis.MessageLevel.Info
                                )
                            except Exception:
                                QgsMessageLog.logMessage(
                                    "🔍 map_settings.layerStyleOverrides() not readable or unsupported in this QGIS version",
                                    "geo_webview", Qgis.MessageLevel.Warning
                                )
                        except Exception as e:
                            QgsMessageLog.logMessage(f"⚠️ Failed to set canvas layerStyleOverrides: {e}", "geo_webview", Qgis.MessageLevel.Warning)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            else:
                QgsMessageLog.logMessage(
                    "⚠️ No layers found in canvas, using project layers",
                    "geo_webview", Qgis.MessageLevel.Warning
                )
                # フォールバック: プロジェクトの可視レイヤーを使用
                project_layers = []
                layer_tree_root = project.layerTreeRoot()
                for layer_tree_layer in layer_tree_root.findLayers():
                    if layer_tree_layer.isVisible():
                        layer = layer_tree_layer.layer()
                        if layer and layer.isValid():
                            project_layers.append(layer)
                map_settings.setLayers(project_layers)
                QgsMessageLog.logMessage(
                    f"📋 Using {len(project_layers)} visible project layers",
                    "geo_webview", Qgis.MessageLevel.Info
                )

        return map_settings

    def _get_visible_layers(self, themes=None):
        """現在のプロジェクトから可視レイヤを取得（テーマ対応）"""
        from qgis.core import QgsProject
        visible_layers = []

        project = QgsProject.instance()
        map_theme_collection = project.mapThemeCollection()

        if themes and themes in map_theme_collection.mapThemes():
            # 指定されたテーマのレイヤを使用
            from qgis.core import QgsMessageLog, Qgis

            theme_record = map_theme_collection.mapThemeState(themes)
            for layer_id in theme_record.layerRecords():
                layer = project.mapLayer(layer_id)
                if layer and layer.isValid():
                    visible_layers.append(layer)
        else:
            # テーマが指定されていない場合は現在のQGIS表示状態を使用
            from qgis.core import QgsMessageLog, Qgis
            if themes:
                QgsMessageLog.logMessage(f"⚠️ Theme '{themes}' not found, using current QGIS display settings", "geo_webview", Qgis.MessageLevel.Warning)

            # プロジェクトのレイヤツリーを走査して可視レイヤを取得
            layer_tree_root = project.layerTreeRoot()
            for layer_tree_layer in layer_tree_root.findLayers():
                if layer_tree_layer.isVisible():
                    layer = layer_tree_layer.layer()
                    if layer and layer.isValid():
                        visible_layers.append(layer)

        return visible_layers

    def _parse_bbox_to_extent(self, bbox, crs):
        """BBOX文字列をQgsRectangleに変換"""
        from qgis.core import QgsRectangle
        try:
            coords = [float(x) for x in bbox.split(',')]
            if len(coords) == 4:
                minx, miny, maxx, maxy = coords
                return QgsRectangle(minx, miny, maxx, maxy)
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"⚠️ Failed to parse BBOX '{bbox}': {e}", "geo_webview", Qgis.MessageLevel.Warning)
        return None

    def _execute_parallel_rendering(self, map_settings):
        """並列レンダリングを実行"""
        from qgis.core import QgsMapRendererParallelJob, QgsMessageLog, Qgis
        import time

        try:
            start_time = time.time()

            # レンダリング前のレイヤー情報をログ
            layers = map_settings.layers()
            QgsMessageLog.logMessage(
                f"🎬 Starting render: {len(layers)} layers, size: {map_settings.outputSize().width()}x{map_settings.outputSize().height()}",
                "geo_webview", Qgis.MessageLevel.Info
            )

            # 並列レンダリングジョブを作成
            render_job = QgsMapRendererParallelJob(map_settings)

            # イベントループで完了を待つ
            loop = QEventLoop()
            render_job.finished.connect(loop.quit)

            render_start = time.time()
            render_job.start()

            # タイムアウト設定(30秒 - OpenLayersは大きめの画像を要求する可能性)
            timer = QTimer()
            timer.timeout.connect(loop.quit)
            timer.setSingleShot(True)
            try:
                timer.start(int(self.render_timeout_s * 1000))
            except Exception:
                # fallback to 30s if misconfigured
                timer.start(30000)

            loop.exec()

            render_elapsed = time.time() - render_start

            if render_job.isActive():
                # タイムアウトした場合
                render_job.cancel()
                QgsMessageLog.logMessage("⚠️ Rendering timeout (30s)", "geo_webview", Qgis.MessageLevel.Warning)
                return None

            # レンダリング結果を取得
            image = render_job.renderedImage()

            total_elapsed = time.time() - start_time

            if image and not image.isNull():
                QgsMessageLog.logMessage(
                    f"✅ Render completed: {render_elapsed:.2f}s (total: {total_elapsed:.2f}s)",
                    "geo_webview", Qgis.MessageLevel.Info
                )
                return image
            else:
                QgsMessageLog.logMessage("⚠️ Rendered image is null", "geo_webview", Qgis.MessageLevel.Warning)
                return None

        except Exception as e:
            import traceback
            QgsMessageLog.logMessage(f"❌ Parallel rendering error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            QgsMessageLog.logMessage(f"❌ Traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
            return None
            QgsMessageLog.logMessage(f"❌ Parallel rendering error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            QgsMessageLog.logMessage(f"❌ Traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
            return None

    def _save_image_as_png(self, image):
        """QImageをPNGバイトデータに変換"""
        try:
            from qgis.PyQt.QtCore import QBuffer, QIODevice
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            png_data = buffer.data()
            # Ensure we return Python bytes (QByteArray -> bytes)
            try:
                png_bytes = bytes(png_data)
            except Exception:
                png_bytes = png_data
            buffer.close()
            return png_bytes
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"⚠️ Failed to save image as PNG: {e}", "geo_webview", Qgis.MessageLevel.Warning)
            return None
