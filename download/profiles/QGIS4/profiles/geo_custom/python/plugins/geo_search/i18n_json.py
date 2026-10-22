# -*- coding: utf-8 -*-
"""i18n/<lang>.json ベースの翻訳ローダ(全プラグイン共通・同一ファイル)。

翻訳カタログは <plugin>/i18n/<lang>.json (UTF-8) のみ。
形式: {"<コンテキスト>": {"<英語ソース>": "<翻訳>"}}
Qt Linguist(lupdate/lrelease)・.ts/.qm は使わない。

- コード側のマーキングは Qt 標準のまま:
  self.tr("...") / QCoreApplication.translate("Ctx", "...") / QT_TRANSLATE_NOOP
- install_translator() が JsonTranslator を install すると、それらの呼び出しが
  JSONカタログを引くようになる(uic/loadUi が処理する .ui 由来の文字列も同じ経路)。
- Qtを介さない文字列(生成HTML等)や QGIS 外のツールからは
  translate_text() / catalog() / lookup() を直接使う。
"""

import json
import os

try:
    from qgis.PyQt.QtCore import (
        QCoreApplication, QLocale, QSettings, QTranslator)
except Exception:  # QGIS外(pytest等)
    try:
        from PyQt6.QtCore import (
            QCoreApplication, QLocale, QSettings, QTranslator)
    except Exception:
        QCoreApplication = QLocale = QSettings = QTranslator = None

# 採用言語(固定・全プラグイン同一)。ソース言語は英語(en)でカタログ不要
LANGS = ("de", "es", "fr", "hi", "it", "ja", "pt", "ru", "zh")

_cache = {}


def lang_code():
    """QGIS設定のUI言語コードを返す。en・未対応言語は 'en'。"""
    if QSettings is None:
        return "en"
    try:
        raw = QSettings().value("locale/userLocale", "") or ""
        code = str(raw).replace("-", "_").split("_")[0].lower()
        if not code:
            code = QLocale.system().name().split("_")[0].lower()
        return code if code in LANGS else "en"
    except Exception:
        return "en"


def catalog(plugin_dir, lang=None):
    """i18n/<lang>.json を読み {context: {source: translation}} を返す。"""
    lang = lang or lang_code()
    if lang == "en":
        return {}
    key = (os.path.abspath(plugin_dir), lang)
    if key not in _cache:
        path = os.path.join(plugin_dir, "i18n", lang + ".json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _cache[key] = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _cache[key] = {}
    return _cache[key]


def lookup(cat, context, source):
    """カタログから翻訳を返す。見つからなければ None。

    context が一致しない場合は全contextを対象に検索する
    (同一ソースの別contextカバー・コンテキスト名揺れの吸収)。
    """
    hit = None
    if context:
        hit = cat.get(context, {}).get(source)
    if hit is None:
        for messages in cat.values():
            if isinstance(messages, dict) and source in messages:
                hit = messages[source]
                break
    return hit or None


def translate_text(plugin_dir, context, source, lang=None):
    """Qtを介さずカタログを直接引く(生成HTML等の非Qt文字列用)。"""
    if not source:
        return source
    return lookup(catalog(plugin_dir, lang), context, source) or source


def install_translator(plugin_dir):
    """現在の言語の JsonTranslator を install して返す。

    返り値の参照を呼び出し側で保持すること(GCでアンインストールされないよう)。
    en・未対応言語・Qt非利用環境では None を返して何もしない。
    """
    if QTranslator is None or QCoreApplication is None:
        return None
    code = lang_code()
    if code == "en":
        return None
    translator = _JsonTranslator(catalog(plugin_dir, code))
    QCoreApplication.installTranslator(translator)
    return translator


if QTranslator is not None:

    class _JsonTranslator(QTranslator):
        """dictカタログを引くQTranslator。

        QCoreApplication.translate()/self.tr()/.ui読み込みの全経路を捕捉する。
        未登録のソースは None を返し、Qt側で英語ソースへフォールバック。
        """

        def __init__(self, cat):
            super().__init__()
            self._cat = cat

        def translate(self, context, source_text, disambiguation=None, n=-1):
            if not source_text:
                return None
            return lookup(self._cat, context, source_text)

else:
    _JsonTranslator = None
