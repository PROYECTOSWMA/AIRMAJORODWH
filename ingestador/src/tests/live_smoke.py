"""Smoke test EN VIVO contra SUNAT SIRE (pide el token a la API de seguridad).

No lo recoge pytest (no tiene prefijo test_). Ejecutar a mano desde la raíz del repo:

    python src/tests/live_smoke.py 202607

OJO: SUNAT limita por tasa (429) la creacion de tickets. No lo corras repetidas veces
seguidas.
"""

import io
import os
import sys
import threading
import zipfile

# Este script vive en <repo>/src/tests: `src/` tiene los paquetes (`assets`) y la raíz
# tiene `definitions.py` / `env/.env`.
_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_SRC)
for _ruta in (_SRC, _REPO_ROOT):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

from assets.sire_assets.resources.token_resource import (  # noqa: E402
    AUDIENCE_SIRE,
    RECURSO_MIGEIGV,
    SireTokenError,
    SireTokenResource,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.proposal_resource import (  # noqa: E402
    read_zip,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.ticket_resource import (  # noqa: E402
    TicketResource,
)


def main(periodo: str, timeout_seconds: int = 600, empresa: str = "Air Majoro"):
    token = SireTokenResource()
    try:
        token.token(empresa, audience=AUDIENCE_SIRE, recurso=RECURSO_MIGEIGV)
    except SireTokenError as exc:
        raise SystemExit(f"Sin token valido para '{empresa}': {exc}")

    ticket = TicketResource(token_resource=token)
    result = {}
    error = {}

    def worker():
        try:
            result["zip"] = ticket.get_zip(periodo, poll_seconds=10, empresa=empresa)
        except Exception as exc:  # noqa: BLE001
            error["exc"] = exc

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(timeout=timeout_seconds)
    if th.is_alive():
        raise SystemExit(f"TIMEOUT: el reporte no termino en {timeout_seconds}s")
    if error:
        raise error["exc"]

    zip_bytes = result["zip"]
    print("zip bytes:", len(zip_bytes))
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in [n for n in zf.namelist() if not n.endswith("/")]:
            print(f"  {name}: {len(zf.read(name))} bytes")

    rows = read_zip(zip_bytes)
    print(f"filas CSV: {len(rows)}")
    if rows:
        print("columnas:", list(rows[0].keys()))


if __name__ == "__main__":
    periodo = sys.argv[1] if len(sys.argv) > 1 else "202607"
    main(periodo)
