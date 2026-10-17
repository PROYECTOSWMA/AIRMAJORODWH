"""Tests del asset sire_details_monthly (iteración, insert de pendientes y missing_documents).

El asset se invoca a través de su función de cómputo subyacente (la que envuelve
``@asset``) con recursos stub para no tocar la red ni la BD.
"""

from datetime import date

import pytest

from assets.sire_assets.sire_details_asset.resources.api_resource.details_resource import (
    CpeDetailsMissing,
)
from assets.sire_assets.sire_details_asset.sire_details_asset import (
    _LOG_AVANCE_CADA,
    _dedupe_documents,
    _missing,
    sire_details_monthly,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    BOOK_CODE_PURCHASES,
    BOOK_CODE_SALES,
)

# ``sire_details_monthly`` es un AssetsDefinition; ``op.compute_fn.decorated_fn``
# es la función original (context, sire_details, sire_details_db).
_ASSET_FN = sire_details_monthly.op.compute_fn.decorated_fn


class _Log:
    def info(self, *args, **kwargs):
        pass


class _Context:
    # Clave de la partición mensual (ventana 2026-07-01 a 2026-08-01).
    partition_key = "2026-07-01"
    log = _Log()


class _Details:
    def __init__(self, items_by_numero, missing_numero=None):
        self.items_by_numero = items_by_numero
        self.missing_numero = missing_numero
        self.calls = []

    def companies(self):
        return ["Air Majoro"]

    def ruc(self, name):
        return "20494626978"

    def get_items(self, senderruc, tipo, serie, numero, rol, *, empresa):
        self.calls.append((senderruc, tipo, serie, numero, rol))
        if numero == self.missing_numero:
            raise CpeDetailsMissing("sin respuesta de la API")
        return self.items_by_numero.get(numero, [])


class _Db:
    def __init__(self, documentos_sales, documentos_purchs, con_detalle_ids=()):
        self.documentos_sales = documentos_sales
        self.documentos_purchs = documentos_purchs
        self.con_detalle_ids = set(con_detalle_ids)
        self.inserts = []
        self.orphan_cleanups = []
        self.rangos_consultados = []

    def count_documents(self, start_date, end_date, empresa, book_code=BOOK_CODE_PURCHASES):
        self.rangos_consultados.append((start_date, end_date, empresa, book_code))
        if book_code == BOOK_CODE_SALES:
            return len(self.documentos_sales)
        return len(self.documentos_purchs)

    def select_documents(self, start_date, end_date, empresa, book_code=BOOK_CODE_PURCHASES):
        self.rangos_consultados.append((start_date, end_date, empresa, book_code))
        if book_code == BOOK_CODE_SALES:
            return self.documentos_sales
        return self.documentos_purchs

    def select_missing_documents(self, start_date, end_date, empresa, book_code=BOOK_CODE_PURCHASES):
        self.rangos_consultados.append((start_date, end_date, empresa, book_code))
        todos = self.documentos_sales if book_code == BOOK_CODE_SALES else self.documentos_purchs
        return [d for d in todos if d["id"] not in self.con_detalle_ids]

    def delete_orphan_details(self, period, empresa, book_code=BOOK_CODE_PURCHASES):
        self.orphan_cleanups.append((period, empresa, book_code))
        return 0

    def insert_details(self, period, empresa, rows, book_code):
        rows_with_meta = [
            {**row, "period": period, "empresa": empresa} for row in rows
        ]
        self.inserts.append((period, empresa, rows_with_meta, book_code))
        return len(rows)


ITEM_A = {
    "cnt_items": 1,
    "cod_unidad_medida": "ZZ",
    "des_unidad_medida": "UNIDAD",
    "des_codigo": "3300000106",
    "des_item": "ITEM A",
    "mto_val_unitario": "10.50",
    "mto_icbper": "0.00",
    "mto_desc": "0.00",
    "mto_imp_total": "10.50",
}

SALES = [
    {"id": 1, "tipo_cp_doc": 1, "tipo_cp_modificado": None,
     "serie": "F001", "numero": 100, "nro_doc_identidad": "20607496961"},
    {"id": 2, "tipo_cp_doc": 7, "tipo_cp_modificado": 3,
     "serie": "B001", "numero": 5, "nro_doc_identidad": "20607496961"},
    {"id": 3, "tipo_cp_doc": 1, "tipo_cp_modificado": None,
     "serie": "F001", "numero": 999, "nro_doc_identidad": "20607496961"},  # falla
    {"id": 4, "tipo_cp_doc": 9, "tipo_cp_modificado": None,
     "serie": "X001", "numero": 1, "nro_doc_identidad": "20607496961"},  # tipo no manejado
]

PURCHS = [
    {"id": 5, "tipo_cp_doc": 3, "tipo_cp_modificado": None,
     "serie": "B100", "numero": 7, "nro_doc_identidad": "20100047218"},
]


def test_asset_itera_empresas_y_libros_y_arma_missing_documents():
    details = _Details({100: [ITEM_A]}, missing_numero=999)
    db = _Db(SALES, PURCHS)

    out = _ASSET_FN(_Context(), details, db)

    # La ventana de la partición 2026-07-01 es [2026-07-01, 2026-08-01).
    assert db.rangos_consultados[0][0] == date(2026, 7, 1)
    assert db.rangos_consultados[0][1] == date(2026, 8, 1)

    # Compras primero: emisor = ruc del proveedor (nro_doc_identidad), rol 2.
    assert details.calls[0] == ("20100047218", "03", "B100", 7, 2)
    # Ventas después: emisor = ruc de la empresa, rol 1, tipo mapeado.
    assert details.calls[1] == ("20494626978", "01", "F001", 100, 1)
    assert details.calls[2] == ("20494626978", "B7", "B001", 5, 1)
    assert details.calls[3] == ("20494626978", "01", "F001", 999, 1)

    # compras insertadas primero (0 ítems: no hay items para el 7)
    periodo, empresa, filas, book_code = db.inserts[0]
    assert (periodo, empresa, book_code) == ("2026-07-01", "Air Majoro", BOOK_CODE_PURCHASES)
    assert filas == []
    # ventas insertadas después: solo el doc 100 tiene items
    periodo, empresa, filas, book_code = db.inserts[1]
    assert (periodo, empresa, book_code) == ("2026-07-01", "Air Majoro", BOOK_CODE_SALES)
    assert len(filas) == 1
    assert filas[0]["sire_sale"] == 1
    assert filas[0]["des_item"] == "ITEM A"
    assert filas[0]["period"] == "2026-07-01"

    # El asset ya NO limpia huérfanos: con el padre append-only (ids estables) no
    # puede haberlos y el saneo por día borraría filas válidas de otros días.
    assert db.orphan_cleanups == []

    # 2 missing en ventas: 999 (sin respuesta) y tipo 9 (no manejado)
    assert out.metadata["missing_documents_count"] == 2
    missing = out.metadata["missing_documents"].value
    assert sorted(m["numero"] for m in missing) == [1, 999]
    assert "tipo_cp_doc no manejado" in [m["motivo"] for m in missing]
    assert "sin respuesta de la API" in [m["motivo"] for m in missing]
    assert all(
        m["empresa"] == "Air Majoro" and m["period"] == "2026-07-01" for m in missing
    )
    assert out.metadata["Air Majoro:sales_details"] == 1
    assert out.metadata["Air Majoro:purchs_details"] == 0


def test_dedupe_documents_quita_repetidos():
    docs = [
        {"tipo_cp_doc": 1, "serie": "F001", "numero": 1},
        {"tipo_cp_doc": 1, "serie": "F001", "numero": 1},
        {"tipo_cp_doc": 1, "serie": "F001", "numero": 2},
    ]
    assert len(_dedupe_documents(docs)) == 2


def test_missing_registro():
    m = _missing("20494626978", "01", "F001", 100, "Air Majoro", "202607", "sin respuesta")
    assert m == {
        "emisor": "20494626978",
        "tipo": "01",
        "serie": "F001",
        "numero": 100,
        "empresa": "Air Majoro",
        "period": "202607",
        "motivo": "sin respuesta",
    }


def test_asset_no_consulta_docs_que_ya_tienen_detalle():
    details = _Details({100: [ITEM_A]}, missing_numero=999)
    db = _Db(SALES, PURCHS, con_detalle_ids={2, 5})

    out = _ASSET_FN(_Context(), details, db)

    # Ventas: solo los docs 1, 3 y 4 quedan pendientes (el 2 ya tiene detalle).
    # Compras: el doc 5 ya tiene detalle -> nunca se llama a get_items con su RUC.
    assert [c[3] for c in details.calls] == [100, 999]

    # compras inserta 0 ítems (nada pendiente); ventas inserta solo el ítem del doc 1.
    assert db.inserts[0] == ("2026-07-01", "Air Majoro", [], BOOK_CODE_PURCHASES)
    periodo, empresa, filas, book_code = db.inserts[1]
    assert (periodo, empresa, book_code) == ("2026-07-01", "Air Majoro", BOOK_CODE_SALES)
    assert len(filas) == 1
    assert filas[0]["sire_sale"] == 1

    # Siguen faltando el doc 3 (sin respuesta) y el doc 4 (tipo no manejado).
    assert out.metadata["missing_documents_count"] == 2


def test_asset_loguea_cada_documento_sin_detalle():
    """Cada documento sin detalle se loguea uno a uno (info), como en sire_files."""

    class _CapturaLog:
        def __init__(self):
            self.infos = []

        def info(self, *args, **kwargs):
            self.infos.append(args[0] % args[1:])

    class _Ctx:
        partition_key = "2026-07-01"
        log = _CapturaLog()

    details = _Details({100: [ITEM_A]}, missing_numero=999)
    db = _Db(SALES, PURCHS)

    out = _ASSET_FN(_Ctx(), details, db)

    sin_detalle = [linea for linea in _Ctx.log.infos if "sin detalle (" in linea]
    # Compras B100-7 y ventas B001-5: la API respondió sin ítems.
    # Venta F001-999: la API no respondió. Venta X001-1: tipo no manejado.
    assert len(sin_detalle) == 4
    assert sum("la API no devolvió ítems" in linea for linea in sin_detalle) == 2
    assert any("B100-7" in linea for linea in sin_detalle)
    assert any("B001-5" in linea for linea in sin_detalle)
    assert any("F001-999" in linea and "sin respuesta de la API" in linea for linea in sin_detalle)
    assert any("X001-1" in linea and "tipo_cp_doc no manejado" in linea for linea in sin_detalle)
    # Las respuestas sin ítems no son fallas: no engordan missing_documents.
    assert out.metadata["missing_documents_count"] == 2


def test_asset_inserta_por_lotes_en_cada_log_avance():
    """El avance se persiste cada ``_LOG_AVANCE_CADA`` documentos, no solo al final."""
    n_docs = _LOG_AVANCE_CADA + 1
    documentos = [
        {
            "id": numero, "tipo_cp_doc": 1, "tipo_cp_modificado": None,
            "serie": "F001", "numero": numero, "nro_doc_identidad": "20607496961",
        }
        for numero in range(1, n_docs + 1)
    ]
    details = _Details({n: [ITEM_A] for n in range(1, n_docs + 1)})
    db = _Db(documentos, [])

    out = _ASSET_FN(_Context(), details, db)

    # Ventas: un insert al llegar al corte intermedio y otro con el resto.
    ventas = [call for call in db.inserts if call[3] == BOOK_CODE_SALES]
    assert len(ventas) == 2
    assert sum(len(call[2]) for call in ventas) == n_docs
    assert all(call[0] == "2026-07-01" and call[1] == "Air Majoro" for call in ventas)
    assert out.metadata["Air Majoro:sales_details"] == n_docs


def test_verbose_apagado_no_loguea_documento_a_documento(monkeypatch):
    """Sin ``SIRE_DETAILS_VERBOSE`` el log de una corrida normal no cambia."""

    class _CapturaLog:
        def __init__(self):
            self.infos = []

        def info(self, *args, **kwargs):
            self.infos.append(args[0] % args[1:])

    class _Ctx:
        partition_key = "2026-07-01"
        log = _CapturaLog()

    for variable in ("SIRE_DETAILS_VERBOSE", "SIRE_VERBOSE"):
        monkeypatch.delenv(variable, raising=False)
    ctx = _Ctx()
    details = _Details({100: [ITEM_A]}, missing_numero=999)
    out = _ASSET_FN(ctx, details, _Db(SALES, PURCHS))

    assert not [l for l in ctx.log.infos if "->" in l]
    assert not [l for l in ctx.log.infos if "resumen verboso" in l]
    assert out.metadata["verbose"] is False


@pytest.mark.parametrize("variable", ["SIRE_DETAILS_VERBOSE", "SIRE_VERBOSE"])
def test_verbose_loguea_cada_documento_con_resultado_y_tiempo(monkeypatch, variable):
    """El modo verboso (el del asset o el común) loguea cada documento y su resumen."""

    class _CapturaLog:
        def __init__(self):
            self.infos = []

        def info(self, *args, **kwargs):
            self.infos.append(args[0] % args[1:])

    class _Ctx:
        partition_key = "2026-07-01"
        log = _CapturaLog()

    monkeypatch.setenv(variable, "true")
    ctx = _Ctx()
    details = _Details({100: [ITEM_A]}, missing_numero=999)
    out = _ASSET_FN(ctx, details, _Db(SALES, PURCHS))

    lineas = [l for l in ctx.log.infos if "->" in l and "resumen verboso" not in l]
    # Compras B100-7 (API sin ítems) + ventas F001-100 (1 ítem), B001-5 (API sin
    # ítems), F001-999 (sin respuesta) y X001-1 (tipo no manejado) = 5 documentos.
    assert len(lineas) == 5
    assert all(" ms" in l for l in lineas)
    assert any("F001-100" in l and "1 ítems" in l for l in lineas)
    assert any("F001-999" in l and "sin respuesta de la API" in l for l in lineas)
    assert any("X001-1" in l and "tipo_cp_doc no manejado" in l for l in lineas)

    # Un resumen de ritmo por (empresa, libro): compras y ventas.
    resumenes = [l for l in ctx.log.infos if "resumen verboso" in l]
    assert len(resumenes) == 2
    assert out.metadata["verbose"] is True
