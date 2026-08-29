# -*- coding: utf-8 -*-
"""
Indicador de resultado — tradução e escolha do dominante.

FONTE ÚNICA DE VERDADE do rótulo que o cliente lê. O export do Meta traz o
indicador cru da API ("actions:post_engagement"); nenhuma dessas strings pode
chegar ao PDF. Acrescentar um indicador novo é acrescentar UMA entrada em
ROTULOS — parser, geradores e templates não mudam.

Uma conta pode ter campanhas com objetivos diferentes na mesma planilha. Aí o
indicador da conta é o de maior SOMA DE RESULTADOS (ver `dominante`), não o da
primeira linha: uma campanha de engajamento aberta no fim do mês não rebatiza
o relatório inteiro.
"""
import logging
import unicodedata
from collections import defaultdict

logger = logging.getLogger(__name__)

ROTULOS = {
    "actions:onsite_conversion.messaging_conversation_started_7d": "Conversas Iniciadas",
    "actions:post_engagement": "Envolvimento com a Publicação",
    "video_thruplay_watched_actions": "Reproduções de Vídeo (ThruPlay)",
    "actions:link_click": "Cliques no Link",
    "actions:landing_page_view": "Visualizações da Página",
    "actions:lead": "Leads",
}

PADRAO = "Resultados"

# O mesmo indicador, em prosa. `ROTULOS` é rótulo de COLUNA — "Conversas
# Iniciadas" encabeça uma tabela, mas dentro de uma frase escrita para o
# cliente o que cabe é "229 conversas" e "R$ 21,01 por conversa". Os dois
# vivem juntos aqui porque são a mesma decisão: como este resultado se chama
# para quem não é gestor de tráfego.
#
# Chaveado pelo rótulo, e não pelo código cru, para não repetir o trabalho de
# casar as variações de escrita que `rotulo()` já faz.
#
# O terceiro campo é o gênero, e não é preciosismo: a frase que fecha a
# mensagem de WhatsApp pergunta "quantas DAS 229 conversas" ou "quantos DOS 45
# leads", e errar a contração é o tipo de detalhe que denuncia texto de robô
# na primeira linha que o cliente lê.
TERMOS = {
    "Conversas Iniciadas": ("conversa", "conversas", "f"),
    "Leads": ("lead", "leads", "m"),
    "Cliques no Link": ("clique no link", "cliques no link", "m"),
    "Visualizações da Página": ("visita à página", "visitas à página", "f"),
    "Envolvimento com a Publicação": ("interação", "interações", "f"),
    "Reproduções de Vídeo (ThruPlay)": ("reprodução de vídeo",
                                        "reproduções de vídeo", "f"),
    PADRAO: ("resultado", "resultados", "m"),
}

# Mesmo objetivo aparece com nomes diferentes conforme a versão e o idioma do
# export ("Conversas por mensagem iniciadas", "messaging_conversation_started").
# Casado por trecho, na ordem — o primeiro que bater vence, então o mais
# específico vem antes.
_FAMILIAS = (
    ("thruplay", "Reproduções de Vídeo (ThruPlay)"),
    ("convers", "Conversas Iniciadas"),
    ("mensag", "Conversas Iniciadas"),
    ("messaging", "Conversas Iniciadas"),
    ("landing_page", "Visualizações da Página"),
    ("pagina de destino", "Visualizações da Página"),
    ("link_click", "Cliques no Link"),
    ("clique no link", "Cliques no Link"),
    ("post_engagement", "Envolvimento com a Publicação"),
    ("envolvimento", "Envolvimento com a Publicação"),
    ("engajamento", "Envolvimento com a Publicação"),
    ("lead", "Leads"),
)


def _norm(texto):
    """minúsculas, sem acento — para casar rótulos independentes de escrita."""
    texto = str(texto or "").lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def _parece_codigo(bruto):
    """Cru da API ("actions:lead", "video_thruplay_watched_actions") — nunca
    pode aparecer para o cliente. Rótulo em linguagem natural que o export
    trouxe pronto ("Compras") não é código: passa sem alarme."""
    return ":" in bruto or "_" in bruto


def rotulo(indicador, conta=None, avisar=True):
    """Rótulo client-facing do indicador. Sem indicador, devolve "Resultados".

    Indicador desconhecido cai no valor cru; se parecer código de API, registra
    um warning com a conta para o caso novo ser mapeado depois — melhor um
    rótulo estranho no PDF do que um relatório que não gera.

    `avisar=False` para quem só reaproveita o rótulo de uma conta já lida —
    sem isso o mesmo indicador viraria três linhas de log por planilha.
    """
    if not indicador:
        return PADRAO
    bruto = str(indicador).strip()
    if bruto in ROTULOS:
        return ROTULOS[bruto]

    normalizado = _norm(bruto)
    for cru, legivel in ROTULOS.items():
        if _norm(cru) == normalizado:
            return legivel
    for trecho, legivel in _FAMILIAS:
        if trecho in normalizado:
            return legivel

    if avisar and _parece_codigo(bruto):
        logger.warning("Indicador de resultado sem rótulo mapeado: %r%s", bruto,
                       f" (conta: {conta})" if conta else "")
    return bruto


def eh_conversa(indicador):
    """True quando o resultado é conversa iniciada — muda o texto da análise
    ("3 conversas" em vez de "3 resultados") e o rótulo do funil."""
    return "convers" in _norm(indicador) or "mensag" in _norm(indicador)


def termos(indicador):
    """`(singular, plural, gênero)` em prosa para este indicador.

    Indicador sem termo mapeado cai em "resultado/resultados" — genérico, mas
    nunca errado. É o mesmo princípio de `rotulo()`: preferir a palavra neutra
    a arriscar um nome que não descreve o que aconteceu.
    """
    return TERMOS.get(rotulo(indicador, avisar=False), TERMOS[PADRAO])


def dominante(registros, campo="indicador", resultados="resultados",
              para_numero=float):
    """Indicador de maior soma de resultados entre as linhas de uma conta.

    Linhas sem resultado não votam — uma campanha que não converteu não define
    o indicador do relatório. Empate resolve pelo indicador que aparece
    primeiro na planilha, mantendo a saída estável entre duas leituras.
    """
    somas = defaultdict(float)
    ordem = {}
    for i, r in enumerate(registros):
        ind = r.get(campo)
        if not ind:
            continue
        ind = str(ind).strip()
        ordem.setdefault(ind, i)
        try:
            valor = para_numero(r.get(resultados)) or 0.0
        except (TypeError, ValueError):
            valor = 0.0
        somas[ind] += valor

    if not somas:
        return ""
    return max(somas, key=lambda ind: (somas[ind], -ordem[ind]))
