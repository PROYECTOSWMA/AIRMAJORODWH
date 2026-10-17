"""Modelos peewee de las facturas de **Textron Aviation** (2 tablas).

``static_invoice_textron_header`` y ``static_invoice_textron_details``. Las llena
``parsers.invoices.textron``.
"""
from __future__ import annotations

from peewee import CharField

from assets.static_data_asset.models.base import BaseModel


class StaticInvoiceTextronHeader(BaseModel):
    """Cabecera de una factura de Textron."""

    class Meta:
        table_name = "static_invoice_textron_header"

    source_file = CharField(null=True)
    vendor = CharField(null=True)
    vendor_name = CharField(null=True)
    invoice_number = CharField(null=True)
    invoice_date = CharField(null=True)
    due_date = CharField(null=True)
    terms = CharField(null=True)
    type = CharField(null=True)
    currency = CharField(null=True)
    sold_to_number = CharField(null=True)
    seller = CharField(null=True)
    po_number = CharField(null=True)
    sales_order = CharField(null=True)
    ship_date = CharField(null=True)
    terms_code = CharField(null=True)
    shipping_terms = CharField(null=True)
    bl_number = CharField(null=True)
    packing_sheet = CharField(null=True)
    weight_lbs = CharField(null=True)
    method = CharField(null=True)
    order_reason = CharField(null=True)
    forwarding_agent = CharField(null=True)
    sold_to_address = CharField(null=True)
    ship_to_address = CharField(null=True)
    subtotal = CharField(null=True)
    shipping_handling = CharField(null=True)
    tax = CharField(null=True)
    total = CharField(null=True)
    total_units = CharField(null=True)
    fed_tax_id = CharField(null=True)
    account = CharField(null=True)
    aba_route = CharField(null=True)
    bank = CharField(null=True)


class StaticInvoiceTextronDetails(BaseModel):
    """Línea de factura de Textron."""

    class Meta:
        table_name = "static_invoice_textron_details"

    source_file = CharField(null=True)
    line = CharField(null=True)
    part_number = CharField(null=True)
    description_1 = CharField(null=True)
    description_2 = CharField(null=True)
    list_price = CharField(null=True)
    discount = CharField(null=True)
    unit_price = CharField(null=True)
    uom = CharField(null=True)
    quantity = CharField(null=True)
    amount = CharField(null=True)
    extras = CharField(null=True)
    raw_line = CharField(null=True)
