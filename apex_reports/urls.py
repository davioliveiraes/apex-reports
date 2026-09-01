from django.urls import path

from relatorios import (views, views_desempenho, views_leitura,
                       views_rastreamento, views_verba)

# Sem /admin: a aplicação não tem modelo nenhum para administrar, e o painel
# do Django seria um segundo formulário de login exposto em HTTP puro (não há
# domínio, logo não há HTTPS — ver deploy/deploy.sh). Quem protege o acesso é
# o basic auth do nginx.
#
# A raiz é a escolha entre as análises, cada uma sob o seu prefixo. Os nomes
# das VIEWS são os antigos (`index`, `revisao`) porque são as mesmas telas de
# sempre; o que mudou em 30/08/2026 foi o prefixo. `/desempenho/` era a
# Análise Geral, e passou a ser a frente que de fato lê o preset DESEMPENHO —
# o cartão já se chamava "Análise Geral" desde 29/08, e a URL tinha ficado
# descrevendo a frente errada.
#
# Cada frente lê um preset diferente do Gerenciador, e essa é a razão de não
# haver uma tela só: os exports abrem sem reclamar uns pelos outros, então
# mandar o arquivo errado é um erro silencioso. Separar as portas é o que o
# transforma num erro que aparece.
urlpatterns = [
    path("", views.home, name="home"),
    path("geral/", views.index, name="index"),
    path("geral/revisao/", views.revisao, name="revisao"),
    path("desempenho/", views_desempenho.painel, name="desempenho"),
    path("desempenho/analise/", views_desempenho.analise,
         name="desempenho_analise"),
    path("desempenho/consolidado/", views_desempenho.consolidado,
         name="desempenho_consolidado"),
    # A Leitura Rápida saiu da home em 30/08/2026: o que estava aqui não é a
    # frente que o produto quer com esse nome (ver docs/CONTEXTO.md). A rota
    # continua publicada e testada, sem link para ela, até o fluxo novo ser
    # definido — apagar código que funciona antes de ter o substituto é
    # trocar uma incoerência de nome por uma perda de função.
    path("leitura/", views_leitura.painel, name="leitura"),
    path("leitura/mensagem/", views_leitura.leitura, name="leitura_mensagem"),
    path("verba/", views_verba.painel, name="verba"),
    path("verba/fechamento/", views_verba.fechamento, name="verba_fechamento"),
    path("rastreamento/", views_rastreamento.painel, name="rastreamento"),
    path("rastreamento/analise/", views_rastreamento.analise,
         name="rastreamento_analise"),
]
