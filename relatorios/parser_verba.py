# -*- coding: utf-8 -*-
"""
Leitor do export do preset `VERBA` do Gerenciador de Anúncios.

Módulo separado do `parser_xlsx` de propósito, e não por organização: o preset
`VERBA` traz colunas que **colidem** com as do export de desempenho. `Início` e
`Término` aqui são as datas de configuração da campanha; lá, o recorte do
relatório ("Início dos relatórios"). Ler os dois com o mesmo mapa faria uma
campanha que subiu dia 17 parecer ter começado no dia 1º — que é justamente o
erro que este módulo existe para evitar (ver `docs/GUIA_VERBA.md`).

Orçamento não é métrica, é configuração: ele só existe no nível em que foi
definido. Campanha `[CBO]` guarda o valor nela mesma; campanha `[ABO]` guarda
"Usando o orçamento do conjunto de anúncios" e o valor está no outro export.
Por isso a coleta são dois arquivos, e por isso o cruzamento é **por ID**:
nome de campanha é renomeado no meio do mês e o merge perde linhas sem avisar.
"""

import re
from datetime import date, datetime

from openpyxl import load_workbook

from .parser_xlsx import _fmt_data, _mapear_colunas, _norm, _to_float

# Mesmo formato de `parser_xlsx._COLUNAS`: chave → (alternativas, proibidos).
# `_mapear_colunas` casa nome exato primeiro e só depois "contém", então
# "Orçamento" ganha de "Tipo de orçamento" sem depender da ordem das colunas —
# os proibidos são o cinto de segurança para o dia em que o Meta renomear uma
# delas (o guia avisa que isso acontece).
_COLUNAS_VERBA = {
    "campanha_id":    ([["identificacao da campanha"], ["campaign id"]], []),
    "campanha":       ([["nome da campanha"], ["campaign name"]], []),
    "conjunto_id":    ([["identificacao", "conjunto"], ["ad set id"]], []),
    "conjunto":       ([["nome do conjunto"], ["ad set name"]], []),
    "orcamento":      ([["orcamento"], ["budget"]], ["tipo", "type"]),
    "tipo_orcamento": ([["tipo de orcamento"], ["budget type"]], []),
    "lances":         ([["estrategia de lances"], ["bid strategy"]], []),
    # Proibidos afastam as colunas homônimas do export de desempenho, caso o
    # operador tenha exportado com as duas predefinições misturadas.
    "inicio":         ([["inicio"], ["starts"], ["start time"]],
                       ["relatorio", "reporting"]),
    "termino":        ([["termino"], ["encerramento"], ["ends"], ["end time"]],
                       ["relatorio", "reporting"]),
    "objetivo":       ([["objetivo"], ["objective"]], []),
    "veiculacao":     ([["veiculacao"], ["delivery"]], []),
    "gasto":          ([["valor gasto"], ["valor usado"], ["amount spent"]], []),
}

# Valores de `Veiculação` que contam como estrutura no ar. Tudo o que não está
# aqui conta como fora — inclusive "em análise" e "programada", que ainda não
# gastam. O valor cru vai para a tabela de conferência da tela: o operador
# precisa poder discordar do que o app decidiu, e para isso precisa ver.
VEICULACOES_ATIVAS = frozenset((
    "active", "ativa", "ativo", "ativas", "ativos",
    "veiculando", "em veiculacao", "delivering", "publicado",
))

# Texto que o Meta escreve na célula de orçamento da campanha quando o valor
# mora um nível abaixo. É o marcador de `[ABO]`, e a única forma de saber que o
# segundo arquivo é obrigatório para esta conta.
_HERDA_DO_CONJUNTO = ("orcamento do conjunto", "ad set budget",
                      "usando o orcamento do conjunto")

_NUMERO = re.compile(r"\d[\d.,]*")


# ----------------------------------------------------------------------
# Leitura de um arquivo
# ----------------------------------------------------------------------
def ler_planilha_verba(arquivo):
    """`(linhas, nivel)` de um export do preset `VERBA`.

    `nivel` é "conjunto" ou "campanha", deduzido das colunas — **a ordem em que
    os dois arquivos são enviados não importa**, e o operador não precisa
    dizer qual é qual.
    """
    wb = load_workbook(arquivo, data_only=True, read_only=True)
    ws = wb.active
    linhas_brutas = list(ws.iter_rows(values_only=True))
    wb.close()
    if not linhas_brutas:
        raise ValueError("A planilha está vazia.")

    cabecalho, mapa = None, {}
    for i, linha in enumerate(linhas_brutas[:10]):
        m = _mapear_colunas(linha, _COLUNAS_VERBA)
        if "orcamento" in m or "gasto" in m:
            cabecalho, mapa = i, m
            break
    if cabecalho is None:
        raise ValueError(
            "Não foi possível reconhecer as colunas de verba nesta planilha. "
            "Aplique a predefinição VERBA em Colunas → Personalizar colunas "
            "antes de exportar (ver docs/GUIA_VERBA.md)."
        )

    linhas = []
    for bruta in linhas_brutas[cabecalho + 1:]:
        if bruta is None or all(c is None or str(c).strip() == "" for c in bruta):
            continue
        reg = {}
        for chave, idx in mapa.items():
            valor = bruta[idx] if idx < len(bruta) else None
            # A sessão serializa em JSON e não sabe gravar `date`.
            if isinstance(valor, date):
                valor = valor.strftime("%Y-%m-%d")
            reg[chave] = valor
        nome_ref = _norm(reg.get("conjunto") or reg.get("campanha"))
        if nome_ref.startswith(("total", "resultados de")):
            continue
        linhas.append(reg)

    if not linhas:
        raise ValueError("Nenhuma linha de dados encontrada na planilha.")
    return linhas, _nivel(linhas)


def _nivel(linhas):
    """"conjunto" quando há coluna de conjunto **preenchida**.

    A checagem é pelo valor, não pela presença da coluna: a predefinição VERBA
    pede as duas identificações, então o export de campanha também traz a
    coluna de conjunto — vazia.
    """
    for r in linhas:
        if str(r.get("conjunto_id") or r.get("conjunto") or "").strip():
            return "conjunto"
    return "campanha"


def ler_arquivos_verba(arquivos):
    """`(linhas_campanha, linhas_conjunto, erro)` para os anexos enviados.

    Um arquivo só é aceito: conta 100% `[CBO]` fecha sem o export de conjunto.
    O que falta nesse caso vira aviso em `montar_estruturas`, nominal e depois
    de saber que existe `[ABO]` — não um erro genérico no envio.
    """
    niveis = {}
    for f in arquivos:
        try:
            linhas, nivel = ler_planilha_verba(f)
        except ValueError as e:
            return None, None, f'Arquivo "{f.name}": {e}'
        except Exception:
            return None, None, (
                f'Não foi possível ler "{f.name}". Confira se é o .xlsx '
                "exportado direto do Gerenciador de Anúncios."
            )
        if nivel in niveis:
            return None, None, (
                f'"{f.name}" é outro export de nível {nivel} — os dois arquivos '
                "são a mesma tabela vista de alturas diferentes, um de "
                "campanha e um de conjunto de anúncios."
            )
        niveis[nivel] = linhas
    return niveis.get("campanha", []), niveis.get("conjunto", []), None


# ----------------------------------------------------------------------
# Orçamento: valor, periodicidade e herança
# ----------------------------------------------------------------------
def partir_orcamento(celula, tipo=None):
    """`(valor, periodicidade, herdado)` da célula de orçamento.

    O export traz valor e periodicidade grudados — `R$ 33,00 Diário`,
    `R$ 1.000,00 Vitalício` —, então o número sai por regex e não por
    `_to_float` direto, que engasgaria no texto ao lado. A coluna *Tipo de
    orçamento*, quando veio, tem a última palavra sobre a periodicidade.

    `herdado=True` é a campanha `[ABO]`: o valor não está aqui, está no export
    de conjunto de anúncios.
    """
    texto = "" if celula is None else str(celula).strip()
    normal = _norm(texto)
    if any(marca in normal for marca in _HERDA_DO_CONJUNTO):
        return None, None, True

    achado = _NUMERO.search(texto)
    valor = _to_float(achado.group(0)) if achado else _to_float(celula)
    if valor is None:
        return None, None, False
    return valor, _periodicidade(tipo, normal), False


def _periodicidade(tipo, texto_normal):
    """"vitalicio" ou "diario" — a fórmula de projeção depende disso."""
    for fonte in (_norm(tipo), texto_normal):
        if "vitalic" in fonte or "lifetime" in fonte:
            return "vitalicio"
        if "diari" in fonte or "daily" in fonte:
            return "diario"
    return "diario"


def ativa(veiculacao):
    """A estrutura está no ar? Só o que está entra no configurado diário."""
    return _norm(veiculacao) in VEICULACOES_ATIVAS


# ----------------------------------------------------------------------
# Cruzamento dos dois níveis
# ----------------------------------------------------------------------
def _data(valor):
    """Texto ISO ou dd/mm/aaaa → `date`; qualquer outra coisa → None."""
    if isinstance(valor, (datetime, date)):
        return valor.date() if isinstance(valor, datetime) else valor
    texto = str(valor or "").strip()[:10]
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _diario_equivalente(valor, periodicidade, inicio, termino, dias_do_mes):
    """`(valor diário, precisou do mês)`.

    Vitalício não é diário: dividi-lo pelo período em que ele vale é o que
    permite compará-lo com o contratado. Sem data de término não há período,
    e aí o mês de referência é o palpite menos ruim — sinalizado, para o
    operador saber que aquele número é uma conversão e não uma leitura.
    """
    if valor is None or periodicidade != "vitalicio":
        return valor, False
    i, f = _data(inicio), _data(termino)
    if i and f and f >= i:
        return valor / ((f - i).days + 1), False
    return valor / dias_do_mes, True


def montar_estruturas(linhas_campanha, linhas_conjunto=(), dias_do_mes=30):
    """`(estruturas, avisos)` — uma estrutura por campanha, conjuntos aninhados.

    Cada campanha sai com dois orçamentos: `orcamento` (tudo o que está
    configurado) e `orcamento_ativo` (só o que está no ar). O segundo é o que
    entra no `configurado_diario` do fechamento; o primeiro fica para a tabela
    de conferência explicar a diferença.

    Campanha pausada zera o ativo mesmo com conjuntos ativos dentro: conjunto
    no ar sob campanha desligada não entrega nada.
    """
    avisos = []
    sem_id = not any(str(r.get("campanha_id") or "").strip()
                     for r in linhas_campanha)
    if sem_id and linhas_conjunto:
        avisos.append(
            "O export não traz a coluna de identificação da campanha — o "
            "cruzamento entre os dois arquivos caiu no nome, que muda quando "
            "a campanha é renomeada. Reexporte com a predefinição VERBA."
        )

    conjuntos = _conjuntos_por_campanha(linhas_conjunto, sem_id, dias_do_mes)

    estruturas, abo_orfas, convertidos = [], 0, 0
    for linha in linhas_campanha:
        chave = _chave(linha, sem_id)
        valor, periodicidade, herdado = partir_orcamento(
            linha.get("orcamento"), linha.get("tipo_orcamento"))
        no_ar = ativa(linha.get("veiculacao"))
        filhos = conjuntos.get(chave, [])

        if herdado or (valor is None and filhos):
            tipo = "ABO"
            orcamento = sum(c["orcamento"] for c in filhos
                            if c["orcamento"] is not None) or None
            orcamento_ativo = sum(c["orcamento"] for c in filhos
                                  if c["ativa"] and c["orcamento"] is not None)
            convertidos += sum(1 for c in filhos if c["convertido"])
            if not filhos:
                abo_orfas += 1
        else:
            tipo = "CBO"
            orcamento, convertido = _diario_equivalente(
                valor, periodicidade, linha.get("inicio"),
                linha.get("termino"), dias_do_mes)
            convertidos += 1 if convertido else 0
            orcamento_ativo = orcamento

        # Campanha fora do ar não configura nada, esteja o valor nela ou nos
        # conjuntos: conjunto ativo sob campanha desligada não entrega.
        if not no_ar:
            orcamento_ativo = 0.0

        estruturas.append({
            "id": chave,
            "nome": str(linha.get("campanha") or "").strip() or "(sem nome)",
            "objetivo": str(linha.get("objetivo") or "").strip(),
            "lances": str(linha.get("lances") or "").strip(),
            "veiculacao": str(linha.get("veiculacao") or "").strip() or "—",
            "ativa": no_ar,
            "inicio": linha.get("inicio"),
            "termino": linha.get("termino"),
            "inicio_br": _fmt_data(linha.get("inicio")) or "—",
            "tipo": tipo,
            "gasto": _to_float(linha.get("gasto")) or 0.0,
            "orcamento": orcamento,
            "orcamento_ativo": orcamento_ativo or 0.0,
            "orcamento_bruto": str(linha.get("orcamento") or "").strip() or "—",
            "conjuntos": filhos,
        })

    if abo_orfas:
        avisos.append(
            f"{abo_orfas} campanha(s) usam orçamento de conjunto de anúncios e "
            "não há export de nível conjunto para resolvê-las — o configurado "
            "sai incompleto. Exporte também a aba Conjuntos de anúncios."
        )
    if convertidos:
        avisos.append(
            f"{convertidos} estrutura(s) com orçamento vitalício sem data de "
            f"término: o valor foi dividido pelos {dias_do_mes} dias do mês "
            "para virar equivalente diário."
        )
    return estruturas, avisos


def _chave(linha, sem_id):
    """ID da campanha — o merge é por ID, e só cai no nome quando não há ID."""
    if not sem_id:
        return str(linha.get("campanha_id") or "").strip()
    return _norm(linha.get("campanha"))


def _conjuntos_por_campanha(linhas, sem_id, dias_do_mes):
    grupos = {}
    for linha in linhas:
        valor, periodicidade, _ = partir_orcamento(
            linha.get("orcamento"), linha.get("tipo_orcamento"))
        orcamento, convertido = _diario_equivalente(
            valor, periodicidade, linha.get("inicio"), linha.get("termino"),
            dias_do_mes)
        grupos.setdefault(_chave(linha, sem_id), []).append({
            "nome": str(linha.get("conjunto") or "").strip() or "(sem nome)",
            "veiculacao": str(linha.get("veiculacao") or "").strip() or "—",
            "ativa": ativa(linha.get("veiculacao")),
            "orcamento": orcamento,
            "orcamento_bruto": str(linha.get("orcamento") or "").strip() or "—",
            "convertido": convertido,
        })
    return grupos
