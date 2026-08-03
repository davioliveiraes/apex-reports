# -*- coding: utf-8 -*-
"""
Gerador do PDF de Listagem (Modo 3) — Agência Apex.

Uma tabela comparativa com UMA LINHA POR CONTA, ranqueada por número de
resultados (maior primeiro) — a coluna `#` é a posição nesse ranking. Sem
soma entre contas e sem análise: comparar não é consolidar. Paisagem A4,
multi-página com cabeçalho de tabela repetido e paginação no rodapé
(WeasyPrint).
"""
from datetime import datetime

from django.template.loader import render_to_string
from weasyprint import HTML

from .gerador_pdf import _logo_b64
from .parser_xlsx import _fmt_int, _fmt_moeda


def linha_conta(nome, dados, posicao=None):
    """Linha da tabela a partir da saída normalizada do parser (1 conta)."""
    n = dados.get("_num") or {}
    inv = n.get("investimento") or 0.0
    res = n.get("resultados") or 0.0

    kpis = dados.get("kpis") or []
    rotulo = kpis[1]["label"] if len(kpis) > 1 else "Resultados"

    return {
        "posicao": posicao,
        "conta": nome,
        "resultado_label": rotulo,
        "resultados": _fmt_int(res),
        "investimento": _fmt_moeda(inv),
        "custo": _fmt_moeda(inv / res if res else None),
        "alcance": _fmt_int(n.get("alcance") or None),
        "impressoes": _fmt_int(n.get("impressoes") or None),
        # Já recalculado pelo parser a partir dos totais brutos da conta
        # (investimento / impressões × 1000), e None quando não há impressões.
        "cpm": _fmt_moeda(n.get("cpm")),
    }


def _chave_ranking(conta):
    """Ordem do ranking: mais resultados primeiro.

    O desempate é por investimento (maior primeiro) e, se ainda empatar, pelo
    nome — sem isso, duas contas de mesmo volume poderiam trocar de posição
    entre duas gerações do mesmo relatório.
    """
    n = (conta.get("dados") or {}).get("_num") or {}
    return (-(n.get("resultados") or 0.0), -(n.get("investimento") or 0.0),
            conta.get("nome") or "")


def montar_linhas(contas):
    """Linhas numeradas da tabela — mesma fonte para o PDF e para a prévia
    da revisão, de modo que o operador confere exatamente o que vai sair."""
    return [linha_conta(c["nome"], c["dados"], posicao=i)
            for i, c in enumerate(sorted(contas, key=_chave_ranking), start=1)]


def gerar_listagem(titulo, contas, arquivo_saida, periodo=""):
    """
    Gera o PDF de listagem em `arquivo_saida` (caminho ou file-like).

    `contas`: lista de {"nome": str, "dados": dict de ler_export_meta}. A
    ordem das linhas é o ranking por número de resultados, não a de envio.

    `periodo`: rótulo já formatado ("01/07/2026 — 31/07/2026") para o canto
    superior direito. Em branco, o bloco não aparece.
    """
    contexto = {
        "titulo": titulo,
        "periodo": periodo,
        "logo_b64": _logo_b64(),
        "linhas": montar_linhas(contas),
        "subtitulo": (f"{len(contas)} conta{'s' if len(contas) != 1 else ''}"
                      f" — ordenadas por volume de resultados"
                      f" · gerado em {datetime.now():%d/%m/%Y}"),
        "rodape": "Relatório gerado a partir de dados exportados do "
                  "Meta Ads Manager. Valores por conta, sem consolidação.",
    }
    html = render_to_string("relatorios/pdf_listagem.html", contexto)
    HTML(string=html).write_pdf(arquivo_saida)
