"""Modelos peewee de los datos extraídos del PDF de CEP (factura de combustible).

``from_email_cep_docs_headers`` es 1:1 con cada PDF adjunto de
``fe.corporacion.energetico@gmail.com`` (CONSORCIO ENERGÉTICO DEL PERÚ S.A.) y
``from_email_cep_docs_details`` es 1:N con su cabecera (un detalle por fila de la
tabla de combustible del PDF).

Reutilizan el mismo ``db`` (SQLite) y ``BaseModel`` de ``mail_asset``. El asset hace
upsert total del día: borra las cabeceras del día (y sus detalles) e inserta las
nuevas; por eso los detalles guardan ``partition_date`` denormalizada.
"""

from __future__ import annotations

from peewee import CharField, DecimalField, ForeignKeyField

from assets.mail_asset.model import BaseModel, EmailAttachments


class CepDocHeader(BaseModel):
    """Cabecera de la factura/nota de crédito de CEP (1:1 con un PDF adjunto)."""

    class Meta:
        table_name = "from_email_cep_docs_headers"

    attachment = ForeignKeyField(
        EmailAttachments,
        backref="cep_doc_headers",
        object_id_name="id_attachment",
        column_name="id_attachment",
    )  # PDF en ``email_attachments``; acceso crudo vía ``id_attachment``
    partition_date = CharField()  # partición diaria (misma que la del correo)
    filename = CharField()        # PDF adjunto del que se extrajo la cabecera

    # Réplica de la cabecera del PDF.
    factura = CharField(default="")          # F002-009674
    tipo_documento = CharField(default="")   # FACTURA / NOTA DE CREDITO
    fecha_emision = CharField(default="")    # 31/12/2025
    cliente = CharField(default="")          # AIR MAJORO S.A.
    ruc_cliente = CharField(default="")      # 20494626978
    direccion = CharField(default="")
    cod_del_cliente = CharField(default="")  # NZA/SPZA
    n_de_guia = CharField(default="")        # 2
    cod_vendedor = CharField(default="")     # 115984
    cond_pago = CharField(default="")        # Contado
    moneda = CharField(default="")           # DOLARES
    o_c = CharField(default="")              # 2009689
    transportista = CharField(default="")
    chofer = CharField(default="")
    son = CharField(default="")              # importe total en letras
    placa = CharField(default="")            # OB-1919
    op_gravadas = DecimalField(max_digits=14, decimal_places=2, null=True)
    op_exoneradas = DecimalField(max_digits=14, decimal_places=2, null=True)
    igv = DecimalField(max_digits=14, decimal_places=2, null=True)
    importe_total = DecimalField(max_digits=14, decimal_places=2, null=True)
    codigo_scop = CharField(default="")      # 12634330075


class CepDocDetail(BaseModel):
    """Detalle de combustible de la tabla del PDF (1 a N con la cabecera)."""

    class Meta:
        table_name = "from_email_cep_docs_details"

    header = ForeignKeyField(CepDocHeader, backref="details", on_delete="CASCADE")
    partition_date = CharField()

    codigo = CharField(default="")        # AV / TA1
    cant = DecimalField(max_digits=14, decimal_places=2, null=True)         # 20.00
    descripcion = CharField(default="")   # AV GAS 100LL / TURBO A-1
    u_m = CharField(default="")           # GLL
    valor_unit = DecimalField(max_digits=14, decimal_places=4, null=True)   # 11.2200
    precio_unit = DecimalField(max_digits=14, decimal_places=4, null=True)  # 13.2396
    valor_venta = DecimalField(max_digits=14, decimal_places=2, null=True)  # 224.40
