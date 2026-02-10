from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from celery import shared_task

from .models import Notification, NotificationSettings

def crear_notificacion(usuario, tipo, titulo, mensaje, enlace='', metadata=None):
    """funcion helper para crear notificaciones"""
    try:
        user_settings = usuario.notification_settings
        if not user_settings.app_todas_notificaciones:
            return None
    except NotificationSettings.DoesNotExist:
        NotificationSettings.objects.create(usuario=usuario)
        
    notification = Notification.objects.create(
        usuario=usuario,
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        enlace=enlace,
        metadata=metadata or {}
    )
    if should_send_email_notification(usuario, tipo):
        enviar_email_notificacion.delay(notification.id)
        
    return notification


def should_send_email_notification(usuario, tipo):
    """determina si se debe enviar una notificacion por email"""
    try: 
        user_settings = usuario.notification_settings
        email_map = {
            'firma_pendiente': user_settings.email_firma_pendiente,
            'compromiso_vencido': user_settings.email_compromiso_vencido,
            'nueva_acta': user_settings.email_nueva_acta,
        }
        return email_map.get(tipo, False)
    except NotificationSettings.DoesNotExist:
        return False
    

@shared_task
def enviar_email_notificacion(notification_id):
    """tarea celery para enviar notificaciones por email"""
    try: 
        notification = Notification.objects.get(id=notification_id)
        subject = f"[Sistema de Actas SENA] {notification.titulo}"
        
        html_message = render_to_string('notifications/email_notification.html', {
            'notification': notification,
            'usuario': notification.usuario,
        })
        
        send_mail(
            subject=subject,
            message=notification.mensaje,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[notification.usuario.email],
            html_message=html_message,
            fail_silently=False,
        )
        return f"Email enviado a {notification.usuario.email}"
    
    except Notification.DoesNotExist:
        return "Notificación no encontrada"
    except Exception as e:
        return f"Error al enviar email: {str(e)}"
