# -*- coding: utf-8 -*-
"""QGIS → KASUGAI Canvas ライブ双方向連携の監視コントローラ。

QSettings ``kasugai_live_sync`` が有効なとき、レイヤ編集(地物追加/
削除・ジオメトリ/属性変更)・スタイル変更・レイヤ追加/削除・
ツリー可視性変更をデバウンスして検出し、最後のエクスポート先へ
**差分エクスポート**(``export_kasugai_project(changed=…)`` で
未変更レイヤのデータ/スタイル書き出しを省略)して
``.kasc+DATA/+live.json`` を更新する。

通知は2系統:
- Canvas アプリ(:8510)稼働時 → ``/api/command`` の ``liveSync``
  ツールをプッシュ(即時反映)
- それ以外(qgis-http/hosted/?kasc= 経路) → Canvas 側が
  プロジェクト内 ``live.json`` をポーリングして検出

逆方向(Canvas → QGIS)は geo_webview 内蔵HTTPサーバの
``POST /live/camera``・``POST /live/selection``・
``POST /live/writeback``(表示/フィルタ/テーマ書き戻し)・
``POST /live/features``(GeoJSON→スクラッチレイヤ投入)が担う。
``suppress()`` は書き戻し適用中の往復出力を抑止するために使う。
"""

import os
import time
from contextlib import contextmanager

from qgis.PyQt.QtCore import QObject, QTimer, QSettings
from qgis.core import QgsProject, QgsMessageLog, Qgis

DEBOUNCE_MS = 1200
SEL_DEBOUNCE_MS = 400
SETTINGS_KEY = 'kasugai_live_sync'


def live_enabled():
    """ライブ双方向連携が有効か(QSettings)。"""
    try:
        on = QSettings('GeoWebView', 'geo_webview').value(
            SETTINGS_KEY, False)
        return str(on).lower() in ('true', '1', 'yes')
    except Exception:  # nosec B110  # 設計上の許容
        return False


# レイヤシグナル名 → 変更種別。
# 'data'=地物/フィルタ変更(GeoJSON等の再出力が必要)
# 'style'=スタイル変更(.qml のみ再出力)
# 'struct'=構成変更(.kasc 構造が変わるため全再出力へ切替)
_LAYER_SIGNALS = (
    ('styleChanged', 'style'),
    ('dataChanged', 'data'),
    ('subsetStringChanged', 'data'),
    ('editCommandEnded', 'data'),
    ('featureAdded', 'data'),
    ('featureDeleted', 'data'),
    ('geometryChanged', 'data'),
    ('attributeValueChanged', 'data'),
    ('layerModified', 'data'),
    # 通常編集の確定(commitChanges)は committed* 系が確実に出る
    # (attributeValueChanged 等はバッファ経路で出ない版がある)
    ('editingStopped', 'data'),
    ('committedAttributeValuesChanges', 'data'),
    ('committedFeaturesAdded', 'data'),
    ('committedFeaturesRemoved', 'data'),
    ('committedGeometriesChanges', 'data'),
    ('nameChanged', 'struct'),
    ('rendererChanged', 'style'),
)


class LiveSyncController(QObject):
    """プロジェクト変更シグナルを監視し差分エクスポート+通知を行う。

    全シグナルは GUI スレッドで発火する。エクスポートは既存の
    kasugaiExport と同じく GUI スレッドで行い、_kasugai_lock で
    /kasugai・bridge 経由の同時実行と直列化する。
    """

    def __init__(self, plugin):
        super().__init__()
        self._plugin = plugin  # geo_webview plugin instance
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)
        self._sel_timer = QTimer(self)
        self._sel_timer.setSingleShot(True)
        self._sel_timer.timeout.connect(self._flush_selection)
        self._pending = {}        # layer.id() -> {'data':bool,'style':bool}
        self._structural = False  # add/remove/reorder/可視性/名称変更
        self._attached_layers = set()  # python id(layer)
        self._connected = False
        self._running = False
        self._suppress = 0  # /live/writeback 適用中の変更検出抑止

    @contextmanager
    def suppress(self):
        """逆書き戻し(Canvas → QGIS)適用中は変更検出を抑止する。

        /live/writeback で可視性・フィルタを反映すると通常のレイヤ
        シグナルが発火するが、これは Canvas 由来の状態なので再出力
        (QGIS → Canvas への往復)は不要。抑止中に発火した変更は
        マークしない(レイヤシグナル接続自体は維持する)。
        """
        self._suppress += 1
        try:
            yield
        finally:
            self._suppress = max(0, self._suppress - 1)

    # ---- 接続管理 ----
    def attach(self):
        """監視を開始する(live_enabled のとき呼ばれる)。"""
        if self._connected:
            return
        self._connected = True
        project = QgsProject.instance()
        for sig_name, slot in (
                ('layersAdded', self._on_layers_added),
                ('layersRemoved', self._on_structure),
                ('readProject', self._on_project_read),
                ('cleared', self._on_project_read)):
            try:
                getattr(project, sig_name).connect(slot)
            except Exception:  # nosec B110  # 設計上の許容
                pass
        try:
            # レイヤツリー可視性・描画順の変更(layersChanged)を拾う
            self._plugin.iface.mapCanvas().layersChanged.connect(
                self._on_structure)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        try:
            # ツリーの可視性トグルは layersChanged が出ない環境があるため
            # ルートノードの visibilityChanged でも拾う
            project.layerTreeRoot().visibilityChanged.connect(
                self._on_structure)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        self._attach_all_layers()

    def detach(self):
        """監視を停止する。pending は破棄。"""
        self._connected = False
        self._pending.clear()
        self._structural = False
        self._timer.stop()
        self._sel_timer.stop()
        project = QgsProject.instance()
        for sig_name, slot in (
                ('layersAdded', self._on_layers_added),
                ('layersRemoved', self._on_structure),
                ('readProject', self._on_project_read),
                ('cleared', self._on_project_read)):
            try:
                getattr(project, sig_name).disconnect(slot)
            except Exception:  # nosec B110  # 設計上の許容
                pass
        try:
            self._plugin.iface.mapCanvas().layersChanged.disconnect(
                self._on_structure)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        try:
            project.layerTreeRoot().visibilityChanged.disconnect(
                self._on_structure)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        self._detach_all_layers()

    def _attach_all_layers(self):
        for layer in QgsProject.instance().mapLayers().values():
            self._attach_layer(layer)

    def _detach_all_layers(self):
        for layer in QgsProject.instance().mapLayers().values():
            if id(layer) in self._attached_layers:
                self._detach_layer(layer)
        self._attached_layers.clear()

    def _attach_layer(self, layer):
        key = id(layer)
        if key in self._attached_layers:
            return
        connected = False
        for sig_name, kind in _LAYER_SIGNALS:
            sig = getattr(layer, sig_name, None)
            if sig is None:
                continue
            try:
                sig.connect(
                    lambda *a, lyr=layer, k=kind: self._mark(lyr, k))
                connected = True
            except Exception:  # nosec B110  # 設計上の許容
                pass
        # QGIS → Canvas 選択同期: ベクターレイヤの選択変更を監視する
        # (差分エクスポートは不要なため _LAYER_SIGNALS とは別系統)
        sig = getattr(layer, 'selectionChanged', None)
        if sig is not None:
            try:
                sig.connect(self._on_selection_changed)
                connected = True
            except Exception:  # nosec B110  # 設計上の許容
                pass
        if connected:
            self._attached_layers.add(key)

    def _detach_layer(self, layer):
        for sig_name, _kind in _LAYER_SIGNALS:
            sig = getattr(layer, sig_name, None)
            if sig is None:
                continue
            try:
                sig.disconnect()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        sig = getattr(layer, 'selectionChanged', None)
        if sig is not None:
            try:
                sig.disconnect(self._on_selection_changed)
            except Exception:  # nosec B110  # 設計上の許容
                pass
        self._attached_layers.discard(id(layer))

    # ---- シグナルハンドラ ----
    def _mark(self, layer, kind):
        if (not self._connected or not live_enabled()
                or self._suppress):
            return
        if kind == 'struct':
            self._structural = True
        else:
            lid = layer.id() if layer is not None else ''
            if lid:
                ent = self._pending.setdefault(
                    lid, {'data': False, 'style': False})
                ent[kind] = True
            else:
                self._structural = True
        self._timer.start(DEBOUNCE_MS)

    def _on_structure(self, *args):
        if (not self._connected or not live_enabled()
                or self._suppress):
            return
        self._structural = True
        # 追加/削除の直後はレイヤシグナル構成も追従する
        self._attach_all_layers()
        self._timer.start(DEBOUNCE_MS)

    def _on_layers_added(self, layers):
        for layer in layers or []:
            self._attach_layer(layer)
        self._on_structure()

    def _on_project_read(self, *args):
        # プロジェクト切替: 積み残しを捨てて接続を張り直す
        self._pending.clear()
        self._structural = False
        self._attached_layers.clear()
        self._attach_all_layers()

    # ---- 差分エクスポート + 通知 ----
    def _flush(self):
        if self._running or not self._connected or not live_enabled():
            return
        if not self._pending and not self._structural:
            return
        from . import kasugai_export
        out_dir = kasugai_export.last_export_dir()
        kasc = os.path.join(out_dir or '', 'kasugai_canvas.kasc')
        if not out_dir or not os.path.isfile(kasc):
            # ライブ対象となる既存エクスポートが無い(最初の
            # kasugaiExport で確立される)ため何もしない
            self._pending.clear()
            self._structural = False
            return
        pending = self._pending
        self._pending = {}
        structural = self._structural
        self._structural = False
        self._running = True
        try:
            srv = getattr(self._plugin, 'server_manager', None)
            port = (srv.get_server_port()
                    if srv and srv.is_server_running() else None)
            live_url = ('http://127.0.0.1:{0}'.format(port)
                        if port else None)
            # 構造変更は全再出力(added/removed の slug ずれ回避)、
            # レイヤ単位変更は差分(未変更レイヤの書き出しを省略)
            changed = None if structural else dict(pending)
            if not structural and not changed:
                return
            if srv is not None:
                with srv._kasugai_lock:
                    kasugai_export.export_kasugai_project(
                        self._plugin.iface, out_dir=out_dir,
                        changed=changed, live_url=live_url)
            else:
                kasugai_export.export_kasugai_project(
                    self._plugin.iface, out_dir=out_dir,
                    changed=changed, live_url=live_url)
            rev = int(time.time() * 1000)
            changed_titles = []
            for lid, kinds in pending.items():
                lyr = QgsProject.instance().mapLayer(lid)
                changed_titles.append({
                    'title': lyr.name() if lyr is not None else str(lid),
                    'data': bool(kinds.get('data')),
                    'style': bool(kinds.get('style')),
                })
            if srv is not None:
                try:
                    srv.live_update(changed_titles, enabled=True)
                except Exception:  # nosec B110  # 設計上の許容
                    pass
            # 稼働中の Canvas アプリへ liveSync をプッシュ(即時反映)。
            # 未稼働でも live.json ポーリングで追従するため失敗は無視
            try:
                if live_url and kasugai_export.detect_kasugai():
                    kasugai_export.kasugai_command('liveSync', {
                        'rev': rev,
                        'full': bool(structural),
                        'changed': [c['title'] for c in changed_titles],
                        'src': live_url,
                    })
            except Exception:  # nosec B110  # 通知失敗は次回更新で追従
                pass
            QgsMessageLog.logMessage(
                'live sync exported: {0} ({1})'.format(
                    'full' if structural else
                    ', '.join(c['title'] for c in changed_titles) or 'none',
                    out_dir),
                'geo_webview', Qgis.MessageLevel.Info)
        except Exception as e:
            QgsMessageLog.logMessage(
                'live sync export failed: {0}'.format(e),
                'geo_webview', Qgis.MessageLevel.Warning)
        finally:
            self._running = False

    # ---- QGIS → Canvas 選択同期 ----
    def _on_selection_changed(self, *args):
        """ベクターレイヤの selectionChanged(GUIスレッド)。デバウンスして送信。"""
        if not self._connected or not live_enabled():
            return
        self._sel_timer.start(SEL_DEBOUNCE_MS)

    def _flush_selection(self):
        """選択状態を収集し /live/state 登録 + Canvas プッシュする。"""
        if not self._connected or not live_enabled():
            return
        layers_out = []
        try:
            from qgis.core import QgsVectorLayer
            from . import kasugai_export
            title_of = {}
            for lyr, groups, _v, _tn in kasugai_export._tree_layers():
                title_of[lyr.id()] = kasugai_export._kasc_layer_title(
                    groups, lyr.name())
            for lyr in QgsProject.instance().mapLayers().values():
                if not isinstance(lyr, QgsVectorLayer):
                    continue
                ids = list(lyr.selectedFeatureIds())
                if not ids:
                    continue
                layers_out.append({
                    'layer': title_of.get(lyr.id()) or lyr.name(),
                    'ids': ids[:500],
                    'count': len(ids),
                })
        except Exception as e:
            QgsMessageLog.logMessage(
                'live selection collect failed: {0}'.format(e),
                'geo_webview', Qgis.MessageLevel.Warning)
            return
        payload = {'layers': layers_out, 'rev': int(time.time() * 1000)}
        srv = getattr(self._plugin, 'server_manager', None)
        if srv is not None:
            try:
                srv.live_notify_qgis_selection(payload)
            except Exception:  # nosec B110  # 設計上の許容
                pass
        # 稼働中の Canvas アプリへ即時プッシュ(未稼働は /live/state で追従)
        try:
            from . import kasugai_export
            if kasugai_export.detect_kasugai():
                kasugai_export.kasugai_command(
                    'liveSync', {'selection': payload})
        except Exception:  # nosec B110  # 通知失敗は次回更新で追従
            pass

    def flush(self):
        """即時同期を要求する(bridge の手動 flush 用)。"""
        if not self._connected:
            return {'ok': False, 'error': 'live sync not attached'}
        self._flush()
        return {'ok': True}

    def status(self):
        return {
            'enabled': live_enabled(),
            'attached': self._connected,
            'running': self._running,
            'pending': len(self._pending),
            'structural': self._structural,
            'watched_layers': len(self._attached_layers),
        }
