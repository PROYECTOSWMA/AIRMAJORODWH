"""Tests del modo verboso compartido de los assets SIRE (details y files)."""

import pytest

from assets.sire_assets.resources.verbose import (
    VERBOSE_ENV,
    VERBOSE_ENV_POR_ASSET,
    verbose_habilitado,
)

_VARIABLES = (VERBOSE_ENV, *VERBOSE_ENV_POR_ASSET.values())


@pytest.fixture(autouse=True)
def _sin_variables(monkeypatch):
    """Aísla cada test del entorno real: ninguna variable de modo verboso puesta."""
    for variable in _VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def test_apagado_por_defecto():
    assert verbose_habilitado("details") is False
    assert verbose_habilitado("files") is False


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", " yes ", "on", "si", "sí"])
def test_la_variable_comun_enciende_los_dos_assets(monkeypatch, valor):
    monkeypatch.setenv(VERBOSE_ENV, valor)

    assert verbose_habilitado("details") is True
    assert verbose_habilitado("files") is True


@pytest.mark.parametrize("valor", ["0", "false", "no", "", "  "])
def test_valores_no_verdaderos_no_encienden(monkeypatch, valor):
    monkeypatch.setenv(VERBOSE_ENV, valor)
    monkeypatch.setenv(VERBOSE_ENV_POR_ASSET["details"], valor)

    assert verbose_habilitado("details") is False


def test_la_variable_por_asset_enciende_solo_el_suyo(monkeypatch):
    monkeypatch.setenv(VERBOSE_ENV_POR_ASSET["details"], "1")

    assert verbose_habilitado("details") is True
    assert verbose_habilitado("files") is False

    monkeypatch.delenv(VERBOSE_ENV_POR_ASSET["details"])
    monkeypatch.setenv(VERBOSE_ENV_POR_ASSET["files"], "1")

    assert verbose_habilitado("details") is False
    assert verbose_habilitado("files") is True
