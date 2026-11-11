# -*- coding: utf-8 -*-
"""geo_import を AI/外部制御から利用するためのブリッジ。

plugin.bridge 属性にこのオブジェクトをぶら下げると、qgis_live_driver の
bridge_call コマンド(ファイルJSONL / REST /api/cmd / MCP qgis_bridge_call)
から ``qgis.utils.plugins['geo_import'].bridge.<method>(*args)`` が
プロセス内で直接呼ばれる。

各メソッドは JSON 文字列を返す(bridge_call 側で構造化される)。
ドメインエラー(ダイアログ未オープン・インデックス不明等)は
``{"ok": false, "error": ...}`` を返し、予期しない例外は呼び出し元
(driver の {"error": traceback})に委ねる。いずれも GUI スレッドで
同期的に実行される。

注意: plugin.run() の本来経路は dlg.exec() でmodal表示するが、
bridge の openDialog() は show() の非modalで開く(呼出が即応答するため)。
また search() の取得は内部QThreadで非同期実行されるため、
search() は開始だけを返し、結果は results() で取得する。
警告系のmodal QMessageBox は util.dlg_warning/dlg_information 経由で
出るため、loadSelected() 中は自動Ok応答に差し替えてメッセージを収集する。

例(MCP): qgis_bridge_call pluginId="geo_import" method="search" args=["地盤"]
"""

import inspect
import json

from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtWidgets import QMessageBox

_CHECKED = Qt.CheckState.Checked
_UNCHECKED = Qt.CheckState.Unchecked
_USER_ROLE = Qt.ItemDataRole.UserRole


class _DialogAutoReply:
    """実行中だけ QMessageBox の modal メソッドを自動Ok応答に差し替える。"""

    _NAMES = ("information", "question", "warning", "critical")

    def __init__(self):
        self.messages = []
        self._orig = {}

    def __enter__(self):
        def _ok(*a):
            self.messages.append(str(a[2]) if len(a) > 2 else "")
            return QMessageBox.StandardButton.Ok
        for name in self._NAMES:
            self._orig[name] = getattr(QMessageBox, name)
            setattr(QMessageBox, name, staticmethod(_ok))
        return self

    def __exit__(self, *exc):
        for name, fn in self._orig.items():
            setattr(QMessageBox, name, fn)
        return False


class GeoImportBridge:
    """``plugins['geo_import'].bridge`` にぶら下げるAI向けAPI。"""

    NAME = "データカタログ取込 (geo_import)"
    SUMMARY = ("データカタログ(CKAN等)を検索し、データセット内の"
               "リソース(ファイル/サービスURL)を選択してQGISへ読み込む。"
               "検索は非同期実行のため、search()後にresults()で結果を取得する。")
    WHEN_TO_USE = [
        "データカタログからデータセットを検索したい",
        "データセットのリソース(配信ファイル/URL)を確認したい",
        "リソースを選んでQGISへレイヤとして読み込みたい",
        "カタログ接続設定(CKAN URL/キャッシュ)を確認したい",
    ]
    METHOD_DOCS = {
        "openDialog": {
            "description":
                "カタログブラウザダイアログを非modalで開く(既に開いていれば前面化)。",
            "example": {"method": "openDialog", "args": []},
        },
        "closeDialog": {
            "description": "カタログブラウザダイアログを閉じる。",
            "example": {"method": "closeDialog", "args": []},
        },
        "openSettings": {
            "description":
                "設定ダイアログを開く(modal。呼出はダイアログを閉じるまで戻らない)。",
            "example": {"method": "openSettings", "args": []},
        },
        "search": {
            "description":
                "データセットを検索する。結果は results() で取得。"
                "text省略時は全件。ネットワークモードではHTTP応答まで"
                "呼出が戻らない(警告modalは自動応答で吸収しmessagesに返す)。",
            "example": {"method": "search", "args": ["地盤"]},
        },
        "results": {
            "description":
                "現在の検索結果一覧(index/title/パッケージid/選択中)と"
                "ページ情報・検索中フラグを返す。",
            "example": {"method": "results", "args": []},
        },
        "selectResult": {
            "description":
                "結果リストのデータセットを選択する(index)。"
                "選択するとリソース一覧(IDC_listRessources)が更新される。",
            "example": {"method": "selectResult", "args": [0]},
        },
        "resources": {
            "description":
                "選択データセットのリソース一覧(index/format/name/url/"
                "checked)を返す。",
            "example": {"method": "resources", "args": []},
        },
        "checkResources": {
            "description":
                "リソースのチェック状態を設定する。'all'/'none'または"
                "index配列(指定indexのみチェック)。",
            "example": {"method": "checkResources", "args": ["all"]},
        },
        "loadSelected": {
            "description":
                "チェック済みリソースをQGISへ読み込む(追加ボタン押下相当)。"
                "警告ダイアログは自動Ok応答しメッセージとして返す。"
                "追加レイヤは qgis_live_driver のレイヤ整理プロファイルが"
                "有効ならルールでグループ配置され、結果はorganizedに返る。",
            "example": {"method": "loadSelected", "args": []},
        },
        "status": {
            "description":
                "ダイアログ開閉・検索中・件数・接続設定(ckan_url/cache_dir)"
                "の状態を返す。",
            "example": {"method": "status", "args": []},
        },
        "nextPage": {
            "description":
                "検索結果の次ページへ移動する(>ボタン押下相当)。",
            "example": {"method": "nextPage", "args": []},
        },
        "prevPage": {
            "description":
                "検索結果の前ページへ移動する(<ボタン押下相当)。",
            "example": {"method": "prevPage", "args": []},
        },
        "gotoPage": {
            "description":
                "検索結果の指定ページへ移動する(1..page_count)。",
            "example": {"method": "gotoPage", "args": [2]},
        },
        "listGroups": {
            "description":
                "カテゴリ(グループ)一覧(index/title/name/checked)を返す。"
                "チェックしたカテゴリのみ検索対象になる。",
            "example": {"method": "listGroups", "args": []},
        },
        "checkGroups": {
            "description":
                "カテゴリのチェックを設定し再検索する。'all'/'none'または"
                "index配列/名前配列。全チェックまたは全未チェックは全件検索と同義。",
            "example": {"method": "checkGroups", "args": [["structures"]]},
        },
        "formatFilter": {
            "description":
                "データ形式フィルタ(IDC_comboFormat)を取得/設定する。"
                "formatsに選択肢一覧も返す。'All'でフィルタ無し。",
            "example": {"method": "formatFilter", "args": ["GeoJSON"]},
        },
        "localCache": {
            "description":
                "ローカルキャッシュ利用チェック(IDC_chkLocalCache)を"
                "取得/設定する。選択中リモートサーバー全てに適用。"
                "有効化時にキャッシュ無ければ再取得が走る(数秒ブロック)。",
            "example": {"method": "localCache", "args": [True]},
        },
        "refreshCache": {
            "description":
                "選択中サーバーのSQLiteキャッシュを再作成する"
                "(再取得ボタン押下相当。長時間ブロックする場合あり)。",
            "example": {"method": "refreshCache", "args": []},
        },
        "selectResults": {
            "description":
                "結果リストの複数データセットを選択する(index配列)。"
                "複数選択時はリソース一覧がマージ表示される。",
            "example": {"method": "selectResults", "args": [[0, 2]]},
        },
        "datasetDetails": {
            "description":
                "選択データセットの詳細(package辞書: notes/organization/"
                "author/license等。index省略時は現在選択)を返す。",
            "example": {"method": "datasetDetails", "args": []},
        },
        "link": {
            "description":
                "リンク表示欄(IDC_plainTextLink)の内容を返す。"
                "copy=True でクリップボードへコピーする。",
            "example": {"method": "link", "args": [True]},
        },
        "openProviders": {
            "description":
                "データプロバイダ選択ダイアログを開く(modalのため非同期起動)。"
                "サーバー選択は selectServers でも直接行える。",
            "example": {"method": "openProviders", "args": []},
        },
        "listServers": {
            "description":
                "カタログサーバー設定(選択中/カスタム/ローカルキャッシュ対象/"
                "接続エラー)を返す。",
            "example": {"method": "listServers", "args": []},
        },
        "selectServers": {
            "description":
                "検索対象サーバーを選択する。名称('|'区切り)または配列。"
                "公式サーバー名またはカスタムサーバー名が指定可。"
                "適用後にダイアログを再読込する。",
            "example": {"method": "selectServers", "args": [["地盤情報"]]},
        },
        "addServer": {
            "description":
                "カスタムサーバーを追加する。urlはCKAN API URLか"
                "ローカルフォルダパス。追加後に選択状態へ反映する。",
            "example": {"method": "addServer",
                        "args": ["mycat", "https://example.com/api/3/"]},
        },
        "removeServer": {
            "description":
                "カスタムサーバーを削除する(公式サーバーは削除不可)。",
            "example": {"method": "removeServer", "args": ["mycat"]},
        },
        "testServer": {
            "description":
                "サーバーURLの接続テストを行う(同期HTTP/フォルダ確認。"
                "数秒ブロック)。ローカルフォルダは存在確認のみ。",
            "example": {"method": "testServer",
                        "args": ["https://example.com/api/3/"]},
        },
        "reload": {
            "description":
                "ダイアログを再読込する(window_loaded相当。"
                "サーバー・カテゴリ・形式一覧を再取得し全件検索)。",
            "example": {"method": "reload", "args": []},
        },
        "openDisclaimer": {
            "description": "免責事項ダイアログを開く。",
            "example": {"method": "openDisclaimer", "args": []},
        },
        "getSettings": {
            "description":
                "設定(ckan_url/cache_dir/results_limit/use_local_cache_all/"
                "local_cache_sites/selected_ckan_servers/custom_servers/"
                "debug/authcfg等)を返す。",
            "example": {"method": "getSettings", "args": []},
        },
        "setSettings": {
            "description":
                "設定を変更して保存する。対応キー: ckan_url/cache_dir/"
                "results_limit/use_local_cache_all/local_cache_sites/"
                "debug/authcfg/auth_propagate/boxdrive_support/"
                "long_path_support。サーバー選択はselectServersを使う。",
            "example": {"method": "setSettings",
                        "args": [{"results_limit": 100}]},
        },
    }

    def __init__(self, plugin):
        self._plugin = plugin

    # ---------- 内部ヘルパ ----------

    @staticmethod
    def _ok(payload=None):
        obj = {"ok": True}
        if payload:
            obj.update(payload)
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def _err(msg):
        return json.dumps({"ok": False, "error": str(msg)},
                          ensure_ascii=False)

    def _dialog(self):
        return getattr(self._plugin, "dlg", None)

    def _require_dialog(self):
        dlg = self._dialog()
        if dlg is None:
            return None, self._err("dialog not open (call openDialog first)")
        return dlg, None

    @staticmethod
    def _res_item(item):
        res = item.data(_USER_ROLE) or {}
        return {
            "name": res.get("name"),
            "format": res.get("format"),
            "url": res.get("url"),
            "id": res.get("id"),
            "checked": item.checkState() == _CHECKED,
        }

    def _method_catalog(self):
        out = []
        for name in sorted(dir(self)):
            if name.startswith("_") or name == "pluginInfo":
                continue
            fn = getattr(self, name)
            if not callable(fn):
                continue
            doc = inspect.getdoc(fn) or ""
            entry = {
                "name": name,
                "signature": f"{name}{inspect.signature(fn)}",
                "description": doc.split("\n")[0] if doc else "",
            }
            extra = self.METHOD_DOCS.get(name) or {}
            if extra.get("description"):
                entry["description"] = extra["description"]
            if extra.get("example"):
                entry["example"] = extra["example"]
            out.append(entry)
        return out

    # ---------- bridge メソッド(JSON文字列を返す) ----------

    def pluginInfo(self):
        """プラグインの自己記述(id/summary/when_to_use/methods)を返す。"""
        return self._ok({
            "id": "geo_import",
            "name": self.NAME,
            "summary": self.SUMMARY,
            "when_to_use": list(self.WHEN_TO_USE),
            "invoke": {"type": "bridge_call", "plugin_id": "geo_import",
                       "method": "<method>", "args": []},
            "methods": self._method_catalog(),
            "state": {"dialog": self._dialog() is not None},
        })

    def status(self):
        """ダイアログ・検索状態・接続設定を返す。"""
        p = self._plugin
        dlg = self._dialog()
        st = p.settings
        searching = bool(getattr(dlg, "data_thread", None) is not None
                         and dlg.data_thread.isRunning()) if dlg else False
        try:
            cur_cache = bool(
                st.use_local_cache(getattr(st, "ckan_url", "") or ""))
        except Exception:
            cur_cache = None
        return self._ok({
            "dialog": dlg is not None,
            "dialogVisible": bool(dlg is not None and dlg.isVisible()),
            "searching": searching,
            "result_count": getattr(dlg, "result_count", None),
            "page": getattr(dlg, "current_page", None),
            "page_count": getattr(dlg, "page_count", None),
            "settings": {
                "ckan_url": getattr(st, "ckan_url", None),
                "ckan_urls": st.active_server_urls() if hasattr(st, "active_server_urls") else [getattr(st, "ckan_url", None)],
                "cache_dir": getattr(st, "cache_dir", None),
                "results_limit": getattr(st, "results_limit", None),
                "use_local_cache_all": getattr(st, "use_local_cache_all", None),
                "local_cache_sites": getattr(st, "local_cache_sites", None),
                "current_site_local_cache": cur_cache,
                "server_errors": getattr(st, "server_errors", {}) or {},
            },
        })

    def openDialog(self):
        """カタログブラウザを非modalで開く。"""
        p = self._plugin
        dlg = self._dialog()
        if dlg is not None:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return self._ok({"opened": True, "already": True})
        QSettings().setValue("geo_import/isopen", True)
        from .geo_import_dialog import GeoImportDialog
        dlg = GeoImportDialog(p.settings, p.iface, p.iface.mainWindow())
        p.dlg = dlg

        def _closed(*_a):
            QSettings().setValue("geo_import/isopen", False)
            p.dlg = None

        dlg.finished.connect(_closed)
        dlg.show()
        return self._ok({"opened": True, "already": False})

    def closeDialog(self):
        """カタログブラウザを閉じる。"""
        dlg = self._dialog()
        if dlg is not None:
            dlg.close()
        return self._ok({"closed": True})

    def openSettings(self):
        """設定ダイアログを開く(modal — 閉じるまで呼出は戻らない)。"""
        self._plugin.open_settings()
        return self._ok({"opened": True})

    def search(self, text=None):
        """データセット検索を開始する(非同期)。結果は results()。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        if text is None:
            dlg.IDC_lineSearch.setText("")
        else:
            dlg.IDC_lineSearch.setText(str(text))
        dlg.search_txt = "" if text is None else str(text)
        # ネットワークモードでは suchen() が同期HTTPでブロックする。
        # 失敗時のmodal警告が呼出を返さないよう自動応答で吸収する。
        with _DialogAutoReply() as cap:
            dlg.suchen()
        return self._ok({"started": True,
                         "query": "" if text is None else str(text),
                         "messages": cap.messages or None})

    def results(self):
        """現在の検索結果一覧とページ情報を返す。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        items = []
        lw = dlg.IDC_listResults
        sel_rows = {i.row() for i in lw.selectedIndexes()}
        for i in range(lw.count()):
            itm = lw.item(i)
            pkg = itm.data(_USER_ROLE) or {}
            items.append({
                "index": i,
                "title": itm.text(),
                "id": pkg.get("id"),
                "name": pkg.get("name"),
                "resources": len(pkg.get("resources", []) or []),
                "selected": i in sel_rows,
            })
        return self._ok({
            "result_count": getattr(dlg, "result_count", None),
            "page": getattr(dlg, "current_page", None),
            "page_count": getattr(dlg, "page_count", None),
            "items": items,
        })

    def selectResult(self, index):
        """結果リストのデータセットを選択する(リソース一覧が更新される)。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        lw = dlg.IDC_listResults
        if not isinstance(index, int) or isinstance(index, bool) \
                or not (0 <= index < lw.count()):
            return self._err(f"invalid index: {index} (0..{lw.count() - 1})")
        lw.setCurrentRow(index)
        return self._ok({"selected": index,
                         "resources": dlg.IDC_listRessources.count()})

    def resources(self):
        """選択データセットのリソース一覧を返す。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        lw = dlg.IDC_listRessources
        out = [dict(self._res_item(lw.item(i)), index=i)
               for i in range(lw.count())]
        return self._ok({"resources": out,
                         "checked": sum(1 for r in out if r["checked"])})

    def checkResources(self, selection="all"):
        """リソースのチェックを設定する。'all'/'none'またはindex配列。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        lw = dlg.IDC_listRessources
        if isinstance(selection, str) and selection == "all":
            dlg.select_all_resources()
        elif isinstance(selection, str) and selection == "none":
            for i in range(lw.count()):
                lw.item(i).setCheckState(_UNCHECKED)
        elif isinstance(selection, (list, tuple)):
            want = set(int(i) for i in selection)
            for i in range(lw.count()):
                lw.item(i).setCheckState(
                    _CHECKED if i in want else _UNCHECKED)
        else:
            return self._err("selection must be 'all'|'none'|[indices]")
        checked = sum(1 for i in range(lw.count())
                      if lw.item(i).checkState() == _CHECKED)
        return self._ok({"checked": checked, "total": lw.count()})

    def loadSelected(self):
        """チェック済みリソースをQGISへ読み込む。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        with _DialogAutoReply() as cap:
            dlg.load_resource_clicked()
        return self._ok({
            "messages": cap.messages,
            # qgis_live_driver の LayerOrganizer が有効なら、
            # 追加レイヤのグループ配置結果(無効/未適用ならNone)
            "organized": getattr(dlg, "last_org_report", None),
        })

    # ---------- ページング ----------

    def nextPage(self):
        """検索結果の次ページへ移動する。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        with _DialogAutoReply() as cap:
            dlg.next_page_clicked()
        return self._ok({"page": dlg.current_page,
                         "page_count": dlg.page_count,
                         "messages": cap.messages or None})

    def prevPage(self):
        """検索結果の前ページへ移動する。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        with _DialogAutoReply() as cap:
            dlg.previous_page_clicked()
        return self._ok({"page": dlg.current_page,
                         "page_count": dlg.page_count,
                         "messages": cap.messages or None})

    def gotoPage(self, page):
        """検索結果の指定ページへ移動する。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        try:
            page = int(page)
        except Exception:
            return self._err(f"invalid page: {page!r}")
        if page < 1 or (dlg.page_count and page > dlg.page_count):
            return self._err(
                f"page out of range: {page} (1..{dlg.page_count or '?'})")
        with _DialogAutoReply() as cap:
            dlg.current_page = page - 1
            dlg.next_page_clicked()  # current_page+1 → 指定ページ
        return self._ok({"page": dlg.current_page,
                         "page_count": dlg.page_count,
                         "messages": cap.messages or None})

    # ---------- カテゴリ / 形式フィルタ ----------

    def listGroups(self):
        """カテゴリ(グループ)一覧を返す。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        lw = dlg.IDC_listGroup
        out = []
        for i in range(lw.count()):
            it = lw.item(i)
            data = it.data(_USER_ROLE) or {}
            out.append({
                "index": i,
                "title": it.text(),
                "name": data.get("name"),
                "checked": it.checkState() == _CHECKED,
            })
        return self._ok({"groups": out,
                         "current_group": getattr(dlg, "current_group", None)})

    def checkGroups(self, selection="all"):
        """カテゴリのチェックを設定し再検索する。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        lw = dlg.IDC_listGroup
        if isinstance(selection, str) and selection == "all":
            want = set(range(lw.count()))
        elif isinstance(selection, str) and selection == "none":
            want = set()
        elif isinstance(selection, (list, tuple)):
            want = set()
            for s in selection:
                if isinstance(s, bool):
                    return self._err("invalid group selector")
                if isinstance(s, int):
                    if not (0 <= s < lw.count()):
                        return self._err(
                            f"group index out of range: {s} "
                            f"(0..{lw.count() - 1})")
                    want.add(s)
                else:
                    hit = None
                    for i in range(lw.count()):
                        it = lw.item(i)
                        data = it.data(_USER_ROLE) or {}
                        if str(s) in (data.get("name"), it.text()):
                            hit = i
                            break
                    if hit is None:
                        return self._err(f"group not found: {s!r}")
                    want.add(hit)
        else:
            return self._err(
                "selection must be 'all'|'none'|[indices|names]")
        # itemChanged発火を抑制してまとめて設定し、最後に1回だけ再検索
        lw.blockSignals(True)
        try:
            for i in range(lw.count()):
                lw.item(i).setCheckState(
                    _CHECKED if i in want else _UNCHECKED)
        finally:
            lw.blockSignals(False)
        with _DialogAutoReply() as cap:
            dlg.current_page = 1
            dlg._GeoImportDialog__search_package()
        checked = [lw.item(i).data(_USER_ROLE).get("name")
                   for i in range(lw.count())
                   if lw.item(i).checkState() == _CHECKED]
        return self._ok({"checked": checked,
                         "result_count": dlg.result_count,
                         "messages": cap.messages or None})

    def formatFilter(self, format=None):
        """データ形式フィルタを取得/設定する('All'でフィルタ無し)。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        cmb = getattr(dlg, "IDC_comboFormat", None)
        if cmb is None:
            return self._err("format combobox not available")
        if format is not None:
            cmb.setCurrentText(str(format))
            # リソース一覧へ再適用(現在選択を再評価)
            try:
                dlg.resultitemchanged(
                    dlg.IDC_listResults.currentItem(), None)
            except Exception:  # nosec B110  # 設計上の許容
                pass
        return self._ok({
            "format": cmb.currentText(),
            "formats": [cmb.itemText(i) for i in range(cmb.count())],
        })

    # ---------- ローカルキャッシュ ----------

    def localCache(self, enabled=None):
        """ローカルキャッシュ利用を取得/設定する。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        chk = getattr(dlg, "IDC_chkLocalCache", None)
        if chk is None:
            return self._err("local cache checkbox not available")
        if enabled is not None:
            with _DialogAutoReply() as cap:
                chk.setChecked(bool(enabled))
            messages = cap.messages or None
        else:
            messages = None
        return self._ok({
            "enabled": bool(chk.isChecked()),
            "enabled_control": bool(chk.isEnabled()),
            "local_cache_sites":
                list(self._plugin.settings.local_cache_sites or []),
            "messages": messages,
        })

    def refreshCache(self):
        """選択中サーバーのSQLiteキャッシュを再作成する(長時間の場合あり)。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        with _DialogAutoReply() as cap:
            dlg.refresh_sqlite_clicked()
        return self._ok({"messages": cap.messages or None,
                         "result_count": dlg.result_count})

    # ---------- 詳細 / リンク / 複数選択 ----------

    def selectResults(self, indices):
        """結果リストの複数データセットを選択する(index配列)。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        lw = dlg.IDC_listResults
        if not isinstance(indices, (list, tuple)):
            indices = [indices]
        rows = set()
        for s in indices:
            if isinstance(s, bool) or not isinstance(s, int) \
                    or not (0 <= s < lw.count()):
                return self._err(
                    f"invalid index: {s!r} (0..{lw.count() - 1})")
            rows.add(s)
        lw.clearSelection()
        for i in rows:
            lw.item(i).setSelected(True)
        if rows:
            lw.setCurrentItem(lw.item(min(rows)))
        return self._ok({"selected": sorted(rows),
                         "resources": dlg.IDC_listRessources.count()})

    def datasetDetails(self, index=None):
        """選択データセットの詳細(package辞書)を返す。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        lw = dlg.IDC_listResults
        if index is None:
            it = lw.currentItem()
            if it is None:
                return self._err("no dataset selected")
        else:
            if isinstance(index, bool) or not isinstance(index, int) \
                    or not (0 <= index < lw.count()):
                return self._err(
                    f"invalid index: {index!r} (0..{lw.count() - 1})")
            it = lw.item(index)
        pkg = it.data(_USER_ROLE) or {}
        try:
            return self._ok({"package": json.loads(
                json.dumps(pkg, default=str))})
        except Exception:
            return self._ok({"package": {
                "title": pkg.get("title"), "id": pkg.get("id"),
                "name": pkg.get("name")}})

    def link(self, copy=False):
        """リンク表示欄の内容を返す。copy=Trueでクリップボードへ。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        text = dlg.IDC_plainTextLink.toPlainText()
        if copy:
            dlg.copy_clipboard()
        return self._ok({"link": text, "copied": bool(copy)})

    # ---------- サーバー / 設定 / その他 ----------

    def openProviders(self):
        """データプロバイダ選択ダイアログを開く(非同期起動)。"""
        from qgis.PyQt.QtCore import QTimer
        dlg, err = self._require_dialog()
        if err:
            return err
        QTimer.singleShot(0, dlg.select_data_provider_clicked)
        return self._ok({"launched": True})

    def listServers(self):
        """カタログサーバー設定一覧を返す。"""
        st = self._plugin.settings
        custom = []
        for name, info in (st.custom_servers or {}).items():
            if isinstance(info, dict):
                custom.append({"name": name, "url": info.get("url"),
                               "type": info.get("type")})
            else:
                custom.append({"name": name, "url": info, "type": None})
        selected = [s for s in
                    (st.selected_ckan_servers or "").split("|") if s]
        return self._ok({
            "selected_servers": selected,
            "selected_ckan_urls": list(st.selected_ckan_urls or []),
            "active_urls": st.active_server_urls(),
            "custom_servers": custom,
            "ckan_url": st.ckan_url,
            "local_cache_sites": list(st.local_cache_sites or []),
            "server_errors": st.server_errors or {},
        })

    def selectServers(self, names):
        """検索対象サーバーを選択して再読込する。"""
        st = self._plugin.settings
        dlg = self._dialog()
        if isinstance(names, str):
            names = [n for n in names.split("|") if n]
        if not isinstance(names, (list, tuple)):
            return self._err("names must be a list of server names")
        st.selected_ckan_servers = "|".join(str(n) for n in names)
        # 選択名→api_url 解決(公式リストは再起動時に構築されるため
        # カスタムサーバーと既知URLから解決する)
        urls = []
        for n in names:
            info = (st.custom_servers or {}).get(n)
            if isinstance(info, dict):
                urls.append(info.get("url"))
            elif info:
                urls.append(info)
        if urls:
            st.selected_ckan_urls = [u for u in urls if u]
            if len(st.selected_ckan_urls) == 1:
                st.ckan_url = st.selected_ckan_urls[0]
        st.save()
        if dlg is not None:
            with _DialogAutoReply() as cap:
                dlg.window_loaded()
            return self._ok({"selected": list(names),
                             "messages": cap.messages or None})
        return self._ok({"selected": list(names)})

    def addServer(self, name, url):
        """カスタムサーバーを追加する。"""
        st = self._plugin.settings
        name = str(name or "").strip()
        url = str(url or "").strip()
        if not name or not url:
            return self._err("name and url required")
        import os
        import urllib.parse
        is_local = (url.startswith(("local://", "file://"))
                    or os.path.isdir(url))
        if not is_local:
            scheme = urllib.parse.urlparse(url).scheme.lower()
            if scheme not in ("http", "https"):
                return self._err("url must be http(s), file://, local:// "
                                 "or a local folder path")
        st.custom_servers = dict(st.custom_servers or {})
        st.custom_servers[name] = {"url": url}
        sel = [s for s in (st.selected_ckan_servers or "").split("|") if s]
        if name not in sel:
            sel.append(name)
        st.selected_ckan_servers = "|".join(sel)
        st.save()
        return self._ok({"added": name, "url": url,
                         "selected": sel})

    def removeServer(self, name):
        """カスタムサーバーを削除する。"""
        st = self._plugin.settings
        name = str(name or "").strip()
        if name not in (st.custom_servers or {}):
            return self._err(
                f"not a custom server: {name!r} "
                f"(custom: {list((st.custom_servers or {}).keys())})")
        del st.custom_servers[name]
        sel = [s for s in (st.selected_ckan_servers or "").split("|")
               if s and s != name]
        st.selected_ckan_servers = "|".join(sel)
        st.save()
        return self._ok({"removed": name, "selected": sel})

    def testServer(self, url):
        """サーバーURLの接続テストを行う(同期HTTP。数秒ブロック)。"""
        dlg = self._dialog()
        cc = getattr(dlg, "cc", None) if dlg is not None else None
        url = str(url or "").strip()
        if not url:
            return self._err("url required")
        import os
        if os.path.isdir(url) or url.startswith(("local://", "file://")):
            path = url
            if url.startswith("local://"):
                path = url[len("local://"):]
            return self._ok({"ok": os.path.isdir(path),
                             "type": "local", "url": url})
        if cc is not None:
            ok, result = cc.test_groups(url)
            if not ok:
                return self._err(str(result))
            return self._ok({"ok": True, "type": "ckan", "url": url})
        return self._err("connector unavailable "
                         "(open the catalog dialog first)")

    def reload(self):
        """ダイアログを再読込する(サーバー・カテゴリ再取得+全件検索)。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        with _DialogAutoReply() as cap:
            dlg.window_loaded()
        return self._ok({"result_count": dlg.result_count,
                         "messages": cap.messages or None})

    def openDisclaimer(self):
        """免責事項ダイアログを開く。"""
        dlg, err = self._require_dialog()
        if err:
            return err
        dlg.show_disclaimer()
        return self._ok({"opened": True})

    def getSettings(self):
        """設定を返す。"""
        st = self._plugin.settings
        return self._ok({
            "ckan_url": st.ckan_url,
            "cache_dir": st.cache_dir,
            "results_limit": getattr(st, "results_limit", None),
            "request_timeout": getattr(st, "request_timeout", None),
            "use_local_cache_all": st.use_local_cache_all,
            "local_cache_sites": list(st.local_cache_sites or []),
            "selected_ckan_servers": st.selected_ckan_servers,
            "selected_ckan_urls": list(st.selected_ckan_urls or []),
            "custom_servers": dict(st.custom_servers or {}),
            "debug": st.debug,
            "authcfg": st.authcfg,
            "auth_propagate": getattr(st, "auth_propagate", None),
            "boxdrive_support": st.boxdrive_support,
            "long_path_support": st.long_path_support,
            "server_errors": st.server_errors or {},
        })

    def setSettings(self, settings=None):
        """設定を変更して保存する。"""
        st = self._plugin.settings
        settings = dict(settings or {})
        allowed = {"ckan_url", "cache_dir", "results_limit",
                   "request_timeout", "use_local_cache_all",
                   "local_cache_sites", "debug", "authcfg",
                   "auth_propagate", "boxdrive_support",
                   "long_path_support"}
        unknown = [k for k in settings if k not in allowed]
        if unknown:
            return self._err(f"unknown keys: {unknown} "
                             f"(allowed: {sorted(allowed)})")
        applied = {}
        for k, v in settings.items():
            if k in ("results_limit", "request_timeout"):
                try:
                    v = int(v)
                except Exception:
                    return self._err(f"invalid {k}: {v!r}")
            elif k in ("use_local_cache_all", "debug", "auth_propagate",
                       "boxdrive_support", "long_path_support"):
                v = bool(v)
            elif k == "local_cache_sites":
                if not isinstance(v, (list, tuple)):
                    return self._err("local_cache_sites must be a list")
                v = [str(x) for x in v]
            else:
                v = str(v) if v is not None else ""
            setattr(st, k, v)
            applied[k] = v
        st.save()
        return self._ok({"applied": applied})
