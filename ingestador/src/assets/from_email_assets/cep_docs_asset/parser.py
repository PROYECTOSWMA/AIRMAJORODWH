"""Parsing del PDF de factura de combustible de CEP (sin I/O).

Cada correo de ``fe.corporacion.energetico@gmail.com`` (CONSORCIO ENERGÉTICO DEL
PERÚ S.A., RUC 20613566881) trae la factura en PDF (y su XML). El PDF dibuja una
cabecera con los datos del comprobante y una tabla de detalle de combustible::

    SEÑOR (ES) : AIR MAJORO S.A.        FECHA DE EMISIÓN : 31/12/2025
    DIRECCION : AV ARGENTINA NRO 4065 ZI CALLAO   R.U.C. : 20494626978
    COD DEL CLIENTE N° DE GUIA COD VENDEDOR COND. PAGO MONEDA O/C
    NZA/SPZA        2          115984       Contado    DOLARES 2009689
    CODIGO CANT. DESCRIPCION U.M. VALOR UNIT. PRECIO UNIT. VALOR VENTA
    AV     20.00 AV GAS 100LL GLL 11.2200    13.2396      224.40
    TRANSPORTISTA : AIR MAJORO S.A.   CHOFER :PILMER D. CESPEDES LOZANO
    SON :DOSCIENTOS SESENTA Y CUATRO Y 79/100 DOLARES AMERICANOS
    PLACA   OP GRAVADAS OP EXONERADAS IGV (18%) IMPORTE TOTAL
    OB-1919 $ 224.40    $ 0.00        $ 40.39  $ 264.79
    CODIGO SCOP : 12634330075

El parseo es **por líneas**: se localiza cada línea de etiquetas conocida
(cabecera, detalle, PLACA) y se leen los valores de la línea siguiente. Es
tolerante a la dirección partida en dos líneas (el `wrap` de la columna) porque
los valores se localizan por su etiqueta, no por posición. Los importes se
convierten a ``Decimal`` (``None`` cuando la celda viene vacía o inválida).

Si no se encuentra la cabecera esperada se lanza ``CepDocsParseError`` y el asset
derrumba la partición (fail-fast).
"""

from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber


class CepDocsParseError(Exception):
    """El PDF no se pudo parsear como factura de combustible de CEP."""


# Número de factura: letra + 3 dígitos de serie + guion + correlativo.
_FACTURA_RE = re.compile(r"\b([A-Z]\d{3}-\d{4,8})\b")

# Etiquetas de la cabecera.
_FECHA_RE = re.compile(r"FECHA DE EMISI[OÓ]N\s*:\s*(\d{1,2}/\d{1,2}/\d{4})")
_CLIENTE_RE = re.compile(
    r"SE[ÑN]OR\s*\(ES\)\s*:\s*(.*?)\s+FECHA DE EMISI[OÓ]N", re.IGNORECASE
)
_RUC_RE = re.compile(r"R\.?\s*U\.?\s*C\.?\s*:\s*(\d{11})")
_DIRECCION_RE = re.compile(r"DIRECCION\s*:\s*(.*?)\s+R\.?\s*U\.?\s*C\.?", re.IGNORECASE)
_TRANSPORTISTA_RE = re.compile(
    r"TRANSPORTISTA\s*:\s*(.*?)\s+CHOFER\s*:\s*(.*)", re.IGNORECASE
)
_SON_RE = re.compile(r"^\s*SON\s*:\s*(.*)$", re.IGNORECASE | re.MULTILINE)
_SCOP_RE = re.compile(r"CODIGO\s+SCOP\s*:\s*(\S+)", re.IGNORECASE)

# Etiquetas que identifican cada bloque de la tabla. La línea de importes sirve
# tanto a la factura (``PLACA ... IMPORTE TOTAL``) como a la nota de crédito
# (``SUBTOTAL IGV (18%) IMPORTE TOTAL``).
_HEADER_LABELS = ("COD DEL CLIENTE", "COD VENDEDOR")
_DETAIL_LABELS = ("CODIGO", "CANT.", "VALOR VENTA")
_PLACA_LABELS = ("IMPORTE TOTAL",)

# Monedas que pueden aparecer en la cabecera (la fila de valores cierra con la
# moneda y, en la factura, con el número de O/C).
_MONEDAS = frozenset({"DOLARES", "DÓLARES", "DOLAR", "SOLES", "USD", "PEN"})

# La nota de crédito reemplaza ``N° DE GUIA`` por ``DOC REFERENCIA``.
_DOC_REFERENCIA = "DOC REFERENCIA"

# Fila de detalle: CODIGO CANT. DESCRIPCION U.M. VALOR_UNIT PRECIO_UNIT VALOR_VENTA
_DETAIL_ROW_RE = re.compile(
    r"^(\S+)\s+(\d[\d,]*\.\d+)\s+(.+?)\s+(\S+)"
    r"\s+(\d[\d,]*\.\d+)\s+(\d[\d,]*\.\d+)\s+(\d[\d,]*\.\d+)$"
)

# Número con 2 decimales (importes de la línea PLACA).
_MONEY_RE = re.compile(r"^[\d,]+\.\d{2}$")

# Token espurio que el PDF intercala entre COD VENDEDOR y COND. PAGO.
_STRAY_TOKENS = {"OFI"}


def _to_decimal(value: Any) -> Decimal | None:
    """``"1,565.47"`` -> ``Decimal("1565.47")``; vacío/inválido -> ``None``."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "."}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _find_label_line(lines: list[str], labels: tuple[str, ...]) -> int | None:
    """Índice de la primera línea que contiene **todas** las etiquetas dadas."""
    for i, line in enumerate(lines):
        upper = line.upper()
        if all(label in upper for label in labels):
            return i
    return None


def _parse_header_values(lines: list[str]) -> dict[str, str]:
    """Valores de la primera fila (COD DEL CLIENTE / N° DE GUIA / COD VENDEDOR...).

    La factura trae ``COD DEL CLIENTE N° DE GUIA COD VENDEDOR COND. PAGO MONEDA O/C``
    y la nota de crédito ``COD DEL CLIENTE DOC REFERENCIA COD VENDEDOR COND. PAGO
    MONEDA O/C`` (sin O/C). Los 3 primeros valores son siempre COD DEL CLIENTE /
    número / COD VENDEDOR; el final es COND. PAGO + MONEDA (+ O/C), así que se
    resuelve por la posición de la moneda.
    """
    idx = _find_label_line(lines, _HEADER_LABELS)
    if idx is None or idx + 1 >= len(lines):
        raise CepDocsParseError(
            "no se encontró la línea de la cabecera (COD DEL CLIENTE / COD VENDEDOR)"
        )
    label = lines[idx].upper()
    tokens = [t for t in lines[idx + 1].split() if t.upper() not in _STRAY_TOKENS]
    if len(tokens) < 4:
        raise CepDocsParseError(
            f"fila de cabecera incompleta (se esperaban >=4 valores): {lines[idx + 1]!r}"
        )
    resto = tokens[3:]
    if resto and resto[-1].upper() in _MONEDAS:
        # Sin O/C: la fila cierra con la moneda (nota de crédito).
        cond_pago, moneda, o_c = " ".join(resto[:-1]), resto[-1], ""
    elif len(resto) >= 2:
        cond_pago, moneda, o_c = " ".join(resto[:-2]), resto[-2], resto[-1]
    else:
        cond_pago, moneda, o_c = "", "", ""
    return {
        "cod_del_cliente": tokens[0],
        "n_de_guia": tokens[1],
        # En la nota de crédito el 3er valor es el documento referenciado, no un
        # código de vendedor: se deja vacío para no contaminar la columna.
        "cod_vendedor": "" if _DOC_REFERENCIA in label else tokens[2],
        "cond_pago": cond_pago,
        "moneda": moneda,
        "o_c": o_c,
    }


def _parse_placa_values(lines: list[str]) -> dict[str, Any]:
    """Valores de la línea de importes (placa + gravadas/exoneradas/IGV/total).

    La factura trae placa y 4 importes (``PLACA OP GRAVADAS OP EXONERADAS IGV
    IMPORTE TOTAL``); la nota de crédito no trae placa y solo 3 (``SUBTOTAL IGV
    IMPORTE TOTAL``), que se mapean como gravadas + IGV + total.
    """
    idx = _find_label_line(lines, _PLACA_LABELS)
    if idx is None or idx + 1 >= len(lines):
        raise CepDocsParseError("no se encontró la línea de importes (IMPORTE TOTAL)")
    tokens = lines[idx + 1].split()
    if not tokens:
        raise CepDocsParseError("la línea de importes está vacía")
    numeros = [t for t in tokens if _MONEY_RE.match(t)]
    primero = tokens[0]
    placa = (
        primero
        if not _MONEY_RE.match(primero) and primero not in {"$", "S/", "US$"}
        else ""
    )
    if len(numeros) >= 4:
        op_gravadas, op_exoneradas, igv, importe_total = numeros[:4]
    elif len(numeros) == 3:
        op_gravadas, igv, importe_total = numeros
        op_exoneradas = None
    else:
        raise CepDocsParseError(
            f"la línea de importes no trae los importes esperados: {lines[idx + 1]!r}"
        )
    return {
        "placa": placa,
        "op_gravadas": _to_decimal(op_gravadas),
        "op_exoneradas": _to_decimal(op_exoneradas),
        "igv": _to_decimal(igv),
        "importe_total": _to_decimal(importe_total),
    }


def _parse_details(lines: list[str]) -> list[dict[str, Any]]:
    """Filas de la tabla de detalle (código, cantidad, descripción, importes...)."""
    idx = _find_label_line(lines, _DETAIL_LABELS)
    if idx is None:
        raise CepDocsParseError(
            "no se encontró la cabecera de detalle (CODIGO / CANT. / VALOR VENTA)"
        )
    detalles: list[dict[str, Any]] = []
    for line in lines[idx + 1 :]:
        match = _DETAIL_ROW_RE.match(line.strip())
        if match is None:
            break  # fin de la tabla (TRANSPORTISTA, SON, PLACA...)
        codigo, cant, descripcion, u_m, valor_unit, precio_unit, valor_venta = (
            match.groups()
        )
        detalles.append(
            {
                "codigo": codigo,
                "cant": _to_decimal(cant),
                "descripcion": descripcion.strip(),
                "u_m": u_m,
                "valor_unit": _to_decimal(valor_unit),
                "precio_unit": _to_decimal(precio_unit),
                "valor_venta": _to_decimal(valor_venta),
            }
        )
    if not detalles:
        raise CepDocsParseError("la tabla de detalle del PDF no tiene filas")
    return detalles


def _parse_header_text(text: str) -> dict[str, str]:
    """Extrae de la cabecera los datos que no están en la tabla."""
    factura = _FACTURA_RE.search(text)
    fecha = _FECHA_RE.search(text)
    cliente = _CLIENTE_RE.search(text)
    ruc = _RUC_RE.search(text)
    direccion = _DIRECCION_RE.search(text)
    transportista = _TRANSPORTISTA_RE.search(text)
    son = _SON_RE.search(text, re.MULTILINE)
    scop = _SCOP_RE.search(text)
    if factura is None:
        raise CepDocsParseError("no se encontró el número de factura en el PDF")
    upper = text.upper()
    if "NOTA DE CREDITO" in upper or "NOTA DE CRÉDITO" in upper:
        tipo_documento = "NOTA DE CREDITO"
    elif "FACTURA" in upper:
        tipo_documento = "FACTURA"
    else:
        tipo_documento = ""
    return {
        "factura": factura.group(1),
        "tipo_documento": tipo_documento,
        "fecha_emision": fecha.group(1) if fecha else "",
        "cliente": cliente.group(1).strip() if cliente else "",
        "ruc_cliente": ruc.group(1) if ruc else "",
        "direccion": direccion.group(1).strip() if direccion else "",
        "transportista": transportista.group(1).strip() if transportista else "",
        "chofer": transportista.group(2).strip() if transportista else "",
        "son": son.group(1).strip() if son else "",
        "codigo_scop": scop.group(1) if scop else "",
    }


def parse_invoice_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    """Parsea un PDF de factura CEP y devuelve ``{"header": {...}, "details": [...]}``.

    ``header`` es la cabecera del comprobante (una por PDF) y ``details`` las filas
    de la tabla de combustible. Lanza ``CepDocsParseError`` si el PDF no se puede
    abrir o no tiene la estructura esperada.
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                raise CepDocsParseError("PDF sin páginas")
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except CepDocsParseError:
        raise
    except Exception as exc:  # PDF corrupto / no es PDF
        raise CepDocsParseError(f"no se pudo abrir el PDF: {exc}") from exc

    lines = text.splitlines()
    header = {
        **_parse_header_text(text),
        **_parse_header_values(lines),
        **_parse_placa_values(lines),
    }
    return {"header": header, "details": _parse_details(lines)}

