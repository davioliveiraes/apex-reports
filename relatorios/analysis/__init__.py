# -*- coding: utf-8 -*-
"""
Motor de análise do período — determinístico, offline, sem dependência externa.

Dois passos, separados de propósito:

    avaliacao = analysis.rules.avaliar(metricas, perfil=..., meta_cpa=...)
    texto     = analysis.templates.redigir(avaliacao, metricas, destino="pdf")

`rules` decide (classificação + sinais + próximo passo) e `templates` redige.
A separação existe para que a mesma `Avaliacao` alimente destinos diferentes —
o PDF hoje, a mensagem de WhatsApp depois — sem reprocessar os números, e para
que a decisão seja testável sem passar pelo texto.

Nada aqui faz I/O, lê relógio ou sorteia: a mesma entrada devolve sempre a
mesma saída.
"""

from . import benchmarks, rules, templates  # noqa: F401

__all__ = ["benchmarks", "rules", "templates"]
