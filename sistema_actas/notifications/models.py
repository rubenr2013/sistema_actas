from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta


User = get_user_model()

class Notification (models.Model):
    TIPOS_NOTIFICACION =[
        ('firma_pendiente', 'Firma Pendiente'),
        ('firma_completada', 'Firma Completada'),
        ('acta_lista_finalizar', 'Acta Lista para Finalizar'),
        ('compromiso_vencido', 'Compromiso Vencido'),
        ('compromiso_proximo', 'Compromiso Próximo a Vencer'),
        ('silencio_administrativo', 'Silencio Administrativo'),
        ('nueva_acta', 'Nueva Acta '),
        ('acta_finalizada', 'Acta Finalizada'),
        ('sistema', 'Notificación del Sistema'),
    ]
    
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notificaciones')
    tipo = models.CharField(max_length=30, choices=TIPOS_NOTIFICACION)
    titulo = models.CharField(max_length=200)
    mensaje = models.TextField()
    enlace = models.CharField(max_length=500, blank=True, help_text='URL para redireccionar al hacer clic')    
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_lectura = models.DateTimeField(null=True, blank=True)
    
    #metadata adicional
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta: 
        verbose_name = 'Notificación'
        verbose_name_plural = 'Notificaciones'
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['usuario', 'leida']),
            models.Index(fields= ['fecha_creacion']),
            models.Index(fields= ['tipo']),
        ]
        
    def marcar_como_leida(self):
        if not self.leida:
            self.leida = True
            self.fecha_lectura = timezone.now()
            self.save()
            
    def get_icon(self):
        icon_map = {
            'firma_pendiente': 'signature',
            'firma_completada': 'check-circle',
            'acta_lista_finalizar': 'flag-checkered',
            'compromiso_vencido': 'exclamation-triangle',
            'compromiso_proximo': 'clock',
            'silencio_administrativo': 'gavel',
            'nueva_acta': 'file-alt',
            'acta_finalizada': 'check-square',
            'sistema': 'cog'
        }
        return icon_map.get(self.tipo, 'bell')
    
    def get_color(self):
        color_map = {
            'firma_pendiente': 'warning',
            'firma_completada': 'success',
            'acta_lista_finalizar': 'info',
            'compromiso_vencido': 'danger',
            'compromiso_proximo': 'warning',
            'silencio_administrativo': 'secondary',
            'nueva_acta': 'primary',
            'acta_finalizada': 'success',
            'sistema': 'info'
        }
        return color_map.get(self.tipo, 'secondary')
    
    def get_url(self):
        return self.enlace or '#'
    
    def __str__(self):
        return f"{self.titulo} - {self.usuario.get_full_name}"
    
class NotificationSettings(models.Model):
    """configuracion de notificaciones por usuario"""
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notificacion_settings')
    
    #notificaciones por email
    email_firma_pendiente = models.BooleanField(default=True)
    email_compromiso_vencido = models.BooleanField(default=True)
    email_nueva_acta = models.BooleanField(default=True)
    
    #notificaciones en la aplicacion 
    app_todas_notificaciones = models.BooleanField(default=True)
    
    #frecuencia de resumenes por emails
    resumen_email = models.CharField(max_length=20, choices=[
        ('nunca', 'Nunca'),
        ('diario', 'Diario'),
        ('semanal', 'Semanal')
    ], default='semanal')
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'configuracion de Notificaciones'
        verbose_name_plural = 'Configuraciones de Notificaciones'
        
    def __str__(self):
        return f"configuracion de {self.usuario.get_full_name()}"