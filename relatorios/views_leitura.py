# -*- coding: utf-8 -*-
"""
Leitura Rápida — as duas telas da leitura curta.

Reescrita em 30/08/2026 sobre o domínio da Análise de Desempenho. Antes esta
frente lia o export COMPLETO (`parser_xlsx.consolidar`) e classificava o
período pela faixa de perfil de negócio; hoje lê o mesmo preset `DESEMPENHO`
da frente de desempenho, com o mesmo parser e a mesma consolidação, e não
classifica (ver `leitura.resumo.classificar`).

O ganho não é economia de código: é que a leitura do WhatsApp e a análise
completa **não podem discordar sobre o mesmo mês**. As duas saem de
`analise_desempenho.consolidar`, então o custo por conversa que vai no grupo é
o mesmo que a outra tela mostra.

Duas telas, e não uma: o envio precisa de um POST com arquivo, e a leitura
precisa sobreviver a um F5. É o mesmo desenho das outras três frentes, e o que
a §7 pede — velocidade — vem de não haver campo nenhum além do nome e do
anexo, não de espremer tudo numa tela.
"""

from django.shortcuts import redirect, render

from . import analise_desempenho, redator_ia, selecao_campanhas
from .forms import LeituraUploadForm
from .leitura import imagem, mensagem, resumo
from .parser_desempenho import ler_arquivo_desempenho

SESSAO_LEITURA = "leitura_apex"

# De onde vieram os números desta leitura. Fica na sessão porque a tela 02
# precisa dizê-lo: um número transcrito de print não tem a mesma garantia de
# um número lido de célula, e quem confere é o operador — que só confere se
# souber que precisa.
ORIGEM_PLANILHA = "planilha"
ORIGEM_IMAGEM = "imagem"


def painel(request):
    """Tela 01 — o cliente e o export, em planilha ou em print."""
    erro, faltando = None, []
    if request.method == "POST":
        form = LeituraUploadForm(request.POST, request.FILES)
        if form.is_valid():
            linhas, avisos, origem, erro, faltando = _ler(form)
            if not erro:
                request.session[SESSAO_LEITURA] = {
                    "cliente": form.cleaned_data["cliente"],
                    "linhas": linhas,
                    "origem": origem,
                    "avisos": avisos,
                }
                return redirect("leitura_mensagem")
    else:
        form = LeituraUploadForm()
    return render(request, "relatorios/leitura_index.html",
                  {"form": form, "erro": erro, "faltando": faltando,
                   "ia_disponivel": redator_ia.disponivel()})


def _ler(form):
    """`(linhas, avisos, origem, erro, colunas faltando)`.

    As duas portas terminam na mesma estrutura — uma lista de linhas na forma
    que `parser_desempenho` entrega. É o que permite todo o resto do fluxo
    ignorar de onde os números vieram.
    """
    prints = form.imagens()
    if prints:
        linhas, avisos, erro = imagem.extrair(prints)
        return linhas, avisos, ORIGEM_IMAGEM, erro, []

    # Mesma validação da Análise de Desempenho, de propósito: duas mensagens
    # diferentes para o mesmo arquivo errado ensinariam o operador que uma das
    # telas está quebrada (§29).
    linhas, erro, faltando = ler_arquivo_desempenho(form.planilha())
    return linhas, [], ORIGEM_PLANILHA, erro, faltando


def leitura(request):
    """Tela 02 — quatro números e o texto pronto."""
    dados = request.session.get(SESSAO_LEITURA)
    if not dados:
        return redirect("leitura")

    # A mesma seleção das outras frentes, e pelo mesmo motivo: uma leitura de
    # três parágrafos sobre nove campanhas com oito paradas fala de operação
    # que não existe. Não aparece quando o arquivo traz um grupo só, que é o
    # caso comum aqui — e nunca aparece numa leitura vinda de print, onde não
    # há coluna de campanha para agrupar.
    escolhidas, selecao, dados = selecao_campanhas.aplicar(
        request, dados, SESSAO_LEITURA)

    # Refeito a cada renderização, como nas outras frentes: é um laço sobre as
    # linhas, e assim não existe texto guardado que possa discordar dos
    # números ao lado dele.
    total = analise_desempenho.consolidar(escolhidas)
    curto = resumo.montar(total)
    texto = mensagem.redigir(curto)

    extra = {}
    if request.method == "POST":
        if CAMPO_IA in request.POST:
            dados, extra = _reescrever_com_ia(
                request, dados, texto, _payload(curto))
        elif CAMPO_MOTOR in request.POST:
            dados, extra = _voltar_ao_motor(request, dados)

    da_imagem = dados.get("origem") == ORIGEM_IMAGEM
    return render(request, "relatorios/leitura_mensagem.html", dict(
        extra, **selecao,
        cliente=dados["cliente"],
        do_motor=not dados.get("texto_ia"),
        ia_disponivel=extra.get("ia_disponivel", redator_ia.disponivel()),
        **{
        # A origem é informação de conferência, não decoração: número
        # transcrito de print pode ter um dígito trocado, e a tela é o único
        # lugar onde isso ainda dá para pegar antes de o texto ser enviado.
        "da_imagem": da_imagem,
        "avisos": dados.get("avisos") or [],
        "periodo": curto["periodo"],
        "periodo_longo": total["periodo"],
        "texto": dados.get("texto_ia") or texto,
        "cartoes": resumo.cartoes(curto),
        "entrega": resumo.entrega(curto),
        "classificacao": curto["classificacao"],
        "n_conjuntos": curto["n_conjuntos"],
        "n_campanhas": curto["n_campanhas"],
        "sem_periodo": not curto["periodo"],
    }))


def _payload(curto):
    """Os quatro números da tela e a entrega, já escritos."""
    return {m["rotulo"]: m["valor"]
            for m in resumo.cartoes(curto) + resumo.entrega(curto)}


# Os dois botões da tela 02 mandam o mesmo formulário para a mesma URL e se
# distinguem pelo nome — o padrão de CAMPO_IA em `views.py`.
CAMPO_IA = "leitura_ia"
CAMPO_MOTOR = "voltar_ao_motor"


def _reescrever_com_ia(request, dados, texto, payload):
    """Outra redação do mesmo texto, com os mesmos números.

    Falhar aqui não custa nada: o texto do motor é recalculado a cada
    renderização e volta à tela na mesma resposta.
    """
    try:
        novo = redator_ia.reescrever(
            texto, payload, redator_ia.PROMPT_REESCRITA_LEITURA)
    except redator_ia.ErroDeIA as e:
        definitivo = e.motivo in redator_ia.DEFINITIVOS
        return dados, {"erro_ia": str(e), "erro_ia_definitivo": definitivo,
                       "ia_disponivel": (redator_ia.disponivel()
                                         and not definitivo)}
    dados["texto_ia"] = novo
    request.session[SESSAO_LEITURA] = dados
    request.session.modified = True
    return dados, {"texto_ia_gerado": True, "ia_disponivel": True}


def _voltar_ao_motor(request, dados):
    """Descarta a reescrita e devolve o texto do cálculo.

    Existe porque a IA é opcional e a volta precisa ser um clique: sem isto,
    desfazer uma reescrita de que o operador não gostou exigiria reenviar o
    arquivo. Só aparece na tela depois de uma reescrita.
    """
    dados.pop("texto_ia", None)
    request.session[SESSAO_LEITURA] = dados
    request.session.modified = True
    return dados, {"restaurado": True}
