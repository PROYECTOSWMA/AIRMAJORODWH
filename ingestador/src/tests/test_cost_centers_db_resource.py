"""Tests de ``AeronaveSireSqliteResource`` (ZIPs del proveedor por mes y append-only).

Cubre la base compartida por los 3 assets de cost centers: el select de los ZIP de
esos meses que **aún no tienen filas** (solo del RUC del proveedor, identificado por
el nombre que SUNAT le pone al ZIP, y solo ``tipo_documento = ZIP``) y el insert
append-only por ``(id_file, aeronave)``, que hace idempotente re-materializar el mes
(o el rango de dos meses del cron).
"""

from datetime import date

import pytest

from assets.from_sire_files_assets.cep_cost_centers_asset.models.model import (
    CepCostCenter,
)
from assets.from_sire_files_assets.cep_cost_centers_asset.resources.db_resource import (
    CepCostCenterSqliteResource,
)
from assets.from_sire_files_assets.petroperu_cost_centers_asset.models.model import (
    PetroperuCostCenter,
)
from assets.from_sire_files_assets.petroperu_cost_centers_asset.resources.db_resource import (
    PetroperuCostCenterSqliteResource,
)
from assets.sire_assets.sire_files_asset.models.model import SirePurchsFiles
from assets.sire_assets.sire_proposal_asset.models.model import SirePurchs, db

RUC_CEP = "20613566881"
RUC_OTRO = "20100128218"
RUC_PETROPERU = RUC_OTRO


@pytest.fixture(autouse=True)
def _clean_db():
    # db es un singleton global: cerrar la conexión entre tests para que cada
    # uno apunte al archivo SQLite temporal que le corresponde.
    yield
    if db.obj is not None:
        try:
            db.obj.close()
        except Exception:
            pass
        db.initialize(None)


def _resource(tmp_path):
    return CepCostCenterSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _compra(ruc=RUC_CEP, serie="E001", numero=1, period="202609"):
    return SirePurchs.create(
        period=period,
        empresa="Air Majoro",
        nro_doc_identidad=ruc,
        tipo_cp_doc=3,
        serie_del_cdp=serie,
        nro_cp_o_doc_nro_inicial_rango=numero,
        fecha_de_emision=date(2026, 9, 10),
    )


def _archivo(sire_purch, period="2026-09-10", tipo="ZIP", nom=None):
    """Fila de ``sire_purchs_files`` con un nombre como el que pone SUNAT.

    SUNAT nombra el archivo ``<RUC del emisor>-<tipo>-<serie>-<numero>.<ext>`` (el
    del ZIP de compras, con el RUC del proveedor), que es lo que usa el resource
    para saber de qué proveedor es el ZIP.
    """
    if nom is None:
        nom = f"{sire_purch.nro_doc_identidad}-01-E001-{sire_purch.id:07d}.zip"
    return SirePurchsFiles.create(
        sire_purch=sire_purch,
        period=period,
        empresa="Air Majoro",
        tipo_documento=tipo,
        nom_archivo=nom,
        val_archivo="QUJD",
    )


def _fila(id_file, aeronave="OB-1234", period="2026-09-10", filename="a.xml"):
    return {
        "id_file": id_file,
        "period": period,
        "filename": filename,
        "aeronave": aeronave,
    }


def test_select_zip_files_solo_del_proveedor_y_de_esos_meses(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    cep = _compra(serie="E001")
    otro = _compra(serie="E002", ruc=RUC_OTRO)
    dia10 = _archivo(cep, period="2026-09-10", nom=f"{RUC_CEP}-01-E001-0000010.zip")
    dia11 = _archivo(cep, period="2026-09-11", nom=f"{RUC_CEP}-01-E001-0000011.zip")
    # Otro mes y otro RUC: fuera.
    _archivo(cep, period="2026-08-31", nom=f"{RUC_CEP}-01-E001-0000012.zip")
    _archivo(otro, period="2026-09-10", nom=f"{RUC_OTRO}-01-E002-0000013.zip")

    zips = res.select_zip_files(["2026-09"])
    assert sorted(z["id"] for z in zips) == sorted([dia10.id, dia11.id])
    assert sorted(z["period"] for z in zips) == ["2026-09-10", "2026-09-11"]

    # El rango del cron (mes anterior + actual) sí lo trae.
    assert len(res.select_zip_files(["2026-08", "2026-09"])) == 3


def test_select_zip_files_usa_el_ruc_del_nombre_y_no_consulta_sire_purchs(tmp_path):
    """El proveedor sale del RUC del nombre del ZIP, no de un JOIN con ``sire_purchs``.

    El nombre del ZIP ya identifica al proveedor (lo pone SUNAT con el RUC del
    emisor) y la integridad referencial de ``sire_purchs_files`` garantiza que cada
    ZIP pertenece a una compra registrada: por eso el padre puede estar "cruzado"
    (no ocurre en datos reales, pero aquí demuestra que el resource no lo mira) y
    el ZIP sigue devolviéndose/descartándose solo por su nombre.
    """
    res = _resource(tmp_path)
    res._ensure_db()
    cep = _compra(serie="E001")
    otro = _compra(serie="E002", ruc=RUC_OTRO)
    con_ruc_cep = _archivo(otro, nom=f"{RUC_CEP}-01-E001-0000010.zip")  # padre de otro RUC
    _archivo(cep, nom=f"{RUC_OTRO}-01-E002-0000011.zip")  # padre CEP, nombre de otro

    zips = res.select_zip_files(["2026-09"])
    assert [z["id"] for z in zips] == [con_ruc_cep.id]


def test_select_zip_files_ignora_pdf(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    compra = _compra()
    zip_ok = _archivo(compra, tipo="ZIP", nom=f"{RUC_CEP}-01-E001-0000010.zip")
    _archivo(compra, tipo="PDF", nom=f"{RUC_CEP}-01-E001-0000010.pdf")

    zips = res.select_zip_files(["2026-09"])
    assert [z["id"] for z in zips] == [zip_ok.id]


def test_select_zip_files_salta_los_zip_ya_procesados(tmp_path):
    """Con filas ya insertadas, el ZIP no vuelve a aparecer (re-pasar el mes es barato)."""
    res = _resource(tmp_path)
    res._ensure_db()
    compra = _compra()
    zip_a = _archivo(compra, nom=f"{RUC_CEP}-01-E001-0000010.zip")
    zip_b = _archivo(compra, period="2026-09-11", nom=f"{RUC_CEP}-01-E001-0000011.zip")

    assert res.insert_aeronaves_new([_fila(zip_a.id)]) == 1
    zips = res.select_zip_files(["2026-09"])
    assert [z["id"] for z in zips] == [zip_b.id]


def test_insert_aeronaves_new_es_idempotente(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    compra = _compra()
    zip_file = _archivo(compra)
    filas = [_fila(zip_file.id, "OB-1234"), _fila(zip_file.id, "OB-5678", filename="b.xml")]

    assert res.insert_aeronaves_new(filas) == 2
    assert CepCostCenter.select().count() == 2

    # Re-materializar el mismo mes no duplica ni borra (append-only).
    assert res.insert_aeronaves_new(filas) == 0
    assert CepCostCenter.select().count() == 2
    assert {r.aeronave for r in CepCostCenter.select()} == {"OB-1234", "OB-5678"}


def test_insert_aeronaves_new_misma_aeronave_en_otro_zip(tmp_path):
    """La clave incluye el ZIP: la misma matrícula en otro ZIP es otra fila."""
    res = _resource(tmp_path)
    res._ensure_db()
    compra = _compra()
    zip_a = _archivo(compra, nom="a.zip")
    zip_b = _archivo(compra, period="2026-09-11", nom="b.zip")

    assert res.insert_aeronaves_new([_fila(zip_a.id), _fila(zip_b.id)]) == 2
    assert CepCostCenter.select().count() == 2


def test_insert_aeronaves_new_sin_filas(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.insert_aeronaves_new([]) == 0
    assert CepCostCenter.select().count() == 0


def test_select_zip_files_sin_meses(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.select_zip_files([]) == []


def test_ensure_db_migra_columnas_nuevas_con_alter_table(tmp_path):
    """Una tabla vieja (sin las columnas nuevas) se migra al abrir la BD.

    ``create_tables`` no añade columnas a tablas existentes, así que ``_ensure_db``
    las agrega por ``ALTER TABLE`` (aquí, el aeropuerto de petroperú).
    """
    from assets.from_sire_files_assets.petroperu_cost_centers_asset.resources.db_resource import (
        PetroperuCostCenterSqliteResource,
    )

    res = PetroperuCostCenterSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res._connect_db()
    db.connect(reuse_if_open=True)
    # Esquema "viejo": la tabla existe pero sin `aeropuerto`/`aeropuerto_completo`.
    db.execute_sql(
        'CREATE TABLE "from_sire_petroperu_cost_centers" ('
        '"id" INTEGER NOT NULL PRIMARY KEY, "period" VARCHAR(255) NOT NULL, '
        '"id_file" INTEGER NOT NULL, "filename" VARCHAR(255) NOT NULL, '
        '"aeronave" VARCHAR(255) NOT NULL)'
    )

    res._ensure_db()

    columnas = {c.name for c in db.get_columns("from_sire_petroperu_cost_centers")}
    assert {"aeropuerto", "aeropuerto_completo"} <= columnas


# --- backfill del aeropuerto (PETROPERU): filas viejas insertadas en NULL ---


def _resource_petroperu(tmp_path):
    return PetroperuCostCenterSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _fila_petroperu(
    id_file,
    aeronave="OB-1234",
    period="2026-09-10",
    filename="a.xml",
    aeropuerto="Pucallpa",
    completo="PRINCIPAL AEROPUERTO) YARINACOCHA CORONEL PORTILLO Ucayali",
):
    return {
        "id_file": id_file,
        "period": period,
        "filename": filename,
        "aeronave": aeronave,
        "aeropuerto": aeropuerto,
        "aeropuerto_completo": completo,
    }


def test_select_zip_files_reprocesa_zip_cuyo_aeropuerto_esta_nulo(tmp_path):
    """Un ZIP con filas pero sin aeropuerto vuelve a mirarse (una vez) para rellenarlo."""
    res = _resource_petroperu(tmp_path)
    res._ensure_db()
    compra = _compra(ruc=RUC_PETROPERU)
    zip_file = _archivo(compra)
    # Fila insertada antes de la columna: aeropuerto NULL -> reprocesable.
    res.insert_aeronaves_new(
        [{**_fila(zip_file.id), "aeropuerto": None, "aeropuerto_completo": None}]
    )
    assert [z["id"] for z in res.select_zip_files(["2026-09"])] == [zip_file.id]

    # Ya relleno el aeropuerto, el ZIP deja de aparecer.
    res.insert_aeronaves_new([_fila_petroperu(zip_file.id)])
    assert res.select_zip_files(["2026-09"]) == []


def test_insert_aeronaves_new_rellena_el_aeropuerto_de_una_fila_existente(tmp_path):
    """El aeropuerto de una fila ya insertada se rellena por UPDATE (no duplica)."""
    res = _resource_petroperu(tmp_path)
    res._ensure_db()
    compra = _compra(ruc=RUC_PETROPERU)
    zip_file = _archivo(compra)
    res.insert_aeronaves_new(
        [{**_fila(zip_file.id), "aeropuerto": None, "aeropuerto_completo": None}]
    )

    insertados = res.insert_aeronaves_new(
        [_fila_petroperu(zip_file.id, aeropuerto="Pucallpa")]
    )

    assert insertados == 0
    assert PetroperuCostCenter.select().count() == 1
    fila = PetroperuCostCenter.get()
    assert fila.aeropuerto == "Pucallpa"
    assert fila.aeropuerto_completo.startswith("PRINCIPAL AEROPUERTO")


def test_el_cep_no_reprocesa_sus_zip_porque_no_tiene_aeropuerto(tmp_path):
    """Sin la columna de aeropuerto, CEP mantiene el comportamiento append-only."""
    res = _resource(tmp_path)
    res._ensure_db()
    compra = _compra()
    zip_file = _archivo(compra)
    assert res.insert_aeronaves_new([_fila(zip_file.id)]) == 1

    assert res.select_zip_files(["2026-09"]) == []
