# -*- coding: utf-8 -*-
"""
Gerador do PDF de Listagem (Modo 3) — Agência Apex.

Uma tabela comparativa com UMA LINHA POR CONTA, na ordem em que os anexos
foram enviados. Sem soma entre contas, sem análise e sem destaque de
"melhor conta": é listagem, não ranking. Paisagem A4, multi-página com
cabeçalho de tabela repetido e paginação no rodapé (WeasyPrint).
"""
from datetime import datetime

from django.template.loader import render_to_string
from weasyprint import HTML

from .gerador_pdf import _logo_b64
from .parser_xlsx import _fmt_dec, _fmt_int, _fmt_moeda


def linha_conta(nome, dados):
    """Linha da tabela a partir da saída normalizada do parser (1 conta)."""
    n = dados.get("_num") or {}
    inv = n.get("investimento") or 0.0
    res = n.get("resultados") or 0.0
    ctr = n.get("ctr")  # já derivado dos totais da conta (cliques/impressões)

    kpis = dados.get("kpis") or []
    rotulo = kpis[1]["label"] if len(kpis) > 1 else "Resultados"

    return {
        "conta": nome,
        "resultado_label": rotulo,
        "investimento": _fmt_moeda(inv),
        "resultados": _fmt_int(res),
        "custo": _fmt_moeda(inv / res if res else None),
        "alcance": _fmt_int(n.get("alcance") or None),
        "impressoes": _fmt_int(n.get("impressoes") or None),
        "ctr": f"{_fmt_dec(ctr)}%" if ctr is not None else "—",
    }


def gerar_listagem(titulo, contas, arquivo_saida):
    """
    Gera o PDF de listagem em `arquivo_saida` (caminho ou file-like).

    `contas`: lista de {"nome": str, "dados": dict de ler_export_meta},
    na ordem de envio dos anexos — a ordem das linhas é preservada.
    """
    contexto = {
        "titulo": titulo,
        "logo_b64": _logo_b64(),
        "linhas": [linha_conta(c["nome"], c["dados"]) for c in contas],
        "subtitulo": (f"{len(contas)} conta{'s' if len(contas) != 1 else ''}"
                      f" — gerado em {datetime.now():%d/%m/%Y}"),
        "rodape": "Relatório gerado a partir de dados exportados do "
                  "Meta Ads Manager. Valores por conta, sem consolidação.",
    }
    html = render_to_string("relatorios/pdf_listagem.html", contexto)
    HTML(string=html).write_pdf(arquivo_saida)
