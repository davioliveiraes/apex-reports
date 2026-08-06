# -*- coding: utf-8 -*-
"""
Faixas de referência do motor de análise — uso INTERNO, nunca no relatório.

Não confundir com `relatorios/benchmarks.py`: aquele classifica CTR/CPC/CPM/
taxa de conversão/frequência para as leituras dos cards do funil; este define
as faixas de CPA que decidem a classificação do período (ÓTIMO / BOM /
ATENÇÃO) e as faixas de apoio que apenas justificam o veredito.

VALORES CALIBRÁVEIS. Estimados para varejo local brasileiro no Meta e
ancorados num caso real (CPA R$ 1,87 · CPM R$ 11,13 · frequência 3,56, conta
DoctorCell). Não são benchmark de mercado verificado — devem ser ajustados
conforme o histórico acumular. Sinais de descalibração: se quase tudo sair
ÓTIMO, apertar o limite superior da faixa; se muita conta cair em ATENÇÃO sem
concordância, afrouxar.
"""

from enum import Enum


class Perfil(str, Enum):
    VAREJO_CELULAR = "varejo_celular"     # boleto, seminovos, assistência
    TIM_REGIONAL = "tim_regional"
    RECRUTAMENTO = "recrutamento"         # Special Ad Category Emprego
    CURSO = "curso"                       # infoproduto
    B2B = "b2b"                           # conversas qualificadas


PERFIL_PADRAO = Perfil.VAREJO_CELULAR

# Classificações do período
OTIMO, BOM, ATENCAO = "OTIMO", "BOM", "ATENCAO"

# (teto do ÓTIMO, teto do BOM) em R$ por resultado. Acima do segundo: ATENÇÃO.
# Usadas SÓ quando a conta não tem meta de CPA definida — são a meta
# substituta, e saem de cena assim que `meta_cpa` chega.
CPA_POR_PERFIL = {
    Perfil.VAREJO_CELULAR: (4.00, 9.00),
    Perfil.TIM_REGIONAL: (5.00, 11.00),
    Perfil.RECRUTAMENTO: (6.00, 13.00),
    Perfil.CURSO: (8.00, 18.00),
    Perfil.B2B: (15.00, 35.00),
}

# Com meta definida a faixa fixa é descartada e vale a razão cpa / meta_cpa.
CPA_RAZAO_META = (0.90, 1.15)

# No consolidado, cada unidade é medida contra o CPA do grupo — referência
# medida, não estimada. Mais tolerante que a meta: a média do grupo é puxada
# pelas próprias unidades, então ficar um pouco acima dela não é falha.
CPA_RAZAO_GRUPO = (0.90, 1.20)

# Precedência da referência do CPA, da mais forte para a mais fraca. A meta é
# combinada com o cliente; o grupo é medido no mesmo período; o perfil é
# estimativa nossa e só entra quando não há mais nada.
REF_META, REF_GRUPO, REF_PERFIL = "meta", "grupo", "perfil"

# --- Faixas de apoio: NÃO classificam o período, apenas o explicam ---

# R$ por mil impressões
CPM_FAIXAS = ((12.0, "muito_competitivo"), (20.0, "competitivo"),
              (35.0, "normal"), (None, "elevado"))

# Frequência numa janela mensal. Abaixo do primeiro limite é "baixa" — repare
# que aqui o corte é estrito (1,5 já conta como saudável).
FREQUENCIA_FAIXAS = ((1.5, "baixa"), (2.5, "saudavel"),
                     (3.5, "elevada"), (None, "saturada"))

# Período curto comprime a janela: frequência 3,0 em 7 dias é muito mais
# agressiva que em 30. O ajuste é contínuo — limite × dias / 30 para qualquer
# período abaixo de 30 dias. Já foi um degrau em 14 dias, e o degrau fazia um
# dia a mais ou a menos virar o veredito de frequência do avesso: com 14 dias
# valia 3,5 para "saturada" e com 13 valia 1,52.
DIAS_JANELA = 30

# % de cliques. Opcional: export sem a coluna não é erro.
CTR_FAIXAS = ((0.8, "baixo"), (2.0, "normal"), (None, "alto"))

# Abaixo disso a amostra não sustenta afirmação forte.
VOLUME_MINIMO_CONFIAVEL = 30

# Fração dos resultados numa única campanha que caracteriza concentração.
CONCENTRACAO = 0.80

# Razão entre o CPA mais caro e o mais barato do grupo a partir da qual as
# unidades deixam de ser variação normal e viram dois grupos diferentes.
DISPERSAO_ALTA = 2.0

# Margem para comparação de fronteira. Sem ela, um CPA de 9,00 vindo de uma
# divisão (899.99 / 100) cairia em ATENÇÃO por resíduo de ponto flutuante.
_EPS = 1e-9


def perfil_valido(perfil):
    """Perfil como enum. Valor desconhecido cai no padrão em vez de estourar:
    um perfil digitado errado não pode impedir a geração do relatório."""
    if isinstance(perfil, Perfil):
        return perfil
    try:
        return Perfil(str(perfil))
    except ValueError:
        return PERFIL_PADRAO


def _classificar(valor, faixas):
    """Primeiro limite que o valor não ultrapassa. `None` é o limite aberto."""
    for limite, nome in faixas:
        if limite is None or valor <= limite + _EPS:
            return nome
    return faixas[-1][1]


def referencia_cpa(perfil=PERFIL_PADRAO, meta_cpa=None, cpa_grupo=None):
    """Contra o que este CPA vai ser comparado, e por qual regra.

    Devolve `(origem, faixas, divisor)`. Com divisor, o que entra na faixa é a
    razão cpa / divisor; sem ele, o próprio CPA em reais. A ordem é a
    precedência: meta combinada > CPA do grupo no mesmo período > faixa
    estimada do perfil.
    """
    if meta_cpa:
        return REF_META, CPA_RAZAO_META, meta_cpa
    if cpa_grupo:
        return REF_GRUPO, CPA_RAZAO_GRUPO, cpa_grupo
    return REF_PERFIL, CPA_POR_PERFIL[perfil_valido(perfil)], None


def faixa_cpa(cpa, perfil=PERFIL_PADRAO, meta_cpa=None, cpa_grupo=None):
    """OTIMO / BOM / ATENCAO segundo a referência de maior precedência."""
    _origem, (otimo, bom), divisor = referencia_cpa(perfil, meta_cpa, cpa_grupo)
    valor = cpa / divisor if divisor else cpa
    if valor <= otimo + _EPS:
        return OTIMO
    if valor <= bom + _EPS:
        return BOM
    return ATENCAO


def faixa_cpm(cpm):
    return _classificar(cpm, CPM_FAIXAS)


def faixa_frequencia(frequencia, dias=None):
    if dias and dias < DIAS_JANELA:
        fator = dias / DIAS_JANELA
        faixas = tuple((None if lim is None else lim * fator, nome)
                       for lim, nome in FREQUENCIA_FAIXAS)
    else:
        faixas = FREQUENCIA_FAIXAS
    # O corte da faixa "baixa" é estrito: exatamente 1,5 já é saudável.
    primeiro, nome_baixa = faixas[0]
    if frequencia < primeiro - _EPS:
        return nome_baixa
    return _classificar(frequencia, faixas[1:])


def faixa_ctr(ctr):
    # Mesmo corte estrito da frequência: 0,8 exato já é normal.
    primeiro, nome_baixo = CTR_FAIXAS[0]
    if ctr < primeiro - _EPS:
        return nome_baixo
    return _classificar(ctr, CTR_FAIXAS[1:])
