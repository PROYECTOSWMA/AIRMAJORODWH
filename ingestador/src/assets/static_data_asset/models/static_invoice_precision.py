"""Modelos peewee de las facturas de **Precision Heliparts (PAG)** (2 tablas).

``static_invoice_precision_header`` y ``static_invoice_precision_details``. Las
llena ``parsers.invoices.precision``.
"""
from __future__ import annotations

from peewee import CharField

from assets.static_data_asset.models.base import BaseModel


class StaticInvoicePrecisionHeader(BaseModel):
    """Cabecera de una factura de Precision Heliparts."""

    class Meta:
        table_name = "static_invoice_precision_header"

    source_file = CharField(null=True)
    vendor = CharField(null=True)
    vendor_name = CharField(null=True)
    invoice_number = CharField(null=True)
    invoice_date = CharField(null=True)
    due_date = CharField(null=True)
    print_date = CharField(null=True)
    printed_by = CharField(null=True)
    print_no = CharField(null=True)
    page = CharField(null=True)
    account_number = CharField(null=True)
    so_number = CharField(null=True)
    our_ref = CharField(null=True)
    po_number = CharField(null=True)
    your_ref = CharField(null=True)
    ship_via = CharField(null=True)
    ship_via_acc = CharField(null=True)
    incoterms = CharField(null=True)
    shipped_date = CharField(null=True)
    terms = CharField(null=True)
    our_contact = CharField(null=True)
    email = CharField(null=True)
    domestic_awb = CharField(null=True)
    intl_awb = CharField(null=True)
    cod_amt = CharField(null=True)
    origin = CharField(null=True)
    contract = CharField(null=True)
    transport = CharField(null=True)
    invoiced_to = CharField(null=True)
    sold_to = CharField(null=True)
    shipped_to = CharField(null=True)
    remit_to = CharField(null=True)
    subtotal = CharField(null=True)
    total = CharField(null=True)
    balance = CharField(null=True)
    currency = CharField(null=True)


class StaticInvoicePrecisionDetails(BaseModel):
    """Línea de factura de Precision Heliparts."""

    class Meta:
        table_name = "static_invoice_precision_details"

    source_file = CharField(null=True)
    line = CharField(null=True)
    part_number = CharField(null=True)
    condition = CharField(null=True)
    qty_ordered = CharField(null=True)
    uom = CharField(null=True)
    qty_shipped = CharField(null=True)
    unit_price = CharField(null=True)
    amount = CharField(null=True)
    description = CharField(null=True)
    extras = CharField(null=True)
    raw_line = CharField(null=True)
