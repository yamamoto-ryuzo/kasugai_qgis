# -*- coding: utf-8 -*-
"""
/***************************************************************************
 QGIS Data Catalog Integration / Catalog Integration
                                 A QGIS plugin
 Download and display CKAN enabled Open Data Portals
                              -------------------
        begin                : 2019-06-30
        git sha              : $Format:%H$
        copyright            : (C) 2019 by BergWerk GIS
        email                : wb@BergWerk-GIS.at
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import json
import os
import time

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QTimer, Qt, QObject, pyqtSignal, QEvent, QCoreApplication, QThread
from qgis.PyQt.QtGui import QStandardItemModel, QStandardItem, QColor
from qgis.PyQt.QtWidgets import QDialog, QApplication, QAction, QInputDialog, QLineEdit, QFileDialog
from .ckanconnector import CkanConnector
from .httpcall import HttpCall
from .serverinstance import ServerInstance
from .util import Util

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(
        os.path.dirname(__file__),
        'geo_import_dialog_dataproviders.ui'
    )
)


class ServerCheckThread(QThread):
    """カタログ一覧の死活チェックをバックグラウンドで実行するワーカー。
    軽量な package_search(rows=0) をQThreadで逐次実行しGUIをブロックしない。
    結果はサーバーごとに resultReady(api_url, ok, latency_ms, message) で通知する。"""
    resultReady = pyqtSignal(object)

    def __init__(self, cc, api_urls):
        super(ServerCheckThread, self).__init__()
        self._cc = cc
        self._api_urls = list(api_urls)

    def run(self):
        for api_url in self._api_urls:
            if self.isInterruptionRequested():
                break
            started = time.monotonic()
            try:
                ok, result = self._cc.package_search(
                    '', None, None, rows=0, api_url=api_url)
            except Exception as e:
                ok, result = False, str(e)
            latency_ms = int((time.monotonic() - started) * 1000)
            self.resultReady.emit(
                (api_url, bool(ok), latency_ms, '' if ok else str(result)))


class GeoImportDialogDataProviders(QDialog, FORM_CLASS):
    def __init__(self, settings, parent=None):
        """Constructor."""
        super(GeoImportDialogDataProviders, self).__init__(parent)
        # Qt Designerで作成したUIファイルからユーザーインターフェースを設定
        # setupUi実行後は、self.<オブジェクト名>でDesignerのオブジェクトにアクセス可能
        # 自動接続スロットも利用可能
        # #widgets-and-dialogs-with-auto-connect
        self.setModal(True)
        self.setupUi(self)
        self.main_win = parent
        self.settings = settings
        self.util = Util(self.settings, self.main_win)
        self.cc = CkanConnector(self.settings, self.util)

        self.clickable(self.IDC_lbl_enter_dataprovider_url).connect(self.lbl_clicked_enter_data_provider_url)
        # add a browse action to the manual URL line edit for selecting local folders
        try:
            browse_action = QAction(QCoreApplication.translate('GeoImport', 'Browse folder...'), self.IDC_leManualUrl)
            browse_action.triggered.connect(self.select_local_folder)
            # addAction places an action inside the QLineEdit (Qt 5+)
            try:
                self.IDC_leManualUrl.addAction(browse_action)
            except Exception:
                # fallback: add to widget context menu
                self.IDC_leManualUrl.addActions([browse_action])
        except Exception:  # nosec B110  # 設計上の許容
            pass
        # connect the new browse button (visible next to test/add)
        try:
            self.IDC_bBrowseLocal.clicked.connect(self.select_local_folder)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        self.list_model = QStandardItemModel(self)
        self.list_model.itemChanged.connect(self.item_checked_changed)
        self.IDC_listProviders.activated.connect(self.server_in_list_activated)
        self.IDC_listProviders.clicked.connect(self.server_in_list_clicked)
        self.IDC_listProviders.setModel(self.list_model)
        delete_custom_server_action = QAction(QCoreApplication.translate('GeoImport', 'Delete'), self.IDC_listProviders)
        delete_custom_server_action.triggered.connect(self.delete_custom_server)
        self.IDC_listProviders.addAction(delete_custom_server_action)
        # self.list_model.setHorizontalHeaderLabels(['CKAN Servers'])
        self.servers = []
        self._check_thread = None
        self._check_queued = set()
        self.finished.connect(self._stop_server_checks)
        self.row_server_selected_in_list = -1
        self.util.msg_log_debug('GeoImportDialogDataProviders constructor')
        # self.IDC_grpManualDataProvider.collapsed = True
        # self.IDC_grpManualDataProvider.setCollapsed(True)
        # self.IDC_listProviders.setStyleSheet("QListWidget::item { border-bottom: 1px solid black; }");
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.window_loaded)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def showEvent(self, event):
        self.util.msg_log_debug('showevent')
        QDialog.showEvent(self, event)
        if self.timer is not None:
            self.timer.start(500)
        self.util.msg_log_debug('showevent finished')

    def window_loaded(self):
        try:
            if self.timer is not None:
                self.timer.stop()
                self.timer = None
            self.list_model.clear()

            # 読み込むJSONファイル（複数）
            instances_urls = [
                'https://raw.githubusercontent.com/ckan/ckan-instances/gh-pages/config/instances.json',
                # 独自登録分は harness repo の geo_import/resources/ を正本として配信
                'https://raw.githubusercontent.com/yamamoto-ryuzo/qgis_live_harness/refs/heads/master/qgis-plugin/geo_import/resources/instances/instances.json'
            ]

            # ローカルのJSONファイルを追加（存在する場合）
            local_instances_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'resources', 'instances', 'instances.json')
            if os.path.exists(local_instances_path):
                # ファイルURIとして追加
                file_uri = f"file:///{local_instances_path.replace('\\', '/')}"
                instances_urls.append(file_uri)
                self.util.msg_log_debug('Found local instances.json: ' + file_uri)

            # すべてのサーバーのリスト
            self.servers = []
            # 取得失敗時の情報を集めてダイアログ表示できるようにする
            fetch_failures = []

            for instances_url in instances_urls:
                self.util.msg_log_debug('Getting instances from: ' + instances_url)

                # ローカルファイルの場合は直接読み込む
                if instances_url.startswith('file:///'):
                    try:
                        local_path = instances_url[8:].replace('/', '\\')
                        with open(local_path, 'r', encoding='utf-8') as f:
                            result = json.load(f)
                        self.process_instances_result(result)
                        continue
                    except Exception as e:
                        self.util.msg_log_error(f"Failed to read local file: {str(e)}")

                # リモートファイルの場合はHTTPリクエスト
                http_call = HttpCall(self.settings, self.util)
                response = http_call.execute_request(
                    instances_url,                    # headers=self.ua_chrome
                    verify=False, stream=True,                    # not needed anymore, as we use QgsNetworkAccessManager.instance() now
                    # , proxies=self.settings.get_proxies()[1]
                    timeout=self.settings.request_timeout
                )

                if not response.ok:
                    self.util.msg_log_error(u'{}: {} {}'.format(response.status_code, response.status_message, response.reason))
                    continue  # 次のURLを処理

                try:
                    # response.text can be a QByteArray, bytes or str depending on Qt/PyQt version
                    resp_text = response.text
                    if hasattr(resp_text, 'data'):
                        try:
                            json_txt = resp_text.data().decode('utf-8')
                        except Exception:
                            json_txt = bytes(resp_text).decode('utf-8', errors='replace')
                    elif isinstance(resp_text, (bytes, bytearray)):
                        json_txt = resp_text.decode('utf-8')
                    else:
                        json_txt = str(resp_text)

                    self.util.msg_log_debug(u'resp_msg (decoded):\n{} .......'.format(json_txt[:255]))
                    result = json.loads(json_txt)
                    self.process_instances_result(result)
                except Exception as e:
                    # 失敗理由を記録
                    msg = f"Error parsing JSON from {instances_url}: {e}"
                    self.util.msg_log_error(msg)
                    fetch_failures.append(msg)
                    self.util.msg_log_last_exception()
                    continue

            # カスタムサーバーを追加
            self.add_custom_servers()

            # サーバーがない場合は警告
            if not self.servers:
                QApplication.restoreOverrideCursor()
                # どの URL が失敗したのかをユーザーに示す
                detail = ''
                if fetch_failures:
                    detail = '\n\n' + '\n'.join(fetch_failures)
                self.util.dlg_warning(QCoreApplication.translate('GeoImport', u'Failed to load any CKAN instances.') + detail)
                return

            # サーバーリストの表示（両方のソース読み込み後に1回だけ行う）
            if len(instances_urls) == instances_urls.index(instances_url) + 1:
                for idx, server in enumerate(self.servers):
                    # サーバー名＋URLを表示
                    display_text = f"{server.short_title} ({server.url})"
                    # ローカルダウンロード利用サイトはマーカーを付ける
                    try:
                        if server.api_url and self.settings.use_local_cache(server.api_url):
                            display_text = QCoreApplication.translate(
                                'GeoImport', '[local] ') + display_text
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
                    i = QStandardItem(display_text)
                    i.setData(server)
                    if server.api_url is not None:
                        if server.is_custom:
                            i.setBackground(QColor(0, 0, 255, 50))
                        # 疎通チェック結果/失敗記録に応じて死活マーカーと色を付ける
                        self._apply_item_status(i, server)
                        i.setCheckable(True)
                        i.setCheckState(Qt.CheckState.Checked if server.selected else Qt.CheckState.Unchecked)
                        self.list_model.appendRow(i)
        finally:
            self.__update_server_count()
            QApplication.restoreOverrideCursor()
            # 一覧表示後に全サーバーの死活を非同期で確認する
            self._start_server_checks()

    def process_instances_result(self, result):
        """JSONから読み込んだインスタンス情報を処理"""
        self.settings.load()
        selected_servers = self.settings.selected_ckan_servers.split('|')

        for entry in result:
            url_api = None
            if 'url-api' in entry:
                url_api = entry['url-api']
                if 'geothermaldata' not in url_api:
                    url_api = url_api.replace('http://', 'https://')
                # APIエンドポイントの形式を確認し、必要な場合のみ/api/3/を追加
                if not (url_api.endswith('/api/3/') or url_api.endswith('/api/3')):
                    url_api += '/api/3/'
            description = entry.get('description', '')
            si = ServerInstance(entry['title'], description, entry['url'], url_api)
            si.selected = True if si.settings_key in selected_servers else False

            # 重複チェック（同じURLは追加しない）
            is_duplicate = False
            for existing in self.servers:
                if existing.url == si.url:
                    is_duplicate = True
                    break

            if not is_duplicate:
                self.servers.append(si)

    def add_custom_servers(self):
        """カスタムサーバーを追加"""
        self.settings.load()
        selected_servers = self.settings.selected_ckan_servers.split('|')

        self.util.msg_log_debug(u'{} custom servers'.format(len(self.settings.custom_servers)))
        for cs_name, cs_info in self.settings.custom_servers.items():
            # cs_info: {url, type}
            if isinstance(cs_info, dict):
                url = cs_info.get('url', '')
                # type情報は今後の拡張用。現状はCKANのみ想定
            else:
                url = cs_info  # 後方互換
            si = ServerInstance(cs_name, cs_name, url, url, custom_entry=True)
            si.selected = True if si.settings_key in selected_servers else False
            self.servers.append(si)

    _STATUS_MARKS = (u'○ ', u'△ ', u'× ')

    def _is_local_server(self, api_url):
        return (api_url.startswith('local://')
                or api_url.startswith('file://')
                or os.path.isdir(api_url))

    def _apply_item_status(self, item, server):
        """死活チェック結果に応じて一覧アイテムへ 稼働/遅延/到達不能 を付与する。
        優先度: 最新チェック結果(TTL内) > 記録済み失敗 > 未チェック(マーカー無し)。"""
        status = None
        latency_ms = None
        error = ''
        check = self.settings.server_check(server.api_url)
        if check is not None:
            status = check.get('status')
            latency_ms = check.get('latency_ms')
            error = check.get('error') or ''
        else:
            err = self.settings.server_error(server.api_url)
            if err:
                status, error = 'down', err
        live_status = getattr(server, 'check_status', None)
        if live_status is not None:
            status = live_status
            latency_ms = getattr(server, 'check_latency', latency_ms)
            error = getattr(server, 'check_error', '') or error
        text = item.text()
        for mark in self._STATUS_MARKS:
            if text.startswith(mark):
                text = text[len(mark):]
                break
        if status == 'ok' and latency_ms is not None and latency_ms > 2000:
            status = 'slow'
        if status == 'ok':
            item.setText(self._STATUS_MARKS[0] + text)
            item.setToolTip(QCoreApplication.translate(
                'GeoImport', 'Reachable (response {0} ms)').format(latency_ms))
        elif status == 'slow':
            item.setText(self._STATUS_MARKS[1] + text)
            item.setToolTip(QCoreApplication.translate(
                'GeoImport', 'Slow response ({0} ms)').format(latency_ms))
        elif status == 'down':
            item.setText(self._STATUS_MARKS[2] + text)
            item.setBackground(QColor(255, 0, 0, 40))
            item.setToolTip(QCoreApplication.translate(
                'GeoImport', 'Last connection failed: {0}').format(error))

    def _start_server_checks(self):
        """一覧の全サーバーへ軽量疎通確認を非同期で実行する。
        TTL内のキャッシュ済み結果は一覧描画時に反映済みのため、
        残りだけをワーカーへ投げる。"""
        pending = getattr(self, '_check_queued', set())
        urls = []
        for s in self.servers:
            if not s.api_url or self._is_local_server(s.api_url):
                continue
            if self.settings.server_check(s.api_url) is not None:
                continue
            if s.api_url in pending:
                continue
            urls.append(s.api_url)
        self._check_queued = pending | set(urls)
        if not self._check_queued:
            return
        thread = getattr(self, '_check_thread', None)
        if thread is not None and thread.isRunning():
            return  # 実行中ワーカーの終了時に残分を再投入する
        self._dequeue_server_checks()

    def _dequeue_server_checks(self):
        urls = sorted(self._check_queued)
        self._check_queued = set()
        if not urls:
            self._check_thread = None
            return
        cc = getattr(self, 'cc', None)
        if cc is None:
            cc = self.cc = CkanConnector(self.settings, self.util)
        # ダイアログ破棄時にQThreadを巻き込まないようparentは付けず、
        # 終了時にdeleteLaterで後始末する
        self._check_thread = ServerCheckThread(cc, urls)
        self._check_thread.resultReady.connect(self._on_server_check_result)
        self._check_thread.finished.connect(self._on_server_checks_finished)
        self._check_thread.finished.connect(self._check_thread.deleteLater)
        self._check_thread.start()

    def _on_server_checks_finished(self):
        if self._check_queued:
            self._dequeue_server_checks()
            return
        self._check_thread = None
        try:
            self.settings.save()  # チェック結果をまとめて永続化
        except Exception:  # nosec B110  # 設計上の許容
            pass

    def _on_server_check_result(self, payload):
        api_url, ok, latency_ms, message = payload
        self.settings.record_server_check(api_url, ok, latency_ms, message)
        for s in self.servers:
            if s.api_url == api_url:
                s.check_status = 'ok' if ok else 'down'
                s.check_latency = latency_ms
                s.check_error = message
                break
        for row in range(self.list_model.rowCount()):
            item = self.list_model.item(row)
            if item is None:
                continue
            server = item.data()
            if isinstance(server, ServerInstance) and server.api_url == api_url:
                self._apply_item_status(item, server)

    def _stop_server_checks(self):
        self._check_queued = set()
        thread = getattr(self, '_check_thread', None)
        if thread is not None:
            thread.requestInterruption()

    def delete_custom_server(self):
        self.util.msg_log_debug('delete context menu clicked')
        if self.row_server_selected_in_list == -1:
            self.util.dlg_information(QCoreApplication.translate('GeoImport', 'py_dlg_data_providers_no_server_selected'))
            return
        server_to_remove_item = self.list_model.item(self.row_server_selected_in_list, 0)
        server_to_remove = server_to_remove_item.data()
        if not server_to_remove.is_custom:
            self.util.dlg_information(QCoreApplication.translate('GeoImport', 'py_dlg_data_providers_cannot_delete_sever_from_official_list'))
            return
        if server_to_remove.short_title in self.settings.custom_servers:
            self.util.msg_log_debug(u'deleting custom server: {}'.format(server_to_remove))
            del self.settings.custom_servers[server_to_remove.short_title]
        else:
            self.util.msg_log_debug(
                u'unable to delete custom server, not found: {}\n{}'
                .format(server_to_remove, self.settings.custom_servers)
            )
        self.servers.remove(server_to_remove)
        self.list_model.removeRow(self.row_server_selected_in_list)
        self.row_server_selected_in_list = -1

    def lbl_clicked_enter_data_provider_url(self):
        self.IDC_leManualUrl.setText('https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/')

    def select_local_folder(self):
        """Open folder dialog and set selected folder into manual URL field."""
        cache_dir = self.settings.cache_dir if hasattr(self.settings, 'cache_dir') else ''
        folder = QFileDialog.getExistingDirectory(
            self,
            QCoreApplication.translate('GeoImport', 'Select LOCAL folder'),
            cache_dir,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )
        if folder and folder != '':
            # set plain path (works with existing detection logic)
            self.IDC_leManualUrl.setText(folder)

    def searchTermChanged(self, text):
        results = []
        for s in self.servers:
            if s.search(text) > 0:
                results.append(s)
        self.list_model.clear()

        if len(results) < 1:
            # early exit
            self.__update_server_count()
            return

        for result in sorted(results, key=lambda r: r.last_search_result, reverse=True):
            # debug: show score of string matching in title
            # i = QStandardItem(u'{} - {}'.format(result.last_search_result, result.title))
            i = QStandardItem(result.title)
            i.setData(result)
            if result.api_url is not None:
                if result.is_custom:
                    i.setBackground(QColor(0, 0, 255, 50))
                # 疎通チェック結果/失敗記録に応じて死活マーカーと色を付ける
                self._apply_item_status(i, result)
                i.setCheckable(True)
                i.setCheckState(Qt.CheckState.Checked if result.selected else Qt.CheckState.Unchecked)
                self.list_model.appendRow(i)
        self.__update_server_count()

    def btn_clicked_test_connection(self):
        self.util.msg_log_debug('btn_clicked_test_connection')

        api_url = self.IDC_leManualUrl.text()
        self.util.msg_log_debug('testing URL: {0}'.format(api_url))

        # detect local folder (allow absolute path, file:// or local://)
        import os
        from urllib.parse import urlparse
        local_path = None
        if api_url.startswith('file://'):
            parsed = urlparse(api_url)
            try:
                from urllib.request import url2pathname
                p = url2pathname(parsed.path)
                if parsed.netloc:
                    # UNC path
                    local_path = os.path.abspath('//' + parsed.netloc + p)
                else:
                    # strip leading slash on Windows drive paths like /C:/...
                    if p.startswith('/') and len(p) > 2 and p[2] == ':':
                        p = p.lstrip('/')
                    local_path = os.path.abspath(p)
            except Exception:
                local_path = os.path.abspath(os.path.join(parsed.netloc, parsed.path))
        elif api_url.startswith('local://'):
            local_path = api_url[len('local://'):]
        elif os.path.isdir(api_url):
            local_path = api_url

        if local_path:
            # If a local folder is provided, consider existence sufficient for connection test.
            if not os.path.isdir(local_path):
                self.util.dlg_warning(QCoreApplication.translate('GeoImport', 'py_dlg_set_info_local_not_found').format(local_path))
                return
            # Treat existing folder as successful connection (do not require packages.json)
            self.util.dlg_information(QCoreApplication.translate('GeoImport', u'py_dlg_set_info_conn_succs'))
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        ok, result = self.cc.test_groups(api_url)
        QApplication.restoreOverrideCursor()

        if not ok:
            self.util.dlg_warning(result)
            return
        else:
            self.util.dlg_information(QCoreApplication.translate('GeoImport', u'py_dlg_set_info_conn_succs'))

    def btn_clicked_add_connection(self):
        self.util.msg_log_debug('btn_clicked_add_connection')

        # let's do another sanity check if the provided url works
        # might have changed since the user tested it
        api_url = self.IDC_leManualUrl.text()
        # detect local folder (allow absolute path, file:// or local://)
        from urllib.parse import urlparse
        server_type = 'CKAN'
        local_path = None
        if api_url.startswith('file://'):
            parsed = urlparse(api_url)
            try:
                from urllib.request import url2pathname
                p = url2pathname(parsed.path)
                if parsed.netloc:
                    local_path = os.path.abspath('//' + parsed.netloc + p)
                else:
                    if p.startswith('/') and len(p) > 2 and p[2] == ':':
                        p = p.lstrip('/')
                    local_path = os.path.abspath(p)
            except Exception:
                import os
                local_path = os.path.abspath(os.path.join(parsed.netloc, parsed.path))
        elif api_url.startswith('local://'):
            local_path = api_url[len('local://'):]
        else:
            import os
            if os.path.isdir(api_url):
                local_path = api_url

        if local_path:
            # normalize
            api_url = os.path.abspath(local_path)
            server_type = 'LOCAL'

        # If not local, test via CKAN API
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        if server_type == 'CKAN':
            ok, result = self.cc.test_groups(api_url)
            QApplication.restoreOverrideCursor()
            if not ok:
                self.util.dlg_warning(result)
                return
        else:
            QApplication.restoreOverrideCursor()

        server_name, ok_pressed = QInputDialog.getText(
            self,
            QCoreApplication.translate('GeoImport', 'py_dlg_data_providers_custom_server'),
            QCoreApplication.translate('GeoImport', 'py_dlg_data_providers_name_custom_server'),
            QLineEdit.EchoMode.Normal,
            ""
        )
        if not ok_pressed or server_name is None or server_name.isspace() or server_name == '':
            return

        if server_name in self.settings.custom_servers:
            self.util.dlg_warning(QCoreApplication.translate('GeoImport', 'py_dlg_data_providers_custom_server_name_exists').format(server_name))
            return

        self.settings.custom_servers[server_name] = {"url": api_url, "type": server_type}
        self.settings.save()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.window_loaded()

    def server_in_list_activated(self, model_index):
        self.util.msg_log_debug(u'server activated, model index: {}'.format(model_index))

    def server_in_list_clicked(self, model_index):
        self.util.msg_log_debug(
            u'server clicked, col:{} row:{} data:{} model:{}'
            .format(
                model_index.column(),
                model_index.row(),
                model_index.data(),
                model_index.model()
            )
        )
        self.row_server_selected_in_list = model_index.row()

    def item_checked_changed(self, item):
        self.util.msg_log_debug(
            u'item changed, checked:{} item:{} item.data:{}'.format(
                item.checkState() == Qt.CheckState.Checked,
                item,
                item.data()
            )
        )
        # 複数サーバーの同時選択を許可する(横断検索用)。
        # チェック状態をそのまま selected フラグに反映するのみ。
        item.data().selected = True if item.checkState() == Qt.CheckState.Checked else False

    def save_btn_clicked(self):
        self.util.msg_log_debug('save clicked')
        selected = [s for s in self.servers if s.selected]
        selected_servers = [s.settings_key for s in selected]
        if len(selected_servers) < 1:
            self.settings.selected_ckan_servers = ''
            self.settings.selected_ckan_urls = []
            self.util.dlg_warning(QCoreApplication.translate('GeoImport', 'py_dlg_data_providers_no_server_selected'))
            return
        else:
            self.util.msg_log_debug(u'selected servers: {}'.format(selected_servers))
            self.settings.selected_ckan_servers = '|'.join(selected_servers)
            # 複数選択時の横断検索用に選択サーバーのapi_url一覧を保存
            self.settings.selected_ckan_urls = [s.api_url for s in selected]
            # 後方互換: 従来の単一ckan_urlには先頭サーバーを設定
            self.settings.ckan_url = selected[0].api_url
        self.settings.save()
        self.accept()

    def __update_server_count(self):
        txt = self.IDC_lbInstanceCount.text().format(
            len([s for s in self.servers if s.api_url is not None]),
            len(self.servers)
        )
        self.IDC_lbInstanceCount.setText(txt)

    def clickable(self, widget):
        # from https://wiki.python.org/moin/PyQt/Making%20non-clickable%20widgets%20clickable
        class Filter(QObject):
            clicked = pyqtSignal()

            def eventFilter(self, obj, event):
                if obj == widget:
                    if event.type() == QEvent.Type.MouseButtonRelease:
                        if obj.rect().contains(event.pos()):
                            self.clicked.emit()
                            # The developer can opt for .emit(obj) to get the object within the slot.
                            return True
                return False

        widget_filter = Filter(widget)
        widget.installEventFilter(widget_filter)
        return widget_filter.clicked
