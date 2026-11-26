# -*- coding: utf-8 -*-
"""Testes ponta a ponta: envia envelopes de requisição Alexa para o handler."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))

import lambda_function as skill  # noqa: E402
from storage import S3TextStorage, TextFileStorage, make_storage  # noqa: E402


def envelope(request, new=True, attrs=None):
    return {
        "version": "1.0",
        "session": {
            "new": new,
            "sessionId": "amzn1.echo-api.session.1",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.test"},
            "attributes": attrs or {},
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.test"},
                "device": {"deviceId": "dev", "supportedInterfaces": {}},
                "apiEndpoint": "https://api.amazonalexa.com",
            }
        },
        "request": dict(
            request,
            requestId="amzn1.echo-api.request.1",
            timestamp="2026-11-20T10:00:00Z",
            locale="pt-BR",
        ),
    }


def intent(name, slots=None, **kw):
    return envelope(
        {"type": "IntentRequest", "intent": {"name": name, "slots": slots or {}, "confirmationStatus": "NONE"}},
        **kw
    )


def texto(valor):
    return {"texto": {"name": "texto", "value": valor, "confirmationStatus": "NONE"}}


def categoria(cat_id, nome):
    return {
        "categoria": {
            "name": "categoria",
            "value": nome,
            "confirmationStatus": "NONE",
            "resolutions": {
                "resolutionsPerAuthority": [
                    {
                        "authority": "amzn1.er-authority.echo-sdk.x.CATEGORIA",
                        "status": {"code": "ER_SUCCESS_MATCH"},
                        "values": [{"value": {"name": nome, "id": cat_id}}],
                    }
                ]
            },
        }
    }


class SkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "caderno.txt")
        skill.storage = TextFileStorage(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, ev):
        return skill.lambda_handler(ev, None)

    def fala(self, resp):
        return resp["response"]["outputSpeech"]["ssml"]

    def test_launch(self):
        r = self.call(envelope({"type": "LaunchRequest"}))
        self.assertIn("Meu Caderno", self.fala(r))
        self.assertFalse(r["response"]["shouldEndSession"])

    def test_add_compra_salva_no_txt_e_encerra(self):
        r = self.call(intent("AddCompraIntent", texto("leite")))
        self.assertIn("Adicionei leite", self.fala(r))
        self.assertTrue(r["response"]["shouldEndSession"])
        with open(self.path, encoding="utf-8") as f:
            linhas = f.read().splitlines()
        self.assertEqual(len(linhas), 1)
        _, cat, txt = linhas[0].split("\t")
        self.assertEqual((cat, txt), ("compras", "leite"))

    def test_compras_com_varios_itens(self):
        self.call(intent("AddCompraIntent", texto("leite, pão e ovos")))
        self.assertEqual([e["texto"] for e in skill.storage.list("compras")], ["leite", "pão", "ovos"])

    def test_add_mantem_sessao_aberta_se_ja_conversando(self):
        r = self.call(intent("AddIdeiaIntent", texto("app de receitas"), new=False))
        self.assertFalse(r["response"]["shouldEndSession"])

    def test_cada_categoria(self):
        self.call(intent("AddIdeiaIntent", texto("app de receitas")))
        self.call(intent("AddLembreteIntent", texto("ligar pro dentista")))
        self.call(intent("AddAnotacaoIntent", texto("a senha do wifi mudou")))
        self.assertEqual(len(skill.storage.list("ideias")), 1)
        self.assertEqual(len(skill.storage.list("lembretes")), 1)
        self.assertEqual(len(skill.storage.list("anotacoes")), 1)

    def test_ler_categoria(self):
        for i in ("leite", "pão", "ovos"):
            skill.storage.add("compras", i)
        r = self.call(intent("LerIntent", categoria("compras", "lista de compras")))
        self.assertIn("Você tem 3 itens na lista de compras: leite, pão e ovos.", self.fala(r))

    def test_ler_singular(self):
        skill.storage.add("ideias", "app de receitas")
        r = self.call(intent("LerIntent", categoria("ideias", "ideias")))
        self.assertIn("Você tem 1 ideia: app de receitas.", self.fala(r))

    def test_ler_vazio(self):
        r = self.call(intent("LerIntent", categoria("compras", "compras")))
        self.assertIn("vazia", self.fala(r))

    def test_ler_tudo(self):
        skill.storage.add("compras", "leite")
        skill.storage.add("ideias", "app")
        r = self.call(intent("LerIntent"))
        fala = self.fala(r)
        self.assertIn("leite", fala)
        self.assertIn("app", fala)

    def test_ler_tudo_vazio(self):
        r = self.call(intent("LerIntent"))
        self.assertIn("vazio", self.fala(r))

    def test_ler_limita_itens(self):
        for i in range(30):
            skill.storage.add("anotacoes", "nota%d" % i)
        fala = self.fala(self.call(intent("LerIntent", categoria("anotacoes", "anotações"))))
        self.assertIn("Você tem 30 anotações", fala)
        self.assertIn("nota29", fala)
        self.assertNotIn("nota0,", fala)

    def test_ssml_escapa_caracteres_especiais(self):
        skill.storage.add("anotacoes", "p&g <b>")
        fala = self.fala(self.call(intent("LerIntent", categoria("anotacoes", "anotações"))))
        self.assertIn("p&amp;g &lt;b&gt;", fala)

    def test_texto_vazio(self):
        r = self.call(intent("AddIdeiaIntent", {"texto": {"name": "texto", "confirmationStatus": "NONE"}}))
        self.assertIn("Não entendi", self.fala(r))
        self.assertEqual(skill.storage.list(), [])

    def test_tab_e_quebra_de_linha_nao_quebram_formato(self):
        skill.storage.add("anotacoes", "linha1\nlinha2\tcoluna")
        self.assertEqual(skill.storage.list()[0]["texto"], "linha1 linha2 coluna")

    def test_persiste_entre_instancias(self):
        skill.storage.add("compras", "café")
        outra = TextFileStorage(self.path)
        self.assertEqual(outra.list("compras")[0]["texto"], "café")

    def test_stop_help_fallback(self):
        self.assertIn("Até logo", self.fala(self.call(intent("AMAZON.StopIntent"))))
        self.assertIn("Para anotar", self.fala(self.call(intent("AMAZON.HelpIntent"))))
        self.assertIn("Não entendi", self.fala(self.call(intent("AMAZON.FallbackIntent"))))

    def test_erro_de_armazenamento_vira_mensagem_amigavel(self):
        skill.storage = TextFileStorage(self.tmp.name)  # diretório, não arquivo
        r = self.call(intent("AddCompraIntent", texto("leite")))
        self.assertIn("problema", self.fala(r))

    # ---------- remover ----------
    def test_remover_item_da_lista(self):
        for i in ("leite", "pão", "ovos"):
            skill.storage.add("compras", i)
        r = self.call(intent("RemoverCompraIntent", texto("Pão")))
        self.assertIn("Removi pão da lista de compras.", self.fala(r))
        self.assertEqual([e["texto"] for e in skill.storage.list("compras")], ["leite", "ovos"])

    def test_remover_ignora_acento_e_maiuscula(self):
        skill.storage.add("compras", "Pão")
        r = self.call(intent("RemoverCompraIntent", texto("pao")))
        self.assertIn("Removi", self.fala(r))
        self.assertEqual(skill.storage.list("compras"), [])

    def test_remover_prefere_igual_exato_a_parcial(self):
        skill.storage.add("compras", "pão")
        skill.storage.add("compras", "pão de queijo")
        self.call(intent("RemoverCompraIntent", texto("pão")))
        self.assertEqual([e["texto"] for e in skill.storage.list("compras")], ["pão de queijo"])

    def test_remover_parcial_avisa_o_que_removeu(self):
        skill.storage.add("compras", "pão francês")
        r = self.call(intent("RemoverCompraIntent", texto("pão")))
        self.assertIn("Removi pão francês", self.fala(r))

    def test_remover_nao_encontrado(self):
        skill.storage.add("compras", "leite")
        r = self.call(intent("RemoverCompraIntent", texto("queijo")))
        self.assertIn("Não encontrei queijo na lista de compras.", self.fala(r))
        self.assertEqual(len(skill.storage.list("compras")), 1)

    def test_remover_so_mexe_na_categoria_certa(self):
        skill.storage.add("compras", "wifi")
        skill.storage.add("anotacoes", "senha do wifi mudou")
        self.call(intent("RemoverAnotacaoIntent", texto("wifi")))
        self.assertEqual(len(skill.storage.list("compras")), 1)
        self.assertEqual(skill.storage.list("anotacoes"), [])

    def test_remover_sem_texto(self):
        r = self.call(intent("RemoverIdeiaIntent", {"texto": {"name": "texto", "confirmationStatus": "NONE"}}))
        self.assertIn("Não entendi", self.fala(r))

    def test_remover_preserva_linhas_fora_do_formato(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("comentário solto\n")
        skill.storage.add("compras", "leite")
        self.call(intent("RemoverCompraIntent", texto("leite")))
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "comentário solto\n")

    def test_remover_ssml_escapa_texto_digitado(self):
        r = self.call(intent("RemoverCompraIntent", texto("p&g")))
        self.assertIn("p&amp;g", self.fala(r))

    # ---------- limpar ----------
    def test_limpar_pede_confirmacao_e_nao_apaga_ainda(self):
        skill.storage.add("compras", "leite")
        skill.storage.add("compras", "pão")
        r = self.call(intent("LimparIntent", categoria("compras", "lista de compras")))
        self.assertIn("Quer mesmo apagar 2 itens na lista de compras?", self.fala(r))
        self.assertFalse(r["response"]["shouldEndSession"])
        self.assertEqual(len(skill.storage.list("compras")), 2)

    def test_limpar_sim_apaga_so_a_categoria(self):
        skill.storage.add("compras", "leite")
        skill.storage.add("ideias", "app")
        r1 = self.call(intent("LimparIntent", categoria("compras", "lista de compras")))
        r2 = self.call(intent("AMAZON.YesIntent", new=False, attrs=r1["sessionAttributes"]))
        self.assertIn("limpei a lista de compras", self.fala(r2))
        self.assertEqual(skill.storage.list("compras"), [])
        self.assertEqual(len(skill.storage.list("ideias")), 1)

    def test_limpar_nao_mantem_tudo(self):
        skill.storage.add("compras", "leite")
        r1 = self.call(intent("LimparIntent", categoria("compras", "compras")))
        r2 = self.call(intent("AMAZON.NoIntent", new=False, attrs=r1["sessionAttributes"]))
        self.assertIn("não apaguei nada", self.fala(r2))
        self.assertEqual(len(skill.storage.list("compras")), 1)

    def test_limpar_tudo(self):
        skill.storage.add("compras", "leite")
        skill.storage.add("ideias", "app")
        r1 = self.call(intent("LimparIntent"))
        self.assertIn("apagar tudo do caderno, 2 entradas", self.fala(r1))
        self.call(intent("AMAZON.YesIntent", new=False, attrs=r1["sessionAttributes"]))
        self.assertEqual(skill.storage.list(), [])

    def test_limpar_lista_desconhecida_nunca_vira_tudo(self):
        skill.storage.add("compras", "leite")
        slots = {"categoria": {"name": "categoria", "value": "geladeira", "confirmationStatus": "NONE"}}
        r = self.call(intent("LimparIntent", slots))
        self.assertIn("Não entendi qual lista", self.fala(r))
        self.assertNotIn("pendente_limpar", r.get("sessionAttributes") or {})
        self.assertEqual(len(skill.storage.list("compras")), 1)

    def test_limpar_lista_vazia(self):
        r = self.call(intent("LimparIntent", categoria("compras", "compras")))
        self.assertIn("vazia", self.fala(r))
        self.assertNotIn("pendente_limpar", r.get("sessionAttributes") or {})

    def test_sim_sem_pendencia_nao_apaga(self):
        skill.storage.add("compras", "leite")
        r = self.call(intent("AMAZON.YesIntent", new=False))
        self.assertIn("nada pendente", self.fala(r))
        self.assertEqual(len(skill.storage.list("compras")), 1)

    def test_pedido_intermediario_cancela_confirmacao(self):
        skill.storage.add("compras", "leite")
        r1 = self.call(intent("LimparIntent", categoria("compras", "compras")))
        r2 = self.call(intent("LerIntent", categoria("compras", "compras"), new=False, attrs=r1["sessionAttributes"]))
        r3 = self.call(intent("AMAZON.YesIntent", new=False, attrs=r2.get("sessionAttributes")))
        self.assertIn("nada pendente", self.fala(r3))
        self.assertEqual(len(skill.storage.list("compras")), 1)

    # ---------- contar ----------
    def test_contar_categoria(self):
        for i in ("leite", "pão", "ovos"):
            skill.storage.add("compras", i)
        r = self.call(intent("ContarIntent", categoria("compras", "lista de compras")))
        self.assertIn("Você tem 3 itens na lista de compras.", self.fala(r))

    def test_contar_singular_e_vazio(self):
        skill.storage.add("ideias", "app")
        self.assertIn("Você tem 1 ideia.", self.fala(self.call(intent("ContarIntent", categoria("ideias", "ideias")))))
        self.assertIn("vazia", self.fala(self.call(intent("ContarIntent", categoria("compras", "compras")))))

    def test_contar_tudo(self):
        skill.storage.add("compras", "leite")
        skill.storage.add("compras", "pão")
        skill.storage.add("anotacoes", "x")
        r = self.call(intent("ContarIntent"))
        self.assertIn("Seu caderno tem: 2 itens na lista de compras e 1 anotação.", self.fala(r))
        self.assertIn("vazio", self.fala(self.call_vazio()))

    def call_vazio(self):
        skill.storage = TextFileStorage(os.path.join(self.tmp.name, "outro.txt"))
        return self.call(intent("ContarIntent"))


class FakeS3:
    """Imita o mínimo do cliente boto3 do S3 (get_object / put_object)."""

    class NoSuchKey(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}

    class AccessDenied(Exception):
        response = {"Error": {"Code": "AccessDenied"}}

    def __init__(self, negar=False):
        self.objetos = {}
        self.negar = negar

    def get_object(self, Bucket, Key):
        if self.negar:
            raise self.AccessDenied()
        if (Bucket, Key) not in self.objetos:
            raise self.NoSuchKey()
        import io

        return {"Body": io.BytesIO(self.objetos[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, **kw):
        assert isinstance(Body, bytes)
        self.objetos[(Bucket, Key)] = Body


class S3StorageTest(unittest.TestCase):
    def test_arquivo_inexistente_e_lista_vazia(self):
        st = S3TextStorage("b", "caderno.txt", client=FakeS3())
        self.assertEqual(st.list(), [])

    def test_add_list_remove_clear_no_s3(self):
        s3 = FakeS3()
        st = S3TextStorage("b", "caderno.txt", client=s3)
        st.add("compras", "leite")
        st.add("compras", "pão")
        st.add("anotacoes", "senha")
        # mesmo formato .txt do arquivo local
        corpo = s3.objetos[("b", "caderno.txt")].decode("utf-8").splitlines()
        self.assertEqual([l.split("\t")[1:] for l in corpo], [["compras", "leite"], ["compras", "pão"], ["anotacoes", "senha"]])
        # persiste entre instâncias (o que o /tmp não fazia)
        outra = S3TextStorage("b", "caderno.txt", client=s3)
        self.assertEqual(outra.count("compras"), 2)
        self.assertEqual(outra.remove("compras", "leite"), ["leite"])
        self.assertEqual(outra.clear("anotacoes"), 1)
        self.assertEqual([e["texto"] for e in outra.list()], ["pão"])

    def test_erro_de_permissao_nao_vira_lista_vazia(self):
        st = S3TextStorage("b", client=FakeS3(negar=True))
        with self.assertRaises(FakeS3.AccessDenied):
            st.add("compras", "leite")  # não pode sobrescrever o caderno achando que está vazio

    def test_make_storage_escolhe_pelo_ambiente(self):
        antigo = {k: os.environ.pop(k, None) for k in ("CADERNO_S3_BUCKET", "S3_PERSISTENCE_BUCKET")}
        try:
            self.assertIsInstance(make_storage(), TextFileStorage)
            os.environ["S3_PERSISTENCE_BUCKET"] = "meu-bucket"
            import types, sys as _sys

            _sys.modules["boto3"] = types.SimpleNamespace(client=lambda nome: FakeS3())
            try:
                st = make_storage()
            finally:
                del _sys.modules["boto3"]
            self.assertIsInstance(st, S3TextStorage)
            self.assertEqual((st.bucket, st.key), ("meu-bucket", "caderno.txt"))
        finally:
            for k, v in antigo.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
