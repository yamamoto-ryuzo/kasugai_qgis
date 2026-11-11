# -*- coding: utf-8 -*-
"""
QMファイル生成スクリプト
lrelease.exeを使用してTS翻訳ファイルからQMファイルを生成します
"""

import os
import subprocess
import sys

# プラグインディレクトリ
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LRELEASE_PATH = r'C:\Qt\linguist_6.9.1\lrelease.exe'

# 対応言語
LANGUAGES = ['en', 'fr', 'de', 'es', 'it', 'pt', 'ja', 'zh', 'ru', 'hi']

def generate_qm_files():
    """各言語のTSファイルからQMファイルを生成"""
    
    if not os.path.exists(LRELEASE_PATH):
        print(f'エラー: lrelease.exeが見つかりません: {LRELEASE_PATH}')
        return False
    
    i18n_dir = os.path.join(PLUGIN_DIR, 'i18n')
    if not os.path.exists(i18n_dir):
        print(f'エラー: i18nディレクトリが見つかりません: {i18n_dir}')
        return False
    
    success_count = 0
    fail_count = 0
    
    for lang in LANGUAGES:
        ts_file = os.path.join(i18n_dir, f'geo_import_{lang}.ts')
        qm_file = os.path.join(i18n_dir, f'geo_import_{lang}.qm')
        
        if not os.path.exists(ts_file):
            print(f'警告: TSファイルが見つかりません: {ts_file}')
            fail_count += 1
            continue
        
        print(f'QMファイルを生成中: {lang}')
        
        try:
            result = subprocess.run(
                [LRELEASE_PATH, ts_file, '-qm', qm_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                print(f'  ✓ 成功: {qm_file}')
                success_count += 1
            else:
                print(f'  ✗ 失敗: {lang}')
                print(f'    stdout: {result.stdout}')
                print(f'    stderr: {result.stderr}')
                fail_count += 1
                
        except subprocess.TimeoutExpired:
            print(f'  ✗ タイムアウト: {lang}')
            fail_count += 1
        except Exception as e:
            print(f'  ✗ エラー: {lang} - {e}')
            fail_count += 1
    
    print(f'\n=== 結果 ===')
    print(f'成功: {success_count}個')
    print(f'失敗: {fail_count}個')
    
    return fail_count == 0

if __name__ == '__main__':
    success = generate_qm_files()
    sys.exit(0 if success else 1)
