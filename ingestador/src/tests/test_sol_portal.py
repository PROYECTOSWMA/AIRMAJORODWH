"""Tests del protocolo HTTP del portal SOL (``sol_portal``).

Simulan el portal con una sesión falsa (como en ``test_rh_asset.py``): el menú
con su ``redirect()``, la pantalla de login, el ``action=fails`` y el
``action=execute`` que responde 302 con el JWT en el ``Location``.
"""

import pytest

import assets.sire_assets.resources.sol_portal as sol
from assets.sire_assets.resources.sol_portal import (
    APP_COMPROBANTES,
    SolPortalError,
    abrir_app,
    abrir_sesion,
    descubrir_flujo,
    extraer_param,
    fallas_pendientes,
    hacer_login,
    inputs_del_form,
    obtener_token_app,
    token_de_apertura,
    token_en_texto,
    url_authen,
)

MENU_HTML = (
    "<script>redirect('https://api-seguridad.sunat.gob.pe/v1/clientessol/abc"
    "/oauth2/authen?client_id=abc&response_type=code')</script>"
)
LOGIN_URL = (
    "https://api-seguridad.sunat.gob.pe/v1/clientessol/abc/oauth2/"
    "loginMenuSol?state=s"
)
LOGIN_HTML = (
    "<form name='LoginForm'><input name='state' value=''>"
    "<input name='j_username' value=''></form>"
)
TOKEN_APP = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJ4In0.firma"


class Respuesta:
    def __init__(self, status_code=200, text="", payload=None, location=None, url=""):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self._payload = payload
        self.headers = {"location": location} if location else {}
        self.url = url
        self.history = []

    def json(self):
        return self._payload


class Sesion:
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


def login_fake(url=LOGIN_URL):
    return Respuesta(text=LOGIN_HTML, url=url)


EMPRESA = {
    "name": "Air Majoro",
    "ruc": "20494626978",
    "user": "FLYMAJOR",
    "password": "clave",
}


# --- helpers puros -------------------------------------------------------------


def test_fallas_pendientes():
    class _Sesion:
        def post(self, *args, **kwargs):
            return Respuesta(payload={"fallas": "2"})

    assert fallas_pendientes(_Sesion()) == 2

    class _SesionRota:
        def post(self, *args, **kwargs):
            raise sol.requests.exceptions.ConnectionError("sin red")

    assert fallas_pendientes(_SesionRota()) is None


def test_inputs_del_form_solo_del_login_form():
    html = (
        "<form name='otro'><input name='fuera' value='x'></form>"
        "<form name='LoginForm'><input name='state' value=''>"
        "<input name='j_username' value=''></form>"
    )
    assert inputs_del_form(html) == {"state": "", "j_username": ""}


def test_extraer_param_y_token_en_texto():
    urls = ["https://x/y?code=1", "https://x/y?token=abc%2Edef"]
    assert extraer_param(urls, "code") == "1"
    assert extraer_param(urls, "token") == "abc.def"
    assert extraer_param(urls, "otro") is None
    assert token_en_texto("...html?token=XYZ") == "XYZ"
    assert token_en_texto("sin nada") is None


def test_url_authen():
    url = url_authen("cli", "https://redir/loader")
    assert url.startswith(sol.SECURITY_BASE + "/cli/oauth2/authen")
    assert "response_type=code" in url
    assert "redirect_uri=https%3A%2F%2Fredir%2Floader" in url


# --- flujo anónimo -------------------------------------------------------------


def test_descubrir_flujo_devuelve_el_form_y_los_ocultos():
    session = Sesion(
        get=[Respuesta(text=MENU_HTML), login_fake()],
        post=[Respuesta(payload={"fallas": "0"})],
    )

    flujo = descubrir_flujo(session)

    assert flujo["action_login"].endswith("/oauth2/j_security_check")
    assert flujo["parametros_login"] == {"state": "s"}
    assert flujo["campos_ocultos"] == {"state": "", "j_username": ""}
    assert flujo["fallas"] == 0


def test_descubrir_flujo_aborta_si_sunat_ya_pide_captcha():
    session = Sesion(
        get=[Respuesta(text=MENU_HTML), login_fake()],
        post=[Respuesta(payload={"fallas": "3"})],
    )

    with pytest.raises(SolPortalError, match="captcha"):
        descubrir_flujo(session)


def test_descubrir_flujo_sin_redirect():
    session = Sesion(get=[Respuesta(text="<html>sin js</html>")])

    with pytest.raises(SolPortalError, match="redirect"):
        descubrir_flujo(session)


def test_descubrir_flujo_sin_pantalla_de_login():
    session = Sesion(get=[Respuesta(text=MENU_HTML), Respuesta(url="https://otro/x")])

    with pytest.raises(SolPortalError, match="pantalla de login"):
        descubrir_flujo(session)


# --- login ---------------------------------------------------------------------


FLUJO = {
    "authen_url": "https://api-seguridad/authen",
    "login_url": LOGIN_URL,
    "action_login": (
        "https://api-seguridad.sunat.gob.pe/v1/clientessol/abc/oauth2/j_security_check"
    ),
    "campos_ocultos": {"state": "", "originalUrl": ""},
    "parametros_login": {"state": "s", "originalUrl": "u"},
    "fallas": 0,
}


def test_hacer_login_manda_las_credenciales_y_sigue_el_302():
    aceptado = Respuesta(
        status_code=302,
        location="https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm?state=s",
    )
    session = Sesion(
        get=[Respuesta(text="menu", url="https://e-menu/.../MenuInternet.htm")],
        post=[Respuesta(payload={"fallas": "0"}), aceptado],
    )

    urls = hacer_login(session, FLUJO, EMPRESA)

    login_post = [p for p in session.posts if p[0] == FLUJO["action_login"]][0]
    kwargs = login_post[1]
    assert kwargs["data"]["tipo"] == "2"
    assert kwargs["data"]["custom_ruc"] == "20494626978"
    assert kwargs["data"]["j_username"] == "FLYMAJOR"
    assert kwargs["data"]["j_password"] == "clave"
    assert kwargs["data"]["captcha"] == ""
    assert kwargs["allow_redirects"] is False
    assert urls == ["https://e-menu/.../MenuInternet.htm"]


def test_hacer_login_sin_credenciales():
    with pytest.raises(SolPortalError, match="ruc/user/password"):
        hacer_login(Sesion(), FLUJO, {"name": "Air Majoro"})


def test_hacer_login_rechazado_no_reintenta():
    rechazado = Respuesta(status_code=302, location=LOGIN_URL)
    session = Sesion(
        post=[Respuesta(payload={"fallas": "0"}), rechazado]
    )

    with pytest.raises(SolPortalError, match="no fue aceptado"):
        hacer_login(session, FLUJO, EMPRESA)
    assert len([p for p in session.posts if p[0] == FLUJO["action_login"]]) == 1


def test_hacer_login_aborta_si_ya_hay_3_fallas():
    session = Sesion(post=[Respuesta(payload={"fallas": "3"})])

    with pytest.raises(SolPortalError, match="captcha"):
        hacer_login(session, FLUJO, EMPRESA)
    assert session.posts == [] or len(session.posts) == 1  # sólo el action=fails


# --- apertura de la app (action=execute) ---------------------------------------


def test_token_de_apertura_lee_el_location():
    destino = f"https://e-factura.sunat.gob.pe/app/.../nuevaconsulta.html?token={TOKEN_APP}"
    session = Sesion(
        get=[Respuesta(status_code=302, location=destino)],
        post=[Respuesta()],  # prevApp
    )

    token, de_donde = token_de_apertura(session, APP_COMPROBANTES)

    assert token == TOKEN_APP
    assert de_donde.startswith("Location del portal")
    # El GET del action=execute va con el código de la app.
    assert "action=execute" in session.gets[0][0]
    assert session.gets[0][1]["allow_redirects"] is False


def test_token_de_apertura_sigue_la_cadena_si_no_hay_token_en_el_location():
    final = Respuesta(text="ok", url=f"https://e-factura/x?token={TOKEN_APP}")
    session = Sesion(
        get=[
            Respuesta(status_code=302, location="https://e-factura/x"),
            final,
        ],
        post=[Respuesta()],
    )

    token, de_donde = token_de_apertura(session, APP_COMPROBANTES)

    assert token == TOKEN_APP
    assert de_donde == "cadena de redirecciones del portal"


def test_token_de_apertura_sin_token_devuelve_none():
    session = Sesion(
        get=[
            Respuesta(status_code=302, location="https://e-factura/x"),
            Respuesta(text="<html>nada</html>", url="https://e-factura/x"),
        ],
        post=[Respuesta()],
    )

    assert token_de_apertura(session, APP_COMPROBANTES) is None


def test_abrir_app_devuelve_el_location_y_falla_con_200():
    session = Sesion(
        get=[Respuesta(status_code=302, location="https://ww1/x")],
        post=[Respuesta()],
    )
    assert abrir_app(session, "11.5.1.1.14") == "https://ww1/x"

    session2 = Sesion(get=[Respuesta(status_code=200, text="menu")], post=[Respuesta()])
    with pytest.raises(SolPortalError, match="no abrió la app"):
        abrir_app(session2, "11.5.1.1.14")


def test_obtener_token_app_con_sesion_ya_logueada():
    destino = f"https://e-factura/x?token={TOKEN_APP}"
    session = Sesion(
        get=[Respuesta(status_code=302, location=destino)],
        post=[Respuesta()],
    )

    token, origen = obtener_token_app(EMPRESA, APP_COMPROBANTES, session=session)

    assert token == TOKEN_APP
    assert origen.startswith("portal SOL")


def test_obtener_token_app_falla_si_la_app_no_deja_token():
    session = Sesion(
        get=[
            Respuesta(status_code=302, location="https://e-factura/x"),
            Respuesta(text="nada", url="https://e-factura/x"),
        ],
        post=[Respuesta()],
    )

    with pytest.raises(SolPortalError, match="no devolvió el token"):
        obtener_token_app(EMPRESA, APP_COMPROBANTES, session=session)


def test_abrir_sesion_hace_login_y_vuelve_al_menu(monkeypatch):
    session = Sesion(
        get=[
            Respuesta(text=MENU_HTML),  # menú
            login_fake(),  # pantalla de login
            Respuesta(text="menu"),  # redirect del login aceptado
            Respuesta(text="menu"),  # menú real ya autenticado
        ],
        post=[
            Respuesta(payload={"fallas": "0"}),  # action=fails (descubrir_flujo)
            Respuesta(payload={"fallas": "0"}),  # action=fails (hacer_login)
            Respuesta(status_code=302, location="https://e-menu/.../MenuInternet.htm"),
        ],
    )
    monkeypatch.setattr(sol.requests, "Session", lambda: session)

    assert abrir_sesion(EMPRESA) is session
    assert session.gets[-1][0] == sol.MENU_URL

