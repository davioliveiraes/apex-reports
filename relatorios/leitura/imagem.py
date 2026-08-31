# -*- coding: utf-8 -*-
"""
Print do Gerenciador → as mesmas `linhas` que o .xlsx produz.

A imagem não é uma segunda fonte de dados: ela é uma segunda porta para a
MESMA. `parser_desempenho` devolve uma lista de dicionários; este módulo
devolve uma lista de dicionários com as mesmas chaves. Daí para a frente
(`analise_desempenho.consolidar` → `resumo.montar` → `mensagem.redigir`) nada
muda, nada sabe de onde veio, e nada precisou ser tocado.

    .xlsx  → parser_desempenho ─┐
                                ├→ linhas → consolidar → resumo → mensagem
    print  → imagem.extrair ────┘

O que este arquivo existe para impedir
--------------------------------------
Um número lido de imagem **não é um número verificado**. Toda a aplicação foi
construída sobre "o número vem da célula", e um dígito confundido pelo modelo
entraria numa mensagem que vai para o cliente com a mesma cara de um número
conferido. Três defesas, e nenhuma delas é opcional:

1. **O prompt proíbe estimar** (ver `redator_ia.PROMPT_EXTRACAO`): o que não
   está legível volta `null`, e `null` vira métrica ausente, não zero.
2. **A aritmética confere a aritmética.** Quando o print traz números
   suficientes, as mesmas relações têm de fechar por dois caminhos
   independentes — `CPM × impressões ÷ 1000` contra `custo × resultados`, e
   `impressões ÷ alcance` contra a frequência escrita. Discordância vira
   aviso, e é ela que pega o dígito trocado.
3. **A tela declara a origem.** Quem confere é o operador, e ele só confere se
   souber que precisa.
"""

import re

from ..parser_xlsx import _to_float

# Extensões que o operador realmente usa para print. A lista mora aqui e no
# formulário, e as duas leem daqui.
EXTENSOES = ("png", "jpg", "jpeg", "webp")

MAX_IMAGENS = 4
MAX_BYTES_IMAGEM = 8 * 1024 * 1024

# Campos que a transcrição pode trazer, na forma que `parser_desempenho`
# entrega. Fora desta lista nada é aceito — o modelo não inventa coluna.
NUMERICOS = ("resultados", "custo_resultado", "alcance", "impressoes",
             "frequencia", "cpm", "conversas", "custo_conversa",
             "novos_contatos")
TEXTUAIS = ("conjunto", "veiculacao", "indicador", "inicio", "termino")

# Quanto dois caminhos independentes podem divergir antes de a divergência
# deixar de ser arredondamento. O Gerenciador arredonda o que mostra (R$ 4,52
# para um custo de 4,5237), então uma folga é obrigatória; 12% é larga o
# bastante para não gritar à toa e estreita o bastante para pegar um dígito
# trocado, que erra por 10× ou por uma ordem de grandeza.
TOLERANCIA = 0.12

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VAZIOS = frozenset(("", "-", "--", "—", "n/a", "na", "nan", "none", "null",
                     "não informado", "nao informado"))


def eh_imagem(nome):
    """O anexo é um print?"""
    return str(nome or "").lower().rsplit(".", 1)[-1] in EXTENSOES


def mime(nome):
    from ..redator_ia import MIMES_DE_IMAGEM
    return MIMES_DE_IMAGEM.get(
        str(nome or "").lower().rsplit(".", 1)[-1], "image/png")


def _numero(valor):
    """Célula transcrita → float, ou `None`.

    Local, e não importado do parser de rastreamento, para a Leitura Rápida
    não passar a depender de outra frente por uma função de oito linhas. O
    trabalho pesado é do `_to_float`, que já é o conversor de dinheiro em
    pt-BR do projeto inteiro.
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return None if valor != valor else float(valor)   # NaN
    texto = str(valor).strip()
    if texto.lower() in _VAZIOS:
        return None
    return _to_float(texto.replace("%", "").strip())


def _texto(valor):
    if valor is None:
        return None
    limpo = str(valor).strip()
    return None if limpo.lower() in _VAZIOS else limpo


def extrair(arquivos):
    """`(linhas, avisos, erro)` a partir de uma ou mais capturas de tela.

    `arquivos` são os `UploadedFile` já validados pelo formulário. Levanta
    nada: a view recebe o erro em português, como no caminho da planilha.
    """
    from .. import redator_ia

    imagens = []
    for f in arquivos:
        f.seek(0)
        imagens.append((f.read(), mime(f.name)))

    try:
        bruto = redator_ia.extrair_metricas_de_imagem(imagens)
    except redator_ia.ErroDeIA as e:
        return None, [], str(e)

    linhas = [_linha(l) for l in bruto["linhas"] if isinstance(l, dict)]
    linhas = [l for l in linhas if _tem_algo(l)]
    if not linhas:
        return None, [], (
            "Não foi possível ler métricas nesta imagem. Confira se o print é "
            "de uma tela do Gerenciador de Anúncios com as colunas visíveis — "
            "ou envie o .xlsx do preset DESEMPENHO, que não depende de "
            "leitura de imagem.")
    return linhas, conferir(linhas), None


def _linha(bruta):
    """Uma linha transcrita, na forma que `parser_desempenho` entrega."""
    linha = {c: _numero(bruta.get(c)) for c in NUMERICOS}
    linha.update({c: _texto(bruta.get(c)) for c in TEXTUAIS})
    for campo in ("inicio", "termino"):
        # Data fora do ISO não vira data: o consolidado a repassa para a tela,
        # e "28 de ago" na linha de período seria pior que período nenhum.
        if linha[campo] and not _ISO.match(linha[campo]):
            linha[campo] = None
    return linha


def _tem_algo(linha):
    """Linha sem número nenhum não é linha — é uma alucinação de estrutura."""
    return any(linha[c] is not None for c in NUMERICOS)


def conferir(linhas):
    """Os avisos de incoerência aritmética do que foi transcrito.

    Cada checagem compara dois caminhos INDEPENDENTES para a mesma grandeza.
    Bater não prova que a leitura está certa; discordar prova que alguma coisa
    está errada, e é isso que se quer saber antes de mandar o texto ao cliente.
    """
    avisos = []
    for i, l in enumerate(linhas, 1):
        onde = l.get("conjunto") or f"linha {i}"

        # Gasto por dois caminhos: pelo CPM e pelo custo por resultado.
        gasto_cpm = _produto(l.get("cpm"), l.get("impressoes"), 1 / 1000)
        gasto_cpa = _produto(l.get("custo_resultado"), l.get("resultados"))
        if _discordam(gasto_cpm, gasto_cpa):
            avisos.append(
                f"Em {onde}, o CPM e o custo por resultado não fecham entre "
                "si — confira os dois números no Gerenciador antes de enviar.")

        # Frequência escrita contra impressões ÷ alcance.
        derivada = _divisao(l.get("impressoes"), l.get("alcance"))
        if _discordam(derivada, l.get("frequencia")):
            avisos.append(
                f"Em {onde}, a frequência lida não bate com impressões "
                "dividido por alcance — confira os três números.")

        # Contato novo é um subconjunto da conversa: mais novos que conversas
        # é impossível, não improvável.
        novos, conversas = l.get("novos_contatos"), l.get("conversas")
        if novos and conversas and novos > conversas:
            avisos.append(
                f"Em {onde}, os novos contatos ({novos:.0f}) passam das "
                f"conversas ({conversas:.0f}), o que não pode acontecer — "
                "algum dos dois foi lido errado.")
    return avisos


def _produto(a, b, fator=1.0):
    return a * b * fator if a and b else None


def _divisao(a, b):
    return a / b if a and b else None


def _discordam(x, y):
    """Duas medidas da mesma grandeza divergem além do arredondamento?"""
    if not x or not y:
        return False
    return abs(x - y) / max(x, y) > TOLERANCIA
