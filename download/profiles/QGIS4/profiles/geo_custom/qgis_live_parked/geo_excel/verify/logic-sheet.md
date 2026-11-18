# geo_excel — 完全ロジックシート

- 種別: qgis_plugin / バージョン: 1.9.5
- 生成: 2026-11-14T07:09:57+09:00 / 機能数: 105

## トポロジ

```mermaid
flowchart LR
  subgraph ENTRY["操作入口"]
    UI["メニュー/ダイアログ"]
    AI["AI/bridge_call"]
  end
  subgraph LOGIC["実装"]
    entry_point___init___py_classFactory["classFactory<br/><i>entry_point</i>"]
    action_plugin_initGui["initGui<br/><i>action</i>"]
    action_plugin_unload["unload<br/><i>action</i>"]
    dialog_GeoExcelSettingsDialog["GeoExcelSettingsDialog<br/><i>dialog</i>"]
    bridge_applyDefaults["applyDefaults<br/><i>bridge_method</i>"]
    bridge_checkExcel["checkExcel<br/><i>bridge_method</i>"]
    bridge_layerVariables["layerVariables<br/><i>bridge_method</i>"]
    bridge_listScripts["listScripts<br/><i>bridge_method</i>"]
    bridge_openSettings["openSettings<br/><i>bridge_method</i>"]
    bridge_pluginInfo["pluginInfo<br/><i>bridge_method</i>"]
    bridge_regenerateTemplates["regenerateTemplates<br/><i>bridge_method</i>"]
    bridge_run["run<br/><i>bridge_method</i>"]
    bridge_setLayerVariables["setLayerVariables<br/><i>bridge_method</i>"]
    bridge_setSettings["setSettings<br/><i>bridge_method</i>"]
    bridge_settings["settings<br/><i>bridge_method</i>"]
    bridge_status["status<br/><i>bridge_method</i>"]
    integration_bridge_py_284["self._win32com_available<br/><i>integration</i>"]
    integration_bridge_py_292["self._win32com_available<br/><i>integration</i>"]
    integration_bridge_py_334["self._win32com_available<br/><i>integration</i>"]
    integration_exportList_py_623["Dispatch<br/><i>integration</i>"]
    integration_exportSingle_py_974["Dispatch<br/><i>integration</i>"]
    integration_exportSingleBulk_py_1019["Dispatch<br/><i>integration</i>"]
    integration_settings_py_167["Dispatch<br/><i>integration</i>"]
    integration_settings_py_182["win32com_available<br/><i>integration</i>"]
    ai_bridge_route["bridge_call経由全到達<br/><i>ai_integration</i>"]
    ai_catalog["describe_plugins登録<br/><i>ai_integration</i>"]
    ai_pluginInfo["pluginInfo自己記述<br/><i>ai_integration</i>"]
    logic_fn_settings_py_auto_apply_enabled["auto_apply_enabled<br/><i>logic_fn</i>"]
    logic_fn_settings_py_check_excel_launch["check_excel_launch<br/><i>logic_fn</i>"]
    logic_fn_settings_py_configured_template["configured_template<br/><i>logic_fn</i>"]
    logic_fn_settings_py_current_settings["current_settings<br/><i>logic_fn</i>"]
    logic_fn_settings_py_documents_dir["documents_dir<br/><i>logic_fn</i>"]
    logic_fn_settings_py_ensure_layer_variables["ensure_layer_variables<br/><i>logic_fn</i>"]
    logic_fn_settings_py_environment_report["environment_report<br/><i>logic_fn</i>"]
    logic_fn_settings_py_excel_registered["excel_registered<br/><i>logic_fn</i>"]
    logic_fn_settings_py_generate_template["generate_template<br/><i>logic_fn</i>"]
    logic_fn_settings_py_generated_template_path["generated_template_path<br/><i>logic_fn</i>"]
    logic_fn_settings_py_output_dir["output_dir<br/><i>logic_fn</i>"]
    logic_fn_settings_py_requirements["requirements<br/><i>logic_fn</i>"]
    logic_fn_settings_py_save_settings["save_settings<br/><i>logic_fn</i>"]
    logic_fn_settings_py_script_variable_spec["script_variable_spec<br/><i>logic_fn</i>"]
    logic_fn_settings_py_set_setting["set_setting<br/><i>logic_fn</i>"]
    logic_fn_settings_py_setting["setting<br/><i>logic_fn</i>"]
    logic_fn_settings_py_win32com_available["win32com_available<br/><i>logic_fn</i>"]
    logic_fn_settings_py_write_xlsx["write_xlsx<br/><i>logic_fn</i>"]
    logic_fn_exportList_py_append_list_insert["append_list_insert<br/><i>template_fn</i>"]
    logic_fn_exportList_py_check_same_name_opend["check_same_name_opend<br/><i>template_fn</i>"]
    logic_fn_exportList_py_check_save_folder["check_save_folder<br/><i>template_fn</i>"]
    logic_fn_exportList_py_contains_text_in_first_cell["contains_text_in_first_cell<br/><i>template_fn</i>"]
    logic_fn_exportList_py_create_expression["create_expression<br/><i>template_fn</i>"]
    logic_fn_exportList_py_evaluate_attach_text["evaluate_attach_text<br/><i>template_fn</i>"]
    logic_fn_exportList_py_excel_value_text["excel_value_text<br/><i>template_fn</i>"]
    logic_fn_exportList_py_find_list_insert["find_list_insert<br/><i>template_fn</i>"]
    logic_fn_exportList_py_get_layer_variable["get_layer_variable<br/><i>template_fn</i>"]
    logic_fn_exportList_py_get_layer_variable_evaluated["get_layer_variable_evaluated<br/><i>template_fn</i>"]
    logic_fn_exportList_py_insert_list["insert_list<br/><i>template_fn</i>"]
    logic_fn_exportList_py_insert_list_values["insert_list_values<br/><i>template_fn</i>"]
    logic_fn_exportList_py_make_expression_context["make_expression_context<br/><i>template_fn</i>"]
    logic_fn_exportList_py_output_list_report["output_list_report<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_add_temp_theme_from_current_state["add_temp_theme_from_current_state<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_append_attach["append_attach<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_append_attach_fit_image["append_attach_fit_image<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_change_theme["change_theme<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_check_same_name_opend["check_same_name_opend<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_check_save_folder["check_save_folder<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_contains_text_in_first_cell["contains_text_in_first_cell<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_create_expression["create_expression<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_create_map_image["create_map_image<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_create_map_images["create_map_images<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_evaluate_attach_text["evaluate_attach_text<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_excel_value_text["excel_value_text<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_find_attach["find_attach<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_find_attach_fit_image["find_attach_fit_image<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_get_layer_variable["get_layer_variable<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_get_layer_variable_on_feature["get_layer_variable_on_feature<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_insert_images["insert_images<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_make_expression_context["make_expression_context<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_output_single_report["output_single_report<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_replace_attach["replace_attach<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_restore_from_temp_theme["restore_from_temp_theme<br/><i>template_fn</i>"]
    logic_fn_exportSingle_py_variable_based_on_feature["variable_based_on_feature<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_add_temp_theme_from_current_state["add_temp_theme_from_current_state<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_append_attach["append_attach<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_append_attach_fit_image["append_attach_fit_image<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_change_theme["change_theme<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_check_save_folder["check_save_folder<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_contains_text_in_first_cell["contains_text_in_first_cell<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_create_expression["create_expression<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_create_map_image["create_map_image<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_create_map_images["create_map_images<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_evaluate_attach_text["evaluate_attach_text<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_excel_value_text["excel_value_text<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_find_attach["find_attach<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_find_attach_fit_image["find_attach_fit_image<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_get_exp_variable_for_feature["get_exp_variable_for_feature<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_get_exp_variable_for_layer["get_exp_variable_for_layer<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_get_layer_variable["get_layer_variable<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_get_raw_variable_for_layer["get_raw_variable_for_layer<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_get_variable_for_feature["get_variable_for_feature<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_insert_images["insert_images<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_make_expression_context["make_expression_context<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_output_single_report["output_single_report<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_replace_attach["replace_attach<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_restore_from_temp_theme["restore_from_temp_theme<br/><i>template_fn</i>"]
    logic_fn_exportSingleBulk_py_variable_based_on_feature["variable_based_on_feature<br/><i>template_fn</i>"]
  end
  AI --> bridge_applyDefaults & bridge_checkExcel & bridge_layerVariables & bridge_listScripts & bridge_openSettings & bridge_pluginInfo & bridge_regenerateTemplates & bridge_run …
  UI --> action_plugin_initGui & action_plugin_unload & dialog_GeoExcelSettingsDialog
  LOGIC --> QGIS["QGIS API / iface / QgsProject"]
  LOGIC --> EXT["外部連携(HTTP/subprocess/ファイル)"]
```

## 機能別ロジック

### entry_point.__init__.py:classFactory — classFactory

- kind: `entry_point` / source: `__init__.py:5`
- signature: `classFactory(iface)`
- 要約: 
- needs_runtime=False / standalone_ok=True

```mermaid
flowchart LR
  E_entry_point___init___py_classFactory["QGIS起動"] --> H_entry_point___init___py_classFactory["classFactory"]
  H_entry_point___init___py_classFactory --> OUT["結果"]
```

- 検証: 単独=import→呼出→戻り値assert / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — standalone経路のみ(要runtime依存無し)

### action.plugin.initGui — initGui

- kind: `action` / source: `plugin.py:136`
- signature: `initGui()`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_action_plugin_initGui["メニュー/ツールバー"] --> H_action_plugin_initGui["initGui"]
  H_action_plugin_initGui --> R_action_plugin_initGui["QGIS/ランタイムAPI"]
  R_action_plugin_initGui --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call/generic trigger→実在確認
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### action.plugin.unload — unload

- kind: `action` / source: `plugin.py:165`
- signature: `unload()`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_action_plugin_unload["メニュー/ツールバー"] --> H_action_plugin_unload["unload"]
  H_action_plugin_unload --> R_action_plugin_unload["QGIS/ランタイムAPI"]
  R_action_plugin_unload --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call/generic trigger→実在確認
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### dialog.GeoExcelSettingsDialog — GeoExcelSettingsDialog

- kind: `dialog` / source: `settings_dialog.py:41`
- signature: `GeoExcelSettingsDialog`
- 要約: geo_excel の既定設定とレイヤ変数を管理するダイアログ。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_dialog_GeoExcelSettingsDialog["UI操作"] --> H_dialog_GeoExcelSettingsDialog["GeoExcelSettingsDialog"]
  H_dialog_GeoExcelSettingsDialog --> R_dialog_GeoExcelSettingsDialog["QGIS/ランタイムAPI"]
  R_dialog_GeoExcelSettingsDialog --> OUT["結果"]
```

- 検証: 単独= / 連携=openDialog→screenshot→closeDialog
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### bridge.applyDefaults — applyDefaults

- kind: `bridge_method` / source: `bridge.py:391`
- signature: `applyDefaults(layer_id=…, script=…)`
- 要約: 不足レイヤ変数へ既定値を適用する(script省略で全スクリプト)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_applyDefaults["AI/bridge_call"] --> H_bridge_applyDefaults["applyDefaults"]
  H_bridge_applyDefaults --> R_bridge_applyDefaults["QGIS/ランタイムAPI"]
  R_bridge_applyDefaults --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call applyDefaults → 応答assert
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 副作用/破壊的/外部通信操作のため手動検証対象

### bridge.checkExcel — checkExcel

- kind: `bridge_method` / source: `bridge.py:412`
- signature: `checkExcel()`
- 要約: Excelを実際にCOM起動して検証する(数秒ブロックする)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_checkExcel["AI/bridge_call"] --> H_bridge_checkExcel["checkExcel"]
  H_bridge_checkExcel --> R_bridge_checkExcel["QGIS/ランタイムAPI"]
  R_bridge_checkExcel --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call checkExcel → 応答assert
- 結果: **pass** 2026-11-14T07:09:57+09:00 — bridge_call応答あり args=[]

### bridge.layerVariables — layerVariables

- kind: `bridge_method` / source: `bridge.py:304`
- signature: `layerVariables(layer_id=…)`
- 要約: 対象レイヤの xlsout_*/dpi レイヤ変数を返す。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_layerVariables["AI/bridge_call"] --> H_bridge_layerVariables["layerVariables"]
  H_bridge_layerVariables --> R_bridge_layerVariables["QGIS/ランタイムAPI"]
  R_bridge_layerVariables --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call layerVariables → 応答assert
- 結果: **pass** 2026-11-14T07:09:57+09:00 — bridge_call応答あり args=[]

### bridge.listScripts — listScripts

- kind: `bridge_method` / source: `bridge.py:299`
- signature: `listScripts()`
- 要約: 帳票スクリプト一覧を返す。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_listScripts["AI/bridge_call"] --> H_bridge_listScripts["listScripts"]
  H_bridge_listScripts --> R_bridge_listScripts["QGIS/ランタイムAPI"]
  R_bridge_listScripts --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call listScripts → 応答assert
- 結果: **pass** 2026-11-14T07:09:57+09:00 — bridge_call応答あり args=[]

### bridge.openSettings — openSettings

- kind: `bridge_method` / source: `bridge.py:419`
- signature: `openSettings()`
- 要約: 設定ダイアログを開く。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_openSettings["AI/bridge_call"] --> H_bridge_openSettings["openSettings"]
  H_bridge_openSettings --> R_bridge_openSettings["QGIS/ランタイムAPI"]
  R_bridge_openSettings --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call openSettings → 応答assert
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 副作用/破壊的/外部通信操作のため手動検証対象

### bridge.pluginInfo — pluginInfo

- kind: `bridge_method` / source: `bridge.py:272`
- signature: `pluginInfo()`
- 要約: プラグインの自己記述(id/summary/when_to_use/methods)を返す。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_pluginInfo["AI/bridge_call"] --> H_bridge_pluginInfo["pluginInfo"]
  H_bridge_pluginInfo --> R_bridge_pluginInfo["QGIS/ランタイムAPI"]
  R_bridge_pluginInfo --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call pluginInfo → 応答assert
- 結果: **pass** 2026-11-14T07:09:57+09:00 — bridge_call応答あり args=[]

### bridge.regenerateTemplates — regenerateTemplates

- kind: `bridge_method` / source: `bridge.py:449`
- signature: `regenerateTemplates(layer_id=…)`
- 要約: 自動生成テンプレートを再生成し不足変数へ既定値を適用する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_regenerateTemplates["AI/bridge_call"] --> H_bridge_regenerateTemplates["regenerateTemplates"]
  H_bridge_regenerateTemplates --> R_bridge_regenerateTemplates["QGIS/ランタイムAPI"]
  R_bridge_regenerateTemplates --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call regenerateTemplates → 応答assert
- 結果: **pass** 2026-11-14T07:09:57+09:00 — bridge_call応答あり args=[]

### bridge.run — run

- kind: `bridge_method` / source: `bridge.py:324`
- signature: `run(script=…, feature_id=…, confirm=…)`
- 要約: 帳票スクリプトを実行する(結果・メッセージを返す)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_run["AI/bridge_call"] --> H_bridge_run["run"]
  H_bridge_run --> R_bridge_run["QGIS/ランタイムAPI"]
  R_bridge_run --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call run → 応答assert
- 結果: **pass** 2026-11-14T07:09:57+09:00 — bridge_call応答あり args=[]

### bridge.setLayerVariables — setLayerVariables

- kind: `bridge_method` / source: `bridge.py:312`
- signature: `setLayerVariables(variables, layer_id=…)`
- 要約: レイヤ変数を設定する。{変数名: 値}、値Noneで削除。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_setLayerVariables["AI/bridge_call"] --> H_bridge_setLayerVariables["setLayerVariables"]
  H_bridge_setLayerVariables --> R_bridge_setLayerVariables["QGIS/ランタイムAPI"]
  R_bridge_setLayerVariables --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call setLayerVariables → 応答assert
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 副作用/破壊的/外部通信操作のため手動検証対象

### bridge.setSettings — setSettings

- kind: `bridge_method` / source: `bridge.py:424`
- signature: `setSettings(settings=…)`
- 要約: 既定設定を保存する(output_dir/dpi/テンプレート/auto_apply)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_setSettings["AI/bridge_call"] --> H_bridge_setSettings["setSettings"]
  H_bridge_setSettings --> R_bridge_setSettings["QGIS/ランタイムAPI"]
  R_bridge_setSettings --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call setSettings → 応答assert
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 副作用/破壊的/外部通信操作のため手動検証対象

### bridge.settings — settings

- kind: `bridge_method` / source: `bridge.py:377`
- signature: `settings()`
- 要約: 既定設定・環境チェック・必要物の列挙を返す。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_settings["AI/bridge_call"] --> H_bridge_settings["settings"]
  H_bridge_settings --> R_bridge_settings["QGIS/ランタイムAPI"]
  R_bridge_settings --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call settings → 応答assert
- 結果: **pass** 2026-11-14T07:09:57+09:00 — bridge_call応答あり args=[]

### bridge.status — status

- kind: `bridge_method` / source: `bridge.py:288`
- signature: `status()`
- 要約: 実行時状態(アクティブレイヤ・選択数・依存環境)を返す。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_bridge_status["AI/bridge_call"] --> H_bridge_status["status"]
  H_bridge_status --> R_bridge_status["QGIS/ランタイムAPI"]
  R_bridge_status --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call status → 応答assert
- 結果: **pass** 2026-11-14T07:09:57+09:00 — bridge_call応答あり args=[]

### integration.bridge.py:284 — self._win32com_available

- kind: `integration` / source: `bridge.py:284`
- signature: `self._win32com_available(…)`
- 要約: 外部連携呼出
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_integration_bridge_py_284["呼出元"] --> H_integration_bridge_py_284["self._win32com_available"]
  H_integration_bridge_py_284 --> R_integration_bridge_py_284["QGIS/ランタイムAPI"]
  R_integration_bridge_py_284 --> OUT["結果"]
```

- 検証: 単独= / 連携=連携先の実在/生成物を確認
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 連携呼出点の記録(実連携実行はbridge_method等で確認)

### integration.bridge.py:292 — self._win32com_available

- kind: `integration` / source: `bridge.py:292`
- signature: `self._win32com_available(…)`
- 要約: 外部連携呼出
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_integration_bridge_py_292["呼出元"] --> H_integration_bridge_py_292["self._win32com_available"]
  H_integration_bridge_py_292 --> R_integration_bridge_py_292["QGIS/ランタイムAPI"]
  R_integration_bridge_py_292 --> OUT["結果"]
```

- 検証: 単独= / 連携=連携先の実在/生成物を確認
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 連携呼出点の記録(実連携実行はbridge_method等で確認)

### integration.bridge.py:334 — self._win32com_available

- kind: `integration` / source: `bridge.py:334`
- signature: `self._win32com_available(…)`
- 要約: 外部連携呼出
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_integration_bridge_py_334["呼出元"] --> H_integration_bridge_py_334["self._win32com_available"]
  H_integration_bridge_py_334 --> R_integration_bridge_py_334["QGIS/ランタイムAPI"]
  R_integration_bridge_py_334 --> OUT["結果"]
```

- 検証: 単独= / 連携=連携先の実在/生成物を確認
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 連携呼出点の記録(実連携実行はbridge_method等で確認)

### integration.exportList.py:623 — Dispatch

- kind: `integration` / source: `exportList.py:623`
- signature: `Dispatch(…)`
- 要約: 外部連携呼出
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_integration_exportList_py_623["呼出元"] --> H_integration_exportList_py_623["Dispatch"]
  H_integration_exportList_py_623 --> R_integration_exportList_py_623["QGIS/ランタイムAPI"]
  R_integration_exportList_py_623 --> OUT["結果"]
```

- 検証: 単独= / 連携=連携先の実在/生成物を確認
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 連携呼出点の記録(実連携実行はbridge_method等で確認)

### integration.exportSingle.py:974 — Dispatch

- kind: `integration` / source: `exportSingle.py:974`
- signature: `Dispatch(…)`
- 要約: 外部連携呼出
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_integration_exportSingle_py_974["呼出元"] --> H_integration_exportSingle_py_974["Dispatch"]
  H_integration_exportSingle_py_974 --> R_integration_exportSingle_py_974["QGIS/ランタイムAPI"]
  R_integration_exportSingle_py_974 --> OUT["結果"]
```

- 検証: 単独= / 連携=連携先の実在/生成物を確認
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 連携呼出点の記録(実連携実行はbridge_method等で確認)

### integration.exportSingleBulk.py:1019 — Dispatch

- kind: `integration` / source: `exportSingleBulk.py:1019`
- signature: `Dispatch(…)`
- 要約: 外部連携呼出
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_integration_exportSingleBulk_py_1019["呼出元"] --> H_integration_exportSingleBulk_py_1019["Dispatch"]
  H_integration_exportSingleBulk_py_1019 --> R_integration_exportSingleBulk_py_1019["QGIS/ランタイムAPI"]
  R_integration_exportSingleBulk_py_1019 --> OUT["結果"]
```

- 検証: 単独= / 連携=連携先の実在/生成物を確認
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 連携呼出点の記録(実連携実行はbridge_method等で確認)

### integration.settings.py:167 — Dispatch

- kind: `integration` / source: `settings.py:167`
- signature: `Dispatch(…)`
- 要約: 外部連携呼出
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_integration_settings_py_167["呼出元"] --> H_integration_settings_py_167["Dispatch"]
  H_integration_settings_py_167 --> R_integration_settings_py_167["QGIS/ランタイムAPI"]
  R_integration_settings_py_167 --> OUT["結果"]
```

- 検証: 単独= / 連携=連携先の実在/生成物を確認
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 連携呼出点の記録(実連携実行はbridge_method等で確認)

### integration.settings.py:182 — win32com_available

- kind: `integration` / source: `settings.py:182`
- signature: `win32com_available(…)`
- 要約: 外部連携呼出
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_integration_settings_py_182["呼出元"] --> H_integration_settings_py_182["win32com_available"]
  H_integration_settings_py_182 --> R_integration_settings_py_182["QGIS/ランタイムAPI"]
  R_integration_settings_py_182 --> OUT["結果"]
```

- 検証: 単独= / 連携=連携先の実在/生成物を確認
- 結果: **skip** 2026-11-14T07:09:57+09:00 — 連携呼出点の記録(実連携実行はbridge_method等で確認)

### ai.bridge_route — bridge_call経由全到達

- kind: `ai_integration` / source: `bridge.py`
- signature: ``
- 要約: 全bridge_methodがAI経路で呼べる
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_ai_bridge_route["AI経路"] --> H_ai_bridge_route["bridge_call経由全到達"]
  H_ai_bridge_route --> R_ai_bridge_route["QGIS/ランタイムAPI"]
  R_ai_bridge_route --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call 全method→ok/error記録
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 8メソッド到達可能

### ai.catalog — describe_plugins登録

- kind: `ai_integration` / source: `geo_driver経由`
- signature: ``
- 要約: カタログに載り呼出可能か
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_ai_catalog["AI経路"] --> H_ai_catalog["describe_plugins登録"]
  H_ai_catalog --> R_ai_catalog["QGIS/ランタイムAPI"]
  R_ai_catalog --> OUT["結果"]
```

- 検証: 単独= / 連携=describe_plugins→plugins[]にid実在+methods非空
- 結果: **pass** 2026-11-14T07:09:57+09:00 — describe_plugins: methods=11

### ai.pluginInfo — pluginInfo自己記述

- kind: `ai_integration` / source: `bridge.py`
- signature: `pluginInfo()`
- 要約: summary/when_to_use/methodsの正確性
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_ai_pluginInfo["AI経路"] --> H_ai_pluginInfo["pluginInfo自己記述"]
  H_ai_pluginInfo --> R_ai_pluginInfo["QGIS/ランタイムAPI"]
  R_ai_pluginInfo --> OUT["結果"]
```

- 検証: 単独= / 連携=bridge_call pluginInfo→メタ一致assert
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 自己記述あり

### logic_fn.settings.py:auto_apply_enabled — auto_apply_enabled

- kind: `logic_fn` / source: `settings.py:98`
- signature: `auto_apply_enabled()`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_auto_apply_enabled["呼出元"] --> H_logic_fn_settings_py_auto_apply_enabled["auto_apply_enabled"]
  H_logic_fn_settings_py_auto_apply_enabled --> R_logic_fn_settings_py_auto_apply_enabled["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_auto_apply_enabled --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:check_excel_launch — check_excel_launch

- kind: `logic_fn` / source: `settings.py:156`
- signature: `check_excel_launch()`
- 要約: Excelを実際にCOM起動して検証する(既存インスタンスがあれば再利用しQuitしない)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_check_excel_launch["呼出元"] --> H_logic_fn_settings_py_check_excel_launch["check_excel_launch"]
  H_logic_fn_settings_py_check_excel_launch --> R_logic_fn_settings_py_check_excel_launch["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_check_excel_launch --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:configured_template — configured_template

- kind: `logic_fn` / source: `settings.py:232`
- signature: `configured_template(kind)`
- 要約: QSettingsのテンプレート指定(未設定なら空文字)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_configured_template["呼出元"] --> H_logic_fn_settings_py_configured_template["configured_template"]
  H_logic_fn_settings_py_configured_template --> R_logic_fn_settings_py_configured_template["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_configured_template --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:current_settings — current_settings

- kind: `logic_fn` / source: `settings.py:102`
- signature: `current_settings()`
- 要約: UI/bridge表示用の現在の既定値セット。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_current_settings["呼出元"] --> H_logic_fn_settings_py_current_settings["current_settings"]
  H_logic_fn_settings_py_current_settings --> R_logic_fn_settings_py_current_settings["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_current_settings --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:documents_dir — documents_dir

- kind: `logic_fn` / source: `settings.py:67`
- signature: `documents_dir()`
- 要約: OSのドキュメントフォルダを返す(取得不可なら ~/Documents)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_documents_dir["呼出元"] --> H_logic_fn_settings_py_documents_dir["documents_dir"]
  H_logic_fn_settings_py_documents_dir --> R_logic_fn_settings_py_documents_dir["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_documents_dir --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:ensure_layer_variables — ensure_layer_variables

- kind: `logic_fn` / source: `settings.py:274`
- signature: `ensure_layer_variables(layer, script_file)`
- 要約: 不足している必須レイヤ変数へ既定値を適用する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_ensure_layer_variables["呼出元"] --> H_logic_fn_settings_py_ensure_layer_variables["ensure_layer_variables"]
  H_logic_fn_settings_py_ensure_layer_variables --> R_logic_fn_settings_py_ensure_layer_variables["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_ensure_layer_variables --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:environment_report — environment_report

- kind: `logic_fn` / source: `settings.py:179`
- signature: `environment_report()`
- 要約: 設定UI/bridge用の環境サマリ。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_environment_report["呼出元"] --> H_logic_fn_settings_py_environment_report["environment_report"]
  H_logic_fn_settings_py_environment_report --> R_logic_fn_settings_py_environment_report["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_environment_report --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:excel_registered — excel_registered

- kind: `logic_fn` / source: `settings.py:138`
- signature: `excel_registered()`
- 要約: ExcelのCOM登録(HKCR\Excel.Application)の有無をレジストリで確認。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_excel_registered["呼出元"] --> H_logic_fn_settings_py_excel_registered["excel_registered"]
  H_logic_fn_settings_py_excel_registered --> R_logic_fn_settings_py_excel_registered["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_excel_registered --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:generate_template — generate_template

- kind: `logic_fn` / source: `settings.py:380`
- signature: `generate_template(path, layer, kind)`
- 要約: レイヤのフィールドから最小限の帳票テンプレートxlsxを生成する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_generate_template["呼出元"] --> H_logic_fn_settings_py_generate_template["generate_template"]
  H_logic_fn_settings_py_generate_template --> R_logic_fn_settings_py_generate_template["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_generate_template --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:generated_template_path — generated_template_path

- kind: `logic_fn` / source: `settings.py:225`
- signature: `generated_template_path(kind, layer)`
- 要約: 自動生成テンプレートのパス: <出力先>/templates/<レイヤ名>_<種別>.xlsx
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_generated_template_path["呼出元"] --> H_logic_fn_settings_py_generated_template_path["generated_template_path"]
  H_logic_fn_settings_py_generated_template_path --> R_logic_fn_settings_py_generated_template_path["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_generated_template_path --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:output_dir — output_dir

- kind: `logic_fn` / source: `settings.py:90`
- signature: `output_dir()`
- 要約: 帳票の既定出力先。既定は <ドキュメント>/geo_excel。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_output_dir["呼出元"] --> H_logic_fn_settings_py_output_dir["output_dir"]
  H_logic_fn_settings_py_output_dir --> R_logic_fn_settings_py_output_dir["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_output_dir --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:requirements — requirements

- kind: `logic_fn` / source: `settings.py:191`
- signature: `requirements()`
- 要約: 実行に必要なものの列挙(UIの案内文とbridgeの情報用)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_requirements["呼出元"] --> H_logic_fn_settings_py_requirements["requirements"]
  H_logic_fn_settings_py_requirements --> R_logic_fn_settings_py_requirements["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_requirements --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:save_settings — save_settings

- kind: `logic_fn` / source: `settings.py:114`
- signature: `save_settings(output_dir_value=…, dpi=…, template_list=…, template_single=…, auto_apply=…)`
- 要約: UIからまとめて保存。Noneの項目は変更しない。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_save_settings["呼出元"] --> H_logic_fn_settings_py_save_settings["save_settings"]
  H_logic_fn_settings_py_save_settings --> R_logic_fn_settings_py_save_settings["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_save_settings --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:script_variable_spec — script_variable_spec

- kind: `logic_fn` / source: `settings.py:205`
- signature: `script_variable_spec()`
- 要約: 帳票スクリプトごとの必須/任意レイヤ変数定義を返す。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_script_variable_spec["呼出元"] --> H_logic_fn_settings_py_script_variable_spec["script_variable_spec"]
  H_logic_fn_settings_py_script_variable_spec --> R_logic_fn_settings_py_script_variable_spec["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_script_variable_spec --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:set_setting — set_setting

- kind: `logic_fn` / source: `settings.py:81`
- signature: `set_setting(key, value)`
- 要約: 空文字/Noneはキー自体を削除(=デフォルトに戻す)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_set_setting["呼出元"] --> H_logic_fn_settings_py_set_setting["set_setting"]
  H_logic_fn_settings_py_set_setting --> R_logic_fn_settings_py_set_setting["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_set_setting --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:setting — setting

- kind: `logic_fn` / source: `settings.py:76`
- signature: `setting(key, default=…)`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_setting["呼出元"] --> H_logic_fn_settings_py_setting["setting"]
  H_logic_fn_settings_py_setting --> R_logic_fn_settings_py_setting["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_setting --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:win32com_available — win32com_available

- kind: `logic_fn` / source: `settings.py:130`
- signature: `win32com_available()`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_win32com_available["呼出元"] --> H_logic_fn_settings_py_win32com_available["win32com_available"]
  H_logic_fn_settings_py_win32com_available --> R_logic_fn_settings_py_win32com_available["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_win32com_available --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.settings.py:write_xlsx — write_xlsx

- kind: `logic_fn` / source: `settings.py:316`
- signature: `write_xlsx(path, rows, sheet_name=…)`
- 要約: 最小構成のxlsxを生成する(inlineStrセルのみ)。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_settings_py_write_xlsx["呼出元"] --> H_logic_fn_settings_py_write_xlsx["write_xlsx"]
  H_logic_fn_settings_py_write_xlsx --> R_logic_fn_settings_py_write_xlsx["QGIS/ランタイムAPI"]
  R_logic_fn_settings_py_write_xlsx --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **pass** 2026-11-14T07:09:57+09:00 — 属性/シンボル実在確認(pyeval)

### logic_fn.exportList.py:append_list_insert — append_list_insert

- kind: `template_fn` / source: `exportList.py:250`
- signature: `append_list_insert(ws, cell, list_insert_list, extent)`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_append_list_insert["呼出元"] --> H_logic_fn_exportList_py_append_list_insert["append_list_insert"]
  H_logic_fn_exportList_py_append_list_insert --> R_logic_fn_exportList_py_append_list_insert["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_append_list_insert --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:check_same_name_opend — check_same_name_opend

- kind: `template_fn` / source: `exportList.py:538`
- signature: `check_same_name_opend(excel_app, book_name)`
- 要約: 同名のブックが現在開かれていないか確認する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_check_same_name_opend["呼出元"] --> H_logic_fn_exportList_py_check_same_name_opend["check_same_name_opend"]
  H_logic_fn_exportList_py_check_same_name_opend --> R_logic_fn_exportList_py_check_same_name_opend["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_check_same_name_opend --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:check_save_folder — check_save_folder

- kind: `template_fn` / source: `exportList.py:481`
- signature: `check_save_folder(path)`
- 要約: 保存ファイルパスのディレクトリが存在しなければ再帰的に作成する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_check_save_folder["呼出元"] --> H_logic_fn_exportList_py_check_save_folder["check_save_folder"]
  H_logic_fn_exportList_py_check_save_folder --> R_logic_fn_exportList_py_check_save_folder["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_check_save_folder --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:contains_text_in_first_cell — contains_text_in_first_cell

- kind: `template_fn` / source: `exportList.py:231`
- signature: `contains_text_in_first_cell(ws, text)`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_contains_text_in_first_cell["呼出元"] --> H_logic_fn_exportList_py_contains_text_in_first_cell["contains_text_in_first_cell"]
  H_logic_fn_exportList_py_contains_text_in_first_cell --> R_logic_fn_exportList_py_contains_text_in_first_cell["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_contains_text_in_first_cell --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:create_expression — create_expression

- kind: `template_fn` / source: `exportList.py:160`
- signature: `create_expression(text)`
- 要約: 引数の文字列から新しい式を作成するオブジェクトを作成
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_create_expression["呼出元"] --> H_logic_fn_exportList_py_create_expression["create_expression"]
  H_logic_fn_exportList_py_create_expression --> R_logic_fn_exportList_py_create_expression["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_create_expression --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:evaluate_attach_text — evaluate_attach_text

- kind: `template_fn` / source: `exportList.py:120`
- signature: `evaluate_attach_text(text, layer=…, feature=…)`
- 要約: ##ListInsert:: / ##Attach:: の後に続く指定文字列を評価して結果を返却する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_evaluate_attach_text["呼出元"] --> H_logic_fn_exportList_py_evaluate_attach_text["evaluate_attach_text"]
  H_logic_fn_exportList_py_evaluate_attach_text --> R_logic_fn_exportList_py_evaluate_attach_text["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_evaluate_attach_text --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:excel_value_text — excel_value_text

- kind: `template_fn` / source: `exportList.py:102`
- signature: `excel_value_text(value)`
- 要約: 評価結果をExcel出力用の値に変換する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_excel_value_text["呼出元"] --> H_logic_fn_exportList_py_excel_value_text["excel_value_text"]
  H_logic_fn_exportList_py_excel_value_text --> R_logic_fn_exportList_py_excel_value_text["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_excel_value_text --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:find_list_insert — find_list_insert

- kind: `template_fn` / source: `exportList.py:294`
- signature: `find_list_insert(ws, list_insert_list, extent)`
- 要約: シート内の##ListInsert::を含むセルから一覧の行として繰り返す情報をリストにする。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_find_list_insert["呼出元"] --> H_logic_fn_exportList_py_find_list_insert["find_list_insert"]
  H_logic_fn_exportList_py_find_list_insert --> R_logic_fn_exportList_py_find_list_insert["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_find_list_insert --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:get_layer_variable — get_layer_variable

- kind: `template_fn` / source: `exportList.py:39`
- signature: `get_layer_variable(layer_context_name, layer)`
- 要約: レイヤ変数を取得
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_get_layer_variable["呼出元"] --> H_logic_fn_exportList_py_get_layer_variable["get_layer_variable"]
  H_logic_fn_exportList_py_get_layer_variable --> R_logic_fn_exportList_py_get_layer_variable["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_get_layer_variable --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:get_layer_variable_evaluated — get_layer_variable_evaluated

- kind: `template_fn` / source: `exportList.py:201`
- signature: `get_layer_variable_evaluated(layer_context_name, layer)`
- 要約: 指定の名前のレイヤ変数を取得し、式なら評価後の文字列を返却する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_get_layer_variable_evaluated["呼出元"] --> H_logic_fn_exportList_py_get_layer_variable_evaluated["get_layer_variable_evaluated"]
  H_logic_fn_exportList_py_get_layer_variable_evaluated --> R_logic_fn_exportList_py_get_layer_variable_evaluated["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_get_layer_variable_evaluated --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:insert_list — insert_list

- kind: `template_fn` / source: `exportList.py:451`
- signature: `insert_list(wb, layer)`
- 要約: ワークブックの全シートに一覧を作成する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_insert_list["呼出元"] --> H_logic_fn_exportList_py_insert_list["insert_list"]
  H_logic_fn_exportList_py_insert_list --> R_logic_fn_exportList_py_insert_list["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_insert_list --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:insert_list_values — insert_list_values

- kind: `template_fn` / source: `exportList.py:347`
- signature: `insert_list_values(ws, layer, list_insert_list, extent)`
- 要約: 一覧の行として繰り返す情報リストを元に、レイヤの全地物の情報をシートに出力する.
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_insert_list_values["呼出元"] --> H_logic_fn_exportList_py_insert_list_values["insert_list_values"]
  H_logic_fn_exportList_py_insert_list_values --> R_logic_fn_exportList_py_insert_list_values["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_insert_list_values --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:make_expression_context — make_expression_context

- kind: `template_fn` / source: `exportList.py:58`
- signature: `make_expression_context(layer=…, feature=…)`
- 要約: 式評価用のコンテキストを作成する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_make_expression_context["呼出元"] --> H_logic_fn_exportList_py_make_expression_context["make_expression_context"]
  H_logic_fn_exportList_py_make_expression_context --> R_logic_fn_exportList_py_make_expression_context["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_make_expression_context --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportList.py:output_list_report — output_list_report

- kind: `template_fn` / source: `exportList.py:496`
- signature: `output_list_report(excel_app, layer, template_path, output_path)`
- 要約: 一覧出力
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportList_py_output_list_report["呼出元"] --> H_logic_fn_exportList_py_output_list_report["output_list_report"]
  H_logic_fn_exportList_py_output_list_report --> R_logic_fn_exportList_py_output_list_report["QGIS/ランタイムAPI"]
  R_logic_fn_exportList_py_output_list_report --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:add_temp_theme_from_current_state — add_temp_theme_from_current_state

- kind: `template_fn` / source: `exportSingle.py:672`
- signature: `add_temp_theme_from_current_state()`
- 要約: 現在の状態で仮のテーマを作成する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_add_temp_theme_from_current_state["呼出元"] --> H_logic_fn_exportSingle_py_add_temp_theme_from_current_state["add_temp_theme_from_current_state"]
  H_logic_fn_exportSingle_py_add_temp_theme_from_current_state --> R_logic_fn_exportSingle_py_add_temp_theme_from_current_state["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_add_temp_theme_from_current_state --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:append_attach — append_attach

- kind: `template_fn` / source: `exportSingle.py:283`
- signature: `append_attach(ws, cell, attach_list)`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_append_attach["呼出元"] --> H_logic_fn_exportSingle_py_append_attach["append_attach"]
  H_logic_fn_exportSingle_py_append_attach --> R_logic_fn_exportSingle_py_append_attach["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_append_attach --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:append_attach_fit_image — append_attach_fit_image

- kind: `template_fn` / source: `exportSingle.py:358`
- signature: `append_attach_fit_image(ws, cell, attach_list, image_dict, tmpdir, default_scale)`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_append_attach_fit_image["呼出元"] --> H_logic_fn_exportSingle_py_append_attach_fit_image["append_attach_fit_image"]
  H_logic_fn_exportSingle_py_append_attach_fit_image --> R_logic_fn_exportSingle_py_append_attach_fit_image["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_append_attach_fit_image --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:change_theme — change_theme

- kind: `template_fn` / source: `exportSingle.py:646`
- signature: `change_theme(theme_name)`
- 要約: テーマ変更
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_change_theme["呼出元"] --> H_logic_fn_exportSingle_py_change_theme["change_theme"]
  H_logic_fn_exportSingle_py_change_theme --> R_logic_fn_exportSingle_py_change_theme["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_change_theme --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:check_same_name_opend — check_same_name_opend

- kind: `template_fn` / source: `exportSingle.py:866`
- signature: `check_same_name_opend(excel_app, book_name)`
- 要約: 同名のブックが現在開かれていないか確認する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_check_same_name_opend["呼出元"] --> H_logic_fn_exportSingle_py_check_same_name_opend["check_same_name_opend"]
  H_logic_fn_exportSingle_py_check_same_name_opend --> R_logic_fn_exportSingle_py_check_same_name_opend["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_check_same_name_opend --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:check_save_folder — check_save_folder

- kind: `template_fn` / source: `exportSingle.py:786`
- signature: `check_save_folder(path)`
- 要約: 保存ファイルパスのディレクトリが存在しなければ再帰的に作成する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_check_save_folder["呼出元"] --> H_logic_fn_exportSingle_py_check_save_folder["check_save_folder"]
  H_logic_fn_exportSingle_py_check_save_folder --> R_logic_fn_exportSingle_py_check_save_folder["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_check_save_folder --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:contains_text_in_first_cell — contains_text_in_first_cell

- kind: `template_fn` / source: `exportSingle.py:264`
- signature: `contains_text_in_first_cell(ws, text)`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_contains_text_in_first_cell["呼出元"] --> H_logic_fn_exportSingle_py_contains_text_in_first_cell["contains_text_in_first_cell"]
  H_logic_fn_exportSingle_py_contains_text_in_first_cell --> R_logic_fn_exportSingle_py_contains_text_in_first_cell["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_contains_text_in_first_cell --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:create_expression — create_expression

- kind: `template_fn` / source: `exportSingle.py:172`
- signature: `create_expression(text)`
- 要約: 引数の文字列から新しい式を作成するオブジェクトを作成
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_create_expression["呼出元"] --> H_logic_fn_exportSingle_py_create_expression["create_expression"]
  H_logic_fn_exportSingle_py_create_expression --> R_logic_fn_exportSingle_py_create_expression["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_create_expression --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:create_map_image — create_map_image

- kind: `template_fn` / source: `exportSingle.py:511`
- signature: `create_map_image(filepath, map_scale, pt_width, pt_height, dpi, theme_name)`
- 要約: 地図画像を作成する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_create_map_image["呼出元"] --> H_logic_fn_exportSingle_py_create_map_image["create_map_image"]
  H_logic_fn_exportSingle_py_create_map_image --> R_logic_fn_exportSingle_py_create_map_image["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_create_map_image --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:create_map_images — create_map_images

- kind: `template_fn` / source: `exportSingle.py:461`
- signature: `create_map_images(image_dict, dpi)`
- 要約: 地図画像ファイルを一時フォルダに作成する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_create_map_images["呼出元"] --> H_logic_fn_exportSingle_py_create_map_images["create_map_images"]
  H_logic_fn_exportSingle_py_create_map_images --> R_logic_fn_exportSingle_py_create_map_images["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_create_map_images --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:evaluate_attach_text — evaluate_attach_text

- kind: `template_fn` / source: `exportSingle.py:132`
- signature: `evaluate_attach_text(text, layer=…, feature=…)`
- 要約: ##Attach:: / ##ListInsert:: の後に続く指定文字列を評価して結果を返却する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_evaluate_attach_text["呼出元"] --> H_logic_fn_exportSingle_py_evaluate_attach_text["evaluate_attach_text"]
  H_logic_fn_exportSingle_py_evaluate_attach_text --> R_logic_fn_exportSingle_py_evaluate_attach_text["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_evaluate_attach_text --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:excel_value_text — excel_value_text

- kind: `template_fn` / source: `exportSingle.py:114`
- signature: `excel_value_text(value)`
- 要約: 評価結果をExcel出力用の値に変換する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_excel_value_text["呼出元"] --> H_logic_fn_exportSingle_py_excel_value_text["excel_value_text"]
  H_logic_fn_exportSingle_py_excel_value_text --> R_logic_fn_exportSingle_py_excel_value_text["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_excel_value_text --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:find_attach — find_attach

- kind: `template_fn` / source: `exportSingle.py:313`
- signature: `find_attach(wb, feature, attach_list)`
- 要約: 指定ブックの全てのシート内から「##Attach::（地物属性名または式）」文字列を検索し、その情報をリストに登録。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_find_attach["呼出元"] --> H_logic_fn_exportSingle_py_find_attach["find_attach"]
  H_logic_fn_exportSingle_py_find_attach --> R_logic_fn_exportSingle_py_find_attach["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_find_attach --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:find_attach_fit_image — find_attach_fit_image

- kind: `template_fn` / source: `exportSingle.py:409`
- signature: `find_attach_fit_image(wb, attach_list, tmpdir, default_scale, dpi)`
- 要約: 指定ブックの全てのシート内から「##AttachFitImage::（テーマ名）::（縮尺）」文字列を検索し、
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_find_attach_fit_image["呼出元"] --> H_logic_fn_exportSingle_py_find_attach_fit_image["find_attach_fit_image"]
  H_logic_fn_exportSingle_py_find_attach_fit_image --> R_logic_fn_exportSingle_py_find_attach_fit_image["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_find_attach_fit_image --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:get_layer_variable — get_layer_variable

- kind: `template_fn` / source: `exportSingle.py:51`
- signature: `get_layer_variable(layer_context_name, layer)`
- 要約: レイヤ変数を取得
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_get_layer_variable["呼出元"] --> H_logic_fn_exportSingle_py_get_layer_variable["get_layer_variable"]
  H_logic_fn_exportSingle_py_get_layer_variable --> R_logic_fn_exportSingle_py_get_layer_variable["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_get_layer_variable --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:get_layer_variable_on_feature — get_layer_variable_on_feature

- kind: `template_fn` / source: `exportSingle.py:235`
- signature: `get_layer_variable_on_feature(layer_context_name, layer, feature, noerror=…)`
- 要約: レイヤ変数を取得し、指定地物の属性値から文字列を作成する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_get_layer_variable_on_feature["呼出元"] --> H_logic_fn_exportSingle_py_get_layer_variable_on_feature["get_layer_variable_on_feature"]
  H_logic_fn_exportSingle_py_get_layer_variable_on_feature --> R_logic_fn_exportSingle_py_get_layer_variable_on_feature["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_get_layer_variable_on_feature --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:insert_images — insert_images

- kind: `template_fn` / source: `exportSingle.py:754`
- signature: `insert_images(wb, attach_image_list)`
- 要約: 指定ブックの全シートの該当セルにリストの内容に従い画像を挿入する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_insert_images["呼出元"] --> H_logic_fn_exportSingle_py_insert_images["insert_images"]
  H_logic_fn_exportSingle_py_insert_images --> R_logic_fn_exportSingle_py_insert_images["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_insert_images --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:make_expression_context — make_expression_context

- kind: `template_fn` / source: `exportSingle.py:70`
- signature: `make_expression_context(layer=…, feature=…)`
- 要約: 式評価用のコンテキストを作成する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_make_expression_context["呼出元"] --> H_logic_fn_exportSingle_py_make_expression_context["make_expression_context"]
  H_logic_fn_exportSingle_py_make_expression_context --> R_logic_fn_exportSingle_py_make_expression_context["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_make_expression_context --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:output_single_report — output_single_report

- kind: `template_fn` / source: `exportSingle.py:801`
- signature: `output_single_report(excel_app, template_path, feature, output_path, dpi)`
- 要約: 対象地物の情報で単票形式のExcelブックを作成、保存する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_output_single_report["呼出元"] --> H_logic_fn_exportSingle_py_output_single_report["output_single_report"]
  H_logic_fn_exportSingle_py_output_single_report --> R_logic_fn_exportSingle_py_output_single_report["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_output_single_report --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:replace_attach — replace_attach

- kind: `template_fn` / source: `exportSingle.py:714`
- signature: `replace_attach(wb, attach_list)`
- 要約: 指定ブックの全シートの該当セルの値をリストの内容で置換する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_replace_attach["呼出元"] --> H_logic_fn_exportSingle_py_replace_attach["replace_attach"]
  H_logic_fn_exportSingle_py_replace_attach --> R_logic_fn_exportSingle_py_replace_attach["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_replace_attach --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:restore_from_temp_theme — restore_from_temp_theme

- kind: `template_fn` / source: `exportSingle.py:697`
- signature: `restore_from_temp_theme(temp_theme_name, map_scale)`
- 要約: 指定の仮のテーマを適用後、削除する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_restore_from_temp_theme["呼出元"] --> H_logic_fn_exportSingle_py_restore_from_temp_theme["restore_from_temp_theme"]
  H_logic_fn_exportSingle_py_restore_from_temp_theme --> R_logic_fn_exportSingle_py_restore_from_temp_theme["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_restore_from_temp_theme --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingle.py:variable_based_on_feature — variable_based_on_feature

- kind: `template_fn` / source: `exportSingle.py:213`
- signature: `variable_based_on_feature(text, feature, layer=…)`
- 要約: 地物の属性値を使用して文字列を作成
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingle_py_variable_based_on_feature["呼出元"] --> H_logic_fn_exportSingle_py_variable_based_on_feature["variable_based_on_feature"]
  H_logic_fn_exportSingle_py_variable_based_on_feature --> R_logic_fn_exportSingle_py_variable_based_on_feature["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingle_py_variable_based_on_feature --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:add_temp_theme_from_current_state — add_temp_theme_from_current_state

- kind: `template_fn` / source: `exportSingleBulk.py:660`
- signature: `add_temp_theme_from_current_state()`
- 要約: 現在の状態で仮のテーマを作成する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_add_temp_theme_from_current_state["呼出元"] --> H_logic_fn_exportSingleBulk_py_add_temp_theme_from_current_state["add_temp_theme_from_current_state"]
  H_logic_fn_exportSingleBulk_py_add_temp_theme_from_current_state --> R_logic_fn_exportSingleBulk_py_add_temp_theme_from_current_state["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_add_temp_theme_from_current_state --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:append_attach — append_attach

- kind: `template_fn` / source: `exportSingleBulk.py:271`
- signature: `append_attach(ws, cell, attach_list)`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_append_attach["呼出元"] --> H_logic_fn_exportSingleBulk_py_append_attach["append_attach"]
  H_logic_fn_exportSingleBulk_py_append_attach --> R_logic_fn_exportSingleBulk_py_append_attach["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_append_attach --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:append_attach_fit_image — append_attach_fit_image

- kind: `template_fn` / source: `exportSingleBulk.py:347`
- signature: `append_attach_fit_image(ws, cell, attach_list, image_dict, tmpdir, default_scale)`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_append_attach_fit_image["呼出元"] --> H_logic_fn_exportSingleBulk_py_append_attach_fit_image["append_attach_fit_image"]
  H_logic_fn_exportSingleBulk_py_append_attach_fit_image --> R_logic_fn_exportSingleBulk_py_append_attach_fit_image["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_append_attach_fit_image --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:change_theme — change_theme

- kind: `template_fn` / source: `exportSingleBulk.py:634`
- signature: `change_theme(theme_name)`
- 要約: テーマ変更
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_change_theme["呼出元"] --> H_logic_fn_exportSingleBulk_py_change_theme["change_theme"]
  H_logic_fn_exportSingleBulk_py_change_theme --> R_logic_fn_exportSingleBulk_py_change_theme["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_change_theme --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:check_save_folder — check_save_folder

- kind: `template_fn` / source: `exportSingleBulk.py:774`
- signature: `check_save_folder(path)`
- 要約: 保存ファイルパスのディレクトリが存在しなければ再帰的に作成する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_check_save_folder["呼出元"] --> H_logic_fn_exportSingleBulk_py_check_save_folder["check_save_folder"]
  H_logic_fn_exportSingleBulk_py_check_save_folder --> R_logic_fn_exportSingleBulk_py_check_save_folder["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_check_save_folder --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:contains_text_in_first_cell — contains_text_in_first_cell

- kind: `template_fn` / source: `exportSingleBulk.py:252`
- signature: `contains_text_in_first_cell(ws, text)`
- 要約: 
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_contains_text_in_first_cell["呼出元"] --> H_logic_fn_exportSingleBulk_py_contains_text_in_first_cell["contains_text_in_first_cell"]
  H_logic_fn_exportSingleBulk_py_contains_text_in_first_cell --> R_logic_fn_exportSingleBulk_py_contains_text_in_first_cell["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_contains_text_in_first_cell --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:create_expression — create_expression

- kind: `template_fn` / source: `exportSingleBulk.py:171`
- signature: `create_expression(text)`
- 要約: 引数の文字列から新しい式を作成するオブジェクトを作成
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_create_expression["呼出元"] --> H_logic_fn_exportSingleBulk_py_create_expression["create_expression"]
  H_logic_fn_exportSingleBulk_py_create_expression --> R_logic_fn_exportSingleBulk_py_create_expression["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_create_expression --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:create_map_image — create_map_image

- kind: `template_fn` / source: `exportSingleBulk.py:499`
- signature: `create_map_image(filepath, map_scale, pt_width, pt_height, dpi, theme_name)`
- 要約: 地図画像を作成する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_create_map_image["呼出元"] --> H_logic_fn_exportSingleBulk_py_create_map_image["create_map_image"]
  H_logic_fn_exportSingleBulk_py_create_map_image --> R_logic_fn_exportSingleBulk_py_create_map_image["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_create_map_image --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:create_map_images — create_map_images

- kind: `template_fn` / source: `exportSingleBulk.py:450`
- signature: `create_map_images(image_dict, dpi)`
- 要約: 地図画像ファイルを一時フォルダに作成する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_create_map_images["呼出元"] --> H_logic_fn_exportSingleBulk_py_create_map_images["create_map_images"]
  H_logic_fn_exportSingleBulk_py_create_map_images --> R_logic_fn_exportSingleBulk_py_create_map_images["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_create_map_images --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:evaluate_attach_text — evaluate_attach_text

- kind: `template_fn` / source: `exportSingleBulk.py:131`
- signature: `evaluate_attach_text(text, layer=…, feature=…)`
- 要約: ##Attach:: の後に続く指定文字列を評価して結果を返却する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_evaluate_attach_text["呼出元"] --> H_logic_fn_exportSingleBulk_py_evaluate_attach_text["evaluate_attach_text"]
  H_logic_fn_exportSingleBulk_py_evaluate_attach_text --> R_logic_fn_exportSingleBulk_py_evaluate_attach_text["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_evaluate_attach_text --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:excel_value_text — excel_value_text

- kind: `template_fn` / source: `exportSingleBulk.py:113`
- signature: `excel_value_text(value)`
- 要約: 評価結果をExcel出力用の値に変換する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_excel_value_text["呼出元"] --> H_logic_fn_exportSingleBulk_py_excel_value_text["excel_value_text"]
  H_logic_fn_exportSingleBulk_py_excel_value_text --> R_logic_fn_exportSingleBulk_py_excel_value_text["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_excel_value_text --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:find_attach — find_attach

- kind: `template_fn` / source: `exportSingleBulk.py:302`
- signature: `find_attach(wb, feature, attach_list)`
- 要約: 指定ブックの全てのシート内から「##Attach::（地物属性名または式）」文字列を検索し、その情報をリストに登録。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_find_attach["呼出元"] --> H_logic_fn_exportSingleBulk_py_find_attach["find_attach"]
  H_logic_fn_exportSingleBulk_py_find_attach --> R_logic_fn_exportSingleBulk_py_find_attach["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_find_attach --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:find_attach_fit_image — find_attach_fit_image

- kind: `template_fn` / source: `exportSingleBulk.py:398`
- signature: `find_attach_fit_image(wb, attach_list, tmpdir, default_scale, dpi)`
- 要約: 指定ブックの全てのシート内から「##AttachFitImage::（テーマ名）::（縮尺）」文字列を検索し、
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_find_attach_fit_image["呼出元"] --> H_logic_fn_exportSingleBulk_py_find_attach_fit_image["find_attach_fit_image"]
  H_logic_fn_exportSingleBulk_py_find_attach_fit_image --> R_logic_fn_exportSingleBulk_py_find_attach_fit_image["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_find_attach_fit_image --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:get_exp_variable_for_feature — get_exp_variable_for_feature

- kind: `template_fn` / source: `exportSingleBulk.py:234`
- signature: `get_exp_variable_for_feature(exp, feature, layer=…)`
- 要約: 指定の式に地物を設定し、評価した結果を返却する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_get_exp_variable_for_feature["呼出元"] --> H_logic_fn_exportSingleBulk_py_get_exp_variable_for_feature["get_exp_variable_for_feature"]
  H_logic_fn_exportSingleBulk_py_get_exp_variable_for_feature --> R_logic_fn_exportSingleBulk_py_get_exp_variable_for_feature["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_get_exp_variable_for_feature --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:get_exp_variable_for_layer — get_exp_variable_for_layer

- kind: `template_fn` / source: `exportSingleBulk.py:895`
- signature: `get_exp_variable_for_layer(raw)`
- 要約: テンプレートファイルパス、出力ファイルパスの辞書から、式として成り立つものを抽出して辞書にして返却する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_get_exp_variable_for_layer["呼出元"] --> H_logic_fn_exportSingleBulk_py_get_exp_variable_for_layer["get_exp_variable_for_layer"]
  H_logic_fn_exportSingleBulk_py_get_exp_variable_for_layer --> R_logic_fn_exportSingleBulk_py_get_exp_variable_for_layer["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_get_exp_variable_for_layer --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:get_layer_variable — get_layer_variable

- kind: `template_fn` / source: `exportSingleBulk.py:50`
- signature: `get_layer_variable(layer_context_name, layer)`
- 要約: レイヤ変数を取得
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_get_layer_variable["呼出元"] --> H_logic_fn_exportSingleBulk_py_get_layer_variable["get_layer_variable"]
  H_logic_fn_exportSingleBulk_py_get_layer_variable --> R_logic_fn_exportSingleBulk_py_get_layer_variable["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_get_layer_variable --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:get_raw_variable_for_layer — get_raw_variable_for_layer

- kind: `template_fn` / source: `exportSingleBulk.py:863`
- signature: `get_raw_variable_for_layer(layer)`
- 要約: レイヤ変数からテンプレートファイルパス、出力ファイルパスを取得し、設定値を辞書にして返却する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_get_raw_variable_for_layer["呼出元"] --> H_logic_fn_exportSingleBulk_py_get_raw_variable_for_layer["get_raw_variable_for_layer"]
  H_logic_fn_exportSingleBulk_py_get_raw_variable_for_layer --> R_logic_fn_exportSingleBulk_py_get_raw_variable_for_layer["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_get_raw_variable_for_layer --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:get_variable_for_feature — get_variable_for_feature

- kind: `template_fn` / source: `exportSingleBulk.py:920`
- signature: `get_variable_for_feature(feature, raw, exp, variable_name)`
- 要約: レイヤ変数からテンプレートファイルパス、出力ファイルパスを抽出し、文字列あるいは式を評価した結果を返却する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_get_variable_for_feature["呼出元"] --> H_logic_fn_exportSingleBulk_py_get_variable_for_feature["get_variable_for_feature"]
  H_logic_fn_exportSingleBulk_py_get_variable_for_feature --> R_logic_fn_exportSingleBulk_py_get_variable_for_feature["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_get_variable_for_feature --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:insert_images — insert_images

- kind: `template_fn` / source: `exportSingleBulk.py:742`
- signature: `insert_images(wb, attach_image_list)`
- 要約: 指定ブックの全シートの該当セルにリストの内容に従い画像を挿入する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_insert_images["呼出元"] --> H_logic_fn_exportSingleBulk_py_insert_images["insert_images"]
  H_logic_fn_exportSingleBulk_py_insert_images --> R_logic_fn_exportSingleBulk_py_insert_images["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_insert_images --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:make_expression_context — make_expression_context

- kind: `template_fn` / source: `exportSingleBulk.py:69`
- signature: `make_expression_context(layer=…, feature=…)`
- 要約: 式評価用のコンテキストを作成する。
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_make_expression_context["呼出元"] --> H_logic_fn_exportSingleBulk_py_make_expression_context["make_expression_context"]
  H_logic_fn_exportSingleBulk_py_make_expression_context --> R_logic_fn_exportSingleBulk_py_make_expression_context["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_make_expression_context --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:output_single_report — output_single_report

- kind: `template_fn` / source: `exportSingleBulk.py:789`
- signature: `output_single_report(excel_app, template_path, feature, output_path, dpi, progress)`
- 要約: 対象地物の情報で単票形式のExcelブックを作成、保存する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_output_single_report["呼出元"] --> H_logic_fn_exportSingleBulk_py_output_single_report["output_single_report"]
  H_logic_fn_exportSingleBulk_py_output_single_report --> R_logic_fn_exportSingleBulk_py_output_single_report["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_output_single_report --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:replace_attach — replace_attach

- kind: `template_fn` / source: `exportSingleBulk.py:702`
- signature: `replace_attach(wb, attach_list)`
- 要約: 指定ブックの全シートの該当セルの値をリストの内容で置換する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_replace_attach["呼出元"] --> H_logic_fn_exportSingleBulk_py_replace_attach["replace_attach"]
  H_logic_fn_exportSingleBulk_py_replace_attach --> R_logic_fn_exportSingleBulk_py_replace_attach["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_replace_attach --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:restore_from_temp_theme — restore_from_temp_theme

- kind: `template_fn` / source: `exportSingleBulk.py:685`
- signature: `restore_from_temp_theme(temp_theme_name, map_scale)`
- 要約: 指定の仮のテーマを適用後、削除する
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_restore_from_temp_theme["呼出元"] --> H_logic_fn_exportSingleBulk_py_restore_from_temp_theme["restore_from_temp_theme"]
  H_logic_fn_exportSingleBulk_py_restore_from_temp_theme --> R_logic_fn_exportSingleBulk_py_restore_from_temp_theme["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_restore_from_temp_theme --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

### logic_fn.exportSingleBulk.py:variable_based_on_feature — variable_based_on_feature

- kind: `template_fn` / source: `exportSingleBulk.py:212`
- signature: `variable_based_on_feature(text, feature, layer=…)`
- 要約: 地物の属性値を使用して文字列を作成
- needs_runtime=True / standalone_ok=False

```mermaid
flowchart LR
  E_logic_fn_exportSingleBulk_py_variable_based_on_feature["呼出元"] --> H_logic_fn_exportSingleBulk_py_variable_based_on_feature["variable_based_on_feature"]
  H_logic_fn_exportSingleBulk_py_variable_based_on_feature --> R_logic_fn_exportSingleBulk_py_variable_based_on_feature["QGIS/ランタイムAPI"]
  R_logic_fn_exportSingleBulk_py_variable_based_on_feature --> OUT["結果"]
```

- 検証: 単独= / 連携=pyeval で属性実在+必要なら呼出
- 結果: **skip** 2026-11-14T07:09:57+09:00 — exec用テンプレ(bridge run経由で検証)

## 検証マトリクス

| 機能 | kind | 単独 | 連携 | 結果 |
|---|---|---|---|---|
| entry_point.__init__.py:classFactory | entry_point | ○ | - | pass |
| action.plugin.initGui | action | - | ○ | pass |
| action.plugin.unload | action | - | ○ | pass |
| dialog.GeoExcelSettingsDialog | dialog | - | ○ | pass |
| bridge.applyDefaults | bridge_method | - | ○ | skip |
| bridge.checkExcel | bridge_method | - | ○ | pass |
| bridge.layerVariables | bridge_method | - | ○ | pass |
| bridge.listScripts | bridge_method | - | ○ | pass |
| bridge.openSettings | bridge_method | - | ○ | skip |
| bridge.pluginInfo | bridge_method | - | ○ | pass |
| bridge.regenerateTemplates | bridge_method | - | ○ | pass |
| bridge.run | bridge_method | - | ○ | pass |
| bridge.setLayerVariables | bridge_method | - | ○ | skip |
| bridge.setSettings | bridge_method | - | ○ | skip |
| bridge.settings | bridge_method | - | ○ | pass |
| bridge.status | bridge_method | - | ○ | pass |
| integration.bridge.py:284 | integration | - | ○ | skip |
| integration.bridge.py:292 | integration | - | ○ | skip |
| integration.bridge.py:334 | integration | - | ○ | skip |
| integration.exportList.py:623 | integration | - | ○ | skip |
| integration.exportSingle.py:974 | integration | - | ○ | skip |
| integration.exportSingleBulk.py:1019 | integration | - | ○ | skip |
| integration.settings.py:167 | integration | - | ○ | skip |
| integration.settings.py:182 | integration | - | ○ | skip |
| ai.bridge_route | ai_integration | - | ○ | pass |
| ai.catalog | ai_integration | - | ○ | pass |
| ai.pluginInfo | ai_integration | - | ○ | pass |
| logic_fn.settings.py:auto_apply_enabled | logic_fn | - | ○ | pass |
| logic_fn.settings.py:check_excel_launch | logic_fn | - | ○ | pass |
| logic_fn.settings.py:configured_template | logic_fn | - | ○ | pass |
| logic_fn.settings.py:current_settings | logic_fn | - | ○ | pass |
| logic_fn.settings.py:documents_dir | logic_fn | - | ○ | pass |
| logic_fn.settings.py:ensure_layer_variables | logic_fn | - | ○ | pass |
| logic_fn.settings.py:environment_report | logic_fn | - | ○ | pass |
| logic_fn.settings.py:excel_registered | logic_fn | - | ○ | pass |
| logic_fn.settings.py:generate_template | logic_fn | - | ○ | pass |
| logic_fn.settings.py:generated_template_path | logic_fn | - | ○ | pass |
| logic_fn.settings.py:output_dir | logic_fn | - | ○ | pass |
| logic_fn.settings.py:requirements | logic_fn | - | ○ | pass |
| logic_fn.settings.py:save_settings | logic_fn | - | ○ | pass |
| logic_fn.settings.py:script_variable_spec | logic_fn | - | ○ | pass |
| logic_fn.settings.py:set_setting | logic_fn | - | ○ | pass |
| logic_fn.settings.py:setting | logic_fn | - | ○ | pass |
| logic_fn.settings.py:win32com_available | logic_fn | - | ○ | pass |
| logic_fn.settings.py:write_xlsx | logic_fn | - | ○ | pass |
| logic_fn.exportList.py:append_list_insert | template_fn | - | ○ | skip |
| logic_fn.exportList.py:check_same_name_opend | template_fn | - | ○ | skip |
| logic_fn.exportList.py:check_save_folder | template_fn | - | ○ | skip |
| logic_fn.exportList.py:contains_text_in_first_cell | template_fn | - | ○ | skip |
| logic_fn.exportList.py:create_expression | template_fn | - | ○ | skip |
| logic_fn.exportList.py:evaluate_attach_text | template_fn | - | ○ | skip |
| logic_fn.exportList.py:excel_value_text | template_fn | - | ○ | skip |
| logic_fn.exportList.py:find_list_insert | template_fn | - | ○ | skip |
| logic_fn.exportList.py:get_layer_variable | template_fn | - | ○ | skip |
| logic_fn.exportList.py:get_layer_variable_evaluated | template_fn | - | ○ | skip |
| logic_fn.exportList.py:insert_list | template_fn | - | ○ | skip |
| logic_fn.exportList.py:insert_list_values | template_fn | - | ○ | skip |
| logic_fn.exportList.py:make_expression_context | template_fn | - | ○ | skip |
| logic_fn.exportList.py:output_list_report | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:add_temp_theme_from_current_state | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:append_attach | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:append_attach_fit_image | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:change_theme | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:check_same_name_opend | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:check_save_folder | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:contains_text_in_first_cell | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:create_expression | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:create_map_image | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:create_map_images | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:evaluate_attach_text | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:excel_value_text | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:find_attach | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:find_attach_fit_image | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:get_layer_variable | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:get_layer_variable_on_feature | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:insert_images | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:make_expression_context | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:output_single_report | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:replace_attach | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:restore_from_temp_theme | template_fn | - | ○ | skip |
| logic_fn.exportSingle.py:variable_based_on_feature | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:add_temp_theme_from_current_state | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:append_attach | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:append_attach_fit_image | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:change_theme | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:check_save_folder | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:contains_text_in_first_cell | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:create_expression | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:create_map_image | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:create_map_images | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:evaluate_attach_text | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:excel_value_text | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:find_attach | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:find_attach_fit_image | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:get_exp_variable_for_feature | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:get_exp_variable_for_layer | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:get_layer_variable | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:get_raw_variable_for_layer | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:get_variable_for_feature | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:insert_images | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:make_expression_context | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:output_single_report | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:replace_attach | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:restore_from_temp_theme | template_fn | - | ○ | skip |
| logic_fn.exportSingleBulk.py:variable_based_on_feature | template_fn | - | ○ | skip |