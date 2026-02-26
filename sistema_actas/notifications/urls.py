from django.urls import path
from . import views, api_views

app_name = "notifications"

urlpatterns = [
    # ========================================
    # VISTAS WEB (Django Template Views)
    # ========================================
    
    # Listado de notificaciones
    path("", views.notifications_list, name="list"),

    # Redirección inteligente: marca como leída y verifica que el recurso exista
    path("go/<int:notification_id>/", views.notification_redirect, name="go"),

    # Marcar como leídas (varias o todas)
    path("mark-as-read/", views.mark_as_read, name="mark_as_read"),

    # Marcar como no leída (una sola)
    path("mark-as-unread/<int:notification_id>/", views.mark_as_unread, name="mark_as_unread"),

    # Eliminar notificación
    path("delete/<int:notification_id>/", views.delete_notification, name="delete"),

    # Configuración de notificaciones
    path("settings/", views.notification_settings, name="settings"),
    
    # ========================================
    # API ENDPOINTS (Para Flutter/Móvil)
    # ========================================
    
    # Listar notificaciones del usuario
    path("api/", api_views.notificaciones_api, name="api_list"),
    
    # Contar notificaciones no leídas
    path("api/count/", api_views.contar_no_leidas_api, name="api_count"),
    
    # Marcar una notificación como leída
    path("api/<int:notificacion_id>/marcar-leida/", api_views.marcar_leida_api, name="api_mark_read"),
    
    # Marcar todas las notificaciones como leídas
    path("api/marcar-todas-leidas/", api_views.marcar_todas_leidas_api, name="api_mark_all_read"),
    
    # Eliminar una notificación
    path("api/<int:notificacion_id>/eliminar/", api_views.eliminar_notificacion_api, name="api_delete"),
]