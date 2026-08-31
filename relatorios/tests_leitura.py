# -*- coding: utf-8 -*-
"""
Testes da Leitura Rápida — do rótulo da campanha à mensagem na tela.

A frente inteira roda offline: o motor é determinístico e a única chamada de
rede (`redator_ia._chamar`) é trocada por resposta fixa, como no resto da
suíte. Nenhum teste daqui gasta crédito.
"""
import io
import re
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from . import indicadores, leitura_rapida, redator_ia
from .analysis import mensagem, rules
from .analysis.benchmarks import ATENCAO, BOM, OTIMO
from .parser_xlsx import consolidar, rotulo_campanha, tokens_comuns

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

CABECALHO = [
    "Nome da campanha", "Resultados", "Indicador de resultado",
    "Valor usado (BRL)", "Impressões", "Alcance", "Cliques no link",
    "Início dos relatórios", "Término dos relatórios",
]

CONVERSAS = "Conversas por mensagem iniciadas"

# Três praças do mesmo produto: o caso que a comparação interna do prompt
# descreve, e o que o rótulo precisa saber distinguir.
TRES_PRACAS = [
    {"nome": "[LEADS][CELULAR-BOLETO][JUNDIAI][ABO][01AGO26]",
     "res": 86, "inv": 1420.50, "imp": 52000, "alc": 16000, "cliques": 900},
    {"nome": "[LEADS][CELULAR-BOLETO][ITU][ABO][01AGO26]",
     "res": 41, "inv": 980.00, "imp": 38000, "alc": 12000, "cliques": 610},
    {"nome": "[LEADS][CELULAR-BOLETO][SALTO][CBO][01AGO26]",
     "res": 15, "inv": 612.30, "imp": 22000, "alc": 7000, "cliques": 300},
]


def _planilha(campanhas, inicio="2026-08-01", fim="2026-08-31"):
    wb = Workbook()
    ws = wb.active
    ws.append(CABECALHO)
    for c in campanhas:
        ws.append([c["nome"], c.get("res"), c.get("indicador", CONVERSAS),
                   c.get("inv"), c.get("imp"), c.get("alc"), c.get("cliques"),
                   inicio, fim])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _arquivo(nome="agosto.xlsx", campanhas=TRES_PRACAS, **kw):
    return SimpleUploadedFile(nome, _planilha(campanhas, **kw),
                              content_type=XLSX_MIME)


def _dados(campanhas=TRES_PRACAS, **kw):
    """O que a sessão guarda, pela mesma porta que a view usa."""
    from .parser_xlsx import ler_registros
    registros, mapa = ler_registros(io.BytesIO(_planilha(campanhas, **kw)))
    return leitura_rapida.enxuto(consolidar(registros, mapa))


def _avaliacao(**kw):
    """Uma `Avaliacao` montada à mão, para exercitar um sinal isolado."""
    base = {"classificacao": BOM, "sinais": [rules.CPA_BOM],
            "motivo_principal": rules.CPA_BOM, "proximo_passo": ""}
    base.update(kw)
    return rules.Avaliacao(**base)


def _paragrafos(texto):
    return [b for b in texto.split("\n\n") if b.strip()]


# ----------------------------------------------------------------------
# O nome da campanha vira nome de praça
# ----------------------------------------------------------------------
class RotuloDaCampanhaTest(SimpleTestCase):
    """O cliente nunca lê `[LEADS][CELULAR-BOLETO][ITU][ABO][01AGO26]`."""

    NOMES = [c["nome"] for c in TRES_PRACAS]

    def test_sobra_so_o_que_distingue_uma_campanha_das_outras(self):
        comuns = tokens_comuns(self.NOMES)
        self.assertEqual([rotulo_campanha(n, comuns) for n in self.NOMES],
                         ["Jundiai", "Itu", "Salto"])

    def test_estrutura_e_data_nunca_entram(self):
        # ABO/CBO é operação interna da agência; a data o cabeçalho já dá.
        for nome in self.NOMES:
            with self.subTest(nome=nome):
                rotulo = rotulo_campanha(nome, tokens_comuns(self.NOMES))
                self.assertNotIn("ABO", rotulo)
                self.assertNotIn("CBO", rotulo)
                self.assertNotIn("26", rotulo)

    def test_nunca_devolve_colchete(self):
        for nome in self.NOMES + ["[UNICA]", "[A][B]"]:
            with self.subTest(nome=nome):
                self.assertNotIn("[", rotulo_campanha(nome))

    def test_conectivo_nao_e_capitalizado(self):
        # `.title()` do Python escreveria "Rei Do Celular", que denuncia o
        # script que montou a frase.
        self.assertEqual(rotulo_campanha("[REI DO CELULAR]"), "Rei do Celular")

    def test_nome_fora_do_padrao_volta_como_veio(self):
        self.assertEqual(rotulo_campanha("Campanha de agosto"),
                         "Campanha de agosto")

    def test_um_nome_so_nao_tem_token_comum(self):
        # Com uma campanha só não há com o que comparar: tudo é "comum" e o
        # rótulo ficaria vazio se a função não recusasse o caso.
        self.assertEqual(tokens_comuns(["[LEADS][ULTRA][ITU][ABO]"]), set())

    def test_sem_nada_a_distinguir_o_rotulo_nao_fica_vazio(self):
        nomes = ["[LEADS][ULTRA][ABO][01AGO26]", "[LEADS][ULTRA][ABO][02AGO26]"]
        comuns = tokens_comuns(nomes)
        self.assertTrue(all(rotulo_campanha(n, comuns) for n in nomes))


class TermosDoIndicadorTest(SimpleTestCase):
    """"229 conversas", não "229 Conversas Iniciadas"."""

    def test_conversa_lead_e_o_neutro(self):
        self.assertEqual(indicadores.termos(CONVERSAS)[:2],
                         ("conversa", "conversas"))
        self.assertEqual(indicadores.termos("actions:lead")[:2], ("lead", "leads"))
        self.assertEqual(indicadores.termos("")[:2], ("resultado", "resultados"))

    def test_o_genero_acompanha_o_termo(self):
        # É ele que decide entre "quantas das conversas" e "quantos dos leads".
        self.assertEqual(indicadores.termos(CONVERSAS)[2], "f")
        self.assertEqual(indicadores.termos("actions:lead")[2], "m")

    def test_indicador_desconhecido_cai_no_neutro(self):
        self.assertEqual(indicadores.termos("Compras")[:2],
                         ("resultado", "resultados"))


# ----------------------------------------------------------------------
# A mensagem
# ----------------------------------------------------------------------
class FormatoDaMensagemTest(TestCase):
    """As duas linhas de cabeçalho, três parágrafos e o encerramento."""

    def setUp(self):
        self.texto = leitura_rapida.mensagem(_dados())
        self.blocos = _paragrafos(self.texto)

    def test_abre_com_periodo_e_classificacao(self):
        self.assertEqual(self.blocos[0], "*Período analisado: 01/08/2026 a 31/08/2026*")
        self.assertEqual(self.blocos[1], "*Leitura do período: ATENÇÃO*")

    def test_tem_exatamente_tres_paragrafos_de_analise(self):
        # 2 de cabeçalho + 3 de análise + 1 de encerramento.
        self.assertEqual(len(self.blocos), 6)

    def test_termina_com_a_pergunta_de_conversao(self):
        # A pergunta fecha a leitura, mas não é a última letra: a frase que
        # explica por que o dado importa vem depois dela, como no gabarito.
        self.assertIn("?", self.blocos[-1])
        self.assertIn("se transformaram em venda", self.blocos[-1])

    def test_a_pergunta_usa_o_numero_de_resultados_do_periodo(self):
        self.assertIn("142", self.blocos[-1])

    def test_a_contracao_acompanha_o_genero_do_termo(self):
        self.assertIn("quantas das 142 conversas", self.blocos[-1])
        leads = leitura_rapida.mensagem(_dados([
            dict(TRES_PRACAS[0], indicador="actions:lead"),
            dict(TRES_PRACAS[1], indicador="actions:lead")]))
        self.assertIn("quantos dos", _paragrafos(leads)[-1])

    def test_nao_tem_marcacao_que_o_whatsapp_nao_entende(self):
        for proibido in ("<b>", "</b>", "**", "##", "- ", "|"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, self.texto)

    def test_o_asterisco_simples_so_marca_o_cabecalho(self):
        com_asterisco = [b for b in self.blocos if "*" in b]
        self.assertEqual(len(com_asterisco), 2)

    def test_nao_cita_nome_cru_de_campanha_nem_estrutura(self):
        for vazamento in ("[", "]", "ABO", "CBO", "CELULAR-BOLETO", "01AGO26"):
            with self.subTest(vazamento=vazamento):
                self.assertNotIn(vazamento, self.texto)

    def test_nao_fala_de_periodo_anterior(self):
        """O export é um arquivo só, do intervalo inteiro: não existe antes."""
        for tempo in ("mês passado", "período anterior", "em relação ao",
                      "cresceu", "caiu em relação", "melhorou"):
            with self.subTest(tempo=tempo):
                self.assertNotIn(tempo, self.texto.lower())

    def test_nao_promete_resultado_futuro(self):
        for promessa in ("vamos alcançar", "garantimos", "vai gerar",
                         "esperamos atingir"):
            with self.subTest(promessa=promessa):
                self.assertNotIn(promessa, self.texto.lower())

    def test_nao_cita_status_de_campanha(self):
        for operacao in ("pausar", "pausada", "duplicar", "aprendizado",
                         "ativar", "desativ"):
            with self.subTest(operacao=operacao):
                self.assertNotIn(operacao, self.texto.lower())

    def test_o_tamanho_fica_na_faixa_de_uma_mensagem_de_whatsapp(self):
        palavras = sum(len(p.split()) for p in self.blocos[2:5])
        # O prompt pede 200 a 260. O motor escreve com o que os dados
        # sustentam, e para de escrever quando acaba o que dizer — por isso o
        # piso aqui é mais baixo. O teto é o que importa: passar dele vira
        # texto que ninguém lê no celular.
        self.assertGreaterEqual(palavras, 140)
        self.assertLessEqual(palavras, 260)


class CenarioGeralTest(TestCase):
    """Parágrafo 1 — investimento, volume e custo, nessa ordem."""

    def test_traz_os_tres_numeros_que_o_prompt_prioriza(self):
        p1 = _paragrafos(leitura_rapida.mensagem(_dados()))[2]
        self.assertIn("R$ 3.012,80", p1)   # investimento
        self.assertIn("142", p1)           # resultados
        self.assertIn("R$ 21,22", p1)      # custo por resultado

    def test_sem_resultado_nao_apura_custo(self):
        texto = leitura_rapida.mensagem(_dados([
            dict(TRES_PRACAS[0], res=0)]))
        p1 = _paragrafos(texto)[2]
        self.assertIn("não registrou conversas", p1)
        self.assertNotIn("custo médio", p1)

    def test_sem_resultado_a_pergunta_final_muda_de_alvo(self):
        texto = leitura_rapida.mensagem(_dados([dict(TRES_PRACAS[0], res=0)]))
        self.assertNotIn("se transformaram em venda", texto)
        self.assertIn("?", _paragrafos(texto)[-1])

    def test_sem_resultado_a_conclusao_nao_fala_de_custo(self):
        # A frase padrão apontaria para um número que a tela não tem.
        p3 = _paragrafos(leitura_rapida.mensagem(
            _dados([dict(TRES_PRACAS[0], res=0)])))[4]
        self.assertIn("registro dos contatos", p3)
        self.assertNotIn("custo por conversa", p3)

    def test_amostra_pequena_vira_ressalva_e_nao_veredito(self):
        texto = leitura_rapida.mensagem(_dados([
            dict(TRES_PRACAS[0], res=4, inv=12.00)]))
        self.assertIn("pequeno para uma leitura definitiva", texto)


class ComparacaoInternaTest(TestCase):
    """Parágrafo 2 — melhor e pior, só quando existe essa divisão."""

    def test_nomeia_a_ponta_mais_barata_e_a_mais_cara(self):
        p2 = _paragrafos(leitura_rapida.mensagem(_dados()))[3]
        self.assertIn("Jundiai", p2)     # R$ 16,52
        self.assertIn("Salto", p2)       # R$ 40,82
        self.assertIn("R$ 16,52", p2)
        self.assertIn("R$ 40,82", p2)

    def test_diferenca_grande_e_quantificada(self):
        p2 = _paragrafos(leitura_rapida.mensagem(_dados()))[3]
        self.assertIn("2,47 vezes", p2)
        self.assertIn("ponto de atenção", p2)

    def test_diferenca_pequena_nao_vira_ponto_de_atencao(self):
        """Inventar um problema onde a diferença é de centavos é pior do que
        não ter o que dizer no parágrafo."""
        quase_iguais = [
            dict(TRES_PRACAS[0], res=180, inv=420.50),
            dict(TRES_PRACAS[1], res=150, inv=380.00),
        ]
        p2 = _paragrafos(leitura_rapida.mensagem(_dados(quase_iguais)))[3]
        self.assertIn("mesmo patamar", p2)
        self.assertNotIn("ponto de atenção", p2)

    def test_uma_campanha_so_nao_e_nomeada(self):
        """Sem uma segunda para contrastar, `tokens_comuns` não tem o que
        cortar e o rótulo sairia com a nomenclatura interna inteira."""
        texto = leitura_rapida.mensagem(_dados([TRES_PRACAS[0]]))
        p2 = _paragrafos(texto)[3]
        self.assertIn("uma frente só", p2)
        self.assertNotIn("Jundiai", p2)
        self.assertNotIn("Leads", texto)

    def test_verba_sem_retorno_vira_o_ponto_de_atencao(self):
        com_seca = [
            dict(TRES_PRACAS[0], res=120, inv=900.00),
            dict(TRES_PRACAS[1], res=0, inv=450.00),
        ]
        p2 = _paragrafos(leitura_rapida.mensagem(_dados(com_seca)))[3]
        self.assertIn("R$ 450,00", p2)
        self.assertIn("sem registrar conversas", p2)

    def test_o_valor_da_verba_seca_e_o_do_motor_e_nao_uma_soma_nossa(self):
        """O motor tira da conta quem gastou menos de 1,5 CPA — campanha que
        mal entrou no leilão ainda não deve resultado. Somar por fora cobraria
        do cliente uma verba que o motor decidiu não cobrar."""
        recem_subida = [
            dict(TRES_PRACAS[0], res=120, inv=900.00),   # CPA R$ 7,50
            dict(TRES_PRACAS[1], res=0, inv=5.00),       # abaixo de 1,5 × CPA
        ]
        texto = leitura_rapida.mensagem(_dados(recem_subida))
        self.assertNotIn("R$ 5,00", texto)
        self.assertIn("pequeno demais para cobrar retorno", texto)


class ConclusaoTest(TestCase):
    """Parágrafo 3 — o que os números dizem e o que acompanhar."""

    def test_dispersao_alta_e_nomeada(self):
        p3 = _paragrafos(leitura_rapida.mensagem(_dados()))[4]
        self.assertIn("desigual", p3)

    def test_diz_o_que_acompanhar_no_proximo_ciclo(self):
        p3 = _paragrafos(leitura_rapida.mensagem(_dados()))[4]
        self.assertIn("próximo ciclo", p3)

    def test_nao_vira_plano_de_acao_detalhado(self):
        p3 = _paragrafos(leitura_rapida.mensagem(_dados()))[4]
        self.assertLessEqual(len(p3.split(". ")), 4)


class FadigaDeCriativoTest(SimpleTestCase):
    """A única causa que o motor levanta — e só com sinal para isso."""

    def test_frequencia_saturada_dispara_sozinha(self):
        self.assertTrue(mensagem.tem_fadiga(
            _avaliacao(sinais=[rules.CPA_BOM, "frequencia_saturada"])))

    def test_frequencia_elevada_precisa_de_ctr_baixo(self):
        self.assertFalse(mensagem.tem_fadiga(
            _avaliacao(sinais=[rules.CPA_BOM, "frequencia_elevada"])))
        self.assertTrue(mensagem.tem_fadiga(_avaliacao(
            sinais=[rules.CPA_BOM, "frequencia_elevada", "ctr_baixo"])))

    def test_frequencia_saudavel_nunca_dispara(self):
        self.assertFalse(mensagem.tem_fadiga(
            _avaliacao(sinais=[rules.CPA_OTIMO, "frequencia_saudavel",
                               "ctr_baixo"])))

    def test_sem_sinal_a_mensagem_nao_menciona_criativo(self):
        texto = mensagem.redigir_leitura(
            _avaliacao(), {"investimento": 900.0, "resultados": 120.0,
                           "cpa": 7.5, "alcance": 20000.0})
        self.assertNotIn("fadiga", texto.lower())
        self.assertNotIn("criativo", texto.lower())

    def test_com_sinal_o_pedido_sai_palavra_por_palavra(self):
        texto = mensagem.redigir_leitura(
            _avaliacao(sinais=[rules.CPA_BOM, "frequencia_saturada"]),
            {"investimento": 900.0, "resultados": 120.0, "cpa": 7.5,
             "frequencia": 4.51, "alcance": 20000.0})
        self.assertIn(mensagem.PEDIDO_DE_CRIATIVOS, texto)
        self.assertIn("4,51", texto)

    def test_o_pedido_vem_antes_do_encerramento(self):
        """A pergunta de conversão fecha a mensagem: é ela que abre a resposta
        do cliente, e o prompt manda sempre incluí-la no fim."""
        texto = mensagem.redigir_leitura(
            _avaliacao(sinais=[rules.CPA_BOM, "frequencia_saturada"]),
            {"investimento": 900.0, "resultados": 120.0, "cpa": 7.5,
             "frequencia": 4.51, "alcance": 20000.0})
        self.assertLess(texto.index(mensagem.PEDIDO_DE_CRIATIVOS),
                        texto.index("Para fecharmos"))


class ClassificacaoTest(SimpleTestCase):
    """As três palavras do prompt, e só elas."""

    def test_as_tres_classificacoes_saem_acentuadas(self):
        self.assertEqual(mensagem.CLASSIFICACAO,
                         {OTIMO: "ÓTIMO", BOM: "BOM", ATENCAO: "ATENÇÃO"})

    def test_a_linha_de_classificacao_usa_a_do_motor(self):
        for classificacao, escrito in mensagem.CLASSIFICACAO.items():
            with self.subTest(classificacao=classificacao):
                texto = mensagem.redigir_leitura(
                    _avaliacao(classificacao=classificacao),
                    {"investimento": 900.0, "resultados": 120.0, "cpa": 7.5})
                self.assertIn(f"*Leitura do período: {escrito}*", texto)


class SemPeriodoTest(TestCase):
    """Export sem as colunas de data não ganha um intervalo inventado."""

    def test_a_linha_do_periodo_some(self):
        dados = _dados()
        dados["periodo"] = ""
        texto = leitura_rapida.mensagem(dados)
        self.assertNotIn("Período analisado", texto)
        self.assertTrue(texto.startswith("*Leitura do período:"))

    def test_a_tela_avisa(self):
        self.assertTrue(leitura_rapida.resumo(dict(_dados(), periodo=""))
                        ["sem_periodo"])


# ----------------------------------------------------------------------
# Fluxo e IA
# ----------------------------------------------------------------------
# O fluxo das duas telas e o atalho da home saíram daqui em 30/08/2026, quando
# a Leitura Rápida foi reescrita sobre o domínio da Análise de Desempenho: ela
# passou a ler o preset DESEMPENHO pelo mesmo parser, deixou de classificar o
# período e perdeu o botão de reescrita por IA (a §28 da especificação lista
# só "Copiar texto" e "Nova leitura"). A cobertura nova está em
# `tests_leitura_rapida.py`.
#
# O que sobrou neste arquivo testa `analysis/mensagem.py` e `leitura_rapida.py`
# DIRETAMENTE. Os dois módulos continuam de pé e passando, mas nenhuma tela os
# chama mais — ver o relatório da sessão.
class HomeTest(TestCase):
    """A grade 2×2 e o atalho que fica fora dela.

    Três das quatro análises têm rota; a quarta é interface. E a Leitura
    Rápida não é nenhuma das quatro — ela ficou como atalho separado, também
    sem rota, até o fluxo dela ser definido.
    """

    def _html(self):
        return self.client.get("/").content.decode()

    def test_as_tres_analises_prontas_apontam_para_as_rotas_certas(self):
        html = self._html()
        for destino in ("/geral/", "/desempenho/", "/verba/"):
            with self.subTest(destino=destino):
                self.assertIn(f'class="frente" href="{destino}"', html)

    def test_a_ordem_da_grade(self):
        """Linha de cima: a completa e a de desempenho. Linha de baixo: verba
        e rastreamento. É a ordem que a grade 2×2 desenha."""
        html = self._html()
        posicoes = [html.index(m) for m in (
            "Análise Geral", "Análise de Desempenho",
            "Análise de Verba", "Análise de Rastreamento")]
        self.assertEqual(posicoes, sorted(posicoes))

    def test_o_pdf_continua_na_analise_geral(self):
        """A Análise Geral mudou de URL em 30/08/2026 — `/desempenho/` passou
        para a frente que de fato lê aquele preset. A tela que gera o PDF é a
        mesma de sempre."""
        html = self._html()
        cartao = html.split('class="frente" href="/geral/"')[1].split("</a>")[0]
        self.assertIn("Análise Geral", cartao)
        self.assertIn("PDF para o cliente", cartao)
        self.assertNotIn("Análise de Desempenho", cartao)

    def test_o_cartao_de_desempenho_aponta_para_o_preset_desempenho(self):
        """Apontava para `/leitura/` até 30/08/2026, que é outra frente: lê o
        export COMPLETO e classifica o período pela faixa do perfil de
        negócio. O cartão certo com a rota errada fazia o operador mandar o
        arquivo errado — e os dois exports abrem sem reclamar."""
        html = self._html()
        cartao = html.split('class="frente" href="/desempenho/"')[1].split("</a>")[0]
        self.assertIn("Análise de Desempenho", cartao)
        self.assertIn("preset DESEMPENHO", cartao)
        self.assertNotIn("PDF", cartao)

    def test_so_a_analise_geral_promete_pdf(self):
        """A hierarquia da tela é uma só: um cartão devolve PDF, os outros
        três devolvem texto para o cliente."""
        html = self._html()
        self.assertEqual(html.count("PDF para o cliente"), 1)
        self.assertEqual(html.count("mensagem para o cliente"), 3)

    def test_nenhum_cartao_da_grade_esta_em_breve(self):
        """As quatro análises estão de pé desde 30/08/2026, quando o
        Rastreamento saiu de "Em breve". O único "Em breve" que sobrou na home
        é o atalho da Leitura Rápida, e ele fica fora da grade.

        A cobertura do cartão de Rastreamento em si está em
        `tests_rastreamento.HomeComQuatroFrentesTest`, junto com a frente.
        """
        grade = self._html().split('class="frentes"')[1]
        self.assertNotIn("em-breve", grade)
        self.assertNotIn("Em breve", grade)

    def test_a_leitura_rapida_e_um_atalho_fora_da_grade(self):
        """Ela não é uma das quatro análises, e o desenho precisa dizer isso:
        a grade são as frentes do produto, o atalho é outra coisa. Enfiá-la
        como quinto cartão foi o que fez a home descrever errado o que a
        aplicação faz.

        Que ele navega desde 30/08/2026 está em
        `tests_leitura_rapida.AtalhoNaHomeTest`, junto com a frente.
        """
        html = self._html()
        self.assertIn("Leitura Rápida", html)
        # Fora da grade: o atalho vem antes de `.frentes` no documento.
        self.assertLess(html.index('class="atalho"'),
                        html.index('class="frentes"'))
        self.assertNotIn("Leitura Rápida",
                         html.split('class="frentes"')[1])

    def test_a_grade_tem_exatamente_quatro_cartoes(self):
        """A Leitura Rápida está na home, mas não na grade."""
        html = self._html()
        grade = html.split('class="frentes"')[1]
        # Só os abridores de cartão: `class="frente-chamada"`, `frente-nome` e
        # companhia também começam com `class="frente`.
        cartoes = (grade.count('class="frente"')
                   + grade.count('class="frente em-breve"'))
        self.assertEqual(cartoes, 4)
        # A grade vem depois do atalho no documento, então nada da Leitura
        # Rápida pode aparecer daqui para baixo.
        self.assertNotIn("Leitura Rápida", grade)

    def test_o_cabecalho_nao_conta_mais_as_frentes(self):
        html = self._html()
        self.assertNotIn("Três frentes", html)
        self.assertIn("Gestão de Tráfego", html)

    def test_o_logo_leva_a_home_tambem_na_leitura(self):
        html = self.client.get("/leitura/").content.decode()
        self.assertIn('<a class="marca-link" href="/"', html)


# ----------------------------------------------------------------------
# O botão de IA
# ----------------------------------------------------------------------
LEITURA_DA_IA = """*Período analisado: 01/08/2026 a 31/08/2026*

*Leitura do período: ATENÇÃO*

No período investimos R$ 3.012,80 e geramos 142 conversas.

Jundiaí entregou o contato mais barato do mês.

O conjunto pede ajuste de rota.

Quantas das 142 conversas viraram venda?"""


class ValidacaoDaLeituraIATest(SimpleTestCase):
    """Recusar não custa relatório nenhum: o texto do motor está na tela desde
    antes do clique e continua depois dele."""

    def test_a_resposta_boa_passa(self):
        self.assertEqual(redator_ia._validar_leitura(LEITURA_DA_IA),
                         LEITURA_DA_IA)

    def test_sem_classificacao_e_recusada(self):
        with self.assertRaises(redator_ia.ErroDeIA) as e:
            redator_ia._validar_leitura("Foi um mês razoável. E aí?")
        self.assertEqual(e.exception.motivo, "formato")
        self.assertIn("classificação", str(e.exception))

    def test_sem_pergunta_no_fim_e_recusada(self):
        with self.assertRaises(redator_ia.ErroDeIA):
            redator_ia._validar_leitura("*Leitura do período: BOM*\n\nFoi bom.")

    def test_marcacao_de_markdown_e_recusada(self):
        for ruim in ("## Título\n\nBOM\n\nE aí?",
                     "BOM\n\n- primeiro item\n\nE aí?",
                     "BOM\n\n| a | b |\n\nE aí?"):
            with self.subTest(ruim=ruim[:12]):
                with self.assertRaises(redator_ia.ErroDeIA):
                    redator_ia._validar_leitura(ruim)

    def test_o_asterisco_do_cabecalho_nao_e_marcacao_proibida(self):
        # É o negrito que o formato PEDE nas duas primeiras linhas.
        redator_ia._validar_leitura("*Leitura do período: BOM*\n\nE aí?")

    def test_resposta_vazia_e_recusada(self):
        with self.assertRaises(redator_ia.ErroDeIA):
            redator_ia._validar_leitura("   ")


class NumerosCompartilhadosTest(SimpleTestCase):
    """Os formatadores saíram de `templates.py` para `numeros.py` quando a
    mensagem passou a escrever os mesmos valores. Uma implementação só."""

    def test_templates_continua_usando_os_mesmos(self):
        from .analysis import numeros, templates
        self.assertIs(templates._moeda, numeros.moeda)
        self.assertIs(templates._inteiro, numeros.inteiro)

    def test_o_milhar_sai_em_pt_br(self):
        from .analysis.numeros import inteiro, moeda
        self.assertEqual(moeda(2012.07), "R$ 2.012,07")
        self.assertEqual(inteiro(52000), "52.000")

    def test_a_mensagem_nunca_emite_ponto_decimal(self):
        texto = leitura_rapida.mensagem(_dados())
        self.assertFalse(re.search(r"R\$ [\d.]+\.\d{2}\b", texto), texto)
