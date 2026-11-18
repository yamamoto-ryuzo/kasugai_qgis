# 凡例作成(geo_legend)

レイヤのシンボル凡例・印刷レイアウトの凡例アイテム・凡例画像の作成手順。
use_when: ユーザーが凡例の作成・色分け/分類/階級区分・ルールベーススタイル・印刷レイアウトへの凡例追加・凡例画像出力を依頼したとき

## 基本方針

- 凡例作成は **`qgis_bridge_call` → `plugin_id="geo_legend"`** の専用メソッドを
  使う。pyeval でレンダラを直書きしない(QGIS4 で API 名が揺れるため)
- `layer` 引数は layer_id/レイヤ名どちらでも可。**省略時はアクティブレイヤ**
- どのメソッドも応答は `{ok, layer, renderer, items[], legend_items[]}` 形式で、
  結果の凡例項目をそのまま確認できる

## メソッド一覧

| メソッド | args | 用途 |
|---|---|---|
| `legendSpec` | `[layer]` | 現在のレンダラ定義の確認(type/field/項目のlabel・値域・filter・color) |
| `applyCategories` | `[layer, field, ramp, labels, colors]` | 個別値分類(地目・種別等の文字列/整数カテゴリ) |
| `applyGraduated` | `[layer, field, classes, ramp, method]` | 数値の階級区分。method=`equal`(等間隔)/`quantile`(分位数) |
| `applyRules` | `[layer, rules, else_label]` | 式ベースの自由分類(範囲・条件・縮尺帯) |
| `applySingleSymbol` | `[layer, color]` | 単一シンボルへ戻す |
| `addLayoutLegend` | `[layout, title, x, y, w, h, layers, linked_map, filter_by_map]` | 印刷レイアウトへ凡例アイテム追加。layout省略で新規作成 |
| `exportLegendImage` | `[path, layers, title, dpi]` | 凡例だけのPNG画像を出力。path省略で一時ファイル |

## レンダラの選び方

- **カテゴリ値で色分け** → `applyCategories`(フィールドの個別値を自動列挙。
  256値超はエラー→`applyGraduated`/`applyRules` へ)
- **数値を段階で分ける** → `applyGraduated`(classes=階級数2-20。
  equal=等間隔・quantile=分位数)
- **条件式・範囲・縮尺で分ける** → `applyRules`。
  rules は `[{"filter": "\"f\" < 10", "label": "小", "color": "#ff0000",
  "width": 0.3, "width_unit": "mm", "min_scale": 25000, "max_scale": 100000}]`
  の辞書リスト。`filter` は `min_scale`/`max_scale` 指定時に省略可
  (min_scale < 縮尺分母 <= max_scale の範囲で有効)

## レシピ

```text
1. 地目で色分け:
   qgis_bridge_call geo_legend applyCategories [null, "地目", "Spectral"]
   → 応答 items[] のlabel/colorをユーザーへ提示

2. 人口を5段階で色分け:
   qgis_bridge_call geo_legend applyGraduated [null, "人口", 5, "Viridis"]

3. 帳票用に凡例画像だけ欲しい:
   qgis_bridge_call geo_legend exportLegendImage [null, ["対象レイヤ名"], "凡例", 150]
   → 応答 path をユーザーへ伝える

4. 印刷レイアウトに凡例を置く:
   qgis_bridge_call geo_legend addLayoutLegend ["A4縦", "凡例", 195, 10]
   → layers=[...] で凡例対象を限定可。linked_map で地図連動
```

## 注意

- 凡例表示の確認は `legendSpec` の `legend_items`(レイヤパネルに出る文字列)を見る
- ドック表示側の操作(対象レイヤ選択・不透明度・名前付きスタイル・
  legend_*変数登録)は同じ geo_legend の従来メソッドを使う
- 作成した凡例を geo_webview `kasugaiExport` で WebGIS へ出す場合、
  Canvas 側の再現範囲は skills「webgis-convert」の凡例・ラベル再現性の節を参照
- 線の太さを縮尺に合わせたい場合は geo_driver `suggestScaleWidth`/
  `applyScaleWidth`(skills「scale-line-width」)と組み合わせる
