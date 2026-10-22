# geo_userfunc

ユーザー定義Pythonコード(式関数・フック・マクロ)のライブラリ管理プラグイン。

## できること

`<profile>/python/geo_userfunc/` に置いた `*.py` をファイルの中身(AST)で
自動分類し、型に応じてQGISへ登録します。

| 型 | 判定条件 | 登録先 |
|---|---|---|
| 関数型 | `@qgsfunction` デコレータ付き関数 | 式エンジン(フィールド計算等で使える) |
| フック型 | `openProject`/`saveProject`/`closeProject` 定義 | プロジェクト信号へ自動配線 |
| マクロ型 | `main(context)` 定義 | プラグインメニュー + `bridge.run()` |

```python
# マクロ型のエントリ規約 — context には iface/任意レイヤ/他プラグインが入る
def main(context):
    iface = context["iface"]
    geo_excel = context["plugins"].get("geo_excel")
    if geo_excel:
        geo_excel.bridge.run("list", None, True)
```

## 管理

- **プラグイン > geo_userfunc > User function library...** で管理ダイアログ
  (GeoSuite共有ツールバーのアイコンからも開ける)
- 有効/無効の切替・編集・再読込・URL取得・upstream一括更新
- 有効状態は `manifest.json` に永続化

## AI/外部制御

`qgis_live_driver` の `bridge_call` から利用:

```json
{"command": "bridge_call", "plugin": "geo_userfunc",
 "method": "evalExpression", "args": ["zen2han('ＡＢＣ１２３')"]}
```

主なメソッド: `listFunctions` / `listMacros` / `run` / `evalExpression` /
`readFunction` / `saveFunction` / `deleteFunction` / `setEnabled` /
`reload` / `updateFromUpstream` / `status` / `openManager`

`saveFunction` → `reload` → `evalExpression` で、AIが関数を書いて
即座に登録・動作確認するループを回せます。

## 他プラグインからの登録

```python
def register_user_functions(self, registry):
    registry.register_macro(
        "my_plugin.my_macro", title="My macro",
        callback=self._run, plugin_id="my_plugin")
```

geo_userfunc の initGui がこの規約メソッドを探索して呼びます(pull)。
または各プラグインの initGui で `plugins['geo_userfunc'].registry` を
直接呼ぶこともできます(push)。geo_userfunc が無い環境では
各プラグインが自前のメニューへフォールバックしてください。

## upstream 追従

同梱 `functions/` は初回起動時にライブラリdirへシードされ、
その後はライブラリdirが正本です。`sources.json` に定義されたURLは
管理ダイアログまたは `updateFromUpstream` で再取得できます。

初期同梱: [QGIS_user_function](https://github.com/yamamoto-ryuzo/QGIS_user_function)
の `python`(`zen2han` 式関数など)を `user_functions.py` として同梱。

# 免責事項

本システムは個人のPCで作成・テストされたものです。  
ご利用によるいかなる損害も責任を負いません。

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>