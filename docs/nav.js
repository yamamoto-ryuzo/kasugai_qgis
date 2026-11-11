// QGIS Launcher ドキュメント共通ナビゲーション
// 使い方: <script src="nav.js" defer></script>
// - 左サイドバーにサイト内リンク・ダウンロードリンクを生成
// - 現在ページを自動ハイライト
// - JS が無効でも本文は通常表示される（サイドバーだけ出ない）
(function () {
  const base = new URL('.', document.currentScript.src).pathname;
  const VERSION = 'v2.3.0';

  const GROUPS = [
    {
      label: null,
      items: [
        { href: 'index.html', text: '1. トップ・画面構成' }
      ]
    },
    {
      label: '内部動作',
      items: [
        { href: 'startup.html', text: '2. 起動処理の流れ（内部動作）' }
      ]
    },
    {
      label: '設定',
      items: [
        { href: 'settings.html', text: '3. qgis_settings.json 制御' },
        { href: 'roles.html', text: '4. ユーザーロール制御' },
        { href: 'drive-mappings.html', text: '5. クラウドドライブ自動割り当て' },
        { href: 'local-sync.html', text: '6. ローカル自動同期' }
      ]
    },
    {
      label: '導入・運用',
      items: [
        { href: 'getting-started.html', text: '7. 導入・起動方法' },
        { href: 'update.html', text: '8. 自動更新' },
        {
          href: 'license.html', text: '9. ライセンス・免責事項',
          children: [
            { href: 'third-party-licenses.html', text: 'THIRD-PARTY LICENSES' },
            { href: 'CHANGELOG.md', text: 'CHANGELOG' }
          ]
        }
      ]
    }
  ];

  const DEMOS = [
    { href: 'https://yamamoto-ryuzo.github.io/kasugai_qgis/public/kasugai_qgis-setup.exe', text: '⬇ インストーラー（kasugai_qgis-setup.exe）' },
    { href: 'https://github.com/yamamoto-ryuzo/kasugai_qgis/issues', text: '🐛 問い合わせ（GitHub Issues）' }
  ];

  function norm(path) {
    // 末尾の index.html / / を正規化して比較できる形にする
    return path.replace(/index\.html$/, '').replace(/\/$/, '');
  }
  const current = norm(location.pathname);

  function isActive(href) {
    return norm(base + href) === current;
  }

  const nav = document.createElement('aside');
  nav.id = 'site-nav';

  let html = `<div class="nav-title"><a href="${base}index.html">QGIS Launcher</a><span class="nav-version">${VERSION}</span></div>`;

  html += '<div class="nav-demos">';
  for (const d of DEMOS) {
    html += `<a class="nav-demo" href="${d.href.startsWith('http') ? d.href : base + d.href}"${d.href.startsWith('http') ? ' target="_blank" rel="noopener noreferrer"' : ''}>${d.text}</a>`;
  }
  html += '</div>';

  for (const g of GROUPS) {
    html += '<div class="nav-group">';
    if (g.label) html += `<div class="nav-group-label">${g.label}</div>`;
    html += '<ul>';
    for (const item of g.items) {
      const active = isActive(item.href) ? ' class="active"' : '';
      html += `<li><a href="${base}${item.href}"${active}>${item.text}</a>`;
      if (item.children) {
        html += '<ul class="nav-sub">';
        for (const c of item.children) {
          const cActive = isActive(c.href) ? ' class="active"' : '';
          html += `<li><a href="${base}${c.href}"${cActive}>${c.text}</a></li>`;
        }
        html += '</ul>';
      }
      html += '</li>';
    }
    html += '</ul></div>';
  }

  nav.innerHTML = html;
  document.body.prepend(nav);
  document.body.classList.add('has-nav');

  // モバイル用ハンバーガー
  const btn = document.createElement('button');
  btn.className = 'nav-toggle';
  btn.type = 'button';
  btn.setAttribute('aria-label', 'メニュー');
  btn.textContent = '☰';
  btn.addEventListener('click', () => document.body.classList.toggle('nav-open'));
  document.body.prepend(btn);
  nav.addEventListener('click', (e) => {
    if (e.target.closest('a')) document.body.classList.remove('nav-open');
  });
})();
