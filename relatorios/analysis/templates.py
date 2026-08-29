# -*- coding: utf-8 -*-
"""
Redação do texto a partir da `Avaliacao` — sem aleatoriedade.

Mesma entrada, mesma saída: nada de sortear variação de frase. O texto sai em
blocos rotulados, separados por linha em branco. Três são fixos e dois
aparecem conforme houver sinal — de 3 a 5 blocos:

    Leitura do período.        veredito + o que o sustenta        (sempre)
    Ponto de atenção.          o sinal que cobra algo do ciclo     (se houver)
    Leitura atual.             o sinal de apoio que sobrou        (se houver)
      ou O que sustentou o resultado., quando não há ponto de atenção
    O que vamos fazer.         ação concreta do próximo ciclo     (sempre)
    Objetivo do próximo ciclo. o degrau seguinte da escada        (sempre)

Cada fragmento existe em duas formas, com e sem número:

    False (PDF)      "O mesmo público já viu os anúncios muitas vezes —
                      sinal de que o alcance atual se esgotou."
    True (WhatsApp)  "Com a frequência em 3,56, o mesmo público já viu os
                      anúncios muitas vezes — o alcance atual se esgotou."

A regra dos números não é "nenhum número": é **não repetir o que a tabela já
mostra**. Número derivado — que o motor calculou e nenhuma tabela do relatório
faz — entra sempre, porque é ele que sustenta um argumento novo. A verba que
saiu sem retorno e quantos contatos ela deveria ter trazido são o caso: estão
em `Avaliacao.derivados`, e aparecem no PDF mesmo com `incluir_numeros=False`.

O leitor é o dono da loja, não um gestor de tráfego: cada métrica vira
consequência de negócio. Sinal negativo vem sempre com o que ele abre como
oportunidade, sem maquiar o problema — saturação não é só desgaste, é
indicação de que há público novo a alcançar.

Restrições de linguagem, todas verificadas em teste:
- status e estrutura de conta (pausar, duplicar, ativar, nome de campanha)
  nunca aparecem: é operação interna da agência. Descrever ESTRATÉGIA —
  concentrar verba, renovar peças, ampliar público, corrigir a captação — é
  permitido e é o que o cliente quer ler;
- nada de promessa de resultado futuro — a ação compromete com AÇÃO e o
  objetivo, com DIREÇÃO. Nunca com número-alvo;
- termo técnico só com explicação em até 4 palavras;
- ATENÇÃO nomeia o problema e apresenta o ajuste, sem otimismo forçado — mas
  sempre com o degrau seguinte declarado no último bloco.

Sobre "custo por resultado": o briefing escreve "custo por conversa", que vale
para as contas de WhatsApp. O mesmo motor atende os perfis `recrutamento`,
`curso` e `b2b`, onde o resultado não é conversa — então o texto usa o termo
neutro, que é também o rótulo da coluna na tabela logo acima no PDF.
"""

from . import contexto as ctx
from . import rules
from .benchmarks import ATENCAO, BOM, OTIMO, REF_GRUPO, REF_META
# Os formatadores moraram aqui até a Leitura Rápida passar a escrever os
# mesmos números nas suas próprias frases. Continuam com o nome privado de
# sempre para não mexer nas dezenas de chamadas deste arquivo.
from .numeros import decimal as _decimal, inteiro as _inteiro  # noqa: F401
from .numeros import moeda as _moeda, percentual as _percentual  # noqa: F401
from .numeros import pt_br as _pt_br  # noqa: F401

PDF, WHATSAPP = "pdf", "whatsapp"

# ----------------------------------------------------------------------
# Orçamento de página
# ----------------------------------------------------------------------
# O texto do MOTOR cabe numa página; o PDF em si aceita mais de uma desde
# 12/08/2026, e é por lá que a análise escrita por IA transborda quando o
# modelo escreve muito. Este orçamento governa só quantos blocos o motor
# escreve — ele não corta nada que venha de fora.
#
# Os tetos são medidos, não estimados: `OrcamentoDePaginaTest` acha por
# bissecção o maior texto que ainda sai em UMA página, gerando PDF de verdade,
# e o teto é esse valor menos 10%. Última medição:
#
#     conta        cabe até 1861 caracteres  ->  teto 1674
#     consolidado  cabe até 1250 caracteres  ->  teto 1125
#
# **Os números caíram em 12/08/2026 e a medição antiga é que estava errada**,
# não o layout novo: a página tinha altura travada com `overflow: hidden`, e o
# texto excedente era desenhado POR CIMA do rodapé sem mudar a contagem de
# páginas. A bissecção media, portanto, o ponto em que o texto ficava ilegível
# — não o ponto em que ele deixava de caber. Agora a seção de análise não se
# parte: ou cabe no que sobrou da página, ou desce inteira para a seguinte.
#
# Na prática nenhum texto do motor chega perto: os reais medem 819 a 1125
# (conta) e 753 a 960 (consolidado). O orçamento é rede de segurança, não
# tesoura de uso diário.
#
# O consolidado é mais apertado porque o donut de composição ocupa mais altura
# que a tabela de campanhas. Os números valem para 5 blocos, o pior caso: cada
# parágrafo a mais custa o respiro entre eles. Contam a string inteira —
# rótulos, marcação e linhas em branco incluídos.
#
# Mexeu no layout do PDF ou no tamanho da fonte? Rode o teste: ele mede de
# novo e falha dizendo o número certo.
LIMITE_PDF = 1674
LIMITE_PDF_GRUPO = 1125

# Ordem de corte quando o texto não cabe: o fixo nunca sai, o apoio sai
# primeiro e o ponto de atenção só depois — o mais relevante fica.
_FIXO, _CORTE_ATENCAO, _CORTE_APOIO = 0, 1, 2

ROTULO_LEITURA = "Leitura do período."
ROTULO_ATENCAO = "Ponto de atenção."
ROTULO_ATUAL = "Leitura atual."
ROTULO_SUSTENTOU = "O que sustentou o resultado."
ROTULO_ACAO = "O que vamos fazer."
ROTULO_OBJETIVO = "Objetivo do próximo ciclo."

# ----------------------------------------------------------------------
# Bloco 1 — leitura do período
# ----------------------------------------------------------------------
_ABERTURA = {
    OTIMO: "O período fechou <b>acima do esperado</b>.",
    BOM: "O período fechou <b>em ritmo saudável</b>.",
    ATENCAO: "O período <b>pede ajuste de rota</b>.",
}

# Quando falta número, o problema é da leitura e não da conta: a abertura por
# classificação culparia a campanha por uma coluna ausente no arquivo.
_ABERTURA_POR_MOTIVO = {
    rules.SEM_INVESTIMENTO: "A leitura do período está <b>incompleta</b>.",
}

# motivo_principal -> (sem número, com número). Sem meta definida, a
# referência é a faixa do perfil, dita ao cliente como "a faixa de trabalho
# da conta" — o cliente não precisa saber que é uma estimativa nossa, mas
# também não pode ouvir que é um número que ele aprovou.
_MOTIVO = {
    rules.CPA_OTIMO: (
        "O custo por resultado ficou bem abaixo da faixa de trabalho da "
        "conta — cada real investido está trazendo contato de cliente a um "
        "preço que dá folga para crescer.",
        "O custo por resultado ficou em <b>{cpa}</b>, bem abaixo da faixa de "
        "trabalho da conta — cada real investido está trazendo contato de "
        "cliente a um preço que dá folga para crescer.",
    ),
    rules.CPA_BOM: (
        "O custo por resultado se manteve dentro da faixa de trabalho da "
        "conta, sem oscilação que exigisse correção de rota — a verba "
        "investida está virando contato real com cliente de forma "
        "previsível, que é a base para crescer com segurança.",
        "O custo por resultado se manteve em <b>{cpa}</b>, dentro da faixa "
        "de trabalho da conta e sem oscilação que exigisse correção de "
        "rota — a verba investida está virando contato real com cliente de "
        "forma previsível, que é a base para crescer com segurança.",
    ),
    rules.CPA_ATENCAO: (
        "O custo por resultado ficou acima da faixa de trabalho da conta: "
        "hoje é preciso investir mais do que o normal para chegar ao mesmo "
        "contato de cliente, e é esse ponto que o próximo ciclo precisa "
        "corrigir.",
        "O custo por resultado ficou em <b>{cpa}</b>, acima da faixa de "
        "trabalho da conta: hoje é preciso investir mais do que o normal "
        "para chegar ao mesmo contato de cliente, e é esse ponto que o "
        "próximo ciclo precisa corrigir.",
    ),
    rules.AMOSTRA_PEQUENA: (
        "O custo por resultado ficou baixo, mas o período trouxe poucos "
        "contatos — é cedo para tratar esse preço como o padrão da conta, e "
        "o próximo ciclo serve para confirmar se ele se sustenta.",
        "O custo por resultado ficou em <b>{cpa}</b>, mas os "
        "<b>{resultados}</b> contatos do período ainda são poucos para "
        "tratar esse preço como o padrão da conta — o próximo ciclo serve "
        "para confirmar se ele se sustenta.",
    ),
    rules.SEM_RESULTADOS: (
        "A verba do período saiu sem gerar contato registrado. Não há custo "
        "por resultado a comparar, e é isso que precisa ser resolvido antes "
        "de qualquer outro ajuste.",
        "Os <b>{investimento}</b> investidos no período saíram sem gerar "
        "contato registrado. Não há custo por resultado a comparar, e é "
        "isso que precisa ser resolvido antes de qualquer outro ajuste.",
    ),
    # Este fragmento é para o operador, não para o cliente: o relatório sai
    # com investimento zerado e não deve ser enviado assim. Ver módulo
    # `rules`, sinal `sem_investimento`.
    rules.SEM_INVESTIMENTO: (
        "O arquivo do período registrou contatos, mas não trouxe o valor "
        "investido. Sem esse número não há custo por resultado a comparar, e "
        "qualquer veredito sobre o período seria chute.",
        "O arquivo do período registrou <b>{resultados}</b> contatos, mas "
        "não trouxe o valor investido. Sem esse número não há custo por "
        "resultado a comparar, e qualquer veredito sobre o período seria "
        "chute.",
    ),
}

# Mesmas chaves, quando a conta tem meta de CPA combinada: a referência deixa
# de ser a faixa estimada e passa a ser a meta, que é o critério de verdade.
_MOTIVO_COM_META = {
    rules.CPA_OTIMO: (
        "O custo por resultado ficou bem abaixo da meta combinada para a "
        "conta — cada real investido está trazendo contato de cliente a um "
        "preço que dá folga para crescer.",
        "O custo por resultado ficou em <b>{cpa}</b>, bem abaixo da meta "
        "combinada para a conta — cada real investido está trazendo contato "
        "de cliente a um preço que dá folga para crescer.",
    ),
    rules.CPA_BOM: (
        "O custo por resultado se manteve dentro da meta combinada para a "
        "conta — a verba investida está virando contato real com cliente de "
        "forma previsível, que é a base para crescer com segurança.",
        "O custo por resultado se manteve em <b>{cpa}</b>, dentro da meta "
        "combinada para a conta — a verba investida está virando contato "
        "real com cliente de forma previsível, que é a base para crescer "
        "com segurança.",
    ),
    rules.CPA_ATENCAO: (
        "O custo por resultado ficou acima da meta combinada para a conta: "
        "hoje é preciso investir mais do que o previsto para chegar ao mesmo "
        "contato de cliente, e é esse ponto que o próximo ciclo precisa "
        "corrigir.",
        "O custo por resultado ficou em <b>{cpa}</b>, acima da meta "
        "combinada para a conta: hoje é preciso investir mais do que o "
        "previsto para chegar ao mesmo contato de cliente, e é esse ponto "
        "que o próximo ciclo precisa corrigir.",
    ),
    rules.AMOSTRA_PEQUENA: (
        "O custo por resultado ficou abaixo da meta combinada, mas o período "
        "trouxe poucos contatos — é cedo para tratar esse preço como o "
        "padrão da conta, e o próximo ciclo serve para confirmar se ele se "
        "sustenta.",
        "O custo por resultado ficou em <b>{cpa}</b>, abaixo da meta "
        "combinada, mas os <b>{resultados}</b> contatos do período ainda são "
        "poucos para tratar esse preço como o padrão da conta — o próximo "
        "ciclo serve para confirmar se ele se sustenta.",
    ),
}

# Mesmas chaves, quando a unidade é lida dentro de um consolidado: a referência
# é o custo médio do grupo no mesmo período — número medido, e que o cliente
# reconhece porque as outras unidades estão na mesma tabela.
_MOTIVO_COM_GRUPO = {
    rules.CPA_OTIMO: (
        "O custo por resultado ficou bem abaixo do custo médio das unidades "
        "no período — esta é das praças que estão comprando contato mais "
        "barato, e o método dela é o que vale copiar para as demais.",
        "O custo por resultado ficou em <b>{cpa}</b>, bem abaixo do custo "
        "médio das unidades no período — esta é das praças que estão "
        "comprando contato mais barato, e o método dela é o que vale copiar "
        "para as demais.",
    ),
    rules.CPA_BOM: (
        "O custo por resultado acompanhou o custo médio das unidades no "
        "período, sem descolar para cima nem para baixo — a praça está "
        "entregando no mesmo padrão do grupo.",
        "O custo por resultado ficou em <b>{cpa}</b>, em linha com o custo "
        "médio das unidades no período — a praça está entregando no mesmo "
        "padrão do grupo.",
    ),
    rules.CPA_ATENCAO: (
        "O custo por resultado ficou acima do custo médio das unidades no "
        "período: esta praça está pagando mais caro por contato do que as "
        "outras do mesmo grupo, no mesmo intervalo e com o mesmo tipo de "
        "campanha.",
        "O custo por resultado ficou em <b>{cpa}</b>, acima do custo médio "
        "das unidades no período: esta praça está pagando mais caro por "
        "contato do que as outras do mesmo grupo, no mesmo intervalo e com o "
        "mesmo tipo de campanha.",
    ),
    rules.AMOSTRA_PEQUENA: (
        "O custo por resultado ficou abaixo do custo médio das unidades, mas "
        "o período trouxe poucos contatos nesta praça — é cedo para tratar "
        "essa vantagem como padrão.",
        "O custo por resultado ficou em <b>{cpa}</b>, abaixo do custo médio "
        "das unidades, mas os <b>{resultados}</b> contatos desta praça ainda "
        "são poucos para tratar essa vantagem como padrão.",
    ),
}

_MOTIVO_POR_REFERENCIA = {REF_META: _MOTIVO_COM_META, REF_GRUPO: _MOTIVO_COM_GRUPO}

# ----------------------------------------------------------------------
# Bloco 2 — sinal secundário
# ----------------------------------------------------------------------
# Frequência e "custo para aparecer na frente do público" (o CPM) são os dois
# termos técnicos que o texto se permite, e nunca sem a explicação junto.
_SECUNDARIO = {
    "frequencia_saturada": (
        "O mesmo público já viu os anúncios muitas vezes — sinal de que o "
        "alcance atual se esgotou. Não é um problema hoje, mas é o fator que "
        "tende a encarecer o custo por resultado se a audiência não for "
        "renovada nas próximas semanas.",
        "Com a frequência em {frequencia}, o mesmo público já viu os "
        "anúncios muitas vezes: o alcance atual se esgotou. Não é um "
        "problema hoje, mas é o fator que tende a encarecer o custo por "
        "resultado se a audiência não for renovada nas próximas semanas.",
    ),
    "frequencia_elevada": (
        "O público já viu os anúncios um bom número de vezes. Ainda há "
        "espaço, mas o teto está próximo — daqui para frente, cada exibição "
        "a mais rende menos que a anterior.",
        "Com a frequência em {frequencia}, o público já viu os anúncios um "
        "bom número de vezes. Ainda há espaço, mas o teto está próximo — "
        "daqui para frente, cada exibição a mais rende menos que a anterior.",
    ),
    "frequencia_baixa": (
        "Cada pessoa alcançada viu os anúncios poucas vezes, o que mostra "
        "que ainda há bastante gente nova ao alcance da conta. É espaço de "
        "crescimento que o período não chegou a usar.",
        "Com a frequência em apenas {frequencia}, cada pessoa alcançada viu "
        "os anúncios poucas vezes: ainda há bastante gente nova ao alcance "
        "da conta. É espaço de crescimento que o período não chegou a usar.",
    ),
    "frequencia_saudavel": (
        "O público viu os anúncios o suficiente para lembrar da marca, sem "
        "cansar. É esse equilíbrio que segura o custo por resultado onde ele "
        "está.",
        "Com a frequência em {frequencia}, o público viu os anúncios o "
        "suficiente para lembrar da marca, sem cansar. É esse equilíbrio que "
        "segura o custo por resultado onde ele está.",
    ),
    "cpm_muito_competitivo": (
        "O custo para aparecer na frente do público está baixo: a mesma "
        "verba comprou bem mais exibição do que o normal. É a condição que "
        "mais favorece ganhar volume sem gastar a mais.",
        "O custo para aparecer na frente do público ficou em {cpm} a cada "
        "mil exibições, bem abaixo do normal. É a condição que mais favorece "
        "ganhar volume sem gastar a mais.",
    ),
    "cpm_competitivo": (
        "O custo para aparecer na frente do público está baixo, o que rendeu "
        "mais exibição pela mesma verba e ajudou a segurar o custo por "
        "resultado.",
        "O custo para aparecer na frente do público ficou em {cpm} a cada "
        "mil exibições, o que rendeu mais exibição pela mesma verba e ajudou "
        "a segurar o custo por resultado.",
    ),
    "cpm_normal": (
        "O custo para aparecer na frente do público ficou no patamar de "
        "sempre — a disputa pelo espaço de anúncio não pesou nem ajudou no "
        "resultado do período.",
        "O custo para aparecer na frente do público ficou em {cpm} a cada "
        "mil exibições, o patamar de sempre — a disputa pelo espaço de "
        "anúncio não pesou nem ajudou no resultado do período.",
    ),
    "cpm_elevado": (
        "O custo para aparecer na frente do público subiu: a disputa pelo "
        "espaço de anúncio ficou mais cara e cada real comprou menos "
        "exibição. Anúncio novo costuma ser o caminho mais rápido de "
        "baratear essa disputa.",
        "O custo para aparecer na frente do público chegou a {cpm} a cada "
        "mil exibições: a disputa pelo espaço de anúncio ficou mais cara e "
        "cada real comprou menos exibição. Anúncio novo costuma ser o "
        "caminho mais rápido de baratear essa disputa.",
    ),
    "ctr_baixo": (
        "Os anúncios estão aparecendo, mas prendendo pouca atenção de quem "
        "vê. Mexer no que a peça mostra é o ajuste de menor custo à mão.",
        "Os anúncios estão aparecendo, mas prendendo pouca atenção: só {ctr} "
        "de quem viu clicou. Mexer no que a peça mostra é o ajuste de menor "
        "custo à mão.",
    ),
    "ctr_alto": (
        "Os anúncios estão prendendo bastante atenção de quem vê — a peça "
        "atual está falando com o público certo.",
        "Os anúncios estão prendendo bastante atenção: {ctr} de quem viu "
        "clicou — a peça atual está falando com o público certo.",
    ),
    "ctr_normal": (
        "Os anúncios estão prendendo a atenção de quem vê dentro do "
        "esperado, sem cobrar ajuste imediato na peça.",
        "Dos que viram os anúncios, {ctr} clicaram — dentro do esperado, sem "
        "cobrar ajuste imediato na peça.",
    ),
    rules.CAMPANHA_UNICA: (
        "Todo o resultado do período veio de uma única estrutura de "
        "campanha, que se mostrou consistente do começo ao fim do mês.",
        "Todo o resultado do período veio de uma única estrutura de "
        "campanha, que se mostrou consistente do começo ao fim do mês.",
    ),
    rules.RESULTADOS_CONCENTRADOS: (
        "Quase todo o resultado veio de uma campanha só; as demais "
        "contribuíram pouco para o total. Concentrar a verba onde ela já "
        "rende é ganho imediato.",
        "Quase todo o resultado veio de uma campanha só; as demais "
        "contribuíram pouco para o total. Concentrar a verba onde ela já "
        "rende é ganho imediato.",
    ),
    rules.MULTIPLAS_CAMPANHAS: (
        "O resultado se distribuiu entre as campanhas no ar, sem a conta "
        "depender de um caminho só para produzir contato.",
        "O resultado se distribuiu entre as campanhas no ar, sem a conta "
        "depender de um caminho só para produzir contato.",
    ),
    # Verba que saiu sem retorno. As duas variantes são iguais de propósito: os
    # números aqui são derivados — a soma da verba parada e quantos contatos
    # ela deveria ter trazido — e nenhuma tabela do relatório os mostra. É
    # justamente isso que autoriza citá-los mesmo na versão sem números.
    rules.VERBA_SEM_RETORNO: (
        "Parte da verba saiu sem gerar contato nenhum: {verba_sem_retorno} no "
        "período, que pelo custo médio da conta deveria ter trazido de "
        "{esperado_min} a {esperado_max} registros. Quando há entrega e não há "
        "resultado, o gargalo está na etapa de captação, não na comunicação "
        "dos anúncios.",
        "Parte da verba saiu sem gerar contato nenhum: {verba_sem_retorno} no "
        "período, que pelo custo médio da conta deveria ter trazido de "
        "{esperado_min} a {esperado_max} registros. Quando há entrega e não há "
        "resultado, o gargalo está na etapa de captação, não na comunicação "
        "dos anúncios.",
    ),
    # Mesma situação sem volume para cobrar: o valor parado é pequeno demais
    # para significar alguma coisa.
    "verba_sem_retorno_curta": (
        "Parte da verba saiu sem gerar contato nenhum: {verba_sem_retorno} no "
        "período. Quando há entrega e não há resultado, o gargalo está na "
        "etapa de captação, não na comunicação dos anúncios.",
        "Parte da verba saiu sem gerar contato nenhum: {verba_sem_retorno} no "
        "período. Quando há entrega e não há resultado, o gargalo está na "
        "etapa de captação, não na comunicação dos anúncios.",
    ),
    # O operador informou que a captação mudou E há verba parada: as duas
    # coisas se explicam, e dizer isso é mais do que a soma das duas frases.
    "captacao_com_verba_parada": (
        "A forma de captação mudou no período, e a verba que passou por ela "
        "saiu sem gerar contato: {verba_sem_retorno}, que pelo custo médio da "
        "conta deveria ter trazido de {esperado_min} a {esperado_max} "
        "registros. O gargalo está no caminho novo, não na comunicação dos "
        "anúncios — que seguem entregando.",
        "A forma de captação mudou no período, e a verba que passou por ela "
        "saiu sem gerar contato: {verba_sem_retorno}, que pelo custo médio da "
        "conta deveria ter trazido de {esperado_min} a {esperado_max} "
        "registros. O gargalo está no caminho novo, não na comunicação dos "
        "anúncios — que seguem entregando.",
    ),
    # Problema operacional ainda aberto: o ponto de atenção é ele, não a
    # métrica. `{problema}` é o sujeito da frase, vindo de `_PROBLEMA_SUJEITO`.
    "problema_aberto": (
        "O gargalo do período está fora da mídia: {problema} não está "
        "funcionando como deveria, e é ali que o contato se perde depois de já "
        "ter custado verba. Enquanto isso não for destravado, melhorar o "
        "anúncio rende pouco.",
        "O gargalo do período está fora da mídia: {problema} não está "
        "funcionando como deveria, e é ali que o contato se perde depois de já "
        "ter custado verba. Enquanto isso não for destravado, melhorar o "
        "anúncio rende pouco.",
    ),
    # Nada mudou na operação e o custo subiu: não há causa interna a apontar,
    # e inventar uma seria pior que admitir que ela está fora daqui.
    "nada_mudou_com_custo_alto": (
        "Nada mudou na operação neste período — mesmo público, mesmas peças, "
        "mesma verba —, e ainda assim o custo por resultado subiu. Quando "
        "isso acontece, a causa costuma estar na disputa pelo espaço de "
        "anúncio, que muda sozinha, e não em algo que tenha sido feito de "
        "diferente.",
        "Nada mudou na operação neste período — mesmo público, mesmas peças, "
        "mesma verba —, e ainda assim o custo por resultado subiu. Quando "
        "isso acontece, a causa costuma estar na disputa pelo espaço de "
        "anúncio, que muda sozinha, e não em algo que tenha sido feito de "
        "diferente.",
    ),
    rules.CAMPANHA_EM_APRENDIZADO: (
        "Há estrutura nova no ar que ainda não gastou o equivalente a um "
        "contato — não deu para julgar se funciona, e por isso ela fica fora "
        "da conta do que rendeu ou deixou de render.",
        "Há estrutura nova no ar que ainda não gastou o equivalente a um "
        "contato: {verba_em_aprendizado} até aqui. Não deu para julgar se "
        "funciona, e por isso ela fica fora da conta do que rendeu.",
    ),
    # Último recurso: export enxuto, sem frequência, custo de exibição,
    # atenção nem estrutura. O bloco existe mesmo assim — a saída tem sempre
    # quatro blocos.
    "_sem_sinal_favoravel": (
        "Fora o custo por resultado, o período correu sem sobressalto: nada "
        "nos números aponta desgaste de público ou entrega mais cara.",
        "Fora o custo por resultado, o período correu sem sobressalto: nada "
        "nos números aponta desgaste de público ou entrega mais cara.",
    ),
    "_sem_sinal_atencao": (
        "O custo é o ponto isolado a resolver: nada mais nos números do "
        "período aponta desgaste de público ou entrega mais cara.",
        "O custo é o ponto isolado a resolver: nada mais nos números do "
        "período aponta desgaste de público ou entrega mais cara.",
    ),
}

# Sinais que cobram algo do ciclo, em ordem de urgência. O primeiro que
# aparecer vira o bloco "Ponto de atenção". As três primeiras chaves são
# compostas — dependem do contexto informado pelo operador — e vêm antes
# porque quem viu a operação sabe mais que a planilha.
_ATENCAO_POR_PRECEDENCIA = (
    "captacao_com_verba_parada",
    "problema_aberto",
    rules.VERBA_SEM_RETORNO,
    "verba_sem_retorno_curta",
    "nada_mudou_com_custo_alto",
    "frequencia_saturada",
    "frequencia_elevada",
    "cpm_elevado",
    "ctr_baixo",
    "_sem_sinal_atencao",
)

# Sinais de apoio, na ordem em que servem de "Leitura atual": frequência
# manda, o custo de entrega entra depois, e a estrutura fecha.
_APOIO_POR_PRECEDENCIA = (
    "frequencia_", "cpm_", "ctr_",
    rules.CAMPANHA_EM_APRENDIZADO,
    rules.RESULTADOS_CONCENTRADOS,
    rules.CAMPANHA_UNICA,
    rules.MULTIPLAS_CAMPANHAS,
)

# ----------------------------------------------------------------------
# Bloco 3 — o que vamos fazer. Compromisso com ação, nunca com número.
# ----------------------------------------------------------------------
_PASSO = {
    "ampliar_publico_e_criativos":
        "Ampliar o público alcançado e colocar novas peças em teste, "
        "renovando o que a audiência vê e abrindo espaço de crescimento sem "
        "desgastar quem já foi impactado.",
    "renovar_criativos_e_abrir_segmentacao":
        "Renovar as peças e abrir a segmentação para além do público atual, "
        "atacando de uma vez o desgaste da audiência e o custo por "
        "resultado.",
    "testar_novos_criativos":
        "Colocar peças novas para rodar, que é o caminho mais direto de "
        "baixar o custo de entrega quando a disputa pelo espaço de anúncio "
        "encarece.",
    "escalar_verba":
        "Aumentar o investimento de forma gradual, aproveitando que ainda há "
        "bastante gente nova ao alcance da conta antes de precisar mexer em "
        "público ou peça.",
    "revisar_segmentacao_e_criativos":
        "Revisar para quem os anúncios estão sendo mostrados e o que as "
        "peças dizem, que são as duas alavancas diretas sobre o custo por "
        "resultado.",
    "corrigir_a_captacao":
        "Refazer o caminho que o interessado percorre depois do clique, que é "
        "onde a verba está parando hoje, e só então voltar a distribuí-la "
        "entre as frentes que já provaram entregar contato.",
    "testar_sem_atribuir_causa":
        "Rodar um teste controlado de público e de peça para achar onde o "
        "custo cede, já que não houve mudança nossa a desfazer — é medindo "
        "que se descobre, não supondo.",
    "redistribuir_verba":
        "Redistribuir a verba entre as campanhas, concentrando onde o custo "
        "por resultado já é menor e reduzindo o que rende pouco.",
    "testar_segunda_estrutura":
        "Colocar no ar uma segunda estrutura de campanha, em paralelo à "
        "atual, para abrir outro caminho de resultado sem mexer no que já "
        "funciona.",
    "conferir_os_dados_do_periodo":
        "Recuperar o valor investido no período e refazer a leitura antes de "
        "decidir qualquer coisa sobre público, verba ou peça.",
    rules.PASSO_PADRAO:
        "Sustentar o ritmo atual e rodar testes pontuais de público e peça, "
        "sem mexer no que está entregando.",
}

# ----------------------------------------------------------------------
# Bloco 4 — objetivo do próximo ciclo (a escada)
# ----------------------------------------------------------------------
# Sempre "o objetivo é" / "buscamos" / "o alvo é": direção, jamais número-alvo
# nem promessa de resultado.
_ESCADA = {
    ATENCAO:
        "o objetivo é trazer o custo por resultado de volta à faixa de "
        "trabalho da conta antes de pensar em aumentar investimento.",
    BOM:
        "buscamos reduzir o custo por resultado e ganhar volume de contatos "
        "mantendo o mesmo nível de investimento.",
    OTIMO:
        "o alvo do próximo ciclo é sustentar esse patamar de custo e "
        "aumentar o volume de contatos sem perder eficiência.",
}

# O problema operacional entra no bloco de ação como primeira frase — é o que
# o cliente quer ler antes de qualquer coisa sobre mídia. Sujeito e situação
# se combinam, em vez de um catálogo de 4 problemas × 3 situações.
_PROBLEMA_SUJEITO = {
    ctx.PROBLEMA_FORMULARIO: "o formulário de cadastro",
    ctx.PROBLEMA_ATENDIMENTO: "o atendimento aos contatos",
    ctx.PROBLEMA_SITE: "o caminho de compra no site",
    ctx.PROBLEMA_ESTOQUE: "a disponibilidade de estoque",
}

# As frases concordam com "a correção" ou usam infinitivo, nunca com o sujeito:
# os sujeitos têm gêneros diferentes ("o formulário", "a disponibilidade"), e
# um particípio fixo produziria "a disponibilidade está sendo corrigido".
_ACAO_PROBLEMA = {
    ctx.PROBLEMA_CORRIGIDO:
        "A correção {de_problema} já foi feita, e o próximo período é o que "
        "vai medir o efeito dela.",
    ctx.PROBLEMA_EM_CORRECAO:
        "A correção {de_problema} está em andamento e é a primeira coisa a "
        "destravar.",
    ctx.PROBLEMA_ABERTO:
        "Destravar {problema} é a prioridade — sem isso, qualquer ajuste de "
        "mídia rende menos do que poderia.",
}

_ESCADA_POR_MOTIVO = {
    rules.SEM_INVESTIMENTO:
        "o objetivo é fechar a leitura do período com o investimento no "
        "lugar, que é o que permite dizer se o custo por contato está bom.",
}

# Liga o objetivo à ação escolhida, para os dois blocos lerem como sequência.
_PREFIXO_OBJETIVO = {
    "ampliar_publico_e_criativos": "Com público ampliado e peças renovadas, ",
    "renovar_criativos_e_abrir_segmentacao":
        "Com peças novas e segmentação mais aberta, ",
    "testar_novos_criativos": "Com peças novas em teste, ",
    "escalar_verba": "Com o investimento subindo de forma controlada, ",
    "revisar_segmentacao_e_criativos":
        "Com público e peças revisados, ",
    "redistribuir_verba": "Com a verba concentrada onde ela já rende mais, ",
    "testar_segunda_estrutura": "Com uma segunda estrutura no ar, ",
    "conferir_os_dados_do_periodo": "Com o número de investimento recuperado, ",
    "corrigir_a_captacao": "Com a captação corrigida, ",
    "testar_sem_atribuir_causa": "Com os testes em campo, ",
    rules.PASSO_PADRAO: "Com o ritmo mantido e testes pontuais em curso, ",
}


# ----------------------------------------------------------------------
# Consolidado — mesmos quatro blocos, um nível acima
# ----------------------------------------------------------------------
_ABERTURA_GRUPO = {
    OTIMO: "O grupo fechou o período <b>acima do esperado</b>.",
    BOM: "O grupo fechou o período <b>em ritmo saudável</b>.",
    ATENCAO: "O grupo <b>pede ajuste de rota</b>.",
}

_MOTIVO_GRUPO = {
    rules.CPA_OTIMO: (
        "Somando todas as unidades, o custo por resultado ficou bem abaixo do "
        "patamar de trabalho do grupo — a operação como um todo está "
        "comprando contato barato.",
        "Somando todas as unidades, o custo por resultado ficou em "
        "<b>{cpa}</b>, bem abaixo do patamar de trabalho do grupo — a "
        "operação como um todo está comprando contato barato.",
    ),
    rules.CPA_BOM: (
        "Somando todas as unidades, o custo por resultado ficou dentro do "
        "patamar de trabalho do grupo — a operação está entregando de forma "
        "previsível no conjunto.",
        "Somando todas as unidades, o custo por resultado ficou em "
        "<b>{cpa}</b>, dentro do patamar de trabalho do grupo — a operação "
        "está entregando de forma previsível no conjunto.",
    ),
    rules.CPA_ATENCAO: (
        "Somando todas as unidades, o custo por resultado ficou acima do "
        "patamar de trabalho do grupo: hoje a operação inteira paga mais do "
        "que deveria por contato.",
        "Somando todas as unidades, o custo por resultado ficou em "
        "<b>{cpa}</b>, acima do patamar de trabalho do grupo: hoje a "
        "operação inteira paga mais do que deveria por contato.",
    ),
}

# Bloco 2 do grupo: a distância entre as unidades. `{melhor}` e `{pior}` são
# nomes de praça, não números — entram nas duas variantes.
_DISPERSAO = {
    (True, True): (
        "As unidades não estão no mesmo ponto: {pior} está pagando bem mais "
        "caro por contato do que {melhor}, no mesmo período e com o mesmo "
        "tipo de campanha. Essa distância é a maior oportunidade do grupo, "
        "porque o que precisa ser feito já está funcionando dentro de casa.",
        "As unidades não estão no mesmo ponto: {pior} paga {cpa_pior} por "
        "contato contra {cpa_melhor} de {melhor}, no mesmo período. Essa "
        "distância é a maior oportunidade do grupo, porque o que precisa ser "
        "feito já está funcionando dentro de casa.",
    ),
    (True, False): (
        "Parte das unidades está puxando o custo do grupo para cima — {pior} "
        "é a que mais pesa. Nenhuma praça se destacou para baixo, então o "
        "ganho virá de corrigir as mais caras, não de copiar alguém.",
        "Parte das unidades está puxando o custo do grupo para cima — {pior}, "
        "com {cpa_pior} por contato, é a que mais pesa. Nenhuma praça se "
        "destacou para baixo, então o ganho virá de corrigir as mais caras.",
    ),
    (False, True): (
        "Nenhuma unidade ficou cara, e {melhor} se destacou comprando contato "
        "mais barato que o resto do grupo — é o padrão que vale examinar para "
        "repetir nas demais.",
        "Nenhuma unidade ficou cara, e {melhor} se destacou com {cpa_melhor} "
        "por contato — é o padrão que vale examinar para repetir nas demais.",
    ),
    (False, False): (
        "As unidades estão todas no mesmo patamar de custo por contato: o "
        "grupo se move junto, sem praça descolada para cima nem para baixo.",
        "As unidades estão todas no mesmo patamar de custo por contato: o "
        "grupo se move junto, sem praça descolada para cima nem para baixo.",
    ),
}

_PASSO_GRUPO = {
    "levar_o_metodo_das_melhores_as_demais":
        "Levantar o que as praças mais baratas estão fazendo de diferente — "
        "público, peça e distribuição de verba — e aplicar isso nas que estão "
        "pagando mais caro por contato.",
    "atacar_as_pracas_mais_caras":
        "Concentrar o trabalho nas praças de custo mais alto, revisando "
        "público e peças antes de mexer em qualquer coisa nas demais.",
    "escalar_as_pracas_mais_baratas":
        "Aumentar a verba onde o contato está saindo mais barato, "
        "aproveitando a folga dessas praças antes de mexer no resto do grupo.",
    rules.PASSO_GRUPO_PADRAO:
        "Rodar o mesmo teste de público e peça em todas as praças ao mesmo "
        "tempo, que é o jeito de mover um grupo que já está alinhado.",
}

_ESCADA_GRUPO = {
    ATENCAO:
        "o objetivo é trazer o custo por contato do grupo de volta ao patamar "
        "de trabalho antes de aumentar investimento em qualquer praça.",
    BOM:
        "buscamos aproximar as praças mais caras do custo das melhores e "
        "ganhar volume no conjunto com o mesmo investimento.",
    OTIMO:
        "o alvo do próximo ciclo é sustentar esse patamar no grupo inteiro e "
        "crescer em volume sem perder a eficiência já conquistada.",
}

_PREFIXO_OBJETIVO_GRUPO = {
    "levar_o_metodo_das_melhores_as_demais":
        "Com o método das melhores praças rodando nas demais, ",
    "atacar_as_pracas_mais_caras": "Com as praças mais caras revisadas, ",
    "escalar_as_pracas_mais_baratas":
        "Com mais verba onde o contato sai mais barato, ",
    rules.PASSO_GRUPO_PADRAO: "Com o mesmo teste rodando em todas as praças, ",
}


def redigir_grupo(avaliacao_grupo, metricas_grupo, *, destino=PDF,
                  incluir_numeros=False):
    """Análise do Período do consolidado, nos mesmos quatro blocos.

    O bloco 2 troca de assunto em relação ao relatório de conta: no grupo o
    que interessa não é frequência nem custo de entrega, é a distância entre
    as praças — que é justamente o que só o consolidado consegue ver.
    """
    ag = avaliacao_grupo
    numeros = _numeros(metricas_grupo)
    rotulo, dispersao = _dispersao(ag, incluir_numeros, numeros)
    blocos = (
        (ROTULO_LEITURA, "%s %s" % (_ABERTURA_GRUPO[ag.grupo.classificacao],
                                    _motivo_grupo(ag, incluir_numeros, numeros)),
         _FIXO),
        # A dispersão é o que só o consolidado enxerga, então ela é a última
        # coisa a sair — mas é a única opcional que existe aqui.
        (rotulo, dispersao, _CORTE_ATENCAO),
        (ROTULO_ACAO, _acao_grupo(ag), _FIXO),
        (ROTULO_OBJETIVO, _PREFIXO_OBJETIVO_GRUPO[ag.proximo_passo]
         + _ESCADA_GRUPO[ag.grupo.classificacao], _FIXO),
    )
    return _formatar(_montar(blocos, destino, LIMITE_PDF_GRUPO), destino)


def _acao_grupo(avaliacao_grupo):
    """Mesma regra da conta: problema operacional declarado abre o bloco."""
    frase = _frase_do_problema(avaliacao_grupo.contexto)
    passo = _PASSO_GRUPO[avaliacao_grupo.proximo_passo]
    return "%s %s" % (frase, passo) if frase else passo


def _motivo_grupo(avaliacao_grupo, incluir_numeros, numeros):
    """`_MOTIVO_GRUPO` cobre os três motivos de CPA; o resto (sem resultado,
    sem investimento, amostra pequena) cai no catálogo da conta, que já diz a
    coisa certa sem falar em unidade."""
    motivo = avaliacao_grupo.grupo.motivo_principal
    par = _MOTIVO_GRUPO.get(motivo) or _MOTIVO[motivo]
    return par[1].format(**numeros) if incluir_numeros else par[0]


def _dispersao(avaliacao_grupo, incluir_numeros, numeros):
    chave = (avaliacao_grupo.tem(rules.UNIDADES_ACIMA),
             avaliacao_grupo.tem(rules.UNIDADES_ABAIXO))
    melhor, pior = avaliacao_grupo.extremos()
    if not melhor:
        # Uma unidade só com CPA: não há distância a descrever.
        chave = (False, False)
    par = _DISPERSAO[chave]
    dados = dict(numeros,
                 melhor=melhor.nome if melhor else "",
                 pior=pior.nome if pior else "",
                 cpa_melhor=_moeda(melhor.cpa) if melhor else "",
                 cpa_pior=_moeda(pior.cpa) if pior else "")
    rotulo = ROTULO_ATENCAO if chave[0] else ROTULO_SUSTENTOU
    texto = par[1] if incluir_numeros else par[0]
    return rotulo, texto.format(**dados)


def redigir(avaliacao, metricas, *, destino=PDF, incluir_numeros=False):
    """Texto final da Análise do Período, em 3 a 5 blocos rotulados.

    Leitura, ação e objetivo são fixos. Entre eles entram o ponto de atenção
    (quando algum sinal cobra algo) e a leitura de apoio (quando sobrou sinal
    que não foi usado no ponto de atenção) — é o que dá ao texto a densidade
    de uma análise em vez de um parecer de três frases.
    """
    numeros = _numeros(metricas, avaliacao)
    blocos = [(ROTULO_LEITURA, "%s %s" % (_abertura(avaliacao),
                                          _motivo(avaliacao, incluir_numeros,
                                                  numeros)), _FIXO)]
    blocos.extend(_blocos_de_apoio(avaliacao, incluir_numeros, numeros))
    blocos.append((ROTULO_ACAO, _acao(avaliacao), _FIXO))
    blocos.append((ROTULO_OBJETIVO, _objetivo(avaliacao), _FIXO))
    return _formatar(_montar(blocos, destino, LIMITE_PDF), destino)


def _montar(blocos, destino, limite):
    """Junta os blocos, descartando os opcionais — do menos relevante para o
    mais — até o texto caber na página.

    O teto vale só para o PDF: a mensagem de WhatsApp não tem página, e cortar
    um bloco ali seria jogar fora conteúdo que cabe.
    """
    escolhidos = list(blocos)
    while True:
        texto = "\n\n".join("<b>%s</b> %s" % (r, t) for r, t, _p in escolhidos)
        if destino != PDF or len(texto) <= limite:
            return texto
        opcionais = [i for i, b in enumerate(escolhidos) if b[2]]
        if not opcionais:
            # Só sobraram os fixos. Cortar mais seria entregar meia leitura —
            # melhor uma segunda página do que uma análise mutilada.
            return texto
        escolhidos.pop(max(opcionais, key=lambda i: escolhidos[i][2]))


def _blocos_de_apoio(avaliacao, incluir_numeros, numeros):
    """Os zero, um ou dois blocos do meio.

    O primeiro é o sinal mais urgente que cobra algo; o segundo é o sinal de
    apoio de maior precedência que ainda não foi usado — e nunca da mesma
    família do primeiro, para não dizer duas vezes a mesma coisa sobre a
    frequência.
    """
    atencao = _sinal_de_atencao(avaliacao)
    apoio = _sinal_de_apoio(avaliacao, exceto=atencao)
    blocos = []
    if atencao:
        blocos.append((ROTULO_ATENCAO,
                       _fragmento(atencao, incluir_numeros, numeros),
                       _CORTE_ATENCAO))
    if apoio:
        # Depois de um ponto de atenção, o segundo bloco é a leitura do
        # cenário; sozinho, ele é o que sustentou o resultado.
        rotulo = ROTULO_ATUAL if atencao else ROTULO_SUSTENTOU
        blocos.append((rotulo, _fragmento(apoio, incluir_numeros, numeros),
                       _CORTE_APOIO))
    if not blocos:
        chave = ("_sem_sinal_atencao" if avaliacao.classificacao == ATENCAO
                 else "_sem_sinal_favoravel")
        rotulo = ROTULO_ATENCAO if avaliacao.classificacao == ATENCAO else ROTULO_SUSTENTOU
        blocos.append((rotulo, _fragmento(chave, incluir_numeros, numeros),
                       _CORTE_APOIO))
    return blocos


def _fragmento(chave, incluir_numeros, numeros):
    par = _SECUNDARIO[chave]
    return (par[1] if incluir_numeros else par[0]).format(**numeros)


def _acao(avaliacao):
    """O passo do motor, precedido — quando há problema operacional declarado —
    da frase que diz em que pé ele está. É o que o cliente quer ler primeiro."""
    frase = _frase_do_problema(avaliacao.contexto)
    passo = _PASSO[avaliacao.proximo_passo]
    return "%s %s" % (frase, passo) if frase else passo


def _frase_do_problema(contexto):
    """A frase de situação do problema operacional, ou "" quando não há."""
    problema = ctx.problema(contexto)
    situacao = (contexto or {}).get("situacao")
    if not problema or situacao not in _ACAO_PROBLEMA:
        return ""
    sujeito = _PROBLEMA_SUJEITO[problema]
    return _ACAO_PROBLEMA[situacao].format(
        problema=sujeito, de_problema=_contrair(sujeito))


def _contrair(sujeito):
    """"o formulário" -> "do formulário"; "a disponibilidade" -> "da …"."""
    artigo, _espaco, resto = sujeito.partition(" ")
    return "d%s %s" % (artigo, resto) if artigo in ("o", "a") else "de " + sujeito


def _sinal_de_atencao(avaliacao):
    """A chave do ponto de atenção, resolvendo antes as compostas — as que só
    existem porque o operador informou algo que a planilha não mostra."""
    tem_verba_parada = avaliacao.tem(rules.VERBA_SEM_RETORNO)
    tem_faixa = bool(avaliacao.derivados.get("resultados_esperados"))
    compostas = {
        "captacao_com_verba_parada": (avaliacao.tem(ctx.MUDOU_CAPTACAO)
                                      and tem_verba_parada and tem_faixa),
        "problema_aberto": bool(ctx.problema(avaliacao.contexto))
                           and avaliacao.tem(ctx.PROBLEMA_ABERTO),
        # Sem faixa de resultados esperados o fragmento longo não fecha a
        # frase: o valor parado é pequeno demais para cobrar um número.
        rules.VERBA_SEM_RETORNO: tem_verba_parada and tem_faixa,
        "verba_sem_retorno_curta": tem_verba_parada and not tem_faixa,
        "nada_mudou_com_custo_alto": (avaliacao.tem(ctx.NADA_MUDOU)
                                      and avaliacao.tem(rules.CPA_ATENCAO)),
    }
    for chave in _ATENCAO_POR_PRECEDENCIA:
        if compostas.get(chave, avaliacao.tem(chave)):
            return chave
    return ""


def _sinal_de_apoio(avaliacao, exceto=""):
    familia = exceto.split("_")[0] if exceto else ""
    for chave in _APOIO_POR_PRECEDENCIA:
        achado = (_sinal(avaliacao, chave) if chave.endswith("_")
                  else (chave if avaliacao.tem(chave) else ""))
        if not achado or achado == exceto or achado.startswith(familia + "_"):
            continue
        if achado in _ATENCAO_POR_PRECEDENCIA and exceto:
            # Um segundo sinal negativo não vira "leitura atual": o ponto de
            # atenção já é o lugar dele, e só cabe um por texto.
            continue
        return achado
    return ""


# ----------------------------------------------------------------------
# Escolha dos fragmentos
# ----------------------------------------------------------------------
def _abertura(avaliacao):
    return (_ABERTURA_POR_MOTIVO.get(avaliacao.motivo_principal)
            or _ABERTURA[avaliacao.classificacao])


def _motivo(avaliacao, incluir_numeros, numeros):
    """O catálogo sai da referência usada; o `_MOTIVO` (faixa do perfil) é o
    fallback, e cobre os motivos que nenhum outro catálogo precisa reescrever
    — sem resultado e sem investimento não mudam com a referência."""
    catalogo = _MOTIVO_POR_REFERENCIA.get(avaliacao.referencia, _MOTIVO)
    par = catalogo.get(avaliacao.motivo_principal) or _MOTIVO[avaliacao.motivo_principal]
    return par[1].format(**numeros) if incluir_numeros else par[0]


def _objetivo(avaliacao):
    escada = (_ESCADA_POR_MOTIVO.get(avaliacao.motivo_principal)
              or _ESCADA[avaliacao.classificacao])
    return _PREFIXO_OBJETIVO[avaliacao.proximo_passo] + escada


def _sinal(avaliacao, prefixo):
    return next((s for s in avaliacao.sinais if s.startswith(prefixo)), "")


# ----------------------------------------------------------------------
# Números e formatação
# ----------------------------------------------------------------------
def _numeros(metricas, avaliacao=None):
    """Tudo que os fragmentos podem interpolar, já formatado em pt-BR.

    Os derivados entram aqui junto dos números do período porque, do ponto de
    vista do texto, não há diferença — a diferença está em quem pode citá-los
    sem número: só os derivados, que nenhuma tabela mostra.
    """
    cpa = metricas.get("cpa")
    if cpa is None:
        cpa = metricas.get("custo_resultado")
    derivados = getattr(avaliacao, "derivados", None) or {}
    esperado = derivados.get("resultados_esperados") or [0, 0]
    problema = ctx.problema(getattr(avaliacao, "contexto", None))
    return {
        "problema": _PROBLEMA_SUJEITO.get(problema, ""),
        "cpa": _moeda(cpa),
        "cpm": _moeda(metricas.get("cpm")),
        "ctr": _percentual(metricas.get("ctr")),
        "investimento": _moeda(metricas.get("investimento")),
        "resultados": _inteiro(metricas.get("resultados")),
        "frequencia": _decimal(metricas.get("frequencia")),
        "verba_sem_retorno": _moeda(derivados.get("verba_sem_retorno")),
        "verba_em_aprendizado": _moeda(derivados.get("verba_em_aprendizado")),
        "esperado_min": esperado[0],
        "esperado_max": esperado[1],
    }


def _formatar(texto, destino):
    """PDF aceita <b> e <i> (o template do WeasyPrint os renderiza); o
    WhatsApp não entende HTML e usa asterisco simples."""
    if destino == WHATSAPP:
        for tag, marca in (("<b>", "*"), ("</b>", "*"), ("<i>", "_"), ("</i>", "_")):
            texto = texto.replace(tag, marca)
    return texto
