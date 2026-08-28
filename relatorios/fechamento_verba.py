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
"""

import calendar
from datetime import date, datetime, timedelta

# ----------------------------------------------------------------------
# Textos — editáveis sem mexer na lógica
# ----------------------------------------------------------------------
STATUS_PARCIAL = "parcial"
STATUS_ALINHADO = "alinhado"
STATUS_POUCO_ACIMA = "pouco_acima"
STATUS_ACIMA = "acima"
STATUS_POUCO_ABAIXO = "pouco_abaixo"
STATUS_ABAIXO = "abaixo"

# Seção 5 do prompt do operador, na íntegra. Em ciclo parcial a frase de
# parcial substitui as demais — o desvio contra o contratado deixa de ser
# indicador válido quando o mês não rodou inteiro.
FRASES_STATUS = {
    STATUS_PARCIAL: ("As campanhas entraram no ar dia {dia}, então {mes} fecha "
                     "parcial — foram {dias} dias de veiculação em vez do mês cheio."),
    STATUS_ALINHADO: ("O ritmo está alinhado com o contratado e o mês deve "
                      "fechar no valor combinado."),
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
    STATUS_PARCIAL: "Confirma que sigo com esse ritmo até o fim do mês?",
    STATUS_ALINHADO: "Posso seguir com esse ritmo até o fim do mês?",
    STATUS_POUCO_ACIMA: "Confirma o ajuste do diário pra fechar no combinado?",
    STATUS_ACIMA: "Confirma o ajuste do diário pra fechar no combinado?",
    STATUS_POUCO_ABAIXO: "Posso seguir acompanhando e te retorno amanhã?",
    STATUS_ABAIXO: "Te retorno ainda hoje com o motivo, pode ser?",
}

# Marca a pendência quando o contratado não foi informado (seção 2 do
# prompt: "campo vazio não se inventa").
_PENDENTE = "R$ [contratado]"

ABERTURA = "Bom dia! Passando o fechamento de verba pra confirmar 👇"

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

# Faixas de desvio da seção 5, em pontos percentuais.
ALINHADO = 3.0
AJUSTE_LEVE = 10.0
# Faixa em que o escoamento não é notícia — fora dela vira origem do desvio.
ESCOAMENTO_OK = (95.0, 105.0)


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
def calcular(estruturas, contratado_mensal=None, contratado_diario=None,
             hoje=None):
    """Todas as variáveis da seção 4 do prompt, mais `status` e `origens`.

    `gasto` soma **todas** as linhas, inclusive pausadas e zeradas: conjunto
    parado com R$ 0,00 é informação, e removê-lo erraria a soma do mês.
    `configurado_diario` soma **só o que está no ar** — é o que a conta pode
    gastar amanhã, não o que já foi configurado algum dia.
    """
    hoje = hoje or date.today()
    dias = dias_do_mes(hoje)
    dias_encerrados = hoje.day - 1
    dias_restantes = dias - dias_encerrados

    mensal, diario, divergencia = _normalizar_contratado(
        contratado_mensal, contratado_diario, dias)

    gasto = sum(e.get("gasto") or 0.0 for e in estruturas)
    configurado_diario = sum(e.get("orcamento_ativo") or 0.0 for e in estruturas)

    inicio_ref, dias_veiculados = _dias_veiculados(estruturas, hoje)
    ritmo_real = gasto / dias_veiculados
    projecao = gasto + ritmo_real * dias_restantes

    desvio = (projecao / mensal - 1) * 100 if mensal else None
    escoamento = (ritmo_real / configurado_diario * 100
                  if configurado_diario else None)
    gap = configurado_diario - diario if diario is not None else None
    corrigido = ((mensal - gasto) / dias_restantes
                 if mensal and dias_restantes > 0 else None)

    parcial = dias_veiculados < dias_encerrados
    calc = {
        "hoje": hoje,
        "ontem": hoje - timedelta(days=1),
        "mes": MESES[hoje.month - 1],
        "dias_do_mes": dias,
        "dias_encerrados": dias_encerrados,
        "dias_restantes": dias_restantes,
        "dias_veiculados": dias_veiculados,
        "inicio_veiculacao": inicio_ref,
        "contratado_mensal": mensal,
        "contratado_diario": diario,
        "configurado_diario": configurado_diario,
        "gasto": gasto,
        "ritmo_real": ritmo_real,
        "projecao_fechamento": projecao,
        "desvio_pct": desvio,
        "taxa_escoamento": escoamento,
        "gap_configuracao": gap,
        "diario_corrigido": corrigido,
        "ciclo_parcial": parcial,
        "divergencia_contratado": divergencia,
    }
    calc["status"] = _status(desvio, parcial)
    calc["origens"] = _origens(calc)
    return calc


def _normalizar_contratado(mensal, diario, dias):
    """`(mensal, diário, divergência)` — seção 2 do prompt.

    Vindo os dois e não batendo, o **mensal** é a referência e a divergência
    sai numa linha fora da mensagem: é ela que o cliente contratou.
    """
    divergencia = None
    if mensal and diario:
        esperado = mensal / dias
        if abs(esperado - diario) > 0.01:
            divergencia = (
                f"Contratado informado de dois jeitos que não batem: "
                f"{reais(mensal)}/mês daria {reais(esperado)}/dia, e foi "
                f"informado {reais(diario)}/dia. Vale o mensal.")
        diario = esperado
    elif mensal:
        diario = mensal / dias
    elif diario:
        mensal = diario * dias
    return mensal, diario, divergencia


def _dias_veiculados(estruturas, hoje):
    """`(início de referência, dias)` — do menor `Início` até ontem.

    Duas correções sobre a leitura literal do prompt, e as duas mudam número:

    1. **Trava no dia 1º do mês.** Campanha contínua que subiu em março daria
       170+ dias veiculados e diluiria o ritmo até a projeção virar ficção. O
       que se mede é o mês corrente.
    2. **Só campanhas que gastaram.** `dias_veiculados` é o denominador de
       `gasto ÷ dias`; campanha que não gastou nada não entra no numerador, e
       deixá-la esticar o denominador produz exatamente o artefato que a nota
       do guia sobre a coluna `Início` manda evitar. Sem nenhuma que tenha
       gasto, cai no conjunto todo.
    """
    primeiro = date(hoje.year, hoje.month, 1)
    ontem = hoje - timedelta(days=1)

    def inicios(filtradas):
        return [d for d in (_data(e.get("inicio")) for e in filtradas) if d]

    datas = inicios([e for e in estruturas if (e.get("gasto") or 0) > 0]) \
        or inicios(estruturas)
    inicio_ref = max(min(datas), primeiro) if datas else primeiro
    return inicio_ref, max(1, (ontem - inicio_ref).days + 1)


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
    """As três origens possíveis, **nesta ordem**, e só as que se aplicam."""
    origens = []
    gap = calc["gap_configuracao"]
    # O gatilho do prompt é `gap ≠ 0`, mas a mensagem sai sem centavos: o mês
    # de 31 dias sozinho faz R$ 990 contratados virarem R$ 31,94/dia, e a
    # regra crua acusaria "R$ 32 está acima de R$ 32". Fira só quando a
    # diferença aparece no número que o operador lê.
    if gap is not None and round(calc["configurado_diario"]) != round(
            calc["contratado_diario"]):
        origens.append(
            f"configuração — diário configurado ({reais(calc['configurado_diario'])}) "
            f"está {'acima' if gap > 0 else 'abaixo'} do diário contratado "
            f"({reais(calc['contratado_diario'])})")
    if calc["ciclo_parcial"]:
        origens.append(
            f"ciclo parcial — {calc['dias_veiculados']} dias veiculados de "
            f"{calc['dias_encerrados']} encerrados, início em "
            f"{calc['inicio_veiculacao']:%d/%m}")
    escoamento = calc["taxa_escoamento"]
    if escoamento is not None and not (ESCOAMENTO_OK[0] <= escoamento
                                       <= ESCOAMENTO_OK[1]):
        origens.append(f"escoamento — conta entregou {pct(escoamento, 0)} "
                       "do configurado")
    return origens


# ----------------------------------------------------------------------
# Os dois blocos de saída
# ----------------------------------------------------------------------
def frase_status(calc):
    modelo = FRASES_STATUS[calc["status"]]
    if calc["status"] != STATUS_PARCIAL:
        return modelo
    return modelo.format(dia=f"{calc['inicio_veiculacao']:%d}",
                         mes=calc["mes"], dias=calc["dias_veiculados"])


def mensagem(calc):
    """Bloco 1 — o que vai colado no grupo do cliente.

    `Gasto até` marca **ontem**, não hoje: o dia corrente ainda está gastando,
    e é sobre os dias encerrados que a projeção foi feita.
    """
    return "\n".join([
        ABERTURA,
        "",
        f"*Contratado:* {reais(calc['contratado_mensal'], _PENDENTE)}/mês",
        f"*Configurado:* {reais(calc['configurado_diario'])}/dia",
        f"*Gasto até {calc['ontem']:%d/%m}:* {reais(calc['gasto'])}",
        f"*Projeção de fechamento:* {reais(calc['projecao_fechamento'])}",
        "",
        frase_status(calc),
        PERGUNTAS[calc["status"]],
    ])


def analise(calc):
    """Bloco 2 — interna, não vai pro cliente. Sem adjetivo, sem hipótese."""
    desvio = calc["desvio_pct"]
    sinal = "+" if desvio and desvio > 0 else ""
    linhas = [
        f"Desvio: {sinal}{pct(desvio)} "
        f"({reais(calc['projecao_fechamento'])} vs "
        f"{reais(calc['contratado_mensal'], _PENDENTE)})",
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
            f"Correção: contratado do mês já ultrapassado em "
            f"{reais(calc['gasto'] - calc['contratado_mensal'])} — não há "
            "diário positivo que feche no combinado")
    if calc["divergencia_contratado"]:
        linhas.append(calc["divergencia_contratado"])
    return "\n".join(linhas)
