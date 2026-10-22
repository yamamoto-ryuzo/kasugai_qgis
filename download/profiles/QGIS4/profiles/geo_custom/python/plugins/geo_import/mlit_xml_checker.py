#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MLIT XML checker - 国土交通省XMLの診断ツール

XMLファイルのタイプを識別し、絵文字付きレイヤ名を表示するテストツール
"""

import os
import sys


def diagnose_xml_type(xml_file_path):
    """XMLファイルのタイプを診断し、絵文字付きレイヤ名を表示"""

    # XMLAttributeLoaderをインポート
    try:
        # パッケージとして実行される場合とスタンドアロンの場合を考慮
        if __name__ == "__main__":
            # スタンドアロン実行の場合
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from xml_attribute_loader import XmlAttributeLoader
        else:
            from .xml_attribute_loader import XmlAttributeLoader
    except ImportError as e:
        print(f"failed to import XMLAttributeLoader: {e}")
        return

    print(f"\nXML file diagnosis: {os.path.basename(xml_file_path)}")
    print("=" * 60)

    # ダミーのifaceでXmlAttributeLoaderを作成
    xml_loader = XmlAttributeLoader(None)

    try:
        # XMLファイルの基本チェック
        if not xml_loader._is_valid_xml_file(xml_file_path):
            print("not a valid XML file")
            return

        print("XML format check: OK")

        # MLIT XML判定
        is_mlit, xml_type, confidence, details = xml_loader.is_mlit_xml(xml_file_path)

        print("\nXML type identification result:")
        print(f"   type: {xml_type}")
        print(f"   MLIT XML: {'yes' if is_mlit else 'no'}")
        print(f"   confidence: {confidence:.2f}")

        if details:
            print("\ndetails:")
            for key, value in details.items():
                if key != 'file_name':
                    print(f"   {key}: {value}")

        # グループ化テスト
        xml_groups = xml_loader._group_xml_files_by_type([xml_file_path])

        print("\ngrouping result:")
        for group_type, files in xml_groups.items():
            print(f"   group: {group_type}")
            print(f"   file count: {len(files)}")

        print(f"\nfinal layer name: {xml_type}")

    except Exception as e:
        print(f"diagnosis error: {e}")
        import traceback
        traceback.print_exc()


def test_all_xml_types():
    """test_mlit_xml_typesディレクトリの全XMLファイルをテスト"""

    test_dir = "test_mlit_xml_types"
    if not os.path.exists(test_dir):
        print(f"test directory not found: {test_dir}")
        print("run test_mlit_xml_types.py first to create test files")
        return

    xml_files = [f for f in os.listdir(test_dir) if f.endswith('.xml')]

    if not xml_files:
        print(f"no XML files in {test_dir}")
        return

    print(f"testing {len(xml_files)} XML files")
    print("=" * 80)

    for xml_file in sorted(xml_files):
        xml_path = os.path.join(test_dir, xml_file)
        diagnose_xml_type(xml_path)
        print()


def main():
    """メイン関数"""
    if len(sys.argv) > 1:
        # 特定のファイルをテスト
        xml_file_path = sys.argv[1]
        if os.path.exists(xml_file_path):
            diagnose_xml_type(xml_file_path)
        else:
            print(f"file not found: {xml_file_path}")
    else:
        # 全テストファイルをテスト
        test_all_xml_types()


if __name__ == "__main__":
    main()
