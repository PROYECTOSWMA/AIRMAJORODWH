"""Contrato de la estandarización de ``serv_desc`` en las compras de combustible.

En la cuenta de **combustibles** (``603201``: PETROPERÚ, CEP, ÍCARO y TERPEL) el
negocio pidió **estandarizar la descripción del servicio** con una única regla,
basada en la **descripción** original:

* si la descripción trae ``100`` -> ``100LL`` (AVGAS);
* cualquier otra descripción -> ``TURBO JET A1``;
* si el **centro de costo NO es una aeronave** del maestro ``static_airplanes``
  (o no hay descripción) -> ``NO IDENTIFICADO``.

La regla es la **única** forma de asignar el tipo de combustible: **no** se deriva
del centro de costo ni de la aeronave. Vive en ``moves`` (no en ``purchs_std``)
porque necesita el centro de costo FINAL, con el override del proveedor ya
aplicado. Como no hay framework de tests de dbt en pytest, aquí se fija el
CONTRATO del pipeline (mismo estilo que ``test_intl_purchs_std_model.py``).
"""
from pathlib import Path

from assets.static_data_asset.parsers.csv_static import parse_csv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DBT = _REPO_ROOT / "src" / "dbt" / "models"
_AIRPLANES_CSV = _REPO_ROOT / "static" / "dwh_static_airplanes.csv"

# Centros de costo que llegan en las compras de combustible y NO son aeronaves
# del maestro: con la regla actual salen como 'NO IDENTIFICADO'.
_CC_SIN_AERONAVE = ("2000", "2190", "2056", "2222")
# Aeronaves reales del maestro (el otro lado de la regla).
_CC_AERONAVE = ("1919", "1921", "2180", "2209")


def _leer(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_moves_estandariza_serv_desc_por_descripcion():
    sql = _leer(_DBT / "moves.sql")

    # La regla vive en `moves`, sobre el CTE que ya tiene el centro de costo FINAL
    # (con el override del proveedor aplicado) y reemplaza la columna `serv_desc`.
    assert "FROM mv_con_cc mv" in sql
    assert "AS serv_desc" in sql
    # Solo la cuenta de combustibles: el resto pasa intacta.
    assert "WHEN mv.account <> '603201' THEN mv.serv_desc" in sql
    # Descripción con '100' -> 100LL; cualquier otra -> TURBO JET A1.
    assert "instr(mv.serv_desc, '100') > 0 THEN '100LL'" in sql
    assert "ELSE 'TURBO JET A1'" in sql
    # Centro de costo que no es aeronave del maestro -> NO IDENTIFICADO.
    assert "THEN 'NO IDENTIFICADO'" in sql
    assert "{{ ref('static_airplanes') }}" in sql
    assert "a.registration = mv.cost_center" in sql
    # Los anticipos de TERPEL conservan su texto: la vista `dwh.vista_reporte_gerencial`
    # los excluye por él (si se reescribiera, volverían al reporte gerencial).
    assert "ILIKE '%PAGO ADELANTADO%'" in sql
    assert "ILIKE '%PAGOS ADELANTADOS%'" in sql


def test_la_asignacion_por_aeronave_ya_no_existe():
    sql = _leer(_DBT / "purchs" / "purchs_std.sql")

    # `extract_cost_center(cc.aeronave)` queda SOLO para el centro de costo: ya no
    # decide el `serv_desc` (se borró la lista de aeronaves AVGAS).
    assert sql.count("extract_cost_center('cc.aeronave')") == 1
    assert "IN ('1919','1921','2180','1929') THEN '100LL'" not in sql
    assert "'TURBO A1-JET'" not in sql
    assert "'100LL'" not in sql


def test_cost_centers_solo_tiene_aeronave_para_combustibles():
    # `cost_centers.aeronave` sale de las tablas de los 4 proveedores de combustible:
    # es de donde salen los CC de la página, así que la regla de `serv_desc` (que se
    # apoya en que el CC sea una aeronave) solo puede afectar a esa cuenta.
    sql = _leer(_DBT / "purchs" / "cost_centers.sql")
    for tabla in (
        "from_sire_cep_cost_centers",
        "from_sire_icaro_cost_centers",
        "from_sire_petroperu_cost_centers",
    ):
        assert tabla in sql
    assert "from_email_terpel_tickets_tickets" in sql


def test_centros_de_costo_no_identificados_no_estan_en_el_maestro():
    aviones = {a["registration"] for a in parse_csv(_AIRPLANES_CSV)}

    # Los CC que el negocio manda a 'NO IDENTIFICADO' no son aeronaves del maestro...
    for cc in _CC_SIN_AERONAVE:
        assert cc not in aviones
    # ...y los que sí lo son quedan sujetos a la regla de la descripción.
    for cc in _CC_AERONAVE:
        assert cc in aviones

