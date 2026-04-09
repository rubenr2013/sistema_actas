"""
Servicio de envío de emails para el sistema de gestión de actas SENA
Funciones helper para cada tipo de notificación
"""

from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging
from datetime import datetime, date
from django.utils import timezone

logger = logging.getLogger('actas.email_service')


def get_site_url():
    """Retorna la URL base del sitio con el protocolo correcto."""
    domain = getattr(settings, 'SITE_DOMAIN', '127.0.0.1:8000')
    is_production = '127.0.0.1' not in domain and 'localhost' not in domain
    protocol = 'https' if is_production else 'http'
    return f'{protocol}://{domain}'


def format_datetime_safe(value, format_str='%d/%m/%Y %H:%M'):
    """
    Formatea un datetime/date o string de forma segura.
    Retorna string formateado o el valor original si falla.
    """
    if value is None:
        return 'No especificado'

    if isinstance(value, datetime):
        try:
            return value.strftime(format_str)
        except Exception:
            return str(value)

    if isinstance(value, date):
        try:
            if '%H' in format_str or '%M' in format_str:
                format_str = '%d/%m/%Y'
            return value.strftime(format_str)
        except Exception:
            return str(value)

    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            return dt.strftime(format_str)
        except Exception:
            try:
                d = datetime.strptime(value, '%Y-%m-%d').date()
                if '%H' in format_str or '%M' in format_str:
                    format_str = '%d/%m/%Y'
                return d.strftime(format_str)
            except Exception:
                return value

    return str(value)


def enviar_email_compromiso_asignado(compromiso, usuario_asignado):
    """
    Envía email cuando se asigna un compromiso a un usuario.
    Retorna True si el email se envió correctamente, False en caso contrario.
    """
    try:
        if not usuario_asignado.email:
            logger.warning('Usuario %s no tiene email configurado', usuario_asignado.username)
            return False

        logger.info('Preparando email de compromiso para: %s', usuario_asignado.email)

        contexto = {
            'nombre_usuario': usuario_asignado.get_full_name() or usuario_asignado.username,
            'titulo_compromiso': compromiso.descripcion,
            'descripcion': compromiso.descripcion,
            'fecha_vencimiento': format_datetime_safe(compromiso.fecha_limite, '%d/%m/%Y') if compromiso.fecha_limite else 'No definida',
            'creador': compromiso.acta.creador.get_full_name() if compromiso.acta else 'Sistema',
            'enlace_compromiso': f'{get_site_url()}/actas/{compromiso.acta.id}/compromisos/',
        }

        html_message = render_to_string('emails/compromiso_asignado.html', contexto)

        send_mail(
            subject=f'Nuevo Compromiso Asignado: {compromiso.descripcion[:50]}...',
            message=f'Hola {contexto["nombre_usuario"]},\n\nSe te ha asignado un nuevo compromiso: {compromiso.descripcion}\n\nFecha de vencimiento: {contexto["fecha_vencimiento"]}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario_asignado.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info('Email de compromiso asignado enviado a %s (Compromiso ID: %s)', usuario_asignado.email, compromiso.id)
        return True

    except Exception as e:
        logger.error('Error al enviar email de compromiso asignado a %s: %s', usuario_asignado.email, str(e), exc_info=True)
        return False


def enviar_email_solicitud_firma(acta, usuario):
    """
    Envía email cuando se requiere la firma de un usuario en un acta.
    Retorna True si el email se envió correctamente, False en caso contrario.
    """
    try:
        if not usuario.email:
            logger.warning('Usuario %s no tiene email configurado', usuario.username)
            return False

        logger.info('Preparando email de solicitud de firma para: %s', usuario.email)

        contexto = {
            'nombre_usuario': usuario.get_full_name() or usuario.username,
            'titulo_acta': acta.titulo,
            'fecha_reunion': format_datetime_safe(acta.fecha_reunion, '%d/%m/%Y %H:%M'),
            'lugar': acta.lugar_reunion or 'No especificado',
            'creador': acta.creador.get_full_name() or acta.creador.username,
            'resumen': strip_tags(acta.desarrollo)[:300] + '...' if len(strip_tags(acta.desarrollo)) > 300 else strip_tags(acta.desarrollo),
            'enlace_acta': f'{get_site_url()}/actas/{acta.id}/',
        }

        html_message = render_to_string('emails/solicitud_firma.html', contexto)

        send_mail(
            subject=f'Solicitud de Firma: {acta.titulo}',
            message=f'Hola {contexto["nombre_usuario"]},\n\nSe requiere tu firma en el acta: {acta.titulo}\n\nFecha de reunion: {contexto["fecha_reunion"]}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info('Email de solicitud de firma enviado a %s (Acta ID: %s)', usuario.email, acta.id)
        return True

    except Exception as e:
        logger.error('Error al enviar email de solicitud de firma a %s: %s', usuario.email, str(e), exc_info=True)
        return False


def enviar_email_acta_firmada_completa(acta):
    """
    Envía email al creador del acta cuando todos los participantes han firmado.
    Retorna True si el email se envió correctamente, False en caso contrario.
    """
    try:
        if not acta.creador.email:
            logger.warning('Creador del acta %s no tiene email configurado', acta.id)
            return False

        from .models import Participante, Firma
        total_participantes = Participante.objects.filter(acta=acta).count()
        total_firmas = Firma.objects.filter(acta=acta).count()

        contexto = {
            'nombre_usuario': acta.creador.get_full_name() or acta.creador.username,
            'titulo_acta': acta.titulo,
            'fecha_reunion': format_datetime_safe(acta.fecha_reunion, '%d/%m/%Y %H:%M'),
            'total_participantes': total_participantes,
            'total_firmas': total_firmas,
            'enlace_acta': f'{get_site_url()}/actas/{acta.id}/',
        }

        html_message = render_to_string('emails/acta_firmada_completa.html', contexto)

        send_mail(
            subject=f'Acta Completamente Firmada: {acta.titulo}',
            message=f'Hola {contexto["nombre_usuario"]},\n\nEl acta "{acta.titulo}" ha sido firmada por todos los participantes ({total_firmas}/{total_participantes}).',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[acta.creador.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info('Email de acta firmada completa enviado a %s (Acta ID: %s)', acta.creador.email, acta.id)
        return True

    except Exception as e:
        logger.error('Error al enviar email de acta firmada completa: %s', str(e), exc_info=True)
        return False

def enviar_pdf_participante_no_registrado(participante_nr, pdf_bytes):
    """
    Envía el PDF del acta a un participante no registrado.
    Retorna True si se envió correctamente, False si falló.
    """
    from django.core.mail import EmailMessage
    from django.utils import timezone as tz

    acta = participante_nr.acta
    try:
        contexto = {
            'nombre_completo': participante_nr.nombre_completo,
            'numero_acta': acta.numero_acta,
            'titulo_acta': acta.titulo,
            'tipo_reunion': acta.get_tipo_reunion_label() if hasattr(acta, 'get_tipo_reunion_label') else acta.get_tipo_reunion_display(),
            'fecha_reunion': format_datetime_safe(acta.fecha_reunion),
            'lugar': getattr(acta, 'lugar_reunion', '') or '—',
            'cargo_rol': participante_nr.cargo_rol or '',
        }

        html_body = render_to_string('emails/acta_participante_no_registrado.html', contexto)
        text_body = strip_tags(html_body)

        asunto = f"Acta de reunión SENA – {acta.titulo} ({acta.numero_acta})"

        msg = EmailMessage(
            subject=asunto,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[participante_nr.email],
        )
        msg.content_subtype = 'plain'
        msg.attach_alternative(html_body, 'text/html')

        nombre_pdf = f"Acta_{acta.numero_acta}.pdf"
        msg.attach(nombre_pdf, pdf_bytes, 'application/pdf')

        msg.send(fail_silently=False)

        participante_nr.pdf_enviado = True
        participante_nr.fecha_envio = tz.now()
        participante_nr.email_rebotado = False
        participante_nr.save(update_fields=['pdf_enviado', 'fecha_envio', 'email_rebotado'])

        logger.info('PDF enviado a participante no registrado %s (Acta %s)', participante_nr.email, acta.numero_acta)
        return True

    except Exception as e:
        participante_nr.email_rebotado = True
        participante_nr.save(update_fields=['email_rebotado'])
        logger.error('Error enviando PDF a %s (Acta %s): %s', participante_nr.email, acta.numero_acta, e, exc_info=True)
        return False


def enviar_pdfs_a_no_registrados(acta):
    """
    Genera el PDF del acta y lo envía a todos los participantes no registrados
    que aún no lo han recibido. Llamar al finalizar el acta.
    Retorna (enviados, fallidos).
    """
    import io as _io
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet

    pendientes = acta.participantes_no_registrados.filter(pdf_enviado=False)
    if not pendientes.exists():
        return 0, 0

    # Generar PDF usando el servicio de plantilla o ReportLab
    pdf_bytes = None
    try:
        from actas.services.plantilla_service import generar_documento_desde_plantilla
        resultado = generar_documento_desde_plantilla(acta)
        if resultado and resultado['tipo'] == 'pdf':
            pdf_bytes = resultado['bytes']
    except Exception as e:
        logger.warning('enviar_pdfs_a_no_registrados: no se pudo usar plantilla: %s', e)

    if not pdf_bytes:
        # Fallback: generar PDF básico con ReportLab
        try:
            from actas.views import _generar_pdf_bytes
            pdf_bytes = _generar_pdf_bytes(acta)
        except Exception as e:
            logger.error('enviar_pdfs_a_no_registrados: no se pudo generar PDF: %s', e)
            return 0, pendientes.count()

    enviados, fallidos = 0, 0
    for participante in pendientes:
        if enviar_pdf_participante_no_registrado(participante, pdf_bytes):
            enviados += 1
        else:
            fallidos += 1

    logger.info('PDFs a no registrados — Acta %s: %d enviados, %d fallidos', acta.numero_acta, enviados, fallidos)
    return enviados, fallidos
