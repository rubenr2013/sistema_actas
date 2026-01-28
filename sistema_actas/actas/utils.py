"""
Utilidades para el módulo de actas
Incluye funciones para detección de roles, generación de códigos, envío de emails y sanitización
"""

import random
import string
import re
import html
import threading
import logging
import os
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

# Intentar importar bleach, si no está disponible usar sanitización básica
try:
    import bleach
    BLEACH_AVAILABLE = True
except ImportError:
    BLEACH_AVAILABLE = False

# Intentar importar resend para envío de emails en cloud
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False


# =============================================================================
# SANITIZACIÓN DE HTML
# =============================================================================

# Tags HTML permitidos (para campos de texto enriquecido)
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'code',
    'a', 'span', 'div', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
]

# Atributos permitidos
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target'],
    'span': ['class'],
    'div': ['class'],
    'table': ['class', 'border'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
}


def sanitizar_html(texto):
    """
    Sanitiza HTML para prevenir XSS.
    Permite solo tags y atributos seguros.

    Args:
        texto (str): Texto con posible HTML

    Returns:
        str: Texto sanitizado
    """
    if not texto:
        return texto

    if BLEACH_AVAILABLE:
        # Usar bleach para sanitización robusta
        return bleach.clean(
            texto,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            strip=True
        )
    else:
        # Sanitización básica si bleach no está disponible
        return sanitizar_html_basico(texto)


def sanitizar_html_basico(texto):
    """
    Sanitización básica de HTML sin bleach.
    Elimina scripts y eventos JavaScript.
    """
    if not texto:
        return texto

    # Eliminar tags de script
    texto = re.sub(r'<script[^>]*>.*?</script>', '', texto, flags=re.IGNORECASE | re.DOTALL)

    # Eliminar atributos de eventos (onclick, onerror, etc.)
    texto = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\s+on\w+\s*=\s*\S+', '', texto, flags=re.IGNORECASE)

    # Eliminar javascript: en href/src
    texto = re.sub(r'(href|src)\s*=\s*["\']?\s*javascript:', r'\1=""', texto, flags=re.IGNORECASE)

    # Eliminar data: URLs peligrosas
    texto = re.sub(r'(href|src)\s*=\s*["\']?\s*data:', r'\1=""', texto, flags=re.IGNORECASE)

    # Eliminar tags style con contenido peligroso
    texto = re.sub(r'<style[^>]*>.*?</style>', '', texto, flags=re.IGNORECASE | re.DOTALL)

    # Eliminar expression() en estilos (IE)
    texto = re.sub(r'expression\s*\(', '', texto, flags=re.IGNORECASE)

    return texto


def sanitizar_texto_plano(texto):
    """
    Convierte texto a texto plano seguro (sin HTML).
    Útil para campos que no deben tener HTML.

    Args:
        texto (str): Texto con posible HTML

    Returns:
        str: Texto plano escapado
    """
    if not texto:
        return texto

    # Escapar todos los caracteres HTML
    return html.escape(str(texto))


def detectar_rol_por_email(email):
    """
    Detecta automáticamente el rol del usuario basándose en su dominio de email.

    Args:
        email (str): Email del usuario

    Returns:
        str: Rol detectado ('aprendiz', 'funcionario', o 'invitado')

    Ejemplos:
        >>> detectar_rol_por_email('juan@soy.sena.edu.co')
        'aprendiz'
        >>> detectar_rol_por_email('maria@sena.edu.co')
        'funcionario'
        >>> detectar_rol_por_email('carlos@gmail.com')
        'invitado'
    """
    email = email.lower().strip()

    if email.endswith('@soy.sena.edu.co'):
        return 'aprendiz'
    elif email.endswith('@sena.edu.co'):
        return 'funcionario'
    else:
        # Cualquier otro dominio (gmail, hotmail, etc.) es invitado
        return 'invitado'


def generar_codigo_verificacion():
    """
    Genera un código de verificación de 6 dígitos numéricos aleatorios.

    Returns:
        str: Código de 6 dígitos (ej: '123456')

    Ejemplos:
        >>> codigo = generar_codigo_verificacion()
        >>> len(codigo)
        6
        >>> codigo.isdigit()
        True
    """
    return ''.join(random.choices(string.digits, k=6))


def _enviar_con_resend(asunto, mensaje, destinatario, html_content=None):
    """
    Envía email usando Resend API (para Railway y otros cloud).
    """
    try:
        resend_api_key = os.environ.get('RESEND_API_KEY')
        if not resend_api_key:
            logger.error("RESEND_API_KEY no está configurada")
            return False

        resend.api_key = resend_api_key

        params = {
            "from": "Sistema Actas SENA <onboarding@resend.dev>",
            "to": [destinatario],
            "subject": asunto,
            "text": mensaje,
        }

        if html_content:
            params["html"] = html_content

        response = resend.Emails.send(params)
        logger.info(f"Email enviado con Resend a {destinatario}: {response}")
        return True
    except Exception as e:
        logger.error(f"Error al enviar email con Resend a {destinatario}: {str(e)}")
        return False


def _enviar_con_smtp(asunto, mensaje, destinatario):
    """
    Envía email usando SMTP tradicional (Gmail).
    """
    try:
        send_mail(
            subject=asunto,
            message=mensaje,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[destinatario],
            fail_silently=False,
        )
        logger.info(f"Email enviado con SMTP a {destinatario}")
        return True
    except Exception as e:
        logger.error(f"Error al enviar email con SMTP a {destinatario}: {str(e)}")
        return False


def _enviar_email_en_hilo(asunto, mensaje, destinatario, html_content=None):
    """
    Función interna que envía el email (ejecutada en un hilo separado).
    Detecta automáticamente si usar Resend o SMTP.
    """
    resend_api_key = os.environ.get('RESEND_API_KEY')

    if RESEND_AVAILABLE and resend_api_key:
        # Usar Resend (Railway, cloud)
        logger.info(f"Usando Resend para enviar a {destinatario}")
        _enviar_con_resend(asunto, mensaje, destinatario, html_content)
    else:
        # Usar SMTP tradicional (localhost, AWS)
        logger.info(f"Usando SMTP para enviar a {destinatario}")
        _enviar_con_smtp(asunto, mensaje, destinatario)


def enviar_email_verificacion(user, codigo):
    """
    Envía un email con el código de verificación al usuario.
    El envío se realiza en un hilo separado para no bloquear la petición.

    Detecta automáticamente el método de envío:
    - Si RESEND_API_KEY existe: usa Resend (cloud/Railway)
    - Si no: usa Gmail SMTP tradicional (localhost/AWS)

    Args:
        user: Instancia del modelo User
        codigo (str): Código de verificación de 6 dígitos

    Returns:
        bool: True siempre (el email se envía en background)
    """
    asunto = 'Código de Verificación - Sistema de Actas SENA'

    mensaje = f"""
Hola {user.first_name} {user.last_name},

Gracias por registrarte en el Sistema de Gestión de Actas del SENA.

Tu código de verificación es: {codigo}

Este código es válido por 15 minutos.

Por favor, ingresa este código en la aplicación para verificar tu cuenta.

Si no solicitaste este código, ignora este mensaje.

---
Sistema de Gestión de Actas SENA
Centro Minero
    """

    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background-color: #39A900; padding: 20px; text-align: center;">
            <h1 style="color: white; margin: 0;">Sistema de Actas SENA</h1>
        </div>
        <div style="padding: 30px; background-color: #f9f9f9;">
            <h2 style="color: #333;">Hola {user.first_name} {user.last_name},</h2>
            <p>Gracias por registrarte en el Sistema de Gestión de Actas del SENA.</p>
            <div style="background-color: #39A900; color: white; padding: 20px; text-align: center; border-radius: 10px; margin: 20px 0;">
                <p style="margin: 0; font-size: 14px;">Tu código de verificación es:</p>
                <h1 style="margin: 10px 0; font-size: 36px; letter-spacing: 5px;">{codigo}</h1>
            </div>
            <p style="color: #666;">Este código es válido por <strong>15 minutos</strong>.</p>
            <p style="color: #666;">Si no solicitaste este código, ignora este mensaje.</p>
        </div>
        <div style="background-color: #333; color: #999; padding: 15px; text-align: center; font-size: 12px;">
            Sistema de Gestión de Actas - Centro Minero SENA
        </div>
    </div>
    """

    # Enviar email en un hilo separado para no bloquear la petición
    thread = threading.Thread(
        target=_enviar_email_en_hilo,
        args=(asunto, mensaje, user.email, html_content)
    )
    thread.daemon = True
    thread.start()

    logger.info(f"Email de verificación programado para {user.email}")
    return True


def crear_codigo_verificacion(user, tipo='registro'):
    """
    Crea un código de verificación para el usuario y lo guarda en la base de datos.

    Args:
        user: Instancia del modelo User
        tipo (str): Tipo de código ('registro' o 'recuperacion')

    Returns:
        CodigoVerificacion: Instancia del código creado

    Ejemplo:
        >>> from accounts.models import User
        >>> user = User.objects.get(email='test@example.com')
        >>> codigo_obj = crear_codigo_verificacion(user, 'registro')
        >>> print(codigo_obj.codigo)
        '123456'
    """
    from accounts.models import CodigoVerificacion

    # Generar código
    codigo = generar_codigo_verificacion()

    # Calcular fecha de expiración (15 minutos desde ahora)
    fecha_expiracion = timezone.now() + timedelta(minutes=15)

    # Crear y guardar el código
    codigo_obj = CodigoVerificacion.objects.create(
        user=user,
        codigo=codigo,
        tipo=tipo,
        fecha_expiracion=fecha_expiracion
    )

    return codigo_obj


def verificar_codigo(user, codigo_ingresado, tipo='registro'):
    """
    Verifica si un código ingresado es válido para el usuario.

    Args:
        user: Instancia del modelo User
        codigo_ingresado (str): Código ingresado por el usuario
        tipo (str): Tipo de código a verificar ('registro' o 'recuperacion')

    Returns:
        tuple: (bool, str) - (es_valido, mensaje_error)

    Ejemplos:
        >>> verificar_codigo(user, '123456', 'registro')
        (True, '')
        >>> verificar_codigo(user, '000000', 'registro')
        (False, 'Código incorrecto')
    """
    from accounts.models import CodigoVerificacion

    try:
        # Buscar el código más reciente del usuario para el tipo especificado
        codigo_obj = CodigoVerificacion.objects.filter(
            user=user,
            tipo=tipo,
            usado=False
        ).order_by('-fecha_creacion').first()

        if not codigo_obj:
            return False, 'No se encontró un código de verificación válido'

        # Verificar si el código coincide
        if codigo_obj.codigo != codigo_ingresado:
            return False, 'Código incorrecto'

        # Verificar si el código ha expirado
        if not codigo_obj.is_valid():
            return False, 'El código ha expirado. Solicita uno nuevo'

        # Código válido
        return True, ''

    except Exception as e:
        return False, f'Error al verificar el código: {str(e)}'


def aprobar_usuario_automaticamente(user):
    """
    Aprueba y verifica automáticamente la cuenta de un usuario.

    Args:
        user: Instancia del modelo User

    Returns:
        User: Usuario actualizado

    Ejemplo:
        >>> user = aprobar_usuario_automaticamente(user)
        >>> user.email_verificado
        True
        >>> user.cuenta_aprobada
        True
    """
    user.email_verificado = True
    user.cuenta_aprobada = True
    user.save()
    return user
