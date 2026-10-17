"""Réplica pydantic de los modelos peewee de SIRE para validar filas antes del insert.

``ProposalResource.get_proposal`` devuelve filas (dicts) con claves snake_case
directamente del CSV. Antes de hacer el upsert se validan con estos modelos para
que los errores de tipo/fecha salten en el programa y no en la BD. Las columnas
extra del CSV (que el modelo peewee no tiene, p. ej. ``apellidos_y_nombres_o_razon_social``
o ``clu2..clu39``) se descartan al volcar el modelo validado.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator


def _parse_sunat_date(value: Any) -> date | None:
    """Acepta fechas SUNAT ('04/07/2026') o ISO ('2026-07-01'); vacío -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no válida: {value!r}")


SunatDate = Annotated[date | None, BeforeValidator(_parse_sunat_date)]


class SirePurchsRow(BaseModel):
    """Fila de compras (RCE). Réplica de ``SirePurchs`` (sin ``period``).

    Todos los campos son opcionales a propósito: SUNAT puede dejar celdas vacías
    en cualquier columna (``normalize_rows`` las convierte a ``None``) y eso no
    debe romper la ingesta. Los tipos y fechas se siguen validando cuando traen valor.
    """

    empresa: str | None = None  # nombre de la empresa; lo inyecta el asset (no viene del CSV)
    ruc: int | None = None
    periodo: str | None = None
    car_sunat: str | None = None
    fecha_de_emision: SunatDate = None
    fecha_vcto_pago: SunatDate = None
    tipo_cp_doc: int | None = None
    serie_del_cdp: str | None = None
    ano: str | None = None
    nro_cp_o_doc_nro_inicial_rango: int | None = None
    nro_final_rango: int | None = None
    tipo_doc_identidad: str | None = None
    nro_doc_identidad: str | None = None
    apellidos_nombres_razon_social: str | None = None
    bi_gravado_dg: Decimal | None = None
    igv_ipm_dg: Decimal | None = None
    bi_gravado_dgng: Decimal | None = None
    igv_ipm_dgng: Decimal | None = None
    bi_gravado_dng: Decimal | None = None
    igv_ipm_dng: Decimal | None = None
    valor_adq_ng: Decimal | None = None
    isc: Decimal | None = None
    icbper: Decimal | None = None
    otros_trib_cargos: Decimal | None = None
    total_cp: Decimal | None = None
    moneda: str | None = None
    tipo_de_cambio: Decimal | None = None
    fecha_emision_doc_modificado: SunatDate = None
    tipo_cp_modificado: int | None = None
    serie_cp_modificado: str | None = None
    cod_dam_o_dsi: str | None = None
    nro_cp_modificado: int | None = None
    clasif_de_bss_y_sss: str | None = None
    id_proyecto_operadores: str | None = None
    porcpart: str | None = None
    imb: int | None = None
    car_orig_ind_e_o_i: str | None = None
    detraccion: str | None = None
    tipo_de_nota: int | None = None
    est_comp: str | None = None
    incal: int | None = None
    clu1: str | None = None


class SireSalesRow(BaseModel):
    """Fila de ventas (RVIE). Réplica de ``SireSales`` (sin ``period``).

    Igual que compras: todos los campos opcionales para tolerar celdas vacías
    de SUNAT sin romper la validación.
    """

    empresa: str | None = None  # nombre de la empresa; lo inyecta el asset (no viene del CSV)
    ruc: int | None = None
    periodo: str | None = None
    car_sunat: str | None = None
    fecha_de_emision: SunatDate = None
    fecha_vcto_pago: SunatDate = None
    tipo_cp_doc: int | None = None
    serie_del_cdp: str | None = None
    nro_cp_o_doc_nro_inicial_rango: int | None = None
    nro_final_rango: int | None = None
    tipo_doc_identidad: str | None = None
    nro_doc_identidad: str | None = None
    apellidos_nombres_razon_social: str | None = None
    valor_facturado_exportacion: Decimal | None = None
    bi_gravada: Decimal | None = None
    dscto_bi: Decimal | None = None
    igv_ipm: Decimal | None = None
    dscto_igv_ipm: Decimal | None = None
    mto_exonerado: Decimal | None = None
    mto_inafecto: Decimal | None = None
    isc: Decimal | None = None
    bi_grav_ivap: Decimal | None = None
    ivap: Decimal | None = None
    icbper: Decimal | None = None
    otros_tributos: Decimal | None = None
    total_cp: Decimal | None = None
    moneda: str | None = None
    tipo_cambio: Decimal | None = None
    fecha_emision_doc_modificado: SunatDate = None
    tipo_cp_modificado: int | None = None
    serie_cp_modificado: str | None = None
    nro_cp_modificado: int | None = None
    id_proyecto_operadores_atribucion: str | None = None
    tipo_de_nota: int | None = None
    est_comp: str | None = None
    valor_fob_embarcado: Decimal | None = None
    valor_op_gratuitas: Decimal | None = None
    tipo_operacion: int | None = None
    dam_cp: str | None = None
    clu: str | None = None
