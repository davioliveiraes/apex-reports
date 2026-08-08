# -*- coding: utf-8 -*-
"""
Vocabulário do "Contexto do período" — o que o operador sabe e a planilha não.

O export diz que o custo subiu; não diz que o formulário quebrou na terça. Este
módulo é a lista fechada do que dá para informar, e é fonte única: o formulário
tira dele as opções da tela e `rules.avaliar` tira dele os sinais. Acrescentar
uma opção é acrescentar uma entrada aqui — nada de editar select e motor.

Lista fechada, e não campo de texto livre, por dois motivos: o texto livre já
existe (o textarea da análise é editável), e opção fechada vira sinal, que é o
que o motor sabe combinar com o resto.

Todos os campos são opcionais. Vazio significa "não informado", que é diferente
de "nada aconteceu" — `NADA_MUDOU` e `SEM_PROBLEMA` são afirmações do operador
e geram sinal; a ausência não gera nada e o texto sai como saía antes.
"""

# ---- O que mudou no período ----
NADA_MUDOU = "nada_mudou"
MUDOU_CRIATIVOS = "mudou_criativos"
MUDOU_PUBLICO = "mudou_publico"
MUDOU_CAPTACAO = "mudou_captacao"
MUDOU_ORCAMENTO = "mudou_orcamento"

MUDANCAS = [
    ("", "Não informado"),
    (NADA_MUDOU, "Nada mudou"),
    (MUDOU_CRIATIVOS, "Criativos novos"),
    (MUDOU_PUBLICO, "Público novo"),
    (MUDOU_CAPTACAO, "Forma de captação alterada"),
    (MUDOU_ORCAMENTO, "Orçamento alterado"),
]

# ---- Problema operacional ----
SEM_PROBLEMA = "sem_problema"
PROBLEMA_FORMULARIO = "problema_formulario"
PROBLEMA_ATENDIMENTO = "problema_atendimento"
PROBLEMA_SITE = "problema_site"
PROBLEMA_ESTOQUE = "problema_estoque"

PROBLEMAS = [
    ("", "Não informado"),
    (SEM_PROBLEMA, "Nenhum"),
    (PROBLEMA_FORMULARIO, "Formulário ou cadastro"),
    (PROBLEMA_ATENDIMENTO, "Atendimento"),
    (PROBLEMA_SITE, "Site ou checkout"),
    (PROBLEMA_ESTOQUE, "Estoque"),
]

# Problemas de verdade — "nenhum" e "não informado" ficam de fora.
PROBLEMAS_REAIS = frozenset((PROBLEMA_FORMULARIO, PROBLEMA_ATENDIMENTO,
                             PROBLEMA_SITE, PROBLEMA_ESTOQUE))

# ---- Situação do problema ----
PROBLEMA_CORRIGIDO = "problema_corrigido"
PROBLEMA_EM_CORRECAO = "problema_em_correcao"
PROBLEMA_ABERTO = "problema_aberto"

SITUACOES = [
    (PROBLEMA_CORRIGIDO, "Já corrigido"),
    (PROBLEMA_EM_CORRECAO, "Em correção"),
    (PROBLEMA_ABERTO, "Ainda aberto"),
]

# Chaves aceitas em `rules.avaliar(contexto=...)`.
CAMPOS = ("mudanca", "problema", "situacao", "passo")


def sinais(contexto):
    """Os sinais que o contexto informado gera, sem inventar nada.

    Campo vazio não vira sinal. `situacao` só conta havendo problema de fato:
    "já corrigido" sem problema declarado não descreve nada.
    """
    if not contexto:
        return []

    fora = [contexto.get("mudanca"), contexto.get("problema")]
    saida = [v for v in fora if v]
    if contexto.get("problema") in PROBLEMAS_REAIS and contexto.get("situacao"):
        saida.append(contexto["situacao"])
    return saida


def problema(contexto):
    """O problema operacional declarado, ou "" quando não há um."""
    valor = (contexto or {}).get("problema")
    return valor if valor in PROBLEMAS_REAIS else ""


def limpar(contexto):
    """Só as chaves conhecidas, com valores conhecidos — o que vem do POST não
    entra no motor sem passar por aqui."""
    if not contexto:
        return {}
    validos = {
        "mudanca": {v for v, _r in MUDANCAS if v},
        "problema": {v for v, _r in PROBLEMAS if v},
        "situacao": {v for v, _r in SITUACOES},
    }
    limpo = {}
    for campo in CAMPOS:
        valor = (contexto.get(campo) or "").strip()
        if campo == "passo":
            if valor:
                limpo[campo] = valor
        elif valor in validos[campo]:
            limpo[campo] = valor
    return limpo
