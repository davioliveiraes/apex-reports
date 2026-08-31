# -*- coding: utf-8 -*-
from django import forms

from . import metricas
from .parser_xlsx import _to_float


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """FileField que aceita vários arquivos num único input."""

    def clean(self, data, initial=None):
        limpar = super().clean
        if isinstance(data, (list, tuple)):
            return [limpar(d, initial) for d in data]
        return [limpar(data, initial)]


class UploadForm(forms.Form):
    MAX_ARQUIVOS = 20

    MODO_UNICO = "unico"
    MODO_CONSOLIDADO = "consolidado"
    MODO_LISTAGEM = "listagem"
    MODO_INDICADOR = "indicador"
    MODOS = [
        (MODO_UNICO, "Anexo único"),
        (MODO_CONSOLIDADO, "Consolidado"),
        (MODO_LISTAGEM, "Listagem"),
        (MODO_INDICADOR, "Indicador Único"),
    ]
    # required=False: sem seleção explícita (fluxo antigo), o modo é inferido
    # pelo nº de anexos em clean() — preserva os modos 1 e 2 como eram.
    modo = forms.ChoiceField(
        label="Modo do relatório", choices=MODOS, required=False,
        initial=MODO_UNICO, widget=forms.RadioSelect,
    )
    # Um nome só para os quatro modos: vai ao cabeçalho do PDF e batiza o
    # arquivo. Até 24/08/2026 a listagem tinha um "título do relatório" à
    # parte, e era o único modo que não mostrava cliente nenhum.
    cliente = forms.CharField(
        label="Cliente / Grupo", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: TIM Brasil"}),
    )
    # Choices vêm do registro central de métricas (callable: reavaliado a cada
    # instância) — acrescentar uma métrica lá aparece aqui sem tocar no form.
    metrica = forms.ChoiceField(
        label="Métrica", choices=metricas.opcoes_agrupadas, required=False,
        help_text="A métrica comparada entre as contas no PDF.",
    )
    arquivos = MultipleFileField(
        label="Exports do Meta Ads Manager (.xlsx)",
        widget=MultipleFileInput(attrs={"accept": ".xlsx", "multiple": True}),
        help_text="De 1 a 20 arquivos — cada anexo representa uma conta/unidade.",
    )

    def clean_arquivos(self):
        arquivos = self.cleaned_data["arquivos"]
        if len(arquivos) > self.MAX_ARQUIVOS:
            raise forms.ValidationError(
                f"Máximo de {self.MAX_ARQUIVOS} arquivos por relatório "
                f"(você enviou {len(arquivos)})."
            )
        for f in arquivos:
            if not f.name.lower().endswith(".xlsx"):
                raise forms.ValidationError(
                    f'"{f.name}" não é um .xlsx — envie apenas arquivos exportados '
                    "do Gerenciador de Anúncios."
                )
            if f.size > 10 * 1024 * 1024:
                raise forms.ValidationError(f'"{f.name}" está acima de 10 MB.')
        return arquivos

    def clean(self):
        cd = super().clean()
        arquivos = cd.get("arquivos") or []

        modo = cd.get("modo")
        if not modo and arquivos:
            modo = self.MODO_UNICO if len(arquivos) == 1 else self.MODO_CONSOLIDADO
            cd["modo"] = modo

        if modo == self.MODO_UNICO and len(arquivos) != 1:
            self.add_error("arquivos",
                           "O modo Anexo único exige exatamente 1 arquivo "
                           f"(você enviou {len(arquivos)}).")
        if modo == self.MODO_CONSOLIDADO and len(arquivos) < 2:
            self.add_error("arquivos",
                           "O consolidado precisa de pelo menos 2 arquivos — "
                           "para 1 conta, use o modo Anexo único.")
        if modo == self.MODO_INDICADOR:
            if len(arquivos) < 2:
                self.add_error("arquivos",
                               "O Indicador Único compara contas — envie pelo "
                               "menos 2 arquivos.")
            if not cd.get("metrica"):
                self.add_error("metrica", "Escolha a métrica a comparar.")

        if not (cd.get("cliente") or "").strip():
            self.add_error("cliente", "Informe o cliente/grupo do relatório.")
        return cd


class _ComCampanhas(forms.Form):
    """Seleção dos grupos de campanha que entram no relatório.

    O campo só nasce quando há mais de um grupo nos anexos: com um só não há
    escolha a fazer, e uma caixa marcada sozinha seria ruído na tela.

    `required=False` de propósito. Quem consome a seleção é o botão *Aplicar
    seleção*; o *Gerar PDF* trabalha sobre o que já está na sessão, e travá-lo
    por causa das caixas prenderia o relatório numa escolha que ele nem lê. A
    recusa de uma seleção vazia é da view, junto do clique que a usa.
    """

    def __init__(self, *args, grupos_campanha=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.grupos_campanha = list(grupos_campanha)
        if len(self.grupos_campanha) > 1:
            self.fields["campanhas"] = forms.MultipleChoiceField(
                label="Campanhas incluídas", required=False,
                choices=[(g, g) for g in self.grupos_campanha],
                widget=forms.CheckboxSelectMultiple,
            )


class RevisaoForm(_ComCampanhas):
    """Etapa 2 — revisar/editar os textos antes de gerar o PDF.

    Herda a seleção de campanhas pelo mesmo motivo do consolidado e da
    listagem: um anexo só também costuma trazer produtos diferentes na mesma
    planilha, e o relatório de um deles é o que o cliente pediu.
    """
    cliente = forms.CharField(label="Cliente", max_length=120)
    periodo = forms.CharField(label="Período", max_length=80, required=False)
    analise = forms.CharField(
        label="Análise do Período", required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Texto curto, em linguagem de cliente (3–5 frases). "
                  "Um parágrafo por bloco (separe com linha em branco). Aceita <b> e <i>.",
    )


class _ComUnidades(forms.Form):
    """Base dos modos multi-conta: um campo de nome por unidade, na ordem de
    envio dos anexos. O nome digitado no painel chega como `initial`."""

    def __init__(self, *args, nomes_unidades=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.n_unidades = len(nomes_unidades)
        for i, nome in enumerate(nomes_unidades):
            # required=False: campo em branco preserva o nome que já vinha
            # (do painel ou do arquivo) — ver nomes_finais().
            self.fields[f"unidade_{i}"] = forms.CharField(
                label=f"Nome da unidade {i + 1}", max_length=120, initial=nome,
                required=False,
            )

    def campos_unidades(self):
        return [self[f"unidade_{i}"] for i in range(self.n_unidades)]

    def nomes_finais(self, atuais):
        """Nomes revisados; campo em branco preserva o nome que já vinha."""
        return [(self.cleaned_data.get(f"unidade_{i}") or "").strip() or atual
                for i, atual in enumerate(atuais)]


class RevisaoGrupoForm(_ComCampanhas, _ComUnidades):
    """Etapa 2 no modo consolidado (2+ anexos): nomes das unidades + análise geral."""

    cliente = forms.CharField(label="Nome do grupo / cliente", max_length=120)
    periodo = forms.CharField(label="Período", max_length=80, required=False)
    analise = forms.CharField(
        label="Análise do Período — Geral", required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Texto curto, em linguagem de cliente (3–5 frases). "
                  "Um parágrafo por bloco (separe com linha em branco). Aceita <b> e <i>.",
    )


class RevisaoListagemForm(_ComCampanhas, _ComUnidades):
    """Etapa 2 do modo Listagem: cliente, período e nomes das contas."""
    cliente = forms.CharField(label="Cliente / grupo", max_length=120)
    # `format` explícito: o input nativo de data só entende ISO, e a locale
    # pt-BR faria o widget renderizar o valor inicial como dd/mm/aaaa —
    # o campo apareceria vazio. Na entrada, o pt-BR aceita as duas formas.
    inicio = forms.DateField(
        label="Início do período", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    fim = forms.DateField(
        label="Fim do período", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def clean(self):
        cd = super().clean()
        inicio, fim = cd.get("inicio"), cd.get("fim")
        # Meia data no cabeçalho ("01/07/2026 — ") é pior que nenhuma.
        if bool(inicio) != bool(fim):
            self.add_error("fim" if inicio else "inicio",
                           "Informe as duas datas do período, ou nenhuma.")
        elif inicio and fim < inicio:
            self.add_error("fim", "O fim do período é anterior ao início.")
        return cd

    def periodo(self):
        """Rótulo do cabeçalho do PDF; vazio quando as datas não foram dadas."""
        inicio, fim = self.cleaned_data.get("inicio"), self.cleaned_data.get("fim")
        return f"{inicio:%d/%m/%Y} — {fim:%d/%m/%Y}" if inicio and fim else ""


class RevisaoIndicadorForm(_ComCampanhas, _ComUnidades):
    """Etapa 2 do modo Indicador Único: cliente, métrica e nomes das contas.

    A métrica é reeditável aqui — trocar de indicador na revisão não exige
    reenviar os anexos, já que o parser rodou inteiro em cada um. E, como nos
    demais modos, a seleção de grupos de campanha recorta o que entra na
    comparação."""
    cliente = forms.CharField(label="Cliente / grupo", max_length=120)
    metrica = forms.ChoiceField(
        label="Métrica comparada", choices=metricas.opcoes_agrupadas,
        help_text="Trocar a métrica aqui regera o PDF sem reenviar os anexos.",
    )


# ----------------------------------------------------------------------
# Análise de Verba
# ----------------------------------------------------------------------
class _BaseInterna(forms.Form):
    """Os dois campos que nenhuma planilha traz.

    O Gerenciador sabe o que foi configurado e o que foi gasto; ele não sabe o
    que foi **contratado** — isso é combinado fora dele. Sem isso o fechamento
    não tem contra o que comparar, e é por isso que é digitado a cada envio em
    vez de lido.

    Eram três. A "data de hoje" saiu em 29/08/2026: o export declara o próprio
    recorte (`Início dos relatórios` / `Encerramento dos relatórios`), e ler a
    data do arquivo é mais confiável do que pedi-la a quem talvez tenha
    exportado ontem. Campo que o arquivo responde é campo que o operador pode
    errar.
    """

    # Os dois ciclos de fechamento, e nada mais. "Por dia" existiu até
    # 29/08/2026 e saiu: o diário nunca foi um contrato, é uma DIVISÃO —
    # R$ 300/semana são R$ 43/dia porque a semana tem 7 dias. Quem sabe esse
    # número é o motor, que conhece o tamanho do ciclo; pedi-lo ao operador
    # criava dois campos que podiam discordar um do outro.
    MENSAL = "mensal"
    QUINZENAL = "quinzenal"
    SEMANAL = "semanal"
    # Do ciclo mais longo ao mais curto. "Por dia" fecha a lista porque é o
    # único que não é uma janela: é a unidade em que o valor foi cotado, e o
    # fechamento continua sendo medido no ciclo (ver `fechamento_verba
    # .CICLO_DIARIO`).
    DIARIO = "diario"
    PERIODICIDADES = [(MENSAL, "por mês"), (QUINZENAL, "por quinzena"),
                      (SEMANAL, "por semana"), (DIARIO, "por dia")]

    # Onde o orçamento da conta está montado. Não é preferência: decide qual
    # aba do Gerenciador exportar, porque é no nível do orçamento que estão as
    # estruturas que o fechamento lista.
    CBO = "cbo"
    ABO = "abo"
    ESTRUTURAS = [(CBO, "CBO — orçamento na campanha"),
                  (ABO, "ABO — orçamento no conjunto")]

    estrutura = forms.ChoiceField(
        label="Estrutura da conta", choices=ESTRUTURAS, initial=CBO,
        widget=forms.RadioSelect,
        help_text="CBO envia o export da aba Campanhas; ABO, o da aba "
                  "Conjuntos de anúncios.",
    )

    def nivel(self):
        """O nível do export que este envio traz."""
        from .parser_verba import NIVEL_CAMPANHA, NIVEL_CONJUNTO
        return (NIVEL_CONJUNTO if self.cleaned_data["estrutura"] == self.ABO
                else NIVEL_CAMPANHA)

    cliente = forms.CharField(
        label="Cliente / unidade", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Rei do Celular"}),
    )
    # CharField, e não DecimalField, porque o valor é digitado à mão em pt-BR:
    # o DecimalField recusa "1.000,00" (só entende o ponto como decimal) e
    # engasga num "R$" colado. `_to_float` é o mesmo conversor que lê dinheiro
    # das planilhas — uma implementação só para os dois caminhos.
    orcamento = forms.CharField(
        label="Orçamento contratado", max_length=20,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: 990,00",
                                      "inputmode": "decimal"}),
        help_text="O valor combinado com o cliente, não o configurado no Meta.",
    )
    periodicidade = forms.ChoiceField(
        label="Esse valor é", choices=PERIODICIDADES, initial=MENSAL,
        widget=forms.RadioSelect,
        help_text="Um número só, e o outro sai daqui sozinho: R$ 300/semana "
                  "são R$ 43/dia; R$ 1.800/mês, R$ 58/dia num mês de 31. Em "
                  "por dia é o contrário — R$ 150/dia fecham R$ 4.650 num "
                  "ciclo de 31, e é esse ciclo que a mensagem compara.",
    )

    def clean_orcamento(self):
        valor = _to_float(self.cleaned_data["orcamento"])
        if valor is None:
            raise forms.ValidationError(
                "Informe o valor em reais — ex.: 990,00 ou 1.000,00.")
        if valor <= 0:
            raise forms.ValidationError("O orçamento contratado precisa ser "
                                        "maior que zero.")
        return valor

    def contratado(self):
        """`(valor do ciclo, ciclo)`.

        O equivalente diário é derivado em `fechamento_verba.calcular`, que é
        quem sabe quantos dias o ciclo tem — 28 a 31 no mês, 7 na semana.
        """
        return self.cleaned_data["orcamento"], self.cleaned_data["periodicidade"]


class VerbaUploadForm(_BaseInterna):
    """Tela 01 da verba: a base interna + UM export do preset VERBA.

    Eram dois arquivos até 29/08/2026, e a razão era o orçamento: `[CBO]`
    guarda o valor na campanha, `[ABO]` no conjunto, e o app não sabia de
    antemão qual era o caso. Duas coisas mudaram isso — o diário passou a vir
    do contrato (o orçamento da planilha não decide mais número nenhum), e a
    estrutura passou a ser declarada em vez de deduzida. Sobrou um arquivo: o
    do nível em que a conta está montada.
    """

    MAX_BYTES = 10 * 1024 * 1024

    arquivo = forms.FileField(
        label="Export do preset VERBA (.xlsx)",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
        help_text="Da aba Campanhas se a conta é CBO; da aba Conjuntos de "
                  "anúncios se é ABO.",
    )

    def clean_arquivo(self):
        f = self.cleaned_data["arquivo"]
        if not f.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(
                f'"{f.name}" não é um .xlsx — envie o arquivo exportado do '
                "Gerenciador de Anúncios.")
        if f.size > self.MAX_BYTES:
            raise forms.ValidationError(f'"{f.name}" está acima de 10 MB.')
        return f


# ----------------------------------------------------------------------
# Leitura Rápida
# ----------------------------------------------------------------------
class LeituraUploadForm(forms.Form):
    """A tela inteira da Leitura Rápida: um nome e um arquivo.

    Deliberadamente menor que o painel de desempenho, que lê o mesmo export.
    Lá os campos existem porque há quatro modos, até vinte anexos e um PDF a
    batizar; aqui a saída é uma mensagem para colar num grupo, e cada campo a
    mais é um segundo a mais entre "abri a planilha" e "mandei a leitura".

    Nem perfil de negócio nem meta de CPA aparecem, e desde 30/08/2026 isso
    deixou de ser uma economia para virar uma consequência: a frente não
    classifica mais o período (ver `leitura.resumo.classificar`), então não há
    o que esses campos alimentassem.
    """

    MAX_BYTES = 10 * 1024 * 1024

    cliente = forms.CharField(
        label="Cliente / unidade", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Rei do Celular"}),
        help_text="Identifica a leitura na tela; não entra na mensagem.",
    )
    # Um campo para as duas portas. Separá-los em "planilha" e "print" faria a
    # tela perguntar algo que o próprio arquivo responde — e é a extensão que
    # decide, não o operador.
    arquivos = MultipleFileField(
        label="Planilha ou print (.xlsx, .png, .jpg)",
        widget=MultipleFileInput(attrs={"accept": ".xlsx,.png,.jpg,.jpeg,.webp",
                                        "multiple": True}),
        help_text="O .xlsx do preset DESEMPENHO, ou capturas de tela do "
                  "Gerenciador de Anúncios.",
    )

    def clean_arquivos(self):
        """Ou UMA planilha, ou até quatro prints — nunca os dois juntos.

        Misturar as duas fontes obrigaria a decidir qual vence quando elas
        discordarem, e não há resposta certa para isso: a planilha é exata, o
        print é transcrito. Uma origem por leitura mantém a resposta óbvia.
        """
        from .leitura.imagem import EXTENSOES, MAX_BYTES_IMAGEM, MAX_IMAGENS

        arquivos = self.cleaned_data["arquivos"]
        # `MultipleFileInput` devolve `files.getlist(nome)`, que é uma LISTA
        # VAZIA quando não veio arquivo nenhum — e lista vazia não dispara o
        # `required` do campo. Sem esta guarda o formulário passa válido sem
        # anexo e a view estoura ao tentar ler `None`.
        if not arquivos:
            raise forms.ValidationError(
                "Envie o .xlsx do preset DESEMPENHO ou pelo menos um print da "
                "tela do Gerenciador.")
        planilhas = [f for f in arquivos if f.name.lower().endswith(".xlsx")]
        imagens = [f for f in arquivos
                   if f.name.lower().rsplit(".", 1)[-1] in EXTENSOES]

        estranhos = [f.name for f in arquivos
                     if f not in planilhas and f not in imagens]
        if estranhos:
            raise forms.ValidationError(
                f'"{estranhos[0]}" não é .xlsx nem imagem — envie o export do '
                "Gerenciador de Anúncios ou um print da tela dele.")
        if planilhas and imagens:
            raise forms.ValidationError(
                "Envie a planilha OU os prints, não os dois: são duas leituras "
                "do mesmo período, e a planilha é a exata.")
        if len(planilhas) > 1:
            raise forms.ValidationError(
                "Uma planilha por leitura — a Leitura Rápida é de uma conta e "
                "um período.")
        if len(imagens) > MAX_IMAGENS:
            raise forms.ValidationError(
                f"Máximo de {MAX_IMAGENS} prints por leitura (você enviou "
                f"{len(imagens)}).")

        for f in planilhas:
            if f.size > self.MAX_BYTES:
                raise forms.ValidationError(f'"{f.name}" está acima de 10 MB.')
        for f in imagens:
            if f.size > MAX_BYTES_IMAGEM:
                raise forms.ValidationError(f'"{f.name}" está acima de 8 MB.')
        return arquivos

    def imagens(self):
        """Os prints do envio, ou lista vazia quando veio planilha."""
        from .leitura.imagem import eh_imagem
        return [f for f in self.cleaned_data["arquivos"] if eh_imagem(f.name)]

    def planilha(self):
        """O .xlsx do envio, ou `None` quando vieram prints."""
        return next((f for f in self.cleaned_data["arquivos"]
                     if f.name.lower().endswith(".xlsx")), None)


# ----------------------------------------------------------------------
# Análise de Desempenho
# ----------------------------------------------------------------------
class DesempenhoUploadForm(forms.Form):
    """A tela inteira da Análise de Desempenho: um nome e um arquivo.

    Mesma forma da tela da verba, e pelo mesmo motivo: a saída é um texto para
    colar num grupo, e cada campo a mais é um segundo a mais entre "abri a
    planilha" e "mandei a leitura". Não há perfil de negócio nem meta de CPA
    porque não há classificação — ver `analise_desempenho.classificar`.
    """

    MAX_BYTES = 10 * 1024 * 1024

    cliente = forms.CharField(
        label="Cliente / unidade", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: TIM Brasil"}),
        help_text="Identifica a análise na tela; não entra no texto.",
    )
    arquivo = forms.FileField(
        label="Export do preset DESEMPENHO (.xlsx)",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
        help_text="Da aba Conjuntos de anúncios, com a predefinição "
                  "DESEMPENHO aplicada em Colunas → Personalizar colunas.",
    )

    def clean_arquivo(self):
        f = self.cleaned_data["arquivo"]
        if not f.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(
                f'"{f.name}" não é um .xlsx — envie o arquivo exportado do '
                "Gerenciador de Anúncios.")
        if f.size > self.MAX_BYTES:
            raise forms.ValidationError(f'"{f.name}" está acima de 10 MB.')
        return f


# ----------------------------------------------------------------------
# Análise de Rastreamento
# ----------------------------------------------------------------------
class RastreamentoUploadForm(forms.Form):
    """A tela inteira da Análise de Rastreamento: um nome e um arquivo.

    Mesma forma das outras duas frentes de texto. O nível preferencial do
    export é o de anúncios (§4) — é onde métrica de vídeo e classificação de
    relevância existem —, mas o formulário não obriga: um export de conjuntos
    é lido do mesmo jeito, com os blocos que ele sustentar.
    """

    MAX_BYTES = 10 * 1024 * 1024

    cliente = forms.CharField(
        label="Cliente / unidade", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: TIM Brasil"}),
        help_text="Identifica a análise na tela; não entra no texto.",
    )
    arquivo = forms.FileField(
        label="Export do preset RASTREAMENTO (.xlsx)",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
        help_text="De preferência da aba Anúncios, com a predefinição "
                  "RASTREAMENTO aplicada em Colunas → Personalizar colunas.",
    )

    def clean_arquivo(self):
        f = self.cleaned_data["arquivo"]
        if not f.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(
                f'"{f.name}" não é um .xlsx — envie o arquivo exportado do '
                "Gerenciador de Anúncios.")
        if f.size > self.MAX_BYTES:
            raise forms.ValidationError(f'"{f.name}" está acima de 10 MB.')
        return f
