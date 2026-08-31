# -*- coding: utf-8 -*-
"""
O que entra na leitura curta — a saída estruturada, antes de virar texto.

Recebe o consolidado da Análise de Desempenho e escolhe. Escolher é o trabalho
desta frente: o preset tem nove métricas e a mensagem cabe em três parágrafos,
então a maior parte do que existe fica de fora de propósito. Um despejo de
métricas não é leitura rápida — é a Análise de Desempenho com menos cuidado.

Nada aqui redige. `mensagem.py` recebe este dicionário e escreve; a tela recebe
o mesmo dicionário e mostra. É o que impede a regra de escorregar para dentro
do template.
"""

from ..analysis.numeros import decimal, inteiro, moeda

# Quanto um conjunto precisa concentrar para a leitura dizer que ele concentra.
# Mesmo critério da Análise de Desempenho, e pelo mesmo motivo: com 52% contra
# 48% a frase descreveria um empate como domínio. Não é benchmark de mercado —
# é uma fatia do próprio arquivo.
FATIA_DE_CONCENTRACAO = 0.6


def montar(total):
    """A leitura curta em forma de dados.

    `total` é a saída de `analise_desempenho.consolidar` — o mesmo modelo
    normalizado que a Análise de Desempenho usa, sem uma segunda consolidação
    (ver §24 da especificação: frequência e CPM não somam, custo por resultado
    não é média simples, e essas regras já estão resolvidas lá).
    """
    singular, plural, _ = total["termos"]
    conversas = total.get("conversas") or 0.0
    novos = total.get("novos_contatos") or 0.0

    return {
        "periodo": _periodo(total),
        "classificacao": classificar(total),
        "resultado_principal": total.get("resultados") or 0.0,
        "termo_singular": singular,
        "termo_plural": plural,
        "custo_principal": total.get("custo_resultado"),
        "conversas": conversas,
        # Numa campanha de mensagem, "Resultados" e "Conversas por mensagem
        # iniciadas" são a MESMA coluna com dois nomes — 393 e 393. Mostrar as
        # duas lado a lado faria a tela parecer que houve 786 de alguma coisa.
        "resultado_e_conversa": bool(total.get("eh_conversa")
                                     and conversas
                                     and conversas == total.get("resultados")),
        "novos_contatos": novos,
        # A fatia de contatos novos é a leitura executiva mais forte que este
        # preset sustenta sozinho: sai de duas colunas do arquivo e não
        # depende de comparação com nada de fora.
        "fatia_novos": (novos / conversas) if conversas and novos else None,
        "alcance": total.get("alcance"),
        "frequencia": total.get("frequencia"),
        "cpm": total.get("cpm"),
        "n_conjuntos": total.get("n_conjuntos") or 0,
        # Quantas CAMPANHAS distintas entraram. Zero num export de conjuntos
        # sem coluna de campanha — e aí o texto fica no plural genérico, que é
        # como ele sempre foi.
        "n_campanhas": total.get("n_campanhas") or 0,
        "comparativo": _comparativo(total),
        "pergunta_comercial": pergunta_comercial(total),
    }


def classificar(total):
    """Sempre `None` — não há metodologia aplicável a este preset.

    `analysis/benchmarks.py` tem faixas de CPA, mas o próprio arquivo as
    declara "estimadas" e "não benchmark de mercado verificado", e elas
    dependem de um **perfil de negócio** que esta tela não pergunta (o fluxo
    é de um clique). O padrão seria `varejo_celular`, com faixa R$ 4/R$ 9 —
    aplicá-la a uma conta TIM, que tem faixa própria no mesmo arquivo,
    classificaria pela régua errada e com cara de método.

    A §12 previu exatamente este caso: sem regra confiável, a saída usa
    "Leitura do período" e nenhuma nota classificatória. Quando a faixa
    existir, é esta função que passa a devolver o selo — `montar`, a mensagem
    e o template já tratam `None`.
    """
    return None


def _periodo(total):
    """"30/07 a 28/08" — sem ano, que é como se escreve num grupo.

    O ano completo fica na tela, ao lado dos números; na mensagem ele só
    ocuparia espaço num texto que precisa ser lido de relance.
    """
    inicio, fim = total.get("inicio"), total.get("termino")
    if not (inicio and fim):
        return ""
    return f"{_curta(inicio)} a {_curta(fim)}"


def _curta(iso):
    partes = str(iso)[:10].split("-")
    return f"{partes[2]}/{partes[1]}" if len(partes) == 3 else str(iso)


def _comparativo(total):
    """UMA informação comparativa, ou `None` (§23).

    A comparação completa entre conjuntos é da Análise de Desempenho. Aqui
    cabe um fato, e ele é escolhido por relevância: concentração de resultados
    quando existe concentração de verdade; senão, o menor custo entre os
    conjuntos, que é o que o operador leva para a próxima decisão.
    """
    conjuntos = [c for c in total.get("conjuntos") or () if c.get("resultados")]
    if len(conjuntos) < 2:
        return None

    lider = max(conjuntos, key=lambda c: c["participacao"])
    if lider["participacao"] >= FATIA_DE_CONCENTRACAO:
        return {"tipo": "concentracao", "rotulo": lider["rotulo"],
                "valor": lider["participacao"],
                # A linha comparada é uma campanha ou um conjunto conforme a
                # aba de onde o export saiu. Sem este sinal a frase chamava
                # tudo de "conjunto", inclusive campanha.
                "eh_campanha": bool(lider.get("campanha"))}

    com_custo = [c for c in conjuntos if c.get("custo_resultado")]
    if not com_custo:
        return None
    barato = min(com_custo, key=lambda c: c["custo_resultado"])
    return {"tipo": "menor_custo", "rotulo": barato["rotulo"],
            "valor": barato["custo_resultado"],
            "eh_campanha": bool(barato.get("campanha"))}


def pergunta_comercial(total):
    """A pergunta que fecha a mensagem — o motivo de ela existir.

    O Meta mostra o contato gerado; quem sabe se ele virou venda é o cliente.
    Perguntar é o que cruza tráfego → atendimento → venda, e é a única forma
    honesta de chegar lá: nada no arquivo diz quantas vendas houve.

    Prioridade da §19: contatos novos, depois conversas, depois a pergunta sem
    número. O `> 0` importa — "Dos 0 novos contatos" seria pior que a pergunta
    genérica.
    """
    novos = total.get("novos_contatos") or 0.0
    conversas = total.get("conversas") or 0.0

    if novos > 0:
        return (f"Dos {inteiro(novos)} novos contatos gerados nesse período, "
                "quantos avançaram para venda?")
    if conversas > 0:
        return (f"Das {inteiro(conversas)} conversas iniciadas nesse período, "
                "quantas resultaram em vendas?")
    # Sem número no arquivo, pergunta sem número. Inventar um aqui destruiria
    # a confiança em todos os outros.
    return "Quantos atendimentos desse período avançaram para venda?"


def cartoes(dados):
    """Os quatro números do topo da tela, já escritos (§11).

    Quatro, e não nove: a tela da leitura rápida é mais simples que a da
    Análise de Desempenho de propósito. Métrica sem valor sai da lista em vez
    de virar um traço.
    """
    brutos = [
        (dados["termo_plural"].capitalize(), dados["resultado_principal"],
         inteiro),
        (f"Custo por {dados['termo_singular']}", dados["custo_principal"],
         moeda),
        ("Conversas", dados["conversas"], inteiro),
        ("Novos contatos", dados["novos_contatos"], inteiro),
    ]
    if dados.get("resultado_e_conversa"):
        # O primeiro cartão já é essa conversa, com o nome do indicador.
        brutos.pop(2)
    return [{"rotulo": r, "valor": f(v)} for r, v, f in brutos
            if v is not None]


def entrega(dados):
    """Alcance, frequência e CPM para a lateral — o que o parágrafo 2 usa."""
    brutos = [("Alcance", dados["alcance"], inteiro),
              ("Frequência", dados["frequencia"], decimal),
              ("CPM", dados["cpm"], moeda)]
    return [{"rotulo": r, "valor": f(v)} for r, v, f in brutos
            if v is not None]
