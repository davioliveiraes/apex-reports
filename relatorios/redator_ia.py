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

from django.conf import settings
from django.utils.html import escape

from .analysis import templates as _templates

# Tempo que o operador espera olhando a tela. Acima disso é melhor devolver o
# erro e deixá-lo clicar de novo do que segurar o gunicorn.
TIMEOUT = 90

# Teto de tokens da resposta. A análise pedida tem 300 palavras; a folga existe
# porque modelos de raciocínio consomem tokens antes de escrever a primeira
# letra, e um teto curto devolve resposta vazia em vez de resposta cortada.
MAX_TOKENS = 4000


class ErroDeIA(RuntimeError):
    """Falha que o operador precisa ler na tela, já em português.

    `motivo` é o que a tela usa para decidir o tom do aviso e se ainda vale
    oferecer o botão — ver `DEFINITIVOS`.
    """

    def __init__(self, mensagem, motivo="desconhecido"):
        super().__init__(mensagem)
        self.motivo = motivo


# Motivos em que clicar de novo dá exatamente o mesmo erro: não é a rede nem o
# momento, é a conta. A tela pinta o aviso de vermelho e esconde o botão, em
# vez de convidar o operador a repetir uma chamada que já se sabe perdida.
DEFINITIVOS = ("credito", "chave", "modelo")


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

A resposta completa deve ter aproximadamente 220 a 300 palavras no máximo.

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


def _codigo_do_erro(e):
    """O `code` que a OpenAI manda junto do erro — `insufficient_quota`,
    `model_not_found`, `invalid_api_key`.

    A SDK expõe em `.code`, mas nem sempre o preenche (erros de conexão não
    têm corpo nenhum); o corpo cru é a fonte que não varia.
    """
    codigo = getattr(e, "code", None)
    if codigo:
        return codigo
    corpo = getattr(e, "body", None)
    if isinstance(corpo, dict) and isinstance(corpo.get("error"), dict):
        return corpo["error"].get("code") or ""
    return ""


def _classificar(e):
    """`(motivo, mensagem em português)` para a exceção que a SDK levantou.

    O caso que interessa é o crédito, e ele não se distingue pelo status:
    saldo zerado e excesso de chamadas chegam os dois como HTTP 429. O que
    separa um do outro é o `code` — `insufficient_quota` contra
    `rate_limit_exceeded`. Um pede recarga, o outro pede quinze segundos.
    """
    codigo = _codigo_do_erro(e)
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


def _chamar(mensagens):
    """A única função deste projeto que faz I/O de rede.

    Isolada para os testes trocarem por uma resposta fixa: a suíte inteira
    roda offline e nunca gasta crédito.
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
            max_completion_tokens=MAX_TOKENS,
        )
    except Exception as e:
        motivo, mensagem = _classificar(e)
        raise ErroDeIA(mensagem, motivo) from e

    texto = (resposta.choices[0].message.content or "").strip()
    if not texto:
        raise ErroDeIA(
            f"O modelo {settings.OPENAI_MODEL} respondeu vazio. Tente de novo; "
            "persistindo, confira se o modelo configurado em OPENAI_MODEL "
            "existe na sua conta.", "vazio")
    return texto


def gerar(dados):
    """Texto cru do modelo, no formato do prompt (com asteriscos).

    Levanta `ErroDeIA` — a view mostra a mensagem e mantém o texto do motor.
    """
    if not disponivel():
        raise ErroDeIA("Nenhuma chave de API configurada: defina OPENAI_API_KEY "
                       "no ambiente (em produção, /etc/apex-reports/env).",
                       "chave")
    return _chamar([
        {"role": "system", "content": PROMPT_OPERADOR + REGRAS_DE_ENTRADA},
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
