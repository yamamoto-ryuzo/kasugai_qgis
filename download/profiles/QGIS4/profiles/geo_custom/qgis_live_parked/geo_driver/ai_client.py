"""AIアシスタントパネル用のLLM APIクライアント(stdlibのみ)。

ai_panel.py(Qt層)から呼ばれる。QGIS/Qtに依存しないためpytest対象。

対応プロバイダ:
  - "openai": OpenAI Chat Completions 互換
    (POST {base}/chat/completions, tools=function calling)。
    Ollama・LM Studio・OpenRouter・xAI Grok・Mistral・Groq・
    DeepSeek等の互換サーバもbase URLを変えるだけで使える
    (例: http://localhost:11434/v1)。Bedrock/Vertex等も
    LiteLLM等の互換プロキシ経由なら同じ経路で繋がる
  - "anthropic": Anthropic Messages API
    (POST {base}/v1/messages, tools=input_schema。
    認証は x-api-key + anthropic-version ヘッダ)
  - "gemini": Google Gemini API
    (POST {base}/models/{model}:generateContent, functionDeclarations。
    認証は x-goog-api-key ヘッダ)
  - "azure": Azure OpenAI Service
    (Chat CompletionsはOpenAI互換だが認証は api-key ヘッダ、
    URLは {resource}/openai/deployments/<deployment>/chat/completions
    ?api-version=…。model欄はデプロイ名)
  - "copilot": GitHub Copilot
    (OpenAI互換の {api}/chat/completions。APIキー欄のGitHubトークンを
    api.github.com/copilot_internal/v2/token で短期トークンに交換し、
    応答の endpoints.api をAPI先に使う。Copilot契約が必要。
    「GitHubでサインイン」ボタンはOAuthデバイスフローでトークンを取得)

ツール定義は mcp_http.TOOLS(MCP/RESTと同一)を各プロバイダの
スキーマに変換して使う。実行は LiveDriver.submit() に委譲するため
このモジュール自体はQGISを触らない。

プロバイダ抽象化: OpenAIProvider/AnthropicProvider/GeminiProvider/
AzureOpenAIProvider/CopilotProvider が build_messages / send /
parse / append_exchange を実装し、
ai_panel のエージェントループはプロバイダ非依存で回る。
"""

import base64
import hashlib
import inspect
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
        return QCoreApplication.translate("geo_driver", src)
    return src


_F_PRICE_TOKENS = QT_TRANSLATE_NOOP(
    "geo_driver", "Input {0} / Output {1} /1M tokens")
_F_PRICE_IMG = QT_TRANSLATE_NOOP(
    "geo_driver", "{0} /image (image generation)")
_F_KIND = QT_TRANSLATE_NOOP("geo_driver", "Kind: {0}")
_F_PRICE = QT_TRANSLATE_NOOP("geo_driver", "Price: {0} ({1})")
_F_CONTEXT = QT_TRANSLATE_NOOP("geo_driver", "Context: {0} tokens")
_LBL_API_VALUE = QT_TRANSLATE_NOOP("geo_driver", "API value")
_LBL_REFERENCE = QT_TRANSLATE_NOOP("geo_driver", "reference")

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

# ---- Anthropic (Messages API) ----
ANTHROPIC_DEFAULT_BASE = "https://api.anthropic.com"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-5"
ANTHROPIC_VERSION = "2023-06-01"
# Messages APIはmax_tokens必須。全現行モデルが許容する値を既定にする
ANTHROPIC_MAX_TOKENS = 8192

# ---- Azure OpenAI ----
# api-versionクエリ省略時の既定(2024-10-21=GAのv1 API)
AZURE_API_VERSION = "2024-10-21"
AZURE_DEFAULT_MODEL = "gpt-4o"

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
        "label": QT_TRANSLATE_NOOP("geo_driver", "OpenAI-compatible"),
        "tag": "【API】",
        "base": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "API key (may be empty for local servers)"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "https://api.openai.com/v1  or  http://localhost:11434/v1"),
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "tag": "【API】",
        "base": ANTHROPIC_DEFAULT_BASE,
        "model": ANTHROPIC_DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "Anthropic API key (issued in the Anthropic Console)"),
        "endpoint_hint": "https://api.anthropic.com",
    },
    "gemini": {
        "label": "Gemini",
        "tag": "【API】",
        "base": GEMINI_DEFAULT_BASE_URL,
        "model": GEMINI_DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "Gemini API key (issued in AI Studio)"),
        "endpoint_hint": "https://generativelanguage.googleapis.com/v1beta",
    },
    "azure": {
        "label": "Azure OpenAI",
        "tag": "【API】",
        "base": ("https://<resource>.openai.azure.com"
                 "/openai/deployments/<deployment>"),
        "model": AZURE_DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "Azure OpenAI API key (KEY1/KEY2 of the resource)"),
        "endpoint_hint": ("https://<resource>.openai.azure.com"
                          "/openai/deployments/<deployment>"),
    },
    "copilot": {
        "label": "GitHub Copilot",
        "tag": "【API】",
        "base": COPILOT_DEFAULT_BASE,
        "model": COPILOT_DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "GitHub token (Copilot subscription required; can be "
            "acquired automatically via \"Sign in with GitHub\")"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "https://api.githubcopilot.com  (URL of a compatible "
            "proxy such as copilot-api)"),
    },
    "devin_acp": {
        "label": "Devin",
        "tag": "【ACP】",
        "base": "",
        "model": "default",
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "not required (uses the IDE's Devin sign-in)"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "working directory for Devin sessions "
            "(default: user home)"),
    },
    "copilot_acp": {
        "label": "GitHub Copilot",
        "tag": "【ACP】",
        "base": "",
        "model": "default",
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "not required (uses the Copilot CLI / gh sign-in)"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "working directory for Copilot CLI sessions "
            "(default: user home)"),
    },
    "acp": {
        "label": QT_TRANSLATE_NOOP("geo_driver", "Custom agent"),
        "tag": "【ACP】",
        "base": "",
        "model": "default",
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "working directory for the agent session "
            "(default: user home)"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "ACP launch command for an arbitrary agent CLI "
            "(e.g. my-agent acp)"),
    },
    "devin_bridge": {
        "label": "Devin",
        "tag": "【ブリッジ】",
        "base": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "API key of the backing OpenAI-compatible endpoint "
            "(the chat LLM delegates work to Devin via the "
            "qgis_devin_* tools)"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "OpenAI-compatible endpoint driving the delegation chat "
            "(e.g. https://api.openai.com/v1)"),
    },
    "copilot_bridge": {
        "label": "GitHub Copilot",
        "tag": "【ブリッジ】",
        "base": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "API key of the backing OpenAI-compatible endpoint "
            "(the chat LLM delegates work to Copilot CLI via the "
            "qgis_copilot_* tools)"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "OpenAI-compatible endpoint driving the delegation chat "
            "(e.g. https://api.openai.com/v1)"),
    },
    "agent": {
        "label": QT_TRANSLATE_NOOP("geo_driver", "External agent"),
        "tag": "【ブリッジ】",
        "base": "",
        "model": "default",
        "key_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "Bearer token for the agent endpoint (optional)"),
        "endpoint_hint": QT_TRANSLATE_NOOP(
            "geo_driver",
            "agent endpoint URL accepting POST {message,...} and "
            "replying {reply: ...} "
            "(e.g. http://127.0.0.1:8511/agent)"),
    },
}

# 表示順は【API】→【ACP】→【ブリッジ】の分類順
# (kasugai_canvas の PROVIDER_ORDER と同じ規則)
PROVIDER_ORDER = ["gemini", "copilot", "azure", "anthropic", "openai",
                  "copilot_acp", "devin_acp", "acp",
                  "copilot_bridge", "devin_bridge", "agent"]

# プロバイダ種別タグ → 接続方式の説明(ツールチップ・ヘルプ用)
PROVIDER_TAGS = {
    "【API】": QT_TRANSLATE_NOOP(
        "geo_driver",
        "Direct LLM API — each message is sent to the model and the "
        "panel runs the tool loop itself"),
    "【ACP】": QT_TRANSLATE_NOOP(
        "geo_driver",
        "Agent session — a Devin/Copilot CLI session is the chat "
        "engine and runs its own tool loop (the panel is a chat UI; "
        "no API key needed — uses the CLI/IDE sign-in; the endpoint "
        "field is the working directory)"),
    "【ブリッジ】": QT_TRANSLATE_NOOP(
        "geo_driver",
        "Delegation chat — a normal API chat with injected "
        "instructions to hand substantial work to an agent CLI via "
        "the qgis_devin_* / qgis_copilot_* tools (the panel still "
        "drives the tool loop; needs an API endpoint + key)"),
}

# ---- モデル一覧のメタ情報 ----

# モデル種別 → 表示ラベル。この順序でコンボをグループ化する。
MODEL_KINDS = [
    ("chat_vision",
     QT_TRANSLATE_NOOP("geo_driver", "Text (image input)")),
    ("chat", QT_TRANSLATE_NOOP("geo_driver", "Text")),
    ("image", QT_TRANSLATE_NOOP("geo_driver", "Image generation")),
    ("embed", QT_TRANSLATE_NOOP("geo_driver", "Embedding")),
    ("other", QT_TRANSLATE_NOOP("geo_driver", "Audio/Other")),
]
MODEL_KIND_LABELS = dict(MODEL_KINDS)

# プロバイダ既定エンドポイント利用時にコンボへ予め載せる推奨モデル
# (「取得」ボタンを押さなくても価格付きで選べるようにするため)。
# 実際に使えるかはAPIキーのプラン次第。取得で実一覧に置き換わる。
SUGGESTED_MODELS = {
    "openai": ["gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4.1",
               "gpt-4o-mini", "gpt-4o", "o4-mini"],
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-5",
                  "claude-haiku-4-5", "claude-opus-4-1",
                  "claude-sonnet-4", "claude-3-7-sonnet"],
    "gemini": ["gemini-3.8-flash", "gemini-3.5-flash",
               "gemini-3.1-flash-lite", "gemini-2.5-pro"],
    "azure": ["gpt-4o", "gpt-4.1", "gpt-5", "gpt-5-mini", "o4-mini"],
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
    Anthropic: usage.input_tokens/output_tokens
    Gemini: usageMetadata.promptTokenCount/candidatesTokenCount
    (thoughtsTokenCount も出力側に含める)
    """
    u = data.get("usage")
    if isinstance(u, dict):
        pin = u.get("prompt_tokens")
        pout = u.get("completion_tokens")
        if pin is not None or pout is not None:
            return {"in": pin or 0, "out": pout or 0}
        pin = u.get("input_tokens")
        pout = u.get("output_tokens")
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
  in the prompt, `prompts` = canned prompt text shown in the panel's
  suggestion list (the body is inserted into the user's input field
  when picked). You may create or update them when the user asks or
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
  - `prompts`: requests to register a frequently used instruction as
    a one-click suggestion ("add this to the suggestions"). The file
    body after the header becomes the text inserted into the input.
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


# ---- OpenAI Responses API (POST {base}/responses) ----
# CopilotのGPT-6系等、/chat/completions を受け付けず /responses 専用の
# モデル向け(GET /models の supported_endpoints で判別できる)。
# ワイヤ形式は異なるが、プロバイダ内部ではchat形式のmsgsを保持し、
# 送信時にだけResponses形式へ変換する(往復でtool_calls/tool結果が
# 混ざったmsgsを毎回まるごと変換するので状態を持たない)。

def responses_tools(tools):
    """OpenAI function calling形式 → Responses APIのtools形式。
    {"type":"function","function":{...}} をフラット化する。"""
    out = []
    for t in tools or []:
        if t.get("type") == "function" \
                and isinstance(t.get("function"), dict):
            d = {"type": "function"}
            d.update(t["function"])
            out.append(d)
        else:
            out.append(t)
    return out


def _responses_content_parts(content, role):
    """chat形式のcontent → Responsesのcontent parts
    (user=input_text/input_image, assistant=output_text)。"""
    text_t = "input_text" if role == "user" else "output_text"
    if isinstance(content, str):
        return [{"type": text_t, "text": content}]
    parts = []
    for p in content or []:
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        if t == "text":
            parts.append({"type": text_t, "text": p.get("text") or ""})
        elif t == "image_url":
            parts.append({"type": "input_image",
                          "image_url":
                              (p.get("image_url") or {}).get("url") or ""})
        elif t in ("input_text", "input_image"):
            parts.append(p)
    return parts


def _tool_result_output(content):
    """chat形式のtool結果content → function_call_output.output。
    文字列はそのまま、画像を含むparts列はinput_*形式にする。"""
    if isinstance(content, str):
        return content
    parts = []
    for p in content or []:
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        if t == "text":
            parts.append({"type": "input_text", "text": p.get("text") or ""})
        elif t == "image_url":
            parts.append({"type": "input_image",
                          "image_url":
                              (p.get("image_url") or {}).get("url") or ""})
    return parts or json.dumps(content, ensure_ascii=False)


def openai_msgs_to_responses_input(msgs):
    """OpenAI chat形式msgs → (instructions, Responses API input items)。"""
    instr = []
    items = []
    for m in msgs or []:
        role = m.get("role")
        if role == "system":
            c = m.get("content")
            instr.append(
                c if isinstance(c, str)
                else "\n".join(p.get("text") or "" for p in c or []
                               if isinstance(p, dict)))
            continue
        if role == "assistant" and m.get("tool_calls"):
            if m.get("content"):
                items.append({"type": "message", "role": "assistant",
                              "content": _responses_content_parts(
                                  m["content"], "assistant")})
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                items.append({
                    "type": "function_call",
                    "call_id": tc.get("id") or "",
                    "name": fn.get("name") or "",
                    "arguments": (args if isinstance(args, str)
                                  else json.dumps(
                                      args or {}, ensure_ascii=False))})
            continue
        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": m.get("tool_call_id") or "",
                "output": _tool_result_output(m.get("content"))})
            continue
        items.append({"type": "message", "role": role,
                      "content": _responses_content_parts(
                          m.get("content"), role)})
    return "\n".join(x for x in instr if x), items


def responses_create(base, api_key, model, msgs, tools=None,
                     timeout=180.0, extra=None, headers=None):
    """POST {base}/responses (非ストリーミング)して応答JSONを返す。

    @param msgs: OpenAI chat形式メッセージ列(system含む)。
      systemメッセージはinstructionsフィールドへ移す
    """
    instr, inp = openai_msgs_to_responses_input(msgs)
    body = {"model": model, "input": inp, "store": False}
    if instr:
        body["instructions"] = instr
    if tools:
        body["tools"] = responses_tools(tools)
        body["tool_choice"] = "auto"
    if extra:
        body.update(extra)
    hdrs = dict(headers or {})
    if api_key:
        hdrs["Authorization"] = f"Bearer {api_key}"
    data = _post_json(base.rstrip("/") + "/responses",
                      hdrs, body, timeout)
    if not isinstance(data, dict) \
            or not isinstance(data.get("output"), list):
        raise ApiError(f"Invalid response format: {str(data)[:300]}")
    return data


def parse_responses_output(data):
    """Responses API応答 → parse()と同じ {"text","calls","raw","usage"}。
    rawはchat形式のassistantメッセージ(append_exchange互換)。"""
    text = []
    calls = []
    tool_calls = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if t == "message":
            for c in item.get("content") or []:
                if isinstance(c, dict) \
                        and c.get("type") == "output_text":
                    text.append(c.get("text") or "")
        elif t == "function_call":
            args = item.get("arguments")
            cid = item.get("call_id") or item.get("id")
            calls.append({"id": cid,
                          "name": item.get("name") or "",
                          "args": parse_tool_arguments(args)})
            tool_calls.append({
                "id": cid, "type": "function",
                "function": {
                    "name": item.get("name") or "",
                    "arguments": (args if isinstance(args, str)
                                  else json.dumps(
                                      args or {}, ensure_ascii=False))}})
    raw = {"role": "assistant", "content": "".join(text) or None}
    if tool_calls:
        raw["tool_calls"] = tool_calls
    return {"text": "".join(text), "calls": calls, "raw": raw,
            "usage": parse_usage(data)}


# model id → True で /responses 専用と記録する。
# Copilotの GET /models の supported_endpoints と、送信時の
# model_not_supported エラーからのフォールバックで学習する
_RESPONSES_ONLY_MODELS = {}


def _responses_only_error(e):
    """そのモデルが /chat/completions を受け付けない場合の
    エラーかを判定する。誤判定の場合 /responses 側が同様に
    失敗してそのエラーが返るだけなので広めに拾う。"""
    s = str(e).lower()
    # "The requested model is not supported." 等の文言揺れも拾う
    return ("not accessible via the /chat/completions" in s
            or "model_not_supported" in s
            or "not supported" in s)


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


# ---- Anthropic (Messages API) ----

def _anthropic_v1(base):
    """base URLを /v1 までの形に正規化する。"""
    u = (base or "").strip().rstrip("/")
    if not u:
        raise ApiError("API endpoint is not set")
    if u.endswith("/messages"):
        u = u[: -len("/messages")].rstrip("/")
    elif u.endswith("/models"):
        u = u[: -len("/models")].rstrip("/")
    if not u.endswith("/v1"):
        u += "/v1"
    return u


def anthropic_messages_url(base):
    """messagesのPOST先URL。"""
    return _anthropic_v1(base) + "/messages"


def anthropic_models_url(base):
    """models一覧のGET先URL。"""
    return _anthropic_v1(base) + "/models"


def anthropic_headers(api_key):
    """Messages APIの認証ヘッダ。"""
    h = {"anthropic-version": ANTHROPIC_VERSION}
    if api_key:
        h["x-api-key"] = api_key
    return h


def anthropic_tools(allowed=None):
    """mcp_http.TOOLS + INSTRUCTION_TOOLS + 外部MCPツールを
    Anthropic tools(input_schema)に変換する。"""
    out = []
    for t in TOOLS + INSTRUCTION_TOOLS + _EXTRA_TOOLS:
        if allowed is not None and _tool_short(t["name"]) not in allowed:
            continue
        out.append({
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        })
    return out


def anthropic_image_part(path):
    """PNGファイル→Anthropicのimageブロック(読めなければNone)。"""
    b64 = image_b64(path)
    if b64 is None:
        return None
    return {"type": "image",
            "source": {"type": "base64",
                       "media_type": "image/png",
                       "data": b64}}


def anthropic_content(text, image_paths):
    """テキスト+画像パス列をAnthropicのcontentにする。

    画像が無い場合は文字列のまま返す(ショートハンド形式)。
    """
    imgs = [p for p in
            (anthropic_image_part(x) for x in image_paths or [])
            if p is not None]
    if not imgs:
        return text or "(empty)"   # 空文字列contentはAPIが拒否する
    return ([{"type": "text", "text": text}] if text else []) + imgs


def anthropic_messages(base, api_key, model, system, messages,
                       tools=None, timeout=180.0, extra=None):
    """POST {base}/v1/messages (非ストリーミング)して応答JSONを返す。"""
    body = {"model": model, "max_tokens": ANTHROPIC_MAX_TOKENS,
            "messages": messages}
    if system:
        body["system"] = system
    if tools:
        body["tools"] = tools
        body["tool_choice"] = {"type": "auto"}
    if extra:
        body.update(extra)
    data = _post_json(anthropic_messages_url(base),
                      anthropic_headers(api_key), body, timeout)
    if not isinstance(data, dict) \
            or not isinstance(data.get("content"), list):
        raise ApiError(f"Invalid response format: {str(data)[:300]}")
    return data


# ---- Azure OpenAI ----

def azure_chat_url(base):
    """Azureのbase(deploymentsパス)をchat/completionsのPOST先URLにする。

    api-versionクエリは省略時 AZURE_API_VERSION を既定として付ける。
    既に /chat/completions や api-version を含むURLはそれを尊重する。
    """
    u = (base or "").strip().rstrip("/")
    if not u:
        raise ApiError("API endpoint is not set")
    sp = urllib.parse.urlsplit(u)
    path = sp.path
    if "/chat/completions" not in path:
        path = path.rstrip("/") + "/chat/completions"
    q = urllib.parse.parse_qsl(sp.query, keep_blank_values=True)
    if not any(k.lower() == "api-version" for k, _ in q):
        q.append(("api-version", AZURE_API_VERSION))
    return urllib.parse.urlunsplit(
        (sp.scheme, sp.netloc, path, urllib.parse.urlencode(q), ""))


def azure_resource_url(base, tail):
    """{scheme}://{host}/openai/<tail>?api-version=… を作る。

    base中の /openai までのパスと api-version を引き継ぐ
    (deployments/models等のリソースレベルAPI用)。
    """
    u = (base or "").strip()
    if not u:
        raise ApiError("API endpoint is not set")
    sp = urllib.parse.urlsplit(u)
    i = sp.path.find("/openai")
    root = sp.path[: i + len("/openai")] if i >= 0 else "/openai"
    ver = next((v for k, v in urllib.parse.parse_qsl(sp.query)
                if k.lower() == "api-version"), AZURE_API_VERSION)
    return urllib.parse.urlunsplit(
        (sp.scheme, sp.netloc, f"{root}/{tail.lstrip('/')}",
         f"api-version={urllib.parse.quote(ver)}", ""))


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


def prompts_dir():
    return os.path.join(_registry_dir(), "prompts")


def _bundled_dir(kind):
    """プラグイン同梱のデフォルト <kind> ディレクトリ。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), kind)


def _bundled_dirs(kind):
    """同梱 <kind> ディレクトリ群(geo_driver + 全ロードプラグイン)。

    各プラグインが自身の <plugin>/<kind>/*.md を同梱できるようにし、
    geo_driver のものを先頭に同名は先勝ちで列挙する。
    """
    dirs = [_bundled_dir(kind)]
    try:
        import qgis.utils
        for p in qgis.utils.plugins.values():
            try:
                d = os.path.join(
                    os.path.dirname(inspect.getfile(type(p))), kind)
            except (TypeError, AttributeError):
                continue
            if d not in dirs and os.path.isdir(d):
                dirs.append(d)
    except Exception:  # nosec B110  # QGIS外利用の許容
        pass
    return dirs


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
    udir = os.path.join(_registry_dir(), kind)
    out = {}
    dirs = [(d, True) for d in _bundled_dirs(kind)] + [(udir, False)]
    for d, builtin in dirs:
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


def list_prompts():
    """おすすめプロンプト一覧(チャット入力欄へ挿入する定型文)。"""
    return list_instruction_files("prompts")


def _md_body(path):
    """_md_head と同規則でヘッダー(#タイトル/説明/use_when)を
    読み飛ばした残りの本文を返す。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return ""
    title = desc = None
    i = 0
    while i < len(lines):
        t = lines[i].strip()
        if not t:
            if title and desc:
                i += 1
                break
            i += 1
            continue
        if t.startswith("#"):
            if title is None:
                title = t.lstrip("#").strip()
                i += 1
                continue
            if desc:
                break       # 次見出し=ヘッダー終了(その行は本文)
            i += 1
            continue
        if desc is None:
            if t.startswith("---") or t.startswith("<!--"):
                i += 1
                continue
            desc = t
            i += 1
            continue
        if _WHEN_RE.match(t):
            i += 1        # use_when 行はヘッダーとして消費
        break               # ラベル行以外=ヘッダー終了(その行は本文)
    return "".join(lines[i:]).strip()


def prompt_body(item_id):
    """prompts の id → 入力欄へ挿入する本文。未指定/未存在はNone。

    ヘッダー(#タイトル/説明/use_when)を除いた残りを返す。
    本文が無いファイルは説明→タイトルの順にフォールバックする。
    """
    for a in list_instruction_files("prompts"):
        if a["id"] == item_id:
            body = _md_body(a["path"])
            return body or a.get("desc") or a["title"]
    return None


def _kind_dir(kind):
    return os.path.join(_registry_dir(), kind)


def _kind_list(kind):
    return list_instruction_files(kind)


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

_KIND_PROP = {"type": "string",
              "enum": ["agents", "skills", "prompts"],
              "description":
                  "agents=役割・方針・出力様式など常時注入の指示書"
                  "(同時に1件のみ有効。人格や「常に〜して」系の依頼向け) / "
                  "skills=特定タスクの手順・レシピ"
                  "(複数共存し必要時だけ読まれる。「この手順を覚えて」"
                  "系の依頼向け) / "
                  "prompts=チャット入力欄へ挿入する定型文"
                  "(パネルのおすすめ一覧に出る。「この指示をおすすめに"
                  "登録して」系の依頼向け。本文=挿入される指示文)"}

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
            "read on demand), 'prompts' for canned prompt text shown "
            "in the panel's suggestion list and inserted into the "
            "chat input when picked (body = the instruction text). "
            "Format: first '# ' line = title, next "
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
    if kind not in ("agents", "skills", "prompts"):
        raise ApiError(
            f"kind must be agents|skills|prompts: {kind!r}")
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


class AnthropicProvider:
    """Anthropic Messages API。

    systemはトップレベルフィールド、ツールはinput_schema、
    ツール結果はuserターンのtool_resultブロックで返す形式。
    """
    id = "anthropic"
    label = PROVIDERS["anthropic"]["label"]

    def list_model_entries(self, base, key, timeout=30.0):
        """GET {base}/v1/models → [{id}, ...] (has_moreでページング)。"""
        url = anthropic_models_url(base)
        out = []
        after = None
        for _ in range(20):              # ページ上限(暴走防止)
            u = url + ("&" if "?" in url else "?") + "limit=1000"
            if after:
                u += "&after_id=" + urllib.parse.quote(after)
            data = _get_json(u, anthropic_headers(key), timeout)
            items = data.get("data") if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise ApiError(
                    f"Invalid response format: {str(data)[:300]}")
            for m in items:
                if isinstance(m, dict) and m.get("id"):
                    out.append({"id": m["id"]})
            if not data.get("has_more") or not data.get("last_id"):
                break
            after = data["last_id"]
        return sorted(out, key=lambda e: e["id"])

    def list_models(self, base, key, timeout=30.0):
        return [e["id"] for e in
                self.list_model_entries(base, key, timeout)]

    def build_messages(self, system, history, user_text,
                       user_images=None):
        msgs = []
        for m in history:
            msgs.append({
                "role": m.get("role"),
                "content": anthropic_content(
                    m.get("content") or "", m.get("images"))})
        msgs.append({"role": "user",
                     "content": anthropic_content(user_text,
                                                  user_images)})
        return msgs

    def send(self, base, key, model, system, msgs, timeout=180.0):
        return anthropic_messages(base, key, model, system, msgs,
                                  tools=anthropic_tools(),
                                  timeout=timeout)

    def parse(self, data):
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks
                       if b.get("type") == "text")
        calls = [{"id": b.get("id"),
                  "name": b.get("name") or "",
                  "args": b.get("input") or {}}
                 for b in blocks if b.get("type") == "tool_use"]
        if not text and not calls:
            raise ApiError(
                f"Response empty or blocked: stop_reason="
                f"{data.get('stop_reason')} {str(data)[:200]}")
        return {"text": text, "calls": calls,
                "raw": {"role": "assistant", "content": blocks},
                "usage": parse_usage(data)}

    def append_exchange(self, msgs, turn, results):
        # assistantターン(contentブロック列)の直後に、全tool_resultを
        # 1つのuserターンへまとめて返す
        msgs.append(turn["raw"])
        parts = []
        for c, r in zip(turn["calls"], results):
            content = r["text"]
            if r.get("image"):
                img = anthropic_image_part(r["image"])
                if img is not None:
                    content = ([{"type": "text", "text": r["text"]}]
                               if r["text"] else []) + [img]
            parts.append({"type": "tool_result",
                          "tool_use_id": c.get("id"),
                          "content": content})
        msgs.append({"role": "user", "content": parts})


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
            # /responses 専用モデルを記録(GPT-6系等。
            # supported_endpoints が無い応答は不明=chat送り)
            eps = m.get("supported_endpoints")
            if isinstance(eps, list):
                if "/chat/completions" not in eps \
                        and "/responses" in eps:
                    _RESPONSES_ONLY_MODELS[m["id"]] = True
                elif "/chat/completions" in eps:
                    _RESPONSES_ONLY_MODELS.pop(m["id"], None)
            out.append(e)
        return sorted(out, key=lambda e: e["id"])

    def send(self, base, key, model, system, msgs, timeout=180.0):
        tok, api_base = copilot_session(key, base)
        if not _RESPONSES_ONLY_MODELS.get(model):
            try:
                return chat_completions(
                    api_base, tok, model, msgs,
                    tools=openai_tools(), timeout=timeout,
                    headers=COPILOT_HEADERS)
            except ApiError as e:
                if not _responses_only_error(e):
                    raise
                # /responses専用モデルだった。学習して切替
                _RESPONSES_ONLY_MODELS[model] = True
        return responses_create(
            api_base, tok, model, msgs,
            tools=openai_tools(), timeout=timeout,
            headers=COPILOT_HEADERS)

    def parse(self, data):
        if isinstance(data, dict) \
                and isinstance(data.get("output"), list):
            return parse_responses_output(data)
        return super().parse(data)


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI Service。

    メッセージ形式はOpenAI互換なので build_messages/parse/
    append_exchange は OpenAIProvider を継承。違いはURLと認証:
    {resource}/openai/deployments/<deployment>/chat/completions
    ?api-version=… に api-key ヘッダで送る。model欄はデプロイ名
    (api-version=2024-10-21以降のv1 APIではmodel指定は任意だが、
    互換のためデプロイ名をそのまま送る)。
    """
    id = "azure"
    label = PROVIDERS["azure"]["label"]

    def list_model_entries(self, base, key, timeout=30.0):
        """GET {resource}/openai/deployments → デプロイ名一覧。

        v1 APIのdeployments一覧が使えない環境では /openai/models
        (基盤モデル名)にフォールバックする。
        """
        headers = {"api-key": key} if key else {}
        try:
            data = _get_json(azure_resource_url(base, "deployments"),
                             headers, timeout)
            items = data.get("data") if isinstance(data, dict) else None
            out = [{"id": m["id"]} for m in items or []
                   if isinstance(m, dict) and m.get("id")]
            if out:
                return sorted(out, key=lambda e: e["id"])
        except ApiError:
            pass                        # /openai/models へフォールバック
        data = _get_json(azure_resource_url(base, "models"),
                         headers, timeout)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ApiError(f"Invalid response format: {str(data)[:300]}")
        return sorted([{"id": m["id"]} for m in items
                       if isinstance(m, dict) and m.get("id")],
                      key=lambda e: e["id"])

    def send(self, base, key, model, system, msgs, timeout=180.0):
        body = {"model": model, "messages": msgs}
        tools = openai_tools()
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        headers = {"api-key": key} if key else {}
        data = _post_json(azure_chat_url(base), headers, body, timeout)
        if not isinstance(data, dict) or not data.get("choices"):
            raise ApiError(
                f"Invalid response format: {str(data)[:300]}")
        return data


# ---- Devin プロバイダ ----
#
# "devin_bridge"(【ブリッジ】): 通常のOpenAI互換チャット + systemへ
# 「qgis_devin_* ツールで実作業をDevinへ委譲せよ」という指示を注入
# する疑似プロバイダ。ツールループはパネル側(従来どおり)。
# "devin_acp"(【ACP】): Devin CLI の `devin acp` セッションをチャット
# エンジンにする実プロバイダ。送信は session/prompt に流し、Devin
# 自身がツールループを回す(geo_driver の /mcp をMCPサーバとして
# 注入するので Devin からQGIS操作も可能)。APIキー不要でIDE認証を
# 共有する。会話履歴はDevinセッション側に保持されるため、各ターン
# は最新ユーザ発言だけを送る。

_DEVIN_BRIDGE_HINT = """\
[DELEGATION MODE] You are a delegation assistant. For any task that
requires writing files, running commands, editing code, or other
substantial work, delegate it to Devin via the qgis_devin_* tools
instead of describing the work yourself:
- qgis_devin_run(prompt, cwd, session_id, engine) starts a task and
  returns task_id (engine "acp" works without `devin auth login`)
- qgis_devin_status / qgis_devin_result monitor it (poll; tasks are
  asynchronous and may take minutes — keep polling until done)
- qgis_devin_abort cancels a running task
Pass the returned session_id to later qgis_devin_run calls to continue
the same Devin session. Report Devin's results to the user."""

_COPILOT_BRIDGE_HINT = _DEVIN_BRIDGE_HINT.replace(
    "Devin", "Copilot CLI").replace("qgis_devin_", "qgis_copilot_")

# devin_acp セッションはcwd単位でモジュールに保持し、送信のたびに
# 再利用する(プロバイダインスタンスは send ごとに作り直されるため)
_ACP_SESSIONS = {}


def _acp_mcp_servers():
    """geo_driver自身の /mcp を Devin セッションへ渡す定義を返す。

    Devin 側のツールループから qgis_pyeval 等が直接使えるようにする。
    ドライバ未起動・QGIS外では空を返す。
    """
    try:
        import qgis.utils  # noqa: PLC0415
        plug = qgis.utils.plugins.get("geo_driver")
        drv = getattr(plug, "driver", None)
        port = getattr(drv, "http_port", None)
        tok = getattr(drv, "token", None)
        if port and tok:
            return [{"type": "http", "name": "qgis-live",
                     "url": f"http://127.0.0.1:{port}/mcp",
                     "headers": [{"name": "Authorization",
                                  "value": f"Bearer {tok}"}]}]
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return []


def close_acp_sessions():
    """devin_acp で開いた全セッションを閉じる(パネル破棄時)。"""
    for s in list(_ACP_SESSIONS.values()):
        try:
            s.close()
        except Exception:  # nosec B110  # 設計上の許容
            pass
    _ACP_SESSIONS.clear()


class DevinBridgeProvider(OpenAIProvider):
    """【ブリッジ】OpenAI互換チャット + Devin委譲指示の注入。"""

    id = "devin_bridge"
    label = PROVIDERS["devin_bridge"]["label"]

    def build_messages(self, system, history, user_text,
                       user_images=None):
        return super().build_messages(
            _DEVIN_BRIDGE_HINT + "\n\n" + (system or ""),
            history, user_text, user_images)


class CopilotBridgeProvider(OpenAIProvider):
    """【ブリッジ】OpenAI互換チャット + Copilot CLI委譲指示の注入。"""

    id = "copilot_bridge"
    label = PROVIDERS["copilot_bridge"]["label"]

    def build_messages(self, system, history, user_text,
                       user_images=None):
        return super().build_messages(
            _COPILOT_BRIDGE_HINT + "\n\n" + (system or ""),
            history, user_text, user_images)


class DevinAcpProvider:
    """【ACP】`devin acp` セッションをチャットエンジンにする。

    エンドポイント欄=セッションの作業ディレクトリ(cwd)、
    APIキー欄=未使用(IDE認証を共有)、モデル欄=Devin側モデル
    ("default"または空で未指定)。geo_driver の /mcp を
    MCPサーバとして渡すので Devin からQGIS操作が可能。
    """

    id = "devin_acp"
    label = PROVIDERS["devin_acp"]["label"]
    ENGINE = "devin"

    def list_model_entries(self, base, key, timeout=30.0):
        return [{"id": "default"}]

    def list_models(self, base, key, timeout=30.0):
        return ["default"]

    def build_messages(self, system, history, user_text,
                       user_images=None):
        # 履歴はDevin側が保持するため表示用の簡易形式のみ
        msgs = [{"role": "system", "content": system}]
        for m in history:
            msgs.append({"role": m.get("role"),
                         "content": m.get("content") or "",
                         "images": m.get("images")})
        msgs.append({"role": "user", "content": user_text,
                     "images": list(user_images or [])})
        return msgs

    def _session(self, cwd, model):
        """engine+cwd単位の常駐セッションを取得(無ければ生成)。"""
        from . import devin_tasks  # noqa: PLC0415
        cwd = os.path.abspath(os.path.expanduser(cwd or "~"))
        skey = (self.ENGINE, cwd)
        s = _ACP_SESSIONS.get(skey)
        if s is not None and s._proc.poll() is not None:
            s = None  # プロセスが死んでいたら作り直す
        if s is None:
            s = devin_tasks.AcpSession(
                cwd, mcp_servers=_acp_mcp_servers(), mode="bypass",
                model=None if model in (None, "", "default") else model,
                engine=self.ENGINE)
            _ACP_SESSIONS[skey] = s
        return s

    def _make_session(self, base, key, model):
        """send からのセッション取得フック。base=エンドポイント欄、
        key=APIキー欄(ACP系では認証外の別用途に使える)。
        既定は base を cwd とみなす"""
        return self._session(base, model)

    def send(self, base, key, model, system, msgs, timeout=180.0):
        from . import devin_tasks  # noqa: PLC0415
        sess = self._make_session(base, key, model)
        last = msgs[-1] if msgs else {}
        text = last.get("content") or ""
        # 新規セッションの最初の発言にだけ system(指示書類)を前置
        if not getattr(sess, "_sys_sent", False):
            if system:
                text = system + "\n\n---\n\n" + text
            sess._sys_sent = True
        blocks = []
        if text.strip():
            blocks.append({"type": "text", "text": text})
        for p in last.get("images") or []:
            try:
                with open(p, "rb") as f:
                    import base64
                    blocks.append({
                        "type": "image",
                        "data": base64.b64encode(f.read()).decode("ascii"),
                        "mimeType": "image/png"})
            except OSError:
                pass
        if not blocks:
            raise ApiError("empty prompt")
        chunks = []

        def on_update(u):
            kind = u.get("sessionUpdate")
            if kind == "agent_message_chunk":
                t = ((u.get("content") or {}).get("text") or "")
                if t:
                    chunks.append(t)
            cb = getattr(self, "on_event", None)
            if cb:
                try:
                    cb(kind, u)
                except Exception:  # nosec B110  # 設計上の許容
                    pass

        sess.on_update = on_update
        self._sess = sess
        try:
            res = sess.prompt(blocks)
        except devin_tasks.TaskError as e:
            raise ApiError(str(e))
        usage = res.get("usage") or {}
        return {"text": "".join(chunks),
                "stop_reason": res.get("stopReason"),
                "session_id": sess.session_id,
                "usage": {"in": usage.get("inputTokens", 0),
                          "out": usage.get("outputTokens", 0)},
                "raw": res}

    def parse(self, data):
        return {"text": data.get("text") or "", "calls": [],
                "raw": data.get("raw") or data,
                "usage": data.get("usage")}

    def append_exchange(self, msgs, turn, results):
        # calls は常に空なので通常呼ばれない。テキストのみ積む
        msgs.append({"role": "assistant",
                     "content": turn.get("text") or ""})

    def abort(self):
        """パネルの中断ボタン → session/cancel。"""
        s = getattr(self, "_sess", None)
        if s is not None:
            s.cancel()


class CopilotAcpProvider(DevinAcpProvider):
    """【ACP】`copilot --acp --stdio` セッションをチャットエンジンにする。

    機構は DevinAcpProvider と同じで、エンジンと認証だけが異なる
    (GitHub Copilot CLI の gh ログインを利用。windsurf_api_key 不要)。
    """

    id = "copilot_acp"
    label = PROVIDERS["copilot_acp"]["label"]
    ENGINE = "copilot"


def _custom_acp_argv(command):
    """起動コマンド文字列を argv に分解する。

    Windows の .cmd/.bat shim は直接 spawn できないため cmd /c 経由にする
    (copilot.cmd 等と同じ対策)。
    """
    import shlex  # noqa: PLC0415
    try:
        argv = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        argv = command.split()
    argv = [a.strip('"').strip("'") for a in argv if a.strip('"').strip("'")]
    if not argv:
        raise ApiError("ACP launch command is empty")
    resolved = shutil.which(argv[0])
    if resolved is None:
        raise ApiError(f"ACP command not found: {argv[0]}")
    argv[0] = resolved
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        argv = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *argv]
    return argv


class CustomAcpProvider(DevinAcpProvider):
    """【ACP】任意の ACP 対応 CLI をチャットエンジンにする。

    エンドポイント欄=起動コマンド(例: `my-agent acp`)、
    APIキー欄=セッションの作業ディレクトリ(cwd。省略時はホーム)。
    認証は CLI 側のログインに委譲(authMethods が提示された場合のみ
    先頭方式を best-effort で試行)。機構は DevinAcpProvider と同じ
    (KASUGAI Canvas の【ACP】カスタムエージェントに相当)。
    """

    id = "acp"
    label = PROVIDERS["acp"]["label"]
    ENGINE = "custom"

    def _make_session(self, base, key, model):
        from . import devin_tasks  # noqa: PLC0415
        command = (base or "").strip()
        if not command:
            raise ApiError(
                "ACP launch command is not set (endpoint field)")
        argv = _custom_acp_argv(command)
        cwd = os.path.abspath(
            os.path.expanduser((key or "").strip() or "~"))
        skey = (self.ENGINE, command, cwd)
        s = _ACP_SESSIONS.get(skey)
        if s is not None and s._proc.poll() is not None:
            s = None  # プロセスが死んでいたら作り直す
        if s is None:
            s = devin_tasks.AcpSession(
                cwd, exe=argv, mcp_servers=_acp_mcp_servers(),
                mode="bypass",
                model=None if model in (None, "", "default") else model,
                engine="custom")
            _ACP_SESSIONS[skey] = s
        return s


class ExternalAgentProvider(OpenAIProvider):
    """【ブリッジ】任意のエージェント HTTP エンドポイントへ委譲する。

    POST {endpoint} {"message", "system", "history", "model"?}
      → {"reply": "..."} (reply/text/message/content のいずれか)。
    KASUGAI Canvas のブリッジハブ /agent と同じ形式で、
    hub の provider 振り分けは model 欄ではなく
    body の "provider" 固定値は使わず直接プロバイダURLへ送る想定。
    """

    id = "agent"
    label = PROVIDERS["agent"]["label"]

    def list_model_entries(self, base, key, timeout=30.0):
        return [{"id": "default"}]

    def list_models(self, base, key, timeout=30.0):
        return ["default"]

    def send(self, base, key, model, system, msgs, timeout=180.0):
        url = (base or "").strip()
        if not url:
            raise ApiError("agent endpoint is not set")
        last = msgs[-1] if msgs else {}
        content = last.get("content")
        if isinstance(content, str):
            text = content
        else:  # 画像付き等のマルチパート形式はテキスト部だけ結合
            text = " ".join(
                p.get("text", "") for p in (content or [])
                if isinstance(p, dict))
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {
            "message": text,
            "system": system or "",
            "history": [
                {"role": m.get("role"), "content": m.get("content")}
                for m in msgs[-20:]
                if m.get("role") in ("user", "assistant", "model")],
        }
        if model and model != "default":
            body["model"] = model
        return _post_json(url, headers, body, timeout)

    def parse(self, data):
        if isinstance(data, dict):
            reply = data.get("reply")
            if isinstance(reply, dict):
                reply = (reply.get("text") or reply.get("content")
                         or reply.get("message") or "")
            if not reply:
                reply = (data.get("text") or data.get("message")
                         or data.get("content") or "")
            if isinstance(reply, str):
                return {"text": reply, "calls": [], "raw": data,
                        "usage": parse_usage(data)}
        raise ApiError(f"Invalid agent response: {str(data)[:300]}")

    def append_exchange(self, msgs, turn, results):
        # calls は常に空。応答 dict をそのまま積むと次の送信履歴を
        # 壊すためテキストのみにする
        msgs.append({"role": "assistant",
                     "content": turn.get("text") or ""})


_PROVIDERS = {"openai": OpenAIProvider, "anthropic": AnthropicProvider,
              "gemini": GeminiProvider, "azure": AzureOpenAIProvider,
              "copilot": CopilotProvider,
              "devin_bridge": DevinBridgeProvider,
              "copilot_bridge": CopilotBridgeProvider,
              "devin_acp": DevinAcpProvider,
              "copilot_acp": CopilotAcpProvider,
              "acp": CustomAcpProvider,
              "agent": ExternalAgentProvider}


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
