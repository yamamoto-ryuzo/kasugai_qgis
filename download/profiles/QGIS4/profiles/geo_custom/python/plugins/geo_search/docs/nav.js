// 自動生成: scripts/build-plugin-docs.py(再実行で上書きされます)
// KASUGAI Canvas docs/nav.js と同型(セクション + 項目 + 子リンク)
(function () {
  var TITLE = 'geo_search';
  var GROUPS = [
    { section: null, items: [
      { href: 'index.html', text: '概要', },
      { href: 'search.html', text: '検索機能（日本語）',
        children: [
          { href: 'search.html#概要', text: '概要' },
          { href: 'search.html#サブシステム図と境界開発者向け', text: 'サブシステム図と境界（開発者向け）' },
          { href: 'search.html#地番検索', text: '地番検索' },
          { href: 'search.html#汎用属性検索', text: '汎用属性検索' },
          { href: 'search.html#所有者検索', text: '所有者検索' },
          { href: 'search.html#検索ロジック実装概要', text: '検索ロジック（実装概要）' },
          { href: 'search.html#ui設定画面', text: 'UI設定画面' },
          { href: 'search.html#設定項目', text: '設定項目' },
          { href: 'search.html#設定ソース読み込み元と注釈', text: '設定ソース（読み込み元）と注釈' },
          { href: 'search.html#設定ファイル説明主要項目', text: '設定ファイル説明（主要項目）' },
          { href: 'search.html#課題と注意点', text: '課題と注意点' },
          { href: 'search.html#参考ファイル', text: '参考ファイル' },
        ]
      },
      { href: 'themes.html', text: 'マップテーマ（Map Themes）機能の概要 — テーマ管理サブシステム',
        children: [
          { href: 'themes.html#user-themeユーザーテーマ--開発中', text: 'User-theme（ユーザーテーマ） — 開発中' },
          { href: 'themes.html#制限事項と既知の問題', text: '制限事項と既知の問題' },
          { href: 'themes.html#テスト手順と検証チェックリスト', text: 'テスト手順と検証チェックリスト' },
          { href: 'themes.html#追加表示additive-modeについて詳細', text: '追加表示（Additive mode）について（詳細）' },
        ]
      },
    ]},
  ];
  var DEMOS = [
    { href: 'https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html', text: 'プラグイン一覧(サイト)' },
    { href: 'https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_search', text: 'GitHub(プラグイン)' },
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
