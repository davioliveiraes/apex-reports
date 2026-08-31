# -*- coding: utf-8 -*-
"""
Testes da Análise de Verba — leitura do preset VERBA, fórmulas do fechamento,
as duas telas e a reescrita por IA.

Arquivo à parte de `tests.py` pelo mesmo motivo do parser e das views: as duas
frentes não compartilham nada além do visual. O runner descobre este arquivo
porque o padrão padrão é `test*.py`.

Nada aqui toca a rede: `redator_ia._chamar` é o único ponto de I/O do projeto e
está sempre trocado por um `MagicMock`.
"""
import io
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from . import fechamento_verba as fv
from . import forms
from . import parser_verba, redator_ia

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Exatamente as colunas da predefinição VERBA do guia. A ordem é a que o
# Gerenciador entrega; o parser não depende dela, mas os testes valem mais
# reproduzindo o arquivo real.
CABECALHO_VERBA = [
    "Nome da campanha", "Identificação da campanha",
    "Nome do conjunto de anúncios", "Identificação do conjunto de anúncios",
    "Orçamento", "Tipo de orçamento", "Estratégia de lances",
    "Início", "Término", "Objetivo", "Veiculação", "Valor gasto (BRL)",
    # As duas do recorte do relatório. Não confundir com `Início`/`Término`
    # acima, que são datas de configuração da campanha — as quatro convivem no
    # mesmo arquivo e o app usa cada par para uma coisa.
    "Início dos relatórios", "Encerramento dos relatórios",
]

# O recorte padrão das planilhas de teste: agosto até o dia 24, que é o
# equivalente ao antigo "hoje = 25/08" — o último dia COM gasto medido.
RELATORIO = ("2026-08-01", "2026-08-24")

# E o recorte de quem fecha por semana: a semana de 24/08 a 30/08, medida até
# sexta. É o que um export tirado com "Esta semana" numa sexta-feira traz.
RELATORIO_SEMANA = ("2026-08-24", "2026-08-28")

HERDADO = "Usando o orçamento do conjunto de anúncios"


def _planilha_verba(linhas, relatorio=RELATORIO, com_periodo=True):
    wb = Workbook()
    ws = wb.active
    cabecalho = CABECALHO_VERBA if com_periodo else CABECALHO_VERBA[:-2]
    ws.append(cabecalho)
    for l in linhas:
        celulas = [
            l.get("campanha", ""), l.get("campanha_id", ""),
            l.get("conjunto", ""), l.get("conjunto_id", ""),
            l.get("orcamento", ""), l.get("tipo", ""),
            l.get("lances", "Maior volume de resultados"),
            l.get("inicio", ""), l.get("termino", ""),
            l.get("objetivo", "Mensagens"), l.get("veiculacao", "active"),
            l.get("gasto", ""),
        ]
        if com_periodo:
            celulas += [l.get("relatorio_de", relatorio[0]),
                        l.get("relatorio_ate", relatorio[1])]
        ws.append(celulas)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _anexo(nome, linhas, **kw):
    return SimpleUploadedFile(nome, _planilha_verba(linhas, **kw),
                              content_type=XLSX_MIME)


def _export(hoje, periodo=None):
    """O recorte de export do cliente que fecha PELO CALENDÁRIO.

    "Hoje" era o dia corrente, ainda gastando; o último dia com gasto medido
    era ontem. O `termino_relatorio` É esse último dia, então a tradução é
    `hoje - 1`.

    O começo é calculado aqui e não por `janela()`: desde 29/08/2026 é o
    arquivo que diz onde o ciclo começa, e `janela` só responde onde ele
    termina. Este helper representa o caso mais comum — quem contrata do dia
    1º ou da segunda-feira —, e é o que mantém as expectativas dos testes
    antigos válidas.
    """
    import relatorios.fechamento_verba as _fv
    ontem = hoje - timedelta(days=1)
    if (periodo or _fv.CICLO_MENSAL) == _fv.CICLO_SEMANAL:
        inicio = ontem - timedelta(days=ontem.weekday())
    else:
        inicio = date(ontem.year, ontem.month, 1)
    return {"inicio_relatorio": inicio, "termino_relatorio": ontem}


# Conta CBO: o orçamento está na campanha, e o export da aba Campanhas basta.
CAMPANHAS = [
    {"campanha": "[LEADS][CELULAR][ITU][CBO][01AGO26]", "campanha_id": "111",
     "orcamento": "R$ 20,00 Diário", "tipo": "Diário",
     "inicio": "2026-08-01", "gasto": 480.0},
    {"campanha": "[LEADS][ULTRA][ITU][CBO][01AGO26]", "campanha_id": "222",
     "orcamento": "R$ 12,00 Diário", "tipo": "Diário",
     "inicio": "2026-08-01", "gasto": 260.0},
]

# Conta ABO: o valor está no conjunto, e é a aba Conjuntos de anúncios que sai.
CONJUNTOS = [
    {"campanha": "[LEADS][ULTRA][ITU][ABO][01AGO26]", "campanha_id": "222",
     "conjunto": "Ultra — 25-45", "conjunto_id": "222001",
     "orcamento": "R$ 8,00 Diário", "tipo": "Diário",
     "inicio": "2026-08-01", "gasto": 180.0},
    {"campanha": "[LEADS][ULTRA][ITU][ABO][01AGO26]", "campanha_id": "222",
     "conjunto": "Ultra — 45+", "conjunto_id": "222002",
     "orcamento": "R$ 4,00 Diário", "tipo": "Diário",
     "inicio": "2026-08-01", "gasto": 80.0, "veiculacao": "inactive"},
]


class LeituraDoPresetTest(SimpleTestCase):
    """O arquivo entra; as colunas saem."""

    def test_le_as_colunas_do_preset(self):
        linhas = parser_verba.ler_planilha_verba(_anexo("camp.xlsx", CAMPANHAS))
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0]["campanha_id"], "111")
        self.assertEqual(linhas[0]["orcamento"], "R$ 20,00 Diário")

    def test_a_coluna_de_conjunto_vem_vazia_no_export_de_campanha(self):
        # A predefinição pede as duas identificações, então o export de
        # campanha TAMBÉM traz a coluna de conjunto — vazia. É o valor que
        # distingue os níveis, não a presença da coluna.
        campanha = parser_verba.ler_planilha_verba(
            _anexo("camp.xlsx", CAMPANHAS))
        conjunto = parser_verba.ler_planilha_verba(
            _anexo("conj.xlsx", CONJUNTOS))
        self.assertFalse(parser_verba.tem_conjunto(campanha))
        self.assertTrue(parser_verba.tem_conjunto(conjunto))

    def test_planilha_de_desempenho_e_recusada_com_o_preset_no_erro(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Nome da campanha", "Resultados", "Impressões"])
        ws.append(["Campanha A", 10, 500])
        buf = io.BytesIO()
        wb.save(buf)
        _linhas, erro = parser_verba.ler_arquivo_verba(
            SimpleUploadedFile("desempenho.xlsx", buf.getvalue(),
                               content_type=XLSX_MIME),
            parser_verba.NIVEL_CAMPANHA)
        self.assertIn("predefinição VERBA", erro)

    def test_linha_de_total_do_export_e_ignorada(self):
        linhas = parser_verba.ler_planilha_verba(_anexo("camp.xlsx", [
            *CAMPANHAS,
            {"campanha": "Total de resultados", "gasto": 740.0},
        ]))
        self.assertEqual(len(linhas), 2)


class OrcamentoTest(SimpleTestCase):
    """A célula de orçamento vem como texto, com a periodicidade grudada."""

    def test_diario(self):
        self.assertEqual(parser_verba.partir_orcamento("R$ 33,00 Diário"),
                         (33.0, "diario", False))

    def test_vitalicio_com_milhar(self):
        self.assertEqual(parser_verba.partir_orcamento("R$ 1.000,00 Vitalício"),
                         (1000.0, "vitalicio", False))

    def test_herdado_do_conjunto_marca_abo(self):
        valor, periodicidade, herdado = parser_verba.partir_orcamento(HERDADO)
        self.assertTrue(herdado)
        self.assertIsNone(valor)
        self.assertIsNone(periodicidade)

    def test_a_coluna_tipo_tem_a_ultima_palavra(self):
        # O rótulo dentro da célula pode faltar; a coluna própria, não.
        self.assertEqual(parser_verba.partir_orcamento("R$ 500,00", "Vitalício"),
                         (500.0, "vitalicio", False))

    def test_celula_vazia(self):
        self.assertEqual(parser_verba.partir_orcamento(""), (None, None, False))

    def test_so_active_conta_como_no_ar(self):
        self.assertTrue(parser_verba.ativa("active"))
        self.assertTrue(parser_verba.ativa("Ativa"))
        # "Em análise" ainda não gasta — fora do configurado.
        self.assertFalse(parser_verba.ativa("Em análise"))
        self.assertFalse(parser_verba.ativa("inactive"))
        self.assertFalse(parser_verba.ativa(""))


class EstruturasTest(SimpleTestCase):
    """Uma linha do export, uma estrutura.

    Havia aqui uma classe inteira sobre o cruzamento por ID entre o export de
    campanha e o de conjunto. Ela morreu com o cruzamento em 29/08/2026: o
    diário do fechamento passou a vir do contrato, o orçamento da planilha
    deixou de decidir número, e sobrou um arquivo — o do nível em que a conta
    está montada.
    """

    def _montar(self, linhas, nivel=parser_verba.NIVEL_CAMPANHA):
        lidas = parser_verba.ler_planilha_verba(
            io.BytesIO(_planilha_verba(linhas)))
        return parser_verba.montar_estruturas(lidas, nivel)

    def test_cbo_lista_campanhas(self):
        estruturas, _avisos = self._montar(CAMPANHAS)
        self.assertEqual([e["nome"] for e in estruturas],
                         [c["campanha"] for c in CAMPANHAS])
        self.assertEqual([e["tipo"] for e in estruturas], ["CBO", "CBO"])
        self.assertEqual(estruturas[0]["orcamento"], 20.0)

    def test_abo_lista_conjuntos_e_diz_de_que_campanha_sao(self):
        estruturas, _avisos = self._montar(CONJUNTOS,
                                           parser_verba.NIVEL_CONJUNTO)
        self.assertEqual([e["nome"] for e in estruturas],
                         ["Ultra — 25-45", "Ultra — 45+"])
        self.assertEqual([e["tipo"] for e in estruturas], ["ABO", "ABO"])
        # Sem a campanha, a tabela lista conjuntos sem dizer de quem são.
        self.assertTrue(all(e["campanha"] for e in estruturas))

    def test_o_gasto_soma_todas_as_linhas_inclusive_a_pausada(self):
        estruturas, _a = self._montar(CONJUNTOS, parser_verba.NIVEL_CONJUNTO)
        self.assertEqual(sum(e["gasto"] for e in estruturas), 260.0)
        self.assertFalse(estruturas[1]["ativa"])

    def test_o_orcamento_lido_nao_decide_numero_nenhum(self):
        """Ele fica na tabela para o operador ver o Meta setado em outro
        valor. O diário do fechamento vem do contrato."""
        estruturas, _a = self._montar(CAMPANHAS)
        calc = fv.calcular(estruturas, 300.0, periodo=fv.CICLO_SEMANAL,
                           inicio_relatorio=SEGUNDA, termino_relatorio=SEXTA)
        self.assertNotIn("configurado_diario", calc)
        self.assertAlmostEqual(calc["contratado_diario"], 300 / 7, 2)

    def test_vitalicio_com_termino_vira_equivalente_diario(self):
        estruturas, _a = self._montar([dict(
            CAMPANHAS[0], orcamento="R$ 1.000,00 Vitalício", tipo="Vitalício",
            inicio="2026-08-01", termino="2026-08-20")])
        self.assertEqual(estruturas[0]["orcamento"], 50.0)   # 1000 / 20 dias

    def test_vitalicio_sem_termino_avisa_o_divisor_usado(self):
        _e, avisos = self._montar([dict(
            CAMPANHAS[0], orcamento="R$ 900,00 Vitalício", tipo="Vitalício",
            termino="")])
        self.assertIn("vitalício sem data de término", avisos[0])


class NivelDeclaradoTest(SimpleTestCase):
    """A estrutura é declarada, mas não é confiada às cegas."""

    def _ler(self, linhas, nivel):
        return parser_verba.ler_arquivo_verba(
            _anexo("c.xlsx", linhas), nivel)

    def test_cbo_com_export_de_campanha_passa(self):
        linhas, erro = self._ler(CAMPANHAS, parser_verba.NIVEL_CAMPANHA)
        self.assertIsNone(erro)
        self.assertEqual(len(linhas), 2)

    def test_abo_com_export_de_conjunto_passa(self):
        linhas, erro = self._ler(CONJUNTOS, parser_verba.NIVEL_CONJUNTO)
        self.assertIsNone(erro)
        self.assertEqual(len(linhas), 2)

    def test_cbo_com_export_de_conjunto_e_recusado(self):
        """Somar o gasto no nível errado não faz o app reclamar de nada — por
        isso a declaração é conferida contra as colunas."""
        _l, erro = self._ler(CONJUNTOS, parser_verba.NIVEL_CAMPANHA)
        self.assertIn("marcou <b>CBO</b>", erro)
        self.assertIn("aba <i>Campanhas</i>", erro)

    def test_abo_com_export_de_campanha_e_recusado(self):
        _l, erro = self._ler(CAMPANHAS, parser_verba.NIVEL_CONJUNTO)
        self.assertIn("marcou <b>ABO</b>", erro)
        self.assertIn("Conjuntos de anúncios", erro)


def _estrutura(gasto, orcamento, inicio):
    """Uma estrutura como `montar_estruturas` a devolve, reduzida ao que o
    fechamento lê: o gasto e a data de início. O `orcamento` vem junto porque
    a tabela de conferência o mostra — o cálculo não o usa."""
    return {"gasto": gasto, "orcamento": orcamento, "inicio": inicio}


class DenominadorDoRitmoTest(SimpleTestCase):
    """O número que decide entre "esperar" e "investigar leilão"."""

    def test_o_caso_rei_do_celular(self):
        """Campanha no ar desde 17/08 num export de 01/08 a 24/08.

        O desvio compara o gasto com o previsto dos 24 dias apurados — e dá
        -39%, porque a campanha só rodou 8 deles. O número é esse mesmo: o
        cliente pagou por um período em que a entrega não aconteceu.

        Quem impede a leitura errada é o denominador do ritmo. `ritmo_real`
        divide por dias VEICULADOS, não por dias apurados, e é ele que mostra
        que enquanto rodou a campanha gastou acima do contratado. Sem essa
        divisão, "gastou pouco" e "rodou pouco" viram a mesma frase.
        """
        calc = fv.calcular([_estrutura(466.75, 58.0, "2026-08-17")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertEqual(calc["dias_apurados"], 24)
        self.assertEqual(calc["dias_veiculados"], 8)
        self.assertAlmostEqual(calc["desvio_pct"], -39.1, places=1)

        # R$ 58/dia enquanto rodou, contra os R$ 32/dia do contrato.
        self.assertAlmostEqual(calc["ritmo_real"], 466.75 / 8, places=2)
        self.assertGreater(calc["taxa_escoamento"], 150)
        self.assertTrue(calc["periodo_parcial"])

    def test_campanha_de_mes_anterior_trava_no_dia_primeiro(self):
        # Sem a trava seriam 170+ dias veiculados, e o ritmo sairia diluído.
        calc = fv.calcular([_estrutura(760.0, 32.0, "2026-03-05")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertEqual(calc["dias_veiculados"], 24)
        self.assertFalse(calc["periodo_parcial"])

    def test_campanha_sem_gasto_nao_estica_o_denominador(self):
        # A que gastou subiu dia 17; a que nunca gastou está no ar desde o dia
        # 1º. Contar a segunda faria o ritmo da primeira parecer um terço.
        calc = fv.calcular([_estrutura(466.75, 58.0, "2026-08-17"),
                            _estrutura(0.0, 10.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertEqual(calc["dias_veiculados"], 8)

    def test_sem_ninguem_com_gasto_cai_no_conjunto_todo(self):
        calc = fv.calcular([_estrutura(0.0, 10.0, "2026-08-10")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertEqual(calc["dias_veiculados"], 15)

    def test_nunca_menor_que_um(self):
        calc = fv.calcular([_estrutura(30.0, 30.0, "2026-08-01")],
                           contratado_ciclo=930.0,
                           inicio_relatorio=date(2026, 8, 1),
                           termino_relatorio=date(2026, 8, 1))
        self.assertEqual(calc["dias_apurados"], 1)
        self.assertEqual(calc["dias_veiculados"], 1)


class DiasDoMesTest(SimpleTestCase):
    """28, 29, 30 ou 31 — nunca 30 fixo."""

    def test_fevereiro_comum_bissexto_e_mes_de_31(self):
        self.assertEqual(fv.dias_do_mes(date(2026, 2, 10)), 28)
        self.assertEqual(fv.dias_do_mes(date(2028, 2, 10)), 29)
        self.assertEqual(fv.dias_do_mes(date(2026, 8, 10)), 31)

    def test_o_contratado_diario_sai_dos_dias_reais(self):
        calc = fv.calcular([_estrutura(0.0, 0.0, "2026-02-01")],
                           contratado_ciclo=280.0, **_export(date(2026, 2, 15)))
        self.assertEqual(calc["dias_do_contrato"], 28)
        self.assertEqual(calc["contratado_diario"], 10.0)

    def test_o_diario_e_o_contratado_dividido_pelos_dias_do_contrato(self):
        calc = fv.calcular([_estrutura(0.0, 0.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 15)))
        self.assertAlmostEqual(calc["contratado_diario"], 990.0 / 31, 4)
        self.assertEqual(calc["dias_do_contrato"], 31)

    def test_so_um_numero_do_contratado_e_digitado(self):
        """Havia dois campos que podiam discordar — mensal e diário. Hoje há
        um campo e uma unidade: o outro número é sempre derivado, e a
        divergência não tem por onde entrar.

        "Por dia" voltou em 31/08/2026 como unidade, e não como segundo campo.
        O teste é justamente que a volta não trouxe o defeito junto.
        """
        self.assertNotIn("contratado_diario", fv.calcular.__code__.co_varnames)
        campos = [c for c in forms.VerbaUploadForm().fields
                  if "orcamento" in c or "diario" in c or "contratado" in c]
        self.assertEqual(campos, ["orcamento"])

    def test_o_diario_digitado_nao_passa_por_divisao_nenhuma(self):
        """A ponta invertida: com "por dia" o valor digitado JÁ É a diária."""
        calc = fv.calcular([_estrutura(0.0, 0.0, "2026-08-01")],
                           contratado_ciclo=150.0, periodo=fv.CICLO_DIARIO,
                           **_export(date(2026, 8, 15)))
        self.assertEqual(calc["contratado_diario"], 150.0)
        self.assertEqual(calc["contratado_unidade"], 150.0)


class StatusTest(SimpleTestCase):
    """As seis frases da seção 5, cada uma na sua faixa."""

    def _status(self, gasto, orcamento=32.0, inicio="2026-08-01"):
        return fv.calcular([_estrutura(gasto, orcamento, inicio)],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))

    def test_alinhado(self):
        calc = self._status(760.0)
        self.assertEqual(calc["status"], fv.STATUS_ALINHADO)
        self.assertIn("alinhado com o contratado", fv.frase_status(calc))

    def test_pouco_acima(self):
        calc = self._status(820.0)
        self.assertEqual(calc["status"], fv.STATUS_POUCO_ACIMA)
        self.assertIn("um pouco acima", fv.frase_status(calc))

    def test_acima(self):
        calc = self._status(1000.0)
        self.assertEqual(calc["status"], fv.STATUS_ACIMA)
        self.assertIn("já estou ajustando", fv.frase_status(calc))

    def test_pouco_abaixo(self):
        calc = self._status(700.0)
        self.assertEqual(calc["status"], fv.STATUS_POUCO_ABAIXO)
        self.assertIn("um pouco abaixo do previsto", fv.frase_status(calc))

    def test_abaixo(self):
        calc = self._status(500.0)
        self.assertEqual(calc["status"], fv.STATUS_ABAIXO)
        self.assertIn("abaixo do previsto", fv.frase_status(calc))

    def test_periodo_parcial_substitui_as_demais(self):
        # Mesmo gasto do caso "abaixo", mas a campanha só rodou 8 dos 24 dias
        # apurados: comparar o gasto com o previsto do período inteiro deixa
        # de ser indicador válido, e a frase diz por quê.
        calc = self._status(500.0, inicio="2026-08-17")
        self.assertEqual(calc["status"], fv.STATUS_PARCIAL)
        frase = fv.frase_status(calc)
        self.assertIn("entraram no ar dia 17", frase)
        self.assertIn("o período ficou parcial", frase)
        self.assertIn("8 dias de veiculação dentro dos 24 apurados", frase)


class OrigensTest(SimpleTestCase):
    """As três origens, checadas na ordem da seção 7."""

    def test_nenhuma_quando_o_ritmo_esta_alinhado(self):
        calc = fv.calcular([_estrutura(760.0, 32.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertEqual(calc["origens"], [])
        self.assertIn("Origem: nenhuma — ritmo alinhado", fv.analise(calc))

    def test_ordem_periodo_escoamento(self):
        # Período incompleto (subiu dia 17) e ritmo de R$ 62/dia sobre os
        # R$ 32 que o contrato pede: as duas disparam, nesta ordem.
        calc = fv.calcular([_estrutura(500.0, 40.0, "2026-08-17")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        rotulos = [o.split(" —")[0] for o in calc["origens"]]
        self.assertEqual(rotulos, ["período parcial", "escoamento"])

    def test_a_origem_configuracao_saiu_com_a_leitura_do_orcamento(self):
        """Ela comparava o diário setado no Meta com o diário contratado. Os
        dois viraram o mesmo número em 29/08/2026, e comparar um número
        consigo mesmo nunca acusa nada."""
        # Ritmo em linha com o contratado: nada a apontar, e antes a
        # diferença entre R$ 32 setados e R$ 31,94 contratados era apontada.
        alinhado = fv.calcular([_estrutura(760.0, 32.0, "2026-08-01")],
                               contratado_ciclo=990.0,
                               **_export(date(2026, 8, 25)))
        self.assertEqual(alinhado["origens"], [])
        # E quando o escoamento fala, ele fala do contratado.
        fora = fv.calcular([_estrutura(1200.0, 32.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertIn("do diário contratado", " ".join(fora["origens"]))
        self.assertNotIn("configuração", " ".join(fora["origens"]))

    def test_escoamento_dentro_da_faixa_nao_vira_origem(self):
        calc = fv.calcular([_estrutura(768.0, 32.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertAlmostEqual(calc["taxa_escoamento"], 100.0, places=0)
        self.assertNotIn("escoamento", " ".join(calc["origens"]))


class MensagemTest(SimpleTestCase):
    """O gabarito da seção 7, bloco 1."""

    def _calc(self, **kw):
        base = dict(contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        base.update(kw)
        return fv.calcular([_estrutura(760.0, 32.0, "2026-08-01")], **base)

    def test_formato_e_limite_de_linhas(self):
        texto = fv.mensagem(self._calc())
        linhas = [l for l in texto.splitlines() if l.strip()]
        self.assertLessEqual(len(linhas), 10)
        self.assertTrue(texto.rstrip().endswith("?"))
        for rotulo in ("*Contratado:*", "*Equivale a:*", "*Período de",
                       "*Previsto no período:*", "*Gasto:*"):
            self.assertIn(rotulo, texto)
        # A projeção saiu com a janela futura: não sobra dia para projetar.
        self.assertNotIn("Fechamento previsto", texto)

    def test_sem_saudacao_de_horario(self):
        """A mensagem pode sair de manhã, de tarde ou de noite, e a hora do
        envio não é decidida aqui."""
        texto = fv.mensagem(self._calc())
        self.assertTrue(texto.startswith("Passando o fechamento"))
        for saudacao in ("Bom dia", "Boa tarde", "Boa noite"):
            self.assertNotIn(saudacao, texto)

    def test_dinheiro_sem_centavos_e_com_ponto_de_milhar(self):
        self.assertEqual(fv.reais(1003.4), "R$ 1.003")
        self.assertEqual(fv.reais(990.0), "R$ 990")
        self.assertIn("*Contratado:* R$ 990/mês", fv.mensagem(self._calc()))

    def test_o_periodo_traz_as_duas_pontas_e_a_contagem(self):
        """"Gasto até 28/08" não dizia desde quando. E a contagem de dias é o
        que deixa visível, para o cliente, que o fechamento fala do intervalo
        que ele espera — é a única defesa contra um recorte mal escolhido."""
        self.assertIn("*Período de 01/08 a 24/08:* 24 dias",
                      fv.mensagem(self._calc()))

    def test_nenhuma_metrica_de_performance_na_mensagem(self):
        texto = fv.mensagem(self._calc()).lower()
        for termo in ("cpm", "ctr", "cpa", "resultado", "clique", "conversa"):
            self.assertNotIn(termo, texto)

    def test_sem_contratado_a_pendencia_fica_marcada(self):
        calc = fv.calcular([_estrutura(760.0, 32.0, "2026-08-01")],
                           **_export(date(2026, 8, 25)))
        self.assertIn("R$ [contratado]", fv.mensagem(calc))

    def test_a_analise_diz_a_diferenca_em_reais(self):
        """No lugar da antiga "Correção: R$ X/dia nos N dias restantes". Não
        há dia restante para corrigir; o que o operador leva daqui é de quanto
        foi a diferença, para decidir o ajuste do próximo período."""
        calc = fv.calcular([_estrutura(1200.0, 40.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        texto = fv.analise(calc)
        # R$ 1.200 gastos contra R$ 766 previstos em 24 dias.
        self.assertIn("Diferença: R$ 434 acima do previsto no período", texto)
        self.assertNotIn("R$ -", texto)
        self.assertNotIn("dias restantes", texto)

    def test_a_diferenca_para_baixo_diz_abaixo(self):
        calc = fv.calcular([_estrutura(600.0, 40.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertIn("Diferença: R$ 166 abaixo do previsto", fv.analise(calc))

    def test_analise_interna_cabe_em_seis_linhas(self):
        calc = fv.calcular([_estrutura(500.0, 60.0, "2026-08-17")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertLessEqual(len(fv.analise(calc).splitlines()), 6)


class FluxoVerbaTest(TestCase):
    """As duas telas, ponta a ponta."""

    def _enviar(self, arquivo=None, **campos):
        dados = {"cliente": "Rei do Celular", "orcamento": "990,00",
                 "periodicidade": "mensal", "estrutura": "cbo"}
        dados.update(campos)
        dados["arquivo"] = (arquivo if arquivo is not None
                            else _anexo("campanhas.xlsx", CAMPANHAS))
        return self.client.post("/verba/", dados)

    def test_envio_leva_ao_fechamento(self):
        self.assertRedirects(self._enviar(), "/verba/fechamento/")

    def test_o_fechamento_traz_os_dois_blocos_e_a_conferencia(self):
        self._enviar()
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertIn("Passando o fechamento de verba", html)
        self.assertIn("Desvio:", html)
        self.assertIn("Origem:", html)
        self.assertIn("não vai pro cliente", html)
        # Conferência: as duas campanhas, com o orçamento cru ao lado.
        self.assertIn("[LEADS][CELULAR][ITU][CBO][01AGO26]", html)
        self.assertIn("R$ 20,00 Diário", html)

    def test_o_diario_da_tela_vem_do_contrato_e_nao_da_planilha(self):
        """A planilha tem R$ 20 + R$ 12 configurados; o contrato é
        R$ 990/mês. O que a tela mostra é o contrato dividido pelos dias."""
        self._enviar()
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertIn("R$ 32/dia", html)      # 990 / 31
        self.assertNotIn("R$ 32,00 Diário", html)

    def test_o_gasto_soma_todas_as_linhas(self):
        self._enviar()
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertIn("R$ 740", html)         # 480 + 260

    def test_conta_abo_fecha_com_o_export_de_conjunto(self):
        """Um arquivo em qualquer estrutura: o que muda é a aba de origem."""
        r = self._enviar(_anexo("conj.xlsx", CONJUNTOS), estrutura="abo")
        self.assertRedirects(r, "/verba/fechamento/")
        resposta = self.client.get("/verba/fechamento/")
        self.assertTrue(resposta.context["nivel_conjunto"])
        self.assertContains(resposta, "Ultra — 25-45")

    def test_estrutura_errada_e_recusada_antes_de_somar_nada(self):
        r = self._enviar(_anexo("conj.xlsx", CONJUNTOS), estrutura="cbo")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "marcou <b>CBO</b>", html=False)

    def test_a_tela_02_nao_edita_dado_nenhum(self):
        """A base interna saiu em 30/08/2026. Contratado errado é um envio
        errado, e o conserto é voltar e reenviar — não corrigir o número na
        tela que já mostra a mensagem pronta para o cliente."""
        self._enviar()
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertNotIn("Base interna", html)
        self.assertNotIn('name="orcamento"', html)
        self.assertNotIn('name="periodicidade"', html)
        self.assertNotIn('name="recalcular"', html)
        # O que a tela ainda diz: o período do export e o ciclo deduzido
        # dele. Sem campo para conferir, essa informação é a única defesa
        # contra um intervalo mal escolhido no Gerenciador.
        self.assertIn("01/08/2026 a 24/08/2026", html)
        self.assertIn("apura <b>exatamente</b> o intervalo do", html)

    def test_outro_contratado_exige_reenviar(self):
        """O caminho que sobrou, e é o certo: o contratado é uma declaração do
        envio, não um campo da tela de saída."""
        self._enviar(orcamento="1.500,00")
        self.assertContains(self.client.get("/verba/fechamento/"),
                            "R$ 1.500/mês")

    def test_os_blocos_de_saida_nao_trazem_metrica_de_performance(self):
        # Toda a garantia da frente de verba: o preset não traz esses campos e
        # o parser não os lê, então não há como vazarem para a mensagem.
        # A checagem é sobre os dois textos, não sobre o HTML inteiro — a
        # página tem CSS e JS onde "ctr" aparece dentro de "Ctrl+C".
        self._enviar()
        r = self.client.get("/verba/fechamento/")
        saida = (r.context["mensagem"] + r.context["analise"]).lower()
        for termo in ("cpm", "ctr", "cpa", "impress", "alcance", "clique",
                      "resultado", "conversa"):
            self.assertNotIn(termo, saida)

    def test_fechamento_sem_sessao_volta_ao_painel(self):
        self.assertRedirects(self.client.get("/verba/fechamento/"), "/verba/")

    def test_o_painel_pede_cliente_e_contratado(self):
        r = self.client.post("/verba/", {
            "arquivo": _anexo("c.xlsx", CAMPANHAS)})
        self.assertContains(r, "Este campo é obrigatório", status_code=200)


RESPOSTA_IA_VERBA = """Passando o fechamento pra você confirmar 👇

*Contratado:* R$ 990/mês
*Equivale a:* R$ 32/dia
*Período de 01/08 a 24/08:* 24 dias
*Previsto no período:* R$ 766
*Gasto:* R$ 740

O ritmo do período ficou alinhado com o contratado.
Posso seguir assim?"""


class MensagemVerbaIATest(TestCase):
    """O botão opcional. Nunca toca a rede: `_chamar` está sempre trocado."""

    def setUp(self):
        self.calc = fv.calcular([_estrutura(740.0, 28.0, "2026-08-01")],
                                contratado_ciclo=990.0, **_export(date(2026, 8, 25)))

    def _gerar(self, resposta):
        """A reescrita pelo caminho que a tela usa desde 30/08/2026.

        A verba migrou para o `reescrever` comum às quatro frentes, com as
        garantias dela passadas como parâmetro — dez linhas de teto, nenhuma
        métrica de performance e a pergunta fechada no fim. Ganhou de brinde a
        guarda dos números, que o caminho antigo não tinha.
        """
        original = fv.mensagem(self.calc, "Rei do Celular")
        with patch.object(redator_ia, "disponivel", return_value=True), \
             patch.object(redator_ia, "_chamar",
                          MagicMock(return_value=resposta)) as chamada:
            return redator_ia.reescrever(
                original,
                redator_ia.numeros_do_fechamento(self.calc, "Rei do Celular"),
                redator_ia.PROMPT_REESCRITA_VERBA,
                proibidos=redator_ia.TERMOS_DE_PERFORMANCE,
                max_linhas=redator_ia.LINHAS_MAXIMAS_VERBA,
                termina_em_pergunta=True), chamada

    def test_numero_trocado_pela_ia_e_recusado(self):
        """A garantia que o caminho antigo não tinha: 28 no lugar de 32 passa
        despercebido na leitura, e ia direto para o cliente."""
        ruim = RESPOSTA_IA_VERBA.replace("R$ 32/dia", "R$ 28/dia")
        with self.assertRaises(redator_ia.ErroDeIA) as ctx:
            self._gerar(ruim)
        self.assertIn("não está no cálculo", str(ctx.exception))

    def test_aceita_a_resposta_no_formato(self):
        texto, _ = self._gerar(RESPOSTA_IA_VERBA)
        self.assertTrue(texto.startswith("Passando o fechamento"))
        self.assertTrue(texto.rstrip().endswith("?"))

    def test_o_payload_leva_numeros_prontos_e_nenhuma_planilha(self):
        _, chamada = self._gerar(RESPOSTA_IA_VERBA)
        enviado = chamada.call_args[0][0][1]["content"]
        self.assertIn("R$ 990", enviado)
        self.assertIn("Rei do Celular", enviado)
        # Nada de linha de planilha nem de métrica de desempenho.
        for termo in ("campanha_id", "conjunto", "cpm", "impress"):
            self.assertNotIn(termo, enviado.lower())

    def test_resposta_com_mais_de_dez_linhas_e_recusada(self):
        with self.assertRaises(redator_ia.ErroDeIA) as ctx:
            self._gerar(RESPOSTA_IA_VERBA + "\n" + "\n".join(
                f"linha extra {i}" for i in range(6)))
        self.assertEqual(ctx.exception.motivo, "formato")
        self.assertIn("Mantido o texto do cálculo", str(ctx.exception))

    def test_resposta_com_metrica_de_performance_e_recusada(self):
        ruim = RESPOSTA_IA_VERBA.replace(
            "O ritmo do período ficou alinhado",
            "O CPM subiu e o ritmo do período ficou alinhado")
        with self.assertRaises(redator_ia.ErroDeIA) as ctx:
            self._gerar(ruim)
        self.assertIn("cpm", str(ctx.exception))
        self.assertIn("não usa", str(ctx.exception))

    def test_resposta_sem_pergunta_fechada_e_recusada(self):
        with self.assertRaises(redator_ia.ErroDeIA) as ctx:
            self._gerar(RESPOSTA_IA_VERBA.rstrip("?") + ".")
        self.assertIn("pergunta fechada", str(ctx.exception))

    def test_resposta_vazia_e_recusada(self):
        with self.assertRaises(redator_ia.ErroDeIA):
            self._gerar("   ")

    def test_sem_chave_o_botao_nem_e_oferecido(self):
        with patch.object(redator_ia, "disponivel", return_value=False):
            with self.assertRaises(redator_ia.ErroDeIA) as ctx:
                redator_ia.reescrever("x", {},
                                      redator_ia.PROMPT_REESCRITA_VERBA)
        self.assertEqual(ctx.exception.motivo, "chave")

    def test_falha_da_ia_preserva_a_mensagem_do_motor(self):
        self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": "990,00",
            "periodicidade": "mensal", "estrutura": "cbo",
            "arquivo": _anexo("c.xlsx", CAMPANHAS)})
        erro = redator_ia.ErroDeIA("A conta está sem crédito.", "credito")
        with patch.object(redator_ia, "disponivel", return_value=True), \
             patch.object(redator_ia, "reescrever", side_effect=erro):
            r = self.client.post("/verba/fechamento/", {
                "cliente": "Rei do Celular", "orcamento": "990,00",
                "periodicidade": "mensal", "estrutura": "cbo",
                "mensagem_ia": "1"})
        html = r.content.decode()
        self.assertIn("A conta está sem crédito.", html)
        self.assertIn("Passando o fechamento de verba", html)
        # Motivo definitivo: o botão sai da tela junto com o aviso.
        self.assertNotIn("Reescrever com IA", html)

    def test_texto_da_ia_vai_para_a_tela_e_volta_num_clique(self):
        """Desfazer era efeito colateral do *Recalcular*, que saiu junto com a
        base interna. Virou botão explícito — que é o que ela sempre foi."""
        base = {"cliente": "Rei do Celular", "orcamento": "990,00",
                "periodicidade": "mensal", "estrutura": "cbo"}
        self.client.post("/verba/", dict(
            base, arquivo=_anexo("c.xlsx", CAMPANHAS)))
        with patch.object(redator_ia, "disponivel", return_value=True), \
             patch.object(redator_ia, "reescrever",
                          return_value=RESPOSTA_IA_VERBA):
            r = self.client.post("/verba/fechamento/", {"mensagem_ia": "1"})
        self.assertIn("reescrita pela IA", r.content.decode())

        r = self.client.post("/verba/fechamento/", {"voltar_ao_motor": "1"})
        html = r.content.decode()
        self.assertIn("do cálculo", html)
        self.assertNotIn(RESPOSTA_IA_VERBA.splitlines()[0], html)


class TrilhoDoPeriodoTest(TestCase):
    """O trilho: a pista escalada, e as posições em CSS que o pt-BR não estraga.

    Eram três marcas — gasto, projeção e alvo. A projeção saiu em 31/08/2026
    junto com a janela futura: sem dia restante não há o que projetar, e a
    pista passou a comparar o gasto com o previsto dos dias apurados.
    """

    def _fechar(self, gasto, orcamento="990,00"):
        campanhas = [dict(CAMPANHAS[0], gasto=gasto)]
        self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": orcamento,
            "periodicidade": "mensal", "estrutura": "cbo",
            "arquivo": _anexo("c.xlsx", campanhas)})
        return self.client.get("/verba/fechamento/")

    def test_as_posicoes_saem_com_ponto_decimal(self):
        # A locale do projeto é pt-BR: um float no template viraria "74,75", e
        # `--gasto:74,75%` é CSS inválido — o navegador descarta em silêncio e
        # a barra fica vazia sem ninguém perceber.
        trilho = self._fechar(740.0).context["trilho"]
        for chave in ("gasto", "alvo"):
            self.assertRegex(trilho[chave], r"^\d+\.\d\d%$")
        self.assertNotIn(",", trilho["gasto"] + trilho["alvo"])

    def test_a_projecao_saiu_da_pista(self):
        self.assertNotIn("projetado", self._fechar(740.0).context["trilho"])

    def test_o_atributo_style_chega_intacto_no_html(self):
        html = self._fechar(740.0).content.decode()
        self.assertRegex(html, r"--gasto:\d+\.\d\d%;--projetado:0%;--alvo:\d+\.\d\d%")

    def test_dentro_do_combinado_o_alvo_fecha_a_pista(self):
        # R$ 766 é exatamente o previsto dos 24 dias apurados.
        trilho = self._fechar(766.0).context["trilho"]
        self.assertEqual(trilho["alvo"], "100.00%")
        self.assertEqual(trilho["tom"], "no-ritmo")

    def test_gasto_que_estoura_empurra_o_alvo_para_dentro(self):
        # A pista é escalada pelo maior dos dois: a barra precisa APARECER
        # passando da marca, não ser cortada na borda.
        trilho = self._fechar(1400.0).context["trilho"]
        self.assertEqual(trilho["gasto"], "100.00%")
        self.assertLess(float(trilho["alvo"].rstrip("%")), 100)
        self.assertEqual(trilho["tom"], "fora")

    def test_o_gasto_nunca_passa_da_pista(self):
        trilho = self._fechar(740.0).context["trilho"]
        self.assertLessEqual(float(trilho["gasto"].rstrip("%")), 100.0)

    def test_sem_contratado_nao_ha_trilho(self):
        # Sem o combinado não existe marca contra a qual comparar, e uma pista
        # sem alvo diria menos que nenhuma.
        calc = fv.calcular([_estrutura(0.0, 28.0, "2026-08-01")],
                           **_export(date(2026, 8, 25)))
        from .views_verba import _trilho
        self.assertIsNone(calc["previsto_periodo"])
        self.assertIsNone(_trilho(calc))


# ----------------------------------------------------------------------
# Contrato semanal
# ----------------------------------------------------------------------
# Cliente que fecha R$ 300 por semana. A unidade muda a diária — R$ 43/dia em
# vez dos R$ 10 que o mesmo valor daria dito "por mês" —, e é a diária que
# multiplica os dias apurados. 29/08/2026 é um sábado.
SABADO = date(2026, 8, 29)
SEGUNDA = date(2026, 8, 24)
DOMINGO = date(2026, 8, 30)
# Último dia COM gasto medido no caso base — o export vai até aqui.
SEXTA = date(2026, 8, 28)


def _semanal(gasto=251.0, orcamento=42.0, inicio="2026-08-24",
             contratado=300.0, **kw):
    """O fechamento semanal do caso base: export de 24/08 a 28/08."""
    janela = {"inicio_relatorio": SEGUNDA, "termino_relatorio": SEXTA}
    janela.update(kw)
    return fv.calcular([_estrutura(gasto, orcamento, inicio)],
                       contratado_ciclo=contratado,
                       periodo=fv.CICLO_SEMANAL, **janela)


class DiasDoContratoTest(SimpleTestCase):
    """Quantos dias tem UM ciclo do contrato — só para virar diária.

    Era `janela()`, e devolvia as duas pontas de uma janela futura sobre a
    qual o gasto era projetado. Essa janela saiu em 31/08/2026: o que se apura
    é o recorte do export. O que sobrou é a única coisa que a periodicidade
    ainda decide — por quanto se divide o valor contratado.
    """

    def test_a_janela_futura_nao_existe_mais(self):
        self.assertFalse(hasattr(fv, "janela"))

    def test_a_semana_sao_sete_dias(self):
        self.assertEqual(fv.dias_do_contrato(SEGUNDA, fv.CICLO_SEMANAL), 7)

    def test_a_quinzena_sao_quinze(self):
        self.assertEqual(fv.dias_do_contrato(SEGUNDA, fv.CICLO_QUINZENAL), 15)

    def test_o_mes_do_dia_primeiro_e_o_mes_do_calendario(self):
        self.assertEqual(fv.dias_do_contrato(date(2026, 8, 1)), 31)

    def test_fevereiro_tambem(self):
        self.assertEqual(fv.dias_do_contrato(date(2026, 2, 1)), 28)

    def test_o_mes_de_quem_entra_no_meio_conta_do_dia_dele(self):
        """Cliente que entra no dia 30 tem um mês que vai do 30 ao 29."""
        self.assertEqual(fv.dias_do_contrato(date(2026, 7, 30)), 31)

    def test_o_contrato_atravessa_a_virada_do_ano(self):
        self.assertEqual(fv.dias_do_contrato(date(2026, 12, 15)), 31)

    def test_dia_que_nao_existe_no_mes_seguinte_encosta_no_ultimo(self):
        """31/01 conta 28 dias porque o ciclo seguinte começaria em 28/02 — o
        mês de fevereiro não tem dia 31 para o contrato cair."""
        self.assertEqual(fv.dias_do_contrato(date(2026, 1, 31)), 28)

    def test_no_diario_a_divisao_nao_acontece(self):
        """O valor digitado já é a diária; `dias_do_contrato` é ignorado."""
        calc = fv.calcular([_estrutura(0.0, 0.0, "2026-08-24")],
                           contratado_ciclo=50.0, periodo=fv.CICLO_DIARIO,
                           inicio_relatorio=SEGUNDA, termino_relatorio=SEXTA)
        self.assertEqual(calc["contratado_diario"], 50.0)


class ContratoSemanalTest(SimpleTestCase):
    """R$ 300/semana — o caso que fez o motor deixar de ser mensal.

    A periodicidade não escolhe mais uma janela: ela só diz por quanto o
    contratado é dividido para virar diária. O que se apura são os dias do
    export, iguais para todo contrato.
    """

    def test_o_diario_sai_de_sete_dias_e_nao_dos_dias_do_mes(self):
        self.assertAlmostEqual(_semanal()["contratado_diario"], 300 / 7, 2)

    def test_os_dias_apurados_saem_do_export(self):
        calc = _semanal()
        self.assertEqual(calc["dias_apurados"], 5)   # 24 a 28
        self.assertEqual(calc["dias_do_contrato"], 7)

    def test_export_de_um_dia_so_apura_um_dia(self):
        """O término do relatório é INCLUSIVO: o dia que ele nomeia é um dia
        com gasto medido, ao contrário do antigo "hoje", que ainda corria."""
        calc = _semanal(termino_relatorio=SEGUNDA)
        self.assertEqual(calc["dias_apurados"], 1)

    def test_o_previsto_e_a_diaria_vezes_os_dias_apurados(self):
        # R$ 42,86/dia em 5 dias = R$ 214,29.
        self.assertAlmostEqual(_semanal()["previsto_periodo"], 300 / 7 * 5, 2)

    def test_sem_contratado_nao_ha_diario_nem_previsto(self):
        """Campo vazio não se inventa (seção 2 do prompt)."""
        calc = fv.calcular([_estrutura(0.0, 42.0, "2026-08-24")],
                           **_export(SABADO, fv.CICLO_SEMANAL),
                           periodo=fv.CICLO_SEMANAL)
        self.assertIsNone(calc["contratado_unidade"])
        self.assertIsNone(calc["contratado_diario"])
        self.assertIsNone(calc["previsto_periodo"])

    def test_a_unidade_muda_o_desvio_do_mesmo_gasto(self):
        """É o ponto inteiro do campo: o mesmo R$ 300 dito "por semana" e
        "por mês" produz diárias diferentes, e o desvio segue a diária."""
        semanal = _semanal()["desvio_pct"]
        mensal = fv.calcular([_estrutura(251.0, 42.0, "2026-08-24")],
                             contratado_ciclo=300.0,
                             inicio_relatorio=SEGUNDA,
                             termino_relatorio=SEXTA)["desvio_pct"]
        self.assertAlmostEqual(semanal, 17.13, 1)     # 251 vs 214
        self.assertAlmostEqual(mensal, 418.7, 1)      # 251 vs 48
        self.assertEqual(fv._status(semanal, False), fv.STATUS_ACIMA)


class DenominadorNaSemanaTest(SimpleTestCase):
    """A trava do ritmo é o começo do CICLO, não o dia 1º do mês."""

    def test_campanha_antiga_trava_na_segunda(self):
        calc = _semanal(inicio="2026-08-10")
        self.assertEqual(calc["inicio_veiculacao"], SEGUNDA)
        self.assertEqual(calc["dias_veiculados"], 5)

    def test_campanha_que_subiu_no_meio_da_semana_conta_do_dia_dela(self):
        calc = _semanal(inicio="2026-08-27")
        self.assertEqual(calc["dias_veiculados"], 2)   # 27 e 28
        self.assertTrue(calc["periodo_parcial"])

    def test_no_mes_a_trava_continua_sendo_o_dia_primeiro(self):
        calc = fv.calcular([_estrutura(251.0, 42.0, "2026-07-10")],
                           contratado_ciclo=990.0, **{"inicio_relatorio": date(2026, 8, 1), "termino_relatorio": SEXTA})
        self.assertEqual(calc["inicio_veiculacao"], date(2026, 8, 1))


class UnidadeDoContratadoTest(SimpleTestCase):
    """As frases falam da unidade certa.

    O vocabulário conjugado ("o mês"/"a semana"/"do mês cheio") saiu em
    31/08/2026 junto com a janela futura: as frases que ele servia prometiam o
    fechamento de um período que este arquivo não mede. Sobrou a unidade, que
    é o que vem depois da barra em "R$ 990/mês".
    """

    def test_a_mensagem_semanal_diz_por_semana(self):
        texto = fv.mensagem(_semanal())
        self.assertIn("*Contratado:* R$ 300/semana", texto)
        self.assertNotIn("/mês", texto)

    def test_a_mensagem_mensal_continua_dizendo_por_mes(self):
        calc = fv.calcular([_estrutura(740.0, 32.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        self.assertIn("*Contratado:* R$ 990/mês", fv.mensagem(calc))

    def test_a_diaria_aparece_logo_abaixo(self):
        """É ela que multiplica os dias apurados, então o cliente precisa
        poder conferir a conta inteira na mensagem."""
        self.assertIn("*Equivale a:* R$ 43/dia", fv.mensagem(_semanal()))

    # R$ 214 em 5 dias contra R$ 214,29 previstos — dentro dos 3% que a
    # seção 5 chama de alinhado.
    ALINHADA = {"gasto": 214.0, "orcamento": 43.0}

    def test_a_pergunta_alinhada_e_curta_e_igual_em_toda_unidade(self):
        calc = _semanal(**self.ALINHADA)
        self.assertEqual(calc["status"], fv.STATUS_ALINHADO)
        self.assertEqual(fv.pergunta(calc), "Podemos seguir assim?")

    def test_nenhuma_pergunta_promete_o_fim_de_um_ciclo(self):
        """"Podemos seguir assim até o fim da semana?" falava de dias que este
        fechamento não mede."""
        for status in fv.PERGUNTAS.values():
            with self.subTest(status=status):
                self.assertNotIn("até o fim", status)

    def test_nenhuma_frase_promete_fechamento_futuro(self):
        for frase in fv.FRASES_STATUS.values():
            with self.subTest(frase=frase[:30]):
                self.assertNotIn("deve fechar", frase)
                # As duas expressões do vocabulário conjugado que descreviam a
                # janela futura. "diário cheio" é outra coisa e pode ficar.
                self.assertNotIn("semana cheia", frase)
                self.assertNotIn("mês cheio", frase)

    def test_a_frase_alinhada_fala_do_periodo(self):
        calc = _semanal(**self.ALINHADA)
        self.assertEqual(fv.frase_status(calc),
                         "O ritmo do período ficou alinhado com o contratado.")

    def test_o_periodo_parcial_conta_os_dias_apurados(self):
        frase = fv.frase_status(_semanal(inicio="2026-08-27"))
        self.assertIn("entraram no ar dia 27", frase)
        self.assertIn("2 dias de veiculação dentro dos 5 apurados", frase)

    def test_nenhuma_frase_do_catalogo_deixa_chave_por_formatar(self):
        """`{artigo}` cru na mensagem do cliente é o defeito que este teste
        existe para pegar."""
        for periodo in (fv.CICLO_MENSAL, fv.CICLO_SEMANAL, fv.CICLO_QUINZENAL,
                        fv.CICLO_DIARIO):
            for status in fv.FRASES_STATUS:
                with self.subTest(periodo=periodo, status=status):
                    calc = dict(_semanal(inicio="2026-08-27"),
                                periodo=periodo, status=status)
                    for texto in (fv.frase_status(calc), fv.pergunta(calc)):
                        self.assertNotIn("{", texto)
                        self.assertNotIn("}", texto)


class FluxoSemanalTest(TestCase):
    """A semana pela porta da frente: form, sessão e tela."""

    def _enviar(self, periodicidade="semanal", orcamento="300,00",
                relatorio=RELATORIO_SEMANA, estrutura="cbo"):
        return self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": orcamento,
            "periodicidade": periodicidade, "estrutura": estrutura,
            "arquivo": _anexo("c.xlsx", [dict(
                CAMPANHAS[0], orcamento="R$ 42,00 Diário",
                inicio="2026-08-24", gasto=251.0)], relatorio=relatorio)})

    def test_a_tela_oferece_os_dois_ciclos(self):
        html = self.client.get("/verba/").content.decode()
        for rotulo in ("por mês", "por semana"):
            with self.subTest(rotulo=rotulo):
                self.assertIn(rotulo, html)

    def test_o_fechamento_semanal_sai_com_a_unidade_na_tela(self):
        self.assertRedirects(self._enviar(), "/verba/fechamento/")
        r = self.client.get("/verba/fechamento/")
        self.assertEqual(r.context["calc"]["periodo"], fv.CICLO_SEMANAL)
        self.assertEqual(r.context["unidade_contratado"], "semana")
        html = r.content.decode()
        self.assertIn("R$ 300/semana", html)
        self.assertIn("O período de 24/08 a 28/08", html)
        self.assertIn("5 dias apurados", " ".join(html.split()))

    def test_a_unidade_semanal_atravessa_o_fluxo(self):
        self._enviar()
        calc = self.client.get("/verba/fechamento/").context["calc"]
        self.assertEqual(calc["contratado_unidade"], 300.0)
        self.assertEqual(calc["dias_do_contrato"], 7)
        self.assertEqual(calc["dias_apurados"], 5)

    def test_a_tela_02_escreve_o_intervalo_apurado(self):
        """Não há campo para conferir, então o intervalo tem de estar escrito:
        é a única defesa contra um recorte mal escolhido no Gerenciador."""
        self._enviar()
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertIn("apura <b>exatamente</b> o intervalo do", html)
        self.assertIn("reenvie", html)

    def test_a_tela_oferece_por_dia_como_unidade(self):
        """O cliente que combina R$ 150/dia não deve ter que multiplicar por
        31 antes de digitar — é a conta que esta frente existe para tirar da
        mão do operador.

        Continua havendo UM campo de valor: "por dia" é a unidade dele.
        """
        html = self.client.get("/verba/").content.decode()
        self.assertIn('value="diario"', html)
        self.assertIn("por dia", html)
        self.assertEqual(html.count('name="orcamento"'), 1)

    def test_sessao_sem_contratado_nao_derruba_a_tela(self):
        """Sessão aberta antes de uma mudança de formato não tem
        `contratado_ciclo`. A tela abre com o valor pendente — nunca um
        TypeError."""
        self._enviar()
        sessao = self.client.session
        dados = sessao["verba_apex"]
        dados.pop("contratado_ciclo", None)
        dados.pop("periodo", None)
        sessao["verba_apex"] = dados
        sessao.save()
        r = self.client.get("/verba/fechamento/")
        self.assertEqual(r.status_code, 200)


class PayloadSemanalIATest(TestCase):
    """A IA precisa saber a unidade: o gabarito do prompt escreve "/mês"."""

    def test_a_unidade_viaja_no_payload(self):
        payload = redator_ia.numeros_do_fechamento(_semanal(), "Rei do Celular")
        self.assertEqual(payload["unidade_do_contratado"], "semana")
        self.assertEqual(payload["contratado"], "R$ 300")
        self.assertEqual(payload["periodo_analisado"],
                         "o período de 24/08 a 28/08")
        self.assertEqual(payload["dias_apurados"], 5)

    def test_no_mensal_a_unidade_e_mes(self):
        calc = fv.calcular([_estrutura(740.0, 32.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))
        payload = redator_ia.numeros_do_fechamento(calc)
        self.assertEqual(payload["unidade_do_contratado"], "mês")
        self.assertEqual(payload["periodo_analisado"],
                         "o período de 01/08 a 24/08")

    def test_o_payload_nao_leva_projecao_nenhuma(self):
        """O que não chega ao modelo ele não tem como escrever."""
        payload = redator_ia.numeros_do_fechamento(_semanal())
        for chave in ("projecao_fechamento", "dias_restantes",
                      "diario_corrigido"):
            self.assertNotIn(chave, payload)

    def test_as_regras_de_entrada_avisam_que_a_unidade_muda(self):
        self.assertIn("unidade_do_contratado",
                      redator_ia._REGRAS_DE_ENTRADA_VERBA)


# ----------------------------------------------------------------------
# O gasto que não cabe no ciclo
# ----------------------------------------------------------------------
class ExportMaiorQueOContratoTest(SimpleTestCase):
    """O alerta de "export maior que o ciclo" saiu — e não faz falta.

    Ele existia porque o gasto de um intervalo era projetado sobre outro:
    exportar o mês inteiro para um cliente semanal somava quatro ciclos num
    número comparado contra uma semana, e a tela dava +508%. Com o previsto
    acompanhando os dias apurados, exportar mais dias não erra número nenhum —
    apura outro intervalo, e o intervalo está escrito na mensagem.
    """

    def test_o_alerta_nao_existe_mais(self):
        self.assertFalse(hasattr(fv, "_alerta_periodo"))
        self.assertNotIn("alerta_periodo", _semanal())

    def test_o_mes_inteiro_num_contrato_semanal_nao_distorce_o_desvio(self):
        """R$ 43/dia contratados; 28 dias apurados preveem R$ 1.200. Gastar
        R$ 1.204 nesses 28 dias é ritmo alinhado — e era +508% antes."""
        calc = _semanal(gasto=1200.0, inicio="2026-08-01",
                        inicio_relatorio=date(2026, 8, 1),
                        termino_relatorio=date(2026, 8, 28))
        self.assertEqual(calc["dias_apurados"], 28)
        self.assertAlmostEqual(calc["previsto_periodo"], 300 / 7 * 28, 2)
        self.assertLess(abs(calc["desvio_pct"]), 1)
        self.assertEqual(calc["status"], fv.STATUS_ALINHADO)

    def test_o_intervalo_apurado_fica_escrito_na_mensagem(self):
        """A defesa contra o recorte errado deixou de ser um alerta e virou o
        próprio texto: quem lê vê de que dias o fechamento fala."""
        texto = fv.mensagem(_semanal(inicio_relatorio=date(2026, 8, 1),
                                     termino_relatorio=date(2026, 8, 28)))
        self.assertIn("*Período de 01/08 a 28/08:* 28 dias", texto)


class SemConfiguradoLidoTest(SimpleTestCase):
    """O alerta "gasto sem orçamento no ar" nasceu e morreu em 29/08/2026.

    Ele existia porque o diário saía da soma dos orçamentos configurados, e
    bastava a conta ser `[ABO]` sem o export de conjunto para ele virar
    R$ 0/dia num fechamento com R$ 1.304 gastos. Com o diário vindo do
    contrato, esse zero deixou de ser possível — e um alerta impossível de
    disparar é ruído no código.
    """

    def test_o_calculo_nao_le_mais_orcamento_da_planilha(self):
        self.assertFalse(hasattr(fv, "_alerta_configurado"))
        calc = _semanal()
        self.assertNotIn("configurado_diario", calc)
        self.assertNotIn("gap_configuracao", calc)

    def test_o_diario_existe_mesmo_com_a_planilha_sem_orcamento(self):
        """O caso real: R$ 1.304 gastos e nenhum orçamento legível."""
        calc = _semanal(gasto=1304.0)
        self.assertAlmostEqual(calc["contratado_diario"], 300 / 7, 2)
        self.assertIn("R$ 43/dia", fv.mensagem(calc))


class PeriodoNaTelaTest(TestCase):
    """O período apurado é lido do arquivo, então precisa estar escrito.

    Esta classe já mediu duas regras que caíram. A primeira dizia qual
    intervalo travar no Gerenciador ("Este mês" / "Esta semana") e recusava o
    que não batesse — servia a quem contrata no dia 1º e mais ninguém. A
    segunda alertava quando o export cobria mais de um ciclo, e saiu em
    31/08/2026 junto com o ciclo suposto.

    O que sobrou de defesa é o operador VER o intervalo que foi lido. A
    aplicação não tem como saber qual intervalo ele queria.
    """

    def _enviar(self, periodicidade="mensal", orcamento="990,00",
                relatorio=RELATORIO, gasto=251.0, estrutura="cbo"):
        return self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": orcamento,
            "periodicidade": periodicidade, "estrutura": estrutura,
            "arquivo": _anexo("c.xlsx", [dict(
                CAMPANHAS[0], orcamento="R$ 42,00 Diário",
                inicio=relatorio[0], gasto=gasto)], relatorio=relatorio)})

    def test_a_tela_de_envio_explica_que_o_intervalo_define_o_periodo(self):
        html = self.client.get("/verba/").content.decode()
        self.assertIn("começando no dia em que", html)
        self.assertIn('id="aba-do-export"', html)

    def test_a_aba_a_exportar_segue_a_estrutura(self):
        html = self.client.get("/verba/").content.decode()
        self.assertIn("abo: 'Conjuntos de anúncios'", html)
        self.assertIn(">Campanhas</b>", html)

    def test_a_tela_02_escreve_o_intervalo_lido(self):
        self._enviar()
        r = self.client.get("/verba/fechamento/")
        self.assertEqual(r.context["relatado_txt"], "01/08/2026 a 24/08/2026")
        self.assertContains(r, "01/08/2026 a 24/08/2026")
        self.assertContains(r, "24 dias apurados")

    def test_o_periodo_de_quem_entra_no_meio_do_mes(self):
        self._enviar(relatorio=("2026-07-30", "2026-08-28"))
        r = self.client.get("/verba/fechamento/")
        self.assertContains(r, "O período de 30/07 a 28/08")
        self.assertEqual(r.context["calc"]["dias_apurados"], 30)

    def test_a_tela_nao_alarma_por_tamanho_de_export(self):
        """O previsto acompanha os dias apurados: exportar mais dias apura
        outro intervalo, não erra número nenhum."""
        self._enviar("semanal", orcamento="300,00",
                     relatorio=("2026-08-01", "2026-08-28"))
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertNotIn("mais de uma semana", html)
        self.assertNotIn('class="erro"', html)


class PeriodoRelatadoTest(SimpleTestCase):
    """O arquivo passou a dizer de que intervalo ele é — e isso apagou um
    campo digitado e uma classe inteira de erro silencioso."""

    def _ler(self, linhas, **kw):
        from .parser_verba import ler_planilha_verba
        return ler_planilha_verba(io.BytesIO(_planilha_verba(linhas, **kw)))

    def test_le_o_intervalo_do_arquivo(self):
        desde, ate, erro = parser_verba.periodo_relatado(self._ler(CAMPANHAS))
        self.assertEqual((desde, ate), (date(2026, 8, 1), date(2026, 8, 24)))
        self.assertIsNone(erro)

    def test_nao_confunde_com_as_datas_de_configuracao_da_campanha(self):
        """`Início` (config) e `Início dos relatórios` convivem no mesmo
        arquivo. Trocá-las faria uma campanha que subiu dia 24 definir o
        período do relatório."""
        # A campanha foi CONFIGURADA para começar em 24/08; o relatório
        # cobre agosto desde o dia 1º. As duas datas coexistem, e cada uma
        # responde uma pergunta diferente.
        linhas = self._ler([dict(CAMPANHAS[0], inicio="2026-08-24")])
        self.assertEqual(str(linhas[0]["inicio"])[:10], "2026-08-24")
        desde, ate, _a = parser_verba.periodo_relatado(linhas)
        self.assertEqual((desde, ate), (date(2026, 8, 1), date(2026, 8, 24)))

    def test_sem_as_colunas_recusa_e_aponta_o_guia(self):
        desde, ate, erro = parser_verba.periodo_relatado(
            self._ler(CAMPANHAS, com_periodo=False))
        self.assertIsNone(desde)
        self.assertIsNone(ate)
        self.assertIn("GUIA_VERBA.md", erro)

    def test_o_intervalo_e_a_uniao_das_linhas(self):
        """Menor início e maior término, não o que estiver no topo: planilha
        editada à mão existe."""
        linhas = self._ler([
            dict(CAMPANHAS[0], relatorio_de="2026-08-05",
                 relatorio_ate="2026-08-20"),
            dict(CAMPANHAS[1], relatorio_de="2026-08-01",
                 relatorio_ate="2026-08-24")])
        desde, ate, _e = parser_verba.periodo_relatado(linhas)
        self.assertEqual((desde, ate), (date(2026, 8, 1), date(2026, 8, 24)))


class SemPeriodoNoArquivoTest(TestCase):
    """Sem o intervalo declarado o app recusa o arquivo — projetar um gasto de
    período desconhecido é como o fechamento saía errado sem ninguém ver."""

    def test_o_envio_e_recusado_com_instrucao(self):
        r = self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": "990,00",
            "periodicidade": "mensal", "estrutura": "cbo",
            "arquivo": _anexo("c.xlsx", CAMPANHAS, com_periodo=False)})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Início dos relatórios")
        self.assertContains(r, "GUIA_VERBA.md")

    def test_a_tela_nao_pede_mais_data_de_hoje(self):
        html = self.client.get("/verba/").content.decode()
        self.assertNotIn("Data de hoje", html)
        self.assertNotIn('name="referencia"', html)

    def test_o_periodo_apurado_e_o_do_export(self):
        """Antes marcava "ontem", contado a partir de uma data digitada — o
        que dava a data certa só quando o operador exportava e preenchia a
        tela no mesmo dia."""
        self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": "990,00",
            "periodicidade": "mensal", "estrutura": "cbo",
            "arquivo": _anexo("c.xlsx", CAMPANHAS)})
        r = self.client.get("/verba/fechamento/")
        self.assertIn("*Período de 01/08 a 24/08:* 24 dias",
                      r.context["mensagem"])


# ----------------------------------------------------------------------
# Quinzena
# ----------------------------------------------------------------------
class ContratoQuinzenalTest(SimpleTestCase):
    """A terceira unidade: o contratado dividido por 15."""

    def _quinzenal(self, gasto=700.0, contratado=900.0, de=date(2026, 8, 15),
                   ate=date(2026, 8, 26)):
        return fv.calcular([_estrutura(gasto, 60.0, de)],
                           contratado_ciclo=contratado,
                           periodo=fv.CICLO_QUINZENAL,
                           inicio_relatorio=de, termino_relatorio=ate)

    def test_a_quinzena_divide_por_quinze(self):
        self.assertEqual(fv.dias_do_contrato(date(2026, 8, 15),
                                             fv.CICLO_QUINZENAL), 15)
        self.assertEqual(self._quinzenal()["contratado_diario"], 60.0)

    def test_os_dias_apurados_saem_do_export(self):
        calc = self._quinzenal()
        self.assertEqual(calc["dias_apurados"], 12)   # 15 a 26
        self.assertEqual(calc["previsto_periodo"], 60.0 * 12)

    def test_a_mensagem_diz_por_quinzena(self):
        calc = self._quinzenal()
        self.assertIn("*Contratado:* R$ 900/quinzena", fv.mensagem(calc))
        self.assertIn("*Equivale a:* R$ 60/dia", fv.mensagem(calc))

    def test_o_periodo_parcial_da_quinzena(self):
        # Campanha no ar desde 24/08 num export que começou em 15/08.
        calc = fv.calcular([_estrutura(200.0, 60.0, date(2026, 8, 24))],
                           contratado_ciclo=900.0, periodo=fv.CICLO_QUINZENAL,
                           inicio_relatorio=date(2026, 8, 15),
                           termino_relatorio=date(2026, 8, 26))
        self.assertIn("3 dias de veiculação dentro dos 12 apurados",
                      fv.frase_status(calc))

    def test_export_maior_que_a_quinzena_apura_o_que_ele_traz(self):
        """Era um alerta vermelho; virou aritmética. 27 dias apurados a
        R$ 60/dia preveem R$ 1.620, e o desvio fala desses 27 dias."""
        calc = self._quinzenal(ate=date(2026, 9, 10))
        self.assertEqual(calc["dias_apurados"], 27)
        self.assertEqual(calc["previsto_periodo"], 60.0 * 27)

    def test_a_tela_oferece_as_quatro_unidades(self):
        self.assertEqual([c[0] for c in forms.VerbaUploadForm.PERIODICIDADES],
                         ["mensal", "quinzenal", "semanal", "diario"])

    def test_nenhuma_frase_do_catalogo_deixa_chave_por_formatar(self):
        for status in fv.FRASES_STATUS:
            with self.subTest(status=status):
                calc = dict(self._quinzenal(), status=status)
                for texto in (fv.frase_status(calc), fv.pergunta(calc)):
                    self.assertNotIn("{", texto)
                    self.assertNotIn("}", texto)


class ContratoPorDiaTest(SimpleTestCase):
    """R$ 150/dia — o valor digitado JÁ É a diária.

    Existe desde 31/08/2026 porque a conta que o operador fazia à mão antes de
    digitar (150 × 31) é exatamente a que esta frente existe para tirar da mão
    dele. E com o período apurado colado no export, a diária virou o único
    número do contrato que entra em conta: ela multiplica os dias do arquivo.
    """

    def _calc(self, gasto=361.0, diario=150.0, inicio="2026-08-28"):
        return fv.calcular([_estrutura(gasto, 0.0, inicio)],
                           contratado_ciclo=diario, periodo=fv.CICLO_DIARIO,
                           inicio_relatorio=date(2026, 8, 28),
                           termino_relatorio=date(2026, 8, 30))

    def test_o_periodo_apurado_e_o_do_export(self):
        """O caso da conta ILOC: export de três dias virava um ciclo suposto
        de 31 e uma projeção de R$ 3.735 a partir de R$ 361 gastos."""
        calc = self._calc()
        self.assertEqual(calc["dias_apurados"], 3)
        self.assertEqual(calc["previsto_periodo"], 450.0)
        self.assertNotIn("projecao_fechamento", calc)

    def test_o_diario_nao_passa_por_divisao(self):
        self.assertEqual(self._calc()["contratado_diario"], 150.0)

    def test_o_desvio_compara_o_gasto_com_o_previsto_dos_dias(self):
        self.assertAlmostEqual(self._calc()["desvio_pct"], -19.8, places=1)

    def test_a_mensagem_fala_na_unidade_combinada(self):
        """Escrever "R$ 4.650/mês" para quem combinou R$ 150/dia é traduzir o
        contrato do cliente para uma unidade que ele não usou."""
        texto = fv.mensagem(self._calc())
        self.assertIn("*Contratado:* R$ 150/dia", texto)
        self.assertIn("*Período de 28/08 a 30/08:* 3 dias", texto)
        self.assertIn("*Previsto no período:* R$ 450", texto)
        self.assertIn("*Gasto:* R$ 361", texto)
        self.assertNotIn("/mês", texto)

    def test_o_contrato_ja_diario_nao_repete_a_linha_de_conversao(self):
        """"Equivale a R$ 150/dia" abaixo de "Contratado R$ 150/dia" seria a
        mesma linha duas vezes."""
        self.assertNotIn("*Equivale a:*", fv.mensagem(self._calc()))

    def test_o_contrato_mensal_traz_a_conversao(self):
        texto = fv.mensagem(fv.calcular(
            [_estrutura(740.0, 0.0, "2026-08-01")], contratado_ciclo=990.0,
            **_export(date(2026, 8, 25))))
        self.assertIn("*Contratado:* R$ 990/mês", texto)
        self.assertIn("*Equivale a:* R$ 32/dia", texto)

    def test_nenhuma_frase_deixa_chave_por_formatar(self):
        for status in fv.FRASES_STATUS:
            with self.subTest(status=status):
                calc = dict(self._calc(), status=status)
                for texto in (fv.frase_status(calc), fv.pergunta(calc)):
                    self.assertNotIn("{", texto)

    def test_a_ia_recebe_o_combinado_na_unidade_certa(self):
        """O payload espelha a mensagem: um número que o modelo lê como
        "/mês" viraria "/mês" na reescrita."""
        payload = redator_ia.numeros_do_fechamento(self._calc(), "Cliente")
        self.assertEqual(payload["contratado"], "R$ 150")
        self.assertEqual(payload["unidade_do_contratado"], "dia")
        self.assertIsNone(payload["equivale_por_dia"])
        self.assertEqual(payload["previsto_no_periodo"], "R$ 450")
        self.assertEqual(payload["dias_apurados"], 3)

    def test_no_contrato_mensal_o_payload_traz_a_conversao(self):
        payload = redator_ia.numeros_do_fechamento(fv.calcular(
            [_estrutura(740.0, 0.0, "2026-08-01")], contratado_ciclo=990.0,
            **_export(date(2026, 8, 25))))
        self.assertEqual(payload["contratado"], "R$ 990")
        self.assertEqual(payload["unidade_do_contratado"], "mês")
        self.assertEqual(payload["equivale_por_dia"], "R$ 32")


class FluxoPorDiaTest(TestCase):
    """As duas telas com um contrato de R$ 150/dia."""

    def _enviar(self):
        return self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": "150,00",
            "periodicidade": "diario", "estrutura": "cbo",
            "arquivo": _anexo("campanhas.xlsx", CAMPANHAS)})

    def test_o_envio_chega_ao_fechamento(self):
        self.assertRedirects(self._enviar(), "/verba/fechamento/")

    def test_a_mensagem_da_tela_traz_o_diario_combinado(self):
        self._enviar()
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertIn("*Contratado:* R$ 150/dia", html)
        self.assertIn("*Período de 01/08 a 24/08:* 24 dias", html)

    def test_a_lateral_espelha_a_mensagem(self):
        """Ler "Contratado R$ 4.650/mês" numa tela cujo contrato é diário
        obriga a conferir de cabeça se 4.650 ÷ 31 dá 150."""
        self._enviar()
        r = self.client.get("/verba/fechamento/")
        self.assertEqual([l["rotulo"] for l in r.context["combinado"]],
                         ["Contratado", "Previsto"])
        self.assertEqual(r.context["combinado"][0]["valor"], "R$ 150/dia")
        self.assertEqual(r.context["combinado"][1]["valor"],
                         "R$ 3.600 · 24 dias")

    def test_o_trilho_e_escalado_pelo_previsto_do_periodo(self):
        self._enviar()
        r = self.client.get("/verba/fechamento/")
        self.assertEqual(r.context["previsto_txt"], "R$ 3.600")

    def test_no_mensal_a_lateral_traz_as_tres_linhas(self):
        self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": "990,00",
            "periodicidade": "mensal", "estrutura": "cbo",
            "arquivo": _anexo("campanhas.xlsx", CAMPANHAS)})
        r = self.client.get("/verba/fechamento/")
        self.assertEqual([l["rotulo"] for l in r.context["combinado"]],
                         ["Contratado", "Equivale a", "Previsto"])


class DeQuemEAEntregaTest(SimpleTestCase):
    """Subentrega não é falha da agência, e o texto não pode dizer que é.

    A divisão de responsabilidade é literal: a agência CONFIGURA o orçamento;
    quem decide quanto gastar por dia é o sistema de entrega do Meta, que
    distribui pelo leilão e com frequência não consome o valor diário cheio.
    Um orçamento de R$ 150/dia é um teto que a plataforma pode ou não
    preencher.

    As frases diziam "estou verificando o motivo antes de qualquer ajuste de
    verba", e a pergunta era "te retorno ainda hoje com o motivo". Assim
    escritas, admitiam um erro que não houve e prometiam uma apuração que não
    tem o que apurar.
    """

    def _abaixo(self, gasto=500.0):
        return fv.calcular([_estrutura(gasto, 32.0, "2026-08-01")],
                           contratado_ciclo=990.0, **_export(date(2026, 8, 25)))

    def test_a_frase_explica_o_mecanismo_da_plataforma(self):
        frase = fv.frase_status(self._abaixo())
        self.assertIn("O orçamento seguiu configurado", frase)
        self.assertIn("entrega do Meta", frase)
        self.assertIn("leilão", frase)

    def test_nenhuma_frase_admite_falha_da_agencia(self):
        """A varredura vale para as SEIS frases, não só para a de subentrega:
        nenhuma banda de desvio é motivo para pedir desculpa."""
        proibidos = ("verificando o motivo", "não conseguimos", "deixamos de",
                     "houve um problema", "desculpa", "falha", "erro nosso",
                     "vou apurar", "estou apurando")
        for status, frase in fv.FRASES_STATUS.items():
            for termo in proibidos:
                with self.subTest(status=status, termo=termo):
                    self.assertNotIn(termo, frase.lower())

    def test_nenhuma_pergunta_promete_apurar_causa(self):
        for status, pergunta in fv.PERGUNTAS.items():
            with self.subTest(status=status):
                self.assertNotIn("motivo", pergunta.lower())
                self.assertNotIn("retorno", pergunta.lower())

    def test_a_pergunta_da_subentrega_pede_seguir_com_o_diario(self):
        """O que resta ao cliente decidir é continuar ou não com o mesmo
        orçamento — não esperar uma explicação que já está na frase."""
        calc = self._abaixo()
        self.assertEqual(fv.pergunta(calc),
                         "Podemos seguir com o mesmo diário configurado?")

    def test_a_mensagem_inteira_fica_sem_tom_de_justificativa(self):
        texto = fv.mensagem(self._abaixo(), "Conta - ILOC")
        self.assertIn("O orçamento seguiu configurado", texto)
        self.assertNotIn("verificando", texto)
        self.assertTrue(texto.rstrip().endswith("?"))

    def test_o_prompt_da_ia_carrega_o_mesmo_contexto(self):
        """Sem isto, a reescrita reintroduz o tom que o motor tirou — o modelo
        preenche a lacuna com o pedido de desculpa que ele viu mil vezes."""
        prompt = redator_ia.PROMPT_REESCRITA_VERBA
        self.assertIn("a agência CONFIGURA o orçamento", prompt)
        self.assertIn("sistema de entrega do Meta", prompt)
        self.assertIn("NÃO é falha da agência", prompt)
        for proibido in ("não conseguimos gastar", "vou verificar o que houve",
                         "peço desculpas"):
            with self.subTest(proibido=proibido):
                self.assertIn(proibido, prompt)

    def test_o_lado_de_cima_tambem_e_da_plataforma(self):
        """O Meta pode consumir mais que o diário num dia e compensar noutro —
        o prompt diz isso para a reescrita não culpar ninguém do outro lado."""
        self.assertIn("consumir mais que o diário em um dia",
                      redator_ia.PROMPT_REESCRITA_VERBA)
