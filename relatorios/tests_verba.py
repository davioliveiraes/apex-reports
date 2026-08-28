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
from datetime import date
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from . import fechamento_verba as fv
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
]

HERDADO = "Usando o orçamento do conjunto de anúncios"


def _planilha_verba(linhas):
    wb = Workbook()
    ws = wb.active
    ws.append(CABECALHO_VERBA)
    for l in linhas:
        ws.append([
            l.get("campanha", ""), l.get("campanha_id", ""),
            l.get("conjunto", ""), l.get("conjunto_id", ""),
            l.get("orcamento", ""), l.get("tipo", ""),
            l.get("lances", "Maior volume de resultados"),
            l.get("inicio", ""), l.get("termino", ""),
            l.get("objetivo", "Mensagens"), l.get("veiculacao", "active"),
            l.get("gasto", ""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _anexo(nome, linhas):
    return SimpleUploadedFile(nome, _planilha_verba(linhas),
                              content_type=XLSX_MIME)


# Conta mista do mundo real: uma campanha [CBO] com o orçamento nela mesma e
# uma [ABO] que só diz onde o valor está.
CAMPANHAS_MISTAS = [
    {"campanha": "[LEADS][CELULAR][ITU][CBO][01AGO26]", "campanha_id": "111",
     "orcamento": "R$ 20,00 Diário", "tipo": "Diário",
     "inicio": "2026-08-01", "gasto": 480.0},
    {"campanha": "[LEADS][ULTRA][ITU][ABO][01AGO26]", "campanha_id": "222",
     "orcamento": HERDADO, "inicio": "2026-08-01", "gasto": 260.0},
]
CONJUNTOS_MISTOS = [
    {"campanha": "[LEADS][ULTRA][ITU][ABO][01AGO26]", "campanha_id": "222",
     "conjunto": "Ultra — 25-45", "conjunto_id": "222001",
     "orcamento": "R$ 8,00 Diário", "tipo": "Diário"},
    {"campanha": "[LEADS][ULTRA][ITU][ABO][01AGO26]", "campanha_id": "222",
     "conjunto": "Ultra — 45+", "conjunto_id": "222002",
     "orcamento": "R$ 4,00 Diário", "tipo": "Diário",
     "veiculacao": "inactive"},
]


class LeituraDoPresetTest(SimpleTestCase):
    """O arquivo entra; o nível e as colunas saem."""

    def test_nivel_campanha_quando_a_coluna_de_conjunto_vem_vazia(self):
        # A predefinição pede as duas identificações, então o export de
        # campanha TAMBÉM traz a coluna de conjunto — vazia. É o valor que
        # decide o nível, não a presença da coluna.
        linhas, nivel = parser_verba.ler_planilha_verba(
            _anexo("camp.xlsx", CAMPANHAS_MISTAS))
        self.assertEqual(nivel, "campanha")
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0]["campanha_id"], "111")
        self.assertEqual(linhas[0]["orcamento"], "R$ 20,00 Diário")

    def test_nivel_conjunto(self):
        _, nivel = parser_verba.ler_planilha_verba(
            _anexo("conj.xlsx", CONJUNTOS_MISTOS))
        self.assertEqual(nivel, "conjunto")

    def test_a_ordem_de_envio_nao_importa(self):
        direta = parser_verba.ler_arquivos_verba([
            _anexo("camp.xlsx", CAMPANHAS_MISTAS),
            _anexo("conj.xlsx", CONJUNTOS_MISTOS)])
        invertida = parser_verba.ler_arquivos_verba([
            _anexo("conj.xlsx", CONJUNTOS_MISTOS),
            _anexo("camp.xlsx", CAMPANHAS_MISTAS)])
        self.assertEqual(direta, invertida)
        self.assertIsNone(direta[2])

    def test_dois_exports_do_mesmo_nivel_sao_recusados(self):
        _, _, erro = parser_verba.ler_arquivos_verba([
            _anexo("a.xlsx", CAMPANHAS_MISTAS),
            _anexo("b.xlsx", CAMPANHAS_MISTAS)])
        self.assertIn("outro export de nível campanha", erro)

    def test_planilha_de_desempenho_e_recusada_com_o_preset_no_erro(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Nome da campanha", "Resultados", "Impressões"])
        ws.append(["Campanha A", 10, 500])
        buf = io.BytesIO()
        wb.save(buf)
        _, _, erro = parser_verba.ler_arquivos_verba(
            [SimpleUploadedFile("desempenho.xlsx", buf.getvalue(),
                                content_type=XLSX_MIME)])
        self.assertIn("predefinição VERBA", erro)

    def test_linha_de_total_do_export_e_ignorada(self):
        linhas, _ = parser_verba.ler_planilha_verba(_anexo("camp.xlsx", [
            *CAMPANHAS_MISTAS,
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


class CruzamentoTest(SimpleTestCase):
    """Os dois níveis viram uma estrutura por campanha."""

    def _montar(self, campanhas=None, conjuntos=None, dias=31):
        """Passa pelas planilhas de verdade em vez de fabricar as linhas.

        Os dicionários das fixtures são receita de célula, não registro lido:
        o `Veiculação` padrão, por exemplo, só existe depois do `.get` que
        monta a planilha. Montar a mão pularia justamente o que decide se a
        estrutura entra no configurado.
        """
        anexos = [_anexo("camp.xlsx",
                         CAMPANHAS_MISTAS if campanhas is None else campanhas)]
        conjuntos = CONJUNTOS_MISTOS if conjuntos is None else conjuntos
        if conjuntos:
            anexos.append(_anexo("conj.xlsx", conjuntos))
        linhas_campanha, linhas_conjunto, erro =             parser_verba.ler_arquivos_verba(anexos)
        self.assertIsNone(erro)
        return parser_verba.montar_estruturas(
            linhas_campanha, linhas_conjunto, dias)

    def test_cbo_usa_o_proprio_orcamento_e_abo_soma_os_conjuntos(self):
        estruturas, avisos = self._montar()
        cbo, abo = estruturas
        self.assertEqual(cbo["tipo"], "CBO")
        self.assertEqual(cbo["orcamento_ativo"], 20.0)
        self.assertEqual(abo["tipo"], "ABO")
        # R$ 8 ativo + R$ 4 pausado = R$ 12 configurados, R$ 8 no ar.
        self.assertEqual(abo["orcamento"], 12.0)
        self.assertEqual(abo["orcamento_ativo"], 8.0)
        self.assertEqual(avisos, [])

    def test_o_cruzamento_e_por_id_e_sobrevive_ao_rename(self):
        # O guia avisa: nome de campanha é renomeado no meio do mês. Com merge
        # por nome, este caso perderia o conjunto e o configurado sairia zero.
        renomeadas = [dict(CAMPANHAS_MISTAS[1],
                           campanha="[LEADS][ULTRA][ITU][ABO][NOVO NOME]")]
        estruturas, _ = self._montar(renomeadas, CONJUNTOS_MISTOS)
        self.assertEqual(estruturas[0]["orcamento_ativo"], 8.0)

    def test_abo_sem_export_de_conjunto_avisa_e_nao_inventa_valor(self):
        estruturas, avisos = self._montar(CAMPANHAS_MISTAS, [])
        self.assertIsNone(estruturas[1]["orcamento"])
        self.assertEqual(estruturas[1]["orcamento_ativo"], 0.0)
        self.assertIn("não há export de nível conjunto", " ".join(avisos))

    def test_campanha_pausada_zera_o_configurado_mas_mantem_o_gasto(self):
        pausada = [dict(CAMPANHAS_MISTAS[0], veiculacao="inactive")]
        estruturas, _ = self._montar(pausada, [])
        self.assertEqual(estruturas[0]["orcamento_ativo"], 0.0)
        self.assertEqual(estruturas[0]["gasto"], 480.0)
        # O valor configurado continua visível na conferência.
        self.assertEqual(estruturas[0]["orcamento"], 20.0)

    def test_conjunto_ativo_sob_campanha_desligada_nao_conta(self):
        desligada = [dict(CAMPANHAS_MISTAS[1], veiculacao="inactive")]
        estruturas, _ = self._montar(desligada, CONJUNTOS_MISTOS)
        self.assertEqual(estruturas[0]["orcamento_ativo"], 0.0)

    def test_vitalicio_com_termino_vira_equivalente_diario(self):
        linha = [{"campanha": "C", "campanha_id": "1", "gasto": 300.0,
                  "orcamento": "R$ 620,00 Vitalício", "tipo": "Vitalício",
                  "inicio": "2026-08-01", "termino": "2026-08-31"}]
        estruturas, avisos = self._montar(linha, [])
        self.assertEqual(estruturas[0]["orcamento_ativo"], 20.0)
        self.assertEqual(avisos, [])

    def test_vitalicio_sem_termino_cai_no_mes_e_avisa(self):
        linha = [{"campanha": "C", "campanha_id": "1", "gasto": 300.0,
                  "orcamento": "R$ 620,00 Vitalício", "tipo": "Vitalício",
                  "inicio": "2026-08-01"}]
        estruturas, avisos = self._montar(linha, [])
        self.assertEqual(estruturas[0]["orcamento_ativo"], 20.0)
        self.assertIn("vitalício sem data de término", " ".join(avisos))

    def test_sem_coluna_de_identificacao_avisa_que_o_merge_caiu_no_nome(self):
        campanhas = [dict(CAMPANHAS_MISTAS[1], campanha_id="")]
        conjuntos = [dict(CONJUNTOS_MISTOS[0], campanha_id="")]
        estruturas, avisos = self._montar(campanhas, conjuntos)
        self.assertIn("cruzamento entre os dois arquivos caiu no nome",
                      " ".join(avisos))
        self.assertEqual(estruturas[0]["orcamento_ativo"], 8.0)


def _estrutura(gasto, orcamento_ativo, inicio):
    return {"gasto": gasto, "orcamento_ativo": orcamento_ativo,
            "inicio": inicio}


class DenominadorDoRitmoTest(SimpleTestCase):
    """O número que decide entre "esperar" e "investigar leilão"."""

    def test_o_caso_rei_do_celular(self):
        # Guia, agosto/2026: campanha no ar desde 17/08, conferência em 25/08,
        # R$ 990/mês contratados. Dividir por dias veiculados dá subentrega
        # leve; por dias encerrados, subentrega crítica. Mesma planilha.
        calc = fv.calcular([_estrutura(466.75, 58.0, "2026-08-17")],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))
        self.assertEqual(calc["dias_encerrados"], 24)
        self.assertEqual(calc["dias_veiculados"], 8)
        self.assertAlmostEqual(calc["desvio_pct"], -11.6, places=1)

        errado = 466.75 / calc["dias_encerrados"]
        projecao_errada = 466.75 + errado * calc["dias_restantes"]
        self.assertAlmostEqual(projecao_errada / 990 - 1, -0.391, places=3)

    def test_campanha_de_mes_anterior_trava_no_dia_primeiro(self):
        # Sem a trava seriam 170+ dias veiculados, e o ritmo sairia diluído.
        calc = fv.calcular([_estrutura(760.0, 32.0, "2026-03-05")],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))
        self.assertEqual(calc["dias_veiculados"], 24)
        self.assertFalse(calc["ciclo_parcial"])

    def test_campanha_sem_gasto_nao_estica_o_denominador(self):
        # A que gastou subiu dia 17; a que nunca gastou está no ar desde o dia
        # 1º. Contar a segunda faria o ritmo da primeira parecer um terço.
        calc = fv.calcular([_estrutura(466.75, 58.0, "2026-08-17"),
                            _estrutura(0.0, 10.0, "2026-08-01")],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))
        self.assertEqual(calc["dias_veiculados"], 8)

    def test_sem_ninguem_com_gasto_cai_no_conjunto_todo(self):
        calc = fv.calcular([_estrutura(0.0, 10.0, "2026-08-10")],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))
        self.assertEqual(calc["dias_veiculados"], 15)

    def test_nunca_menor_que_um(self):
        calc = fv.calcular([_estrutura(30.0, 30.0, "2026-08-01")],
                           contratado_mensal=930.0, hoje=date(2026, 8, 1))
        self.assertEqual(calc["dias_encerrados"], 0)
        self.assertEqual(calc["dias_veiculados"], 1)


class DiasDoMesTest(SimpleTestCase):
    """28, 29, 30 ou 31 — nunca 30 fixo."""

    def test_fevereiro_comum_bissexto_e_mes_de_31(self):
        self.assertEqual(fv.dias_do_mes(date(2026, 2, 10)), 28)
        self.assertEqual(fv.dias_do_mes(date(2028, 2, 10)), 29)
        self.assertEqual(fv.dias_do_mes(date(2026, 8, 10)), 31)

    def test_o_contratado_diario_sai_dos_dias_reais(self):
        calc = fv.calcular([_estrutura(0.0, 0.0, "2026-02-01")],
                           contratado_mensal=280.0, hoje=date(2026, 2, 15))
        self.assertEqual(calc["dias_do_mes"], 28)
        self.assertEqual(calc["contratado_diario"], 10.0)

    def test_contratado_diario_vira_mensal(self):
        calc = fv.calcular([_estrutura(0.0, 0.0, "2026-08-01")],
                           contratado_diario=33.0, hoje=date(2026, 8, 15))
        self.assertEqual(calc["contratado_mensal"], 33.0 * 31)

    def test_mensal_e_diario_que_nao_batem_valem_pelo_mensal(self):
        calc = fv.calcular([_estrutura(0.0, 0.0, "2026-08-01")],
                           contratado_mensal=990.0, contratado_diario=50.0,
                           hoje=date(2026, 8, 15))
        self.assertEqual(calc["contratado_mensal"], 990.0)
        self.assertIn("Vale o mensal", calc["divergencia_contratado"])


class StatusTest(SimpleTestCase):
    """As seis frases da seção 5, cada uma na sua faixa."""

    def _status(self, gasto, orcamento=32.0, inicio="2026-08-01"):
        return fv.calcular([_estrutura(gasto, orcamento, inicio)],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))

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
        self.assertIn("levemente abaixo", fv.frase_status(calc))

    def test_abaixo(self):
        calc = self._status(500.0)
        self.assertEqual(calc["status"], fv.STATUS_ABAIXO)
        self.assertIn("verificando o motivo", fv.frase_status(calc))

    def test_ciclo_parcial_substitui_as_demais(self):
        # Mesmo gasto do caso "abaixo", mas com o mês incompleto: o desvio
        # contra o contratado deixa de ser indicador válido.
        calc = self._status(500.0, inicio="2026-08-17")
        self.assertEqual(calc["status"], fv.STATUS_PARCIAL)
        frase = fv.frase_status(calc)
        self.assertIn("entraram no ar dia 17", frase)
        self.assertIn("agosto fecha parcial", frase)
        self.assertIn("8 dias de veiculação", frase)


class OrigensTest(SimpleTestCase):
    """As três origens, checadas na ordem da seção 7."""

    def test_nenhuma_quando_o_ritmo_esta_alinhado(self):
        calc = fv.calcular([_estrutura(760.0, 32.0, "2026-08-01")],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))
        self.assertEqual(calc["origens"], [])
        self.assertIn("Origem: nenhuma — ritmo alinhado", fv.analise(calc))

    def test_ordem_configuracao_ciclo_escoamento(self):
        # Configurado a R$ 40 contra R$ 32 contratados, mês incompleto e
        # ritmo de R$ 62/dia sobre R$ 40 configurados: as três disparam.
        calc = fv.calcular([_estrutura(500.0, 40.0, "2026-08-17")],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))
        rotulos = [o.split(" —")[0] for o in calc["origens"]]
        self.assertEqual(rotulos, ["configuração", "ciclo parcial", "escoamento"])

    def test_diferenca_de_arredondamento_do_mes_nao_vira_origem(self):
        # R$ 990/mês em agosto dá R$ 31,94/dia. Configurado a R$ 32, a regra
        # crua acusaria "R$ 32 está acima de R$ 32" em quase toda conta.
        calc = fv.calcular([_estrutura(760.0, 32.0, "2026-08-01")],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))
        self.assertNotIn("configuração", " ".join(calc["origens"]))

    def test_escoamento_dentro_da_faixa_nao_vira_origem(self):
        calc = fv.calcular([_estrutura(768.0, 32.0, "2026-08-01")],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))
        self.assertAlmostEqual(calc["taxa_escoamento"], 100.0, places=0)
        self.assertNotIn("escoamento", " ".join(calc["origens"]))


class MensagemTest(SimpleTestCase):
    """O gabarito da seção 7, bloco 1."""

    def _calc(self, **kw):
        base = dict(contratado_mensal=990.0, hoje=date(2026, 8, 25))
        base.update(kw)
        return fv.calcular([_estrutura(760.0, 32.0, "2026-08-01")], **base)

    def test_formato_e_limite_de_linhas(self):
        texto = fv.mensagem(self._calc())
        linhas = [l for l in texto.splitlines() if l.strip()]
        self.assertLessEqual(len(linhas), 10)
        self.assertTrue(texto.startswith("Bom dia!"))
        self.assertTrue(texto.rstrip().endswith("?"))
        for rotulo in ("*Contratado:*", "*Configurado:*", "*Gasto até",
                       "*Projeção de fechamento:*"):
            self.assertIn(rotulo, texto)

    def test_dinheiro_sem_centavos_e_com_ponto_de_milhar(self):
        self.assertEqual(fv.reais(1003.4), "R$ 1.003")
        self.assertEqual(fv.reais(990.0), "R$ 990")
        self.assertIn("*Contratado:* R$ 990/mês", fv.mensagem(self._calc()))

    def test_o_gasto_e_marcado_ate_ontem(self):
        # dias_encerrados é hoje − 1: a projeção não conta o dia corrente, e o
        # rótulo precisa dizer a mesma coisa.
        self.assertIn("*Gasto até 24/08:*", fv.mensagem(self._calc()))

    def test_nenhuma_metrica_de_performance_na_mensagem(self):
        texto = fv.mensagem(self._calc()).lower()
        for termo in ("cpm", "ctr", "cpa", "resultado", "clique", "conversa"):
            self.assertNotIn(termo, texto)

    def test_sem_contratado_a_pendencia_fica_marcada(self):
        calc = fv.calcular([_estrutura(760.0, 32.0, "2026-08-01")],
                           hoje=date(2026, 8, 25))
        self.assertIn("R$ [contratado]", fv.mensagem(calc))

    def test_correcao_negativa_vira_frase_em_vez_de_diario_negativo(self):
        calc = fv.calcular([_estrutura(1200.0, 40.0, "2026-08-01")],
                           contratado_mensal=990.0, hoje=date(2026, 8, 25))
        texto = fv.analise(calc)
        self.assertIn("já ultrapassado em R$ 210", texto)
        self.assertNotIn("R$ -", texto)

    def test_analise_interna_cabe_em_seis_linhas(self):
        calc = fv.calcular([_estrutura(500.0, 60.0, "2026-08-17")],
                           contratado_mensal=990.0, contratado_diario=50.0,
                           hoje=date(2026, 8, 25))
        self.assertLessEqual(len(fv.analise(calc).splitlines()), 6)


class FluxoVerbaTest(TestCase):
    """As duas telas, ponta a ponta."""

    def _enviar(self, arquivos=None, **campos):
        dados = {"cliente": "Rei do Celular", "orcamento": "990,00",
                 "periodicidade": "mensal", "referencia": "2026-08-25"}
        dados.update(campos)
        dados["arquivos"] = arquivos if arquivos is not None else [
            _anexo("campanhas.xlsx", CAMPANHAS_MISTAS),
            _anexo("conjuntos.xlsx", CONJUNTOS_MISTOS)]
        return self.client.post("/verba/", dados)

    def test_a_home_oferece_as_duas_frentes(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Análise de Desempenho", html)
        self.assertIn("Análise de Verba", html)
        self.assertIn('href="/desempenho/"', html)
        self.assertIn('href="/verba/"', html)

    def test_envio_leva_ao_fechamento(self):
        self.assertRedirects(self._enviar(), "/verba/fechamento/")

    def test_o_fechamento_traz_os_dois_blocos_e_a_conferencia(self):
        self._enviar()
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertIn("Bom dia! Passando o fechamento de verba", html)
        self.assertIn("Desvio:", html)
        self.assertIn("Origem:", html)
        self.assertIn("não vai pro cliente", html)
        # Conferência: as duas campanhas, com o orçamento cru ao lado.
        self.assertIn("[LEADS][CELULAR][ITU][CBO][01AGO26]", html)
        self.assertIn("R$ 20,00 Diário", html)
        self.assertIn(HERDADO, html)

    def test_o_configurado_soma_so_o_que_esta_no_ar(self):
        self._enviar()
        html = self.client.get("/verba/fechamento/").content.decode()
        # CBO R$ 20 + conjunto ativo R$ 8 = R$ 28. O conjunto pausado de R$ 4
        # fica de fora do configurado, mas o gasto continua somando tudo.
        self.assertIn("R$ 28/dia", html)
        self.assertIn("R$ 740", html)

    def test_um_arquivo_so_basta_para_conta_cbo(self):
        so_cbo = [CAMPANHAS_MISTAS[0]]
        r = self._enviar([_anexo("campanhas.xlsx", so_cbo)])
        self.assertRedirects(r, "/verba/fechamento/")
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertIn("R$ 20/dia", html)

    def test_abo_sem_o_export_de_conjunto_avisa_na_tela(self):
        r = self._enviar([_anexo("campanhas.xlsx", CAMPANHAS_MISTAS)])
        self.assertRedirects(r, "/verba/fechamento/")
        html = self.client.get("/verba/fechamento/").content.decode()
        self.assertIn("não há export de nível conjunto", html)

    def test_so_o_export_de_conjunto_e_recusado(self):
        r = self._enviar([_anexo("conjuntos.xlsx", CONJUNTOS_MISTOS)])
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "O gasto do mês sai do export de campanha")

    def test_tres_arquivos_sao_recusados(self):
        r = self._enviar([_anexo(f"{i}.xlsx", CAMPANHAS_MISTAS)
                          for i in range(3)])
        self.assertContains(r, "no máximo 2 arquivos")

    def test_recalcular_com_outra_data_sem_reenviar_planilha(self):
        self._enviar()
        r = self.client.post("/verba/fechamento/", {
            "cliente": "Rei do Celular", "orcamento": "990,00",
            "periodicidade": "mensal", "referencia": "2026-08-20"})
        html = " ".join(r.content.decode().split())
        self.assertIn("Números refeitos", html)
        self.assertIn("19 de 31 dias encerrados", html)

    def test_recalcular_com_outro_contratado(self):
        self._enviar()
        r = self.client.post("/verba/fechamento/", {
            "cliente": "Rei do Celular", "orcamento": "1.500,00",
            "periodicidade": "mensal", "referencia": "2026-08-25"})
        self.assertContains(r, "R$ 1.500/mês")

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
            "arquivos": [_anexo("c.xlsx", CAMPANHAS_MISTAS)]})
        self.assertContains(r, "Este campo é obrigatório", status_code=200)


RESPOSTA_IA_VERBA = """Bom dia! Passando o fechamento pra você confirmar 👇

*Contratado:* R$ 990/mês
*Configurado:* R$ 28/dia
*Gasto até 24/08:* R$ 740
*Projeção de fechamento:* R$ 956

O ritmo está alinhado com o contratado e o mês deve fechar no valor combinado.
Posso seguir assim até o fim do mês?"""


class MensagemVerbaIATest(TestCase):
    """O botão opcional. Nunca toca a rede: `_chamar` está sempre trocado."""

    def setUp(self):
        self.calc = fv.calcular([_estrutura(740.0, 28.0, "2026-08-01")],
                                contratado_mensal=990.0, hoje=date(2026, 8, 25))

    def _gerar(self, resposta):
        with patch.object(redator_ia, "disponivel", return_value=True), \
             patch.object(redator_ia, "_chamar",
                          MagicMock(return_value=resposta)) as chamada:
            return redator_ia.gerar_mensagem_verba(self.calc, "Rei do Celular"), \
                chamada

    def test_aceita_a_resposta_no_formato(self):
        texto, _ = self._gerar(RESPOSTA_IA_VERBA)
        self.assertTrue(texto.startswith("Bom dia!"))
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
        self.assertIn("Mantida a mensagem do cálculo", str(ctx.exception))

    def test_resposta_com_metrica_de_performance_e_recusada(self):
        ruim = RESPOSTA_IA_VERBA.replace(
            "O ritmo está alinhado com o contratado",
            "O CPM subiu e o ritmo está alinhado")
        with self.assertRaises(redator_ia.ErroDeIA) as ctx:
            self._gerar(ruim)
        self.assertIn("métrica de performance", str(ctx.exception))

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
                redator_ia.gerar_mensagem_verba(self.calc)
        self.assertEqual(ctx.exception.motivo, "chave")

    def test_falha_da_ia_preserva_a_mensagem_do_motor(self):
        self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": "990,00",
            "periodicidade": "mensal", "referencia": "2026-08-25",
            "arquivos": [_anexo("c.xlsx", CAMPANHAS_MISTAS)]})
        erro = redator_ia.ErroDeIA("A conta está sem crédito.", "credito")
        with patch.object(redator_ia, "disponivel", return_value=True), \
             patch.object(redator_ia, "gerar_mensagem_verba", side_effect=erro):
            r = self.client.post("/verba/fechamento/", {
                "cliente": "Rei do Celular", "orcamento": "990,00",
                "periodicidade": "mensal", "referencia": "2026-08-25",
                "mensagem_ia": "1"})
        html = r.content.decode()
        self.assertIn("A conta está sem crédito.", html)
        self.assertIn("Bom dia! Passando o fechamento de verba", html)
        # Motivo definitivo: o botão sai da tela junto com o aviso.
        self.assertNotIn("Reescrever com IA", html)

    def test_texto_da_ia_vai_para_a_tela_e_e_descartado_ao_recalcular(self):
        base = {"cliente": "Rei do Celular", "orcamento": "990,00",
                "periodicidade": "mensal", "referencia": "2026-08-25"}
        self.client.post("/verba/", dict(
            base, arquivos=[_anexo("c.xlsx", CAMPANHAS_MISTAS)]))
        with patch.object(redator_ia, "disponivel", return_value=True), \
             patch.object(redator_ia, "gerar_mensagem_verba",
                          return_value=RESPOSTA_IA_VERBA):
            r = self.client.post("/verba/fechamento/",
                                 dict(base, mensagem_ia="1"))
        self.assertIn("reescrita pela IA", r.content.decode())

        # Recalcular refaz os números; o texto escrito sobre os anteriores sai.
        r = self.client.post("/verba/fechamento/",
                             dict(base, referencia="2026-08-20"))
        html = r.content.decode()
        self.assertIn("do cálculo", html)
        self.assertNotIn("Posso seguir assim até o fim do mês?", html)


class TrilhoDeFechamentoTest(TestCase):
    """O trilho: a pista escalada, e as posições em CSS que o pt-BR não estraga."""

    def _fechar(self, gasto, orcamento="990,00"):
        campanhas = [dict(CAMPANHAS_MISTAS[0], gasto=gasto)]
        self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": orcamento,
            "periodicidade": "mensal", "referencia": "2026-08-25",
            "arquivos": [_anexo("c.xlsx", campanhas)]})
        return self.client.get("/verba/fechamento/")

    def test_as_posicoes_saem_com_ponto_decimal(self):
        # A locale do projeto é pt-BR: um float no template viraria "74,75", e
        # `--gasto:74,75%` é CSS inválido — o navegador descarta em silêncio e
        # a barra fica vazia sem ninguém perceber.
        trilho = self._fechar(740.0).context["trilho"]
        for chave in ("gasto", "projetado", "alvo"):
            self.assertRegex(trilho[chave], r"^\d+\.\d\d%$")
        self.assertNotIn(",", "".join(trilho[k] for k in ("gasto", "projetado", "alvo")))

    def test_o_atributo_style_chega_intacto_no_html(self):
        html = self._fechar(740.0).content.decode()
        self.assertRegex(html, r"--gasto:\d+\.\d\d%;--projetado:\d+\.\d\d%;--alvo:\d+\.\d\d%")

    def test_dentro_do_combinado_o_alvo_fecha_a_pista(self):
        # R$ 766 em 24 dias projeta ~R$ 989 contra R$ 990 contratados.
        trilho = self._fechar(766.0).context["trilho"]
        self.assertEqual(trilho["alvo"], "100.00%")
        self.assertEqual(trilho["tom"], "no-ritmo")

    def test_projecao_que_estoura_empurra_o_alvo_para_dentro(self):
        # A pista é escalada pela projeção, não pelo contratado: a barra
        # precisa APARECER passando da marca, não ser cortada na borda.
        trilho = self._fechar(1400.0).context["trilho"]
        self.assertEqual(trilho["projetado"], "100.00%")
        self.assertLess(float(trilho["alvo"].rstrip("%")), 100)
        self.assertEqual(trilho["tom"], "fora")

    def test_o_gasto_nunca_passa_do_projetado(self):
        trilho = self._fechar(740.0).context["trilho"]
        self.assertLessEqual(float(trilho["gasto"].rstrip("%")),
                             float(trilho["projetado"].rstrip("%")))

    def test_sem_contratado_nao_ha_trilho(self):
        # Sem o combinado não existe marca contra a qual comparar, e uma pista
        # sem alvo diria menos que nenhuma.
        calc = fv.calcular([_estrutura(740.0, 28.0, "2026-08-01")],
                           hoje=date(2026, 8, 25))
        from .views_verba import _trilho
        calc["contratado_mensal"] = None
        calc["projecao_fechamento"] = 0.0
        self.assertIsNone(_trilho(calc))
