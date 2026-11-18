# -*- coding: utf-8 -*-
"""geo_userfunc 実行履歴(JSONL)の追記・読出し。

``run``/``evalExpression`` の呼出を 1行1レコードの JSONL で
``<profile>/geo_userfunc_history.jsonl`` へ記録する。
QGIS 非依存の純粋ロジックのみを置く(QGIS 外で単体テスト可能にするため)。
"""

import json
import os


def append_record(path, record):
    """履歴JSONLへ1レコード追記する。"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_history(path, target=None, limit=100):
    """履歴JSONLを新しい順で返す。target指定で対象名に絞り込む。"""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if target and rec.get("target") != target:
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out
