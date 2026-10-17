"""Modelos peewee de las facturas de **Kal-Airparts** (2 tablas).

``static_invoice_kal_header`` y ``static_invoice_kal_details``. Las llena
``parsers.invoices.kal``.
"""
from __future__ import annotations

from peewee import CharField

from assets.static_data_asset.models.base import BaseModel


class StaticInvoiceKalHeader(BaseModel):
    """Cabecera de una factura de Kal."""

    class Meta:
        table_name = "static_invoice_kal_header"

    source_file = CharField(null=True)
    vendor = CharField(null=True)
    vendor_name = CharField(null=True)
    invoice_number = CharField(null=True)
    invoice_date = CharField(null=True)
    po_number = CharField(null=True)
    customer_number = CharField(null=True)
    sales_person = CharField(null=True)
    ship_via = CharField(null=True)
    terms = CharField(null=True)
    sales_order = CharField(null=True)
    order_date = CharField(null=True)
    ship_date = CharField(null=True)
    sold_to = CharField(null=True)
    ship_to = CharField(null=True)
    total_due = CharField(null=True)
    currency = CharField(null=True)
    approved_by = CharField(null=True)


class StaticInvoiceKalDetails(BaseModel):
    """Línea de factura de Kal."""

    class Meta:
        table_name = "static_invoice_kal_details"

    source_file = CharField(null=True)
    item = CharField(null=True)
    order_qty = CharField(null=True)
    ship_qty = CharField(null=True)
    condition = CharField(null=True)
    part_number = CharField(null=True)
    description = CharField(null=True)
    unit_price = CharField(null=True)
    amount = CharField(null=True)
    extras = CharField(null=True)
    raw_line = CharField(null=True)
