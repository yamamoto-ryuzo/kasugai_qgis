// 自動生成: scripts/build-plugin-docs.py(再実行で上書きされます)
(function () {
  var TITLE = 'geo_webview';
  var PAGES = [
    { href: 'index.html', text: '概要', },
    { href: 'architecture.html', text: '1. 連携構成図',
      children: [
        { href: 'architecture.html#連携方針対応クライアント', text: '連携方針（対応クライアント）' },
      ]
    },
    { href: 'features.html', text: '2. 主な機能',
      children: [
        { href: 'features.html#エクスポート', text: '【エクスポート】' },
        { href: 'features.html#zip', text: '【ZIP】' },
        { href: 'features.html#-webview', text: '【▶ WebView】' },
        { href: 'features.html#-canvas', text: '【▶ Canvas】' },
        { href: 'features.html#webgis', text: 'WebGIS' },
      ]
    },
    { href: 'engines.html', text: '3. マルチエンジン',
      children: [
        { href: 'engines.html#起動ページenginehtml', text: '起動ページ（&lt;engine&gt;.html）' },
        { href: 'engines.html#kasugai-canvas-エンジン比較', text: 'KASUGAI Canvas エンジン比較' },
        { href: 'engines.html#githubpages-cdnkasugai-canvas-web', text: 'GitHubPages CDN（kasugai-canvas-web）' },
      ]
    },
    { href: 'getting-started.html', text: '4. 導入ガイド',
      children: [
        { href: 'getting-started.html#クイックスタート', text: 'クイックスタート' },
        { href: 'getting-started.html#サーバレス配信の流れ', text: 'サーバレス配信の流れ' },
      ]
    },
    { href: 'technical.html', text: '5. 技術資料',
      children: [
        { href: 'technical.html#内蔵-http-サーバー補助機能', text: '内蔵 HTTP サーバー（補助機能）' },
        { href: 'technical.html#パーマリンクexternal-control従来機能', text: 'パーマリンク・External Control（従来機能）' },
        { href: 'technical.html#ネットワーク機能', text: 'ネットワーク機能' },
        { href: 'technical.html#エンドポイント一覧', text: 'エンドポイント一覧' },
        { href: 'technical.html#geo_suite-との連携', text: 'geo_suite との連携' },
        { href: 'technical.html#動作環境', text: '動作環境' },
        { href: 'technical.html#kasugai-canvas-連携詳細', text: 'KASUGAI Canvas 連携（詳細）' },
        { href: 'technical.html#開発カスタマイズ', text: '開発・カスタマイズ' },
        { href: 'technical.html#セキュリティ注意事項', text: 'セキュリティ注意事項' },
      ]
    },
    { href: 'spec.html', text: 'geo_webview — 仕様書',
      children: [
        { href: 'spec.html#目的と範囲', text: '目的と範囲' },
        { href: 'spec.html#1-機能概要', text: '1. 機能概要' },
        { href: 'spec.html#2-api--エンドポイント仕様高水準', text: '2. API / エンドポイント仕様（高水準）' },
        { href: 'spec.html#3-パーマリンク形式とパラメータ', text: '3. パーマリンク形式とパラメータ' },
        { href: 'spec.html#4-web-配信kasugai-canvas-エクスポート', text: '4. Web 配信（KASUGAI Canvas エクスポート）' },
        { href: 'spec.html#59-ogc-サービスv3290-で廃止', text: '5–9. OGC サービス（v3.29.0 で廃止）' },
        { href: 'spec.html#10-google-maps--google-earth-連携v3300-で廃止', text: '10. Google Maps / Google Earth 連携（v3.30.0 で廃止）' },
        { href: 'spec.html#11-external-control外部制御のパース優先度と挙動', text: '11. External Control（外部制御）のパース優先度と挙動' },
        { href: 'spec.html#12-テーマ-theme-サポート', text: '12. テーマ (Theme) サポート' },
        { href: 'spec.html#13-レンダリングscreenshotとパフォーマンス', text: '13. レンダリング（/screenshot）とパフォーマンス' },
        { href: 'spec.html#14-投影-crs-ポリシー', text: '14. 投影 (CRS) ポリシー' },
        { href: 'spec.html#15-kasugai-canvas-連携送出', text: '15. KASUGAI Canvas 連携（送出）' },
        { href: 'spec.html#16-セキュリティ運用上の注意', text: '16. セキュリティ・運用上の注意' },
        { href: 'spec.html#17-テストqa-手順', text: '17. テスト・QA 手順' },
        { href: 'spec.html#18-実装ファイルと責務マッピング', text: '18. 実装ファイルと責務マッピング' },
        { href: 'spec.html#19-変更履歴の要約v2v3-ハイライト', text: '19. 変更履歴の要約（V2/V3 ハイライト）' },
      ]
    },
    { href: 'integration.html', text: 'geo_webview — 外部サービス・クライアント連携方針',
      children: [
        { href: 'integration.html#連携構成図', text: '連携構成図' },
        { href: 'integration.html#reearth-visualizergeo_suiteへの対応方針', text: 'Re:Earth Visualizer（geo_suite）への対応方針' },
        { href: 'integration.html#arcgis-系への対応方針', text: 'ArcGIS 系への対応方針' },
      ]
    },
    { href: 'license.html', text: '6. ライセンス・履歴・免責',
      children: [
        { href: 'license.html#バージョン履歴', text: 'バージョン履歴' },
        { href: 'license.html#ライセンス', text: 'ライセンス' },
        { href: 'license.html#免責事項', text: '免責事項' },
      ]
    },
  ];
  var LINKS = [
    { href: 'https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html', text: 'プラグイン一覧(サイト)' },
    { href: 'https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_webview', text: 'GitHub(プラグイン)' }
  ];
  var here = location.pathname.split('/').pop() || 'index.html';
  var nav = document.createElement('aside');
  nav.id = 'site-nav';
  var h = '<div class="nav-title"><a href="index.html">' + TITLE + '</a></div>';
  h += '<div class="nav-demos">';
  for (var i = 0; i < LINKS.length; i++) {
    h += '<a class="nav-demo" href="' + LINKS[i].href + '" target="_blank" rel="noopener noreferrer">' + LINKS[i].text + '</a>';
  }
  h += '</div><div class="nav-group"><ul>';
  for (var i = 0; i < PAGES.length; i++) {
    var p = PAGES[i];
    h += '<li><a href="' + p.href + '"' +
      (p.href === here ? ' class="active"' : '') + '>' + p.text + '</a>';
    if (p.children) {
      h += '<ul class="nav-sub">';
      for (var j = 0; j < p.children.length; j++) {
        var c = p.children[j];
        h += '<li><a href="' + c.href + '">' + c.text + '</a></li>';
      }
      h += '</ul>';
    }
    h += '</li>';
  }
  h += '</ul></div>';
  nav.innerHTML = h;
  document.body.prepend(nav);
  document.body.classList.add('has-nav');
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
