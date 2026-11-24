# -*- coding: utf-8 -*-
"""エクスポートファイル無しで現在の QGIS プロジェクトを .kasc テキスト
としてオンデマンド生成する(3D Canvas View / live ネイティブモード用)。

GET /live/kasc が呼ばれるたびに現在のレイヤツリー・表示状態・
スタイルから .kasc を組み立てる。ベクターは canvas_data/ への
変換・複写を行わず、ファイル/URL ソースはネイティブ形式のまま
``/live/file``(原本配信)を参照し、ファイルを持たないソースは
``/live/features``(GeoJSON オンデマンド配信)へ振り向ける。
スタイルは ``/live/style``(.qml オンデマンド出力)。
「QGIS のデータをそのまま表示」する経路になる。

Canvas がネイティブ再現できないラスタ(GDAL ラスタ等)は
``/live/render``(QGIS 描画 PNG)を ``image:`` 行として出すため、
QML・データ形式が Canvas 未対応でも視覚的には再現される
(QGIS の3Dビューが 2D 描画を地形へ貼るのと同じ発想)。
"""

import os
import re
import tempfile
import urllib.parse

# export_kasugai_project と同じ既定ベースマップ候補(変更時は両方を更新)
_DEFAULT_BASE_LINES = [
    'base: 地理院タイル 標準地図 | '
    'https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png | '
    '出典：国土地理院 | maxZoom=18',
    'base: 地理院タイル 淡色地図 | '
    'https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png | '
    '出典：国土地理院 | maxZoom=18 | minZoom=2 | bbox=122,19,155,47',
    'base: 地理院タイル 全国最新写真 | '
    'https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg | '
    '出典：国土地理院 | maxZoom=18 | minZoom=2 | bbox=122,19,155,47',
    'base: OpenStreetMap | '
    'https://tile.openstreetmap.org/{z}/{x}/{y}.png | '
    '(c) OpenStreetMap contributors | maxZoom=19',
]


def _rewrite_qml_assets_live(xml, base_url, warnings=None):
    """live 配信用に .qml 内のシンボル画像参照を ``/live/file/`` URL へ書き換える。

    エクスポート経路は ``_export_qml_assets`` が画像を canvas_data/ へ
    複製して参照を書き換えるが、live 経路はファイルを生成しないため、
    実ファイルの絶対パスを ``{base}/live/file/<encoded-abs-path>`` へ
    向ける(/live/file の許可判定は server_manager._live_file_allowed)。
    変更が無ければ入力 XML をそのまま返す。
    """
    warnings = warnings if warnings is not None else []
    base = (base_url or '').rstrip('/')
    if not base:
        return xml
    try:
        from .defusedxml import ElementTree as ET
    except ImportError:
        from defusedxml import ElementTree as ET
    from . import kasugai_export as ex
    try:
        root = ET.fromstring(xml)
    except Exception:
        return xml
    try:
        from qgis.core import QgsProject
        qml_dir = QgsProject.instance().absolutePath() or ''
    except Exception:  # nosec B110  # 設計上の許容
        qml_dir = ''
    svg_dirs = None
    changed = False
    for layer_el in root.iter('layer'):
        keys = ex._QML_ASSET_KEYS.get(
            (layer_el.get('class') or '').strip().lower())
        if not keys:
            continue
        for el, attr in ex._qml_asset_props(layer_el, keys):
            raw = (el.get(attr) or '').strip()
            if not raw or ex._REMOTE_ASSET_RE.match(raw):
                continue
            if svg_dirs is None:
                svg_dirs = ex._qgis_svg_search_paths()
            src = ex._resolve_asset_file(raw, qml_dir, svg_dirs)
            if not src:
                warnings.append(
                    'live/style: シンボル画像が見つかりません: {0}'.format(raw))
                continue
            enc = urllib.parse.quote(src.replace('\\', '/'), safe='')
            el.set(attr, '{0}/live/file/{1}'.format(base, enc))
            changed = True
    if not changed:
        return xml
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + \
        ET.tostring(root, encoding='unicode')


def layer_qml_xml(layer, style_name=None, warnings=None, base_url=None):
    """レイヤのスタイルを .qml XML 文字列で返す。

    style_name 指定時は styleManager の名前付きスタイル
    (xmlData() は .qml 同等の <qgis> 文書。theme 記録のスタイル用)。
    省略時は現在スタイルを exportNamedStyle で書き出す。
    base_url 指定時はシンボル画像参照を ``{base}/live/file/`` へ書き換える。
    失敗時は None。
    """
    warnings = warnings if warnings is not None else []
    try:
        if style_name:
            mgr = layer.styleManager()
            st = mgr.style(style_name) if mgr is not None else None
            if st is None or not st.isValid():
                return None
            xml = st.xmlData()
        else:
            from qgis.PyQt.QtXml import QDomDocument
            doc = QDomDocument()
            layer.exportNamedStyle(doc)
            xml = doc.toString()
    except Exception as e:
        warnings.append('{0}: qml export failed: {1}'.format(
            layer.name(), e))
        return None
    if not xml:
        return None
    # geo_userfunc の展開宣言済みユーザー関数を組込み式へ置き換える
    # (既存処理はファイル前提のため一時ファイル経由で再利用する)
    try:
        from . import kasugai_export
        if kasugai_export._user_func_expansions():
            fd, tmp = tempfile.mkstemp(suffix='.qml')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(xml)
                kasugai_export._expand_user_funcs_in_qml(tmp, warnings)
                with open(tmp, 'r', encoding='utf-8') as f:
                    xml = f.read()
            finally:
                try:
                    os.remove(tmp)
                except OSError:  # nosec B110  # 設計上の許容
                    pass
    except Exception:  # nosec B110  # 設計上の許容
        pass
    if base_url:
        try:
            xml = _rewrite_qml_assets_live(xml, base_url, warnings)
        except Exception as e:  # nosec B110  # 失敗しても生 QML は返す
            warnings.append('{0}: live asset rewrite failed: {1}'.format(
                layer.name(), e))
    return xml


def build_live_kasc(iface, base_url, warnings=None):
    """現在のプロジェクトから .kasc テキストを生成して返す(GUIスレッド)。

    ベクターは ``geojson:`` 行の URL を ``/live/features``、
    ``style=`` を ``/live/style`` へ向ける。非表示レイヤも ``| off``
    で出力し(Canvas 側で表示切替・テーマ適用ができる)、
    描画順はエクスポートと同じレイヤツリー順に従う。
    """
    from qgis.core import (QgsProject, QgsVectorLayer, QgsRasterLayer,
                           QgsWkbTypes)
    from . import kasugai_export as ex
    warnings = warnings if warnings is not None else []
    base = str(base_url or '').rstrip('/')
    project = QgsProject.instance()

    def enc(s):
        return urllib.parse.quote(str(s), safe='')

    def feat_url(title):
        # limit 未指定だとサーバ既定 2000 で静かに切り詰められるため
        # サーバ上限(20000)を明示する。超過分は応答の truncated で判別
        return '{0}/live/features?layer={1}&limit=20000'.format(
            base, enc(title))

    def live_file_ref(path):
        # 原本ファイルを /live/file/<encoded-abs-path> で配信する参照。
        # shpjs 等が URL 文字列末尾の拡張子置換で sidecar(.dbf 等)を
        # 派生するため、パス全体を1セグメントへエンコードする。
        # http(s) ソースや file:// 形式(delimitedtext)はそのまま/
        # 実パスへ正規化して返す
        p = urllib.parse.unquote(str(path or '')).split('?')[0]
        if re.match(r'https?://', p):
            return p
        if p.startswith('file://'):
            p = p[7:]
        if re.match(r'^/[A-Za-z]:/', p):
            p = p[1:]
        return '{0}/live/file/{1}'.format(base, enc(p))

    def style_url(title, name=None):
        u = '{0}/live/style?layer={1}'.format(base, enc(title))
        if name:
            u += '&name={0}'.format(enc(name))
        return u

    group_states = {}
    exclusive_groups = set()
    skipped = []
    tree = ex._tree_layers(skipped, warnings, group_states,
                           exclusive_groups)
    # カスタムレイヤ順(描画順オーバーライド)が有効ならその順へ並べ替える
    try:
        root = project.layerTreeRoot()
        if root.hasCustomLayerOrder():
            order_map = {id(lyr): i
                         for i, lyr in enumerate(
                             root.customLayerOrder() or [])}
            tree = sorted(
                tree,
                key=lambda t: order_map.get(id(t[0]), len(order_map)))
    except Exception:  # nosec B110  # 設計上の許容
        pass
    basemap_names = ex._basemap_group_names()

    # 表示中の最下段 XYZ → base: 行(エクスポートと同じ規則)
    last_xyz_id = None
    for layer, _g, vis, _tn in tree:
        if vis and ex._xyz_layer_info(layer):
            last_xyz_id = id(layer)

    kasc_lines = []
    detected_base = None
    group_bases = []
    emitted_ids = set()
    title_by_id = {}

    def _attr_opt(lyr):
        attr = ex._attribution(lyr)
        return ' | attr={0}'.format(ex._kasc_escape(attr)) if attr else ''

    for layer, groups, visible, _tn in tree:
        try:
            if str(layer.customProperty('kasugai_export', '')
                   or '').strip() == 'off':
                skipped.append(
                    '{0} (Canvasへ引き継がない設定)'.format(layer.name()))
                continue
            bm_idx = ex._basemap_group_index(groups, basemap_names)
            title = ex._kasc_layer_title(
                groups, layer.name(), exclusive_groups)
            site_opt = ex._canvas_layer_opts_suffix(
                layer, groups, bm_idx, None)
            vis_off_opt = str(layer.customProperty('kasugai_vis', '')
                              or '').strip() == 'off'
            vis_flag = 'off' if (vis_off_opt or not visible) else 'on'
            title_by_id[layer.id()] = title

            if isinstance(layer, QgsVectorLayer):
                try:
                    if layer.wkbType() == QgsWkbTypes.NoGeometry:
                        skipped.append(
                            '{0} (属性テーブル)'.format(layer.name()))
                        continue
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                # 編集中レイヤはライブ表示から除外(原本ファイルには
                # 未保存の編集が反映されず、GeoJSON 経路は大レイヤで
                # 重いため運用上除く。編集終了で復帰する)
                try:
                    if layer.isEditable():
                        skipped.append(
                            '{0} (編集中のためライブ表示を除外)'.format(
                                layer.name()))
                        continue
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                # ファイル/URL ソースはネイティブ形式のまま原本を配信
                # (WebGIS としての形式別性能をそのまま測れるようにする。
                # _native_ref のローカルファイル複製を /live/file 参照に
                # 置き換える file_ref 経路)
                native = None
                try:
                    native = ex._native_ref(
                        layer, '', '', {}, warnings,
                        write=False, file_ref=live_file_ref)
                except Exception as e:
                    warnings.append(
                        '{0}: native ref failed: {1}'.format(
                            layer.name(), e))
                if isinstance(native, dict) and native.get('type') \
                        and native.get('ref'):
                    opts = dict(native.get('opts') or {})
                    # where= は行の最終オプション(値は行末まで)
                    where_val = opts.pop('where', None)
                    line = '{0}: {1} | {2} | {3}'.format(
                        native['type'], title,
                        ex._kasc_escape(native['ref']), vis_flag)
                    for key, val in opts.items():
                        line += ' | {0}={1}'.format(
                            key, ex._kasc_escape(val))
                    line += ' | style={0}'.format(style_url(title))
                    line += ex._vector_opts_suffix(layer, warnings)
                    line += ex._scale_vis_opt(layer)
                    line += _attr_opt(layer)
                    line += site_opt
                    if where_val:
                        line += ' | where={0}'.format(where_val)
                    kasc_lines.append(line)
                    emitted_ids.add(id(layer))
                    ln_meta = ex._legend_node_line(_tn, title)
                    if ln_meta:
                        kasc_lines.append(ln_meta)
                    continue
                # ネイティブ参照できないソース(メモリ/PostGIS/CSV列推定
                # 失敗・再投影必要等)は /live/features の GeoJSON
                # オンデマンド配信へフォールバック
                line = 'geojson: {0} | {1} | {2}'.format(
                    title, feat_url(title), vis_flag)
                line += ' | style={0}'.format(style_url(title))
                line += ex._vector_opts_suffix(layer, warnings)
                line += ex._scale_vis_opt(layer)
                line += _attr_opt(layer)
                line += site_opt
                kasc_lines.append(line)
                emitted_ids.add(id(layer))
                ln_meta = ex._legend_node_line(_tn, title)
                if ln_meta:
                    kasc_lines.append(ln_meta)
                continue

            # ベクタータイル(URL ソースのみ。ローカル .mbtiles は未対応)
            vt_src = ex._vectortile_source(layer)
            if vt_src:
                line = '{0}: {1} | {2} | {3}'.format(
                    vt_src['kind'], title,
                    ex._kasc_escape(vt_src['url']), vis_flag)
                if vt_src.get('zmin') is not None:
                    line += ' | minzoom={0}'.format(vt_src['zmin'])
                if vt_src.get('zmax') is not None:
                    line += ' | maxzoom={0}'.format(vt_src['zmax'])
                line += ex._scale_vis_opt(layer)
                line += _attr_opt(layer)
                line += site_opt
                kasc_lines.append(line)
                emitted_ids.add(id(layer))
                continue

            # 3D Tiles(http(s) URL のみ。ローカル tileset は未対応)
            if ex._is_tiled_scene(layer):
                src = layer.source() or ''
                m = re.search(r'(?:^|&)url=([^&]+)', src)
                target = (urllib.parse.unquote(m.group(1))
                          if m else src.strip())
                if target.startswith('/vsicurl/'):
                    target = target[len('/vsicurl/'):]
                if re.match(r'https?://', target) and \
                        target.split('?')[0].lower().endswith('.json'):
                    line = '3dtiles: {0} | {1} | {2}'.format(
                        title, ex._kasc_escape(target), vis_flag)
                    line += ex._scale_vis_opt(layer)
                    line += _attr_opt(layer)
                    line += site_opt
                    kasc_lines.append(line)
                    emitted_ids.add(id(layer))
                else:
                    skipped.append(
                        '{0} (3dtiles ローカル参照は未対応)'.format(
                            layer.name()))
                continue

            xyz = ex._xyz_layer_info(layer)
            if xyz:
                url, zmin, zmax = xyz
                if not re.match(r'https?://', url):
                    skipped.append(
                        '{0} (ローカルタイルテンプレートは未対応)'.format(
                            layer.name()))
                    continue
                opacity = ex._maplayer_opacity(layer)
                bbox = ex._layer_extent_bbox(layer)
                if bm_idx is not None:
                    # ベースマップグループ内の XYZ → base: 候補
                    base_title = '/'.join(
                        [ex._kasc_escape(g)
                         for g in groups[bm_idx + 1:] if g] +
                        [ex._kasc_escape(layer.name())])
                    line = 'base: {0} | {1}'.format(
                        base_title, ex._kasc_escape(url))
                    attr = ex._attribution(layer)
                    if attr:
                        line += ' | {0}'.format(ex._kasc_escape(attr))
                    if zmax is not None:
                        line += ' | maxZoom={0}'.format(zmax)
                    if zmin is not None:
                        line += ' | minZoom={0}'.format(zmin)
                    if opacity is not None:
                        line += ' | opacity={0}'.format(opacity)
                    line += ex._scale_vis_opt(layer)
                    if not visible:
                        line += ' | off'
                    group_bases.append((visible, line))
                elif visible and id(layer) == last_xyz_id:
                    line = 'base: {0} | {1}'.format(
                        title, ex._kasc_escape(url))
                    attr = ex._attribution(layer)
                    if attr:
                        line += ' | {0}'.format(ex._kasc_escape(attr))
                    if zmax is not None:
                        line += ' | maxZoom={0}'.format(zmax)
                    if zmin is not None:
                        line += ' | minZoom={0}'.format(zmin)
                    if opacity is not None:
                        line += ' | opacity={0}'.format(opacity)
                    line += ex._scale_vis_opt(layer)
                    detected_base = line
                else:
                    line = 'xyz: {0} | {1} | {2}'.format(
                        title, ex._kasc_escape(url), vis_flag)
                    if zmax is not None:
                        line += ' | maxZoom={0}'.format(zmax)
                    if zmin is not None:
                        line += ' | minZoom={0}'.format(zmin)
                    if opacity is not None:
                        line += ' | opacity={0}'.format(opacity)
                    line += ex._scale_vis_opt(layer)
                    if bbox is not None:
                        line += ' | bbox={0}'.format(bbox)
                    line += _attr_opt(layer)
                    line += site_opt
                    kasc_lines.append(line)
                    emitted_ids.add(id(layer))
                continue

            wmts = ex._wmts_layer_info(layer)
            if wmts:
                url, w_layers, w_styles, w_tms, w_fmt, w_tilesize = wmts
                line = 'wmts: {0} | {1} | {2}'.format(
                    title, ex._kasc_escape(url), vis_flag)
                if w_layers:
                    line += ' | layer={0}'.format(ex._kasc_escape(w_layers))
                if w_styles:
                    line += ' | style={0}'.format(ex._kasc_escape(w_styles))
                if w_tms:
                    line += ' | tilematrixset={0}'.format(
                        ex._kasc_escape(w_tms))
                if w_fmt:
                    line += ' | format={0}'.format(ex._kasc_escape(w_fmt))
                if w_tilesize in (256, 512):
                    line += ' | tilesize={0}'.format(w_tilesize)
                opacity = ex._maplayer_opacity(layer)
                if opacity is not None:
                    line += ' | opacity={0}'.format(opacity)
                bbox = ex._layer_extent_bbox(layer)
                if bbox is not None:
                    line += ' | bbox={0}'.format(bbox)
                line += ex._scale_vis_opt(layer)
                line += _attr_opt(layer)
                line += site_opt
                kasc_lines.append(line)
                emitted_ids.add(id(layer))
                continue

            wms = ex._wms_layer_info(layer)
            if wms:
                url, wms_layers, wms_styles, wms_fmt, wms_ver = wms
                line = 'wms: {0} | {1} | {2}'.format(
                    title, ex._kasc_escape(url), vis_flag)
                if wms_layers:
                    line += ' | layers={0}'.format(
                        ex._kasc_escape(wms_layers))
                if wms_styles:
                    line += ' | styles={0}'.format(
                        ex._kasc_escape(wms_styles))
                if wms_fmt:
                    line += ' | format={0}'.format(ex._kasc_escape(wms_fmt))
                if wms_ver:
                    line += ' | version={0}'.format(
                        ex._kasc_escape(wms_ver))
                opacity = ex._maplayer_opacity(layer)
                if opacity is not None:
                    line += ' | opacity={0}'.format(opacity)
                bbox = ex._layer_extent_bbox(layer)
                if bbox is not None:
                    line += ' | bbox={0}'.format(bbox)
                line += ex._scale_vis_opt(layer)
                line += _attr_opt(layer)
                line += site_opt
                kasc_lines.append(line)
                emitted_ids.add(id(layer))
                continue

            if isinstance(layer, QgsRasterLayer):
                # Canvas がネイティブ再現できないラスタは QGIS 描画 PNG を
                # image: 行で出す(/live/render は layers= で対象のみ描画)
                bb = ex._layer_extent_bbox(layer)
                if bb:
                    try:
                        w_, s_, e_, n_ = [float(v) for v in bb.split(',')]
                        pw = 2048
                        ph = max(1, min(4096, int(round(
                            pw * (n_ - s_) / max(e_ - w_, 1e-9)))))
                    except Exception:  # nosec B110  # 設計上の許容
                        pw, ph = 2048, 2048
                    rurl = ('{0}/live/render?layers={1}&bbox={2}'
                            '&w={3}&h={4}&bg=transparent').format(
                        base, enc(title), bb, pw, ph)
                    line = 'image: {0} | {1} | {2}'.format(
                        title, rurl, vis_flag)
                    line += ' | bbox={0}'.format(bb)
                    opacity = ex._maplayer_opacity(layer)
                    if opacity is not None:
                        line += ' | opacity={0}'.format(opacity)
                    line += ex._scale_vis_opt(layer)
                    line += _attr_opt(layer)
                    line += site_opt
                    kasc_lines.append(line)
                    emitted_ids.add(id(layer))
                else:
                    skipped.append(
                        '{0} (ラスタ: 範囲不明のため出力不可)'.format(
                            layer.name()))
                continue

            skipped.append('{0} ({1})'.format(
                layer.name(), ex._skip_reason(layer)))
        except Exception as e:
            warnings.append('{0}: {1}'.format(layer.name(), e))

    # theme: 行(マップテーマ → Canvas 可視性プリセット)。
    # テーマ記録の名前付きスタイルは ;style= で /live/style?name= を参照
    try:
        collection = project.mapThemeCollection()
        for name in sorted(collection.mapThemes() or []):
            try:
                visible_ids = set(
                    collection.mapThemeVisibleLayerIds(name))
                style_by_id = {}
                try:
                    rec = collection.mapThemeState(name)
                    for lr in rec.layerRecords():
                        lyr = lr.layer()
                        if lyr is None or not lr.usingCurrentStyle:
                            continue
                        sname = lr.currentStyle or ''
                        if sname:
                            style_by_id[lyr.id()] = sname
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                parts = []
                for layer, _g, _v, _tn in tree:
                    if layer.id() not in visible_ids \
                            or id(layer) not in emitted_ids:
                        continue
                    title = title_by_id.get(layer.id())
                    if not title:
                        continue
                    tok = title
                    sname = style_by_id.get(layer.id())
                    if sname:
                        tok = '{0};style={1}'.format(
                            tok, style_url(title, name=sname))
                    parts.append(tok)
                kasc_lines.append('theme: {0}{1}'.format(
                    ex._kasc_escape(name),
                    ''.join(' | ' + t for t in parts)))
            except Exception as e:
                warnings.append('theme {0}: {1}'.format(name, e))
    except Exception as e:
        warnings.append('theme 行出力失敗: {0}'.format(e))

    for s in skipped:
        kasc_lines.append('# skipped: {0}'.format(s))

    # ---- ヘッダ(bases → cam → live → 3Dビュー設定 → group) ----
    header = [
        '# live session generated by geo_webview /live/kasc '
        '(no export files)',
    ]
    try:
        ptitle = project.title() or os.path.splitext(
            os.path.basename(project.fileName() or ''))[0] \
            or 'QGIS live'
    except Exception:  # nosec B110  # 設計上の許容
        ptitle = 'QGIS live'
    header.append('title: {0}'.format(ex._kasc_escape(ptitle)))
    if detected_base:
        header.append(detected_base)
    ordered_group_bases = [line for vis, line in group_bases if vis] + \
        [line for vis, line in group_bases if not vis]
    header.extend(ordered_group_bases)
    if not detected_base and not any(v for v, _l in group_bases):
        # QGIS で表示中のベースマップが無い → Canvas 側に「ベースマップ
        # なし」を初期選択させるモード行(全エンジン対応済み)。
        # 出さないと後続の既定候補行が勝手に選択されてしまう
        header.append('base: ベースマップなし | none')
    header.extend(_DEFAULT_BASE_LINES)
    try:
        cam = ex._camera_line(iface)
        if cam:
            header.append(cam)
    except Exception:  # nosec B110  # 設計上の許容
        pass
    # live: 行 — shared/live.js がこれを検出して双方向連携を開始する。
    # | follow で QGIS 2D キャンバスへ Canvas カメラを追従させる
    # (QGIS 3Dビューの「2Dキャンバスに追従」と同じ既定動作)
    header.append('live: {0} | follow'.format(ex._kasc_escape(base)))
    try:
        header.extend(ex._threed_lines(project, warnings))
    except Exception as e:
        warnings.append('3Dビュー設定の出力に失敗: {0}'.format(e))
    for gname, gstate in group_states.items():
        _exp = gstate[0] if isinstance(gstate, tuple) else gstate
        header.append('group: {0} | {1}'.format(
            ex._kasc_escape(gname),
            'expanded' if _exp else 'collapsed'))
    return '\n'.join(header + kasc_lines) + '\n'
