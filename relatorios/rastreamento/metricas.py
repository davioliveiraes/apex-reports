# -*- coding: utf-8 -*-
"""
Os números do rastreamento: agregação e taxas derivadas.

Duas regras governam este arquivo.

**Aditiva soma, taxa não.** Cliques, visualizações e marcos de vídeo somam.
CTR, CPC, custo por visualização e custo por ThruPlay são razões — somá-las
não significa nada, e a média simples entre anúncios mente sempre que um
anúncio entregou dez vezes mais que o outro.

**Taxa consolidada só com o denominador de volta.** Toda razão aqui é
reconstruída como `Σ numerador / Σ denominador`, nunca como média. O
denominador vem da própria definição da métrica invertida:

    impressões = cliques ÷ (CTR ÷ 100)
    alcance    = cliques únicos ÷ (CTR único ÷ 100)
    gasto      = CPC × cliques

Conferido contra o export real: 582 cliques com CTR 0,58193 reconstroem
100.012 impressões, e 544 cliques únicos com CTR único 2,417993 reconstroem
22.498 de alcance — exatamente os dois números que o export de DESEMPENHO da
mesma conta declara. A álgebra fecha.

**CTR e CTR único não são comparáveis.** Têm denominadores diferentes —
impressões contra alcance. É por isso que o CTR único (2,42%) é quatro vezes o
CTR (0,58%) no arquivo de referência, sem que nada esteja errado. Nenhuma
frase do produto pode colocá-los lado a lado como se um fosse a versão limpa
do outro.
"""

from ..parser_rastreamento import RANKINGS, abaixo_da_media

# Métricas que podem ser somadas entre anúncios (§18).
ADITIVAS = ("link_clicks", "unique_link_clicks", "landing_page_views",
            "video_3s_views", "thruplays", "video_25", "video_50", "video_75",
            "video_100")

# Cada razão e o seu denominador. É o mapa que permite consolidar corretamente
# sem escrever a mesma divisão cinco vezes.
#   chave consolidada: (métrica de custo/taxa por linha, denominador, escala)
# `escala` 100 devolve a taxa em unidade de percentual; 1 devolve dinheiro.
RAZOES = {
    "link_ctr": ("link_ctr", "link_clicks", 100.0),
    "unique_link_ctr": ("unique_link_ctr", "unique_link_clicks", 100.0),
    "link_cpc": ("link_cpc", "link_clicks", 1.0),
    "cost_per_landing_page_view": ("cost_per_landing_page_view",
                                   "landing_page_views", 1.0),
    "cost_per_thruplay": ("cost_per_thruplay", "thruplays", 1.0),
}

# Os quatro marcos do vídeo, na ordem em que o espectador os atravessa.
MARCOS = ("video_25", "video_50", "video_75", "video_100")
ROTULO_MARCO = {"video_25": "25%", "video_50": "50%", "video_75": "75%",
                "video_100": "100%"}


def _soma(linhas, campo):
    """Soma o campo, ignorando linha que não tem a métrica.

    Devolve `None` quando NENHUMA linha tem — para o produto distinguir "zero
    ThruPlays" de "este arquivo não fala de vídeo".
    """
    valores = [l[campo] for l in linhas if l.get(campo) is not None]
    return sum(valores) if valores else None


def rotulo(linha, indice):
    """Como este anúncio se chama na tela e no texto.

    Prefere o nome do anúncio, que é o nível em que a frente foi pensada
    (§4); cai para conjunto e campanha quando o export veio mais acima — o
    arquivo de referência é de conjunto, então este caminho é o normal, não a
    exceção.
    """
    for campo in ("ad_name", "adset_name", "campaign_name"):
        if linha.get(campo):
            return linha[campo]
    return f"Anúncio {indice}"


# O nível do export, no singular e no plural. Flexionado porque a tela escreve
# "1 conjunto de anúncios" e "3 conjuntos de anúncios" com o mesmo rótulo, e
# "1 conjuntos" denuncia texto montado por concatenação.
NIVEIS = (("ad_name", ("anúncio", "anúncios")),
          ("adset_name", ("conjunto de anúncios", "conjuntos de anúncios")),
          ("campaign_name", ("campanha", "campanhas")))


def nivel(linhas, quantidade=None):
    """Em que nível o export foi tirado — só para a tela dizer ao operador."""
    for campo, (singular, plural) in NIVEIS:
        if any(l.get(campo) for l in linhas):
            return singular if quantidade == 1 else plural
    return "linha" if quantidade == 1 else "linhas"


def tem_video(linha):
    """Este anúncio é de vídeo?

    Um anúncio de imagem não tem métrica de vídeo nenhuma — não tem zero, tem
    ausência. É a distinção que decide se o bloco de retenção existe para ele
    (§13), e é por isso que o parser transforma "--" em `None` e não em 0.
    """
    campos = MARCOS + ("video_3s_views", "thruplays")
    return any(linha.get(c) is not None for c in campos)


def consolidar(linhas):
    """Os totais do arquivo, com cada razão reconstruída do denominador."""
    anuncios = [_anuncio(l, i) for i, l in enumerate(linhas, 1)]
    total = {campo: _soma(anuncios, campo) for campo in ADITIVAS}

    for chave, (metrica, denominador, escala) in RAZOES.items():
        total[chave] = _razao(anuncios, metrica, denominador, escala)

    # Participação de cada anúncio no todo (§17.2 e §17.3).
    for campo, alvo in (("link_clicks", "share_clicks"),
                        ("landing_page_views", "share_lpv")):
        soma = total.get(campo)
        for a in anuncios:
            a[alvo] = ((a[campo] / soma)
                       if soma and a.get(campo) is not None else None)

    total["taxa_carregamento"] = taxa_carregamento(
        total.get("landing_page_views"), total.get("link_clicks"))
    total["retencao"] = retencao(total)
    total["anuncios"] = anuncios
    total["n_anuncios"] = len(anuncios)
    total["n_video"] = sum(1 for a in anuncios if a["tem_video"])
    total["rankings"] = _rankings(anuncios)
    total["periodo"] = _periodo(linhas)
    total["atribuicao"] = next(
        (l["attribution_setting"] for l in linhas
         if l.get("attribution_setting")), None)
    total["nivel"] = nivel(linhas, len(anuncios))
    return total


def _anuncio(linha, indice):
    """Uma linha do export com o que dela se deriva."""
    a = dict(linha)
    a["rotulo"] = rotulo(linha, indice)
    a["tem_video"] = tem_video(linha)
    a["taxa_carregamento"] = taxa_carregamento(
        linha.get("landing_page_views"), linha.get("link_clicks"))
    a["retencao"] = retencao(linha)
    a["rankings_abaixo"] = [c for c in RANKINGS
                            if abaixo_da_media(linha.get(c))]
    # Impressões e alcance reconstruídos: não vão para a tela nem para o
    # texto (não estão no preset), existem para ponderar as taxas.
    a["_impressoes"] = _denominador(linha.get("link_clicks"),
                                    linha.get("link_ctr"))
    a["_alcance"] = _denominador(linha.get("unique_link_clicks"),
                                 linha.get("unique_link_ctr"))
    return a


def _denominador(numerador, taxa):
    """`numerador ÷ (taxa ÷ 100)` — a definição da taxa, invertida."""
    if numerador is None or not taxa:
        return None
    return numerador / (taxa / 100.0)


def _razao(anuncios, metrica, denominador, escala):
    """`Σ numerador ÷ Σ denominador`, sobre as linhas que têm as duas pontas.

    Média ponderada de verdade, e não média simples: um anúncio com 500
    cliques e outro com 5 não valem o mesmo na taxa da conta.

    Devolve `None` quando nenhuma linha tem as duas pontas — aí a leitura sai
    por anúncio, como manda a §18, em vez de sair um número inventado.
    """
    peso = numerador = 0.0
    for a in anuncios:
        valor, base = a.get(metrica), a.get(denominador)
        if valor is None or not base:
            continue
        if escala == 100.0:
            # Taxa: o denominador real é o que a própria taxa esconde
            # (impressões, alcance). Reconstruí-lo é o que torna a soma
            # legítima.
            base_real = _denominador(base, valor)
            if not base_real:
                continue
            numerador += base
            peso += base_real
        else:
            # Custo: `valor × base` é o gasto daquela linha.
            numerador += valor * base
            peso += base
    if not peso:
        return None
    return (numerador / peso) * escala if escala == 100.0 else numerador / peso


def taxa_carregamento(lpv, cliques):
    """`visualizações ÷ cliques`, em percentual (§10).

    Derivada legítima: numerador e denominador estão os dois no arquivo. Sem
    um dos dois, devolve `None` — não calcular é a resposta certa quando a
    campanha manda para o WhatsApp e página de destino não existe (§11).
    """
    if not cliques or lpv is None:
        return None
    return lpv / cliques * 100.0


def retencao(dados):
    """As quatro taxas de retenção do vídeo (§14), em percentual.

    Cada uma só existe se o marco anterior for maior que zero — é a proteção
    contra divisão por zero, contra célula vazia e contra coluna ausente, e
    ela é a mesma coisa nos três casos porque o parser já normalizou tudo
    para `None`.
    """
    def taxa(de, para):
        base, topo = dados.get(de), dados.get(para)
        if not base or topo is None:
            return None
        return topo / base * 100.0

    return {
        "25_50": taxa("video_25", "video_50"),
        "50_75": taxa("video_50", "video_75"),
        "75_100": taxa("video_75", "video_100"),
        "25_100": taxa("video_25", "video_100"),
    }


def maior_queda(ret):
    """Entre quais marcos a perda proporcional foi maior.

    Devolve `(rótulo do trecho, perda em %)` ou `None`. É a única afirmação
    que o funil de marcos sustenta: o XLSX não tem linha do tempo do vídeo,
    então dizer em que SEGUNDO a queda aconteceu seria invenção (§14).
    """
    trechos = (("25_50", "25% e 50%"), ("50_75", "50% e 75%"),
               ("75_100", "75% e 100%"))
    perdas = [(nome, 100.0 - ret[chave])
              for chave, nome in trechos if ret.get(chave) is not None]
    if not perdas:
        return None
    return max(perdas, key=lambda p: p[1])


def _rankings(anuncios):
    """As classificações do Meta, preservadas como texto (§12).

    Nada é convertido em número: "Acima da média" não é 3, e criar essa
    escala seria inventar uma metodologia que o Meta não publicou.
    """
    resumo = {}
    for campo in RANKINGS:
        valores = [a[campo] for a in anuncios if a.get(campo)]
        resumo[campo] = {
            "valores": valores,
            "abaixo": [a["rotulo"] for a in anuncios
                       if abaixo_da_media(a.get(campo))],
            # Com um anúncio só, o valor dele É o da conta. Com vários, a
            # tela lista por anúncio em vez de escolher um vencedor.
            "unico": valores[0] if len(set(valores)) == 1 and valores else None,
        }
    return resumo


def _periodo(linhas):
    """`(início, fim)` do recorte do relatório, lido das próprias linhas."""
    inicio = fim = None
    for l in linhas:
        inicio = inicio or l.get("report_start")
        fim = fim or l.get("report_end")
        if inicio and fim:
            break
    return inicio, fim
