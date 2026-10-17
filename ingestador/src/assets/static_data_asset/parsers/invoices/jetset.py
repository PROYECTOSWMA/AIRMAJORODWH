"""Facturas de **JetSet Airmotive Co., Inc.** (``Invoice #: NNNNN``).

Es el software **Quantum Control**, así que el trabajo lo hace ``_quantum.py``;
aquí solo se fija el proveedor. Las POs de este proveedor usan ese mismo número
(``Cust. PO#``/``Cust. PO#``), que es la clave del cruce posterior.

Los PDF son de una sola página y la tabla de ítems se envuelve: la cantidad
``Shipped``/``BackOrd`` y el código ``CD`` pueden caer en otro renglón, y los
datos del ítem (``Serial #``, ``Core Charge``, ``CORE CHARGE``) van debajo en
``extras``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _quantum

VENDOR = "JETSET AIRMOTIVE"
VENDOR_NAME = "JetSet Airmotive Co., Inc."
MARCA = "JETSET AIRMOTIVE"


def parse_pdf(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cabecera y detalles de **una** factura de JetSet."""
    return _quantum.parse(path, VENDOR, VENDOR_NAME, MARCA)


def parse(carpeta: Path) -> dict[str, list[dict[str, Any]]]:
    """Todas las facturas de JetSet de ``carpeta``."""
    return _quantum.parse_carpeta(carpeta, VENDOR, VENDOR_NAME, MARCA)
