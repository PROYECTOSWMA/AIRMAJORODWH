"""Tests del asset ingest_emails: la descarga es **incremental** y por día.

El asset se invoca a través de su función de cómputo subyacente (la que envuelve
``@asset``) con recursos stub para no tocar la red ni la BD. Lo que se blinda es
que a Gmail solo se le piden los correos cuyo ``id`` **no** está ya en ``emails``.

Desde que ``ingest_emails`` declara
``BackfillPolicy.multi_run(max_partitions_per_run=30)``, un run de backfill invoca la
función **una vez** con los N días del trozo (``context.partition_keys``): por eso la
lógica de un día está en ``procesar_dia`` y aquí se prueba también que el asset la
recorre para **todos** los días del run y que **no** devuelve ``Output`` con valor (en
un run de rango el IO manager por defecto reventaría el run).
"""

from dagster import MaterializeResult

from assets.mail_asset.mail_asset import ingest_emails, procesar_dia

# ``ingest_emails`` es un AssetsDefinition; ``op.compute_fn.decorated_fn`` es la
# función original (context, gmail, db).
_ASSET_FN = ingest_emails.op.compute_fn.decorated_fn

CUENTA = "jorge.paredes@airmajoro.com"
OTRA_CUENTA = "contabilidad@airmajoro.com"


class _Log:
    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, *args, **kwargs):
        self.infos.append(args)

    def warning(self, *args, **kwargs):
        self.warnings.append(args)


class _Context:
    """Contexto mínimo: un día, o el trozo de rango de un run de backfill."""

    def __init__(self, partition_key="2026-08-11", partition_keys=None):
        self.partition_key = partition_key
        if partition_keys is not None:
            self.partition_keys = partition_keys
        self.log = _Log()


class _Gmail:
    """Doble del GmailResource: registra qué ids le piden descargar."""

    def __init__(self, ids_by_account):
        self.ids_by_account = ids_by_account
        self.list_calls = []
        self.fetch_calls = []

    def list_message_ids(self, query="", max_results=500):
        self.list_calls.append((query, max_results))
        return {cuenta: list(ids) for cuenta, ids in self.ids_by_account.items()}

    def fetch_emails(
        self, query="", max_results=500, ids_by_account=None, skip_ids=None
    ):
        self.fetch_calls.append(
            {
                "query": query,
                "ids_by_account": ids_by_account,
                "skip_ids": skip_ids,
            }
        )
        omitidos = skip_ids or set()
        return [
            {"id": mid, "mailbox": cuenta, "attachments": []}
            for cuenta, ids in (ids_by_account or {}).items()
            for mid in ids
            if mid not in omitidos
        ]


class _Db:
    """Doble del DbResource: ``emails`` contendrá solo los ids de ``existentes``."""

    def __init__(self, existentes=()):
        self.existentes = set(existentes)
        self.ids_consultados = None
        self.emails_insertados = []
        self.adjuntos_insertados = []

    def existing_email_ids(self, ids):
        self.ids_consultados = list(ids)
        return {i for i in ids if i in self.existentes}

    def append_emails(self, partition_date, emails):
        self.emails_insertados.append((partition_date, emails))
        return len(emails)

    def append_email_attachments(self, partition_date, emails):
        self.adjuntos_insertados.append((partition_date, emails))
        return 0


def test_solo_pide_a_gmail_los_correos_que_faltan():
    gmail = _Gmail({CUENTA: ["m1", "m2", "m3"]})
    db = _Db(existentes={"m1", "m3"})

    result = _ASSET_FN(_Context(), gmail, db)

    # La consulta de ids va contra TODOS los del día...
    assert db.ids_consultados == ["m1", "m2", "m3"]
    # ...y a Gmail solo se le piden los que faltan.
    assert gmail.fetch_calls[0]["skip_ids"] == {"m1", "m3"}
    assert [e["id"] for e in db.emails_insertados[0][1]] == ["m2"]
    assert result.metadata["emails_ingested"] == 1
    assert result.metadata["emails_skipped"] == 2
    assert result.metadata["emails_in_window"] == 3


def test_la_primera_corrida_baja_todo():
    gmail = _Gmail({CUENTA: ["m1", "m2"]})
    db = _Db()

    result = _ASSET_FN(_Context(), gmail, db)

    assert gmail.fetch_calls[0]["skip_ids"] == set()
    assert len(db.emails_insertados[0][1]) == 2
    assert result.metadata["emails_skipped"] == 0


def test_consulta_el_dia_completo_de_la_particion():
    gmail = _Gmail({CUENTA: ["m1"]})
    db = _Db()

    _ASSET_FN(_Context(), gmail, db)

    query, max_results = gmail.list_calls[0]
    assert query == "after:2026/08/11 before:2026/08/12"
    assert max_results >= 500
    # Los ids ya listados se reutilizan: el asset no vuelve a listar en fetch_emails.
    assert gmail.fetch_calls[0]["ids_by_account"] == {CUENTA: ["m1"]}


def test_consulta_todas_las_cuentas_en_una_sola_pasada():
    gmail = _Gmail({CUENTA: ["m1"], OTRA_CUENTA: ["m2"]})
    db = _Db(existentes={"m1"})

    result = _ASSET_FN(_Context(), gmail, db)

    assert db.ids_consultados == ["m1", "m2"]
    assert result.metadata["mailboxes"].data == [OTRA_CUENTA]
    assert len(gmail.list_calls) == 1


def test_avisa_si_una_cuenta_llena_el_tope_de_ids():
    context = _Context()
    gmail = _Gmail({CUENTA: [f"m{i}" for i in range(500)]})

    _ASSET_FN(context, gmail, _Db())

    assert any(CUENTA in aviso for aviso in context.log.warnings)


def test_los_adjuntos_se_insertan_despues_de_los_correos():
    gmail = _Gmail({CUENTA: ["m1"]})
    db = _Db()

    _ASSET_FN(_Context(), gmail, db)

    assert db.emails_insertados == [("2026-08-11", [{"id": "m1", "mailbox": CUENTA, "attachments": []}])]
    assert db.adjuntos_insertados == [("2026-08-11", [{"id": "m1", "mailbox": CUENTA, "attachments": []}])]


# --- Un día por llamada (``procesar_dia``) y el rango de un backfill -------------


def test_procesar_dia_devuelve_el_resumen_del_dia():
    gmail = _Gmail({CUENTA: ["m1", "m2"]})
    db = _Db(existentes={"m1"})

    resumen = procesar_dia(_Context(), gmail, db, "2026-08-11")

    assert resumen["partition_date"] == "2026-08-11"
    assert resumen["emails_ingested"] == 1
    assert resumen["emails_skipped"] == 1
    assert resumen["emails_in_window"] == 2
    assert resumen["mailboxes"] == [CUENTA]
    assert db.emails_insertados[0][0] == "2026-08-11"


def test_el_asset_recorre_todos_los_dias_del_run_de_backfill():
    # ``multi_run(max_partitions_per_run=30)``: la función se invoca UNA vez por run con
    # el trozo de rango en ``partition_keys``, así que el asset procesa cada día.
    dias = ["2026-08-10", "2026-08-11", "2026-08-12"]
    gmail = _Gmail({CUENTA: ["m1"]})
    db = _Db()
    context = _Context(partition_key=dias[0], partition_keys=dias)

    result = _ASSET_FN(context, gmail, db)

    # Una consulta (y un insert) por día, cada una con SU ventana after/before.
    assert [query for query, _ in gmail.list_calls] == [
        "after:2026/08/10 before:2026/08/11",
        "after:2026/08/11 before:2026/08/12",
        "after:2026/08/12 before:2026/08/13",
    ]
    assert [fecha for fecha, _ in db.emails_insertados] == dias
    assert [fecha for fecha, _ in db.adjuntos_insertados] == dias
    # La metadata es el agregado del run.
    assert result.metadata["emails_ingested"] == 3
    assert result.metadata["days_processed"] == 3
    assert result.metadata["days"].data == dias
    assert result.metadata["emails_by_day"].data == {dia: 1 for dia in dias}


def test_la_descarga_incremental_es_por_dia():
    # El incremental no se comparte entre días: cada día pregunta por los suyos, así que
    # los ya guardados se saltan uno a uno y no se re-descarga nada.
    dias = ["2026-08-10", "2026-08-11"]
    gmail = _Gmail({CUENTA: ["m1"]})
    db = _Db(existentes={"m1"})
    context = _Context(partition_key=dias[0], partition_keys=dias)

    result = _ASSET_FN(context, gmail, db)

    assert [llamada["skip_ids"] for llamada in gmail.fetch_calls] == [{"m1"}, {"m1"}]
    assert all(not emails for _, emails in db.emails_insertados)
    assert result.metadata["emails_ingested"] == 0
    assert result.metadata["emails_skipped"] == 2


def test_el_asset_no_devuelve_output_con_valor():
    # Con un rango de particiones (backfill multi_run), un ``Output`` con valor pasa por
    # el IO manager por defecto, que no sabe persistir un output asociado a varias
    # particiones y tumbaría el run después de escribir los datos. El resumen va en la
    # metadata del materialization event (``MaterializeResult``), no en un valor.
    assert _ASSET_FN.__annotations__.get("return") is MaterializeResult
