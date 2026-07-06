# データ取得用QThread
from qgis.PyQt.QtCore import QThread, pyqtSignal


class DataFetchThread(QThread):
    result_ready = pyqtSignal(list, int, int, int)  # (page_results, result_count, page_count, total_resource_count)

    def __init__(self, db_path, format_text, format_lc, current_page, results_limit, search_txt=None, group_names=None):
        super().__init__()
        self.db_path = db_path
        self.format_text = format_text
        self.format_lc = format_lc
        self.current_page = current_page
        self.results_limit = results_limit
        self.search_txt = search_txt or ''
        self.group_names = group_names  # 追加: グループ名リスト

    def run(self):
        import sqlite3
        filtered_results = []
        result_count = 0
        total_resource_count = 0
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            # まず全件取得（形式フィルタは後でPython側で）
            c.execute('SELECT raw_json FROM packages')
            rows = c.fetchall()
            import json
            for row in rows:
                entry = json.loads(row[0])
                # カテゴリ（グループ）フィルタ
                group_match = True
                if self.group_names is not None:
                    # entry['groups']はリスト（各要素はdictで'name'キーあり）
                    entry_groups = [g['name'] for g in entry.get('groups', []) if 'name' in g]
                    # 1つでも一致すればOK（OR条件）
                    group_match = any(g in entry_groups for g in self.group_names)
                if not group_match:
                    continue
                # 検索語フィルタ
                if self.search_txt:
                    text_fields = []
                    if 'title' in entry and entry['title']:
                        if isinstance(entry['title'], dict):
                            text_fields.extend(str(v) for v in entry['title'].values())
                        else:
                            text_fields.append(str(entry['title']))
                    if 'notes' in entry and entry['notes']:
                        text_fields.append(str(entry['notes']))
                    if 'tags' in entry and entry['tags']:
                        for tag in entry['tags']:
                            if isinstance(tag, dict) and 'name' in tag:
                                text_fields.append(str(tag['name']))
                            elif isinstance(tag, str):
                                text_fields.append(tag)
                    if 'author' in entry and entry['author']:
                        text_fields.append(str(entry['author']))
                    if 'maintainer' in entry and entry['maintainer']:
                        text_fields.append(str(entry['maintainer']))
                    if 'organization' in entry and entry['organization']:
                        org = entry['organization']
                        if isinstance(org, dict):
                            for k in ('name', 'title', 'description'):
                                v = org.get(k)
                                if v:
                                    text_fields.append(str(v))
                    search_hit = any(self.search_txt.lower() in t.lower() for t in text_fields)
                else:
                    search_hit = True
                # データ形式フィルタ
                if self.format_text == 'すべて':
                    if search_hit:
                        filtered_results.append(entry)
                else:
                    if any(self.format_lc == (res.get('format','').strip().lower()) for res in entry.get('resources', [])) and search_hit:
                        filtered_results.append(entry)
            # 全件分のリソース数を集計（形式フィルタを考慮）
            if self.format_text == 'すべて':
                total_resource_count = sum(len(entry.get('resources', [])) for entry in filtered_results)
            else:
                total_resource_count = sum(
                    len([res for res in entry.get('resources', []) if self.format_lc == (res.get('format') or '').strip().lower()])
                    for entry in filtered_results
                )
            conn.close()
        except Exception as e:
            filtered_results = []
            total_resource_count = 0
        result_count = len(filtered_results)
        page_count = max(1, (result_count + self.results_limit - 1) // self.results_limit)
        start_idx = (self.current_page - 1) * self.results_limit
        end_idx = start_idx + self.results_limit
        page_results = filtered_results[start_idx:end_idx]
        self.result_ready.emit(page_results, result_count, page_count, total_resource_count)
# -*- coding: utf-8 -*-
"""
/***************************************************************************
 QGIS Data Catalog Integration / Catalog Integration
                                 A QGIS plugin
 Download and display CKAN enabled Open Data Portals
                              -------------------
        begin                : 2014-10-24
        git sha              : $Format:%H$
        copyright            : (C) 2014 by BergWerk GIS
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

import math
import os
import sys
from qgis.PyQt.QtCore import Qt, QTimer, QCoreApplication
from qgis.PyQt import QtGui, uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QApplication, QListWidgetItem, QDialog, QMessageBox
from .geo_import_dialog_disclaimer import GeoImportDialogDisclaimer
from .geo_import_dialog_dataproviders import GeoImportDialogDataProviders
from .pyperclip import copy
from .ckanconnector import CkanConnector
from .util import Util


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'geo_import_dialog_base.ui'))


class GeoImportDialog(QDialog, FORM_CLASS):
    # メインダイアログクラス - データカタログのブラウズと検索を管理
    
    @staticmethod
    def tr(message):
        """翻訳用のtr()メソッド"""
        return QCoreApplication.translate('GeoImport', message)
    
    def on_IDC_bSelectAllResources_clicked(self):
        # 全リソース選択ボタンのクリックイベント処理
        self.select_all_resources()
        
    def select_all_resources(self):
        """検索結果リストに表示されているデータセット・リソースのみ全選択・全チェックする"""
        # 検索結果リストの内容をそのまま全選択
        if hasattr(self, 'IDC_listResults'):
            self.IDC_listResults.selectAll()
        # リソースも「現在の検索結果・形式フィルタ」に従い全チェック
        selected_items = self.IDC_listResults.selectedItems() if hasattr(self, 'IDC_listResults') else []
        format_text = self.IDC_comboFormat.currentText() if hasattr(self, 'IDC_comboFormat') else 'すべて'
        format_lc = format_text.lower()
        def is_format_match(res):
            if format_text == 'すべて':
                return True
            if 'format' in res and res['format']:
                fmt = res['format'].strip().lower()
                if format_lc == fmt:
                    return True
            return False
        all_resources = []
        for item in selected_items:
            package = item.data(Qt.ItemDataRole.UserRole)
            if package is None:
                continue
            resources = package.get('resources', [])
            filtered_resources = [res for res in resources if is_format_match(res)]
            all_resources.extend(filtered_resources)
        if hasattr(self, 'IDC_listRessources'):
            self.IDC_listRessources.clear()
            for res in all_resources:
                disp = u'{}: {}'.format(res.get('format', 'no format'), res.get('url', '(no url)'))
                item = QListWidgetItem(disp)
                item.setData(Qt.ItemDataRole.UserRole, res)
                item.setCheckState(Qt.CheckState.Checked)
                self.IDC_listRessources.addItem(item)
        # Log for debugging which path triggers label update
        try:
            self.util.msg_log_debug(u'select_all_resources: added {0} resources, calling update_resource_checked_count'.format(len(all_resources)))
        except Exception:
            pass
        self.update_resource_checked_count()

    def clear_selection(self):
        """検索結果リストの選択をクリアする"""
        if hasattr(self, 'IDC_listResults'):
            self.IDC_listResults.clearSelection()
            self.IDC_textDetails.clear()
            self.IDC_listRessources.clear()
            self.IDC_plainTextLink.clear()
        if hasattr(self, 'IDC_lblSelectedCount'):
            self.IDC_lblSelectedCount.setText("選択中: 0件")
    def update_format_list(self, results):
        """
        データ形式リストを一般的な形式+GISでよく使われる形式の固定リスト＋実データ形式一覧で構成し、手入力もできるようにする
        """
        # 固定リスト
        format_list = [
            'すべて',
            'csv', 'tsv', 'txt', 'json', 'geojson', 'xml', 'html', 'pdf', 'zip', 'rar', '7z',
            'xls', 'xlsx',
            'shp', 'gpkg', 'kml', 'kmz', 'gml',
            'sqlite', 'rdf',
            'jpg', 'jpeg', 'png', 'gif', 'tiff', 'svg',
        ]
        # 検索結果から実際のformat値を抽出
        if results:
            found_formats = set()
            for entry in results:
                for res in entry.get('resources', []):
                    fmt = res.get('format', '').strip()
                    if fmt:
                        found_formats.add(fmt)
            # 固定リストにないものを追加
            for fmt in sorted(found_formats, key=lambda x: x.lower()):
                if fmt.lower() not in [f.lower() for f in format_list]:
                    format_list.append(fmt)
        # 重複除去しつつ大文字小文字区別せず整形
        seen = set()
        format_list_unique = []
        for fmt in format_list:
            key = fmt.lower()
            if key not in seen:
                format_list_unique.append(fmt)
                seen.add(key)
        self.set_format_combobox(format_list_unique)

    def set_format_combobox(self, format_list):
        if hasattr(self, 'IDC_comboFormat'):
            self.IDC_comboFormat.blockSignals(True)
            self.IDC_comboFormat.clear()
            for fmt in format_list:
                self.IDC_comboFormat.addItem(fmt)
            self.IDC_comboFormat.setEditable(True)
            self.IDC_comboFormat.blockSignals(False)

    def __init__(self, settings, iface, parent=None):
        """Constructor."""
        super(GeoImportDialog, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)
        self.iface = iface
        self.main_win = parent
        self.search_txt = ''
        self.cur_package = None
        self.result_count = 0
        self.current_page = 1
        self.page_count = 0
        self.current_group = None
        # TODO:
        # * create settings dialog
        # * read SETTINGS

        self.settings = settings
        self.util = Util(self.settings, self.main_win)

        self.IDC_lblVersion.setText(self.IDC_lblVersion.text().format(self.settings.version))
        #self.IDC_lblSuchergebnisse.setText(self.util.tr('py_dlg_base_search_result'))
        self.IDC_lblPage.setText(self.util.tr('py_dlg_base_page_1_1'))

        # データ形式コンボボックスを手入力可能に
        if hasattr(self, 'IDC_comboFormat'):
            self.IDC_comboFormat.setEditable(True)

        icon_path = self.util.resolve(u'icon-copy.png')
        self.IDC_bCopy.setIcon(QtGui.QIcon(icon_path))

        self.cc = CkanConnector(self.settings, self.util)

        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.window_loaded)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        # don't initialized dialogs here, WaitCursor would be set several times
        # self.dlg_disclaimer = GeoImportDialogDisclaimer(self.settings)
        # self.dlg_dataproviders = GeoImportDialogDataProviders(self.settings, self.util)

        # --- 追加: SQLite再取得ボタンのシグナル接続 ---
        if hasattr(self, 'IDC_bRefreshSqlite'):
            self.IDC_bRefreshSqlite.clicked.connect(self.refresh_sqlite_clicked)
        # データセット一覧で複数選択を可能に
        if hasattr(self, 'IDC_listResults'):
            self.IDC_listResults.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
            self.IDC_listResults.selectionModel().selectionChanged.connect(self.update_selected_count)
        if hasattr(self, 'IDC_listRessources'):
            self.IDC_listRessources.itemChanged.connect(self.update_resource_checked_count)
        # --- 全選択ボタンのシグナル接続（明示的に） ---
        if hasattr(self, 'IDC_bSelectAllResources'):
            self.IDC_bSelectAllResources.clicked.connect(self.select_all_resources)
        # --- 全選択ボタンのシグナル接続（存在する場合） ---
        if hasattr(self, 'IDC_bSelectAllResources'):
            self.IDC_bSelectAllResources.clicked.connect(self.select_all_resources)
        
        # ダイアログ起動時に一度全件検索を実施（初期表示）
        self.list_all_clicked()

    def update_resource_checked_count(self, item=None):
        checked_count = 0
        for i in range(self.IDC_listRessources.count()):
            if self.IDC_listRessources.item(i).checkState() == Qt.CheckState.Checked:
                checked_count += 1
        selected_items = self.IDC_listResults.selectedItems() if hasattr(self, 'IDC_listResults') else []
        # Debug log to indicate this function updated the label
        try:
            self.util.msg_log_debug(u'update_resource_checked_count: selected_datasets={0} checked_resources={1}'.format(len(selected_items), checked_count))
        except Exception:
            pass
        if hasattr(self, 'IDC_lblSelectedCount'):
            self.IDC_lblSelectedCount.setText(f"選択中　データセット: {len(selected_items)}件 / データ: {checked_count}件")

    def update_selected_count(self):
        selected_items = self.IDC_listResults.selectedItems()
        format_text = self.IDC_comboFormat.currentText() if hasattr(self, 'IDC_comboFormat') else 'すべて'
        format_lc = format_text.lower()
        def is_format_match(res):
            if format_text == 'すべて':
                return True
            if 'format' in res and res['format']:
                fmt = res['format'].strip().lower()
                if format_lc in fmt or fmt in format_lc:
                    return True
            return False
        all_resources = []
        for item in selected_items:
            package = item.data(Qt.ItemDataRole.UserRole)
            if package is None:
                continue
            resources = package.get('resources', [])
            filtered_resources = [res for res in resources if is_format_match(res)]
            all_resources.extend(filtered_resources)
        # リソース一覧も選択変更時に必ず再表示
        self.IDC_listRessources.clear()
        for res in all_resources:
            disp = u'{}: {}'.format(res.get('format', 'no format'), res.get('url', '(no url)'))
            item = QListWidgetItem(disp)
            item.setData(Qt.ItemDataRole.UserRole, res)
            item.setCheckState(Qt.CheckState.Checked)
            self.IDC_listRessources.addItem(item)
        # Debug log to indicate this function updated the label
        try:
            self.util.msg_log_debug(u'update_selected_count: selected_datasets={0} resources_count={1}'.format(len(selected_items), len(all_resources)))
        except Exception:
            pass
        if hasattr(self, 'IDC_lblSelectedCount'):
            self.IDC_lblSelectedCount.setText(f"選択中　データセット: {len(selected_items)}件 / データ: {len(all_resources)}件")
    def _get_cache_db_path(self):
        """
        現在のCKANサーバーURLごとにキャッシュDBファイル名を分けて返す
        """
        import re, hashlib
        cache_dir = self.settings.cache_dir
        if not cache_dir or not os.path.isdir(cache_dir):
            if sys.platform == 'win32':
                from pathlib import Path
                downloads = str(Path.home() / 'Downloads')
            elif sys.platform == 'darwin':
                downloads = os.path.expanduser('~/Downloads')
            else:
                downloads = os.path.expanduser('~/Downloads')
            cache_dir = os.path.join(downloads, 'Catalog Integration')
            if not os.path.isdir(cache_dir):
                try:
                    os.makedirs(cache_dir, exist_ok=True)
                except Exception as e:
                    self.util.msg_log_error(f"キャッシュディレクトリの作成に失敗: {str(e)}")
                    # 別の場所にフォールバック
                    try:
                        temp_dir = os.path.join(os.path.expanduser('~'), 'Catalog_Integration_Cache')
                        os.makedirs(temp_dir, exist_ok=True)
                        cache_dir = temp_dir
                        self.util.msg_log_debug(f"代替キャッシュディレクトリを作成: {temp_dir}")
                    except Exception as e2:
                        self.util.msg_log_error(f"代替キャッシュディレクトリの作成にも失敗: {str(e2)}")
                        # 最終手段: 一時ディレクトリを使用
                        import tempfile
                        cache_dir = tempfile.gettempdir()
                        self.util.msg_log_debug(f"一時ディレクトリを使用: {cache_dir}")
                        
        # サーバーURLからファイル名を生成（記号を_に）
        url = getattr(self.settings, 'ckan_url', 'default')
        # URLがBoxDriveパスなど長すぎる場合はハッシュ化
        if len(url) > 100 or ('Box' in url and len(url) > 50):
            self.util.msg_log_debug(f"【BoxDrive対策】長いURLをハッシュ化: {url}")
            hash_obj = hashlib.md5(url.encode('utf-8'))
            url_hash = hash_obj.hexdigest()[:12]  # 12文字のハッシュ
            
            # 短縮化したURLの識別子を生成（最初の20文字 + ハッシュ）
            url_parts = url.split('/')
            if len(url_parts) > 2:
                url_id = f"{url_parts[-2][:10]}_{url_parts[-1][:10]}_{url_hash}"
            else:
                url_id = f"box_{url_hash}"
                
            self.util.msg_log_debug(f"【BoxDrive対策】ハッシュ化したURL ID: {url_id}")
        else:
            # 通常のURL処理: 記号を_に変換
            url_id = re.sub(r'[^a-zA-Z0-9]', '_', url)
            # 長さ制限
            if len(url_id) > 50:
                url_id = url_id[:40] + '_' + hashlib.md5(url_id.encode('utf-8')).hexdigest()[:8]
                
        db_path = os.path.join(cache_dir, f'ckan_cache_{url_id}.db')
        self.util.msg_log_debug(f"キャッシュDBパス: {db_path}")
        return db_path

    def _create_sqlite_from_local(self, local_path):
        """Create SQLite cache DB from a local folder (packages.json / packages/* or auto-generate).
        Returns (True, db_path) on success, (False, error_message) on failure.
        """
        try:
            import json, sqlite3, hashlib
            
            # キャッシュディレクトリのパスを取得
            cache_dir = os.path.dirname(self._get_cache_db_path())
            
            # JSONファイル名の生成（URLハッシュ部分を使用）
            url = getattr(self.settings, 'ckan_url', 'default')
            url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:12]
            json_prefix = f'ckan_cache_{url_hash}'
            cache_packages_path = os.path.join(cache_dir, f'{json_prefix}_packages.json')
            cache_groups_path = os.path.join(cache_dir, f'{json_prefix}_groups.json')
            
            # まずキャッシュディレクトリのJSONをチェック
            all_results = []
            if os.path.exists(cache_packages_path):
                self.util.msg_log_debug(f"キャッシュからJSONを読み込み: {cache_packages_path}")
                try:
                    with open(cache_packages_path, 'r', encoding='utf-8') as f:
                        all_results = json.load(f)
                except Exception as e:
                    self.util.msg_log_error(f"キャッシュJSONの読み込みエラー: {str(e)}")
            
            # キャッシュがない場合はローカルフォルダから読み込み試行
            if not all_results:
                pkg_json_path = os.path.join(local_path, 'packages.json')
                if os.path.exists(pkg_json_path):
                    self.util.msg_log_debug(f"ローカルフォルダからJSONを読み込み: {pkg_json_path}")
                    try:
                        with open(pkg_json_path, 'r', encoding='utf-8') as f:
                            all_results = json.load(f)
                        # キャッシュにコピー
                        with open(cache_packages_path, 'w', encoding='utf-8') as pf:
                            json.dump(all_results, pf, ensure_ascii=False, indent=2)
                        self.util.msg_log_debug(f"ローカルJSONをキャッシュにコピー: {cache_packages_path}")
                    except Exception as e:
                        self.util.msg_log_error(f"ローカルJSONの読み込みエラー: {str(e)}")
                else:
                    pkg_dir = os.path.join(local_path, 'packages')
                    if os.path.isdir(pkg_dir):
                        for fname in os.listdir(pkg_dir):
                            if fname.lower().endswith('.json'):
                                try:
                                    with open(os.path.join(pkg_dir, fname), 'r', encoding='utf-8') as f:
                                        all_results.append(json.load(f))
                                except Exception:
                                    continue
                        if all_results:
                            # キャッシュにコピー
                            with open(cache_packages_path, 'w', encoding='utf-8') as pf:
                                json.dump(all_results, pf, ensure_ascii=False, indent=2)
                            self.util.msg_log_debug(f"複数のローカルJSONをキャッシュにマージ: {cache_packages_path}")

            # auto-generate if still empty (same logic as refresh)
            if not all_results:
                # build groups from immediate subdirectories and packages per subdirectory
                # 除外ファイル・フォルダのリスト（メタデータファイルや一般的なシステムファイル）
                exclude_names = {
                    'packages.json', 'groups.json', 'thumbs.db', 'desktop.ini', '.ds_store',
                    '__pycache__', '.git', '.svn', 'node_modules', '.tmp', 'temp'
                }
                exclude_extensions = {
                    '.tmp', '.temp', '.bak', '.log', '.cache', '.lock', '.swp', '.swo',
                    '.exe', '.dll', '.so', '.dylib', '.app', '.deb', '.rpm', '.msi'
                }
                
                def _should_include_file(filename, filepath):
                    """
                    ファイルをデータベースに含めるかどうかを判定
                    除外対象以外のすべてのファイルを含める（拡張子制限なし）
                    """
                    fname_lower = filename.lower()
                    ext_lower = os.path.splitext(filename)[1].lower()
                    
                    # 除外ファイル名（完全一致）
                    if fname_lower in exclude_names:
                        return False
                    
                    # 除外拡張子
                    if ext_lower in exclude_extensions:
                        return False
                    
                    # 隠しファイル（Unix系）
                    if filename.startswith('.') and len(filename) > 1:
                        return False
                    
                    # 一時ファイル
                    if filename.startswith('~') or filename.endswith('~'):
                        return False
                    
                    # 空ファイルは除外（0バイト）
                    try:
                        if os.path.getsize(filepath) == 0:
                            return False
                    except:
                        pass
                    
                    return True
                
                generated_pkgs = []
                generated_groups = []
                # immediate subdirectories -> groups
                try:
                    for name in os.listdir(local_path):
                        p = os.path.join(local_path, name)
                        if os.path.isdir(p):
                            grp = {'id': name, 'name': name, 'title': name, 'description': ''}
                            generated_groups.append(grp)
                            # collect data files under this subdir (recursively)
                            i = 1
                            resources = []
                            for root, dirs, files in os.walk(p):
                                for fname in files:
                                    filepath = os.path.join(root, fname)
                                    if _should_include_file(fname, filepath):
                                        ext = os.path.splitext(fname)[1].lower().lstrip('.') or 'file'
                                        file_url = 'file:///' + os.path.abspath(filepath).replace('\\', '/')
                                        resources.append({'id': f'{name}-res-{i}', 'name': fname, 'format': ext, 'url': file_url})
                                        i += 1
                            if resources:
                                pkg = {'id': f'local-package-{name}', 'title': name, 'resources': resources, 'groups': [{'name': name}]}
                                generated_pkgs.append(pkg)
                except Exception:
                    pass

                # root-level files -> a package
                try:
                    root_resources = []
                    j = 1
                    for fname in os.listdir(local_path):
                        filepath = os.path.join(local_path, fname)
                        if os.path.isfile(filepath):
                            if _should_include_file(fname, filepath):
                                ext = os.path.splitext(fname)[1].lower().lstrip('.') or 'file'
                                file_url = 'file:///' + os.path.abspath(filepath).replace('\\', '/')
                                root_resources.append({'id': f'root-res-{j}', 'name': fname, 'format': ext, 'url': file_url})
                                j += 1
                    if root_resources:
                        pkg_root = {'id': 'local-package-root', 'title': os.path.basename(local_path) or 'local-package', 'resources': root_resources}
                        generated_pkgs.insert(0, pkg_root)
                except Exception:
                    pass

                if generated_pkgs:
                    all_results = generated_pkgs
                    # persist packages.json to cache directory
                    try:
                        cache_packages_path = os.path.join(cache_dir, f'{json_prefix}_packages.json')
                        with open(cache_packages_path, 'w', encoding='utf-8') as pf:
                            json.dump(all_results, pf, ensure_ascii=False, indent=2)
                        self.util.msg_log_debug(f"JSONキャッシュ作成: {cache_packages_path}")
                    except Exception as e:
                        self.util.msg_log_error(f"JSONキャッシュ作成失敗: {str(e)}")
                        pass
                    # persist groups.json to cache directory
                    try:
                        cache_groups_path = os.path.join(cache_dir, f'{json_prefix}_groups.json')
                        if generated_groups:
                            with open(cache_groups_path, 'w', encoding='utf-8') as gf:
                                json.dump(generated_groups, gf, ensure_ascii=False, indent=2)
                            self.util.msg_log_debug(f"グループJSONキャッシュ作成: {cache_groups_path}")
                        # set group_result so it will be saved to DB below
                        group_result = generated_groups
                    except Exception as e:
                        self.util.msg_log_error(f"グループJSONキャッシュ作成失敗: {str(e)}")
                        pass

            if not all_results:
                # No packages found: create an empty packages.json in cache dir to avoid errors and
                # continue to create an empty cache DB (tables will be created, no rows).
                try:
                    cache_packages_path = os.path.join(cache_dir, f'{json_prefix}_packages.json')
                    with open(cache_packages_path, 'w', encoding='utf-8') as pf:
                        json.dump([], pf, ensure_ascii=False, indent=2)
                    self.util.msg_log_debug(f"空のJSONキャッシュ作成: {cache_packages_path}")
                except Exception as e:
                    self.util.msg_log_error(f"空のJSONキャッシュ作成失敗: {str(e)}")
                    pass
                # keep all_results as empty list and continue to create DB

            db_path = self._get_cache_db_path()
            from .save_ckan_to_sqlite import save_ckan_packages_to_sqlite
            save_ckan_packages_to_sqlite(db_path, all_results)

            # groups
            groups_path = os.path.join(local_path, 'groups.json')
            # If group_result was generated above, keep it; otherwise try to load from groups.json
            if 'group_result' not in locals() or not group_result:
                group_result = []
                if os.path.exists(groups_path):
                    try:
                        with open(groups_path, 'r', encoding='utf-8') as f:
                            group_result = json.load(f)
                    except Exception:
                        group_result = []

            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS groups (raw_json TEXT)''')
            c.execute('DELETE FROM groups')
            for group in group_result:
                c.execute('INSERT INTO groups (raw_json) VALUES (?)', (json.dumps(group),))
            conn.commit()
            conn.close()
            # If no packages were found, inform the user that an empty index was created
            if not all_results:
                try:
                    self.util.dlg_information(self.util.tr('py_dlg_set_info_empty_local_created').format(local_path))
                except Exception:
                    pass
            return True, db_path
        except Exception as e:
            return False, str(e)

    def refresh_sqlite_clicked(self):
        """
        全データセットを再取得しSQLiteキャッシュを再作成する（CKAN APIのstartパラメータでページング取得）
        """
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # 1. APIからカテゴリ取得
            # determine if current server is LOCAL type
            server_url = getattr(self.settings, 'ckan_url', '')
            server_is_local = False
            try:
                # if url corresponds to a custom server entry with type LOCAL, mark as local
                for name, info in self.settings.custom_servers.items():
                    if isinstance(info, dict) and info.get('url'):
                        if info.get('url') == server_url and info.get('type') == 'LOCAL':
                            server_is_local = True
                            local_path = info.get('url')
                            break
                # also accept local paths directly stored in ckan_url
                import os
                if not server_is_local:
                    # support local:// and file:// schemes and plain directory paths
                    try:
                        if server_url.startswith('local://'):
                            local_path = server_url[len('local://'):]
                            if os.path.isdir(local_path):
                                server_is_local = True
                        elif server_url.startswith('file://'):
                            from urllib.parse import urlparse
                            parsed = urlparse(server_url)
                            try:
                                from urllib.request import url2pathname
                                p = url2pathname(parsed.path)
                                if parsed.netloc:
                                    local_path = os.path.abspath('//' + parsed.netloc + p)
                                else:
                                    if p.startswith('/') and len(p) > 2 and p[2] == ':':
                                        p = p.lstrip('/')
                                    local_path = os.path.abspath(p)
                                if os.path.isdir(local_path):
                                    server_is_local = True
                            except Exception:
                                local_path = os.path.abspath(os.path.join(parsed.netloc, parsed.path))
                                if os.path.isdir(local_path):
                                    server_is_local = True
                        elif os.path.isdir(server_url):
                            server_is_local = True
                            local_path = server_url
                    except Exception:
                        server_is_local = False
            except Exception:
                server_is_local = False

            if server_is_local:
                # Read local groups and packages from files
                try:
                    import json
                    import sqlite3
                    all_results = []
                    group_result = []
                    # Prefer a single root-level packages.json file. Do not aggregate packages/*.json
                    pkg_json_path = os.path.join(local_path, 'packages.json')
                    if os.path.exists(pkg_json_path):
                        try:
                            with open(pkg_json_path, 'r', encoding='utf-8') as f:
                                all_results = json.load(f)
                        except Exception:
                            all_results = []

                    # If still empty, try to auto-generate packages.json from files in folder
                    def _auto_generate_packages_from_folder(folder):
                        """Create packages.json by creating package entries for data files.
                        For each immediate subdirectory, create a group and a package containing
                        all data files under that subdirectory (recursively). Also collect
                        root-level data files into a single package.
                        Returns (pkgs, groups) where groups is a list of group dicts.
                        Excludes generated metadata files (packages.json, groups.json)
                        from being treated as data resources to avoid self-reference.
                        """
                        pkgs = []
                        groups = []
                        # 除外ファイル・フォルダのリスト（メタデータファイルや一般的なシステムファイル）
                        exclude_names = {
                            'packages.json', 'groups.json', 'thumbs.db', 'desktop.ini', '.ds_store',
                            '__pycache__', '.git', '.svn', 'node_modules', '.tmp', 'temp'
                        }
                        exclude_extensions = {
                            '.tmp', '.temp', '.bak', '.log', '.cache', '.lock', '.swp', '.swo',
                            '.exe', '.dll', '.so', '.dylib', '.app', '.deb', '.rpm', '.msi'
                        }
                        
                        def _should_include_file_refresh(filename, filepath):
                            """
                            ファイルをデータベースに含めるかどうかを判定（refresh用）
                            除外対象以外のすべてのファイルを含める（拡張子制限なし）
                            """
                            fname_lower = filename.lower()
                            ext_lower = os.path.splitext(filename)[1].lower()
                            
                            # 除外ファイル名（完全一致）
                            if fname_lower in exclude_names:
                                return False
                            
                            # 除外拡張子
                            if ext_lower in exclude_extensions:
                                return False
                            
                            # 隠しファイル（Unix系）
                            if filename.startswith('.') and len(filename) > 1:
                                return False
                            
                            # 一時ファイル
                            if filename.startswith('~') or filename.endswith('~'):
                                return False
                            
                            # 空ファイルは除外（0バイト）
                            try:
                                if os.path.getsize(filepath) == 0:
                                    return False
                            except:
                                pass
                            
                            return True
                        
                        # immediate subdirectories -> groups and packages
                        try:
                            for name in os.listdir(folder):
                                p = os.path.join(folder, name)
                                if os.path.isdir(p):
                                    grp = {'id': name, 'name': name, 'title': name, 'description': ''}
                                    groups.append(grp)
                                    i = 1
                                    resources = []
                                    for root, dirs, files in os.walk(p):
                                        for fname in files:
                                            filepath = os.path.join(root, fname)
                                            if _should_include_file_refresh(fname, filepath):
                                                ext = os.path.splitext(fname)[1].lower().lstrip('.') or 'file'
                                                file_url = 'file:///' + os.path.abspath(filepath).replace('\\', '/')
                                                resources.append({'id': f'{name}-res-{i}', 'name': fname, 'format': ext, 'url': file_url})
                                                i += 1
                                    if resources:
                                        pkg = {'id': f'local-package-{name}', 'title': name, 'resources': resources, 'groups': [{'name': name}]}
                                        pkgs.append(pkg)
                        except Exception:
                            pass

                        # root-level files -> a package
                        try:
                            root_resources = []
                            j = 1
                            for fname in os.listdir(folder):
                                filepath = os.path.join(folder, fname)
                                if os.path.isfile(filepath):
                                    if _should_include_file_refresh(fname, filepath):
                                        ext = os.path.splitext(fname)[1].lower().lstrip('.') or 'file'
                                        file_url = 'file:///' + os.path.abspath(filepath).replace('\\', '/')
                                        root_resources.append({'id': f'root-res-{j}', 'name': fname, 'format': ext, 'url': file_url})
                                        j += 1
                            if root_resources:
                                pkg_root = {'id': 'local-package-root', 'title': os.path.basename(folder) or 'local-package', 'resources': root_resources}
                                pkgs.insert(0, pkg_root)
                        except Exception:
                            pass

                        return pkgs, groups

                    # キャッシュディレクトリとJSONファイル名を設定
                    cache_dir = os.path.dirname(self._get_cache_db_path())
                    import hashlib
                    local_path_hash = hashlib.md5(local_path.encode('utf-8')).hexdigest()[:12]
                    url_hash = local_path_hash
                    json_prefix = f'ckan_cache_{url_hash}'
                    cache_packages_path = os.path.join(cache_dir, f'{json_prefix}_packages.json')
                    cache_groups_path = os.path.join(cache_dir, f'{json_prefix}_groups.json')
                    
                    # Always attempt to auto-generate packages/groups from the local folder
                    generated = []
                    generated_groups = []
                    try:
                        generated_pkgs, generated_groups = _auto_generate_packages_from_folder(local_path)
                        if generated_pkgs:
                            all_results = generated_pkgs
                            # persist packages.json to cache (overwrite every refresh)
                            try:
                                with open(cache_packages_path, 'w', encoding='utf-8') as pf:
                                    json.dump(all_results, pf, ensure_ascii=False, indent=2)
                                self.util.msg_log_debug(f"JSONキャッシュ更新: {cache_packages_path}")
                            except Exception as e:
                                self.util.msg_log_error(f"JSONキャッシュ更新失敗: {str(e)}")
                                pass
                    except Exception:
                        generated_pkgs = []
                        generated_groups = []
                    
                    # If we generated groups during auto-generation, save to cache
                    if 'generated_groups' in locals() and generated_groups:
                        try:
                            with open(cache_groups_path, 'w', encoding='utf-8') as gf:
                                json.dump(generated_groups, gf, ensure_ascii=False, indent=2)
                            group_result = generated_groups
                            self.util.msg_log_debug(f"グループJSONキャッシュ更新: {cache_groups_path}")
                        except Exception as e:
                            self.util.msg_log_error(f"グループJSONキャッシュ更新失敗: {str(e)}")
                            group_result = generated_groups
                    else:
                        # キャッシュからグループ情報を読み込む
                        if os.path.exists(cache_groups_path):
                            try:
                                with open(cache_groups_path, 'r', encoding='utf-8') as f:
                                    group_result = json.load(f)
                                self.util.msg_log_debug(f"グループJSONキャッシュを読み込み: {cache_groups_path}")
                            except Exception as e:
                                self.util.msg_log_error(f"グループJSONキャッシュ読み込み失敗: {str(e)}")
                                group_result = []
                        else:
                            # キャッシュがない場合はローカルのgroups.jsonを確認
                            groups_path = os.path.join(local_path, 'groups.json')
                            if os.path.exists(groups_path):
                                try:
                                    with open(groups_path, 'r', encoding='utf-8') as f:
                                        group_result = json.load(f)
                                    # キャッシュにコピー
                                    with open(cache_groups_path, 'w', encoding='utf-8') as gf:
                                        json.dump(group_result, gf, ensure_ascii=False, indent=2)
                                    self.util.msg_log_debug(f"ローカルグループJSONをキャッシュにコピー: {cache_groups_path}")
                                except Exception:
                                    group_result = []
                            else:
                                group_result = []
                    # save to sqlite
                    if all_results:
                        db_path = self._get_cache_db_path()
                        from .save_ckan_to_sqlite import save_ckan_packages_to_sqlite
                        save_ckan_packages_to_sqlite(db_path, all_results)
                        conn = sqlite3.connect(db_path)
                        c = conn.cursor()
                        c.execute('''CREATE TABLE IF NOT EXISTS groups (raw_json TEXT)''')
                        c.execute('DELETE FROM groups')
                        for group in group_result:
                            c.execute('INSERT INTO groups (raw_json) VALUES (?)', (json.dumps(group),))
                        conn.commit()
                        conn.close()
                        self.update_format_list(all_results)
                        self.list_all_clicked()
                        self.window_loaded()
                        return
                    else:
                        # No generated packages: create empty packages.json in cache and proceed to create an empty DB
                        try:
                            with open(cache_packages_path, 'w', encoding='utf-8') as pf:
                                json.dump([], pf, ensure_ascii=False, indent=2)
                            self.util.msg_log_debug(f"空のJSONキャッシュ作成: {cache_packages_path}")
                        except Exception as e:
                            self.util.msg_log_error(f"空のJSONキャッシュ作成失敗: {str(e)}")
                            pass
                        # inform the user that an empty index was created
                        try:
                            self.util.dlg_information(self.util.tr('py_dlg_set_info_empty_local_created').format(local_path))
                        except Exception:
                            pass
                        # continue with empty all_results to create empty DB (save_ckan_packages_to_sqlite will create tables)
                except Exception as e:
                    QApplication.restoreOverrideCursor()
                    error_msg = str(e)
                    
                    # BOXドライブの場合の特別処理
                    is_box_drive = False
                    if 'Box' in local_path or 'Box Drive' in local_path:
                        is_box_drive = True
                    
                    if is_box_drive:
                        # BOXドライブ用のエラーメッセージを表示
                        self.util.dlg_warning(self.util.tr('py_dlg_set_info_local_read_error_boxdrive').format(error_msg))
                    else:
                        # 通常のエラーメッセージ
                        self.util.dlg_warning(self.util.tr('py_dlg_set_info_local_read_error').format(error_msg))
                    return

            # 1. APIからカテゴリ取得
            ok, group_result = self.cc.get_groups()
            if ok is False:
                QApplication.restoreOverrideCursor()
                self.util.dlg_warning(group_result)
                return
            if not group_result:
                self.list_all_clicked()
                return
            # 2. ページングで全件取得
            from qgis.PyQt.QtWidgets import QProgressDialog
            rows_per_page = 1000
            start = 0
            all_results = []
            total_count = None
            page = 1
            progress = None
            while True:
                ok, page_result = self.cc.package_search('', None, None, rows=rows_per_page, start=start)
                if not ok or 'results' not in page_result:
                    break
                results = page_result['results']
                if total_count is None:
                    total_count = page_result.get('count', 0)
                    max_page = (total_count + rows_per_page - 1) // rows_per_page
                    progress = QProgressDialog(self.util.tr('CKAN全件取得中...'), self.util.tr('キャンセル'), 0, max_page, self)
                    progress.setWindowTitle(self.util.tr('進捗'))
                    progress.setWindowModality(Qt.WindowModality.WindowModal)
                    progress.setMinimumDuration(0)
                    progress.setValue(0)
                if not results:
                    break
                all_results.extend(results)
                if progress:
                    progress.setValue(page)
                    progress.setLabelText(self.util.tr('CKAN全件取得中... ({}/{})').format(page, max_page))
                    titles = [entry.get('title', 'no title') for entry in results]
                    try:
                        from qgis.core import QgsMessageLog, Qgis
                        QgsMessageLog.logMessage(f"取得データセット（ページ{page}）: {titles}", self.util.dlg_caption, Qgis.Info)
                    except Exception:
                        pass
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        break
                if len(all_results) >= total_count:
                    break
                if progress and progress.wasCanceled():
                    break
                page += 1
                start += rows_per_page
            if progress:
                progress.setValue(max_page)
                progress.close()
            if all_results:
                from qgis.core import QgsMessageLog, Qgis
                try:
                    import sqlite3, json
                    db_path = self._get_cache_db_path()
                    QgsMessageLog.logMessage(self.util.tr(u"Caching data to SQLite has started."), self.util.dlg_caption, Qgis.Info)
                    # --- パッケージ保存 ---
                    from .save_ckan_to_sqlite import save_ckan_packages_to_sqlite
                    save_ckan_packages_to_sqlite(db_path, all_results)
                    # --- カテゴリリストも保存 ---
                    conn = sqlite3.connect(db_path)
                    c = conn.cursor()
                    c.execute('''CREATE TABLE IF NOT EXISTS groups (raw_json TEXT)''')
                    c.execute('DELETE FROM groups')
                    for group in group_result:
                        c.execute('INSERT INTO groups (raw_json) VALUES (?)', (json.dumps(group),))
                    conn.commit()
                    conn.close()
                    QgsMessageLog.logMessage(self.util.tr(u"Caching data to SQLite has finished."), self.util.dlg_caption, Qgis.Info)
                    self.util.msg_log_debug(self.util.tr(u"Saved {} records to SQLite DB: {}.").format(len(all_results), db_path))
                except Exception as e:
                    QgsMessageLog.logMessage(self.util.tr(u"SQLite save error: {}".format(e)), self.util.dlg_caption, Qgis.Critical)
                    self.util.msg_log_error(self.util.tr(u"SQLite save error: {}".format(e)))
                self.update_format_list(all_results)
                self.list_all_clicked()
                self.window_loaded()  # カテゴリ一覧を再表示
        finally:
            QApplication.restoreOverrideCursor()


    def showEvent(self, event):
        self.util.msg_log_debug('showevent')
        QDialog.showEvent(self, event)
        if self.timer is not None:
            self.timer.start(500)
        self.util.msg_log_debug('showevent finished')

    def window_loaded(self):
        try:
            self.settings.load()
            self.IDC_lblApiUrl.setText(self.util.tr('Current server: {0}').format(self.settings.ckan_url))
            self.IDC_lblCacheDir.setText(self.util.tr('Cache path: {0}').format(self.settings.cache_dir))
            if self.timer is not None:
                self.timer.stop()
                self.timer = None

            self.IDC_listResults.clear()
            self.IDC_listGroup.clear()
            self.IDC_textDetails.setText('')
            self.IDC_listRessources.clear()
            self.IDC_plainTextLink.setPlainText('')

            self.util.msg_log_debug('before get_groups')

            # --- カテゴリリストをSQLiteから取得 ---
            import sqlite3, json
            db_path = self._get_cache_db_path()
            all_results = []
            # determine if current server is a local folder and get path
            local_path = None
            try:
                server_url = getattr(self.settings, 'ckan_url', '')
                for name, info in self.settings.custom_servers.items():
                    if isinstance(info, dict) and info.get('url') == server_url and info.get('type') == 'LOCAL':
                        local_path = info.get('url')
                        break
                if not local_path:
                    if server_url.startswith('local://'):
                        local_path = server_url[len('local://'):]
                    elif server_url.startswith('file://'):
                        from urllib.parse import urlparse
                        parsed = urlparse(server_url)
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
                            local_path = os.path.abspath(os.path.join(parsed.netloc, parsed.path))
                    elif os.path.isdir(server_url):
                        local_path = server_url
            except Exception:
                local_path = None

            def _read_db_and_fill(db_path_local):
                res_list = []
                try:
                    conn = sqlite3.connect(db_path_local)
                    c = conn.cursor()
                    # カテゴリリスト取得
                    c.execute('SELECT raw_json FROM groups')
                    group_rows = c.fetchall()
                    if not group_rows:
                        self.util.msg_log_debug("DB groups table is empty - グループ情報なしで続行")
                    else:
                        from qgis.PyQt.QtCore import Qt
                        from qgis.PyQt.QtWidgets import QListWidgetItem
                        for row in group_rows:
                            group = json.loads(row[0])
                            title = group.get('title') or group.get('name', '')
                            self.util.msg_log_debug(f'Add group: {title}')
                            item = QListWidgetItem(title)
                            item.setData(Qt.ItemDataRole.UserRole, group)
                            item.setCheckState(Qt.CheckState.Unchecked)
                            self.IDC_listGroup.addItem(item)
                    # パッケージ一覧取得
                    c.execute('SELECT raw_json FROM packages')
                    rows = c.fetchall()
                    for row in rows:
                        entry = json.loads(row[0])
                        res_list.append(entry)
                    conn.close()
                    return True, res_list
                except Exception as e:
                    self.util.msg_log_error(f"DB read error: {e}")
                    return False, str(e)

            ok, result = _read_db_and_fill(db_path)
            if ok:
                all_results = result
            else:
                # try to auto-create DB from local folder if available
                if local_path:
                    created, msg = self._create_sqlite_from_local(local_path)
                    if created:
                        # re-read db
                        ok2, result2 = _read_db_and_fill(db_path)
                        if ok2:
                            all_results = result2
                        else:
                            all_results = None
                    else:
                        self.util.msg_log_error(f"Failed to create DB from local: {msg}")
                        all_results = None
                else:
                    all_results = None
            self.update_format_list(all_results)
            # 起動時に必ず検索結果を表示
            self.list_all_clicked()
        except Exception as e:
            self.util.msg_log_error(f"window_loaded error: {e}")
            self.util.dlg_warning(f"起動時エラー: {e}")
        finally:
            QApplication.restoreOverrideCursor()

    def close_dlg(self):
        QDialog.reject(self)

    def show_disclaimer(self):
        self.dlg_disclaimer = GeoImportDialogDisclaimer(self.settings)
        self.dlg_disclaimer.show()

    def searchtextchanged(self, search_txt):
        self.search_txt = search_txt

    def suchen(self):
        self.current_page = 1
        self.current_group = None
        self.__search_package()

    def list_all_clicked(self):
        self.current_page = 1
        self.current_group = None
        # don't hint on wildcards, empty text works as well, as CKAN uses *:* as
        # default when ?q= has not text
        # self.IDC_lineSearch.setText('*:*')
        self.IDC_lineSearch.setText('')
        self.__search_package()

    def category_item_clicked(self, item):
        self.util.msg_log_debug(item.data(Qt.ItemDataRole.UserRole)['name'])
        self.current_group = item.data(Qt.ItemDataRole.UserRole)['name']
        self.current_page = 1
        self.__search_package()

    def select_data_provider_clicked(self):
        self.util.msg_log_debug('select data provider clicked')
        self.dlg_dataproviders = GeoImportDialogDataProviders(self.settings)
        self.dlg_dataproviders.show()
        if self.dlg_dataproviders.exec():
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.window_loaded()

    def __search_package(self, page=None):
        self.IDC_listResults.clear()
        # ページング制御
        if page is not None:
            self.util.msg_log_debug(u'page is not None, cp:{0} pg:{1}'.format(self.current_page, page))
            self.current_page = self.current_page + page
            if self.current_page < 1:
                self.current_page = 1
            if self.current_page > self.page_count:
                self.current_page = self.page_count
            self.util.msg_log_debug(u'page is not None, cp:{0} pg:{1}'.format(self.current_page, page))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        db_path = self._get_cache_db_path()
        format_text = self.IDC_comboFormat.currentText() if hasattr(self, 'IDC_comboFormat') else 'すべて'
        format_lc = format_text.lower()
        results_limit = getattr(self.settings, 'results_limit', 50)
        # カテゴリ（グループ）フィルタを取得
        group_names = self.__get_selected_groups()
        # QThreadでデータ取得
        self.data_thread = DataFetchThread(db_path, format_text, format_lc, self.current_page, results_limit, self.search_txt, group_names)
        self.data_thread.result_ready.connect(self._on_data_ready)
        self.data_thread.start()

    def _on_data_ready(self, page_results, result_count, page_count, total_resource_count):
        QApplication.restoreOverrideCursor()
        self.result_count = result_count
        self.page_count = page_count
        # 全検索結果分のリソース数を表示
        erg_text = f"検索結果　データセット: {self.result_count}件 / データ: {total_resource_count}件"
        self.util.msg_log_debug(erg_text)
        page_text = self.util.tr(u'py_dlg_base_page_count').format(self.current_page, self.page_count)
        self.IDC_lblSuchergebnisse.setText(erg_text)
        self.IDC_lblPage.setText(page_text)
        self.IDC_listResults.clear()
        for entry in page_results:
            title_txt = u'no title available'
            if 'title' not in entry:
                continue
            e = entry['title']
            if e is None:
                title_txt = 'no title'
            elif isinstance(e, dict):
                title_txt = next(iter(list(e.values())))
            elif isinstance(e, list):
                title_txt = e[0]
            else:
                title_txt = e
            item = QListWidgetItem(title_txt)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.IDC_listResults.addItem(item)

    def list_group_item_changed(self, item):
        # カテゴリのチェック状態変更時に再検索を実行
        self.__search_package()

    def resultitemchanged(self, current, previous):
        # 選択データセット変更時、詳細はcurrentのみ、リソースはselected_itemsベースで再表示
        self.IDC_textDetails.setText('')
        self.IDC_listRessources.clear()
        self.IDC_plainTextLink.clear()
        format_text = self.IDC_comboFormat.currentText() if hasattr(self, 'IDC_comboFormat') else 'すべて'
        format_lc = format_text.lower()
        def is_format_match(res):
            if format_text == 'すべて':
                return True
            if 'format' in res and res['format']:
                fmt = res['format'].strip().lower()
                if format_lc in fmt or fmt in format_lc:
                    return True
            return False
        # 詳細情報はcurrentのみ
        if current is not None:
            package = current.data(Qt.ItemDataRole.UserRole)
            if package is not None:
                org = package.get('organization', {})
                org_name = org.get('title') or org.get('name') or 'no organization'
                org_desc = org.get('description', '') if isinstance(org, dict) else ''
                details_text = (
                    u'{0}\n\nOrganization: {1}\n{2}\n\nAuthor: {3} <{4}>\nMaintainer: {5} <{6}>\n\nLicense: {7}'.format(
                        package.get('notes', 'no notes'),
                        org_name,
                        org_desc,
                        package.get('author', 'no author'),
                        package.get('author_email', 'no author_email'),
                        package.get('maintainer', 'no maintainer'),
                        package.get('maintainer_email', 'no maintainer_email'),
                        package.get('license_id', 'no license_id')
                    )
                )
                self.IDC_textDetails.setText(details_text)
        # リソース一覧は選択状態に応じて毎回再構築（selected_itemsベースで統一）
        selected_items = self.IDC_listResults.selectedItems()
        all_resources = []
        for item in selected_items:
            package = item.data(Qt.ItemDataRole.UserRole)
            if package is None:
                continue
            resources = package.get('resources', [])
            filtered_resources = [res for res in resources if is_format_match(res)]
            all_resources.extend(filtered_resources)
        for res in all_resources:
            disp = u'{}: {}'.format(res.get('format', 'no format'), res.get('url', '(no url)'))
            item = QListWidgetItem(disp)
            item.setData(Qt.ItemDataRole.UserRole, res)
            item.setCheckState(Qt.CheckState.Checked)
            self.IDC_listRessources.addItem(item)
        # 選択数（データセット数・リソース数）を表示
        if hasattr(self, 'IDC_lblSelectedCount'):
            sel_count = len(selected_items)
            self.IDC_lblSelectedCount.setText(f"選択中　データセット: {sel_count}件 / データ: {len(all_resources)}件")

    def resource_item_changed(self, new_item):
        if new_item is None:
            return
        url = new_item.data(Qt.ItemDataRole.UserRole)['url']
        self.util.msg_log_debug(url)
        self.__fill_link_box(url)

    def load_resource_clicked(self):
        # シンプルに、UI上に表示されているリソース一覧を基準にダウンロード対象を決定する
        if not hasattr(self, 'IDC_listRessources'):
            self.util.dlg_warning(self.util.tr(u'py_dlg_base_warn_no_resource'))
            return

        # チェックされたリソースのみを対象とする（チェックが無ければ何もしない）
        checked_list = self.__get_selected_resources()
        if not checked_list:
            self.util.dlg_warning(self.util.tr(u'py_dlg_base_warn_no_resource'))
            return
        all_resources = checked_list

        # 結果リスト全体からパッケージマップを作成して、各リソースに _package_id を付与する（単純化）
        package_map = {}
        for idx in range(self.IDC_listResults.count()):
            itm = self.IDC_listResults.item(idx)
            pkg = itm.data(Qt.ItemDataRole.UserRole)
            if pkg and 'id' in pkg:
                package_map[pkg['id']] = pkg

        first_pkg_id = next(iter(package_map.keys()), None)
        for res in all_resources:
            if res.get('_package_id'):
                continue
            found = False
            for pid, pkg in package_map.items():
                for r in pkg.get('resources', []):
                    if (res.get('id') and r.get('id') and res.get('id') == r.get('id')) or \
                       (res.get('url') and r.get('url') and res.get('url') == r.get('url')) or \
                       (res.get('name') and r.get('name') and res.get('name') == r.get('name')):
                        res['_package_id'] = pid
                        found = True
                        break
                if found:
                    break
            if not found and first_pkg_id:
                res['_package_id'] = first_pkg_id

        # --- ここからダイアログ抑制用フラグ ---
        # 既存ファイル上書き確認ダイアログの選択（1回目だけ表示、以降は自動適用）
        already_loaded_dialog_answer = None
        # 大容量ファイル警告ダイアログの選択（1回目だけ表示、以降は自動適用）
        bigfile_dialog_answer = None
        # ZIP展開失敗時のダイアログ選択（1回目だけ表示、以降は自動適用）
        extract_dialog_answer = None
        # レイヤ追加失敗時のマネージャで開くか確認ダイアログ選択（1回目だけ表示、以降は自動適用）
        addlayer_dialog_answer = None

        # XMLファイル統合処理のセッションは、XMLと判定されるリソースがある場合のみ開始
        xml_candidates = [r for r in all_resources if (r.get('format') and r.get('format').lower() == 'xml') or (r.get('url') and r.get('url').lower().endswith('.xml'))]
        xml_session_started = False
        if xml_candidates:
            session_name = f"bulk_load_{len(xml_candidates)}_xml_resources"
            self.util.start_xml_collection_session(session_name)
            xml_session_started = True

        for resource in all_resources:
            # パッケージIDからpackage情報取得
            package_id = resource.get('_package_id')
            package = package_map.get(package_id)
            if package is None:
                continue
            if resource['name'] is None:
                resource['name'] = "Unnamed resource"
            self.util.msg_log_debug(u'Bearbeite: {0}'.format(resource['name']))
            # Build readable folder names: <server>_<urlid>/<safe_title>_<package_id>/<safe_name>_<resource_id>
            pkg_title = package.get('title') or package.get('name') or package.get('id')
            res_name = resource.get('name') or resource.get('title') or resource.get('id')
            safe_pkg = self.util.safe_filename(pkg_title, fallback=package.get('id'))
            safe_res = self.util.safe_filename(res_name, fallback=resource.get('id'))

            # Derive server folder from current CKAN API URL
            server_url = getattr(self.settings, 'ckan_url', '') or 'default'
            try:
                from urllib.parse import urlparse
                parsed = urlparse(server_url)
                host = parsed.netloc or parsed.path or server_url
            except Exception:
                host = server_url
            import hashlib
            # create a short stable hash from the full server URL to avoid collisions
            url_hash = hashlib.sha1(server_url.encode('utf-8')).hexdigest()[:8]
            safe_host = self.util.safe_filename(host, fallback='server')
            server_dir = f"{safe_host}_{url_hash}"
            # debug log to help diagnose server folder generation
            try:
                self.util.msg_log_debug(f'server_url={server_url} host={host} server_dir={server_dir} url_hash={url_hash}')
            except Exception:
                pass

            dest_dir = os.path.join(
                self.settings.cache_dir,
                server_dir,
                f"{safe_pkg}_{package['id']}",
                f"{safe_res}_{resource['id']}"
            )
            if self.util.create_dir(dest_dir) is False:
                self.util.dlg_warning(self.util.tr(u'py_dlg_base_warn_cache_dir_not_created').format(dest_dir))
                return
            dest_file = os.path.join(dest_dir, os.path.split(resource['url'])[1])
            format_lower = resource['format'].lower()
            url_val = resource.get('url', '').strip()
            # XYZ形式の場合はURLが空でなく、http/httpsで始まり、{z}/{x}/{y}を含む場合のみ直接追加
            if format_lower == 'xyz' and url_val and (url_val.startswith('http://') or url_val.startswith('https://')) and ('{z}' in url_val and '{x}' in url_val and '{y}' in url_val):
                try:
                    from qgis.core import QgsRasterLayer, QgsProject
                    xyz_src = f'type=xyz&url={url_val}'
                    xyz_layer = QgsRasterLayer(xyz_src, resource['name'], 'wms')
                    if xyz_layer.isValid():
                        QgsProject.instance().addMapLayer(xyz_layer)
                        self.util.msg_log_debug(f'XYZ layer added: {url_val}')
                    else:
                        self.util.dlg_warning(self.util.tr(u'py_dlg_base_lyr_not_loaded').format(resource['name'], 'XYZ layer invalid'))
                except Exception as e:
                    self.util.dlg_warning(self.util.tr(u'py_dlg_base_lyr_not_loaded').format(resource['name'], str(e)))
                continue
            # 通常のダウンロード・追加処理
            if format_lower == 'wms':
                # WMSの場合はGetCapabilitiesで情報取得し、最初のレイヤ名でQGISにレイヤ追加
                try:
                    import requests
                    from xml.etree import ElementTree as ET
                    wms_url = url_val
                    if not wms_url.lower().endswith('?'):
                        if '?' in wms_url:
                            wms_url += '&'
                        else:
                            wms_url += '?'
                    getcap_url = wms_url + 'SERVICE=WMS&REQUEST=GetCapabilities'
                    resp = requests.get(getcap_url, timeout=10)
                    if resp.status_code == 200:
                        # レイヤ名を取得
                        try:
                            root = ET.fromstring(resp.content)
                            ns = {'wms': 'http://www.opengis.net/wms'}
                            # WMS 1.3.0/1.1.1両対応
                            # --- 最下層のLayer Nameを再帰的に取得 ---
                            def find_leaf_layer_names(elem):
                                ns_wms = '{http://www.opengis.net/wms}'
                                result = []
                                # 子Layerを取得
                                children = elem.findall(f'{ns_wms}Layer')
                                if not children:
                                    children = elem.findall('Layer')
                                if children:
                                    for child in children:
                                        result.extend(find_leaf_layer_names(child))
                                else:
                                    # 子LayerがなければこのLayerがleaf
                                    name_elem = elem.find(f'{ns_wms}Name')
                                    if name_elem is None:
                                        name_elem = elem.find('Name')
                                    if name_elem is not None and name_elem.text:
                                        result.append(name_elem.text)
                                return result

                            # ルートからCapability/Layerを探す
                            cap_layer = None
                            ns_wms = '{http://www.opengis.net/wms}'
                            cap = root.find(f'{ns_wms}Capability')
                            if cap is None:
                                cap = root.find('Capability')
                            if cap is not None:
                                cap_layer = cap.find(f'{ns_wms}Layer')
                                if cap_layer is None:
                                    cap_layer = cap.find('Layer')
                            leaf_names = []
                            if cap_layer is not None:
                                leaf_names = find_leaf_layer_names(cap_layer)
                            if not leaf_names:
                                # fallback: 旧方式
                                layer_elems = root.findall('.//{http://www.opengis.net/wms}Layer')
                                if not layer_elems:
                                    layer_elems = root.findall('.//Layer')
                                for lyr in layer_elems:
                                    name_elem = lyr.find('{http://www.opengis.net/wms}Name')
                                    if name_elem is None:
                                        name_elem = lyr.find('Name')
                                    if name_elem is not None and name_elem.text:
                                        leaf_names.append(name_elem.text)
                            if not leaf_names:
                                self.util.dlg_warning(self.util.tr(u'py_dlg_base_lyr_not_loaded').format(resource['name'], 'No layer name found in WMS'))
                                continue
                            # 最初のleaf layer名を使う
                            layer_name = leaf_names[0]
                            wms_params = f"crs=EPSG:4326&format=image/png&layers={layer_name}&url={wms_url}&styles="
                            from qgis.core import QgsRasterLayer, QgsProject
                            wms_layer = QgsRasterLayer(wms_params, resource['name'], 'wms')
                            if wms_layer.isValid():
                                QgsProject.instance().addMapLayer(wms_layer)
                                self.util.msg_log_debug(f'WMS layer added: {wms_url} (layer: {layer_name})')
                            else:
                                self.util.dlg_warning(self.util.tr(u'py_dlg_base_lyr_not_loaded').format(resource['name'], f'WMS layer invalid (layer: {layer_name})'))
                        except Exception as e:
                            self.util.dlg_warning(self.util.tr(u'py_dlg_base_lyr_not_loaded').format(resource['name'], f'WMS parse error: {e}'))
                    else:
                        self.util.dlg_warning(self.util.tr(u'py_dlg_base_lyr_not_loaded').format(resource['name'], f'GetCapabilities failed: {resp.status_code}'))
                except Exception as e:
                    self.util.dlg_warning(self.util.tr(u'py_dlg_base_lyr_not_loaded').format(resource['name'], str(e)))
                continue
            if format_lower == 'wmts':
                resource_url = url_val
                resource_url_lower = resource_url.lower()
                if not resource_url_lower.endswith('.qlr'):
                    dest_file += '.wmts'
                continue
            if format_lower == 'wfs':
                dest_file += '.wfs'
            if format_lower == 'georss':
                dest_file += '.georss'
            do_download = True
            do_delete = False
            if os.path.isfile(dest_file):
                # --- 既存ファイル上書き確認ダイアログ（1回目だけ表示） ---
                if already_loaded_dialog_answer is None:
                    # 1回目だけダイアログ表示し、選択を記憶
                    if QMessageBox.Yes == self.util.dlg_yes_no(self.util.tr(u'py_dlg_base_data_already_loaded')):
                        already_loaded_dialog_answer = QMessageBox.Yes
                        do_delete = True
                        do_download = True
                    else:
                        already_loaded_dialog_answer = QMessageBox.No
                        do_download = False
                else:
                    # 2回目以降は前回の選択を自動適用
                    if already_loaded_dialog_answer == QMessageBox.Yes:
                        do_delete = True
                        do_download = True
                    else:
                        do_download = False
            download_failed = False
            if do_download is True:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                QtWidgets.qApp.processEvents()
                file_size_ok, file_size, hdr_exception = self.cc.get_file_size(url_val)
                QApplication.restoreOverrideCursor()
                if not file_size_ok:
                    file_size = 0
                # --- 大容量ファイル警告ダイアログ（1回目だけ表示） ---
                if file_size > 50:
                    if bigfile_dialog_answer is None:
                        # 1回目だけダイアログ表示し、選択を記憶
                        if QMessageBox.No == self.util.dlg_yes_no(self.util.tr(u'py_dlg_base_big_file').format(file_size)):
                            bigfile_dialog_answer = QMessageBox.No
                            continue
                        else:
                            bigfile_dialog_answer = QMessageBox.Yes
                    else:
                        # 2回目以降は前回の選択を自動適用
                        if bigfile_dialog_answer == QMessageBox.No:
                            continue
                if hdr_exception:
                    self.util.msg_log_error(u'error getting size of response, HEAD request failed: {}'.format(hdr_exception))
                self.util.msg_log_debug('setting wait cursor')
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                QtWidgets.qApp.processEvents()
                self.util.msg_log_debug('wait cursor set')
                ok, err_msg, new_file_name = self.cc.download_resource(
                    url_val
                    , resource['format']
                    , dest_file
                    , do_delete
                )
                QApplication.restoreOverrideCursor()
                if ok is False:
                    self.util.dlg_warning(err_msg)
                    download_failed = True
                else:
                    if new_file_name:
                        dest_file = new_file_name
                    if os.path.basename(dest_file).lower().endswith('.zip'):
                        ok, err_msg = self.util.extract_zip(dest_file, dest_dir)
                        QApplication.restoreOverrideCursor()
                        # --- ZIP展開失敗時のダイアログ（1回目だけ表示） ---
                        if ok is False:
                            if extract_dialog_answer is None:
                                # 1回目だけダイアログ表示し、選択を記憶
                                if QMessageBox.No == self.util.dlg_yes_no(self.util.tr(u'py_dlg_base_warn_not_extracted').format(err_msg)):
                                    extract_dialog_answer = QMessageBox.No
                                    continue
                                else:
                                    extract_dialog_answer = QMessageBox.Yes
                            else:
                                # 2回目以降は前回の選択を自動適用
                                if extract_dialog_answer == QMessageBox.No:
                                    continue
            # XYZ形式でURLが空や不正な場合は何もしない（警告も不要）
            ok, err_msg = self.util.add_lyrs_from_dir(dest_dir, resource['name'], resource['url'])
            if ok is False:
                # --- レイヤ追加失敗時のマネージャで開くか確認ダイアログ（1回目だけ表示） ---
                if addlayer_dialog_answer is None:
                    # 1回目だけダイアログ表示し、選択を記憶
                    if isinstance(err_msg, dict):
                        if QMessageBox.Yes == self.util.dlg_yes_no(self.util.tr(u'py_dlg_base_open_manager').format(resource['url'])):
                            addlayer_dialog_answer = QMessageBox.Yes
                            self.util.open_in_manager(err_msg["dir_path"])
                        else:
                            addlayer_dialog_answer = QMessageBox.No
                    else:
                        self.util.dlg_warning(self.util.tr(u'py_dlg_base_lyr_not_loaded').format(resource['name'], err_msg))
                        addlayer_dialog_answer = QMessageBox.No
                else:
                    # 2回目以降は前回の選択を自動適用
                    if addlayer_dialog_answer == QMessageBox.Yes and isinstance(err_msg, dict):
                        self.util.open_in_manager(err_msg["dir_path"])
                continue

        # XMLファイル統合処理のセッションを終了（開始していた場合のみ）
        try:
            if xml_session_started:
                self.util.finish_xml_collection_session()
        except NameError:
            # 古いコードパスでは xml_session_started が定義されていない場合がある
            # その場合は finish を呼ばない
            pass

    def next_page_clicked(self):
        self.__search_package(page=+1)

    def previous_page_clicked(self):
        self.__search_package(page=-1)

    def copy_clipboard(self):
        copy(self.IDC_plainTextLink.toPlainText())

    def __fill_link_box(self, url):
        self.IDC_plainTextLink.setPlainText(url)

    def __get_selected_groups(self):
        groups = []
        for i in range(0, self.IDC_listGroup.count()):
            item = self.IDC_listGroup.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                groups.append(item.data(Qt.ItemDataRole.UserRole)['name'])

        # None: means search all groups
        if len(groups) < 1 or len(groups) == self.IDC_listGroup.count():
            return None
        return groups

    def __get_selected_resources(self):
        res = []
        for i in range(0, self.IDC_listRessources.count()):
            item = self.IDC_listRessources.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                res.append(item.data(Qt.ItemDataRole.UserRole))

        if len(res) < 1:
            return None
        return res

    def _shorten_path(self, s):
        """ private class to shorten string to 33 chars and place a html-linebreak inside"""
        result = u""
        if len(s) > 33:
            result = s[:33] + u'<br />' + self._shorten_path(s[33:])
        else:
            return s
        return result

    def help_ttip_search(self):
        self.util.dlg_information(self.util.tr(u'dlg_base_ttip_search'))

    def help_ttip_filter(self):
        self.util.dlg_information(self.util.tr(u'dlg_base_ttip_filter'))

    def help_ttip_data_list(self):
        self.util.dlg_information(self.util.tr(u'dlg_base_ttip_data_list'))

    def help_ttip_resource(self):
        self.util.dlg_information(self.util.tr(u'dlg_base_ttip_resource'))
