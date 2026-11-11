> **QGIS Live Harness のプラグイン** — [QGIS Live Harness](https://yamamoto-ryuzo.github.io/qgis_live_harness/) · [プラグイン一覧](https://yamamoto-ryuzo.github.io/qgis_live_harness/plugins.html) · [リポジトリ](https://github.com/yamamoto-ryuzo/qgis_live_harness)

# geo_userfunc

Library manager for user-defined Python code in QGIS
(expression functions, project hooks, and macros).
日本語版は [README_JP.md](README_JP.md)。

## What it does

`*.py` files placed in `<profile>/python/geo_userfunc/` are classified by
AST analysis and registered according to their type:

| Type | Detected by | Registered as |
|---|---|---|
| Function | `@qgsfunction` decorator | Expression engine function |
| Hook | `openProject`/`saveProject`/`closeProject` defs | Wired to project signals |
| Macro | `main(context)` def | Plugin menu + `bridge.run()` |

```python
# Macro entry convention — context carries iface / optional layer / plugins
def main(context):
    iface = context["iface"]
    geo_excel = context["plugins"].get("geo_excel")
    if geo_excel:
        geo_excel.bridge.run("list", None, True)
```

## Management

- **Plugins > geo_userfunc > User function library...** opens the manager
  dialog (also via the shared GeoSuite toolbar)
- Enable/disable, edit, reload, fetch-from-URL, upstream bulk update
- Enabled state is persisted in `manifest.json`

## AI / remote control

Available through `qgis_live_driver` `bridge_call`:

```json
{"command": "bridge_call", "plugin": "geo_userfunc",
 "method": "evalExpression", "args": ["zen2han('ＡＢＣ１２３')"]}
```

Main methods: `listFunctions` / `listMacros` / `run` / `evalExpression` /
`readFunction` / `saveFunction` / `deleteFunction` / `setEnabled` /
`reload` / `updateFromUpstream` / `status` / `openManager`

`saveFunction` → `reload` → `evalExpression` lets an AI author, register
and verify a new function in one loop.

## Registering from other plugins

```python
def register_user_functions(self, registry):
    registry.register_macro(
        "my_plugin.my_macro", title="My macro",
        callback=self._run, plugin_id="my_plugin")
```

geo_userfunc's `initGui` discovers this convention method (pull), or a
plugin may call `plugins['geo_userfunc'].registry` directly (push).
When geo_userfunc is absent, each plugin should fall back to its own menu.

## Upstream tracking

Bundled `functions/` seeds the library dir on first launch; afterwards the
library dir is authoritative. URLs in `sources.json` can be re-fetched via
the manager dialog or `updateFromUpstream`.

Initial bundle: `user_functions.py` from
[QGIS_user_function](https://github.com/yamamoto-ryuzo/QGIS_user_function).

## Disclaimer

This system was created and tested on a personal computer.  
We accept no liability for any damage arising from its use.

<p align="center">
  <a href="https://giphy.com/explore/free-gif" target="_blank">
    <img src="https://github.com/yamamoto-ryuzo/QGIS_portable_3x/raw/master/imgs/giphy.gif" width="500" title="avvio QGIS">
  </a>
</p>
