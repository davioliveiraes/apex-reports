# -*- coding: utf-8 -*-
"""
Análise de Desempenho — dos conjuntos do export ao texto do cliente.

Motor próprio, e não uma reutilização do da Análise Geral (`analysis/rules.py`)
nem do da antiga Leitura Rápida (`analysis/mensagem.py`). Os dois classificam o
período em ÓTIMO/BOM/ATENÇÃO comparando o custo por resultado com a faixa
estimada de um perfil de negócio. Aqui isso seria chute com cara de método: o
preset `DESEMPENHO` não traz valor gasto, e a faixa do perfil nunca foi
calibrada para ele. Ver `classificar()` no fim do arquivo.

A unidade de análise são AS CAMPANHAS MARCADAS na tela — o mesmo bloco
`Campanhas incluídas` da Análise Geral, com as mesmas caixas (ver
`selecao_campanhas.py`). O arquivo costuma trazer várias: a conta de
referência traz nove, e oito estão paradas há meses, com zero em tudo.
Consolidar o arquivo inteiro fazia o texto falar dessas oito, e falar delas
como "conjuntos" — o preset é o mesmo nos dois níveis, e até 30/08/2026 o
parser só lia o nome do conjunto, que num export de campanhas não existe.
Toda linha ficava anônima e virava "Conjunto 1", "Conjunto 2".

Depois da seleção, o resto do arquivo deixa de existir para esta frente:
números, texto e payload da IA saem só do que ficou marcado. E o texto sabe
quantas campanhas ficaram: com uma é "a campanha", com várias é "as campanhas
selecionadas" — nunca "os conjuntos", que era o defeito de origem.

O que sobra é o que os números dizem sozinhos, e é bastante. Nenhuma frase
daqui afirma causa — "a frequência ficou em 4,75" é dado, "o criativo saturou"
seria diagnóstico, e diagnóstico exige contexto que uma planilha de treze
colunas não tem.

Sobre o investimento
--------------------
O preset não traz `Valor gasto`, mas ele é **recuperável**: `CPM × impressões
÷ 1000` é a definição do CPM invertida. É a única forma de consolidar custo
por resultado corretamente quando há vários conjuntos — a média simples dos
custos ignora que um conjunto gastou o triplo do outro, e a média ponderada
pelos resultados apaga o conjunto que gastou e não converteu.

Esse investimento **não aparece na tela nem no texto**: ele é peso de cálculo,
não métrica. Mostrá-lo seria anunciar um número que o operador não encontra no
Gerenciador com esse nome.
"""

from datetime import datetime

from .analysis.numeros import decimal, inteiro, moeda
from .indicadores import dominante, eh_conversa, rotulo, termos
from .parser_desempenho import ativa, periodo_do_relatorio

# Tokens do padrão de nomenclatura que não dizem nada ao cliente:
# `[ADV+][AUTO][LEADS][V1]` é objetivo, automação, objetivo de novo e versão —
# quatro colchetes, zero informação para quem recebe a mensagem. Sobrando nada
# legível, o conjunto vira "Conjunto 1" e o operador renomeia no texto, que é
# editável justamente por isto.
_JARGAO = frozenset((
    "abo", "cbo", "adv", "adv+", "advantage", "asc", "asc+", "auto",
    "leads", "lead", "msg", "mensagem", "mensagens", "conversas", "vendas",
    "trafego", "alcance", "engajamento", "conversao", "video", "reels",
))


def _numero(v):
    """Célula vazia é zero aqui — quem chama já decidiu que a soma existe."""
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _data(iso):
    """"2026-07-30" -> "30/07/2026". Texto de outra forma vem como veio."""
    if not iso:
        return ""
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)


def rotulo_da_linha(linha_ou_nome, indice):
    """O nome da linha como a INTERFACE o mostra.

    Prefere o nome da campanha e cai para o do conjunto — o preset sai das
    duas abas do Gerenciador. Nunca entra no texto do cliente: lá a campanha é
    "a campanha" (ver `redigir`), porque `[LEADS][CELULAR-BOLETO][BRAGANCA]` é
    nomenclatura interna nossa e não diz nada a quem recebe a mensagem.

    Mantém só os colchetes que não são jargão de operação e capitaliza o que
    sobrar. Nome fora do padrão de colchetes passa inteiro — aí ele já foi
    escrito por gente, e não há o que limpar.
    """
    if isinstance(linha_ou_nome, dict):
        linha_ou_nome = (linha_ou_nome.get("campanha")
                         or linha_ou_nome.get("conjunto"))
    bruto = str(linha_ou_nome or "").strip()
    if not bruto:
        return f"Linha {indice}"
    if "[" not in bruto:
        return bruto

    legiveis = []
    for token in bruto.replace("]", "[").split("["):
        token = token.strip()
        if not token or token.lower() in _JARGAO:
            continue
        # Marcador de versão ("V1", "V12") e data ("01SET25") não são nome.
        if token[0] in "Vv" and token[1:].isdigit():
            continue
        if any(c.isdigit() for c in token) and len(token) <= 8:
            continue
        legiveis.append(token.title() if token.isupper() else token)
    return " · ".join(legiveis) if legiveis else f"Linha {indice}"


# ----------------------------------------------------------------------
# Consolidação
# ----------------------------------------------------------------------
def consolidar(linhas):
    """Os números do período a partir das linhas do export.

    Aditivas somam; razões são recalculadas a partir do investimento
    recuperado, nunca pela média dos conjuntos (ver o cabeçalho do módulo).
    """
    conjuntos = [_conjunto(linha, i) for i, linha in enumerate(linhas, 1)]

    somar = lambda campo: sum(c[campo] for c in conjuntos)  # noqa: E731
    resultados = somar("resultados")
    impressoes = somar("impressoes")
    alcance = somar("alcance")
    conversas = somar("conversas")
    investimento = somar("investimento")

    for c in conjuntos:
        c["participacao"] = (c["resultados"] / resultados) if resultados else 0.0

    # O custo por conversa sai só dos conjuntos que reportaram conversa: numa
    # conta com objetivos misturados, dividir a verba inteira pelas conversas
    # de dois conjuntos cobraria delas o que os outros gastaram.
    com_conversa = [c for c in conjuntos if c["conversas"]]
    inv_conversa = sum(c["investimento"] for c in com_conversa)

    inicio, termino = periodo_do_relatorio(linhas)
    indicador = dominante(linhas)
    # Quantas campanhas distintas o operador deixou marcadas. É o único
    # número desta função que muda o TEXTO em vez dos totais, e ele existe
    # porque a seleção passou a ser múltipla em 31/08/2026.
    nomes = {c["campanha"] for c in conjuntos if c["campanha"]}
    return {
        "conjuntos": conjuntos,
        "n_conjuntos": len(conjuntos),
        "n_campanhas": len(nomes),
        "varias_campanhas": len(nomes) > 1,
        "n_ativos": sum(1 for c in conjuntos if c["ativa"]),
        "resultados": resultados,
        "impressoes": impressoes,
        "alcance": alcance,
        "conversas": conversas,
        "novos_contatos": somar("novos_contatos"),
        "custo_resultado": (investimento / resultados) if resultados else None,
        "custo_conversa": (inv_conversa / conversas) if conversas else None,
        "cpm": (investimento / impressoes * 1000) if impressoes else None,
        "frequencia": (impressoes / alcance) if alcance else None,
        # Alcance é o único total que não é exatamente aditivo: a mesma pessoa
        # atingida por dois conjuntos é contada duas vezes. Com um conjunto só
        # a soma é o número do Gerenciador; com vários, a frequência derivada
        # sai subestimada e a tela avisa.
        "alcance_somado": len(conjuntos) > 1,
        # Metade das conversas vindas de contato novo é o patamar a partir do
        # qual a leitura chama a participação de "relevante". Não é benchmark
        # de mercado — é a metade, e ela está escrita aqui em vez de solta
        # dentro de uma frase.
        "fatia_novos_alta": bool(
            somar("novos_contatos") and conversas
            and somar("novos_contatos") / conversas >= 0.5),
        "indicador": indicador,
        "rotulo_indicador": rotulo(indicador, avisar=False),
        "termos": termos(indicador),
        "eh_conversa": eh_conversa(indicador),
        "inicio": inicio,
        "termino": termino,
        "periodo": (f"{_data(inicio)} a {_data(termino)}"
                    if inicio and termino else ""),
        "investimento": investimento,
    }


def _conjunto(linha, indice):
    """Uma linha do export com o investimento recuperado."""
    impressoes = _numero(linha.get("impressoes"))
    cpm = linha.get("cpm")
    resultados = _numero(linha.get("resultados"))
    custo = linha.get("custo_resultado")

    if cpm is not None and impressoes:
        investimento = float(cpm) * impressoes / 1000.0
    elif custo is not None and resultados:
        # Sem CPM (conjunto sem entrega, ou coluna em branco), o custo por
        # resultado dá o mesmo gasto por outro caminho.
        investimento = float(custo) * resultados
    else:
        investimento = 0.0

    veiculacao = str(linha.get("veiculacao") or "").strip()
    # O export no nível de campanha não traz a coluna de veiculação. Nesse
    # caso, o próprio Meta só preenche `Indicador de resultados` na linha que
    # teve o resultado configurado/entregue; as linhas inativas do arquivo de
    # referência deixam o campo vazio. Um status explícito continua soberano:
    # `paused` não vira ativo só porque há um indicador histórico.
    indicador_preenchido = bool(str(linha.get("indicador") or "").strip())
    esta_ativa = ativa(veiculacao) if veiculacao else indicador_preenchido

    return {
        # O nome CRU, como ele está na planilha — é por ele que o operador
        # acha a linha no Gerenciador. Lê as duas colunas porque o preset sai
        # das duas abas; ler só a do conjunto deixava todo export de campanhas
        # sem nome nenhum.
        "nome": (linha.get("campanha") or linha.get("conjunto") or "").strip(),
        # Separado do `nome` de propósito: é ele que diz quantas CAMPANHAS
        # entraram na leitura, e num export de conjuntos sem coluna de
        # campanha ele fica vazio — aí a análise é de uma campanha só, ainda
        # que sobre várias linhas, e o texto continua no singular.
        "campanha": str(linha.get("campanha") or "").strip(),
        "rotulo": rotulo_da_linha(linha, indice),
        "veiculacao": veiculacao,
        "ativa": esta_ativa,
        "resultados": resultados,
        "custo_resultado": (float(custo) if custo is not None
                            else (investimento / resultados
                                  if resultados else None)),
        "alcance": _numero(linha.get("alcance")),
        "impressoes": impressoes,
        "frequencia": linha.get("frequencia"),
        "cpm": cpm,
        "conversas": _numero(linha.get("conversas")),
        "custo_conversa": linha.get("custo_conversa"),
        "novos_contatos": _numero(linha.get("novos_contatos")),
        "investimento": investimento,
    }


# ----------------------------------------------------------------------
# O texto do cliente
# ----------------------------------------------------------------------
# Como o texto se refere ao que foi analisado. Duas colunas, e não uma frase
# montada com `if` no meio de cada parágrafo: assim dá para ler de cima a
# baixo o vocabulário inteiro da frente, e é onde se confere que a palavra
# "conjunto" não aparece em lugar nenhum.
_VOZ = {
    False: {"sujeito": "a campanha", "Sujeito": "A campanha",
            "registrou": "registrou", "nao_registrou": "não registrou",
            "alcancou": "alcançou", "sustentou": "sustentou",
            "teve": "teve", "e_registrou": "registrou"},
    True:  {"sujeito": "as campanhas selecionadas",
            "Sujeito": "As campanhas selecionadas",
            "registrou": "registraram", "nao_registrou": "não registraram",
            "alcancou": "alcançaram", "sustentou": "sustentaram",
            "teve": "tiveram", "e_registrou": "registraram"},
}


def voz(agregado):
    """O vocabulário do texto: singular com uma campanha, plural com várias."""
    return _VOZ[bool(agregado.get("varias_campanhas"))]


def redigir(agregado):
    """A leitura das campanhas marcadas, pronta para colar no WhatsApp.

    Um título curto e três parágrafos, sempre os mesmos: o que foi produzido,
    como a entrega aconteceu, e o que se lê disso. Sem comparação entre
    campanhas — o que ficou marcado entra somado, e o que ficou de fora não
    entra nem como pano de fundo.

    A campanha nunca é chamada pelo nome. `[LEADS][CELULAR-BOLETO][BRAGANCA]`
    é a nossa nomenclatura interna e não diz nada a quem recebe a mensagem; o
    nome fica na tela, onde o operador confere o que está lendo.
    """
    paragrafos = (_resultado(agregado), _entrega(agregado),
                  _leitura(agregado))
    return "\n\n".join(("*Desempenho*", *(p for p in paragrafos if p)))


def _resultado(ag):
    """Parágrafo 1 — o que a campanha produziu e a que custo.

    O indicador vira prosa: um resultado que o Meta chama de
    `actions:onsite_conversion.messaging_conversation_started_7d` é uma
    conversa, e é assim que ele aparece. "557 resultados" seria fiel à coluna
    e opaco para o cliente.
    """
    singular, plural, _ = ag["termos"]
    v = voz(ag)
    total = ag["resultados"]
    periodo = (f"Entre {_data(ag['inicio'])} e {_data(ag['termino'])}"
               if ag["periodo"] else "No período analisado")

    if not total:
        return f"{periodo}, {v['sujeito']} {v['nao_registrou']} {plural}."

    frase = (f"{periodo}, {v['sujeito']} {v['registrou']} {inteiro(total)} "
             f"{plural if total != 1 else singular}")
    if ag["custo_resultado"]:
        frase += (f", com custo médio de {moeda(ag['custo_resultado'])} por "
                  f"{singular}")
    return frase + "."


def _entrega(ag):
    """Parágrafo 2 — quanta gente, quantas vezes, a que preço, e quantos novos.

    A frequência entra como frequência e o CPM como CPM, sem tradução
    didática e sem adjetivo: não há faixa de referência calibrada para este
    preset (ver `classificar`), então "alta" ou "barato" seriam invenção com
    cara de método.
    """
    frases = []
    v = voz(ag)
    alcance, impressoes = ag.get("alcance"), ag.get("impressoes")
    if alcance or impressoes:
        f = v["Sujeito"]
        if alcance:
            f += f" {v['alcancou']} {inteiro(alcance)} pessoas"
        if impressoes:
            f += f" e {v['e_registrou']} " if alcance else f" {v['registrou']} "
            f += f"{inteiro(impressoes)} impressões"
        detalhes = []
        if ag.get("frequencia"):
            detalhes.append(f"frequência média de {decimal(ag['frequencia'])}")
        if ag.get("cpm"):
            detalhes.append(f"CPM de {moeda(ag['cpm'])}")
        if detalhes:
            f += ", com " + " e ".join(detalhes)
        frases.append(f + ".")

    novos = _novos_contatos(ag)
    if novos:
        frases.append(novos)
    return " ".join(frases)


def _novos_contatos(ag):
    """Quantos contatos eram novos, e que fatia das conversas isso representa.

    A frase descreve a MÉTRICA, não a história de quem escreveu: "387 foram
    classificados como novos contatos pelo Meta" é o que a coluna diz; "387
    nunca haviam falado com a empresa" seria uma afirmação sobre pessoas que o
    Meta não faz e que nós não temos como conferir.
    """
    novos = ag.get("novos_contatos") or 0.0
    conversas = ag.get("conversas") or 0.0
    if not novos:
        return ""
    if not conversas:
        return f"Foram {inteiro(novos)} novos contatos no período."
    return (f"Das {inteiro(conversas)} conversas, {inteiro(novos)} foram "
            "classificados como novos contatos pelo Meta, representando "
            f"aproximadamente {_fatia(novos, conversas)} do total.")


def _leitura(ag):
    """Parágrafo 3 — a leitura executiva.

    Costurada a partir do que o arquivo sustenta, e nada além. Nenhuma frase
    aqui classifica um número como bom ou ruim: sem faixa de referência isso
    seria opinião vestida de análise. O que ela faz é apontar o que merece
    acompanhamento — que é diferente de apontar um culpado.
    """
    singular, plural, _ = ag["termos"]
    v = voz(ag)
    partes = []

    if ag["resultados"]:
        # Sem repetir o custo nem o volume: os dois já foram ditos no primeiro
        # parágrafo, e renumerá-los aqui é o que faz uma leitura de três
        # parágrafos parecer preenchimento de espaço.
        f = (f"No período, {v['sujeito']} {v['sustentou']} a geração de "
             f"{plural}")
        if ag.get("fatia_novos_alta"):
            f += " com participação relevante de novos contatos"
        partes.append(f + ".")
    else:
        partes.append(f"No período, {v['sujeito']} {v['teve']} entrega mas "
                      f"{v['nao_registrou']} {plural} — vale revisar a "
                      "configuração antes de seguir.")

    if ag.get("frequencia"):
        partes.append(
            f"A frequência ficou em {decimal(ag['frequencia'])}, mostrando uma "
            "exposição recorrente ao mesmo público, e é um ponto para "
            "acompanhar nas próximas leituras junto à evolução do custo por "
            f"{singular}.")
    return " ".join(partes)


def _fatia(parte, total):
    """"69%" — sem casa decimal.

    "69,48%" numa mensagem de WhatsApp é precisão que ninguém pediu e que
    denuncia número jogado direto do cálculo para a frase.
    """
    return f"{round(parte / total * 100)}%" if total else ""


# ----------------------------------------------------------------------
# Classificação — o lugar reservado, ainda vazio
# ----------------------------------------------------------------------
def classificar(agregado):
    """Sempre `None`: não há metodologia de classificação para este preset.

    A Análise Geral classifica o período comparando o custo por resultado com
    a faixa estimada do perfil de negócio (`analysis/benchmarks.py`), e essa
    faixa foi calibrada com investimento real, campanha a campanha. O preset
    `DESEMPENHO` não traz investimento, não traz perfil e não traz meta — dar
    um selo "BOM" a partir daqui seria inventar o método e depois acreditar
    nele.

    Quando existir faixa oficial para este preset, é esta função que passa a
    devolver o selo; `views_desempenho` e o template já tratam `None` como
    "sem classificação" e não precisam mudar.
    """
    return None


def resumo(agregado):
    """As métricas do topo da tela, já formatadas (ver §11 da especificação).

    O template não formata dinheiro: a locale do projeto é pt-BR e um
    `floatformat` escreveria "17,78" onde o resto do produto escreve
    "R$ 17,78".
    """
    traco = "—"
    cartoes = [
        ("Resultados", inteiro(agregado["resultados"])),
        ("Custo por resultado",
         moeda(agregado["custo_resultado"]) if agregado["custo_resultado"]
         else traco),
        ("Conversas iniciadas", inteiro(agregado["conversas"])),
        ("Custo por conversa",
         moeda(agregado["custo_conversa"]) if agregado["custo_conversa"]
         else traco),
        ("Novos contatos", inteiro(agregado["novos_contatos"])),
        ("Alcance", inteiro(agregado["alcance"])),
        ("Impressões", inteiro(agregado["impressoes"])),
        ("Frequência",
         decimal(agregado["frequencia"]) if agregado["frequencia"] else traco),
        ("CPM", moeda(agregado["cpm"]) if agregado["cpm"] else traco),
    ]
    return [{"rotulo": r, "valor": v} for r, v in cartoes]
