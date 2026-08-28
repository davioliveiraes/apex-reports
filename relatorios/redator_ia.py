# -*- coding: utf-8 -*-
"""
Análise do Período escrita por IA, a partir do prompt do operador.

O motor de regras (`analysis/`) continua sendo o texto padrão da tela: é
determinístico, offline e nunca falha. Este módulo é o caminho alternativo,
acionado por botão na revisão — a IA escreve melhor, mas depende de rede, de
crédito e de uma resposta que só se confere depois que chegou.

Três garantias, nesta ordem:

1. **Nada sai daqui sem passar por `para_pdf`.** A resposta do modelo é texto
   de terceiro entrando num template que renderiza com `|safe`: escapamos
   tudo e só então devolvemos os destaques que o formato prevê.
2. **O modelo não recebe o que ele poderia inventar.** O payload leva
   `dados_ausentes` — a lista explícita do que o relatório NÃO tem. É o que
   impede "o custo caiu em relação ao mês passado" quando não existe mês
   passado no arquivo.
3. **Falhar aqui não impede o relatório de sair.** Erro de rede, de chave ou
   de crédito vira aviso na tela; o texto do motor continua no lugar.
"""

import json
import re
import unicodedata

from django.conf import settings
from django.utils.html import escape

from . import fechamento_verba as _verba
from .analysis import templates as _templates

# Tempo que o operador espera olhando a tela. Acima disso é melhor devolver o
# erro e deixá-lo clicar de novo do que segurar o gunicorn.
TIMEOUT = 90

# Teto de tokens da resposta. A análise pedida tem 300 palavras — cabem em 700
# tokens —, mas este teto NÃO é só do texto: nos modelos de raciocínio ele
# cobre também os tokens gastos antes da primeira letra, e estourá-lo devolve
# resposta VAZIA, não resposta cortada. Medido num consolidado de 13 unidades:
# o `gpt-5` queimou 2880 tokens de raciocínio para escrever 378 de texto — 81%
# de um teto de 4000, margem que um relatório maior consome sozinho. A folga
# aqui não é gasto: token não usado não é cobrado.
MAX_TOKENS = 12000

# Quanto o modelo pensa antes de escrever. Sem este parâmetro a OpenAI aplica
# `medium`, e o relatório fica refém do que ela decidir mudar no padrão. Medido
# no mesmo consolidado de 13 unidades, com o `gpt-5.6-sol`: `none` 0 tokens de
# raciocínio, `low` 145, `medium` 334, `high` 375, `xhigh` 1495. `high` custa
# quase o mesmo que o padrão e lê melhor a diferença entre as unidades — que é
# justamente o trabalho aqui. `max` existe no modelo mas o endpoint
# `chat.completions` o recusa com 400; só sai pelo `/v1/responses`.
ESFORCO = "high"


class ErroDeIA(RuntimeError):
    """Falha que o operador precisa ler na tela, já em português.

    `motivo` é o que a tela usa para decidir o tom do aviso e se ainda vale
    oferecer o botão — ver `DEFINITIVOS`.
    """

    def __init__(self, mensagem, motivo="desconhecido"):
        super().__init__(mensagem)
        self.motivo = motivo


# Motivos em que clicar de novo dá exatamente o mesmo erro: não é a rede nem o
# momento, é a conta (`credito`, `chave`, `modelo`) ou a configuração deste
# arquivo (`teto`). A tela pinta o aviso de vermelho e esconde o botão, em vez
# de convidar o operador a repetir uma chamada que já se sabe perdida.
DEFINITIVOS = ("credito", "chave", "modelo", "teto")


# ----------------------------------------------------------------------
# O prompt
# ----------------------------------------------------------------------
# Texto do operador, na íntegra e sem edição nossa: é ele que define o que o
# cliente lê. Mexer aqui é mexer no produto — não "melhore" a redação deste
# bloco sem que a mudança tenha sido pedida.
PROMPT_OPERADOR = """Atue como gestor de tráfego pago sênior, especialista em análise de campanhas de Meta Ads.

Vou anexar um relatório com todas as métricas de desempenho da campanha.

Sua função é entregar SOMENTE uma leitura profissional, classificação e análise do período, escrita diretamente para o cliente.

Não faça tabela e não repita todas as métricas do relatório.

## OBJETIVO

Transformar os dados em uma explicação clara para o cliente entender:

- Como foi o desempenho geral da campanha.
- Quanto foi investido e quantos resultados foram gerados.
- Como ficou o custo por resultado.
- Quais campanhas, regiões, públicos ou anúncios mais se destacaram, quando houver essa divisão no relatório.
- Quais foram os principais pontos de atenção.
- Como a operação encerra o período analisado.

## REGRAS

- Analise exclusivamente os dados presentes no relatório.
- Não invente informações, metas, causas ou resultados.
- Informe sempre o período exato analisado.
- Não faça tabela.
- Não faça lista de métricas.
- Não tente comentar todos os números disponíveis.
- Escolha somente os dados que realmente ajudam a explicar o desempenho.
- Priorize investimento, quantidade de resultados e custo por resultado.
- Utilize alcance, CTR, CPC, frequência, impressões ou outras métricas apenas quando forem importantes para explicar o cenário.
- Quando houver divisão por cidade, região, campanha, conjunto ou anúncio, destaque os melhores e piores desempenhos somente quando forem relevantes.
- Se houver período anterior, mencione a comparação mais importante.
- Não invente causas para aumento ou redução de desempenho.
- Não cite pausa, duplicação, aprendizado ou status de campanha sem essa informação estar no relatório.
- Não prometa resultados futuros.
- Escreva diretamente para o cliente.
- Use linguagem simples, profissional e transparente.
- Evite excesso de termos técnicos.
- Não use palavras como "performance", "CPM" ou outras expressões técnicas sem necessidade.
- Evite repetir o mesmo número em mais de um parágrafo.

## CLASSIFICAÇÃO

Escolha somente UMA:

*ÓTIMO*
Os dados apresentam boa eficiência na geração de resultados, custo saudável e/ou evolução relevante em relação ao período anterior.

*BOM*
A campanha apresenta desempenho saudável e consistente, mas ainda existem pontos que podem ganhar eficiência.

*ATENÇÃO*
Os dados mostram perda de eficiência, custo elevado, redução de resultados ou algum ponto importante que merece acompanhamento.

A classificação deve considerar o conjunto dos dados, nunca apenas uma métrica isolada.

## TAMANHO DA RESPOSTA

A resposta deve ter:

- Período analisado.
- Classificação.
- Exatamente 3 parágrafos de análise.

Cada parágrafo deve ter aproximadamente 3 a 4 linhas em uma mensagem de WhatsApp.

A resposta completa deve caber no limite informado em TAMANHO MÁXIMO, mais abaixo. Esse limite manda sobre qualquer estimativa de palavras.

## FORMATO DA RESPOSTA

*Período analisado: [data inicial] a [data final]*

*Leitura do período: [ÓTIMO / BOM / ATENÇÃO]*

No primeiro parágrafo:

Apresente o cenário geral do período.

Informe de forma natural os principais números, principalmente investimento, quantidade de resultados e custo médio por resultado.

Explique de maneira simples o que esses números representam para a campanha.

Exemplo de construção:

"No período, investimos R$ X nas campanhas e geramos X conversas, resultando em um custo médio de R$ X por contato. A operação manteve um volume [saudável / estável / abaixo do esperado] de oportunidades, com um custo [eficiente / controlado / que merece atenção] para a captação."

No segundo parágrafo:

Faça a principal comparação interna encontrada no relatório.

Quando houver dados por cidade, região, campanha, conjunto ou anúncio, destaque:

- melhor resultado;
- pior resultado ou principal ponto de atenção.

Use números para sustentar a leitura.

Exemplo:

"O principal destaque positivo foi [região/campanha], que apresentou custo de R$ X por conversa. Em contrapartida, [região/campanha] ficou em R$ X, tornando-se o principal ponto de atenção em eficiência neste período."

No terceiro parágrafo:

Feche a análise olhando o conjunto dos dados.

Explique em aproximadamente 3 linhas:

- o que os números indicam sobre a operação atual;
- se existe concentração de bons resultados ou diferença relevante entre campanhas/regiões;
- qual ponto deve receber maior acompanhamento no próximo ciclo.

O terceiro parágrafo deve funcionar como uma conclusão profissional, sem virar plano de ação detalhado.

Exemplo de linha de raciocínio:

"No geral, os números mostram uma operação equilibrada, mas com diferenças relevantes entre algumas regiões. A maior oportunidade está em entender o que está fazendo as melhores praças entregarem contatos mais baratos e acompanhar de perto aquelas que estão elevando o custo médio da operação."

IMPORTANTE:

O cliente não precisa receber uma aula de tráfego pago.

Ele precisa terminar a leitura entendendo:

"Como foi a campanha, onde tivemos os melhores resultados e onde precisamos prestar mais atenção."

## RELATÓRIO

Analise o relatório anexado."""

# O que o prompt do operador não tem como saber: por onde o relatório entra e
# o que o texto não pode conter porque o destino não aceita.
REGRAS_DE_ENTRADA = """

## COMO O RELATÓRIO CHEGA

O relatório não é um arquivo anexado: vem como JSON na próxima mensagem, já
somado pela aplicação. É esse JSON o "relatório anexado" a que o prompt acima
se refere, e ele é a única fonte de dados que existe.

- `totais` já está agregado no período inteiro — não some nada de novo.
- `campanhas` (ou `unidades`, no consolidado) é o único recorte disponível.
- `dados_ausentes` lista o que o relatório NÃO tem. Nada dessa lista pode ser
  mencionado, comparado, estimado ou suposto — nem para dizer que faltou.
  Havendo "período anterior" nessa lista, não existe período anterior: não
  escreva que algo subiu, caiu, cresceu, melhorou, piorou ou se manteve.
- O nome da campanha segue o padrão [OBJETIVO][MARCA][ESTRUTURA][PRAÇA][DATA].
  Quando houver praça, chame-a pelo nome da cidade por extenso e em caixa
  normal (JUNDIAI vira Jundiaí). Nunca escreva o nome cru da campanha, nem os
  colchetes, nem a data contida nele.
- Números em reais chegam como número puro; escreva no padrão brasileiro
  (R$ 2.012,07). Percentuais idem (0,59%).

## FORMATO DA SAÍDA

Texto puro, em português do Brasil. O único destaque permitido é o *asterisco
simples*, e só nas duas linhas de cabeçalho. Nada de markdown, títulos,
listas, emoji ou HTML. Sem preâmbulo e sem despedida: a primeira linha da
resposta é a linha do período analisado."""


# Quanto do limite da página NÃO é análise. O `para_pdf` joga fora a linha do
# período mas conta a da classificação, já com as tags `<b></b>` que ele
# acrescenta, mais os `\n\n` entre os quatro blocos: 40 caracteres no pior
# caso ("ATENÇÃO"). Os 20 restantes são a margem entre "encostou no limite" e
# "virou segunda página" — o modelo acerta o comprimento por aproximação, não
# contando letras.
RESERVA_DO_CABECALHO = 60

# Caracteres por palavra em português, espaço incluído, medido nas respostas
# reais deste prompt (~6,3). Palavras são o que o modelo consegue controlar;
# caracteres são o que a página cobra. A conversão mora aqui para o prompt
# poder pedir as duas coisas sem que uma desminta a outra.
CHARS_POR_PALAVRA = 6.5

# Onde começa a faixa aceitável, como fração do teto. Só o teto, medido, fez o
# modelo tratá-lo como alvo a evitar: no consolidado ele escrevia 750 dos 1065
# caracteres disponíveis, jogando fora 30% da análise que cabia na página. O
# piso existe para o espaço da folha ser usado, não só respeitado.
PISO = 0.8


def limite_do_texto(dados):
    """Quantos caracteres de análise cabem na página deste relatório.

    Consolidado sobra menos: a tabela de unidades come a folha. O número é o
    mesmo que o `para_pdf` usa para avisar — se as duas contas discordassem, o
    modelo escreveria para um limite e o operador seria avisado por outro.
    """
    return (_templates.LIMITE_PDF_GRUPO if dados.get("modo") == "grupo"
            else _templates.LIMITE_PDF)


def _regra_de_tamanho(limite):
    """O teto de tamanho, que o prompt do operador não tem como saber.

    Ele fala em 3 parágrafos de 3 a 4 linhas de WhatsApp — medida de tela de
    celular, não de folha A4 com tabela em cima. Quem conhece o espaço que
    sobra é a aplicação, e é ela que fecha o número aqui.
    """
    cabe = limite - RESERVA_DO_CABECALHO
    teto = int(cabe / CHARS_POR_PALAVRA)
    return f"""

## TAMANHO MÁXIMO

Os 3 parágrafos de análise, somados, devem ter entre {int(teto * PISO)} e
{teto} palavras — no máximo {cabe} caracteres.

O teto não é meta, é o que cabe na folha: passar dele empurra a análise para
uma segunda página do PDF. Mas ficar bem abaixo também é erro — o espaço é do
cliente, e análise curta demais entrega menos leitura do que o relatório
comporta. Escreva perto do limite sem ultrapassá-lo, distribuindo o espaço
entre os 3 parágrafos."""


# ----------------------------------------------------------------------
# Payload
# ----------------------------------------------------------------------
# Rótulos com unidade no próprio nome: o modelo não vê a documentação do
# parser, e "cpc: 2.56" é convite para ele inventar o que a sigla significa.
_ROTULOS = {
    "investimento": "investimento_reais",
    "resultados": "resultados",
    "custo_resultado": "custo_por_resultado_reais",
    "impressoes": "impressoes",
    "alcance": "pessoas_alcancadas",
    "frequencia": "vezes_que_cada_pessoa_viu_em_media",
    "cpm": "custo_por_mil_impressoes_reais",
    "cliques": "cliques_no_link",
    "ctr": "porcentagem_de_cliques_sobre_impressoes",
    "cpc": "custo_por_clique_reais",
    "taxa_conversao": "porcentagem_de_resultados_sobre_cliques",
}

# Recortes que o Ads Manager exporta e estes relatórios não trazem. É a lista
# que segura a alucinação — ver a docstring do módulo. Cresce quando o export
# empobrece, nunca quando ele melhora.
_SEMPRE_AUSENTE = [
    "período anterior para comparação",
    "recorte por dia (o relatório é o total do período)",
    "recorte por idade, gênero, posicionamento, dispositivo ou região",
    "nível de conjunto de anúncios e de anúncio",
    "valor de conversão, receita, ticket médio e ROAS",
    "meta de custo por resultado combinada com o cliente",
]


# Coluna do export que sustenta cada métrica. As que faltam aqui são
# derivadas de outras (custo por resultado, CPM, frequência) e se anulam
# sozinhas quando o divisor não existe.
_FONTE = {
    "investimento": "investimento", "resultados": "resultados",
    "impressoes": "impressoes", "alcance": "alcance",
    "cliques": "cliques", "ctr": "cliques", "cpc": "cliques",
    "taxa_conversao": "cliques",
}


# Contagens, não medidas: vão como inteiro para o modelo não escrever
# "229,0 conversas" nem "3900,0 impressões".
_INTEIROS = frozenset(("resultados", "impressoes", "alcance", "cliques"))


def _num(valor, casas=2):
    if not isinstance(valor, (int, float)):
        return None
    return int(round(valor)) if casas == 0 else round(valor, casas)


def _totais(num, colunas=()):
    """Os números do período, só os que o export realmente trouxe.

    A soma de uma coluna que não existe dá zero, e zero aqui seria mentira
    grave: "784 cliques" e "0 cliques" são leituras diferentes do período,
    "não medimos cliques" não é nenhuma das duas. Por isso a decisão é pela
    coluna reconhecida (`_colunas`), como no resto da aplicação, e não pelo
    valor — que é justamente a distinção que o parser guarda ali.
    """
    saida = {}
    for chave, rotulo in _ROTULOS.items():
        fonte = _FONTE.get(chave)
        if fonte and colunas and fonte not in colunas:
            continue
        valor = _num(num.get(chave), 0 if chave in _INTEIROS else 2)
        if valor is not None:
            saida[rotulo] = valor
    return saida


def _campanhas(dados):
    """Uma linha por campanha, com o custo por resultado já calculado.

    Calculado aqui, e não deixado para o modelo: divisão feita por LLM é
    exatamente o tipo de número que sai errado sem ninguém perceber.
    """
    saida = []
    for nome, c in (dados.get("_campanhas") or {}).items():
        res, inv = c.get("res") or 0.0, c.get("inv") or 0.0
        saida.append({
            "nome_da_campanha": nome,
            "resultados": _num(res, 0),
            "investimento_reais": _num(inv),
            "custo_por_resultado_reais": _num(inv / res) if res else None,
        })
    return sorted(saida, key=lambda c: c["resultados"] or 0, reverse=True)


def _unidades(dados):
    """Mesma ideia do consolidado: uma linha por unidade do grupo."""
    colunas = dados.get("_colunas") or ()
    saida = []
    for u in dados.get("unidades") or []:
        saida.append({"nome_da_unidade": u.get("nome"),
                      **_totais(u.get("num") or {}, colunas)})
    return sorted(saida, key=lambda u: u.get("resultados") or 0, reverse=True)


def montar_payload(dados):
    """O relatório como o modelo o recebe: JSON-serializável e sem sobra.

    Só entra o que sustenta uma frase. `avaliacao`, sinais e próximo passo do
    motor de regras ficam de fora de propósito: o prompt pede que o modelo
    leia os dados, não que ele concorde com outra leitura.
    """
    num = dados.get("_num") or {}
    colunas = dados.get("_colunas") or ()
    grupo = dados.get("modo") == "grupo"

    ausentes = list(_SEMPRE_AUSENTE)
    if colunas and "cliques" not in colunas:
        ausentes.insert(0, "cliques, CTR e custo por clique")

    payload = {
        "cliente": dados.get("cliente") or "",
        "periodo_analisado": dados.get("periodo") or "",
        "dias_do_periodo": dados.get("_dias"),
        "tipo_de_resultado": dados.get("indicador") or "",
        "totais": _totais(num, colunas),
        "dados_ausentes": ausentes,
    }
    if grupo:
        payload["unidades"] = _unidades(dados)
        payload["observacao"] = (
            "Relatório consolidado: cada unidade é uma conta do mesmo cliente, "
            "e os totais são a soma de todas."
        )
    else:
        payload["campanhas"] = _campanhas(dados)
    return payload


# ----------------------------------------------------------------------
# Chamada
# ----------------------------------------------------------------------
def disponivel():
    """Há chave configurada? Sem ela o botão nem aparece na tela."""
    return bool(getattr(settings, "OPENAI_API_KEY", ""))


def _campo_do_erro(e, nome):
    """Um campo do erro da OpenAI: `code` (`insufficient_quota`,
    `model_not_found`, `invalid_api_key`) ou `param` (o parâmetro recusado).

    A SDK expõe os dois como atributo, mas nem sempre os preenche (erro de
    conexão não tem corpo nenhum); o corpo cru é a fonte que não varia.
    """
    valor = getattr(e, nome, None)
    if valor:
        return valor
    corpo = getattr(e, "body", None)
    if isinstance(corpo, dict) and isinstance(corpo.get("error"), dict):
        return corpo["error"].get(nome) or ""
    return ""


def _classificar(e):
    """`(motivo, mensagem em português)` para a exceção que a SDK levantou.

    O caso que interessa é o crédito, e ele não se distingue pelo status:
    saldo zerado e excesso de chamadas chegam os dois como HTTP 429. O que
    separa um do outro é o `code` — `insufficient_quota` contra
    `rate_limit_exceeded`. Um pede recarga, o outro pede quinze segundos.
    """
    codigo = _campo_do_erro(e, "code")
    status = getattr(e, "status_code", None)
    classe = type(e).__name__

    if codigo == "insufficient_quota":
        return "credito", (
            "Os créditos da IA acabaram — a OpenAI recusou a chamada por "
            "saldo. Recarregue em platform.openai.com/settings/organization/"
            "billing; enquanto isso o relatório sai normalmente com o texto "
            "do motor de regras.")
    if status == 429:
        return "limite", (
            "A OpenAI recusou por excesso de chamadas neste momento. Espere "
            "alguns segundos e clique de novo.")
    if status == 401 or codigo in ("invalid_api_key", "invalid_request_error"):
        return "chave", (
            "A OpenAI recusou a chave configurada. Confira o OPENAI_API_KEY "
            "do ambiente (em produção, /etc/apex-reports/env) — se ela foi "
            "revogada ou trocada no painel, é preciso colar a nova e "
            "reiniciar o serviço.")
    if codigo == "model_not_found" or status == 404:
        return "modelo", (
            f"O modelo {settings.OPENAI_MODEL} não existe ou não está "
            "liberado para esta chave. Corrija o OPENAI_MODEL do ambiente e "
            "reinicie o serviço.")
    # Nem todo modelo raciocina, e os que não raciocinam recusam o parâmetro
    # em vez de o ignorar. É o erro que aparece ao trocar o OPENAI_MODEL por um
    # modelo de conversa — e a mensagem crua não diz qual dos dois ceder.
    if _campo_do_erro(e, "param") == "reasoning_effort":
        return "modelo", (
            f"O modelo {settings.OPENAI_MODEL} não aceita o esforço de "
            f"raciocínio '{ESFORCO}' que este projeto pede. Ou configure em "
            "OPENAI_MODEL um modelo de raciocínio, ou ajuste o ESFORCO em "
            "relatorios/redator_ia.py.")
    # Sem `openai` importado aqui não dá para usar `isinstance`; o nome da
    # classe é o que a SDK garante em todas as versões da linha 1.x.
    if classe in ("APITimeoutError", "APIConnectionError"):
        return "rede", (
            f"A OpenAI não respondeu em {TIMEOUT} segundos. Pode ser a rede "
            "do servidor ou instabilidade do serviço; clique de novo.")
    if status is not None and status >= 500:
        return "servico", (
            "A OpenAI está com instabilidade no momento (erro do lado "
            "deles). Clique de novo em alguns instantes.")
    # Nada reconhecido: a mensagem da SDK é técnica e em inglês, mas some
    # junto com o erro se não for mostrada — e é a única pista que resta.
    return "desconhecido", (
        f"A chamada ao modelo {settings.OPENAI_MODEL} falhou: {e}")


def _diagnosticar_vazio(escolha, max_tokens=MAX_TOKENS):
    """`(motivo, mensagem)` para uma resposta HTTP 200 sem texto dentro.

    Chegar aqui já prova uma coisa que a mensagem antiga punha em dúvida: o
    modelo existe e a chave o alcança — nome errado teria virado 404 lá em
    cima, em `_classificar`. O que sobra é o `finish_reason`, e ele separa dois
    casos que pedem ações opostas do operador:

    - `length` num modelo de raciocínio quase nunca é texto cortado no meio. É
      o raciocínio tendo consumido `max_tokens` inteiro antes de escrever a
      primeira letra. Clicar de novo repete o gasto, então é definitivo.
    - o resto é a resposta estranha e rara, em que repetir costuma resolver.
    """
    razao = getattr(escolha, "finish_reason", None)
    if razao == "length":
        return "teto", (
            f"O modelo {settings.OPENAI_MODEL} gastou os {max_tokens} tokens "
            "da resposta raciocinando e não sobrou nada escrito. Isso é ajuste "
            "do sistema, não da sua conta: aumente o teto de tokens desta "
            "chamada em relatorios/redator_ia.py ou configure um OPENAI_MODEL "
            "que raciocine menos.")
    recusa = (getattr(escolha.message, "refusal", None) or "").strip()
    if recusa:
        return "vazio", (
            f"O modelo {settings.OPENAI_MODEL} se recusou a escrever esta "
            f"análise: {recusa}")
    return "vazio", (
        f"O modelo {settings.OPENAI_MODEL} respondeu sem texto "
        f"(finish_reason={razao!r}). Tente de novo — se repetir, o modelo "
        "configurado em OPENAI_MODEL pode não servir para esta tarefa.")


def _chamar(mensagens, max_tokens=MAX_TOKENS, esforco=ESFORCO):
    """A única função deste projeto que faz I/O de rede.

    Isolada para os testes trocarem por uma resposta fixa: a suíte inteira
    roda offline e nunca gasta crédito. `max_tokens`/`esforco` têm o teto e o
    esforço da Análise do Período como default — a chamada mais barata das
    leituras do funil (ver `gerar_leituras_funil`) passa os dela.
    """
    try:
        from openai import OpenAI
    except ImportError:                                  # pragma: no cover
        raise ErroDeIA("O pacote `openai` não está instalado neste ambiente — "
                       "rode `pip install -r requirements.txt`.", "instalacao")

    cliente = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=TIMEOUT,
                     max_retries=1)
    try:
        resposta = cliente.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=mensagens,
            max_completion_tokens=max_tokens,
            reasoning_effort=esforco,
        )
    except Exception as e:
        motivo, mensagem = _classificar(e)
        raise ErroDeIA(mensagem, motivo) from e

    escolha = resposta.choices[0]
    texto = (escolha.message.content or "").strip()
    if not texto:
        motivo, mensagem = _diagnosticar_vazio(escolha, max_tokens)
        raise ErroDeIA(mensagem, motivo)
    return texto


def gerar(dados):
    """Texto cru do modelo, no formato do prompt (com asteriscos).

    Levanta `ErroDeIA` — a view mostra a mensagem e mantém o texto do motor.
    """
    if not disponivel():
        raise ErroDeIA("Nenhuma chave de API configurada: defina OPENAI_API_KEY "
                       "no ambiente (em produção, /etc/apex-reports/env).",
                       "chave")
    sistema = (PROMPT_OPERADOR + REGRAS_DE_ENTRADA
               + _regra_de_tamanho(limite_do_texto(dados)))
    return _chamar([
        {"role": "system", "content": sistema},
        {"role": "user", "content": json.dumps(montar_payload(dados),
                                               ensure_ascii=False, indent=1)},
    ])


# ----------------------------------------------------------------------
# Da resposta para o PDF
# ----------------------------------------------------------------------
_DESTAQUE = re.compile(r"\*{1,2}\s*([^*\n]+?)\s*\*{1,2}")
# "Período analisado: ..." — o cabeçalho do PDF já imprime o período no canto
# superior direito, e repeti-lo na primeira linha da análise é o tipo de
# duplicação que o cliente lê como descuido.
# O asterisco do destaque abre a linha, então ele entra no que se pula.
_LINHA_PERIODO = re.compile(r"^[\s*]*per[íi]odo\s+analisado\b", re.IGNORECASE)


def _blocos(texto):
    normalizado = texto.replace("\r\n", "\n").replace("\r", "\n")
    return [b.strip() for b in re.split(r"\n[ \t]*\n", normalizado) if b.strip()]


def para_pdf(texto, limite=None):
    """Converte a resposta do modelo no que o PDF aceita.

    Devolve `(texto, avisos)`. Os avisos são para o operador ler antes de
    gerar o arquivo — nada aqui bloqueia, porque o textarea é editável e a
    decisão final é dele.
    """
    limite = limite or _templates.LIMITE_PDF
    blocos = []
    for bloco in _blocos(texto):
        if _LINHA_PERIODO.match(bloco):
            continue
        # Escapa TUDO primeiro: o que chega aqui é texto de terceiro e o
        # template do PDF renderiza com `|safe`. Aspas e apóstrofos voltam ao
        # normal logo em seguida — viram entidade dentro de atributo, e aqui
        # não há atributo nenhum, só conteúdo de <p>.
        limpo = escape(bloco).replace("&#x27;", "'").replace("&quot;", '"')
        blocos.append(_DESTAQUE.sub(r"<b>\1</b>", limpo))

    final = "\n\n".join(blocos)
    avisos = []
    if len(final) > limite:
        # Aviso, não impedimento: desde 12/08/2026 o PDF aceita mais de uma
        # página, e a seção de análise desce inteira em vez de o texto ser
        # desenhado por cima do rodapé. Encurtar continua sendo opção do
        # operador — só não é mais obrigação.
        avisos.append(
            f"O texto tem {len(final)} caracteres; acima de {limite} a Análise "
            "do Período não cabe no que sobra da página e desce inteira para "
            "uma segunda. Não é erro — só confira se você quer o relatório "
            "com duas páginas.")
    if len(blocos) != 4:
        avisos.append(
            f"O formato pede a linha de classificação e 3 parágrafos; vieram "
            f"{len(blocos)} blocos. Confira antes de gerar.")
    return final, avisos


# ----------------------------------------------------------------------
# Leituras do funil, escritas por IA
# ----------------------------------------------------------------------
# As 4 legendas curtas sob os cards do Funil de Vendas — só estas têm leitura
# no PDF (ver `_METRICAS_LEITURA` em `gerador_pdf.py`; CPC é calculado mas
# nunca aparece nesses cards). Sem IA elas vêm de um catálogo fixo em
# `parser_xlsx._LEITURAS_CARD`, indexado só pela classificação de benchmark —
# duas contas na mesma faixa recebem a MESMA frase, sem olhar a magnitude do
# número. Esta chamada troca isso por uma frase por conta, escrita a partir
# do número real, com o catálogo como piso: falhar aqui não troca nada, e o
# relatório sai igual a antes desta funcionalidade existir.
CHAVES_LEITURA_FUNIL = ("frequencia", "cpm", "ctr", "taxa_conversao")

# Bem mais barata que a Análise do Período: são 4 frases curtas a partir de
# números que já estão no payload, não uma leitura de conjunto do período
# nem uma comparação entre unidades. `low` já é esforço de sobra pra isso.
ESFORCO_LEITURAS_FUNIL = "low"

# Ainda não medido como o teto da análise principal está (aquele comentário
# vem de tokens de raciocínio reais, medidos num consolidado de 13 unidades).
# A folga aqui é generosa de propósito: sobrar tokens não custa nada, faltar
# devolve resposta vazia.
MAX_TOKENS_LEITURAS_FUNIL = 1500

# Teto de sanidade por legenda — não é medido por bisseção como `LIMITE_PDF`
# porque o card do funil não tem altura fixa (o CSS deixa ele esticar).
# Existe só pra barrar o modelo escrevendo um parágrafo em vez de uma
# legenda; acima disso a legenda cai no catálogo estático.
LIMITE_LEITURA_FUNIL = 220

PROMPT_LEITURAS_FUNIL = """Atue como gestor de tráfego pago sênior, especialista em Meta Ads.

Você vai escrever legendas curtas — uma frase cada — para os cards do funil de vendas de um relatório de Meta Ads. Cada legenda fica embaixo do número da métrica no card, com o nome da métrica já escrito em negrito ao lado (ex.: "Frequência: <sua frase>"). NÃO repita o nome da métrica nem o número dela na frase — os dois já aparecem no card, acima e ao lado.

## MÉTRICAS

Escreva uma legenda para cada uma destas, mas SOMENTE se ela aparecer em "totais" no JSON que vai chegar a seguir:

- frequencia: quantas vezes, em média, a mesma pessoa viu os anúncios.
- cpm: custo a cada mil vezes que os anúncios foram exibidos.
- ctr: porcentagem de quem viu e clicou.
- taxa_conversao: porcentagem de quem clicou e virou resultado.

Se uma dessas não estiver em "totais", não escreva a chave dela — não invente o número.

## REGRAS

- Fale a consequência para o negócio, não a métrica em si. Nunca escreva a sigla crua (CPM, CTR, CPA, CPC) nem a palavra "performance".
- Baseie a frase no número real recebido — dois relatórios com números diferentes precisam ler diferente. Não escreva a mesma frase pronta pra faixas inteiras de valor.
- Tom sempre construtivo: mesmo quando o número pede atenção, descreva a ação em andamento ("estamos ajustando..."), nunca alarme o cliente.
- Nunca prometa resultado futuro nem cite pausa, duplicação ou status de campanha.
- Não invente causa que os dados não sustentam.
- Uma frase por métrica, sem ponto de exclamação, sem emoji.

## EXEMPLOS DE TOM E TAMANHO (não copie — escreva a partir dos números deste relatório)

- frequencia: "Boa presença junto ao público — estamos ampliando as audiências para manter a entrega eficiente."
- cpm: "Custo de entrega competitivo — bom momento para ganhar volume."
- ctr: "Estamos renovando os criativos para elevar a taxa de cliques."
- taxa_conversao: "Boa eficiência do fluxo de atendimento."

## FORMATO DA RESPOSTA

Responda SOMENTE com um objeto JSON, sem markdown, sem cerca de código, sem texto antes ou depois — só as chaves entre as 4 acima que tiverem número em "totais". Exemplo de resposta completa:

{"frequencia": "...", "cpm": "...", "ctr": "...", "taxa_conversao": "..."}"""

# Versão curta do que `REGRAS_DE_ENTRADA` explica pro prompt principal — só a
# parte que importa aqui (o payload é o mesmo). Não reaproveita a constante
# inteira porque a seção "FORMATO DA SAÍDA" dela é sobre texto com asterisco,
# e aqui a saída é JSON.
_REGRAS_DE_ENTRADA_LEITURAS_FUNIL = """

## COMO O RELATÓRIO CHEGA

Vem como JSON na próxima mensagem, já somado pela aplicação — é a única fonte
de dados que existe. `totais` já está agregado no período inteiro; a chave
"dados_ausentes" lista o que o relatório NÃO tem, e nada dessa lista pode ser
mencionado, comparado ou suposto. Números em reais e percentuais chegam como
número puro — escreva no padrão brasileiro (R$ 2.012,07 · 0,59%) só se
precisar citar um número que NÃO seja o da própria métrica da legenda (o
card acima dela já mostra esse)."""


def gerar_leituras_funil(dados):
    """As legendas do funil escritas a partir dos números do relatório.

    Devolve um dict só com as chaves que o modelo escreveu e passaram pela
    validação de `_parse_leituras_funil` — chave ausente no resultado
    significa "mantenha o texto do catálogo estático pra essa métrica",
    decidido por quem aplica (`parser_xlsx.substituir_leituras`).

    Levanta `ErroDeIA` nos mesmos casos de `gerar()` (rede, crédito, chave —
    tratados por `_classificar`, chamado dentro de `_chamar`) mais o motivo
    "formato" quando a resposta não é o JSON esperado.
    """
    if not disponivel():
        raise ErroDeIA("Nenhuma chave de API configurada: defina OPENAI_API_KEY "
                       "no ambiente (em produção, /etc/apex-reports/env).",
                       "chave")
    sistema = PROMPT_LEITURAS_FUNIL + _REGRAS_DE_ENTRADA_LEITURAS_FUNIL
    bruto = _chamar([
        {"role": "system", "content": sistema},
        {"role": "user", "content": json.dumps(montar_payload(dados),
                                               ensure_ascii=False, indent=1)},
    ], max_tokens=MAX_TOKENS_LEITURAS_FUNIL, esforco=ESFORCO_LEITURAS_FUNIL)
    return _parse_leituras_funil(bruto)


# Alguns modelos cercam o JSON com ```json apesar da instrução de não usar
# markdown; tolerado aqui em vez de reforçado no prompt, porque um `strip`
# errado é mais barato que confiar que a instrução sempre é obedecida.
_CERCA_JSON = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _parse_leituras_funil(texto):
    """`{"frequencia": "...", ...}` a partir da resposta crua do modelo.

    Chave fora de `CHAVES_LEITURA_FUNIL`, valor vazio ou maior que
    `LIMITE_LEITURA_FUNIL` é descartada em silêncio — quem chama trata a
    ausência de uma chave como "sem leitura nova pra essa métrica", não como
    erro. JSON que não dá pra interpretar levanta `ErroDeIA`: aí nenhuma
    leitura muda, não só as que vieram malformadas.
    """
    limpo = _CERCA_JSON.sub("", texto.strip())
    try:
        bruto = json.loads(limpo)
    except (json.JSONDecodeError, ValueError) as e:
        raise ErroDeIA(
            f"O modelo {settings.OPENAI_MODEL} não respondeu em JSON ao pedido "
            "das legendas do funil. A Análise do Período já está salva; só as "
            "legendas do funil continuam com o texto padrão.", "formato") from e
    if not isinstance(bruto, dict):
        raise ErroDeIA(
            f"O modelo {settings.OPENAI_MODEL} respondeu algo que não é um "
            "objeto JSON para as legendas do funil.", "formato")

    saida = {}
    for chave in CHAVES_LEITURA_FUNIL:
        valor = bruto.get(chave)
        if isinstance(valor, str) and 0 < len(valor.strip()) <= LIMITE_LEITURA_FUNIL:
            saida[chave] = valor.strip()
    return saida


# ----------------------------------------------------------------------
# Fechamento de verba — reescrita da mensagem
# ----------------------------------------------------------------------
# Terceira chamada do projeto, e a mais barata das três: o texto tem dez
# linhas e todos os números já vêm calculados. O modelo aqui só redige.
#
# A garantia central desta chamada é o que ela NÃO envia. O payload leva os
# valores prontos do `fechamento_verba.calcular` e nada mais — nenhuma linha
# de planilha, nenhuma métrica de desempenho. A proibição da seção 6 ("não
# citar CPM, CTR, CPA, resultados") deixa de depender de o modelo obedecer:
# ele não recebe esses números, então não tem o que citar.
ESFORCO_VERBA = "low"

# Dez linhas de texto. O teto alto é pelo mesmo motivo de MAX_TOKENS: nos
# modelos de raciocínio ele cobre também os tokens gastos antes da primeira
# letra, e estourá-lo devolve resposta vazia, não cortada.
MAX_TOKENS_VERBA = 3000

LINHAS_MAXIMAS_VERBA = 10

# Métricas de desempenho que a seção 6 proíbe na mensagem de verba. Aparecendo
# qualquer uma, a resposta é recusada e a mensagem do motor fica no lugar —
# não vale "limpar" o texto do modelo: se ele citou o que não recebeu, a frase
# inteira é invenção.
TERMOS_DE_PERFORMANCE = (
    "cpm", "ctr", "cpa", "cpc", "roas", "thruplay",
    "impress", "alcance", "frequenc", "clique", "conversao", "conversa",
    "lead", "resultado", "engajamento", "custo por",
)

# Texto do operador (seções 6 e 7 do prompt de Fechamento de Verba), na íntegra
# e sem edição nossa — mesma regra do PROMPT_OPERADOR: mexer aqui é mexer no
# produto.
PROMPT_VERBA = """Você é um analista de tráfego pago conferindo orçamento, não performance.

Sua função é reescrever a mensagem de fechamento de verba abaixo, mantendo exatamente os mesmos números.

## 6. REGRAS DA MENSAGEM

**Obrigatório:** PT-BR direto · negrito com asterisco simples · máximo 10 linhas · terminar com pergunta fechada · máximo 1 emoji.

**Proibido:** ação operacional (pausar, duplicar, ativar) · nomenclatura interna ou nome de campanha · métrica de performance (CPM, CTR, CPA, resultados) · prometer resultado · justificar desvio com causa não confirmada · "aparentemente", "acredito que", "talvez".

## 7. SAÍDA

Devolva SOMENTE a mensagem, no formato:

```
Bom dia! Passando o fechamento de verba pra confirmar 👇

*Contratado:* R$ [contratado_mensal]/mês
*Configurado:* R$ [configurado_diario]/dia
*Gasto até [DD/MM]:* R$ [gasto]
*Projeção de fechamento:* R$ [projecao_fechamento]

[frase de status]
[pergunta fechada]
```
"""

_REGRAS_DE_ENTRADA_VERBA = """
## O QUE VOCÊ RECEBE

Um JSON com os valores já calculados e já formatados, mais a frase de status e
a pergunta que encerram a mensagem.

## REGRAS DA ENTRADA

- Copie os valores como vieram. Não recalcule, não arredonde, não converta.
- Mantenha o sentido da frase de status: ela sai de uma tabela de decisão e
  trocá-la muda o que o cliente entende do mês.
- Termine com uma pergunta fechada — a que veio serve; outra equivalente também.
- Não escreva nada além da mensagem: sem título, sem comentário, sem cerca de
  código.
"""


def _payload_verba(calc, cliente=""):
    """O fechamento como o modelo o recebe: números prontos e nada mais."""
    return {
        "cliente": cliente,
        "mes_analisado": calc["mes"],
        "contratado_mensal": _verba.reais(calc["contratado_mensal"]),
        "configurado_diario": _verba.reais(calc["configurado_diario"]),
        "gasto_ate": f"{calc['ontem']:%d/%m}",
        "gasto": _verba.reais(calc["gasto"]),
        "projecao_fechamento": _verba.reais(calc["projecao_fechamento"]),
        "frase_de_status": _verba.frase_status(calc),
        "pergunta_fechada": _verba.PERGUNTAS[calc["status"]],
    }


def gerar_mensagem_verba(calc, cliente=""):
    """Outra redação da mesma mensagem de fechamento.

    Levanta `ErroDeIA` — a view mostra o aviso e mantém o texto do motor, que
    nunca deixa de existir.
    """
    if not disponivel():
        raise ErroDeIA("Nenhuma chave de API configurada: defina OPENAI_API_KEY "
                       "no ambiente (em produção, /etc/apex-reports/env).",
                       "chave")
    bruto = _chamar(
        [{"role": "system", "content": PROMPT_VERBA + _REGRAS_DE_ENTRADA_VERBA},
         {"role": "user", "content": json.dumps(_payload_verba(calc, cliente),
                                                ensure_ascii=False, indent=1)}],
        max_tokens=MAX_TOKENS_VERBA, esforco=ESFORCO_VERBA)
    return _validar_mensagem_verba(bruto)


def _validar_mensagem_verba(texto):
    """A resposta, ou `ErroDeIA` explicando por que ela foi recusada.

    Recusar aqui não custa relatório nenhum: a mensagem determinística está na
    tela desde antes do clique, e continua depois dele.
    """
    limpo = _CERCA_JSON.sub("", (texto or "").strip()).strip()
    if not limpo:
        raise ErroDeIA("O modelo devolveu uma mensagem vazia.", "formato")

    linhas = [l for l in limpo.splitlines() if l.strip()]
    if len(linhas) > LINHAS_MAXIMAS_VERBA:
        raise ErroDeIA(
            f"A mensagem veio com {len(linhas)} linhas e o limite é "
            f"{LINHAS_MAXIMAS_VERBA}. Mantida a mensagem do cálculo.", "formato")

    normal = _sem_acento(limpo)
    citados = sorted({t for t in TERMOS_DE_PERFORMANCE if t in normal})
    if citados:
        raise ErroDeIA(
            "A mensagem citou métrica de performance (" + ", ".join(citados)
            + "), que o fechamento de verba não usa. Mantida a mensagem do "
              "cálculo.", "formato")

    if not limpo.rstrip().endswith("?"):
        raise ErroDeIA("A mensagem não terminou com pergunta fechada. "
                       "Mantida a mensagem do cálculo.", "formato")
    return limpo


def _sem_acento(texto):
    baixo = texto.lower()
    return "".join(c for c in unicodedata.normalize("NFD", baixo)
                   if unicodedata.category(c) != "Mn")
