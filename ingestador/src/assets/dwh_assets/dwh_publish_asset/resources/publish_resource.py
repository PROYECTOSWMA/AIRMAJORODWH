"""Resource ``dwh_publish``: publica el DuckDB analítico en el schema ``dwh`` de PostgreSQL.

Aquí vive **todo** el motor de publicación (antes repartido entre este resource y un
``sync_db.py`` en la raíz que hacía de CLI):

- **Fuente**: ``analytics_poc.duckdb``, lo que materializa ``dbt_run`` (ver
  ``src/dbt/profiles.yml``). Se abre en SOLO LECTURA: no se escribe nada ahí.
- **Destino**: el schema de PostgreSQL (``dwh`` por defecto) con el MISMO nombre de tabla
  (``moves`` -> ``dwh.moves``). No hay lista de tablas hardcodeada ni mapeo de nombres: se
  recorren **todas** las tablas BASE del esquema ``main`` del DuckDB.
- Por tabla: la crea si no existe (tipos mapeados desde DuckDB), la vacía con ``DELETE`` y la
  vuelve a llenar completa con ``COPY``. **No** se hace ``DROP``: en el DWH cuelgan objetos
  (p. ej. la vista ``vw_move_reporte_gerencial``) y soltar la tabla los rompería. Con
  ``recreate`` sí se suelta y recrea (para cambios de TIPOS).
- Las tablas del schema destino que ya no existan en el DuckDB no se tocan: se listan al
  final como aviso.

Las **credenciales de PostgreSQL no se configuran aquí**: se leen del entorno (``PGHOST``
—admite ``host:puerto``—, ``PGPORT``, ``PGDATABASE``, ``PGUSER``, ``PGPASSWORD`` y
``PGDWH_SCHEMA`` para el schema), más ``env/.env`` de la raíz, que se carga al importar **sin
pisar** lo ya exportado. El proceso que ejecuta el run (cron, ``dagster dev``, daemon) tiene
que traerlas.

Uso manual desde la raíz del repo (``--dry-run`` NO escribe en PostgreSQL):

    python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py --dry-run
    python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py --only moves,calendar
    python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py --exclude dwh_movimientos
    python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py --recreate

En Dagster (lo normal, y con las deps del grafo):

    python -m dagster asset materialize -m definitions --select publish_dwh
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb
import psycopg
from dagster import ConfigurableResource
from dotenv import load_dotenv

# src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py -> parents[5] = repo
REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DUCKDB = REPO_ROOT / "analytics_poc.duckdb"
SOURCE_SCHEMA = "main"
DEFAULT_SCHEMA = "dwh"

# Credenciales del DWH: `env/.env` de la raíz, sin pisar lo que ya esté exportado.
_ENV_PATH = REPO_ROOT / "env" / ".env"
if _ENV_PATH.is_file():
    load_dotenv(dotenv_path=_ENV_PATH)


def schema_destino() -> str:
    """Schema de PostgreSQL donde se publica (``PGDWH_SCHEMA``, por defecto ``dwh``)."""
    return os.environ.get("PGDWH_SCHEMA", DEFAULT_SCHEMA)


def pg_params() -> dict[str, object]:
    """Credenciales del PostgreSQL de publicación (variables de entorno)."""
    host = os.environ.get("PGHOST", "localhost")
    inline_port = None
    # Tolerancia: si en PGHOST vienen "host:puerto" juntos, se separan.
    if ":" in host and not host.startswith("["):
        host, inline_port = host.split(":", 1)
    return {
        "host": host,
        # 5432 = puerto estándar de PostgreSQL; el DWH real lo fija con PGPORT (5447).
        "port": int(inline_port or os.environ.get("PGPORT", "5432")),
        "dbname": os.environ.get("PGDATABASE", "postgres"),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
    }


# ---------------------------------------------------------------------------
# DuckDB -> PostgreSQL (tipos)
# ---------------------------------------------------------------------------
_SIMPLE_TYPES = {
    "BOOLEAN": "BOOLEAN",
    "TINYINT": "SMALLINT",
    "SMALLINT": "SMALLINT",
    "INTEGER": "INTEGER",
    "BIGINT": "BIGINT",
    "HUGEINT": "NUMERIC(38,0)",
    "UTINYINT": "SMALLINT",
    "USMALLINT": "INTEGER",
    "UINTEGER": "BIGINT",
    "UBIGINT": "NUMERIC(20,0)",
    "REAL": "REAL",
    "FLOAT": "REAL",
    "DOUBLE": "DOUBLE PRECISION",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIME WITH TIME ZONE": "TIMETZ",
    "TIMESTAMP": "TIMESTAMP",
    "TIMESTAMP_S": "TIMESTAMP",
    "TIMESTAMP_MS": "TIMESTAMP",
    "TIMESTAMP_NS": "TIMESTAMP",
    "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
    "VARCHAR": "TEXT",
    "BLOB": "BYTEA",
    "UUID": "UUID",
    "JSON": "JSONB",
}


def pg_type(duck_type: str) -> str:
    """Tipo de Postgres equivalente al tipo de DuckDB (TEXT como último recurso)."""
    upper = duck_type.upper().strip()
    base = upper.split("(", 1)[0].strip()
    if base in ("DECIMAL", "NUMERIC"):
        inner = upper[upper.find("(") + 1 : upper.rfind(")")] if "(" in upper else ""
        return f"NUMERIC({inner})" if inner else "NUMERIC"
    return _SIMPLE_TYPES.get(base, "TEXT")


# ---------------------------------------------------------------------------
# Metadatos (DuckDB y PostgreSQL)
# ---------------------------------------------------------------------------
def duckdb_connect(path: str | Path) -> duckdb.DuckDBPyConnection:
    """Abre el DuckDB de origen en **solo lectura**, con plan B para el mismo proceso.

    La publicación solo **lee** del DuckDB, así que lo normal es ``read_only=True`` (y así
    el error de "otro proceso lo tiene abierto" sale como error de lock, que se diagnostica
    bien). Pero cuando ``dbt_run`` y ``publish_dwh`` corren en el **mismo proceso**
    (``scripts/run_pipeline.py`` usa el executor in-process), dbt ya dejó el fichero abierto
    en lectura-escritura y DuckDB **no permite** abrirlo otra vez con otra configuración::

        Connection Error: Can't open a connection to same database file with a
        different configuration than existing connections

    En ese caso se reabre con la configuración que ya existe (lectura-escritura): es la
    misma instancia DuckDB del proceso, así que no hay ningún lock que pelear. Cualquier
    otro error (p. ej. el lock porque lo tiene abierto otro proceso) se propaga tal cual.
    """
    try:
        return duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:
        if "different configuration" not in str(exc):
            raise
        return duckdb.connect(str(path))


def duckdb_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Tablas BASE del esquema ``main`` del DuckDB (solo el catálogo propio)."""
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_catalog = current_database() "
        "AND table_schema = ? AND table_type = 'BASE TABLE' "
        "ORDER BY table_name",
        [SOURCE_SCHEMA],
    ).fetchall()
    return [r[0] for r in rows]


def duckdb_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    """Columnas ``(nombre, tipo DuckDB)`` de una tabla, en su orden."""
    return con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_catalog = current_database() "
        "AND table_schema = ? AND table_name = ? "
        "ORDER BY ordinal_position",
        [SOURCE_SCHEMA, table],
    ).fetchall()


def pg_tables(cur: psycopg.Cursor, schema: str) -> set[str]:
    """Tablas que ya existen en el schema destino."""
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (schema,),
    )
    return {r[0] for r in cur.fetchall()}


def pg_columns(cur: psycopg.Cursor, schema: str, table: str) -> list[str]:
    """Columnas que ya tiene la tabla destino (lista vacía si no existe)."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (schema, table),
    )
    return [r[0] for r in cur.fetchall()]



# ---------------------------------------------------------------------------
# Sincronización
# ---------------------------------------------------------------------------
def sync_table(
    con: duckdb.DuckDBPyConnection,
    conn: psycopg.Connection,
    table: str,
    *,
    schema: str,
    dry_run: bool = False,
    recreate: bool = False,
) -> int:
    """Vuelca ``table`` del DuckDB a ``"<schema>"."<table>"``. Devuelve las filas copiadas.

    Con ``recreate=True`` la tabla destino se suelta y se vuelve a crear: es lo que hace
    falta cuando cambian los TIPOS de las columnas (el ``CREATE TABLE IF NOT EXISTS`` no los
    toca). Ojo: solo para tablas sin vistas/objetos que dependan de ellas.
    """
    columns = duckdb_columns(con, table)
    if not columns:
        print(f"  !! {table}: sin columnas en DuckDB, se omite")
        return 0
    names = [c for c, _ in columns]

    # 1) Crear la tabla destino (o añadirle las columnas que le falten).
    with conn.cursor() as cur:
        if recreate:
            print(f'  DROP + CREATE de "{schema}"."{table}" (--recreate)')
            if not dry_run:
                cur.execute(f'DROP TABLE IF EXISTS "{schema}"."{table}"')
        existing = pg_columns(cur, schema, table)
        if not existing:
            col_defs = ", ".join(f'"{c}" {pg_type(t)}' for c, t in columns)
            print(f'  creando "{schema}"."{table}" ({len(columns)} columnas)')
            if not dry_run:
                cur.execute(f'CREATE TABLE "{schema}"."{table}" ({col_defs})')
        else:
            tipos = dict(columns)
            faltan = [c for c in names if c not in existing]
            if faltan:
                print(f"  {table}: + columnas nuevas: {', '.join(faltan)}")
                if not dry_run:
                    for c in faltan:
                        cur.execute(
                            f'ALTER TABLE "{schema}"."{table}" '
                            f'ADD COLUMN IF NOT EXISTS "{c}" {pg_type(tipos[c])}'
                        )
            sobran = [c for c in existing if c not in names]
            if sobran:
                print(
                    f"  (aviso) {table}: el DWH tiene columnas que DuckDB no trae "
                    f"(no se tocan): {', '.join(sobran)}"
                )

    # 2) Leer del DuckDB y copiar con COPY (rápido). psycopg adapta los tipos:
    #    Decimal -> NUMERIC, date/datetime -> DATE/TIMESTAMP, None -> NULL...
    cols_sql = ", ".join(f'"{c}"' for c in names)
    rows = con.execute(f'SELECT {cols_sql} FROM "{SOURCE_SCHEMA}"."{table}"').fetchall()

    if dry_run:
        print(f'  [dry-run] {len(rows)} filas -> "{schema}"."{table}"')
        return len(rows)

    # 3) DELETE y no DROP: las vistas del DWH (p. ej. vw_move_reporte_gerencial)
    #    dependen de las tablas y un DROP las dejaría inválidas.
    with conn.cursor() as cur:
        cur.execute(f'DELETE FROM "{schema}"."{table}"')
    if rows:
        with conn.cursor() as cur:
            with cur.copy(f'COPY "{schema}"."{table}" ({cols_sql}) FROM STDIN') as copy:
                for row in rows:
                    copy.write_row(row)
    conn.commit()
    print(f'  {len(rows)} filas -> "{schema}"."{table}"')
    return len(rows)


def seleccionar_tablas(tablas: list[str], only: str | None, exclude: str | None) -> list[str]:
    """Aplica ``--only`` / ``--exclude`` (listas separadas por comas) a las tablas BASE."""
    if only:
        queridas = {t.strip() for t in only.split(",") if t.strip()}
        tablas = [t for t in tablas if t in queridas]
    if exclude:
        fuera = {t.strip() for t in exclude.split(",") if t.strip()}
        tablas = [t for t in tablas if t not in fuera]
    return tablas



class DwhPublishError(RuntimeError):
    """Falla de la publicación a PostgreSQL (derrumba la materialización de ``publish_dwh``)."""

    codigo_salida = 1


class DuckdbNoDisponibleError(DwhPublishError):
    """No se pudo abrir el DuckDB (no existe, o lo tiene bloqueado otro proceso)."""

    codigo_salida = 2


def publicar(
    *,
    duckdb_path: str | Path,
    schema: str,
    only: str | None = None,
    exclude: str | None = None,
    dry_run: bool = False,
    recreate: bool = False,
) -> int:
    """Publica el DuckDB (completo o el subconjunto pedido) y devuelve las filas copiadas.

    Lanza ``DuckdbNoDisponibleError`` (código 2) si no se puede abrir el DuckDB y
    ``DwhPublishError`` (código 1) si no hay nada que publicar.
    """
    ruta = Path(duckdb_path).expanduser().resolve()
    if not ruta.exists():
        raise DuckdbNoDisponibleError(f"No existe el DuckDB: {ruta}")
    try:
        con = duckdb_connect(ruta)
    except duckdb.Error as exc:
        raise DuckdbNoDisponibleError(
            f"No se pudo abrir {ruta}.\nDuckDB abre el fichero en EXCLUSIVA: cierra DBeaver "
            f"(u otro proceso) que lo tenga abierto.\n  {exc}"
        ) from exc

    try:
        tablas = seleccionar_tablas(duckdb_tables(con), only, exclude)
        if not tablas:
            raise DwhPublishError(f"No hay tablas BASE que publicar en {ruta.name}.")

        pg = pg_params()
        print(f"Origen : {ruta}  (esquema {SOURCE_SCHEMA}, {len(tablas)} tablas)")
        for tabla in tablas:
            print(f"         - {tabla}")
        print(f'Destino: {pg["host"]}:{pg["port"]}/{pg["dbname"]}  ->  esquema "{schema}"')
        if dry_run:
            print("(dry-run: no se escribe nada)")
        print()

        total = 0
        with psycopg.connect(**pg, connect_timeout=30) as conn:
            if not dry_run:
                with conn.cursor() as cur:
                    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                conn.commit()
            for tabla in tablas:
                total += sync_table(
                    con, conn, tabla, schema=schema, dry_run=dry_run, recreate=recreate
                )

            # Aviso: tablas del schema destino que ya no están en el DuckDB.
            with conn.cursor() as cur:
                huerfanas = sorted(pg_tables(cur, schema) - set(duckdb_tables(con)))

        if huerfanas:
            print()
            print(f'Aviso: hay tablas en "{schema}" que ya NO están en el DuckDB (no se tocan):')
            for tabla in huerfanas:
                print(f"  - {schema}.{tabla}")

        print()
        print(
            f'Listo: {len(tablas)} tablas y {total} filas publicadas en el esquema "{schema}".'
        )
        return total
    finally:
        con.close()



class DwhPublishResource(ConfigurableResource):
    """Publica (copia) las tablas del DuckDB en el schema configurado de PostgreSQL."""

    duckdb_path: str = str(DEFAULT_DUCKDB)
    # Por defecto, lo mismo que el CLI: `PGDWH_SCHEMA` (o "dwh") leído al importar.
    schema_name: str = schema_destino()
    only: str | None = None
    exclude: str | None = None
    dry_run: bool = False
    recreate: bool = False

    def tables(self) -> list[str]:
        """Tablas BASE del DuckDB que se van a publicar (ya con ``only``/``exclude``).

        Usa ``duckdb_connect`` (no un ``duckdb.connect`` a pelo): cuando ``dbt_run`` ya abrió
        el fichero en este mismo proceso, DuckDB rechaza una segunda conexión con otra
        configuración y hay que reabrir con la existente.
        """
        try:
            con = duckdb_connect(self.duckdb_path)
        except duckdb.Error as exc:
            raise DuckdbNoDisponibleError(
                f"No se pudo abrir el DuckDB '{self.duckdb_path}': {exc}\n"
                "DuckDB abre el fichero en EXCLUSIVA: cierra DBeaver (u otro proceso) que lo "
                "tenga abierto y materializa antes `dbt_run` (es quien crea el fichero)."
            ) from exc
        try:
            return seleccionar_tablas(duckdb_tables(con), self.only, self.exclude)
        finally:
            con.close()

    def publish(self) -> int:
        """Publica el DuckDB en Postgres y devuelve las **filas** copiadas."""
        return publicar(
            duckdb_path=self.duckdb_path,
            schema=self.schema_name,
            only=self.only,
            exclude=self.exclude,
            dry_run=self.dry_run,
            recreate=self.recreate,
        )


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Publica todas las tablas del DuckDB en el schema de PostgreSQL (mismo nombre)."
        )
    )
    parser.add_argument(
        "--duckdb",
        default=str(DEFAULT_DUCKDB),
        help=f"ruta del DuckDB de origen (por defecto {DEFAULT_DUCKDB})",
    )
    parser.add_argument(
        "--schema",
        default=schema_destino(),
        help=f'schema destino en PostgreSQL (por defecto {schema_destino()!r}, o PGDWH_SCHEMA)',
    )
    parser.add_argument("--only", default=None, help="publicar solo estas tablas (separadas por comas)")
    parser.add_argument(
        "--exclude", default=None, help="no publicar estas tablas (separadas por comas)"
    )
    parser.add_argument("--dry-run", action="store_true", help="no escribe nada en PostgreSQL")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="DROP + CREATE de las tablas seleccionadas (para cambios de TIPOS; "
        "solo si nada depende de ellas)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI del motor de publicación: 0 = OK, 1 = nada que publicar, 2 = sin DuckDB."""
    args = _parse(argv)
    try:
        publicar(
            duckdb_path=args.duckdb,
            schema=args.schema,
            only=args.only,
            exclude=args.exclude,
            dry_run=args.dry_run,
            recreate=args.recreate,
        )
    except DwhPublishError as exc:
        print(exc, file=sys.stderr)
        return exc.codigo_salida
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

