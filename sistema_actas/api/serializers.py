from rest_framework import serializers
from actas.models import Acta, Compromiso, Firma
from notifications.models import Notification


class ActaSerializer(serializers.ModelSerializer):
    creador_nombre = serializers.CharField(source='creador.get_full_name', read_only=True)
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    tipo_reunion_display = serializers.CharField(source='get_tipo_reunion_display', read_only=True)
    modalidad_display = serializers.CharField(source='get_modalidad_display', read_only=True)
    firmas_completadas = serializers.SerializerMethodField()
    total_firmas = serializers.SerializerMethodField()
    porcentaje_firmas = serializers.SerializerMethodField()
    
    class Meta:
        model = Acta
        fields = [
            'id', 'numero_acta', 'titulo', 'tipo_reunion', 'tipo_reunion_display',
            'fecha_reunion', 'lugar_reunion', 'modalidad', 'modalidad_display',
            'estado', 'estado_display', 'creador_nombre', 'fecha_creacion',
            'firmas_completadas', 'total_firmas', 'porcentaje_firmas',
            'silencio_administrativo'
        ]
    
    def get_firmas_completadas(self, obj):
        return obj.get_firmas_completadas()
    
    def get_total_firmas(self, obj):
        return obj.get_total_firmas()
    
    def get_porcentaje_firmas(self, obj):
        return obj.get_porcentaje_firmas()

class CompromisoSerializer(serializers.ModelSerializer):
    responsable_nombre = serializers.CharField(source='responsable.get_full_name', read_only=True)
    acta_numero = serializers.CharField(source='acta.numero_acta', read_only=True)
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    dias_restantes = serializers.SerializerMethodField()
    
    class Meta:
        model = Compromiso
        fields = [
            'id', 'descripcion', 'responsable_nombre', 'fecha_limite',
            'estado', 'estado_display', 'porcentaje_avance', 'acta_numero',
            'dias_restantes', 'observaciones'
        ]
    
    def get_dias_restantes(self, obj):
        return obj.dias_restantes()

class NotificationSerializer(serializers.ModelSerializer):
    icon = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()
    tiempo_transcurrido = serializers.SerializerMethodField()
    
    class Meta:
        model = Notification
        fields = [
            'id', 'tipo', 'titulo', 'mensaje', 'enlace', 'leida',
            'fecha_creacion', 'icon', 'color', 'tiempo_transcurrido'
        ]
    
    def get_icon(self, obj):
        return obj.get_icon()
    
    def get_color(self, obj):
        return obj.get_color()
    
    def get_tiempo_transcurrido(self, obj):
        from django.contrib.humanize.templatetags.humanize import naturaltime
        return naturaltime(obj.fecha_creacion)