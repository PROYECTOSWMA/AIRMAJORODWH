"""Tests de GmailResource: listado barato de ids, descarga del mensaje y salto de
los ids que ya están en la tabla ``emails``.

El servicio de Gmail se sustituye por un doble en memoria (``_Service``), así que
los tests no tocan la red ni piden credenciales.
"""

import base64
from email.message import EmailMessage

from assets.mail_asset.resources.api_resource import GmailResource

CUENTA = "jorge.paredes@airmajoro.com"
OTRA_CUENTA = "contabilidad@airmajoro.com"


def _raw(subject="asunto", con_adjunto=True):
    """Mensaje MIME completo codificado como lo devuelve Gmail (``raw``)."""
    msg = EmailMessage()
    msg["From"] = "Proveedor <proveedor@x.com>"
    msg["Subject"] = subject
    msg["Date"] = "Mon, 10 Aug 2026 10:00:00 -0500"
    msg.set_content("cuerpo del correo")
    if con_adjunto:
        msg.add_attachment(
            b"contenido-pdf",
            maintype="application",
            subtype="pdf",
            filename="a.pdf",
        )
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


class _Request:
    """Doble del request encadenado de googleapiclient (solo hace falta execute)."""

    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _Service:
    """Doble de ``service.users().messages()``: guarda las llamadas y responde."""

    def __init__(self, ids, raws):
        self.ids = list(ids)
        self.raws = raws
        self.list_calls = []
        self.get_calls = []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return _Request({"messages": [{"id": i} for i in self.ids]})

    def list_next(self, request, response):
        return None

    def get(self, **kwargs):
        message_id = kwargs["id"]
        self.get_calls.append(message_id)
        return _Request(
            {
                "id": message_id,
                "threadId": "t-" + message_id,
                "internalDate": "1786208410000",
                "raw": self.raws[message_id],
            }
        )


def _resource(servicios, accounts=(CUENTA,)):
    """GmailResource con los servicios ya inyectados (no pasa por credenciales)."""
    res = GmailResource(accounts=list(accounts))
    res._services = dict(servicios)
    return res


def _servicio(ids, con_adjunto=True):
    return _Service(ids, {i: _raw(con_adjunto=con_adjunto) for i in ids})


def test_list_message_ids_devuelve_los_ids_por_cuenta():
    uno = _servicio(["m1", "m2"])
    otro = _servicio(["m9"])
    res = _resource({CUENTA: uno, OTRA_CUENTA: otro}, accounts=(CUENTA, OTRA_CUENTA))

    ids = res.list_message_ids(query="after:2026/08/11 before:2026/08/12")

    assert ids == {CUENTA: ["m1", "m2"], OTRA_CUENTA: ["m9"]}
    # Una sola llamada a messages.list por cuenta y sin pedir cuerpos.
    assert len(uno.list_calls) == 1 and len(otro.list_calls) == 1
    assert uno.list_calls[0]["q"] == "after:2026/08/11 before:2026/08/12"
    assert uno.get_calls == [] and otro.get_calls == []


def test_fetch_emails_descarga_los_mensajes_y_los_etiqueta_con_su_cuenta():
    servicio = _servicio(["m1", "m2"])
    res = _resource({CUENTA: servicio})

    emails = res.fetch_emails(query="q")

    assert [e["id"] for e in emails] == ["m1", "m2"]
    assert {e["mailbox"] for e in emails} == {CUENTA}
    assert servicio.get_calls == ["m1", "m2"]
    assert emails[0]["sender"] == "proveedor@x.com"
    assert emails[0]["subject"] == "asunto"
    assert [a["filename"] for a in emails[0]["attachments"]] == ["a.pdf"]


def test_fetch_emails_salta_los_ids_ya_guardados():
    servicio = _servicio(["m1", "m2", "m3"])
    res = _resource({CUENTA: servicio})

    emails = res.fetch_emails(query="q", skip_ids={"m1", "m3"})

    # A Gmail solo se le pide el mensaje nuevo (m2): ni cuerpo ni adjuntos del resto.
    assert [e["id"] for e in emails] == ["m2"]
    assert servicio.get_calls == ["m2"]


def test_fetch_emails_sin_skip_ids_descarga_todo():
    servicio = _servicio(["m1", "m2"])
    res = _resource({CUENTA: servicio})

    emails = res.fetch_emails(query="q")

    assert [e["id"] for e in emails] == ["m1", "m2"]
    assert servicio.get_calls == ["m1", "m2"]


def test_fetch_emails_con_ids_pasados_no_vuelve_a_listar():
    servicio = _servicio(["m1", "m2"])
    res = _resource({CUENTA: servicio})

    emails = res.fetch_emails(query="q", ids_by_account={CUENTA: ["m2"]})

    assert [e["id"] for e in emails] == ["m2"]
    # Los ids ya venían listados: no se repite la llamada barata a messages.list.
    assert servicio.list_calls == []


def test_fetch_emails_salta_por_id_aunque_haya_varias_cuentas():
    uno = _servicio(["m1", "m2"])
    otro = _servicio(["m2", "m3"])
    res = _resource({CUENTA: uno, OTRA_CUENTA: otro}, accounts=(CUENTA, OTRA_CUENTA))

    emails = res.fetch_emails(query="q", skip_ids={"m2"})

    # El id ya guardado se salta en TODAS las bandejas (la PK de `emails` es el id).
    assert [e["id"] for e in emails] == ["m1", "m3"]
    assert uno.get_calls == ["m1"] and otro.get_calls == ["m3"]


def test_fetch_emails_sin_adjuntos_tambien_salta():
    servicio = _servicio(["m1", "m2"], con_adjunto=False)
    res = _resource({CUENTA: servicio})

    emails = res.fetch_emails(query="q", skip_ids={"m1"})

    assert [e["id"] for e in emails] == ["m2"]
    assert emails[0]["attachments"] == []
