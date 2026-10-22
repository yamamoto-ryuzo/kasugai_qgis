# -*- coding: utf-8 -*-

import json
import os
import re
import sys


from .httpcall import HttpCall
from .httpcall import RequestsExceptionTimeout
from .httpcall import RequestsExceptionConnectionError
from .pyperclip import copy
from qgis.PyQt.QtCore import QCoreApplication


class CkanConnector:
    """CKAN Connector"""

    def __init__(self, settings, util):
        # 設定とユーティリティクラスを初期化
        # CKANサーバーとの通信やローカルデータベースへのアクセスを管理
        self.settings = settings
        self.settings.load()
        self.util = util
        # ソート順序を設定（名前の昇順）
        self.sort = 'name asc'
        self.mb_downloaded = 0
        # Chrome風のユーザーエージェント設定（CKAN APIへのHTTPリクエストで使用）
        self.ua_chrome = {
            b'Accept': b'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            # DON'T use: haven't found a way to tell QNetworkRequest to decompress on the fly
            # although it should automatically when this header is present
            # https://code.qt.io/cgit/qt/qtbase.git/tree/src/network/access/qhttpnetworkconnection.cpp?h=5.11#n299
            b'Accept-Encoding': b'gzip, deflate',
            b'Accept-Language': b'en-US,en;q=0.8,de;q=0.6,de-DE;q=0.4,de-CH;q=0.2',
            b'User-Agent': b'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36'
        }

    def get_groups(self, api_url=None):
        # CKANサーバーまたはローカルパスからグループ一覧を取得
        # api_url省略時は従来どおり settings.ckan_url を対象とする
        target_url = api_url or self.settings.ckan_url
        # BoxDriveなどの特殊パターンを早期検出して処理
        if isinstance(target_url, str) and (
            'Box' in target_url or
            target_url.startswith('B:\\') or
            'OneDrive' in target_url or
            ('Google' in target_url and 'Drive' in target_url)
        ):
            # 詳細なログを出力
            if 'Box' in target_url or target_url.startswith('B:\\'):
                self.util.msg_log(u'[BoxDrive] detected BoxDrive path: {0}'.format(target_url))
                self.util.msg_log(u'[BoxDrive] skipping group list fetch')
                self.util.msg_log(u'[BoxDrive] handling completed for BoxDrive path - returning empty group list')
            else:
                self.util.msg_log_debug(u'cloud storage path detected (early): {0} - returning empty group list'.format(target_url))
            return True, []

        # return self.__get_data(self.api, 'group_list?all_fields=true')
        ok, result = self._validate_ckan_url(target_url)

        if not ok:
            self.util.msg_log_error(u'CKAN URL validation failed: {0}'.format(result))
            return ok, result

        # If result points to a local folder or local/file scheme, return empty groups (handled by caller)
        try:
            # ローカル/クラウドドライブのパスチェック
            if isinstance(result, str) and (
                result.startswith('local://') or
                result.startswith('file://') or
                self._is_accessible_path(result)
            ):
                self.util.msg_log_debug(u'local or cloud path detected: {0}'.format(result))
                return True, []
        except Exception as e:
            # エラーが出てもBoxDriveなら特別処理
            if isinstance(result, str) and ('Box' in result or result.startswith('B:\\')):
                self.util.msg_log(u'[BoxDrive] error on BoxDrive path; applying special handling: {0}'.format(result))
                self.util.msg_log(u'[BoxDrive] error details: {0}'.format(str(e)))
                self.util.msg_log(u'[BoxDrive] recovery: continuing and returning empty group list')
                return True, []
            self.util.msg_log_error(u'error during local path check: {0}'.format(str(e)))

        # 接続確認は __get_data 内で行うためここでは実施しない
        self.util.msg_log_debug(u'fetching group list')
        return self.__get_data(result, 'action/group_list?all_fields=true')

    def test_groups(self, test_path):
        ok, result = self._validate_ckan_url(test_path)

        if not ok:
            self.util.msg_log_error(u'URL validation failed for test path: {0}'.format(result))
            return ok, result

        # Local folders should be treated as valid without HTTP calls
        try:
            # ローカル/クラウドドライブのパスチェック
            if isinstance(result, str) and (
                result.startswith('local://') or
                result.startswith('file://') or
                self._is_accessible_path(result)
            ):
                self.util.msg_log_debug(u'test: local or cloud path detected: {0}'.format(result))
                return True, []
        except Exception as e:
            self.util.msg_log_error(u'test: error during local path check: {0}'.format(str(e)))

        # 接続確認は __get_data 内で行うためここでは実施しない
        self.util.msg_log_debug(u'test: fetching group list')
        return self.__get_data(result, 'action/group_list?all_fields=true')

    def package_search(self, text, groups=None, page=None, rows=None, start=None, api_url=None):
        # api_url省略時は従来どおり settings.ckan_url を対象とする
        target_url = api_url or self.settings.ckan_url
        # BoxDriveなどの特殊パターンを早期検出して処理
        if isinstance(target_url, str) and (
            'Box' in target_url or
            target_url.startswith('B:\\') or
            'OneDrive' in target_url or
            ('Google' in target_url and 'Drive' in target_url)
        ):
            # 詳細なログを出力
            if 'Box' in target_url or target_url.startswith('B:\\'):
                self.util.msg_log(u'[BoxDrive] detected BoxDrive path: {0}'.format(target_url))
                self.util.msg_log(u'[BoxDrive] applying special handling')
                self.util.msg_log(u'[BoxDrive] skipping processing for BoxDrive path, returning empty result')
            else:
                self.util.msg_log_debug(u'cloud storage path detected (early): {0} - returning empty search result'.format(target_url))
            return True, {'results': [], 'count': 0}

        ok, result = self._validate_ckan_url(target_url)

        if not ok:
            self.util.msg_log_error(u'CKAN URL validation failed: {0}'.format(result))
            return ok, result

        # If server is local, return empty search result structure
        try:
            # ローカル/クラウドドライブのパスチェック
            if isinstance(result, str) and (
                result.startswith('local://') or
                result.startswith('file://') or
                self._is_accessible_path(result)
            ):
                self.util.msg_log_debug(u'local or cloud path detected: {0} - returning empty result'.format(result))
                return True, {'results': [], 'count': 0}
        except Exception as e:
            # エラーが出てもBoxDriveなら特別処理
            if isinstance(result, str) and ('Box' in result or result.startswith('B:\\')):
                self.util.msg_log(u'[BoxDrive] error on BoxDrive path; applying special handling: {0}'.format(result))
                self.util.msg_log(u'[BoxDrive] error details: {0}'.format(str(e)))
                self.util.msg_log(u'[BoxDrive] recovery: continuing and returning empty search result')
                return True, {'results': [], 'count': 0}
            self.util.msg_log_error(u'error during local path check: {0}'.format(str(e)))

        # 接続確認は __get_data 内で行うためここでは実施しない
        self.util.msg_log_debug(u'running package search')

        # グループフィルタ(カテゴリ)。複数選択時はOR条件でfqに渡す
        import urllib.parse
        fq_query = ''
        if groups:
            try:
                quoted = u' OR '.join(
                    u'"{0}"'.format(str(g).replace('"', '')) for g in groups)
                fq_query = u'&fq=' + urllib.parse.quote(
                    u'groups:({0})'.format(quoted))
            except Exception:
                fq_query = ''
        self.util.msg_log_debug(u'fq: {0}'.format(fq_query))
        # startパラメータ
        if start is not None:
            start_query = f'&start={start}'
        elif page is not None:
            start_query = self.__get_start(page)
        else:
            start_query = ''
        self.util.msg_log_debug(u'start: {0}'.format(start_query))

        # 全文検索クエリを組み立て。フィールド指定句(title:/description:等)は
        # サイトのSolrスキーマ依存で400/409になることがあるため、プレーンな
        # 全文検索とする(CKANのデフォルトが複数フィールドを横断する)。
        # Solr特殊文字はエスケープし、URL用にエンコードする。
        if text and text.strip():
            escaped = re.sub(
                r'([+\-&|!(){}\[\]^"~*?:\\/])', r'\\\1', text.strip())
            q = urllib.parse.quote(escaped, safe='')
        else:
            q = '*:*'

        # rows指定（なければsettings.results_limit）
        rows_val = rows if rows is not None else self.settings.results_limit
        return self.__get_data(
            result,
            u'action/package_search?q={0}&rows={1}{2}{3}'.format(q, rows_val, start_query, fq_query)
        )

    def show_group(self, group_name, page=None):
        ok, result = self._validate_ckan_url(self.settings.ckan_url)

        if not ok:
            self.util.msg_log_error(u'CKAN URL validation failed: {0}'.format(result))
            return ok, result

        # 接続確認は __get_data 内で行うためここでは実施しない
        self.util.msg_log_debug(group_name)
        if page is None:
            start_query = ''
        else:
            start_query = self.__get_start(page)

        self.util.msg_log_debug(u'show_group, start: {0}'.format(start_query))
        self.util.msg_log_debug(u'server connection OK, running group show')

        return self.__get_data(
            result, u'action/package_search?q=&fq=(groups:{0})&sort={1}&rows={2}{3}'.format(
                group_name,
                self.sort,
                self.settings.results_limit,
                start_query
            )
        )

    def get_file_size(self, url):
        """
        Get Headers for specified url and calculate file size in MB from Content-Length.
        """
        self.util.msg_log_debug(u'Requesting HEAD for: {0}'.format(url))

        # 接続確認
        connection_ok, error_message = self.__check_connection(url)
        if not connection_ok:
            self.util.msg_log_error(u'get file size: server connection check failed: {0}'.format(error_message))
            return False, QCoreApplication.translate('GeoImport', u'cc_api_not_accessible').format(error_message), Exception(error_message)

        try:
            http_call = HttpCall(self.settings, self.util)
            request_head = http_call.execute_request(url, http_method='head')

            self.util.msg_log_debug(
                u'get_file_size response:\nex:{0}\nhdr:{1}\nok:{2}\nreason:{3}\nstcode:{4}\nstmsg:{5}\ncontent:{6}'
                .format(
                    request_head.exception,
                    request_head.headers,
                    request_head.ok,
                    request_head.reason,
                    request_head.status_code,
                    request_head.status_message,
                    request_head.text[:255]
                )
            )

            if not request_head.ok:
                the_exception = request_head.exception if request_head.exception else Exception(QCoreApplication.translate('GeoImport', u'cc_url_error'))
                return False, QCoreApplication.translate('GeoImport', u'cc_url_error'), the_exception

        except RequestsExceptionTimeout as cte:
            self.util.msg_log(u'{0}\n{1}\n\n\n{2}'.format(cte, dir(cte), cte))
            return False, QCoreApplication.translate('GeoImport', u'cc_connection_timeout').format(cte), cte
        except Exception:
            return False, QCoreApplication.translate('GeoImport', u'cc_url_error').format(url, sys.exc_info()[1]), Exception(QCoreApplication.translate('GeoImport', u'cc_url_error'))

        if 'Content-Length' not in request_head.headers:
            self.util.msg_log_warning(u'No content-length in response header! Returning 0.')
            for h in request_head.headers:
                self.util.msg_log_debug(u'{}'.format(h))
            return True, 0, None

        content_length = request_head.headers['Content-Length']
        file_size = int(content_length) / 1000000  # divide to get MB

        self.util.msg_log_debug(u'Content-Length: {0} MB'.format(file_size))

        return True, file_size, None

    def __is_chunked(self, te):
        if not te:
            return False
        te = te.lower()
        return 'chunked' == te

    def __file_name_from_service(self, url, cd, ct):
        self.util.msg_log_debug(
            u'__file_name_from_service:\nurl: {}\nContent-Description: {}\nContent-Type: {}'
            .format(url, cd, ct)
        )

        cd = cd.lower() if cd else None
        ct = ct.lower() if ct else None

        if not cd:
            # return None
            # try to get something out of the url
            # and get rid of '?' and '&'
            file_name = url[url.rfind("/") + 1:]
            if file_name.find('?') > -1:
                file_name = file_name[:file_name.find('?')]
            if file_name.find('&') > -1:
                file_name = file_name[:file_name.find('&')]
            return file_name

        if 'attachment' in cd and 'filename=' in cd:
            file_name = cd.split('filename=')[1]
            file_name = file_name.replace('"', '').replace(';', '')
            self.util.msg_log_debug('file_name (attachment):' + file_name)
            return file_name

        if 'inline' in cd and 'filename=' in cd:
            file_name = cd.split('filename=')[1]
            file_name = file_name.replace('"', '').replace(';', '')
            self.util.msg_log_debug('file_name (inline):' + file_name)
            if ct:
                ext_ct = ct.split(';')[0].split('/')[1]
                ext_file_name = os.path.splitext(file_name)[1][1:]
                self.util.msg_log_debug(u'ext_ct:{0} ext_file_name:{1}'.format(ext_ct, ext_file_name))
                if ext_file_name not in ext_ct:
                    file_name += '.' + ext_ct
            return file_name

        return None

    def download_resource(self, url, resource_format, dest_file, delete):
        try:
            #             if resource_format is not None:
            #                 if resource_format.lower() == 'georss':
            #                     dest_file += '.xml'
            if delete is True:
                os.remove(dest_file)

            # urls might have line breaks
            url = self.util.remove_newline(url)

            # ローカルファイル（file:// / local:// / 直接パス）は直接コピーして処理する
            try:
                if isinstance(url, str) and (url.startswith('file://') or url.startswith('local://') or os.path.exists(url)):
                    import shutil
                    from urllib.parse import urlparse
                    from urllib.request import url2pathname

                    # local:// scheme -> パス部
                    if url.startswith('local://'):
                        local_path = url[len('local://'):]
                    else:
                        parsed = urlparse(url)
                        # Windows: file:///C:/path の場合先頭の/を削る
                        path = url2pathname(parsed.path)
                        if path.startswith('/') and len(path) > 2 and path[2] == ':':
                            path = path.lstrip('/')
                        local_path = path

                    # もし渡されたのが直接のファイルパスだった場合
                    if not os.path.exists(local_path) and os.path.exists(url):
                        local_path = url

                    if os.path.exists(local_path):
                        # dest の既存ファイルを削除
                        try:
                            if delete and os.path.exists(dest_file):
                                os.remove(dest_file)
                        except Exception:  # nosec B110  # 設計上の許容
                            pass
                        # コピー
                        try:
                            shutil.copyfile(local_path, dest_file)
                            return True, '', dest_file
                        except Exception as e:
                            self.util.msg_log_error(u'failed to copy local file: {0}'.format(str(e)))
                            return False, QCoreApplication.translate('GeoImport', u'cc_download_error').format(str(e)), None
            except Exception:  # nosec B110  # 設計上の許容
                # ローカル処理に失敗した場合は標準のネットワーク処理にフォールバック
                pass

            # 接続確認
            connection_ok, error_message = self.__check_connection(url)
            if not connection_ok:
                self.util.msg_log_error(u'resource download: server connection check failed: {0}'.format(error_message))
                return False, QCoreApplication.translate('GeoImport', u'cc_api_not_accessible').format(error_message), None

            self.util.msg_log_debug(u'server connection OK, downloading resource')
            http_call = HttpCall(self.settings, self.util)
            response = http_call.execute_request(
                url, headers=self.ua_chrome, verify=False, stream=True,                # not needed anymore, as we use QgsNetworkAccessManager.instance() now
                # , proxies=self.settings.get_proxies()[1]
                timeout=self.settings.request_timeout
            )

            self.util.msg_log_debug(
                u'download_resource response:\nex:{0}\nhdr:{1}\nok:{2}\nreason:{3}\nstcode:{4}\nstmsg:{5}\ncontent:{6}'
                .format(
                    response.exception,
                    '\n'.join([u'{}: {}'.format(hdr, response.headers[hdr]) for hdr in response.headers]),
                    response.ok,
                    response.reason,
                    response.status_code,
                    response.status_message,
                    response.text[:255]
                )
            )

            if not response.ok:
                return False, QCoreApplication.translate('GeoImport', u'cc_download_error').format(response.reason), None

            # Content-Disposition:
            # http://www.w3.org/Protocols/rfc2616/rfc2616-sec19.html
            # http://www.iana.org/assignments/cont-disp/cont-disp.xhtml
            file_name_from_service = self.__file_name_from_service(
                url, response.headers.get('Content-Disposition'), response.headers.get('Content-Type')
            )
            self.util.msg_log_debug(u'file name from service: {0}'.format(file_name_from_service))
            if file_name_from_service:
                # set new dest_file name
                dest_file = os.path.join(os.path.dirname(dest_file), file_name_from_service)

            self.util.msg_log_debug(u'dest_file: {0}'.format(dest_file))

            # hack for WFS/WM(T)S Services, that don't specify the format as wms, wmts or wfs
            url_low = url.lower()
            self.util.msg_log_debug(u'url.lower(): {0}'.format(url.lower()))

            if 'wfs' in url_low and 'getcapabilities' in url_low and not dest_file.endswith('.wfs'):
                if dest_file.find('?') > -1:
                    dest_file = dest_file[:dest_file.find('?')]
                self.util.msg_log_debug('wfs: adding ".wfs"')
                dest_file += '.wfs'
            if 'wmts' in url_low and 'getcapabilities' in url_low and not dest_file.endswith('.wmts'):
                if dest_file.find('?') > -1:
                    dest_file = dest_file[:dest_file.find('?')]
                self.util.msg_log_debug('wmts: adding ".wmts"')
                dest_file += '.wmts'
            # !!!!! we use extension wmts for wms too !!!!
            if 'wms' in url_low and 'getcapabilities' in url_low and not dest_file.endswith('.wmts'):
                if dest_file.find('?') > -1:
                    dest_file = dest_file[:dest_file.find('?')]
                self.util.msg_log_debug('wms: adding ".wmts"')
                dest_file += '.wmts'

            # in case some query parameters still slipped through, once again: check for '?'
            self.util.msg_log_debug(u'dest_file before final removal of "?" and "&": {0}'.format(dest_file))
            file_name_without_extension, file_extension = os.path.splitext(dest_file)
            self.util.msg_log_debug(u'file name:{}\n extension:{}'.format(file_name_without_extension, file_extension))
            if dest_file.find('?') > -1:
                dest_file = dest_file[:dest_file.find('?')] + file_extension
            if dest_file.find('&') > -1:
                dest_file = dest_file[:dest_file.find('&')] + file_extension

            self.util.msg_log_debug(u'final dest_file: {0}'.format(dest_file))

            # if file name has been set from service, set again after above changes for wfs/wm(t)s
            if file_name_from_service:
                # set return value to full path
                file_name_from_service = dest_file

            # chunk_size = 1024
            chunk_size = None
            # http://docs.python-requests.org/en/latest/user/advanced/#chunk-encoded-requests
            if self.__is_chunked(response.headers.get(b'Transfer-Encoding')):
                self.util.msg_log_debug('response is chunked')
                chunk_size = None

            with open(dest_file, 'wb') as handle:
                for chunk in response.iter_content(chunk_size):
                    if chunk:
                        handle.write(chunk)

            return True, '', file_name_from_service
        # except RequestsExceptionsTimeout as cte:
            # self.util.msg_log(u'{0}\n{1}\n\n\n{2}'.format(cte, dir(cte), cte.message))
            # return False, QCoreApplication.translate('GeoImport', u'cc_connection_timeout').format(cte.message)
        except IOError as e:
            self.util.msg_log_debug("download_resource, Can't retrieve {0} to {1}: {2}".format(url, dest_file, e))
            return False, QCoreApplication.translate('GeoImport', u'cc_download_error').format(e.strerror), None
        except NameError as ne:
            self.util.msg_log_debug(u'{0}'.format(ne))
            return False, ne.message, None
        except Exception:
            self.util.msg_log_last_exception()
            return False, QCoreApplication.translate('GeoImport', u'cc_download_error').format(sys.exc_info()[0]), None

    def __get_data(self, api, action):
        # データカタログ横断検索システムのAPIエンドポイント対応
        if api.endswith('backend/api/'):
            # backend/api/action/ の形式になるように調整
            if action.startswith('action/'):
                url = u'{0}{1}'.format(api, action)
            else:
                url = u'{0}action/{1}'.format(api, action.replace('action/', ''))
        else:
            url = u'{0}{1}'.format(api, action)

        self.util.msg_log_debug(u'api request: {0}'.format(url))
        copy(url)

        # 接続確認は事前チェックとして行うが、失敗しても実リクエストは試行する
        # (HEADベースの事前確認は一部サイトで不安定なため、失敗=即中断にすると
        # 実際にはアクセス可能なサイトが cc_api_not_accessible になる)
        connection_ok, error_message = self.__check_connection(api)
        if not connection_ok:
            self.util.msg_log_warning(u'pre-flight connection check failed, trying request anyway: {0}'.format(error_message))

        # 接続確認OKの場合のみデータ取得を実行
        try:
            url = self.util.remove_newline(url)
            http_call = HttpCall(self.settings, self.util)
            response = http_call.execute_request(
                url, headers=self.ua_chrome, verify=False,                # not needed anymore, as we use QgsNetworkAccessManager.instance() now
                # , proxies=self.settings.get_proxies()[1]
                timeout=self.settings.request_timeout
            )

            self.util.msg_log_debug(
                u'__get_data response:\nex:{0}\nhdr:{1}\nok:{2}\nreason:{3}\nstcode:{4}\nstmsg:{5}\ncontent:{6}'
                .format(
                    response.exception,
                    response.headers,
                    response.ok,
                    response.reason,
                    response.status_code,
                    response.status_message,
                    response.text[:255]
                )
            )

            if not response.ok:
                return False, QCoreApplication.translate('GeoImport', u'cc_api_not_accessible').format(response.reason)

        except RequestsExceptionTimeout as cte:
            self.util.msg_log_error(u'connection timeout for: {0}'.format(url))
            return False, QCoreApplication.translate('GeoImport', u'cc_connection_timeout').format(cte.message)
        except RequestsExceptionConnectionError as ce:
            self.util.msg_log_error(u'ConnectionError:{0}'.format(ce))
            return False, ce
        except UnicodeEncodeError as uee:
            self.util.msg_log_error(u'msg:{0} enc:{1} args:{2} reason:{3}'.format(uee.message, uee.encoding, uee.args, uee.reason))
            return False, QCoreApplication.translate('GeoImport', u'cc_api_not_accessible')
        # except:
        #    self.util.msg_log_error(u'unexpected error during request: {0}'.format(sys.exc_info()[0]))
        #    self.util.msg_log_last_exception()
        #    return False, QCoreApplication.translate('GeoImport', u'cc_api_not_accessible')

        if response.status_code != 200:
            return False, QCoreApplication.translate('GeoImport', u'cc_server_fault')

        # decode QByteArray
        try:
            json_txt = response.text.data().decode()
            self.util.msg_log_debug(u'resp_msg (decoded):\n{} .......'.format(json_txt[:255]))
            result = json.loads(json_txt)
        except TypeError as te:
            self.util.msg_log_error(u'unexpected TypeError: {0}'.format(te))
            return False, QCoreApplication.translate('GeoImport', u'cc_api_not_accessible')
        except AttributeError as ae:
            self.util.msg_log_error(u'unexpected AttributeError: {0}'.format(ae))
            return False, QCoreApplication.translate('GeoImport', u'cc_api_not_accessible')
        except Exception:
            self.util.msg_log_error(u'unexpected error during request or parsing of response:')
            self.util.msg_log_last_exception()
            return False, QCoreApplication.translate('GeoImport', u'cc_invalid_json')

        if result['success'] is False:
            return False, result['error']['message']
        return True, result['result']

    def __get_start(self, page):
        start = self.settings.results_limit * page - self.settings.results_limit
        return u'&start={0}'.format(start)

    def _is_accessible_path(self, path):
        """
        パスがアクセス可能なディレクトリかどうかを確認する
        クラウドドライブ（BoxDrive、OneDrive、GoogleDriveなど）やネットワークドライブにも対応
        応答なしになるのを防ぐため、迅速に判定する
        """
        try:
            self.util.msg_log_debug(u'starting path access check: {0}'.format(path))

            # 長すぎるパス名の検出と対応（Windowsパス長制限対策）
            if isinstance(path, str) and len(path) > 240 and sys.platform == 'win32':
                self.util.msg_log_warning(u'[path length] detected very long path ({0} chars): {1}'.format(len(path), path[:100] + '...'))

                # 長いBoxDriveパスの場合は特別対応
                if 'Box' in path:
                    self.util.msg_log(u'[BoxDrive+path length] detected long BoxDrive path; applying special handling')
                    return True

            # クラウドストレージやネットワークパスの特徴を検知
            is_potential_cloud_drive = False

            # BoxDriveの特徴的なパターンを確認
            if 'Box' in path or path.startswith('B:\\'):
                self.util.msg_log(u'[BoxDrive] detected BoxDrive path pattern: {0}'.format(path))
                self.util.msg_log(u'[BoxDrive] detected BoxDrive; treating as local path')
                is_potential_cloud_drive = True

            # OneDriveの特徴的なパターンを確認
            elif 'OneDrive' in path:
                self.util.msg_log_debug(u'detected OneDrive pattern: {0}'.format(path))
                is_potential_cloud_drive = True

            # Googleドライブの特徴的なパターンを確認
            elif 'Google' in path and 'Drive' in path:
                self.util.msg_log_debug(u'detected Google Drive pattern: {0}'.format(path))
                is_potential_cloud_drive = True

            # ネットワークパス
            elif path.startswith('\\\\'):
                self.util.msg_log_debug(u'detected network path: {0}'.format(path))
                is_potential_cloud_drive = True

            # クラウドドライブが検出された場合
            if is_potential_cloud_drive:
                if 'Box' in path or path.startswith('B:\\'):
                    self.util.msg_log(u'[BoxDrive] treating BoxDrive path as local: {0}'.format(path))
                    self.util.msg_log(u'[BoxDrive] path check process completed successfully')
                else:
                    self.util.msg_log_debug(u'treating as cloud or network path; handling as local path: {0}'.format(path))
                return True

            # 通常のディレクトリチェック - クラウドドライブでない場合のみ
            if os.path.isdir(path):
                self.util.msg_log_debug(u'recognized as normal directory: {0}'.format(path))
                return True

            # その他の一般的なファイルシステムチェック - タイムアウト制御あり
            if os.path.exists(path):
                import threading

                # 非常に短いタイムアウトで存在確認のみ行う (2秒)
                result = [False]

                def quick_access_check():
                    try:
                        # より軽量な方法でアクセス可能かを確認
                        # ファイル一覧取得ではなくパスの存在確認のみ
                        if os.access(path, os.R_OK):
                            result[0] = True
                    except Exception as e:
                        self.util.msg_log_error(u'path access check error: {0}'.format(str(e)))

                # スレッドを作成して実行
                thread = threading.Thread(target=quick_access_check)
                thread.daemon = True
                thread.start()

                # 2秒の短いタイムアウトでチェック
                thread.join(2.0)

                if result[0]:
                    self.util.msg_log_debug(u'path is readable: {0}'.format(path))
                    return True
                else:
                    self.util.msg_log_warning(u'quick path access check timed out; treating as inaccessible: {0}'.format(path))
                    return False

            self.util.msg_log_debug(u'path is not a directory or not accessible: {0}'.format(path))
            return False

        except Exception as e:
            self.util.msg_log_error(u'error during path access check: {0} - {1}'.format(path, str(e)))
            # エラーの場合でも、特徴的なパスはローカルパスとして処理
            if 'Box' in path or 'OneDrive' in path or ('Google' in path and 'Drive' in path):
                self.util.msg_log_warning(u'error occurred but cloud storage pattern detected; treating as local path: {0}'.format(path))
                return True
            return False

    def __check_connection(self, url):
        """
        URLへの接続を確認
        """
        import threading

        if url is None:
            return False, "URL is None"

        # BoxDriveなど特定のクラウドストレージパスを特別扱い
        if isinstance(url, str) and (
            'Box' in url or
            url.startswith('B:\\') or
            'OneDrive' in url or
            ('Google' in url and 'Drive' in url)
        ):
            self.util.msg_log(u'[cloud path] detected cloud storage path: {0}'.format(url))
            # BoxDriveの場合、より詳細なログを出力
            if 'Box' in url or url.startswith('B:\\'):
                self.util.msg_log(u'[BoxDrive] skipping connection check for BoxDrive path')
                self.util.msg_log(u'[BoxDrive] processing takes a special route')
            return True, None

        # ローカルパスかどうかを判定
        try:
            if self._is_accessible_path(url):
                self.util.msg_log_debug(u'local path available: {0}'.format(url))
                return True, None
        except Exception as e:
            # BoxDriveパスでエラーが起きた場合は特別扱い
            if isinstance(url, str) and ('Box' in url or url.startswith('B:\\')):
                self.util.msg_log(u'[BoxDrive] exception during BoxDrive path access check: {0}'.format(str(e)))
                self.util.msg_log(u'[BoxDrive] applying special handling for BoxDrive path: {0}'.format(url))
                return True, None
            self.util.msg_log_error(u'local path access check failed: {0}'.format(str(e)))
            return False, f"local path access error: {e}"

        # HTTP URLの場合：接続確認
        if url.startswith('http'):
            try:
                # タイムアウト付きで接続テスト
                result = [False, "Connection timed out"]

                def check_url():
                    try:
                        self.util.msg_log_debug(u'checking connection to server: {0}'.format(url))
                        http_call = HttpCall(self.settings, self.util)
                        response = http_call.execute_request(
                            url,
                            http_method='head',
                            timeout=self.settings.request_timeout
                        )
                        if response.ok:
                            result[0] = True
                            result[1] = None
                            self.util.msg_log_debug(u'server connection succeeded: {0}'.format(url))
                        else:
                            result[0] = False
                            result[1] = f"Status: {response.status_code} - {response.reason}"
                            self.util.msg_log_warning(u'server connection error: {0} - status: {1}'.format(
                                url, f"{response.status_code} - {response.reason}"))
                    except Exception as e:
                        result[0] = False
                        result[1] = str(e)
                        self.util.msg_log_warning(u'server connection exception: {0} - {1}'.format(url, str(e)))

                # スレッド作成と実行
                thread = threading.Thread(target=check_url)
                thread.daemon = True
                thread.start()

                # タイムアウト
                timeout_seconds = min(30, max(5, self.settings.request_timeout))  # 5～30秒の範囲内に制限
                self.util.msg_log_debug(u'connection check timeout: {0}s'.format(timeout_seconds))
                thread.join(timeout_seconds)

                if thread.is_alive():
                    self.util.msg_log_warning(u'server connection timeout: {0}'.format(url))
                    return False, "Connection timed out"

                return result[0], result[1]

            except Exception as e:
                self.util.msg_log_error(u'unexpected error during connection check: {0}'.format(str(e)))
                return False, str(e)

        # その他のURLスキーム：未サポート
        self.util.msg_log_warning(u'unsupported URL scheme: {0}'.format(url))
        return False, f"Unsupported URL scheme: {url}"

    def _validate_ckan_url(self, ckan_url):
        """Validate the CKAN API URL - check for trailing slash and correct API Version"""
        # Allow local folders or file:// and local:// schemes without requiring API version
        try:
            self.util.msg_log_debug(u'starting URL validation: {0}'.format(ckan_url))

            # 明らかなクラウドストレージパターンを早期検出（パフォーマンスと応答なし防止のため）
            if isinstance(ckan_url, str):
                # BoxDrive、OneDrive、GoogleDriveなどのパターン検出
                if ('Box' in ckan_url or 'OneDrive' in ckan_url or
                    ('Google' in ckan_url and 'Drive' in ckan_url) or
                        ckan_url.startswith('\\\\')):
                    self.util.msg_log_debug(u'cloud storage pattern detected (immediate): {0}'.format(ckan_url))
                    return True, ckan_url

            # file:// or local:// are considered valid local sources
            if isinstance(ckan_url, str) and (ckan_url.startswith('local://') or ckan_url.startswith('file://')):
                self.util.msg_log_debug(u'detected URL with special scheme: {0}'.format(ckan_url))
                return True, ckan_url

            # BoxDriveなどのタイムアウトを防ぐため、ドライブレターの場合は特別処理
            if isinstance(ckan_url, str) and len(ckan_url) > 2 and ckan_url[1:3] == ':\\':
                drive_letter = ckan_url[0].upper()
                # BoxDriveはB:ドライブを使うことが多い
                if drive_letter == 'B':
                    self.util.msg_log(u'[BoxDrive] detected BoxDrive drive letter (B:): {0}'.format(ckan_url))
                    self.util.msg_log(u'[BoxDrive] treating path with drive letter B as BoxDrive')
                    self.util.msg_log(u'[BoxDrive] skipping URL validation and treating as valid')
                    return True, ckan_url

            # クラウドドライブやネットワークドライブの可能性を確認（タイムアウト制御あり）
            if isinstance(ckan_url, str):
                is_accessible = self._is_accessible_path(ckan_url)
                if is_accessible:
                    self.util.msg_log_debug(u'accessible directory path detected: {0}'.format(ckan_url))
                    return True, ckan_url

        except Exception as e:
            # if any error occurs during local detection, fall back to normal validation
            self.util.msg_log_error(u'error during local path validation: {0} - {1}'.format(ckan_url, str(e)))

            # 例外が発生した場合でも、BoxDriveなどの特定パターンは例外的に許可
            if isinstance(ckan_url, str) and ('Box' in ckan_url or 'B:\\' in ckan_url):
                self.util.msg_log_warning(u'exceptionally allowing BoxDrive pattern: {0}'.format(ckan_url))
                return True, ckan_url

            pass

        # HTTP APIチェック
        if not isinstance(ckan_url, str):
            return False, QCoreApplication.translate('GeoImport', u"cc_wrong_api")

        if not ckan_url.endswith("/"):
            ckan_url += "/"

        # データカタログ横断検索システムのAPI URLは特別な形式（backend/api/）を使用
        if ckan_url.endswith("backend/api/"):
            return True, ckan_url

        # 標準CKAN APIのバージョンチェック
        if not ckan_url.endswith("3/"):  # was bei neuen APIS > 3?
            self.util.msg_log_debug(u'unsupported API version: {0}'.format(ckan_url))
            return False, QCoreApplication.translate('GeoImport', u"cc_wrong_api")

        return True, ckan_url
