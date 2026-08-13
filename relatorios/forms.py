# -*- coding: utf-8 -*-
from django import forms

from . import metricas
from .parser_xlsx import VEICULACAO_TODAS, VEICULACOES


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
    TITULO_LISTAGEM_PADRAO = "Relatório de Listagem"

    # required=False: sem seleção explícita (fluxo antigo), o modo é inferido
    # pelo nº de anexos em clean() — preserva os modos 1 e 2 como eram.
    modo = forms.ChoiceField(
        label="Modo do relatório", choices=MODOS, required=False,
        initial=MODO_UNICO, widget=forms.RadioSelect,
    )
    cliente = forms.CharField(
        label="Cliente / Grupo", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: TIM Brasil"}),
    )
    titulo = forms.CharField(
        label="Título do relatório", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": TITULO_LISTAGEM_PADRAO}),
        help_text="Opcional — aparece no topo do PDF de listagem.",
    )
    # Choices vêm do registro central de métricas (callable: reavaliado a cada
    # instância) — acrescentar uma métrica lá aparece aqui sem tocar no form.
    metrica = forms.ChoiceField(
        label="Métrica", choices=metricas.opcoes_agrupadas, required=False,
        help_text="A métrica comparada entre as contas no PDF.",
    )
    # Filtra as linhas pela coluna "Veiculação da campanha" do export
    # (valores "active"/"inactive", mesmo com o cabeçalho em português).
    veiculacao = forms.ChoiceField(
        label="Campanhas", choices=VEICULACOES, required=False,
        initial=VEICULACAO_TODAS,
        help_text="Quais campanhas entram na comparação, pelo status de "
                  "veiculação no export.",
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
            cd["veiculacao"] = cd.get("veiculacao") or VEICULACAO_TODAS

        if modo == self.MODO_LISTAGEM:
            cd["titulo"] = (cd.get("titulo") or "").strip() or self.TITULO_LISTAGEM_PADRAO
        elif not (cd.get("cliente") or "").strip():
            self.add_error("cliente", "Informe o cliente/grupo do relatório.")
        return cd


class RevisaoForm(forms.Form):
    """Etapa 2 — revisar/editar os textos antes de gerar o PDF."""
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


class RevisaoGrupoForm(_ComUnidades):
    """Etapa 2 no modo consolidado (2+ anexos): nomes das unidades + análise geral."""

    cliente = forms.CharField(label="Nome do grupo / cliente", max_length=120)
    periodo = forms.CharField(label="Período", max_length=80, required=False)
    analise = forms.CharField(
        label="Análise do Período — Geral", required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Texto curto, em linguagem de cliente (3–5 frases). "
                  "Um parágrafo por bloco (separe com linha em branco). Aceita <b> e <i>.",
    )


class RevisaoListagemForm(_ComUnidades):
    """Etapa 2 do modo Listagem: título do PDF, período e nomes das contas."""
    titulo = forms.CharField(
        label="Título do relatório", max_length=120, required=False,
        widget=forms.TextInput(
            attrs={"placeholder": UploadForm.TITULO_LISTAGEM_PADRAO}),
        help_text="Em branco, usa "
                  f'"{UploadForm.TITULO_LISTAGEM_PADRAO}".',
    )
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

    def clean_titulo(self):
        return (self.cleaned_data["titulo"] or "").strip() \
            or UploadForm.TITULO_LISTAGEM_PADRAO

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


class RevisaoIndicadorForm(_ComUnidades):
    """Etapa 2 do modo Indicador Único: cliente, métrica e nomes das contas.

    A métrica é reeditável aqui — trocar de indicador na revisão não exige
    reenviar os anexos, já que o parser rodou inteiro em cada um."""
    cliente = forms.CharField(label="Cliente / grupo", max_length=120)
    metrica = forms.ChoiceField(
        label="Métrica comparada", choices=metricas.opcoes_agrupadas,
        help_text="Trocar a métrica aqui regera o PDF sem reenviar os anexos.",
    )
    veiculacao = forms.ChoiceField(
        label="Campanhas", choices=VEICULACOES, required=False,
        initial=VEICULACAO_TODAS,
        help_text="Filtro pelo status de veiculação no export — também "
                  "reeditável sem reenviar os anexos.",
    )

    def clean_veiculacao(self):
        return self.cleaned_data["veiculacao"] or VEICULACAO_TODAS
