# -*- coding: utf-8 -*-
"""
Classificação do período e escolha do próximo passo — determinístico.

Princípio: **o CPA decide a classificação sozinho.** CPM, frequência, CTR e
estrutura de campanhas não mexem no veredito; entram só na justificativa e na
escolha do próximo passo. É o que mantém a regra "escolha UMA classificação,
não misture" e torna o resultado auditável — dado um CPA e um perfil, dá para
prever a classificação sem ler o resto.

O que muda entre um relatório e outro não é a regra, é contra o que o CPA é
comparado, em ordem de precedência:

    meta combinada  >  CPA do grupo no mesmo período  >  faixa do perfil

A meta vem do cliente; o CPA do grupo é medido (no consolidado, cada unidade
contra o total do grupo); a faixa do perfil é estimativa nossa e só entra
quando não há mais nada. Quem escolhe é `benchmarks.referencia_cpa`.

`avaliar()` é pura: sem I/O, sem relógio, sem aleatoriedade.
"""

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

from . import benchmarks, contexto as ctx
from .benchmarks import ATENCAO, BOM, OTIMO, REF_GRUPO, REF_PERFIL, Perfil

# ----------------------------------------------------------------------
# Catálogo de sinais — strings estáveis, são chave em templates.py.
# Renomear aqui obriga a renomear lá.
# ----------------------------------------------------------------------
CPA_OTIMO = "cpa_otimo"
CPA_BOM = "cpa_bom"
CPA_ATENCAO = "cpa_atencao"
SEM_RESULTADOS = "sem_resultados"
SEM_INVESTIMENTO = "sem_investimento"

AMOSTRA_PEQUENA = "amostra_pequena"
COMPARADA_AO_GRUPO = "comparada_ao_grupo"
META_CPA_INDEFINIDA = "meta_cpa_indefinida"
SEM_PERIODO_ANTERIOR = "sem_periodo_anterior"
AGUARDANDO_DADOS_DE_VENDA = "aguardando_dados_de_venda"

CAMPANHA_UNICA = "campanha_unica"
MULTIPLAS_CAMPANHAS = "multiplas_campanhas"
RESULTADOS_CONCENTRADOS = "resultados_concentrados"
VERBA_SEM_RETORNO = "verba_sem_retorno"
CAMPANHA_EM_APRENDIZADO = "campanha_em_aprendizado"

FREQUENCIA_SATURADA = "frequencia_saturada"
FREQUENCIA_BAIXA = "frequencia_baixa"
CPM_ELEVADO = "cpm_elevado"

# Sinal de CPA por classificação.
_SINAL_CPA = {OTIMO: CPA_OTIMO, BOM: CPA_BOM, ATENCAO: CPA_ATENCAO}

_CPA_FAVORAVEL = (CPA_OTIMO, CPA_BOM)


@dataclass(frozen=True)
class Avaliacao:
    classificacao: Literal["OTIMO", "BOM", "ATENCAO"]
    sinais: list = field(default_factory=list)
    motivo_principal: str = ""   # chave do sinal que determinou a classificação
    proximo_passo: str = ""      # chave da ação escolhida
    perfil: str = Perfil.VAREJO_CELULAR.value
    meta_definida: bool = False
    # Contra o que o CPA foi comparado: "meta", "grupo" ou "perfil". Muda o
    # texto (a frase cita a referência certa), nunca a regra.
    referencia: str = REF_PERFIL
    # Números que o motor calculou e que NÃO estão em nenhuma tabela do
    # relatório — é o que autoriza citá-los no texto. Chaves estáveis, valores
    # sempre serializáveis (números e listas, nunca tuplas).
    derivados: dict = field(default_factory=dict)
    # O que o operador informou na revisão, já validado (ver analysis.contexto).
    contexto: dict = field(default_factory=dict)

    def tem(self, *sinais):
        return any(s in self.sinais for s in sinais)


def avaliar(
    metricas: dict,
    *,
    perfil: str = Perfil.VAREJO_CELULAR,
    meta_cpa: Optional[float] = None,
    cpa_grupo: Optional[float] = None,
    contexto: Optional[dict] = None,
    periodo_anterior: Optional[dict] = None,
    dias_periodo: Optional[int] = None,
) -> Avaliacao:
    """
    `metricas` é o dicionário já produzido pelo parser: investimento, alcance,
    impressoes, frequencia, cpm, resultados, cpa, ctr (opcional) e campanhas
    (lista de dicts com `nome` e `resultados`).

    `cpa_grupo` é o custo por resultado do grupo no mesmo período, quando a
    conta está sendo lida dentro de um consolidado. É referência MEDIDA, e por
    isso vence a faixa estimada do perfil — só perde para a meta combinada.

    `contexto` é o que o operador informou na revisão (ver `analysis.contexto`):
    o que mudou no período, problema operacional e sua situação. Vira sinal
    como qualquer outro — justifica o veredito e escolhe o próximo passo, sem
    nunca mexer na classificação, que continua sendo do CPA.

    `periodo_anterior` faz parte do contrato desde já mas ainda não é usado —
    é aceito e ignorado, gerando `sem_periodo_anterior`. Está aqui para que a
    Etapa 3 (histórico) não mude a assinatura de quem já chama.
    """
    perfil = benchmarks.perfil_valido(perfil)
    contexto = ctx.limpar(contexto)
    meta_definida = bool(meta_cpa)
    referencia, _faixas, _divisor = benchmarks.referencia_cpa(
        perfil, meta_cpa, cpa_grupo)

    resultados = _numero(metricas.get("resultados")) or 0.0
    investimento = _numero(metricas.get("investimento"))
    cpa = _cpa(metricas, resultados)

    sinais = []

    # ---- 1. CPA: é ele, e só ele, que classifica ----
    if resultados and not investimento:
        # Houve resultado sem verba registrada: o export não trouxe a coluna de
        # investimento (ou veio zerada). O CPA daí sairia zero, e zero passaria
        # pela faixa mais barata de qualquer perfil — o motor elogiaria um
        # período que ele não conseguiu medir. Erra alto, de propósito.
        classificacao, motivo = ATENCAO, SEM_INVESTIMENTO
        sinais.append(SEM_INVESTIMENTO)
    elif cpa is None:
        # Fora do quadro de regras: sem resultado não há CPA para comparar com
        # a meta. Verba gasta sem retorno não é ÓTIMO nem BOM, então cai em
        # ATENÇÃO com motivo próprio — o texto não pode falar de "custo por
        # resultado" que não existe.
        classificacao, motivo = ATENCAO, SEM_RESULTADOS
        sinais.append(SEM_RESULTADOS)
    else:
        classificacao = benchmarks.faixa_cpa(cpa, perfil, meta_cpa, cpa_grupo)
        motivo = _SINAL_CPA[classificacao]
        sinais.append(motivo)

    # ---- 2. Único rebaixamento: volume baixo não sustenta "ótimo" ----
    if resultados and resultados < benchmarks.VOLUME_MINIMO_CONFIAVEL:
        sinais.append(AMOSTRA_PEQUENA)
        if classificacao == OTIMO:
            classificacao, motivo = BOM, AMOSTRA_PEQUENA

    # ---- 3. Sinais de apoio: explicam, não classificam ----
    cpm = _numero(metricas.get("cpm"))
    if cpm:
        sinais.append(f"cpm_{benchmarks.faixa_cpm(cpm)}")

    frequencia = _numero(metricas.get("frequencia"))
    if frequencia:
        sinais.append(
            f"frequencia_{benchmarks.faixa_frequencia(frequencia, dias_periodo)}")

    ctr = _numero(metricas.get("ctr"))
    if ctr is not None:
        sinais.append(f"ctr_{benchmarks.faixa_ctr(ctr)}")

    sinais_campanhas, derivados = _sinais_campanhas(
        metricas.get("campanhas") or [], cpa)
    sinais.extend(sinais_campanhas)

    # ---- 4. O que o operador informou: a planilha não sabe ----
    sinais.extend(ctx.sinais(contexto))

    # ---- 5. Contexto do que ainda não temos ----
    if referencia == REF_GRUPO:
        sinais.append(COMPARADA_AO_GRUPO)
    if not meta_definida:
        sinais.append(META_CPA_INDEFINIDA)
        # Não vira texto no PDF: existe para a pergunta de fechamento da
        # mensagem de WhatsApp (Etapa 4).
        sinais.append(AGUARDANDO_DADOS_DE_VENDA)
    if periodo_anterior is None:
        sinais.append(SEM_PERIODO_ANTERIOR)

    return Avaliacao(
        classificacao=classificacao,
        sinais=sinais,
        motivo_principal=motivo,
        proximo_passo=_passo_escolhido(sinais, contexto, _PROXIMO_PASSO,
                                       PASSO_PADRAO),
        perfil=perfil.value,
        meta_definida=meta_definida,
        referencia=referencia,
        derivados=derivados,
        contexto=contexto,
    )


# ----------------------------------------------------------------------
# Grupo (consolidado): o mesmo motor, um nível acima
# ----------------------------------------------------------------------
GRUPO_HOMOGENEO = "grupo_homogeneo"
UNIDADES_ACIMA = "unidades_acima_do_grupo"
UNIDADES_ABAIXO = "unidades_abaixo_do_grupo"
DISPERSAO_ALTA = "dispersao_alta"


@dataclass(frozen=True)
class UnidadeAvaliada:
    nome: str
    cpa: Optional[float] = None
    razao: Optional[float] = None       # cpa da unidade / cpa do grupo
    avaliacao: Optional[Avaliacao] = None


@dataclass(frozen=True)
class AvaliacaoGrupo:
    grupo: Avaliacao                    # o total, contra meta ou faixa do perfil
    unidades: list = field(default_factory=list)
    cpa_grupo: Optional[float] = None
    sinais: list = field(default_factory=list)   # dispersão entre as unidades
    proximo_passo: str = ""
    contexto: dict = field(default_factory=dict)

    def tem(self, *sinais):
        return any(s in self.sinais for s in sinais)

    def extremos(self):
        """(mais barata, mais cara) entre as unidades com CPA. `None` quando
        não há duas para comparar — grupo de uma unidade só não tem extremo."""
        com_cpa = [u for u in self.unidades if u.cpa]
        if len(com_cpa) < 2:
            return None, None
        ordenadas = sorted(com_cpa, key=lambda u: u.cpa)
        return ordenadas[0], ordenadas[-1]


def avaliar_grupo(
    unidades: list,
    metricas_grupo: dict,
    *,
    perfil: str = Perfil.VAREJO_CELULAR,
    meta_cpa: Optional[float] = None,
    contexto: Optional[dict] = None,
    dias_periodo: Optional[int] = None,
) -> AvaliacaoGrupo:
    """
    Avalia o consolidado. `unidades` é uma lista de {"nome", "metricas"}.

    O grupo é medido como qualquer conta — contra a meta ou a faixa do perfil.
    Cada unidade, não: ela é medida contra o CPA do próprio grupo no mesmo
    período. É a única referência do sistema que não é estimativa nossa nem
    depende de dado que ainda não temos — as outras unidades rodaram o mesmo
    intervalo, o mesmo tipo de campanha e a mesma gestão.
    """
    contexto = ctx.limpar(contexto)
    grupo = avaliar(metricas_grupo, perfil=perfil, meta_cpa=meta_cpa,
                    contexto=contexto, dias_periodo=dias_periodo)
    resultados_grupo = _numero(metricas_grupo.get("resultados")) or 0.0
    cpa_grupo = _cpa(metricas_grupo, resultados_grupo)

    avaliadas = []
    for u in unidades:
        metricas = u.get("metricas") or {}
        cpa = _cpa(metricas, _numero(metricas.get("resultados")) or 0.0)
        avaliadas.append(UnidadeAvaliada(
            nome=u.get("nome") or "",
            cpa=cpa,
            razao=cpa / cpa_grupo if cpa and cpa_grupo else None,
            # A unidade não recebe o contexto: ele descreve a operação do
            # grupo, e repeti-lo em cada praça inventaria treze problemas de
            # formulário onde há um.
            avaliacao=avaliar(metricas, perfil=perfil, meta_cpa=meta_cpa,
                              cpa_grupo=cpa_grupo, dias_periodo=dias_periodo),
        ))

    sinais = _sinais_dispersao(avaliadas) + ctx.sinais(contexto)
    return AvaliacaoGrupo(
        grupo=grupo, unidades=avaliadas, cpa_grupo=cpa_grupo, sinais=sinais,
        contexto=contexto,
        proximo_passo=_passo_escolhido(sinais, contexto, _PROXIMO_PASSO_GRUPO,
                                       PASSO_GRUPO_PADRAO))


def _sinais_dispersao(avaliadas):
    classificacoes = [u.avaliacao.classificacao for u in avaliadas
                      if u.avaliacao and u.cpa]
    if not classificacoes:
        return []

    sinais = []
    if ATENCAO in classificacoes:
        sinais.append(UNIDADES_ACIMA)
    if OTIMO in classificacoes:
        sinais.append(UNIDADES_ABAIXO)
    if not sinais:
        sinais.append(GRUPO_HOMOGENEO)

    cpas = [u.cpa for u in avaliadas if u.cpa]
    if len(cpas) > 1 and min(cpas) and max(cpas) / min(cpas) >= benchmarks.DISPERSAO_ALTA:
        sinais.append(DISPERSAO_ALTA)
    return sinais


# Grupo com praça cara E praça barata é o caso mais acionável: a solução já
# está dentro de casa. Só praça cara vira diagnóstico, não cópia.
_PROXIMO_PASSO_GRUPO = (
    (lambda s: UNIDADES_ACIMA in s and UNIDADES_ABAIXO in s,
     "levar_o_metodo_das_melhores_as_demais"),
    (lambda s: UNIDADES_ACIMA in s,
     "atacar_as_pracas_mais_caras"),
    (lambda s: UNIDADES_ABAIXO in s,
     "escalar_as_pracas_mais_baratas"),
)

PASSO_GRUPO_PADRAO = "elevar_o_patamar_do_grupo"

# Opções do select "Próximo passo" na revisão do consolidado.
PASSOS_GRUPO = tuple(dict.fromkeys(
    [chave for _casa, chave in _PROXIMO_PASSO_GRUPO] + [PASSO_GRUPO_PADRAO]))


# ----------------------------------------------------------------------
# Próximo passo — primeira regra que casar vence. A ordem É a regra:
# saturação de público antes de custo de entrega, custo de entrega antes de
# folga de público, e o CPA em atenção antes de qualquer ajuste fino.
# ----------------------------------------------------------------------
_PROXIMO_PASSO = (
    # Antes de tudo: sem verba lida não há o que decidir sobre a conta.
    (lambda s: SEM_INVESTIMENTO in s,
     "conferir_os_dados_do_periodo"),
    # Verba saindo sem retorno é mais urgente que qualquer ajuste fino: é
    # dinheiro parando de virar contato agora, não daqui a duas semanas. Mas
    # se o operador já corrigiu o gargalo, mandar corrigir de novo é contradizer
    # a própria frase anterior do texto — aí a conta volta ao trabalho de mídia.
    (lambda s: VERBA_SEM_RETORNO in s and ctx.PROBLEMA_CORRIGIDO not in s,
     "corrigir_a_captacao"),
    # Nada mudou na operação e mesmo assim o custo subiu: a causa está fora do
    # que se controla. Aqui o passo é testar, não "corrigir" o que ninguém
    # mexeu — atribuir causa seria inventar uma.
    (lambda s: ctx.NADA_MUDOU in s and CPA_ATENCAO in s,
     "testar_sem_atribuir_causa"),
    (lambda s: FREQUENCIA_SATURADA in s and _favoravel(s),
     "ampliar_publico_e_criativos"),
    (lambda s: FREQUENCIA_SATURADA in s and CPA_ATENCAO in s,
     "renovar_criativos_e_abrir_segmentacao"),
    (lambda s: CPM_ELEVADO in s,
     "testar_novos_criativos"),
    (lambda s: FREQUENCIA_BAIXA in s and _favoravel(s),
     "escalar_verba"),
    (lambda s: CPA_ATENCAO in s or SEM_RESULTADOS in s,
     "revisar_segmentacao_e_criativos"),
    (lambda s: RESULTADOS_CONCENTRADOS in s,
     "redistribuir_verba"),
    (lambda s: CAMPANHA_UNICA in s and _favoravel(s),
     "testar_segunda_estrutura"),
)

PASSO_PADRAO = "sustentar_com_testes_incrementais"

# Opções do select "Próximo passo" na revisão — a mesma lista que o motor usa.
PASSOS = tuple(dict.fromkeys(
    [chave for _casa, chave in _PROXIMO_PASSO] + [PASSO_PADRAO]))


def proximo_passo(sinais):
    for casa, chave in _PROXIMO_PASSO:
        if casa(sinais):
            return chave
    return PASSO_PADRAO


def _passo_escolhido(sinais, contexto, tabela, padrao):
    """O passo do operador vence o do motor — ele viu o que a planilha não vê.

    Valor desconhecido é ignorado em vez de estourar: um select desatualizado
    não pode impedir a geração do relatório.
    """
    validos = {chave for _casa, chave in tabela} | {padrao}
    escolhido = (contexto or {}).get("passo")
    if escolhido in validos:
        return escolhido
    for casa, chave in tabela:
        if casa(sinais):
            return chave
    return padrao


def _favoravel(sinais):
    return any(s in sinais for s in _CPA_FAVORAVEL)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _numero(valor):
    """None quando o export não trouxe a coluna. Zero continua sendo zero —
    é o que distingue 'métrica ausente' de 'métrica igual a zero'."""
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _cpa(metricas, resultados):
    """CPA informado; na falta dele, derivado do investimento. None sem
    resultados — dividir por zero aqui viraria um veredito inventado."""
    cpa = _numero(metricas.get("cpa"))
    if cpa is None:
        cpa = _numero(metricas.get("custo_resultado"))
    if cpa is None and resultados:
        investimento = _numero(metricas.get("investimento"))
        cpa = investimento / resultados if investimento else None
    return cpa if resultados else None


def _sinais_campanhas(campanhas, cpa_conta):
    """
    O que a tabela de campanhas diz e o relatório não conta: estrutura,
    concentração e — o mais caro de todos — verba que saiu sem retorno.

    Devolve `(sinais, derivados)`. Os derivados são os números calculados aqui
    que não aparecem em tabela nenhuma, e são eles que autorizam o texto a
    citar um valor.
    """
    if not campanhas:
        return [], {}

    linhas = [(_numero(c.get("resultados")) or 0.0,
               _numero(c.get("investimento")) or 0.0) for c in campanhas]
    com_investimento = [l for l in linhas if l[1] > 0]

    sinais = [CAMPANHA_UNICA] if len(campanhas) == 1 else [MULTIPLAS_CAMPANHAS]

    # Concentração: só faz sentido havendo duas estruturas de fato no ar.
    # Campanha sem verba não é uma segunda tentativa, é uma linha na planilha.
    # Quando o chamador não informa investimento nenhum, a exigência cai — não
    # dá para descartar por um dado que não foi passado.
    base = com_investimento or linhas
    resultados = [r for r, _inv in linhas]
    total = sum(resultados)
    if len(base) > 1 and total:
        if max(resultados) / total >= benchmarks.CONCENTRACAO:
            sinais.append(RESULTADOS_CONCENTRADOS)

    derivados = {}
    produtivas = [l for l in linhas if l[0] > 0]
    zeradas = [l for l in linhas if l[0] <= 0 and l[1] > 0]
    if produtivas and zeradas and cpa_conta:
        # Quem gastou menos que ~1,5 CPA ainda não teve chance: cobrar
        # resultado dela seria cobrar de quem mal entrou no leilão.
        piso = benchmarks.FATOR_APRENDIZADO * cpa_conta
        aprendizado = [l for l in zeradas if l[1] < piso]
        desperdicio = sum(inv for _res, inv in zeradas if inv >= piso)

        if aprendizado:
            sinais.append(CAMPANHA_EM_APRENDIZADO)
            derivados["verba_em_aprendizado"] = round(
                sum(inv for _res, inv in aprendizado), 2)
        if desperdicio > 0:
            sinais.append(VERBA_SEM_RETORNO)
            derivados["verba_sem_retorno"] = round(desperdicio, 2)
            faixa = _faixa_esperada(desperdicio, cpa_conta)
            if faixa:
                derivados["resultados_esperados"] = faixa
    return sinais, derivados


def _faixa_esperada(valor, cpa):
    """Quantos resultados aquela verba deveria ter trazido, como faixa —
    "3 a 4", não "3,55". O número exato daria à conta uma precisão que ela não
    tem, e o teto nunca supera o valor real para não inflar a cobrança."""
    if not cpa or valor <= 0:
        return None
    alto = math.ceil(valor / cpa)
    return [alto - 1, alto] if alto >= 2 else None
