# -*- coding: utf-8 -*-
"""
XML診断ツール - XMLファイルの問題を診断するためのユーティリティ
"""

import os
import xml.etree.ElementTree as ET
from xml.parsers.expat import ExpatError


def diagnose_xml_file(file_path):
    """
    XMLファイルの問題を診断する
    
    :param file_path: XMLファイルのパス
    :return: 診断結果の辞書
    """
    result = {
        'file_exists': False,
        'file_readable': False,
        'file_size': 0,
        'encoding_detected': None,
        'xml_valid': False,
        'xml_error': None,
        'root_element': None,
        'element_count': 0,
        'first_lines': [],
        'recommendations': []
    }
    
    try:
        # ファイル存在確認
        result['file_exists'] = os.path.exists(file_path)
        if not result['file_exists']:
            result['recommendations'].append("ファイルが存在しません")
            return result
        
        # ファイルサイズ確認
        result['file_size'] = os.path.getsize(file_path)
        if result['file_size'] == 0:
            result['recommendations'].append("ファイルが空です")
            return result
        
        # 読み取り権限確認
        result['file_readable'] = os.access(file_path, os.R_OK)
        if not result['file_readable']:
            result['recommendations'].append("ファイルの読み取り権限がありません")
            return result
        
        # エンコーディング検出とファイル内容確認
        encodings = ['utf-8', 'utf-8-sig', 'shift_jis', 'cp932', 'iso-2022-jp', 'euc-jp']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    lines = []
                    for i in range(10):  # 最初の10行を読む
                        line = f.readline()
                        if not line:
                            break
                        lines.append(line.strip())
                    result['first_lines'] = lines
                    result['encoding_detected'] = encoding
                    break
            except UnicodeDecodeError:
                continue
        
        if result['encoding_detected'] is None:
            result['recommendations'].append("文字エンコーディングを検出できませんでした")
            return result
        
        # XML構文チェック
        try:
            # 複数のエンコーディングでXML解析を試行
            xml_parsed = False
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        xml_content = f.read()
                    
                    # エンコーディング宣言を修正
                    import re
                    xml_declaration_pattern = r'<\?xml\s+version\s*=\s*["\'][^"\']*["\']\s*encoding\s*=\s*["\'][^"\']*["\']\s*\?>'
                    match = re.search(xml_declaration_pattern, xml_content, re.IGNORECASE)
                    if match:
                        new_declaration = '<?xml version="1.0" encoding="UTF-8"?>'
                        xml_content = xml_content.replace(match.group(0), new_declaration)
                    
                    # 文字列からXMLを解析
                    root = ET.fromstring(xml_content)
                    result['xml_valid'] = True
                    result['root_element'] = root.tag
                    result['element_count'] = len(list(root.iter()))
                    xml_parsed = True
                    break
                    
                except (ET.ParseError, UnicodeDecodeError):
                    continue
                except Exception:
                    continue
            
            if not xml_parsed:
                # 従来の方法も試す
                tree = ET.parse(file_path)
                root = tree.getroot()
                result['xml_valid'] = True
                result['root_element'] = root.tag
                result['element_count'] = len(list(root.iter()))
            
        except ET.ParseError as e:
            result['xml_error'] = str(e)
            result['recommendations'].append(f"XML構文エラー: {str(e)}")
            
        except ExpatError as e:
            result['xml_error'] = str(e)
            result['recommendations'].append(f"XML解析エラー: {str(e)}")
            
        except Exception as e:
            result['xml_error'] = str(e)
            result['recommendations'].append(f"予期しないエラー: {str(e)}")
        
        # 推奨事項の追加
        if result['xml_valid']:
            if result['element_count'] < 5:
                result['recommendations'].append("要素数が少ないため、データが不完全な可能性があります")
            else:
                result['recommendations'].append("XMLファイルは正常に解析できます")
        else:
            if result['xml_error'] and 'multi-byte encodings are not supported' in result['xml_error']:
                result['recommendations'].append("マルチバイトエンコーディングの問題です。改善されたXMLローダーを使用してください")
            elif result['xml_error'] and 'encoding' in result['xml_error'].lower():
                result['recommendations'].append("エンコーディングの問題があります。ファイルの文字コードを確認してください")
        
        if result['first_lines']:
            first_line = result['first_lines'][0] if result['first_lines'] else ""
            if not first_line.startswith('<?xml'):
                result['recommendations'].append("XML宣言が見つかりません")
            elif 'Shift_JIS' in first_line or 'shift_jis' in first_line:
                result['recommendations'].append("Shift_JISエンコーディングが検出されました。改善されたXMLローダーで処理可能です")
        
    except Exception as e:
        result['recommendations'].append(f"診断中にエラーが発生しました: {str(e)}")
    
    return result


def print_diagnosis(file_path):
    """
    XMLファイルの診断結果を出力する
    
    :param file_path: XMLファイルのパス
    """
    print(f"=== XML診断結果: {file_path} ===")
    
    result = diagnose_xml_file(file_path)
    
    print(f"ファイル存在: {result['file_exists']}")
    print(f"読み取り可能: {result['file_readable']}")
    print(f"ファイルサイズ: {result['file_size']} bytes")
    print(f"検出エンコーディング: {result['encoding_detected']}")
    print(f"XML妥当性: {result['xml_valid']}")
    
    if result['xml_error']:
        print(f"XMLエラー: {result['xml_error']}")
    
    if result['root_element']:
        print(f"ルート要素: {result['root_element']}")
    
    print(f"要素数: {result['element_count']}")
    
    if result['first_lines']:
        print("ファイルの最初の数行:")
        for i, line in enumerate(result['first_lines'][:5], 1):
            print(f"  {i}: {line[:100]}{'...' if len(line) > 100 else ''}")
    
    if result['recommendations']:
        print("推奨事項:")
        for rec in result['recommendations']:
            print(f"  - {rec}")
    
    print("=" * 50)


if __name__ == "__main__":
    # テスト用
    import sys
    if len(sys.argv) > 1:
        print_diagnosis(sys.argv[1])
    else:
        print("使用方法: python xml_diagnostics.py <XMLファイルパス>")