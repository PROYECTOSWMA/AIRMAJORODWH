"""Parsers de las facturas y órdenes de compra del exterior.

``static/INVOICE INTERNACIONALES`` tiene **una subcarpeta por proveedor** y una
carpeta ``ORDEN DE COMPRA`` (con una subcarpeta por proveedor). Cada parser:

* recibe un **PDF** (``parse_pdf(path) -> (header, details)``) y
* lee su **carpeta** completa (``parse(carpeta) -> {"header": [...], "details": [...]}``).

| Carpeta | Parser | Tablas |
| --- | --- | --- |
| ``FENIX AEROSPACE`` | ``fenix`` | ``static_invoice_fenix_header`` / ``_details`` |
| ``JETSET`` | ``jetset`` | ``static_invoice_jetset_header`` / ``_details`` |
| ``KAL AIRPARTS`` | ``kal`` | ``static_invoice_kal_header`` / ``_details`` |
| ``PENIEL`` | ``peniel`` | ``static_invoice_peniel_header`` / ``_details`` |
| ``PRECISION HELIPARTS`` | ``precision`` | ``static_invoice_precision_header`` / ``_details`` |
| ``TEXTRON`` | ``textron`` | ``static_invoice_textron_header`` / ``_details`` |
| ``ORDEN DE COMPRA`` | ``purchase_order`` | ``static_invoice_po_header`` / ``_details`` |

Las órdenes de compra usan **un solo parser** porque las seis subcarpetas
comparten el mismo formulario de Air Majoro.

Cómo se leen los PDF (ver ``_common``): texto por líneas en los formatos de
software ajeno y **rejilla por coordenadas** en los formularios y en las tablas
que se envuelven. Todo se guarda como texto, los montos como número plano y las
fechas en ISO; cada fila lleva ``source_file`` (y ``page`` en los detalles) para
poder revisar el PDF original.
"""
from __future__ import annotations

from . import fenix, jetset, kal, peniel, precision, purchase_order, textron

__all__ = [
    "fenix",
    "jetset",
    "kal",
    "peniel",
    "precision",
    "purchase_order",
    "textron",
]
