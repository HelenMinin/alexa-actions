"""Armazenamento das anotações em arquivo .txt.

Formato (uma entrada por linha, separada por TAB):

    2026-11-20T10:30:00<TAB>compras<TAB>leite

O arquivo é legível/editável à mão. Para trocar o backend depois (S3,
DynamoDB...), basta criar outra classe com os mesmos métodos `add` e `list`.
"""

import os
import threading
from datetime import datetime

CATEGORIAS = ("compras", "ideias", "lembretes", "anotacoes")

# No AWS Lambda só /tmp é gravável (e ele NÃO é permanente: some quando o
# container é reciclado). Veja o README para a migração para S3/DynamoDB.
if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    _padrao = "/tmp/caderno.txt"
else:
    _padrao = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caderno.txt")

DEFAULT_PATH = os.environ.get("CADERNO_FILE", _padrao)


def _clean(text):
    """Remove quebras de linha e tabs para não quebrar o formato do arquivo."""
    return " ".join(str(text).split())


class TextFileStorage:
    def __init__(self, path=None):
        self.path = path or DEFAULT_PATH
        self._lock = threading.Lock()

    def add(self, categoria, texto, when=None):
        if categoria not in CATEGORIAS:
            raise ValueError("Categoria inválida: %s" % categoria)
        texto = _clean(texto)
        if not texto:
            raise ValueError("Texto vazio")
        when = when or datetime.now()
        line = "%s\t%s\t%s\n" % (when.strftime("%Y-%m-%dT%H:%M:%S"), categoria, texto)
        with self._lock:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)

    def list(self, categoria=None):
        """Retorna lista de dicts {quando, categoria, texto}, da mais antiga à mais nova."""
        if not os.path.exists(self.path):
            return []
        entries = []
        with self._lock, open(self.path, encoding="utf-8") as f:
            for raw in f:
                parts = raw.rstrip("\n").split("\t", 2)
                if len(parts) != 3:
                    continue  # ignora linhas editadas à mão fora do formato
                quando, cat, texto = parts
                if categoria and cat != categoria:
                    continue
                entries.append({"quando": quando, "categoria": cat, "texto": texto})
        return entries
