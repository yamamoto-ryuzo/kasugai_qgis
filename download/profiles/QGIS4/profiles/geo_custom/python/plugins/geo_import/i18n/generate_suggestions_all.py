#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate translation suggestions for all languages present in i18n.
- For each TS, list unfinished entries and suggest the English source text as a placeholder.
- Does NOT modify TS files.
Outputs: i18n/reports/suggestions_<locale>.txt
"""
import os
import xml.etree.ElementTree as ET

here = os.path.dirname(os.path.abspath(__file__))
i18n_dir = here
reports_dir = os.path.join(i18n_dir, 'reports')
os.makedirs(reports_dir, exist_ok=True)

# find TS files
ts_files = [f for f in os.listdir(i18n_dir) if f.startswith('geo_import_') and f.endswith('.ts')]
ts_map = {f.replace('geo_import_','').replace('.ts',''): os.path.join(i18n_dir,f) for f in ts_files}

# load english sources
en_path = None
for k,v in ts_map.items():
    if k.startswith('en'):
        en_path = v
        break
if not en_path and ts_files:
    en_path = os.path.join(i18n_dir, ts_files[0])

en_sources = {}
if en_path:
    try:
        tree = ET.parse(en_path)
        root = tree.getroot()
        for ctx in root.findall('context'):
            ctx_name = ctx.find('name').text if ctx.find('name') is not None else ''
            for msg in ctx.findall('message'):
                src = msg.find('source')
                if src is None:
                    continue
                key = (ctx_name, (src.text or ''))
                en_sources[key] = src.text or ''
    except Exception as e:
        print('Failed to parse english ts:', e)

def collect_unfinished_items(ts_path):
    items = []
    try:
        tree = ET.parse(ts_path)
        root = tree.getroot()
    except Exception:
        return items
    for ctx in root.findall('context'):
        ctx_name = ctx.find('name').text if ctx.find('name') is not None else ''
        for msg in ctx.findall('message'):
            trans = msg.find('translation')
            src = msg.find('source')
            if trans is None or src is None:
                continue
            if trans.get('type') == 'unfinished':
                locs = [f"{l.get('filename')}:{l.get('line')}" for l in msg.findall('location')]
                items.append({'context':ctx_name, 'source': src.text or '', 'locations': locs})
    return items

for locale, path in ts_map.items():
    unfinished = collect_unfinished_items(path)
    out_path = os.path.join(reports_dir, f'suggestions_{locale}.txt')
    with open(out_path, 'w', encoding='utf-8') as out:
        out.write(f'Suggestions for {locale}\n')
        out.write('====================\n')
        out.write(f'Total unfinished: {len(unfinished)}\n\n')
        for i,item in enumerate(unfinished,1):
            ctx = item['context']
            source = item['source']
            key = (ctx, source)
            suggestion = en_sources.get(key, source)
            out.write(f'[{i}] Context: {ctx}\n')
            out.write(f'Locations: {";".join(item["locations"]) if item["locations"] else "(no location)"}\n')
            out.write('Source:\n')
            out.write(source + '\n')
            out.write('Suggestion (English source fallback):\n')
            out.write((suggestion or '<no suggestion>') + '\n')
            out.write('\n')
    print(f'Wrote suggestions for {locale} -> {out_path}')

print('All suggestions written to', reports_dir)
