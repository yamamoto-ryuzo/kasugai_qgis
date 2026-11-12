> **QGIS Live Harness の中核ドライバ** — [QGIS Live Harness](https://yamamoto-ryuzo.github.io/qgis_live_harness/) · [プラグイン一覧](https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html) · [リポジトリ](https://github.com/yamamoto-ryuzo/qgis_live_harness)

# QGIS Live Driver (`qgis_live_driver`)

[Japanese / 日本語: `README_JP.md`](README_JP.md)

A UI-less, control-only plugin that lets clients on the **same PC** (AI tools,
etc.) **remotely operate a running QGIS process**.
It can be installed standalone into any QGIS installation by simply copying it
into `python/plugins/` (no repository or Node required).

Because this plugin has no `QWebEngineView`, it provides a `pyeval`-based
remote-control surface for **any QGIS environment and any other plugin**, with
or without WebEngine.

- Commands: `pyeval` (arbitrary Python execution) / `screenshot` / `status` /
  `open_plugin` / `reload_plugin` / `bridge_call` + `plugin_id` forwarding (hub)
- Connection surfaces (4, all routed to the same dispatch): file JSONL /
  HTTP REST `/api/*` / MCP Streamable HTTP `/mcp` / MCP stdio (`mcp_stdio.py`)

**Full documentation (command list, control scope, REST endpoints, etc.):**
https://yamamoto-ryuzo.github.io/qgis_live_harness/driver.html

## Activation

```powershell
# From this repository (deploys all plugins at once)
powershell -ExecutionPolicy Bypass -File scripts/deploy-plugin.ps1 -Install

# Or manually: copy this folder to python/plugins/qgis_live_driver/
# and enable it in the QGIS Plugin Manager
```

### Quick start (first time)

1. Install + enable the plugin (above).
2. Turn on `Plugins > QGIS Live Driver > Remote Control (localhost only)`
   and accept the warning — the **Connection Info** dialog opens
   automatically with everything a client needs (MCP URL, token, registry
   path, live dir). Reopen it anytime via
   `Plugins > QGIS Live Driver > Connection Info`.
3. Paste one of the shown configs into your MCP client:
   - **stdio** (recommended): spawns the bundled `mcp_stdio.py` and
     auto-discovers the running QGIS session — no port/token handling.
   - **Streamable HTTP**: `http://127.0.0.1:<port>/mcp` with the shown
     `Authorization: Bearer <token>`.
   - Plain REST is also shown as a `curl` example.
4. (Development only) To link this plugin to the `qgis_live_harness`
   repository — required for Deploy Mode / hot reload — click
   **Locate harness repo…** in the Connection Info dialog or **Browse…**
   in `Plugins > QGIS Live Driver > Deploy Mode` and select the repo
   folder. The path is saved to QSettings and used before marker-file or
   junction auto-detection.

Two activation paths (OFF and harmless by default):

- **Menu toggle**: `Plugins > QGIS Live Driver > Remote control (localhost only)`.
  A warning dialog is shown the first time it is enabled; the setting is saved
  to QSettings so it stays enabled on subsequent launches.

The plugin also creates the shared **GeoSuite toolbar** with an always-visible
deploy-mode badge at its head (Development/Usage; click to open the Deploy Mode
dialog). Other harness-managed plugins (geo_search etc.) place their toolbar
items on this same toolbar.
- **Environment variable**: setting `WEBENGINE_LIVE_DIR` enables it immediately
  at startup (for development; `scripts/verify-in-qgis.ps1` sets this when
  launching QGIS).

## AI Assistant Panel

`Plugins > QGIS Live Driver > AI Assistant` opens a **chat dock that connects
an LLM API to operate QGIS interactively** (`ai_panel.py` + `ai_client.py`).

- **Providers** (combo selection; settings are stored per provider):
  - **OpenAI-compatible**: Chat Completions
    (`POST {base}/chat/completions` + function calling).
    Change the endpoint to use Ollama (`http://localhost:11434/v1`),
    LM Studio, OpenRouter, xAI Grok (`https://api.x.ai/v1`), Mistral,
    Groq, DeepSeek, or other local/compatible servers. Providers with
    proprietary APIs such as AWS Bedrock or Vertex AI can also be used
    through an OpenAI-compatible proxy such as LiteLLM.
  - **Anthropic (Claude)**: Anthropic Messages API
    (`POST {base}/v1/messages`, tools = `input_schema`, authenticated
    via `x-api-key` + `anthropic-version`). Get an API key from the
    Anthropic Console. Default model: `claude-sonnet-4-5`.
  - **Gemini**: Google Gemini API
    (`POST {base}/models/{model}:generateContent` +
    functionDeclarations, authenticated via `x-goog-api-key`).
    Get an API key from AI Studio. Default model: `gemini-2.5-flash`.
  - **Azure OpenAI**: Chat Completions on Azure OpenAI Service
    (`{resource}/openai/deployments/<deployment>/chat/completions
    ?api-version=…`, authenticated via the `api-key` header). Enter the
    deployment endpoint and use the deployment name as the model.
    `api-version` defaults to `2024-10-21` when omitted.
  - **GitHub Copilot**: OpenAI-compatible Copilot API
    (`POST {api}/chat/completions`). **Requires a GitHub Copilot
    subscription.** Enter a GitHub token (`gho_`/`ghu_`/`ghp_`…) in the API
    key field. Internally it is exchanged at
    `api.github.com/copilot_internal/v2/token` and requests are sent to the
    `endpoints.api` from the response (individual/business/enterprise).
    In environments where `v2/token` does not respond, it falls back to
    resolving only the API endpoint via `copilot_internal/user` and using the
    GitHub token directly as Bearer (same behavior as the `@github/copilot`
    CLI). The **"Sign in with GitHub"** button can also obtain a token via the
    OAuth device flow (default client_id is VS Code's public OAuth App;
    override with `QGIS_LIVE_GITHUB_CLIENT_ID`). If the endpoint is changed
    from the default, no token exchange occurs and the GitHub token is used
    directly as Bearer, so compatible proxies such as copilot-api also work.
    **Supported plans**: Pro/Free/Business/Enterprise/EMU
    (Enterprise Managed Users — usable when an enterprise assigns a
    Business/Enterprise seat to an EMU). For Business/Enterprise/EMU,
    `endpoints.api` returns `api.business.`/`api.enterprise.githubcopilot.com`
    and is resolved automatically via the same path. For EMU, PAT issuance may
    be restricted by enterprise policy, so "Sign in with GitHub" (device flow)
    is recommended. Models disabled by the organization's Copilot model policy
    cannot be listed or used. Enterprise-side restrictions such as IdP
    conditional access cannot be bypassed by the app.
- **Model selection**: the model field is an editable combo. The adjacent
  "Fetch" button imports the available model list from `GET {base}/models`
  (for Gemini, models without generateContent support are excluded). The list
  is grouped by capability (text / image-input / image generation / embedding,
  etc.), and each item shows pricing (input/output, $/1M tokens). Pricing
  prefers `pricing`/`modality`/`context_length` returned by services such as
  OpenRouter, falling back to a built-in reference price table for major
  models. With the default endpoint, a recommended model list is shown even
  before "Fetch". The capability, price, and context length of the selected
  model are displayed below the field.
- **Agents/Skills (instruction files)**: two kinds of Markdown files extend
  behavior:
  - **`~/.qgis-live/agents/*.md`** — always-injected instruction files
    (role/policy). Selecting one in the panel's "Agent" combo injects its
    content into the system prompt. The "Edit" button creates/edits/deletes
    files (multiple definitions can be switched; the selection is remembered
    per chat).
  - **`~/.qgis-live/skills/*.md`** — on-demand procedure files. Only a list of
    id + description (+ `use_when`) is placed in the prompt; the model reads
    the body via `qgis_pyeval`'s `open()` when the task matches (saves tokens
    since nothing is always injected). **Configure via the "Skills" row in API
    settings — all files are listed in the combo (no selection needed; all
    are listed automatically), and the "Edit" dialog
    creates/edits/deletes them**.
  - Both can have bundled defaults under `<plugin>/<kind>/`; user-side files
    with the same name take precedence. Format: first `# ` line = title, next
    non-empty line = description, followed by an optional
    `use_when: <when to use>` line (aliases: when/when_to_use/用途/使いどき)
    which appears as `use when:` in the prompt list. (Bundled defaults are
    optional; none are currently bundled.)
  - **The AI itself can edit and select instruction files**:
    `ai_list_instructions` / `ai_read_instruction` /
    `ai_save_instruction` / `ai_delete_instruction`, plus
    `ai_select_agent` (switching the selected agent) are exposed to the model.
    Since the agent list appears in the prompt with id + description like
    skills, the model can autonomously select an agent suited to the task.
    Saves always write to the user side; saving with the same name as a
    bundled file effectively overrides it (deletion is user-side only). After
    changes, the panel combos are rebuilt automatically.
  - **The "Edit" dialog is non-modal**: chat input remains usable while it is
    open. Writing a fix request in the prompt field at the bottom of the
    dialog and clicking "Ask AI to fix" sends it to the chat AI together with
    the editor content; the result the AI saves via `ai_save_instruction` is
    reflected in the editor (unsaved manual edits are not overwritten). If a
    file with the same name is saved while creating a new one, that file
    becomes selected.
  - **Direct editing from chat input is also possible**: input starting with
    `/` is executed as a local command instead of being sent to the API.
    `/agent` (list + current), `/agent <name>` (switch),
    `/agent <name> <body>` (save and select), `/skill` (list),
    `/skill <name>` (show body), `/skill <name> <body>` (save). The body can
    span multiple lines starting from line 2. `/help` shows the list.
  - **Also operable by external AI**: the MCP/REST `qgis_instruction` tool
    (op=list|read|save|delete) lets orchestrators discover and edit
    instruction files (subject to `QGIS_LIVE_TOOLS` allowlist).
- **Display**: AI responses are rendered as Markdown
  (headings/lists/tables/code blocks). "New chat" saves the current
  conversation to the history combo and starts fresh. Opening a past chat
  from the history combo restores its display and context so the conversation
  can continue. History is persisted to `~/.qgis-live/chats.json`
  (latest 50) and survives QGIS restarts. "↓" saves the displayed chat as
  Markdown; "✕" deletes the displayed history chat.
- **Send/Stop/Resend**: Enter (or "Send") sends; Shift+Enter inserts a
  newline. "Send" is disabled while input is empty; while running, the button
  becomes a red "■ Stop" which stops the loop at turn boundaries (in-flight
  API responses and tool executions run to completion). "Resend" cancels the
  last question+response and sends the same question again. Long
  conversations are truncated from the oldest turns (MAX_HISTORY_CHARS) so
  API errors from oversized contexts do not occur. Context/cost display at
  bottom right (`ctx 9k/128k (6%) · Σ13k · $0.0023`). ctx is the measured
  prompt_tokens from the latest API response (~ prefix with a chars÷3
  estimate when unavailable), Σ is cumulative tokens per chat, $ is the
  estimated cost for models with pricing info (flat-rate services such as
  Copilot show Σ only). Saved to chat history together with usage.
- **Image attachments**: paste from clipboard (Ctrl+V), drag & drop image
  files, or use the "📎" button to attach images. They appear as thumbnail
  chips above the input and are bundled into the user message on send (kept
  in history so the model can reference them in later turns). Images are
  normalized to PNG and resized to 2048px on the long edge before being saved
  to a temp file. **Attachments are not allowed while a model estimated not
  to support images (outside the "image input" group in the list) is
  selected** — the 📎 button is also disabled (manually entered models are
  estimated by name hints).
- **Confirmation mode**: enabling "Confirm before tool execution" asks for
  approval on each tool call (for cases where you do not want pyeval, which
  executes arbitrary code, to run automatically).
- **Tools**: the same set as `mcp_http.TOOLS`
  (`qgis_pyeval` / `qgis_screenshot` / `qgis_status` /
  `qgis_eval` / `qgis_devreload` / `qgis_open_plugin` /
  `qgis_reload_plugin` / `qgis_bridge_call` /
  `qgis_instruction`), plus panel-local `ai_*` tools for reading/writing
  instruction files, and external MCP server tools `mcp_*`. Returned
  tool_calls are processed via `driver.submit()` (qgis_*) or local execution
  (ai_*/mcp_*) in an agent loop (max 25 round trips).
- **External MCP server connections**: API settings "MCP" row → "Settings"
  edits `~/.qgis-live/mcp_servers.json` (Claude Desktop-compatible format):
  ```json
  {"mcpServers": {
    "fs":  {"command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/work"]},
    "api": {"url": "http://localhost:3000/mcp",
            "headers": {"Authorization": "Bearer ..."}},
    "box": {"url": "https://mcp.box.com",
            "oauth": {"authorize_url":
                        "https://account.box.com/api/oauth2/authorize",
                      "token_url": "https://api.box.com/oauth2/token",
                      "client_id": "...", "client_secret": "...",
                      "redirect_uri": "http://127.0.0.1:8020/callback"}},
    "ccg": {"url": "https://example.com/mcp",
            "oauth": {"token_url": "https://example.com/oauth/token",
                      "client_id": "...", "client_secret": "...",
                      "extra": {"box_subject_type": "enterprise",
                                "box_subject_id": "..."}}}
  }}
  ```
  `command` = stdio child process (no console window on Windows);
  `url` = Streamable HTTP.
  **Secrets go to the credential store**: saving a plaintext
  `oauth.client_secret` automatically moves it to the OS credential store
  (credential_store, the same location as API keys); the config file keeps
  only a `"$store:mcp:<server>:client_secret"` reference. If storing fails,
  it is an error and nothing is saved in plaintext. Values in
  `headers`/`env`/`oauth.client_id` written as `"$store:<key>"` are also
  resolved from the store at connection time (manually written references
  require prior registration in the credential store). Existing configs with
  leftover plaintext client_secrets are migrated by re-saving in the settings
  dialog. Authentication is either fixed values via `headers`, or two kinds
  of OAuth via `oauth`: with `authorize_url` = **authorization_code+PKCE**
  (the browser opens a consent screen on first send; tokens are saved to
  `~/.qgis-live/mcp_tokens.json` and automatically refreshed via
  refresh_token afterwards; for user-consent servers such as mcp.box.com;
  redirect_uri must be registered app-side), without `authorize_url` =
  **client_credentials** (client_id+secret; provider-specific form params via
  `extra`). Retries once on 401. On connection failure, a checklist guide
  "① Redirect URI registration ② authorization_code enabled ③ id/secret
  match" is shown with the error. To use mcp.box.com, Box additionally
  requires a Business plan or higher, MCP enabled in the Admin Console, and a
  Custom App with standard OAuth2 (CCG-only Server Apps do not work).
  Obtained tokens are stored in plaintext in
  `~/.qgis-live/mcp_tokens.json` (contains access/refresh tokens — handle
  with care). On first send, it connects and performs tools/list; each tool
  is exposed to the model as `mcp_<server>__<tool>`. Saving the config
  reconnects on the next send. Servers that fail to connect show an error in
  the chat area while other servers continue. Note: pointing this at QGIS's
  own driver MCP endpoint makes tools/call self-referential via GUI-thread
  dispatch, so in practice point it at other servers.
- **Works even with the remote-control toggle OFF**: the panel uses its own
  internal LiveDriver (no registry/HTTP exposure), so AI operation can be
  tried without enabling external exposure.
- **Sending images**: `qgis_screenshot` results go as `image_url` content,
  and attached images (paste/📎) are bundled into the user message and sent
  to the model as images. For models estimated not to support images,
  screenshot results return text (path) only and attachments cannot be made.
- Settings (endpoint/model) are stored in QSettings.
  **API keys are stored in the OS credential store** (`credential_store.py`):
  DPAPI on Windows (same user-bound encryption as browser password storage),
  Keychain on macOS, Secret Service (secret-tool) on Linux. Only when none is
  available does it fall back to `~/.qgis-live/ai-secrets.json` (0600
  permissions, plaintext). The panel's "Key storage" field shows the current
  backend. **If writing to the store itself fails, an error is shown and the
  key is never saved in plaintext.**

## Security model (localhost only)

Because `pyeval` is **arbitrary code execution**, all channels are protected
by:

- **127.0.0.1 binding only** — unreachable from external networks
- **Mandatory session token** — auto-generated per launch. HTTP requires
  `Authorization: Bearer` etc.; commands.jsonl verifies the `token` field of
  each line. The token is written only to the registry
  (`~/.qgis-live/<pid>-qgis_live_driver.json`) and `live_dir/token`, with
  user-only ACLs applied.
- **Host/Origin validation** — HTTP requests whose Host or Origin points
  outside loopback are rejected (DNS rebinding / browser drive-by protection).
- `QGIS_LIVE_TOOLS` can restrict the exposed command types
  (e.g. `status,screenshot`).

**Threat model boundary**: since the token lives in a user-only file,
processes that can already execute arbitrary code as the same user cannot be
stopped (the limit of any localhost service). The trust boundary is the local
user account.

Local MCP clients (`mcp_stdio.py`, etc.) read the token automatically from
the registry, so client-side usage is unchanged.

## Disclaimer

This system was created and tested on a personal computer.  
We accept no liability for any damage arising from its use.

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>
