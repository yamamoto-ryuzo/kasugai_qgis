#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TSファイルを解析して未翻訳エントリを言語ごとに出力するスクリプト
出力: i18n/reports/unfinished_<lang>.txt
"""
import os
import xml.etree.ElementTree as ET

here = os.path.dirname(os.path.abspath(__file__))
reports_dir = os.path.join(here, 'reports')
if not os.path.exists(reports_dir):
    os.makedirs(reports_dir, exist_ok=True)

files = [f for f in os.listdir(here) if f.startswith('geo_import_') and f.endswith('.ts')]
summary = []
for fname in sorted(files):
    path = os.path.join(here, fname)
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as e:
        print(f'Error parsing {fname}: {e}')
        continue

    lang = root.get('language') or fname.replace('geo_import_', '').replace('.ts','')
    out_lines = []
    count = 0
    for context in root.findall('context'):
        ctx_name = context.find('name').text if context.find('name') is not None else ''
        for message in context.findall('message'):
            src = message.find('source')
            trans = message.find('translation')
            if trans is None:
                continue
            ttype = trans.get('type')
            if ttype == 'unfinished':
                count += 1
                source_text = src.text if src is not None else ''
                # gather locations
                locs = []
                for loc in message.findall('location'):
                    fname_loc = loc.get('filename') or ''
                    line_loc = loc.get('line') or ''
                    locs.append(f'{fname_loc}:{line_loc}')
                if not locs:
                    locs = ['(no location)']
                out_lines.append('---')
                out_lines.append(f'Context: {ctx_name}')
                out_lines.append(f'Locations: {", ".join(locs)}')
                out_lines.append('Source:')
                out_lines.append(source_text if source_text is not None else '')
                trans_text = trans.text or ''
                out_lines.append('Existing translation (empty/unfinished):')
                out_lines.append(trans_text)

    out_path = os.path.join(reports_dir, f'unfinished_{lang}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f'# Unfinished translations report for {fname} (language={lang})\n')
        f.write(f'# Count: {count}\n\n')
        if out_lines:
            f.write('\n'.join(out_lines))
        else:
            f.write('# No unfinished entries found.\n')
    summary.append((lang, fname, count, out_path))

# also write a combined summary
summary_path = os.path.join(reports_dir, 'summary_unfinished.txt')
with open(summary_path, 'w', encoding='utf-8') as sf:
    sf.write('Unfinished translations summary\n')
    sf.write('================================\n')
    for lang, fname, count, out_path in summary:
        sf.write(f'{lang} ({fname}): {count} entries -> {out_path}\n')

print('Reports written to:', reports_dir)
print('\n'.join([f'{lang}: {count}' for lang,_,count,_ in summary]))
