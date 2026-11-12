#!/usr/bin/env python3
"""qgis_live_driver用 MCP stdio ブリッジ(標準ライブラリのみ)。

MCPクライアントがこのスクリプトをspawnするだけで、
稼働中QGISへの遠隔操作がMCPツールとして使える:

    python .../plugins/qgis_live_driver/mcp_stdio.py

動作: stdinの1行1JSON-RPCメッセージを受け、tools/callを
live dir の commands.jsonl へ追記 → results.jsonl の結果を待ち
MCP形式でstdoutへ返す。

接続先は ~/.qgis-live/<pid>-<plugin>.json のレジストリから自動検出
(QGIS側で プラグイン > QGIS Live Driver > Remote Control が
有効になっている必要あり)。
QGIS_LIVE_PLUGIN で対象プラグインを指定できる(既定: qgis_live_driver)。
"""

import base64
import json
import os
import sys
import time

REG_DIR = os.environ.get(
    "QGIS_LIVE_REGISTRY",
    os.path.join(os.path.expanduser("~"), ".qgis-live"),
)
TARGET_PLUGIN = os.environ.get("QGIS_LIVE_PLUGIN", "qgis_live_driver")
TIMEOUT = 120.0
POLL = 0.2

PROTOCOL_VERSION = "2025-03-26"

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

_session = f"mcp{os.getpid()}"
_seq = 0
_live_dir = None
_token = None


def _err(msg):
    sys.stderr.write(f"[mcp_stdio] {msg}\n")
    sys.stderr.flush()


def _entry_token(entry, live_dir):
    """レジストリエントリ or live_dir/token から認証トークンを取り出す。"""
    t = entry.get("token")
    if t:
        return t
    try:
        with open(os.path.join(live_dir, "token"),
                  encoding="ascii") as f:
            return f.read().strip() or None
    except Exception:
        return None


def _find_live_dir():
    """レジストリから稼働中のlive dirを探して応答確認する。

    @returns (live_dir, token) or None
    """
    if not os.path.isdir(REG_DIR):
        return None
    cands = []
    for name in os.listdir(REG_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(REG_DIR, name), encoding="utf-8") as f:
                e = json.load(f)
            if e.get("live_dir"):
                cands.append(e)
        except Exception:  # nosec B110  # 設計上の許容
            pass
    cands.sort(key=lambda e: (
        e.get("plugin_id") != TARGET_PLUGIN, -e.get("started", 0)))
    for e in cands:
        d = e["live_dir"]
        tok = _entry_token(e, d)
        if _probe(d, tok):
            return d, tok
    return None


def _probe(live_dir, token):
    try:
        return _send(live_dir, {"id": f"{_session}-probe",
                                "type": "pyeval", "code": "1"},
                     token=token, timeout=5.0).get("result") == 1
    except Exception:
        return False


def _send(live_dir, cmd, token=None, timeout=TIMEOUT):
    cmd_path = os.path.join(live_dir, "commands.jsonl")
    res_path = os.path.join(live_dir, "results.jsonl")
    if token:
        cmd["token"] = token
    os.makedirs(live_dir, exist_ok=True)
    with open(cmd_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(cmd, ensure_ascii=False) + "\n")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(res_path):
            with open(res_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except Exception:  # nosec B112  # 設計上の許容
                        continue
                    if obj.get("id") == cmd["id"]:
                        return obj
        time.sleep(POLL)
    return {"id": cmd["id"], "error": f"timeout ({timeout}s)"}


def _next_id():
    global _seq
    _seq += 1
    return f"{_session}-{_seq}"


def _resolve():
    global _live_dir, _token
    if _live_dir is None:
        found = _find_live_dir()
        if found:
            _live_dir, _token = found
    return _live_dir is not None


def _tool_call(name, args):
    global _live_dir, _token
    if not _resolve():
        return {"content": [{"type": "text", "text":
                             "no live qgis_live_driver driver "
                             f"(registry: {REG_DIR})"}],
                "isError": True}
    if not (name or "").startswith("qgis_"):
        return {"content": [{"type": "text", "text": f"unknown tool: {name}"}],
                "isError": True}
    # qgis_<type> → {"type": "<type>", ...args} にそのまま変換する。
    # 新しいコマンド種別を追加してもここは変更不要。
    cmd = {"id": _next_id(), "type": name[len("qgis_"):]}
    cmd.update({k: v for k, v in args.items() if v is not None})
    if name == "qgis_screenshot" and not cmd.get("path"):
        import tempfile
        cmd["path"] = os.path.join(
            tempfile.gettempdir(), f"qgis-shot-{_seq}.png")
    rep = _send(_live_dir, cmd, token=_token)
    # ドライバreload等でトークンが変わった場合は再検出して1回だけやり直す
    if rep.get("error") == "unauthorized":
        _live_dir = _token = None
        if _resolve():
            rep = _send(_live_dir, cmd, token=_token)
    if name == "qgis_screenshot" and "error" not in rep:
        try:
            with open(rep["result"], "rb") as f:
                return {"content": [{
                    "type": "image",
                    "data": base64.b64encode(f.read()).decode("ascii"),
                    "mimeType": "image/png",
                }]}
        except Exception as e:
            rep = {"error": repr(e)}
    if "error" in rep:
        return {"content": [{"type": "text", "text": str(rep["error"])}],
                "isError": True}
    v = rep.get("result")
    return {"content": [{"type": "text", "text":
                         v if isinstance(v, str)
                         else json.dumps(v, ensure_ascii=False, indent=2)}]}


def _handle(msg):
    method = msg.get("method", "")
    mid = msg.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "protocolVersion": msg.get("params", {})
                .get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "qgis-live", "version": "0.2.0"},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        p = msg.get("params", {})
        return {"jsonrpc": "2.0", "id": mid,
                "result": _tool_call(p.get("name"), p.get("arguments") or {})}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601,
                      "message": f"method not found: {method}"}}


def main():
    _err(f"started. registry={REG_DIR} target={TARGET_PLUGIN}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:  # nosec B112  # 設計上の許容
            continue
        if msg.get("method", "").startswith("notifications/") or "id" not in msg:
            continue  # 通知は応答不要
        try:
            resp = _handle(msg)
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": repr(e)}}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
