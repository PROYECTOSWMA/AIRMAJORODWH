
from __future__ import annotations

from peewee import CharField, TextField

from assets.static_data_asset.models.base import BaseModel


class StaticDwhCostCenters(BaseModel):
    """Fila del maestro de centros de costo.

    Las columnas son las del CSV `static/dwh_static_cost_centers.csv` (renombradas en
    2026-10: antes eran `cc`, `code` y `description`):

    - `codigo`: el código de centro de costo que trae la planilla y `moves`
      ('101', '200', 'OPE-NAZCA', ...).
    - `abreviatura`: la clave corta del maestro ('1919' = nº de aeronave, 'ADM-PCL', 'OMA').
    - `descripcion`: la etiqueta legible ('OB1919', 'GASTO ADMINISTRATIVO PUCALLPA').
    - `grupo`: la agrupación del maestro (COSTO_VENTAS, GASTO ADMINISTRATIVO, ...).
    - `unidad_negocio`: la unidad de negocio ya resuelta (NAZCA, SELVA, MEDEVAC, ...).
    """

    class Meta:
        table_name = "static_dwh_cost_centers"
        primary_key = False

    codigo = CharField(null=True)
    abreviatura = CharField(null=True)
    descripcion = TextField(null=True)
    grupo = CharField(null=True)
    unidad_negocio = TextField(null=True)
