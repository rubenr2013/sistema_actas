from django.contrib.auth import authenticate, get_user_model
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, FileResponse
from django.utils import timezone
from django.conf import settings
from django.db.models import Q, Count, Prefetch, Max
from datetime import timedelta, datetime
from rest_framework.authtoken.models import Token
from .models import Acta, Participante, Firma, Compromiso, ComentarioActa, ArchivoAdjunto
import json
import logging
import os
import zipfile
import tempfile


User = get_user_model()
logger = logging.getLogger(__name__)


def handle_error(e, custom_message="Error procesando la solicitud"):
    """
    Maneja errores de forma segura sin exponer detalles internos
    Registra el error completo en logs
    """
    logger.error(f"{custom_message}: {str(e)}", exc_info=True)
    return custom_message


def get_user_from_token(request):
    """
    Helper para autenticar al usuario usando el token del header Authorization.
    Incluye verificación de expiración de token (24 horas por defecto).

    Retorna:
        - (user, None) si el token es válido
        - (None, JsonResponse) si el token es inválido o falta

    Uso:
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response
        # Continuar con user autenticado
    """
    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith('Bearer '):
        return None, JsonResponse({
            'success': False,
            'error': 'No autenticado. Header Authorization requerido.'
        }, status=401)

    token_key = auth_header.replace('Bearer ', '').strip()

    if not token_key:
        return None, JsonResponse({
            'success': False,
            'error': 'Token vacío'
        }, status=401)

    try:
        token = Token.objects.select_related('user').get(key=token_key)

        # Verificar expiración del token (24 horas por defecto)
        token_lifetime = getattr(settings, 'TOKEN_EXPIRATION_HOURS', 24)
        token_age = timezone.now() - token.created

        if token_age > timedelta(hours=token_lifetime):
            # Token expirado - eliminarlo
            token.delete()
            return None, JsonResponse({
                'success': False,
                'error': 'Token expirado. Por favor inicia sesión nuevamente.',
                'codigo_error': 'TOKEN_EXPIRADO'
            }, status=401)

        return token.user, None
    except Token.DoesNotExist:
        return None, JsonResponse({
            'success': False,
            'error': 'Token inválido o expirado'
        }, status=401)


@csrf_exempt
def login_api(request):
    """
    API de login para la app móvil Flutter.

    Recibe:
        - username (email del usuario)
        - password

    Retorna:
        - token: Token aleatorio seguro de 40 caracteres
        - user: Datos del usuario autenticado

    Seguridad:
        - Genera un token criptográfico único por usuario
        - El token se almacena en la base de datos
        - Si el usuario ya tiene un token, se retorna el existente
    """
    if request.method == 'POST':
        try:
            # Leer datos del request (con validación de JSON)
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({
                    'success': False,
                    'error': 'Formato de datos inválido'
                }, status=400)

            # Validar que los campos sean strings
            numero_documento = data.get('numero_documento', '') if isinstance(data.get('numero_documento'), str) else ''
            password = data.get('password') if isinstance(data.get('password'), str) else None
            # Soporte legacy: algunos clientes pueden seguir enviando 'username' o 'email'
            legacy_username = data.get('username', '') or data.get('email', '')

            if not password:
                return JsonResponse({
                    'success': False,
                    'error': 'La contraseña es requerida'
                }, status=400)

            if not numero_documento and not legacy_username:
                return JsonResponse({
                    'success': False,
                    'error': 'El número de documento es requerido'
                }, status=400)

            # Autenticar usuario
            # Flujo nuevo: buscar por numero_documento y luego autenticar con su email
            if numero_documento:
                try:
                    user_obj = User.objects.get(numero_documento=numero_documento)
                    user = authenticate(request, username=user_obj.email, password=password)
                except User.DoesNotExist:
                    user = None
            else:
                # Flujo legacy: el cliente envió email/username directamente
                user = authenticate(request, username=legacy_username, password=password)

            if user is not None:
                # Los admin/superusuarios omiten verificaciones de email y cuenta
                es_admin = user.rol == 'admin' or user.is_superuser

                # Verificar si el email está verificado (no aplica para admin)
                if not es_admin and not user.email_verificado:
                    return JsonResponse({
                        'success': False,
                        'error': 'Debes verificar tu email antes de iniciar sesión',
                        'requiere_verificacion': True,
                        'email': user.email
                    }, status=403)

                # Verificar el estado de la cuenta (reemplaza el check de cuenta_aprobada)
                if not es_admin:
                    estado = getattr(user, 'estado_cuenta', 'activa')
                    if estado != 'activa':
                        mensajes_estado = {
                            'pendiente_aprobacion': (
                                'Tu cuenta está pendiente de aprobación. '
                                'Te notificaremos cuando un administrador la revise.'
                            ),
                            'rechazada': (
                                'Tu cuenta fue rechazada. '
                                'Contacta al administrador si crees que es un error.'
                            ),
                            'suspendida': (
                                'Tu cuenta ha sido suspendida. '
                                'Contacta al administrador para más información.'
                            ),
                        }
                        return JsonResponse({
                            'success': False,
                            'error': mensajes_estado.get(estado, 'Tu cuenta no está activa'),
                            'codigo_error': f'CUENTA_{estado.upper()}',
                            'estado_cuenta': estado,
                        }, status=403)

                # Verificar si la cuenta está activa
                if not user.activo:
                    return JsonResponse({
                        'success': False,
                        'error': 'Tu cuenta ha sido desactivada. Contacta al administrador'
                    }, status=403)

                # Eliminar token anterior si existe y crear uno nuevo
                # Esto garantiza un token fresco con fecha de creación actualizada
                Token.objects.filter(user=user).delete()
                token = Token.objects.create(user=user)

                # Calcular expiración del token para informar al cliente
                token_lifetime = getattr(settings, 'TOKEN_EXPIRATION_HOURS', 24)
                expires_at = timezone.now() + timedelta(hours=token_lifetime)

                # Login exitoso
                return JsonResponse({
                    'success': True,
                    'token': token.key,  # Token seguro de 40 caracteres
                    'expires_at': expires_at.isoformat(),
                    'expires_in_hours': token_lifetime,
                    'user': {
                        'id': user.id,
                        'email': user.email,
                        'first_name': user.first_name,
                        'last_name': user.last_name,
                        'rol': user.rol,
                        'tipo_documento': user.tipo_documento,
                        'numero_documento': user.numero_documento,
                        'firma_digital': user.firma_digital.url if user.firma_digital else None,
                        'email_verificado': user.email_verificado,
                        'cuenta_aprobada': user.cuenta_aprobada,
                    }
                })
            else:
                # Credenciales incorrectas
                return JsonResponse({
                    'success': False,
                    'error': 'Credenciales incorrectas'
                }, status=401)
                
        except Exception as e:
            # Error del servidor
            return JsonResponse({
                'success': False,
                'error': handle_error(e, "Error durante el login")
            }, status=500)
    
    # Método no permitido
    return JsonResponse({
        'success': False,
        'error': 'Método no permitido'
    }, status=405)


@csrf_exempt
def logout_api(request):
    """
    API de logout para la app móvil Flutter.

    Elimina el token del usuario de la base de datos, invalidando la sesión.

    Header requerido:
        Authorization: Bearer <token>

    Retorna:
        - success: True si el logout fue exitoso
    """
    if request.method == 'POST':
        try:
            user, error_response = get_user_from_token(request)
            if error_response:
                return error_response

            # Eliminar el token del usuario
            Token.objects.filter(user=user).delete()

            return JsonResponse({
                'success': True,
                'message': 'Sesión cerrada exitosamente'
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': handle_error(e, "Error durante el logout")
            }, status=500)

    return JsonResponse({
        'success': False,
        'error': 'Método no permitido'
    }, status=405)


# ============================================
#  APIs de Registro y Verificación
# ============================================

@csrf_exempt
def register_api(request):
    """
    API de registro para nuevos usuarios.

    Recibe (multipart/form-data porque incluye archivo de imagen):
        - email            (obligatorio)
        - password         (obligatorio)
        - first_name       (obligatorio)
        - last_name        (obligatorio)
        - tipo_documento   (obligatorio: CC, TI, CE, PA, OTRO)
        - numero_documento (obligatorio, único en el sistema)
        - firma_digital    (obligatorio, archivo JPG/PNG/WEBP, máx 2MB)
        - ficha_id         (obligatorio solo si email termina en @soy.sena.edu.co)

    Flujo:
        1. Detecta automáticamente el rol por dominio del email
        2. Valida todos los campos y el archivo de firma
        3. Crea el usuario con rol, firma y ficha (si aplica)
        4. Envía email con código de verificación de 6 dígitos
        5. Retorna mensaje personalizado según el tipo de usuario
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    try:
        from .utils import detectar_rol_por_email, crear_codigo_verificacion, enviar_email_verificacion
        import re
        import os
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError as DjangoValidationError

        # ── Leer campos de texto (vienen en request.POST, no en JSON) ────────────
        # El endpoint ahora usa multipart/form-data para poder recibir el archivo de firma
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        tipo_documento = request.POST.get('tipo_documento', '').strip().upper()
        numero_documento = request.POST.get('numero_documento', '').strip()
        ficha_id = request.POST.get('ficha_id', '').strip()

        # ── Leer archivo de firma (viene en request.FILES) ───────────────────────
        firma = request.FILES.get('firma_digital')

        # ── Validaciones de campos de texto ──────────────────────────────────────
        if not email or not password or not first_name or not last_name:
            return JsonResponse({
                'success': False,
                'error': 'Email, contraseña, nombre y apellido son requeridos'
            }, status=400)

        if not tipo_documento or not numero_documento:
            return JsonResponse({
                'success': False,
                'error': 'El tipo y número de documento son obligatorios'
            }, status=400)

        tipos_validos = ['CC', 'TI', 'CE', 'PA', 'OTRO']
        if tipo_documento not in tipos_validos:
            return JsonResponse({
                'success': False,
                'error': f'Tipo de documento inválido. Los valores aceptados son: {", ".join(tipos_validos)}'
            }, status=400)

        # Solo letras, números y guiones (cubre pasaportes como "AB-123456")
        if not re.match(r'^[a-zA-Z0-9\-]+$', numero_documento):
            return JsonResponse({
                'success': False,
                'error': 'El número de documento solo puede contener letras, números y guiones'
            }, status=400)

        if User.objects.filter(numero_documento=numero_documento).exists():
            return JsonResponse({
                'success': False,
                'error': f'Ya existe un usuario registrado con el documento {numero_documento}'
            }, status=400)

        # ── Validar email ─────────────────────────────────────────────────────────
        try:
            validate_email(email)
        except DjangoValidationError:
            return JsonResponse({'success': False, 'error': 'Formato de email inválido'}, status=400)

        if User.objects.filter(email=email).exists():
            return JsonResponse({'success': False, 'error': 'Este email ya está registrado'}, status=400)

        # ── Detectar rol según dominio del email ──────────────────────────────────
        rol_detectado = detectar_rol_por_email(email)

        # ── Validar firma digital ─────────────────────────────────────────────────
        if not firma:
            return JsonResponse({
                'success': False,
                'error': 'La firma digital es obligatoria para el registro'
            }, status=400)

        # Verificar extensión del archivo (solo imágenes)
        extension = os.path.splitext(firma.name.lower())[1]
        extensiones_validas = ['.jpg', '.jpeg', '.png', '.webp']
        if extension not in extensiones_validas:
            return JsonResponse({
                'success': False,
                'error': 'La firma debe ser una imagen JPG, PNG o WEBP'
            }, status=400)

        # Verificar tamaño (máximo 2MB)
        TAMANO_MAX_FIRMA = 2 * 1024 * 1024  # 2MB en bytes
        if firma.size > TAMANO_MAX_FIRMA:
            return JsonResponse({
                'success': False,
                'error': 'La firma no puede superar 2MB de tamaño'
            }, status=400)

        # ── Validar ficha (obligatoria solo para aprendices) ──────────────────────
        ficha_obj = None
        if rol_detectado == 'aprendiz':
            if not ficha_id:
                return JsonResponse({
                    'success': False,
                    'error': 'Los aprendices deben seleccionar su ficha de formación'
                }, status=400)
            try:
                from formacion.models import Ficha
                ficha_obj = Ficha.objects.get(id=ficha_id, activa=True)
            except Ficha.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'La ficha seleccionada no existe o no está activa'
                }, status=400)
        # Si el usuario NO es aprendiz, ignoramos ficha_id aunque el cliente lo envíe

        # ── Crear usuario ─────────────────────────────────────────────────────────
        # El modelo save() se encarga de redimensionar la firma si es muy grande
        user = User.objects.create_user(
            username=numero_documento,  # username = numero_documento (identificador interno)
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            rol=rol_detectado,
            tipo_documento=tipo_documento,
            numero_documento=numero_documento,
            firma_digital=firma,
            ficha=ficha_obj,
            email_verificado=False,
            cuenta_aprobada=False,
            activo=True
        )

        # ── Enviar email de verificación ──────────────────────────────────────────
        codigo_obj = crear_codigo_verificacion(user, tipo='registro')
        email_enviado = enviar_email_verificacion(user, codigo_obj.codigo)

        if not email_enviado:
            user.delete()
            return JsonResponse({
                'success': False,
                'error': 'Error al enviar el email de verificación. Intenta de nuevo'
            }, status=500)

        # Mensaje personalizado según el tipo de usuario
        if rol_detectado == 'aprendiz':
            mensaje = 'Registro exitoso. Bienvenido al SENA. Revisa tu email para verificar tu cuenta.'
        elif rol_detectado == 'funcionario':
            mensaje = 'Registro exitoso. Tu cuenta está pendiente de aprobación por el administrador. Te notificaremos cuando esté activa.'
        else:
            mensaje = 'Registro exitoso. Revisa tu email para verificar tu cuenta.'

        return JsonResponse({
            'success': True,
            'message': mensaje,
            'user_id': user.id,
            'rol_asignado': rol_detectado,
            'email': email
        }, status=201)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e, "Error durante el registro")
        }, status=500)


@csrf_exempt
def verificar_codigo_api(request):
    """
    API para verificar el código de 6 dígitos enviado por email.

    Recibe:
        - email: Email del usuario
        - codigo: Código de 6 dígitos

    Flujo:
        1. Busca el código más reciente del usuario
        2. Verifica que no haya expirado (15 minutos)
        3. Verifica que el código coincida
        4. Marca el email como verificado
        5. Aprueba la cuenta automáticamente
        6. Marca el código como usado

    Retorna:
        - success: True/False
        - message: Mensaje descriptivo
        - token: Token de autenticación (si verificación exitosa)
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        from .utils import verificar_codigo, aprobar_usuario_automaticamente
        from accounts.models import CodigoVerificacion

        # Leer datos del request
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()
        codigo_ingresado = data.get('codigo', '').strip()

        if not email or not codigo_ingresado:
            return JsonResponse({
                'success': False,
                'error': 'Email y código son requeridos'
            }, status=400)

        # Buscar usuario
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Usuario no encontrado'
            }, status=404)

        # Verificar si ya está verificado
        if user.email_verificado and user.cuenta_aprobada:
            return JsonResponse({
                'success': False,
                'error': 'Tu cuenta ya está verificada. Puedes iniciar sesión'
            }, status=400)

        # Verificar el código
        es_valido, mensaje_error = verificar_codigo(user, codigo_ingresado, tipo='registro')

        if not es_valido:
            return JsonResponse({
                'success': False,
                'error': mensaje_error
            }, status=400)

        # Código válido: aprobar usuario automáticamente
        user = aprobar_usuario_automaticamente(user)

        # Marcar el código como usado
        codigo_obj = CodigoVerificacion.objects.filter(
            user=user,
            codigo=codigo_ingresado,
            tipo='registro',
            usado=False
        ).first()

        if codigo_obj:
            codigo_obj.marcar_usado()

        # Generar token de autenticación
        token, created = Token.objects.get_or_create(user=user)

        return JsonResponse({
            'success': True,
            'message': 'Email verificado exitosamente. Tu cuenta ha sido aprobada',
            'token': token.key,
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'rol': user.rol,
                'email_verificado': user.email_verificado,
                'cuenta_aprobada': user.cuenta_aprobada,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Formato de datos inválido'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e, "Error al verificar el código")
        }, status=500)


@csrf_exempt
def reenviar_codigo_api(request):
    """
    API para reenviar el código de verificación si expiró.

    Recibe:
        - email: Email del usuario

    Flujo:
        1. Busca el usuario
        2. Verifica que no esté ya verificado
        3. Genera nuevo código de 6 dígitos
        4. Envía email con el nuevo código

    Retorna:
        - success: True/False
        - message: Mensaje descriptivo
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        from .utils import crear_codigo_verificacion, enviar_email_verificacion

        # Leer datos del request
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()

        if not email:
            return JsonResponse({
                'success': False,
                'error': 'Email es requerido'
            }, status=400)

        # Buscar usuario
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Usuario no encontrado'
            }, status=404)

        # Verificar si ya está verificado
        if user.email_verificado and user.cuenta_aprobada:
            return JsonResponse({
                'success': False,
                'error': 'Tu cuenta ya está verificada. Puedes iniciar sesión'
            }, status=400)

        # Crear nuevo código de verificación
        codigo_obj = crear_codigo_verificacion(user, tipo='registro')

        # Enviar email con el nuevo código
        email_enviado = enviar_email_verificacion(user, codigo_obj.codigo)

        if not email_enviado:
            return JsonResponse({
                'success': False,
                'error': 'Error al enviar el email. Intenta de nuevo'
            }, status=500)

        return JsonResponse({
            'success': True,
            'message': 'Código reenviado exitosamente. Revisa tu email'
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Formato de datos inválido'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e, "Error al reenviar el código")
        }, status=500)


# ============================================
#  API de Dashboard
# ============================================
@csrf_exempt
def dashboard_api(request):
    """
    API para obtener estadísticas del dashboard

    Header requerido:
        Authorization: Bearer <token>

    Retorna estadísticas del usuario autenticado.
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario con token seguro
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response
        
        # Estadísticas
        total_actas = Acta.objects.filter(creador=user).count()
        
        # Firmas pendientes (donde el usuario es participante y no ha firmado)
        firmas_pendientes_count = Firma.objects.filter(
            usuario=user,
            firmado=False,
            acta__estado='en_revision'
        ).count()
        
        # Compromisos activos
        compromisos_activos = Compromiso.objects.filter(
            responsable=user,
            estado__in=['pendiente', 'en_progreso']
        ).count()
        
        # Compromisos vencidos
        compromisos_vencidos = Compromiso.objects.filter(
            responsable=user,
            estado='vencido'
        ).count()
        
        # Actas recientes (últimas 5)
        actas_recientes = Acta.objects.filter(
            creador=user
        ).order_by('-fecha_creacion')[:5]
        
        actas_recientes_data = [{
            'id': acta.id,
            'numero_acta': acta.numero_acta,
            'titulo': acta.titulo,
            'estado': acta.estado,
            'fecha_reunion': acta.fecha_reunion.isoformat(),
            'fecha_creacion': acta.fecha_creacion.isoformat(),
        } for acta in actas_recientes]
        
        # Firmas pendientes (lista completa)
        firmas_pendientes_lista = Firma.objects.filter(
            usuario=user,
            firmado=False,
            acta__estado='en_revision'
        ).select_related('acta')[:5]
        
        firmas_pendientes_data = [{
            'id': firma.id,
            'acta': {
                'id': firma.acta.id,
                'numero_acta': firma.acta.numero_acta,
                'titulo': firma.acta.titulo,
                'fecha_reunion': firma.acta.fecha_reunion.isoformat(),
            }
        } for firma in firmas_pendientes_lista]
        
        # Compromisos próximos
        compromisos_proximos = Compromiso.objects.filter(
            responsable=user,
            estado__in=['pendiente', 'en_progreso']
        ).order_by('fecha_limite')[:5]
        
        compromisos_proximos_data = [{
            'id': compromiso.id,
            'descripcion': compromiso.descripcion,
            'fecha_limite': compromiso.fecha_limite.isoformat(),
            'estado': compromiso.estado,
            'porcentaje_avance': compromiso.porcentaje_avance,
            'dias_restantes': compromiso.dias_restantes(),
            'acta': {
                'id': compromiso.acta.id,
                'numero_acta': compromiso.acta.numero_acta,
                'titulo': compromiso.acta.titulo,
                'fecha_reunion': compromiso.acta.fecha_reunion.isoformat(),
            }
        } for compromiso in compromisos_proximos]
        
        return JsonResponse({
            'success': True,
            'data': {
                'estadisticas': {
                    'total_actas': total_actas,
                    'firmas_pendientes': firmas_pendientes_count,
                    'compromisos_activos': compromisos_activos,
                    'compromisos_vencidos': compromisos_vencidos,
                },
                'actas_recientes': actas_recientes_data,
                'firmas_pendientes': firmas_pendientes_data,
                'compromisos_proximos': compromisos_proximos_data,
            }
        })
        
    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Usuario no encontrado'
        }, status=401)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)
        

@csrf_exempt
def actas_list_api(request):
    """
    API para listar actas del usuario
    Soporta filtros por estado y búsqueda
    Soporta paginación: ?page=1&limit=20
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener parámetros de filtro
        estado = request.GET.get('estado', None)  # borrador, en_revision, finalizada, archivada
        search = request.GET.get('search', None)  # búsqueda por título o número

        # Parámetros de paginación
        try:
            page = int(request.GET.get('page', 1))
            limit = int(request.GET.get('limit', 20))
            limit = min(limit, 100)  # Máximo 100 registros por página
        except ValueError:
            page = 1
            limit = 20

        # Query base - actas creadas por el usuario O donde es participante
        # Optimizado con select_related y prefetch_related para evitar N+1 queries
        actas = Acta.objects.filter(
            Q(creador=user) |  # Actas que creó
            Q(participantes__usuario=user)  # Actas donde es participante
        ).select_related(
            'creador'  # Evita N+1 en acceso a creador
        ).prefetch_related(
            'participantes',  # Prefetch participantes
            'participantes__usuario',  # Prefetch usuarios de participantes
            Prefetch('firmas', queryset=Firma.objects.select_related('usuario')),  # Prefetch firmas con usuario
        ).distinct()

        # Aplicar filtro de estado
        if estado and estado != 'todos':
            actas = actas.filter(estado=estado)

        # Aplicar búsqueda
        if search:
            actas = actas.filter(
                Q(titulo__icontains=search) |
                Q(numero_acta__icontains=search)
            )

        # Ordenar por fecha de creación (más recientes primero)
        actas = actas.order_by('-fecha_creacion')

        # Contar total antes de paginar
        total_count = actas.count()

        # Aplicar paginación
        start = (page - 1) * limit
        end = start + limit
        actas_paginadas = list(actas[start:end])  # Ejecutar query una sola vez

        # Serializar datos
        actas_data = []
        for acta in actas_paginadas:
            # Calcular estadísticas de firmas
            total_firmas = acta.participantes.count()
            firmas_completadas = acta.firmas.filter(firmado=True).count()
            porcentaje_firmas = (firmas_completadas / total_firmas * 100) if total_firmas > 0 else 0

            # Verificar rol del usuario en esta acta
            es_creador = acta.creador == user
            es_participante = acta.participantes.filter(usuario=user).exists()
            tiene_firma_pendiente = acta.firmas.filter(usuario=user, firmado=False).exists()

            actas_data.append({
                'id': acta.id,
                'numero_acta': acta.numero_acta,
                'titulo': acta.titulo,
                'tipo_reunion': acta.tipo_reunion,
                'estado': acta.estado,
                'fecha_reunion': acta.fecha_reunion.isoformat(),
                'fecha_creacion': acta.fecha_creacion.isoformat(),
                'lugar_reunion': acta.lugar_reunion,
                'modalidad': acta.modalidad,
                'generada_con_ia': acta.generada_con_ia,
                'creador': {
                    'id': acta.creador.id,
                    'nombre_completo': acta.creador.get_full_name(),
                },
                'usuario_rol': {
                    'es_creador': es_creador,
                    'es_participante': es_participante,
                    'tiene_firma_pendiente': tiene_firma_pendiente,
                },
                'estadisticas_firmas': {
                    'total': total_firmas,
                    'completadas': firmas_completadas,
                    'porcentaje': round(porcentaje_firmas, 1),
                }
            })

        # Calcular paginación
        total_pages = (total_count + limit - 1) // limit

        return JsonResponse({
            'success': True,
            'data': {
                'actas': actas_data,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_prev': page > 1,
                }
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)


@csrf_exempt
def acta_detalle_api(request, acta_id):
    """
    API para obtener el detalle completo de un acta
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener acta
        try:
            acta = Acta.objects.get(id=acta_id)
        except Acta.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Acta no encontrada'
            }, status=404)
        
        # Verificar permisos (debe ser creador o participante)
        es_creador = acta.creador == user
        es_participante = acta.participantes.filter(usuario=user).exists()
        
        if not (es_creador or es_participante):
            return JsonResponse({
                'success': False,
                'error': 'No tienes permiso para ver esta acta'
            }, status=403)
        
        # Obtener participantes
        participantes_data = []
        for participante in acta.participantes.all():
            # Buscar firma del participante
            firma = acta.firmas.filter(usuario=participante.usuario).first()
            
            participantes_data.append({
                'id': participante.id,
                'usuario': {
                    'id': participante.usuario.id,
                    'nombre_completo': participante.usuario.get_full_name(),
                    'email': participante.usuario.email,
                    'rol': participante.usuario.rol,
                },
                'rol_en_reunion': participante.rol_en_reunion,
                'obligatorio_firma': participante.obligatorio_firma,
                'firma': {
                    'firmado': firma.firmado if firma else False,
                    'fecha_firma': firma.fecha_firma.isoformat() if firma and firma.fecha_firma else None,
                    'tiene_firma': bool(firma),
                } if firma else None,
            })
        
        # Obtener compromisos
        compromisos_data = []
        for compromiso in acta.compromisos.all():
            compromisos_data.append({
                'id': compromiso.id,
                'descripcion': compromiso.descripcion,
                'responsable': {
                    'id': compromiso.responsable.id,
                    'nombre_completo': compromiso.responsable.get_full_name(),
                },
                'fecha_limite': compromiso.fecha_limite.isoformat(),
                'estado': compromiso.estado,
                'porcentaje_avance': compromiso.porcentaje_avance,
                'dias_restantes': compromiso.dias_restantes(),
                'observaciones': compromiso.observaciones,
            })
        
        # Calcular estadísticas
        total_firmas = acta.participantes.count()
        firmas_completadas = acta.firmas.filter(firmado=True).count()
        porcentaje_firmas = (firmas_completadas / total_firmas * 100) if total_firmas > 0 else 0
        
        # Datos del acta
        acta_data = {
            'id': acta.id,
            'numero_acta': acta.numero_acta,
            'titulo': acta.titulo,
            'tipo_reunion': acta.tipo_reunion,
            'estado': acta.estado,
            'fecha_reunion': acta.fecha_reunion.isoformat(),
            'fecha_creacion': acta.fecha_creacion.isoformat(),
            'fecha_modificacion': acta.fecha_modificacion.isoformat(),
            'lugar_reunion': acta.lugar_reunion,
            'modalidad': acta.modalidad,
            'orden_dia': acta.orden_dia,
            'desarrollo': acta.desarrollo,
            'observaciones': acta.observaciones,
            'generada_con_ia': acta.generada_con_ia,
            'prompt_original': acta.prompt_original if acta.generada_con_ia else None,
            'modelo_ia_usado': acta.modelo_ia_usado if acta.generada_con_ia else None,
            'fecha_limite_firmas': acta.fecha_limite_firmas.isoformat() if acta.fecha_limite_firmas else None,
            'silencio_administrativo': acta.silencio_administrativo,
            'puede_aplicar_silencio': acta.puede_aplicar_silencio_administrativo(),
            'creador': {
                'id': acta.creador.id,
                'nombre_completo': acta.creador.get_full_name(),
                'email': acta.creador.email,
                'rol': acta.creador.rol,
            },
            'participantes': participantes_data,
            'compromisos': compromisos_data,
            'estadisticas_firmas': {
                'total': total_firmas,
                'completadas': firmas_completadas,
                'porcentaje': round(porcentaje_firmas, 1),
            },
            'permisos_usuario': {
                'es_creador': es_creador,
                'es_participante': es_participante,
                'puede_editar': es_creador and acta.estado == 'borrador',
                'puede_firmar': es_participante and acta.estado == 'en_revision',
            }
        }
        
        return JsonResponse({
            'success': True,
            'data': acta_data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)



""" API para obtener y actualizar el perfil del usuario"""
@csrf_exempt
def perfil_api(request):

    # Autenticar usuario
    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        # GET - Obtener perfil
        if request.method == 'GET':
            user_data = {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'nombre_completo': user.get_full_name(),
                'rol': user.rol,
                'tipo_documento': user.tipo_documento,
                'numero_documento': user.numero_documento,
                'centro': user.centro,
                'telefono': user.telefono,
                'fecha_registro': user.date_joined.isoformat(),
                'ultimo_login': user.last_login.isoformat() if user.last_login else None,
                'firma_digital': user.firma_digital.url if user.firma_digital else None,
                'tiene_firma': bool(user.firma_digital),
                'email_verificado': user.email_verificado,
                'cuenta_aprobada': user.cuenta_aprobada,
                'activo': user.activo,
            }
            
            # Estadísticas del usuario
            stats = {
                'total_actas_creadas': Acta.objects.filter(creador=user).count(),
                'actas_en_borrador': Acta.objects.filter(creador=user, estado='borrador').count(),
                'actas_finalizadas': Acta.objects.filter(creador=user, estado='finalizada').count(),
                'compromisos_asignados': Compromiso.objects.filter(responsable=user).count(),
                'compromisos_completados': Compromiso.objects.filter(responsable=user, estado='completado').count(),
                'firmas_pendientes': Firma.objects.filter(usuario=user, firmado=False).count(),
            }
            
            return JsonResponse({
                'success': True,
                'data': {
                    'user': user_data,
                    'stats': stats,
                }
            })
        
        # PUT - Actualizar perfil
        elif request.method == 'PUT':
            data = json.loads(request.body)
            
            # Actualizar campos permitidos
            if 'first_name' in data:
                user.first_name = data['first_name']
            if 'last_name' in data:
                user.last_name = data['last_name']
            if 'email' in data:
                user.email = data['email']
            
            user.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Perfil actualizado correctamente',
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'rol': user.rol,
                    'tipo_documento': user.tipo_documento,
                    'numero_documento': user.numero_documento,
                }
            })
        
        else:
            return JsonResponse({
                'success': False,
                'error': 'Método no permitido'
            }, status=405)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)


@csrf_exempt
def cambiar_password_api(request):
    """
    API para cambiar la contraseña del usuario
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener datos del request
        data = json.loads(request.body)
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        if not current_password or not new_password:
            return JsonResponse({
                'success': False,
                'error': 'Faltan datos requeridos'
            }, status=400)
        
        # Verificar contraseña actual
        if not user.check_password(current_password):
            return JsonResponse({
                'success': False,
                'error': 'La contraseña actual es incorrecta'
            }, status=400)
        
        # Validar nueva contraseña
        password_errors = []

        if len(new_password) < 8:
            password_errors.append('La contraseña debe tener al menos 8 caracteres')

        if not any(char.isupper() for char in new_password):
            password_errors.append('La contraseña debe contener al menos una letra mayúscula')

        if not any(char.islower() for char in new_password):
            password_errors.append('La contraseña debe contener al menos una letra minúscula')

        if not any(char.isdigit() for char in new_password):
            password_errors.append('La contraseña debe contener al menos un número')

        if password_errors:
            return JsonResponse({
                'success': False,
                'error': 'Contraseña débil',
                'detalles': password_errors
            }, status=400)
        
        # Cambiar contraseña
        user.set_password(new_password)
        user.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Contraseña actualizada correctamente'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)


""""api para obtener la lista de usuarios para agregar participantes al acta"""
@csrf_exempt
def usuarios_list_api(request):
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Solo roles que crean actas pueden ver la lista de usuarios
        roles_permitidos = ['instructor', 'funcionario', 'coordinador', 'director', 'admin']
        if user.rol not in roles_permitidos:
            return JsonResponse({
                'success': False,
                'error': 'No tienes permiso para ver la lista de usuarios.'
            }, status=403)

        # Obtener todos los usuarios activos
        usuarios = User.objects.filter(is_active=True).order_by('first_name', 'last_name')

        usuarios_data = []
        for u in usuarios:
            usuarios_data.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'first_name': u.first_name,
                'last_name': u.last_name,
                'nombre_completo': u.get_full_name(),
                'rol': u.rol,
            })

        return JsonResponse({
            'success': True,
            'data': usuarios_data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)

@csrf_exempt
def crear_acta_api(request):
    """
    API para crear una nueva acta (manual o con IA)
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Validación de permisos: mismos roles que la vista web
        roles_permitidos = ['instructor', 'funcionario', 'coordinador', 'director', 'admin']

        rol_usuario = user.rol.lower() if user.rol else 'invitado'

        if rol_usuario not in roles_permitidos:
            logger.warning(
                f'Usuario {user.email} (rol: {rol_usuario}) intentó crear acta sin permisos'
            )
            return JsonResponse({
                'success': False,
                'error': 'No tienes permisos para crear actas. Solo funcionarios, coordinadores, directores y administradores pueden crear actas.',
                'codigo_error': 'PERMISOS_INSUFICIENTES',
                'rol_requerido': roles_permitidos,
                'rol_actual': rol_usuario
            }, status=403)

        logger.info(f'Usuario {user.email} (rol: {rol_usuario}) creando acta...')

        # Obtener datos del request
        data = json.loads(request.body)

        # Validar campos requeridos
        required_fields = ['titulo', 'fecha_reunion', 'lugar_reunion', 'tipo_reunion', 'modalidad']
        for field in required_fields:
            if field not in data or not data[field]:
                return JsonResponse({
                    'success': False,
                    'error': f'El campo {field} es requerido'
                }, status=400)
        
        # Crear acta
        acta = Acta.objects.create(
            titulo=data['titulo'],
            fecha_reunion=data['fecha_reunion'],
            lugar_reunion=data['lugar_reunion'],
            tipo_reunion=data['tipo_reunion'],
            modalidad=data['modalidad'],
            orden_dia=data.get('orden_dia', ''),
            desarrollo=data.get('desarrollo', ''),
            observaciones=data.get('observaciones', ''),
            creador=user,
            estado='borrador',
            generada_con_ia=data.get('generada_con_ia', False),
            prompt_original=data.get('prompt_original', ''),
            modelo_ia_usado=data.get('modelo_ia_usado', ''),
        )
        
        # Agregar participantes
        participantes_data = data.get('participantes', [])
        for participante_info in participantes_data:
            try:
                participante_usuario = User.objects.get(id=participante_info['usuario_id'])
                participante = Participante.objects.create(
                    acta=acta,
                    usuario=participante_usuario,
                    rol_en_reunion=participante_info.get('rol_en_reunion', ''),
                    obligatorio_firma=participante_info.get('obligatorio_firma', True),
                )
                
                # Crear registro de firma
                Firma.objects.create(
                    acta=acta,
                    usuario=participante_usuario,
                    firmado=False,
                )

                # Enviar notificación por email al participante que debe firmar
                try:
                    from .email_service import enviar_email_solicitud_firma
                    enviar_email_solicitud_firma(acta, participante_usuario)
                except Exception as e:
                    logger.warning(f'No se pudo enviar email de solicitud de firma a {participante_usuario.email}: {str(e)}')

            except User.DoesNotExist:
                continue

        # Procesar compromisos si vienen en el request
        compromisos_data = data.get('compromisos', [])
        compromisos_creados = []

        if compromisos_data and isinstance(compromisos_data, list):
            logger.info(f'Procesando {len(compromisos_data)} compromisos para acta {acta.numero_acta}')

            for comp_data in compromisos_data:
                try:
                    # Extraer datos del compromiso
                    descripcion = comp_data.get('descripcion', '').strip()
                    responsable_id = comp_data.get('responsable_id') or comp_data.get('responsable')
                    fecha_limite = comp_data.get('fecha_limite')

                    # Validar campos requeridos
                    if not descripcion:
                        logger.warning('Compromiso sin descripción, saltando...')
                        continue

                    if not responsable_id:
                        logger.warning('Compromiso sin responsable, saltando...')
                        continue

                    # Obtener usuario responsable
                    try:
                        if isinstance(responsable_id, int):
                            responsable = User.objects.get(id=responsable_id)
                        else:
                            # Puede ser email
                            responsable = User.objects.get(email=responsable_id)
                    except User.DoesNotExist:
                        logger.error(f'Usuario responsable no encontrado: {responsable_id}')
                        continue

                    # Parsear fecha_limite
                    if isinstance(fecha_limite, str):
                        try:
                            # Formato esperado: "YYYY-MM-DD" o "YYYY-MM-DD HH:MM:SS"
                            if 'T' in fecha_limite or ' ' in fecha_limite:
                                fecha_obj = datetime.fromisoformat(fecha_limite.replace('Z', ''))
                                fecha_limite_date = fecha_obj.date()
                            else:
                                fecha_obj = datetime.strptime(fecha_limite, '%Y-%m-%d')
                                fecha_limite_date = fecha_obj.date()
                        except Exception as e:
                            logger.warning(f'Error parseando fecha límite "{fecha_limite}": {str(e)}')
                            # Usar fecha por defecto (5 días desde ahora)
                            fecha_limite_date = datetime.now().date() + timedelta(days=5)
                    else:
                        # Si no es string, usar valor por defecto
                        fecha_limite_date = datetime.now().date() + timedelta(days=5)

                    # Crear compromiso
                    compromiso = Compromiso.objects.create(
                        acta=acta,
                        descripcion=descripcion,
                        responsable=responsable,
                        fecha_limite=fecha_limite_date,
                        estado='pendiente'
                    )

                    compromisos_creados.append({
                        'id': compromiso.id,
                        'descripcion': compromiso.descripcion,
                        'responsable': compromiso.responsable.get_full_name() or compromiso.responsable.email,
                        'responsable_id': compromiso.responsable.id,
                        'fecha_limite': compromiso.fecha_limite.isoformat() if compromiso.fecha_limite else None,
                        'estado': compromiso.estado
                    })

                    logger.info(f'Compromiso creado: {compromiso.descripcion[:50]}...')

                    # Opcional: Enviar email de notificación
                    try:
                        from .email_service import enviar_email_compromiso_asignado
                        enviar_email_compromiso_asignado(compromiso, responsable)
                    except Exception as e:
                        logger.warning(f'Error enviando email de compromiso: {str(e)}')

                except Exception as e:
                    logger.error(f'Error creando compromiso: {str(e)}', exc_info=True)
                    continue

            logger.info(f'{len(compromisos_creados)} compromisos creados exitosamente para acta {acta.numero_acta}')

        return JsonResponse({
            'success': True,
            'message': 'Acta creada correctamente',
            'data': {
                'acta_id': acta.id,
                'numero_acta': acta.numero_acta,
                'titulo': acta.titulo,
                'estado': acta.estado,
                'fecha_reunion': acta.fecha_reunion.isoformat() if hasattr(acta.fecha_reunion, 'isoformat') else str(acta.fecha_reunion),
                'compromisos_creados': compromisos_creados,
                'total_compromisos': len(compromisos_creados),
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)


@csrf_exempt
def generar_acta_ia_api(request):
    """
    API para generar contenido de acta usando IA (Groq)
    CORREGIDO: Ahora usa la misma función que Django Web (utils.py)
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener datos del request
        data = json.loads(request.body)
        prompt = data.get('prompt', '')
        tipo_acta = data.get('tipo_acta', 'reunion_general').strip()

        if not prompt:
            return JsonResponse({
                'success': False,
                'error': 'El prompt es requerido'
            }, status=400)

        # Validar tipo_acta contra los valores permitidos (fallback seguro)
        from actas.prompts import TIPOS_ACTA_DICT
        if tipo_acta not in TIPOS_ACTA_DICT:
            tipo_acta = 'reunion_general'

        # USAR LA MISMA FUNCIÓN QUE DJANGO WEB, con tipo_acta especializado
        try:
            from core.utils import generar_acta_con_ia

            # Esta función devuelve {"orden_dia": "...", "desarrollo": "..."}
            resultado = generar_acta_con_ia(prompt, user, tipo_acta=tipo_acta)

            return JsonResponse({
                'success': True,
                'data': {
                    'orden_dia': resultado['orden_dia'],
                    'desarrollo': resultado['desarrollo'],
                    'modelo_usado': 'llama-3.1-8b-instant',
                    'tipo_acta': tipo_acta,
                    'tipo_acta_label': TIPOS_ACTA_DICT.get(tipo_acta, 'Reunion General'),
                }
            })
            
        except ValueError as e:
            return JsonResponse({
                'success': False,
                'error': handle_error(e, 'Error de formato en respuesta de IA')
            }, status=500)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': handle_error(e, 'Error al generar contenido con IA')
            }, status=500)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)

@csrf_exempt
def actas_pendientes_firma_api(request):
    """
    API para obtener actas que el usuario debe firmar
    Soporta paginación: ?page=1&limit=20
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Parámetros de paginación
        try:
            page = int(request.GET.get('page', 1))
            limit = int(request.GET.get('limit', 20))
            limit = min(limit, 100)  # Máximo 100 registros por página
        except ValueError:
            page = 1
            limit = 20

        # Obtener firmas pendientes del usuario
        firmas_pendientes = Firma.objects.filter(
            usuario=user,
            firmado=False,
            acta__estado='en_revision'  # Solo actas en revisión
        ).select_related('acta', 'acta__creador').order_by('-acta__fecha_creacion')

        # Contar total antes de paginar
        total_count = firmas_pendientes.count()

        # Aplicar paginación
        start = (page - 1) * limit
        end = start + limit
        firmas_paginadas = firmas_pendientes[start:end]

        actas_data = []
        for firma in firmas_paginadas:
            acta = firma.acta

            # Contar cuántos han firmado
            total_participantes = Participante.objects.filter(acta=acta).count()
            firmados = Firma.objects.filter(acta=acta, firmado=True).count()

            actas_data.append({
                'firma_id': firma.id,
                'acta': {
                    'id': acta.id,
                    'numero_acta': acta.numero_acta,
                    'titulo': acta.titulo,
                    'fecha_reunion': acta.fecha_reunion.isoformat(),
                    'lugar_reunion': acta.lugar_reunion,
                    'tipo_reunion': acta.tipo_reunion,
                    'modalidad': acta.modalidad,
                    'estado': acta.estado,
                    'orden_dia': acta.orden_dia,
                    'desarrollo': acta.desarrollo,
                    'observaciones': acta.observaciones,
                    'creador': {
                        'nombre_completo': acta.creador.get_full_name(),
                        'username': acta.creador.username,
                    }
                },
                'firmas_completadas': f'{firmados}/{total_participantes}',
                'porcentaje_firmado': int((firmados / total_participantes) * 100) if total_participantes > 0 else 0,
            })

        # Calcular paginación
        total_pages = (total_count + limit - 1) // limit

        return JsonResponse({
            'success': True,
            'data': {
                'actas': actas_data,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_prev': page > 1,
                }
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)

@csrf_exempt
def firmar_acta_api(request):
    """
    API para firmar un acta
    Recibe la firma como imagen en base64
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)
    
    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener datos del request
        data = json.loads(request.body)
        firma_id = data.get('firma_id')
        firma_imagen_base64 = data.get('firma_imagen')  # Base64 de la imagen
        
        if not firma_id:
            return JsonResponse({
                'success': False,
                'error': 'ID de firma requerido'
            }, status=400)
        
        if not firma_imagen_base64:
            return JsonResponse({
                'success': False,
                'error': 'Imagen de firma requerida'
            }, status=400)
        
        # Obtener registro de firma
        try:
            firma = Firma.objects.get(id=firma_id, usuario=user)
        except Firma.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Firma no encontrada o no tienes permiso'
            }, status=404)
        
        # Verificar que el acta esté en estado 'en_revision'
        if firma.acta.estado != 'en_revision':
            return JsonResponse({
                'success': False,
                'error': 'El acta debe estar en revisión para poder firmarla.'
            }, status=400)

        # Verificar que no esté ya firmada
        if firma.firmado:
            return JsonResponse({
                'success': False,
                'error': 'Ya has firmado esta acta'
            }, status=400)
        
        # Guardar la imagen de firma
        import base64
        from django.core.files.base import ContentFile
        
        try:
            # Decodificar base64
            format, imgstr = firma_imagen_base64.split(';base64,')
            ext = format.split('/')[-1]
            
            # Crear archivo
            firma_file = ContentFile(base64.b64decode(imgstr), name=f'firma_{user.id}_{firma.id}.{ext}')
            
            # Guardar en el modelo
            firma.firma_imagen = firma_file
            firma.firma_datos = imgstr  # base64 puro, persiste en BD
            firma.firmado = True
            firma.fecha_firma = timezone.now()
            firma.save()
            
            # Verificar si todos han firmado para cambiar estado del acta
            acta = firma.acta
            total_firmas = Firma.objects.filter(acta=acta).count()
            firmas_completadas = Firma.objects.filter(acta=acta, firmado=True).count()
            
            if total_firmas == firmas_completadas:
                # Todos firmaron, cambiar estado a finalizada
                acta.estado = 'finalizada'
                acta.save()

                # Enviar notificación al creador de que el acta está completamente firmada
                try:
                    from .email_service import enviar_email_acta_firmada_completa
                    enviar_email_acta_firmada_completa(acta)
                except Exception as e:
                    logger.warning(f'No se pudo enviar email de acta firmada completa: {str(e)}')

                return JsonResponse({
                    'success': True,
                    'message': 'Firma guardada correctamente. El acta ha sido finalizada.',
                    'acta_finalizada': True
                })
            else:
                return JsonResponse({
                    'success': True,
                    'message': 'Firma guardada correctamente',
                    'acta_finalizada': False,
                    'firmas_completadas': f'{firmas_completadas}/{total_firmas}'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': handle_error(e, 'Error al procesar la imagen de firma')
            }, status=500)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)

@csrf_exempt
def cambiar_estado_acta_api(request, acta_id):
    """
    API para cambiar el estado de un acta
    Solo el creador puede cambiar el estado
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener acta
        try:
            acta = Acta.objects.get(id=acta_id)
        except Acta.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Acta no encontrada'
            }, status=404)
        
        # Verificar que sea el creador
        if acta.creador != user:
            return JsonResponse({
                'success': False,
                'error': 'No tienes permiso para cambiar el estado de esta acta'
            }, status=403)
        
        # Obtener nuevo estado del request
        data = json.loads(request.body)
        nuevo_estado = data.get('estado')
        
        estados_validos = ['borrador', 'en_revision', 'finalizada', 'archivada']
        if nuevo_estado not in estados_validos:
            return JsonResponse({
                'success': False,
                'error': 'Estado no válido'
            }, status=400)
        
        # Validaciones según el estado
        if nuevo_estado == 'en_revision':
            # Verificar que tenga participantes
            participantes_count = Participante.objects.filter(acta=acta).count()
            if participantes_count == 0:
                return JsonResponse({
                    'success': False,
                    'error': 'El acta debe tener al menos un participante para enviar a revisión'
                }, status=400)
        
        # Cambiar estado
        estado_anterior = acta.estado
        acta.estado = nuevo_estado
        acta.save()

        # Si cambia a 'en_revision', enviar notificaciones por email
        if nuevo_estado == 'en_revision':
            from notifications.models import Notification

            # Establecer fecha límite para firmas
            acta.fecha_limite_firmas = timezone.now() + timedelta(days=acta.aplicar_silencio_dias)
            acta.save()

            # Obtener todos los participantes
            participantes = acta.participantes.all()

            participantes_notificados = 0
            # Para cada participante, crear/recuperar firma y enviar email
            for participante in participantes:
                # Crear o recuperar objeto Firma
                firma, created = Firma.objects.get_or_create(
                    acta=acta,
                    usuario=participante.usuario,
                    defaults={'firmado': False}
                )

                # Crear notificación
                try:
                    Notification.objects.create(
                        usuario=participante.usuario,
                        tipo='firma_pendiente',
                        titulo='📝 Nueva acta pendiente de firma',
                        mensaje=f"Tienes pendiente firmar el acta '{acta.numero_acta} - {acta.titulo}'. Fecha límite: {acta.fecha_limite_firmas.strftime('%d/%m/%Y')}",
                        enlace=f'/actas/{acta.id}/',
                    )
                except Exception as e:
                    logger.warning(f'Error creando notificación para {participante.usuario.email}: {str(e)}')

                # Enviar email
                try:
                    from .email_service import enviar_email_solicitud_firma
                    resultado = enviar_email_solicitud_firma(acta, participante.usuario)
                    if resultado:
                        participantes_notificados += 1
                        logger.info(f'Email enviado a {participante.usuario.email}')
                except Exception as e:
                    logger.warning(f'Error enviando email a {participante.usuario.email}: {str(e)}')

            logger.info(f'Notificaciones enviadas para acta {acta.numero_acta}: {participantes_notificados} participantes')

        return JsonResponse({
            'success': True,
            'message': f'Estado cambiado de {estado_anterior} a {nuevo_estado}',
            'data': {
                'acta_id': acta.id,
                'numero_acta': acta.numero_acta,
                'estado_anterior': estado_anterior,
                'estado_nuevo': nuevo_estado,
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)


@csrf_exempt
def crear_compromiso_api(request):
    """
    API para crear un compromiso desde la app móvi.
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener datos del request
        data = json.loads(request.body)
        acta_id = data.get('acta_id')
        descripcion = data.get('descripcion')
        responsable_id = data.get('responsable_id')
        fecha_limite = data.get('fecha_limite')
        observaciones = data.get('observaciones', '')
        
        # Validaciones
        if not acta_id or not descripcion or not responsable_id or not fecha_limite:
            return JsonResponse({
                'success': False,
                'error': 'Faltan campos obligatorios (acta_id, descripcion, responsable_id, fecha_limite)'
            }, status=400)
        
        # Verificar que el acta existe
        try:
            acta = Acta.objects.get(id=acta_id)
        except Acta.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Acta no encontrada'
            }, status=404)
        
        # Verificar que el usuario tenga permiso (debe ser creador o participante)
        es_creador = acta.creador == user
        es_participante = Participante.objects.filter(acta=acta, usuario=user).exists()
        
        if not (es_creador or es_participante):
            return JsonResponse({
                'success': False,
                'error': 'No tienes permiso para agregar compromisos a esta acta'
            }, status=403)
        
        # Verificar que el responsable existe
        try:
            responsable = User.objects.get(id=responsable_id)
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Usuario responsable no encontrado'
            }, status=404)
        
        # Validar formato de fecha
        from datetime import datetime
        try:
            fecha_limite_obj = datetime.strptime(fecha_limite, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({
                'success': False,
                'error': 'Formato de fecha inválido. Use YYYY-MM-DD'
            }, status=400)
        
        # Validar que la fecha no sea en el pasado
        from datetime import date
        if fecha_limite_obj < date.today():
            return JsonResponse({
                'success': False,
                'error': 'La fecha límite no puede ser en el pasado'
            }, status=400)
        
        # Crear el compromiso
        compromiso = Compromiso.objects.create(
            acta=acta,
            descripcion=descripcion,
            responsable=responsable,
            fecha_limite=fecha_limite_obj,
            observaciones=observaciones,
            estado='pendiente',
            porcentaje_avance=0
        )

        # Enviar notificación por email al responsable
        try:
            from .email_service import enviar_email_compromiso_asignado
            enviar_email_compromiso_asignado(compromiso, responsable)
        except Exception as e:
            logger.warning(f'No se pudo enviar email de compromiso asignado: {str(e)}')

        return JsonResponse({
            'success': True,
            'message': 'Compromiso creado exitosamente',
            'data': {
                'id': compromiso.id,
                'descripcion': compromiso.descripcion,
                'responsable': {
                    'id': responsable.id,
                    'nombre_completo': responsable.get_full_name(),
                    'username': responsable.username,
                },
                'fecha_limite': compromiso.fecha_limite.isoformat(),
                'estado': compromiso.estado,
                'porcentaje_avance': compromiso.porcentaje_avance,
                'acta': {
                    'id': acta.id,
                    'numero_acta': acta.numero_acta,
                    'titulo': acta.titulo,
                }
            }
        })
        
    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Usuario no encontrado'
        }, status=401)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)
        
@csrf_exempt
def editar_acta_api(request, acta_id):
    """
    API para editar un acta (solo en estado borrador)
    Permite edición por creador y participantes
    Registra quién hizo los cambios
    """
    if request.method != 'PUT':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener el acta
        try:
            acta = Acta.objects.get(id=acta_id)
        except Acta.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Acta no encontrada'
            }, status=404)
        
        # Verificar que el acta esté en borrador
        if acta.estado != 'borrador':
            return JsonResponse({
                'success': False,
                'error': 'Solo se pueden editar actas en estado Borrador'
            }, status=403)
        
        # Verificar permisos: creador O participante
        es_creador = acta.creador == user
        es_participante = Participante.objects.filter(acta=acta, usuario=user).exists()
        
        if not (es_creador or es_participante):
            return JsonResponse({
                'success': False,
                'error': 'No tienes permiso para editar esta acta'
            }, status=403)
        
        # Obtener datos del request
        data = json.loads(request.body)
        
        # Registrar cambios (para auditoría)
        cambios_realizados = []
        
        # Actualizar campos básicos
        if 'titulo' in data and data['titulo'] != acta.titulo:
            cambios_realizados.append(f"Título: '{acta.titulo}' → '{data['titulo']}'")
            acta.titulo = data['titulo']
        
        if 'fecha_reunion' in data:
            nueva_fecha = datetime.fromisoformat(data['fecha_reunion'].replace('Z', '+00:00'))
            if nueva_fecha != acta.fecha_reunion:
                cambios_realizados.append(f"Fecha reunión cambiada")
                acta.fecha_reunion = nueva_fecha
        
        if 'lugar_reunion' in data and data['lugar_reunion'] != acta.lugar_reunion:
            cambios_realizados.append(f"Lugar: '{acta.lugar_reunion}' → '{data['lugar_reunion']}'")
            acta.lugar_reunion = data['lugar_reunion']
        
        if 'tipo_reunion' in data and data['tipo_reunion'] != acta.tipo_reunion:
            cambios_realizados.append(f"Tipo reunión cambiado")
            acta.tipo_reunion = data['tipo_reunion']
        
        if 'modalidad' in data and data['modalidad'] != acta.modalidad:
            cambios_realizados.append(f"Modalidad cambiada")
            acta.modalidad = data['modalidad']
        
        if 'orden_dia' in data and data['orden_dia'] != acta.orden_dia:
            cambios_realizados.append("Orden del día modificado")
            acta.orden_dia = data['orden_dia']
        
        if 'desarrollo' in data and data['desarrollo'] != acta.desarrollo:
            cambios_realizados.append("Desarrollo modificado")
            acta.desarrollo = data['desarrollo']
        
        if 'observaciones' in data and data['observaciones'] != acta.observaciones:
            cambios_realizados.append("Observaciones modificadas")
            acta.observaciones = data['observaciones']
        
        # Marcar como editada manualmente (si fue generada con IA)
        if acta.generada_con_ia and len(cambios_realizados) > 0:
            acta.editada_despues_ia = True
            acta.fecha_ultima_edicion_manual = timezone.now()
        
        # Guardar acta
        acta.save()
        
        # Actualizar participantes si se enviaron
        if 'participantes' in data:
            # Eliminar participantes actuales
            Participante.objects.filter(acta=acta).delete()
            
            # Agregar nuevos participantes
            for participante_data in data['participantes']:
                usuario_id = participante_data.get('usuario_id')
                rol = participante_data.get('rol_en_reunion', '')
                
                try:
                    usuario = User.objects.get(id=usuario_id)
                    Participante.objects.create(
                        acta=acta,
                        usuario=usuario,
                        rol_en_reunion=rol,
                        obligatorio_firma=True
                    )
                except User.DoesNotExist:
                    continue
            
            cambios_realizados.append("Participantes actualizados")
        
        # Crear comentario de auditoría con los cambios
        if cambios_realizados:
            from .models import ComentarioActa
            ComentarioActa.objects.create(
                acta=acta,
                autor=user,
                texto=f"[EDICIÓN] {user.get_full_name()} editó el acta:\n" + "\n".join(f"- {cambio}" for cambio in cambios_realizados)
            )
        
        return JsonResponse({
            'success': True,
            'message': 'Acta actualizada correctamente',
            'data': {
                'acta_id': acta.id,
                'numero_acta': acta.numero_acta,
                'cambios_realizados': cambios_realizados,
                'editado_por': user.get_full_name(),
            }
        })
        
    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Usuario no encontrado'
        }, status=401)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)
        
@csrf_exempt
def generar_pdf_api(request, acta_id):
    """
    API para generar y descargar PDF del acta
    Réplica de la función generar_pdf pero con autenticación por token
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener acta
        try:
            acta = Acta.objects.get(id=acta_id)
        except Acta.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Acta no encontrada'
            }, status=404)
        
        # Verificar permisos
        es_creador = acta.creador == user
        es_participante = Participante.objects.filter(acta=acta, usuario=user).exists()
        
        if not (es_creador or es_participante or user.is_staff):
            return JsonResponse({
                'success': False,
                'error': 'No tienes permiso para descargar esta acta'
            }, status=403)
        
        # ── Intento con plantilla Word ──────────────────────────────────────
        try:
            from actas.services.plantilla_service import generar_documento_desde_plantilla
            resultado = generar_documento_desde_plantilla(acta)
            if resultado:
                content_type = 'application/pdf' if resultado['tipo'] == 'pdf' else (
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                )
                resp = HttpResponse(resultado['bytes'], content_type=content_type)
                resp['Content-Disposition'] = f'attachment; filename="{resultado["nombre"]}"'
                return resp
        except Exception as _e:
            logger.error('generar_pdf_api: error con plantilla Word, usando ReportLab: %s', _e)
        # ── Fallback ReportLab ──────────────────────────────────────────────

        # === GENERAR PDF (mismo código que views.generar_pdf) ===
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from datetime import timedelta
        import os
        from django.conf import settings
        from django.http import HttpResponse

        # Crear PDF en buffer (para poder fusionar anexos después)
        import io as _io_pdf
        pdf_buffer = _io_pdf.BytesIO()

        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )
        
        styles = getSampleStyleSheet()
        story = []
        
        # Logo SENA (usar la ruta correcta que ya funciona)
        try:
            logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo-sena.png')
            if os.path.exists(logo_path):
                logo = Image(logo_path, width=1*inch, height=1*inch)
                story.append(logo)
        except:
            pass
        
        story.append(Spacer(1, 10))
        
        # ACTA No.
        acta_header = Table(
            [[Paragraph(f"<b>ACTA No. {acta.numero_acta}</b>", styles['Title'])]],
            colWidths=[7*inch]
        )
        acta_header.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, -1), colors.lightgrey),
        ]))
        story.append(acta_header)
        
        # NOMBRE DEL COMITÉ
        comite_table = Table(
            [
                [Paragraph("<b>NOMBRE DEL COMITÉ O DE LA REUNIÓN:</b>", styles['Normal'])],
                [Paragraph(acta.titulo, styles['Normal'])]
            ],
            colWidths=[7*inch],
            rowHeights=[0.3*inch, None]
        )
        comite_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(comite_table)
        
        # CIUDAD/FECHA y HORA
        fecha_str = acta.fecha_reunion.strftime("%d/%m/%Y")
        hora_inicio = acta.fecha_reunion.strftime("%H:%M")
        hora_fin = (acta.fecha_reunion + timedelta(hours=2)).strftime("%H:%M")
        
        info_table = Table(
            [
                [
                    Paragraph("<b>CIUDAD Y FECHA:</b>", styles['Normal']),
                    Paragraph(f"{acta.lugar_reunion}, {fecha_str}", styles['Normal']),
                    Paragraph("<b>HORA INICIO:</b>", styles['Normal']),
                    Paragraph(hora_inicio, styles['Normal']),
                    Paragraph("<b>HORA FIN:</b>", styles['Normal']),
                    Paragraph(hora_fin, styles['Normal']),
                ]
            ],
            colWidths=[1.2*inch, 2*inch, 1*inch, 0.8*inch, 1*inch, 1*inch]  # Total = 7 pulgadas
        )
        info_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(info_table)
        
        # LUGAR/ENLACE
        lugar_table = Table(
            [
                [
                    Paragraph("<b>LUGAR Y/O ENLACE:</b>", styles['Normal']),
                    Paragraph(acta.lugar_reunion, styles['Normal']),
                    Paragraph("<b>DIRECCIÓN / REGIONAL / CENTRO:</b>", styles['Normal']),
                    Paragraph("Centro Minero SENA", styles['Normal']),
                ]
            ],
            colWidths=[1.5*inch, 2*inch, 2*inch, 1.5*inch]
        )
        lugar_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(lugar_table)

        # AGENDA - minimizar espacio completamente
        agenda_content = acta.orden_dia if acta.orden_dia else "No especificada"

        # Crear estilo compacto sin espacios
        from reportlab.lib.styles import ParagraphStyle
        style_compacto = ParagraphStyle(
            'Compacto',
            parent=styles['Normal'],
            spaceAfter=0,
            spaceBefore=0,
            leftIndent=0,
            rightIndent=0,
        )

        # Si el contenido es muy corto, usar una sola fila compacta
        if len(agenda_content.strip()) < 50:
            agenda_table = Table(
                [
                    [Paragraph("<b>AGENDA O PUNTOS PARA DESARROLLAR:</b><br/>" + agenda_content.replace('\n', '<br/>'), style_compacto)]
                ],
                colWidths=[7*inch],
                rowHeights=[0.6*inch],
                splitByRow=1  # Altura fija muy pequeña
            )
        else:
            # Contenido largo: altura automática
            agenda_table = Table(
                [
                    [Paragraph("<b>AGENDA O PUNTOS PARA DESARROLLAR:</b>", styles['Normal'])],
                    [Paragraph(agenda_content.replace('\n', '<br/>'), styles['Normal'])]
                ],
                colWidths=[7*inch],
                splitByRow=1
            )

        agenda_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(agenda_table)
        
        # OBJETIVOS
        objetivo = f"Reunión de tipo {acta.get_tipo_reunion_display()}"
        if acta.generada_con_ia:
            objetivo += " (Generada con IA)"
        
        objetivo_table = Table(
            [
                [Paragraph("<b>OBJETIVO(S) DE LA REUNIÓN:</b>", styles['Normal'])],
                [Paragraph(objetivo, styles['Normal'])]
            ],
            colWidths=[7*inch],
            splitByRow=1
        )
        objetivo_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(objetivo_table)

        # DESARROLLO
        desarrollo_content = acta.desarrollo if acta.desarrollo else "No especificado"
        desarrollo_table = Table(
            [
                [Paragraph("<b>DESARROLLO DE LA REUNIÓN</b>", styles['Normal'])],
                [Paragraph(desarrollo_content.replace('\n', '<br/>'), styles['Normal'])]
            ],
            colWidths=[7*inch],
            splitByRow=1
        )
        desarrollo_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(desarrollo_table)

        # CONCLUSIONES
        conclusiones = acta.observaciones if acta.observaciones else "Sin observaciones adicionales"
        conclusiones_table = Table(
            [
                [Paragraph("<b>CONCLUSIONES</b>", styles['Normal'])],
                [Paragraph(conclusiones.replace('\n', '<br/>'), styles['Normal'])]
            ],
            colWidths=[7*inch]
        )
        conclusiones_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(conclusiones_table)

        # COMPROMISOS
        compromisos_data = [
            [
                Paragraph("<b>ACTIVIDAD/DECISIÓN</b>", styles['Normal']),
                Paragraph("<b>FECHA</b>", styles['Normal']),
                Paragraph("<b>RESPONSABLE</b>", styles['Normal']),
                Paragraph("<b>FIRMA</b>", styles['Normal']),
            ]
        ]
        
        if acta.compromisos.exists():
            for comp in acta.compromisos.all():
                compromisos_data.append([
                    Paragraph(comp.descripcion, styles['Normal']),
                    Paragraph(comp.fecha_limite.strftime("%d/%m/%Y"), styles['Normal']),
                    Paragraph(comp.responsable.get_full_name(), styles['Normal']),
                    Paragraph("", styles['Normal']),
                ])
        else:
            compromisos_data.append([
                Paragraph("No se registraron compromisos", styles['Normal']),
                "", "", ""
            ])
        
        compromisos_table = Table(compromisos_data, colWidths=[2.5*inch, 1.2*inch, 1.8*inch, 1.5*inch])
        compromisos_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(compromisos_table)

        # ASISTENTES
        story.append(Spacer(1, 10))

        asistentes_data = [
            [
                Paragraph("<b>NOMBRE</b>", styles['Normal']),
                Paragraph("<b>DEPENDENCIA/EMPRESA</b>", styles['Normal']),
                Paragraph("<b>APRUEBA (SI/NO)</b>", styles['Normal']),
                Paragraph("<b>FIRMA</b>", styles['Normal']),
            ]
        ]

        for participante in acta.participantes.select_related('usuario').all():
            firma_obj = acta.firmas.filter(usuario=participante.usuario).first()

            if firma_obj and firma_obj.firmado:
                # Intentar cargar la imagen de la firma
                firma_cell = None

                # OPCIÓN 1: Buscar en firma_imagen (archivo en disco)
                if firma_obj.firma_imagen:
                    try:
                        firma_path = os.path.join(settings.MEDIA_ROOT, str(firma_obj.firma_imagen))
                        if os.path.exists(firma_path):
                            firma_cell = Image(firma_path, width=1.5*inch, height=0.6*inch)
                    except Exception as e:
                        logger.warning('Error cargando firma_imagen en PDF API: %s', e)

                # OPCIÓN 2: Buscar en firma_datos (base64 en BD)
                if not firma_cell and firma_obj.firma_datos:
                    try:
                        import base64 as _b64, io as _io
                        firma_bytes = _b64.b64decode(firma_obj.firma_datos)
                        firma_cell = Image(_io.BytesIO(firma_bytes), width=1.5*inch, height=0.6*inch)
                    except Exception as e:
                        logger.warning('Error cargando firma desde base64 en PDF API: %s', e)

                # OPCIÓN 3: Buscar en firma_digital del usuario (archivo en disco)
                if not firma_cell and hasattr(participante.usuario, 'firma_digital') and participante.usuario.firma_digital:
                    try:
                        firma_path = os.path.join(settings.MEDIA_ROOT, str(participante.usuario.firma_digital))
                        if os.path.exists(firma_path):
                            firma_cell = Image(firma_path, width=1.5*inch, height=0.6*inch)
                    except Exception as e:
                        logger.warning('Error cargando firma_digital en PDF API: %s', e)

                # Si no se pudo cargar imagen, usar texto
                if not firma_cell:
                    firma_cell = Paragraph(
                        "✓ Firmado<br/><font size=6>({fecha})</font>".format(
                            fecha=firma_obj.fecha_firma.strftime("%d/%m/%Y") if firma_obj.fecha_firma else "N/A"
                        ),
                        styles['Normal']
                    )
            else:
                firma_cell = Paragraph("<font color='red'>Pendiente</font>", styles['Normal'])

            asistentes_data.append([
                Paragraph(participante.usuario.get_full_name(), styles['Normal']),
                Paragraph(participante.rol_en_reunion or "Participante", styles['Normal']),
                Paragraph("SÍ" if firma_obj and firma_obj.firmado else "NO", styles['Normal']),
                firma_cell
            ])

        asistentes_table = Table(asistentes_data, colWidths=[1.8*inch, 1.8*inch, 1.2*inch, 2.2*inch])
        asistentes_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(asistentes_table)
        
        # NOTA LEGAL
        story.append(Spacer(1, 10))
        nota_legal = Paragraph(
            "<font size=7>De acuerdo con La Ley 1581 de 2012, Protección de Datos Personales, el Servicio Nacional de Aprendizaje SENA, "
            "se compromete a garantizar la seguridad y protección de los datos personales que se encuentran almacenados en este "
            "documento, y les dará el tratamiento correspondiente en cumplimiento de lo establecido legalmente.</font>",
            styles['Normal']
        )
        story.append(nota_legal)
        
        # FOOTER
        story.append(Spacer(1, 20))
        footer_style = ParagraphStyle(
            'CenteredFooter',
            parent=styles['Normal'],
            alignment=TA_CENTER,
            fontSize=8,
        )
        footer = Paragraph("<b>GOR-F-084 V02</b>", footer_style)
        story.append(footer)

        # Construir PDF en buffer
        doc.build(story)
        acta_pdf_bytes = pdf_buffer.getvalue()

        # Fusionar con anexos PDF si los hay
        try:
            from actas.utils import fusionar_acta_con_anexos
            pdf_final = fusionar_acta_con_anexos(acta_pdf_bytes, acta)
        except Exception as e_merge:
            logger.error(f'Error al fusionar anexos del acta {acta_id}: {e_merge}')
            pdf_final = acta_pdf_bytes  # Fallback: solo el acta

        tiene_anexos = acta.anexos.exists()
        filename = f'ACTA_{acta.numero_acta}{"_con_anexos" if tiene_anexos else ""}.pdf'

        response = HttpResponse(pdf_final, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(pdf_final)
        return response

    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Usuario no encontrado'
        }, status=401)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)


@csrf_exempt
def mis_compromisos_api(request):
    """
    API para obtener los compromisos asignados al usuario autenticado
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener compromisos del usuario
        compromisos = Compromiso.objects.filter(
            responsable=user
        ).select_related('acta', 'responsable').order_by('-fecha_limite')
        
        # Serializar compromisos
        compromisos_data = []
        for comp in compromisos:
            compromisos_data.append({
                'id': comp.id,
                'descripcion': comp.descripcion,
                'fecha_limite': comp.fecha_limite.strftime('%Y-%m-%d'),
                'estado': comp.estado,
                'porcentaje_avance': comp.porcentaje_avance,
                'dias_restantes': comp.dias_restantes(),
                'observaciones': comp.observaciones,
                'reporte_cumplimiento': comp.reporte_cumplimiento,
                'acta': {
                    'id': comp.acta.id,
                    'numero_acta': comp.acta.numero_acta,
                    'titulo': comp.acta.titulo,
                },
                'responsable': {
                    'id': comp.responsable.id,
                    'nombre_completo': comp.responsable.get_full_name(),
                }
            })
        
        return JsonResponse({
            'success': True,
            'data': compromisos_data
        })
        
    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Usuario no encontrado'
        }, status=401)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)


@csrf_exempt
def actualizar_compromiso_api(request, compromiso_id):
    """
    API para actualizar el estado, porcentaje y reporte de un compromiso
    Solo el responsable puede actualizar
    """
    if request.method != 'PUT':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener compromiso
        try:
            compromiso = Compromiso.objects.get(id=compromiso_id)
        except Compromiso.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Compromiso no encontrado'
            }, status=404)
        
        # Verificar que el usuario es el responsable
        if compromiso.responsable != user:
            return JsonResponse({
                'success': False,
                'error': 'Solo el responsable puede actualizar este compromiso'
            }, status=403)
        
        # Obtener datos del request
        data = json.loads(request.body)

        # Actualizar campos
        estado = data.get('estado')
        porcentaje_avance = data.get('porcentaje_avance')
        reporte_cumplimiento = data.get('reporte_cumplimiento', '')

        # Validar estado
        estados_validos = ['pendiente', 'en_progreso', 'completado', 'vencido']
        if estado and estado not in estados_validos:
            return JsonResponse({
                'success': False,
                'error': f'Estado inválido. Debe ser: {", ".join(estados_validos)}'
            }, status=400)

        # Validar porcentaje
        if porcentaje_avance is not None:
            try:
                porcentaje_avance = int(porcentaje_avance)
                if porcentaje_avance < 0 or porcentaje_avance > 100:
                    return JsonResponse({
                        'success': False,
                        'error': 'El porcentaje debe estar entre 0 y 100'
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'error': 'Porcentaje inválido'
                }, status=400)

        # Guardar estado anterior para notificación
        estado_anterior = compromiso.get_estado_display() if hasattr(compromiso, 'get_estado_display') else compromiso.estado

        # Actualizar compromiso
        if estado:
            compromiso.estado = estado
        
        if porcentaje_avance is not None:
            compromiso.porcentaje_avance = porcentaje_avance
            
            # Si llega a 100%, marcar como completado
            if porcentaje_avance == 100:
                compromiso.estado = 'completado'
                compromiso.fecha_completado = timezone.now()
        
        if reporte_cumplimiento:
            compromiso.reporte_cumplimiento = reporte_cumplimiento

        compromiso.save()

        # Enviar notificación por email si hubo cambio de estado
        if estado and estado != estado_anterior:
            try:
                from .email_service import enviar_email_compromiso_actualizado
                # El usuario que actualiza es el responsable mismo
                enviar_email_compromiso_actualizado(compromiso, estado_anterior, user)
            except Exception as e:
                logger.warning(f'No se pudo enviar email de compromiso actualizado: {str(e)}')

        return JsonResponse({
            'success': True,
            'message': 'Compromiso actualizado exitosamente',
            'data': {
                'id': compromiso.id,
                'estado': compromiso.estado,
                'porcentaje_avance': compromiso.porcentaje_avance,
                'reporte_cumplimiento': compromiso.reporte_cumplimiento,
            }
        })
        
    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Usuario no encontrado'
        }, status=401)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)
        
@csrf_exempt
def aplicar_silencio_administrativo_api(request, acta_id):
    """
    API para aplicar silencio administrativo a un acta
    POST: Aplica silencio administrativo si cumple condiciones
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticar usuario (soporta token API y sesión web)
        user, error_response = get_user_from_token(request)
        if error_response:
            # Fallback a autenticación por sesión (para la web)
            if request.user and request.user.is_authenticated:
                user = request.user
            else:
                return error_response

        # Obtener el acta
        try:
            acta = Acta.objects.get(id=acta_id)
        except Acta.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Acta no encontrada'
            }, status=404)

        # Verificar que puede aplicar silencio
        if not acta.puede_aplicar_silencio_administrativo():
            # Dar razón específica
            if not acta.fecha_limite_firmas:
                razon = 'El acta no tiene fecha límite de firmas establecida'
            elif acta.estado != 'en_revision':
                razon = f'El acta debe estar en estado "En Revisión" (actual: {acta.get_estado_display()})'
            elif timezone.now() <= acta.fecha_limite_firmas:
                dias_restantes = (acta.fecha_limite_firmas - timezone.now()).days
                razon = f'Aún no ha vencido el plazo de firmas (faltan {dias_restantes} días)'
            elif not acta.firmas.filter(firmado=False).exists():
                razon = 'Todos los participantes ya han firmado el acta'
            else:
                razon = 'No se puede aplicar silencio administrativo'

            return JsonResponse({
                'success': False,
                'error': razon
            }, status=400)

        # Aplicar silencio administrativo
        acta.aplicar_silencio_admin()

        # Crear notificación para participantes
        from notifications.models import Notification
        participantes = acta.participantes.all()

        for participante in participantes:
            Notification.objects.create(
                usuario=participante.usuario,
                tipo='silencio_administrativo',
                titulo='Silencio Administrativo Aplicado',
                mensaje=f'Se ha aplicado silencio administrativo al Acta {acta.numero_acta} - {acta.titulo}',
                enlace=f'/actas/{acta.id}/',
                metadata={
                    'acta_id': acta.id,
                    'acta_numero': acta.numero_acta,
                }
            )

        return JsonResponse({
            'success': True,
            'message': 'Silencio administrativo aplicado exitosamente',
            'firmas_actualizadas': acta.firmas.filter(firmado_por_silencio=True).count(),
            'data': {
                'acta_id': acta.id,
                'numero_acta': acta.numero_acta,
                'estado': acta.estado,
                'silencio_administrativo': acta.silencio_administrativo,
                'firmas_aplicadas': acta.firmas.filter(firmado_por_silencio=True).count(),
            }
        })

    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Usuario no encontrado'
        }, status=401)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': handle_error(e)
        }, status=500)
        
@csrf_exempt
def register_api(request):
    """
    API para registro de nuevos usuarios
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)
    
    try:
        data = json.loads(request.body)
        
        # Obtener datos
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')
        rol = data.get('rol', 'aprendiz')
        telefono = data.get('telefono', '').strip()
        
        # Validaciones básicas
        if not all([first_name, last_name, email, password]):
            return JsonResponse({
                'success': False,
                'error': 'Todos los campos son obligatorios'
            }, status=400)
        
        # Validar email
        if not '@' in email:
            return JsonResponse({
                'success': False,
                'error': 'Email inválido'
            }, status=400)
        
        # Validar contraseña
        if len(password) < 8:
            return JsonResponse({
                'success': False,
                'error': 'La contraseña debe tener al menos 8 caracteres'
            }, status=400)
        
        # Validar que el email no exista
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'error': 'Este correo ya está registrado'
            }, status=400)
        
        # Validar rol
        roles_validos = ['aprendiz', 'instructor', 'funcionario', 'coordinador', 'director']
        if rol not in roles_validos:
            return JsonResponse({
                'success': False,
                'error': 'Rol inválido'
            }, status=400)
        
        # No permitir registro como admin
        if rol == 'admin':
            return JsonResponse({
                'success': False,
                'error': 'No puedes registrarte como Administrador'
            }, status=400)
        
        # Validar dominio de email según rol
        if rol == 'aprendiz':
            dominios_validos = ['@soy.sena.edu.co', '@gmail.com']
            if not any(email.endswith(d) for d in dominios_validos):
                return JsonResponse({
                    'success': False,
                    'error': 'El correo del aprendiz debe ser @soy.sena.edu.co o @gmail.com'
                }, status=400)
        elif rol in ['funcionario', 'coordinador', 'director', 'instructor']:
            dominios_validos = ['@sena.edu.co', '@gmail.com']
            if not any(email.endswith(d) for d in dominios_validos):
                return JsonResponse({
                    'success': False,
                    'error': 'El correo debe ser @sena.edu.co o @gmail.com'
                }, status=400)
        
        # Generar username único
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        # Crear usuario
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            rol=rol,
            telefono=telefono,
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Cuenta creada correctamente. Ahora puedes iniciar sesión.',
            'data': {
                'id': user.id,
                'email': user.email,
                'nombre_completo': user.get_full_name(),
                'rol': user.rol,
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Datos inválidos'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@csrf_exempt
def actualizar_firma_api(request):
    """
    API para actualizar firma digital del usuario
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)
    
    # Verificar autenticación
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return JsonResponse({
            'success': False,
            'error': 'No autenticado'
        }, status=401)
    
    token = auth_header.split(' ')[1]
    
    try:
        token_obj = Token.objects.get(key=token)
        user = token_obj.user
    except Token.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Token inválido'
        }, status=401)
    
    # Verificar que se envió una imagen
    if 'firma_digital' not in request.FILES:
        return JsonResponse({
            'success': False,
            'error': 'No se envió ninguna imagen'
        }, status=400)
    
    firma = request.FILES['firma_digital']
    
    # Validar tamaño (máximo 2 MB)
    if firma.size > 2 * 1024 * 1024:
        return JsonResponse({
            'success': False,
            'error': 'La imagen no debe superar los 2 MB'
        }, status=400)
    
    # Validar formato
    extensiones_permitidas = ['.png', '.jpg', '.jpeg']
    extension = os.path.splitext(firma.name)[1].lower()
    if extension not in extensiones_permitidas:
        return JsonResponse({
            'success': False,
            'error': 'Solo se permiten imágenes PNG, JPG o JPEG'
        }, status=400)
    
    try:
        # Eliminar firma anterior si existe
        if user.firma_digital:
            if os.path.isfile(user.firma_digital.path):
                os.remove(user.firma_digital.path)
        
        # Guardar nueva firma
        user.firma_digital = firma
        user.save()
        
        # URL completa de la firma
        firma_url = request.build_absolute_uri(user.firma_digital.url) if user.firma_digital else None
        
        return JsonResponse({
            'success': True,
            'message': 'Firma digital actualizada correctamente',
            'data': {
                'firma_digital': firma_url,
                'tiene_firma': True,
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al guardar firma: {str(e)}'
        }, status=500)
        
@csrf_exempt
def solicitar_codigo_recuperacion_api(request):
    """
    API para solicitar código de recuperación de contraseña
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)
    
    try:
        data = json.loads(request.body)
        email = data.get('email', '').lower().strip()
        
        if not email:
            return JsonResponse({
                'success': False,
                'error': 'Email es requerido'
            }, status=400)
        
        # Buscar usuario
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Por seguridad, no revelar si el email existe o no
            return JsonResponse({
                'success': True,
                'message': 'Si el correo existe, recibirás un código de recuperación'
            })
        
        # Generar código de 6 dígitos
        import random
        code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        
        # Crear registro de código (expira en 15 minutos)
        from datetime import timedelta
        from accounts.models import PasswordResetCode
        
        reset_code = PasswordResetCode.objects.create(
            user=user,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=15)
        )
        
        # Enviar email
        from django.core.mail import send_mail
        from django.conf import settings
        
        subject = 'Código de Recuperación - Sistema Actas SENA'
        message = f"""
Hola {user.get_full_name()},

Has solicitado recuperar tu contraseña en el Sistema de Gestión de Actas SENA.

Tu código de recuperación es:

    {code}

Este código expira en 15 minutos.

Si no solicitaste este código, ignora este mensaje.

---
Sistema de Gestión de Actas
SENA Centro Minero
        """
        
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Código de recuperación enviado al correo'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Datos inválidos'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al enviar código: {str(e)}'
        }, status=500)


@csrf_exempt
def verificar_codigo_recuperacion_api(request):
    """
    API para verificar código de recuperación
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)
    
    try:
        data = json.loads(request.body)
        email = data.get('email', '').lower().strip()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return JsonResponse({
                'success': False,
                'error': 'Email y código son requeridos'
            }, status=400)
        
        # Buscar usuario
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Código inválido o expirado'
            }, status=400)
        
        # Buscar código válido
        from accounts.models import PasswordResetCode
        
        try:
            reset_code = PasswordResetCode.objects.filter(
                user=user,
                code=code,
                used=False
            ).latest('created_at')
            
            if not reset_code.is_valid():
                return JsonResponse({
                    'success': False,
                    'error': 'Código expirado. Solicita uno nuevo.'
                }, status=400)
            
            return JsonResponse({
                'success': True,
                'message': 'Código verificado correctamente'
            })
            
        except PasswordResetCode.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Código inválido o expirado'
            }, status=400)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Datos inválidos'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al verificar código: {str(e)}'
        }, status=500)


@csrf_exempt
def resetear_password_api(request):
    """
    API para establecer nueva contraseña con código de recuperación
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)
    
    try:
        data = json.loads(request.body)
        email = data.get('email', '').lower().strip()
        code = data.get('code', '').strip()
        new_password = data.get('new_password', '')
        
        if not email or not code or not new_password:
            return JsonResponse({
                'success': False,
                'error': 'Email, código y nueva contraseña son requeridos'
            }, status=400)
        
        # Validar contraseña
        if len(new_password) < 8:
            return JsonResponse({
                'success': False,
                'error': 'La contraseña debe tener al menos 8 caracteres'
            }, status=400)
        
        # Buscar usuario
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Código inválido o expirado'
            }, status=400)
        
        # Buscar código válido
        from accounts.models import PasswordResetCode
        
        try:
            reset_code = PasswordResetCode.objects.filter(
                user=user,
                code=code,
                used=False
            ).latest('created_at')
            
            if not reset_code.is_valid():
                return JsonResponse({
                    'success': False,
                    'error': 'Código expirado. Solicita uno nuevo.'
                }, status=400)
            
            # Cambiar contraseña
            user.set_password(new_password)
            user.save()
            
            # Marcar código como usado
            reset_code.used = True
            reset_code.save()
            
            # Invalidar todos los otros códigos del usuario
            PasswordResetCode.objects.filter(
                user=user,
                used=False
            ).exclude(id=reset_code.id).update(used=True)
            
            return JsonResponse({
                'success': True,
                'message': 'Contraseña actualizada correctamente'
            })
            
        except PasswordResetCode.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Código inválido o expirado'
            }, status=400)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Datos inválidos'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al resetear contraseña: {str(e)}'
        }, status=500)
        
@csrf_exempt
def firmas_pendientes_api(request):
    """
    API para obtener lista completa de actas pendientes de firma
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    # Autenticar usuario
    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        # Obtener firmas pendientes del usuario
        firmas_pendientes = Firma.objects.filter(
            usuario=user,
            firmado=False,
            acta__estado='en_revision'
        ).select_related('acta', 'acta__creador').order_by('-acta__fecha_creacion')
        
        # Construir respuesta con información completa
        firmas_data = []
        for firma in firmas_pendientes:
            acta = firma.acta
            
            # Calcular estadísticas de firmas del acta
            total_firmas = acta.participantes.count()
            firmas_completadas = acta.firmas.filter(firmado=True).count()
            porcentaje_firmado = round((firmas_completadas / total_firmas * 100), 1) if total_firmas > 0 else 0
            
            firmas_data.append({
                'firma_id': firma.id,  # ← Cambiado de 'id' a 'firma_id'
                'acta': {
                    'id': acta.id,
                    'numero_acta': acta.numero_acta,
                    'titulo': acta.titulo,
                    'fecha_reunion': acta.fecha_reunion.isoformat(),
                    'lugar_reunion': acta.lugar_reunion,
                    'tipo_reunion': acta.tipo_reunion,  # ← Agregado
                    'modalidad': acta.modalidad,  # ← Agregado
                    'estado': acta.estado,
                    'orden_dia': acta.orden_dia or '',  # ← Agregado
                    'desarrollo': acta.desarrollo or '',  # ← Agregado
                    'observaciones': acta.observaciones or '',  # ← Agregado
                    'creador': {
                        'id': acta.creador.id,
                        'nombre_completo': acta.creador.get_full_name(),
                        'username': acta.creador.username,  # ← Agregado
                        'email': acta.creador.email,
                    }
                },
                'firmas_completadas': f"{firmas_completadas}/{total_firmas}",
                'porcentaje_firmado': int(porcentaje_firmado),  # ← Convertir a int
            })
        
        return JsonResponse({
            'success': True,
            'data': firmas_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al cargar firmas pendientes: {str(e)}'
        }, status=500)
    
@csrf_exempt
def exportar_datos_usuario_api(request):
    """
    API para exportar todos los datos del usuario actual
    Genera un archivo ZIP con:
    - Perfil del usuario (JSON)
    - Actas creadas por el usuario (JSON)
    - Compromisos asignados (JSON)
    - Firmas realizadas (JSON)
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    # Autenticar usuario
    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        import zipfile
        import tempfile
        from django.http import FileResponse
        
        # Crear archivo temporal
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        
        with zipfile.ZipFile(temp_file.name, 'w') as backup_zip:
            # 1. Perfil del usuario
            perfil_data = {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'rol': user.rol,
                'telefono': user.telefono,
                'fecha_exportacion': timezone.now().isoformat(),
            }
            backup_zip.writestr('perfil.json', json.dumps(perfil_data, indent=2, ensure_ascii=False))
            
            # 2. Actas creadas por el usuario
            actas = Acta.objects.filter(creador=user)
            actas_data = []
            for acta in actas:
                actas_data.append({
                    'id': acta.id,
                    'numero_acta': acta.numero_acta,
                    'titulo': acta.titulo,
                    'fecha_reunion': acta.fecha_reunion.isoformat(),
                    'lugar_reunion': acta.lugar_reunion,
                    'tipo_reunion': acta.tipo_reunion,
                    'modalidad': acta.modalidad,
                    'orden_dia': acta.orden_dia,
                    'desarrollo': acta.desarrollo,
                    'observaciones': acta.observaciones,
                    'estado': acta.estado,
                    'fecha_creacion': acta.fecha_creacion.isoformat(),
                })
            backup_zip.writestr('actas.json', json.dumps(actas_data, indent=2, ensure_ascii=False))
            
            # 3. Compromisos donde es responsable
            compromisos = Compromiso.objects.filter(responsable=user)
            compromisos_data = []
            for compromiso in compromisos:
                compromisos_data.append({
                    'id': compromiso.id,
                    'descripcion': compromiso.descripcion,
                    'fecha_limite': compromiso.fecha_limite.isoformat(),
                    'estado': compromiso.estado,
                    'porcentaje_avance': compromiso.porcentaje_avance,
                    'acta_numero': compromiso.acta.numero_acta,
                    'fecha_completado': compromiso.fecha_completado.isoformat() if compromiso.fecha_completado else None,
                    'observaciones': compromiso.observaciones,
                })
            backup_zip.writestr('compromisos.json', json.dumps(compromisos_data, indent=2, ensure_ascii=False))
            
            # 4. Firmas realizadas
            firmas = Firma.objects.filter(usuario=user, firmado=True)
            firmas_data = []
            for firma in firmas:
                firmas_data.append({
                    'acta_numero': firma.acta.numero_acta,
                    'acta_titulo': firma.acta.titulo,
                    'fecha_firma': firma.fecha_firma.isoformat() if firma.fecha_firma else None,
                })
            backup_zip.writestr('firmas.json', json.dumps(firmas_data, indent=2, ensure_ascii=False))
            
            # 5. README con información
            readme = f"""
EXPORTACIÓN DE DATOS PERSONALES
Sistema de Gestión de Actas SENA

Usuario: {user.get_full_name()}
Email: {user.email}
Fecha de exportación: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}

Contenido:
- perfil.json: Información de tu perfil
- actas.json: {actas.count()} acta(s) creada(s) por ti
- compromisos.json: {compromisos.count()} compromiso(s) asignado(s)
- firmas.json: {firmas.count()} firma(s) realizada(s)

Para importar estos datos:
1. Ve a tu perfil en la aplicación
2. Click en "Importar mis datos"
3. Selecciona este archivo ZIP

Nota: Solo puedes importar tus propios datos.
            """
            backup_zip.writestr('README.txt', readme)
        
        # Leer el contenido del archivo
        temp_file.close()
        with open(temp_file.name, 'rb') as f:
            file_content = f.read()

        # Eliminar archivo temporal
        try:
            os.unlink(temp_file.name)
        except:
            pass

        # Nombre del archivo
        filename = f'backup_{user.username}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.zip'

        # Crear respuesta HTTP con el contenido
        from django.http import HttpResponse
        response = HttpResponse(file_content, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(file_content)
        response['Access-Control-Expose-Headers'] = 'Content-Disposition'

        return response
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al exportar datos: {str(e)}'
        }, status=500)

@csrf_exempt
def importar_datos_usuario_api(request):
    """
    API para importar datos del usuario desde un archivo ZIP
    Valida que solo se importen datos del mismo usuario
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    # Autenticar usuario
    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        import zipfile
        import tempfile
        
        # Obtener archivo del request
        if 'backup_file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'No se proporcionó ningún archivo'
            }, status=400)
        
        backup_file = request.FILES['backup_file']
        
        # Validar extensión
        if not backup_file.name.endswith('.zip'):
            return JsonResponse({
                'success': False,
                'error': 'El archivo debe ser un ZIP'
            }, status=400)
        
        # Validar tamaño (máximo 10 MB)
        if backup_file.size > 10 * 1024 * 1024:
            return JsonResponse({
                'success': False,
                'error': 'El archivo es demasiado grande (máximo 10 MB)'
            }, status=400)
        
        # Guardar temporalmente
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        for chunk in backup_file.chunks():
            temp_file.write(chunk)
        temp_file.close()
        
        # Leer contenido del ZIP
        with zipfile.ZipFile(temp_file.name, 'r') as backup_zip:
            # Verificar archivos esperados
            expected_files = ['perfil.json', 'actas.json', 'compromisos.json', 'firmas.json']
            zip_files = backup_zip.namelist()
            
            for expected in expected_files:
                if expected not in zip_files:
                    os.unlink(temp_file.name)
                    return JsonResponse({
                        'success': False,
                        'error': f'Archivo ZIP inválido: falta {expected}'
                    }, status=400)
            
            # Leer perfil
            perfil_content = backup_zip.read('perfil.json')
            perfil_data = json.loads(perfil_content)
            
            # Validar que el backup es del mismo usuario
            if perfil_data['email'] != user.email:
                os.unlink(temp_file.name)
                return JsonResponse({
                    'success': False,
                    'error': 'Este backup pertenece a otro usuario. Solo puedes importar tus propios datos.'
                }, status=403)
            
            # Leer actas
            actas_content = backup_zip.read('actas.json')
            actas_data = json.loads(actas_content)
            
            # Leer compromisos
            compromisos_content = backup_zip.read('compromisos.json')
            compromisos_data = json.loads(compromisos_content)
        
        # Eliminar archivo temporal
        os.unlink(temp_file.name)
        
        # Estadísticas de importación
        stats = {
            'actas_en_backup': len(actas_data),
            'compromisos_en_backup': len(compromisos_data),
            'actas_actuales': Acta.objects.filter(creador=user).count(),
            'compromisos_actuales': Compromiso.objects.filter(responsable=user).count(),
        }
        
        return JsonResponse({
            'success': True,
            'message': 'Backup validado correctamente',
            'stats': stats,
            'advertencia': 'IMPORTANTE: La importación sobrescribirá tus datos actuales. ¿Deseas continuar?'
        })
        
    except zipfile.BadZipFile:
        return JsonResponse({
            'success': False,
            'error': 'Archivo ZIP corrupto o inválido'
        }, status=400)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Datos JSON inválidos en el backup'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al importar datos: {str(e)}'
        }, status=500)


@csrf_exempt
def confirmar_importacion_datos_api(request):
    """
    API para confirmar y ejecutar la importación de datos
    Este endpoint ejecuta la restauración real de los datos
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    # Autenticar usuario
    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        import zipfile
        import tempfile
        from django.db import transaction
        
        # Obtener archivo del request
        if 'backup_file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'No se proporcionó ningún archivo'
            }, status=400)
        
        backup_file = request.FILES['backup_file']
        
        # Guardar temporalmente
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        for chunk in backup_file.chunks():
            temp_file.write(chunk)
        temp_file.close()
        
        # Ejecutar importación en una transacción
        with transaction.atomic():
            with zipfile.ZipFile(temp_file.name, 'r') as backup_zip:
                # Leer datos
                actas_content = backup_zip.read('actas.json')
                actas_data = json.loads(actas_content)
                
                compromisos_content = backup_zip.read('compromisos.json')
                compromisos_data = json.loads(compromisos_content)
                
                # Eliminar actas actuales del usuario
                Acta.objects.filter(creador=user).delete()
                
                # Restaurar actas
                actas_restauradas = 0
                for acta_data in actas_data:
                    try:
                        Acta.objects.create(
                            creador=user,
                            numero_acta=acta_data['numero_acta'],
                            titulo=acta_data['titulo'],
                            fecha_reunion=datetime.fromisoformat(acta_data['fecha_reunion']),
                            lugar_reunion=acta_data['lugar_reunion'],
                            tipo_reunion=acta_data['tipo_reunion'],
                            modalidad=acta_data['modalidad'],
                            orden_dia=acta_data['orden_dia'],
                            desarrollo=acta_data['desarrollo'],
                            observaciones=acta_data['observaciones'],
                            estado=acta_data['estado'],
                        )
                        actas_restauradas += 1
                    except Exception as e:
                        # Si falla una acta, continuar con las demás
                        continue
        
        # Eliminar archivo temporal
        os.unlink(temp_file.name)
        
        return JsonResponse({
            'success': True,
            'message': 'Datos importados correctamente',
            'stats': {
                'actas_restauradas': actas_restauradas,
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al importar datos: {str(e)}'
        }, status=500)

# ============================================
# ENDPOINTS DE BACKUP GENERAL PARA ADMINISTRADOR
# Agregar estas funciones al final de actas/api_views.py
# ============================================

import subprocess
from pathlib import Path
from django.core.management import call_command
from io import StringIO

# ============================================
# 1. LISTAR BACKUPS DISPONIBLES
# ============================================
@csrf_exempt
def listar_backups_api(request):
    """
    Lista todos los backups disponibles en el servidor.
    Solo accesible para administradores.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        # Autenticar y verificar que sea admin
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response
        
        # Verificar que sea administrador
        if not user.is_staff and not user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No tienes permisos de administrador'
            }, status=403)
        
        # Obtener carpeta de backups
        backup_dir = Path(settings.BASE_DIR) / 'backups'
        
        if not backup_dir.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            return JsonResponse({
                'success': True,
                'backups': [],
                'message': 'No hay backups disponibles'
            })
        
        # Listar archivos .sql.gz
        backups = []
        for backup_file in backup_dir.glob('*.sql.gz'):
            stat = backup_file.stat()
            backups.append({
                'filename': backup_file.name,
                'size': round(stat.st_size / (1024 * 1024), 2),  # MB
                'created': datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
                'timestamp': stat.st_ctime,
            })
        
        # Ordenar por fecha (más reciente primero)
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return JsonResponse({
            'success': True,
            'backups': backups,
            'total': len(backups)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al listar backups: {str(e)}'
        }, status=500)


# ============================================
# 2. CREAR NUEVO BACKUP
# ============================================
@csrf_exempt
def crear_backup_api(request):
    """
    Crea un nuevo backup de la base de datos.
    Solo accesible para administradores.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        # Autenticar y verificar que sea admin
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response
        
        # Verificar que sea administrador
        if not user.is_staff and not user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No tienes permisos de administrador'
            }, status=403)
        
        # Ejecutar comando de backup
        out = StringIO()
        call_command('backup_database', stdout=out)
        output = out.getvalue()
        
        # Extraer nombre del archivo y tamaño del output
        lines = output.strip().split('\n')
        filename = None
        size = None
        
        for line in lines:
            if 'Archivo:' in line:
                filename = line.split('Archivo:')[1].strip()
            elif 'Tamaño:' in line:
                size = line.split('Tamaño:')[1].strip()
        
        if filename:
            return JsonResponse({
                'success': True,
                'message': 'Backup creado exitosamente',
                'filename': filename,
                'size': size
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No se pudo crear el backup'
            }, status=500)
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al crear backup: {str(e)}'
        }, status=500)


# ============================================
# 3. DESCARGAR BACKUP
# ============================================
@csrf_exempt
def descargar_backup_api(request, filename):
    """
    Descarga un archivo de backup específico.
    Solo accesible para administradores.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        # Autenticar y verificar que sea admin
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response
        
        # Verificar que sea administrador
        if not user.is_staff and not user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No tienes permisos de administrador'
            }, status=403)
        
        # Verificar que el archivo existe
        backup_dir = Path(settings.BASE_DIR) / 'backups'
        backup_file = backup_dir / filename
        
        if not backup_file.exists() or not backup_file.is_file():
            return JsonResponse({
                'success': False,
                'error': 'Archivo de backup no encontrado'
            }, status=404)
        
        # Verificar que sea un archivo .sql.gz
        if not filename.endswith('.sql.gz'):
            return JsonResponse({
                'success': False,
                'error': 'Tipo de archivo no válido'
            }, status=400)
        
        # Enviar archivo
        response = FileResponse(
            open(backup_file, 'rb'),
            content_type='application/gzip'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al descargar backup: {str(e)}'
        }, status=500)


# ============================================
# 4. RESTAURAR BACKUP
# ============================================
@csrf_exempt
def restaurar_backup_api(request):
    """
    Restaura la base de datos desde un backup.
    Solo accesible para administradores.
    ADVERTENCIA: Esta operación es DESTRUCTIVA.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        # Autenticar y verificar que sea admin
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response
        
        # Verificar que sea administrador
        if not user.is_staff and not user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No tienes permisos de administrador'
            }, status=403)
        
        # Obtener nombre del archivo
        data = json.loads(request.body)
        filename = data.get('filename')
        confirmacion = data.get('confirmacion', '')  # Usuario debe escribir "RESTAURAR"
        
        if not filename:
            return JsonResponse({
                'success': False,
                'error': 'Nombre de archivo no proporcionado'
            }, status=400)
        
        # Verificar confirmación
        if confirmacion != 'RESTAURAR':
            return JsonResponse({
                'success': False,
                'error': 'Debes escribir "RESTAURAR" para confirmar esta acción destructiva'
            }, status=400)
        
        # Verificar que el archivo existe
        backup_dir = Path(settings.BASE_DIR) / 'backups'
        backup_file = backup_dir / filename
        
        if not backup_file.exists():
            return JsonResponse({
                'success': False,
                'error': 'Archivo de backup no encontrado'
            }, status=404)
        
        # Ejecutar comando de restore
        out = StringIO()
        try:
            call_command('restore_database', str(backup_file), stdout=out)
            output = out.getvalue()
            
            return JsonResponse({
                'success': True,
                'message': 'Base de datos restaurada exitosamente',
                'output': output
            })
        except Exception as restore_error:
            return JsonResponse({
                'success': False,
                'error': f'Error durante la restauración: {str(restore_error)}'
            }, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Datos JSON inválidos'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al restaurar backup: {str(e)}'
        }, status=500)


# ============================================
# 5. ELIMINAR BACKUP
# ============================================
@csrf_exempt
def eliminar_backup_api(request, filename):
    """
    Elimina un archivo de backup específico.
    Solo accesible para administradores.
    """
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        # Autenticar y verificar que sea admin
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response
        
        # Verificar que sea administrador
        if not user.is_staff and not user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No tienes permisos de administrador'
            }, status=403)
        
        # Verificar que el archivo existe
        backup_dir = Path(settings.BASE_DIR) / 'backups'
        backup_file = backup_dir / filename
        
        if not backup_file.exists():
            return JsonResponse({
                'success': False,
                'error': 'Archivo de backup no encontrado'
            }, status=404)
        
        # Verificar que sea un archivo .sql.gz
        if not filename.endswith('.sql.gz'):
            return JsonResponse({
                'success': False,
                'error': 'Tipo de archivo no válido'
            }, status=400)
        
        # Eliminar archivo
        backup_file.unlink()
        
        return JsonResponse({
            'success': True,
            'message': f'Backup {filename} eliminado correctamente'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error al eliminar backup: {str(e)}'
        }, status=500)


# ============================================================================
# ENDPOINTS: ARCHIVOS ADJUNTOS PARA ACTAS
# ============================================================================

@csrf_exempt
def adjuntar_archivo_acta_api(request, acta_id):
    """
    POST /actas/api/actas/<acta_id>/adjuntar-archivo/

    Sube un archivo adjunto a un acta

    Headers:
        Authorization: Bearer {token}
        Content-Type: multipart/form-data

    Body (multipart/form-data):
        archivo: File (requerido) - Archivo a subir
        descripcion: String (opcional) - Descripción del archivo

    Validaciones:
    - Tamaño máximo: 10 MB
    - Tipos permitidos: pdf, doc, docx, xls, xlsx, ppt, pptx, txt, jpg, jpeg, png, gif, zip, rar
    - Solo creador del acta o admin pueden adjuntar archivos

    Response (éxito):
        {
            "success": true,
            "message": "Archivo adjuntado correctamente",
            "archivo": {
                "id": 1,
                "nombre_original": "documento.pdf",
                "tipo_archivo": "pdf",
                "tamaño_bytes": 1048576,
                "fecha_subida": "2025-12-25T10:30:00",
                "subido_por": "Juan Pérez",
                "descripcion": "Presupuesto 2025"
            }
        }

    Response (error):
        {
            "success": false,
            "error": "mensaje de error"
        }
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido. Use POST.'
        }, status=405)

    try:
        # Autenticación
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Verificar que el acta existe
        try:
            acta = Acta.objects.get(id=acta_id)
        except Acta.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Acta no encontrada'
            }, status=404)

        # Verificar permisos: solo creador o admin pueden adjuntar
        if acta.creador != user and user.rol != 'admin':
            return JsonResponse({
                'success': False,
                'error': 'No tienes permisos para adjuntar archivos a esta acta'
            }, status=403)

        # Verificar que se envió un archivo
        if 'archivo' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'No se proporcionó archivo. Use el campo "archivo".'
            }, status=400)

        archivo = request.FILES['archivo']
        descripcion = request.POST.get('descripcion', '')

        # Validar tamaño (máximo 10 MB)
        MAX_SIZE = 10 * 1024 * 1024  # 10 MB en bytes
        if archivo.size > MAX_SIZE:
            size_mb = archivo.size / (1024 * 1024)
            return JsonResponse({
                'success': False,
                'error': f'Archivo muy grande ({size_mb:.2f} MB). Tamaño máximo: 10 MB'
            }, status=400)

        # Validar tipo de archivo
        extensiones_permitidas = [
            'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
            'txt', 'jpg', 'jpeg', 'png', 'gif', 'zip', 'rar'
        ]
        nombre_archivo = archivo.name
        extension = nombre_archivo.split('.')[-1].lower() if '.' in nombre_archivo else ''

        if extension not in extensiones_permitidas:
            return JsonResponse({
                'success': False,
                'error': f'Tipo de archivo no permitido. Permitidos: {", ".join(extensiones_permitidas)}'
            }, status=400)

        # Crear archivo adjunto
        archivo_adjunto = ArchivoAdjunto.objects.create(
            acta=acta,
            archivo=archivo,
            nombre_original=nombre_archivo,
            tipo_archivo=extension,
            tamaño_bytes=archivo.size,
            subido_por=user,
            descripcion=descripcion
        )

        logger.info(
            f'Archivo {nombre_archivo} adjuntado a acta {acta.numero_acta} '
            f'por usuario {user.username}'
        )

        return JsonResponse({
            'success': True,
            'message': 'Archivo adjuntado correctamente',
            'archivo': {
                'id': archivo_adjunto.id,
                'nombre_original': archivo_adjunto.nombre_original,
                'tipo_archivo': archivo_adjunto.tipo_archivo,
                'tamaño_bytes': archivo_adjunto.tamaño_bytes,
                'tamaño_legible': archivo_adjunto.tamaño_legible,
                'fecha_subida': archivo_adjunto.fecha_subida.isoformat(),
                'subido_por': user.get_full_name() or user.email,
                'descripcion': archivo_adjunto.descripcion
            }
        })

    except Exception as e:
        logger.error(f'Error al adjuntar archivo: {str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Error al adjuntar archivo: {str(e)}'
        }, status=500)


@csrf_exempt
def listar_archivos_acta_api(request, acta_id):
    """
    GET /actas/api/actas/<acta_id>/archivos/

    Lista todos los archivos adjuntos de un acta

    Headers:
        Authorization: Bearer {token}

    Response (éxito):
        {
            "success": true,
            "archivos": [
                {
                    "id": 1,
                    "nombre_original": "documento.pdf",
                    "tipo_archivo": "pdf",
                    "tamaño_bytes": 1048576,
                    "tamaño_legible": "1.00 MB",
                    "fecha_subida": "2025-12-25T10:30:00",
                    "subido_por": "Juan Pérez",
                    "descripcion": "Presupuesto 2025"
                }
            ],
            "total": 1
        }

    Response (error):
        {
            "success": false,
            "error": "mensaje de error"
        }
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido. Use GET.'
        }, status=405)

    try:
        # Autenticación
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Verificar que el acta existe
        try:
            acta = Acta.objects.get(id=acta_id)
        except Acta.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Acta no encontrada'
            }, status=404)

        # Obtener todos los archivos adjuntos del acta
        archivos = ArchivoAdjunto.objects.filter(acta=acta).select_related('subido_por')

        archivos_data = [
            {
                'id': archivo.id,
                'nombre_original': archivo.nombre_original,
                'tipo_archivo': archivo.tipo_archivo,
                'tamaño_bytes': archivo.tamaño_bytes,
                'tamaño_legible': archivo.tamaño_legible,
                'fecha_subida': archivo.fecha_subida.isoformat(),
                'subido_por': (
                    archivo.subido_por.get_full_name()
                    if archivo.subido_por and archivo.subido_por.get_full_name()
                    else archivo.subido_por.email
                    if archivo.subido_por
                    else 'Usuario eliminado'
                ),
                'descripcion': archivo.descripcion
            }
            for archivo in archivos
        ]

        return JsonResponse({
            'success': True,
            'archivos': archivos_data,
            'total': len(archivos_data)
        })

    except Exception as e:
        logger.error(f'Error al listar archivos: {str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Error al listar archivos: {str(e)}'
        }, status=500)


@csrf_exempt
def descargar_archivo_adjunto_api(request, adjunto_id):
    """
    GET /actas/api/adjuntos/<adjunto_id>/descargar/

    Descarga un archivo adjunto

    Headers:
        Authorization: Bearer {token}

    Response (éxito):
        - Retorna el archivo para descarga con header Content-Disposition

    Response (error):
        {
            "success": false,
            "error": "mensaje de error"
        }
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido. Use GET.'
        }, status=405)

    try:
        # Autenticación
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Verificar que el archivo existe
        try:
            archivo_adjunto = ArchivoAdjunto.objects.select_related('acta').get(id=adjunto_id)
        except ArchivoAdjunto.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Archivo no encontrado'
            }, status=404)

        # Verificar que el archivo físico existe
        if not archivo_adjunto.archivo:
            return JsonResponse({
                'success': False,
                'error': 'Archivo no disponible'
            }, status=404)

        if not os.path.isfile(archivo_adjunto.archivo.path):
            logger.error(
                f'Archivo físico no encontrado: {archivo_adjunto.archivo.path} '
                f'(ID: {adjunto_id})'
            )
            return JsonResponse({
                'success': False,
                'error': 'Archivo físico no encontrado en el servidor'
            }, status=404)

        # Retornar archivo para descarga
        logger.info(
            f'Usuario {user.username} descargó archivo {archivo_adjunto.nombre_original} '
            f'(Acta: {archivo_adjunto.acta.numero_acta})'
        )

        response = FileResponse(
            open(archivo_adjunto.archivo.path, 'rb'),
            content_type='application/octet-stream'
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{archivo_adjunto.nombre_original}"'
        )
        return response

    except Exception as e:
        logger.error(f'Error al descargar archivo: {str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Error al descargar archivo: {str(e)}'
        }, status=500)


@csrf_exempt
def eliminar_archivo_adjunto_api(request, adjunto_id):
    """
    DELETE /actas/api/adjuntos/<adjunto_id>/

    Elimina un archivo adjunto

    Headers:
        Authorization: Bearer {token}

    Permisos:
    - Solo el creador del acta o administradores pueden eliminar archivos

    Response (éxito):
        {
            "success": true,
            "message": "Archivo eliminado correctamente"
        }

    Response (error):
        {
            "success": false,
            "error": "mensaje de error"
        }
    """
    if request.method != 'DELETE':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido. Use DELETE.'
        }, status=405)

    try:
        # Autenticación
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Verificar que el archivo existe
        try:
            archivo_adjunto = ArchivoAdjunto.objects.select_related('acta').get(id=adjunto_id)
        except ArchivoAdjunto.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Archivo no encontrado'
            }, status=404)

        # Verificar permisos: solo creador del acta o admin pueden eliminar
        acta = archivo_adjunto.acta
        if acta.creador != user and user.rol != 'admin':
            return JsonResponse({
                'success': False,
                'error': 'No tienes permisos para eliminar este archivo'
            }, status=403)

        # Guardar información para el log
        nombre_archivo = archivo_adjunto.nombre_original
        numero_acta = acta.numero_acta

        # Eliminar archivo (el método delete() del modelo se encarga de eliminar el archivo físico)
        archivo_adjunto.delete()

        logger.info(
            f'Usuario {user.username} eliminó archivo {nombre_archivo} '
            f'de acta {numero_acta}'
        )

        return JsonResponse({
            'success': True,
            'message': 'Archivo eliminado correctamente'
        })

    except Exception as e:
        logger.error(f'Error al eliminar archivo: {str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Error al eliminar archivo: {str(e)}'
        }, status=500)


# =============================================================================
# ENDPOINTS DE ADMINISTRACIÓN DE USUARIOS
# =============================================================================

def _serializar_usuario_admin(u):
    """Serializa un usuario con todos los campos necesarios para la vista admin."""
    return {
        'id': u.id,
        'username': u.username,
        'email': u.email,
        'first_name': u.first_name,
        'last_name': u.last_name,
        'nombre_completo': u.get_full_name(),
        'rol': u.rol,
        'centro': u.centro,
        'telefono': u.telefono,
        'email_verificado': u.email_verificado,
        'cuenta_aprobada': u.cuenta_aprobada,
        'activo': u.activo,
        'is_active': u.is_active,
        'fecha_registro': u.date_joined.isoformat(),
        'ultimo_login': u.last_login.isoformat() if u.last_login else None,
        'tiene_firma': bool(u.firma_digital),
        'firma_digital': u.firma_digital.url if u.firma_digital else None,
    }


@csrf_exempt
def admin_usuarios_list_api(request):
    """
    GET /api/admin/usuarios/
    Lista todos los usuarios del sistema con estado completo.
    Solo administradores, coordinadores y directores.
    Filtros: ?rol=instructor, ?verificado=false, ?aprobado=false, ?buscar=texto
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    if user.rol not in ['admin', 'coordinador', 'director']:
        return JsonResponse({'success': False, 'error': 'No tienes permiso para esta acción.'}, status=403)

    try:
        usuarios = User.objects.all().order_by('first_name', 'last_name')

        # Filtros opcionales
        rol_filtro = request.GET.get('rol')
        verificado = request.GET.get('verificado')
        aprobado = request.GET.get('aprobado')
        buscar = request.GET.get('buscar', '').strip()

        if rol_filtro:
            usuarios = usuarios.filter(rol=rol_filtro)
        if verificado is not None:
            usuarios = usuarios.filter(email_verificado=(verificado.lower() == 'true'))
        if aprobado is not None:
            usuarios = usuarios.filter(cuenta_aprobada=(aprobado.lower() == 'true'))
        if buscar:
            from django.db.models import Q as Qdb
            usuarios = usuarios.filter(
                Qdb(first_name__icontains=buscar) |
                Qdb(last_name__icontains=buscar) |
                Qdb(email__icontains=buscar)
            )

        return JsonResponse({
            'success': True,
            'total': usuarios.count(),
            'data': [_serializar_usuario_admin(u) for u in usuarios],
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': handle_error(e)}, status=500)


@csrf_exempt
def admin_usuario_detalle_api(request, user_id):
    """
    GET /api/admin/usuarios/<id>/
    Detalle completo de un usuario. Solo admin, coordinador, director.
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    if user.rol not in ['admin', 'coordinador', 'director']:
        return JsonResponse({'success': False, 'error': 'No tienes permiso para esta acción.'}, status=403)

    try:
        objetivo = User.objects.get(id=user_id)
        data = _serializar_usuario_admin(objetivo)
        data['stats'] = {
            'total_actas_creadas': Acta.objects.filter(creador=objetivo).count(),
            'firmas_pendientes': Firma.objects.filter(usuario=objetivo, firmado=False).count(),
            'compromisos_asignados': Compromiso.objects.filter(responsable=objetivo).count(),
            'compromisos_completados': Compromiso.objects.filter(responsable=objetivo, estado='completado').count(),
        }
        return JsonResponse({'success': True, 'data': data})

    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Usuario no encontrado.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': handle_error(e)}, status=500)


@csrf_exempt
def admin_aprobar_usuario_api(request, user_id):
    """
    POST /api/admin/usuarios/<id>/aprobar/
    Body: {"aprobar": true/false}
    Aprueba o rechaza la cuenta de un usuario. Solo admin.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    if user.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Solo los administradores pueden aprobar cuentas.'}, status=403)

    try:
        objetivo = User.objects.get(id=user_id)
        data = json.loads(request.body)
        aprobar = data.get('aprobar', True)

        objetivo.cuenta_aprobada = bool(aprobar)
        objetivo.save()

        return JsonResponse({
            'success': True,
            'message': f"Cuenta {'aprobada' if aprobar else 'rechazada'} correctamente.",
            'cuenta_aprobada': objetivo.cuenta_aprobada,
        })

    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Usuario no encontrado.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': handle_error(e)}, status=500)


@csrf_exempt
def admin_activar_usuario_api(request, user_id):
    """
    POST /api/admin/usuarios/<id>/activar/
    Body: {"activar": true/false}
    Activa o desactiva un usuario. Solo admin.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    if user.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Solo los administradores pueden activar/desactivar usuarios.'}, status=403)

    try:
        objetivo = User.objects.get(id=user_id)

        if objetivo.id == user.id:
            return JsonResponse({'success': False, 'error': 'No puedes desactivar tu propia cuenta.'}, status=400)

        data = json.loads(request.body)
        activar = data.get('activar', True)

        objetivo.activo = bool(activar)
        objetivo.is_active = bool(activar)
        objetivo.save()

        return JsonResponse({
            'success': True,
            'message': f"Usuario {'activado' if activar else 'desactivado'} correctamente.",
            'activo': objetivo.activo,
        })

    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Usuario no encontrado.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': handle_error(e)}, status=500)


@csrf_exempt
def admin_cambiar_rol_api(request, user_id):
    """
    PATCH /api/admin/usuarios/<id>/rol/
    Body: {"rol": "instructor"}
    Cambia el rol de un usuario. Solo admin.
    Roles válidos: aprendiz, instructor, invitado, funcionario, coordinador, director
    (No se puede asignar 'admin' por API por seguridad)
    """
    if request.method != 'PATCH':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    if user.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Solo los administradores pueden cambiar roles.'}, status=403)

    try:
        objetivo = User.objects.get(id=user_id)
        data = json.loads(request.body)
        nuevo_rol = data.get('rol', '').lower()

        roles_validos = ['aprendiz', 'instructor', 'invitado', 'funcionario', 'coordinador', 'director']
        if nuevo_rol not in roles_validos:
            return JsonResponse({
                'success': False,
                'error': f"Rol inválido. Roles permitidos: {', '.join(roles_validos)}"
            }, status=400)

        objetivo.rol = nuevo_rol
        objetivo.save()

        return JsonResponse({
            'success': True,
            'message': f"Rol cambiado a '{nuevo_rol}' correctamente.",
            'rol': objetivo.rol,
        })

    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Usuario no encontrado.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': handle_error(e)}, status=500)


@csrf_exempt
def admin_eliminar_usuario_api(request, user_id):
    """
    DELETE /api/admin/usuarios/<id>/
    Elimina un usuario del sistema. Solo admin.
    No se puede eliminar al propio admin.
    """
    if request.method != 'DELETE':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    if user.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Solo los administradores pueden eliminar usuarios.'}, status=403)

    try:
        objetivo = User.objects.get(id=user_id)

        if objetivo.id == user.id:
            return JsonResponse({'success': False, 'error': 'No puedes eliminar tu propia cuenta.'}, status=400)

        if objetivo.rol == 'admin':
            return JsonResponse({'success': False, 'error': 'No puedes eliminar a otro administrador.'}, status=400)

        nombre = objetivo.get_full_name()
        objetivo.delete()

        return JsonResponse({
            'success': True,
            'message': f"Usuario '{nombre}' eliminado correctamente.",
        })

    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Usuario no encontrado.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': handle_error(e)}, status=500)


# =============================================================================
# API: SISTEMA DE ESTADOS DE CUENTA
# =============================================================================

@csrf_exempt
def verificar_estado_api(request):
    """
    GET /actas/api/auth/verificar-estado/

    Devuelve el estado_cuenta del usuario autenticado por token.
    El frontend móvil lo usa para mostrar la pantalla apropiada después del login.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    user, error = get_user_from_token(request)
    if error:
        return error

    estado = getattr(user, 'estado_cuenta', 'activa')
    motivo = user.observaciones_aprobacion if estado == 'rechazada' else ''

    return JsonResponse({
        'success': True,
        'estado_cuenta': estado,
        'motivo': motivo,
    })


@csrf_exempt
def cuentas_pendientes_api(request):
    """
    GET /actas/api/admin/cuentas-pendientes/

    Lista de usuarios con estado='pendiente_aprobacion'. Solo para admins.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    user, error = get_user_from_token(request)
    if error:
        return error

    if user.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Sin permisos de administrador'}, status=403)

    pendientes = User.objects.filter(estado_cuenta='pendiente_aprobacion').order_by('-fecha_registro')

    return JsonResponse({
        'success': True,
        'total': pendientes.count(),
        'usuarios': [
            {
                'id': u.id,
                'nombre': u.get_full_name(),
                'email': u.email,
                'tipo_documento': u.tipo_documento,
                'numero_documento': u.numero_documento or '',
                'fecha_registro': u.fecha_registro.isoformat(),
            }
            for u in pendientes
        ],
    })


@csrf_exempt
def aprobar_cuenta_api(request):
    """
    POST /actas/api/admin/aprobar-cuenta/

    Body JSON: { "user_id": 5, "nuevo_rol": "instructor", "observaciones": "..." }
    Solo para admins.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    admin, error = get_user_from_token(request)
    if error:
        return error

    if admin.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Sin permisos de administrador'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'JSON inválido'}, status=400)

    user_id = data.get('user_id')
    nuevo_rol = data.get('nuevo_rol', '').strip()
    observaciones = data.get('observaciones', '').strip()

    if not user_id or not nuevo_rol:
        return JsonResponse({'success': False, 'error': 'user_id y nuevo_rol son requeridos'}, status=400)

    try:
        user_a_aprobar = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Usuario no encontrado'}, status=404)

    if user_a_aprobar.estado_cuenta != 'pendiente_aprobacion':
        return JsonResponse({'success': False, 'error': 'Esta cuenta no está pendiente de aprobación'}, status=400)

    try:
        from actas.utils import aprobar_cuenta_usuario
        aprobar_cuenta_usuario(user_a_aprobar, nuevo_rol, admin, observaciones)
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({
        'success': True,
        'message': f"Cuenta de {user_a_aprobar.get_full_name()} aprobada con rol '{nuevo_rol}'.",
    })


# =============================================================================
# API: ANEXOS PDF DE ACTAS
# =============================================================================

@csrf_exempt
def anexos_acta_api(request, acta_id):
    """
    GET  /actas/api/actas/<id>/anexos/  → Lista los anexos del acta.
    POST /actas/api/actas/<id>/anexos/  → Sube un nuevo anexo PDF (multipart).

    Permisos POST: creador o participante del acta; acta debe estar en 'borrador'.
    Límite: máximo 10 anexos por acta.
    """
    from .models import AnexoActa, MAX_ANEXOS_POR_ACTA
    from django.core.exceptions import ValidationError as DjangoValidationError

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        acta = Acta.objects.get(id=acta_id)
    except Acta.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Acta no encontrada'}, status=404)

    es_creador = acta.creador_id == user.id
    es_participante = acta.participantes.filter(usuario=user).exists()

    if not (es_creador or es_participante or user.rol == 'admin'):
        return JsonResponse({'success': False, 'error': 'No tienes acceso a esta acta'}, status=403)

    # ── GET: listar anexos ────────────────────────────────────────────────────
    if request.method == 'GET':
        anexos = acta.anexos.select_related('cargado_por').order_by('orden', 'fecha_carga')
        data = [
            {
                'id': a.id,
                'nombre_archivo': a.nombre_archivo,
                'orden': a.orden,
                'fecha_carga': a.fecha_carga.isoformat(),
                'cargado_por': a.cargado_por.get_full_name() if a.cargado_por else '',
                'tamaño_bytes': a.archivo.size if a.archivo else 0,
            }
            for a in anexos
        ]
        return JsonResponse({'success': True, 'total': len(data), 'anexos': data})

    # ── POST: subir nuevo anexo ───────────────────────────────────────────────
    if request.method == 'POST':
        if acta.estado != 'borrador':
            return JsonResponse({
                'success': False,
                'error': f'Solo se pueden añadir anexos mientras el acta esté en Borrador (estado actual: {acta.estado})'
            }, status=400)

        if acta.anexos.count() >= MAX_ANEXOS_POR_ACTA:
            return JsonResponse({
                'success': False,
                'error': f'El acta ya tiene el máximo de {MAX_ANEXOS_POR_ACTA} anexos permitidos'
            }, status=400)

        archivo = request.FILES.get('archivo')
        if not archivo:
            return JsonResponse({'success': False, 'error': 'No se recibió ningún archivo'}, status=400)

        # Sanitizar nombre de archivo
        import re as _re
        nombre_seguro = _re.sub(r'[^\w\s.\-]', '_', archivo.name)[:255]

        # Calcular orden automático
        ultimo_orden = acta.anexos.aggregate(max_orden=Max('orden'))['max_orden']
        siguiente_orden = (ultimo_orden + 1) if ultimo_orden is not None else 0

        anexo = AnexoActa(
            acta=acta,
            archivo=archivo,
            nombre_archivo=nombre_seguro,
            orden=siguiente_orden,
            cargado_por=user,
        )
        try:
            anexo.full_clean()  # Dispara validar_pdf_anexo
            anexo.save()
        except DjangoValidationError as ve:
            msgs = '; '.join(
                m for field_msgs in ve.message_dict.values() for m in field_msgs
            ) if hasattr(ve, 'message_dict') else str(ve)
            return JsonResponse({'success': False, 'error': msgs}, status=400)

        logger.info(f'Usuario {user.email} subió anexo "{nombre_seguro}" al acta {acta.numero_acta}')
        return JsonResponse({
            'success': True,
            'message': 'Anexo subido correctamente',
            'anexo': {
                'id': anexo.id,
                'nombre_archivo': anexo.nombre_archivo,
                'orden': anexo.orden,
                'fecha_carga': anexo.fecha_carga.isoformat(),
            }
        }, status=201)

    return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)


@csrf_exempt
def eliminar_anexo_api(request, acta_id, anexo_id):
    """
    DELETE /actas/api/actas/<id>/anexos/<anexo_id>/

    Elimina un anexo del acta.
    Solo el creador puede eliminar; solo si el acta está en 'borrador'.
    """
    from .models import AnexoActa

    if request.method != 'DELETE':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        acta = Acta.objects.get(id=acta_id)
    except Acta.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Acta no encontrada'}, status=404)

    if acta.creador_id != user.id and user.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Solo el creador puede eliminar anexos'}, status=403)

    if acta.estado != 'borrador':
        return JsonResponse({
            'success': False,
            'error': 'Solo se pueden eliminar anexos mientras el acta esté en Borrador'
        }, status=400)

    try:
        anexo = AnexoActa.objects.get(id=anexo_id, acta=acta)
    except AnexoActa.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Anexo no encontrado'}, status=404)

    nombre = anexo.nombre_archivo
    anexo.delete()  # También elimina el archivo físico

    logger.info(f'Usuario {user.email} eliminó anexo "{nombre}" del acta {acta.numero_acta}')
    return JsonResponse({'success': True, 'message': f'Anexo "{nombre}" eliminado correctamente'})


@csrf_exempt
def reordenar_anexos_api(request, acta_id):
    """
    PUT /actas/api/actas/<id>/anexos/orden/

    Reordena los anexos del acta.
    Body: {"orden": [<id_anexo_1>, <id_anexo_2>, ...]}
    Solo creador; solo en estado 'borrador'.
    """
    from .models import AnexoActa

    if request.method != 'PUT':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        acta = Acta.objects.get(id=acta_id)
    except Acta.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Acta no encontrada'}, status=404)

    if acta.creador_id != user.id and user.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Solo el creador puede reordenar anexos'}, status=403)

    if acta.estado != 'borrador':
        return JsonResponse({
            'success': False,
            'error': 'Solo se pueden reordenar anexos mientras el acta esté en Borrador'
        }, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'JSON inválido'}, status=400)

    ids_ordenados = data.get('orden', [])
    if not isinstance(ids_ordenados, list):
        return JsonResponse({'success': False, 'error': '"orden" debe ser una lista de IDs'}, status=400)

    # Verificar que todos los IDs pertenecen al acta
    ids_del_acta = set(acta.anexos.values_list('id', flat=True))
    if set(ids_ordenados) != ids_del_acta:
        return JsonResponse({'success': False, 'error': 'La lista debe contener exactamente los IDs de todos los anexos'}, status=400)

    for posicion, anexo_id in enumerate(ids_ordenados):
        AnexoActa.objects.filter(id=anexo_id, acta=acta).update(orden=posicion)

    return JsonResponse({'success': True, 'message': 'Orden de anexos actualizado correctamente'})


# =============================================================================
# API: REVISIÓN COLABORATIVA DE ACTAS
# =============================================================================

@csrf_exempt
def enviar_a_revision_api(request, acta_id):
    """
    POST /actas/api/actas/<id>/enviar-a-revision/

    Envía el acta al proceso de revisión colaborativa.
    Solo el creador puede hacerlo y solo si estado='borrador'.

    Response (éxito):
        {"success": true, "estado": "en_revision", "fecha_limite_revision": "..."}
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        acta = Acta.objects.get(id=acta_id)
    except Acta.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Acta no encontrada'}, status=404)

    if acta.creador_id != user.id:
        return JsonResponse({'success': False, 'error': 'Solo el creador puede enviar el acta a revisión'}, status=403)

    if acta.estado != 'borrador':
        return JsonResponse({
            'success': False,
            'error': f'El acta debe estar en estado Borrador para enviarse a revisión (estado actual: {acta.estado})'
        }, status=400)

    if not acta.participantes.exists():
        return JsonResponse({'success': False, 'error': 'El acta debe tener al menos un participante'}, status=400)

    try:
        from actas.utils import enviar_acta_a_revision
        enviar_acta_a_revision(acta, user)
        return JsonResponse({
            'success': True,
            'message': 'Acta enviada a revisión. Los participantes han sido notificados.',
            'estado': acta.estado,
            'ciclo_revision': acta.ciclo_revision,
            'fecha_limite_revision': acta.fecha_limite_revision.isoformat() if acta.fecha_limite_revision else None,
        })
    except Exception as e:
        logger.error(f'Error al enviar acta {acta_id} a revisión: {e}', exc_info=True)
        return JsonResponse({'success': False, 'error': f'Error al enviar a revisión: {str(e)}'}, status=500)


@csrf_exempt
def aprobar_acta_api(request, acta_id):
    """
    POST /actas/api/actas/<id>/aprobar/

    El participante aprueba el acta en el ciclo actual.
    Body (opcional): {"firma_digital": "<base64>"}

    Response (éxito):
        {"success": true, "estado": "en_revision"|"finalizada", "aprobados": N, "total": N}
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        acta = Acta.objects.get(id=acta_id)
    except Acta.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Acta no encontrada'}, status=404)

    if acta.estado != 'en_revision':
        return JsonResponse({
            'success': False,
            'error': f'Solo se puede aprobar un acta en revisión (estado actual: {acta.estado})'
        }, status=400)

    if not acta.participantes.filter(usuario=user).exists():
        return JsonResponse({'success': False, 'error': 'No eres participante de esta acta'}, status=403)

    # Evitar doble aprobación en el mismo ciclo
    participante_obj = acta.participantes.get(usuario=user)
    if (participante_obj.estado_aprobacion == 'aprobado'
            and participante_obj.ciclo_revision == acta.ciclo_revision):
        return JsonResponse({'success': False, 'error': 'Ya aprobaste esta acta en el ciclo actual'}, status=400)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    firma_base64 = data.get('firma_digital') or None

    try:
        from actas.utils import aprobar_acta_participante
        nuevo_estado = aprobar_acta_participante(acta, user, firma_base64=firma_base64)

        aprobados = acta.participantes.filter(
            estado_aprobacion='aprobado', ciclo_revision=acta.ciclo_revision
        ).count()
        total = acta.participantes.count()

        return JsonResponse({
            'success': True,
            'message': 'Has aprobado el acta.' + (' El acta ha sido finalizada.' if nuevo_estado == 'finalizada' else ''),
            'estado': nuevo_estado,
            'aprobados': aprobados,
            'total': total,
        })
    except Exception as e:
        logger.error(f'Error al aprobar acta {acta_id}: {e}', exc_info=True)
        return JsonResponse({'success': False, 'error': f'Error al aprobar: {str(e)}'}, status=500)


@csrf_exempt
def rechazar_acta_api(request, acta_id):
    """
    POST /actas/api/actas/<id>/rechazar/

    El participante rechaza el acta. El acta vuelve inmediatamente a 'borrador'.
    Body: {"observaciones": "Texto con mínimo 10 caracteres"}

    Response (éxito):
        {"success": true, "estado": "borrador", "ciclo_revision": N}
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        acta = Acta.objects.get(id=acta_id)
    except Acta.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Acta no encontrada'}, status=404)

    if acta.estado != 'en_revision':
        return JsonResponse({
            'success': False,
            'error': f'Solo se puede rechazar un acta en revisión (estado actual: {acta.estado})'
        }, status=400)

    if not acta.participantes.filter(usuario=user).exists():
        return JsonResponse({'success': False, 'error': 'No eres participante de esta acta'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'JSON inválido'}, status=400)

    observaciones = data.get('observaciones', '').strip()
    if len(observaciones) < 10:
        return JsonResponse({
            'success': False,
            'error': 'Las observaciones son obligatorias y deben tener al menos 10 caracteres'
        }, status=400)

    try:
        from actas.utils import rechazar_acta_participante
        acta_actualizada = rechazar_acta_participante(acta, user, observaciones)
        return JsonResponse({
            'success': True,
            'message': 'Has rechazado el acta. El creador ha sido notificado y el acta vuelve a Borrador.',
            'estado': acta_actualizada.estado,
            'ciclo_revision': acta_actualizada.ciclo_revision,
        })
    except Exception as e:
        logger.error(f'Error al rechazar acta {acta_id}: {e}', exc_info=True)
        return JsonResponse({'success': False, 'error': f'Error al rechazar: {str(e)}'}, status=500)


@csrf_exempt
def cerrar_acta_api(request, acta_id):
    """
    POST /actas/api/actas/<id>/cerrar/

    Cierra el acta por vencimiento de plazo sin consenso.
    Solo admin o creador del acta.
    Body: {"motivo_cierre": "Texto explicando el cierre"}

    Response (éxito):
        {"success": true, "estado": "cerrada_por_vencimiento", "fecha_cierre": "..."}
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        acta = Acta.objects.get(id=acta_id)
    except Acta.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Acta no encontrada'}, status=404)

    if acta.creador_id != user.id and user.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Solo el creador o un administrador puede cerrar el acta'}, status=403)

    if acta.estado not in ('borrador', 'en_revision'):
        return JsonResponse({
            'success': False,
            'error': f'No se puede cerrar un acta en estado {acta.estado}'
        }, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'JSON inválido'}, status=400)

    motivo = data.get('motivo_cierre', '').strip()
    if not motivo:
        return JsonResponse({'success': False, 'error': 'El motivo de cierre es obligatorio'}, status=400)

    try:
        from actas.utils import cerrar_acta_por_vencimiento
        acta_actualizada = cerrar_acta_por_vencimiento(acta, user, motivo)
        return JsonResponse({
            'success': True,
            'message': 'Acta cerrada por vencimiento. Los participantes han sido notificados.',
            'estado': acta_actualizada.estado,
            'fecha_cierre': acta_actualizada.fecha_cierre.isoformat() if acta_actualizada.fecha_cierre else None,
            'cerrada_por': user.get_full_name(),
        })
    except Exception as e:
        logger.error(f'Error al cerrar acta {acta_id}: {e}', exc_info=True)
        return JsonResponse({'success': False, 'error': f'Error al cerrar acta: {str(e)}'}, status=500)


@csrf_exempt
def historial_acta_api(request, acta_id):
    """
    GET /actas/api/actas/<id>/historial/

    Retorna el historial_cambios completo del acta, paginado por ciclo.
    Accesible para participantes, creador y admin.

    Response (éxito):
        {"success": true, "historial": [...], "total_eventos": N, "ciclo_actual": N}
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        acta = Acta.objects.get(id=acta_id)
    except Acta.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Acta no encontrada'}, status=404)

    es_participante = acta.participantes.filter(usuario=user).exists()
    if acta.creador_id != user.id and user.rol != 'admin' and not es_participante:
        return JsonResponse({'success': False, 'error': 'No tienes acceso a esta acta'}, status=403)

    historial = acta.historial_cambios or []
    return JsonResponse({
        'success': True,
        'numero_acta': acta.numero_acta,
        'titulo': acta.titulo,
        'estado': acta.estado,
        'ciclo_actual': acta.ciclo_revision,
        'total_eventos': len(historial),
        'historial': historial,
    })


@csrf_exempt
def participantes_estado_api(request, acta_id):
    """
    GET /actas/api/actas/<id>/participantes-estado/

    Retorna el estado de aprobación de cada participante en el ciclo actual.
    Accesible para participantes, creador y admin.

    Response (éxito):
        {
          "success": true,
          "ciclo_actual": N,
          "resumen": {"pendiente": N, "aprobado": N, "rechazado": N},
          "participantes": [...]
        }
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    user, error_response = get_user_from_token(request)
    if error_response:
        return error_response

    try:
        acta = Acta.objects.select_related('creador').get(id=acta_id)
    except Acta.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Acta no encontrada'}, status=404)

    es_participante = acta.participantes.filter(usuario=user).exists()
    if acta.creador_id != user.id and user.rol != 'admin' and not es_participante:
        return JsonResponse({'success': False, 'error': 'No tienes acceso a esta acta'}, status=403)

    participantes_data = []
    resumen = {'pendiente': 0, 'aprobado': 0, 'rechazado': 0}

    for p in acta.participantes.select_related('usuario').order_by('fecha_agregado'):
        estado = p.estado_aprobacion
        resumen[estado] = resumen.get(estado, 0) + 1
        participantes_data.append({
            'id': p.id,
            'usuario_id': p.usuario_id,
            'nombre': p.usuario.get_full_name(),
            'email': p.usuario.email,
            'rol_en_reunion': p.rol_en_reunion,
            'obligatorio_firma': p.obligatorio_firma,
            'estado_aprobacion': estado,
            'fecha_respuesta': p.fecha_respuesta.isoformat() if p.fecha_respuesta else None,
            'observaciones': p.observaciones if estado == 'rechazado' else '',
            'ciclo_revision': p.ciclo_revision,
        })

    return JsonResponse({
        'success': True,
        'numero_acta': acta.numero_acta,
        'estado': acta.estado,
        'ciclo_actual': acta.ciclo_revision,
        'fecha_limite_revision': acta.fecha_limite_revision.isoformat() if acta.fecha_limite_revision else None,
        'resumen': resumen,
        'total': len(participantes_data),
        'participantes': participantes_data,
    })


@csrf_exempt
def rechazar_cuenta_api(request):
    """
    POST /actas/api/admin/rechazar-cuenta/

    Body JSON: { "user_id": 5, "motivo": "No es funcionario verificado." }
    Solo para admins.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    admin, error = get_user_from_token(request)
    if error:
        return error

    if admin.rol != 'admin':
        return JsonResponse({'success': False, 'error': 'Sin permisos de administrador'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'JSON inválido'}, status=400)

    user_id = data.get('user_id')
    motivo = data.get('motivo', '').strip()

    if not user_id or not motivo:
        return JsonResponse({'success': False, 'error': 'user_id y motivo son requeridos'}, status=400)

    try:
        user_a_rechazar = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Usuario no encontrado'}, status=404)

    from actas.utils import rechazar_cuenta_usuario
    rechazar_cuenta_usuario(user_a_rechazar, motivo, admin)

    return JsonResponse({
        'success': True,
        'message': f"Cuenta de {user_a_rechazar.get_full_name()} rechazada.",
    })