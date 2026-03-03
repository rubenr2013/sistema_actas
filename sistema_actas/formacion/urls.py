from django.urls import path
from . import api_views

urlpatterns = [
    # ── Programas ──────────────────────────────────────────────────────────────
    # GET  → lista programas activos
    # POST → crear programa (admin)
    path('api/programas/', api_views.programas_api, name='api_programas'),

    # GET    → detalle de un programa
    # PUT    → editar programa (admin)
    # DELETE → desactivar programa (admin)
    path('api/programas/<int:programa_id>/', api_views.programa_detalle_api, name='api_programa_detalle'),

    # ── Fichas ─────────────────────────────────────────────────────────────────
    # IMPORTANTE: 'buscar/' debe estar ANTES de '<int:ficha_id>/'
    # porque si no, Django intentaría convertir "buscar" a un número y fallaría
    path('api/fichas/buscar/', api_views.buscar_ficha_api, name='api_buscar_ficha'),

    # GET  → lista fichas activas (con filtro ?programa=<id>)
    # POST → crear ficha (admin)
    path('api/fichas/', api_views.fichas_api, name='api_fichas'),

    # GET    → detalle de una ficha
    # PUT    → editar ficha (admin)
    # DELETE → desactivar ficha (admin)
    path('api/fichas/<int:ficha_id>/', api_views.ficha_detalle_api, name='api_ficha_detalle'),
]
