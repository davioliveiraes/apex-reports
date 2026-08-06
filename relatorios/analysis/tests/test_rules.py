# -*- coding: utf-8 -*-
"""
Testes do motor de regras. `unittest` puro — nada aqui toca Django, e por
isso rodam tanto por `manage.py test relatorios` quanto por qualquer runner
que descubra `test_*`.
"""
import unittest

from .. import rules
from ..benchmarks import ATENCAO, BOM, CPA_POR_PERFIL, OTIMO, Perfil

# Caso de referência: DoctorCell Santa Maria, 01/07 a 31/07/2026.
REFERENCIA = {
    "investimento": 644.98, "alcance": 16279, "impressoes": 57965,
    "frequencia": 3.56, "cpm": 11.13, "resultados": 344, "cpa": 1.87,
    "campanhas": [{"nome": "wpp-19.06.abo", "resultados": 344}],
}


def _metricas(**mudancas):
    """Referência com os campos trocados — mantém o resto plausível para que
    cada teste isole uma variável só."""
    return dict(REFERENCIA, **mudancas)


class CasoDeReferenciaTest(unittest.TestCase):

    def setUp(self):
        self.av = rules.avaliar(REFERENCIA, perfil=Perfil.VAREJO_CELULAR)

    def test_classificacao_e_motivo(self):
        self.assertEqual(self.av.classificacao, OTIMO)
        self.assertEqual(self.av.motivo_principal, rules.CPA_OTIMO)

    def test_sinais_esperados(self):
        for sinal in ("cpa_otimo", "cpm_muito_competitivo",
                      "frequencia_saturada", "campanha_unica",
                      "meta_cpa_indefinida", "aguardando_dados_de_venda",
                      "sem_periodo_anterior"):
            self.assertIn(sinal, self.av.sinais)

    def test_proximo_passo(self):
        self.assertEqual(self.av.proximo_passo, "ampliar_publico_e_criativos")

    def test_perfil_e_meta_no_resultado(self):
        self.assertEqual(self.av.perfil, "varejo_celular")
        self.assertFalse(self.av.meta_definida)


class FaixasDeCpaTest(unittest.TestCase):
    """As fronteiras de cada perfil, dos dois lados. Volume alto de propósito:
    o rebaixamento por amostra pequena tem teste próprio."""

    def test_fronteiras_de_todos_os_perfis(self):
        for perfil, (otimo, bom) in CPA_POR_PERFIL.items():
            casos = [(otimo, OTIMO), (otimo + 0.01, BOM),
                     (bom, BOM), (bom + 0.01, ATENCAO)]
            for cpa, esperado in casos:
                with self.subTest(perfil=perfil.value, cpa=cpa):
                    av = rules.avaliar(_metricas(cpa=cpa, resultados=500),
                                       perfil=perfil)
                    self.assertEqual(av.classificacao, esperado)

    def test_perfil_desconhecido_cai_no_padrao(self):
        av = rules.avaliar(_metricas(cpa=4.00, resultados=500),
                           perfil="nao_existe")
        self.assertEqual(av.perfil, "varejo_celular")
        self.assertEqual(av.classificacao, OTIMO)

    def test_perfil_aceita_string(self):
        av = rules.avaliar(_metricas(cpa=10.00, resultados=500),
                           perfil="tim_regional")
        self.assertEqual(av.classificacao, BOM)   # atenção em varejo_celular


class MetaDeCpaTest(unittest.TestCase):
    """Com meta, a faixa fixa do perfil sai de cena."""

    def test_meta_sobrepoe_a_faixa_do_perfil(self):
        # CPA 20,00 é ATENÇÃO em varejo_celular pela faixa fixa (teto 9,00),
        # mas fica em 0,80 da meta — ótimo.
        av = rules.avaliar(_metricas(cpa=20.00, resultados=500),
                           perfil=Perfil.VAREJO_CELULAR, meta_cpa=25.00)
        self.assertEqual(av.classificacao, OTIMO)
        self.assertTrue(av.meta_definida)

    def test_fronteiras_da_razao(self):
        for cpa, esperado in ((9.00, OTIMO), (9.01, BOM),
                              (11.50, BOM), (11.51, ATENCAO)):
            with self.subTest(cpa=cpa):
                av = rules.avaliar(_metricas(cpa=cpa, resultados=500),
                                   meta_cpa=10.00)
                self.assertEqual(av.classificacao, esperado)

    def test_com_meta_nao_sinaliza_pendencia_de_venda(self):
        av = rules.avaliar(_metricas(resultados=500), meta_cpa=5.00)
        self.assertNotIn(rules.META_CPA_INDEFINIDA, av.sinais)
        self.assertNotIn(rules.AGUARDANDO_DADOS_DE_VENDA, av.sinais)


class VolumeMinimoTest(unittest.TestCase):

    def test_amostra_pequena_rebaixa_otimo_para_bom(self):
        av = rules.avaliar(_metricas(resultados=25))
        self.assertEqual(av.classificacao, BOM)
        self.assertEqual(av.motivo_principal, rules.AMOSTRA_PEQUENA)
        # O CPA continua sendo ótimo — o que muda é a confiança na amostra.
        self.assertIn(rules.CPA_OTIMO, av.sinais)
        self.assertIn(rules.AMOSTRA_PEQUENA, av.sinais)

    def test_amostra_pequena_nao_promove_atencao(self):
        av = rules.avaliar(_metricas(cpa=30.00, resultados=25))
        self.assertEqual(av.classificacao, ATENCAO)
        self.assertEqual(av.motivo_principal, rules.CPA_ATENCAO)

    def test_amostra_pequena_nao_rebaixa_bom(self):
        av = rules.avaliar(_metricas(cpa=6.00, resultados=25))
        self.assertEqual(av.classificacao, BOM)
        self.assertEqual(av.motivo_principal, rules.CPA_BOM)

    def test_exatamente_no_minimo_nao_rebaixa(self):
        av = rules.avaliar(_metricas(resultados=30))
        self.assertEqual(av.classificacao, OTIMO)


class SinaisDeApoioNaoClassificamTest(unittest.TestCase):

    def test_cpm_elevado_com_cpa_otimo_continua_otimo(self):
        av = rules.avaliar(_metricas(cpm=80.0, resultados=500))
        self.assertEqual(av.classificacao, OTIMO)
        self.assertIn("cpm_elevado", av.sinais)

    def test_frequencia_saturada_com_cpa_otimo_continua_otimo(self):
        av = rules.avaliar(_metricas(frequencia=9.0, resultados=500))
        self.assertEqual(av.classificacao, OTIMO)

    def test_faixas_de_cpm(self):
        for cpm, sinal in ((12.0, "cpm_muito_competitivo"),
                           (12.01, "cpm_competitivo"),
                           (20.0, "cpm_competitivo"),
                           (20.01, "cpm_normal"),
                           (35.0, "cpm_normal"),
                           (35.01, "cpm_elevado")):
            with self.subTest(cpm=cpm):
                av = rules.avaliar(_metricas(cpm=cpm, resultados=500))
                self.assertIn(sinal, av.sinais)

    def test_faixas_de_frequencia_na_janela_mensal(self):
        for freq, sinal in ((1.49, "frequencia_baixa"),
                            (1.5, "frequencia_saudavel"),
                            (2.5, "frequencia_saudavel"),
                            (2.51, "frequencia_elevada"),
                            (3.5, "frequencia_elevada"),
                            (3.51, "frequencia_saturada")):
            with self.subTest(frequencia=freq):
                av = rules.avaliar(_metricas(frequencia=freq, resultados=500))
                self.assertIn(sinal, av.sinais)


class PeriodoCurtoTest(unittest.TestCase):

    def test_sete_dias_aperta_os_limites_de_frequencia(self):
        # 3,0 em 30 dias é elevada; em 7 dias (limites × 7/30) é saturação.
        mensal = rules.avaliar(_metricas(frequencia=3.0, resultados=500),
                               dias_periodo=30)
        self.assertIn("frequencia_elevada", mensal.sinais)

        semanal = rules.avaliar(_metricas(frequencia=3.0, resultados=500),
                                dias_periodo=7)
        self.assertIn("frequencia_saturada", semanal.sinais)

    def test_periodo_longo_nao_ajusta(self):
        av = rules.avaliar(_metricas(frequencia=2.0, resultados=500),
                           dias_periodo=31)
        self.assertIn("frequencia_saudavel", av.sinais)

    def test_sem_dias_usa_a_janela_cheia(self):
        av = rules.avaliar(_metricas(frequencia=2.0, resultados=500))
        self.assertIn("frequencia_saudavel", av.sinais)


class EstruturaDeCampanhasTest(unittest.TestCase):

    def test_campanha_unica(self):
        av = rules.avaliar(REFERENCIA)
        self.assertIn(rules.CAMPANHA_UNICA, av.sinais)
        self.assertNotIn(rules.MULTIPLAS_CAMPANHAS, av.sinais)

    def test_concentracao_a_partir_de_oitenta_por_cento(self):
        av = rules.avaliar(_metricas(resultados=100, campanhas=[
            {"nome": "A", "resultados": 80}, {"nome": "B", "resultados": 20}]))
        self.assertIn(rules.MULTIPLAS_CAMPANHAS, av.sinais)
        self.assertIn(rules.RESULTADOS_CONCENTRADOS, av.sinais)

    def test_abaixo_de_oitenta_nao_concentra(self):
        av = rules.avaliar(_metricas(resultados=100, campanhas=[
            {"nome": "A", "resultados": 79}, {"nome": "B", "resultados": 21}]))
        self.assertNotIn(rules.RESULTADOS_CONCENTRADOS, av.sinais)

    def test_sem_campanhas_nao_emite_sinal_de_estrutura(self):
        av = rules.avaliar(_metricas(campanhas=[]))
        for sinal in (rules.CAMPANHA_UNICA, rules.MULTIPLAS_CAMPANHAS,
                      rules.RESULTADOS_CONCENTRADOS):
            self.assertNotIn(sinal, av.sinais)


class ColunasOpcionaisTest(unittest.TestCase):

    def test_export_sem_ctr_nao_e_erro(self):
        av = rules.avaliar(_metricas(resultados=500))
        self.assertFalse([s for s in av.sinais if s.startswith("ctr_")])
        self.assertEqual(av.classificacao, OTIMO)

    def test_faixas_de_ctr_quando_a_coluna_vem(self):
        for ctr, sinal in ((0.79, "ctr_baixo"), (0.8, "ctr_normal"),
                           (2.0, "ctr_normal"), (2.01, "ctr_alto")):
            with self.subTest(ctr=ctr):
                av = rules.avaliar(_metricas(ctr=ctr, resultados=500))
                self.assertIn(sinal, av.sinais)

    def test_ctr_zero_ainda_e_um_valor_lido(self):
        # Zero é "ninguém clicou", não "coluna ausente".
        av = rules.avaliar(_metricas(ctr=0.0, resultados=500))
        self.assertIn("ctr_baixo", av.sinais)

    def test_cpa_derivado_do_investimento_quando_ausente(self):
        metricas = _metricas(resultados=200, investimento=400.0)
        metricas.pop("cpa")
        av = rules.avaliar(metricas)           # 400 / 200 = 2,00
        self.assertEqual(av.classificacao, OTIMO)


class SemResultadosTest(unittest.TestCase):
    """Fora do quadro de regras do briefing: sem resultado não há CPA para
    comparar. Verba gasta sem retorno não pode sair como ÓTIMO."""

    def test_periodo_sem_resultado_cai_em_atencao(self):
        av = rules.avaliar(_metricas(resultados=0, cpa=None, cpm=15.0))
        self.assertEqual(av.classificacao, ATENCAO)
        self.assertEqual(av.motivo_principal, rules.SEM_RESULTADOS)
        self.assertEqual(av.proximo_passo, "revisar_segmentacao_e_criativos")

    def test_nao_emite_sinal_de_cpa(self):
        av = rules.avaliar(_metricas(resultados=0, cpa=None, cpm=15.0))
        self.assertFalse([s for s in av.sinais if s.startswith("cpa_")])


class SemInvestimentoTest(unittest.TestCase):
    """Coluna de verba ausente no export: o CPA sairia zero, e zero é mais
    barato que a faixa mais barata de qualquer perfil. O motor tem que recusar
    a leitura em vez de elogiar o que não mediu."""

    def _sem_verba(self, **mudancas):
        metricas = _metricas(cpa=None, investimento=None, **mudancas)
        metricas.pop("cpa")
        metricas.pop("investimento")
        return rules.avaliar(metricas)

    def test_resultado_sem_verba_nao_vira_otimo(self):
        av = self._sem_verba()
        self.assertEqual(av.classificacao, ATENCAO)
        self.assertEqual(av.motivo_principal, rules.SEM_INVESTIMENTO)
        self.assertEqual(av.proximo_passo, "conferir_os_dados_do_periodo")

    def test_investimento_zerado_conta_como_ausente(self):
        av = rules.avaliar(_metricas(investimento=0.0, cpa=0.0))
        self.assertEqual(av.classificacao, ATENCAO)
        self.assertIn(rules.SEM_INVESTIMENTO, av.sinais)

    def test_nao_emite_sinal_de_cpa(self):
        self.assertFalse([s for s in self._sem_verba().sinais
                          if s.startswith("cpa_")])

    def test_sinais_de_apoio_continuam_valendo(self):
        # Frequência e estrutura não dependem de verba — seguem sendo lidos.
        av = self._sem_verba()
        self.assertIn("frequencia_saturada", av.sinais)
        self.assertIn(rules.CAMPANHA_UNICA, av.sinais)

    def test_conferir_dados_vence_todas_as_outras_regras(self):
        av = self._sem_verba(frequencia=4.0, cpm=80.0)
        self.assertEqual(av.proximo_passo, "conferir_os_dados_do_periodo")

    def test_periodo_sem_verba_e_sem_resultado_e_sem_resultados(self):
        # Conta que não rodou: o motivo é a falta de resultado, não a de verba.
        av = rules.avaliar(_metricas(resultados=0, cpa=None, investimento=0.0))
        self.assertEqual(av.motivo_principal, rules.SEM_RESULTADOS)


class ProximoPassoTest(unittest.TestCase):

    def _passo(self, **mudancas):
        return rules.avaliar(_metricas(resultados=500, **mudancas)).proximo_passo

    def test_saturacao_com_cpa_favoravel_amplia(self):
        self.assertEqual(self._passo(frequencia=4.0),
                         "ampliar_publico_e_criativos")

    def test_saturacao_com_cpa_em_atencao_renova_e_abre(self):
        self.assertEqual(self._passo(frequencia=4.0, cpa=30.0),
                         "renovar_criativos_e_abrir_segmentacao")

    def test_cpm_elevado_testa_criativos(self):
        self.assertEqual(self._passo(frequencia=2.0, cpm=80.0),
                         "testar_novos_criativos")

    def test_frequencia_baixa_com_cpa_otimo_escala(self):
        self.assertEqual(self._passo(frequencia=1.1), "escalar_verba")

    def test_frequencia_baixa_com_cpa_em_atencao_nao_escala(self):
        self.assertEqual(self._passo(frequencia=1.1, cpa=30.0),
                         "revisar_segmentacao_e_criativos")

    def test_concentracao_redistribui(self):
        passo = self._passo(frequencia=2.0, campanhas=[
            {"nome": "A", "resultados": 90}, {"nome": "B", "resultados": 10}])
        self.assertEqual(passo, "redistribuir_verba")

    def test_campanha_unica_com_cpa_favoravel_testa_segunda_estrutura(self):
        self.assertEqual(self._passo(frequencia=2.0), "testar_segunda_estrutura")

    def test_padrao_quando_nada_mais_casa(self):
        passo = self._passo(frequencia=2.0, campanhas=[
            {"nome": "A", "resultados": 50}, {"nome": "B", "resultados": 50}])
        self.assertEqual(passo, rules.PASSO_PADRAO)

    def test_saturacao_vem_antes_de_cpm_elevado(self):
        self.assertEqual(self._passo(frequencia=4.0, cpm=80.0),
                         "ampliar_publico_e_criativos")


class PurezaTest(unittest.TestCase):

    def test_mesma_entrada_mesma_saida(self):
        a = rules.avaliar(REFERENCIA)
        b = rules.avaliar(REFERENCIA)
        self.assertEqual(a, b)

    def test_nao_muta_a_entrada(self):
        antes = dict(REFERENCIA)
        rules.avaliar(REFERENCIA)
        self.assertEqual(REFERENCIA, antes)

    def test_periodo_anterior_e_aceito_e_ignorado(self):
        anterior = {"cpa": 0.50, "resultados": 900}
        com = rules.avaliar(_metricas(resultados=500), periodo_anterior=anterior)
        sem = rules.avaliar(_metricas(resultados=500))
        self.assertEqual(com.classificacao, sem.classificacao)
        self.assertEqual(com.proximo_passo, sem.proximo_passo)
        self.assertNotIn(rules.SEM_PERIODO_ANTERIOR, com.sinais)
        self.assertIn(rules.SEM_PERIODO_ANTERIOR, sem.sinais)
