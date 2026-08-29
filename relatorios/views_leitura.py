# -*- coding: utf-8 -*-
"""
Leitura Rápida — as duas telas da mensagem de período.

Arquivo à parte pelo mesmo motivo de `views_verba.py`: são frentes diferentes
do mesmo produto. A de desempenho lê o export e termina num PDF de páginas;
esta lê o MESMO export e termina num texto para colar no grupo do cliente.

O que a sessão guarda é o `consolidar` reduzido (ver
`leitura_rapida.CAMPOS_SESSAO`), não a mensagem pronta. O texto é reescrito a
cada renderização, e é barato — é um punhado de `format` sobre números que já
estão calculados. Guardar o texto criaria um estado que pode discordar dos
números que a própria tela mostra ao lado.
"""

from django.shortcuts import redirect, render

from . import leitura_rapida, redator_ia
from .analysis.numeros import inteiro, moeda
from .forms import LeituraUploadForm
from .parser_xlsx import consolidar, ler_registros

SESSAO_LEITURA = "leitura_apex"

# Os dois botões da tela 02. Ambos mandam o mesmo formulário para a mesma URL e
# se distinguem pelo nome — o padrão de CAMPO_IA em `views.py`.
CAMPO_IA_LEITURA = "leitura_ia"
CAMPO_MOTOR = "voltar_ao_motor"


def painel(request):
    """Tela 01 — o nome do cliente e um export de desempenho."""
    erro = None
    if request.method == "POST":
        form = LeituraUploadForm(request.POST, request.FILES)
        if form.is_valid():
            dados, erro = _ler(form.cleaned_data["arquivo"])
            if not erro:
                dados["cliente"] = form.cleaned_data["cliente"]
                request.session[SESSAO_LEITURA] = dados
                return redirect("leitura_mensagem")
    else:
        form = LeituraUploadForm()
    return render(request, "relatorios/leitura_index.html",
                  {"form": form, "erro": erro})


def leitura(request):
    """Tela 02 — a mensagem, a conferência das frentes e o botão de IA."""
    dados = request.session.get(SESSAO_LEITURA)
    if not dados:
        return redirect("leitura")

    extra = {}
    if request.method == "POST":
        if CAMPO_IA_LEITURA in request.POST:
            dados, extra = _reescrever_com_ia(request, dados)
        elif CAMPO_MOTOR in request.POST:
            dados, extra = _voltar_ao_motor(request, dados)

    do_motor = not dados.get("texto_ia")
    return render(request, "relatorios/leitura_mensagem.html", dict(
        extra,
        cliente=dados["cliente"],
        periodo=dados.get("periodo") or "",
        texto=dados.get("texto_ia") or leitura_rapida.mensagem(dados),
        do_motor=do_motor,
        frentes_tabela=_para_tela(dados),
        ia_disponivel=extra.get("ia_disponivel", redator_ia.disponivel()),
        **leitura_rapida.resumo(dados),
    ))


def _ler(arquivo):
    """`(dados enxutos, erro)` para um export de desempenho.

    A mensagem de erro aponta a outra frente de propósito: o engano provável
    aqui não é mandar um arquivo corrompido, é mandar o export do preset VERBA
    — os dois saem do mesmo Gerenciador, na mesma semana, para o mesmo cliente.
    """
    try:
        registros, mapa = ler_registros(arquivo)
    except ValueError as e:
        return None, f'Arquivo "{arquivo.name}": {e}'
    except Exception:
        return None, (
            f'Não foi possível ler "{arquivo.name}". Confira se é um .xlsx de '
            "desempenho do Gerenciador de Anúncios — o export do preset VERBA "
            "não serve aqui: ele traz orçamento, não resultado.")
    return leitura_rapida.enxuto(consolidar(registros, mapa)), None


def _para_tela(dados):
    """As frentes da conferência, ordenadas do contato mais barato ao mais caro.

    Mesma ordem em que a mensagem as cita — o operador confere de cima para
    baixo sem procurar. As que não converteram fecham a lista: elas não têm
    custo para ordenar, e é justamente isso que precisa saltar aos olhos.
    """
    linhas = []
    for r in leitura_rapida.recortes(dados):
        res, inv = r["resultados"], r["investimento"]
        cpa = inv / res if res and inv else None
        linhas.append({"rotulo": r["rotulo"], "cpa": cpa,
                       "resultados_txt": inteiro(res),
                       "investimento_txt": moeda(inv),
                       "cpa_txt": moeda(cpa) if cpa else "—"})
    return sorted(linhas, key=lambda l: (l["cpa"] is None, l["cpa"] or 0.0))


def _reescrever_com_ia(request, dados):
    """Outra redação do mesmo período, pelo prompt do operador.

    Falhar aqui não custa nada: o texto do motor volta à tela na mesma
    renderização, porque ele nunca foi guardado — é recalculado sempre.
    """
    try:
        texto = redator_ia.gerar_leitura_periodo(dados)
    except redator_ia.ErroDeIA as e:
        definitivo = e.motivo in redator_ia.DEFINITIVOS
        return dados, {"erro_ia": str(e),
                       "erro_ia_definitivo": definitivo,
                       "ia_disponivel": (redator_ia.disponivel()
                                         and not definitivo)}
    dados["texto_ia"] = texto
    request.session[SESSAO_LEITURA] = dados
    request.session.modified = True
    return dados, {"texto_ia_gerado": True, "ia_disponivel": True}


def _voltar_ao_motor(request, dados):
    """Descarta a redação da IA e devolve a do cálculo.

    Existe porque a IA é opcional e a volta precisa ser um clique: sem isto,
    desfazer uma reescrita de que o operador não gostou exigiria reenviar a
    planilha.
    """
    dados.pop("texto_ia", None)
    request.session[SESSAO_LEITURA] = dados
    request.session.modified = True
    return dados, {"restaurado": True}
