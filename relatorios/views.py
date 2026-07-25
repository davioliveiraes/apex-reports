# -*- coding: utf-8 -*-
import io
import os
import re
import unicodedata
from datetime import datetime

from django.http import FileResponse
from django.shortcuts import redirect, render

from . import metricas
from .forms import RevisaoForm, RevisaoGrupoForm, UploadForm
from .gerador_indicador import gerar_indicador
from .gerador_listagem import gerar_listagem
from .gerador_pdf import gerar_relatorio
from .parser_xlsx import consolidar_grupo, ler_export_meta, montar_composicao

SESSION_KEY = "relatorio_apex"


def index(request):
    """Painel — escolha do modo + upload de 1 a 20 .xlsx.

    Modos: único (1 anexo → revisão), consolidado (2+ anexos somados →
    revisão), listagem (tabela 1 linha por conta → PDF direto) e indicador
    único (uma métrica comparada entre contas → PDF direto).
    """
    erro = None
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            lidos, erro = _ler_arquivos(form.cleaned_data["arquivos"])
            if not erro:
                modo = form.cleaned_data["modo"]
                if modo == UploadForm.MODO_LISTAGEM:
                    return _pdf_listagem(form.cleaned_data["titulo"], lidos)
                if modo == UploadForm.MODO_INDICADOR:
                    return _pdf_indicador(form.cleaned_data["cliente"],
                                          form.cleaned_data["metrica"], lidos)
                if modo == UploadForm.MODO_UNICO:
                    dados = lidos[0]["dados"]
                    dados.pop("_num", None)
                else:
                    dados = consolidar_grupo(lidos)
                dados["cliente"] = form.cleaned_data["cliente"]
                request.session[SESSION_KEY] = dados
                return redirect("revisao")
    else:
        form = UploadForm()
    return render(request, "relatorios/index.html", {"form": form, "erro": erro})


def _pdf_listagem(titulo, lidos):
    """Modo 3 — PDF de listagem direto (sem revisão: não há análise a editar).
    `lidos` mantém a ordem de envio dos anexos, que é a ordem das linhas."""
    buffer = io.BytesIO()
    gerar_listagem(titulo, lidos, buffer)
    buffer.seek(0)
    slug = _slug(titulo) or "Relatorio-de-Listagem"
    nome = f"{slug}-{datetime.now():%d-%m-%Y}.pdf"
    return FileResponse(buffer, as_attachment=True, filename=nome)


def _pdf_indicador(cliente, chave_metrica, lidos):
    """Modo 4 — PDF de uma métrica comparada entre contas (sem revisão: não há
    texto a editar). `lidos` mantém a ordem de envio; a ordenação das linhas
    segue a direção de `melhor` no registro de métricas."""
    buffer = io.BytesIO()
    periodo = gerar_indicador(cliente, chave_metrica, lidos, buffer)
    buffer.seek(0)
    partes = [_slug(cliente) or "cliente",
              _slug(metricas.METRICS_REGISTRY[chave_metrica]["label"]),
              _slug(periodo) or f"{datetime.now():%d-%m-%Y}"]
    return FileResponse(buffer, as_attachment=True,
                        filename="-".join(partes) + ".pdf")


def _ler_arquivos(arquivos):
    """Lê cada anexo; ao falhar, devolve erro apontando QUAL arquivo falhou."""
    lidos = []
    for f in arquivos:
        try:
            dados = ler_export_meta(f)
        except ValueError as e:
            return None, f'Arquivo "{f.name}": {e}'
        except Exception:
            return None, (
                f'Não foi possível ler "{f.name}". '
                "Confira se é um .xlsx válido do Meta Ads Manager."
            )
        lidos.append({"nome": _nome_unidade(f.name), "dados": dados})
    return lidos, None


def _nome_unidade(nome_arquivo):
    """Nome sugerido da unidade a partir do nome do arquivo (editável na revisão)."""
    base = os.path.splitext(os.path.basename(nome_arquivo))[0]
    return re.sub(r"[-_]+", " ", base).strip() or "Unidade"


def revisao(request):
    """Etapa 2 — revisar KPIs lidos e editar análise antes de gerar o PDF."""
    dados = request.session.get(SESSION_KEY)
    if not dados:
        return redirect("index")

    if dados.get("modo") == "grupo":
        return _revisao_grupo(request, dados)

    if request.method == "POST":
        form = RevisaoForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            relatorio = {
                "titulo": "Relatório de Tráfego Pago",
                "cliente": cd["cliente"],
                "periodo": cd["periodo"],
                # O funil substitui os cards de KPI no PDF (mesmos números,
                # agora com a leitura de cada métrica ao lado)
                "funil": dados.get("funil"),
                "grafico_funil": dados.get("grafico_funil"),
                "detalhes_campanha": dados.get("detalhes_campanha"),
                "grafico_campanhas": dados.get("grafico_campanhas"),
                "analise": [p.strip() for p in cd["analise"].split("\n\n") if p.strip()],
            }
            buffer = io.BytesIO()
            gerar_relatorio(relatorio, buffer)
            buffer.seek(0)
            nome = _nome_arquivo(cd["cliente"], cd.get("periodo", ""))
            return FileResponse(buffer, as_attachment=True, filename=nome)
    else:
        form = RevisaoForm(initial={
            "cliente": dados.get("cliente", ""),
            "periodo": dados.get("periodo", ""),
            "analise": dados.get("analise_sugerida", ""),
        })

    return render(request, "relatorios/revisao.html", {"form": form, "dados": dados})


def _revisao_grupo(request, dados):
    """Etapa 2 do modo consolidado — nomes das unidades e análise geral editáveis."""
    unidades = dados["unidades"]
    nomes = [u["nome"] for u in unidades]

    if request.method == "POST":
        form = RevisaoGrupoForm(request.POST, nomes_unidades=nomes)
        if form.is_valid():
            cd = form.cleaned_data
            for i, u in enumerate(unidades):
                u["nome"] = (cd.get(f"unidade_{i}") or "").strip() or u["nome"]
            nomes_finais = [u["nome"] for u in unidades]
            rodape = ("Unidades incluídas no consolidado: "
                      + ", ".join(nomes_finais)
                      + ". Relatório gerado a partir de dados exportados do "
                      "Meta Ads Manager.")
            relatorio = {
                "titulo": "Relatório de Tráfego Pago",
                "cliente": cd["cliente"],
                "periodo": cd["periodo"],
                "subtitulo_extra": f"Consolidado de {len(unidades)} unidades",
                "funil": dados.get("funil"),
                "grafico_funil": dados.get("grafico_funil"),
                # Composição remontada para refletir nomes de unidade editados
                "composicao": montar_composicao(unidades),
                "unidades": [{"nome": n} for n in nomes_finais],
                "analise": [p.strip() for p in cd["analise"].split("\n\n") if p.strip()],
                "rodape": rodape,
            }
            buffer = io.BytesIO()
            gerar_relatorio(relatorio, buffer)
            buffer.seek(0)
            nome = _nome_arquivo(cd["cliente"], cd.get("periodo", ""))
            return FileResponse(buffer, as_attachment=True, filename=nome)
    else:
        form = RevisaoGrupoForm(nomes_unidades=nomes, initial={
            "cliente": dados.get("cliente", ""),
            "periodo": dados.get("periodo", ""),
            "analise": dados.get("analise_sugerida", ""),
        })

    contexto = {
        "form": form,
        "dados": dados,
        "modo_grupo": True,
        "pares_unidades": list(zip(unidades, form.campos_unidades())),
    }
    return render(request, "relatorios/revisao.html", contexto)


_MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]


def _slug(texto):
    """Translitera acentos (São -> Sao) e troca o resto por hífen."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = sem_acento.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-")


def _nome_arquivo(cliente, periodo):
    """Ex.: 'Tim-Sao-Jose-Campanhas-1-de-jul-de-2026-15-de-jul-de-2026.pdf'"""
    empresa = _slug(cliente) or "cliente"
    try:
        inicio, fim = (datetime.strptime(p.strip(), "%d/%m/%Y")
                       for p in periodo.split(" a "))
        datas = "-".join(f"{d.day}-de-{_MESES_PT[d.month - 1]}-de-{d.year}"
                         for d in (inicio, fim))
    except ValueError:
        datas = f"{datetime.now():%d-%m-%Y}"
    return f"{empresa}-Campanhas-{datas}.pdf"

