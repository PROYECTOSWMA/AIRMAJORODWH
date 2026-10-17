"""Tests de FlightReportsSqliteResource (upsert total por período)."""

import pytest

from assets.from_sql_majoro_assets.flight_reports_asset.models.model import (
    FlightReports,
    db,
)
from assets.from_sql_majoro_assets.flight_reports_asset.resources.db_resource import (
    FlightReportsSqliteResource,
)


@pytest.fixture(autouse=True)
def _clean_db():
    # ``db`` es un DatabaseProxy global compartido: se desenlaza entre tests para
    # que cada recurso lo apunte al archivo SQLite temporal que le corresponde.
    yield
    if db.obj is not None:
        try:
            db.obj.close()
        except Exception:
            pass
        db.initialize(None)


def _row(
    fecha: str = "2026-08-01",
    sede: str = "MEDEVAC",
    matricula: str = "OB2092",
    horas: str = "3.50",
    pax: int = 8,
) -> dict:
    return {
        "fecha_vuelo": fecha,
        "sede_operacion": sede,
        "matricula": matricula,
        "horas_vuelo": horas,
        "total_pasajeros": pax,
    }


def test_upsert_inserts_and_replaces_same_period(tmp_path):
    res = FlightReportsSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    n = res.upsert_report("2026-08-01", [_row(), _row(matricula="OB2200")])
    assert n == 2
    assert FlightReports.select().where(FlightReports.period == "2026-08-01").count() == 2

    n2 = res.upsert_report("2026-08-01", [_row(matricula="OB2221P")])
    assert n2 == 1
    assert FlightReports.select().where(FlightReports.period == "2026-08-01").count() == 1
    assert (
        FlightReports.get(FlightReports.period == "2026-08-01").matricula == "OB2221P"
    )


def test_upsert_does_not_touch_other_periods(tmp_path):
    res = FlightReportsSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.upsert_report("2026-07-01", [_row()])
    res.upsert_report("2026-08-01", [_row(), _row(matricula="OB2200")])
    assert FlightReports.select().where(FlightReports.period == "2026-07-01").count() == 1
    assert FlightReports.select().where(FlightReports.period == "2026-08-01").count() == 2


def test_upsert_empty_rows_clears_period(tmp_path):
    res = FlightReportsSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.upsert_report("2026-08-01", [_row()])
    n = res.upsert_report("2026-08-01", [])
    assert n == 0
    assert FlightReports.select().where(FlightReports.period == "2026-08-01").count() == 0


def test_upsert_many_rows_chunked(tmp_path, monkeypatch):
    """Muchas filas no deben superar el límite de variables SQL de SQLite."""

    import assets._common.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 100)
    res = FlightReportsSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    rows = [_row(matricula=f"OB{i:04d}") for i in range(50)]
    n = res.upsert_report("2026-08-01", rows)
    assert n == 50
    assert FlightReports.select().where(FlightReports.period == "2026-08-01").count() == 50
    assert FlightReports.get(FlightReports.matricula == "OB0049") is not None
