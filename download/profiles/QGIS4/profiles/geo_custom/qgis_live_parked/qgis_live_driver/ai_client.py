"""AIアシスタントパネル用のLLM APIクライアント(stdlibのみ)。

ai_panel.py(Qt層)から呼ばれる。QGIS/Qtに依存しないためpytest対象。

対応プロバイダ:
  - "openai": OpenAI Chat Completions 互換
    (POST {base}/chat/completions, tools=function calling)。
    Ollama・LM Studio・OpenRouter等の互換サーバも
    base URLを変えるだけで使える(例: http://localhost:11434/v1)
  - "gemini": Google Gemini API
    (POST {base}/models/{model}:generateContent, functionDeclarations。
    認証は x-goog-api-key ヘッダ)
  - "copilot": GitHub Copilot
    (OpenAI互換の {api}/chat/completions。APIキー欄のGitHubトークンを
    api.github.com/copilot_internal/v2/token で短期トークンに交換し、
    応答の endpoints.api をAPI先に使う。Copilot契約が必要。
    「GitHubでサインイン」ボタンはOAuthデバイスフローでトークンを取得)

ツール定義は mcp_http.TOOLS(MCP/RESTと同一)を各プロバイダの
スキーマに変換して使う。実行は LiveDriver.submit() に委譲するため
このモジュール自体はQGISを触らない。

プロバイダ抽象化: OpenAIProvider/GeminiProvider/CopilotProvider が
  build_messages / send / parse / append_exchange を実装し、
ai_panel のエージェントループはプロバイダ非依存で回る。
"""

import base64
import hashlib
import itertools
import json
import os
import re
import secrets
import shutil
import subprocess  # nosec B404  # MCPサーバ起動に必要
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

from . import credential_store
from .mcp_http import TOOLS

try:
    from qgis.PyQt.QtCore import QCoreApplication, QT_TRANSLATE_NOOP
except ImportError:
    QCoreApplication = None

    def QT_TRANSLATE_NOOP(ctx, src):  # noqa: N802
        return src


def tr_label(src):
    """UI表示用ラベルの実行時翻訳。Qtが無い環境(pytest)では英語のまま。"""
    if QCoreApplication is not None:
        return QCoreApplication.translate("qgis_live_driver", src)
    return src


_F_PRICE_TOKENS = QT_TRANSLATE_NOOP(
    "qgis_live_driver", "Input {0} / Output {1} /1M tokens")
_F_PRICE_IMG = QT_TRANSLATE_NOOP(
    "qgis_live_driver", "{0} /image (image generation)")
_F_KIND = QT_TRANSLATE_NOOP("qgis_live_driver", "Kind: {0}")
_F_PRICE = QT_TRANSLATE_NOOP("qgis_live_driver", "Price: {0} ({1})")
_F_CONTEXT = QT_TRANSLATE_NOOP("qgis_live_driver", "Context: {0} tokens")
_LBL_API_VALUE = QT_TRANSLATE_NOOP("qgis_live_driver", "API value")
_LBL_REFERENCE = QT_TRANSLATE_NOOP("qgis_live_driver", "reference")

# 1ユーザメッセージに対するツール実行の最大往復数(暴走防止)
MAX_TOOL_ROUNDS = 25

# ツール結果としてモデルに返すテキストの上限(超過分は切り詰め)
MAX_TOOL_RESULT_CHARS = 6000
# 会話履歴をプロンプトへ渡す上限(文字数)。超過分は古いターンから
# 落とす(往復で肥大したコンテキストがAPIエラーになるのを防ぐ)
MAX_HISTORY_CHARS = 60000

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"

# ---- GitHub Copilot ----
# GitHub Copilot APIは公開仕様ではなく、VS CodeのCopilot Chatが使う
# 内部エンドポイント。GitHubトークンを短期トークンに交換して使うのは
# copilot-api等のコミュニティ実装と同じ経路。Copilot契約が必要。
COPILOT_DEFAULT_BASE = "https://api.githubcopilot.com"
COPILOT_DEFAULT_MODEL = "gpt-4o"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"  # nosec B105  # 公開API URL
# v2/tokenが応答しない環境でのフォールバック: 契約情報(endpoints.api/
# access_type_sku)を返す。@github/copilot CLIが使う公式経路
COPILOT_USER_URL = "https://api.github.com/copilot_internal/user"
# api.githubcopilot.com が要求するクライアント識別ヘッダ。
# 任意のEditor-Versionでは拒否されうるため、VS CodeのCopilot Chatが
# 送る値(VS Code拡張・copilot-api等と同じデファクト)を使う。
COPILOT_HEADERS = {
    "Editor-Version": "vscode/1.99.3",
    "Editor-Plugin-Version": "copilot-chat/0.26.7",
    "Copilot-Integration-Id": "vscode-chat",
    "Openai-Intent": "conversation-panel",
    "User-Agent": "GitHubCopilotChat/0.26.7",
}
# OAuthデバイスフローのclient_id。既定はVS Codeの公開OAuth Appで、
# 同意画面には「Visual Studio Code」と表示される(Copilot認可を受ける
# デファクトの方法。copilot-api等も同値)。独自OAuth Appを使う場合は
# 環境変数で差し替える。
GITHUB_CLIENT_ID = os.environ.get("QGIS_LIVE_GITHUB_CLIENT_ID",
                                  "Iv1.b507a08c87ecfe98")
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"  # nosec B105  # 公開API URL

PROVIDERS = {
    "openai": {
        "label": QT_TRANSLATE_NOOP("qgis_live_driver", "OpenAI-compatible"),
        "base": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "qgis_live_driver",
            "API key (may be empty for local servers)"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "qgis_live_driver",
            "https://api.openai.com/v1  or  http://localhost:11434/v1"),
    },
    "gemini": {
        "label": "Gemini",
        "base": GEMINI_DEFAULT_BASE_URL,
        "model": GEMINI_DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "qgis_live_driver",
            "Gemini API key (issued in AI Studio)"),
        "endpoint_hint": "https://generativelanguage.googleapis.com/v1beta",
    },
    "copilot": {
        "label": "GitHub Copilot",
        "base": COPILOT_DEFAULT_BASE,
        "model": COPILOT_DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "qgis_live_driver",
            "GitHub token (Copilot subscription required; can be "
            "acquired automatically via \"Sign in with GitHub\")"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "qgis_live_driver",
            "https://api.githubcopilot.com  (URL of a compatible "
            "proxy such as copilot-api)"),
    },
}

# ---- モデル一覧のメタ情報 ----

# モデル種別 → 表示ラベル。この順序でコンボをグループ化する。
MODEL_KINDS = [
    ("chat_vision",
     QT_TRANSLATE_NOOP("qgis_live_driver", "Text (image input)")),
    ("chat", QT_TRANSLATE_NOOP("qgis_live_driver", "Text")),
    ("image", QT_TRANSLATE_NOOP("qgis_live_driver", "Image generation")),
    ("embed", QT_TRANSLATE_NOOP("qgis_live_driver", "Embedding")),
    ("other", QT_TRANSLATE_NOOP("qgis_live_driver", "Audio/Other")),
]
MODEL_KIND_LABELS = dict(MODEL_KINDS)

# プロバイダ既定エンドポイント利用時にコンボへ予め載せる推奨モデル
# (「取得」ボタンを押さなくても価格付きで選べるようにするため)。
# 実際に使えるかはAPIキーのプラン次第。取得で実一覧に置き換わる。
SUGGESTED_MODELS = {
    "openai": ["gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4.1",
               "gpt-4o-mini", "gpt-4o", "o4-mini"],
    "gemini": ["gemini-3.8-flash", "gemini-3.5-flash",
               "gemini-3.1-flash-lite", "gemini-2.5-pro"],
    "copilot": ["gpt-4o", "gpt-4.1", "gpt-5-mini", "gpt-5", "o4-mini",
                "claude-sonnet-4", "claude-3.7-sonnet", "gemini-2.5-pro"],
}

# 主要モデルの参考価格 (USD / 1Mトークン, [入力, 出力])。
# APIが価格を返さない場合の目安表示用。公開価格ベースだが
# 変動しうるため「参考値」として表示する。モデルIDの末尾部分
# (プロバイダ名を除いたもの)との前方一致・最長一致で引く。
KNOWN_MODEL_PRICES = {
    "gpt-5-pro": (15.00, 120.00),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o3": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    "claude-opus-4": (15.00, 75.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4": (1.00, 5.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-haiku": (0.25, 1.25),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
}

# 種別推定のための名前ヒント(モデルID末尾の小文字に対して検索)。
# 判定は推定であり、APIが modality 等を返す場合はそちらを優先する。
_EMBED_RE = re.compile(r"embed")
_IMAGE_RE = re.compile(
    r"dall-e|gpt-image|imagen|[-_/]image($|[-_.0-9])|flux|"
    r"stable.?diffusion|sdxl|ideogram|recraft|playground-v|cogview|"
    r"kolors|seedream|photon|hunyuan-image|pixart")
_AUDIO_RE = re.compile(
    r"whisper|tts|transcribe|realtime|audio|moderation|speech|voice")
_VISION_RE = re.compile(
    r"vision|gpt-4o|chatgpt|gpt-4\.1|gpt-5|gpt-4-turbo|gpt-4-|"
    r"\bo[134]\b|claude|gemini|gemma-?3|pixtral|llava|moondream|"
    r"cogvlm|internvl|minicpm-v|qvq|glm-4|kimi|[-_.]vl($|[-_.0-9])|"
    r"qwen.*vl|llama-4|llama-3\.2-(11|90)b|mistral-(small|medium|large)|"
    r"grok")


def classify_model(model_id, entry=None):
    """モデルID(+APIのメタ情報)から種別を推定する。

    @returns "chat_vision"|"chat"|"image"|"embed"|"other"
    entry は list_model_entries() の1要素。OpenRouter等が返す
    architecture.modality ("text+image->text" 等) や
    input_modalities/output_modalities があれば最優先で使う。
    """
    tail = (model_id or "").split("/")[-1].lower()
    if entry:
        mod = str(entry.get("modality") or "").lower()
        ins = [str(x).lower() for x in entry.get("input_modalities") or []]
        outs = [str(x).lower() for x in entry.get("output_modalities") or []]
        if "->" in mod:
            mi, mo = mod.split("->", 1)
            if "image" in mo:
                return "image"
            if "image" in mi:
                return "chat_vision"
        if any("image" in o for o in outs):
            return "image"
        if any("image" in i for i in ins):
            return "chat_vision"
    if _EMBED_RE.search(tail):
        return "embed"
    if _IMAGE_RE.search(tail):
        return "image"
    if _AUDIO_RE.search(tail):
        return "other"
    if _VISION_RE.search(tail):
        return "chat_vision"
    return "chat"


def _usd(v):
    """金額を $ 表記に整形 (0.6→$0.60, 0.075→$0.075, 10→$10)。"""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    if "." in s and len(s.rsplit(".", 1)[1]) < 2:
        s = f"{v:.2f}"
    return f"${s}"


def fmt_tokens(n):
    """トークン数を短縮表記に (128000→"128k", 1048576→"1.0M")。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _known_price(tail):
    """既知価格表を末尾IDで最長前方一致検索 → (in_usd, out_usd)|None"""
    best = None
    for key, io in KNOWN_MODEL_PRICES.items():
        if tail == key or tail.startswith(key):
            if best is None or len(key) > len(best[0]):
                best = (key, io)
    return best[1] if best else None


def _entry_price(entry, tail):
    """価格情報 → (短表記, 説明文, 出典, (in,out)/1MのUSD|None) 。

    OpenRouter等が pricing.prompt/completion (USD/token) を返せば
    それを使い、無ければ既知価格表(参考値)にフォールバックする。
    """
    pr = entry.get("pricing")
    if isinstance(pr, dict):
        def _pm(key):
            try:
                return float(pr[key]) * 1_000_000
            except (KeyError, TypeError, ValueError):
                return None
        pin, pout = _pm("prompt"), _pm("completion")
        if pin is not None or pout is not None:
            pin, pout = pin or 0.0, pout or 0.0
            return (f"{_usd(pin)}/{_usd(pout)}",
                    tr_label(_F_PRICE_TOKENS).format(
                        _usd(pin), _usd(pout)),
                    "api", (pin, pout))
        try:
            pimg = float(pr.get("image"))
        except (TypeError, ValueError):
            pimg = None
        if pimg:
            return (f"{_usd(pimg)}/img",
                    tr_label(_F_PRICE_IMG).format(_usd(pimg)),
                    "api", None)
    kp = _known_price(tail)
    if kp:
        return (f"{_usd(kp[0])}/{_usd(kp[1])}",
                tr_label(_F_PRICE_TOKENS).format(
                    _usd(kp[0]), _usd(kp[1])),
                "known", kp)
    return None, None, None, None


def model_info(entry):
    """list_model_entries()の1要素 → {id, kind, price, price_desc,
    price_src, price_usd, context} に正規化する。"""
    mid = entry["id"]
    tail = mid.split("/")[-1].lower()
    price, desc, src, usd = _entry_price(entry, tail)
    return {
        "id": mid,
        "kind": classify_model(mid, entry),
        "price": price,
        "price_desc": desc,
        "price_src": src,          # "api"=エンドポイント応答 / "known"=参考値
        "price_usd": usd,          # (in_usd, out_usd)/1Mトークン|None
        "context": (entry.get("context_length")
                    or entry.get("input_token_limit")),
    }


def usage_cost(info, total):
    """model_info + 累計usage {"in","out"} → 推定コストUSD|None。

    price_usd は1MトークンあたりのUSD。"known"(参考値)でも計算する。
    """
    pr = info.get("price_usd")
    if not pr:
        return None
    return (total.get("in", 0) * pr[0]
            + total.get("out", 0) * pr[1]) / 1_000_000


def parse_usage(data):
    """API応答のusage → {"in","out"}|None に正規化する。

    OpenAI互換: usage.prompt_tokens/completion_tokens
    Gemini: usageMetadata.promptTokenCount/candidatesTokenCount
    (thoughtsTokenCount も出力側に含める)
    """
    u = data.get("usage")
    if isinstance(u, dict):
        pin = u.get("prompt_tokens")
        pout = u.get("completion_tokens")
        if pin is not None or pout is not None:
            return {"in": pin or 0, "out": pout or 0}
    m = data.get("usageMetadata")
    if isinstance(m, dict):
        pin = m.get("promptTokenCount")
        pout = ((m.get("candidatesTokenCount") or 0)
                + (m.get("thoughtsTokenCount") or 0))
        if pin is not None or pout:
            return {"in": pin or 0, "out": pout}
    return None


def model_label(info):
    """コンボの表示テキスト。価格があれば 'id   $in/$out' 形式。"""
    return (f"{info['id']}   {info['price']}" if info.get("price")
            else info["id"])


def model_tooltip(info):
    """コンボ項目のツールチップ(複数行)。"""
    lines = [info["id"],
             tr_label(_F_KIND).format(tr_label(
                 MODEL_KIND_LABELS.get(info["kind"], info["kind"])))]
    if info.get("price_desc"):
        src = (tr_label(_LBL_API_VALUE) if info["price_src"] == "api"
               else tr_label(_LBL_REFERENCE))
        lines.append(
            tr_label(_F_PRICE).format(info["price_desc"], src))
    if info.get("context"):
        ctx = fmt_tokens(info["context"])
        if ctx:
            lines.append(tr_label(_F_CONTEXT).format(ctx))
    return "\n".join(lines)


SYSTEM_PROMPT = """\
You are an AI assistant running inside QGIS (a desktop GIS application).
You operate QGIS through the provided tools. All tools run on the local
QGIS process via its live driver.

Guidelines:
- Prefer `qgis_pyeval` for QGIS operations. The code runs in the QGIS
  GUI thread with `iface`, `QgsProject`, `QgsApplication` and `driver`
  in scope. Expressions return their value; for statements assign the
  output to a variable named `result`.
- Use `qgis_status` first if you need to know which plugins are loaded
  or whether a plugin has a WebEngine view.
- Use `qgis_screenshot` to visually check the map canvas or the main
  window after operations that change the map.
- `plugin_id` routes eval/pyeval/screenshot to another plugin's live
  driver (e.g. a WebEngine plugin's `view`). Loaded plugin ids: {plugins}
- `ai_*` tools manage instruction files on this machine:
  `agents` = persistent instructions injected into your system prompt
  (one selected at a time), `skills` = on-demand procedural docs listed
  in the prompt. You may create or update them when the user asks or
  when a reusable procedure emerges. Save always writes a user file;
  bundled files can be shadowed by saving the same id but never deleted.
- When the user asks to save/learn/create instructions, choose the
  right kind by intent and tell them which you chose and why:
  - `agents`: requests about how you should always behave — a role,
    persona, policy, or output style ("be a surveying expert", "always
    answer with a table", "from now on do X"). Only one is active at
    a time, so also offer to select it via ai_select_agent.
  - `skills`: requests to remember a procedure — repeatable steps for
    a specific task ("remember this workflow", "save how to do X").
    Skills coexist and are read on demand, so this is the default for
    task-specific knowledge.
  If the intent is genuinely ambiguous, ask the user which they want
  before saving.
- `mcp_<server>__<tool>` tools (if present) are provided by external
  MCP servers configured on this machine.
- Keep each step small and verify the result before moving on.
- Answer in the user's language.
"""


class ApiError(Exception):
    """API呼び出しの失敗(HTTP/接続/応答形式/設定不足)。"""


def provider_defaults(provider):
    """プロバイダID → {"base","model","label","key_hint","endpoint_hint"}"""
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise ApiError(f"Unknown provider: {provider}")


# ---- 共通HTTP ----

def _require_http_scheme(url):
    """http/https 以外のスキーム(file:等)を拒否する。"""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ApiError("Unsupported URL scheme: {0}".format(scheme or "(none)"))


def _get_json(url, headers, timeout=30.0):
    _require_http_scheme(url)
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # _require_http_schemeでhttp/httpsのみ許可
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # nosec B110  # 設計上の許容
            pass
        raise ApiError(f"HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"Connection failed: {e.reason}") from e


def _post_json(url, headers, body, timeout=180.0):
    _require_http_scheme(url)
    headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # _require_http_schemeでhttp/httpsのみ許可
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # nosec B110  # 設計上の許容
            pass
        raise ApiError(f"HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"Connection failed: {e.reason}") from e


def _post_form(url, fields, timeout=30.0):
    """application/x-www-form-urlencoded でPOSTして応答JSONを返す。"""
    _require_http_scheme(url)
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST", headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # _require_http_schemeでhttp/httpsのみ許可
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # nosec B110  # 設計上の許容
            pass
        raise ApiError(f"HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"Connection failed: {e.reason}") from e


# ---- GitHub Copilot: トークン交換 / OAuthデバイスフロー ----

# GitHubトークン → {"token","expires_at","api"} のキャッシュ
_COPILOT_CACHE = {}
_COPILOT_CACHE_LOCK = threading.Lock()


def _gh_headers(github_token):
    return {"Authorization": f"token {github_token}",
            "Accept": "application/json",
            **COPILOT_HEADERS}


def copilot_session(github_token, base):
    """GitHubトークン → (Copilot APIのBearerトークン, API base) に解決する。

    baseが既定(COPILOT_DEFAULT_BASE)の場合のみ、GitHubトークンを
    copilot_internal/v2/token で短期トークンに交換し、応答の
    endpoints.api (individual/business/enterprise) をAPI先に使う。
    トークンは期限切れ60秒前までモジュール内キャッシュする。
    v2/token が応答しない環境(404の報告あり)では
    copilot_internal/user でAPI先だけを解決し、GitHubトークンを
    そのままBearerに使う(@github/copilot CLIと同じ動作)。
    既定以外のbaseはcopilot-api互換プロキシ等とみなし、
    交換せずgithub_tokenをそのままBearerに使う。
    """
    u = (base or "").strip().rstrip("/") or COPILOT_DEFAULT_BASE
    if not github_token:
        raise ApiError(
            "Enter a GitHub token in the API key field, or acquire one "
            "via \"Sign in with GitHub\"")
    if u != COPILOT_DEFAULT_BASE:
        return github_token, u
    now = time.time()
    with _COPILOT_CACHE_LOCK:
        ent = _COPILOT_CACHE.get(github_token)
        if ent and ent["expires_at"] - now >= 60:
            return ent["token"], ent["api"]
        try:
            data = _get_json(COPILOT_TOKEN_URL, _gh_headers(github_token))
            tok = data.get("token")
            if not tok:
                raise ApiError(f"no token: {str(data)[:200]}")
            ent = {
                "token": tok,
                "expires_at": float(
                    data.get("expires_at")
                    or now + float(data.get("refresh_in") or 1500)),
                "api": ((data.get("endpoints") or {}).get("api")
                        or COPILOT_DEFAULT_BASE),
            }
        except ApiError as e1:
            # フォールバック: copilot_internal/user でプラン別API先を
            # 解決し、GitHubトークンをそのままBearerに使う
            try:
                user = _get_json(COPILOT_USER_URL,
                                 _gh_headers(github_token))
            except ApiError as e2:
                raise ApiError(
                    "Could not obtain a Copilot token"
                    " (the GitHub token may be invalid or lack a Copilot "
                    "subscription): "
                    f"{e1} / {e2}") from e2
            ent = {
                "token": github_token,
                "expires_at": now + 1500,
                "api": ((user.get("endpoints") or {}).get("api")
                        or COPILOT_DEFAULT_BASE),
            }
        _COPILOT_CACHE[github_token] = ent
        return ent["token"], ent["api"]


def github_device_code(scope="read:user"):
    """OAuthデバイスフローを開始する。

    @returns {"device_code","user_code","verification_uri",
              "interval","expires_in"} — ユーザにverification_uriで
      user_codeを入力させ、device_codeをポーリングに使う
    """
    d = _post_form(GITHUB_DEVICE_CODE_URL,
                   {"client_id": GITHUB_CLIENT_ID, "scope": scope})
    if not d.get("device_code") or not d.get("user_code"):
        raise ApiError(f"Invalid device code response: {str(d)[:300]}")
    return d


def github_poll_access_token(device_code):
    """デバイスフローのトークンを1回ポーリングする。

    @returns API応答dict。{"access_token": ...} なら完了、
      {"error": "authorization_pending"|"slow_down"|...} は未完了/失敗
      (GitHubは未認可でもHTTP 200でerrorフィールドを返す)
    """
    return _post_form(GITHUB_ACCESS_TOKEN_URL, {
        "client_id": GITHUB_CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})


# ---- OpenAI互換 (Chat Completions) ----

def openai_models_url(base):
    """base URLをmodels一覧のGET先に正規化する。"""
    u = (base or "").strip().rstrip("/")
    if not u:
        raise ApiError("API endpoint is not set")
    if u.endswith("/chat/completions"):
        u = u[: -len("/chat/completions")]
    return u + "/models"


def endpoint_url(base):
    """base URLをchat/completionsのPOST先に正規化する。

    "https://api.openai.com/v1" → ".../v1/chat/completions"
    既に /chat/completions で終わるURLはそのまま使う。
    """
    u = (base or "").strip().rstrip("/")
    if not u:
        raise ApiError("API endpoint is not set")
    if not u.endswith("/chat/completions"):
        u += "/chat/completions"
    return u


def _tool_short(name):
    """ツール名の接頭辞(qgis_|ai_)を剥がした種別名。allowed判定用。"""
    return name.split("_", 1)[1] if "_" in name else name


def openai_tools(allowed=None):
    """mcp_http.TOOLS + INSTRUCTION_TOOLS + 外部MCPツールを
    OpenAI function callingスキーマに変換する。"""
    out = []
    for t in TOOLS + INSTRUCTION_TOOLS + _EXTRA_TOOLS:
        if allowed is not None and _tool_short(t["name"]) not in allowed:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            },
        })
    return out


def chat_completions(base, api_key, model, messages, tools=None,
                     timeout=180.0, extra=None, headers=None):
    """POST {base}/chat/completions (非ストリーミング)して応答JSONを返す。

    @param headers: Authorization以外に追加するヘッダ(Copilot用)
    @raises ApiError: HTTP/接続エラー・応答形式不正
    """
    body = {"model": model, "messages": messages}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if extra:
        body.update(extra)
    hdrs = dict(headers or {})
    if api_key:
        hdrs["Authorization"] = f"Bearer {api_key}"
    data = _post_json(endpoint_url(base), hdrs, body, timeout)
    if not isinstance(data, dict) or not data.get("choices"):
        raise ApiError(f"Invalid response format: {str(data)[:300]}")
    return data


# ---- Gemini (generateContent) ----

def gemini_models_url(base):
    """base URLをmodels一覧のGET先に正規化する。"""
    u = (base or "").strip().rstrip("/")
    if not u:
        raise ApiError("API endpoint is not set")
    if ":generateContent" in u:
        u = u.split("/models/")[0]  # /models/<m>:generateContent を切る
    return u + "/models"


def _gemini_schema(s):
    """JSON Schema(lowercase type)をGemini functionDeclarationsの
    Schema(UPPERCASE type, OpenAPIサブセット)に変換する。"""
    if isinstance(s, dict):
        out = {}
        for k, v in s.items():
            out[k] = (v.upper() if (k == "type" and isinstance(v, str))
                      else _gemini_schema(v))
        if out.get("type") == "ARRAY" and "items" not in out:
            out["items"] = {}  # items必須。{}=任意型
        return out
    if isinstance(s, list):
        return [_gemini_schema(x) for x in s]
    return s


def gemini_tools(allowed=None):
    """mcp_http.TOOLS + INSTRUCTION_TOOLS + 外部MCPツールを
    Gemini functionDeclarationsに変換する。"""
    decls = []
    for t in TOOLS + INSTRUCTION_TOOLS + _EXTRA_TOOLS:
        if allowed is not None and _tool_short(t["name"]) not in allowed:
            continue
        decls.append({
            "name": t["name"],
            "description": t["description"],
            "parameters": _gemini_schema(t["inputSchema"]),
        })
    return decls


def gemini_url(base, model):
    """generateContentのPOST先URL。"""
    u = (base or "").strip().rstrip("/")
    if not u:
        raise ApiError("API endpoint is not set")
    if ":generateContent" in u:
        return u
    return f"{u}/models/{model}:generateContent"


def gemini_generate(base, api_key, model, system, contents,
                    tools=None, timeout=180.0, extra=None):
    """POST {base}/models/{model}:generateContent して応答JSONを返す。"""
    body = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
    if extra:
        body.update(extra)
    headers = {"x-goog-api-key": api_key} if api_key else {}
    data = _post_json(gemini_url(base, model), headers, body, timeout)
    if not isinstance(data, dict) or not data.get("candidates"):
        fb = (data or {}).get("promptFeedback") if isinstance(data, dict) else None
        raise ApiError(
            f"Invalid or blocked response: "
            f"{str(fb or data)[:300]}")
    return data


# ---- ツール共通 ----

def tool_to_command(name, args):
    """ツール呼び出し(qgis_<type>)をドライバのコマンドdictに変換する。

    mcp_http._tool_call と同じ規則: qgis_接頭辞を剥がしてtypeにし、
    引数をそのままマージする。None値の引数は送らない。
    """
    if not (name or "").startswith("qgis_"):
        raise ApiError(f"Unknown tool: {name}")
    cmd = {"type": name[len("qgis_"):]}
    cmd.update({k: v for k, v in (args or {}).items() if v is not None})
    return cmd


def trim_history(history, max_chars=MAX_HISTORY_CHARS):
    """会話履歴を max_chars 以内にする。古いターンから落とし、
    最新ターンは必ず残る(プロンプト送信時のコンテキスト上限対策)。"""
    total = 0
    keep = []
    for m in reversed(history or []):
        n = len(m.get("content") or "")
        if keep and total + n > max_chars:
            break
        keep.append(m)
        total += n
    return list(reversed(keep))


def parse_tool_arguments(raw):
    """tool_callのarguments(JSON文字列)をdictにする。"""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception as e:
        raise ApiError(
            f"tool arguments are not valid JSON: {e}: {str(raw)[:200]}")


def command_from_tool_call(tc):
    """OpenAI tool_callオブジェクト → (name, ドライバcmd)。"""
    fn = (tc or {}).get("function") or {}
    name = fn.get("name") or ""
    args = parse_tool_arguments(fn.get("arguments"))
    return name, tool_to_command(name, args)


def reply_to_text(rep):
    """ドライバのreply dictをツール結果テキストにする。"""
    if "error" in rep:
        return f"ERROR: {rep['error']}"
    text = rep.get("result")
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False, indent=2)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = (text[:MAX_TOOL_RESULT_CHARS]
                + f"\n... (truncated, {len(text)} chars total)")
    return text


def screenshot_temp_path():
    return os.path.join(tempfile.gettempdir(),
                        f"qgis-ai-shot-{uuid.uuid4().hex[:8]}.png")


def attachment_temp_path():
    """チャット入力に添付された画像の保存先(PNGに正規化して書く)。"""
    return os.path.join(tempfile.gettempdir(),
                        f"qgis-ai-attach-{uuid.uuid4().hex[:8]}.png")


def image_b64(path):
    """PNGファイルをbase64文字列にする(読めなければNone)。"""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None


def image_url_part(path):
    """PNGファイル→OpenAIのimage_urlパート(読めなければNone)。"""
    b64 = image_b64(path)
    if b64 is None:
        return None
    return {"type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}}


def image_inline_part(path):
    """PNGファイル→GeminiのinlineDataパート(読めなければNone)。"""
    b64 = image_b64(path)
    if b64 is None:
        return None
    return {"inlineData": {"mimeType": "image/png", "data": b64}}


def user_content(text, image_paths):
    """ユーザ入力(テキスト+画像パス列)をOpenAIのcontentにする。

    画像が無い・全て読めない場合はテキスト文字列のまま返す
    (vision非対応モデルとの互換のため単一テキストは配列化しない)。
    """
    imgs = [p for p in
            (image_url_part(x) for x in image_paths or [])
            if p is not None]
    if not imgs:
        return text or ""
    return ([{"type": "text", "text": text}] if text else []) + imgs


def image_message_content(path, note=None):
    """PNGファイルをOpenAI vision用のcontent配列にする(読めなければNone)。"""
    part = image_url_part(path)
    if part is None:
        return None
    return [{"type": "text",
             "text": note or f"screenshot saved: {path}"}, part]


def system_prompt(plugins=None, agent_text=None, skills=None,
                  agents=None, active_agent=None):
    """システムプロンプトを組み立てる。

    @param agent_text: エージェント指示書(agents/*.mdの本文)。
      選択されていれば常時注入される
    @param skills: list_skills() の一覧。パス+説明のみ載せ、
      本文はモデルが必要時に qgis_pyeval の open() で読む
      (progressive disclosureでトークン節約)
    @param agents: list_agents() の一覧。id+説明のみ載せ、
      active_agent に [active] を付ける。モデルは
      ai_select_agent で切替・ai_read_instruction で読取できる
    """
    plist = ", ".join(sorted(plugins)) if plugins else "(none)"
    p = SYSTEM_PROMPT.format(plugins=plist)
    if agent_text and agent_text.strip():
        p += "\n## Agent instructions\n" + agent_text.strip() + "\n"
    if agents:
        lines = "\n".join(
            f"- {a['id']}: {a['desc'] or a['title']}"
            + (f" — use when: {a['when']}" if a.get("when") else "")
            + (" [active]" if a["id"] == active_agent else "")
            for a in agents)
        p += ("\n## Agents\n"
              "Agent instruction files define persistent behavior. "
              "The [active] agent's body is already injected above. "
              "Each entry's 'use when' (if any) says which tasks it "
              "suits. Switch with ai_select_agent, or read one via "
              "ai_read_instruction and adopt it ad hoc:\n"
              + lines + "\n")
    if skills:
        lines = "\n".join(
            f"- {s['id']} ({s['path']}): {s['desc']}"
            + (f" — use when: {s['when']}" if s.get("when") else "")
            for s in skills)
        p += ("\n## Skills\n"
              "Skill files are available on this machine. Check each "
              "entry's 'use when' (if any); when a task matches, read "
              "the file via qgis_pyeval open() first:\n"
              + lines + "\n")
    return p


# ---- エージェント/スキル(指示書ファイル) ----
# 整理方針:
#   agents/  = 常時注入される指示書(役割・方針)。UIで1件選択して使う
#   skills/  = オンデマンドの手順書。一覧だけをプロンプトに載せ、
#              モデルが該当タスク時に qgis_pyeval で本文を読む
# 置き場所(ユーザ定義)は ~/.qgis-live/<kind>/ (QGIS_LIVE_REGISTRY準拠)。
# <plugin>/<kind>/ はプラグイン同梱の読み取り専用デフォルトで、
# ユーザ側の同名ファイルが優先される(上書き)。

def _registry_dir():
    return os.environ.get(
        "QGIS_LIVE_REGISTRY",
        os.path.join(os.path.expanduser("~"), ".qgis-live"))


def agents_dir():
    return os.path.join(_registry_dir(), "agents")


def skills_dir():
    return os.path.join(_registry_dir(), "skills")


def _bundled_dir(kind):
    """プラグイン同梱のデフォルト <kind> ディレクトリ。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), kind)


# ヘッダーの「使いどき」ラベル(説明文の直後・最初の空行までの間に書く)
_WHEN_RE = re.compile(
    r"^(?:use_when|when_to_use|when|用途|使いどき)\s*[:：]\s*(.+)$",
    re.IGNORECASE)


def _md_head(path):
    """.md の先頭から (title, desc, when) を取る。

    所定書式(ヘッダー):
        # タイトル
        説明文(1行)
        use_when: 使いどき(1行、省略可)
    'use_when' には when/when_to_use/用途/使いどき の別名も使える。
    when 行は説明文の直後・最初の空行までの間のみ認識する。
    frontmatter的な '---' やコメント行は読み飛ばす。
    """
    title = desc = when = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                t = raw.strip()
                if not t:
                    if title and desc:
                        break
                    continue
                if t.startswith("#"):
                    if title is None:
                        title = t.lstrip("#").strip()
                    elif desc:
                        break      # 次見出し=ヘッダー終了
                    continue
                if desc is None:
                    if t.startswith("---") or t.startswith("<!--"):
                        continue
                    desc = t
                    continue
                m = _WHEN_RE.match(t)
                if m:
                    when = m.group(1).strip()
                break              # ラベル行以外=ヘッダー終了
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return title, desc, when


def list_instruction_files(kind):
    """"agents"|"skills" の .md を走査する。

    @returns [{id, title, desc, path, builtin}] (id=ファイル名stemで
      ソート)。bundled→user の順で走査し、同名はユーザ側が上書き。
    """
    udir = agents_dir() if kind == "agents" else skills_dir()
    out = {}
    for d, builtin in ((_bundled_dir(kind), True), (udir, False)):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith(".md"):
                continue
            stem = f[:-3]
            if not builtin or stem not in out:
                p = os.path.join(d, f)
                title, desc, when = _md_head(p)
                out[stem] = {"id": stem, "path": p, "builtin": builtin,
                             "title": title or stem, "desc": desc or "",
                             "when": when or ""}
    return [out[k] for k in sorted(out)]


def list_agents():
    """利用可能なエージェント指示書一覧。"""
    return list_instruction_files("agents")


def list_skills():
    """利用可能なスキル手順書一覧。"""
    return list_instruction_files("skills")


def _kind_dir(kind):
    return agents_dir() if kind == "agents" else skills_dir()


def _kind_list(kind):
    return list_agents() if kind == "agents" else list_skills()


def load_agent(agent_id):
    """エージェントid → 指示テキスト。未指定/未存在はNone。"""
    return load_instruction("agents", agent_id)


def load_instruction(kind, item_id):
    """kind("agents"|"skills")のid → 本文。未指定/未存在はNone。"""
    if not item_id:
        return None
    for a in _kind_list(kind):
        if a["id"] == item_id:
            try:
                with open(a["path"], "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return None
    return None


def save_agent(name, text):
    """ユーザの agents/ に <name>.md として保存しパスを返す。"""
    return save_instruction("agents", name, text)


def save_skill(name, text):
    """ユーザの skills/ に <name>.md として保存しパスを返す。"""
    return save_instruction("skills", name, text)


def save_instruction(kind, name, text):
    """ユーザの <kind>/ に <name>.md として保存しパスを返す。

    ファイル名に使えない文字・空白は '_' に置換する。
    """
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", (name or "").strip())
    if not safe:
        raise ApiError("Name is empty")
    d = _kind_dir(kind)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, safe + ".md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text or "")
    return p


def delete_agent(agent_id):
    """ユーザ側のエージェントファイルを消す(bundledは消せない)。"""
    return delete_instruction("agents", agent_id)


def delete_skill(skill_id):
    """ユーザ側のスキルファイルを消す(bundledは消せない)。"""
    return delete_instruction("skills", skill_id)


def delete_instruction(kind, item_id):
    """ユーザ側の <kind>/<id>.md を消す(bundledは消せない)。"""
    for a in _kind_list(kind):
        if a["id"] == item_id and not a["builtin"]:
            try:
                os.remove(a["path"])
                return True
            except Exception:
                return False
    return False


# ---- AIローカルツール(指示書の自己編集) ----
# qgis_* ツールはドライバのコマンドだが、ai_* ツールはパネル側で
# ローカル実行し、このファイル層に委譲する。
# mcp_http.TOOLS と同じ {name, description, inputSchema} 形にして
# openai_tools()/gemini_tools() にそのまま混ぜられるようにする。

_KIND_PROP = {"type": "string", "enum": ["agents", "skills"],
              "description":
                  "agents=役割・方針・出力様式など常時注入の指示書"
                  "(同時に1件のみ有効。人格や「常に〜して」系の依頼向け) / "
                  "skills=特定タスクの手順・レシピ"
                  "(複数共存し必要時だけ読まれる。「この手順を覚えて」"
                  "系の依頼向け)"}

INSTRUCTION_TOOLS = [
    {
        "name": "ai_list_instructions",
        "description":
            "List agent/skill instruction files on this machine "
            "(id, title, desc, path, bundled-or-user).",
        "inputSchema": {"type": "object",
                        "properties": {"kind": _KIND_PROP},
                        "required": ["kind"]},
    },
    {
        "name": "ai_read_instruction",
        "description":
            "Read the full body of an agent/skill instruction file by id.",
        "inputSchema": {"type": "object",
                        "properties": {"kind": _KIND_PROP,
                                       "id": {"type": "string",
                                              "description": "ファイル名(stem)"}},
                        "required": ["kind", "id"]},
    },
    {
        "name": "ai_save_instruction",
        "description":
            "Create or overwrite an agent/skill instruction file. Always "
            "writes the user file (~/.qgis-live/<kind>/<name>.md); a "
            "user file with a bundled id shadows the bundled one. "
            "Choose the kind by intent: 'agents' for behavior/persona/"
            "output-style instructions (only one is active at a time), "
            "'skills' for task procedures and recipes (many coexist, "
            "read on demand). Format: first '# ' line = title, next "
            "non-empty line = description, optionally followed by a "
            "'use_when: <when to use>' line (shown in listings so "
            "the model can pick it when a task matches), then the "
            "instruction body.",
        "inputSchema": {"type": "object",
                        "properties": {"kind": _KIND_PROP,
                                       "name": {"type": "string",
                                                "description": "ファイル名(stem)"},
                                       "text": {"type": "string",
                                                "description": "ファイル本文(Markdown)"}},
                        "required": ["kind", "name", "text"]},
    },
    {
        "name": "ai_delete_instruction",
        "description":
            "Delete a user-side agent/skill instruction file. "
            "Bundled files cannot be deleted.",
        "inputSchema": {"type": "object",
                        "properties": {"kind": _KIND_PROP,
                                       "id": {"type": "string",
                                              "description": "ファイル名(stem)"}},
                        "required": ["kind", "id"]},
    },
    {
        "name": "ai_select_agent",
        "description":
            "Switch the active agent instruction injected into your "
            "system prompt. Pass the agent id, or empty to clear. "
            "Panel-only: not meaningful for external clients.",
        "inputSchema": {"type": "object",
                        "properties": {
                            "id": {"type": "string",
                                   "description": "エージェントid(空=解除)"}},
                        "required": ["id"]},
    },
]

INSTRUCTION_TOOL_NAMES = {t["name"] for t in INSTRUCTION_TOOLS}


def run_instruction_tool(name, args):
    """ai_* ツールを実行して結果テキストを返す(パネルローカル実行)。

    @raises ApiError: 未知ツール・引数不正・対象なし
    """
    if name == "ai_select_agent":
        # 選択状態はパネル側のUI状態のためここでは扱わない
        raise ApiError("ai_select_agent is only valid on the AI panel")
    a = args or {}
    kind = a.get("kind") or ""
    if kind not in ("agents", "skills"):
        raise ApiError(f"kind must be agents|skills: {kind!r}")
    if name == "ai_list_instructions":
        items = list_instruction_files(kind)
        if not items:
            return "(none)"
        return "\n".join(
            f"- {i['id']}: {i['title']}"
            + (f" — {i['desc']}" if i.get("desc") else "")
            + (f" — use when: {i['when']}" if i.get("when") else "")
            + f" [{'bundled' if i['builtin'] else 'user'}] {i['path']}"
            for i in items)
    if name == "ai_read_instruction":
        body = load_instruction(kind, a.get("id") or "")
        if body is None:
            raise ApiError(f"{kind} '{a.get('id')}' not found")
        return body
    if name == "ai_save_instruction":
        if a.get("text") is None:
            raise ApiError("text is required")
        return f"saved: {save_instruction(kind, a.get('name'), a['text'])}"
    if name == "ai_delete_instruction":
        if delete_instruction(kind, a.get("id") or ""):
            return f"deleted: {kind}/{a.get('id')}"
        raise ApiError(
            f"cannot delete {kind} '{a.get('id')}'"
            "(does not exist or is bundled)")
    raise ApiError(f"Unknown tool: {name}")


# ---- 外部MCPクライアント(外向き接続) ----
# AIパネルが外部MCPサーバのツールを使うための接続層。
# 設定は ~/.qgis-live/mcp_servers.json (Claude Desktop互換):
#   {"mcpServers": {"fs":  {"command": "npx", "args": [...]},
#                   "api": {"url": "http://localhost:3000/mcp"}}}
# command=stdio起動 / url=Streamable HTTP。発見ツールは
# mcp_<server>__<tool> にマングリングしてfunction callingへ混ぜ、
# _EXTRA_TOOL_CALLERS 経由でパネルがローカル実行する。
# 秘密値(client_secret・headers・env)は "$store:<key>" と書くと
# OSの資格情報ストア(credential_store)から解決される。
# 平文の oauth.client_secret は mcp_save_config 保存時に自動で
# ストアへ移され、設定ファイルには参照だけが残る。

MCP_PROTOCOL_VERSION = "2025-03-26"


def mcp_config_path():
    """外部MCPサーバの設定ファイル。"""
    return os.path.join(_registry_dir(), "mcp_servers.json")


# 設定値中の資格情報ストア参照プレフィックス
MCP_SECRET_REF = "$store:"  # nosec B105  # 参照プレフィックス(資格情報ではない)


def _mcp_secret_key(server, field):
    """資格情報ストア上のキー名(サーバ名+項目名)。"""
    return f"mcp:{server}:{field}"


def _resolve_secret_ref(v):
    """'$store:<key>' 参照なら資格情報ストアから値を解決する。"""
    if isinstance(v, str) and v.startswith(MCP_SECRET_REF):
        key = v[len(MCP_SECRET_REF):]
        s = credential_store.get_secret(key)
        if s is None:
            raise ApiError(
                f"'{key}' not found in credential store"
                "($store: reference in mcp_servers.json)")
        return s
    return v


MCP_CONFIG_TEMPLATE = {
    "mcpServers": {
        "example-stdio": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem",
                     "C:\\work"],
        },
        "example-http": {
            "url": "http://localhost:3000/mcp",
            "headers": {"Authorization": "Bearer <static token>"},
        },
        "box-http-oauth": {
            "url": "https://mcp.box.com",
            "oauth": {
                "authorize_url":
                    "https://account.box.com/api/oauth2/authorize",
                "token_url": "https://api.box.com/oauth2/token",  # nosec B105  # 公開API URL
                "client_id": "<Box app Client ID>",
                "client_secret": "<Client Secret>",  # nosec B105  # テンプレートのプレースホルダ
                "redirect_uri": "http://127.0.0.1:8020/callback",
            },
        },
        "example-http-ccg": {
            "url": "https://example.com/mcp",
            "oauth": {
                "token_url": "https://example.com/oauth/token",  # nosec B105  # 例示URL
                "client_id": "<client_id>",
                "client_secret": "<client_secret>",  # nosec B105  # テンプレートのプレースホルダ
                "extra": {"box_subject_type": "enterprise",
                          "box_subject_id": "<id>"},
            },
        },
    },
}


def mcp_servers_config():
    """mcp_servers.json を読み {name: {command|url, ...}} を返す。"""
    try:
        with open(mcp_config_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        raise ApiError(f"cannot read mcp_servers.json: {e}")
    servers = d.get("mcpServers") if isinstance(d, dict) else None
    if not isinstance(servers, dict):
        return {}
    return {str(n): c for n, c in servers.items()
            if isinstance(c, dict) and (c.get("command") or c.get("url"))}


def mcp_save_config(text):
    """設定JSONテキストを検証して mcp_servers.json へ保存する。

    oauth.client_secret に平文が書かれていた場合はOSの資格情報
    ストア(credential_store)へ移し、設定ファイルには
    '$store:<key>' 参照だけを残す(APIキーと同じ方針で
    ストア保存に失敗した場合は平文では保存しない)。
    実際に保存したJSONテキストを返す。
    空欄は「MCPサーバなし」として {"mcpServers": {}} に正規化する。
    """
    if not (text or "").strip():
        text = '{"mcpServers": {}}'
    try:
        d = json.loads(text)
    except Exception as e:
        raise ApiError(f"invalid JSON: {e}")
    if not isinstance(d, dict) \
            or not isinstance(d.get("mcpServers"), dict):
        raise ApiError('use {"mcpServers": {...}} format')
    migrated = False
    for name, conf in d["mcpServers"].items():
        oc = conf.get("oauth") if isinstance(conf, dict) else None
        sec = oc.get("client_secret") if isinstance(oc, dict) else None
        if not isinstance(sec, str) or not sec \
                or sec.startswith(MCP_SECRET_REF) \
                or (sec.startswith("<") and sec.endswith(">")):
            continue                      # 既に参照 or 未記入の雛形
        key = _mcp_secret_key(name, "client_secret")
        if not credential_store.set_secret(key, sec):
            raise ApiError(
                f"could not save client_secret for '{name}' to the "
                f"credential store (backend={credential_store.backend()}); "
                "not saved in plain text.")
        oc["client_secret"] = MCP_SECRET_REF + key
        migrated = True
    out = (json.dumps(d, ensure_ascii=False, indent=2)
           if migrated else text)
    os.makedirs(os.path.dirname(mcp_config_path()), exist_ok=True)
    with open(mcp_config_path(), "w", encoding="utf-8") as f:
        f.write(out)
    return out


def _loads_rpc(text):
    """JSON-RPCメッセージ(単一orバッチ)を列挙する。"""
    try:
        d = json.loads(text)
    except Exception:
        return
    for m in (d if isinstance(d, list) else [d]):
        if isinstance(m, dict):
            yield m


def _iter_rpc_msgs(raw, ctype=""):
    """HTTP応答本文からJSON-RPCメッセージを列挙する。

    application/json は単一/バッチそのまま、text/event-stream は
    各SSEイベントの data: ペイロード(複数行連結可)が1メッセージ。
    """
    if "text/event-stream" in (ctype or ""):
        data_lines = []
        for line in raw.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif not line.strip() and data_lines:
                yield from _loads_rpc("\n".join(data_lines))
                data_lines = []
        if data_lines:
            yield from _loads_rpc("\n".join(data_lines))
    else:
        yield from _loads_rpc(raw)


def _mcp_error(m):
    e = m.get("error")
    if isinstance(e, dict):
        e = e.get("message", e)
    return f"MCP error: {e}"


def _oauth_request(oc, body, timeout=30.0):
    """トークンエンドポイントへform-encoded POST(RFC 6749 Basic認証)。

    @returns {"access_token","refresh_token"?,"expires_at"} のdict
    """
    turl = oc.get("token_url") or ""
    if not turl:
        raise ApiError("oauth.token_url is empty")
    cid = _resolve_secret_ref(oc.get("client_id")) or ""
    csec = _resolve_secret_ref(oc.get("client_secret")) or ""
    body = dict(body)
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Accept": "application/json"}
    if csec:
        # confidential client: RFC 6749 Basic認証
        cred = (f"{urllib.parse.quote(cid)}:"
                f"{urllib.parse.quote(csec)}")
        headers["Authorization"] = (
            "Basic " + base64.b64encode(cred.encode()).decode())
    elif cid:
        body.setdefault("client_id", cid)   # public client
    _require_http_scheme(turl)
    req = urllib.request.Request(
        turl, data=urllib.parse.urlencode(body).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # _require_http_schemeでhttp/httpsのみ許可
            d = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # nosec B110  # 設計上の許容
            pass
        raise ApiError(
            f"token fetch HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"token fetch connection failed: {e.reason}") from e
    tok = d.get("access_token")
    if not tok:
        raise ApiError(f"Invalid token response: {str(d)[:200]}")
    # expires_in から60秒の余裕を持たせて期限を計算
    return {"access_token": tok,
            "refresh_token": d.get("refresh_token"),
            "expires_at": (time.time()
                           + float(d.get("expires_in") or 3600) - 60)}


def _oauth_token(oc, timeout=30.0):
    """client_credentialsでトークン取得 → (access_token, expires_at)。"""
    body = {"grant_type": "client_credentials"}
    if oc.get("scope"):
        body["scope"] = oc["scope"]
    for k, v in (oc.get("extra") or {}).items():
        body[str(k)] = str(v)
    t = _oauth_request(oc, body, timeout)
    return t["access_token"], t["expires_at"]


def _mcp_tokens_path():
    """OAuthトークンの永続化先。"""
    return os.path.join(_registry_dir(), "mcp_tokens.json")


def _mcp_token_load(name):
    try:
        with open(_mcp_tokens_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        t = d.get(name) if isinstance(d, dict) else None
        return t if isinstance(t, dict) else None
    except Exception:
        return None


def _mcp_token_save(name, tok):
    """{access_token, refresh_token?, expires_at} を保存する。"""
    try:
        try:
            with open(_mcp_tokens_path(), "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        if not isinstance(d, dict):
            d = {}
        d[name] = tok
        os.makedirs(os.path.dirname(_mcp_tokens_path()), exist_ok=True)
        with open(_mcp_tokens_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
    except Exception:  # nosec B110  # 設計上の許容
        pass                       # 保存失敗は致命的ではない


def _mcp_token_delete(name):
    try:
        with open(_mcp_tokens_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and name in d:
            del d[name]
            with open(_mcp_tokens_path(), "w",
                      encoding="utf-8") as f:
                json.dump(d, f, indent=1)
    except Exception:  # nosec B110  # 設計上の許容
        pass


def _oauth_authorize(oc, timeout=180.0, on_status=None, is_aborted=None):
    """authorization_code + PKCE でユーザー同意型トークンを取得する。

    ローカルHTTPリスナ(既定 http://127.0.0.1:8020/callback)を立てて
    ブラウザを開き、コールバックの code をトークンに交換する。
    oauth.authorize_url が必須。client_secret あれば Basic 認証。
    is_aborted() がTrueを返すと待機を打ち切ってApiErrorを返す。
    @returns _oauth_request() のdict
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer
    aurl = oc.get("authorize_url") or ""
    if not aurl:
        raise ApiError("oauth.authorize_url is empty")
    redir = oc.get("redirect_uri") or "http://127.0.0.1:8020/callback"
    got = {}

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            body = ("<html><body><h3>Authentication completed. "
                    "You can return to QGIS.</h3></body></html>"
                    ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",
                             "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    try:
        httpd = HTTPServer(
            ("127.0.0.1", urllib.parse.urlparse(redir).port or 8020),
            _H)
    except OSError:
        # ポート占有時はエフェメラル。redirect_uriもそれに合わせる
        # (RFC 8252ではloopbackはポート問わず許容)
        httpd = HTTPServer(("127.0.0.1", 0), _H)
        redir = (f"http://127.0.0.1:{httpd.server_address[1]}"
                 "/callback")
    state = secrets.token_urlsafe(16)
    ver = secrets.token_urlsafe(64)
    chal = base64.urlsafe_b64encode(
        hashlib.sha256(ver.encode()).digest()).rstrip(b"=").decode()
    q = {"response_type": "code",
         "client_id": oc.get("client_id") or "",
         "redirect_uri": redir,
         "state": state,
         "code_challenge": chal,
         "code_challenge_method": "S256"}
    if oc.get("scope"):
        q["scope"] = oc["scope"]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        webbrowser.open(aurl + "?" + urllib.parse.urlencode(q))
        host = urllib.parse.urlparse(aurl).netloc
        hint = (f"If it still fails, check the app settings:"
                f" ①Redirect URI '{redir}' is registered"
                " ②OAuth2 standard (authorization_code) is enabled"
                " ③client_id/secret match")
        if on_status:
            on_status(
                f"Complete OAuth sign-in in the browser: {host}."
                + hint)
        deadline = time.time() + timeout
        while "code" not in got and "error" not in got:
            if is_aborted and is_aborted():
                raise ApiError("OAuth sign-in aborted")
            if time.time() > deadline:
                raise ApiError(
                    "OAuth sign-in timed out "
                    "(consent was not completed in the browser). " + hint)
            time.sleep(0.3)
    finally:
        httpd.shutdown()
        httpd.server_close()
    if got.get("error"):
        raise ApiError(f"OAuth error: {got['error']} "
                       f"{got.get('error_description') or ''}。" + hint)
    if got.get("state") != state:
        raise ApiError("OAuth state mismatch (CSRF check)")
    try:
        return _oauth_request(oc, {
            "grant_type": "authorization_code",
            "code": got["code"],
            "redirect_uri": redir,
            "code_verifier": ver}, timeout)
    except ApiError as e:
        raise ApiError(f"{e}。{hint}") from e


class _McpHttp:
    """MCP Streamable HTTPクライアント(POST→JSON or SSE)。

    cfg.oauth がある場合はトークンを取得し Authorization: Bearer
    を付ける。authorize_url あれば authorization_code+PKCE
    (ブラウザでユーザー同意、トークンは ~/.qgis-live/mcp_tokens.json
    に永続化し refresh_token で更新)、無ければ client_credentials。
    """

    def __init__(self, cfg, name="", on_status=None, is_aborted=None):
        self.url = (cfg.get("url") or "").rstrip("/")
        if not self.url:
            raise ApiError("MCP server url is empty")
        self.headers = {str(k): str(_resolve_secret_ref(v) or "")
                        for k, v in (cfg.get("headers") or {}).items()}
        self.oauth = cfg.get("oauth") or None
        self.name = name
        self._status = on_status or (lambda m: None)
        self._aborted = is_aborted or (lambda: False)
        self._tok, self._tok_exp = None, 0.0
        self._stale = False       # 401を受けたら保存トークンを疑う
        self.session_id = None
        self._next = itertools.count(1)

    def _obtain_token(self, timeout):
        """access_tokenを解決する: 保存済み→refresh→新規取得。"""
        oc = self.oauth
        st = _mcp_token_load(self.name)
        if st and st.get("access_token"):
            if not self._stale \
                    and time.time() < st.get("expires_at", 0):
                return st["access_token"], st["expires_at"]
            if st.get("refresh_token"):
                try:
                    t = _oauth_request(oc, {
                        "grant_type": "refresh_token",
                        "refresh_token": st["refresh_token"]},
                        timeout)
                    _mcp_token_save(self.name, t)
                    self._stale = False
                    return t["access_token"], t["expires_at"]
                except ApiError:
                    _mcp_token_delete(self.name)   # 再認可へ
        if oc.get("authorize_url"):
            self._status(
                f"MCP '{self.name}': complete OAuth sign-in in the browser")
            t = _oauth_authorize(oc, on_status=self._status,
                                 is_aborted=self._aborted)
            _mcp_token_save(self.name, t)
        else:
            tok, exp = _oauth_token(oc, timeout)
            t = {"access_token": tok, "expires_at": exp}
            _mcp_token_save(self.name, t)
        self._stale = False
        return t["access_token"], t["expires_at"]

    def _auth_headers(self, timeout):
        if not self.oauth:
            return {}
        if not self._tok or time.time() >= self._tok_exp:
            self._tok, self._tok_exp = self._obtain_token(timeout)
        return {"Authorization": f"Bearer {self._tok}"}

    def _post(self, msg, timeout):
        # OAuth利用時は401でトークンを破棄して1回だけ再試行
        for attempt in range(2 if self.oauth else 1):
            hdrs = {"Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    **self._auth_headers(timeout), **self.headers}
            if self.session_id:
                hdrs["Mcp-Session-Id"] = self.session_id
            _require_http_scheme(self.url)
            req = urllib.request.Request(
                self.url, data=json.dumps(msg).encode("utf-8"),
                headers=hdrs, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # _require_http_schemeでhttp/httpsのみ許可
                    sid = r.headers.get("Mcp-Session-Id")
                    if sid:
                        self.session_id = sid
                    ctype = r.headers.get("Content-Type", "")
                    raw = r.read().decode("utf-8", "replace")
                    status = r.status
            except urllib.error.HTTPError as e:
                if e.code == 401 and self.oauth and attempt == 0:
                    # トークン失効→保存分も疑い、refresh/再認可で再試行
                    self._tok = None
                    self._stale = True
                    continue
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                raise ApiError(
                    f"HTTP {e.code}: {detail or e.reason}") from e
            except urllib.error.URLError as e:
                raise ApiError(f"Connection failed: {e.reason}") from e
            if status == 202 or not raw.strip():
                return []                    # 通知応答(空)
            return list(_iter_rpc_msgs(raw, ctype))

    def request(self, method, params, timeout=30.0):
        mid = next(self._next)
        msgs = self._post({"jsonrpc": "2.0", "id": mid, "method": method,
                           "params": params or {}}, timeout)
        for m in msgs:
            if m.get("id") == mid:
                if "error" in m:
                    raise ApiError(_mcp_error(m))
                return m.get("result")
        raise ApiError(f"MCP {method}: no response returned")

    def notify(self, method, params):
        try:
            self._post({"jsonrpc": "2.0", "method": method,
                        "params": params or {}}, 15.0)
        except ApiError:  # nosec B110  # 設計上の許容
            pass

    def close(self):
        pass


class _McpStdio:
    """MCP stdioクライアント(子プロセスと改行区切りJSON-RPC)。"""

    def __init__(self, cfg):
        command = cfg.get("command") or ""
        if not command:
            raise ApiError("MCP server command is empty")
        exe = shutil.which(command) or command
        env = dict(os.environ)
        env.update({str(k): str(_resolve_secret_ref(v) or "")
                    for k, v in (cfg.get("env") or {}).items()})
        kw = {}
        cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if cf:
            kw["creationflags"] = cf      # コンソール窓を出さない(Windows)
        try:
            self._p = subprocess.Popen(  # nosec B603  # ユーザ設定のMCPサーバ起動(仕様)
                [exe] + [str(a) for a in cfg.get("args") or []],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env, **kw)
        except OSError as e:
            raise ApiError(f"failed to start MCP server: {e}") from e
        self._pending = {}
        self._next = itertools.count(1)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while True:
            line = self._p.stdout.readline()
            if not line:
                break
            try:
                m = json.loads(line.decode("utf-8", "replace"))
            except Exception:  # nosec B112  # 設計上の許容
                continue
            slot = self._pending.get(m.get("id"))
            if slot:
                slot[1]["res"] = m
                slot[0].set()
        for ev, box in self._pending.values():   # プロセス終了→全失敗
            box["res"] = {"error": "MCP server exited"}
            ev.set()

    def _send(self, msg):
        try:
            self._p.stdin.write(
                (json.dumps(msg, ensure_ascii=False) + "\n")
                .encode("utf-8"))
            self._p.stdin.flush()
        except Exception as e:
            raise ApiError(f"failed to write to MCP server: {e}") from e

    def request(self, method, params, timeout=30.0):
        mid = next(self._next)
        ev = threading.Event()
        box = {}
        self._pending[mid] = (ev, box)
        try:
            self._send({"jsonrpc": "2.0", "id": mid, "method": method,
                        "params": params or {}})
            if not ev.wait(timeout):
                raise ApiError(f"MCP {method}: timeout ({timeout}s)")
            m = box.get("res") or {}
            if "error" in m:
                raise ApiError(_mcp_error(m))
            return m.get("result")
        finally:
            self._pending.pop(mid, None)

    def notify(self, method, params):
        try:
            self._send({"jsonrpc": "2.0", "method": method,
                        "params": params or {}})
        except ApiError:  # nosec B110  # 設計上の許容
            pass

    def close(self):
        try:
            self._p.terminate()
        except Exception:  # nosec B110  # 設計上の許容
            pass


def _mcp_result_text(r):
    """tools/call のresultをテキストにする。isErrorはApiError。"""
    if not isinstance(r, dict):
        return str(r)
    parts = [c.get("text", "") for c in r.get("content") or []
             if isinstance(c, dict) and c.get("type") == "text"]
    text = "\n".join(p for p in parts if p)
    if not text:
        text = json.dumps(r, ensure_ascii=False)
    if r.get("isError"):
        raise ApiError(text[:500])
    return text


class McpSession:
    """接続済みMCPサーバ。tools=TOOL形の一覧, call()で実行。

    transportはcfgで決まる: command→stdio / url→Streamable HTTP。
    """

    def __init__(self, name, cfg, timeout=30.0, on_status=None,
                 is_aborted=None):
        self.name = name
        self._io = (_McpStdio(cfg) if cfg.get("command")
                    else _McpHttp(cfg, name=name, on_status=on_status,
                                  is_aborted=is_aborted))
        self._io.request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "qgis-live-driver",
                           "version": "0.6"},
        }, timeout)
        self._io.notify("notifications/initialized", {})
        r = self._io.request("tools/list", {}, timeout) or {}
        self.tools = [t for t in r.get("tools") or [] if t.get("name")]

    def call(self, tool, args, timeout=120.0):
        r = self._io.request("tools/call",
                             {"name": tool, "arguments": args or {}},
                             timeout)
        return _mcp_result_text(r)

    def close(self):
        self._io.close()


def _safe_name(s):
    """OpenAIのツール名制約([A-Za-z0-9_-])に寄せる。"""
    return re.sub(r"[^A-Za-z0-9_-]", "_", s or "")


def mcp_discover(timeout=30.0, on_status=None, is_aborted=None):
    """設定ファイルの全MCPサーバへ接続しツール一覧を集約する。

    @param on_status: 進行状況コールバック(OAuth認証待ち等をUIへ)
    @param is_aborted: Trueを返すと接続処理を打ち切るコールバック
    @returns {"tools": [mangled TOOL形], "callers": {name: fn},
              "sessions": {name: McpSession}, "errors": {name: str}}
    """
    out = {"tools": [], "callers": {}, "sessions": {}, "errors": {}}
    for name, cfg in mcp_servers_config().items():
        if is_aborted and is_aborted():
            break
        try:
            sess = McpSession(name, cfg, timeout, on_status=on_status,
                              is_aborted=is_aborted)
        except ApiError as e:
            out["errors"][name] = str(e)
            continue
        except Exception as e:
            out["errors"][name] = f"{type(e).__name__}: {e}"
            continue
        out["sessions"][name] = sess
        for t in sess.tools:
            mangled = ("mcp_" + _safe_name(name)
                       + "__" + _safe_name(t["name"]))[:64]
            out["tools"].append({
                "name": mangled,
                "description":
                    f"[{name}] {t.get('description') or ''}".strip(),
                "inputSchema": t.get("inputSchema")
                or {"type": "object", "properties": {}},
            })
            out["callers"][mangled] = (
                lambda a, _s=sess, _t=t["name"]: _s.call(_t, a))
    return out


_EXTRA_TOOLS = []
_EXTRA_TOOL_CALLERS = {}


def register_extra_tools(tools, callers):
    """外部MCP由来ツールを openai_tools/gemini_tools に反映する。

    呼び出しはパネルのワーカースレッド側で行う。
    """
    _EXTRA_TOOLS[:] = list(tools or [])
    _EXTRA_TOOL_CALLERS.clear()
    _EXTRA_TOOL_CALLERS.update(callers or {})


def run_extra_tool(name, args):
    """外部MCPツールを実行してテキストを返す。"""
    fn = _EXTRA_TOOL_CALLERS.get(name)
    if fn is None:
        raise ApiError(f"Unknown external tool: {name}")
    return fn(args or {})


# ---- プロバイダ抽象化 ----
# 各プロバイダは以下のインターフェースを持つ:
#   build_messages(system, history, user_text, user_images=None)
#       -> ワイヤ形式のメッセージ列
#       historyの要素は {"role","content","images"?}(images=PNGパス列)、
#       user_imagesは新規ユーザメッセージに添付するPNGパス列。
#   send(base, key, model, system, msgs, timeout) -> 応答JSON
#   parse(data) -> {"text": str, "calls": [{"id","name","args"}], "raw": ...}
#   append_exchange(msgs, turn, results)
#       results: callsに対応する [{"text": str, "image": path|None}]
#       raw assistant + プロバイダ固有のツール結果エントリをmsgsに積む
#   list_models(base, key, timeout) -> [モデルID, ...]
#   list_model_entries(base, key, timeout) -> [{id, メタ情報...}]


class OpenAIProvider:
    id = "openai"
    label = PROVIDERS["openai"]["label"]

    def list_model_entries(self, base, key, timeout=30.0):
        """GET {base}/models → [{id, 価格/modality等(あれば)}, ...]

        OpenRouter等は pricing・context_length・architecture.modality
        を返すため、あれば拾ってメタ情報表示に使う。
        """
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        data = _get_json(openai_models_url(base), headers, timeout)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ApiError(f"Invalid response format: {str(data)[:300]}")
        out = []
        for i in items:
            if not isinstance(i, dict) or not i.get("id"):
                continue
            e = {"id": i["id"]}
            arch = i.get("architecture") or {}
            for k in ("modality", "input_modalities", "output_modalities"):
                if arch.get(k):
                    e[k] = arch[k]
            if i.get("pricing"):
                e["pricing"] = i["pricing"]
            if i.get("context_length"):
                e["context_length"] = i["context_length"]
            out.append(e)
        return sorted(out, key=lambda e: e["id"])

    def list_models(self, base, key, timeout=30.0):
        """GET {base}/models → data[].id をソートして返す。"""
        return [e["id"] for e in self.list_model_entries(base, key, timeout)]

    def build_messages(self, system, history, user_text,
                       user_images=None):
        msgs = [{"role": "system", "content": system}]
        for m in history:
            d = dict(m)
            imgs = d.pop("images", None)  # ワイヤ形式に無いキーは剥がす
            if imgs:
                d["content"] = user_content(
                    m.get("content") or "", imgs)
            msgs.append(d)
        msgs.append({"role": "user",
                     "content": user_content(user_text, user_images)})
        return msgs

    def send(self, base, key, model, system, msgs, timeout=180.0):
        return chat_completions(base, key, model, msgs,
                                tools=openai_tools(), timeout=timeout)

    def parse(self, data):
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            calls.append({
                "id": tc.get("id"),
                "name": fn.get("name") or "",
                "args": parse_tool_arguments(fn.get("arguments")),
            })
        return {"text": msg.get("content") or "",
                "calls": calls, "raw": msg,
                "usage": parse_usage(data)}

    def append_exchange(self, msgs, turn, results):
        msgs.append(turn["raw"])
        for c, r in zip(turn["calls"], results):
            content = r["text"]
            if r.get("image"):
                img = image_message_content(r["image"], note=r["text"])
                if img is not None:
                    content = img
            msgs.append({"role": "tool",
                         "tool_call_id": c.get("id"),
                         "content": content})


class GeminiProvider:
    id = "gemini"
    label = PROVIDERS["gemini"]["label"]

    def list_model_entries(self, base, key, timeout=30.0):
        """GET {base}/models → generateContent対応モデルの
        [{id, input/output_token_limit}, ...] を返す。"""
        headers = {"x-goog-api-key": key} if key else {}
        data = _get_json(gemini_models_url(base), headers, timeout)
        items = data.get("models") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ApiError(f"Invalid response format: {str(data)[:300]}")
        out = []
        for m in items:
            name = (m.get("name") or "").split("/")[-1]
            methods = m.get("supportedGenerationMethods")
            if not name or (methods and "generateContent" not in methods):
                continue
            e = {"id": name}
            if m.get("inputTokenLimit"):
                e["input_token_limit"] = m["inputTokenLimit"]
            if m.get("outputTokenLimit"):
                e["output_token_limit"] = m["outputTokenLimit"]
            out.append(e)
        return sorted({e["id"]: e for e in out}.values(),
                      key=lambda e: e["id"])

    def list_models(self, base, key, timeout=30.0):
        """GET {base}/models → generateContent対応モデルを返す。

        応答の models[].name は "models/<id>" 形式なので接頭辞を剥がす。
        supportedGenerationMethods に generateContent が無いモデル
        (embed等)は除外する。
        """
        return [e["id"] for e in self.list_model_entries(base, key, timeout)]

    def _parts(self, text, image_paths=None):
        parts = [{"text": text}] if text else []
        parts += [p for p in
                  (image_inline_part(x) for x in image_paths or [])
                  if p is not None]
        return parts

    def build_messages(self, system, history, user_text,
                       user_images=None):
        contents = []
        for m in history:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role,
                             "parts": self._parts(
                                 m.get("content", ""), m.get("images"))})
        contents.append({"role": "user",
                         "parts": self._parts(user_text, user_images)})
        return contents

    def send(self, base, key, model, system, msgs, timeout=180.0):
        return gemini_generate(base, key, model, system, msgs,
                               tools=gemini_tools(), timeout=timeout)

    def parse(self, data):
        cand = (data.get("candidates") or [{}])[0]
        content = cand.get("content") or {}
        parts = content.get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        calls = [{"id": None,
                  "name": (p.get("functionCall") or {}).get("name") or "",
                  "args": (p.get("functionCall") or {}).get("args") or {}}
                 for p in parts if "functionCall" in p]
        raw = {"role": "model", "parts": parts}
        if not text and not calls:
            raise ApiError(
                f"Response empty or blocked: finishReason="
                f"{cand.get('finishReason')} {str(data)[:200]}")
        return {"text": text, "calls": calls, "raw": raw,
                "usage": parse_usage(data)}

    def append_exchange(self, msgs, turn, results):
        # モデルのfunctionCallを含むcontentをそのまま積み、
        # 全functionResponseを1つのuserターンにまとめて返す
        msgs.append(turn["raw"])
        parts = []
        for c, r in zip(turn["calls"], results):
            parts.append({"functionResponse": {
                "name": c["name"],
                "response": {"result": r["text"]},
            }})
            if r.get("image"):
                part = image_inline_part(r["image"])
                if part is not None:
                    parts.append(part)
        msgs.append({"role": "user", "parts": parts})


class CopilotProvider(OpenAIProvider):
    """GitHub Copilot。

    メッセージ形式はOpenAI互換なので build_messages/parse/
    append_exchange は OpenAIProvider を継承。違いは認証だけ:
    APIキー欄のGitHubトークンを copilot_session() で短期トークンに
    交換し、契約種別に応じたAPI先(endpoints.api)を使う。
    """
    id = "copilot"
    label = PROVIDERS["copilot"]["label"]

    def list_model_entries(self, base, key, timeout=30.0):
        """GET {api}/models → chat対応モデル一覧。

        Copilot APIの応答は capabilities.type / policy.state /
        capabilities.limits.max_context_window_tokens /
        supports.vision を持つため、種別とコンテキスト長の判定に使う。
        capabilitiesを持たない応答(互換プロキシ等)は全件採用する。
        """
        tok, api_base = copilot_session(key, base)
        data = _get_json(
            api_base.rstrip("/") + "/models",
            {"Authorization": f"Bearer {tok}", **COPILOT_HEADERS},
            timeout)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ApiError(f"Invalid response format: {str(data)[:300]}")
        out = []
        for m in items:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            caps = m.get("capabilities")
            if not isinstance(caps, dict):
                out.append({"id": m["id"]})
                continue
            if caps.get("type") not in (None, "chat"):
                continue
            if (m.get("policy") or {}).get("state") == "disabled":
                continue
            e = {"id": m["id"],
                 "input_modalities":
                     ["text", "image"]
                     if (caps.get("supports") or {}).get("vision")
                     else ["text"]}
            lim = caps.get("limits") or {}
            if lim.get("max_context_window_tokens"):
                e["context_length"] = lim["max_context_window_tokens"]
            out.append(e)
        return sorted(out, key=lambda e: e["id"])

    def send(self, base, key, model, system, msgs, timeout=180.0):
        tok, api_base = copilot_session(key, base)
        return chat_completions(api_base, tok, model, msgs,
                                tools=openai_tools(), timeout=timeout,
                                headers=COPILOT_HEADERS)


_PROVIDERS = {"openai": OpenAIProvider, "gemini": GeminiProvider,
              "copilot": CopilotProvider}


def get_provider(provider):
    """プロバイダID → プロバイダインスタンス。"""
    try:
        return _PROVIDERS[provider]()
    except KeyError:
        raise ApiError(f"Unknown provider: {provider}")


def list_models(provider, base, key, timeout=30.0):
    """プロバイダのエンドポイントから利用可能なモデルID一覧を返す。"""
    return get_provider(provider).list_models(base, key, timeout)


def list_model_infos(provider, base, key, timeout=30.0):
    """モデル一覧をメタ情報付きで返す。

    @returns [model_info()のdict, ...] (idでソート済み)
    """
    entries = get_provider(provider).list_model_entries(base, key, timeout)
    return [model_info(e) for e in entries]
