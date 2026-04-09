from django.urls import path
from . import views
from . import api_views 


app_name = "actas"

urlpatterns = [
    path("", views.actas_list, name="actas_list"),
    path("crear/", views.crear_acta, name="crear"),
    path("<int:acta_id>/", views.detalle_acta, name="detalle"),
    path("<int:acta_id>/editar/", views.editar_acta, name="editar"),
    path("<int:acta_id>/firmar/", views.firmar_acta, name="firmar"),
    path("<int:acta_id>/eliminar/", views.eliminar_acta, name="eliminar"),
    path("<int:acta_id>/pdf/", views.generar_pdf, name="pdf"),
    path("<int:acta_id>/enviar-revision/", views.enviar_revision, name="enviar_revision"),
    path("<int:acta_id>/finalizar/", views.finalizar_acta, name="finalizar"),
    path("<int:acta_id>/archivar/", views.archivar_acta, name="archivar"),
    path("firmas-pendientes/", views.firmas_pendientes, name="firmas_pendientes"),
    
    path("procesar-ia/", views.procesar_con_ia, name="procesar_ia"),

    # Rutas de compromisos
    path("<int:acta_id>/compromisos/", views.lista_compromisos, name="lista_compromisos"),
    path("compromisos/", views.mis_compromisos, name="mis_compromisos"),
    path("<int:acta_id>/compromisos/nuevo/", views.crear_compromiso, name="crear_compromiso"),
    path("compromisos/<int:compromiso_id>/editar/", views.editar_compromiso, name="editar_compromiso"),
    path("compromisos/<int:compromiso_id>/eliminar/", views.eliminar_compromiso, name="eliminar_compromiso"),

    # Rutas para aprendices
    path("aprendiz/pendientes/", views.aprendiz_pendientes, name="aprendiz_pendientes"),
    path("aprendiz/compromisos/", views.aprendiz_compromisos, name="aprendiz_compromisos"),
    
    # ============================================
    # API para app móvil (AGREGAR AL FINAL)
    # ============================================
    # Autenticación y registro
    path('api/auth/login/', api_views.login_api, name='api_login'),
    path('api/auth/logout/', api_views.logout_api, name='api_logout'),
    path('api/auth/register/', api_views.register_api, name='api_register'),
    path('api/auth/verificar-email/', api_views.verificar_codigo_api, name='api_verificar_email'),
    path('api/auth/reenviar-codigo/', api_views.reenviar_codigo_api, name='api_reenviar_codigo'),

    # Dashboard y perfil
    path('api/dashboard/', api_views.dashboard_api, name='api_dashboard'),
    path('api/actas/', api_views.actas_list_api, name='api_actas_list'),
    path('api/actas/<int:acta_id>/', api_views.acta_detalle_api, name='api_acta_detalle'),
    path("api/perfil/", api_views.perfil_api, name="api_perfil"), 
    path('api/cambiar-password/', api_views.cambiar_password_api, name='api_cambiar_password'),
    path('api/usuarios/', api_views.usuarios_list_api, name='api_usuarios_list'),
    path('api/actas/crear/', api_views.crear_acta_api, name='api_crear_acta'),
    path('api/actas/generar-ia/', api_views.generar_acta_ia_api, name='api_generar_ia'),
    path('api/firmas/firmar/', api_views.firmar_acta_api, name='api_firmar_acta'), 
    path('api/actas/<int:acta_id>/cambiar-estado/', api_views.cambiar_estado_acta_api, name='api_cambiar_estado'), 
    path('api/compromisos/crear/', api_views.crear_compromiso_api, name='api_crear_compromiso'),
    path('api/actas/<int:acta_id>/editar/', api_views.editar_acta_api, name='api_editar_acta'),
    path('api/actas/<int:acta_id>/pdf/', api_views.generar_pdf_api, name='api_generar_pdf'),
    path('api/compromisos/mis-compromisos/', api_views.mis_compromisos_api, name='api_mis_compromisos'),
    path('api/compromisos/<int:compromiso_id>/actualizar/', api_views.actualizar_compromiso_api, name='api_actualizar_compromiso'),
    path('api/actas/<int:acta_id>/aplicar-silencio/', api_views.aplicar_silencio_administrativo_api, name='api_aplicar_silencio'),
    path('api/perfil/actualizar-firma/', api_views.actualizar_firma_api, name='api_actualizar_firma'),
    path('api/auth/solicitar-codigo/', api_views.solicitar_codigo_recuperacion_api, name='api_solicitar_codigo'),
    path('api/auth/verificar-codigo/', api_views.verificar_codigo_recuperacion_api, name='api_verificar_codigo'),
    path('api/auth/resetear-password/', api_views.resetear_password_api, name='api_resetear_password'),
    path('api/auth/verificar-estado/', api_views.verificar_estado_api, name='api_verificar_estado'),

    # Aprobación de cuentas (admin)
    path('api/admin/cuentas-pendientes/', api_views.cuentas_pendientes_api, name='api_cuentas_pendientes'),
    path('api/admin/aprobar-cuenta/', api_views.aprobar_cuenta_api, name='api_aprobar_cuenta'),
    path('api/admin/rechazar-cuenta/', api_views.rechazar_cuenta_api, name='api_rechazar_cuenta'),
    path('api/firmas/pendientes/', api_views.firmas_pendientes_api, name='api_firmas_pendientes'),
    path('api/perfil/exportar-datos/', api_views.exportar_datos_usuario_api, name='api_exportar_datos'),
    path('api/perfil/importar-datos/', api_views.importar_datos_usuario_api, name='api_importar_datos'),
    path('api/perfil/confirmar-importacion/', api_views.confirmar_importacion_datos_api, name='api_confirmar_importacion'),
    path('api/admin/backups/', api_views.listar_backups_api, name='api_listar_backups'),
    path('api/admin/backups/crear/', api_views.crear_backup_api, name='api_crear_backup'),
    path('api/admin/backups/descargar/<str:filename>/', api_views.descargar_backup_api, name='api_descargar_backup'),
    path('api/admin/backups/restaurar/', api_views.restaurar_backup_api, name='api_restaurar_backup'),
    path('api/admin/backups/eliminar/<str:filename>/', api_views.eliminar_backup_api, name='api_eliminar_backup'),

    # Gestión de usuarios (admin)
    path('api/admin/usuarios/', api_views.admin_usuarios_list_api, name='api_admin_usuarios_list'),
    path('api/admin/usuarios/<int:user_id>/', api_views.admin_usuario_detalle_api, name='api_admin_usuario_detalle'),
    path('api/admin/usuarios/<int:user_id>/aprobar/', api_views.admin_aprobar_usuario_api, name='api_admin_aprobar_usuario'),
    path('api/admin/usuarios/<int:user_id>/activar/', api_views.admin_activar_usuario_api, name='api_admin_activar_usuario'),
    path('api/admin/usuarios/<int:user_id>/rol/', api_views.admin_cambiar_rol_api, name='api_admin_cambiar_rol'),
    path('api/admin/usuarios/<int:user_id>/eliminar/', api_views.admin_eliminar_usuario_api, name='api_admin_eliminar_usuario'),

    # Archivos adjuntos de actas
    path('api/actas/<int:acta_id>/adjuntar-archivo/', api_views.adjuntar_archivo_acta_api, name='api_adjuntar_archivo'),
    path('api/actas/<int:acta_id>/archivos/', api_views.listar_archivos_acta_api, name='api_listar_archivos'),
    path('api/adjuntos/<int:adjunto_id>/descargar/', api_views.descargar_archivo_adjunto_api, name='api_descargar_adjunto'),
    path('api/adjuntos/<int:adjunto_id>/', api_views.eliminar_archivo_adjunto_api, name='api_eliminar_adjunto'),

    # Anexos PDF de actas
    path('api/actas/<int:acta_id>/anexos/', api_views.anexos_acta_api, name='api_anexos_acta'),
    path('api/actas/<int:acta_id>/anexos/<int:anexo_id>/', api_views.eliminar_anexo_api, name='api_eliminar_anexo'),
    path('api/actas/<int:acta_id>/anexos/orden/', api_views.reordenar_anexos_api, name='api_reordenar_anexos'),

    # Participantes no registrados
    path('<int:acta_id>/nr/<int:nr_id>/reenviar/', views.reenviar_pdf_nr, name='reenviar_pdf_nr'),

    # Plantillas de acta (admin)
    path('plantillas/', views.plantillas_list, name='plantillas_list'),
    path('plantillas/crear/', views.plantilla_crear, name='plantilla_crear'),
    path('plantillas/<int:plantilla_id>/editar/', views.plantilla_editar, name='plantilla_editar'),
    path('plantillas/<int:plantilla_id>/eliminar/', views.plantilla_eliminar, name='plantilla_eliminar'),
    path('plantillas/guia/pdf/', views.guia_plantillas_pdf, name='guia_plantillas_pdf'),
    path('plantillas/guia/docx/', views.guia_plantillas_docx, name='guia_plantillas_docx'),

    # Revisión colaborativa - Vistas web (sesión Django)
    path('<int:acta_id>/web/enviar-revision/', views.web_enviar_a_revision, name='web_enviar_revision'),
    path('<int:acta_id>/web/aprobar/', views.web_aprobar_acta, name='web_aprobar_acta'),
    path('<int:acta_id>/web/rechazar/', views.web_rechazar_acta, name='web_rechazar_acta'),
    path('<int:acta_id>/web/cerrar/', views.web_cerrar_acta, name='web_cerrar_acta'),

    # Participantes no registrados (API móvil)
    path('api/actas/<int:acta_id>/participantes-nr/', api_views.participantes_nr_list_api, name='api_participantes_nr_list'),
    path('api/actas/<int:acta_id>/participantes-nr/<int:nr_id>/', api_views.participante_nr_detalle_api, name='api_participante_nr_detalle'),
    path('api/actas/<int:acta_id>/participantes-nr/<int:nr_id>/reenviar/', api_views.reenviar_pdf_nr_api, name='api_reenviar_pdf_nr'),

    # Revisión colaborativa de actas
    path('api/actas/<int:acta_id>/enviar-a-revision/', api_views.enviar_a_revision_api, name='api_enviar_a_revision'),
    path('api/actas/<int:acta_id>/aprobar/', api_views.aprobar_acta_api, name='api_aprobar_acta'),
    path('api/actas/<int:acta_id>/rechazar/', api_views.rechazar_acta_api, name='api_rechazar_acta'),
    path('api/actas/<int:acta_id>/cerrar/', api_views.cerrar_acta_api, name='api_cerrar_acta'),
    path('api/actas/<int:acta_id>/historial/', api_views.historial_acta_api, name='api_historial_acta'),
    path('api/actas/<int:acta_id>/participantes-estado/', api_views.participantes_estado_api, name='api_participantes_estado'),
]
