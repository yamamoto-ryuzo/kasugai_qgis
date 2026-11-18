"""qgis_live_driver内蔵HTTPサーバ。標準ライブラリのみで実装。

MCP (Streamable HTTP) と plain REST を同一ポートで提供し、
MCP非対応のAI/アプリからもHTTP POSTだけでQGISを操作できるようにする。

  POST /mcp              MCP JSON-RPC (initialize/tools/list/tools/call/ping)
  POST /api/cmd          コマンドJSONそのまま dispatch ({"type":"status"} 等)
  POST /api/pyeval       {"code": "..."} → {"result": ...} | {"error": ...}
  POST /api/eval         {"expression": "...", "plugin_id": "<id>"} (viewを持つ
                         プラグインへ転送。plugin_id無しならunsupportedを返す)
  POST /api/screenshot   {"path": "...?", "plugin_id": "...", "target": "..."}
                         → PNGバイナリ (Content-Type: image/png)
  GET  /api/tools        ツール仕様JSON(function calling系AIが読む用)
  GET  /api/status       statusコマンドの結果
  GET  /api/health       {"ok": true, "pid": ...}

実行経路: HTTPワーカースレッド → driver.submit() でメモリキュー投入 →
GUIスレッドの LiveDriver._poll が実行 → 結果を待機して返す。
iface/QgsProject に触れるのは常にGUIスレッドのみ。

plugin_id を指定すると eval/pyeval/screenshot/devreload はそのプラグインの
LiveDriverへ転送される(ハブ経路)。open_plugin/reload_plugin/bridge_call/
status は plugin_id をコマンド引数としてこのドライバが処理する。

バインドは 127.0.0.1 固定、ポート0(空き自動選択)。
pyeval=任意コード実行のためリモート公開は想定しない。

認証(localhost限定運用):
  全エンドポイント(/api/health以外)でセッショントークンの照合を必須とする。
  トークンはドライバ起動時に自動生成され、ユーザ限定ファイル
  (live_dir/token・レジストリJSON)にのみ書き出される。
  ローカルのMCPクライアントはそこから読むだけで使える。
  Authorization: Bearer / X-Api-Key / api-key のいずれかで送る。
  加えて Host が loopback 以外、または Origin が loopback 以外を指す
  リクエストは拒否する(DNSリバインド・ブラウザ経由の対策)。
  QGIS_LIVE_API_KEY を設定するとそのキーも追加で受け付ける。
  QGIS_LIVE_TOOLS    公開するコマンド種別のカンマ区切り(例 "status,screenshot")。
                     /mcp の tools/list・tools/call と /api/* の両方に効く。
                     未設定 or "*" で全許可。
"""

import base64
import hmac
import json
import os
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

TOOLS = [
    {
        "name": "qgis_pyeval",
        "description":
            "Execute arbitrary Python inside the running QGIS process "
            "(GUI thread). Namespace has iface/QgsProject/QgsApplication/"
            "driver. Expressions return their value; statements return "
            "the `result` variable. With plugin_id, runs in that plugin's "
            "driver namespace (its `view` is available).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "plugin_id": {"type": "string"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "qgis_eval",
        "description":
            "Evaluate a JS expression inside a plugin's QWebEngineView "
            "(routed to the plugin's live driver via plugin_id).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string"},
                "plugin_id": {"type": "string"},
            },
            "required": ["expression", "plugin_id"],
        },
    },
    {
        "name": "qgis_screenshot",
        "description":
            "Capture PNG. Default: this driver's map canvas. With plugin_id "
            "routes to that plugin (its view). target: canvas|mainwindow "
            "(driver) or view|window|canvas|mainwindow (WebEngine plugin). "
            "Returns the image.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "plugin_id": {"type": "string"},
                "target": {"type": "string"},
            },
        },
    },
    {
        "name": "qgis_devreload",
        "description":
            "Re-import a plugin's repo-side bridge/ui (WEBENGINE_DEV_SRC) and "
            "reload its page. Routed via plugin_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"plugin_id": {"type": "string"}},
            "required": ["plugin_id"],
        },
    },
    {
        "name": "qgis_status",
        "description":
            "Driver status: pid, http port, loaded plugins and which have "
            "live drivers / views.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "qgis_open_plugin",
        "description":
            "Load+start a QGIS plugin if needed and call its open_dialog().",
        "inputSchema": {
            "type": "object",
            "properties": {"plugin_id": {"type": "string"}},
            "required": ["plugin_id"],
        },
    },
    {
        "name": "qgis_reload_plugin",
        "description":
            "Hot-reload a QGIS plugin (sys.modules cleanup + reloadPlugin + "
            "open_dialog). No QGIS restart needed.",
        "inputSchema": {
            "type": "object",
            "properties": {"plugin_id": {"type": "string"}},
            "required": ["plugin_id"],
        },
    },
    {
        "name": "qgis_bridge_call",
        "description":
            "Call a plugin's bridge method directly in-process (bypasses "
            "WebChannel, so it works even while the JS renderer is starved). "
            "JSON-string results are parsed. plugin_id optional.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plugin_id": {"type": "string"},
                "method": {"type": "string"},
                "args": {"type": "array"},
            },
            "required": ["method"],
        },
    },
    {
        "name": "qgis_describe_plugins",
        "description":
            "Catalog of all loaded QGIS plugins and their AI-callable "
            "capabilities. For plugins exposing a `bridge`, aggregates "
            "each bridge's pluginInfo() (summary / when_to_use / methods "
            "with signatures and examples). Call this first to discover "
            "which plugin to use for a task, then invoke it via "
            "qgis_bridge_call.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "qgis_instruction",
        "description":
            "Manage AI instruction files on this machine. kind=agents "
            "(persistent instructions injected into the assistant's "
            "system prompt) or skills (on-demand procedural docs). "
            "op=list|read|save|delete. save writes the user file "
            "(~/.qgis-live/<kind>/<name>.md); a same-id user file "
            "shadows the bundled one. delete works on user files only. "
            "Format: first '# ' line = title, next non-empty line = "
            "description, rest = body.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "op": {"type": "string",
                       "enum": ["list", "read", "save", "delete"]},
                "kind": {"type": "string",
                         "enum": ["agents", "skills"]},
                "id": {"type": "string",
                       "description": "対象ファイル名(stem)。read/delete用"},
                "name": {"type": "string",
                         "description": "保存ファイル名(stem)。save用"},
                "text": {"type": "string",
                         "description": "ファイル本文(Markdown)。save用"},
            },
            "required": ["op", "kind"],
        },
    },
]

PROTOCOL_VERSION = "2025-03-26"


def _content_text(v):
    return {
        "content": [{
            "type": "text",
            "text": v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2),
        }]
    }


def _content_error(msg):
    return {"content": [{"type": "text", "text": str(msg)}], "isError": True}


class _Handler(BaseHTTPRequestHandler):
    server_version = "qgis-live/0.3"
    protocol_version = "HTTP/1.1"

    _LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

    def log_message(self, *args):
        pass  # QGIS内でstderrは死にやすいので黙らせる

    # ---- 共通ユーティリティ ----

    def _local_req_ok(self):
        """loopback発であることをヘッダで確認(DNSリバインド/ブラウザ対策)。

        Hostがloopback以外を指す、またはOriginがloopback以外の
        サイトを指すリクエストは拒否する。ローカルのWebアプリ
        (localhostオリジン)からの利用は許可する。
        """
        host = self.headers.get("Host", "")
        if host:
            h = host.strip()
            if h.startswith("["):
                h = h[1:h.index("]")] if "]" in h else h.strip("[]")
            else:
                h = h.split(":")[0]
            if h.lower() not in self._LOCAL_HOSTS:
                self._json(403, {"error": "forbidden host"})
                return False
        origin = self.headers.get("Origin")
        if origin is not None:
            try:
                oh = urlparse(origin).hostname or ""
            except Exception:
                oh = ""
            if oh.lower() not in self._LOCAL_HOSTS:
                self._json(403, {"error": "forbidden origin"})
                return False
        return True

    def _auth_ok(self):
        """トークン照合。サーバに1つ以上の有効キーが必須(無ければ全拒否)。"""
        keys = self.server.api_keys
        if not keys:
            return False
        auth = self.headers.get("Authorization", "")
        tok = ""
        if auth.lower().startswith("bearer "):
            tok = auth[7:].strip()
        if not tok:
            tok = (self.headers.get("X-Api-Key")
                   or self.headers.get("api-key") or "")
        return bool(tok) and any(
            hmac.compare_digest(tok, k) for k in keys)

    def _gate(self, path):
        """認証ゲート。/api/health は生存確認用に無認証で通す。"""
        if not self._local_req_ok():
            return False
        if path == "/api/health" or self._auth_ok():
            return True
        self._json(401, {"error": "unauthorized"})
        return False

    def _allowed(self, ctype):
        """QGIS_LIVE_TOOLSによるコマンド種別フィルタ。None=全許可。"""
        allow = self.server.allowed
        return allow is None or ctype in allow

    def _tools(self):
        return [t for t in TOOLS if self._allowed(t["name"][len("qgis_"):])]

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json(self, code, obj, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, cmd, timeout=180.0):
        return self.server.driver.submit(cmd, timeout=timeout)

    # ---- REST ----

    def do_GET(self):
        if not self._gate(self.path):
            return
        if self.path == "/api/health":
            self._json(200, {"ok": True, "pid": os.getpid(),
                             "plugin": "qgis_live_driver"})
        elif self.path == "/api/tools":
            self._json(200, {"tools": self._tools()})
        elif self.path == "/api/status":
            if not self._allowed("status"):
                self._json(403, {"error": "type 'status' not allowed"})
                return
            self._json(200, self._dispatch({"type": "status"}))
        elif self.path == "/mcp":
            # Streamable HTTPのGET(SSEストリーム)は提供しない
            self._json(405, {"error": "method not allowed"},
                       {"Allow": "POST"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        # keep-alive接続で未読ボディが次リクエストを壊さないよう先に読み捨てる
        body = self._read_body()
        if not self._gate(self.path):
            return
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            self._json(400, {"error": f"bad json: {e}"})
            return
        if self.path == "/mcp":
            self._mcp(data)
        elif self.path == "/api/cmd":
            # コマンドJSONをそのままdispatch(type/plugin_id等すべて有効)
            self._api_call(data)
        elif self.path == "/api/pyeval":
            self._api_call({"type": "pyeval", "code": data.get("code", ""),
                            "plugin_id": data.get("plugin_id")})
        elif self.path == "/api/eval":
            self._api_call({"type": "eval",
                            "expression": data.get("expression", ""),
                            "plugin_id": data.get("plugin_id")})
        elif self.path == "/api/screenshot":
            self._api_shot(data.get("path"), data.get("plugin_id"),
                           data.get("target"))
        else:
            self._json(404, {"error": "not found"})

    def _api_call(self, cmd):
        if not self._allowed(cmd.get("type", "")):
            self._json(403, {"error":
                             f"type '{cmd.get('type')}' not allowed"})
            return
        # 未指定のplugin_idは送信しない(省略=ローカル/既定対象の意味を残す)
        if cmd.get("plugin_id") is None:
            cmd.pop("plugin_id", None)
        rep = self._dispatch(cmd)
        self._json(200 if "error" not in rep else 500, rep)

    def _api_shot(self, path, plugin_id=None, target=None):
        if not self._allowed("screenshot"):
            self._json(403, {"error": "type 'screenshot' not allowed"})
            return
        if not path:
            path = os.path.join(tempfile.gettempdir(),
                                f"qgis-shot-{uuid.uuid4().hex[:8]}.png")
        cmd = {"type": "screenshot", "path": path}
        if plugin_id:
            cmd["plugin_id"] = plugin_id
        if target:
            cmd["target"] = target
        rep = self._dispatch(cmd)
        if "error" in rep:
            self._json(500, rep)
            return
        try:
            with open(rep["result"], "rb") as f:
                png = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)
        except Exception as e:
            self._json(500, {"error": repr(e)})

    # ---- MCP (Streamable HTTP, JSON応答のみ) ----

    def _mcp(self, msg):
        method = msg.get("method", "")
        mid = msg.get("id")

        if method.startswith("notifications/"):
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if method == "initialize":
            self._json(200, {
                "jsonrpc": "2.0", "id": mid,
                "result": {
                    "protocolVersion": msg.get("params", {})
                    .get("protocolVersion", PROTOCOL_VERSION),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "qgis-live", "version": "0.2.0"},
                },
            }, {"Mcp-Session-Id": uuid.uuid4().hex})
            return

        if method == "ping":
            self._json(200, {"jsonrpc": "2.0", "id": mid, "result": {}})
            return

        if method == "tools/list":
            self._json(200, {"jsonrpc": "2.0", "id": mid,
                             "result": {"tools": self._tools()}})
            return

        if method == "tools/call":
            params = msg.get("params", {})
            result = self._tool_call(params.get("name"),
                                     params.get("arguments") or {})
            self._json(200, {"jsonrpc": "2.0", "id": mid, "result": result})
            return

        self._json(200, {
            "jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        })

    def _tool_call(self, name, args):
        if not (name or "").startswith("qgis_"):
            return _content_error(f"unknown tool: {name}")
        if not self._allowed(name[len("qgis_"):]):
            return _content_error(
                f"tool '{name}' disabled (QGIS_LIVE_TOOLS)")
        # qgis_<type> → {"type": "<type>", ...args} にそのまま変換する。
        # 新しいコマンド種別を追加してもここは変更不要。
        if name == "qgis_screenshot":
            return self._tool_screenshot(args)
        cmd = {"type": name[len("qgis_"):],
               "id": f"http-{uuid.uuid4().hex[:8]}"}
        cmd.update({k: v for k, v in args.items() if v is not None})
        rep = self._dispatch(cmd)
        if "error" in rep:
            return _content_error(rep["error"])
        return _content_text(rep.get("result"))

    def _tool_screenshot(self, args):
        path = args.get("path") or os.path.join(
            tempfile.gettempdir(), f"qgis-shot-{uuid.uuid4().hex[:8]}.png")
        cmd = {"type": "screenshot", "path": path,
               "id": f"http-{uuid.uuid4().hex[:8]}"}
        if args.get("plugin_id"):
            cmd["plugin_id"] = args["plugin_id"]
        if args.get("target"):
            cmd["target"] = args["target"]
        rep = self._dispatch(cmd)
        if "error" in rep:
            return _content_error(rep["error"])
        try:
            with open(rep["result"], "rb") as f:
                return {"content": [{
                    "type": "image",
                    "data": base64.b64encode(f.read()).decode("ascii"),
                    "mimeType": "image/png",
                }]}
        except Exception as e:
            return _content_error(repr(e))


def start_http(driver, host="127.0.0.1", port=0,
               api_keys=None, allowed=None):
    """HTTPサーバをデーモンスレッドで起動し実ポートを返す。

    api_keys: 受け付けるトークンの集合。必須(空なら全リクエスト拒否)
    allowed: 許可するコマンド種別の集合。None=全許可
    """
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.daemon_threads = True
    httpd.driver = driver
    httpd.api_keys = set(api_keys or ())
    httpd.allowed = allowed
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, httpd.server_address[1]
