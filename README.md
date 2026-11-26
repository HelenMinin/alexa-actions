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
| Contar | "…**quantos itens tem na lista de compras**" · "quantas ideias eu tenho" · "quantos itens tem no caderno" |
| Remover um item | "…**tirar leite da lista de compras**" · "já comprei o pão" · "apagar ideia app de receitas" · "apagar lembrete dentista" · "apagar anotação wifi" |
| Limpar | "…**limpar a lista de compras**" · "limpar as ideias" · "limpar tudo" — a Alexa pergunta *"Quer mesmo apagar…?"* e só apaga se você disser **sim** |

Na lista de compras, "leite, pão e ovos" vira 3 itens separados.
Ao ouvir, a Alexa lê no máximo os 15 itens mais recentes de cada categoria.

Ao remover, a comparação ignora maiúsculas e acentos. Se houver um item igual ao que você falou, só ele sai;
senão saem os que contêm o que você falou (*"pão"* remove *"pão francês"*) e a Alexa diz o que removeu.

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
lambda/storage.py           TextFileStorage e S3TextStorage (add, list, count, remove, clear)
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

## Guardar de verdade: S3

Por padrão o `caderno.txt` fica em arquivo local. No Lambda / Alexa-hosted o único lugar gravável é `/tmp`,
que **é apagado** quando o container é reciclado — serve só para testar o fluxo.

Para persistir, o **mesmo `.txt`** é guardado em um objeto S3. A skill escolhe sozinha pelo ambiente:

| Variável de ambiente | Efeito |
|---|---|
| `CADERNO_S3_BUCKET` (ou `S3_PERSISTENCE_BUCKET`) | liga o S3 com esse bucket |
| `CADERNO_S3_KEY` | nome do objeto (padrão `caderno.txt`) |
| `CADERNO_FILE` | caminho do arquivo local (sem S3) |

- **Alexa-hosted:** o bucket já vem em `S3_PERSISTENCE_BUCKET` — não precisa configurar nada.
- **Lambda próprio:** crie um bucket, defina `CADERNO_S3_BUCKET` e dê à função, no role, `s3:GetObject` e
  `s3:PutObject` no objeto e **`s3:ListBucket`** no bucket. Sem o `ListBucket` o S3 responde "acesso negado"
  (e não "não existe") antes do primeiro uso, e a skill falha em vez de começar do zero.

O caderno é **um arquivo só** (uso pessoal): quem usar a skill na sua conta enxerga as mesmas listas. Cada gravação
lê e regrava o arquivo inteiro, o que é bom para algumas centenas de itens e não para dezenas de milhares.
