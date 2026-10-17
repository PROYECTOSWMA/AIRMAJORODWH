"""Contrato del maestro de cuentas del Estado de Resultados (EERR).

El reporte **añade** filas que no existen en las tablas de movimientos: los subtotales
`tipo = 'MEDIDA'` (UTILIDAD BRUTA, RESULTADO OPERATIVO) y las cuentas del maestro con
importe 0 por (mes x centro de costo).

Las filas MEDIDA se consiguen **sin `UNION`**: se sacan del propio maestro de cuentas,
donde viven como **pseudo-cuentas** (una por cada grupo ``tipo = 'MEDIDA'`` de
``dwh_static_master_account_groups``). Ese es el contrato que fijan estos tests: si
mañana se añade un grupo MEDIDA y se olvida su pseudo-cuenta, el subtotal del reporte
desaparece (y habría que volver a la `UNION`). Lo consume la página de EERR del
dashboard (``dashboardaim/pages/estado-resultados.md``: ``where tipo = 'MEDIDA'``).

El maestro se publica al DWH con `dbt run` (modelo `static_master_accounts`) y el
asset `publish_dwh`, así que un cambio en el CSV exige re-ejecutar el pipeline.
"""
from pathlib import Path

from assets.static_data_asset.parsers.csv_static import parse_csv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CUENTAS_CSV = _REPO_ROOT / "static" / "dwh_static_master_accounts.csv"
_GRUPOS_CSV = _REPO_ROOT / "static" / "dwh_static_master_account_groups.csv"


def _grupos_medida() -> list[dict]:
    return [g for g in parse_csv(_GRUPOS_CSV) if g["tipo"] == "MEDIDA"]


def _cuentas() -> dict[str, dict]:
    return {c["codigo_pcge"]: c for c in parse_csv(_CUENTAS_CSV)}


def test_hay_dos_grupos_medida_con_orden():
    grupos = _grupos_medida()
    assert {g["grupo"] for g in grupos} == {"UTILIDAD BRUTA", "RESULTADO OPERATIVO"}
    assert all(g["orden"] for g in grupos)


def test_cada_grupo_medida_tiene_su_pseudo_cuenta_en_el_maestro():
    cuentas = _cuentas()
    for grupo in _grupos_medida():
        # El código de la pseudo-cuenta es el NOMBRE del grupo MEDIDA.
        assert grupo["grupo"] in cuentas, grupo["grupo"]
        pseudo = cuentas[grupo["grupo"]]
        assert pseudo["grupo"] == grupo["grupo"]
        # `descripcion` de la fila MEDIDA = `cuenta` de la pseudo-cuenta.
        assert pseudo["cuenta"] == grupo["grupo"]
        assert pseudo["cuenta_pcge"] is None
        assert pseudo["comentario"] and "MEDIDA" in pseudo["comentario"]


def test_las_pseudo_cuentas_no_chocan_con_codigos_del_maestro():
    codigos = [c["codigo_pcge"] for c in parse_csv(_CUENTAS_CSV)]
    assert len(codigos) == len(set(codigos))
    for grupo in _grupos_medida():
        # Los códigos PCGE son numéricos: un nombre no puede colisionar con ellos.
        assert not any(caracter.isdigit() for caracter in grupo["grupo"])
