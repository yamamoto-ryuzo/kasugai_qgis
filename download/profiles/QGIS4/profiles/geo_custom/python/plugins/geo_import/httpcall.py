# -*- coding: utf-8 -*-

import inspect

from urllib.parse import unquote
from qgis.PyQt.QtCore import QEventLoop
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkReply
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsApplication
from qgis.core import QgsNetworkAccessManager

from .settings import Settings
from .util import Util


class RequestsException(Exception):
    pass


class RequestsExceptionTimeout(RequestsException):
    pass


class RequestsExceptionConnectionError(RequestsException):
    pass


class RequestsExceptionUserAbort(RequestsException):
    pass


class HttpCall:
    """
    Wrapper around gsNetworkAccessManager and QgsAuthManager to make HTTP calls.
    """

    def __init__(self, settings, util):
        # 設定とユーティリティクラスのインスタンスを保持
        assert isinstance(settings, Settings)
        assert isinstance(util, Util)
        self.settings = settings
        self.util = util
        self.reply = None

    # Qt5 / Qt6 の違いで QNetworkReply のエラー定数が名前空間化されている場合があるため
    # ここで互換性用の定数を解決しておく（Qt5/Qt6対応）
    try:
        QNR_NO_ERROR = QNetworkReply.NoError
        QNR_TIMEOUT_ERROR = QNetworkReply.TimeoutError
        QNR_CONNECTION_REFUSED_ERROR = QNetworkReply.ConnectionRefusedError
    except AttributeError:
        # Qt6: QNetworkReply.NetworkError.<Name>
        try:
            QNR_NO_ERROR = QNetworkReply.NetworkError.NoError
            QNR_TIMEOUT_ERROR = QNetworkReply.NetworkError.TimeoutError
            QNR_CONNECTION_REFUSED_ERROR = QNetworkReply.NetworkError.ConnectionRefusedError
        except Exception:
            # 最終フォールバック: 既存属性に頼る（互換性のため）
            QNR_NO_ERROR = getattr(QNetworkReply, 'NoError', 0)
            QNR_TIMEOUT_ERROR = getattr(QNetworkReply, 'TimeoutError', 1)
            QNR_CONNECTION_REFUSED_ERROR = getattr(QNetworkReply, 'ConnectionRefusedError', 2)

    
    def execute_request(self, url, **kwargs):
        """
        Uses QgsNetworkAccessManager and QgsAuthManager.
        """
        # HTTPメソッドを取得（デフォルトはget）
        method = kwargs.get('http_method', 'get')

        headers = kwargs.get('headers', {})
        # 圧縮コンテンツが正しく展開されない問題を修正
        # QNetworkRequestにこのヘッダーを設定すると、QNetworkAccessManagerに
        # 「自分で処理するからコンテンツエンコーディング処理はしないでください」と伝えることになる
        # 参照: https://bugs.webkit.org/show_bug.cgi?id=63696#c1
        try:
            del headers[b'Accept-Encoding']
        except KeyError as ke:
            # 1回目の削除後は存在しないため、デバッグレベルでログ出力
            self.util.msg_log_debug(u'unexpected error deleting request header: {}'.format(ke))
            pass

        # QUrlによる二重クォートを回避
        url = unquote(url)

        self.util.msg_log_debug(u'http_call request: {} {}'.format(method, url))

        # レスポンスオブジェクトの定義
        class Response:
            status_code = 200
            status_message = 'OK'
            text = ''
            ok = True
            headers = {}
            reason = ''
            exception = None

            def iter_content(self, _):
                return [self.text]

        self.http_call_result = Response()
        url = self.util.remove_newline(url)

        # ネットワークリクエストを作成
        req = QNetworkRequest()
        req.setUrl(QUrl(url))
        # FollowRedirectsAttribute は Qt のバージョンで存在しない場合があるため
        # 存在チェックしてから設定する（Qt5/Qt6互換性のため）
        try:
            attr_ns = getattr(QNetworkRequest, 'Attribute', None)
            if attr_ns is not None and hasattr(attr_ns, 'FollowRedirectsAttribute'):
                req.setAttribute(attr_ns.FollowRedirectsAttribute, True)
            elif hasattr(QNetworkRequest, 'FollowRedirectsAttribute'):
                req.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
            else:
                self.util.msg_log_debug('QNetworkRequest FollowRedirectsAttribute not available; skipping setAttribute')
        except Exception:
            # 何らかの予期せぬ問題があればログに残して続行
            self.util.msg_log_error('error setting FollowRedirectsAttribute on QNetworkRequest')
            self.util.msg_log_last_exception()

        for k, v in headers.items():
            self.util.msg_log_debug("%s: %s" % (k, v))
            try:
                req.setRawHeader(k, v)
            except:
                self.util.msg_log_error(u'FAILED to set header: {} => {}'.format(k, v))
                self.util.msg_log_last_exception()
        if self.settings.authcfg:
            self.util.msg_log_debug(u'before updateNetworkRequest')
            QgsApplication.authManager().updateNetworkRequest(req, self.settings.authcfg)
            self.util.msg_log_debug(u'before updateNetworkRequest')

        if self.reply is not None and self.reply.isRunning():
            self.reply.close()

        self.util.msg_log_debug(u'getting QgsNetworkAccessManager.instance()')
        #func = getattr(QgsNetworkAccessManager.instance(), method)
        #func = QgsNetworkAccessManager().get(req)




        #manager = QNetworkAccessManager()
        #event = QEventLoop()
        #response = manager.get(QNetworkRequest(QUrl(url)))
        #response.downloadProgress.connect(self.download_progress)
        #response.finished.connect(event.quit)
        #event.exec()
        #response_msg = response.readAll()
        ##response_msg = str(response_msg)
        #response_msg = str(response_msg, encoding='utf-8')
        ##response_msg = response_msg.decode('utf-8')
        #response.deleteLater()
        #self.util.msg_log_debug(u'response message:\n{} ...'.format(response_msg[:255]))
        #self.http_call_result.text = response_msg  # in Python3 all strings are unicode, so QString is not defined
        #return self.http_call_result



        # Calling the server ...
        self.util.msg_log_debug('before self.reply = func(req)')
        #self.reply = func(req)
        #self.reply = QgsNetworkAccessManager.instance().get(req)
        method_call = getattr(QgsNetworkAccessManager.instance(), method)
        self.reply = method_call(req)
        #self.reply.setReadBufferSize(1024*1024*1024)
        #self.reply.setReadBufferSize(1024 * 1024 * 1024 * 1024)
        self.reply.setReadBufferSize(0)
        self.util.msg_log_debug('after self.reply = func(req)')

        # Let's log the whole call for debugging purposes:
        if self.settings.debug:
            self.util.msg_log_debug("\nSending %s request to %s" % (method.upper(), req.url().toString()))
            headers = {str(h): str(req.rawHeader(h)) for h in req.rawHeaderList()}
            for k, v in headers.items():
                try:
                    self.util.msg_log_debug("%s: %s" % (k, v))
                except:
                    self.util.msg_log_debug('error logging headers')

        if self.settings.authcfg:
            self.util.msg_log_debug("update reply w/ authcfg: {0}".format(self.settings.authcfg))
            QgsApplication.authManager().updateNetworkReply(self.reply, self.settings.authcfg)

        self.util.msg_log_debug('before connecting to events')

        # connect downloadProgress event
        try:
            self.reply.downloadProgress.connect(self.download_progress)
            #pass
        except:
            self.util.msg_log_error('error connecting "downloadProgress" event')
            self.util.msg_log_last_exception()

        # connect reply finished event
        try:
            self.reply.finished.connect(self.reply_finished)
            #pass
        except:
            self.util.msg_log_error('error connecting reply "finished" progress event')
            self.util.msg_log_last_exception()
        self.util.msg_log_debug('after connecting to events')

        # Call and block
        self.event_loop = QEventLoop()
        try:
            self.reply.finished.connect(self.event_loop.quit)
        except:
            self.util.msg_log_error('error connecting reply "finished" progress event to event loop quit')
            self.util.msg_log_last_exception()

        self.mb_downloaded = 0
        # Catch all exceptions (and clean up requests)
        self.event_loop.exec()

        # Let's log the whole response for debugging purposes:
        if self.settings.debug:
            self.util.msg_log_debug(
                u'\nGot response [{}/{}] ({} bytes) from:\n{}\nexception:{}'.format(
                    self.http_call_result.status_code,
                    self.http_call_result.status_message,
                    len(self.http_call_result.text),
                    self.reply.url().toString(),
                    self.http_call_result.exception
                )
            )
            headers = {str(h): str(self.reply.rawHeader(h)) for h in self.reply.rawHeaderList()}
            for k, v in headers.items():
                self.util.msg_log_debug("%s: %s" % (k, v))
            self.util.msg_log_debug("Payload :\n%s ......" % self.http_call_result.text[:255])

        self.reply.close()
        self.util.msg_log_debug("Deleting reply ...")
        try:
            self.reply.deleteLater()
        except:
            self.util.msg_log_error('unexpected error deleting QNetworkReply')
            self.util.msg_log_last_exception()

        self.reply = None

        if self.http_call_result.exception is not None:
            self.util.msg_log_error('http_call_result.exception is not None')
            self.http_call_result.ok = False
            # raise self.http_call_result.exception
        return self.http_call_result

    def download_progress(self, bytes_received, bytes_total):
        mb_received = bytes_received / (1024 * 1024)
        if mb_received - self.mb_downloaded >= 1:
            self.mb_downloaded = mb_received
            self.util.msg_log_debug(
                u'downloadProgress {:.1f} of {:.1f} MB" '
                .format(mb_received, bytes_total / (1024 * 1024))
            )

    def reply_finished(self):
        self.util.msg_log_debug('------- reply_finished')
        try:
            err = self.reply.error()
            # Qt6では QNetworkRequest.Attribute.<Name> へ移動している
            try:
                httpStatus = self.reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                httpStatusMessage = self.reply.attribute(QNetworkRequest.Attribute.HttpReasonPhraseAttribute)
            except AttributeError:
                httpStatus = self.reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                httpStatusMessage = self.reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
            self.http_call_result.status_code = httpStatus
            self.http_call_result.status_message = httpStatusMessage
            for k, v in self.reply.rawHeaderPairs():
                self.http_call_result.headers[k.data().decode()] = v.data().decode()
                self.http_call_result.headers[k.data().decode().lower()] = v.data().decode()
            if err == self.QNR_NO_ERROR:
                self.util.msg_log_debug('QNetworkReply.NoError')
                self.http_call_result.text = self.reply.readAll()
                self.http_call_result.ok = True
            else:
                self.util.msg_log_error('QNetworkReply Error')
                self.http_call_result.ok = False
                msg = "Network error #{0}: {1}"\
                    .format(
                        self.reply.error(),
                        self.reply.errorString()
                )
                self.http_call_result.reason = msg
                self.util.msg_log_error(msg)
                if err == QNR_TIMEOUT_ERROR:
                    self.http_call_result.exception = RequestsExceptionTimeout(msg)
                if err == self.QNR_CONNECTION_REFUSED_ERROR:
                    self.http_call_result.exception = RequestsExceptionConnectionError(msg)
                else:
                    self.http_call_result.exception = Exception(msg)
        except:
            self.util.msg_log_error(u'unexpected error in {}'.format(inspect.stack()[0][3]))
            self.util.msg_log_last_exception()
