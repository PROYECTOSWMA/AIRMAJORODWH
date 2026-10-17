"""Tests del asset mensual ``seesol_rh_monthly`` (particiones, política y upsert).

El asset se invoca con un contexto y unos resources de mentira: se comprueba que
itera los meses del run (1 en una materialización normal, N en un backfill
``single_run``) y las empresas de ``EMPRESAS``, que hace el upsert **por (period,
empresa)** y que avisa cuando el mes nuevo trae menos filas que el anterior.
"""
import datetime as dt

from dagster import MaterializeResult

from assets._common.partitions import seesol_rh_monthly_partitions_def
from assets.seesol_rh_asset.seesol_rh_asset import seesol_rh_monthly

import assets.seesol_rh_asset.seesol_rh_asset as mod

_ASSET_FN = seesol_rh_monthly.op.compute_fn.decorated_fn
_EMPRESAS = ["Empresa A", "Empresa B"]


class _Log:
    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, *args, **kwargs):
        self.infos.append(args)

    def warning(self, *args, **kwargs):
        self.warnings.append(args)


class _Ctx:
    def __init__(self, partition_key="2026-08-01", partition_keys=None):
        self.partition_key = partition_key
        if partition_keys is not None:
            self.partition_keys = partition_keys
        self.log = _Log()


class _Api:
    """``RhResource`` stub: filas por (empresa, period) y registro de llamadas."""

    def __init__(self, filas_por_empresa):
        self.filas_por_empresa = filas_por_empresa
        self.calls = []

    def get_month(self, empresa, period):
        self.calls.append((empresa, period))
        return [
            {"nro_doc_emitido": f"{empresa}-{i}", "period": period}
            for i in range(self.filas_por_empresa.get(empresa, 0))
        ]


class _Db:
    """``SeesolRhSqliteResource`` stub: registra los upserts y las consultas."""

    def __init__(self, previas=None):
        self.upserts = []  # (period, empresa, rows)
        self.consultas = []  # (period, empresa)
        self.previas = previas or {}

    def count_month(self, period, empresa):
        self.consultas.append((period, empresa))
        return self.previas.get((period, empresa), 0)

    def upsert_month(self, period, empresa, rows):
        self.upserts.append((period, empresa, rows))
        return len(rows)


def _spec(asset):
    return next(iter(asset.specs))


def test_particion_mensual_con_el_mes_en_curso():
    ahora = dt.datetime(2026, 9, 17, 12, 0, tzinfo=dt.timezone.utc)
    keys = seesol_rh_monthly_partitions_def.get_partition_keys(current_time=ahora)
    assert keys[0] == "2026-01-01"
    assert keys[-1] == "2026-09-01"  # end_offset=1: el mes en curso es válido
    assert len(keys) == 9  # enero..septiembre de 2026
    assert _spec(seesol_rh_monthly).partitions_def is seesol_rh_monthly_partitions_def


def test_single_run_y_sin_automatizacion():
    politica = seesol_rh_monthly.backfill_policy
    assert politica is not None and politica.max_partitions_per_run is None
    assert _spec(seesol_rh_monthly).automation_condition is None
    # El RH es un asset independiente: no declara dependencias.
    assert _spec(seesol_rh_monthly).deps == []


def test_no_devuelve_output_con_valor():
    # El cron materializa el rango de 2 meses con ``single_run``: un ``Output`` con
    # valor pasa por el IO manager por defecto, que no soporta persistir un output
    # asociado a varias particiones, y el step cae después de haber upserteado.
    fn = seesol_rh_monthly.op.compute_fn.decorated_fn
    assert fn.__annotations__.get("return") is MaterializeResult


def test_asset_upserta_por_mes_y_empresa(monkeypatch):
    monkeypatch.setattr(mod, "EMPRESAS", _EMPRESAS)
    api = _Api({"Empresa A": 2, "Empresa B": 1})
    db = _Db()

    out = _ASSET_FN(_Ctx("2026-08-01"), api, db)

    assert api.calls == [("Empresa A", "2026-08-01"), ("Empresa B", "2026-08-01")]
    assert db.consultas == [("2026-08-01", "Empresa A"), ("2026-08-01", "Empresa B")]
    # El upsert va por (period, empresa) con la empresa estampada en cada fila.
    assert [u[:2] for u in db.upserts] == [
        ("2026-08-01", "Empresa A"),
        ("2026-08-01", "Empresa B"),
    ]
    assert db.upserts[0][2][0]["empresa"] == "Empresa A"
    assert db.upserts[0][2][0]["period"] == "2026-08-01"
    assert out.metadata["2026-08-01|Empresa A"] == 2
    assert out.metadata["2026-08-01|Empresa B"] == 1
    assert out.metadata["rows_upserted"] == 3
    assert out.metadata["months"] == 1
    assert out.metadata["periods"] == "2026-08-01"


def test_asset_backfill_de_dos_meses(monkeypatch):
    monkeypatch.setattr(mod, "EMPRESAS", ["Empresa A"])
    api = _Api({"Empresa A": 1})
    db = _Db()

    out = _ASSET_FN(
        _Ctx(partition_keys=["2026-08-01", "2026-09-01"], partition_key="2026-08-01"),
        api,
        db,
    )

    assert api.calls == [("Empresa A", "2026-08-01"), ("Empresa A", "2026-09-01")]
    assert out.metadata["2026-08-01|Empresa A"] == 1
    assert out.metadata["2026-09-01|Empresa A"] == 1
    assert out.metadata["months"] == 2
    assert out.metadata["periods"] == "2026-08-01, 2026-09-01"


def test_asset_avisa_si_el_mes_trae_menos_filas(monkeypatch):
    monkeypatch.setattr(mod, "EMPRESAS", ["Empresa A"])
    api = _Api({"Empresa A": 1})
    db = _Db(previas={("2026-08-01", "Empresa A"): 5})
    ctx = _Ctx("2026-08-01")

    _ASSET_FN(ctx, api, db)

    assert len(ctx.log.warnings) == 1
    assert "incompleto" in ctx.log.warnings[0][0]
