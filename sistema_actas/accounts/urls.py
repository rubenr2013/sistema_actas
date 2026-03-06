# accounts/urls.py

from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

# Define el namespace (espacio de nombres) para esta aplicación. CRÍTICO.
app_name = "accounts"

urlpatterns = [
    # ==========================================================
    # VISTAS PERSONALIZADAS
    # ==========================================================
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("verificar-email/<str:email>/", views.verificar_email_view, name="verificar_email"),
    path("reenviar-codigo/<str:email>/", views.reenviar_codigo_view, name="reenviar_codigo"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("settings/", views.settings_view, name="settings"),
    
    path("usuarios/", views.usuarios, name="usuarios"),
    path('usuarios/editar/<int:user_id>/', views.editar_usuario, name='editar_usuario'),
    path('usuarios/eliminar/<int:user_id>/', views.eliminar_usuario, name='eliminar_usuario'),

    # ── Sistema de aprobación de cuentas ───────────────────────────────────
    # Página informativa cuando la cuenta no está activa (sin login requerido)
    path("cuenta-pendiente/", views.cuenta_pendiente_view, name="cuenta_pendiente"),

    # Panel de admin: lista de cuentas pendientes
    path("cuentas-pendientes/", views.cuentas_pendientes_view, name="cuentas_pendientes"),

    # Acciones de aprobación / rechazo (POST desde el panel)
    path("aprobar-cuenta/<int:user_id>/", views.aprobar_cuenta_view, name="aprobar_cuenta"),
    path("rechazar-cuenta/<int:user_id>/", views.rechazar_cuenta_view, name="rechazar_cuenta"),
    
    # ==========================================================
    # FLUJO DE RECUPERACIÓN DE CONTRASEÑA (CORREGIDO)
    # ==========================================================
    
    # 1. Formulario de Solicitud de Correo: /accounts/password_reset/
    # Incluye 'email_template_name' para usar una plantilla personalizada que soluciona el NoReverseMatch.
    path('password_reset/',
        auth_views.PasswordResetView.as_view(
            template_name='accounts/password_reset_form.html',
            success_url=reverse_lazy('accounts:password_reset_done'), # Redirección a la vista Done con namespace
            email_template_name='accounts/password_reset_email.html'  # <-- CORRECCIÓN CRÍTICA
        ),
        name='password_reset'),

    # 2. Confirmación de Envío: /accounts/password_reset/done/
    path("password_reset/done/", 
        auth_views.PasswordResetDoneView.as_view(
            template_name='accounts/password_reset_done.html'
        ), 
        name="password_reset_done"),

    # 3. Formulario para la Nueva Contraseña (usa uidb64 y token de la URL)
    # Ruta: /accounts/reset/<uidb64>/<token>/
    path("reset/<uidb64>/<token>/", 
        auth_views.PasswordResetConfirmView.as_view(
            template_name='accounts/password_reset_confirm.html',
            success_url=reverse_lazy('accounts:password_reset_complete') # Redirección a la vista Complete con namespace
        ), 
        name="password_reset_confirm"),

    # 4. Éxito Final: /accounts/reset/done/
    path("reset/done/", 
        auth_views.PasswordResetCompleteView.as_view(
            template_name='accounts/password_reset_complete.html'
        ), 
        name="password_reset_complete"),
]