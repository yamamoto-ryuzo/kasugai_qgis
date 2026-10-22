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
