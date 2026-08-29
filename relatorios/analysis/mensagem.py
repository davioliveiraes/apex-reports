# -*- coding: utf-8 -*-
"""
Leitura Rápida — a mensagem de período que vai colada no grupo do cliente.

Terceiro destino da mesma `Avaliacao`. `templates.py` escreve a Análise do
Período que entra no PDF, em blocos rotulados; aqui o mesmo veredito vira o
formato que o operador manda no WhatsApp: duas linhas de cabeçalho, três
parágrafos corridos e uma pergunta de fechamento.

A forma não é escolha nossa — é o PROMPT DE ANÁLISE DE PERÍODO (v2) que o
operador usava à mão antes desta tela existir, e este módulo é a tradução
determinística dele. O que o prompt pede como instrução ("priorize
investimento, resultados e custo por resultado", "destaque melhor e pior
somente quando houver essa divisão", "não prometa resultados futuros") vira
aqui escolha de frase e ausência de frase; o botão de IA da tela reescreve o
mesmo conteúdo com o prompt original, quando o operador quiser outra redação.

Três coisas que o motor NÃO faz, e são justamente as que o prompt proíbe:

1. **Não compara com período anterior.** O export é o total do intervalo, e um
   arquivo só. Nenhuma frase daqui diz que algo subiu, caiu ou melhorou.
2. **Não inventa causa.** O único diagnóstico que sai é o de desgaste do
   criativo, e ele tem gatilho declarado (ver `tem_fadiga`).
3. **Não nomeia campanha como ela se chama na conta.** O que entra na frase é
   o rótulo já limpo pelo chamador — praça ou produto, sem colchete e sem
   nomenclatura interna.

Sobre gênero: nada aqui usa artigo antes do termo do resultado, exceto o
encerramento — que precisa de "quantas das conversas" ou "quantos dos leads" e
por isso recebe o gênero junto do termo (ver `indicadores.TERMOS`).
"""

from .benchmarks import ATENCAO, BOM, DISPERSAO_ALTA, OTIMO
from .numeros import decimal, inteiro, moeda
from . import rules

# `(singular, plural, gênero)`. O chamador manda o do indicador da conta; este
# é o neutro, que serve a qualquer objetivo sem mentir sobre nenhum.
TERMO_PADRAO = ("resultado", "resultados", "m")

CLASSIFICACAO = {OTIMO: "ÓTIMO", BOM: "BOM", ATENCAO: "ATENÇÃO"}

# Contração do plural, para o encerramento: "quantas DAS conversas".
_DAS = {"f": ("quantas", "das"), "m": ("quantos", "dos")}

# A partir de quantas vezes a diferença entre a ponta mais barata e a mais cara
# deixa de ser ruído do leilão e vira frase. Abaixo disto o texto nomeia os
# dois extremos sem quantificar a distância — dizer "1,1 vez mais caro" seria
# dar peso a uma diferença que não tem.
DIFERENCA_RELEVANTE = 1.3

# Pedido de material novo, palavra por palavra como o prompt do operador o
# escreve. Só sai quando `tem_fadiga` fecha — o prompt é explícito: "Se não
# houver esses sinais no relatório, não mencione fadiga de criativo."
PEDIDO_DE_CRIATIVOS = (
    "Os dados indicam que pode haver fadiga do criativo. Precisamos adicionar "
    "anúncios com novas imagens ou vídeos para ajudar a reengajar os públicos "
    "e melhorar o desempenho. Você consegue nos enviar novos materiais para "
    "produzirmos as próximas variações?"
)


def tem_fadiga(avaliacao):
    """Há sinal de desgaste do criativo neste relatório?

    O prompt do operador descreve três sintomas: frequência elevada ou em
    alta, CTR em queda e custo por resultado subindo ao longo do período. Dois
    deles são séries no tempo, e o export é o TOTAL do intervalo — não existe
    "em alta" nem "em queda" para medir num número só. Fingir que existe seria
    inventar a tendência, então o gatilho aqui é o que o dado sustenta:

    - frequência saturada, sozinha (o mesmo público já viu demais); ou
    - frequência elevada junto de CTR baixo — o público ainda não estourou,
      mas já reage pouco ao que vê.

    Erra para o lado de não pedir: um pedido de material a mais custa a
    confiança do cliente na leitura, e o operador pode acrescentá-lo à mão no
    texto, que é editável na tela.
    """
    return (avaliacao.tem("frequencia_saturada")
            or (avaliacao.tem("frequencia_elevada")
                and avaliacao.tem("ctr_baixo")))


def redigir_leitura(avaliacao, metricas, *, periodo="", recortes=(),
                    termo=TERMO_PADRAO):
    """A mensagem inteira, pronta para copiar.

    `recortes` é a divisão interna do relatório — uma entrada por campanha,
    já com o rótulo que o cliente lê: `{"rotulo", "resultados",
    "investimento"}`. Lista vazia é caso legítimo (conta de frente única), e o
    segundo parágrafo se ajusta em vez de sumir.
    """
    n = _numeros(metricas, avaliacao, termo)
    frentes = _frentes(recortes)
    blocos = [
        _cabecalho(avaliacao, periodo),
        _cenario(avaliacao, n),
        _comparacao(avaliacao, frentes, n),
        _conclusao(avaliacao, frentes, n),
    ]
    if tem_fadiga(avaliacao):
        blocos.append(PEDIDO_DE_CRIATIVOS)
    blocos.append(_encerramento(avaliacao, n))
    return "\n\n".join(b for b in blocos if b)


# ----------------------------------------------------------------------
# As frentes comparáveis
# ----------------------------------------------------------------------
def _frentes(recortes):
    """`(produtivas do mais barato ao mais caro, secas)`.

    "Seca" é a frente que consumiu verba e não registrou resultado: ela não
    entra na comparação de custo — não existe custo por resultado de zero
    resultado —, mas a existência dela muda o que o segundo parágrafo tem a
    dizer.

    O QUANTO essas frentes gastaram não é somado aqui, e sim lido de
    `avaliacao.derivados["verba_sem_retorno"]`. A diferença importa: o motor
    tira da conta quem gastou menos de 1,5 CPA, porque campanha que mal entrou
    no leilão ainda não deve resultado. Somar por fora seria cobrar do cliente
    uma verba que o motor decidiu não cobrar.
    """
    produtivas, secas = [], []
    for r in recortes:
        res = float(r.get("resultados") or 0.0)
        inv = float(r.get("investimento") or 0.0)
        linha = {"rotulo": r.get("rotulo") or "", "resultados": res,
                 "investimento": inv, "cpa": inv / res if res and inv else None}
        (produtivas if linha["cpa"] else secas).append(linha)
    produtivas.sort(key=lambda l: l["cpa"])
    return produtivas, secas


def _numeros(metricas, avaliacao, termo):
    singular, plural, genero = termo
    resultados = float(metricas.get("resultados") or 0.0)
    cpa = metricas.get("cpa")
    if cpa is None:
        cpa = metricas.get("custo_resultado")
    return {
        "singular": singular, "plural": plural, "genero": genero,
        "quantos": _DAS[genero][0], "das": _DAS[genero][1],
        "investimento": moeda(metricas.get("investimento")),
        "resultados_num": resultados,
        "resultados": inteiro(resultados),
        "cpa": moeda(cpa),
        "frequencia": decimal(metricas.get("frequencia")),
        "alcance_num": float(metricas.get("alcance") or 0.0),
        "alcance": inteiro(metricas.get("alcance")),
        "verba_sem_retorno": moeda(
            avaliacao.derivados.get("verba_sem_retorno")),
    }


# ----------------------------------------------------------------------
# Cabeçalho
# ----------------------------------------------------------------------
def _cabecalho(avaliacao, periodo):
    """As duas linhas de destaque, com asterisco simples — o único markup que
    o WhatsApp entende e o único que o prompt autoriza.

    Sem período no export não se inventa um: a linha some. O operador vê o
    aviso na tela e escreve as datas à mão, que é honesto; imprimir o mês
    corrente ali seria carimbar no relatório um intervalo que ninguém leu.
    """
    linhas = []
    if periodo:
        linhas.append(f"*Período analisado: {periodo}*")
    linhas.append("*Leitura do período: "
                  f"{CLASSIFICACAO[avaliacao.classificacao]}*")
    return "\n\n".join(linhas)


# ----------------------------------------------------------------------
# Parágrafo 1 — cenário geral
# ----------------------------------------------------------------------
_LEITURA_DO_CUSTO = {
    OTIMO: ("É um custo eficiente para esse tipo de captação: a verba do "
            "período se converteu em contato com folga, e o volume gerado "
            "sustenta essa leitura."),
    BOM: ("É um custo controlado para esse tipo de captação, com um volume "
          "consistente de oportunidades ao longo do período — a operação "
          "entregou o que a verba comportava, e ainda há espaço para ganhar "
          "eficiência."),
    ATENCAO: ("É um custo elevado para esse tipo de captação, e é ele que "
              "puxa a leitura do período: a mesma verba precisou disputar "
              "mais espaço no leilão para trazer cada contato."),
}

_RESSALVA_DE_AMOSTRA = (
    "O volume ainda é pequeno para uma leitura definitiva, então esses "
    "números valem como indicação de rumo, não como média firmada."
)

# O alcance entra porque explica o cenário — é a base de público de onde os
# contatos saíram —, e não porque é mais um número a citar. A frequência NÃO
# entra aqui: ela é o número do terceiro parágrafo quando há desgaste, e o
# prompt proíbe repetir o mesmo número em dois parágrafos.
_BASE_DE_PUBLICO = (
    "Os anúncios apareceram para {alcance} pessoas no período, e é dessa base "
    "de público que saíram os contatos."
)


def _cenario(avaliacao, n):
    """Investimento, volume e custo por resultado — nesta ordem, que é a
    prioridade que o prompt manda respeitar."""
    if avaliacao.tem(rules.SEM_RESULTADOS):
        return ("No período, investimos {investimento} e o relatório não "
                "registrou {plural} no intervalo. Sem resultado não há custo "
                "por {singular} a apurar, e é isso que define a leitura deste "
                "período.").format(**n)
    if avaliacao.tem(rules.SEM_INVESTIMENTO):
        return ("No período, o relatório registrou {resultados} {plural}, mas "
                "não trouxe o valor investido. Sem essa coluna não dá para "
                "apurar o custo por {singular}, que é o número que sustenta a "
                "leitura — e é por isso que este período fica em "
                "acompanhamento.").format(**n)

    frases = [
        ("No período, investimos {investimento} e geramos {resultados} "
         "{plural}, a um custo médio de {cpa} por {singular}.").format(**n),
        _LEITURA_DO_CUSTO[avaliacao.classificacao],
    ]
    if n["alcance_num"]:
        frases.append(_BASE_DE_PUBLICO.format(**n))
    if avaliacao.tem(rules.AMOSTRA_PEQUENA):
        frases.append(_RESSALVA_DE_AMOSTRA)
    return " ".join(frases)


# ----------------------------------------------------------------------
# Parágrafo 2 — comparação interna
# ----------------------------------------------------------------------
_SEM_DIVISAO = (
    "Todo o investimento do período ficou em uma frente só, então não há "
    "comparação interna entre praças ou campanhas a fazer: os números acima "
    "já descrevem o conjunto da operação."
)


def _comparacao(avaliacao, frentes, n):
    """Melhor e pior, com número — e só quando existe essa divisão.

    Quando não existe, o parágrafo diz que não existe em vez de sumir: três
    parágrafos é o formato acordado, e um cliente que recebe dois toda vez
    percebe que faltou alguma coisa.
    """
    produtivas, secas = frentes
    perdida = avaliacao.derivados.get("verba_sem_retorno") or 0.0

    if len(produtivas) >= 2:
        frases = [_extremos(produtivas, n)]
        if perdida:
            frases.append(
                ("Some-se a isso {verba_sem_retorno} que saíram sem registrar "
                 "{plural} no intervalo.").format(**n))
        elif avaliacao.tem(rules.RESULTADOS_CONCENTRADOS):
            frases.append(_concentracao(produtivas, n))
        return " ".join(frases)

    if len(produtivas) == 1:
        if not secas:
            # Uma campanha e mais nada: não há o que contrastar, e nomeá-la
            # seria pior do que não nomear. Com um nome só na conta,
            # `tokens_comuns` não tem com o que comparar e o rótulo sai com a
            # nomenclatura interna inteira — objetivo, produto e praça.
            return _SEM_DIVISAO
        unica = ("Só uma frente converteu no período: {rotulo}, a "
                 "{cpa_frente} por {singular}.").format(
                     rotulo=produtivas[0]["rotulo"],
                     cpa_frente=moeda(produtivas[0]["cpa"]), **n)
        if perdida:
            # A comparação existe, e é a mais dura que este relatório conta.
            return unica + (" As demais consumiram {verba_sem_retorno} sem "
                            "registrar {plural}, e é aí que está o principal "
                            "ponto de atenção em eficiência.").format(**n)
        return unica + (" As demais ainda não registraram {plural} no "
                        "intervalo, e o que gastaram é pequeno demais para "
                        "cobrar retorno delas neste período.").format(**n)

    if perdida:
        return ("O relatório não traz duas frentes com resultado para "
                "comparar entre si. O que ele mostra é {verba_sem_retorno} "
                "investidos sem {plural} registrados no intervalo, e é esse o "
                "ponto de atenção do período.").format(**n)
    return _SEM_DIVISAO


def _extremos(produtivas, n):
    melhor, pior = produtivas[0], produtivas[-1]
    razao = pior["cpa"] / melhor["cpa"]
    dados = dict(n, melhor=melhor["rotulo"], cpa_melhor=moeda(melhor["cpa"]),
                 pior=pior["rotulo"], cpa_pior=moeda(pior["cpa"]),
                 razao=decimal(razao))
    frase = ("O melhor desempenho ficou com {melhor}, a {cpa_melhor} por "
             "{singular}.").format(**dados)
    if razao >= DIFERENCA_RELEVANTE:
        frase += (" Na outra ponta, {pior} fechou a {cpa_pior}, e é o "
                  "principal ponto de atenção em eficiência do período — cada "
                  "contato custa {razao} vezes mais de uma ponta à "
                  "outra.").format(**dados)
    else:
        # Nomear um "ponto de atenção" onde a diferença é de centavos seria
        # fabricar um problema para ter o que escrever no parágrafo.
        frase += (" Na outra ponta, {pior} fechou a {cpa_pior} — as frentes do "
                  "período estão praticamente no mesmo patamar de "
                  "eficiência.").format(**dados)
    # O custo sozinho não diz quanto a diferença pesa: R$ 40 por contato numa
    # frente que trouxe três é outro problema que numa que trouxe oitenta.
    return frase + (" Em volume, foram {res_melhor} {plural} de um lado e "
                    "{res_pior} do outro.").format(
                        res_melhor=inteiro(melhor["resultados"]),
                        res_pior=inteiro(pior["resultados"]), **n)


def _concentracao(produtivas, n):
    total = sum(l["resultados"] for l in produtivas)
    lider = max(produtivas, key=lambda l: l["resultados"])
    fatia = round(lider["resultados"] / total * 100) if total else 0
    return ("Vale registrar que {fatia}% {das} {plural} do período vieram de "
            "{lider}.").format(fatia=fatia, lider=lider["rotulo"], **n)


# ----------------------------------------------------------------------
# Parágrafo 3 — conclusão
# ----------------------------------------------------------------------
_ABERTURA_DA_CONCLUSAO = {
    "desigual": ("No geral, os números mostram uma operação que funciona, mas "
                 "de forma desigual: o mesmo contato custa mais que o dobro "
                 "de uma frente para outra."),
    "variacao": ("No geral, os números mostram uma operação equilibrada, com "
                 "diferenças de eficiência entre as frentes que ainda cabem "
                 "na variação normal do leilão."),
    "concentrada": ("No geral, o período se apoiou numa frente principal, o "
                    "que dá previsibilidade enquanto ela funciona e concentra "
                    "o risco quando ela oscila."),
    "unica": ("No geral, o período descreve uma operação de frente única: a "
              "leitura fica mais simples, mas sobra menos margem de "
              "comparação para saber onde a verba rende mais."),
    "homogenea": ("No geral, os números mostram uma operação equilibrada, sem "
                  "uma frente destoando das outras."),
}

_ACOMPANHAMENTO = {
    OTIMO: ("O que merece maior acompanhamento no próximo ciclo é sustentar "
            "esse custo à medida que o volume cresce — é aí que a eficiência "
            "costuma ser testada."),
    BOM: ("O que merece maior acompanhamento no próximo ciclo é entender o "
          "que faz a frente mais barata entregar melhor e aproximar as demais "
          "desse patamar."),
    ATENCAO: ("O que merece maior acompanhamento no próximo ciclo é o custo "
              "por {singular}, começando por onde a verba está rendendo "
              "menos."),
}

# Sem divisão interna não há "frente mais barata" a citar no acompanhamento.
_ACOMPANHAMENTO_SEM_FRENTES = {
    BOM: ("O que merece maior acompanhamento no próximo ciclo é o custo por "
          "{singular}, que é o número que dita a eficiência da operação."),
}

# Sem resultado (ou sem a coluna de investimento) não existe custo por
# resultado, e as frases padrão apontariam para um número que a tela não tem.
_ACOMPANHAMENTO_SEM_CUSTO = (
    "O que merece maior acompanhamento no próximo ciclo é o registro dos "
    "contatos: sem esse dado no relatório não há custo a comparar, e é ele que "
    "diz se o que faltou foi contato ou foi medição."
)
_CONCLUSAO_SEM_CUSTO = (
    "No conjunto, é um período que não fecha uma leitura de eficiência — e é "
    "essa lacuna, antes do desempenho, o que precisa ser resolvido."
)

# O fecho do terceiro parágrafo: o que este período diz sobre a operação como
# um todo. Compromete com DIREÇÃO, nunca com número-alvo nem com promessa —
# é a mesma restrição que `templates.py` aplica ao bloco de objetivo do PDF.
_CONCLUSAO_DO_PERIODO = {
    OTIMO: ("No conjunto, é um período que valida o caminho atual: a estrutura "
            "no ar entrega contato a um custo que se sustenta."),
    BOM: ("No conjunto, é um período de operação estável, com o espaço de "
          "ganho conhecido e localizado em vez de espalhado."),
    ATENCAO: ("No conjunto, é um período que pede correção de rota antes de "
              "ampliar investimento: a estrutura no ar está entregando "
              "contato mais caro do que a captação comporta."),
}

_LEITURA_DA_FADIGA = (
    "Os dados também apontam desgaste dos anúncios: com a frequência em "
    "{frequencia}, o mesmo público já viu as peças muitas vezes, o que tende "
    "a encarecer cada novo contato."
)


def _conclusao(avaliacao, frentes, n):
    produtivas, _secas = frentes
    frases = [_ABERTURA_DA_CONCLUSAO[_forma(avaliacao, produtivas)]]
    sem_custo = avaliacao.tem(rules.SEM_RESULTADOS, rules.SEM_INVESTIMENTO)

    if sem_custo:
        acompanhamento = _ACOMPANHAMENTO_SEM_CUSTO
    elif len(produtivas) < 2:
        acompanhamento = _ACOMPANHAMENTO_SEM_FRENTES.get(
            avaliacao.classificacao, _ACOMPANHAMENTO[avaliacao.classificacao])
    else:
        acompanhamento = _ACOMPANHAMENTO[avaliacao.classificacao]
    frases.append(acompanhamento.format(**n))

    if tem_fadiga(avaliacao):
        frases.append(_LEITURA_DA_FADIGA.format(**n))
    frases.append(_CONCLUSAO_SEM_CUSTO if sem_custo
                  else _CONCLUSAO_DO_PERIODO[avaliacao.classificacao])
    return " ".join(frases)


def _forma(avaliacao, produtivas):
    """Que operação estes números descrevem — a chave da frase de abertura."""
    if len(produtivas) < 2:
        return "unica"
    razao = produtivas[-1]["cpa"] / produtivas[0]["cpa"]
    if razao >= DISPERSAO_ALTA:
        return "desigual"
    if avaliacao.tem(rules.RESULTADOS_CONCENTRADOS):
        return "concentrada"
    if razao >= DIFERENCA_RELEVANTE:
        return "variacao"
    return "homogenea"


# ----------------------------------------------------------------------
# Encerramento — a pergunta de conversão
# ----------------------------------------------------------------------
# Sempre presente, e sempre uma pergunta: é o que transforma o relatório em
# conversa e o que devolve à agência o dado que nenhum export tem — quantos
# dos contatos viraram venda. O motor já sabia que ela viria: `avaliar` marca
# `aguardando_dados_de_venda` desde antes desta tela existir.
_PERGUNTA_DE_CONVERSAO = (
    "Para fecharmos a leitura do período, você consegue nos informar {quantos} "
    "{das} {resultados} {plural} se transformaram em venda? Esse dado nos "
    "ajuda a direcionar o investimento para o que realmente converte."
)

# Sem resultado no relatório não há o que cruzar com venda. A pergunta muda de
# alvo em vez de sumir — o fechamento é o que abre a resposta do cliente.
_PERGUNTA_SEM_RESULTADO = (
    "Para fecharmos a leitura do período, você consegue confirmar se chegou "
    "algum contato pelos canais da loja neste intervalo? Esse dado nos ajuda "
    "a separar o que é entrega dos anúncios do que é registro do contato."
)


def _encerramento(avaliacao, n):
    if not n["resultados_num"]:
        return _PERGUNTA_SEM_RESULTADO
    return _PERGUNTA_DE_CONVERSAO.format(**n)
