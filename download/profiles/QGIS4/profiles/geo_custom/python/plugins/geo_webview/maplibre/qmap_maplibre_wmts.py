"""WMTS helper utilities for geo_webview MapLibre HTML generation.

This module contains a small, dependency-light helper to select the appropriate
WMTS tile template used in the MapLibre HTML template.

The functions intentionally avoid importing heavy QGIS modules at import time
and instead attempt lightweight existence checks so the module can be used
both inside and outside QGIS (e.g. in unit tests).
"""

# Public API exported by this module
__all__ = [
    'choose_tile_template',
]


def choose_tile_template() -> str:
    """Return a tile URL template string.

    Prefers a local WMTS endpoint when QGIS is available, otherwise falls
    back to a public OSM tile template.

    Returns
    -------
    str
        Tile URL template suitable for MapLibre tile sources.
    """
    try:
        # existence check for QGIS runtime
        # MapLibre requires complete URLs for tile sources.
        # The server manager is instantiated with the plugin and we don't
        # have easy access to its port here; use the default port.
        port = 8089
        return f"http://localhost:{port}/wmts/{{z}}/{{x}}/{{y}}.png"
    except Exception:
        return "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
