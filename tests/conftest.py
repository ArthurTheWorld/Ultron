"""Testes rodam sem rede e sem chaves reais: variáveis falsas e arquivos em pasta temporária."""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Precisam existir antes de importar config. Valores falsos: nada sai para a rede.
os.environ.update({
    "GEMINI_API_KEY": "teste",
    "GOOGLE_CREDENTIALS": "credenciais/teste.json",
    "PLANILHA_ID": "teste",
    "TELEGRAM_TOKEN": "123:teste",
    "ULTRON_USUARIO": "Arthur",
})

import pytest  # noqa: E402

import config  # noqa: E402
from tools import conteudo  # noqa: E402


@pytest.fixture(autouse=True)
def arquivos_temporarios(tmp_path, monkeypatch):
    """Nenhum teste escreve na pasta real do projeto."""
    monkeypatch.setattr(config, "POSTS_APROVADOS", tmp_path / "posts_aprovados.jsonl")
    monkeypatch.setattr(config, "POSTS_PUBLICADOS", tmp_path / "posts_publicados.jsonl")
    monkeypatch.setattr(conteudo, "ARQUIVO_RASCUNHO", tmp_path / "estado" / "rascunho.json")
    conteudo._estado.update(chat=None, rascunho=None, ajustes=0, carregado=False)
    conteudo._exibir.clear()
    yield tmp_path
