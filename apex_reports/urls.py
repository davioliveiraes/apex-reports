from django.urls import path

from relatorios import views

# Sem /admin: a aplicação não tem modelo nenhum para administrar, e o painel
# do Django seria um segundo formulário de login exposto em HTTP puro (não há
# domínio, logo não há HTTPS — ver deploy/deploy.sh). Quem protege o acesso é
# o basic auth do nginx.
urlpatterns = [
    path("", views.index, name="index"),
    path("revisao/", views.revisao, name="revisao"),
]
