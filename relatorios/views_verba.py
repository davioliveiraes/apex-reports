# -*- coding: utf-8 -*-
"""
Análise de Verba — as duas telas do fechamento.

Arquivo separado de `views.py` pelo mesmo motivo que o parser é separado: são
duas frentes que não compartilham nada além do visual. A de desempenho lê como
as campanhas entregaram e termina num PDF; esta lê como o orçamento está
configurado e termina numa mensagem para colar no grupo do cliente.

A sessão guarda as **linhas cruas** dos dois exports, não os números prontos.
É o que permite corrigir o contratado ou a data de referência na tela 02 e ver
tudo se refazer sem reenviar planilha — e é preciso: o equivalente diário de um
orçamento vitalício depende de quantos dias tem o mês analisado.
"""

from datetime import date

from django.shortcuts import redirect, render

from . import fechamento_verba, redator_ia
from .forms import VerbaBaseForm, VerbaUploadForm
from .parser_verba import ler_arquivos_verba, montar_estruturas

SESSAO_VERBA = "verba_apex"

# A tela 02 tem dois botões que mandam o mesmo formulário para a mesma URL:
# *Recalcular* (o padrão) e *Reescrever com IA*, que se identifica por este
# campo. Mesmo padrão de CAMPO_IA/CAMPO_CAMPANHAS em views.py.
CAMPO_IA_VERBA = "mensagem_ia"


def painel(request):
    """Tela 01 — a base interna e os exports do preset VERBA."""
    erro = None
    if request.method == "POST":
        form = VerbaUploadForm(request.POST, request.FILES)
        if form.is_valid():
            campanhas, conjuntos, erro = ler_arquivos_verba(
                form.cleaned_data["arquivos"])
            if not erro and not campanhas:
                erro = ("O único arquivo enviado é do nível conjunto de "
                        "anúncios. O gasto do mês sai do export de campanha — "
                        "exporte também a aba Campanhas.")
            if not erro:
                mensal, diario = form.contratado()
                request.session[SESSAO_VERBA] = {
                    "cliente": form.cleaned_data["cliente"],
                    "contratado_mensal": mensal,
                    "contratado_diario": diario,
                    "referencia": form.cleaned_data["referencia"].isoformat(),
                    "linhas_campanha": campanhas,
                    "linhas_conjunto": conjuntos,
                }
                return redirect("verba_fechamento")
    else:
        form = VerbaUploadForm()
    return render(request, "relatorios/verba_index.html",
                  {"form": form, "erro": erro})


def fechamento(request):
    """Tela 02 — os dois blocos de saída, a conferência e a base reeditável."""
    dados = request.session.get(SESSAO_VERBA)
    if not dados:
        return redirect("verba")

    extra = {}
    if request.method == "POST":
        form = VerbaBaseForm(request.POST)
        if form.is_valid() and CAMPO_IA_VERBA in request.POST:
            dados, extra = _reescrever_com_ia(request, dados, form)
        elif form.is_valid():
            dados, extra = _recalcular(request, dados, form)
    else:
        form = _form_base(dados)

    estruturas, avisos, calc = _apurar(dados)
    return render(request, "relatorios/verba_fechamento.html", dict(
        extra,
        form=form,
        cliente=dados["cliente"],
        calc=calc,
        estruturas=_para_tela(estruturas),
        avisos=avisos,
        mensagem=dados.get("mensagem_ia") or fechamento_verba.mensagem(calc),
        analise=fechamento_verba.analise(calc),
        frase_status=fechamento_verba.frase_status(calc),
        ia_disponivel=extra.get("ia_disponivel", redator_ia.disponivel()),
        **_resumo(calc),
    ))


# O template não formata dinheiro: `reais()` é uma função Python, e um
# `floatformat` no HTML devolveria "990,0" onde o resto do produto escreve
# "R$ 990". Os textos prontos vêm daqui.
def _para_tela(estruturas):
    reais = fechamento_verba.reais
    linhas = []
    for e in estruturas:
        # A coluna mostra o configurado inteiro; o "no ar" só aparece quando
        # difere. Sem ele a conta da tela não fecha: uma campanha com conjunto
        # pausado dentro entra na soma do topo por um valor menor do que o que
        # a própria linha exibe.
        ativo = (reais(e["orcamento_ativo"])
                 if e["orcamento"] != e["orcamento_ativo"] else "")
        linhas.append(dict(e,
                           orcamento_diario_txt=reais(e["orcamento"]),
                           orcamento_ativo_txt=ativo,
                           gasto_txt=reais(e["gasto"])))
    return linhas


def _resumo(calc):
    reais, pct = fechamento_verba.reais, fechamento_verba.pct
    desvio = calc["desvio_pct"]
    return {
        "contratado_txt": reais(calc["contratado_mensal"]),
        "configurado_txt": reais(calc["configurado_diario"]),
        "gasto_txt": reais(calc["gasto"]),
        "projecao_txt": reais(calc["projecao_fechamento"]),
        "ritmo_txt": reais(calc["ritmo_real"]),
        "desvio_txt": ("+" if desvio and desvio > 0 else "") + pct(desvio),
        "trilho": _trilho(calc),
    }


# Cores do desvio na tela, derivadas do status e não de uma segunda regra:
# duas escadas para a mesma coisa acabariam discordando uma da outra.
_TOM_DO_STATUS = {
    fechamento_verba.STATUS_ALINHADO: "no-ritmo",
    fechamento_verba.STATUS_POUCO_ACIMA: "desviando",
    fechamento_verba.STATUS_POUCO_ABAIXO: "desviando",
    fechamento_verba.STATUS_PARCIAL: "desviando",
    fechamento_verba.STATUS_ACIMA: "fora",
    fechamento_verba.STATUS_ABAIXO: "fora",
}


def _trilho(calc):
    """As três posições do trilho de fechamento, em % da própria pista.

    A pista é escalada pelo MAIOR entre contratado e projeção, não pelo
    contratado: assim uma projeção que estoura o combinado aparece passando da
    marca em vez de ser cortada na borda — que é justamente o caso que o
    operador precisa ver de longe.

    As posições saem daqui como **texto com o `%` colado**, e não como float:
    a locale do projeto é pt-BR, e o template localizaria `74.75` para
    `74,75` — CSS inválido, que o navegador descarta em silêncio deixando a
    barra vazia. Comprimento de CSS não é número de ler.
    """
    contratado = calc["contratado_mensal"] or 0.0
    projecao = calc["projecao_fechamento"] or 0.0
    escala = max(contratado, projecao)
    if not escala:
        return None

    def posicao(valor):
        return f"{(valor or 0.0) / escala * 100:.2f}%"

    return {
        "gasto": posicao(calc["gasto"]),
        "projetado": posicao(projecao),
        "alvo": posicao(contratado),
        "tom": _TOM_DO_STATUS.get(calc["status"], "desviando"),
    }


def _apurar(dados):
    """`(estruturas, avisos, calc)` a partir do que está na sessão.

    Refeito a cada renderização, e de propósito: é barato (um laço sobre as
    linhas), e assim não existe estado calculado que possa discordar da base
    interna que o operador acabou de corrigir.
    """
    hoje = date.fromisoformat(dados["referencia"])
    estruturas, avisos = montar_estruturas(
        dados["linhas_campanha"], dados["linhas_conjunto"],
        fechamento_verba.dias_do_mes(hoje))
    calc = fechamento_verba.calcular(
        estruturas, dados.get("contratado_mensal"),
        dados.get("contratado_diario"), hoje)
    return estruturas, avisos, calc


def _form_base(dados):
    """A base interna como está na sessão — mensal e diário nunca convivem
    aqui: guardamos o que o operador digitou, e é ele que volta para a tela."""
    mensal = dados.get("contratado_mensal")
    valor = mensal if mensal else dados.get("contratado_diario")
    return VerbaBaseForm(initial={
        "cliente": dados["cliente"],
        # O campo é texto e o valor guardado é float: sem formatar, o input
        # voltaria "990.0" para quem digitou "990,00".
        "orcamento": f"{valor:.2f}".replace(".", ","),
        "periodicidade": (VerbaBaseForm.MENSAL if mensal
                          else VerbaBaseForm.DIARIO),
        "referencia": date.fromisoformat(dados["referencia"]),
    })


def _recalcular(request, dados, form):
    """Refaz os números com a base interna corrigida, sem reenviar planilha.

    O texto da IA é descartado junto: ele foi escrito sobre os números
    anteriores, e mantê-lo na tela seria oferecer a leitura de outro
    fechamento.
    """
    mensal, diario = form.contratado()
    novo = dict(dados,
                cliente=form.cleaned_data["cliente"],
                contratado_mensal=mensal,
                contratado_diario=diario,
                referencia=form.cleaned_data["referencia"].isoformat())
    novo.pop("mensagem_ia", None)
    request.session[SESSAO_VERBA] = novo
    request.session.modified = True
    return novo, {"recalculado": True}


def _reescrever_com_ia(request, dados, form):
    """Pede ao modelo outra redação da mesma mensagem.

    Falhar aqui não custa nada: a mensagem do motor continua na tela e o erro
    vira aviso. É o mesmo contrato da Análise do Período.
    """
    dados, _ = _recalcular(request, dados, form)
    _, _, calc = _apurar(dados)
    try:
        texto = redator_ia.gerar_mensagem_verba(calc, dados["cliente"])
    except redator_ia.ErroDeIA as e:
        definitivo = e.motivo in redator_ia.DEFINITIVOS
        return dados, {"erro_ia": str(e),
                       "erro_ia_definitivo": definitivo,
                       "ia_disponivel": redator_ia.disponivel() and not definitivo}

    dados["mensagem_ia"] = texto
    request.session[SESSAO_VERBA] = dados
    request.session.modified = True
    return dados, {"mensagem_ia_gerada": True, "ia_disponivel": True}
