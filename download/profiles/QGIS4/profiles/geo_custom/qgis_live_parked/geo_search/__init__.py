"""QGIS plugin entrypoint.

Avoid heavy imports at module import time to prevent circular imports during
QGIS plugin loading.
"""


def classFactory(iface):
    # Ensure sys.stderr is usable: some embeders set it to None which breaks
    # third-party libraries (numpy writes to sys.stderr during import). If it
    # is None, restore from sys.__stderr__ or provide a small logging wrapper.
    try:
        import sys
        import logging
        if getattr(sys, 'stderr', None) is None or not hasattr(sys.stderr, 'write'):
            if getattr(sys, '__stderr__', None) is not None and hasattr(sys.__stderr__, 'write'):
                sys.stderr = sys.__stderr__
            else:
                class _StderrProxy:
                    def write(self, s):
                        try:
                            logging.getLogger('geo_search').error(str(s).rstrip())
                        except Exception:  # nosec B110  # 設計上の許容
                            pass

                    def flush(self):
                        return
                sys.stderr = _StderrProxy()
    except Exception:  # nosec B110  # 設計上の許容
        # best-effort: do not prevent plugin from loading
        pass

    # Import plugin implementation and return an instance
    from .plugin import plugin
    return plugin(iface)
