from __future__ import annotations

from peewee import CharField, DateField, DecimalField, IntegerField, Model


from assets._common.db import db


class BaseModel(Model):
    class Meta:
        database = db


class SireSales(BaseModel):
    class Meta:
        table_name = "sire_sales"

    period = CharField()
    empresa = CharField()

    # Literal copy from sire. Columnas nullable: SUNAT puede enviar celdas vacías.
    ruc = IntegerField(null=True)
    # razon_social = CharField() # For not ambiguity with apellidos_nombres_razon_social
    periodo = CharField(null=True)
    car_sunat = CharField(null=True)
    fecha_de_emision = DateField(null=True)
    fecha_vcto_pago = DateField(null=True)
    tipo_cp_doc = IntegerField(null=True)
    serie_del_cdp = CharField(null=True)
    nro_cp_o_doc_nro_inicial_rango = IntegerField(null=True)
    nro_final_rango = IntegerField(null=True)
    tipo_doc_identidad = CharField(null=True)
    nro_doc_identidad = CharField(null=True)
    apellidos_nombres_razon_social = CharField(null=True)
    valor_facturado_exportacion = DecimalField(max_digits=18, decimal_places=2, null=True)
    bi_gravada = DecimalField(max_digits=18, decimal_places=2, null=True)
    dscto_bi = DecimalField(max_digits=18, decimal_places=2, null=True)
    igv_ipm = DecimalField(max_digits=18, decimal_places=2, null=True)
    dscto_igv_ipm = DecimalField(max_digits=18, decimal_places=2, null=True)
    mto_exonerado = DecimalField(max_digits=18, decimal_places=2, null=True)
    mto_inafecto = DecimalField(max_digits=18, decimal_places=2, null=True)
    isc = DecimalField(max_digits=18, decimal_places=2, null=True)
    bi_grav_ivap = DecimalField(max_digits=18, decimal_places=2, null=True)
    ivap = DecimalField(max_digits=18, decimal_places=2, null=True)
    icbper = DecimalField(max_digits=18, decimal_places=2, null=True)
    otros_tributos = DecimalField(max_digits=18, decimal_places=2, null=True)
    total_cp = DecimalField(max_digits=18, decimal_places=2, null=True)
    moneda = CharField(null=True)
    tipo_cambio = DecimalField(max_digits=18, decimal_places=2, null=True)
    fecha_emision_doc_modificado = DateField(null=True)
    tipo_cp_modificado = IntegerField(null=True)
    serie_cp_modificado = CharField(null=True)
    nro_cp_modificado = IntegerField(null=True)
    id_proyecto_operadores_atribucion = CharField(null=True)
    tipo_de_nota = IntegerField(null=True)
    est_comp = CharField(null=True)
    valor_fob_embarcado = DecimalField(max_digits=18, decimal_places=2, null=True)
    valor_op_gratuitas = DecimalField(max_digits=18, decimal_places=2, null=True)
    tipo_operacion = IntegerField(null=True)
    dam_cp = CharField(null=True)
    clu = CharField(null=True)

    

class SirePurchs(BaseModel):
    class Meta:
        table_name = "sire_purchs"

    period = CharField()
    empresa = CharField()

    # Literal copy from sire. Columnas nullable: SUNAT puede enviar celdas vacías.
    ruc = IntegerField(null=True)
    # apellidos_y_nombres_o_razon_social = CharField() # For not ambiguity with apellidos_nombres_razon_social
    periodo = CharField(null=True)
    car_sunat = CharField(null=True)
    fecha_de_emision = DateField(null=True)
    fecha_vcto_pago = DateField(null=True)
    tipo_cp_doc = IntegerField(null=True)
    serie_del_cdp = CharField(null=True)
    ano = CharField(null=True)
    nro_cp_o_doc_nro_inicial_rango = IntegerField(null=True)
    nro_final_rango = IntegerField(null=True)
    tipo_doc_identidad = CharField(null=True)
    nro_doc_identidad = CharField(null=True)
    apellidos_nombres_razon_social = CharField(null=True)
    bi_gravado_dg = DecimalField(max_digits=18, decimal_places=2, null=True)
    igv_ipm_dg = DecimalField(max_digits=18, decimal_places=2, null=True)
    bi_gravado_dgng = DecimalField(max_digits=18, decimal_places=2, null=True)
    igv_ipm_dgng = DecimalField(max_digits=18, decimal_places=2, null=True)
    bi_gravado_dng = DecimalField(max_digits=18, decimal_places=2, null=True)
    igv_ipm_dng = DecimalField(max_digits=18, decimal_places=2, null=True)
    valor_adq_ng = DecimalField(max_digits=18, decimal_places=2, null=True)
    isc = DecimalField(max_digits=18, decimal_places=2, null=True)
    icbper = DecimalField(max_digits=18, decimal_places=2, null=True)
    otros_trib_cargos = DecimalField(max_digits=18, decimal_places=2, null=True)
    total_cp = DecimalField(max_digits=18, decimal_places=2, null=True)
    moneda = CharField(null=True)
    tipo_de_cambio = DecimalField(max_digits=18, decimal_places=2, null=True)
    fecha_emision_doc_modificado = DateField(null=True)
    tipo_cp_modificado = IntegerField(null=True)
    serie_cp_modificado = CharField(null=True)
    cod_dam_o_dsi = CharField(null=True)
    nro_cp_modificado = IntegerField(null=True)
    clasif_de_bss_y_sss = CharField(null=True)
    id_proyecto_operadores = CharField(null=True)
    porcpart = CharField(null=True)
    imb = IntegerField(null=True)
    car_orig_ind_e_o_i = CharField(null=True)
    detraccion = CharField(null=True)
    tipo_de_nota = IntegerField(null=True)
    est_comp = CharField(null=True)
    incal = IntegerField(null=True)
    clu1 = CharField(null=True)
    # clu2 = CharField(null=True)
    # clu3 = CharField(null=True)
    # clu4 = CharField(null=True)
    # clu5 = CharField(null=True)
    # clu6 = CharField(null=True)
    # clu7 = CharField(null=True)
    # clu8 = CharField(null=True)
    # clu9 = CharField(null=True)
    # clu10 = CharField(null=True)
    # clu11 = CharField(null=True)
    # clu12 = CharField(null=True)
    # clu13 = CharField(null=True)
    # clu14 = CharField(null=True)
    # clu15 = CharField(null=True)
    # clu16 = CharField(null=True)
    # clu17 = CharField(null=True)
    # clu18 = CharField(null=True)
    # clu19 = CharField(null=True)
    # clu20 = CharField(null=True)
    # clu21 = CharField(null=True)
    # clu22 = CharField(null=True)
    # clu23 = CharField(null=True)
    # clu24 = CharField(null=True)
    # clu25 = CharField(null=True)
    # clu26 = CharField(null=True)
    # clu27 = CharField(null=True)
    # clu28 = CharField(null=True)
    # clu29 = CharField(null=True)
    # clu30 = CharField(null=True)
    # clu31 = CharField(null=True)
    # clu32 = CharField(null=True)
    # clu33 = CharField(null=True)
    # clu34 = CharField(null=True)
    # clu35 = CharField(null=True)
    # clu36 = CharField(null=True)
    # clu37 = CharField(null=True)
    # clu38 = CharField(null=True)
    # clu39 = CharField(null=True)
