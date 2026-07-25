# -*- coding: utf-8 -*-
"""
Registro central das métricas comparáveis entre contas — modo Indicador Único.

FONTE ÚNICA DE VERDADE: o seletor da UI (forms.UploadForm.metrica) e o motor
de agregação (gerador_indicador) leem daqui. Acrescentar uma métrica nova é
acrescentar UMA entrada ao dicionário — nenhuma view, template ou regra de
agregação precisa mudar.

Campos de cada entrada:
    label      rótulo exibido na UI e no PDF
    unidade    "R$" | "%" | "" (decimal puro) | substantivo contado
    estagio    topo | meio | fundo — agrupa o seletor como o funil do relatório
    agregacao  "soma"       aditiva: total do grupo = soma das contas
               "recalculo"  razão: total = `formula` aplicada sobre os brutos
                            SOMADOS. Nunca média das médias — isso distorce o
                            total quando as contas têm volumes diferentes.
    formula    só em "recalculo": expressão sobre outras chaves deste registro
               (que precisam ser, elas próprias, de agregação "soma")
    melhor     "maior" | "menor" | None (sem ranking → ordem de envio)
    fonte      chave equivalente em dados["_num"] do parser; para as métricas
               de soma é também a chave da coluna em parser_xlsx._COLUNAS, o
               que permite detectar automaticamente dado indisponível
"""

import re

from .parser_xlsx import _fmt_dec, _fmt_int, _fmt_moeda

METRICS_REGISTRY = {
    "investimento_total": {
        "label": "Investimento Total", "unidade": "R$", "estagio": "topo",
        "agregacao": "soma", "melhor": None, "fonte": "investimento"},
    "alcance": {
        "label": "Alcance", "unidade": "pessoas", "estagio": "topo",
        "agregacao": "soma", "melhor": None, "fonte": "alcance"},
    "impressoes": {
        "label": "Impressões", "unidade": "visualizações", "estagio": "topo",
        "agregacao": "soma", "melhor": None, "fonte": "impressoes"},
    "frequencia": {
        "label": "Frequência", "unidade": "", "estagio": "topo",
        "agregacao": "recalculo", "formula": "impressoes / alcance",
        "melhor": None, "fonte": "frequencia"},
    "cpm": {
        "label": "CPM", "unidade": "R$", "estagio": "topo",
        "agregacao": "recalculo",
        "formula": "investimento_total / impressoes * 1000",
        "melhor": "menor", "fonte": "cpm"},
    "cliques_link": {
        "label": "Cliques no Link", "unidade": "cliques", "estagio": "meio",
        "agregacao": "soma", "melhor": "maior", "fonte": "cliques"},
    "ctr": {
        "label": "CTR", "unidade": "%", "estagio": "meio",
        "agregacao": "recalculo", "formula": "cliques_link / impressoes * 100",
        "melhor": "maior", "fonte": "ctr"},
    "cpc": {
        "label": "CPC", "unidade": "R$", "estagio": "meio",
        "agregacao": "recalculo", "formula": "investimento_total / cliques_link",
        "melhor": "menor", "fonte": "cpc"},
    "conversas_iniciadas": {
        "label": "Conversas Iniciadas", "unidade": "conversas", "estagio": "fundo",
        "agregacao": "soma", "melhor": "maior", "fonte": "resultados"},
    "cpa": {
        "label": "Custo por Resultado (CPA)", "unidade": "R$", "estagio": "fundo",
        "agregacao": "recalculo",
        "formula": "investimento_total / conversas_iniciadas",
        "melhor": "menor", "fonte": "custo_resultado"},
    "taxa_conversao": {
        "label": "Taxa de Conversão", "unidade": "%", "estagio": "fundo",
        "agregacao": "recalculo",
        "formula": "conversas_iniciadas / cliques_link * 100",
        "melhor": "maior", "fonte": "taxa_conversao"},
}

# Rótulos dos grupos do seletor — mesma ordem/nomenclatura do funil do relatório
ESTAGIOS = [
    ("topo", "Topo de Funil — Atração"),
    ("meio", "Meio de Funil — Interesse e Clique"),
    ("fundo", "Fundo de Funil — Conversão"),
]

# Métricas cuja leitura depende do objetivo da campanha: comparar unidades com
# indicadores de resultado diferentes pode não fazer sentido.
SENSIVEIS_AO_OBJETIVO = ("cpa", "taxa_conversao")


def opcoes_agrupadas():
    """Choices do seletor, agrupadas por estágio: [(grupo, [(chave, label)])]."""
    return [
        (rotulo, [(chave, m["label"]) for chave, m in METRICS_REGISTRY.items()
                  if m["estagio"] == estagio])
        for estagio, rotulo in ESTAGIOS
    ]


def _referencias(formula):
    """Chaves do registro citadas numa fórmula."""
    return [t for t in re.findall(r"[a-z_]+", formula) if t in METRICS_REGISTRY]


def componentes(chave):
    """
    Métricas de soma das quais `chave` depende — ela mesma, se for aditiva;
    senão, as citadas na fórmula (resolvidas recursivamente).
    """
    m = METRICS_REGISTRY[chave]
    if m["agregacao"] == "soma":
        return {chave}
    conjunto = set()
    for ref in _referencias(m["formula"]):
        conjunto |= componentes(ref)
    return conjunto


def disponivel(chave, colunas):
    """
    True se o export trouxe todas as colunas de que a métrica depende.
    `colunas`: dados["_colunas"] do parser (chaves de coluna reconhecidas).
    """
    colunas = set(colunas or ())
    return all(METRICS_REGISTRY[c]["fonte"] in colunas for c in componentes(chave))


def valor_conta(chave, num):
    """
    Valor da métrica numa conta. Usa o valor pronto do `_num` do parser quando
    existe; para métricas de razão sem equivalente lá, aplica a fórmula sobre
    os componentes da própria conta — assim uma métrica de razão nova entra no
    registro sem exigir nada do parser (uma métrica de soma, ao contrário,
    precisa de uma coluna que o parser já leia).
    """
    metrica = METRICS_REGISTRY[chave]
    fonte = metrica.get("fonte")
    valor = (num or {}).get(fonte) if fonte else None
    if valor is not None or metrica["agregacao"] == "soma":
        return valor
    return _avaliar(metrica["formula"],
                    {ref: valor_conta(ref, num)
                     for ref in _referencias(metrica["formula"])})


def _avaliar(formula, valores):
    """
    Aplica a fórmula do registro sobre `valores` (dict chave→número).

    `formula` é constante do próprio módulo, nunca entrada de usuário — daí o
    eval com namespace fechado. Componente ausente ou divisão por zero → None.
    """
    if any(valores.get(k) is None for k in _referencias(formula)):
        return None
    try:
        return eval(formula, {"__builtins__": {}}, dict(valores))
    except ZeroDivisionError:
        return None


def total_geral(chave, nums):
    """
    Total do grupo para a métrica, a partir dos `_num` das contas com dado
    disponível. Soma direta quando aditiva; para métricas de razão, recalcula
    a fórmula sobre os componentes brutos somados.
    """
    if not nums:
        return None
    metrica = METRICS_REGISTRY[chave]
    if metrica["agregacao"] == "soma":
        valores = [v for v in (valor_conta(chave, n) for n in nums) if v is not None]
        return sum(valores) if valores else None
    # Cada referência da fórmula é resolvida no nível do GRUPO (soma dos brutos
    # ou, se ela própria for de razão, novo recálculo) — nunca média das médias.
    return _avaliar(metrica["formula"],
                    {ref: total_geral(ref, nums)
                     for ref in _referencias(metrica["formula"])})


def formatar(chave, valor):
    """Formata o valor no padrão brasileiro conforme a unidade da métrica."""
    if valor is None:
        return "—"
    unidade = METRICS_REGISTRY[chave]["unidade"]
    if unidade == "R$":
        return _fmt_moeda(valor)
    if unidade == "%":
        return f"{_fmt_dec(valor)}%"
    if unidade == "":
        return _fmt_dec(valor)
    return _fmt_int(valor)


def rotulo_coluna(chave):
    """
    Cabeçalho da coluna de valor. A unidade contada entra entre parênteses
    ("Alcance (pessoas)"), exceto quando o rótulo já a contém — evita
    "Conversas Iniciadas (conversas)". R$ e % já aparecem no próprio valor.
    """
    m = METRICS_REGISTRY[chave]
    unidade = m["unidade"]
    if (unidade and unidade not in ("R$", "%")
            and unidade.lower() not in m["label"].lower()):
        return f"{m['label']} ({unidade})"
    return m["label"]


def ordenar(linhas, chave):
    """
    Ordena pela métrica conforme `melhor`: maior → decrescente, menor →
    crescente, None → ordem de envio. Contas sem dado vão sempre para o fim.
    """
    melhor = METRICS_REGISTRY[chave]["melhor"]
    if not melhor:
        return list(linhas)
    com_dado = [l for l in linhas if l["valor"] is not None]
    sem_dado = [l for l in linhas if l["valor"] is None]
    com_dado.sort(key=lambda l: l["valor"], reverse=(melhor == "maior"))
    return com_dado + sem_dado
