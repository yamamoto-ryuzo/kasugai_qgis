# defusedxml
#
# Copyright (c) 2013 by Christian Heimes <christian@python.org>
# Licensed to PSF under a Contributor Agreement.
# See https://www.python.org/psf/license for licensing details.
"""Defuse XML bomb denial of service vulnerabilities

NOTE: This vendored copy is trimmed to the ElementTree facade only
(common.py + ElementTree.py). ``defuse_stdlib()`` and the other
stdlib facades are intentionally omitted: monkey-patching stdlib XML
inside QGIS breaks qgis.PyQt.uic.loadUiType (see qgis2web upstream
history) and is not needed here.
"""
from __future__ import print_function, absolute_import

from .common import (
    DefusedXmlException,
    DTDForbidden,
    EntitiesForbidden,
    ExternalReferenceForbidden,
    NotSupportedError,
)


__version__ = "0.7.1"

__all__ = [
    "DefusedXmlException",
    "DTDForbidden",
    "EntitiesForbidden",
    "ExternalReferenceForbidden",
    "NotSupportedError",
]
