from django.urls import path
from . import api_views, views

app_name = 'formacion'

urlpatterns = [
    # ── Vistas Web (admin) ─────────────────────────────────────────────────
    path('programas/', views.programas_list, name='programas_list'),
    path('programas/<int:programa_id>/editar/', views.editar_programa, name='editar_programa'),
    path('programas/<int:programa_id>/eliminar/', views.eliminar_programa, name='eliminar_programa'),

    path('fichas/', views.fichas_list, name='fichas_list'),
    path('fichas/<int:ficha_id>/editar/', views.editar_ficha, name='editar_ficha'),
    path('fichas/<int:ficha_id>/eliminar/', views.eliminar_ficha, name='eliminar_ficha'),


    # ── Programas ──────────────────────────────────────────────────────────────
    # GET  → lista programas activos
    # POST → crear programa (admin)
    path('api/programas/', api_views.programas_api, name='api_programas'),

    # GET    → detalle de un programa
    # PUT    → editar programa (admin)
    # DELETE → desactivar programa (admin)
    path('api/programas/<int:programa_id>/', api_views.programa_detalle_api, name='api_programa_detalle'),

    # ── Fichas ─────────────────────────────────────────────────────────────────
    # IMPORTANTE: las rutas con palabras ('activas/', 'buscar/') deben ir ANTES
    # de '<int:ficha_id>/' porque Django lee las URLs de arriba a abajo.
    # Si '<int:ficha_id>/' estuviera primero, intentaría convertir "activas" a número y fallaría.

    # Público: lista para el formulario de registro de la app móvil
    path('api/fichas/activas/', api_views.fichas_activas_api, name='api_fichas_activas'),

    path('api/fichas/buscar/', api_views.buscar_ficha_api, name='api_buscar_ficha'),

    # GET  → lista fichas activas (con filtro ?programa=<id>)
    # POST → crear ficha (admin)
    path('api/fichas/', api_views.fichas_api, name='api_fichas'),

    # GET    → detalle de una ficha
    # PUT    → editar ficha (admin)
    # DELETE → desactivar ficha (admin)
    path('api/fichas/<int:ficha_id>/', api_views.ficha_detalle_api, name='api_ficha_detalle'),
]
