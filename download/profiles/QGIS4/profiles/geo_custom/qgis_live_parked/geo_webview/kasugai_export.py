# -*- coding: utf-8 -*-
"""KASUGAI Canvas 連携エクスポート。

QGIS プロジェクトの表示中ベクターレイヤーを GeoJSON + QGISスタイル(.qml)
として出力し、KASUGAI Canvas プロジェクト形式(.kasc + DATA/)を生成する。

KASUGAI Canvas は ``geojson: タイトル | DATA/x.geojson | on | style=DATA/x.qml``
形式の .kasc 行を読み、.qml の <renderer-v2> を Cesium 描画へコンパイルする。
ネイティブ参照できるソースは ``gpkg:``/``geojson:``/``geoparquet:``/
``flatgeobuf:``、CSV/TSV・フィルタ付きソースは ``duckdb:``、
3D Tiles レイヤは ``3dtiles:``、XYZ タイルは ``xyz:``/``base:`` 行になる。
ローカルサーバー版(port 8510)が起動していれば
``POST /api/projects/register {path: <kasc>}`` で外部プロジェクトとして
登録でき、そのまま ``?project=<id>`` で開ける(登録フォルダの DATA/ が
そのまま配信される)。``POST /api/command`` の switchProject で
起動中の画面を切り替えることもできる。
起動エンジンは ``/cesium/`` ``/maplibre/`` ``/openlayers/`` ``/leaflet/``
``/gsimaps/`` ``/navara/`` の実パスで直接指定できる(``?engine=``
リダイレクトへの
依存を避ける)。

このモジュールは PyQGIS 環境でのみ使用する(ユニットテスト不可)。
ネットワーク呼び出しは全て短いタイムアウト付きのベストエフォート。
"""

import json
import math
import os
import re
import shutil
import subprocess  # nosec B404  # kasugai_canvas.exe の連携起動用
import time
import urllib.error
import urllib.parse
import urllib.request

from .i18n_json import lang_code, translate_text

# KASUGAI Canvas ローカルサーバーの既定ポート(run.py _get_port と同じ)
DEFAULT_KASUGAI_PORT = 8510
SETTINGS_KEY_OUTPUT = 'kasugai_output_path'
SETTINGS_KEY_PORT = 'kasugai_port'

# KASUGAI Canvas の起動エンジン(web/index.html の engine パラメータと同じ)
VALID_ENGINES = ('cesium', 'maplibre', 'openlayers', 'leaflet', 'gsimaps',
                 'navara')
DEFAULT_ENGINE = 'cesium'

KASUGAI_EXE_NAME = 'kasugai_canvas.exe'
_KASUGAI_UNINSTALL_KEY = (
    r'Software\Microsoft\Windows\CurrentVersion\Uninstall\KASUGAI Canvas')

# ベースマップ候補群を表すレイヤツリーのグループ名(大小文字不問)。
# この名前のグループに入っている XYZ レイヤは base: 行として
# ベースマップ一覧へ登録する(グループ名自体はタイトルに含めず、
# 配下のサブグループは / 区切りのタイトルとして残し、
# Canvas 側のベースマップ選択でグループ化表示される)
# QSettings kasugai_basemap_groups(カンマ区切り)でユーザーが
# 追加名を登録できる(設定ダイアログの Basemap Groups)
BASEMAP_GROUP_NAMES = frozenset(
    ('背景図', 'ベースマップ', 'basemap'))
SETTINGS_KEY_BASEMAP_GROUPS = 'kasugai_basemap_groups'

# .kasc と同じ場所に出力するエンジン起動HTML(サーバレス配布用)。
# 各HTMLは ?kasc=<.kascの絶対URL> 付きでエンジンへ転送するだけの
# 自己完結ページ。エンジン本体(web/ の中身)は ./ ../ ../../ / の順に
# 自動探索し、見つからなければHTML内の CANVAS_BASE を編集してもらう
_LAUNCHER_ENGINES = (
    'cesium', 'maplibre', 'openlayers', 'leaflet', 'gsimaps', 'navara')

# 起動HTML内の __T_*__ トークン→英語ソースの対応表。
# i18n/<lang>.json の geo_webview.page コンテキストから
# QGISのUI言語へ翻訳して差し込む(未登録言語は英語のまま)。
_PAGE_CTX = 'geo_webview.page'
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

_PAGE_STRINGS = {
    '__T_SEARCHING__':
        'Searching for the engine\u2026',
    '__T_NOTFOUND__':
        'The engine (contents of <code>web/</code>) was not found.',
    '__T_UPLOAD__':
        'Upload this folder (<code>__KASC__</code> and <code>DATA/</code>) '
        'together with the engine to the same web server. Locations checked:',
    '__T_CANVAS_BASE__':
        'If the engine is placed elsewhere, set its URL (with a trailing '
        '<code>/</code>) in <code>CANVAS_BASE</code> in this HTML.',
    '__T_NOSCRIPT__':
        'This page requires JavaScript.',
    '__T_LOCALHELP__':
        'Could not connect to the local KASUGAI Canvas '
        "(<a href='http://127.0.0.1:8510/'>127.0.0.1:8510</a>). "
        'Start the app and reload this page. '
        '(For use on an external web host, upload this folder and the '
        'engine to the same server.)',
    '__T_HOSTED_PH__':
        'Hosted engine URL (e.g. https://example.com/canvas/)',
    '__T_OPEN_HOSTED__':
        'Open in hosted engine',
    '__T_BROWSER_ONLY__':
        'Runs in the browser only (select this folder \u2192 ?kasc=local)',
    '__T_TITLE__':
        'KASUGAI Canvas project \u2014 __KASC__',
    '__T_H1__':
        'KASUGAI Canvas project \u2014 <code>__KASC__</code>',
    '__T_INTRO__':
        'This export (<code>.kasc</code>+<code>DATA/</code>, launcher HTMLs) '
        'can be viewed in three ways.',
    '__T_ROUTE1__':
        'Open in KASUGAI Canvas (main integrated player)',
    '__T_ROUTE1_NOTE__':
        'Registers the project with a running Canvas app (127.0.0.1:8510) '
        'and opens it. If the app is not running, start it and reload '
        'this page.',
    '__T_CONNECTING__':
        'Connecting to Canvas\u2026',
    '__T_ROUTE2__':
        'Instant view in the browser via local HTTP delivery',
    '__T_ROUTE2_NOTE__':
        "The QGIS plugin's HTTP server serves the installed Canvas "
        '<code>web/</code> and <code>DATA/</code> (requires Canvas '
        'installed + server running).',
    '__T_LOCALNOTE__':
        'Open this page via <code>http://localhost:8089/export-data/</code> '
        'to enable the links.',
    '__T_ROUTE3__':
        'Serverless web delivery',
    '__T_ROUTE3_NOTE__':
        'Opens in the hosted engine (GitHub Pages). Data is available only '
        'while the plugin server is running.<br />'
        'For permanent hosting, <b>upload this whole folder plus the '
        'engine (contents of web/) to the same static host</b> and use the '
        'launcher HTMLs below (the engine is auto-detected).',
    '__T_LAUNCHER_LIST__':
        'Launcher pages after deployment:',
    '__T_CANVASBASE2__':
        '(engine location can be set via <code>CANVAS_BASE</code> in each '
        'HTML)',
    '__T_PACKAGEZIP__':
        'Package ZIP',
    '__T_ZIPDESC__':
        'A ZIP of the whole export (<code>.kasc</code>+<code>DATA/</code>+'
        'launcher HTMLs). Useful for static-host deployment and Re:Earth '
        'geo_suite <code>qgis:</code> import.<br />'
        "When opened via the plugin's HTTP server, clicking generates it "
        'on the fly and downloads it.',
    '__T_ZIPDL__':
        'Download __ZIP_NAME__',
    '__T_ZIPDISABLED__':
        '(ZIP download is disabled on file:// \u2014 open via the HTTP '
        'server)',
    '__T_LABEL_CESIUM__':
        'Cesium (3D, default)',
    '__T_NOCONN__':
        '<li>Cannot connect to the Canvas app (not running). Start it and '
        'reload this page.</li>',
    '__T_LOCALDISABLED__':
        "<li>(disabled) Open via the plugin's HTTP server</li>",
    '__T_HOSTEDUNSET__':
        '<li>(hosted URL not set) Upload this folder and the engine to a '
        'static host</li>',
}


def _localize_page(html):
    """テンプレート内の __LANG__ / __T_*__ を現在のUI言語で置換する。"""
    html = html.replace('__LANG__', lang_code() or 'en')
    for token, source in _PAGE_STRINGS.items():
        html = html.replace(
            token, translate_text(_PLUGIN_DIR, _PAGE_CTX, source))
    return html


_ENGINE_LAUNCHER_HTML = '''<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>KASUGAI Canvas — __ENGINE__</title>
<style>
  body { font-family: system-ui,"Segoe UI","Yu Gothic",sans-serif; margin: 28px; line-height: 1.65; color: #1d2b35; }
  code { background: #eef2f5; padding: 1px 5px; border-radius: 4px; }
  #tried a { color: #2c5ea8; }
  .note { color: #52636d; font-size: 0.9em; }
</style>
</head>
<body>
<h1 style="font-size:1.15em">KASUGAI Canvas — __ENGINE__</h1>
<p id="status">__T_SEARCHING__</p>
<div id="notfound" hidden>
  <p>__T_NOTFOUND__<br />
  __T_UPLOAD__</p>
  <ul id="tried"></ul>
  <p class="note">__T_CANVAS_BASE__</p>
</div>
<noscript><p>__T_NOSCRIPT__</p></noscript>
<script>
(function () {
  "use strict";
  // Location of the KASUGAI Canvas engine (contents of web/).
  // Point to the directory containing cesium/ maplibre/ openlayers/
  // leaflet/ gsimaps/ navara/ shared/ with a trailing /
  // (e.g. "https://example.com/canvas/").
  // When left empty, __ENGINE__/index.html is probed under ./ ../ ../../ /
  var CANVAS_BASE = "";
  // URL of the hosted engine (trailing /, e.g. "https://example.com/canvas/").
  // When set, file:// launches offer an "open in hosted engine" option
  // (?kasc=local mode where the browser reads a local folder by itself)
  var HOSTED_BASE = "__HOSTED_BASE__";
  var ENGINE = "__ENGINE__";
  var KASC = "__KASC__";
  var kascUrl = new URL(KASC, location.href).href;
  var ENGINES = ["cesium", "maplibre", "openlayers", "leaflet", "gsimaps", "navara"];
  function engineBase(base) {
    // If the base ends with an engine directory, replace it; otherwise append ENGINE
    var u = new URL(base, location.href);
    u.search = ""; u.hash = "";
    var seg = u.pathname.replace(/[/]+$/, "").split("/").pop().toLowerCase();
    if (ENGINES.indexOf(seg) >= 0) {
      u.pathname = u.pathname.replace(/[^/]+[/]?$/, ENGINE + "/");
      return u.href;
    }
    return new URL(ENGINE + "/", u).href;
  }
  function target(base) {
    return engineBase(base) + "?kasc=" + encodeURIComponent(kascUrl);
  }
  // On file://, register the .kasc with the local KASUGAI Canvas
  // (127.0.0.1:8510) as an external project and forward to
  // /<engine>/?project=<id>. Browsers cannot fetch local files from
  // file:// pages, so no web probing is done (CANVAS_BASE wins if set)
  if (!CANVAS_BASE && location.protocol === "file:") {
    var kascPath = decodeURIComponent(new URL(KASC, location.href).pathname)
      .replace(/^\\/([A-Za-z]:)/, "$1").replace(/\\//g, "\\\\");
    function localHelp() {
      document.getElementById("status").innerHTML = "__T_LOCALHELP__";
      // "Open in hosted engine": works even without HOSTED_BASE preset.
      // The input is kept in localStorage (shared by all launchers on file://)
      var row = document.createElement("div");
      row.style.cssText = "margin-top:10px";
      var inp = document.createElement("input");
      inp.placeholder = "__T_HOSTED_PH__";
      inp.style.cssText = "width:65%;padding:4px";
      try {
        inp.value = HOSTED_BASE || localStorage.getItem("kasugai_hosted_base") || "";
      } catch (e) { inp.value = HOSTED_BASE; }
      var go = document.createElement("button");
      go.textContent = "__T_OPEN_HOSTED__";
      go.style.cssText = "padding:4px 10px;margin-left:4px";
      go.onclick = function () {
        var base = inp.value.trim();
        if (!base) return;
        if (!/[\\/]$/.test(base)) base += "/";
        try { localStorage.setItem("kasugai_hosted_base", base); } catch (e) {}
        // Pass this folder name as dirhint so the hosted UI can guide selection
        var dirName = "";
        try {
          dirName = decodeURIComponent(location.pathname.replace(/[/][^/]*$/, "")
            .split("/").filter(Boolean).pop() || "");
        } catch (e) {}
        location.href = engineBase(base) + "?kasc=local" +
          (dirName ? "&dirhint=" + encodeURIComponent(dirName) : "");
      };
      row.appendChild(inp); row.appendChild(go);
      var hint = document.createElement("div");
      hint.style.cssText = "font-size:11px;color:#667;margin-top:4px";
      hint.textContent = "__T_BROWSER_ONLY__";
      row.appendChild(hint);
      document.getElementById("status").appendChild(row);
    }
    fetch("http://127.0.0.1:8510/api/projects/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: kascPath })
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (res) {
        if (res && res.id) {
          location.replace("http://127.0.0.1:8510/" + ENGINE + "/?project=" + encodeURIComponent(res.id));
        } else { localHelp(); }
      }).catch(localHelp);
    return;
  }
  if (CANVAS_BASE) {
    location.replace(target(new URL(CANVAS_BASE, location.href)));
    return;
  }
  var bases = ["./", "../", "../../", "/"];
  var i = 0;
  function next() {
    if (i >= bases.length) {
      document.getElementById("status").hidden = true;
      document.getElementById("notfound").hidden = false;
      // On http(s) delivery (e.g. geo_webview :8089) the .kasc already
      // lives on this server, so an absolute URL can forward straight
      // to the hosted engine
      if (HOSTED_BASE && location.protocol.indexOf("http") === 0) {
        var hp = document.createElement("p");
        var ha = document.createElement("a");
        ha.href = target(HOSTED_BASE);
        ha.textContent = "__T_OPEN_HOSTED__";
        hp.appendChild(ha);
        document.getElementById("notfound").appendChild(hp);
      }
      return;
    }
    var base = new URL(bases[i], location.href); i += 1;
    var probe = new URL(ENGINE + "/index.html", base).href;
    var li = document.createElement("li");
    var a = document.createElement("a");
    a.href = target(base); a.textContent = probe;
    li.appendChild(a);
    document.getElementById("tried").appendChild(li);
    fetch(probe, { method: "HEAD", cache: "no-store" })
      .then(function (r) { if (r.ok) location.replace(target(base)); else next(); })
      .catch(function () { next(); });
  }
  next();
})();
</script>
</body>
</html>
'''

_LAUNCHER_INDEX_HTML = '''<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__T_TITLE__</title>
<style>
  body { font-family: system-ui,"Segoe UI","Yu Gothic",sans-serif; margin: 28px; line-height: 1.65; color: #1d2b35; max-width: 900px; }
  code { background: #eef2f5; padding: 1px 5px; border-radius: 4px; }
  section { border: 1px solid #d7dfe6; border-radius: 8px; padding: 10px 16px; margin: 14px 0; }
  h2 { font-size: 1em; margin: 0 0 6px; }
  ul { margin: 6px 0; padding-left: 20px; }
  li { margin: 3px 0; }
  a { color: #2c5ea8; }
  .note { color: #52636d; font-size: 0.88em; }
  .route-no { display: inline-block; background: #2c5ea8; color: #fff; border-radius: 50%;
    width: 1.5em; height: 1.5em; text-align: center; line-height: 1.5em; margin-right: 6px; font-size: 0.8em; }
</style>
</head>
<body>
<h1 style="font-size:1.15em">__T_H1__</h1>
<p>__T_INTRO__</p>

<section>
  <h2><span class="route-no">1</span>__T_ROUTE1__</h2>
  <p class="note">__T_ROUTE1_NOTE__</p>
  <ul id="canvas-links"><li>__T_CONNECTING__</li></ul>
</section>

<section>
  <h2><span class="route-no">2</span>__T_ROUTE2__</h2>
  <p class="note">__T_ROUTE2_NOTE__</p>
  <ul id="local-links"></ul>
  <p id="local-note" class="note" hidden>__T_LOCALNOTE__</p>
</section>

<section>
  <h2><span class="route-no">3</span>__T_ROUTE3__</h2>
  <p class="note">__T_ROUTE3_NOTE__</p>
  <ul id="hosted-links"></ul>
  <p class="note">__T_LAUNCHER_LIST__
    <a href="cesium.html">cesium.html</a> / <a href="maplibre.html">maplibre.html</a> /
    <a href="openlayers.html">openlayers.html</a> / <a href="leaflet.html">leaflet.html</a> /
    <a href="gsimaps.html">gsimaps.html</a> / <a href="navara.html">navara.html</a>
    __T_CANVASBASE2__</p>
</section>

<section>
  <h2>__T_PACKAGEZIP__</h2>
  <p class="note">__T_ZIPDESC__
  <span id="zip-note"></span></p>
  <p><a href="__ZIP_NAME__" download>__T_ZIPDL__</a></p>
</section>

<script>
(function () {
  "use strict";
  var KASC = "__KASC__";
  var HOSTED_BASE = "__HOSTED_BASE__";
  var ENGINES = ["cesium", "maplibre", "openlayers", "leaflet", "gsimaps", "navara"];
  var LABELS = { cesium: "__T_LABEL_CESIUM__", maplibre: "MapLibre GL", openlayers: "OpenLayers", leaflet: "Leaflet", gsimaps: "GSI Maps", navara: "Navara" };
  var kascUrl = new URL(KASC, location.href).href;
  var isHttp = /^https?:$/.test(location.protocol);
  if (!isHttp) {
    document.getElementById("zip-note").textContent = "__T_ZIPDISABLED__";
  }
  function links(el, make) {
    var ul = document.getElementById(el);
    ul.innerHTML = "";
    ENGINES.forEach(function (e) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = make(e); a.textContent = LABELS[e];
      li.appendChild(a); ul.appendChild(li);
    });
  }
  // (1) KASUGAI Canvas (main integrated player): register the project on
  //     127.0.0.1:8510 and open it. file:// registers the local path,
  //     http(s) reuses the ?kasc= URL directly
  var cl = document.getElementById("canvas-links");
  var kascPath = "";
  try {
    kascPath = decodeURIComponent(new URL(KASC, location.href).pathname)
      .replace(/^[/]([A-Za-z]:)/, "$1");
  } catch (e) {}
  fetch("http://127.0.0.1:8510/health", { cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function () {
      if (isHttp) {
        links("canvas-links", function (e) {
          return "http://127.0.0.1:8510/" + e + "/?kasc=" + encodeURIComponent(kascUrl);
        });
      } else {
        // file://: pass the local path to the register API and open ?project=
        return fetch("http://127.0.0.1:8510/api/projects/register", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: kascPath.replace(new RegExp("[/]", "g"), "\\\\") })
        }).then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function (res) {
            links("canvas-links", function (e) {
              return "http://127.0.0.1:8510/" + e + "/?project=" + encodeURIComponent(res.id);
            });
          });
      }
    })
    .catch(function () {
      cl.innerHTML = "__T_NOCONN__";
    });
  // (2) Local HTTP delivery: only when this page is served over http(s)
  //     (e.g. opened via geo_webview :8089)
  if (isHttp) {
    links("local-links", function (e) {
      return location.origin + "/" + e + "/?kasc=" + encodeURIComponent(kascUrl);
    });
  } else {
    document.getElementById("local-links").innerHTML = "__T_LOCALDISABLED__";
    document.getElementById("local-note").hidden = false;
  }
  // (3) Serverless web delivery: absolute .kasc URL on http(s), or
  //     ?kasc=local (folder-pick mode of the hosted engine) on file://
  if (HOSTED_BASE) {
    links("hosted-links", function (e) {
      if (isHttp) {
        return HOSTED_BASE + e + "/?kasc=" + encodeURIComponent(kascUrl);
      }
      var dirName = "";
      try {
        dirName = decodeURIComponent(location.pathname.replace(/[/][^/]*$/, "")
          .split("/").filter(Boolean).pop() || "");
      } catch (e2) {}
      return HOSTED_BASE + e + "/?kasc=local" +
        (dirName ? "&dirhint=" + encodeURIComponent(dirName) : "");
    });
  } else {
    document.getElementById("hosted-links").innerHTML = "__T_HOSTEDUNSET__";
  }
})();
</script>
</body>
</html>
'''


def normalize_engine(engine):
    """engine 名を正規化。無効値は None を返す。"""
    e = str(engine or '').strip().lower()
    return e if e in VALID_ENGINES else None


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


def set_output_dir(path):
    """パネル等で選択した出力先を QSettings に保存する。

    空文字/'__default__' を渡すと既定(インストール先/ドキュメント)に戻る。
    """
    _qsettings().setValue(SETTINGS_KEY_OUTPUT, (path or '').strip())


def get_kasugai_install_dir():
    """QSettings の kasugai_install_path（KASUGAI Canvas インストール先）を返す。

    設定済みでディレクトリが存在する場合のみ返し、それ以外は None。
    空/'__default__' は未設定扱い。
    """
    try:
        saved = (_qsettings().value('kasugai_install_path', '') or '').strip()
        if saved and saved != '__default__' and os.path.isdir(saved):
            return saved
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return None


def _registry_install_dir():
    """Windows インストーラが登録するインストール先をレジストリから返す。

    HKCU\\...\\Uninstall\\KASUGAI Canvas\\InstallLocation。
    未登録・非 Windows は None。
    """
    if os.name != 'nt':
        return None
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _KASUGAI_UNINSTALL_KEY) as key:
            loc = winreg.QueryValueEx(key, 'InstallLocation')[0]
        # ディレクトリが消えた/ファイルのみ欠落した中途半端な登録は
        # 未インストール扱いにする(exe の存在まで確認)
        if loc and os.path.isfile(os.path.join(loc, KASUGAI_EXE_NAME)):
            return loc
    except Exception:  # nosec B110  # レジストリ未登録は正常系
        pass
    return None


def detect_kasugai_install_dir():
    """KASUGAI Canvas のインストール先を特定して返す（見つからなければ None）。

    1) QSettings ``kasugai_install_path``（設定で明示登録）
    2) Windows インストーラのレジストリ InstallLocation（設定未登録でも
       インストール済みなら一体運用に使う）
    """
    return get_kasugai_install_dir() or _registry_install_dir()


def kasugai_projects_dir():
    """KASUGAI インストール先の projects/ ディレクトリを返す（未設定なら None）。

    <install>/projects/ を優先し、無ければ <install>/web/projects/、
    どちらも無ければ <install>/projects/ を作成して返す。
    """
    install = detect_kasugai_install_dir()
    if not install:
        return None
    for cand in (os.path.join(install, 'projects'),
                 os.path.join(install, 'web', 'projects')):
        if os.path.isdir(cand):
            return cand
    cand = os.path.join(install, 'projects')
    os.makedirs(cand, exist_ok=True)
    return cand


def kasugai_qgis_projects_dir():
    """QGIS 連携プロジェクト専用の ``<install>/QGIS_projects/`` を返す。

    Canvas 本体の ``projects/``（ユーザー管理）と分離し、QGIS 由来の
    エクスポートを専用フォルダに置く。Canvas への表示は
    ``/api/projects/register`` の外部プロジェクト登録経由。
    インストール先を検出できなければ None（設定未登録でもレジストリ
    検出で一体運用になる）。ディレクトリは必要時に作成する。
    """
    install = detect_kasugai_install_dir()
    if not install:
        return None
    cand = os.path.join(install, 'QGIS_projects')
    os.makedirs(cand, exist_ok=True)
    return cand


def preferred_output_dir(project_name=None):
    """QGIS 連携プロジェクトの出力先ディレクトリを決める。

    パネル等で出力先(kasugai_output_path)を明示している場合はそれを
    最優先で使う。未設定なら KASUGAI Canvas のインストール先が
    登録済みのとき ``<install>/QGIS_projects/<QGISプロジェクト名>/``
    （Canvas 本体の projects/ と分離した QGIS 連携専用フォルダ。
    Canvas への表示は外部プロジェクト登録経由）、未登録なら
    ``default_output_dir()``（``<Documents>/kasugai_canvas_qgis``）。

    project_name 未指定時は QgsProject.instance().baseName()。
    """
    try:
        saved = str(
            _qsettings().value(SETTINGS_KEY_OUTPUT, '') or '').strip()
        if saved and saved != '__default__':
            return saved
    except Exception:  # nosec B110  # 設計上の許容
        pass
    proj_dir = kasugai_qgis_projects_dir()
    if proj_dir:
        if not project_name:
            try:
                from qgis.core import QgsProject
                project_name = QgsProject.instance().baseName()
            except Exception:  # nosec B110  # 設計上の許容
                project_name = None
        return os.path.join(
            proj_dir, project_dir_slug(project_name or 'qgis_export'))
    return default_output_dir()


_last_export_dir = None


def last_export_dir():
    """直近のエクスポート出力先（/export-data/ の配信ルート）。

    セッション内で一度もエクスポートしていなければ preferred_output_dir()
    （実際の出力先と同じ規則: 設定→Canvasインストール先→Documents）。
    """
    return _last_export_dir or preferred_output_dir()


def existing_export(output_dir=None):
    """既にエクスポート済みの ``kasugai_canvas.kasc`` を探す。

    output_dir 未指定時は preferred_output_dir() と同じ規則で出力先を
    決める。見つかれば ``(dir, kasc_path)`` を返し、_last_export_dir も
    更新して /export-data/ の配信ルートとして使えるようにする。
    未エクスポートなら None。
    """
    global _last_export_dir
    out_dir = os.path.abspath(output_dir or preferred_output_dir())
    kasc = os.path.join(out_dir, 'kasugai_canvas.kasc')
    if not os.path.isfile(kasc):
        return None
    _last_export_dir = out_dir
    return out_dir, kasc


def project_dir_slug(name):
    """プロジェクト名から projects/<id>/ 用の安全なスラッグを作る。"""
    import re as _re
    slug = _re.sub(r'[^A-Za-z0-9_-]+', '_', str(name or '').strip()).strip('_')
    return slug or 'qgis_export'


def get_kasugai_port():
    """QSettings の kasugai_port(未設定は8510)を返す。"""
    try:
        saved = _qsettings().value(SETTINGS_KEY_PORT, '') or ''
        if str(saved).strip():
            return int(str(saved).strip())
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return DEFAULT_KASUGAI_PORT


# ---- ホスト版エンジン(kasugai-canvas-web) ----

KASUGAI_WEB_HOST = (
    'https://yamamoto-ryuzo.github.io/kasugai-canvas-web/')
HOSTED_CHANNELS = ('stable', 'unstable')
SETTINGS_KEY_HOSTED_CHANNEL = 'kasugai_hosted_channel'


def get_hosted_channel():
    """QSettings の kasugai_hosted_channel(未設定は 'stable')を返す。

    'stable'/'unstable' または完全URL(自前ホスト用)を取る。
    """
    v = (_qsettings().value(SETTINGS_KEY_HOSTED_CHANNEL, '') or '')
    return str(v).strip() or 'stable'


def export_zip_name(channel=None):
    """エクスポートZIPのファイル名を返す。

    CDNチャンネル(stable/unstable/カスタムURL)を
    ``kasugai_canvas_<tag>.zip`` として反映する。
    カスタムURLは末尾パス要素をタグ化する。
    """
    ch = str(channel if channel is not None
             else get_hosted_channel()).strip()
    if ch.lower() in HOSTED_CHANNELS:
        tag = ch.lower()
    elif ch.lower().startswith(('http://', 'https://')):
        seg = urllib.parse.urlparse(ch).path.rstrip('/').rsplit('/', 1)[-1]
        tag = re.sub(r'[^A-Za-z0-9_.-]+', '_', seg) or 'custom'
    else:
        tag = 'custom'
    return 'kasugai_canvas_{0}.zip'.format(tag)


def _is_export_zip_name(name):
    """kasugai_canvas.zip / kasugai_canvas_<tag>.zip 形式なら True。"""
    return bool(re.match(r'kasugai_canvas(_[A-Za-z0-9_.-]+)?\.zip$',
                         os.path.basename(name or ''), re.IGNORECASE))


def hosted_engine_base(channel=None):
    """ホスト版エンジンのベースURL(末尾/付き)を返す。

    channel に http(s):// 始まりの値を渡すと自前ホストURLとして使う。
    未知の値は stable にフォールバックする。
    """
    ch = str(channel if channel is not None
             else get_hosted_channel()).strip()
    if ch.lower().startswith(('http://', 'https://')):
        return ch if ch.endswith('/') else ch + '/'
    if ch.lower() not in HOSTED_CHANNELS:
        ch = 'stable'
    return '{0}{1}/'.format(KASUGAI_WEB_HOST, ch.lower())


def build_hosted_view_url(kasc_path, engine=None, port=None,
                          channel=None):
    """ホスト版エンジン + geo_webviewサーバのデータ配信で .kasc を開くURL。

    Canvas未インストール環境向けの最終フォールバック。
    ホスト版エンジンが /export-data/ 配下の .kasc+DATA/ を
    http://localhost:<port> から fetch する(サーバ側の
    OPTIONS/PNA対応が前提)。kasc_path が last_export_dir()
    配下に無い場合は None。
    """
    if not port:
        return None
    try:
        rel = os.path.relpath(kasc_path, last_export_dir())
    except ValueError:
        return None
    rel = rel.replace('\\', '/')
    if rel.startswith('..'):
        return None
    kasc_url = 'http://127.0.0.1:{0}/export-data/{1}'.format(
        int(port), urllib.parse.quote(rel))
    e = normalize_engine(engine) or DEFAULT_ENGINE
    return '{0}{1}/?kasc={2}'.format(
        hosted_engine_base(channel), e,
        urllib.parse.quote(kasc_url, safe=''))


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


def _kasc_layer_title(groups, leaf_name, exclusive_groups=None):
    """レイヤツリーのパンくずタイトルを返す。

    直系の親グループが相互排他(exclusive_groups に収集済み)なら
    親子間を ``//`` で繋ぐ(Canvas の排他グループ指定と同規則)。
    """
    parts = ([_kasc_escape(g) for g in groups if g] +
             [_kasc_escape(leaf_name)])
    if len(parts) > 1 and exclusive_groups is not None \
            and tuple(groups) in exclusive_groups:
        return '/'.join(parts[:-1]) + '//' + parts[-1]
    return '/'.join(parts)


def _project_maplayer_elements(project):
    """プロジェクトファイル(.qgs/.qgz)の <maplayer> 要素を id 引き辞書で返す。

    戻り値は ``(doc, {layer_id: QDomElement})``。doc は QDomElement の
    DOM 生存のために呼び出し側で保持する。取得不可時は ``(None, {})``。
    """
    from qgis.PyQt.QtXml import QDomDocument
    fname = project.fileName() or ''
    if not fname or not os.path.exists(fname):
        return None, {}
    try:
        if fname.lower().endswith('.qgz'):
            import zipfile
            with zipfile.ZipFile(fname) as zf:
                names = [n for n in zf.namelist()
                         if n.lower().endswith('.qgs')]
                if not names:
                    return None, {}
                data = zf.read(names[0])
        else:
            with open(fname, 'rb') as f:
                data = f.read()
        doc = QDomDocument()
        if not doc.setContent(data):
            return None, {}
        elems = {}
        lst = doc.elementsByTagName('maplayer')
        for i in range(lst.count()):
            el = lst.item(i).toElement()
            lid = el.namedItem('id').toElement().text()
            if lid:
                elems[lid] = el
        return doc, elems
    except Exception:  # nosec B110  # 設計上の許容
        return None, {}


# <maplayer> の type 属性 → レイヤクラス名(plugin/annotation/group は対象外)
_MAPLAYER_TYPE_CLS = {
    'vector': 'QgsVectorLayer',
    'raster': 'QgsRasterLayer',
    'mesh': 'QgsMeshLayer',
    'vector-tile': 'QgsVectorTileLayer',
    'point-cloud': 'QgsPointCloudLayer',
    'tiled-scene': 'QgsTiledSceneLayer',
}


def _layer_from_maplayer_elem(elem, context):
    """<maplayer> 要素から QgsMapLayer を再生成する。失敗時 None。"""
    import qgis.core as qc
    cls = getattr(qc, _MAPLAYER_TYPE_CLS.get(
        elem.attribute('type') or '', ''), None)
    if cls is None:
        return None
    try:
        lyr = cls()
        if lyr.readLayerXml(elem, context):
            return lyr
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return None


def _retry_invalid_layer(layer):
    """isValid()=False のレイヤへデータソース再解決を試みる。

    破損レイヤ(読込時にソース未達等)は id・スタイル・設定を保ったまま
    setDataSource で同一ソースを再オープンできる。成功時 True。
    """
    try:
        if layer.isValid():
            return True
    except Exception:  # nosec B110  # 設計上の許容
        return False
    try:
        src = layer.source() or ''
        prov = layer.providerType() or ''
        name = layer.name() or ''
        if not src:
            return False
        layer.setDataSource(src, name, prov)
        return bool(layer.isValid())
    except Exception:  # nosec B110  # 設計上の許容
        return False


def _load_unresolved_layer(project, node, maplayer_elems, context):
    """layer()=None のツリーノードをプロジェクトXML定義から再生成・再登録する。

    <maplayer> 要素を readLayerXml で読むため、スタイルやフィルタ等の
    プロジェクト設定も復元される。再登録に成功すれば
    layerTreeRegistryBridge が同 id の弱参照ノードへ自動解決する。
    """
    lid = ''
    try:
        lid = node.layerId() or ''
    except Exception:  # nosec B110  # 設計上の許容
        pass
    elem = maplayer_elems.get(lid)
    if elem is None:
        return None
    lyr = _layer_from_maplayer_elem(elem, context)
    if lyr is None or not lyr.isValid():
        return None
    project.addMapLayer(lyr)
    try:
        node.resolveReferences(project)
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return node.layer() or lyr


def _tree_layers(skipped=None, warnings=None, group_states=None,
                 exclusive_groups=None):
    """レイヤツリー順(上から)に (layer, group_path, visible) で返す。

    visible はノード自身のチェックと全祖先の表示状態の積(実効表示状態)。

    layer() が未解決のノード(ソース破損等でプロジェクトへ読み込まれ
    なかったレイヤ)は、プロジェクトファイルの <maplayer> 定義から
    再生成して再登録し、本来のツリー位置で出力する。解決不能なものは
    skipped へ「(未読込レイヤ)」として記録する。

    group_states に dict を渡すと、「 / 」連結のグループパスをキーに
    展開状態(True=expanded/False=collapsed)を収集する(#59)。
    exclusive_groups に set を渡すと、相互排他(チェックで1つだけ表示)な
    グループのパス(tuple)を収集する。直系のレイヤは ``//`` 区切りの
    排他グループタイトルとして出力する。
    """
    from qgis.core import (QgsProject, QgsReadWriteContext,
                           QgsPathResolver)
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    entries = []

    def _walk(node, groups, visible):
        from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer

        def _subtree_checked(gnode):
            """グループ配下の全レイヤノードのチェック状態を集約する
            (#63: グループの checked/unchecked/partial を再現するため)。"""
            states = []
            for ch in gnode.children():
                if isinstance(ch, QgsLayerTreeGroup):
                    states.extend(_subtree_checked(ch))
                elif isinstance(ch, QgsLayerTreeLayer):
                    try:
                        states.append(bool(ch.itemVisibilityChecked()))
                    except Exception:  # nosec B110  # 設計上の許容
                        states.append(True)
            return states

        excl = False
        if (exclusive_groups is not None
                and isinstance(node, QgsLayerTreeGroup)):
            try:
                excl = bool(node.isMutuallyExclusive())
            except Exception:  # nosec B110  # 設計上の許容
                excl = False
        for child in node.children():
            try:
                checked = child.itemVisibilityChecked()
            except Exception:
                checked = True
            eff = visible and bool(checked)
            if isinstance(child, QgsLayerTreeGroup):
                path = groups + [child.name()]
                if group_states is not None:
                    try:
                        expanded = bool(child.isExpanded())
                    except Exception:  # nosec B110  # 設計上の許容
                        expanded = True
                    _st = _subtree_checked(child)
                    _cs = ('checked' if all(_st)
                           else 'unchecked' if not any(_st) else 'partial')
                    group_states[' / '.join(path)] = (expanded, _cs)
                _walk(child, path, eff)
            elif isinstance(child, QgsLayerTreeLayer):
                entries.append((child, list(groups), eff))
                if excl:
                    exclusive_groups.add(tuple(groups))

    _walk(root, [], True)

    # 未読込レイヤがあればプロジェクトXMLを一度だけ読み、
    # <maplayer> 定義から再生成を試みる
    maplayer_elems = {}
    doc = None
    if any(node.layer() is None for node, _g, _v in entries):
        doc, maplayer_elems = _project_maplayer_elements(project)
    _ = doc  # QDomElement 生存のため DOM を保持するのみ
    context = QgsReadWriteContext()
    try:
        context.setPathResolver(QgsPathResolver(project.fileName()))
    except Exception:  # nosec B110  # 設計上の許容
        pass

    result = []
    for node, groups, eff in entries:
        lyr = node.layer()
        if lyr is None:
            lyr = _load_unresolved_layer(
                project, node, maplayer_elems, context)
            if warnings is not None and lyr is not None:
                warnings.append(
                    '{0}: 未読込レイヤを再読込'.format(lyr.name()))
            elif skipped is not None and lyr is None:
                skipped.append(
                    '{0} (未読込レイヤ)'.format(
                        node.name() or node.layerId()))
        else:
            try:
                valid = bool(lyr.isValid())
            except Exception:  # nosec B110  # 設計上の許容
                valid = True
            if not valid:
                # 破損レイヤ(読込時にソース未達等)は同一定義で再オープンを試みる
                if _retry_invalid_layer(lyr):
                    if warnings is not None:
                        warnings.append(
                            '{0}: 破損レイヤを再読込'.format(lyr.name()))
                elif skipped is not None:
                    skipped.append(
                        '{0} (破損レイヤ)'.format(lyr.name()))
                    continue
        if lyr is not None:
            result.append((lyr, groups, eff, node))
    return result


def _basemap_group_names():
    """ベースマップグループ名の集合(小文字)を返す。

    内蔵の BASEMAP_GROUP_NAMES に、QSettings
    ``kasugai_basemap_groups``(カンマ/読点/改行区切り)でユーザーが
    追加した名前を加えたもの。
    """
    names = set(BASEMAP_GROUP_NAMES)
    try:
        extra = _qsettings().value(SETTINGS_KEY_BASEMAP_GROUPS, '') or ''
    except Exception:  # nosec B110  # QSettings 非依存環境では空扱い
        extra = ''
    for part in re.split(r'[,;、，\n\r]+', str(extra)):
        part = part.strip().lower()
        if part:
            names.add(part)
    return names


def _basemap_group_index(groups, names=None):
    """groups 内でベースマップグループ名に一致する最外側の index を返す。

    names 省略時は _basemap_group_names() を使う。
    一致するグループが無ければ None。
    """
    names = names if names is not None else _basemap_group_names()
    for i, name in enumerate(groups or []):
        if (name or '').strip().lower() in names:
            return i
    return None


def _geo_equiv_crs(layer):
    """Canvas が再投影なしで扱える地理座標系か(4326 系・CRS84・JGD)。"""
    try:
        crs = layer.crs()
        if not crs or not crs.isValid():
            return False
        if crs.authid().upper() in ('EPSG:4326', 'EPSG:4269',
                                    'EPSG:4612', 'EPSG:6668'):
            return True
        return crs.isGeographic()
    except Exception:
        return False


def _source_path(layer):
    """ogr 系ソースの実ファイルパスを取り出す。なければ None。"""
    try:
        from qgis.core import QgsDataSourceUri
        db = QgsDataSourceUri(layer.source()).database()
    except Exception:
        db = ''
    cand = db or (layer.source() or '').split('|')[0]
    cand = urllib.parse.unquote(cand)
    if cand.startswith('file://'):
        cand = cand[7:]
    if re.match(r'^/[A-Za-z]:/', cand):
        cand = cand[1:]
    return cand if cand and os.path.exists(cand) else None


def _same_data_copy(src_abs, dest_abs):
    """DATA/ 内の既存コピーがソースと同一内容か(サイズ+mtime一致)。

    copy2 はソースの mtime を保持するため、過去エクスポートの複製は
    この条件に一致する。一致すれば再コピー不要(複製の蓄積防止)。
    """
    try:
        s, d = os.stat(src_abs), os.stat(dest_abs)
    except OSError:
        return False
    return s.st_size == d.st_size and s.st_mtime == d.st_mtime


def _copy_to_data(src_path, data_dir, slug, copied):
    """ローカルファイルを DATA/<slug><ext> へコピーし 'DATA/...' を返す。

    宛先は常に固定名 ``<slug><ext>``。既存が同一内容なら再利用、
    異なる内容なら上書きする(旧仕様の ``<slug>_N<ext>`` 連番複製は
    エクスポート毎に DATA/ が肥大化するため廃止)。
    """
    src_abs = os.path.abspath(src_path)
    if src_abs in copied:
        return copied[src_abs]
    ext = os.path.splitext(src_abs)[1]
    dest_abs = os.path.join(data_dir, slug + ext)
    same = False
    try:
        same = os.path.samefile(src_abs, dest_abs)
    except Exception:  # nosec B110  # 存在しない場合はコピー対象
        pass
    if not same and not _same_data_copy(src_abs, dest_abs):
        shutil.copy2(src_abs, dest_abs)
    rel = 'DATA/' + os.path.basename(dest_abs)
    copied[src_abs] = rel
    return rel


# DATA/ へ複製するローカルディレクトリツリー(3D Tiles / ローカルXYZタイル)の上限
_LOCAL_TREE_MAX_BYTES = 1024 ** 3  # 1 GiB

# duckdb: 行へ回せる区切りテキストの拡張子(delimitedtext / ogr 共通)
_DUCKDB_TEXT_EXTS = ('.csv', '.tsv')


def _local_path(s):
    """file:///・/C:/ 形式・クエリ/パイプ付きURIからローカルパスを取り出す。"""
    p = urllib.parse.unquote((s or '').split('?')[0].split('|')[0])
    if p.startswith('file://'):
        p = p[7:]
    if re.match(r'^/[A-Za-z]:/', p):
        p = p[1:]
    return p


def _tree_bytes(path, cap):
    """ディレクトリ以下の合計バイト数。cap 超過で打ち切り。"""
    total = 0
    for _root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(_root, fn))
            except OSError:
                pass
            if total > cap:
                return total
    return total


def _copy_tree_to_data(src_dir, data_dir, slug, copied):
    """ローカルディレクトリを DATA/<slug>/ へ複製し 'DATA/<slug>' を返す。

    既存の同名ディレクトリは(前回エクスポート産物として)置き換える。
    """
    src_abs = os.path.abspath(src_dir)
    if src_abs in copied:
        return copied[src_abs]
    dest_abs = os.path.join(data_dir, slug)
    same = False
    try:
        same = os.path.samefile(src_abs, dest_abs)
    except Exception:  # nosec B110  # 存在しない場合はコピー対象
        pass
    if not same:
        if os.path.isdir(dest_abs):
            shutil.rmtree(dest_abs)
        shutil.copytree(src_abs, dest_abs)
    rel = 'DATA/' + slug
    copied[src_abs] = rel
    return rel


def _subset_filter(layer):
    """レイヤのプロバイダフィルタ(subsetString)を where= 値として返す。

    ``|`` を含む式は .kasc 行の区切りと衝突するため None を返す
    (呼び出し側は GeoJSON 再エクスポートでフィルタを反映する)。
    """
    try:
        raw = (layer.subsetString() or '').strip()
    except Exception:  # nosec B110  # 設計上の許容
        return None
    if not raw or '|' in raw:
        return None
    return _kasc_escape(raw) or None


def _has_unusable_subset(layer):
    """subsetString が設定済みだが | を含み where= に変換できないか。"""
    try:
        raw = (layer.subsetString() or '').strip()
    except Exception:  # nosec B110  # 設計上の許容
        return False
    return bool(raw and '|' in raw)


def _csv_geom_hints(path):
    """ローカル CSV/TSV のヘッダ行からジオメトリ列・経度/緯度列を推定する。

    戻り値 (geom_col, lon_col, lat_col)。読めなければ (None,None,None)。
    列名は Canvas 側の自動検出(geometry/geom/wkb/the_geom・lon/lat 慣用名)
    より広く、明示指定に使える名前(wkt/x/y)も拾う。
    """
    try:
        with open(path, 'rb') as f:
            raw = f.read(131072)
    except Exception:  # nosec B110  # 設計上の許容
        return None, None, None
    lines = raw.decode('utf-8-sig', errors='replace').splitlines()
    if not lines:
        return None, None, None
    head = lines[0]
    delim = max((',', ';', '\t', '|'), key=lambda d: head.count(d))
    names = [c.strip().strip('"').strip("'") for c in head.split(delim)]
    lower = {n.lower(): n for n in names if n}
    geom = next((lower[k] for k in
                 ('geometry', 'geom', 'wkt', 'wkb', 'the_geom')
                 if k in lower), None)
    lon = next((lower[k] for k in
                ('lon', 'lng', 'longitude', 'x') if k in lower), None)
    lat = next((lower[k] for k in
                ('lat', 'latitude', 'y') if k in lower), None)
    return geom, lon, lat


def _delimited_params(layer):
    """delimitedtext プロバイダのソースを (パスorURL, クエリparams) に分解。"""
    src = layer.source() or ''
    if '?' in src:
        path, _, qs = src.partition('?')
        params = {k.lower(): v for k, v in
                  urllib.parse.parse_qsl(qs, keep_blank_values=True)}
    else:
        path, params = src, {}
    return path, params


def _is_tiled_scene(layer):
    """QgsTiledSceneLayer(QGIS 3.34+ の 3D Tiles レイヤ)か。"""
    try:
        from qgis.core import QgsTiledSceneLayer
        return isinstance(layer, QgsTiledSceneLayer)
    except Exception:
        # 旧バージョン・独自型はプロバイダ名で判定
        # (QGIS3=tiled_scene / QGIS4=tiledscene・cesiumtiles・esrii3s)
        try:
            return (layer.providerType() or '') in (
                'tiled_scene', 'tiledscene', 'cesiumtiles', 'esrii3s')
        except Exception:  # nosec B110  # 設計上の許容
            return False


def _tiledscene_ref(layer, slug, data_dir, copied, warnings):
    """3D Tiles レイヤの参照先を返す。解決できなければ None。

    - http(s)/vsicurl URL → そのまま参照
    - ローカルの tileset.json(またはそのディレクトリ) → ディレクトリツリーを
      DATA/<slug>/ へ複製して DATA/<slug>/<basename> を返す
    """
    src = layer.source() or ''
    m = re.search(r'(?:^|&)url=([^&]+)', src)
    target = urllib.parse.unquote(m.group(1)) if m else src.strip()
    if not target:
        return None
    if target.startswith('/vsicurl/'):
        target = target[len('/vsicurl/'):]
    if re.match(r'https?://', target):
        # Cesium tileset.json のみ対応(Esri i3s 等の SceneServer URL は除外)
        if target.split('?')[0].lower().endswith('.json'):
            return target
        return None
    path = _local_path(target)
    if os.path.isdir(path):
        base_dir, ts_path = path, os.path.join(path, 'tileset.json')
    else:
        base_dir, ts_path = os.path.dirname(path) or path, path
    if not os.path.isfile(ts_path):
        return None
    if _tree_bytes(base_dir, _LOCAL_TREE_MAX_BYTES) > _LOCAL_TREE_MAX_BYTES:
        warnings.append(
            '{0}: 3dtiles ディレクトリが {1} 超のため複製を中止'.format(
                layer.name(), _LOCAL_TREE_MAX_BYTES))
        return None
    _copy_tree_to_data(base_dir, data_dir, slug, copied)
    return 'DATA/{0}/{1}'.format(slug, os.path.basename(ts_path))


def _local_xyz_template(url, slug, data_dir, copied, warnings):
    """ローカル XYZ テンプレート(file:///.../{z}/{x}/{y}.png)を DATA/ へ複製。

    戻り値 'DATA/<slug>/{z}/{x}/{y}.png' 形式の参照テンプレート。解決不可・
    サイズ超過時は None。
    """
    path = _local_path(url)
    if '{z}' not in path:
        return None
    base, _, rest = path.partition('{z}')
    base_dir = base.rstrip('/\\')
    template = '{z}' + rest
    if not os.path.isdir(base_dir):
        return None
    if _tree_bytes(base_dir, _LOCAL_TREE_MAX_BYTES) > _LOCAL_TREE_MAX_BYTES:
        warnings.append(
            '{0}: ローカルタイルツリーが {1} 超のため複製を中止'.format(
                slug, _LOCAL_TREE_MAX_BYTES))
        return None
    _copy_tree_to_data(base_dir, data_dir, slug, copied)
    return 'DATA/{0}/{1}'.format(slug, template.replace(os.sep, '/'))


def _maplayer_opacity(layer):
    """レイヤ不透明度(0-1)。1.0 または取得不可なら None。"""
    try:
        op = float(layer.opacity())
        return op if 0.0 <= op < 0.999 else None
    except Exception:  # nosec B110  # 設計上の許容
        return None


# QPainter::CompositionMode の値 → 名前(警告表示用)。
# 0=SourceOver(通常)以外は Canvas で再現できない
_BLEND_MODE_NAMES = {
    0: 'SourceOver', 1: 'DestinationOver', 2: 'Clear', 3: 'Source',
    4: 'Destination', 5: 'SourceIn', 6: 'DestinationIn', 7: 'SourceOut',
    8: 'DestinationOut', 9: 'SourceAtop', 10: 'DestinationAtop',
    11: 'Xor', 12: 'Plus', 13: 'Multiply', 14: 'Screen', 15: 'Overlay',
    16: 'Darken', 17: 'Lighten', 18: 'ColorDodge', 19: 'ColorBurn',
    20: 'HardLight', 21: 'SoftLight', 22: 'Difference', 23: 'Exclusion',
}

# ベクターレンダラ種別 → Canvas 側オプション。
# ヒートマップ/クラスタは QML スタイル変換ではなく .kasc の
# heat=on/cluster=on へマッピングする(Canvas 側の専用描画機構を使う)
_RENDERER_OPT_MAP = {
    'heatmaprenderer': {'heat': 'on'},
    'pointcluster': {'cluster': 'on'},
    'pointdisplacement': {'cluster': 'on'},
}

# Canvas で再現できないレンダラ種別 → 警告用の説明
_UNSUPPORTED_RENDERER_NAMES = {
    'invertedpolygonrenderer': '反転ポリゴン',
    '25drenderer': '2.5D',
    'embeddedsymbol': '埋め込みシンボル',
    'mergedfeaturerenderer': '結合地物',
    'nullsymbol': 'null シンボル(地物非表示)',
    'interpolated': '補間',
    'geometrygenerator': 'ジオメトリジェネレータ',
}


def _blend_warning(layer, warnings):
    """レイヤ/地物ブレンドモードが非標準なら警告を出す。

    QGIS の multiply/screen/overlay 等は Canvas 側で再現できないため
    (概ね通常描画になる)、ユーザーが認識できるよう warnings へ記録する。
    """
    for meth, label in (('blendMode', 'ブレンドモード'),
                        ('featureBlendMode', '地物ブレンドモード')):
        try:
            fn = getattr(layer, meth, None)
            if fn is None:
                continue
            bm = fn()
            val = int(bm.value if hasattr(bm, 'value') else bm)
        except Exception:  # nosec B112  # 設計上の許容
            continue
        if val and val != 0:
            warnings.append('{0}: {1} {2} は未対応(近似描画)'.format(
                layer.name(), label,
                _BLEND_MODE_NAMES.get(val, str(val))))


def _temporal_opts(layer, warnings):
    """時間対応(temporal)設定 → ``time=``/``time_end=``/``time_span=``。

    QgsVectorLayerTemporalProperties の mode 別に変換する:
    - InstantFromField        → time=<開始フィールド>
    - StartAndEndFromFields   → time=<開始> + time_end=<終了>
    - StartAndDurationFromFields → time=<開始>(期間フィールドは未対応→警告)
    - FromExpressions / FixedRange / RedrawOnly → 変換不能(警告 or 無視)
    """
    opts = {}
    try:
        tp = layer.temporalProperties()
    except Exception:  # nosec B110  # 設計上の許容
        return opts
    try:
        if not tp or not tp.isActive():
            return opts
        from qgis.core import QgsVectorLayerTemporalProperties as _T
        mode = tp.mode()
        if mode == _T.ModeFeatureDateTimeInstantFromField:
            if tp.startField():
                opts['time'] = tp.startField()
            else:
                warnings.append(
                    '{0}: 時間フィールド未設定'.format(layer.name()))
        elif mode == _T.ModeFeatureDateTimeStartAndEndFromFields:
            if tp.startField():
                opts['time'] = tp.startField()
            if tp.endField():
                opts['time_end'] = tp.endField()
            if not opts:
                warnings.append(
                    '{0}: 時間フィールド未設定'.format(layer.name()))
        elif mode == getattr(
                _T, 'ModeFeatureDateTimeStartAndDurationFromFields',
                object()):
            if tp.startField():
                opts['time'] = tp.startField()
            warnings.append(
                '{0}: 地物ごとの期間(durationField)は未対応'.format(
                    layer.name()))
        elif mode == getattr(
                _T, 'ModeFeatureDateTimeStartAndEndFromExpressions',
                object()):
            warnings.append(
                '{0}: 式ベースの時間設定は未対応'.format(layer.name()))
        elif mode == _T.ModeFixedTemporalRange:
            warnings.append(
                '{0}: 固定時間範囲はタイムスライダーへ変換不可'.format(
                    layer.name()))
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return opts


def _renderer_opts(layer, warnings):
    """ベクターレンダラ種別 → Canvas オプション(heat=/cluster=)。

    変換不能なレンダラ(反転ポリゴン/2.5D/ジオメトリジェネレータ等)は
    「最も近い表現へのフォールバック」となるため warnings に記録する。
    """
    opts = {}
    try:
        r = layer.renderer()
        rtype = (r.type() or '').strip().lower() if r else ''
    except Exception:  # nosec B110  # 設計上の許容
        return opts
    if rtype in _RENDERER_OPT_MAP:
        opts.update(_RENDERER_OPT_MAP[rtype])
    elif rtype in _UNSUPPORTED_RENDERER_NAMES:
        warnings.append('{0}: {1}レンダラは未対応(近似描画)'.format(
            layer.name(), _UNSUPPORTED_RENDERER_NAMES[rtype]))
    # シンボルレイヤ単位の未対応要素(ジオメトリジェネレータ)を拾う
    try:
        syms = []
        if r and hasattr(r, 'symbol'):
            s = r.symbol()
            if s is not None:
                syms = [s]
        if not syms and r and hasattr(r, 'symbols'):
            try:
                from qgis.core import QgsRenderContext
                syms = list(r.symbols(QgsRenderContext()) or [])
            except Exception:  # nosec B110  # 設計上の許容
                syms = []
        for s in syms:
            if s is None:
                continue
            try:
                for i in range(s.symbolLayerCount()):
                    lt = (s.symbolLayer(i).layerType() or '').strip()
                    if lt == 'GeometryGenerator':
                        warnings.append(
                            '{0}: ジオメトリジェネレータは未対応'
                            '(近似描画)'.format(layer.name()))
                        raise StopIteration
            except StopIteration:
                break
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return opts


def _layer_3d_opts(layer, warnings):
    """ベクターの3Dレンダラ(立ち上げ) → ``extrude=<m>``/``z=<m>``(#60)。

    QgsVectorLayer3DRenderer のシンボル(ポリゴン/ライン)が持つ
    extrusionHeight(立ち上げ高さ)と height(基準高さオフセット)を
    Canvas の extrudedHeight/height へ橋渡しする。renderer3D を持たない
    レイヤ・シンボル無し・読み取り失敗時は空dict。2.5D(2D側)レンダラは
    _renderer_opts 側の warnings 対象のままとする。
    """
    opts = {}
    try:
        r3d = layer.renderer3D()
        sym = r3d.symbol() if r3d is not None else None
    except Exception:  # nosec B110  # 設計上の許容
        return opts
    if sym is None:
        return opts
    try:
        ext = float(sym.extrusionHeight())
        if ext > 0:
            opts['extrude'] = '{0:g}'.format(ext)
    except Exception:  # nosec B110  # 設計上の許容
        pass
    try:
        h = float(sym.height())
        if h:
            opts['z'] = '{0:g}'.format(h)
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return opts


def _vector_opts_suffix(layer, warnings):
    """ベクター行(geojson:/gpkg: 等)共通の追加オプション文字列を返す。

    - 時間対応 → `` | time=<f>``/`` | time_end=<f>``/`` | time_span=<s>``
    - レンダラ種別 → `` | heat=on``/`` | cluster=on``
    - 3Dレンダラ立ち上げ → `` | extrude=<m>``/`` | z=<m>``
    - レイヤ不透明度 → `` | opacity=<0-1>``
    """
    opts = {}
    opts.update(_temporal_opts(layer, warnings))
    opts.update(_renderer_opts(layer, warnings))
    opts.update(_layer_3d_opts(layer, warnings))
    _blend_warning(layer, warnings)
    op = _maplayer_opacity(layer)
    if op is not None:
        opts['opacity'] = '{0:g}'.format(op)
    out = ''
    for key, val in opts.items():
        out += ' | {0}={1}'.format(key, _kasc_escape(val))
    return out


def _scale_vis_opt(layer):
    """QGIS の縮尺表示設定を `` | minScale= | maxScale=`` オプションにする。

    QgsMapLayer::minimumScale() は引き側限界(分母が大きい方)、
    maximumScale() は寄り側限界(分母が小さい方・0 は無制限)。
    Canvas 側は minScale → ズーム下限、maxScale → ズーム上限として
    解釈する(QGIS と同じ命名方向)。未設定時は空文字。
    """
    try:
        if not layer.hasScaleBasedVisibility():
            return ''
        lo = float(layer.minimumScale() or 0)
        hi = float(layer.maximumScale() or 0)
    except Exception:
        return ''
    out = ''
    if lo > 0:
        out += ' | minScale={0:g}'.format(lo)
    if hi > 0:
        out += ' | maxScale={0:g}'.format(hi)
    return out


def _layer_extent_bbox(layer):
    """レイヤ範囲を EPSG:4326 の 'w,s,e,n' 文字列に。全域相当/失敗時 None。"""
    try:
        from qgis.core import (QgsCoordinateReferenceSystem,
                               QgsCoordinateTransform, QgsProject)
        ext = layer.extent()
        if not ext or not ext.isFinite() or ext.isEmpty():
            return None
        crs = layer.crs()
        if crs and crs.isValid() and crs.authid() != 'EPSG:4326':
            tr = QgsCoordinateTransform(
                crs, QgsCoordinateReferenceSystem('EPSG:4326'),
                QgsProject.instance())
            ext = tr.transform(ext)
        w, s, e, n = (ext.xMinimum(), ext.yMinimum(),
                      ext.xMaximum(), ext.yMaximum())
        if e - w >= 350.0 or n - s >= 170.0:
            return None
        return '{0:.6f},{1:.6f},{2:.6f},{3:.6f}'.format(w, s, e, n)
    except Exception:
        return None


# skipped 記録用の種別名 → ユーザー向け理由(#50)。
# 対象外レイヤ種別をサイレントに捨てないよう、理由を明示する
_SKIP_REASON_BY_CLASS = {
    'QgsMeshLayer': 'メッシュレイヤ(未対応)',
    'QgsVectorTileLayer': 'ベクタータイル(ローカル/URL参照不可)',
    'QgsPointCloudLayer': '点群レイヤ(未対応)',
    'QgsAnnotationLayer': 'アノテーションレイヤ(未対応)',
    'QgsPluginLayer': 'プラグインレイヤ(未対応)',
    'QgsGroupLayer': 'グループレイヤ(未対応)',
}


def _skip_reason(layer):
    """skipped 記録用の種別文字列(クラス名+プロバイダ、既知種別は和訳)。"""
    cls_name = type(layer).__name__
    if cls_name in _SKIP_REASON_BY_CLASS:
        return _SKIP_REASON_BY_CLASS[cls_name]
    prov = ''
    try:
        prov = layer.providerType() or ''
    except Exception:  # nosec B110  # 設計上の許容
        pass
    cls = cls_name.replace('Qgs', '')
    return '{0}({1})'.format(cls, prov) if prov else cls


def _vectortile_source(layer):
    """QgsVectorTileLayer のプロバイダ接続文字列を解析し、Canvas の
    mvt:/pmtiles: 行へ引き渡せるタイルソースを返す(#50)。
    戻り値 {'kind','url','zmin','zmax'}。URL参照できない
    (ローカル .mbtiles 等)場合は None → 呼び出し側は skipped へ回す。"""
    try:
        from qgis.core import QgsVectorTileLayer
        if not isinstance(layer, QgsVectorTileLayer):
            return None
    except Exception:  # nosec B110  # 設計上の許容
        return None
    try:
        from urllib.parse import unquote
        src = layer.source() or ''
    except Exception:  # nosec B110  # 設計上の許容
        return None
    # vectortile プロバイダの接続文字列は type=xyz&url=...&zmin=..&zmax=.. 形式
    params = {}
    for part in src.split('&'):
        k, _, v = part.partition('=')
        if k:
            params[k.strip().lower()] = unquote(v.strip())
    url = params.get('url') or ''
    if not url or not re.match(r'https?://', url):
        return None  # ローカル .mbtiles・file:// 等は DATA 複製せず未対応

    def _zi(key):
        try:
            return int(params[key]) if params.get(key) else None
        except Exception:  # nosec B110  # 設計上の許容
            return None
    zmin, zmax = _zi('zmin'), _zi('zmax')
    if url.lower().endswith('.pmtiles') or params.get('type') == 'pmtiles':
        return {'kind': 'pmtiles', 'url': url, 'zmin': zmin, 'zmax': zmax}
    if '{z}' in url and '{x}' in url and '{y}' in url:
        return {'kind': 'mvt', 'url': url, 'zmin': zmin, 'zmax': zmax}
    if url.lower().endswith('.json'):
        # TileJSON: Canvas 側が tiles[] を解決する
        return {'kind': 'mvt', 'url': url, 'zmin': zmin, 'zmax': zmax}
    return None


def _legend_node_line(node, title):
    """QgsLayerTreeLayer の legend カスタムプロパティ → legendnode: 行(#63)。
    凡例ノード順(legendNodeOrder)・ユーザーラベル(legendNodeUserLabel)・
    凡例表示名(legend/title-label)が既定と異なる場合のみ行を返す。"""
    try:
        from qgis.core import QgsMapLayerLegendUtils
        order = list(QgsMapLayerLegendUtils.legendNodeOrder(node) or [])
        labels = {}
        for i in order:
            lbl = QgsMapLayerLegendUtils.legendNodeUserLabel(node, i)
            if lbl:
                labels[i] = lbl
        try:
            title_label = node.customProperty('legend/title-label') or ''
        except Exception:  # nosec B110  # 設計上の許容
            title_label = ''
        custom_order = bool(order) and any(
            i != o for o, i in enumerate(order))
        if not custom_order and not labels and not title_label:
            return None
        line = 'legendnode: {0}'.format(_kasc_escape(title))
        if custom_order:
            line += ' | order={0}'.format(
                ','.join(str(i) for i in order))
        for i in sorted(labels):
            line += ' | label{0}={1}'.format(i, _kasc_escape(labels[i]))
        if title_label:
            line += ' | title={0}'.format(_kasc_escape(title_label))
        return line
    except Exception:  # nosec B110  # 設計上の許容
        return None


def _duckdb_target_ref(target, slug, data_dir, copied):
    """duckdb: 参照用に target(URL or ローカルパス)を ref へ変換する。"""
    if re.match(r'https?://', target):
        return target
    path = _local_path(target)
    if not path or not os.path.exists(path):
        return None
    return _copy_to_data(path, data_dir, slug, copied)


# geotiff: 行へ回せるラスタファイルの拡張子(GeoTIFF/COG)
_GEOTIFF_EXTS = ('.tif', '.tiff', '.gtif', '.gtiff')


def _geotiff_layer_ref(layer, slug, data_dir, copied):
    """QgsRasterLayer のソースが GeoTIFF/COG なら参照を返す。

    - http(s)/vsicurl の .tif 系 → URL をそのまま参照(COG 前提)
    - ローカルの .tif 系 → DATA/ へコピーして相対参照
    それ以外のラスタ(WMS/仮想等)やファイル不在は None。
    """
    try:
        from qgis.core import QgsRasterLayer
        if not isinstance(layer, QgsRasterLayer):
            return None
    except Exception:  # nosec B110  # 設計上の許容
        return None
    if (layer.providerType() or '').lower() != 'gdal':
        return None
    src = layer.source() or ''
    url = src.replace('/vsicurl/', '')
    if re.match(r'https?://', url):
        low = url.split('?')[0].lower()
        return url if low.endswith(_GEOTIFF_EXTS) else None
    path = _local_path(src)
    if not path or not path.lower().endswith(_GEOTIFF_EXTS):
        return None
    if not os.path.exists(path):
        return None
    return _copy_to_data(path, data_dir, slug, copied)


def _native_ref(layer, slug, data_dir, copied, warnings, embed_style=False):
    """Canvas が直接参照できるソースなら参照辞書を返す。

    戻り値: ``{'type': <kasc行タイプ>, 'ref': <参照>, 'opts': {k: v}}``、
    または ``{'skip_reason': <理由>}``(表示不能と確定)、不可時は None
    (呼び出し側で GeoJSON 再エクスポートに回す)。

    - http(s) ソース: 拡張子に応じて URL をそのまま参照
    - ローカルファイル: DATA/<slug><ext> へコピーして相対参照
    - delimitedtext / .csv,.tsv → ``duckdb:``(lon=/lat=/geom= 付き)
    - subsetString → gpkg は ``where=``、parquet は ``duckdb:+format=parquet``
      へ切替、GeoJSON/FGB はフィルタ反映のため GeoJSON 変換へ回す
    地理座標系でない場合は None(GeoJSON 再エクスポートへ回す)。

    embed_style=True ならローカル GPKG の layer_styles へ現在スタイルを
    保存してから DATA/ へコピーする(配布コピーにスタイルを含めるため、
    コピー前の埋め込みが必須)。
    """
    src = layer.source() or ''
    subset = _subset_filter(layer)

    # delimitedtext プロバイダ(CSV/TSV等) → duckdb:
    if (layer.providerType() or '') == 'delimitedtext':
        path, params = _delimited_params(layer)
        geom = params.get('wktfield') or None
        lon = params.get('xfield') or None
        lat = params.get('yfield') or None
        if not geom and not (lon and lat):
            return {'skip_reason': 'ジオメトリ列なし(属性テーブル)'}
        if not _geo_equiv_crs(layer):
            return None  # 再投影が必要 → GeoJSON 変換
        ref = _duckdb_target_ref(path, slug, data_dir, copied)
        if not ref:
            return None
        opts = {'format': 'tsv' if path.lower().endswith('.tsv') else 'csv'}
        if geom:
            opts['geom'] = geom
        else:
            opts['lon'] = lon
            opts['lat'] = lat
        if subset:
            opts['where'] = subset
        return {'type': 'duckdb', 'ref': ref, 'opts': opts}

    # http(s)/vsicurl ソース → 拡張子で行タイプ決定
    if re.match(r'https?://', src) or src.startswith('/vsicurl/'):
        url = src.replace('/vsicurl/', '')
        low = url.split('?')[0].lower()
        kind, ext = None, None
        for e, k in (('.gpkg', 'gpkg'), ('.geojson', 'geojson'),
                     ('.json', 'geojson'), ('.parquet', 'geoparquet'),
                     ('.fgb', 'flatgeobuf'),
                     ('.csv', 'duckdb'), ('.tsv', 'duckdb')):
            if low.endswith(e):
                kind, ext = k, e
                break
        if not kind:
            return None
        opts = {}
        if kind == 'duckdb':
            opts['format'] = 'tsv' if ext == '.tsv' else 'csv'
        if subset:
            if kind in ('gpkg', 'duckdb'):
                opts['where'] = subset
            elif kind == 'geoparquet':
                kind = 'duckdb'
                opts['format'] = 'parquet'
                opts['where'] = subset
            else:
                # geojson:/flatgeobuf: に where= は無い → GeoJSON 変換で反映
                return None
        return {'type': kind, 'ref': url, 'opts': opts}

    # ローカルファイルソース
    src_path = _source_path(layer)
    if not src_path:
        return None
    ext = os.path.splitext(src_path)[1].lower()

    # ogr の区切りテキスト → duckdb:(ヘッダからジオメトリ/経緯度列を推定。
    # ogr CSV は CRS 情報を持たないため値はそのまま=再投影なし)
    if ext in _DUCKDB_TEXT_EXTS:
        geom, lon, lat = _csv_geom_hints(src_path)
        if not geom and not (lon and lat):
            return None
        opts = {'format': 'tsv' if ext == '.tsv' else 'csv'}
        if geom:
            opts['geom'] = geom
        else:
            opts['lon'] = lon
            opts['lat'] = lat
        if subset:
            opts['where'] = subset
        return {'type': 'duckdb',
                'ref': _copy_to_data(src_path, data_dir, slug, copied),
                'opts': opts}

    kinds = {'.gpkg': 'gpkg', '.geojson': 'geojson', '.json': 'geojson',
             '.parquet': 'geoparquet', '.fgb': 'flatgeobuf'}
    kind = kinds.get(ext)
    if not kind:
        return None
    # GeoJSON は仕様上 lon/lat のため CRS 不明でも同等扱いとする
    geojson_spec = ext in ('.geojson', '.json')
    if not geojson_spec and not _geo_equiv_crs(layer):
        return None
    if subset:
        if kind == 'geoparquet':
            kind = 'duckdb'
        elif kind != 'gpkg':
            # geojson/flatgeobuf は where= 非対応 → GeoJSON 変換で反映
            return None
    if kind == 'gpkg' and embed_style:
        # コピー後に埋め込むと配布コピー(DATA/)へスタイルが入らないため、
        # 必ず元 GPKG への保存 → コピーの順に行う
        if _embed_gpkg_style(layer):
            warnings.append(
                '{0}: layer_styles に既定スタイルを保存'.format(layer.name()))
            prev = copied.get(os.path.abspath(src_path))
            if prev:
                # 同一 GPKG の別レイヤで既に DATA/ へコピー済み → 参照名を
                # 変えずに同じ宛先へ上書き再コピーし、全レイヤ分の
                # layer_styles を配布コピーへ反映する
                shutil.copy2(src_path,
                             os.path.join(data_dir,
                                          os.path.basename(prev)))
        else:
            warnings.append(
                '{0}: layer_styles への保存に失敗'.format(layer.name()))
    ref = _copy_to_data(src_path, data_dir, slug, copied)
    opts = {}
    if kind == 'duckdb':
        opts['format'] = 'parquet'
    if kind == 'gpkg':
        m = re.search(r'layername=([^|&]+)', src)
        if m:
            opts['table'] = urllib.parse.unquote(m.group(1))
    if subset:
        opts['where'] = subset
    return {'type': kind, 'ref': ref, 'opts': opts}


def _embed_gpkg_style(layer):
    """GPKG の layer_styles へ既定スタイルを保存する(QGIS 標準機能)。

    データ+スタイルを1ファイルで配布できる。元ファイルに書き込む点に注意。
    saveStyleToDatabase はエラーメッセージ文字列を返す(空=成功。
    QGIS 4.0 実測)。
    """
    try:
        res = layer.saveStyleToDatabase(
            'kasugai', 'KASUGAI Canvas 既定スタイル', True, '')
        return not res
    except Exception:  # プロバイダ未対応等 → 呼び出し側で警告
        return False


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


# .qml 内で画像ファイルを参照するシンボルレイヤ。
# キーは class 属性値(小文字)、値はファイル参照を持つ prop 名(小文字)。
# QGIS 内蔵シンボルは transport/… 等の相対名や QGIS インストール先の
# 絶対パスのまま書き出され、DATA/ に実体が無いと Canvas 側は解決
# できない(円・単色へフォールバック)ため、複製して参照を書き換える
_QML_ASSET_KEYS = {
    'svgmarker': ('name', 'path'),
    'rastermarker': ('imagefile', 'file', 'path'),
    'svgfill': ('svgfile', 'file'),
    'rasterfill': ('imagefile', 'file'),
    'imagefill': ('imagefile', 'file'),
}

# ローカルファイル化できない参照(file: スキームは _local_path で処理する)
_REMOTE_ASSET_RE = re.compile(
    r'^(?:https?|data|base64|url|blob)[:;]', re.IGNORECASE)


def _qml_asset_props(layer_el, keys):
    """<layer> 要素内のファイル参照 prop を (element, value_attr) で yield。

    QGIS 3.28+/4 の ``<Option type="Map"><Option name= value=>`` 形式と
    旧形式 ``<prop k= v=>`` の両方に対応する。
    """
    keys = set(keys)
    for child in layer_el:
        if child.tag == 'Option':
            if (child.get('type') or '').strip().lower() == 'map':
                for opt in child:
                    if (opt.tag == 'Option' and
                            (opt.get('name') or '').strip().lower() in keys):
                        yield opt, 'value'
            elif (child.get('name') or '').strip().lower() in keys:
                yield child, 'value'
        elif (child.tag == 'prop' and
                (child.get('k') or '').strip().lower() in keys):
            yield child, 'v'


def _qgis_svg_search_paths():
    """QGIS の SVG 検索ディレクトリ一覧(内蔵+ユーザー登録)。"""
    from qgis.core import QgsApplication
    return [p for p in (QgsApplication.svgPaths() or []) if p]


def _resolve_svg_file(name):
    """SVG 参照名を実ファイルの絶対パスへ解決する。失敗時 None。

    svgSymbolNameToPath(name, resolver) が SVG 検索パス
    (内蔵+ユーザー登録)を探し、未解決時は入力名をそのまま返す
    (QGIS 4.0 実測)ため、isfile で実在を確定させる。
    """
    from qgis.core import QgsPathResolver, QgsSymbolLayerUtils
    full = QgsSymbolLayerUtils.svgSymbolNameToPath(name, QgsPathResolver())
    if full and os.path.isfile(full):
        return os.path.abspath(full)
    return None


def _resolve_asset_file(value, qml_dir, svg_dirs):
    """シンボルの画像参照値をローカルの実ファイルへ解決する。

    絶対パスはそのまま、相対名はプロジェクト dir → qml dir →
    SVG 検索パスの順で探す。見つからなければ None。
    """
    from qgis.core import QgsProject
    v = urllib.parse.unquote(str(value or '').strip())
    if not v:
        return None
    p = _local_path(v)
    if os.path.isabs(p):
        return os.path.abspath(p) if os.path.isfile(p) else None
    dirs = []
    proj_dir = QgsProject.instance().absolutePath()
    if proj_dir:
        dirs.append(proj_dir)
    dirs.append(qml_dir)
    dirs.extend(svg_dirs or [])
    for base in dirs:
        cand = os.path.normpath(os.path.join(base, p))
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    return _resolve_svg_file(p)


def _export_qml_assets(qml_path, layer_slug, data_dir, used_names, copied,
                       warnings):
    """.qml が参照するシンボル画像(SVG/ラスタ)を DATA/ へ複製し参照を書き換える。

    QGIS 内蔵 SVG シンボルやユーザーのローカル画像は .qml に
    生パスのまま残り、Canvas 側は .qml のある DATA/ からしか解決
    できない。ここで参照ファイルを DATA/ へ複製し、.qml の値を
    DATA/ 内のファイル名へ書き換える。
    戻り値: 複製したファイル数。
    """
    # defusedxml を vendored 同梱し利用(実体宣言/外部参照をパーサ層で拒否)
    try:
        from .defusedxml import ElementTree as ET
    except ImportError:
        # スタンドアロン実行時(プラグインディレクトリを sys.path に追加)用
        from defusedxml import ElementTree as ET
    with open(qml_path, 'r', encoding='utf-8') as f:
        raw_text = f.read()
    m = re.search(r'<!DOCTYPE[^>]*>', raw_text)
    doctype = m.group(0) if m else ''
    root = ET.fromstring(raw_text)
    qml_dir = os.path.dirname(qml_path)
    svg_dirs = None
    count = 0
    changed = False
    for layer_el in root.iter('layer'):
        keys = _QML_ASSET_KEYS.get(
            (layer_el.get('class') or '').strip().lower())
        if not keys:
            continue
        for el, attr in _qml_asset_props(layer_el, keys):
            raw = (el.get(attr) or '').strip()
            if not raw or _REMOTE_ASSET_RE.match(raw):
                continue
            if svg_dirs is None:
                svg_dirs = _qgis_svg_search_paths()
            src = _resolve_asset_file(raw, qml_dir, svg_dirs)
            if not src:
                warnings.append(
                    '{0}: シンボル画像が見つかりません: {1}'.format(
                        os.path.basename(qml_path), raw))
                continue
            slug = _slugify('{0}_{1}'.format(
                layer_slug,
                os.path.splitext(os.path.basename(src))[0]), used_names)
            rel = _copy_to_data(src, data_dir, slug, copied)
            el.set(attr, os.path.basename(rel))
            changed = True
            count += 1
    if changed:
        body = ET.tostring(root, encoding='unicode')
        with open(qml_path, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            if doctype:
                f.write(doctype + '\n')
            f.write(body)
    return count


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


def _wms_layer_info(layer):
    """QGIS の WMS ラスタレイヤ(type=xyz 以外)なら
    (base_url, layers_csv, styles_csv, format, version) を返す。

    source URI は ``key=value&key=value`` 形式で、layers=/styles= は
    繰り返し出る(レイヤ順を保持)。値はパーセントエンコード済み。
    ``wms:`` 行は GetMap を 256px タイルへ分解して参照するため、
    エンドポイントURLは生で渡し、レイヤ指定はオプションとして出す。
    """
    try:
        if layer.providerType() not in ('wms',):
            return None
        src = layer.source() or ''
        if 'type=xyz' in src or 'type%3Dxyz' in src.lower():
            return None
        params = {}
        lists = {}
        for part in src.split('&'):
            if '=' not in part:
                continue
            key, val = part.split('=', 1)
            key = key.strip().lower()
            val = urllib.parse.unquote(val.strip())
            if key in ('layers', 'styles'):
                lists.setdefault(key, []).append(val)
            else:
                params[key] = val
        url = params.get('url')
        if not url or not re.match(r'https?://', url):
            return None
        return (url,
                ','.join(lists.get('layers', [])),
                ','.join(lists.get('styles', [])),
                params.get('format') or '',
                params.get('version') or '')
    except Exception:
        return None


def _wmts_layer_info(layer):
    """QGIS の WMTS ラスタレイヤなら
    (url, layers_csv, styles_csv, tilematrixset, format, tilesize) を返す。

    WMS(GetMap) と違い、tileMatrixSet を持つソースは ``wmts:`` 行へ
    出力する(Canvas 側が KVP GetTile または RESTful テンプレートへ展開)。
    """
    try:
        if layer.providerType() not in ('wms',):
            return None
        src = layer.source() or ''
        if 'type=xyz' in src or 'type%3Dxyz' in src.lower():
            return None
        params = {}
        lists = {}
        for part in src.split('&'):
            if '=' not in part:
                continue
            key, val = part.split('=', 1)
            key = key.strip().lower()
            val = urllib.parse.unquote(val.strip())
            if key in ('layers', 'styles'):
                lists.setdefault(key, []).append(val)
            else:
                params[key] = val
        tms = params.get('tilematrixset')
        if not tms:
            return None
        url = params.get('url')
        if not url or not re.match(r'https?://', url):
            return None
        try:
            tilesize = int(params.get('tiledimensions') or 0) or None
        except Exception:  # nosec B110  # 設計上の許容
            tilesize = None
        return (url,
                ','.join(lists.get('layers', [])),
                ','.join(lists.get('styles', [])),
                tms, params.get('format') or '', tilesize)
    except Exception:
        return None


# 焼き付け PNG(レンダラ再現フォールバック)の長辺上限
_RASTER_BAKE_MAX_PX = 4096


def _raster_needs_bake(layer):
    """再現に「QGIS で描画済み PNG への焼き付け」が必要なラスタか。

    - multibandcolor: ``bands=`` で表現できるため対象外
    - singlebandgray: コントラスト強調(ストレッチ)ありなら焼き付け
    - paletted: パレット色は geotiff 参照で再現されないため焼き付け
    - それ以外(疑似カラー/ヒルシェード/等高線/未知のレンダラ): 焼き付け
    """
    try:
        r = layer.renderer()
        rtype = (r.type() or '').strip().lower() if r else ''
        if rtype in ('multibandcolor', ''):
            return False
        if rtype == 'singlebandgray':
            try:
                ce = r.contrastEnhancement()
                return (ce is not None and
                        int(ce.contrastEnhancementAlgorithm()) != 0)
            except Exception:  # nosec B110  # 設計上の許容
                return False
        return True
    except Exception:  # nosec B110  # 設計上の許容
        return False


def _raster_bands_opt(layer):
    """multibandcolor レンダラの band 選択 → 'r,g,b'。標準(1,2,3)なら None。"""
    try:
        r = layer.renderer()
        if not r or (r.type() or '').strip().lower() != 'multibandcolor':
            return None
        bands = [r.redBand(), r.greenBand(), r.blueBand()]
        if min(bands) < 1 or bands == [1, 2, 3]:
            return None
        return ','.join(str(b) for b in bands)
    except Exception:  # nosec B110  # 設計上の許容
        return None


def _render_raster_png(layer, png_path, warnings):
    """ラスタレイヤを現在の表示状態のまま PNG(透過)へ焼き付ける。

    レンダラ(疑似カラー・ヒルシェード・ストレッチ・パレット)・
    ブレンド・描画効果を含めて QGIS の見た目をそのまま保存し、
    ``image:`` 行で参照できるようにする。戻り値は EPSG:4326 の
    'w,s,e,n' bbox 文字列、失敗時 None。
    """
    try:
        from qgis.core import (QgsMapRendererSequentialJob,
                               QgsMapSettings)
        from qgis.PyQt.QtCore import QSize
        from qgis.PyQt.QtGui import QColor
        ext = layer.extent()
        if not ext or not ext.isFinite() or ext.isEmpty():
            return None
        w_px = int(layer.width() or 0)
        h_px = int(layer.height() or 0)
        if w_px <= 0 or h_px <= 0:
            w_px, h_px = 1024, 1024
        scale = _RASTER_BAKE_MAX_PX / float(max(w_px, h_px))
        if scale < 1.0:
            w_px = max(1, int(w_px * scale))
            h_px = max(1, int(h_px * scale))
            warnings.append('{0}: 焼き付けPNGを {1}px 以内へ縮小'.format(
                layer.name(), _RASTER_BAKE_MAX_PX))
        settings = QgsMapSettings()
        settings.setLayers([layer])
        crs = layer.crs()
        if crs and crs.isValid():
            settings.setDestinationCrs(crs)
        settings.setExtent(ext)
        settings.setOutputSize(QSize(w_px, h_px))
        settings.setBackgroundColor(QColor(0, 0, 0, 0))
        job = QgsMapRendererSequentialJob(settings)
        job.start()
        job.waitForFinished()
        img = job.renderedImage()
        if img.isNull() or not img.save(png_path, 'PNG'):
            return None
        return _raster_bbox_str(layer)
    except Exception as e:
        warnings.append('{0}: ラスタ焼き付け失敗: {1}'.format(
            layer.name(), e))
        return None


def _raster_bbox_str(layer):
    """レイヤ範囲の EPSG:4326 'w,s,e,n' 文字列(焼き付けPNGのbboxと同値)。

    差分エクスポートで既存PNGを再利用する際に bbox= を再計算せずに
    復元するために使う(描画は行わない)。
    """
    try:
        from qgis.core import (QgsCoordinateReferenceSystem,
                               QgsCoordinateTransform, QgsProject)
        ext = layer.extent()
        if not ext or not ext.isFinite() or ext.isEmpty():
            return None
        crs = layer.crs()
        if crs and crs.isValid() and crs.authid() != 'EPSG:4326':
            tr = QgsCoordinateTransform(
                crs, QgsCoordinateReferenceSystem('EPSG:4326'),
                QgsProject.instance())
            ext = tr.transformBoundingBox(ext)
        return '{0:.6f},{1:.6f},{2:.6f},{3:.6f}'.format(
            ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum())
    except Exception:  # nosec B110  # 設計上の許容
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


def _project_xml_root(project):
    """プロジェクトファイル(.qgs/.qgz)を ElementTree root で返す。"""
    fname = project.fileName() or ''
    if not fname or not os.path.exists(fname):
        return None
    try:
        if fname.lower().endswith('.qgz'):
            import zipfile
            with zipfile.ZipFile(fname) as zf:
                names = [n for n in zf.namelist()
                         if n.lower().endswith('.qgs')]
                if not names:
                    return None
                data = zf.read(names[0])
        else:
            with open(fname, 'rb') as f:
                data = f.read()
        try:
            from .defusedxml import ElementTree as ET
        except ImportError:
            from defusedxml import ElementTree as ET
        return ET.fromstring(data)
    except Exception:  # nosec B110  # 設計上の許容
        return None


def _qgis3d_color_hex(value):
    """QGIS 色文字列 'r,g,b,a,rgb:…' / '#rrggbb' → '#RRGGBB'(失敗時 None)。"""
    if not value:
        return None
    value = str(value).strip()
    if value.startswith('#'):
        return value[:7]
    try:
        parts = [int(float(p.strip())) for p in value.split(',')[:3]]
        if len(parts) == 3 and all(0 <= p <= 255 for p in parts):
            return '#{0:02X}{1:02X}{2:02X}'.format(*parts)
    except (TypeError, ValueError):
        pass
    return None


# ---- 3Dビュー(ローカル/グローブ) → cam:/fly_geojson: 行 ----------------

_WGS84_A = 6378137.0
_WGS84_E2 = (1.0 / 298.257223563) * (2.0 - 1.0 / 298.257223563)


def _ecef_to_geodetic(x, y, z):
    """ECEF(m) → (lat_deg, lon_deg, 楕円体高 m)。WGS84 閉形式+反復。"""
    p = math.hypot(x, y)
    if p < 1e-9:
        return (math.copysign(90.0, z), 0.0,
                abs(z) - _WGS84_A * math.sqrt(1.0 - _WGS84_E2))
    lon = math.atan2(y, x)
    lat = math.atan2(z, p * (1.0 - _WGS84_E2))
    for _ in range(5):
        n = _WGS84_A / math.sqrt(1.0 - _WGS84_E2 * math.sin(lat) ** 2)
        lat = math.atan2(z + _WGS84_E2 * n * math.sin(lat), p)
    n = _WGS84_A / math.sqrt(1.0 - _WGS84_E2 * math.sin(lat) ** 2)
    return math.degrees(lat), math.degrees(lon), p / math.cos(lat) - n


def _camera_offset_enu(dist, pitch_deg, yaw_deg):
    """QGIS 3Dカメラ姿勢 → 注視点からカメラへの ENU オフセット (E,N,U) m。

    ``QgsCameraPose::updateCamera``(ローカル)/``updateCameraGlobe``(グローブ)
    の分解: 高さ成分は ``dist*cos(pitch)``、水平成分は ``dist*sin(pitch)``、
    カメラは注視点から見て方位 ``(180-yaw)``° に位置する
    (``E=g*sin(yaw), N=-g*cos(yaw)``)。pitch: 0=真上俯瞰, 90=水平。
    """
    p, h = math.radians(pitch_deg), math.radians(yaw_deg)
    g = dist * math.sin(p)
    return g * math.sin(h), -g * math.cos(h), dist * math.cos(p)


def _camera_geodetic(x, y, z, dist, pitch, yaw, wgs3, globe):
    """注視点(シーン座標)+姿勢 → カメラの (lat, lon, h)。失敗時 None。"""
    e, n, u = _camera_offset_enu(dist, pitch, yaw)
    if not globe:
        return wgs3(x + e, y + n, z + u)
    lat_c, lon_c, _h_c = wgs3(x, y, z)
    clat, clon = math.radians(lat_c), math.radians(lon_c)
    # 注視点でのローカル ENU 基底(ECEF での単位ベクトル)
    up = (math.cos(clat) * math.cos(clon),
          math.cos(clat) * math.sin(clon), math.sin(clat))
    east = (-math.sin(clon), math.cos(clon), 0.0)
    north = (-math.sin(clat) * math.cos(clon),
             -math.sin(clat) * math.sin(clon), math.cos(clat))
    cx = x + e * east[0] + n * north[0] + u * up[0]
    cy = y + e * east[1] + n * north[1] + u * up[1]
    cz = z + e * east[2] + n * north[2] + u * up[2]
    return _ecef_to_geodetic(cx, cy, cz)


def _cam_3d_line(name, lat, lon, h, pitch, yaw):
    """cam:QGIS3D 行。h=楕円体高, p=QGIS pitch→Cesium pitch(pitch-90),
    d=視線方位(360-yaw)。QGIS yaw は反時計回り(数学的正方向)のため
    視線方位は ``-yaw`` になる(updateCamera* の ENU 分解より)。"""
    return ('cam:QGIS3D {0}|{1:.6f}|{2:.6f}|h={3:.0f}'
            '|p={4:.1f}|d={5:.1f}').format(
                _kasc_escape(name), lat, lon, max(1.0, h),
                pitch - 90.0, (-yaw) % 360.0)


def _scene_crs_authid(view):
    """<view><qgis3d><crs> 要素からシーンCRS の authid を取る。"""
    crs_el = view.find('qgis3d/crs')
    if crs_el is None:
        return None
    for el in crs_el.iter():
        if el.tag == 'authid' and el.text and el.text.strip():
            return el.text.strip()
    return None


def _scene_transformer(view, project, warnings):
    """ビューのシーン座標→測地変換 ``wgs3(x,y,z)->(lat,lon,h)`` と
    グローブ(地心系)フラグを返す。

    - シーンCRSが地心系(グローブ: EPSG:4978 等) → ECEF→測地(WGS84
      閉形式。非WGS84系は QgsCoordinateTransform→EPSG:4979)
    - EPSG:4326 → 恒等
    - その他ローカルシーン → QgsCoordinateTransform(シーンCRS→4326)
      で (x,y) 変換、z は高さとしてそのまま返す
    """
    authid = _scene_crs_authid(view)
    has_qgis = False
    try:
        from qgis.core import (QgsCoordinateReferenceSystem,
                               QgsCoordinateTransform, QgsPoint,
                               QgsPointXY, Qgis)
        has_qgis = True
    except Exception:  # nosec B110  # qgis 無し環境(単体テスト)の許容
        pass
    scene_crs = None
    if has_qgis:
        try:
            scene_crs = (QgsCoordinateReferenceSystem(authid)
                         if authid else project.crs())
            if scene_crs is not None and not scene_crs.isValid():
                scene_crs = None
        except Exception:  # nosec B110  # 設計上の許容
            scene_crs = None
    globe = False
    if scene_crs is not None:
        try:
            globe = scene_crs.type() == Qgis.CrsType.Geocentric
        except Exception:  # nosec B110  # 設計上の許容
            globe = False
    if not globe and (authid or '').upper() == 'EPSG:4978':
        globe = True  # qgis 無し/判定失敗時のフォールバック
    if globe:
        if not has_qgis or scene_crs is None \
                or (authid or '').upper() == 'EPSG:4978':
            return _ecef_to_geodetic, True
        try:
            tr = QgsCoordinateTransform(
                scene_crs,
                QgsCoordinateReferenceSystem('EPSG:4979'), project)

            def f(x, y, z):
                pt = tr.transform(QgsPoint(x, y, z))
                return pt.y(), pt.x(), pt.z()
            return f, True
        except Exception as e:
            warnings.append('3Dビュー: ECEF変換失敗({0})、'
                            'WGS84近似で処理: {1}'.format(authid, e))
            return _ecef_to_geodetic, True
    if (authid or '').upper() == 'EPSG:4326':
        return (lambda x, y, z: (y, x, z)), False
    if not has_qgis:
        if not authid:
            return (lambda x, y, z: (y, x, z)), False
        warnings.append('3Dビュー: qgis 未検出のためシーンCRS {0} を'
                        '4326とみなします'.format(authid))
        return (lambda x, y, z: (y, x, z)), False
    try:
        if scene_crs is None:
            scene_crs = QgsCoordinateReferenceSystem(authid)
        tr = QgsCoordinateTransform(
            scene_crs, QgsCoordinateReferenceSystem('EPSG:4326'), project)

        def f(x, y, z):
            try:
                pt = tr.transform(QgsPoint(x, y, z))
                return pt.y(), pt.x(), pt.z()
            except Exception:
                pt = tr.transform(QgsPointXY(x, y))
                return pt.y(), pt.x(), z
        return f, False
    except Exception as e:
        warnings.append('3Dビュー: シーンCRS {0} の変換を'
                        '作成できず座標をそのまま使います: {1}'.format(
                            authid or project.crs().authid(), e))
        return (lambda x, y, z: (y, x, z)), False


def _anim3d_fly_line(view, name, wgs3, globe, data_dir, used_names,
                     warnings):
    """<animation3d><keyframe> 列 → fly_geojson: 行 + DATA/*.geojson。

    キーフレームは ``lookingAtMapPoint``(注視点・シーン座標)+姿勢で保持
    されるため、各キーフレームのカメラ位置を _camera_geodetic で求めて
    フライパス(カメラ軌道)にする。speed はカメラ軌道の3D総延長を
    アニメーション時間で割った m/s。キーフレーム2未満は行を返さない。
    """
    anim = view.find('animation3d')
    if anim is None:
        return None
    keyframes = anim.findall('keyframes/keyframe')
    if len(keyframes) < 2:
        return None
    coords, times = [], []
    for kf in keyframes:
        try:
            x = float(kf.get('x'))
            y = float(kf.get('y'))
            z = float(kf.get('z') or 0.0)
            dist = float(kf.get('dist') or 0)
            pitch = float(kf.get('pitch') or 0)
            yaw = float(kf.get('yaw') or 0)
            t = float(kf.get('time') or 0)
        except (TypeError, ValueError):
            continue
        if dist <= 0:
            continue
        try:
            lat, lon, h = _camera_geodetic(
                x, y, z, dist, pitch, yaw, wgs3, globe)
        except Exception:  # nosec B112  # 設計上の許容
            continue
        coords.append([round(lon, 6), round(lat, 6),
                       int(round(max(1.0, h)))])
        times.append(t)
    if len(coords) < 2:
        return None
    legs = []
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        legs.append(math.hypot(_fly_leg_dist_m(a, b), b[2] - a[2]))
    total = sum(legs)
    duration = max(times) - min(times)
    speed = (total / duration) if duration > 0.5 and total > 0 else None
    if speed is None or speed <= 0 or speed > 10000:
        speed = _fly_auto_speed_ms(total)
    speed = round(speed, 1)
    step = int(round(total / max(1, len(coords) - 1))) or 100
    title = 'QGIS3D {0}'.format(name)
    slug = _slugify('anim3d_{0}'.format(name), used_names)
    gj = {
        'type': 'FeatureCollection',
        'features': [{
            'type': 'Feature',
            'properties': {
                'name': title,
                'source': 'qgis3dAnimation',
                'view': name,
                'keyframes': len(coords),
                'duration': round(duration, 2),
                'heightReference': 'MSL',
                'fly': {
                    'speed': speed, 'height': 0, 'step': step,
                    'loop': False, 'view': 'camera',
                },
            },
            'geometry': {
                'type': 'LineString',
                'coordinates': coords,
            },
        }],
    }
    path = os.path.join(data_dir, slug + '.geojson')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(gj, f, ensure_ascii=False)
    except Exception as e:
        warnings.append('3Dビュー {0}: アニメgeojson書込失敗: {1}'.format(
            name, e))
        return None
    return ('fly_geojson: {0} | DATA/{1}.geojson | speed={2} '
            '| view=camera | step={3}').format(
                _kasc_escape(title), slug, speed, step)


def _threed_lines(project, warnings, data_dir=None, used_names=None):
    """保存済み3Dビュー(<mapViewDocks3D><view>) → cam:/terrain:/scene3d:/light:/fly_geojson: 行一覧。

    3D カメラは注視点(xMap,yMap,zMap=シーンCRS, dist=視線距離, pitch,
    yaw)で保持される。カメラ位置は注視点からの ENU オフセット
    (E=dist*sin(p)*sin(yaw), N=-dist*sin(p)*cos(yaw), U=dist*cos(p))
    で求め ``cam:QGIS3D <名前>|lat|lon|h=|p=|d=`` として出力する
    (2D の cam: と分離するため名前を前置)。シーンCRSはビューごとの
    <qgis3d><crs> を使い、地心系(グローブ・QGIS4)は ECEF→測地変換する。
    地形設定は ``terrain:`` 行、シーン画面設定(背景色/スカイボックス/
    影/SSAO/EDL・グローブ時は globe=on)は ``scene3d:`` 行、平行光源は
    ``light:`` 行(シーン座標の光源方向ベクトル→方位/仰角)。
    <animation3d> キーフレームはカメラ軌道を ``fly_geojson:`` 行 +
    DATA/anim3d_*.geojson として出力する(#60)。
    """
    out = []
    root = _project_xml_root(project)
    if root is None:
        return out
    try:
        for view in root.iter('view'):
            name = view.get('name') or '3D'
            cam_el = view.find('camera')
            if cam_el is None:
                continue
            try:
                x = float(cam_el.get('xMap'))
                y = float(cam_el.get('yMap'))
                z = float(cam_el.get('zMap') or 0)
                dist = float(cam_el.get('dist') or 0)
                pitch = float(cam_el.get('pitch') or 0)
                yaw = float(cam_el.get('yaw') or 0)
            except (TypeError, ValueError):
                continue
            if dist <= 0:
                continue
            wgs3, globe = _scene_transformer(view, project, warnings)
            try:
                lat, lon, h = _camera_geodetic(
                    x, y, z, dist, pitch, yaw, wgs3, globe)
                out.append(_cam_3d_line(name, lat, lon, h, pitch, yaw))
            except Exception as e:
                warnings.append(
                    '3Dビュー {0}: カメラ変換失敗: {1}'.format(name, e))
            if data_dir is not None and used_names is not None:
                try:
                    line = _anim3d_fly_line(
                        view, name, wgs3, globe, data_dir, used_names,
                        warnings)
                    if line:
                        out.append(line)
                except Exception as e:
                    warnings.append(
                        '3Dビュー {0}: アニメ出力失敗: {1}'.format(name, e))
            qgis3d = view.find('qgis3d')
            if qgis3d is None:
                continue
            # 地形(ジェネレータ/垂直誇張/オフセット/陰影) → terrain: 行。
            # 既定(dem・誇張1・オフセット0・陰影off)と同じ内容は出さない
            terr = qgis3d.find('terrain')
            if terr is not None:
                try:
                    opts = []
                    gen = terr.find('generator')
                    gtype = (gen.get('type') or '').strip() \
                        if gen is not None else ''
                    try:
                        ex = float(terr.get('exaggeration') or 1.0)
                    except (TypeError, ValueError):
                        ex = 1.0
                    try:
                        off = float(terr.get('elevation-offset') or 0.0)
                    except (TypeError, ValueError):
                        off = 0.0
                    if abs(ex - 1.0) > 0.001:
                        opts.append('exaggeration={0:g}'.format(ex))
                    if abs(off) > 0.001:
                        opts.append('offset={0:g}'.format(off))
                    if terr.get('shading-enabled') == '1':
                        opts.append('shading=on')
                    if gtype and (gtype != 'dem' or opts):
                        opts.insert(0, 'generator={0}'.format(gtype))
                    if opts:
                        out.append('terrain: qgis | {0}'.format(
                            ' | '.join(opts)))
                except (TypeError, ValueError):
                    pass
            # 画面設定(背景色/スカイボックス/影/SSAO/EDL) → scene3d: 行。
            # 既定(QGIS 初期状態)と同じ内容は出さない
            sopts = []
            if globe:
                sopts.append('globe=on')
            # background は先頭に出す(Canvas が背景色適用時に空を隠すため、
            # skybox=on を後ろに置いて有効な SkyBox を復帰させる)
            color_el = qgis3d.find('color')
            if color_el is not None:
                bg = _qgis3d_color_hex(color_el.get('background'))
                if bg and bg.upper() != '#FFFFFF':
                    sopts.append('background={0}'.format(bg))
            sky_el = qgis3d.find('skybox')
            if sky_el is not None and sky_el.get('skybox-enabled') == '1':
                sopts.append('skybox=on')
            shadow_el = qgis3d.find('shadow-rendering')
            if shadow_el is not None and \
                    shadow_el.get('shadow-rendering-enabled') == '1':
                sopts.append('shadows=on')
            ao_el = qgis3d.find('screen-space-ambient-occlusion')
            if ao_el is not None and ao_el.get('enabled') == '1':
                sopts.append('ao=on')
            edl_el = qgis3d.find('eye-dome-lighting')
            if edl_el is not None and edl_el.get('enabled') == '1':
                sopts.append('edl=on')
            if sopts:
                out.append('scene3d: {0} | {1}'.format(
                    _kasc_escape(name), ' | '.join(sopts)))
            # 平行光源 → light: 行。QGIS 3D シーン座標は x=東, y=上,
            # z=南(-z が北)で、ベクトルは光源「へ向かう」方向
            # (Qt3D worldDirection)。方位/仰角へ変換して渡す
            lights = qgis3d.find('lights')
            if lights is not None:
                for dl in lights.findall('directional-light'):
                    try:
                        lx = float(dl.get('x') or 0)
                        ly = float(dl.get('y') or 0)
                        lz = float(dl.get('z') or 0)
                        norm = math.sqrt(lx * lx + ly * ly + lz * lz)
                        if norm <= 0:
                            continue
                        lopts = [
                            'az={0:.1f}'.format(
                                math.degrees(
                                    math.atan2(lx, -lz)) % 360),
                            'el={0:.1f}'.format(
                                math.degrees(math.asin(ly / norm)))]
                        try:
                            inten = float(dl.get('intensity') or 1.0)
                            if abs(inten - 1.0) > 0.001:
                                lopts.append(
                                    'intensity={0:g}'.format(inten))
                        except (TypeError, ValueError):
                            pass
                        col = _qgis3d_color_hex(dl.get('color'))
                        if col and col.upper() != '#FFFFFF':
                            lopts.append('color={0}'.format(col))
                        out.append('light: {0} | {1}'.format(
                            _kasc_escape(name), ' | '.join(lopts)))
                    except (TypeError, ValueError):
                        continue
    except Exception as e:
        warnings.append('3Dビュー設定の出力に失敗: {0}'.format(e))
    return out


def _theme_style_qml(layer, style_name, data_dir, slug, theme_slug,
                     warnings, used_names, copied):
    """テーマ記録の名前付きスタイル(styleManager の名前)を
    DATA/<slug>__<theme>.qml へ出力し 'DATA/...' を返す。
    styleManager に無い・無効なスタイルは None。
    xmlData() は .qml 同等の <qgis> 文書文字列(QGIS 4.0 実測)。"""
    try:
        mgr = layer.styleManager()
        st = mgr.style(style_name) if mgr is not None else None
        if st is None or not st.isValid():
            return None
        fname = '{0}__{1}.qml'.format(
            slug or 'layer', theme_slug or 'theme')
        fpath = os.path.join(data_dir, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(st.xmlData())
        # メインスタイルと同様にシンボル画像(SVG/ラスタ)を
        # DATA/ へ複製して参照を書き換える(絶対パス残存を防ぐ)
        try:
            _export_qml_assets(
                fpath, slug or 'layer', data_dir, used_names, copied,
                warnings)
        except Exception as e:
            warnings.append(
                'theme style {0}: シンボル画像の複製失敗: {1}'.format(
                    style_name, e))
        return 'DATA/' + fname
    except Exception as e:
        warnings.append('theme style {0}: {1}'.format(style_name, e))
        return None


def _export_bookmarks_xml(path):
    """QGISブックマーク(プロジェクト+アプリケーション)を qgis_bookmarks
    形式の XML として path へ出力する。

    extent は全て EPSG:4326 へ正規化する(sr_id はQGIS内部srsidで
    EPSGと一致しないため、参照側が確実に度単位として読めるようにする)。
    戻り値は書き出した件数。失敗時・0件時は 0(ファイルは作らない)。
    """
    try:
        from qgis.core import (QgsApplication, QgsBookmark,
                               QgsBookmarkManager,
                               QgsCoordinateReferenceSystem,
                               QgsCoordinateTransform, QgsProject,
                               QgsReferencedRectangle)
        project = QgsProject.instance()
        dest = QgsCoordinateReferenceSystem('EPSG:4326')
        # 変換済みブックマークを集める一時マネージャ(initialize しないので
        # ファイルへは書き出さない)
        tmp = QgsBookmarkManager()
        count = 0
        for mgr in (project.bookmarkManager(),
                    QgsApplication.bookmarkManager()):
            if mgr is None:
                continue
            for bm in mgr.bookmarks() or []:
                try:
                    ext = bm.extent()
                    if ext is None or ext.isNull() or ext.isEmpty():
                        continue
                    src = ext.crs()
                    if src is None or not src.isValid():
                        src = project.crs()
                    rect = QgsCoordinateTransform(
                        src, dest, project).transformBoundingBox(ext)
                    nb = QgsBookmark()
                    nb.setName(bm.name())
                    nb.setGroup(bm.group())
                    nb.setRotation(bm.rotation())
                    nb.setExtent(QgsReferencedRectangle(rect, dest))
                    tmp.addBookmark(nb)
                    count += 1
                except Exception:  # nosec B112  # 設計上の許容
                    continue
        if not count:
            return 0
        return count if QgsBookmarkManager.exportToFile(path, [tmp]) else 0
    except Exception:
        return 0


# ---- アトラス → fly_geojson: 行 -------------------------------------

# Canvas 側の正典カメラ高換算(web/shared/kasc.js の nadirVisibleExtent /
# zoomToCamHeightView と同じ球体幾何)。表示範囲 E[m] を収める直下視
# カメラ高 h を返す。fov は正典 60 度・ビューポートは正方形として扱う
_EARTH_R = 6371008.8
_MERC_R = 6378137.0


def _merc_y(lat):
    lat = max(-85.05, min(85.05, float(lat)))
    return _MERC_R * math.log(
        math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))


def _extent_view_height(w, s, e, n, margin=1.08, fov_deg=60.0):
    """EPSG:4326 の bbox を収める正典カメラ高(m)を返す。

    Canvas の正典高さ ⇄ 表示範囲は ``E = 2αR`` (α は視線の中心角)。
    メルカトルメートルで範囲の大きい方を E に取り、margin で外周に
    余白を持たせる。戻り値は楕円体高(MSL基準で良い近似値)。
    """
    dx = abs(math.radians(float(e) - float(w))) * _MERC_R
    dy = abs(_merc_y(n) - _merc_y(s))
    ext = max(dx, dy, 1.0) * margin
    alpha = ext / (2.0 * _EARTH_R)
    th = math.radians(fov_deg) / 2.0
    return _EARTH_R * (math.sin(alpha + th) / math.sin(th) - 1.0)


def _fly_leg_dist_m(a, b):
    """[lon,lat] 2点間の地表距離(m)。Canvas flyLegDist と同じhaversine。"""
    d_lat = math.radians(b[1] - a[1])
    d_lng = math.radians(b[0] - a[0])
    s = (math.sin(d_lat / 2.0) ** 2 +
         math.cos(math.radians(a[1])) * math.cos(math.radians(b[1])) *
         math.sin(d_lng / 2.0) ** 2)
    return 2.0 * _EARTH_R * math.asin(min(1.0, math.sqrt(s)))


def _fly_auto_speed_ms(total_m):
    """ルート総距離から既定速度(m/s)を決める。

    Canvas shared/player-api.js の flyAutoSpeedKmh と同じ階段。
    ``.kasc`` の ``speed=`` は m/s 規約で書く(2Dプレイヤー側の解釈)。
    """
    if total_m < 5e3:
        return 16.7   # 60 km/h
    if total_m < 5e4:
        return 83.3   # 300 km/h
    return 250.0      # 900 km/h


def _atlas_page_frames(layout, warnings):
    """アトラス有効な印刷レイアウトの各ページ表示範囲を返す。

    ``atlas.beginRender() → seekTo(i) → 参照地図の extent()`` で
    実際のページ範囲を取り、EPSG:4326 bbox へ変換する。戻り値は
    ``{'coverage': レイヤ名, 'rotation': 地図回転角,
       'pages': [{'name':..., 'bbox':(w,s,e,n)}...]}``。
    アトラス無効・条件未達は None。
    """
    from qgis.core import (QgsCoordinateReferenceSystem,
                           QgsCoordinateTransform, QgsLayoutItemMap,
                           QgsProject)
    atlas = layout.atlas()
    if atlas is None or not atlas.enabled():
        return None
    coverage = atlas.coverageLayer()
    if coverage is None:
        warnings.append('atlas {0}: カバレッジレイヤ無し'.format(
            layout.name()))
        return None
    ref_map = layout.referenceMap()
    if ref_map is None:
        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap):
                ref_map = item
                break
    if ref_map is None:
        warnings.append('atlas {0}: 地図アイテム無し'.format(
            layout.name()))
        return None
    project = QgsProject.instance()
    map_crs = ref_map.crs()
    dest = QgsCoordinateReferenceSystem('EPSG:4326')
    to_wgs = (QgsCoordinateTransform(map_crs, dest, project)
              if map_crs is not None and map_crs.isValid()
              and map_crs != dest else None)
    pages = []
    try:
        if not atlas.beginRender():
            warnings.append('atlas {0}: beginRender失敗'.format(
                layout.name()))
            return None
        try:
            count = atlas.count()
        except Exception:
            count = 0
        for i in range(count):
            try:
                if not atlas.seekTo(i):
                    continue
            except Exception:  # nosec B112  # 設計上の許容
                continue
            try:
                ext = ref_map.extent()
            except Exception:  # nosec B112  # 設計上の許容
                continue
            if ext is None or ext.isNull() or ext.isEmpty():
                continue
            try:
                if to_wgs is not None:
                    ext = to_wgs.transformBoundingBox(ext)
            except Exception:  # nosec B112  # 設計上の許容
                continue
            name = ''
            # ページ名: ユーザー定義名 → ファイル名式 → 連番 の優先順。
            # メソッド有無・引数の違い(旧API)は個別に try で吸収する
            for call in (
                    lambda: atlas.nameForPage(i),
                    lambda: atlas.filenameForPage(i),
                    lambda: atlas.currentFilename()):
                try:
                    name = str(call() or '').strip()
                except Exception:  # nosec B112  # 設計上の許容
                    name = ''
                if name:
                    break
            w = min(ext.xMinimum(), ext.xMaximum())
            e = max(ext.xMinimum(), ext.xMaximum())
            s = min(ext.yMinimum(), ext.yMaximum())
            n = max(ext.yMinimum(), ext.yMaximum())
            pages.append({'name': name or 'page {0}'.format(i + 1),
                          'bbox': (w, s, e, n)})
    finally:
        try:
            atlas.endRender()
        except Exception:  # nosec B110  # 設計上の許容
            pass
    rotation = 0.0
    try:
        rotation = float(ref_map.mapRotation() or 0.0)
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return {'coverage': coverage.name(), 'rotation': rotation,
            'pages': pages}


def _export_atlas_fly(project, data_dir, used_names, warnings):
    """アトラス有効な印刷レイアウト → fly_geojson: 行 + DATA/atlas_*.geojson。

    各ページの表示範囲を巡回するフライパスを生成する。座標のZ値には
    そのページ範囲を収める正典カメラ高を焼き込み、GeoJSON properties の
    ``heightReference: "MSL"`` で地形加算を抑止する(Cesium復元規約)。
    ``properties.fly`` に speed/pitch/step 等も埋め込み、.kasc 行側と
    同じ設定がリロード後も維持されるようにする。
    戻り値は (fly_geojson行のリスト, atlas情報のリスト)。
    """
    lines, infos = [], []
    try:
        mgr = project.layoutManager()
        layouts = mgr.printLayouts() if mgr is not None else []
    except Exception:  # nosec B110  # 設計上の許容
        layouts = []
    for layout in layouts:
        try:
            frames = _atlas_page_frames(layout, warnings)
        except Exception as e:
            warnings.append('atlas {0}: {1}'.format(layout.name(), e))
            continue
        if not frames:
            continue
        pages = frames['pages']
        if not pages:
            warnings.append('atlas {0}: ページ0件'.format(layout.name()))
            continue
        if abs(frames['rotation'] or 0.0) > 0.01:
            warnings.append(
                'atlas {0}: 地図回転({1:.1f}°)はフライパスに反映'
                'できません'.format(layout.name(), frames['rotation']))
        coords = []
        for p in pages:
            w, s, e, n = p['bbox']
            lon = (w + e) / 2.0
            lat = (s + n) / 2.0
            height = _extent_view_height(w, s, e, n)
            coords.append([
                round(lon, 6), round(lat, 6),
                int(round(max(1.0, height)))])
        legs = [_fly_leg_dist_m(coords[i], coords[i + 1])
                for i in range(len(coords) - 1)]
        total = sum(legs)
        speed = _fly_auto_speed_ms(total)
        speed = round(speed, 1)
        step = int(round(total / len(legs))) if legs else 100
        name = 'Atlas: {0}'.format(layout.name())
        slug = _slugify('atlas_{0}'.format(layout.name()), used_names)
        gj = {
            'type': 'FeatureCollection',
            'features': [{
                'type': 'Feature',
                'properties': {
                    'name': name,
                    'source': 'qgisAtlas',
                    'layout': layout.name(),
                    'coverage': frames['coverage'],
                    'pages': [p['name'] for p in pages],
                    'pageCount': len(pages),
                    'heightReference': 'MSL',
                    'fly': {
                        'speed': speed, 'height': 0, 'pitch': -85,
                        'step': step, 'loop': False, 'view': 'camera',
                    },
                },
                'geometry': {
                    'type': 'LineString',
                    'coordinates': coords,
                },
            }],
        }
        path = os.path.join(data_dir, slug + '.geojson')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(gj, f, ensure_ascii=False)
        except Exception as e:
            warnings.append('atlas {0}: geojson書込失敗: {1}'.format(
                layout.name(), e))
            continue
        line = ('fly_geojson: {0} | DATA/{1}.geojson | speed={2} '
                '| pitch=-85 | height=0 | view=camera | step={3}'
                ).format(_kasc_escape(name), slug, speed, step)
        lines.append(line)
        infos.append({
            'layout': layout.name(), 'pages': len(pages),
            'coverage': frames['coverage'],
            'file': 'DATA/{0}.geojson'.format(slug), 'title': name,
        })
    return lines, infos


def _attribution(layer):
    """レイヤの出典(attribution)文字列。失敗時は空文字。"""
    try:
        return (layer.attribution() or '').strip()
    except Exception:  # nosec B110  # 設計上の許容
        return ''


def _write_engine_launchers(out_dir, kasc_name):
    """.kasc と同じ場所に <engine>.html 起動ページ一式を出力する。

    生成物:
        cesium.html / maplibre.html / openlayers.html / leaflet.html /
            gsimaps.html / navara.html —
            同名エンジンへ ``?kasc=<この .kasc の絶対URL>`` 付きで転送する
            自己完結ランチャー。エンジン本体(web/ の中身)は ./ ../ ../../ /
            の順に自動探索し、見つからなければHTML内の CANVAS_BASE を
            編集して使う
        index.html — 3系統の表示経路案内ページ(①KASUGAI Canvas登録
            ②ローカルHTTP配信で即表示 ③サーバレスWEB配信/パッケージ配置)
            ＋ kasugai_canvas_<ch>.zip ダウンロードリンク

    出力フォルダとエンジンを同じ静的 Web サーバーへアップするだけで
    動く、サーバレス配布のための部品。
    """
    written = []
    for engine in _LAUNCHER_ENGINES:
        html = (_localize_page(_ENGINE_LAUNCHER_HTML)
                .replace('__ENGINE__', engine)
                .replace('__HOSTED_BASE__', hosted_engine_base())
                .replace('__KASC__', kasc_name))
        path = os.path.join(out_dir, '{0}.html'.format(engine))
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        written.append(path)
    idx_path = os.path.join(out_dir, 'index.html')
    with open(idx_path, 'w', encoding='utf-8') as f:
        f.write(_localize_page(_LAUNCHER_INDEX_HTML)
                .replace('__KASC__', kasc_name)
                .replace('__ZIP_NAME__', export_zip_name())
                .replace('__HOSTED_BASE__', hosted_engine_base()))
    written.append(idx_path)
    return written


def export_kasugai_project(iface, out_dir=None, visible_only=True,
                           native_formats=True, hidden_as_off=False,
                           embed_gpkg_style=False,
                           emit_themes=True, emit_bookmarks=True,
                           emit_launchers=True, emit_zip=False,
                           emit_atlas=True,
                           changed=None, live_url=None):
    """レイヤツリーを KASUGAI Canvas プロジェクトとして出力する。

    引数:
        visible_only: True なら非表示レイヤは出力しない(既定)。
        native_formats: True なら GPKG/GeoJSON/GeoParquet/FlatGeobuf
            ソース(ローカルファイル・http URL)をそのまま参照し、
            CSV/TSV(delimitedtext 等)は ``duckdb:`` 行(lon=/lat=/geom=)、
            フィルタ付き GPKG は ``where=`` 付き ``gpkg:``、
            フィルタ付き Parquet は ``duckdb:+format=parquet+where=``、
            3D Tiles レイヤは ``3dtiles:``、ローカル XYZ テンプレートは
            タイルツリー複製の ``xyz:`` 行として出力する。
            それ以外のベクターのみ GeoJSON(EPSG:4326)へ出力する。
            False なら全ベクターを GeoJSON へ変換する(従来動作)。
        hidden_as_off: True なら非表示レイヤも ``| off`` 付きで出力する
            (visible_only より優先。プロジェクト構成の丸ごと引越し用)。
            なお「背景図」「ベースマップ」「basemap」名
            (設定 ``kasugai_basemap_groups`` で追加可)のグループ内に
            ある XYZ レイヤは visible_only/hidden_as_off に関わらず
            全て ``base:`` 行(ベースマップ候補)として出力する。
            グループ名はタイトルから外し、配下のサブグループのみ
            ``サブグループ/レイヤ名`` として残す(Canvas 側の
            ベースマップ選択でグループ化表示される)。
        embed_gpkg_style: True なら gpkg: 参照レイヤの現在スタイルを
            QGIS 標準の layer_styles(useAsDefault)へも保存する。
            **元の .gpkg ファイルへ書き込む**点に注意(opt-in)。
            保存は DATA/ へのコピー前に行い、配布コピーにも
            layer_styles が含まれる(対象はローカル GPKG のみ。
            http URL 参照の GPKG へは書き込めないため対象外)。
        emit_themes: True ならプロジェクトのマップテーマを ``theme:`` 行
            (Canvas の可視性プリセット)として出力する(既定)。
            テーマが存在する場合、非表示レイヤも ``| off`` で出力しないと
            テーマ側から表示へ戻せないため、hidden_as_off 同等に全レイヤを
            出力する。テーマが無ければ従来どおりの出力。
        emit_bookmarks: True ならプロジェクト+アプリケーションの
            ブックマークを ``bookmarks.xml``(qgis_bookmarks 形式・
            EPSG:4326 正規化)として出力し ``bookmark:`` 行を書く(既定)。
            Canvas 側ではカメラプリセットUIにそのまま並ぶ。
        emit_launchers: True なら .kasc と同じ場所に
            ``<engine>.html``(cesium/maplibre/openlayers/leaflet/gsimaps/
            navara)と
            ``index.html`` のエンジン起動ページを出力する(既定)。
            各HTMLは ``?kasc=<この .kasc の絶対URL>`` 付きでエンジンへ
            転送し、エンジン本体(web/ の中身)を ./ ../ ../../ / の順に
            自動探索する。出力フォルダとエンジンを同じ静的サーバーへ
            アップするだけで動くサーバレス配布の部品。
        emit_zip: True なら出力一式(.kasc+DATA/+bookmarks.xml等)を
            ``kasugai_canvas_<tag>.zip``(export_zip_name、CDNチャンネル反映)
            として同じ場所に固める(既定 False)。
            Re:Earth geo_suite の ``qgis: <zip URL>`` インスペクタ行が
            このZIPを直接取り込める(CMS等へアップするだけで再現可能)。
            ``/export-data/kasugai_canvas*.zip`` からも取得できる
            (未生成時はその場で固めて返す)。
        emit_atlas: True ならアトラス有効な印刷レイアウトを
            ``fly_geojson:`` 行 + ``DATA/atlas_*.geojson`` として
            出力する(既定)。各アトラスページの表示範囲を巡回する
            フライパスで、座標Z値にページを収めるカメラ高を焼き込む
            (``properties.heightReference="MSL"`` で地形加算を抑止)。

    戻り値: {"dir","kasc","data_dir","layers":[{name,file,features}],
             "tiles":[...],"skipped":[...],"errors":[...],"warnings":[...],
             "launchers":[...],"zip":...,"atlases":[{layout,pages,file}]}。
    layers が1件も無くても .kasc は出力する。
    """
    from qgis.core import QgsVectorLayer, QgsProject
    out_dir = os.path.abspath(out_dir or get_output_dir())
    data_dir = os.path.join(out_dir, 'DATA')
    os.makedirs(data_dir, exist_ok=True)
    global _last_export_dir
    _last_export_dir = out_dir
    # 旧世代の kasugai_canvas*.zip が残っていると /export-data/ で
    # 陳腐化したZIPが配信されるため除去する(emit_zip 時は後段で再生成)
    try:
        for name in os.listdir(out_dir):
            if _is_export_zip_name(name):
                os.remove(os.path.join(out_dir, name))
    except Exception:  # nosec B110  # 設計上の許容
        pass

    project = QgsProject.instance()
    project_title = os.path.splitext(
        os.path.basename(project.fileName() or ''))[0] or 'QGIS Export'

    used_names = set()
    slug_by_id = {}  # layer.id() → DATA/ 用 slug(theme 行の ;style= で使う)
    copied = {}
    layers_out, tiles_out, skipped, errors, warnings = [], [], [], [], []
    kasc_lines = []
    # ライブ差分エクスポート: {layer.id(): {'data':bool,'style':bool}}。
    # changed 指定時は未変更レイヤのデータ/スタイル書き出しを
    # 既存ファイルがある場合に限りスキップし、live.json に変更一覧を書く
    live_changed = []
    detected_base = None  # 表示中の最下段 XYZ → base: 行
    group_bases = []      # ベースマップグループ内 XYZ の base: 行
    basemap_layer_ids = set()  # base: 行へ回したレイヤ(theme 行から除外)

    group_states = {}
    exclusive_groups = set()
    tree = _tree_layers(skipped, warnings, group_states, exclusive_groups)

    # カスタムレイヤー順(描画順オーバーライド)が有効ならその順へ並べ替える(#59)
    try:
        root = project.layerTreeRoot()
        if root.hasCustomLayerOrder():
            order_map = {id(l): i
                         for i, l in enumerate(root.customLayerOrder() or [])}
            tree = sorted(
                tree,
                key=lambda t: order_map.get(id(t[0]), len(order_map)))
    except Exception:  # nosec B110  # 設計上の許容
        pass

    # theme: 行(マップテーマ → Canvas 可視性プリセット)の素材。
    # テーマが存在する場合、非表示レイヤも | off で出さないとテーマ適用時に
    # 表示へ戻せないため、hidden_as_off 同等に全レイヤを出力対象にする
    theme_names = []
    if emit_themes:
        try:
            theme_names = sorted(
                project.mapThemeCollection().mapThemes() or [])
        except Exception:
            theme_names = []
    export_hidden_off = hidden_as_off or bool(theme_names)

    # base: 判定用に表示中の最下段 XYZ を先に特定する
    last_xyz_id = None
    for layer, _groups, vis, _tn in tree:
        if vis and _xyz_layer_info(layer):
            last_xyz_id = id(layer)

    # ベースマップグループ名(内蔵+ユーザー追加)はエクスポート中固定
    basemap_names = _basemap_group_names()

    for layer, groups, visible, tnode in tree:
        # 「背景図」「basemap」名のグループはベースマップ候補の入れ物。
        # 中の XYZ レイヤはレイヤ行ではなく base: 行として登録する
        # (グループ名はタイトルから外し、配下のサブグループは残す)
        bm_idx = _basemap_group_index(groups, basemap_names)
        title = _kasc_layer_title(groups, layer.name(), exclusive_groups)
        kinds = changed.get(layer.id()) if isinstance(changed, dict) else None
        if kinds is not None:
            live_changed.append({
                'title': title,
                'data': bool(kinds.get('data')),
                'style': bool(kinds.get('style')),
            })
        if not visible:
            if (bm_idx is not None
                    and not isinstance(layer, QgsVectorLayer)
                    and _xyz_layer_info(layer)):
                # ベースマップ候補は表示状態に関わらず全て登録する
                # (visible_only/hidden_as_off の対象外。非表示は | off で
                # 「初期選択しない候補」として出す)
                vis_flag = 'off'
            elif export_hidden_off:
                vis_flag = 'off'
            elif not visible_only:
                vis_flag = 'on'
            else:
                continue
        else:
            vis_flag = 'on'

        if isinstance(layer, QgsVectorLayer):
            # ジオメトリを持たない属性テーブルは Canvas で描画できない
            try:
                from qgis.core import QgsWkbTypes
                if layer.wkbType() == QgsWkbTypes.NoGeometry:
                    skipped.append(
                        '{0} (属性テーブル)'.format(layer.name()))
                    continue
            except Exception:  # nosec B110  # 設計上の許容
                pass
            slug = _slugify(layer.name() or 'layer', used_names)
            slug_by_id[layer.id()] = slug
            qml_path = os.path.join(data_dir, slug + '.qml')
            style_opt = ''
            if (changed is None or (kinds or {}).get('style')
                    or not os.path.isfile(qml_path)):
                try:
                    _export_qml(layer, qml_path)
                    try:
                        _export_qml_assets(
                            qml_path, slug, data_dir, used_names, copied,
                            warnings)
                    except Exception as e:
                        warnings.append(
                            '{0}: シンボル画像の複製失敗: {1}'.format(
                                layer.name(), e))
                    style_opt = ' | style=DATA/{0}.qml'.format(slug)
                except Exception as e:
                    errors.append('{0}: qml {1}'.format(layer.name(), e))
            else:
                # 未変更レイヤ: 既存 .qml を再利用して書き出しをスキップ
                style_opt = ' | style=DATA/{0}.qml'.format(slug)
            feat_count = -1
            try:
                feat_count = int(layer.featureCount())
            except Exception:  # nosec B110  # 設計上の許容
                pass
            # 時間対応・ヒートマップ/クラスタ・透過度等の共通オプション
            vopt = _vector_opts_suffix(layer, warnings)

            if _has_unusable_subset(layer):
                warnings.append(
                    '{0}: フィルタに | を含むためGeoJSON変換'.format(
                        layer.name()))
                native = None
            else:
                native = _native_ref(
                    layer, slug, data_dir, copied, warnings,
                    embed_style=embed_gpkg_style) if native_formats else None
            if isinstance(native, dict) and native.get('skip_reason'):
                skipped.append(
                    '{0} ({1})'.format(layer.name(), native['skip_reason']))
                continue
            if native:
                line_type, ref = native['type'], native['ref']
                line = '{0}: {1} | {2} | {3}'.format(
                    line_type, title, _kasc_escape(ref), vis_flag)
                for key, val in native.get('opts', {}).items():
                    line += ' | {0}={1}'.format(key, _kasc_escape(val))
                line += style_opt
                line += vopt
                line += _scale_vis_opt(layer)
                attr = _attribution(layer)
                if attr:
                    line += ' | attr={0}'.format(_kasc_escape(attr))
                layers_out.append({
                    'name': layer.name(), 'title': title, 'file': ref,
                    'qml': 'DATA/{0}.qml'.format(slug) if style_opt else None,
                    'features': feat_count, 'format': line_type,
                })
                kasc_lines.append(line)
                continue

            # ネイティブ参照できないベクター → GeoJSON(EPSG:4326)へ変換
            gj_path = os.path.join(data_dir, slug + '.geojson')
            if (changed is None or (kinds or {}).get('data')
                    or not os.path.isfile(gj_path)):
                try:
                    _export_geojson(layer, gj_path)
                except Exception as e:
                    errors.append(
                        '{0}: geojson {1}'.format(layer.name(), e))
                    continue
            if not _geo_equiv_crs(layer):
                warnings.append(
                    '{0}: CRS {1} を EPSG:4326 へ再投影'.format(
                        layer.name(), layer.crs().authid() or ''))
            layers_out.append({
                'name': layer.name(), 'title': title,
                'file': 'DATA/{0}.geojson'.format(slug),
                'qml': 'DATA/{0}.qml'.format(slug) if style_opt else None,
                'features': feat_count, 'format': 'geojson',
            })
            attr = _attribution(layer)
            attr_opt = ' | attr={0}'.format(
                _kasc_escape(attr)) if attr else ''
            kasc_lines.append(
                'geojson: {0} | DATA/{1}.geojson | {2}{3}{4}{5}{6}'.format(
                    title, slug, vis_flag, style_opt, vopt,
                    _scale_vis_opt(layer), attr_opt))
            ln_meta = _legend_node_line(tnode, title)
            if ln_meta:
                kasc_lines.append(ln_meta)
        else:
            vt_src = _vectortile_source(layer)
            if vt_src:
                line = '{0}: {1} | {2} | {3}'.format(
                    vt_src['kind'], title, _kasc_escape(vt_src['url']),
                    vis_flag)
                if vt_src['zmin'] is not None:
                    line += ' | minzoom={0}'.format(vt_src['zmin'])
                if vt_src['zmax'] is not None:
                    line += ' | maxzoom={0}'.format(vt_src['zmax'])
                line += _scale_vis_opt(layer)
                attr = _attribution(layer)
                if attr:
                    line += ' | attr={0}'.format(_kasc_escape(attr))
                kasc_lines.append(line)
                tiles_out.append({'name': layer.name(), 'url': vt_src['url'],
                                  'type': vt_src['kind']})
                continue
            if _is_tiled_scene(layer):
                slug = _slugify(layer.name() or 'scene', used_names)
                ref = _tiledscene_ref(layer, slug, data_dir, copied,
                                      warnings)
                if ref:
                    line = '3dtiles: {0} | {1} | {2}'.format(
                        title, _kasc_escape(ref), vis_flag)
                    line += _scale_vis_opt(layer)
                    attr = _attribution(layer)
                    if attr:
                        line += ' | attr={0}'.format(_kasc_escape(attr))
                    kasc_lines.append(line)
                    tiles_out.append({'name': layer.name(), 'url': ref,
                                      'type': '3dtiles'})
                else:
                    skipped.append(
                        '{0} (3dtiles参照不可)'.format(layer.name()))
                continue
            xyz = _xyz_layer_info(layer)
            if xyz:
                url, zmin, zmax = xyz
                if not re.match(r'https?://', url):
                    # file:/// 等のローカルタイルテンプレートは DATA/ へ複製
                    slug = _slugify(layer.name() or 'tiles', used_names)
                    ref = _local_xyz_template(url, slug, data_dir, copied,
                                              warnings)
                    if ref:
                        url = ref
                    else:
                        skipped.append(
                            '{0} (ローカルタイル複製不可)'.format(
                                layer.name()))
                        continue
                opacity = _maplayer_opacity(layer)
                bbox = _layer_extent_bbox(layer)
                if bm_idx is not None:
                    # ベースマップグループ内の XYZ → base: 候補として登録。
                    # グループ名は外し、配下サブグループのみタイトルに残す
                    base_title = '/'.join(
                        [_kasc_escape(g)
                         for g in groups[bm_idx + 1:] if g] +
                        [_kasc_escape(layer.name())])
                    line = 'base: {0} | {1}'.format(
                        base_title, _kasc_escape(url))
                    attr = _attribution(layer)
                    if attr:
                        line += ' | {0}'.format(_kasc_escape(attr))
                    if zmax is not None:
                        line += ' | maxZoom={0}'.format(zmax)
                    if zmin is not None:
                        line += ' | minZoom={0}'.format(zmin)
                    if opacity is not None:
                        line += ' | opacity={0}'.format(opacity)
                    line += _scale_vis_opt(layer)
                    if not visible:
                        line += ' | off'
                    group_bases.append((visible, line))
                    basemap_layer_ids.add(id(layer))
                elif visible and id(layer) == last_xyz_id:
                    # QGIS の最下段タイルはベースマップとして出力
                    line = 'base: {0} | {1}'.format(title, _kasc_escape(url))
                    attr = _attribution(layer)
                    if attr:
                        line += ' | {0}'.format(_kasc_escape(attr))
                    if zmax is not None:
                        line += ' | maxZoom={0}'.format(zmax)
                    if zmin is not None:
                        line += ' | minZoom={0}'.format(zmin)
                    if opacity is not None:
                        line += ' | opacity={0}'.format(opacity)
                    line += _scale_vis_opt(layer)
                    detected_base = line
                else:
                    line = 'xyz: {0} | {1} | {2}'.format(
                        title, _kasc_escape(url), vis_flag)
                    if zmax is not None:
                        line += ' | maxZoom={0}'.format(zmax)
                    if zmin is not None:
                        line += ' | minZoom={0}'.format(zmin)
                    if opacity is not None:
                        line += ' | opacity={0}'.format(opacity)
                    line += _scale_vis_opt(layer)
                    if bbox is not None:
                        line += ' | bbox={0}'.format(bbox)
                    attr = _attribution(layer)
                    if attr:
                        line += ' | attr={0}'.format(_kasc_escape(attr))
                    kasc_lines.append(line)
                tiles_out.append({'name': layer.name(), 'url': url,
                                  'type': 'xyz'})
            else:
                wmts = _wmts_layer_info(layer)
                if wmts:
                    url, w_layers, w_styles, w_tms, w_fmt, w_tilesize = wmts
                    line = 'wmts: {0} | {1} | {2}'.format(
                        title, _kasc_escape(url), vis_flag)
                    if w_layers:
                        line += ' | layer={0}'.format(
                            _kasc_escape(w_layers))
                    if w_styles:
                        line += ' | style={0}'.format(
                            _kasc_escape(w_styles))
                    if w_tms:
                        line += ' | tilematrixset={0}'.format(
                            _kasc_escape(w_tms))
                    if w_fmt:
                        line += ' | format={0}'.format(
                            _kasc_escape(w_fmt))
                    if w_tilesize in (256, 512):
                        line += ' | tilesize={0}'.format(w_tilesize)
                    opacity = _maplayer_opacity(layer)
                    bbox = _layer_extent_bbox(layer)
                    if opacity is not None:
                        line += ' | opacity={0}'.format(opacity)
                    if bbox is not None:
                        line += ' | bbox={0}'.format(bbox)
                    line += _scale_vis_opt(layer)
                    attr = _attribution(layer)
                    if attr:
                        line += ' | attr={0}'.format(_kasc_escape(attr))
                    kasc_lines.append(line)
                    tiles_out.append({'name': layer.name(), 'url': url,
                                      'type': 'wmts'})
                    continue
                wms = _wms_layer_info(layer)
                if wms:
                    url, wms_layers, wms_styles, wms_fmt, wms_ver = wms
                    line = 'wms: {0} | {1} | {2}'.format(
                        title, _kasc_escape(url), vis_flag)
                    if wms_layers:
                        line += ' | layers={0}'.format(
                            _kasc_escape(wms_layers))
                    if wms_styles:
                        line += ' | styles={0}'.format(
                            _kasc_escape(wms_styles))
                    if wms_fmt:
                        line += ' | format={0}'.format(
                            _kasc_escape(wms_fmt))
                    if wms_ver:
                        line += ' | version={0}'.format(
                            _kasc_escape(wms_ver))
                    opacity = _maplayer_opacity(layer)
                    bbox = _layer_extent_bbox(layer)
                    if opacity is not None:
                        line += ' | opacity={0}'.format(opacity)
                    if bbox is not None:
                        line += ' | bbox={0}'.format(bbox)
                    line += _scale_vis_opt(layer)
                    attr = _attribution(layer)
                    if attr:
                        line += ' | attr={0}'.format(_kasc_escape(attr))
                    kasc_lines.append(line)
                    tiles_out.append({'name': layer.name(), 'url': url,
                                      'type': 'wms'})
                else:
                    # GDAL ラスタ: GeoTIFF/COG は geotiff: 行、
                    # それ以外の形式・再現不能なレンダラ設定は
                    # QGIS で描画済み PNG へ焼き付けて image: 行で出す
                    slug = _slugify(layer.name() or 'raster', used_names)
                    ref = _geotiff_layer_ref(
                        layer, slug, data_dir, copied)
                    need_bake = ref is None or _raster_needs_bake(layer)
                    baked_bbox = None
                    if need_bake:
                        png_path = os.path.join(data_dir, slug + '.png')
                        if (changed is None or kinds is not None
                                or not os.path.isfile(png_path)):
                            baked_bbox = _render_raster_png(
                                layer, png_path, warnings)
                        else:
                            # 未変更ラスタ: 既存PNG再利用(bboxは範囲から再現)
                            baked_bbox = _raster_bbox_str(layer)
                    if baked_bbox:
                        line = 'image: {0} | DATA/{1}.png | {2}'.format(
                            title, slug, vis_flag)
                        line += ' | bbox={0}'.format(baked_bbox)
                        opacity = _maplayer_opacity(layer)
                        if opacity is not None:
                            line += ' | opacity={0}'.format(opacity)
                        line += _scale_vis_opt(layer)
                        attr = _attribution(layer)
                        if attr:
                            line += ' | attr={0}'.format(
                                _kasc_escape(attr))
                        kasc_lines.append(line)
                        tiles_out.append({
                            'name': layer.name(),
                            'url': 'DATA/{0}.png'.format(slug),
                            'type': 'image'})
                    elif ref:
                        line = 'geotiff: {0} | {1} | {2}'.format(
                            title, _kasc_escape(ref), vis_flag)
                        bands = _raster_bands_opt(layer)
                        if bands:
                            line += ' | bands={0}'.format(bands)
                        line += _scale_vis_opt(layer)
                        opacity = _maplayer_opacity(layer)
                        if opacity is not None:
                            line += ' | opacity={0}'.format(opacity)
                        attr = _attribution(layer)
                        if attr:
                            line += ' | attr={0}'.format(
                                _kasc_escape(attr))
                        kasc_lines.append(line)
                        tiles_out.append({'name': layer.name(), 'url': ref,
                                          'type': 'geotiff'})
                    else:
                        skipped.append(
                            '{0} ({1})'.format(
                                layer.name(), _skip_reason(layer)))

    cam = _camera_line(iface)
    bookmark_count = 0
    if emit_bookmarks:
        bookmark_count = _export_bookmarks_xml(
            os.path.join(out_dir, 'bookmarks.xml'))
    default_bases = [
        'base: 地理院タイル 標準地図 | '
        'https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png | '
        '出典：国土地理院 | maxZoom=18',
        'base: 地理院タイル 淡色地図 | '
        'https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png | '
        '出典：国土地理院 | maxZoom=18 | minZoom=2 | bbox=122,19,155,47',
        'base: 地理院タイル 全国最新写真 | '
        'https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg | '
        '出典：国土地理院 | maxZoom=18 | minZoom=2 | bbox=122,19,155,47',
        'base: OpenStreetMap | https://tile.openstreetmap.org/{z}/{x}/{y}.png | '
        '(c) OpenStreetMap contributors | maxZoom=19',
    ]
    # ベースマップグループ由来の base: は表示中のものを先に並べ、
    # 非表示は | off 付きで後ろへ(先頭が Canvas の既定ベースマップ)
    ordered_group_bases = [line for vis, line in group_bases if vis] + \
        [line for vis, line in group_bases if not vis]
    # QGIS 側で表示中の XYZ があれば既定ベースマップとして先頭に置く
    bases = ([detected_base] if detected_base else []) + \
        ordered_group_bases + default_bases
    header = [
        '# Exported from QGIS geo_webview -> KASUGAI Canvas',
    ] + bases
    if cam:
        header.append(cam)
    # ライブ双方向連携: QGIS 内蔵HTTPサーバの /live/* 起点URL。
    # Canvas は同梱の live.json をポーリングし、/live/camera・
    # /live/selection へカメラ/選択を逆通知する(live_sync 有効時のみ)
    if live_url:
        header.append('live: {0}'.format(_kasc_escape(str(live_url))))
    # QGISブックマーク → bookmarks.xml + bookmark: 行。
    # Canvas 側が XML を読み込んでカメラプリセットへ展開する
    if bookmark_count:
        header.append('bookmark: bookmarks.xml')

    # Canvas 側の既定は折りたたみのため、展開状態は明示的に受け渡す
    for gname, gstate in group_states.items():
        _exp, _cs = (gstate if isinstance(gstate, tuple)
                     else (gstate, 'checked'))
        _gl = 'group: {0} | {1}'.format(
            _kasc_escape(gname), 'expanded' if _exp else 'collapsed')
        if _cs != 'checked':
            _gl += ' | checked={0}'.format(_cs)
        header.append(_gl)

    # 保存済み3Dビュー → cam:QGIS3D 行 + terrain: 行
    # + アニメーション → fly_geojson: 行(#60)
    try:
        header.extend(_threed_lines(project, warnings, data_dir,
                                    used_names))
    except Exception as e:
        warnings.append('3Dビュー出力失敗: {0}'.format(e))

    # theme: 行(QGIS マップテーマ → Canvas 可視性プリセット)。
    # 表示レイヤは .kasc のレイヤタイトル(groups/名 のパンくず)と一致させる
    if theme_names:
        try:
            collection = project.mapThemeCollection()
            title_by_id = {}
            for layer, groups, _vis, _tn in tree:
                if id(layer) in basemap_layer_ids:
                    continue  # base: 行へ回したレイヤはテーマ対象外
                title_by_id[layer.id()] = _kasc_layer_title(
                    groups, layer.name(), exclusive_groups)
            for name in theme_names:
                try:
                    visible_ids = set(
                        collection.mapThemeVisibleLayerIds(name))
                    # テーマ記録の名前付きスタイル → ;style= で引き継ぐ
                    # (MapThemeLayerRecord: layer()=メソッド、
                    #  usingCurrentStyle/currentStyle=属性。QGIS 4.0 実測)
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
                    except Exception as e:
                        warnings.append(
                            'theme {0}: スタイル記録の取得失敗: {1}'.format(
                                name, e))
                    theme_slug = _slugify(name, used_names)
                    parts = []
                    for layer, _g, _v, _tn in tree:
                        if layer.id() not in visible_ids:
                            continue
                        title = title_by_id.get(layer.id())
                        if not title:
                            continue
                        tok = title
                        sname = style_by_id.get(layer.id())
                        if sname:
                            rel = _theme_style_qml(
                                layer, sname, data_dir,
                                slug_by_id.get(layer.id()),
                                theme_slug, warnings,
                                used_names, copied)
                            if rel:
                                tok = '{0};style={1}'.format(tok, rel)
                        parts.append(tok)
                    kasc_lines.append('theme: {0}{1}'.format(
                        _kasc_escape(name),
                        ''.join(' | ' + t for t in parts)))
                except Exception as e:
                    warnings.append('theme {0}: {1}'.format(name, e))
        except Exception as e:
            warnings.append('theme 行出力失敗: {0}'.format(e))

    # アトラス有効な印刷レイアウト → fly_geojson: 行。
    # 各ページ範囲を巡回するプレゼン用フライパス(座標Z=ページを収める高さ)
    atlases = []
    if emit_atlas:
        try:
            fly_lines, atlases = _export_atlas_fly(
                project, data_dir, used_names, warnings)
            kasc_lines.extend(fly_lines)
        except Exception as e:
            warnings.append('atlas 行出力失敗: {0}'.format(e))

    kasc_path = os.path.join(out_dir, 'kasugai_canvas.kasc')
    with open(kasc_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(header + kasc_lines) + '\n')
    with open(os.path.join(out_dir, 'project.json'), 'w',
              encoding='utf-8') as f:
        json.dump({'title': project_title}, f, ensure_ascii=False)

    # ライブ連携マニフェスト。Canvas は .kasc と同じ場所のこのファイルを
    # ポーリングし、rev 増加で .kasc/変更データを再取得する
    if live_url:
        try:
            from datetime import datetime as _dt
            with open(os.path.join(out_dir, 'live.json'), 'w',
                      encoding='utf-8') as f:
                json.dump({
                    'ok': True,
                    'rev': int(time.time() * 1000),
                    'updated': _dt.now().isoformat(timespec='seconds'),
                    'changed': live_changed,
                }, f, ensure_ascii=False)
        except Exception as e:
            warnings.append('live.json 出力失敗: {0}'.format(e))

    launchers = []
    if emit_launchers:
        try:
            launchers = _write_engine_launchers(
                out_dir, os.path.basename(kasc_path))
        except Exception as e:
            warnings.append('engine launcher html 生成失敗: {0}'.format(e))

    zip_path = None
    if emit_zip:
        try:
            zip_path = _write_export_zip(out_dir)
        except Exception as e:
            warnings.append('zip 生成失敗: {0}'.format(e))

    return {
        'dir': out_dir, 'kasc': kasc_path, 'data_dir': data_dir,
        'title': project_title, 'layers': layers_out,
        'tiles': tiles_out, 'skipped': skipped, 'errors': errors,
        'warnings': warnings, 'themes': theme_names,
        'bookmarks': bookmark_count, 'launchers': launchers,
        'zip': zip_path, 'atlases': atlases,
    }


def _iter_export_files(root):
    """out_dir 配下の ZIP 格納対象を (実パス, zip内相対パス) で列挙する。

    ルートの kasugai_canvas*.zip 自身は除外する。
    """
    for r, _dirs, names in os.walk(root):
        for name in names:
            if os.path.abspath(r) == os.path.abspath(root) \
                    and _is_export_zip_name(name):
                continue
            full = os.path.join(r, name)
            arc = os.path.relpath(full, root).replace(os.sep, '/')
            yield full, arc


def _write_export_zip(out_dir):
    """出力フォルダ一式を kasugai_canvas_<tag>.zip として固める。

    ファイル名は CDN チャンネルを反映(export_zip_name)。
    展開時にルートへ .kasc+DATA/ が並ぶよう out_dir 相対パスで格納する
    (zip 自身は除外)。Re:Earth geo_suite の ``qgis:`` 取り込みは
    ZIP 内の .kasc を最短パス優先で検出するため、この配置で正しく解決する。
    """
    import zipfile
    zip_path = os.path.join(out_dir, export_zip_name())
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for full, arc in _iter_export_files(out_dir):
            zf.write(full, arc)
    return zip_path


def build_export_zip(out_dir=None):
    """エクスポート物一式を kasugai_canvas_<tag>.zip 相当の bytes で返す。

    /export-data/kasugai_canvas*.zip のオンデマンド生成用。
    ファイルは残さずメモリ上で固めて返すだけなので、内容は常に
    直近エクスポートの最新状態になる。
    """
    import io
    import zipfile
    root = os.path.abspath(out_dir or last_export_dir())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for full, arc in _iter_export_files(root):
            zf.write(full, arc)
    return buf.getvalue()


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
            'http://127.0.0.1:{0}/api/capabilities'.format(port),
            timeout=1.5)
        if isinstance(caps, dict):
            caps['_port'] = port
            return caps
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return None


def build_kasugai_url(project_id, engine=None, port=None):
    """KASUGAI Canvas のプロジェクトURLを構築する。

    engine 指定時は ``/<engine>/?project=<id>`` 形式
    (cesium/maplibre/openlayers/leaflet/gsimaps/navara の実パスを直接指す。
    web/index.html の ?engine= リダイレクトに依存しないため、
    旧バージョンの Canvas でも確実にそのエンジンが開く)。
    engine=None/無効値は既定(cesium)の ``/?project=<id>``。
    """
    port = int(port or get_kasugai_port())
    base = 'http://127.0.0.1:{0}'.format(port)
    e = normalize_engine(engine)
    if e:
        base += '/{0}/'.format(e)
    return '{0}?project={1}'.format(
        base, urllib.parse.quote(str(project_id)))


def register_kasugai_project(kasc_path, port=None, engine=None):
    """POST /api/projects/register で.kascを外部プロジェクト登録する。

    戻り値: {"ok":True,"id":...,"url":...} または {"ok":False,"error":...}
    engine 指定時は url が /<engine>/?project=<id> 形式になる。
    """
    port = int(port or get_kasugai_port())
    try:
        res = _http_json(
            'http://127.0.0.1:{0}/api/projects/register'.format(port),
            payload={'path': os.path.abspath(kasc_path)}, timeout=4.0)
        pid = res.get('id')
        if res.get('ok') and pid:
            return {'ok': True, 'id': pid,
                    'url': build_kasugai_url(pid, engine, port)}
        return {'ok': False, 'error': str(res)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def kasugai_command(name, args=None, port=None):
    """POST /api/command でチャットツールをキューイング(ベストエフォート)。"""
    port = int(port or get_kasugai_port())
    try:
        res = _http_json(
            'http://127.0.0.1:{0}/api/command'.format(port),
            payload={'name': name, 'args': args or {}}, timeout=4.0)
        return {'ok': bool(res.get('ok')), 'response': res}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def find_kasugai_exe():
    """起動可能な kasugai_canvas.exe のパスを返す（見つからなければ None）。

    detect_kasugai_install_dir()（設定→レジストリ）で特定した
    インストール先の ``<dir>/`` と ``<dir>/server/`` を見る。
    """
    install = detect_kasugai_install_dir()
    if not install:
        return None
    for cand in (os.path.join(install, KASUGAI_EXE_NAME),
                 os.path.join(install, 'server', KASUGAI_EXE_NAME)):
        if os.path.isfile(cand):
            return cand
    return None


def find_kasugai_web_dir():
    """インストール済み KASUGAI Canvas の配信用 ``web/`` ディレクトリを返す。

    Canvas サーバ(8510)未起動時に、geo_webview の HTTP サーバが
    エンジンHTMLを代わりに配信するフォールバックで使う。
    exe と同階層の ``web/`` を優先し、``<install>/web`` と
    ``<install>/server/web`` も見る。``web/index.html`` が存在する
    場合のみ絶対パスを返す（見つからなければ None）。
    """
    cands = []
    exe = find_kasugai_exe()
    if exe:
        cands.append(os.path.join(os.path.dirname(exe), 'web'))
    install = detect_kasugai_install_dir()
    if install:
        cands.append(os.path.join(install, 'web'))
        cands.append(os.path.join(install, 'server', 'web'))
    for cand in cands:
        if os.path.isfile(os.path.join(cand, 'index.html')):
            return os.path.abspath(cand)
    return None


def find_kasugai_engine_dir(engine=None):
    """インストール済みCanvas web/ 内の ``<engine>/`` ディレクトリを返す。

    マルチエンジン構成(web/cesium/等)のインストールのみ有効。
    旧単一エンジン構成(web/直下にapp.js)や engine ディレクトリが無い
    場合は None(?kasc= 再生不可のため hosted フォールバックへ回す)。
    """
    web = find_kasugai_web_dir()
    if not web:
        return None
    e = normalize_engine(engine) or DEFAULT_ENGINE
    d = os.path.join(web, e)
    if os.path.isfile(os.path.join(d, 'index.html')):
        return os.path.abspath(d)
    return None


def build_local_view_url(kasc_path, engine=None, port=None):
    """geo_webview の HTTP サーバ経由で .kasc を開くURLを組み立てる。

    Canvas サーバ(8510)未起動時のフォールバック用。
    ``http://localhost:<port>/<engine>/?kasc=<export-data配下URL>``。
    サーバ側でインストール済みCanvasの web/ 配信(エンドポイントに
    一致しなかったパスの静的解決)が有効なことが前提。
    kasc_path が last_export_dir() 配下に無い場合は None。
    """
    if not port:
        return None
    try:
        rel = os.path.relpath(kasc_path, last_export_dir())
    except ValueError:
        return None
    rel = rel.replace('\\', '/')
    if rel.startswith('..'):
        return None
    kasc_url = 'http://127.0.0.1:{0}/export-data/{1}'.format(
        int(port), urllib.parse.quote(rel))
    e = normalize_engine(engine) or DEFAULT_ENGINE
    return 'http://127.0.0.1:{0}/{1}/?kasc={2}'.format(
        int(port), e, urllib.parse.quote(kasc_url, safe=''))


def launch_kasugai(kasc_path=None, open_browser=False):
    """kasugai_canvas.exe を起動する。起動要求に成功すれば True。

    open_browser=False(既定)では ``--no-browser`` でサーバーのみ起動し、
    ブラウザは呼び出し側がエンジン付きURLで開く。open_browser=True または
    .kasc パス指定でのみ exe 既定挙動(ブラウザ自動起動)を利用する。
    """
    exe = find_kasugai_exe()
    if not exe:
        return False
    args = [exe]
    if not open_browser:
        args.append('--no-browser')
    if kasc_path:
        args.append(os.path.abspath(kasc_path))
    try:
        subprocess.Popen(  # nosec B603  # 固定exe・シェル非経由
            args, cwd=os.path.dirname(exe))
        return True
    except Exception as e:
        print(f'⚠️ KASUGAI launch failed: {e}')
        return False


def wait_for_kasugai(timeout=12.0, interval=0.3, pump_events=True):
    """起動直後のローカルサーバ応答を待つ。応答があれば capabilities。

    pump_events=True のとき待機中に Qt イベントを回して UI を固めない
    （GUI スレッドからの呼び出し用）。HTTP ハンドラ等の別スレッドでは
    False を指定すること。
    """
    deadline = time.time() + timeout
    while True:
        caps = detect_kasugai()
        if caps or time.time() >= deadline:
            return caps
        if pump_events:
            try:
                from qgis.PyQt.QtWidgets import QApplication
                app = QApplication.instance()
                if app is not None:
                    app.processEvents()
            except Exception:  # nosec B110  # 設計上の許容
                pass
        time.sleep(interval)


def open_kasc_with_association(kasc_path):
    """.kasc ファイル関連付け経由で Canvas 起動を要求する（Windows）。

    インストーラが ``.kasc → kasugai_canvas.exe --open-browser %1`` を
    登録済みなら起動できる。この経路は既定エンジンでブラウザが開く。
    起動要求ができれば True（起動完了は保証しない）。
    """
    if not kasc_path or not hasattr(os, 'startfile'):
        return False
    try:
        os.startfile(os.path.abspath(kasc_path))  # nosec B606
        return True
    except OSError:
        return False


def ensure_kasugai_running(kasc_path=None, timeout=12.0,
                           pump_events=True):
    """KASUGAI Canvas ローカルサーバを使える状態にして capabilities を返す。

    1. 既に稼働中 → そのまま返す
    2. インストール済み exe を発見 → ``--no-browser`` で起動して待機
       （ブラウザは呼び出し側がエンジン付きURLで開く）
    3. exe 不明・未インストール → kasc_path をファイル関連付けで開いて待機
       （この経路は既定エンジンのブラウザが exe 側で開かれる）

    戻り値は ``(capabilities or None, opened_default_browser)``。
    第2戻り値が True のとき、関連付け起動により既定エンジンのタブが
    既に開かれている可能性が高い（二重オープン防止に利用）。
    """
    caps = detect_kasugai()
    if caps:
        return caps, False
    if launch_kasugai():
        caps = wait_for_kasugai(
            timeout=timeout, pump_events=pump_events)
        if caps:
            return caps, False
    if open_kasc_with_association(kasc_path):
        caps = wait_for_kasugai(
            timeout=timeout, pump_events=pump_events)
        return caps, True
    return None, False


# ---- 自動インストール（配布ZIPのダウンロード・展開） ----

# 公開チャンネル(main)の配布物を参照する
KASUGAI_LATEST_JSON_URL = (
    'https://raw.githubusercontent.com/yamamoto-ryuzo/kasugai_canvas'
    '/main/download/latest.json')
KASUGAI_ZIP_FALLBACK_URL = (
    'https://raw.githubusercontent.com/yamamoto-ryuzo/kasugai_canvas'
    '/main/download/kasugai_canvas.zip')


def kasugai_download_url():
    """latest.json から配布ZIPのURLを返す（取得失敗時は既定URL）。"""
    try:
        meta = _http_json(KASUGAI_LATEST_JSON_URL, timeout=5.0)
        url = ((meta.get('platforms') or {})
               .get('windows-x86_64') or {}).get('url')
        if url and str(url).startswith('https://'):
            return url
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return KASUGAI_ZIP_FALLBACK_URL


def default_install_dir():
    r"""既定インストール先。インストーラ既定の C:\kasugai\kasugai_canvas
    を優先し、作成できなければ %LOCALAPPDATA%\kasugai_canvas。"""
    if os.name == 'nt':
        cand = r'C:\kasugai\kasugai_canvas'
        try:
            os.makedirs(cand, exist_ok=True)
            return cand
        except OSError:
            pass
    import tempfile
    base = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
    return os.path.join(base, 'kasugai_canvas')


def _safe_extractall(zf, dest_dir):
    """zip-slip 対策付き extractall。"""
    dest = os.path.abspath(dest_dir)
    for member in zf.namelist():
        target = os.path.abspath(os.path.join(dest, member))
        if not (target == dest or target.startswith(dest + os.sep)):
            raise RuntimeError('unsafe path in archive: {0}'.format(member))
    zf.extractall(dest)


def _download(url, tmp, progress_cb=None, cancel=None):
    """url を tmp へダウンロードする。

    progress_cb(stage, done, total) が渡されていれば
    ('download', 済みバイト, 総バイト) で進捗を逐次通知する
    (総バイト不明時は total=0)。cancel['cancelled'] が真なら中断する。
    """
    if urllib.parse.urlparse(url).scheme != 'https':
        raise ValueError('download URL must be https: {0}'.format(url))
    req = urllib.request.Request(
        url, headers={'User-Agent': 'geo_webview'})
    with (urllib.request.urlopen(req, timeout=300) as res,  # nosec B310  # 直上でhttpsスキームを検証済み
            open(tmp, 'wb') as out):
        try:
            total = int(res.headers.get('Content-Length') or 0)
        except Exception:  # nosec B110  # 設計上の許容
            total = 0
        done = 0
        while True:
            if cancel and cancel.get('cancelled'):
                raise RuntimeError('install cancelled by user')
            chunk = res.read(1 << 18)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb('download', done, total)


def install_kasugai(dest_dir=None, progress_cb=None, cancel=None):
    """KASUGAI Canvas の配布ZIPをダウンロード・展開してインストール先を返す。

    dest_dir 既定は default_install_dir()。成功時は
    ``kasugai_install_path`` 設定へ自動登録する。
    progress_cb(stage, done, total) で進捗通知
    ('download'/'extract')。
    失敗時は例外を送出（呼び出し側でキャッチして通知する）。
    ブロッキングするため GUI スレッドではタスク経由で呼ぶこと。
    """
    import tempfile
    import zipfile
    dest_dir = os.path.abspath(dest_dir or default_install_dir())
    url = kasugai_download_url()
    fd, tmp = tempfile.mkstemp(suffix='.zip', prefix='kasugai_canvas_')
    os.close(fd)
    try:
        _download(url, tmp, progress_cb, cancel)
        if cancel and cancel.get('cancelled'):
            raise RuntimeError('install cancelled by user')
        if progress_cb:
            progress_cb('extract', 0, 0)
        os.makedirs(dest_dir, exist_ok=True)
        with zipfile.ZipFile(tmp) as zf:
            _safe_extractall(zf, dest_dir)
    finally:
        try:
            os.remove(tmp)
        except OSError:  # nosec B110  # 設計上の許容
            pass
    exe = os.path.join(dest_dir, KASUGAI_EXE_NAME)
    if not os.path.isfile(exe):
        raise RuntimeError(
            'kasugai_canvas.exe not found in downloaded archive')
    try:
        _qsettings().setValue('kasugai_install_path', dest_dir)
    except Exception:  # nosec B110  # 設計上の許容
        pass
    return dest_dir


KASUGAI_SETUP_FALLBACK_URL = (
    'https://raw.githubusercontent.com/yamamoto-ryuzo/kasugai_canvas'
    '/main/download/kasugai_canvas_setup.exe')


def kasugai_setup_url():
    """配布セットアップ(NSIS EXE)のURLを返す。

    ZIPと同じ配布ディレクトリの kasugai_canvas_setup.exe を指す
    (latest.json はZIPのみ公開するため basename 置換で求める)。
    """
    base = kasugai_download_url().split('?')[0].rsplit('/', 1)[0]
    if base.startswith(('https://', 'http://')):
        return base + '/kasugai_canvas_setup.exe'
    return KASUGAI_SETUP_FALLBACK_URL


def install_kasugai_setup(wait=True, progress_cb=None, cancel=None):
    """NSIS セットアップをダウンロード・実行する通常インストール経路。

    ポータブルZIP展開(install_kasugai)と違い、.kasc ファイル関連付け・
    スタートメニュー/アンインストーラ登録・InstallLocation レジストリ
    登録が行われる。NSIS ウィザードを対話表示し、wait=True で
    インストーラ終了まで待機する(ブロッキングのため GUI スレッドでは
    タスク経由で呼ぶこと)。終了後は InstallLocation レジストリから
    実インストール先を検出し kasugai_install_path へ登録する。
    progress_cb(stage, done, total) で進捗通知
    ('download'/'wizard')。cancel['cancelled'] が真なら
    DL中は中断、ウィザード待機中はプロセスを終了して中断する。
    ユーザがウィザードをキャンセルした場合は exe 不在で例外となる。
    """
    import tempfile
    import time
    url = kasugai_setup_url()
    fd, tmp = tempfile.mkstemp(
        suffix='.exe', prefix='kasugai_canvas_setup_')
    os.close(fd)
    try:
        _download(url, tmp, progress_cb, cancel)
        if progress_cb:
            progress_cb('wizard', 0, 0)
        proc = subprocess.Popen([tmp])  # nosec B603  # 自前配布物のみ
        if wait:
            # ×キャンセル時にウィザードプロセスを終了して抜ける
            while proc.poll() is None:
                if cancel and cancel.get('cancelled'):
                    try:
                        proc.kill()
                    except OSError:  # nosec B110  # 設計上の許容
                        pass
                    raise RuntimeError('install cancelled by user')
                time.sleep(0.5)
        dest = _registry_install_dir() or default_install_dir()
        exe = os.path.join(dest, KASUGAI_EXE_NAME)
        if not os.path.isfile(exe):
            raise RuntimeError(
                'setup wizard finished but {0} was not found — '
                'installation cancelled or the wizard was blocked'.format(
                    KASUGAI_EXE_NAME))
        try:
            _qsettings().setValue('kasugai_install_path', dest)
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return dest
    finally:
        try:
            os.remove(tmp)
        except OSError:  # nosec B110  # 設計上の許容
            pass
