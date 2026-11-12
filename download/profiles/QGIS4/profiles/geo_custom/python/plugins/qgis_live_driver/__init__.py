import json
import os
import tempfile
import time
import traceback

try:
    from qgis.PyQt.QtCore import QCoreApplication
except ImportError:
    # QGISの外(unit test等)でimportされる場合はNoneになる。
    # GUIコードパスはQGIS内でしか走らないため問題ない。
    QCoreApplication = None

from .i18n_json import install_translator


def _log(msg):
    log = os.environ.get(
        "WEBENGINE_LOG_PATH",
        os.path.join(tempfile.gettempdir(), "plugin_load.log"),
    )
    try:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")
    except Exception:  # nosec B110  # 設計上の許容
        pass


def _http_allowed():
    """QGIS_LIVE_TOOLS から公開コマンド種別の集合を読む(None=全許可)。"""
    raw = os.environ.get("QGIS_LIVE_TOOLS", "").strip()
    if raw and raw != "*":
        return {t.strip().lower().removeprefix("qgis_")
                for t in raw.split(",") if t.strip()}
    return None


def _registry_dir():
    # spawnされる側(MCPクライアントのshim等)が環境変数を持たないため、
    # 検出情報は固定パス ~/.qgis-live/ に書き出す
    return os.environ.get(
        "QGIS_LIVE_REGISTRY",
        os.path.join(os.path.expanduser("~"), ".qgis-live"),
    )


def _restrict_file(path):
    """トークン等を含むファイルをユーザ限定ACLにする(best-effort)。"""
    try:
        if os.name == "nt":
            import shutil
            import subprocess  # nosec B404  # icacls実行に必要
            user = os.environ.get("USERNAME") or ""
            exe = shutil.which("icacls") or os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"),
                "System32", "icacls.exe")
            if user:
                subprocess.run(  # nosec B603  # 引数は固定+USERNAMEのみ
                    [exe, path, "/inheritance:r",
                     "/grant:r", f"{user}:F"],
                    capture_output=True, timeout=10)
        else:
            os.chmod(path, 0o600)
    except Exception:  # nosec B110  # 設計上の許容
        pass


class QgisLivePlugin:
    """UIを持たない制御専用プラグイン。

    有効化は2経路(どちらも localhost 限定・トークン必須):
      - WEBENGINE_LIVE_DIR env 設定 → 起動時に即時有効(開発用途)
      - メニューのトグル → QSettingsに保存され次回起動から自動有効

    公開面:
      - ファイルJSONL (commands.jsonl/results.jsonl) — 言語非依存の基底
      - HTTP 127.0.0.1:<auto port> (/mcp = MCP Streamable HTTP, /api/* = REST)
      - ~/.qgis-live/<pid>-qgis_live_driver.json — 接続情報+トークン(自動検出用)
    """

    SETTING_ENABLED = "qgis_live_driver/enabled"
    SETTING_AI_PANEL = "qgis_live_driver/ai_panel_open"
    _MENU_NAME = "QGIS Live Driver"
    # メニューアクションのソース文字列(英語)。表示時は翻訳される
    _ACTION_SOURCES = ("Remote Control (localhost only)",
                       "AI Assistant",
                       "Connection Info",
                       "Hot Reload",
                       "Hot Reload (auto-apply on save)",
                       "Deploy Mode")

    def _own_action_texts(self):
        """残存アクション除去用。英語ソースと翻訳後テキストの両方を含める。"""
        texts = set(self._ACTION_SOURCES)
        for src in self._ACTION_SOURCES:
            texts.add(QCoreApplication.translate("qgis_live_driver", src))
        return texts

    def __init__(self, iface):
        self.iface = iface
        self.driver = None
        self._http = None
        self._reg_path = None
        self._action = None
        self._ai_action = None
        self._ai_panel = None
        self._ai_driver = None
        self._hot_menu = None
        self._mode_action = None
        self._conn_action = None
        self._conn_dlg = None
        self._geo_tb = None
        self._mode_badge = None
        self._mode_badge_action = None
        self._mode_badge_sep = None
        self._ai_tb_button = None
        self._ai_tb_action = None
        self._mode_timer = None
        self._init_language()
        try:
            from .bridge import QgisLiveBridge
            self.bridge = QgisLiveBridge(self)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        # プラグイン横断のレイヤ整理サービス。geo_import等は
        # plugins['qgis_live_driver'].layer_org.place_all([(layer, ctx)])
        # で追加レイヤをプロファイルのルールへ配置できる(無ければflat)
        try:
            from .layer_org import LayerOrganizer
            self.layer_org = LayerOrganizer()
        except Exception:
            self.layer_org = None

    def _init_language(self):
        """QGISの言語設定に合わせて i18n/<lang>.json を載せる。
        ソース文字列は英語。en または未対応言語では翻訳を載せない。"""
        try:
            self.translator = install_translator(
                os.path.dirname(os.path.abspath(__file__)))
        except Exception:
            self.translator = None

    def _own_menu(self):
        """プラグイン > QGIS Live Driver サブメニューを返す(無ければNone)。"""
        try:
            for top in self.iface.mainWindow().menuBar().actions():
                tm = top.menu()
                if tm is None:
                    continue
                for a in tm.actions():
                    sm = a.menu()
                    if sm is not None and sm.title() == self._MENU_NAME:
                        return sm
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return None

    def _sweep_menu_actions(self):
        """同名テキストの残存アクションをメニューから除去する。

        過去世代のプラグインがunloadで除去し損ねたQAction(リロードで
        孤立したもの)を掃除する。initGuiで新規追加の前に呼ぶ。
        """
        menu = self._own_menu()
        if menu is None:
            return
        for a in list(menu.actions()):
            if a.text() in self._own_action_texts():
                try:
                    menu.removeAction(a)
                    a.deleteLater()
                except Exception:  # nosec B110  # 設計上の許容
                    pass

    def initGui(self):
        from qgis.PyQt.QtWidgets import QAction
        self._sweep_menu_actions()  # 前世代の孤立アクション除去
        self._ai_action = QAction(
            QCoreApplication.translate("qgis_live_driver", "AI Assistant"),
            self.iface.mainWindow())
        self._ai_action.triggered.connect(self._open_ai_panel)
        self.iface.addPluginToMenu("QGIS Live Driver", self._ai_action)

        self._action = QAction(
            QCoreApplication.translate(
                "qgis_live_driver", "Remote Control (localhost only)"),
            self.iface.mainWindow())
        self._action.setCheckable(True)
        self._action.toggled.connect(self._on_toggle)
        self.iface.addPluginToMenu("QGIS Live Driver", self._action)

        self._conn_action = QAction(
            QCoreApplication.translate(
                "qgis_live_driver", "Connection Info"),
            self.iface.mainWindow())
        self._conn_action.triggered.connect(self._open_conn_info)
        self.iface.addPluginToMenu("QGIS Live Driver", self._conn_action)

        self._hot_menu = self._build_hot_menu()
        self.iface.addPluginToMenu("QGIS Live Driver",
                                   self._hot_menu.menuAction())

        # Deploy Modeダイアログはharness repoの指定経路でもあるため
        # repo未解決(単体install)でも常に出す
        self._mode_action = QAction(
            QCoreApplication.translate("qgis_live_driver", "Deploy Mode"),
            self.iface.mainWindow())
        self._mode_action.triggered.connect(self._open_mode_dialog)
        self.iface.addPluginToMenu("QGIS Live Driver", self._mode_action)
        self._init_geo_toolbar()

        live_base = os.environ.get("WEBENGINE_LIVE_DIR")
        _log(f"qgis_live_driver initGui: live_base={live_base!r}")
        if live_base:
            self._start(live_base)  # dev経路: env優先で即起動
        elif self._settings_enabled():
            self._start(self._default_live_base())
        self._sync_action()
        # 前回開いていたAIパネルはリロード/再起動後も開き直す
        if self._settings_enabled(self.SETTING_AI_PANEL):
            self._open_ai_panel()

    # ---- ホットリロード ----

    def _build_hot_menu(self):
        from qgis.PyQt.QtWidgets import QMenu
        menu = QMenu(
            QCoreApplication.translate("qgis_live_driver", "Hot Reload"),
            self.iface.mainWindow())
        menu.aboutToShow.connect(self._rebuild_hot_menu)
        return menu

    def _rebuild_hot_menu(self):
        """開くたびに開発対象プラグインの一覧を作り直す。"""
        if self._hot_menu is None:
            return
        self._hot_menu.clear()
        ids = self._dev_plugin_ids()
        for pid in ids:
            act = self._hot_menu.addAction(pid)
            act.triggered.connect(
                lambda _checked=False, p=pid: self._hot_reload([p]))
        if ids:
            self._hot_menu.addSeparator()
            act = self._hot_menu.addAction(
                QCoreApplication.translate(
                    "qgis_live_driver", "Reload All"))
            act.triggered.connect(
                lambda _checked=False: self._hot_reload(ids))
        else:
            act = self._hot_menu.addAction(
                QCoreApplication.translate(
                    "qgis_live_driver",
                    "(no development plugins)"))
            act.setEnabled(False)

    def _dev_plugin_ids(self):
        try:
            from .hot_reload import dev_plugin_ids
            return dev_plugin_ids(__file__)
        except Exception:
            _log("hot reload id discovery failed:\n"
                 + traceback.format_exc())
            return []

    def _hot_reload(self, ids):
        try:
            from .hot_reload import reload_plugins
            reload_plugins(ids, notify=self._hot_notify)
        except Exception:
            _log("hot reload failed:\n" + traceback.format_exc())

    def _hot_notify(self, level, msg):
        try:
            from qgis.core import Qgis
            lv = (Qgis.MessageLevel.Warning if level == "warn"
                  else Qgis.MessageLevel.Info)
            self.iface.messageBar().pushMessage(
                "QGIS Live Driver", msg, level=lv, duration=4)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        _log(f"hot_reload {level}: {msg}")

    # ---- 接続情報 ----

    def _open_conn_info(self):
        """接続情報ダイアログを開く(開いていれば開き直して最新化)。"""
        try:
            if self._conn_dlg is not None:
                try:
                    self._conn_dlg.close()
                    self._conn_dlg.deleteLater()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            from .connection_info import show_dialog
            self._conn_dlg = show_dialog(self)
        except Exception:
            _log("connection info dialog failed:\n"
                 + traceback.format_exc())

    # ---- deployモード切替 ----

    def _open_mode_dialog(self):
        try:
            from .mode_switch import show_dialog
            show_dialog(self.iface, __file__, notify=self._hot_notify)
        except Exception:
            _log("deploy mode dialog failed:\n" + traceback.format_exc())
        self._refresh_mode_badge()

    # ---- GeoSuite共有ツールバー ----

    def _init_geo_toolbar(self):
        """GeoSuiteツールバーをfind-or-createし、先頭にモードバッジを載せる。

        バッジは「開発モード/利用モード」の常時表示で、クリックすると
        Deploy Modeダイアログを開く。他プラグインのツールバー項目は
        同名ツールバーへ各プラグインが自分で追加する。
        """
        try:
            from qgis.PyQt.QtCore import QTimer
            from qgis.PyQt.QtGui import QIcon
            from qgis.PyQt.QtWidgets import QToolButton
            from .geo_toolbar import geo_suite_toolbar
            self._geo_tb = geo_suite_toolbar(self.iface)
            # ドライバ稼働中は常時表示を強制(表示/非表示メニューからも
            # 外せないようtoggleViewActionを無効化。unloadで復帰する)
            try:
                tva = self._geo_tb.toggleViewAction()
                if tva is not None:
                    tva.setEnabled(False)
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._geo_tb.setVisible(True)
            self._mode_badge = QToolButton(self._geo_tb)
            self._mode_badge.setAutoRaise(True)
            self._mode_badge.clicked.connect(self._open_mode_dialog)
            # 既存項目があれば先頭へ挿入(リロード順に関わらず常に先頭)
            acts = self._geo_tb.actions()
            if acts:
                self._mode_badge_action = self._geo_tb.insertWidget(
                    acts[0], self._mode_badge)
            else:
                self._mode_badge_action = self._geo_tb.addWidget(
                    self._mode_badge)
            # バッジとプラグイン項目の間に区切りを入れる
            after = self._geo_tb.actions()
            if len(after) > 1:
                self._mode_badge_sep = self._geo_tb.insertSeparator(
                    after[1])
            else:
                self._mode_badge_sep = None
            # AIアシスタント起動ボタン(バッジ右隣。ツールバーへの
            # AIエントリ点がないため最低限チャット起動は常駐させる)
            self._ai_tb_button = QToolButton(self._geo_tb)
            self._ai_tb_button.setAutoRaise(True)
            self._ai_tb_button.setToolTip(
                QCoreApplication.translate(
                    "qgis_live_driver", "AI Assistant"))
            ai_icon = QIcon(os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "icon_ai.png"))
            if ai_icon.isNull():
                self._ai_tb_button.setText("AI")
            else:
                self._ai_tb_button.setIcon(ai_icon)
            self._ai_tb_button.clicked.connect(self._open_ai_panel)
            after = self._geo_tb.actions()
            if len(after) > 2:
                self._ai_tb_action = self._geo_tb.insertWidget(
                    after[2], self._ai_tb_button)
            else:
                self._ai_tb_action = self._geo_tb.addWidget(
                    self._ai_tb_button)
            self._refresh_mode_badge()
            self._mode_timer = QTimer(self.iface.mainWindow())
            self._mode_timer.setInterval(5000)
            self._mode_timer.timeout.connect(self._refresh_mode_badge)
            self._mode_timer.start()
        except Exception:
            _log("GeoSuite toolbar init failed:\n" + traceback.format_exc())

    def _refresh_mode_badge(self):
        if self._mode_badge is None:
            return
        try:
            if self._geo_tb is not None and not self._geo_tb.isVisible():
                # 常時表示の強制(何らかの経路で隠された場合に戻す)
                self._geo_tb.setVisible(True)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        try:
            from .mode_switch import deploy_state
            st = deploy_state(__file__)
            tr = QCoreApplication.translate
            label = {
                "dev": tr("qgis_live_driver", "Development mode"),
                "use": tr("qgis_live_driver", "Usage mode"),
                "mixed": tr("qgis_live_driver", "Mixed"),
                "none": tr("qgis_live_driver", "Not deployed"),
            }.get(st["mode"], st["mode"] or "")
            from qgis.PyQt.QtGui import QIcon
            self._mode_badge.setToolTip(
                "{0} — {1}".format(
                    label, tr("qgis_live_driver", "Deploy Mode")))
            if st["mode"] == "use":
                # 利用モードは邪魔にならないよう歯車アイコンのみ
                self._mode_badge.setText("")
                self._mode_badge.setStyleSheet("")
                icon = QIcon()
                try:
                    from qgis.core import QgsApplication
                    icon = QgsApplication.getThemeIcon(
                        "/mActionOptions.svg")
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                if icon.isNull():
                    self._mode_badge.setText("⚙")
                else:
                    self._mode_badge.setIcon(icon)
                return
            self._mode_badge.setIcon(QIcon())
            self._mode_badge.setText(label)
            # devは赤背景で注意喚起、それ以外は既定
            style = {
                "dev": ("QToolButton { font-weight: bold; color: white; "
                        "background: #c0392b; border-radius: 3px; "
                        "padding: 1px 6px; }"),
            }.get(st["mode"], "")
            self._mode_badge.setStyleSheet(style)
        except Exception:  # nosec B110  # 設計上の許容
            pass

    # ---- AIアシスタントパネル ----

    def _open_ai_panel(self):
        from .ai_panel import show_panel
        new = self._ai_panel is None
        self._ai_panel = show_panel(
            self.iface, self._panel_driver, self._ai_panel)
        # 表示状態を永続化(ホットリロード/QGIS再起動で開き直すため)
        self._set_setting(True, self.SETTING_AI_PANEL)
        if new:
            try:
                self._ai_panel.visibilityChanged.connect(
                    lambda vis:
                    self._set_setting(bool(vis), self.SETTING_AI_PANEL))
            except Exception:  # nosec B110  # 設計上の許容
                pass

    def _panel_driver(self):
        """AIパネルのツール実行に使うLiveDriverを返す。

        リモート制御が有効なら既存ドライバを共有し、無効時はパネル専用の
        内部ドライバを作る。内部ドライバはレジストリ・HTTP公開面を持たず
        (tempdirのlive dirのみ)外部からは発見できない。
        生成はQTimerを含むため必ずGUIスレッドで行う。
        """
        if self.driver is not None:
            return self.driver
        if self._ai_driver is None:
            from .live_driver import LiveDriver
            live_dir = os.path.join(
                tempfile.gettempdir(), f"qgis-live-ai-{os.getpid()}")
            self._ai_driver = LiveDriver(live_dir, iface=self.iface)
        return self._ai_driver

    # ---- 有効化/無効化 ----

    def _default_live_base(self):
        # env未指定の配布利用ではレジストリ配下のユーザ専用dirを使う
        return os.path.join(_registry_dir(), "run")

    def _settings_enabled(self, key=SETTING_ENABLED):
        try:
            from qgis.PyQt.QtCore import QSettings
            return str(QSettings().value(
                key, "false")).lower() in ("1", "true")
        except Exception:
            return False

    def _set_setting(self, on, key=SETTING_ENABLED):
        try:
            from qgis.PyQt.QtCore import QSettings
            QSettings().setValue(key, bool(on))
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _sync_action(self):
        if self._action is not None:
            self._action.blockSignals(True)
            self._action.setChecked(self.driver is not None)
            self._action.blockSignals(False)

    def _on_toggle(self, checked):
        if checked and self.driver is None:
            from qgis.PyQt.QtWidgets import QMessageBox
            ret = QMessageBox.warning(
                self.iface.mainWindow(), "QGIS Live Driver",
                QCoreApplication.translate(
                    "qgis_live_driver",
                    "Local (localhost) clients will be able to remotely "
                    "control this QGIS process.\n"
                    "pyeval executes arbitrary Python inside QGIS.\n\n"
                    "Access is protected by a per-session token stored "
                    "only in a user-private file, but only trusted "
                    "processes should run under your account.\n\n"
                    "Enable it?"),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                self._sync_action()
                return
            self._set_setting(True)
            self._start(self._default_live_base())
            if self.driver is None:
                self._set_setting(False)
            else:
                # 初回利用者が「次に繋ぐ方法」を迷わないよう
                # 接続情報ダイアログを開く(メニューからも開ける)
                self._open_conn_info()
        elif not checked and self.driver is not None:
            self._set_setting(False)
            self._stop()
        self._sync_action()

    def _start(self, live_base):
        live_dir = os.path.join(
            live_base, f"qgis-{os.getpid()}", __package__)
        try:
            from .live_driver import LiveDriver
            self.driver = LiveDriver(live_dir, iface=self.iface)
            _log(f"qgis_live_driver LiveDriver active: {live_dir}")
        except Exception:
            _log("qgis_live_driver LiveDriver failed:\n"
                 + traceback.format_exc())
            return

        # 認証: セッショントークン必須。QGIS_LIVE_API_KEYは追加キーとして任意
        api_keys = {self.driver.token}
        env_key = os.environ.get("QGIS_LIVE_API_KEY") or None
        if env_key:
            api_keys.add(env_key)
        port = None
        try:
            from .mcp_http import start_http
            self._http, port = start_http(
                self.driver, api_keys=api_keys,
                allowed=_http_allowed())
            self.driver.http_port = port
            _log(f"qgis_live_driver HTTP API: http://127.0.0.1:{port}/ "
                 f"tools={sorted(_http_allowed()) if _http_allowed() else 'all'}")
        except Exception:
            _log("qgis_live_driver HTTP failed:\n"
                 + traceback.format_exc())

        try:
            reg_dir = _registry_dir()
            os.makedirs(reg_dir, exist_ok=True)
            self._reg_path = os.path.join(
                reg_dir, f"{os.getpid()}-{__package__}.json")
            with open(self._reg_path, "w", encoding="utf-8") as f:
                json.dump({
                    "pid": os.getpid(),
                    "plugin_id": __package__,
                    "live_dir": live_dir,
                    "http_port": port,
                    "mcp_url": (f"http://127.0.0.1:{port}/mcp"
                                if port else None),
                    "token": self.driver.token,
                    "http_tools": (sorted(_http_allowed())
                                   if _http_allowed() else "all"),
                    "started": time.time(),
                }, f)
            # トークンを含むためユーザ限定にする
            _restrict_file(self._reg_path)
            _restrict_file(os.path.join(live_dir, "token"))
        except Exception:
            _log("qgis_live_driver registry write failed:\n"
                 + traceback.format_exc())

    def _stop(self):
        if self._http is not None:
            try:
                self._http.shutdown()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._http = None
        if self.driver is not None:
            try:
                self.driver.stop()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self.driver = None
        if self._reg_path is not None:
            try:
                os.remove(self._reg_path)
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._reg_path = None

    def unload(self):
        # unload中の例外はQGIS側で握り潰されつつ処理が続行され、
        # 除去前のアクションがメニューに孤立するため、全て個別に握り潰す
        if self._ai_panel is not None:
            try:
                # closeで発火するvisibilityChangedが設定をFalseへ
                # 上書きしないよう先に切ってから表示状態を保存する
                self._ai_panel.visibilityChanged.disconnect()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            try:
                self._set_setting(bool(self._ai_panel.isVisible()),
                                  self.SETTING_AI_PANEL)
            except Exception:  # nosec B110  # 設計上の許容
                pass
            try:
                self._ai_panel.close()
                self._ai_panel.deleteLater()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._ai_panel = None
        if self._ai_driver is not None:
            try:
                self._ai_driver.stop()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._ai_driver = None
        if self._hot_menu is not None:
            try:
                self.iface.removePluginMenu(
                    "QGIS Live Driver", self._hot_menu.menuAction())
                self._hot_menu.deleteLater()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._hot_menu = None
        if self._conn_dlg is not None:
            try:
                self._conn_dlg.close()
                self._conn_dlg.deleteLater()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._conn_dlg = None
        for action in (self._ai_action, self._action, self._conn_action,
                       self._mode_action):
            if action is not None:
                try:
                    self.iface.removePluginMenu("QGIS Live Driver",
                                                action)
                    action.deleteLater()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        self._ai_action = None
        self._action = None
        self._conn_action = None
        self._mode_action = None
        if self._mode_timer is not None:
            try:
                self._mode_timer.stop()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._mode_timer = None
        for a in (self._mode_badge_sep, self._mode_badge_action):
            if a is not None:
                try:
                    if self._geo_tb is not None:
                        self._geo_tb.removeAction(a)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        self._mode_badge_sep = None
        self._mode_badge_action = None
        if self._mode_badge is not None:
            try:
                self._mode_badge.deleteLater()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._mode_badge = None
        if self._ai_tb_action is not None:
            try:
                if self._geo_tb is not None:
                    self._geo_tb.removeAction(self._ai_tb_action)
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._ai_tb_action = None
        if self._ai_tb_button is not None:
            try:
                self._ai_tb_button.deleteLater()
            except Exception:  # nosec B110  # 設計上の許容
                pass
            self._ai_tb_button = None
        if self._geo_tb is not None:
            try:
                # 常時表示の強制を解除(他プラグインの項目は残る)
                tva = self._geo_tb.toggleViewAction()
                if tva is not None:
                    tva.setEnabled(True)
            except Exception:  # nosec B110  # 設計上の許容
                pass
        self._geo_tb = None
        self._sweep_menu_actions()  # 自身以外の残存も掃除
        try:
            self._stop()
        except Exception:  # nosec B110  # 設計上の許容
            pass


def classFactory(iface):
    return QgisLivePlugin(iface)
