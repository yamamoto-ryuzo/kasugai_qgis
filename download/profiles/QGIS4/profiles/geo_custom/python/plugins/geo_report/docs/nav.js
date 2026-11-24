// 自動生成: scripts/build-plugin-docs.py(再実行で上書きされます)
// KASUGAI Canvas docs/nav.js と同型(セクション + 項目 + 子リンク)
(function () {
  var TITLE = 'geo_report';
  var GROUPS = [
    { section: null, items: [
      { href: 'index.html', text: '概要', },
    ]},
  ];
  var DEMOS = [
    { href: 'https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html', text: 'プラグイン一覧(サイト)' },
    { href: 'https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_report', text: 'GitHub(プラグイン)' },
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
