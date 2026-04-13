from notifications.models import Notification

def notifications_count(request):
    """Context processor para agregar el conteo de notificaciones y cuentas pendientes."""
    if request.user.is_authenticated:
        count = Notification.objects.filter(
            usuario=request.user,
            leida=False
        ).count()

        recent_notifications = Notification.objects.filter(
            usuario=request.user,
            leida=False
        ).order_by('-fecha_creacion')[:5]

        # Conteo de cuentas pendientes de aprobación (solo visible para admins)
        pending_accounts_count = 0
        if getattr(request.user, 'rol', None) == 'admin' or getattr(request.user, 'is_staff', False):
            from accounts.models import User
            pending_accounts_count = User.objects.filter(
                estado_cuenta='pendiente_aprobacion'
            ).count()

        return {
            'notifications_count': count,
            'user_notifications': recent_notifications,
            'pending_accounts_count': pending_accounts_count,
        }

    return {
        'notifications_count': 0,
        'user_notifications': [],
        'pending_accounts_count': 0,
    }