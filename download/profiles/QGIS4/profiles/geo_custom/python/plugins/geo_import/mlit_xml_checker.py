#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MLIT XML checker - 国土交通省XMLの診断ツール

XMLファイルのタイプを識別し、絵文字付きレイヤ名を表示するテストツール
"""

import os
import sys
from xml.etree import ElementTree as ET


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
        print(f"XMLAttributeLoaderのインポートに失敗しました: {e}")
        return
    
    print(f"\n🔍 XMLファイル診断: {os.path.basename(xml_file_path)}")
    print("=" * 60)
    
    # ダミーのifaceでXmlAttributeLoaderを作成
    xml_loader = XmlAttributeLoader(None)
    
    try:
        # XMLファイルの基本チェック
        if not xml_loader._is_valid_xml_file(xml_file_path):
            print("❌ 有効なXMLファイルではありません")
            return
        
        print("✅ XMLファイル形式チェック: OK")
        
        # MLIT XML判定
        is_mlit, xml_type, confidence, details = xml_loader.is_mlit_xml(xml_file_path)
        
        print(f"\n📋 XMLタイプ識別結果:")
        print(f"   タイプ: {xml_type}")
        print(f"   MLIT XML: {'はい' if is_mlit else 'いいえ'}")
        print(f"   信頼度: {confidence:.2f}")
        
        if details:
            print(f"\n📊 詳細情報:")
            for key, value in details.items():
                if key != 'file_name':
                    print(f"   {key}: {value}")
        
        # グループ化テスト
        xml_groups = xml_loader._group_xml_files_by_type([xml_file_path])
        
        print(f"\n🎨 グループ化結果:")
        for group_type, files in xml_groups.items():
            print(f"   グループ: {group_type}")
            print(f"   ファイル数: {len(files)}")
        
        print(f"\n🏷️ 最終レイヤ名: {xml_type}")
        
    except Exception as e:
        print(f"❌ 診断エラー: {str(e)}")
        import traceback
        traceback.print_exc()


def test_all_xml_types():
    """test_mlit_xml_typesディレクトリの全XMLファイルをテスト"""
    
    test_dir = "test_mlit_xml_types"
    if not os.path.exists(test_dir):
        print(f"❌ テストディレクトリが見つかりません: {test_dir}")
        print("先にtest_mlit_xml_types.pyを実行してテストファイルを作成してください")
        return
    
    xml_files = [f for f in os.listdir(test_dir) if f.endswith('.xml')]
    
    if not xml_files:
        print(f"❌ {test_dir}にXMLファイルが見つかりません")
        return
    
    print(f"🎯 {len(xml_files)}個のXMLファイルをテストします")
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
            print(f"❌ ファイルが見つかりません: {xml_file_path}")
    else:
        # 全テストファイルをテスト
        test_all_xml_types()


if __name__ == "__main__":
    main()