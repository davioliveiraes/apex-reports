# -*- coding: utf-8 -*-
"""
Análise de Rastreamento — as duas telas do diagnóstico.

Quarta frente, mesmo desenho das outras: a sessão guarda as **linhas cruas** do
export, e a consolidação é refeita a cada renderização. É barato (um laço) e
evita um estado calculado que possa discordar da tabela de conferência ao lado.

Não há PDF em lugar nenhum deste fluxo: a saída é texto.
"""

from django.shortcuts import redirect, render

from . import redator_ia, selecao_campanhas
from .analysis.numeros import inteiro, moeda
from .forms import RastreamentoUploadForm
from .parser_rastreamento import (blocos_possiveis, ler_arquivo_rastreamento)
from .rastreamento import diagnostico, mensagem, metricas

SESSAO_RASTREAMENTO = "rastreamento_apex"


def painel(request):
    """Tela 01 — o nome do cliente e um export do preset RASTREAMENTO."""
    erro, encontradas, esperadas = None, [], []
    if request.method == "POST":
        form = RastreamentoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            linhas, disponiveis, erro, encontradas, esperadas = (
                ler_arquivo_rastreamento(form.cleaned_data["arquivo"]))
            if not erro:
                request.session[SESSAO_RASTREAMENTO] = {
                    "cliente": form.cleaned_data["cliente"],
                    "linhas": linhas,
                    # `set` não cabe em JSON, e a sessão serializa em JSON.
                    "disponiveis": sorted(disponiveis),
                }
                return redirect("rastreamento_analise")
    else:
        form = RastreamentoUploadForm()
    return render(request, "relatorios/rastreamento_index.html",
                  {"form": form, "erro": erro, "encontradas": encontradas,
                   "esperadas": esperadas})


def analise(request):
    """Tela 02 — os quatro blocos, o diagnóstico e o texto do cliente."""
    dados = request.session.get(SESSAO_RASTREAMENTO)
    if not dados:
        return redirect("rastreamento")

    disponiveis = set(dados.get("disponiveis") or ())
    # Antes de qualquer conta, como nas outras frentes: o que não está marcado
    # não entra no consolidado, nos quatro blocos, no diagnóstico nem no
    # payload da IA. Um export de conta inteira mistura campanhas de objetivos
    # diferentes, e uma taxa de carregamento somada sobre elas não descreve
    # caminho nenhum.
    escolhidas, selecao, dados = selecao_campanhas.aplicar(
        request, dados, SESSAO_RASTREAMENTO,
        campos=selecao_campanhas.NOMES_RASTREAMENTO,
        entrega=selecao_campanhas.ENTREGA_RASTREAMENTO)
    total = metricas.consolidar(escolhidas)
    diag = diagnostico.diagnosticar(total, disponiveis)
    inicio, fim = total["periodo"]
    texto = mensagem.redigir(total, diag)

    extra = {}
    if request.method == "POST":
        if CAMPO_IA in request.POST:
            dados, extra = _reescrever_com_ia(
                request, dados, texto, _payload(diag))
        elif CAMPO_MOTOR in request.POST:
            dados, extra = _voltar_ao_motor(request, dados)

    do_motor = not dados.get("texto_ia")
    return render(request, "relatorios/rastreamento_analise.html", dict(
        extra, **selecao,
        cliente=dados["cliente"],
        do_motor=do_motor,
        ia_disponivel=extra.get("ia_disponivel", redator_ia.disponivel()),
        **{
        "periodo": (f"{mensagem._data(inicio)} a {mensagem._data(fim)}"
                    if inicio and fim else ""),
        "texto": dados.get("texto_ia") or texto,
        "blocos": [_bloco_para_tela(b) for b in diag["blocos"]],
        "gargalo": diag["gargalo"],
        "anuncios": _para_tela(total),
        "n_anuncios": total["n_anuncios"],
        "n_video": total["n_video"],
        "nivel": total["nivel"],
        "atribuicao": total["atribuicao"],
        "possiveis": len(blocos_possiveis(disponiveis)),
        "sem_periodo": not (inicio and fim),
    }))


def _payload(diag):
    """As métricas dos quatro blocos, já escritas, mais o gargalo apontado."""
    numeros = {}
    for bloco in diag["blocos"]:
        for m in bloco["metricas"]:
            numeros[f"{bloco['titulo']} — {m['rotulo']}"] = _FORMATO[
                m["formato"]](m["valor"])
    gargalo = diag.get("gargalo")
    return {"metricas": numeros,
            "ponto_de_atencao": gargalo["titulo"] if gargalo else None,
            "evidencia": gargalo["evidencia"] if gargalo else None}


# O template não formata número: a locale do projeto é pt-BR e um
# `floatformat` escreveria "0,58" onde o produto escreve "0,58%". Os textos
# prontos vêm daqui.
_FORMATO = {
    "inteiro": inteiro,
    "moeda": moeda,
    "percentual": diagnostico.percentual,
    "texto": lambda v: str(v),
}


def _bloco_para_tela(bloco):
    """O bloco com os valores já escritos.

    Métrica sem valor já saiu em `diagnostico._bloco`: a tela mostra o que o
    arquivo tem, e não uma grade de traços (§25).
    """
    return dict(bloco, metricas=[
        dict(m, texto=_FORMATO[m["formato"]](m["valor"]))
        for m in bloco["metricas"]])


def _para_tela(total):
    """A conferência por anúncio, do maior volume de cliques ao menor.

    Os que não registraram clique fecham a lista — não têm por onde ordenar, e
    é justamente isso que precisa saltar aos olhos.
    """
    linhas = []
    for a in total["anuncios"]:
        cliques = a.get("link_clicks")
        linhas.append({
            "rotulo": a["rotulo"],
            "veiculacao": a.get("delivery") or "—",
            "cliques": cliques,
            "cliques_txt": inteiro(cliques) if cliques is not None else "—",
            "ctr_txt": (diagnostico.percentual(a["link_ctr"])
                        if a.get("link_ctr") is not None else "—"),
            "cpc_txt": (moeda(a["link_cpc"]) if a.get("link_cpc") is not None
                        else "—"),
            "carregamento_txt": (
                diagnostico.percentual(a["taxa_carregamento"])
                if a.get("taxa_carregamento") is not None else "—"),
            "share_txt": (f"{round(a['share_clicks'] * 100)}%"
                          if a.get("share_clicks") is not None else "—"),
            "video_txt": (diagnostico.percentual(a["retencao"]["25_100"])
                          if a.get("retencao", {}).get("25_100") is not None
                          else "—"),
            "abaixo": [diagnostico.ROTULO_RANKING[c]
                       for c in a.get("rankings_abaixo") or ()],
        })
    return sorted(linhas, key=lambda l: (l["cliques"] is None,
                                         -(l["cliques"] or 0)))


# Os dois botões da tela 02 mandam o mesmo formulário para a mesma URL e se
# distinguem pelo nome — o padrão de CAMPO_IA em `views.py`.
CAMPO_IA = "rastreamento_ia"
CAMPO_MOTOR = "voltar_ao_motor"


def _reescrever_com_ia(request, dados, texto, payload):
    """Outra redação do mesmo texto, com os mesmos números.

    Falhar aqui não custa nada: o texto do motor é recalculado a cada
    renderização e volta à tela na mesma resposta.
    """
    try:
        novo = redator_ia.reescrever(
            texto, payload, redator_ia.PROMPT_REESCRITA_RASTREAMENTO)
    except redator_ia.ErroDeIA as e:
        definitivo = e.motivo in redator_ia.DEFINITIVOS
        return dados, {"erro_ia": str(e), "erro_ia_definitivo": definitivo,
                       "ia_disponivel": (redator_ia.disponivel()
                                         and not definitivo)}
    dados["texto_ia"] = novo
    request.session[SESSAO_RASTREAMENTO] = dados
    request.session.modified = True
    return dados, {"texto_ia_gerado": True, "ia_disponivel": True}


def _voltar_ao_motor(request, dados):
    """Descarta a reescrita e devolve o texto do cálculo.

    Existe porque a IA é opcional e a volta precisa ser um clique: sem isto,
    desfazer uma reescrita de que o operador não gostou exigiria reenviar o
    arquivo. Só aparece na tela depois de uma reescrita.
    """
    dados.pop("texto_ia", None)
    request.session[SESSAO_RASTREAMENTO] = dados
    request.session.modified = True
    return dados, {"restaurado": True}
