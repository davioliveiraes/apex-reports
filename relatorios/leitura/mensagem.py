# -*- coding: utf-8 -*-
"""
A leitura curta, pronta para colar no grupo do cliente.

Três parágrafos e uma pergunta. O tamanho é a funcionalidade: esta mensagem
compete com o tempo de rolagem de um grupo de WhatsApp, e uma leitura de meia
tela não é lida — é ignorada. Quem quer a análise longa tem a Análise de
Desempenho, que existe exatamente para isso.

    *Leitura do período — 30/07 a 28/08*

    [1] o que aconteceu     — resultado e custo
    [2] como foi a entrega  — alcance, frequência, CPM
    [3] qual é a leitura    — a interpretação executiva
    *Ponto comercial:* ...  — a pergunta que cruza com a venda

Tom
---
De gestor de tráfego, não de gerador de texto: direto, sem adjetivo que os
números não sustentem, sem "performance sólida e promissora". Frequência é
relatada ("permaneceu em 4,45"), nunca julgada ("sem saturação") — o preset
não tem como sustentar o julgamento.

Formatação
----------
Só `*negrito*`, que é o que o WhatsApp entende. Sem tabela, sem bullet, sem
markdown de título: o que não renderiza no aplicativo vira lixo visível na
tela do cliente.
"""

from ..analysis.numeros import decimal, inteiro, moeda

TITULO = "Leitura do período"


def redigir(dados):
    """A mensagem inteira, a partir da saída de `resumo.montar`."""
    blocos = [_cabecalho(dados), _resultado(dados), _entrega(dados),
              _leitura(dados), _ponto_comercial(dados)]
    return "\n\n".join(b for b in blocos if b)


def _cabecalho(dados):
    """O título, com o selo de classificação quando ele existir.

    Hoje nunca existe (ver `resumo.classificar`), e a linha fica só com o
    período — que é o que a §12 pede enquanto não houver metodologia.
    """
    selo = dados.get("classificacao")
    titulo = f"{TITULO} — {selo}" if selo else TITULO
    periodo = dados.get("periodo")
    return f"*{titulo} — {periodo}*" if periodo else f"*{titulo}*"


def _resultado(dados):
    """Parágrafo 1 — o que aconteceu."""
    total = dados["resultado_principal"]
    um = total == 1
    termo = dados["termo_singular"] if um else dados["termo_plural"]

    # Uma campanha marcada, uma campanha na frase. O plural genérico ficou
    # para o export de conjuntos, onde a aplicação não sabe a quantas
    # campanhas aquelas linhas pertencem.
    uma = dados.get("n_campanhas") == 1
    sujeito = "a campanha" if uma else "as campanhas"

    if not total:
        return (f"No período{_no_periodo(dados)}, {sujeito} ainda não "
                f"registr{'ou' if uma else 'aram'} {dados['termo_plural']}.")

    frase = (f"No período{_no_periodo(dados)}, {sujeito} "
             f"{'gerou' if uma else 'geraram'} {inteiro(total)} {termo}")
    custo = dados.get("custo_principal")
    if custo:
        frase += (f", com custo médio de {moeda(custo)} por "
                  f"{dados['termo_singular']}")
    return frase + "."


def _no_periodo(dados):
    return f" de {dados['periodo']}" if dados.get("periodo") else ""


def _entrega(dados):
    """Parágrafo 2 — como foi a entrega.

    Impressões ficam de fora: alcance responde "quanta gente" e frequência
    responde "quantas vezes", e as impressões são o produto das duas. Num
    texto de três parágrafos, o número redundante é o primeiro a sair.

    A frequência é relatada, não julgada. "Sem saturação" exigiria uma
    referência que este preset não tem.
    """
    alcance = dados.get("alcance")
    if not alcance:
        return ""

    frase = f"A entrega alcançou {inteiro(alcance)} pessoas"
    detalhes = []
    if dados.get("frequencia"):
        detalhes.append(f"frequência de {decimal(dados['frequencia'])}")
    if dados.get("cpm"):
        detalhes.append(f"CPM de {moeda(dados['cpm'])}")
    if detalhes:
        frase += ", com " + " e ".join(detalhes)
    return frase + "."


def _leitura(dados):
    """Parágrafo 3 — a interpretação executiva.

    Uma coisa só, escolhida por quanto informa: a fatia de contatos novos
    quando ela existe (é o que diz se a verba trouxe gente nova ou reaqueceu
    a base), senão o único fato comparativo entre conjuntos (§23).

    Nenhuma causa é afirmada. "Criativo saturado", "público ruim" e "problema
    no atendimento" são hipóteses que o arquivo não distingue entre si.
    """
    partes = []
    fatia = dados.get("fatia_novos")
    novos = dados.get("novos_contatos") or 0.0

    if fatia and novos:
        partes.append(
            f"Dos contatos do período, {inteiro(novos)} "
            f"({_pct(fatia)}) foram de pessoas que ainda não haviam falado "
            "com a empresa.")
    elif novos:
        partes.append(f"O período trouxe {inteiro(novos)} contatos novos.")

    comparativo = _comparativo(dados)
    if comparativo:
        partes.append(comparativo)

    # Sem contato novo e sem comparação entre conjuntos, o terceiro parágrafo
    # simplesmente não existe. A tentação era fechar com o custo, mas ele já
    # foi dito no primeiro — e repetir número é o que faz uma leitura curta
    # parecer preenchimento de espaço (§21). Duas frases e a pergunta é uma
    # leitura completa; três com uma repetida, não.
    return " ".join(partes)


def _comparativo(dados):
    """O único fato entre conjuntos que cabe aqui.

    A comparação completa é da Análise de Desempenho — repeti-la seria
    transformar a leitura rápida no relatório que ela existe para não ser.
    """
    c = dados.get("comparativo")
    if not c:
        return ""
    quem = "A campanha" if c.get("eh_campanha") else "O conjunto"
    if c["tipo"] == "concentracao":
        return (f"{quem} {c['rotulo']} concentrou a maior parte dos "
                f"resultados ({_pct(c['valor'])}).")
    return (f"{quem} {c['rotulo']} apresentou o menor custo por "
            f"{dados['termo_singular']} entre os analisados "
            f"({moeda(c['valor'])}).")


def _ponto_comercial(dados):
    """A pergunta, destacada e separada dos parágrafos.

    Vem rotulada porque tem outra função: os três parágrafos informam, esta
    linha pede uma resposta. Sem o rótulo ela se perde como quarta frase de um
    texto corrido, e é justamente ela que fecha o ciclo com a venda.
    """
    pergunta = dados.get("pergunta_comercial")
    return f"*Ponto comercial:* {pergunta}" if pergunta else ""


def _pct(fracao):
    """"73%" — sem casa decimal.

    "73,28%" numa mensagem de WhatsApp é precisão que ninguém pediu e que
    denuncia número jogado direto do cálculo para a frase.
    """
    return f"{round(fracao * 100)}%"
