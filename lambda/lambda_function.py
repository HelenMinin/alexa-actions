# -*- coding: utf-8 -*-
"""Skill Alexa "Meu Caderno": salva compras, ideias, lembretes e anotações
em um arquivo .txt e lê de volta quando você pedir."""

import re
from xml.sax.saxutils import escape

from ask_sdk_core.dispatch_components import (
    AbstractExceptionHandler,
    AbstractRequestHandler,
    AbstractRequestInterceptor,
)
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import get_slot_value, is_intent_name, is_request_type

from storage import make_storage

# S3 se CADERNO_S3_BUCKET / S3_PERSISTENCE_BUCKET estiver definida; senão arquivo local.
storage = make_storage()

# nome falado de cada categoria (singular, plural/lista)
NOMES = {
    "compras": {"lista": "lista de compras", "item": "item", "itens": "itens",
                "em": "na lista de compras", "de": "da lista de compras"},
    "ideias": {"lista": "ideias", "item": "ideia", "itens": "ideias",
               "em": "nas ideias", "de": "das ideias"},
    "lembretes": {"lista": "lembretes", "item": "lembrete", "itens": "lembretes",
                  "em": "nos lembretes", "de": "dos lembretes"},
    "anotacoes": {"lista": "anotações", "item": "anotação", "itens": "anotações",
                  "em": "nas anotações", "de": "das anotações"},
}

# Intent de adicionar -> categoria
ADD_INTENTS = {
    "AddCompraIntent": "compras",
    "AddIdeiaIntent": "ideias",
    "AddLembreteIntent": "lembretes",
    "AddAnotacaoIntent": "anotacoes",
}

# Intent de remover -> categoria
REMOVE_INTENTS = {
    "RemoverCompraIntent": "compras",
    "RemoverIdeiaIntent": "ideias",
    "RemoverLembreteIntent": "lembretes",
    "RemoverAnotacaoIntent": "anotacoes",
}

MAX_LIDOS = 15  # evita a Alexa falar por minutos
PENDENTE = "pendente_limpar"  # atributo de sessão: o que aguarda confirmação ("tudo" ou categoria)


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


def slot_preenchido(handler_input, nome):
    """True se o usuário falou algo no slot (mesmo que não tenha sido reconhecido)."""
    slot = (handler_input.request_envelope.request.intent.slots or {}).get(nome)
    return bool(slot and slot.value)


def contagem(categoria, total):
    """'3 itens na lista de compras', '1 ideia', '2 lembretes'."""
    nome = NOMES[categoria]
    texto = "%d %s" % (total, nome["item"] if total == 1 else nome["itens"])
    return texto + " na lista de compras" if categoria == "compras" else texto


def vazio(categoria):
    if categoria == "compras":
        return "Sua lista de compras está vazia."
    return "Você não tem nada salvo em %s." % NOMES[categoria]["lista"]


def responder(handler_input, fala):
    """Se a skill foi aberta direto com o comando, encerra; se já estava
    conversando, deixa aberta para o próximo pedido."""
    rb = handler_input.response_builder
    if handler_input.request_envelope.session.new:
        return rb.speak(fala).set_should_end_session(True).response
    return rb.speak(fala + " Mais alguma coisa?").ask("Mais alguma coisa?").response


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

        return responder(handler_input, fala)


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
        itens = [e["texto"] for e in storage.list(categoria)]
        if not itens:
            return vazio(categoria)
        total = len(itens)
        recentes = itens[-MAX_LIDOS:]
        cabecalho = "Você tem " + contagem(categoria, total)
        if total > MAX_LIDOS:
            cabecalho += ". Os %d mais recentes são" % MAX_LIDOS
        return "%s: %s." % (cabecalho, juntar(recentes))


class RemoverHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return any(is_intent_name(n)(handler_input) for n in REMOVE_INTENTS)

    def handle(self, handler_input):
        categoria = REMOVE_INTENTS[handler_input.request_envelope.request.intent.name]
        texto = get_slot_value(handler_input, "texto")
        rb = handler_input.response_builder

        if not texto or not texto.strip():
            return rb.speak("Não entendi o que remover. Pode repetir?").ask(
                "Pode repetir o que você quer remover?"
            ).response

        removidos = storage.remove(categoria, texto)
        if removidos:
            fala = "Removi %s %s." % (juntar(removidos), NOMES[categoria]["de"])
        else:
            fala = "Não encontrei %s %s." % (say(texto.strip()), NOMES[categoria]["em"])
        return responder(handler_input, fala)


class LimparHandler(AbstractRequestHandler):
    """Pede confirmação por voz antes de apagar uma lista (ou o caderno todo)."""

    def can_handle(self, handler_input):
        return is_intent_name("LimparIntent")(handler_input)

    def handle(self, handler_input):
        rb = handler_input.response_builder
        categoria = resolver_categoria(handler_input)

        # Falou uma lista que não reconhecemos: nunca assumir "tudo".
        if not categoria and slot_preenchido(handler_input, "categoria"):
            return rb.speak(
                "Não entendi qual lista limpar. Diga, por exemplo: limpar a lista de compras."
            ).ask("Qual lista você quer limpar?").response

        if categoria:
            total = storage.count(categoria)
            if not total:
                return rb.speak(vazio(categoria)).response
            pergunta = "Quer mesmo apagar %s? Diga sim ou não." % contagem(categoria, total)
        else:
            total = storage.count()
            if not total:
                return rb.speak("Seu caderno está vazio.").response
            pergunta = "Quer mesmo apagar tudo do caderno, %d %s? Diga sim ou não." % (
                total, "entrada" if total == 1 else "entradas")

        handler_input.attributes_manager.session_attributes[PENDENTE] = categoria or "tudo"
        return rb.speak(pergunta).ask("Quer mesmo apagar? Diga sim ou não.").response


class SimHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.YesIntent")(handler_input)

    def handle(self, handler_input):
        sessao = handler_input.attributes_manager.session_attributes
        pendente = sessao.pop(PENDENTE, None)
        rb = handler_input.response_builder
        if not pendente:
            return rb.speak("Não tenho nada pendente. O que você quer anotar ou consultar?").ask(
                "O que você quer anotar ou consultar?"
            ).response
        if pendente == "tudo":
            apagados = storage.clear()
            fala = "Pronto, apaguei tudo do caderno."
        else:
            apagados = storage.clear(pendente)
            fala = "Pronto, limpei %s." % (
                "a lista de compras" if pendente == "compras" else NOMES[pendente]["lista"]
            )
        if not apagados:
            fala = "Não havia nada para apagar."
        return responder(handler_input, fala)


class NaoHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.NoIntent")(handler_input)

    def handle(self, handler_input):
        sessao = handler_input.attributes_manager.session_attributes
        tinha = sessao.pop(PENDENTE, None)
        fala = "Ok, não apaguei nada." if tinha else "Ok."
        return responder(handler_input, fala)


class ContarHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ContarIntent")(handler_input)

    def handle(self, handler_input):
        categoria = resolver_categoria(handler_input)
        rb = handler_input.response_builder
        if categoria:
            total = storage.count(categoria)
            fala = ("Você tem " + contagem(categoria, total) + ".") if total else vazio(categoria)
            return rb.speak(fala).response

        partes = []
        for cat in NOMES:
            total = storage.count(cat)
            if total:
                partes.append(contagem(cat, total))
        fala = ("Seu caderno tem: " + juntar(partes) + ".") if partes else "Seu caderno está vazio."
        return rb.speak(fala).response


class HelpHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        fala = (
            "Para anotar, diga: adicionar leite na lista de compras, salvar ideia seguida "
            "da ideia, criar lembrete, ou anotar que e o que quiser guardar. "
            "Para ouvir, diga: o que tem na lista de compras, quais são minhas ideias, "
            "ou ler tudo. Para contar, diga: quantos itens tem na lista de compras. "
            "Para tirar algo, diga: tirar leite da lista de compras. "
            "E para esvaziar, diga: limpar a lista de compras."
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


class LimparPendenciaInterceptor(AbstractRequestInterceptor):
    """Qualquer pedido que não seja sim/não cancela uma confirmação de limpar pendente,
    para um "sim" distraído, mais tarde, nunca apagar nada."""

    def process(self, handler_input):
        req = handler_input.request_envelope.request
        if req.object_type == "IntentRequest" and req.intent.name not in (
            "AMAZON.YesIntent",
            "AMAZON.NoIntent",
        ):
            handler_input.attributes_manager.session_attributes.pop(PENDENTE, None)


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
sb.add_request_handler(ContarHandler())
sb.add_request_handler(RemoverHandler())
sb.add_request_handler(LimparHandler())
sb.add_request_handler(SimHandler())
sb.add_request_handler(NaoHandler())
sb.add_request_handler(HelpHandler())
sb.add_request_handler(CancelStopHandler())
sb.add_request_handler(FallbackHandler())
sb.add_request_handler(SessionEndedHandler())
sb.add_global_request_interceptor(LimparPendenciaInterceptor())
sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
