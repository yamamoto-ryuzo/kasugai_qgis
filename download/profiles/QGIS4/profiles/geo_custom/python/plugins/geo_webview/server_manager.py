# -*- coding: utf-8 -*-
import socket
import threading
import time
import urllib.parse
import json
import html
import os
import re
import concurrent.futures
from collections import deque
from datetime import datetime
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsMessageLog, Qgis
from .i18n_json import catalog, lang_code
# lazy import http_server inside methods to avoid circular import during QGIS plugin init

# 生成HTMLページのラベル(i18n/<lang>.json の "geo_webview.page" context
# に翻訳を登録。未登録は英語にフォールバック)
_PAGE_CONTEXT = 'geo_webview.page'
_PAGE_EN = {
    'title': 'QMap Permalink - Map View',
    'subtitle': 'Integrated map view by the QGIS plugin - using WMS endpoint',
    'map_info': '📍 Map Information',
    'center_x': 'Center (X)',
    'center_y': 'Center (Y)',
    'scale': 'Scale',
    'crs': 'CRS',
    'rotation': 'Rotation',
    'image_size': 'Image Size',
    'controls': '🔧 Controls',
    'wms_image': '📷 Show WMS Image',
    'refresh': '🔄 Refresh Map',
    'copy_link': '🔗 Copy Permalink',
    'tip_rotate': 'Rotate with north up',
    'tip_reset': 'Reset north',
    'copied': 'Permalink copied to clipboard!',
    'err_title': 'QMap Permalink - Error',
    'err_failed': 'Failed to generate the permalink page',
    'back': '🔙 Back',
    'home': '🏠 Home',
}


def _page_strings():
    """生成HTMLページのラベル辞書を返す。"""
    lang = lang_code()
    page = catalog(os.path.dirname(os.path.abspath(__file__)),
                   lang).get(_PAGE_CONTEXT, {})
    strings = {key: page.get(en) or en for key, en in _PAGE_EN.items()}
    strings['lang'] = lang if page else 'en'
    return strings


class GeoWebViewServerManager:
    """geo_webview用HTTPサーバー管理クラス - WMS専用シンプル版

    WMSサーバーの起動・停止・リクエスト処理を担当します。
    不要なエンドポイント（画像、マップ、タイル）は全て削除されています。
    """

    @staticmethod
    def _calculate_optimal_workers():
        """PCのCPUコア数に基づいて最適なワーカー数を計算

        Returns:
            int: 最適なワーカー数 (最小4、最大32)

        計算式:
        - CPUコア数+4を基本とする（I/O待ちを考慮）
        - 最小4: 低スペックPCでも基本的な並列処理を確保
        - 最大32: メモリ使用量とコンテキストスイッチのオーバーヘッドを抑制

        例:
        - 4コアPC: min(32, 4+4) = 8ワーカー
        - 8コアPC: min(32, 8+4) = 12ワーカー
        - 16コアPC: min(32, 16+4) = 20ワーカー
        - 32コアPC: min(32, 32+4) = 32ワーカー（上限）
        """
        try:
            cpu_count = os.cpu_count()
            if cpu_count is None:
                # cpu_count()がNoneを返す場合のフォールバック
                return 6  # デフォルト値（ブラウザの典型的な並列リクエスト数）

            # CPUコア数+4（I/O待ちを考慮）、最小4、最大32
            workers = min(32, max(4, cpu_count + 4))

            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(
                f"💻 Detected: CPU cores={cpu_count}, HTTP parallel workers={workers}",
                "geo_webview", Qgis.MessageLevel.Info
            )

            return workers
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(
                f"⚠️ Worker count auto-calculation failed, using default 6: {e}",
                "geo_webview", Qgis.MessageLevel.Warning
            )
            return 6

    def __init__(self, iface, navigation_signals, webmap_generator, main_plugin):
        """サーバーマネージャーを初期化

        Args:
            iface: QGISインターフェース
            navigation_signals: ナビゲーション用シグナル
            webmap_generator: WebMapGeneratorインスタンス
            main_plugin: メインプラグインクラスのインスタンス（共通メソッド呼び出し用）
        """
        self.iface = iface
        self.navigation_signals = navigation_signals
        self.main_plugin = main_plugin
        self.webmap_generator = webmap_generator

        # WMSサービスを初期化
        from .wms_service import GeoWebViewWMSService
        self.wms_service = GeoWebViewWMSService(iface, webmap_generator, 8089, False)
        # WMTSサービスを初期化（サーバマネージャ自身を渡すことで依存を小さくする）
        try:
            from .wmts_service import GeoWebViewWMTSService
            self.wmts_service = GeoWebViewWMTSService(self)
        except Exception:
            # 初期化が失敗してもサーバは動作を続けられるように None を許容
            # ただし失敗理由はログに出しておく (QGIS のメッセージログが使える場合)
            try:
                import traceback
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(
                    f"WMTS service initialization failed: {traceback.format_exc()}",
                    "geo_webview",
                    Qgis.MessageLevel.Warning
                )
            except Exception:
                # 最低限コンソールには表示
                try:
                    import sys
                    import traceback
                    sys.stderr.write('WMTS init failed:\n')
                    traceback.print_exc()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            self.wmts_service = None
        # Track last known WMTS identity to avoid unnecessary work
        self._last_wmts_identity_short = None
        self._last_wmts_identity_raw = None
        self._layer_change_timer = None

        # Attach layer-tree signals (best-effort) so that when visible layers change
        # we can ensure a new WMTS identity folder/meta is created. This is defensive
        # and will try multiple common signal names used in different QGIS versions.
        try:
            self._attach_layer_tree_hooks()
        except Exception:  # nosec B110  # 設計上の許容
            pass

        # WFSサービスを初期化
        try:
            from .wfs_service import GeoWebViewWFSService
            self.wfs_service = GeoWebViewWFSService(iface, 8089)
        except Exception:
            # 初期化が失敗してもサーバは動作を続けられるように None を許容
            self.wfs_service = None

        # HTTPサーバー関連の状態
        self.http_server = None
        self.server_thread = None
        self.server_port = 8089  # デフォルトポート
        self.preferred_port = 8089  # ユーザー指定の優先ポート
        self._http_running = False
        self._last_request_text = ""

        # HTTP並列処理用スレッドプール（PCのCPU性能に応じて自動調整）
        optimal_workers = self._calculate_optimal_workers()
        self._http_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=optimal_workers,
            thread_name_prefix='HTTP-Handler'
        )

        # プラグインバージョン情報
        self.plugin_version = self._get_plugin_version()
        # 任意のCRSを強制的にEPSG:3857として扱うオプション（デフォルト: False）
        self.force_epsg3857 = False

        # クライアントから受領したパーマリンク履歴(最新10件)
        # 要素: {'url','client','ua','time'}
        self.received_history = deque(maxlen=10)
        # MACアドレス解決キャッシュ {ip: (set_of_macs, epoch)}
        self._mac_cache = {}
        # 独立レンダラ(QgsMapRendererParallelJob)の同時実行はQGISクラッシュを
        # 引き起こすため直列化する(WMSサービスと共有して全経路を一本化)
        self._render_lock = getattr(self.wms_service, '_render_lock', None) or threading.Lock()
        # KASUGAIエクスポートは同一出力先へ書き込むため同時実行を直列化する
        self._kasugai_lock = threading.Lock()

    def _safe_int(self, value, default):
        """文字列から安全にintに変換する。NaNや不正値は default を返す。"""
        try:
            # floatを経由して 'NaN' をはじく
            v = float(value)
            if v != v:  # NaN check
                return int(default)
            return int(v)
        except Exception:
            return int(default)

    def _get_plugin_version(self):
        """metadata.txtからプラグインバージョンを取得"""
        try:
            plugin_dir = os.path.dirname(__file__)
            metadata_path = os.path.join(plugin_dir, 'metadata.txt')

            if os.path.exists(metadata_path):
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                    # 各行をチェック（スペースを無視）
                    for line in lines:
                        # スペースを削除して "version=" で始まるかチェック
                        clean_line = line.replace(' ', '').replace('\t', '').lower()
                        if clean_line.startswith('version='):
                            # 元の行から値を抽出
                            if '=' in line:
                                version = line.split('=')[1].strip()
                                return version

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"❌ Version detection error: {e}", "geo_webview", Qgis.MessageLevel.Warning)

        # デフォルトバージョン（metadata.txtから読み取れない場合）
        return "UNKNOWN"

    def start_http_server(self, preferred_port=None):
        """HTTPサーバーを起動

        Args:
            preferred_port: 優先的に使用したいポート番号（指定がない場合は8089から検索）
        """
        try:
            if self._http_running:
                return

            # 優先ポートが指定されていればそれを使用
            if preferred_port is not None:
                self.preferred_port = preferred_port

            # 使用可能なポートを探す
            # 標準ポート(80, 443)の場合はそのまま使用、それ以外は指定ポートから+10の範囲で検索
            if self.preferred_port in (80, 443):
                # 標準ポートの場合はそのポートのみを試行
                start_port = self.preferred_port
                end_port = self.preferred_port
            else:
                # その他のポートの場合は±10の範囲で検索（下限は80）
                start_port = max(80, self.preferred_port)
                end_port = min(65535, self.preferred_port + 10)

            self.server_port = self.find_available_port(start_port, end_port)

            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._set_reuse_socketopt(server_socket)
            # bind to all interfaces so non-localhost access is possible
            server_socket.bind(('0.0.0.0', self.server_port))  # nosec B104  # LAN共有は本機能の仕様
            server_socket.listen(5)
            server_socket.settimeout(1.0)

            self.http_server = server_socket
            self._http_running = True

            self.server_thread = threading.Thread(
                target=self.run_server,
                name="QMapPermalinkHTTP",
                daemon=True,
            )
            self.server_thread.start()

            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"🚀 QMap Permalink v{self.plugin_version} WMS HTTP server started: http://localhost:{self.server_port}/wms", "geo_webview", Qgis.MessageLevel.Info)
            self.iface.messageBar().pushMessage(
                "QMap Permalink",
                QCoreApplication.translate("geo_webview", "WMS HTTP server started (port: {0})").format(self.server_port),
                duration=3
            )

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"Failed to start HTTP server: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            self.iface.messageBar().pushMessage(
                QCoreApplication.translate("geo_webview", "QMap Permalink Error"),
                QCoreApplication.translate("geo_webview", "Failed to start HTTP server: {0}").format(e),
                duration=5
            )
            self._http_running = False
            if self.http_server:
                try:
                    self.http_server.close()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                self.http_server = None

    def run_server(self):
        """サーバーを安全に実行（並列処理版）"""
        try:
            while self._http_running and self.http_server:
                try:
                    conn, addr = self.http_server.accept()
                except socket.timeout:  # nosec B112  # 設計上の許容
                    continue
                except OSError:
                    break

                # リクエストをスレッドプールで並列処理（ブラウザの6タイル同時取得に対応）
                try:
                    # スレッドプールが有効かチェック
                    if hasattr(self, '_http_executor') and self._http_executor and not getattr(self._http_executor, '_shutdown', False):
                        self._http_executor.submit(self._handle_client_connection_safe, conn, addr)
                    else:
                        # スレッドプールが使えない場合は接続を閉じる
                        try:
                            conn.close()
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                except Exception as e:
                    from qgis.core import QgsMessageLog, Qgis
                    QgsMessageLog.logMessage(f"Failed to dispatch HTTP request to thread pool: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                    try:
                        conn.close()
                    except Exception:  # nosec B110  # 設計上の許容
                        pass

        finally:
            self._http_running = False
            if self.http_server:
                try:
                    self.http_server.close()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                self.http_server = None
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage("HTTP server stopped", "geo_webview", Qgis.MessageLevel.Info)

    def stop_http_server(self):
        """HTTPサーバーを停止"""
        try:
            self._http_running = False

            # ソケットを先に閉じてacceptループを終了
            if self.http_server:
                try:
                    self.http_server.close()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                self.http_server = None

            # スレッドの終了を待つ
            if self.server_thread and self.server_thread.is_alive():
                try:
                    self.server_thread.join(timeout=3.0)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                self.server_thread = None

            # スレッドプールをシャットダウン（最後に実行）
            if hasattr(self, '_http_executor') and self._http_executor:
                try:
                    self._http_executor.shutdown(wait=True, cancel_futures=True)
                except TypeError:
                    # Python 3.8以前はcancel_futures引数がない
                    self._http_executor.shutdown(wait=True)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                # 新しいエグゼキュータを作成（次回起動用）
                optimal_workers = self._calculate_optimal_workers()
                self._http_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=optimal_workers,
                    thread_name_prefix='HTTP-Handler'
                )

            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage("QMap Permalink HTTP server stopped", "geo_webview", Qgis.MessageLevel.Info)

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"An error occurred while stopping the HTTP server: {e}", "geo_webview", Qgis.MessageLevel.Critical)

    def _handle_client_connection_safe(self, conn, addr):
        """HTTPリクエストを安全に処理（エラーハンドリング付き）"""
        try:
            self._handle_client_connection(conn, addr)
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"Error while handling HTTP request: {e}", "geo_webview", Qgis.MessageLevel.Warning)
        finally:
            try:
                conn.close()
            except Exception:  # nosec B110  # 設計上の許容
                pass

    def _handle_client_connection(self, conn, addr):
        """HTTPリクエストを解析してWMSリクエストを処理"""
        # 初期タイムアウト設定（リクエスト読み取り用）
        conn.settimeout(10.0)

        with conn:
            from . import http_server
            request_bytes = http_server.read_http_request(conn)
            if not request_bytes:
                return

            request_text = request_bytes.decode('iso-8859-1', errors='replace')
            self._last_request_text = request_text

            from qgis.core import QgsMessageLog, Qgis
            try:
                request_line = request_text.splitlines()[0]
            except IndexError:
                from . import http_server
                http_server.send_http_response(conn, 400, "Bad Request", "Invalid HTTP request line.")
                return

            parts = request_line.split()
            if len(parts) < 3:
                from . import http_server
                http_server.send_http_response(conn, 400, "Bad Request", "Malformed HTTP request line.")
                return

            method, target, _ = parts

            if method.upper() != 'GET':
                from . import http_server
                http_server.send_http_response(conn, 405, "Method Not Allowed", "Only GET is supported.")
                return

            # MACアドレス認証モード(設定で有効時のみ): 未登録MACのクライアントは403
            if not self._mac_auth_check(addr[0] if addr else ''):
                from . import http_server
                http_server.send_http_response(
                    conn, 403, "Forbidden",
                    "Access denied: client MAC address is not registered.",
                    "text/plain; charset=utf-8")
                return

            parsed_url = urllib.parse.urlparse(target)
            params = urllib.parse.parse_qs(parsed_url.query)
            # OGCパラメータ名は大小区別なし(Cesium等は小写で送る)ため、
            # 大写エイリアスを補完する。既存キーは上書きしない
            for key in list(params):
                key_up = key.upper()
                if key_up != key and key_up not in params:
                    params[key_up] = params[key]
            # Manually unquote parameter values to handle UTF-8 encoding issues
            for key in params:
                params[key] = [urllib.parse.unquote_plus(val) for val in params[key]]
            # Extract Host header for use in generated URLs (used for OnlineResource)
            host = None
            for line in request_text.splitlines():
                if line.lower().startswith('host:'):
                    host = line.split(':', 1)[1].strip()
                    break

            # ブラウザで読み込まれるページURL（/qgis-map）を受け取ったときだけ
            # パネルのナビゲート欄に表示するためにemitする。
            # ただしパネル側から生成した自前のページ遷移(internal=1付与)は
            # ナビゲート欄の上書き・受領履歴の対象外とする。
            try:
                is_internal = 'internal' in params
                if parsed_url.path in ('/qgis-map', '/maplibre'):
                    server_port = None
                    try:
                        server_port = self.http_server.getsockname()[1] if self.http_server else self.server_port
                    except Exception:
                        server_port = self.server_port

                    if not host:
                        host = f'localhost:{server_port}'

                    # target が absolute URI の場合はそのまま使う
                    if target.startswith('http://') or target.startswith('https://'):
                        full_url = target
                    else:
                        full_url = f'http://{host}{target}'

                    if not is_internal:
                        # 受領履歴に記録(クライアントIP・User-Agent・時刻つき、最大10件)
                        try:
                            ua = ''
                            for hline in request_text.splitlines():
                                if hline.lower().startswith('user-agent:'):
                                    ua = hline.split(':', 1)[1].strip()
                                    break
                            self.received_history.appendleft({
                                'url': full_url,
                                'client': addr[0] if addr else '',
                                'ua': ua,
                                'time': datetime.now().isoformat(timespec='seconds'),
                            })
                        except Exception:  # nosec B110  # 設計上の許容
                            pass

                        # Emit the full URL for UI if signal available
                        if hasattr(self, 'navigation_signals') and self.navigation_signals:
                            try:
                                if hasattr(self.navigation_signals, 'request_origin_changed'):
                                    self.navigation_signals.request_origin_changed.emit(full_url)
                            except Exception:  # nosec B110  # 設計上の許容
                                pass

                        # main_plugin にも保持（パネル未作成時のフォールバック）
                        try:
                            if hasattr(self, 'main_plugin'):
                                setattr(self.main_plugin, '_last_request_origin', full_url)
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
            except Exception:  # nosec B110  # 設計上の許容
                pass

            # WMSエンドポイントの処理（直接PNG画像返却）
            if parsed_url.path == '/wms':
                try:
                    self.wms_service.handle_wms_request(conn, params, host)
                except Exception as e:
                    QgsMessageLog.logMessage(f"❌ WMS handler error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                    import traceback
                    QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(conn, 500, "Internal Server Error", f"WMS processing failed: {str(e)}")
                return

            # OpenLayersパーマリンクエンドポイントの処理（HTMLページ生成、内部で/wmsを参照）
            if parsed_url.path == '/qgis-map':
                try:
                    self._handle_permalink_html_page(conn, params)
                except Exception as e:
                    QgsMessageLog.logMessage(f"❌ OpenLayers HTML page error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                    import traceback
                    QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(conn, 500, "Internal Server Error", f"OpenLayers HTML page generation failed: {str(e)}")
                return

            # Dynamic MapLibre style endpoint: return a Mapbox style JSON for a given WFS typename
            if parsed_url.path in ('/maplibre-style', '/maplibre/style'):
                try:
                    # Determine typename (support several param names)
                    wfs_typename = None
                    for k in ('typename', 'typenames', 'TYPENAME', 'TYPENAMES', 'layer', 'layers', 'type', 'typeName'):
                        if k in params and params.get(k):
                            wfs_typename = params.get(k)[0]
                            break

                    # If no typename specified, return a base WMTS-only style (no WFS layers)
                    if not wfs_typename:
                        # Use the same IDs as the full style path to keep UI toggles consistent
                        # 動的ホスト名を使用（外部アクセス対応）
                        base_url = f"http://{host}" if host else f"http://localhost:{self.server_port}"
                        wmts_tile_url = f"{base_url}/wmts/{{z}}/{{x}}/{{y}}.png"
                        wmts_base_style = {
                            "version": 8,
                            "sources": {
                                "qmap": {
                                    "type": "raster",
                                    "tiles": [wmts_tile_url],
                                    "tileSize": 256
                                }
                            },
                            "layers": [
                                {
                                    "id": "qmap",
                                    "type": "raster",
                                    "source": "qmap",
                                    "minzoom": 0,
                                    "maxzoom": 22,
                                    "layout": {"visibility": "visible"}
                                }
                            ]
                        }
                        payload = json.dumps(wmts_base_style, ensure_ascii=False)
                        from . import http_server
                        http_server.send_http_response(conn, 200, 'OK', payload, 'application/json; charset=utf-8')
                        return

                    # Ensure WFS service exists
                    if not hasattr(self, 'wfs_service') or self.wfs_service is None:
                        from . import http_server
                        http_server.send_http_response(conn, 501, 'Not Implemented', 'WFS service not available', 'text/plain; charset=utf-8')
                        return

                    # Find layer and try several matching strategies
                    layer = None
                    try:
                        layer = self.wfs_service._find_layer_by_name(wfs_typename)
                    except Exception:
                        layer = None

                    if layer is None:
                        # Strict policy: typename must be the exact QGIS layer.id()
                        try:
                            cands = self.wfs_service._get_vector_layers()
                        except Exception:
                            cands = []
                        cand_ids = []
                        for c in cands:
                            try:
                                cand_ids.append(c.id())
                            except Exception:  # nosec B112  # 設計上の許容
                                continue
                        body = {
                            'error': f"Layer '{wfs_typename}' not found",
                            'available_typenames': cand_ids
                        }
                        payload = json.dumps(body, ensure_ascii=False, indent=2)
                        from . import http_server
                        http_server.send_http_response(conn, 404, 'Not Found', payload, 'application/json; charset=utf-8')
                        return

                    # Convert QGIS layer style directly to Mapbox layers using QGIS API
                    try:
                        from .maplibre.qmap_maplibre_wfs import qgis_layer_to_maplibre_style
                        # create safe source id based on the QGIS layer id (canonical)
                        try:
                            raw_id = layer.id()
                        except Exception:
                            raw_id = str(wfs_typename)
                        # Use the QGIS layer's raw id as the canonical typename and
                        # as the MapLibre source id. Do NOT prefix with 'wfs_'.
                        # We intentionally keep the raw layer.id() (including
                        # hyphens or leading underscores) to preserve one-to-one
                        # correspondence with QGIS objects.
                        _wfs_source_id = str(raw_id)
                        mapbox_layers = qgis_layer_to_maplibre_style(raw_id, _wfs_source_id)
                        try:
                            from qgis.core import QgsMessageLog, Qgis
                            QgsMessageLog.logMessage(f'🎨 Converted to {len(mapbox_layers)} Mapbox layers: {[ml.get("id") for ml in mapbox_layers if isinstance(ml, dict)]}', 'QMapPermalink', Qgis.MessageLevel.Info)
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                    except Exception as e:
                        from . import http_server
                        http_server.send_http_response(conn, 500, 'Internal Server Error', f'Failed to convert layer style: {e}', 'text/plain; charset=utf-8')
                        return

                    # Build MapLibre style JSON with WMTS base and WFS vector layers
                    # Build style dict
                    # Use complete URL for tile template (MapLibre requires absolute URLs)
                    # 動的ホスト名を使用（外部アクセス対応）
                    base_url = f"http://{host}" if host else f"http://localhost:{self.server_port}"
                    tile_template = f'{base_url}/wmts/{{z}}/{{x}}/{{y}}.png'

                    # Ensure all mapbox_layers have explicit visibility set to 'visible'
                    # so that client-side controls can toggle them properly
                    try:
                        for ml in mapbox_layers:
                            if isinstance(ml, dict):
                                if 'layout' not in ml:
                                    ml['layout'] = {}
                                if 'visibility' not in ml.get('layout', {}):
                                    ml['layout']['visibility'] = 'visible'
                    except Exception:  # nosec B110  # 設計上の許容
                        pass

                    style_dict = {
                        'version': 8,
                        # use canonical QGIS layer id for the style name (must match typename)
                        'name': str(raw_id) if layer is not None else str(wfs_typename),
                        'glyphs': 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
                        'sources': {
                            'qmap': {
                                'type': 'raster',
                                'tiles': [tile_template],
                                'tileSize': 256,
                                'attribution': 'QMapPermalink WMTS'
                            },
                            _wfs_source_id: {
                                'type': 'geojson',
                                'data': f"{base_url}/wfs?SERVICE=WFS&REQUEST=GetFeature&TYPENAMES={urllib.parse.quote(str(raw_id))}&OUTPUTFORMAT=application/json&MAXFEATURES=1000"
                            }
                        },
                        'layers': [
                            {'id': 'qmap', 'type': 'raster', 'source': 'qmap', 'minzoom': 0, 'layout': {'visibility': 'visible'}}
                        ] + mapbox_layers
                    }
                    payload = json.dumps(style_dict, ensure_ascii=False, indent=2)
                    from . import http_server
                    http_server.send_http_response(conn, 200, 'OK', payload, 'application/json; charset=utf-8')
                    return
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(conn, 500, 'Internal Server Error', f'Error in maplibre-style handler: {e}', 'text/plain; charset=utf-8')
                    return

            # MapLibre パーマリンクエンドポイントの処理（HTMLページ生成）
            if parsed_url.path == '/maplibre':
                try:
                    # Accept multiple parameter formats:
                    # 1. lat/lon/zoom (WGS84 coordinates)
                    # 2. x/y/scale/crs/rotation (arbitrary CRS with rotation support)
                    # 3. permalink (full URL string)
                    lat = params.get('lat', [None])[0]
                    lon = params.get('lon', [None])[0]
                    zoom = params.get('zoom', [None])[0]
                    x = params.get('x', [None])[0]
                    y = params.get('y', [None])[0]
                    scale = params.get('scale', [None])[0]
                    crs = params.get('crs', [None])[0]
                    rotation = params.get('rotation', [None])[0]
                    permalink = params.get('permalink', [None])[0]

                    html_content = None

                    # Prefer QGIS-aware generator when running inside QGIS
                    try:
                        # Attempt to use the plugin's maplibre_generator which uses
                        # QGIS transformation APIs to handle arbitrary CRSs.
                        from . import maplibre_generator
                        import webbrowser
                        import os

                        # /maplibre-style is handled at top-level routing to avoid nested path checks
                        # Prevent maplibre_generator.open_maplibre_from_permalink from
                        # actually opening the browser: monkey-patch webbrowser.open.
                        _orig_web_open = webbrowser.open
                        try:
                            webbrowser.open = lambda *a, **k: None
                            # call generator which writes a temp HTML file and
                            # returns its path
                            temp_path = None
                            # Determine optional WFS typename from outer params (prefer explicit param)
                            wfs_typename = None
                            try:
                                for k in ('typename', 'typenames', 'TYPENAME', 'TYPENAMES', 'layer', 'layers', 'type', 'typeName'):
                                    if k in params and params.get(k):
                                        wfs_typename = params.get(k)[0]
                                        break
                            except Exception:
                                wfs_typename = None

                            # If typename not provided by request, try to auto-select
                            # from the project's /wfs-layers list (prefer layers with
                            # a finite bbox). This uses the same project-configured
                            # WFSLayers as the /wfs-layers endpoint.
                            if not wfs_typename:
                                try:
                                    layers_list = self._collect_wfs_layers()
                                    if layers_list:
                                        import math
                                        chosen = None
                                        for L in layers_list:
                                            bbox = L.get('bbox', {}) or {}
                                            try:
                                                minx = float(bbox.get('minx'))
                                                if math.isfinite(minx):
                                                    chosen = L
                                                    break
                                            except Exception:  # nosec B112  # 設計上の許容
                                                continue
                                        if not chosen:
                                            chosen = layers_list[0]
                                        # Use the canonical typename (QGIS layer.id()) when
                                        # auto-selecting a layer. The /wfs-layers entries
                                        # expose both 'name' (UI-normalized) and 'typename'
                                        # (canonical). Prefer 'typename' to avoid generating
                                        # permalinks that reference human-friendly names.
                                        wfs_typename = chosen.get('typename') or chosen.get('id') or chosen.get('name')
                                        try:
                                            from qgis.core import QgsMessageLog, Qgis
                                        except Exception:  # nosec B110  # 設計上の許容
                                            pass
                                except Exception:  # nosec B110  # 設計上の許容
                                    # ignore and leave wfs_typename as None
                                    pass

                            # Try calling generator with provided permalink (if any) and pass typename
                            try:
                                if permalink:
                                    temp_path = maplibre_generator.open_maplibre_from_permalink(permalink, wfs_typename)
                                elif x is not None and y is not None:
                                    # Build synthetic permalink from x/y/scale/crs/rotation parameters
                                    # Use x/y directly (not center_x/center_y) as maplibre_generator expects
                                    p = f"http://localhost/?x={x}&y={y}"
                                    if crs is not None:
                                        p += f"&crs={crs}"
                                    if scale is not None:
                                        p += f"&scale={scale}"
                                    if rotation is not None:
                                        p += f"&rotation={rotation}"
                                    temp_path = maplibre_generator.open_maplibre_from_permalink(p, wfs_typename)
                                elif lat is not None and lon is not None:
                                    # Build synthetic permalink from lat/lon/zoom parameters
                                    p = f"http://localhost/?lat={lat}&lon={lon}"
                                    if zoom is not None:
                                        p += f"&zoom={zoom}"
                                    temp_path = maplibre_generator.open_maplibre_from_permalink(p, wfs_typename)
                                else:
                                    # Fallback: 現在の地図キャンバスから合成パーマリンクを生成
                                    # (空パーマリンクは _parse_permalink が必ず失敗させるため)
                                    canvas_permalink = self._canvas_permalink()
                                    temp_path = maplibre_generator.open_maplibre_from_permalink(
                                        canvas_permalink or '', wfs_typename)
                            except Exception as e:
                                # If generator failed (e.g. couldn't parse permalink), attempt a safe fallback
                                try:
                                    QgsMessageLog.logMessage(f"⚠️ MapLibre generator failed: {e} - retrying with canvas permalink", "geo_webview", Qgis.MessageLevel.Warning)
                                except Exception:  # nosec B110  # 設計上の許容
                                    pass
                                try:
                                    temp_path = maplibre_generator.open_maplibre_from_permalink(
                                        self._canvas_permalink() or '', None)
                                except Exception:
                                    # re-raise original to be handled by outer exception handler
                                    raise

                            # Read the generated HTML file and send it
                            if temp_path and os.path.exists(temp_path):
                                with open(temp_path, 'r', encoding='utf-8') as f:
                                    html_content = f.read()
                        finally:
                            # restore original webbrowser.open regardless of outcome
                            try:
                                webbrowser.open = _orig_web_open
                            except Exception:  # nosec B110  # 設計上の許容
                                pass
                    except Exception:
                        # Any failure here falls back to lightweight generator
                        html_content = None

                    if not html_content:
                        # We assume PyQGIS is available in this simplified unified
                        # setup. If the QGIS-aware generator failed for any
                        # reason, return an error page rather than falling back
                        # to the standalone/lightweight generator which we are
                        # removing to keep the codebase PyQGIS-centric.
                        from . import http_server
                        error_html = self._generate_error_html_page(
                            "MapLibre HTML generation failed (QGIS-dependent generator failed)."
                        )
                        http_server.send_http_response(conn, 500, "Internal Server Error", error_html, "text/html; charset=utf-8")
                        return

                    # プレゼンテーション追従モード(follow/present指定時):
                    # /present/state をポーリングしてQGIS側の表示に追従する
                    if html_content and ('follow' in params or 'present' in params):
                        html_content = self._inject_follow_script(html_content, 'maplibre')

                    from . import http_server
                    http_server.send_http_response(conn, 200, "OK", html_content, "text/html; charset=utf-8")
                except Exception as e:
                    QgsMessageLog.logMessage(f"❌ MapLibre HTML page error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                    import traceback
                    QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(conn, 500, "Internal Server Error", f"MapLibre HTML page generation failed: {str(e)}")
                return

            # WMTS/XYZ endpoint: delegate to qmap_wmts_service for GetCapabilities and tiles
            if parsed_url.path.startswith('/wmts') or parsed_url.path.startswith('/xyz'):
                try:
                    # lazily create service if missing
                    if not hasattr(self, 'wmts_service') or self.wmts_service is None:
                        try:
                            from .wmts_service import GeoWebViewWMTSService
                            self.wmts_service = GeoWebViewWMTSService(self)
                        except Exception:
                            # Log import/instantiation failure so operator can diagnose
                            try:
                                import traceback
                                from qgis.core import QgsMessageLog, Qgis
                                QgsMessageLog.logMessage(
                                    f"Lazy WMTS service creation failed: {traceback.format_exc()}",
                                    "geo_webview",
                                    Qgis.MessageLevel.Warning
                                )
                            except Exception:
                                try:
                                    import sys
                                    import traceback
                                    sys.stderr.write('Lazy WMTS creation failed:\n')
                                    traceback.print_exc()
                                except Exception:  # nosec B110  # 設計上の許容
                                    pass
                            self.wmts_service = None

                    if self.wmts_service:
                        self.wmts_service.handle_wmts_request(conn, parsed_url, params, host)
                    else:
                        from . import http_server
                        http_server.send_http_response(conn, 501, 'Not Implemented', 'WMTS service not available')
                except Exception as e:
                    QgsMessageLog.logMessage(f"❌ WMTS delegation error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                    import traceback
                    QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(conn, 500, "Internal Server Error", f"WMTS processing failed: {str(e)}")
                return

            # Lightweight JSON endpoint to list publishable WFS vector layers
            if parsed_url.path == '/wfs-layers':
                try:
                    self._handle_wfs_layers(conn, params)
                except Exception as e:
                    QgsMessageLog.logMessage(f"❌ wfs-layers handler error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                    import traceback
                    QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(conn, 500, "Internal Server Error", f"wfs-layers failed: {str(e)}")
                return

            # WFS endpoint: delegate to qmap_wfs_service for GetCapabilities, GetFeature, DescribeFeatureType, and GetStyles
            if parsed_url.path.startswith('/wfs') or ('SERVICE' in params and params.get('SERVICE', [''])[0].upper() == 'WFS'):
                try:
                    # lazily create service if missing
                    if not hasattr(self, 'wfs_service') or self.wfs_service is None:
                        try:
                            from .wfs_service import GeoWebViewWFSService
                            self.wfs_service = GeoWebViewWFSService(self.iface, self.server_port)
                        except Exception:
                            self.wfs_service = None

                    if self.wfs_service:
                        # QMapPermalinkWFSService.handle_wfs_request expects (conn, params, host)
                        # (not parsed_url). Pass parameters accordingly.
                        try:
                            self.wfs_service.handle_wfs_request(conn, params, host)
                        except TypeError:
                            # Defensive fallback for older/alternate signatures that accept parsed_url
                            try:
                                self.wfs_service.handle_wfs_request(conn, parsed_url, params, host)
                            except Exception:
                                raise
                    else:
                        from . import http_server
                        http_server.send_http_response(conn, 501, 'Not Implemented', 'WFS service not available')
                except Exception as e:
                    QgsMessageLog.logMessage(f"❌ WFS delegation error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                    import traceback
                    QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(conn, 500, "Internal Server Error", f"WFS processing failed: {str(e)}")
                return
            if parsed_url.path == '/debug-bookmarks':
                try:
                    if hasattr(self, '_handle_debug_bookmarks') and callable(getattr(self, '_handle_debug_bookmarks')):
                        self._handle_debug_bookmarks(conn)
                    else:
                        # Handler not implemented in this instance
                        from . import http_server
                        http_server.send_http_response(conn, 501, 'Not Implemented', 'debug-bookmarks handler not available')
                except Exception as e:
                    QgsMessageLog.logMessage(f"❌ debug-bookmarks handler error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
                    import traceback
                    QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(conn, 500, "Internal Server Error", f"debug-bookmarks failed: {str(e)}")
                return

            # クライアントから受領したパーマリンク履歴(JSON)
            if parsed_url.path == '/received':
                try:
                    payload = json.dumps(
                        {'received': list(self.received_history)},
                        ensure_ascii=False)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK', payload,
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'received failed: {e}', 'text/plain; charset=utf-8')
                return

            # 現在のキャンバス状態(JSON)。プレゼンテーション追従用
            if parsed_url.path == '/present/state':
                try:
                    payload = json.dumps(
                        self._canvas_state_dict(), ensure_ascii=False)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK', payload,
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'present/state failed: {e}', 'text/plain; charset=utf-8')
                return

            # 現在のキャンバス表示と同等のPNG(プレゼンテーション共有用)
            if parsed_url.path == '/screenshot':
                try:
                    self._handle_screenshot(conn, params)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'❌ screenshot handler error: {e}',
                        'geo_webview', Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'screenshot failed: {e}', 'text/plain; charset=utf-8')
                return

            # プレゼンテーションページ(地図キャンバスのウィンドウ共有表示)
            if parsed_url.path == '/present':
                try:
                    self._handle_present_page(conn, params)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'❌ present handler error: {e}',
                        'geo_webview', Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'present failed: {e}', 'text/plain; charset=utf-8')
                return

            # KASUGAI Canvas 連携: 表示中レイヤを .kasc プロジェクトに出力し、
            # 起動中のKASUGAIへ登録してプロジェクトURLをJSONで返す
            # (生成ページ右上の KASUGAI ボタンから呼ばれる)
            if parsed_url.path == '/kasugai':
                try:
                    self._handle_kasugai(conn)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'❌ kasugai handler error: {e}',
                        'geo_webview', Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'kasugai failed: {e}', 'text/plain; charset=utf-8')
                return

            # OpenLayers+Cesiumの2画面3Dページ
            if parsed_url.path == '/map3d':
                try:
                    self._handle_map3d(conn, params, host)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'❌ map3d handler error: {e}',
                        'geo_webview', Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'map3d failed: {e}', 'text/plain; charset=utf-8')
                return

            # --- 静的ファイル配信: favicon.ico, style.json, data.geojson など ---
            import os
            # Support a few well-known static assets. Also allow serving small
            # companion scripts stored under maplibre/scripts (qmap_postload.js,
            # wmts_layers.js) by searching that directory as a fallback.
            static_files = ["/favicon.ico", "/style.json", "/data.geojson", "/qmap_postload.js", "/wmts_layers.js"]
            if parsed_url.path in static_files:
                # プラグインディレクトリからファイルを探す
                plugin_dir = os.path.dirname(os.path.abspath(__file__))
                fname = parsed_url.path.lstrip("/")

                # Candidate locations: plugin root, then maplibre/scripts
                candidates = [os.path.join(plugin_dir, fname), os.path.join(plugin_dir, 'maplibre', 'scripts', fname)]
                found = None
                for fpath in candidates:
                    try:
                        if os.path.exists(fpath):
                            found = fpath
                            break
                    except Exception:  # nosec B112  # 設計上の許容
                        continue

                if found:
                    # Content-Type判定
                    if fname.endswith(".ico"):
                        content_type = "image/x-icon"
                    elif fname.endswith(".json"):
                        content_type = "application/json; charset=utf-8"
                    elif fname.endswith(".geojson"):
                        content_type = "application/geo+json; charset=utf-8"
                    elif fname.endswith(".js"):
                        content_type = "application/javascript; charset=utf-8"
                    else:
                        content_type = "application/octet-stream"
                    with open(found, "rb") as f:
                        data = f.read()
                    http_server.send_binary_response(conn, 200, "OK", data, content_type)
                    return
                else:
                    http_server.send_http_response(conn, 404, "Not Found", f"File not found: {fname}", "text/plain; charset=utf-8")
                    return

            # 未対応のエンドポイントは404エラー
            QgsMessageLog.logMessage(f"❌ Unknown endpoint: {parsed_url.path}", "geo_webview", Qgis.MessageLevel.Warning)
            from . import http_server
            # 明示的に利用可能なエンドポイント一覧に /wmts と /wfs を含める
            http_server.send_http_response(
                conn,
                404,
                "Not Found",
                "Available endpoints: /wms (PNG image), /qgis-map (OpenLayers HTML), /maplibre (MapLibre HTML), /map3d (OpenLayers+Cesium 3D), /present (shared canvas view), /present/state (canvas JSON), /screenshot (canvas PNG), /received (permalink history), /wmts (WMTS tiles), /wfs (WFS service)"
            )
            return

    # ---------- MACアドレス認証 ----------

    @staticmethod
    def _norm_mac(value):
        """MAC表記を 'AA:BB:CC:DD:EE:FF' 大文字に正規化。不正値はNone。"""
        m = re.sub(r'[^0-9A-Fa-f]', '', str(value))
        if len(m) != 12:
            return None
        return ':'.join(m[i:i + 2] for i in range(0, 12, 2)).upper()

    def _local_macs(self):
        """このマシンのMACアドレス集合を返す(best-effort)。"""
        macs = set()
        try:
            import uuid
            n = self._norm_mac(format(uuid.getnode(), '012x'))
            if n:
                macs.add(n)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        try:
            import subprocess  # nosec B404  # 意図的なOSコマンド呼出し
            if os.name == 'nt':
                out = subprocess.check_output(  # nosec B603 B607
                    ['getmac', '/fo', 'csv', '/nh'], timeout=5)
                text = out.decode('mbcs', errors='replace')
                for token in re.findall(
                        r'(?:[0-9A-Fa-f]{2}[-:]){5}[0-9A-Fa-f]{2}', text):
                    n = self._norm_mac(token)
                    if n:
                        macs.add(n)
            else:
                sysd = '/sys/class/net'
                if os.path.isdir(sysd):
                    for dev in os.listdir(sysd):
                        try:
                            with open(os.path.join(sysd, dev, 'address')) as fh:
                                n = self._norm_mac(fh.read())
                                if n:
                                    macs.add(n)
                        except Exception:  # nosec B112  # 設計上の許容
                            continue
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return macs

    def _arp_lookup(self, ip):
        """ARPテーブルからリモートIPのMACアドレス集合を返す。"""
        macs = set()
        try:
            import subprocess  # nosec B404  # 意図的なOSコマンド呼出し
            if os.name == 'nt':
                out = subprocess.check_output(['arp', '-a'], timeout=5)  # nosec B603 B607
                text = out.decode('mbcs', errors='replace')
            else:
                try:
                    out = subprocess.check_output(  # nosec B603 B607
                        ['ip', 'neigh', 'show'], timeout=5)
                    text = out.decode(errors='replace')
                except Exception:
                    out = subprocess.check_output(['arp', '-a'], timeout=5)  # nosec B603 B607
                    text = out.decode(errors='replace')
            for line in text.splitlines():
                if ip in line:
                    for token in re.findall(
                            r'(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}', line):
                        n = self._norm_mac(token)
                        if n:
                            macs.add(n)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return macs

    def _resolve_client_macs(self, ip):
        """クライアントIPのMACアドレス集合(30秒キャッシュ)。"""
        now = time.time()
        ent = self._mac_cache.get(ip)
        if ent and now - ent[1] < 30:
            return ent[0]
        macs = set()
        try:
            if ip in ('127.0.0.1', '::1') or ip.startswith('::ffff:127.'):
                macs |= self._local_macs()
            else:
                macs |= self._arp_lookup(ip)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        self._mac_cache[ip] = (macs, now)
        return macs

    def _mac_auth_check(self, client_ip):
        """MAC認証モードの判定。無効時は常にTrue。

        有効時(QSettings geo_webview.mac_auth_enabled)は、クライアントの
        MACアドレスが mac_auth_allowed(空白/カンマ区切り)に登録済みか判定。
        """
        try:
            from qgis.PyQt.QtCore import QSettings
            s = QSettings('GeoWebView', 'geo_webview')
            enabled = str(
                s.value('mac_auth_enabled', 'false')).lower() in (
                    '1', 'true', 'yes', 'on')
            if not enabled:
                return True
            raw = s.value('mac_auth_allowed', '') or ''
            allowed = {
                self._norm_mac(m) for m in re.split(r'[\s,;]+', str(raw))
                if self._norm_mac(m)}
            if not allowed:
                return False
            client_macs = {
                self._norm_mac(m) for m in self._resolve_client_macs(client_ip)
                if self._norm_mac(m)}
            return bool(allowed & client_macs)
        except Exception:
            # 認証判定で例外が出た場合は安全側(拒否)
            return False

    # ---------- キャンバス状態 / プレゼンテーション ----------

    def _canvas_state_dict(self):
        """現在の地図キャンバス状態をJSON化可能なdictで返す。

        x/y/crs はキャンバスCRS、x3857/y3857 はEPSG:3857、lon/lat は
        EPSG:4326 にそれぞれ変換した中心座標。zoom はscaleからの推定。
        """
        canvas = self.iface.mapCanvas()
        ms = canvas.mapSettings()
        c = canvas.center()
        scale = canvas.scale()
        crs_auth = ms.destinationCrs().authid()
        rotation = 0.0
        try:
            rotation = float(canvas.rotation())
        except Exception:  # nosec B110  # 設計上の許容
            pass
        zoom = None
        try:
            from .scale_zoom import estimate_zoom_from_scale_maplibre
            zoom = estimate_zoom_from_scale_maplibre(scale)
        except Exception:
            try:
                from .scale_zoom import estimate_zoom_from_scale
                zoom = estimate_zoom_from_scale(scale)
            except Exception:
                zoom = None
        lon = lat = x3857 = y3857 = None
        try:
            src = QgsCoordinateReferenceSystem(crs_auth)
            if src.isValid():
                proj = QgsProject.instance()
                p4326 = QgsCoordinateTransform(
                    src, QgsCoordinateReferenceSystem('EPSG:4326'), proj
                ).transform(QgsPointXY(c.x(), c.y()))
                lon, lat = p4326.x(), p4326.y()
                p3857 = QgsCoordinateTransform(
                    src, QgsCoordinateReferenceSystem('EPSG:3857'), proj
                ).transform(QgsPointXY(c.x(), c.y()))
                x3857, y3857 = p3857.x(), p3857.y()
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return {
            'x': c.x(), 'y': c.y(), 'scale': scale, 'crs': crs_auth,
            'rotation': rotation, 'zoom': zoom,
            'lon': lon, 'lat': lat, 'x3857': x3857, 'y3857': y3857,
            'time': datetime.now().isoformat(timespec='seconds'),
        }

    def _handle_screenshot(self, conn, params):
        """現在の地図キャンバス表示と同等内容のPNGを返す(回転も反映)。

        QgsMapRendererParallelJob でキャンバスのMapSettingsを複製描画するため
        GUIスレッドをブロックしない。w/h(またはwidth/height)で出力サイズ指定可。
        """
        from . import http_server
        canvas = self.iface.mapCanvas()
        from qgis.core import QgsMapSettings
        from qgis.PyQt.QtCore import QSize, QBuffer, QIODevice, QByteArray
        ms = QgsMapSettings(canvas.mapSettings())
        w = self._safe_int(
            params.get('w', params.get('width', [0]))[0], 0)
        h = self._safe_int(
            params.get('h', params.get('height', [0]))[0], 0)
        if w <= 0 or h <= 0:
            try:
                w = int(canvas.width())
                h = int(canvas.height())
            except Exception:
                w, h = 0, 0
        if w <= 0 or h <= 0:
            w, h = 800, 600
        w = min(w, 4096)
        h = min(h, 4096)
        ms.setOutputSize(QSize(w, h))
        image = None
        try:
            if self.wms_service is not None:
                image = self.wms_service._execute_parallel_rendering(ms)
        except Exception:
            image = None
        if image is None or image.isNull():
            http_server.send_http_response(
                conn, 500, 'Internal Server Error', 'render failed',
                'text/plain; charset=utf-8')
            return
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        try:
            image.save(buf, 'PNG')
        finally:
            try:
                buf.close()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        data = bytes(ba)
        http_server.send_binary_response(
            conn, 200, 'OK', data, 'image/png')

    def _handle_present_page(self, conn, params):
        """地図キャンバスのウィンドウ共有ページ(/screenshot定期更新)を返す。"""
        from . import http_server
        interval = self._safe_int(params.get('interval', [1500])[0], 1500)
        if interval < 250:
            interval = 250
        S = _page_strings()
        html_page = u'''<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="initial-scale=1"/>
<title>geo_webview - Presentation</title>
<style>
html,body{{margin:0;padding:0;height:100%;background:#111;color:#eee;font-family:sans-serif}}
#wrap{{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden}}
#shot{{max-width:100%;max-height:100%}}
#info{{position:fixed;left:0;right:0;bottom:0;padding:4px 10px;background:rgba(0,0,0,.55);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
</style>
</head>
<body>
<div id="wrap"><img id="shot" alt="loading..."/></div>
<div id="info">geo_webview presentation</div>
<script>
(function(){{
  var img = document.getElementById('shot');
  var info = document.getElementById('info');
  var timer = {interval};
  function reload(){{
    var im = new Image();
    im.onload = function(){{ img.src = im.src; }};
    im.src = 'screenshot?ts=' + Date.now();
  }}
  async function state(){{
    try{{
      var r = await fetch('present/state'); var s = await r.json();
      if(s) info.textContent =
        'center: ' + (s.lon!=null? s.lon.toFixed(6)+','+s.lat.toFixed(6) : s.x.toFixed(1)+','+s.y.toFixed(1)) +
        '  scale: 1:' + Math.round(s.scale) +
        '  rotation: ' + (s.rotation||0).toFixed(1) + '°  crs: ' + s.crs +
        '  (' + s.time + ')';
    }}catch(e){{}}
  }}
  setInterval(reload, timer);
  setInterval(state, timer);
  reload(); state();
}})();
</script>
</body>
</html>'''.format(lang=S.get('lang', 'en'), interval=interval)
        http_server.send_http_response(
            conn, 200, 'OK', html_page, 'text/html; charset=utf-8')

    def _handle_map3d(self, conn, params, host):
        """OpenLayers+Cesiumの2画面3Dページを返す。"""
        from . import http_server
        nav = self._canvas_state_dict()
        # 明示パラメータがあれば上書き(値はキャンバスCRS基準)
        for k in ('x', 'y', 'scale', 'rotation'):
            try:
                if params.get(k):
                    nav[k] = float(params[k][0])
            except Exception:  # nosec B110  # 設計上の許容
                pass
        if params.get('crs'):
            nav['crs'] = params['crs'][0]
        # x/y がパラメータ指定された場合は各系へ変換し直す
        try:
            src = QgsCoordinateReferenceSystem(str(nav.get('crs')))
            if src.isValid() and nav.get('x') is not None:
                proj = QgsProject.instance()
                p4326 = QgsCoordinateTransform(
                    src, QgsCoordinateReferenceSystem('EPSG:4326'), proj
                ).transform(QgsPointXY(float(nav['x']), float(nav['y'])))
                nav['lon'], nav['lat'] = p4326.x(), p4326.y()
                p3857 = QgsCoordinateTransform(
                    src, QgsCoordinateReferenceSystem('EPSG:3857'), proj
                ).transform(QgsPointXY(float(nav['x']), float(nav['y'])))
                nav['x3857'], nav['y3857'] = p3857.x(), p3857.y()
        except Exception:  # nosec B110  # 設計上の許容
            pass
        try:
            from .scale_zoom import estimate_zoom_from_scale_maplibre
            nav['zoom'] = estimate_zoom_from_scale_maplibre(nav.get('scale'))
        except Exception:  # nosec B110  # 設計上の許容
            pass
        html_content = self.webmap_generator.generate_ol_cesium_page(
            nav, host or f'localhost:{self.server_port}')
        http_server.send_http_response(
            conn, 200, 'OK', html_content, 'text/html; charset=utf-8')

    def _handle_kasugai(self, conn):
        """表示中レイヤをKASUGAI Canvasプロジェクトとして出力し、
        起動中のKASUGAIローカルサーバへ登録してプロジェクトURLを返す。

        応答JSON:
          成功 {ok:true, url:<KASUGAIプロジェクトURL|null>, dir, layers, tiles}
          失敗 {ok:false, error}
        url が null の場合はKASUGAI未起動(出力のみ成功)を意味する。
        """
        from . import http_server, kasugai_export
        with self._kasugai_lock:
            result = kasugai_export.export_kasugai_project(self.iface)
            n_layers = len(result.get('layers') or [])
            n_tiles = len(result.get('tiles') or [])
            if not n_layers and not n_tiles:
                http_server.send_http_response(
                    conn, 200, 'OK',
                    json.dumps(
                        {'ok': False, 'error': 'no visible vector/tile layers'},
                        ensure_ascii=False),
                    'application/json; charset=utf-8')
                return
            url = None
            try:
                if kasugai_export.detect_kasugai():
                    reg = kasugai_export.register_kasugai_project(
                        result['kasc'])
                    if reg.get('ok'):
                        kasugai_export.kasugai_command(
                            'switchProject', {'projectId': reg['id']})
                        url = reg.get('url')
            except Exception as e:
                QgsMessageLog.logMessage(
                    f'⚠️ KASUGAI registration failed: {e}',
                    'geo_webview', Qgis.MessageLevel.Warning)
            http_server.send_http_response(
                conn, 200, 'OK',
                json.dumps(
                    {'ok': True, 'url': url, 'dir': result.get('dir'),
                     'layers': n_layers, 'tiles': n_tiles},
                    ensure_ascii=False),
                'application/json; charset=utf-8')

    def _inject_follow_script(self, html_content, kind):
        """生成HTMLにプレゼンテーション追従スクリプトを差し込む。

        kind: 'maplibre' または 'openlayers'。/present/state を定期ポーリングし
        QGIS側の表示位置・ズーム・回転をクライアント側地図へ強制反映する。
        """
        if kind == 'maplibre':
            js = u'''
<script>
(function(){
  function apply(s){
    try{
      var m = window.qmap_map || window.map;
      if(!m || !s) return;
      var opt = {};
      if(typeof s.lon === 'number' && typeof s.lat === 'number') opt.center = [s.lon, s.lat];
      if(typeof s.zoom === 'number') opt.zoom = s.zoom;
      if(typeof s.rotation === 'number') opt.bearing = -s.rotation;
      m.jumpTo(opt);
    }catch(e){}
  }
  async function tick(){
    try{ var r = await fetch('present/state'); apply(await r.json()); }catch(e){}
  }
  setInterval(tick, 1500); tick();
})();
</script>
'''
        else:
            js = u'''
<script>
(function(){
  function apply(s){
    try{
      var m = (typeof map !== 'undefined') ? map : (window.qmap_ol_map || window.map);
      if(!m || !s) return;
      var view = m.getView();
      if(typeof s.x3857 === 'number' && typeof s.y3857 === 'number') view.setCenter([s.x3857, s.y3857]);
      if(typeof s.zoom === 'number') view.setZoom(s.zoom);
      if(typeof s.rotation === 'number') view.setRotation(-s.rotation * Math.PI / 180);
    }catch(e){}
  }
  async function tick(){
    try{ var r = await fetch('present/state'); apply(await r.json()); }catch(e){}
  }
  setInterval(tick, 1500); tick();
})();
</script>
'''
        idx = html_content.rfind('</body>')
        if idx >= 0:
            return html_content[:idx] + js + html_content[idx:]
        return html_content + js

    def _handle_permalink_html_page(self, conn, params):
        """パーマリンクパラメータに基づいてWMSエンドポイントを使用するHTMLページを生成"""
        from qgis.core import QgsMessageLog, Qgis

        try:

            # パーマリンクパラメータを取得
            x = params.get('x', [None])[0]
            y = params.get('y', [None])[0]
            scale = params.get('scale', [None])[0]
            crs = params.get('crs', ['EPSG:3857'])[0]
            rotation = params.get('rotation', ['0.0'])[0]
            width = params.get('width', ['800'])[0]
            height = params.get('height', ['600'])[0]

            # x/y 未指定時は現在の地図キャンバスへフォールバック
            # (以前は暗黙に EPSG:3857 原点(0,0)へ飛んでいた)
            if x is None or y is None:
                try:
                    canvas = self.iface.mapCanvas()
                    if canvas is not None:
                        c = canvas.center()
                        x = str(c.x())
                        y = str(c.y())
                        if scale is None:
                            scale = str(canvas.scale())
                        crs = canvas.mapSettings().destinationCrs().authid()
                        if 'rotation' not in params:
                            rotation = str(canvas.rotation()) \
                                if hasattr(canvas, 'rotation') else '0.0'
                except Exception:  # nosec B110  # 設計上の許容
                    pass

            # Convert incoming center coordinates to EPSG:3857 unconditionally
            try:
                from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsPointXY
                if x is None or y is None:
                    raise ValueError('missing x/y parameters')
                src = QgsCoordinateReferenceSystem(str(crs))
                tgt = QgsCoordinateReferenceSystem('EPSG:3857')
                fx = float(x)
                fy = float(y)
                if src.isValid() and src.authid() != 'EPSG:3857':
                    transform = QgsCoordinateTransform(src, tgt, QgsProject.instance())
                    pt = transform.transform(QgsPointXY(fx, fy))
                    x3857 = str(pt.x())
                    y3857 = str(pt.y())
                else:
                    x3857 = str(fx)
                    y3857 = str(fy)
            except Exception:
                # If transformation fails, fall back to treating the values as already EPSG:3857
                x3857 = str(x if x is not None else 0)
                y3857 = str(y if y is not None else 0)

            # Generate HTML page using converted EPSG:3857 center coordinates
            html_content = self._generate_wms_based_html_page(x3857, y3857, scale, 'EPSG:3857', rotation, width, height)
            # プレゼンテーション追従モード(follow/present指定時)
            if html_content and ('follow' in params or 'present' in params):
                html_content = self._inject_follow_script(html_content, 'openlayers')
            # HTMLレスポンスを送信
            from . import http_server
            http_server.send_http_response(conn, 200, "OK", html_content, "text/html; charset=utf-8")

        except Exception as e:
            QgsMessageLog.logMessage(f"❌ Permalink HTML page generation error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            import traceback
            QgsMessageLog.logMessage(f"❌ Error traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)

            # エラー時はエラーページを返す
            error_html = self._generate_error_html_page(f"Error generating permalink page: {str(e)}")
            from . import http_server
            http_server.send_http_response(conn, 500, "Internal Server Error", error_html, "text/html; charset=utf-8")

    def _handle_debug_bookmarks(self, conn):
        """Return a JSON list of collected bookmarks (for debugging)."""
        from qgis.core import QgsProject
        try:
            bookmarks_list = []
            mgr = None
            try:
                mgr = QgsProject.instance().bookmarkManager()
            except Exception:
                try:
                    mgr = QgsProject.instance().bookmarks()
                except Exception:
                    mgr = None

            raw = None
            if mgr is not None:
                try:
                    raw = mgr.bookmarks()
                except Exception:
                    try:
                        raw = mgr.getBookmarks()
                    except Exception:
                        raw = None

            if raw:
                for b in raw:
                    name = ''
                    try:
                        if hasattr(b, 'name'):
                            name = b.name()
                        else:
                            name = str(getattr(b, 'displayName', '') or '')
                    except Exception:
                        try:
                            if isinstance(b, dict) and 'name' in b:
                                name = str(b.get('name'))
                        except Exception:
                            name = ''

                    bx = None
                    by = None
                    try:
                        if hasattr(b, 'point'):
                            p = b.point()
                            bx = p.x()
                            by = p.y()
                    except Exception:
                        bx = None
                        by = None

                    if (bx is None or by is None) and hasattr(b, 'center'):
                        try:
                            p = b.center()
                            bx = p.x()
                            by = p.y()
                        except Exception:  # nosec B110  # 設計上の許容
                            pass

                    if (bx is None or by is None) and hasattr(b, 'extent'):
                        try:
                            ext = b.extent()
                            bx = (ext.xMinimum() + ext.xMaximum()) / 2.0
                            by = (ext.yMinimum() + ext.yMaximum()) / 2.0
                        except Exception:  # nosec B110  # 設計上の許容
                            pass

                    if (bx is None or by is None) and isinstance(b, dict):
                        try:
                            if 'x' in b and 'y' in b:
                                bx = float(b.get('x'))
                                by = float(b.get('y'))
                            elif 'lon' in b and 'lat' in b:
                                bx = float(b.get('lon'))
                                by = float(b.get('lat'))
                        except Exception:  # nosec B110  # 設計上の許容
                            pass

                    if bx is None or by is None:
                        continue

                    # Attempt to determine source CRS id
                    src_crs_id = None
                    try:
                        if hasattr(b, 'crs'):
                            src_crs_id = b.crs()
                    except Exception:
                        src_crs_id = None

                    # Provide orig coords and placeholder for transformed values (transformation done elsewhere)
                    bookmarks_list.append({
                        'name': str(name),
                        'x': bx,
                        'y': by,
                        'src_crs': src_crs_id,
                        'orig_x': bx,
                        'orig_y': by
                    })

            import json
            payload = json.dumps({'bookmarks': bookmarks_list}, ensure_ascii=False)
            from . import http_server
            http_server.send_http_response(conn, 200, 'OK', payload, 'application/json; charset=utf-8')
        except Exception as e:
            try:
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(f'❌ debug-bookmarks error: {e}', 'QMapPermalink', Qgis.MessageLevel.Warning)
            except Exception:  # nosec B110  # 設計上の許容
                pass
            from . import http_server
            http_server.send_http_response(conn, 500, 'Internal Server Error', f'{{"error": "{str(e)}"}}', 'application/json; charset=utf-8')

    def _handle_wfs_layers(self, conn, params=None):
        """Return a JSON list of vector layers that can be exposed via WFS.

        Each item contains: name (normalized for TYPENAME), title, crs, bbox (WGS84)
        Supports query param 'only-visible' (1/true/yes) to return only layers
        currently visible in the map canvas.
        """
        try:
            from qgis.core import QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem, QgsCoordinateTransform
            layers_list = []

            # parse only-visible param
            only_visible = False
            try:
                if params:
                    val = params.get('only-visible', params.get('only_visible', params.get('visible', [''])))[0]
                    if isinstance(val, str) and val.lower() in ('1', 'true', 'yes', 'on'):
                        only_visible = True
            except Exception:
                only_visible = False

            visible_ids = None
            if only_visible:
                try:
                    canvas = self.iface.mapCanvas()
                    if canvas:
                        layer_tree_root = QgsProject.instance().layerTreeRoot()
                        visible_ids = set()
                        for lay in canvas.layers():
                            try:
                                lnode = layer_tree_root.findLayer(lay.id())
                                if lnode is not None and lnode.isVisible():
                                    visible_ids.add(lay.id())
                            except Exception:  # nosec B112  # 設計上の許容
                                continue
                except Exception:
                    visible_ids = None

            # Prefer project-level WFSLayers entry if present (QGIS project OWS/WFS export list)
            project = QgsProject.instance()
            try:
                wfs_ids, ok = project.readListEntry('WFSLayers', '/')
            except Exception:
                wfs_ids, ok = ([], False)

            # Determine which layer ids to iterate: require WFSLayers to be present
            if ok and wfs_ids:
                candidate_ids = [str(i) for i in wfs_ids]
            else:
                # No WFSLayers defined in project -> per request, do NOT fallback to all layers.
                import json
                payload = json.dumps({'layers': []}, ensure_ascii=False)
                from . import http_server
                http_server.send_http_response(conn, 200, 'OK', payload, 'application/json; charset=utf-8')
                return

            for lid in candidate_ids:
                try:
                    layer = QgsProject.instance().mapLayer(lid)
                    if not layer:
                        # skip missing / invalid entries
                        continue

                    if not isinstance(layer, QgsVectorLayer):
                        continue

                    if visible_ids is not None and layer.id() not in visible_ids:
                        continue

                    title = layer.name()
                    name_norm = title.replace(' ', '_')
                    crs = layer.crs().authid() if layer.crs().isValid() else 'EPSG:4326'

                    # attempt to get layer extent and convert to WGS84

                    def _sanitize_bbox_val(val):
                        import math
                        if val is None or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                            return None
                        return float(val)

                    try:
                        extent = layer.extent()
                        if layer.crs().authid() != 'EPSG:4326':
                            src = layer.crs()
                            tgt = QgsCoordinateReferenceSystem('EPSG:4326')
                            transform = QgsCoordinateTransform(src, tgt, QgsProject.instance())
                            extent = transform.transformBoundingBox(extent)
                        bbox = {
                            'minx': _sanitize_bbox_val(extent.xMinimum()),
                            'miny': _sanitize_bbox_val(extent.yMinimum()),
                            'maxx': _sanitize_bbox_val(extent.xMaximum()),
                            'maxy': _sanitize_bbox_val(extent.yMaximum())
                        }
                    except Exception:
                        bbox = {'minx': -180, 'miny': -90, 'maxx': 180, 'maxy': 90}

                    # レイヤの主色・線色を取得（単一シンボルのみ）
                    color = None
                    stroke_color = None
                    try:
                        renderer = layer.renderer()
                        if renderer and renderer.type() == 'singleSymbol':
                            symbol = renderer.symbol()
                            if symbol:
                                geom_type = layer.geometryType() if hasattr(layer, 'geometryType') else None
                                # 0: Point, 1: Line, 2: Polygon
                                if geom_type == 0:  # Point
                                    color = symbol.color().name(QColor.NameFormat.HexArgb) if hasattr(symbol.color(), 'name') else symbol.color().name()
                                elif geom_type == 1:  # Line
                                    color = symbol.color().name(QColor.NameFormat.HexArgb) if hasattr(symbol.color(), 'name') else symbol.color().name()
                                elif geom_type == 2:  # Polygon
                                    if hasattr(symbol, 'fillColor'):
                                        color = symbol.fillColor().name(QColor.NameFormat.HexArgb) if hasattr(symbol.fillColor(), 'name') else symbol.fillColor().name()
                                    if hasattr(symbol, 'strokeColor'):
                                        stroke_color = symbol.strokeColor().name(QColor.NameFormat.HexArgb) if hasattr(symbol.strokeColor(), 'name') else symbol.strokeColor().name()
                                    else:
                                        stroke_color = symbol.color().name(QColor.NameFormat.HexArgb) if hasattr(symbol.color(), 'name') else symbol.color().name()
                    except Exception:
                        color = None
                        stroke_color = None

                    try:
                        gt = layer.geometryType() if hasattr(layer, 'geometryType') else None
                        if gt == 0:
                            geom_type_name = 'Point'
                        elif gt == 1:
                            geom_type_name = 'LineString'
                        elif gt == 2:
                            geom_type_name = 'Polygon'
                        elif gt is None:
                            geom_type_name = 'Unknown'
                        else:
                            geom_type_name = str(gt)
                    except Exception:
                        geom_type_name = 'Unknown'

                    layer_entry = {
                        'id': layer.id(),
                        # canonical typename: use the QGIS layer.id() exactly
                        'typename': layer.id(),
                        'name': name_norm,
                        'title': title,
                        'crs': crs,
                        'bbox': bbox,
                        'geom_type': geom_type_name
                    }
                    if color:
                        layer_entry['color'] = color
                    if stroke_color:
                        layer_entry['stroke_color'] = stroke_color
                    layers_list.append(layer_entry)
                except Exception:  # nosec B112  # 設計上の許容
                    continue

            import json
            payload = json.dumps({'layers': layers_list}, ensure_ascii=False)
            from . import http_server
            http_server.send_http_response(conn, 200, 'OK', payload, 'application/json; charset=utf-8')
        except Exception as e:
            try:
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(f'❌ wfs-layers error: {e}', 'QMapPermalink', Qgis.MessageLevel.Warning)
            except Exception:  # nosec B110  # 設計上の許容
                pass
            from . import http_server
            http_server.send_http_response(conn, 500, 'Internal Server Error', f'{{"error": "{str(e)}"}}', 'application/json; charset=utf-8')

    def _collect_wfs_layers(self, only_visible: bool = False):
        """内部用: プロジェクトの WFSLayers エントリから publishable なレイヤ情報リストを返す。

        戻り値: list of dict items with keys: name, title, crs, bbox
        """
        try:
            from qgis.core import QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem, QgsCoordinateTransform
            layers_list = []

            visible_ids = None
            if only_visible:
                try:
                    canvas = self.iface.mapCanvas()
                    if canvas:
                        layer_tree_root = QgsProject.instance().layerTreeRoot()
                        visible_ids = set()
                        for lay in canvas.layers():
                            try:
                                lnode = layer_tree_root.findLayer(lay.id())
                                if lnode is not None and lnode.isVisible():
                                    visible_ids.add(lay.id())
                            except Exception:  # nosec B112  # 設計上の許容
                                continue
                except Exception:
                    visible_ids = None

            project = QgsProject.instance()
            try:
                wfs_ids, ok = project.readListEntry('WFSLayers', '/')
            except Exception:
                wfs_ids, ok = ([], False)

            if not (ok and wfs_ids):
                return []

            for lid in [str(i) for i in wfs_ids]:
                try:
                    layer = QgsProject.instance().mapLayer(lid)
                    if not layer:
                        continue
                    if not isinstance(layer, QgsVectorLayer):
                        continue
                    if visible_ids is not None and layer.id() not in visible_ids:
                        continue

                    title = layer.name()
                    name_norm = title.replace(' ', '_')
                    crs = layer.crs().authid() if layer.crs().isValid() else 'EPSG:4326'

                    def _sanitize_bbox_val(val):
                        import math
                        if val is None or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                            return None
                        return float(val)

                    try:
                        extent = layer.extent()
                        if layer.crs().authid() != 'EPSG:4326':
                            src = layer.crs()
                            tgt = QgsCoordinateReferenceSystem('EPSG:4326')
                            transform = QgsCoordinateTransform(src, tgt, QgsProject.instance())
                            extent = transform.transformBoundingBox(extent)
                        bbox = {
                            'minx': _sanitize_bbox_val(extent.xMinimum()),
                            'miny': _sanitize_bbox_val(extent.yMinimum()),
                            'maxx': _sanitize_bbox_val(extent.xMaximum()),
                            'maxy': _sanitize_bbox_val(extent.yMaximum())
                        }
                    except Exception:
                        bbox = {'minx': None, 'miny': None, 'maxx': None, 'maxy': None}

                    # レイヤの主色・線色を取得（QGISバージョン差異に配慮）
                    color = None
                    stroke_color = None
                    try:
                        from qgis.PyQt.QtGui import QColor
                        renderer = layer.renderer()
                        symbol = None
                        # categorizedSymbol/ruleBased/gradiented など複数シンボル系にも対応
                        if renderer:
                            rtype = renderer.type() if hasattr(renderer, 'type') else ''
                            if rtype == 'categorizedSymbol' and hasattr(renderer, 'categories'):
                                cats = renderer.categories()
                                if cats and hasattr(cats[0], 'symbol'):
                                    symbol = cats[0].symbol()
                            elif rtype == 'ruleRenderer' and hasattr(renderer, 'rootRule'):
                                root = renderer.rootRule()
                                rules = root.children() if root and hasattr(root, 'children') else []
                                if rules and hasattr(rules[0], 'symbol'):
                                    symbol = rules[0].symbol()
                            elif rtype == 'graduatedSymbol' and hasattr(renderer, 'ranges'):
                                ranges = renderer.ranges()
                                if ranges and hasattr(ranges[0], 'symbol'):
                                    symbol = ranges[0].symbol()
                            elif hasattr(renderer, 'symbols') and callable(renderer.symbols):
                                symbols = renderer.symbols()
                                if symbols:
                                    symbol = symbols[0]
                            elif hasattr(renderer, 'symbol') and callable(renderer.symbol):
                                symbol = renderer.symbol()
                        if symbol:
                            geom_type = layer.geometryType() if hasattr(layer, 'geometryType') else None
                            symbol_layer = symbol.symbolLayer(0) if hasattr(symbol, 'symbolLayer') and callable(symbol.symbolLayer) else None
                            if symbol_layer:
                                if hasattr(symbol_layer, 'fillColor') and callable(symbol_layer.fillColor):
                                    fill_c = symbol_layer.fillColor()
                                    color = fill_c.name(QColor.NameFormat.HexArgb) if hasattr(fill_c, 'name') else str(fill_c.name())
                                if hasattr(symbol_layer, 'strokeColor') and callable(symbol_layer.strokeColor):
                                    stroke_c = symbol_layer.strokeColor()
                                    stroke_color = stroke_c.name(QColor.NameFormat.HexArgb) if hasattr(stroke_c, 'name') else str(stroke_c.name())
                                if geom_type == 1 and not color and hasattr(symbol_layer, 'strokeColor') and callable(symbol_layer.strokeColor):
                                    stroke_c = symbol_layer.strokeColor()
                                    color = stroke_c.name(QColor.NameFormat.HexArgb) if hasattr(stroke_c, 'name') else str(stroke_c.name())
                                if geom_type == 0 and not color and hasattr(symbol_layer, 'fillColor') and callable(symbol_layer.fillColor):
                                    fill_c = symbol_layer.fillColor()
                                    color = fill_c.name(QColor.NameFormat.HexArgb) if hasattr(fill_c, 'name') else str(fill_c.name())
                            if not color and hasattr(symbol, 'color') and callable(symbol.color):
                                c = symbol.color()
                                color = c.name(QColor.NameFormat.HexArgb) if hasattr(c, 'name') else str(c.name())
                            if not stroke_color and hasattr(symbol, 'color') and callable(symbol.color):
                                c = symbol.color()
                                stroke_color = c.name(QColor.NameFormat.HexArgb) if hasattr(c, 'name') else str(c.name())
                        # symbol is None の場合は何もしない
                    except Exception:
                        color = None
                        stroke_color = None

                    try:
                        gt = layer.geometryType() if hasattr(layer, 'geometryType') else None
                        if gt == 0:
                            geom_type_name = 'Point'
                        elif gt == 1:
                            geom_type_name = 'LineString'
                        elif gt == 2:
                            geom_type_name = 'Polygon'
                        elif gt is None:
                            geom_type_name = 'Unknown'
                        else:
                            geom_type_name = str(gt)
                    except Exception:
                        geom_type_name = 'Unknown'

                    layer_entry = {
                        'id': layer.id(),
                        # canonical typename: use the QGIS layer.id() exactly
                        'typename': layer.id(),
                        'name': name_norm,
                        'title': title,
                        'crs': crs,
                        'bbox': bbox,
                        'geom_type': geom_type_name
                    }
                    if color:
                        layer_entry['color'] = color
                    if stroke_color:
                        layer_entry['stroke_color'] = stroke_color
                    layers_list.append(layer_entry)
                except Exception:  # nosec B112  # 設計上の許容
                    continue

            return layers_list
        except Exception:
            return []

    def _generate_wms_based_html_page(self, x, y, scale, crs, rotation, width, height):
        """WMSエンドポイントを使用するHTMLページを生成（WebMapGeneratorを使用）"""

        try:
            # WebMapGeneratorを使用してWMSベースのHTMLページを生成
            navigation_data = {
                'x': float(x),
                'y': float(y),
                'scale': float(scale),
                'crs': str(crs),
                'rotation': float(rotation)
            }

            server_port = self.http_server.getsockname()[1] if self.http_server else 8089
            # Try to collect QGIS spatial bookmarks and inject into navigation_data
            bookmarks_list = []
            try:
                from qgis.core import QgsProject, QgsMessageLog, Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY

                # Try common bookmark manager access patterns
                mgr = None
                try:
                    mgr = QgsProject.instance().bookmarkManager()
                except Exception:
                    try:
                        mgr = QgsProject.instance().bookmarks()
                    except Exception:
                        mgr = None

                if mgr is None:
                    QgsMessageLog.logMessage('🔍 Bookmark manager not found (mgr is None)', 'QMapPermalink', Qgis.MessageLevel.Warning)

                raw = None
                if mgr is not None:
                    try:
                        raw = mgr.bookmarks()
                    except Exception:
                        try:
                            raw = mgr.getBookmarks()
                        except Exception:
                            raw = None

                if raw is None:
                    pass
                else:
                    try:
                        _ = len(raw)
                    except Exception:
                        _ = 'unknown'

                if raw:
                    for b in raw:
                        # Extract name
                        name = ''
                        try:
                            if hasattr(b, 'name'):
                                name = b.name()
                            else:
                                name = str(getattr(b, 'displayName', '') or '')
                        except Exception:
                            try:
                                if isinstance(b, dict) and 'name' in b:
                                    name = str(b.get('name'))
                            except Exception:
                                name = ''

                        # Extract point-like coordinates from common accessors
                        bx = None
                        by = None
                        try:
                            if hasattr(b, 'point'):
                                p = b.point()
                                bx = p.x()
                                by = p.y()
                        except Exception:
                            bx = None
                            by = None

                        if (bx is None or by is None) and hasattr(b, 'center'):
                            try:
                                p = b.center()
                                bx = p.x()
                                by = p.y()
                            except Exception:  # nosec B110  # 設計上の許容
                                pass

                        if (bx is None or by is None) and hasattr(b, 'extent'):
                            try:
                                ext = b.extent()
                                bx = (ext.xMinimum() + ext.xMaximum()) / 2.0
                                by = (ext.yMinimum() + ext.yMaximum()) / 2.0
                            except Exception:  # nosec B110  # 設計上の許容
                                pass

                        if (bx is None or by is None) and isinstance(b, dict):
                            try:
                                if 'x' in b and 'y' in b:
                                    bx = float(b.get('x'))
                                    by = float(b.get('y'))
                                elif 'lon' in b and 'lat' in b:
                                    bx = float(b.get('lon'))
                                    by = float(b.get('lat'))
                            except Exception:  # nosec B110  # 設計上の許容
                                pass

                        if bx is None or by is None:
                            # couldn't obtain coordinates for this bookmark
                            continue

                        # Determine source CRS for bookmark if available
                        src_crs = None
                        try:
                            if hasattr(b, 'crs'):
                                src_crs = b.crs()
                        except Exception:
                            src_crs = None

                        if not src_crs:
                            try:
                                src_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
                            except Exception:
                                src_crs = QgsCoordinateReferenceSystem('EPSG:3857')

                        # Transform bookmark original coordinates to EPSG:3857 (client expects 3857)
                        try:
                            tgt_crs = QgsCoordinateReferenceSystem('EPSG:3857')
                            transform = QgsCoordinateTransform(src_crs, tgt_crs, QgsProject.instance())
                            pt = transform.transform(QgsPointXY(bx, by))
                            lon = float(pt.x())
                            lat = float(pt.y())
                        except Exception:
                            lon = float(bx)
                            lat = float(by)

                        # determine original source CRS id for potential proj4 registration
                        src_crs_id = None
                        try:
                            if hasattr(src_crs, 'authid'):
                                src_crs_id = src_crs.authid()
                            else:
                                src_crs_id = str(src_crs)
                        except Exception:
                            src_crs_id = None

                        # Keep both a client-friendly lon/lat in EPSG:4326 and the
                        # original bookmark coordinates (orig_x/orig_y) in the
                        # bookmark's source CRS so the client can request the
                        # server to render using the original CRS when available.
                        bookmarks_list.append({
                            'name': str(name),
                            # provide bookmark coordinates already in EPSG:3857 for client
                            'x': lon,
                            'y': lat,
                            'crs': 'EPSG:3857',
                            'src_crs': src_crs_id,
                            'orig_x': bx,
                            'orig_y': by
                        })
            except Exception:
                # On any issue, don't block page generation; just omit bookmarks
                try:
                    from qgis.core import QgsMessageLog, Qgis
                    QgsMessageLog.logMessage('❌ Error while extracting bookmarks; skipping bookmarks', 'QMapPermalink', Qgis.MessageLevel.Warning)
                except Exception:  # nosec B110  # 設計上の許容
                    pass

            if bookmarks_list:
                navigation_data['bookmarks'] = bookmarks_list

            # Try to collect available map themes and inject into navigation_data
            themes_list = []
            try:
                from qgis.core import QgsProject
                project = QgsProject.instance()
                try:
                    theme_collection = project.mapThemeCollection()
                except Exception:
                    theme_collection = None

                if theme_collection:
                    try:
                        available = theme_collection.mapThemes()
                        # mapThemes() may return dict-like or iterable of names
                        if isinstance(available, dict):
                            themes_list = sorted(list(available.keys()))
                        else:
                            # ensure list of strings
                            themes_list = [str(t) for t in available]
                    except Exception:
                        themes_list = []
            except Exception:
                themes_list = []

            if themes_list:
                navigation_data['themes'] = themes_list

            # WebMapGeneratorの新しいメソッドを使用
            html_content = self.webmap_generator.generate_wms_based_html_page(
                navigation_data,
                int(width),
                int(height),
                server_port
            )

            return html_content

        except Exception:
            # フォールバック: シンプルなWMSベースHTMLページ
            server_port = self.http_server.getsockname()[1] if self.http_server else 8089
            # Use relative WMS URL so clients use the same origin as the HTML page
            _ = "/"
            wms_url = f"/wms?x={x}&y={y}&scale={scale}&crs={crs}&rotation={rotation}&width={width}&height={height}"

        # Build head scripts for OpenLayers using shared utility
        try:
            from qmap_permalink.proj_utils import build_ol_proj_head
            head_scripts = build_ol_proj_head(crs)
        except Exception:
            # fallback include
            head_scripts = (
                '    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ol@v8.2.0/ol.css" type="text/css">\n'
                '    <script src="https://cdn.jsdelivr.net/npm/ol@v8.2.0/dist/ol.js"></script>\n'
            )

        # Projection registration via proj4 is no longer used. The plugin
        # enforces EPSG:3857 on the client and performs server-side transforms
        # earlier in the request handling, so no additional special-case is necessary here.

        # OpenLayersを使用したHTMLページテンプレート
        S = _page_strings()
        html_template = f"""<!DOCTYPE html>
<html lang="{S['lang']}">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{S['title']}</title>
{head_scripts}
    <style>
        body {{
            margin: 0;
            padding: 20px;
            font-family: Arial, sans-serif;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .header {{
            background: #2c3e50;
            color: white;
            padding: 20px;
            text-align: center;
        }}
        .map-container {{
            position: relative;
            height: 600px;
            border: 2px solid #ddd;
        }}
        #map {{
            width: 100%;
            height: 100%;
        }}
        .info-panel {{
            padding: 20px;
            background: #ecf0f1;
            border-top: 1px solid #ddd;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .info-item {{
            background: white;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #3498db;
        }}
        .info-label {{
            font-weight: bold;
            color: #2c3e50;
            margin-bottom: 5px;
        }}
        .info-value {{
            color: #555;
            font-family: monospace;
        }}
        .controls {{
            padding: 20px;
            background: #f8f9fa;
            border-top: 1px solid #ddd;
            text-align: center;
        }}
        .btn {{
            padding: 10px 20px;
            margin: 5px;
            background: #3498db;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }}
        .btn:hover {{
            background: #2980b9;
        }}
        .btn-secondary {{
            background: #95a5a6;
        }}
        .btn-secondary:hover {{
            background: #7f8c8d;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🗺️ QMap Permalink</h1>
            <p>{S['subtitle']}</p>
        </div>

        <div class="map-container">
            <div id="map"></div>
        </div>

        <div class="info-panel">
            <h3>{S['map_info']}</h3>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">{S['center_x']}</div>
                    <div class="info-value">{x}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">{S['center_y']}</div>
                    <div class="info-value">{y}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">{S['scale']}</div>
                    <div class="info-value">1:{scale}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">{S['crs']}</div>
                    <div class="info-value">{crs}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">{S['rotation']}</div>
                    <div class="info-value">{rotation}°</div>
                </div>
                <div class="info-item">
                    <div class="info-label">{S['image_size']}</div>
                    <div class="info-value">{width} × {height}</div>
                </div>
            </div>
        </div>

        <div class="controls">
            <h3>{S['controls']}</h3>
            <a href="{wms_url}" target="_blank" class="btn">{S['wms_image']}</a>
            <a href="/wms?SERVICE=WMS&REQUEST=GetCapabilities" target="_blank" class="btn btn-secondary">📋 WMS Capabilities</a>
            <button onclick="refreshMap()" class="btn">{S['refresh']}</button>
            <button onclick="copyPermalink()" class="btn btn-secondary">{S['copy_link']}</button>
        </div>
    </div>

    <script>
        // OpenLayers地図の初期化
        const centerX = parseFloat('{x}');
        const centerY = parseFloat('{y}');
        const mapScale = parseFloat('{scale}');
        const mapRotation = parseFloat('{rotation}') * Math.PI / 180; // ラジアンに変換
        const mapCrs = '{crs}';

        // 地図の初期化
        const map = new ol.Map({{
            target: 'map',
            layers: [
                new ol.layer.Image({{
                    source: new ol.source.ImageWMS({{
                        url: '/wms',
                        params: {{
                            'x': centerX,
                            'y': centerY,
                            'scale': mapScale,
                            'crs': mapCrs,
                            'ANGLE': {rotation},
                            'width': 800,
                            'height': 600
                        }},
                        serverType: 'qgis',
                        crossOrigin: 'anonymous'
                    }})
                }})
            ],
            view: new ol.View({{
                center: [centerX, centerY],
                zoom: calculateZoomFromScale(mapScale),
                rotation: mapRotation,
                projection: mapCrs
            }})
        }});

        // Ensure the WMS source receives the initial ANGLE param (degrees)
        try {{
            var _wmsSrc = map.getLayers().getArray()[0].getSource();
            try {{ window.wmsSource = _wmsSrc; }} catch(e) {{}}
            var _initAngleDeg = 0;
            try {{ _initAngleDeg = (typeof mapRotation === 'number') ? (mapRotation * 180 / Math.PI) : (parseFloat('{rotation}') || 0); }} catch(e) {{ _initAngleDeg = parseFloat('{rotation}') || 0; }}
            if(_wmsSrc && typeof _wmsSrc.updateParams === 'function') {{
                try {{ _wmsSrc.updateParams({{ 'ANGLE': _initAngleDeg }}); }} catch(e) {{}}
                try {{ _wmsSrc.refresh(); }} catch(e) {{}}
            }}
        }} catch(e) {{ /* fail silently */ }}

        // 北向き矢印コントロールを追加
        map.addControl(new ol.control.Rotate({{
            tipLabel: '{S['tip_rotate']}',
            resetNorthLabel: '{S['tip_reset']}'
        }}));

        // スケールからズームレベルを計算する関数
        function calculateZoomFromScale(scale) {{
            // 概算でのズームレベル計算
            const baseScale = 591657527.591555;
            return Math.log2(baseScale / scale);
        }}

        // 地図の回転に合わせてWMSパラメータも更新
        map.getView().on('change:rotation', function() {{
            const rotation = map.getView().getRotation();
            const angleDeg = rotation * 180 / Math.PI;
            const wmsSource = map.getLayers().getArray()[0].getSource();
            if(wmsSource && typeof wmsSource.updateParams === 'function'){{
                wmsSource.updateParams({{ 'ANGLE': angleDeg }});
                wmsSource.refresh();
            }}
        }});

        // 地図を更新する関数
        function refreshMap() {{
            map.getView().setCenter([centerX, centerY]);
            map.getView().setZoom(calculateZoomFromScale(mapScale));
            // Do not force rotation to 0 here; preserve current view rotation.
            map.getLayers().getArray()[0].getSource().refresh();
        }}

        // パーマリンクをコピーする関数
        function copyPermalink() {{
            const permalink = window.location.href;
            navigator.clipboard.writeText(permalink).then(() => {{
                alert('{S['copied']}');
            }}).catch(() => {{
                // フォールバック
                const textArea = document.createElement('textarea');
                textArea.value = permalink;
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                alert('{S['copied']}');
            }});
        }}

        // ページ読み込み完了時の処理
        document.addEventListener('DOMContentLoaded', function() {{
            console.log('🗺️ QMap Permalink page loaded');
            console.log('📍 Center:', centerX, centerY);
            console.log('📏 Scale:', mapScale);
            console.log('🔄 Rotation:', '{rotation}°');
            console.log('🌐 CRS:', mapCrs);
        }});
    </script>
</body>
</html>"""

        return html_template

    def _canvas_permalink(self):
        """現在の地図キャンバスから /maplibre 用の合成パーマリンクを生成する。

        maplibre_generator.open_maplibre_from_permalink は空文字列を受理
        しないため、パラメータ無しリクエスト時のフォールバックに使う。
        キャンバスが読めない場合は None を返す。
        """
        try:
            canvas = self.iface.mapCanvas()
            if canvas is None:
                return None
            center = canvas.center()
            scale = canvas.scale()
            crs = canvas.mapSettings().destinationCrs().authid()
            rotation = canvas.rotation() if hasattr(canvas, 'rotation') else 0.0
            return (f"http://localhost/?x={center.x()}&y={center.y()}"
                    f"&crs={crs}&scale={scale}&rotation={rotation}")
        except Exception:
            return None

    def _build_navigation_data_from_params(self, params):
        """互換性用: HTTPパラメータ(dict of lists)から navigation_data を構築して返す

        params: dict where values are lists (urllib.parse.parse_qs形式)

        Returns:
            dict: navigation_data. Examples:
                {'type': 'location', 'location': '<encoded json>'}
                {'type': 'coordinates', 'x': x, 'y': y, 'scale': scale, 'crs': crs, 'zoom': zoom, 'rotation': rotation, 'theme_info': theme}

        Raises:
            ValueError: 必要なパラメータが不足している場合
        """
        from qgis.core import QgsMessageLog, Qgis

        try:
            # location パラメータがあれば location タイプ
            if 'location' in params and params['location']:
                location_val = params['location'][0]
                return {'type': 'location', 'location': location_val}

            # coordinates ベース: x, y が必須
            if 'x' in params and 'y' in params:
                x_val = params.get('x', [None])[0]
                y_val = params.get('y', [None])[0]
                if x_val is None or y_val is None:
                    raise ValueError('x or y parameter missing')

                # optional params
                scale_val = params.get('scale', [None])[0]
                zoom_val = params.get('zoom', [None])[0]
                crs_val = params.get('crs', [None])[0]
                rotation_val = params.get('rotation', [None])[0]
                theme_val = params.get('theme', [None])[0]

                navigation_data = {
                    'type': 'coordinates',
                    'x': float(x_val) if x_val is not None else None,
                    'y': float(y_val) if y_val is not None else None,
                    'scale': float(scale_val) if scale_val is not None else None,
                    'zoom': float(zoom_val) if zoom_val is not None else None,
                    'crs': str(crs_val) if crs_val is not None else None,
                    'rotation': float(rotation_val) if rotation_val is not None else None,
                    'theme_info': theme_val
                }

                return navigation_data

            # フォールバック: 不明なパラメータ
            raise ValueError('No navigation parameters found')

        except Exception as e:
            QgsMessageLog.logMessage(f"Error building navigation_data from params: {e}", "geo_webview", Qgis.MessageLevel.Warning)
            raise

    def _generate_error_html_page(self, error_message):
        """エラーページのHTMLを生成"""
        S = _page_strings()
        error_html = f"""<!DOCTYPE html>
<html lang="{S['lang']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{S['err_title']}</title>
    <style>
        body {{
            margin: 0;
            padding: 40px;
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .error-container {{
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            text-align: center;
            max-width: 500px;
        }}
        .error-icon {{
            font-size: 4rem;
            margin-bottom: 20px;
        }}
        .error-title {{
            color: #e74c3c;
            margin-bottom: 20px;
            font-size: 1.5rem;
        }}
        .error-message {{
            color: #555;
            margin-bottom: 30px;
            line-height: 1.6;
        }}
        .btn {{
            padding: 12px 24px;
            background: #3498db;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            display: inline-block;
            margin: 5px;
        }}
        .btn:hover {{
            background: #2980b9;
        }}
    </style>
</head>
<body>
    <div class="error-container">
        <div class="error-icon">❌</div>
        <h1 class="error-title">{S['err_failed']}</h1>
        <p class="error-message">{html.escape(error_message)}</p>
        <a href="javascript:history.back()" class="btn">{S['back']}</a>
        <a href="/" class="btn">{S['home']}</a>
    </div>
</body>
</html>"""
        return error_html

    def _calculate_bbox_from_permalink(self, center_x, center_y, scale, width, height, crs):
        """パーマリンクパラメータからBBOXを計算"""
        try:
            from qgis.core import QgsMessageLog, Qgis

            # 画面解像度（DPI）とピクセルあたりのサイズを計算
            dpi = 96  # 標準DPI
            meters_per_inch = 0.0254
            pixels_per_meter = dpi / meters_per_inch

            # スケールから地図単位での表示範囲を計算
            map_width_m = (width / pixels_per_meter) * scale
            map_height_m = (height / pixels_per_meter) * scale

            # 中心点から範囲を計算
            half_width = map_width_m / 2
            half_height = map_height_m / 2

            minx = center_x - half_width
            miny = center_y - half_height
            maxx = center_x + half_width
            maxy = center_y + half_height

            bbox = f"{minx},{miny},{maxx},{maxy}"

            return bbox

        except Exception as e:
            QgsMessageLog.logMessage(f"❌ BBOX calculation error: {e}", "geo_webview", Qgis.MessageLevel.Warning)
            return None

    def _handle_wms_get_map_with_bbox(self, conn, bbox, crs, width, height, rotation=0.0):
        """計算されたBBOXでWMS GetMapを処理"""
        from qgis.core import QgsMessageLog, Qgis

        try:
            # If requested CRS is not EPSG:3857, transform bbox to EPSG:3857
            try:
                if crs and crs.upper() != 'EPSG:3857' and bbox:
                    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
                    src_crs = QgsCoordinateReferenceSystem(crs)
                    tgt_crs = QgsCoordinateReferenceSystem('EPSG:3857')
                    if src_crs.isValid():
                        coords = [float(x) for x in bbox.split(',')]
                        if len(coords) == 4:
                            rect = QgsRectangle(coords[0], coords[1], coords[2], coords[3])
                            transform = QgsCoordinateTransform(src_crs, tgt_crs, QgsProject.instance())
                            rect = transform.transformBoundingBox(rect)
                            bbox = f"{rect.xMinimum()},{rect.yMinimum()},{rect.xMaximum()},{rect.yMaximum()}"
                            crs = 'EPSG:3857'
                    else:
                        QgsMessageLog.logMessage(f"⚠️ Invalid CRS '{crs}' - forcing to EPSG:3857", "geo_webview", Qgis.MessageLevel.Warning)
                        crs = 'EPSG:3857'
            except Exception:  # nosec B110  # 設計上の許容
                pass

            # Use canvas-based rendering as the authoritative method for
            # permalink BBOX requests. Rotation handling should be applied
            # via canvas extent/rotation adjustment if needed.
            png_data = self._generate_qgis_map_png(width, height, bbox, crs, rotation)
            if png_data and len(png_data) > 1000:
                from . import http_server
                http_server.send_binary_response(conn, 200, "OK", png_data, "image/png")
                return

            # 最終フォールバック: エラー画像
            error_image = self._generate_error_image(width, height, "Permalink Rendering Failed")
            from . import http_server
            http_server.send_binary_response(conn, 200, "OK", error_image, "image/png")

        except Exception as e:
            QgsMessageLog.logMessage(f"❌ WMS GetMap with BBOX error: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            error_image = self._generate_error_image(width, height, f"Error: {str(e)}")
            from . import http_server
            http_server.send_binary_response(conn, 200, "OK", error_image, "image/png")

    def _generate_webmap_png(self, width, height, bbox, crs):
        """WebMapGeneratorを使用してPNG画像を生成"""
        try:
            from qgis.core import QgsMessageLog, Qgis

            if not self.webmap_generator:
                QgsMessageLog.logMessage("❌ WebMapGenerator not available", "geo_webview", Qgis.MessageLevel.Warning)
                return None

            # WebMapGeneratorにダミーのナビゲーションデータを渡す
            navigation_data = {
                'type': 'coordinates',
                'lat': 35.6762,  # 東京駅
                'lon': 139.6503,
                'crs': 'EPSG:4326',
                'scale': 10000,
                'zoom': 10
            }

            # WMSパラメータからナビゲーションデータを更新
            if bbox and crs:
                try:
                    coords = [float(x) for x in bbox.split(',')]
                    if len(coords) == 4:
                        minx, miny, maxx, maxy = coords
                        center_lon = (minx + maxx) / 2
                        center_lat = (miny + maxy) / 2
                        navigation_data.update({
                            'lon': center_lon,
                            'lat': center_lat,
                            'crs': crs
                        })
                except Exception as e:
                    QgsMessageLog.logMessage(f"⚠️ Failed to parse BBOX: {e}", "geo_webview", Qgis.MessageLevel.Warning)

            # WebMapGeneratorを使って画像を生成
            try:
                # generate_qgis_image_map メソッドを使用（HTML文字列を取得）
                html_content = self.webmap_generator.generate_qgis_image_map(navigation_data, width, height)

                # HTMLコンテンツからbase64画像データを抽出
                import re
                base64_match = re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)', html_content)
                if base64_match:
                    import base64
                    png_data = base64.b64decode(base64_match.group(1))
                    return png_data
                else:
                    QgsMessageLog.logMessage("❌ No base64 image found in WebMapGenerator output", "geo_webview", Qgis.MessageLevel.Warning)
                    return None

            except Exception as e:
                QgsMessageLog.logMessage(f"❌ WebMapGenerator generation failed: {e}", "geo_webview", Qgis.MessageLevel.Warning)
                return None

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"❌ Error in _generate_webmap_png: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            return None

    def _generate_qgis_map_png(self, width, height, bbox, crs, rotation=0.0):
        """Generate PNG using PyQGIS independent renderer only.

        This implementation avoids canvas capture and always uses the
        independent renderer (QgsMapSettings + QgsMapRendererParallelJob).
        """
        from qgis.core import QgsMessageLog, Qgis

        try:
            return self._render_map_image(width, height, bbox, crs, rotation)
        except Exception as e:
            QgsMessageLog.logMessage(f"❌ Error in _generate_qgis_map_png (delegated): {e}", "geo_webview", Qgis.MessageLevel.Critical)
            return None

    def _capture_canvas_image(self, width, height):
        """キャンバスから直接画像をキャプチャ"""
        # Qt GUI operations (like canvas.grab()) must run in the GUI/main thread.
        # The HTTP server runs in a worker thread, so calling canvas.grab() directly
        # can cause an access violation. To avoid this we request a capture on the
        # main thread via a helper QObject that emits a signal when done, and
        # we wait synchronously (with a timeout) for the result.
        try:
            from qgis.core import QgsMessageLog, Qgis
            from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot, QEventLoop, QTimer, QCoreApplication

            # Define the helper only once and keep it on the instance.
            if not hasattr(self, '_capture_helper') or self._capture_helper is None:
                class _CanvasCaptureHelper(QObject):
                    request_capture = pyqtSignal(int, int)
                    finished = pyqtSignal(bytes)

                    def __init__(self, iface):
                        super().__init__()
                        self.iface = iface
                        # connect request -> internal slot which runs in helper's thread
                        self.request_capture.connect(self._do_capture)

                    @pyqtSlot(int, int)
                    def _do_capture(self, w, h):
                        try:
                            canvas = self.iface.mapCanvas()
                            if not canvas:
                                QgsMessageLog.logMessage("❌ No map canvas available (helper)", "geo_webview", Qgis.MessageLevel.Warning)
                                self.finished.emit(b'')
                                return

                            # Allow pending paint events to finish so labels/symbols
                            # complete rendering before grabbing.
                            try:
                                from qgis.PyQt.QtWidgets import QApplication
                                QApplication.processEvents()
                            except Exception:  # nosec B110  # 設計上の許容
                                pass

                            pixmap = canvas.grab()
                            if pixmap.isNull():
                                QgsMessageLog.logMessage("❌ Failed to grab canvas pixmap (helper)", "geo_webview", Qgis.MessageLevel.Warning)
                                self.finished.emit(b'')
                                return

                            # scale if requested size differs
                            try:
                                from qgis.PyQt.QtCore import Qt
                                # For WMS we should match the requested size exactly
                                if w and h and (w != pixmap.width() or h != pixmap.height()):
                                    pixmap = pixmap.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                            except Exception:  # nosec B110  # 設計上の許容
                                pass

                            image = pixmap.toImage()
                            if image.isNull():
                                QgsMessageLog.logMessage("❌ Failed to convert pixmap to image (helper)", "geo_webview", Qgis.MessageLevel.Warning)
                                self.finished.emit(b'')
                                return

                            from qgis.PyQt.QtCore import QByteArray, QBuffer, QIODevice
                            byte_array = QByteArray()
                            buffer = QBuffer(byte_array)
                            # QIODevice.OpenModeFlag.WriteOnly may be namespaced differently in Qt6/PyQt6.
                            write_mode = getattr(QIODevice, 'WriteOnly', None)
                            if write_mode is None:
                                om = getattr(QIODevice, 'OpenMode', None) or getattr(QIODevice, 'OpenModeFlag', None)
                                if om is not None and hasattr(om, 'WriteOnly'):
                                    write_mode = getattr(om, 'WriteOnly')
                            if write_mode is None:
                                try:
                                    write_mode = int(1)
                                except Exception:
                                    write_mode = 1
                            buffer.open(write_mode)
                            success = image.save(buffer, "PNG")
                            if not success:
                                QgsMessageLog.logMessage("❌ Failed to save image as PNG (helper)", "geo_webview", Qgis.MessageLevel.Warning)
                                self.finished.emit(b'')
                                return

                            png_data = byte_array.data()
                            self.finished.emit(png_data)

                        except Exception as e:
                            QgsMessageLog.logMessage(f"❌ Exception in helper capture: {e}", "geo_webview", Qgis.MessageLevel.Warning)
                            try:
                                self.finished.emit(b'')
                            except Exception:  # nosec B110  # 設計上の許容
                                pass

                # Create helper and move it to the main (GUI) thread so its slot runs there.
                helper = _CanvasCaptureHelper(self.iface)
                try:
                    main_thread = QCoreApplication.instance().thread()
                    helper.moveToThread(main_thread)
                except Exception:  # nosec B110  # 設計上の許容
                    # If moveToThread fails for any reason, keep helper in current thread
                    pass
                self._capture_helper = helper

            helper = self._capture_helper

            # Prepare an event loop to wait for the capture to finish (with timeout).
            loop = QEventLoop()
            captured = {'data': b''}

            def _on_finished(data):
                captured['data'] = data or b''
                try:
                    loop.quit()
                except Exception:  # nosec B110  # 設計上の許容
                    pass

            helper.finished.connect(_on_finished)

            # Emit request; because helper lives in GUI thread, the connected slot
            # will be invoked there. Emission from worker thread is safe and
            # delivery is queued to the helper's thread.
            helper.request_capture.emit(int(width), int(height))

            # Safety timeout (5 seconds) to avoid hanging the server thread forever.
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: loop.quit())
            timer.start(5000)

            loop.exec()
            try:
                helper.finished.disconnect(_on_finished)
            except Exception:  # nosec B110  # 設計上の許容
                pass

            png = captured.get('data')
            if png and len(png) > 0:
                return png

            # If capture failed or timed out, fallback to None so caller can try
            # other rendering approaches.
            QgsMessageLog.logMessage("⚠️ Canvas capture timed out or failed", "geo_webview", Qgis.MessageLevel.Warning)
            return None

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"❌ Error in _capture_canvas_image: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            return None

    def _render_map_image(self, width, height, bbox, crs, rotation=0.0):
        """独立レンダラでPNGを生成する（rotation をサポート）

        Args:
            width, height: 出力ピクセルサイズ
            bbox: 'minx,miny,maxx,maxy' 文字列または None
            crs: CRS文字列（例: 'EPSG:3857'）
            rotation: 地図回転角度（度単位）。QgsMapSettings の回転サポートがある場合に使用されます。
        """
        from qgis.core import QgsMessageLog, Qgis

        try:
            # WMS独立レンダリング設定を作成(同時レンダリング防止のため直列化)
            with self._render_lock:
                map_settings = self._create_wms_map_settings(width, height, bbox, crs, rotation=rotation)
                if not map_settings:
                    QgsMessageLog.logMessage("❌ Failed to create WMS map settings", "geo_webview", Qgis.MessageLevel.Warning)
                    return None

                # 独立したマップレンダラーでPNG画像を生成
                png_data = self._execute_map_rendering(map_settings)
            if png_data:
                return png_data
            else:
                QgsMessageLog.logMessage("❌ Professional WMS rendering failed", "geo_webview", Qgis.MessageLevel.Warning)
                return None

        except Exception as e:
            QgsMessageLog.logMessage(f"❌ Error in professional WMS rendering: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            import traceback
            QgsMessageLog.logMessage(f"❌ Traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
            return None

    def _create_wms_map_settings(self, width, height, bbox, crs, rotation=0.0):
        """WMS用の独立したマップ設定を作成 - キャンバスに依存しない

        rotation: 回転角度（度） — map settings が回転をサポートする場合は適用します。
        """
        from qgis.core import QgsMapSettings, QgsRectangle, QgsCoordinateReferenceSystem, QgsProject, QgsMessageLog, Qgis

        try:
            # 新しいマップ設定オブジェクトを作成
            map_settings = QgsMapSettings()

            # 1. レイヤ設定 - QGISデスクトップの表示状態を踏襲
            canvas = self.iface.mapCanvas()
            if canvas:
                # アクティブなレイヤのみを取得（表示状態を踏襲）
                visible_layers = []
                layer_tree_root = QgsProject.instance().layerTreeRoot()

                for layer in canvas.layers():
                    layer_tree_layer = layer_tree_root.findLayer(layer.id())
                    # QgsLayerTreeNode implements __len__ (children count), so a leaf
                    # layer node is falsy — compare with None, not truthiness.
                    if layer_tree_layer is not None and layer_tree_layer.isVisible():
                        visible_layers.append(layer)

                map_settings.setLayers(visible_layers)
                map_settings.setBackgroundColor(canvas.canvasColor())
            else:
                # キャンバスが無い場合はプロジェクトの全レイヤを使用
                from qgis.core import QgsProject
                project = QgsProject.instance()
                map_settings.setLayers(project.mapLayers().values())
                QgsMessageLog.logMessage("⚠️ No canvas, using all project layers", "geo_webview", Qgis.MessageLevel.Warning)

            # 2. 出力サイズ設定
            from qgis.PyQt.QtCore import QSize
            map_settings.setOutputSize(QSize(width, height))

            # 3. 座標系と範囲設定 - WMSパラメータに基づく
            if bbox and crs:
                success = self._configure_wms_extent_and_crs(map_settings, bbox, crs)
                if not success:
                    QgsMessageLog.logMessage("❌ Failed to configure WMS extent/CRS", "geo_webview", Qgis.MessageLevel.Warning)
                    return None
            else:
                # デフォルト範囲設定
                if canvas:
                    map_settings.setDestinationCrs(canvas.mapSettings().destinationCrs())
                    map_settings.setExtent(canvas.extent())
                else:
                    # 世界全体をデフォルトに
                    world_crs = QgsCoordinateReferenceSystem("EPSG:4326")
                    world_extent = QgsRectangle(-180, -90, 180, 90)
                    map_settings.setDestinationCrs(world_crs)
                    map_settings.setExtent(world_extent)

            # 4. 品質設定
            map_settings.setFlag(QgsMapSettings.Antialiasing, True)
            map_settings.setFlag(QgsMapSettings.UseAdvancedEffects, True)
            map_settings.setFlag(QgsMapSettings.ForceVectorOutput, False)
            map_settings.setFlag(QgsMapSettings.DrawEditingInfo, False)

            # 5. DPI設定
            map_settings.setOutputDpi(96)

            # 6. 回転（度） - QgsMapSettings には setRotation がある場合に適用
            try:
                # Apply rotation when caller provided a rotation value (including 0.0).
                # This ensures ANGLE=0 and ANGLE!=0 follow the same code path.
                if rotation is not None and hasattr(map_settings, 'setRotation'):
                    map_settings.setRotation(float(rotation))
            except Exception:  # nosec B110  # 設計上の許容
                pass

            return map_settings

        except Exception as e:
            QgsMessageLog.logMessage(f"❌ Error creating WMS map settings: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            return None

    def _configure_wms_extent_and_crs(self, map_settings, bbox, crs):
        """WMSパラメータに基づいて範囲と座標系を設定"""
        from qgis.core import QgsRectangle, QgsCoordinateReferenceSystem, QgsMessageLog, Qgis

        try:
            # BBOXの解析 (minx,miny,maxx,maxy)
            coords = [float(x) for x in bbox.split(',')]
            if len(coords) != 4:
                QgsMessageLog.logMessage(f"❌ Invalid BBOX format: {bbox}", "geo_webview", Qgis.MessageLevel.Warning)
                return False

            minx, miny, maxx, maxy = coords
            extent = QgsRectangle(minx, miny, maxx, maxy)

            # CRS設定
            target_crs = QgsCoordinateReferenceSystem(crs)
            if not target_crs.isValid():
                QgsMessageLog.logMessage(f"❌ Invalid CRS: {crs}", "geo_webview", Qgis.MessageLevel.Warning)
                return False

            map_settings.setDestinationCrs(target_crs)
            map_settings.setExtent(extent)

            return True

        except ValueError as e:
            QgsMessageLog.logMessage(f"❌ Error parsing BBOX coordinates: {e}", "geo_webview", Qgis.MessageLevel.Warning)
            return False
        except Exception as e:
            QgsMessageLog.logMessage(f"❌ Error configuring WMS extent/CRS: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            return False

    def _execute_map_rendering(self, map_settings):
        """独立したマップレンダラーでPNG画像を生成"""
        from qgis.core import QgsMapRendererParallelJob, QgsMessageLog, Qgis

        try:
            # レンダリング最適化設定
            # キャッシュ有効化とパフォーマンスチューニング
            try:
                # UseRenderingOptimization: レンダリング最適化を有効化
                from qgis.core import QgsMapSettings
                if hasattr(map_settings, 'setFlag'):
                    # UseRenderingOptimization (0x0040) を有効化
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

                # キャッシュヒントを有効化
                if hasattr(map_settings, 'setPathResolver'):
                    # パスリゾルバを設定することでキャッシュが効率化される
                    try:
                        from qgis.core import QgsProject
                        map_settings.setPathResolver(QgsProject.instance().pathResolver())
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
            except Exception:  # nosec B110  # 設計上の許容
                pass

            # 並列レンダリングジョブを作成
            job = QgsMapRendererParallelJob(map_settings)

            # レンダリング実行
            job.start()
            job.waitForFinished()

            # レンダリング結果を取得
            image = job.renderedImage()
            if image.isNull():
                QgsMessageLog.logMessage("❌ Rendered image is null", "geo_webview", Qgis.MessageLevel.Warning)
                return None

            # PNG形式でバイト配列に変換
            from qgis.PyQt.QtCore import QByteArray, QBuffer, QIODevice
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            # QIODevice.OpenModeFlag.WriteOnly may be namespaced differently in Qt6/PyQt6.
            write_mode = getattr(QIODevice, 'WriteOnly', None)
            if write_mode is None:
                om = getattr(QIODevice, 'OpenMode', None) or getattr(QIODevice, 'OpenModeFlag', None)
                if om is not None and hasattr(om, 'WriteOnly'):
                    write_mode = getattr(om, 'WriteOnly')
            if write_mode is None:
                try:
                    write_mode = int(1)
                except Exception:
                    write_mode = 1
            buffer.open(write_mode)

            success = image.save(buffer, "PNG")
            if not success:
                QgsMessageLog.logMessage("❌ Failed to save rendered image as PNG", "geo_webview", Qgis.MessageLevel.Warning)
                return None

            png_data = byte_array.data()
            return png_data

        except Exception as e:
            QgsMessageLog.logMessage(f"❌ Error executing map rendering: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            import traceback
            QgsMessageLog.logMessage(f"❌ Traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
            return None

            # マップレンダリング実行
            from qgis.core import QgsMapRendererParallelJob

            job = QgsMapRendererParallelJob(map_settings)
            job.start()
            job.waitForFinished()

            image = job.renderedImage()
            if image.isNull():
                QgsMessageLog.logMessage("❌ Rendered image is null", "geo_webview", Qgis.MessageLevel.Warning)
                return None

            # PNG形式でバイト配列に変換
            from qgis.PyQt.QtCore import QByteArray, QBuffer, QIODevice
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)

            success = image.save(buffer, "PNG")
            if not success:
                QgsMessageLog.logMessage("❌ Failed to save image as PNG", "geo_webview", Qgis.MessageLevel.Warning)
                return None

            png_data = byte_array.data()
            return png_data

        except Exception as e:
            QgsMessageLog.logMessage(f"❌ Error generating QGIS map PNG: {e}", "geo_webview", Qgis.MessageLevel.Critical)
            import traceback
            QgsMessageLog.logMessage(f"❌ Traceback: {traceback.format_exc()}", "geo_webview", Qgis.MessageLevel.Critical)
            return None

    def _generate_error_image(self, width, height, error_message):
        """エラーメッセージ付きの画像を生成"""
        try:
            from qgis.PyQt.QtGui import QImage, QPainter, QFont, QColor
            from qgis.PyQt.QtCore import Qt, QByteArray, QBuffer, QIODevice

            # 画像を作成
            image = QImage(width, height, QImage.Format.Format_ARGB32)
            image.fill(QColor(240, 240, 240))  # 明るいグレー背景

            # ペインターで描画
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # フォントとペンを設定
            font = QFont("Arial", 12)
            painter.setFont(font)
            painter.setPen(QColor(180, 0, 0))  # 赤色のテキスト

            # エラーメッセージを描画
            rect = image.rect()
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, f"Error:\n{error_message}")

            painter.end()

            # PNG形式でバイト配列に変換
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            # QIODevice.OpenModeFlag.WriteOnly may be namespaced differently in Qt6/PyQt6.
            write_mode = getattr(QIODevice, 'WriteOnly', None)
            if write_mode is None:
                om = getattr(QIODevice, 'OpenMode', None) or getattr(QIODevice, 'OpenModeFlag', None)
                if om is not None and hasattr(om, 'WriteOnly'):
                    write_mode = getattr(om, 'WriteOnly')
            if write_mode is None:
                try:
                    write_mode = int(1)
                except Exception:
                    write_mode = 1
            buffer.open(write_mode)
            image.save(buffer, "PNG")

            return byte_array.data()

        except Exception:
            # 最小限のPNG画像を返す
            return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00\x00\x00\x01\x00\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x16tEXtSoftware\x00www.inkscape.org\x9b\xee<\x1a\x00\x00\x00\x1ftEXtTitle\x00Error Image\x87\x96\xf0\x8e\x00\x00\x00\x12IDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82'

    def _guess_bind_ip(self):
        """サーバの外向きIPv4アドレスを推定して返す（簡易）"""
        try:
            import socket as _socket
            # 外部に到達可能なダミー接続を作って自IPを取得
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            try:
                s.connect(('8.8.8.8', 53))
                ip = s.getsockname()[0]
            except Exception:
                ip = '127.0.0.1'
            finally:
                try:
                    s.close()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            return ip
        except Exception:
            return '127.0.0.1'

    @staticmethod
    def _set_reuse_socketopt(sock):
        """WindowsではSO_EXCLUSIVEADDRUSEでポートの占有を排他化する。

        SO_REUSEADDR はWindowsでは他プロセスによる同一ポートの多重
        バインド(ポート横取り)を許してしまうため、複数QGISインスタンスが
        同居する環境で接続が別プロセスへ分散し無応答になる。
        UnixではSO_REUSEADDR(TIME_WAIT再利用)を維持する。
        """
        try:
            excl = getattr(socket, 'SO_EXCLUSIVEADDRUSE', None)
            if excl is not None:  # Windows
                sock.setsockopt(socket.SOL_SOCKET, excl, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:  # nosec B110  # 設計上の許容
            pass

    def find_available_port(self, start_port, end_port):
        """使用可能なポートを探す

        Args:
            start_port: 開始ポート番号
            end_port: 終了ポート番号

        Returns:
            使用可能なポート番号
        """
        for port in range(start_port, end_port + 1):
            try:
                # test bind on all interfaces
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    self._set_reuse_socketopt(s)
                    s.bind(('0.0.0.0', port))  # nosec B104  # 実bind(上記)と同じIFで空き確認する必要がある
                    return port
            except OSError as e:
                # ポート80, 443は管理者権限が必要な場合がある
                if port in (80, 443):
                    from qgis.core import QgsMessageLog, Qgis
                    QgsMessageLog.logMessage(
                        f"Failed to bind port {port} (administrator rights may be required): {e}",
                        "geo_webview", Qgis.MessageLevel.Warning
                    )
                continue
        raise RuntimeError(f"No available port found in range {start_port}-{end_port}")

    def is_server_running(self):
        """サーバーが稼働中かどうかを確認"""
        return self._http_running and self.http_server is not None

    def get_server_port(self):
        """現在のサーバーポートを取得"""
        return self.server_port if self.is_server_running() else None

    def check_external_access(self):
        """外部からのアクセス可能性を診断

        Returns:
            dict: 診断結果を含む辞書
                {
                    'server_running': bool,
                    'port': int,
                    'local_ip': str,
                    'all_ips': list,
                    'localhost_url': str,
                    'local_network_url': str,
                    'firewall_warning': bool,
                    'message': str
                }
        """
        result = {
            'server_running': False,
            'port': None,
            'local_ip': '127.0.0.1',
            'all_ips': [],
            'localhost_url': '',
            'local_network_url': '',
            'firewall_warning': True,
            'message': ''
        }

        try:
            # サーバー稼働状態チェック
            result['server_running'] = self.is_server_running()
            result['port'] = self.get_server_port()

            if not result['server_running']:
                result['message'] = QCoreApplication.translate('geo_webview', 'The HTTP server is not running')
                return result

            # ローカルIPアドレスを取得
            import socket
            hostname = socket.gethostname()

            # すべてのIPアドレスを取得
            try:
                all_addresses = socket.getaddrinfo(hostname, None)
                ipv4_addresses = []
                for addr in all_addresses:
                    if addr[0] == socket.AF_INET:  # IPv4のみ
                        ip = addr[4][0]
                        if ip not in ipv4_addresses and not ip.startswith('127.'):
                            ipv4_addresses.append(ip)
                result['all_ips'] = ipv4_addresses
            except Exception:  # nosec B110  # 設計上の許容
                pass

            # プライマリローカルIP（外向き）を取得
            result['local_ip'] = self._guess_bind_ip()

            # URLを生成
            result['localhost_url'] = f"http://localhost:{result['port']}"
            if result['local_ip'] != '127.0.0.1':
                result['local_network_url'] = f"http://{result['local_ip']}:{result['port']}"

            # ファイアウォール警告の判定（Windowsの場合）
            allowed_ports = []
            try:
                import platform
                if platform.system() == 'Windows':
                    # Windowsファイアウォールルールの確認を試みる
                    import subprocess  # nosec B404  # 意図的なOSコマンド呼出し
                    try:
                        # netshコマンドでファイアウォールルールを確認
                        import re
                        output = subprocess.run(  # nosec B603 B607
                            ['netsh', 'advfirewall', 'firewall', 'show',
                             'rule', 'name=all'],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        # ルールが見つかれば警告なし
                        if output.returncode == 0 and re.search(
                                r'LocalPort.*{0}'.format(result["port"]),
                                output.stdout, re.IGNORECASE):
                            result['firewall_warning'] = False
                        else:
                            result['firewall_warning'] = True

                        # 許可されているポートを検出（範囲1024-65535で確認）
                        try:
                            allowed_ports = self._scan_firewall_allowed_ports()
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                    except Exception:
                        # コマンド実行失敗時は警告を表示
                        result['firewall_warning'] = True
                else:
                    # Windows以外は警告なし（確認方法が異なるため）
                    result['firewall_warning'] = False
            except Exception:
                result['firewall_warning'] = True

            # メッセージ生成
            messages = []
            messages.append(QCoreApplication.translate('geo_webview', "✅ Server is running on port {0}").format(result['port']))
            messages.append(QCoreApplication.translate('geo_webview', "🏠 Local: {0}").format(result['localhost_url']))

            if result['local_network_url']:
                messages.append(QCoreApplication.translate('geo_webview', "🌐 Network: {0}").format(result['local_network_url']))

            if result['all_ips']:
                messages.append(QCoreApplication.translate('geo_webview', "📡 Available IPs: {0}").format(', '.join(result['all_ips'])))

            if result['firewall_warning']:
                messages.append(QCoreApplication.translate('geo_webview', "\n⚠️ The firewall may be blocking port {0}").format(result['port']))
                messages.append(QCoreApplication.translate('geo_webview', "   To allow external access, permit"))
                messages.append(QCoreApplication.translate('geo_webview', "   port {0} (TCP) in Windows Firewall").format(result['port']))

                # 許可されているポートがあれば表示
                if allowed_ports:
                    messages.append(QCoreApplication.translate('geo_webview', "\n🔓 Ports allowed in the firewall: {0}").format(', '.join(map(str, allowed_ports[:10]))))
                    if len(allowed_ports) > 10:
                        messages.append(QCoreApplication.translate('geo_webview', "   ({0} more)").format(len(allowed_ports) - 10))
                else:
                    messages.append(QCoreApplication.translate('geo_webview', "\n❌ No ports allowed in the firewall were found"))
                    messages.append(QCoreApplication.translate('geo_webview', "   To enable external access, create a new rule"))
                    messages.append(QCoreApplication.translate('geo_webview', "   in Windows Firewall to allow the port"))
            else:
                messages.append(QCoreApplication.translate('geo_webview', "\n✅ A firewall rule is configured"))

            result['message'] = '\n'.join(messages)

        except Exception as e:
            result['message'] = QCoreApplication.translate('geo_webview', 'An error occurred during diagnostics: {0}').format(e)

        return result

    def _scan_firewall_allowed_ports(self):
        """Windowsファイアウォールで許可されているポートをスキャン

        Returns:
            list: 許可されているポート番号のリスト
        """
        allowed_ports = []
        try:
            import subprocess  # nosec B404  # 意図的なOSコマンド呼出し
            import re

            # netshコマンドでファイアウォールルールを取得
            output = subprocess.run(  # nosec B603 B607
                ['netsh', 'advfirewall', 'firewall', 'show',
                 'rule', 'name=all'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if output.returncode == 0:
                lines = output.stdout.split('\n')
                current_rule_enabled = False
                current_rule_action = None

                for line in lines:
                    line_lower = line.lower().strip()

                    # ルールが有効かチェック
                    if 'enabled:' in line_lower:
                        current_rule_enabled = 'yes' in line_lower

                    # アクションがAllowかチェック
                    if 'action:' in line_lower:
                        current_rule_action = 'allow' in line_lower

                    # LocalPortを探す
                    if 'localport:' in line_lower and current_rule_enabled and current_rule_action:
                        # ポート番号を抽出
                        match = re.search(r'localport:\s*(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)', line_lower)
                        if match:
                            port_spec = match.group(1)
                            # カンマ区切りのポートを処理
                            for port_part in port_spec.split(','):
                                if '-' in port_part:
                                    # 範囲の場合（例: 8000-8100）
                                    start, end = port_part.split('-')
                                    try:
                                        start_port = int(start.strip())
                                        end_port = int(end.strip())
                                        # 範囲が広すぎる場合は最初の10個だけ追加
                                        for p in range(start_port, min(end_port + 1, start_port + 10)):
                                            if 1024 <= p <= 65535 and p not in allowed_ports:
                                                allowed_ports.append(p)
                                    except ValueError:  # nosec B110  # 設計上の許容
                                        pass
                                else:
                                    # 単一ポートの場合
                                    try:
                                        port = int(port_part.strip())
                                        if 1024 <= port <= 65535 and port not in allowed_ports:
                                            allowed_ports.append(port)
                                    except ValueError:  # nosec B110  # 設計上の許容
                                        pass

                    # 空行で次のルールに移行
                    if not line.strip():
                        current_rule_enabled = False
                        current_rule_action = None

            # ソートして返す
            allowed_ports.sort()
            return allowed_ports

        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"Firewall port scan error: {e}", "geo_webview", Qgis.MessageLevel.Warning)
            return []

    def add_firewall_rule(self, port, rule_name=None, request_elevation=True):
        """Windowsファイアウォールにポートを許可するルールを追加

        Args:
            port: 許可するポート番号
            rule_name: ルール名(省略時は自動生成)
            request_elevation: 管理者権限昇格を要求するか(デフォルトTrue)

        Returns:
            dict: 結果を含む辞書
                {
                    'success': bool,
                    'message': str,
                    'admin_required': bool,
                    'elevated': bool  # 昇格を試みたか
                }
        """
        result = {
            'success': False,
            'message': '',
            'admin_required': False,
            'elevated': False
        }

        try:
            import platform
            import subprocess  # nosec B404  # 意図的なOSコマンド呼出し

            if platform.system() != 'Windows':
                result['message'] = QCoreApplication.translate('geo_webview', 'This feature is only available on Windows')
                return result

            # ルール名の生成
            if not rule_name:
                rule_name = f"QMapPermalink-Port-{port}"

            # netshコマンドでファイアウォールルールを追加
            cmd = (
                f'netsh advfirewall firewall add rule '
                f'name="{rule_name}" '
                f'dir=in '
                f'action=allow '
                f'protocol=TCP '
                f'localport={port} '
                f'enable=yes'
            )

            try:
                # まず通常権限で試す
                output = subprocess.run(  # nosec B603 B607
                    ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                     'name={0}'.format(rule_name), 'dir=in',
                     'action=allow', 'protocol=TCP',
                     'localport={0}'.format(port), 'enable=yes'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if output.returncode == 0:
                    result['success'] = True
                    result['message'] = QCoreApplication.translate('geo_webview', 'Firewall rule "{0}" has been added').format(rule_name)
                    from qgis.core import QgsMessageLog, Qgis
                    QgsMessageLog.logMessage(result['message'], "geo_webview", Qgis.MessageLevel.Info)
                else:
                    # 通常権限で失敗した場合、管理者権限で再試行
                    if request_elevation:
                        result['elevated'] = True

                        try:
                            # PowerShellの完全パスを取得
                            import os
                            ps_path = os.path.join(os.environ.get('SYSTEMROOT', 'C:\\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')

                            # PowerShellが見つからない場合は代替パスを試す
                            if not os.path.exists(ps_path):
                                ps_path = 'powershell.exe'

                            # netshの完全パスを取得
                            netsh_path = os.path.join(os.environ.get('SYSTEMROOT', 'C:\\Windows'), 'System32', 'netsh.exe')
                            if not os.path.exists(netsh_path):
                                netsh_path = 'netsh.exe'

                            # PowerShellのStart-Processで直接netshを管理者権限で実行
                            # ArgumentListを配列形式で構築
                            args = [
                                'advfirewall',
                                'firewall',
                                'add',
                                'rule',
                                f'name={rule_name}',
                                'dir=in',
                                'action=allow',
                                'protocol=TCP',
                                f'localport={port}',
                                'enable=yes'
                            ]

                            # ArgumentListを文字列として結合
                            args_str = ','.join([f"'{arg}'" for arg in args])

                            # PowerShellコマンドを構築
                            ps_cmd = f'Start-Process -FilePath "{netsh_path}" -ArgumentList {args_str} -Verb RunAs -Wait -WindowStyle Hidden'

                            _ = subprocess.run(  # nosec B603
                                [ps_path, '-NoProfile', '-Command', ps_cmd],
                                capture_output=True,
                                text=True,
                                timeout=60,  # UAC待ち時間を考慮
                                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                            )

                            # 少し待機してからルールを確認
                            import time
                            time.sleep(1)

                            # 結果を確認(成功の場合、元のnetshコマンドをもう一度チェック)
                            verify_output = subprocess.run(  # nosec B603 B607
                                ['netsh', 'advfirewall', 'firewall', 'show',
                                 'rule', 'name={0}'.format(rule_name)],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )

                            if verify_output.returncode == 0 and rule_name in verify_output.stdout:
                                result['success'] = True
                                result['message'] = QCoreApplication.translate('geo_webview', 'Firewall rule "{0}" has been added with administrator rights').format(rule_name)
                                from qgis.core import QgsMessageLog, Qgis
                                QgsMessageLog.logMessage(result['message'], "geo_webview", Qgis.MessageLevel.Info)
                            else:
                                # ユーザーがUACをキャンセルした可能性
                                result['admin_required'] = True
                                result['message'] = QCoreApplication.translate(
                                    'geo_webview', 'Administrator elevation was cancelled or adding the rule failed.\n\nTo run manually, execute the following command in an administrator command prompt:\n\n{0}').format(cmd)
                                result['command'] = cmd
                        except subprocess.TimeoutExpired:
                            result['message'] = QCoreApplication.translate('geo_webview', 'Adding the firewall rule timed out (60 seconds)')
                            result['command'] = cmd
                        except Exception as elev_e:
                            result['message'] = QCoreApplication.translate(
                                'geo_webview', 'Execution with administrator rights failed: {0}\n\nTo run manually, execute the following command in an administrator command prompt:\n\n{1}').format(elev_e, cmd)
                            result['command'] = cmd
                            result['admin_required'] = True
                    else:
                        result['admin_required'] = True
                        result['message'] = QCoreApplication.translate(
                            'geo_webview', 'Administrator rights are required.\n\nExecute the following command in an administrator command prompt:\n\n{0}').format(cmd)
                        result['command'] = cmd
                        from qgis.core import QgsMessageLog, Qgis
                        QgsMessageLog.logMessage(f"Administrator rights required to add firewall rule: {output.stderr}", "geo_webview", Qgis.MessageLevel.Warning)

            except subprocess.TimeoutExpired:
                result['message'] = QCoreApplication.translate('geo_webview', 'Adding the firewall rule timed out')
            except Exception as e:
                if request_elevation:
                    result['message'] = QCoreApplication.translate(
                        'geo_webview', 'Execution with administrator rights failed: {0}\n\nTo run manually, execute the following command in an administrator command prompt:\n\n{1}').format(e, cmd)
                    result['command'] = cmd
                else:
                    result['admin_required'] = True
                    result['message'] = QCoreApplication.translate(
                        'geo_webview', 'Administrator rights are required.\n\nError: {0}\n\nExecute the following command in an administrator command prompt:\n\n{1}').format(e, cmd)
                    result['command'] = cmd

        except Exception as e:
            result['message'] = QCoreApplication.translate('geo_webview', 'Failed to add the firewall rule: {0}').format(e)
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(result['message'], "geo_webview", Qgis.MessageLevel.Critical)

        return result

    def _attach_layer_tree_hooks(self):
        """Best-effort: attach to layer-tree/project signals to detect changes in
        the visible layer composition. Different QGIS versions expose different
        signal names; try a few common ones and connect to a debounced handler.
        """
        try:
            root = QgsProject.instance().layerTreeRoot()
        except Exception:
            return

        # Common root signals to try
        candidate_signals = [
            'nodeChanged', 'childrenChanged', 'visibilityChanged',
            'layerOrderChanged', 'addedChildren', 'removedChildren'
        ]

        hooked = False
        for sname in candidate_signals:
            try:
                sig = getattr(root, sname, None)
                if sig and hasattr(sig, 'connect'):
                    try:
                        sig.connect(self._on_layer_tree_changed)
                        hooked = True
                    except Exception:  # nosec B112  # 設計上の許容
                        continue
            except Exception:  # nosec B112  # 設計上の許容
                continue

        # Fallback: try project-level signals
        if not hooked:
            proj = QgsProject.instance()
            for sname in ('layersAdded', 'layersRemoved', 'layersChanged'):
                try:
                    sig = getattr(proj, sname, None)
                    if sig and hasattr(sig, 'connect'):
                        try:
                            sig.connect(self._on_layer_tree_changed)
                            hooked = True
                        except Exception:  # nosec B112  # 設計上の許容
                            continue
                except Exception:  # nosec B112  # 設計上の許容
                    continue

        try:
            QgsMessageLog.logMessage(f"Layer-tree hooks attached: {hooked}", 'QMapPermalink', Qgis.MessageLevel.Info)
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _on_layer_tree_changed(self, *args, **kwargs):
        """Debounce signal events and schedule handling on a short timer."""
        try:
            # cancel previous timer if any
            if getattr(self, '_layer_change_timer', None):
                try:
                    self._layer_change_timer.cancel()
                except Exception:  # nosec B110  # 設計上の許容
                    pass

            # schedule a short delay to avoid thrashing during bulk operations
            t = threading.Timer(0.5, self._handle_layers_changed)
            t.daemon = True
            self._layer_change_timer = t
            t.start()
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _handle_layers_changed(self):
        """Called after a short debounce delay when layer-tree changes are detected.
        Ensures WMTS identity folder/meta exists for the new composition. Does not
        attempt expensive pre-rendering by default (low-risk)."""
        try:
            if not hasattr(self, 'wmts_service') or self.wmts_service is None:
                return

            try:
                identity_short, identity_raw = self.wmts_service._get_identity_info()
            except Exception:
                return

            if identity_short == getattr(self, '_last_wmts_identity_short', None):
                # nothing changed
                return

            # update last known
            self._last_wmts_identity_short = identity_short
            self._last_wmts_identity_raw = identity_raw

            # Ensure identity folder/meta exists (idempotent, fast)
            try:
                h, d = self.wmts_service.ensure_identity(identity_short, identity_raw)
                QgsMessageLog.logMessage(f"WMTS identity updated/ensured: {identity_short} -> {h}", 'QMapPermalink', Qgis.MessageLevel.Info)
            except Exception as e:
                try:
                    QgsMessageLog.logMessage(f"WMTS ensure_identity failed: {e}", 'QMapPermalink', Qgis.MessageLevel.Warning)
                except Exception:  # nosec B110  # 設計上の許容
                    pass

        except Exception:  # nosec B110  # 設計上の許容
            pass
