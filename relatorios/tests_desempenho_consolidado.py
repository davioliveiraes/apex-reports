# -*- coding: utf-8 -*-
"""Contrato do modo Consolidado, sem alterar o fluxo Individual."""

import json
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.utils.datastructures import MultiValueDict

from relatorios import desempenho_consolidado as dc
from relatorios.forms import DesempenhoUploadForm
from relatorios.tests_desempenho import (CABECALHO, REFERENCIA, campanha,
                                         planilha)
from relatorios.views_desempenho import SESSAO_DESEMPENHO_CONSOLIDADO


def linha(nome="[LEADS][CELULAR][UNIDADE]", *, alcance=1000,
          impressoes=3000, conversas=100, custo=4, novos=70,
          inicio="2026-08-01", termino="2026-08-31"):
    dado = campanha(nome, resultados=conversas, custo=custo,
                    alcance=alcance, impressoes=impressoes,
                    frequencia=(impressoes / alcance if alcance else None),
                    cpm=12, conversas=conversas, custo_conversa=custo,
                    novos=novos)
    dado["inicio"], dado["termino"] = inicio, termino
    return dado


def unidade(nome, *linhas):
    return {"cliente": "TIM", "produto": "Celular no Boleto",
            "unidade": nome, "arquivo": f"{nome}.xlsx",
            "campanha": linhas[0].get("campanha", "Campanha"),
            "linhas": list(linhas)}


def linha_xlsx(nome, *, alcance=1000, impressoes=3000, conversas=100,
               custo=4, novos=70, inicio="2026-08-01", termino="2026-08-31"):
    dado = list(REFERENCIA)
    dado[0], dado[1], dado[2] = inicio, termino, nome
    dado[4], dado[6] = conversas, custo
    dado[7], dado[8] = alcance, impressoes
    dado[9], dado[10] = ((impressoes / alcance if alcance else None), 12)
    dado[11], dado[12], dado[13] = conversas, custo, novos
    return dado


def arquivo(nome, *linhas):
    xlsx = planilha(linhas)
    xlsx.name = nome
    return xlsx


def upload(xlsx):
    """O mesmo wrapper que o test client cria ao receber um arquivo."""
    return SimpleUploadedFile(
        xlsx.name, xlsx.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class MatematicaConsolidadaTest(SimpleTestCase):
    def test_exige_no_minimo_duas_unidades(self):
        with self.assertRaisesRegex(dc.ErroDeConsolidacao, "pelo menos 2"):
            dc.consolidar([unidade("Bragança", linha())])

    def test_recusa_mais_de_vinte_unidades(self):
        with self.assertRaisesRegex(dc.ErroDeConsolidacao, "máximo 20"):
            dc.consolidar([unidade(str(i), linha()) for i in range(21)])

    def test_duas_unidades_validas(self):
        resultado = dc.consolidar([
            unidade("Bragança", linha()), unidade("Atibaia", linha())])
        self.assertEqual(len(resultado["unidades"]), 2)

    def test_varias_unidades_validas(self):
        resultado = dc.consolidar([
            unidade(str(i), linha(alcance=100 + i)) for i in range(8)])
        self.assertEqual(len(resultado["unidades"]), 8)

    def test_soma_alcance(self):
        resultado = dc.consolidar([
            unidade("A", linha(alcance=1200)),
            unidade("B", linha(alcance=3400))])
        self.assertEqual(resultado["total_alcance"], Decimal("4600"))

    def test_soma_impressoes(self):
        resultado = dc.consolidar([
            unidade("A", linha(impressoes=2300)),
            unidade("B", linha(impressoes=4700))])
        self.assertEqual(resultado["total_impressoes"], Decimal("7000"))

    def test_soma_conversas(self):
        resultado = dc.consolidar([
            unidade("A", linha(conversas=45)),
            unidade("B", linha(conversas=155))])
        self.assertEqual(resultado["total_conversas"], Decimal("200"))

    def test_soma_novos_contatos(self):
        resultado = dc.consolidar([
            unidade("A", linha(novos=31)), unidade("B", linha(novos=69))])
        self.assertEqual(resultado["total_novos_contatos"], Decimal("100"))

    def test_frequencia_e_impressoes_por_alcance_total(self):
        resultado = dc.consolidar([
            unidade("A", linha(alcance=100, impressoes=400)),
            unidade("B", linha(alcance=900, impressoes=900))])
        self.assertEqual(resultado["frequencia_consolidada"], Decimal("1.3"))

    def test_frequencia_nao_e_media_simples_das_unidades(self):
        resultado = dc.consolidar([
            unidade("A", linha(alcance=100, impressoes=400)),
            unidade("B", linha(alcance=900, impressoes=900))])
        self.assertNotEqual(resultado["frequencia_consolidada"], Decimal("2.5"))

    def test_custo_por_conversa_e_ponderado(self):
        resultado = dc.consolidar([
            unidade("A", linha(conversas=10, custo=2)),
            unidade("B", linha(conversas=90, custo=10))])
        self.assertEqual(resultado["custo_conversa_consolidado"], Decimal("9.2"))

    def test_custo_nao_e_media_simples(self):
        resultado = dc.consolidar([
            unidade("A", linha(conversas=10, custo=2)),
            unidade("B", linha(conversas=90, custo=10))])
        self.assertNotEqual(resultado["custo_conversa_consolidado"], Decimal("6"))

    def test_zero_conversas_vira_traco(self):
        resultado = dc.consolidar([
            unidade("A", linha(conversas=0, custo=0)),
            unidade("B", linha(conversas=0, custo=0))])
        self.assertIsNone(resultado["custo_conversa_consolidado"])
        self.assertIn("Custo/conversa ... —", dc.redigir(resultado))

    def test_zero_alcance_vira_traco(self):
        resultado = dc.consolidar([
            unidade("A", linha(alcance=0, impressoes=0)),
            unidade("B", linha(alcance=0, impressoes=0))])
        self.assertIsNone(resultado["frequencia_consolidada"])
        self.assertIn("Frequência ....... —", dc.redigir(resultado))

    def test_nao_produz_nan_nem_infinity(self):
        a, b = linha(), linha()
        a["alcance"], b["custo_conversa"] = float("nan"), float("inf")
        resultado = dc.consolidar([unidade("A", a), unidade("B", b)])
        bruto = json.dumps(resultado, default=str)
        self.assertNotIn("NaN", bruto)
        self.assertNotIn("Infinity", bruto)

    def test_periodos_iguais_sao_aceitos(self):
        resultado = dc.consolidar([
            unidade("A", linha()), unidade("B", linha())])
        self.assertEqual(resultado["periodo"], "01/08/2026 a 31/08/2026")

    def test_periodos_divergentes_sao_recusados_e_listados(self):
        with self.assertRaises(dc.PeriodosDivergentes) as contexto:
            dc.consolidar([
                unidade("A", linha(termino="2026-08-31")),
                unidade("B", linha(termino="2026-08-30"))])
        self.assertEqual(len(contexto.exception.periodos), 2)
        self.assertIn("31/08", contexto.exception.periodos[0]["periodo"])


class SaidaConsolidadaTest(SimpleTestCase):
    def setUp(self):
        self.resultado = dc.consolidar([
            unidade("Bragança", linha(alcance=26303, impressoes=125841,
                                       conversas=559, custo=2.75, novos=391)),
            unidade("Atibaia", linha(alcance=10000, impressoes=30000,
                                      conversas=100, custo=4.25, novos=60)),
        ])
        self.texto = dc.redigir(self.resultado)

    def test_formata_inteiros_em_pt_br(self):
        self.assertIn("36.303", self.texto)
        self.assertIn("155.841", self.texto)

    def test_formata_brl(self):
        self.assertRegex(self.texto, r"Custo/conversa \.\.\. R\$ \d,\d{2}")

    def test_texto_traz_cliente_e_produto(self):
        self.assertIn("*TIM — Celular no Boleto*", self.texto)

    def test_texto_comeca_com_titulo_desempenho(self):
        self.assertTrue(self.texto.startswith(
            "*Desempenho*\n\n*TIM — Celular no Boleto*"))

    def test_texto_traz_todas_as_unidades(self):
        self.assertIn("Bragança + Atibaia", self.texto)

    def test_texto_traz_periodo_curto(self):
        self.assertIn("Período: 01/08 a 31/08", self.texto)

    def test_lista_longa_quebra_sem_esconder_unidades(self):
        dados = dc.consolidar([
            unidade(f"Unidade muito extensa {i}", linha()) for i in range(20)])
        texto = dc.redigir(dados)
        for i in range(20):
            self.assertIn(f"Unidade muito extensa {i}", texto)

    def test_conferencia_termina_com_linha_consolidada(self):
        linhas = dc.conferencia(self.resultado)
        self.assertEqual(linhas[-1]["unidade"], "CONSOLIDADO")
        self.assertTrue(linhas[-1]["consolidado"])


class FormularioConsolidadoTest(SimpleTestCase):
    def _form(self, arquivos, **dados):
        base = {"modo": "consolidado", "cliente": "TIM",
                "produto": "Celular no Boleto"}
        base.update(dados)
        return DesempenhoUploadForm(
            base, MultiValueDict({"arquivos": [upload(a) for a in arquivos]}))

    def test_tentativa_com_um_arquivo(self):
        form = self._form([arquivo("a.xlsx", linha_xlsx("Campanha A"))])
        self.assertFalse(form.is_valid())
        self.assertIn("pelo menos 2", str(form.errors["arquivos"]))

    def test_tentativa_com_vinte_e_um_arquivos(self):
        arquivos = [arquivo(f"{i}.xlsx", linha_xlsx(f"Campanha {i}"))
                    for i in range(21)]
        form = self._form(arquivos)
        self.assertFalse(form.is_valid())
        self.assertIn("Máximo de 20", str(form.errors["arquivos"]))

    def test_dois_arquivos_passam_a_validacao_do_form(self):
        form = self._form([
            arquivo("a.xlsx", linha_xlsx("Campanha A")),
            arquivo("b.xlsx", linha_xlsx("Campanha B")),
        ])
        self.assertTrue(form.is_valid(), form.errors)

    def test_produto_e_obrigatorio_so_no_consolidado(self):
        consolidado = self._form([
            arquivo("a.xlsx", linha_xlsx("A")),
            arquivo("b.xlsx", linha_xlsx("B"))], produto="")
        individual = DesempenhoUploadForm(
            {"cliente": "TIM"}, MultiValueDict({
                "arquivo": [upload(arquivo("a.xlsx", linha_xlsx("A")))]}))
        self.assertFalse(consolidado.is_valid())
        self.assertTrue(individual.is_valid(), individual.errors)


class FluxoConsolidadoTest(TestCase):
    def _enviar(self, arquivos, unidades=None, follow=True):
        return self.client.post("/desempenho/", {
            "modo": "consolidado", "cliente": "TIM",
            "produto": "Celular no Boleto",
            "unidades": unidades or [f"Unidade {i}" for i in range(len(arquivos))],
            "arquivos": arquivos,
        }, follow=follow)

    def _sessao(self, unidades, invalidos=()):
        sessao = self.client.session
        sessao[SESSAO_DESEMPENHO_CONSOLIDADO] = {
            "cliente": "TIM", "produto": "Celular no Boleto",
            "unidades": unidades, "arquivos_invalidos": list(invalidos),
        }
        sessao.save()

    def test_upload_de_dois_arquivos_abre_o_consolidado(self):
        resposta = self._enviar([
            arquivo("braganca.xlsx", linha_xlsx("Campanha A")),
            arquivo("atibaia.xlsx", linha_xlsx("Campanha B")),
        ], ["Bragança", "Atibaia"])
        self.assertTemplateUsed(resposta, "relatorios/desempenho_consolidado.html")
        self.assertContains(resposta, "Consolidado de Desempenho")
        self.assertIsNotNone(resposta.context["resultado"])

    def test_arquivo_invalido_entre_validos_fica_visivel(self):
        invalido = planilha([["Campanha X", 10]], ["Nome da campanha", "X"])
        invalido.name = "verba.xlsx"
        resposta = self._enviar([
            arquivo("a.xlsx", linha_xlsx("Campanha A")), invalido,
            arquivo("b.xlsx", linha_xlsx("Campanha B")),
        ], ["A", "Inválida", "B"])
        self.assertContains(resposta, "verba.xlsx")
        self.assertContains(resposta, "não entrou no consolidado")
        self.assertEqual(resposta.context["n_unidades"], 2)
        self.assertIsNotNone(resposta.context["resultado"])

    def test_periodos_divergentes_bloqueiam_a_saida(self):
        resposta = self._enviar([
            arquivo("a.xlsx", linha_xlsx("Campanha A", termino="2026-08-31")),
            arquivo("b.xlsx", linha_xlsx("Campanha B", termino="2026-08-30")),
        ], ["Bragança", "Atibaia"])
        self.assertContains(resposta, "Os arquivos possuem períodos diferentes")
        self.assertContains(resposta, "Bragança — 01/08/2026 a 31/08/2026")
        self.assertIsNone(resposta.context["resultado"])

    def test_mais_de_uma_campanha_exige_selecao(self):
        self._sessao([
            {"unidade": "A", "arquivo": "a.xlsx",
             "linhas": [linha("[LEADS][A][01]"), linha("[LEADS][B][01]")]},
            {"unidade": "B", "arquivo": "b.xlsx",
             "linhas": [linha("[LEADS][A][02]")]},
        ])
        resposta = self.client.get("/desempenho/consolidado/")
        self.assertContains(resposta, "Escolha a campanha deste arquivo")
        self.assertIsNone(resposta.context["resultado"])

    def test_selecao_e_individual_por_arquivo(self):
        self._sessao([
            {"unidade": "A", "arquivo": "a.xlsx",
             "linhas": [linha("[LEADS][A][01]", alcance=100),
                        linha("[LEADS][B][01]", alcance=999)]},
            {"unidade": "B", "arquivo": "b.xlsx",
             "linhas": [linha("[LEADS][A][02]", alcance=200)]},
        ])
        resposta = self.client.post("/desempenho/consolidado/", {
            "unidade_0": "A", "campanha_0": "LEADS · A",
            "unidade_1": "B", "campanha_1": "LEADS · A",
            "aplicar_consolidado": "1",
        })
        self.assertEqual(resposta.context["resultado"]["total_alcance"],
                         Decimal("300"))

    def test_campanha_nao_selecionada_e_ignorada(self):
        self._sessao([
            {"unidade": "A", "arquivo": "a.xlsx",
             "linhas": [linha("[LEADS][A][01]", conversas=10),
                        linha("[LEADS][B][01]", conversas=900)]},
            {"unidade": "B", "arquivo": "b.xlsx",
             "linhas": [linha("[LEADS][A][02]", conversas=20)]},
        ])
        resposta = self.client.post("/desempenho/consolidado/", {
            "unidade_0": "A", "campanha_0": "LEADS · A",
            "unidade_1": "B", "campanha_1": "LEADS · A",
        })
        self.assertEqual(resposta.context["resultado"]["total_conversas"],
                         Decimal("30"))

    def test_tela_tem_os_seis_indicadores_e_a_conferencia(self):
        resposta = self._enviar([
            arquivo("a.xlsx", linha_xlsx("Campanha A")),
            arquivo("b.xlsx", linha_xlsx("Campanha B")),
        ], ["A", "B"])
        for rotulo in ("Alcance", "Impressões", "Frequência", "Conversas",
                       "Custo/conversa", "Novos contatos"):
            self.assertContains(resposta, rotulo)
        self.assertContains(resposta, "CONSOLIDADO")

    def test_botao_copia_somente_o_texto_compacto(self):
        resposta = self._enviar([
            arquivo("a.xlsx", linha_xlsx("Campanha A")),
            arquivo("b.xlsx", linha_xlsx("Campanha B")),
        ], ["A", "B"])
        html = resposta.content.decode()
        self.assertIn('data-alvo="txt-consolidado"', html)
        self.assertIn("Copiar consolidado", html)
        self.assertIn("Consolidado copiado.", html)

    def test_modo_consolidado_nao_oferece_ia(self):
        resposta = self._enviar([
            arquivo("a.xlsx", linha_xlsx("Campanha A")),
            arquivo("b.xlsx", linha_xlsx("Campanha B")),
        ], ["A", "B"])
        self.assertNotContains(resposta, "Reescrever com IA")

    @patch("relatorios.redator_ia.reescrever")
    def test_modo_consolidado_nao_chama_a_ia(self, reescrever):
        self._enviar([
            arquivo("a.xlsx", linha_xlsx("Campanha A")),
            arquivo("b.xlsx", linha_xlsx("Campanha B")),
        ], ["A", "B"])
        reescrever.assert_not_called()

    def test_sem_sessao_volta_ao_painel(self):
        resposta = self.client.get("/desempenho/consolidado/")
        self.assertRedirects(resposta, "/desempenho/")

    def test_fluxo_individual_antigo_continua_funcionando(self):
        resposta = self.client.post("/desempenho/", {
            "cliente": "TIM Brasil", "arquivo": planilha(),
        }, follow=True)
        self.assertTemplateUsed(resposta, "relatorios/desempenho_analise.html")
        self.assertTrue(resposta.context["texto"].startswith("*Desempenho*\n\n"))
        self.assertContains(resposta, "Reescrever com IA")

    def test_prompt_da_ia_individual_nao_foi_acoplado_ao_consolidado(self):
        from relatorios import redator_ia
        self.assertNotIn("Consolidado", redator_ia.PROMPT_REESCRITA_DESEMPENHO)
        self.assertIn("exatamente quatro parágrafos",
                      redator_ia.PROMPT_REESCRITA_DESEMPENHO)
