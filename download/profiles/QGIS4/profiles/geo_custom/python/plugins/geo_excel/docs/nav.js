// 自動生成: scripts/build-plugin-docs.py(再実行で上書きされます)
(function () {
  var TITLE = 'geo_excel';
  var PAGES = [
    { href: 'index.html', text: '概要', },
  ];
  var LINKS = [
    { href: 'https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html', text: 'プラグイン一覧(サイト)' },
    { href: 'https://github.com/yamamoto-ryuzo/qgis_live_harness/tree/master/qgis-plugin/geo_excel', text: 'GitHub(プラグイン)' }
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
