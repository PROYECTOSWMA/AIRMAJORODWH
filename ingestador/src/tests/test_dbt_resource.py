"""Tests del resource de dbt (`DbtResource`).

Cubren lo que el resource aporta sobre la CLI: los argumentos de ``dbt run``, el **CWD
puesto en el proyecto dbt** (el ``profiles.yml`` usa rutas relativas al CWD) y la
conversión de cualquier fallo en ``DbtRunError``. **No invocan dbt de verdad**: se
monkeypatchea el seam ``_invoke`` (el import de ``dbt`` es perezoso y aquí ni se toca).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from assets.dwh_assets.dbt_run_asset.resources.dbt_resource import (
    DEFAULT_PROJECT_DIR,
    DbtResource,
    DbtRunError,
)


class _Node:
    """Doble del nodo de resultado de dbt (solo ``node.name`` y ``status.value``)."""

    def __init__(self, name, status):
        self.node = type("Nodo", (), {"name": name})()
        self.status = type("Estado", (), {"value": status})()


class _Result:
    """Doble del ``dbtRunnerResult`` de dbt-core."""

    def __init__(self, success=True, nodes=(), exception=None):
        self.success = success
        self.result = list(nodes)
        self.exception = exception


def _resource(**kwargs) -> DbtResource:
    return DbtResource(project_dir=str(DEFAULT_PROJECT_DIR), **kwargs)


def test_args_por_defecto():
    args = _resource().dbt_args()

    assert args[:3] == ["run", "--project-dir", str(DEFAULT_PROJECT_DIR)]
    assert args[3] == "--profiles-dir"
    assert args[4] == str(DEFAULT_PROJECT_DIR)  # profiles.yml vive en el proyecto
    assert args[args.index("--target") + 1] == "dev"
    assert "--select" not in args


def test_args_con_select_profiles_dir_y_extra_args():
    res = _resource(profiles_dir="/tmp/perfiles", select="moves", extra_args=["--no-partial-parse"])
    args = res.dbt_args()

    assert args[args.index("--profiles-dir") + 1] == "/tmp/perfiles"
    assert args[args.index("--select") + 1] == "moves"
    assert args[-1] == "--no-partial-parse"


def test_corre_con_el_cwd_del_proyecto_y_lo_restaura(monkeypatch):
    visto = {}

    def falso_invoke(self, args):
        visto["cwd"] = os.getcwd()
        visto["args"] = args
        return _Result(nodes=[_Node("moves", "success"), _Node("partners", "success")])

    monkeypatch.setattr(DbtResource, "_invoke", falso_invoke)
    cwd_antes = os.getcwd()

    resumen = _resource().run()

    assert Path(visto["cwd"]).resolve() == DEFAULT_PROJECT_DIR.resolve()
    assert visto["args"] == resumen["args"]
    assert os.getcwd() == cwd_antes  # el CWD del proceso se restaura
    assert resumen["models_run"] == 2
    assert resumen["statuses"] == {"success": 2}
    assert resumen["failed_models"] == []
    assert resumen["elapsed_seconds"] >= 0


def test_restaura_el_cwd_si_dbt_falla(monkeypatch):
    def falso_invoke(self, args):
        raise RuntimeError("boom")

    monkeypatch.setattr(DbtResource, "_invoke", falso_invoke)
    cwd_antes = os.getcwd()

    with pytest.raises(DbtRunError):
        _resource().run()

    assert os.getcwd() == cwd_antes


def test_success_false_lanza_dbt_run_error_con_los_modelos_fallidos(monkeypatch):
    monkeypatch.setattr(
        DbtResource,
        "_invoke",
        lambda self, args: _Result(
            success=False,
            nodes=[_Node("moves", "success"), _Node("sales_std", "error")],
            exception="Compilation Error in model sales_std",
        ),
    )

    with pytest.raises(DbtRunError) as excinfo:
        _resource().run()

    mensaje = str(excinfo.value)
    assert "Compilation Error in model sales_std" in mensaje
    assert "sales_std" in mensaje


def test_success_false_sin_exception_menciona_los_modelos_fallidos(monkeypatch):
    monkeypatch.setattr(
        DbtResource,
        "_invoke",
        lambda self, args: _Result(success=False, nodes=[_Node("moves", "error")]),
    )

    with pytest.raises(DbtRunError) as excinfo:
        _resource().run()

    assert "moves" in str(excinfo.value)


def test_excepcion_inesperada_se_envuelve_en_dbt_run_error(monkeypatch):
    def falso_invoke(self, args):
        raise ValueError("sin conexión")

    monkeypatch.setattr(DbtResource, "_invoke", falso_invoke)

    with pytest.raises(DbtRunError) as excinfo:
        _resource().run()

    assert "sin conexión" in str(excinfo.value)
    assert "--project-dir" in str(excinfo.value)
