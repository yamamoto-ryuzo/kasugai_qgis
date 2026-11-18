# -*- coding: utf-8 -*-
"""geo_userfunc 共有レジストリ。

他プラグインが自分のマクロ/関数を geo_userfunc の管理下に登録するための
窓口。plugin.registry にぶら下がり、GeoSuite共有ツールバーや layer_org
と同じ「共有プリミティブ」パターンで使う。

登録側(plugin)の規約:

    def register_user_functions(self, registry):
        registry.register_macro(
            "my_plugin.my_macro",
            title="My macro",
            description="...",
            callback=self._run_macro,   # callback(context) -> dict|None
            plugin_id="my_plugin",
        )

geo_userfunc が自分から他プラグインを探索する pull 経路
(plugin._discover_plugin_macros が register_user_functions を呼ぶ)と、
他プラグインが initGui で plugins['geo_userfunc'].registry を直接呼ぶ
push 経路の両方を受け付ける。後者は geo_userfunc 未ロード時に
各プラグインが自前メニューへフォールバックするための経路でもある。
"""


class MacroRegistry:
    """登録マクロの保持と実行仲介。plugin.registry として公開。"""

    def __init__(self, iface):
        self.iface = iface
        self._entries = {}      # macro_id -> dict
        self._listeners = []    # 登録/解除時のUI更新フック

    # ---------- 登録(他プラグインから呼ばれる) ----------

    def register_macro(self, macro_id, callback, title=None, description=None,
                       plugin_id=None, needs_selection=False):
        """マクロを登録する。

        callback(context) -> dict|None。context は
        {"iface", "plugins", "layer", "layer_id", "feature_id", "args"}。
        戻り値がdictなら {"ok": bool, ...} としてbridgeに返る。
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._entries[str(macro_id)] = {
            "id": str(macro_id),
            "callback": callback,
            "title": title or str(macro_id),
            "description": description or "",
            "plugin_id": plugin_id,
            "needs_selection": bool(needs_selection),
        }
        self._notify()

    def unregister_plugin(self, plugin_id):
        """指定プラグインの登録を全解除する(そのプラグインのunload用)。"""
        removed = [k for k, v in self._entries.items()
                   if v.get("plugin_id") == plugin_id]
        for k in removed:
            del self._entries[k]
        if removed:
            self._notify()
        return removed

    # ---------- 参照 ----------

    def get(self, macro_id):
        """macro_id 完全一致→サフィックス一致の順で解決する。"""
        s = str(macro_id or "").strip()
        if s in self._entries:
            return self._entries[s]
        for k, v in self._entries.items():
            if k.endswith("." + s) or k == s:
                return v
        return None

    def entries(self):
        return [dict(v) for v in sorted(self._entries.values(),
                                        key=lambda v: v["id"])]

    def describe(self):
        out = []
        for v in self.entries():
            v = dict(v)
            v.pop("callback", None)
            out.append(v)
        return out

    # ---------- 実行 ----------

    def run(self, macro_id, context):
        """登録マクロを実行して結果をdictで返す。"""
        entry = self.get(macro_id)
        if entry is None:
            return {"ok": False,
                    "error": "unknown macro: {0}".format(macro_id)}
        try:
            result = entry["callback"](context)
        except Exception as e:
            import traceback
            return {"ok": False,
                    "error": "{0}\n{1}".format(e, traceback.format_exc(limit=5))}
        if isinstance(result, dict):
            result.setdefault("ok", True)
            return result
        return {"ok": True, "result": result}

    # ---------- 変更通知 ----------

    def on_changed(self, fn):
        """登録内容が変わったとき呼ぶリスナを追加(UI同期用)。"""
        if callable(fn):
            self._listeners.append(fn)

    def _notify(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:  # nosec B110  # 設計上の許容
                pass
