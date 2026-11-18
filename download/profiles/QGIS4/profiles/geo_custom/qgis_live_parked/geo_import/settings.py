# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QSettings
import os

from qgis.core import QgsMessageLog, Qgis


class Settings:

    def __init__(self):
        # プラグインの設定を初期化
        self.debug = True
        self.results_limit = 50  # 検索結果の表示件数制限
        self.request_timeout = 15  # HTTP要求のタイムアウト秒数
        self.ckan_url = None
        self.selected_ckan_servers = ''
        self.selected_ckan_urls = []  # 複数選択時のアクティブなapi_url一覧(横断検索用)
        self.server_errors = {}  # {api_url: {"error": msg, "time": iso}} 接続失敗の記録
        self.custom_servers = {}
        self.authcfg = None
        self.cache_dir = None
        self.boxdrive_support = True  # BoxDriveサポートを有効化
        self.long_path_support = True  # 長いパス名対応を有効化
        # ローカルダウンロード(SQLiteキャッシュ)利用設定
        # デフォルトはネットワーク経由の直接取得。ローカルキャッシュはオプション。
        self.use_local_cache_all = False  # 全サイトでローカルキャッシュを利用
        self.local_cache_sites = []  # ローカルキャッシュを利用するサイト(api_url)のリスト
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
        self.KEY_USE_LOCAL_CACHE_ALL = 'geo_import/use_local_cache_all'
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
        # 全サイトのローカルキャッシュ利用フラグ
        self.use_local_cache_all = qgis_settings.value(self.KEY_USE_LOCAL_CACHE_ALL, False, bool)
        # サーバリストはキャッシュフォルダに保存
        if not self.cache_dir:
            # デフォルトキャッシュディレクトリ
            self.cache_dir = os.path.join(os.path.expanduser('~'), '.geo_import_cache')
        if not os.path.exists(self.cache_dir):
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
            except Exception as e:
                QgsMessageLog.logMessage(f'failed to create cache directory: {e}', self.DLG_CAPTION, Qgis.MessageLevel.Warning)
                # 別の場所にフォールバック（ユーザーディレクトリ直下）
                try:
                    alternate_cache = os.path.join(os.path.expanduser('~'), 'Catalog_Integration_Cache')
                    os.makedirs(alternate_cache, exist_ok=True)
                    self.cache_dir = alternate_cache
                    QgsMessageLog.logMessage(f'using alternative cache directory: {alternate_cache}', self.DLG_CAPTION, Qgis.MessageLevel.Info)
                except Exception:
                    # 最終的にはシステムの一時ディレクトリを使用
                    import tempfile
                    self.cache_dir = tempfile.gettempdir()
                    QgsMessageLog.logMessage(f'using temp directory as cache: {self.cache_dir}', self.DLG_CAPTION, Qgis.MessageLevel.Info)
        servers_path = os.path.join(self.cache_dir, 'ckan_servers.json')
        if os.path.exists(servers_path):
            try:
                with open(servers_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.selected_ckan_servers = data.get('selected_ckan_servers', '')
                    loaded_urls = data.get('selected_ckan_urls', [])
                    self.selected_ckan_urls = loaded_urls if isinstance(loaded_urls, list) else []
                    loaded_errors = data.get('server_errors', {})
                    self.server_errors = loaded_errors if isinstance(loaded_errors, dict) else {}
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
                    sites = data.get('local_cache_sites', [])
                    self.local_cache_sites = sites if isinstance(sites, list) else []
            except Exception:
                self.selected_ckan_servers = ''
                self.selected_ckan_urls = []
                self.custom_servers = {}
                self.local_cache_sites = []
                self.server_errors = {}
        else:
            self.selected_ckan_servers = ''
            self.selected_ckan_urls = []
            self.custom_servers = {}
            self.local_cache_sites = []
            self.server_errors = {}
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
        qgis_settings.setValue(self.KEY_USE_LOCAL_CACHE_ALL, self.use_local_cache_all)
        # サーバリストはキャッシュフォルダに保存
        if not self.cache_dir:
            self.cache_dir = os.path.join(os.path.expanduser('~'), '.geo_import_cache')
        if not os.path.exists(self.cache_dir):
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
            except Exception as e:
                QgsMessageLog.logMessage(f'failed to create settings cache directory: {e}', self.DLG_CAPTION, Qgis.MessageLevel.Warning)
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
            'selected_ckan_urls': self.selected_ckan_urls if isinstance(self.selected_ckan_urls, list) else [],
            'custom_servers': self.custom_servers,
            'local_cache_sites': self.local_cache_sites if isinstance(self.local_cache_sites, list) else [],
            'server_errors': self.server_errors if isinstance(self.server_errors, dict) else {}
        }
        try:
            with open(servers_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QgsMessageLog.logMessage(f'Failed to save ckan_servers.json: {e}', self.DLG_CAPTION, Qgis.MessageLevel.Warning)

    def active_server_urls(self):
        """
        アクティブなカタログサーバー(api_url)の一覧を返す。
        複数選択時は selected_ckan_urls、未設定/単一選択時は従来の ckan_url にフォールバック。
        """
        urls = [u for u in (self.selected_ckan_urls or []) if isinstance(u, str) and u]
        if urls:
            return urls
        return [self.ckan_url] if self.ckan_url else []

    def record_server_error(self, url, message):
        """サーバーの接続失敗を記録する(死んでいるCKANの明示用)"""
        if not url:
            return
        if not isinstance(self.server_errors, dict):
            self.server_errors = {}
        import datetime
        self.server_errors[url] = {
            'error': str(message)[:300],
            'time': datetime.datetime.now().isoformat(timespec='seconds'),
        }

    def clear_server_error(self, url):
        """接続成功時にサーバーの失敗記録を消す"""
        if isinstance(self.server_errors, dict) and url in self.server_errors:
            del self.server_errors[url]

    def server_error(self, url):
        """記録された失敗メッセージを返す。無ければNone"""
        entry = (self.server_errors or {}).get(url)
        if isinstance(entry, dict):
            return entry.get('error')
        return entry

    def use_local_cache(self, url):
        """
        指定したサイト(api_url)でローカルキャッシュ(SQLite)を利用するか判定する。
        全体設定(use_local_cache_all)またはサイト個別設定(local_cache_sites)で有効ならTrue。
        """
        if self.use_local_cache_all:
            return True
        return bool(url) and url in (self.local_cache_sites or [])

    def set_local_cache_site(self, url, enabled):
        """サイト単位のローカルキャッシュ利用フラグを設定する"""
        if not isinstance(self.local_cache_sites, list):
            self.local_cache_sites = []
        if enabled:
            if url and url not in self.local_cache_sites:
                self.local_cache_sites.append(url)
        elif url in self.local_cache_sites:
            self.local_cache_sites.remove(url)

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
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return ''
