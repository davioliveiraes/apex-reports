# -*- coding: utf-8 -*-
"""
Fechamento de verba — as fórmulas, o status e os dois blocos de saída.

Determinístico de ponta a ponta, e por escolha: o prompt de Fechamento de Verba
não é um pedido de redação, é uma tabela de decisão. As fórmulas são fechadas e
cada faixa de desvio já tem UMA frase escrita, então o código as aplica sem
rede, sem crédito e sem a chance de o modelo errar uma divisão em silêncio. A
IA entra depois, por botão, só para reescrever o texto (ver
`redator_ia.gerar_mensagem_verba`).

O número que este módulo existe para acertar é o denominador do ritmo — o caso
Rei do Celular no guia. Campanha no ar desde 17/08, conferência em 25/08,
R$ 990/mês contratados, R$ 466,75 gastos:

    gasto ÷  8 dias veiculados  -> projeção R$ 875, desvio de -11,6%  (esperar)
    gasto ÷ 24 dias encerrados  -> projeção R$ 603, desvio de -39,1%  (investigar)

É a mesma planilha; muda só por quantos dias se divide, e com ela a decisão.
(O guia registra -70,8% para o denominador errado. Aquele número veio da conta
real, com gasto e contratado que o texto não traz — o que se reproduz aqui é o
mecanismo, não o par de percentuais.)

O ciclo não é sempre o mês. Há cliente que fecha a verba por semana — R$ 300
de segunda a domingo —, e para ele o mês não é uma janela, é uma soma de
quatro fechamentos que já aconteceram. Por isso tudo que aqui se chamava "do
mês" passou a se chamar "do ciclo": a janela, os dias, o contratado e a
projeção. `janela()` é quem sabe onde o ciclo começa e termina; o resto do
módulo só pergunta a ela.

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
VOCABULARIO = {
    CICLO_MENSAL: {"artigo": "o", "nome": "mês", "cheio": "do mês cheio",
                   "fim": "o fim do mês", "do_ciclo": "do mês"},
    CICLO_QUINZENAL: {"artigo": "a", "nome": "quinzena",
                      "cheio": "da quinzena cheia", "fim": "o fim da quinzena",
                      "do_ciclo": "da quinzena"},
    CICLO_SEMANAL: {"artigo": "a", "nome": "semana", "cheio": "da semana cheia",
                    "fim": "o fim da semana", "do_ciclo": "da semana"},
}

# Seção 5 do prompt do operador, na íntegra. Em ciclo parcial a frase de
# parcial substitui as demais — o desvio contra o contratado deixa de ser
# indicador válido quando o ciclo não rodou inteiro.
FRASES_STATUS = {
    STATUS_PARCIAL: ("As campanhas entraram no ar dia {dia}, então {rotulo} "
                     "fecha parcial — foram {dias} dias de veiculação em vez "
                     "{cheio}."),
    STATUS_ALINHADO: ("O ritmo está alinhado com o contratado e {artigo} "
                      "{nome} deve fechar no valor combinado."),
    STATUS_POUCO_ACIMA: ("O ritmo está um pouco acima do contratado e já vou "
                         "ajustar o diário pra fechar no valor combinado."),
    STATUS_ACIMA: ("O ritmo está acima do contratado e já estou ajustando pra "
                   "fechar dentro do combinado."),
    STATUS_POUCO_ABAIXO: ("O ritmo está levemente abaixo do configurado e "
                          "estou acompanhando a entrega de perto."),
    STATUS_ABAIXO: ("A entrega ficou abaixo do previsto no período e estou "
                    "verificando o motivo antes de qualquer ajuste de verba."),
}

# A seção 6 exige terminar com pergunta fechada, mas não diz quais são — estas
# foram escritas aqui e ficam isoladas de propósito, para serem conferidas e
# trocadas sem tocar em fórmula nenhuma. Fechadas mesmo: todas se respondem
# com sim ou não.
PERGUNTAS = {
    STATUS_PARCIAL: "Podemos seguir assim até {fim}?",
    STATUS_ALINHADO: "Podemos seguir assim?",
    STATUS_POUCO_ACIMA: "Confirma o ajuste do diário pra fechar no combinado?",
    STATUS_ACIMA: "Confirma o ajuste do diário pra fechar no combinado?",
    STATUS_POUCO_ABAIXO: "Posso seguir acompanhando e te retorno amanhã?",
    STATUS_ABAIXO: "Te retorno ainda hoje com o motivo, pode ser?",
}

# Marca a pendência quando o contratado não foi informado (seção 2 do
# prompt: "campo vazio não se inventa").
_PENDENTE = "R$ [contratado]"

# Sem saudação, e de propósito: "Bom dia" numa mensagem que sai às sete da
# noite mente na primeira palavra, e a hora do envio não é decidida aqui.
ABERTURA = "Passando o fechamento de verba pra confirmar 👇"

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

# Faixas de desvio da seção 5, em pontos percentuais.
ALINHADO = 3.0
AJUSTE_LEVE = 10.0
# Faixa em que o escoamento não é notícia — fora dela vira origem do desvio.
ESCOAMENTO_OK = (95.0, 105.0)

# A heurística do teto (gasto acima de 1,5× o que o configurado explicava)
# saiu em 29/08/2026, e não porque errava: porque virou desnecessária. Com o
# período declarado no próprio export, o descasamento entre o recorte do
# arquivo e o ciclo do contrato é medido de forma EXATA — ver
# `_alerta_periodo`. Uma heurística com falso positivo conhecido (mudança
# grande de orçamento no meio do ciclo dava o mesmo sinal) não se mantém ao
# lado da conta certa.


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


def janela(inicio, periodo=CICLO_MENSAL):
    """`(início, fim, dias, rótulo)` do ciclo que COMEÇA em `inicio`.

    Fonte única do tamanho e do nome do ciclo. Quem diz onde ele começa é o
    arquivo: `inicio` é o `Início dos relatórios` do export.

    Até 29/08/2026 o ciclo era o calendário — do dia 1º ao último do mês, ou de
    segunda a domingo. Isso servia a quem contrata no dia 1º e mais ninguém.
    Cliente que entra no dia 17 tem um mês que vai do 17 ao 16, e medi-lo
    contra o mês do calendário mistura dois ciclos num número só.

    Mês aqui é "até a véspera do mesmo dia no mês seguinte": 30/07 fecha em
    29/08, o que dá 31 dias. Dia que não existe no mês seguinte encosta no
    último dele — 31/01 fecha em 27/02, porque o próximo ciclo começa em 28/02.
    """
    # Ciclos de tamanho fixo: contam dias corridos a partir do início.
    for ciclo, dias, nome in ((CICLO_SEMANAL, DIAS_DA_SEMANA, "a semana"),
                              (CICLO_QUINZENAL, DIAS_DA_QUINZENA, "a quinzena")):
        if periodo == ciclo:
            fim = inicio + timedelta(days=dias - 1)
            return inicio, fim, dias, f"{nome} de {inicio:%d/%m} a {fim:%d/%m}"

    fim = _mesmo_dia_no_mes_seguinte(inicio) - timedelta(days=1)
    dias = (fim - inicio).days + 1
    # Ciclo que começa no dia 1º É o mês do calendário, e chamá-lo pelo nome
    # lê melhor do que por um intervalo que o cliente já conhece de cor.
    rotulo = (MESES[inicio.month - 1] if inicio.day == 1
              else f"o ciclo de {inicio:%d/%m} a {fim:%d/%m}")
    return inicio, fim, dias, rotulo


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
    """Todas as variáveis da seção 4 do prompt, mais `status` e `origens`.

    `periodo` diz qual é a janela do contrato — o mês ou a semana. Ele muda
    tudo que depende de "quanto falta": os dias do ciclo, os encerrados, os
    restantes, a projeção e o desvio. Não é formatação.

    O par `inicio_relatorio`/`termino_relatorio` é o recorte que o EXPORT
    declara, e é ele que ancora o cálculo INTEIRO: o ciclo **começa onde o
    relatório começa**, e os dias encerrados vão até onde ele termina. Não
    existe "hoje" aqui, nem calendário — o arquivo diz as duas pontas.

    A contrapartida é que a aplicação passa a confiar no intervalo escolhido no
    Gerenciador: exportar "Últimos 7 dias" para um cliente mensal cria um ciclo
    que começa sete dias atrás, e nenhuma conta acusa isso. O que resta de
    defesa é o ciclo aparecer escrito na tela, e o alerta de export que cobre
    mais de um ciclo (ver `_alerta_periodo`).

    `gasto` soma **todas** as linhas, inclusive pausadas e zeradas: conjunto
    parado com R$ 0,00 é informação, e removê-lo erraria a soma do ciclo.

    O DIÁRIO não é lido da planilha. R$ 300 por semana são R$ 43/dia porque a
    semana tem 7 dias, e é essa divisão que o fechamento usa — para projetar,
    para medir o escoamento e para escrever na mensagem. Antes o diário saía da
    soma dos orçamentos configurados no Meta, e bastava a conta ser `[ABO]` sem
    o export de conjunto para ele virar R$ 0/dia num fechamento com R$ 1.304
    gastos. O que está setado no Meta continua visível na tabela de
    conferência; ele só não decide mais número nenhum.
    """
    ate = _data(termino_relatorio) or date.today()
    desde = _data(inicio_relatorio) or ate
    inicio_ciclo, fim_ciclo, dias, rotulo = janela(desde, periodo)
    # Inclusivo: o dia do término do relatório é um dia COM gasto medido, ao
    # contrário do antigo "hoje", que ainda estava correndo.
    dias_encerrados = min(max((ate - inicio_ciclo).days + 1, 0), dias)
    dias_restantes = dias - dias_encerrados

    contratado, diario = _normalizar_contratado(contratado_ciclo, dias)

    gasto = sum(e.get("gasto") or 0.0 for e in estruturas)

    # O piso é o começo do ciclo, que agora É o começo do relatório: o gasto
    # só existe dentro do recorte do arquivo.
    inicio_ref, dias_veiculados = _dias_veiculados(estruturas, ate, inicio_ciclo)
    ritmo_real = gasto / dias_veiculados
    projecao = gasto + ritmo_real * dias_restantes

    desvio = (projecao / contratado - 1) * 100 if contratado else None
    # Quanto a conta entregou por dia contra o que o contrato pede por dia.
    escoamento = ritmo_real / diario * 100 if diario else None
    corrigido = ((contratado - gasto) / dias_restantes
                 if contratado and dias_restantes > 0 else None)

    parcial = dias_veiculados < dias_encerrados
    calc = {
        # Até quando o arquivo mediu gasto. É esta a data que a mensagem
        # imprime em "Gasto até", e ela vem do export — não do relógio.
        "ate": ate,
        "desde": desde,
        "periodo": periodo,
        "rotulo": rotulo,
        "inicio_ciclo": inicio_ciclo,
        "fim_ciclo": fim_ciclo,
        "dias_do_ciclo": dias,
        "dias_encerrados": dias_encerrados,
        "dias_restantes": dias_restantes,
        "dias_veiculados": dias_veiculados,
        "inicio_veiculacao": inicio_ref,
        "contratado_ciclo": contratado,
        "contratado_diario": diario,
        "gasto": gasto,
        "ritmo_real": ritmo_real,
        "projecao_fechamento": projecao,
        "desvio_pct": desvio,
        "taxa_escoamento": escoamento,
        "diario_corrigido": corrigido,
        "ciclo_parcial": parcial,
    }
    calc["alerta_periodo"] = _alerta_periodo(calc)
    calc["status"] = _status(desvio, parcial)
    calc["origens"] = _origens(calc)
    return calc


def _normalizar_contratado(ciclo, dias):
    """`(do ciclo, diário)` — seção 2 do prompt.

    O diário nunca é digitado: ele é o valor do ciclo dividido pelos dias do
    ciclo. R$ 300 por semana são R$ 43/dia porque a semana tem 7 dias, e
    R$ 990 por mês são R$ 32/dia porque agosto tem 31 — quem sabe esse número
    é o motor, não o operador.

    Foi assim que a divergência entre "mensal" e "diário" deixou de existir:
    não há dois campos para discordarem um do outro.
    """
    if not ciclo:
        return None, None
    return ciclo, ciclo / dias


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


def _alerta_periodo(calc):
    """Export que cobre MAIS de um ciclo — ou `None`.

    Desde que o ciclo passou a começar onde o relatório começa, não há mais
    como o export "começar fora do ciclo": ele define o começo. O que ainda dá
    para errar é o tamanho — exportar trinta dias para um cliente que fecha por
    semana soma quatro ciclos num número só, e foi isso que gerou +508% na
    tela.

    Fica FORA da análise interna de propósito. Aquele bloco é sobre a verba do
    cliente e é copiado inteiro; isto é sobre o arquivo que foi enviado, e só
    interessa a quem está na tela.
    """
    inicio, fim, ate = calc["inicio_ciclo"], calc["fim_ciclo"], calc["ate"]
    if ate <= fim:
        return None
    vocab = vocabulario(calc)
    # "um mês" / "uma quinzena" / "uma semana" — o artigo sai do mesmo
    # vocabulário que as frases de status usam.
    um = "um" if vocab["artigo"] == "o" else "uma"
    return (
        f"O export vai de {inicio:%d/%m} a {ate:%d/%m} — mais de {um} "
        f"{vocab['nome']}. Começando em {inicio:%d/%m}, o ciclo fecha em "
        f"{fim:%d/%m}, e o gasto do arquivo inclui dias do ciclo seguinte. "
        f"Refaça o export terminando em {fim:%d/%m} ou antes.")


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
    if calc["ciclo_parcial"]:
        origens.append(
            f"ciclo parcial — {calc['dias_veiculados']} dias veiculados de "
            f"{calc['dias_encerrados']} encerrados, início em "
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
    """Como este ciclo se chama nas frases — ver `VOCABULARIO`."""
    return VOCABULARIO[calc.get("periodo") or CICLO_MENSAL]


def frase_status(calc):
    return FRASES_STATUS[calc["status"]].format(
        dia=f"{calc['inicio_veiculacao']:%d}", rotulo=calc["rotulo"],
        dias=calc["dias_veiculados"], **vocabulario(calc))


def pergunta(calc):
    return PERGUNTAS[calc["status"]].format(**vocabulario(calc))


def mensagem(calc):
    """Bloco 1 — o que vai colado no grupo do cliente.

    Quatro números com rótulo explícito e um veredito. O gasto vem com as
    DUAS pontas do período: "Gasto até 28/08" não dizia desde quando, e num
    ciclo que começa no dia 30 o cliente não tem como adivinhar.
    """
    return "\n".join([
        ABERTURA,
        "",
        f"*Contratado:* {reais(calc['contratado_ciclo'], _PENDENTE)}"
        f"/{vocabulario(calc)['nome']}",
        f"*Configurado:* {reais(calc['contratado_diario'], _PENDENTE)}/dia",
        f"*Gasto de {calc['desde']:%d/%m} a {calc['ate']:%d/%m}:* "
        f"{reais(calc['gasto'])}",
        f"*Fechamento previsto:* {reais(calc['projecao_fechamento'])}",
        "",
        frase_status(calc),
        pergunta(calc),
    ])


def analise(calc):
    """Bloco 2 — interna, não vai pro cliente. Sem adjetivo, sem hipótese."""
    desvio = calc["desvio_pct"]
    sinal = "+" if desvio and desvio > 0 else ""
    linhas = [
        f"Desvio: {sinal}{pct(desvio)} "
        f"({reais(calc['projecao_fechamento'])} vs "
        f"{reais(calc['contratado_ciclo'], _PENDENTE)})",
        "Origem: " + ("; ".join(calc["origens"]) or "nenhuma — ritmo alinhado"),
    ]
    corrigido = calc["diario_corrigido"]
    if corrigido is not None and corrigido >= 0:
        linhas.append(f"Correção: {reais(corrigido)}/dia nos "
                      f"{calc['dias_restantes']} dias restantes")
    elif corrigido is not None:
        # Contratado já consumido: o diário corrigido sai negativo, e
        # "R$ -16/dia" não é instrução que alguém execute.
        linhas.append(
            f"Correção: contratado {vocabulario(calc)['do_ciclo']} já "
            f"ultrapassado em "
            f"{reais(calc['gasto'] - calc['contratado_ciclo'])} — não há "
            "diário positivo que feche no combinado")
    return "\n".join(linhas)
