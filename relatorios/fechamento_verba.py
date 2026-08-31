# -*- coding: utf-8 -*-
"""
Fechamento de verba — as fórmulas, o status e os dois blocos de saída.

Determinístico de ponta a ponta, e por escolha: o prompt de Fechamento de Verba
não é um pedido de redação, é uma tabela de decisão. As fórmulas são fechadas e
cada faixa de desvio já tem UMA frase escrita, então o código as aplica sem
rede, sem crédito e sem a chance de o modelo errar uma divisão em silêncio. A
IA entra depois, por botão, só para reescrever o texto (ver
`redator_ia.reescrever`, com `PROMPT_REESCRITA_VERBA`).

O denominador do ritmo continua sendo o número mais delicado daqui, mesmo sem
projeção — é ele que separa "gastou pouco" de "rodou pouco". O caso Rei do
Celular no guia: campanha no ar desde 17/08 num export de 01/08 a 24/08,
R$ 990/mês contratados, R$ 466,75 gastos.

    gasto ÷ 24 dias apurados   -> R$ 19/dia  (parece subentrega)
    gasto ÷  8 dias veiculados -> R$ 58/dia  (entregou acima do contratado)

O desvio compara o gasto com o previsto dos 24 dias e dá -39%, porque o
cliente pagou por um período em que a entrega não aconteceu — isso é fato e
vai para a mensagem. Mas `ritmo_real` e `taxa_escoamento` dividem pelos dias
VEICULADOS, e é essa segunda conta que diz ao operador que o problema foi a
campanha ter subido tarde, não o leilão. Sem ela, as duas histórias sairiam
com a mesma cara. `periodo_parcial` marca o caso e troca a frase de status.

O que se apura é o RECORTE DO EXPORT, e nada além dele (31/08/2026)
--------------------------------------------------------------------
Até aqui o módulo projetava: o export dizia onde o ciclo começava, uma janela
de mês (ou semana, ou quinzena) dizia onde ele terminaria, e o gasto medido
era esticado até lá. Com três dias de arquivo e um ciclo suposto de 31, isso
produzia uma projeção de R$ 3.735 a partir de R$ 361 gastos — um número que
descreve uma hipótese, não a conta.

Hoje o período apurado é o intervalo que o arquivo declara, ponto. Dele saem
os dias, o previsto e o desvio; não há dia restante para projetar, e por isso
não há projeção. A pergunta da frente deixou de ser "vai fechar no combinado?"
e passou a ser "fechou no combinado?" — uma troca de previsão por exatidão,
feita de propósito.

A periodicidade sobreviveu, mas com um trabalho só: dizer em que UNIDADE o
valor foi contratado, para virar diária. R$ 990/mês são R$ 32/dia num mês de
31; R$ 300/semana são R$ 43/dia; R$ 150/dia já são R$ 150/dia. É a diária que
multiplica os dias apurados e vira o previsto do período.

Duas coisas caíram junto, e nenhuma faz falta:

* o alerta de "export maior que o ciclo" — exportar trinta dias para quem
  fecha por semana já não erra número nenhum, porque o previsto acompanha os
  dias apurados;
* a linha de correção do diário — não há dias restantes sobre os quais
  corrigir. No lugar dela a análise interna diz a diferença em reais.

E o ciclo é ancorado no ARQUIVO, não no relógio nem num campo digitado. O
export declara o próprio recorte (`Início dos relatórios` / `Encerramento dos
relatórios`), e é o fim desse recorte que diz até quando há gasto medido. Isso
apagou de uma vez o campo "data de hoje" e a classe inteira de erro que ele
carregava: gasto de um intervalo projetado sobre outro.
"""

import calendar
from datetime import date, datetime, timedelta

# ----------------------------------------------------------------------
# Textos — editáveis sem mexer na lógica
# ----------------------------------------------------------------------
# O ciclo do contrato. Não é preferência de exibição: é a janela sobre a qual
# o gasto é projetado e contra a qual o desvio é medido. Cliente que fecha por
# semana e é medido contra o mês recebe um desvio que não diz nada sobre o que
# ele contratou.
CICLO_MENSAL = "mensal"
CICLO_QUINZENAL = "quinzenal"
CICLO_SEMANAL = "semanal"
# O contrato cotado por DIA. Não é um quarto tamanho de janela: é a unidade em
# que o valor foi combinado. Quem fecha a R$ 150/dia continua fechando por mês
# — e a conta que ele não deve ser obrigado a fazer na mão é justamente
# 150 × 31. A janela deste ciclo é a mensal (ver `janela`); o que muda é o
# sentido do número digitado, que aqui JÁ É o diário.
CICLO_DIARIO = "diario"

DIAS_DA_SEMANA = 7
DIAS_DA_QUINZENA = 15

STATUS_PARCIAL = "parcial"
STATUS_ALINHADO = "alinhado"
STATUS_POUCO_ACIMA = "pouco_acima"
STATUS_ACIMA = "acima"
STATUS_POUCO_ABAIXO = "pouco_abaixo"
STATUS_ABAIXO = "abaixo"

# Como cada ciclo é chamado dentro das frases. Português não deixa
# parametrizar "o mês"/"a semana" com uma variável só: muda o artigo, muda a
# concordância de "cheio"/"cheia". Um vocabulário por ciclo resolve os dois
# sem duplicar as seis frases.
# A unidade em que o contratado foi combinado — o que vem depois da barra em
# "R$ 990/mês". É o que sobrou do vocabulário de ciclo: as frases que
# conjugavam "o mês"/"a semana"/"do mês cheio" descreviam uma janela futura, e
# essa janela deixou de existir quando o período apurado virou o recorte do
# export.
VOCABULARIO = {
    CICLO_MENSAL: {"unidade": "mês"},
    CICLO_QUINZENAL: {"unidade": "quinzena"},
    CICLO_SEMANAL: {"unidade": "semana"},
    CICLO_DIARIO: {"unidade": "dia"},
}

# Seção 5 do prompt do operador, na íntegra. Em ciclo parcial a frase de
# parcial substitui as demais — o desvio contra o contratado deixa de ser
# indicador válido quando o ciclo não rodou inteiro.
# Todas no tempo do que já aconteceu. As antigas prometiam o fechamento de uma
# janela futura ("o mês deve fechar no valor combinado"); sem projeção, prometer
# fechamento seria falar de um período que este arquivo não mede.
#
# E nenhuma delas trata subentrega como falha da agência. A divisão de
# responsabilidade é literal: **a agência configura o orçamento; quem decide
# quanto gastar por dia é o sistema de entrega do Meta**, que distribui pelo
# leilão e com frequência não consome o valor diário cheio. Um orçamento de
# R$ 150/dia é um teto que a plataforma pode ou não preencher, e isso não está
# sob controle de quem opera a conta.
#
# As frases de subentrega diziam "estou verificando o motivo antes de qualquer
# ajuste de verba", e a pergunta era "te retorno ainda hoje com o motivo".
# Escritas assim, admitiam um erro que não houve e prometiam uma apuração que
# não tem o que apurar. Hoje elas dizem o mecanismo — que é informação útil ao
# cliente e verdadeira.
FRASES_STATUS = {
    STATUS_PARCIAL: ("As campanhas entraram no ar dia {dia}, então o período "
                     "ficou parcial — foram {dias} dias de veiculação dentro "
                     "dos {apurados} apurados."),
    STATUS_ALINHADO: "O ritmo do período ficou alinhado com o contratado.",
    STATUS_POUCO_ACIMA: ("O ritmo do período ficou um pouco acima do "
                         "contratado e já vou ajustar o diário."),
    STATUS_ACIMA: ("O ritmo do período ficou acima do contratado e já estou "
                   "ajustando o diário."),
    STATUS_POUCO_ABAIXO: ("O período fechou um pouco abaixo do previsto. O "
                          "orçamento seguiu configurado o tempo todo — a "
                          "entrega do Meta oscila conforme o leilão e nem "
                          "sempre consome o valor diário cheio."),
    STATUS_ABAIXO: ("O período fechou abaixo do previsto. O orçamento seguiu "
                    "configurado o tempo todo; quem define quanto gastar por "
                    "dia é a entrega do Meta, e ela varia com o leilão — em "
                    "dias de menor disputa a plataforma não usa todo o "
                    "diário."),
}

# A seção 6 exige terminar com pergunta fechada, mas não diz quais são — estas
# foram escritas aqui e ficam isoladas de propósito, para serem conferidas e
# trocadas sem tocar em fórmula nenhuma. Fechadas mesmo: todas se respondem
# com sim ou não.
PERGUNTAS = {
    STATUS_PARCIAL: "Podemos seguir assim?",
    STATUS_ALINHADO: "Podemos seguir assim?",
    STATUS_POUCO_ACIMA: "Confirma o ajuste do diário?",
    STATUS_ACIMA: "Confirma o ajuste do diário?",
    STATUS_POUCO_ABAIXO: "Podemos seguir com o mesmo diário configurado?",
    STATUS_ABAIXO: "Podemos seguir com o mesmo diário configurado?",
}

# Marca a pendência quando o contratado não foi informado (seção 2 do
# prompt: "campo vazio não se inventa").
_PENDENTE = "R$ [contratado]"

# Sem saudação, e de propósito: "Bom dia" numa mensagem que sai às sete da
# noite mente na primeira palavra, e a hora do envio não é decidida aqui.
ABERTURA = "Passando o fechamento de verba pra confirmar 👇"

# Faixas de desvio da seção 5, em pontos percentuais.
ALINHADO = 3.0
AJUSTE_LEVE = 10.0
# Faixa em que o escoamento não é notícia — fora dela vira origem do desvio.
ESCOAMENTO_OK = (95.0, 105.0)

# A heurística do teto (gasto acima de 1,5× o que o configurado explicava)
# saiu em 29/08/2026, e não porque errava: porque virou desnecessária. Ela
# tentava adivinhar quando o recorte do arquivo não batia com o ciclo do
# contrato — pergunta que deixou de existir em 31/08/2026, quando o recorte do
# arquivo PASSOU A SER o período apurado. Uma heurística com falso positivo
# conhecido (mudança grande de orçamento no meio do ciclo dava o mesmo sinal)
# não se mantém ao lado da conta certa.


# ----------------------------------------------------------------------
# Formatação
# ----------------------------------------------------------------------
def reais(valor, vazio="—"):
    """`R$ 1.003` — sem centavos, milhar com ponto (seção 4 do prompt).

    `vazio` é o que sai no lugar de um valor ausente. Na mensagem o contratado
    vira `R$ [contratado]`, marcado como pendência: campo vazio não se inventa,
    e um traço ali passaria por número lido.
    """
    if valor is None:
        return vazio
    return "R$ " + f"{round(valor):,}".replace(",", ".")


def pct(valor, casas=1):
    if valor is None:
        return "—"
    return f"{valor:.{casas}f}".replace(".", ",") + "%"


def dias_do_mes(dia):
    """Dias reais do mês — 28, 29, 30 ou 31, nunca 30 fixo (seção 4).

    Público porque o parser precisa do mesmo número antes do cálculo: é por ele
    que um orçamento vitalício sem data de término vira equivalente diário.
    """
    return calendar.monthrange(dia.year, dia.month)[1]


def dias_do_contrato(inicio, periodo=CICLO_MENSAL):
    """Quantos dias tem UM ciclo do contrato — só para virar diária.

    Era `janela()`, e devolvia as duas pontas de uma janela futura sobre a
    qual o gasto era projetado. Essa janela deixou de existir em 31/08/2026:
    o que se apura é o recorte do export (ver o cabeçalho do módulo). O que
    sobrou desta função é a única coisa que a periodicidade ainda decide —
    por quanto se divide o valor contratado para chegar à diária.

    Semana e quinzena são fixas. Mês é o do calendário a partir de `inicio`:
    "até a véspera do mesmo dia no mês seguinte", o que dá 28 a 31 dias. Dia
    que não existe no mês seguinte encosta no último dele — 31/01 conta 28
    dias, porque o próximo ciclo começaria em 28/02.

    `CICLO_DIARIO` também cai no mês e nunca é usado: naquele ciclo o valor
    digitado JÁ É a diária, e `_normalizar_contratado` não divide nada.
    """
    if periodo == CICLO_SEMANAL:
        return DIAS_DA_SEMANA
    if periodo == CICLO_QUINZENAL:
        return DIAS_DA_QUINZENA
    return (_mesmo_dia_no_mes_seguinte(inicio) - inicio).days


def _mesmo_dia_no_mes_seguinte(dia):
    ano, mes = ((dia.year + 1, 1) if dia.month == 12
                else (dia.year, dia.month + 1))
    return date(ano, mes, min(dia.day, calendar.monthrange(ano, mes)[1]))


def _data(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()[:10]
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


# ----------------------------------------------------------------------
# Os números
# ----------------------------------------------------------------------
def calcular(estruturas, contratado_ciclo=None, periodo=CICLO_MENSAL,
             inicio_relatorio=None, termino_relatorio=None):
    """Os números do fechamento a partir do que o arquivo declara.

    O par `inicio_relatorio`/`termino_relatorio` é o recorte que o EXPORT
    traz, e ele É o período apurado — as duas pontas, inclusive. Não existe
    "hoje" aqui, nem calendário, nem janela suposta: o arquivo diz de quando
    até quando houve gasto medido, e é sobre esses dias que tudo é calculado.

    `periodo` diz apenas em que unidade o contratado foi combinado, para virar
    diária (ver `dias_do_contrato`). Ele não decide mais quantos dias se apura.

    A contrapartida é que a aplicação confia no intervalo escolhido no
    Gerenciador: exportar sete dias de um cliente mensal produz o fechamento
    correto DAQUELES sete dias, e não do mês. O período apurado aparece escrito
    na tela e na mensagem justamente por isso — é o que deixa o erro de recorte
    visível para quem confere.

    `gasto` soma **todas** as linhas, inclusive pausadas e zeradas: conjunto
    parado com R$ 0,00 é informação, e removê-lo erraria a soma do período.

    O DIÁRIO não é lido da planilha. R$ 300 por semana são R$ 43/dia porque a
    semana tem 7 dias, e é essa diária que multiplica os dias apurados. Antes
    o diário saía da soma dos orçamentos configurados no Meta, e bastava a
    conta ser `[ABO]` sem o export de conjunto para ele virar R$ 0/dia num
    fechamento com R$ 1.304 gastos. O que está setado no Meta continua visível
    na tabela de conferência; ele só não decide número nenhum.
    """
    ate = _data(termino_relatorio) or date.today()
    desde = _data(inicio_relatorio) or ate
    # O período apurado, inclusivo nas duas pontas: o dia do término do
    # relatório é um dia COM gasto medido.
    dias_apurados = max((ate - desde).days + 1, 1)
    rotulo = f"o período de {desde:%d/%m} a {ate:%d/%m}"

    do_contrato = dias_do_contrato(desde, periodo)
    unidade, diario = _normalizar_contratado(contratado_ciclo, do_contrato,
                                             periodo)
    previsto = diario * dias_apurados if diario else None

    gasto = sum(e.get("gasto") or 0.0 for e in estruturas)

    # O piso é o começo do recorte: o gasto só existe dentro do arquivo, e
    # contar dias fora dele dividiria o dinheiro por um tempo em que ele não
    # foi medido.
    inicio_ref, dias_veiculados = _dias_veiculados(estruturas, ate, desde)
    ritmo_real = gasto / dias_veiculados

    desvio = (gasto / previsto - 1) * 100 if previsto else None
    # Quanto a conta entregou por dia contra o que o contrato pede por dia.
    escoamento = ritmo_real / diario * 100 if diario else None
    diferenca = (gasto - previsto) if previsto is not None else None

    parcial = dias_veiculados < dias_apurados
    calc = {
        # As duas pontas do que o arquivo mediu. São elas que a mensagem
        # imprime, e elas vêm do export — não do relógio.
        "ate": ate,
        "desde": desde,
        "periodo": periodo,
        "rotulo": rotulo,
        "dias_apurados": dias_apurados,
        # Quantos dias tem um ciclo do contrato. Só serve para a divisão que
        # produziu a diária; nenhum outro número depende dele.
        "dias_do_contrato": do_contrato,
        "dias_veiculados": dias_veiculados,
        "inicio_veiculacao": inicio_ref,
        # O valor como foi digitado, na unidade escolhida.
        "contratado_unidade": unidade,
        "contratado_diario": diario,
        "previsto_periodo": previsto,
        "gasto": gasto,
        "ritmo_real": ritmo_real,
        "desvio_pct": desvio,
        "taxa_escoamento": escoamento,
        "diferenca": diferenca,
        "periodo_parcial": parcial,
    }
    calc["status"] = _status(desvio, parcial)
    calc["origens"] = _origens(calc)
    return calc


def _normalizar_contratado(valor, dias, periodo=CICLO_MENSAL):
    """`(o que foi digitado, a diária)` — seção 2 do prompt.

    Um número é digitado e a diária sempre sai dele. Quem diz como é a
    unidade escolhida: R$ 300 por semana são R$ 43/dia porque a semana tem 7
    dias, R$ 990 por mês são R$ 32/dia porque agosto tem 31, e R$ 150 por dia
    já são R$ 150/dia — nesse não há divisão nenhuma.

    A diária é o único número do contrato que entra em conta daqui em diante:
    é ela que multiplica os dias apurados e vira o previsto do período.
    Nunca há dois campos digitados para discordarem um do outro.
    """
    if not valor:
        return None, None
    if periodo == CICLO_DIARIO:
        return valor, valor
    return valor, valor / dias


def _dias_veiculados(estruturas, ate, piso):
    """`(início de referência, dias)` — do menor `Início` até o fim do export.

    `ate` é INCLUSIVO: é o último dia com gasto medido, e não o "ontem" de um
    dia que ainda está correndo. `piso` é o mais tarde entre o começo do ciclo
    e o começo do recorte do export — nenhum dos dois pode ser ultrapassado
    por baixo.

    Três correções sobre a leitura literal do prompt, e as três mudam número:

    1. **Trava no primeiro dia do ciclo.** Campanha contínua que subiu em
       março daria 170+ dias veiculados e diluiria o ritmo até a projeção
       virar ficção. O que se mede é o ciclo corrente — o mês, ou a semana
       para quem fecha por semana.
    2. **Trava também no começo do export.** O gasto só existe dentro do
       recorte do arquivo; contar dias fora dele dividiria o dinheiro por um
       tempo em que ele não foi medido.
    3. **Só campanhas que gastaram.** `dias_veiculados` é o denominador de
       `gasto ÷ dias`; campanha que não gastou nada não entra no numerador, e
       deixá-la esticar o denominador produz exatamente o artefato que a nota
       do guia sobre a coluna `Início` manda evitar. Sem nenhuma que tenha
       gasto, cai no conjunto todo.
    """
    def inicios(filtradas):
        return [d for d in (_data(e.get("inicio")) for e in filtradas) if d]

    com_gasto = [e for e in estruturas if (e.get("gasto") or 0) > 0]
    datas = inicios(com_gasto) or inicios(estruturas)
    inicio_ref = max(min(datas), piso) if datas else piso
    return inicio_ref, max(1, (ate - inicio_ref).days + 1)


def _status(desvio, parcial):
    if parcial:
        return STATUS_PARCIAL
    if desvio is None:
        return STATUS_ALINHADO
    if abs(desvio) <= ALINHADO:
        return STATUS_ALINHADO
    if desvio > AJUSTE_LEVE:
        return STATUS_ACIMA
    if desvio > ALINHADO:
        return STATUS_POUCO_ACIMA
    if desvio >= -AJUSTE_LEVE:
        return STATUS_POUCO_ABAIXO
    return STATUS_ABAIXO


def _origens(calc):
    """As origens possíveis, **nesta ordem**, e só as que se aplicam.

    Eram três. A origem "configuração" — diário configurado no Meta contra
    diário contratado — saiu em 29/08/2026 junto com a leitura do orçamento da
    planilha: os dois números viraram o mesmo, e comparar um número consigo
    mesmo nunca acusa nada. O que o Meta tem setado continua na tabela de
    conferência, para o operador ver de olho.
    """
    origens = []
    if calc["periodo_parcial"]:
        origens.append(
            f"período parcial — {calc['dias_veiculados']} dias veiculados de "
            f"{calc['dias_apurados']} apurados, início em "
            f"{calc['inicio_veiculacao']:%d/%m}")
    escoamento = calc["taxa_escoamento"]
    if escoamento is not None and not (ESCOAMENTO_OK[0] <= escoamento
                                       <= ESCOAMENTO_OK[1]):
        origens.append(f"escoamento — conta entregou {pct(escoamento, 0)} "
                       "do diário contratado")
    return origens


# ----------------------------------------------------------------------
# Os dois blocos de saída
# ----------------------------------------------------------------------
def vocabulario(calc):
    """A unidade em que o contratado foi combinado — ver `VOCABULARIO`."""
    return VOCABULARIO[calc.get("periodo") or CICLO_MENSAL]


def frase_status(calc):
    return FRASES_STATUS[calc["status"]].format(
        dia=f"{calc['inicio_veiculacao']:%d}", rotulo=calc["rotulo"],
        dias=calc["dias_veiculados"], apurados=calc["dias_apurados"],
        **vocabulario(calc))


def pergunta(calc):
    return PERGUNTAS[calc["status"]].format(**vocabulario(calc))


def mensagem(calc, cliente=""):
    """Bloco 1 — o que vai colado no grupo do cliente.

    Números com rótulo explícito e um veredito. O período apurado vem com as
    DUAS pontas e com a contagem de dias: é o que permite ao cliente conferir
    que o fechamento fala do intervalo que ele espera, e é a única defesa
    contra um recorte mal escolhido no Gerenciador.

    O nome de Cliente/unidade abre a mensagem em negrito, como nas outras
    frentes de texto fazem com o título. Numa linha própria, e não embutido na
    abertura, por concordância: "o fechamento da Atibaia" funciona, "o
    fechamento da Rei do Celular" não — e o app não tem como saber o gênero de
    um nome que o operador digita.
    """
    nome = (cliente or "").strip()
    linhas = [f"*{nome}*", ""] if nome else []
    dias = calc["dias_apurados"]
    linhas += [ABERTURA, ""] + _contratado(calc) + [
        f"*Período de {calc['desde']:%d/%m} a {calc['ate']:%d/%m}:* "
        f"{dias} dia{'s' if dias != 1 else ''}",
        f"*Previsto no período:* {reais(calc['previsto_periodo'], _PENDENTE)}",
        f"*Gasto:* {reais(calc['gasto'])}",
        "",
        frase_status(calc),
        pergunta(calc),
    ]
    return "\n".join(linhas)


def _contratado(calc):
    """O combinado, na unidade em que ele foi combinado.

    Escrever "R$ 4.650/mês" para quem combinou R$ 150/dia é traduzir o
    contrato do cliente para uma unidade que ele não usou — e a mensagem
    existe para ele conferir, não para ele converter. Por isso a primeira
    linha repete a unidade escolhida.

    A segunda linha só existe quando há o que converter: num contrato já
    cotado por dia, "Equivale a R$ 150/dia" seria a mesma linha duas vezes.
    """
    unidade = vocabulario(calc)["unidade"]
    digitado = reais(calc["contratado_unidade"], _PENDENTE)
    linhas = [f"*Contratado:* {digitado}/{unidade}"]
    if calc.get("periodo") != CICLO_DIARIO:
        linhas.append(
            f"*Equivale a:* {reais(calc['contratado_diario'], _PENDENTE)}/dia")
    return linhas


def analise(calc):
    """Bloco 2 — interna, não vai pro cliente. Sem adjetivo, sem hipótese."""
    desvio = calc["desvio_pct"]
    sinal = "+" if desvio and desvio > 0 else ""
    dias = calc["dias_apurados"]
    linhas = [
        f"Desvio: {sinal}{pct(desvio)} "
        f"({reais(calc['gasto'])} vs "
        f"{reais(calc['previsto_periodo'], _PENDENTE)} previstos em "
        f"{dias} dia{'s' if dias != 1 else ''})",
        "Origem: " + ("; ".join(calc["origens"]) or "nenhuma — ritmo alinhado"),
    ]
    # No lugar da antiga "Correção: R$ X/dia nos N dias restantes". Não há dia
    # restante para corrigir: o que o operador leva daqui é de quanto foi a
    # diferença, em reais, para decidir o ajuste do próximo período.
    diferenca = calc["diferenca"]
    if diferenca is not None and round(abs(diferenca)) >= 1:
        lado = "acima" if diferenca > 0 else "abaixo"
        linhas.append(f"Diferença: {reais(abs(diferenca))} {lado} do previsto "
                      "no período")
    return "\n".join(linhas)
