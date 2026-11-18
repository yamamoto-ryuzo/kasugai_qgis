# スケール連動の標準線幅(geo_driver scale_style)

レイヤの用途(カテゴリ)と表示縮尺から標準的に適切な線幅を提案し、レンダラへ適用する手順。
use_when: ユーザーが線幅の決定・縮尺に応じた線の太さ・「適切な線幅」・スケール依存のスタイル設定を依頼したとき

## 基本方針

- 線幅は「カテゴリ(道路/河川/境界等)×縮尺帯」の**標準テーブル**から決める。値はプロファイルJSON管理で、勘で決めない
- 呼出しは `qgis_bridge_call` → `plugin_id="geo_driver"`。メソッドは5つ:
  `scaleStyleProfiles` / `scaleStyleTable` / `setScaleStyleProfile` / `suggestScaleWidth` / `applyScaleWidth`
- 「提案だけ見せて」= `suggestScaleWidth` or `applyScaleWidth(dry=True)`、実適用 = `applyScaleWidth`

## メソッド

| メソッド | args | 返すもの |
|---|---|---|
| `scaleStyleProfiles` | なし | プロファイル一覧 + active。同梱`default` + ユーザ`~/.qgis-live/scale_style/*.json` |
| `scaleStyleTable` | `[profile]` | アクティブ(または指定)プロファイルの縮尺帯・カテゴリ別base_mm/real_width_m全量 |
| `setScaleStyleProfile` | `[name]` | アクティブプロファイル切替(QSettings永続化) |
| `suggestScaleWidth` | `[layer_id, category, scale, profile]` | `{category, scale, band, base_mm, factor, width_mm, real_width_m, width_m_equiv}` |
| `applyScaleWidth` | `[layer_id, category, scale, mode, profile, dry]` | 適用結果。mode=`mm`/`meters`/`rules`、dry=trueで予定のみ |

省略時の既定: layer_id=アクティブレイヤ、category=レイヤ名/geomから推定、scale=現在のキャンバス縮尺。

## mode の選び方(applyScaleWidth)

| mode | 意味 | 向く用途 |
|---|---|---|
| `mm` | 現在縮尺に適した紙面幅(mm)を固定 | 単一縮尺で使うレイヤ・手早い体裁整え |
| `meters` | 実世界幅(m)で描く(RenderMetersInMapUnits)。ズームで見た目の太さが変わる | 実寸が意味を持つ幅(道路幅員・河川幅・バッファ表現) |
| `rules` | 縮尺帯ごとに幅が切替わるルールベースレンダラを生成 | 広い縮尺域で使うレイヤの標準仕上げ。凡例にも帯名+幅が出る |

`rules` は geo_legend ロード時はその `applyRules` へ委譲(結果に `delegated` が付く)、
未ロード/失敗時は geo_driver 内部実装へ自動フォールバックする。戻りの `rules[]` で
各帯の `min_scale`/`max_scale`/`width` を確認できる。

## 手順レシピ

```text
1. まず提案を見る:
   qgis_bridge_call geo_driver suggestScaleWidth [null, null, null]
   → category/band/width_mm/real_width_m を確認しユーザーへ提示

2. 適用(固定幅):
   qgis_bridge_call geo_driver applyScaleWidth [null, null, null, "mm"]

3. 縮尺帯ルールにする(推奨・標準仕上げ):
   qgis_bridge_call geo_driver applyScaleWidth [null, null, null, "rules"]
   → legendSpec(geo_legend)で凡例表示を確認
```

- カテゴリ推定が外れたら `category` を明示(例 `"road_major"`)。一覧は `scaleStyleTable` の `categories[].key`
- プロファイル切替が要望されたら `scaleStyleProfiles` → `setScaleStyleProfile`
- ユーザ独自の標準は `~/.qgis-live/scale_style/<name>.json` を作れば同梱`default`を同名で上書き/別名追加できる(qgis_pyevalでファイル出力)

## 同梱 default プロファイルの構造

```json
{
  "scale_bands": [{"max": 2500, "label": "1:2,500迄", "factor": 1.5}, ...],
  "categories": [
    {"key": "road_major", "match": {"name_re": "国道|主要|..."},
     "base_mm": 0.55, "real_width_m": 13.0}, ...
  ]
}
```

- `width_mm = base_mm × 帯factor`(0.05〜10に丸め)。基準帯(1:5,000〜25,000)はfactor=1.0
- `match` は `name_re`(レイヤ名正規表現)または `geom`(line/polygon)。先勝ち、`default` が兜底
- `real_width_m` が null のカテゴリ(境界/等高線等)は mode=`meters` を適用できない→`mm`か`rules`を選ぶ

## 注意

- 対象はライン/ポリゴンのベクターレイヤ(ストローク幅のあるもの)。ポイント/ラスタは `layer is not a line/polygon vector layer` で失敗する
- rules 適用後に単一シンボルへ戻す場合は geo_legend `applySingleSymbol`
- 縮尺帯ルールの active 範囲は `min_scale < 縮尺分母 <= max_scale`(QGIS仕様)
