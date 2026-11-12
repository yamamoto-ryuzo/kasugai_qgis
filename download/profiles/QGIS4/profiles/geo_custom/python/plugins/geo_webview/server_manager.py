# -*- coding: utf-8 -*-
import socket
import threading
import time
import urllib.parse
import json
import os
import re
import math
import concurrent.futures
from collections import deque
from datetime import datetime
from qgis.PyQt.QtCore import QCoreApplication, QObject, QEvent, pyqtSignal, Qt, QThread
from qgis.core import QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsMessageLog, Qgis, QgsRectangle
from .i18n_json import lang_code, translate_text
# lazy import http_server inside methods to avoid circular import during QGIS plugin init

_PAGE_CTX = 'geo_webview.page'
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# /present 共有ページの表示文字列(英語ソース→カタログ翻訳)。
# html 内の __T_*__ トークンを QGISのUI言語へ翻訳して差し込む
# (未登録言語は英語のまま)。
_PRESENT_STRINGS = {
    '__T_HINT__':
        'drag / wheel / pinch: pan &amp; zoom&ensp;&middot;&ensp;'
        'Alt+Shift+drag / compass: rotate&ensp;&middot;&ensp;Esc / &#8962;: '
        'reset',
    '__T_NAV__':
        'Navigation',
    '__T_RESETNORTH__':
        'Reset rotation to north',
    '__T_ROTATEHINT__':
        'Alt+Shift+drag to rotate',
    '__T_RESETHOME__':
        'Reset to shared view',
    '__T_HOMEHINT__':
        'Back to shared view',
    '__T_INFO__':
        'geo_webview presentation',
    '__T_INDVIEW__':
        ' - independent view',
    '__T_CENTER__':
        'center: ',
    '__T_SCALE__':
        '  scale: 1:',
    '__T_ROT__':
        '  rotation: ',
}


def _localize_page(html):
    """生成HTML内の __T_*__ トークンを現在のUI言語で置換する。"""
    for token, source in _PRESENT_STRINGS.items():
        html = html.replace(
            token, translate_text(_PLUGIN_DIR, _PAGE_CTX, source))
    return html


class _CursorLeaveFilter(QObject):
    """キャンバスからマウスが出たことを検出するイベントフィルタ。

    xyCoordinates はキャンバス上の移動中のみ発火するため、退出検出には
    QEvent.Leave を使う。
    """
    def __init__(self, on_leave):
        super().__init__()
        self._on_leave = on_leave

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.Type.Leave:
                self._on_leave()
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return False


class _MainThreadInvoker(QObject):
    """ワーカースレッドの処理をGUIスレッドへ投げて結果を待つ仲介。

    HTTPハンドラ(スレッドプール)から QgsLayoutManager / QgsLayoutExporter
    等のGUIスレッド依存APIを安全に呼ぶために使う。生成はGUIスレッドで
    行うこと(このQObjectの所属スレッドで slot が実行される)。
    """

    _invoke = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._invoke.connect(
            self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, payload):
        func, done, box = payload
        try:
            box['result'] = func()
        except Exception as e:
            box['error'] = e
        finally:
            done.set()

    def call(self, func, timeout=120):
        """func をGUIスレッドで実行し戻り値を返す。既にGUIスレッドなら直接実行。"""
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() is app.thread():
            return func()
        done = threading.Event()
        box = {}
        self._invoke.emit((func, done, box))
        if not done.wait(timeout):
            raise TimeoutError('GUI thread call timed out')
        if 'error' in box:
            raise box['error']
        return box.get('result')


class GeoWebViewServerManager:
    """geo_webview用HTTPサーバー管理クラス

    内蔵HTTPサーバーの起動・停止・リクエスト処理を担当します。
    提供エンドポイント: /kasugai(.kascエクスポート)、/export-data/、
    /present・/present/state・/screenshot(画面共有)、/received(受領履歴)、
    /layouts・/layout-pdf(印刷レイアウト一覧/PDF出力)、
    /<engine>/(KASUGAI Canvas web/ 静的フォールバック)。
    /qgis-map・旧形式/wms のパーマリンクURLは受領履歴とExternal Control
    ナビゲートのトリガとしてのみ扱います。
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

    def __init__(self, iface, navigation_signals, main_plugin):
        """サーバーマネージャーを初期化

        Args:
            iface: QGISインターフェース
            navigation_signals: ナビゲーション用シグナル
            main_plugin: メインプラグインクラスのインスタンス（共通メソッド呼び出し用）
        """
        self.iface = iface
        self.navigation_signals = navigation_signals
        self.main_plugin = main_plugin

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
        # クライアントから受領したパーマリンク履歴(最新10件)
        # 要素: {'url','client','ua','time'}
        self.received_history = deque(maxlen=10)
        # MACアドレス解決キャッシュ {ip: (set_of_macs, epoch)}
        self._mac_cache = {}
        # 独立レンダラ(QgsMapRendererParallelJob)の同時実行はQGISクラッシュを
        # 引き起こすため直列化する(/screenshot の複製描画で使用)
        self._render_lock = threading.Lock()
        # キャンバス上のマウス最終位置(/present のカーソル誇張表示用)
        self._cursor = None
        try:
            canvas = self.iface.mapCanvas()
            canvas.xyCoordinates.connect(self._on_cursor_xy)
            self._cursor_leave_filter = _CursorLeaveFilter(
                self._clear_cursor)
            canvas.installEventFilter(self._cursor_leave_filter)
            vp = canvas.viewport()
            if vp is not None:
                vp.installEventFilter(self._cursor_leave_filter)
        except Exception:  # nosec B110  # カーソル追跡は付加機能・失敗時は /present のカーソル表示が出ないのみ
            pass
        # KASUGAIエクスポートは同一出力先へ書き込むため同時実行を直列化する
        self._kasugai_lock = threading.Lock()
        # ライブ双方向連携(/live/*)の状態。live_sync が更新し、
        # GET /live/state が Canvas 側へ返す
        self._live = {
            'enabled': False, 'rev': 0, 'updated': None,
            'changed': [], 'camera': None, 'selection': None,
            'writeback': None, 'features': None,
        }
        # 印刷レイアウトPDF出力もレイアウト参照の同時実行を防ぐため直列化する
        self._layout_lock = threading.Lock()
        # HTTPワーカーからGUIスレッドAPIを呼ぶための仲介
        # (このインスタンス生成=GUIスレッド実行が前提)
        self._main_invoker = _MainThreadInvoker()

    def _on_cursor_xy(self, point):
        """キャンバス上のマウス移動(GUIスレッド)。最終位置を保持する。"""
        try:
            self._cursor = {'x': point.x(), 'y': point.y()}
        except Exception:
            self._cursor = None

    def _clear_cursor(self):
        """キャンバスからマウスが出たのでカーソル表示を消す。"""
        self._cursor = None

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
            lan_url = self.get_network_url()
            url_desc = f"http://localhost:{self.server_port}" + (
                f" / {lan_url}" if lan_url else "")
            QgsMessageLog.logMessage(f"🚀 geo_webview v{self.plugin_version} HTTP server started: {url_desc}", "geo_webview", Qgis.MessageLevel.Info)
            self.iface.messageBar().pushMessage(
                "QMap Permalink",
                QCoreApplication.translate("geo_webview", "HTTP server started (port: {0})").format(self.server_port)
                + (f"  {lan_url}" if lan_url else ""),
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
        """HTTPリクエストを解析して各エンドポイントへ振り分ける"""
        # 初期タイムアウト設定（リクエスト読み取り用）
        conn.settimeout(10.0)

        with conn:
            from . import http_server
            request_bytes = http_server.read_http_request(conn)
            if not request_bytes:
                return

            request_text = request_bytes.decode('iso-8859-1', errors='replace')
            self._last_request_text = request_text

            # CORS 許可リスト判定用に Origin ヘッダを記録
            # (http_server 側の応答が ACAO を付けるかの判定に使う)
            _origin = ''
            for _hline in request_text.split('\r\n'):
                if _hline.lower().startswith('origin:'):
                    _origin = _hline.split(':', 1)[1].strip()
                    break
            http_server.set_request_origin(_origin)

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

            # OPTIONS: CORS + Private Network Access プリフライト
            # (ホスト版エンジン https → localhost への fetch 用)
            if method.upper() == 'OPTIONS':
                from . import http_server
                http_server.send_options_response(conn)
                return

            # HEAD はエクスポート用ランチャーHTMLのエンジン自動探索
            # (fetch HEAD で <engine>/index.html を探す)が使うため受け付ける。
            # 静的配信(export-data / Canvas web/)のみを対象とする
            # POST はライブ双方向連携(/live/*)のみ受け付ける
            head_only = method.upper() == 'HEAD'
            _req_path0 = target.split('?', 1)[0].split(' ', 1)[0]
            is_post = method.upper() == 'POST' \
                and _req_path0.startswith('/live/')
            if method.upper() not in ('GET', 'HEAD') and not is_post:
                from . import http_server
                http_server.send_http_response(conn, 405, "Method Not Allowed", "Only GET, HEAD, POST(/live/*) and OPTIONS are supported.")
                return
            # POST ボディ(JSON)。ヘッダ終端以降がボディ
            req_body = b''
            if is_post and b'\r\n\r\n' in request_bytes:
                req_body = request_bytes.partition(b'\r\n\r\n')[2]

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
            # パラメータ名は大小区別なしで受け付ける(小写で送る
            # クライアント対応のため大写エイリアスを補完)。既存キーは上書きしない
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

            # HEAD は静的配信のみ応答する(エンジン自動探索プローブ用)
            if head_only:
                try:
                    served = False
                    if parsed_url.path.startswith('/export-data/'):
                        served = True
                        self._handle_export_data(
                            conn, parsed_url.path[len('/export-data/'):],
                            head_only=True)
                    else:
                        served = self._handle_canvas_web(
                            conn, parsed_url.path, head_only=True)
                    if not served:
                        from . import http_server
                        http_server.send_http_response(
                            conn, 404, 'Not Found', 'not found',
                            'text/plain; charset=utf-8')
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'❌ HEAD handler error: {e}',
                        'geo_webview', Qgis.MessageLevel.Warning)
                return

            # ブラウザ/外部クライアントからパーマリンクURL（/qgis-map、
            # 旧形式の /wms パーマリンクも互換のため含む）を受け取ったときだけ
            # パネルのナビゲート欄に表示するためにemitする。
            # ただしパネル側から生成した自前のページ遷移(internal=1付与)は
            # ナビゲート欄の上書き・受領履歴の対象外とする。
            try:
                is_internal = 'internal' in params
                if parsed_url.path in ('/qgis-map', '/wms'):
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

            # --- ライブ双方向連携(Canvas ↔ QGIS) ---
            # GET /live/state : 連携状態+現在のキャンバス状態(JSON)
            # live.qgis_selection は live_sync 側の選択監視が随時更新する
            if parsed_url.path == '/live/state' and not is_post:
                try:
                    payload = json.dumps(
                        {'ok': True, 'live': self._live,
                         'canvas': self._canvas_state_dict()},
                        ensure_ascii=False)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK', payload,
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/state failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # GET /live/mcp-discover : QGIS Live Driver セッションの検出。
            # AIチャット(CDNホスト版含む)がMCP接続先URLを得るためのもので、
            # トークン自体は返さない(POST /live/mcp がサーバ側で付与する)。
            if parsed_url.path == '/live/mcp-discover' and not is_post:
                try:
                    from . import live_mcp
                    port = self.get_server_port() or self.server_port
                    payload = json.dumps(
                        live_mcp.discover_payload(port), ensure_ascii=False)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK', payload,
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/mcp-discover failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # POST /live/mcp : Live Driver /mcp へのリレー。
            # qgis_pyeval 等の任意コード実行が乗るため TCP ピアが
            # loopback の接続のみ許可する(他の /live/* より露出が大きい)。
            if parsed_url.path == '/live/mcp' and is_post:
                try:
                    from . import live_mcp
                    if not live_mcp.is_loopback_peer(addr[0] if addr else ''):
                        from . import http_server
                        http_server.send_http_response(
                            conn, 403, 'Forbidden',
                            'live/mcp is loopback only',
                            'text/plain; charset=utf-8')
                        return
                    status, body, ctype, sid = live_mcp.relay(
                        req_body,
                        content_type=live_mcp.request_header(
                            request_text, 'Content-Type'),
                        accept=live_mcp.request_header(
                            request_text, 'Accept'),
                        session_id=live_mcp.request_header(
                            request_text, 'Mcp-Session-Id'),
                        protocol_version=live_mcp.request_header(
                            request_text, 'MCP-Protocol-Version'))
                    from . import http_server
                    import http.client
                    extra = ['Mcp-Session-Id: {0}'.format(sid)] if sid else None
                    http_server.send_binary_response(
                        conn, status,
                        http.client.responses.get(status, 'OK'),
                        body, ctype, extra_headers=extra)
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/mcp failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # POST /live/camera : Canvas の視点を QGIS キャンバスへ反映
            # body: {longitude,latitude,height|zoom|scale,heading?} または
            #       {bbox:[w,s,e,n]}(EPSG:4326)
            if parsed_url.path == '/live/camera' and is_post:
                try:
                    payload = json.loads(
                        req_body.decode('utf-8') or '{}')
                    applied = self._main_invoker.call(
                        lambda: self._apply_live_camera(payload),
                        timeout=30)
                    self._live['camera'] = {
                        'received': payload,
                        'time': datetime.now().isoformat(timespec='seconds')}
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK',
                        json.dumps({'ok': True, 'applied': applied},
                                   ensure_ascii=False),
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/camera failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # POST /live/selection : Canvas の地物選択を QGIS の選択へ反映
            # body: {layer:"<kasc title>", ids:[fid...]} または
            #       {layer:"<title>", longitude,latitude,buffer_m?} または
            #       {layer:"<title>", bbox:[w,s,e,n]}
            if parsed_url.path == '/live/selection' and is_post:
                try:
                    payload = json.loads(
                        req_body.decode('utf-8') or '{}')
                    applied = self._main_invoker.call(
                        lambda: self._apply_live_selection(payload),
                        timeout=30)
                    self._live['selection'] = {
                        'received': payload, 'applied': applied,
                        'time': datetime.now().isoformat(timespec='seconds')}
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK',
                        json.dumps({'ok': True, **applied},
                                   ensure_ascii=False),
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/selection failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # POST /live/writeback : Canvas の表示/フィルタ/テーマ変更を
            # QGIS プロジェクトへ書き戻す(.kasc → QGIS 逆方向)
            # body: {layers:[{title,visible,where?}], theme?:"<テーマ名>"}
            if parsed_url.path == '/live/writeback' and is_post:
                try:
                    payload = json.loads(
                        req_body.decode('utf-8') or '{}')
                    applied = self._main_invoker.call(
                        lambda: self._apply_live_writeback(payload),
                        timeout=60)
                    self._live['writeback'] = {
                        'received': payload, 'applied': applied,
                        'time': datetime.now().isoformat(timespec='seconds')}
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK',
                        json.dumps({'ok': True, **applied},
                                   ensure_ascii=False),
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/writeback failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # POST /live/features : Canvas の作図/GeoJSON を
            # スクラッチレイヤとしてプロジェクトへ投入
            # body: {name, geojson: FeatureCollection|Feature[],
            #        replace?:bool(既定true)}
            if parsed_url.path == '/live/features' and is_post:
                try:
                    payload = json.loads(
                        req_body.decode('utf-8') or '{}')
                    applied = self._main_invoker.call(
                        lambda: self._apply_live_features(payload),
                        timeout=120)
                    self._live['features'] = {
                        'name': payload.get('name'),
                        'applied': applied,
                        'time': datetime.now().isoformat(timespec='seconds')}
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK',
                        json.dumps({'ok': True, **applied},
                                   ensure_ascii=False),
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/features failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # GET /live/layers : プロジェクトのレイヤーカタログ
            # (kasc タイトル付き。Canvas の「QGISからレイヤ追加」用)
            if parsed_url.path == '/live/layers' and not is_post:
                try:
                    catalog = self._main_invoker.call(
                        self._live_layer_catalog, timeout=60)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK',
                        json.dumps({'ok': True, **catalog},
                                   ensure_ascii=False),
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/layers failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # GET /live/features : オンデマンド地物配信(GeoJSON)
            # ?layer=<kasc title>&bbox=w,s,e,n(EPSG:4326)&limit=&offset=
            # または pt=lon,lat&tol=<レイヤCRS単位> で地点検索
            if parsed_url.path == '/live/features' and not is_post:
                try:
                    data = self._main_invoker.call(
                        lambda: self._live_features_query(params),
                        timeout=120)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK',
                        json.dumps(data, ensure_ascii=False),
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/features query failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # GET /live/selection : QGIS 側の選択地物を GeoJSON で返す
            # (Canvas 側ハイライト表示用。&max= で地物数上限、既定500)
            if parsed_url.path == '/live/selection' and not is_post:
                try:
                    max_feat = self._safe_int(
                        params.get('max', ['500'])[0], 500)
                    data = self._main_invoker.call(
                        lambda: self._live_selection_dump(max_feat),
                        timeout=60)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 200, 'OK',
                        json.dumps({'ok': True, **data},
                                   ensure_ascii=False),
                        'application/json; charset=utf-8')
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/selection failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # GET /live/render : 4326 bbox 指定のマップ描画PNG
            # (Canvas 側「QGIS描画」フォールバックオーバーレイ用)
            # ?bbox=w,s,e,n(EPSG:4326)&w=&h=&layers=<kasc titles>&bg=transparent
            if parsed_url.path == '/live/render' and not is_post:
                try:
                    self._handle_live_render(conn, params)
                except Exception as e:
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'live/render failed: {e}',
                        'text/plain; charset=utf-8')
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
            # (?engine=cesium|maplibre|openlayers|leaflet|gsimaps|navara
            #  で起動エンジン指定可)
            if parsed_url.path == '/kasugai':
                try:
                    self._handle_kasugai(conn, params)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'❌ kasugai handler error: {e}',
                        'geo_webview', Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'kasugai failed: {e}', 'text/plain; charset=utf-8')
                return

            # 印刷レイアウト一覧(JSON)。KASUGAI Canvas 印刷ダイアログの
            # 「QGISレイアウトでPDF出力」が参照する
            if parsed_url.path == '/layouts':
                try:
                    self._handle_layouts(conn)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'❌ layouts handler error: {e}',
                        'geo_webview', Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'layouts failed: {e}', 'text/plain; charset=utf-8')
                return

            # 印刷レイアウトのPDF出力。?layout=<name> 省略時は先頭のレイアウト
            if parsed_url.path == '/layout-pdf':
                try:
                    self._handle_layout_pdf(conn, params)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'❌ layout-pdf handler error: {e}',
                        'geo_webview', Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error',
                        f'layout-pdf failed: {e}',
                        'text/plain; charset=utf-8')
                return

            # /export-data/<rel>: KASUGAI/Re:Earth エクスポート産物(out_dir配下)の配信
            if parsed_url.path.startswith('/export-data/'):
                try:
                    self._handle_export_data(
                        conn, parsed_url.path[len('/export-data/'):])
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'❌ export-data error: {e}',
                        'geo_webview', Qgis.MessageLevel.Critical)
                    from . import http_server
                    http_server.send_http_response(
                        conn, 500, 'Internal Server Error', str(e),
                        'text/plain; charset=utf-8')
                return

            # --- 静的ファイル配信: favicon.ico + /vendor/(同梱JSライブラリ) ---
            import os
            static_files = ["/favicon.ico"]
            if (parsed_url.path in static_files
                    or parsed_url.path.startswith('/vendor/')):
                plugin_dir = os.path.dirname(os.path.abspath(__file__))
                fname = parsed_url.path.lstrip("/")
                fpath = os.path.normpath(os.path.join(plugin_dir, fname))
                if (os.path.isfile(fpath)
                        and fpath.startswith(os.path.normpath(plugin_dir))):
                    content_type = self._static_content_type(fpath)
                    with open(fpath, "rb") as f:
                        data = f.read()
                    http_server.send_binary_response(conn, 200, "OK", data, content_type)
                    return
                http_server.send_http_response(conn, 404, "Not Found", f"File not found: {fname}", "text/plain; charset=utf-8")
                return

            # --- KASUGAI Canvas web/ 静的配信(フォールバック) ---
            # Canvas サーバ(8510)未起動時に、インストール済みCanvasの
            # エンジンHTMLをこのサーバが代わりに配信する。全エンドポイントに
            # 一致しなかったパスのみ web/ 配下へ解決する
            try:
                if self._handle_canvas_web(conn, parsed_url.path):
                    return
            except Exception as e:
                QgsMessageLog.logMessage(
                    f'❌ canvas web handler error: {e}',
                    'geo_webview', Qgis.MessageLevel.Critical)

            # 未対応のエンドポイントは404エラー
            QgsMessageLog.logMessage(f"❌ Unknown endpoint: {parsed_url.path}", "geo_webview", Qgis.MessageLevel.Warning)
            from . import http_server
            http_server.send_http_response(
                conn,
                404,
                "Not Found",
                "Available endpoints: /present (shared canvas view), /present/state (canvas JSON), /screenshot (canvas PNG), /received (permalink history), /kasugai (KASUGAI Canvas export), /layouts (print layout list), /layout-pdf (print layout PDF), /export-data/<rel> (export files), /<engine>/ (KASUGAI Canvas web static fallback)"
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
        mupp = 0.0
        cw = ch = 0
        try:
            mupp = float(ms.mapUnitsPerPixel())
            cw = int(canvas.width())
            ch = int(canvas.height())
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return {
            'x': c.x(), 'y': c.y(), 'scale': scale, 'crs': crs_auth,
            'rotation': rotation, 'zoom': zoom,
            'lon': lon, 'lat': lat, 'x3857': x3857, 'y3857': y3857,
            'mupp': mupp, 'width': cw, 'height': ch,
            'cursor': self._cursor,
            'time': datetime.now().isoformat(timespec='seconds'),
        }

    # ---------- ライブ双方向連携 ----------

    def live_update(self, changed=None, enabled=None):
        """live_sync からの更新を記録する。/live/state と push 通知に使う。

        changed: [{'title': str, 'kind': 'data'|'style'|'full'}...] または None
        """
        st = self._live
        st['rev'] = int(time.time() * 1000)
        st['updated'] = datetime.now().isoformat(timespec='seconds')
        if changed is not None:
            st['changed'] = list(changed)
        if enabled is not None:
            st['enabled'] = bool(enabled)
        return st['rev']

    def live_notify_qgis_selection(self, payload):
        """live_sync の選択監視から QGIS 側選択状態を受け取り記録する。

        payload: {'layers': [{'layer':<kasc title>,'ids':[fid...],
        'count':N}], 'rev':<epoch ms>}。GET /live/state の
        live.qgis_selection として Canvas へ公開される
        (Canvas 側は rev 変化でハイライトを再描画する)。
        """
        self._live['qgis_selection'] = dict(payload or {})

    def _apply_live_camera(self, payload):
        """Canvas 側のカメラ(JSON)を QGIS キャンバスへ反映する(GUIスレッド)。

        payload: {longitude,latitude,zoom|scale|height,heading?}
                  または {bbox:[w,s,e,n]}(EPSG:4326)。
        """
        canvas = self.iface.mapCanvas()
        dest = canvas.mapSettings().destinationCrs()
        src = QgsCoordinateReferenceSystem('EPSG:4326')
        project = QgsProject.instance()
        applied = {}
        bbox = payload.get('bbox')
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            rect = QgsRectangle(*[float(v) for v in bbox])
            if src != dest:
                rect = QgsCoordinateTransform(
                    src, dest, project).transformBoundingBox(rect)
            canvas.setExtent(rect)
            applied['extent'] = True
        else:
            lon = payload.get('longitude', payload.get('lon'))
            lat = payload.get('latitude', payload.get('lat'))
            if lon is not None and lat is not None:
                pt = QgsPointXY(float(lon), float(lat))
                if src != dest:
                    pt = QgsCoordinateTransform(
                        src, dest, project).transform(pt)
                canvas.setCenter(pt)
                applied['center'] = [pt.x(), pt.y()]
            scale = payload.get('scale')
            if scale is None and payload.get('zoom') is not None:
                try:
                    from .scale_zoom import estimate_scale_from_zoom
                    scale = estimate_scale_from_zoom(payload.get('zoom'))
                except Exception:  # nosec B110  # 設計上の許容
                    scale = None
            if scale is None and payload.get('height') is not None:
                # Cesium カメラ高さ(m) → 概算縮尺(垂直FOV60°・0.28mm/px)
                try:
                    h = float(payload.get('height'))
                    if h > 0:
                        scale = h / (0.00028 * 2 * 0.5773502691896257)
                except Exception:  # nosec B110  # 設計上の許容
                    scale = None
            if scale:
                canvas.zoomScale(float(scale))
                applied['scale'] = float(scale)
        heading = payload.get('heading', payload.get('rotation'))
        if heading is not None:
            try:
                canvas.setRotation(float(heading))
                applied['rotation'] = float(heading)
            except Exception:  # nosec B110  # 設計上の許容
                pass
        canvas.refresh()
        return applied

    def _apply_live_selection(self, payload):
        """Canvas 側の選択(JSON)を QGIS のレイヤ選択へ反映する(GUIスレッド)。

        payload: {layer:"<kasc title>", ids:[fid...]}
                 | {layer, longitude,latitude,buffer_m?}
                 | {layer, bbox:[w,s,e,n]}
        """
        from qgis.core import QgsVectorLayer
        project = QgsProject.instance()
        title = str(payload.get('layer') or payload.get('title') or '').strip()
        layer = self._resolve_kasc_layer(title) if title else None
        if layer is None:
            layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            return {'selected': 0,
                    'layer': layer.name() if layer is not None else None}
        selected = 0
        ids = payload.get('ids')
        if isinstance(ids, (list, tuple)) and ids:
            try:
                layer.selectByIds([int(i) for i in ids])
                selected = layer.selectedFeatureCount()
            except Exception:  # nosec B110  # 設計上の許容
                selected = 0
        if not selected:
            rect4326 = None
            bbox = payload.get('bbox')
            lon = payload.get('longitude', payload.get('lon'))
            lat = payload.get('latitude', payload.get('lat'))
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                rect4326 = QgsRectangle(*[float(v) for v in bbox])
            elif lon is not None and lat is not None:
                try:
                    buf = float(payload.get('buffer_m')
                                or payload.get('buffer') or 5.0)
                except Exception:  # nosec B110  # 設計上の許容
                    buf = 5.0
                d = buf / 111320.0
                rect4326 = QgsRectangle(
                    float(lon) - d, float(lat) - d,
                    float(lon) + d, float(lat) + d)
            if rect4326 is not None:
                src = QgsCoordinateReferenceSystem('EPSG:4326')
                rect = rect4326
                if layer.crs() != src:
                    rect = QgsCoordinateTransform(
                        src, layer.crs(), project).transformBoundingBox(
                            rect4326)
                layer.selectByRect(rect)
                selected = layer.selectedFeatureCount()
        if selected:
            layer.triggerRepaint()
        return {'selected': int(selected), 'layer': layer.name()}

    def _resolve_kasc_layer(self, title):
        """kasc タイトル(「グループ/葉」フルパスまたは葉名)から
        QgsMapLayer を解決する。見つからなければ None。"""
        project = QgsProject.instance()
        title = str(title or '').strip()
        if not title:
            return None
        leaf = title.split('/')[-1].strip()
        try:
            from . import kasugai_export
            tree = kasugai_export._tree_layers()

            def norm(s):
                return '/'.join(p.strip() for p in str(s).split('/'))
            want = norm(title)
            cand = [lyr for lyr, groups, _v, _tn in tree
                    if norm(kasugai_export._kasc_layer_title(
                        groups, lyr.name())) == want]
            if not cand:
                cand = [lyr for lyr in project.mapLayers().values()
                        if lyr.name() == leaf or lyr.name() == title]
            return cand[0] if cand else None
        except Exception:  # nosec B110  # 設計上の許容
            return None

    def _apply_live_writeback(self, payload):
        """Canvas 側の表示/フィルタ/テーマ状態を QGIS プロジェクトへ
        書き戻す(GUIスレッド)。.kasc → QGIS の逆方向オーサリング。

        payload: {layers:[{title,visible,where?}], theme?:"<テーマ名>"}
          - title  : kasc タイトル(「グループ/葉」フルパスまたは葉名)
          - visible: レイヤツリーのチェック状態。True のとき祖先
                     グループも ON にして実効表示を確実にする
          - where  : ベクターレイヤのプロバイダフィルタ(subsetString)。
                     キーがある場合のみ適用(空文字=フィルタ解除)
          - theme  : 同名のマップテーマがあれば適用(可視性+記録済み
                     スタイルの一括反映)。無ければ layers 側の
                     per-layer visible がそのまま効く
        """
        from contextlib import nullcontext
        from qgis.core import QgsVectorLayer, QgsLayerTreeModel
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        applied = {'visibility': 0, 'filter': 0, 'theme': None,
                   'missing': []}
        ctl = getattr(self.main_plugin, '_live_sync', None)
        ctx = ctl.suppress() if ctl is not None else nullcontext()
        with ctx:
            theme = str(payload.get('theme') or '').strip()
            if theme:
                try:
                    coll = project.mapThemeCollection()
                    if theme in coll.mapThemes():
                        try:
                            model = self.iface.layerTreeView() \
                                .layerTreeModel()
                        except Exception:  # nosec B110  # 設計上の許容
                            model = QgsLayerTreeModel(root)
                        coll.applyTheme(theme, root, model)
                        applied['theme'] = theme
                except Exception:  # nosec B110  # 設計上の許容
                    applied['theme'] = None
            for ent in payload.get('layers') or []:
                if not isinstance(ent, dict):
                    continue
                title = str(ent.get('title') or '').strip()
                layer = self._resolve_kasc_layer(title)
                if layer is None:
                    if title:
                        applied['missing'].append(title)
                    continue
                if ent.get('visible') is not None:
                    node = root.findLayer(layer.id())
                    if node is not None:
                        node.setItemVisibilityChecked(
                            bool(ent.get('visible')))
                        if ent.get('visible'):
                            parent = node.parent()
                            while (parent is not None
                                   and parent != root):
                                parent.setItemVisibilityChecked(True)
                                parent = parent.parent()
                        applied['visibility'] += 1
                # where= はフィルタのキー。filter= もエイリアスとして受け付ける
                if ('where' in ent or 'filter' in ent) \
                        and isinstance(layer, QgsVectorLayer):
                    try:
                        layer.setSubsetString(
                            str(ent.get('where', ent.get('filter')) or ''))
                        applied['filter'] += 1
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
        try:
            self.iface.mapCanvas().refresh()
        except Exception:  # nosec B110  # 設計上の許容
            pass
        QgsMessageLog.logMessage(
            'live writeback applied: vis={0} filter={1} theme={2}'.format(
                applied['visibility'], applied['filter'],
                applied['theme']),
            'geo_webview', Qgis.MessageLevel.Info)
        return applied

    def _apply_live_features(self, payload):
        """Canvas からの GeoJSON をスクラッチ(memory)レイヤとして
        プロジェクトへ投入する(GUIスレッド)。

        payload: {name, geojson: FeatureCollection|Feature[],
                  replace?:bool(既定True)}
          - 同名(kasugai_live_name カスタムプロパティ一致)の既存
            レイヤは replace 時に除去して作り直す(同じ作図レイヤの
            再送=差し替え運用)
          - ジオメトリ型混在の FeatureCollection は型ごとに分割
          - 追加先はレイヤツリー先頭の「Canvas」グループ
          - 追加は live_sync 抑止しない: QGIS側へ投入された地物は
            通常の変更として差分エクスポート→Canvas へ往復する
        """
        from qgis.core import (QgsVectorLayer, QgsJsonUtils,
                               QgsLayerTreeLayer)
        name = str(payload.get('name') or 'Canvas').strip() or 'Canvas'
        fc = payload.get('geojson')
        if isinstance(fc, dict):
            feats_in = fc.get('features') or []
        elif isinstance(fc, list):
            feats_in = fc
        else:
            feats_in = []
        feats_in = [f for f in feats_in
                    if isinstance(f, dict)
                    and isinstance(f.get('geometry'), dict)]
        if not feats_in:
            return {'added': 0, 'layers': []}
        replace = payload.get('replace', True)
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        if replace:
            for lyr in list(project.mapLayers().values()):
                try:
                    if lyr.customProperty('kasugai_live_name') == name:
                        project.removeMapLayer(lyr.id())
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        _TYPE_WKB = {
            'Point': 'Point', 'MultiPoint': 'MultiPoint',
            'LineString': 'LineString',
            'MultiLineString': 'MultiLineString',
            'Polygon': 'Polygon', 'MultiPolygon': 'MultiPolygon',
        }
        by_geom = {}
        for f in feats_in:
            wkb = _TYPE_WKB.get(
                str(f['geometry'].get('type') or ''))
            if wkb:
                by_geom.setdefault(wkb, []).append(f)
        group_node = root.findGroup('Canvas')
        if group_node is None:
            group_node = root.insertGroup(0, 'Canvas')
        created = []
        multi = len(by_geom) > 1
        for wkb, flist in by_geom.items():
            layer_name = (name if not multi
                          else '{0}({1})'.format(name, wkb))
            layer = QgsVectorLayer(
                '{0}?crs=epsg:4326'.format(wkb), layer_name, 'memory')
            if not layer.isValid():
                continue
            fc_json = json.dumps(
                {'type': 'FeatureCollection', 'features': flist},
                ensure_ascii=False)
            try:
                fields = QgsJsonUtils.stringToFields(fc_json)
                if fields.isValid() and fields.count():
                    layer.dataProvider().addAttributes(fields.toList())
                    layer.updateFields()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            qfeats = []
            for f in flist:
                try:
                    parsed = QgsJsonUtils.stringToFeatureList(
                        json.dumps(
                            {'type': 'FeatureCollection',
                             'features': [f]},
                            ensure_ascii=False))
                except Exception:  # nosec B110  # 設計上の許容
                    parsed = []
                for qf in parsed:
                    try:
                        qf.setFields(layer.fields(), True)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                    qfeats.append(qf)
            if qfeats:
                layer.dataProvider().addFeatures(qfeats)
            layer.updateExtents()
            layer.setCustomProperty('kasugai_live_name', name)
            project.addMapLayer(layer, False)
            group_node.insertChildNode(0, QgsLayerTreeLayer(layer))
            created.append({'name': layer_name,
                            'features': len(qfeats),
                            'geometry': wkb})
        try:
            self.iface.mapCanvas().refresh()
        except Exception:  # nosec B110  # 設計上の許容
            pass
        added = sum(c['features'] for c in created)
        QgsMessageLog.logMessage(
            'live features added: {0} feature(s) as {1} layer(s) '
            '(name={2})'.format(added, len(created), name),
            'geo_webview', Qgis.MessageLevel.Info)
        return {'added': added, 'layers': created}

    # ---- GET /live/* オンデマンド配信 ----

    def _kasc_title_map(self):
        """layer.id() → kasc タイトルの写像を作る(重い tree 走査を1回で)。"""
        try:
            from . import kasugai_export
            return {lyr.id(): kasugai_export._kasc_layer_title(
                groups, lyr.name())
                for lyr, groups, _v, _tn in kasugai_export._tree_layers()}
        except Exception:  # nosec B110  # 設計上の許容
            return {}

    def _live_layer_catalog(self):
        """GET /live/layers 用: レイヤツリー全レイヤのカタログ(GUIスレッド)。

        kasc タイトル(「グループ/葉」)をキーに、型・地物数・4326範囲・
        フィルタ有無を返す。Canvas の「QGISからレイヤ追加」UIが使う。
        """
        from qgis.core import QgsVectorLayer, QgsRasterLayer
        project = QgsProject.instance()
        titles = self._kasc_title_map()
        out = []
        for lid, layer in project.mapLayers().items():
            try:
                title = titles.get(lid) or layer.name()
                if isinstance(layer, QgsVectorLayer):
                    entry = {
                        'title': title, 'id': lid, 'type': 'vector',
                        'geometry': {
                            0: 'point', 1: 'line', 2: 'polygon',
                        }.get(layer.geometryType(), 'none'),
                        'count': int(layer.featureCount()),
                        'hasFilter': bool(layer.subsetString()),
                        'crs': layer.crs().authid(),
                    }
                    try:
                        ext = layer.extent()
                        src = layer.crs()
                        if (src.isValid() and ext.isFinite()
                                and not ext.isEmpty()):
                            if src.authid() != 'EPSG:4326':
                                ext = QgsCoordinateTransform(
                                    src, QgsCoordinateReferenceSystem(
                                        'EPSG:4326'),
                                    project).transformBoundingBox(ext)
                            entry['extent'] = [
                                ext.xMinimum(), ext.yMinimum(),
                                ext.xMaximum(), ext.yMaximum()]
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                elif isinstance(layer, QgsRasterLayer):
                    entry = {'title': title, 'id': lid,
                             'type': 'raster', 'crs': layer.crs().authid()}
                else:
                    entry = {'title': title, 'id': lid, 'type': 'other'}
                out.append(entry)
            except Exception:  # nosec B112  # 設計上の許容
                continue
        return {'layers': out}

    def _rect4326_to_layer(self, rect, layer):
        """EPSG:4326 の QgsRectangle を layer のCRSへ変換する。"""
        src = QgsCoordinateReferenceSystem('EPSG:4326')
        dest = layer.crs()
        if not src.isValid() or not dest.isValid() or src == dest:
            return rect
        return QgsCoordinateTransform(
            src, dest, QgsProject.instance()).transformBoundingBox(rect)

    def _live_features_query(self, params):
        """GET /live/features 用(GUIスレッド): レイヤの地物を GeoJSON で返す。

        範囲(bbox)・地点(pt+tol)・上限/オフセットをサポートし、
        displayExpression は _display プロパティとして埋め込む。
        """
        from qgis.core import (QgsVectorLayer, QgsFeatureRequest,
                               QgsJsonExporter, QgsExpression,
                               QgsExpressionContext,
                               QgsExpressionContextUtils)
        title = str(params.get('layer', [''])[0] or '').strip()
        layer = self._resolve_kasc_layer(title) if title else None
        if layer is None:
            return {'ok': False, 'error': 'layer not found: {0}'.format(
                title)}
        if not isinstance(layer, QgsVectorLayer):
            return {'ok': False, 'error': 'not a vector layer: {0}'.format(
                title)}
        req = QgsFeatureRequest()
        bbox = self._parse_floats(params.get('bbox', [None])[0], 4)
        pt = self._parse_floats(params.get('pt', [None])[0], 2)
        if bbox is not None and bbox[2] > bbox[0] and bbox[3] > bbox[1]:
            req.setFilterRect(
                self._rect4326_to_layer(QgsRectangle(*bbox), layer))
        elif pt is not None:
            tol = self._parse_floats(params.get('tol', [None])[0], 1)
            tol = tol[0] if tol else 0.0
            p = QgsPointXY(pt[0], pt[1])
            p = self._rect4326_to_layer(
                QgsRectangle(p.x(), p.y(), p.x(), p.y()), layer).center()
            if tol <= 0:
                # 既定トレランス: レイヤ範囲の 0.1% (タップ判定程度)
                ext = layer.extent()
                tol = max(ext.width(), ext.height()) * 0.001
                if tol <= 0:
                    tol = 1e-5
            req.setFilterRect(QgsRectangle(
                p.x() - tol, p.y() - tol, p.x() + tol, p.y() + tol))
        limit = self._safe_int(params.get('limit', ['2000'])[0], 2000)
        limit = max(1, min(20000, limit or 2000))
        offset = max(0, self._safe_int(
            params.get('offset', ['0'])[0], 0))
        exporter = QgsJsonExporter(layer)
        disp = ''
        try:
            disp = str(layer.displayExpression() or '')
        except Exception:  # nosec B110  # 設計上の許容
            disp = ''
        expr = ctx = None
        if disp:
            try:
                expr = QgsExpression(disp)
                ctx = QgsExpressionContext()
                ctx.appendScopes(
                    QgsExpressionContextUtils
                    .globalProjectLayerScopes(layer))
            except Exception:  # nosec B110  # 設計上の許容
                expr = ctx = None
        features = []
        seen = 0
        truncated = False
        for f in layer.getFeatures(req):
            if seen < offset:
                seen += 1
                continue
            if len(features) >= limit:
                truncated = True
                break
            seen += 1
            try:
                feat = json.loads(exporter.exportFeature(f))
            except Exception:  # nosec B112  # 設計上の許容
                continue
            if expr is not None and ctx is not None:
                try:
                    ctx.setFeature(f)
                    feat.setdefault('properties', {})[
                        '_display'] = expr.evaluate(ctx)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            features.append(feat)
        return {'ok': True, 'layer': title,
                'count': len(features), 'truncated': truncated,
                'geojson': {'type': 'FeatureCollection',
                            'features': features}}

    def _selection_signature(self):
        """QGIS 側選択状態の署名(GUIスレッド)。

        [layer_id, count, first_id, last_id] のリストを返し、
        Canvas 側が変更検出してから GET /live/selection を呼ぶ
        判定材料にする(地物数・先端IDの軽量比較)。
        """
        from qgis.core import QgsVectorLayer
        sig = []
        try:
            for lid, layer in QgsProject.instance().mapLayers().items():
                try:
                    if not isinstance(layer, QgsVectorLayer):
                        continue
                    cnt = int(layer.selectedFeatureCount())
                    if not cnt:
                        continue
                    ids = list(layer.selectedFeatureIds())
                    sig.append([lid, cnt,
                                ids[0] if ids else -1,
                                ids[-1] if ids else -1])
                except Exception:  # nosec B112  # 設計上の許容
                    continue
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return {'sig': sig}

    def _live_selection_dump(self, max_features=500):
        """GET /live/selection 用(GUIスレッド): 選択中の地物を
        GeoJSON FeatureCollection で返す(各 properties.__layer に
        kasc タイトルを付与)。max_features は全レイヤ合計の上限。
        """
        from qgis.core import QgsVectorLayer, QgsJsonExporter
        titles = self._kasc_title_map()
        layers_out = []
        features = []
        budget = max(1, int(max_features or 500))
        for lid, layer in QgsProject.instance().mapLayers().items():
            try:
                if not isinstance(layer, QgsVectorLayer):
                    continue
                cnt = int(layer.selectedFeatureCount())
                if not cnt:
                    continue
                title = titles.get(lid) or layer.name()
                layers_out.append({'title': title, 'count': cnt})
                remaining = budget - len(features)
                if remaining <= 0:
                    continue
                exporter = QgsJsonExporter(layer)
                for f in layer.selectedFeatures()[:remaining]:
                    try:
                        feat = json.loads(exporter.exportFeature(f))
                        feat.setdefault('properties', {})[
                            '__layer'] = title
                        features.append(feat)
                    except Exception:  # nosec B112  # 設計上の許容
                        continue
            except Exception:  # nosec B112  # 設計上の許容
                continue
        return {'layers': layers_out,
                'geojson': {'type': 'FeatureCollection',
                            'features': features}}

    def _handle_live_render(self, conn, params):
        """GET /live/render 用: EPSG:4326 の bbox で地図を描画しPNGを返す。

        Canvas の「QGIS描画」フォールバックオーバーレイが使う。
        bg=transparent で背景透過、layers=<kasc titles,カンマ区切り> で
        描画対象レイヤを絞れる(省略時はキャンバスの全レイヤ)。
        応答 X-Map-Extent は EPSG:4326 で返し、配置側は
        そのままアンカーできる。
        """
        from . import http_server
        from qgis.core import QgsMapSettings
        from qgis.PyQt.QtCore import QSize, QBuffer, QIODevice, \
            QByteArray, Qt
        canvas = self.iface.mapCanvas()
        ms = QgsMapSettings(canvas.mapSettings())
        bbox = self._parse_floats(params.get('bbox', [None])[0], 4)
        if bbox is None or not (bbox[2] > bbox[0] and bbox[3] > bbox[1]):
            http_server.send_http_response(
                conn, 400, 'Bad Request',
                'bbox=w,s,e,n (EPSG:4326) is required',
                'text/plain; charset=utf-8')
            return
        rect = QgsRectangle(*bbox)
        project = QgsProject.instance()
        src = QgsCoordinateReferenceSystem('EPSG:4326')
        dest = ms.destinationCrs()
        try:
            if src.isValid() and dest.isValid() and src != dest:
                rect = QgsCoordinateTransform(
                    src, dest, project).transformBoundingBox(rect)
        except Exception as e:
            http_server.send_http_response(
                conn, 400, 'Bad Request',
                'extent transform failed: {0}'.format(e),
                'text/plain; charset=utf-8')
            return
        w = self._safe_int(
            params.get('w', params.get('width', [0]))[0], 0)
        h = self._safe_int(
            params.get('h', params.get('height', [0]))[0], 0)
        if w <= 0 or h <= 0:
            w, h = 1024, 768
        w, h = min(w, 4096), min(h, 4096)
        ms.setExtent(self._adjust_extent_to_aspect(rect, w, h))
        ms.setRotation(0)
        layers_param = str(params.get('layers', [''])[0] or '').strip()
        if layers_param:
            resolved = [self._resolve_kasc_layer(t.strip())
                        for t in layers_param.split(',') if t.strip()]
            ms.setLayers([lyr for lyr in resolved if lyr is not None])
        if str(params.get('bg', [''])[0]).lower() \
                in ('transparent', 'none', '0'):
            ms.setBackgroundColor(Qt.GlobalColor.transparent)
        ms.setOutputSize(QSize(w, h))
        image = None
        try:
            with self._render_lock:
                image = self._render_map_settings(ms)
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
        rendered = ms.extent()
        try:
            if src.isValid() and dest.isValid() and src != dest:
                rendered = QgsCoordinateTransform(
                    dest, src, project).transformBoundingBox(rendered)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        extra_headers = [
            'X-Map-Extent: {:.6f},{:.6f},{:.6f},{:.6f}'.format(
                rendered.xMinimum(), rendered.yMinimum(),
                rendered.xMaximum(), rendered.yMaximum()),
            'Access-Control-Expose-Headers: X-Map-Extent',
        ]
        http_server.send_binary_response(
            conn, 200, 'OK', bytes(ba), 'image/png', extra_headers)

    @staticmethod
    def _parse_floats(text, count):
        """'a,b,c,...' 形式のクエリ値を float リストへ変換する。

        個数が一致し全て有限値ならリストを返し、それ以外は None。
        """
        if text is None:
            return None
        try:
            values = [float(v) for v in str(text).split(',')]
        except (TypeError, ValueError):
            return None
        if len(values) != count:
            return None
        for v in values:
            if v != v or v in (float('inf'), float('-inf')):
                return None
        return values

    @staticmethod
    def _screen_region_to_extent(rect, rot_deg):
        """回転 rot_deg の描画で、画面上に写したい領域 rect(キャンバスCRS)
        が収まるよう setExtent に渡すべき軸平行矩形を返す。

        mapToPixel のピクセル→地図座標変換は extent を中心に +rot_deg
        (反時計回り)回転するため、頂点を逆回転した外接矩形を返す。
        rect より若干大きい範囲になり得る(包含保証のための安全側)。
        """
        cx = rect.center().x()
        cy = rect.center().y()
        a = math.radians(-rot_deg)
        ca, sa = math.cos(a), math.sin(a)
        xs, ys = [], []
        for x, y in (
                (rect.xMinimum(), rect.yMinimum()),
                (rect.xMaximum(), rect.yMinimum()),
                (rect.xMaximum(), rect.yMaximum()),
                (rect.xMinimum(), rect.yMaximum())):
            dx, dy = x - cx, y - cy
            xs.append(cx + dx * ca - dy * sa)
            ys.append(cy + dx * sa + dy * ca)
        return QgsRectangle(min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _adjust_extent_to_aspect(rect, out_w, out_h):
        """rect を out_w/out_h のアスペクト比へ拡張して合わせた QgsRectangle を返す。"""
        if out_w <= 0 or out_h <= 0 or rect.width() <= 0 or rect.height() <= 0:
            return rect
        target = out_w / out_h
        current = rect.width() / rect.height()
        if abs(current - target) < 1e-9:
            return rect
        if current > target:
            dh = rect.width() / target - rect.height()
            rect.setYMinimum(rect.yMinimum() - dh / 2.0)
            rect.setYMaximum(rect.yMaximum() + dh / 2.0)
        else:
            dw = rect.height() * target - rect.width()
            rect.setXMinimum(rect.xMinimum() - dw / 2.0)
            rect.setXMaximum(rect.xMaximum() + dw / 2.0)
        return rect

    def _handle_screenshot(self, conn, params):
        """現在の地図キャンバス表示と同等内容のPNGを返す(回転も反映)。

        QgsMapRendererParallelJob でキャンバスのMapSettingsを複製描画するため
        GUIスレッドをブロックしない。w/h(またはwidth/height)で出力サイズ指定可。
        視聴者側ズーム用に描画範囲を変えるパラメータを持つ:
          extent=xmin,ymin,xmax,ymax ... キャンバスCRSの範囲を直接指定
            (同一描画の再現用。回転はそのまま効く)
          screen=xmin,ymin,xmax,ymax ... 画面上に見せたい領域をキャンバス
            CRSで指定。回転時は写る範囲が矩形からずれるため、逆回転した
            外接矩形へ内部変換して描画する(回転0では extent と同義)
          bbox=cx,cy,fw,fh ... ベース画像(既定=現在のキャンバス描画)に対する
            割合座標で、中心(cx,cy)と表示幅高(fw,fh,ともに0..1)を指定する。
            base=xmin,ymin,xmax,ymax と bw,bh でベース画像を差し替えられる
            (ズーム表示をさらに拡大・移動する継続操作用。base は直前の
            X-Map-Extent 値、bw/bh はその画像のピクセルサイズ)。
        応答ヘッダ:
          X-Map-Extent ... 実際に setExtent した範囲(キャンバスCRS)
          X-Map-Corners ... 描画画像の左上/右上/左下の実座標
            (x,yを6値連結。回転時も画像の写る位置を正確に示す)
        """
        from . import http_server
        canvas = self.iface.mapCanvas()
        from qgis.core import QgsMapSettings
        from qgis.PyQt.QtCore import QSize, QBuffer, QIODevice, QByteArray
        ms = QgsMapSettings(canvas.mapSettings())

        # --- 描画範囲の解決(既定はキャンバスそのまま) ---
        rect = None
        bbox = self._parse_floats(params.get('bbox', [None])[0], 4)
        if bbox is not None:
            cx, cy, fw, fh = bbox
            if 0 < fw <= 1.0 and 0 < fh <= 1.0:
                try:
                    # ベース画像を再現する MapSettings を組み、ピクセル→
                    # 地図座標の変換(mapToPixel=回転対応)で範囲を求める
                    base_ms = QgsMapSettings(ms)
                    base = self._parse_floats(
                        params.get('base', [None])[0], 4)
                    if base is not None:
                        base_ms.setExtent(QgsRectangle(*base))
                    bw0 = self._safe_int(params.get('bw', [0])[0], 0)
                    bh0 = self._safe_int(params.get('bh', [0])[0], 0)
                    if bw0 > 0 and bh0 > 0:
                        base_ms.setOutputSize(QSize(bw0, bh0))
                    w0 = base_ms.outputSize().width()
                    h0 = base_ms.outputSize().height()
                    if w0 > 0 and h0 > 0:
                        ctr = base_ms.mapToPixel().toMapPoint(
                            cx * w0, cy * h0)
                        mupp = base_ms.mapUnitsPerPixel()
                        wm = fw * w0 * mupp
                        hm = fh * h0 * mupp
                        rect = QgsRectangle(
                            ctr.x() - wm / 2.0, ctr.y() - hm / 2.0,
                            ctr.x() + wm / 2.0, ctr.y() + hm / 2.0)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'⚠️ screenshot bbox ignored: {e}',
                        'geo_webview', Qgis.MessageLevel.Warning)
        else:
            ext = self._parse_floats(params.get('extent', [None])[0], 4)
            if ext is not None and ext[2] > ext[0] and ext[3] > ext[1]:
                rect = QgsRectangle(*ext)
            else:
                scr = self._parse_floats(
                    params.get('screen', [None])[0], 4)
                if scr is not None and scr[2] > scr[0] and scr[3] > scr[1]:
                    rect = QgsRectangle(*scr)
                    rot = ms.rotation()
                    if abs(rot) > 1e-9:
                        rect = self._screen_region_to_extent(rect, rot)

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
        if rect is not None:
            ms.setExtent(self._adjust_extent_to_aspect(rect, w, h))
        # rot=<deg>: 描画回転を明示(既定=キャンバス回転)。0 で北向き描画
        rot_p = params.get('rot', [None])[0]
        if rot_p is not None:
            try:
                ms.setRotation(float(rot_p))
            except (TypeError, ValueError):
                pass
        ms.setOutputSize(QSize(w, h))
        image = None
        try:
            with self._render_lock:
                image = self._render_map_settings(ms)
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
        rendered = ms.extent()
        # 画像コーナーの実座標(回転を含む描画位置の正確なアンカー用)
        m2p = ms.mapToPixel()
        c_tl = m2p.toMapPoint(0, 0)
        c_tr = m2p.toMapPoint(w, 0)
        c_bl = m2p.toMapPoint(0, h)
        extra_headers = [
            'X-Map-Extent: {:.6f},{:.6f},{:.6f},{:.6f}'.format(
                rendered.xMinimum(), rendered.yMinimum(),
                rendered.xMaximum(), rendered.yMaximum()),
            'X-Map-Corners: {:.6f},{:.6f},{:.6f},{:.6f},{:.6f},{:.6f}'.format(
                c_tl.x(), c_tl.y(), c_tr.x(), c_tr.y(), c_bl.x(), c_bl.y()),
            'Access-Control-Expose-Headers: X-Map-Extent, X-Map-Corners',
        ]
        http_server.send_binary_response(
            conn, 200, 'OK', data, 'image/png', extra_headers)

    def _render_map_settings(self, map_settings, timeout_s=30):
        """QgsMapRendererParallelJob で map_settings を複製描画して QImage を返す。

        /screenshot 用。GUIスレッドをブロックしないようイベントループで
        待機し、timeout_s 秒でタイムアウトする。呼び出し側で
        self._render_lock を取得して直列化すること。
        """
        from qgis.core import QgsMapRendererParallelJob
        from qgis.PyQt.QtCore import QEventLoop, QTimer

        render_job = QgsMapRendererParallelJob(map_settings)
        loop = QEventLoop()
        render_job.finished.connect(loop.quit)
        render_job.start()
        timer = QTimer()
        timer.timeout.connect(loop.quit)
        timer.setSingleShot(True)
        timer.start(int(timeout_s * 1000))
        loop.exec()
        if render_job.isActive():
            render_job.cancel()
            return None
        image = render_job.renderedImage()
        if image is None or image.isNull():
            return None
        return image

    def _handle_layouts(self, conn):
        """プロジェクトの印刷レイアウト一覧をJSONで返す(GET /layouts)。"""
        from . import http_server

        def work():
            mgr = QgsProject.instance().layoutManager()
            out = []
            for layout in mgr.printLayouts():
                entry = {
                    'name': layout.name(),
                    'pages': layout.pageCollection().pageCount(),
                }
                if layout.pageCollection().pageCount() > 0:
                    size = layout.pageCollection().page(0).pageSize()
                    entry['w_mm'] = round(size.width(), 1)
                    entry['h_mm'] = round(size.height(), 1)
                out.append(entry)
            return out

        try:
            layouts = self._main_invoker.call(work, timeout=30)
            payload = json.dumps(
                {'ok': True, 'layouts': layouts}, ensure_ascii=False)
            http_server.send_http_response(
                conn, 200, 'OK', payload,
                'application/json; charset=utf-8')
        except Exception as e:
            http_server.send_http_response(
                conn, 500, 'Internal Server Error',
                f'layouts failed: {e}', 'text/plain; charset=utf-8')

    def _handle_layout_pdf(self, conn, params):
        """印刷レイアウトをPDF出力して返す(GET /layout-pdf?layout=<name>)。

        ?layout 省略時は先頭のレイアウト。?dpi= で出力DPIを指定可
        (72-600、既定300)。QgsLayoutExporter はGUIスレッドで実行する。
        """
        from . import http_server
        name = (params.get('layout') or params.get('name') or [None])[0]
        dpi = max(72, min(self._safe_int(params.get('dpi', [300])[0], 300), 600))

        def work():
            import tempfile
            from qgis.core import QgsLayoutExporter
            mgr = QgsProject.instance().layoutManager()
            layout = mgr.layoutByName(name) if name else None
            if layout is None:
                layouts = mgr.printLayouts()
                if name or not layouts:
                    raise LookupError(
                        'layout not found: {}'.format(name or '(none)'))
                layout = layouts[0]
            fd, path = tempfile.mkstemp(
                suffix='.pdf', prefix='geo_webview_layout_')
            os.close(fd)
            settings = QgsLayoutExporter.PdfExportSettings()
            settings.dpi = dpi
            result = QgsLayoutExporter(layout).exportToPdf(path, settings)
            if result != QgsLayoutExporter.ExportResult.Success:
                try:
                    os.remove(path)
                except OSError:  # nosec B110  # 設計上の許容
                    pass
                raise RuntimeError(
                    'PDF export failed: {}'.format(result))
            return path, layout.name()

        try:
            with self._layout_lock:
                pdf_path, layout_name = self._main_invoker.call(
                    work, timeout=120)
        except LookupError as e:
            http_server.send_http_response(
                conn, 404, 'Not Found', str(e),
                'text/plain; charset=utf-8')
            return
        except Exception as e:
            http_server.send_http_response(
                conn, 500, 'Internal Server Error',
                f'layout-pdf failed: {e}', 'text/plain; charset=utf-8')
            return

        try:
            with open(pdf_path, 'rb') as f:
                data = f.read()
        finally:
            try:
                os.remove(pdf_path)
            except OSError:  # nosec B110  # 設計上の許容
                pass
        quoted = urllib.parse.quote(layout_name or 'layout')
        headers = [
            "Content-Disposition: inline; filename=\"print.pdf\";"
            " filename*=UTF-8''{}.pdf".format(quoted),
        ]
        http_server.send_binary_response(
            conn, 200, 'OK', data, 'application/pdf', headers)

    def _handle_present_page(self, conn, params):
        """地図キャンバスのウィンドウ共有ページ(/screenshot定期更新)を返す。

        OpenLayers ビュー上に北向き描画画像を配置し、視聴者ごとに
        ドラッグ/ホイール/ピンチ/回転(Alt+Shift+ドラッグ)等地図ライブラリ
        標準操作で独立ズーム・移動・回転できる。キャンバス回転は
        ビューの回転として再現されるため、QGIS と同じ見え方になる。
        操作終了時(moveend)に /screenshot?extent=...&rot=0 で該当範囲を
        サーバ再描画する。
        """
        from . import http_server
        interval = self._safe_int(params.get('interval', [1500])[0], 1500)
        if interval < 250:
            interval = 250
        lang = lang_code() or 'en'
        html_page = u'''<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="initial-scale=1"/>
<title>geo_webview - Presentation</title>
<link rel="stylesheet" href="vendor/ol/ol.css"/>
<script src="vendor/ol/ol.js"></script>
<style>
html,body{margin:0;padding:0;height:100%;background:#111;color:#eee;font-family:sans-serif;overflow:hidden}
#map{position:fixed;inset:0;background:#111}
.ol-viewport{background:#111}
#info{position:fixed;left:0;right:0;bottom:0;padding:4px 10px;background:rgba(0,0,0,.55);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none;z-index:2000}
#hint{position:fixed;top:8px;left:10px;padding:2px 8px;background:rgba(0,0,0,.45);border-radius:4px;font-size:11px;opacity:.9;pointer-events:none;z-index:2000}
/* ナビゲーションツールバー(KASUGAI Canvas OL版と同型の右上配置) */
.navigation-toolbar{position:fixed;z-index:2000;top:14px;right:14px;display:flex;flex-direction:column;align-items:center;gap:6px;padding:7px 5px;border:1px solid rgba(14,32,64,.12);border-radius:10px;background:rgba(255,255,255,.6);box-shadow:0 8px 18px rgba(10,20,40,.16)}
.navigation-toolbar button{min-width:42px;min-height:29px;padding:5px 7px;border:1px solid rgba(0,0,0,.08);border-radius:7px;background:linear-gradient(#fff,#f1f4f8);color:#263643;cursor:pointer;font-size:13px}
.navigation-toolbar button:hover{background:#e7f3f0}
.compass-button{position:relative;width:64px;height:64px;min-width:64px !important;min-height:64px !important;border-radius:50% !important;transition:transform 180ms ease}
.compass-button strong{position:absolute;left:50%;top:15px;transform:translateX(-50%);color:#222;font-size:19px}
.compass-needle{position:absolute;left:50%;top:50%;width:0;height:0;border-left:7px solid transparent;border-right:7px solid transparent;border-bottom:27px solid #e33d3d;transform:translate(-7px,-27px);transform-origin:7px 27px}
.compass-needle::after{content:"";position:absolute;left:0;top:27px;border-left:7px solid transparent;border-right:7px solid transparent;border-top:27px solid #a82020}
/* ホバーヒント(コンパスはtransformで回転するため針と別の.nav-itemラッパーに置く) */
.navigation-toolbar .nav-item{position:relative;display:flex}
.navigation-toolbar .nav-hint{position:absolute;right:calc(100% + 8px);top:50%;transform:translateY(-50%);padding:4px 8px;border-radius:6px;background:rgba(20,30,40,.85);color:#fff;font-size:11px;white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .15s}
.navigation-toolbar .nav-item:hover .nav-hint,.navigation-toolbar .nav-item:focus-within .nav-hint{opacity:1}
#reset{position:fixed;top:8px;right:10px;padding:6px 12px;background:rgba(0,0,0,.6);color:#fff;border:1px solid #777;border-radius:4px;font-size:12px;cursor:pointer;display:none;z-index:2000}
#reset:hover{background:rgba(70,70,70,.8)}
</style>
</head>
<body>
<div id="map"></div>
<div id="hint">__T_HINT__</div>
<aside class="navigation-toolbar" aria-label="__T_NAV__">
  <span class="nav-item"><button id="nav-compass" class="compass-button" type="button" title="__T_RESETNORTH__"><span class="compass-needle"></span><strong>N</strong></button><span class="nav-hint" role="tooltip">__T_ROTATEHINT__</span></span>
  <span class="nav-item"><button id="nav-home" type="button" title="__T_RESETHOME__">⌂</button><span class="nav-hint" role="tooltip">__T_HOMEHINT__</span></span>
</aside>
<div id="info">__T_INFO__</div>
<script>
(function(){
  var info = document.getElementById('info');
  var compass = document.getElementById('nav-compass');
  var timer = __INTERVAL__;
  var dpr = Math.min(window.devicePixelRatio || 1, 2);

  var proj = new ol.proj.Projection({code: 'canvas', units: 'm'});
  var view = new ol.View({
    projection: proj, center: [0, 0], resolution: 1, rotation: 0
  });
  var map = new ol.Map({
    target: 'map',
    controls: ol.control.defaults.defaults(
      {zoom: false, rotate: false, attribution: false}),
    interactions: ol.interaction.defaults.defaults(),
    layers: [],
    view: view
  });
  var imgLayer = new ol.layer.Image();
  map.addLayer(imgLayer);

  // --- プレゼンターのマウスカーソル(誇張表示) ---
  var cursorFeature = new ol.Feature();
  var cursorSvg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24">' +
    '<path d="M5 3 L19 12 L12 13.8 L9 21 Z" fill="#ffdd00" stroke="#111" stroke-width="1.4"/></svg>';
  var cursorLayer = new ol.layer.Vector({
    source: new ol.source.Vector({features: [cursorFeature]}),
    style: new ol.style.Style({
      image: new ol.style.Icon({
        src: 'data:image/svg+xml;utf8,' + encodeURIComponent(cursorSvg),
        anchor: [0.14, 0.08],
        scale: 1.5
      })
    }),
    updateWhileAnimating: true,
    updateWhileInteracting: true
  });
  map.addLayer(cursorLayer);

  var home = true;          // true=キャンバス共有ビュー追従中
  var homeRes = 0;          // 追従時の解像度(倍率表示の基準)
  var program = false;      // プログラム的なビュー移動中フラグ
  var loading = false;
  var dirty = false;
  var gen = 0;              // reset毎に+1(飛行中レスポンスの破棄用)
  var curUrl = null;        // revoke用objectURL
  var renderTimer = null;
  var stateText = '';

  function updateHud(){
    var z = '';
    if(!home && homeRes > 0)
      z = '   [zoom x' + (homeRes / view.getResolution()).toFixed(1) +
          '__T_INDVIEW__]';
    info.textContent = stateText + z;
  }
  function setImage(d){
    if(curUrl) URL.revokeObjectURL(curUrl);
    curUrl = d.url;
    imgLayer.setSource(new ol.source.ImageStatic({
      url: d.url,
      imageExtent: (d.extent && d.extent.length === 4) ?
                   d.extent : d.requested,
      projection: proj
    }));
  }
  var reqExt = null;        // 直近リクエストの extent(ヘッダ欠落時の予備)
  function loadImage(url, cb){
    loading = true;
    fetch(url).then(function(r){
      if(!r.ok) throw new Error('http ' + r.status);
      var ext = (r.headers.get('X-Map-Extent') || '').split(',').map(Number);
      return r.blob().then(function(b){
        cb({url: URL.createObjectURL(b), extent: ext, requested: reqExt});
      });
    }).catch(function(e){
      // 失敗時は前の画像を保持
    }).finally(function(){
      loading = false;
      if(dirty){ dirty = false; renderView(); }
    });
  }
  // 現在のビュー領域を北向きでサーバ再描画して差し替える
  function renderView(){
    if(loading){ dirty = true; return; }
    var size = map.getSize();
    if(!size) return;
    var ext = view.calculateExtent(size);
    var w = Math.round(size[0] * dpr), h = Math.round(size[1] * dpr);
    reqExt = ext;
    var g = gen;
    loadImage('screenshot?extent=' + ext.join(',') + '&rot=0' +
              '&w=' + w + '&h=' + h + '&ts=' + Date.now(),
      function(d){
        if(g !== gen){ URL.revokeObjectURL(d.url); return; }
        setImage(d);
        updateHud();
      });
  }
  function reset(){
    gen++;
    home = true;
    dirty = false;
    updateHud();
    pollState(true);
  }

  // ユーザー操作で独立ビューへ移行(DOMイベントのみ判定。
  // movestart はプログラム的移動でも非同期発火するため使わない)
  function userMoved(){
    if(home){ home = false; updateHud(); }
  }
  map.getTargetElement().addEventListener('pointerdown', userMoved);
  map.getTargetElement().addEventListener('wheel', userMoved);
  map.getTargetElement().addEventListener('touchstart', userMoved);
  map.on('moveend', function(){
    if(renderTimer) clearTimeout(renderTimer);
    renderTimer = setTimeout(renderView, 150);
  });
  map.on('change:size', function(){ renderView(); });
  document.getElementById('nav-home').addEventListener('click', reset);
  compass.addEventListener('click', function(){
    userMoved();
    view.animate({rotation: 0, duration: 300});
  });
  view.on('change:rotation', function(){
    compass.style.transform =
      'rotateZ(' + (view.getRotation() * 180 / Math.PI) + 'deg)';
  });
  window.addEventListener('keydown', function(e){
    if(e.key === 'Escape' || e.key === '0') reset();
    else if(e.key === '+' || e.key === '-' ||
            e.key.indexOf('Arrow') === 0) userMoved();
  });

  // キャンバス状態の追従(home時)と情報表示
  async function pollState(force){
    try{
      var r = await fetch('present/state'); var s = await r.json();
      if(!s) return;
      stateText =
        '__T_CENTER__' + (s.lon!=null? s.lon.toFixed(6)+','+s.lat.toFixed(6) : s.x.toFixed(1)+','+s.y.toFixed(1)) +
        '__T_SCALE__' + Math.round(s.scale) +
        '__T_ROT__' + (s.rotation||0).toFixed(1) + '°  crs: ' + s.crs +
        '  (' + s.time + ')';
      if(s.cursor && s.cursor.x != null)
        cursorFeature.setGeometry(
          new ol.geom.Point([s.cursor.x, s.cursor.y]));
      else
        cursorFeature.setGeometry(null);
      if(home && s.mupp > 0){
        var rot = (s.rotation || 0) * Math.PI / 180;
        var c = view.getCenter(), res = view.getResolution();
        var moved = Math.abs(c[0]-s.x) + Math.abs(c[1]-s.y) > s.mupp
          || Math.abs(res - s.mupp) > s.mupp * 1e-4
          || Math.abs(view.getRotation() - rot) > 1e-5;
        if(moved || force){
          program = true;
          view.setCenter([s.x, s.y]);
          view.setResolution(s.mupp);
          view.setRotation(rot);
          program = false;
          homeRes = s.mupp;
        }
      }
      updateHud();
    }catch(e){}
  }
  // カーソル追従は軽量な state ポーリングで高速化、再描画は interval 間隔
  setInterval(pollState, 350);
  setInterval(renderView, timer);
  pollState(true); renderView();
})();
</script>
</body>
</html>'''
        html_page = _localize_page(html_page
                                   .replace('__LANG__', lang)
                                   .replace('__INTERVAL__', str(interval)))
        http_server.send_http_response(
            conn, 200, 'OK', html_page, 'text/html; charset=utf-8')

    # 静的配信用 Content-Type 対応表。mimetypes モジュールは
    # Windows レジストリ依存で .js が text/plain になる環境があるため
    # 主要型は固定する
    _STATIC_MIME = {
        '.html': 'text/html; charset=utf-8',
        '.htm': 'text/html; charset=utf-8',
        '.js': 'text/javascript; charset=utf-8',
        '.mjs': 'text/javascript; charset=utf-8',
        '.css': 'text/css; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.geojson': 'application/geo+json; charset=utf-8',
        '.kasc': 'application/json; charset=utf-8',
        '.qml': 'application/xml; charset=utf-8',
        '.xml': 'application/xml; charset=utf-8',
        '.csv': 'text/csv; charset=utf-8',
        '.tsv': 'text/tab-separated-values; charset=utf-8',
        '.txt': 'text/plain; charset=utf-8',
        '.svg': 'image/svg+xml',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.ico': 'image/x-icon',
        '.zip': 'application/zip',
        '.wasm': 'application/wasm',
        '.map': 'application/json; charset=utf-8',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
        '.ttf': 'font/ttf',
        '.parquet': 'application/octet-stream',
        '.fgb': 'application/octet-stream',
        '.b3dm': 'application/octet-stream',
        '.gpkg': 'application/octet-stream',
    }

    @classmethod
    def _static_content_type(cls, path):
        return cls._STATIC_MIME.get(
            os.path.splitext(path)[1].lower(), 'application/octet-stream')

    def _handle_export_data(self, conn, rel, head_only=False):
        """KASUGAI/Re:Earth エクスポート産物(直近の出力先配下)を配信。

        パストラバーサル防止のため出力ディレクトリ外は拒否する。
        Re:Earth inspector の絶対URL参照や Canvas プロジェクト登録時の
        DATA/ 直接参照に使う。インストール先 projects/<id>/ に出力した
        場合も last_export_dir() でそちらを配信する。
        .html/.js/.css 等も正しい Content-Type で返すため、出力された
        エンジンランチャーHTMLをこのサーバ経由でブラウザ表示できる。
        """
        import os
        import urllib.parse
        from . import http_server, kasugai_export
        root = os.path.abspath(kasugai_export.last_export_dir())
        rel_path = urllib.parse.unquote(rel or '').replace('\\', '/')
        target = os.path.abspath(os.path.join(root, rel_path))
        if not target.startswith(root + os.sep) or not os.path.isfile(target):
            # kasugai_canvas*.zip はファイル未生成でもその場で固めて返す
            # (エクスポート時のZIP生成は廃止し、ダウンロード要求時に生成。
            # ファイル名は要求名をそのまま返す=CDNチャンネル反映名に対応)
            if '/' not in rel_path.lstrip('/') \
                    and kasugai_export._is_export_zip_name(rel_path) \
                    and os.path.isdir(root):
                data = kasugai_export.build_export_zip(root)
                fname = os.path.basename(rel_path)
                if head_only:
                    http_server.send_head_response(
                        conn, 200, 'OK', len(data), 'application/zip')
                    return
                http_server.send_binary_response(
                    conn, 200, 'OK', data, 'application/zip',
                    ['Content-Disposition: attachment; '
                     'filename="{0}"'.format(fname)])
                return
            http_server.send_http_response(
                conn, 404, 'Not Found', 'not found',
                'text/plain; charset=utf-8')
            return
        ctype = self._static_content_type(target)
        if head_only:
            http_server.send_head_response(
                conn, 200, 'OK', os.path.getsize(target), ctype)
            return
        with open(target, 'rb') as f:
            data = f.read()
        http_server.send_binary_response(conn, 200, 'OK', data, ctype)

    def _handle_canvas_web(self, conn, rel_path, head_only=False):
        """インストール済み KASUGAI Canvas の ``web/`` を静的配信する。

        Canvas サーバ(8510)未起動時に、エクスポート済み .kasc+DATA/ を
        開くための最小HTTPサーバとして本サーバを使うためのフォールバック。
        全エンドポイントに一致しなかったパスを web/ 配下へ解決する
        (例: /cesium/index.html → <install>/web/cesium/index.html)。
        配信できれば True、見つからなければ False。
        """
        from . import http_server, kasugai_export
        web_root = kasugai_export.find_kasugai_web_dir()
        if not web_root:
            return False
        web_root = os.path.normcase(os.path.abspath(web_root))
        rel = urllib.parse.unquote(rel_path or '').replace('\\', '/')
        target = os.path.abspath(
            os.path.join(web_root, *rel.lstrip('/').split('/')))
        target_nc = os.path.normcase(target)
        if target_nc != web_root and \
                not target_nc.startswith(web_root + os.sep):
            return False
        if os.path.isdir(target):
            target = os.path.join(target, 'index.html')
        if not os.path.isfile(target):
            return False
        ctype = self._static_content_type(target)
        if head_only:
            http_server.send_head_response(
                conn, 200, 'OK', os.path.getsize(target), ctype)
            return True
        with open(target, 'rb') as f:
            data = f.read()
        http_server.send_binary_response(conn, 200, 'OK', data, ctype)
        return True

    def _handle_kasugai(self, conn, params=None):
        """表示中レイヤをKASUGAI Canvasプロジェクトとして出力し、
        起動中のKASUGAIローカルサーバへ登録してプロジェクトURLを返す。

        params['engine'] で起動エンジンを指定できる
        (cesium|maplibre|openlayers|leaflet|gsimaps|navara、既定 cesium)。

        応答JSON:
          成功 {ok:true, url:<開くURL|null>, via, dir, layers, tiles, engine}
          失敗 {ok:false, error}
        via は url の供給元: 'kasugai'=Canvasサーバ登録、
        'qgis-http'=本サーバのCanvas web/静的配信フォールバック、
        'hosted'=ホスト版エンジン(kasugai-canvas-web)+本サーバの
        データ配信(Canvas未インストール向け・要インターネット)、
        null=未起動かつフォールバック不可(出力のみ成功)。
        """
        from . import http_server, kasugai_export
        engine = kasugai_export.DEFAULT_ENGINE
        try:
            requested = (params or {}).get('engine', [None])[0]
            if requested:
                engine = kasugai_export.normalize_engine(requested) \
                    or kasugai_export.DEFAULT_ENGINE
        except Exception:  # nosec B110  # 設計上の許容
            pass
        with self._kasugai_lock:
            result = kasugai_export.export_kasugai_project(
                self.iface,
                out_dir=kasugai_export.preferred_output_dir())
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
            via = None
            # ?route= で再生経路を明示できる: kasugai / local|qgis-http /
            # hosted。未指定(auto)は従来どおり3段フォールバック
            route = str(
                (params or {}).get('route', ['auto'])[0] or 'auto'
                ).strip().lower()
            if route == 'qgis-http':
                route = 'local'
            if route not in ('auto', 'kasugai', 'local', 'hosted'):
                route = 'auto'
            try:
                caps = None
                _launched = False
                if route in ('auto', 'kasugai'):
                    caps, _launched = kasugai_export.ensure_kasugai_running(
                        result['kasc'], pump_events=False)
                if not caps and route in ('auto', 'kasugai') and str(
                        (params or {}).get('install', [''])[0]
                        ).lower() in ('1', 'true', 'yes'):
                    # ?install=1: 未検出なら配布ZIPを取得・展開して再試行
                    kasugai_export.install_kasugai()
                    caps, _launched = kasugai_export.ensure_kasugai_running(
                        result['kasc'], pump_events=False)
                if caps:
                    reg = kasugai_export.register_kasugai_project(
                        result['kasc'], engine=engine)
                    if reg.get('ok'):
                        kasugai_export.kasugai_command(
                            'switchProject', {'projectId': reg['id']})
                        url = reg.get('url')
                        via = 'kasugai'
            except Exception as e:
                QgsMessageLog.logMessage(
                    f'⚠️ KASUGAI registration failed: {e}',
                    'geo_webview', Qgis.MessageLevel.Warning)
            if not url and route in ('auto', 'local'):
                # Canvas未起動/未検出のフォールバック: このHTTPサーバ自体を
                # 最小配信サーバとして使い、インストール済みCanvasの web/ と
                # /export-data/ 配下の .kasc+DATA/ でエンジンを開く
                try:
                    # 旧単一エンジン構成のインストールは ?kasc= 非対応のため
                    # <engine>/ の存在まで確認する
                    if kasugai_export.find_kasugai_engine_dir(engine):
                        url = kasugai_export.build_local_view_url(
                            result['kasc'], engine=engine,
                            port=self.get_server_port() or self.server_port)
                        if url:
                            via = 'qgis-http'
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'⚠️ KASUGAI static fallback failed: {e}',
                        'geo_webview', Qgis.MessageLevel.Warning)
            if not url and route in ('auto', 'hosted'):
                # 最終フォールバック: ホスト版エンジン(kasugai-canvas-web)
                # + 本サーバの /export-data/ データ配信。Canvas未インストール
                # 環境でもブラウザで開ける(要インターネット)
                try:
                    url = kasugai_export.build_hosted_view_url(
                        result['kasc'], engine=engine,
                        port=self.get_server_port() or self.server_port)
                    if url:
                        via = 'hosted'
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f'⚠️ KASUGAI hosted fallback failed: {e}',
                        'geo_webview', Qgis.MessageLevel.Warning)
            http_server.send_http_response(
                conn, 200, 'OK',
                json.dumps(
                    {'ok': True, 'url': url, 'via': via,
                     'dir': result.get('dir'),
                     'layers': n_layers, 'tiles': n_tiles,
                     'engine': engine},
                    ensure_ascii=False),
                'application/json; charset=utf-8')

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

    def get_local_ip(self):
        """LAN内の他マシンから到達可能な自IPv4を返す(取得不能時は127.0.0.1)。"""
        return self._guess_bind_ip()

    def get_network_url(self, path=''):
        """LAN内の他マシンからアクセス可能なURL(http://<LAN-IP>:<port><path>)を返す。

        サーバ未起動またはLAN IPが取得できない(127.0.0.1)場合はNone。
        """
        port = self.get_server_port()
        if not port:
            return None
        ip = self.get_local_ip()
        if ip == '127.0.0.1':
            return None
        return f"http://{ip}:{port}{path}"

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
