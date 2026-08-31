# -*- coding: utf-8 -*-
"""
O diagnóstico: os quatro blocos e o ponto de atenção.

Como o gargalo é escolhido — e por que não é por limiar
-------------------------------------------------------
A §20 pede que a análise aponte a etapa que merece atenção; a §21 proíbe
inventar benchmark ("CTR bom = X", "carregamento bom = X"). As duas convivem
se o gargalo sair de **comparação**, e não de régua.

O problema de comparar as etapas entre si é que elas não são comparáveis. Uma
perda de 20% entre clique e carregamento e uma perda de 85% entre os marcos de
25% e 100% do vídeo não medem a mesma coisa: quase todo funil de vídeo perde
mais de 80% até o fim, e isso é o normal do formato, não um defeito. Eleger o
maior número faria o vídeo ser sempre o gargalo, em todo arquivo, para sempre.

Por isso a escolha segue uma ordem de **força de evidência**, e cada nível tem
um gatilho que se sustenta sozinho:

1. RELEVÂNCIA — o Meta classificou algo abaixo da média. É o único sinal que
   não sai da nossa própria aritmética: ele compara o anúncio com os
   concorrentes reais pelo mesmo público, coisa que o arquivo não permite
   fazer. Vale mais que qualquer razão calculada aqui.
2. A etapa com maior DISPERSÃO entre anúncios. Se um anúncio carrega 90% dos
   cliques e outro 40%, a perda é demonstravelmente evitável — a prova está no
   próprio arquivo, num anúncio que conseguiu. Sem dois anúncios não há
   comparação, e sem comparação não há esta conclusão.
3. Nada. `None`, que a tela escreve como "Sem evidência suficiente para
   apontar um gargalo principal" — o que a §26 prefere a uma conclusão
   inventada.

Dentro do bloco de retenção, dizer entre quais marcos a queda foi maior é
outra coisa e é sempre legítimo: é comparação interna ao mesmo funil, com a
mesma população, e a §14 autoriza explicitamente.

O lugar reservado para as regras oficiais
-----------------------------------------
Quando existirem faixas calibradas, elas entram em `LIMIARES` abaixo e
`gargalo()` ganha um nível 0 acima da relevância. Parser, métricas e texto não
mudam — é o motivo de este arquivo estar separado dos outros dois.
"""

from ..parser_rastreamento import (BLOCO_CLIQUE, BLOCO_DESTINO,
                                   BLOCO_RELEVANCIA, BLOCO_RETENCAO, RANKINGS)
from . import metricas

# A partir de quanto dois anúncios "diferem de verdade" na mesma etapa. Não é
# benchmark: não diz que 2% de CTR é bom, diz que 2% e 0,6% no mesmo arquivo
# são coisas diferentes o bastante para valer uma frase. É o mesmo critério
# relativo que a Análise de Desempenho usa entre conjuntos.
MARGEM_RELATIVA = 1.3

# Reservado para a metodologia oficial (§21). Vazio de propósito: um dicionário
# vazio é uma promessa; um dicionário com números chutados é uma dívida.
LIMIARES = {}

TITULOS = {
    BLOCO_CLIQUE: "Clique",
    BLOCO_DESTINO: "Destino",
    BLOCO_RELEVANCIA: "Relevância",
    BLOCO_RETENCAO: "Retenção",
}

PERGUNTAS = {
    BLOCO_CLIQUE: "O anúncio está transformando exibição em clique?",
    BLOCO_DESTINO: "Quem clica chega ao destino?",
    BLOCO_RELEVANCIA: "Como o Meta compara este anúncio com os concorrentes?",
    BLOCO_RETENCAO: "O vídeo segura a atenção depois que começa?",
}

ROTULO_RANKING = {
    "quality_ranking": "Qualidade",
    "engagement_rate_ranking": "Engajamento",
    "conversion_rate_ranking": "Conversão",
}

# O que a tela escreve quando o bloco não pôde ser avaliado. Cada ausência tem
# a sua razão provável, e dizer "sem dados" nos quatro casos jogaria no
# operador a tarefa de descobrir qual é qual.
AUSENCIAS = {
    BLOCO_CLIQUE: "O arquivo não trouxe métricas de clique.",
    BLOCO_DESTINO: ("Sem visualizações da página de destino neste arquivo — "
                    "é o esperado quando a campanha manda direto para "
                    "WhatsApp, Direct ou Messenger."),
    BLOCO_RELEVANCIA: ("O Meta ainda não publicou classificação de relevância "
                       "para estes anúncios — costuma faltar volume."),
    BLOCO_RETENCAO: "Sem métricas de vídeo neste arquivo.",
}


def diagnosticar(total, disponiveis):
    """O diagnóstico inteiro: os quatro blocos e o ponto de atenção."""
    blocos = [_clique(total, disponiveis), _destino(total, disponiveis),
              _relevancia(total, disponiveis), _retencao(total, disponiveis)]
    return {"blocos": blocos, "gargalo": gargalo(total, blocos)}


# ----------------------------------------------------------------------
# Os quatro blocos
# ----------------------------------------------------------------------
def _bloco(chave, disponivel, metricas_, sinais=(), nota=None):
    return {"chave": chave, "titulo": TITULOS[chave],
            "pergunta": PERGUNTAS[chave], "disponivel": disponivel,
            "metricas": [m for m in metricas_ if m["valor"] is not None],
            "sinais": list(sinais),
            "nota": nota if not disponivel else None,
            "ausencia": AUSENCIAS[chave]}


def _clique(total, disponiveis):
    """Volume, taxa e custo do clique.

    Os dois CTR aparecem lado a lado mas nunca comparados: têm denominadores
    diferentes (impressões contra alcance), e tratá-los como a mesma medida
    faria o único aparecer sempre "melhor".
    """
    tem = any(c in disponiveis for c in
              ("link_clicks", "link_ctr", "link_cpc", "unique_link_clicks"))
    m = [
        {"chave": "link_clicks", "rotulo": "Cliques no link",
         "valor": total.get("link_clicks"), "formato": "inteiro"},
        {"chave": "unique_link_clicks", "rotulo": "Cliques únicos",
         "valor": total.get("unique_link_clicks"), "formato": "inteiro"},
        {"chave": "link_ctr", "rotulo": "CTR do link",
         "valor": total.get("link_ctr"), "formato": "percentual"},
        {"chave": "unique_link_ctr", "rotulo": "CTR único",
         "valor": total.get("unique_link_ctr"), "formato": "percentual"},
        {"chave": "link_cpc", "rotulo": "CPC do link",
         "valor": total.get("link_cpc"), "formato": "moeda"},
    ]
    return _bloco(BLOCO_CLIQUE, tem, m, _sinais_de_dispersao(total, "link_ctr"))


def _destino(total, disponiveis):
    """A passagem do clique para o carregamento da página.

    Derivada legítima porque as duas pontas estão no arquivo. Ausente, não é
    problema: é o retrato de uma campanha de mensagem (§11).
    """
    tem = total.get("landing_page_views") is not None
    m = [
        {"chave": "landing_page_views", "rotulo": "Visualizações do destino",
         "valor": total.get("landing_page_views"), "formato": "inteiro"},
        {"chave": "cost_per_landing_page_view", "rotulo": "Custo por visualização",
         "valor": total.get("cost_per_landing_page_view"), "formato": "moeda"},
        {"chave": "taxa_carregamento", "rotulo": "Taxa de carregamento",
         "valor": total.get("taxa_carregamento"), "formato": "percentual"},
    ]
    return _bloco(BLOCO_DESTINO, tem, m,
                  _sinais_de_dispersao(total, "taxa_carregamento"))


def _relevancia(total, disponiveis):
    """As três classificações do Meta, como o Meta as escreveu.

    Categóricas: nada aqui vira número. O sinal de atenção é factual — "o Meta
    classificou abaixo da média" —, e a interpretação (criativo, público,
    oferta) fica de fora porque o arquivo não distingue entre elas.
    """
    rk = total.get("rankings") or {}
    tem = any(rk.get(c, {}).get("valores") for c in RANKINGS)
    m = [{"chave": c, "rotulo": ROTULO_RANKING[c],
          "valor": _valor_ranking(rk.get(c, {}), total["n_anuncios"]),
          "formato": "texto"} for c in RANKINGS]

    sinais = []
    for campo in RANKINGS:
        abaixo = rk.get(campo, {}).get("abaixo") or []
        if abaixo:
            sinais.append({
                "tipo": "abaixo_da_media", "campo": campo,
                "rotulo": ROTULO_RANKING[campo], "alvos": abaixo,
                "texto": (f"{ROTULO_RANKING[campo]} abaixo da média em "
                          f"{_lista(abaixo)}.")})
    return _bloco(BLOCO_RELEVANCIA, tem, m, sinais)


def _valor_ranking(resumo, n_anuncios):
    """A classificação para a tela.

    Com um valor só (ou um anúncio só) mostra o valor. Com anúncios
    discordando, mostra a contagem em vez de escolher um vencedor — a média de
    categorias não existe.
    """
    if not resumo.get("valores"):
        return None
    if resumo.get("unico"):
        return resumo["unico"]
    abaixo = len(resumo.get("abaixo") or [])
    if abaixo:
        return f"{abaixo} de {n_anuncios} abaixo da média"
    return f"{len(set(resumo['valores']))} classificações distintas"


def _retencao(total, disponiveis):
    """O funil do vídeo, e onde ele perde mais.

    Só existe se houver anúncio em vídeo. Para um arquivo de imagens o bloco
    não é mostrado vazio — ele some, e a tela diz por quê numa linha (§25).
    """
    tem = total.get("n_video", 0) > 0
    ret = total.get("retencao") or {}
    m = [
        {"chave": "video_3s_views", "rotulo": "Reproduções de 3s",
         "valor": total.get("video_3s_views"), "formato": "inteiro"},
        {"chave": "thruplays", "rotulo": "ThruPlays",
         "valor": total.get("thruplays"), "formato": "inteiro"},
        {"chave": "cost_per_thruplay", "rotulo": "Custo por ThruPlay",
         "valor": total.get("cost_per_thruplay"), "formato": "moeda"},
        {"chave": "video_25", "rotulo": "25% do vídeo",
         "valor": total.get("video_25"), "formato": "inteiro"},
        {"chave": "video_50", "rotulo": "50% do vídeo",
         "valor": total.get("video_50"), "formato": "inteiro"},
        {"chave": "video_75", "rotulo": "75% do vídeo",
         "valor": total.get("video_75"), "formato": "inteiro"},
        {"chave": "video_100", "rotulo": "100% do vídeo",
         "valor": total.get("video_100"), "formato": "inteiro"},
        {"chave": "retencao_25_100", "rotulo": "Chegam ao fim (de 25%)",
         "valor": ret.get("25_100"), "formato": "percentual"},
    ]

    sinais = []
    queda = metricas.maior_queda(ret)
    if queda:
        # Comparação interna ao mesmo funil, com a mesma população — a única
        # afirmação que os marcos sustentam. O XLSX não tem linha do tempo do
        # vídeo, então em que SEGUNDO a queda aconteceu não se sabe (§14).
        trecho, perda = queda
        sinais.append({"tipo": "maior_queda", "trecho": trecho,
                       "perda": perda,
                       "texto": (f"A maior perda proporcional aconteceu entre "
                                 f"os marcos de {trecho}.")})
    return _bloco(BLOCO_RETENCAO, tem, m, sinais)


def _lista(nomes):
    """"A", "A e B", "A, B e C" — sem vírgula serial, que não existe em
    português."""
    nomes = list(nomes)
    if len(nomes) == 1:
        return nomes[0]
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


# ----------------------------------------------------------------------
# Dispersão entre anúncios
# ----------------------------------------------------------------------
# Como cada métrica comparável se escreve numa frase. Fica aqui, e não no
# template, porque a evidência do gargalo entra no texto do cliente — e lá não
# existe filtro de template.
_COMPARAVEIS = {
    "link_ctr": ("O CTR", "percentual"),
    "taxa_carregamento": ("A taxa de carregamento", "percentual"),
}


def percentual(valor):
    """"1,40%" e "76%" — duas casas só onde elas mudam a leitura.

    Um CTR de 1,4% precisa da casa decimal; uma taxa de carregamento de 76%
    não, e "75,74%" ali é precisão que ninguém pediu. É a mesma função que a
    tela e a prosa usam, para o cartão não dizer "75,74%" ao lado de uma frase
    que diz "76%".
    """
    casas = 2 if abs(valor) < 10 else 0
    return f"{valor:.{casas}f}".replace(".", ",") + "%"


def _escrever(valor, formato):
    if formato == "percentual":
        return percentual(valor)
    return f"{valor:.2f}".replace(".", ",")


def _sinais_de_dispersao(total, campo):
    """Anúncios que destoam dos demais na mesma métrica.

    Só com dois ou mais anúncios: sem um segundo anúncio no arquivo não existe
    "os demais", e a comparação vira comparação com uma régua inventada.
    """
    anuncios = [a for a in total.get("anuncios", [])
                if a.get(campo) is not None]
    if len(anuncios) < 2:
        return []

    melhor = max(anuncios, key=lambda a: a[campo])
    pior = min(anuncios, key=lambda a: a[campo])
    if not pior[campo] or melhor[campo] < pior[campo] * MARGEM_RELATIVA:
        return []

    nome, formato = _COMPARAVEIS.get(campo, ("A métrica", "decimal"))
    return [{"tipo": "dispersao", "campo": campo,
             "melhor": melhor["rotulo"], "pior": pior["rotulo"],
             "valor_melhor": melhor[campo], "valor_pior": pior[campo],
             "razao": melhor[campo] / pior[campo],
             "texto": (f"{nome} variou de "
                       f"{_escrever(pior[campo], formato)} em "
                       f"{pior['rotulo']} a "
                       f"{_escrever(melhor[campo], formato)} em "
                       f"{melhor['rotulo']}."),
             "evidencia": (f"{nome.lower()} foi de "
                           f"{_escrever(pior[campo], formato)} em "
                           f"{pior['rotulo']} contra "
                           f"{_escrever(melhor[campo], formato)} em "
                           f"{melhor['rotulo']}, no mesmo período")}]


# ----------------------------------------------------------------------
# O gargalo
# ----------------------------------------------------------------------
def gargalo(total, blocos):
    """A etapa que merece mais atenção, ou `None`.

    Ordem de força de evidência — ver o cabeçalho do módulo para o porquê de
    não ser "a maior perda".
    """
    por_chave = {b["chave"]: b for b in blocos}

    # 1. O Meta comparou com os concorrentes; nós não conseguimos.
    relevancia = por_chave[BLOCO_RELEVANCIA]
    if relevancia["disponivel"] and relevancia["sinais"]:
        campos = _lista([s["rotulo"].lower() for s in relevancia["sinais"]])
        return {"bloco": BLOCO_RELEVANCIA, "titulo": TITULOS[BLOCO_RELEVANCIA],
                "evidencia": (f"o Meta classificou {campos} abaixo da média "
                              "para o público disputado")}

    # 2. A etapa em que os anúncios mais divergem entre si: a perda é
    #    demonstravelmente evitável, e a prova é o anúncio que conseguiu.
    candidatos = [(b, s) for b in blocos for s in b["sinais"]
                  if s["tipo"] == "dispersao"]
    if candidatos:
        bloco, sinal = max(candidatos, key=lambda c: c[1]["razao"])
        return {"bloco": bloco["chave"], "titulo": bloco["titulo"],
                "evidencia": sinal["evidencia"]}

    # 3. Sem comparação possível, nenhuma conclusão. É melhor do que uma
    #    inventada (§26).
    return None
