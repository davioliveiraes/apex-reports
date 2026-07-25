# -*- coding: utf-8 -*-
"""
Faixas de referência (benchmarks) das métricas de mídia — uso INTERNO.

A classificação (abaixo / dentro / acima da faixa) alimenta as leituras dos
cards do funil e a escolha das frases da "Análise do Período", sempre
traduzida para linguagem de cliente. Os termos de diagnóstico dos
comentários abaixo (saturação de público, gargalo no destino etc.) ficam
restritos a este módulo — nunca aparecem no relatório.

Valores iniciais para o mercado Meta Ads em 2026. As faixas variam por
vertical e por objetivo de campanha: ajuste editando as constantes ou
passando o dict `faixas` em avaliar_metricas().
"""

# Cada faixa é (mínimo, máximo) do intervalo considerado "dentro do esperado".
CTR_LINK = (2.0, 5.0)          # % — abaixo: criativo perdendo atratividade
CPC = (0.50, 3.00)             # R$ — acima/subindo: possível saturação de público
CPM = (25.0, 60.0)             # R$ — acima: leilão concorrido no público
TAXA_CONVERSAO = (3.0, 10.0)   # % clique→resultado — abaixo: gargalo no destino
                               # (página/WhatsApp), não no anúncio
FREQUENCIA_FRIO = (1.5, 2.5)   # acima: ampliar público
FREQUENCIA_RETARGET = (3.0, 6.0)  # aplicar apenas quando o retargeting for
                                  # identificável; caso contrário, faixa de frio

FAIXAS_PADRAO = {
    "ctr": CTR_LINK,
    "cpc": CPC,
    "cpm": CPM,
    "taxa_conversao": TAXA_CONVERSAO,
    "frequencia": FREQUENCIA_FRIO,
}

# Classificações possíveis de uma métrica
ABAIXO, DENTRO, ACIMA, EXCELENTE = "abaixo", "dentro", "acima", "excelente"


def avaliar_metricas(numeros, faixas=None, retargeting=False):
    """
    Classifica cada métrica disponível em `numeros` (dict com os valores
    numéricos de ctr, cpc, cpm, taxa_conversao e frequencia; None = ausente)
    como 'abaixo' / 'dentro' / 'acima' da faixa de referência.

    Casos especiais:
    - taxa_conversao > 100% é possível em campanhas de conversa (conversas
      podem originar de visualizações, sem clique) → 'excelente', nunca
      tratada como anomalia;
    - retargeting=True troca a faixa de frequência pela de retargeting.

    `faixas` permite override por chamada, ex.: {"ctr": (1.0, 3.0)}.
    Métricas ausentes em `numeros` ficam fora do resultado.
    """
    ativas = dict(FAIXAS_PADRAO)
    if retargeting:
        ativas["frequencia"] = FREQUENCIA_RETARGET
    if faixas:
        ativas.update(faixas)

    avaliacao = {}
    for metrica, (minimo, maximo) in ativas.items():
        valor = (numeros or {}).get(metrica)
        if valor is None:
            continue
        if metrica == "taxa_conversao" and valor > 100:
            avaliacao[metrica] = EXCELENTE
        elif valor < minimo:
            avaliacao[metrica] = ABAIXO
        elif valor > maximo:
            avaliacao[metrica] = ACIMA
        else:
            avaliacao[metrica] = DENTRO
    return avaliacao
