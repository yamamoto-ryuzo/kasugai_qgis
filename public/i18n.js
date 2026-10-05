// i18n 最小実装。
// 方針: HTML のリテラルは日本語（初期表示）、翻訳の基準言語は英語（en.json が正本）。
// 対応言語の追加は SUPPORTED_LANGUAGES と public/i18n/<lang>.json の追加のみで行う
// （加えてサーバー側で /i18n/<lang>.json の配信ルートが必要）。
const SUPPORTED_LANGUAGES = [
  { code: 'ja', label: '日本語' },
  { code: 'en', label: 'English' },
  { code: 'zh', label: '简体中文' },
  { code: 'zh-tw', label: '繁體中文' },
  { code: 'ko', label: '한국어' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'pt', label: 'Português' },
  { code: 'ru', label: 'Русский' },
];
const I18N_FALLBACK_LANG = 'en';
const I18N_STORAGE_KEY = 'kasugai_qgis_lang';

let i18nDict = {};
let i18nFallback = {};
let currentLang = I18N_FALLBACK_LANG;

function detectLanguage() {
  try {
    const saved = localStorage.getItem(I18N_STORAGE_KEY);
    if (saved && SUPPORTED_LANGUAGES.some(l => l.code === saved)) return saved;
  } catch (e) { /* ignore */ }
  const nav = (navigator.language || '').toLowerCase();
  // zh-tw が zh より先にマッチするよう、コード長の降順で比較する
  const match = [...SUPPORTED_LANGUAGES]
    .sort((a, b) => b.code.length - a.code.length)
    .find(l => nav.startsWith(l.code));
  return match ? match.code : I18N_FALLBACK_LANG;
}

async function fetchDict(lang) {
  try {
    const res = await fetch('/i18n/' + lang + '.json');
    if (!res.ok) return {};
    return await res.json();
  } catch (e) {
    return {};
  }
}

// キー未登録時は英語（フォールバック）→それでも無ければキー自体を返す。
function t(key, params) {
  let s = i18nDict[key];
  if (s === undefined) s = i18nFallback[key];
  if (s === undefined) return key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      s = s.replaceAll('{' + k + '}', String(v));
    }
  }
  return s;
}

function applyI18n() {
  document.documentElement.lang = currentLang;
  const title = t('app_title');
  if (title) document.title = title;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    let params;
    const raw = el.getAttribute('data-i18n-args');
    if (raw) {
      try { params = JSON.parse(raw); } catch (e) { /* ignore */ }
    }
    el.textContent = t(el.getAttribute('data-i18n'), params);
  });
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    el.setAttribute('placeholder', t(el.getAttribute('data-i18n-ph')));
  });
}

async function initI18n() {
  currentLang = detectLanguage();
  i18nFallback = await fetchDict(I18N_FALLBACK_LANG);
  i18nDict = currentLang === I18N_FALLBACK_LANG ? i18nFallback : await fetchDict(currentLang);
  applyI18n();
}

async function setLanguage(lang) {
  try { localStorage.setItem(I18N_STORAGE_KEY, lang); } catch (e) { /* ignore */ }
  currentLang = lang;
  i18nDict = lang === I18N_FALLBACK_LANG ? i18nFallback : await fetchDict(lang);
  applyI18n();
  if (typeof window.onLanguageChanged === 'function') window.onLanguageChanged();
}
