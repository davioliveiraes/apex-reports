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
from .parser_verba import (NIVEL_CAMPANHA, NIVEL_CONJUNTO, ler_arquivo_verba,
                           montar_estruturas, periodo_relatado)

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
            nivel = form.nivel()
            linhas, erro = ler_arquivo_verba(form.cleaned_data["arquivo"], nivel)
            if not erro:
                # O intervalo do relatório vem do ARQUIVO. Sem ele não há como
                # saber a que período o gasto se refere, e projetar mesmo
                # assim é o que produzia números que não descreviam nada.
                desde, ate, erro = periodo_relatado(linhas)
            if not erro:
                do_ciclo, ciclo = form.contratado()
                request.session[SESSAO_VERBA] = {
                    "cliente": form.cleaned_data["cliente"],
                    "contratado_ciclo": do_ciclo,
                    "periodo": ciclo,
                    "estrutura": form.cleaned_data["estrutura"],
                    "nivel": nivel,
                    "desde": desde.isoformat(),
                    "ate": ate.isoformat(),
                    "linhas": linhas,
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
        nivel_conjunto=dados.get("nivel") == NIVEL_CONJUNTO,
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
    """As linhas da conferência já formatadas.

    O orçamento aqui é o que está setado no Meta, e ele não decide número
    nenhum desde 29/08/2026 — o diário do fechamento vem do contrato. Continua
    na tabela porque é o que denuncia Meta em R$ 20/dia sob um contrato que
    pede R$ 43, e essa leitura é do operador.
    """
    reais = fechamento_verba.reais
    return [dict(e,
                 orcamento_diario_txt=reais(e["orcamento"]),
                 gasto_txt=reais(e["gasto"]))
            for e in estruturas]


def _resumo(calc):
    reais, pct = fechamento_verba.reais, fechamento_verba.pct
    desvio = calc["desvio_pct"]
    return {
        "contratado_txt": reais(calc["contratado_ciclo"]),
        # A unidade do contratado na tela sai do mesmo vocabulário que a
        # mensagem usa — duas fontes acabariam escrevendo "/mês" ao lado de
        # uma mensagem que diz "/semana".
        "unidade_contratado": fechamento_verba.vocabulario(calc)["nome"],
        "configurado_txt": reais(calc["contratado_diario"]),
        "gasto_txt": reais(calc["gasto"]),
        "projecao_txt": reais(calc["projecao_fechamento"]),
        "ritmo_txt": reais(calc["ritmo_real"]),
        "desvio_txt": ("+" if desvio and desvio > 0 else "") + pct(desvio),
        "trilho": _trilho(calc),
        # O intervalo do export, e o ciclo que ele definiu. O segundo fica
        # escrito na tela de propósito: é a única defesa que sobrou contra um
        # intervalo mal escolhido no Gerenciador. A aplicação não tem como
        # saber que o ciclo do cliente é outro; o operador tem, e só se vir o
        # que foi deduzido.
        "relatado_txt": f"{calc['desde']:%d/%m/%Y} a {calc['ate']:%d/%m/%Y}",
        "ciclo_txt": (f"{calc['inicio_ciclo']:%d/%m/%Y} a "
                      f"{calc['fim_ciclo']:%d/%m/%Y}"),
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
    contratado = calc["contratado_ciclo"] or 0.0
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
    ate = date.fromisoformat(dados["ate"])
    # `dias_do_mes` aqui é do PARSER, não do fechamento: é por ele que um
    # orçamento vitalício sem data de término vira equivalente diário. Essa
    # conta não tem relação com o ciclo do contrato — um vitalício de R$ 1.000
    # não passa a durar sete dias porque o cliente fecha por semana.
    estruturas, avisos = montar_estruturas(
        dados["linhas"], dados.get("nivel") or NIVEL_CAMPANHA,
        fechamento_verba.dias_do_mes(ate))
    calc = fechamento_verba.calcular(
        estruturas, dados.get("contratado_ciclo"),
        periodo=dados.get("periodo") or fechamento_verba.CICLO_MENSAL,
        inicio_relatorio=date.fromisoformat(dados["desde"]),
        termino_relatorio=ate)
    return estruturas, avisos, calc


def _form_base(dados):
    """A base interna como está na sessão — dois campos, e é o que o operador
    digitou que volta para a tela."""
    valor = dados.get("contratado_ciclo")
    return VerbaBaseForm(initial={
        "cliente": dados["cliente"],
        # O campo é texto e o valor guardado é float: sem formatar, o input
        # voltaria "990.0" para quem digitou "990,00". Sessão antiga não tem o
        # valor — aí o campo volta vazio e o operador redigita, em vez de a
        # tela quebrar com um TypeError.
        "orcamento": f"{valor:.2f}".replace(".", ",") if valor else "",
        "periodicidade": (dados.get("periodo")
                          or fechamento_verba.CICLO_MENSAL),
    })


def _recalcular(request, dados, form):
    """Refaz os números com a base interna corrigida, sem reenviar planilha.

    O texto da IA é descartado junto: ele foi escrito sobre os números
    anteriores, e mantê-lo na tela seria oferecer a leitura de outro
    fechamento.
    """
    do_ciclo, ciclo = form.contratado()
    novo = dict(dados,
                cliente=form.cleaned_data["cliente"],
                contratado_ciclo=do_ciclo,
                periodo=ciclo)
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
