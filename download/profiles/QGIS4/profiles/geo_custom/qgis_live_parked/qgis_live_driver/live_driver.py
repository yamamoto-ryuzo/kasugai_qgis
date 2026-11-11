"""QGISプロセスをファイル経由で外部制御するドライバ(スタンドアロン版)。

WebEngineを持たない任意のプラグイン/QGIS環境で使える制御面だけの実装。
viewを持たないため eval/devreload は未対応(plugin_idでviewを持つ
他プラグインへ転送は可)。代わりに screenshot は iface.mapCanvas() の
地図キャンバスをPNG化する。

環境変数 WEBENGINE_LIVE_DIR 設定時のみ有効。
live dir は WEBENGINE_LIVE_DIR/qgis-<pid>/<plugin_id>/。

コマンド形式(1行1JSON):
  {"id": 1, "type": "pyeval", "code": "iface.activeLayer().name()",
   "token": "<live_dir>/token の内容"}
  {"id": 2, "type": "screenshot", "path": "C:/.../shot.png",
   "token": "..."}  ← 地図キャンバス
  {"id": 3, "type": "status", "token": "..."}
  {"id": 4, "type": "open_plugin", "plugin_id": "<plugin_id>",
   "token": "..."}
  {"id": 5, "type": "reload_plugin", "plugin_id": "<plugin_id>",
   "token": "..."}
  {"id": 6, "type": "bridge_call", "plugin_id": "<plugin_id>",
   "method": "pluginInfo", "args": [], "token": "..."}
  {"id": 7, "type": "describe_plugins", "token": "..."}
   ← 全プラグインのAI利用可能機能カタログ(bridge+pluginInfo集約)

認証: 起動ごとにセッショントークンを生成し live_dir/token と
レジストリJSONに書き出す(どちらもユーザ限定ACL)。ファイル経由
コマンドは token 一致を必須とし、同一マシンの他ユーザや
無関係なプロセスからの書き込みを拒否する。HTTP面も同じ
トークンでBearer認証する(mcp_http.py参照)。

plugin_id を「ルーティング」として使うコマンド(eval/pyeval/screenshot/
devreload)は、plugin_id が他プラグインを指す場合そのプラグインの
LiveDriverに転送され、結果は呼び出し元の results.jsonl に返る
(このドライバが全プラグインの統一制御点になる)。
"""

import hmac
import inspect
import itertools
import json
import os
import queue
import secrets
import threading
import traceback

from qgis.PyQt.QtCore import QTimer

POLL_MS = 200

# id無しコマンド(HTTPの/api/*等)用の自動採番。転送先のevalではcidが
# JS報告との照合キーになるため、Noneのままでは結果報告が全て破棄される
_AUTO_IDS = itertools.count(1)

# plugin_id をルーティングではなくコマンド自身の引数として使う種別。
# これらは常にこのドライバ自身が処理する。
_LOCAL_TYPES = {"status", "open_plugin", "reload_plugin", "bridge_call",
                "describe_plugins", "instruction"}


def _to_jsonable(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, dict):
        return {str(k): _to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_to_jsonable(x) for x in v]
    return repr(v)


def _loaded_plugins():
    import qgis.utils
    return qgis.utils.plugins


def _plugin_metadata(pid, key):
    """プラグインのmetadata.txtから値を読む(失敗時None)。"""
    try:
        import qgis.utils
        v = qgis.utils.pluginMetadata(pid, key)
        return v if v else None
    except Exception:
        return None


def reload_plugin_now(plugin_id):
    """sys.modulesキャッシュを掃除してreloadPluginし、open_dialogを開き直す。

    reload_pluginコマンドとメニューのホットリロード(hot_reload.py)の
    共通処理。呼び出し中のコードフレームはreload後も有効なままなので、
    plugin_id に自分自身(qgis_live_driver)を渡してもよい。
    """
    import sys
    import qgis.utils
    for k in [k for k in list(sys.modules)
              if k == plugin_id or k.startswith(plugin_id + ".")]:
        sys.modules.pop(k, None)
    if plugin_id in qgis.utils.plugins:
        qgis.utils.reloadPlugin(plugin_id)
    else:
        qgis.utils.loadPlugin(plugin_id)
        qgis.utils.startPlugin(plugin_id)
    p = qgis.utils.plugins.get(plugin_id)
    opened = False
    if p is not None and hasattr(p, "open_dialog"):
        p.open_dialog()
        opened = True
    return {
        "loaded": plugin_id in qgis.utils.plugins,
        "opened": opened,
        "plugins": sorted(qgis.utils.plugins.keys()),
    }


class _GenericBridge:
    """bridgeを持たないプラグイン向けの汎用アダプタ。

    repo管理外のサードパーティプラグイン(mmqgis等)は個別bridge.pyを
    持てないため、ドライバ側で最低限の共通制御面を提供する。
    メソッドは専用bridgeと同じくJSON文字列を返す。

    - `pluginInfo` / `status` / `actions` / `trigger` / `run` /
      `openDialog` / `closeDialog`
    - `run`/`trigger` はQTimer.singleShot(0, ...)で非同期発火するため、
      対象がmodalダイアログを開いてもコマンド応答はブロックされない
    """

    _DLG_ATTRS = ("dialog", "dlg", "dockwidget", "dock_widget", "dock")

    def __init__(self, plugin_id, plugin):
        self._pid = plugin_id
        self._plugin = plugin

    @staticmethod
    def _ok(payload=None):
        obj = {"ok": True, "generic": True}
        if payload:
            obj.update(payload)
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def _err(msg):
        return json.dumps({"ok": False, "generic": True, "error": str(msg)},
                          ensure_ascii=False)

    def _find_dialog(self):
        for a in self._DLG_ATTRS:
            w = getattr(self._plugin, a, None)
            if w is not None and hasattr(w, "show"):
                return w
        return None

    def _actions(self):
        from qgis.PyQt.QtWidgets import QAction
        acts = getattr(self._plugin, "actions", None) or []
        return [a for a in acts if isinstance(a, QAction)]

    # ---------- メソッド(JSON文字列を返す) ----------

    def pluginInfo(self):
        """metadata由来の自己記述+汎用メソッド一覧。"""
        return self._ok({
            "id": self._pid,
            "name": _plugin_metadata(self._pid, "name") or self._pid,
            "version": _plugin_metadata(self._pid, "version"),
            "summary": _plugin_metadata(self._pid, "description"),
            "when_to_use": [
                "このプラグインのメニュー/ツールバー操作を実行したい",
                "プラグインのダイアログやドックを開閉したい",
                "専用bridge未搭載プラグインを最低限操作したい",
            ],
            "invoke": {"type": "bridge_call", "plugin_id": self._pid,
                       "method": "<method>", "args": []},
            "methods": [
                {"name": "pluginInfo", "signature": "pluginInfo()",
                 "description": "metadata由来の自己記述を返す"},
                {"name": "status", "signature": "status()",
                 "description": "ダイアログ有無・アクション数等の状態を返す"},
                {"name": "actions", "signature": "actions()",
                 "description": "プラグインのQAction一覧(index/text/enabled)"},
                {"name": "trigger", "signature": "trigger(action)",
                 "description": "アクションを非同期で実行(index/テキスト。"
                                "modalダイアログを開いても応答は即返る)"},
                {"name": "run", "signature": "run()",
                 "description": "plugin.run()を非同期で実行"
                                "(modalダイアログを開いても応答は即返る)"},
                {"name": "openDialog", "signature": "openDialog()",
                 "description": "dialog/dlg/dockwidget属性のウィジェットを"
                                "表示(無ければrun()を非同期実行)"},
                {"name": "closeDialog", "signature": "closeDialog()",
                 "description": "dialog/dlg/dockwidget属性のウィジェットを閉じる"},
            ],
        })

    def status(self):
        """プラグインの状態(ダイアログ有無・アクション数・版)を返す。"""
        dlg = self._find_dialog()
        return self._ok({
            "id": self._pid,
            "version": _plugin_metadata(self._pid, "version"),
            "widget": dlg.__class__.__name__ if dlg is not None else None,
            "widgetVisible": bool(dlg is not None and dlg.isVisible()),
            "actions": len(self._actions()),
            "has_run": callable(getattr(self._plugin, "run", None)),
        })

    def actions(self):
        """プラグインのQAction一覧を返す。"""
        out = []
        for i, a in enumerate(self._actions()):
            try:
                out.append({"index": i, "text": a.text(),
                            "enabled": a.isEnabled(),
                            "checkable": a.isCheckable()})
            except Exception:
                out.append({"index": i, "text": None})
        return self._ok({"actions": out})

    def trigger(self, action):
        """アクションを非同期で実行する(index/テキスト指定)。"""
        acts = self._actions()
        target = None
        if isinstance(action, bool):
            return self._err("invalid action selector")
        if isinstance(action, int):
            if -len(acts) <= action < len(acts):
                target = acts[action]
        else:
            s = str(action or "")
            for a in acts:
                if a.text() == s:
                    target = a
                    break
            if target is None:
                for a in acts:
                    if s and s in a.text():
                        target = a
                        break
        if target is None:
            return self._err(
                f"action not found: {action} "
                f"(have: {[a.text() for a in acts]})")
        QTimer.singleShot(0, target.trigger)
        return self._ok({"triggered": target.text(), "async": True})

    def run(self):
        """plugin.run()を非同期で実行する。"""
        fn = getattr(self._plugin, "run", None)
        if not callable(fn):
            return self._err("plugin has no run()")
        QTimer.singleShot(0, fn)
        return self._ok({"started": True, "async": True})

    def openDialog(self):
        """dialog/dlg/dockwidget属性のウィジェットを表示する。"""
        dlg = self._find_dialog()
        if dlg is not None:
            dlg.show()
            try:
                dlg.raise_()
                dlg.activateWindow()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            return self._ok({"opened": True,
                             "widget": dlg.__class__.__name__})
        fn = getattr(self._plugin, "run", None)
        if callable(fn):
            QTimer.singleShot(0, fn)
            return self._ok({"opened": True, "via": "run", "async": True})
        return self._err("no dialog/dockwidget attribute and no run()")

    def closeDialog(self):
        """dialog/dlg/dockwidget属性のウィジェットを閉じる。"""
        dlg = self._find_dialog()
        if dlg is None:
            return self._err("no dialog/dockwidget attribute")
        try:
            dlg.close()
        except Exception:
            dlg.hide()
        return self._ok({"closed": True,
                         "widget": dlg.__class__.__name__})


def _find_plugin_driver(plugin_id):
    """他プラグインのLiveDriverを返す(無ければNone)。"""
    p = _loaded_plugins().get(plugin_id)
    if p is None:
        return None
    for attr in ("driver", "_live", "live"):
        d = getattr(p, attr, None)
        if d is not None and hasattr(d, "_handle"):
            return d
    return None


class LiveDriver:
    def __init__(self, live_dir, iface):
        self.iface = iface
        self.view = None  # WebEngineなし。ns経由でクライアントがUI有無を判定できる
        self.dir = live_dir
        self.cmd_path = os.path.join(live_dir, "commands.jsonl")
        self.res_path = os.path.join(live_dir, "results.jsonl")
        self.http_port = None  # __init__.py が start_http 後に設定する
        # ドライバ再生成時に過去のコマンドを再実行しないよう末尾までスキップ
        self.offset = os.path.getsize(self.cmd_path) if os.path.exists(self.cmd_path) else 0
        # 全チャネル共通の認証トークン。commands.jsonl は同じマシンの
        # 誰でもappendし得るため、ファイル経由のコマンド受付はこの
        # 一致を必須とする。クライアントは live_dir/token または
        # レジストリJSONから読む(いずれもユーザ限定ACLを目指す)
        self.token = secrets.token_hex(24)
        self._ns = {"iface": iface, "view": None, "driver": self}
        # pyeval内で頻出のQGIS APIを事前importしておく(利便性のため)
        try:
            from qgis.core import QgsProject, QgsApplication
            self._ns.update({"QgsProject": QgsProject,
                             "QgsApplication": QgsApplication})
        except Exception:  # nosec B110  # 設計上の許容
            pass
        # ファイル以外の命令入力(HTTPサーバ等の別スレッドからの投入)。
        # GUIスレッド以外から iface/QgsProject に触れないため、
        # 実行は必ずこのドライバの_poll(GUIスレッド)内で行う
        self._queue = queue.Queue()
        os.makedirs(live_dir, exist_ok=True)
        try:
            with open(os.path.join(live_dir, "token"), "w",
                      encoding="ascii") as f:
                f.write(self.token)
        except Exception:  # nosec B110  # 設計上の許容
            pass

        self.timer = QTimer()
        self.timer.timeout.connect(self._poll)
        self.timer.start(POLL_MS)

    def submit(self, cmd, timeout=180.0):
        """別スレッドからコマンドを投入し、GUIスレッドでの実行結果を待って返す。

        @returns {"id":..., "result": v} or {"id":..., "error": e}
        """
        if cmd.get("id") is None:
            cmd["id"] = f"submit-{next(_AUTO_IDS)}"
        box = {}
        done = threading.Event()
        self._queue.put((cmd, box, done))
        if not done.wait(timeout):
            return {"id": cmd.get("id"), "error": f"submit timeout ({timeout}s)"}
        return box.get("reply", {"id": cmd.get("id"), "error": "no reply"})

    def stop(self):
        self.timer.stop()
        # timer.timeout.connect(bound method) がselfへの参照を保持し、
        # リロードごとにドライバ+QTimerが滞留するためC++側も解放する
        self.timer.deleteLater()

    def _poll(self):
        # メモリキュー(HTTP等)の命令を先に処理
        while True:
            try:
                cmd, box, done = self._queue.get_nowait()
            except queue.Empty:
                break
            # replyが呼ばれた時点で完了。_handleが"async"を返した(eval転送等)は
            # replyが非同期的に後で呼ばれるため、ここでdone.set()しない

            def _reply_once(obj, _box=box, _done=done):
                _box["reply"] = obj
                _done.set()
            try:
                async_pending = self._handle(cmd, reply=_reply_once) == "async"
            except Exception:
                async_pending = False
                box["reply"] = {"id": cmd.get("id"),
                                "error": traceback.format_exc()}
            if not async_pending and not done.is_set():
                done.set()

        if not os.path.exists(self.cmd_path):
            return
        # ファイルが作り直されるとoffsetが実サイズを超えて読み飛ばすため補正
        if os.path.getsize(self.cmd_path) < self.offset:
            self.offset = 0
        with open(self.cmd_path, "r", encoding="utf-8") as f:
            f.seek(self.offset)
            data = f.read()
        # クライアントが書き込み中の部分行を処理するとJSONDecodeErrorで
        # コマンド喪失するため、改行で終端された行だけ処理し、
        # 未完の末尾はoffsetを進めず次ポーリングに残す
        end = data.rfind("\n")
        if end < 0:
            return
        self.offset += end + 1
        for line in data[:end].split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except Exception as e:
                self._reply({"id": None, "error": repr(e)})
                continue
            # ファイル経由コマンドはトークン必須。submit()(HTTP経由)や
            # _forward()(他ドライバ経由)は呼び出し元で認証済みのため対象外
            if not hmac.compare_digest(str(cmd.get("token") or ""),
                                       self.token):
                self._reply({"id": cmd.get("id"), "error": "unauthorized"})
                continue
            try:
                self._handle(cmd)
            except Exception as e:
                self._reply({"id": None, "error": repr(e)})

    def _handle(self, cmd, reply=None):
        reply = reply or self._reply
        cid = cmd.get("id") or f"auto-{next(_AUTO_IDS)}"
        ctype = cmd.get("type", "eval")
        pid = cmd.get("plugin_id")
        # plugin_id が他プラグインを指すコマンドはそのドライバへ転送。
        # 結果は注入したreply経由でこのlive dirのresults.jsonlに返る。
        if pid and pid != __package__ and ctype not in _LOCAL_TYPES:
            return self._forward(cid, pid, cmd, reply)
        if ctype == "pyeval":
            self._pyeval(cid, cmd.get("code", ""), reply)
            return
        if ctype == "screenshot":
            self._screenshot(cid, cmd, reply)
            return
        if ctype == "status":
            reply({"id": cid, "result": self._status()})
            return
        if ctype == "open_plugin":
            self._open_plugin(cid, pid, reply)
            return
        if ctype == "reload_plugin":
            self._reload_plugin(cid, pid, reply)
            return
        if ctype == "bridge_call":
            self._bridge_call(cid, cmd, reply)
            return
        if ctype == "describe_plugins":
            self._describe_plugins(cid, reply)
            return
        if ctype == "instruction":
            self._instruction(cid, cmd, reply)
            return
        reply({
            "id": cid,
            "error": f"type={ctype} unsupported: qgis_live_driver has no WebEngine view. "
            "pass plugin_id of a WebEngine plugin to route "
            "(eval/devreload/screenshot), or use "
            "pyeval/status/open_plugin/reload_plugin/bridge_call/"
            "describe_plugins",
        })

    def _forward(self, cid, pid, cmd, reply):
        """他プラグインのドライバへコマンドを転送し、結果を呼び出し元へ返す。"""
        drv = _find_plugin_driver(pid)
        if drv is None:
            reply({"id": cid, "error":
                   f"plugin '{pid}' has no live driver "
                   f"(loaded: {sorted(_loaded_plugins().keys())})"})
            return
        if "reply" not in inspect.signature(drv._handle).parameters:
            reply({"id": cid, "error":
                   f"plugin '{pid}' driver does not support reply routing; "
                   "redeploy+reload it to update live_driver.py"})
            return
        fwd = {k: v for k, v in cmd.items() if k != "plugin_id"}
        try:
            return drv._handle(fwd, reply=reply)
        except Exception:
            reply({"id": cid, "error": traceback.format_exc()})

    def _instruction(self, cid, cmd, reply):
        """指示書(agents/skills)の操作。qgis_instructionツールの実体。

        GUI依存を持たないファイルI/Oだが、他コマンドと同じく
        GUIスレッドのdispatchで処理する(ai_clientは同プラグイン内)。
        """
        try:
            from . import ai_client
            op = cmd.get("op") or ""
            kind = cmd.get("kind") or ""
            if kind not in ("agents", "skills"):
                reply({"id": cid,
                       "error": f"kind must be agents|skills: {kind!r}"})
                return
            if op == "list":
                reply({"id": cid, "result":
                       ai_client.list_instruction_files(kind)})
            elif op == "read":
                body = ai_client.load_instruction(
                    kind, cmd.get("id") or "")
                if body is None:
                    reply({"id": cid, "error":
                           f"{kind} '{cmd.get('id')}' not found"})
                else:
                    reply({"id": cid, "result": body})
            elif op == "save":
                p = ai_client.save_instruction(
                    kind, cmd.get("name") or "", cmd.get("text") or "")
                reply({"id": cid, "result": f"saved: {p}"})
            elif op == "delete":
                if ai_client.delete_instruction(
                        kind, cmd.get("id") or ""):
                    reply({"id": cid, "result":
                           f"deleted: {kind}/{cmd.get('id')}"})
                else:
                    reply({"id": cid, "error":
                           f"cannot delete {kind} '{cmd.get('id')}' "
                           "(missing or bundled)"})
            else:
                reply({"id": cid,
                       "error": f"op must be list|read|save|delete: {op!r}"})
        except Exception:
            reply({"id": cid, "error": traceback.format_exc()})

    def _status(self):
        """ドライバ自身と全プラグインの状態を返す(生存確認・一覧用)。"""
        plugs = {}
        try:
            for pid, p in _loaded_plugins().items():
                drv = None
                for a in ("driver", "_live", "live"):
                    d = getattr(p, a, None)
                    if d is not None and hasattr(d, "_handle"):
                        drv = d
                        break
                plugs[pid] = {
                    "driver": drv is not None,
                    "view": bool(drv is not None
                                 and getattr(drv, "view", None) is not None),
                    "bridge": getattr(p, "bridge", None) is not None,
                }
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return {
            "pid": os.getpid(),
            "plugin": __package__,
            "live_dir": self.dir,
            "http_port": self.http_port,
            "view": self.view is not None,
            "plugins": plugs,
        }

    def _open_plugin(self, cid, pid, reply):
        """プラグインをload/startし、open_dialogがあれば開く。"""
        if not pid:
            reply({"id": cid, "error": "plugin_id required"})
            return
        try:
            import qgis.utils
            if pid not in qgis.utils.plugins:
                qgis.utils.loadPlugin(pid)
                qgis.utils.startPlugin(pid)
            p = qgis.utils.plugins.get(pid)
            opened = False
            if p is not None and hasattr(p, "open_dialog"):
                p.open_dialog()
                opened = True
            reply({"id": cid, "result": {
                "loaded": pid in qgis.utils.plugins,
                "opened": opened,
                "plugins": sorted(qgis.utils.plugins.keys()),
            }})
        except Exception:
            reply({"id": cid, "error": traceback.format_exc()})

    def _reload_plugin(self, cid, pid, reply):
        """sys.modulesキャッシュを掃除してreloadPluginし、ダイアログを開き直す。

        自分自身(qgis_live_driver)のreloadも可能: 実行中はこのドライバが
        unload→再生成されるが、呼び出し中のコードフレームは有効なままなので
        reload完了後に結果をresults.jsonlへ書き込める。
        """
        if not pid:
            reply({"id": cid, "error": "plugin_id required"})
            return
        try:
            reply({"id": cid, "result": reload_plugin_now(pid)})
        except Exception:
            reply({"id": cid, "error": traceback.format_exc()})

    def _bridge_call(self, cid, cmd, reply):
        """プラグインのbridgeオブジェクトのメソッドをプロセス内で直接呼ぶ。

        JSのBridgeClient.callJsonと違いWebChannelを経由しないため、
        レンダラー飢餓中でもbridgeメソッドを検証できる。
        bridgeメソッドがJSON文字列を返す慣例に合わせ、パース可能なら
        構造化して返す。plugin_id省略時はbridgeを持つ最初のプラグイン。
        """
        pid = cmd.get("plugin_id")
        method = cmd.get("method")
        args = cmd.get("args") or []
        try:
            plugins = _loaded_plugins()
            target = plugins.get(pid) if pid else None
            if target is None:
                target = next(
                    (p for p in plugins.values()
                     if getattr(p, "bridge", None) is not None), None)
            if target is None:
                reply({"id": cid, "error":
                       f"plugin '{pid}' not loaded "
                       f"(loaded: {sorted(plugins.keys())})"})
                return
            # 専用bridgeが無いプラグインは汎用アダプタで最低限の制御面を提供
            bridge = getattr(target, "bridge", None)
            if bridge is None:
                gpid = next((k for k, v in plugins.items() if v is target),
                            pid)
                bridge = _GenericBridge(gpid, target)
            fn = getattr(bridge, method, None) if bridge is not None else None
            if not callable(fn):
                reply({"id": cid, "error":
                       f"no bridge method '{method}'. methods: "
                       f"{[m for m in dir(bridge) if not m.startswith('_')] if bridge else 'no bridge'}"})
                return
            res = fn(*args)
            if isinstance(res, str):
                try:
                    res = json.loads(res)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            reply({"id": cid, "result": _to_jsonable(res)})
        except Exception:
            reply({"id": cid, "error": traceback.format_exc()})

    def _describe_plugins(self, cid, reply):
        """AIから利用可能なプラグインのカタログを返す。

        ロード済み全プラグインを列挙し、bridgeを持つものは
        pluginInfo() を呼んで自己記述(id/name/summary/when_to_use/
        methods)を集約する。「どのプラグインをいつどう使うか」を
        AIが発見するための入口。
        """
        try:
            out = []
            for pid, p in sorted(_loaded_plugins().items()):
                entry = {"id": pid}
                bridge = getattr(p, "bridge", None)
                entry["bridge"] = bridge is not None
                if bridge is None:
                    # 汎用アダプタ経由でmetadata由来の自己記述を載せ、
                    # bridge未搭載プラグインもAIが発見・操作できるようにする
                    bridge = _GenericBridge(pid, p)
                    entry["generic"] = True
                if bridge is not None:
                    info = getattr(bridge, "pluginInfo", None)
                    if callable(info):
                        try:
                            res = info()
                            if isinstance(res, str):
                                try:
                                    res = json.loads(res)
                                except Exception:  # nosec B110  # 設計上の許容
                                    pass
                            entry["info"] = _to_jsonable(res)
                        except Exception:
                            entry["info_error"] = traceback.format_exc()
                    else:
                        entry["methods"] = sorted(
                            m for m in dir(bridge)
                            if not m.startswith("_")
                            and callable(getattr(bridge, m)))
                out.append(entry)
            reply({"id": cid, "result": {
                "pid": os.getpid(),
                "plugins": out,
            }})
        except Exception:
            reply({"id": cid, "error": traceback.format_exc()})

    def _screenshot(self, cid, cmd, reply):
        """地図キャンバス(既定)またはメインウィンドウをPNG保存する。"""
        path = cmd.get("path") or os.path.join(self.dir, f"shot-{cid}.png")
        target = cmd.get("target", "canvas")
        try:
            if target == "canvas":
                canvas = self.iface.mapCanvas() if self.iface is not None else None
                if canvas is None:
                    reply({"id": cid, "error": "no map canvas"})
                    return
                canvas.saveAsImage(path)
            elif target in ("mainwindow", "main"):
                if self.iface is None:
                    reply({"id": cid, "error": "no iface"})
                    return
                self.iface.mainWindow().grab().save(path)
            else:
                reply({"id": cid, "error":
                       f"unknown screenshot target: {target} "
                       "(canvas|mainwindow)"})
                return
            reply({"id": cid, "result": path})
        except Exception:
            reply({"id": cid, "error": traceback.format_exc()})

    def _pyeval(self, cid, code, reply=None):
        """QGISプロセス内でPythonを実行する。

        式としてコンパイルできればeval、その結果を返す。文の場合はexecで実行し、
        名前空間の `result` 変数の値を返す(未設定ならNone)。
        同期的に実行するため長いコードはイベントループをブロックする点に注意。
        plugin_id付きで転送された場合、そのプラグインのドライバの
        名前空間(view等)で実行される。
        """
        reply = reply or self._reply
        self._ns.pop("result", None)
        try:
            try:
                code_obj = compile(code, "<pyeval>", "eval")
            except SyntaxError:
                code_obj = compile(code, "<pyeval>", "exec")
            res = eval(code_obj, self._ns)  # nosec B307  # 任意Python実行が本プラグインの主目的
            if res is None:
                res = self._ns.pop("result", None)
            reply({"id": cid, "result": _to_jsonable(res)})
        except Exception:
            reply({"id": cid, "error": traceback.format_exc()})

    def _reply(self, obj):
        os.makedirs(os.path.dirname(self.res_path), exist_ok=True)
        with open(self.res_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
