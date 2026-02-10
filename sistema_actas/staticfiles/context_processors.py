from notifications.models import Notification

def notifications_count(request):
    """Context processor para agregar el conteo de notificaciones"""
    if request.user.is_authenticated:
        count = Notification.objects.filter(
            usuario=request.user, 
            leida=False
        ).count()
        
        recent_notifications = Notification.objects.filter(
            usuario=request.user, 
            leida=False
        ).order_by('-fecha_creacion')[:5]
        
        return {
            'notifications_count': count,
            'user_notifications': recent_notifications
        }
    
    return {
        'notifications_count': 0,
        'user_notifications': []
    }