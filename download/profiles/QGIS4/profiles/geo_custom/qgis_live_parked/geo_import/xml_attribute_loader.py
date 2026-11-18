# -*- coding: utf-8 -*-
"""
/***************************************************************************
 XML Attribute Loader
                                 A QGIS plugin component
 Load XML files as simple attribute tables (no geometry)
                              -------------------
        begin                : 2025-09-20
        copyright            : (C) 2025 by yamamoto-ryuzo
        email                : ryuzo@example.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
# defusedxml を vendored 同梱し利用(実体宣言/外部参照をパーサ層で拒否)
# 加えて _reject_unsafe_xml で DOCTYPE/ENTITY を事前拒否
try:
    from .defusedxml import ElementTree as ET
except ImportError:
    # スタンドアロン実行時(プラグインディレクトリを sys.path に追加)用
    from defusedxml import ElementTree as ET
from qgis.PyQt.QtCore import QVariant, QCoreApplication
from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsProject,
    Qgis,
    QgsMessageLog
)

# Unified log tag for this repository
LOG_TAG = 'geo_import'


def _reject_unsafe_xml(text):
    """DOCTYPE/ENTITY宣言を含むXMLを拒否する(XXE/entity展開対策)。"""
    if '<!DOCTYPE' in text or '<!ENTITY' in text:
        raise ET.ParseError('DOCTYPE/ENTITY declarations are not allowed')


class XmlAttributeLoader:
    """XMLファイルを単純な属性テーブルとして読み込むクラス"""

    def __init__(self, iface):
        """
        コンストラクタ
        :param iface: QGIS interface instance
        """
        self.iface = iface

        # 国土交通省関連XMLの識別パターン
        self.mlit_xml_patterns = {
            'electronic_delivery': ['電子納品', '工事完成図書', '土木設計業務', 'CALS/EC', 'OFFICE-INDEX', 'CONSTRUCTION_NAME', 'OFFICE_NAME'],
            'survey_results': ['測量成果', '基準点', '水準点', '多角点', 'SURVEY', 'POINT_DATA', 'COORDINATE_X'],
            'jpgis': ['JPGIS', 'GM_', 'GML', 'gml:', 'xmlns:gml', 'ksj_app_schema', 'AdministrativeBoundary'],
            'cad_sxf': ['SXF', 'CAD', 'P21', 'EXPRESS', 'SXF_DATA', 'LAYER_NAME', 'FEATURE_CODE'],
            'estimation': ['積算', '工種', '種別', '細別', '単価', 'COST', 'COST_ESTIMATION', 'UNIT_PRICE'],
            'facility_mgmt': ['施設', '設備', '機器', '点検', '維持管理', 'FACILITY', 'FACILITY_MANAGEMENT', 'INSPECTION_RECORD'],
            'geography': ['地理空間', '座標', '測地', 'COORDINATE', 'DATUM', 'GEOGRAPHIC_DATA', 'LOCATION_INFO'],
            'construction': ['施工', 'PROJECT_INFO', 'WORK_RECORD']  # 'CONSTRUCTION'と'WORK'を除去してより具体的に
        }

    def load_multiple_xml_merged(self, xml_file_paths, layer_name=None):
        """
        複数のXMLファイルを種類別にマージして読み込む

        :param xml_file_paths: XMLファイルパスのリスト
        :param layer_name: ベースレイヤ名
        :return: 作成されたレイヤのリスト
        """
        QgsMessageLog.logMessage(
            f"*** load_multiple_xml_merged started: {len(xml_file_paths)} files ***",
            LOG_TAG,
            Qgis.MessageLevel.Info
        )
        for file_path in xml_file_paths:
            QgsMessageLog.logMessage(
                f"  file to process: {file_path}",
                LOG_TAG,
                Qgis.MessageLevel.Info
            )

        if not xml_file_paths:
            return []

        # XMLファイルを種類別に分類
        xml_groups = self._group_xml_files_by_type(xml_file_paths)

        QgsMessageLog.logMessage(
            f"XML grouping result: {len(xml_groups)} types",
            LOG_TAG,
            Qgis.MessageLevel.Info
        )
        for xml_type, file_paths in xml_groups.items():
            QgsMessageLog.logMessage(
                f"  {xml_type}: {len(file_paths)} files",
                LOG_TAG,
                Qgis.MessageLevel.Info
            )

        created_layers = []

        for xml_type, file_paths in xml_groups.items():
            if len(file_paths) == 1:
                # 単一ファイル（個別のsource_file情報はload_xml_as_attribute_tableで設定済み）
                layer = self.load_xml_as_attribute_table(file_paths[0])
                if layer:
                    created_layers.append(layer)
            else:
                # 複数ファイルの場合はマージ
                merged_layer = self._merge_xml_files_by_type(file_paths, xml_type, layer_name)
                if merged_layer:
                    created_layers.append(merged_layer)

        return created_layers

    def _group_xml_files_by_type(self, xml_file_paths):
        """
        XMLファイルを種類別にグループ化

        :param xml_file_paths: XMLファイルパスのリスト
        :return: {xml_type: [file_paths]} の辞書
        """
        groups = {}

        for file_path in xml_file_paths:
            try:
                is_mlit, xml_type, confidence, details = self.is_mlit_xml(file_path)

                # 信頼度が低い場合は汎用XMLとして扱う
                if confidence < 0.3:
                    xml_type = "Generic XML"

                if xml_type not in groups:
                    groups[xml_type] = []
                groups[xml_type].append(file_path)

            except Exception:
                # エラーの場合は汎用XMLとして分類
                if "Generic XML" not in groups:
                    groups["Generic XML"] = []
                groups["Generic XML"].append(file_path)

        return groups

    def _merge_xml_files_by_type(self, file_paths, xml_type, base_layer_name=None):
        """
        同じタイプのXMLファイルをマージして一つのレイヤを作成

        :param file_paths: 同じタイプのXMLファイルパスのリスト
        :param xml_type: XMLの種類
        :param base_layer_name: ベースレイヤ名
        :return: マージされたQgsVectorLayer
        """
        if not file_paths:
            return None

        # レイヤ名の決定
        if len(file_paths) == 1:
            # 単一ファイルの場合 - 元のファイル名ベースのレイヤ名を使用
            filename = os.path.splitext(os.path.basename(file_paths[0]))[0]
            layer_name = f"XML_Attributes_{filename}"
        else:
            # 複数ファイルの場合 - XMLタイプ名に統合情報を追加
            layer_name = f"{xml_type} (merged {len(file_paths)} files)"

        if len(file_paths) == 1:
            QgsMessageLog.logMessage(
                f"XML processing: {xml_type} - {os.path.basename(file_paths[0])}",
                LOG_TAG,
                Qgis.MessageLevel.Info
            )
        else:
            QgsMessageLog.logMessage(
                f"XML merge started: {xml_type} - {len(file_paths)} files",
                LOG_TAG,
                Qgis.MessageLevel.Info
            )

        # 最初のファイルをベースとしてレイヤを作成
        base_layer = self.load_xml_as_attribute_table(file_paths[0], layer_name)
        if not base_layer:
            return None

        QgsMessageLog.logMessage(
            f"base layer created: {file_paths[0]} -> {layer_name}",
            LOG_TAG,
            Qgis.MessageLevel.Info
        )

        # 残りのファイルを順次マージ
        for i, file_path in enumerate(file_paths[1:], 2):
            try:
                temp_layer = self.load_xml_as_attribute_table(file_path, f"temp_{i}")
                if temp_layer:
                    QgsMessageLog.logMessage(
                        f"merging file {i}: {file_path}",
                        LOG_TAG,
                        Qgis.MessageLevel.Info
                    )
                    self._merge_layer_data(base_layer, temp_layer, file_path)  # フルパスを渡す

                    # マージ完了後、一時レイヤを削除
                    QgsProject.instance().removeMapLayer(temp_layer.id())
                    QgsMessageLog.logMessage(
                        f"removing temp layer: temp_{i}",
                        LOG_TAG,
                        Qgis.MessageLevel.Info
                    )

            except Exception as e:
                QgsMessageLog.logMessage(
                    f"file merge error: {file_path} - {e}",
                    LOG_TAG,
                    Qgis.MessageLevel.Warning
                )

        # 完了メッセージ
        if len(file_paths) == 1:
            success_message = f"XML load completed: {layer_name} - {base_layer.featureCount()} features"
            QgsMessageLog.logMessage(success_message, LOG_TAG, Qgis.MessageLevel.Success)
            self._show_success(success_message)
        else:
            success_message = f"XML merge completed: {layer_name} - {len(file_paths)} files, {base_layer.featureCount()} features"
            QgsMessageLog.logMessage(success_message, LOG_TAG, Qgis.MessageLevel.Success)
            self._show_success(success_message)

        # マージされたレイヤをQGISプロジェクトに追加
        QgsProject.instance().addMapLayer(base_layer)

        return base_layer

    def load_xml_as_attribute_table(self, xml_file_path, layer_name=None):
        """
        XMLファイルを属性テーブル（ジオメトリなし）として読み込む

        :param xml_file_path: XMLファイルのパス
        :param layer_name: レイヤ名（指定しない場合はファイル名を使用）
        :return: 作成されたQgsVectorLayer、エラーの場合はNone
        """
        # 呼び出し元の特定のためのログ
        import traceback
        call_stack = traceback.format_stack()
        caller_info = call_stack[-2] if len(call_stack) > 1 else "unknown"

        QgsMessageLog.logMessage(
            f"*** load_xml_as_attribute_table called: {xml_file_path} ***",
            LOG_TAG,
            Qgis.MessageLevel.Info
        )
        QgsMessageLog.logMessage(
            f"caller: {caller_info.strip()}",
            LOG_TAG,
            Qgis.MessageLevel.Info
        )

        try:
            # ファイルパスの正規化
            xml_file_path = os.path.normpath(xml_file_path)

            # ファイルの存在確認
            if not os.path.exists(xml_file_path):
                self._show_error(QCoreApplication.translate('GeoImport', "XML file not found: {0}").format(xml_file_path))
                return None

            # ファイルサイズの確認
            file_size = os.path.getsize(xml_file_path)
            if file_size == 0:
                self._show_error(QCoreApplication.translate('GeoImport', "XML file is empty: {0}").format(xml_file_path))
                return None

            # ファイルの読み取り権限確認
            if not os.access(xml_file_path, os.R_OK):
                self._show_error(QCoreApplication.translate('GeoImport', "No read permission for XML file: {0}").format(xml_file_path))
                return None

            # レイヤ名の設定
            if layer_name is None:
                layer_name = f"XML_Attributes_{os.path.splitext(os.path.basename(xml_file_path))[0]}"

            # ファイルの内容を事前にチェック
            if not self._validate_xml_file(xml_file_path):
                return None

            # XMLファイルを適切なエンコーディングで解析
            try:
                root = self._parse_xml_with_encoding(xml_file_path)
                if root is None:
                    return None

                # 国土交通省XMLかどうかの詳細診断
                is_mlit, xml_type, confidence, details = self.is_mlit_xml(xml_file_path)

                # 診断結果をログに記録
                QgsMessageLog.logMessage(
                    f"XML diagnosis - type: {xml_type}, MLIT XML: {is_mlit}, confidence: {confidence:.2f}",
                    LOG_TAG,
                    Qgis.MessageLevel.Info
                )

                # 高い信頼度の場合は詳細情報も記録
                if confidence >= 0.5:
                    if details.get('mlit_keywords'):
                        QgsMessageLog.logMessage(
                            f"detected keywords: {', '.join(details['mlit_keywords'][:3])}",
                            LOG_TAG,
                            Qgis.MessageLevel.Info
                        )
                    if details.get('structure_indicators'):
                        QgsMessageLog.logMessage(
                            f"structure indicators: {', '.join(details['structure_indicators'][:2])}",
                            LOG_TAG,
                            Qgis.MessageLevel.Info
                        )

            except Exception as e:
                error_msg = QCoreApplication.translate('GeoImport', "Error while loading XML file: {0}").format(e) + "\n"
                error_msg += f"file: {xml_file_path}"
                self._show_error(error_msg)
                return None

            # XMLの構造を分析してフィールドを自動検出
            fields = self._analyze_xml_structure(root)

            if not fields:
                self._show_error(QCoreApplication.translate('GeoImport', "Could not detect attribute fields in XML file"))
                return None

            # メモリレイヤを作成（ジオメトリなし）
            layer = QgsVectorLayer("None", layer_name, "memory")
            if not layer.isValid():
                self._show_error(QCoreApplication.translate('GeoImport', "Failed to create memory layer"))
                return None

            provider = layer.dataProvider()

            # source_fileフィールドを追加
            source_field = QgsField("source_file", QVariant.String)
            source_field.setLength(500)  # フルパス用に長さを拡張
            fields.append(source_field)

            # フィールドを追加
            provider.addAttributes(fields)
            layer.updateFields()

            # XMLからデータを抽出してフィーチャを作成
            features = self._extract_features_from_xml(root, fields)

            if not features:
                self._show_warning(QCoreApplication.translate('GeoImport', "No data extracted from XML file"))

            # フィーチャをレイヤに追加
            provider.addFeatures(features)
            layer.updateExtents()

            # source_file情報をフルパスで設定
            self._update_source_file_info(layer, xml_file_path)

            # プロジェクトに追加
            QgsProject.instance().addMapLayer(layer)

            # 成功メッセージ
            self._show_success(QCoreApplication.translate('GeoImport', "XML file loaded as attribute table: {0} ({1} features)").format(layer.name(), len(features)))

            # ログに記録
            QgsMessageLog.logMessage(
                f"XML loaded as attribute table: {xml_file_path} -> {layer.name()} ({len(features)} records)",
                LOG_TAG,
                Qgis.MessageLevel.Info
            )

            return layer

        except Exception as e:
            error_msg = QCoreApplication.translate('GeoImport', "Failed to load XML file: {0}").format(e) + "\n"
            error_msg += f"file: {xml_file_path}\n"
            error_msg += QCoreApplication.translate('GeoImport', "See the QGIS log panel for detailed error information.")
            self._show_error(error_msg)
            QgsMessageLog.logMessage(
                f"Error loading XML: {str(e)} from file: {xml_file_path}",
                LOG_TAG,
                Qgis.MessageLevel.Critical
            )
            return None

    def _validate_xml_file(self, xml_file_path):
        """
        XMLファイルの基本的な妥当性をチェック

        :param xml_file_path: XMLファイルのパス
        :return: 妥当性チェックの結果（True/False）
        """
        try:
            # 複数のエンコーディングを試す
            encodings = ['utf-8', 'utf-8-sig', 'shift_jis', 'cp932', 'iso-2022-jp', 'euc-jp']

            file_content = None
            detected_encoding = None

            for encoding in encodings:
                try:
                    with open(xml_file_path, 'r', encoding=encoding) as f:
                        file_content = f.read(1000)  # 最初の1000文字を読む
                        detected_encoding = encoding
                        break
                except UnicodeDecodeError:  # nosec B112  # 設計上の許容
                    continue

            if file_content is None:
                self._show_error(QCoreApplication.translate('GeoImport', "Cannot detect character encoding of XML file: {0}").format(xml_file_path))
                return False

            # XML宣言の確認
            lines = file_content.split('\n')[:5]
            first_line = lines[0].strip() if lines else ""

            # XML宣言またはXML要素の存在確認
            has_xml_declaration = first_line.startswith('<?xml')
            has_xml_elements = any(line.strip().startswith('<') and not line.strip().startswith('<!')
                                   for line in lines if line.strip())

            if not has_xml_declaration and not has_xml_elements:
                self._show_error(QCoreApplication.translate('GeoImport', "File does not appear to be XML: {0}\nfirst line: {1}...").format(xml_file_path, first_line[:100]))
                return False

            # DTD宣言があっても問題ない
            if '<!DOCTYPE' in file_content:
                QgsMessageLog.logMessage(
                    f"DTD declaration found; continuing: {xml_file_path}",
                    LOG_TAG,
                    Qgis.MessageLevel.Info
                )

            # スタイルシート宣言があっても問題ない
            if '<?xml-stylesheet' in file_content:
                QgsMessageLog.logMessage(
                    f"stylesheet declaration found; continuing: {xml_file_path}",
                    LOG_TAG,
                    Qgis.MessageLevel.Info
                )

            # エンコーディング情報をログに記録
                QgsMessageLog.logMessage(
                    f"XML encoding detected: {detected_encoding} - {xml_file_path}",
                    LOG_TAG,
                    Qgis.MessageLevel.Info
                )

            return True

        except Exception as e:
            self._show_error(QCoreApplication.translate('GeoImport', "Error during XML pre-check: {0}").format(e))
            return False

    def _parse_xml_with_encoding(self, xml_file_path):
        """
        適切なエンコーディングでXMLファイルを解析

        :param xml_file_path: XMLファイルのパス
        :return: root 要素、失敗時は None
        """
        # 試行するエンコーディングのリスト
        encodings = ['utf-8', 'utf-8-sig', 'shift_jis', 'cp932', 'iso-2022-jp', 'euc-jp']

        for encoding in encodings:
            try:
                # ファイルを指定されたエンコーディングで読み込み
                with open(xml_file_path, 'r', encoding=encoding) as f:
                    xml_content = f.read()

                # エンコーディング宣言を修正（ElementTreeが理解できる形式に）
                xml_content = self._fix_encoding_declaration(xml_content, encoding)

                # 文字列からElementTreeオブジェクトを作成
                try:
                    _reject_unsafe_xml(xml_content)
                    root = ET.fromstring(xml_content)  # 直上でDOCTYPE/ENTITYを拒否済み

                    QgsMessageLog.logMessage(
                        f"XML file parsed successfully as {encoding}: {xml_file_path}",
                        LOG_TAG,
                        Qgis.MessageLevel.Info
                    )
                    return root

                except ET.ParseError as e:
                    QgsMessageLog.logMessage(
                        f"XML parse error with encoding {encoding}: {e}",
                        LOG_TAG,
                        Qgis.MessageLevel.Warning
                    )
                    continue

            except UnicodeDecodeError:  # nosec B112  # 設計上の許容
                # このエンコーディングでは読めない
                continue
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"read error with encoding {encoding}: {e}",
                    LOG_TAG,
                    Qgis.MessageLevel.Warning
                )
                continue

        # すべてのエンコーディングで失敗
        error_msg = "could not parse XML file; no supported encoding could read it.\n"
        error_msg += f"tried encodings: {', '.join(encodings)}\n"
        error_msg += f"file: {xml_file_path}"
        self._show_error(error_msg)

        QgsMessageLog.logMessage(
            f"All encoding attempts failed for file: {xml_file_path}",
            LOG_TAG,
            Qgis.MessageLevel.Critical
        )

        return None

    def _identify_xml_type(self, root, xml_file_path):
        """
        XMLファイルの種類を識別する（国土交通省関連のXMLに特化）

        :param root: XML root element
        :param xml_file_path: XMLファイルのパス
        :return: XMLファイルの種類（文字列）
        """
        xml_content_str = ""

        # XML全体を文字列として取得
        try:
            with open(xml_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                xml_content_str = f.read().lower()
        except Exception:  # nosec B110  # 設計上の許容
            # エンコーディングエラーでも継続
            pass

        # ルート要素の名前とその子要素を確認
        root_tag = root.tag.lower()
        if '}' in root_tag:
            root_tag = root_tag.split('}')[1]

        # 子要素の名前リストを作成
        child_tags = []
        for child in root:
            tag_name = child.tag.lower()
            if '}' in tag_name:
                tag_name = tag_name.split('}')[1]
            child_tags.append(tag_name)

        # DTD宣言からの識別
        if 'rep04.dtd' in xml_content_str or 'rep' in xml_content_str:
            return "MLIT report data"

        # 各パターンとマッチング
        for xml_type, patterns in self.mlit_xml_patterns.items():
            for pattern in patterns:
                pattern_lower = pattern.lower()
                if (pattern_lower in xml_content_str or
                    pattern_lower in root_tag or
                        any(pattern_lower in tag for tag in child_tags)):
                    type_names = {
                        'electronic_delivery': "Electronic delivery XML (CALS/EC)",
                        'survey_results': "Survey results XML (MLIT survey spec)",
                        'jpgis': "JPGIS geospatial XML",
                        'cad_sxf': "CAD/SXF XML",
                        'estimation': "Cost estimation XML (JACIC)",
                        'facility_mgmt': "Facility management XML",
                        'geography': "Geospatial XML",
                        'construction': "Construction XML"
                    }
                    return type_names.get(xml_type, f"{xml_type} XML")

        # 特定の構造からの識別
        if '報告書' in root_tag or '情報' in root_tag:
            return "Japanese XML (report/info)"
        elif 'feature' in root_tag or 'gml' in xml_content_str:
            return "GML/geospatial XML"
        elif root_tag in ['data', 'records', 'items']:
            return "Data table XML"

        return "Generic XML"

    def is_mlit_xml(self, xml_file_path):
        """
        XMLファイルが国土交通省関連のデータかどうかを判定する

        :param xml_file_path: XMLファイルのパス
        :return: (is_mlit: bool, xml_type: str, confidence: float, details: dict)
        """
        try:
            # XMLファイルを解析
            root = self._parse_xml_with_encoding(xml_file_path)
            if root is None:
                return False, "unparseable", 0.0, {}

            # 判定結果の詳細を記録
            details = {
                'file_name': os.path.basename(xml_file_path),
                'root_element': root.tag,
                'dtd_detected': False,
                'namespace_detected': [],
                'mlit_keywords': [],
                'structure_indicators': []
            }

            # XML内容を文字列として取得
            xml_content_str = ""
            try:
                with open(xml_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    xml_content_str = f.read()
                    details['file_size'] = len(xml_content_str)
            except Exception:  # nosec B110  # 設計上の許容
                pass

            xml_content_lower = xml_content_str.lower()
            confidence_score = 0.0

            # 1. DTD宣言による識別（高い信頼度）
            mlit_dtds = [
                'rep04.dtd', 'rep01.dtd', 'rep02.dtd', 'rep03.dtd',
                'cals.dtd', 'survey.dtd', 'jpgis.dtd'
            ]
            for dtd in mlit_dtds:
                if dtd in xml_content_lower:
                    details['dtd_detected'] = dtd
                    confidence_score += 0.8
                    break

            # 2. 名前空間による識別（高い信頼度）
            mlit_namespaces = [
                'jpgis.mlit.go.jp', 'gsi.go.jp', 'jacic.or.jp',
                'cals-ed.go.jp', 'nlftp.mlit.go.jp'
            ]
            for ns in mlit_namespaces:
                if ns in xml_content_lower:
                    details['namespace_detected'].append(ns)
                    confidence_score += 0.7

            # 3. ファイル命名規則による識別
            filename = os.path.basename(xml_file_path).upper()
            mlit_file_patterns = [
                'INDEX_D.XML', 'DRAWF.XML', 'SURVEY.XML', 'BORING.XML',
                'N03-', 'A31-', 'A33-', 'L02-', 'P11-', 'P12-'
            ]
            for pattern in mlit_file_patterns:
                if pattern in filename:
                    details['structure_indicators'].append(f"file name pattern: {pattern}")
                    confidence_score += 0.6
                    break

            # 4. 国土交通省特有のキーワードによる識別
            mlit_keywords = [
                # 電子納品関連
                '電子納品', 'cals/ec', '工事完成図書', '土木設計業務',
                # 測量関連
                '測量成果', '基準点', '水準点', '多角点', '測地座標',
                # 地理空間情報関連
                'jpgis', '国土数値情報', '地理空間情報', '国土地理院',
                # 建設関連
                '積算', '工種', '種別', '細別', 'jacic',
                # 報告書関連
                '報告書ファイル情報', '業務概要版', '詳細版'
            ]

            keyword_matches = 0
            for keyword in mlit_keywords:
                if keyword in xml_content_lower:
                    details['mlit_keywords'].append(keyword)
                    keyword_matches += 1

            if keyword_matches > 0:
                confidence_score += min(keyword_matches * 0.1, 0.5)

            # 5. 構造的特徴による識別
            root_tag = root.tag.lower()
            if '}' in root_tag:
                root_tag = root_tag.split('}')[1]

            # 国土交通省XML特有の構造パターン
            if root_tag in ['reportdata', '工事情報', '業務情報', '測量成果', 'survey_data']:
                details['structure_indicators'].append(f"root element: {root_tag}")
                confidence_score += 0.4

            # 子要素のパターンチェック
            child_tags = [child.tag.lower().split('}')[-1] for child in root]
            mlit_child_patterns = [
                '報告書ファイル情報', '工事管理項目', '業務管理項目',
                '測点', '観測値', '座標値', '地物', 'feature'
            ]

            for pattern in mlit_child_patterns:
                if pattern in child_tags:
                    details['structure_indicators'].append(f"child elements: {pattern}")
                    confidence_score += 0.2
                    break

            # 6. 文字エンコーディングによる補助判定
            if 'shift_jis' in xml_content_lower or 'shift-jis' in xml_content_lower:
                details['structure_indicators'].append("Shift_JIS encoding (Japanese XML)")
                confidence_score += 0.1

            # 判定結果の決定
            is_mlit = confidence_score >= 0.3

            # XMLタイプの詳細判定
            xml_type = self._identify_xml_type(root, xml_file_path)

            # 信頼度の正規化（0.0-1.0）
            confidence_score = min(confidence_score, 1.0)

            return is_mlit, xml_type, confidence_score, details

        except Exception as e:
            return False, f"error: {e}", 0.0, {'error': str(e)}

    def _fix_encoding_declaration(self, xml_content, actual_encoding):
        """
        XML宣言のエンコーディングを実際のエンコーディングに合わせて修正

        :param xml_content: XML内容（文字列）
        :param actual_encoding: 実際のエンコーディング
        :return: 修正されたXML内容
        """
        import re

        # XML宣言のパターンを検索
        xml_declaration_pattern = r'<\?xml\s+version\s*=\s*["\'][^"\']*["\']\s*encoding\s*=\s*["\'][^"\']*["\']\s*\?>'

        match = re.search(xml_declaration_pattern, xml_content, re.IGNORECASE)
        if match:
            # 既存のXML宣言をUTF-8に置換
            new_declaration = '<?xml version="1.0" encoding="UTF-8"?>'
            xml_content = xml_content.replace(match.group(0), new_declaration)

        return xml_content

    def _analyze_xml_structure(self, root):
        """
        XMLの構造を分析してフィールドリストを生成

        :param root: XML root element
        :return: QgsFieldのリスト
        """
        fields = []
        field_names = set()

        # まず各要素を調べてフィールド名を収集
        elements = self._find_data_elements(root)

        # 各要素の子要素とネストした要素をすべて調査
        for element in elements[:10]:  # 最初の10要素をサンプルとして分析
            self._collect_field_names(element, field_names, prefix="")

        # フィールド名をソートして整理
        sorted_field_names = sorted(field_names)

        for field_name in sorted_field_names:
            # フィールドタイプを推定（とりあえず文字列）
            fields.append(QgsField(field_name, QVariant.String))

        # 基本フィールドを追加
        if "xml_id" not in field_names:
            fields.insert(0, QgsField("xml_id", QVariant.Int))
        if "element_path" not in field_names:
            fields.append(QgsField("element_path", QVariant.String))

        return fields

    def _collect_field_names(self, element, field_names, prefix="", max_depth=3, current_depth=0):
        """
        要素から再帰的にフィールド名を収集

        :param element: XML要素
        :param field_names: フィールド名のセット
        :param prefix: フィールド名のプレフィックス
        :param max_depth: 最大再帰深度
        :param current_depth: 現在の深度
        """
        if current_depth > max_depth:
            return

        # 現在の要素の属性を追加
        for attr_name in element.attrib:
            attr_field_name = f"{prefix}{attr_name}" if prefix else attr_name
            field_names.add(attr_field_name)

        # 子要素を処理
        for child in element:
            child_tag = child.tag
            # 名前空間プレフィックスを除去
            if '}' in child_tag:
                child_tag = child_tag.split('}')[1]

            child_field_name = f"{prefix}{child_tag}" if prefix else child_tag

            # 子要素がテキストを持つ場合、フィールドとして追加
            if child.text and child.text.strip():
                field_names.add(child_field_name)

            # さらに子要素がある場合は再帰的に処理
            if len(list(child)) > 0:
                # ネストした要素は「親.子」の形式で名前を付ける
                new_prefix = f"{child_field_name}." if current_depth < 2 else ""
                if new_prefix:
                    self._collect_field_names(child, field_names, new_prefix, max_depth, current_depth + 1)
            else:
                # 末端要素はそのまま追加
                field_names.add(child_field_name)

    def _find_data_elements(self, root):
        """
        XMLからデータ要素を探す

        :param root: XML root element
        :return: データ要素のリスト
        """
        # 一般的なデータ要素名を試す（英語）
        common_names = ['record', 'item', 'data', 'entry', 'row', 'element', 'node']

        for name in common_names:
            elements = root.findall(f".//{name}")
            if elements and len(elements) > 0:
                # 要素が子要素を持っているかチェック
                if len(list(elements[0])) > 0:
                    return elements

        # 日本語の要素名を試す（国土交通省の標準的なXML要素を含む）
        japanese_names = [
            # 一般的な日本語要素
            '報告書ファイル情報', 'データ', '項目', 'レコード', '記録', '情報',
            # 国土交通省電子納品関連
            '工事情報', '業務情報', '測量成果', '地質・土質調査',
            '図面情報', '工事写真', 'CADデータ',
            # JPGIS/地理空間情報関連
            '地物', 'Feature', 'フィーチャ', '空間属性', '図形',
            # 測量成果関連
            '基準点', '水準点', '多角点', '測点', '観測値',
            # CAD/SXF関連
            '作図要素', '図形要素', 'レイヤ', 'グループ',
            # 積算システム関連
            '工種', '種別', '細別', '規格', '単価', '数量',
            # 施設管理関連
            '施設', '設備', '機器', '点検', '維持管理'
        ]

        for name in japanese_names:
            elements = root.findall(f".//{name}")
            if elements and len(elements) > 0:
                if len(list(elements[0])) > 0:
                    return elements

        # 子要素から最も多く出現する要素名を探す
        element_counts = {}
        for child in root.iter():
            if len(list(child)) > 0:  # 子要素を持つ要素
                tag_name = child.tag
                # 名前空間プレフィックスを除去
                if '}' in tag_name:
                    tag_name = tag_name.split('}')[1]
                element_counts[tag_name] = element_counts.get(tag_name, 0) + 1

        if element_counts:
            # 最も多く出現する要素名を取得
            most_common = max(element_counts, key=element_counts.get)
            elements = root.findall(f".//{most_common}")
            if elements and len(elements) > 1:  # 複数の同じ要素がある場合
                return elements

        # ルート要素の直接の子要素が同じタグ名を持つ場合
        children = list(root)
        if len(children) > 1:
            # 同じタグ名の子要素が複数ある場合
            tag_groups = {}
            for child in children:
                tag_name = child.tag
                if '}' in tag_name:
                    tag_name = tag_name.split('}')[1]
                if tag_name not in tag_groups:
                    tag_groups[tag_name] = []
                tag_groups[tag_name].append(child)

            # 最も多いグループを返す
            if tag_groups:
                largest_group = max(tag_groups.values(), key=len)
                if len(largest_group) > 1:
                    return largest_group

        # 最後の手段：ルート要素の全子要素を返す
        if len(children) > 0:
            return children

        # ルート要素自体を返す（単一要素の場合）
        return [root]

    def _extract_features_from_xml(self, root, fields):
        """
        XMLからフィーチャを抽出

        :param root: XML root element
        :param fields: フィールドリスト
        :return: QgsFeatureのリスト
        """
        features = []
        elements = self._find_data_elements(root)

        field_names = [field.name() for field in fields]

        for i, element in enumerate(elements):
            feature = QgsFeature()
            attributes = []

            # 各フィールドの値を設定
            for field_name in field_names:
                if field_name == "xml_id":
                    attributes.append(i + 1)
                elif field_name == "element_path":
                    path = self._get_element_path(element, root)
                    attributes.append(path)
                else:
                    # 値を取得（複数の方法を試す）
                    value = self._extract_field_value(element, field_name)
                    attributes.append(value)

            feature.setAttributes(attributes)
            features.append(feature)

        return features

    def _extract_field_value(self, element, field_name):
        """
        要素から指定されたフィールドの値を抽出

        :param element: XML要素
        :param field_name: フィールド名
        :return: 抽出された値（文字列）
        """
        # 1. 直接の子要素から取得
        child = element.find(field_name)
        if child is not None and child.text is not None:
            return child.text.strip()

        # 2. 属性から取得
        attr_value = element.get(field_name)
        if attr_value is not None:
            return attr_value.strip()

        # 3. ネストした子要素から取得（ドット記法に対応）
        if '.' in field_name:
            parts = field_name.split('.')
            current = element
            for part in parts:
                current = current.find(part)
                if current is None:
                    break
            if current is not None and current.text is not None:
                return current.text.strip()

        # 4. 名前空間を無視して検索
        for child in element.iter():
            tag_name = child.tag
            if '}' in tag_name:
                tag_name = tag_name.split('}')[1]
            if tag_name == field_name and child.text is not None:
                return child.text.strip()

        # 5. 部分一致で検索（日本語要素名の場合に有効）
        for child in element.iter():
            tag_name = child.tag
            if '}' in tag_name:
                tag_name = tag_name.split('}')[1]
            if field_name in tag_name and child.text is not None:
                return child.text.strip()

        # 6. 逆方向の部分一致（フィールド名がタグ名に含まれる場合）
        for child in element.iter():
            tag_name = child.tag
            if '}' in tag_name:
                tag_name = tag_name.split('}')[1]
            if tag_name in field_name and child.text is not None:
                return child.text.strip()

        # 7. 複数の値がある場合は結合して返す
        values = []
        for child in element.iter():
            tag_name = child.tag
            if '}' in tag_name:
                tag_name = tag_name.split('}')[1]
            if tag_name == field_name and child.text is not None:
                values.append(child.text.strip())

        if values:
            return " | ".join(values)  # 複数値は区切り文字で結合

        # 値が見つからない場合は空文字列
        return ""

    def _get_element_path(self, element, root):
        """
        要素のXPathを取得

        :param element: XML element
        :param root: ルート要素
        :return: XPath文字列
        """
        if element == root:
            return f"/{root.tag}"

        path_parts = []
        current = element

        # 親要素を辿ってパスを構築
        _ = []
        parent = element.getparent() if hasattr(element, 'getparent') else None

        # ElementTreeの場合、親要素の取得方法が異なる
        if parent is None:
            # ルートから要素を探してパスを構築
            def find_path(node, target, current_path=""):
                if node == target:
                    return current_path + "/" + node.tag
                for child in node:
                    result = find_path(child, target, current_path + "/" + node.tag)
                    if result:
                        return result
                return None

            path = find_path(root, element)
            return path if path else f"/{root.tag}/unknown"

        # 通常の親要素取得が可能な場合
        while current is not None and current != root:
            path_parts.insert(0, current.tag)
            current = current.getparent() if hasattr(current, 'getparent') else None

        if path_parts:
            return "/" + root.tag + "/" + "/".join(path_parts)
        else:
            return f"/{root.tag}"

    def _show_error(self, message):
        """エラーメッセージを表示"""
        if self.iface and self.iface.messageBar():
            self.iface.messageBar().pushMessage(
                LOG_TAG, message, level=Qgis.MessageLevel.Critical, duration=10)

    def _show_warning(self, message):
        """警告メッセージを表示"""
        if self.iface and self.iface.messageBar():
            self.iface.messageBar().pushMessage(
                LOG_TAG, message, level=Qgis.MessageLevel.Warning, duration=5)

    def _add_source_file_field(self, layer):
        """レイヤーにソースファイルパスフィールドを追加"""
        provider = layer.dataProvider()
        # フルパス用に十分な長さ（500文字）を確保
        source_field = QgsField("source_file", QVariant.String)
        source_field.setLength(500)
        provider.addAttributes([source_field])
        layer.updateFields()

    def _merge_layer_data(self, target_layer, source_layer, source_file_path):
        """ソースレイヤーのデータをターゲットレイヤーにマージ"""
        provider = target_layer.dataProvider()
        # --- フィールドのユニオン処理 ---
        # ターゲットに存在しないソース側のフィールドを追加して属性欠損を防ぐ
        target_field_names = [f.name() for f in target_layer.fields()]
        source_fields = [f for f in source_layer.fields()]
        missing_fields = [f for f in source_fields if f.name() not in target_field_names]

        if missing_fields:
            # 追加前にログ
            QgsMessageLog.logMessage(
                f"adding fields missing in target: {', '.join([f.name() for f in missing_fields])}",
                LOG_TAG,
                Qgis.MessageLevel.Info
            )
            provider.addAttributes(missing_fields)
            target_layer.updateFields()

        # フィールド名のキャッシュを再取得
        target_field_names = [f.name() for f in target_layer.fields()]

        # ソースレイヤーのフィーチャーを取得して追加
        features = []
        for feature in source_layer.getFeatures():
            new_feature = QgsFeature(target_layer.fields())

            # ソースの各フィールド値を可能な限りコピー
            for field in source_layer.fields():
                field_name = field.name()
                if field_name in target_field_names:
                    new_feature.setAttribute(field_name, feature.attribute(field_name))

            # source_file 情報の取り扱い
            existing_source = None
            if "source_file" in [f.name() for f in source_layer.fields()]:
                existing_source = feature.attribute("source_file")

            if existing_source:
                if "source_file" in target_field_names:
                    new_feature.setAttribute("source_file", existing_source)
            else:
                if "source_file" in target_field_names:
                    new_feature.setAttribute("source_file", source_file_path)

            features.append(new_feature)

        if features:
            provider.addFeatures(features)
            target_layer.updateExtents()

        QgsMessageLog.logMessage(
            f"merge completed: added {len(features)} records from '{source_file_path}'",
            LOG_TAG,
            Qgis.MessageLevel.Info
        )

    def _update_source_file_info(self, layer, file_path):
        """レイヤーの全フィーチャーにソースファイル情報を更新"""
        provider = layer.dataProvider()

        # 全フィーチャーのsource_fileフィールドを更新
        features = []
        for feature in layer.getFeatures():
            feature.setAttribute("source_file", file_path)  # フルパスを設定
            features.append(feature)

        # フィーチャーを更新
        feature_dict = {f.id(): {layer.fields().indexFromName("source_file"): file_path}
                        for f in features}
        provider.changeAttributeValues(feature_dict)
        layer.updateExtents()

        QgsMessageLog.logMessage(
            f"updated source file info: set '{file_path}' on {len(features)} records",
            LOG_TAG,
            Qgis.MessageLevel.Info
        )

    def _show_success(self, message):
        """成功メッセージを表示"""
        if self.iface and self.iface.messageBar():
            self.iface.messageBar().pushMessage(
                LOG_TAG, message, level=Qgis.MessageLevel.Success, duration=3)


def diagnose_mlit_xml(xml_file_path):
    """
    スタンドアロン関数：XMLファイルが国土交通省関連かどうかを診断

    :param xml_file_path: XMLファイルのパス
    :return: 診断結果の辞書
    """
    # ダミーのifaceでXmlAttributeLoaderを初期化
    class DummyIface:
        def messageBar(self):
            return None

    try:
        loader = XmlAttributeLoader(DummyIface())
        is_mlit, xml_type, confidence, details = loader.is_mlit_xml(xml_file_path)

        return {
            'is_mlit_xml': is_mlit,
            'xml_type': xml_type,
            'confidence': confidence,
            'details': details,
            'recommendation': _get_recommendation(is_mlit, confidence, xml_type)
        }
    except Exception as e:
        return {
            'is_mlit_xml': False,
            'xml_type': 'error',
            'confidence': 0.0,
            'details': {'error': str(e)},
            'recommendation': f"error during file diagnosis: {e}"
        }


def _get_recommendation(is_mlit, confidence, xml_type):
    """診断結果に基づく推奨事項を生成"""
    if is_mlit and confidence >= 0.8:
        return f"identified as {xml_type} with high confidence. Suitable for loading in QGIS."
    elif is_mlit and confidence >= 0.5:
        return f"identified as {xml_type} with medium confidence. Loadable, but checking the structure is recommended."
    elif is_mlit and confidence >= 0.3:
        return f"identified as {xml_type} with low confidence. Some MLIT XML characteristics found; detailed review required."
    else:
        return "The file does not appear to be a standard MLIT XML format. It will be processed as generic XML."


def print_mlit_xml_diagnosis(xml_file_path):
    """
    XMLファイルの診断結果をコンソールに出力

    :param xml_file_path: XMLファイルのパス
    """
    print(f"=== MLIT XML diagnosis: {xml_file_path} ===")

    result = diagnose_mlit_xml(xml_file_path)

    print(f"file name: {os.path.basename(xml_file_path)}")
    print(f"MLIT XML: {'yes' if result['is_mlit_xml'] else 'no'}")
    print(f"XML type: {result['xml_type']}")
    print(f"confidence: {result['confidence']:.2f} ({result['confidence'] * 100:.1f}%)")
    print(f"recommendation: {result['recommendation']}")

    details = result['details']
    if details:
        print("\n--- details ---")
        if 'file_size' in details:
            print(f"file size: {details['file_size']:,} bytes")
        if 'root_element' in details:
            print(f"root element: {details['root_element']}")
        if details.get('dtd_detected'):
            print(f"DTD detected: {details['dtd_detected']}")
        if details.get('namespace_detected'):
            print(f"namespaces detected: {', '.join(details['namespace_detected'])}")
        if details.get('mlit_keywords'):
            print(f"MLIT keywords: {', '.join(details['mlit_keywords'][:5])}{'...' if len(details['mlit_keywords']) > 5 else ''}")
        if details.get('structure_indicators'):
            print(f"structure indicators: {', '.join(details['structure_indicators'])}")
        if 'error' in details:
            print(f"error: {details['error']}")

    print("=" * 50)


if __name__ == "__main__":
    # コマンドライン実行時のテスト
    import sys
    if len(sys.argv) > 1:
        xml_file_path = sys.argv[1]
        print_mlit_xml_diagnosis(xml_file_path)
    else:
        print("usage: python xml_attribute_loader.py <XML file path>")
        print("example: python xml_attribute_loader.py /path/to/report.xml")
