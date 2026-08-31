# -*- coding: utf-8 -*-
"""
Campanhas incluídas — a seleção compartilhada pelas quatro frentes de texto.

A Análise Geral já tinha isto desde o começo: um bloco `01 Campanhas incluídas`
com uma caixa por grupo e um botão *Aplicar seleção* que refaz a leitura do
anexo sem reenviar arquivo (`views._aplicar_selecao`). As frentes de texto
nasceram sem ele, cada uma consolidando o arquivo inteiro — e a de Desempenho
chegou a ganhar um seletor próprio, de campanha única, num `<select>` que não
se parecia com nada mais no produto.

Este módulo é a mesma ideia com um dono só. O agrupamento é literalmente o da
Análise Geral (`parser_xlsx.chave_grupo_campanha`: os dois primeiros colchetes
do nome, que são o produto anunciado), então uma conta recortada num modo
recorta igual no outro. O que muda entre as frentes são duas coisas, e elas
entram por parâmetro:

* **onde está o nome** — o preset de rastreamento chama a coluna de
  `campaign_name`, o de desempenho de `campanha`, e um export de conjuntos
  pode não trazer campanha nenhuma;
* **o que conta como entrega** — impressões no desempenho, cliques no link no
  rastreamento, valor gasto na verba.

Por que a seleção padrão não é sempre "tudo marcado"
----------------------------------------------------
Na Análise Geral é, e faz sentido lá: o operador escolhe os anexos que quer
comparar. Nas frentes de texto o arquivo é um export inteiro da conta, e a
conta de referência traz nove campanhas com oito paradas há meses. Elas somam
zero em tudo, então não mudam número nenhum — mas mudam o TEXTO, que passa a
falar no plural de campanhas que não rodaram. Por isso o padrão aqui é
*marcado o que entregou*, com as paradas visíveis e desmarcadas em vez de
escondidas. Quando nada entregou, tudo volta marcado: uma tela sem nenhuma
caixa marcada não é uma leitura, é um beco.

A verba é a exceção declarada (`padrao_completo`): lá uma campanha configurada
que ainda não gastou continua fazendo parte do fechamento, e desmarcá-la
sozinha alteraria o orçamento configurado do ciclo.
"""

from .parser_xlsx import GRUPO_SEM_NOME, chave_grupo_campanha

# O botão. Mesmo nome do da Análise Geral, de propósito: é o mesmo gesto, e um
# dia as duas telas podem dividir o mesmo trecho de template.
CAMPO = "aplicar_campanhas"

# Onde cada preset guarda o nome, na ordem em que se prefere lê-lo, e o que
# conta como entrega. Ficam aqui, e não espalhados nas views, porque é a única
# diferença real entre as quatro frentes — vê-las lado a lado é o que impede
# que a quinta invente uma terceira convenção.
NOMES_DESEMPENHO = ("campanha", "conjunto")
NOMES_RASTREAMENTO = ("campaign_name", "adset_name", "ad_name")

ENTREGA_DESEMPENHO = ("impressoes",)
ENTREGA_RASTREAMENTO = ("link_clicks",)
ENTREGA_VERBA = ("gasto",)

ERRO_VAZIO = "Marque pelo menos um grupo de campanhas."


def nome_da_linha(linha, campos=NOMES_DESEMPENHO):
    """O nome de campanha desta linha, cru, ou `""`.

    Cai de campo em campo porque o mesmo preset sai de abas diferentes do
    Gerenciador: um export de conjuntos não traz coluna de campanha, e ler só
    a primeira deixaria toda linha anônima — que é exatamente o defeito que
    fazia a Análise de Desempenho escrever "Conjunto 1".
    """
    for campo in campos:
        valor = str(linha.get(campo) or "").strip()
        if valor:
            return valor
    return ""


def _numero(valor):
    try:
        return float(valor or 0.0)
    except (TypeError, ValueError):
        return 0.0


def grupos(linhas, *, campos=NOMES_DESEMPENHO, entrega=ENTREGA_DESEMPENHO):
    """Os grupos de campanha destas linhas, na ordem em que aparecem.

    `[{"chave", "campanhas", "n_campanhas", "n_linhas", "entregou"}]` — a
    mesma forma de `parser_xlsx.grupos_de_campanha`, com dois campos a mais
    que a tela usa para não deixar o operador escolher no escuro.

    A ordem é a do arquivo, e não a do volume: a lista de caixas é uma cópia
    do que está na planilha, e reordenar por resultado faria a conferência
    contra o Gerenciador virar uma caça.
    """
    encontrados = {}
    for linha in linhas:
        nome = nome_da_linha(linha, campos)
        chave = chave_grupo_campanha(nome)
        g = encontrados.setdefault(chave, {
            "chave": chave, "campanhas": [], "n_linhas": 0, "_entrega": 0.0})
        if nome and nome not in g["campanhas"]:
            g["campanhas"].append(nome)
        g["n_linhas"] += 1
        g["_entrega"] += sum(_numero(linha.get(c)) for c in entrega)

    saida = []
    for g in encontrados.values():
        saida.append({
            "chave": g["chave"],
            "campanhas": g["campanhas"],
            "n_campanhas": len(g["campanhas"]) or g["n_linhas"],
            "n_linhas": g["n_linhas"],
            "entregou": bool(g["_entrega"]),
        })
    return saida


def filtrar(linhas, chaves, campos=NOMES_DESEMPENHO):
    """As linhas dos grupos escolhidos.

    `chaves` vazio não filtra nada — é o que faz a sessão antiga, gravada
    antes de esta seleção existir, seguir funcionando como sempre funcionou.
    """
    if not chaves:
        return list(linhas)
    escolhidos = set(chaves)
    return [l for l in linhas
            if chave_grupo_campanha(nome_da_linha(l, campos)) in escolhidos]


def padrao(grupos_, completo=False):
    """As chaves que já nascem marcadas.

    O que entregou, ou tudo quando nada entregou (ver o cabeçalho do módulo).
    `completo` força tudo — é o caso da verba.
    """
    todas = [g["chave"] for g in grupos_]
    if completo:
        return todas
    com_entrega = [g["chave"] for g in grupos_ if g["entregou"]]
    return com_entrega or todas


def aplicar(request, dados, chave_sessao, *, campos=NOMES_DESEMPENHO,
            entrega=ENTREGA_DESEMPENHO, padrao_completo=False):
    """`(linhas escolhidas, contexto da tela, dados da sessão)`.

    Chamada no topo da tela 02 de cada frente, ANTES de qualquer conta: o que
    não foi marcado não entra no consolidado, no texto nem no payload da IA.
    Filtrar depois seria filtrar a exibição de um número que já foi calculado
    com o arquivo inteiro.

    Aplicar uma seleção descarta a reescrita da IA junto, pelo mesmo motivo
    que trocar de arquivo descartaria: aquele texto foi escrito sobre outros
    números, e deixá-lo na tela é oferecer a leitura de uma coisa como se
    fosse de outra.

    Uma seleção vazia é recusada e a anterior permanece. Desmarcar tudo não é
    "todas as campanhas" — é uma tela sem análise nenhuma, e o silêncio faria
    parecer que o clique não funcionou.
    """
    linhas = dados.get("linhas") or []
    todos = grupos(linhas, campos=campos, entrega=entrega)
    validas = {g["chave"] for g in todos}

    marcadas = dados.get("campanhas")
    erro = None
    if request.method == "POST" and CAMPO in request.POST:
        pedidas = [c for c in request.POST.getlist("campanhas") if c in validas]
        if not pedidas:
            erro = ERRO_VAZIO
        else:
            marcadas = pedidas
            dados = dict(dados, campanhas=marcadas)
            dados.pop("texto_ia", None)
            dados.pop("mensagem_ia", None)
            request.session[chave_sessao] = dados
            request.session.modified = True

    # Sessão antiga, ou grupo que sumiu num reenvio: cair no padrão é melhor
    # do que devolver uma análise vazia por causa de uma chave morta.
    marcadas = [c for c in (marcadas or ()) if c in validas]
    if not marcadas:
        marcadas = padrao(todos, completo=padrao_completo)

    for g in todos:
        g["marcada"] = g["chave"] in marcadas
        # A tela precisa dizer isto ao lado do nome: no arquivo de referência
        # oito dos nove grupos estão parados, e sem o aviso a lista de caixas
        # parece nove opções equivalentes.
        g["sem_entrega"] = not g["entregou"]
        g["sem_nome"] = g["chave"] == GRUPO_SEM_NOME

    contexto = {
        "grupos_campanha": todos,
        # Uma caixa sozinha não é escolha — é ruído na tela. Mesma regra do
        # `_ComCampanhas` da Análise Geral.
        "tem_selecao": len(todos) > 1,
        "erro_campanhas": erro,
    }
    return filtrar(linhas, marcadas, campos), contexto, dados
