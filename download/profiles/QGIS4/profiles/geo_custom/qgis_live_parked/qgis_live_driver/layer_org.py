"""レイヤ整理サービス(LayerOrganizer)。

プラグインをまたいだ「追加レイヤの表示標準化」を担う。
geo_import 等が追加したレイヤを、プロファイルJSONのルールに従って
レイヤツリーのグループへ移動・リネーム・スタイル適用する。

配置(agents/skills と同じ 同梱デフォルト+ユーザ上書き パターン):
  同梱   : <plugin>/layer_org/*.json    (読み取り専用デフォルト)
  ユーザ : ~/.qgis-live/layer_org/*.json (QGIS_LIVE_REGISTRY準拠、同名優先)

アクティブプロファイルは QSettings "qgis_live_driver/layer_org/profile"
(stem名、既定 "default")。

プロファイルJSONスキーマ:
  {
    "name": "default",              // 表示名(省略時=ファイルstem)
    "description": "...",           // 用途メモ
    "root": "取込データ",            // 全グループの親(省略時=ツリー直下)
    "enabled": true,                // false で整理を無効化
    "rules": [                      // 先勝ち。全キーAND一致
      {"match": {"format": ["wms","wmts","xyz"],   // ctxのリソースformatまたは拡張子
                 "ext": ["shp","gpkg"],            // レイヤソースの拡張子
                 "provider": ["wms","ogr"],        // layer.providerType()
                 "layer_type": ["vector","raster","mesh","pointcloud"],
                 "geom": ["point","line","polygon","none","unknown"],
                 "plugin": ["geo_import"],         // ctxの呼出元プラグインid
                 "name_re": "正規表現",            // レイヤ名/リソース名にsearch
                 "dataset_re": "正規表現",         // ctxのデータセット名にsearch
                 "url_re": "正規表現"},            // リソースURL/レイヤソースにsearch
       "group": "背景/サービス",     // '/'区切りのグループパス(root配下)
       "rename": "{dataset} - {resource}",        // 省略可。{name}{format}{ext}{provider}も可
       "style": "styles/foo.qml",   // 省略可。プロファイルdir相対または絶対.qml
       "top": true}                 // 省略可。グループ先頭に挿入(既定=末尾)
    ],
    "fallback": "その他"             // どのルールにも合わない時のgroup(省略時=移動しない)
  }

GUIスレッド前提のQGIS操作は全てメソッド内importに閉じ込め、
このモジュール自体は stdlib のみでimport可能(unit test対象)。
"""

import json
import os
import re

_SETTING_PROFILE = "qgis_live_driver/layer_org/profile"
_DEFAULT_PROFILE = "default"


def _registry_dir():
    return os.environ.get(
        "QGIS_LIVE_REGISTRY",
        os.path.join(os.path.expanduser("~"), ".qgis-live"))


def profiles_dir():
    """ユーザ定義プロファイル置き場 ~/.qgis-live/layer_org/。"""
    return os.path.join(_registry_dir(), "layer_org")


def _bundled_dir():
    """プラグイン同梱のデフォルトプロファイル dir。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "layer_org")


def _as_list(v):
    return list(v) if isinstance(v, (list, tuple)) else [v]


def list_profiles():
    """利用可能なプロファイル一覧。[{id,name,description,builtin,path}]。

    bundled→user の順に走査し、同名(stem)はユーザ側が上書き。
    """
    out = {}
    for d, builtin in ((_bundled_dir(), True), (profiles_dir(), False)):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith(".json"):
                continue
            stem = f[:-5]
            if not builtin or stem not in out:
                p = os.path.join(d, f)
                name, desc = stem, ""
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        meta = json.load(fh)
                    name = meta.get("name") or stem
                    desc = meta.get("description") or ""
                except Exception:  # nosec B110  # 設計上の許容
                    pass
                out[stem] = {"id": stem, "name": name, "description": desc,
                             "path": p, "builtin": builtin}
    return [out[k] for k in sorted(out)]


def load_profile(name):
    """プロファイルid → (dict, path)。見つからなければ (None, None)。"""
    for p in list_profiles():
        if p["id"] == name:
            try:
                with open(p["path"], "r", encoding="utf-8") as f:
                    prof = json.load(f)
            except Exception:
                return None, None
            prof["_path"] = p["path"]
            prof["_dir"] = os.path.dirname(p["path"])
            prof["id"] = name
            return prof, p["path"]
    return None, None


# ---- レイヤ属性の抽出(QGIS依存は関数内に閉じ込める) ----

_SOURCE_SPLIT_RE = re.compile(r"[|?]")


def _layer_ext(source):
    """レイヤソース文字列から拡張子を推定する(先頭のパス部のみ見る)。"""
    if not source:
        return ""
    head = _SOURCE_SPLIT_RE.split(source, 1)[0]
    # URIパラメータ型(url=...)はファイル拡張子を持たない
    if "=" in os.path.basename(head):
        return ""
    ext = os.path.splitext(head)[1]
    return ext.lstrip(".").lower()


def layer_attrs(layer, ctx=None):
    """ルール照合用の属性dictをレイヤ+コンテキストから作る。

    ctxキー(呼出元が付与): plugin_id / dataset / dataset_id /
    resource / resource_id / format / url / file / tags
    """
    ctx = dict(ctx or {})
    attrs = {"ctx": ctx}
    try:
        attrs["name"] = layer.name() or ""
    except Exception:
        attrs["name"] = ""
    try:
        attrs["provider"] = (layer.providerType() or "").lower()
    except Exception:
        attrs["provider"] = ""
    # QgsMapLayerType: 0 vector 1 raster 2 plugin 3 mesh
    #                4 vector_tile 5 pointcloud 6 annotation 7 group 8 3d
    try:
        lt = int(layer.type())
        attrs["layer_type"] = {
            0: "vector", 1: "raster", 2: "plugin", 3: "mesh",
            4: "vector_tile", 5: "pointcloud", 6: "annotation",
            7: "group", 8: "3d",
        }.get(lt, "other")
    except Exception:
        attrs["layer_type"] = "other"
    geom = "none"
    if attrs["layer_type"] == "vector":
        try:
            from qgis.core import QgsWkbTypes
            gt = int(QgsWkbTypes.geometryType(layer.wkbType()))
            geom = {0: "point", 1: "line", 2: "polygon"}.get(gt, "unknown")
        except Exception:
            geom = "unknown"
    attrs["geom"] = geom
    src = ""
    try:
        src = layer.source() or ""
    except Exception:  # nosec B110  # 設計上の許容
        pass
    attrs["source"] = src
    ext = _layer_ext(str(ctx.get("file") or "")) \
        or _layer_ext(src)
    attrs["ext"] = ext
    attrs["format"] = str(ctx.get("format") or "").strip().lower() \
        or ext
    attrs["url"] = str(ctx.get("url") or src or "")
    return attrs


def match_rule(rules, attrs):
    """ルール配列を先頭から評価し、最初に一致したルールを返す。

    rule["match"] の全キーが一致でAND。matchが空/欠落なら常時一致。
    """
    for i, rule in enumerate(rules or []):
        m = rule.get("match") or {}
        if _match_all(m, attrs):
            return i, rule
    return None, None


def _match_all(m, attrs):
    ctx = attrs.get("ctx") or {}
    for key, want in m.items():
        if key == "format":
            cand = {attrs.get("format", ""), attrs.get("ext", "")}
            if not {str(w).lower() for w in _as_list(want)} & cand:
                return False
        elif key == "ext":
            if attrs.get("ext", "") not in \
                    {str(w).lower().lstrip(".") for w in _as_list(want)}:
                return False
        elif key == "provider":
            if attrs.get("provider", "") not in \
                    {str(w).lower() for w in _as_list(want)}:
                return False
        elif key == "layer_type":
            if attrs.get("layer_type", "") not in \
                    {str(w).lower() for w in _as_list(want)}:
                return False
        elif key == "geom":
            if attrs.get("geom", "") not in \
                    {str(w).lower() for w in _as_list(want)}:
                return False
        elif key == "plugin":
            if str(ctx.get("plugin_id") or "") not in \
                    {str(w) for w in _as_list(want)}:
                return False
        elif key == "name_re":
            text = "\n".join([attrs.get("name", ""),
                              str(ctx.get("resource") or "")])
            if not re.search(str(want), text):
                return False
        elif key == "dataset_re":
            if not re.search(str(want),
                             str(ctx.get("dataset") or "")):
                return False
        elif key == "url_re":
            if not re.search(str(want), attrs.get("url", "")):
                return False
        elif key == "tags":
            tags = {str(t).lower() for t in _as_list(ctx.get("tags") or [])}
            if not {str(w).lower() for w in _as_list(want)} & tags:
                return False
        else:
            return False   # 未定義キーはマッチ失敗(設定ミスを沈黙させない)
    return True


def render_template(tpl, attrs):
    """renameテンプレートの {token} を属性値で置換する。"""
    ctx = attrs.get("ctx") or {}
    mapping = {
        "name": attrs.get("name", ""),
        "provider": attrs.get("provider", ""),
        "ext": attrs.get("ext", ""),
        "format": attrs.get("format", ""),
        "layer_type": attrs.get("layer_type", ""),
        "geom": attrs.get("geom", ""),
        "plugin": ctx.get("plugin_id") or "",
        "dataset": ctx.get("dataset") or "",
        "resource": ctx.get("resource") or "",
        "url": ctx.get("url") or "",
    }

    def _sub(mo):
        return str(mapping.get(mo.group(1), mo.group(0)))

    return re.sub(r"\{([a-z_]+)\}", _sub, str(tpl)).strip()


class LayerOrganizer:
    """追加レイヤをプロファイルのルールでレイヤツリーへ整理する。

    他プラグインからは plugins['qgis_live_driver'].layer_org.place_all()
    で呼ぶ。ドライバ不在・プロファイル無効時は呼び出し側が従来動作へ
    フォールバックできるよう、ここでは静かにno-opレポートを返す。
    """

    # ---------- プロファイル解決 ----------

    def active_profile_name(self):
        try:
            from qgis.PyQt.QtCore import QSettings
            v = QSettings().value(_SETTING_PROFILE, _DEFAULT_PROFILE)
            return str(v or _DEFAULT_PROFILE)
        except Exception:
            return _DEFAULT_PROFILE

    def set_active_profile(self, name):
        prof, _ = load_profile(str(name or ""))
        if prof is None:
            return {"ok": False,
                    "error": f"profile not found: {name}",
                    "profiles": [p["id"] for p in list_profiles()]}
        try:
            from qgis.PyQt.QtCore import QSettings
            QSettings().setValue(_SETTING_PROFILE, str(name))
        except Exception:  # nosec B110  # 設計上の許容
            pass
        return {"ok": True, "active": str(name)}

    def profile(self, name=None):
        """プロファイルdictを返す(未指定=アクティブ)。無効/不在はNone。"""
        prof, _ = load_profile(name or self.active_profile_name())
        if prof is None or prof.get("enabled") is False:
            return None
        return prof

    # ---------- 整理本体 ----------

    def place_all(self, items, profile_name=None, dry=False):
        """items=[(layer, ctx)|layer, ...] をルール適用で配置する。

        @returns {"profile": id, "enabled": bool,
                  "placed": [...], "skipped": [...]}
        """
        prof = self.profile(profile_name)
        entries, skipped = [], []
        pid = (prof or {}).get("id")
        for it in items:
            if isinstance(it, tuple):
                layer, ctx = it
            else:
                layer, ctx = it, {}
            try:
                entries.append(self.place(layer, ctx, prof, dry=dry))
            except Exception as e:
                skipped.append({"error": repr(e)})
        return {"profile": pid, "enabled": prof is not None,
                "placed": entries, "skipped": skipped}

    def place(self, layer, ctx=None, prof=None, dry=False):
        """1レイヤをルール適用で配置し、結果エントリを返す。"""
        attrs = layer_attrs(layer, ctx)
        entry = {"layer": attrs.get("name"), "attrs": {
            k: attrs[k] for k in
            ("provider", "layer_type", "geom", "ext", "format")}}
        if prof is None:
            entry["action"] = "disabled"
            return entry
        idx, rule = match_rule(prof.get("rules"), attrs)
        group_path = None
        if rule is not None:
            entry["rule"] = idx
            group_path = rule.get("group")
        elif prof.get("fallback"):
            entry["rule"] = "fallback"
            group_path = prof["fallback"]
        if group_path:
            root = prof.get("root")
            full = f"{root}/{group_path}" if root else group_path
            entry["group"] = full
            if not dry:
                top = bool(rule and rule.get("top"))
                group = self._ensure_group(full)
                self._move_to_group(layer, group, top=top)
                if rule and rule.get("collapsed"):
                    try:
                        group.setExpanded(False)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
        else:
            entry["action"] = "no-match"
            return entry
        if rule and rule.get("rename"):
            new_name = render_template(rule["rename"], attrs)
            if new_name:
                entry["renamed"] = new_name
                if not dry:
                    try:
                        layer.setName(new_name)
                        # 既に置かれたツリーノード側も追随
                        self._rename_node(layer, new_name)
                    except Exception:  # nosec B110  # 設計上の許容
                        pass
        if rule and rule.get("style"):
            style = rule["style"]
            if not os.path.isabs(style):
                style = os.path.join(prof.get("_dir") or "", style)
            entry["style"] = style
            if not dry:
                try:
                    layer.loadNamedStyle(style)
                    layer.triggerRepaint()
                except Exception:  # nosec B110  # 設計上の許容
                    pass
        entry["action"] = "dry" if dry else "placed"
        return entry

    def organize_project(self, profile_name=None, dry=False):
        """プロジェクト内の全レイヤを再整理する(冪等)。

        コンテキストが無いため format/plugin/tags 等のctxキーには
        レイヤ由来の値だけが使われる。
        """
        from qgis.core import QgsProject
        items = [(ly, {}) for ly in QgsProject.instance().mapLayers().values()]
        return self.place_all(items, profile_name=profile_name, dry=dry)

    def describe(self, name=None):
        """bridge表示用のプロファイル要約。"""
        prof, path = load_profile(name or self.active_profile_name())
        if prof is None:
            return None
        return {
            "id": prof.get("id"), "name": prof.get("name"),
            "description": prof.get("description"),
            "path": path, "root": prof.get("root"),
            "enabled": prof.get("enabled") is not False,
            "fallback": prof.get("fallback"),
            "rules": [{"match": r.get("match") or {},
                       "group": r.get("group"),
                       "rename": r.get("rename"),
                       "style": r.get("style")}
                      for r in prof.get("rules") or []],
        }

    # ---------- レイヤツリー操作(QGIS依存) ----------

    def _ensure_group(self, path):
        """'/'区切りのパスを辿ってグループを作成し末端を返す。"""
        from qgis.core import QgsLayerTree, QgsProject
        parent = QgsProject.instance().layerTreeRoot()
        for part in [p for p in str(path).split("/") if p]:
            nxt = None
            for ch in parent.children():
                if QgsLayerTree.isGroup(ch) and ch.name() == part:
                    nxt = ch
                    break
            if nxt is None:
                nxt = parent.addGroup(part)
            parent = nxt
        return parent

    @staticmethod
    def _move_to_group(layer, group, top=False):
        """レイヤのツリーノードを指定グループへ移動する。

        同一レイヤのノードは複数存在し得るため、元ノードのcloneを
        グループへ挿入してから元ノードを除去する(所有権の問題を避ける)。
        ノードが無い(addToLegend=False等)場合は直接追加する。
        """
        from qgis.core import QgsProject
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer.id())
        if node is None:
            group.addLayer(layer)
            return
        parent = node.parent()
        if parent is group:
            return
        new_node = node.clone()
        parent.removeChildNode(node)
        group.insertChildNode(0 if top else -1, new_node)

    @staticmethod
    def _rename_node(layer, new_name):
        from qgis.core import QgsLayerTree, QgsProject
        node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if node is not None and QgsLayerTree.isLayer(node):
            try:
                node.setName(new_name)
            except Exception:  # nosec B110  # 設計上の許容
                pass
