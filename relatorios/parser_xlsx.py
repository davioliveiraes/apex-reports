# -*- coding: utf-8 -*-
"""
Leitor do export .xlsx do Meta Ads Manager.

Identifica as colunas por palavras-chave (funciona com export em PT ou EN),
consolida os KPIs do período, monta o funil de vendas e os dados dos gráficos
(funil visual e share de resultados por campanha/unidade).
"""

import unicodedata
from datetime import date, datetime

from openpyxl import load_workbook

from . import benchmarks, indicadores


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _norm(texto):
    """minúsculas, sem acento — para casar nomes de coluna."""
    if texto is None:
        return ""
    texto = str(texto).lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace("\xa0", "").strip()
    # formato brasileiro: 1.234,56
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _fmt_moeda(v):
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_int(v):
    if v is None:
        return "—"
    return f"{int(round(v)):,}".replace(",", ".")


def _fmt_dec(v, casas=2):
    if v is None:
        return "—"
    return f"{v:.{casas}f}".replace(".", ",")


def _fmt_data(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%d/%m/%Y")
    if v:
        s = str(v).strip()
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return s
    return None


# Mapeamento coluna → (palavras-chave alternativas, termos proibidos no nome)
_COLUNAS = {
    "campanha":    ([["nome da campanha"], ["campaign name"]], []),
    "conjunto":    ([["nome do conjunto"], ["ad set name"]], []),
    "anuncio":     ([["nome do anuncio"], ["ad name"]], []),
    "investimento": ([["valor usado"], ["amount spent"]], []),
    "resultados":  ([["resultados"], ["results"]], ["custo", "cost", "indicador", "indicator", "tipo", "type", "taxa", "rate"]),
    "custo_resultado": ([["custo por resultado"], ["cost per result"]], []),
    "indicador":   ([["indicador de resultado"], ["result indicator"], ["tipo de resultado"], ["result type"]], []),
    "impressoes":  ([["impressoes"], ["impressions"]], ["cpm", "custo", "cost"]),
    "cliques":     ([["cliques no link"], ["link clicks"], ["cliques", "link"]],
                    ["unicos", "unique", "ctr", "custo", "cost", "taxa", "rate"]),
    "alcance":     ([["alcance"], ["reach"]], ["custo", "cost"]),
    "frequencia":  ([["frequencia"], ["frequency"]], []),
    "cpm":         ([["cpm"]], []),
    # Status de veiculação DA CAMPANHA — os termos proibidos afastam as colunas
    # equivalentes de conjunto e de anúncio, que o export também traz.
    "veiculacao":  ([["veiculacao"], ["delivery"]],
                    ["conjunto", "ad set", "anuncio", "ad delivery"]),
    "inicio":      ([["inicio dos relatorios"], ["reporting starts"]], []),
    "termino":     ([["termino dos relatorios"], ["encerramento dos relatorios"], ["reporting ends"]], []),
    "orcamento":   ([["orcamento"], ["budget"]], []),
}


# ----------------------------------------------------------------------
# Veiculação da campanha (coluna "Veiculação da campanha" / "Campaign Delivery")
# ----------------------------------------------------------------------
VEICULACAO_TODAS = "todas"
VEICULACAO_ATIVAS = "ativas"
VEICULACAO_INATIVAS = "inativas"

VEICULACOES = [
    (VEICULACAO_TODAS, "Todas as campanhas"),
    (VEICULACAO_ATIVAS, "Somente campanhas ativas"),
    (VEICULACAO_INATIVAS, "Somente campanhas inativas"),
]

# O export usa os valores do Meta mesmo com o cabeçalho em português
# ("active"/"inactive"); as variantes traduzidas aparecem em exports antigos.
# ATENÇÃO à ordem: "inactive" contém "active", então o desligado é testado
# primeiro — inverter a ordem classificaria toda campanha inativa como ativa.
_TERMOS_INATIVA = ("inactive", "inativ", "paus", "desativ", "archiv", "arquiv",
                   "delet", "exclu", "conclu", "complet", "encerr", "rejeit",
                   "reject", "not delivering", "nao veiculando")
_TERMOS_ATIVA = ("active", "ativ", "delivering", "veiculando", "learning",
                 "aprendiz")


def campanha_ativa(valor):
    """True (veiculando), False (parada) ou None quando não dá para afirmar —
    célula vazia ou status que não casa com nenhum termo conhecido."""
    v = _norm(valor).replace("_", " ")
    if not v:
        return None
    if any(t in v for t in _TERMOS_INATIVA):
        return False
    if any(t in v for t in _TERMOS_ATIVA):
        return True
    return None


def filtrar_veiculacao(registros, veiculacao):
    """Linhas que atendem ao filtro. Status desconhecido fica de fora dos
    filtros específicos — só entra em "todas", onde nada é descartado."""
    if veiculacao == VEICULACAO_TODAS:
        return list(registros)
    ativa = veiculacao == VEICULACAO_ATIVAS
    return [r for r in registros if campanha_ativa(r.get("veiculacao")) is ativa]


def _mapear_colunas(header):
    """Retorna {chave: índice}. Prioriza match exato; depois 'contém', respeitando exclusões."""
    normalizados = [_norm(h) for h in header]
    mapa = {}
    for chave, (alternativas, proibidos) in _COLUNAS.items():
        # 1º passe: nome exatamente igual a uma keyword
        for i, nome in enumerate(normalizados):
            if any(len(alt) == 1 and nome == alt[0] for alt in alternativas):
                mapa[chave] = i
                break
        if chave in mapa:
            continue
        # 2º passe: contém todas as keywords e nenhum termo proibido
        for i, nome in enumerate(normalizados):
            if not nome:
                continue
            if any(p in nome for p in proibidos):
                continue
            if any(all(kw in nome for kw in alt) for alt in alternativas):
                mapa[chave] = i
                break
    return mapa


# ----------------------------------------------------------------------
# Leitura principal
# ----------------------------------------------------------------------
def ler_export_meta(arquivo, veiculacao=VEICULACAO_TODAS, conta=None):
    """
    Lê o .xlsx exportado do Meta Ads Manager e devolve um dicionário com:
    kpis, metricas_extra, funil, gráficos (funil visual e share por campanha),
    detalhes_campanha, período detectado e a análise sugerida.
    Levanta ValueError com mensagem amigável se o arquivo não for reconhecido.

    `veiculacao` restringe as linhas ao status da campanha (ver VEICULACOES).
    """
    registros, mapa = ler_registros(arquivo)
    return consolidar(filtrar_veiculacao(registros, veiculacao), mapa, conta)


def ler_registros(arquivo):
    """
    Linhas de dados do export + mapa de colunas reconhecidas, sem consolidar.

    Separado de `ler_export_meta` para que um mesmo arquivo possa ser
    consolidado mais de uma vez — é o que permite trocar o filtro de veiculação
    na revisão sem pedir o anexo de novo.
    """
    wb = load_workbook(arquivo, data_only=True, read_only=True)
    ws = wb.active

    linhas = list(ws.iter_rows(values_only=True))
    wb.close()
    if not linhas:
        raise ValueError("A planilha está vazia.")

    # Localiza a linha de cabeçalho (nem sempre é a primeira)
    header_idx, mapa = None, {}
    for i, linha in enumerate(linhas[:10]):
        m = _mapear_colunas(linha)
        if "investimento" in m or "resultados" in m or "impressoes" in m:
            header_idx, mapa = i, m
            break
    if header_idx is None:
        raise ValueError(
            "Não foi possível reconhecer as colunas do export do Meta Ads Manager. "
            "Confira se o arquivo é o .xlsx exportado direto do Gerenciador de Anúncios."
        )

    registros = []
    for linha in linhas[header_idx + 1:]:
        if linha is None or all(c is None or str(c).strip() == "" for c in linha):
            continue
        reg = {}
        for chave, idx in mapa.items():
            reg[chave] = linha[idx] if idx < len(linha) else None
        # Ignora linhas de total do próprio export
        nome_ref = _norm(reg.get("anuncio") or reg.get("conjunto") or reg.get("campanha"))
        if nome_ref.startswith(("total", "resultados de")):
            continue
        registros.append(reg)

    if not registros:
        raise ValueError("Nenhuma linha de dados encontrada na planilha.")

    return registros, mapa


def consolidar(registros, mapa, conta=None):
    """`conta` só identifica a origem no log de indicador não mapeado."""
    # ---- Totais do período ----
    investimento = sum(v for v in (_to_float(r.get("investimento")) for r in registros) if v) or 0.0
    resultados = sum(v for v in (_to_float(r.get("resultados")) for r in registros) if v) or 0.0
    impressoes = sum(v for v in (_to_float(r.get("impressoes")) for r in registros) if v) or 0.0
    alcance = sum(v for v in (_to_float(r.get("alcance")) for r in registros) if v) or 0.0
    cliques = sum(v for v in (_to_float(r.get("cliques")) for r in registros) if v) or 0.0

    custo_resultado = investimento / resultados if resultados else None
    frequencia = impressoes / alcance if alcance else None
    cpm = investimento / impressoes * 1000 if impressoes else None
    # Métricas de meio/fundo de funil — calculadas quando o export não as traz
    ctr = cliques / impressoes * 100 if cliques and impressoes else None
    cpc = investimento / cliques if cliques else None
    taxa_conversao = resultados / cliques * 100 if cliques and resultados else None

    # O indicador da conta é o de maior soma de resultados, não o da primeira
    # linha: uma planilha com campanhas de objetivos diferentes rotularia o
    # relatório pela campanha que por acaso abre o arquivo.
    indicador = indicadores.dominante(registros, para_numero=_to_float)
    indicador_curto = indicadores.rotulo(indicador, conta)

    inicio = next((r.get("inicio") for r in registros if r.get("inicio")), None)
    termino = next((r.get("termino") for r in registros if r.get("termino")), None)
    periodo = ""
    if inicio and termino:
        periodo = f"{_fmt_data(inicio)} a {_fmt_data(termino)}"

    dados = {
        "periodo": periodo,
        # Colunas efetivamente reconhecidas no export — permite distinguir
        # "métrica ausente na planilha" de "métrica igual a zero".
        "_colunas": sorted(mapa),
        "kpis": [
            {"label": "Investimento", "valor": _fmt_moeda(investimento)},
            {"label": indicador_curto, "valor": _fmt_int(resultados)},
            {"label": "Custo / Resultado", "valor": _fmt_moeda(custo_resultado)},
        ],
        "metricas_extra": {
            "Impressões": _fmt_int(impressoes),
            "Alcance": _fmt_int(alcance),
            "Frequência": _fmt_dec(frequencia),
            "CPM": _fmt_moeda(cpm),
        },
        "_num": {  # valores numéricos para a análise automática e consolidação
            "investimento": investimento, "resultados": resultados,
            "custo_resultado": custo_resultado, "cpm": cpm, "frequencia": frequencia,
            "impressoes": impressoes, "alcance": alcance,
            "cliques": cliques, "ctr": ctr, "cpc": cpc, "taxa_conversao": taxa_conversao,
        },
    }

    # ---- Funil de vendas (topo / meio / fundo) ----
    dados["funil"] = {"etapas": _montar_funil(dados["_num"], indicador)}
    dados["indicador"] = indicador

    # ---- Funil visual (gráfico de barras decrescentes) ----
    dados["grafico_funil"] = _dados_grafico_funil(dados["_num"], indicador)

    # ---- Desempenho por campanha ----
    campanhas = {}
    for r in registros:
        nome = str(r.get("campanha") or "").strip()
        if not nome:
            continue
        c = campanhas.setdefault(nome, {"res": 0.0, "inv": 0.0, "imp": 0.0, "alc": 0.0})
        c["res"] += _to_float(r.get("resultados")) or 0
        c["inv"] += _to_float(r.get("investimento")) or 0
        c["imp"] += _to_float(r.get("impressoes")) or 0
        c["alc"] += _to_float(r.get("alcance")) or 0
    if campanhas:
        # Sem coluna de Status: a veiculação serve para FILTRAR as linhas
        # (ver filtrar_veiculacao), mas é decisão interna da agência e não
        # aparece no relatório do cliente.
        dados["detalhes_campanha"] = {
            "titulo": "Desempenho por Campanha",
            "header": ["Campanha", "Resultados", "Investimento", "Custo/Resultado"],
            "linhas": [
                [nome, _fmt_int(c["res"]), _fmt_moeda(c["inv"]),
                 _fmt_moeda(c["inv"] / c["res"] if c["res"] else None)]
                for nome, c in campanhas.items()
            ],
            "legenda": f"Indicador de resultado: {indicador_curto}." if indicador else None,
        }
        # Rosca com o share de resultados por campanha (melhor = menor custo, em verde)
        dados["grafico_campanhas"] = _dados_grafico_campanhas(campanhas, resultados)

    # ---- Análise do Período sugerida (editável na revisão) ----
    dados["analise_sugerida"] = _analise_periodo(dados["_num"], campanhas, indicador)

    return dados


def _dados_grafico_funil(n, indicador):
    """Estágios do funil visual: Alcance → Cliques → Conversas (só os presentes)."""
    indicador_curto = indicadores.rotulo(indicador, avisar=False)
    estagios = []
    if n.get("alcance"):
        estagios.append({"rotulo": "Alcance", "valor": n["alcance"],
                         "texto": f"{_fmt_int(n['alcance'])} pessoas"})
    elif n.get("impressoes"):
        estagios.append({"rotulo": "Impressões", "valor": n["impressoes"],
                         "texto": f"{_fmt_int(n['impressoes'])} visualizações"})
    if n.get("cliques"):
        estagios.append({"rotulo": "Cliques no Link", "valor": n["cliques"],
                         "texto": f"{_fmt_int(n['cliques'])} cliques"})
    if n.get("resultados"):
        estagios.append({"rotulo": indicador_curto, "valor": n["resultados"],
                         "texto": _fmt_int(n["resultados"])})
    return estagios if len(estagios) >= 2 else []


def _dados_grafico_campanhas(campanhas, resultados_total):
    """Itens da rosca de share por campanha; a de menor custo é o destaque."""
    com_res = [(nome, c) for nome, c in campanhas.items() if c.get("res")]
    if len(com_res) < 2 or not resultados_total:
        return []
    nome_melhor = min(com_res, key=lambda kv: kv[1]["inv"] / kv[1]["res"])[0]
    itens = sorted(com_res, key=lambda kv: -kv[1]["res"])
    return [{
        "nome": nome,
        "valor": c["res"],
        "texto": _fmt_int(c["res"]),
        "share": c["res"] / resultados_total * 100,
        "melhor": nome == nome_melhor,
    } for nome, c in itens]


def _montar_funil(n, indicador):
    """Etapas do funil (topo/meio/fundo) a partir dos totais numéricos `n`."""
    eh_conversa = indicadores.eh_conversa(indicador)
    indicador_curto = indicadores.rotulo(indicador, avisar=False)
    rotulo_custo = "Custo por Conversa (CPA)" if eh_conversa else "Custo por Resultado (CPA)"
    av = benchmarks.avaliar_metricas(n)

    topo = [["Investimento Total", _fmt_moeda(n["investimento"]),
             "Verba total aplicada em mídia no período."]]
    if n["alcance"]:
        topo.append(["Alcance", f"{_fmt_int(n['alcance'])} pessoas",
                     "Pessoas únicas alcançadas pelos anúncios."])
    if n["impressoes"]:
        topo.append(["Impressões", f"{_fmt_int(n['impressoes'])} visualizações",
                     "Total de vezes que os anúncios foram exibidos."])
    if n["frequencia"]:
        topo.append(["Frequência", _fmt_dec(n["frequencia"]),
                     _leitura_metrica("frequencia", av)])
    if n["cpm"]:
        topo.append(["CPM (custo por mil)", _fmt_moeda(n["cpm"]),
                     _leitura_metrica("cpm", av)])

    meio = []
    if n["cliques"]:
        meio.append(["Cliques no Link", f"{_fmt_int(n['cliques'])} cliques",
                     "Cliques direcionados ao destino (WhatsApp / página)."])
        if n["ctr"] is not None:
            meio.append(["CTR (taxa de cliques)", f"{_fmt_dec(n['ctr'])}%",
                         _leitura_metrica("ctr", av)])
        if n["cpc"] is not None:
            meio.append(["CPC (custo por clique)", _fmt_moeda(n["cpc"]),
                         _leitura_metrica("cpc", av)])

    fundo = []
    if n["resultados"]:
        fundo.append([indicador_curto, _fmt_int(n["resultados"]),
                      "Total de conversões registradas no período."])
    if n["custo_resultado"] is not None:
        fundo.append([rotulo_custo, _fmt_moeda(n["custo_resultado"]),
                      "Quanto custou, em média, cada conversão."])
    if n["taxa_conversao"] is not None:
        fundo.append(["Taxa de Conversão (clique → conversa)",
                      f"{_fmt_dec(n['taxa_conversao'])}%",
                      _leitura_metrica("taxa_conversao", av)])

    return [
        {"titulo": t, "linhas": l} for t, l in [
            ("Topo de Funil — Atração", topo),
            ("Meio de Funil — Interesse e Clique", meio),
            ("Fundo de Funil — Conversão", fundo),
        ] if l
    ]


# ----------------------------------------------------------------------
# Consolidação multi-contas (grupo de unidades)
# ----------------------------------------------------------------------
def consolidar_grupo(unidades):
    """
    Consolida os dados de 2+ contas/unidades num relatório único de grupo.

    `unidades`: lista de {"nome": str, "dados": dict retornado por ler_export_meta}
    (o dict de cada unidade precisa ainda conter a chave "_num").

    Regra de agregação: soma investimento/impressões/alcance/cliques/resultados
    e recalcula as taxas sobre os totais — nunca média simples de percentuais.
    """
    us = []
    for u in unidades:
        d = u["dados"]
        us.append({
            "nome": u["nome"],
            "num": d["_num"],
            "funil": d.get("funil"),
            "kpis": d.get("kpis", []),
            "indicador": d.get("indicador", ""),
            "periodo": d.get("periodo", ""),
        })

    n = _totais_grupo(us)
    # Mesma regra da conta individual, um nível acima: o indicador do grupo é
    # o das unidades que respondem pela maior parte dos resultados.
    indicador = indicadores.dominante(
        [{"indicador": u["indicador"], "resultados": u["num"].get("resultados")}
         for u in us])
    eh_conversa = indicadores.eh_conversa(indicador)
    indicador_curto = indicadores.rotulo(indicador, avisar=False)

    funil = {"etapas": _montar_funil(n, indicador)}
    if n["alcance"]:
        funil["legenda"] = ("Alcance geral: soma das unidades — pode haver "
                            "sobreposição de audiência entre as contas.")

    dados = {
        "modo": "grupo",
        "periodo": _periodo_grupo(us),
        "kpis": [
            {"label": "Investimento", "valor": _fmt_moeda(n["investimento"])},
            {"label": indicador_curto, "valor": _fmt_int(n["resultados"])},
            {"label": "Custo / Resultado", "valor": _fmt_moeda(n["custo_resultado"])},
        ],
        "funil": funil,
        "grafico_funil": _dados_grafico_funil(n, indicador),
        "composicao": montar_composicao(us),
        "unidades": us,
    }
    # Aviso de indicador divergente: só na tela de revisão — não vai ao PDF.
    aviso = _aviso_indicador(us)
    if aviso:
        dados["aviso_indicador"] = aviso
    dados["analise_sugerida"] = _analise_grupo(us, n, eh_conversa)
    return dados


def _totais_grupo(us):
    """Totais do grupo somando as unidades; taxas recalculadas sobre os totais."""
    def soma(chave):
        return sum(v for v in (u["num"].get(chave) for u in us) if v) or 0.0

    investimento = soma("investimento")
    resultados = soma("resultados")
    impressoes = soma("impressoes")
    alcance = soma("alcance")
    cliques = soma("cliques")
    return {
        "investimento": investimento, "resultados": resultados,
        "impressoes": impressoes, "alcance": alcance, "cliques": cliques,
        "custo_resultado": investimento / resultados if resultados else None,
        "frequencia": impressoes / alcance if alcance else None,
        "cpm": investimento / impressoes * 1000 if impressoes else None,
        "ctr": cliques / impressoes * 100 if cliques and impressoes else None,
        "cpc": investimento / cliques if cliques else None,
        "taxa_conversao": resultados / cliques * 100 if cliques and resultados else None,
    }


def montar_composicao(unidades):
    """
    Participação de cada unidade no total de resultados do grupo — dados do
    gráfico de composição (barras horizontais). Público para permitir remontar
    com os nomes de unidade editados na revisão.
    """
    total = sum(u["num"].get("resultados") or 0 for u in unidades)
    ordenadas = sorted(unidades, key=lambda u: -(u["num"].get("resultados") or 0))
    itens = [{
        "nome": u["nome"],
        "valor": u["num"].get("resultados") or 0,
        "texto": _fmt_int(u["num"].get("resultados") or 0),
        "share": (u["num"].get("resultados") or 0) / total * 100 if total else 0,
    } for u in ordenadas]
    return {"titulo": "Participação de Cada Unidade nos Resultados", "itens": itens}


def _aviso_indicador(us):
    """Texto de aviso quando os anexos não usam o mesmo indicador de resultado."""
    grupos = {}
    for u in us:
        if u.get("indicador"):
            # Agrupado pelo rótulo legível: o aviso é para o operador decidir,
            # não para ele decifrar "actions:post_engagement".
            grupos.setdefault(indicadores.rotulo(u["indicador"], avisar=False),
                              []).append(u["nome"])
    if len(grupos) <= 1:
        return None
    partes = "; ".join(f'"{ind}" ({", ".join(nomes)})' for ind, nomes in grupos.items())
    return (
        "Os anexos não usam o mesmo indicador de resultado — "
        f"{partes}. Os totais do grupo somam métricas diferentes; "
        "confira se a comparação faz sentido antes de gerar o PDF."
    )


def _periodo_grupo(us):
    """Período do grupo: do menor início ao maior fim entre as unidades."""
    datas = []
    for u in us:
        try:
            ini, fim = (datetime.strptime(x.strip(), "%d/%m/%Y")
                        for x in (u.get("periodo") or "").split(" a "))
            datas.append((ini, fim))
        except ValueError:
            continue
    if datas:
        ini = min(d[0] for d in datas)
        fim = max(d[1] for d in datas)
        return f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
    return next((u["periodo"] for u in us if u.get("periodo")), "")


def _analise_grupo(us, n, eh_conversa):
    """
    Análise do Período — Geral: unidades citadas só por números, resumo com
    os totais somados (benchmarks sobre as taxas recalculadas) e continuidade.
    """
    rotulo = "conversa" if eh_conversa else "resultado"
    av = benchmarks.avaliar_metricas(n)

    itens = {u["nome"]: {"res": u["num"].get("resultados") or 0,
                         "inv": u["num"].get("investimento") or 0}
             for u in us}
    frases = _frases_mencoes(itens, n["resultados"], rotulo, sujeito="unidade")
    frases.append(_frase_resumo(n, rotulo, av,
                                sujeito_plural=f"{len(us)} unidades"))
    return " ".join(frases) + "\n\n" + " ".join(_frases_continuidade(av, n, rotulo))


# ----------------------------------------------------------------------
# Leituras automáticas das métricas do funil (1 linha por card no PDF)
# ----------------------------------------------------------------------
# Enquadramento sempre positivo ou neutro: a classificação de benchmark é
# interna; para o cliente, a agência aparece em ação contínua.
_LEITURAS_CARD = {
    "frequencia": {
        benchmarks.ABAIXO: "Frequência saudável — público longe da saturação.",
        benchmarks.DENTRO: "Frequência saudável — público longe da saturação.",
        benchmarks.ACIMA: ("Boa presença junto ao público — estamos ampliando "
                           "as audiências para manter a entrega eficiente."),
    },
    "cpm": {
        benchmarks.ABAIXO: ("Custo de entrega competitivo — bom momento para "
                            "ganhar volume."),
        benchmarks.DENTRO: "Custo de entrega competitivo.",
        benchmarks.ACIMA: ("Público concorrido — otimizamos a entrega para "
                           "manter o custo sob controle."),
    },
    "ctr": {
        benchmarks.ABAIXO: ("Estamos renovando os criativos para elevar a "
                            "taxa de cliques."),
        benchmarks.DENTRO: "Taxa de cliques dentro da faixa esperada.",
        benchmarks.ACIMA: "Anúncios com ótima atratividade para o público.",
    },
    "cpc": {
        benchmarks.ABAIXO: "Custo por clique competitivo.",
        benchmarks.DENTRO: "Custo por clique dentro da faixa esperada.",
        benchmarks.ACIMA: ("Estamos refinando públicos e entrega para reduzir "
                           "o custo por clique."),
    },
    "taxa_conversao": {
        benchmarks.ABAIXO: ("Estamos alinhando o fluxo de atendimento para "
                            "aproveitar melhor cada clique."),
        benchmarks.DENTRO: "Boa eficiência do fluxo de atendimento.",
        benchmarks.ACIMA: "Boa eficiência do fluxo de atendimento.",
        benchmarks.EXCELENTE: ("Excelente eficiência — parte das conversas "
                               "chega direto do anúncio, sem depender do clique."),
    },
}


def _leitura_metrica(metrica, avaliacao):
    """Leitura curta da métrica conforme a classificação de benchmark."""
    classe = avaliacao.get(metrica)
    return _LEITURAS_CARD[metrica].get(classe, "") if classe else ""


# ----------------------------------------------------------------------
# Análise do Período sugerida (3–5 frases, editável na revisão)
# ----------------------------------------------------------------------
# Frases de continuidade ("passos adiante"): tom de rotina, escolhidas pela
# classificação de benchmark. Duas formulações por tema para não repetir a
# mesma frase em relatórios consecutivos (a escolha é determinística a
# partir dos números do período).
_CONTINUIDADE = {
    "criativos": [
        "Para as próximas semanas, seguimos com a renovação de criativos para "
        "elevar a taxa de cliques.",
        "Na sequência, entram novos criativos em teste para ampliar o interesse "
        "nos anúncios.",
    ],
    "entrega": [
        "Seguimos otimizando públicos e entrega para melhorar o custo por {rotulo}.",
        "O próximo passo é refinar as audiências para deixar a entrega ainda "
        "mais eficiente.",
    ],
    "atendimento": [
        "Vamos alinhar com vocês o fluxo de atendimento para converter mais "
        "cliques em {rotulo}s.",
        "Na sequência, ajustamos em conjunto o fluxo de atendimento para "
        "aproveitar melhor cada clique.",
    ],
    "ritmo": [
        "O plano é sustentar o ritmo atual, com testes incrementais para seguir "
        "ganhando eficiência.",
        "Seguimos no mesmo ritmo, testando variações pontuais para continuar "
        "evoluindo os números.",
    ],
}


def _frases_continuidade(av, n, rotulo):
    """1–2 frases de fechamento, conforme a classificação das métricas."""
    temas = []
    if av.get("ctr") == benchmarks.ABAIXO:
        temas.append("criativos")
    if av.get("taxa_conversao") == benchmarks.ABAIXO:
        temas.append("atendimento")
    if benchmarks.ACIMA in (av.get("cpc"), av.get("cpm")):
        temas.append("entrega")
    if not temas:
        temas = ["ritmo"]
    semente = int((n.get("investimento") or 0) * 100 + (n.get("resultados") or 0))
    return [_CONTINUIDADE[t][semente % len(_CONTINUIDADE[t])].format(rotulo=rotulo)
            for t in temas[:2]]


def _frases_mencoes(itens, total_resultados, rotulo, sujeito="campanha"):
    """
    Menções às campanhas/unidades — exclusivamente números (volume, share,
    investimento, custo por resultado). Sem destaque forçado: o líder só é
    citado quando o share supera com folga a divisão igual entre os itens.
    """
    com_res = [(nome, c) for nome, c in itens.items() if c.get("res")]
    if not com_res or not total_resultados:
        return []
    if len(com_res) == 1:
        nome, c = com_res[0]
        return [f"A {sujeito} <b>{nome}</b> respondeu pelas {_fmt_int(c['res'])} "
                f"{rotulo}s do período, com investimento de {_fmt_moeda(c['inv'])} "
                f"e custo de <b>{_fmt_moeda(c['inv'] / c['res'])}</b> por {rotulo}."]

    nome, c = max(com_res, key=lambda kv: kv[1]["res"])
    share = c["res"] / total_resultados * 100
    if share >= 100 / len(com_res) + 10:
        return [f"A {sujeito} <b>{nome}</b> concentrou {_fmt_int(c['res'])} "
                f"{rotulo}s ({share:.0f}% do total), com investimento de "
                f"{_fmt_moeda(c['inv'])} e custo de "
                f"<b>{_fmt_moeda(c['inv'] / c['res'])}</b> por {rotulo}."]
    custos = [cc["inv"] / cc["res"] for _, cc in com_res]
    faixa = (f"em torno de {_fmt_moeda(min(custos))}"
             if _fmt_moeda(min(custos)) == _fmt_moeda(max(custos))
             else f"entre {_fmt_moeda(min(custos))} e {_fmt_moeda(max(custos))}")
    return [f"As {len(com_res)} {sujeito}s contribuíram de forma equilibrada "
            f"para o total, com custo por {rotulo} {faixa}."]


def _clausula_eficiencia(av):
    """Complemento do resumo geral, derivado da classificação de benchmark."""
    cpm_ok = av.get("cpm") in (benchmarks.ABAIXO, benchmarks.DENTRO)
    freq_ok = av.get("frequencia") in (benchmarks.ABAIXO, benchmarks.DENTRO)
    if cpm_ok and freq_ok:
        return (", com custo de entrega competitivo e público ainda longe "
                "da saturação")
    if cpm_ok:
        return ", com custo de entrega competitivo"
    if av.get("cpm") == benchmarks.ACIMA:
        return ", mesmo com o público mais concorrido no período"
    return ""


def _frase_resumo(n, rotulo, av, sujeito_plural=None):
    """Resumo geral do período: totais + leitura simples de eficiência."""
    quem = f"Somando as {sujeito_plural}, o" if sujeito_plural else "No período, o"
    if not n["resultados"]:
        return (f"{quem} investimento de <b>{_fmt_moeda(n['investimento'])}</b> "
                f"alcançou {_fmt_int(n['alcance'])} pessoas com os anúncios.")
    return (f"{quem} investimento de <b>{_fmt_moeda(n['investimento'])}</b> "
            f"gerou <b>{_fmt_int(n['resultados'])}</b> {rotulo}s, a um custo "
            f"médio de <b>{_fmt_moeda(n['custo_resultado'])}</b> por {rotulo}"
            f"{_clausula_eficiencia(av)}.")


def _analise_periodo(n, campanhas, indicador):
    """Análise do Período (1 conta): menções por números, resumo e continuidade."""
    rotulo = "conversa" if indicadores.eh_conversa(indicador) else "resultado"
    av = benchmarks.avaliar_metricas(n)

    frases = _frases_mencoes(campanhas, n["resultados"], rotulo)
    frases.append(_frase_resumo(n, rotulo, av))
    return " ".join(frases) + "\n\n" + " ".join(_frases_continuidade(av, n, rotulo))
