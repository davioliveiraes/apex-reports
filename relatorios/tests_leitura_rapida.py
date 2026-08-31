# -*- coding: utf-8 -*-
"""
Testes da Leitura Rápida — a leitura curta sobre o domínio de Desempenho.

A frente não tem parser próprio: ela come o export do preset `DESEMPENHO` pelo
mesmo `parser_desempenho` e consolida pelo mesmo `analise_desempenho`. O que se
testa aqui é a **escolha** — o que entra nos três parágrafos, o que fica de
fora e como nasce a pergunta comercial.
"""

import io
import json
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils.html import strip_tags

from relatorios import analise_desempenho as ad
from relatorios import redator_ia
from relatorios.leitura import imagem, mensagem, resumo
from relatorios.tests_desempenho import CABECALHO, REFERENCIA, planilha

CONVERSA = "actions:onsite_conversion.messaging_conversation_started_7d"


_AUTO = object()


def conjunto(nome="[LEADS][CELULAR][ITU][ABO][01SET25]", resultados=100,
             custo=5.0, alcance=8000, impressoes=30000, cpm=_AUTO,
             conversas=None, custo_conversa=None, novos=60,
             indicador=CONVERSA):
    """Uma linha já parseada — o formato que o parser de desempenho devolve.

    O CPM sai de `custo × resultados ÷ impressões` por padrão, para a linha
    ser internamente coerente. Sem isso a fixture descreveria uma planilha
    impossível: o consolidado de Desempenho reconstrói o gasto pelo CPM (ver o
    cabeçalho de `analise_desempenho`), então um `custo` que não fecha com o
    `cpm` some no caminho — e o teste falharia pela própria incoerência.
    """
    if cpm is _AUTO:
        cpm = ((custo * resultados / impressoes * 1000)
               if custo and resultados and impressoes else 16.67)
    return {
        "inicio": "2026-08-01", "termino": "2026-08-07",
        "conjunto": nome, "veiculacao": "active",
        "resultados": float(resultados), "indicador": indicador,
        "custo_resultado": custo, "alcance": float(alcance),
        "impressoes": float(impressoes), "frequencia": 3.75, "cpm": cpm,
        "conversas": float(resultados if conversas is None else conversas),
        "custo_conversa": custo if custo_conversa is None else custo_conversa,
        "novos_contatos": float(novos),
    }


def ler(linhas):
    """`(estruturado, texto)` — o caminho inteiro do domínio até a mensagem."""
    curto = resumo.montar(ad.consolidar(linhas))
    return curto, mensagem.redigir(curto)


# ----------------------------------------------------------------------
# A saída estruturada
# ----------------------------------------------------------------------
class SaidaEstruturadaTest(SimpleTestCase):
    """§27: os dados antes da string, para nenhuma regra viver no template."""

    def test_o_estruturado_traz_o_que_a_tela_e_o_texto_precisam(self):
        curto, _ = ler([conjunto()])
        for chave in ("periodo", "classificacao", "resultado_principal",
                      "custo_principal", "conversas", "novos_contatos",
                      "alcance", "frequencia", "cpm", "comparativo",
                      "pergunta_comercial"):
            with self.subTest(chave=chave):
                self.assertIn(chave, curto)

    def test_o_periodo_sai_curto_sem_ano(self):
        """Num grupo de WhatsApp o ano ocupa espaço e não informa nada."""
        curto, _ = ler([conjunto()])
        self.assertEqual(curto["periodo"], "01/08 a 07/08")

    def test_consome_o_consolidado_de_desempenho_sem_recalcular(self):
        """§24: frequência não soma, CPM não soma, custo não é média simples —
        e essas regras já estão resolvidas no domínio de Desempenho."""
        linhas = [conjunto(resultados=200, custo=5.0, impressoes=40000,
                           cpm=25.0),
                  conjunto("[B]", resultados=60, custo=12.0, impressoes=18000,
                           cpm=40.0)]
        total = ad.consolidar(linhas)
        curto = resumo.montar(total)
        self.assertEqual(curto["custo_principal"], total["custo_resultado"])
        self.assertEqual(curto["cpm"], total["cpm"])
        self.assertEqual(curto["frequencia"], total["frequencia"])

    def test_nao_classifica_o_periodo(self):
        """§12: `analysis/benchmarks.py` se declara estimativa, não benchmark
        verificado, e depende de um perfil de negócio que esta tela não
        pergunta. Sem régua confiável, nenhum selo."""
        curto, _ = ler([conjunto()])
        self.assertIsNone(curto["classificacao"])
        self.assertIsNone(resumo.classificar(ad.consolidar([conjunto()])))

    def test_a_tela_mostra_quatro_cartoes_no_maximo(self):
        """§11: a leitura rápida é mais simples que a Análise de Desempenho,
        que mostra nove."""
        curto, _ = ler([conjunto()])
        self.assertLessEqual(len(resumo.cartoes(curto)), 4)


# ----------------------------------------------------------------------
# A pergunta comercial
# ----------------------------------------------------------------------
class PerguntaComercialTest(SimpleTestCase):
    """§17 e §19 — o elemento que dá nome ao produto.

    O Meta mostra o contato gerado, não o fechamento. Perguntar é a única
    forma honesta de cruzar tráfego → atendimento → venda.
    """

    def test_com_novos_contatos_pergunta_pelos_contatos(self):
        curto, texto = ler([conjunto(novos=42)])
        self.assertIn("Dos 42 novos contatos gerados nesse período, quantos "
                      "avançaram para venda?", curto["pergunta_comercial"])
        self.assertIn("*Ponto comercial:*", texto)

    def test_sem_novos_contatos_cai_para_conversas(self):
        """§19: o fallback só vale se houver conversa com volume."""
        curto, _ = ler([conjunto(resultados=55, conversas=55, novos=0)])
        self.assertIn("Das 55 conversas iniciadas nesse período, quantas "
                      "resultaram em vendas?", curto["pergunta_comercial"])

    def test_sem_nenhuma_das_duas_a_pergunta_perde_o_numero(self):
        """§19: "Dos 0 novos contatos" seria pior que a pergunta genérica."""
        curto, texto = ler([conjunto(resultados=45, conversas=0,
                                     custo_conversa=None, novos=0,
                                     indicador="actions:lead")])
        self.assertEqual(curto["pergunta_comercial"],
                         "Quantos atendimentos desse período avançaram para "
                         "venda?")
        self.assertNotIn("Dos 0", texto)
        self.assertNotIn("Das 0", texto)

    def test_a_pergunta_nunca_afirma_venda(self):
        """§18: o XLSX não tem essa informação. Nem taxa, nem ROAS, nem
        faturamento, nem ticket."""
        _, texto = ler([conjunto()])
        baixo = texto.lower()
        for proibido in ("vendas foram", "faturamento", "roas", "ticket",
                         "taxa de conversão em venda", "receita"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, baixo)
        self.assertTrue(texto.rstrip().endswith("?"))


# ----------------------------------------------------------------------
# O texto
# ----------------------------------------------------------------------
class TextoDaLeituraTest(SimpleTestCase):
    """§13 a §22."""

    def setUp(self):
        self.curto, self.texto = ler([conjunto()])

    def test_cabecalho_com_titulo_e_periodo(self):
        self.assertTrue(self.texto.startswith(
            "*Leitura do período — 01/08 a 07/08*"))

    def test_tres_paragrafos_e_a_pergunta(self):
        blocos = self.texto.split("\n\n")
        self.assertEqual(len(blocos), 5)          # cabeçalho + 3 + pergunta
        self.assertTrue(blocos[-1].startswith("*Ponto comercial:*"))

    def test_e_curta(self):
        """§21: precisa ser lida de relance dentro de um grupo."""
        self.assertLess(len(self.texto.split()), 110)

    def test_formatacao_de_whatsapp(self):
        """§20: só asterisco simples, sem tabela e sem markdown complexo."""
        for proibido in ("**", "##", "|", "- ", "```", "###"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, self.texto)

    def test_nao_cita_investimento(self):
        """§6: o preset não traz `Valor gasto`. O consolidado reconstrói um
        gasto para ponderar as taxas, e ele não pode vazar para a frase."""
        baixo = self.texto.lower()
        for proibido in ("investimento", "valor gasto", "verba", "investiu",
                         "gasto de"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, baixo)

    def test_a_frequencia_e_relatada_e_nao_julgada(self):
        """§15: "sem saturação" exigiria uma referência que não existe."""
        self.assertIn("frequência de 3,75", self.texto)
        for proibido in ("saturaç", "saturad", "fadiga", "desgast"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, self.texto.lower())

    def test_nao_afirma_causa(self):
        """§16: criativo, público e atendimento são hipóteses que o arquivo
        não distingue entre si."""
        baixo = self.texto.lower()
        for proibido in ("criativo", "público ruim", "atendimento falhou",
                         "anúncio vencedor", "problema no"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, baixo)

    def test_sem_frase_generica_de_ia(self):
        """§22: tom de gestor de tráfego, não de gerador de texto."""
        baixo = self.texto.lower()
        for proibido in ("performance sólida", "promissor",
                         "excelentes resultados", "demonstram uma",
                         "de forma robusta"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, baixo)

    def test_nunca_escreve_none_ou_nan(self):
        """§34, casos 13 e 14 — em todos os caminhos, não só no feliz."""
        casos = [
            [conjunto()],
            [conjunto(novos=0)],
            [conjunto(resultados=0, custo=None, conversas=0,
                      custo_conversa=None, novos=0)],
            [conjunto(alcance=0, impressoes=0, cpm=None)],
            [conjunto(), conjunto("[B]", resultados=40, custo=9.0)],
        ]
        for i, linhas in enumerate(casos):
            _, texto = ler(linhas)
            with self.subTest(caso=i):
                for lixo in ("None", "nan", "NaN", "inf", "R$ 0,00 por"):
                    self.assertNotIn(lixo, texto)

    def test_sem_periodo_o_texto_nao_inventa_data(self):
        linha = conjunto()
        linha["inicio"] = linha["termino"] = None
        curto, texto = ler([linha])
        self.assertEqual(curto["periodo"], "")
        self.assertTrue(texto.startswith("*Leitura do período*"))
        self.assertNotIn("None", texto)


class ParagrafosTest(SimpleTestCase):
    """O que cada parágrafo responde (§14, §15, §16)."""

    def _p(self, linhas):
        _, texto = ler(linhas)
        return texto.split("\n\n")

    def test_p1_traz_resultado_e_custo(self):
        p = self._p([conjunto(resultados=87, custo=6.42, conversas=87)])
        self.assertIn("87 conversas", p[1])
        self.assertIn("R$ 6,42", p[1])

    def test_p1_sem_custo_nao_inventa(self):
        """§34, caso 7."""
        p = self._p([conjunto(resultados=0, custo=None, conversas=0,
                              custo_conversa=None, novos=0)])
        self.assertIn("ainda não registraram conversas", p[1])
        self.assertNotIn("custo médio", p[1])

    def test_p2_traz_entrega_sem_impressoes(self):
        """Alcance responde "quanta gente" e frequência "quantas vezes" — as
        impressões são o produto das duas, e num texto curto o número
        redundante é o primeiro a sair."""
        p = self._p([conjunto()])
        self.assertIn("8.000 pessoas", p[2])
        self.assertIn("frequência", p[2])
        self.assertNotIn("impressões", p[2])

    def test_p2_some_quando_nao_ha_entrega(self):
        """§34, caso 8: sem alcance não há o que dizer sobre entrega."""
        _, texto = ler([conjunto(alcance=0, impressoes=0, cpm=None)])
        self.assertNotIn("A entrega alcançou", texto)

    def test_p3_traz_a_fatia_de_contatos_novos(self):
        p = self._p([conjunto(resultados=100, conversas=100, novos=73)])
        self.assertIn("73 (73%)", p[3])
        self.assertIn("ainda não haviam falado", p[3])

    def test_p3_some_em_vez_de_repetir_numero(self):
        """§21: a tentação era fechar com o custo, mas ele já foi dito no
        primeiro parágrafo. Duas frases e a pergunta é uma leitura completa;
        três com uma repetida, não."""
        _, texto = ler([conjunto(novos=0)])
        blocos = texto.split("\n\n")
        self.assertEqual(len(blocos), 4)          # cabeçalho + 2 + pergunta
        self.assertEqual(texto.count("R$ 5,00"), 1)


class ComparacaoEntreConjuntosTest(SimpleTestCase):
    """§23: UMA informação comparativa, não o relatório completo."""

    def test_um_conjunto_nao_gera_comparativo(self):
        curto, _ = ler([conjunto()])
        self.assertIsNone(curto["comparativo"])

    def test_concentracao_quando_ela_existe(self):
        curto, texto = ler([conjunto(resultados=200, custo=5.0),
                            conjunto("[B]", resultados=40, custo=9.0,
                                     novos=20)])
        self.assertEqual(curto["comparativo"]["tipo"], "concentracao")
        self.assertIn("concentrou a maior parte dos resultados", texto)

    def test_empate_vira_menor_custo_e_nao_concentracao(self):
        """52% contra 48% não é concentração — é empate. Aí o fato útil é
        outro: qual conjunto saiu mais barato."""
        curto, texto = ler([conjunto("[A]", resultados=100, custo=6.0),
                            conjunto("[B]", resultados=90, custo=4.2)])
        self.assertEqual(curto["comparativo"]["tipo"], "menor_custo")
        self.assertIn("menor custo por conversa", texto)
        self.assertNotIn("concentrou", texto)

    def test_so_um_fato_comparativo(self):
        """A comparação completa é da Análise de Desempenho. Repeti-la aqui
        transformaria a leitura rápida no relatório que ela existe para não
        ser."""
        _, texto = ler([conjunto(resultados=200, custo=5.0),
                        conjunto("[B]", resultados=40, custo=9.0, novos=20)])
        self.assertEqual(texto.count("O conjunto "), 1)
        for ausente in ("ponto de atenção", "merece acompanhamento",
                        "não registrou"):
            with self.subTest(ausente=ausente):
                self.assertNotIn(ausente, texto.lower())


# ----------------------------------------------------------------------
# Fluxo
# ----------------------------------------------------------------------
class FluxoLeituraRapidaTest(TestCase):
    """As duas telas, do envio ao texto copiável."""

    def _enviar(self, arquivo=None):
        return self.client.post("/leitura/", {
            "cliente": "TIM Brasil",
            "arquivos": arquivo or planilha(),
        }, follow=True)

    def test_o_painel_abre(self):
        r = self.client.get("/leitura/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Leitura Rápida")
        self.assertContains(r, "preset DESEMPENHO")

    def test_o_envio_leva_a_leitura(self):
        r = self._enviar()
        self.assertContains(r, "TIM Brasil")
        self.assertContains(r, "Leitura do período")

    def test_a_tela_mostra_os_quatro_numeros_e_o_texto(self):
        html = self._enviar().content.decode()
        self.assertIn("393", html)
        self.assertIn("R$ 4,52", html)
        self.assertIn("288", html)
        self.assertIn('id="txt-leitura"', html)
        self.assertIn("Copiar texto", html)
        self.assertIn("Nova leitura", html)

    def test_a_tela_e_mais_enxuta_que_a_analise_de_desempenho(self):
        """§11: sem tabela de conferência, sem diagnóstico, sem os nove
        cartões. O foco é o texto."""
        html = self._enviar().content.decode()
        self.assertNotIn("<table", html)
        self.assertNotIn("Conferência", html)
        self.assertNotIn("Principal ponto de atenção", html)

    def test_nao_ha_pdf_no_fluxo(self):
        # A regra é sobre o que a interface mostra. Procurar no HTML bruto
        # também inspeciona atributos técnicos: um token CSRF aleatório já
        # conteve a sequência "PDF" e fez este teste falhar sem existir PDF
        # em lugar nenhum da tela.
        painel = strip_tags(
            _sem_estilo(self.client.get("/leitura/").content.decode()))
        leitura = strip_tags(_sem_estilo(self._enviar().content.decode()))
        self.assertNotIn("PDF", painel)
        self.assertNotIn("PDF", leitura)

    def test_reusa_a_validacao_da_analise_de_desempenho(self):
        """§29: duas mensagens diferentes para o mesmo arquivo errado
        ensinariam o operador que uma das telas está quebrada."""
        errado = planilha([["Campanha X", "R$ 33,00 Diário", 120.0]],
                          ["Nome da campanha", "Orçamento", "Valor gasto (BRL)"])
        errado.name = "verba.xlsx"
        r = self.client.post("/leitura/", {"cliente": "TIM",
                                           "arquivos": errado})
        self.assertContains(r, "DESEMPENHO")
        self.assertTemplateUsed(r, "relatorios/leitura_index.html")
        self.assertNotIn("leitura_apex", self.client.session)

    def test_colunas_faltando_sao_listadas(self):
        sem_cpm = [c for c in CABECALHO if not c.startswith("CPM")]
        linha = [v for c, v in zip(CABECALHO, REFERENCIA)
                 if not c.startswith("CPM")]
        r = self.client.post("/leitura/", {
            "cliente": "TIM", "arquivos": planilha([linha], sem_cpm)})
        self.assertContains(r, "CPM (custo por 1.000 impressões)")

    def test_a_leitura_sem_sessao_volta_para_o_envio(self):
        self.assertRedirects(self.client.get("/leitura/mensagem/"), "/leitura/")

    def test_nao_e_um_xlsx(self):
        arquivo = io.BytesIO(b"nao sou planilha")
        arquivo.name = "relatorio.pdf"
        r = self.client.post("/leitura/", {"cliente": "TIM",
                                           "arquivos": arquivo})
        self.assertContains(r, "não é .xlsx nem imagem")

    def test_varios_conjuntos_atravessam_o_fluxo(self):
        outro = list(REFERENCIA)
        outro[2] = "[LEADS][CELULAR][SALTO][ABO][13JUL26]"
        outro[4], outro[11] = 40, 40
        html = self._enviar(planilha([REFERENCIA, outro])).content.decode()
        self.assertIn("Leitura do período", html)
        self.assertIn("2 conjuntos", html)


def _sem_estilo(html):
    """O HTML sem o <style>, que é inline e traz "Gerar PDF" num comentário."""
    antes, _, resto = html.partition("<style>")
    return antes + resto.partition("</style>")[2]


class AtalhoNaHomeTest(TestCase):
    """§8 e §9: funcional, compacto, e ainda fora da grade."""

    def _html(self):
        return self.client.get("/").content.decode()

    def test_o_atalho_virou_link(self):
        html = self._html()
        self.assertIn('class="atalho" href="/leitura/"', html)
        # A classe `.atalho.em-breve` continua definida na folha de estilo,
        # guardada para o próximo indisponível — o que precisa ter sumido é a
        # marcação renderizada.
        self.assertNotIn("Em breve", _sem_estilo(html))

    def test_continua_fora_da_grade(self):
        """§8: não pode virar um quinto cartão."""
        html = self._html()
        self.assertLess(html.index('class="atalho"'),
                        html.index('class="frentes"'))
        grade = html.split('class="frentes"')[1]
        self.assertNotIn("Leitura Rápida", grade)
        self.assertEqual(grade.count('class="frente"'), 4)

    def test_a_grade_continua_com_as_quatro_analises(self):
        html = self._html()
        for destino in ("/geral/", "/desempenho/", "/verba/", "/rastreamento/"):
            with self.subTest(destino=destino):
                self.assertIn(f'class="frente" href="{destino}"', html)

    def test_nada_na_home_esta_em_breve(self):
        """§33: as cinco funcionalidades estão de pé — quatro na grade e a
        Leitura Rápida no atalho."""
        self.assertNotIn("em-breve", _sem_estilo(self._html()))


class SuperficieDaLeituraTest(SimpleTestCase):
    """§25: sem segundo parser, sem segunda consolidação."""

    def test_nao_existe_parser_proprio(self):
        for modulo in (resumo, mensagem):
            fonte = io.open(modulo.__file__, encoding="utf-8").read()
            with self.subTest(modulo=modulo.__name__):
                self.assertNotIn("load_workbook", fonte)
                self.assertNotIn("openpyxl", fonte)
                self.assertNotIn("_COLUNAS", fonte)

    def test_a_view_le_pelo_parser_de_desempenho(self):
        from relatorios import views_leitura
        fonte = io.open(views_leitura.__file__, encoding="utf-8").read()
        self.assertIn("from .parser_desempenho import", fonte)
        self.assertIn("analise_desempenho.consolidar", fonte)

    def test_o_texto_nao_calcula_e_o_resumo_nao_redige(self):
        """§26: a regra fica no serviço, não na tela nem no texto."""
        texto = io.open(mensagem.__file__, encoding="utf-8").read()
        dados = io.open(resumo.__file__, encoding="utf-8").read()
        self.assertNotIn("FATIA_DE_CONCENTRACAO", texto)
        self.assertNotIn("*Ponto comercial:*", dados)


class CartoesDaTelaTest(SimpleTestCase):
    """§11: um resumo pequeno, e sem o mesmo número duas vezes."""

    def test_conversa_como_resultado_nao_vira_dois_cartoes(self):
        """Numa campanha de mensagem, "Resultados" e "Conversas por mensagem
        iniciadas" são a MESMA coluna com dois nomes. Lado a lado, a tela
        pareceria mostrar 786 de alguma coisa."""
        curto, _ = ler([conjunto(resultados=393, conversas=393, novos=288)])
        self.assertTrue(curto["resultado_e_conversa"])
        rotulos = [c["rotulo"] for c in resumo.cartoes(curto)]
        self.assertEqual(rotulos,
                         ["Conversas", "Custo por conversa", "Novos contatos"])

    def test_resultado_diferente_de_conversa_mantem_os_dois(self):
        """Conta de leads com campanha de mensagem junto: são números
        diferentes e os dois informam."""
        curto, _ = ler([conjunto(resultados=45, conversas=12,
                                 indicador="actions:lead")])
        self.assertFalse(curto["resultado_e_conversa"])
        rotulos = [c["rotulo"] for c in resumo.cartoes(curto)]
        self.assertIn("Leads", rotulos)
        self.assertIn("Conversas", rotulos)

    def test_a_entrega_fica_na_lateral_e_nao_nos_cartoes(self):
        curto, _ = ler([conjunto()])
        rotulos = [c["rotulo"] for c in resumo.cartoes(curto)]
        for lateral in ("Alcance", "Frequência", "CPM"):
            with self.subTest(lateral=lateral):
                self.assertNotIn(lateral, rotulos)
        self.assertEqual([e["rotulo"] for e in resumo.entrega(curto)],
                         ["Alcance", "Frequência", "CPM"])


# ----------------------------------------------------------------------
# Leitura por print
# ----------------------------------------------------------------------
RESPOSTA_VISAO = json.dumps({"linhas": [{
    "conjunto": "[ADV+][AUTO][LEADS][V1]", "veiculacao": "Ativa",
    "indicador": "Conversas por mensagem iniciadas",
    "resultados": 393, "custo_resultado": 4.52, "alcance": 22498,
    "impressoes": 100012, "frequencia": 4.45, "cpm": 17.78,
    "conversas": 393, "custo_conversa": 4.52, "novos_contatos": 288,
    "inicio": "2026-07-30", "termino": "2026-08-28"}]}, ensure_ascii=False)

# Um PNG de mentira: o parser de imagem nunca abre o arquivo, só o encaminha
# em base64. O que se testa aqui é o contrato com o modelo, não a decodificação
# de imagem — que é da OpenAI.
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _print(nome="print.png", conteudo=_PNG):
    arquivo = io.BytesIO(conteudo)
    arquivo.name = nome
    return arquivo


class ExtracaoDePrintTest(SimpleTestCase):
    """A transcrição vira as MESMAS linhas que o .xlsx produz.

    `_chamar` é o único ponto de I/O do projeto e é sempre patcheado: a suíte
    roda offline e nunca gasta crédito.
    """

    def _extrair(self, resposta=RESPOSTA_VISAO):
        with mock.patch.object(redator_ia, "_chamar",
                               return_value=resposta) as chamar:
            with mock.patch.object(redator_ia, "disponivel",
                                   return_value=True):
                linhas, avisos, erro = imagem.extrair([_print()])
        return linhas, avisos, erro, chamar

    def test_o_print_vira_linha_na_forma_do_parser(self):
        """É o contrato inteiro desta funcionalidade: se a forma bater, nada
        a jusante precisa saber que houve uma imagem."""
        linhas, avisos, erro, _ = self._extrair()
        self.assertIsNone(erro)
        self.assertEqual(linhas[0]["resultados"], 393.0)
        self.assertEqual(linhas[0]["novos_contatos"], 288.0)
        self.assertEqual(linhas[0]["inicio"], "2026-07-30")
        self.assertEqual(avisos, [])

    def test_a_linha_do_print_atravessa_o_pipeline_de_planilha(self):
        linhas, _, _, _ = self._extrair()
        curto = resumo.montar(ad.consolidar(linhas))
        texto = mensagem.redigir(curto)
        self.assertIn("393 conversas", texto)
        self.assertIn("288 novos contatos gerados", texto)

    def test_a_imagem_vai_como_data_uri_no_payload(self):
        _, _, _, chamar = self._extrair()
        mensagens = chamar.call_args[0][0]
        blocos = mensagens[1]["content"]
        self.assertEqual(blocos[1]["type"], "image_url")
        self.assertTrue(
            blocos[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_o_prompt_proibe_estimar_e_calcular(self):
        """As duas regras que separam transcrição de invenção."""
        _, _, _, chamar = self._extrair()
        sistema = chamar.call_args[0][0][0]["content"]
        self.assertIn("Nunca estime", sistema)
        self.assertIn("Nunca calcule um campo a partir de outro", sistema)
        self.assertIn("null", sistema)

    def test_campo_ilegivel_vira_ausente_e_nao_zero(self):
        """`null` é "não deu para ler"; 0 seria "o Meta mediu zero". Confundir
        os dois faria a mensagem afirmar um resultado que ninguém viu."""
        resposta = json.dumps({"linhas": [{
            "resultados": 120, "custo_resultado": None, "cpm": "--",
            "alcance": "", "novos_contatos": 40, "conversas": 120}]})
        linhas, _, erro, _ = self._extrair(resposta)
        self.assertIsNone(erro)
        self.assertIsNone(linhas[0]["custo_resultado"])
        self.assertIsNone(linhas[0]["cpm"])
        self.assertIsNone(linhas[0]["alcance"])

    def test_numeros_em_pt_br_e_com_simbolo(self):
        resposta = json.dumps({"linhas": [{
            "resultados": 1234, "custo_resultado": "R$ 4,52",
            "frequencia": "4,45", "cpm": "17,78", "conversas": 1234}]})
        linhas, _, _, _ = self._extrair(resposta)
        self.assertAlmostEqual(linhas[0]["custo_resultado"], 4.52)
        self.assertAlmostEqual(linhas[0]["frequencia"], 4.45)
        self.assertAlmostEqual(linhas[0]["cpm"], 17.78)

    def test_data_fora_do_iso_nao_vira_periodo(self):
        """"28 de ago" na linha de período seria pior que período nenhum."""
        resposta = json.dumps({"linhas": [{
            "resultados": 10, "conversas": 10,
            "inicio": "30 de jul de 2026", "termino": "28/08"}]})
        linhas, _, _, _ = self._extrair(resposta)
        self.assertIsNone(linhas[0]["inicio"])
        self.assertIsNone(linhas[0]["termino"])

    def test_imagem_que_nao_e_do_gerenciador(self):
        linhas, _, erro, _ = self._extrair(json.dumps({"linhas": []}))
        self.assertIsNone(linhas)
        self.assertIn("Gerenciador de Anúncios", erro)

    def test_linha_sem_numero_nenhum_e_descartada(self):
        """Estrutura sem conteúdo é alucinação de forma, não dado."""
        resposta = json.dumps({"linhas": [{"conjunto": "Campanha X"}]})
        linhas, _, erro, _ = self._extrair(resposta)
        self.assertIsNone(linhas)

    def test_resposta_com_cerca_de_codigo_ainda_e_lida(self):
        cercada = "```json\n" + RESPOSTA_VISAO + "\n```"
        linhas, _, erro, _ = self._extrair(cercada)
        self.assertIsNone(erro)
        self.assertEqual(linhas[0]["resultados"], 393.0)

    def test_resposta_que_nao_e_json_vira_erro_amigavel(self):
        linhas, _, erro, _ = self._extrair("Desculpe, nao consegui ler.")
        self.assertIsNone(linhas)
        self.assertIn(".xlsx", erro)

    def test_sem_chave_de_api_o_print_falha_dizendo_o_caminho(self):
        with mock.patch.object(redator_ia, "disponivel", return_value=False):
            linhas, _, erro = imagem.extrair([_print()])
        self.assertIsNone(linhas)
        self.assertIn("OPENAI_API_KEY", erro)
        self.assertIn(".xlsx", erro)


class CoerenciaDoPrintTest(SimpleTestCase):
    """A aritmética conferindo a aritmética.

    Bater não prova que a transcrição está certa; discordar prova que alguma
    coisa está errada — e é isso que pega o dígito trocado antes de o texto ir
    para o cliente.
    """

    def test_numeros_coerentes_nao_geram_aviso(self):
        self.assertEqual(imagem.conferir([{
            "conjunto": "A", "resultados": 100, "custo_resultado": 5.0,
            "impressoes": 30000, "cpm": 16.67, "alcance": 8000,
            "frequencia": 3.75, "conversas": 100, "novos_contatos": 60}]), [])

    def test_cpm_que_nao_fecha_com_o_custo_vira_aviso(self):
        """Gasto por dois caminhos: 30.000 impressões a R$ 16,67 dão R$ 500;
        100 resultados a R$ 50 dariam R$ 5.000. Um dos dois foi lido errado."""
        avisos = imagem.conferir([{
            "conjunto": "A", "resultados": 100, "custo_resultado": 50.0,
            "impressoes": 30000, "cpm": 16.67}])
        self.assertTrue(any("nao fecham entre si" in a.replace("ã", "a")
                            for a in avisos))

    def test_frequencia_que_nao_bate_com_impressoes_por_alcance(self):
        avisos = imagem.conferir([{
            "conjunto": "A", "impressoes": 30000, "alcance": 8000,
            "frequencia": 12.0}])
        self.assertTrue(any("lida" in a and "bate" in a for a in avisos))

    def test_novos_contatos_acima_das_conversas_e_impossivel(self):
        avisos = imagem.conferir([{
            "conjunto": "A", "conversas": 100, "novos_contatos": 250}])
        self.assertTrue(any("pode acontecer" in a for a in avisos))

    def test_arredondamento_do_gerenciador_nao_vira_aviso(self):
        """O Meta mostra R$ 4,52 para um custo de 4,5237 — a folga existe para
        isso, e sem ela o aviso apareceria em toda leitura."""
        self.assertEqual(imagem.conferir([{
            "conjunto": "A", "resultados": 393, "custo_resultado": 4.52,
            "impressoes": 100012, "cpm": 17.78}]), [])

    def test_campo_ausente_nao_dispara_checagem(self):
        self.assertEqual(imagem.conferir([{"resultados": 100}]), [])


class FluxoDePrintTest(TestCase):
    """As duas telas com print, e o que elas precisam declarar."""

    def _enviar(self, arquivos=None, resposta=RESPOSTA_VISAO):
        with mock.patch.object(redator_ia, "_chamar", return_value=resposta):
            with mock.patch.object(redator_ia, "disponivel",
                                   return_value=True):
                return self.client.post("/leitura/", {
                    "cliente": "TIM Brasil",
                    "arquivos": arquivos or [_print()],
                }, follow=True)

    def test_o_print_gera_a_leitura(self):
        r = self._enviar()
        self.assertContains(r, "TIM Brasil")
        self.assertContains(r, "393")
        self.assertContains(r, "Leitura do período")

    def test_a_tela_declara_que_os_numeros_vieram_de_print(self):
        """A defesa que sobra depois da aritmética: quem confere é o operador,
        e ele só confere se souber que precisa."""
        html = self._enviar().content.decode()
        self.assertIn("transcritos do print", html)
        self.assertIn("Print (transcrito)", html)
        self.assertIn("kpis-curto da-imagem", html)

    def test_com_planilha_a_tela_nao_avisa_nada(self):
        html = self.client.post("/leitura/", {
            "cliente": "TIM", "arquivos": planilha()},
            follow=True).content.decode()
        self.assertNotIn("transcritos do print", html)
        self.assertIn("Planilha (.xlsx)", html)

    def test_avisos_de_incoerencia_aparecem_na_tela(self):
        incoerente = json.dumps({"linhas": [{
            "conjunto": "A", "resultados": 100, "custo_resultado": 50.0,
            "impressoes": 30000, "cpm": 16.67, "conversas": 100,
            "novos_contatos": 60}]})
        html = self._enviar(resposta=incoerente).content.decode()
        self.assertIn("fecham entre si", html)

    def test_varios_prints_num_envio(self):
        r = self._enviar([_print("um.png"), _print("dois.jpg")])
        self.assertContains(r, "Leitura do período")

    def test_planilha_e_print_juntos_sao_recusados(self):
        """Misturar obrigaria a decidir qual vence quando discordarem, e não
        há resposta certa: a planilha é exata, o print é transcrito."""
        r = self.client.post("/leitura/", {
            "cliente": "TIM", "arquivos": [planilha(), _print()]})
        self.assertContains(r, "não os dois")
        self.assertNotIn("leitura_apex", self.client.session)

    def test_arquivo_de_outro_tipo_e_recusado(self):
        outro = io.BytesIO(b"%PDF-1.4")
        outro.name = "relatorio.pdf"
        r = self.client.post("/leitura/", {"cliente": "TIM",
                                           "arquivos": outro})
        self.assertContains(r, "não é .xlsx nem imagem")

    def test_mais_de_quatro_prints(self):
        r = self.client.post("/leitura/", {
            "cliente": "TIM",
            "arquivos": [_print("p%d.png" % i) for i in range(5)]})
        self.assertContains(r, "Máximo de 4 prints")

    def test_a_tela_de_envio_avisa_quando_nao_ha_chave(self):
        with mock.patch.object(redator_ia, "disponivel", return_value=False):
            html = self.client.get("/leitura/").content.decode()
        self.assertIn("por print não funciona", html)


class EnvioVazioTest(TestCase):
    """O buraco que `MultipleFileInput` abre sozinho.

    O widget devolve `files.getlist(nome)`, que é uma LISTA VAZIA quando não
    veio anexo — e lista vazia não dispara o `required` do campo. Sem a guarda
    em `clean_arquivos`, o formulário passava válido sem arquivo e a view
    estourava com 500 ao tentar ler `None`.
    """

    def test_post_sem_anexo_vira_erro_de_formulario(self):
        r = self.client.post("/leitura/", {"cliente": "TIM"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "pelo menos um print")
        self.assertNotIn("leitura_apex", self.client.session)


class NivelDoExportTest(SimpleTestCase):
    """Campanha não é conjunto, e o preset sai das duas abas do Gerenciador.

    Até 31/08/2026 esta frente chamava tudo de conjunto: o cabeçalho dizia
    "1 conjunto" e a frase comparativa dizia "O conjunto LEADS · CELULAR-BOLETO"
    — os dois sobre uma campanha. É o mesmo defeito que a Análise de Desempenho
    corrigiu um dia antes, na frente que ficou de fora naquele dia.
    """

    def _campanha(self, nome, **kw):
        linha = conjunto(nome, **kw)
        linha["campanha"] = linha.pop("conjunto")
        return linha

    def _texto(self, linhas):
        return mensagem.redigir(resumo.montar(ad.consolidar(linhas)))

    def test_uma_campanha_fala_no_singular(self):
        texto = self._texto([self._campanha("[LEADS][ULTRA][ITU][ABO]",
                                            resultados=557)])
        self.assertIn("a campanha gerou 557", texto)
        self.assertNotIn("as campanhas", texto)

    def test_export_de_conjuntos_segue_no_plural_generico(self):
        """Sem coluna de campanha a aplicação não sabe a quantas campanhas
        aquelas linhas pertencem — e chutar o singular seria pior."""
        texto = self._texto([conjunto("[LEADS][A][ITU][ABO]", resultados=60),
                             conjunto("[LEADS][B][ITU][ABO]", resultados=40)])
        self.assertIn("as campanhas geraram 100", texto)

    def test_a_frase_comparativa_chama_campanha_de_campanha(self):
        texto = self._texto([
            self._campanha("[LEADS][A][ITU][ABO]", resultados=90),
            self._campanha("[LEADS][B][ITU][ABO]", resultados=10)])
        self.assertIn("A campanha", texto)
        self.assertNotIn("O conjunto", texto)

    def test_a_frase_comparativa_ainda_diz_conjunto_quando_e_conjunto(self):
        texto = self._texto([conjunto("[LEADS][A][ITU][ABO]", resultados=90),
                             conjunto("[LEADS][B][ITU][ABO]", resultados=10)])
        self.assertIn("O conjunto", texto)

    def test_a_tela_conta_campanhas_e_nao_conjuntos(self):
        curto = resumo.montar(ad.consolidar(
            [self._campanha("[LEADS][A][ITU][ABO]"),
             self._campanha("[LEADS][B][ITU][ABO]")]))
        self.assertEqual(curto["n_campanhas"], 2)
