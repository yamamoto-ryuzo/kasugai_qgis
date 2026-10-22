# -*- coding: utf-8 -*-
"""
XML診断ツール - XMLファイルの問題を診断するためのユーティリティ
"""

import os
# defusedxml を vendored 同梱し利用(実体宣言/外部参照をパーサ層で拒否)
# 加えて _reject_unsafe_xml で DOCTYPE/ENTITY を事前拒否
try:
    from .defusedxml import ElementTree as ET
except ImportError:
    # スタンドアロン実行時(プラグインディレクトリを sys.path に追加)用
    from defusedxml import ElementTree as ET
from xml.parsers.expat import ExpatError


def _reject_unsafe_xml(text):
    """DOCTYPE/ENTITY宣言を含むXMLを拒否する(XXE/entity展開対策)。"""
    probe = text if isinstance(text, str) else text.decode('utf-8', 'ignore')
    if '<!DOCTYPE' in probe or '<!ENTITY' in probe:
        raise ET.ParseError('DOCTYPE/ENTITY declarations are not allowed')


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
            result['recommendations'].append("file does not exist")
            return result

        # ファイルサイズ確認
        result['file_size'] = os.path.getsize(file_path)
        if result['file_size'] == 0:
            result['recommendations'].append("file is empty")
            return result

        # 読み取り権限確認
        result['file_readable'] = os.access(file_path, os.R_OK)
        if not result['file_readable']:
            result['recommendations'].append("no read permission for file")
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
            except UnicodeDecodeError:  # nosec B112  # 設計上の許容
                continue

        if result['encoding_detected'] is None:
            result['recommendations'].append("could not detect character encoding")
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
                    _reject_unsafe_xml(xml_content)
                    root = ET.fromstring(xml_content)  # 直上でDOCTYPE/ENTITYを拒否済み
                    result['xml_valid'] = True
                    result['root_element'] = root.tag
                    result['element_count'] = len(list(root.iter()))
                    xml_parsed = True
                    break

                except (ET.ParseError, UnicodeDecodeError):  # nosec B112  # 設計上の許容
                    continue
                except Exception:  # nosec B112  # 設計上の許容
                    continue

            if not xml_parsed:
                # 従来の方法も試す
                with open(file_path, 'rb') as f:
                    raw = f.read()
                _reject_unsafe_xml(raw)
                root = ET.fromstring(raw)  # 直上でDOCTYPE/ENTITYを拒否済み
                result['xml_valid'] = True
                result['root_element'] = root.tag
                result['element_count'] = len(list(root.iter()))

        except ET.ParseError as e:
            result['xml_error'] = str(e)
            result['recommendations'].append(f"XML syntax error: {e}")

        except ExpatError as e:
            result['xml_error'] = str(e)
            result['recommendations'].append(f"XML parse error: {e}")

        except Exception as e:
            result['xml_error'] = str(e)
            result['recommendations'].append(f"unexpected error: {e}")

        # 推奨事項の追加
        if result['xml_valid']:
            if result['element_count'] < 5:
                result['recommendations'].append("few elements found; data may be incomplete")
            else:
                result['recommendations'].append("XML file can be parsed successfully")
        else:
            if result['xml_error'] and 'multi-byte encodings are not supported' in result['xml_error']:
                result['recommendations'].append("multibyte encoding issue. Use the improved XML loader")
            elif result['xml_error'] and 'encoding' in result['xml_error'].lower():
                result['recommendations'].append("encoding issue. Check the file character encoding")

        if result['first_lines']:
            first_line = result['first_lines'][0] if result['first_lines'] else ""
            if not first_line.startswith('<?xml'):
                result['recommendations'].append("XML declaration not found")
            elif 'Shift_JIS' in first_line or 'shift_jis' in first_line:
                result['recommendations'].append("Shift_JIS encoding detected. Processable with the improved XML loader")

    except Exception as e:
        result['recommendations'].append(f"error during diagnosis: {e}")

    return result


def print_diagnosis(file_path):
    """
    XMLファイルの診断結果を出力する

    :param file_path: XMLファイルのパス
    """
    print(f"=== XML diagnosis: {file_path} ===")

    result = diagnose_xml_file(file_path)

    print(f"file exists: {result['file_exists']}")
    print(f"readable: {result['file_readable']}")
    print(f"file size: {result['file_size']} bytes")
    print(f"detected encoding: {result['encoding_detected']}")
    print(f"XML valid: {result['xml_valid']}")

    if result['xml_error']:
        print(f"XML error: {result['xml_error']}")

    if result['root_element']:
        print(f"root element: {result['root_element']}")

    print(f"element count: {result['element_count']}")

    if result['first_lines']:
        print("first lines of file:")
        for i, line in enumerate(result['first_lines'][:5], 1):
            print(f"  {i}: {line[:100]}{'...' if len(line) > 100 else ''}")

    if result['recommendations']:
        print("recommendations:")
        for rec in result['recommendations']:
            print(f"  - {rec}")

    print("=" * 50)


if __name__ == "__main__":
    # テスト用
    import sys
    if len(sys.argv) > 1:
        print_diagnosis(sys.argv[1])
    else:
        print("usage: python xml_diagnostics.py <XML file path>")
