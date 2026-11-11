# -*- coding: utf-8 -*-
"""
TSファイル更新スクリプト
pylupdate5を使用して翻訳ファイルを更新します
"""

import os
import subprocess
import sys

# プラグインディレクトリ
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# pylupdate5のパスを探索
def find_pylupdate():
    """pylupdate5/pylupdate6のパスを検索"""
    # 一般的なパスをチェック
    possible_paths = [
        'pylupdate5',
        'pylupdate6',
        r'C:\Qt\6.9.1\msvc2019_64\bin\lupdate.exe',
        r'C:\Qt\linguist_6.9.1\lupdate.exe',
        r'C:\Python39\Scripts\pylupdate5.exe',
        r'C:\Python310\Scripts\pylupdate5.exe',
        r'C:\Python311\Scripts\pylupdate5.exe',
    ]
    
    for path in possible_paths:
        try:
            result = subprocess.run([path, '-version'], 
                                    capture_output=True, 
                                    text=True, 
                                    timeout=5)
            if result.returncode == 0:
                print(f'使用するpylupdate: {path}')
                return path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    
    return None

def update_ts_files():
    """TSファイルを更新"""
    pylupdate = find_pylupdate()
    
    if not pylupdate:
        print('エラー: pylupdate5/pylupdate6が見つかりません')
        print('PyQt5またはPyQt6をインストールしてください')
        return False
    
    # プロジェクトファイルのパス
    pro_file = os.path.join(PLUGIN_DIR, 'geo_import.pro')
    
    if not os.path.exists(pro_file):
        print(f'エラー: プロジェクトファイルが見つかりません: {pro_file}')
        return False
    
    print(f'TSファイルを更新中: {pro_file}')
    
    # pylupdate5を実行
    try:
        result = subprocess.run(
            [pylupdate, '-verbose', pro_file],
            cwd=PLUGIN_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        
        if result.returncode == 0:
            print('TSファイルの更新が完了しました')
            return True
        else:
            print(f'エラー: pylupdate5の実行に失敗しました (終了コード: {result.returncode})')
            return False
            
    except subprocess.TimeoutExpired:
        print('エラー: pylupdate5の実行がタイムアウトしました')
        return False
    except Exception as e:
        print(f'エラー: {e}')
        return False

if __name__ == '__main__':
    success = update_ts_files()
    sys.exit(0 if success else 1)
