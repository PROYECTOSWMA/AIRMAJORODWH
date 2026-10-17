"""Tests del extractor y el parser de los cost centers SIRE.

El extractor (``file_extractor``) saca el XML del comprobante del ZIP que SUNAT
entrega en el segmento 02; el parser (``parser``) solo aplica la regex de la
matrícula ``OB-####`` sobre ese ``str``.
"""

import io
import zipfile

import pytest

from assets.from_sire_files_assets._common.file_extractor import (
    SireXmlError,
    extract_xml,
)
from assets.from_sire_files_assets._common.parser import (
    parse_aeropuerto,
    parse_aeronave,
)

# Nombre del XML del comprobante y de la respuesta de SUNAT como los emite la API.
XML_COMPROBANTE = "20613566881-01-F002-012747.xml"
XML_RESPUESTA = "R-20613566881-01-F002-012747.xml"

CONTENIDO_COMPROBANTE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Invoice><cbc:ID>F002-12747</cbc:ID>"
    "<cac:Item><cbc:Description>AERONAVE OB-2092 SERVICIO</cbc:Description></cac:Item>"
    "</Invoice>"
)
CONTENIDO_RESPUESTA = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<ApplicationResponse><cbc:ID>F002-12747</cbc:ID></ApplicationResponse>"
)


def _zip_en_memoria(nombres_contenidos: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nombre, contenido in nombres_contenidos:
            zf.writestr(nombre, contenido)
    return buf.getvalue()


def test_extract_xml_devuelve_el_xml_del_comprobante_como_str():
    zip_bytes = _zip_en_memoria(
        [
            (XML_COMPROBANTE, CONTENIDO_COMPROBANTE.encode("utf-8")),
            (XML_RESPUESTA, CONTENIDO_RESPUESTA.encode("utf-8")),
        ]
    )

    xml = extract_xml(zip_bytes)

    # Es el XML del comprobante como ``str`` (no bytes) y con su nombre en el ZIP.
    assert isinstance(xml, str)
    assert xml == CONTENIDO_COMPROBANTE
    assert xml.filename == XML_COMPROBANTE


def test_extract_xml_ignora_la_respuesta_r_y_lo_que_no_es_xml():
    # La respuesta ``R-`` va primero y hay un PDF: solo vale el XML del comprobante.
    zip_bytes = _zip_en_memoria(
        [
            (XML_RESPUESTA, CONTENIDO_RESPUESTA.encode("utf-8")),
            ("20613566881-01-F002-012747.pdf", b"%PDF-1.4"),
            ("carpeta/", b""),
            (XML_COMPROBANTE, CONTENIDO_COMPROBANTE.encode("utf-8")),
        ]
    )

    xml = extract_xml(zip_bytes)

    assert xml == CONTENIDO_COMPROBANTE
    assert xml.filename == XML_COMPROBANTE


def test_extract_xml_sin_comprobante_lanza_error():
    # Solo viene la respuesta de SUNAT: no hay XML de comprobante que extraer.
    zip_bytes = _zip_en_memoria([(XML_RESPUESTA, CONTENIDO_RESPUESTA.encode("utf-8"))])

    with pytest.raises(SireXmlError, match="comprobante"):
        extract_xml(zip_bytes)


def test_extract_xml_zip_vacio_lanza_error():
    with pytest.raises(SireXmlError, match="comprobante"):
        extract_xml(_zip_en_memoria([]))


def test_extract_xml_archivo_que_no_es_zip_lanza_error():
    with pytest.raises(SireXmlError, match="ZIP"):
        extract_xml(b"%PDF-1.4 no soy un ZIP")


@pytest.mark.parametrize("aeronave", ["OB-2092", "OB2092"])
def test_parse_aeronave_con_y_sin_guion(aeronave):
    # SUNAT emite la matrícula con guion (CEP/PETROPERU) o sin guion (ICARO).
    xml = f"<Invoice><cbc:Description>AERONAVE {aeronave}</cbc:Description></Invoice>"

    assert parse_aeronave(xml) == aeronave


def test_parse_aeronave_sin_matricula_devuelve_none():
    assert parse_aeronave("<Invoice><cbc:Description>VUELO LIMA</cbc:Description></Invoice>") is None
    assert parse_aeronave("") is None


def test_parse_aeronave_devuelve_la_primera_coincidencia():
    xml = "<x>OB-1234</x><y>OB5678</y>"

    assert parse_aeronave(xml) == "OB-1234"


def test_extractor_y_parser_juntos():
    """Pipeline completo del asset: ZIP -> xml str -> aeronave."""
    zip_bytes = _zip_en_memoria(
        [
            (XML_COMPROBANTE, CONTENIDO_COMPROBANTE.encode("utf-8")),
            (XML_RESPUESTA, CONTENIDO_RESPUESTA.encode("utf-8")),
        ]
    )

    xml = extract_xml(zip_bytes)

    assert parse_aeronave(xml) == "OB-2092"


# --- aeropuerto del DatoAdicional de código 31 (PETROPERU) ---

_DATO_31 = (
    "<DatoAdicional><Codigo>31</Codigo>"
    "<Valor><![CDATA[PRINCIPAL AEROPUERTO) YARINACOCHA CORONEL PORTILLO Ucayali]]></Valor>"
    "</DatoAdicional>"
)


def test_parse_aeropuerto_ultima_palabra_y_texto_completo():
    xml = f"<Invoice><ext:ExtensionContent><DatosAdicionales>{_DATO_31}</DatosAdicionales></ext:ExtensionContent></Invoice>"

    aeropuerto, completo = parse_aeropuerto(xml)

    assert aeropuerto == "Ucayali"
    assert completo == "PRINCIPAL AEROPUERTO) YARINACOCHA CORONEL PORTILLO Ucayali"


def test_parse_aeropuerto_sin_cdata_y_con_saltos_de_linea():
    xml = (
        "<DatoAdicional>\n  <Codigo>31</Codigo>\n  <Valor>\n"
        "PRINCIPAL AEROPUERTO) YARINACOCHA CORONEL PORTILLO Ucayali\n"
        "  </Valor>\n</DatoAdicional>"
    )

    assert parse_aeropuerto(xml) == (
        "Ucayali",
        "PRINCIPAL AEROPUERTO) YARINACOCHA CORONEL PORTILLO Ucayali",
    )


def test_parse_aeropuerto_ignora_otros_codigos():
    xml = (
        "<DatoAdicional><Codigo>20</Codigo><Valor>250105 - YARINACOCHA</Valor></DatoAdicional>"
        "<DatoAdicional><Codigo>23</Codigo><Valor>OB-2209</Valor></DatoAdicional>"
    )

    assert parse_aeropuerto(xml) == (None, None)
    assert parse_aeropuerto("") == (None, None)
