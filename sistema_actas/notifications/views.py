from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator 
from django.db.models import Q

from .models import Notification, NotificationSettings

@login_required 
def notifications_list (request): 
    """Vist para listar todas las nitificaciones del usuario """
    notificaciones = Notification.objects.filter(usuario=request.user)
    
    #filtros
    tipo = request.GET.get('tipo')
    leida = request.GET.get('leida')
    
    if tipo: 
        notificaciones = notificaciones.filter(tipo=tipo)
        
    if leida == 'true':
        notificaciones = notificaciones.filter(leida=True)
    elif leida == 'false':
        notificaciones = notificaciones.filter(leida=False)
        
    #pagination
    paginator = Paginator(notificaciones, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)   
    context = {
        'page_obj': page_obj,
        'tipos_notificacion': Notification.TIPOS_NOTIFICACION,
        'filtros': {
            'tipo': tipo,
            'leida': leida
        }
    }
    
    return render(request, 'notifications/list.html', context)

@login_required
@require_POST
def mark_as_read(request):
    """marcar notificaciones como leidas"""
    notification_ids= request.POST.getlist('notification_ids', [])
    
    if notification_ids:
        """marcar notificaciones especificadas"""
        notificaciones = Notification.objects.filter(
            id__in=notification_ids,
            usuario=request.user,
            leida=False
        )
    else:
        #marcar tods como no leidas
        notificaciones = Notification.objects.filter(
            usuario=request.user,
            leida=False
        )
        
    count= 0 
    for notification in notificaciones:
        notification.marcar_como_leida()
        count +=1
    return JsonResponse({
        'success': True,
        'marked_count': count,
        'message': f"{count} notificaciones marcadas como leidas"
    })
    
@login_required
@require_POST
def mark_as_unread(request, notification_id):
    """mrcar una notificacion como no leida"""
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        usuario=request.user
    )
    
    notification.leida= False
    notification.fecha_lectura = None
    notification.save()
    
    return JsonResponse({
        'success': True,
        'message': 'Notificación marcada como no leida.'
    })
    
@login_required
@require_POST
def delete_notification(request, notification_id):
    """Eliminar una notificacion"""
    notification = get_object_or_404(
        Notification, 
        id= notification_id,
        usuario=request.user
    )
    notification.delete()
    
    return JsonResponse({
        'sucess': True,
        'message': "Notificación eliminada"
    })

@login_required
def notification_settings(request):
    """vista para configurar las preferencias de notificaciones """
    settings, created = NotificationSettings.objects.get_or_create(usuario=request.user)
    
    if request.method == 'POST':
        settings.email_firma_pendiente = request.POST.get('email_firma_pendiente') == 'on'
        settings.email_compromiso_vencido= request.POST.get('email_compromiso_vencido') == 'on'
        settings.email_nueva_acta = request.POST.get('email_nueva_acta') == 'on'
        settings.app_todas_notificaciones = request.POST.get ( 'app_todas_notificaciones') == 'on'
        settings.resumen.email = request.POST.get('resumen_email', 'semanal')
        settings.save()
        
        return JsonResponse({
            'sucess': True,
            'message': 'Configuración guardada axitosamente.'
        })
        
    return render (request, 'notifications/settings.html', {'settings': settings})