# -*- coding: utf-8 -*-
"""Testes ponta a ponta: envia envelopes de requisição Alexa para o handler."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))

import lambda_function as skill  # noqa: E402
from storage import TextFileStorage  # noqa: E402


def envelope(request, new=True):
    return {
        "version": "1.0",
        "session": {
            "new": new,
            "sessionId": "amzn1.echo-api.session.1",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.test"},
            "attributes": {},
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


if __name__ == "__main__":
    unittest.main()
