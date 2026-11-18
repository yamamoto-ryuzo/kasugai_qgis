"""Devin CLI(devin.exe)セッションをQGISプロセス内で非同期実行する。

qgis_devin_* ツール群の実体。2つのエンジンを持つ:

- "acp"(既定): `devin acp` をJSON-RPC(stdio)で駆動。
  IDE認証(credentials.toml の windsurf_api_key)を共有するため
  `devin auth login` 不要。session/load で既存セッション再開も可。
  dispatcher(C:\\devin\\agent\\acp-runner.mjs)と同じ経路。
- "print": `devin -p`(非対話モード)を起動しstdoutをログへ写す。
  `devin auth login` によるCLIログインが必要。

engine="auto" はIDE認証情報があれば acp、無ければ print を選ぶ。

タスクレジストリはプロセスメモリ上に保持するため、QGIS再起動で
追跡情報は消える(プロセス自体は孤児として残り得る点に注意)。
stdlibのみで実装し実QGIS無しでpytest可能。iface等は触らない。
"""

import itertools
import json
import os
import re
import shutil
import subprocess  # nosec B404  # devin.exe起動に必要
import threading
import time
import uuid

# dispatcher(C:\devin\agent)と同じ既定インストール先
_DEFAULT_EXE = os.path.expandvars(
    r"%LOCALAPPDATA%\Programs\Devin\resources\app\extensions"
    r"\windsurf\devin\bin\devin.exe")
_CREDENTIALS = os.path.expandvars(r"%APPDATA%\devin\credentials.toml")

_PERMISSION_MODES = ("normal", "accept-edits", "smart", "dangerous")
_ENGINES = ("auto", "acp", "print")
_AGENTS = ("devin", "copilot")

_TASKS = {}
_LOCK = threading.Lock()
_MAX_TASKS = 32
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class TaskError(Exception):
    """ツールへそのまま返せるユーザー向けエラー。"""


def find_exe(exe=None):
    """devin.exe のパスを解決する。見つからなければ None。

    解決順: 引数 > QGIS_LIVE_DEVIN_EXE > PATH の devin > 既定インストール先。
    """
    for c in (exe, os.environ.get("QGIS_LIVE_DEVIN_EXE"),
              shutil.which("devin"), _DEFAULT_EXE):
        if c and os.path.isfile(c):
            return c
    return None


def _ide_api_key():
    """IDE認証共有用の windsurf_api_key を返す。見つからなければ None。

    解決順: QGIS_LIVE_WINDSURF_API_KEY > WINDSURF_API_KEY >
    credentials.toml。値はログへ書き出さない。
    """
    for k in ("QGIS_LIVE_WINDSURF_API_KEY", "WINDSURF_API_KEY"):
        v = os.environ.get(k)
        if v:
            return v
    try:
        with open(_CREDENTIALS, encoding="utf-8") as f:
            m = re.search(r"windsurf_api_key\s*=\s*['\"]([^'\"]+)",
                          f.read())
        return m.group(1) if m else None
    except OSError:
        return None


def _copilot_exe_spec():
    """copilot CLI を直接spawn可能なargv先頭列を返す。無ければNone。

    npmの .cmd shim は直接spawnできず cmd /c 経由は引数クォートが
    脆弱なので、実exe/winget shim > node+npm-loader.js の順で探す。
    QGISの子プロセスはPATHにnpm dirが無いことがあるため、
    既定インストール先(%APPDATA%\\npm 等)も候補に含める。
    """
    npm_dir = os.path.expandvars(r"%APPDATA%\npm")
    cands = [shutil.which("copilot"),
             os.path.join(npm_dir, "copilot.cmd"),
             os.path.join(npm_dir, "copilot")]
    for w in cands:
        if not w or not os.path.isfile(w):
            continue
        if w.lower().endswith(".exe"):
            return [w]
        loader = os.path.join(
            os.path.dirname(w), "node_modules", "@github",
            "copilot", "npm-loader.js")
        for node in (shutil.which("node"),
                     r"C:\Program Files\nodejs\node.exe"):
            if node and os.path.isfile(node) and \
                    os.path.isfile(loader):
                return [node, loader]
    shim = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Links\copilot.exe")
    if os.path.isfile(shim):
        return [shim]
    return None


def _build_copilot_argv(prompt, session_id=None, model=None,
                        permission_mode="dangerous"):
    """`copilot -p` 非対話実行のコマンドライン。

    権限: permission_mode="dangerous" は環境変数
    COPILOT_ALLOW_ALL=true(全ツール自動許可+作業dir信頼=
    devinの --respect-workspace-trust false 相当)を run() 側で
    立てる。"accept-edits" は --allow-all-tools(ツールは許可するが
    dir信頼はしない)。それ以外は追加フラグ無し(非対話では
    未承認ツールは否認される)。再開は -r <session_id>。
    """
    spec = _copilot_exe_spec()
    if spec is None:
        raise TaskError(
            "copilot CLI not found (install @github/copilot or "
            "set QGIS_LIVE_DEVIN_EXE-style path via exe arg)")
    argv = spec + ["-s", "-p", prompt]
    if permission_mode not in (None, "", "dangerous", "accept-edits"):
        raise TaskError(
            f"copilot permission_mode supports "
            f"('dangerous', 'accept-edits', 'normal'): "
            f"{permission_mode!r}")
    if permission_mode == "accept-edits":
        argv += ["--allow-all-tools"]
    if model:
        argv += ["--model", model]
    if session_id:
        argv += ["-r", session_id]
    return argv


def _resolve_engine(engine, agent="devin"):
    """engine="auto"|"acp"|"print" を実エンジン名に解決する。"""
    if engine in (None, "", "auto"):
        if agent == "copilot":
            return "acp"  # IDE認証不要のため常にacpを優先
        return "acp" if _ide_api_key() else "print"
    if engine not in ("acp", "print"):
        raise TaskError(f"engine must be one of {_ENGINES}: {engine!r}")
    return engine


def _build_argv(exe, prompt_file, session_id=None, model=None,
                permission_mode="dangerous"):
    """`devin -p` 非対話実行のコマンドライン。

    --respect-workspace-trust false: -p は対話プロンプトを出せないため
    未信頼dirで即死するのを防ぐ。--prompt-file: 長文プロンプトを
    コマンドライン長制限なく渡す。
    """
    argv = [exe, "-p", "--respect-workspace-trust", "false"]
    if permission_mode:
        if permission_mode not in _PERMISSION_MODES:
            raise TaskError(
                f"permission_mode must be one of "
                f"{_PERMISSION_MODES}: {permission_mode!r}")
        argv += ["--permission-mode", permission_mode]
    if model:
        argv += ["--model", model]
    if session_id:
        argv += ["-r", session_id]
    argv += ["--prompt-file", prompt_file]
    return argv


def _prune_locked():
    """レジストリ上限超過時、終了済みの古いタスクから捨てる。"""
    if len(_TASKS) <= _MAX_TASKS:
        return
    done = sorted((t for t in _TASKS.values() if t["proc"].poll() is not None),
                  key=lambda t: t["started"])
    for t in done[: len(_TASKS) - _MAX_TASKS]:
        _close(t)
        del _TASKS[t["id"]]


def _close(t):
    for k in ("logf", "errf"):
        f = t.get(k)
        if f is not None:
            try:
                f.close()
            except Exception:  # nosec B110  # 設計上の許容
                pass


def run(prompt, cwd=None, session_id=None, model=None,
        permission_mode="dangerous", exe=None, live_dir=None,
        engine="auto", agent="devin"):
    """エージェントCLIセッションを非同期起動し、タスク情報を返す。

    @param exe: 実行ファイルパス。list/tuple を渡すとそれをそのまま
        argv として使う(テスト用。CLI引数は付かない)
    @param engine: "auto"|"acp"|"print"。autoは使える方を選ぶ
    @param agent: "devin" または "copilot"(GitHub Copilot CLI)
    @returns {"task_id", "pid", "cwd", "log", "engine"}
    """
    prompt = prompt or ""
    if not prompt.strip():
        raise TaskError("prompt is required")
    if agent not in _AGENTS:
        raise TaskError(f"agent must be one of {_AGENTS}: {agent!r}")
    cwd = os.path.abspath(os.path.expanduser(cwd or "~"))
    if not os.path.isdir(cwd):
        raise TaskError(f"cwd is not a directory: {cwd}")

    log_dir = os.path.join(live_dir or os.path.expanduser("~"), agent)
    os.makedirs(log_dir, exist_ok=True)
    task_id = f"{agent}-{uuid.uuid4().hex[:8]}"
    prompt_file = os.path.join(log_dir, f"prompt-{task_id}.txt")
    log = os.path.join(log_dir, f"{task_id}.log")
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(prompt)

    if isinstance(exe, (list, tuple)):
        argv = list(exe)
        eng = engine if engine in ("acp", "print") else "print"
    elif agent == "copilot":
        eng = _resolve_engine(engine, agent)
        if eng == "acp":
            argv = _copilot_argv()
        else:
            argv = _build_copilot_argv(
                prompt, session_id=session_id, model=model,
                permission_mode=permission_mode)
    else:
        exe = find_exe(exe)
        if exe is None:
            raise TaskError(
                "devin.exe not found (set QGIS_LIVE_DEVIN_EXE or "
                "install Devin CLI)")
        eng = _resolve_engine(engine)
        argv = ([exe, "acp"] if eng == "acp"
                else _build_argv(exe, prompt_file, session_id=session_id,
                                 model=model,
                                 permission_mode=permission_mode))

    if eng == "acp" and agent == "devin" and not _ide_api_key():
        raise TaskError(
            "engine 'acp' requires IDE credentials "
            "(windsurf_api_key in %APPDATA%/devin/credentials.toml or "
            "WINDSURF_API_KEY); use engine='print' with `devin auth "
            "login` instead")

    env = None
    if agent == "copilot" and permission_mode == "dangerous":
        # COPILOT_ALLOW_ALL=true は全ツール自動許可に加えて
        # 作業dirも信頼する(devin --respect-workspace-trust false相当)
        env = dict(os.environ, COPILOT_ALLOW_ALL="true")

    try:
        # acp: セッションログはワーカースレッドが単独で書くため
        # buffering=0。stderr(CLIのトレースログ)は別ファイルへ
        # 分離する(同一ファイルへの別appendハンドルは書込みが
        # 競合で欠落する実績あり)
        logf = open(log, "ab", buffering=0 if eng == "acp" else -1)
        errf = open(log[:-4] + ".stderr.log", "ab") \
            if eng == "acp" else None
        try:
            if eng == "acp":
                # JSON-RPCをstdin/stdoutでやり取りするためpipe。
                # stderrは別ファイルへ(stdoutへの混入はRPCを壊す)
                proc = subprocess.Popen(  # nosec B603
                    argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=errf, cwd=cwd, env=env,
                    creationflags=_NO_WINDOW)
            else:
                proc = subprocess.Popen(  # nosec B603
                    argv, stdout=logf, stderr=subprocess.STDOUT,
                    cwd=cwd, env=env, creationflags=_NO_WINDOW)
        except Exception:
            logf.close()
            if errf is not None:
                errf.close()
            raise
    except OSError as e:
        raise TaskError(f"failed to start {agent} cli: {e}")

    t = {"id": task_id, "pid": proc.pid, "argv": argv, "cwd": cwd,
         "prompt": prompt[:500], "prompt_full": prompt, "log": log,
         "stderr_log": (errf.name if errf is not None else None),
         "prompt_file": prompt_file, "started": time.time(),
         "proc": proc, "logf": logf, "errf": errf,
         "session_id": session_id,
         "engine": eng, "agent": agent, "model": model,
         "acp_engine": agent,
         "permission_mode": permission_mode or "dangerous",
         "dangerous": permission_mode == "dangerous", "done": False}
    with _LOCK:
        _TASKS[task_id] = t
        _prune_locked()
    if eng == "acp":
        w = threading.Thread(target=_acp_drive, args=(t,), daemon=True,
                             name=f"acp-{task_id}")
        t["worker"] = w
        w.start()
    return {"task_id": task_id, "pid": proc.pid, "cwd": cwd,
            "log": log, "engine": eng}


def _get(task_id):
    t = _TASKS.get(task_id or "")
    if t is None:
        raise TaskError(f"task not found: {task_id}")
    return t


def _summary(t):
    code = t["proc"].poll()
    return {
        "task_id": t["id"], "pid": t["pid"],
        "state": "running" if code is None and not t.get("done")
                 else ("exited" if code == 0 or t.get("done")
                       else "failed"),
        "exit_code": code,
        "cwd": t["cwd"], "prompt": t["prompt"],
        "session_id": t["session_id"], "engine": t["engine"],
        "agent": t.get("agent", "devin"),
        "elapsed_sec": round(time.time() - t["started"], 1),
        "log": t["log"], "stderr_log": t.get("stderr_log"),
    }


def _tail(path, chars):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > chars:
                f.seek(-chars, os.SEEK_END)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def status(task_id=None, tail=2000):
    """タスク状態を返す。task_id省略時は全タスク一覧。"""
    if not task_id:
        with _LOCK:
            return {"tasks": [_summary(t) for t in _TASKS.values()]}
    t = _get(task_id)
    out = _summary(t)
    out["log_tail"] = _tail(t["log"], max(0, int(tail)))
    if out["state"] != "running":
        _close(t)
    return out


def result(task_id, tail=20000):
    """タスクの出力(ログ末尾)を返す。"""
    t = _get(task_id)
    out = _summary(t)
    out["output"] = _tail(t["log"], max(0, int(tail)))
    if out["state"] != "running":
        _close(t)
    return out


def abort(task_id):
    """実行中タスクをkillする。"""
    t = _get(task_id)
    t["proc"].kill()
    out = _summary(t)
    out["aborted"] = True
    return out


# ---- ACP (Agent Client Protocol) エンジン ----
# `devin.exe acp` はstdio上で行単位JSON-RPCを話す。1スレッドが
# initialize→authenticate→session/new(またはload)→session/promptを
# 順に投げ、応答待ち中も session/update 通知の整形と
# session/request_permission への自動応答を継続する。
# (dispatcher C:\devin\agent\acp-runner.mjs と同じ手順)

def _pick_permission_option(options, dangerous):
    """request_permission の選択肢から応答 optionId を選ぶ。

    dangerous=常にallow系(allow_always優先)。それ以外はallow_once系
    (一度きり許可)を優先し、allow系が無ければ先頭にフォールバック。
    """
    opts = options or []

    def _oid(o):
        return str(o.get("optionId") or o.get("id") or "")

    def _find(*words):
        for o in opts:
            oid, kind = _oid(o), str(o.get("kind") or "")
            if any(w in oid or w == kind for w in words):
                return oid
        return None

    if dangerous:
        hit = _find("allow_always") or _find("allow")
        if hit:
            return hit
    hit = _find("allow_once") or _find("allow")
    if hit:
        return hit
    return _oid(opts[0]) if opts else "allow_once"


def _acp_handle(msg, t, send, out):
    """エージェント→クライアント方向の通知/リクエストを処理する。"""
    method = msg.get("method")
    if method == "session/update":
        u = (msg.get("params") or {}).get("update") or {}
        kind = u.get("sessionUpdate")
        if kind == "agent_message_chunk":
            text = ((u.get("content") or {}).get("text") or "")
            if text:
                out(text, raw=True)
        elif kind == "tool_call":
            args = json.dumps(u.get("rawInput") or u.get("input")
                              or "", ensure_ascii=False)[:160]
            out(f"\n[tool ->] {u.get('title') or u.get('toolName') or 'tool'}"
                f" {args}")
        elif kind == "tool_call_update" and u.get("status") == "failed":
            out(f"[tool x] {u.get('title') or ''}")
        elif kind == "plan":
            out("[plan] "
                + json.dumps(u.get("entries") or "",
                             ensure_ascii=False)[:300])
        # agent_thought_chunk/config_option_update等は省略
    elif msg.get("id") is not None:
        # リクエスト: 許可問い合わせはポリシーで自動応答、
        # 未知のメソッドはmethod not foundを返す(応答無しで止めない)
        if method == "session/request_permission":
            oid = _pick_permission_option(
                (msg.get("params") or {}).get("options"),
                t["dangerous"])
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {
                "outcome": {"outcome": "selected", "optionId": oid}}})
            out(f"\n[permission ->] {oid}")
        else:
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "error": {"code": -32601,
                            "message": f"unsupported: {method}"}})


def _acp_drive(t):
    """ACPセッションをワーカースレッドで駆動する。

    セッションログ(t["logf"])はこのスレッドが単独で書く
    (子stderrは別ファイル)。プロンプト完了(または失敗)で
    t["done"] を立ててプロセスを終了させ、_summary の
    state 判定に委ねる。
    """
    proc = t["proc"]
    seq = itertools.count(1)
    logf = t["logf"]

    def out(s, raw=False):
        data = s.encode("utf-8", "replace")
        logf.write(data if raw else data + b"\n")

    def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        proc.stdin.flush()

    def rpc(method, params):
        mid = next(seq)
        send({"jsonrpc": "2.0", "id": mid,
              "method": method, "params": params})
        while True:
            line = proc.stdout.readline()
            if not line:
                raise TaskError(f"{method}: acp process exited")
            try:
                msg = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                out("[acp] " + line.decode("utf-8", "replace").rstrip())
                continue
            if "method" in msg:
                _acp_handle(msg, t, send, out)
                continue
            if msg.get("id") != mid:
                continue  # 別idの遅延応答(通常来ない)
            if "error" in msg:
                raise TaskError(
                    f"{method}: {json.dumps(msg['error'])[:400]}")
            return msg.get("result") or {}

    try:
        init = rpc("initialize", {
            "protocolVersion": 1,
            "clientInfo": {"name": "qgis-live-driver", "version": "1.0.0"},
            # fs/terminal を true にすると実行がクライアントへ委任される。
            # エージェント側ツールに任せるため false 固定
            "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False},
                "terminal": False}})
        caps = init.get("agentCapabilities") or {}
        if t.get("acp_engine") == "copilot":
            # 認証はCLI側のghログインに委譲。authMethods提示時のみ
            # 先頭方式をbest-effortで試みる(terminal-authを伴い
            # うるため失敗は無視して session/new へ進む)
            m = (init.get("authMethods") or [{}])[0]
            if m.get("id"):
                try:
                    rpc("authenticate", {"methodId": m["id"]})
                except TaskError as e:
                    out(f"[auth skipped] {e}")
        else:
            rpc("authenticate", {"methodId": "devin-browser",
                                 "_meta": {"api_key": _ide_api_key()}})
        sid = t["session_id"]
        if sid and caps.get("loadSession"):
            try:
                rpc("session/load", {"sessionId": sid, "cwd": t["cwd"],
                                     "mcpServers": []})
                out(f"[session resumed] {sid}")
            except TaskError as e:
                out(f"[acp] session/load failed ({e}) -> new session")
                sid = None
        if not sid:
            s = rpc("session/new", {"cwd": t["cwd"], "mcpServers": []})
            sid = s.get("sessionId")
            t["session_id"] = sid
            out(f"[session started] {sid}")
        # permission_mode → ACPモード。ACPのモードIDは
        # accept-edits/smart/ask/plan/bypass。dangerousはbypassへ
        # 写像すると request_permission 自体が来なくなる
        mode = {"dangerous": "bypass", "smart": "smart",
                "accept-edits": "accept-edits"}.get(t["permission_mode"])
        if mode:
            try:
                rpc("session/set_mode",
                    {"sessionId": sid, "modeId": mode})
                out(f"[mode] {mode}")
            except TaskError as e:
                out(f"[mode failed] {mode}: {e}")
        if t["model"]:
            try:
                rpc("session/set_config_option",
                    {"sessionId": sid, "configId": "model",
                     "value": t["model"]})
                out(f"[option] model -> {t['model']}")
            except TaskError as e:
                out(f"[option failed] model: {e}")
        res = rpc("session/prompt", {
            "sessionId": sid,
            "prompt": [{"type": "text", "text": t["prompt_full"]}]})
        out(f"\n[done] {json.dumps(res or {}, ensure_ascii=False)}")
        t["done"] = True
    except Exception as e:  # プロセス側異常もここへ来る
        try:
            out(f"\n[fatal] {e}")
        except OSError:
            pass
        t["error"] = str(e)
    finally:
        # devin側セッション一覧に残さないよう session/close を
        # best-effort通知(応答は待たない)してからプロセスを畳む
        try:
            if t["done"] and t["session_id"]:
                send({"jsonrpc": "2.0", "method": "session/close",
                      "params": {"sessionId": t["session_id"]}})
        except Exception:  # nosec B110  # 設計上の許容
            pass
        try:
            proc.terminate()
        except OSError:
            pass
        _close(t)


def _copilot_argv():
    """`copilot --acp --stdio` のargv(dispatcher copilotSpawnSpec相当)。

    直接spawn可能な spec が取れればそれを使い、無理な場合のみ
    cmd経由で解決させる(引数を含まないのでcmdでも安全)。
    """
    spec = _copilot_exe_spec()
    if spec is not None:
        return spec + ["--acp", "--stdio"]
    if os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", "copilot --acp --stdio"]
    return ["copilot", "--acp", "--stdio"]


class AcpSession:
    """`devin acp` / `copilot --acp --stdio` の常駐セッション
    (チャットプロバイダ用)。

    _acp_drive(ワンショットタスク)と違い、prompt() を呼ぶたびに同じ
    セッションへ session/prompt を送れる。readerスレッドが応答・
    通知・エージェントからのリクエストを多重化するので、send側は
    単純に応答を待てばよい。

    @param mode: ACPモードID(bypass/smart/accept-edits等)。
        permission_mode からの写像は _ACP_MODES を使う
    @param on_update: session/update ごとに呼ぶコールバック
        (readerスレッド上で実行されるため重い処理は避ける)
    """

    _ACP_MODES = {"dangerous": "bypass", "smart": "smart",
                  "accept-edits": "accept-edits"}

    def __init__(self, cwd, exe=None, mcp_servers=None, mode="bypass",
                 on_update=None, session_id=None, model=None,
                 engine="devin"):
        self.cwd = cwd
        self.on_update = on_update
        self.session_id = None
        self.modes = None
        self.config_options = None
        self._proc = None
        self._pending = {}
        self._seq = itertools.count(1)
        self._wlock = threading.Lock()
        self._closed = False
        if isinstance(exe, (list, tuple)):
            argv = list(exe)  # テスト用: argvをそのまま使う
        elif engine == "copilot":
            argv = ([exe, "--acp", "--stdio"] if exe
                    else _copilot_argv())
        else:
            exe = find_exe(exe)
            if exe is None:
                raise TaskError(
                    "devin.exe not found (set QGIS_LIVE_DEVIN_EXE or "
                    "install Devin CLI)")
            argv = [exe, "acp"]
        if engine == "devin" and not _ide_api_key():
            raise TaskError(
                "ACP requires IDE credentials (windsurf_api_key)")
        # devin acp は WINDSURF_EXT_HOST_PID のプロセスを「親」として
        # 監視し、死亡を検出すると自己終了する。IDEターミナル等から
        # 起動されたQGISが IDE再起動済みの陳腐pidを継承していると
        # セッション生成直後に acp が落ちてしまうため、実際の親である
        # 自プロセス(QGIS)を指すよう上書きする
        env = dict(os.environ)
        if env.get("WINDSURF_EXT_HOST_PID"):
            env["WINDSURF_EXT_HOST_PID"] = str(os.getpid())
        try:
            self._proc = subprocess.Popen(  # nosec B603
                argv, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, cwd=cwd, env=env,
                creationflags=_NO_WINDOW)
        except OSError as e:
            raise TaskError(f"failed to start devin acp: {e}")
        self._reader = threading.Thread(
            target=self._read_loop, daemon=True, name="acp-reader")
        self._reader.start()
        try:
            init = self.rpc("initialize", {
                "protocolVersion": 1,
                "clientInfo": {"name": "qgis-live-driver",
                               "version": "1.0.0"},
                "clientCapabilities": {
                    "fs": {"readTextFile": False,
                           "writeTextFile": False},
                    "terminal": False}}, timeout=60.0)
            caps = init.get("agentCapabilities") or {}
            if engine == "devin":
                self.rpc("authenticate", {
                    "methodId": "devin-browser",
                    "_meta": {"api_key": _ide_api_key()}}, timeout=60.0)
            else:
                # copilot: 認証はCLI側のghログインに委譲。
                # authMethods が提示されたら先頭方式を試みるが、
                # copilot-login はterminal-authを伴いうるため
                # 失敗・タイムアウトは無視して session/new へ進む
                # (ghログイン済みなら認証自体が不要)
                m = (init.get("authMethods") or [{}])[0]
                if m.get("id"):
                    try:
                        self.rpc("authenticate", {"methodId": m["id"]},
                                 timeout=15.0)
                    except TaskError:
                        pass
            mcp = list(mcp_servers or [])
            if session_id and caps.get("loadSession"):
                try:
                    s = self.rpc("session/load", {
                        "sessionId": session_id, "cwd": cwd,
                        "mcpServers": mcp}, timeout=60.0)
                    self.session_id = session_id
                except TaskError:
                    session_id = None
            if not self.session_id:
                try:
                    s = self.rpc("session/new", {
                        "cwd": cwd, "mcpServers": mcp}, timeout=60.0)
                except TaskError:
                    if not mcp:
                        raise
                    # MCP定義が原因かもしれないので空で再試行
                    s = self.rpc("session/new", {
                        "cwd": cwd, "mcpServers": []}, timeout=60.0)
                self.session_id = s.get("sessionId")
            self.modes = (s or {}).get("modes")
            self.config_options = (s or {}).get("configOptions")
            if mode:
                try:
                    self.rpc("session/set_mode", {
                        "sessionId": self.session_id,
                        "modeId": mode}, timeout=15.0)
                except TaskError:
                    pass
            if model:
                try:
                    self.rpc("session/set_config_option", {
                        "sessionId": self.session_id,
                        "configId": "model", "value": model},
                        timeout=15.0)
                except TaskError:
                    pass
        except Exception:
            self.close()
            raise

    def _send(self, msg):
        with self._wlock:
            self._proc.stdin.write(
                (json.dumps(msg) + "\n").encode("utf-8"))
            self._proc.stdin.flush()

    def rpc(self, method, params=None, timeout=None):
        """JSON-RPCを投げてresultを待つ。timeout=Noneで無制限。"""
        if self._closed:
            raise TaskError("acp session is closed")
        mid = next(self._seq)
        ev = threading.Event()
        box = {}
        self._pending[mid] = (ev, box)
        try:
            self._send({"jsonrpc": "2.0", "id": mid, "method": method,
                        "params": params or {}})
        except (OSError, ValueError) as e:
            self._pending.pop(mid, None)
            raise TaskError(f"{method}: send failed: {e}")
        if not ev.wait(timeout):
            self._pending.pop(mid, None)
            raise TaskError(f"{method}: timeout")
        if "error" in box:
            raise TaskError(
                f"{method}: {json.dumps(box['error'])[:400]}")
        if "eof" in box:
            raise TaskError(f"{method}: acp process exited")
        return box.get("result") or {}

    def _read_loop(self):
        try:
            for raw in self._proc.stdout:
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if "method" in msg:
                    self._handle_agent(msg)
                    continue
                mid = msg.get("id")
                ent = self._pending.pop(mid, None)
                if ent is not None:
                    ev, box = ent
                    if "error" in msg:
                        box["error"] = msg["error"]
                    else:
                        box["result"] = msg.get("result")
                    ev.set()
        finally:
            # プロセス終了: 待機中の全rpcを解放する
            for mid, (ev, box) in list(self._pending.items()):
                box["eof"] = True
                ev.set()
            self._pending.clear()

    def _handle_agent(self, msg):
        method = msg.get("method")
        if msg.get("id") is not None:
            # エージェント→クライアントのリクエスト
            if method == "session/request_permission":
                oid = _pick_permission_option(
                    (msg.get("params") or {}).get("options"),
                    True)
                self._respond(msg["id"], {
                    "outcome": {"outcome": "selected",
                                "optionId": oid}})
            else:
                self._respond(msg["id"], err={
                    "code": -32601,
                    "message": f"unsupported: {method}"})
        elif method == "session/update":
            u = (msg.get("params") or {}).get("update") or {}
            if self.on_update:
                try:
                    self.on_update(u)
                except Exception:  # nosec B110  # 設計上の許容
                    pass

    def _respond(self, mid, result=None, err=None):
        rep = {"jsonrpc": "2.0", "id": mid}
        if err is not None:
            rep["error"] = err
        else:
            rep["result"] = result
        try:
            self._send(rep)
        except (OSError, ValueError):
            pass

    def prompt(self, blocks):
        """session/prompt を送り、ターン終了まで待つ。

        @param blocks: [{"type":"text","text":...},
                        {"type":"image","data":b64,"mimeType":...}]
        @returns session/prompt の result(stopReason/usage等)
        """
        return self.rpc("session/prompt", {
            "sessionId": self.session_id, "prompt": blocks})

    def cancel(self):
        """進行中ターンを中断させる(session/cancel通知)。"""
        try:
            self._send({"jsonrpc": "2.0", "method": "session/cancel",
                        "params": {"sessionId": self.session_id}})
        except (OSError, ValueError):
            pass

    def close(self):
        """session/close をbest-effort通知してプロセスを畳む。"""
        if self._closed:
            return
        self._closed = True
        try:
            if self.session_id:
                self._send({"jsonrpc": "2.0", "method": "session/close",
                            "params": {"sessionId": self.session_id}})
        except (OSError, ValueError):
            pass
        try:
            self._proc.terminate()
        except OSError:
            pass
