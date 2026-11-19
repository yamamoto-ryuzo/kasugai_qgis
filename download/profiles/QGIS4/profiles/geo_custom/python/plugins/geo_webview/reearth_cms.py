# -*- coding: utf-8 -*-
"""Re:Earth CMS 連携(Issue #11)。

Re:Earth CMS Integration API を使い、geo_webview から

- Phase 1: ベクタレイヤを CMS アイテムとして登録する
  (選択フィーチャのみ/全フィーチャ、属性↔CMSフィールドのマッピング付き)
- Phase 2: .kasc+canvas_data/ の出力物一式を ZIP 化して CMS アセットとして
  アップロード・公開し、assets.cms.reearth.io の公開URLを取得する

を行う。読み取り側(CMSアイテムのレイヤ読み込み等)は kasugai_canvas
側の対応(Issue #132)が担う。

API基礎:
  Integration API: https://api.cms.reearth.io/api/<workspace>/
    Bearer <integration token>
    POST /{ws}/projects/{proj}/models/{model}/items     アイテム作成
    POST /{ws}/projects/{proj}/items/{itemId}/publish   アイテム公開
    POST /{ws}/projects/{proj}/assets                    アセット作成
                                                      (multipart file)
    POST /{ws}/assets/{assetId}/publish                  アセット公開
    GET  /{ws}/assets/{assetId}                          アセット取得
    GET  /{ws}/projects/{proj}/models/{model}/schema.json スキーマ取得
  workspace/project/model は ID でも alias/key でも指定可
  (IdOrAlias / IdOrKey パラメータ)。

シークレット管理:
  インテグレーショントークンはリポジトリへコミットしない。
  保持先は環境変数 REEARTH_CMS_TOKEN を最優先とし、未設定時のみ
  QSettings(GeoWebView/geo_webview, reearth_cms_token)を使う。
  bridge はトークン値そのものを返さず has_token/token_source のみ報告する。

このモジュールは PyQGIS 環境でのみ使用する(レイヤ→アイテム変換部)。
HTTP クライアント部は urllib のみで、外部依存を追加しない。
ネットワーク呼び出しは全てタイムアウト付き。
"""

import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

DEFAULT_API_BASE = 'https://api.cms.reearth.io/api'
ENV_TOKEN = 'REEARTH_CMS_TOKEN'  # nosec B105  # 環境変数名(秘密値ではない)

SKEY_BASE = 'reearth_cms_base'
SKEY_WORKSPACE = 'reearth_cms_workspace'
SKEY_PROJECT = 'reearth_cms_project'
SKEY_MODEL = 'reearth_cms_model'
SKEY_TOKEN = 'reearth_cms_token'  # nosec B105  # QSettingsキー名(秘密値ではない)

_TIMEOUT = 30.0
_DEFAULT_MAX_FEATURES = 500


class CmsError(Exception):
    """CMS API の失敗(HTTPエラー・未設定・パラメータ不正)。"""


def _qsettings():
    from qgis.PyQt.QtCore import QSettings
    return QSettings('GeoWebView', 'geo_webview')


def get_settings():
    """CMS 接続設定を返す(トークン値は含めない)。"""
    s = _qsettings()
    token = get_token()
    return {
        'base_url': s.value(SKEY_BASE, '') or DEFAULT_API_BASE,
        'workspace': s.value(SKEY_WORKSPACE, ''),
        'project': s.value(SKEY_PROJECT, ''),
        'model': s.value(SKEY_MODEL, ''),
        'has_token': bool(token),
        'token_source': 'env' if os.environ.get(ENV_TOKEN) else
                        ('qsettings' if s.value(SKEY_TOKEN, '') else 'none'),
    }


def save_settings(base_url=None, workspace=None, project=None,
                  model=None, token=None):
    """CMS 接続設定を保存する。None の項目は変更しない。"""
    s = _qsettings()
    applied = {}
    if base_url is not None:
        v = (base_url or '').strip().rstrip('/') or DEFAULT_API_BASE
        s.setValue(SKEY_BASE, v)
        applied['base_url'] = v
    if workspace is not None:
        s.setValue(SKEY_WORKSPACE, str(workspace).strip())
        applied['workspace'] = str(workspace).strip()
    if project is not None:
        s.setValue(SKEY_PROJECT, str(project).strip())
        applied['project'] = str(project).strip()
    if model is not None:
        s.setValue(SKEY_MODEL, str(model).strip())
        applied['model'] = str(model).strip()
    if token is not None:
        s.setValue(SKEY_TOKEN, str(token).strip())
        applied['token'] = 'set' if token else 'cleared'
    return applied


def get_token():
    """インテグレーショントークン。環境変数 REEARTH_CMS_TOKEN 優先。"""
    return (os.environ.get(ENV_TOKEN) or
            _qsettings().value(SKEY_TOKEN, '') or '')


def _require(*names):
    st = get_settings()
    missing = [n for n in names if not st.get(n)]
    if missing:
        raise CmsError(
            'CMS設定が不足しています: {0} (cmsSettings で設定)'.format(
                ', '.join(missing)))
    if not get_token():
        raise CmsError(
            'インテグレーショントークンが未設定です(環境変数 {0} または '
            'cmsSettings の token)'.format(ENV_TOKEN))
    return st


def _request(method, path, body=None, headers=None, raw_body=None,
             content_type=None):
    """Integration API への1リクエスト。失敗は CmsError として表面化する。"""
    st = _require('workspace')
    url = '{0}/{1}{2}'.format(st['base_url'],
                              urllib.parse.quote(st['workspace'], safe=''),
                              path)
    h = {'Authorization': 'Bearer ' + get_token(),
         'Accept': 'application/json'}
    if headers:
        h.update(headers)
    data = raw_body
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        h['Content-Type'] = 'application/json'
    if content_type:
        h['Content-Type'] = content_type
    if urllib.parse.urlparse(url).scheme not in ('http', 'https'):
        raise CmsError('unsupported URL scheme: {0}'.format(url))
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as res:  # nosec B310  # 直上でhttp/httpsスキームを検証済み
            data = res.read()
            ctype = res.headers.get('Content-Type', '')
            if b'json' in ctype.encode('ascii', 'ignore'):
                return json.loads(data.decode('utf-8'))
            return {'_raw': data.decode('utf-8', 'replace')}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode('utf-8', 'replace')[:2000]
        except Exception:
            detail = str(e)
        raise CmsError(
            'CMS API {0} {1} -> HTTP {2}: {3}'.format(
                method, path, e.code, detail))
    except urllib.error.URLError as e:
        raise CmsError(
            'CMS API {0} {1} 接続失敗: {2}'.format(method, path, e.reason))


def _quote(seg):
    return urllib.parse.quote(str(seg), safe='')


def _project_path(st):
    return '/projects/{0}'.format(_quote(st['project']))


def _multipart(file_field, file_path, fields=None):
    """multipart/form-data の body を自前構築する(requests 非依存)。"""
    boundary = '----geoWebview' + uuid.uuid4().hex
    parts = []
    for k, v in (fields or {}).items():
        parts.append(
            ('--{0}\r\nContent-Disposition: form-data; name="{1}"\r\n\r\n'
             '{2}\r\n').format(boundary, k, v).encode('utf-8'))
    fname = os.path.basename(file_path)
    with open(file_path, 'rb') as f:
        payload = f.read()
    parts.append(
        ('--{0}\r\nContent-Disposition: form-data; name="{1}"; '
         'filename="{2}"\r\nContent-Type: application/octet-stream\r\n\r\n'
         ).format(boundary, file_field, fname).encode('utf-8'))
    parts.append(payload)
    parts.append('\r\n--{0}--\r\n'.format(boundary).encode('utf-8'))
    return b''.join(parts), 'multipart/form-data; boundary=' + boundary


# ---------- モデル / スキーマ ----------

def get_schema(workspace=None, project=None, model=None):
    """モデルのスキーマ(フィールド定義)を返す。"""
    st = _require('workspace', 'project', 'model')
    proj = project or st['project']
    mdl = model or st['model']
    return _request(
        'GET',
        '/projects/{0}/models/{1}/schema.json'.format(
            _quote(proj), _quote(mdl)))


# ---------- Phase 1: レイヤ → CMS アイテム ----------

def _qvariant_to_value(v):
    """QgsVectorLayer の属性値を CMS フィールド値に変換する。"""
    try:
        from qgis.core import NULL
        if v is NULL:
            return None
    except Exception:  # nosec B110  # QGIS外ではimport自体が失敗し得る
        pass
    try:
        from qgis.PyQt.QtCore import (QDate, QDateTime, QTime, QByteArray,
                                      QVariant, Qt)
        if isinstance(v, (QDate, QDateTime, QTime)):
            return v.toString(Qt.DateFormat.ISODate)
        if isinstance(v, QByteArray):
            return bytes(v).decode('utf-8', 'replace')
        if isinstance(v, QVariant):
            return _qvariant_to_value(v.value())
    except Exception:  # nosec B110  # QGIS外ではimport自体が失敗し得る
        pass
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    try:
        return str(v)
    except Exception:
        return None


def _iter_layer_features(layer, selected_only):
    if selected_only:
        return layer.selectedFeatures()
    return layer.getFeatures()


def layer_to_items(layer, mapping=None, geometry_key=None,
                   selected_only=False):
    """ベクタレイヤを CMS アイテム作成用フィールド配列へ変換する。

    mapping: {属性名: CMSフィールドkey}。未指定の属性は属性名=フィールドkey
    の同名自動対応。mapping 値が None/'' の属性は送らない。
    geometry_key: 指定時、地物ジオメトリを GeoJSON geometry オブジェクト
    としてその key のフィールドへ格納する(CMS の geometryObject/
    geometryEditor フィールド向け。CRS は EPSG:4326 へ変換する)。
    """
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, \
        QgsProject

    mapping = mapping or {}
    crs4326 = QgsCoordinateReferenceSystem('EPSG:4326')
    xform = None
    if geometry_key:
        try:
            xform = QgsCoordinateTransform(layer.crs(), crs4326,
                                           QgsProject.instance())
        except Exception:
            xform = None
    items = []
    field_names = [f.name() for f in layer.fields()]
    for feat in _iter_layer_features(layer, selected_only):
        fields = []
        attrs = feat.attributes()
        for i, name in enumerate(field_names):
            key = mapping.get(name, name)
            if not key:
                continue
            value = _qvariant_to_value(attrs[i]) if i < len(attrs) else None
            fields.append({'key': key, 'value': value})
        if geometry_key:
            geom = feat.geometry()
            if geom and not geom.isNull():
                if xform is not None:
                    geom.transform(xform)
                fields.append({'key': geometry_key,
                               'value': json.loads(geom.asJson())})
        items.append({'fields': fields})
    return items


def create_item(item, project=None, model=None):
    """POST /projects/{p}/models/{m}/items でアイテムを1件作成する。"""
    st = _require('workspace', 'project', 'model')
    proj = project or st['project']
    mdl = model or st['model']
    return _request(
        'POST',
        '/projects/{0}/models/{1}/items'.format(_quote(proj), _quote(mdl)),
        body=item)


def publish_item(item_id, project=None):
    """アイテムを公開状態にする(Public API で読めるようにする)。"""
    st = _require('workspace', 'project')
    proj = project or st['project']
    return _request(
        'POST',
        '/projects/{0}/items/{1}/publish'.format(
            _quote(proj), _quote(item_id)))


def register_layer(layer_name=None, mapping=None, geometry_key=None,
                   selected_only=False, publish=False,
                   max_features=_DEFAULT_MAX_FEATURES):
    """指定(またはアクティブ)ベクタレイヤを CMS アイテムとして登録する。

    戻り値: {layer, model, created, failed, item_ids, errors}
    """
    from qgis.core import QgsMapLayer, QgsProject
    from qgis.utils import iface

    layer = None
    if layer_name:
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == layer_name or lyr.id() == layer_name:
                layer = lyr
                break
        if layer is None:
            raise CmsError('レイヤが見つかりません: {0}'.format(layer_name))
    else:
        layer = iface.activeLayer()
        if layer is None:
            raise CmsError('アクティブレイヤがありません')
    if layer.type() != QgsMapLayer.VectorLayer:
        raise CmsError('ベクタレイヤではありません: {0}'.format(layer.name()))

    items = layer_to_items(layer, mapping=mapping,
                           geometry_key=geometry_key,
                           selected_only=selected_only)
    if not items:
        raise CmsError('登録対象フィーチャが0件です({0})'.format(layer.name()))
    if len(items) > max_features:
        raise CmsError(
            'フィーチャ数 {0} が上限 {1} を超えています。'
            '範囲を絞るか max_features を上げてください'.format(
                len(items), max_features))

    created = 0
    item_ids = []
    errors = []
    for i, item in enumerate(items):
        try:
            res = create_item(item)
            iid = res.get('id')
            if iid:
                item_ids.append(iid)
                if publish:
                    publish_item(iid)
            created += 1
        except CmsError as e:
            errors.append({'index': i, 'error': str(e)})
    return {
        'layer': layer.name(), 'layer_id': layer.id(),
        'created': created, 'failed': len(errors),
        'item_ids': item_ids, 'errors': errors[:20],
        'published': bool(publish),
    }


# ---------- Phase 2: .kasc+canvas_data/ → CMS アセット ----------

def zip_export_dir(src_dir, zip_path=None):
    """.kasc+canvas_data/ の出力フォルダ一式を ZIP 化する。"""
    src_dir = os.path.abspath(src_dir)
    if not os.path.isdir(src_dir):
        raise CmsError('出力フォルダが存在しません: {0}'.format(src_dir))
    has_kasc = any(fn.lower().endswith('.kasc')
                   for fn in os.listdir(src_dir))
    if not has_kasc:
        raise CmsError(
            'フォルダ内に .kasc がありません: {0}'.format(src_dir))
    if zip_path is None:
        fd, zip_path = tempfile.mkstemp(
            suffix='.zip', prefix='kasc_cms_')
        os.close(fd)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src_dir):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, src_dir)
                zf.write(full, rel.replace(os.sep, '/'))
    return zip_path


def upload_asset(file_path, project=None):
    """multipart でアセットを作成する。戻り値はアセットJSON。"""
    st = _require('workspace', 'project')
    proj = project or st['project']
    body, ctype = _multipart('file', file_path)
    return _request(
        'POST',
        '/projects/{0}/assets'.format(_quote(proj)),
        raw_body=body, content_type=ctype)


def publish_asset(asset_id):
    """アセットを公開し assets.cms.reearth.io で配信可能にする。"""
    _require('workspace')
    return _request('POST', '/assets/{0}/publish'.format(_quote(asset_id)))


def get_asset(asset_id):
    _require('workspace')
    return _request('GET', '/assets/{0}'.format(_quote(asset_id)))


def upload_kasc_export(export_dir=None, publish=True):
    """.kasc+canvas_data/ 出力物を ZIP 化して CMS アセットとして公開する。

    export_dir 省略時は直近の kasugaiExport 出力先(last_export_dir)。
    戻り値: {asset_id, name, url, zip_path, published}
    """
    _require('workspace', 'project')
    if not export_dir:
        from . import kasugai_export
        export_dir = kasugai_export.last_export_dir()
    if not export_dir:
        raise CmsError(
            'エクスポート出力がありません。先に kasugaiExport を実行してください')
    zip_path = zip_export_dir(export_dir)
    asset = upload_asset(zip_path)
    asset_id = asset.get('id')
    if not asset_id:
        raise CmsError(
            'アセット作成の応答に id がありません: {0}'.format(asset))
    published = False
    if publish:
        publish_asset(asset_id)
        asset = get_asset(asset_id)
        published = True
    return {
        'asset_id': asset_id,
        'name': asset.get('name'),
        'url': asset.get('url'),
        'zip_path': zip_path,
        'export_dir': export_dir,
        'published': published,
    }
