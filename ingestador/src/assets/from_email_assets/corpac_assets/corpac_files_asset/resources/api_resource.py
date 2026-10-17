"""Consulta del portal de comunicaciones CORPAC (Mercurio) con ``requests``.

Un correo CORPAC trae un enlace ``.../Comunicaciones?accessCode=...&action=1``; el
portal es un form estilo ASP.NET: se hace GET a ese enlace (la ``Session`` conserva
las cookies), se extraen los ``<input type=\"hidden\">`` y se hace POST al mismo URL
con esos campos más ``btnAdjuntos`` para obtener el ZIP de documentos (factura + OC).

Solo ``requests`` + stdlib (regex para los inputs ocultos): sin navegador headless.
"""

from __future__ import annotations

import re

import requests
from dagster import ConfigurableResource
from pydantic import Field

# El portal responde a un User-Agent de navegador; sin él puede devolver una página
# distinta o bloquear la descarga.
CORPAC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CORPAC_GET_TIMEOUT_SECONDS = 30
CORPAC_POST_TIMEOUT_SECONDS = 90

# Magic bytes de un ZIP (PK\\x03\\x04; los zips vacíos/spanned usan PK\\x05\\x06/\\x07\\x08).
_ZIP_MAGIC = b"PK"

# Tags <input> y atributos con comillas simples o dobles, en cualquier orden.
_INPUT_TAG_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"([\w:.-]+)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)


class CorpacZipError(Exception):
    """No se pudo obtener el ZIP del portal CORPAC (cae la materialización)."""


def extract_hidden_inputs(html: str) -> dict[str, str]:
    """Devuelve los campos ``<input type=\"hidden\">`` del HTML como dict name -> value.

    Regex (no ``html.parser``): más ligero y sin depender del orden de los atributos;
    maneja comillas simples y dobles. ``type`` se compara en minúsculas.
    """
    resultado: dict[str, str] = {}
    for tag in _INPUT_TAG_RE.finditer(html):
        attrs = {
            nombre.lower(): valor
            for nombre, _, valor in _ATTR_RE.findall(tag.group(0))
        }
        if attrs.get("type", "").lower() == "hidden" and attrs.get("name"):
            resultado[attrs["name"]] = attrs.get("value", "")
    return resultado


class CorpacResource(ConfigurableResource):
    """Resource que descarga el ZIP de documentos del portal CORPAC.

    ``download_zip`` hace GET al enlace de la comunicación, extrae los campos ocultos
    del form y hace POST con ``btnAdjuntos`` para obtener el ZIP. Devuelve los bytes
    del ZIP. Cualquier respuesta inesperada (red, HTTP != 200 o contenido que no es
    ZIP) lanza ``CorpacZipError``.
    """

    user_agent: str = Field(default=CORPAC_USER_AGENT)
    get_timeout: int = Field(default=CORPAC_GET_TIMEOUT_SECONDS)
    post_timeout: int = Field(default=CORPAC_POST_TIMEOUT_SECONDS)

    def download_zip(self, url: str) -> bytes:
        """POST al portal y retorna el ZIP de documentos (factura + OC)."""
        with requests.Session() as session:
            session.headers["User-Agent"] = self.user_agent

            try:
                respuesta = session.get(url, timeout=self.get_timeout)
            except requests.RequestException as exc:
                raise CorpacZipError(
                    f"No hubo respuesta del portal CORPAC en GET {url}: {exc}"
                ) from exc
            if respuesta.status_code != 200:
                raise CorpacZipError(
                    f"GET {url} devolvió HTTP {respuesta.status_code}: "
                    f"{respuesta.text[:500]}"
                )

            ocultos = extract_hidden_inputs(respuesta.text)
            datos = dict(ocultos)
            datos["btnAdjuntos"] = "Descargar Documentos"

            try:
                respuesta = session.post(
                    url,
                    data=datos,
                    headers={"Referer": url},
                    timeout=self.post_timeout,
                )
            except requests.RequestException as exc:
                raise CorpacZipError(
                    f"No hubo respuesta del portal CORPAC en POST {url}: {exc}"
                ) from exc
            if respuesta.status_code != 200:
                raise CorpacZipError(
                    f"POST {url} devolvió HTTP {respuesta.status_code}: "
                    f"{respuesta.text[:500]}"
                )

            contenido = respuesta.content
            if contenido[: len(_ZIP_MAGIC)] != _ZIP_MAGIC:
                raise CorpacZipError(
                    f"La respuesta del portal no es un ZIP de documentos (url={url})"
                )
            return contenido
