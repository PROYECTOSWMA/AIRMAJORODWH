"""Parsing puro del flujo aeronaves-from-sire (sin I/O).

El XML del comprobante ya viene extraído como texto por
``assets.from_sire_files_assets._common.file_extractor``; aquí solo se busca la
matrícula de aeronave ``OB-####`` (y, para petroperú, el aeropuerto del
``DatoAdicional`` de código 31) sobre ese ``str`` con regex.
"""

from __future__ import annotations

import re

# Patrón de matrícula de aeronave peruana: "OB" + 4 dígitos. El guion es
# opcional: en la práctica SUNAT lo emite con guion (CEP/PETROPERU, "OB-2092") y
# a veces sin guion (ICARO, "OB2092").
AERONAVE_RE = re.compile(r"OB-?\d{4}")

# ``DatoAdicional`` de código 31 de los comprobantes de PETROPERU: el ``Valor`` trae
# el aeropuerto, p. ej. ``PRINCIPAL AEROPUERTO) YARINACOCHA CORONEL PORTILLO Ucayali``.
_AEROPUERTO_RE = re.compile(
    r"<DatoAdicional>\s*<Codigo>\s*31\s*</Codigo>\s*<Valor>(.*?)</Valor>\s*</DatoAdicional>",
    re.DOTALL,
)


def parse_aeronave(xml: str) -> str | None:
    """Devuelve la primera aeronave ``OB-####`` del XML o ``None`` si no hay."""
    match = AERONAVE_RE.search(xml)
    return match.group(0) if match else None


def _strip_cdata(text: str) -> str:
    """Quita el envoltorio ``<![CDATA[ ... ]]>`` del ``Valor`` (si lo trae)."""
    text = text.strip()
    if text.startswith("<![CDATA["):
        text = text[len("<![CDATA[") :]
    if text.endswith("]]>"):
        text = text[: -len("]]>")]
    return text.strip()


def parse_aeropuerto(xml: str) -> tuple[str | None, str | None]:
    """Aeropuerto del ``DatoAdicional`` de código 31: ``(aeropuerto, completo)``.

    - ``aeropuerto`` es la **última palabra** del texto del ``Valor``
      (``"PRINCIPAL AEROPUERTO) YARINACOCHA CORONEL PORTILLO Ucayali"`` -> ``"Ucayali"``);
    - ``aeropuerto_completo`` es el texto completo del ``Valor``.

    Devuelve ``(None, None)`` si el XML no trae ese ``DatoAdicional``.
    """
    match = _AEROPUERTO_RE.search(xml)
    if match is None:
        return None, None
    completo = _strip_cdata(match.group(1))
    palabras = completo.split()
    if not palabras:
        return None, None
    return palabras[-1], completo
