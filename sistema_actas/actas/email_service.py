"""
Servicio de envío de emails para el sistema de gestión de actas SENA
Funciones helper para cada tipo de notificación
"""

from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
import logging
from datetime import datetime, date
from django.utils import timezone

logger = logging.getLogger('actas.email_service')


def format_datetime_safe(value, format_str='%d/%m/%Y %H:%M'):
    """
    Formatea un datetime/date o string de forma segura

    Args:
        value: datetime, date o string ISO
        format_str: formato de salida

    Returns:
        string formateado o el valor original si falla
    """
    if value is None:
        return 'No especificado'

    # Si ya es datetime o date, formatear directamente
    if isinstance(value, datetime):
        try:
            return value.strftime(format_str)
        except:
            return str(value)

    if isinstance(value, date):
        try:
            # Para dates, usar formato sin hora
            if '%H' in format_str or '%M' in format_str:
                format_str = '%d/%m/%Y'
            return value.strftime(format_str)
        except:
            return str(value)

    # Si es string, intentar parsearlo
    if isinstance(value, str):
        try:
            # Intentar parsear como ISO datetime
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            return dt.strftime(format_str)
        except:
            try:
                # Intentar parsear como fecha YYYY-MM-DD
                d = datetime.strptime(value, '%Y-%m-%d').date()
                if '%H' in format_str or '%M' in format_str:
                    format_str = '%d/%m/%Y'
                return d.strftime(format_str)
            except:
                # Si falla todo, devolver el string original
                return value

    # Fallback: convertir a string
    return str(value)


def enviar_email_compromiso_asignado(compromiso, usuario_asignado):
    """
    Envía email cuando se asigna un compromiso a un usuario

    Args:
        compromiso: Instancia del modelo Compromiso
        usuario_asignado: Instancia del modelo User

    Returns:
        bool: True si el email se envió correctamente, False en caso contrario
    """
    try:
        # Validar que el usuario tenga email
        if not usuario_asignado.email:
            logger.warning(f'Usuario {usuario_asignado.username} no tiene email configurado')
            print(f"⚠️ Usuario {usuario_asignado.username} no tiene email configurado")
            return False

        print(f"📧 Preparando email de compromiso para: {usuario_asignado.email}")

        # Preparar contexto para el template
        contexto = {
            'nombre_usuario': usuario_asignado.get_full_name() or usuario_asignado.username,
            'titulo_compromiso': compromiso.descripcion,
            'descripcion': compromiso.descripcion,
            'fecha_vencimiento': format_datetime_safe(compromiso.fecha_limite, '%d/%m/%Y') if compromiso.fecha_limite else 'No definida',
            'creador': compromiso.acta.creador.get_full_name() if compromiso.acta else 'Sistema',
            'enlace_compromiso': f'http://{settings.SITE_DOMAIN}/compromisos/{compromiso.id}/' if hasattr(settings, 'SITE_DOMAIN') else '#',
        }
        print(f"✓ Contexto preparado para el template")

        # Renderizar template HTML
        print(f"🎨 Renderizando template HTML...")
        html_message = render_to_string('emails/compromiso_asignado.html', contexto)
        print(f"✓ Template renderizado exitosamente ({len(html_message)} caracteres)")

        # Enviar email
        print(f"📤 Enviando email a {usuario_asignado.email}...")
        send_mail(
            subject=f'🔔 Nuevo Compromiso Asignado: {compromiso.descripcion[:50]}...',
            message=f'Hola {contexto["nombre_usuario"]},\n\nSe te ha asignado un nuevo compromiso: {compromiso.descripcion}\n\nFecha de vencimiento: {contexto["fecha_vencimiento"]}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario_asignado.email],
            html_message=html_message,
            fail_silently=False,
        )
        print(f"✓ Email enviado exitosamente a {usuario_asignado.email}")

        logger.info(f'Email de compromiso asignado enviado a {usuario_asignado.email} (Compromiso ID: {compromiso.id})')
        return True

    except Exception as e:
        logger.error(f'Error al enviar email de compromiso asignado: {str(e)}', exc_info=True)
        print(f"❌ ERROR al enviar email de compromiso:")
        print(f"   Tipo: {type(e).__name__}")
        print(f"   Mensaje: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def enviar_email_solicitud_firma(acta, usuario):
    """
    Envía email cuando se requiere la firma de un usuario en un acta

    Args:
        acta: Instancia del modelo Acta
        usuario: Instancia del modelo User que debe firmar

    Returns:
        bool: True si el email se envió correctamente, False en caso contrario
    """
    try:
        # Validar que el usuario tenga email
        if not usuario.email:
            logger.warning(f'Usuario {usuario.username} no tiene email configurado')
            print(f"⚠️ Usuario {usuario.username} no tiene email configurado")
            return False

        print(f"📧 Preparando email de solicitud de firma para: {usuario.email}")

        # Preparar contexto para el template
        contexto = {
            'nombre_usuario': usuario.get_full_name() or usuario.username,
            'titulo_acta': acta.titulo,
            'fecha_reunion': format_datetime_safe(acta.fecha_reunion, '%d/%m/%Y %H:%M'),
            'lugar': acta.lugar_reunion or 'No especificado',
            'creador': acta.creador.get_full_name() or acta.creador.username,
            'resumen': acta.desarrollo[:200] + '...' if len(acta.desarrollo) > 200 else acta.desarrollo,
            'enlace_acta': f'http://{settings.SITE_DOMAIN}/actas/{acta.id}/' if hasattr(settings, 'SITE_DOMAIN') else '#',
        }
        print(f"✓ Contexto preparado para el template")

        # Renderizar template HTML
        print(f"🎨 Renderizando template HTML...")
        html_message = render_to_string('emails/solicitud_firma.html', contexto)
        print(f"✓ Template renderizado exitosamente ({len(html_message)} caracteres)")

        # Enviar email
        print(f"📤 Enviando email a {usuario.email}...")
        send_mail(
            subject=f'✍️ Solicitud de Firma: {acta.titulo}',
            message=f'Hola {contexto["nombre_usuario"]},\n\nSe requiere tu firma en el acta: {acta.titulo}\n\nFecha de reunión: {contexto["fecha_reunion"]}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario.email],
            html_message=html_message,
            fail_silently=False,
        )
        print(f"✓ Email enviado exitosamente a {usuario.email}")

        logger.info(f'Email de solicitud de firma enviado a {usuario.email} (Acta ID: {acta.id})')
        return True

    except Exception as e:
        logger.error(f'Error al enviar email de solicitud de firma: {str(e)}', exc_info=True)
        print(f"❌ ERROR al enviar email de solicitud de firma:")
        print(f"   Tipo: {type(e).__name__}")
        print(f"   Mensaje: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def enviar_email_acta_firmada_completa(acta):
    """
    Envía email al creador del acta cuando todos los participantes han firmado

    Args:
        acta: Instancia del modelo Acta

    Returns:
        bool: True si el email se envió correctamente, False en caso contrario
    """
    try:
        # Validar que el creador tenga email
        if not acta.creador.email:
            logger.warning(f'Creador del acta {acta.id} no tiene email configurado')
            return False

        # Contar firmas y participantes
        from .models import Participante, Firma
        total_participantes = Participante.objects.filter(acta=acta).count()
        total_firmas = Firma.objects.filter(acta=acta).count()

        # Preparar contexto para el template
        contexto = {
            'nombre_usuario': acta.creador.get_full_name() or acta.creador.username,
            'titulo_acta': acta.titulo,
            'fecha_reunion': format_datetime_safe(acta.fecha_reunion, '%d/%m/%Y %H:%M'),
            'total_participantes': total_participantes,
            'total_firmas': total_firmas,
            'enlace_acta': f'http://{settings.SITE_DOMAIN}/actas/{acta.id}/' if hasattr(settings, 'SITE_DOMAIN') else '#',
        }

        # Renderizar template HTML
        html_message = render_to_string('emails/acta_firmada_completa.html', contexto)

        # Enviar email
        send_mail(
            subject=f'✅ Acta Completamente Firmada: {acta.titulo}',
            message=f'Hola {contexto["nombre_usuario"]},\n\n¡Excelente noticia! El acta "{acta.titulo}" ha sido firmada por todos los participantes ({total_firmas}/{total_participantes}).',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[acta.creador.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f'Email de acta firmada completa enviado a {acta.creador.email} (Acta ID: {acta.id})')
        return True

    except Exception as e:
        logger.error(f'Error al enviar email de acta firmada completa: {str(e)}', exc_info=True)
        return False


def enviar_email_recordatorio_compromiso(compromiso):
    """
    Envía email de recordatorio cuando un compromiso está próximo a vencer

    Args:
        compromiso: Instancia del modelo Compromiso

    Returns:
        bool: True si el email se envió correctamente, False en caso contrario
    """
    try:
        # Validar que el responsable tenga email
        if not compromiso.responsable or not compromiso.responsable.email:
            logger.warning(f'Compromiso {compromiso.id} no tiene responsable con email configurado')
            return False

        # Calcular tiempo restante
        from datetime import timedelta
        if compromiso.fecha_limite:
            dias_restantes = (compromiso.fecha_limite - datetime.now().date()).days
            if dias_restantes == 0:
                tiempo_restante = '¡Vence hoy!'
            elif dias_restantes == 1:
                tiempo_restante = 'Vence mañana'
            else:
                tiempo_restante = f'{dias_restantes} días'
        else:
            tiempo_restante = 'No definida'

        # Preparar contexto para el template
        contexto = {
            'nombre_usuario': compromiso.responsable.get_full_name() or compromiso.responsable.username,
            'titulo_compromiso': compromiso.descripcion,
            'descripcion': compromiso.descripcion,
            'fecha_vencimiento': format_datetime_safe(compromiso.fecha_limite, '%d/%m/%Y') if compromiso.fecha_limite else 'No definida',
            'tiempo_restante': tiempo_restante,
            'estado': compromiso.get_estado_display() if hasattr(compromiso, 'get_estado_display') else compromiso.estado,
            'enlace_compromiso': f'http://{settings.SITE_DOMAIN}/compromisos/{compromiso.id}/' if hasattr(settings, 'SITE_DOMAIN') else '#',
        }

        # Renderizar template HTML
        html_message = render_to_string('emails/recordatorio_compromiso.html', contexto)

        # Enviar email
        send_mail(
            subject=f'⏰ Recordatorio: Compromiso próximo a vencer - {compromiso.descripcion[:50]}...',
            message=f'Hola {contexto["nombre_usuario"]},\n\nRecordatorio: Tu compromiso "{compromiso.descripcion}" vence en {tiempo_restante}.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[compromiso.responsable.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f'Email de recordatorio enviado a {compromiso.responsable.email} (Compromiso ID: {compromiso.id})')
        return True

    except Exception as e:
        logger.error(f'Error al enviar email de recordatorio: {str(e)}', exc_info=True)
        return False


def enviar_email_compromiso_actualizado(compromiso, estado_anterior, actualizador):
    """
    Envía email cuando se actualiza el estado de un compromiso

    Args:
        compromiso: Instancia del modelo Compromiso
        estado_anterior: str con el estado anterior del compromiso
        actualizador: Instancia del modelo User que realizó la actualización

    Returns:
        bool: True si el email se envió correctamente, False en caso contrario
    """
    try:
        # Validar que el responsable tenga email
        if not compromiso.responsable or not compromiso.responsable.email:
            logger.warning(f'Compromiso {compromiso.id} no tiene responsable con email configurado')
            return False

        # Preparar mensaje adicional según el cambio de estado
        estado_nuevo = compromiso.get_estado_display() if hasattr(compromiso, 'get_estado_display') else compromiso.estado

        if 'completado' in estado_nuevo.lower() or 'cumplido' in estado_nuevo.lower():
            mensaje_adicional = '<p style="color: #28a745; font-weight: bold;">¡Felicitaciones! El compromiso ha sido marcado como completado.</p>'
        elif 'pendiente' in estado_nuevo.lower():
            mensaje_adicional = '<p>El compromiso ha vuelto al estado pendiente. Por favor, revisa los detalles.</p>'
        else:
            mensaje_adicional = '<p>El estado del compromiso ha cambiado. Por favor, revisa los detalles.</p>'

        # Preparar contexto para el template
        contexto = {
            'nombre_usuario': compromiso.responsable.get_full_name() or compromiso.responsable.username,
            'titulo_compromiso': compromiso.descripcion,
            'descripcion': compromiso.descripcion,
            'estado_anterior': estado_anterior,
            'estado_nuevo': estado_nuevo,
            'fecha_vencimiento': format_datetime_safe(compromiso.fecha_limite, '%d/%m/%Y') if compromiso.fecha_limite else 'No definida',
            'actualizador': actualizador.get_full_name() or actualizador.username,
            'mensaje_adicional': mensaje_adicional,
            'enlace_compromiso': f'http://{settings.SITE_DOMAIN}/compromisos/{compromiso.id}/' if hasattr(settings, 'SITE_DOMAIN') else '#',
        }

        # Renderizar template HTML
        html_message = render_to_string('emails/compromiso_actualizado.html', contexto)

        # Enviar email
        send_mail(
            subject=f'📊 Compromiso Actualizado: {compromiso.descripcion[:50]}...',
            message=f'Hola {contexto["nombre_usuario"]},\n\nEl compromiso "{compromiso.descripcion}" ha sido actualizado.\n\nEstado anterior: {estado_anterior}\nEstado nuevo: {estado_nuevo}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[compromiso.responsable.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f'Email de compromiso actualizado enviado a {compromiso.responsable.email} (Compromiso ID: {compromiso.id})')
        return True

    except Exception as e:
        logger.error(f'Error al enviar email de compromiso actualizado: {str(e)}', exc_info=True)
        return False


def enviar_email_nuevo_comentario(acta, comentario, autor):
    """
    Envía email a los participantes de un acta cuando se agrega un nuevo comentario

    Args:
        acta: Instancia del modelo Acta
        comentario: str con el texto del comentario
        autor: Instancia del modelo User que escribió el comentario

    Returns:
        int: Número de emails enviados exitosamente
    """
    try:
        from .models import Participante

        # Obtener todos los participantes del acta (excepto el autor del comentario)
        participantes = Participante.objects.filter(acta=acta).exclude(usuario=autor)

        emails_enviados = 0

        for participante in participantes:
            try:
                # Validar que el participante tenga email
                if not participante.usuario.email:
                    logger.warning(f'Participante {participante.usuario.username} no tiene email configurado')
                    continue

                # Preparar contexto para el template
                contexto = {
                    'nombre_usuario': participante.usuario.get_full_name() or participante.usuario.username,
                    'titulo_acta': acta.titulo,
                    'fecha_reunion': format_datetime_safe(acta.fecha_reunion, '%d/%m/%Y %H:%M'),
                    'autor_comentario': autor.get_full_name() or autor.username,
                    'comentario': comentario[:300] + '...' if len(comentario) > 300 else comentario,
                    'fecha_comentario': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'enlace_acta': f'http://{settings.SITE_DOMAIN}/actas/{acta.id}/' if hasattr(settings, 'SITE_DOMAIN') else '#',
                }

                # Renderizar template HTML
                html_message = render_to_string('emails/nuevo_comentario.html', contexto)

                # Enviar email
                send_mail(
                    subject=f'💬 Nuevo Comentario en: {acta.titulo}',
                    message=f'Hola {contexto["nombre_usuario"]},\n\n{contexto["autor_comentario"]} ha comentado en el acta "{acta.titulo}":\n\n"{comentario[:200]}..."',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[participante.usuario.email],
                    html_message=html_message,
                    fail_silently=False,
                )

                logger.info(f'Email de nuevo comentario enviado a {participante.usuario.email} (Acta ID: {acta.id})')
                emails_enviados += 1

            except Exception as e:
                logger.error(f'Error al enviar email a {participante.usuario.email}: {str(e)}')
                continue

        logger.info(f'Total de emails de nuevo comentario enviados: {emails_enviados} (Acta ID: {acta.id})')
        return emails_enviados

    except Exception as e:
        logger.error(f'Error al enviar emails de nuevo comentario: {str(e)}', exc_info=True)
        return 0
