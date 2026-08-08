# -*- coding: utf-8 -*-
"""
Consolidado: cada unidade medida contra o CPA do próprio grupo.

É a única referência do motor que não é estimativa nossa — as outras unidades
rodaram o mesmo intervalo, o mesmo tipo de campanha e a mesma gestão.
"""
import unittest

from .. import benchmarks, rules, templates
from ..benchmarks import ATENCAO, BOM, OTIMO


def _unidade(nome, resultados, investimento, **extra):
    metricas = {"resultados": resultados, "investimento": investimento,
                "impressoes": resultados * 100, "alcance": resultados * 40,
                "frequencia": 2.0, "cpm": 15.0}
    metricas.update(extra)
    return {"nome": nome, "metricas": metricas}


def _grupo(unidades):
    """Totais somados e taxas recalculadas sobre eles — a mesma regra do
    parser, para o teste não medir uma agregação diferente da real."""
    def soma(chave):
        return sum(u["metricas"].get(chave) or 0 for u in unidades)

    investimento, resultados = soma("investimento"), soma("resultados")
    impressoes, alcance = soma("impressoes"), soma("alcance")
    return {
        "investimento": investimento, "resultados": resultados,
        "impressoes": impressoes, "alcance": alcance,
        "cpa": investimento / resultados if resultados else None,
        "frequencia": impressoes / alcance if alcance else None,
        "cpm": investimento / impressoes * 1000 if impressoes else None,
    }


def _avaliar(unidades, **kw):
    return rules.avaliar_grupo(unidades, _grupo(unidades), **kw)


# Grupo com uma praça cara e duas baratas: CPA do grupo = 500/110 = 4,55.
DISPERSO = [_unidade("Cara", 10, 400.0),
            _unidade("Barata", 50, 50.0),
            _unidade("Média", 50, 50.0)]

# Todas com CPA de 5,00.
HOMOGENEO = [_unidade("A", 100, 500.0),
             _unidade("B", 100, 500.0),
             _unidade("C", 100, 500.0)]


class ReferenciaDoGrupoTest(unittest.TestCase):

    def test_unidade_e_medida_contra_o_grupo(self):
        ag = _avaliar(DISPERSO)
        self.assertAlmostEqual(ag.cpa_grupo, 500 / 110, places=4)
        por_nome = {u.nome: u for u in ag.unidades}
        self.assertEqual(por_nome["Cara"].avaliacao.classificacao, ATENCAO)
        self.assertEqual(por_nome["Barata"].avaliacao.classificacao, OTIMO)
        for u in ag.unidades:
            self.assertEqual(u.avaliacao.referencia, benchmarks.REF_GRUPO)
            self.assertIn(rules.COMPARADA_AO_GRUPO, u.avaliacao.sinais)

    def test_a_faixa_do_perfil_sai_de_cena(self):
        # CPA de 40,00 seria ATENÇÃO em qualquer perfil; 1,00 seria ÓTIMO em
        # todos. O que decide aqui é a distância para o grupo, não a faixa.
        ag = _avaliar([_unidade("A", 10, 400.0), _unidade("B", 10, 420.0)])
        for u in ag.unidades:
            self.assertEqual(u.avaliacao.classificacao, BOM)

    def test_meta_vence_o_grupo(self):
        # Com meta combinada, a referência medida cede: a meta é o critério
        # de verdade, e o grupo volta a ser só contexto.
        ag = _avaliar(DISPERSO, meta_cpa=100.0)
        for u in ag.unidades:
            self.assertEqual(u.avaliacao.referencia, benchmarks.REF_META)
        # Todas abaixo da meta: a praça "cara" para o grupo não é cara para o
        # cliente, e é o combinado com ele que vale.
        self.assertNotIn(ATENCAO,
                         [u.avaliacao.classificacao for u in ag.unidades])

    def test_o_grupo_nao_e_medido_contra_ele_mesmo(self):
        # Senão todo consolidado sairia BOM por construção.
        ag = _avaliar(HOMOGENEO)
        self.assertEqual(ag.grupo.referencia, benchmarks.REF_PERFIL)
        self.assertEqual(ag.grupo.classificacao, BOM)   # CPA 5,00 em varejo

    def test_razao_de_cada_unidade(self):
        ag = _avaliar(DISPERSO)
        por_nome = {u.nome: u for u in ag.unidades}
        self.assertAlmostEqual(por_nome["Cara"].razao, 40 / (500 / 110), places=4)
        self.assertAlmostEqual(por_nome["Barata"].razao, 1 / (500 / 110), places=4)


class DispersaoTest(unittest.TestCase):

    def test_grupo_com_praca_cara_e_barata(self):
        ag = _avaliar(DISPERSO)
        self.assertIn(rules.UNIDADES_ACIMA, ag.sinais)
        self.assertIn(rules.UNIDADES_ABAIXO, ag.sinais)
        self.assertIn(rules.DISPERSAO_ALTA, ag.sinais)
        self.assertEqual(ag.proximo_passo,
                         "levar_o_metodo_das_melhores_as_demais")

    def test_grupo_homogeneo(self):
        ag = _avaliar(HOMOGENEO)
        self.assertEqual(ag.sinais, [rules.GRUPO_HOMOGENEO])
        self.assertEqual(ag.proximo_passo, rules.PASSO_GRUPO_PADRAO)

    def test_dispersao_alta_precisa_do_dobro(self):
        # 1,99x ainda é variação; 2,0x já são dois grupos diferentes.
        quase = _avaliar([_unidade("A", 100, 100.0), _unidade("B", 100, 199.0)])
        self.assertNotIn(rules.DISPERSAO_ALTA, quase.sinais)
        dobro = _avaliar([_unidade("A", 100, 100.0), _unidade("B", 100, 200.0)])
        self.assertIn(rules.DISPERSAO_ALTA, dobro.sinais)

    def test_extremos(self):
        melhor, pior = _avaliar(DISPERSO).extremos()
        self.assertEqual(melhor.nome, "Barata")
        self.assertEqual(pior.nome, "Cara")

    def test_uma_unidade_so_nao_tem_extremos(self):
        melhor, pior = _avaliar([_unidade("A", 100, 500.0)]).extremos()
        self.assertIsNone(melhor)
        self.assertIsNone(pior)

    def test_unidade_sem_resultado_fica_fora_da_dispersao(self):
        # Sem CPA não há distância a medir: ela não vira extremo nem entra na
        # conta da dispersão. Mas a verba dela continua no total do grupo, e
        # portanto encarece a referência de todas as outras — é o que deve
        # acontecer, e é por isso que ela aparece como praça a resolver.
        ag = _avaliar([_unidade("A", 100, 500.0), _unidade("B", 100, 500.0),
                       _unidade("Zerada", 0, 300.0)])
        por_nome = {u.nome: u for u in ag.unidades}
        self.assertIsNone(por_nome["Zerada"].cpa)
        self.assertIsNone(por_nome["Zerada"].razao)
        self.assertEqual(por_nome["Zerada"].avaliacao.motivo_principal,
                         rules.SEM_RESULTADOS)
        melhor, pior = ag.extremos()
        self.assertNotIn("Zerada", (melhor.nome, pior.nome))

    def test_verba_sem_resultado_encarece_a_referencia_do_grupo(self):
        sem = _avaliar([_unidade("A", 100, 500.0), _unidade("B", 100, 500.0)])
        com = _avaliar([_unidade("A", 100, 500.0), _unidade("B", 100, 500.0),
                        _unidade("Zerada", 0, 300.0)])
        self.assertGreater(com.cpa_grupo, sem.cpa_grupo)


class RedacaoDoGrupoTest(unittest.TestCase):

    def _texto(self, unidades, **kw):
        numeros = kw.pop("incluir_numeros", False)
        return templates.redigir_grupo(_avaliar(unidades, **kw),
                                       _grupo(unidades), incluir_numeros=numeros)

    def test_quatro_blocos(self):
        for unidades in (DISPERSO, HOMOGENEO, [_unidade("A", 100, 500.0)]):
            for numeros in (False, True):
                with self.subTest(n=len(unidades), numeros=numeros):
                    blocos = self._texto(unidades,
                                         incluir_numeros=numeros).split("\n\n")
                    self.assertEqual(len(blocos), 4)

    def test_nomeia_a_praca_cara_e_a_barata(self):
        texto = self._texto(DISPERSO)
        self.assertIn("Cara", texto)
        self.assertIn("Barata", texto)
        self.assertTrue(texto.split("\n\n")[1].startswith(
            "<b>%s</b>" % templates.ROTULO_ATENCAO))

    def test_grupo_homogeneo_nao_inventa_destaque(self):
        texto = self._texto(HOMOGENEO)
        self.assertIn("todas no mesmo patamar", texto)
        self.assertTrue(texto.split("\n\n")[1].startswith(
            "<b>%s</b>" % templates.ROTULO_SUSTENTOU))

    def test_sem_numeros_no_pdf(self):
        # Nome de praça pode ter dígito ("TIM 01"), então aqui a regra é sobre
        # os números das tabelas: nada de moeda nem percentual.
        for unidades in (DISPERSO, HOMOGENEO):
            texto = self._texto(unidades)
            self.assertNotIn("R$", texto)
            self.assertNotIn("%", texto)

    def test_com_numeros_traz_os_dois_custos(self):
        texto = self._texto(DISPERSO, incluir_numeros=True)
        self.assertIn("R$ 40,00", texto)   # praça cara
        self.assertIn("R$ 1,00", texto)    # praça barata

    def test_toda_chave_de_passo_do_grupo_tem_texto_e_prefixo(self):
        chaves = ({chave for _, chave in rules._PROXIMO_PASSO_GRUPO}
                  | {rules.PASSO_GRUPO_PADRAO})
        self.assertEqual(chaves - set(templates._PASSO_GRUPO), set())
        self.assertEqual(chaves - set(templates._PREFIXO_OBJETIVO_GRUPO), set())

    def test_determinismo(self):
        self.assertEqual(self._texto(DISPERSO), self._texto(DISPERSO))

    def test_cabe_no_orcamento_mesmo_com_nome_de_praca_no_limite(self):
        # O bloco de dispersão interpola dois nomes, e o campo do formulário
        # aceita 120 caracteres cada.
        longo = "M" * 120
        unidades = [_unidade(longo + " A", 10, 400.0),
                    _unidade(longo + " B", 50, 50.0)]
        for numeros in (False, True):
            with self.subTest(numeros=numeros):
                self.assertLessEqual(len(self._texto(unidades,
                                                     incluir_numeros=numeros)),
                                     templates.LIMITE_PDF_GRUPO)

    def test_dispersao_e_a_ultima_a_sair(self):
        original = templates.LIMITE_PDF_GRUPO
        try:
            templates.LIMITE_PDF_GRUPO = 700
            blocos = self._texto(DISPERSO).split("\n\n")
            self.assertEqual(len(blocos), 3)
            self.assertTrue(blocos[0].startswith(
                "<b>%s</b>" % templates.ROTULO_LEITURA))
        finally:
            templates.LIMITE_PDF_GRUPO = original
