# -*- coding: utf-8 -*-
"""geo_webview の HTTP サーバ経由で QGIS Live Driver の MCP を公開するリレー。

背景: KASUGAI Canvas の AI チャットは、ローカルアプリ(:8510)では
/api/qgis-live/mcp リレー経由で Live Driver の MCP ツール
(qgis_pyeval / qgis_bridge_call 等)を利用できるが、CDN ホスト版
(静的配信)には相当するバックエンドが無い。Live Driver の /mcp 自体は
CORS 非対応 + Bearer 必須のためブラウザから直接は叩けない。
geo_webview の内蔵サーバ(:8089)は既に CORS + Private Network Access
対応済みなので、この経路に MCP リレーを載せて CDN からも到達可能にする。

エンドポイント(server_manager.py で登録):
  GET  /live/mcp-discover : 稼働中の Live Driver セッションを検出し、
                            ブラウザが MCP 接続先として登録すべき
                            リレーURL(このサーバ自身の /live/mcp)を返す。
                            トークンは返さない(リレー側で付与するため不要)
  POST /live/mcp          : 検出したセッションの /mcp へ転送する。
                            セッション解決は毎回行うため、QGIS 再起動で
                            ポート・トークンが変わっても自動で追随する

セキュリティ: qgis_pyeval=任意コード実行が乗るため、リレーは TCP ピアが
loopback の接続のみ受け付ける(server_manager 側で is_loopback_peer を
適用)。ブラウザ発の攻撃面は既存の CORS 許可リスト(http_server.py)で
制限される。
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

# 応答ボディ上限(8510 側の MCP_MAX_RESPONSE_BYTES=32MB と同じ)
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

# tools/call は重い処理(Processing 等)があり得るため長めに取る。
# クライアント側(mcp.js)の tools/call タイムアウト 120s より少し長い
RELAY_TIMEOUT_SEC = 125.0

_LOOPBACK_HOSTNAMES = frozenset(('127.0.0.1', 'localhost', '::1'))


def is_loopback_peer(ip):
    """TCP ピアの IP が loopback か判定する。

    pyeval(任意コード実行)を載せる /live/mcp リレーは LAN からの利用を
    想定しないため、呼び出し側はこの判定で同一マシン発に限定する。
    """
    ip = (ip or '').strip()
    if ip.startswith('::ffff:'):  # IPv4-mapped
        ip = ip[len('::ffff:'):]
    return ip in _LOOPBACK_HOSTNAMES


def _registry_dir():
    """Live Driver のセッションレジストリ dir を返す。

    geo_driver はリモート制御 ON 時に ~/.qgis-live/<pid>-<plugin>.json
    (QGIS_LIVE_REGISTRY で変更可)へ {mcp_url, token, pid, plugin_id,
    started} を書き出す。kasugai_canvas サーバ(main.rs)と同じ規約で読む。
    """
    return os.environ.get('QGIS_LIVE_REGISTRY') or os.path.join(
        os.path.expanduser('~'), '.qgis-live')


def driver_sessions():
    """レジストリを走査し Live Driver セッション候補を返す。

    geo_driver 優先・started の新しい順(kasugai_canvas 側の
    qgis_live_sessions() と同じ並び)。
    """
    reg = _registry_dir()
    entries = []
    if os.path.isdir(reg):
        for name in os.listdir(reg):
            if not name.endswith('.json'):
                continue
            try:
                with open(os.path.join(reg, name), 'r',
                          encoding='utf-8') as f:
                    entry = json.load(f)
            except Exception:  # nosec B112  # 壊れたJSONは候補から外すだけ
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get('mcp_url') and entry.get('token'):
                entries.append(entry)

    def _key(e):
        try:
            started = float(e.get('started') or 0)
        except (TypeError, ValueError):
            started = 0.0
        return (e.get('plugin_id') != 'geo_driver', -started)

    entries.sort(key=_key)
    return entries


def _pid_alive(pid):
    """pid のプロセスが生存しているか。

    レジストリには終了済み QGIS の stale エントリが残り得るため、
    HTTP 疎通(ポート毎のタイムアウト待ち)より先にプロセス死で除外する。
    判定不能な環境(非 Windows 等)では True を返し従来通り疎通に任せる。
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0 or os.name != 'nt':
        return True
    try:
        import ctypes
        # PROCESS_QUERY_LIMITED_INFORMATION
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:  # nosec B110  # 判定不能時は疎通確認に委ねる
        return True


def _loopback_base(entry):
    """エントリの mcp_url から loopback 検証済みのベースURLを返す。"""
    mcp_url = str(entry.get('mcp_url') or '')
    if not mcp_url.endswith('/mcp'):
        return ''
    base = mcp_url[:-len('/mcp')]
    try:
        host = urllib.parse.urlsplit(base).hostname or ''
    except Exception:  # nosec B110  # 不正URLは候補外扱い
        return ''
    if host.lower() not in _LOOPBACK_HOSTNAMES:
        return ''
    return base


def pick_session(timeout=2.0):
    """生存確認できた最初のセッションを (base_url, token, entry) で返す。

    各候補の /api/health(無認証)を疎通して生死を確認する。
    """
    for entry in driver_sessions():
        if not _pid_alive(entry.get('pid')):
            continue
        base = _loopback_base(entry)
        if not base:
            continue
        try:
            req = urllib.request.Request(base + '/api/health', method='GET')
            with urllib.request.urlopen(req, timeout=timeout) as res:  # nosec B310  # 直上でloopback URLに限定済み
                if 200 <= res.status < 300:
                    return base, str(entry.get('token') or ''), entry
        except Exception:  # nosec B112  # セッション終了済み等: 次候補へ
            continue
    return None


def discover_payload(self_port):
    """GET /live/mcp-discover の応答JSONを返す。

    ブラウザ側は返された url を MCP サーバ接続先として登録する。
    トークンはリレー内で付与するためここでは返さない。
    """
    found = pick_session()
    if not found:
        return {
            'ok': False,
            'reason': 'no_live_session',
            'sessions': len(driver_sessions()),
        }
    _base, _token, entry = found
    return {
        'ok': True,
        'url': 'http://127.0.0.1:{0}/live/mcp'.format(int(self_port)),
        'pid': entry.get('pid'),
        'plugin_id': entry.get('plugin_id'),
        'sessions': len(driver_sessions()),
    }


def request_header(request_text, name):
    """生のHTTPリクエストテキストから指定ヘッダ値を取り出す。"""
    prefix = name.lower() + ':'
    for line in request_text.split('\r\n'):
        if line.lower().startswith(prefix):
            return line.split(':', 1)[1].strip()
    return ''


def relay(body, content_type='', accept='', session_id='',
          protocol_version='', timeout=RELAY_TIMEOUT_SEC):
    """POST ボディを Live Driver の /mcp へ転送し応答を返す。

    Args:
        body: リクエストボディ(bytes)
        content_type/accept/session_id/protocol_version:
            転送するクライアントヘッダ(未指定時は既定値/送らない)

    Returns:
        (status_code, body_bytes, content_type, mcp_session_id)
        セッション未検出時は (503, ...) を返す。urllib は 202/204 等の
        非200系も HTTPError として投げるため、それも通常応答として扱う。
    """
    found = pick_session()
    if not found:
        return (503,
                'no running QGIS Live Driver session'.encode('utf-8'),
                'text/plain; charset=utf-8', '')
    base, token, _entry = found
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': content_type or 'application/json',
        'Accept': accept or 'application/json, text/event-stream',
    }
    if session_id:
        headers['Mcp-Session-Id'] = session_id
    if protocol_version:
        headers['MCP-Protocol-Version'] = protocol_version
    req = urllib.request.Request(
        base + '/mcp', data=body or b'', headers=headers, method='POST')
    try:
        res_ctx = urllib.request.urlopen(req, timeout=timeout)  # nosec B310  # 直上でloopback URLに限定済み
    except urllib.error.HTTPError as e:
        # 202 Accepted(通知応答)やエラー応答もそのまま転送対象
        res_ctx = e
    except Exception as e:
        return (502,
                'live driver unreachable: {0}'.format(e).encode('utf-8'),
                'text/plain; charset=utf-8', '')
    with res_ctx as res:
        data = res.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            return (502, b'response too large',
                    'text/plain; charset=utf-8', '')
        return (
            res.status,
            data,
            res.headers.get('Content-Type') or 'application/json',
            res.headers.get('Mcp-Session-Id') or '',
        )
