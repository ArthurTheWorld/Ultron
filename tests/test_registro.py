from datetime import date

import pytest

import planilha
from tools import registro


@pytest.fixture
def planilha_falsa(monkeypatch):
    """Planilha em memória: {(aba, intervalo): linha}."""
    dados: dict = {}
    monkeypatch.setattr(planilha, "data_inicio", lambda: date(2026, 11, 2))
    monkeypatch.setattr(planilha, "ler", lambda aba, intervalo: list(dados.get((aba, intervalo), [])))
    monkeypatch.setattr(planilha, "escrever",
                        lambda aba, intervalo, linha: dados.__setitem__((aba, intervalo), list(linha)))
    return dados


def test_somar_acumula_no_mesmo_dia(planilha_falsa):
    registro.registrar_dia("2026-11-18", convites=10)
    r = registro.registrar_dia("2026-11-18", convites=5, comentarios=2)
    assert r["ok"]
    assert r["totais_do_dia"]["convites"] == 15
    assert r["totais_do_dia"]["comentarios"] == 2


def test_corrigir_substitui(planilha_falsa):
    registro.registrar_dia("2026-11-18", convites=25)
    r = registro.registrar_dia("2026-11-18", modo="corrigir", convites=20)
    assert r["totais_do_dia"]["convites"] == 20


def test_observacoes_somam_com_separador(planilha_falsa):
    registro.registrar_dia("2026-11-18", observacoes="primeira")
    r = registro.registrar_dia("2026-11-18", observacoes="segunda")
    assert r["totais_do_dia"]["observacoes"] == "primeira | segunda"


def test_avisa_quando_recrutadores_passam_do_total(planilha_falsa):
    r = registro.registrar_dia("2026-11-18", convites=3, convites_recrutadores=5)
    assert r["avisos"]


def test_rejeita_negativos_data_invalida_e_vazio(planilha_falsa):
    assert registro.registrar_dia("2026-11-18", convites=-1)["ok"] is False
    assert registro.registrar_dia("18/11/2026", convites=1)["ok"] is False
    assert registro.registrar_dia("2026-11-18")["ok"] is False
    assert registro.registrar_dia("2030-01-01", convites=1)["ok"] is False
    assert planilha_falsa == {}  # nada foi gravado


def test_dia_tem_registro(planilha_falsa):
    assert registro.dia_tem_registro(date(2026, 11, 18)) is False
    registro.registrar_dia("2026-11-18", rotina_feita=True)
    assert registro.dia_tem_registro(date(2026, 11, 18)) is True
    assert registro.dia_tem_registro(date(2030, 1, 1)) is None
