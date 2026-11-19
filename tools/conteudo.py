"""Fluxo de posts: rascunho, ajustes, aprovação e descarte.

O rascunho em revisão fica salvo em estado/rascunho.json. Assim ele sobrevive a
reinícios do bot (queda de internet, supervisor reiniciando, PC desligado): depois
de voltar, dá para continuar ajustando ou aprovar o mesmo rascunho.
"""
import json

from google.genai import types
from pydantic import BaseModel

import config
from llm import carregar_prompt, cliente

ARQUIVO_RASCUNHO = config.RAIZ / "estado" / "rascunho.json"


class RascunhoPost(BaseModel):
    transcricao: str
    gancho: str
    corpo: str
    fechamento: str
    hashtags: list[str]
    alertas: list[str]


# chat: sessão do Gemini com o histórico de revisão (só em memória).
# rascunho/ajustes: também gravados em disco.
_estado: dict = {"chat": None, "rascunho": None, "ajustes": 0, "carregado": False}
_exibir: list[str] = []  # textos que a interface mostra literalmente ao usuário


# ---------------------------------------------------------------------------
# Persistência do rascunho

def _salvar() -> None:
    r = _estado["rascunho"]
    if r is None:
        ARQUIVO_RASCUNHO.unlink(missing_ok=True)
        return
    ARQUIVO_RASCUNHO.parent.mkdir(exist_ok=True)
    ARQUIVO_RASCUNHO.write_text(json.dumps(
        {"ajustes": _estado["ajustes"], "rascunho": r.model_dump()}, ensure_ascii=False, indent=2,
    ), encoding="utf-8")


def _carregar() -> None:
    """Na primeira chamada, recupera o rascunho salvo antes de um reinício."""
    if _estado["carregado"]:
        return
    _estado["carregado"] = True
    if _estado["rascunho"] is None and ARQUIVO_RASCUNHO.exists():
        try:
            dados = json.loads(ARQUIVO_RASCUNHO.read_text(encoding="utf-8"))
            _estado["rascunho"] = RascunhoPost.model_validate(dados["rascunho"])
            _estado["ajustes"] = int(dados.get("ajustes", 0))
        except (ValueError, KeyError):
            ARQUIVO_RASCUNHO.unlink(missing_ok=True)  # arquivo corrompido: melhor recomeçar


def _limpar() -> None:
    _estado.update(chat=None, rascunho=None, ajustes=0)
    _salvar()


# ---------------------------------------------------------------------------
# Exibição

def texto_do_post(r: RascunhoPost) -> str:
    return f"{r.gancho}\n\n{r.corpo}\n\n{r.fechamento}\n\n{' '.join(r.hashtags)}"


def _registrar_exibicao(r: RascunhoPost) -> None:
    alertas = "\n".join(f"  • {a}" for a in r.alertas) or "  (nenhum)"
    _exibir.append(
        "──────── RASCUNHO ────────\n"
        f"{texto_do_post(r)}\n"
        "──────────────────────────\n"
        f"Alertas:\n{alertas}"
    )


def consumir_exibicao() -> list[str]:
    """Chamado pela interface (CLI, Telegram) para mostrar o rascunho sem paráfrase do modelo."""
    itens = list(_exibir)
    _exibir.clear()
    return itens


# ---------------------------------------------------------------------------
# Gemini

def _novo_chat(historico=None):
    return cliente().chats.create(
        model=config.MODELO,
        config=types.GenerateContentConfig(
            system_instruction=carregar_prompt("post.md"),
            # O modelo de posts não tem ferramentas: sem isso o SDK tenta "chamar funções" à toa.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            response_mime_type="application/json",
            response_schema=RascunhoPost,
        ),
        history=historico,
    )


def _parse(resp) -> RascunhoPost:
    if isinstance(resp.parsed, RascunhoPost):
        return resp.parsed
    return RascunhoPost.model_validate_json(resp.text)


def _resumo(r: RascunhoPost) -> dict:
    return {
        "ok": True,
        "exibido_ao_usuario": True,
        "ajustes_feitos": _estado["ajustes"],
        "alertas": r.alertas,
        "palavras": len(f"{r.gancho} {r.corpo} {r.fechamento}".split()),
    }


# ---------------------------------------------------------------------------
# Ferramentas do agente. As docstrings são lidas pelo Gemini.

def rascunhar_post(transcricao: str) -> dict:
    """Cria um rascunho de post para o LinkedIn a partir do que o usuário contou.

    Use quando ele relatar um aprendizado, experiência ou reflexão profissional para
    virar post, ou pedir explicitamente um post. Substitui qualquer rascunho anterior
    ainda não aprovado. O rascunho é exibido automaticamente para ele.

    Args:
        transcricao: Transcrição fiel e completa do que ele disse sobre o tema, sem resumir, corrigir ou acrescentar nada.
    """
    _carregar()
    chat = _novo_chat()
    resp = chat.send_message(
        "Transcrição do áudio do autor:\n<audio_transcrito>\n"
        f"{transcricao}\n</audio_transcrito>\n\nGere o rascunho."
    )
    r = _parse(resp)
    _estado.update(chat=chat, rascunho=r, ajustes=0)
    _salvar()
    _registrar_exibicao(r)
    return _resumo(r)


def ajustar_post(pedido: str) -> dict:
    """Aplica um ajuste pedido pelo usuário ao rascunho de post em revisão.

    Use quando houver rascunho em revisão e ele pedir mudanças ("deixa o gancho mais
    direto", "tira a hashtag X", "encurta"). A nova versão é exibida automaticamente.

    Args:
        pedido: O ajuste pedido, com as palavras dele.
    """
    _carregar()
    r = _estado["rascunho"]
    if r is None:
        return {"ok": False, "erro": "Não há rascunho em revisão. Peça um novo post primeiro."}
    if _estado["chat"] is None:
        # Rascunho recuperado do disco depois de um reinício: o histórico se perdeu,
        # então o modelo recebe a versão atual inteira antes do pedido.
        _estado["chat"] = _novo_chat()
        mensagem = (f"Versão atual do rascunho (JSON):\n{r.model_dump_json()}\n\n"
                    f"Ajuste pedido pelo autor: {pedido}")
    else:
        mensagem = f"Ajuste pedido pelo autor: {pedido}"
    novo = _parse(_estado["chat"].send_message(mensagem))
    _estado["rascunho"] = novo
    _estado["ajustes"] += 1
    _salvar()
    _registrar_exibicao(novo)
    return _resumo(novo)


def ver_rascunho() -> dict:
    """Mostra de novo o rascunho de post em revisão, sem alterar nada.

    Use quando o usuário pedir para ver, rever ou reenviar o rascunho atual.
    """
    _carregar()
    r = _estado["rascunho"]
    if r is None:
        return {"ok": False, "erro": "Não há rascunho em revisão."}
    _registrar_exibicao(r)
    return _resumo(r)


def aprovar_post() -> dict:
    """Aprova o rascunho em revisão e o salva como pronto para publicar.

    Use SOMENTE quando o usuário aprovar explicitamente ("aprovado", "pode salvar",
    "manda ver"). Elogios ou comentários sobre o texto não são aprovação.
    """
    _carregar()
    r = _estado["rascunho"]
    if r is None:
        return {"ok": False, "erro": "Não há rascunho em revisão para aprovar."}
    aprovado_em = config.agora()
    registro = {
        "id": aprovado_em.strftime("%Y%m%d%H%M%S"),
        "aprovado_em": aprovado_em.isoformat(timespec="seconds"),
        "ajustes": _estado["ajustes"],
        "texto": texto_do_post(r),
        **r.model_dump(),
    }
    with open(config.POSTS_APROVADOS, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    _limpar()
    return {"ok": True, "salvo_em": config.POSTS_APROVADOS.name,
            "proximo_passo": "Para publicar no LinkedIn, o usuário deve enviar o comando /publicar."}


def descartar_post() -> dict:
    """Descarta o rascunho em revisão sem salvar. Use quando ele disser para descartar ou desistir do post."""
    _carregar()
    tinha = _estado["rascunho"] is not None
    _limpar()
    return {"ok": True, "havia_rascunho": tinha}


# ---------------------------------------------------------------------------
# Controle de publicação. NÃO são ferramentas do Gemini: só a interface chama.

def _ler_jsonl(caminho) -> list[dict]:
    if not caminho.exists():
        return []
    with open(caminho, encoding="utf-8") as f:
        return [json.loads(linha) for linha in f if linha.strip()]


def post_pendente_publicacao() -> dict | None:
    """Último post aprovado que ainda não foi publicado."""
    publicados = {p["id"] for p in _ler_jsonl(config.POSTS_PUBLICADOS)}
    pendentes = [p for p in _ler_jsonl(config.POSTS_APROVADOS) if p.get("id") and p["id"] not in publicados]
    return pendentes[-1] if pendentes else None


def marcar_publicado(post_id: str, urn: str) -> None:
    with open(config.POSTS_PUBLICADOS, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": post_id,
            "urn": urn,
            "publicado_em": config.agora().isoformat(timespec="seconds"),
        }, ensure_ascii=False) + "\n")
