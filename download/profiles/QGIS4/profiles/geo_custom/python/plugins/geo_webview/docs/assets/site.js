// geo_webview docs — 最新バージョンバッジ + mermaid 図のレンダリング
// オフライン/取得失敗時はバッジ非表示・mermaid コードがそのまま表示される

// metadata.txt(version=)を master から取得し、サイドバータイトルと
// [data-plugin-version] 要素へバッジ表示する(harness の auto-update と同じ
// raw.githubusercontent.com 経由)
const META_URL =
  'https://raw.githubusercontent.com/yamamoto-ryuzo/qgis_live_harness/master/qgis-plugin/geo_webview/metadata.txt';
try {
  const res = await fetch(META_URL);
  const m = res.ok && (await res.text()).match(/^version\s*=\s*(\S+)/m);
  if (m) {
    const site = document.querySelector('nav.sidebar .site');
    if (site) {
      const b = document.createElement('span');
      b.className = 'ver-badge';
      b.textContent = 'v' + m[1];
      site.appendChild(b);
    }
    for (const el of document.querySelectorAll('[data-plugin-version]')) {
      el.textContent = 'v' + m[1];
      el.removeAttribute('hidden');
    }
  }
} catch { /* ネットワーク不通時は非表示のまま */ }

// mermaid 図のレンダリング(CDN)
try {
  const { default: mermaid } =
    await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs');
  for (const code of document.querySelectorAll('pre > code.language-mermaid')) {
    const div = document.createElement('div');
    div.className = 'mermaid';
    div.textContent = code.textContent;
    code.parentElement.replaceWith(div);
  }
  await mermaid.run({ querySelector: '.mermaid' });
} catch { /* CDN 未到達時は pre のまま */ }
