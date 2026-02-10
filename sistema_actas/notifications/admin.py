from django.contrib import admin
from .models import Notification, NotificationSettings

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'usuario', 'tipo', 'leida', 'fecha_creacion']
    list_filter = ['tipo', 'leida', 'fecha_creacion']
    search_fields = ['titulo', 'mensaje', 'usuario__email']
    readonly_fields = ['fecha_creacion', 'fecha_lectura']

@admin.register(NotificationSettings)
class NotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'email_firma_pendiente', 'email_compromiso_vencido']