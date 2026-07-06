# -*- coding: utf-8 -*-

import json
import os
import sys
import string


from .httpcall import HttpCall
from .httpcall import RequestsException
from .httpcall import RequestsExceptionTimeout
from .httpcall import RequestsExceptionConnectionError
from .httpcall import RequestsExceptionUserAbort
from .pyperclip import copy


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

    def get_groups(self):
        # CKANサーバーまたはローカルパスからグループ一覧を取得
        # BoxDriveなどの特殊パターンを早期検出して処理
        if isinstance(self.settings.ckan_url, str) and (
            'Box' in self.settings.ckan_url or 
            self.settings.ckan_url.startswith('B:\\') or 
            'OneDrive' in self.settings.ckan_url or
            ('Google' in self.settings.ckan_url and 'Drive' in self.settings.ckan_url)
        ):
            # 詳細なログを出力
            if 'Box' in self.settings.ckan_url or self.settings.ckan_url.startswith('B:\\'):
                self.util.msg_log(u'【BoxDrive検出】BoxDriveパスを検出しました: {0}'.format(self.settings.ckan_url))
                self.util.msg_log(u'【BoxDrive処理】グループ一覧取得をスキップします')
                self.util.msg_log(u'【BoxDrive状態】BoxDriveパスに対する処理を完了しました - 空のグループ一覧を返します')
            else:
                self.util.msg_log_debug(u'クラウドストレージパス検出 (早期処理): {0} - 空のグループリストを返します'.format(self.settings.ckan_url))
            return True, []
            
        # return self.__get_data(self.api, 'group_list?all_fields=true')
        ok, result = self._validate_ckan_url(self.settings.ckan_url)

        if not ok:
            self.util.msg_log_error(u'CKAN URL検証に失敗: {0}'.format(result))
            return ok, result
            
        # If result points to a local folder or local/file scheme, return empty groups (handled by caller)
        try:
            # ローカル/クラウドドライブのパスチェック
            if isinstance(result, str) and (
                result.startswith('local://') or 
                result.startswith('file://') or 
                self._is_accessible_path(result)
            ):
                self.util.msg_log_debug(u'ローカルまたはクラウドパス検出: {0}'.format(result))
                return True, []
        except Exception as e:
            # エラーが出てもBoxDriveなら特別処理
            if isinstance(result, str) and ('Box' in result or result.startswith('B:\\')):
                self.util.msg_log(u'【BoxDrive例外処理】BoxDriveパスでエラーが発生しましたが、特別処理を適用します: {0}'.format(result))
                self.util.msg_log(u'【BoxDrive例外詳細】エラーの内容: {0}'.format(str(e)))
                self.util.msg_log(u'【BoxDrive回復処理】処理を続行して空のグループリストを返します')
                return True, []
            self.util.msg_log_error(u'ローカルパス確認中のエラー: {0}'.format(str(e)))
            
        # サーバー接続確認
        connection_ok, error_message = self.__check_connection(result)
        if not connection_ok:
            self.util.msg_log_error(u'サーバー接続確認に失敗: {0}'.format(error_message))
            return False, self.util.tr(u'cc_api_not_accessible').format(error_message)
            
        self.util.msg_log_debug(u'サーバー接続OK、グループリスト取得を実行します')
        return self.__get_data(result, 'action/group_list?all_fields=true')

    def test_groups(self, test_path):
        ok, result = self._validate_ckan_url(test_path)

        if not ok:
            self.util.msg_log_error(u'テストパスのURL検証に失敗: {0}'.format(result))
            return ok, result
            
        # Local folders should be treated as valid without HTTP calls
        try:
            # ローカル/クラウドドライブのパスチェック
            if isinstance(result, str) and (
                result.startswith('local://') or 
                result.startswith('file://') or 
                self._is_accessible_path(result)
            ):
                self.util.msg_log_debug(u'テスト: ローカルまたはクラウドパス検出: {0}'.format(result))
                return True, []
        except Exception as e:
            self.util.msg_log_error(u'テスト: ローカルパス確認中のエラー: {0}'.format(str(e)))
        
        # サーバー接続確認
        connection_ok, error_message = self.__check_connection(result)
        if not connection_ok:
            self.util.msg_log_error(u'テスト: サーバー接続確認に失敗: {0}'.format(error_message))
            return False, self.util.tr(u'cc_api_not_accessible').format(error_message)
            
        self.util.msg_log_debug(u'テスト: サーバー接続OK、グループリスト取得を実行します')
        return self.__get_data(result, 'action/group_list?all_fields=true')

    def package_search(self, text, groups=None, page=None, rows=None, start=None):
        # BoxDriveなどの特殊パターンを早期検出して処理
        if isinstance(self.settings.ckan_url, str) and (
            'Box' in self.settings.ckan_url or 
            self.settings.ckan_url.startswith('B:\\') or 
            'OneDrive' in self.settings.ckan_url or
            ('Google' in self.settings.ckan_url and 'Drive' in self.settings.ckan_url)
        ):
            # 詳細なログを出力
            if 'Box' in self.settings.ckan_url or self.settings.ckan_url.startswith('B:\\'):
                self.util.msg_log(u'【BoxDrive検出】BoxDriveパスを検出しました: {0}'.format(self.settings.ckan_url))
                self.util.msg_log(u'【BoxDrive処理】BoxDrive用に特別処理を適用します')
                self.util.msg_log(u'【BoxDrive状態】BoxDriveパスに対する処理をスキップし、空の結果を返します')
            else:
                self.util.msg_log_debug(u'クラウドストレージパス検出 (早期処理): {0} - 空の検索結果を返します'.format(self.settings.ckan_url))
            return True, {'results': [], 'count': 0}
            
        ok, result = self._validate_ckan_url(self.settings.ckan_url)

        if not ok:
            self.util.msg_log_error(u'CKAN URL検証に失敗: {0}'.format(result))
            return ok, result

        # If server is local, return empty search result structure
        try:
            # ローカル/クラウドドライブのパスチェック
            if isinstance(result, str) and (
                result.startswith('local://') or 
                result.startswith('file://') or 
                self._is_accessible_path(result)
            ):
                self.util.msg_log_debug(u'ローカルまたはクラウドパス検出: {0} - 空の検索結果を返します'.format(result))
                return True, {'results': [], 'count': 0}
        except Exception as e:
            # エラーが出てもBoxDriveなら特別処理
            if isinstance(result, str) and ('Box' in result or result.startswith('B:\\')):
                self.util.msg_log(u'【BoxDrive例外処理】BoxDriveパスでエラーが発生しましたが、特別処理を適用します: {0}'.format(result))
                self.util.msg_log(u'【BoxDrive例外詳細】エラーの内容: {0}'.format(str(e)))
                self.util.msg_log(u'【BoxDrive回復処理】処理を続行して空の検索結果を返します')
                return True, {'results': [], 'count': 0}
            self.util.msg_log_error(u'ローカルパス確認中のエラー: {0}'.format(str(e)))
            
        # サーバー接続確認
        connection_ok, error_message = self.__check_connection(result)
        if not connection_ok:
            self.util.msg_log_error(u'サーバー接続確認に失敗: {0}'.format(error_message))
            return False, self.util.tr(u'cc_api_not_accessible').format(error_message)
            
        self.util.msg_log_debug(u'サーバー接続OK、パッケージ検索を実行します')

        # グループフィルタは使用しない
        group_filter = ''
        # self.util.msg_log_debug(u'group_filter: {0}'.format(group_filter))
        # startパラメータ
        if start is not None:
            start_query = f'&start={start}'
        elif page is not None:
            start_query = self.__get_start(page)
        else:
            start_query = ''
        self.util.msg_log_debug(u'start: {0}'.format(start_query))

        # 全文検索クエリを組み立て
        if text and text.strip():
            # タイトル・説明・タグのOR全文検索
            q = u'({0}) OR description:{0} OR tags:{0}'.format(text)
        else:
            q = '*:*'

        # rows指定（なければsettings.results_limit）
        rows_val = rows if rows is not None else self.settings.results_limit
        return self.__get_data(
            result,
            u'action/package_search?q={0}&rows={1}{2}'.format(q, rows_val, start_query)
        )

    def show_group(self, group_name, page=None):
        ok, result = self._validate_ckan_url(self.settings.ckan_url)

        if not ok:
            self.util.msg_log_error(u'CKAN URL検証に失敗: {0}'.format(result))
            return ok, result
            
        # サーバー接続確認
        connection_ok, error_message = self.__check_connection(result)
        if not connection_ok:
            self.util.msg_log_error(u'サーバー接続確認に失敗: {0}'.format(error_message))
            return False, self.util.tr(u'cc_api_not_accessible').format(error_message)

        self.util.msg_log_debug(group_name)
        if page is None:
            start_query = ''
        else:
            start_query = self.__get_start(page)

        self.util.msg_log_debug(u'show_group, start: {0}'.format(start_query))
        self.util.msg_log_debug(u'サーバー接続OK、グループ表示を実行します')

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
            self.util.msg_log_error(u'ファイルサイズ取得: サーバー接続確認に失敗: {0}'.format(error_message))
            return False, self.util.tr(u'cc_api_not_accessible').format(error_message), Exception(error_message)

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
                the_exception = request_head.exception if request_head.exception else Exception(self.util.tr(u'cc_url_error'))
                return False, self.util.tr(u'cc_url_error'), the_exception

        except RequestsExceptionTimeout as cte:
            self.util.msg_log(u'{0}\n{1}\n\n\n{2}'.format(cte, dir(cte), cte))
            return False, self.util.tr(u'cc_connection_timeout').format(cte), cte
        except:
            return False, self.util.tr(u'cc_url_error').format(url, sys.exc_info()[1]), Exception(self.util.tr(u'cc_url_error'))

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
                        except Exception:
                            pass
                        # コピー
                        try:
                            shutil.copyfile(local_path, dest_file)
                            return True, '', dest_file
                        except Exception as e:
                            self.util.msg_log_error(u'ローカルファイルのコピーに失敗: {0}'.format(str(e)))
                            return False, self.util.tr(u'cc_download_error').format(str(e)), None
            except Exception:
                # ローカル処理に失敗した場合は標準のネットワーク処理にフォールバック
                pass

            # 接続確認
            connection_ok, error_message = self.__check_connection(url)
            if not connection_ok:
                self.util.msg_log_error(u'リソースダウンロード: サーバー接続確認に失敗: {0}'.format(error_message))
                return False, self.util.tr(u'cc_api_not_accessible').format(error_message), None

            self.util.msg_log_debug(u'サーバー接続OK、リソースダウンロードを実行します')
            http_call = HttpCall(self.settings, self.util)
            response = http_call.execute_request(
                url
                , headers=self.ua_chrome
                , verify=False
                , stream=True
                # not needed anymore, as we use QgsNetworkAccessManager.instance() now
                #, proxies=self.settings.get_proxies()[1]
                , timeout=self.settings.request_timeout
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
                return False, self.util.tr(u'cc_download_error').format(response.reason), None

            # Content-Disposition:
            # http://www.w3.org/Protocols/rfc2616/rfc2616-sec19.html
            # http://www.iana.org/assignments/cont-disp/cont-disp.xhtml
            file_name_from_service = self.__file_name_from_service(
                url
                , response.headers.get('Content-Disposition')
                , response.headers.get('Content-Type')
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

            #chunk_size = 1024
            chunk_size = None
            #http://docs.python-requests.org/en/latest/user/advanced/#chunk-encoded-requests
            if self.__is_chunked(response.headers.get(b'Transfer-Encoding')):
                self.util.msg_log_debug('response is chunked')
                chunk_size = None

            with open(dest_file, 'wb') as handle:
                for chunk in response.iter_content(chunk_size):
                    if chunk:
                        handle.write(chunk)

            return True, '', file_name_from_service
        #except RequestsExceptionsTimeout as cte:
            #self.util.msg_log(u'{0}\n{1}\n\n\n{2}'.format(cte, dir(cte), cte.message))
            #return False, self.util.tr(u'cc_connection_timeout').format(cte.message)
        except IOError as e:
            self.util.msg_log_debug("download_resource, Can't retrieve {0} to {1}: {2}".format(url, dest_file, e))
            return False, self.util.tr(u'cc_download_error').format(e.strerror), None
        except NameError as ne:
            self.util.msg_log_debug(u'{0}'.format(ne))
            return False, ne.message, None
        except:
            self.util.msg_log_last_exception()
            return False, self.util.tr(u'cc_download_error').format(sys.exc_info()[0]), None

    def __check_connection(self, url):
        """サーバーとの接続を確認するためのヘルパーメソッド"""
        self.util.msg_log_debug(u'サーバー接続確認: {0}'.format(url))
        
        # クラウドストレージパスやローカルパスの場合はチェックせずに成功とする
        try:
            # クラウドストレージの特徴的なパターンを確認（事前にURL検証をすり抜けた場合のため）
            if isinstance(url, str) and ('Box' in url or 'OneDrive' in url or 
                ('Google' in url and 'Drive' in url) or url.startswith('\\\\') or
                url.startswith('file://') or url.startswith('local://')):
                
                # BoxDrive特別ログ
                if 'Box' in url or url.startswith('B:\\'):
                    self.util.msg_log(u'【BoxDrive接続チェック】BoxDriveパスを検出: {0}'.format(url))
                    self.util.msg_log(u'【BoxDrive接続スキップ】BoxDriveはHTTP接続チェックをスキップします')
                    self.util.msg_log(u'【BoxDrive接続状態】接続は成功と判定されました')
                else:
                    self.util.msg_log_debug(u'クラウドストレージまたはローカルパス。接続チェックをスキップ: {0}'.format(url))
                
                return True, None
        except Exception:
            # 何かエラーがあっても処理を続行
            pass
            
        # 通常のHTTP接続の場合はより短いタイムアウトで確認
        try:
            import threading
            import time
            
            # タイムアウト用のフラグとスレッド結果
            connection_result = [False, None]
            
            def connection_check_thread():
                try:
                    url_clean = self.util.remove_newline(url)
                    http_call = HttpCall(self.settings, self.util)
                    response = http_call.execute_request(
                        url_clean
                        , headers=self.ua_chrome
                        , verify=False
                        # 接続確認は非常に短いタイムアウトに設定
                        , timeout=min(3.0, self.settings.request_timeout / 3)
                    )
                    
                    if response.ok:
                        connection_result[0] = True
                    else:
                        connection_result[1] = response.reason
                except RequestsExceptionTimeout as cte:
                    connection_result[1] = self.util.tr(u'cc_connection_timeout').format(
                        getattr(cte, 'message', str(cte))
                    )
                except RequestsExceptionConnectionError as ce:
                    connection_result[1] = str(ce)
                except Exception as e:
                    connection_result[1] = str(e)
            
            # スレッドを作成して実行
            thread = threading.Thread(target=connection_check_thread)
            thread.daemon = True
            thread.start()
            
            # 3秒間だけスレッドの完了を待つ
            thread.join(3.0)
            
            if thread.is_alive():
                # スレッドが3秒以内に終わらなかった = タイムアウト
                self.util.msg_log_error(u'サーバー接続確認がタイムアウトしました: {0}'.format(url))
                return False, self.util.tr(u'cc_connection_timeout').format("Connection check timeout")
                
            if connection_result[0]:
                self.util.msg_log_debug(u'サーバー接続成功: {0}'.format(url))
                return True, None
            else:
                reason = connection_result[1] if connection_result[1] else "Unknown error"
                self.util.msg_log_error(u'サーバー接続失敗: {0} - {1}'.format(url, reason))
                return False, reason
                
        except Exception as e:
            self.util.msg_log_error(u'サーバー接続確認プロセス自体でエラー発生: {0} - {1}'.format(url, str(e)))
            self.util.msg_log_last_exception()
            return False, str(e)

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
        
        # 接続確認を先に行う
        connection_ok, error_message = self.__check_connection(api)
        if not connection_ok:
            self.util.msg_log_error(u'サーバー接続確認に失敗したため、APIリクエストを中断します: {0}'.format(error_message))
            return False, self.util.tr(u'cc_api_not_accessible').format(error_message)
            
        # 接続確認OKの場合のみデータ取得を実行
        try:
            url = self.util.remove_newline(url)
            http_call = HttpCall(self.settings, self.util)
            response = http_call.execute_request(
                url
                , headers=self.ua_chrome
                , verify=False
                # not needed anymore, as we use QgsNetworkAccessManager.instance() now
                #, proxies=self.settings.get_proxies()[1]
                , timeout=self.settings.request_timeout
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
                return False, self.util.tr(u'cc_api_not_accessible').format(response.reason)

        except RequestsExceptionTimeout as cte:
            self.util.msg_log_error(u'connection timeout for: {0}'.format(url))
            return False, self.util.tr(u'cc_connection_timeout').format(cte.message)
        except RequestsExceptionConnectionError as ce:
            self.util.msg_log_error(u'ConnectionError:{0}'.format(ce))
            return False, ce
        except UnicodeEncodeError as uee:
            self.util.msg_log_error(u'msg:{0} enc:{1} args:{2} reason:{3}'.format(uee.message, uee.encoding, uee.args, uee.reason))
            return False, self.util.tr(u'cc_api_not_accessible')
        #except:
        #    self.util.msg_log_error(u'unexpected error during request: {0}'.format(sys.exc_info()[0]))
        #    self.util.msg_log_last_exception()
        #    return False, self.util.tr(u'cc_api_not_accessible')

        if response.status_code != 200:
            return False, self.util.tr(u'cc_server_fault')

        # decode QByteArray
        try:
            json_txt = response.text.data().decode()
            self.util.msg_log_debug(u'resp_msg (decoded):\n{} .......'.format(json_txt[:255]))
            result = json.loads(json_txt)
        except TypeError as te:
            self.util.msg_log_error(u'unexpected TypeError: {0}'.format(te))
            return False, self.util.tr(u'cc_api_not_accessible')
        except AttributeError as ae:
            self.util.msg_log_error(u'unexpected AttributeError: {0}'.format(ae))
            return False, self.util.tr(u'cc_api_not_accessible')
        except:
            self.util.msg_log_error(u'unexpected error during request or parsing of response:')
            self.util.msg_log_last_exception()
            return False, self.util.tr(u'cc_invalid_json')

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
            self.util.msg_log_debug(u'パスのアクセス確認開始: {0}'.format(path))
            
            # 長すぎるパス名の検出と対応（Windowsパス長制限対策）
            if isinstance(path, str) and len(path) > 240 and sys.platform == 'win32':
                self.util.msg_log_warning(u'【パス長対策】非常に長いパスを検出 ({0}文字): {1}'.format(len(path), path[:100] + '...'))
                
                # 長いBoxDriveパスの場合は特別対応
                if 'Box' in path:
                    self.util.msg_log(u'【BoxDrive+パス長対策】長いBoxDriveパスを検出しました。特別処理を適用します')
                    return True
            
            # クラウドストレージやネットワークパスの特徴を検知
            is_potential_cloud_drive = False
            
            # BoxDriveの特徴的なパターンを確認
            if 'Box' in path or path.startswith('B:\\'):
                self.util.msg_log(u'【BoxDrive検出】BoxDriveパスパターンを検出: {0}'.format(path))
                self.util.msg_log(u'【BoxDrive処理】BoxDriveと判定してローカルパスとして処理します')
                is_potential_cloud_drive = True
                
            # OneDriveの特徴的なパターンを確認
            elif 'OneDrive' in path:
                self.util.msg_log_debug(u'OneDriveパターンを検出: {0}'.format(path))
                is_potential_cloud_drive = True
                
            # Googleドライブの特徴的なパターンを確認
            elif 'Google' in path and 'Drive' in path:
                self.util.msg_log_debug(u'Google Driveパターンを検出: {0}'.format(path))
                is_potential_cloud_drive = True
                
            # ネットワークパス
            elif path.startswith('\\\\'):
                self.util.msg_log_debug(u'ネットワークパスを検出: {0}'.format(path))
                is_potential_cloud_drive = True
                
            # クラウドドライブが検出された場合
            if is_potential_cloud_drive:
                if 'Box' in path or path.startswith('B:\\'):
                    self.util.msg_log(u'【BoxDriveパス確認】BoxDriveパスをローカルパスとして処理: {0}'.format(path))
                    self.util.msg_log(u'【BoxDrive進捗】パス確認プロセスを正常に完了しました')
                else:
                    self.util.msg_log_debug(u'クラウドストレージまたはネットワークパスと判定。ローカルパスとして処理します: {0}'.format(path))
                return True
                
            # 通常のディレクトリチェック - クラウドドライブでない場合のみ
            if os.path.isdir(path):
                self.util.msg_log_debug(u'通常のディレクトリとして認識: {0}'.format(path))
                return True
                
            # その他の一般的なファイルシステムチェック - タイムアウト制御あり
            if os.path.exists(path):
                import threading
                import time
                
                # 非常に短いタイムアウトで存在確認のみ行う (2秒)
                result = [False]
                
                def quick_access_check():
                    try:
                        # より軽量な方法でアクセス可能かを確認
                        # ファイル一覧取得ではなくパスの存在確認のみ
                        if os.access(path, os.R_OK):
                            result[0] = True
                    except Exception as e:
                        self.util.msg_log_error(u'パスアクセスチェックエラー: {0}'.format(str(e)))
                
                # スレッドを作成して実行
                thread = threading.Thread(target=quick_access_check)
                thread.daemon = True
                thread.start()
                
                # 2秒の短いタイムアウトでチェック
                thread.join(2.0)
                
                if result[0]:
                    self.util.msg_log_debug(u'パスは読み取り可能: {0}'.format(path))
                    return True
                else:
                    self.util.msg_log_warning(u'パスへの迅速アクセスチェックがタイムアウト。安全のためアクセス不可と判定: {0}'.format(path))
                    return False
            
            self.util.msg_log_debug(u'パスはディレクトリではない、またはアクセスできない: {0}'.format(path))
            return False
            
        except Exception as e:
            self.util.msg_log_error(u'パスアクセス確認中のエラー: {0} - {1}'.format(path, str(e)))
            # エラーの場合でも、特徴的なパスはローカルパスとして処理
            if 'Box' in path or 'OneDrive' in path or ('Google' in path and 'Drive' in path):
                self.util.msg_log_warning(u'エラーが発生したが、クラウドストレージパターンを検出。ローカルパスとして処理: {0}'.format(path))
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
            self.util.msg_log(u'【クラウドパス検出】クラウドストレージパスを検出: {0}'.format(url))
            # BoxDriveの場合、より詳細なログを出力
            if 'Box' in url or url.startswith('B:\\'):
                self.util.msg_log(u'【BoxDrive対策】BoxDriveパスの接続確認をスキップします')
                self.util.msg_log(u'【BoxDrive情報】BoxDriveの処理は特別ルートで行われます')
            return True, None
            
        # ローカルパスかどうかを判定
        try:
            if self._is_accessible_path(url):
                self.util.msg_log_debug(u'ローカルパスが利用可能: {0}'.format(url))
                return True, None
        except Exception as e:
            # BoxDriveパスでエラーが起きた場合は特別扱い
            if isinstance(url, str) and ('Box' in url or url.startswith('B:\\')):
                self.util.msg_log(u'【BoxDrive例外】BoxDriveパスへのアクセス確認で例外が発生: {0}'.format(str(e)))
                self.util.msg_log(u'【BoxDrive対応】BoxDriveパスは特別処理を適用します: {0}'.format(url))
                return True, None
            self.util.msg_log_error(u'ローカルパスのアクセス確認に失敗: {0}'.format(str(e)))
            return False, f"ローカルパスアクセスエラー: {str(e)}"

        # HTTP URLの場合：接続確認
        if url.startswith('http'):
            try:
                # タイムアウト付きで接続テスト
                result = [False, "Connection timed out"]
                
                def check_url():
                    try:
                        self.util.msg_log_debug(u'サーバーへの接続を確認中: {0}'.format(url))
                        http_call = HttpCall(self.settings, self.util)
                        response = http_call.execute_request(
                            url,
                            http_method='head',
                            timeout=self.settings.request_timeout
                        )
                        if response.ok:
                            result[0] = True
                            result[1] = None
                            self.util.msg_log_debug(u'サーバー接続成功: {0}'.format(url))
                        else:
                            result[0] = False
                            result[1] = f"Status: {response.status_code} - {response.reason}"
                            self.util.msg_log_warning(u'サーバー接続エラー: {0} - ステータス: {1}'.format(
                                url, f"{response.status_code} - {response.reason}"))
                    except Exception as e:
                        result[0] = False
                        result[1] = str(e)
                        self.util.msg_log_warning(u'サーバー接続例外: {0} - {1}'.format(url, str(e)))
                
                # スレッド作成と実行
                thread = threading.Thread(target=check_url)
                thread.daemon = True
                thread.start()
                
                # タイムアウト
                timeout_seconds = min(30, max(5, self.settings.request_timeout))  # 5～30秒の範囲内に制限
                self.util.msg_log_debug(u'接続確認タイムアウト: {0}秒'.format(timeout_seconds))
                thread.join(timeout_seconds)
                
                if thread.is_alive():
                    self.util.msg_log_warning(u'サーバー接続タイムアウト: {0}'.format(url))
                    return False, "Connection timed out"
                
                return result[0], result[1]
                
            except Exception as e:
                self.util.msg_log_error(u'接続確認中の予期せぬエラー: {0}'.format(str(e)))
                return False, str(e)
        
        # その他のURLスキーム：未サポート
        self.util.msg_log_warning(u'未サポートのURLスキーム: {0}'.format(url))
        return False, f"Unsupported URL scheme: {url}"

    def _validate_ckan_url(self, ckan_url):
        """Validate the CKAN API URL - check for trailing slash and correct API Version"""
        # Allow local folders or file:// and local:// schemes without requiring API version
        try:
            self.util.msg_log_debug(u'URL検証開始: {0}'.format(ckan_url))
            
            # 明らかなクラウドストレージパターンを早期検出（パフォーマンスと応答なし防止のため）
            if isinstance(ckan_url, str):
                # BoxDrive、OneDrive、GoogleDriveなどのパターン検出
                if ('Box' in ckan_url or 'OneDrive' in ckan_url or 
                    ('Google' in ckan_url and 'Drive' in ckan_url) or
                    ckan_url.startswith('\\\\')):
                    self.util.msg_log_debug(u'クラウドストレージパターン検出（即時認識）: {0}'.format(ckan_url))
                    return True, ckan_url
            
            # file:// or local:// are considered valid local sources
            if isinstance(ckan_url, str) and (ckan_url.startswith('local://') or ckan_url.startswith('file://')):
                self.util.msg_log_debug(u'特殊スキーマのURL検出: {0}'.format(ckan_url))
                return True, ckan_url
            
            # BoxDriveなどのタイムアウトを防ぐため、ドライブレターの場合は特別処理
            if isinstance(ckan_url, str) and len(ckan_url) > 2 and ckan_url[1:3] == ':\\':
                drive_letter = ckan_url[0].upper()
                # BoxDriveはB:ドライブを使うことが多い
                if drive_letter == 'B':
                    self.util.msg_log(u'【BoxDrive検出】BoxDriveのドライブレター(B:)を検出: {0}'.format(ckan_url))
                    self.util.msg_log(u'【BoxDrive処理】ドライブレターBを持つパスをBoxDriveとして処理します')
                    self.util.msg_log(u'【BoxDrive状態】URL検証をスキップして有効と判定します')
                    return True, ckan_url
                
            # クラウドドライブやネットワークドライブの可能性を確認（タイムアウト制御あり）
            if isinstance(ckan_url, str):
                is_accessible = self._is_accessible_path(ckan_url)
                if is_accessible:
                    self.util.msg_log_debug(u'アクセス可能なディレクトリパス検出: {0}'.format(ckan_url))
                    return True, ckan_url
                
        except Exception as e:
            # if any error occurs during local detection, fall back to normal validation
            self.util.msg_log_error(u'ローカルパス検証中のエラー: {0} - {1}'.format(ckan_url, str(e)))
            
            # 例外が発生した場合でも、BoxDriveなどの特定パターンは例外的に許可
            if isinstance(ckan_url, str) and ('Box' in ckan_url or 'B:\\' in ckan_url):
                self.util.msg_log_warning(u'BoxDriveパターンを例外的に許可: {0}'.format(ckan_url))
                return True, ckan_url
                
            pass

        # HTTP APIチェック
        if not isinstance(ckan_url, str):
            return False, self.util.tr(u"cc_wrong_api")
            
        if not ckan_url.endswith("/"):
            ckan_url += "/"
            
        # データカタログ横断検索システムのAPI URLは特別な形式（backend/api/）を使用
        if ckan_url.endswith("backend/api/"):
            return True, ckan_url
            
        # 標準CKAN APIのバージョンチェック
        if not ckan_url.endswith("3/"):  # was bei neuen APIS > 3?
            self.util.msg_log_debug(u'unsupported API version: {0}'.format(ckan_url))
            return False, self.util.tr(u"cc_wrong_api")

        return True, ckan_url
