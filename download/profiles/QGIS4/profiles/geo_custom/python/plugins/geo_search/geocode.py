# -*- coding: utf-8 -*-
"""住所検索(ジオコーディング)プロバイダ。

KASUGAI Canvas (kasugai_canvas/web) の searchProviders / parseCoordinateQuery
と同じ仕様を QGIS 側へ移植したもの。各プロバイダは
``{title, address, latitude, longitude}`` の dict リストを返す。

- gsi    : 国土地理院 AddressSearch(キー不要・既定)
- osm    : OSM Nominatim(キー不要)
- google : Google Geocoding + Places(テキスト検索)ハイブリッド(要APIキー)
- yahoo  : Yahoo!ジオコーダ(要アプリケーションID)

HTTP 通信は QgsBlockingNetworkRequest を使い、QGIS のプロキシ/認証設定を継承する。
同期呼び出しのため GUI スレッドでは応答待ちの間ブロックする
(CANVAS 側と同じく 15 秒の転送タイムアウトを設定)。
"""

import json
import os
import re
from urllib.parse import quote

from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsBlockingNetworkRequest

from .log import log_message

_TAG = "GEO-search-plugin"

DEFAULT_PROVIDER = "gsi"
PROVIDERS = ("gsi", "google", "yahoo", "osm")
RESULT_LIMIT = 20
TIMEOUT_MS = 15000

# Nominatim は識別可能な User-Agent を要求するため全リクエストに付与する
USER_AGENT = ("geo_search QGIS plugin "
              "(https://github.com/yamamoto-ryuzo/qgis_live_harness)")

# メモリレイヤのフィールド順(結果テーブルの列にもなる)
MEMORY_FIELDS = ("title", "address", "provider", "lon", "lat")
ADDRESS_LAYER_NAME = "geo_search 住所検索"


class GeocodeError(Exception):
    """プロバイダのネットワーク/キー未設定エラー。"""


def _tr(message):
    try:
        from qgis.PyQt.QtCore import QCoreApplication
        return QCoreApplication.translate("SearchWidget", message)
    except Exception:  # nosec B110  # 設計上の許容
        return message


def _http_get(url, headers=None):
    """同期GET。レスポンス文字列を返し、失敗時は GeocodeError。"""
    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(b"User-Agent", USER_AGENT.encode("utf-8"))
    try:
        req.setTransferTimeout(TIMEOUT_MS)
    except Exception:  # nosec B110  # 旧Qt向けフォールバック
        pass
    for k, v in (headers or {}).items():
        req.setRawHeader(str(k).encode("utf-8"), str(v).encode("utf-8"))
    blocking = QgsBlockingNetworkRequest()
    err = blocking.get(req, True)
    if _no_error() != err:
        raise GeocodeError(blocking.errorMessage() or _tr("Search failed"))
    reply = blocking.reply()
    if reply.error() != _no_reply_error():
        raise GeocodeError(reply.errorString() or _tr("Search failed"))
    return bytes(reply.content()).decode("utf-8", "replace")


def _http_post_json(url, payload, headers=None):
    """同期POST(JSON)。レスポンス文字列を返し、失敗時は GeocodeError。"""
    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(b"User-Agent", USER_AGENT.encode("utf-8"))
    req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                  "application/json")
    try:
        req.setTransferTimeout(TIMEOUT_MS)
    except Exception:  # nosec B110  # 旧Qt向けフォールバック
        pass
    for k, v in (headers or {}).items():
        req.setRawHeader(str(k).encode("utf-8"), str(v).encode("utf-8"))
    blocking = QgsBlockingNetworkRequest()
    err = blocking.post(req, QByteArray(json.dumps(payload).encode("utf-8")), True)
    if _no_error() != err:
        raise GeocodeError(blocking.errorMessage() or _tr("Search failed"))
    reply = blocking.reply()
    if reply.error() != _no_reply_error():
        raise GeocodeError(reply.errorString() or _tr("Search failed"))
    return bytes(reply.content()).decode("utf-8", "replace")


def _no_error():
    try:
        return QgsBlockingNetworkRequest.ErrorCode.NoError
    except AttributeError:
        return QgsBlockingNetworkRequest.NoError


def _no_reply_error():
    from qgis.PyQt.QtNetwork import QNetworkReply
    try:
        return QNetworkReply.NetworkError.NoError
    except AttributeError:
        return QNetworkReply.NoError


def _lang():
    """QGIS UI言語コード(google/nominatim の言語パラメータ用)。"""
    try:
        from .i18n_json import lang_code
        return lang_code() or "en"
    except Exception:  # nosec B110  # 設計上の許容
        return "en"


def _item(title, address, lat, lon):
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return {"title": str(title or ""), "address": str(address or ""),
            "latitude": lat_f, "longitude": lon_f}


# ---------------------------------------------------------------------------
# プロバイダ実装(CANVAS web/cesium/app.js の searchProviders に対応)
# ---------------------------------------------------------------------------

_GSI_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="

# 行政区画名の接尾辞(これで終わる入力は補完リクエスト不要とみなす)
_ADMIN_SUFFIXES = "都道府県市区町村郡"


def _gsi_fetch(query):
    """GSI AddressSearch を1回呼び出し、アイテムリストを返す。"""
    data = json.loads(_http_get(_GSI_URL + quote(query)) or "[]")
    out = []
    for item in (data if isinstance(data, list) else []):
        props = item.get("properties") or {}
        coords = (item.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        it = _item(props.get("title") or props.get("name")
                   or props.get("Name") or "",
                   props.get("address") or props.get("Address")
                   or props.get("title") or "",
                   coords[1], coords[0])
        if it:
            out.append(it)
    return out


def _rank_results(items, query):
    """関連度順に安定ソート: 完全一致 > 前方一致 > 部分一致 > その他。
    同一グループ内はタイトルが短いもの(=代表地名に近い)を優先する。
    GSI API の生順はデータセット順であり関連度ではないため必須の後処理。"""
    q = str(query or "")

    def key(pair):
        idx, it = pair
        t = str(it.get("title") or "")
        if q and t == q:
            group = 0
        elif q and t.startswith(q):
            group = 1
        elif q and q in t:
            group = 2
        else:
            group = 3
        return (group, len(t), idx)

    return [it for _, it in sorted(enumerate(items), key=key)]


def _search_gsi(query):
    q = str(query or "").strip()
    items = _gsi_fetch(q)
    # 「東京」「札幌」のような行政区画接尾辞を持たない短い入力は、
    # API が「末尾要素の部分一致候補」(〜町東 等)を先頭に大量に返し
    # 「東京都」「札幌市」のような行政区画本体が埋もれてしまう。
    # "<q>都" の補完リクエストを1本投げると行政区画レベルの候補が
    # 絞られて返るため(札幌都→北海道札幌市、秋葉原都→東京都台東区秋葉原)、
    # クエリを含む候補だけを拾って先頭へマージする。
    if (2 <= len(q) <= 10 and q[-1] not in _ADMIN_SUFFIXES
            and not re.search(r"[0-9０-９]", q)):
        try:
            extra = [it for it in _gsi_fetch(q + "都")
                     if q in str(it.get("title") or "")]
        except GeocodeError:
            extra = []
        if extra:
            seen = {(it["title"], it["latitude"], it["longitude"])
                    for it in items}
            items = [it for it in extra
                     if (it["title"], it["latitude"], it["longitude"])
                     not in seen] + items
    return _rank_results(items, q)


def _search_osm(query):
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=20"
           "&accept-language={}&q={}".format(_lang(), quote(query)))
    data = json.loads(_http_get(url) or "[]")
    out = []
    for r in (data if isinstance(data, list) else []):
        display = str(r.get("display_name") or "")
        it = _item(display.split(",")[0], display,
                   r.get("lat"), r.get("lon"))
        if it:
            out.append(it)
    return out


def _google_geocode(query, key):
    url = ("https://maps.googleapis.com/maps/api/geocode/json?address={}"
           "&key={}&language={}".format(quote(query), quote(key), _lang()))
    data = json.loads(_http_get(url) or "{}")
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise GeocodeError(data.get("error_message") or status
                           or _tr("Search failed"))
    out = []
    for item in data.get("results") or []:
        loc = ((item.get("geometry") or {}).get("location")) or {}
        it = _item(item.get("formatted_address") or "",
                   item.get("formatted_address") or "",
                   loc.get("lat"), loc.get("lng"))
        if it:
            out.append(it)
    return out


def _google_places(query, key):
    text = _http_post_json(
        "https://places.googleapis.com/v1/places:searchText",
        {"textQuery": str(query or ""), "languageCode": _lang(),
         "pageSize": 20},
        {"X-Goog-Api-Key": key,
         "X-Goog-FieldMask":
         "places.displayName,places.formattedAddress,places.location"})
    data = json.loads(text or "{}")
    out = []
    for place in data.get("places") or []:
        loc = place.get("location") or {}
        it = _item((place.get("displayName") or {}).get("text") or "",
                   place.get("formattedAddress") or "",
                   loc.get("latitude"), loc.get("longitude"))
        if it:
            out.append(it)
    return out


def _search_google(query, key):
    """Geocoding(住所向け)+Places(施設向け)を呼んでマージする。

    CANVAS と同じく片方が失敗しても他方の結果を返し、同一地点
    (座標を約11m単位に丸めたもの)の重複は Geocoding 側を優先して除く。
    """
    if not key:
        raise GeocodeError(_tr("Google Maps API key is not set"))
    geocode_items, places_items = [], []
    geocode_err = places_err = None
    try:
        geocode_items = _google_geocode(query, key)
    except Exception as e:
        geocode_err = e
    try:
        places_items = _google_places(query, key)
    except Exception as e:
        places_err = e
    items = geocode_items + places_items
    if not items:
        raise geocode_err or places_err or GeocodeError(
            _tr("Search failed"))
    seen = set()
    out = []
    for it in items:
        k = (round(it["latitude"] * 1e4), round(it["longitude"] * 1e4))
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def _search_yahoo(query, app_id):
    if not app_id:
        raise GeocodeError(_tr("Yahoo app id is not set"))
    url = ("https://map.yahooapis.jp/geocode/V1/geoCoder?appid={}"
           "&query={}&output=json".format(quote(app_id), quote(query)))
    data = json.loads(_http_get(url) or "{}")
    out = []
    for feature in data.get("Feature") or []:
        coords = str((feature.get("Geometry") or {})
                     .get("Coordinates") or "").split(",")
        if len(coords) < 2:
            continue
        it = _item(feature.get("Name") or (feature.get("Property") or {})
                   .get("Address") or "",
                   (feature.get("Property") or {}).get("Address")
                   or feature.get("Name") or "",
                   coords[1], coords[0])
        if it:
            out.append(it)
    return out


# ---------------------------------------------------------------------------
# APIキー解決(タブ設定 dict → 環境変数の順)
# ---------------------------------------------------------------------------

def resolve_api_key(setting=None):
    """Google Maps APIキー。設定値 "ApiKey" > 環境変数 GOOGLE_MAPS_API_KEY。"""
    if isinstance(setting, dict):
        key = setting.get("ApiKey")
        if key:
            return str(key)
    return os.environ.get("GOOGLE_MAPS_API_KEY") or ""


def resolve_yahoo_app_id(setting=None):
    """Yahoo アプリケーションID。設定値 "YahooAppId" > 環境変数 YAHOO_APPID。"""
    if isinstance(setting, dict):
        app_id = setting.get("YahooAppId")
        if app_id:
            return str(app_id)
    return os.environ.get("YAHOO_APPID") or ""


def search(query, provider=None, setting=None, limit=RESULT_LIMIT):
    """ジオコーディングを実行し {title,address,latitude,longitude} を返す。

    provider 省略時は設定の "Provider"、それも無ければ gsi。
    座標と解釈できる入力は呼び出し側で parse_coordinate_query 済みとし、
    ここではプロバイダへ委譲するだけに留める。
    limit=None の場合はプロバイダ応答の全件を返す(呼び出し側で
    ページング等により遅延消費する用途)。既定は RESULT_LIMIT 件。
    """
    q = str(query or "").strip()
    if not q:
        return []
    prov = (provider or (setting or {}).get("Provider")
            or DEFAULT_PROVIDER).lower()
    if prov == "nominatim":
        prov = "osm"
    log_message("address search: provider={} query={}".format(prov, q), _TAG, 0)
    if prov == "osm":
        items = _search_osm(q)
    elif prov == "google":
        items = _search_google(q, resolve_api_key(setting))
    elif prov == "yahoo":
        items = _search_yahoo(q, resolve_yahoo_app_id(setting))
    else:
        prov = "gsi"
        items = _search_gsi(q)
    for it in items:
        it["provider"] = prov
    if limit is None:
        return items
    return items[:max(0, int(limit))]


# ---------------------------------------------------------------------------
# 座標直入力パーサ(CANVAS web/shared/coords-format.js の移植)
# "35.6,139.7" / "139.7,35.6" / "N35°36'50\" E139°43'0\"" /
# "35度36分 139度43分" 等を {latitude,longitude} に正規化する
# ---------------------------------------------------------------------------

# CANVAS側は分記号 ' の後に秒数が必須で "35度36分" は非座標扱いになるが、
# こちらは ' のみ(秒なし)も分の終端として許容する拡張仕様
_COORD_COMPONENT = re.compile(
    r"^([NSEW])?\s*([+-]?\d+(?:\.\d+)?)"
    r"(?:\s*°\s*(\d+(?:\.\d+)?))?"
    r"(?:\s*'\s*(\d+(?:\.\d+)?)?)?"
    r"(?:\s*\")?\s*([NSEW])?$",
    re.IGNORECASE)


def _coord_component(text):
    m = _COORD_COMPONENT.match(str(text).strip())
    if not m:
        return None
    try:
        v = abs(float(m.group(2)))
        if m.group(3):
            v += float(m.group(3)) / 60.0
        if m.group(4):
            v += float(m.group(4)) / 3600.0
    except ValueError:
        return None
    hemi = (m.group(1) or m.group(5) or "").upper()
    if hemi in ("S", "W") or str(m.group(2)).startswith("-"):
        v = -v
    return {"v": v, "hemi": hemi}


def _order_lat_lng(a, b):
    a_is_lon = a["hemi"] in ("E", "W") or (
        abs(a["v"]) > 90 and abs(b["v"]) <= 90)
    b_is_lat = b["hemi"] in ("N", "S")
    if (a_is_lon and not b_is_lat) or b_is_lat:
        lat, lng = b["v"], a["v"]
    else:
        lat, lng = a["v"], b["v"]
    if abs(lat) > 90 or abs(lng) > 180:
        return None
    return {"latitude": lat, "longitude": lng}


def parse_coordinate_query(text):
    """座標と解釈できれば {"latitude","longitude"}、不可なら None。"""
    s = str(text or "").strip()
    if not s:
        return None
    for src, dst in ((("，", "、"), ","), ("北緯", "N"), ("南緯", "S"),
                     ("東経", "E"), ("西経", "W"), ("度", "°"), ("分", "'"),
                     ("秒", '"')):
        if isinstance(src, tuple):
            for ch in src:
                s = s.replace(ch, dst)
        else:
            s = s.replace(src, dst)
    for ch in "′’`":
        s = s.replace(ch, "'")
    for ch in "″”":
        s = s.replace(ch, '"')
    if not re.search(r"\d", s):
        return None
    if "," in s:
        candidates = [p.strip() for p in s.split(",") if p.strip()]
    else:
        candidates = [p for p in re.split(r"\s+", s) if p]
    for i in range(1, len(candidates)):
        a = _coord_component(" ".join(candidates[:i]))
        b = _coord_component(" ".join(candidates[i:]))
        if a and b:
            result = _order_lat_lng(a, b)
            if result:
                return result
    return None


# ---------------------------------------------------------------------------
# 結果を QGIS メモリレイヤのポイント地物へ展開するヘルパ
# (タブ型 SearchAddressFeature と bridge searchAddress で共用)
# ---------------------------------------------------------------------------

def ensure_address_layer(name=ADDRESS_LAYER_NAME, add_to_project=True):
    """住所検索結果用メモリレイヤ(EPSG:4326 ポイント)を find-or-create で返す。

    既存レイヤが見つかればそれを再利用し、無ければ作成する。
    add_to_project=True(既定)ならプロジェクトへ追加し、False なら
    レイヤツリーへ出さない非登録メモリレイヤとする(スクラッチ作成OFF)。
    プロジェクト切替で削除済みの場合は作り直す。
    """
    from qgis.core import (
        QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem,
        QgsMarkerSymbol)
    project = QgsProject.instance()
    for layer in project.mapLayersByName(name):
        try:
            if layer is not None and layer.isValid():
                return layer
        except Exception:  # nosec B110  # 削除済みC++ラッパー対策
            continue
    uri = "Point?crs=EPSG:4326" + "".join(
        "&field={}:{}".format(
            f, "double" if f in ("lon", "lat") else "string")
        for f in MEMORY_FIELDS)
    layer = QgsVectorLayer(uri, name, "memory")
    try:
        symbol = QgsMarkerSymbol.createSimple({
            "name": "circle", "color": "#e53935",
            "outline_color": "#ffffff", "outline_width": "0.4",
            "size": "3.4"})
        layer.renderer().setSymbol(symbol)
    except Exception:  # nosec B110  # シンボル設定失敗は既定描画のまま
        pass
    try:
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    except Exception:  # nosec B110  # 設計上の許容
        pass
    if add_to_project:
        project.addMapLayer(layer)
    return layer


def _item_to_feature(layer, it):
    """結果 dict 1件を QgsFeature 化する。座標が不正なら None。"""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY
    try:
        lon = float(it["longitude"])
        lat = float(it["latitude"])
    except (KeyError, TypeError, ValueError):
        return None
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
    f.setAttributes([
        str(it.get("title") or ""),
        str(it.get("address") or ""),
        str(it.get("provider") or ""),
        lon, lat,
    ])
    return f


def results_to_features(layer, items, append=False):
    """検索結果 dict をメモリレイヤの地物として書き込み、作成した
    QgsFeature のリストを返す。
    append=False(既定)は既存地物を消してから追加、True は追記のみ。"""
    provider_dp = layer.dataProvider()
    if not append:
        try:
            ids = [f.id() for f in layer.getFeatures()]
            if ids:
                provider_dp.deleteFeatures(ids)
        except Exception:  # nosec B110  # 設計上の許容
            pass
    new_features = []
    for it in items or []:
        f = _item_to_feature(layer, it)
        if f is not None:
            new_features.append(f)
    return _add_features(layer, provider_dp, new_features)


def _add_features(layer, provider_dp, feats):
    """provider へ地物を追加し、fid 確定済みの QgsFeature リストを返す。

    PyQGIS の addFeatures は (成功, 追加後の地物リスト) を返し、
    渡したオブジェクト側には fid が反映されない点に注意する
    (返却地物の id() が結果ダイアログの選択・ズームに使われる)。
    """
    if not feats:
        return []
    # フォールバック再取得用に既存 fid を控えておく(追加分のみ抽出するため)
    pre_ids = set()
    try:
        for f in layer.getFeatures():
            pre_ids.add(f.id())
    except Exception:  # nosec B110  # 設計上の許容
        pass
    res = provider_dp.addFeatures(feats)
    added = None
    try:
        # (bool, QgsFeatureList) 形式の戻り値を優先利用
        if isinstance(res, tuple) and len(res) >= 2:
            added = list(res[1])
    except Exception:  # nosec B110  # 設計上の許容
        added = None
    if added is None or len(added) != len(feats):
        # 戻り値が取れない環境は追加分だけをレイヤから取り直す
        try:
            added = [f for f in layer.getFeatures()
                     if f.id() not in pre_ids]
        except Exception:  # nosec B110  # 設計上の許容
            added = feats
    try:
        layer.updateExtents()
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return added


class AddressFeaturePager:
    """住所検索結果をページ単位で遅延地物化するシーケンス。

    ``len()`` は全アイテム数、``obj[s:e]`` は要求された範囲だけを
    メモリレイヤへ追記して QgsFeature のリストを返す。ResultDialog の
    page_limit 分割がそのまま「取得をページ単位」として働き、
    巨大な結果セットでも初期表示は先頭1ページ分の地物化で済む。
    ``_lazy`` 属性は ResultDialog 側の list() 変換ガード用フラグ。
    """

    _lazy = True

    def __init__(self, layer, items):
        self._layer = layer
        self._items = list(items or [])
        self._features = {}

    def __len__(self):
        return len(self._items)

    def __getitem__(self, key):
        n = len(self._items)
        if isinstance(key, slice):
            idxs = range(*key.indices(n))
            missing = [i for i in idxs if i not in self._features]
            if missing:
                self._append(missing)
            return [self._features[i] for i in idxs
                    if i in self._features]
        idx = int(key)
        if idx < 0:
            idx += n
        if idx < 0 or idx >= n:
            raise IndexError(key)
        if idx not in self._features:
            self._append([idx])
        return self._features[idx]

    def __iter__(self):
        # 反復はチャンク単位で順次地物化する(全件反復はフォーム表示等
        # の明示操作時のみ発生する)
        n = len(self._items)
        i = 0
        while i < n:
            e = min(i + 64, n)
            self._append([j for j in range(i, e) if j not in self._features])
            for j in range(i, e):
                if j in self._features:
                    yield self._features[j]
            i = e

    def _append(self, idxs):
        """指定インデックスのアイテムをメモリレイヤへ追記して地物化する。"""
        if not idxs:
            return
        provider_dp = self._layer.dataProvider()
        feats = []
        owners = []
        for i in idxs:
            f = _item_to_feature(self._layer, self._items[i])
            if f is None:
                continue
            feats.append(f)
            owners.append(i)
        if not feats:
            return
        added = _add_features(self._layer, provider_dp, feats)
        for i, f in zip(owners, added):
            self._features[i] = f
