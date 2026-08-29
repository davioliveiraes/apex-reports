# -*- coding: utf-8 -*-
"""
Leitura Rápida — a ponte entre o export lido e a mensagem escrita.

O motor (`analysis/mensagem.py`) é puro: recebe uma `Avaliacao`, métricas e uma
lista de frentes já rotuladas, e devolve texto. Quem sabe que existe planilha é
este arquivo — ele tira do `consolidar` o que a mensagem precisa e traduz o
nome cru da campanha (`[LEADS][CELULAR][ITU][ABO][01SET25]`) no nome que o
cliente reconhece ("Itu").

A frente inteira roda sobre o MESMO export da Análise de Desempenho. Não é
economia de código, é o que garante que a mensagem do WhatsApp e o PDF nunca
contem números diferentes do mesmo mês: os dois saem de `consolidar`.
"""

from .analysis import mensagem as _mensagem
from .analysis import rules
from .analysis.numeros import decimal, inteiro, moeda
from .indicadores import termos
from .parser_xlsx import rotulo_campanha, tokens_comuns

# O que a sessão guarda do `consolidar`. Fora daqui ficam os gráficos, o funil
# e as tabelas do PDF: são a maior parte do dicionário e esta frente não
# desenha nenhum deles. Os campos abaixo são exatamente os que a mensagem e o
# payload da IA leem — tirar qualquer um quebra um dos dois.
CAMPOS_SESSAO = ("_num", "_colunas", "_metricas", "_campanhas", "_dias",
                 "avaliacao", "periodo", "indicador", "kpis")


def enxuto(dados):
    """O `consolidar` reduzido ao que esta frente usa."""
    return {k: dados[k] for k in CAMPOS_SESSAO if k in dados}


def avaliacao(dados):
    """A `Avaliacao` de volta como objeto.

    `consolidar` a guarda em `dados["avaliacao"]` já convertida em dict, para
    caber na sessão. O motor de texto precisa do `.tem()` e do `.derivados`,
    então ela é remontada aqui — os campos são os mesmos, o `asdict` não perde
    nenhum.
    """
    return rules.Avaliacao(**dados["avaliacao"])


def recortes(dados):
    """As frentes comparáveis do relatório, uma por campanha.

    O rótulo sai do que **distingue** cada campanha das outras da conta (ver
    `parser_xlsx.rotulo_campanha`): normalmente a praça, às vezes o produto.
    Campanha sem nome na planilha fica de fora — uma frente anônima não dá
    para citar numa frase, e citá-la como "(sem nome)" entregaria ao cliente a
    bagunça do nosso preenchimento.
    """
    campanhas = dados.get("_campanhas") or {}
    comuns = tokens_comuns(campanhas)
    linhas = []
    for nome, c in campanhas.items():
        rotulo = rotulo_campanha(nome, comuns)
        if not rotulo:
            continue
        linhas.append({"rotulo": rotulo,
                       "resultados": c.get("res") or 0.0,
                       "investimento": c.get("inv") or 0.0})
    return linhas


def mensagem(dados):
    """A leitura do período, pronta para copiar no WhatsApp."""
    aval = avaliacao(dados)
    return _mensagem.redigir_leitura(
        aval, dados.get("_metricas") or dados.get("_num") or {},
        periodo=dados.get("periodo") or "",
        recortes=recortes(dados),
        termo=termos(dados.get("indicador")))


def tem_fadiga(dados):
    """O relatório disparou o pedido de criativos novos?

    A tela mostra isso à parte porque é a única frase da mensagem que pede
    algo ao cliente além de informação — o operador merece vê-la sinalizada
    antes de enviar, não descobri-la lendo.
    """
    return _mensagem.tem_fadiga(avaliacao(dados))


# Cor do selo na tela, derivada da classificação e não de uma segunda regra:
# duas escadas para a mesma coisa acabariam discordando uma da outra.
TOM_DA_CLASSIFICACAO = {"OTIMO": "otimo", "BOM": "bom", "ATENCAO": "atencao"}


def resumo(dados):
    """Os números do período já formatados, para a coluna lateral da tela."""
    num = dados.get("_num") or {}
    aval = avaliacao(dados)
    frentes = len(recortes(dados))
    return {
        "classificacao": _mensagem.CLASSIFICACAO[aval.classificacao],
        "tom": TOM_DA_CLASSIFICACAO[aval.classificacao],
        "investimento_txt": moeda(num.get("investimento")),
        "resultados_txt": inteiro(num.get("resultados")),
        "cpa_txt": moeda(num.get("custo_resultado")),
        "frequencia_txt": decimal(num.get("frequencia")),
        "termo_singular": termos(dados.get("indicador"))[0],
        "termo_plural": termos(dados.get("indicador"))[1],
        "frentes": frentes,
        "tem_fadiga": _mensagem.tem_fadiga(aval),
        "sem_periodo": not (dados.get("periodo") or ""),
    }
