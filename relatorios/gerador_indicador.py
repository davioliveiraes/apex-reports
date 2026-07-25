# -*- coding: utf-8 -*-
"""
Gerador do PDF de Indicador Único (Modo 4) — Agência Apex.

Compara UMA métrica escolhida entre 2 e 20 contas: tabela ordenada pela
métrica, destaque na melhor unidade e total do grupo calculado conforme a
regra de agregação do registro (soma para métricas aditivas, recálculo sobre
os brutos somados para métricas de razão).

A métrica é sempre lida de `metricas.METRICS_REGISTRY` — este módulo não
conhece nenhuma métrica pelo nome. O parser roda inteiro em cada anexo (não há
parser paralelo); aqui só se filtra a métrica pedida para exibição, mantendo
os demais valores disponíveis para os recálculos do total.
"""

import base64
import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from django.template.loader import render_to_string
from weasyprint import HTML

from . import metricas
from .gerador_pdf import VERMELHO, _logo_b64

VERDE = "#34D399"   # destaque da melhor unidade (mesmo tom de `tr.melhor` na UI)


def _linhas(chave, contas):
    """Uma linha por conta, na ordem de envio, com o valor da métrica.

    Conta sem a coluna necessária no export (ou sem valor calculável) entra
    com valor None: aparece como "—", fica fora do total e é listada no
    rodapé como dado indisponível."""
    linhas = []
    for conta in contas:
        dados = conta["dados"]
        num = dados.get("_num") or {}
        valor = (metricas.valor_conta(chave, num)
                 if metricas.disponivel(chave, dados.get("_colunas")) else None)
        linhas.append({"conta": conta["nome"], "valor": valor, "num": num})
    return linhas


def _aviso_objetivo(chave, contas):
    """Aviso quando a métrica depende do objetivo e os anexos usam indicadores
    de resultado diferentes — mesma leitura do aviso do modo consolidado."""
    if chave not in metricas.SENSIVEIS_AO_OBJETIVO:
        return None
    grupos = {}
    for conta in contas:
        indicador = str(conta["dados"].get("indicador") or "").strip()
        if indicador:
            grupos.setdefault(indicador, []).append(conta["nome"])
    if len(grupos) <= 1:
        return None
    partes = "; ".join(f'"{ind}" ({", ".join(nomes)})' for ind, nomes in grupos.items())
    return (
        f"As contas não usam o mesmo indicador de resultado — {partes}. "
        f"A comparação de {metricas.METRICS_REGISTRY[chave]['label']} entre "
        "unidades com objetivos diferentes pode não ser direta."
    )


def _periodo_curto(contas):
    """Período do grupo no padrão de hífen: '01-07 a 17-07'.

    Do menor início ao maior fim entre os anexos (o parser entrega cada
    período como 'dd/mm/aaaa a dd/mm/aaaa')."""
    intervalos = []
    for conta in contas:
        try:
            ini, fim = (datetime.strptime(p.strip(), "%d/%m/%Y")
                        for p in (conta["dados"].get("periodo") or "").split(" a "))
            intervalos.append((ini, fim))
        except ValueError:
            continue
    if not intervalos:
        return ""
    ini = min(i[0] for i in intervalos)
    fim = max(i[1] for i in intervalos)
    return f"{ini:%d-%m} a {fim:%d-%m}"


def _barras_png(linhas):
    """Barras horizontais com o valor de cada conta — melhor unidade em verde.
    PNG transparente em base64 (mesmo padrão do donut do relatório)."""
    dados = [l for l in linhas if l["valor"] is not None]
    if len(dados) < 2:
        return None

    ordem = dados[::-1]           # matplotlib desenha de baixo para cima
    valores = [l["valor"] for l in ordem]
    cores = [VERDE if l["destaque"] else VERMELHO for l in ordem]
    posicoes = list(range(len(ordem)))
    maximo = max(valores) or 1

    fig, ax = plt.subplots(figsize=(7.2, max(1.8, 0.34 * len(ordem) + 0.4)), dpi=200)
    ax.barh(posicoes, valores, color=cores, height=0.62)
    ax.set_yticks(posicoes)
    ax.set_yticklabels([l["conta"] for l in ordem], fontsize=8.5,
                       color="#C7CBD1", fontfamily="DejaVu Sans")
    ax.tick_params(axis="y", length=0)
    ax.set_xticks([])
    ax.set_xlim(0, maximo * 1.2)
    for borda in ax.spines.values():
        borda.set_visible(False)
    for i, linha in enumerate(ordem):
        ax.text(linha["valor"] + maximo * 0.02, i, linha["valor_fmt"],
                va="center", fontsize=8.5, fontweight="bold",
                color="#FFFFFF", fontfamily="DejaVu Sans")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight",
                pad_inches=0.03)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def gerar_indicador(cliente, chave, contas, arquivo_saida):
    """
    Gera o PDF do Indicador Único em `arquivo_saida` (caminho ou file-like).

    `chave`:  chave de metricas.METRICS_REGISTRY
    `contas`: [{"nome": str, "dados": dict de ler_export_meta}] na ordem de envio
    """
    metrica = metricas.METRICS_REGISTRY[chave]
    linhas = metricas.ordenar(_linhas(chave, contas), chave)

    com_dado = [l for l in linhas if l["valor"] is not None]
    total = metricas.total_geral(chave, [l["num"] for l in com_dado])

    # Destaque: a 1ª linha já é a melhor, pois `ordenar` respeita `melhor`
    for linha in linhas:
        linha["destaque"] = False
    if metrica["melhor"] and com_dado:
        linhas[0]["destaque"] = True

    # % do total só faz sentido em métrica aditiva
    soma = metrica["agregacao"] == "soma"
    for linha in linhas:
        linha["indisponivel"] = linha["valor"] is None
        linha["valor_fmt"] = metricas.formatar(chave, linha["valor"])
        linha["share"] = (linha["valor"] / total * 100
                          if soma and total and linha["valor"] is not None else None)

    indisponiveis = [l["conta"] for l in linhas if l["valor"] is None]
    notas = []
    aviso = _aviso_objetivo(chave, contas)
    if aviso:
        notas.append(aviso)
    if indisponiveis:
        notas.append(
            f"Dado indisponível no export de: {', '.join(indisponiveis)} — "
            f"{'estas contas ficaram' if len(indisponiveis) > 1 else 'esta conta ficou'} "
            "fora do total do grupo."
        )
    if not soma:
        notas.append(
            f"O total geral de {metrica['label']} é recalculado sobre os "
            "valores brutos somados de todas as contas — não é a média dos "
            "valores individuais."
        )

    periodo = _periodo_curto(contas)
    contexto = {
        "cliente": cliente,
        "periodo": periodo,
        "logo_b64": _logo_b64(),
        "metrica_label": metrica["label"],
        "coluna_valor": metricas.rotulo_coluna(chave),
        "mostrar_share": soma,
        "linhas": linhas,
        "total_fmt": metricas.formatar(chave, total),
        "total_rotulo": "Total geral" if soma else "Geral (recalculado)",
        "subtitulo": (f"{len(contas)} conta{'s' if len(contas) != 1 else ''}"
                      f" — gerado em {datetime.now():%d-%m-%Y}"),
        "grafico_b64": _barras_png(linhas),
        "notas": notas,
        "rodape": "Relatório gerado a partir de dados exportados do Meta Ads Manager.",
    }
    html = render_to_string("relatorios/pdf_indicador.html", contexto)
    HTML(string=html).write_pdf(arquivo_saida)
    return periodo
