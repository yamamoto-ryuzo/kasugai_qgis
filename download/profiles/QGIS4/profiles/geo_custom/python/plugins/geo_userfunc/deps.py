# -*- coding: utf-8 -*-
"""geo_userfunc マクロの他プラグイン依存を AST から抽出する。

``plugins['geo_excel'].bridge.run(...)`` のような参照・呼出と、
``context['plugins']['id']`` 経由の参照、
``gb = plugins['x'].bridge`` で束縛した変数経由の呼出を拾う。
QGIS 非依存の純粋ロジック(QGIS 外で単体テスト可能)。
"""

import ast


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_plugins_dict(node):
    """ノードが plugins 辞書(変数/context['plugins']/属性)を指すか。"""
    if isinstance(node, ast.Name):
        return node.id == "plugins"
    if isinstance(node, ast.Subscript):
        return _const_str(node.slice) == "plugins"
    if isinstance(node, ast.Attribute):
        return node.attr == "plugins"
    return False


def _plugin_subscript(node):
    """``plugins['id']`` 形なら plugin id を返す。違えば None。"""
    if isinstance(node, ast.Subscript) and _is_plugins_dict(node.value):
        return _const_str(node.slice)
    return None


def _resolve(node, bindings, depth=0):
    """式が指す (plugin_id, 属性チェーン) を返す。解決不能は None。"""
    if depth > 6:
        return None
    pid = _plugin_subscript(node)
    if pid is not None:
        return (pid, ())
    if isinstance(node, ast.Attribute):
        base = _resolve(node.value, bindings, depth + 1)
        if base is not None:
            return (base[0], base[1] + (node.attr,))
    elif isinstance(node, ast.Name):
        return bindings.get(node.id)
    return None


def extract_plugin_deps(source):
    """ソース中の他プラグイン参照を抽出する。

    戻り値: ``{plugin_id: {"methods": [bridgeメソッド名...]}}``
    methods が空なら参照のみ(呼出未検出または ``.bridge`` 以外の利用)。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    deps = {}      # pid -> set(method)
    bindings = {}  # var name -> (pid, attrs)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            info = _resolve(node.value, bindings)
            if info is not None:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        bindings[t.id] = info
        elif isinstance(node, ast.Call):
            info = _resolve(node.func, bindings)
            if info is not None:
                pid, attrs = info
                method = ".".join(a for a in attrs if a != "bridge")
                deps.setdefault(pid, set()).add(method or "(ref)")
        pid = _plugin_subscript(node)
        if pid is not None:
            deps.setdefault(pid, set())

    return {p: {"methods": sorted(m)} for p, m in sorted(deps.items())}
