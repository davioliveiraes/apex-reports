# -*- coding: utf-8 -*-
"""
O texto do rastreamento, pronto para colar no WhatsApp.

Separado do diagnóstico pelo mesmo motivo que `analysis/templates.py` é
separado de `analysis/rules.py`: mudar uma frase não pode exigir mexer numa
fórmula. Aqui não se decide nada — o que este arquivo recebe já foi decidido em
`diagnostico.py`.

Regras de redação
-----------------
Negrito só com asterisco simples, do jeito que o WhatsApp entende (§28). Sem
tabela, sem lista com marcador, sem markdown de título — o que não renderiza no
aplicativo vira lixo visível na tela do cliente.

Cada parágrafo só existe se o arquivo sustentar. Um bloco ausente **não vira
frase** — "não foi possível avaliar o destino" é informação de operação, não do
cliente, e vive na tela ao lado. O que o cliente recebe é o que se sabe.

Nada aqui projeta o mês seguinte, promete resultado ou afirma causa. "O CTR foi
0,58%" é dado; "o criativo não está atraindo" seria diagnóstico de uma causa
que o arquivo não isola de outras três.
"""

from ..analysis.numeros import inteiro, moeda, pt_br
from ..parser_rastreamento import BLOCO_RELEVANCIA
from .diagnostico import _lista, percentual
from .metricas import maior_queda


def _pct_fino(valor):
    """"0,58%" — duas casas, para as taxas pequenas como o CTR."""
    return pt_br(f"{float(valor):.2f}") + "%"


# Mesma régua da tela: duas casas só onde elas mudam a leitura. Importada em
# vez de reescrita para o texto não dizer "76%" ao lado de um cartão que diz
# "75,74%".
_pct = percentual


def _data(iso):
    """"2026-07-30" -> "30/07/2026"."""
    if not iso:
        return ""
    partes = str(iso)[:10].split("-")
    return "/".join(reversed(partes)) if len(partes) == 3 else str(iso)


def redigir(total, diag):
    """A leitura do rastreamento, pronta para copiar."""
    partes = [_cabecalho(total), _clique(total), _destino(total),
              _relevancia(total, diag), _retencao(total),
              _atencao(total, diag)]
    return "\n\n".join(p for p in partes if p)


def _cabecalho(total):
    inicio, fim = total.get("periodo") or (None, None)
    if inicio and fim:
        return f"*Rastreamento da campanha — {_data(inicio)} a {_data(fim)}*"
    return "*Rastreamento da campanha*"


def _clique(total):
    """Volume, taxa e custo do clique.

    Os dois CTR nunca aparecem na mesma frase comparados: têm denominadores
    diferentes (impressões contra alcance), e o cliente leria o único como uma
    versão melhorada do outro. O único entra sozinho, com o que ele mede.
    """
    cliques = total.get("link_clicks")
    if cliques is None:
        return ""
    if not cliques:
        # Zero clique é informação, e das boas: sem ela o texto sairia só com
        # o cabeçalho, e o cliente receberia uma mensagem que não diz nada.
        return ("Os anúncios não registraram cliques no link no período.")

    frase = f"Os anúncios registraram *{inteiro(cliques)} cliques no link*"
    detalhes = []
    if total.get("link_ctr"):
        detalhes.append(f"CTR de {_pct_fino(total['link_ctr'])}")
    if total.get("link_cpc"):
        detalhes.append(f"CPC de {moeda(total['link_cpc'])}")
    if detalhes:
        frase += ", com " + " e ".join(detalhes)
    frase += "."

    unicos = total.get("unique_link_clicks")
    if unicos and unicos != cliques:
        frase += (f" Desses, {inteiro(unicos)} vieram de pessoas diferentes.")
    return frase


def _destino(total):
    """A passagem do clique ao carregamento — só quando o arquivo tem as duas
    pontas. Campanha de mensagem não tem página de destino, e silêncio é a
    leitura certa (§11)."""
    taxa = total.get("taxa_carregamento")
    lpv = total.get("landing_page_views")
    if taxa is None or lpv is None:
        return ""

    frase = (f"Do total de cliques, *{inteiro(lpv)} chegaram a carregar a "
             f"página de destino* — {_pct(taxa)} dos acessos")
    custo = total.get("cost_per_landing_page_view")
    if custo:
        frase += f", a {moeda(custo)} por visualização"
    return frase + "."


def _relevancia(total, diag):
    """As classificações do Meta, com as palavras do Meta.

    Sem tradução para número e sem conclusão sobre causa: o que se diz é que a
    plataforma comparou o anúncio com os concorrentes e onde ela apontou algo.
    """
    bloco = _bloco(diag, BLOCO_RELEVANCIA)
    if not bloco or not bloco["disponivel"]:
        return ""

    abaixo = [s for s in bloco["sinais"] if s["tipo"] == "abaixo_da_media"]
    if abaixo:
        campos = _lista([s["rotulo"].lower() for s in abaixo])
        return (f"Na comparação que o Meta faz com os anúncios que disputam o "
                f"mesmo público, a classificação de {campos} ficou *abaixo da "
                "média*. É um sinal para acompanhar, não um veredito sobre o "
                "criativo.")

    valores = [m for m in bloco["metricas"] if m["valor"]]
    if not valores:
        return ""
    return ("Na comparação que o Meta faz com os anúncios que disputam o mesmo "
            "público, as classificações vieram assim: "
            + _lista([f"{m['rotulo'].lower()} {str(m['valor']).lower()}"
                      for m in valores]) + ".")


def _retencao(total):
    """O funil do vídeo. Ausente para anúncio de imagem, e sem nota nenhuma —
    o cliente não precisa saber que existe uma métrica que o formato dele não
    tem."""
    if not total.get("n_video"):
        return ""
    ret = total.get("retencao") or {}
    ate_o_fim = ret.get("25_100")
    thruplays = total.get("thruplays")

    frases = []
    if thruplays:
        frases.append(f"O vídeo teve *{inteiro(thruplays)} ThruPlays*")
    if ate_o_fim is not None:
        inicio = "e " if frases else "No vídeo, "
        frases.append(f"{inicio}{_pct(ate_o_fim)} de quem passou do primeiro "
                      "quarto assistiu até o fim")
    if not frases:
        return ""

    texto = " ".join(frases).replace(" e No vídeo,", " e") + "."
    queda = maior_queda(ret)
    if queda:
        # Comparação interna ao mesmo funil — a única afirmação que os marcos
        # sustentam. Em que segundo a queda aconteceu, o arquivo não diz.
        texto += f" A maior perda proporcional ficou entre {queda[0]}."
    return texto


def _atencao(total, diag):
    """O ponto de atenção, com a evidência que o sustenta.

    Sem gargalo identificado o parágrafo some — dizer ao cliente "não
    encontramos gargalo" é informação de operação, e afirmá-lo como conclusão
    seria prometer que não há nenhum.
    """
    gargalo = diag.get("gargalo")
    if not gargalo:
        return ""
    return (f"*Principal ponto de atenção: {gargalo['titulo'].lower()}* — "
            f"{gargalo['evidencia']}.")


def _bloco(diag, chave):
    return next((b for b in diag.get("blocos", []) if b["chave"] == chave),
                None)
