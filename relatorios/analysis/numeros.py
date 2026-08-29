# -*- coding: utf-8 -*-
"""
Números em pt-BR, como o texto os escreve.

Existe separado desde que `templates.py` deixou de ser o único a redigir: a
mensagem da Leitura Rápida (`mensagem.py`) escreve os mesmos valores nas mesmas
frases, e duas implementações do mesmo "R$ 2.012,07" acabariam divergindo numa
casa decimal sem ninguém notar.

Contrato diferente do `parser_xlsx._fmt_*`, e de propósito: ali `None` vira
"—", que é o traço de uma célula vazia numa tabela. Aqui `None` vira zero,
porque quem chama já decidiu que a frase existe — um travessão no meio de uma
oração seria pior do que o número que não temos.
"""


def pt_br(texto):
    """1,234.56 -> 1.234,56"""
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def moeda(valor):
    return "R$ " + pt_br(f"{float(valor or 0):,.2f}")


def decimal(valor):
    return f"{float(valor or 0):.2f}".replace(".", ",")


def percentual(valor):
    return f"{float(valor or 0):.2f}".replace(".", ",") + "%"


def inteiro(valor):
    return pt_br(f"{int(float(valor or 0)):,d}")
