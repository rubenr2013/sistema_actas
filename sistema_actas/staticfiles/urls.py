from django.urls import path
from . import views
from core import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("backup/", views.vista_backup, name="vista_backup"),
    path("backup/crear/", views.crear_copia_seguridad, name="crear_copia_seguridad"),
    path("backup/crear-personal/", views.crear_backup_personal, name="crear_backup_personal"),
    path("backup/restaurar-personal/", views.restaurar_backup_personal, name="restaurar_backup_personal"),
    path("backup/restaurar/<str:nombre_archivo>/", views.restaurar_backup, name="restaurar_backup"),
    path("backup/eliminar/<str:nombre_archivo>/", views.eliminar_copia_seguridad, name="eliminar_copia_seguridad"),
]