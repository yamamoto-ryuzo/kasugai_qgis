# -*- coding: utf-8 -*-
"""geo_webview を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、geo_driver の
bridge_call コマンド(ファイルJSONL / REST /api/cmd / MCP qgis_bridge_call)
から ``qgis.utils.plugins['geo_webview'].bridge.<method>(*args)`` が
プロセス内で直接呼ばれる。Qt Widgets プラグインなので WebChannel は通らない。

各メソッドは JSON 文字列を返す(bridge_call 側で構造化される)。
ドメインエラーは ``{"ok": false, "error": ...}`` を返し、予期しない例外は
呼び出し元(driver の {"error": traceback})に委ねる。いずれも GUI スレッドで
同期的に実行される。

**モーダルダイアログ禁止**: パネルのボタンハンドラ(on_navigate_clicked_panel
等)はエラー時に QMessageBox を出してGUIスレッドをブロックするため、
bridge では同等処理を例外送出型の内部実装で行う。

例(MCP): qgis_bridge_call pluginId="geo_webview" method="navigate"
         args=["http://localhost:8089/qgis-map?x=15573700&y=4258000&scale=5000&crs=EPSG:3857"]
"""

import inspect
import json
import os
import urllib.parse


def _jsonable(v):
    """QgsPointXY 等のQGIS/Qt値をJSON化可能な値に変換する。"""
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


class GeoWebViewBridge:
    """``plugins['geo_webview'].bridge`` にぶら下げるAI向けAPI。

    保有するのはプラグインインスタンスへの参照のみ。パネルが未生成でも
    サーバー制御・ナビゲーション・URL生成は使える。
    """

    # AI向け自己記述。ドライバの describe_plugins カタログが pluginInfo()
    # 経由でこれを集約する。メソッド仕様は signature/docstring から
    # 自動生成し、METHOD_DOCS で補足する。
    NAME = "geo_webview (QMap Permalink)"
    SUMMARY = ("QGIS プロジェクトを .kasc+DATA/ パッケージに出力して"
               "KASUGAI Canvas(Cesium/MapLibre/OpenLayers/Leaflet/"
               "GSI Maps/Navara)"
               "で再生する"
               "サーバレスWeb配信プラグイン。"
               "地図表示状態(中心/縮尺/回転/テーマ)をパーマリンクURLとして"
               "生成・復元する。"
               "内蔵HTTPサーバは /kasugai 起動・/export-data/ 配信・"
               "/present 画面共有・パーマリンク受領を担う。")
    WHEN_TO_USE = [
        "表示中レイヤをKASUGAI Canvas用に出力・登録・起動したい",
        "現在の地図ビューを共有できるパーマリンクURLを発行したい",
        "パーマリンクのURLからQGISの地図を移動したい",
        "座標・縮尺・回転・テーマを指定して地図ビューを直接操作したい",
        "HTTPサーバの起動・停止・ポート変更・状態確認をしたい",
        "外部端末からのアクセス可否(ファイアウォール等)を診断したい",
        "プロジェクトのマップテーマ/ブックマークを一覧・適用したい",
        "QGISキャンバスを /present・/screenshot で画面共有したい",
    ]
    METHOD_DOCS = {
        "status": {
            "description":
                "パネル表示・HTTPサーバ・キャンバス(中心/縮尺/CRS/回転)・"
                "直近リクエストURLなどの実行時状態を返す。",
            "example": {"method": "status", "args": []},
        },
        "openPanel": {
            "description": "GeoWebViewドックパネルを生成・表示する。",
            "example": {"method": "openPanel", "args": []},
        },
        "closePanel": {
            "description": "GeoWebViewドックパネルを隠す(破棄はしない)。",
            "example": {"method": "closePanel", "args": []},
        },
        "serverStatus": {
            "description":
                "HTTPサーバの稼働状態・ポート・URLを返す。deep=Trueで"
                "外部アクセス診断(ファイアウォール確認、数秒かかる)も実行。",
            "example": {"method": "serverStatus", "args": [True]},
        },
        "startServer": {
            "description":
                "内蔵HTTPサーバを起動する。port指定時はそのポート"
                "優先(使用中なら+10まで探索)。起動済みで別ポート指定なら再起動。",
            "example": {"method": "startServer", "args": [8089]},
        },
        "stopServer": {
            "description": "HTTPサーバを停止する。",
            "example": {"method": "stopServer", "args": []},
        },
        "setPort": {
            "description":
                "優先ポートを設定し、起動中なら即座にそのポートで再起動する"
                "(確認ダイアログ無し)。80/443は管理者権限が必要。",
            "example": {"method": "setPort", "args": [8090]},
        },
        "externalControl": {
            "description":
                "外部制御モードを取得/設定する。TrueにするとHTTPリクエスト"
                "受信時に地図が自動ナビゲートされる。要パネル(openPanel後)。",
            "example": {"method": "externalControl", "args": [True]},
        },
        "generatePermalink": {
            "description":
                "現在の地図ビューから /qgis-map パーマリンクURL(ナビゲーション"
                "交換形式)を生成する。theme指定でテーマ復元情報を付与。"
                "パネルがあれば入力欄にも反映。",
            "example": {"method": "generatePermalink", "args": ["概況図"]},
        },
        "navigate": {
            "description":
                "パーマリンク(/qgis-map・旧/wms)/qgis-permalink:// URLから"
                "地図を移動する。"
                "モーダルダイアログは出さず、失敗は ok:false で返す。",
            "example": {"method": "navigate",
                        "args": ["http://localhost:8089/qgis-map?x=15573700&y=4258000&scale=5000&crs=EPSG:3857"]},
        },
        "navigateTo": {
            "description":
                "座標を直接指定して地図を移動する。x/y+crs または lat/lon、"
                "scale(縮尺分母)またはzoom、rotation(度)、theme(テーマ名)を指定可。",
            "example": {"method": "navigateTo",
                        "args": [{"lat": 35.68, "lon": 139.69, "scale": 5000}]},
        },
        "listThemes": {
            "description":
                "プロジェクトのマップテーマ一覧とパネルの現在選択を返す。",
            "example": {"method": "listThemes", "args": []},
        },
        "applyTheme": {
            "description":
                "マップテーマをレイヤツリーへ適用し、パネルのコンボも同期する。",
            "example": {"method": "applyTheme", "args": ["概況図"]},
        },
        "saveTheme": {
            "description":
                "現在のレイヤツリー状態(表示/非表示・現行スタイル)を"
                "マップテーマとしてプロジェクトへ保存する。"
                "同名がある場合は overwrite=True のときのみ上書き。"
                "パネルのテーマコンボにも反映される。",
            "example": {"method": "saveTheme",
                        "args": [{"name": "概況図", "overwrite": False}]},
        },
        "deleteTheme": {
            "description":
                "マップテーマをプロジェクトから削除し、"
                "パネルのテーマコンボを更新する。",
            "example": {"method": "deleteTheme", "args": ["概況図"]},
        },
        "listBookmarks": {
            "description":
                "プロジェクト/ユーザブックマーク一覧(中心をEPSG:3857化)を返す。",
            "example": {"method": "listBookmarks", "args": []},
        },
        "copyPermalink": {
            "description":
                "パーマリンクをクリップボードへコピーする。未生成なら自動生成。",
            "example": {"method": "copyPermalink", "args": []},
        },
        "openExternal": {
            "description":
                "KASUGAI Canvas を指定エンジンで起動する。serviceは"
                " cesium / openlayers / maplibre / leaflet / gsimaps /"
                " navara。",
            "example": {"method": "openExternal", "args": ["maplibre"]},
        },
        "kasugaiExport": {
            "description":
                "表示中レイヤをKASUGAI Canvasプロジェクト(.kasc+DATA/"
                "+.qmlスタイル)として出力する。GPKG/GeoJSON/Parquet/FGB"
                "ソースは変換せず参照、CSV/TSVはduckdb:行、フィルタ付き"
                "GPKGはwhere=付き、3D Tilesは3dtiles:行、他ベクターは"
                "GeoJSON(4326)化。起動中のKASUGAIローカルサーバ(port 8510)"
                "があれば外部プロジェクト登録してブラウザで開く。"
                "engine=cesium|openlayers|maplibre|leaflet|gsimaps|navara "
                "で起動エンジンを指定できる(既定 cesium)。"
                "open_app=Falseで出力のみ。hidden_as_off=Trueで非表示レイヤ"
                "もoff行として出力。embed_gpkg_style=TrueでGPKGの"
                "layer_stylesへも保存。QGISブックマークは bookmarks.xml"
                "として出力され bookmark: 行が付く(Canvas側がカメラ"
                "プリセットへ展開。emit_bookmarks=Falseで抑制)。"
                ".kascと同じ場所に <engine>.html 起動ページ(index.html"
                "含む)も出力し、フォルダ+エンジンを静的サーバーへ上げる"
                "だけで ?kasc= 経由のサーバレス配信になる"
                "(emit_launchers=Falseで抑制)。"
                "emit_zip=True で出力一式を kasugai_canvas_<tag>.zip に固める"
                "(Re:Earth geo_suite の 'qgis:' インスペクタ行が直接取込可)。"
                "アトラス有効な印刷レイアウトは各ページ範囲を巡回する"
                "fly_geojson: 行+DATA/atlas_*.geojson として出力される"
                "(Canvas FLYルート=プレゼン巡回。emit_atlas=Falseで抑制)。"
                "use_existing=True で再エクスポートせず既存の .kasc のみ"
                "使用(未出力なら code=not_exported)。",
            "example": {"method": "kasugaiExport", "args": []},
        },
        "checkAccess": {
            "description":
                "外部アクセス診断(サーバ状態/ローカルIP/ファイアウォール)を"
                "実行し結果dictを返す。数秒かかる。",
            "example": {"method": "checkAccess", "args": []},
        },
        "endpoints": {
            "description":
                "HTTPサーバが公開するエンドポイント一覧と基底URLを返す。",
            "example": {"method": "endpoints", "args": []},
        },
        "getSettings": {
            "description":
                "設定(KASUGAI出力先・インストール先・優先ポート)とプラグイン"
                "バージョンを返す。",
            "example": {"method": "getSettings", "args": []},
        },
        "setSettings": {
            "description":
                "設定を変更する。対応キー: kasugai_output_path /"
                " kasugai_install_path / kasugai_port /"
                " kasugai_hosted_channel / kasugai_engine /"
                " mac_auth_enabled / mac_auth_allowed / port。",
            "example": {"method": "setSettings",
                        "args": [{"kasugai_port": 8510}]},
        },
        "openExportFolder": {
            "description":
                "KASUGAI出力フォルダ(.kasc+DATA/の出力先)を"
                "OSのファイルマネージャで開く。",
            "example": {"method": "openExportFolder", "args": []},
        },
        "openPresent": {
            "description":
                "キャンバス画面共有ページ(/present)をブラウザで開く"
                "(要HTTPサーバ起動。未起動なら自動起動しない)。"
                "返すurlは共有前提のLAN IP優先(localhostへフォールバック)。",
            "example": {"method": "openPresent", "args": []},
        },
        "receivedHistory": {
            "description":
                "受領パーマリンク履歴(/received。外部から送信された"
                "パーマリンクURLの履歴、最新10件)を返す。",
            "example": {"method": "receivedHistory", "args": []},
        },
        "addFirewallRule": {
            "description":
                "Windowsファイアウォールに受信ルールを追加する。"
                "管理者権限が必要でUAC昇格ダイアログが出る場合がある"
                "(port省略時は現在のサーバポート)。",
            "example": {"method": "addFirewallRule", "args": [8089]},
        },
        "macAuth": {
            "description":
                "MACアドレス認証を取得/設定する。enabled=True/False、"
                "allowed=許可MACアドレス文字列。",
            "example": {"method": "macAuth",
                        "args": [True, "AA-BB-CC-00-11-22"]},
        },
        "liveWriteback": {
            "description":
                "Canvas 側の表示/フィルタ/テーマ状態を QGIS プロジェクトへ"
                "書き戻す(POST /live/writeback と同じ適用ロジック)。",
            "example": {"method": "liveWriteback",
                        "args": [{"layers": [{"title": "道路", "visible": False},
                                             {"title": "筆", "where": "city='名古屋'"}],
                                  "theme": "概況図"}]},
        },
        "liveAddFeatures": {
            "description":
                "GeoJSON をスクラッチ(memory)レイヤとしてプロジェクトへ"
                "投入する(POST /live/features と同じ適用ロジック)。"
                "同名再送は置換(replace=True)。「Canvas」グループへ追加。",
            "example": {"method": "liveAddFeatures",
                        "args": ["作図レイヤー",
                                 {"type": "FeatureCollection", "features": []},
                                 True]},
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

    def _panel(self):
        return getattr(self._plugin, "panel", None)

    def _server(self):
        return getattr(self._plugin, "server_manager", None)

    def _canvas_state(self):
        """現在の地図キャンバス状態をdictで返す(失敗時None)。"""
        try:
            canvas = self._plugin.iface.mapCanvas()
            c = canvas.center()
            ext = canvas.extent()
            return {
                "center": [c.x(), c.y()],
                "extent": [ext.xMinimum(), ext.yMinimum(),
                           ext.xMaximum(), ext.yMaximum()],
                "scale": float(canvas.scale()),
                "rotation": float(canvas.rotation()
                                  if hasattr(canvas, "rotation") else 0.0),
                "crs": canvas.mapSettings().destinationCrs().authid(),
            }
        except Exception:
            return None

    def _update_panel_status(self):
        """サーバー状態をパネル表示へ同期(パネルがあれば)。"""
        panel = self._panel()
        server = self._server()
        if panel is None or server is None:
            return
        try:
            port = server.get_server_port() or server.server_port
            panel.update_server_status(
                port, server.is_server_running(),
                network_url=server.get_network_url())
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _open_url(self, url):
        """既定ブラウザでURLを開く。失敗時は例外。"""
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        if not QDesktopServices.openUrl(QUrl(url)):
            import webbrowser
            webbrowser.open(url)

    # ---------- カタログ ----------

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
        panel = self._panel()
        server = self._server()
        return self._ok({
            "id": "geo_webview",
            "name": self.NAME,
            "summary": self.SUMMARY,
            "when_to_use": list(self.WHEN_TO_USE),
            "invoke": {"type": "bridge_call", "plugin_id": "geo_webview",
                       "method": "<method>", "args": []},
            "methods": self._method_catalog(),
            "state": {
                "panel": panel is not None,
                "panelVisible": bool(panel is not None and panel.isVisible()),
                "serverRunning": bool(server is not None
                                      and server.is_server_running()),
                "serverPort": (server.get_server_port()
                               if server is not None else None),
            },
        })

    def status(self):
        """パネル・サーバ・キャンバス・入出力欄の実行時状態を返す。"""
        p = self._plugin
        panel = self._panel()
        server = self._server()
        server_running = bool(server is not None
                              and server.is_server_running())
        port = server.get_server_port() if server is not None else None
        fields = {}
        if panel is not None:
            for attr in ("lineEdit_permalink", "lineEdit_navigate"):
                w = getattr(panel, attr, None)
                if w is not None:
                    try:
                        fields[attr] = w.text()
                    except Exception:
                        fields[attr] = None
            for attr in ("checkBox_external_control", "checkBox_server_toggle"):
                w = getattr(panel, attr, None)
                if w is not None:
                    try:
                        fields[attr] = bool(w.isChecked())
                    except Exception:
                        fields[attr] = None
            cmb = getattr(panel, "comboBox_themes", None)
            if cmb is not None:
                try:
                    fields["comboBox_themes"] = cmb.currentText()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            sp = getattr(panel, "spinBox_port", None)
            if sp is not None:
                try:
                    fields["spinBox_port"] = sp.value()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        return self._ok({
            "version": getattr(server, "plugin_version", None),
            "panel": panel is not None,
            "panelVisible": bool(panel is not None and panel.isVisible()),
            "server": {
                "running": server_running,
                "port": port,
                "preferred_port": getattr(server, "preferred_port", None),
                "base_url": (f"http://localhost:{port}"
                             if server_running and port else None),
                "network_url": (server.get_network_url()
                                if server is not None else None),
            },
            "canvas": self._canvas_state(),
            "fields": fields,
            "lastRequestOrigin": getattr(p, "_last_request_origin", None),
        })

    # ---------- パネル ----------

    def openPanel(self):
        """GeoWebViewドックパネルを生成・表示する(冪等、トグルではない)。"""
        p = self._plugin
        if p.panel is None:
            p.toggle_panel()  # 生成+ドック+表示
        else:
            if not p.panel.isVisible():
                p.panel.show()
            try:
                p.panel.raise_()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        panel = p.panel
        if panel is None:
            return self._err("panel creation failed "
                             "(PANEL_AVAILABLE may be False)")
        return self._ok({"visible": bool(panel.isVisible())})

    def closePanel(self):
        """GeoWebViewドックパネルを隠す(インスタンスは保持)。"""
        panel = self._panel()
        if panel is not None:
            try:
                panel.hide()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        return self._ok({"visible": bool(panel is not None
                                         and panel.isVisible())})

    # ---------- HTTPサーバ ----------

    def serverStatus(self, deep=False):
        """HTTPサーバの稼働状態・ポート・URLを返す。

        deep=True で check_external_access(ファイアウォール確認含む)を
        実行する(数秒かかる場合あり)。
        """
        server = self._server()
        if server is None:
            return self._err("server_manager not initialized")
        running = server.is_server_running()
        port = server.get_server_port()
        out = {
            "running": running,
            "port": port,
            "preferred_port": getattr(server, "preferred_port", None),
            "localhost_url": (f"http://localhost:{port}" if port else None),
            "network_url": server.get_network_url(),
        }
        if deep:
            try:
                out["diagnostics"] = _jsonable(server.check_external_access())
            except Exception as e:
                out["diagnostics_error"] = str(e)
        return self._ok(out)

    def startServer(self, port=None):
        """HTTPサーバを起動する。port指定時はそのポートを優先する。"""
        server = self._server()
        if server is None:
            return self._err("server_manager not initialized")
        if port is not None:
            try:
                port = int(port)
            except Exception:
                return self._err(f"invalid port: {port!r}")
            if not (1 <= port <= 65535):
                return self._err(f"port out of range: {port}")
            server.preferred_port = port
        if server.is_server_running():
            cur = server.get_server_port()
            if port is None or cur == port:
                return self._ok({"running": True, "port": cur,
                                 "already_running": True})
            # 別ポート指定: 再起動(確認ダイアログ無し)
            server.stop_http_server()
        server.start_http_server()
        self._update_panel_status()
        if not server.is_server_running():
            return self._err("server failed to start "
                             f"(preferred_port={server.preferred_port})")
        return self._ok({"running": True,
                         "port": server.get_server_port(),
                         "url": (server.get_network_url() or
                                 f"http://localhost:{server.get_server_port()}"),
                         "localhost_url":
                             f"http://localhost:{server.get_server_port()}",
                         "network_url": server.get_network_url()})

    def stopServer(self):
        """HTTPサーバを停止する。"""
        server = self._server()
        if server is None:
            return self._err("server_manager not initialized")
        server.stop_http_server()
        self._update_panel_status()
        return self._ok({"running": server.is_server_running()})

    def setPort(self, port):
        """優先ポートを設定する。起動中ならそのポートで再起動する。

        パネルの spinBox_port にも反映する(再起動確認ダイアログは出さない)。
        """
        server = self._server()
        if server is None:
            return self._err("server_manager not initialized")
        try:
            port = int(port)
        except Exception:
            return self._err(f"invalid port: {port!r}")
        if not (1 <= port <= 65535):
            return self._err(f"port out of range: {port}")
        server.preferred_port = port
        panel = self._panel()
        if panel is not None:
            sp = getattr(panel, "spinBox_port", None)
            if sp is not None:
                try:
                    sp.blockSignals(True)
                    sp.setValue(port)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                finally:
                    try:
                        sp.blockSignals(False)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
        restarted = False
        if server.is_server_running():
            server.stop_http_server()
            server.start_http_server(port)
            restarted = True
        self._update_panel_status()
        if restarted and not server.is_server_running():
            return self._err(f"server failed to restart on port {port}")
        return self._ok({
            "preferred_port": server.preferred_port,
            "running": server.is_server_running(),
            "port": server.get_server_port(),
            "restarted": restarted,
        })

    def externalControl(self, enabled=None):
        """外部制御モード(HTTP要求で自動ナビゲート)を取得/設定する。

        enabled: True/False で設定、None で現在値のみ返す。パネル必要。
        """
        panel = self._panel()
        if panel is None:
            return self._err("panel not open (call openPanel first)")
        cbx = getattr(panel, "checkBox_external_control", None)
        if cbx is None:
            return self._err("panel has no external control checkbox")
        if enabled is not None:
            try:
                cbx.setChecked(bool(enabled))
            except Exception as e:
                return self._err(f"setChecked failed: {e}")
        return self._ok({"external_control": bool(cbx.isChecked())})

    # ---------- パーマリンク生成 ----------

    def generatePermalink(self, theme=None):
        """現在の地図ビューからパーマリンクURLを生成する。

        theme: マップテーマ名(指定時は theme= パラメータ付与)。
               None/""なら位置のみ。パネルがあれば入力欄・コンボへも反映。
        """
        p = self._plugin
        specific_theme = None
        if theme:
            from qgis.core import QgsProject
            names = list(
                QgsProject.instance().mapThemeCollection().mapThemes() or [])
            if str(theme) not in names:
                return self._err(f"theme not found: {theme!r} "
                                 f"(available: {names})")
            specific_theme = str(theme)
        url = p.generate_permalink(include_theme=bool(specific_theme),
                                   specific_theme=specific_theme)
        panel = self._panel()
        if panel is not None:
            for attr in ("lineEdit_permalink", "lineEdit_navigate"):
                w = getattr(panel, attr, None)
                if w is not None:
                    try:
                        w.setText(url)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
            cmb = getattr(panel, "comboBox_themes", None)
            if cmb is not None and specific_theme:
                try:
                    cmb.blockSignals(True)
                    cmb.setCurrentText(specific_theme)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                finally:
                    try:
                        cmb.blockSignals(False)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
        return self._ok({"url": url, "theme": specific_theme,
                         "canvas": self._canvas_state()})

    def copyPermalink(self):
        """現在のパーマリンクをクリップボードへコピーする(未生成なら生成)。"""
        p = self._plugin
        text = ""
        panel = self._panel()
        if panel is not None:
            w = getattr(panel, "lineEdit_permalink", None)
            if w is not None:
                try:
                    text = (w.text() or "").strip()
                except Exception:
                    text = ""
        if not text:
            text = p.generate_permalink(include_theme=False)
            if panel is not None:
                w = getattr(panel, "lineEdit_permalink", None)
                if w is not None:
                    try:
                        w.setText(text)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
        if not text:
            return self._err("failed to build permalink")
        try:
            from qgis.PyQt.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
        except Exception as e:
            return self._err(f"clipboard setText failed: {e}")
        return self._ok({"copied": text})

    # ---------- ナビゲーション ----------

    def navigate(self, url):
        """パーマリンクURLから地図ビューを移動する(モーダル無し)。

        対応形式:
          - http(s)://…/qgis-map?x=&y=&scale=&crs=&rotation=[&theme=]
          - 旧形式 http(s)://…/wms?…
          - qgis-permalink://<urlencoded JSON>
        失敗時は {"ok": false, "error": ...} を返す(QMessageBoxは出さない)。
        """
        p = self._plugin
        if not url:
            return self._err("url required")
        url = str(url).strip()
        parsed = urllib.parse.urlparse(url)
        lowered = url.lower()

        # qgis-map / wms 内部パーマリンク(スキーム省略も許容)
        if "/qgis-map" in lowered or "qgis-map?" in lowered or (
                parsed.scheme in ("http", "https")
                and "/wms" in (parsed.path or "")):
            target = url if parsed.scheme else "https://" + url
            params = urllib.parse.parse_qs(urllib.parse.urlparse(target).query)
            server = self._server()
            try:
                nav = server._build_navigation_data_from_params(params)
            except Exception as e:
                return self._err(f"cannot parse permalink params: {e}")
            if nav.get("type") == "location":
                p.navigate_from_http(nav["location"])
            elif nav.get("type") == "coordinates":
                p.navigate_to_coordinates(
                    nav.get("x"), nav.get("y"), nav.get("scale"),
                    nav.get("zoom"), nav.get("crs"), nav.get("rotation"),
                    nav.get("theme_info"))
            else:
                return self._err("no navigation parameters in permalink")
            return self._ok({"kind": "permalink", "type": nav.get("type"),
                             "canvas": self._canvas_state()})

        # 従来のカスタムプロトコル形式
        if url.startswith("qgis-permalink://"):
            from qgis.core import (QgsCoordinateReferenceSystem,
                                   QgsRectangle)
            data = json.loads(urllib.parse.unquote(url[17:]))
            crs = QgsCoordinateReferenceSystem(data["crs"])
            extent = QgsRectangle(data["x_min"], data["y_min"],
                                  data["x_max"], data["y_max"])
            canvas = p.iface.mapCanvas()
            canvas.setDestinationCrs(crs)
            canvas.setExtent(extent)
            canvas.refresh()
            return self._ok({"kind": "qgis-permalink",
                             "canvas": self._canvas_state()})

        return self._err("unsupported URL format "
                         "(qgis-map permalink / qgis-permalink://)")

    def navigateTo(self, x=None, y=None, lat=None, lon=None, scale=None,
                   zoom=None, crs=None, rotation=None, theme=None):
        """座標を直接指定して地図ビューを移動する。

        x/y + crs(既定EPSG:3857相当にはしない。crs省略時EPSG:4326)または
        lat/lon(=EPSG:4326)を指定。scale(縮尺分母)優先、無ければzoomから推定、
        両方無ければ現在縮尺を維持。rotationは度。themeはテーマ名。

        bridge_call は位置引数のみのため、第1引数にdictを渡す形式も受ける:
        navigateTo({"lat": 35.68, "lon": 139.69, "scale": 5000})
        """
        p = self._plugin
        if isinstance(x, dict):
            opts = dict(x)
            x = opts.get("x")
            y = opts.get("y")
            lat = opts.get("lat")
            lon = opts.get("lon")
            scale = opts.get("scale", scale)
            zoom = opts.get("zoom", zoom)
            crs = opts.get("crs", crs)
            rotation = opts.get("rotation", rotation)
            theme = opts.get("theme", theme)
        if lat is not None and lon is not None:
            x, y, crs = float(lon), float(lat), "EPSG:4326"
        if x is None or y is None:
            return self._err("x/y or lat/lon required")
        crs = crs or "EPSG:4326"
        p.navigate_to_coordinates(x, y, scale, zoom, crs, rotation, theme)
        return self._ok({"canvas": self._canvas_state()})

    # ---------- テーマ/ブックマーク ----------

    def listThemes(self):
        """マップテーマ一覧・パネルコンボの現在選択を返す。"""
        from qgis.core import QgsProject
        names = sorted(
            QgsProject.instance().mapThemeCollection().mapThemes() or [])
        current = None
        panel = self._panel()
        cmb = getattr(panel, "comboBox_themes", None) if panel else None
        if cmb is not None:
            try:
                txt = cmb.currentText()
                if txt and not txt.startswith("--"):
                    current = txt
            except Exception:  # nosec B110  # 設計上の許容
                pass
        return self._ok({"themes": names, "current": current})

    def applyTheme(self, name):
        """マップテーマをレイヤツリーへ適用し、パネルコンボも同期する。"""
        p = self._plugin
        from qgis.core import QgsProject
        names = list(
            QgsProject.instance().mapThemeCollection().mapThemes() or [])
        if name not in names:
            return self._err(f"theme not found: {name!r} "
                             f"(available: {names})")
        if not p._apply_theme_from_permalink(name):
            return self._err(f"apply_theme failed: {name!r}")
        panel = self._panel()
        cmb = getattr(panel, "comboBox_themes", None) if panel else None
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
        return self._ok({"applied": name})

    def saveTheme(self, name=None, overwrite=False):
        """現在のレイヤツリー状態をマップテーマとして保存する。

        name: テーマ名(dict指定時は {"name": ...} でも可)。
        overwrite: 同名テーマの上書きを許可するか(既定False)。
        """
        if isinstance(name, dict):
            overwrite = bool(name.get("overwrite", overwrite))
            name = name.get("name") or name.get("theme") or ""
        name = (str(name) if name is not None else "").strip()
        if not name:
            return self._err("theme name is empty")

        from qgis.core import QgsProject
        collection = QgsProject.instance().mapThemeCollection()
        if name in collection.mapThemes() and not overwrite:
            return self._err(
                f"theme already exists: {name!r} "
                "(pass overwrite=True to replace)")
        result = self._plugin.save_current_as_theme(name)
        if not result.get("ok"):
            return self._err(f"save theme failed: {result.get('error')}")
        return self._ok({"saved": name,
                         "overwritten": result.get("overwritten", False)})

    def deleteTheme(self, name):
        """マップテーマを削除する。"""
        if isinstance(name, dict):
            name = name.get("name") or name.get("theme") or ""
        name = (str(name) if name is not None else "").strip()
        if not name:
            return self._err("theme name is empty")
        result = self._plugin.delete_theme(name)
        if not result.get("ok"):
            return self._err(result.get("error") or "delete theme failed")
        return self._ok({"deleted": name})

    def listBookmarks(self):
        """プロジェクト/ユーザブックマーク一覧(中心EPSG:3857)を返す。"""
        try:
            items = self._plugin._collect_bookmarks_epsg3857()
        except Exception as e:
            return self._err(f"collect bookmarks failed: {e}")
        return self._ok({"bookmarks": _jsonable(items)})

    # ---------- 外部サービスURL ----------

    def openExternal(self, service):
        """KASUGAI Canvas を指定エンジンで起動する。

        service: KASUGAI Canvas エンジン名
        ("cesium" | "openlayers" | "maplibre" | "leaflet" | "gsimaps"
         | "navara")
        """
        service = str(service or "").strip().lower()
        if service in ("cesium", "openlayers", "maplibre", "leaflet",
                       "gsimaps", "navara"):
            # KASUGAI Canvas: エクスポート・登録・ブラウザ起動まで行う
            return self.kasugaiExport(engine=service, open_app=True)
        return self._err("unknown service: {!r} (cesium/openlayers/"
                         "maplibre/leaflet/gsimaps/navara)".format(service))

    # ---------- KASUGAI Canvas 連携 ----------

    def kasugaiExport(self, output_dir=None, open_app=True,
                      native_formats=True, hidden_as_off=False,
                      embed_gpkg_style=False, emit_themes=True,
                      emit_bookmarks=True, emit_launchers=True,
                      emit_zip=False, engine=None, install=False, route=None,
                      use_existing=False, emit_atlas=True):
        """表示中レイヤをKASUGAI Canvasプロジェクトとして出力・連携する。

        表示中のベクターレイヤを DATA/ へ出力し、.kasc(geojson:/gpkg:/
        geoparquet:/flatgeobuf:/duckdb: 行+style=.qml・3dtiles:・
        xyz:/base:行・cam:行)を生成する。native_formats=True(既定)で
        GPKG/GeoJSON/Parquet/FGB ソースは変換せずそのまま参照
        (ファイルはDATA/へコピー、URLはそのまま記述)、CSV/TSVは
        duckdb:行(lon=/lat=/geom=)、フィルタ付きGPKGは where=付き、
        3D Tilesは3dtiles:行とし、それ以外のベクターのみ
        GeoJSON(EPSG:4326)へ変換する。hidden_as_off=True で非表示レイヤも ``| off`` 付きで
        出力。embed_gpkg_style=True で GPKG レイヤのスタイルを
        layer_styles(useAsDefault)にも保存する(元ファイルへ書き込む)。
        emit_themes=True(既定)でマップテーマを theme: 行として出力
        (テーマがある場合は非表示レイヤも | off で自動出力)。
        emit_bookmarks=True(既定)でQGISブックマーク(プロジェクト+
        アプリケーション)を bookmarks.xml(qgis_bookmarks形式・EPSG:4326
        正規化)として出力し bookmark: 行を書く(Canvas 側が読み込んで
        カメラプリセットに展開する)。
        emit_launchers=True(既定)で .kasc と同じ場所に <engine>.html
        (cesium/maplibre/openlayers/leaflet/gsimaps/navara)と index.html の
        エンジン
        起動ページを出力する。出力フォルダとエンジン(web/ の中身)を
        同じ静的サーバーへアップすれば ?kasc= 経由でサーバレス動作する。
        emit_zip=True で出力一式(.kasc+DATA/等)を kasugai_canvas_<tag>.zip に
        固める(<tag>はCDNチャンネル反映、export_zip_name)。
        Re:Earth geo_suite の qgis: インスペクタ行がこのZIPを
        直接取り込める(/export-data/kasugai_canvas*.zip でも取得可)。
        emit_atlas=True(既定)でアトラス有効な印刷レイアウトを
        fly_geojson: 行+DATA/atlas_*.geojson(各ページ範囲を巡回する
        ルート・座標Zにページを収めるカメラ高)として出力する。
        出力先は output_dir または設定 kasugai_output_path
        (既定: <ドキュメント>/kasugai_canvas_qgis)。
        use_existing=True で再エクスポートせず出力先の既存 .kasc のみを
        使う(パネル「▶ Canvas」ボタン経路)。未出力なら
        {"ok": false, "code": "not_exported"} を返す。

        open_app=True で起動中のKASUGAIローカルサーバ(port 8510)へ
        /api/projects/register で登録し、switchProjectコマンドを送って
        ブラウザで開く。Canvas未起動・未検出でも、インストール済みCanvasの
        web/ が見つかれば geo_webview のHTTPサーバがエンジンHTMLと
        /export-data/ のデータを配信するフォールバックURL(via:'qgis-http')
        を返してブラウザで開く。どちらも無理なら出力のみ行う。
        engine=cesium|openlayers|maplibre|leaflet|gsimaps|navara で起動エンジンを
        指定できる(既定 cesium、URLの ?engine= パラメータ経由)。
        GUIスレッドで全レイヤを逐次エクスポートするため、大量レイヤでは
        数秒ブロックする場合がある。
        """
        from . import kasugai_export
        engine = kasugai_export.normalize_engine(engine) \
            or kasugai_export.DEFAULT_ENGINE
        try:
            srv = self._server()
            port = (srv.get_server_port()
                    if srv and srv.is_server_running() else None)
            # KASUGAI インストール先が登録済みなら projects/<id>/ へ直出力する
            target_dir = output_dir or kasugai_export.preferred_output_dir()
            if use_existing:
                # 再エクスポートせず既存の出力物のみ使う。未出力なら
                # code=not_exported で返し、呼び出し側が「先に
                # エクスポート」を案内する
                found = kasugai_export.existing_export(target_dir)
                if not found:
                    return json.dumps({
                        "ok": False,
                        "code": "not_exported",
                        "error": "no exported project at {0}".format(
                            target_dir),
                        "dir": target_dir,
                    }, ensure_ascii=False)
                result = {"dir": found[0], "kasc": found[1]}
                try:
                    pj = os.path.join(result["dir"], 'project.json')
                    if os.path.isfile(pj):
                        with open(pj, encoding='utf-8') as f:
                            result["title"] = json.load(f).get('title')
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            else:
                # ライブ連携有効時は .kasc に live: 行を出して
                # live.json マニフェストを同梱する
                live_url = None
                try:
                    from . import live_sync as _live_mod
                    srv_live = self._server()
                    live_port = (srv_live.get_server_port() if srv_live
                                 and srv_live.is_server_running() else None)
                    if live_port and _live_mod.live_enabled():
                        live_url = 'http://127.0.0.1:{0}'.format(live_port)
                except Exception:  # nosec B110  # 設計上の許容
                    live_url = None
                result = kasugai_export.export_kasugai_project(
                    self._plugin.iface, out_dir=target_dir or None,
                    native_formats=bool(native_formats),
                    hidden_as_off=bool(hidden_as_off),
                    embed_gpkg_style=bool(embed_gpkg_style),
                    emit_themes=bool(emit_themes),
                    emit_bookmarks=bool(emit_bookmarks),
                    emit_launchers=bool(emit_launchers),
                    emit_zip=bool(emit_zip),
                    emit_atlas=bool(emit_atlas),
                    live_url=live_url)
        except Exception as e:
            return self._err(f"kasugai export failed: {e}")
        out = {
            "dir": result["dir"],
            "kasc": result["kasc"],
            "title": result.get("title"),
            "layers": result.get("layers", []),
            "tiles": result.get("tiles", []),
            "skipped": result.get("skipped", []),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", []),
            "themes": result.get("themes", []),
            "bookmarks": result.get("bookmarks", 0),
            "atlases": result.get("atlases", []),
            "launchers": result.get("launchers", []),
            "zip": result.get("zip"),
            "use_existing": bool(use_existing),
        }
        if not open_app:
            out["registered"] = False
            return self._ok(out)
        # 再生経路の明示指定: 'kasugai'(Canvas登録) / 'local'|'qgis-http'
        # (本サーバ静的配信) / 'hosted'(ホスト版エンジン)。既定 'auto' は
        # kasugai→qgis-http→hosted の3段フォールバック。
        route = str(route or 'auto').strip().lower()
        if route == 'qgis-http':
            route = 'local'
        if route not in ('auto', 'kasugai', 'local', 'hosted'):
            route = 'auto'
        out["route"] = route
        caps = None
        launched_default = False
        if route in ('auto', 'kasugai'):
            caps, launched_default = kasugai_export.ensure_kasugai_running(
                result["kasc"], pump_events=False)
        if not caps and install and route in ('auto', 'kasugai'):
            # 未検出かつ install=True: 配布ZIPを取得・展開してから再試行
            # (ダウンロードのため数十秒ブロックする場合がある)
            try:
                kasugai_export.install_kasugai()
                out["installed"] = True
                caps, launched_default = \
                    kasugai_export.ensure_kasugai_running(
                        result["kasc"], pump_events=False)
            except Exception as e:
                out["installed"] = False
                out["install_error"] = str(e)
        if not caps:
            out["registered"] = False
            # Canvas未起動/未検出のフォールバック: geo_webview のHTTPサーバを
            # 最小配信サーバとして使い、インストール済みCanvasの web/ と
            # /export-data/ 配下の .kasc+DATA/ でエンジンを開く
            try:
                # 旧単一エンジン構成のインストールは ?kasc= 非対応のため
                # <engine>/ の存在まで確認する
                if route in ('auto', 'local') and port and \
                        kasugai_export.find_kasugai_engine_dir(engine):
                    local_url = kasugai_export.build_local_view_url(
                        result["kasc"], engine=engine, port=port)
                    if local_url:
                        out["url"] = local_url
                        out["via"] = "qgis-http"
                        out["note"] = (
                            "kasugai canvas local server not detected; "
                            "served via geo_webview http server "
                            "(installed web/ + export-data).")
                        try:
                            self._open_url(local_url)
                            out["opened"] = True
                        except Exception as e:
                            out["opened"] = False
                            out["open_error"] = str(e)
                        return self._ok(out)
            except Exception:  # nosec B110  # フォールバック失敗は従来挙動へ
                pass
            # 最終フォールバック: ホスト版エンジン(kasugai-canvas-web) +
            # 本サーバの /export-data/ データ配信。Canvas未インストール環境
            # でもブラウザで開ける(要インターネット)
            try:
                hosted_url = (
                    kasugai_export.build_hosted_view_url(
                        result["kasc"], engine=engine, port=port)
                    if route in ('auto', 'hosted') else None)
                if hosted_url:
                    out["url"] = hosted_url
                    out["via"] = "hosted"
                    out["note"] = (
                        "kasugai canvas not detected; opened via hosted "
                        "engine (kasugai-canvas-web) + geo_webview "
                        "export-data.")
                    try:
                        self._open_url(hosted_url)
                        out["opened"] = True
                    except Exception as e:
                        out["opened"] = False
                        out["open_error"] = str(e)
                    return self._ok(out)
            except Exception:  # nosec B110  # フォールバック失敗は従来挙動へ
                pass
            out["note"] = (
                "kasugai canvas local server not detected (port 8510)."
                + (" launched via .kasc file association."
                   if launched_default else
                   " install kasugai canvas or set the install path"
                   " in plugin settings for auto-launch."
                   " install=True downloads and installs it."))
            return self._ok(out)
        reg = kasugai_export.register_kasugai_project(
            result["kasc"], engine=engine)
        out["registered"] = bool(reg.get("ok"))
        if reg.get("ok"):
            out["projectId"] = reg["id"]
            out["url"] = reg["url"]
            out["via"] = "kasugai"
            out["engine"] = engine
            kasugai_export.kasugai_command(
                "switchProject", {"projectId": reg["id"]})
            try:
                self._open_url(reg["url"])
                out["opened"] = True
            except Exception as e:
                out["opened"] = False
                out["open_error"] = str(e)
        else:
            out["register_error"] = reg.get("error")
        return self._ok(out)

    # ---------- 診断 / エンドポイント ----------

    def checkAccess(self):
        """外部アクセス診断(ファイアウォール含む)を実行し結果を返す。

        サーバ未起動なら先に起動してから診断する。数秒かかる場合あり。
        """
        server = self._server()
        if server is None:
            return self._err("server_manager not initialized")
        if not server.is_server_running():
            server.start_http_server()
        try:
            result = server.check_external_access()
        except Exception as e:
            return self._err(f"check_external_access failed: {e}")
        return self._ok({"diagnostics": _jsonable(result)})

    def endpoints(self):
        """HTTPサーバが公開するエンドポイント一覧と基底URLを返す。"""
        server = self._server()
        if server is None:
            return self._err("server_manager not initialized")
        port = server.get_server_port()
        localhost_base = f"http://localhost:{port}" if port else \
            f"http://localhost:{getattr(server, 'preferred_port', 8089)}"
        # 共有前提のためLAN IP優先(localhostへフォールバック)
        base = server.get_network_url() or localhost_base
        eps = [
            {"path": "/kasugai",
             "url": f"{base}/kasugai"
                    "?engine=cesium|openlayers|maplibre|leaflet|gsimaps|navara",
             "description": "KASUGAI Canvasエクスポート・登録・起動"},
            {"path": "/export-data/<rel>",
             "url": f"{base}/export-data/<dir>/kasugai_canvas.kasc",
             "description": "直近エクスポート物(.kasc+DATA/)の配信"},
            {"path": "/present",
             "url": f"{base}/present",
             "description": "QGISキャンバスのウィンドウ共有ページ"},
            {"path": "/present/state",
             "url": f"{base}/present/state",
             "description": "キャンバス状態JSON(追従モード用)"},
            {"path": "/screenshot",
             "url": f"{base}/screenshot",
             "description": "現在のキャンバス表示PNG"},
            {"path": "/received",
             "url": f"{base}/received",
             "description": "受領パーマリンク履歴JSON"},
            {"path": "/live/state",
             "url": f"{base}/live/state",
             "description": "連携状態+キャンバス状態+選択署名JSON"},
            {"path": "/live/layers",
             "url": f"{base}/live/layers",
             "description": "レイヤカタログ(kascタイトル付き)"},
            {"path": "/live/features",
             "url": f"{base}/live/features?layer=<title>&bbox=w,s,e,n",
             "description": "オンデマンド地物配信(GeoJSON)"},
            {"path": "/live/selection",
             "url": f"{base}/live/selection",
             "description": "QGIS側選択地物(GeoJSON)"},
            {"path": "/live/render",
             "url": f"{base}/live/render?bbox=w,s,e,n&w=&h=",
             "description": "4326範囲のマップ描画PNG(QGIS描画フォールバック)"},
        ]
        return self._ok({"running": server.is_server_running(),
                         "port": port, "base_url": base,
                         "localhost_url": localhost_base,
                         "network_url": server.get_network_url(),
                         "endpoints": eps})

    # ---------- 設定 ----------

    def getSettings(self):
        """設定(出力先ディレクトリ・優先ポート)とバージョンを返す。"""
        from qgis.PyQt.QtCore import QSettings
        s = QSettings("GeoWebView", "geo_webview")
        server = self._server()
        from . import kasugai_export
        return self._ok({
            "version": getattr(server, "plugin_version", None),
            "kasugai_output_path": s.value("kasugai_output_path",
                                           "__default__"),
            "kasugai_output_dir": kasugai_export.get_output_dir(),
            "kasugai_install_path": s.value("kasugai_install_path", ""),
            "kasugai_install_dir": kasugai_export.get_kasugai_install_dir(),
            "kasugai_projects_dir": kasugai_export.kasugai_projects_dir(),
            "kasugai_qgis_projects_dir":
                kasugai_export.kasugai_qgis_projects_dir(),
            "kasugai_port": kasugai_export.get_kasugai_port(),
            "kasugai_hosted_channel":
                kasugai_export.get_hosted_channel(),
            "kasugai_hosted_base":
                kasugai_export.hosted_engine_base(),
            "kasugai_engine": s.value("kasugai_engine", "cesium"),
            "mac_auth_enabled": s.value("mac_auth_enabled", "false"),
            "mac_auth_allowed": s.value("mac_auth_allowed", ""),
            "preferred_port": getattr(server, "preferred_port", None),
            "plugin_dir": getattr(self._plugin, "plugin_dir", None),
        })

    def setSettings(self, settings=None):
        """設定を変更する。

        settings(dict) 対応キー:
          kasugai_output_path: KASUGAIエクスポート出力先
              ("__default__" で <ドキュメント>/kasugai_canvas_qgis)
          kasugai_port: KASUGAIローカルサーバのポート(既定8510)
          kasugai_install_path: KASUGAIインストール先
              （設定時は <install>/QGIS_projects/<id>/ へ .kasc+DATA/ を直出力）
          kasugai_hosted_channel: ホスト版エンジンのチャンネル
              (stable/unstable または完全URL。既定 stable)
          port: HTTPサーバ優先ポート(起動中なら再起動)
        """
        from qgis.PyQt.QtCore import QSettings
        settings = dict(settings or {})
        allowed = {"port", "kasugai_output_path", "kasugai_port",
                   "kasugai_install_path", "kasugai_hosted_channel",
                   "kasugai_engine", "mac_auth_enabled", "mac_auth_allowed"}
        unknown = [k for k in settings if k not in allowed]
        if unknown:
            return self._err(f"unknown keys: {unknown} "
                             f"(allowed: {sorted(allowed)})")
        s = QSettings("GeoWebView", "geo_webview")
        applied = {}
        if "kasugai_engine" in settings:
            eng = str(settings["kasugai_engine"]).strip().lower()
            from . import kasugai_export as _ke
            if _ke.normalize_engine(eng) is None:
                return self._err(
                    f"invalid kasugai_engine: {eng!r} "
                    "(cesium/openlayers/maplibre/leaflet/gsimaps/navara)")
            s.setValue("kasugai_engine", _ke.normalize_engine(eng))
            applied["kasugai_engine"] = _ke.normalize_engine(eng)
            panel = self._panel()
            combo = getattr(panel, "comboBox_engine", None) if panel else None
            if combo is not None:
                try:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(
                        max(0, combo.findData(applied["kasugai_engine"])))
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                finally:
                    try:
                        combo.blockSignals(False)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
        for key in ("kasugai_output_path", "kasugai_install_path",
                    "kasugai_hosted_channel", "mac_auth_allowed"):
            if key in settings:
                s.setValue(key, str(settings[key]))
                applied[key] = str(settings[key])
        if "mac_auth_enabled" in settings:
            v = 'true' if bool(settings["mac_auth_enabled"]) else 'false'
            s.setValue("mac_auth_enabled", v)
            applied["mac_auth_enabled"] = bool(settings["mac_auth_enabled"])
            panel = self._panel()
            cb = getattr(panel, "checkBox_mac_auth", None) if panel else None
            if cb is not None:
                try:
                    cb.blockSignals(True)
                    cb.setChecked(applied["mac_auth_enabled"])
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                finally:
                    try:
                        cb.blockSignals(False)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
        if "kasugai_port" in settings:
            try:
                kp = int(settings["kasugai_port"])
                if not (1 <= kp <= 65535):
                    raise ValueError
            except Exception:
                return self._err(
                    f"invalid kasugai_port: {settings['kasugai_port']!r}")
            s.setValue("kasugai_port", str(kp))
            applied["kasugai_port"] = kp
        if "port" in settings:
            r = json.loads(self.setPort(settings["port"]))
            if not r.get("ok"):
                return self._err(r.get("error", "setPort failed"))
            applied["port"] = r.get("preferred_port")
            applied["server_restarted"] = r.get("restarted")
        return self._ok({"applied": applied})

    # ---------- フォルダ / present / 受領履歴 / MAC認証 ----------

    def openExportFolder(self):
        """KASUGAI出力フォルダをOSのファイルマネージャで開く。"""
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        from . import kasugai_export
        out_dir = kasugai_export.preferred_output_dir()
        os.makedirs(out_dir, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.abspath(out_dir)))
        return self._ok({"dir": out_dir})

    def openPresent(self):
        """キャンバス画面共有ページ(/present)をブラウザで開く。

        共有前提のため返すurlはLAN IP優先(localhostへフォールバック)。
        """
        server = self._server()
        if server is None or not server.is_server_running():
            return self._err("http server is not running "
                             "(call startServer first)")
        port = server.get_server_port() or 8089
        url = server.get_network_url('/present') or \
            f"http://localhost:{port}/present"
        self._open_url(url)
        return self._ok({"url": url,
                         "localhost_url": f"http://localhost:{port}/present",
                         "opened": True})

    def receivedHistory(self):
        """受領パーマリンク履歴(最新10件)を返す。"""
        server = self._server()
        if server is None:
            return self._err("server_manager not initialized")
        entries = list(getattr(server, "received_history", []) or [])
        return self._ok({"received": _jsonable(entries)})

    def addFirewallRule(self, port=None):
        """Windowsファイアウォールに受信ルールを追加する。

        管理者権限が必要。request_elevation=True のため
        UAC昇格ダイアログがユーザーに表示される場合がある。
        """
        server = self._server()
        if server is None:
            return self._err("server_manager not initialized")
        if port is None:
            port = server.get_server_port() or \
                getattr(server, "preferred_port", 8089)
        try:
            port = int(port)
        except Exception:
            return self._err(f"invalid port: {port!r}")
        result = server.add_firewall_rule(port, request_elevation=True)
        if result.get("success"):
            return self._ok({"port": port,
                             "message": result.get("message")})
        out = {"ok": False,
               "error": result.get("message") or "failed",
               "admin_required": bool(result.get("admin_required")),
               "command": result.get("command")}
        return json.dumps(out, ensure_ascii=False)

    def macAuth(self, enabled=None, allowed=None):
        """MACアドレス認証を取得/設定する。"""
        from qgis.PyQt.QtCore import QSettings
        s = QSettings('GeoWebView', 'geo_webview')
        if enabled is not None:
            s.setValue('mac_auth_enabled',
                       'true' if bool(enabled) else 'false')
            panel = self._panel()
            cb = getattr(panel, "checkBox_mac_auth", None) \
                if panel else None
            if cb is not None:
                try:
                    cb.blockSignals(True)
                    cb.setChecked(bool(enabled))
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                finally:
                    try:
                        cb.blockSignals(False)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
        if allowed is not None:
            s.setValue('mac_auth_allowed', str(allowed))
            panel = self._panel()
            le = getattr(panel, "lineEdit_mac_auth", None) \
                if panel else None
            if le is not None:
                try:
                    le.setText(str(allowed))
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        cur_enabled = str(s.value(
            'mac_auth_enabled', 'false')).lower() in ('1', 'true', 'yes', 'on')
        return self._ok({
            "enabled": cur_enabled,
            "allowed": str(s.value('mac_auth_allowed', '') or '')})

    # ---------- ライブ双方向連携 ----------

    def liveSyncStatus(self):
        """ライブ連携の状態を返す。

        enabled(QSettings)/attached(監視中)/running(出力中)/
        pending(保留変更数)/live(サーバ側 rev・直近camera/selection)。
        """
        from . import live_sync as _live_mod
        ctl = getattr(self._plugin, '_live_sync', None)
        st = ctl.status() if ctl is not None else {
            'enabled': _live_mod.live_enabled(), 'attached': False}
        srv = self._server()
        if srv is not None:
            st['live'] = dict(srv._live)
        return self._ok(st)

    def liveSyncStart(self):
        """ライブ双方向連携を有効化して監視を開始する。

        以後レイヤ編集・スタイル変更が最後のエクスポート先へ
        差分出力され、稼働中の Canvas へ liveSync 通知される。
        """
        from qgis.PyQt.QtCore import QSettings
        from . import live_sync as _live_mod
        QSettings('GeoWebView', 'geo_webview').setValue(
            _live_mod.SETTINGS_KEY, True)
        ctl = getattr(self._plugin, '_live_sync', None)
        if ctl is not None:
            ctl.attach()
        return self.liveSyncStatus()

    def liveSyncStop(self):
        """ライブ双方向連携を無効化して監視を停止する。"""
        from qgis.PyQt.QtCore import QSettings
        from . import live_sync as _live_mod
        QSettings('GeoWebView', 'geo_webview').setValue(
            _live_mod.SETTINGS_KEY, False)
        ctl = getattr(self._plugin, '_live_sync', None)
        if ctl is not None:
            ctl.detach()
        return self.liveSyncStatus()

    def liveSyncFlush(self):
        """保留中の変更を即時差分エクスポート+通知する。"""
        ctl = getattr(self._plugin, '_live_sync', None)
        if ctl is None:
            return self._err('live sync controller not initialized')
        return self._ok(ctl.flush())

    def liveWriteback(self, payload=None):
        """Canvas 側の表示/フィルタ/テーマ状態を QGIS プロジェクトへ
        書き戻す(POST /live/writeback と同じ適用ロジック)。

        payload: {"layers": [{"title": "グループ/葉", "visible": bool,
        "where": "<subsetString>"}], "theme": "<マップテーマ名>"}。
        theme は同名のマップテーマがあれば visibility+スタイルを一括
        適用。layers の where はキーがある時のみ subsetString を更新
        (空文字=解除)。適用中は live_sync の再エクスポートを抑止する。
        """
        srv = self._server()
        if srv is None:
            return self._err('server manager not available')
        if payload is not None and not isinstance(payload, dict):
            return self._err('payload must be a dict')
        return self._ok(srv._apply_live_writeback(payload or {}))

    def liveAddFeatures(self, name="", geojson=None, replace=True):
        """GeoJSON をスクラッチ(memory)レイヤとしてプロジェクトへ
        投入する(POST /live/features と同じ適用ロジック)。

        Canvas の作図スケッチや追加 GeoJSON の往復投入用。
        name はレイヤ名かつ置換キー(replace=True で同名の
        kasugai_live_name レイヤを除去して作り直す)。
        geojson は FeatureCollection または Feature のリスト。
        ジオメトリ型混在は型ごとに分割し、レイヤツリー先頭の
        「Canvas」グループへ追加する。
        """
        srv = self._server()
        if srv is None:
            return self._err('server manager not available')
        return self._ok(srv._apply_live_features({
            'name': name, 'geojson': geojson, 'replace': bool(replace)}))
