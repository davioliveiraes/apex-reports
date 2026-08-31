# -*- coding: utf-8 -*-
"""
Análise de Desempenho — as duas telas da leitura de conjuntos.

Arquivo separado de `views.py` pelo mesmo motivo do `views_verba.py`: são
frentes que não compartilham nada além do visual. A Análise Geral lê o export
completo e termina num PDF de páginas; esta lê o export do preset
`DESEMPENHO`, no nível de conjuntos, e termina num texto para colar no grupo
do cliente. Não há PDF em lugar nenhum deste fluxo.

A sessão guarda as **linhas cruas** do export, não os números prontos. Refazer
a consolidação a cada renderização é barato (um laço sobre as linhas) e evita
um estado calculado que possa discordar da tabela de conferência ao lado.
"""

from django.shortcuts import redirect, render

from . import analise_desempenho, redator_ia, selecao_campanhas
from .analysis.numeros import decimal, inteiro, moeda
from .forms import DesempenhoUploadForm
from .parser_desempenho import ler_arquivo_desempenho

SESSAO_DESEMPENHO = "desempenho_apex"


def painel(request):
    """Tela 01 — o nome do cliente e um export do preset DESEMPENHO."""
    erro, faltando = None, []
    if request.method == "POST":
        form = DesempenhoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            linhas, erro, faltando = ler_arquivo_desempenho(
                form.cleaned_data["arquivo"])
            if not erro:
                request.session[SESSAO_DESEMPENHO] = {
                    "cliente": form.cleaned_data["cliente"],
                    "linhas": linhas,
                }
                return redirect("desempenho_analise")
    else:
        form = DesempenhoUploadForm()
    return render(request, "relatorios/desempenho_index.html",
                  {"form": form, "erro": erro, "faltando": faltando})


def analise(request):
    """Tela 02 — o resumo das métricas, o texto do cliente e a conferência."""
    dados = request.session.get(SESSAO_DESEMPENHO)
    if not dados:
        return redirect("desempenho")

    # A seleção acontece ANTES de qualquer conta: o que não está marcado não
    # entra no consolidado, no texto nem no payload da IA. Oito das nove
    # campanhas do export de referência estão paradas há meses, e consolidá-las
    # junto era o que fazia o texto falar delas.
    escolhidas, selecao, dados = selecao_campanhas.aplicar(
        request, dados, SESSAO_DESEMPENHO)
    agregado = analise_desempenho.consolidar(escolhidas)
    texto = analise_desempenho.redigir(agregado)

    extra = {}
    if request.method == "POST":
        if CAMPO_IA in request.POST:
            dados, extra = _reescrever_com_ia(
                request, dados, texto, _payload(agregado))
        elif CAMPO_MOTOR in request.POST:
            dados, extra = _voltar_ao_motor(request, dados)

    do_motor = not dados.get("texto_ia")
    return render(request, "relatorios/desempenho_analise.html", dict(
        extra, **selecao,
        cliente=dados["cliente"],
        do_motor=do_motor,
        ia_disponivel=extra.get("ia_disponivel", redator_ia.disponivel()),
        **{
        "periodo": agregado["periodo"],
        "texto": dados.get("texto_ia") or texto,
        "metricas": analise_desempenho.resumo(agregado),
        "conjuntos": _para_tela(agregado),
        "n_conjuntos": agregado["n_conjuntos"],
        "n_campanhas": agregado["n_campanhas"],
        "n_ativos": agregado["n_ativos"],
        "rotulo_indicador": agregado["rotulo_indicador"],
        # Com vários conjuntos o alcance somado conta duas vezes quem foi
        # atingido por dois deles, e a frequência derivada sai subestimada.
        # A tela diz isso; o texto do cliente não, porque a diferença não muda
        # nenhuma decisão dele.
        "alcance_somado": agregado["alcance_somado"],
        "sem_periodo": not agregado["periodo"],
        "classificacao": analise_desempenho.classificar(agregado),
    }))


# Os rótulos com que o modelo lê cada número. Explícitos, e não derivados do
# resumo da tela, porque é este dicionário que define o vocabulário da
# reescrita: o modelo chama de "frequência" o que chega como "Frequência".
_ROTULOS_DO_PAYLOAD = (
    ("Período", "periodo"),
    ("Tipo de resultado", "rotulo_indicador"),
    ("Resultados", "resultados"),
    ("Custo por resultado", "custo_resultado"),
    ("Alcance", "alcance"),
    ("Impressões", "impressoes"),
    ("Frequência", "frequencia"),
    ("CPM", "cpm"),
    ("Conversas iniciadas", "conversas"),
    ("Custo por conversa", "custo_conversa"),
    ("Novos contatos", "novos_contatos"),
)


def _payload(agregado):
    """Os números da CAMPANHA SELECIONADA, como o modelo os recebe.

    Nunca a planilha, nunca outra campanha, e nunca um campo vazio: métrica
    ausente sai do dicionário em vez de viajar como `None`. Um `null` no
    payload é um convite para o modelo escrever "sem dados de frequência", que
    é informação de operação e não do cliente.
    """
    formato = {
        "resultados": inteiro, "alcance": inteiro, "impressoes": inteiro,
        "conversas": inteiro, "novos_contatos": inteiro,
        "custo_resultado": moeda, "custo_conversa": moeda, "cpm": moeda,
        "frequencia": decimal,
    }
    dados = {}
    for rotulo, chave in _ROTULOS_DO_PAYLOAD:
        valor = agregado.get(chave)
        if valor is None or valor == "" or valor == 0:
            continue
        dados[rotulo] = formato[chave](valor) if chave in formato else valor

    novos = agregado.get("novos_contatos") or 0
    conversas = agregado.get("conversas") or 0
    if novos and conversas:
        dados["Percentual de novos contatos"] = (
            f"{round(novos / conversas * 100)}%")
    return dados


def _para_tela(agregado):
    """As linhas da conferência, do menor custo por resultado ao maior.

    Os conjuntos que não converteram fecham a lista: não têm custo por onde
    ordenar, e é justamente isso que precisa saltar aos olhos.

    O nome **cru** vai junto do rótulo limpo. O texto do cliente usa o rótulo
    ("Conjunto 1" quando o nome é só jargão de operação); aqui o operador
    precisa do nome que ele encontra no Gerenciador.
    """
    linhas = []
    for c in agregado["conjuntos"]:   # só as linhas da campanha selecionada
        custo = c["custo_resultado"]
        linhas.append({
            "rotulo": c["rotulo"],
            "nome": c["nome"] or "(sem nome na planilha)",
            "veiculacao": "Ativo" if c["ativa"] else "Desativado",
            "ativa": c["ativa"],
            "custo": custo,
            "resultados_txt": inteiro(c["resultados"]),
            "custo_txt": moeda(custo) if custo else "—",
            "impressoes_txt": inteiro(c["impressoes"]),
            "frequencia_txt": (decimal(c["frequencia"]) if c["frequencia"]
                               else "—"),
            "novos_txt": inteiro(c["novos_contatos"]),
        })
    return sorted(linhas, key=lambda l: (l["custo"] is None, l["custo"] or 0.0))


# Os dois botões da tela 02 mandam o mesmo formulário para a mesma URL e se
# distinguem pelo nome — o padrão de CAMPO_IA em `views.py`.
CAMPO_IA = "desempenho_ia"
CAMPO_MOTOR = "voltar_ao_motor"
_PROIBIDOS_NA_REESCRITA = ("conjunto", "outras campanhas")
_REFORCO_SEGUNDA_TENTATIVA = (
    "CORREÇÃO OBRIGATÓRIA PARA ESTA NOVA TENTATIVA\n"
    "A tentativa anterior não cumpriu o contrato de saída e foi descartada. "
    "Gere novamente do zero. Antes de responder, confira: título exato, "
    "quatro parágrafos, todos os números preservados, nenhum termo interno "
    "de estrutura e último parágrafo sem números. Retorne somente a nova "
    "mensagem final."
)

_CAMPOS_DA_MENSAGEM_IA = (
    ("PERÍODO", "Período"),
    ("RESULTADO PRINCIPAL", "Resultados"),
    ("TIPO DE RESULTADO", "Tipo de resultado"),
    ("CUSTO POR RESULTADO", "Custo por resultado"),
    ("CONVERSAS INICIADAS", "Conversas iniciadas"),
    ("CUSTO POR CONVERSA", "Custo por conversa"),
    ("NOVOS CONTATOS", "Novos contatos"),
    ("PERCENTUAL DE NOVOS CONTATOS", "Percentual de novos contatos"),
    ("ALCANCE", "Alcance"),
    ("IMPRESSÕES", "Impressões"),
    ("FREQUÊNCIA", "Frequência"),
    ("CPM", "CPM"),
)


def _mensagem_usuario_ia(texto, payload):
    """Fatos rotulados para a IA, sem XLSX, nome técnico ou valor ausente."""
    secoes = ["DADOS E FATOS VALIDADOS DA CAMPANHA SELECIONADA"]
    for titulo, chave in _CAMPOS_DA_MENSAGEM_IA:
        if chave in payload:
            secoes.append(f"{titulo}\n{payload[chave]}")
    secoes.extend((
        "TEXTO DETERMINÍSTICO — REFERÊNCIA FACTUAL ADICIONAL\n" + texto,
        "TAREFA\nProduza uma nova versão da mensagem. Use os dados "
        "estruturados como fonte principal; não faça uma paráfrase linha por "
        "linha do texto determinístico. Acrescente ao final o quarto "
        "parágrafo consultivo, sem números ou métricas, falando diretamente "
        "com o cliente.",
    ))
    return "\n\n".join(secoes)


def _validar_reescrita_desempenho(novo, original):
    """Garantias exclusivas do texto de Desempenho para o cliente.

    A guarda comum impede números inventados. Aqui também recusamos título
    ausente e omissões: nesta frente todos os valores do texto determinístico
    precisam sobreviver à melhora de redação.
    """
    blocos = redator_ia._blocos(novo)
    if not blocos or blocos[0] != "*Desempenho*":
        raise redator_ia.ErroDeIA(
            "A reescrita não começou com *Desempenho*. Mantido o texto do "
            "cálculo.", "formato")
    if len(blocos) != 5:
        raise redator_ia.ErroDeIA(
            "A reescrita não veio com os quatro parágrafos pedidos. Mantido "
            "o texto do cálculo.", "formato")
    if redator_ia._NUMERO_NO_TEXTO.search(blocos[-1]):
        raise redator_ia.ErroDeIA(
            "O último parágrafo repetiu números, mas ele deve falar "
            "diretamente com o cliente. Mantido o texto do cálculo.",
            "formato")

    originais = set(redator_ia._NUMERO_NO_TEXTO.findall(original))
    presentes = set(redator_ia._NUMERO_NO_TEXTO.findall(novo))
    omitidos = sorted(originais - presentes)
    if omitidos:
        raise redator_ia.ErroDeIA(
            "A reescrita omitiu número do cálculo "
            f"({', '.join(omitidos[:3])}). Mantido o texto do cálculo — a IA "
            "pode melhorar as frases, não retirar os dados.", "formato")
    return novo


def _reescrever_com_ia(request, dados, texto, payload):
    """Outra redação do mesmo texto, com os mesmos números.

    Falhar aqui não custa nada: o texto do motor é recalculado a cada
    renderização e volta à tela na mesma resposta.
    """
    mensagem = _mensagem_usuario_ia(texto, payload)

    def gerar(mensagem_usuario):
        candidato = redator_ia.reescrever(
            texto, payload, redator_ia.PROMPT_REESCRITA_DESEMPENHO,
            proibidos=_PROIBIDOS_NA_REESCRITA,
            mensagem_usuario=mensagem_usuario)
        return _validar_reescrita_desempenho(candidato, texto)

    try:
        try:
            novo = gerar(mensagem)
        except redator_ia.ErroDeIA as primeira:
            # Formato é resposta inválida do modelo, não falha da conta. Uma
            # única nova tentativa substitui o clique manual que o operador
            # acabava fazendo depois de reaplicar a mesma seleção.
            if primeira.motivo != "formato":
                raise
            novo = gerar(mensagem + "\n\n" + _REFORCO_SEGUNDA_TENTATIVA)
    except redator_ia.ErroDeIA as e:
        definitivo = e.motivo in redator_ia.DEFINITIVOS
        return dados, {"erro_ia": str(e), "erro_ia_definitivo": definitivo,
                       "ia_disponivel": (redator_ia.disponivel()
                                         and not definitivo)}
    dados["texto_ia"] = novo
    request.session[SESSAO_DESEMPENHO] = dados
    request.session.modified = True
    return dados, {"texto_ia_gerado": True, "ia_disponivel": True}


def _voltar_ao_motor(request, dados):
    """Descarta a reescrita e devolve o texto do cálculo.

    Existe porque a IA é opcional e a volta precisa ser um clique: sem isto,
    desfazer uma reescrita de que o operador não gostou exigiria reenviar o
    arquivo. Só aparece na tela depois de uma reescrita.
    """
    dados.pop("texto_ia", None)
    request.session[SESSAO_DESEMPENHO] = dados
    request.session.modified = True
    return dados, {"restaurado": True}
