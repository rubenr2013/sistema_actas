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
    Verifica el email del usuario y decide si su cuenta queda activa
    o pendiente de aprobación según su rol:

      - aprendiz / invitado → estado_cuenta='activa' (aprobación automática)
      - funcionario        → estado_cuenta='pendiente_aprobacion' (requiere admin)

    Args:
        user: Instancia del modelo User

    Returns:
        User: Usuario actualizado
    """
    user.email_verificado = True

    if user.rol in ('aprendiz', 'invitado'):
        # Aprendices e invitados quedan activos de inmediato
        user.cuenta_aprobada = True
        user.estado_cuenta = 'activa'
        user.save()
    else:
        # Funcionarios quedan pendientes de revisión por el admin
        user.cuenta_aprobada = False
        user.estado_cuenta = 'pendiente_aprobacion'
        user.save()
        # Notificar a todos los admins sobre el nuevo funcionario
        notificar_admins_nuevo_funcionario(user)

    return user


def _enviar_email_nuevo_funcionario_admin(admin_user, nuevo_usuario):
    """
    Función interna que envía el email al admin avisando de un
    nuevo funcionario pendiente de aprobación.
    Se ejecuta en un hilo separado (no bloquea la petición).
    """
    asunto = f'Nueva solicitud de cuenta: {nuevo_usuario.get_full_name()} ({nuevo_usuario.email})'

    mensaje = f"""
Hola {admin_user.first_name},

Un nuevo funcionario se ha registrado en el Sistema de Actas del SENA y está esperando aprobación:

  Nombre:   {nuevo_usuario.get_full_name()}
  Email:    {nuevo_usuario.email}
  Documento: {nuevo_usuario.get_tipo_documento_display() if hasattr(nuevo_usuario, 'get_tipo_documento_display') else nuevo_usuario.tipo_documento} {nuevo_usuario.numero_documento}

Por favor ingresa al panel de administración para revisar y asignar el rol correspondiente.

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
            <h2 style="color: #333;">Nueva solicitud de cuenta</h2>
            <p>Hola <strong>{admin_user.first_name}</strong>,</p>
            <p>El siguiente funcionario se registró y está <strong>pendiente de aprobación</strong>:</p>
            <table style="width:100%; border-collapse:collapse; margin:16px 0;">
                <tr>
                    <td style="padding:8px; font-weight:bold; color:#555;">Nombre:</td>
                    <td style="padding:8px;">{nuevo_usuario.get_full_name()}</td>
                </tr>
                <tr style="background:#f0f0f0;">
                    <td style="padding:8px; font-weight:bold; color:#555;">Email:</td>
                    <td style="padding:8px;">{nuevo_usuario.email}</td>
                </tr>
                <tr>
                    <td style="padding:8px; font-weight:bold; color:#555;">Documento:</td>
                    <td style="padding:8px;">{nuevo_usuario.tipo_documento} {nuevo_usuario.numero_documento}</td>
                </tr>
            </table>
            <p>Por favor ingresa al sistema para revisar y asignar el rol correspondiente.</p>
        </div>
        <div style="background-color: #333; color: #999; padding: 15px; text-align: center; font-size: 12px;">
            Sistema de Gestión de Actas - Centro Minero SENA
        </div>
    </div>
    """

    _enviar_email_en_hilo(asunto, mensaje, admin_user.email, html_content)


def notificar_admins_nuevo_funcionario(nuevo_usuario):
    """
    Notifica a todos los admins activos del sistema cuando un nuevo
    funcionario se registra con estado 'pendiente_aprobacion'.

    Para cada admin:
      1. Crea una notificación in-app
      2. Envía un email en background

    Args:
        nuevo_usuario: instancia del User recién registrado
    """
    from accounts.models import User as UserModel
    from notifications.models import Notification

    admins = UserModel.objects.filter(rol='admin', activo=True)

    if not admins.exists():
        logger.warning(
            f"No hay admins activos para notificar sobre el nuevo funcionario {nuevo_usuario.email}"
        )
        return

    mensaje_notif = (
        f"Nuevo funcionario registrado: {nuevo_usuario.get_full_name()} ({nuevo_usuario.email}). "
        f"Por favor revisa y asigna su rol."
    )

    for admin in admins:
        # Notificación in-app
        Notification.objects.create(
            usuario=admin,
            tipo='nueva_solicitud_rol',
            titulo='Nueva solicitud de cuenta pendiente',
            mensaje=mensaje_notif,
            enlace='/actas/api/admin/usuarios/',
        )

        # Email en hilo separado para no bloquear la petición
        thread = threading.Thread(
            target=_enviar_email_nuevo_funcionario_admin,
            args=(admin, nuevo_usuario)
        )
        thread.daemon = True
        thread.start()

    logger.info(
        f"Notificación de nuevo funcionario enviada a {admins.count()} admin(s) "
        f"para el usuario {nuevo_usuario.email}"
    )


# =============================================================================
# APROBACIÓN / RECHAZO DE CUENTAS
# =============================================================================

def _enviar_email_cuenta_aprobada(user, nuevo_rol):
    """
    Email al usuario cuando su cuenta es aprobada por un admin.
    Se ejecuta en un hilo separado.
    """
    rol_legible = {
        'admin': 'Administrador',
        'director': 'Director',
        'coordinador': 'Coordinador',
        'instructor': 'Instructor',
        'funcionario': 'Funcionario',
    }.get(nuevo_rol, nuevo_rol.capitalize())

    asunto = '¡Tu cuenta ha sido aprobada! - Sistema de Actas SENA'

    mensaje = f"""
Hola {user.first_name} {user.last_name},

¡Buenas noticias! Tu cuenta en el Sistema de Actas del SENA ha sido aprobada.

  Rol asignado: {rol_legible}

Ya puedes iniciar sesión y acceder al sistema.

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
            <h2 style="color: #333;">¡Tu cuenta ha sido aprobada!</h2>
            <p>Hola <strong>{user.first_name} {user.last_name}</strong>,</p>
            <p>Tu cuenta ha sido revisada y aprobada por el administrador.</p>
            <div style="background-color: #39A900; color: white; padding: 16px; border-radius: 8px; margin: 20px 0; text-align: center;">
                <p style="margin: 0; font-size: 14px;">Tu rol en el sistema:</p>
                <h2 style="margin: 8px 0;">{rol_legible}</h2>
            </div>
            <p>Ya puedes iniciar sesión y usar el sistema.</p>
        </div>
        <div style="background-color: #333; color: #999; padding: 15px; text-align: center; font-size: 12px;">
            Sistema de Gestión de Actas - Centro Minero SENA
        </div>
    </div>
    """

    _enviar_email_en_hilo(asunto, mensaje, user.email, html_content)


def aprobar_cuenta_usuario(user_a_aprobar, nuevo_rol, admin_user, observaciones=''):
    """
    Aprueba la cuenta de un funcionario pendiente.

    Actualiza: rol, estado_cuenta='activa', fecha_aprobacion, aprobado_por.
    Notifica: email + in-app al usuario aprobado.

    Args:
        user_a_aprobar: instancia del User a aprobar
        nuevo_rol (str): rol a asignar (instructor, coordinador, etc.)
        admin_user: instancia del admin que aprueba
        observaciones (str): notas opcionales del admin
    """
    from django.utils import timezone
    from notifications.models import Notification

    ROLES_VALIDOS = ['admin', 'director', 'coordinador', 'instructor', 'funcionario']
    if nuevo_rol not in ROLES_VALIDOS:
        raise ValueError(f"Rol '{nuevo_rol}' inválido. Opciones: {ROLES_VALIDOS}")

    # Actualizar el usuario
    user_a_aprobar.rol = nuevo_rol
    user_a_aprobar.estado_cuenta = 'activa'
    user_a_aprobar.cuenta_aprobada = True
    user_a_aprobar.fecha_aprobacion = timezone.now()
    user_a_aprobar.aprobado_por = admin_user
    if observaciones:
        user_a_aprobar.observaciones_aprobacion = observaciones
    user_a_aprobar.save()

    # Notificación in-app al usuario
    rol_legible = {
        'admin': 'Administrador', 'director': 'Director',
        'coordinador': 'Coordinador', 'instructor': 'Instructor',
        'funcionario': 'Funcionario',
    }.get(nuevo_rol, nuevo_rol.capitalize())

    Notification.objects.create(
        usuario=user_a_aprobar,
        tipo='sistema',
        titulo='¡Tu cuenta ha sido aprobada!',
        mensaje=f'Tu cuenta fue aprobada. Ahora puedes usar el sistema con el rol de {rol_legible}.',
        enlace='/actas/',
    )

    # Email al usuario (en hilo separado)
    thread = threading.Thread(
        target=_enviar_email_cuenta_aprobada,
        args=(user_a_aprobar, nuevo_rol)
    )
    thread.daemon = True
    thread.start()

    logger.info(
        f"Cuenta aprobada: {user_a_aprobar.email} con rol '{nuevo_rol}' "
        f"por {admin_user.email}"
    )


# =============================================================================
# FUSIÓN DE PDFs (ACTA + ANEXOS)
# =============================================================================

def fusionar_acta_con_anexos(acta_pdf_bytes: bytes, acta) -> bytes:
    """
    Fusiona el PDF del acta con sus AnexoActa ordenados.

    Args:
        acta_pdf_bytes: bytes del PDF del acta principal (generado con ReportLab).
        acta: instancia de Acta.

    Returns:
        bytes del PDF consolidado (acta + anexos en orden).
        Si no hay anexos o hay error en la fusión, retorna acta_pdf_bytes sin cambios.
    """
    try:
        from pypdf import PdfWriter, PdfReader
        import io as _io

        anexos = acta.anexos.order_by('orden', 'fecha_carga').all()
        if not anexos.exists():
            return acta_pdf_bytes

        writer = PdfWriter()

        # 1. Añadir páginas del acta principal
        reader_acta = PdfReader(_io.BytesIO(acta_pdf_bytes))
        for page in reader_acta.pages:
            writer.add_page(page)

        # 2. Añadir páginas de cada anexo en orden
        for anexo in anexos:
            try:
                if not anexo.archivo or not os.path.isfile(anexo.archivo.path):
                    logger.warning(f'Anexo {anexo.id} no encontrado en disco, se omite.')
                    continue
                reader_anexo = PdfReader(anexo.archivo.path)
                for page in reader_anexo.pages:
                    writer.add_page(page)
            except Exception as exc_anexo:
                logger.error(
                    f'Error al fusionar anexo {anexo.id} ({anexo.nombre_archivo}): {exc_anexo}'
                )
                continue  # Omitir el anexo corrupto, continuar con los demás

        # 3. Serializar a bytes
        output = _io.BytesIO()
        writer.write(output)
        return output.getvalue()

    except ImportError:
        logger.error('pypdf no está instalado. Instálalo con: pip install pypdf')
        return acta_pdf_bytes
    except Exception as exc:
        logger.error(
            f'Error al fusionar PDF del acta {acta.numero_acta}: {exc}', exc_info=True
        )
        return acta_pdf_bytes  # Fallback: devolver solo el acta sin los anexos


# =============================================================================
# REVISIÓN COLABORATIVA DE ACTAS
# =============================================================================

def _registrar_historial_acta(acta, accion, usuario_nombre, detalle='', ciclo=None):
    """
    Agrega una entrada al campo historial_cambios del acta (JSONField).
    NO hace save() — el llamador debe guardar el acta.
    """
    if not isinstance(acta.historial_cambios, list):
        acta.historial_cambios = []
    acta.historial_cambios.append({
        'ciclo': ciclo if ciclo is not None else acta.ciclo_revision,
        'fecha': timezone.now().isoformat(),
        'accion': accion,
        'usuario': usuario_nombre,
        'detalle': detalle,
    })


def _notificar_participantes_acta(acta, tipo, titulo_tpl, mensaje_tpl, excluir_ids=None):
    """
    Crea notificaciones in-app para TODOS los participantes del acta.

    titulo_tpl / mensaje_tpl pueden contener {numero_acta} como placeholder.
    excluir_ids: set/list de IDs de usuario que NO deben recibir la notificación.
    """
    from notifications.models import Notification

    excluir_ids = set(excluir_ids or [])
    enlace = f'/actas/{acta.id}/'
    titulo = titulo_tpl.format(numero_acta=acta.numero_acta)
    mensaje = mensaje_tpl.format(numero_acta=acta.numero_acta, titulo=acta.titulo)

    for p in acta.participantes.select_related('usuario').all():
        if p.usuario_id in excluir_ids:
            continue
        Notification.objects.create(
            usuario=p.usuario,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            enlace=enlace,
        )


def _enviar_email_revision_pendiente_thread(acta, participante):
    """Email de invitación a revisar el acta (ejecutado en hilo)."""
    try:
        site_url = getattr(settings, 'SITE_DOMAIN', '127.0.0.1:8000')
        protocol = 'https' if '127.0.0.1' not in site_url and 'localhost' not in site_url else 'http'
        url_acta = f'{protocol}://{site_url}/actas/{acta.id}/'

        html_message = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
          <div style="background:linear-gradient(135deg,#39A900,#2d8400);padding:30px;text-align:center;">
            <h1 style="color:#fff;margin:0;font-size:24px;">Sistema de Actas SENA</h1>
          </div>
          <div style="padding:30px;">
            <p>Hola, <strong>{participante.get_full_name()}</strong></p>
            <p>Has sido invitado/a a revisar el acta:</p>
            <div style="background:#f8f9fa;border-left:4px solid #39A900;padding:15px;margin:20px 0;border-radius:4px;">
              <strong>{acta.numero_acta}</strong> — {acta.titulo}
            </div>
            <p>Por favor, ingresa al sistema para aprobar o rechazar el acta con tus observaciones.</p>
            <div style="text-align:center;margin:25px 0;">
              <a href="{url_acta}" style="background:#39A900;color:#fff;padding:12px 30px;border-radius:6px;text-decoration:none;font-weight:bold;">
                Revisar acta
              </a>
            </div>
            <p style="color:#666;font-size:13px;">Si el botón no funciona, copia este enlace: {url_acta}</p>
          </div>
        </div>
        """
        send_mail(
            subject=f'[SENA] Acta {acta.numero_acta} pendiente de tu revisión',
            message=f'El acta {acta.numero_acta} ({acta.titulo}) está pendiente de tu revisión.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[participante.email],
            html_message=html_message,
            fail_silently=True,
        )
    except Exception as exc:
        logger.error(f'Error al enviar email de revisión pendiente: {exc}')


def _enviar_email_acta_rechazada_thread(acta, creador, participante_nombre, observaciones):
    """Email al creador cuando un participante rechaza el acta (ejecutado en hilo)."""
    try:
        site_url = getattr(settings, 'SITE_DOMAIN', '127.0.0.1:8000')
        protocol = 'https' if '127.0.0.1' not in site_url and 'localhost' not in site_url else 'http'
        url_acta = f'{protocol}://{site_url}/actas/{acta.id}/'

        html_message = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
          <div style="background:linear-gradient(135deg,#dc3545,#b02a37);padding:30px;text-align:center;">
            <h1 style="color:#fff;margin:0;font-size:24px;">Sistema de Actas SENA</h1>
          </div>
          <div style="padding:30px;">
            <p>Hola, <strong>{creador.get_full_name()}</strong></p>
            <p>El participante <strong>{participante_nombre}</strong> ha <strong>rechazado</strong> el acta:</p>
            <div style="background:#f8f9fa;border-left:4px solid #dc3545;padding:15px;margin:20px 0;border-radius:4px;">
              <strong>{acta.numero_acta}</strong> — {acta.titulo}
            </div>
            <p><strong>Motivo del rechazo:</strong></p>
            <div style="background:#fff3cd;border:1px solid #ffc107;padding:15px;border-radius:4px;margin:10px 0;">
              {observaciones}
            </div>
            <p>El acta ha vuelto al estado <em>Borrador</em> para que puedas corregirla y enviarla nuevamente a revisión.</p>
            <div style="text-align:center;margin:25px 0;">
              <a href="{url_acta}" style="background:#dc3545;color:#fff;padding:12px 30px;border-radius:6px;text-decoration:none;font-weight:bold;">
                Ver acta
              </a>
            </div>
          </div>
        </div>
        """
        send_mail(
            subject=f'[SENA] Acta {acta.numero_acta} rechazada por {participante_nombre}',
            message=f'{participante_nombre} rechazó el acta {acta.numero_acta}. Motivo: {observaciones}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[creador.email],
            html_message=html_message,
            fail_silently=True,
        )
    except Exception as exc:
        logger.error(f'Error al enviar email de acta rechazada: {exc}')


def _enviar_email_acta_finalizada_thread(acta, participante):
    """Email a cada participante cuando el acta es finalizada (ejecutado en hilo)."""
    try:
        site_url = getattr(settings, 'SITE_DOMAIN', '127.0.0.1:8000')
        protocol = 'https' if '127.0.0.1' not in site_url and 'localhost' not in site_url else 'http'
        url_acta = f'{protocol}://{site_url}/actas/{acta.id}/'

        html_message = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
          <div style="background:linear-gradient(135deg,#198754,#146c43);padding:30px;text-align:center;">
            <h1 style="color:#fff;margin:0;font-size:24px;">Sistema de Actas SENA</h1>
          </div>
          <div style="padding:30px;">
            <p>Hola, <strong>{participante.get_full_name()}</strong></p>
            <p>El acta <strong>{acta.numero_acta}</strong> — <em>{acta.titulo}</em> ha sido <strong>finalizada</strong>.</p>
            <p>Todos los participantes han aprobado el contenido del acta.</p>
            <div style="text-align:center;margin:25px 0;">
              <a href="{url_acta}" style="background:#198754;color:#fff;padding:12px 30px;border-radius:6px;text-decoration:none;font-weight:bold;">
                Ver acta finalizada
              </a>
            </div>
          </div>
        </div>
        """
        send_mail(
            subject=f'[SENA] Acta {acta.numero_acta} finalizada',
            message=f'El acta {acta.numero_acta} ({acta.titulo}) ha sido finalizada. Todos aprobaron.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[participante.email],
            html_message=html_message,
            fail_silently=True,
        )
    except Exception as exc:
        logger.error(f'Error al enviar email de acta finalizada: {exc}')


def _enviar_email_acta_cerrada_thread(acta, participante, motivo):
    """Email a cada participante cuando el acta se cierra por vencimiento (ejecutado en hilo)."""
    try:
        site_url = getattr(settings, 'SITE_DOMAIN', '127.0.0.1:8000')
        protocol = 'https' if '127.0.0.1' not in site_url and 'localhost' not in site_url else 'http'
        url_acta = f'{protocol}://{site_url}/actas/{acta.id}/'

        html_message = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
          <div style="background:linear-gradient(135deg,#6c757d,#495057);padding:30px;text-align:center;">
            <h1 style="color:#fff;margin:0;font-size:24px;">Sistema de Actas SENA</h1>
          </div>
          <div style="padding:30px;">
            <p>Hola, <strong>{participante.get_full_name()}</strong></p>
            <p>El acta <strong>{acta.numero_acta}</strong> — <em>{acta.titulo}</em> ha sido <strong>cerrada sin consenso</strong>.</p>
            <div style="background:#f8f9fa;border-left:4px solid #6c757d;padding:15px;margin:20px 0;border-radius:4px;">
              <strong>Motivo:</strong> {motivo}
            </div>
            <div style="text-align:center;margin:25px 0;">
              <a href="{url_acta}" style="background:#6c757d;color:#fff;padding:12px 30px;border-radius:6px;text-decoration:none;font-weight:bold;">
                Ver acta
              </a>
            </div>
          </div>
        </div>
        """
        send_mail(
            subject=f'[SENA] Acta {acta.numero_acta} cerrada por vencimiento',
            message=f'El acta {acta.numero_acta} fue cerrada. Motivo: {motivo}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[participante.email],
            html_message=html_message,
            fail_silently=True,
        )
    except Exception as exc:
        logger.error(f'Error al enviar email de acta cerrada: {exc}')


def enviar_acta_a_revision(acta, creador):
    """
    Envía el acta al estado 'en_revision':
    - Cambia estado y calcula fecha_limite_revision (now + 7 días)
    - Marca todos los participantes del ciclo actual como 'pendiente'
    - Registra en historial_cambios
    - Envía notificaciones in-app + email a todos los participantes
    """
    from notifications.models import Notification

    now = timezone.now()
    acta.estado = 'en_revision'
    acta.fecha_limite_revision = now + timedelta(days=7)

    _registrar_historial_acta(
        acta,
        accion='enviado_a_revision',
        usuario_nombre=creador.get_full_name(),
        detalle=f'Ciclo {acta.ciclo_revision}: acta enviada a revisión. '
                f'Fecha límite: {acta.fecha_limite_revision.strftime("%d/%m/%Y %H:%M")}',
    )
    acta.save()

    # Resetear estado de todos los participantes para este ciclo
    acta.participantes.all().update(
        estado_aprobacion='pendiente',
        fecha_respuesta=None,
        observaciones='',
        ciclo_revision=acta.ciclo_revision,
    )

    # Notificaciones
    _notificar_participantes_acta(
        acta,
        tipo='revision_pendiente',
        titulo_tpl='Acta {numero_acta} pendiente de tu revisión',
        mensaje_tpl='El acta {numero_acta} — {titulo} está disponible para revisión. '
                    'Por favor, aprueba o rechaza con tus observaciones.',
        excluir_ids=[creador.id],
    )

    # Email en hilos separados
    for p in acta.participantes.select_related('usuario').exclude(usuario_id=creador.id):
        t = threading.Thread(
            target=_enviar_email_revision_pendiente_thread,
            args=(acta, p.usuario),
            daemon=True,
        )
        t.start()

    logger.info(f'Acta {acta.numero_acta} enviada a revisión. Ciclo {acta.ciclo_revision}.')


def aprobar_acta_participante(acta, participante_user, firma_base64=None):
    """
    Registra la aprobación de un participante:
    - Actualiza Participante.estado_aprobacion = 'aprobado'
    - Guarda la firma si se provee
    - Si TODOS aprobaron → acta pasa a 'finalizada', notifica a todos
    - Si no → registra en historial y notifica al creador
    Retorna el estado actualizado del acta ('en_revision' o 'finalizada').
    """
    from notifications.models import Notification
    from .models import Participante, Firma

    participante_obj = acta.participantes.select_related('usuario').get(usuario=participante_user)
    participante_obj.estado_aprobacion = 'aprobado'
    participante_obj.fecha_respuesta = timezone.now()
    participante_obj.ciclo_revision = acta.ciclo_revision
    participante_obj.save()

    # Guardar/actualizar la firma si se envió base64
    if firma_base64:
        import base64
        from django.core.files.base import ContentFile
        try:
            if ',' in firma_base64:
                firma_base64 = firma_base64.split(',', 1)[1]
            firma_bytes = base64.b64decode(firma_base64)
            firma_obj, _ = Firma.objects.get_or_create(acta=acta, usuario=participante_user)
            firma_obj.firmado = True
            firma_obj.fecha_firma = timezone.now()
            firma_obj.firma_datos = firma_base64  # base64 puro, persiste en BD
            firma_obj.firma_imagen.save(
                f'firma_{participante_user.id}_{acta.id}.png',
                ContentFile(firma_bytes),
                save=True,
            )
        except Exception as exc:
            logger.warning(f'No se pudo guardar firma base64: {exc}')

    # Registrar en historial
    _registrar_historial_acta(
        acta,
        accion='aprobado_por_participante',
        usuario_nombre=participante_user.get_full_name(),
        detalle=f'{participante_user.get_full_name()} aprobó el acta en el ciclo {acta.ciclo_revision}.',
    )

    # Verificar si TODOS los participantes aprobaron
    total = acta.participantes.count()
    aprobados = acta.participantes.filter(
        estado_aprobacion='aprobado', ciclo_revision=acta.ciclo_revision
    ).count()

    if total > 0 and aprobados == total:
        # Acta finalizada
        acta.estado = 'finalizada'
        _registrar_historial_acta(
            acta,
            accion='finalizada',
            usuario_nombre='sistema',
            detalle=f'Todos los participantes ({total}) aprobaron el acta.',
        )
        acta.save()

        # Notificar a TODOS los participantes
        _notificar_participantes_acta(
            acta,
            tipo='acta_finalizada',
            titulo_tpl='Acta {numero_acta} finalizada',
            mensaje_tpl='El acta {numero_acta} — {titulo} ha sido finalizada. Todos los participantes aprobaron.',
        )
        for p in acta.participantes.select_related('usuario').all():
            t = threading.Thread(
                target=_enviar_email_acta_finalizada_thread,
                args=(acta, p.usuario),
                daemon=True,
            )
            t.start()
    else:
        acta.save()
        # Notificar al creador
        Notification.objects.create(
            usuario=acta.creador,
            tipo='acta_aprobada_parcial',
            titulo=f'{participante_user.get_full_name()} aprobó el acta {acta.numero_acta}',
            mensaje=f'{participante_user.get_full_name()} aprobó el acta. '
                    f'{aprobados}/{total} participantes han aprobado.',
            enlace=f'/actas/{acta.id}/',
        )

    logger.info(
        f'Acta {acta.numero_acta}: {participante_user.email} aprobó. '
        f'Estado: {acta.estado}. Aprobados {aprobados}/{total}.'
    )
    return acta.estado


def rechazar_acta_participante(acta, participante_user, observaciones):
    """
    Registra el rechazo de un participante:
    - Actualiza Participante.estado_aprobacion = 'rechazado'
    - Cambia acta a estado 'borrador'
    - Incrementa ciclo_revision
    - Registra en historial_cambios
    - Notifica al creador (in-app + email)
    Retorna el acta actualizada.
    """
    from notifications.models import Notification

    participante_obj = acta.participantes.select_related('usuario').get(usuario=participante_user)
    participante_obj.estado_aprobacion = 'rechazado'
    participante_obj.fecha_respuesta = timezone.now()
    participante_obj.observaciones = observaciones
    participante_obj.ciclo_revision = acta.ciclo_revision
    participante_obj.save()

    ciclo_anterior = acta.ciclo_revision

    _registrar_historial_acta(
        acta,
        accion='rechazado_por_participante',
        usuario_nombre=participante_user.get_full_name(),
        detalle=f'{participante_user.get_full_name()} rechazó el acta. Motivo: {observaciones}',
        ciclo=ciclo_anterior,
    )

    # Regresar a borrador e incrementar ciclo
    acta.estado = 'borrador'
    acta.ciclo_revision = ciclo_anterior + 1

    _registrar_historial_acta(
        acta,
        accion='regresado_a_borrador',
        usuario_nombre='sistema',
        detalle=f'Ciclo {acta.ciclo_revision}: acta regresada a borrador tras rechazo.',
        ciclo=acta.ciclo_revision,
    )
    acta.save()

    # Notificación in-app al creador
    Notification.objects.create(
        usuario=acta.creador,
        tipo='acta_rechazada',
        titulo=f'{participante_user.get_full_name()} rechazó el acta {acta.numero_acta}',
        mensaje=f'Motivo: {observaciones}. El acta ha vuelto al estado Borrador (ciclo {acta.ciclo_revision}).',
        enlace=f'/actas/{acta.id}/',
    )

    # Email al creador en hilo separado
    t = threading.Thread(
        target=_enviar_email_acta_rechazada_thread,
        args=(acta, acta.creador, participante_user.get_full_name(), observaciones),
        daemon=True,
    )
    t.start()

    logger.info(
        f'Acta {acta.numero_acta}: {participante_user.email} rechazó. '
        f'Ciclo nuevo: {acta.ciclo_revision}.'
    )
    return acta


def cerrar_acta_por_vencimiento(acta, usuario_cierre, motivo):
    """
    Cierra el acta por vencimiento de plazo:
    - Cambia estado a 'cerrada_por_vencimiento'
    - Guarda cerrada_por, fecha_cierre y motivo_cierre
    - Registra estado final de cada participante en historial
    - Notifica a TODOS los participantes (in-app + email)
    Retorna el acta actualizada.
    """
    now = timezone.now()
    acta.estado = 'cerrada_por_vencimiento'
    acta.cerrada_por = usuario_cierre
    acta.fecha_cierre = now
    acta.motivo_cierre = motivo

    # Registrar estado final de cada participante
    resumen_participantes = []
    for p in acta.participantes.select_related('usuario').all():
        resumen_participantes.append(
            f'{p.usuario.get_full_name()}: {p.get_estado_aprobacion_display()}'
        )

    _registrar_historial_acta(
        acta,
        accion='cerrada_por_vencimiento',
        usuario_nombre=usuario_cierre.get_full_name(),
        detalle=(
            f'Acta cerrada por vencimiento. Motivo: {motivo}. '
            f'Estado final por participante: {"; ".join(resumen_participantes)}'
        ),
    )
    acta.save()

    # Notificaciones in-app a todos los participantes
    _notificar_participantes_acta(
        acta,
        tipo='acta_cerrada',
        titulo_tpl='Acta {numero_acta} cerrada sin consenso',
        mensaje_tpl=f'El acta {{numero_acta}} — {{titulo}} fue cerrada por vencimiento. Motivo: {motivo}',
    )

    # Emails en hilos separados
    for p in acta.participantes.select_related('usuario').all():
        t = threading.Thread(
            target=_enviar_email_acta_cerrada_thread,
            args=(acta, p.usuario, motivo),
            daemon=True,
        )
        t.start()

    logger.info(
        f'Acta {acta.numero_acta} cerrada por vencimiento por {usuario_cierre.email}. '
        f'Motivo: {motivo}'
    )
    return acta


def rechazar_cuenta_usuario(user_a_rechazar, motivo, admin_user):
    """
    Rechaza la cuenta de un funcionario pendiente.

    Actualiza: estado_cuenta='rechazada', observaciones_aprobacion, fecha_aprobacion.
    Notifica: solo in-app al usuario (sin email por privacidad).

    Args:
        user_a_rechazar: instancia del User a rechazar
        motivo (str): razón del rechazo (se guardará y mostrará al usuario)
        admin_user: instancia del admin que rechaza
    """
    from django.utils import timezone
    from notifications.models import Notification

    # Actualizar el usuario
    user_a_rechazar.estado_cuenta = 'rechazada'
    user_a_rechazar.cuenta_aprobada = False
    user_a_rechazar.fecha_aprobacion = timezone.now()
    user_a_rechazar.aprobado_por = admin_user
    user_a_rechazar.observaciones_aprobacion = motivo
    user_a_rechazar.save()

    # Solo notificación in-app (sin email por privacidad)
    Notification.objects.create(
        usuario=user_a_rechazar,
        tipo='sistema',
        titulo='Solicitud de cuenta no aprobada',
        mensaje=f'Tu solicitud de registro no fue aprobada. Motivo: {motivo}',
        enlace='/accounts/cuenta-pendiente/',
    )

    logger.info(
        f"Cuenta rechazada: {user_a_rechazar.email} "
        f"por {admin_user.email}. Motivo: {motivo}"
    )
