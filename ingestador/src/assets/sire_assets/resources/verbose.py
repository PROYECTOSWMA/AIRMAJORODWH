"""Modo verboso compartido de los assets SIRE (``sire_details`` y ``sire_files``).

Una sola variable, ``SIRE_VERBOSE``, enciende el detalle documento a documento en
**ambos** assets (``sire_details_monthly`` y ``sire_files_monthly``); además cada uno
tiene la suya (``SIRE_DETAILS_VERBOSE`` / ``SIRE_FILES_VERBOSE``) para depurar solo
uno sin inundar el log del otro. Encienden el modo los valores
``1``/``true``/``yes``/``on``/``si``/``sí`` (sin distinguir mayúsculas ni espacios).

Vive aquí (y no en cada asset) para que la variable común y el parseo sean una sola
fuente de verdad. ``scripts/run_pipeline.py`` carga ``env/.env`` al arrancar, así que
basta con poner la variable ahí (o exportarla antes del run).
"""

from __future__ import annotations

import os

# Variable común: activa el modo verboso de todos los assets SIRE.
VERBOSE_ENV = "SIRE_VERBOSE"

# Variable por asset: activa solo el suyo, con independencia de la común.
VERBOSE_ENV_POR_ASSET = {
    "details": "SIRE_DETAILS_VERBOSE",
    "files": "SIRE_FILES_VERBOSE",
}

_VALORES_VERDADEROS = {"1", "true", "yes", "on", "si", "sí"}


def _es_verdadero(valor: str | None) -> bool:
    """``True`` si ``valor`` es uno de los que encienden el modo verboso."""
    return (valor or "").strip().lower() in _VALORES_VERDADEROS


def verbose_habilitado(asset: str) -> bool:
    """``True`` si ``asset`` debe loguear documento a documento.

    ``asset`` es la clave en ``VERBOSE_ENV_POR_ASSET`` (``"details"`` o ``"files"``).
    Se lee del entorno en cada llamada (no se cachea) para poder probarlo con
    ``monkeypatch`` y para que apagar la variable no exija reiniciar el proceso.
    """
    return _es_verdadero(os.environ.get(VERBOSE_ENV)) or _es_verdadero(
        os.environ.get(VERBOSE_ENV_POR_ASSET[asset])
    )
