# -*- coding: utf-8 -*-
"""
Testes do fluxo web (upload → revisão → PDF), cobrindo o modo individual
(1 anexo) e o consolidado (2 a 20 anexos) no layout dark de UMA página
(WeasyPrint). A contagem de páginas usa `pdfinfo` quando disponível e
PyMuPDF como fallback.
"""
import io
import shutil
import subprocess
import tempfile
from unittest.mock import patch

import fitz  # PyMuPDF — extração de texto e contagem de páginas
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from . import benchmarks, metricas, parser_xlsx
from .parser_xlsx import consolidar_grupo, ler_export_meta

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
        self.assertIn(
            'filename="ILOC-Campanhas-1-de-jul-de-2026-15-de-jul-de-2026.pdf"',
            r["Content-Disposition"],
        )
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
    """Texto sugerido: só números e continuidade — nunca status de campanha."""

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

    def test_campanha_dominante_share_e_custo(self):
        dados = _dados([
            {"nome": "Campanha A", "res": 80, "inv": 160.0, "imp": 8000,
             "alc": 5000, "cliques": 400},
            {"nome": "Campanha B", "res": 20, "inv": 100.0, "imp": 2000,
             "alc": 1500, "cliques": 100},
        ])
        analise = dados["analise_sugerida"]
        self.assertIn("Campanha A", analise)
        self.assertIn("(80% do total)", analise)
        self.assertIn("R$ 2,00", analise)          # 160 / 80

    def test_campanhas_equilibradas_sem_destaque_forcado(self):
        dados = _dados([
            {"nome": "Campanha A", "res": 50, "inv": 100.0, "imp": 5000,
             "alc": 4000, "cliques": 300},
            {"nome": "Campanha B", "res": 50, "inv": 110.0, "imp": 5000,
             "alc": 4000, "cliques": 300},
        ])
        analise = dados["analise_sugerida"]
        self.assertIn("equilibrada", analise)
        self.assertNotIn("concentrou", analise)
        self.assertIn("entre R$ 2,00 e R$ 2,20", analise)

    def test_ctr_abaixo_leitura_positiva_e_passo_de_criativos(self):
        # CTR 1% (abaixo da faixa 2–5%); demais métricas dentro das faixas
        dados = _dados([{"nome": "C", "res": 5, "inv": 300.0, "imp": 10000,
                         "alc": 8000, "cliques": 100}])
        _valor, leitura = _linhas_funil(dados)["CTR (taxa de cliques)"]
        self.assertEqual(
            leitura, "Estamos renovando os criativos para elevar a taxa de cliques.")
        # Passo adiante aponta renovação de criativos, sem tom de falha
        self.assertIn("criativos", dados["analise_sugerida"])
        for termo in ("cansado", "não está prendendo", "Baixo"):
            self.assertNotIn(termo, leitura + dados["analise_sugerida"])

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

        analise = grupo["analise_sugerida"]
        # Resumo usa os totais somados e a leitura de eficiência do benchmark
        self.assertIn("R$ 250,00", analise)
        self.assertIn("R$ 10,00", analise)         # 250 / 25 resultados
        self.assertIn("público ainda longe da saturação", analise)
        # Shares 40/40/20: sem destaque forçado entre as unidades
        self.assertIn("equilibrada", analise)


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

    def test_linhas_na_ordem_de_envio(self):
        texto = _texto_pdf(_bytes_pdf(self._post_listagem()))
        # Ordem de envio ≠ ordem alfabética ≠ ordem por resultados:
        # centro (40) → norte (10) → sul (25)
        pos = [texto.index(nome) for nome in
               ("unidade centro", "unidade norte", "unidade sul")]
        self.assertEqual(pos, sorted(pos))

    def test_valores_por_conta_em_pt_br_sem_consolidar(self):
        texto = _texto_pdf(_bytes_pdf(self._post_listagem()))
        self.assertIn("R$ 80,00", texto)      # investimento da 1ª conta
        self.assertIn("R$ 2,00", texto)       # custo/resultado: 80 / 40
        self.assertIn("R$ 5,55", texto)       # custo/resultado: 55,50 / 10
        self.assertIn("7,50%", texto)         # CTR: 300 / 4000
        self.assertIn("2.500", texto)         # alcance pt-BR da 1ª conta
        self.assertIn("Conversas Iniciadas", texto)   # label do resultado
        # Sem consolidação nem análise
        self.assertNotIn("R$ 235,50", texto)  # soma dos investimentos
        self.assertNotIn("Análise", texto)

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
        # Nome do arquivo: cliente + métrica + período em hífen
        self.assertIn("TIM-Brasil-Conversas-Iniciadas", r["Content-Disposition"])

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
