# -*- coding: utf-8 -*-
"""
Testes do fluxo web (upload → revisão → PDF), cobrindo o modo individual
(1 anexo) e o consolidado (2 a 20 anexos) no layout dark de UMA página
(WeasyPrint). A contagem de páginas usa `pdfinfo` quando disponível e
PyMuPDF como fallback.
"""
import io
import json
import shutil
import subprocess
import tempfile
from datetime import date
from unittest.mock import patch

import fitz  # PyMuPDF — extração de texto e contagem de páginas
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from . import analysis, benchmarks, metricas, parser_xlsx
from .analysis import templates
from .parser_xlsx import consolidar_grupo, ler_export_meta
from .views import _MESES_PT, _paragrafos as _paragrafos_analise

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

CABECALHO = [
    "Nome da campanha", "Veiculação da campanha", "Resultados",
    "Indicador de resultado", "Valor usado (BRL)", "Impressões", "Alcance",
    "Cliques no link", "Início dos relatórios", "Término dos relatórios",
]

INDICADOR = "Conversas por mensagem iniciadas"


def _planilha(campanhas, inicio="2026-07-01", fim="2026-07-15", indicador=INDICADOR):
    wb = Workbook()
    ws = wb.active
    ws.append(CABECALHO)
    for c in campanhas:
        ws.append([
            c["nome"], c.get("status", "active"), c.get("res"),
            c.get("indicador", indicador), c.get("inv"), c.get("imp"),
            c.get("alc"), c.get("cliques"), inicio, fim,
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _arquivo(nome, campanhas, **kw):
    return SimpleUploadedFile(nome, _planilha(campanhas, **kw), content_type=XLSX_MIME)


def _planilha_sem_veiculacao(campanhas, inicio="2026-07-01", fim="2026-07-15"):
    """Export legado, sem a coluna de veiculação da campanha."""
    wb = Workbook()
    ws = wb.active
    ws.append([c for c in CABECALHO if c != "Veiculação da campanha"])
    for c in campanhas:
        ws.append([c["nome"], c.get("res"), INDICADOR, c.get("inv"), c.get("imp"),
                   c.get("alc"), c.get("cliques"), inicio, fim])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _bytes_pdf(resposta):
    return b"".join(resposta.streaming_content)


def _texto_pdf(pdf_bytes):
    """Texto de todas as páginas do PDF, com espaços normalizados."""
    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    texto = "\n".join(p.get_text() for p in pdf)
    pdf.close()
    return " ".join(texto.split())


def _paginas(pdf_bytes):
    """Nº de páginas via `pdfinfo` (poppler); fallback PyMuPDF se ausente."""
    if shutil.which("pdfinfo"):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(pdf_bytes)
            f.flush()
            saida = subprocess.run(["pdfinfo", f.name], capture_output=True,
                                   text=True, check=True).stdout
        for linha in saida.splitlines():
            if linha.startswith("Pages:"):
                return int(linha.split(":")[1])
    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    n = len(pdf)
    pdf.close()
    return n


def _tem_imagem(pdf_bytes, minimo=2):
    """True se a página tiver ao menos `minimo` imagens (logo + donut)."""
    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    n = len(pdf[0].get_images())
    pdf.close()
    return n >= minimo


class FluxoIndividualTest(TestCase):
    """1 anexo: página única com funil, tabela + donut por campanha e análise."""

    def _upload(self):
        f = _arquivo("iloc.xlsx", [
            {"nome": "Campanha A", "res": 40, "inv": 80.0, "imp": 4000,
             "alc": 2500, "cliques": 300},
            {"nome": "Campanha B", "res": 20, "inv": 120.0, "imp": 2000,
             "alc": 1000, "cliques": 120},
        ])
        return self.client.post("/", {"cliente": "ILOC", "arquivos": [f]})

    def _gerar_pdf(self):
        return self.client.post("/revisao/", {
            "cliente": "ILOC", "periodo": "01/07/2026 a 15/07/2026",
            "analise": "Texto de análise.",
        })

    def test_fluxo_completo(self):
        r = self._upload()
        self.assertEqual(r.status_code, 302)

        r = self.client.get("/revisao/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("Topo de Funil — Atração", html)
        self.assertNotIn("checklist_agencia", html)

        dados = self.client.session["relatorio_apex"]
        self.assertNotIn("modo", dados)

        r = self._gerar_pdf()
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="ILOC-anexounico-1-jul-26-15-jul-26.pdf"',
                      r["Content-Disposition"])
        pdf = _bytes_pdf(r)
        self.assertEqual(_paginas(pdf), 1, "o relatório deve ter UMA página")

        texto = _texto_pdf(pdf)
        self.assertIn("Funil de Vendas", texto)
        self.assertIn("Desempenho por Campanha", texto)
        self.assertIn("Análise do Período", texto)
        # Tabela: share de resultados por campanha (40/60 = 67%)
        self.assertIn("Campanha A", texto)
        self.assertIn("67%", texto)
        # Donut embutido como imagem (além do logo)
        self.assertTrue(_tem_imagem(pdf), "donut ausente do PDF")
        # Sem seções antigas do layout ReportLab
        self.assertNotIn("Checklist", texto)
        self.assertNotIn("Composição por Unidade", texto)
        # Status de veiculação é assunto interno — não aparece no relatório
        self.assertNotIn("Status", texto)

    def test_oito_campanhas_agrupam_em_outras(self):
        f = _arquivo("conta.xlsx", [
            {"nome": f"Campanha {i}", "res": 10 * (8 - i), "inv": 50.0 + i,
             "imp": 3000, "alc": 2000, "cliques": 200}
            for i in range(8)
        ])
        r = self.client.post("/", {"cliente": "ILOC", "arquivos": [f]})
        self.assertEqual(r.status_code, 302)

        r = self._gerar_pdf()
        self.assertEqual(r.status_code, 200)
        pdf = _bytes_pdf(r)
        self.assertEqual(_paginas(pdf), 1,
                         "8 campanhas devem agrupar em 'Outras' e manter 1 página")
        texto = _texto_pdf(pdf)
        # 4 maiores + linha agregada com as 4 restantes
        self.assertIn("Campanha 0", texto)
        self.assertIn("Campanha 3", texto)
        self.assertIn("Outras (4)", texto)
        self.assertNotIn("Campanha 7", texto)


class FluxoConsolidadoTest(TestCase):
    """2+ anexos: página única com funil geral, donut por unidade e análise."""

    def _upload_tres(self):
        # A: custo/resultado 2,00 (melhor) · B: 6,00 · C: sem resultados
        arquivos = [
            _arquivo("TIM_Sao_Jose.xlsx", [
                {"nome": "Camp SJ", "res": 50, "inv": 100.0, "imp": 10000,
                 "alc": 5000, "cliques": 500},
            ]),
            _arquivo("TIM_Braganca.xlsx", [
                {"nome": "Camp BR", "res": 50, "inv": 300.0, "imp": 20000,
                 "alc": 10000, "cliques": 1000},
            ]),
            _arquivo("TIM_Maxshopping.xlsx", [
                {"nome": "Camp MX", "res": 0, "inv": 200.0, "imp": 30000,
                 "alc": 20000, "status": "not_delivering"},
            ]),
        ]
        return self.client.post("/", {"cliente": "TIM Brasil", "arquivos": arquivos})

    def test_agregacao(self):
        r = self._upload_tres()
        self.assertEqual(r.status_code, 302)

        dados = self.client.session["relatorio_apex"]
        self.assertEqual(dados["modo"], "grupo")
        self.assertEqual(len(dados["unidades"]), 3)

        # Funil geral: totais somados e taxas recalculadas sobre os totais
        linhas = {m: v for etapa in dados["funil"]["etapas"]
                  for m, v, _ in etapa["linhas"]}
        self.assertEqual(linhas["Investimento Total"], "R$ 600,00")
        self.assertEqual(linhas["Impressões"], "60.000 visualizações")
        # CPM = 600 / 60000 * 1000 = 10,00 (não média dos CPMs por unidade)
        self.assertEqual(linhas["CPM (custo por mil)"], "R$ 10,00")
        self.assertEqual(linhas["CTR (taxa de cliques)"], "2,50%")
        self.assertEqual(linhas["Conversas Iniciadas"], "100")
        self.assertEqual(linhas["Custo por Conversa (CPA)"], "R$ 6,00")

    def test_pdf_consolidado(self):
        self._upload_tres()

        r = self.client.get("/revisao/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "unidade_0")

        r = self.client.post("/revisao/", {
            "cliente": "TIM Brasil", "periodo": "01/07/2026 a 15/07/2026",
            "analise": "Análise do grupo.",
            "unidade_0": "TIM São José", "unidade_1": "TIM Bragança",
            "unidade_2": "TIM Maxshopping",
        })
        self.assertEqual(r.status_code, 200)
        pdf = _bytes_pdf(r)
        self.assertEqual(_paginas(pdf), 1, "o consolidado deve ter UMA página")

        texto = _texto_pdf(pdf)
        self.assertIn("Consolidado de 3 unidades", texto)
        self.assertIn("R$ 600,00", texto)                 # total somado no funil
        self.assertIn("Composição por Unidade", texto)
        # Legenda do donut: nome + valor + percentual (unidades com resultado)
        self.assertIn("TIM São José — 50 (50%)", texto)
        self.assertIn("TIM Bragança — 50 (50%)", texto)
        # Rodapé lista as unidades somadas + nota de sobreposição de alcance
        self.assertIn("TIM São José, TIM Bragança, TIM Maxshopping", texto)
        self.assertIn("sobreposição de audiência", texto)
        # Donut embutido; sem tabela de campanhas no consolidado
        self.assertTrue(_tem_imagem(pdf), "donut ausente do PDF")
        self.assertNotIn("Desempenho por Campanha", texto)
        self.assertNotIn("Ranking", texto)
        # Status de veiculação (unidade C está not_delivering) não vaza
        self.assertNotIn("not_delivering", texto)

    def test_indicador_divergente_gera_aviso(self):
        arquivos = [
            _arquivo("loja_a.xlsx", [{"nome": "C", "res": 10, "inv": 50.0,
                                      "imp": 1000, "alc": 800}]),
            _arquivo("loja_b.xlsx", [{"nome": "C", "res": 5, "inv": 40.0,
                                      "imp": 900, "alc": 700}],
                     indicador="Compras"),
        ]
        r = self.client.post("/", {"cliente": "Grupo", "arquivos": arquivos})
        self.assertEqual(r.status_code, 302)

        # Aviso na tela de revisão (não bloqueia o fluxo)
        r = self.client.get("/revisao/")
        self.assertContains(r, "não usam o mesmo indicador")

        # A validação é interna: o aviso NÃO vaza para o PDF do cliente
        r = self.client.post("/revisao/", {
            "cliente": "Grupo", "periodo": "01/07/2026 a 15/07/2026",
            "analise": "Análise.", "unidade_0": "Loja A", "unidade_1": "Loja B",
        })
        self.assertEqual(r.status_code, 200)
        pdf = _bytes_pdf(r)
        self.assertEqual(_paginas(pdf), 1)
        self.assertNotIn("não usam o mesmo indicador", _texto_pdf(pdf))

    def test_vinte_arquivos_uma_pagina(self):
        arquivos = [
            _arquivo(f"unidade_{i:02d}.xlsx", [
                {"nome": f"Camp {i}", "res": 10 + i, "inv": 50.0 + i,
                 "imp": 1000, "alc": 800, "cliques": 100},
            ])
            for i in range(20)
        ]
        r = self.client.post("/", {"cliente": "Grupo 20", "arquivos": arquivos})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.client.session["relatorio_apex"]["unidades"]), 20)

        post = {"cliente": "Grupo 20", "periodo": "01/07/2026 a 15/07/2026",
                "analise": "Análise."}
        post.update({f"unidade_{i}": f"Unidade {i:02d}" for i in range(20)})
        r = self.client.post("/revisao/", post)
        self.assertEqual(r.status_code, 200)
        pdf = _bytes_pdf(r)
        self.assertEqual(_paginas(pdf), 1,
                         "20 unidades devem caber em 1 página (fatias <3% viram 'Outras')")
        texto = _texto_pdf(pdf)
        self.assertIn("Consolidado de 20 unidades", texto)
        # Rodapé lista todas as unidades
        self.assertIn("Unidade 00", texto)
        self.assertIn("Unidade 19", texto)


def _dados(campanhas, **kw):
    """Atalho: parseia uma planilha sintética direto pelo ler_export_meta."""
    return ler_export_meta(io.BytesIO(_planilha(campanhas, **kw)))


def _linhas_funil(dados):
    """{métrica: (valor, leitura)} de todas as etapas do funil."""
    return {m: (v, l) for etapa in dados["funil"]["etapas"]
            for m, v, l in etapa["linhas"]}


class CasosReaisTest(TestCase):
    """
    Duas contas reais, do anexo à página impressa.

    Elix Finance sai do PDF em `docs/Elix-Finance-anexounico-31-jul-26-6-ago-26.pdf`.
    TecnoCell Chapada não tem PDF versionado: os números vêm do export
    `Tecno-Cell-Chapada-Campanhas-30-de-jul-de-2026-5-de-ago-de-2026.xlsx`,
    lido em 07/08/2026 — foi ele que revelou o rótulo `Valor gasto (BRL)`.
    """

    # 31/07 a 06/08/2026 · R$ 257,86 · 13 conversas · CPA R$ 19,84
    ELIX = [{"nome": "[LEADS][CLINICA-BOLETO][ABO][31JUL26]", "res": 13,
             "inv": 171.24, "imp": 3900, "alc": 1950},
            {"nome": "[LEADS][CLINICA-BOL][ABO][04AGO26]", "res": 0,
             "inv": 70.51, "imp": 1200, "alc": 600},
            {"nome": "[LEADS][CLINICA-BOL][ABO][04AGO26] — Cópia", "res": 0,
             "inv": 16.11, "imp": 460, "alc": 213}]

    # 30/07 a 05/08/2026 · R$ 338,80 · 82 conversas · CPA R$ 4,13 · 1 campanha
    TECNOCELL = [{"nome": "[VENDAS][IPHONE-ASSTECH][ABO][27JUL26]", "res": 82,
                  "inv": 338.80, "imp": 35840, "alc": 10206}]

    def _ler(self, campanhas, inicio, fim):
        return parser_xlsx.ler_export_meta(io.BytesIO(
            _planilha(campanhas, inicio=inicio, fim=fim)))

    def _elix(self):
        return self._ler(self.ELIX, "2026-07-31", "2026-08-06")

    def _tecnocell(self):
        return self._ler(self.TECNOCELL, "2026-07-30", "2026-08-05")

    # ---- Elix: verba parada é o assunto do período ----
    def test_elix_numeros_batem_com_o_pdf(self):
        n = self._elix()["_num"]
        self.assertAlmostEqual(n["investimento"], 257.86, places=2)
        self.assertEqual(n["resultados"], 13)
        self.assertAlmostEqual(n["custo_resultado"], 19.83, places=1)
        self.assertAlmostEqual(n["frequencia"], 2.01, places=2)

    def test_elix_aponta_a_verba_parada_e_a_faixa_esperada(self):
        av = self._elix()["avaliacao"]
        self.assertEqual(av["derivados"]["verba_sem_retorno"], 70.51)
        self.assertEqual(av["derivados"]["verba_em_aprendizado"], 16.11)
        self.assertEqual(av["derivados"]["resultados_esperados"], [3, 4])
        self.assertEqual(av["proximo_passo"], "corrigir_a_captacao")

    def test_elix_no_pdf_diz_que_o_gargalo_e_a_captacao(self):
        dados = self._elix()
        self.client.post("/", {"cliente": "Elix Finance", "arquivos": [
            _arquivo("elix.xlsx", self.ELIX, inicio="2026-07-31",
                     fim="2026-08-06")]})
        r = self.client.post("/revisao/", {
            "cliente": "Elix Finance", "periodo": "31/07/2026 a 06/08/2026",
            "analise": dados["analise_sugerida"].replace("\n", "\r\n")})
        pdf = _bytes_pdf(r)
        self.assertEqual(_paginas(pdf), 1)
        texto = _texto_pdf(pdf)
        self.assertIn("R$ 70,51", texto)
        self.assertIn("de 3 a 4 registros", texto)
        self.assertIn("na etapa de captação", texto)
        # E o número derivado NÃO é a soma das duas zeradas: a de R$ 16,11
        # ainda não gastou o equivalente a um contato.
        self.assertNotIn("R$ 86,62", texto)

    # ---- TecnoCell: entrega sadia, público saturado ----
    def test_tecnocell_numeros_batem_com_o_export(self):
        n = self._tecnocell()["_num"]
        self.assertAlmostEqual(n["investimento"], 338.80, places=2)
        self.assertEqual(n["resultados"], 82)
        self.assertAlmostEqual(n["custo_resultado"], 4.13, places=2)
        self.assertAlmostEqual(n["frequencia"], 3.51, places=2)

    def test_tecnocell_sem_verba_parada_e_publico_saturado(self):
        av = self._tecnocell()["avaliacao"]
        self.assertEqual(av["classificacao"], "BOM")   # 4,13 > teto 4,00
        self.assertNotIn("verba_sem_retorno", av["sinais"])
        self.assertIn("campanha_unica", av["sinais"])
        self.assertIn("frequencia_saturada", av["sinais"])
        self.assertEqual(av["proximo_passo"], "ampliar_publico_e_criativos")

    def test_tecnocell_no_pdf_nao_repete_os_numeros_da_tabela(self):
        dados = self._tecnocell()
        self.assertNotRegex(dados["analise_sugerida"], r"\d")
        self.assertNotIn("R$", dados["analise_sugerida"])

    def test_as_duas_contas_sao_lidas_de_forma_diferente(self):
        # Mesma janela de 7 dias e mesma aplicação: o texto tem que separar
        # uma conta com gargalo de captação de uma com público desgastado.
        elix = self._elix()["analise_sugerida"]
        tecno = self._tecnocell()["analise_sugerida"]
        self.assertNotEqual(elix, tecno)
        self.assertIn("captação", elix)
        self.assertNotIn("captação", tecno)
        self.assertIn("já viu os anúncios muitas vezes", tecno)


class OrcamentoDePaginaTest(TestCase):
    """
    O teto de caracteres da análise é MEDIDO, não estimado.

    Acha por bissecção o maior texto que ainda cabe numa página, gerando PDF
    de verdade em cada passo, e confere que o teto em `templates` está abaixo
    disso com a folga de 10%. Mexeu na fonte, no espaçamento ou no layout? Este
    teste falha dizendo o número novo.
    """

    ROTULOS = ["Leitura do período.", "Ponto de atenção.", "Leitura atual.",
               "O que vamos fazer.", "Objetivo do próximo ciclo."]
    FRASE = ("O custo por resultado ficou dentro da faixa de trabalho da conta "
             "e a verba investida segue virando contato real com cliente de "
             "forma previsível ao longo de todo o período observado. ")
    FOLGA = 0.90
    BLOCOS = 5          # pior caso: cada parágrafo custa o respiro entre eles

    def _texto(self, total, blocos=None):
        """String de exatamente `total` caracteres, em parágrafos rotulados —
        rótulos e separadores contam, porque é a string inteira que o limite
        controla."""
        blocos = blocos or self.BLOCOS
        marcas = ["<b>%s</b> " % self.ROTULOS[i % len(self.ROTULOS)]
                  for i in range(blocos)]
        sobra = total - sum(len(m) for m in marcas) - 2 * (blocos - 1)
        por_bloco = sobra // blocos
        partes = []
        for i, marca in enumerate(marcas):
            n = por_bloco if i < blocos - 1 else sobra - por_bloco * (blocos - 1)
            partes.append(marca + (self.FRASE * (n // len(self.FRASE) + 2))[:n])
        texto = "\n\n".join(partes)
        self.assertEqual(len(texto), total)
        return texto

    def _cabe(self, campos, total):
        r = self.client.post("/revisao/", dict(campos, analise=self._texto(total)))
        return _paginas(_bytes_pdf(r)) == 1

    def _maximo(self, campos, teto_busca=4000):
        baixo, alto = 600, teto_busca
        self.assertTrue(self._cabe(campos, baixo), "nem o texto mínimo cabe")
        self.assertFalse(self._cabe(campos, alto),
                         "o limite de busca não estoura a página — suba o teto")
        while alto - baixo > 25:
            meio = (baixo + alto) // 2
            if self._cabe(campos, meio):
                baixo = meio
            else:
                alto = meio
        return baixo

    def _conferir(self, limite, medido, modo):
        self.assertLessEqual(
            limite, int(medido * self.FOLGA),
            "o teto de %s está alto demais: cabem %d caracteres, então o teto "
            "com 10%% de folga é %d — atualize templates.py"
            % (modo, medido, int(medido * self.FOLGA)))

    def test_no_teto_ainda_cabe_uma_pagina(self):
        # A verificação direta do que o teto promete: um texto do tamanho
        # exato do limite sai numa página só, nos dois modos.
        casos = [
            ("conta", templates.LIMITE_PDF, [
                _arquivo("a.xlsx", [
                    {"nome": "Camp A", "res": 40, "inv": 80.0, "imp": 4000,
                     "alc": 2500, "cliques": 300},
                    {"nome": "Camp B", "res": 20, "inv": 120.0, "imp": 2000,
                     "alc": 1000, "cliques": 120},
                    {"nome": "Camp C", "res": 10, "inv": 60.0, "imp": 1500,
                     "alc": 900, "cliques": 80},
                    {"nome": "Camp D", "res": 5, "inv": 40.0, "imp": 900,
                     "alc": 500, "cliques": 40}])],
             {"cliente": "Medição", "periodo": "01/07/2026 a 31/07/2026"}),
            ("consolidado", templates.LIMITE_PDF_GRUPO,
             [_arquivo("u%d.xlsx" % i, [
                 {"nome": "C", "res": 40 + i, "inv": 80.0 + i, "imp": 4000,
                  "alc": 2500, "cliques": 300}]) for i in range(3)],
             {"cliente": "Medição", "periodo": "01/07/2026 a 31/07/2026",
              "unidade_0": "Praça A", "unidade_1": "Praça B",
              "unidade_2": "Praça C"}),
        ]
        for modo, limite, arquivos, campos in casos:
            with self.subTest(modo=modo):
                self.client.post("/", {"cliente": "Medição",
                                       "arquivos": arquivos})
                for blocos in (3, 4, 5):
                    r = self.client.post("/revisao/", dict(
                        campos, analise=self._texto(limite, blocos)))
                    self.assertEqual(
                        _paginas(_bytes_pdf(r)), 1,
                        "%s: %d caracteres em %d blocos estouraram a página"
                        % (modo, limite, blocos))

    def test_teto_da_conta_individual(self):
        self.client.post("/", {"cliente": "Medição", "arquivos": [
            _arquivo("a.xlsx", [
                {"nome": "Camp A", "res": 40, "inv": 80.0, "imp": 4000,
                 "alc": 2500, "cliques": 300},
                {"nome": "Camp B", "res": 20, "inv": 120.0, "imp": 2000,
                 "alc": 1000, "cliques": 120},
                {"nome": "Camp C", "res": 10, "inv": 60.0, "imp": 1500,
                 "alc": 900, "cliques": 80},
                {"nome": "Camp D", "res": 5, "inv": 40.0, "imp": 900,
                 "alc": 500, "cliques": 40}])]})
        campos = {"cliente": "Medição", "periodo": "01/07/2026 a 31/07/2026"}
        self._conferir(templates.LIMITE_PDF, self._maximo(campos), "conta")

    def test_teto_do_consolidado(self):
        self.client.post("/", {"cliente": "Medição", "arquivos": [
            _arquivo("u%d.xlsx" % i, [
                {"nome": "C", "res": 40 + i, "inv": 80.0 + i, "imp": 4000,
                 "alc": 2500, "cliques": 300}]) for i in range(3)]})
        campos = {"cliente": "Medição", "periodo": "01/07/2026 a 31/07/2026",
                  "unidade_0": "Praça A", "unidade_1": "Praça B",
                  "unidade_2": "Praça C"}
        self._conferir(templates.LIMITE_PDF_GRUPO, self._maximo(campos),
                       "consolidado")


class ContextoDoPeriodoTest(TestCase):
    """
    Bloco "Contexto do período" na tela 02: campos opcionais que viram sinal e
    o botão que regera a análise sem reenviar o anexo.
    """

    ELIX = [{"nome": "A", "res": 13, "inv": 171.24, "imp": 3900, "alc": 1950},
            {"nome": "B", "res": 0, "inv": 70.51, "imp": 1200, "alc": 600},
            {"nome": "C", "res": 0, "inv": 16.11, "imp": 460, "alc": 213}]

    def _importar(self, campanhas=None, cliente="Elix"):
        f = _arquivo("e.xlsx", campanhas or self.ELIX,
                     inicio="2026-07-31", fim="2026-08-06")
        self.client.post("/", {"cliente": cliente, "arquivos": [f]})
        return self.client.session["relatorio_apex"]

    def _regerar(self, **campos):
        base = {"cliente": "Elix", "periodo": "31/07/2026 a 06/08/2026",
                "analise": "texto que o operador tinha", "regerar": "1"}
        base.update(campos)
        r = self.client.post("/revisao/", base)
        self.assertEqual(r.status_code, 200)
        return r, self.client.session["relatorio_apex"]

    def test_bloco_aparece_na_tela_dois_e_nao_na_um(self):
        self._importar()
        painel = self.client.get("/").content.decode()
        self.assertNotIn("Contexto do período", painel)
        revisao = self.client.get("/revisao/").content.decode()
        self.assertIn("Contexto do período", revisao)
        self.assertIn('name="regerar"', revisao)
        for campo in ("id_mudanca", "id_problema", "id_situacao",
                      "id_passo", "id_meta_cpa"):
            self.assertIn(campo, revisao)

    def test_regerar_recalcula_e_preserva_os_campos(self):
        antes = self._importar()["analise_sugerida"]
        r, dados = self._regerar(mudanca="mudou_captacao")
        self.assertNotEqual(dados["analise_sugerida"], antes)
        self.assertIn("A forma de captação mudou", dados["analise_sugerida"])
        # O textarea volta com o texto novo, e o select com o que foi marcado.
        html = r.content.decode()
        self.assertIn("A forma de captação mudou", html)
        self.assertIn('value="mudou_captacao" selected', html)

    def test_contexto_sobrevive_na_sessao_entre_regeracoes(self):
        self._importar()
        self._regerar(mudanca="mudou_captacao")
        _r, dados = self._regerar(mudanca="mudou_captacao",
                                  problema="problema_formulario",
                                  situacao="problema_corrigido")
        self.assertEqual(dados["_contexto"], {
            "mudanca": "mudou_captacao", "problema": "problema_formulario",
            "situacao": "problema_corrigido"})
        # E o GET seguinte volta com tudo preenchido.
        html = self.client.get("/revisao/").content.decode()
        self.assertIn('value="problema_formulario" selected', html)

    def test_regerar_nao_gera_pdf(self):
        self._importar()
        r, _dados = self._regerar(mudanca="nada_mudou")
        self.assertEqual(r["Content-Type"].split(";")[0], "text/html")

    def test_sem_contexto_a_analise_e_a_mesma_de_antes(self):
        original = self._importar()["analise_sugerida"]
        _r, dados = self._regerar()
        self.assertEqual(dados["analise_sugerida"], original)

    def test_meta_de_cpa_informada_vira_a_referencia(self):
        self._importar()
        _r, dados = self._regerar(meta_cpa="30,00")
        self.assertEqual(dados["_meta_cpa"], 30.0)
        av = dados["avaliacao"]
        self.assertEqual(av["referencia"], "meta")
        self.assertTrue(av["meta_definida"])
        # CPA 19,84 contra meta 30,00 = razão 0,66 (ótimo), mas 13 resultados
        # não sustentam afirmação forte: o rebaixamento por amostra vale igual.
        self.assertEqual(av["classificacao"], "BOM")
        self.assertIn("amostra_pequena", av["sinais"])
        self.assertNotIn("meta_cpa_indefinida", av["sinais"])
        self.assertIn("meta combinada", dados["analise_sugerida"])

    def test_situacao_sem_problema_e_descartada(self):
        self._importar()
        _r, dados = self._regerar(situacao="problema_corrigido")
        self.assertEqual(dados["_contexto"], {})
        self.assertNotIn("já foi corrigido", dados["analise_sugerida"])

    def test_passo_escolhido_pelo_operador(self):
        self._importar()
        _r, dados = self._regerar(passo="escalar_verba")
        self.assertEqual(dados["avaliacao"]["proximo_passo"], "escalar_verba")

    def test_pdf_sai_com_a_analise_regerada(self):
        self._importar()
        _r, dados = self._regerar(problema="problema_atendimento",
                                  situacao="problema_aberto")
        # O navegador reenvia o bloco de contexto junto: são os mesmos campos
        # da tela. Omiti-los aqui seria dizer que o operador os apagou — ver
        # ContextoNaoAplicadoTest.
        r = self.client.post("/revisao/", {
            "cliente": "Elix", "periodo": "31/07/2026 a 06/08/2026",
            "problema": "problema_atendimento", "situacao": "problema_aberto",
            "analise": dados["analise_sugerida"].replace("\n", "\r\n")})
        texto = _texto_pdf(_bytes_pdf(r))
        self.assertIn("atendimento aos contatos", texto)

    def test_consolidado_tambem_tem_o_bloco(self):
        arquivos = [
            _arquivo("a.xlsx", [{"nome": "CA", "res": 50, "inv": 100.0,
                                 "imp": 5000, "alc": 4000}]),
            _arquivo("b.xlsx", [{"nome": "CB", "res": 10, "inv": 200.0,
                                 "imp": 5000, "alc": 4000}]),
        ]
        self.client.post("/", {"cliente": "Grupo", "arquivos": arquivos})
        html = self.client.get("/revisao/").content.decode()
        self.assertIn("Contexto do período", html)
        # O select de passo traz as opções de GRUPO, não as de conta.
        self.assertIn("levar_o_metodo_das_melhores_as_demais", html)
        self.assertNotIn("escalar_verba", html)

        r = self.client.post("/revisao/", {
            "cliente": "Grupo", "periodo": "01/07/2026 a 15/07/2026",
            "analise": "x", "regerar": "1", "unidade_0": "Praça A",
            "unidade_1": "Praça B", "problema": "problema_estoque",
            "situacao": "problema_em_correcao"})
        self.assertEqual(r.status_code, 200)
        dados = self.client.session["relatorio_apex"]
        self.assertIn("A correção da disponibilidade de estoque está em andamento",
                      dados["analise_sugerida"])
        # Nomes das unidades preservados na regeração.
        self.assertIn("Praça A", r.content.decode())


class ContextoNaoAplicadoTest(TestCase):
    """
    Contexto e meta preenchidos com o operador clicando direto em *Gerar PDF*.

    O bloco só era aplicado pelo botão *Regerar análise*: quem preenchia a meta
    de custo por resultado e ia direto ao PDF recebia o relatório medido contra
    a faixa estimada do perfil, com o campo preenchido na tela e nada avisando.
    Agora o PDF é segurado até a análise refletir o que foi informado — ou até
    o operador dizer que é o texto dele que vale.
    """

    def _importar(self):
        f = _arquivo("e.xlsx", ContextoDoPeriodoTest.ELIX,
                     inicio="2026-07-31", fim="2026-08-06")
        self.client.post("/", {"cliente": "Elix", "arquivos": [f]})
        return self.client.session["relatorio_apex"]

    def _gerar(self, analise, **campos):
        """POST de *Gerar PDF* — sem `regerar`, como o botão do aside envia."""
        base = {"cliente": "Elix", "periodo": "31/07/2026 a 06/08/2026",
                "analise": analise.replace("\n", "\r\n")}
        base.update(campos)
        return self.client.post("/revisao/", base)

    def _sessao(self):
        return self.client.session["relatorio_apex"]

    def test_sem_contexto_o_pdf_sai_no_primeiro_clique(self):
        dados = self._importar()
        r = self._gerar(dados["analise_sugerida"])
        self.assertEqual(_paginas(_bytes_pdf(r)), 1)

    def test_meta_informada_segura_o_pdf_e_recalcula(self):
        antes = self._importar()["analise_sugerida"]
        r = self._gerar(antes, meta_cpa="30,00")

        # Voltou a tela, não o arquivo.
        self.assertEqual(r["Content-Type"].split(";")[0], "text/html")
        dados = self._sessao()
        self.assertEqual(dados["_meta_cpa"], 30.0)
        self.assertEqual(dados["avaliacao"]["referencia"], "meta")
        self.assertNotEqual(dados["analise_sugerida"], antes)
        # E o texto novo está à vista, com o aviso do que aconteceu.
        html = r.content.decode()
        self.assertIn("meta combinada", html)
        self.assertIn("acaba de ser recalculado", html)

    def test_segundo_clique_gera_o_pdf(self):
        self._importar()
        self._gerar(self._sessao()["analise_sugerida"], meta_cpa="30,00")
        r = self._gerar(self._sessao()["analise_sugerida"], meta_cpa="30,00")
        self.assertIn("meta combinada", _texto_pdf(_bytes_pdf(r)))

    def test_texto_editado_a_mao_nao_e_sobrescrito(self):
        original = self._importar()["analise_sugerida"]
        r = self._gerar("Texto que eu mesmo escrevi.", meta_cpa="30,00")

        self.assertEqual(r["Content-Type"].split(";")[0], "text/html")
        html = r.content.decode()
        self.assertIn("Texto que eu mesmo escrevi.", html)
        self.assertIn("gerar_assim_mesmo", html)
        # A análise do motor continua a de antes: a edição não virou sugestão,
        # e a meta ainda não foi aplicada.
        self.assertEqual(self._sessao()["analise_sugerida"], original)

    def test_gerar_assim_mesmo_sai_com_o_texto_do_operador(self):
        self._importar()
        r = self._gerar("Texto que eu mesmo escrevi.", meta_cpa="30,00",
                        gerar_assim_mesmo="1")
        self.assertIn("Texto que eu mesmo escrevi.", _texto_pdf(_bytes_pdf(r)))
        # A meta fica guardada mesmo sem ter sido aplicada: regerar depois não
        # obriga a digitar tudo de novo.
        self.assertEqual(self._sessao()["_meta_cpa"], 30.0)

    def test_contexto_apagado_tambem_segura_o_pdf(self):
        """Tirar a meta é mudança como qualquer outra — a análise ainda cita
        uma meta que o operador acabou de apagar."""
        self._importar()
        self.client.post("/revisao/", {
            "cliente": "Elix", "periodo": "31/07/2026 a 06/08/2026",
            "analise": "x", "regerar": "1", "meta_cpa": "30,00"})
        self.assertEqual(self._sessao()["_meta_cpa"], 30.0)

        r = self._gerar(self._sessao()["analise_sugerida"])
        self.assertEqual(r["Content-Type"].split(";")[0], "text/html")
        dados = self._sessao()
        self.assertIsNone(dados["_meta_cpa"])
        self.assertEqual(dados["avaliacao"]["referencia"], "perfil")

    def test_consolidado_segura_o_pdf_do_mesmo_jeito(self):
        arquivos = [
            _arquivo("a.xlsx", [{"nome": "CA", "res": 50, "inv": 100.0,
                                 "imp": 5000, "alc": 4000}]),
            _arquivo("b.xlsx", [{"nome": "CB", "res": 10, "inv": 200.0,
                                 "imp": 5000, "alc": 4000}]),
        ]
        self.client.post("/", {"cliente": "Grupo", "arquivos": arquivos})
        analise = self._sessao()["analise_sugerida"]

        r = self.client.post("/revisao/", {
            "cliente": "Grupo", "periodo": "01/07/2026 a 15/07/2026",
            "analise": analise.replace("\n", "\r\n"),
            "unidade_0": "Praça A", "unidade_1": "Praça B",
            "problema": "problema_estoque", "situacao": "problema_aberto"})

        self.assertEqual(r["Content-Type"].split(";")[0], "text/html")
        html = r.content.decode()
        self.assertIn("acaba de ser recalculado", html)
        # Os nomes das unidades sobrevivem à volta para a tela.
        self.assertIn("Praça A", html)
        self.assertIn("disponibilidade de estoque", self._sessao()["analise_sugerida"])


class ColunaDeInvestimentoTest(TestCase):
    """O Meta alterna o rótulo da coluna de verba entre exports. Não
    reconhecê-la zera investimento e custo por resultado sem avisar
    ninguém — o zero passa por número legítimo."""

    def _dados(self, rotulo):
        wb = Workbook()
        ws = wb.active
        ws.append([c if c != "Valor usado (BRL)" else rotulo
                   for c in CABECALHO])
        ws.append(["Campanha A", "active", 82, INDICADOR, 338.80, 35840,
                   10206, 500, "2026-07-30", "2026-08-05"])
        buf = io.BytesIO()
        wb.save(buf)
        return ler_export_meta(io.BytesIO(buf.getvalue()))

    def test_variantes_de_rotulo_da_coluna(self):
        for rotulo in ("Valor usado (BRL)", "Valor gasto (BRL)",
                       "Valor investido (BRL)", "Amount spent (BRL)"):
            with self.subTest(rotulo=rotulo):
                n = self._dados(rotulo)["_num"]
                self.assertAlmostEqual(n["investimento"], 338.80, places=2)
                self.assertAlmostEqual(n["custo_resultado"], 4.13, places=2)

    def test_coluna_desconhecida_nao_vira_periodo_otimo(self):
        # Sem a verba o CPA sai zero, e zero é mais barato que a faixa mais
        # barata de qualquer perfil. A análise tem que recusar a leitura.
        dados = self._dados("Verba aplicada")
        self.assertEqual(dados["_num"]["investimento"], 0.0)
        self.assertEqual(dados["avaliacao"]["classificacao"], "ATENCAO")
        self.assertEqual(dados["avaliacao"]["motivo_principal"],
                         "sem_investimento")
        self.assertIn("não trouxe o valor investido", dados["analise_sugerida"])


class BenchmarksTest(TestCase):
    """Classificação das métricas nas faixas de referência configuráveis."""

    def test_classificacao_basica(self):
        av = benchmarks.avaliar_metricas({
            "ctr": 1.0, "cpm": 30.0, "cpc": 4.0,
            "frequencia": 2.0, "taxa_conversao": 5.0,
        })
        self.assertEqual(av, {
            "ctr": benchmarks.ABAIXO, "cpm": benchmarks.DENTRO,
            "cpc": benchmarks.ACIMA, "frequencia": benchmarks.DENTRO,
            "taxa_conversao": benchmarks.DENTRO,
        })

    def test_taxa_conversao_acima_de_100_e_excelente(self):
        # Conversas podem originar de visualizações sem clique — não é anomalia
        av = benchmarks.avaliar_metricas({"taxa_conversao": 250.0})
        self.assertEqual(av["taxa_conversao"], benchmarks.EXCELENTE)

    def test_override_de_faixas_por_chamada(self):
        self.assertEqual(benchmarks.avaliar_metricas({"ctr": 1.5}),
                         {"ctr": benchmarks.ABAIXO})
        av = benchmarks.avaliar_metricas({"ctr": 1.5}, faixas={"ctr": (1.0, 3.0)})
        self.assertEqual(av, {"ctr": benchmarks.DENTRO})

    def test_faixa_de_frequencia_para_retargeting(self):
        self.assertEqual(benchmarks.avaliar_metricas({"frequencia": 4.0}),
                         {"frequencia": benchmarks.ACIMA})
        av = benchmarks.avaliar_metricas({"frequencia": 4.0}, retargeting=True)
        self.assertEqual(av, {"frequencia": benchmarks.DENTRO})

    def test_metricas_ausentes_ficam_fora(self):
        self.assertEqual(benchmarks.avaliar_metricas({"ctr": None}), {})


class AnaliseAutomaticaTest(TestCase):
    """
    Integração do motor de regras (`analysis/`) com o parser: a conta
    individual passa pela avaliação, o consolidado ainda usa o texto por
    composição. As regras em si têm testes próprios em analysis/tests/.
    """

    def test_status_nao_vaza_para_analise_nem_para_o_pdf(self):
        f = _arquivo("conta.xlsx", [
            {"nome": "Campanha A", "res": 40, "inv": 80.0, "imp": 4000,
             "alc": 2500, "cliques": 300, "status": "inactive"},
            {"nome": "Campanha B", "res": 0, "inv": 60.0, "imp": 2000,
             "alc": 1000, "status": "not_delivering"},
        ])
        r = self.client.post("/", {"cliente": "ILOC", "arquivos": [f]})
        self.assertEqual(r.status_code, 302)

        analise = self.client.session["relatorio_apex"]["analise_sugerida"]
        for termo in ("inactive", "not_delivering", "inativ", "fora do ar",
                      "Ads Manager", "bloqueio", "reprova"):
            self.assertNotIn(termo, analise)

        # PDF gerado com a análise sugerida: nada de status ou auditoria
        r = self.client.post("/revisao/", {
            "cliente": "ILOC", "periodo": "01/07/2026 a 15/07/2026",
            "analise": analise,
        })
        texto = _texto_pdf(_bytes_pdf(r))
        for termo in ("inactive", "not_delivering", "Status", "fora do ar",
                      "verificando"):
            self.assertNotIn(termo, texto)

    def test_a_analise_mais_longa_ainda_cabe_em_uma_pagina(self):
        # A análise saiu de dois parágrafos curtos para quatro blocos, e o
        # relatório individual é de UMA página fechada. Este teste pega o mais
        # longo dos textos que o motor sabe produzir e leva até o PDF.
        f = _arquivo("conta.xlsx", [
            {"nome": "Campanha A", "res": 40, "inv": 80.0, "imp": 4000,
             "alc": 2500, "cliques": 300},
            {"nome": "Campanha B", "res": 20, "inv": 120.0, "imp": 2000,
             "alc": 1000, "cliques": 120},
        ])
        self.client.post("/", {"cliente": "ILOC", "arquivos": [f]})

        metricas = {"investimento": 644.98, "alcance": 16279,
                    "impressoes": 57965, "frequencia": 3.56, "cpm": 11.13,
                    "resultados": 344, "cpa": 1.87, "ctr": 0.5,
                    "campanhas": [{"nome": "a", "resultados": 344}]}
        textos = []
        for cpa in (1.87, 6.0, 30.0):
            for meta in (None, 5.00):
                for frequencia in (1.1, 2.0, 3.0, 4.0):
                    for cpm in (11.13, 25.0, 80.0):
                        av = analysis.rules.avaliar(
                            dict(metricas, cpa=cpa, frequencia=frequencia,
                                 cpm=cpm), meta_cpa=meta)
                        textos.append(analysis.templates.redigir(av, metricas))
        maior = max(textos, key=len)

        r = self.client.post("/revisao/", {
            "cliente": "ILOC", "periodo": "01/07/2026 a 15/07/2026",
            "analise": maior,
        })
        pdf = _bytes_pdf(r)
        self.assertEqual(_paginas(pdf), 1,
                         "a análise mais longa estourou a página do relatório")
        # E o texto chegou inteiro: o último bloco é o que cairia fora.
        self.assertIn("Objetivo do próximo ciclo", _texto_pdf(pdf))

    def test_quebra_de_bloco_sobrevive_ao_textarea(self):
        # O navegador manda \r\n (HTML spec). Separar por "\n\n" cru não acha
        # separador nenhum e a análise inteira sai num parágrafo só — era
        # assim que o bug aparecia no PDF, com os rótulos vermelhos correndo
        # no meio do texto.
        f = _arquivo("conta.xlsx", [
            {"nome": "Campanha A", "res": 40, "inv": 80.0, "imp": 4000,
             "alc": 2500, "cliques": 300}])
        self.client.post("/", {"cliente": "ILOC", "arquivos": [f]})
        analise = self.client.session["relatorio_apex"]["analise_sugerida"]
        blocos = analise.split("\n\n")
        self.assertGreaterEqual(len(blocos), 3)

        r = self.client.post("/revisao/", {
            "cliente": "ILOC", "periodo": "01/07/2026 a 15/07/2026",
            "analise": analise.replace("\n", "\r\n"),
        })
        texto = _texto_pdf(_bytes_pdf(r))
        # Cada bloco começa num parágrafo próprio: o rótulo do último não pode
        # aparecer grudado no fim do penúltimo.
        for rotulo in ("Leitura do período.", "O que vamos fazer.",
                       "Objetivo do próximo ciclo."):
            self.assertIn(rotulo, texto)
        self.assertEqual(len(_paragrafos_analise(analise.replace("\n", "\r\n"))),
                         len(blocos))

    def test_linha_em_branco_com_espaco_ainda_separa(self):
        # Operador que edita o texto à mão deixa espaço na linha vazia.
        self.assertEqual(_paragrafos_analise("Um.\r\n   \r\nDois."),
                         ["Um.", "Dois."])
        self.assertEqual(_paragrafos_analise("Um.\n\nDois.\n\n\nTrês."),
                         ["Um.", "Dois.", "Três."])

    def test_analise_da_conta_vem_do_motor_de_regras(self):
        # 80/20 entre duas campanhas, CPA de R$ 2,60: período ótimo, e o
        # próximo passo sai da concentração de resultados.
        dados = _dados([
            {"nome": "Campanha A", "res": 80, "inv": 160.0, "imp": 8000,
             "alc": 5000, "cliques": 400},
            {"nome": "Campanha B", "res": 20, "inv": 100.0, "imp": 2000,
             "alc": 1500, "cliques": 100},
        ])
        av = dados["avaliacao"]
        self.assertEqual(av["classificacao"], "OTIMO")
        self.assertIn("resultados_concentrados", av["sinais"])
        self.assertEqual(av["proximo_passo"], "redistribuir_verba")
        self.assertIn("Redistribuir a verba entre as campanhas",
                      dados["analise_sugerida"])

    def test_analise_do_pdf_nao_repete_os_numeros_das_tabelas(self):
        dados = _dados([
            {"nome": "Campanha A", "res": 50, "inv": 100.0, "imp": 5000,
             "alc": 4000, "cliques": 300},
            {"nome": "Campanha B", "res": 50, "inv": 110.0, "imp": 5000,
             "alc": 4000, "cliques": 300},
        ])
        analise = dados["analise_sugerida"]
        self.assertNotRegex(analise, r"\d")
        self.assertNotIn("R$", analise)
        # Frequência 1,25 em 15 dias equivale a 2,5 no mês: patamar saudável.
        self.assertIn("frequencia_saudavel", dados["avaliacao"]["sinais"])

    def test_cpa_alto_classifica_em_atencao_e_pede_revisao(self):
        # CTR 1% (abaixo da faixa 2–5%) e CPA de R$ 60,00 com 5 resultados
        dados = _dados([{"nome": "C", "res": 5, "inv": 300.0, "imp": 10000,
                         "alc": 8000, "cliques": 100}])
        _valor, leitura = _linhas_funil(dados)["CTR (taxa de cliques)"]
        self.assertEqual(
            leitura, "Estamos renovando os criativos para elevar a taxa de cliques.")

        av = dados["avaliacao"]
        self.assertEqual(av["classificacao"], "ATENCAO")
        # Amostra pequena não promove nada: o rebaixamento só desce.
        self.assertIn("amostra_pequena", av["sinais"])
        self.assertEqual(av["motivo_principal"], "cpa_atencao")
        self.assertIn("Revisar para quem os anúncios estão sendo mostrados",
                      dados["analise_sugerida"])
        for termo in ("cansado", "não está prendendo", "Baixo"):
            self.assertNotIn(termo, leitura + dados["analise_sugerida"])

    def test_avaliacao_serializavel_acompanha_os_dados(self):
        # É ela, não o texto, que vira payload nas etapas seguintes.
        dados = _dados([{"nome": "C", "res": 344, "inv": 644.98, "imp": 57965,
                         "alc": 16279, "cliques": 900}])
        self.assertEqual(json.loads(json.dumps(dados["avaliacao"])),
                         dados["avaliacao"])
        self.assertEqual(dados["avaliacao"]["perfil"], "varejo_celular")
        self.assertFalse(dados["avaliacao"]["meta_definida"])

    def test_meta_de_cpa_substitui_a_faixa_do_perfil(self):
        registros, mapa = parser_xlsx.ler_registros(io.BytesIO(_planilha(
            [{"nome": "C", "res": 100, "inv": 800.0, "imp": 20000,
              "alc": 12000, "cliques": 500}])))
        # CPA de R$ 8,00: dentro da faixa de varejo_celular (teto 9,00)...
        self.assertEqual(
            parser_xlsx.consolidar(registros, mapa)["avaliacao"]["classificacao"],
            "BOM")
        # ...e acima de uma meta de R$ 5,00 (razão 1,60).
        self.assertEqual(
            parser_xlsx.consolidar(registros, mapa, meta_cpa=5.0)
            ["avaliacao"]["classificacao"], "ATENCAO")

    def test_periodo_curto_endurece_a_leitura_de_frequencia(self):
        # Frequência 1,4: no mês inteiro é público de sobra; na semana, o
        # mesmo número já significa que a audiência viu bastante.
        campanhas = [{"nome": "C", "res": 100, "inv": 200.0, "imp": 14000,
                      "alc": 10000, "cliques": 500}]
        mes = parser_xlsx.ler_export_meta(io.BytesIO(
            _planilha(campanhas, inicio="2026-07-01", fim="2026-07-30")))
        semana = parser_xlsx.ler_export_meta(io.BytesIO(
            _planilha(campanhas, inicio="2026-07-01", fim="2026-07-07")))
        self.assertIn("frequencia_baixa", mes["avaliacao"]["sinais"])
        self.assertIn("frequencia_saturada", semana["avaliacao"]["sinais"])

    def test_ajuste_de_frequencia_nao_tem_degrau_em_catorze_dias(self):
        # Já teve: 14 dias usava os limites cheios e 13 usava 13/30 deles, e
        # um dia a mais no export virava o veredito de frequência do avesso.
        campanhas = [{"nome": "C", "res": 100, "inv": 200.0, "imp": 25000,
                      "alc": 10000, "cliques": 500}]
        sinais = []
        for fim in ("2026-07-13", "2026-07-14", "2026-07-15"):
            dados = parser_xlsx.ler_export_meta(io.BytesIO(
                _planilha(campanhas, inicio="2026-07-01", fim=fim)))
            sinais.append([s for s in dados["avaliacao"]["sinais"]
                           if s.startswith("frequencia_")])
        self.assertEqual(sinais[0], sinais[1])
        self.assertEqual(sinais[1], sinais[2])

    def test_taxa_de_conversao_acima_de_100_e_excelente(self):
        # 250 conversas com 100 cliques: conversas vindas de visualizações
        dados = _dados([{"nome": "C", "res": 250, "inv": 300.0, "imp": 10000,
                         "alc": 8000, "cliques": 100}])
        _valor, leitura = _linhas_funil(dados)["Taxa de Conversão (clique → conversa)"]
        self.assertIn("Excelente eficiência", leitura)

    def test_consolidado_classifica_taxas_recalculadas(self):
        # CPM da unidade A sozinha = R$ 100 (acima); recalculado sobre os
        # totais do grupo = 250/15000*1000 = R$ 16,67 (abaixo da faixa)
        grupo = consolidar_grupo([
            {"nome": "A", "dados": _dados([{"nome": "CA", "res": 10, "inv": 100.0,
                                            "imp": 1000, "alc": 800, "cliques": 50}])},
            {"nome": "B", "dados": _dados([{"nome": "CB", "res": 10, "inv": 100.0,
                                            "imp": 9000, "alc": 7000, "cliques": 200}])},
            {"nome": "C", "dados": _dados([{"nome": "CC", "res": 5, "inv": 50.0,
                                            "imp": 5000, "alc": 4000, "cliques": 100}])},
        ])
        _valor, leitura = _linhas_funil(grupo)["CPM (custo por mil)"]
        self.assertIn("Custo de entrega competitivo", leitura)

        # As três unidades têm o mesmo CPA (R$ 10,00), igual ao do grupo:
        # nenhuma descolada, e o grupo inteiro acima da faixa do perfil.
        av = grupo["avaliacao"]
        self.assertAlmostEqual(av["cpa_grupo"], 10.0, places=2)
        self.assertEqual(av["grupo"]["classificacao"], "ATENCAO")
        self.assertIn("grupo_homogeneo", av["sinais"])
        self.assertEqual(av["proximo_passo"], "elevar_o_patamar_do_grupo")
        self.assertIn("todas no mesmo patamar", grupo["analise_sugerida"])

    def test_consolidado_mede_cada_unidade_contra_o_custo_do_grupo(self):
        # A gasta R$ 400 por 10 resultados (CPA 40); B e C, R$ 50 por 50
        # (CPA 1). CPA do grupo = 500/110 = R$ 4,55 — A fica 8,8x acima.
        grupo = consolidar_grupo([
            {"nome": "Cara", "dados": _dados([{"nome": "CA", "res": 10, "inv": 400.0,
                                               "imp": 9000, "alc": 6000, "cliques": 300}])},
            {"nome": "Barata", "dados": _dados([{"nome": "CB", "res": 50, "inv": 50.0,
                                                 "imp": 5000, "alc": 4000, "cliques": 200}])},
            {"nome": "Média", "dados": _dados([{"nome": "CC", "res": 50, "inv": 50.0,
                                                "imp": 5000, "alc": 4000, "cliques": 200}])},
        ])
        av = grupo["avaliacao"]
        por_nome = {u["nome"]: u for u in av["unidades"]}
        self.assertEqual(por_nome["Cara"]["avaliacao"]["classificacao"], "ATENCAO")
        self.assertEqual(por_nome["Barata"]["avaliacao"]["classificacao"], "OTIMO")
        # A referência de cada unidade é o grupo, não a faixa do perfil.
        self.assertEqual(por_nome["Cara"]["avaliacao"]["referencia"], "grupo")
        self.assertIn("comparada_ao_grupo", por_nome["Cara"]["avaliacao"]["sinais"])

        self.assertIn("unidades_acima_do_grupo", av["sinais"])
        self.assertIn("unidades_abaixo_do_grupo", av["sinais"])
        self.assertIn("dispersao_alta", av["sinais"])
        self.assertEqual(av["proximo_passo"],
                         "levar_o_metodo_das_melhores_as_demais")

        analise = grupo["analise_sugerida"]
        self.assertIn("Cara", analise)      # a praça mais cara é nomeada
        self.assertIn("Barata", analise)    # e a que tem o método a copiar
        self.assertNotIn("R$", analise)     # os números estão na tabela acima

    def test_analise_do_grupo_cabe_na_pagina_com_nomes_longos(self):
        # O bloco 2 do consolidado nomeia duas praças, e o nome vem do
        # operador. O consolidado também é de UMA página fechada.
        nomes = ["Tim %02d — Maxi Shopping Jundiaí Zona Norte" % i
                 for i in range(20)]
        arquivos = [_arquivo("u%d.xlsx" % i, [
            {"nome": "C", "res": 100 + i * 20, "inv": 100.0 + i * 90,
             "imp": 9000, "alc": 4000, "cliques": 400}]) for i in range(20)]
        self.client.post("/", {"cliente": "TIM Brasil", "arquivos": arquivos})
        analise = self.client.session["relatorio_apex"]["analise_sugerida"]
        # A praça mais cara e a mais barata são nomeadas pelo nome do arquivo
        # até o operador renomear; o texto tem que caber de qualquer forma.
        campos = {"cliente": "TIM Brasil", "periodo": "01/07/2026 a 15/07/2026",
                  "analise": analise}
        campos.update({"unidade_%d" % i: n for i, n in enumerate(nomes)})
        r = self.client.post("/revisao/", campos)
        pdf = _bytes_pdf(r)
        self.assertEqual(_paginas(pdf), 1,
                         "a análise do grupo estourou a página do consolidado")
        self.assertIn("Objetivo do próximo ciclo", _texto_pdf(pdf))

    def test_avaliacao_do_grupo_e_serializavel(self):
        grupo = consolidar_grupo([
            {"nome": "A", "dados": _dados([{"nome": "CA", "res": 40, "inv": 80.0,
                                            "imp": 4000, "alc": 3000, "cliques": 200}])},
            {"nome": "B", "dados": _dados([{"nome": "CB", "res": 40, "inv": 90.0,
                                            "imp": 4000, "alc": 3000, "cliques": 200}])},
        ])
        self.assertEqual(json.loads(json.dumps(grupo["avaliacao"])),
                         grupo["avaliacao"])


class ValidacaoUploadTest(TestCase):
    def test_limite_de_vinte_arquivos(self):
        arquivos = [
            _arquivo(f"conta_{i}.xlsx", [{"nome": "C", "res": 1, "inv": 10.0,
                                          "imp": 100, "alc": 80}])
            for i in range(21)
        ]
        r = self.client.post("/", {"cliente": "Grupo", "arquivos": arquivos})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Máximo de 20 arquivos")

    def test_extensao_invalida_aponta_arquivo(self):
        arquivos = [
            _arquivo("ok.xlsx", [{"nome": "C", "res": 1, "inv": 10.0,
                                  "imp": 100, "alc": 80}]),
            SimpleUploadedFile("notas.txt", b"nao e planilha", content_type="text/plain"),
        ]
        r = self.client.post("/", {"cliente": "Grupo", "arquivos": arquivos})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "notas.txt")

    def test_arquivo_corrompido_no_meio_do_lote_aponta_arquivo(self):
        ok = {"nome": "C", "res": 1, "inv": 10.0, "imp": 100, "alc": 80}
        arquivos = [
            _arquivo("a.xlsx", [ok]),
            SimpleUploadedFile("b.xlsx", b"bytes invalidos", content_type=XLSX_MIME),
            _arquivo("c.xlsx", [ok]),
        ]
        r = self.client.post("/", {"cliente": "Grupo", "arquivos": arquivos})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("b.xlsx", html)
        self.assertNotIn("relatorio_apex", self.client.session)


class NomeDoArquivoTest(TestCase):
    """Padrão único nos quatro modos:
    '[empresa]-[funcionalidade]-[início]-[fim].pdf'. O nome sozinho diz de
    quem é o relatório, que relatório é e de que período — na pasta de
    downloads, meses depois, é só isso que sobra."""

    CONTA = {"nome": "C", "res": 40, "inv": 80.0, "imp": 4000, "alc": 2500}

    def _anexos(self, quantos, **kw):
        return [_arquivo(f"u{i}.xlsx", [dict(self.CONTA)], **kw)
                for i in range(quantos)]

    def _nome(self, resposta):
        return resposta["Content-Disposition"].split('filename="')[1].rstrip('"')

    def test_anexo_unico(self):
        self.client.post("/", {"cliente": "TIM BRASIL",
                               "arquivos": self._anexos(1)})
        r = self.client.post("/revisao/", {"cliente": "TIM BRASIL",
                                           "periodo": "01/07/2026 a 31/07/2026",
                                           "analise": ""})
        self.assertEqual(self._nome(r),
                         "TIM-BRASIL-anexounico-1-jul-26-31-jul-26.pdf")

    def test_consolidado(self):
        self.client.post("/", {"cliente": "TIM BRASIL",
                               "arquivos": self._anexos(3)})
        r = self.client.post("/revisao/", {"cliente": "TIM BRASIL",
                                           "periodo": "01/07/2026 a 31/07/2026",
                                           "analise": ""})
        self.assertEqual(self._nome(r),
                         "TIM-BRASIL-consolidado-1-jul-26-31-jul-26.pdf")

    def test_listagem(self):
        self.client.post("/", {"modo": "listagem", "titulo": "TIM BRASIL",
                               "arquivos": self._anexos(3)})
        r = self.client.post("/revisao/", {"titulo": "TIM BRASIL",
                                           "inicio": "2026-07-01",
                                           "fim": "2026-07-31"})
        self.assertEqual(self._nome(r),
                         "TIM-BRASIL-listagem-1-jul-26-31-jul-26.pdf")

    def test_indicador_unico(self):
        self.client.post("/", {"modo": "indicador", "cliente": "TIM BRASIL",
                               "metrica": "investimento_total",
                               "arquivos": self._anexos(3, inicio="2026-07-01",
                                                        fim="2026-07-31")})
        r = self.client.post("/revisao/", {"cliente": "TIM BRASIL",
                                           "metrica": "investimento_total"})
        self.assertEqual(self._nome(r),
                         "TIM-BRASIL-indicadorunico-1-jul-26-31-jul-26.pdf")

    def test_sem_periodo_marca_a_data_de_geracao(self):
        """Uma data só, sem rótulo, seria lida como início de intervalo."""
        self.client.post("/", {"modo": "listagem", "titulo": "TIM BRASIL",
                               "arquivos": self._anexos(2)})
        r = self.client.post("/revisao/", {"titulo": "TIM BRASIL"})
        hoje = date.today()
        self.assertEqual(
            self._nome(r),
            f"TIM-BRASIL-listagem-gerado-{hoje.day}-"
            f"{_MESES_PT[hoje.month - 1]}-{hoje:%y}.pdf")

    def test_acento_e_pontuacao_viram_hifen(self):
        self.client.post("/", {"cliente": "Grupo São José & Cia",
                               "arquivos": self._anexos(1)})
        r = self.client.post("/revisao/", {"cliente": "Grupo São José & Cia",
                                           "periodo": "", "analise": ""})
        self.assertTrue(self._nome(r).startswith("Grupo-Sao-Jose-Cia-anexounico-"),
                        self._nome(r))


class IndicadorDeResultadoTest(TestCase):
    """O export traz o indicador cru da API ("actions:post_engagement") e uma
    conta pode misturar objetivos. Vale para os quatro modos: o rótulo do PDF
    é o do indicador de maior volume, sempre traduzido."""

    def _pdf_unico(self, campanhas):
        self.client.post("/", {"cliente": "ILOC",
                               "arquivos": [_arquivo("a.xlsx", campanhas)]})
        return _texto_pdf(_bytes_pdf(self.client.post("/revisao/", {
            "cliente": "ILOC", "periodo": "", "analise": ""})))

    def test_indicador_dominante_vence_a_primeira_linha(self):
        """Caso real: a campanha de engajamento abre a planilha, mas responde
        por menos de um terço dos resultados."""
        texto = self._pdf_unico([
            {"nome": "Engaja", "res": 120, "inv": 100.0, "imp": 5000, "alc": 4000,
             "indicador": "actions:post_engagement"},
            {"nome": "Mensagens", "res": 305, "inv": 200.0, "imp": 9000, "alc": 7000,
             "indicador": "actions:onsite_conversion."
                          "messaging_conversation_started_7d"},
        ])
        self.assertIn("Conversas Iniciadas", texto)
        self.assertNotIn("Envolvimento com a Publicação", texto)

    def test_nenhum_codigo_de_api_chega_ao_cliente(self):
        for cru, esperado in (
                ("actions:post_engagement", "Envolvimento com a Publicação"),
                ("actions:lead", "Leads"),
                ("actions:link_click", "Cliques no Link"),
                ("actions:landing_page_view", "Visualizações da Página"),
                ("video_thruplay_watched_actions", "Reproduções de Vídeo")):
            texto = self._pdf_unico([{"nome": "C", "res": 10, "inv": 50.0,
                                      "imp": 1000, "alc": 800, "indicador": cru}])
            self.assertIn(esperado, texto)
            self.assertNotIn("actions:", texto)
            self.assertNotIn("_actions", texto)

    def test_linha_sem_resultado_nao_vota_no_indicador(self):
        """Campanha que gastou sem converter entra nos totais, mas não decide
        o rótulo — senão bastaria uma campanha zerada para renomear o PDF."""
        texto = self._pdf_unico([
            {"nome": "Sem resultado", "res": None, "inv": 300.0, "imp": 9000,
             "alc": 7000, "indicador": "actions:lead"},
            {"nome": "Mensagens", "res": 12, "inv": 40.0, "imp": 1000, "alc": 800,
             "indicador": "actions:onsite_conversion."
                          "messaging_conversation_started_7d"},
        ])
        self.assertIn("Conversas Iniciadas", texto)
        self.assertNotIn("Leads", texto)

    def test_indicador_desconhecido_cai_no_cru_e_avisa_no_log(self):
        with self.assertLogs("relatorios.indicadores", level="WARNING") as log:
            texto = self._pdf_unico([{"nome": "C", "res": 10, "inv": 50.0,
                                      "imp": 1000, "alc": 800,
                                      "indicador": "actions:objetivo_novo"}])
        self.assertEqual(len(log.output), 1, "um aviso por conta, não um por seção")
        self.assertIn("actions:objetivo_novo", log.output[0])
        self.assertIn("conta: a", log.output[0])       # de qual anexo veio
        self.assertIn("actions:objetivo_novo", texto)  # gera assim mesmo

    def test_rotulo_do_export_por_extenso_nao_vira_alarme(self):
        """Export em pt-BR já traz linguagem de cliente; não é código de API."""
        with patch("relatorios.indicadores.logger") as log:
            texto = self._pdf_unico([{"nome": "C", "res": 10, "inv": 50.0,
                                      "imp": 1000, "alc": 800,
                                      "indicador": "Compras"}])
        log.warning.assert_not_called()
        self.assertIn("Compras", texto)

    def test_consolidado_usa_o_indicador_dominante_do_grupo(self):
        conversa = ("actions:onsite_conversion."
                    "messaging_conversation_started_7d")
        arquivos = [
            _arquivo("grande.xlsx", [{"nome": "C", "res": 100, "inv": 200.0,
                                      "imp": 9000, "alc": 7000}],
                     indicador=conversa),
            _arquivo("pequena.xlsx", [{"nome": "C", "res": 8, "inv": 30.0,
                                       "imp": 900, "alc": 700}],
                     indicador="actions:lead"),
        ]
        self.client.post("/", {"cliente": "Grupo", "arquivos": arquivos})
        html = self.client.get("/revisao/").content.decode()
        self.assertIn("Conversas Iniciadas", html)
        # O aviso de divergência continua, mas em linguagem de gente
        self.assertIn("não usam o mesmo indicador", html)
        self.assertIn("Leads", html)
        self.assertNotIn("actions:", html)


class FluxoListagemTest(TestCase):
    """Modo 3: tabela com 1 linha por conta, na ordem de envio, sem
    consolidação, sem análise e sem destaque de melhor conta. Como os demais
    modos, passa pela revisão antes de gerar o PDF."""

    CONTAS = [
        ("unidade_centro.xlsx", 40, 80.0, 4000, 2500, 300),
        ("unidade_norte.xlsx", 10, 55.5, 2000, 900, 100),
        ("unidade_sul.xlsx", 25, 100.0, 5000, 3000, 250),
    ]

    def _upload(self, titulo="", nomes=None):
        arquivos = [
            _arquivo(nome, [{"nome": "C", "res": res, "inv": inv,
                             "imp": imp, "alc": alc, "cliques": cli}])
            for nome, res, inv, imp, alc, cli in self.CONTAS
        ]
        post = {"modo": "listagem", "titulo": titulo, "arquivos": arquivos}
        if nomes:
            post["nome_conta"] = nomes
        return self.client.post("/", post)

    def _post_listagem(self, titulo="", nomes=None):
        """Fluxo completo: painel → revisão → PDF."""
        self._upload(titulo, nomes)
        return self.client.post("/revisao/", {"titulo": titulo})

    def test_upload_leva_a_revisao_antes_do_pdf(self):
        r = self._upload()
        self.assertRedirects(r, "/revisao/")
        # A revisão mostra a prévia da tabela que vai ao PDF
        html = self.client.get("/revisao/").content.decode()
        self.assertIn("Revisar listagem", html)
        self.assertIn("unidade centro", html)

    def test_gera_pdf_na_revisao(self):
        r = self._post_listagem()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("Relatorio-de-Listagem", r["Content-Disposition"])

    def test_nomes_editados_na_revisao_vao_para_o_pdf(self):
        self._upload()
        r = self.client.post("/revisao/", {
            "titulo": "", "unidade_0": "Loja Centro",
            "unidade_1": "Loja Norte", "unidade_2": "Loja Sul"})
        texto = _texto_pdf(_bytes_pdf(r))
        self.assertIn("Loja Centro", texto)
        self.assertNotIn("unidade centro", texto)

    def test_titulo_padrao_e_customizado(self):
        texto = _texto_pdf(_bytes_pdf(self._post_listagem()))
        self.assertIn("Relatório de Listagem", texto)

        r = self._post_listagem(titulo="Visão Geral — Franquias")
        texto = _texto_pdf(_bytes_pdf(r))
        self.assertIn("Visão Geral — Franquias", texto)
        self.assertIn("Visao-Geral-Franquias", r["Content-Disposition"])

    def test_linhas_ranqueadas_por_resultados(self):
        texto = _texto_pdf(_bytes_pdf(self._post_listagem()))
        # Enviadas como centro (40) → norte (10) → sul (25); o ranking
        # reordena para centro → sul → norte, independente da ordem de envio.
        pos = [texto.index(nome) for nome in
               ("unidade centro", "unidade sul", "unidade norte")]
        self.assertEqual(pos, sorted(pos))

    def test_empate_em_resultados_desempata_por_investimento(self):
        """Duas gerações da mesma base têm de produzir o mesmo PDF: sem
        desempate explícito, contas de igual volume trocariam de posição."""
        arquivos = [
            _arquivo("magra.xlsx", [{"nome": "C", "res": 30, "inv": 40.0,
                                     "imp": 2000, "alc": 1500}]),
            _arquivo("gorda.xlsx", [{"nome": "C", "res": 30, "inv": 90.0,
                                     "imp": 3000, "alc": 2000}]),
        ]
        self.client.post("/", {"modo": "listagem", "arquivos": arquivos})
        texto = _texto_pdf(_bytes_pdf(self.client.post("/revisao/", {})))
        self.assertLess(texto.index("gorda"), texto.index("magra"))

    def test_valores_por_conta_em_pt_br_sem_consolidar(self):
        texto = _texto_pdf(_bytes_pdf(self._post_listagem()))
        self.assertIn("R$ 80,00", texto)      # investimento da 1ª conta
        self.assertIn("R$ 2,00", texto)       # custo/resultado: 80 / 40
        self.assertIn("R$ 5,55", texto)       # custo/resultado: 55,50 / 10
        self.assertIn("R$ 20,00", texto)      # CPM: 80 / 4000 * 1000
        self.assertIn("2.500", texto)         # alcance pt-BR da 1ª conta
        self.assertIn("Conversas Iniciadas", texto)   # label do resultado
        # Sem consolidação nem análise
        self.assertNotIn("R$ 235,50", texto)  # soma dos investimentos
        self.assertNotIn("Análise", texto)

    def test_ordem_das_colunas(self):
        """O tipo de resultado vem colado ao número dele, e a posição abre a
        linha — ler "Conversas Iniciadas / 40" seguido não exige varrer a
        tabela até a coluna certa."""
        texto = _texto_pdf(_bytes_pdf(self._post_listagem()))
        colunas = ["#", "Conta", "Resultado", "Nº Resultados",
                   "Investimento (R$)", "Custo/Resultado (R$)", "Alcance",
                   "Impressões", "CPM (R$)"]
        pos = [texto.index(c) for c in colunas]
        self.assertEqual(pos, sorted(pos), f"cabeçalho fora de ordem: {texto[:200]}")

    def test_sem_ctr_e_com_cpm(self):
        """O export de Campanhas não traz cliques: a coluna de CTR renderizava
        "—" em toda linha. Trocada por CPM, que sai dos totais já lidos."""
        texto = _texto_pdf(_bytes_pdf(self._post_listagem()))
        self.assertNotIn("CTR", texto)
        self.assertIn("CPM (R$)", texto)
        for cpm in ("R$ 20,00", "R$ 27,75"):   # centro/sul e norte
            self.assertIn(cpm, texto)

    def test_coluna_de_posicao_numera_o_ranking(self):
        texto = _texto_pdf(_bytes_pdf(self._post_listagem()))
        for posicao, nome in enumerate(
                ("unidade centro", "unidade sul", "unidade norte"), start=1):
            self.assertRegex(texto, rf"{posicao} {nome}")

    def test_conta_sem_impressoes_nao_estoura_no_cpm(self):
        arquivos = [_arquivo("sem_dados.xlsx",
                             [{"nome": "C", "res": 0, "inv": 12.0}]),
                    _arquivo("com_dados.xlsx",
                             [{"nome": "C", "res": 4, "inv": 20.0, "imp": 1000}])]
        self.client.post("/", {"modo": "listagem", "arquivos": arquivos})
        texto = _texto_pdf(_bytes_pdf(self.client.post("/revisao/", {})))
        self.assertIn("R$ 20,00", texto)   # CPM da conta com impressões
        self.assertIn("—", texto)          # CPM e custo/resultado da outra

    def _upload_periodos(self):
        """Três anexos com janelas diferentes — o período do relatório é a
        união delas: 01/07 (menor início) a 31/07 (maior fim)."""
        arquivos = [
            _arquivo("centro.xlsx", [{"nome": "C", "res": 40, "inv": 80.0}],
                     inicio="2026-07-05", fim="2026-07-20"),
            _arquivo("norte.xlsx", [{"nome": "C", "res": 10, "inv": 55.5}],
                     inicio="2026-07-01", fim="2026-07-18"),
            _arquivo("sul.xlsx", [{"nome": "C", "res": 25, "inv": 100.0}],
                     inicio="2026-07-10", fim="2026-07-31"),
        ]
        return self.client.post("/", {"modo": "listagem", "arquivos": arquivos})

    def test_periodo_sugerido_a_partir_dos_anexos(self):
        self._upload_periodos()
        html = self.client.get("/revisao/").content.decode()
        # ISO no value: é o formato que o input nativo de data entende
        self.assertIn('value="2026-07-01"', html)
        self.assertIn('value="2026-07-31"', html)

    def test_periodo_editado_vai_para_o_cabecalho_do_pdf(self):
        self._upload_periodos()
        r = self.client.post("/revisao/", {"titulo": "", "inicio": "2026-07-01",
                                           "fim": "2026-07-31"})
        self.assertIn("01/07/2026 — 31/07/2026", _texto_pdf(_bytes_pdf(r)))

    def test_periodo_em_branco_omite_o_bloco(self):
        self._upload_periodos()
        texto = _texto_pdf(_bytes_pdf(self.client.post("/revisao/", {})))
        self.assertNotRegex(texto, r"\d{2}/\d{2}/\d{4} — \d{2}/\d{2}/\d{4}")

    def test_meia_data_e_periodo_invertido_sao_recusados(self):
        for post in ({"inicio": "2026-07-01"},                       # sem fim
                     {"fim": "2026-07-31"},                          # sem início
                     {"inicio": "2026-07-31", "fim": "2026-07-01"}):  # invertido
            self._upload_periodos()
            r = self.client.post("/revisao/", post)
            self.assertEqual(r.status_code, 200)
            self.assertNotEqual(r["Content-Type"], "application/pdf")

    def test_modo_unico_exige_exatamente_um_arquivo(self):
        ok = {"nome": "C", "res": 1, "inv": 10.0, "imp": 100, "alc": 80}
        r = self.client.post("/", {
            "modo": "unico", "cliente": "ILOC",
            "arquivos": [_arquivo("a.xlsx", [ok]), _arquivo("b.xlsx", [ok])],
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "exatamente 1 arquivo")

    def test_modo_consolidado_exige_dois_ou_mais(self):
        ok = {"nome": "C", "res": 1, "inv": 10.0, "imp": 100, "alc": 80}
        r = self.client.post("/", {
            "modo": "consolidado", "cliente": "Grupo",
            "arquivos": [_arquivo("a.xlsx", [ok])],
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "pelo menos 2 arquivos")

    def test_modos_1_e_2_exigem_cliente(self):
        ok = {"nome": "C", "res": 1, "inv": 10.0, "imp": 100, "alc": 80}
        r = self.client.post("/", {
            "modo": "unico", "arquivos": [_arquivo("a.xlsx", [ok])]})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Informe o cliente")


# ----------------------------------------------------------------------
# Modo 4 — Indicador Único
# ----------------------------------------------------------------------
CABECALHO_SEM_CLIQUES = [c for c in CABECALHO if c != "Cliques no link"]


def _arquivo_sem_cliques(nome, campanhas, inicio="2026-07-01", fim="2026-07-15"):
    """Export em que a coluna de cliques não existe — usado para o caso de
    métrica indisponível numa das contas."""
    wb = Workbook()
    ws = wb.active
    ws.append(CABECALHO_SEM_CLIQUES)
    for c in campanhas:
        ws.append([c["nome"], "active", c.get("res"), INDICADOR, c.get("inv"),
                   c.get("imp"), c.get("alc"), inicio, fim])
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(nome, buf.getvalue(), content_type=XLSX_MIME)


# centro: CPA 2,00 · CTR 7,50%  |  norte: CPA 5,55 · CTR 5,00%
# sul:    CPA 4,00 · CTR 5,00%
# Totais: investimento 235,50 · resultados 75 · impressões 11.000 · cliques 650
CONTAS_INDICADOR = [
    ("unidade_centro.xlsx", 40, 80.0, 4000, 2500, 300),
    ("unidade_norte.xlsx", 10, 55.5, 2000, 900, 100),
    ("unidade_sul.xlsx", 25, 100.0, 5000, 3000, 250),
]


class FluxoIndicadorTest(TestCase):
    """Modo 4: PDF direto comparando UMA métrica entre contas — ordenado pela
    direção de `melhor` no registro, com total agregado conforme a regra da
    métrica (soma × recálculo sobre os brutos)."""

    def _upload(self, metrica, cliente="TIM Brasil", arquivos=None, nomes=None):
        if arquivos is None:
            arquivos = [
                _arquivo(nome, [{"nome": "C", "res": res, "inv": inv,
                                 "imp": imp, "alc": alc, "cliques": cli}])
                for nome, res, inv, imp, alc, cli in CONTAS_INDICADOR
            ]
        post = {"modo": "indicador", "cliente": cliente,
                "metrica": metrica, "arquivos": arquivos}
        if nomes:
            post["nome_conta"] = nomes
        return self.client.post("/", post)

    def _post(self, metrica, cliente="TIM Brasil", arquivos=None, **extra):
        """Fluxo completo: painel → revisão → PDF."""
        self._upload(metrica, cliente, arquivos)
        return self.client.post("/revisao/",
                                {"cliente": cliente, "metrica": metrica, **extra})

    def _texto(self, metrica, **kw):
        return _texto_pdf(_bytes_pdf(self._post(metrica, **kw)))

    def test_upload_leva_a_revisao_com_previa(self):
        r = self._upload("conversas_iniciadas")
        self.assertRedirects(r, "/revisao/")
        html = self.client.get("/revisao/").content.decode()
        self.assertIn("Revisar indicador", html)
        self.assertIn("75", html)          # total já calculado na prévia

    def test_gera_pdf_na_revisao(self):
        r = self._post("conversas_iniciadas")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn('filename="TIM-Brasil-indicadorunico-1-jul-26-15-jul-26.pdf"',
                      r["Content-Disposition"])

    def test_trocar_metrica_na_revisao_nao_exige_reenviar_anexos(self):
        self._upload("conversas_iniciadas")
        r = self.client.post("/revisao/", {"cliente": "TIM", "metrica": "cpa"})
        texto = _texto_pdf(_bytes_pdf(r))
        self.assertIn("R$ 3,14", texto)    # CPA geral recalculado
        self.assertIn("Custo por Resultado", texto)

    def test_cookie_sinaliza_download_quando_ha_token(self):
        # O front manda um token; o PDF volta com esse token num cookie, sinal
        # de que o arquivo saiu — é o que fecha a etapa 02 na tela.
        self._upload("cpa")
        r = self.client.post("/revisao/", {"cliente": "TIM", "metrica": "cpa",
                                           "download_token": "abc123"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.cookies["apex_download"].value, "abc123")

    def test_sem_token_nao_ha_cookie(self):
        r = self._post("cpa")
        self.assertNotIn("apex_download", r.cookies)

    def test_nome_digitado_no_painel_substitui_o_nome_do_arquivo(self):
        # Cada anexo carrega o nome da conta digitado no painel; é ele que vai
        # ao PDF, não o "unidade_centro" derivado do arquivo.
        self._upload("conversas_iniciadas",
                     nomes=["Loja Centro", "Loja Norte", "Loja Sul"])
        r = self.client.post("/revisao/",
                             {"cliente": "TIM", "metrica": "conversas_iniciadas"})
        texto = _texto_pdf(_bytes_pdf(r))
        self.assertIn("Loja Centro", texto)
        self.assertNotIn("unidade centro", texto)

    def test_nome_em_branco_cai_no_nome_do_arquivo(self):
        # Campo vazio → mantém o comportamento antigo (nome derivado do arquivo).
        self._upload("conversas_iniciadas", nomes=["", "Loja Norte", ""])
        r = self.client.post("/revisao/",
                             {"cliente": "TIM", "metrica": "conversas_iniciadas"})
        texto = _texto_pdf(_bytes_pdf(r))
        self.assertIn("unidade centro", texto)   # fallback do arquivo
        self.assertIn("Loja Norte", texto)       # digitado

    def test_nome_editado_na_revisao_vence_o_do_painel(self):
        self._upload("conversas_iniciadas", nomes=["Loja Centro", "N", "S"])
        r = self.client.post("/revisao/", {
            "cliente": "TIM", "metrica": "conversas_iniciadas",
            "unidade_0": "Centro Revisado", "unidade_1": "N", "unidade_2": "S"})
        texto = _texto_pdf(_bytes_pdf(r))
        self.assertIn("Centro Revisado", texto)
        self.assertNotIn("Loja Centro", texto)

    def test_metrica_aditiva_soma_e_mostra_share(self):
        texto = self._texto("conversas_iniciadas")
        self.assertIn("Conversas Iniciadas", texto)
        self.assertIn("75", texto)          # total = 40 + 10 + 25
        self.assertIn("53,3%", texto)       # share de centro
        self.assertIn("13,3%", texto)       # share de norte

    def test_metrica_de_taxa_recalcula_total_e_omite_share(self):
        texto = self._texto("cpa")
        # CPA geral = 235,50 / 75 = 3,14 — e NÃO a média das CPAs (3,85)
        self.assertIn("R$ 3,14", texto)
        self.assertNotIn("R$ 3,85", texto)
        self.assertIn("não é a média dos valores individuais", texto)
        self.assertNotIn("% do total", texto)

    def test_ctr_geral_recalculado_sobre_os_brutos(self):
        texto = self._texto("ctr")
        self.assertIn("5,91%", texto)       # 650 / 11.000
        self.assertNotIn("5,83%", texto)    # média dos CTRs das contas

    def test_ordem_segue_a_direcao_de_melhor(self):
        # conversas → "maior" é melhor: centro (40) · sul (25) · norte (10)
        texto = self._texto("conversas_iniciadas")
        pos = [texto.index(n) for n in ("unidade centro", "unidade sul", "unidade norte")]
        self.assertEqual(pos, sorted(pos))

        # CPA → "menor" é melhor: centro (2,00) · sul (4,00) · norte (5,55)
        texto = self._texto("cpa")
        pos = [texto.index(n) for n in ("unidade centro", "unidade sul", "unidade norte")]
        self.assertEqual(pos, sorted(pos))

    def test_metrica_sem_ranking_mantem_ordem_de_envio(self):
        # investimento_total tem melhor=None → ordem dos anexos, não por valor
        texto = self._texto("investimento_total")
        pos = [texto.index(n) for n in ("unidade centro", "unidade norte", "unidade sul")]
        self.assertEqual(pos, sorted(pos))

    def test_nome_da_unidade_igual_ao_modo_listagem(self):
        # Mesma origem (nome do arquivo, via views._nome_unidade) nos dois modos
        indicador = self._texto("conversas_iniciadas")
        arquivos = [
            _arquivo(nome, [{"nome": "C", "res": res, "inv": inv,
                             "imp": imp, "alc": alc, "cliques": cli}])
            for nome, res, inv, imp, alc, cli in CONTAS_INDICADOR
        ]
        self.client.post("/", {"modo": "listagem", "arquivos": arquivos})
        listagem = _texto_pdf(_bytes_pdf(self.client.post("/revisao/", {})))
        for nome in ("unidade centro", "unidade norte", "unidade sul"):
            self.assertIn(nome, indicador)
            self.assertIn(nome, listagem)

    def test_conta_sem_a_coluna_fica_fora_do_total(self):
        arquivos = [
            _arquivo("centro.xlsx", [{"nome": "C", "res": 40, "inv": 80.0,
                                      "imp": 4000, "alc": 2500, "cliques": 300}]),
            _arquivo_sem_cliques("norte.xlsx", [{"nome": "C", "res": 10,
                                                 "inv": 55.5, "imp": 2000,
                                                 "alc": 900}]),
        ]
        texto = self._texto("ctr", arquivos=arquivos)
        self.assertIn("Dado indisponível no export de: norte", texto)
        # CTR geral = 300 / 4.000 — a conta sem cliques não entra na conta
        self.assertIn("7,50%", texto)
        self.assertNotIn("6,67%", texto)   # 300 / 6.000, se norte entrasse

    def test_periodo_em_hifen(self):
        texto = self._texto("conversas_iniciadas")
        self.assertIn("01-07 a 15-07", texto)
        self.assertNotIn("01/07/2026", texto)

    def test_aviso_de_objetivo_divergente_so_em_metrica_sensivel(self):
        # Cada POST consome os uploads: os anexos são remontados a cada chamada
        def anexos():
            return [
                _arquivo("centro.xlsx", [{"nome": "C", "res": 40, "inv": 80.0,
                                          "imp": 4000, "alc": 2500, "cliques": 300}]),
                _arquivo("norte.xlsx", [{"nome": "C", "res": 10, "inv": 55.5,
                                         "imp": 2000, "alc": 900, "cliques": 100}],
                         indicador="Cliques no link"),
            ]

        self.assertIn("objetivos diferentes", self._texto("cpa", arquivos=anexos()))
        # Métrica de topo não depende do objetivo → sem aviso
        self.assertNotIn("objetivos diferentes",
                         self._texto("impressoes", arquivos=anexos()))

    def test_exige_dois_arquivos_e_metrica(self):
        ok = {"nome": "C", "res": 1, "inv": 10.0, "imp": 100, "alc": 80}
        r = self.client.post("/", {"modo": "indicador", "cliente": "G",
                                   "metrica": "cpa",
                                   "arquivos": [_arquivo("a.xlsx", [ok])]})
        self.assertContains(r, "pelo menos 2 arquivos")

        r = self.client.post("/", {
            "modo": "indicador", "cliente": "G",
            "arquivos": [_arquivo("a.xlsx", [ok]), _arquivo("b.xlsx", [ok])]})
        self.assertContains(r, "Escolha a métrica")

    def test_seletor_agrupado_por_estagio_no_painel(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Topo de Funil", html)
        self.assertIn("Meio de Funil", html)
        self.assertIn("Fundo de Funil", html)
        self.assertIn('value="taxa_conversao"', html)


class RegistroMetricasTest(TestCase):
    """O registro é a fonte única: acrescentar uma métrica não toca view,
    template nem regra de agregação."""

    def test_agregacao_de_taxa_nunca_e_media_das_medias(self):
        # 2 contas de volumes muito diferentes: a média das CPAs (5,50) fica
        # longe do CPA real do grupo (100 / 55 = 1,82)
        nums = [{"investimento": 20.0, "resultados": 50.0},
                {"investimento": 80.0, "resultados": 5.0}]
        self.assertAlmostEqual(metricas.total_geral("cpa", nums), 100 / 55)

    def test_soma_e_direta_para_metrica_aditiva(self):
        nums = [{"investimento": 20.0}, {"investimento": 80.0}]
        self.assertEqual(metricas.total_geral("investimento_total", nums), 100.0)

    def test_denominador_zero_vira_indisponivel(self):
        nums = [{"investimento": 20.0, "resultados": 0.0}]
        self.assertIsNone(metricas.total_geral("cpa", nums))
        self.assertEqual(metricas.formatar("cpa", None), "—")

    def test_metrica_nova_so_com_uma_entrada_no_registro(self):
        nova = dict(metricas.METRICS_REGISTRY)
        nova["custo_por_mil_alcancados"] = {
            "label": "Custo por Mil Alcançados", "unidade": "R$",
            "estagio": "topo", "agregacao": "recalculo",
            "formula": "investimento_total / alcance * 1000",
            "melhor": "menor", "fonte": None,
        }
        with patch.object(metricas, "METRICS_REGISTRY", nova):
            # 1) aparece no seletor, no grupo certo
            topo = dict(metricas.opcoes_agrupadas())["Topo de Funil — Atração"]
            self.assertIn(("custo_por_mil_alcancados", "Custo por Mil Alcançados"),
                          topo)
            # 2) agrega sozinha: 235,50 / 6.400 * 1000 = 36,80
            nums = [{"investimento": 80.0, "alcance": 2500.0},
                    {"investimento": 55.5, "alcance": 900.0},
                    {"investimento": 100.0, "alcance": 3000.0}]
            self.assertAlmostEqual(
                metricas.total_geral("custo_por_mil_alcancados", nums),
                235.5 / 6400 * 1000)
            # 3) gera o PDF sem nenhuma alteração em view/template/agregação
            arquivos = [
                _arquivo(nome, [{"nome": "C", "res": res, "inv": inv,
                                 "imp": imp, "alc": alc, "cliques": cli}])
                for nome, res, inv, imp, alc, cli in CONTAS_INDICADOR
            ]
            self.client.post("/", {
                "modo": "indicador", "cliente": "TIM",
                "metrica": "custo_por_mil_alcancados", "arquivos": arquivos})
            r = self.client.post("/revisao/", {
                "cliente": "TIM", "metrica": "custo_por_mil_alcancados"})
            self.assertEqual(r["Content-Type"], "application/pdf")
            texto = _texto_pdf(_bytes_pdf(r))
            self.assertIn("Custo por Mil Alcançados", texto)
            self.assertIn("R$ 36,80", texto)



class VeiculacaoTest(TestCase):
    """Filtro pela coluna "Veiculação da campanha" do export (active/inactive)
    no modo Indicador Único: recorta as linhas ANTES de qualquer soma, então
    todos os números do PDF — inclusive os recalculados — saem do recorte."""

    # Por conta: uma campanha ativa + uma inativa, com resultados distintos
    CONTAS = [
        ("centro.xlsx", [
            {"nome": "Ativa", "status": "active", "res": 30, "inv": 60.0,
             "imp": 3000, "alc": 2000, "cliques": 200},
            {"nome": "Parada", "status": "inactive", "res": 10, "inv": 20.0,
             "imp": 1000, "alc": 500, "cliques": 100},
        ]),
        ("norte.xlsx", [
            {"nome": "Ativa", "status": "active", "res": 20, "inv": 40.0,
             "imp": 2000, "alc": 1500, "cliques": 150},
            {"nome": "Parada", "status": "inactive", "res": 5, "inv": 15.5,
             "imp": 500, "alc": 300, "cliques": 50},
        ]),
    ]

    def _pdf(self, veiculacao, metrica="conversas_iniciadas", contas=None):
        arquivos = [_arquivo(nome, campanhas)
                    for nome, campanhas in (contas or self.CONTAS)]
        self.client.post("/", {"modo": "indicador", "cliente": "TIM",
                               "metrica": metrica, "veiculacao": veiculacao,
                               "arquivos": arquivos})
        r = self.client.post("/revisao/", {"cliente": "TIM", "metrica": metrica,
                                           "veiculacao": veiculacao})
        return _texto_pdf(_bytes_pdf(r))

    # ---- classificação do status ------------------------------------
    def test_inactive_nao_e_confundido_com_active(self):
        # "inactive" contém "active": a ordem de teste no parser importa
        self.assertIs(parser_xlsx.campanha_ativa("active"), True)
        self.assertIs(parser_xlsx.campanha_ativa("inactive"), False)
        self.assertIs(parser_xlsx.campanha_ativa("Inactive"), False)
        self.assertIs(parser_xlsx.campanha_ativa("campaign_paused"), False)
        self.assertIs(parser_xlsx.campanha_ativa("Ativa"), True)
        self.assertIs(parser_xlsx.campanha_ativa("Inativa"), False)
        # Sem status ou status desconhecido: não afirma nada
        self.assertIsNone(parser_xlsx.campanha_ativa(""))
        self.assertIsNone(parser_xlsx.campanha_ativa(None))
        self.assertIsNone(parser_xlsx.campanha_ativa("em analise"))

    # ---- o recorte muda os totais -----------------------------------
    def test_todas_soma_ativas_e_inativas(self):
        texto = self._pdf("todas")
        self.assertIn("65", texto)          # 30 + 10 + 20 + 5

    def test_somente_ativas(self):
        texto = self._pdf("ativas")
        self.assertIn("50", texto)          # 30 + 20
        self.assertIn("somente campanhas ativas", texto)

    def test_somente_inativas(self):
        texto = self._pdf("inativas")
        self.assertIn("15", texto)          # 10 + 5
        self.assertIn("somente campanhas inativas", texto)

    def test_metrica_de_razao_recalculada_dentro_do_recorte(self):
        # CPA das ativas = (60 + 40) / (30 + 20) = 2,00 — e não os 2,08 do total
        texto = self._pdf("ativas", metrica="cpa")
        self.assertIn("R$ 2,00", texto)
        self.assertNotIn("R$ 2,08", texto)

    def test_recorte_declarado_no_pdf(self):
        texto = self._pdf("ativas")
        self.assertIn("Campanhas fora do recorte não entram", texto)
        # No recorte padrão não há nota nenhuma sobre veiculação
        self.assertNotIn("Campanhas fora do recorte", self._pdf("todas"))

    # ---- casos de borda ---------------------------------------------
    def test_conta_sem_campanhas_no_recorte_fica_fora_do_total(self):
        contas = list(self.CONTAS) + [
            ("sul.xlsx", [{"nome": "Parada", "status": "inactive", "res": 99,
                           "inv": 500.0, "imp": 9000, "alc": 8000,
                           "cliques": 900}]),
        ]
        texto = self._pdf("ativas", contas=contas)
        self.assertIn("Sem campanhas no recorte em: sul", texto)
        self.assertIn("50", texto)          # total segue 30 + 20
        self.assertNotIn("149", texto)      # a conta sem ativas não entrou

    def test_export_sem_a_coluna_entra_com_tudo_e_e_sinalizado(self):
        sem_coluna = SimpleUploadedFile(
            "legado.xlsx",
            _planilha_sem_veiculacao([{"nome": "C", "res": 7, "inv": 14.0,
                                       "imp": 700, "alc": 600, "cliques": 70}]),
            content_type=XLSX_MIME)
        arquivos = [_arquivo(n, c) for n, c in self.CONTAS] + [sem_coluna]
        self.client.post("/", {"modo": "indicador", "cliente": "TIM",
                               "metrica": "conversas_iniciadas",
                               "veiculacao": "ativas", "arquivos": arquivos})
        r = self.client.post("/revisao/", {"cliente": "TIM", "veiculacao": "ativas",
                                           "metrica": "conversas_iniciadas"})
        texto = _texto_pdf(_bytes_pdf(r))
        self.assertIn("não traz a coluna de veiculação", texto)
        self.assertIn("57", texto)          # 30 + 20 + 7 (a legado entra inteira)

    def test_trocar_o_recorte_na_revisao_nao_exige_reenviar_anexos(self):
        arquivos = [_arquivo(n, c) for n, c in self.CONTAS]
        self.client.post("/", {"modo": "indicador", "cliente": "TIM",
                               "metrica": "conversas_iniciadas",
                               "veiculacao": "todas", "arquivos": arquivos})
        r = self.client.post("/revisao/", {"cliente": "TIM", "veiculacao": "inativas",
                                           "metrica": "conversas_iniciadas"})
        self.assertIn("15", _texto_pdf(_bytes_pdf(r)))

    def test_outros_modos_ignoram_o_filtro(self):
        # Listagem não expõe o campo: segue com todas as campanhas
        arquivos = [_arquivo(n, c) for n, c in self.CONTAS]
        self.client.post("/", {"modo": "listagem", "veiculacao": "ativas",
                               "arquivos": arquivos})
        texto = _texto_pdf(_bytes_pdf(self.client.post("/revisao/", {})))
        self.assertIn("R$ 80,00", texto)    # centro inteira: 60 + 20
