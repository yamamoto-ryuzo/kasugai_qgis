"""AIアシスタントドック — LLM APIを接続してQGISを対話操作するUI。

`プラグイン > QGIS Live Driver > AI アシスタント` で開く。
プロバイダ(OpenAI互換 / Anthropic / Gemini / Azure OpenAI /
GitHub Copilot)・エンドポイント・APIキー・モデルを設定すると、
チャット経由でこのドライバのツール群
(qgis_pyeval/qgis_screenshot/...)をfunction callingでループ実行する。
GitHub Copilot選択時は「GitHubでサインイン」ボタンでOAuthデバイス
フローによるトークン取得ができる。

構成:
  - 通信・スキーマ変換は ai_client.py(stdlibのみ・pytest対象)
  - ツール実行は LiveDriver.submit() → GUIスレッドのdispatch。
    リモート制御トグルOFFでも __init__ 側が用意する内部ドライバで動く
  - ネットワーク/ツール実行はワーカースレッド、UI更新はシグナル経由
  - APIキーはOSの資格情報ストアに保存される(credential_store.py)。
    ストア書込みに失敗した場合は平文保存せずエラーにする。
    エンドポイント/モデルはQSettingsにプロバイダごと別キーで保持する
"""

import html
import json
import os
import re
import threading
import time

from qgis.PyQt.QtCore import (
    Qt, QSettings, QUrl, QCoreApplication, QT_TRANSLATE_NOOP,
    pyqtSignal)
from qgis.PyQt.QtGui import (
    QDesktopServices,
    QImage,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
    QTextDocument,
)
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QLabel,
)

from . import ai_client, credential_store

_SETTING = "qgis_live_driver/ai_{}"
_PROVIDER_IDS = list(ai_client.PROVIDERS.keys())
_MODEL_HINT = QT_TRANSLATE_NOOP(
    "qgis_live_driver",
    "Press \"Fetch\" to list models from the endpoint. "
    "Values in parentheses are prices (input/output, $/1M tokens, "
    "reference only).")


def _esc(t):
    return html.escape(t or "").replace("\n", "<br>")


def _md(t):
    """Markdown → 本文用HTML(QTextDocument.toHtml()のbody中身)。"""
    doc = QTextDocument()
    doc.setMarkdown(t or "")
    h = doc.toHtml()
    m = re.search(r"<body[^>]*>(.*)</body>", h, re.S)
    return m.group(1) if m else h


class _Input(QPlainTextEdit):
    """Enterで送信、Shift+Enterで改行する入力欄。

    画像(クリップボード・画像ファイルのドラッグ&ドロップ)は
    テキストとして挿入せず sig_images でパネルへ渡す。
    """
    sig_submit = pyqtSignal()
    sig_images = pyqtSignal(list)  # [QImage|ローカルパスstr, ...]

    _IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp",
                 ".webp", ".tif", ".tiff"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._hint = ""
        self._composing = False

    def _image_sources(self, mime):
        """mimeデータから画像ソース(QImage or ローカルパス)を取り出す。"""
        if mime.hasImage():
            return [mime.imageData()]
        return [u.toLocalFile() for u in mime.urls()
                if u.isLocalFile() and os.path.splitext(
                    u.toLocalFile())[1].lower() in self._IMG_EXTS]

    def canInsertFromMimeData(self, mime):
        return (bool(self._image_sources(mime))
                or super().canInsertFromMimeData(mime))

    def insertFromMimeData(self, mime):
        imgs = self._image_sources(mime)
        if imgs:
            self.sig_images.emit(imgs)
            return
        super().insertFromMimeData(mime)

    def dragEnterEvent(self, e):
        if self._image_sources(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        imgs = self._image_sources(e.mimeData())
        if imgs:
            self.sig_images.emit(imgs)
            e.acceptProposedAction()
            return
        super().dropEvent(e)

    def set_hint(self, text):
        """プレースホルダ文言を保持して適用する。"""
        self._hint = text or ""
        super().setPlaceholderText(self._hint)

    def keyPressEvent(self, e):
        # ShiftなしのEnterで送信(IME変換中の確定Enterは送信しない)
        if (e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not self._composing
                and not e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.sig_submit.emit()
            return
        super().keyPressEvent(e)

    def inputMethodEvent(self, e):
        # IME変換中(preedit)もdocumentは空のままのため、Qtのplaceholderが
        # 未確定文字列と重なって描画される。変換中はplaceholderを消す
        self._composing = bool(e.preeditString())
        super().setPlaceholderText("" if self._composing else self._hint)
        super().inputMethodEvent(e)

    def focusOutEvent(self, e):
        super().setPlaceholderText(self._hint)
        super().focusOutEvent(e)


class AiPanel(QDockWidget):
    sig_append = pyqtSignal(str, str)    # (kind, text) 表示はGUIスレッドで整形
    sig_instructions = pyqtSignal()      # ai_*ツールが指示書を更新した
    sig_agent_changed = pyqtSignal(str)  # ai_select_agentで選択切替(id)
    sig_confirm = pyqtSignal(str, str)   # ツール確認要求(name, args表示)
    sig_status = pyqtSignal(str)
    sig_busy = pyqtSignal(bool)
    sig_models = pyqtSignal(list, str)   # (models, error) モデル一覧取得結果
    sig_signin = pyqtSignal(str, str)    # (pid, token) デバイスフロー完了
    sig_open_url = pyqtSignal(str)       # ブラウザで開くURL(GUIスレッドで実行)

    def __init__(self, iface, get_driver, parent=None):
        super().__init__(
            QCoreApplication.translate(
                "qgis_live_driver", "AI Assistant"),
            parent or iface.mainWindow())
        self.setObjectName("QgisLiveAiPanel")
        self.iface = iface
        self._get_driver = get_driver
        self._history = []      # [{"role": "user"|"assistant", "content": str}]
        # チャットセッション。先頭は常に「現在のチャット」(コンボindexと一致)。
        # 過去チャットは {"title","history","html"} として後ろに積む
        self._sessions = [{"title": QCoreApplication.translate(
            "qgis_live_driver", "Current chat"),
            "history": self._history, "html": "",
            "agent": None}]
        self._open_chat = 0     # 表示中のセッションindex
        self._model_infos = {}  # {id: ai_client.model_info()}
        self._busy = False
        self._abort = False         # 中断ボタンで立つ。ループ境界で観測
        self._alive = True
        self._signin_abort = False
        self._confirm_event = threading.Event()
        self._confirm_result = False
        self._mcp_done = False       # 外部MCPの発見を済ませたか
        self._mcp_sessions = {}      # {name: McpSession} 切断用に保持
        self._plugins = []           # 直近送信時のプラグイン一覧(ctx推定用)
        self._instr_dlg = None       # 開いている指示書編集ダイアログ
        self._attachments = []       # 送信待ちの添付画像パス(PNG)
        self._usage = {"in": 0, "out": 0, "last": 0}  # API応答usage累計
        self.destroyed.connect(self._on_destroyed)

        root = QWidget(self)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 6, 6, 6)

        # ---- API設定 ----
        box = QGroupBox(self.tr("API settings"), root)
        form = QFormLayout(box)
        self.cmb_provider = QComboBox(box)
        for pid in _PROVIDER_IDS:
            self.cmb_provider.addItem(ai_client.tr_label(
                ai_client.PROVIDERS[pid]["label"]), pid)
        self.ed_endpoint = QLineEdit(box)
        self.ed_key = QLineEdit(box)
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.lbl_keystore = QLabel(credential_store.backend_label(), box)
        self.lbl_keystore.setStyleSheet("color:#666; font-size:11px")
        self.lbl_keystore.setWordWrap(True)
        self.cmb_model = QComboBox(box)
        self.cmb_model.setEditable(True)
        self.cmb_model.setToolTip(self.tr(
            "Model to use. Press \"Fetch\" to list models from the "
            "endpoint.\n"
            "Values in parentheses are prices per 1M tokens "
            "(input/output, $).\n"
            "Models in the \"Text (image input)\" group support sending "
            "screenshots."))
        model_row = QWidget(box)
        mr = QHBoxLayout(model_row)
        mr.setContentsMargins(0, 0, 0, 0)
        self.btn_models = QPushButton(self.tr("Fetch"), model_row)
        self.btn_models.setToolTip(self.tr(
            "Fetch the model list from the endpoint "
            "(GET {base}/models)"))
        mr.addWidget(self.cmb_model, 1)
        mr.addWidget(self.btn_models)
        self.lbl_model_info = QLabel(
            QCoreApplication.translate("qgis_live_driver", _MODEL_HINT),
            box)
        self.lbl_model_info.setStyleSheet("color:#666; font-size:11px")
        self.lbl_model_info.setWordWrap(True)
        self.chk_confirm = QCheckBox(
            self.tr("Confirm before running tools"), box)
        self.chk_confirm.setToolTip(self.tr(
            "When ON, asks for approval before each tool call.\n"
            "Use this if you do not want arbitrary code execution "
            "(pyeval) to run automatically."))
        # エージェント(常時注入する指示書 ~/.qgis-live/agents/*.md)
        agent_row = QWidget(box)
        ar = QHBoxLayout(agent_row)
        ar.setContentsMargins(0, 0, 0, 0)
        self.cmb_agent = QComboBox(box)
        self.cmb_agent.setToolTip(self.tr(
            "Instruction document (agent) injected on every request.\n"
            "Lists ~/.qgis-live/agents/*.md. Use \"Edit\" to create or "
            "modify."))
        self.btn_agent_edit = QPushButton(self.tr("Edit"), agent_row)
        self.btn_agent_edit.setToolTip(self.tr(
            "Create, edit, or delete agent instructions (.md)"))
        ar.addWidget(self.cmb_agent, 1)
        ar.addWidget(self.btn_agent_edit)
        form.addRow(self.tr("Agent"), agent_row)
        # スキル(オンデマンド手順書 ~/.qgis-live/skills/*.md。
        # 全件がプロンプトの一覧に載るため選択ではなく一覧表示)
        skill_row = QWidget(box)
        sk = QHBoxLayout(skill_row)
        sk.setContentsMargins(0, 0, 0, 0)
        self.cmb_skill = QComboBox(box)
        self.cmb_skill.setToolTip(self.tr(
            "On-demand instruction documents. All entries appear in the "
            "prompt list,\n"
            "and the model reads the body via qgis_pyeval's open() when "
            "needed.\n"
            "Lists ~/.qgis-live/skills/*.md. Use \"Edit\" to create or "
            "modify."))
        self.btn_skill_edit = QPushButton(self.tr("Edit"), skill_row)
        self.btn_skill_edit.setToolTip(self.tr(
            "Create, edit, or delete skill instructions (.md)"))
        sk.addWidget(self.cmb_skill, 1)
        sk.addWidget(self.btn_skill_edit)
        form.addRow(self.tr("Skill"), skill_row)
        # 外部MCPサーバ(~/.qgis-live/mcp_servers.json)
        mcp_row = QWidget(box)
        mk = QHBoxLayout(mcp_row)
        mk.setContentsMargins(0, 0, 0, 0)
        self.lbl_mcp = QLabel(self.tr("Not configured"), mcp_row)
        self.lbl_mcp.setStyleSheet("color:#666")
        self.btn_mcp = QPushButton(self.tr("Configure"), mcp_row)
        self.btn_mcp.setToolTip(self.tr(
            "Edit external MCP server settings (mcp_servers.json).\n"
            "command=launch via stdio / url=Streamable HTTP.\n"
            "Discovered tools become usable as "
            "mcp_<server>__<tool>."))
        mk.addWidget(self.lbl_mcp, 1)
        mk.addWidget(self.btn_mcp)
        form.addRow("MCP", mcp_row)
        # Copilot選択時のみ見せるOAuthデバイスフロー行
        self.w_signin = QWidget(box)
        sr = QHBoxLayout(self.w_signin)
        sr.setContentsMargins(0, 0, 0, 0)
        self.btn_signin = QPushButton(
            self.tr("Sign in with GitHub"), self.w_signin)
        self.btn_signin.setToolTip(self.tr(
            "Acquires a GitHub token via the OAuth device flow and sets "
            "it in the API key field.\n"
            "Enter the displayed code in the browser "
            "(github.com/login/device).\n"
            "Requires an account with a GitHub Copilot subscription."))
        sr.addWidget(self.btn_signin)
        lbl = QLabel(
            self.tr("GitHub account with a Copilot subscription"),
            self.w_signin)
        lbl.setStyleSheet("color:#666; font-size:11px")
        sr.addWidget(lbl, 1)
        self.w_signin.setVisible(False)
        form.addRow(self.tr("Provider"), self.cmb_provider)
        form.addRow(self.tr("Endpoint"), self.ed_endpoint)
        form.addRow(self.tr("API key"), self.ed_key)
        form.addRow("", self.w_signin)
        form.addRow(self.tr("Key storage"), self.lbl_keystore)
        form.addRow(self.tr("Model"), model_row)
        form.addRow("", self.lbl_model_info)
        form.addRow("", self.chk_confirm)
        lay.addWidget(box)
        self.box_api = box

        # ---- チャット履歴 ----
        crow = QHBoxLayout()
        self.btn_settings = QPushButton("⚙", root)
        self.btn_settings.setCheckable(True)
        self.btn_settings.setFixedWidth(32)
        self.btn_settings.setToolTip(self.tr(
            "Toggle visibility of the API settings"))
        crow.addWidget(self.btn_settings)
        self.btn_newchat = QPushButton(self.tr("New chat"), root)
        self.btn_newchat.setToolTip(self.tr(
            "Saves the current chat to history and starts a new one.\n"
            "The context (conversation history) is also reset."))
        self.cmb_chats = QComboBox(root)
        self.cmb_chats.setToolTip(self.tr(
            "Past chats. Select one to review it or continue the "
            "conversation."))
        self.cmb_chats.addItem(self.tr("Current chat"))
        crow.addWidget(self.btn_newchat)
        crow.addWidget(self.cmb_chats, 1)
        self.btn_chat_export = QPushButton("↓", root)
        self.btn_chat_export.setFixedWidth(26)
        self.btn_chat_export.setToolTip(self.tr(
            "Save the displayed chat to a Markdown file"))
        self.btn_chat_del = QPushButton("✕", root)
        self.btn_chat_del.setFixedWidth(26)
        self.btn_chat_del.setEnabled(False)
        self.btn_chat_del.setToolTip(self.tr(
            "Delete the displayed history chat (the current chat is "
            "excluded)"))
        crow.addWidget(self.btn_chat_export)
        crow.addWidget(self.btn_chat_del)
        lay.addLayout(crow)

        # ---- チャット表示 ----
        self.view = QTextBrowser(root)
        self.view.setOpenExternalLinks(True)
        lay.addWidget(self.view, 1)

        # ---- 添付画像(入力欄への貼付・D&D・📎ボタンで追加) ----
        self.attach_row = QWidget(root)
        ah = QHBoxLayout(self.attach_row)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(4)
        ah.addStretch(1)
        self.attach_row.setVisible(False)
        lay.addWidget(self.attach_row)

        # ---- 入力行 ----
        self.input = _Input(root)
        self._input_hint = self.tr(
            "Enter instructions (Enter to send / Shift+Enter for a new "
            "line / Ctrl+V or drag & drop to attach images).\n"
            "Use /agent and /skill to edit instructions directly "
            "(/help)")
        self.input.set_hint(self._input_hint)
        self.input.setMaximumHeight(64)
        lay.addWidget(self.input)

        row = QHBoxLayout()
        self.btn_attach = QPushButton("📎", root)
        self.btn_attach.setFixedWidth(30)
        self.btn_attach.setToolTip(self.tr(
            "Attach and send an image file.\n"
            "You can also paste (Ctrl+V) or drag & drop into the input "
            "field."))
        row.addWidget(self.btn_attach)
        self.btn_send = QPushButton(self.tr("Send"), root)
        self.btn_send.setToolTip(self.tr(
            "Enter also sends. While sending it changes to \"Abort\" "
            "and\n"
            "stops the ongoing round trip (in-flight API responses/"
            "tool executions cannot be interrupted)."))
        self.btn_retry = QPushButton(self.tr("Retry"), root)
        self.btn_retry.setEnabled(False)
        self.btn_retry.setToolTip(self.tr(
            "Discard the last question and its response, then resend"))
        self.btn_clear = QPushButton(self.tr("Clear history"), root)
        self.lbl_status = QLabel("", root)
        row.addWidget(self.btn_send)
        row.addWidget(self.btn_retry)
        row.addWidget(self.btn_clear)
        row.addWidget(self.lbl_status, 1)
        self.lbl_ctx = QLabel("", root)
        self.lbl_ctx.setStyleSheet("color:#666; font-size:11px")
        self.lbl_ctx.setToolTip(self.tr(
            "ctx: context usage (measured prompt_tokens from the last "
            "API response;\n"
            "if unavailable, an estimate marked with ~ using "
            "chars/3). The right value is the model limit.\n"
            "Σ: total tokens for this chat. $: estimated cost (when "
            "pricing info is available)"))
        row.addWidget(self.lbl_ctx)
        lay.addLayout(row)

        self.setWidget(root)
        self._load_settings()
        self._restore_chats()
        self._snapshot_fields()

        self.cmb_provider.currentIndexChanged.connect(
            self._on_provider_changed)
        self.cmb_model.activated.connect(self._on_model_activated)
        self.cmb_model.currentTextChanged.connect(
            self._on_model_text_changed)
        self.btn_models.clicked.connect(self._fetch_models)
        self.btn_send.clicked.connect(self._send_or_abort)
        self.btn_retry.clicked.connect(self._retry)
        self.btn_clear.clicked.connect(self._clear)
        self.btn_newchat.clicked.connect(self._new_chat)
        self.cmb_chats.activated.connect(self._switch_chat)
        self.btn_chat_export.clicked.connect(self._export_chat)
        self.btn_chat_del.clicked.connect(self._delete_chat)
        self.btn_settings.toggled.connect(self._on_settings_toggled)
        self.btn_agent_edit.clicked.connect(self._edit_agent)
        self.cmb_agent.activated.connect(self._on_agent_activated)
        self.btn_skill_edit.clicked.connect(self._edit_skills)
        self.btn_mcp.clicked.connect(self._edit_mcp)
        self.input.sig_submit.connect(self._send)
        self.input.sig_images.connect(self._on_pasted_images)
        self.btn_attach.clicked.connect(self._attach_files)
        self.input.textChanged.connect(self._refresh_send_button)
        self._refresh_send_button()
        self.sig_append.connect(self._append)
        self.sig_instructions.connect(self._refresh_instructions)
        self.sig_agent_changed.connect(self._on_agent_changed)
        self.sig_confirm.connect(self._on_confirm)
        self.sig_status.connect(self.lbl_status.setText)
        self.sig_busy.connect(self._set_busy)
        self.sig_models.connect(self._on_models)
        self.btn_signin.clicked.connect(self._signin)
        self.sig_signin.connect(self._on_signin)
        self.sig_open_url.connect(
            lambda u: QDesktopServices.openUrl(QUrl(u)))

    # ---- 設定の永続化 ----

    def _provider(self):
        return self.cmb_provider.currentData() or "openai"

    def _load_settings(self):
        s = QSettings()
        pid = s.value(_SETTING.format("provider"), "openai")
        idx = (_PROVIDER_IDS.index(pid) if pid in _PROVIDER_IDS else 0)
        self.cmb_provider.setCurrentIndex(idx)
        self._load_provider_fields()
        self.chk_confirm.setChecked(
            str(s.value(_SETTING.format("confirm"), "false")).lower()
            in ("1", "true"))
        # API設定の表示状態: 保存値が無い初回だけ、
        # キー未設定なら開く・設定済みなら畳む
        v = s.value(_SETTING.format("settings_visible"), None)
        if v is None:
            v = not credential_store.get_secret(f"ai_{pid}_api_key")
        else:
            v = str(v).lower() in ("1", "true")
        self.btn_settings.setChecked(bool(v))
        self.box_api.setVisible(self.btn_settings.isChecked())
        self._refresh_agents(s.value(_SETTING.format("agent"), ""))
        self._refresh_skills()
        self._update_mcp_label()

    def _on_settings_toggled(self, on):
        self.box_api.setVisible(on)
        QSettings().setValue(_SETTING.format("settings_visible"), on)

    # ---- エージェント(常時注入の指示書) ----

    def _refresh_agents(self, select_id=None):
        """エージェントコンボを ~/.qgis-live/agents/*.md で再構築する。"""
        cur = (select_id if select_id is not None
               else self.cmb_agent.currentData())
        self.cmb_agent.blockSignals(True)
        self.cmb_agent.clear()
        self.cmb_agent.addItem(self.tr("(none)"), None)
        for a in ai_client.list_agents():
            self.cmb_agent.addItem(a["title"], a["id"])
            tip = a["path"]
            if a.get("when"):
                tip = f"use_when: {a['when']}\n" + tip
            if a.get("desc"):
                tip = a["desc"] + "\n" + tip
            self.cmb_agent.setItemData(
                self.cmb_agent.count() - 1, tip,
                Qt.ItemDataRole.ToolTipRole)
        idx = self.cmb_agent.findData(cur)
        self.cmb_agent.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_agent.blockSignals(False)

    def _on_agent_activated(self, _idx):
        QSettings().setValue(_SETTING.format("agent"),
                             self.cmb_agent.currentData() or "")
        self._update_ctx_label()

    def _edit_agent(self):
        self._open_instruction_editor(
            "agents", self.cmb_agent.currentData())

    # ---- スキル(オンデマンド手順書。選択不要で全件が一覧に載る) ----

    def _refresh_skills(self):
        """スキルコンボを ~/.qgis-live/skills/*.md + 同梱品で再構築する。"""
        cur = self.cmb_skill.currentData()
        self.cmb_skill.blockSignals(True)
        self.cmb_skill.clear()
        skills = ai_client.list_skills()
        if not skills:
            self.cmb_skill.addItem(self.tr("(none)"), None)
        for s in skills:
            label = s["title"] + (self.tr(" (bundled)")
                                  if s["builtin"] else "")
            self.cmb_skill.addItem(label, s["id"])
            tip = s["path"]
            if s.get("when"):
                tip = f"use_when: {s['when']}\n" + tip
            if s.get("desc"):
                tip = s["desc"] + "\n" + tip
            self.cmb_skill.setItemData(
                self.cmb_skill.count() - 1, tip,
                Qt.ItemDataRole.ToolTipRole)
        idx = self.cmb_skill.findData(cur)
        self.cmb_skill.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_skill.blockSignals(False)

    def _edit_skills(self):
        self._open_instruction_editor(
            "skills", self.cmb_skill.currentData())

    # ---- 指示書編集 ----
    # 「編集」ダイアログは非モーダル。開いている間もチャット入力欄は
    # 通常通り使え、ダイアログ内のプロンプト欄からAIへ本文の修正を
    # 依頼できる(AIの ai_save_instruction 保存を sig_instructions で
    # 検知し、開いているダイアログの編集欄へ反映する)。

    def _open_instruction_editor(self, kind, select):
        """指示書編集ダイアログを(非モーダルで)開く。"""
        dlg = self._instr_dlg
        if dlg is not None:
            # 既に開いていれば種別/対象を切替えて前面へ
            i = dlg.cmb_kind.findData(kind)
            if i >= 0:
                dlg.cmb_kind.setCurrentIndex(i)
                dlg.reload(select)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = _InstructionsDialog(self, kind=kind, select=select)
        self._instr_dlg = dlg
        dlg.finished.connect(
            lambda _r: self._close_instruction_editor())
        dlg.show()

    def _close_instruction_editor(self):
        """ダイアログが閉じたら参照を外してコンボを再構築する。"""
        dlg = self._instr_dlg
        self._instr_dlg = None
        if dlg is not None:
            dlg.deleteLater()
        self._refresh_instructions()

    def _refresh_instructions(self):
        """AIのai_*ツールが指示書を更新した後のコンボ再構築。"""
        self._refresh_agents()
        self._refresh_skills()
        if self._instr_dlg is not None:
            self._instr_dlg.refresh_external()

    def _on_agent_changed(self, aid):
        """AIの ai_select_agent で選択中エージェントが切替わった。"""
        idx = self.cmb_agent.findData(aid or None)
        self.cmb_agent.setCurrentIndex(idx if idx >= 0 else 0)
        QSettings().setValue(_SETTING.format("agent"), aid or "")
        self._update_ctx_label()

    # ---- 外部MCPサーバ ----

    def _update_mcp_label(self):
        """MCP設定の状態を行ラベルに反映する。"""
        try:
            n = len(ai_client.mcp_servers_config())
        except ai_client.ApiError as e:
            self.lbl_mcp.setText(
                self.tr("Config error: {0}").format(e))
            return
        self.lbl_mcp.setText(
            self.tr("{0} server(s)").format(n) if n
            else self.tr("Not configured"))

    def _edit_mcp(self):
        dlg = _McpDialog(self)
        dlg.exec()
        self._update_mcp_label()
        if dlg.saved:
            self._reset_mcp()      # 次の送信で再ディスカバリ

    def _reset_mcp(self):
        """接続中のMCPセッションを閉じて未発見状態に戻す。"""
        for s in self._mcp_sessions.values():
            try:
                s.close()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        self._mcp_sessions = {}
        self._mcp_done = False
        ai_client.register_extra_tools([], {})

    def _ensure_mcp(self):
        """外部MCPサーバへ接続してツールを登録する(ワーカースレッド)。

        初回送信時の1回だけ実行。設定変更は _edit_mcp でリセットされる。
        """
        if self._mcp_done:
            return
        self._mcp_done = True
        if not ai_client.mcp_servers_config():
            self._emit(self.sig_append, "tool",
                       self.tr("MCP server not configured"))
            return
        self._emit(self.sig_status,
                   self.tr("Connecting to MCP servers…"))
        r = ai_client.mcp_discover(
            on_status=lambda m: self._emit(
                self.sig_append, "tool", m),
            is_aborted=lambda: self._abort)
        ai_client.register_extra_tools(r["tools"], r["callers"])
        self._mcp_sessions = r["sessions"]
        if self._abort:
            # 中断で未接続のまま。次の送信で再ディスカバリする
            self._mcp_done = False
            return
        for name, err in r["errors"].items():
            self._emit(self.sig_append, "error",
                       self.tr("MCP '{0}' connection failed: {1}")
                       .format(name, err))
        ok = {n: len(s.tools) for n, s in r["sessions"].items()}
        if ok:
            self._emit(self.sig_append, "tool",
                       self.tr("MCP connected: ") + ", ".join(
                           self.tr("{0} ({1} tools)").format(n, c)
                           for n, c in ok.items()))

    def _load_provider_fields(self):
        """現在のプロバイダの保存値(無ければ既定)を入力欄へ反映する。"""
        s = QSettings()
        pid = self._provider()
        d = ai_client.PROVIDERS[pid]
        self.w_signin.setVisible(pid == "copilot")
        # 旧キー(プロバイダ無し)からの移行: 新キーが無ければ読む

        def legacy(k, dv):
            return (
                s.value(_SETTING.format(f"{pid}_{k}"), None)
                if s.value(_SETTING.format(f"{pid}_{k}"), None) is not None
                else s.value(_SETTING.format(k), dv))
        ep = legacy("endpoint", d["base"]) if pid == "openai" \
            else s.value(_SETTING.format(f"{pid}_endpoint"), d["base"])
        # APIキーはOS資格情報ストアを優先し、
        # 無ければ従来のQSettings平文値(移行元)を読む
        key = credential_store.get_secret(f"ai_{pid}_api_key")
        if key is None:
            key = (legacy("api_key", "") if pid == "openai"
                   else s.value(_SETTING.format(f"{pid}_api_key"), ""))
        model = legacy("model", d["model"]) if pid == "openai" \
            else s.value(_SETTING.format(f"{pid}_model"), d["model"])
        self.ed_endpoint.setText(ep)
        self.ed_endpoint.setPlaceholderText(
            ai_client.tr_label(d["endpoint_hint"]))
        self.ed_key.setText(key)
        self.ed_key.setPlaceholderText(
            ai_client.tr_label(d["key_hint"]))
        self.cmb_model.clear()
        # 既定エンドポイント利用時は推奨モデル(種別・参考価格付き)を
        # 予めコンボへ載せる。カスタムエンドポイント(Ollama等)では
        # 一覧が異なるため載せず「取得」で実一覧を取る運用にする。
        if ep == d["base"]:
            infos = [ai_client.model_info({"id": m})
                     for m in ai_client.SUGGESTED_MODELS.get(pid, ())]
            self._set_model_items(infos, keep_text=model)
        else:
            self._model_infos = {}
        self.cmb_model.setEditText(model)
        self.cmb_model.lineEdit().setPlaceholderText(d["model"])
        self._update_model_info()

    def _save_settings(self):
        s = QSettings()
        pid = self._provider()
        s.setValue(_SETTING.format("provider"), pid)
        s.setValue(_SETTING.format(f"{pid}_endpoint"),
                   self.ed_endpoint.text())
        self._save_provider_key(pid, self.ed_key.text())
        s.setValue(_SETTING.format(f"{pid}_model"),
                   self._current_model())
        s.setValue(_SETTING.format("confirm"),
                   self.chk_confirm.isChecked())

    def _save_provider_key(self, pid, key):
        """APIキーをOS資格情報ストアへ保存する。

        QSettingsにはいかなる場合も平文を残さない。ストア書込みに
        失敗した場合はエラー表示する(平文フォールバックはしない)。
        その場合でも入力欄の値は残るため今回のセッション内では
        送信できるが、次回起動時は再入力が必要になる。
        """
        s = QSettings()
        name = f"ai_{pid}_api_key"
        if key:
            ok = credential_store.set_secret(name, key)
        else:
            ok = credential_store.delete_secret(name)
        s.remove(_SETTING.format(f"{pid}_api_key"))
        if ok:
            s.setValue(_SETTING.format(f"{pid}_key_store"),
                       credential_store.backend())
        else:
            s.remove(_SETTING.format(f"{pid}_key_store"))
            self._append(
                "error",
                self.tr(
                    "Could not save the API key to the OS credential "
                    "store (backend={0}). It is not saved in plain "
                    "text. The entered key can be used in this "
                    "session, but you will need to re-enter it next "
                    "time.")
                .format(credential_store.backend()))
        return ok

    def _on_provider_changed(self, _idx):
        """切替前のプロバイダの入力値を保存し、新プロバイダの値を読み込む。

        currentIndexChanged 時点で combo は既に新プロバイダを指すため、
        直前のプロバイダを保持しておく必要がある。
        """
        self._signin_abort = True  # 進行中のデバイスフローがあれば止める
        prev = getattr(self, "_prev_provider", None)
        if prev is not None and prev != self._provider():
            s = QSettings()
            s.setValue(_SETTING.format(f"{prev}_endpoint"),
                       self._prev_endpoint)
            self._save_provider_key(prev, self._prev_key)
            s.setValue(_SETTING.format(f"{prev}_model"),
                       self._prev_model)
        self._load_provider_fields()
        self._snapshot_fields()

    def _snapshot_fields(self):
        self._prev_provider = self._provider()
        self._prev_endpoint = self.ed_endpoint.text()
        self._prev_key = self.ed_key.text()
        self._prev_model = self._current_model()

    # ---- モデル選択 ----

    def _current_model(self):
        """選択中のモデルID。装飾付き表示("id   $x/$y")や
        グループ見出しが入っていてもIDだけを返す。"""
        data = self.cmb_model.currentData()
        t = self.cmb_model.currentText().strip()
        # itemDataは表示テキストがその項目のIDと一致する時だけ信用する
        # (選択後にテキストが書き換わるとcurrentIndexが旧項目を指し得る)
        if data and (not t or t == str(data)):
            return str(data)
        if not t or t.startswith("──"):
            return ""
        # モデルIDは空白を含まないため、表示装飾(空白2つ以上+価格)は剥がす
        return re.split(r"\s{2,}", t, maxsplit=1)[0].strip()

    def _set_model_items(self, infos, keep_text=None):
        """モデルコンボを種別グループ付きで再構築する。

        @returns 設定したモデル数
        """
        cur = (keep_text if keep_text is not None
               else self._current_model())
        self._model_infos = {i["id"]: i for i in infos}
        mdl = QStandardItemModel(self.cmb_model)
        n = 0
        for kind, label in ai_client.MODEL_KINDS:
            entries = [i for i in infos if i["kind"] == kind]
            if not entries:
                continue
            hdr = QStandardItem(f"── {ai_client.tr_label(label)} ──")
            hdr.setEnabled(False)          # 選択不可の見出し行
            f = hdr.font()
            f.setBold(True)
            hdr.setFont(f)
            mdl.appendRow(hdr)
            for i in entries:
                it = QStandardItem(ai_client.model_label(i))
                it.setData(i["id"], Qt.ItemDataRole.UserRole)
                it.setToolTip(ai_client.model_tooltip(i))
                mdl.appendRow(it)
                n += 1
        self.cmb_model.setModel(mdl)
        idx = self.cmb_model.findData(cur) if cur else -1
        if cur and idx >= 0:
            self.cmb_model.setCurrentIndex(idx)
            self.cmb_model.setEditText(cur)  # IDだけをline editに表示
        elif cur:
            self.cmb_model.setEditText(cur)
        self._update_model_info()
        return n

    def _on_model_activated(self, idx):
        """項目選択時、line editには装飾無しのIDだけを残す。"""
        data = self.cmb_model.itemData(idx)
        if data:
            self.cmb_model.setEditText(str(data))

    def _on_model_text_changed(self, _text):
        self._update_model_info()

    def _model_supports_images(self):
        """選択中モデルが画像入力対応と推定されるか。

        取得済み一覧(_model_infos)のkindを優先し、手入力の未知
        モデルは classify_model の名前ヒントで推定する。
        """
        mid = (self._current_model()
               or ai_client.PROVIDERS[self._provider()]["model"])
        info = self._model_infos.get(mid)
        kind = (info["kind"] if info
                else ai_client.classify_model(mid))
        return kind == "chat_vision"

    def _update_model_info(self):
        """モデル欄の下に選択中モデルの種別・価格等を表示する。"""
        ok_img = self._model_supports_images()
        self.btn_attach.setEnabled(ok_img)
        self.btn_attach.setToolTip(
            self.tr(
                "Attach and send an image file.\n"
                "You can also paste (Ctrl+V) or drag & drop into the "
                "input field.")
            if ok_img else
            self.tr(
                "The selected model does not support image input, so "
                "attachments are unavailable.\n"
                "Select a model from the \"Text (image input)\" "
                "group."))
        info = self._model_infos.get(self._current_model())
        if not info:
            self.lbl_model_info.setText(
                QCoreApplication.translate(
                    "qgis_live_driver", _MODEL_HINT))
            self._update_ctx_label()
            return
        parts = [ai_client.tr_label(ai_client.MODEL_KIND_LABELS.get(
            info["kind"], info["kind"]))]
        if info.get("price_desc"):
            src = ("API" if info["price_src"] == "api"
                   else self.tr("ref"))
            parts.append(f"{info['price_desc']} ({src})")
        ctx = ai_client.fmt_tokens(info.get("context"))
        if ctx:
            parts.append(self.tr("context {0}").format(ctx))
        if info["kind"] == "chat":
            parts.append(self.tr(
                "may not support image input (select a \"Text (image "
                "input)\" model to send images)"))
        elif info["kind"] != "chat_vision":
            parts.append(self.tr("not usable for chat"))
        self.lbl_model_info.setText(" / ".join(parts))
        self._update_ctx_label()   # 上限表示がモデル依存のため更新

    # ---- 表示 ----

    _STYLE = {
        "user": "#0759c7",
        "assistant": "#222222",
        "tool": "#666666",
        "cmd": "#666666",
        "error": "#b00020",
    }

    def _append(self, kind, text):
        color = self._STYLE.get(kind, "#222")
        label = {"user": self.tr("you"), "assistant": "AI",
                 "tool": "tool", "cmd": "cmd",
                 "error": "error"}.get(kind, kind)
        if kind == "assistant":
            # AI応答はMarkdownレンダリング(表・コードブロック・見出し等)
            body = f"<div style='color:{color}'>{_md(text)}</div>"
        elif kind == "tool":
            body = (f"<span style='color:{color}'>"
                    f"<pre style='margin:2px 0'>{_esc(text)}</pre></span>")
        else:
            body = f"<span style='color:{color}'>{_esc(text)}</span>"
        self.view.append(
            f"<div style='margin:6px 0'>"
            f"<b style='color:{color}'>[{label}]</b> {body}</div>")

    def _set_busy(self, busy):
        self._busy = busy
        self.input.setEnabled(not busy)
        self._refresh_send_button()
        self.btn_retry.setEnabled(not busy and bool(self._history))
        self.btn_chat_export.setEnabled(not busy)
        if busy:
            self.lbl_status.setText(self.tr("Running…"))
        if not busy:
            self._update_ctx_label()   # 往復終了=履歴確定のタイミング

    def _refresh_send_button(self):
        """送信ボタンで状態を示す。

        実行中は停止色の「中断」(中断ボタン)、待機中は「送信」で
        入力が空の間は無効化して入力待ちであることを示す。
        """
        if self._busy:
            self.btn_send.setText(self.tr("■ Abort"))
            self.btn_send.setStyleSheet(
                "background:#b03a2e; color:white;")
            self.btn_send.setEnabled(True)
        else:
            self.btn_send.setText(self.tr("Send"))
            self.btn_send.setStyleSheet("")
            self.btn_send.setEnabled(
                bool(self.input.toPlainText().strip())
                or bool(self._attachments))

    # ---- 添付画像 ----
    # クリップボード貼付・ドラッグ&ドロップ・📎ボタンで追加した画像は
    # PNGへ正規化してtempへ保存し、サムネイルチップとして入力欄の
    # 上に並べる。送信時にユーザメッセージへ同梱され、履歴にも残る
    # (tempファイルが残る間だけ表示・再送できる)。

    _ATTACH_MAX_SIDE = 2048   # 添付画像の長辺上限(トークン節約)

    def _add_attachment(self, src):
        """画像(QImage/QPixmap/ファイルパス)をPNG正規化して添付列へ。"""
        if not self._model_supports_images():
            self._append(
                "error",
                self.tr(
                    "The selected model does not support image input, "
                    "so attachments are unavailable (select a model "
                    "from the \"Text (image input)\" group)"))
            return
        if isinstance(src, str):
            img = QImage(src)
        elif isinstance(src, QPixmap):
            img = src.toImage()
        else:
            img = src
        if img is None or img.isNull():
            self._append("error",
                         self.tr("Cannot read as an image: {0}")
                         .format(src if isinstance(src, str)
                                 else self.tr("(pasted image)")))
            return
        if max(img.width(), img.height()) > self._ATTACH_MAX_SIDE:
            img = img.scaled(
                self._ATTACH_MAX_SIDE, self._ATTACH_MAX_SIDE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        path = ai_client.attachment_temp_path()
        if not img.save(path, "PNG"):
            self._append("error", self.tr(
                "Failed to save the attached image: {0}").format(path))
            return
        self._attachments.append(path)
        chip = QFrame(self.attach_row)
        chip.setFrameShape(QFrame.Shape.StyledPanel)
        cl = QHBoxLayout(chip)
        cl.setContentsMargins(2, 2, 2, 2)
        cl.setSpacing(2)
        thumb = QLabel(chip)
        thumb.setPixmap(QPixmap.fromImage(img).scaledToHeight(
            44, Qt.TransformationMode.SmoothTransformation))
        thumb.setToolTip(path)
        cl.addWidget(thumb)
        btn = QPushButton("✕", chip)
        btn.setFixedSize(18, 18)
        btn.setToolTip(self.tr("Remove this image"))
        cl.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
        btn.clicked.connect(
            lambda _c, p=path, w=chip: self._remove_attachment(p, w))
        lay = self.attach_row.layout()
        lay.insertWidget(lay.count() - 1, chip)  # stretchの直前
        self.attach_row.setVisible(True)
        self._refresh_send_button()

    def _remove_attachment(self, path, chip):
        try:
            self._attachments.remove(path)
        except ValueError:  # nosec B110  # 設計上の許容
            pass
        chip.deleteLater()
        if not self._attachments:
            self.attach_row.setVisible(False)
        self._refresh_send_button()

    def _clear_attachments(self):
        self._attachments = []
        lay = self.attach_row.layout()
        while lay.count() > 1:        # 末尾のstretchだけ残す
            w = lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.attach_row.setVisible(False)

    def _on_pasted_images(self, sources):
        for s in sources:
            self._add_attachment(s)

    def _attach_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Attach image"), "",
            self.tr("Image files (*.png *.jpg *.jpeg *.gif *.bmp *.webp"
                    " *.tif *.tiff)"))
        for p in paths:
            self._add_attachment(p)

    def _append_image(self, path):
        """送信した添付画像をチャット表示へ出す(ローカルimgタグ)。"""
        url = QUrl.fromLocalFile(path).toString()
        self.view.append(
            f"<div style='margin:2px 0 6px 0'>"
            f"<img src='{html.escape(url)}' width='240'></div>")

    def _update_ctx_label(self):
        """コンテキスト使用量と累計トークン/コストを右下に表示する。"""
        # ctx: 直近API応答のprompt_tokensがあれば実測値、無ければ文字数推定
        actual = self._usage.get("last", 0)
        if actual:
            est, mark = actual, ""
        else:
            try:
                chars = len(self._build_system(
                    self._plugins, self.cmb_agent.currentData()))
            except Exception:
                chars = 0
            chars += sum(len(m.get("content") or "")
                         for m in self._history)
            est, mark = chars // 3, "~"  # 日本語~1.5/英~4字の中間
        info = self._model_infos.get(self._current_model()) or {}
        lim = info.get("context")
        parts = [f"ctx {mark}{ai_client.fmt_tokens(est)}"
                 + (f"/{ai_client.fmt_tokens(lim)}"
                    f" ({est * 100 // lim}%)" if lim else "")]
        # 累計: APIがusageを返した時だけ表示。価格が分かればコストも
        total = self._usage["in"] + self._usage["out"]
        if total:
            parts.append(f"Σ{ai_client.fmt_tokens(total)}")
            cost = ai_client.usage_cost(info, self._usage)
            if cost is not None:
                parts.append(f"${cost:.4f}" if cost < 1
                             else f"${cost:.2f}")
        self.lbl_ctx.setText(" · ".join(parts))

    def _clear(self):
        self._history.clear()
        self.view.clear()
        self._update_ctx_label()

    # ---- チャット履歴 ----

    def _chat_title(self, history):
        """先頭のユーザーメッセージからタイトルを作る。"""
        for m in history:
            if m.get("role") == "user" and m.get("content"):
                t = m["content"].splitlines()[0].strip()
                return t[:30] + ("…" if len(t) > 30 else "")
        return self.tr("Chat {0}").format(len(self._sessions))

    def _save_open_chat(self):
        """表示中チャットの状態(履歴+表示HTML)をセッションへ書き戻す。

        空ビューのtoHtml()は空body付きの文書を返すため、
        表示テキストが無い場合はhtmlを空にしておく
        (「新しいチャット」で空セッションが履歴化されないように)。
        """
        s = self._sessions[self._open_chat]
        s["history"] = self._history
        s["html"] = (self.view.toHtml()
                     if self.view.toPlainText().strip() else "")
        s["agent"] = self.cmb_agent.currentData()
        s["usage"] = self._usage

    def _load_chat(self, idx):
        """セッションを表示状態にする(履歴・HTML・エージェントを更新)。"""
        s = self._sessions[idx]
        self._history = s["history"]
        self.view.setHtml(s["html"])
        ai = self.cmb_agent.findData(s.get("agent"))
        self.cmb_agent.setCurrentIndex(ai if ai >= 0 else 0)
        self._usage = dict(s.get("usage")
                           or {"in": 0, "out": 0, "last": 0})
        self._open_chat = idx
        # 「現在のチャット」(0)は削除対象外
        self.btn_chat_del.setEnabled(idx > 0)
        self._update_ctx_label()

    def _new_chat(self):
        """現在のチャットを履歴へ保存し、新規チャットを開始する。

        過去チャット表示中でも押せる: その表示状態を保存した上で
        新しい「現在のチャット」を開く。現在のチャットが空なら
        その表示に戻るだけ。
        """
        self._save_open_chat()
        live = self._sessions[0]
        if live["history"] or live["html"]:
            live["title"] = self._chat_title(live["history"])
            self._sessions.append(live)
            self.cmb_chats.addItem(live["title"])
            self._sessions[0] = {"title": self.tr("Current chat"),
                                 "history": [], "html": "", "agent": None}
        self._load_chat(0)
        self.cmb_chats.setCurrentIndex(0)

    def _switch_chat(self, idx):
        """履歴コンボの選択: 表示中を保存してから選択チャットを開く。"""
        if idx == self._open_chat or idx >= len(self._sessions):
            return
        self._save_open_chat()
        self._load_chat(idx)
        self._persist_chats()

    def _chats_path(self):
        """履歴永続化先 ~/.qgis-live/chats.json。"""
        return os.path.join(
            os.path.dirname(ai_client.agents_dir()), "chats.json")

    def _persist_chats(self):
        """アーカイブ済みチャット(セッション[1:])をファイルへ保存。"""
        try:
            data = self._sessions[1:][-50:]  # 最新50件まで
            with open(self._chats_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _restore_chats(self):
        """起動時に保存済みチャットをセッションとコンボへ復元する。"""
        try:
            with open(self._chats_path(), "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            return
        if not isinstance(saved, list):
            return
        for s in saved:
            if not isinstance(s, dict) \
                    or ("history" not in s and "html" not in s):
                continue
            s.setdefault("title", self.tr("Chat"))
            s.setdefault("history", [])
            s.setdefault("html", "")
            s.setdefault("agent", None)
            self._sessions.append(s)
            self.cmb_chats.addItem(str(s["title"]))

    def _delete_chat(self):
        """表示中の履歴チャットを削除して現在のチャットへ戻る。"""
        idx = self._open_chat
        if idx <= 0 or idx >= len(self._sessions):
            return  # 現在のチャット(0)は消せない
        del self._sessions[idx]
        self.cmb_chats.blockSignals(True)
        self.cmb_chats.removeItem(idx)
        self.cmb_chats.setCurrentIndex(0)
        self.cmb_chats.blockSignals(False)
        self._open_chat = -1        # _load_chatで確定させる
        self._load_chat(0)
        self._persist_chats()

    def _export_chat(self):
        """表示中チャットをMarkdownファイルへ保存。"""
        doc = QTextDocument()
        doc.setHtml(self.view.toHtml())
        md = doc.toMarkdown()
        if not md.strip():
            self._append("error", self.tr("Nothing to save"))
            return
        title = self._sessions[self._open_chat].get("title") or "chat"
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save chat"), f"{title}.md",
            "Markdown (*.md)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            self._append("tool", self.tr("Chat saved: {0}").format(path))
        except Exception as e:
            self._append("error", self.tr("Failed to save: {0}")
                         .format(e))

    def _on_destroyed(self):
        self._alive = False
        self._signin_abort = True
        self._reset_mcp()

    def _emit(self, sig, *args):
        """ワーカースレッドからのemit。パネル消去後は無視。"""
        if not self._alive:
            return
        try:
            sig.emit(*args)
        except RuntimeError:
            self._alive = False

    def hideEvent(self, e):
        self._save_settings()
        self._save_open_chat()
        self._persist_chats()
        super().hideEvent(e)

    # ---- モデル一覧取得 ----

    def _fetch_models(self):
        """「取得」ボタン: {base}/models から一覧を取り込む。"""
        pid = self._provider()
        base = (self.ed_endpoint.text().strip()
                or ai_client.PROVIDERS[pid]["base"])
        key = self.ed_key.text().strip()
        self.btn_models.setEnabled(False)
        self.lbl_status.setText(self.tr("Fetching model list…"))
        threading.Thread(
            target=self._models_run, args=(pid, base, key),
            daemon=True, name="qgis-ai-models").start()

    def _models_run(self, pid, base, key):
        try:
            infos = ai_client.list_model_infos(pid, base, key)
            self._emit(self.sig_models, infos, "")
        except Exception as e:
            self._emit(self.sig_models, [], str(e))

    def _on_models(self, infos, error):
        self.btn_models.setEnabled(True)
        self.lbl_status.setText("")
        if error:
            self._append("error", self.tr(
                "Failed to fetch the model list: {0}").format(error))
            return
        n = self._set_model_items(infos)
        self._append("tool", self.tr(
            "Fetched {0} model(s)").format(n))

    # ---- GitHubサインイン (OAuthデバイスフロー) ----

    def _signin(self):
        """「GitHubでサインイン」: デバイスフローでトークンを取得する。

        ボタンはcopilot選択時のみ表示。ポーリングはワーカースレッド、
        完了は sig_signin でGUIスレッドに戻す。
        """
        self._signin_abort = False
        self.btn_signin.setEnabled(False)
        threading.Thread(target=self._signin_run, daemon=True,
                         name="qgis-ai-signin").start()

    def _signin_run(self):
        try:
            d = ai_client.github_device_code()
        except Exception as e:
            self._emit(self.sig_append, "error",
                       self.tr("Failed to get a device code for "
                               "sign-in: {0}").format(e))
            self._emit(self.sig_signin, "copilot", "")
            return
        uri = d.get("verification_uri") or "https://github.com/login/device"
        code = d["user_code"]
        self._emit(self.sig_append, "tool",
                   self.tr("GitHub sign-in: open {0} and enter code "
                           "{1}").format(uri, code))
        self._emit(self.sig_status,
                   self.tr("Entering code {0} on GitHub…")
                   .format(code))
        self._emit(self.sig_open_url, uri)
        interval = max(int(d.get("interval") or 5), 3)
        deadline = time.time() + int(d.get("expires_in") or 900)
        token = err = None
        while time.time() < deadline:
            if self._signin_abort or not self._alive:
                err = self.tr("Aborted")
                break
            time.sleep(interval)
            try:
                r = ai_client.github_poll_access_token(d["device_code"])
            except Exception as e:
                err = self.tr("Polling failed: {0}").format(e)
                break
            if r.get("access_token"):
                token = r["access_token"]
                break
            e = r.get("error")
            if e == "slow_down":
                interval += 5
            elif e != "authorization_pending":
                err = (f"{e}: {r.get('error_description') or ''}"
                       .rstrip(": "))
                break
        if token:
            self._emit(self.sig_append, "tool",
                       self.tr("GitHub sign-in completed. The token "
                               "was set in the API key field"))
        else:
            self._emit(self.sig_append, "error",
                       self.tr("GitHub sign-in: {0}")
                       .format(err or self.tr("Code expired")))
        self._emit(self.sig_status, "")
        self._emit(self.sig_signin, "copilot", token or "")

    def _on_signin(self, pid, token):
        """デバイスフロー完了(GUIスレッド)。トークンをキー欄へ保存。"""
        self.btn_signin.setEnabled(True)
        if token and self._provider() == pid:
            self.ed_key.setText(token)
            self._save_provider_key(pid, token)
            self._snapshot_fields()

    # ---- 送信/エージェントループ ----

    def _send_or_abort(self):
        """送信ボタン: 実行中なら中断フラグを立てる。"""
        if self._busy:
            self._abort = True
            self.lbl_status.setText(self.tr("Aborting…"))
            # 中断要求を受理したことが見えるようボタン側も変える
            self.btn_send.setText(self.tr("Aborting…"))
            self.btn_send.setEnabled(False)
            return
        self._send()

    def _retry(self):
        """最後の質問+応答を取り消して同じ質問を再送する。"""
        if self._busy or not self._history:
            return
        while self._history and self._history[-1]["role"] != "user":
            self._history.pop()
        if not self._history:
            return
        msg = self._history.pop()
        self.input.setPlainText(msg["content"])
        for p in msg.get("images") or []:
            if os.path.isfile(p):
                self._add_attachment(p)
        self._send()

    def _send(self):
        text = self.input.toPlainText().strip()
        images = list(self._attachments)
        if (not text and not images) or self._busy:
            return
        if text and self._chat_command(text):
            self.input.clear()
            return
        if self._send_prompt(text, images):
            self.input.clear()
            self._clear_attachments()

    def _send_prompt(self, text, images=None):
        """ユーザーメッセージをAPIへ送る。送信を開始できたらTrue。

        images は添付画像(PNGパス列)。テキスト無しでも画像だけ送れる。
        指示書編集ダイアログの「AIに修正を依頼」からも呼ぶ。
        """
        if self._busy:
            self._append("error",
                         self.tr("Cannot send while running "
                                 "(retry after it completes)"))
            return False
        images = [p for p in (images or []) if os.path.isfile(p)]
        vision = self._model_supports_images()
        if images and not vision:
            self._append(
                "error",
                self.tr(
                    "The selected model does not support image input, "
                    "so images cannot be sent (select a model from "
                    "the \"Text (image input)\" group)"))
            return False
        # 送信の応答を速くするため、GUI側の準備(ドライバ生成・設定保存・
        # 履歴描画)より先にボタンを「中断」表示へ切替えて即再描画する
        # (通常の再描画はこの関数が戻るまで遅延されるため)。
        # 準備が失敗したら待機表示へ戻す
        self._abort = False
        self.sig_busy.emit(True)
        self.btn_send.repaint()
        self.lbl_status.repaint()
        try:
            driver = self._get_driver()  # 生成を伴うため必ずGUIスレッドで取得
            if driver is None:
                raise RuntimeError(
                    self.tr("could not prepare the live driver"))
            plugins = []
            try:
                import qgis.utils
                plugins = sorted(qgis.utils.plugins.keys())
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._plugins = plugins
            pid = self._provider()
            cfg = {
                "provider": pid,
                "base": (self.ed_endpoint.text().strip()
                         or ai_client.PROVIDERS[pid]["base"]),
                "key": self.ed_key.text().strip(),
                "model": (self._current_model()
                          or ai_client.PROVIDERS[pid]["model"]),
                # モデルの画像対応推定。スクショの画像返却に使う
                "vision": vision,
                "agent": self.cmb_agent.currentData(),
                "confirm": self.chk_confirm.isChecked(),
            }
            self._save_settings()
            self._append("user", text or self.tr("(image only)"))
            for p in images:
                self._append_image(p)
        except Exception as e:
            self.sig_busy.emit(False)
            self._append("error", str(e))
            return False
        threading.Thread(
            target=self._agent_run,
            args=(driver, cfg, plugins, text, images),
            daemon=True, name="qgis-ai-agent").start()
        return True

    # チャット入力のローカルコマンド(APIへは送らない)。
    # '/<cmd> <名前>' のあと同一行または改行以降を指示書本文とする。
    _CHAT_CMDS = {"/agent": "agents", "/agents": "agents",
                  "/skill": "skills", "/skills": "skills"}

    _CMD_USAGE = QT_TRANSLATE_NOOP(
        "qgis_live_driver",
        "Instruction commands (run locally, not sent to the API):\n"
        "  /agent               Show the current agent and list\n"
        "  /agent <name>        Switch agent\n"
        "  /agent <name> <body> Save an agent and select it\n"
        "  /skill               List skills\n"
        "  /skill <name>        Show a skill's body\n"
        "  /skill <name> <body> Save a skill\n"
        "(The body can span multiple lines starting from line 2)")

    def _chat_command(self, text):
        """'/agent' '/skill' 系の入力をローカルコマンドとして処理する。

        指示書(agents|skills の .md)の保存・切替・参照をAPIを介さず
        直接行う。処理した場合True(APIへは送らない)。該当しない
        コマンド名の '/' 入力はFalse(通常メッセージとして送信)。
        """
        first, _, rest = text.partition("\n")
        toks = first.split(None, 2)
        if toks[0].lower() in ("/help", "/?"):
            self._append("user", text)
            self._append("cmd", QCoreApplication.translate(
                "qgis_live_driver", self._CMD_USAGE))
            return True
        kind = self._CHAT_CMDS.get(toks[0].lower())
        if kind is None:
            return False
        name = toks[1] if len(toks) > 1 else ""
        body = ((toks[2] + "\n" if len(toks) > 2 else "") + rest).strip()
        self._append("user", text)
        try:
            if not name:
                msg = ai_client.run_instruction_tool(
                    "ai_list_instructions", {"kind": kind})
                if kind == "agents":
                    cur = self.cmb_agent.currentData()
                    msg = (self.tr("Selected: {0}").format(
                        cur or self.tr("(none)")) + "\n" + msg)
                self._append("cmd", msg)
                return True
            if not body:
                if kind == "agents":
                    self._cmd_select_agent(name)
                else:
                    self._cmd_show_instruction(kind, name)
                return True
            self._cmd_save_instruction(kind, name, body)
        except ai_client.ApiError as e:
            self._append("error", str(e))
        return True

    def _cmd_select_agent(self, name):
        """'/agent <名前>' — 既存エージェントへ切替える。"""
        stem = re.sub(r'[\\/:*?"<>|\s]+', "_", name)
        if ai_client.load_instruction("agents", stem) is None:
            raise ai_client.ApiError(
                self.tr("agent '{0}' not found "
                        "(provide a body to save it as new)")
                .format(stem))
        self._on_agent_changed(stem)
        self._append("cmd", self.tr("Switched agent to '{0}'")
                     .format(stem))

    def _cmd_show_instruction(self, kind, name):
        """'/skill <名前>' — 指示書の本文を表示する。"""
        stem = re.sub(r'[\\/:*?"<>|\s]+', "_", name)
        text = ai_client.load_instruction(kind, stem)
        if text is None:
            raise ai_client.ApiError(
                self.tr("skill '{0}' not found "
                        "(provide a body to save it as new)")
                .format(stem))
        self._append("cmd", text)

    def _cmd_save_instruction(self, kind, name, body):
        """'/agent|skill <名前> <本文>' — 指示書を保存する。"""
        p = ai_client.save_instruction(kind, name, body)
        stem = os.path.splitext(os.path.basename(p))[0]
        self._refresh_instructions()
        label = (self.tr("agent") if kind == "agents"
                 else self.tr("skill"))
        if kind == "agents":
            self._on_agent_changed(stem)
            self._append(
                "cmd", self.tr("{0} '{1}' saved and selected\n{2}")
                .format(label, stem, p))
        else:
            self._append("cmd", self.tr("{0} '{1}' saved\n{2}")
                         .format(label, stem, p))

    def _build_system(self, plugins, agent_id):
        """選択中エージェント+スキル/エージェント一覧込みのsystem prompt。"""
        return ai_client.system_prompt(
            plugins,
            agent_text=ai_client.load_agent(agent_id),
            skills=ai_client.list_skills(),
            agents=ai_client.list_agents(),
            active_agent=agent_id)

    def _agent_run(self, driver, cfg, plugins, user_text, user_images):
        """ワーカースレッド: API呼出 + ツール実行のループ。"""
        try:
            prov = ai_client.get_provider(cfg["provider"])
        except ai_client.ApiError as e:
            self._emit(self.sig_append, "error", str(e))
            self._emit(self.sig_status, "")
            self._emit(self.sig_busy, False)
            return
        self._ensure_mcp()
        system = self._build_system(plugins, cfg.get("agent"))
        msgs = prov.build_messages(
            system, ai_client.trim_history(self._history),
            user_text, user_images)
        final_text = ""
        try:
            for _ in range(ai_client.MAX_TOOL_ROUNDS):
                if self._abort:
                    final_text = self.tr("(aborted)")
                    self._emit(self.sig_append, "error", final_text)
                    break
                self._emit(self.sig_status,
                           self.tr("Waiting for API response…"))
                data = prov.send(cfg["base"], cfg["key"], cfg["model"],
                                 system, msgs)
                turn = prov.parse(data)
                u = turn.get("usage")
                if u:
                    self._usage["in"] += u.get("in", 0)
                    self._usage["out"] += u.get("out", 0)
                    self._usage["last"] = u.get("in", 0)
                if turn["text"]:
                    self._emit(self.sig_append, "assistant", turn["text"])
                if not turn["calls"]:
                    final_text = turn["text"]
                    break
                results = []
                for c in turn["calls"]:
                    if self._abort:
                        results.append({"text": "ABORTED by user",
                                        "image": None})
                    else:
                        results.append(
                            self._run_tool(driver, cfg,
                                           c["name"], c["args"]))
                prov.append_exchange(msgs, turn, results)
                # ai_select_agent: 選択中エージェントの切替を反映し
                # システムプロンプトを組み直す(最後の指定が優先)
                sel = [r["agent_select"] for r in results
                       if "agent_select" in r]
                if sel:
                    aid = sel[-1]
                    cfg["agent"] = aid
                    system = self._build_system(plugins, aid or None)
                    if msgs and msgs[0].get("role") == "system":
                        msgs[0]["content"] = system  # OpenAI形式。
                        # Gemini/Anthropicはsend時にsystemを別渡し
                        # するため変数で追従
                    self._emit(self.sig_agent_changed, aid or "")
            else:
                final_text = self.tr(
                    "(tool round-trip limit reached)")
                self._emit(self.sig_append, "error", final_text)
            # 会話履歴はテキスト対のみ保持(ツール詳細は畳む)。
            # 添付画像はPNGパスとしてuserエントリに残し、後続ターンの
            # build_messagesがワイヤ形式へ再変換する
            entry = {"role": "user", "content": user_text}
            if user_images:
                entry["images"] = list(user_images)
            self._history.append(entry)
            if final_text:
                self._history.append(
                    {"role": "assistant", "content": final_text})
        except ai_client.ApiError as e:
            self._emit(self.sig_append, "error", str(e))
        except Exception:
            import traceback
            self._emit(self.sig_append, "error", traceback.format_exc())
        finally:
            self._emit(self.sig_status, "")
            self._emit(self.sig_busy, False)

    def _run_tool(self, driver, cfg, name, args):
        """ツール呼び出しをドライバにdispatchして正規化結果を返す。

        @returns {"text": str, "image": path|None}
        """
        if self._abort:
            return {"text": "ABORTED", "image": None}
        # 確認モード: 実行のたびにユーザへ可否を問う
        if cfg.get("confirm") and not self._confirm_tool(name, args):
            self._emit(self.sig_append, "tool",
                       self.tr("{0} → skipped by user").format(name))
            return {"text": "SKIPPED: user denied", "image": None}
        if name in ai_client.INSTRUCTION_TOOL_NAMES:
            return self._run_instruction_tool(name, args)
        if (name or "").startswith("mcp_"):
            return self._run_extra_tool(name, args)
        try:
            cmd = ai_client.tool_to_command(name, args)
        except ai_client.ApiError as e:
            self._emit(self.sig_append, "error", str(e))
            return {"text": f"ERROR: {e}", "image": None}
        disp = {k: v for k, v in cmd.items() if k != "type"}
        self._emit(self.sig_append, "tool",
                   f"{name} {json.dumps(disp, ensure_ascii=False)}")
        if cmd["type"] == "screenshot" and not cmd.get("path"):
            cmd["path"] = ai_client.screenshot_temp_path()
        self._emit(self.sig_status,
                   self.tr("{0} running…").format(name))
        rep = driver.submit(cmd)
        text = ai_client.reply_to_text(rep)
        self._emit(self.sig_append, "tool",
                   f"→ {text[:2000]}"
                   + ("…" if len(text) > 2000 else ""))
        # スクリーンショットは画像対応モデルの時だけ画像として返す
        # (非対応モデルへ画像を送るとAPIエラーになるため)
        image = None
        if (cmd["type"] == "screenshot" and "error" not in rep
                and cfg["vision"]):
            image = rep.get("result")
        return {"text": text, "image": image}

    def _run_instruction_tool(self, name, args):
        """ai_* ツール: 指示書ファイルのパネルローカル操作。

        ファイルI/OのみでGUI操作を含まないためワーカースレッドで
        実行できる。UIのコンボ更新はシグナルでGUIスレッドに戻す。
        """
        self._emit(self.sig_append, "tool",
                   f"{name} {json.dumps(args or {}, ensure_ascii=False)}")
        self._emit(self.sig_status,
                   self.tr("{0} running…").format(name))
        r = {"text": "", "image": None}
        if name == "ai_select_agent":
            # 選択状態はパネルのUI状態。結果dictのagent_selectキーを
            # エージェントループが拾ってsystem promptを組み直す
            aid = ((args or {}).get("id") or "").strip()
            if aid and not any(a["id"] == aid
                               for a in ai_client.list_agents()):
                r["text"] = f"ERROR: agents '{aid}' not found"
            else:
                r["text"] = (f"active agent set: {aid}" if aid
                             else "active agent cleared")
                r["agent_select"] = aid
        else:
            try:
                r["text"] = ai_client.run_instruction_tool(name, args)
            except ai_client.ApiError as e:
                r["text"] = f"ERROR: {e}"
            except Exception as e:
                r["text"] = f"ERROR: {type(e).__name__}: {e}"
            self._emit(self.sig_instructions)
        text = r["text"]
        self._emit(self.sig_append, "tool",
                   f"→ {text[:2000]}"
                   + ("…" if len(text) > 2000 else ""))
        return r

    def _run_extra_tool(self, name, args):
        """外部MCPツール(mcp_<server>__<tool>)をセッション経由で実行。"""
        self._emit(self.sig_append, "tool",
                   f"{name} {json.dumps(args or {}, ensure_ascii=False)}")
        self._emit(self.sig_status,
                   self.tr("{0} running…").format(name))
        try:
            text = ai_client.run_extra_tool(name, args)
        except ai_client.ApiError as e:
            text = f"ERROR: {e}"
        except Exception as e:
            text = f"ERROR: {type(e).__name__}: {e}"
        self._emit(self.sig_append, "tool",
                   f"→ {text[:2000]}"
                   + ("…" if len(text) > 2000 else ""))
        return {"text": text, "image": None}

    # ---- ツール実行の確認(確認モード) ----

    def _confirm_tool(self, name, args):
        """ワーカースレッド→GUIスレッドでYes/Noを聞き結果を返す。

        モーダル表示中もワーカーはポーリング待機し、中断やパネル
        消去で打ち切れる(デッドロック防止)。
        """
        self._confirm_event.clear()
        self._emit(self.sig_confirm, name,
                   json.dumps(args or {}, ensure_ascii=False)[:400])
        while not self._confirm_event.wait(0.3):
            if self._abort or not self._alive:
                return False
        return bool(self._confirm_result)

    def _on_confirm(self, name, args_text):
        """確認ダイアログを出す(GUIスレッド)。"""
        ok = QMessageBox.question(
            self, self.tr("Confirm tool execution"),
            self.tr("Run {0}?\n\n{1}").format(name, args_text),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes
        self._confirm_result = ok
        self._confirm_event.set()


class _McpDialog(QDialog):
    """外部MCPサーバ設定(~/.qgis-live/mcp_servers.json)の編集。

    Claude Desktop互換のJSONをそのまま編集する。
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(
            self.tr("External MCP server settings"))
        self.resize(560, 420)
        self.saved = False
        lay = QVBoxLayout(self)
        lbl = QLabel(
            self.tr(
                "Configure external MCP servers in "
                "{\"mcpServers\": {...}} format.\n"
                "command=launch via stdio / url=Streamable HTTP. "
                "Discovered tools are usable as "
                "mcp_<server>__<tool>.\n"
                "oauth.client_secret is moved to the OS credential "
                "store on save, leaving only a $store: reference in "
                "the config file.\n"
                "Saving an empty field disables MCP servers, and "
                "saving reconnects on the next send."), self)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#666; font-size:11px")
        lay.addWidget(lbl)
        self.ed = QPlainTextEdit(self)
        try:
            with open(ai_client.mcp_config_path(), "r",
                      encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = json.dumps(ai_client.MCP_CONFIG_TEMPLATE,
                              ensure_ascii=False, indent=2)
        self.ed.setPlainText(text)
        lay.addWidget(self.ed, 1)
        # 接続例(read-only)。クリックでエディタへマージ挿入できる
        grp = QGroupBox(self.tr("Connection examples"), self)
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(4, 4, 4, 4)
        self.ed_sample = QPlainTextEdit(grp)
        self.ed_sample.setReadOnly(True)
        self.ed_sample.setPlainText(
            json.dumps(ai_client.MCP_CONFIG_TEMPLATE,
                       ensure_ascii=False, indent=2))
        self.ed_sample.setMaximumHeight(120)
        self.ed_sample.setStyleSheet(
            "font-family:Consolas,monospace; font-size:11px;"
            "background:#f6f6f6")
        gl.addWidget(self.ed_sample)
        btn_insert = QPushButton(
            self.tr("Insert example into editor"), grp)
        gl.addWidget(btn_insert)
        lay.addWidget(grp)
        row = QHBoxLayout()
        btn_save = QPushButton(self.tr("Save"), self)
        btn_close = QPushButton(self.tr("Close"), self)
        row.addWidget(btn_save)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)
        btn_save.clicked.connect(self._save)
        btn_insert.clicked.connect(self._insert_sample)
        btn_close.clicked.connect(self.reject)

    def _insert_sample(self):
        """接続例をエディタのmcpServersへマージ挿入する。"""
        try:
            d = json.loads(self.ed.toPlainText() or "{}")
        except Exception as e:
            QMessageBox.warning(self, self.tr("MCP settings"),
                                self.tr("Cannot read JSON: {0}")
                                .format(e))
            return
        if not isinstance(d, dict):
            d = {}
        sv = d.setdefault("mcpServers", {})
        for name, conf in ai_client.MCP_CONFIG_TEMPLATE[
                "mcpServers"].items():
            if name not in sv:
                sv[name] = conf
        self.ed.setPlainText(
            json.dumps(d, ensure_ascii=False, indent=2))

    def _save(self):
        text = self.ed.toPlainText()
        try:
            saved = ai_client.mcp_save_config(text)
        except ai_client.ApiError as e:
            QMessageBox.warning(self, self.tr("MCP settings"), str(e))
            return
        if saved != text:
            self.ed.setPlainText(saved)
            # $store: 参照が増えた時だけclient_secret移行を通知する
            # (空欄→{"mcpServers": {}} 等の正規化では出さない)
            if (saved.count(ai_client.MCP_SECRET_REF)
                    > text.count(ai_client.MCP_SECRET_REF)):
                QMessageBox.information(
                    self, self.tr("MCP settings"),
                    self.tr("Moved client_secret to the OS credential "
                            "store; only a $store: reference remains "
                            "in the config file."))
        self.saved = True
        self.accept()


class _InstructionsDialog(QDialog):
    """指示書(agents|skills の *.md)の作成・編集・削除ダイアログ。

    保存は常にユーザ側 ~/.qgis-live/<kind>/ へ書く。
    プラグイン同梱(bundled)は読み取り専用だが、同名で保存すれば
    ユーザ側ファイルとして優先される(実質の上書き)。
    """

    _KINDS = [("agents",
               QT_TRANSLATE_NOOP("qgis_live_driver", "Agents")),
              ("skills",
               QT_TRANSLATE_NOOP("qgis_live_driver", "Skills"))]

    def __init__(self, parent, kind="agents", select=None):
        super().__init__(parent)
        self.setWindowTitle(
            self.tr("Edit instructions (agents/skills)"))
        self.resize(760, 480)
        lay = QVBoxLayout(self)
        self.cmb_kind = QComboBox(self)
        for kid, label in self._KINDS:
            self.cmb_kind.addItem(
                QCoreApplication.translate("qgis_live_driver", label),
                kid)
        lay.addWidget(self.cmb_kind)
        self.cmb = QComboBox(self)
        lay.addWidget(self.cmb)
        self.ed_name = QLineEdit(self)
        self.ed_name.setPlaceholderText(self.tr(
            "Name (file name; saved as <name>.md. e.g. map-design)"))
        lay.addWidget(self.ed_name)
        # 編集(Markdown入力)と表示(レンダリング)を左右に分割
        split = QSplitter(Qt.Orientation.Horizontal, self)
        ed_box = QGroupBox(self.tr("Edit (Markdown)"), split)
        eb = QVBoxLayout(ed_box)
        eb.setContentsMargins(4, 4, 4, 4)
        self.ed_body = QPlainTextEdit(ed_box)
        eb.addWidget(self.ed_body)
        pv_box = QGroupBox(self.tr("Preview"), split)
        pb = QVBoxLayout(pv_box)
        pb.setContentsMargins(4, 4, 4, 4)
        self.preview = QTextBrowser(pv_box)
        self.preview.setOpenExternalLinks(True)
        pb.addWidget(self.preview)
        split.addWidget(ed_box)
        split.addWidget(pv_box)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        self.ed_body.textChanged.connect(self._update_preview)
        # 編集/表示ペインのスクロール位置を比率で相互に追従させる
        self._syncing_scroll = False
        self.ed_body.verticalScrollBar().valueChanged.connect(
            lambda _v: self._sync_scroll(self.ed_body, self.preview))
        self.preview.verticalScrollBar().valueChanged.connect(
            lambda _v: self._sync_scroll(self.preview, self.ed_body))
        self.lbl_hint = QLabel("", self)
        self.lbl_hint.setStyleSheet("color:#666; font-size:11px")
        self.lbl_hint.setWordWrap(True)
        lay.addWidget(self.lbl_hint)
        # AIへの修正依頼: 編集欄の本文と指示をチャットへ送り、
        # AIが ai_save_instruction で保存した結果を編集欄へ反映する
        prow = QHBoxLayout()
        self.ed_prompt = _Input(self)
        self.ed_prompt.set_hint(
            self.tr("Edit instructions for the AI (Enter to send)"))
        self.ed_prompt.setMaximumHeight(48)
        self.ed_prompt.setToolTip(
            self.tr("e.g. \"Add a summary section\" \"Make the tone "
                    "more concise\""))
        self.btn_ai = QPushButton(
            self.tr("Ask AI to revise"), self)
        self.btn_ai.setToolTip(
            self.tr(
                "Send the editor body and the instructions above to "
                "the chat AI.\n"
                "When the AI saves, the result is reflected in the "
                "editor (not while there are unsaved manual edits)"))
        prow.addWidget(self.ed_prompt, 1)
        prow.addWidget(self.btn_ai)
        lay.addLayout(prow)
        row = QHBoxLayout()
        self.btn_save = QPushButton(self.tr("Save"), self)
        self.btn_del = QPushButton(self.tr("Delete"), self)
        self.btn_dir = QPushButton(
            self.tr("Open folder"), self)
        btn_close = QPushButton(self.tr("Close"), self)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_del)
        row.addWidget(self.btn_dir)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)
        self.cmb_kind.activated.connect(lambda _i: self.reload())
        self.cmb.activated.connect(self._pick)
        self.btn_save.clicked.connect(self._save)
        self.btn_del.clicked.connect(self._delete)
        self.btn_dir.clicked.connect(self._open_dir)
        btn_close.clicked.connect(self.accept)
        self.ed_prompt.sig_submit.connect(self._ask_ai)
        self.btn_ai.clicked.connect(self._ask_ai)
        self._items = {}
        self._loaded_body = ""   # 最後に読込/保存した本文(外部変更検知用)
        i = self.cmb_kind.findData(kind)
        self.cmb_kind.setCurrentIndex(i if i >= 0 else 0)
        self.reload(select)

    def _update_preview(self):
        """編集中のMarkdownを表示ペインにレンダリングする。"""
        # setMarkdown で表示側が先頭へ巻き戻るため、その間の
        # 逆方向同期(表示→編集)を抑止し、描画後に編集側の
        # スクロール位置へ合わせ直す
        self._syncing_scroll = True
        try:
            self.preview.setMarkdown(self.ed_body.toPlainText())
        finally:
            self._syncing_scroll = False
        self._sync_scroll(self.ed_body, self.preview)

    def _sync_scroll(self, src, dst):
        """src のスクロール比率を dst へ反映する(双方向の追従用)。"""
        if self._syncing_scroll:
            return
        s = src.verticalScrollBar()
        d = dst.verticalScrollBar()
        ratio = s.value() / s.maximum() if s.maximum() > 0 else 0.0
        self._syncing_scroll = True
        try:
            d.setValue(int(round(d.maximum() * ratio)))
        finally:
            self._syncing_scroll = False

    def _kind(self):
        return self.cmb_kind.currentData() or "agents"

    def _kind_label(self):
        return self.cmb_kind.currentText()

    def reload(self, select=None):
        kind = self._kind()
        self._items = {a["id"]: a for a in
                       ai_client.list_instruction_files(kind)}
        self.lbl_hint.setText(
            self.tr(
                "Agents: the selected one is injected into the system "
                "prompt on every request. Format: \"# Title\" → "
                "description → \"use_when: when to use\" (optional)")
            if kind == "agents" else
            self.tr(
                "Skills: only the list of id+description+use_when "
                "appears in the prompt; the model reads the body via "
                "qgis_pyeval's open() when needed. Format: \"# Title\" "
                "→ description → \"use_when: when to use\" "
                "(optional)"))
        self._rebuild_combo(select)
        self._pick(self.cmb.currentIndex())

    def _rebuild_combo(self, select=None):
        """self._items でコンボを再構築しselect(省略時は現在値)を維持。"""
        cur = self.cmb.currentData() if select is None else select
        self.cmb.blockSignals(True)
        self.cmb.clear()
        self.cmb.addItem(
            self.tr("+ New {0}").format(self._kind_label()), "")
        for a in self._items.values():
            label = a["title"] + (self.tr(" (bundled)")
                                  if a["builtin"] else "")
            self.cmb.addItem(label, a["id"])
        i = self.cmb.findData(cur) if cur else -1
        self.cmb.setCurrentIndex(i if i > 0 else 0)
        self.cmb.blockSignals(False)

    def _pick(self, _idx):
        a = self._items.get(self.cmb.currentData() or "")
        if a is None:
            self.ed_name.setText("")
            self.ed_body.setPlainText("")
            self._loaded_body = ""
            return
        self.ed_name.setText(a["id"])
        try:
            with open(a["path"], "r", encoding="utf-8") as f:
                body = f.read()
        except Exception:
            body = ""
        self.ed_body.setPlainText(body)
        self._loaded_body = body

    def refresh_external(self):
        """AIの ai_* ツール等で指示書ファイルが変わった時の追従。

        一覧を再構築して選択を維持し、選択中ファイルの本文が外部で
        更新されていれば編集欄へ反映する。未保存の手編集がある間は
        上書きしない。新規作成中に同名ファイルが現れたらそれを
        選択状態にする。
        """
        kind = self._kind()
        self._items = {a["id"]: a for a in
                       ai_client.list_instruction_files(kind)}
        aid = self.cmb.currentData() or ""
        if not aid:
            stem = re.sub(r'[\\/:*?"<>|\s]+', "_",
                          self.ed_name.text().strip())
            if stem in self._items:
                aid = stem
        self._rebuild_combo(aid or None)
        a = self._items.get(self.cmb.currentData() or "")
        if a is None:
            return
        try:
            with open(a["path"], "r", encoding="utf-8") as f:
                body = f.read()
        except Exception:
            return
        if (body != self._loaded_body
                and self.ed_body.toPlainText() == self._loaded_body):
            self.ed_name.setText(a["id"])
            self.ed_body.setPlainText(body)
            self._loaded_body = body

    def _ask_ai(self):
        """「AIに修正を依頼」: 編集欄の本文と指示をチャットのAIへ送る。"""
        prompt = self.ed_prompt.toPlainText().strip()
        if not prompt:
            return
        panel = self.parent()
        if panel is None:
            return
        kind = self._kind()
        name = (self.ed_name.text().strip()
                or self.cmb.currentData() or "")
        body = self.ed_body.toPlainText().strip()
        msg = (f"Please revise the {self._kind_label()} instruction "
               f"'{name or 'new'}'.\n\n"
               f"## Revision instructions\n{prompt}\n\n"
               f"## Current body\n{body or '(empty)'}\n\n")
        if name:
            msg += (f"Save the full revised text with "
                    f"ai_save_instruction "
                    f"(kind='{kind}', name='{name}').")
        else:
            msg += ("Give it a suitable name and save as new with "
                    f"ai_save_instruction (kind='{kind}').")
        if panel._send_prompt(msg):
            self.ed_prompt.clear()

    def _save(self):
        try:
            p = ai_client.save_instruction(
                self._kind(), self.ed_name.text(),
                self.ed_body.toPlainText())
        except Exception as e:
            QMessageBox.warning(self, self.tr("Save failed"), str(e))
            return False
        stem = os.path.splitext(os.path.basename(p))[0]
        self.reload(stem)
        return True

    def _delete(self):
        aid = self.cmb.currentData() or ""
        if not aid:
            return
        a = self._items.get(aid)
        if a and a["builtin"]:
            QMessageBox.information(
                self, self.tr("Cannot delete"),
                self.tr("Instructions bundled with the plugin "
                        "cannot be deleted"))
            return
        if QMessageBox.question(
                self, self.tr("Delete"),
                self.tr("Delete {0} '{1}'?")
                .format(self._kind_label(), aid)
        ) != QMessageBox.StandardButton.Yes:
            return
        ai_client.delete_instruction(self._kind(), aid)
        self.reload()

    def _open_dir(self):
        d = (ai_client.agents_dir() if self._kind() == "agents"
             else ai_client.skills_dir())
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))


def _tabify_with_sibling(iface, panel):
    """同じドック領域に表示中のドックがあれば分割せずタブ化する。

    AIアシスタントを開いた時にレイヤパネル等の既存ドックと
    縦に分かれるのではなく、タブで重なるようにする。
    """
    from qgis.PyQt.QtWidgets import QDockWidget
    mw = iface.mainWindow()
    area = mw.dockWidgetArea(panel)
    for d in mw.findChildren(QDockWidget):
        if (d is not panel and d.isVisible()
                and mw.dockWidgetArea(d) == area):
            mw.tabifyDockWidget(d, panel)
            return


def show_panel(iface, get_driver, panel):
    """ドックを(必要なら生成して)表示し、インスタンスを返す。"""
    if panel is None:
        panel = AiPanel(iface, get_driver)
        iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, panel)
        _tabify_with_sibling(iface, panel)
    panel.show()
    panel.raise_()
    return panel
