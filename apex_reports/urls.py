from django.urls import path

from relatorios import views, views_verba

# Sem /admin: a aplicação não tem modelo nenhum para administrar, e o painel
# do Django seria um segundo formulário de login exposto em HTTP puro (não há
# domínio, logo não há HTTPS — ver deploy/deploy.sh). Quem protege o acesso é
# o basic auth do nginx.
#
# A raiz é a escolha entre as duas frentes. Cada uma leva o seu prefixo porque
# são exports diferentes do Gerenciador respondendo perguntas diferentes:
# desempenho lê como as campanhas entregaram, verba lê como o orçamento está
# configurado. Misturá-las numa tela só faria o operador enviar a planilha
# errada — que é um erro silencioso, já que as duas abrem sem reclamar.
urlpatterns = [
    path("", views.home, name="home"),
    path("desempenho/", views.index, name="index"),
    path("desempenho/revisao/", views.revisao, name="revisao"),
    path("verba/", views_verba.painel, name="verba"),
    path("verba/fechamento/", views_verba.fechamento, name="verba_fechamento"),
]
