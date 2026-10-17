"""Modelos peewee de las facturas de **Peniel Aerospace** (2 tablas).

Mismo diseño que JetSet (software Quantum Control), pero tablas propias:
``static_invoice_peniel_header`` y ``static_invoice_peniel_details``. Las llena
``parsers.invoices.peniel``.
"""
from __future__ import annotations

from peewee import CharField

from assets.static_data_asset.models.base import BaseModel


class StaticInvoicePenielHeader(BaseModel):
    """Cabecera de una factura de Peniel."""

    class Meta:
        table_name = "static_invoice_peniel_header"

    source_file = CharField(null=True)
    vendor = CharField(null=True)
    vendor_name = CharField(null=True)
    invoice_number = CharField(null=True)
    invoice_date = CharField(null=True)
    date_printed = CharField(null=True)
    printed_time = CharField(null=True)
    num_items = CharField(null=True)
    page = CharField(null=True)
    po_number = CharField(null=True)
    order_date = CharField(null=True)
    ship_date = CharField(null=True)
    terms = CharField(null=True)
    weight = CharField(null=True)
    ship_via = CharField(null=True)
    num_boxes = CharField(null=True)
    ship_via_acc = CharField(null=True)
    sales_order = CharField(null=True)
    buyer = CharField(null=True)
    cust_vat = CharField(null=True)
    ship_log = CharField(null=True)
    ship_order = CharField(null=True)
    shipment = CharField(null=True)
    customer_number = CharField(null=True)
    awb = CharField(null=True)
    vat_number = CharField(null=True)
    prepared_by = CharField(null=True)
    incoterm = CharField(null=True)
    freight_forward = CharField(null=True)
    att = CharField(null=True)
    to_address = CharField(null=True)
    ship_to_address = CharField(null=True)
    subtotal = CharField(null=True)
    tax_total = CharField(null=True)
    misc_charge = CharField(null=True)
    freight = CharField(null=True)
    disc_total = CharField(null=True)
    total = CharField(null=True)
    payment_amt = CharField(null=True)
    payment_type = CharField(null=True)
    payment_owed = CharField(null=True)
    currency = CharField(null=True)


class StaticInvoicePenielDetails(BaseModel):
    """Línea de factura de Peniel."""

    class Meta:
        table_name = "static_invoice_peniel_details"

    source_file = CharField(null=True)
    item = CharField(null=True)
    part_number = CharField(null=True)
    alt_part = CharField(null=True)
    description = CharField(null=True)
    shipped = CharField(null=True)
    backord_cd = CharField(null=True)
    unit_price = CharField(null=True)
    uom = CharField(null=True)
    amount = CharField(null=True)
    extras = CharField(null=True)
    raw_line = CharField(null=True)
