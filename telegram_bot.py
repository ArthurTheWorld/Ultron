"""Ultron no Telegram (long polling: não precisa de servidor público nem ngrok).

    python telegram_bot.py

Comandos: /ajuda | /voz on | /voz off | /publicar
Na primeira mensagem, o seu ID aparece no terminal. Coloque-o em
TELEGRAM_ALLOWED_IDS no .env e reinicie.
"""
import logging
import os
import threading
import time
from contextlib import contextmanager

import requests

import config
import lembrete
import nucleo
import voz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)  # silencia o "AFC is enabled" repetitivo
log = logging.getLogger("ultron.telegram")

TOKEN = config.obrigatoria("TELEGRAM_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}"
ARQUIVOS = f"https://api.telegram.org/file/bot{TOKEN}"
LIMITE_TEXTO = 4000      # o Telegram aceita até 4096 caracteres por mensagem
LIMITE_LEGENDA = 1024    # legenda de áudio

AJUDA = (
    "Ultron online. Pode mandar texto ou áudio.\n\n"
    "Exemplos:\n"
    "- \"Hoje mandei 20 convites, 5 para recrutadores, e fiz 3 comentários\"\n"
    "- \"Como está a minha semana?\"\n"
    "- Um áudio contando um aprendizado, para virar post\n\n"
    "Comandos:\n"
    "/publicar - publica o último post aprovado (pede confirmação)\n"
    "/voz on | /voz off - liga ou desliga as respostas em áudio\n"
    "/ajuda - mostra esta mensagem"
)


def ids_permitidos(valor: str) -> set[int]:
    permitidos = set()
    for item in valor.replace(" ", "").split(","):
        if item.lstrip("-").isdigit():
            permitidos.add(int(item))
        elif item:
            log.warning("TELEGRAM_ALLOWED_IDS: valor ignorado (não é um ID numérico): %s", item)
    return permitidos


PERMITIDOS = ids_permitidos(os.getenv("TELEGRAM_ALLOWED_IDS", ""))

_opcoes = {
    "voz": os.getenv("ULTRON_VOZ", "on").lower() == "on",
    "legenda": os.getenv("ULTRON_LEGENDA", "on").lower() == "on",
}


def _api(metodo: str, **params) -> dict:
    r = requests.post(f"{API}/{metodo}", json=params, timeout=params.get("timeout", 0) + 30)
    dados = r.json()
    if not dados.get("ok"):
        raise RuntimeError(f"Telegram {metodo}: {dados.get('description')}")
    return dados["result"]


def dividir(texto: str, limite: int = LIMITE_TEXTO) -> list[str]:
    """Quebra textos longos em pedaços, de preferência em fim de parágrafo ou de linha."""
    pedacos = []
    while len(texto) > limite:
        corte = max(texto.rfind("\n\n", 0, limite), texto.rfind("\n", 0, limite))
        if corte <= 0:
            corte = texto.rfind(" ", 0, limite)
        if corte <= 0:
            corte = limite
        pedacos.append(texto[:corte].rstrip())
        texto = texto[corte:].lstrip()
    if texto:
        pedacos.append(texto)
    return pedacos


def enviar(chat_id: int, texto: str) -> None:
    for pedaco in dividir(texto):
        _api("sendMessage", chat_id=chat_id, text=pedaco)


def enviar_voz(chat_id: int, texto: str) -> None:
    """Responde em áudio. Se o TTS falhar (cota, rede), cai para texto em vez de ficar em silêncio."""
    try:
        _api("sendChatAction", chat_id=chat_id, action="record_voice")
        audio = voz.sintetizar(texto)
    except Exception as e:
        log.warning("TTS falhou (%s). Enviando em texto.", e)
        enviar(chat_id, texto)
        return

    dados = {"chat_id": chat_id}
    legenda_cabe = len(texto) <= LIMITE_LEGENDA
    if _opcoes["legenda"] and legenda_cabe:
        dados["caption"] = texto
    r = requests.post(f"{API}/sendVoice", data=dados,
                      files={"voice": ("ultron.ogg", audio, "audio/ogg")}, timeout=60)
    if not r.json().get("ok"):
        log.warning("sendVoice falhou: %s. Enviando em texto.", r.text[:200])
        enviar(chat_id, texto)
        return
    if _opcoes["legenda"] and not legenda_cabe:
        enviar(chat_id, texto)  # texto longo demais para legenda: vai como mensagem separada


@contextmanager
def digitando(chat_id: int):
    """Mantém o "digitando..." visível enquanto o Ultron trabalha.

    O Telegram apaga o indicador após ~5s; sob alta demanda, uma resposta pode levar
    bem mais que isso, e sem o indicador parece que o bot travou.
    """
    parar = threading.Event()

    def manter():
        while not parar.is_set():
            try:
                _api("sendChatAction", chat_id=chat_id, action="typing")
            except Exception:
                pass
            parar.wait(4)

    t = threading.Thread(target=manter, daemon=True)
    t.start()
    try:
        yield
    finally:
        parar.set()


def baixar_arquivo(file_id: str) -> bytes:
    caminho = _api("getFile", file_id=file_id)["file_path"]
    r = requests.get(f"{ARQUIVOS}/{caminho}", timeout=60)
    r.raise_for_status()
    return r.content


def processar(msg: dict) -> None:
    usuario = msg.get("from", {}).get("id")
    chat_id = msg["chat"]["id"]

    if usuario not in PERMITIDOS:
        log.warning("Mensagem ignorada de ID não autorizado: %s (%s). "
                    "Se for você, coloque esse número em TELEGRAM_ALLOWED_IDS no .env.",
                    usuario, msg.get("from", {}).get("first_name"))
        return

    def responder(texto: str, falar: bool = False) -> None:
        if falar and _opcoes["voz"]:
            enviar_voz(chat_id, texto)
        else:
            enviar(chat_id, texto)

    texto = (msg.get("text") or "").strip()
    if texto.lower() in ("/start", "/ajuda", "/help"):
        responder(AJUDA)
        return
    if texto.lower() in ("/voz on", "/voz off"):
        _opcoes["voz"] = texto.lower().endswith("on")
        responder(f"Respostas em áudio {'ativadas' if _opcoes['voz'] else 'desativadas'}.")
        return

    with digitando(chat_id):
        if texto:
            nucleo.tratar(responder, texto=texto)
        elif "voice" in msg or "audio" in msg:
            midia = msg.get("voice") or msg.get("audio")
            audio = baixar_arquivo(midia["file_id"])
            nucleo.tratar(responder, audio=audio, mime=midia.get("mime_type", "audio/ogg").split(";")[0])
        else:
            responder("Por enquanto eu entendo mensagens de texto e áudio.")


def avisar_todos(texto: str) -> None:
    """Usado pelo lembrete diário. Em conversa privada, o chat_id é o próprio ID do usuário."""
    for chat_id in PERMITIDOS:
        try:
            enviar(chat_id, texto)
        except Exception:
            log.exception("Falha ao enviar lembrete para %s", chat_id)


def main() -> None:
    eu = _api("getMe")
    log.info("Ultron conectado como @%s. Voz: %s (%s). Aguardando mensagens (Ctrl+C para sair).",
             eu["username"], "on" if _opcoes["voz"] else "off", voz.NOME_VOZ)
    if PERMITIDOS:
        lembrete.iniciar(avisar_todos)
    else:
        log.warning("TELEGRAM_ALLOWED_IDS vazio: mande uma mensagem ao bot para descobrir o seu ID.")

    offset = None
    while True:
        try:
            atualizacoes = _api("getUpdates", timeout=50, offset=offset, allowed_updates=["message"])
        except requests.RequestException as e:
            log.warning("Falha de rede (%s). Tentando de novo em 5s.", e)
            time.sleep(5)
            continue
        except RuntimeError as e:
            log.error("%s", e)
            time.sleep(5)
            continue

        for upd in atualizacoes:
            offset = upd["update_id"] + 1  # confirma: o Telegram não reenvia esta atualização
            if "message" in upd:
                try:
                    processar(upd["message"])
                except Exception:
                    log.exception("Falha ao processar mensagem")


if __name__ == "__main__":
    main()
