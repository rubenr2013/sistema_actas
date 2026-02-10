import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sistema_actas.settings')
app = Celery('sistema_actas')
app.config_from_object('django.conf:settings', namespace='CELERY')

#configuracion de beat schedule para tareas periodicas

app. conf.beat_schedule = {
    'verificar-silencio-administrativo': {
        'task':'actas.tasks.verificar_silencio_administrativo',
        'schedule': 3600.0, #cada hora
    },
    'notificar-compromisos-proximos': {
        'task': 'actas.tasks.notificar_compromisos_proximos',
        'schedule': 86400.0, #cada dia
    }, 
    'marcar-compromisos-vencidos': {
        'task': 'actas.tasks.marcar_compromisos_vencidos',
        'schedule': 3600.0, #cada hora
    },
    'limpiar-notificaciones-antiguas':{
        'task': 'notifications.tasks.limpiar_notificaciones_antiguas',
        'schedule': 604800.0, #cada semana
    }
}

app.conf.timezone = 'America/Bogota'

app.autodiscover_tasks()