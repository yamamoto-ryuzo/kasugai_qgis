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
RESULT_LIMIT = 5
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

def _search_gsi(query):
    url = ("https://msearch.gsi.go.jp/address-search/AddressSearch?q="
           + quote(query))
    data = json.loads(_http_get(url) or "[]")
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


def _search_osm(query):
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=5"
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
         "pageSize": 10},
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
    return items[:max(0, int(limit or RESULT_LIMIT))]


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


def results_to_features(layer, items):
    """検索結果 dict をメモリレイヤの地物として書き換え、QgsFeatureを返す。"""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY
    provider_dp = layer.dataProvider()
    try:
        ids = [f.id() for f in layer.getFeatures()]
        if ids:
            provider_dp.deleteFeatures(ids)
    except Exception:  # nosec B110  # 設計上の許容
        pass
    new_features = []
    for it in items or []:
        try:
            lon = float(it["longitude"])
            lat = float(it["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        f.setAttributes([
            str(it.get("title") or ""),
            str(it.get("address") or ""),
            str(it.get("provider") or ""),
            lon, lat,
        ])
        new_features.append(f)
    if new_features:
        provider_dp.addFeatures(new_features)
        layer.updateExtents()
    return list(layer.getFeatures())
