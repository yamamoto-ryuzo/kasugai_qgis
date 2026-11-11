# -*- coding: utf-8 -*-
"""
Apply suggestions to TS files:
- Create a backup of each TS as .bak
- For each <translation type="unfinished">, replace with suggested text (English source fallback)
- Remove the 'type' attribute (mark as finished)
- Does not change context or source

CAUTION: This will modify TS files in-place. Backups are created.
"""
import os
import xml.etree.ElementTree as ET

here = os.path.dirname(os.path.abspath(__file__))
# find ts files
files = [f for f in os.listdir(here) if f.startswith('geo_import_') and f.endswith('.ts')]

# find en source mapping
en_path = None
for f in files:
    if f.startswith('geo_import_en'):
        en_path = os.path.join(here, f)
        break
if not en_path and files:
    en_path = os.path.join(here, files[0])

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
                key = (ctx_name, src.text or '')
                en_sources[key] = src.text or ''
    except Exception as e:
        print('Failed to parse en TS:', e)

summary = []
for f in files:
    path = os.path.join(here, f)
    bak = path + '.bak'
    if not os.path.exists(bak):
        with open(path, 'rb') as r, open(bak, 'wb') as w:
            w.write(r.read())
    tree = ET.parse(path)
    root = tree.getroot()
    changed = 0
    for ctx in root.findall('context'):
        ctx_name = ctx.find('name').text if ctx.find('name') is not None else ''
        for msg in ctx.findall('message'):
            src = msg.find('source')
            trans = msg.find('translation')
            if trans is None or src is None:
                continue
            if trans.get('type') == 'unfinished':
                key = (ctx_name, src.text or '')
                suggestion = en_sources.get(key, src.text or '')
                trans.text = suggestion
                if 'type' in trans.attrib:
                    del trans.attrib['type']
                changed += 1
    if changed > 0:
        tree.write(path, encoding='utf-8', xml_declaration=True)
    summary.append((f, changed, bak))

print('Applied suggestions summary:')
for f,changed,bak in summary:
    print(f'{f}: {changed} entries updated (backup: {os.path.basename(bak)})')

print('\nNext step: run lrelease to regenerate QM files (e.g., run ..\\lrelease_all.bat)')
