# -*- coding: utf-8 -*-
"""
Contexto do período: o que o operador informa vira sinal, e sinal vira texto.

Regra que atravessa o arquivo inteiro: contexto vazio produz exatamente o que
a aplicação produzia antes de existirem estes campos. O contexto acrescenta
leitura — nunca muda a classificação, que continua sendo do CPA.
"""
import unittest

from .. import contexto as ctx
from .. import rules, templates
from ..benchmarks import ATENCAO, OTIMO
from .test_rules import REFERENCIA, _metricas

ELIX = {
    "investimento": 257.86, "alcance": 2763, "impressoes": 5560,
    "frequencia": 2.01, "cpm": 46.38, "resultados": 13, "cpa": 19.84,
    "campanhas": [
        {"nome": "A", "resultados": 13, "investimento": 171.24},
        {"nome": "B", "resultados": 0, "investimento": 70.51},
        {"nome": "C", "resultados": 0, "investimento": 16.11},
    ],
}

# CPA de 30,00 sem verba parada: o caso de "nada mudou e mesmo assim subiu".
CARA = dict(ELIX, cpa=30.0, resultados=100,
            campanhas=[{"nome": "A", "resultados": 100, "investimento": 3000.0}])


def _texto(metricas, contexto=None, **kw):
    av = rules.avaliar(metricas, contexto=contexto, **kw)
    return av, templates.redigir(av, metricas)


class VocabularioTest(unittest.TestCase):

    def test_limpar_descarta_o_que_nao_conhece(self):
        sujo = {"mudanca": "invadiu", "problema": ctx.PROBLEMA_SITE,
                "situacao": "qualquer", "lixo": "x"}
        self.assertEqual(ctx.limpar(sujo), {"problema": ctx.PROBLEMA_SITE})

    def test_limpar_aceita_vazio(self):
        self.assertEqual(ctx.limpar(None), {})
        self.assertEqual(ctx.limpar({}), {})

    def test_situacao_sem_problema_real_nao_vira_sinal(self):
        for problema in ("", ctx.SEM_PROBLEMA):
            with self.subTest(problema=problema):
                sinais = ctx.sinais({"problema": problema,
                                     "situacao": ctx.PROBLEMA_CORRIGIDO})
                self.assertNotIn(ctx.PROBLEMA_CORRIGIDO, sinais)

    def test_nada_mudou_e_afirmacao_e_gera_sinal(self):
        # Diferente de "não informado", que não gera nada.
        self.assertEqual(ctx.sinais({"mudanca": ctx.NADA_MUDOU}),
                         [ctx.NADA_MUDOU])
        self.assertEqual(ctx.sinais({"mudanca": ""}), [])

    def test_toda_opcao_do_select_vira_sinal(self):
        for valor, rotulo in ctx.MUDANCAS:
            with self.subTest(mudanca=valor):
                self.assertTrue(rotulo)
                if valor:
                    self.assertIn(valor, ctx.sinais({"mudanca": valor}))

        for valor, rotulo in ctx.PROBLEMAS:
            with self.subTest(problema=valor):
                self.assertTrue(rotulo)
                if valor:
                    self.assertIn(valor, ctx.sinais({"problema": valor}))

        for valor, rotulo in ctx.SITUACOES:
            with self.subTest(situacao=valor):
                self.assertTrue(rotulo)
                self.assertIn(valor, ctx.sinais({
                    "problema": ctx.PROBLEMA_SITE, "situacao": valor}))


class SemContextoTest(unittest.TestCase):
    """A garantia de não-regressão: vazio é igual a antes."""

    def test_contexto_vazio_nao_muda_nada(self):
        for vazio in (None, {}, {"mudanca": "", "problema": "", "situacao": "",
                                 "passo": ""}):
            with self.subTest(vazio=vazio):
                sem = templates.redigir(rules.avaliar(REFERENCIA), REFERENCIA)
                com = templates.redigir(
                    rules.avaliar(REFERENCIA, contexto=vazio), REFERENCIA)
                self.assertEqual(sem, com)

    def test_contexto_nao_entra_nos_sinais_quando_vazio(self):
        av = rules.avaliar(REFERENCIA, contexto={})
        self.assertEqual(av.contexto, {})
        for sinal in av.sinais:
            self.assertFalse(sinal.startswith("mudou_"))
            self.assertFalse(sinal.startswith("problema_"))


class NaoMexeNaClassificacaoTest(unittest.TestCase):

    def test_nenhuma_combinacao_muda_o_veredito(self):
        base = rules.avaliar(REFERENCIA).classificacao
        for mudanca, _r in ctx.MUDANCAS:
            for problema, _r2 in ctx.PROBLEMAS:
                for situacao, _r3 in ctx.SITUACOES:
                    av = rules.avaliar(REFERENCIA, contexto={
                        "mudanca": mudanca, "problema": problema,
                        "situacao": situacao})
                    with self.subTest(m=mudanca, p=problema, s=situacao):
                        self.assertEqual(av.classificacao, base)

    def test_meta_muda_o_veredito_porque_e_referencia_e_nao_contexto(self):
        # A meta não é "contexto": é o critério de comparação do CPA.
        self.assertEqual(rules.avaliar(_metricas(cpa=4.0, resultados=500),
                                       meta_cpa=10.0).classificacao, OTIMO)
        self.assertEqual(rules.avaliar(_metricas(cpa=4.0, resultados=500),
                                       meta_cpa=2.0).classificacao, ATENCAO)


class CaptacaoComVerbaParadaTest(unittest.TestCase):

    def test_junta_a_mudanca_ao_numero_derivado(self):
        _av, texto = _texto(ELIX, {"mudanca": ctx.MUDOU_CAPTACAO},
                            dias_periodo=7)
        atencao = texto.split("\n\n")[1]
        self.assertIn("A forma de captação mudou", atencao)
        self.assertIn("R$ 70,51", atencao)
        self.assertIn("de 3 a 4 registros", atencao)
        self.assertIn("não na comunicação dos anúncios", atencao)

    def test_sem_verba_parada_a_mudanca_nao_inventa_gargalo(self):
        _av, texto = _texto(REFERENCIA, {"mudanca": ctx.MUDOU_CAPTACAO})
        self.assertNotIn("forma de captação mudou", texto)


class ProblemaOperacionalTest(unittest.TestCase):

    def test_aberto_nomeia_o_problema_no_ponto_de_atencao(self):
        _av, texto = _texto(ELIX, {"problema": ctx.PROBLEMA_ATENDIMENTO,
                                   "situacao": ctx.PROBLEMA_ABERTO})
        atencao = texto.split("\n\n")[1]
        self.assertIn("o atendimento aos contatos", atencao)
        self.assertIn("fora da mídia", atencao)

    def test_corrigido_descreve_a_correcao_como_feita(self):
        _av, texto = _texto(ELIX, {"problema": ctx.PROBLEMA_FORMULARIO,
                                   "situacao": ctx.PROBLEMA_CORRIGIDO})
        acao = texto.split("\n\n")[-2]
        self.assertIn("A correção do formulário de cadastro já foi feita", acao)
        # E o passo deixa de mandar corrigir o que já foi corrigido.
        self.assertNotIn("Refazer o caminho", acao)

    def test_em_correcao_fala_no_presente(self):
        _av, texto = _texto(ELIX, {"problema": ctx.PROBLEMA_SITE,
                                   "situacao": ctx.PROBLEMA_EM_CORRECAO})
        self.assertIn("A correção do caminho de compra no site está em andamento",
                      texto.split("\n\n")[-2])

    def test_cada_problema_tem_sujeito_proprio(self):
        for problema in ctx.PROBLEMAS_REAIS:
            with self.subTest(problema=problema):
                self.assertIn(problema, templates._PROBLEMA_SUJEITO)

    def test_problema_sem_situacao_nao_entra_no_bloco_de_acao(self):
        sem, texto_sem = _texto(ELIX, None)
        _com, texto_com = _texto(ELIX, {"problema": ctx.PROBLEMA_ESTOQUE})
        self.assertEqual(texto_sem.split("\n\n")[-2], texto_com.split("\n\n")[-2])


class NadaMudouTest(unittest.TestCase):

    def test_custo_alto_sem_mudanca_nao_atribui_causa(self):
        av, texto = _texto(CARA, {"mudanca": ctx.NADA_MUDOU})
        atencao = texto.split("\n\n")[1]
        self.assertIn("Nada mudou na operação", atencao)
        self.assertEqual(av.proximo_passo, "testar_sem_atribuir_causa")
        self.assertIn("é medindo que se descobre", texto.split("\n\n")[-2])

    def test_custo_bom_sem_mudanca_nao_dispara(self):
        _av, texto = _texto(REFERENCIA, {"mudanca": ctx.NADA_MUDOU})
        self.assertNotIn("Nada mudou na operação", texto)


class PassoDoOperadorTest(unittest.TestCase):

    def test_escolha_do_operador_vence_o_motor(self):
        automatico = rules.avaliar(ELIX).proximo_passo
        escolhido = rules.avaliar(ELIX, contexto={"passo": "escalar_verba"})
        self.assertNotEqual(automatico, "escalar_verba")
        self.assertEqual(escolhido.proximo_passo, "escalar_verba")

    def test_passo_desconhecido_e_ignorado(self):
        av = rules.avaliar(ELIX, contexto={"passo": "nao_existe"})
        self.assertEqual(av.proximo_passo, rules.avaliar(ELIX).proximo_passo)

    def test_toda_opcao_do_select_tem_texto(self):
        for passo in rules.PASSOS:
            with self.subTest(passo=passo):
                self.assertIn(passo, templates._PASSO)
                self.assertIn(passo, templates._PREFIXO_OBJETIVO)
        for passo in rules.PASSOS_GRUPO:
            with self.subTest(passo=passo):
                self.assertIn(passo, templates._PASSO_GRUPO)
                self.assertIn(passo, templates._PREFIXO_OBJETIVO_GRUPO)


class MatrizTest(unittest.TestCase):
    """
    Toda combinação dos campos de contexto, nas duas contas reais e com e sem
    números: 6 mudanças × 6 problemas × 4 situações (incluindo a vazia) × 2
    métricas × 2 formas = 1.152 textos. O que se afirma aqui vale para todos.
    """

    SITUACOES = [""] + [v for v, _r in ctx.SITUACOES]

    def _todas(self):
        for metricas in (ELIX, CARA):
            for mudanca, _r in ctx.MUDANCAS:
                for problema, _r2 in ctx.PROBLEMAS:
                    for situacao in self.SITUACOES:
                        contexto = {"mudanca": mudanca, "problema": problema,
                                    "situacao": situacao}
                        av = rules.avaliar(metricas, contexto=contexto,
                                           dias_periodo=7)
                        for numeros in (False, True):
                            yield (contexto, av,
                                   templates.redigir(av, metricas,
                                                     incluir_numeros=numeros))

    def test_estrutura_e_orcamento_em_toda_combinacao(self):
        for contexto, _av, texto in self._todas():
            blocos = texto.split("\n\n")
            with self.subTest(**contexto):
                self.assertGreaterEqual(len(blocos), 3)
                self.assertLessEqual(len(blocos), 5)
                self.assertLessEqual(len(texto), templates.LIMITE_PDF)
                self.assertTrue(blocos[0].startswith(
                    "<b>%s</b> " % templates.ROTULO_LEITURA))
                self.assertTrue(blocos[-1].startswith(
                    "<b>%s</b> " % templates.ROTULO_OBJETIVO))

    def test_restricoes_de_lingua_em_toda_combinacao(self):
        proibidos = ("pausa", "duplicar", "ativar", "desativ", "inativ",
                     "veiculação", "ads manager", "gerenciador",
                     "vamos reduzir", "vamos atingir", "garantimos", "cpa",
                     "cpm", "ctr")
        for contexto, _av, texto in self._todas():
            with self.subTest(**contexto):
                for termo in proibidos:
                    self.assertNotIn(termo, texto.lower())

    def test_nenhum_placeholder_escapa_sem_valor(self):
        for contexto, _av, texto in self._todas():
            with self.subTest(**contexto):
                self.assertNotIn("{", texto)
                self.assertNotIn("}", texto)
                # Sujeito vazio deixaria "A correção  já foi feita".
                self.assertNotIn("  ", texto)

    def test_o_objetivo_nunca_traz_numero(self):
        for contexto, _av, texto in self._todas():
            objetivo = texto.split("\n\n")[-1]
            with self.subTest(**contexto):
                self.assertNotRegex(objetivo, r"\d")

    def test_determinismo_em_toda_combinacao(self):
        primeira = [t for _c, _a, t in self._todas()]
        segunda = [t for _c, _a, t in self._todas()]
        self.assertEqual(primeira, segunda)

    def test_tudo_vazio_e_identico_a_nao_passar_contexto(self):
        vazio = {"mudanca": "", "problema": "", "situacao": ""}
        for metricas in (ELIX, CARA, REFERENCIA):
            for numeros in (False, True):
                sem = templates.redigir(rules.avaliar(metricas, dias_periodo=7),
                                        metricas, incluir_numeros=numeros)
                com = templates.redigir(
                    rules.avaliar(metricas, contexto=vazio, dias_periodo=7),
                    metricas, incluir_numeros=numeros)
                with self.subTest(cpa=metricas.get("cpa"), numeros=numeros):
                    self.assertEqual(sem, com)


class FronteirasDaMetaTest(unittest.TestCase):
    """Os dois cortes da razão cpa/meta: 0,90 e 1,15. Volume alto de propósito
    — o rebaixamento por amostra pequena tem teste próprio."""

    def _classificar(self, cpa, meta):
        return rules.avaliar(_metricas(cpa=cpa, resultados=500),
                             meta_cpa=meta).classificacao

    def test_cada_corte_dos_dois_lados(self):
        for meta in (5.00, 10.00, 19.84, 100.00):
            casos = [
                (meta * 0.89, OTIMO), (meta * 0.90, OTIMO),
                (meta * 0.91, "BOM"), (meta * 1.14, "BOM"),
                (meta * 1.15, "BOM"), (meta * 1.16, ATENCAO),
            ]
            for cpa, esperado in casos:
                with self.subTest(meta=meta, cpa=round(cpa, 4)):
                    self.assertEqual(self._classificar(cpa, meta), esperado)

    def test_a_meta_ignora_a_faixa_do_perfil_nos_dois_sentidos(self):
        # CPA 2,00 é ótimo em varejo_celular, mas ruim contra meta de 1,00.
        self.assertEqual(self._classificar(2.00, 1.00), ATENCAO)
        # CPA 50,00 é atenção em qualquer perfil, mas ótimo contra meta de 100.
        self.assertEqual(self._classificar(50.00, 100.00), OTIMO)

    def test_meta_zero_ou_nula_nao_conta_como_meta(self):
        for meta in (None, 0, 0.0):
            with self.subTest(meta=meta):
                av = rules.avaliar(_metricas(cpa=4.0, resultados=500),
                                   meta_cpa=meta)
                self.assertFalse(av.meta_definida)
                self.assertIn(rules.META_CPA_INDEFINIDA, av.sinais)


class SerializavelTest(unittest.TestCase):

    def test_contexto_viaja_na_avaliacao(self):
        import json
        from dataclasses import asdict
        av = rules.avaliar(ELIX, contexto={"problema": ctx.PROBLEMA_SITE,
                                           "situacao": ctx.PROBLEMA_ABERTO})
        bruto = asdict(av)
        self.assertEqual(json.loads(json.dumps(bruto)), bruto)
        self.assertEqual(bruto["contexto"]["problema"], ctx.PROBLEMA_SITE)
