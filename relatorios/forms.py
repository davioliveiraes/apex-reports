# -*- coding: utf-8 -*-
from datetime import date

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
    """Os três campos que nenhuma planilha traz.

    O Gerenciador sabe o que foi configurado e o que foi gasto; ele não sabe o
    que foi **contratado** — isso é combinado fora dele. Sem esses campos o
    fechamento não tem contra o que comparar, e é por isso que eles são
    digitados a cada envio em vez de lidos.
    """

    MENSAL = "mensal"
    DIARIO = "diario"
    PERIODICIDADES = [(MENSAL, "por mês"), (DIARIO, "por dia")]

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
        help_text="R$ 990/mês e R$ 33/dia são o mesmo contrato — o app converte.",
    )
    # `format` explícito pelo mesmo motivo da listagem: o input nativo de data
    # só entende ISO, e a locale pt-BR renderizaria o inicial como dd/mm/aaaa.
    referencia = forms.DateField(
        label="Data de hoje", initial=date.today,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Define o mês analisado e quantos dias já encerraram.",
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
        """`(mensal, diário)` — só um dos dois vem preenchido; o outro é
        derivado em `fechamento_verba.calcular`, que sabe os dias do mês."""
        valor = self.cleaned_data["orcamento"]
        if self.cleaned_data["periodicidade"] == self.MENSAL:
            return valor, None
        return None, valor


class VerbaUploadForm(_BaseInterna):
    """Tela 01 da verba: a base interna + os exports do preset VERBA."""

    MAX_ARQUIVOS = 2

    arquivos = MultipleFileField(
        label="Exports do preset VERBA (.xlsx)",
        widget=MultipleFileInput(attrs={"accept": ".xlsx", "multiple": True}),
        help_text="Um por nível: campanha e conjunto de anúncios. Conta 100% "
                  "CBO fecha só com o de campanha.",
    )

    def clean_arquivos(self):
        arquivos = self.cleaned_data["arquivos"]
        if len(arquivos) > self.MAX_ARQUIVOS:
            raise forms.ValidationError(
                "O fechamento de verba usa no máximo 2 arquivos — um de "
                f"campanha e um de conjunto de anúncios (você enviou "
                f"{len(arquivos)})."
            )
        for f in arquivos:
            if not f.name.lower().endswith(".xlsx"):
                raise forms.ValidationError(
                    f'"{f.name}" não é um .xlsx — envie apenas arquivos '
                    "exportados do Gerenciador de Anúncios."
                )
            if f.size > 10 * 1024 * 1024:
                raise forms.ValidationError(f'"{f.name}" está acima de 10 MB.')
        return arquivos


class VerbaBaseForm(_BaseInterna):
    """Tela 02 da verba: a mesma base interna, sem os anexos.

    Corrigir o contratado ou a data de referência refaz todos os números sem
    reenviar planilha — as linhas dos dois exports ficam na sessão, no mesmo
    espírito do *Aplicar seleção* dos relatórios de desempenho.
    """
