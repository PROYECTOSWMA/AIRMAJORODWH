"""Parsing puro del flujo CORPAC (sin I/O): body del correo -> enlace, ZIP -> archivos.

Funciones puras sin conexión a datos fuera del programa: solo reciben strings/bytes
y devuelven strings/bytes. Por eso este módulo no es un resource.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile

# Enlace de comunicaciones CORPAC dentro del body del correo (verificado en BD: el
# body se guarda como HTML decodificado). El accessCode es base64-ish y puede traer
# `+`/`/`/`=`. En el HTML el `&` separador es literal (a veces `&amp;`).
_CORPAC_URL_RE = re.compile(
    r"https://www\.fedtt-peru\.com/MercurioCorpacPortal/Paginas/Comunicaciones\?"
    r"accessCode=([A-Za-z0-9+/=_-]+)&(?:amp;)?action=(\d+)"
)


def extract_corpac_url(body: str) -> str | None:
    """Extrae el enlace de comunicaciones CORPAC del body de un correo.

    Devuelve la URL canónica reconstruida (tolerante a ``&amp;`` del HTML) o ``None``
    si el body no trae el enlace.
    """
    match = _CORPAC_URL_RE.search(body or "")
    if not match:
        return None
    access_code, action = match.group(1), match.group(2)
    return (
        "https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones"
        f"?accessCode={access_code}&action={action}"
    )


def extract_zip_files(zip_bytes: bytes) -> list[dict[str, str]]:
    """Desempaqueta el ZIP de documentos y devuelve sus archivos.

    Cada entrada es ``{"filename": nombre, "data": contenido en base64}`` (la misma
    convención que ``email_attachments``/``sire_*_files``). Los directorios se ignoran.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return [
            {
                "filename": info.filename,
                "data": base64.b64encode(zf.read(info)).decode("ascii"),
            }
            for info in zf.infolist()
            if not info.is_dir()
        ]
