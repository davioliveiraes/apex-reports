# -*- coding: utf-8 -*-
"""
Leitura Rápida — a resposta a "o que eu mando no grupo agora?".

NÃO é uma segunda Análise de Desempenho, e não tem parser nenhum: ela consome
o **mesmo modelo normalizado** que a frente de desempenho produz
(`analise_desempenho.consolidar`), a partir do mesmo export do preset
`DESEMPENHO`. O que muda daqui para lá é só o recorte e o tamanho:

    XLSX DESEMPENHO
          ↓
    parser_desempenho  →  analise_desempenho.consolidar
                                    ↓
                    ┌───────────────┴───────────────┐
            Análise de Desempenho              Leitura Rápida
          (diagnóstico, comparação            (3 parágrafos e
           entre conjuntos, atenção)           uma pergunta)

Dois módulos, pela mesma razão de `rastreamento/`: `resumo.py` decide o que
entra, `mensagem.py` escreve. A saída estruturada existe para que nenhuma
regra viva no template — a tela recebe números já escolhidos e um texto
pronto.

O que esta frente nunca faz
---------------------------
- **Não cita investimento.** O preset não traz `Valor gasto`. O consolidado
  reconstrói um gasto para ponderar as taxas corretamente, mas ele é peso de
  cálculo e não pode aparecer numa frase (ver o cabeçalho de
  `analise_desempenho`).
- **Não afirma venda.** O Meta mostra o contato, não o fechamento. Por isso a
  mensagem termina perguntando, e é essa pergunta que cruza tráfego →
  atendimento → venda.
- **Não classifica o período.** Ver `resumo.classificar`.
"""
