"""Asset ``publish_dwh``: publica el DuckDB analítico en el schema ``dwh`` de PostgreSQL.

Es el último eslabón del pipeline (assets -> ``dbt_run`` -> publicación) y el paso que hasta
ahora era manual (``python sync_db.py`` con las credenciales PG en el entorno). El **motor
vive en `DwhPublishResource`** (`resources/publish_resource.py`, que también es su CLI):
publica **todas** las tablas BASE del DuckDB con el mismo nombre (``moves`` -> ``dwh.moves``),
crea lo que falte y hace ``DELETE`` + ``COPY`` sin ``DROP`` (la vista
``dwh.vista_reporte_gerencial`` cuelga de esas tablas).

Depende de ``dbt_run``: el orden lo impone el grafo, no hay que acordarse. No es
particionable (publica el DuckDB completo).
"""

from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
)

from assets.dwh_assets.dbt_run_asset.dbt_run_asset import dbt_run
from assets.dwh_assets.dwh_publish_asset.resources.publish_resource import (
    DwhPublishResource,
)


@asset(
    name="publish_dwh",
    group_name="dwh",
    deps=[dbt_run],
    description=(
        "Copia las tablas BASE de `analytics_poc.duckdb` al schema `dwh` de PostgreSQL "
        "(mismo nombre, `DELETE` + `COPY`, sin `DROP`)."
    ),
)
def publish_dwh(
    context: AssetExecutionContext,
    dwh_publish: DwhPublishResource,
) -> MaterializeResult:
    """Publica el DuckDB en Postgres dejando tablas y filas publicadas en la metadata."""
    tablas = dwh_publish.tables()
    if not tablas:
        context.log.warning(
            "El DuckDB %s no tiene tablas BASE: ¿se materializó `dbt_run`?",
            dwh_publish.duckdb_path,
        )
    destino = (
        "dry-run (sin escribir en PostgreSQL)"
        if dwh_publish.dry_run
        else f"schema {dwh_publish.schema_name}"
    )
    context.log.info(
        "publicando %d tablas de %s -> %s",
        len(tablas),
        dwh_publish.duckdb_path,
        destino,
    )

    filas = dwh_publish.publish()

    context.log.info("publicadas %d filas en %s", filas, destino)
    return MaterializeResult(
        metadata={
            "duckdb_path": dwh_publish.duckdb_path,
            "pg_schema": dwh_publish.schema_name,
            "dry_run": dwh_publish.dry_run,
            "tables": MetadataValue.json(tablas),
            "tables_count": len(tablas),
            "rows_published": filas,
        }
    )
