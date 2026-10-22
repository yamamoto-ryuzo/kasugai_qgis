# -*- coding: utf-8 -*-
"""KASUGAI Canvas 連携エクスポート。

QGIS プロジェクトの表示中ベクターレイヤーを GeoJSON + QGISスタイル(.qml)
として出力し、KASUGAI Canvas プロジェクト形式(.kasc + DATA/)を生成する。

KASUGAI Canvas は ``geojson: タイトル | DATA/x.geojson | on | style=DATA/x.qml``
形式の .kasc 行を読み、.qml の <renderer-v2> を Cesium 描画へコンパイルする。
ローカルサーバー版(port 8510)が起動していれば
``POST /api/projects/register {path: <kasc>}`` で外部プロジェクトとして
登録でき、そのまま ``?project=<id>`` で開ける(登録フォルダの DATA/ が
そのまま配信される)。``POST /api/command`` の switchProject で
起動中の画面を切り替えることもできる。

このモジュールは PyQGIS 環境でのみ使用する(ユニットテスト不可)。
ネットワーク呼び出しは全て短いタイムアウト付きのベストエフォート。
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

# KASUGAI Canvas ローカルサーバーの既定ポート(run.py _get_port と同じ)
DEFAULT_KASUGAI_PORT = 8510
SETTINGS_KEY_OUTPUT = 'kasugai_output_path'
SETTINGS_KEY_PORT = 'kasugai_port'


def _qsettings():
    from qgis.PyQt.QtCore import QSettings
    return QSettings('GeoWebView', 'geo_webview')


def default_output_dir():
    """既定出力先: <ドキュメント>/kasugai_canvas_qgis。"""
    try:
        from qgis.PyQt.QtCore import QStandardPaths
        loc = getattr(
            getattr(QStandardPaths, 'StandardLocation', QStandardPaths),
            'DocumentsLocation')
        docs = QStandardPaths.writableLocation(loc)
        if docs:
            return os.path.join(docs, 'kasugai_canvas_qgis')
    except Exception:  # nosec B110  # 設計上の許容
        pass
    import tempfile
    return os.path.join(tempfile.gettempdir(), 'kasugai_canvas_qgis')


def get_output_dir():
    """QSettings の kasugai_output_path(空/'__default__'は既定)を返す。"""
    try:
        saved = _qsettings().value(SETTINGS_KEY_OUTPUT, '') or ''
        saved = str(saved).strip()
        if saved and saved != '__default__':
            return saved
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return default_output_dir()


def get_kasugai_port():
    """QSettings の kasugai_port(未設定は8510)を返す。"""
    try:
        saved = _qsettings().value(SETTINGS_KEY_PORT, '') or ''
        if str(saved).strip():
            return int(str(saved).strip())
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return DEFAULT_KASUGAI_PORT


def _slugify(name, used):
    """レイヤ名からDATA/用の安全なファイル名(ASCII)を作る。"""
    slug = re.sub(r'[^A-Za-z0-9_\-]+', '_', str(name or '')).strip('_')
    if not slug:
        slug = 'layer'
    base = slug
    i = 2
    while slug.lower() in used:
        slug = '{0}_{1}'.format(base, i)
        i += 1
    used.add(slug.lower())
    return slug


def _kasc_escape(text):
    """.kasc 行の | 区切り・改行を壊さないようサニタイズする。"""
    return re.sub(r'[|\r\n]+', ' ', str(text or '')).strip()


def _visible_tree_layers():
    """レイヤツリー順(上から)に表示中レイヤを (layer, group_path) で返す。

    ノード自身のチェックと全祖先の表示状態が両方ONのものだけ。
    """
    from qgis.core import QgsProject
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    result = []

    def _walk(node, groups, visible):
        from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer
        for child in node.children():
            try:
                checked = child.itemVisibilityChecked()
            except Exception:
                checked = True
            eff = visible and bool(checked)
            if isinstance(child, QgsLayerTreeGroup):
                _walk(child, groups + [child.name()], eff)
            elif isinstance(child, QgsLayerTreeLayer):
                lyr = child.layer()
                if lyr is not None and eff:
                    result.append((lyr, list(groups)))

    _walk(root, [], True)
    return result


def _export_geojson(layer, path):
    """ベクターレイヤを EPSG:4326 の GeoJSON へ書き出す。"""
    from qgis.core import (QgsCoordinateReferenceSystem,
                           QgsCoordinateTransform, QgsProject,
                           QgsVectorFileWriter)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GeoJSON'
    options.fileEncoding = 'UTF-8'
    options.ct = QgsCoordinateTransform(
        layer.crs(), QgsCoordinateReferenceSystem('EPSG:4326'),
        QgsProject.instance())
    if hasattr(QgsVectorFileWriter, 'writeAsVectorFormatV3'):
        err, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, path, QgsProject.instance().transformContext(), options)
    else:
        err, msg = QgsVectorFileWriter.writeAsVectorFormatV2(
            layer, path, QgsProject.instance().transformContext(), options)
    if err != QgsVectorFileWriter.NoError:
        raise RuntimeError('GeoJSON export failed: {0} ({1})'.format(err, msg))
    return path


def _export_qml(layer, path):
    """レイヤの現在スタイルを .qml として保存する。"""
    msg, ok = layer.saveNamedStyle(path)
    if not ok:
        raise RuntimeError('qml save failed: {0}'.format(msg))
    return path


def _xyz_layer_info(layer):
    """XYZタイル系ラスタレイヤなら (url, zmin, zmax) を返す。

    source URI は ``key=value&key=value`` 形式で url 値は
    パーセントエンコード済み(&を含まない)。値だけをunquoteすることで
    url内の ``x={x}&y={y}&z={z}`` を保持する。
    """
    try:
        if layer.providerType() not in ('wms',):
            return None
        src = layer.source() or ''
        if 'type=xyz' not in src and 'type%3Dxyz' not in src.lower():
            return None
        params = {}
        for part in src.split('&'):
            if '=' not in part:
                continue
            key, val = part.split('=', 1)
            params[key.strip().lower()] = urllib.parse.unquote(val.strip())
        url = params.get('url')
        if not url:
            return None

        def _num(name):
            try:
                return int(params[name])
            except Exception:
                return None
        return url, _num('zmin'), _num('zmax')
    except Exception:
        return None


def _camera_line(iface, height_hint_scale=None):
    """現在キャンバスから cam: 行を作る。失敗時 None。"""
    try:
        from qgis.core import (QgsCoordinateReferenceSystem,
                               QgsCoordinateTransform, QgsPointXY,
                               QgsProject)
        canvas = iface.mapCanvas()
        ext = canvas.extent()
        crs = canvas.mapSettings().destinationCrs()
        tr = QgsCoordinateTransform(
            crs, QgsCoordinateReferenceSystem('EPSG:4326'),
            QgsProject.instance())
        c = tr.transform(QgsPointXY(ext.center().x(), ext.center().y()))
        scale = float(canvas.scale() or 10000)
        # 概算: 画面高~800px * 0.28mm/px * scale を地上高、
        # Cesium fov60° より h ≒ 地上高/1.15 → scale*0.2
        h = max(120.0, scale * 0.2)
        line = 'cam:QGIS|{0:.6f}|{1:.6f}|h={2:.0f}|p=-90'.format(
            c.y(), c.x(), h)
        try:
            rot = float(canvas.rotation())
            if abs(rot) > 0.01:
                line += '|d={0:.1f}'.format(rot % 360)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return line
    except Exception:
        return None


def export_kasugai_project(iface, out_dir=None, visible_only=True):
    """表示中レイヤを KASUGAI Canvas プロジェクトとして出力する。

    戻り値: {"dir","kasc","data_dir","layers":[{name,file,features}],
             "tiles":[...],"skipped":[...],"errors":[...]}。
    layers が1件も無くても .kasc は出力する。
    """
    from qgis.core import QgsVectorLayer, QgsProject
    out_dir = os.path.abspath(out_dir or get_output_dir())
    data_dir = os.path.join(out_dir, 'DATA')
    os.makedirs(data_dir, exist_ok=True)

    project = QgsProject.instance()
    project_title = os.path.splitext(
        os.path.basename(project.fileName() or ''))[0] or 'QGIS Export'

    used_names = set()
    layers_out, tiles_out, skipped, errors = [], [], [], []
    kasc_lines = []

    tree = _visible_tree_layers() if visible_only else [
        (lyr, []) for lyr in project.mapLayers().values()
        if lyr is not None]

    for layer, groups in tree:
        title = '/'.join(
            [_kasc_escape(g) for g in groups if g] +
            [_kasc_escape(layer.name())])
        if isinstance(layer, QgsVectorLayer):
            slug = _slugify(layer.name() or 'layer', used_names)
            gj_path = os.path.join(data_dir, slug + '.geojson')
            qml_path = os.path.join(data_dir, slug + '.qml')
            try:
                _export_geojson(layer, gj_path)
            except Exception as e:
                errors.append('{0}: geojson {1}'.format(layer.name(), e))
                continue
            style_opt = ''
            try:
                _export_qml(layer, qml_path)
                style_opt = ' | style=DATA/{0}.qml'.format(slug)
            except Exception as e:
                errors.append('{0}: qml {1}'.format(layer.name(), e))
            feat_count = -1
            try:
                feat_count = int(layer.featureCount())
            except Exception:  # nosec B110  # 設計上の許容
                pass
            layers_out.append({
                'name': layer.name(), 'title': title,
                'file': 'DATA/{0}.geojson'.format(slug),
                'qml': 'DATA/{0}.qml'.format(slug) if style_opt else None,
                'features': feat_count,
            })
            kasc_lines.append(
                'geojson: {0} | DATA/{1}.geojson | on{2}'.format(
                    title, slug, style_opt))
        else:
            xyz = _xyz_layer_info(layer)
            if xyz:
                url, zmin, zmax = xyz
                line = 'xyz: {0} | {1} | on'.format(title, _kasc_escape(url))
                if zmax is not None:
                    line += ' | maxZoom={0}'.format(zmax)
                if zmin is not None:
                    line += ' | minZoom={0}'.format(zmin)
                tiles_out.append({'name': layer.name(), 'url': url})
                kasc_lines.append(line)
            else:
                skipped.append(layer.name())

    cam = _camera_line(iface)
    header = [
        '# Exported from QGIS geo_webview -> KASUGAI Canvas',
        'base: 地理院タイル 標準地図 | '
        'https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png | '
        '出典：国土地理院 | maxZoom=18',
        'base: 地理院タイル 淡色地図 | '
        'https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png | '
        '出典：国土地理院 | maxZoom=18',
        'base: 地理院タイル 全国最新写真 | '
        'https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg | '
        '出典：国土地理院 | maxZoom=18',
        'base: OpenStreetMap | https://tile.openstreetmap.org/{z}/{x}/{y}.png | '
        '(c) OpenStreetMap contributors | maxZoom=19',
    ]
    if cam:
        header.append(cam)

    kasc_path = os.path.join(out_dir, 'kasugai_canvas.kasc')
    with open(kasc_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(header + kasc_lines) + '\n')
    with open(os.path.join(out_dir, 'project.json'), 'w',
              encoding='utf-8') as f:
        json.dump({'title': project_title}, f, ensure_ascii=False)

    return {
        'dir': out_dir, 'kasc': kasc_path, 'data_dir': data_dir,
        'title': project_title, 'layers': layers_out,
        'tiles': tiles_out, 'skipped': skipped, 'errors': errors,
    }


def _http_json(url, payload=None, timeout=2.0, method=None):
    """小さなJSON HTTP呼び出し。payload無しはGET。"""
    if urllib.parse.urlparse(url).scheme not in ('http', 'https'):
        raise ValueError('unsupported URL scheme: {0}'.format(url))
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method)
    with urllib.request.urlopen(req, timeout=timeout) as res:  # nosec B310  # 直上でhttp/httpsスキームを検証済み
        body = res.read(65536)
    return json.loads(body.decode('utf-8'))


def detect_kasugai(port=None):
    """KASUGAIローカルサーバが稼働していればcapabilitiesを返す。"""
    port = int(port or get_kasugai_port())
    try:
        caps = _http_json(
            'http://localhost:{0}/api/capabilities'.format(port),
            timeout=1.5)
        if isinstance(caps, dict):
            caps['_port'] = port
            return caps
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return None


def register_kasugai_project(kasc_path, port=None):
    """POST /api/projects/register で.kascを外部プロジェクト登録する。

    戻り値: {"ok":True,"id":...,"url":...} または {"ok":False,"error":...}
    """
    port = int(port or get_kasugai_port())
    try:
        res = _http_json(
            'http://localhost:{0}/api/projects/register'.format(port),
            payload={'path': os.path.abspath(kasc_path)}, timeout=4.0)
        pid = res.get('id')
        if res.get('ok') and pid:
            return {'ok': True, 'id': pid,
                    'url': 'http://localhost:{0}/?project={1}'.format(
                        port, urllib.parse.quote(str(pid)))}
        return {'ok': False, 'error': str(res)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def kasugai_command(name, args=None, port=None):
    """POST /api/command でチャットツールをキューイング(ベストエフォート)。"""
    port = int(port or get_kasugai_port())
    try:
        res = _http_json(
            'http://localhost:{0}/api/command'.format(port),
            payload={'name': name, 'args': args or {}}, timeout=4.0)
        return {'ok': bool(res.get('ok')), 'response': res}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
