from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'api'

router = DefaultRouter()
router.register(r'actas', views.ActaViewSet)
router.register(r'compromisos', views.CompromisoViewSet)
router.register(r'notifications', views.NotificationViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/stats/', views.dashboard_stats, name='dashboard_stats'),
    path('actas/<int:acta_id>/firmas/', views.acta_firmas_status, name='acta_firmas'),
    path('users/search/', views.search_users, name='search_users'),
    path('export/actas/', views.export_actas, name='export_actas'),
]