// 自動生成: scripts/build-plugin-docs.py(再実行で上書きされます)
// KASUGAI Canvas docs/nav.js と同型(セクション + 項目 + 子リンク)
(function () {
  var TITLE = 'geo_webview';
  var GROUPS = [
    { section: '概要', sectionHref: 'index.html', items: [
      { href: 'index.html', text: '概要', },
      { href: 'spec.html', text: '仕様書',
        children: [
          { href: 'spec.html#目的と範囲', text: '目的と範囲' },
          { href: 'spec.html#概要', text: '概要 — geo_webview の全体像' },
          { href: 'spec.html#api-リファレンス', text: 'HTTP API リファレンス' },
          { href: 'spec.html#crs-ポリシー', text: '投影 (CRS) ポリシー' },
          { href: 'spec.html#セキュリティ運用上の注意', text: 'セキュリティ・運用上の注意' },
          { href: 'spec.html#テストqa-手順', text: 'テスト・QA 手順' },
          { href: 'spec.html#実装ファイルと責務マッピング', text: '実装ファイルと責務マッピング' },
        ]
      },
      { href: 'getting-started.html', text: '導入ガイド',
        children: [
          { href: 'getting-started.html#クイックスタート', text: 'クイックスタート' },
          { href: 'getting-started.html#サーバレス配信の流れ', text: 'サーバレス配信の流れ' },
        ]
      },
      { href: 'architecture.html', text: '連携構成図',
        children: [
          { href: 'architecture.html#連携方針対応クライアント', text: '連携方針（対応クライアント）' },
        ]
      },
    ]},
    { section: 'タブ別機能', items: [
      { href: 'use/1-1-Webタブ.html', text: '1. Web タブ',
        children: [
          { href: 'use/1-1-Webタブ.html#エクスポート', text: '1-1 エクスポート・出力設定' },
          { href: 'use/1-1-Webタブ.html#起動webview', text: '1-2 起動（CDN・Engine）' },
          { href: 'use/1-1-Webタブ.html#canvasアプリ連携', text: '1-3 KASUGAI Canvas アプリ連携' },
          { href: 'use/1-1-Webタブ.html#http-server', text: '1-4 HTTP Server' },
          { href: 'features.html', text: '主な機能' },
          { href: 'engines.html', text: 'マルチエンジン' },
        ]
      },
      { href: 'use/1-2-Liveタブ.html', text: '2. Live タブ',
        children: [
          { href: 'use/1-2-Liveタブ.html#open-live-view', text: '2-1 Open Live View（起動）' },
          { href: 'use/1-2-Liveタブ.html#双方向連携', text: '2-2 双方向連携（追従・選択）' },
          { href: 'use/1-2-Liveタブ.html#add-to-canvas', text: '2-3 Add to Canvas' },
        ]
      },
      { href: 'use/1-3-Layersタブ.html', text: '3. Layers タブ',
        children: [
          { href: 'use/1-3-Layersタブ.html#custom-layers-tab', text: '3-1 Custom layers tab（site= 自動付与）' },
          { href: 'use/1-3-Layersタブ.html#レイヤ別オプション', text: '3-2 レイヤ別オプション（site/order/list/opts）' },
        ]
      },
      { href: 'use/1-4-Filterタブ.html', text: '4. Filter タブ',
        children: [
          { href: 'use/1-4-Filterタブ.html#条件選択', text: '4-1 条件選択（Site・Field・値）' },
          { href: 'use/1-4-Filterタブ.html#複数選択自動適用', text: '4-2 複数選択・自動適用' },
        ]
      },
      { href: 'use/1-5-XYZタブ.html', text: '5. XYZ タブ',
        children: [
          { href: 'use/1-5-XYZタブ.html#自動焼き付け', text: '5-1 Vector → XYZ タイル焼き付け（自動）' },
          { href: 'use/1-5-XYZタブ.html#basemap-groups', text: '5-2 Basemap Groups' },
          { href: 'use/1-5-XYZタブ.html#独立出力', text: '5-3 Standalone XYZ export（独立出力）' },
        ]
      },
      { href: 'use/1-6-Otherタブ.html', text: '6. Other タブ',
        children: [
          { href: 'use/1-6-Otherタブ.html#テーマ', text: '6-1 テーマ (Theme)' },
          { href: 'use/1-6-Otherタブ.html#パーマリンク', text: '6-2 パーマリンク（Permalink）' },
          { href: 'use/1-6-Otherタブ.html#共有', text: '6-3 共有（Share / Presentation）' },
          { href: 'integration.html', text: '外部サービス・クライアント連携方針' },
        ]
      },
      { href: 'use/1-7-パネル下部.html', text: '7. パネル下部',
        children: [
          { href: 'use/1-7-パネル下部.html#external-control', text: '7-1 External Control（外部制御）' },
          { href: 'use/1-7-パネル下部.html#設定ダイアログ', text: '7-2 設定ダイアログ（歯車ボタン）' },
          { href: 'technical.html', text: '技術資料' },
        ]
      },
    ]},
    { section: '資料', items: [
      { href: 'license.html', text: 'ライセンス・履歴・免責',
        children: [
          { href: 'license.html#バージョン履歴', text: 'バージョン履歴' },
          { href: 'license.html#ライセンス', text: 'ライセンス' },
          { href: 'license.html#免責事項', text: '免責事項' },
        ]
      },
    ]},
  ];
  var DEMOS = [
    { href: 'https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html', text: 'プラグイン一覧(サイト)' },
    { href: 'https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_webview', text: 'GitHub(プラグイン)' },
    { href: 'https://yamamoto-ryuzo.github.io/kasugai_canvas/web/cesium/', text: '▶ サンプルサイト(KASUGAI Canvas)' },
  ];
  var base = new URL('.', document.currentScript.src).pathname;
  function norm(p) {
    p = p.replace(/#.*$/, '').replace(/index\.html$/, '')
      .replace(/\/$/, '');
    try { p = decodeURIComponent(p); } catch (e) {}
    return p;
  }
  var current = norm(location.pathname);
  function isActive(href) {
    return href.indexOf('#') < 0 && norm(base + href) === current;
  }
  var nav = document.createElement('aside');
  nav.id = 'site-nav';
  var h = '<div class="nav-title"><a href="' + base + 'index.html">' + TITLE + '</a><span class="nav-version" data-plugin-version hidden></span></div>';
  h += '<div class="nav-demos">';
  for (var i = 0; i < DEMOS.length; i++) {
    h += '<a class="nav-demo" href="' + DEMOS[i].href + '" target="_blank" rel="noopener noreferrer">' + DEMOS[i].text + '</a>';
  }
  h += '</div>';
  for (var g = 0; g < GROUPS.length; g++) {
    var grp = GROUPS[g];
    if (grp.section) h += grp.sectionHref
      ? '<div class="nav-section"><a href="' + base + grp.sectionHref + '">' + grp.section + '</a></div>'
      : '<div class="nav-section">' + grp.section + '</div>';
    h += '<div class="nav-group"><ul>';
    for (var i = 0; i < grp.items.length; i++) {
      var p = grp.items[i];
      h += '<li><a href="' + base + p.href + '"' +
        (isActive(p.href) ? ' class="active"' : '') + '>' + p.text + '</a>';
      if (p.children) {
        h += '<ul class="nav-sub">';
        for (var j = 0; j < p.children.length; j++) {
          var c = p.children[j];
          h += '<li><a href="' + base + c.href + '"' +
            (isActive(c.href) ? ' class="active"' : '') + '>'
 + c.text + '</a></li>';
        }
        h += '</ul>';
      }
      h += '</li>';
    }
    h += '</ul></div>';
  }
  nav.innerHTML = h;
  document.body.prepend(nav);
  document.body.classList.add('has-nav');
  var SCROLL_KEY = 'plugin-docs-nav-scroll';
  try {
    var st = sessionStorage.getItem(SCROLL_KEY);
    if (st) nav.scrollTop = parseInt(st, 10) || 0;
    var st_ = null;
    nav.addEventListener('scroll', function () {
      if (st_) clearTimeout(st_);
      st_ = setTimeout(function () {
        try { sessionStorage.setItem(SCROLL_KEY,
 String(nav.scrollTop)); } catch (e) {}
      }, 80);
    });
  } catch (e) {}
  var btn = document.createElement('button');
  btn.className = 'nav-toggle'; btn.type = 'button';
  btn.setAttribute('aria-label', 'メニュー'); btn.textContent = '☰';
  btn.addEventListener('click', function () {
    document.body.classList.toggle('nav-open'); });
  document.body.prepend(btn);
  nav.addEventListener('click', function (e) {
    if (e.target.closest('a')) document.body.classList.remove('nav-open');
  });
})();
