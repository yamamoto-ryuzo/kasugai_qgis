# -*- coding: utf-8 -*-
"""geo_webview を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、qgis_live_driver の
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
    SUMMARY = ("QGIS を軽量 OGC サーバ(WMS/WMTS/WFS)として起動し、"
               "地図表示状態(中心/縮尺/回転/テーマ)をパーマリンクURLとして"
               "生成・復元する。OpenLayers/MapLibre のWeb地図HTML生成や"
               "Google Maps/Earth 連携URLの発行も行う。")
    WHEN_TO_USE = [
        "現在の地図ビューを共有できるパーマリンクURLを発行したい",
        "パーマリンク/Google Maps/Earth のURLからQGISの地図を移動したい",
        "座標・縮尺・回転・テーマを指定して地図ビューを直接操作したい",
        "WMS/WMTS/WFS HTTPサーバの起動・停止・ポート変更・状態確認をしたい",
        "外部端末からのアクセス可否(ファイアウォール等)を診断したい",
        "OpenLayers/MapLibre のHTML地図を生成してブラウザで開きたい",
        "Google Maps/Google Earth で現在位置を開くURLを発行したい",
        "プロジェクトのマップテーマ/ブックマークを一覧・適用したい",
        "WFS公開レイヤの一覧を取得したい",
        "表示中レイヤをKASUGAI Canvas用に出力・連携したい",
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
                "WMS/WMTS/WFS HTTPサーバを起動する。port指定時はそのポート"
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
                "現在の地図ビューから /qgis-map パーマリンクURLを生成する。"
                "theme指定でテーマ復元情報を付与。パネルがあれば入力欄にも反映。",
            "example": {"method": "generatePermalink", "args": ["概況図"]},
        },
        "navigate": {
            "description":
                "パーマリンク/Google Maps(@lat,lon,…z|…m)/Google Earth"
                "(@lat,lon,…a,…d,…y)/qgis-permalink:// URLから地図を移動する。"
                "モーダルダイアログは出さず、失敗は ok:false で返す。",
            "example": {"method": "navigate",
                        "args": ["https://www.google.co.jp/maps/@35.68,139.69,16z"]},
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
        "googleMapsUrl": {
            "description":
                "現在の地図中心・縮尺からGoogle Maps URL(@lat,lon,Zz)を返す。",
            "example": {"method": "googleMapsUrl", "args": []},
        },
        "googleEarthUrl": {
            "description":
                "現在の地図中心・縮尺からGoogle Earth Web URLを返す。",
            "example": {"method": "googleEarthUrl", "args": []},
        },
        "maplibreUrl": {
            "description":
                "現在の地図ビューに対応する /maplibre エンドポイントURLを返す"
                "(要サーバ起動)。WFS typenameは含めない。",
            "example": {"method": "maplibreUrl", "args": []},
        },
        "openlayersUrl": {
            "description":
                "OpenLayers HTMLを生成・保存し、静的HTTPサーバで配信する"
                "URLを返す。open_browser=Trueで既定ブラウザでも開く。",
            "example": {"method": "openlayersUrl", "args": [False]},
        },
        "openExternal": {
            "description":
                "外部サービスを既定ブラウザで開く。serviceは google_maps /"
                " google_earth / maplibre / openlayers。",
            "example": {"method": "openExternal", "args": ["maplibre"]},
        },
        "kasugaiExport": {
            "description":
                "表示中レイヤをKASUGAI Canvasプロジェクト(GeoJSON+.qml"
                "スタイル+kasugai_canvas.kasc)として出力する。起動中の"
                "KASUGAIローカルサーバ(port 8510)があれば外部プロジェクト"
                "登録してブラウザで開く。open_app=Falseで出力のみ。",
            "example": {"method": "kasugaiExport", "args": []},
        },
        "wfsLayers": {
            "description":
                "WFS公開対象レイヤ(typename/bbox/crs/色)の一覧を返す。",
            "example": {"method": "wfsLayers", "args": []},
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
                "設定(MapLibre/OpenLayers出力先・優先ポート)とプラグイン"
                "バージョンを返す。",
            "example": {"method": "getSettings", "args": []},
        },
        "setSettings": {
            "description":
                "設定を変更する。対応キー: maplibre_output_path /"
                " openlayers_output_path('__default__'=temp) / port。",
            "example": {"method": "setSettings",
                        "args": [{"maplibre_output_path": "__default__"}]},
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
            panel.update_server_status(port, server.is_server_running())
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _navigation_data_from_canvas(self):
        """現在キャンバスからGoogle系/共通ナビゲーションデータを構築する。"""
        p = self._plugin
        canvas = p.iface.mapCanvas()
        extent = canvas.extent()
        crs = canvas.mapSettings().destinationCrs()
        scale = canvas.scale()
        cx, cy = extent.center().x(), extent.center().y()
        lat, lon = p._convert_to_wgs84(cx, cy, crs.authid())
        if lat is None or lon is None:
            return None, "coordinate transform to WGS84 failed"
        return {
            "type": "coordinates",
            "x": cx, "y": cy,
            "lat": lat, "lon": lon,
            "scale": scale,
            "crs": crs.authid(),
            "zoom": p._estimate_zoom_from_scale(scale),
        }, None

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
                "services": {
                    "wms": server is not None
                    and getattr(server, "wms_service", None) is not None,
                    "wmts": server is not None
                    and getattr(server, "wmts_service", None) is not None,
                    "wfs": server is not None
                    and getattr(server, "wfs_service", None) is not None,
                },
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
                         "url": f"http://localhost:{server.get_server_port()}"})

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
        """パーマリンク/Google URLから地図ビューを移動する(モーダル無し)。

        対応形式:
          - http(s)://…/qgis-map?x=&y=&scale=&crs=&rotation=[&theme=]
          - Google Maps  : @lat,lon,ZZz / @lat,lon,NNNm
          - Google Earth : @lat,lon,AAa,DDd,YYy
          - qgis-permalink://<urlencoded JSON>
        失敗時は {"ok": false, "error": ...} を返す(QMessageBoxは出さない)。
        """
        p = self._plugin
        if not url:
            return self._err("url required")
        url = str(url).strip()
        parsed = urllib.parse.urlparse(url)
        lowered = url.lower()

        # Google Earth Web(@lat,lon,…a,…d[,…y])を最優先で試す
        if "@" in url:
            try:
                pe = p._parse_google_earth_url(url)
            except Exception:
                pe = None
            if pe:
                p.navigate_to_coordinates(
                    pe["lon"], pe["lat"], pe.get("scale"), pe.get("zoom"),
                    "EPSG:4326")
                return self._ok({"kind": "google_earth", "parsed": _jsonable(pe),
                                 "canvas": self._canvas_state()})
            try:
                pm = p._parse_google_maps_at_url(url)
            except Exception:
                pm = None
            if pm:
                width_m = pm.get("map_width_m")
                if width_m:
                    canvas = p.iface.mapCanvas()
                    scale = p._compute_scale_from_map_width_at_center(
                        pm["lat"], pm["lon"], width_m, canvas)
                    if scale:
                        p.navigate_to_coordinates(
                            pm["lon"], pm["lat"], scale, None, "EPSG:4326")
                        return self._ok({"kind": "google_maps",
                                         "map_width_m": width_m,
                                         "scale": scale,
                                         "canvas": self._canvas_state()})
                p.navigate_to_coordinates(
                    pm["lon"], pm["lat"], pm.get("scale"), pm.get("zoom"),
                    "EPSG:4326")
                return self._ok({"kind": "google_maps", "parsed": _jsonable(pm),
                                 "canvas": self._canvas_state()})

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
                         "(qgis-map permalink / Google @-style / "
                         "qgis-permalink://)")

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

    def listBookmarks(self):
        """プロジェクト/ユーザブックマーク一覧(中心EPSG:3857)を返す。"""
        try:
            items = self._plugin._collect_bookmarks_epsg3857()
        except Exception as e:
            return self._err(f"collect bookmarks failed: {e}")
        return self._ok({"bookmarks": _jsonable(items)})

    # ---------- 外部サービスURL ----------

    def googleMapsUrl(self):
        """現在の地図中心・縮尺から Google Maps URL を返す。"""
        p = self._plugin
        nav, err = self._navigation_data_from_canvas()
        if nav is None:
            return self._err(err)
        url = p._build_google_maps_url(nav)
        if not url:
            return self._err("google maps url build failed")
        return self._ok({"url": url})

    def googleEarthUrl(self):
        """現在の地図中心・縮尺から Google Earth Web URL を返す。"""
        p = self._plugin
        nav, err = self._navigation_data_from_canvas()
        if nav is None:
            return self._err(err)
        url = p._build_google_earth_url(nav)
        if not url:
            return self._err("google earth url build failed")
        return self._ok({"url": url})

    def maplibreUrl(self):
        """現在の地図ビューに対応する /maplibre エンドポイントURLを返す。

        サーバ未起動ならエラー(先に startServer を呼ぶ)。
        """
        server = self._server()
        if server is None or not server.is_server_running():
            return self._err("http server not running (call startServer)")
        port = server.get_server_port()
        st = self._canvas_state()
        if st is None:
            return self._err("cannot read canvas state")
        url = (f"http://localhost:{port}/maplibre"
               f"?x={st['center'][0]:.6f}&y={st['center'][1]:.6f}"
               f"&scale={st['scale']:.1f}&crs={st['crs']}"
               f"&rotation={st['rotation']:.2f}")
        return self._ok({"url": url})

    def openlayersUrl(self, open_browser=False):
        """OpenLayers HTMLを生成・保存し、静的配信サーバのURLを返す。

        open_browser=True で既定ブラウザでも開く。出力先は設定
        (openlayers_output_path、既定 temp/qmap_openlayers)に従う。
        """
        import os
        p = self._plugin
        server = self._server()
        if getattr(p, "webmap_generator", None) is None:
            return self._err("webmap_generator not available")
        port = (server.get_server_port() if server is not None else None) \
            or getattr(server, "server_port", 8089) or 8089
        canvas = p.iface.mapCanvas()
        center, scale = canvas.center(), canvas.scale()
        from qgis.core import (QgsCoordinateReferenceSystem,
                               QgsCoordinateTransform, QgsProject)
        canvas_crs = canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        if canvas_crs.authid() != "EPSG:3857":
            tr = QgsCoordinateTransform(canvas_crs, target_crs,
                                        QgsProject.instance())
            c3857 = tr.transform(center)
        else:
            c3857 = center
        navigation_data = {
            "x": c3857.x(), "y": c3857.y(),
            "scale": scale,
            "rotation": canvas.rotation(),
            "crs": "EPSG:3857",
            "bookmarks": p._collect_bookmarks_epsg3857(),
            "themes": p._collect_themes(),
        }
        html_content = p.webmap_generator.generate_wms_based_html_page(
            navigation_data, image_width=800, image_height=600,
            server_port=port)
        from .webmap_generator import save_openlayers_html_to_file
        path = save_openlayers_html_to_file(html_content, port)
        if not path or not os.path.exists(path):
            return self._err(f"failed to save openlayers html: {path}")
        try:
            url = p._serve_static_and_get_url(os.path.dirname(path))
        except Exception as e:
            return self._err(f"static server failed: {e} (file: {path})")
        if open_browser:
            try:
                self._open_url(url)
            except Exception as e:
                return self._err(f"open browser failed: {e} (url: {url})")
        return self._ok({"path": path, "url": url,
                         "opened": bool(open_browser)})

    def openExternal(self, service):
        """外部サービスを既定ブラウザで開く。

        service: "google_maps" | "google_earth" | "maplibre" | "openlayers"
        """
        service = str(service or "").strip().lower()
        if service == "google_maps":
            r = json.loads(self.googleMapsUrl())
        elif service == "google_earth":
            r = json.loads(self.googleEarthUrl())
        elif service == "maplibre":
            r = json.loads(self.maplibreUrl())
        elif service == "openlayers":
            r = json.loads(self.openlayersUrl(open_browser=False))
        else:
            return self._err("unknown service: {!r} (google_maps/"
                             "google_earth/maplibre/openlayers)"
                             .format(service))
        if not r.get("ok"):
            return self._err(r.get("error", "url build failed"))
        url = r["url"]
        try:
            self._open_url(url)
        except Exception as e:
            return self._err(f"open browser failed: {e} (url: {url})")
        out = {"service": service, "url": url}
        if r.get("path"):
            out["path"] = r["path"]
        return self._ok(out)

    # ---------- KASUGAI Canvas 連携 ----------

    def kasugaiExport(self, output_dir=None, open_app=True):
        """表示中レイヤをKASUGAI Canvasプロジェクトとして出力・連携する。

        表示中のベクターレイヤを GeoJSON(EPSG:4326)+.qmlスタイルとして
        DATA/ に書き出し、geojson:行(style=付き)・xyz:行・cam:行を含む
        kasugai_canvas.kasc を生成する。出力先は output_dir または
        設定 kasugai_output_path(既定: <ドキュメント>/kasugai_canvas_qgis)。

        open_app=True で起動中のKASUGAIローカルサーバ(port 8510)へ
        /api/projects/register で登録し、switchProjectコマンドを送って
        ブラウザで開く。未起動なら出力のみ行う。
        GUIスレッドで全レイヤを逐次エクスポートするため、大量レイヤでは
        数秒ブロックする場合がある。
        """
        from . import kasugai_export
        try:
            result = kasugai_export.export_kasugai_project(
                self._plugin.iface, out_dir=output_dir or None)
        except Exception as e:
            return self._err(f"kasugai export failed: {e}")
        out = {
            "dir": result["dir"],
            "kasc": result["kasc"],
            "title": result["title"],
            "layers": result["layers"],
            "tiles": result["tiles"],
            "skipped": result["skipped"],
            "errors": result["errors"],
        }
        if not open_app:
            out["registered"] = False
            return self._ok(out)
        caps = kasugai_export.detect_kasugai()
        if not caps:
            out["registered"] = False
            out["note"] = ("kasugai canvas local server not detected "
                           "(port 8510). open the .kasc file manually.")
            return self._ok(out)
        reg = kasugai_export.register_kasugai_project(result["kasc"])
        out["registered"] = bool(reg.get("ok"))
        if reg.get("ok"):
            out["projectId"] = reg["id"]
            out["url"] = reg["url"]
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

    # ---------- WFSレイヤ / 診断 / エンドポイント ----------

    def wfsLayers(self, only_visible=False):
        """WFS公開対象レイヤ(typename/bbox/crs/色/geom_type)の一覧を返す。"""
        server = self._server()
        if server is None:
            return self._err("server_manager not initialized")
        try:
            items = server._collect_wfs_layers(only_visible=bool(only_visible))
        except Exception as e:
            return self._err(f"collect wfs layers failed: {e}")
        return self._ok({"layers": _jsonable(items)})

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
        base = f"http://localhost:{port}" if port else \
            f"http://localhost:{getattr(server, 'preferred_port', 8089)}"
        eps = [
            {"path": "/wms",
             "url": f"{base}/wms?SERVICE=WMS&REQUEST=GetCapabilities",
             "description": "WMS (GetCapabilities/GetMap → PNG)"},
            {"path": "/qgis-map",
             "url": f"{base}/qgis-map?x=<x>&y=<y>&scale=<s>&crs=<crs>",
             "description": "OpenLayers パーマリンクHTMLページ"},
            {"path": "/maplibre",
             "url": f"{base}/maplibre",
             "description": "MapLibre GL 地図HTMLページ"},
            {"path": "/maplibre-style",
             "url": f"{base}/maplibre-style?typename=<layer>",
             "description": "MapLibre style JSON(WFS注入)"},
            {"path": "/wmts",
             "url": f"{base}/wmts?SERVICE=WMTS&REQUEST=GetCapabilities",
             "description": "WMTSタイル/GetCapabilities"},
            {"path": "/xyz/{z}/{x}/{y}.png",
             "url": f"{base}/xyz/{{z}}/{{x}}/{{y}}.png",
             "description": "XYZタイル(WMTSのエイリアス)"},
            {"path": "/wfs",
             "url": f"{base}/wfs?SERVICE=WFS&REQUEST=GetCapabilities",
             "description": "WFS (GetCapabilities/GetFeature等)"},
            {"path": "/wfs-layers",
             "url": f"{base}/wfs-layers",
             "description": "WFS公開レイヤ一覧JSON"},
        ]
        return self._ok({"running": server.is_server_running(),
                         "port": port, "endpoints": eps})

    # ---------- 設定 ----------

    def getSettings(self):
        """設定(出力先ディレクトリ・優先ポート)とバージョンを返す。"""
        import os
        import tempfile
        from qgis.PyQt.QtCore import QSettings
        s = QSettings("GeoWebView", "geo_webview")
        server = self._server()
        ml = s.value("maplibre_output_path", "__default__")
        ol = s.value("openlayers_output_path", "__default__")
        from . import kasugai_export
        tmp = tempfile.gettempdir()
        return self._ok({
            "version": getattr(server, "plugin_version", None),
            "maplibre_output_path": ml,
            "maplibre_output_dir": (os.path.join(tmp, "qmap_maplibre")
                                    if ml == "__default__" else ml),
            "openlayers_output_path": ol,
            "openlayers_output_dir": (os.path.join(tmp, "qmap_openlayers")
                                      if ol == "__default__" else ol),
            "kasugai_output_path": s.value("kasugai_output_path",
                                           "__default__"),
            "kasugai_output_dir": kasugai_export.get_output_dir(),
            "kasugai_port": kasugai_export.get_kasugai_port(),
            "preferred_port": getattr(server, "preferred_port", None),
            "plugin_dir": getattr(self._plugin, "plugin_dir", None),
        })

    def setSettings(self, settings=None):
        """設定を変更する。

        settings(dict) 対応キー:
          maplibre_output_path / openlayers_output_path:
              出力先ディレクトリ("__default__" で temp に戻す)
          kasugai_output_path: KASUGAIエクスポート出力先
              ("__default__" で <ドキュメント>/kasugai_canvas_qgis)
          kasugai_port: KASUGAIローカルサーバのポート(既定8510)
          port: HTTPサーバ優先ポート(起動中なら再起動)
        """
        from qgis.PyQt.QtCore import QSettings
        settings = dict(settings or {})
        allowed = {"maplibre_output_path", "openlayers_output_path", "port",
                   "kasugai_output_path", "kasugai_port"}
        unknown = [k for k in settings if k not in allowed]
        if unknown:
            return self._err(f"unknown keys: {unknown} "
                             f"(allowed: {sorted(allowed)})")
        s = QSettings("GeoWebView", "geo_webview")
        applied = {}
        for key in ("maplibre_output_path", "openlayers_output_path",
                    "kasugai_output_path"):
            if key in settings:
                s.setValue(key, str(settings[key]))
                applied[key] = str(settings[key])
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
            if key in settings:
                s.setValue(key, str(settings[key]))
                applied[key] = str(settings[key])
        if "port" in settings:
            r = json.loads(self.setPort(settings["port"]))
            if not r.get("ok"):
                return self._err(r.get("error", "setPort failed"))
            applied["port"] = r.get("preferred_port")
            applied["server_restarted"] = r.get("restarted")
        return self._ok({"applied": applied})
