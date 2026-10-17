"""Tests del asset sire_files_monthly (iteración, insert de pendientes y missing_files).

El asset se invoca a través de su función de cómputo subyacente (la que envuelve
``@asset``) con recursos stub para no tocar la red ni la BD.
"""

import pytest

from assets.sire_assets.sire_files_asset.resources.api_resource.constants import (
    FILE_KIND_PDF,
    FILE_KIND_ZIP,
)
from assets.sire_assets.sire_files_asset.resources.api_resource.files_resource import (
    CpeFilesMissing,
)
from assets.sire_assets.sire_files_asset.sire_files_asset import (
    _LOG_AVANCE_CADA,
    _dedupe_documents,
    _missing,
    sire_files_monthly,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    BOOK_CODE_PURCHASES,
    BOOK_CODE_SALES,
)

# ``sire_files_monthly`` es un AssetsDefinition; ``op.compute_fn.decorated_fn``
# es la función original (context, sire_files, sire_files_db).
_ASSET_FN = sire_files_monthly.op.compute_fn.decorated_fn


class _Log:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class _Context:
    # Clave de la partición mensual (ventana 2026-07-01 a 2026-08-01).
    partition_key = "2026-07-01"
    log = _Log()


class _Files:
    def __init__(self, archivos):
        self.archivos = archivos  # {(numero, tipo_archivo): {"nom_archivo", "val_archivo"}}
        self.calls = []

    def companies(self):
        return ["Air Majoro"]

    def ruc(self, name):
        return "20494626978"

    def get_file(self, senderruc, tipo, serie, numero, *, tipo_archivo, empresa, rol=1):
        self.calls.append((senderruc, tipo, serie, numero, rol, tipo_archivo))
        if (numero, tipo_archivo) not in self.archivos:
            raise CpeFilesMissing("sin respuesta de la API")
        return self.archivos[(numero, tipo_archivo)]


class _Db:
    def __init__(self, documentos_sales, documentos_purchs, con_archivo=()):
        self.documentos_sales = documentos_sales
        self.documentos_purchs = documentos_purchs
        self.con_archivo = set(con_archivo)  # {(id, tipo_archivo)} ya presente
        self.inserts = []
        self.orphan_cleanups = []

    def select_missing_files(self, start_date, end_date, empresa, tipo_documento, book_code=BOOK_CODE_PURCHASES):
        todos = self.documentos_sales if book_code == BOOK_CODE_SALES else self.documentos_purchs
        return [
            d for d in todos
            if (d["id"], tipo_documento) not in self.con_archivo
        ]

    def delete_orphan_files(self, period, empresa, book_code=BOOK_CODE_PURCHASES):
        self.orphan_cleanups.append((period, empresa, book_code))
        return 0

    def insert_files(self, period, empresa, rows, book_code):
        rows_with_meta = [
            {**row, "period": period, "empresa": empresa} for row in rows
        ]
        self.inserts.append((period, empresa, rows_with_meta, book_code))
        return len(rows)


ARCHIVO = {
    "nom_archivo": "20514513172-08-F040-399-XML.zip",
    "val_archivo": "UEsDBBQAAAAIAG62M1xEjjea7RQAAIZDAAAb",
}

SALES = [
    {"id": 1, "tipo_cp_doc": 1, "tipo_cp_modificado": None,
     "serie": "F001", "numero": 100, "nro_doc_identidad": "20607496961"},
    {"id": 2, "tipo_cp_doc": 9, "tipo_cp_modificado": None,
     "serie": "X001", "numero": 1, "nro_doc_identidad": "20607496961"},  # tipo no manejado
]

PURCHS = [
    {"id": 3, "tipo_cp_doc": 3, "tipo_cp_modificado": None,
     "serie": "B100", "numero": 7, "nro_doc_identidad": "20100047218"},
]


def test_asset_consulta_pdf_y_zip_por_registro_y_arma_missing_files():
    files = _Files(
        {
            (100, FILE_KIND_PDF): ARCHIVO,
            (100, FILE_KIND_ZIP): ARCHIVO,
            (7, FILE_KIND_PDF): ARCHIVO,
            (7, FILE_KIND_ZIP): ARCHIVO,
        }
    )
    db = _Db(SALES, PURCHS)

    out = _ASSET_FN(_Context(), files, db)

    # Compras primero: emisor = ruc del proveedor, rol 2; PDF y ZIP por documento.
    assert ("20100047218", "03", "B100", 7, 2, FILE_KIND_PDF) in files.calls
    assert ("20100047218", "03", "B100", 7, 2, FILE_KIND_ZIP) in files.calls
    # Ventas después: emisor = ruc de la empresa, rol 1; PDF y ZIP por documento.
    assert ("20494626978", "01", "F001", 100, 1, FILE_KIND_PDF) in files.calls
    assert ("20494626978", "01", "F001", 100, 1, FILE_KIND_ZIP) in files.calls

    # 4 inserts: compras pdf, compras zip, ventas pdf, ventas zip (una fila c/u).
    assert len(db.inserts) == 4
    for i, (bc, tipo) in enumerate(
        [
            (BOOK_CODE_PURCHASES, FILE_KIND_PDF),
            (BOOK_CODE_PURCHASES, FILE_KIND_ZIP),
            (BOOK_CODE_SALES, FILE_KIND_PDF),
            (BOOK_CODE_SALES, FILE_KIND_ZIP),
        ]
    ):
        periodo, empresa, filas, book_code = db.inserts[i]
        assert (periodo, empresa, book_code) == ("2026-07-01", "Air Majoro", bc)
        assert len(filas) == 1
        assert filas[0]["tipo_documento"] == tipo
        assert filas[0]["nom_archivo"] == ARCHIVO["nom_archivo"]
        assert filas[0]["period"] == "2026-07-01"

    # ventas: el doc 100 usa el FK sire_sale; compras: el doc 3 usa sire_purch.
    assert db.inserts[2][2][0]["sire_sale"] == 1
    assert db.inserts[0][2][0]["sire_purch"] == 3

    # El asset ya NO limpia huérfanos: con el padre append-only (ids estables) no
    # puede haberlos y el saneo por día borraría filas válidas de otros días.
    assert db.orphan_cleanups == []

    # 2 missing en ventas (tipo 9 no manejado): uno por cada tipo de documento
    assert out.metadata["missing_files_count"] == 2
    missing = out.metadata["missing_files"].value
    assert sorted(m["tipo_documento"] for m in missing) == [FILE_KIND_PDF, FILE_KIND_ZIP]
    assert all(m["numero"] == 1 for m in missing)
    assert all(m["motivo"] == "tipo_cp_doc no manejado" for m in missing)
    assert all(m["empresa"] == "Air Majoro" for m in missing)

    assert out.metadata["Air Majoro:sales_pdf"] == 1
    assert out.metadata["Air Majoro:sales_zip"] == 1
    assert out.metadata["Air Majoro:purchs_pdf"] == 1
    assert out.metadata["Air Majoro:purchs_zip"] == 1


def test_asset_no_reconsulta_el_tipo_ya_presente():
    # El doc 100 de ventas ya tiene PDF: solo se vuelve a pedir su ZIP.
    files = _Files(
        {
            (100, FILE_KIND_ZIP): ARCHIVO,
            (7, FILE_KIND_PDF): ARCHIVO,
            (7, FILE_KIND_ZIP): ARCHIVO,
        }
    )
    db = _Db(SALES, PURCHS, con_archivo={(1, FILE_KIND_PDF)})

    out = _ASSET_FN(_Context(), files, db)

    # No se pide el PDF del doc 100 (ya existe); el ZIP sí se pide.
    assert [
        c for c in files.calls
        if c[2] == "F001" and c[5] == FILE_KIND_PDF
    ] == []
    assert ("20494626978", "01", "F001", 100, 1, FILE_KIND_ZIP) in files.calls

    # El doc 2 (tipo 9) sigue en missing, una vez por cada tipo de documento.
    assert out.metadata["missing_files_count"] == 2


def test_asset_registra_missing_cuando_la_api_no_responde():
    files = _Files(
        {
            (7, FILE_KIND_PDF): ARCHIVO,
            (7, FILE_KIND_ZIP): ARCHIVO,
        }
    )
    db = _Db(
        [
            {"id": 1, "tipo_cp_doc": 1, "tipo_cp_modificado": None,
             "serie": "F001", "numero": 100, "nro_doc_identidad": "20607496961"},
        ],
        PURCHS,
    )

    out = _ASSET_FN(_Context(), files, db)

    missing = out.metadata["missing_files"].value
    assert sorted(m["motivo"] for m in missing) == [
        "sin respuesta de la API",
        "sin respuesta de la API",
    ]
    assert all(m["tipo"] == "01" for m in missing)
    assert all(m["numero"] == 100 for m in missing)
    # El archivo de compras sí se insertó (2 filas, una por tipo).
    assert db.inserts[0][2][0]["nom_archivo"] == ARCHIVO["nom_archivo"]


def test_asset_loguea_cada_documento_missing():
    class _CapturaLog:
        def __init__(self):
            self.warnings = []

        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            self.warnings.append(args[0] % args[1:])

    class _Ctx:
        partition_key = "2026-07-01"
        log = _CapturaLog()

    files = _Files({(7, FILE_KIND_PDF): ARCHIVO, (7, FILE_KIND_ZIP): ARCHIVO})
    db = _Db(
        [
            {"id": 1, "tipo_cp_doc": 1, "tipo_cp_modificado": None,
             "serie": "F001", "numero": 100, "nro_doc_identidad": "20607496961"},
        ],
        PURCHS,
    )

    out = _ASSET_FN(_Ctx(), files, db)

    # 2 missing (PDF y ZIP del doc 100 de ventas) -> 2 warnings logueados.
    assert out.metadata["missing_files_count"] == 2
    assert len(_Ctx.log.warnings) == 2
    for w in _Ctx.log.warnings:
        assert "sin archivo" in w
        assert "motivo: sin respuesta de la API" in w
        assert "F001-100" in w


def test_dedupe_documents_quita_repetidos():
    docs = [
        {"tipo_cp_doc": 1, "serie": "F001", "numero": 1},
        {"tipo_cp_doc": 1, "serie": "F001", "numero": 1},
        {"tipo_cp_doc": 1, "serie": "F001", "numero": 2},
    ]
    assert len(_dedupe_documents(docs)) == 2


def test_missing_registro():
    m = _missing(
        "20494626978", "01", "F001", 100, "Air Majoro", "202607",
        FILE_KIND_PDF, "sin respuesta",
    )
    assert m == {
        "emisor": "20494626978",
        "tipo": "01",
        "serie": "F001",
        "numero": 100,
        "empresa": "Air Majoro",
        "period": "202607",
        "tipo_documento": FILE_KIND_PDF,
        "motivo": "sin respuesta",
    }


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
    files = _Files(
        {
            (numero, tipo): ARCHIVO
            for numero in range(1, n_docs + 1)
            for tipo in (FILE_KIND_PDF, FILE_KIND_ZIP)
        }
    )
    db = _Db(documentos, [])

    out = _ASSET_FN(_Context(), files, db)

    # Ventas: por cada tipo, un insert al llegar al corte intermedio y otro con el resto.
    ventas = [call for call in db.inserts if call[3] == BOOK_CODE_SALES]
    for tipo in (FILE_KIND_PDF, FILE_KIND_ZIP):
        lote = [call for call in ventas if call[2][0]["tipo_documento"] == tipo]
        assert len(lote) == 2
        assert sum(len(call[2]) for call in lote) == n_docs
        assert all(call[0] == "2026-07-01" and call[1] == "Air Majoro" for call in lote)
    assert out.metadata["Air Majoro:sales_pdf"] == n_docs
    assert out.metadata["Air Majoro:sales_zip"] == n_docs


def test_verbose_apagado_no_loguea_documento_a_documento(monkeypatch):
    """Sin modo verboso el log de una corrida normal no cambia."""

    class _CapturaLog:
        def __init__(self):
            self.infos = []

        def info(self, *args, **kwargs):
            self.infos.append(args[0] % args[1:])

        def warning(self, *args, **kwargs):
            pass

    class _Ctx:
        partition_key = "2026-07-01"
        log = _CapturaLog()

    for variable in ("SIRE_FILES_VERBOSE", "SIRE_VERBOSE"):
        monkeypatch.delenv(variable, raising=False)

    ctx = _Ctx()
    files = _Files(
        {
            (100, FILE_KIND_PDF): ARCHIVO,
            (100, FILE_KIND_ZIP): ARCHIVO,
            (7, FILE_KIND_PDF): ARCHIVO,
            (7, FILE_KIND_ZIP): ARCHIVO,
        }
    )
    out = _ASSET_FN(ctx, files, _Db(SALES, PURCHS))

    assert not [l for l in ctx.log.infos if "->" in l]
    assert not [l for l in ctx.log.infos if "resumen verboso" in l]
    assert out.metadata["verbose"] is False


@pytest.mark.parametrize("variable", ["SIRE_FILES_VERBOSE", "SIRE_VERBOSE"])
def test_verbose_loguea_cada_documento_con_resultado_y_tiempo(monkeypatch, variable):
    """El modo verboso (el del asset o el común) loguea cada documento y su resumen."""

    class _CapturaLog:
        def __init__(self):
            self.infos = []

        def info(self, *args, **kwargs):
            self.infos.append(args[0] % args[1:])

        def warning(self, *args, **kwargs):
            pass

    class _Ctx:
        partition_key = "2026-07-01"
        log = _CapturaLog()

    monkeypatch.setenv(variable, "1")
    files = _Files(
        {
            (100, FILE_KIND_PDF): ARCHIVO,
            (100, FILE_KIND_ZIP): ARCHIVO,
            (7, FILE_KIND_PDF): ARCHIVO,
            (7, FILE_KIND_ZIP): ARCHIVO,
        }
    )
    ctx = _Ctx()
    out = _ASSET_FN(ctx, files, _Db(SALES, PURCHS))

    lineas = [l for l in ctx.log.infos if "->" in l and "resumen verboso" not in l]
    # Compras B100-7 (PDF y ZIP) + ventas F001-100 (PDF y ZIP) + ventas X001-1
    # (tipo 9 no manejado, PDF y ZIP) = 6 documentos-tipo procesados.
    assert len(lineas) == 6
    assert all(" ms" in l for l in lineas)
    assert sum("con archivo" in l for l in lineas) == 4
    assert sum("tipo_cp_doc no manejado" in l for l in lineas) == 2
    assert any("F001-100" in l and FILE_KIND_PDF in l for l in lineas)

    # Un resumen de ritmo por (empresa, libro, tipo): compras/ventas × PDF/ZIP.
    assert len([l for l in ctx.log.infos if "resumen verboso" in l]) == 4
    assert out.metadata["verbose"] is True

