# -*- coding: utf-8 -*-
"""
Redação do texto a partir da `Avaliacao` — sem aleatoriedade.

Mesma entrada, mesma saída: nada de sortear variação de frase. O texto sai em
quatro blocos rotulados, separados por linha em branco:

    Leitura do período.        veredito + o que o sustenta
    Ponto de atenção.          sinal secundário, quando ele cobra algo
      ou
    O que sustentou o resultado.
    O que vamos fazer.         ação concreta do próximo ciclo
    Objetivo do próximo ciclo. o degrau seguinte da escada

Cada fragmento existe em duas formas, com e sem número:

    False (PDF)      "O mesmo público já viu os anúncios muitas vezes —
                      sinal de que o alcance atual se esgotou."
    True (WhatsApp)  "Com a frequência em 3,56, o mesmo público já viu os
                      anúncios muitas vezes — o alcance atual se esgotou."

No PDF os números já estão nas tabelas logo acima da análise; repeti-los só
faz o cliente reler o que acabou de ver. Na mensagem avulsa não há tabela
nenhuma, e aí o número entra — como justificativa da leitura, nunca como
relistagem.

O leitor é o dono da loja, não um gestor de tráfego: cada métrica vira
consequência de negócio. Sinal negativo vem sempre com o que ele abre como
oportunidade, sem maquiar o problema — saturação não é só desgaste, é
indicação de que há público novo a alcançar.

Restrições de linguagem, todas verificadas em teste:
- status de campanha (pausa, duplicação, ativação) nunca aparece: é operação
  interna da agência;
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

from . import rules
from .benchmarks import ATENCAO, BOM, OTIMO, REF_GRUPO, REF_META

PDF, WHATSAPP = "pdf", "whatsapp"

ROTULO_LEITURA = "Leitura do período."
ROTULO_ATENCAO = "Ponto de atenção."
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

# Sinais que cobram algo do próximo ciclo. Definem o rótulo do bloco 2.
_SINAIS_DE_ATENCAO = frozenset((
    "frequencia_saturada", "frequencia_elevada", "cpm_elevado", "ctr_baixo",
    "_sem_sinal_atencao",
))

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
                                    _motivo_grupo(ag, incluir_numeros, numeros))),
        (rotulo, dispersao),
        (ROTULO_ACAO, _PASSO_GRUPO[ag.proximo_passo]),
        (ROTULO_OBJETIVO, _PREFIXO_OBJETIVO_GRUPO[ag.proximo_passo]
         + _ESCADA_GRUPO[ag.grupo.classificacao]),
    )
    texto = "\n\n".join("<b>%s</b> %s" % bloco for bloco in blocos)
    return _formatar(texto, destino)


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
    """Texto final da Análise do Período, em quatro blocos rotulados."""
    numeros = _numeros(metricas)
    rotulo_secundario, secundario = _secundario(avaliacao, incluir_numeros,
                                                numeros)
    blocos = (
        (ROTULO_LEITURA, "%s %s" % (_abertura(avaliacao),
                                    _motivo(avaliacao, incluir_numeros, numeros))),
        (rotulo_secundario, secundario),
        (ROTULO_ACAO, _PASSO[avaliacao.proximo_passo]),
        (ROTULO_OBJETIVO, _objetivo(avaliacao)),
    )
    texto = "\n\n".join("<b>%s</b> %s" % bloco for bloco in blocos)
    return _formatar(texto, destino)


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


def _secundario(avaliacao, incluir_numeros, numeros):
    """Frequência manda; o custo de exibição entra quando a frequência está
    saudável ou ausente. Depois vêm atenção e estrutura, e por fim um
    fragmento neutro — o bloco nunca some, porque a saída tem sempre quatro."""
    escolhido = _sinal_secundario(avaliacao)
    par = _SECUNDARIO[escolhido]
    rotulo = ROTULO_ATENCAO if escolhido in _SINAIS_DE_ATENCAO else ROTULO_SUSTENTOU
    texto = par[1].format(**numeros) if incluir_numeros else par[0]
    return rotulo, texto


def _sinal_secundario(avaliacao):
    frequencia = _sinal(avaliacao, "frequencia_")
    if frequencia and frequencia != "frequencia_saudavel":
        return frequencia
    for candidato in (_sinal(avaliacao, "cpm_"), frequencia,
                      _sinal(avaliacao, "ctr_")):
        if candidato:
            return candidato
    for estrutura in (rules.RESULTADOS_CONCENTRADOS, rules.CAMPANHA_UNICA,
                      rules.MULTIPLAS_CAMPANHAS):
        if avaliacao.tem(estrutura):
            return estrutura
    return ("_sem_sinal_atencao" if avaliacao.classificacao == ATENCAO
            else "_sem_sinal_favoravel")


def _objetivo(avaliacao):
    escada = (_ESCADA_POR_MOTIVO.get(avaliacao.motivo_principal)
              or _ESCADA[avaliacao.classificacao])
    return _PREFIXO_OBJETIVO[avaliacao.proximo_passo] + escada


def _sinal(avaliacao, prefixo):
    return next((s for s in avaliacao.sinais if s.startswith(prefixo)), "")


# ----------------------------------------------------------------------
# Números e formatação
# ----------------------------------------------------------------------
def _numeros(metricas):
    cpa = metricas.get("cpa")
    if cpa is None:
        cpa = metricas.get("custo_resultado")
    return {
        "cpa": _moeda(cpa),
        "cpm": _moeda(metricas.get("cpm")),
        "ctr": _percentual(metricas.get("ctr")),
        "investimento": _moeda(metricas.get("investimento")),
        "resultados": _inteiro(metricas.get("resultados")),
        "frequencia": _decimal(metricas.get("frequencia")),
    }


def _formatar(texto, destino):
    """PDF aceita <b> e <i> (o template do WeasyPrint os renderiza); o
    WhatsApp não entende HTML e usa asterisco simples."""
    if destino == WHATSAPP:
        for tag, marca in (("<b>", "*"), ("</b>", "*"), ("<i>", "_"), ("</i>", "_")):
            texto = texto.replace(tag, marca)
    return texto


def _pt_br(texto):
    """1,234.56 -> 1.234,56"""
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _moeda(valor):
    return "R$ " + _pt_br(f"{float(valor or 0):,.2f}")


def _decimal(valor):
    return f"{float(valor or 0):.2f}".replace(".", ",")


def _percentual(valor):
    return f"{float(valor or 0):.2f}".replace(".", ",") + "%"


def _inteiro(valor):
    return _pt_br(f"{int(float(valor or 0)):,d}")
