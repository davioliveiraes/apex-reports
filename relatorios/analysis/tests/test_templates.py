# -*- coding: utf-8 -*-
"""Redação: os blocos variáveis, os números que podem ou não aparecer no PDF e
as restrições de língua."""
import re
import unittest

from .. import rules, templates
from ..benchmarks import ATENCAO, BOM, OTIMO
from .test_rules import REFERENCIA, _metricas


def _texto(metricas=None, destino="pdf", incluir_numeros=False, **kw):
    metricas = REFERENCIA if metricas is None else metricas
    return templates.redigir(rules.avaliar(metricas, **kw), metricas,
                             destino=destino, incluir_numeros=incluir_numeros)


def _blocos(texto):
    return texto.split("\n\n")


def _todas_as_variantes():
    """Cobertura larga de combinações de sinais — cada caso muda uma coisa e
    mantém o resto plausível."""
    sem_ctr = _metricas(resultados=500)
    casos = [
        REFERENCIA,                                          # ÓTIMO saturado
        _metricas(cpa=6.0, resultados=500),                  # BOM
        _metricas(cpa=30.0, resultados=500),                 # ATENÇÃO
        _metricas(cpa=30.0, frequencia=4.0, resultados=500),
        _metricas(resultados=25),                            # amostra pequena
        _metricas(resultados=0, cpa=None),                   # sem resultados
        _metricas(cpa=None, investimento=None),              # sem verba lida
        _metricas(frequencia=1.1, resultados=500),           # freq. baixa
        _metricas(frequencia=2.0, resultados=500),           # freq. saudável
        _metricas(frequencia=3.0, resultados=500),           # freq. elevada
        _metricas(frequencia=2.0, cpm=80.0, resultados=500),  # entrega cara
        _metricas(frequencia=2.0, cpm=25.0, resultados=500),
        _metricas(frequencia=2.0, cpm=15.0, resultados=500),
        _metricas(resultados=500, ctr=0.5),
        _metricas(resultados=500, ctr=1.2),
        _metricas(resultados=500, ctr=3.0),
        _metricas(resultados=500, campanhas=[
            {"nome": "A", "resultados": 90}, {"nome": "B", "resultados": 10}]),
        _metricas(resultados=500, campanhas=[
            {"nome": "A", "resultados": 50}, {"nome": "B", "resultados": 50}]),
        _metricas(resultados=500, campanhas=[]),
        # Export enxuto: nem frequência, nem custo de exibição, nem campanhas.
        dict(sem_ctr, frequencia=None, cpm=None, campanhas=[]),
        dict(sem_ctr, cpa=30.0, frequencia=None, cpm=None, campanhas=[]),
    ]
    for metricas in casos:
        for meta in (None, 5.00):
            yield metricas, meta


class OrcamentoTest(unittest.TestCase):
    """
    Quando o texto não cabe, o corte é por precedência: o apoio sai primeiro, o
    ponto de atenção depois, e os três fixos nunca saem.

    O teto real é medido no PDF (relatorios/tests.py::OrcamentoDePaginaTest);
    aqui o que se testa é o comportamento do corte, com o teto forçado para
    baixo — senão o teste dependeria de nenhum fragmento caber, que é o
    contrário do que se quer.
    """

    def setUp(self):
        self.limite = templates.LIMITE_PDF
        self.limite_grupo = templates.LIMITE_PDF_GRUPO

    def tearDown(self):
        templates.LIMITE_PDF = self.limite
        templates.LIMITE_PDF_GRUPO = self.limite_grupo

    def _texto_com_teto(self, teto, metricas=None, **kw):
        templates.LIMITE_PDF = teto
        return _texto(metricas, **kw)

    def test_texto_de_hoje_cabe_com_folga_em_toda_variante(self):
        for metricas, meta in _todas_as_variantes():
            for numeros in (False, True):
                with self.subTest(cpa=metricas.get("cpa"), meta=meta):
                    self.assertLessEqual(
                        len(_texto(metricas, meta_cpa=meta,
                                   incluir_numeros=numeros)),
                        templates.LIMITE_PDF)

    def test_o_apoio_sai_antes_do_ponto_de_atencao(self):
        completo = _blocos(_texto())
        self.assertEqual(len(completo), 5)
        cortado = _blocos(self._texto_com_teto(len(_texto()) - 1))
        rotulos = [b.split("</b> ")[0].replace("<b>", "") for b in cortado]
        self.assertEqual(len(cortado), 4)
        self.assertIn(templates.ROTULO_ATENCAO, rotulos)
        self.assertNotIn(templates.ROTULO_ATUAL, rotulos)

    def test_depois_do_apoio_sai_o_ponto_de_atencao(self):
        cortado = _blocos(self._texto_com_teto(700))
        rotulos = [b.split("</b> ")[0].replace("<b>", "") for b in cortado]
        self.assertEqual(rotulos, [templates.ROTULO_LEITURA,
                                   templates.ROTULO_ACAO,
                                   templates.ROTULO_OBJETIVO])

    def test_os_tres_fixos_nunca_saem(self):
        # Teto absurdo: sobra o mínimo, e o mínimo é a leitura, a ação e o
        # objetivo. Meia análise seria pior que uma segunda página.
        cortado = _blocos(self._texto_com_teto(1))
        self.assertEqual(len(cortado), 3)

    def test_whatsapp_nao_tem_pagina_e_nao_corta(self):
        templates.LIMITE_PDF = 700
        completo = templates.redigir(rules.avaliar(REFERENCIA), REFERENCIA,
                                     destino="whatsapp")
        self.assertEqual(len(completo.split("\n\n")), 5)


class BlocosTest(unittest.TestCase):
    """Três blocos fixos (leitura, ação, objetivo) e até dois no meio."""

    def test_entre_tres_e_cinco_blocos(self):
        for metricas, meta in _todas_as_variantes():
            for numeros in (False, True):
                with self.subTest(cpa=metricas.get("cpa"), meta=meta,
                                  numeros=numeros):
                    blocos = _blocos(_texto(metricas, meta_cpa=meta,
                                            incluir_numeros=numeros))
                    self.assertGreaterEqual(len(blocos), 3)
                    self.assertLessEqual(len(blocos), 5)
                    self.assertTrue(all(b.strip() for b in blocos))

    def test_blocos_fixos_sempre_nas_pontas(self):
        for metricas, meta in _todas_as_variantes():
            with self.subTest(cpa=metricas.get("cpa"), meta=meta):
                blocos = _blocos(_texto(metricas, meta_cpa=meta))
                self.assertTrue(blocos[0].startswith(
                    "<b>%s</b> " % templates.ROTULO_LEITURA))
                self.assertTrue(blocos[-2].startswith(
                    "<b>%s</b> " % templates.ROTULO_ACAO))
                self.assertTrue(blocos[-1].startswith(
                    "<b>%s</b> " % templates.ROTULO_OBJETIVO))

    def test_rotulos_do_meio_sao_os_previstos(self):
        meio = {templates.ROTULO_ATENCAO, templates.ROTULO_ATUAL,
                templates.ROTULO_SUSTENTOU}
        for metricas, meta in _todas_as_variantes():
            with self.subTest(cpa=metricas.get("cpa"), meta=meta):
                for bloco in _blocos(_texto(metricas, meta_cpa=meta))[1:-2]:
                    rotulo = bloco.split("</b> ")[0].replace("<b>", "")
                    self.assertIn(rotulo, meio)

    def test_leitura_atual_so_depois_de_um_ponto_de_atencao(self):
        # Sozinho, o bloco de apoio é "o que sustentou o resultado".
        for metricas, meta in _todas_as_variantes():
            blocos = _blocos(_texto(metricas, meta_cpa=meta))
            rotulos = [b.split("</b> ")[0].replace("<b>", "") for b in blocos]
            with self.subTest(cpa=metricas.get("cpa"), meta=meta):
                if templates.ROTULO_ATUAL in rotulos:
                    self.assertIn(templates.ROTULO_ATENCAO, rotulos)
                    self.assertLess(rotulos.index(templates.ROTULO_ATENCAO),
                                    rotulos.index(templates.ROTULO_ATUAL))

    def test_o_meio_nunca_repete_a_mesma_metrica(self):
        # Frequência no ponto de atenção e frequência de novo na leitura atual
        # seria dizer duas vezes a mesma coisa.
        for metricas, meta in _todas_as_variantes():
            blocos = _blocos(_texto(metricas, meta_cpa=meta))[1:-2]
            if len(blocos) < 2:
                continue
            with self.subTest(cpa=metricas.get("cpa"), meta=meta):
                self.assertNotEqual(blocos[0], blocos[1])
                for termo in ("frequência", "custo para aparecer"):
                    self.assertFalse(termo in blocos[0] and termo in blocos[1],
                                     termo)

    def test_todo_bloco_tem_texto_alem_do_rotulo(self):
        for bloco in _blocos(_texto()):
            corpo = bloco.split("</b> ", 1)[1]
            self.assertGreater(len(corpo), 40)

    def test_acao_vem_do_passo_escolhido(self):
        acao = _blocos(_texto())[-2]
        self.assertIn(templates._PASSO["ampliar_publico_e_criativos"], acao)

    def test_toda_chave_de_passo_tem_texto_e_prefixo(self):
        chaves = {chave for _, chave in rules._PROXIMO_PASSO} | {rules.PASSO_PADRAO}
        self.assertEqual(chaves - set(templates._PASSO), set())
        self.assertEqual(chaves - set(templates._PREFIXO_OBJETIVO), set())

    def test_todo_motivo_possivel_tem_texto(self):
        motivos = {rules.CPA_OTIMO, rules.CPA_BOM, rules.CPA_ATENCAO,
                   rules.AMOSTRA_PEQUENA, rules.SEM_RESULTADOS,
                   rules.SEM_INVESTIMENTO}
        self.assertEqual(motivos - set(templates._MOTIVO), set())

    def test_sem_verba_lida_nao_abre_elogiando_nem_culpando_a_conta(self):
        metricas = _metricas(cpa=None, investimento=None)
        texto = _texto(metricas)
        self.assertIn("<b>incompleta</b>", texto)
        self.assertIn("não trouxe o valor investido", texto)
        self.assertIn("Recuperar o valor investido", texto)
        for termo in ("acima do esperado", "ritmo saudável",
                      "pede ajuste de rota"):
            self.assertNotIn(termo, texto)


class RotuloDoBlocoDoisTest(unittest.TestCase):
    """`Ponto de atenção.` só quando o sinal secundário cobra algo."""

    def _rotulo(self, **mudancas):
        return _blocos(_texto(_metricas(resultados=500, **mudancas)))[1]

    def test_ponto_de_atencao(self):
        for mudancas in ({"frequencia": 4.0},                  # saturada
                         {"frequencia": 3.0},                  # elevada
                         {"frequencia": 2.0, "cpm": 80.0},     # entrega cara
                         {"frequencia": None, "cpm": None, "ctr": 0.5}):
            with self.subTest(**mudancas):
                self.assertTrue(self._rotulo(**mudancas).startswith(
                    "<b>%s</b>" % templates.ROTULO_ATENCAO))

    def test_o_que_sustentou_o_resultado(self):
        for mudancas in ({"frequencia": 1.1},                  # baixa
                         {"frequencia": 2.0, "cpm": 10.0},     # entrega barata
                         {"frequencia": 2.0, "cpm": 25.0},     # entrega normal
                         {"frequencia": None, "cpm": None, "ctr": 3.0}):
            with self.subTest(**mudancas):
                self.assertTrue(self._rotulo(**mudancas).startswith(
                    "<b>%s</b>" % templates.ROTULO_SUSTENTOU))

    def test_export_enxuto_ainda_rende_um_bloco_dois(self):
        magro = dict(_metricas(resultados=500), frequencia=None, cpm=None,
                     campanhas=[])
        self.assertTrue(_blocos(_texto(magro))[1].startswith(
            "<b>%s</b>" % templates.ROTULO_SUSTENTOU))
        magro_ruim = dict(magro, cpa=30.0)
        self.assertTrue(_blocos(_texto(magro_ruim))[1].startswith(
            "<b>%s</b>" % templates.ROTULO_ATENCAO))


class ObjetivoDoProximoCicloTest(unittest.TestCase):
    """O bloco 4 compromete com direção — nunca com número nem promessa."""

    def _objetivos(self):
        for metricas, meta in _todas_as_variantes():
            for numeros in (False, True):
                yield _blocos(_texto(metricas, meta_cpa=meta,
                                     incluir_numeros=numeros))[-1]

    def test_nunca_traz_digito(self):
        for objetivo in self._objetivos():
            self.assertNotRegex(objetivo, r"\d")
            self.assertNotIn("R$", objetivo)
            self.assertNotIn("%", objetivo)

    def test_nunca_promete_resultado(self):
        proibidos = ("vamos reduzir", "vamos atingir", "vamos chegar",
                     "vamos dobrar", "vai cair", "vai subir", "garantimos",
                     "prometemos")
        for objetivo in self._objetivos():
            for termo in proibidos:
                self.assertNotIn(termo, objetivo.lower())

    def test_usa_verbo_de_direcao(self):
        aceitos = ("o objetivo é", "buscamos", "o alvo do próximo ciclo é")
        for objetivo in self._objetivos():
            self.assertTrue(any(v in objetivo for v in aceitos), objetivo)

    def test_cada_classificacao_tem_seu_degrau(self):
        degraus = {
            OTIMO: _texto(REFERENCIA),
            BOM: _texto(_metricas(cpa=6.0, resultados=500)),
            ATENCAO: _texto(_metricas(cpa=30.0, resultados=500)),
        }
        for classificacao, texto in degraus.items():
            self.assertIn(templates._ESCADA[classificacao], _blocos(texto)[-1])

    def test_objetivo_liga_com_a_acao_escolhida(self):
        texto = _texto()   # ampliar_publico_e_criativos
        self.assertTrue(_blocos(texto)[-1].startswith(
            "<b>%s</b> %s" % (templates.ROTULO_OBJETIVO,
                              templates._PREFIXO_OBJETIVO[
                                  "ampliar_publico_e_criativos"])))


class SemNumerosNoPdfTest(unittest.TestCase):
    """No PDF os números já estão nas tabelas logo acima da análise."""

    def test_nenhum_digito_em_nenhuma_variante(self):
        for metricas, meta in _todas_as_variantes():
            texto = _texto(metricas, meta_cpa=meta)
            with self.subTest(cpa=metricas.get("cpa"), meta=meta):
                self.assertNotRegex(texto, r"\d")
                self.assertNotIn("R$", texto)
                self.assertNotIn("%", texto)

    def test_com_numeros_traz_o_cpa_em_pt_br(self):
        texto = _texto(incluir_numeros=True)
        self.assertIn("R$ 1,87", texto)
        self.assertIn("3,56", texto)      # frequência no bloco 2

    def test_com_numeros_traz_o_ctr_com_sinal_de_porcento(self):
        texto = _texto(_metricas(resultados=500, frequencia=None, cpm=None,
                                 ctr=0.5), incluir_numeros=True)
        self.assertIn("0,50%", texto)

    def test_milhar_em_pt_br(self):
        texto = _texto(_metricas(resultados=25, investimento=1234.56),
                       incluir_numeros=True)
        self.assertIn("<b>25</b>", texto)
        texto = _texto(_metricas(resultados=0, cpa=None, investimento=1234.56),
                       incluir_numeros=True)
        self.assertIn("R$ 1.234,56", texto)


class FormatacaoPorDestinoTest(unittest.TestCase):

    def test_pdf_usa_apenas_b_e_i(self):
        texto = _texto(incluir_numeros=True)
        self.assertIn("<b>", texto)
        # Nenhuma outra tag, e nada de markdown
        self.assertEqual(set(re.findall(r"</?([a-z]+)>", texto)), {"b"})
        for marca in ("**", "__", "##", "- ", "*"):
            self.assertNotIn(marca, texto)

    def test_whatsapp_usa_asterisco_simples(self):
        texto = _texto(destino="whatsapp", incluir_numeros=True)
        self.assertNotIn("<", texto)
        self.assertIn("*R$ 1,87*", texto)
        self.assertNotIn("**", texto)

    def test_whatsapp_mantem_os_rotulos_em_negrito(self):
        texto = _texto(destino="whatsapp")
        self.assertTrue(texto.startswith("*%s*" % templates.ROTULO_LEITURA))


class LinguagemTest(unittest.TestCase):

    def _todos_os_textos(self):
        for metricas, meta in _todas_as_variantes():
            for numeros in (False, True):
                yield _texto(metricas, meta_cpa=meta, incluir_numeros=numeros)

    def test_nunca_menciona_status_de_campanha(self):
        proibidos = ("pausa", "pausar", "pausad", "duplicar", "duplicad",
                     "ativar", "ativação", "desativ", "inativ", "veiculação",
                     "ads manager", "gerenciador")
        for texto in self._todos_os_textos():
            for termo in proibidos:
                self.assertNotIn(termo, texto.lower())

    def test_nunca_promete_resultado_futuro(self):
        proibidos = ("vamos dobrar", "vai cair", "vai subir", "garantimos",
                     "prometemos", "certamente", "com certeza")
        for texto in self._todos_os_textos():
            for termo in proibidos:
                self.assertNotIn(termo, texto.lower())

    def test_atencao_nomeia_o_problema_sem_otimismo_forcado(self):
        texto = _texto(_metricas(cpa=30.0, resultados=500))
        self.assertIn("<b>pede ajuste de rota</b>", texto)
        self.assertIn("acima da faixa de trabalho da conta", texto)
        for termo in ("parabéns", "excelente", "ótimo resultado"):
            self.assertNotIn(termo, texto.lower())

    def test_termo_tecnico_vem_explicado(self):
        # Sigla crua nunca aparece: frequência vem com a explicação junto e o
        # CPM entra como "custo para aparecer na frente do público".
        for texto in self._todos_os_textos():
            self.assertNotIn("CPM", texto)
            self.assertNotIn("CPA", texto)
            self.assertNotIn("CTR", texto)

    def test_traduz_a_metrica_em_consequencia_de_negocio(self):
        # As formulações que o briefing manda evitar, por soarem a relatório
        # de gestor de tráfego em vez de conversa com o dono da loja.
        proibidos = ("patamar que consideramos aceitável", "frequência chegou "
                     "a saturação", "cpm competitivo", "ctr baixo")
        for texto in self._todos_os_textos():
            for termo in proibidos:
                self.assertNotIn(termo, texto.lower())


class DeterminismoTest(unittest.TestCase):

    def test_mesma_entrada_mesma_string(self):
        self.assertEqual(_texto(), _texto())

    def test_meta_muda_a_referencia_citada(self):
        sem = _texto(_metricas(cpa=4.0, resultados=500))
        com = _texto(_metricas(cpa=4.0, resultados=500), meta_cpa=10.00)
        self.assertIn("faixa de trabalho da conta", sem)
        self.assertIn("meta combinada", com)


class SinalSecundarioTest(unittest.TestCase):

    def test_frequencia_manda_quando_nao_esta_saudavel(self):
        texto = _texto(_metricas(frequencia=4.0, cpm=80.0, resultados=500))
        self.assertIn("já viu os anúncios muitas vezes", texto)
        self.assertNotIn("custo para aparecer", texto)

    def test_entrega_entra_quando_a_frequencia_esta_saudavel(self):
        texto = _texto(_metricas(frequencia=2.0, cpm=80.0, resultados=500))
        self.assertIn("custo para aparecer na frente do público", texto)

    def test_sem_frequencia_e_sem_entrega_cai_na_atencao_ou_na_estrutura(self):
        metricas = dict(_metricas(resultados=500), frequencia=None, cpm=None)
        self.assertIn("única estrutura de campanha", _texto(metricas))
        self.assertIn("prendendo pouca atenção", _texto(dict(metricas, ctr=0.5)))


class ClassificacaoNaAberturaTest(unittest.TestCase):

    def test_cada_classificacao_tem_abertura_propria(self):
        aberturas = {
            OTIMO: _texto(REFERENCIA),
            BOM: _texto(_metricas(cpa=6.0, resultados=500)),
            ATENCAO: _texto(_metricas(cpa=30.0, resultados=500)),
        }
        for classificacao, texto in aberturas.items():
            self.assertTrue(texto.startswith(
                "<b>%s</b> %s" % (templates.ROTULO_LEITURA,
                                  templates._ABERTURA[classificacao])))
        self.assertEqual(len(set(aberturas.values())), 3)
