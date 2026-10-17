"""Modelos peewee de las facturas de **Fenix Aerospace** (2 tablas).

* ``static_invoice_fenix_header``: una fila por factura, con **todos** los campos
  de la cabecera del PDF.
* ``static_invoice_fenix_details``: una fila por línea de factura, con los metadatos
  del ítem (``extras``: HTS, ECCN, ALT FOR…) y el renglón original (``raw_line``).

Todo es texto (los importes van como número plano y las fechas en ISO). Las llena
``parsers.invoices.fenix`` y el cruce con las órdenes de compra se hará en dbt.
"""
from __future__ import annotations

from peewee import CharField, IntegerField

from assets.static_data_asset.models.base import BaseModel


class StaticInvoiceFenixHeader(BaseModel):
    """Cabecera de una factura de Fenix."""

    class Meta:
        table_name = "static_invoice_fenix_header"

    source_file = CharField(null=True)
    vendor = CharField(null=True)
    vendor_name = CharField(null=True)
    invoice_number = CharField(null=True)
    invoice_date = CharField(null=True)
    invoice_terms = CharField(null=True)
    so_number = CharField(null=True)
    rls_number = CharField(null=True)
    po_number = CharField(null=True)
    vat_tax_id = CharField(null=True)
    website = CharField(null=True)
    requisitioner = CharField(null=True)
    requisitioner_phone = CharField(null=True)
    awb = CharField(null=True)
    ship_date = CharField(null=True)
    num_pieces = CharField(null=True)
    total_weight = CharField(null=True)
    incoterms = CharField(null=True)
    port_dest = CharField(null=True)
    shipped_via = CharField(null=True)
    shipped_via_acct = CharField(null=True)
    billing_contact = CharField(null=True)
    billing_phone = CharField(null=True)
    billing_email = CharField(null=True)
    contact = CharField(null=True)
    contact_phone = CharField(null=True)
    bill_to = CharField(null=True)
    ship_to = CharField(null=True)
    subtotal = CharField(null=True)
    tax = CharField(null=True)
    freight = CharField(null=True)
    total = CharField(null=True)
    currency = CharField(null=True)
    comments = CharField(null=True)


class StaticInvoiceFenixDetails(BaseModel):
    """Línea de factura de Fenix."""

    class Meta:
        table_name = "static_invoice_fenix_details"

    source_file = CharField(null=True)
    page = IntegerField(null=True)
    row_number = IntegerField(null=True)
    line_number = CharField(null=True)
    part_number = CharField(null=True)
    serial_number = CharField(null=True)
    description = CharField(null=True)
    condition = CharField(null=True)
    qty = CharField(null=True)
    uom = CharField(null=True)
    unit_price = CharField(null=True)
    amount = CharField(null=True)
    extras = CharField(null=True)
    raw_line = CharField(null=True)
