# -*- coding: utf-8 -*-
"""
Reescrita por IA — a mesma garantia nas quatro frentes de texto.

Uma função para as quatro (`redator_ia.reescrever`), porque o trabalho é o
mesmo: pegar o texto que o motor determinístico escreveu e escrevê-lo melhor
**sem tocar em nenhum número**. Essa promessa não é confiança no modelo, é
mecânica — `_validar_reescrita` recusa qualquer resposta que introduza um
valor que não estava no texto original.

`_chamar` é o único ponto de I/O do projeto e é sempre patcheado: a suíte roda
offline e nunca gasta crédito.
"""

import io
from unittest import mock

from django.test import SimpleTestCase, TestCase

from relatorios import redator_ia
from relatorios.tests_desempenho import planilha


NOVA_DESEMPENHO = """*Desempenho*

No intervalo de 30/07/2026 a 28/08/2026, o principal resultado da campanha foi a geração de 393 conversas, com custo médio de R$ 4,52 por contato iniciado.

A entrega chegou a 22.498 pessoas por meio de 100.012 impressões, com frequência de 4,45 e CPM de R$ 17,78. Dentro do volume observado, 288 vieram de novos contatos, participação equivalente a 73%.

A leitura do período combina continuidade na geração de oportunidades e presença relevante de pessoas que ainda não haviam iniciado contato. A recorrência da exposição permanece como o principal ponto para acompanhar ao lado da evolução do custo.

Para este momento, o cenário é positivo e indica continuidade no trabalho de mídia. Vamos observar se esse comportamento se mantém nas próximas leituras e ajustar a comunicação caso apareça uma mudança relevante."""


class GuardaDosNumerosTest(SimpleTestCase):
    """A checagem que transforma "não invente dado" em garantia.

    O modelo pode reordenar frases e trocar palavras. Não pode somar, deduzir,
    projetar nem arredondar — qualquer uma dessas introduz um número que não
    estava lá, e a resposta inteira é descartada.
    """

    ORIGINAL = ("Foram 393 conversas, a R$ 4,52 cada. "
                "A entrega alcançou 22.498 pessoas, com frequência de 4,45.")

    def test_reescrita_fiel_passa(self):
        boa = ("As 393 conversas saíram a R$ 4,52. A campanha alcançou "
               "22.498 pessoas, com frequência de 4,45.")
        self.assertEqual(redator_ia._validar_reescrita(boa, self.ORIGINAL),
                         boa)

    def test_total_somado_pelo_modelo_e_recusado(self):
        """393 × R$ 4,52 dá R$ 1.776 — número correto, e ainda assim inventado:
        ele não estava no texto que o motor escreveu."""
        with self.assertRaises(redator_ia.ErroDeIA) as ctx:
            redator_ia._validar_reescrita(
                "Foram 393 conversas, R$ 1.776 no total.", self.ORIGINAL)
        self.assertIn("1.776", str(ctx.exception))
        self.assertEqual(ctx.exception.motivo, "formato")

    def test_percentual_deduzido_e_recusado(self):
        with self.assertRaises(redator_ia.ErroDeIA):
            redator_ia._validar_reescrita(
                "Foram 393 conversas, alta de 12% sobre o mês anterior.",
                self.ORIGINAL)

    def test_numero_alterado_e_recusado(self):
        """Um dígito trocado é o pior caso: passa despercebido na leitura."""
        with self.assertRaises(redator_ia.ErroDeIA):
            redator_ia._validar_reescrita(
                "Foram 398 conversas, a R$ 4,52 cada.", self.ORIGINAL)

    def test_pontuacao_no_fim_da_frase_nao_conta_como_numero(self):
        """"R$ 4,52." no fim do parágrafo é o mesmo 4,52 do meio do texto — o
        ponto final não pode fazer a guarda disparar."""
        self.assertTrue(redator_ia._validar_reescrita(
            "A campanha alcançou 22.498 pessoas. Foram 393 conversas, a "
            "R$ 4,52.", self.ORIGINAL))

    def test_marcacao_que_o_whatsapp_nao_renderiza_e_recusada(self):
        for ruim in ("# Resumo\nForam 393 conversas.",
                     "- Foram 393 conversas.",
                     "1. Foram 393 conversas."):
            with self.subTest(ruim=ruim):
                with self.assertRaises(redator_ia.ErroDeIA):
                    redator_ia._validar_reescrita(ruim, self.ORIGINAL)

    def test_negrito_do_whatsapp_passa(self):
        self.assertTrue(redator_ia._validar_reescrita(
            "*Foram 393 conversas*, a R$ 4,52 cada. Alcance de 22.498 "
            "pessoas, frequência de 4,45.", self.ORIGINAL))

    def test_resposta_vazia_e_recusada(self):
        with self.assertRaises(redator_ia.ErroDeIA):
            redator_ia._validar_reescrita("   ", self.ORIGINAL)

    def test_cerca_de_codigo_e_removida_e_nao_recusada(self):
        limpo = redator_ia._validar_reescrita(
            "```\nForam 393 conversas, a R$ 4,52.\n```", self.ORIGINAL)
        self.assertFalse(limpo.startswith("`"))


class ChamadaDaReescritaTest(SimpleTestCase):
    """O que o modelo recebe — e o que ele nunca recebe."""

    def _reescrever(self, resposta="Outra redação com 393 conversas."):
        with mock.patch.object(redator_ia, "_chamar",
                               return_value=resposta) as chamar:
            with mock.patch.object(redator_ia, "disponivel",
                                   return_value=True):
                texto = redator_ia.reescrever(
                    "Foram 393 conversas.", {"Conversas": "393"},
                    redator_ia.PROMPT_REESCRITA_LEITURA)
        return texto, chamar

    def test_o_modelo_recebe_o_texto_e_os_numeros(self):
        _, chamar = self._reescrever()
        conteudo = chamar.call_args[0][0][1]["content"]
        self.assertIn("texto_atual", conteudo)
        self.assertIn("numeros_do_periodo", conteudo)
        self.assertIn("393", conteudo)

    def test_o_prompt_proibe_alterar_e_acrescentar_numero(self):
        _, chamar = self._reescrever()
        sistema = chamar.call_args[0][0][0]["content"]
        self.assertIn("Não altere nenhum número", sistema)
        self.assertIn("Não acrescente número nenhum", sistema)
        self.assertIn("Não invente causa", sistema)
        # E a parte de cima diz o que ESTE texto está tentando fazer — é
        # exatamente o que o prompt genérico não dizia.
        self.assertIn("Ponto comercial", sistema)

    def test_sem_chave_levanta_erro_definitivo(self):
        with mock.patch.object(redator_ia, "disponivel", return_value=False):
            with self.assertRaises(redator_ia.ErroDeIA) as ctx:
                redator_ia.reescrever(
                    "x", {}, redator_ia.PROMPT_REESCRITA_LEITURA)
        self.assertIn(ctx.exception.motivo, redator_ia.DEFINITIVOS)


class BotoesDasTelasTest(TestCase):
    """§ do pedido: "Ler planilhas" na tela 01 de todas, "Ler material" na
    Leitura Rápida, e "Reescrever com IA" como ação da tela 02."""

    ROTULOS = {"/geral/": "Ler planilhas", "/desempenho/": "Ler planilhas",
               "/verba/": "Ler planilhas", "/rastreamento/": "Ler planilhas",
               "/leitura/": "Ler material"}

    def test_a_tela_01_de_cada_frente_tem_o_rotulo_padrao(self):
        for rota, rotulo in self.ROTULOS.items():
            with self.subTest(rota=rota):
                html = self.client.get(rota).content.decode()
                self.assertIn(f'<span id="btn-rotulo">{rotulo}</span>', html)

    def test_a_leitura_rapida_nao_diz_planilhas(self):
        """Ela come planilha OU print: "planilhas" seria metade do que ela
        aceita, e quem chegou com um print leria isso como "aqui não"."""
        html = self.client.get("/leitura/").content.decode()
        self.assertNotIn('<span id="btn-rotulo">Ler planilhas</span>', html)


class ReescritaNasTelasTest(TestCase):
    """O botão em cada tela 02, o que ele faz e o que ele preserva quando
    falha."""

    def _abrir(self, rota, arquivo=None):
        """Sobe a planilha e devolve a URL da tela 02."""
        destino = {"/desempenho/": "/desempenho/analise/",
                   "/leitura/": "/leitura/mensagem/"}[rota]
        campo = "arquivos" if rota == "/leitura/" else "arquivo"
        self.client.post(rota, {"cliente": "TIM Brasil",
                                campo: arquivo or planilha()})
        return destino

    def test_o_botao_aparece_nas_duas_frentes_de_texto(self):
        for rota, campo in (("/desempenho/", "desempenho_ia"),
                            ("/leitura/", "leitura_ia")):
            with self.subTest(rota=rota):
                destino = self._abrir(rota)
                with mock.patch.object(redator_ia, "disponivel",
                                       return_value=True):
                    html = self.client.get(destino).content.decode()
                self.assertIn(f'name="{campo}"', html)
                self.assertIn("Reescrever com IA", html)

    def test_sem_chave_o_botao_nao_aparece(self):
        destino = self._abrir("/desempenho/")
        with mock.patch.object(redator_ia, "disponivel", return_value=False):
            html = self.client.get(destino).content.decode()
        self.assertNotIn("Reescrever com IA", html)

    def test_a_reescrita_substitui_o_texto_na_tela(self):
        destino = self._abrir("/desempenho/")
        with mock.patch.object(redator_ia, "_chamar",
                               return_value=NOVA_DESEMPENHO):
            with mock.patch.object(redator_ia, "disponivel",
                                   return_value=True):
                r = self.client.post(destino, {"desempenho_ia": "1"})
        self.assertContains(r, "reescrita pela IA")
        self.assertContains(r, "Nova versão gerada com IA.")
        self.assertIn(NOVA_DESEMPENHO, r.content.decode())

    def test_desempenho_envia_system_e_user_prompts_especificos(self):
        destino = self._abrir("/desempenho/")
        with mock.patch.object(redator_ia, "_chamar",
                               return_value=NOVA_DESEMPENHO) as chamar:
            with mock.patch.object(redator_ia, "disponivel", return_value=True):
                self.client.post(destino, {"desempenho_ia": "1"})
        mensagens = chamar.call_args[0][0]
        self.assertEqual(mensagens[0]["content"],
                         redator_ia.PROMPT_REESCRITA_DESEMPENHO)
        usuario = mensagens[1]["content"]
        self.assertIn("DADOS E FATOS VALIDADOS", usuario)
        self.assertIn("RESULTADO PRINCIPAL\n393", usuario)
        self.assertIn("ALCANCE\n22.498", usuario)
        self.assertIn("TEXTO DETERMINÍSTICO — REFERÊNCIA FACTUAL", usuario)
        self.assertIn("quarto parágrafo consultivo", usuario)
        self.assertNotIn("texto_atual", usuario)
        self.assertNotIn("numeros_do_periodo", usuario)

    def test_voltar_ao_motor_desfaz_num_clique(self):
        """Sem isto, desfazer uma reescrita de que o operador não gostou
        exigiria reenviar o arquivo."""
        destino = self._abrir("/desempenho/")
        with mock.patch.object(redator_ia, "_chamar",
                               return_value=NOVA_DESEMPENHO):
            with mock.patch.object(redator_ia, "disponivel",
                                   return_value=True):
                self.client.post(destino, {"desempenho_ia": "1"})
                r = self.client.post(destino, {"voltar_ao_motor": "1"})
        self.assertContains(r, "De volta ao")
        self.assertNotIn(NOVA_DESEMPENHO, r.content.decode())

    def test_desempenho_recusa_reescrita_sem_o_titulo(self):
        destino = self._abrir("/desempenho/")
        sem_titulo = NOVA_DESEMPENHO.removeprefix("*Desempenho*\n\n")
        with mock.patch.object(redator_ia, "_chamar", return_value=sem_titulo):
            with mock.patch.object(redator_ia, "disponivel", return_value=True):
                r = self.client.post(destino, {"desempenho_ia": "1"})
        self.assertContains(r, "não começou com *Desempenho*")
        self.assertTrue(r.context["texto"].startswith("*Desempenho*\n\n"))

    def test_desempenho_recusa_reescrita_que_omite_numero(self):
        destino = self._abrir("/desempenho/")
        sem_alcance = NOVA_DESEMPENHO.replace("22.498", "o público alcançado")
        with mock.patch.object(redator_ia, "_chamar", return_value=sem_alcance):
            with mock.patch.object(redator_ia, "disponivel", return_value=True):
                r = self.client.post(destino, {"desempenho_ia": "1"})
        self.assertContains(r, "omitiu número do cálculo")
        self.assertIn("22.498", r.context["texto"])

    def test_desempenho_recusa_reescrita_que_fala_em_conjunto(self):
        destino = self._abrir("/desempenho/")
        com_conjunto = NOVA_DESEMPENHO.replace("a campanha", "o conjunto", 1)
        with mock.patch.object(redator_ia, "_chamar",
                               return_value=com_conjunto) as chamar:
            with mock.patch.object(redator_ia, "disponivel", return_value=True):
                r = self.client.post(destino, {"desempenho_ia": "1"})
        self.assertEqual(chamar.call_count, 2)
        self.assertContains(r, "citou conjunto")
        self.assertNotIn("o conjunto", r.context["texto"].lower())

    def test_primeiro_clique_refaz_resposta_invalida_sem_aplicar_selecao(self):
        destino = self._abrir("/desempenho/")
        self.assertNotIn("campanhas", self.client.session["desempenho_apex"])
        invalida = NOVA_DESEMPENHO.replace("a campanha", "o conjunto", 1)
        with mock.patch.object(redator_ia, "_chamar",
                               side_effect=[invalida,
                                            NOVA_DESEMPENHO]) as chamar:
            with mock.patch.object(redator_ia, "disponivel", return_value=True):
                r = self.client.post(destino, {"desempenho_ia": "1"})
        self.assertEqual(chamar.call_count, 2)
        self.assertContains(r, "Nova versão gerada com IA.")
        self.assertEqual(r.context["texto"], NOVA_DESEMPENHO)
        reforco = chamar.call_args_list[1][0][0][1]["content"]
        self.assertIn("CORREÇÃO OBRIGATÓRIA", reforco)

    def test_desempenho_exige_quatro_paragrafos_depois_do_titulo(self):
        destino = self._abrir("/desempenho/")
        sem_quarto = "\n\n".join(NOVA_DESEMPENHO.split("\n\n")[:-1])
        with mock.patch.object(redator_ia, "_chamar", return_value=sem_quarto):
            with mock.patch.object(redator_ia, "disponivel", return_value=True):
                r = self.client.post(destino, {"desempenho_ia": "1"})
        self.assertContains(r, "não veio com os quatro parágrafos")
        self.assertNotIn(sem_quarto, r.context["texto"])

    def test_desempenho_exige_ultimo_paragrafo_sem_numeros(self):
        destino = self._abrir("/desempenho/")
        blocos = NOVA_DESEMPENHO.split("\n\n")
        blocos[-1] = ("Para este momento, vamos acompanhar as 393 conversas "
                      "nas próximas leituras.")
        com_metrica_no_fim = "\n\n".join(blocos)
        with mock.patch.object(redator_ia, "_chamar",
                               return_value=com_metrica_no_fim):
            with mock.patch.object(redator_ia, "disponivel", return_value=True):
                r = self.client.post(destino, {"desempenho_ia": "1"})
        self.assertContains(r, "último parágrafo repetiu números")
        self.assertNotIn(com_metrica_no_fim, r.context["texto"])

    def test_falha_da_ia_preserva_o_texto_do_motor(self):
        """O texto do cálculo é refeito a cada renderização — ele nunca saiu
        da tela, então falhar não custa relatório nenhum."""
        destino = self._abrir("/desempenho/")
        erro = redator_ia.ErroDeIA("A OpenAI recusou por excesso.", "limite")
        with mock.patch.object(redator_ia, "_chamar", side_effect=erro):
            with mock.patch.object(redator_ia, "disponivel",
                                   return_value=True):
                r = self.client.post(destino, {"desempenho_ia": "1"})
        self.assertContains(r, "excesso")
        self.assertContains(r, "393")

    def test_reescrita_que_inventa_numero_e_recusada_na_tela(self):
        destino = self._abrir("/leitura/")
        with mock.patch.object(redator_ia, "_chamar",
                               return_value="Foram 393 conversas, R$ 9.999 "
                                            "no total."):
            with mock.patch.object(redator_ia, "disponivel",
                                   return_value=True):
                r = self.client.post(destino, {"leitura_ia": "1"})
        self.assertContains(r, "não está no cálculo")
        # O aviso CITA o número recusado — é o que torna a recusa auditável.
        # O que não pode é ele ter entrado no texto que vai para o cliente.
        html = r.content.decode()
        campo = html.split('id="txt-leitura"')[1].split("</textarea>")[0]
        self.assertNotIn("9.999", campo)


class VerbaSemRecalcularTest(TestCase):
    """O *Recalcular* saiu; a base interna continua editável e é aplicada pelo
    próprio botão de IA, que já recalculava antes de escrever."""

    def _abrir(self):
        from relatorios.tests_verba import CAMPANHAS, _anexo
        self.client.post("/verba/", {
            "cliente": "Rei do Celular", "orcamento": "990,00",
            "periodicidade": "mensal", "estrutura": "cbo",
            "arquivo": _anexo("campanhas.xlsx", CAMPANHAS)})
        return "/verba/fechamento/"

    def test_o_botao_de_recalcular_saiu_da_tela(self):
        with mock.patch.object(redator_ia, "disponivel", return_value=True):
            html = self.client.get(self._abrir()).content.decode()
        self.assertNotIn('name="recalcular"', html)
        self.assertNotIn(">Recalcular<", html)

    def test_a_reescrita_continua_sendo_a_acao_da_tela(self):
        with mock.patch.object(redator_ia, "disponivel", return_value=True):
            html = self.client.get(self._abrir()).content.decode()
        self.assertIn('name="mensagem_ia"', html)
        self.assertIn("Reescrever com IA", html)

    def test_a_base_interna_saiu_da_tela(self):
        """A tela 02 deixou de editar dado: o que muda ali agora é só o TEXTO,
        e só pelo botão de IA. Contratado errado é um envio errado."""
        with mock.patch.object(redator_ia, "disponivel", return_value=True):
            html = self.client.get(self._abrir()).content.decode()
        self.assertNotIn("Base interna", html)
        self.assertNotIn('name="orcamento"', html)
        self.assertNotIn('name="periodicidade"', html)

    def test_a_reescrita_nao_precisa_mais_do_formulario(self):
        """Sem base interna, o POST leva só o nome do botão."""
        destino = self._abrir()
        # Só números que o motor produziu: a guarda descarta a
        # resposta inteira ao ver um valor que não estava no original.
        nova = ("Passando o fechamento pra confirmar\n\n"
                "*Contratado:* R$ 990/mês\n*Equivale a:* R$ 32/dia\n"
                "*Período de 01/08 a 24/08:* 24 dias\n"
                "*Previsto no período:* R$ 766\n*Gasto:* R$ 740\n\n"
                "Podemos seguir assim?")
        with mock.patch.object(redator_ia, "_chamar", return_value=nova):
            with mock.patch.object(redator_ia, "disponivel",
                                   return_value=True):
                r = self.client.post(destino, {"mensagem_ia": "1"})
        self.assertContains(r, "reescrita pela IA")


    def test_a_verba_tambem_desfaz_num_clique(self):
        """Ela era a única sem volta: quem devolvia o texto do motor era o
        *Recalcular*, de tabela. Com ele fora, a volta virou botão explícito —
        que é o que ela sempre foi."""
        destino = self._abrir()
        # Só números que o motor produziu: a guarda descarta a
        # resposta inteira ao ver um valor que não estava no original.
        nova = ("Passando o fechamento pra confirmar\n\n"
                "*Contratado:* R$ 990/mês\n*Equivale a:* R$ 32/dia\n"
                "*Período de 01/08 a 24/08:* 24 dias\n"
                "*Previsto no período:* R$ 766\n*Gasto:* R$ 740\n\n"
                "Podemos seguir assim?")
        with mock.patch.object(redator_ia, "_chamar", return_value=nova):
            with mock.patch.object(redator_ia, "disponivel",
                                   return_value=True):
                r = self.client.post(destino, {"mensagem_ia": "1"})
                self.assertContains(r, "reescrita pela IA")
                r = self.client.post(destino, {"voltar_ao_motor": "1"})
        self.assertContains(r, "do cálculo")
        self.assertNotContains(r, "reescrita pela IA")


class SuperficieDaReescritaTest(SimpleTestCase):
    """Uma implementação só, para as quatro frentes."""

    def test_as_quatro_views_usam_a_mesma_funcao(self):
        """Uma máquina, quatro prompts. As regras que impedem a invenção de
        dado passaram a valer também na verba, que até 30/08/2026 tinha
        caminho próprio e ficava sem a guarda dos números."""
        from relatorios import (views_desempenho, views_leitura,
                                views_rastreamento, views_verba)
        for modulo in (views_desempenho, views_leitura, views_rastreamento,
                       views_verba):
            fonte = io.open(modulo.__file__, encoding="utf-8").read()
            with self.subTest(modulo=modulo.__name__):
                self.assertIn("redator_ia.reescrever", fonte)

    def test_cada_frente_manda_o_seu_proprio_prompt(self):
        """Um prompt por análise: o genérico reescrevia bem um texto que ele
        não sabia o que era."""
        from relatorios import (views_desempenho, views_leitura,
                                views_rastreamento, views_verba)
        for modulo, prompt in (
                (views_desempenho, "PROMPT_REESCRITA_DESEMPENHO"),
                (views_leitura, "PROMPT_REESCRITA_LEITURA"),
                (views_rastreamento, "PROMPT_REESCRITA_RASTREAMENTO"),
                (views_verba, "PROMPT_REESCRITA_VERBA")):
            fonte = io.open(modulo.__file__, encoding="utf-8").read()
            with self.subTest(modulo=modulo.__name__):
                self.assertIn(prompt, fonte)

    def test_so_desempenho_monta_mensagem_usuario_especifica(self):
        from relatorios import (views_desempenho, views_leitura,
                                views_rastreamento, views_verba)
        desempenho = io.open(views_desempenho.__file__, encoding="utf-8").read()
        self.assertIn("mensagem_usuario=", desempenho)
        for modulo in (views_leitura, views_rastreamento, views_verba):
            fonte = io.open(modulo.__file__, encoding="utf-8").read()
            with self.subTest(modulo=modulo.__name__):
                self.assertNotIn("mensagem_usuario=", fonte)

    def test_outros_prompts_nao_herdam_o_contrato_de_quatro_paragrafos(self):
        for prompt in (redator_ia.PROMPT_REESCRITA_LEITURA,
                       redator_ia.PROMPT_REESCRITA_RASTREAMENTO,
                       redator_ia.PROMPT_REESCRITA_VERBA):
            with self.subTest(prompt=prompt[:40]):
                self.assertNotIn("PARÁGRAFO 4", prompt)
                self.assertIn("REGRAS ABSOLUTAS", prompt)

    def test_a_reescrita_nunca_recebe_o_arquivo(self):
        """O modelo não recebe o que ele poderia inventar: só os números que
        já estão no texto que ele vai reescrever."""
        fonte = io.open(redator_ia.__file__, encoding="utf-8").read()
        corpo = fonte.split("def reescrever(")[1].split("\ndef ")[0]
        for proibido in ("arquivo", "planilha", "load_workbook", "registros"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, corpo)
