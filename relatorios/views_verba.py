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
from decimal import Decimal, InvalidOperation

from django.shortcuts import redirect, render

from . import fechamento_verba, redator_ia, selecao_campanhas
from .forms import VerbaUploadForm
from .parser_verba import (NIVEL_CAMPANHA, NIVEL_CONJUNTO, ler_arquivo_verba,
                           montar_estruturas, periodo_relatado)

SESSAO_VERBA = "verba_apex"

# A tela 02 tem dois botões que mandam o mesmo formulário para a mesma URL:
# *Recalcular* (o padrão) e *Reescrever com IA*, que se identifica por este
# campo. Mesmo padrão de CAMPO_IA/CAMPO_CAMPANHAS em views.py.
CAMPO_IA_VERBA = "mensagem_ia"

# Desfazer a reescrita precisa ser um clique, como nas outras três frentes.
# Antes quem devolvia o texto do motor era o *Recalcular*, de tabela — ele
# descartava a redação da IA como efeito colateral de refazer os números. Com
# ele fora, a volta virou um botão explícito, que é o que ela sempre foi.
CAMPO_MOTOR_VERBA = "voltar_ao_motor"


_CAMPOS_DA_MENSAGEM_IA_VERBA = (
    ("CLIENTE", "cliente"),
    ("TIPO DE CONTRATO", "tipo_contrato"),
    ("VALOR CONTRATADO", "valor_contratado"),
    ("EQUIVALENTE DIÁRIO", "equivalente_diario"),
    ("ESTRUTURA", "estrutura"),
    ("ORÇAMENTO CONFIGURADO", "orcamento_configurado"),
    ("PERÍODO ANALISADO", "periodo_analisado"),
    ("QUANTIDADE DE DIAS", "dias_apurados"),
    ("REFERÊNCIA DO PERÍODO", "referencia_periodo"),
    ("INVESTIMENTO REALIZADO", "investimento_realizado"),
    ("STATUS CONTRATADO X CONFIGURADO", "status_configuracao"),
)


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
    """Tela 02 — os dois blocos de saída e a conferência.

    Nada de dado se edita aqui desde 30/08/2026: a base interna saiu da tela.
    Contratado errado é um envio errado, e o conserto é voltar e reenviar —
    não corrigir o número na tela que já mostra a mensagem pronta. O que muda
    nesta tela agora é só o TEXTO, e só pelo botão de IA.
    """
    dados = request.session.get(SESSAO_VERBA)
    if not dados:
        return redirect("verba")

    # A seleção vem antes do cálculo, como nas outras frentes. Aqui ela serve
    # a um caso concreto: conta que roda campanha fora do contrato — uma
    # institucional, um teste pago à parte — tinha esse gasto entrando no
    # fechamento sem ter como sair.
    #
    # Todas as caixas nascem marcadas, e essa é a diferença para as frentes de
    # texto: lá o padrão desmarca o que não entregou, mas aqui uma campanha
    # configurada que ainda não gastou continua fazendo parte do orçamento do
    # ciclo, e tirá-la sozinha mudaria o configurado sem ninguém pedir.
    _, selecao, dados = selecao_campanhas.aplicar(
        request, dados, SESSAO_VERBA,
        entrega=selecao_campanhas.ENTREGA_VERBA, padrao_completo=True)

    extra = {}
    if request.method == "POST":
        if CAMPO_IA_VERBA in request.POST:
            dados, extra = _reescrever_com_ia(request, dados)
        elif CAMPO_MOTOR_VERBA in request.POST:
            dados, extra = _voltar_ao_motor(request, dados)

    estruturas, avisos, calc = _apurar(dados)
    return render(request, "relatorios/verba_fechamento.html", dict(
        extra, **selecao,
        cliente=dados["cliente"],
        calc=calc,
        estruturas=_para_tela(estruturas),
        nivel_conjunto=dados.get("nivel") == NIVEL_CONJUNTO,
        avisos=avisos,
        mensagem=(dados.get("mensagem_ia")
                  or fechamento_verba.mensagem(calc, dados["cliente"])),
        # Mesmo sinal das outras três frentes: decide o rótulo da caixa de
        # saída e se o botão de voltar aparece.
        do_motor=not dados.get("mensagem_ia"),
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
        # O alvo do período apurado — é por ele que o trilho é escalado.
        "previsto_txt": reais(calc["previsto_periodo"]),
        # A unidade do contratado na tela sai do mesmo vocabulário que a
        # mensagem usa — duas fontes acabariam escrevendo "/mês" ao lado de
        # uma mensagem que diz "/semana".
        "unidade_contratado": fechamento_verba.vocabulario(calc)["unidade"],
        "configurado_txt": reais(calc["contratado_diario"]),
        # As linhas do combinado na lateral, na mesma ordem da mensagem, e
        # prontas aqui porque a segunda some no contrato já cotado por dia.
        "combinado": _combinado(calc),
        "gasto_txt": reais(calc["gasto"]),
        "ritmo_txt": reais(calc["ritmo_real"]),
        "desvio_txt": ("+" if desvio and desvio > 0 else "") + pct(desvio),
        "trilho": _trilho(calc),
        # O intervalo que o export declara — e que agora É o período apurado.
        # Fica escrito na tela de propósito: é a única defesa contra um
        # recorte mal escolhido no Gerenciador, porque a aplicação não tem
        # como saber qual intervalo o operador queria.
        "relatado_txt": f"{calc['desde']:%d/%m/%Y} a {calc['ate']:%d/%m/%Y}",
    }


def _combinado(calc):
    """As linhas do combinado na lateral: `[{rotulo, valor}]`.

    Espelham a mensagem: o contratado na unidade em que foi combinado, a
    diária que sai dele (só quando há o que converter) e o previsto dos dias
    apurados. Ler "Contratado R$ 4.650/mês" numa tela cujo contrato é diário
    obriga a conferir de cabeça se 4.650 ÷ 31 dá 150.
    """
    reais = fechamento_verba.reais
    dias = calc["dias_apurados"]
    linhas = [{"rotulo": "Contratado",
               "valor": (f"{reais(calc['contratado_unidade'])}/"
                         f"{fechamento_verba.vocabulario(calc)['unidade']}")}]
    if calc.get("periodo") != fechamento_verba.CICLO_DIARIO:
        linhas.append({"rotulo": "Equivale a",
                       "valor": f"{reais(calc['contratado_diario'])}/dia"})
    linhas.append({
        "rotulo": "Previsto",
        "valor": (f"{reais(calc['previsto_periodo'])} · {dias} "
                  f"dia{'s' if dias != 1 else ''}")})
    return linhas


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
    """As duas posições do trilho, em % da própria pista.

    Eram três: gasto, projeção e alvo. A projeção saiu em 31/08/2026 junto com
    a janela futura — sem dia restante não há o que projetar, e a pista passou
    a comparar o gasto com o previsto dos dias apurados.

    A pista é escalada pelo MAIOR entre previsto e gasto, e não pelo previsto:
    assim um gasto que estoura o combinado aparece passando da marca em vez de
    ser cortado na borda — que é justamente o caso que o operador precisa ver
    de longe.

    As posições saem daqui como **texto com o `%` colado**, e não como float:
    a locale do projeto é pt-BR, e o template localizaria `74.75` para
    `74,75` — CSS inválido, que o navegador descarta em silêncio deixando a
    barra vazia. Comprimento de CSS não é número de ler.
    """
    previsto = calc["previsto_periodo"] or 0.0
    gasto = calc["gasto"] or 0.0
    escala = max(previsto, gasto)
    if not escala:
        return None

    def posicao(valor):
        return f"{(valor or 0.0) / escala * 100:.2f}%"

    return {
        "gasto": posicao(gasto),
        "alvo": posicao(previsto),
        "tom": _TOM_DO_STATUS.get(calc["status"], "desviando"),
    }


def _apurar(dados):
    """`(estruturas, avisos, calc)` a partir do que está na sessão.

    Refeito a cada renderização, e de propósito: é barato (um laço sobre as
    linhas), e assim não existe estado calculado que possa discordar da base
    interna que o operador acabou de corrigir.
    """
    ate = date.fromisoformat(dados["ate"])
    linhas = selecao_campanhas.filtrar(dados["linhas"], dados.get("campanhas"))
    # `dias_do_mes` aqui é do PARSER, não do fechamento: é por ele que um
    # orçamento vitalício sem data de término vira equivalente diário. Essa
    # conta não tem relação com o ciclo do contrato — um vitalício de R$ 1.000
    # não passa a durar sete dias porque o cliente fecha por semana.
    estruturas, avisos = montar_estruturas(
        linhas, dados.get("nivel") or NIVEL_CAMPANHA,
        fechamento_verba.dias_do_mes(ate))
    calc = fechamento_verba.calcular(
        estruturas, dados.get("contratado_ciclo"),
        periodo=dados.get("periodo") or fechamento_verba.CICLO_MENSAL,
        inicio_relatorio=date.fromisoformat(dados["desde"]),
        termino_relatorio=ate)
    return estruturas, avisos, calc


def _voltar_ao_motor(request, dados):
    """Descarta a reescrita e devolve a mensagem do cálculo.

    Era efeito colateral do *Recalcular*, que saiu junto com a base interna.
    Virou botão explícito — que é o que ela sempre foi.
    """
    dados.pop("mensagem_ia", None)
    request.session[SESSAO_VERBA] = dados
    request.session.modified = True
    return dados, {"restaurado": True}


def _decimal_finito(valor):
    """`Decimal` para comparação financeira, ou `None` para valor ausente."""
    if valor is None or valor == "":
        return None
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return numero if numero.is_finite() else None


def _orcamento_configurado_diario(estruturas):
    """Soma operacional do orçamento diário configurado nas estruturas ativas.

    O parser já converte orçamento vitalício para equivalente diário e já
    identifica o nível correto (campanha no CBO, conjunto no ABO). Esta leitura
    serve somente ao contexto da reescrita: não entra nas fórmulas nem altera o
    texto determinístico do fechamento.
    """
    valores = []
    for estrutura in estruturas:
        if not estrutura.get("ativa"):
            continue
        valor = _decimal_finito(estrutura.get("orcamento"))
        if valor is not None:
            valores.append(valor)
    return sum(valores, Decimal("0")) if valores else None


def _status_configuracao(contratado_diario, configurado_diario):
    """Classificação determinística da configuração que orienta a pergunta.

    A igualdade acompanha a precisão exibida pela frente (`reais`, sem
    centavos). Assim, a IA nunca recebe dois valores visualmente iguais junto
    de um status de divergência por fração não mostrada ao cliente.
    """
    contratado = _decimal_finito(contratado_diario)
    configurado = _decimal_finito(configurado_diario)
    if contratado is None or configurado is None:
        return None
    if fechamento_verba.reais(contratado) == fechamento_verba.reais(configurado):
        return "aligned"
    return ("configured_below" if configurado < contratado
            else "configured_above")


def _valor_presente_na_ia(valor):
    """Impede que ausência técnica vire texto (`None`, `NaN`, `undefined`)."""
    if valor is None:
        return False
    if isinstance(valor, (float, Decimal)):
        numero = _decimal_finito(valor)
        if numero is None:
            return False
    texto = str(valor).strip()
    return bool(texto) and texto.lower() not in {
        "none", "nan", "null", "undefined", "—",
    }


def _payload_ia_verba(dados, estruturas, calc):
    """Fatos financeiros validados para a IA, sem linhas do XLSX."""
    unidade = fechamento_verba.vocabulario(calc)["unidade"]
    contratado = calc.get("contratado_unidade")
    contratado_diario = calc.get("contratado_diario")
    configurado_diario = _orcamento_configurado_diario(estruturas)

    payload = {
        "cliente": dados.get("cliente"),
        "tipo_contrato": calc.get("periodo"),
        "valor_contratado": (
            f"{fechamento_verba.reais(contratado)}/{unidade}"
            if contratado is not None else None),
        "equivalente_diario": (
            f"{fechamento_verba.reais(contratado_diario)}/dia"
            if contratado_diario is not None else None),
        "estrutura": str(dados.get("estrutura") or "").upper(),
        "orcamento_configurado": (
            f"{fechamento_verba.reais(configurado_diario)}/dia"
            if configurado_diario is not None else None),
        "periodo_analisado": (
            f"{calc['desde']:%d/%m} a {calc['ate']:%d/%m}"
            if calc.get("desde") and calc.get("ate") else None),
        "dias_apurados": calc.get("dias_apurados"),
        "referencia_periodo": (
            fechamento_verba.reais(calc.get("previsto_periodo"))
            if calc.get("previsto_periodo") is not None else None),
        "investimento_realizado": (
            fechamento_verba.reais(calc.get("gasto"))
            if calc.get("gasto") is not None else None),
        "status_configuracao": _status_configuracao(
            contratado_diario, configurado_diario),
    }
    return {chave: valor for chave, valor in payload.items()
            if _valor_presente_na_ia(valor)}


def _mensagem_usuario_ia_verba(texto, payload):
    """User Prompt próprio: dados estruturados primeiro, texto como apoio."""
    secoes = ["DADOS FINANCEIROS E OPERACIONAIS VALIDADOS PELA APLICAÇÃO"]
    for titulo, chave in _CAMPOS_DA_MENSAGEM_IA_VERBA:
        valor = payload.get(chave)
        if _valor_presente_na_ia(valor):
            secoes.append(f"{titulo}\n{valor}")

    status = payload.get("status_configuracao")
    if status == "aligned":
        direcao = ("Finalize perguntando se podemos manter a configuração "
                   "atual no próximo período.")
    elif status in {"configured_below", "configured_above"}:
        direcao = ("Finalize perguntando se podemos ajustar o orçamento "
                   "configurado para o valor contratado.")
    else:
        direcao = ("Como não há status de comparação disponível, não declare "
                   "alinhamento ou divergência e faça uma pergunta neutra "
                   "sobre a continuidade da configuração.")

    secoes.extend((
        "TEXTO DETERMINÍSTICO — REFERÊNCIA FACTUAL SECUNDÁRIA\n" + texto,
        "TAREFA\nProduza uma nova mensagem para o cliente. Use os dados "
        "estruturados como fonte principal e não faça uma paráfrase linha por "
        "linha. Explique claramente a relação entre orçamento configurado, "
        "referência do período e investimento realizado. Não trate a "
        "diferença entre referência e investimento como erro. " + direcao,
    ))
    return "\n\n".join(secoes)


def _fonte_numerica_ia_verba(texto, payload):
    """Autoriza na guarda comum os números estruturados além do texto base."""
    return "\n".join([texto] + [str(valor) for valor in payload.values()
                                if _valor_presente_na_ia(valor)])


def _validar_reescrita_verba(texto, payload):
    blocos = redator_ia._blocos(texto)
    if not blocos or blocos[0] != "*Verba*":
        raise redator_ia.ErroDeIA(
            "A reescrita não começou com *Verba*. Mantida a mensagem do "
            "cálculo.", "formato")

    # Os quatro fatos que sustentam a comunicação financeira não podem sumir
    # na melhora de redação. Campo ausente no XLSX/contexto não é cobrado.
    fatos = {
        "valor_contratado": "contrat",
        "orcamento_configurado": "configur",
        "periodo_analisado": "period",
        "referencia_periodo": "referenc",
        "investimento_realizado": "invest",
    }
    linhas = [redator_ia._sem_acento(linha) for linha in texto.splitlines()
              if linha.strip()]
    for chave, radical in fatos.items():
        valor = payload.get(chave)
        valor_normal = redator_ia._sem_acento(str(valor or ""))
        presente = any(valor_normal in linha and radical in linha
                       for linha in linhas)
        if _valor_presente_na_ia(valor) and not presente:
            raise redator_ia.ErroDeIA(
                f"A reescrita omitiu {chave.replace('_', ' ')}. Mantida a "
                "mensagem do cálculo.", "formato")
    return texto


def _reescrever_com_ia(request, dados):
    """Pede ao modelo outra redação da mesma mensagem.

    Falhar aqui não custa nada: a mensagem do motor continua na tela e o erro
    vira aviso. É o mesmo contrato das outras três frentes.
    """
    estruturas, _, calc = _apurar(dados)
    original = fechamento_verba.mensagem(calc, dados["cliente"])
    payload = _payload_ia_verba(dados, estruturas, calc)
    mensagem_usuario = _mensagem_usuario_ia_verba(original, payload)
    try:
        texto = redator_ia.reescrever(
            _fonte_numerica_ia_verba(original, payload),
            payload,
            redator_ia.PROMPT_REESCRITA_VERBA,
            # Além das métricas de performance, a guarda recusa linguagem que
            # transformaria oscilação de entrega em erro ou causa inventada.
            proibidos=(redator_ia.TERMOS_DE_PERFORMANCE
                       + redator_ia.TERMOS_INDEVIDOS_VERBA),
            max_linhas=redator_ia.LINHAS_MAXIMAS_VERBA,
            termina_em_pergunta=True,
            mensagem_usuario=mensagem_usuario)
        texto = _validar_reescrita_verba(texto, payload)
    except redator_ia.ErroDeIA as e:
        definitivo = e.motivo in redator_ia.DEFINITIVOS
        return dados, {"erro_ia": str(e),
                       "erro_ia_definitivo": definitivo,
                       "ia_disponivel": redator_ia.disponivel() and not definitivo}

    dados["mensagem_ia"] = texto
    request.session[SESSAO_VERBA] = dados
    request.session.modified = True
    return dados, {"mensagem_ia_gerada": True, "ia_disponivel": True}
