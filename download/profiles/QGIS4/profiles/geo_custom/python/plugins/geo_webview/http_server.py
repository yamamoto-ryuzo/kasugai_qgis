# -*- coding: utf-8 -*-
"""Shared lightweight HTTP utilities for QMapPermalink.

This module provides minimal request/response helpers used by the
plugin's internal socket-based HTTP servers. Keeping these utilities
centralized makes future extensions (middleware, logging, CORS, etc.)
easier.
"""

import threading
import urllib.parse

# ワーカースレッドごとの現在リクエスト Origin(接続ハンドラが記録)
_request_local = threading.local()

# file:// 起動HTML は Origin "null"。ホスト版エンジンは
# kasugai-canvas-web CDN・kasugai_canvas Pages が同一オリジン
_STATIC_ALLOWED_ORIGINS = frozenset((
    'null',
    'https://yamamoto-ryuzo.github.io',
))

# ローカルの別ポートのページからの開発・連携用(同一マシン上の
# プロセスは CORS 無しで読めるため実質的な追加露出にならない)
_LOOPBACK_HOSTNAMES = frozenset(('127.0.0.1', 'localhost', '::1'))


def set_request_origin(origin):
    """接続ハンドラが現在リクエストの Origin ヘッダを記録する。"""
    _request_local.origin = origin or ''


def _custom_hosted_origin():
    """設定のホスト版チャンネル(カスタムURL時)のオリジンを返す。"""
    try:
        from . import kasugai_export
        base = kasugai_export.hosted_engine_base()
    except Exception:  # nosec B110  # 未初期化/QGIS外は追加許可なし
        return ''
    parts = urllib.parse.urlsplit(base)
    if parts.scheme in ('http', 'https') and parts.hostname:
        default = 80 if parts.scheme == 'http' else 443
        port = '' if parts.port in (None, default) else ':{0}'.format(parts.port)
        return '{0}://{1}{2}'.format(parts.scheme, parts.hostname, port)
    return ''


def cors_allowed_origin(origin):
    """CORS で応答を読ませてよいオリジンか判定する。

    許可リスト: file://(null)・ホスト版エンジン(github.io・設定の
    カスタムURL)・ループバック。それ以外のオリジンには ACAO を
    返さず、任意サイトからのローカルデータ読み取りを遮断する。
    """
    if not origin:
        return False
    if origin in _STATIC_ALLOWED_ORIGINS:
        return True
    # prefix 一致だと http://localhost.evil.com 等の偽サブドメインが
    # 通るため、ループバックは urlsplit でホスト名を厳密に抜き出して比較
    try:
        parts = urllib.parse.urlsplit(origin)
        if parts.scheme in ('http', 'https') \
                and parts.hostname in _LOOPBACK_HOSTNAMES:
            return True
    except Exception:  # nosec B110  # 不正な Origin は未許可扱い
        pass
    return origin == _custom_hosted_origin()


def _cors_headers():
    """許可オリジンのときだけ ACAO/Vary 行を返す。

    Expose-Headers は MCP リレー(POST /live/mcp)がブラウザへ
    セッションIDを読み取らせるために必要。
    """
    origin = getattr(_request_local, 'origin', '')
    if cors_allowed_origin(origin):
        return [
            'Access-Control-Allow-Origin: {0}'.format(origin),
            'Access-Control-Expose-Headers: Mcp-Session-Id, '
            'MCP-Protocol-Version',
            'Vary: Origin',
        ]
    return []


def read_http_request(conn, max_size=8192, max_body=4 * 1024 * 1024):
    """Read raw HTTP request bytes from a connected socket.

    ヘッダ終端(\r\n\r\n)まで読み、Content-Length があればボディも
    続けて読む(POST /live/* 用)。ボディ上限は max_body。

    Args:
        conn: socket-like object with recv
        max_size: maximum bytes to read for the header section
            (prevents unbounded memory use)
        max_body: maximum bytes to read for the request body

    Returns:
        bytes: raw request bytes (may be empty on error/timeout)
    """
    try:
        data = b''
        while b'\r\n\r\n' not in data and len(data) < max_size:
            chunk = conn.recv(1024)
            if not chunk:
                break
            data += chunk
        if b'\r\n\r\n' in data:
            head, _, body = data.partition(b'\r\n\r\n')
            want = 0
            for line in head.split(b'\r\n'):
                if line.lower().startswith(b'content-length:'):
                    try:
                        want = int(line.split(b':', 1)[1].strip())
                    except (ValueError, IndexError):
                        want = 0
                    break
            want = max(0, min(want, max_body))
            while len(body) < want:
                chunk = conn.recv(min(65536, want - len(body)))
                if not chunk:
                    break
                body += chunk
            data = head + b'\r\n\r\n' + body
        return data
    except Exception:
        return b''


def send_http_response(conn, status_code, reason, body, content_type="text/plain; charset=utf-8"):
    """Send a minimal HTTP response (text or bytes).

    Args:
        conn: socket-like object with sendall
        status_code: integer HTTP status code
        reason: status reason phrase
        body: str or bytes body
        content_type: Content-Type header value
    """
    try:
        if isinstance(body, str):
            body_bytes = body.encode('utf-8')
        else:
            body_bytes = body or b''

        header_lines = [
            f"HTTP/1.1 {status_code} {reason}",
            f"Content-Length: {len(body_bytes)}",
            f"Content-Type: {content_type}",
        ] + _cors_headers() + [
            "Connection: close",
            "",
            "",
        ]
        header = "\r\n".join(header_lines).encode('utf-8')
        conn.sendall(header + body_bytes)
    except Exception:
        try:
            conn.close()
        except Exception:  # nosec B110  # 設計上の許容
            pass


def send_binary_response(conn, status_code, reason, data, content_type, extra_headers=None):
    """Send a binary HTTP response (images, etc.).

    Args:
        extra_headers: optional list of additional "Name: value" header lines
    """
    try:
        header_lines = [
            f"HTTP/1.1 {status_code} {reason}",
            f"Content-Length: {len(data)}",
            f"Content-Type: {content_type}",
        ] + _cors_headers()
        if extra_headers:
            header_lines.extend(extra_headers)
        header_lines += [
            "Connection: close",
            "",
            "",
        ]
        header = "\r\n".join(header_lines).encode('utf-8')
        conn.sendall(header + data)
    except Exception:
        try:
            conn.close()
        except Exception:  # nosec B110  # 設計上の許容
            pass


def send_options_response(conn):
    """CORS + Private Network Access プリフライト(OPTIONS)応答。

    ホスト版エンジン(https://*.github.io)から http://localhost への
    fetch は Chrome の Private Network Access 対象となり、プリフライト
    応答に Access-Control-Allow-Private-Network が必要。
    許可リスト外のオリジンには CORS ヘッダを返さない。
    """
    try:
        header_lines = ["HTTP/1.1 204 No Content"]
        origin = getattr(_request_local, 'origin', '')
        if cors_allowed_origin(origin):
            header_lines += [
                'Access-Control-Allow-Origin: {0}'.format(origin),
                "Access-Control-Allow-Methods: GET, HEAD, POST, OPTIONS",
                "Access-Control-Allow-Headers: *",
                "Access-Control-Allow-Private-Network: true",
                "Access-Control-Max-Age: 600",
                "Vary: Origin",
            ]
        header_lines += [
            "Content-Length: 0",
            "Connection: close",
            "",
            "",
        ]
        header = "\r\n".join(header_lines).encode('utf-8')
        conn.sendall(header)
    except Exception:
        try:
            conn.close()
        except Exception:  # nosec B110  # 設計上の許容
            pass


def send_head_response(conn, status_code, reason, content_length, content_type):
    """Send headers only for a HEAD request (no body)."""
    try:
        header_lines = [
            f"HTTP/1.1 {status_code} {reason}",
            f"Content-Length: {int(content_length)}",
            f"Content-Type: {content_type}",
        ] + _cors_headers() + [
            "Connection: close",
            "",
            "",
        ]
        header = "\r\n".join(header_lines).encode('utf-8')
        conn.sendall(header)
    except Exception:
        try:
            conn.close()
        except Exception:  # nosec B110  # 設計上の許容
            pass
