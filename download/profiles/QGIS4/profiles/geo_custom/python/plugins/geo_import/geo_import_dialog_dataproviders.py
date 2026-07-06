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

from qgis.PyQt import QtGui, uic
from qgis.PyQt.QtCore import QTimer, Qt, QStringListModel, QModelIndex, QObject, pyqtSignal, QEvent, QCoreApplication
from qgis.PyQt.QtGui import QStandardItemModel, QStandardItem, QColor
from qgis.PyQt.QtWidgets import QDialog, QApplication, QListWidgetItem, QAction, QInputDialog, QLineEdit, QFileDialog
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


class GeoImportDialogDataProviders(QDialog, FORM_CLASS):
    @staticmethod
    def tr(message):
        """翻訳用のtr()メソッド"""
        return QCoreApplication.translate('GeoImport', message)
    
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
            browse_action = QAction(self.util.tr('Browse folder...'), self.IDC_leManualUrl)
            browse_action.triggered.connect(self.select_local_folder)
            # addAction places an action inside the QLineEdit (Qt 5+)
            try:
                self.IDC_leManualUrl.addAction(browse_action)
            except Exception:
                # fallback: add to widget context menu
                self.IDC_leManualUrl.addActions([browse_action])
        except Exception:
            pass
        # connect the new browse button (visible next to test/add)
        try:
            self.IDC_bBrowseLocal.clicked.connect(self.select_local_folder)
        except Exception:
            pass
        self.list_model = QStandardItemModel(self)
        self.list_model.itemChanged.connect(self.item_checked_changed)
        self.IDC_listProviders.activated.connect(self.server_in_list_activated)
        self.IDC_listProviders.clicked.connect(self.server_in_list_clicked)
        self.IDC_listProviders.setModel(self.list_model)
        delete_custom_server_action = QAction('Delete', self.IDC_listProviders)
        delete_custom_server_action.triggered.connect(self.delete_custom_server)
        self.IDC_listProviders.addAction(delete_custom_server_action)
        # self.list_model.setHorizontalHeaderLabels(['CKAN Servers'])
        self.servers = []
        self.row_server_selected_in_list = -1
        self.util.msg_log_debug('GeoImportDialogDataProviders constructor')
        # self.IDC_grpManualDataProvider.collapsed = True
        # self.IDC_grpManualDataProvider.setCollapsed(True)
        #self.IDC_listProviders.setStyleSheet("QListWidget::item { border-bottom: 1px solid black; }");
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
                # raw.githubusercontent.com expects the branch name directly (not refs/heads/)
                'https://raw.githubusercontent.com/yamamoto-ryuzo/geo_import/main/resources/instances/instances.json'
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
                    instances_url
                    # , headers=self.ua_chrome
                    , verify=False
                    , stream=True
                    # not needed anymore, as we use QgsNetworkAccessManager.instance() now
                    #, proxies=self.settings.get_proxies()[1]
                    , timeout=self.settings.request_timeout
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
                self.util.dlg_warning(self.util.tr(u'Failed to load any CKAN instances.') + detail)
                return

            # サーバーリストの表示（両方のソース読み込み後に1回だけ行う）
            if len(instances_urls) == instances_urls.index(instances_url) + 1:
                for idx, server in enumerate(self.servers):
                    # サーバー名＋URLを表示
                    display_text = f"{server.short_title} ({server.url})"
                    i = QStandardItem(display_text)
                    i.setData(server)
                    if server.api_url is not None:
                        if server.is_custom:
                            i.setBackground(QColor(0, 0, 255, 50))
                        i.setCheckable(True)
                        i.setCheckState(Qt.CheckState.Checked if server.selected else Qt.CheckState.Unchecked)
                        self.list_model.appendRow(i)
        finally:
            self.__update_server_count()
            QApplication.restoreOverrideCursor()

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

    def delete_custom_server(self):
        self.util.msg_log_debug('delete context menu clicked')
        if self.row_server_selected_in_list == -1:
            self.util.dlg_information(self.util.tr('py_dlg_data_providers_no_server_selected'))
            return
        server_to_remove_item = self.list_model.item(self.row_server_selected_in_list, 0)
        server_to_remove = server_to_remove_item.data()
        if not server_to_remove.is_custom:
            self.util.dlg_information(self.util.tr('py_dlg_data_providers_cannot_delete_sever_from_official_list'))
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
            self.util.tr('Select LOCAL folder'),
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
                self.util.dlg_warning(self.util.tr('py_dlg_set_info_local_not_found').format(local_path))
                return
            # Treat existing folder as successful connection (do not require packages.json)
            self.util.dlg_information(self.util.tr(u'py_dlg_set_info_conn_succs'))
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        ok, result = self.cc.test_groups(api_url)
        QApplication.restoreOverrideCursor()

        if not ok:
            self.util.dlg_warning(result)
            return
        else:
            self.util.dlg_information(self.util.tr(u'py_dlg_set_info_conn_succs'))

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
            self.util.tr('py_dlg_data_providers_custom_server'),
            self.util.tr('py_dlg_data_providers_name_custom_server'),
            QLineEdit.Normal,
            ""
        )
        if not ok_pressed or server_name is None or server_name.isspace() or server_name == '':
            return

        if server_name in self.settings.custom_servers:
            self.util.dlg_warning(self.util.tr('py_dlg_data_providers_custom_server_name_exists').format(server_name))
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
        if item.checkState() == Qt.CheckState.Unchecked:
            item.data().selected = False
            return

        # deselect all available servers.
        # currently selected one might not be visible
        # because of current search criteria
        for server in self.servers:
            server.selected = False

        # now work on server visible in the list
        for row in range(self.list_model.rowCount()):
            i = self.list_model.item(row, 0)
            if i != item and i.checkState() == Qt.CheckState.Checked:
                i.setCheckState(Qt.CheckState.Unchecked)

        item.data().selected = True if item.checkState() == Qt.CheckState.Checked else False

    def save_btn_clicked(self):
        self.util.msg_log_debug('save clicked')
        selected_servers = [s.settings_key for s in self.servers if s.selected]
        if len(selected_servers) < 1:
            self.settings.selected_ckan_servers = ''
            self.util.dlg_warning(self.util.tr('py_dlg_data_providers_no_server_selected'))
            return
        else:
            self.util.msg_log_debug(u'selected servers: {}'.format(selected_servers))
            self.settings.selected_ckan_servers = '|'.join(selected_servers)
            self.settings.ckan_url = [s for s in self.servers if s.selected][0].api_url
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
