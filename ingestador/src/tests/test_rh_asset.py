"""Tests del parser, del resource HTTP y de la vía HTTP del reporte RH del SEE-SOL.

El parser se prueba directamente; del resource se prueban los helpers puros
(rango del mes, criterios del POST, captcha/fallas, login de 1 intento) y
``get_month`` con la vía HTTP simulada. El asset (``seesol_rh_monthly``) tiene su
propio archivo (``test_seesol_rh_asset.py``).
"""
import json
from decimal import Decimal

import pytest

import assets.seesol_rh_asset.resources.api_resource.rh_resource as mod
from assets.seesol_rh_asset.parsers.rh import parse_rh_text
from assets.seesol_rh_asset.resources.api_resource import RhResource, SeesolRhError

HEADER = (
    "Fecha de Emisión|Tipo Doc. Emitido|Nro. Doc. Emitido|Estado Doc. Emitido|"
    "Tipo de Doc. Emisor|Nro. Doc. Emisor|"
    "Apellidos y Nombres, Denominación o Razón Social del Emisor|Tipo de Renta|"
    "Gratuito|Descripción|Observación|Moneda de Operación|Renta Bruta|"
    "Impuesto a la Renta|Renta Neta|Monto Neto Pendiente de Pago|"
)


def _row(
    fecha="01/08/2026",
    descripcion="SERVICIO",
    observacion="-",
    renta="1200.00",
):
    return (
        f"{fecha}|RH|E001-1|NO ANULADO|RUC|10418240178|CLIENTE PRUEBA|A|NO|"
        f"{descripcion}|{observacion}|SOLES|{renta}|96.00|1104.00|0.00|"
    )


# --- parser --------------------------------------------------------------------


def test_parse_rh_text_basico():
    filas = parse_rh_text(HEADER + _row())
    assert len(filas) == 1
    f = filas[0]
    assert f["fecha_de_emision"] == "01/08/2026"
    assert f["nro_doc_emitido"] == "E001-1"
    assert (
        f["apellidos_y_nombres_denominacion_o_razon_social_del_emisor"]
        == "CLIENTE PRUEBA"
    )
    assert f["gratuito"] == "NO"
    assert f["observacion"] == "-"
    assert f["renta_bruta"] == Decimal("1200.00")
    assert f["impuesto_a_la_renta"] == Decimal("96.00")
    assert f["renta_neta"] == Decimal("1104.00")


def test_parse_rh_text_descripcion_partida():
    # La Descripción puede traer un salto de línea embebido; no debe partir el
    # registro (caso real que aparece en los reportes de SUNAT).
    filas = parse_rh_text(
        HEADER + _row(descripcion="APOYO MEDICO 2789 MOYOBAMBA\n01-08-2026")
    )
    assert len(filas) == 1
    assert filas[0]["descripcion"] == "APOYO MEDICO 2789 MOYOBAMBA\n01-08-2026"
    assert filas[0]["nro_doc_emitido"] == "E001-1"
    assert filas[0]["monto_neto_pendiente_de_pago"] == Decimal("0.00")


def test_parse_rh_text_numerico_vacio():
    filas = parse_rh_text(HEADER + _row(renta="-"))
    assert filas[0]["renta_bruta"] is None


def test_parse_rh_text_varias_filas():
    filas = parse_rh_text(
        HEADER + _row(fecha="01/08/2026") + _row(fecha="02/08/2026", renta="600.00")
    )
    assert len(filas) == 2
    assert filas[0]["fecha_de_emision"] == "01/08/2026"
    assert filas[1]["fecha_de_emision"] == "02/08/2026"
    assert filas[1]["renta_bruta"] == Decimal("600.00")


def test_parse_rh_text_solo_cabecera():
    assert parse_rh_text(HEADER) == []


# --- helpers puros (sin red) ---------------------------------------------------


def test_rango_del_mes():
    assert mod.rango_del_mes(2026, 8) == ("01/08/2026", "31/08/2026")
    assert mod.rango_del_mes(2026, 2) == ("01/02/2026", "28/02/2026")
    assert mod.rango_del_mes(2028, 2) == ("01/02/2028", "29/02/2028")
    assert mod.rango_del_mes(2026, 12) == ("01/12/2026", "31/12/2026")


def test_criterios_busqueda_lleva_los_tipos_concatenados():
    """El campo oculto `tipocomprobante` va como "01;02;03;" (trampa verificada)."""
    criterios = mod.criterios_busqueda("01/08/2026", "31/08/2026")
    assert ("accion", "CapturaCriterioConsulatRec1") in criterios
    assert ("tipocomprobante", "01;02;03;") in criterios
    assert ("fec_desde", "01/08/2026") in criterios
    assert ("fec_hasta", "31/08/2026") in criterios
    assert ("tipoestado", "00") in criterios
    assert ("wacepta", "Buscar") in criterios


def test_criterios_busqueda_rechaza_rango_de_mas_de_un_mes():
    with pytest.raises(ValueError, match="máx"):
        mod.criterios_busqueda("01/07/2026", "31/08/2026")


def test_criterios_busqueda_rechaza_fecha_mal_formada():
    with pytest.raises(ValueError, match="inválida"):
        mod.criterios_busqueda("2026-08-01", "31/08/2026")


def test_sin_registros_y_base_del_portal():
    assert mod.sin_registros("<html>No se han encontrado registros</html>") is True
    assert mod.sin_registros("<html>ok</html>") is False
    assert mod.base_del_portal("https://ww1.sunat.gob.pe/ol-x/cpelec001Alias?a=1") == (
        "https://ww1.sunat.gob.pe"
    )
    with pytest.raises(SeesolRhError, match="inválida"):
        mod.base_del_portal("cpelec001Alias?a=1")


def test_inputs_del_form_solo_toma_el_loginform():
    html = (
        "<form name='LoginForm'>"
        "<input name='state' value='abc'>"
        "<input name='j_username' value=''>"
        "</form>"
        "<form name='otro'><input name='fuera' value='x'></form>"
    )
    assert mod.inputs_del_form(html) == {"state": "abc", "j_username": ""}


# --- login del portal (simulado) -----------------------------------------------


class _Respuesta:
    def __init__(self, status_code=200, text="", payload=None, location=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self._payload = payload
        self.headers = {"location": location} if location else {}
        self.url = ""

    def json(self):
        return self._payload


class _SesionFake:
    """Sesión de ``requests`` simulada: devuelve las respuestas encoladas."""

    def __init__(self, get=None, post=None):
        self._get = list(get or [])
        self._post = list(post or [])
        self.gets = []
        self.posts = []

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self._get.pop(0)

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self._post.pop(0)


def _login_fake(
    url="https://api-seguridad.sunat.gob.pe/v1/clientessol/abc/oauth2/loginMenuSol?state=s",
):
    respuesta = _Respuesta(
        text=(
            "<form name='LoginForm'><input name='state' value=''>"
            "<input name='j_username' value=''></form>"
        )
    )
    respuesta.url = url
    return respuesta


def test_descubrir_flujo_devuelve_el_form_y_los_ocultos():
    menu = _Respuesta(text="redirect('https://api-seguridad.sunat.gob.pe/authen?x=1')")
    session = _SesionFake(
        get=[menu, _login_fake()], post=[_Respuesta(payload={"fallas": "0"})]
    )

    flujo = mod.descubrir_flujo(session)

    assert flujo["action_login"] == (
        "https://api-seguridad.sunat.gob.pe/v1/clientessol/abc/oauth2/j_security_check"
    )
    assert flujo["parametros_login"] == {"state": "s"}
    assert flujo["campos_ocultos"] == {"state": "", "j_username": ""}
    assert flujo["fallas"] == 0


def test_descubrir_flujo_aborta_si_sunat_ya_pide_captcha():
    menu = _Respuesta(text="redirect('https://api-seguridad.sunat.gob.pe/authen?x=1')")
    session = _SesionFake(
        get=[menu, _login_fake()], post=[_Respuesta(payload={"fallas": "3"})]
    )

    with pytest.raises(SeesolRhError, match="captcha"):
        mod.descubrir_flujo(session)


def test_hacer_login_manda_las_credenciales_y_sigue_el_302():
    aceptado = _Respuesta(
        status_code=302,
        location="https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm?state=s",
    )
    session = _SesionFake(
        get=[_Respuesta(text="menu")],
        # 1º el `action=fails` (pre-chequeo de captcha) y 2º el login.
        post=[_Respuesta(payload={"fallas": "0"}), aceptado],
    )
    flujo = {
        "login_url": (
            "https://api-seguridad.sunat.gob.pe/v1/clientessol/abc/oauth2/"
            "loginMenuSol?state=s"
        ),
        "action_login": (
            "https://api-seguridad.sunat.gob.pe/v1/clientessol/abc/oauth2/"
            "j_security_check"
        ),
        "campos_ocultos": {"state": "", "originalUrl": ""},
        "parametros_login": {"state": "s", "originalUrl": "u"},
    }

    mod.hacer_login(
        session,
        flujo,
        {
            "name": "Air Majoro",
            "ruc": "20494626978",
            "user": "FLYMAJOR",
            "password": "clave",
        },
    )

    url, kwargs = [p for p in session.posts if p[0] == flujo["action_login"]][0]
    assert kwargs["data"]["tipo"] == "2"
    assert kwargs["data"]["custom_ruc"] == "20494626978"
    assert kwargs["data"]["j_username"] == "FLYMAJOR"
    assert kwargs["data"]["j_password"] == "clave"
    assert kwargs["data"]["captcha"] == ""
    # El JS del portal copia del query string al form los campos que existan.
    assert kwargs["data"]["state"] == "s"
    assert kwargs["data"]["originalUrl"] == "u"
    # El 302 se sigue para dejar la sesión establecida.
    assert session.gets[0][0].startswith("https://e-menu.sunat.gob.pe")


def test_hacer_login_sin_credenciales():
    flujo = {"campos_ocultos": {}, "parametros_login": {}}
    with pytest.raises(SeesolRhError, match="ruc/user/password"):
        mod.hacer_login(_SesionFake(), flujo, {"name": "Air Majoro"})


def test_hacer_login_rechazado_no_reintenta():
    rechazado = _Respuesta(
        status_code=302,
        location=(
            "https://api-seguridad.sunat.gob.pe/v1/clientessol/abc/oauth2/"
            "loginMenuSol?error=1"
        ),
    )
    session = _SesionFake(
        post=[_Respuesta(payload={"fallas": "0"}), rechazado]
    )
    flujo = {
        "login_url": "https://api-seguridad.sunat.gob.pe/loginMenuSol",
        "action_login": "https://api-seguridad.sunat.gob.pe/j_security_check",
        "campos_ocultos": {},
        "parametros_login": {},
    }

    with pytest.raises(SeesolRhError, match="no fue aceptado"):
        mod.hacer_login(
            session,
            flujo,
            {"name": "Air Majoro", "ruc": "1", "user": "u", "password": "p"},
        )
    # Un único intento de login (además del `action=fails` previo), sin reintentos.
    login_posts = [p for p in session.posts if p[0] == flujo["action_login"]]
    assert len(login_posts) == 1


# --- RhResource (vía HTTP simulada) --------------------------------------------


def _credenciales(tmp_path, nombre="Air Majoro"):
    ruta = tmp_path / "sire_credentials.json"
    ruta.write_text(
        json.dumps(
            [
                {
                    "name": nombre,
                    "ruc": "20494626978",
                    "user": "FLYMAJOR",
                    "password": "clave",
                }
            ]
        ),
        encoding="utf-8",
    )
    return str(ruta)


def test_get_month_estampa_el_period_y_pide_el_mes_completo(tmp_path, monkeypatch):
    llamadas = {}

    def fake_abrir_sesion(empresa):
        llamadas["empresa"] = empresa
        return "session-fake"

    def fake_descargar(session, desde, hasta):
        llamadas["session"] = session
        llamadas["rango"] = (desde, hasta)
        return HEADER + _row(observacion="1")

    monkeypatch.setattr(mod, "abrir_sesion", fake_abrir_sesion)
    monkeypatch.setattr(mod, "descargar_reporte", fake_descargar)

    filas = RhResource(credentials_path=_credenciales(tmp_path)).get_month(
        "Air Majoro", "2026-08-01"
    )

    assert llamadas["empresa"]["user"] == "FLYMAJOR"
    assert llamadas["session"] == "session-fake"
    assert llamadas["rango"] == ("01/08/2026", "31/08/2026")
    assert [f["period"] for f in filas] == ["2026-08-01"]
    assert filas[0]["nro_doc_emitido"] == "E001-1"
    # Las filas no traen `empresa`: lo estampa el asset antes del upsert.
    assert "empresa" not in filas[0]


def test_get_month_admite_period_sin_dia(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "abrir_sesion", lambda empresa: "session-fake")
    monkeypatch.setattr(
        mod, "descargar_reporte", lambda session, desde, hasta: HEADER + _row()
    )

    filas = RhResource(credentials_path=_credenciales(tmp_path)).get_month(
        "Air Majoro", "2026-08"
    )

    assert [f["period"] for f in filas] == ["2026-08"]


def test_get_month_sin_registros_devuelve_lista_vacia(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "abrir_sesion", lambda empresa: "session-fake")
    monkeypatch.setattr(mod, "descargar_reporte", lambda session, desde, hasta: HEADER)

    assert RhResource(credentials_path=_credenciales(tmp_path)).get_month(
        "Air Majoro", "2026-08-01"
    ) == []


def test_empresa_desconocida(tmp_path):
    with pytest.raises(SeesolRhError, match="No existe"):
        RhResource(credentials_path=_credenciales(tmp_path)).empresa("Otra S.A.")
