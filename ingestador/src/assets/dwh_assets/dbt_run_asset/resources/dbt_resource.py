"""Resource que ejecuta ``dbt run`` sobre el proyecto dbt de ``src/dbt``.

La capa analítica del pipeline se materializa con **dbt** en ``analytics_poc.duckdb``
leyendo ``db.sqlite`` (perfil ``consolidado``, target único ``dev``; ver
``src/dbt/profiles.yml``). Este resource ejecuta ese ``dbt run`` **en proceso**
(``dbtRunner`` de dbt-core) con el **CWD puesto en el proyecto dbt**: el ``profiles.yml``
usa rutas **relativas al CWD** (``../../analytics_poc.duckdb`` y ``../../db.sqlite``),
así que hay que reproducir el ``cd src/dbt && dbt run`` de la CLI.

Por qué en proceso y no un ``subprocess`` del ejecutable ``dbt``: los console scripts de
``.venv/bin`` tienen el shebang con la ruta vieja del repo (ver
``memory-bank/techContext.md``), así que ``subprocess("dbt", ...)`` fallaría;
``dbtRunner`` no depende de ese script. El import de ``dbt`` es **perezoso** (solo al
materializar), para no cargarlo al levantar ``definitions.py``.

``run()`` devuelve un resumen (modelos, estados y tiempo) y **lanza** ``DbtRunError``
si dbt falla, de forma que el step quede en FAILURE.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dagster import ConfigurableResource

# src/assets/dwh_assets/dbt_run_asset/resources/dbt_resource.py -> parents[4] = src
_SRC_DIR = Path(__file__).resolve().parents[4]
REPO_ROOT = _SRC_DIR.parent
DEFAULT_PROJECT_DIR = _SRC_DIR / "dbt"


class DbtRunError(Exception):
    """Falla de ``dbt run`` (derrumba la materialización de ``dbt_run``)."""


class DbtResource(ConfigurableResource):
    """Ejecuta ``dbt run`` sobre el proyecto dbt de ``src/dbt`` (target ``dev``)."""

    project_dir: str = str(DEFAULT_PROJECT_DIR)
    profiles_dir: str | None = None
    target: str = "dev"
    select: str | None = None
    extra_args: list[str] = []

    def dbt_args(self) -> list[str]:
        """Argumentos de la CLI de dbt (``dbt run ...``), en orden."""
        args = [
            "run",
            "--project-dir",
            self.project_dir,
            "--profiles-dir",
            self.profiles_dir or self.project_dir,
            "--target",
            self.target,
        ]
        if self.select:
            args += ["--select", self.select]
        return args + list(self.extra_args)

    def _invoke(self, args: list[str]) -> Any:
        """Invoca dbt en proceso (seam de test: los tests monkeypatchean aquí).

        Devuelve el ``dbtRunnerResult`` de dbt-core (``.success``, ``.result`` con la
        lista de nodos y ``.exception`` con el error de dbt si lo hubo).
        """
        from dbt.cli.main import dbtRunner

        return dbtRunner().invoke(args)

    def run(self) -> dict[str, Any]:
        """Ejecuta ``dbt run`` y devuelve el resumen; lanza ``DbtRunError`` si falla."""
        args = self.dbt_args()
        cwd = os.getcwd()
        started = time.monotonic()
        try:
            # El `profiles.yml` usa rutas relativas al CWD (equivale a `cd src/dbt`).
            os.chdir(self.project_dir)
            result = self._invoke(args)
        except DbtRunError:
            raise
        except Exception as exc:  # noqa: BLE001 - se re-lanza como fallo de dbt
            raise DbtRunError(
                f"`dbt run` falló al invocarse ({' '.join(args)}): {exc}"
            ) from exc
        finally:
            os.chdir(cwd)
        elapsed = time.monotonic() - started

        statuses: dict[str, int] = {}
        fallidos: list[str] = []
        for node in getattr(result, "result", None) or []:
            status = getattr(node, "status", None)
            nombre = getattr(status, "value", None) or str(status)
            statuses[str(nombre)] = statuses.get(str(nombre), 0) + 1
            if nombre == "error":
                fallidos.append(getattr(getattr(node, "node", None), "name", "?"))
        modelos = sum(statuses.values())

        if not getattr(result, "success", False):
            detalle = str(getattr(result, "exception", "") or "") or (
                f"modelos con error: {fallidos}" if fallidos else "sin detalle"
            )
            raise DbtRunError(
                f"`dbt run` terminó con error: {detalle} "
                f"(modelos: {modelos}, estados: {statuses})"
            )

        return {
            "args": args,
            "elapsed_seconds": round(elapsed, 2),
            "statuses": statuses,
            "models_run": modelos,
            "failed_models": fallidos,
        }
