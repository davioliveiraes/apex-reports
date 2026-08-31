# -*- coding: utf-8 -*-
"""
Testes do bloco *Campanhas incluídas* — o recorte compartilhado.

A Análise Geral sempre teve este bloco; as quatro frentes de texto ganharam-no
em 31/08/2026, com a mesma marcação e o mesmo agrupamento
(`selecao_campanhas.py`). O que este arquivo defende é justamente o
"compartilhado": que as cinco telas recortem uma conta do mesmo jeito, e que a
seleção aconteça ANTES do cálculo em todas elas.

Nada aqui toca a rede — `redator_ia._chamar` é o único ponto de I/O do projeto
e nenhum teste deste arquivo chega perto dele.
"""

import io

from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from relatorios import selecao_campanhas as sc
from relatorios.parser_xlsx import GRUPO_SEM_NOME

from .tests_desempenho import CONVERSA

# O export de desempenho com a coluna de campanha — a aba Campanhas do
# Gerenciador, que é de onde sai o arquivo de referência da conta TIM-02.
CABECALHO = [
    "Início dos relatórios", "Encerramento dos relatórios",
    "Nome da campanha", "Veiculação da campanha",
    "Resultados", "Indicador de resultados", "Custo por resultados",
    "Alcance", "Impressões", "Frequência",
    "CPM (custo por 1.000 impressões) (BRL)",
    "Conversas por mensagem iniciadas",
    "Custo por conversa por mensagem iniciada (BRL)",
    "Novos contatos de mensagem",
]


def linha(nome, resultados=100, alcance=8000, impressoes=30000, cpm=16.67,
          novos=60):
    """Uma linha do export, na ordem de `CABECALHO`."""
    custo = (cpm * impressoes / 1000.0 / resultados) if resultados else None
    return ["2026-08-01", "2026-08-31", nome, "active",
            resultados, CONVERSA, custo, alcance, impressoes,
            (impressoes / alcance) if alcance else None, cpm,
            resultados, custo, novos]


def parada(nome):
    """A campanha que existe no arquivo e não rodou no período — oito das nove
    da conta de referência estão assim."""
    return ["2026-08-01", "2026-08-31", nome, "paused",
            0, CONVERSA, None, 0, 0, None, None, 0, None, 0]


def planilha(linhas):
    wb = Workbook()
    ws = wb.active
    ws.append(list(CABECALHO))
    for l in linhas:
        ws.append(list(l))
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    buffer.name = "desempenho.xlsx"
    return buffer


# Duas campanhas do mesmo produto (mesmo grupo), uma de outro, e uma parada.
ARQUIVO = [
    linha("[LEADS][CELULAR-BOLETO][BRAGANCA][ABO][01SET25]", resultados=300),
    linha("[LEADS][CELULAR-BOLETO][ITU][ABO][01SET25]", resultados=200),
    linha("[LEADS][ULTRA][ITU][ABO][01SET25]", resultados=57),
    parada("[ENGAJA][TESTE][ITU][ABO][01SET25]"),
]

GRUPO_BOLETO = "LEADS · CELULAR-BOLETO"
GRUPO_ULTRA = "LEADS · ULTRA"
GRUPO_ENGAJA = "ENGAJA · TESTE"


# ----------------------------------------------------------------------
# O módulo
# ----------------------------------------------------------------------
class AgrupamentoTest(SimpleTestCase):
    """O mesmo recorte da Análise Geral: os dois primeiros colchetes."""

    def _linhas(self, *nomes):
        return [{"campanha": n} for n in nomes]

    def test_agrupa_pelo_produto_como_a_analise_geral(self):
        """Região e data variam entre unidades do mesmo produto; é por produto
        que se quer recortar, e é o que a outra frente já fazia."""
        grupos = sc.grupos(self._linhas(
            "[LEADS][CELULAR-BOLETO][SALTO][ABO][13JUL26]",
            "[LEADS][CELULAR-BOLETO][ITU][ABO][01SET25]",
            "[LEADS][ULTRA][ABO][24JUL26]"))
        self.assertEqual([g["chave"] for g in grupos],
                         [GRUPO_BOLETO, "LEADS · ULTRA"])
        self.assertEqual(grupos[0]["n_campanhas"], 2)

    def test_mantem_a_ordem_do_arquivo(self):
        """A lista de caixas é uma cópia do que está na planilha. Reordenar
        por volume faria a conferência contra o Gerenciador virar uma caça."""
        grupos = sc.grupos(self._linhas("Zebra", "Alfa", "Meio"))
        self.assertEqual([g["chave"] for g in grupos],
                         ["Zebra", "Alfa", "Meio"])

    def test_nome_fora_do_padrao_vira_grupo_dele_mesmo(self):
        """Pior caso aceitável: o operador escolhe campanha por campanha."""
        grupos = sc.grupos(self._linhas("Engaja-Aberto", "Venda02-Aberto"))
        self.assertEqual([g["chave"] for g in grupos],
                         ["Engaja-Aberto", "Venda02-Aberto"])

    def test_linha_sem_nome_nao_some(self):
        """Descartar em silêncio verba que não dá para atribuir seria pior do
        que mostrar um grupo feio."""
        grupos = sc.grupos(self._linhas("", "Alfa"))
        self.assertEqual(grupos[0]["chave"], GRUPO_SEM_NOME)

    def test_cai_para_o_nome_do_conjunto(self):
        """Export da aba Conjuntos não traz coluna de campanha. Ler só a
        primeira deixava toda linha anônima — o defeito que produzia
        "Conjunto 1"."""
        grupos = sc.grupos([{"conjunto": "[LEADS][CELULAR][ITU][ABO][01SET25]"}])
        self.assertEqual(grupos[0]["chave"], "LEADS · CELULAR")

    def test_le_o_nome_de_onde_o_preset_de_rastreamento_o_guarda(self):
        grupos = sc.grupos([{"campaign_name": "[LEADS][ULTRA][ITU][ABO]"}],
                           campos=sc.NOMES_RASTREAMENTO,
                           entrega=sc.ENTREGA_RASTREAMENTO)
        self.assertEqual(grupos[0]["chave"], GRUPO_ULTRA)


class PadraoDaSelecaoTest(SimpleTestCase):
    """O que já nasce marcado, e por quê."""

    def test_marca_so_o_que_entregou(self):
        """Campanha parada soma zero em tudo e não muda número nenhum — mas
        muda o TEXTO, que passa a falar no plural de operação que não rodou."""
        grupos = sc.grupos([{"campanha": "Viva", "impressoes": 30000},
                            {"campanha": "Morta", "impressoes": 0}])
        self.assertEqual(sc.padrao(grupos), ["Viva"])

    def test_quando_nada_entregou_marca_tudo(self):
        """Uma tela sem nenhuma caixa marcada não é uma leitura, é um beco."""
        grupos = sc.grupos([{"campanha": "A", "impressoes": 0},
                            {"campanha": "B", "impressoes": 0}])
        self.assertEqual(sc.padrao(grupos), ["A", "B"])

    def test_a_verba_marca_tudo_de_propósito(self):
        """Campanha configurada que ainda não gastou continua fazendo parte do
        orçamento do ciclo; desmarcá-la sozinha mudaria o configurado."""
        grupos = sc.grupos([{"campanha": "Gastou", "gasto": 480.0},
                            {"campanha": "Nao gastou", "gasto": 0.0}],
                           entrega=sc.ENTREGA_VERBA)
        self.assertEqual(sc.padrao(grupos, completo=True),
                         ["Gastou", "Nao gastou"])

    def test_a_entrega_de_cada_preset_e_uma_coluna_diferente(self):
        """Impressões no desempenho, cliques no link no rastreamento, valor
        gasto na verba. É a única diferença real entre as frentes."""
        self.assertEqual(
            (sc.ENTREGA_DESEMPENHO, sc.ENTREGA_RASTREAMENTO, sc.ENTREGA_VERBA),
            (("impressoes",), ("link_clicks",), ("gasto",)))


class FiltroTest(SimpleTestCase):
    def test_devolve_so_as_linhas_dos_grupos_marcados(self):
        linhas = [{"campanha": "[LEADS][A][ITU][ABO]"},
                  {"campanha": "[LEADS][A][SALTO][ABO]"},
                  {"campanha": "[LEADS][B][ITU][ABO]"}]
        self.assertEqual(len(sc.filtrar(linhas, ["LEADS · A"])), 2)

    def test_sem_chave_nenhuma_nao_filtra(self):
        """A sessão gravada antes de esta seleção existir segue funcionando
        como sempre funcionou."""
        linhas = [{"campanha": "A"}, {"campanha": "B"}]
        self.assertEqual(len(sc.filtrar(linhas, None)), 2)
        self.assertEqual(len(sc.filtrar(linhas, [])), 2)


# ----------------------------------------------------------------------
# As telas
# ----------------------------------------------------------------------
class BlocoNaTelaTest(TestCase):
    """A Análise de Desempenho, ponta a ponta — a frente onde a seleção mais
    muda o resultado."""

    def _enviar(self, linhas=ARQUIVO):
        self.client.post("/desempenho/",
                         {"cliente": "TIM Bragança", "arquivo": planilha(linhas)})
        return self.client.get("/desempenho/analise/")

    def test_o_bloco_aparece_com_a_marcacao_da_analise_geral(self):
        html = self._enviar().content.decode()
        self.assertIn("Campanhas incluídas", html)
        self.assertIn('class="grupo-row"', html)
        self.assertIn('name="campanhas"', html)
        self.assertIn("Aplicar seleção", html)

    def test_um_grupo_so_nao_desenha_caixa_nenhuma(self):
        """Uma caixa marcada sozinha não é escolha, é ruído na tela — mesma
        regra do `_ComCampanhas` da Análise Geral."""
        html = self._enviar([linha("[LEADS][ULTRA][ITU][ABO]")]).content.decode()
        self.assertNotIn("Campanhas incluídas", html)

    def test_a_campanha_parada_vem_desmarcada_e_avisada(self):
        r = self._enviar()
        marcadas = {g["chave"] for g in r.context["grupos_campanha"]
                    if g["marcada"]}
        self.assertEqual(marcadas, {GRUPO_BOLETO, GRUPO_ULTRA})
        self.assertIn("sem entrega no período", r.content.decode())

    def test_o_padrao_soma_so_o_que_entregou(self):
        """As três vivas: 300 + 200 + 57."""
        self.assertEqual(self._enviar().context["metricas"][0]["valor"], "557")

    def test_aplicar_selecao_refaz_os_numeros(self):
        self._enviar()
        r = self.client.post("/desempenho/analise/",
                             {"aplicar_campanhas": "1",
                              "campanhas": [GRUPO_ULTRA]})
        self.assertEqual(r.context["metricas"][0]["valor"], "57")
        self.assertIn("a campanha registrou 57", r.context["texto"])

    def test_a_selecao_sobrevive_ao_f5(self):
        """Ela vai para a sessão, como o resto do estado desta frente."""
        self._enviar()
        self.client.post("/desempenho/analise/",
                         {"aplicar_campanhas": "1", "campanhas": [GRUPO_ULTRA]})
        r = self.client.get("/desempenho/analise/")
        self.assertEqual(r.context["metricas"][0]["valor"], "57")

    def test_duas_marcadas_somam_e_o_texto_vai_ao_plural(self):
        self._enviar()
        r = self.client.post("/desempenho/analise/",
                             {"aplicar_campanhas": "1",
                              "campanhas": [GRUPO_BOLETO, GRUPO_ULTRA]})
        texto = r.context["texto"]
        self.assertIn("as campanhas selecionadas registraram 557", texto)
        self.assertNotIn("conjunto", texto.lower())

    def test_desmarcar_tudo_e_recusado_sem_apagar_a_analise(self):
        """Desmarcar tudo não é "todas as campanhas" — é uma tela sem análise
        nenhuma, e o silêncio faria parecer que o clique não funcionou."""
        self._enviar()
        r = self.client.post("/desempenho/analise/", {"aplicar_campanhas": "1"})
        self.assertContains(r, sc.ERRO_VAZIO)
        self.assertEqual(r.context["metricas"][0]["valor"], "557")

    def test_grupo_inventado_no_post_e_ignorado(self):
        """O `value` das caixas chega do cliente e não é confiável."""
        self._enviar()
        r = self.client.post("/desempenho/analise/",
                             {"aplicar_campanhas": "1",
                              "campanhas": ["grupo-que-nao-existe"]})
        self.assertContains(r, sc.ERRO_VAZIO)

    def test_aplicar_selecao_descarta_a_reescrita_da_ia(self):
        """Aquele texto foi escrito sobre outros números; deixá-lo na tela é
        oferecer a leitura de uma coisa como se fosse de outra."""
        self._enviar()
        sessao = self.client.session
        sessao["desempenho_apex"] = dict(sessao["desempenho_apex"],
                                         texto_ia="Texto da IA")
        sessao.save()
        r = self.client.post("/desempenho/analise/",
                             {"aplicar_campanhas": "1",
                              "campanhas": [GRUPO_ULTRA]})
        self.assertNotIn("Texto da IA", r.content.decode())
        self.assertTrue(r.context["do_motor"])

    def test_o_que_saiu_nao_chega_ao_payload_da_ia(self):
        """A seleção acontece antes de qualquer conta — filtrar depois seria
        filtrar a exibição de um número já calculado com o arquivo inteiro."""
        from relatorios import analise_desempenho as ad
        from relatorios.views_desempenho import _payload
        linhas = sc.filtrar(
            [{"campanha": "[LEADS][ULTRA][ITU][ABO]", "resultados": 57.0,
              "impressoes": 30000.0, "cpm": 16.67, "indicador": CONVERSA},
             {"campanha": "[LEADS][CELULAR-BOLETO][ITU][ABO]",
              "resultados": 500.0, "impressoes": 90000.0, "cpm": 16.67,
              "indicador": CONVERSA}],
            [GRUPO_ULTRA])
        self.assertEqual(_payload(ad.consolidar(linhas))["Resultados"], "57")


class BlocoNasQuatroFrentesTest(TestCase):
    """O mesmo bloco nas quatro telas de texto.

    O teste existe porque a tentação, com quatro frentes parecidas, é resolver
    numa e esquecer as outras três — foi assim que a Análise de Desempenho
    passou meses com um `<select>` que não se parecia com nada no produto.
    """

    def test_as_quatro_telas_incluem_o_mesmo_trecho(self):
        alvo = '{% include "relatorios/_campanhas_incluidas.html"'
        for tela in ("desempenho_analise", "rastreamento_analise",
                     "leitura_mensagem", "verba_fechamento"):
            with self.subTest(tela=tela):
                caminho = f"relatorios/templates/relatorios/{tela}.html"
                self.assertIn(alvo, io.open(caminho, encoding="utf-8").read())

    def test_as_quatro_views_recortam_antes_de_calcular(self):
        """`aplicar` devolve as linhas já filtradas; chamá-la depois da
        consolidação seria recortar um número que já somou o arquivo todo."""
        for modulo in ("views_desempenho", "views_rastreamento",
                       "views_leitura", "views_verba"):
            with self.subTest(modulo=modulo):
                fonte = io.open(f"relatorios/{modulo}.py",
                                encoding="utf-8").read()
                self.assertIn("selecao_campanhas.aplicar(", fonte)

    def test_a_leitura_rapida_recorta_igual(self):
        html = self._leitura().content.decode()
        self.assertIn("Campanhas incluídas", html)
        self.assertIn(GRUPO_ULTRA, html)

    def test_a_leitura_rapida_aplica_a_selecao(self):
        self._leitura()
        r = self.client.post("/leitura/mensagem/",
                             {"aplicar_campanhas": "1",
                              "campanhas": [GRUPO_ULTRA]})
        self.assertEqual(r.context["cartoes"][0]["valor"], "57")

    def _leitura(self):
        self.client.post("/leitura/", {"cliente": "TIM Bragança",
                                       "arquivos": planilha(ARQUIVO)})
        return self.client.get("/leitura/mensagem/")

    def test_o_rastreamento_recorta_igual(self):
        """O preset é outro e a coluna do nome também; o bloco é o mesmo."""
        from .tests_rastreamento import CABECALHO as CAB_R
        from .tests_rastreamento import linha as anuncio, planilha as xlsx_r
        anuncios = [anuncio("[LEADS][ULTRA][ITU][ABO]", cliques=400),
                    anuncio("[LEADS][CELULAR-BOLETO][ITU][ABO]", cliques=182)]
        self.client.post("/rastreamento/",
                         {"cliente": "TIM", "arquivo": xlsx_r(anuncios, CAB_R)})
        r = self.client.get("/rastreamento/analise/")
        self.assertContains(r, "Campanhas incluídas")

        depois = self.client.post("/rastreamento/analise/",
                                  {"aplicar_campanhas": "1",
                                   "campanhas": [GRUPO_ULTRA]})
        self.assertEqual(depois.context["n_anuncios"], 1)

    def test_a_verba_recorta_igual_e_o_gasto_sai_junto(self):
        """A campanha que sai do fechamento leva o gasto dela junto — é o que
        permite tirar do ciclo uma campanha que não está no contrato."""
        from .tests_verba import CAMPANHAS, _anexo
        self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": "990,00",
            "periodicidade": "mensal", "estrutura": "cbo",
            "arquivo": _anexo("campanhas.xlsx", CAMPANHAS)})
        r = self.client.get("/verba/fechamento/")
        self.assertContains(r, "Campanhas incluídas")
        # As duas nascem marcadas aqui, ao contrário das frentes de texto.
        self.assertEqual([g["marcada"] for g in r.context["grupos_campanha"]],
                         [True, True])
        self.assertEqual(r.context["calc"]["gasto"], 740.0)

        depois = self.client.post("/verba/fechamento/",
                                  {"aplicar_campanhas": "1",
                                   "campanhas": ["LEADS · CELULAR"]})
        self.assertEqual(depois.context["calc"]["gasto"], 480.0)
