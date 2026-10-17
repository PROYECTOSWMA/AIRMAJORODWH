"""Modelos peewee de las **órdenes de compra** de Air Majoro (2 tablas).

* ``static_invoice_po_header``: una fila por orden (las seis subcarpetas de
  proveedor comparten el mismo formulario).
* ``static_invoice_po_details``: una fila por ítem, **respetando las columnas del
  PDF** (``cc`` y ``aeronave`` pueden llevar la aeronave indistintamente; ``raw_line``
  guarda la fila tal cual).

Las llena ``parsers.invoices.purchase_order``.
"""
from __future__ import annotations

from peewee import CharField, IntegerField

from assets.static_data_asset.models.base import BaseModel


class StaticInvoicePoHeader(BaseModel):
    """Cabecera de una orden de compra."""

    class Meta:
        table_name = "static_invoice_po_header"

    source_file = CharField(null=True)
    po_type = CharField(null=True)
    po_number = CharField(null=True)
    po_date = CharField(null=True)
    po_date_raw = CharField(null=True)
    billing_company = CharField(null=True)
    ruc = CharField(null=True)
    billing_address = CharField(null=True)
    billing_contact = CharField(null=True)
    supplier = CharField(null=True)
    supplier_contact = CharField(null=True)
    supplier_email = CharField(null=True)
    supplier_phone = CharField(null=True)
    supplier_address = CharField(null=True)
    order_type = CharField(null=True)
    payment_terms = CharField(null=True)
    delivery_terms = CharField(null=True)
    category = CharField(null=True)
    lead_time = CharField(null=True)
    quote = CharField(null=True)
    shipping_name = CharField(null=True)
    shipping_contact = CharField(null=True)
    shipping_email = CharField(null=True)
    shipping_phone = CharField(null=True)
    shipping_address = CharField(null=True)
    buyer = CharField(null=True)
    pages = CharField(null=True)
    currency = CharField(null=True)
    subtotal = CharField(null=True)
    shipping_handling = CharField(null=True)
    tax = CharField(null=True)
    total = CharField(null=True)
    remarks = CharField(null=True)
    approved_by = CharField(null=True)


class StaticInvoicePoDetails(BaseModel):
    """Ítem de una orden de compra (columnas tal como están en el PDF)."""

    class Meta:
        table_name = "static_invoice_po_details"

    source_file = CharField(null=True)
    page = IntegerField(null=True)
    item = CharField(null=True)
    catalogue_type = CharField(null=True)
    part_number = CharField(null=True)
    i_w = CharField(null=True)
    condition = CharField(null=True)
    description = CharField(null=True)
    cc = CharField(null=True)
    serial = CharField(null=True)
    qty = CharField(null=True)
    um = CharField(null=True)
    unit_cost = CharField(null=True)
    total_cost = CharField(null=True)
    aeronave = CharField(null=True)
    maintenance_note = CharField(null=True)
    raw_line = CharField(null=True)
