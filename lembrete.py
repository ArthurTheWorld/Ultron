"""Lembrete diário: avisa quando a rotina do dia ainda não foi registrada.

Configure no .env com ULTRON_LEMBRETE=HH:MM (padrão 21:00) ou ULTRON_LEMBRETE=off.
O último dia lembrado fica em estado/lembrete.txt, então reiniciar o bot à noite
não repete o aviso.
"""
import logging
import os
import threading
from datetime import date, datetime, time
from typing import Callable

import config
from tools import registro

log = logging.getLogger("ultron.lembrete")

ARQUIVO = config.RAIZ / "estado" / "lembrete.txt"
INTERVALO = 60  # segundos entre verificações

MENSAGEM = ("Ainda não há nada registrado hoje. Quando puder, me conte o que fez no LinkedIn: "
            "convites, comentários, conversas. Se hoje foi dia de folga, tudo bem também.")


def horario_configurado() -> time | None:
    """Horário do lembrete, ou None se desativado/ inválido."""
    valor = os.getenv("ULTRON_LEMBRETE", "21:00").strip().lower()
    if valor in ("", "off", "0", "nao", "não"):
        return None
    try:
        return datetime.strptime(valor, "%H:%M").time()
    except ValueError:
        log.warning("ULTRON_LEMBRETE inválido (%s). Use HH:MM ou off. Lembrete desativado.", valor)
        return None


def deve_verificar(agora: datetime, horario: time, ultimo: date | None) -> bool:
    """Já passou do horário de hoje e ainda não lembramos hoje?"""
    return agora.time() >= horario and ultimo != agora.date()


def _ler_ultimo() -> date | None:
    try:
        return date.fromisoformat(ARQUIVO.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _gravar_ultimo(dia: date) -> None:
    ARQUIVO.parent.mkdir(exist_ok=True)
    ARQUIVO.write_text(dia.isoformat(), encoding="utf-8")


def verificar(agora: datetime, horario: time, avisar: Callable[[str], None]) -> bool:
    """Uma rodada. Retorna True se enviou o lembrete."""
    if not deve_verificar(agora, horario, _ler_ultimo()):
        return False
    tem = registro.dia_tem_registro(agora.date())
    _gravar_ultimo(agora.date())  # grava antes de avisar: nunca dois lembretes no mesmo dia
    if tem is False:
        avisar(MENSAGEM)
        return True
    return False


def iniciar(avisar: Callable[[str], None]) -> threading.Thread | None:
    """Liga o lembrete em segundo plano. avisar(texto) manda a mensagem ao usuário."""
    horario = horario_configurado()
    if horario is None:
        log.info("Lembrete diário desativado.")
        return None

    def laco():
        while True:
            try:
                verificar(config.agora(), horario, avisar)
            except Exception:  # planilha fora do ar etc.: tenta de novo no próximo ciclo
                log.exception("Falha ao verificar o lembrete")
            threading.Event().wait(INTERVALO)

    t = threading.Thread(target=laco, name="lembrete", daemon=True)
    t.start()
    log.info("Lembrete diário às %s.", horario.strftime("%H:%M"))
    return t
