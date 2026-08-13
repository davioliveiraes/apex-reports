# -*- coding: utf-8 -*-
import io
import os
import re
import unicodedata
from datetime import date, datetime

from django.http import FileResponse
from django.shortcuts import redirect, render

from . import redator_ia
from .analysis import templates as templates_analise
from .forms import (RevisaoForm, RevisaoGrupoForm, RevisaoIndicadorForm,
                    RevisaoListagemForm, UploadForm)
from .gerador_indicador import gerar_indicador, montar_tabela
from .gerador_listagem import gerar_listagem, montar_linhas
from .gerador_pdf import gerar_relatorio
from .parser_xlsx import (VEICULACAO_TODAS, VEICULACOES, consolidar,
                          consolidar_grupo, filtrar_veiculacao, ler_export_meta,
                          ler_registros, montar_composicao)

SESSION_KEY = "relatorio_apex"


def index(request):
    """Painel — escolha do modo + upload de 1 a 20 .xlsx.

    Os quatro modos — único, consolidado, listagem e indicador único — seguem
    o mesmo fluxo de duas etapas: aqui os anexos são lidos e guardados na
    sessão; a revisão confere o resultado e gera o PDF.
    """
    erro = None
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            modo = form.cleaned_data["modo"]
            lidos, erro = _ler_arquivos(
                form.cleaned_data["arquivos"], request.POST.getlist("nome_conta"),
                # Só o indicador único reoferece o filtro de veiculação na
                # revisão, então só ele paga o custo das três consolidações.
                variantes=modo == UploadForm.MODO_INDICADOR)
            if not erro:
                if modo in (UploadForm.MODO_LISTAGEM, UploadForm.MODO_INDICADOR):
                    request.session[SESSION_KEY] = {
                        "modo": modo,
                        "titulo": form.cleaned_data["titulo"],
                        "cliente": form.cleaned_data["cliente"],
                        "metrica": form.cleaned_data["metrica"],
                        "veiculacao": form.cleaned_data["veiculacao"],
                        "contas": [{"nome": c["nome"], "dados": _enxuto(c["dados"]),
                                    "variantes": c.get("variantes"),
                                    "tem_veiculacao": c.get("tem_veiculacao", False)}
                                   for c in lidos],
                    }
                    return redirect("revisao")
                if modo == UploadForm.MODO_UNICO:
                    # `_num` fica na sessão (o consolidado sempre precisou
                    # dele): é a fonte dos totais no payload do redator de IA,
                    # e são onze números — não é ele que engorda a sessão.
                    dados = lidos[0]["dados"]
                else:
                    dados = consolidar_grupo(lidos)
                dados["cliente"] = form.cleaned_data["cliente"]
                request.session[SESSION_KEY] = dados
                return redirect("revisao")
    else:
        form = UploadForm()
    return render(request, "relatorios/index.html", {"form": form, "erro": erro})


# Campos do parser de que os modos listagem/indicador realmente precisam.
# Guardar só isto mantém a sessão enxuta com 20 contas (o funil, a análise
# sugerida e os detalhes por campanha não entram nesses dois PDFs).
_CAMPOS_CONTA = ("_num", "_colunas", "kpis", "indicador", "periodo")


def _enxuto(dados):
    return {k: dados[k] for k in _CAMPOS_CONTA if k in dados}


def _sinalizar_download(request, resposta):
    """O PDF volta como FileResponse e a página não navega — o front fica sem
    saber que o arquivo já saiu. Devolvemos, junto do PDF, um cookie com o
    token que o form enviou; o JS o detecta e fecha a etapa na tela."""
    token = request.POST.get("download_token")
    if token:
        resposta.set_cookie("apex_download", token, max_age=60, samesite="Lax")
    return resposta


def _periodo_detectado(contas):
    """(início mais antigo, fim mais recente) entre os anexos — sugestão para
    o campo de período na revisão.

    Sai do período que o parser já leu de cada arquivo ("dd/mm/aaaa a
    dd/mm/aaaa"); anexo sem as colunas de data simplesmente não participa.
    """
    inicios, fins = [], []
    for c in contas:
        partes = ((c.get("dados") or {}).get("periodo") or "").split(" a ")
        if len(partes) != 2:
            continue
        try:
            i, f = (datetime.strptime(p.strip(), "%d/%m/%Y").date()
                    for p in partes)
        except ValueError:
            continue
        inicios.append(i)
        fins.append(f)
    return (min(inicios), max(fins)) if inicios else (None, None)


def _pdf_listagem(titulo, contas, periodo=""):
    """Modo 3 — PDF de listagem. As linhas saem ranqueadas por número de
    resultados; `contas` chega aqui na ordem de envio dos anexos."""
    buffer = io.BytesIO()
    gerar_listagem(titulo, contas, buffer, periodo=periodo)
    buffer.seek(0)
    nome = _nome_arquivo(titulo or "Relatorio de Listagem",
                         UploadForm.MODO_LISTAGEM, *_datas_periodo(periodo))
    return FileResponse(buffer, as_attachment=True, filename=nome)


def _pdf_indicador(cliente, chave_metrica, contas, veiculacao=VEICULACAO_TODAS):
    """Modo 4 — PDF de uma métrica comparada entre contas. `contas` mantém a
    ordem de envio; a ordenação das linhas segue a direção de `melhor` no
    registro de métricas."""
    buffer = io.BytesIO()
    gerar_indicador(cliente, chave_metrica, contas, buffer, veiculacao)
    buffer.seek(0)
    nome = _nome_arquivo(cliente, UploadForm.MODO_INDICADOR,
                         *_periodo_detectado(contas))
    return FileResponse(buffer, as_attachment=True, filename=nome)


def _ler_arquivos(arquivos, nomes=None, variantes=False):
    """Lê cada anexo; ao falhar, devolve erro apontando QUAL arquivo falhou.

    `nomes` são os nomes de conta digitados no painel, na mesma ordem dos
    anexos. Quando em branco (ou ausentes), cai no nome derivado do arquivo —
    assim o modo de anexo único, que não expõe o campo, segue funcionando.

    `variantes` consolida o mesmo anexo nos três filtros de veiculação, para
    a revisão poder trocar de filtro sem pedir o arquivo de novo.
    """
    nomes = nomes or []
    lidos = []
    for i, f in enumerate(arquivos):
        try:
            registros, mapa = ler_registros(f)
        except ValueError as e:
            return None, f'Arquivo "{f.name}": {e}'
        except Exception:
            return None, (
                f'Não foi possível ler "{f.name}". '
                "Confira se é um .xlsx válido do Meta Ads Manager."
            )
        digitado = (nomes[i] if i < len(nomes) else "").strip()
        nome = digitado or _nome_unidade(f.name)
        conta = {"nome": nome, "dados": consolidar(registros, mapa, nome)}
        if variantes:
            # Filtro sem nenhuma campanha → None: a conta entra no PDF como
            # "—", fora do total, em vez de virar uma linha de zeros.
            conta["variantes"] = {
                chave: (_enxuto(consolidar(linhas, mapa, nome)) if linhas else None)
                for chave, _ in VEICULACOES
                for linhas in [filtrar_veiculacao(registros, chave)]
            }
            conta["tem_veiculacao"] = "veiculacao" in mapa
        lidos.append(conta)
    return lidos, None


def _contas_veiculacao(contas, veiculacao):
    """Contas prontas para o gerador, no filtro de veiculação escolhido.

    Export sem a coluna de veiculação não tem como ser filtrado: entra com
    todas as campanhas e é sinalizado, em vez de sumir da comparação.
    """
    saida = []
    for c in contas:
        variantes = c.get("variantes") or {}
        ignorado = veiculacao != VEICULACAO_TODAS and not c.get("tem_veiculacao")
        dados = variantes.get(VEICULACAO_TODAS if ignorado else veiculacao,
                              c.get("dados"))
        saida.append({
            "nome": c["nome"],
            "dados": dados or {"_num": {}, "_colunas": []},
            "sem_campanhas": dados is None,
            "filtro_ignorado": ignorado,
        })
    return saida


def _paragrafos(texto):
    """Blocos da análise, um por parágrafo do PDF.

    O textarea devolve quebra de linha no formato do HTML (`\\r\\n`), então
    separar por `\\n\\n` cru não acha separador nenhum e a análise inteira sai
    num parágrafo só — que é como o bug aparecia no PDF. Normaliza antes de
    cortar, e aceita também linhas em branco com espaço no meio.
    """
    normalizado = texto.replace("\r\n", "\n").replace("\r", "\n")
    return [p.strip() for p in re.split(r"\n[ \t]*\n", normalizado) if p.strip()]


def _nome_unidade(nome_arquivo):
    """Nome sugerido da unidade a partir do nome do arquivo (editável na revisão)."""
    base = os.path.splitext(os.path.basename(nome_arquivo))[0]
    return re.sub(r"[-_]+", " ", base).strip() or "Unidade"


def revisao(request):
    """Etapa 2 — revisar KPIs lidos e editar análise antes de gerar o PDF."""
    dados = request.session.get(SESSION_KEY)
    if not dados:
        return redirect("index")

    modo = dados.get("modo")
    if modo == "grupo":
        return _revisao_grupo(request, dados)
    if modo == UploadForm.MODO_LISTAGEM:
        return _revisao_listagem(request, dados)
    if modo == UploadForm.MODO_INDICADOR:
        return _revisao_indicador(request, dados)

    if request.method == "POST":
        form = RevisaoForm(request.POST)
        if form.is_valid() and _pediu_ia(request):
            form, extra = _analisar_com_ia(request, dados, form)
            return render(request, "relatorios/revisao.html",
                          dict(extra, form=form, dados=dados))
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
                "analise": _paragrafos(cd["analise"]),
            }
            buffer = io.BytesIO()
            gerar_relatorio(relatorio, buffer)
            buffer.seek(0)
            nome = _nome_arquivo(cd["cliente"], UploadForm.MODO_UNICO,
                                 *_datas_periodo(cd.get("periodo", "")))
            return _sinalizar_download(
                request, FileResponse(buffer, as_attachment=True, filename=nome))
    else:
        form = RevisaoForm(initial={
            "cliente": dados.get("cliente", ""),
            "periodo": dados.get("periodo", ""),
            "analise": _texto_da_analise(dados),
        })

    return render(request, "relatorios/revisao.html",
                  {"form": form, "dados": dados, "ia_disponivel": redator_ia.disponivel()})


# ----------------------------------------------------------------------
# Análise do Período escrita por IA
# ----------------------------------------------------------------------
CAMPO_IA = "analise_ia"


def _pediu_ia(request):
    return CAMPO_IA in request.POST


def _texto_da_analise(dados):
    """O que o textarea mostra: a última análise da IA, se houve uma, e o
    texto do motor de regras enquanto não houver."""
    return dados.get("analise_ia") or dados.get("analise_sugerida", "")


def _analisar_com_ia(request, dados, form):
    """Pede o texto ao modelo e devolve `(form a renderizar, contexto extra)`.

    Falhar aqui é rotina — rede, crédito, modelo errado —, e falhar não pode
    custar o relatório: o erro vira aviso na tela e o texto que estava no
    formulário continua onde estava, sem ser tocado.
    """
    try:
        bruto = redator_ia.gerar(dados)
    except redator_ia.ErroDeIA as e:
        return form, {"erro_ia": str(e), "ia_disponivel": redator_ia.disponivel()}

    limite = (templates_analise.LIMITE_PDF_GRUPO if dados.get("modo") == "grupo"
              else templates_analise.LIMITE_PDF)
    texto, avisos = redator_ia.para_pdf(bruto, limite=limite)

    # O bruto fica guardado com os asteriscos: é ele que serve para o WhatsApp,
    # e regerar a mesma análise só para mudar de destino custaria outra chamada.
    dados["analise_ia_bruta"] = bruto
    dados["analise_ia"] = texto
    request.session[SESSION_KEY] = dados
    request.session.modified = True

    return _com_texto(form, texto), {"analise_ia_gerada": True,
                                     "avisos_ia": avisos,
                                     "ia_disponivel": True}


def _com_texto(form, texto):
    """O mesmo formulário, com o textarea trocado.

    O `data` de um form já vinculado é imutável, então o texto novo entra por
    `initial` num form não vinculado — o resto dos campos volta como veio.
    """
    inicial = dict(form.cleaned_data, analise=texto)
    kwargs = {}
    if hasattr(form, "n_unidades"):
        kwargs["nomes_unidades"] = [form.cleaned_data.get(f"unidade_{i}") or ""
                                    for i in range(form.n_unidades)]
    return type(form)(initial=inicial, **kwargs)


def _revisao_grupo(request, dados):
    """Etapa 2 do modo consolidado — nomes das unidades e análise geral editáveis."""
    unidades = dados["unidades"]
    nomes = [u["nome"] for u in unidades]

    if request.method == "POST":
        form = RevisaoGrupoForm(request.POST, nomes_unidades=nomes)
        if form.is_valid() and _pediu_ia(request):
            form, extra = _analisar_com_ia(request, dados, form)
            return render(request, "relatorios/revisao.html", dict(
                extra, form=form, dados=dados, modo_grupo=True,
                pares_unidades=list(zip(unidades, form.campos_unidades()))))
        if form.is_valid():
            cd = form.cleaned_data
            nomes_finais = form.nomes_finais(nomes)
            for u, nome in zip(unidades, nomes_finais):
                u["nome"] = nome
            nota_unidades = ("Unidades incluídas no consolidado: "
                             + ", ".join(nomes_finais) + ".")
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
                "analise": _paragrafos(cd["analise"]),
                "nota_unidades": nota_unidades,
            }
            buffer = io.BytesIO()
            gerar_relatorio(relatorio, buffer)
            buffer.seek(0)
            nome = _nome_arquivo(cd["cliente"], UploadForm.MODO_CONSOLIDADO,
                                 *_datas_periodo(cd.get("periodo", "")))
            return _sinalizar_download(
                request, FileResponse(buffer, as_attachment=True, filename=nome))
    else:
        form = RevisaoGrupoForm(nomes_unidades=nomes, initial={
            "cliente": dados.get("cliente", ""),
            "periodo": dados.get("periodo", ""),
            "analise": _texto_da_analise(dados),
        })

    contexto = {
        "form": form,
        "dados": dados,
        "modo_grupo": True,
        "ia_disponivel": redator_ia.disponivel(),
        "pares_unidades": list(zip(unidades, form.campos_unidades())),
    }
    return render(request, "relatorios/revisao.html", contexto)


def _revisao_listagem(request, dados):
    """Etapa 2 do modo Listagem — título e nomes das contas antes do PDF."""
    contas = dados["contas"]
    nomes = [c["nome"] for c in contas]

    if request.method == "POST":
        form = RevisaoListagemForm(request.POST, nomes_unidades=nomes)
        if form.is_valid():
            for conta, nome in zip(contas, form.nomes_finais(nomes)):
                conta["nome"] = nome
            request.session[SESSION_KEY] = dados      # nomes revisados persistem
            return _sinalizar_download(request, _pdf_listagem(
                form.cleaned_data["titulo"], contas, form.periodo()))
    else:
        inicio, fim = _periodo_detectado(contas)
        form = RevisaoListagemForm(nomes_unidades=nomes, initial={
            "titulo": dados.get("titulo", ""), "inicio": inicio, "fim": fim})

    return render(request, "relatorios/revisao.html", {
        "form": form, "dados": dados, "modo_listagem": True,
        "pares_unidades": list(zip(contas, form.campos_unidades())),
        "previa": montar_linhas(contas),
    })


def _revisao_indicador(request, dados):
    """Etapa 2 do modo Indicador Único — cliente, métrica e nomes das contas.

    A prévia mostra a mesma tabela do PDF (já ordenada pela direção de `melhor`
    e com o total agregado conforme a regra da métrica), para a conferência
    acontecer antes de gerar o arquivo."""
    contas = dados["contas"]
    nomes = [c["nome"] for c in contas]

    if request.method == "POST":
        form = RevisaoIndicadorForm(request.POST, nomes_unidades=nomes)
        if form.is_valid():
            for conta, nome in zip(contas, form.nomes_finais(nomes)):
                conta["nome"] = nome
            dados["metrica"] = form.cleaned_data["metrica"]
            dados["cliente"] = form.cleaned_data["cliente"]
            dados["veiculacao"] = form.cleaned_data["veiculacao"]
            request.session[SESSION_KEY] = dados
            return _sinalizar_download(request, _pdf_indicador(
                dados["cliente"], dados["metrica"],
                _contas_veiculacao(contas, dados["veiculacao"]),
                dados["veiculacao"]))
    else:
        form = RevisaoIndicadorForm(nomes_unidades=nomes, initial={
            "cliente": dados.get("cliente", ""),
            "metrica": dados.get("metrica", ""),
            "veiculacao": dados.get("veiculacao") or VEICULACAO_TODAS,
        })

    chave = dados.get("metrica")
    filtro = dados.get("veiculacao") or VEICULACAO_TODAS
    return render(request, "relatorios/revisao.html", {
        "form": form, "dados": dados, "modo_indicador": True,
        "pares_unidades": list(zip(contas, form.campos_unidades())),
        "previa_indicador": (
            montar_tabela(chave, _contas_veiculacao(contas, filtro), filtro)
            if chave else None),
    })


_MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]

# Trecho que identifica a funcionalidade no nome do arquivo. Fica separado das
# constantes de modo do form: aquelas são chaves internas ("unico"), estas o
# operador lê na pasta de downloads meses depois.
_FUNCIONALIDADES = {
    UploadForm.MODO_UNICO: "anexounico",
    UploadForm.MODO_CONSOLIDADO: "consolidado",
    UploadForm.MODO_LISTAGEM: "listagem",
    UploadForm.MODO_INDICADOR: "indicadorunico",
}


def _slug(texto):
    """Translitera acentos (São -> Sao) e troca o resto por hífen."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = sem_acento.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-")


def _data_curta(d):
    """1º de julho de 2026 -> '1-jul-26' (dia sem zero à esquerda)."""
    return f"{d.day}-{_MESES_PT[d.month - 1]}-{d:%y}"


def _datas_periodo(periodo):
    """(início, fim) a partir do período em texto — "01/07/2026 a 15/07/2026"
    dos modos 1 e 2, "01/07/2026 — 31/07/2026" da listagem."""
    partes = re.split(r"\s+(?:a|—|até)\s+", str(periodo or "").strip())
    if len(partes) != 2:
        return None, None
    try:
        return tuple(datetime.strptime(p.strip(), "%d/%m/%Y").date()
                     for p in partes)
    except ValueError:
        return None, None


def _nome_arquivo(empresa, modo, inicio=None, fim=None):
    """Nome do PDF, no mesmo padrão nos quatro modos:

        TIM-BRASIL-consolidado-1-jul-26-31-jul-26.pdf

    Sem período legível entra a data de geração, marcada como tal para não ser
    lida como intervalo: 'TIM-BRASIL-listagem-gerado-3-ago-26.pdf'.
    """
    partes = [_slug(empresa) or "cliente", _FUNCIONALIDADES.get(modo, modo)]
    if inicio and fim:
        partes += [_data_curta(inicio), _data_curta(fim)]
    else:
        partes += ["gerado", _data_curta(date.today())]
    return "-".join(partes) + ".pdf"

