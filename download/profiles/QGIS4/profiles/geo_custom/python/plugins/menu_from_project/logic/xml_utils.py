from typing import Optional

# PyQGIS
from qgis.PyQt.QtXml import QDomNode


def getFirstChildByAttrValue(elt, tagName, key, value):
    if isinstance(elt, QDomNode):
        elt = elt.toElement()
    nodes = elt.elementsByTagName(tagName)
    for node in (nodes.at(i) for i in range(nodes.size())):
        if (
            node.toElement().hasAttribute(key)
            and node.toElement().attribute(key) == value
        ):
            # layer founds
            return node

    return None


def getFirstChildByTagNameValue(elt, tagName, key, value) -> Optional[QDomNode]:
    nodes = elt.elementsByTagName(tagName)
    for node in (nodes.at(i) for i in range(nodes.size())):
        nd = node.namedItem(key)
        if nd and value == nd.firstChild().toText().data():
            # layer founds
            return node

    return None
