import json
from datetime import date, datetime, time

import pytest

import lembrete
import nucleo
from tools import conteudo, registro


def rascunho(gancho="Gancho"):
    return conteudo.RascunhoPost(transcricao="t", gancho=gancho, corpo="Corpo", fechamento="Fim",
                                 hashtags=["#dbt"], alertas=[])


# rascunho persistente --------------------------------------------------------

def test_rascunho_sobrevive_a_reinicio():
    conteudo._estado.update(rascunho=rascunho(), ajustes=2, carregado=True)
    conteudo._salvar()

    conteudo._estado.update(chat=None, rascunho=None, ajustes=0, carregado=False)  # "reiniciou"
    r = conteudo.ver_rascunho()

    assert r["ok"] and r["ajustes_feitos"] == 2
    assert "Gancho" in conteudo.consumir_exibicao()[0]


def test_ajuste_depois_de_reinicio_manda_a_versao_atual(monkeypatch):
    conteudo._estado.update(rascunho=rascunho(), ajustes=0, carregado=True)
    conteudo._salvar()
    conteudo._estado.update(chat=None, rascunho=None, carregado=False)

    enviadas = []

    class ChatFalso:
        def send_message(self, mensagem):
            enviadas.append(mensagem)
            return type("R", (), {"parsed": rascunho("Novo gancho")})()

    monkeypatch.setattr(conteudo, "_novo_chat", lambda historico=None: ChatFalso())
    r = conteudo.ajustar_post("encurta")

    assert r["ok"] and r["ajustes_feitos"] == 1
    assert '"gancho":"Gancho"' in enviadas[0] and "encurta" in enviadas[0]
    salvo = json.loads(conteudo.ARQUIVO_RASCUNHO.read_text(encoding="utf-8"))
    assert salvo["rascunho"]["gancho"] == "Novo gancho"


def test_aprovar_grava_e_apaga_o_rascunho():
    conteudo._estado.update(rascunho=rascunho(), carregado=True)
    conteudo._salvar()

    assert conteudo.aprovar_post()["ok"]
    assert not conteudo.ARQUIVO_RASCUNHO.exists()
    assert conteudo.post_pendente_publicacao()["gancho"] == "Gancho"


def test_rascunho_corrompido_e_ignorado():
    conteudo.ARQUIVO_RASCUNHO.parent.mkdir()
    conteudo.ARQUIVO_RASCUNHO.write_text("{quebrado", encoding="utf-8")
    assert conteudo.ver_rascunho()["ok"] is False
    assert not conteudo.ARQUIVO_RASCUNHO.exists()


# confirmação de publicação ----------------------------------------------------

@pytest.fixture
def canal(monkeypatch):
    saida, agente = [], []

    class AgenteFalso:
        def responder(self, texto=None, audio=None, mime=None):
            agente.append(texto or "<audio>")
            return "resposta"

    monkeypatch.setattr(nucleo, "_ultron", AgenteFalso())
    monkeypatch.setattr(nucleo.linkedin, "dias_para_expirar", lambda: 30)
    publicados = []
    monkeypatch.setattr(nucleo.linkedin, "publicar",
                        lambda texto: publicados.append(texto) or {"ok": True, "urn": "urn:1", "url": "u"})
    nucleo._confirmacao["post"] = None
    conteudo._estado.update(rascunho=rascunho(), carregado=True)
    conteudo.aprovar_post()

    def enviar(texto, falar=False):
        saida.append(texto)

    return enviar, saida, agente, publicados


def test_sim_publica(canal):
    enviar, saida, agente, publicados = canal
    nucleo.tratar(enviar, texto="/publicar")
    nucleo.tratar(enviar, texto="Sim!")
    assert publicados and "Publicado" in saida[-1]
    assert conteudo.post_pendente_publicacao() is None
    assert agente == []


def test_nao_cancela_sem_chamar_o_agente(canal):
    enviar, saida, agente, publicados = canal
    nucleo.tratar(enviar, texto="/publicar")
    nucleo.tratar(enviar, texto="não")
    assert not publicados and "cancelada" in saida[-1]
    assert agente == []


def test_outra_mensagem_cancela_e_segue_para_o_agente(canal):
    enviar, saida, agente, publicados = canal
    nucleo.tratar(enviar, texto="/publicar")
    nucleo.tratar(enviar, texto="mandei 10 convites hoje")
    assert not publicados
    assert any("cancelada" in s for s in saida)
    assert agente == ["mandei 10 convites hoje"]


def test_audio_durante_confirmacao_nao_se_perde(canal):
    enviar, saida, agente, publicados = canal
    nucleo.tratar(enviar, texto="/publicar")
    nucleo.tratar(enviar, audio=b"ogg")
    assert not publicados and agente == ["<audio>"]


# lembrete diário --------------------------------------------------------------

def test_deve_verificar_so_depois_do_horario_e_uma_vez_por_dia():
    nove = time(21, 0)
    assert not lembrete.deve_verificar(datetime(2026, 11, 18, 20, 59), nove, None)
    assert lembrete.deve_verificar(datetime(2026, 11, 18, 21, 0), nove, None)
    assert not lembrete.deve_verificar(datetime(2026, 11, 18, 22, 0), nove, date(2026, 11, 18))
    assert lembrete.deve_verificar(datetime(2026, 11, 19, 21, 30), nove, date(2026, 11, 18))


def test_lembra_uma_vez_quando_o_dia_esta_vazio(tmp_path, monkeypatch):
    monkeypatch.setattr(lembrete, "ARQUIVO", tmp_path / "lembrete.txt")
    monkeypatch.setattr(registro, "dia_tem_registro", lambda dia: False)
    avisos = []
    agora = datetime(2026, 11, 18, 21, 5)

    assert lembrete.verificar(agora, time(21, 0), avisos.append)
    assert not lembrete.verificar(agora, time(21, 0), avisos.append)
    assert len(avisos) == 1


def test_nao_lembra_quando_ja_registrou(tmp_path, monkeypatch):
    monkeypatch.setattr(lembrete, "ARQUIVO", tmp_path / "lembrete.txt")
    monkeypatch.setattr(registro, "dia_tem_registro", lambda dia: True)
    avisos = []
    assert not lembrete.verificar(datetime(2026, 11, 18, 21, 5), time(21, 0), avisos.append)
    assert avisos == []


@pytest.mark.parametrize("valor,esperado", [
    ("21:30", time(21, 30)), ("off", None), ("", None), ("25:99", None),
])
def test_horario_configurado(monkeypatch, valor, esperado):
    monkeypatch.setenv("ULTRON_LEMBRETE", valor)
    assert lembrete.horario_configurado() == esperado
