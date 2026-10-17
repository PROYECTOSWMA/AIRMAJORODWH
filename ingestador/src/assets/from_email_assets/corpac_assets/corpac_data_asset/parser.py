"""Parsing del PDF CORPAC ``01-*.pdf`` de detalle de servicios (sin I/O).

Cada PDF es una factura de servicios de aeronavegación con una cabecera
(``FACTURA``, ``FECHA DOC.``, ``Fch.Impresión``, ``Hora``, ``Página``,
``CLIENTE``, ``MATRICULA``, ``TIPO AERONAVE``, ``PMD(TM)``) y una tabla de
detalle de 11 columnas.

El PDF dibuja los **bordes de celda** de la tabla en posiciones fijas
(verificadas idénticas en 16+ PDFs de 12 series, incluidas las multipágina),
así que cada palabra se clasifica por el **centro de su caja** dentro del
rango X de su columna. No se parsea el texto en orden de lectura sino por
coordenadas: eso distingue de forma inequívoca SERVICIO vs. ORIGEN vs.
DESTINO vs. VUELO LLEGADA vs. VUELO SALIDA vs. RUTA.

Casos especiales manejados:
- La ruta aérea es texto variable multi-palabra (``DCT MULAN AMVEX V18``,
  ``RUTA KM VARIABLE``, ``SPCL DCT SPAY``...).
- A veces la ruta y el KM salen pegados en un solo token que cruza el límite
  de columna (``UT332/UT323123.32`` -> ruta ``UT332/UT32`` + km ``3123.32``):
  se parte por el número decimal final.
- El precio lleva moneda (``S/`` soles o ``US$``) + monto; se guardan por
  separado.
- Cada fila puede traer VUELO LLEGADA, VUELO SALIDA, ambos o ninguno.
- La cabecera se repite en cada página de los multipágina; se lee de la
  primera página y las filas de detalle se juntan de todas las páginas.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

# Límites X de las columnas de detalle (bordes de celda reales del PDF).
# (nombre, x0, x1)
_DETAIL_COLUMNS: list[tuple[str, float, float]] = [
    ("servicio", 21.1, 176.5),
    ("origen", 176.5, 215.1),
    ("destino", 215.1, 252.9),
    ("vuelo_llegada", 252.9, 303.6),
    ("vuelo_salida", 303.6, 355.3),
    ("ruta", 355.3, 440.4),
    ("km", 440.4, 492.7),
    ("fecha_llegada", 492.7, 590.1),
    ("fecha_salida", 590.1, 687.8),
    ("min", 687.8, 724.2),
    ("precio", 724.2, 801.0),
]

# Límite entre RUTA AEREA y TOTAL KM: un token que lo cruce y termine en
# número decimal se parte (ruta + km pegados).
_RUTA_KM_X = 440.4

# El texto del TOTAL KM arranca en la misma X en todas las filas (columna
# alineada a la izquierda). Se mide por página como la mediana del x0 de los
# valores de km puros; la ruta, si es muy larga, se pega al km
# (``UT332/UT323123.32``) y solo se parte bien por posición de caracteres.
_KM_TEXT_X = 464.4

# Número puro con 2 decimales (típico del TOTAL KM): "274.72", "1,039.70".
_PURE_NUMBER_RE = re.compile(r"^\d[\d,]*\.\d{2}$")

# Número decimal final (admite separador de miles): "3123.32" en
# "UT332/UT323123.32" o "1,039.70". Solo es fallback: si hay caracteres
# disponibles se parte por posición (``_KM_TEXT_X``), que es inequívoco.
_KM_RE = re.compile(r"([\d][\d,]*\.\d+)\s*$")

# Monedas que pueden acompañar al precio unitario.
_MONEDAS = ("S/", "US$")

# Las filas de datos empiezan justo debajo de la línea de MATRICULA (que
# termina en top ~93.3). Los encabezados de tabla (~58-77) quedan fuera.
_DATA_TOP_MIN = 95.0


class CorpacDataParseError(Exception):
    """El PDF no se pudo parsear como factura CORPAC de servicios."""


def _column_name(center: float) -> str | None:
    """Columna de detalle a la que pertenece el centro X de una palabra."""
    for name, x0, x1 in _DETAIL_COLUMNS:
        if x0 <= center < x1:
            return name
    return None


def _split_route_km(text: str) -> tuple[str, str] | None:
    """Parte un token pegado ruta+km: ``UT332/UT323123.32`` -> (``UT332/UT32``, ``3123.32``).

    Devuelve ``None`` si el token no termina en un número decimal.
    """
    match = _KM_RE.search(text)
    if not match:
        return None
    ruta = text[: match.start()].rstrip()
    if not ruta:
        return None
    return ruta, match.group(1).replace(",", "")


def _measure_km_text_start(words: list[dict[str, Any]]) -> float:
    """X donde empieza el texto del TOTAL KM (mediana de los km puros de la página).

    Los valores de km (p. ej. ``274.72``) comparten columna alineada a la
    izquierda; su mediana es el punto donde arranca el km en cualquier fila.
    """
    starts = [
        w["x0"]
        for w in words
        if _PURE_NUMBER_RE.match(w["text"])
        and 440.4 <= (w["x0"] + w["x1"]) / 2 < 492.7
    ]
    if not starts:
        return _KM_TEXT_X
    starts.sort()
    return starts[len(starts) // 2]


def _split_route_km_by_chars(
    word: dict[str, Any],
    page_chars: list[dict[str, Any]],
    km_text_x: float,
) -> tuple[str, str] | None:
    """Parte por **posición de caracteres** un token que cruza el límite ruta|KM.

    El KM arranca en ``km_text_x`` y el texto de la ruta queda a la izquierda
    (aunque se solape con la columna KM). Sin esta distinción espacial el split
    textual es ambiguo: ``UT332/UT323123.32`` admite ``UT332/UT3``+``23123.32``
    o ``UT332/UT32``+``3123.32``; el umbral se pone medio punto antes del
    inicio del km para absorber la tolerancia del render.
    """
    chars = [
        c
        for c in page_chars
        if word["top"] - 1.0 <= c["top"] <= word["bottom"] + 1.0
        and word["x0"] - 1.0 <= c["x0"] <= word["x1"] + 1.0
    ]
    if not chars:
        return None
    chars.sort(key=lambda c: (c["x0"], c["x1"]))
    umbral = km_text_x - 0.5
    ruta = "".join(c["text"] for c in chars if c["x0"] < umbral).strip()
    km = "".join(c["text"] for c in chars if c["x0"] >= umbral).strip()
    if not ruta or not km:
        return None
    return ruta, km.replace(",", "")


def _as_decimal(text: str) -> Decimal | None:
    """Convierte un texto numérico a Decimal(2). ``None`` si no es numérico."""
    limpio = (text or "").strip().replace(",", "").replace("S/", "").replace("US$", "")
    if not limpio:
        return None
    try:
        return Decimal(limpio).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
def _parse_header(words: list[dict[str, Any]]) -> dict[str, str]:
    """Cabecera de la factura: busca cada etiqueta y lee el valor de su línea.

    Solo se miran las palabras de la **zona de cabecera** (``top`` por encima
    de la tabla, antes de las filas de detalle): las líneas ``MATRICULA:`` que
    aparecen intercaladas dentro de la tabla (facturas con varias aeronaves)
    no deben sobreescribir la aeronave de la cabecera.
    """
    result: dict[str, str] = {
        "factura": "",
        "fecha_doc": "",
        "fch_impresion": "",
        "hora": "",
        "cliente": "",
        "pagina": "",
        "matricula": "",
        "tipo_aeronave": "",
        "pmd": "",
    }

    lineas: dict[float, list[tuple[float, str]]] = defaultdict(list)
    for w in words:
        if w["top"] >= _DATA_TOP_MIN:
            continue  # filas de la tabla: no son cabecera
        # Etiqueta y valor comparten línea visual aunque sus ``top`` difieran
        # décimas (p. ej. Fch.Impresión: 21.8 vs valor 21.5). Redondear al
        # entero agrupa la misma línea: las líneas reales distan >= 12pt.
        lineas[round(w["top"])].append((w["x0"], w["text"]))
    for tokens in lineas.values():
        tokens.sort(key=lambda t: t[0])
        textos = [t for _, t in tokens]

        if "Fch.Impresión:" in textos:
            i = textos.index("Fch.Impresión:")
            if i + 1 < len(textos):
                result["fch_impresion"] = textos[i + 1]
        if "FACTURA" in textos:
            i = textos.index("FACTURA")
            if i + 1 < len(textos):
                result["factura"] = textos[i + 1]
        if "DOC.:" in textos:
            i = textos.index("DOC.:")
            if i + 1 < len(textos):
                result["fecha_doc"] = textos[i + 1]
        if "Hora:" in textos:
            i = textos.index("Hora:")
            if i + 1 < len(textos):
                result["hora"] = textos[i + 1]
        if "CLIENTE" in textos:
            i = textos.index("CLIENTE")
            resto = textos[i + 1 :]
            if resto and resto[0] == ":":
                resto = resto[1:]
            cliente: list[str] = []
            for t in resto:
                if t == "Página:":
                    break
                cliente.append(t)
            result["cliente"] = " ".join(cliente)
        if "Página:" in textos:
            i = textos.index("Página:")
            result["pagina"] = " ".join(textos[i + 1 : i + 4])
        if "MATRICULA:" in textos:
            i = textos.index("MATRICULA:")
            vals: list[str] = []
            for t in textos[i + 1 :]:
                if t == "TIPO":
                    break
                vals.append(t)
            result["matricula"] = " ".join(vals)
        if "AERONAVE:" in textos:
            i = textos.index("AERONAVE:")
            vals = []
            for t in textos[i + 1 :]:
                if t == "PMD(TM):":
                    break
                vals.append(t)
            result["tipo_aeronave"] = " ".join(vals)
        if "PMD(TM):" in textos:
            i = textos.index("PMD(TM):")
            if i + 1 < len(textos):
                result["pmd"] = textos[i + 1]

    return result


def _page_bands(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Agrupa las palabras de una página por banda vertical (ordenadas por X).

    Cada fila de datos comparte el mismo ``top`` (las filas distan ~13pt, así
    que redondear al entero no las fusiona). Las líneas de cabecera (encabezado
    de tabla, ``ANEXO``...) quedan fuera por el umbral ``_DATA_TOP_MIN``.
    """
    bandas: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for w in words:
        if w["top"] < _DATA_TOP_MIN:
            continue
        bandas[round(w["top"])].append(w)
    return [sorted(bandas[top], key=lambda w: w["x0"]) for top in sorted(bandas)]


def _parse_aircraft_line(words: list[dict[str, Any]]) -> dict[str, str]:
    """Lee ``MATRICULA`` / ``TIPO AERONAVE`` / ``PMD(TM)`` de una línea.

    Dentro de la tabla puede haber una línea de aeronave por cada sección (una
    factura puede facturar a varias matrículas); también es la línea que se
    repite en cada página de los multipágina.
    """
    result = {"matricula": "", "tipo_aeronave": "", "pmd": ""}
    textos = [w["text"] for w in words]
    if "MATRICULA:" in textos:
        i = textos.index("MATRICULA:")
        vals: list[str] = []
        for t in textos[i + 1 :]:
            if t == "TIPO":
                break
            vals.append(t)
        result["matricula"] = " ".join(vals)
    if "AERONAVE:" in textos:
        i = textos.index("AERONAVE:")
        vals = []
        for t in textos[i + 1 :]:
            if t == "PMD(TM):":
                break
            vals.append(t)
        result["tipo_aeronave"] = " ".join(vals)
    if "PMD(TM):" in textos:
        i = textos.index("PMD(TM):")
        if i + 1 < len(textos):
            result["pmd"] = textos[i + 1]
    return result


def _build_detail_record(
    words: list[dict[str, Any]],
    page_chars: list[dict[str, Any]],
    km_text_x: float,
) -> dict[str, Any] | None:
    """Clasifica las palabras de una fila por columna y arma el registro."""
    por_columna: dict[str, list[str]] = {name: [] for name, _, _ in _DETAIL_COLUMNS}

    for w in words:
        text = w["text"]
        x0, x1 = w["x0"], w["x1"]

        # Token pegado ruta+km que cruza el límite de la columna KM: se parte
        # por posición de caracteres (inequívoco) y por regex como fallback.
        if x0 < _RUTA_KM_X <= x1:
            partido = _split_route_km_by_chars(w, page_chars, km_text_x) or _split_route_km(
                text
            )
            if partido:
                ruta, km = partido
                por_columna["ruta"].append(ruta)
                por_columna["km"].append(km)
                continue

        nombre = _column_name((x0 + x1) / 2)
        if nombre:
            por_columna[nombre].append(text)

    servicio = " ".join(por_columna["servicio"])
    origen = " ".join(por_columna["origen"])
    destino = " ".join(por_columna["destino"])
    vuelo_llegada = " ".join(por_columna["vuelo_llegada"])
    vuelo_salida = " ".join(por_columna["vuelo_salida"])
    ruta = " ".join(por_columna["ruta"])
    km_text = " ".join(por_columna["km"])
    fecha_llegada = " ".join(por_columna["fecha_llegada"])
    fecha_salida = " ".join(por_columna["fecha_salida"])
    total_min = " ".join(por_columna["min"])

    moneda = ""
    precio_text = ""
    for t in por_columna["precio"]:
        if t in _MONEDAS:
            moneda = t
        else:
            precio_text = t

    # Fila válida: debe tener al menos una columna de datos reales.
    if not any(
        (origen, destino, vuelo_llegada, vuelo_salida, ruta, km_text, fecha_llegada)
    ):
        return None

    return {
        "servicio": servicio,
        "aeropuerto_origen": origen,
        "aeropuerto_destino": destino,
        "vuelo_llegada": vuelo_llegada,
        "vuelo_salida": vuelo_salida,
        "ruta_aerea": ruta,
        "total_km": _as_decimal(km_text),
        "fecha_llegada": fecha_llegada,
        "fecha_salida": fecha_salida,
        "total_min": total_min,
        "moneda": moneda,
        "precio_unitario": _as_decimal(precio_text),
    }


def parse_invoice_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    """Parsea un PDF ``01-*.pdf`` y devuelve ``{"headers": [...], "details": [...]}``.

    La cabecera de factura (``FACTURA``, ``FECHA DOC.``, ``Fch.Impresión``,
    ``Hora``, ``Página``, ``CLIENTE``) se lee de la primera página. Dentro de
    la tabla puede haber **una línea de aeronave por sección** (una factura
    puede facturar a varias matrículas, p. ej. ``MATRICULA: OB-2092P ...``
    intercalada en la tabla): se genera una cabecera por sección con su
    ``matricula``/``tipo_aeronave``/``pmd`` y cada fila de detalle apunta a su
    sección con ``_section`` (índice en ``headers``).

    Las filas de detalle se juntan de todas las páginas (en los multipágina la
    línea de aeronave se repite; si es la misma no abre nueva sección).
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                raise CorpacDataParseError("PDF sin páginas")
            base = _parse_header(pdf.pages[0].extract_words())

            # Sección inicial: la aeronave de la cabecera de la página 1.
            sections: list[dict[str, str]] = [
                {
                    "matricula": base["matricula"],
                    "tipo_aeronave": base["tipo_aeronave"],
                    "pmd": base["pmd"],
                }
            ]
            current = 0
            details: list[dict[str, Any]] = []

            for page in pdf.pages:
                words = page.extract_words()
                page_chars = page.chars
                km_text_x = _measure_km_text_start(words)

                for ws in _page_bands(words):
                    textos = [w["text"] for w in ws]

                    # Línea de aeronave: abre nueva sección si es distinta de la
                    # actual (la repetición de página de los multipágina no).
                    if "MATRICULA:" in textos:
                        aeronave = _parse_aircraft_line(ws)
                        if aeronave != sections[current]:
                            sections.append(aeronave)
                            current = len(sections) - 1
                        continue

                    # Total del documento: no es una fila de detalle.
                    if any(t == "TOTAL:" for t in textos):
                        continue

                    registro = _build_detail_record(ws, page_chars, km_text_x)
                    if registro is not None:
                        registro["_section"] = current
                        details.append(registro)
    except CorpacDataParseError:
        raise
    except Exception as exc:  # PDF corrupto / no es PDF
        raise CorpacDataParseError(f"no se pudo abrir el PDF: {exc}") from exc

    if not base.get("factura"):
        raise CorpacDataParseError(
            "no se encontró la etiqueta FACTURA en la cabecera del PDF"
        )

    headers = [
        {
            "factura": base["factura"],
            "fecha_doc": base["fecha_doc"],
            "fch_impresion": base["fch_impresion"],
            "hora": base["hora"],
            "pagina": base["pagina"],
            "cliente": base["cliente"],
            "matricula": seccion["matricula"],
            "tipo_aeronave": seccion["tipo_aeronave"],
            "pmd": seccion["pmd"],
        }
        for seccion in sections
    ]

    return {"headers": headers, "details": details}
