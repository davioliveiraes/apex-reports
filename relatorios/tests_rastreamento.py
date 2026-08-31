# -*- coding: utf-8 -*-
"""
Testes da Análise de Rastreamento — o preset, as derivadas e o diagnóstico.

O arquivo de referência é o export real do preset `RASTREAMENTO` (30/07 a
28/08/2026, um conjunto, 582 cliques). Ele é magro de propósito nos testes: é
o retrato de uma campanha de WhatsApp, sem página de destino, sem vídeo e sem
classificação de relevância. Se a frente só funcionasse com o arquivo completo,
funcionaria em nenhum arquivo real desta conta.
"""

import io

from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from relatorios import parser_rastreamento as pr
from relatorios.rastreamento import diagnostico, mensagem, metricas

# O preset completo, com o `(BRL)` que o Meta cola em tudo que é dinheiro.
CABECALHO = [
    "Início dos relatórios", "Encerramento dos relatórios",
    "Nome do anúncio", "Veiculação do anúncio",
    "Cliques no link", "Cliques no link únicos",
    "CTR (taxa de cliques no link)", "CTR único (taxa de cliques no link)",
    "CPC (custo por clique no link) (BRL)",
    "Visualizações da página de destino",
    "Custo por visualização da página de destino (BRL)",
    "Configuração de atribuição",
    "Classificação de qualidade", "Classificação da taxa de engajamento",
    "Classificação da taxa de conversão",
    "Reproduções de vídeo por no mínimo 3 segundos", "ThruPlays",
    "Custo por ThruPlay (BRL)",
    "Reproduções de 25% do vídeo", "Reproduções de 50% do vídeo",
    "Reproduções de 75% do vídeo", "Reproduções de 100% do vídeo",
]

# O cabeçalho e a linha do export REAL — nível de conjunto, dez colunas, com
# as duas de página de destino vazias.
CABECALHO_REAL = [
    "Início dos relatórios", "Encerramento dos relatórios",
    "Nome do conjunto de anúncios", "Cliques no link", "Cliques no link únicos",
    "CTR (taxa de cliques no link)", "CTR único (taxa de cliques no link)",
    "Visualizações da página de destino",
    "Custo por visualização da página de destino (BRL)",
    "Configuração de atribuição",
]
LINHA_REAL = ["2026-07-30", "2026-08-28", "[ADV+][AUTO][LEADS][V1]",
              582, 544, 0.58193, 2.417993, None, None,
              "Clique de 7 dias ou visualização de 1 dia"]

ATRIBUICAO = "Clique de 7 dias ou visualização de 1 dia"


def linha(nome="[VIDEO][A]", cliques=400, unicos=360, ctr=2.1, ctr_u=5.5,
          cpc=0.90, lpv=340, custo_lpv=1.06, veiculacao="active",
          qualidade=None, engajamento=None, conversao=None,
          v3=9000, thruplays=4200, custo_tp=0.09,
          v25=6000, v50=2400, v75=1500, v100=1100):
    """Uma linha na ordem exata de `CABECALHO`."""
    return ["2026-08-01", "2026-08-31", nome, veiculacao, cliques, unicos,
            ctr, ctr_u, cpc, lpv, custo_lpv, ATRIBUICAO,
            qualidade, engajamento, conversao, v3, thruplays, custo_tp,
            v25, v50, v75, v100]


def imagem(nome="[IMG][A]", **kw):
    """Anúncio de imagem: as sete colunas de vídeo vêm vazias, que é como o
    Meta exporta um criativo estático."""
    kw.update(v3=None, thruplays=None, custo_tp=None,
              v25=None, v50=None, v75=None, v100=None)
    return linha(nome, **kw)


def planilha(linhas=None, cabecalho=CABECALHO, antes=()):
    wb = Workbook()
    ws = wb.active
    for extra in antes:
        ws.append(extra)
    ws.append(list(cabecalho))
    for l in (linhas if linhas is not None else [linha()]):
        ws.append(list(l))
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    buffer.name = "rastreamento.xlsx"
    return buffer


def ler(linhas=None, cabecalho=CABECALHO):
    return pr.ler_planilha_rastreamento(planilha(linhas, cabecalho))


def analisar(linhas=None, cabecalho=CABECALHO):
    """`(total, diagnóstico)` — o caminho inteiro, do .xlsx ao veredito."""
    dados, disponiveis = ler(linhas, cabecalho)
    total = metricas.consolidar(dados)
    return total, diagnostico.diagnosticar(total, disponiveis)


# ----------------------------------------------------------------------
# Parser e aliases
# ----------------------------------------------------------------------
class AliasesDoPresetTest(SimpleTestCase):
    """A camada de normalização (§6).

    As armadilhas deste preset são os pares único/não-único e o `(BRL)`. Casar
    a coluna errada não levanta erro nenhum — devolve o número do vizinho.
    """

    def setUp(self):
        self.dados, self.disponiveis = ler()

    def test_o_par_unico_nao_se_confunde(self):
        l = self.dados[0]
        self.assertEqual(l["link_clicks"], 400)
        self.assertEqual(l["unique_link_clicks"], 360)
        self.assertAlmostEqual(l["link_ctr"], 2.1)
        self.assertAlmostEqual(l["unique_link_ctr"], 5.5)

    def test_cabecalho_com_brl_e_reconhecido(self):
        """`CPC (custo por clique no link) (BRL)` e as outras três colunas de
        dinheiro do preset trazem o sufixo — e ele não pode atrapalhar."""
        l = self.dados[0]
        self.assertAlmostEqual(l["link_cpc"], 0.90)
        self.assertAlmostEqual(l["cost_per_landing_page_view"], 1.06)
        self.assertAlmostEqual(l["cost_per_thruplay"], 0.09)

    def test_custo_nao_rouba_a_coluna_do_volume(self):
        l = self.dados[0]
        self.assertEqual(l["landing_page_views"], 340)
        self.assertEqual(l["thruplays"], 4200)

    def test_os_quatro_marcos_do_video(self):
        l = self.dados[0]
        self.assertEqual((l["video_25"], l["video_50"], l["video_75"],
                          l["video_100"]), (6000, 2400, 1500, 1100))

    def test_as_tres_classificacoes_sao_distinguidas(self):
        dados, _ = ler([linha(qualidade="Acima da média",
                              engajamento="Na média",
                              conversao="Abaixo da média")])
        l = dados[0]
        self.assertEqual(l["quality_ranking"], "Acima da média")
        self.assertEqual(l["engagement_rate_ranking"], "Na média")
        self.assertEqual(l["conversion_rate_ranking"], "Abaixo da média")

    def test_a_regra_de_negocio_nao_ve_o_nome_do_meta(self):
        """§6: a grafia com que o Meta escreve o cabeçalho — parênteses,
        sufixo de moeda, nome longo da métrica — não existe fora do parser.

        "Cliques no link" continua aparecendo, mas como RÓTULO de tela, que é
        outra coisa: ele é escolha nossa de vocabulário, e mudar a coluna no
        Gerenciador não o invalida.
        """
        for modulo in (metricas, diagnostico, mensagem):
            fonte = io.open(modulo.__file__, encoding="utf-8").read()
            with self.subTest(modulo=modulo.__name__):
                self.assertNotIn("CTR (taxa", fonte)
                self.assertNotIn("(BRL)", fonte)
                self.assertNotIn("no mínimo 3 segundos", fonte)
                self.assertNotIn("página de destino)", fonte)
                self.assertNotIn("_COLUNAS_RASTREAMENTO", fonte)

    def test_le_o_export_real_de_conjuntos(self):
        """Dez colunas, nível de conjunto, sem vídeo e sem página de destino:
        é o arquivo que esta conta realmente produz."""
        dados, disponiveis = ler([LINHA_REAL], CABECALHO_REAL)
        self.assertEqual(dados[0]["link_clicks"], 582)
        self.assertEqual(dados[0]["adset_name"], "[ADV+][AUTO][LEADS][V1]")
        # Coluna presente e vazia não conta como métrica disponível.
        self.assertNotIn("landing_page_views", disponiveis)
        self.assertEqual(pr.blocos_possiveis(disponiveis), [pr.BLOCO_CLIQUE])

    def test_o_cabecalho_pode_nao_ser_a_primeira_linha(self):
        dados, _ = ler_com_prefixo()
        self.assertEqual(dados[0]["link_clicks"], 400)

    def test_linha_de_total_e_ignorada(self):
        total = linha(nome="Total de resultados")
        dados, _ = ler([linha(), total])
        self.assertEqual(len(dados), 1)


def ler_com_prefixo():
    return pr.ler_planilha_rastreamento(
        planilha(antes=[["Relatório de anúncios"], []]))


class NormalizacaoDeValoresTest(SimpleTestCase):
    """§31: o que o Meta escreve numa célula quando não há número."""

    def test_vazios_do_meta_viram_none_e_nao_zero(self):
        """A distinção importa: 0 ThruPlays é um vídeo que ninguém assistiu;
        `None` é um anúncio de imagem, que não tem a métrica."""
        for cru in ("", "-", "--", "—", "N/A", "n/a", "NaN", None):
            with self.subTest(cru=cru):
                self.assertIsNone(pr.numero(cru))

    def test_moeda_e_milhar_em_pt_br(self):
        self.assertAlmostEqual(pr.numero("R$ 1.234,56"), 1234.56)
        self.assertAlmostEqual(pr.numero("0,90"), 0.90)
        self.assertAlmostEqual(pr.numero("12.345,67"), 12345.67)

    def test_ponto_sozinho_e_lido_como_decimal(self):
        """"1.234" é ambíguo — milhar em pt-BR, decimal em en-US. O projeto
        inteiro resolve como decimal desde o primeiro parser, e é o que
        preserva "0.58" vindo do export real. Divergir só aqui faria a mesma
        célula virar dois números conforme a frente que a lê.
        """
        self.assertAlmostEqual(pr.numero("0.58"), 0.58)
        self.assertAlmostEqual(pr.numero("1.234"), 1.234)

    def test_percentual_nos_formatos_que_o_meta_exporta(self):
        """§13 dos testes: o `%` sai sem dividir por 100 — as taxas deste
        preset já vêm em unidade de percentual, conferido contra o export
        real."""
        self.assertAlmostEqual(pr.numero("0,58%"), 0.58)
        self.assertAlmostEqual(pr.numero("0.58"), 0.58)
        self.assertAlmostEqual(pr.numero(0.58193), 0.58193)
        self.assertAlmostEqual(pr.numero("2,42 %"), 2.42)

    def test_nan_de_planilha_quebrada(self):
        self.assertIsNone(pr.numero(float("nan")))

    def test_ranking_e_preservado_como_texto(self):
        """§12: categórico. "Acima da média" não vira 3."""
        self.assertEqual(pr.texto("Acima da média"), "Acima da média")
        self.assertIsNone(pr.texto("--"))

    def test_abaixo_da_media_casa_as_variacoes_de_grafia(self):
        for valor in ("Abaixo da média", "abaixo da media",
                      "Abaixo da média (20% inferiores)", "Below average"):
            with self.subTest(valor=valor):
                self.assertTrue(pr.abaixo_da_media(valor))
        for valor in ("Acima da média", "Na média", "", None):
            with self.subTest(valor=valor):
                self.assertFalse(pr.abaixo_da_media(valor))


class ValidacaoDoPresetTest(SimpleTestCase):
    """§5 e §30: o arquivo passa se sustentar UM bloco."""

    def test_so_metricas_de_clique_ja_basta(self):
        dados, disponiveis = ler([LINHA_REAL], CABECALHO_REAL)
        self.assertEqual(pr.blocos_possiveis(disponiveis), [pr.BLOCO_CLIQUE])

    def test_so_metricas_de_video_ja_basta(self):
        """Um export só de retenção não tem clique nenhum, e ainda assim
        responde a uma das quatro perguntas."""
        cab = ["Nome do anúncio", "ThruPlays", "Reproduções de 25% do vídeo",
               "Reproduções de 100% do vídeo"]
        _, disponiveis = ler([["[VIDEO][A]", 900, 1800, 300]], cab)
        self.assertEqual(pr.blocos_possiveis(disponiveis), [pr.BLOCO_RETENCAO])

    def test_export_de_outro_preset_e_recusado_na_busca_do_cabecalho(self):
        """O export do preset VERBA abre sem reclamar — nenhuma coluna dele é
        de rastreamento, então a recusa acontece antes de haver o que somar."""
        cab = ["Nome da campanha", "Orçamento", "Valor gasto (BRL)"]
        with self.assertRaises(pr.ErroDePreset) as ctx:
            ler([["Campanha X", "R$ 33,00 Diário", 120.0]], cab)
        self.assertIn("RASTREAMENTO", str(ctx.exception))
        self.assertTrue(ctx.exception.esperadas)

    def test_colunas_certas_todas_vazias_sao_recusadas_com_as_duas_listas(self):
        """O caminho estreito da segunda guarda: o cabeçalho É de
        rastreamento, mas nenhuma célula tem valor. Sem isto o arquivo
        passaria e a tela abriria com quatro blocos vazios.
        """
        cab = ["Nome do anúncio", "Visualizações da página de destino",
               "Custo por visualização da página de destino (BRL)"]
        with self.assertRaises(pr.ErroDePreset) as ctx:
            ler([["[A]", None, None]], cab)
        self.assertIn("não contém métricas suficientes", str(ctx.exception))
        self.assertTrue(ctx.exception.esperadas)

    def test_coluna_presente_mas_toda_vazia_nao_conta(self):
        """É o caso do export de WhatsApp: as colunas de página de destino
        vêm, sempre em branco. Contá-las abriria um bloco que não existe."""
        dados, disponiveis = ler([linha(lpv=None, custo_lpv=None)])
        self.assertNotIn("landing_page_views", disponiveis)
        self.assertNotIn(pr.BLOCO_DESTINO, pr.blocos_possiveis(disponiveis))

    def test_planilha_vazia(self):
        with self.assertRaises(ValueError):
            ler([])

    def test_ler_arquivo_devolve_erro_em_vez_de_levantar(self):
        arquivo = planilha([["Campanha X", 1]], ["Nome da campanha", "X"])
        arquivo.name = "verba.xlsx"
        linhas, disp, erro, encontradas, esperadas = (
            pr.ler_arquivo_rastreamento(arquivo))
        self.assertIsNone(linhas)
        self.assertIn("verba.xlsx", erro)
        self.assertTrue(esperadas)


# ----------------------------------------------------------------------
# Métricas derivadas e agregação
# ----------------------------------------------------------------------
class DerivadasTest(SimpleTestCase):
    """§17: só o que tem numerador e denominador no próprio arquivo."""

    def test_taxa_de_carregamento(self):
        self.assertAlmostEqual(metricas.taxa_carregamento(80, 100), 80.0)

    def test_taxa_de_carregamento_sem_lpv_nao_calcula(self):
        """§10 e §11: campanha de WhatsApp não tem página de destino, e não
        calcular é a resposta certa — não zero."""
        self.assertIsNone(metricas.taxa_carregamento(None, 100))

    def test_taxa_de_carregamento_com_zero_cliques(self):
        """§8 dos testes: divisão por zero."""
        self.assertIsNone(metricas.taxa_carregamento(50, 0))
        self.assertIsNone(metricas.taxa_carregamento(0, 0))

    def test_as_quatro_retencoes(self):
        ret = metricas.retencao({"video_25": 1000, "video_50": 400,
                                 "video_75": 250, "video_100": 200})
        self.assertAlmostEqual(ret["25_50"], 40.0)
        self.assertAlmostEqual(ret["50_75"], 62.5)
        self.assertAlmostEqual(ret["75_100"], 80.0)
        self.assertAlmostEqual(ret["25_100"], 20.0)

    def test_retencao_com_marcos_ausentes(self):
        """§10 dos testes: 75% e 100% não vieram."""
        ret = metricas.retencao({"video_25": 1000, "video_50": 400,
                                 "video_75": None, "video_100": None})
        self.assertAlmostEqual(ret["25_50"], 40.0)
        self.assertIsNone(ret["50_75"])
        self.assertIsNone(ret["75_100"])
        self.assertIsNone(ret["25_100"])

    def test_retencao_com_marco_zerado_nao_divide(self):
        ret = metricas.retencao({"video_25": 0, "video_50": 0,
                                 "video_75": 0, "video_100": 0})
        self.assertTrue(all(v is None for v in ret.values()))

    def test_maior_queda_aponta_o_trecho_e_nao_o_segundo(self):
        """§14: o XLSX não tem linha do tempo do vídeo. Dizer em que segundo
        a queda aconteceu seria invenção."""
        ret = metricas.retencao({"video_25": 1000, "video_50": 400,
                                 "video_75": 380, "video_100": 360})
        trecho, perda = metricas.maior_queda(ret)
        self.assertEqual(trecho, "25% e 50%")
        self.assertAlmostEqual(perda, 60.0)

    def test_maior_queda_sem_marcos(self):
        self.assertIsNone(metricas.maior_queda(metricas.retencao({})))


class AgregacaoTest(SimpleTestCase):
    """§18: aditiva soma, taxa se reconstrói do denominador."""

    def test_aditivas_somam(self):
        total, _ = analisar([linha("[A]", cliques=400, unicos=360, lpv=340),
                             linha("[B]", cliques=120, unicos=110, lpv=52)])
        self.assertEqual(total["link_clicks"], 520)
        self.assertEqual(total["unique_link_clicks"], 470)
        self.assertEqual(total["landing_page_views"], 392)
        self.assertEqual(total["thruplays"], 8400)

    def test_ctr_consolidado_nao_e_media_simples(self):
        """CTR 2,1% num anúncio de 400 cliques e 0,7% num de 120 não dão 1,4%
        — dão 1,44%, porque o denominador do primeiro é muito maior."""
        total, _ = analisar([linha("[A]", cliques=400, ctr=2.1),
                             linha("[B]", cliques=120, ctr=0.7)])
        self.assertNotAlmostEqual(total["link_ctr"], 1.4, places=2)
        # Σcliques ÷ Σimpressões reconstruídas.
        impressoes = 400 / 0.021 + 120 / 0.007
        self.assertAlmostEqual(total["link_ctr"], 520 / impressoes * 100,
                               places=6)

    def test_cpc_consolidado_pondera_pelos_cliques(self):
        total, _ = analisar([linha("[A]", cliques=400, cpc=0.90),
                             linha("[B]", cliques=100, cpc=3.00)])
        # (360 + 300) ÷ 500 = 1,32 — e não (0,90 + 3,00) ÷ 2 = 1,95.
        self.assertAlmostEqual(total["link_cpc"], 1.32, places=6)

    def test_os_dois_ctr_reconstroem_denominadores_diferentes(self):
        """CTR usa impressões, CTR único usa alcance. Conferido contra o
        export real: 582 cliques a 0,58193% dão as 100.012 impressões e 544
        únicos a 2,417993% dão os 22.498 de alcance que o preset DESEMPENHO
        da mesma conta declara."""
        dados, _ = ler([LINHA_REAL], CABECALHO_REAL)
        a = metricas.consolidar(dados)["anuncios"][0]
        self.assertEqual(round(a["_impressoes"]), 100012)
        self.assertEqual(round(a["_alcance"]), 22498)

    def test_taxa_nao_consolidavel_devolve_none(self):
        """Sem CPC em linha nenhuma não há como reconstruir o gasto, e §18
        manda preferir a leitura por anúncio a um número inventado."""
        total, _ = analisar([linha(cpc=None)])
        self.assertIsNone(total["link_cpc"])

    def test_participacao_de_cliques_e_de_lpv(self):
        total, _ = analisar([linha("[A]", cliques=300, lpv=200),
                             linha("[B]", cliques=100, lpv=100)])
        por_rotulo = {a["rotulo"]: a for a in total["anuncios"]}
        self.assertAlmostEqual(por_rotulo["[A]"]["share_clicks"], 0.75)
        self.assertAlmostEqual(por_rotulo["[B]"]["share_lpv"], 1 / 3)


# ----------------------------------------------------------------------
# Vídeo e imagem
# ----------------------------------------------------------------------
class VideoEImagemTest(SimpleTestCase):
    """§13 e §25: retenção só existe para quem tem vídeo."""

    def test_anuncio_de_imagem_nao_tem_bloco_de_retencao(self):
        total, diag = analisar([imagem()])
        self.assertEqual(total["n_video"], 0)
        bloco = _bloco(diag, pr.BLOCO_RETENCAO)
        self.assertFalse(bloco["disponivel"])
        self.assertIn("Sem métricas de vídeo", bloco["ausencia"])

    def test_anuncio_de_video_tem_bloco_de_retencao(self):
        total, diag = analisar([linha()])
        self.assertEqual(total["n_video"], 1)
        self.assertTrue(_bloco(diag, pr.BLOCO_RETENCAO)["disponivel"])

    def test_arquivo_misto_conta_so_os_de_video(self):
        total, _ = analisar([linha("[VIDEO][A]"), imagem("[IMG][B]")])
        self.assertEqual((total["n_anuncios"], total["n_video"]), (2, 1))

    def test_o_texto_do_cliente_omite_video_para_imagem(self):
        total, diag = analisar([imagem()])
        texto = mensagem.redigir(total, diag)
        for palavra in ("vídeo", "ThruPlay", "retenção"):
            with self.subTest(palavra=palavra):
                self.assertNotIn(palavra, texto)


# ----------------------------------------------------------------------
# Diagnóstico
# ----------------------------------------------------------------------
class DiagnosticoTest(SimpleTestCase):
    """§20, §21 e §26: comparação, nunca régua inventada."""

    def test_relevancia_abaixo_da_media_vence_como_evidencia(self):
        """É o único sinal que não sai da nossa aritmética: o Meta comparou o
        anúncio com os concorrentes reais pelo mesmo público."""
        _, diag = analisar([linha(qualidade="Abaixo da média"),
                            linha("[B]", cliques=100, ctr=0.5, lpv=20)])
        self.assertEqual(diag["gargalo"]["bloco"], pr.BLOCO_RELEVANCIA)
        self.assertIn("o Meta classificou", diag["gargalo"]["evidencia"])

    def test_dispersao_entre_anuncios_vira_gargalo_com_os_dois_numeros(self):
        """§20 pede dado comprovável: a evidência cita os dois extremos."""
        _, diag = analisar([linha("[A]", cliques=300, lpv=255),
                            linha("[B]", cliques=150, lpv=61)])
        gargalo = diag["gargalo"]
        self.assertEqual(gargalo["bloco"], pr.BLOCO_DESTINO)
        self.assertIn("41%", gargalo["evidencia"])
        self.assertIn("85%", gargalo["evidencia"])

    def test_um_anuncio_so_nao_produz_gargalo(self):
        """§26: sem um segundo anúncio não há comparação, e sem comparação a
        conclusão seria uma régua inventada."""
        _, diag = analisar([linha()])
        self.assertIsNone(diag["gargalo"])

    def test_anuncios_parecidos_nao_produzem_gargalo(self):
        _, diag = analisar([linha("[A]", cliques=300, ctr=1.9, lpv=255),
                            linha("[B]", cliques=280, ctr=1.8, lpv=235)])
        self.assertIsNone(diag["gargalo"])

    def test_nao_existe_benchmark_universal(self):
        """§21: nenhum "CTR bom = X" no código. O lugar está reservado e
        vazio."""
        self.assertEqual(diagnostico.LIMIARES, {})

    def test_nao_ha_classificacao_do_periodo(self):
        """§22: sem metodologia oficial, nenhum selo BOM/REGULAR/RUIM."""
        total, diag = analisar([linha()])
        texto = mensagem.redigir(total, diag)
        for selo in ("BOM", "REGULAR", "RUIM", "ÓTIMO", "Excelente"):
            with self.subTest(selo=selo):
                self.assertNotIn(selo, texto)

    def test_o_video_nunca_vence_o_destino_por_ser_maior_a_queda(self):
        """A armadilha que o desenho evita: todo funil de vídeo perde mais de
        80% até o fim, e escolher "a maior perda" faria o vídeo ser o gargalo
        de todo arquivo, para sempre."""
        _, diag = analisar([
            linha("[A]", cliques=300, lpv=290, v25=1000, v50=200, v75=80,
                  v100=40),
            linha("[B]", cliques=280, lpv=270, v25=900, v50=180, v75=70,
                  v100=35)])
        self.assertIsNone(diag["gargalo"])

    def test_os_quatro_blocos_saem_sempre_na_mesma_ordem(self):
        _, diag = analisar([linha()])
        self.assertEqual([b["chave"] for b in diag["blocos"]],
                         [pr.BLOCO_CLIQUE, pr.BLOCO_DESTINO,
                          pr.BLOCO_RELEVANCIA, pr.BLOCO_RETENCAO])

    def test_bloco_sem_dado_nao_lista_metrica_nenhuma(self):
        """§25: nada de grade vazia de traços."""
        _, diag = analisar([imagem()])
        self.assertEqual(_bloco(diag, pr.BLOCO_RETENCAO)["metricas"], [])

    def test_rankings_vazios_nao_quebram_e_nao_viram_sinal(self):
        """§5 dos testes: anúncio novo, sem volume para o Meta classificar."""
        _, diag = analisar([linha(qualidade=None, engajamento=None,
                                  conversao=None)])
        bloco = _bloco(diag, pr.BLOCO_RELEVANCIA)
        self.assertFalse(bloco["disponivel"])
        self.assertEqual(bloco["sinais"], [])

    def test_a_maior_queda_do_video_e_sempre_reportada(self):
        """Comparação interna ao mesmo funil — legítima com um anúncio só."""
        _, diag = analisar([linha(v25=1000, v50=300, v75=280, v100=260)])
        sinais = _bloco(diag, pr.BLOCO_RETENCAO)["sinais"]
        self.assertTrue(any("25% e 50%" in s["texto"] for s in sinais))


def _bloco(diag, chave):
    return next(b for b in diag["blocos"] if b["chave"] == chave)


# ----------------------------------------------------------------------
# Texto do cliente
# ----------------------------------------------------------------------
class TextoDoClienteTest(SimpleTestCase):
    """§16, §27 e §28."""

    def test_nao_inventa_conversao(self):
        """§16: o preset não tem resultado, conversa, contato nem venda.
        Nenhuma taxa clique→conversa pode existir."""
        total, diag = analisar([linha()])
        texto = mensagem.redigir(total, diag).lower()
        for proibido in ("conversa", "lead", "venda", "compra", "roas",
                         "cpa", "custo por resultado", "converteu"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, texto)

    def test_formatacao_de_whatsapp(self):
        """§28: asterisco simples, sem markdown complexo e sem tabela."""
        total, diag = analisar([linha(qualidade="Abaixo da média"),
                                linha("[B]", cliques=100)])
        texto = mensagem.redigir(total, diag)
        self.assertTrue(texto.startswith("*Rastreamento da campanha"))
        for proibido in ("**", "##", "|", "- ", "```"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, texto)

    def test_cita_o_periodo_do_arquivo(self):
        total, diag = analisar([linha()])
        self.assertIn("01/08/2026 a 31/08/2026",
                      mensagem.redigir(total, diag))

    def test_os_dois_ctr_nunca_sao_comparados_na_mesma_frase(self):
        """Têm denominadores diferentes — impressões contra alcance. Lado a
        lado, o cliente leria o único como a versão limpa do outro."""
        total, diag = analisar([linha(ctr=2.1, ctr_u=5.5)])
        texto = mensagem.redigir(total, diag)
        self.assertIn("CTR de", texto)
        self.assertNotIn("CTR único", texto)

    def test_sem_gargalo_o_paragrafo_de_atencao_some(self):
        total, diag = analisar([linha()])
        self.assertNotIn("ponto de atenção", mensagem.redigir(total, diag))

    def test_com_gargalo_o_paragrafo_traz_a_evidencia(self):
        total, diag = analisar([linha("[A]", cliques=300, lpv=255),
                                linha("[B]", cliques=150, lpv=61)])
        texto = mensagem.redigir(total, diag)
        self.assertIn("*Principal ponto de atenção: destino*", texto)
        self.assertIn("41%", texto)

    def test_campanha_de_whatsapp_nao_e_acusada_de_pagina_com_problema(self):
        """§11: sem página de destino a etapa não é avaliada, e o silêncio é a
        leitura certa — não uma acusação."""
        dados, disponiveis = ler([LINHA_REAL], CABECALHO_REAL)
        total = metricas.consolidar(dados)
        texto = mensagem.redigir(total,
                                 diagnostico.diagnosticar(total, disponiveis))
        self.assertNotIn("página", texto.lower())
        self.assertIn("582 cliques no link", texto)

    def test_zero_cliques_ainda_diz_alguma_coisa(self):
        """§7 dos testes. Sem esta frase o texto sairia só com o cabeçalho."""
        total, diag = analisar([linha(cliques=0, unicos=0, ctr=0.0, ctr_u=0.0,
                                      cpc=None, lpv=0, custo_lpv=None)])
        self.assertIn("não registraram cliques", mensagem.redigir(total, diag))

    def test_nao_promete_futuro_nem_afirma_causa(self):
        total, diag = analisar([linha(qualidade="Abaixo da média"),
                                linha("[B]", cliques=100)])
        texto = mensagem.redigir(total, diag).lower()
        for proibido in ("vamos", "garantimos", "certamente", "criativo ruim",
                         "público errado", "oferta ruim", "não funciona"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, texto)

    def test_o_texto_e_de_tamanho_medio(self):
        total, diag = analisar([linha(qualidade="Abaixo da média"),
                                linha("[B]", cliques=100)])
        self.assertLess(len(mensagem.redigir(total, diag).split()), 220)


# ----------------------------------------------------------------------
# Fluxo
# ----------------------------------------------------------------------
class FluxoRastreamentoTest(TestCase):
    """As duas telas."""

    def _enviar(self, arquivo=None):
        return self.client.post("/rastreamento/", {
            "cliente": "TIM Brasil",
            "arquivo": arquivo or planilha(),
        }, follow=True)

    def test_o_painel_abre(self):
        r = self.client.get("/rastreamento/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Análise de Rastreamento")
        self.assertContains(r, "preset RASTREAMENTO")

    def test_o_envio_leva_a_analise(self):
        r = self._enviar()
        self.assertContains(r, "TIM Brasil")
        self.assertContains(r, "01/08/2026 a 31/08/2026")

    def test_a_tela_mostra_os_quatro_blocos(self):
        html = self._enviar().content.decode()
        for titulo in ("Clique", "Destino", "Relevância", "Retenção"):
            with self.subTest(titulo=titulo):
                self.assertIn(titulo, html)

    def test_a_tela_traz_o_texto_num_campo_copiavel(self):
        html = self._enviar().content.decode()
        self.assertIn('id="txt-rastreamento"', html)
        self.assertIn('data-alvo="txt-rastreamento"', html)
        self.assertIn("Copiar texto", html)
        self.assertIn("Nova análise", html)

    def test_nao_ha_pdf_no_fluxo(self):
        """§29: Rastreamento não gera PDF."""
        painel = _sem_estilo(self.client.get("/rastreamento/").content.decode())
        analise = _sem_estilo(self._enviar().content.decode())
        self.assertNotIn("PDF", painel)
        self.assertNotIn("PDF", analise)

    def test_o_diagnostico_aparece_na_tela(self):
        html = self._enviar(planilha([
            linha("[A]", cliques=300, lpv=255),
            linha("[B]", cliques=150, lpv=61)])).content.decode()
        self.assertIn("Principal ponto de atenção", html)
        self.assertIn("Destino", html)

    def test_sem_evidencia_a_tela_diz_isso_em_vez_de_inventar(self):
        html = self._enviar().content.decode()
        self.assertIn("Sem evidência suficiente", html)
        self.assertIn('class="diagnostico vazio"', html)

    def test_arquivo_sem_metricas_mostra_as_duas_listas(self):
        errado = planilha([["Campanha X", "R$ 33,00 Diário"]],
                          ["Nome da campanha", "Orçamento"])
        errado.name = "verba.xlsx"
        r = self.client.post("/rastreamento/", {"cliente": "TIM",
                                                "arquivo": errado})
        self.assertContains(r, "Métricas encontradas")
        self.assertContains(r, "Métricas esperadas")
        self.assertTemplateUsed(r, "relatorios/rastreamento_index.html")
        self.assertNotIn("rastreamento_apex", self.client.session)

    def test_o_export_real_atravessa_o_fluxo(self):
        r = self._enviar(planilha([LINHA_REAL], CABECALHO_REAL))
        html = r.content.decode()
        self.assertIn("582", html)
        # Um bloco de quatro, e a tela diz por que os outros três faltam.
        self.assertIn("1 de 4 blocos", html)
        self.assertIn("WhatsApp, Direct ou Messenger", html)
        self.assertIn("Sem métricas de vídeo", html)

    def test_a_analise_sem_sessao_volta_para_o_envio(self):
        self.assertRedirects(self.client.get("/rastreamento/analise/"),
                             "/rastreamento/")

    def test_nao_e_um_xlsx(self):
        arquivo = io.BytesIO(b"nao sou planilha")
        arquivo.name = "relatorio.pdf"
        r = self.client.post("/rastreamento/", {"cliente": "TIM",
                                                "arquivo": arquivo})
        self.assertContains(r, "não é um .xlsx")


def _sem_estilo(html):
    """O HTML sem o <style>, que é inline e traz "Gerar PDF" num comentário."""
    antes, _, resto = html.partition("<style>")
    return antes + resto.partition("</style>")[2]


class HomeComQuatroFrentesTest(TestCase):
    """§2 e §35: o cartão saiu de "Em breve"; a Leitura Rápida continua."""

    def _html(self):
        return self.client.get("/").content.decode()

    def test_o_rastreamento_virou_cartao_clicavel(self):
        html = self._html()
        self.assertIn('class="frente" href="/rastreamento/"', html)
        cartao = html.split('class="frente" href="/rastreamento/"')[1] \
                     .split("</a>")[0]
        self.assertIn("Análise de Rastreamento", cartao)
        self.assertIn("Onde está o gargalo?", cartao)
        self.assertIn("preset RASTREAMENTO", cartao)
        self.assertIn("diagnóstico", cartao)
        self.assertNotIn("Em breve", cartao)

    def test_a_grade_continua_2x2_com_quatro_cartoes(self):
        grade = self._html().split('class="frentes"')[1]
        cartoes = (grade.count('class="frente"')
                   + grade.count('class="frente em-breve"'))
        self.assertEqual(cartoes, 4)

    def test_nenhum_cartao_da_grade_esta_em_breve(self):
        """As quatro análises estão de pé (§35)."""
        grade = self._html().split('class="frentes"')[1]
        self.assertNotIn("frente em-breve", grade)
        self.assertNotIn("Em breve", grade)

    def test_a_leitura_rapida_continua_fora_da_grade(self):
        """Ela saiu de "Em breve" em 30/08/2026, mas continua onde estava: um
        atalho compacto ao lado do título, e não um quinto cartão."""
        html = self._html()
        self.assertIn('class="atalho" href="/leitura/"', html)
        self.assertLess(html.index('class="atalho"'),
                        html.index('class="frentes"'))
        self.assertNotIn("Leitura Rápida", html.split('class="frentes"')[1])

    def test_as_quatro_analises_apontam_para_as_rotas_certas(self):
        html = self._html()
        for destino in ("/geral/", "/desempenho/", "/verba/", "/rastreamento/"):
            with self.subTest(destino=destino):
                self.assertIn(f'class="frente" href="{destino}"', html)


class SuperficieDaFrenteTest(SimpleTestCase):
    """§34: Rastreamento não é Desempenho com outros nomes."""

    def test_nao_importa_o_motor_das_outras_frentes(self):
        for modulo in (metricas, diagnostico, mensagem):
            fonte = io.open(modulo.__file__, encoding="utf-8").read()
            with self.subTest(modulo=modulo.__name__):
                self.assertNotIn("analise_desempenho", fonte)
                self.assertNotIn("from .analysis import rules", fonte)
                self.assertNotIn("fechamento_verba", fonte)

    def test_tem_o_seu_proprio_mapa_de_colunas(self):
        from relatorios import parser_desempenho, parser_xlsx
        self.assertIsNot(pr._COLUNAS_RASTREAMENTO, parser_xlsx._COLUNAS)
        self.assertIsNot(pr._COLUNAS_RASTREAMENTO,
                         parser_desempenho._COLUNAS_DESEMPENHO)

    def test_as_responsabilidades_estao_separadas(self):
        """§33: parser, cálculo, diagnóstico e texto em arquivos diferentes.
        O texto não calcula; o cálculo não redige."""
        calculo = io.open(metricas.__file__, encoding="utf-8").read()
        diag = io.open(diagnostico.__file__, encoding="utf-8").read()
        texto = io.open(mensagem.__file__, encoding="utf-8").read()
        # O cálculo não redige: nenhuma frase de saída nasce nele.
        self.assertNotIn("*Principal ponto", calculo)
        self.assertNotIn("Sem métricas de vídeo neste arquivo", calculo)
        # O texto não decide: o limiar de comparação vive no diagnóstico.
        self.assertNotIn("MARGEM_RELATIVA = ", texto)
        self.assertIn("MARGEM_RELATIVA = ", diag)
