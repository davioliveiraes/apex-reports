# -*- coding: utf-8 -*-
"""
Gerador de Relatórios PDF — Agência Apex (Tráfego Pago)
========================================================
Camada de renderização: HTML + CSS (template pdf_relatorio.html) convertido
em PDF com WeasyPrint. Layout dark de dashboard em UMA PÁGINA A4:

    cabeçalho (título + badge com o total de resultados)
    → 1 · Funil de Vendas (3 cards: topo / meio / fundo)
    → 2 · Desempenho por Campanha (tabela + donut)   [modo 1 anexo]
      ou 2 · Composição por Unidade (donut)          [modo consolidado]
    → 3 · Análise do Período → rodapé.

O donut é gerado com matplotlib (PNG transparente, determinístico) e
embutido em base64 — nenhuma imagem externa. A interface pública continua
gerar_relatorio(dados, arquivo_saida) com o mesmo dicionário `dados`
montado pelas views (parser e fluxo não mudam).
"""

import base64
import io
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from django.template.loader import render_to_string
from weasyprint import HTML

VERMELHO = "#D8232A"
# Tons de cinza das fatias secundárias (o vermelho é do destaque)
CINZAS = ["#8A8F98", "#5F646D", "#4A4E56", "#383C43", "#2E3138",
          "#A6ABB3", "#71767F", "#555A62"]

LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "img", "logo_apex.png",
)

MAX_LINHAS_CAMPANHA = 5   # acima disso: 4 maiores + "Outras (N)"
MIN_SHARE_FATIA = 3.0     # fatias menores que 3% agrupam em "Outras"


# ----------------------------------------------------------------------
# Helpers de formatação (mesmo padrão brasileiro do parser)
# ----------------------------------------------------------------------
def _fmt_moeda(v):
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_int(v):
    if v is None:
        return "—"
    return f"{int(round(v)):,}".replace(",", ".")


def _parse_int(texto):
    """'1.234' → 1234.0 (formato de _fmt_int); '—' → 0."""
    s = str(texto).replace(".", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_moeda(texto):
    """'R$ 1.234,56' → 1234.56 (formato de _fmt_moeda); '—' → None."""
    s = str(texto).replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _logo_b64():
    if not os.path.exists(LOGO_PATH):
        return ""
    with open(LOGO_PATH, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


# ----------------------------------------------------------------------
# Funil — três cards com leituras curtas
# ----------------------------------------------------------------------
_ROTULOS_CURTOS = {
    "CPM (custo por mil)": "CPM",
    "CTR (taxa de cliques)": "CTR",
    "CPC (custo por clique)": "CPC",
    "Taxa de Conversão (clique → conversa)": "Taxa de Conversão",
}

# Métricas cuja leitura vira a linha de rodapé de cada card
_METRICAS_LEITURA = {
    "topo": ["Frequência", "CPM (custo por mil)"],
    "meio": ["CTR (taxa de cliques)"],
    "fundo": ["Taxa de Conversão (clique → conversa)"],
}


def _cards_funil(funil):
    """Converte as etapas do funil nos três cards do layout (topo/meio/fundo)."""
    cards = []
    for etapa in (funil or {}).get("etapas", []):
        titulo = etapa["titulo"]
        chave = ("topo" if titulo.startswith("Topo")
                 else "meio" if titulo.startswith("Meio") else "fundo")
        linhas, leituras = [], []
        for metrica, valor, leitura in etapa["linhas"]:
            linhas.append({"rotulo": _ROTULOS_CURTOS.get(metrica, metrica),
                           "valor": valor})
            if metrica in _METRICAS_LEITURA[chave] and leitura:
                rotulo = _ROTULOS_CURTOS.get(metrica, metrica)
                leituras.append(f"<b>{rotulo}:</b> {leitura}")
        cards.append({"chave": chave, "titulo": titulo,
                      "linhas": linhas, "leituras": leituras})
    return cards


def _badge_resultados(funil):
    """Total de resultados + indicador (1ª linha do fundo de funil) para o badge."""
    for etapa in (funil or {}).get("etapas", []):
        if etapa["titulo"].startswith("Fundo") and etapa["linhas"]:
            metrica, valor, _ = etapa["linhas"][0]
            return {"valor": valor, "indicador": metrica}
    return None


# ----------------------------------------------------------------------
# Seção 2 — tabela de campanhas / fatias do donut
# ----------------------------------------------------------------------
def _linhas_campanhas(detalhes):
    """Linhas da tabela ordenadas por resultados; acima de 5, agrupa em 'Outras'."""
    linhas = []
    for nome, res_fmt, inv_fmt, _custo_fmt in detalhes.get("linhas", []):
        linhas.append({"nome": nome, "res": _parse_int(res_fmt),
                       "inv": _parse_moeda(inv_fmt) or 0.0})
    linhas.sort(key=lambda l: -l["res"])

    if len(linhas) > MAX_LINHAS_CAMPANHA:
        topo, resto = linhas[:MAX_LINHAS_CAMPANHA - 1], linhas[MAX_LINHAS_CAMPANHA - 1:]
        outras = {"nome": f"Outras ({len(resto)})",
                  "res": sum(l["res"] for l in resto),
                  "inv": sum(l["inv"] for l in resto)}
        linhas = topo + [outras]

    total = sum(l["res"] for l in linhas)
    for l in linhas:
        l["share"] = l["res"] / total * 100 if total else 0
        l["res_fmt"] = _fmt_int(l["res"])
        l["inv_fmt"] = _fmt_moeda(l["inv"])
        l["custo_fmt"] = _fmt_moeda(l["inv"] / l["res"] if l["res"] else None)
    return linhas


def _fatias(itens, destaque_nome=None):
    """Fatias do donut a partir de {nome, valor, share}; <3% agrupa em 'Outras'."""
    itens = sorted([dict(i) for i in itens if (i.get("valor") or 0) > 0],
                   key=lambda i: -i["valor"])
    total = sum(i["valor"] for i in itens)
    if not total or len(itens) < 2:
        return []
    grandes = [i for i in itens if i["valor"] / total * 100 >= MIN_SHARE_FATIA]
    pequenas = [i for i in itens if i["valor"] / total * 100 < MIN_SHARE_FATIA]
    if len(pequenas) == 1:          # sobrando uma só, não vale a pena agrupar
        grandes, pequenas = itens, []
    fatias = [dict(i) for i in grandes]
    if pequenas:
        fatias.append({"nome": f"Outras ({len(pequenas)})",
                       "valor": sum(i["valor"] for i in pequenas)})

    cinza = 0
    for f in fatias:
        f["share"] = f["valor"] / total * 100
        f["texto"] = _fmt_int(f["valor"])
        f["destaque"] = destaque_nome is not None and f["nome"] == destaque_nome
        if f["destaque"]:
            f["cor"] = VERMELHO
        else:
            f["cor"] = CINZAS[cinza % len(CINZAS)]
            cinza += 1
    return fatias


def _donut_png(fatias, centro_valor, centro_rotulo):
    """Donut matplotlib → PNG transparente (base64), rótulos de % nas fatias."""
    fig, ax = plt.subplots(figsize=(3.2, 3.2), dpi=300)
    valores = [f["valor"] for f in fatias]
    cores = [f["cor"] for f in fatias]
    wedges, _textos, autotextos = ax.pie(
        valores, colors=cores, startangle=90, counterclock=False,
        autopct="%1.0f%%", pctdistance=0.78,
        wedgeprops={"width": 0.42, "edgecolor": "#0B0B0D", "linewidth": 2},
    )
    for t in autotextos:
        t.set_color("white")
        t.set_fontsize(11)
        t.set_fontweight("bold")
        t.set_fontfamily("DejaVu Sans")
    ax.text(0, 0.06, centro_valor, ha="center", va="center", color="white",
            fontsize=22, fontweight="bold", fontfamily="DejaVu Sans")
    ax.text(0, -0.22, centro_rotulo, ha="center", va="center", color="#C7CBD1",
            fontsize=9, fontfamily="DejaVu Sans")
    ax.set_aspect("equal")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight",
                pad_inches=0.02)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _secao_campanhas(dados):
    """Seção 2 do modo individual: tabela + donut do share por campanha."""
    detalhes = dados.get("detalhes_campanha")
    if not detalhes:
        return None, None
    linhas = _linhas_campanhas(detalhes)

    com_res = [l for l in linhas if l["res"] > 0]
    destaque = min(com_res, key=lambda l: l["inv"] / l["res"])["nome"] \
        if com_res else None
    for l in linhas:
        l["destaque"] = l["nome"] == destaque

    fatias = _fatias(
        [{"nome": l["nome"], "valor": l["res"]} for l in linhas], destaque)
    donut = _montar_donut(fatias, dados, "2 · Desempenho por Campanha")
    return linhas, donut


def _secao_composicao(dados):
    """Seção 2 do modo consolidado: donut com a participação de cada unidade."""
    itens = (dados.get("composicao") or {}).get("itens") or []
    com_res = [i for i in itens if (i.get("valor") or 0) > 0]
    destaque = max(com_res, key=lambda i: i["valor"])["nome"] if com_res else None
    fatias = _fatias(itens, destaque)
    return _montar_donut(fatias, dados, "2 · Composição por Unidade")


def _montar_donut(fatias, dados, titulo_secao):
    if not fatias:
        return None
    badge = _badge_resultados(dados.get("funil")) or {}
    centro_valor = badge.get("valor", _fmt_int(sum(f["valor"] for f in fatias)))
    indicador = badge.get("indicador", "resultados")
    return {
        "titulo_secao": titulo_secao,
        "png_b64": _donut_png(fatias, centro_valor, "resultados"),
        "fatias": fatias,
        "total_texto": f"Total de {centro_valor} resultados ({indicador})",
    }


# ----------------------------------------------------------------------
# Função principal
# ----------------------------------------------------------------------
def gerar_relatorio(dados: dict, arquivo_saida="relatorio_apex.pdf"):
    """Renderiza o template HTML com os `dados` das views e grava o PDF
    (1 página A4) em `arquivo_saida` — caminho ou objeto file-like."""
    modo_grupo = bool(dados.get("unidades"))

    if modo_grupo:
        tabela, donut = None, _secao_composicao(dados)
    else:
        tabela, donut = _secao_campanhas(dados)

    rodape = dados.get(
        "rodape",
        "Relatório gerado a partir de dados exportados do Meta Ads Manager.",
    )
    legenda_funil = (dados.get("funil") or {}).get("legenda")
    if modo_grupo and legenda_funil:
        rodape += " " + legenda_funil

    contexto = {
        "titulo": dados.get("titulo", "Relatório de Tráfego Pago"),
        "cliente": dados.get("cliente", ""),
        "periodo": dados.get("periodo", ""),
        "subtitulo_extra": dados.get("subtitulo_extra", ""),
        "logo_b64": _logo_b64(),
        "badge": _badge_resultados(dados.get("funil")),
        "cards": _cards_funil(dados.get("funil")),
        "modo_grupo": modo_grupo,
        "tabela": tabela,
        "donut": donut,
        "analise": dados.get("analise") or [],
        "rodape": rodape,
    }
    html = render_to_string("relatorios/pdf_relatorio.html", contexto)
    HTML(string=html).write_pdf(arquivo_saida)
    if isinstance(arquivo_saida, str):
        print(f"PDF gerado: {arquivo_saida}")
