"""Tests del asset corpac_files_daily (parseo, descarga, insert y fail-fast).

El asset se invoca a través de su función de cómputo subyacente (la que envuelve
``@asset``) con recursos stub para no tocar la red ni la BD. Si un correo falla el
asset lanza ``CorpacProcessingError``: la partición cae y nunca se llega al insert.
El último test usa el ``CorpacSqliteResource`` real (SQLite temporal) para cubrir el
**append-only** de punta a punta: en una segunda corrida los correos que ya tienen
archivos se saltan y ni se vuelven a descargar.

Con ``BackfillPolicy.multi_run(max_partitions_per_run=30)``, igual que ``ingest_emails``,
un run de backfill invoca la función **una vez** con los N días del trozo
(``context.partition_keys``): la lógica de un día vive en ``procesar_dia`` y aquí se prueba
también que el asset la recorre para **todos** los días del run y que **no** devuelve
``Output`` con valor (en un run de rango el IO manager por defecto reventaría el run).
"""

import zipfile
from io import BytesIO

import pytest

from dagster import MaterializeResult

from assets.from_email_assets.corpac_assets.corpac_files_asset.corpac_files_asset import (
    CorpacProcessingError,
    corpac_files_daily,
    procesar_dia,
)
from assets.from_email_assets.corpac_assets.corpac_files_asset.models.model import CorpacFile
from assets.from_email_assets.corpac_assets.corpac_files_asset.resources.api_resource import CorpacZipError
from assets.from_email_assets.corpac_assets.corpac_files_asset.resources.db_resource import (
    CORPAC_SENDER,
    CorpacSqliteResource,
)
from assets.mail_asset.model import Email, db

# ``corpac_files_daily`` es un AssetsDefinition; ``op.compute_fn.decorated_fn``
# es la función original (context, corpac, corpac_db).
_ASSET_FN = corpac_files_daily.op.compute_fn.decorated_fn


@pytest.fixture(autouse=True)
def _clean_db():
    # ``db`` es un singleton global: al test que usa el resource real (no el stub)
    # hay que cerrarle la conexión al terminar para que el siguiente test apunte a
    # su propio archivo SQLite temporal.
    yield
    if db.obj is not None:
        try:
            db.obj.close()
        except Exception:
            pass
        db.initialize(None)

URL = (
    "https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones"
    "?accessCode=bWZ1dzFsczErY2s90&action=1"
)
URL_2 = (
    "https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones"
    "?accessCode=OTROCODIGO&action=1"
)

# ZIP con magic bytes PK inválido (truncado): pasa el chequeo de descarga pero
# ``extract_zip_files`` falla al desempaquetar.
ZIP_INVALIDO = bytes([0x50, 0x4B, 0x03, 0x04]) + b"contenido-truncado"


def _body_con_enlace(url):
    # HTML minimalista con el enlace CORPAC.
    return '<a href="' + url + '">' + url + "</a>"


def _zip_en_memoria(nombres_contenidos):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nombre, contenido in nombres_contenidos:
            zf.writestr(nombre, contenido)
    buf.seek(0)
    return buf.read()


class _Log:
    def info(self, *args, **kwargs):
        pass


class _Context:
    """Contexto mínimo: un día, o el trozo de rango de un run ``multi_run``."""

    def __init__(self, partition_key="2026-08-11", partition_keys=None):
        self.partition_key = partition_key
        if partition_keys is not None:
            self.partition_keys = partition_keys
        self.log = _Log()


class _Corpac:
    def __init__(self, zips):
        self.zips = zips  # url -> bytes
        self.calls = []

    def download_zip(self, url):
        self.calls.append(url)
        if url not in self.zips:
            raise CorpacZipError("no disponible")
        return self.zips[url]


class _Db:
    def __init__(self, emails=(), por_dia=None):
        self.emails = list(emails)
        # Correos por día (para el trozo de un backfill); si no hay entrada, ``emails``.
        self.por_dia = por_dia or {}
        self.upserts = []

    def select_corpac_emails(self, partition_date):
        return self.por_dia.get(partition_date, self.emails)

    def upsert_files(self, partition_date, rows):
        self.upserts.append((partition_date, list(rows)))
        return len(rows)


def _email(eid, body):
    return {
        "id": eid,
        "sender": "servicio.facturacion@pegasus.com.pe",
        "body": body,
    }


def test_asset_descarga_zip_e_inserta_hijos_con_id_email():
    zip_bytes = _zip_en_memoria(
        [
            ("FACTURA-1.pdf", b"%PDF-1.4"),
            ("FACTURA-1.xml", b"<Invoice/>"),
            ("OC-1.pdf", b"%PDF-1.4 oc"),
        ]
    )
    corpac = _Corpac({URL: zip_bytes})
    db = _Db([_email("e1", _body_con_enlace(URL))])

    out = _ASSET_FN(_Context(), corpac, db)

    assert corpac.calls == [URL]
    assert len(db.upserts) == 1
    particion, filas = db.upserts[0]
    assert particion == "2026-08-11"
    assert [f["filename"] for f in filas] == [
        "FACTURA-1.pdf",
        "FACTURA-1.xml",
        "OC-1.pdf",
    ]
    assert all(f["id_email"] == "e1" for f in filas)
    assert all(f["data"] for f in filas)
    assert out.metadata["files_inserted"] == 3
    assert out.metadata["emails_procesados"] == 1


def test_asset_sin_enlace_cae_la_particion():
    corpac = _Corpac({})
    db = _Db([_email("e1", "cuerpo sin enlace CORPAC")])

    with pytest.raises(CorpacProcessingError, match="sin enlace CORPAC"):
        _ASSET_FN(_Context(), corpac, db)

    assert corpac.calls == []
    assert db.upserts == []  # nunca llega al upsert


def test_asset_descarga_fallida_cae_la_particion():
    zip_ok = _zip_en_memoria([("OK.pdf", b"%PDF")])
    corpac = _Corpac({URL: zip_ok})
    db = _Db(
        [
            _email("e1", _body_con_enlace(URL)),
            _email("e2", _body_con_enlace(URL_2)),
        ]
    )

    with pytest.raises(CorpacProcessingError, match="e2"):
        _ASSET_FN(_Context(), corpac, db)

    assert corpac.calls == [URL, URL_2]
    assert db.upserts == []  # nada se insertó


def test_asset_zip_invalido_cae_la_particion():
    corpac = _Corpac({URL: ZIP_INVALIDO})
    db = _Db([_email("e1", _body_con_enlace(URL))])

    with pytest.raises(CorpacProcessingError, match="zip inválido"):
        _ASSET_FN(_Context(), corpac, db)

    assert db.upserts == []


def test_asset_sin_correos_del_dia():
    corpac = _Corpac({})
    db = _Db([])

    out = _ASSET_FN(_Context(), corpac, db)

    assert corpac.calls == []
    assert db.upserts == [("2026-08-11", [])]
    assert out.metadata["files_inserted"] == 0
    assert out.metadata["emails_procesados"] == 0
    assert out.metadata["days_processed"] == 1


# --- Un día por llamada (``procesar_dia``) y el trozo de un ``multi_run`` -----------------


def test_procesar_dia_devuelve_el_resumen_del_dia():
    zip_bytes = _zip_en_memoria([("OK.pdf", b"%PDF")])
    corpac = _Corpac({URL: zip_bytes})
    db = _Db([_email("e1", _body_con_enlace(URL))])

    resumen = procesar_dia(_Context(), corpac, db, "2026-08-11")

    assert resumen["period"] == "2026-08-11"
    assert resumen["files_inserted"] == 1
    assert resumen["emails_procesados"] == 1
    assert db.upserts[0][0] == "2026-08-11"


def test_asset_recorre_todos_los_dias_del_trozo():
    # ``multi_run(max_partitions_per_run=30)``: Dagster invoca la función UNA vez por run con
    # el trozo de días de la materialización (``partition_keys``), así que el asset los
    # procesa uno a uno.
    zip_11 = _zip_en_memoria([("A.pdf", b"%PDF")])
    zip_12 = _zip_en_memoria([("B.pdf", b"%PDF"), ("B.xml", b"<x/>")])
    corpac = _Corpac({URL: zip_11, URL_2: zip_12})
    dias = ["2026-08-11", "2026-08-12"]
    db = _Db(
        por_dia={
            "2026-08-11": [_email("e1", _body_con_enlace(URL))],
            "2026-08-12": [_email("e2", _body_con_enlace(URL_2))],
        }
    )
    context = _Context(partition_key=dias[0], partition_keys=dias)

    out = _ASSET_FN(context, corpac, db)

    # Un upsert por día, en orden y con su propia partición.
    assert corpac.calls == [URL, URL_2]
    assert [period for period, _ in db.upserts] == dias
    assert [len(filas) for _, filas in db.upserts] == [1, 2]
    # La metadata es el agregado del run.
    assert out.metadata["files_inserted"] == 3
    assert out.metadata["emails_procesados"] == 2
    assert out.metadata["days_processed"] == 2
    assert out.metadata["days"].data == dias
    assert out.metadata["files_by_day"].data == {"2026-08-11": 1, "2026-08-12": 2}


def test_el_fail_fast_es_por_dia():
    # El insert del día es todo-o-nada para los correos pendientes y los días anteriores ya
    # están insertados: un correo roto tumba el run, pero no re-hace los días ya cargados
    # (idempotente por día, append-only).
    zip_ok = _zip_en_memoria([("OK.pdf", b"%PDF")])
    corpac = _Corpac({URL: zip_ok})
    dias = ["2026-08-11", "2026-08-12"]
    db = _Db(
        por_dia={
            "2026-08-11": [_email("e1", _body_con_enlace(URL))],
            "2026-08-12": [_email("e2", "cuerpo sin enlace CORPAC")],
        }
    )
    context = _Context(partition_key=dias[0], partition_keys=dias)

    with pytest.raises(CorpacProcessingError, match="sin enlace CORPAC"):
        _ASSET_FN(context, corpac, db)

    assert [period for period, _ in db.upserts] == ["2026-08-11"]


def test_el_asset_no_devuelve_output_con_valor():
    # Con un trozo de particiones, un ``Output`` con valor pasa por el IO manager por
    # defecto, que no sabe persistir un output asociado a varias particiones y tumbaría
    # el run después de escribir los datos. El resumen va en la metadata del
    # materialization event (``MaterializeResult``), no en un valor.
    assert _ASSET_FN.__annotations__.get("return") is MaterializeResult


def test_asset_es_append_only_y_salta_los_correos_con_archivos(tmp_path):
    # Con el resource real (SQLite temporal): ``select_corpac_emails`` descarta los correos
    # que ya tienen **al menos un** archivo, así que el asset no los vuelve a descargar ni
    # re-inserta nada suyo (los ``id`` viejos, o sea ``corpac_header.file_id``, intactos).
    res = CorpacSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res._ensure_db()
    Email.create(
        id="e1", partition_date="2026-08-11", sender=CORPAC_SENDER, body=_body_con_enlace(URL)
    )
    Email.create(
        id="e2", partition_date="2026-08-11", sender=CORPAC_SENDER, body=_body_con_enlace(URL_2)
    )
    res.upsert_files(
        "2026-08-11", [{"id_email": "e1", "filename": "VIEJO.pdf", "data": "QUJD"}]
    )
    id_viejo = CorpacFile.get(CorpacFile.filename == "VIEJO.pdf").id

    corpac = _Corpac({URL_2: _zip_en_memoria([("NUEVO.pdf", b"%PDF")])})

    out = _ASSET_FN(_Context(), corpac, res)

    assert corpac.calls == [URL_2]  # el correo ya procesado ni se descarga
    assert out.metadata["emails_procesados"] == 1
    assert out.metadata["files_inserted"] == 1
    assert sorted(f.filename for f in CorpacFile.select()) == ["NUEVO.pdf", "VIEJO.pdf"]
    assert CorpacFile.get(CorpacFile.filename == "VIEJO.pdf").id == id_viejo

    # Tercera corrida con todo ya procesado: no descarga ni inserta nada.
    corpac.calls.clear()
    out = _ASSET_FN(_Context(), corpac, res)
    assert corpac.calls == []
    assert out.metadata["files_inserted"] == 0
