# -*- coding: utf-8 -*-
"""
Análise de Rastreamento — o caminho do anúncio até o destino.

Pacote, e não um módulo só, porque a frente tem três responsabilidades que
mudam por motivos diferentes:

- `metricas.py`   — o que os números dizem: agregação e taxas derivadas.
- `diagnostico.py`— o que isso significa: os quatro blocos e o gargalo.
- `mensagem.py`   — como se conta ao cliente: o texto de WhatsApp.

A divisão é a mesma que `analysis/` já usa entre `rules.py` (decide) e
`templates.py` (redige), e existe pelo mesmo motivo: mudar uma frase não pode
exigir mexer numa fórmula, e recalibrar uma regra não pode reescrever texto.

O parser fica FORA do pacote (`relatorios/parser_rastreamento.py`), ao lado dos
outros três — é lá que se procura quando o Meta renomeia uma coluna.

Nenhuma regra deste pacote conhece a grafia do Meta: da saída do parser em
diante só existem os nomes internos (`link_ctr`, `video_50`, `quality_ranking`).
"""
