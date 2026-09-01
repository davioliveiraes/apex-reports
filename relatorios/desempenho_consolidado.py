# -*- coding: utf-8 -*-
"""Consolidação de 2 a 20 contas do preset DESEMPENHO.

Este módulo recebe apenas as linhas das campanhas que o operador escolheu em
cada arquivo. Ler XLSX e decidir a campanha continuam sendo responsabilidades
do parser e da view já existentes; aqui ficam somente as regras matemáticas e
a saída determinística do modo Consolidado.

Duas regras merecem ficar explícitas junto do cálculo:

* alcance é uma soma operacional dos alcances reportados por conta. O export
  não permite deduplicar uma pessoa alcançada por contas diferentes;
* custo por conversa é ponderado pelo volume de conversas e pelos custos por
  conversa reportados nos exports. Nunca é a média simples entre unidades.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from . import analise_desempenho
from .analysis.numeros import decimal, inteiro, moeda
from .parser_desempenho import periodo_do_relatorio

MIN_UNIDADES = 2
MAX_UNIDADES = 20


class ErroDeConsolidacao(ValueError):
    """Entrada que não pode produzir um consolidado confiável."""


class PeriodosDivergentes(ErroDeConsolidacao):
    """Os exports não cobrem exatamente o mesmo intervalo."""

    def __init__(self, periodos):
        self.periodos = periodos
        super().__init__("Os arquivos possuem períodos diferentes.")


def _numero(valor, *, opcional=False):
    """Decimal finito; células ausentes viram zero ou ``None``."""
    if valor is None or valor == "":
        return None if opcional else Decimal("0")
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None if opcional else Decimal("0")
    if not numero.is_finite():
        return None if opcional else Decimal("0")
    return numero


def _somar(linhas, campo):
    return sum((_numero(linha.get(campo)) for linha in linhas), Decimal("0"))


def _custo_por_conversa(linhas):
    """Custo reportado ponderado pelas conversas das linhas selecionadas.

    Se alguma linha com conversas não trouxer custo, o valor deixa de ser
    calculável: completar o numerador com zero anunciaria um custo artificial.
    """
    conversas = Decimal("0")
    custo_estimado = Decimal("0")
    for linha in linhas:
        volume = _numero(linha.get("conversas"))
        if not volume:
            continue
        custo = _numero(linha.get("custo_conversa"), opcional=True)
        if custo is None:
            return None
        conversas += volume
        custo_estimado += volume * custo
    return custo_estimado / conversas if conversas else None


def periodo_texto(inicio, termino, *, ano=True):
    if not inicio or not termino:
        return "Período não informado"

    def formatar(valor):
        try:
            data = datetime.strptime(str(valor)[:10], "%Y-%m-%d")
            return data.strftime("%d/%m/%Y" if ano else "%d/%m")
        except ValueError:
            return str(valor)

    return f"{formatar(inicio)} a {formatar(termino)}"


def _unidade(dados):
    linhas = list(dados.get("linhas") or [])
    agregado = analise_desempenho.consolidar(linhas)
    inicio, termino = periodo_do_relatorio(linhas)
    return {
        "unidade": str(dados.get("unidade") or "Unidade").strip(),
        "arquivo": str(dados.get("arquivo") or "").strip(),
        "campanha": str(dados.get("campanha") or "").strip(),
        "inicio": inicio,
        "termino": termino,
        "periodo": periodo_texto(inicio, termino),
        "alcance": _numero(agregado.get("alcance")),
        "impressoes": _numero(agregado.get("impressoes")),
        "frequencia": (_numero(agregado.get("frequencia"), opcional=True)
                       if agregado.get("frequencia") is not None else None),
        "conversas": _numero(agregado.get("conversas")),
        "custo_conversa": _custo_por_conversa(linhas),
        "novos_contatos": _numero(agregado.get("novos_contatos")),
    }


def consolidar(unidades):
    """Consolida unidades já filtradas pela campanha escolhida."""
    unidades = list(unidades)
    if len(unidades) < MIN_UNIDADES:
        raise ErroDeConsolidacao(
            "O consolidado precisa de pelo menos 2 arquivos válidos.")
    if len(unidades) > MAX_UNIDADES:
        raise ErroDeConsolidacao(
            "O consolidado aceita no máximo 20 arquivos.")

    detalhadas = [_unidade(u) for u in unidades]
    periodos = [{"unidade": u["unidade"], "inicio": u["inicio"],
                 "termino": u["termino"], "periodo": u["periodo"]}
                for u in detalhadas]
    intervalos = {(u["inicio"], u["termino"]) for u in detalhadas}
    # Período ausente também bloqueia: sem ele não há como provar que os
    # exports representam a mesma janela, ainda que todos estejam em branco.
    if len(intervalos) != 1 or any(not a or not b for a, b in intervalos):
        raise PeriodosDivergentes(periodos)

    alcance = sum((u["alcance"] for u in detalhadas), Decimal("0"))
    impressoes = sum((u["impressoes"] for u in detalhadas), Decimal("0"))
    conversas = sum((u["conversas"] for u in detalhadas), Decimal("0"))
    novos = sum((u["novos_contatos"] for u in detalhadas), Decimal("0"))

    # Soma operacional: pessoas entre contas podem se sobrepor e não há dado
    # para deduplicá-las. A razão ainda é a frequência coerente com essa soma.
    frequencia = impressoes / alcance if alcance else None

    custos_completos = all(
        not u["conversas"] or u["custo_conversa"] is not None
        for u in detalhadas)
    custo_estimado = sum(
        (u["conversas"] * u["custo_conversa"]
         for u in detalhadas if u["conversas"] and u["custo_conversa"] is not None),
        Decimal("0"),
    )
    custo_conversa = (custo_estimado / conversas
                      if conversas and custos_completos else None)

    inicio, termino = next(iter(intervalos))
    return {
        "cliente": str(unidades[0].get("cliente") or "").strip(),
        "produto": str(unidades[0].get("produto") or "").strip(),
        "inicio": inicio,
        "termino": termino,
        "periodo": periodo_texto(inicio, termino),
        "periodo_curto": periodo_texto(inicio, termino, ano=False),
        "unidades": detalhadas,
        "total_alcance": alcance,
        "total_impressoes": impressoes,
        "frequencia_consolidada": frequencia,
        "total_conversas": conversas,
        "custo_conversa_consolidado": custo_conversa,
        "total_novos_contatos": novos,
        "alcance_somado": True,
    }


def _nomes_em_linhas(nomes, limite=72):
    """Quebra listas longas sem esconder nenhuma unidade."""
    linhas = []
    atual = ""
    for nome in nomes:
        trecho = nome if not atual else f" + {nome}"
        if atual and len(atual) + len(trecho) > limite:
            linhas.append(atual)
            atual = f"+ {nome}"
        else:
            atual += trecho
    if atual:
        linhas.append(atual)
    return "\n".join(linhas)


def redigir(resultado):
    """Bloco compacto e determinístico para WhatsApp e Notion."""
    custo = resultado["custo_conversa_consolidado"]
    freq = resultado["frequencia_consolidada"]
    unidades = _nomes_em_linhas([u["unidade"] for u in resultado["unidades"]])
    return "\n".join((
        "*Desempenho*",
        "",
        f"*{resultado['cliente']} — {resultado['produto']}*",
        unidades,
        f"Período: {resultado['periodo_curto']}",
        "",
        f"Alcance .......... {inteiro(resultado['total_alcance'])}",
        f"Impressões ....... {inteiro(resultado['total_impressoes'])}",
        f"Frequência ....... {decimal(freq) if freq is not None else '—'}",
        f"Conversas ........ {inteiro(resultado['total_conversas'])}",
        f"Custo/conversa ... {moeda(custo) if custo is not None else '—'}",
        f"Novos contatos ... {inteiro(resultado['total_novos_contatos'])}",
    ))


def resumo(resultado):
    """Os seis cartões da tela, já no padrão pt-BR."""
    freq = resultado["frequencia_consolidada"]
    custo = resultado["custo_conversa_consolidado"]
    valores = (
        ("Alcance", inteiro(resultado["total_alcance"])),
        ("Impressões", inteiro(resultado["total_impressoes"])),
        ("Frequência", decimal(freq) if freq is not None else "—"),
        ("Conversas", inteiro(resultado["total_conversas"])),
        ("Custo/conversa", moeda(custo) if custo is not None else "—"),
        ("Novos contatos", inteiro(resultado["total_novos_contatos"])),
    )
    return [{"rotulo": rotulo, "valor": valor} for rotulo, valor in valores]


def conferencia(resultado):
    """Linhas formatadas da conferência, incluindo o total final."""
    linhas = []
    for unidade in resultado["unidades"]:
        linhas.append({
            "unidade": unidade["unidade"],
            "campanha": unidade["campanha"],
            "alcance": inteiro(unidade["alcance"]),
            "impressoes": inteiro(unidade["impressoes"]),
            "frequencia": (decimal(unidade["frequencia"])
                            if unidade["frequencia"] is not None else "—"),
            "conversas": inteiro(unidade["conversas"]),
            "custo_conversa": (moeda(unidade["custo_conversa"])
                                if unidade["custo_conversa"] is not None else "—"),
            "novos_contatos": inteiro(unidade["novos_contatos"]),
            "consolidado": False,
        })
    total = resumo(resultado)
    por_rotulo = {m["rotulo"]: m["valor"] for m in total}
    linhas.append({
        "unidade": "CONSOLIDADO", "campanha": "—",
        "alcance": por_rotulo["Alcance"],
        "impressoes": por_rotulo["Impressões"],
        "frequencia": por_rotulo["Frequência"],
        "conversas": por_rotulo["Conversas"],
        "custo_conversa": por_rotulo["Custo/conversa"],
        "novos_contatos": por_rotulo["Novos contatos"],
        "consolidado": True,
    })
    return linhas
