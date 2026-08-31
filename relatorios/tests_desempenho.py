# -*- coding: utf-8 -*-
"""
Testes da Análise de Desempenho — o preset, a consolidação e o texto.

O arquivo de referência da implementação é o export real de conjuntos de
anúncios com a predefinição `DESEMPENHO` (30/07 a 28/08/2026, um conjunto,
393 conversas). Os números dele estão no `REFERENCIA` abaixo e são conferidos
contra o que o Gerenciador mostra — é o único jeito de saber que a
consolidação não inventou nada.
"""

import io
import json

from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from relatorios import analise_desempenho as ad
from relatorios import selecao_campanhas as sc
from relatorios import parser_desempenho as pd

CONVERSA = "actions:onsite_conversion.messaging_conversation_started_7d"

# As colunas na ordem exata em que o export real as traz.
CABECALHO = [
    "Início dos relatórios", "Encerramento dos relatórios",
    "Nome do conjunto de anúncios", "Veiculação do conjunto de anúncios",
    "Resultados", "Indicador de resultados", "Custo por resultados",
    "Alcance", "Impressões", "Frequência",
    "CPM (custo por 1.000 impressões) (BRL)",
    "Conversas por mensagem iniciadas",
    "Custo por conversa por mensagem iniciada (BRL)",
    "Novos contatos de mensagem",
    "Resultados (iniciais)", "Indicador de resultados (inicial)",
]

# A linha do export real, com as duas últimas colunas vazias como ela veio.
REFERENCIA = ["2026-07-30", "2026-08-28", "[ADV+][AUTO][LEADS][V1]", "active",
              393, CONVERSA, 4.52374046, 22498, 100012, 4.445373, 17.776167,
              393, 4.52374, 288, None, None]


def planilha(linhas=(REFERENCIA,), cabecalho=CABECALHO, antes=()):
    """Um .xlsx em memória, no formato do export."""
    wb = Workbook()
    ws = wb.active
    for extra in antes:
        ws.append(extra)
    ws.append(list(cabecalho))
    for linha in linhas:
        ws.append(list(linha))
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    buffer.name = "desempenho.xlsx"
    return buffer


def campanha(nome="[LEADS][CELULAR-BOLETO][BRAGANCA][ABO][01SET25]", **kw):
    """Uma linha de export no nível de CAMPANHA — o do arquivo de referência.

    O preset é o mesmo do export de conjuntos; o que muda é a coluna do nome,
    e era justamente ela que faltava no parser até 30/08/2026.
    """
    linha = conjunto(nome, **kw)
    linha["campanha"] = linha.pop("conjunto")
    return linha


def conjunto(nome="[LEADS][CELULAR][ITU][ABO][01SET25]", resultados=100,
             custo=5.0, alcance=8000, impressoes=30000, frequencia=3.75,
             cpm=16.67, conversas=None, custo_conversa=None, novos=60,
             veiculacao="active"):
    """Uma linha já parseada — para os testes do motor, sem passar pelo .xlsx."""
    return {
        "inicio": "2026-08-01", "termino": "2026-08-31",
        "conjunto": nome, "veiculacao": veiculacao,
        "resultados": float(resultados), "indicador": CONVERSA,
        "custo_resultado": custo, "alcance": float(alcance),
        "impressoes": float(impressoes), "frequencia": frequencia, "cpm": cpm,
        "conversas": float(resultados if conversas is None else conversas),
        "custo_conversa": custo if custo_conversa is None else custo_conversa,
        "novos_contatos": float(novos),
    }


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------
class PresetDesempenhoTest(SimpleTestCase):
    """O mapa de colunas, que é onde este preset dá errado.

    Quatro colunas começam iguais — `Resultados`, `Resultados (iniciais)`,
    `Indicador de resultados` e `Indicador de resultados (inicial)`. Casar a
    errada faz a análise ler a coluna vazia e concluir que o mês não teve
    resultado nenhum, sem erro em lugar nenhum.
    """

    def test_le_o_export_de_referencia(self):
        linhas = pd.ler_planilha_desempenho(planilha())
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["resultados"], 393.0)
        self.assertEqual(linhas[0]["novos_contatos"], 288.0)
        self.assertEqual(linhas[0]["conjunto"], "[ADV+][AUTO][LEADS][V1]")

    def test_resultados_nao_e_confundido_com_resultados_iniciais(self):
        """A coluna vazia vem DEPOIS na planilha; um match por "contém" sem
        exclusão pegaria a primeira que casasse."""
        linhas = pd.ler_planilha_desempenho(planilha())
        self.assertEqual(linhas[0]["resultados"], 393.0)
        self.assertIsNone(linhas[0]["resultados_iniciais"])

    def test_indicador_nao_e_confundido_com_o_inicial(self):
        linhas = pd.ler_planilha_desempenho(planilha())
        self.assertEqual(linhas[0]["indicador"], CONVERSA)
        self.assertIsNone(linhas[0]["indicador_inicial"])

    def test_cpm_nao_rouba_a_coluna_de_impressoes(self):
        """"CPM (custo por 1.000 impressões)" contém "impressões" e "custo"."""
        linhas = pd.ler_planilha_desempenho(planilha())
        self.assertEqual(linhas[0]["impressoes"], 100012.0)
        self.assertAlmostEqual(linhas[0]["cpm"], 17.776167)

    def test_custo_por_conversa_nao_rouba_a_coluna_de_conversas(self):
        linhas = pd.ler_planilha_desempenho(planilha())
        self.assertEqual(linhas[0]["conversas"], 393.0)
        self.assertAlmostEqual(linhas[0]["custo_conversa"], 4.52374)

    def test_as_colunas_opcionais_vazias_nao_impedem_a_leitura(self):
        """`Resultados (iniciais)` vem vazia no export real. Exigi-la
        recusaria o arquivo certo."""
        self.assertNotIn("resultados_iniciais", pd.COLUNAS_ESSENCIAIS)
        self.assertNotIn("indicador_inicial", pd.COLUNAS_ESSENCIAIS)

    def test_o_cabecalho_pode_nao_ser_a_primeira_linha(self):
        linhas = pd.ler_planilha_desempenho(
            planilha(antes=[["Relatório de conjuntos"], []]))
        self.assertEqual(linhas[0]["resultados"], 393.0)

    def test_linha_de_total_do_export_e_ignorada(self):
        total = list(REFERENCIA)
        total[2] = "Total de resultados"
        linhas = pd.ler_planilha_desempenho(planilha([REFERENCIA, total]))
        self.assertEqual(len(linhas), 1)

    def test_varios_conjuntos_viram_varias_linhas(self):
        outro = list(REFERENCIA)
        outro[2] = "[LEADS][B][V1]"
        linhas = pd.ler_planilha_desempenho(planilha([REFERENCIA, outro]))
        self.assertEqual(len(linhas), 2)

    def test_datas_tipadas_viram_texto_iso(self):
        """A sessão serializa em JSON e não sabe gravar `date`."""
        from datetime import date
        crua = list(REFERENCIA)
        crua[0], crua[1] = date(2026, 7, 30), date(2026, 8, 28)
        linhas = pd.ler_planilha_desempenho(planilha([crua]))
        self.assertEqual(linhas[0]["inicio"], "2026-07-30")

    def test_ativa_le_a_veiculacao(self):
        self.assertTrue(pd.ativa("active"))
        self.assertTrue(pd.ativa("Ativa"))
        # "Em análise" e "programada" ainda não gastam — não contam como no ar.
        self.assertFalse(pd.ativa("paused"))
        self.assertFalse(pd.ativa("Em análise"))
        self.assertFalse(pd.ativa(""))


class ValidacaoDoPresetTest(SimpleTestCase):
    """Arquivo errado precisa falhar dizendo QUAL coluna falta."""

    def test_coluna_essencial_faltando_e_nomeada(self):
        sem_cpm = [c for c in CABECALHO if not c.startswith("CPM")]
        linha = [v for c, v in zip(CABECALHO, REFERENCIA)
                 if not c.startswith("CPM")]
        with self.assertRaises(pd.ErroDePreset) as ctx:
            pd.ler_planilha_desempenho(planilha([linha], sem_cpm))
        self.assertIn("CPM (custo por 1.000 impressões)", ctx.exception.faltando)

    def test_varias_faltando_saem_todas(self):
        fora = ("Alcance", "Frequência", "Novos contatos de mensagem")
        cab = [c for c in CABECALHO if c not in fora]
        linha = [v for c, v in zip(CABECALHO, REFERENCIA) if c not in fora]
        with self.assertRaises(pd.ErroDePreset) as ctx:
            pd.ler_planilha_desempenho(planilha([linha], cab))
        self.assertEqual(sorted(ctx.exception.faltando), sorted(fora))

    def test_planilha_de_outro_preset_e_recusada_com_instrucao(self):
        """O export do preset VERBA abre sem reclamar — é por isso que a
        recusa precisa dizer o que fazer, não só que deu errado."""
        with self.assertRaises(pd.ErroDePreset) as ctx:
            pd.ler_planilha_desempenho(planilha(
                [["Campanha X", "R$ 33,00 Diário", 120.0]],
                ["Nome da campanha", "Orçamento", "Valor gasto (BRL)"]))
        self.assertIn("DESEMPENHO", str(ctx.exception))

    def test_planilha_sem_linha_de_dados(self):
        with self.assertRaises(ValueError):
            pd.ler_planilha_desempenho(planilha([]))

    def test_ler_arquivo_devolve_erro_em_vez_de_levantar(self):
        arquivo = planilha([["Campanha X", 1]], ["Nome da campanha", "X"])
        arquivo.name = "verba.xlsx"
        linhas, erro, faltando = pd.ler_arquivo_desempenho(arquivo)
        self.assertIsNone(linhas)
        self.assertIn("verba.xlsx", erro)
        self.assertEqual(faltando, [])


# ----------------------------------------------------------------------
# Consolidação
# ----------------------------------------------------------------------
class ConsolidacaoTest(SimpleTestCase):
    """Os números do arquivo de referência, conferidos contra o Gerenciador."""

    def setUp(self):
        self.ag = ad.consolidar(pd.ler_planilha_desempenho(planilha()))

    def test_os_totais_sao_os_do_export(self):
        self.assertEqual(self.ag["resultados"], 393.0)
        self.assertEqual(self.ag["alcance"], 22498.0)
        self.assertEqual(self.ag["impressoes"], 100012.0)
        self.assertEqual(self.ag["novos_contatos"], 288.0)

    def test_as_razoes_batem_com_a_planilha_ate_o_centavo(self):
        """Com um conjunto só, o consolidado tem de ser o número do arquivo —
        se a derivação por investimento estivesse errada, apareceria aqui."""
        self.assertAlmostEqual(self.ag["custo_resultado"], 4.52374046, places=5)
        self.assertAlmostEqual(self.ag["cpm"], 17.776167, places=5)
        self.assertAlmostEqual(self.ag["frequencia"], 4.445373, places=5)
        self.assertAlmostEqual(self.ag["custo_conversa"], 4.52374, places=5)

    def test_o_resumo_da_tela_traz_os_nove_cartoes_formatados(self):
        resumo = {m["rotulo"]: m["valor"] for m in ad.resumo(self.ag)}
        self.assertEqual(resumo["Resultados"], "393")
        self.assertEqual(resumo["Custo por resultado"], "R$ 4,52")
        self.assertEqual(resumo["Alcance"], "22.498")
        self.assertEqual(resumo["Impressões"], "100.012")
        self.assertEqual(resumo["Frequência"], "4,45")
        self.assertEqual(resumo["CPM"], "R$ 17,78")
        self.assertEqual(resumo["Novos contatos"], "288")
        self.assertEqual(len(resumo), 9)

    def test_o_indicador_vira_termo_de_prosa(self):
        self.assertEqual(self.ag["rotulo_indicador"], "Conversas Iniciadas")
        self.assertEqual(self.ag["termos"][:2], ("conversa", "conversas"))


class AgregacaoDeVariosConjuntosTest(SimpleTestCase):
    """Aditivas somam; razões não. É a regra que a §8 da especificação pede."""

    def test_custo_consolidado_nao_e_media_simples_dos_conjuntos(self):
        """R$ 5 num conjunto que trouxe 200 e R$ 12 num que trouxe 60 não dão
        R$ 8,50 — dão R$ 6,62, porque o primeiro pesa mais."""
        ag = ad.consolidar([
            conjunto(resultados=200, custo=5.0, impressoes=40000, cpm=25.0),
            conjunto(nome="[LEADS][B][V1]", resultados=60, custo=12.0,
                     impressoes=18000, cpm=40.0),
        ])
        media_simples = (5.0 + 12.0) / 2
        self.assertNotAlmostEqual(ag["custo_resultado"], media_simples, places=2)
        self.assertAlmostEqual(ag["custo_resultado"], (1000 + 720) / 260,
                               places=4)

    def test_conjunto_que_gastou_e_nao_converteu_entra_no_custo(self):
        """Média ponderada pelos resultados apagaria este conjunto; o custo do
        período ficaria menor do que foi de verdade."""
        so_bom = ad.consolidar([conjunto(resultados=100, impressoes=30000,
                                         cpm=20.0)])
        com_seco = ad.consolidar([
            conjunto(resultados=100, impressoes=30000, cpm=20.0),
            conjunto(nome="[LEADS][B][V1]", resultados=0, custo=None,
                     impressoes=10000, cpm=20.0, novos=0),
        ])
        self.assertGreater(com_seco["custo_resultado"],
                           so_bom["custo_resultado"])

    def test_cpm_consolidado_pondera_pelas_impressoes(self):
        ag = ad.consolidar([
            conjunto(impressoes=90000, cpm=10.0),
            conjunto(nome="[LEADS][B][V1]", impressoes=10000, cpm=50.0),
        ])
        # (900 + 500) / 100000 * 1000 = 14, não (10+50)/2 = 30.
        self.assertAlmostEqual(ag["cpm"], 14.0, places=4)

    def test_o_alcance_somado_e_declarado_como_aproximacao(self):
        """A mesma pessoa atingida por dois conjuntos é contada duas vezes, e
        a frequência derivada sai subestimada. A tela avisa; o número não é
        escondido."""
        um = ad.consolidar([conjunto()])
        dois = ad.consolidar([conjunto(), conjunto(nome="[LEADS][B][V1]")])
        self.assertFalse(um["alcance_somado"])
        self.assertTrue(dois["alcance_somado"])

    def test_custo_por_conversa_ignora_conjuntos_sem_conversa(self):
        """Numa conta com objetivos misturados, dividir a verba inteira pelas
        conversas de um conjunto cobraria dele o que os outros gastaram."""
        ag = ad.consolidar([
            conjunto(resultados=100, impressoes=30000, cpm=20.0, conversas=100),
            conjunto(nome="[LEADS][B][V1]", resultados=50, impressoes=20000,
                     cpm=30.0, conversas=0, custo_conversa=None, novos=0),
        ])
        self.assertAlmostEqual(ag["custo_conversa"], 600.0 / 100, places=4)

    def test_conta_os_ativos_pela_veiculacao(self):
        ag = ad.consolidar([
            conjunto(), conjunto(nome="[LEADS][B][V1]", veiculacao="paused")])
        self.assertEqual((ag["n_conjuntos"], ag["n_ativos"]), (2, 1))


def selecionadas(linhas, chaves=None):
    """As linhas que sobram da seleção, na mesma ordem da view.

    Agrupar, aplicar o padrão, filtrar — `selecao_campanhas.aplicar` faz isso
    com um `request` na mão. Aqui a sequência é repetida sem o HTTP para os
    testes de motor poderem chamar `consolidar` sobre exatamente o que a tela
    consolida.
    """
    return sc.filtrar(linhas, chaves or sc.padrao(sc.grupos(linhas)))


class SelecaoDeCampanhaTest(SimpleTestCase):
    """Quais campanhas entram na leitura.

    O export de referência traz nove campanhas e oito estão paradas há meses,
    com zero em tudo. Consolidar o arquivo inteiro fazia o texto falar dessas
    oito — e falar delas como "conjuntos", porque num export de campanhas o
    nome do conjunto não existe e toda linha ficava anônima.

    Em 31/08/2026 o `<select>` de campanha única deu lugar ao bloco de caixas
    da Análise Geral (`selecao_campanhas.py`): mesmo agrupamento, mesma
    marcação, mesmo botão. O que se preservou foi o efeito — as paradas ficam
    de fora sem que ninguém precise clicar.
    """

    def _arquivo(self):
        """Nove campanhas, uma com dados. O retrato da conta real."""
        vivas = [campanha("[LEADS][CELULAR-BOLETO][BRAGANCA][ABO][01SET25]",
                          resultados=557, custo=2.68, alcance=25865,
                          impressoes=122901, cpm=12.16, novos=387)]
        mortas = [campanha(nome, resultados=0, custo=None, alcance=0,
                           impressoes=0, cpm=None, conversas=0,
                           custo_conversa=None, novos=0)
                  for nome in ("Test-Venda01-29/04", "Venda02-Aberto",
                               "Venda03-Fechado", "Lead02-TesteCria",
                               "Engaja-TesteCria", "Engaja-Aberto",
                               "Engaja-Semelhante", "Engaja-insta-test")]
        return mortas + vivas

    def test_o_arquivo_lista_todas_as_campanhas_para_escolher(self):
        self.assertEqual(len(sc.grupos(self._arquivo())), 9)

    def test_so_a_campanha_que_entregou_nasce_marcada(self):
        marcadas = sc.padrao(sc.grupos(self._arquivo()))
        self.assertEqual(marcadas, ["LEADS · CELULAR-BOLETO"])

    def test_so_o_que_esta_marcado_entra_nos_calculos(self):
        """§1 e §25: as oito paradas são irrelevantes depois da seleção."""
        ag = ad.consolidar(selecionadas(self._arquivo()))
        self.assertEqual(ag["resultados"], 557.0)
        self.assertEqual(ag["alcance"], 25865.0)
        self.assertEqual(ag["n_conjuntos"], 1)

    def test_marcar_outra_campanha_muda_todos_os_numeros(self):
        linhas = selecionadas(self._arquivo(), ["Venda02-Aberto"])
        self.assertEqual(ad.consolidar(linhas)["resultados"], 0.0)

    def test_marcar_duas_soma_as_duas(self):
        """A seleção passou a ser múltipla: duas marcadas entram somadas, e
        não comparadas uma com a outra."""
        linhas = [campanha("Campanha A", resultados=30),
                  campanha("Campanha B", resultados=20),
                  campanha("Campanha C", resultados=90)]
        ag = ad.consolidar(selecionadas(linhas, ["Campanha A", "Campanha B"]))
        self.assertEqual(ag["resultados"], 50.0)
        self.assertEqual(ag["n_campanhas"], 2)

    def test_chave_desconhecida_nao_esvazia_a_analise(self):
        """Sessão antiga, ou campanha que saiu do export: o padrão é melhor
        do que uma tela sem número nenhum."""
        arquivo = self._arquivo()
        grupos = sc.grupos(arquivo)
        vivas = [c for c in ("campanha-que-nao-existe",)
                 if c in {g["chave"] for g in grupos}]
        self.assertEqual(vivas, [])
        self.assertEqual(len(selecionadas(arquivo, vivas or None)), 1)

    def test_campanhas_paradas_saem_marcadas_para_a_tela(self):
        """O operador escolhe no escuro se a lista não disser quais estão
        paradas — são oito de nove neste arquivo."""
        paradas = [g for g in sc.grupos(self._arquivo()) if not g["entregou"]]
        self.assertEqual(len(paradas), 8)

    def test_export_de_conjuntos_ainda_funciona(self):
        """O preset é o mesmo nas duas abas do Gerenciador; o que muda é a
        coluna do nome, e o agrupamento cai no do conjunto."""
        linhas = [conjunto("[LEADS][A][ITU][ABO][01SET25]", resultados=40)]
        self.assertEqual([g["chave"] for g in sc.grupos(linhas)], ["LEADS · A"])
        self.assertEqual(ad.consolidar(selecionadas(linhas))["resultados"],
                         40.0)

    def test_varias_linhas_da_mesma_campanha_somam(self):
        """Export de conjuntos com a coluna de campanha: as linhas da campanha
        marcada entram todas."""
        linhas = [campanha("Campanha A", resultados=30),
                  campanha("Campanha A", resultados=20),
                  campanha("Campanha B", resultados=90)]
        ag = ad.consolidar(selecionadas(linhas, ["Campanha A"]))
        self.assertEqual(ag["resultados"], 50.0)
        self.assertEqual(ag["n_campanhas"], 1)


class RotuloDaLinhaTest(SimpleTestCase):
    """O nome que a INTERFACE mostra. O texto do cliente nunca o usa."""

    def test_prefere_o_nome_da_campanha(self):
        linha = campanha("[LEADS][CELULAR][ITU][ABO][01SET25]")
        linha["conjunto"] = "[OUTRO][NOME]"
        self.assertEqual(ad.rotulo_da_linha(linha, 1), "Celular · Itu")

    def test_cai_para_o_conjunto_quando_nao_ha_campanha(self):
        linha = conjunto("[LEADS][CELULAR][SALTO][ABO][13JUL26]")
        self.assertEqual(ad.rotulo_da_linha(linha, 1), "Celular · Salto")

    def test_nome_escrito_por_gente_passa_inteiro(self):
        self.assertEqual(ad.rotulo_da_linha("Público frio — Itu", 1),
                         "Público frio — Itu")

    def test_sem_nome_nenhum_vira_rotulo_neutro(self):
        """Nem "Conjunto 1" nem "Campanha 1": os dois inventam uma entidade
        que o arquivo não nomeou."""
        self.assertEqual(ad.rotulo_da_linha({}, 3), "Linha 3")
        self.assertEqual(ad.rotulo_da_linha(None, 2), "Linha 2")



class TextoDoClienteTest(SimpleTestCase):
    """A §12 e a §13: o que o texto precisa dizer, e o que não pode."""

    def setUp(self):
        self.ag = ad.consolidar(pd.ler_planilha_desempenho(planilha()))
        self.texto = ad.redigir(self.ag)

    def test_cita_o_periodo_lido_do_arquivo(self):
        self.assertIn("Entre 30/07/2026 e 28/08/2026", self.texto)

    def test_traz_resultado_custo_entrega_e_contatos(self):
        for pedaco in ("393 conversas", "R$ 4,52", "22.498 pessoas",
                       "100.012 impressões", "4,45", "R$ 17,78", "288"):
            with self.subTest(pedaco=pedaco):
                self.assertIn(pedaco, self.texto)

    def test_nao_repete_o_mesmo_numero_como_se_fossem_dois(self):
        """Numa campanha de mensagem, "Resultados" e "Conversas iniciadas" são
        a mesma coluna com dois nomes. Dizer "393 conversas e também 393
        conversas iniciadas" é o texto denunciando que ninguém o leu."""
        self.assertNotIn("Foram 393 conversas iniciadas", self.texto)
        self.assertEqual(self.texto.count("393 conversas"), 2)
        self.assertEqual(self.texto.count("393"), 2)

    def test_a_frequencia_e_descrita_e_nao_diagnosticada(self):
        """A §12 autoriza "exposição recorrente" e proíbe "criativo saturado":
        um é a divisão que produziu o número, o outro é uma causa que a
        planilha não comprova."""
        self.assertIn("frequência média de 4,45", self.texto)
        for proibido in ("saturad", "fadiga", "desgast", "cansad"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, self.texto.lower())

    def test_nao_promete_o_futuro(self):
        for proibido in ("vamos alcançar", "deve crescer", "garantimos",
                         "certamente", "no próximo mês teremos"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, self.texto.lower())

    def test_nao_cita_metrica_que_o_preset_nao_traz(self):
        """A §5: CTR, CPC, cliques, ROAS e valor gasto não existem neste
        export. O investimento é recuperado para ponderar os custos, e é
        justamente por isso que ele não pode vazar para o texto."""
        for ausente in ("ctr", "cpc", "clique", "roas", "valor gasto",
                        "investimento", "verba", "página de destino"):
            with self.subTest(ausente=ausente):
                self.assertNotIn(ausente, self.texto.lower())

    def test_tem_tres_paragrafos_com_um_conjunto_so(self):
        self.assertEqual(len(self.texto.split("\n\n")), 3)

    def test_nao_e_longo(self):
        self.assertLess(len(self.texto.split()), 180)

    def test_percentual_do_cliente_nao_tem_casa_decimal(self):
        """"73,28% dos contatos" é precisão que ninguém pediu e que denuncia
        número jogado direto do cálculo para a frase."""
        self.assertIn("73%", self.texto)
        self.assertNotIn("73,28", self.texto)

    def test_concorda_com_o_genero_e_o_numero_do_indicador(self):
        """O indicador vira prosa: plural no volume, singular no custo."""
        self.assertIn("registrou 393 conversas", self.texto)
        self.assertIn("por conversa", self.texto)
        self.assertNotIn("393 conversa,", self.texto)


class TextoDeUmaCampanhaTest(SimpleTestCase):
    """§2 e §18: nada de conjunto, nada de comparação, nada do que ficou
    desmarcado."""

    def _texto(self, linhas, chaves=None):
        return ad.redigir(ad.consolidar(selecionadas(linhas, chaves)))

    def test_o_texto_nunca_diz_conjunto(self):
        """O teste que a especificação pediu por escrito."""
        texto = self._texto([campanha("[LEADS][A][ITU][ABO][01SET25]")])
        self.assertNotIn("conjunto", texto.lower())

    def test_o_texto_nao_conta_as_campanhas_do_arquivo(self):
        linhas = [campanha(f"Campanha {i}", resultados=10 * i)
                  for i in range(1, 10)]
        texto = self._texto(linhas)
        for proibido in ("9 campanhas", "entre as", "9 conjuntos",
                         "a operação rodou"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, texto.lower())

    def test_o_texto_nao_nomeia_a_campanha(self):
        """`[LEADS][CELULAR-BOLETO][BRAGANCA]` é nomenclatura interna e não
        diz nada a quem recebe a mensagem."""
        texto = self._texto([campanha(
            "[LEADS][CELULAR-BOLETO][BRAGANCA][ABO][01SET25]")])
        self.assertNotIn("BRAGANCA", texto)
        self.assertNotIn("[", texto)
        self.assertIn("a campanha", texto)

    def test_com_varias_marcadas_o_texto_vai_para_o_plural(self):
        """A seleção múltipla não pode virar "a campanha registrou" sobre a
        soma de três — e muito menos "os conjuntos", que era o defeito de
        origem desta frente."""
        linhas = [campanha("Campanha A", resultados=30),
                  campanha("Campanha B", resultados=20)]
        texto = self._texto(linhas, ["Campanha A", "Campanha B"])
        self.assertIn("as campanhas selecionadas registraram", texto)
        self.assertNotIn("conjunto", texto.lower())
        self.assertNotIn("2 campanhas", texto)

    def test_com_uma_marcada_o_texto_fica_no_singular(self):
        texto = self._texto([campanha("Campanha A", resultados=30)])
        self.assertIn("a campanha registrou", texto)
        self.assertNotIn("as campanhas", texto)

    def test_campanhas_paradas_nao_viram_diagnostico(self):
        """§25: oito linhas zeradas não são "oito campanhas sem resultado" —
        elas simplesmente não fazem parte da análise."""
        linhas = [campanha("morta-%d" % i, resultados=0, custo=None,
                           alcance=0, impressoes=0, cpm=None, conversas=0,
                           custo_conversa=None, novos=0) for i in range(8)]
        linhas.append(campanha("viva", resultados=557, novos=387))
        texto = self._texto(linhas)
        self.assertNotIn("morta", texto)
        for proibido in ("não registrou", "sem resultado", "revisar"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, texto.lower())



class PeriodoSemResultadoTest(SimpleTestCase):
    """O caso que não pode quebrar nem mentir."""

    def test_zero_resultados_nao_vira_divisao_por_zero(self):
        ag = ad.consolidar([conjunto(resultados=0, custo=None, novos=0,
                                     veiculacao="paused")])
        self.assertIsNone(ag["custo_resultado"])
        self.assertIsNone(ag["custo_conversa"])
        texto = ad.redigir(ag)
        self.assertIn("não registrou conversas", texto)
        self.assertNotIn("registrou 0", texto)

    def test_nao_diagnostica_a_veiculacao(self):
        """A linha "nenhum conjunto aparece ativo" saiu em 30/08/2026: o export
        de campanhas nem traz a coluna de veiculação, e a frase aparecia em
        todo arquivo desse nível."""
        texto = ad.redigir(ad.consolidar([
            conjunto(resultados=0, custo=None, novos=0, veiculacao="paused")]))
        self.assertNotIn("ativo", texto)
        self.assertNotIn("conjunto", texto.lower())

    def test_export_sem_datas_nao_inventa_periodo(self):
        linha = conjunto()
        linha["inicio"] = linha["termino"] = None
        ag = ad.consolidar([linha])
        self.assertEqual(ag["periodo"], "")
        self.assertIn("No período analisado", ad.redigir(ag))


class ClassificacaoTest(SimpleTestCase):
    """A §15: sem metodologia confiável, nenhum selo."""

    def test_nao_classifica_o_periodo(self):
        ag = ad.consolidar(pd.ler_planilha_desempenho(planilha()))
        self.assertIsNone(ad.classificar(ag))

    def test_o_texto_nao_carrega_selo_de_qualidade(self):
        texto = ad.redigir(ad.consolidar(pd.ler_planilha_desempenho(planilha())))
        for selo in ("ÓTIMO", "BOM", "REGULAR", "ATENÇÃO", "MUITO BOM"):
            with self.subTest(selo=selo):
                self.assertNotIn(selo, texto)


# ----------------------------------------------------------------------
# Fluxo
# ----------------------------------------------------------------------
class FluxoDesempenhoTest(TestCase):
    """As duas telas, do envio ao texto copiável."""

    def _enviar(self, arquivo=None):
        return self.client.post("/desempenho/", {
            "cliente": "TIM Brasil",
            "arquivo": arquivo or planilha(),
        }, follow=True)

    def test_o_painel_abre(self):
        r = self.client.get("/desempenho/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Análise de Desempenho")
        self.assertContains(r, "preset DESEMPENHO")

    def test_o_envio_leva_a_analise(self):
        r = self._enviar()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "TIM Brasil")
        self.assertContains(r, "30/07/2026 a 28/08/2026")

    def test_a_tela_mostra_as_nove_metricas(self):
        html = self._enviar().content.decode()
        for valor in ("393", "R$ 4,52", "288", "22.498", "100.012", "4,45",
                      "R$ 17,78"):
            with self.subTest(valor=valor):
                self.assertIn(valor, html)

    def test_a_tela_traz_o_texto_num_campo_copiavel(self):
        html = self._enviar().content.decode()
        self.assertIn('id="txt-desempenho"', html)
        self.assertIn('data-alvo="txt-desempenho"', html)
        self.assertIn("Copiar texto", html)

    def test_a_conferencia_mostra_o_nome_cru(self):
        """A interface mostra o nome que existe no Gerenciador — é por ele que
        o operador confere qual campanha está lendo. O texto do cliente não o
        usa: lá a campanha é "a campanha"."""
        r = self._enviar()
        html = r.content.decode()
        self.assertIn("[ADV+][AUTO][LEADS][V1]", html)
        self.assertNotIn("[ADV+]", r.context["texto"])

    @staticmethod
    def _sem_estilo(html):
        """O HTML sem o <style>, que é inline e traz "Gerar PDF" num
        comentário de CSS — o teste precisa olhar o que é renderizado, não o
        que está escrito na folha de estilo."""
        antes, _, resto = html.partition("<style>")
        return antes + resto.partition("</style>")[2]

    def test_nao_ha_pdf_em_lugar_nenhum_do_fluxo(self):
        """A §10 e a §16: a saída desta frente é texto."""
        painel = self._sem_estilo(self.client.get("/desempenho/").content.decode())
        analise = self._sem_estilo(self._enviar().content.decode())
        # Nenhuma das duas telas escreve "PDF" — nem como botão, nem como
        # nota de rodapé. Quem quer o relatório em páginas é mandado para a
        # outra frente pelo nome dela.
        self.assertNotIn("PDF", painel)
        self.assertNotIn("PDF", analise)
        self.assertIn("use a Análise Geral", analise)

    def test_ha_o_botao_de_nova_analise(self):
        html = self._enviar().content.decode()
        self.assertIn("Nova análise", html)
        self.assertIn('href="/desempenho/"', html)

    def test_arquivo_do_preset_errado_volta_com_as_colunas_que_faltam(self):
        errado = planilha([["Campanha X", "R$ 33,00 Diário", 120.0]],
                          ["Nome da campanha", "Orçamento", "Valor gasto (BRL)"])
        errado.name = "verba.xlsx"
        r = self.client.post("/desempenho/", {"cliente": "TIM",
                                              "arquivo": errado})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "DESEMPENHO")
        # Não avançou: continua na tela de envio, sem sessão gravada. O nome
        # digitado volta preenchido de propósito — obrigar a redigitá-lo
        # puniria o operador duas vezes pelo mesmo engano.
        self.assertTemplateUsed(r, "relatorios/desempenho_index.html")
        self.assertNotIn("desempenho_apex", self.client.session)

    def test_a_analise_sem_sessao_volta_para_o_envio(self):
        r = self.client.get("/desempenho/analise/")
        self.assertRedirects(r, "/desempenho/")

    def test_nao_e_um_xlsx(self):
        arquivo = io.BytesIO(b"nao sou planilha")
        arquivo.name = "relatorio.pdf"
        r = self.client.post("/desempenho/", {"cliente": "TIM",
                                              "arquivo": arquivo})
        self.assertContains(r, "não é um .xlsx")


class SuperficieDaFrenteTest(TestCase):
    """O que esta frente NÃO compartilha com as outras.

    O teste existe porque a tentação é reaproveitar: as três frentes de texto
    parecem a mesma coisa de longe. `analysis/mensagem.py` e `analysis/rules.py`
    classificam o período por faixa de perfil de negócio, e essa faixa não vale
    para este preset.
    """

    def test_o_motor_nao_importa_as_regras_das_outras_frentes(self):
        import relatorios.analise_desempenho as motor
        fonte = io.open(motor.__file__, encoding="utf-8").read()
        self.assertNotIn("from .analysis import rules", fonte)
        self.assertNotIn("from .analysis import mensagem", fonte)
        self.assertNotIn("leitura_rapida", fonte)

    def test_a_frente_tem_o_seu_proprio_parser(self):
        """Ler o preset DESEMPENHO com o mapa do export completo faria
        `Resultados (iniciais)` competir com `Resultados`."""
        from relatorios import parser_xlsx
        self.assertIsNot(pd._COLUNAS_DESEMPENHO, parser_xlsx._COLUNAS)


class PayloadDaIATest(TestCase):
    """§20 a §23: o que o modelo recebe da Análise de Desempenho.

    Nunca o arquivo, nunca outra campanha, e nunca um campo vazio.
    """

    def _payload(self, linhas, chaves=None):
        from relatorios.views_desempenho import _payload
        return _payload(ad.consolidar(selecionadas(linhas, chaves)))

    def test_leva_as_metricas_da_campanha_selecionada(self):
        dados = self._payload([campanha(
            resultados=557, custo=2.68, alcance=25865, impressoes=122901,
            cpm=12.16, novos=387)])
        self.assertEqual(dados["Resultados"], "557")
        self.assertEqual(dados["Alcance"], "25.865")
        self.assertEqual(dados["Impressões"], "122.901")
        self.assertEqual(dados["Novos contatos"], "387")
        self.assertEqual(dados["Percentual de novos contatos"], "69%")

    def test_nunca_manda_none_nan_nem_null(self):
        """§23: um campo vazio no payload convida o modelo a escrever "sem
        dados de frequência", que é informação de operação, não do cliente."""
        casos = [
            [campanha()],
            [campanha(novos=0)],
            [campanha(resultados=0, custo=None, conversas=0,
                      custo_conversa=None, novos=0)],
            [campanha(alcance=0, impressoes=0, cpm=None)],
        ]
        for i, linhas in enumerate(casos):
            with self.subTest(caso=i):
                bruto = json.dumps(self._payload(linhas), ensure_ascii=False)
                for lixo in ("None", "null", "NaN", "nan", "undefined"):
                    self.assertNotIn(lixo, bruto)

    def test_metrica_ausente_sai_do_payload(self):
        dados = self._payload([campanha(novos=0)])
        self.assertNotIn("Novos contatos", dados)
        self.assertNotIn("Percentual de novos contatos", dados)

    def test_o_payload_nao_fala_de_conjuntos_nem_de_outras_campanhas(self):
        """§15 dos testes: a IA não sabe nem precisa saber quantas outras
        campanhas existem no arquivo."""
        linhas = [campanha("Campanha morta-%d" % i, resultados=0, custo=None,
                           alcance=0, impressoes=0, cpm=None, conversas=0,
                           custo_conversa=None, novos=0) for i in range(8)]
        linhas.append(campanha("[LEADS][BRAGANCA][ABO]", resultados=557,
                               novos=387))
        bruto = json.dumps(self._payload(linhas), ensure_ascii=False).lower()
        self.assertNotIn("conjunto", bruto)
        self.assertNotIn("morta", bruto)
        self.assertNotIn("campanhas", bruto)

    def test_o_prompt_proibe_falar_em_conjuntos(self):
        from relatorios import redator_ia
        prompt = redator_ia.PROMPT_REESCRITA_DESEMPENHO
        self.assertIn("Nunca fale em conjunto", prompt)
        self.assertIn("EXCLUSIVAMENTE ao que o operador marcou", prompt)
        # A seleção virou múltipla, e o modelo não pode "corrigir" o número
        # gramatical do motor — nem para o singular, nem para o plural.
        self.assertIn("Mantenha o número gramatical", prompt)
        self.assertIn("Não exponha o nome técnico", prompt)
        self.assertIn("Não altere nenhum número", prompt)


class CasoDeReferenciaTest(SimpleTestCase):
    """§30: o export real da conta TIM-02 Bragança.

    Nove campanhas, oito paradas há meses, uma com 557 conversas. É o arquivo
    que produzia "Entre os 9 conjuntos" e "Conjunto 9 concentrou 100%".
    """

    NUMEROS = dict(resultados=557, custo=2.68231598, alcance=25865,
                   impressoes=122901, frequencia=4.751633, cpm=12.156532,
                   conversas=557, custo_conversa=2.682316, novos=387)

    def _texto(self):
        mortas = [campanha("Engaja-%d" % i, resultados=0, custo=None,
                           alcance=0, impressoes=0, cpm=None, conversas=0,
                           custo_conversa=None, novos=0) for i in range(8)]
        viva = campanha("[LEADS][CELULAR-BOLETO][BRAGANCA][ABO][01SET25]",
                        **self.NUMEROS)
        viva["inicio"], viva["termino"] = "2026-07-31", "2026-08-29"
        return ad.redigir(ad.consolidar(selecionadas(mortas + [viva])))

    def test_traz_os_numeros_da_campanha_selecionada(self):
        texto = self._texto()
        for valor in ("31/07/2026", "29/08/2026", "557", "R$ 2,68", "25.865",
                      "122.901", "4,75", "R$ 12,16", "387", "69%"):
            with self.subTest(valor=valor):
                self.assertIn(valor, texto)

    def test_nao_traz_nada_das_outras_oito(self):
        texto = self._texto()
        for proibido in ("9 conjuntos", "Conjunto 1", "Conjunto 2",
                         "Conjunto 9", "100% do total", "Engaja",
                         "8 campanhas", "conjunto"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido.lower(), texto.lower())

    def test_tem_tres_paragrafos_e_e_curto(self):
        texto = self._texto()
        self.assertEqual(len(texto.split("\n\n")), 3)
        self.assertLess(len(texto.split()), 140)

    def test_nao_diagnostica_causa(self):
        """§12: essas métricas não comprovam saturação, criativo ruim nem
        público errado."""
        texto = self._texto().lower()
        for proibido in ("saturad", "criativo", "público errado", "pausar",
                         "escalar", "campanha vencedora", "atendimento"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, texto)
