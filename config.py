"""Configuração central do Ultron. Tudo que muda entre ambientes vem do .env."""
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")


class ConfiguracaoFaltando(RuntimeError):
    """Variável obrigatória ausente no .env."""


def obrigatoria(nome: str) -> str:
    """Lê uma variável obrigatória com uma mensagem que diz o que fazer."""
    valor = os.getenv(nome, "").strip()
    if not valor:
        raise ConfiguracaoFaltando(
            f"A variável {nome} não está definida. Copie .env.example para .env e preencha {nome}."
        )
    return valor


def _caminho(valor: str) -> Path:
    """Aceita caminho absoluto ou relativo à raiz do projeto."""
    p = Path(valor)
    return p if p.is_absolute() else RAIZ / p


GEMINI_API_KEY = obrigatoria("GEMINI_API_KEY")
MODELO = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# Usado quando o modelo principal está sobrecarregado. Deixe vazio para desativar.
MODELO_RESERVA = os.getenv("GEMINI_MODEL_RESERVA", "gemini-2.5-flash-lite")

GOOGLE_CREDENTIALS = _caminho(obrigatoria("GOOGLE_CREDENTIALS"))
PLANILHA_ID = obrigatoria("PLANILHA_ID")

# Como o Ultron chama você nas conversas e nos prompts.
USUARIO = os.getenv("ULTRON_USUARIO", "").strip() or "Arthur"

FUSO = ZoneInfo(os.getenv("ULTRON_FUSO", "").strip() or "America/Sao_Paulo")
PROMPTS = RAIZ / "prompts"
POSTS_APROVADOS = RAIZ / "posts_aprovados.jsonl"
POSTS_PUBLICADOS = RAIZ / "posts_publicados.jsonl"


def agora() -> datetime:
    return datetime.now(FUSO)


def hoje() -> date:
    return agora().date()
