"""Armazenamento das anotações em um arquivo .txt (local ou no S3).

Formato (uma entrada por linha, separada por TAB):

    2026-11-20T10:30:00<TAB>compras<TAB>leite

O arquivo é legível/editável à mão. Linhas fora do formato são ignoradas na
leitura e preservadas quando o arquivo é reescrito (remover/limpar).

Backends (mesmos métodos: add, list, remove, clear, count):
  - TextFileStorage: arquivo local (dev, servidor próprio, /tmp no Lambda).
  - S3TextStorage:   o mesmo .txt guardado em um objeto S3 (persistente).

`make_storage()` escolhe pelo ambiente: se `CADERNO_S3_BUCKET` (ou
`S3_PERSISTENCE_BUCKET`, que as skills Alexa-hosted já trazem) estiver
definida, usa S3; senão usa arquivo local.
"""

import os
import tempfile
import threading
import unicodedata
from datetime import datetime

CATEGORIAS = ("compras", "ideias", "lembretes", "anotacoes")

# No AWS Lambda só /tmp é gravável (e ele NÃO é permanente: some quando o
# container é reciclado). Para guardar de verdade, use o S3 (veja o README).
if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    _padrao = "/tmp/caderno.txt"
else:
    _padrao = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caderno.txt")

DEFAULT_PATH = os.environ.get("CADERNO_FILE", _padrao)


def _clean(text):
    """Remove quebras de linha e tabs para não quebrar o formato do arquivo."""
    return " ".join(str(text).split())


def _norm(text):
    """Minúsculas, sem acentos e sem espaços repetidos (para comparar o que foi falado)."""
    decomposto = unicodedata.normalize("NFKD", str(text).lower())
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.split())


def _parse(linha):
    """'quando<TAB>categoria<TAB>texto' -> dict, ou None se a linha estiver fora do formato."""
    partes = linha.split("\t", 2)
    if len(partes) != 3:
        return None
    return {"quando": partes[0], "categoria": partes[1], "texto": partes[2]}


class BaseStorage:
    """Lógica comum. Subclasses só implementam `_read_text` e `_write_text`."""

    def __init__(self):
        self._lock = threading.RLock()

    # --- backend -----------------------------------------------------------
    def _read_text(self):
        raise NotImplementedError

    def _write_text(self, text):
        raise NotImplementedError

    # --- helpers -----------------------------------------------------------
    def _lines(self):
        linhas = self._read_text().split("\n")
        if linhas and linhas[-1] == "":
            linhas.pop()
        return [l.rstrip("\r") for l in linhas]

    def _save(self, linhas):
        self._write_text("".join(l + "\n" for l in linhas))

    # --- API ---------------------------------------------------------------
    def add(self, categoria, texto, when=None):
        if categoria not in CATEGORIAS:
            raise ValueError("Categoria inválida: %s" % categoria)
        texto = _clean(texto)
        if not texto:
            raise ValueError("Texto vazio")
        when = when or datetime.now()
        linha = "%s\t%s\t%s" % (when.strftime("%Y-%m-%dT%H:%M:%S"), categoria, texto)
        with self._lock:
            linhas = self._lines()
            linhas.append(linha)
            self._save(linhas)

    def list(self, categoria=None):
        """Lista de dicts {quando, categoria, texto}, da mais antiga à mais nova."""
        with self._lock:
            entries = [_parse(l) for l in self._lines()]
        return [e for e in entries if e and (not categoria or e["categoria"] == categoria)]

    def count(self, categoria=None):
        return len(self.list(categoria))

    def remove(self, categoria, texto):
        """Remove itens de `categoria` que correspondem a `texto`.

        Compara sem acento/maiúsculas. Se houver itens exatamente iguais, remove
        só eles; senão remove os que contêm o texto falado (ex.: "pão" apaga
        "pão francês"). Devolve a lista dos textos removidos (vazia se nada casou).
        """
        alvo = _norm(_clean(texto))
        if not alvo:
            return []
        with self._lock:
            linhas = self._lines()
            candidatos = []  # (índice da linha, texto normalizado)
            for i, linha in enumerate(linhas):
                e = _parse(linha)
                if e and e["categoria"] == categoria:
                    candidatos.append((i, e["texto"], _norm(e["texto"])))
            exatos = [c for c in candidatos if c[2] == alvo]
            casados = exatos or [c for c in candidatos if alvo in c[2]]
            if not casados:
                return []
            apagar = {c[0] for c in casados}
            self._save([l for i, l in enumerate(linhas) if i not in apagar])
            return [c[1] for c in casados]

    def clear(self, categoria=None):
        """Apaga todos os itens de `categoria` (ou do caderno todo se None). Devolve quantos."""
        with self._lock:
            linhas = self._lines()
            manter, apagados = [], 0
            for linha in linhas:
                e = _parse(linha)
                if e and (categoria is None or e["categoria"] == categoria):
                    apagados += 1
                else:
                    manter.append(linha)
            if apagados:
                self._save(manter)
            return apagados


class TextFileStorage(BaseStorage):
    def __init__(self, path=None):
        super().__init__()
        self.path = path or DEFAULT_PATH

    def _read_text(self):
        if not os.path.exists(self.path):
            return ""
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def _write_text(self, text):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # grava em arquivo temporário e troca: nunca deixa o caderno pela metade
        fd, tmp = tempfile.mkstemp(dir=directory or ".", prefix=".caderno-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise


class S3TextStorage(BaseStorage):
    """Mesmo .txt, guardado em s3://bucket/key.

    Permissões IAM necessárias no objeto: s3:GetObject e s3:PutObject. Dê também
    s3:ListBucket no bucket: sem ele o S3 responde "acesso negado" (e não
    "não existe") quando o arquivo ainda não foi criado.
    """

    def __init__(self, bucket, key="caderno.txt", client=None):
        super().__init__()
        self.bucket = bucket
        self.key = key
        if client is None:
            import boto3  # já vem no runtime do Lambda / Alexa-hosted

            client = boto3.client("s3")
        self.client = client

    def _read_text(self):
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self.key)
        except Exception as e:  # botocore.exceptions.ClientError
            codigo = (getattr(e, "response", None) or {}).get("Error", {}).get("Code")
            if codigo in ("NoSuchKey", "404"):
                return ""
            raise
        return obj["Body"].read().decode("utf-8")

    def _write_text(self, text):
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=text.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )


def make_storage():
    bucket = os.environ.get("CADERNO_S3_BUCKET") or os.environ.get("S3_PERSISTENCE_BUCKET")
    if bucket:
        return S3TextStorage(bucket, os.environ.get("CADERNO_S3_KEY", "caderno.txt"))
    return TextFileStorage()
