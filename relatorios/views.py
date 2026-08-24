# -*- coding: utf-8 -*-
import io
import os
import re
import unicodedata
from datetime import date, datetime

from django.http import FileResponse
from django.shortcuts import redirect, render

from . import redator_ia
from .forms import (RevisaoForm, RevisaoGrupoForm, RevisaoIndicadorForm,
                    RevisaoListagemForm, UploadForm)
from .gerador_indicador import gerar_indicador, montar_tabela
from .gerador_listagem import gerar_listagem, montar_linhas
from .gerador_pdf import gerar_relatorio
from .parser_xlsx import (VEICULACAO_TODAS, VEICULACOES, consolidar,
                          consolidar_grupo, filtrar_campanhas,
                          filtrar_veiculacao, grupos_de_campanha,
                          ler_export_meta, ler_registros, montar_composicao,
                          substituir_leituras)

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
                    sessao = {
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
                    if modo == UploadForm.MODO_LISTAGEM:
                        sessao.update(_fonte_reconsolidacao(lidos))
                    request.session[SESSION_KEY] = sessao
                    return redirect("revisao")
                if modo == UploadForm.MODO_UNICO:
                    # `_num` fica na sessão (o consolidado sempre precisou
                    # dele): é a fonte dos totais no payload do redator de IA,
                    # e são onze números — não é ele que engorda a sessão.
                    dados = lidos[0]["dados"]
                else:
                    dados = consolidar_grupo(lidos)
                    dados.update(_fonte_reconsolidacao(lidos))
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
        conta = {"nome": nome, "registros": registros, "mapa": mapa,
                 "dados": consolidar(registros, mapa, nome)}
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


# ----------------------------------------------------------------------
# Seleção de campanhas (consolidado e listagem)
# ----------------------------------------------------------------------
# Nome do botão que refaz a leitura com outra seleção. A escolha mora na
# revisão, não no painel, por um motivo que não é de gosto: os grupos de
# campanha só existem depois de ler os anexos — no painel não haveria o que
# marcar. O filtro de veiculação do modo Indicador é o precedente da mesma
# ideia; o que não dá para copiar dele é pré-calcular as variantes, porque
# aqui são 2^N combinações em vez de três.
CAMPO_CAMPANHAS = "aplicar_campanhas"


def _pediu_campanhas(request):
    return CAMPO_CAMPANHAS in request.POST


def _fonte_reconsolidacao(lidos):
    """O que a sessão guarda para refazer a leitura sem pedir os anexos de novo.

    `_indices` diz a que anexo cada unidade do relatório corresponde: com um
    filtro aplicado a lista de unidades encolhe, e sem isso os campos de nome
    da tela apontariam para o anexo errado na segunda seleção.

    Custo medido nos 13 exports TIM: 10 KB de registros, contra os 35 KB que a
    sessão do consolidado já ocupava.
    """
    return {
        "_anexos": [{"nome": c["nome"], "registros": c["registros"],
                     "mapa": c["mapa"]} for c in lidos],
        "_indices": list(range(len(lidos))),
    }


def _grupos_disponiveis(anexos):
    """Grupos de campanha somados de todos os anexos, do mais presente ao menos.

    Leva junto o que a tela mostra para o operador conferir o agrupamento: em
    quantos anexos o grupo aparece e quais são as campanhas dentro dele.
    """
    grupos = {}
    for anexo in anexos:
        for g in grupos_de_campanha(anexo["registros"]):
            acc = grupos.setdefault(g["chave"],
                                    {"chave": g["chave"], "campanhas": [], "anexos": 0})
            acc["anexos"] += 1
            for nome in g["campanhas"]:
                if nome not in acc["campanhas"]:
                    acc["campanhas"].append(nome)
    return sorted(grupos.values(), key=lambda g: (-g["anexos"], g["chave"]))


def _chaves(grupos):
    return [g["chave"] for g in grupos]


def _selecao_atual(dados, grupos):
    """Seleção a marcar na tela: a última aplicada, ou tudo na primeira visita."""
    return dados.get("_selecao_campanhas") or _chaves(grupos)


def _reconsolidar(anexos, selecao):
    """`(unidades, índices dos anexos que sobraram)` para a seleção dada.

    Anexo sem nenhuma campanha do filtro sai do relatório: uma linha de zeros e
    uma fatia de 0% na composição dizem menos do que a unidade não aparecer.
    Nenhuma planilha é reaberta — só o laço Python sobre os registros.
    """
    unidades, indices = [], []
    for i, anexo in enumerate(anexos):
        linhas = filtrar_campanhas(anexo["registros"], selecao)
        if not linhas:
            continue
        unidades.append({"nome": anexo["nome"],
                         "dados": consolidar(linhas, anexo["mapa"], anexo["nome"])})
        indices.append(i)
    return unidades, indices


def _aplicar_selecao(dados, form, minimo, erro_minimo):
    """`(unidades, índices, seleção, erro)` — refaz a leitura pela seleção do form.

    O nome que o operador acabou de digitar volta para o anexo antes do filtro:
    os campos da tela seguem os anexos que sobraram da seleção anterior, e sem
    esse passo o texto digitado se perderia a cada clique.
    """
    anexos = dados["_anexos"]
    vivos = dados.get("_indices") or list(range(len(anexos)))
    for i, nome in zip(vivos, form.nomes_finais([anexos[i]["nome"] for i in vivos])):
        anexos[i]["nome"] = nome

    selecao = form.cleaned_data.get("campanhas") or None
    if "campanhas" in form.fields and not selecao:
        # Desmarcar tudo não é "todas as campanhas" — é um relatório vazio.
        return None, None, None, "Marque pelo menos um grupo de campanhas."
    unidades, indices = _reconsolidar(anexos, selecao)
    if len(unidades) < minimo:
        return None, None, None, erro_minimo
    return unidades, indices, selecao, None


def _pares_campanhas(form, grupos):
    """(caixa de seleção, grupo) para a tela — os contadores e a lista de
    campanhas vêm do grupo, não do widget. None quando não há o que escolher."""
    if "campanhas" not in form.fields:
        return None
    return list(zip(form["campanhas"], grupos))


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
        # Crédito acabado, chave recusada, modelo inexistente: o botão sai da
        # tela junto com o aviso. Continuar oferecendo um clique que já se sabe
        # perdido é pior do que não oferecer nenhum.
        definitivo = e.motivo in redator_ia.DEFINITIVOS
        return form, {"erro_ia": str(e),
                      "erro_ia_definitivo": definitivo,
                      "ia_disponivel": redator_ia.disponivel() and not definitivo}

    # O mesmo limite que o prompt pediu ao modelo: fossem dois números, a IA
    # escreveria para um e o operador seria avisado pelo outro.
    texto, avisos = redator_ia.para_pdf(
        bruto, limite=redator_ia.limite_do_texto(dados))

    # O bruto fica guardado com os asteriscos: é ele que serve para o WhatsApp,
    # e regerar a mesma análise só para mudar de destino custaria outra chamada.
    dados["analise_ia_bruta"] = bruto
    dados["analise_ia"] = texto

    # Segunda chamada, à parte da análise: reescreve as legendas do funil
    # (Frequência, CPM, CTR, Taxa de Conversão) a partir dos mesmos números.
    # Falhar aqui não desfaz o que já foi salvo acima — vira só mais um aviso
    # não bloqueante, e as legendas ficam com o texto estático de sempre.
    try:
        leituras = redator_ia.gerar_leituras_funil(dados)
        substituir_leituras(dados.get("funil"), leituras)
    except redator_ia.ErroDeIA as e:
        avisos.append(f"Legendas do funil: {e}")

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
    if hasattr(form, "grupos_campanha"):
        # Sem isto o campo de campanhas não renasceria e a seleção sumiria da
        # tela depois de um clique na IA.
        kwargs["grupos_campanha"] = form.grupos_campanha
    return type(form)(initial=inicial, **kwargs)


_ERRO_MINIMO_GRUPO = (
    "A seleção deixaria menos de 2 unidades no consolidado — não há anexo "
    "suficiente com campanha dos grupos marcados. A seleção anterior continua "
    "valendo."
)


def _revisao_grupo(request, dados):
    """Etapa 2 do modo consolidado — nomes das unidades e análise geral editáveis."""
    unidades = dados["unidades"]
    nomes = [u["nome"] for u in unidades]
    grupos = _grupos_disponiveis(dados.get("_anexos") or [])

    if request.method == "POST":
        form = RevisaoGrupoForm(request.POST, nomes_unidades=nomes,
                                grupos_campanha=_chaves(grupos))
        # `grupos` vazio = sessão sem os registros (aberta antes de a seleção
        # existir): não há o que refazer, e o POST forjado não deve estourar.
        if form.is_valid() and grupos and _pediu_campanhas(request):
            dados, form, extra = _refazer_grupo(request, dados, form, grupos)
            return render(request, "relatorios/revisao.html", dict(
                extra, form=form, dados=dados, modo_grupo=True,
                pares_unidades=list(zip(dados["unidades"], form.campos_unidades())),
                pares_campanhas=_pares_campanhas(form, grupos)))
        if form.is_valid() and _pediu_ia(request):
            form, extra = _analisar_com_ia(request, dados, form)
            return render(request, "relatorios/revisao.html", dict(
                extra, form=form, dados=dados, modo_grupo=True,
                pares_unidades=list(zip(unidades, form.campos_unidades())),
                pares_campanhas=_pares_campanhas(form, grupos)))
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
        form = _form_grupo(dados, grupos)

    contexto = {
        "form": form,
        "dados": dados,
        "modo_grupo": True,
        "ia_disponivel": redator_ia.disponivel(),
        "pares_unidades": list(zip(unidades, form.campos_unidades())),
        "pares_campanhas": _pares_campanhas(form, grupos),
    }
    return render(request, "relatorios/revisao.html", contexto)


def _form_grupo(dados, grupos, cliente=None, periodo=None):
    """Formulário do consolidado montado a partir da sessão."""
    return RevisaoGrupoForm(
        nomes_unidades=[u["nome"] for u in dados["unidades"]],
        grupos_campanha=_chaves(grupos),
        initial={
            "cliente": dados.get("cliente", "") if cliente is None else cliente,
            "periodo": dados.get("periodo", "") if periodo is None else periodo,
            "analise": _texto_da_analise(dados),
            "campanhas": _selecao_atual(dados, grupos),
        })


def _refazer_grupo(request, dados, form, grupos):
    """Refaz o consolidado com a seleção de campanhas do form.

    Reconstrói tudo — KPIs, funil, composição, gráficos e a análise do motor —,
    porque com outro conjunto de campanhas todos esses números mudam. Pelo
    mesmo motivo o texto da IA é descartado: ele foi escrito sobre os números
    anteriores, e mantê-lo na tela seria oferecer uma leitura de outro
    relatório. Cliente e período digitados sobrevivem: são do operador, não da
    planilha.
    """
    cd = form.cleaned_data
    unidades, indices, selecao, erro = _aplicar_selecao(
        dados, form, minimo=2, erro_minimo=_ERRO_MINIMO_GRUPO)
    if erro:
        return dados, form, {"erro_campanhas": erro,
                             "ia_disponivel": redator_ia.disponivel()}

    novo = consolidar_grupo(unidades)
    novo["cliente"] = cd["cliente"]
    novo["periodo"] = cd.get("periodo") or novo.get("periodo", "")
    novo["_anexos"] = dados["_anexos"]
    novo["_indices"] = indices
    novo["_selecao_campanhas"] = selecao
    request.session[SESSION_KEY] = novo
    request.session.modified = True

    return novo, _form_grupo(novo, grupos), {
        "campanhas_aplicadas": True,
        "unidades_fora": len(dados["_anexos"]) - len(unidades),
        "ia_disponivel": redator_ia.disponivel(),
    }


_ERRO_MINIMO_LISTAGEM = (
    "Nenhum anexo tem campanha dos grupos marcados — a listagem sairia vazia. "
    "A seleção anterior continua valendo."
)


def _revisao_listagem(request, dados):
    """Etapa 2 do modo Listagem — título e nomes das contas antes do PDF."""
    contas = dados["contas"]
    nomes = [c["nome"] for c in contas]
    grupos = _grupos_disponiveis(dados.get("_anexos") or [])
    extra = {}

    if request.method == "POST":
        form = RevisaoListagemForm(request.POST, nomes_unidades=nomes,
                                   grupos_campanha=_chaves(grupos))
        if form.is_valid() and grupos and _pediu_campanhas(request):
            dados, form, extra = _refazer_listagem(request, dados, form, grupos)
            contas = dados["contas"]
        elif form.is_valid():
            for conta, nome in zip(contas, form.nomes_finais(nomes)):
                conta["nome"] = nome
            request.session[SESSION_KEY] = dados      # nomes revisados persistem
            return _sinalizar_download(request, _pdf_listagem(
                form.cleaned_data["titulo"], contas, form.periodo()))
    else:
        form = _form_listagem(dados, grupos)

    return render(request, "relatorios/revisao.html", dict(
        extra,
        form=form, dados=dados, modo_listagem=True,
        pares_unidades=list(zip(contas, form.campos_unidades())),
        pares_campanhas=_pares_campanhas(form, grupos),
        previa=montar_linhas(contas)))


def _form_listagem(dados, grupos, periodo=None):
    """Formulário da listagem montado a partir da sessão.

    `periodo` None manda detectar as datas dos anexos (primeira visita); uma
    tupla vale como está, inclusive vazia — datas que o operador apagou não
    voltam sozinhas ao aplicar uma seleção.
    """
    inicio, fim = periodo if periodo is not None \
        else _periodo_detectado(dados["contas"])
    return RevisaoListagemForm(
        nomes_unidades=[c["nome"] for c in dados["contas"]],
        grupos_campanha=_chaves(grupos),
        initial={"titulo": dados.get("titulo", ""), "inicio": inicio, "fim": fim,
                 "campanhas": _selecao_atual(dados, grupos)})


def _refazer_listagem(request, dados, form, grupos):
    """Refaz a listagem com a seleção de campanhas do form.

    Cada conta é reconsolidada só com as campanhas escolhidas, e o ranking sai
    de novo dos números novos — a ordem das linhas pode mudar, que é justamente
    o ponto de comparar só um produto.
    """
    cd = form.cleaned_data
    unidades, indices, selecao, erro = _aplicar_selecao(
        dados, form, minimo=1, erro_minimo=_ERRO_MINIMO_LISTAGEM)
    if erro:
        return dados, form, {"erro_campanhas": erro}

    novo = dict(dados,
                titulo=cd["titulo"],
                contas=[{"nome": u["nome"], "dados": _enxuto(u["dados"])}
                        for u in unidades],
                _indices=indices,
                _selecao_campanhas=selecao)
    request.session[SESSION_KEY] = novo
    request.session.modified = True

    return novo, _form_listagem(novo, grupos, (cd.get("inicio"), cd.get("fim"))), {
        "campanhas_aplicadas": True,
        "unidades_fora": len(dados["_anexos"]) - len(unidades),
    }


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

