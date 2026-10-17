"""Tests del parser CORPAC (extracción del enlace del body y desempaquetado del ZIP)."""

import base64
import io
import zipfile

from assets.from_email_assets.corpac_assets.corpac_files_asset.parser import extract_corpac_url, extract_zip_files

# Body real verificado en BD: HTML decodificado con el enlace literal `&`.
BODY_HTML = (
    '<html><head></head><body style="font-family:verdana,arial,sans-serif; font-size:9pt; ">'
    '<table cellspacing="4" style="width:100%"><tbody><tr><td colspan="2" style="width:100%;">'
    '<img src="https://www.fedtt-peru.com/MercurioCorpacPortal/images/corpac.png" alt="Corpac" '
    'style="height: 60px;" /></td></tr></tbody></table>'
    '<div id="pMain"><h3><b>SISTEMA DE COMUNICACIONES DE FACTURA ELECTRÓNICA</b></h3></div>'
    '<div id="pOthers"><p>Para acceder al contenido de la comunicación, siga el siguiente enlace:<br/>'
    '&nbsp;&nbsp;&nbsp;&nbsp; <a href="https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/'
    'Comunicaciones?accessCode=bWZ1dzFsczErY2s90&action=1" style="line-height: 40px;">'
    'https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones?'
    'accessCode=bWZ1dzFsczErY2s90&action=1</a></p></div></body></html>'
)

URL_ESPERADA = (
    "https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones"
    "?accessCode=bWZ1dzFsczErY2s90&action=1"
)


def test_extract_corpac_url_desde_html():
    assert extract_corpac_url(BODY_HTML) == URL_ESPERADA


def test_extract_corpac_url_tolera_amp_entity():
    # El `&` separador puede venir escapado como `&amp;` en el HTML.
    body = BODY_HTML.replace("&action=1", "&amp;action=1")
    assert extract_corpac_url(body) == URL_ESPERADA


def test_extract_corpac_url_desde_texto_plano():
    texto = (
        "Para acceder al contenido de la comunicación, siga el siguiente enlace:\n"
        "     https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones"
        "?accessCode=bWZ1dzFsczErY2s90&action=1\n"
        "Gracias por utilizar nuestros servicios."
    )
    assert extract_corpac_url(texto) == URL_ESPERADA


def test_extract_corpac_url_access_code_con_slash_mas_e_igual():
    # El accessCode es base64-ish: puede traer `/`, `+` y `=` de padding.
    url = (
        "https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones"
        "?accessCode=ZmhH/RjNBL/1Zsc0U90+abc=&action=2"
    )
    assert extract_corpac_url(f'<a href="{url}">{url}</a>') == url


def test_extract_corpac_url_body_sin_enlace_devuelve_none():
    assert extract_corpac_url("Estimado cliente, no hay nada aquí.") is None
    assert (
        extract_corpac_url(
            "<html><a href='https://otro-sitio.com/Comunicaciones?accessCode=x&action=1'>otro</a></html>"
        )
        is None
    )
    assert extract_corpac_url("") is None
    assert extract_corpac_url(None) is None


def _zip_en_memoria(nombres_contenidos):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nombre, contenido in nombres_contenidos:
            zf.writestr(nombre, contenido)
    buf.seek(0)
    return buf.read()


def test_extract_zip_files_devuelve_filas_base64():
    zip_bytes = _zip_en_memoria(
        [
            ("FACTURA-1.pdf", b"%PDF-1.4 contenido"),
            ("FACTURA-1.xml", b"<Invoice>...</Invoice>"),
            ("OC-100.pdf", b"%PDF-1.4 oc"),
        ]
    )
    archivos = extract_zip_files(zip_bytes)
    assert [a["filename"] for a in archivos] == [
        "FACTURA-1.pdf",
        "FACTURA-1.xml",
        "OC-100.pdf",
    ]
    assert archivos[0]["data"] == base64.b64encode(b"%PDF-1.4 contenido").decode("ascii")
    assert archivos[1]["data"] == base64.b64encode(b"<Invoice>...</Invoice>").decode("ascii")


def test_extract_zip_files_ignora_directorios():
    zip_bytes = _zip_en_memoria(
        [
            ("carpeta/", b""),
            ("carpeta/FACTURA-1.pdf", b"%PDF"),
        ]
    )
    archivos = extract_zip_files(zip_bytes)
    assert [a["filename"] for a in archivos] == ["carpeta/FACTURA-1.pdf"]
