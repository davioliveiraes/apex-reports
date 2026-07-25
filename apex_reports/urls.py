from django.contrib import admin
from django.urls import path

from relatorios import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.index, name="index"),
    path("revisao/", views.revisao, name="revisao"),
]
