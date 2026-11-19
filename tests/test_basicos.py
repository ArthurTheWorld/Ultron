from datetime import date, timedelta

import pytest

import config
import llm
import planilha
import telegram_bot
from tools import linkedin


# config ---------------------------------------------------------------------

def test_variavel_obrigatoria_ausente_explica_o_que_fazer(monkeypatch):
    monkeypatch.delenv("PLANILHA_ID", raising=False)
    with pytest.raises(config.ConfiguracaoFaltando, match="PLANILHA_ID"):
        config.obrigatoria("PLANILHA_ID")


def test_variavel_so_com_espacos_conta_como_ausente(monkeypatch):
    monkeypatch.setenv("PLANILHA_ID", "   ")
    with pytest.raises(config.ConfiguracaoFaltando):
        config.obrigatoria("PLANILHA_ID")


# prompts --------------------------------------------------------------------

def test_prompt_preenche_usuario_perfil_e_exemplo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROMPTS", tmp_path)
    (tmp_path / "p.md").write_text("Olá {usuario}.\n{perfil}\n{exemplo}", encoding="utf-8")
    (tmp_path / "perfil.exemplo.md").write_text("perfil genérico", encoding="utf-8")
    (tmp_path / "perfil.md").write_text("engenheiro de dados", encoding="utf-8")
    (tmp_path / "exemplo_post.md").write_text("meu post", encoding="utf-8")

    texto = llm.carregar_prompt("p.md")

    assert "Olá Arthur." in texto
    assert "engenheiro de dados" in texto and "genérico" not in texto
    assert "<exemplo>\nmeu post\n</exemplo>" in texto


def test_prompt_sem_perfil_pessoal_usa_o_modelo_e_sem_exemplo_avisa(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROMPTS", tmp_path)
    (tmp_path / "p.md").write_text("{perfil}|{exemplo}", encoding="utf-8")
    (tmp_path / "perfil.exemplo.md").write_text("perfil genérico", encoding="utf-8")

    texto = llm.carregar_prompt("p.md")

    assert texto.startswith("perfil genérico|")
    assert "Nenhum post de exemplo" in texto


def test_prompts_reais_nao_tem_marcador_sobrando():
    for nome in ("ultron.md", "post.md"):
        texto = llm.carregar_prompt(nome)
        assert "{usuario}" not in texto and "{perfil}" not in texto and "{exemplo}" not in texto
        assert "Gustavo" not in texto and "Jarvis" not in texto


# planilha -------------------------------------------------------------------

def test_linha_do_dia_e_conta_simples(monkeypatch):
    monkeypatch.setattr(planilha, "data_inicio", lambda: date(2026, 11, 2))
    assert planilha.linha_do_dia(date(2026, 11, 2)) == 5
    assert planilha.linha_do_dia(date(2026, 11, 18)) == 21


def test_linha_do_dia_fora_do_periodo(monkeypatch):
    monkeypatch.setattr(planilha, "data_inicio", lambda: date(2026, 11, 2))
    with pytest.raises(planilha.ForaDoIntervalo):
        planilha.linha_do_dia(date(2026, 11, 1))
    with pytest.raises(planilha.ForaDoIntervalo):
        planilha.linha_do_dia(date(2026, 11, 2) + timedelta(days=84))


# linkedin -------------------------------------------------------------------

def test_commentary_escapa_reservados_e_cria_hashtags():
    saida = linkedin.formatar_commentary("Pipeline (dbt) @ 100% #DataEngineering")
    assert r"\(dbt\)" in saida
    assert r"\@" in saida
    assert "{hashtag|\\#|DataEngineering}" in saida


def test_versao_api_volta_dois_meses_inclusive_na_virada_do_ano(monkeypatch):
    monkeypatch.delenv("LINKEDIN_VERSION", raising=False)

    class Janeiro(date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 15)

    monkeypatch.setattr(linkedin, "date", Janeiro)
    assert linkedin._versao_api() == "202611"


def test_versao_api_fixada_no_env(monkeypatch):
    monkeypatch.setenv("LINKEDIN_VERSION", "202601")
    assert linkedin._versao_api() == "202601"


# telegram -------------------------------------------------------------------

def test_dividir_prefere_quebra_de_paragrafo():
    texto = "a" * 30 + "\n\n" + "b" * 30
    assert telegram_bot.dividir(texto, limite=40) == ["a" * 30, "b" * 30]


def test_dividir_texto_sem_espaco_corta_no_limite():
    assert telegram_bot.dividir("x" * 25, limite=10) == ["x" * 10, "x" * 10, "x" * 5]


def test_ids_permitidos_ignora_lixo():
    assert telegram_bot.ids_permitidos("123, abc, 456,") == {123, 456}
