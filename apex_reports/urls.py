from django.urls import path

from relatorios import views, views_leitura, views_verba

# Sem /admin: a aplicação não tem modelo nenhum para administrar, e o painel
# do Django seria um segundo formulário de login exposto em HTTP puro (não há
# domínio, logo não há HTTPS — ver deploy/deploy.sh). Quem protege o acesso é
# o basic auth do nginx.
#
# A raiz é a escolha entre as três frentes, cada uma sob o seu prefixo.
# Desempenho e leitura lêem o MESMO export e diferem no que entregam — um PDF
# de páginas e uma mensagem de WhatsApp; a verba lê outro export, do preset
# próprio. Misturá-las numa tela só faria o operador enviar a planilha errada,
# que é um erro silencioso: os dois arquivos abrem sem reclamar.
urlpatterns = [
    path("", views.home, name="home"),
    path("desempenho/", views.index, name="index"),
    path("desempenho/revisao/", views.revisao, name="revisao"),
    path("leitura/", views_leitura.painel, name="leitura"),
    path("leitura/mensagem/", views_leitura.leitura, name="leitura_mensagem"),
    path("verba/", views_verba.painel, name="verba"),
    path("verba/fechamento/", views_verba.fechamento, name="verba_fechamento"),
]
