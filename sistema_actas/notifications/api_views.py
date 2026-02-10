from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import get_user_model
from .models import Notification
import json
from actas.api_views import get_user_from_token

User = get_user_model()


@csrf_exempt
def notificaciones_api(request):
    """
    API para obtener notificaciones del usuario
    GET: Lista de notificaciones
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticación con token seguro
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Filtros opcionales
        leida = request.GET.get('leida')  # 'true' o 'false'
        tipo = request.GET.get('tipo')
        limit = int(request.GET.get('limit', 50))
        
        # Obtener notificaciones
        notificaciones = Notification.objects.filter(usuario=user)
        
        # Aplicar filtros
        if leida == 'true':
            notificaciones = notificaciones.filter(leida=True)
        elif leida == 'false':
            notificaciones = notificaciones.filter(leida=False)
        
        if tipo:
            notificaciones = notificaciones.filter(tipo=tipo)
        
        # Limitar resultados
        notificaciones = notificaciones[:limit]
        
        # Serializar
        notificaciones_data = []
        for notif in notificaciones:
            notificaciones_data.append({
                'id': notif.id,
                'tipo': notif.tipo,
                'titulo': notif.titulo,
                'mensaje': notif.mensaje,
                'enlace': notif.enlace,
                'leida': notif.leida,
                'fecha_creacion': notif.fecha_creacion.isoformat(),
                'fecha_lectura': notif.fecha_lectura.isoformat() if notif.fecha_lectura else None,
                'metadata': notif.metadata,
            })
        
        # Contar no leídas
        no_leidas = Notification.objects.filter(usuario=user, leida=False).count()
        
        return JsonResponse({
            'success': True,
            'data': {
                'notificaciones': notificaciones_data,
                'total_no_leidas': no_leidas,
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
def contar_no_leidas_api(request):
    """
    API para obtener el contador de notificaciones no leídas
    """
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)
    
    try:
        # Autenticación con token seguro
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Contar no leídas
        no_leidas = Notification.objects.filter(usuario=user, leida=False).count()
        
        return JsonResponse({
            'success': True,
            'data': {
                'count': no_leidas
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
def marcar_leida_api(request, notificacion_id):
    """
    API para marcar una notificación como leída
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticación con token seguro
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener notificación
        try:
            notificacion = Notification.objects.get(id=notificacion_id, usuario=user)
        except Notification.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Notificación no encontrada'
            }, status=404)
        
        # Marcar como leída
        notificacion.marcar_como_leida()

        return JsonResponse({
            'success': True,
            'message': 'Notificación marcada como leída'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
def marcar_todas_leidas_api(request):
    """
    API para marcar todas las notificaciones como leídas
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticación con token seguro
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Marcar todas como leídas
        notificaciones = Notification.objects.filter(usuario=user, leida=False)
        count = 0
        for notif in notificaciones:
            notif.marcar_como_leida()
            count += 1
        
        return JsonResponse({
            'success': True,
            'message': f'{count} notificaciones marcadas como leídas',
            'count': count
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
def eliminar_notificacion_api(request, notificacion_id):
    """
    API para eliminar una notificación
    """
    if request.method != 'DELETE':
        return JsonResponse({
            'success': False,
            'error': 'Método no permitido'
        }, status=405)

    try:
        # Autenticación con token seguro
        user, error_response = get_user_from_token(request)
        if error_response:
            return error_response

        # Obtener notificación
        try:
            notificacion = Notification.objects.get(id=notificacion_id, usuario=user)
        except Notification.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Notificación no encontrada'
            }, status=404)
        
        # Eliminar
        notificacion.delete()

        return JsonResponse({
            'success': True,
            'message': 'Notificación eliminada'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
        
