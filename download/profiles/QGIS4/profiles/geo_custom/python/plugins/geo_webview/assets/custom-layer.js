// custom-layer — 「site」キーで複数レイヤを任意グループにまとめて
// 一括制御するカスタムレイヤパネル。
//
// .kasc のレイヤ行に site=<グループ名> を付けると、その名ごとに
// グループ化されて表示される。Cesium では標準レイヤタブと同じ
// DOM 構造・クラス（layer-group / layer-item / layer-row /
// layer-legend-items）で描画するため、画面構成・文字サイズ・
// 行高・凡例の開閉が標準タブと同一になる。
// site= はこのタブ専用の集約キーで、標準レイヤタブには全レイヤが従来通り
// 表示される（標準一覧から隠すには list=off を使う）。list=off のレイヤは
// 「一覧から除外」なのでこのタブにも表示しない。site= 無しレイヤは
// このタブ末尾の「その他」に集約されて一括 on/off できる。
// メンバー内の表示順は order=<数値> で指定できる。
// 凡例の並びは legend_order=asc|desc|reverse またはカンマ区切りの
// ラベル列挙(legend_order=区分A,区分C,区分B。未列挙は末尾・元順維持)
// で変更できる。未指定は .qml のシンボル順。
// タブ名(name=)が組み込みタブと重複する場合、組み込み側は自動的に
// 「システムレイヤ」等に改称される。
// 同時に「フィルタ」タブも登録する — site 単位の共通属性で全メンバー
// レイヤへ where= 式を一括適用/解除する(QGIS WEBVIEW の Filter タブと
// 同じ構成。setLayerFilter/getLayerGeoJson 非対応エンジンでは出ない)。
//
//   geojson: A工区・ポリゴン | canvas_data/a-poly.geojson | site=A工区 | order=1
//   geojson: A工区・ライン   | canvas_data/a-line.geojson | site=A工区 | order=2
//   geojson: A工区・ポイント | canvas_data/a-pt.geojson   | site=A工区 | order=3
//   plugin: custom-layer | name=レイヤ | url=canvas_data/custom-layer.js | before=layers-panel
//
// manifest.options.key で集約キー名を変えられる（既定 "site"）。

export async function init(api, manifest) {
  const KEY = manifest.options?.key || "site";
  const MISC = "その他";
  const groupCollapsed = new Set();  // site 名ごとの折りたたみ状態
  const legendCollapsed = new Set(); // レイヤ id ごとの凡例折りたたみ
  const style = document.createElement("style");
  style.textContent = `
    .sc-count { color: #778; font-weight: 400; font-size: 0.85em; }
    .sc-empty { padding: 8px; color: #778; font-size: 0.9em; }
    .sc-title { display: flex; align-items: center; gap: 5px;
      min-height: 16px; padding: 1px 7px 1px 4px; line-height: 1;
      font-weight: 700; }
    .sc-title input { width: 15px; min-height: 15px; margin: 0; }
    .sc-label { flex: 1; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; cursor: pointer; }
    .sc-legend { display: flex; align-items: center; gap: 5px;
      min-height: 16px; line-height: 1; }
    .sc-legend input { width: 14px; min-height: 14px; margin: 0; }
    .sc-legend .sw { width: 16px; height: 16px; display: inline-block; }
    .sc-legend img { width: 16px; height: 16px; }
    .sc-legend .lb { flex: 1; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; }
    .sc-legend-toggle { flex: 0 0 auto; width: 14px; min-width: 14px;
      min-height: 16px; margin-right: -4px; padding: 0; border: 0;
      background: transparent; color: #52636d; font-size: 11px;
      line-height: 1; cursor: pointer; }
    .sc-legend-focus { flex: 0 0 auto; width: 24px; min-width: 24px;
      min-height: 16px; padding: 0; border: 0; background: transparent;
      font-size: 15px; line-height: 1; opacity: .7; cursor: pointer; }
    .sc-legend-focus:hover { opacity: 1; }
  `;

  // 現在の一覧順(先頭=最前面)を保ったまま site キーで集約。
  // メンバーは order=<数値> があればその順、無ければ現在順。
  // キー無しレイヤは末尾に「その他」としてまとめて一括制御する
  const collect = () => {
    const map = new Map();
    const misc = [];
    for (const l of api.listLayers() || []) {
      if (l.options?.list === "off") continue; // list=off は一覧に出さない
      const k = l.options?.[KEY];
      if (!k) { misc.push(l); continue; }
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(l);
    }
    const sites = [...map.entries()].map(([name, members]) => ({
      name,
      members: [...members].sort((a, b) =>
        (Number(a.options?.order) || 1e9) - (Number(b.options?.order) || 1e9)),
    }));
    if (misc.length) sites.push({ name: MISC, members: misc, misc: true });
    return sites;
  };

  const swatch = (e, cls) => {
    const url = e?.spec && api.legendSwatchUrl
      ? api.legendSwatchUrl(e.spec) : null;
    if (url) {
      const img = document.createElement("img");
      img.className = "legend-swatch";
      img.src = url;
      img.alt = "";
      return img;
    }
    const sp = document.createElement("span");
    sp.className = `legend-swatch legend-swatch-empty`;
    return sp;
  };

  // 標準タブの凡例項目と同じ構造:
  // <label class="legend-row"><input.legend-checkbox><img.legend-swatch><span.legend-label>
  const legendEntry = (m, e) => {
    const row = document.createElement("label");
    row.className = "legend-row";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "legend-checkbox";
    cb.checked = e.visible !== false;
    cb.disabled = !e.symbolName || !api.setLayerLegendVisible;
    cb.addEventListener("change",
      () => api.setLayerLegendVisible?.(
        m.id, e.symbolName || e.label, cb.checked));
    const lb = document.createElement("span");
    lb.className = "legend-label";
    lb.textContent = e.label || e.symbolName || "";
    row.append(cb, swatch(e), lb);
    return row;
  };

  // 凡例の並び順: legend_order=asc|desc|reverse または
  // カンマ区切りのラベル列挙(未列挙は末尾・元順維持)
  const sortLegendEntries = (m, entries) => {
    const spec = String(m.options?.legend_order || "").trim();
    if (!spec || entries.length < 2) return entries;
    const key = e => String(e.label || e.symbolName || "");
    if (spec === "reverse") return [...entries].reverse();
    if (spec === "asc" || spec === "desc") {
      const s = [...entries].sort(
        (a, b) => key(a).localeCompare(key(b), "ja"));
      return spec === "desc" ? s.reverse() : s;
    }
    const pos = new Map(
      spec.split(",").map((t, i) => [t.trim(), i]));
    const idx = e => pos.has(key(e)) ? pos.get(key(e)) : 1e9;
    return [...entries].sort((a, b) => idx(a) - idx(b));
  };

  // 標準タブの .layer-item と同じ構造:
  // <label class="layer-row">[toggle|spacer][cb][swatch][title][📍]
  // 複数シンボルは .layer-legend-items(開閉可)の凡例行を子に持つ
  const memberItem = m => {
    const item = document.createElement("div");
    item.className = "layer-item";
    const row = document.createElement("label");
    row.className = "layer-row";
    const entries = sortLegendEntries(m, m.legend || []);
    const multi = entries.length > 1;
    let items = null;
    if (multi) {
      items = document.createElement("div");
      items.className = "layer-legend-items";
      items.hidden = legendCollapsed.has(m.id);
      for (const e of entries) items.appendChild(legendEntry(m, e));
      const tgl = document.createElement("button");
      tgl.type = "button";
      tgl.className = "layer-legend-toggle";
      const collapsed = legendCollapsed.has(m.id);
      tgl.textContent = collapsed ? "▸" : "▾";
      tgl.setAttribute("aria-expanded", String(!collapsed));
      tgl.addEventListener("click", ev => {
        ev.preventDefault();
        ev.stopPropagation();
        const now = !items.hidden;
        items.hidden = now;
        tgl.textContent = now ? "▸" : "▾";
        tgl.setAttribute("aria-expanded", String(!now));
        if (now) legendCollapsed.add(m.id);
        else legendCollapsed.delete(m.id);
      });
      row.appendChild(tgl);
    } else {
      const sp = document.createElement("span");
      sp.className = "layer-legend-toggle-spacer";
      sp.setAttribute("aria-hidden", "true");
      row.appendChild(sp);
    }
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!m.visible;
    cb.addEventListener("change",
      () => api.setLayerVisible(m.id, cb.checked));
    row.appendChild(cb);
    if (entries.length === 1) row.appendChild(swatch(entries[0]));
    const title = document.createElement("span");
    title.textContent = m.title;
    row.appendChild(title);
    if (api.focusLayer) {
      const focus = document.createElement("button");
      focus.type = "button";
      focus.className = "layer-focus";
      focus.title = "フォーカス";
      focus.textContent = "📍";
      focus.addEventListener("click", ev => {
        ev.preventDefault();
        ev.stopPropagation();
        void api.focusLayer(m.id);
      });
      row.appendChild(focus);
    }
    item.appendChild(row);
    if (items) item.appendChild(items);
    return item;
  };

  // 標準タブの <section class="layer-group grouped"> と同じ構造:
  // .layer-group-title(toggle+group checkbox+label) + .layer-group-children
  const siteSection = site => {
    const sec = document.createElement("section");
    sec.className = "layer-group grouped";
    const collapsed = groupCollapsed.has(site.name);
    const title = document.createElement("div");
    title.className = "layer-group-title";
    const tgl = document.createElement("button");
    tgl.type = "button";
    tgl.className = "layer-group-toggle";
    tgl.textContent = collapsed ? "▸" : "▾";
    tgl.setAttribute("aria-expanded", String(!collapsed));
    const children = document.createElement("div");
    children.className = "layer-group-children";
    children.hidden = collapsed;
    tgl.addEventListener("click", () => {
      const now = !children.hidden;
      children.hidden = now;
      tgl.textContent = now ? "▸" : "▾";
      tgl.setAttribute("aria-expanded", String(!now));
      if (now) groupCollapsed.add(site.name);
      else groupCollapsed.delete(site.name);
    });
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "layer-group-checkbox";
    const visCount = site.members.filter(m => m.visible).length;
    cb.checked = visCount === site.members.length;
    cb.indeterminate = visCount > 0 && visCount < site.members.length;
    cb.addEventListener("change", () => {
      for (const m of site.members) api.setLayerVisible(m.id, cb.checked);
    });
    const label = document.createElement("label");
    label.className = "layer-group-label";
    label.textContent = site.name;
    label.title = site.members.map(m => m.title).join(" ／ ");
    const count = document.createElement("span");
    count.className = "sc-count";
    count.textContent = `(${site.members.length})`;
    label.appendChild(count);
    title.append(tgl, cb, label);
    for (const m of site.members) children.appendChild(memberItem(m));
    sec.append(title, children);
    return sec;
  };

  // 非 Cesium エンジン向けの簡易フォールバック(lv-*/sc-* クラス)
  const fallbackSection = site => {
    const wrap = document.createElement("div");
    const row = document.createElement("div");
    row.className = "lv-group-title sc-title";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    const visCount = site.members.filter(m => m.visible).length;
    cb.checked = visCount === site.members.length;
    cb.indeterminate = visCount > 0 && visCount < site.members.length;
    cb.addEventListener("change", () => {
      for (const m of site.members) api.setLayerVisible(m.id, cb.checked);
    });
    const label = document.createElement("span");
    label.className = "lv-title sc-label";
    label.textContent = `${site.name} (${site.members.length})`;
    label.title = site.members.map(m => m.title).join(" ／ ");
    row.append(cb, label);
    wrap.appendChild(row);
    for (const m of site.members) {
      const mr = document.createElement("label");
      mr.className = "sc-legend";
      const mcb = document.createElement("input");
      mcb.type = "checkbox";
      mcb.checked = !!m.visible;
      mcb.addEventListener("change",
        () => api.setLayerVisible(m.id, mcb.checked));
      const ml = document.createElement("span");
      ml.className = "lb";
      ml.textContent = m.title;
      mr.append(mcb, ml);
      if (api.focusLayer) {
        const f = document.createElement("button");
        f.type = "button";
        f.className = "sc-legend-focus";
        f.textContent = "📍";
        f.addEventListener("click",
          ev => { ev.preventDefault(); void api.focusLayer(m.id); });
        mr.append(f);
      }
      wrap.appendChild(mr);
    }
    return wrap;
  };

  // ---- サイト共通フィルタ(「フィルタ」タブ) --------------------------
  // QGIS WEBVIEW の Filter タブと同じ構成: site(=集約キー)単位で
  // 全メンバーレイヤに共通する属性を選び、where= 式を一括適用する。
  //   数値フィールド → 演算子(= != < <= > >=) + 数値入力
  //   その他         → = / != + 既存値入力(候補リスト付き)
  //   複数選択       → IN / NOT IN + 既存値チェックリスト(数値も可)
  // where= は where-eval.js の OGR SQL WHERE 句として評価される。
  // ※ NOT IN は where-eval が中置 NOT 非対応のため NOT (… IN (…)) で出す

  // where= を受け付けるベクター型(sql:/ogrsql: はクエリ全文型なので除外)
  const FILTER_VECTOR_TYPES = new Set([
    "geojson", "layer", "geoparquet", "parquet", "flatgeobuf", "fgb",
    "gpkg", "geopackage", "csv", "tsv", "duckdb", "kml", "kmz", "gpx",
    "czml", "topojson", "esrijson", "arcgis", "geojsonl", "ndjson",
    "jsonl", "geojsonseq", "fgseq", "geojson-seq", "wkt", "wkb", "igc",
    "polyline", "gml", "wfs", "shp", "shapefile",
  ]);
  // geojsonSource/_geojson が where= 適用前の全件を保持する型
  // (それ以外はフィルタ済みになるため、値列挙時に一時解除→復元する)
  const FULL_SOURCE_TYPES = new Set(["geojson", "layer", "entities"]);
  // FlatGeobuf ヘッダ columns の数値型
  const NUMERIC_COL_TYPES = new Set([
    "Byte", "UByte", "Short", "UShort", "Int", "UInt",
    "Long", "ULong", "Float", "Double",
  ]);

  // list=off も含めて site ごとのフィルタ対象メンバーを集約
  const filterSites = () => {
    const map = new Map();
    const misc = [];
    for (const l of api.listLayers() || []) {
      if (!FILTER_VECTOR_TYPES.has(l.type)) continue;
      const k = l.options?.[KEY];
      if (!k) { misc.push(l); continue; }
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(l);
    }
    const sites = [...map.entries()].map(([name, members]) => ({ name, members }));
    if (misc.length) sites.push({ name: MISC, members: misc });
    return sites;
  };

  // メンバー1件の フィールド名→数値か マップ
  // (fgb ヘッダの列型を優先、無ければ地物の値から判定)
  const fieldMapOf = l => {
    const cols = l.fgb?.columns;
    if (cols?.length) {
      const m = {};
      for (const c of cols) if (c?.name) m[c.name] = NUMERIC_COL_TYPES.has(c.type);
      return m;
    }
    const gj = api.getLayerGeoJson?.(l.id) || api.getLayerGeoJson?.(l.title);
    const m = {};
    for (const f of (gj?.features || []).slice(0, 500)) {
      const p = f?.properties || {};
      for (const [k, v] of Object.entries(p)) {
        if (k.startsWith("__kasc_")) continue; // スタイル焼付け内部属性
        if (!(k in m)) m[k] = true;
        if (v != null && typeof v !== "number") m[k] = false;
      }
    }
    return m;
  };

  // 全メンバー共通フィールド名→数値か(全メンバーで数値のとき true)
  const commonFields = members => {
    let common = null;
    for (const m of members) {
      const fm = fieldMapOf(m);
      if (common == null) common = fm;
      else {
        for (const k of Object.keys(common)) {
          if (!(k in fm)) delete common[k];
          else common[k] = common[k] && fm[k];
        }
      }
    }
    return common || {};
  };

  // メンバー全レイヤの既存値を列挙(最大100件)。
  // フィルタ済みソースの型は where= を一時解除して全件から集めて復元する
  const collectValues = async (members, field) => {
    const vals = new Set();
    for (const m of members) {
      const prev = m.filter || "";
      const cleared = !!prev && !FULL_SOURCE_TYPES.has(m.type) && !!api.setLayerFilter;
      if (cleared) { try { await api.setLayerFilter(m.id, ""); } catch (_) {} }
      try {
        const gj = await api.getLayerGeoJson?.(m.id)
          || await api.getLayerGeoJson?.(m.title);
        for (const f of gj?.features || []) {
          const v = f?.properties?.[field];
          if (v != null) vals.add(String(v));
          if (vals.size > 100) break;
        }
      } finally {
        if (cleared) { try { await api.setLayerFilter(m.id, prev); } catch (_) {} }
      }
      if (vals.size > 100) break;
    }
    return [...vals]
      .sort((a, b) => a.localeCompare(b, "ja", { numeric: true }))
      .slice(0, 100);
  };

  const filterStyle = document.createElement("style");
  filterStyle.textContent = `
    .sf-row { display: flex; align-items: center; gap: 5px; margin: 3px 0; }
    .sf-row > label { flex: 0 0 auto; font-size: 0.85em; }
    .sf-row select, .sf-row input[type="text"], .sf-row input[type="number"] {
      flex: 1; min-width: 0; min-height: 26px; font-size: 0.85em; padding: 2px 5px;
      border: 1px solid #b9c4cc; border-radius: 3px; }
    .sf-row select.sf-op { flex: 0 0 auto; width: 76px; }
    .sf-multi-cb { font-size: 0.85em; display: flex; align-items: center; gap: 4px; }
    .sf-multi-cb input[type="checkbox"], .sf-vals input[type="checkbox"] {
      flex: 0 0 auto; width: 13px; min-height: 13px; margin: 0; }
    .sf-vals { flex: 1; max-height: calc(100vh - var(--control-panel-bottom-clearance, 140px)); overflow-y: auto;
      border: 1px solid #b9c4cc; border-radius: 3px; padding: 2px 5px; }
    .sf-vals label { display: flex; align-items: center; gap: 4px;
      font-size: 0.85em; line-height: 1.35; }
    .sf-btn { min-height: 24px; padding: 2px 10px; font-size: 0.85em; cursor: pointer; }
    .sf-allcol { flex: 0 0 auto; display: flex; flex-direction: column; gap: 2px; }
    .sf-btn.sf-mini { min-height: 18px; padding: 1px 6px; font-size: 0.75em; }
    .sf-status { flex: 1; font-size: 0.78em; color: #345;
      word-break: break-all; }
  `;

  const registerFilterPanel = afterKey => {
    if (!api.setLayerFilter || !api.getLayerGeoJson) return;
    let siteSel, fieldSel, multiCb, rowNum, rowStr, rowMulti,
      opNum, opStr, opMulti, inputNum, inputStr, listEl, statusEl, valList;
    // manifest.options の filter_* = QGIS Filter タブの選択状態。
    // 複数選択のチェックは値列挙後に1回だけ反映する
    const fpreset = manifest?.options || {};
    let pendingMulti = Array.isArray(fpreset.filter_values)
      ? new Set(fpreset.filter_values.map(String)) : null;
    // フィルタ無し(where 無し/全通過)は全値が通る状態 →
    // 初回の値列挙で全チェックにする(pendingMulti があればそちら優先)
    let pendingMultiAll = false;
    const h = (tag, cls, text) => {
      const el = document.createElement(tag);
      if (cls) el.className = cls;
      if (text != null) el.textContent = text;
      return el;
    };
    const qf = s => `"${String(s).replace(/"/g, '""')}"`;
    const ql = s => `'${String(s).replace(/'/g, "''")}'`;
    const status = txt => { if (statusEl) statusEl.textContent = txt || ""; };

    const curMembers = () =>
      filterSites().find(s => s.name === siteSel.value)?.members || [];
    // 現在表示中(where= 適用後)の地物が持つ値の集合。
    // チェック状態を「実際の表示状態」に合わせるために使う。
    // getLayerFilteredGeoJson 非対応の古いホストでは null を返す
    const displayedValues = field => {
      if (!field || typeof api.getLayerFilteredGeoJson !== "function")
        return null;
      const s = new Set();
      for (const m of curMembers()) {
        const gj = api.getLayerFilteredGeoJson(m.id ?? m.title);
        for (const ft of gj?.features || []) {
          const v = ft?.properties?.[field];
          if (v != null) s.add(String(v));
        }
      }
      return s;
    };
    // 現在の選択をページセッションへ保存する。プラグインが再初期化
    // (inspector-plugins-changed の差分再起動・.kasc 再適用)された
    // とき、古い filter_values プリセットへ巻き戻るのではなく
    // ユーザーの直前選択を優先復元するために使う
    const saveSel = () => {
      try {
        window.__kascFilterSel = {
          site: siteSel?.value || "",
          field: fieldSel?.value || "",
          multi: !!multiCb?.checked,
          op: multiCb?.checked ? opMulti?.value
            : (fieldNumeric() ? opNum?.value : opStr?.value) || "",
          values: multiCb?.checked
            ? [...listEl.querySelectorAll("input:checked")].map(i => i.value)
            : null,
          value: multiCb?.checked ? null
            : (fieldNumeric() ? inputNum?.value : inputStr?.value) || "",
          at: Date.now(),
        };
      } catch (_) { /* 無視 */ }
    };
    const fieldNumeric = () =>
      fieldSel.selectedOptions?.[0]?.dataset.num === "1";

    const refreshSites = () => {
      const cur = siteSel.value;
      siteSel.textContent = "";
      for (const s of filterSites()) {
        const o = document.createElement("option");
        o.value = s.name;
        o.textContent = s.name;
        siteSel.appendChild(o);
      }
      if (cur) siteSel.value = cur;
      refreshFields();
    };

    const refreshFields = () => {
      const members = curMembers();
      const cur = fieldSel.value;
      fieldSel.textContent = "";
      const common = commonFields(members);
      for (const name of Object.keys(common).sort((a, b) => a.localeCompare(b, "ja"))) {
        const o = document.createElement("option");
        o.value = name;
        o.textContent = common[name] ? `${name} (num)` : name;
        if (common[name]) o.dataset.num = "1";
        fieldSel.appendChild(o);
      }
      if (cur && fieldSel.querySelector(`option[value="${CSS.escape(cur)}"]`)) {
        fieldSel.value = cur;
      }
      if (!Object.keys(common).length) status(members.length ? "共通属性がありません" : "対象レイヤがありません");
      else if (statusEl && /共通属性がありません|対象レイヤがありません/.test(statusEl.textContent)) status("");
      updateMode();
    };

    // 直近に列挙したフィールド(prev の引継ぎは同一フィールドの
    // 再列挙時のみ行い、フィールド変更時は適用状態から再シードする)
    let valsField = "";

    // フィールド/サイト変更時のチェック/入力再シード。
    // チェックは常に「現在表示中の地物が持つ値」(実表示状態に一致:
    // 全除外→0件・フィルタ無し→全値・絞り込み中→通過値のみ)。
    // 演算子・複数/単一モード・単一値は適用済み where= から復元する
    const reseedField = () => {
      valsField = "";  // prev の引継ぎを無効化(サイト/フィールド変更)
      const field = fieldSel.value;
      const f = (curMembers()[0]?.filter || "").trim();
      const a = restoreFromExpr(f);
      pendingMultiAll = false;
      inputNum.value = "";
      inputStr.value = "";
      const disp = displayedValues(field);
      if (disp != null) {
        pendingMulti = disp;
      } else if (a?.empty) {
        pendingMulti = new Set();   // 全除外 → 0件
      } else if (a?.full || !f || !a || a.field !== field) {
        pendingMultiAll = true;     // 無制限 → 全チェック
      } else if (a.multi) {
        pendingMulti = new Set(a.values.map(String));
      }
      if (a && !a.empty && !a.full && a.field === field) {
        // このフィールドへの適用済み式 → op/モード/単一値を復元
        multiCb.checked = !!a.multi;
        if (a.multi) {
          if ([...opMulti.options].some(o => o.value === a.op))
            opMulti.value = a.op;
        } else {
          const tgt = fieldNumeric() ? opNum : opStr;
          if ([...tgt.options].some(o => o.value === a.op))
            tgt.value = a.op;
          if (fieldNumeric()) inputNum.value = a.value;
          else inputStr.value = a.value;
        }
      } else if (!multiCb.checked && disp?.size === 1) {
        // 単一モード: 表示中の値が1種ならそれを実態として入力
        const v = [...disp][0];
        if (fieldNumeric()) inputNum.value = v;
        else inputStr.value = v;
      }
    };

    const refreshValues = async () => {
      const field = fieldSel.value;
      if (!field) return;
      const vals = await collectValues(curMembers(), field);
      // 単一選択の候補(datalist)
      if (valList) {
        valList.textContent = "";
        for (const v of vals) {
          const o = document.createElement("option");
          o.value = v;
          valList.appendChild(o);
        }
      }
      // 複数選択のチェックリスト(チェック状態は同一フィールドの
      // 再列挙でのみ保持。フィールド変更時は reseedField 済み)
      const sameField = valsField === field;
      valsField = field;
      const prev = new Set(
        [...listEl.querySelectorAll("input:checked")].map(i => i.value));
      listEl.textContent = "";
      for (const v of vals) {
        const lb = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = v;
        cb.checked = (sameField && prev.has(v)) || pendingMultiAll
          || pendingMulti?.has(v) === true;
        lb.append(cb, document.createTextNode(v));
        listEl.appendChild(lb);
      }
      pendingMulti = null;
      pendingMultiAll = false;
    };

    const updateMode = () => {
      const numeric = fieldNumeric();
      const multi = multiCb.checked;
      rowNum.style.display = numeric && !multi ? "" : "none";
      rowStr.style.display = !numeric && !multi ? "" : "none";
      rowMulti.style.display = multi ? "" : "none";
      if (!numeric || multi) void refreshValues();
    };

    const buildExpr = () => {
      const field = fieldSel.value;
      if (!field) return { error: "フィールドを選択" };
      const numeric = fieldNumeric();
      if (multiCb.checked) {
        const sel = [...listEl.querySelectorAll("input:checked")]
          .map(i => i.value);
        if (!sel.length) {
          // 0件選択: IN=何も通さない(常偽式 1=0) / NOT IN=全て通す(解除)
          return opMulti.value === "NOT IN" ? { expr: "" }
            : { expr: "1=0" };
        }
        const vs = sel.map(v => numeric ? v : ql(v)).join(",");
        const inner = `${qf(field)} IN (${vs})`;
        return { expr: opMulti.value === "NOT IN" ? `NOT (${inner})` : inner };
      }
      if (numeric) {
        const num = Number(inputNum.value.trim());
        if (!Number.isFinite(num)) return { error: "数値を入力" };
        return { expr: `${qf(field)} ${opNum.value} ${num}` };
      }
      const v = inputStr.value.trim();
      if (!v) return { error: "値を選択" };
      return { expr: `${qf(field)} ${opStr.value} ${ql(v)}` };
    };

    const applyFilter = async () => {
      const members = curMembers();
      if (!members.length) { status("対象レイヤがありません"); return; }
      const r = buildExpr();
      if (r.error) { status(r.error); return; }
      let n = 0;
      saveSel();
      for (const m of members) {
        try {
          const res = await api.setLayerFilter(m.id, r.expr);
          if (res?.ok !== false) n++;
        } catch (_) {}
      }
      status(`${r.expr}（${n}件に適用）`);
      void refreshValues();
    };

    const clearFilter = async () => {
      const members = curMembers();
      saveSel();
      for (const m of members) {
        try { await api.setLayerFilter(m.id, ""); } catch (_) {}
      }
      status("");
      void refreshValues();
    };

    // IN リスト("'a','b''c',1,2")を分解してデコードする
    const splitInVals = body => {
      const out = [];
      let i = 0;
      while (i < body.length) {
        while (i < body.length && /[\s,]/.test(body[i])) i++;
        if (i >= body.length) break;
        if (body[i] === "'") {
          let v = ""; i++;
          while (i < body.length) {
            if (body[i] === "'" && body[i + 1] === "'") { v += "'"; i += 2; }
            else if (body[i] === "'") { i++; break; }
            else v += body[i++];
          }
          out.push(v);
        } else {
          const j = body.indexOf(",", i);
          const tok = (j < 0 ? body.slice(i) : body.slice(i, j)).trim();
          if (tok) out.push(tok);
          i = j < 0 ? body.length : j;
        }
      }
      return out;
    };

    // レイヤ適用済みの where= 式から UI 選択状態を復元する
    // (適用済みがデフォルト。filter_* プリセットより優先して使う)
    const restoreFromExpr = expr => {
      const t = String(expr || "").trim();
      if (!t) return null;
      // 0件選択の書き戻し(常偽式 1=0)は「複数選択 IN + チェック0件」
      // として復元する(1=1 は 0件+NOT IN = 全通過)
      if (/^(?:1\s*=\s*0|0\s*=\s*1)$/.test(t))
        return { empty: true };
      if (/^1\s*=\s*1$/.test(t))
        return { full: true };
      const F = '"((?:[^"]|"")+)"';
      let m = t.match(new RegExp(`^NOT\\s*\\(\\s*${F}\\s+IN\\s*\\((.*)\\)\\s*\\)$`, "i"));
      if (m) return { field: m[1].replace(/""/g, '"'), multi: true, op: "NOT IN", values: splitInVals(m[2]) };
      m = t.match(new RegExp(`^${F}\\s+IN\\s*\\((.*)\\)\\s*$`, "i"));
      if (m) return { field: m[1].replace(/""/g, '"'), multi: true, op: "IN", values: splitInVals(m[2]) };
      m = t.match(new RegExp(`^${F}\\s*(=|!=|<=|>=|<|>)\\s*(?:'((?:[^']|'')*)'|(-?[\\d.]+))\\s*$`));
      if (m) return { field: m[1].replace(/""/g, '"'), multi: false, op: m[2],
        value: m[3] != null ? m[3].replace(/''/g, "'") : m[4] };
      return null;
    };

    // 選択が完結していれば即適用(適用ボタン不要)。値・演算子・
    // 複数選択の変更のみトリガ — サイト/フィールドの選択自体では
    // 適用しない(未完成の選択で誤適用しないため)。値が0件
    // (全解除/入力クリア)のときはフィルタ解除として即反映する
    let autoT = null;
    const autoApply = (delay = 200) => {
      clearTimeout(autoT);
      autoT = setTimeout(() => {
        if (!curMembers().length) return;
        const r = buildExpr();
        if (r.error) {
          if (r.error !== "フィールドを選択") void clearFilter();
          return;
        }
        void applyFilter();
      }, delay);
    };

    api.registerPanel({
      id: "site-filter",
      title: "フィルタ",
      ...(afterKey ? { after: afterKey } : {}),
      onInit(panel) {
        panel.appendChild(filterStyle);
        siteSel = document.createElement("select");
        fieldSel = document.createElement("select");
        const sfRow = h("div", "sf-row");
        sfRow.append(h("label", null, "サイト:"), siteSel,
          h("label", null, "フィールド:"), fieldSel);
        panel.appendChild(sfRow);
        // 複数選択トグル
        const mrow = h("div", "sf-row");
        const mlb = h("label", "sf-multi-cb");
        multiCb = document.createElement("input");
        multiCb.type = "checkbox";
        mlb.append(multiCb, document.createTextNode("複数選択"));
        mrow.appendChild(mlb);
        panel.appendChild(mrow);
        // 数値行
        rowNum = h("div", "sf-row");
        opNum = document.createElement("select");
        opNum.className = "sf-op";
        for (const o of ["=", "!=", "<", "<=", ">", ">="])
          opNum.appendChild(new Option(o, o));
        inputNum = document.createElement("input");
        inputNum.type = "number";
        inputNum.step = "any";
        inputNum.placeholder = "値(数値)";
        rowNum.append(opNum, inputNum);
        panel.appendChild(rowNum);
        // 文字列行(入力+候補datalist)
        rowStr = h("div", "sf-row");
        opStr = document.createElement("select");
        opStr.className = "sf-op";
        for (const o of ["=", "!="]) opStr.appendChild(new Option(o, o));
        inputStr = document.createElement("input");
        inputStr.type = "text";
        inputStr.placeholder = "値";
        valList = document.createElement("datalist");
        const dlId = `sf-vals-${Math.random().toString(36).slice(2)}`;
        valList.id = dlId;
        inputStr.setAttribute("list", dlId);
        rowStr.append(opStr, inputStr, valList);
        panel.appendChild(rowStr);
        // 複数選択行
        rowMulti = h("div", "sf-row");
        opMulti = document.createElement("select");
        opMulti.className = "sf-op";
        for (const o of ["IN", "NOT IN"]) opMulti.appendChild(new Option(o, o));
        const allCol = h("div", "sf-allcol");
        const setAll = checked => {
          for (const cb of listEl.querySelectorAll("input[type=checkbox]"))
            cb.checked = checked;
        };
        const allBtn = h("button", "sf-btn sf-mini", "全選択");
        allBtn.type = "button";
        // チェック操作と同時に地図へ即反映(デバウンスを介さず直接適用)
        allBtn.addEventListener("click", () => {
          setAll(true);
          void applyFilter();
        });
        const noneBtn = h("button", "sf-btn sf-mini", "全解除");
        noneBtn.type = "button";
        // 0件選択 = 1件も通さない(IN は常偽式・NOT IN は全通過)。
        // 全選択の逆操作として地図へ即反映する
        noneBtn.addEventListener("click", () => {
          setAll(false);
          saveSel();  // 0件選択の状態も再初期化時に復元できるよう保存
          void applyFilter();
        });
        allCol.append(opMulti, allBtn, noneBtn);
        listEl = h("div", "sf-vals");
        // チェック1つ切替ごとに即適用(デバウンスでまとめる)
        listEl.addEventListener("change", ev => {
          if (ev.target?.type === "checkbox") autoApply();
        });
        rowMulti.append(allCol, listEl);
        rowMulti.style.alignItems = "flex-start";
        panel.appendChild(rowMulti);
        // ステータス表示は不要(適用は選択時点で即反映)
        statusEl = null;
        // イベント(値・演算子・複数選択の変更で即適用)
        siteSel.addEventListener("change",
          () => { refreshFields(); reseedField(); });
        fieldSel.addEventListener("change",
          () => { reseedField(); updateMode(); });
        multiCb.addEventListener("change", () => { updateMode(); autoApply(); });
        for (const s of [opNum, opStr, opMulti])
          s.addEventListener("change", () => autoApply());
        inputNum.addEventListener("input", () => autoApply(350));
        inputStr.addEventListener("input", () => autoApply(350));
        refreshSites();
        // .kasc の filter_* = QGIS Filter タブの選択状態を初期値へ復元
        const pStr = v => (v == null ? "" : String(v));
        if (fpreset.filter_site != null
          && [...siteSel.options].some(o => o.value === pStr(fpreset.filter_site))) {
          siteSel.value = pStr(fpreset.filter_site);
          refreshFields();
        }
        if (fpreset.filter_field != null
          && [...fieldSel.options].some(o => o.value === pStr(fpreset.filter_field))) {
          fieldSel.value = pStr(fpreset.filter_field);
        }
        if (fpreset.filter_multi === true) multiCb.checked = true;
        updateMode();
        const pOp = pStr(fpreset.filter_op);
        const opTarget = multiCb.checked ? opMulti
          : fieldNumeric() ? opNum : opStr;
        if (pOp && [...opTarget.options].some(o => o.value === pOp)) {
          opTarget.value = pOp;
        }
        if (fpreset.filter_value != null && !multiCb.checked) {
          if (fieldNumeric()) inputNum.value = pStr(fpreset.filter_value);
          else inputStr.value = pStr(fpreset.filter_value);
        }
        // レイヤへ適用済みの where= があればフィールド/演算子/単一値を
        // 復元(filter_* プリセットより実際の適用状態を優先)。
        // 値のチェックは式ではなく「表示中の地物が持つ値」で決める
        const applied = restoreFromExpr(curMembers()[0]?.filter);
        if (applied && !applied.empty && !applied.full
            && [...fieldSel.options]
            .some(o => o.value === applied.field)) {
          fieldSel.value = applied.field;
          multiCb.checked = !!applied.multi;
          updateMode();
          const apOp = multiCb.checked ? opMulti
            : fieldNumeric() ? opNum : opStr;
          if ([...apOp.options].some(o => o.value === applied.op))
            apOp.value = applied.op;
          if (!applied.multi) {
            if (fieldNumeric()) inputNum.value = applied.value;
            else inputStr.value = applied.value;
          }
        } else if (applied == null
            && (curMembers()[0]?.filter || "").trim()) {
          // 解析不能な where(独自式等)が残る場合はセッション内の
          // 直前選択のフィールド/演算子だけ復元(値は表示実態から)
          const snap = window.__kascFilterSel;
          if (snap?.field &&
              [...fieldSel.options].some(o => o.value === snap.field)) {
            fieldSel.value = snap.field;
            multiCb.checked = !!snap.multi;
            updateMode();
            const snOp = multiCb.checked ? opMulti
              : fieldNumeric() ? opNum : opStr;
            if (snap.op &&
                [...snOp.options].some(o => o.value === snap.op))
              snOp.value = snap.op;
          }
        }
        // チェック値は実表示状態に一致させる(1=0→0件・無し→全件・
        // 絞り込み中→通過値)。getLayerFilteredGeoJson 非対応の古い
        // ホストでは where 有無で推定する
        const disp = displayedValues(fieldSel.value);
        if (disp != null) {
          pendingMulti = disp;
        } else if (applied?.empty) {
          multiCb.checked = true;
          pendingMulti = new Set();
          updateMode();
        } else if (applied?.full || !pendingMulti) {
          pendingMultiAll = true;
        }
        // 現在のフィルタをステータスに表示(先頭メンバー)
        const first = curMembers()[0];
        if (first?.filter) status(first.filter);
      },
      onShow() {
        refreshSites();
        const first = curMembers()[0];
        if (first?.filter) status(first.filter);
      },
    });
  };

  let list = null;
  const render = () => {
    if (!list) return;
    const native = !!document.getElementById("layer-list");
    const sites = collect();
    list.textContent = "";
    if (!sites.length) {
      const p = document.createElement("div");
      p.className = "sc-empty";
      p.textContent = `site=<グループ名> を付けたレイヤがありません`;
      list.appendChild(p);
      return;
    }
    if (native) {
      // #layer-list { font-size: 18px } と同じ文字サイズに揃える
      const ll = document.getElementById("layer-list");
      list.style.fontSize = getComputedStyle(ll).fontSize;
      for (const site of sites) list.appendChild(siteSection(site));
    } else {
      for (const site of sites) list.appendChild(fallbackSection(site));
    }
  };

  const layerPanel = api.registerPanel({
    id: "custom-layer",
    title: manifest.name || "レイヤ",
    onInit(panel) {
      panel.appendChild(style);
      if (document.getElementById("layer-list")) {
        // 標準タブと同じ .layer-head-row(全展開/全折りたたみ)
        const head = document.createElement("div");
        head.className = "layer-head-row";
        const mk = (glyph, title, fn) => {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "layer-head-btn";
          b.title = title;
          b.textContent = glyph;
          b.addEventListener("click", fn);
          return b;
        };
        const expand = mk("🔽", "すべて展開", () => {
          groupCollapsed.clear();
          legendCollapsed.clear();
          render();
        });
        expand.style.marginLeft = "auto";
        const collapse = mk("🔼", "すべて折りたたみ", () => {
          for (const s of collect()) {
            groupCollapsed.add(s.name);
            for (const m of s.members) {
              if ((m.legend || []).length > 1) legendCollapsed.add(m.id);
            }
          }
          render();
        });
        head.append(expand, collapse);
        panel.appendChild(head);
      }
      list = document.createElement("div");
      panel.appendChild(list);
      render();
    },
    onShow() { render(); },
  });
  // 「フィルタ」タブをレイヤタブの直後に登録(setLayerFilter 非対応の
  // エンジンでは registerFilterPanel 内で何もしない)
  registerFilterPanel(layerPanel?.key);
  api.on?.("layers-changed", () => render());
}
