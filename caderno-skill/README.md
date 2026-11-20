# Meu Caderno — skill Alexa para compras, ideias, lembretes e anotações

Salva o que você falar em um arquivo `caderno.txt` e lê de volta quando você perguntar.
Idioma: português do Brasil (`pt-BR`). Nome de invocação: **"meu caderno"**.

## O que dizer

| Quero… | Exemplos |
|---|---|
| Adicionar compras | "Alexa, peça ao meu caderno para **adicionar leite, pão e ovos na lista de compras**" · "preciso comprar café" |
| Salvar ideia | "…**salvar ideia** app de receitas" · "tive uma ideia …" |
| Salvar lembrete | "…**criar lembrete** ligar pro dentista" · "me lembre de …" |
| Salvar anotação | "…**anotar que** a senha do wifi mudou" · "salvar anotação …" |
| Ouvir | "Alexa, pergunte ao meu caderno **o que tem na lista de compras**" · "quais são minhas ideias" · "ler meus lembretes" · "ler tudo" |

Na lista de compras, "leite, pão e ovos" vira 3 itens separados.
Ao ouvir, a Alexa lê no máximo os 15 itens mais recentes de cada categoria.

> "Lembretes" aqui são só texto salvo — **não** disparam alarme/notificação.

## Formato do `caderno.txt`

Uma entrada por linha, separada por TAB: `data-hora<TAB>categoria<TAB>texto`

```
2026-11-20T10:30:00	compras	leite
2026-11-20T10:31:12	ideias	app de receitas
```

Categorias: `compras`, `ideias`, `lembretes`, `anotacoes`. Pode editar o arquivo à mão.

## Estrutura

```
lambda/lambda_function.py   handlers da skill
lambda/storage.py           TextFileStorage (troque por S3/DynamoDB depois)
skill-package/              manifest + modelo de interação pt-BR (formato ASK CLI)
tests/test_skill.py         testes ponta a ponta (sem precisar da Alexa)
```

## Testar localmente

```bash
pip install -r lambda/requirements.txt
python -m unittest discover -s tests -v
```

## Publicar

1. Crie a skill em <https://developer.amazon.com/alexa/console/ask> (modelo *Custom*, idioma *Português (BR)*),
   ou use o ASK CLI apontando para `skill-package/`.
2. Em *Build → JSON Editor*, cole `skill-package/interactionModels/custom/pt-BR.json` e faça *Build*.
3. Em *Code* (Alexa-hosted Python) ou numa função AWS Lambda (Python 3.x), suba o conteúdo de `lambda/`
   com handler `lambda_function.lambda_handler`, e ligue o ARN em `skill.json` / *Endpoint*.
4. Teste na aba *Test* (modo *Development*) — funciona nos seus Echos logados na mesma conta.

## ⚠️ Limitação do .txt na nuvem

Rodando em Lambda / Alexa-hosted, o único lugar gravável é `/tmp`, que **é apagado** quando o container
é reciclado (minutos/horas sem uso). O `.txt` serve para validar o fluxo e para rodar em um servidor
próprio (variável `CADERNO_FILE=/caminho/caderno.txt`). Para guardar de verdade, o próximo passo é
trocar `TextFileStorage` por S3 (mantém o mesmo `.txt`) ou DynamoDB — só `add()` e `list()` mudam.
