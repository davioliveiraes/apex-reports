# -*- coding: utf-8 -*-
"""
Análise de Desempenho — os fluxos Individual e Consolidado.

Arquivo separado de `views.py` pelo mesmo motivo do `views_verba.py`: são
frentes que não compartilham nada além do visual. A Análise Geral lê o export
completo e termina num PDF de páginas; esta lê o export do preset
`DESEMPENHO`, no nível de conjuntos, e termina num texto para colar no grupo
do cliente. Não há PDF em lugar nenhum deste fluxo.

A sessão guarda as **linhas cruas** do export, não os números prontos. Refazer
a consolidação a cada renderização é barato (um laço sobre as linhas) e evita
um estado calculado que possa discordar da tabela de conferência ao lado.
"""

import os
import re

from django.shortcuts import redirect, render

from . import (analise_desempenho, desempenho_consolidado, redator_ia,
               selecao_campanhas)
from .analysis.numeros import decimal, inteiro, moeda
from .forms import DesempenhoUploadForm
from .parser_desempenho import ler_arquivo_desempenho, periodo_do_relatorio

SESSAO_DESEMPENHO = "desempenho_apex"
SESSAO_DESEMPENHO_CONSOLIDADO = "desempenho_consolidado_apex"


def painel(request):
    """Tela 01 — escolhe o modo e lê um ou vários exports DESEMPENHO."""
    erro, faltando, erros_arquivos = None, [], []
    if request.method == "POST":
        form = DesempenhoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            if form.cleaned_data["modo"] == form.MODO_CONSOLIDADO:
                validos, erros_arquivos = _ler_consolidado(request, form)
                if len(validos) >= desempenho_consolidado.MIN_UNIDADES:
                    request.session[SESSAO_DESEMPENHO_CONSOLIDADO] = {
                        "cliente": form.cleaned_data["cliente"],
                        "produto": form.cleaned_data["produto"],
                        "unidades": validos,
                        "arquivos_invalidos": erros_arquivos,
                    }
                    return redirect("desempenho_consolidado")
                erro = ("O consolidado precisa de pelo menos 2 arquivos "
                        "válidos com o preset DESEMPENHO.")
                return render(request, "relatorios/desempenho_index.html", {
                    "form": form, "erro": erro, "faltando": [],
                    "erros_arquivos": erros_arquivos,
                })

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
                  {"form": form, "erro": erro, "faltando": faltando,
                   "erros_arquivos": erros_arquivos})


def _nome_unidade(nome_arquivo):
    """Sugestão editável; o nome do arquivo nunca é tratado como verdade."""
    base = os.path.splitext(os.path.basename(nome_arquivo))[0]
    base = re.sub(r"^\[[^]]+\]", "", base)
    return re.sub(r"[-_]+", " ", base).strip() or "Unidade"


def _ler_consolidado(request, form):
    """Valida cada anexo sem deixar um arquivo incompatível passar calado."""
    nomes = request.POST.getlist("unidades")
    validos, invalidos = [], []
    for indice, arquivo in enumerate(form.cleaned_data["arquivos"]):
        linhas, erro, faltando = ler_arquivo_desempenho(arquivo)
        unidade = (nomes[indice].strip() if indice < len(nomes) else "")
        unidade = (unidade or _nome_unidade(arquivo.name))[:120]
        if erro:
            invalidos.append({
                "arquivo": arquivo.name, "unidade": unidade,
                "erro": erro, "faltando": faltando,
            })
            continue
        validos.append({
            "arquivo": arquivo.name, "unidade": unidade, "linhas": linhas,
        })
    return validos, invalidos


def _opcoes_de_campanha(unidade):
    """Opções de um arquivo, com escolha automática só quando inequívoca."""
    grupos = selecao_campanhas.grupos(unidade.get("linhas") or [])
    atual = unidade.get("campanha")
    chaves = {g["chave"] for g in grupos}
    if atual not in chaves:
        com_entrega = [g for g in grupos if g["entregou"]]
        candidatos = com_entrega or grupos
        atual = candidatos[0]["chave"] if len(candidatos) == 1 else None

    opcoes = []
    for grupo in grupos:
        nomes = grupo["campanhas"]
        rotulo = " · ".join(nomes) if nomes else grupo["chave"]
        opcoes.append(dict(grupo, rotulo=rotulo,
                           selecionada=grupo["chave"] == atual))
    return opcoes, atual


def _campanha_para_conferencia(opcoes, chave):
    for opcao in opcoes:
        if opcao["chave"] == chave:
            return opcao["rotulo"]
    return chave or ""


def consolidado(request):
    """Seleção por unidade, totais, texto copiável e conferência interna."""
    dados = request.session.get(SESSAO_DESEMPENHO_CONSOLIDADO)
    if not dados:
        return redirect("desempenho")

    unidades = dados.get("unidades") or []
    erros = []
    telas = []

    # Primeiro estabelece as opções/padrões para que o POST só aceite chaves
    # que realmente pertencem àquele arquivo.
    for indice, unidade in enumerate(unidades):
        opcoes, atual = _opcoes_de_campanha(unidade)
        telas.append({"indice": indice, "dados": unidade,
                      "opcoes": opcoes, "selecionada": atual})

    if request.method == "POST":
        for tela in telas:
            indice = tela["indice"]
            unidade = tela["dados"]
            nome = request.POST.get(f"unidade_{indice}", "").strip()
            if not nome:
                erros.append(
                    f"Informe o nome da unidade do arquivo {unidade['arquivo']}.")
            else:
                unidade["unidade"] = nome[:120]

            pedida = request.POST.get(f"campanha_{indice}", "").strip()
            validas = {opcao["chave"] for opcao in tela["opcoes"]}
            if pedida not in validas:
                erros.append(
                    f"Escolha a campanha da unidade {unidade['unidade']}.")
                tela["selecionada"] = None
            else:
                unidade["campanha"] = pedida
                tela["selecionada"] = pedida

        dados["unidades"] = unidades
        request.session[SESSAO_DESEMPENHO_CONSOLIDADO] = dados
        request.session.modified = True

    # Reflete a seleção atual nas opções depois de um POST.
    for tela in telas:
        for opcao in tela["opcoes"]:
            opcao["selecionada"] = opcao["chave"] == tela["selecionada"]
        inicio, termino = periodo_do_relatorio(tela["dados"].get("linhas") or [])
        tela["periodo"] = desempenho_consolidado.periodo_texto(inicio, termino)
        tela["status"] = ("DESEMPENHO válido · campanha selecionada"
                          if tela["selecionada"] else
                          "DESEMPENHO válido · escolha a campanha")

    resultado = None
    periodos_divergentes = []
    todas_escolhidas = bool(telas) and all(t["selecionada"] for t in telas)
    if todas_escolhidas and not erros:
        preparadas = []
        for tela in telas:
            unidade = tela["dados"]
            chave = tela["selecionada"]
            preparadas.append({
                "cliente": dados["cliente"], "produto": dados["produto"],
                "unidade": unidade["unidade"], "arquivo": unidade["arquivo"],
                "campanha": _campanha_para_conferencia(tela["opcoes"], chave),
                "linhas": selecao_campanhas.filtrar(unidade["linhas"], [chave]),
            })
        try:
            resultado = desempenho_consolidado.consolidar(preparadas)
        except desempenho_consolidado.PeriodosDivergentes as exc:
            erros.append(str(exc))
            periodos_divergentes = exc.periodos
        except desempenho_consolidado.ErroDeConsolidacao as exc:
            erros.append(str(exc))

    contexto = {
        "cliente": dados["cliente"], "produto": dados["produto"],
        "unidades": telas, "n_unidades": len(telas), "erros": erros,
        "arquivos_invalidos": dados.get("arquivos_invalidos") or [],
        "periodos_divergentes": periodos_divergentes,
        "todas_escolhidas": todas_escolhidas,
        "resultado": resultado,
        "metricas": desempenho_consolidado.resumo(resultado) if resultado else [],
        "texto": desempenho_consolidado.redigir(resultado) if resultado else "",
        "conferencia": (desempenho_consolidado.conferencia(resultado)
                        if resultado else []),
    }
    return render(request, "relatorios/desempenho_consolidado.html", contexto)


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
