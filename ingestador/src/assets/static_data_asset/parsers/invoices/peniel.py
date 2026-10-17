"""Facturas de **Peniel Aerospace** (``Invoice #: I#####``).

Mismo software que JetSet (**Quantum Control**), así que comparte ``_quantum.py``;
además de los campos comunes este proveedor imprime ``FF`` (freight forward),
``ATT``, ``Terms``, ``Ship Via`` + ``Ship Via Acc``, ``Prepared By``, ``# of
Boxes``, ``Weight`` e ``INCOTERM``.

⚠️ En la carpeta hay un PDF que **no** es una factura (``2.PENIEL I67568 PO
731.pdf``): es una factura **I67568** que en realidad vive en la carpeta de
órdenes de compra, así que se ignora (el parser solo acepta documentos con la
marca de Peniel y número ``I…``).

Los ítems traen el P/N y la descripción en la misma celda
(``1 GN3058-24 NYCO GN 3058-24 Synthetic``) y el alternativo en la línea
siguiente (``Alt: A-6741-12-7-2 GREASE``), que queda en ``extras``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _quantum

VENDOR = "PENIEL AEROSPACE"
VENDOR_NAME = "Peniel Aerospace"
MARCA = "PENIEL AEROSPACE"


def parse_pdf(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cabecera y detalles de **una** factura de Peniel."""
    return _quantum.parse(path, VENDOR, VENDOR_NAME, MARCA)


def parse(carpeta: Path) -> dict[str, list[dict[str, Any]]]:
    """Todas las facturas de Peniel de ``carpeta``."""
    return _quantum.parse_carpeta(carpeta, VENDOR, VENDOR_NAME, MARCA)
