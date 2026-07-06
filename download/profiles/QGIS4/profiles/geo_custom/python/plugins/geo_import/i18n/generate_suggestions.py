# -*- coding: utf-8 -*-
"""
Generate translation suggestions for selected languages (en, ja).
- Does NOT modify TS files.
- Outputs suggestion files to i18n/reports/suggestions_<lang>.txt

Approach:
- For 'en': suggestion = source (copy English source into translation)
- For 'ja': try to find an existing finished translation in the same ja TS for the same source
  (useful if duplicates exist). If none found, leave suggestion empty.
"""
import os
import xml.etree.ElementTree as ET

here = os.path.dirname(os.path.abspath(__file__))
i18n_dir = here
reports_dir = os.path.join(i18n_dir, 'reports')
os.makedirs(reports_dir, exist_ok=True)

langs = ['en', 'ja']
# map lang -> filename
lang_files = {}
for f in os.listdir(i18n_dir):
    if f.startswith('geo_import_') and f.endswith('.ts'):
        code = f.replace('geo_import_', '').replace('.ts','')
        lang_files[code] = os.path.join(i18n_dir, f)

# helper to parse TS and build source->translation dict for finished entries
def build_translation_map(ts_path):
    try:
        tree = ET.parse(ts_path)
        root = tree.getroot()
    except Exception:
        return {}
    mapping = {}
    for ctx in root.findall('context'):
        for msg in ctx.findall('message'):
            src = msg.find('source')
            trans = msg.find('translation')
            if src is None or trans is None:
                continue
            ttype = trans.get('type')
            text_src = src.text or ''
            text_trans = trans.text or ''
            if ttype != 'unfinished' and text_trans.strip() != '':
                # store first occurrence
                if text_src not in mapping:
                    mapping[text_src] = text_trans
    return mapping

# build ja mapping if available
ja_map = {}
if 'ja' in lang_files:
    ja_map = build_translation_map(lang_files['ja'])

# parse english TS to get list of all sources (use en if present, else take any TS)
sources = []
if 'en' in lang_files:
    path_en = lang_files['en']
else:
    # fallback: pick first ts
    path_en = next(iter(lang_files.values()))

try:
    tree = ET.parse(path_en)
    root = tree.getroot()
    for ctx in root.findall('context'):
        for msg in ctx.findall('message'):
            src = msg.find('source')
            if src is None:
                continue
            sources.append((ctx.find('name').text if ctx.find('name') is not None else '', src.text or ''))
except Exception as e:
    print('Error reading source TS:', e)

# build list of unfinished items per lang
def collect_unfinished(ts_path):
    items = []
    try:
        tree = ET.parse(ts_path)
        root = tree.getroot()
    except Exception:
        return items
    for ctx in root.findall('context'):
        ctx_name = ctx.find('name').text if ctx.find('name') is not None else ''
        for msg in ctx.findall('message'):
            src = msg.find('source')
            trans = msg.find('translation')
            if trans is None:
                continue
            if trans.get('type') == 'unfinished':
                locs = [f"{l.get('filename')}:{l.get('line')}" for l in msg.findall('location')]
                items.append({'context':ctx_name, 'source': src.text or '', 'locations': locs})
    return items

for lang in langs:
    code = 'en' if lang == 'en' else 'ja'
    # find ts for this code
    ts_path = None
    # lang_files keys include full locale like en_US, ja_JP; find those starting with code
    for k,v in lang_files.items():
        if k.startswith(code):
            ts_path = v
            break
    if not ts_path:
        print(f'No TS file found for {lang}, skipping')
        continue

    unfinished = collect_unfinished(ts_path)
    out_path = os.path.join(reports_dir, f'suggestions_{code}.txt')
    with open(out_path, 'w', encoding='utf-8') as out:
        out.write(f'Suggestions for {code}\n')
        out.write('====================\n')
        out.write(f'Total unfinished: {len(unfinished)}\n\n')
        for i,item in enumerate(unfinished,1):
            source = item['source']
            suggestion = ''
            if code == 'en':
                suggestion = source
            elif code == 'ja':
                # try to find existing translation for same source
                suggestion = ja_map.get(source, '')
            out.write(f'[{i}] Context: {item["context"]}\n')
            out.write(f'Locations: {";".join(item["locations"]) if item["locations"] else "(no location)"}\n')
            out.write('Source:\n')
            out.write(source + '\n')
            out.write('Suggestion:\n')
            out.write((suggestion or '<no suggestion>') + '\n')
            out.write('\n')
    print(f'Wrote suggestions for {code} -> {out_path}')

print('Done')
