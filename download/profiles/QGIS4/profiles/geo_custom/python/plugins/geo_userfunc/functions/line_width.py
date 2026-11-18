from qgis.core import *


@qgsfunction(args='auto', group='ユーザー関数')
def line_width(base, minimum, ref_scale, scale, feature, parent):
    """縮尺連動の線幅(mm)を返す。

    基準縮尺 ref_scale では base mm。ズームアウト(縮尺分母の増大)で
    base*ref_scale/scale に反比例して細くなり minimum で打止め、
    ズームイン側は base で頭打ちする。
    clamp(minimum, base*ref_scale/scale, base) と等価。
    KASUGAI Canvas (web/shared/qml-style.js EXPR_FUNCS) の
    line_width 実装と同じ縮尺則。

    @expr: clamp({minimum}, {base}*{ref_scale}/{scale}, {base})
    """
    try:
        b = float(base)
        m = float(minimum)
        r = float(ref_scale)
        s = float(scale)
    except (TypeError, ValueError):
        return None
    if r <= 0 or s <= 0:
        return m
    w = b * r / s
    return min(max(w, m), b)
