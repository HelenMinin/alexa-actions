# -*- coding: utf-8 -*-
"""Skill Alexa "Meu Caderno": salva compras, ideias, lembretes e anotações
em um arquivo .txt e lê de volta quando você pedir."""

import re
from xml.sax.saxutils import escape

from ask_sdk_core.dispatch_components import (
    AbstractExceptionHandler,
    AbstractRequestHandler,
)
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import get_slot_value, is_intent_name, is_request_type

from storage import TextFileStorage

storage = TextFileStorage()

# nome falado de cada categoria (singular, plural/lista)
NOMES = {
    "compras": {"lista": "lista de compras", "item": "item", "itens": "itens"},
    "ideias": {"lista": "ideias", "item": "ideia", "itens": "ideias"},
    "lembretes": {"lista": "lembretes", "item": "lembrete", "itens": "lembretes"},
    "anotacoes": {"lista": "anotações", "item": "anotação", "itens": "anotações"},
}

# Intent de adicionar -> categoria
ADD_INTENTS = {
    "AddCompraIntent": "compras",
    "AddIdeiaIntent": "ideias",
    "AddLembreteIntent": "lembretes",
    "AddAnotacaoIntent": "anotacoes",
}

MAX_LIDOS = 15  # evita a Alexa falar por minutos


def say(text):
    """Escapa caracteres especiais de SSML (&, <, >) em texto vindo do usuário."""
    return escape(text)


def juntar(itens):
    itens = [say(i) for i in itens]
    if len(itens) <= 1:
        return "".join(itens)
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def resolver_categoria(handler_input):
    """Lê o slot 'categoria' e devolve a chave canônica (ou None)."""
    slot = (handler_input.request_envelope.request.intent.slots or {}).get("categoria")
    if not slot or not slot.resolutions:
        return None
    for auth in slot.resolutions.resolutions_per_authority or []:
        if auth.status.code.value == "ER_SUCCESS_MATCH" and auth.values:
            return auth.values[0].value.id
    return None


def separar_compras(texto):
    """'leite, pão e ovos' -> ['leite', 'pão', 'ovos']"""
    partes = re.split(r"\s*,\s*|\s+e\s+", texto.strip())
    return [p for p in partes if p]


class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        fala = (
            "Meu Caderno. Você pode dizer, por exemplo: adicionar leite na lista de "
            "compras, salvar ideia, criar lembrete, ou o que tem na minha lista de compras?"
        )
        return handler_input.response_builder.speak(fala).ask(
            "O que você quer anotar ou consultar?"
        ).response


class AddHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return any(is_intent_name(n)(handler_input) for n in ADD_INTENTS)

    def handle(self, handler_input):
        intent_name = handler_input.request_envelope.request.intent.name
        categoria = ADD_INTENTS[intent_name]
        texto = get_slot_value(handler_input, "texto")
        rb = handler_input.response_builder

        if not texto or not texto.strip():
            return rb.speak("Não entendi o que anotar. Pode repetir?").ask(
                "Pode repetir o que você quer anotar?"
            ).response

        textos = separar_compras(texto) if categoria == "compras" else [texto]
        for t in textos:
            storage.add(categoria, t)

        if categoria == "compras":
            fala = "Adicionei %s à lista de compras." % juntar(textos)
        elif categoria == "ideias":
            fala = "Ideia salva."
        elif categoria == "lembretes":
            fala = "Lembrete salvo."
        else:
            fala = "Anotação salva."

        # Se a skill foi aberta direto com o comando, encerra; se já estava
        # conversando, deixa aberta para a próxima anotação.
        if handler_input.request_envelope.session.new:
            return rb.speak(fala).set_should_end_session(True).response
        return rb.speak(fala + " Mais alguma coisa?").ask("Mais alguma coisa?").response


class LerHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("LerIntent")(handler_input)

    def handle(self, handler_input):
        categoria = resolver_categoria(handler_input)
        rb = handler_input.response_builder
        if categoria:
            return rb.speak(self._ler_categoria(categoria)).response

        # Sem categoria: lê um resumo de tudo.
        partes = []
        for cat in NOMES:
            if storage.list(cat):
                partes.append(self._ler_categoria(cat))
        fala = " ".join(partes) if partes else "Seu caderno está vazio."
        return rb.speak(fala).response

    @staticmethod
    def _ler_categoria(categoria):
        nome = NOMES[categoria]
        itens = [e["texto"] for e in storage.list(categoria)]
        if not itens:
            if categoria == "compras":
                return "Sua lista de compras está vazia."
            return "Você não tem nada salvo em %s." % nome["lista"]
        total = len(itens)
        recentes = itens[-MAX_LIDOS:]
        if categoria == "compras":
            cabecalho = "Você tem %d %s na lista de compras" % (
                total,
                nome["item"] if total == 1 else nome["itens"],
            )
        else:
            cabecalho = "Você tem %d %s" % (
                total,
                nome["item"] if total == 1 else nome["itens"],
            )
        if total > MAX_LIDOS:
            cabecalho += ". Os %d mais recentes são" % MAX_LIDOS
        return "%s: %s." % (cabecalho, juntar(recentes))


class HelpHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        fala = (
            "Para anotar, diga: adicionar leite na lista de compras, salvar ideia seguida "
            "da ideia, criar lembrete, ou anotar que e o que quiser guardar. "
            "Para ouvir, diga: o que tem na lista de compras, quais são minhas ideias, "
            "ou ler tudo."
        )
        return handler_input.response_builder.speak(fala).ask("Como posso ajudar?").response


class CancelStopHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.CancelIntent")(handler_input) or is_intent_name(
            "AMAZON.StopIntent"
        )(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.speak("Até logo!").response


class FallbackHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.speak(
            "Não entendi. Você pode dizer, por exemplo: adicionar leite na lista de compras."
        ).ask("O que você quer anotar ou consultar?").response


class SessionEndedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        print("Erro: %r" % exception)
        return handler_input.response_builder.speak(
            "Desculpe, tive um problema para acessar o caderno. Tente de novo."
        ).response


sb = SkillBuilder()
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(AddHandler())
sb.add_request_handler(LerHandler())
sb.add_request_handler(HelpHandler())
sb.add_request_handler(CancelStopHandler())
sb.add_request_handler(FallbackHandler())
sb.add_request_handler(SessionEndedHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
