# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QSettings
import os
import configparser

from qgis.core import QgsMessageLog, Qgis


class Settings:

    def __init__(self):
        # プラグインの設定を初期化
        self.debug = True
        self.results_limit = 50  # 検索結果の表示件数制限
        self.request_timeout = 15  # HTTP要求のタイムアウト秒数
        self.ckan_url = None
        self.selected_ckan_servers = ''
        self.custom_servers = {}
        self.authcfg = None
        self.cache_dir = None
        self.boxdrive_support = True  # BoxDriveサポートを有効化
        self.long_path_support = True  # 長いパス名対応を有効化
        self.DLG_CAPTION = u'geo_import'
        self.KEY_CACHE_DIR = 'geo_import/cache_dir'
        self.KEY_CKAN_API = 'geo_import/ckan_api'
        self.KEY_AUTHCFG = 'geo_import/authcfg'
        self.KEY_AUTH_PROPAGATE = 'geo_import/auth_propagate'
        self.KEY_SELECTED_CKAN_SERVERS = 'geo_import/selected_ckan_servers'
        self.KEY_CUSTOM_SERVERS = 'geo_import/custom_ckan_servers'
        self.KEY_SHOW_DEBUG_INFO = 'geo_import/show_debug_info'
        self.KEY_BOXDRIVE_SUPPORT = 'geo_import/boxdrive_support'
        self.KEY_LONG_PATH_SUPPORT = 'geo_import/long_path_support'
        self.version = self._determine_version()

    def load(self):
        # QGISの設定から値を読み込む
        import json
        qgis_settings = QSettings()
        self.cache_dir = qgis_settings.value(self.KEY_CACHE_DIR, '')
        if self.cache_dir is None:
            self.cache_dir = ''
        self.ckan_url = qgis_settings.value(self.KEY_CKAN_API, 'https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/')
        # BoxDriveサポートと長いパス名対応の設定を読み込み
        self.boxdrive_support = qgis_settings.value(self.KEY_BOXDRIVE_SUPPORT, True, bool)
        self.long_path_support = qgis_settings.value(self.KEY_LONG_PATH_SUPPORT, True, bool)
        # サーバリストはキャッシュフォルダに保存
        if not self.cache_dir:
            # デフォルトキャッシュディレクトリ
            self.cache_dir = os.path.join(os.path.expanduser('~'), '.geo_import_cache')
        if not os.path.exists(self.cache_dir):
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
            except Exception as e:
                QgsMessageLog.logMessage(f'キャッシュディレクトリの作成に失敗: {e}', self.DLG_CAPTION, Qgis.Warning)
                # 別の場所にフォールバック（ユーザーディレクトリ直下）
                try:
                    alternate_cache = os.path.join(os.path.expanduser('~'), 'Catalog_Integration_Cache')
                    os.makedirs(alternate_cache, exist_ok=True)
                    self.cache_dir = alternate_cache
                    QgsMessageLog.logMessage(f'代替キャッシュディレクトリを使用: {alternate_cache}', self.DLG_CAPTION, Qgis.Info)
                except Exception:
                    # 最終的にはシステムの一時ディレクトリを使用
                    import tempfile
                    self.cache_dir = tempfile.gettempdir()
                    QgsMessageLog.logMessage(f'一時ディレクトリをキャッシュとして使用: {self.cache_dir}', self.DLG_CAPTION, Qgis.Info)
        servers_path = os.path.join(self.cache_dir, 'ckan_servers.json')
        if os.path.exists(servers_path):
            try:
                with open(servers_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.selected_ckan_servers = data.get('selected_ckan_servers', '')
                    # 既存データがstrの場合はtype=CKANでラップ
                    loaded_custom = data.get('custom_servers', {})
                    new_custom = {}
                    for name, val in loaded_custom.items():
                        if isinstance(val, dict) and 'url' in val and 'type' in val:
                            new_custom[name] = val
                        elif isinstance(val, str):
                            new_custom[name] = {'url': val, 'type': 'CKAN'}
                        else:
                            # 不正な形式はスキップ
                            continue
                    self.custom_servers = new_custom
            except Exception:
                self.selected_ckan_servers = ''
                self.custom_servers = {}
        else:
            self.selected_ckan_servers = ''
            self.custom_servers = {}
        self.debug = qgis_settings.value(self.KEY_SHOW_DEBUG_INFO, False, bool)
        self.authcfg = qgis_settings.value(self.KEY_AUTHCFG, '')
        self.auth_propagate = qgis_settings.value(self.KEY_AUTH_PROPAGATE, False, bool)

    def save(self):
        # 設定をQGISの設定とJSONファイルに保存
        import json
        qgis_settings = QSettings()
        qgis_settings.setValue(self.KEY_CACHE_DIR, self.cache_dir)
        qgis_settings.setValue(self.KEY_CKAN_API, self.ckan_url)
        qgis_settings.setValue(self.KEY_AUTHCFG, self.authcfg)
        qgis_settings.setValue(self.KEY_AUTH_PROPAGATE, self.auth_propagate)
        qgis_settings.setValue(self.KEY_SHOW_DEBUG_INFO, self.debug)
        qgis_settings.setValue(self.KEY_BOXDRIVE_SUPPORT, self.boxdrive_support)
        qgis_settings.setValue(self.KEY_LONG_PATH_SUPPORT, self.long_path_support)
        # サーバリストはキャッシュフォルダに保存
        if not self.cache_dir:
            self.cache_dir = os.path.join(os.path.expanduser('~'), '.geo_import_cache')
        if not os.path.exists(self.cache_dir):
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
            except Exception as e:
                QgsMessageLog.logMessage(f'設定保存用キャッシュディレクトリの作成に失敗: {e}', self.DLG_CAPTION, Qgis.Warning)
                # 別の場所にフォールバック（ユーザーディレクトリ直下）
                try:
                    alternate_cache = os.path.join(os.path.expanduser('~'), 'Catalog_Integration_Cache')
                    os.makedirs(alternate_cache, exist_ok=True)
                    self.cache_dir = alternate_cache
                except Exception:
                    # 最終的にはシステムの一時ディレクトリを使用
                    import tempfile
                    self.cache_dir = tempfile.gettempdir()
        servers_path = os.path.join(self.cache_dir, 'ckan_servers.json')
        # custom_serversの値は{name: {url, type}}形式で保存
        data = {
            'selected_ckan_servers': self.selected_ckan_servers,
            'custom_servers': self.custom_servers
        }
        try:
            with open(servers_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QgsMessageLog.logMessage(f'Failed to save ckan_servers.json: {e}', self.DLG_CAPTION, Qgis.Warning)

    def _determine_version(self):
        """
        QGIS公式metadata.txt形式（セクションなし）に対応し、version=行を直接パース
        """
        meta_path = os.path.join(os.path.dirname(__file__), 'metadata.txt')
        try:
            with open(meta_path, encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('version='):
                        return line.strip().split('=', 1)[1]
        except Exception:
            pass
        return ''
