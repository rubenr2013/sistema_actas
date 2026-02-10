from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
from django.contrib.auth import get_user_model

import csv
import json
from datetime import datetime, timedelta
from django.utils import timezone

from actas.models import Acta, Compromiso, Firma
from notifications.models import Notification
from .serializers import ActaSerializer, CompromisoSerializer, NotificationSerializer

User = get_user_model()


class ActaViewSet(viewsets.ModelViewSet):
    queryset = Acta.objects.all()
    serializer_class = ActaSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Acta.objects.filter(
            Q(creador=self.request.user) | 
            Q(participantes__usuario=self.request.user)
        ).distinct()
    
    @action(detail=True, methods=['post'])
    def firmar(self, request, pk=None):
        """Endpoint para firmar una acta"""
        acta = self.get_object()
        
        try:
            firma = Firma.objects.get(acta=acta, usuario=request.user)
            
            if firma.firmado:
                return Response(
                    {'error': 'Ya ha firmado esta acta'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            comentarios = request.data.get('comentarios', '')
            firma.comentarios = comentarios
            firma.firmar(request)
            
            return Response({
                'success': True,
                'message': 'Acta firmada exitosamente',
                'firmas_completadas': acta.get_firmas_completadas(),
                'total_firmas': acta.get_total_firmas()
            })
            
        except Firma.DoesNotExist:
            return Response(
                {'error': 'No tiene permisos para firmar esta acta'},
                status=status.HTTP_403_FORBIDDEN
            )


class CompromisoViewSet(viewsets.ModelViewSet):
    queryset = Compromiso.objects.all() 
    serializer_class = CompromisoSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Compromiso.objects.filter(
            Q(responsable=self.request.user) |
            Q(acta__creador=self.request.user) |
            Q(acta__participantes__usuario=self.request.user)
        ).distinct()


class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Notification.objects.filter(usuario=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    """API endpoint para estadísticas del dashboard"""
    user = request.user
    
    stats = {
        'total_actas': Acta.objects.filter(
            Q(creador=user) | Q(participantes__usuario=user)
        ).distinct().count(),
        
        'actas_pendientes_firma': Firma.objects.filter(
            usuario=user, firmado=False, acta__estado='en_revision'
        ).count(),
        
        'compromisos_pendientes': Compromiso.objects.filter(
            responsable=user, estado__in=['pendiente', 'en_progreso']
        ).count(),
        
        'compromisos_vencidos': Compromiso.objects.filter(
            responsable=user, estado='vencido'
        ).count(),
        
        'notificaciones_no_leidas': Notification.objects.filter(
            usuario=user, leida=False
        ).count()
    }
    
    return Response(stats)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def acta_firmas_status(request, acta_id):
    """Estado de firmas de una acta específica"""
    try:
        acta = Acta.objects.get(id=acta_id)
        
        # Verificar permisos
        if not (
            acta.creador == request.user or 
            acta.participantes.filter(usuario=request.user).exists() or
            request.user.is_staff
        ):
            return Response(
                {'error': 'Sin permisos'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return Response({
            'completadas': acta.get_firmas_completadas(),
            'total': acta.get_total_firmas(),
            'porcentaje': acta.get_porcentaje_firmas(),
            'estado': acta.estado,
            'firmas': [
                {
                    'usuario': firma.usuario.get_full_name(),
                    'email': firma.usuario.email,
                    'firmado': firma.firmado,
                    'fecha_firma': firma.fecha_firma.isoformat() if firma.fecha_firma else None
                }
                for firma in acta.firmas.select_related('usuario').all()
            ]
        })
        
    except Acta.DoesNotExist:
        return Response(
            {'error': 'Acta no encontrada'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_users(request):
    """Buscar usuarios por email (solo dominios @sena.edu.co)"""
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return Response([])
    
    users = User.objects.filter(
        Q(email__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query),
        email__endswith='@sena.edu.co',
        activo=True
    )[:10]
    
    results = [
        {
            'id': user.id,
            'email': user.email,
            'full_name': user.get_full_name(),
            'rol': user.get_rol_display()
        }
        for user in users
    ]
    
    return Response(results)


@login_required
def export_actas(request):
    """Exportar actas a CSV"""
    actas = Acta.objects.filter(
        Q(creador=request.user) | Q(participantes__usuario=request.user)
    ).distinct().order_by('-fecha_creacion')
    
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="actas_{timezone.now().strftime("%Y%m%d")}.csv"'
    response.write('\ufeff'.encode('utf8'))  # BOM para Excel
    
    writer = csv.writer(response)
    
    # Headers
    writer.writerow([
        'Número Acta',
        'Título',
        'Tipo Reunión',
        'Fecha Reunión',
        'Lugar',
        'Modalidad',
        'Estado',
        'Creador',
        'Participantes',
        'Firmas Completadas',
        'Total Firmas',
        'Compromisos',
        'Fecha Creación'
    ])
    
    # Data
    for acta in actas:
        participantes = ', '.join([p.usuario.get_full_name() for p in acta.participantes.all()])
        
        writer.writerow([
            acta.numero_acta,
            acta.titulo,
            acta.get_tipo_reunion_display(),
            acta.fecha_reunion.strftime('%d/%m/%Y %H:%M'),
            acta.lugar_reunion,
            acta.get_modalidad_display(),
            acta.get_estado_display(),
            acta.creador.get_full_name(),
            participantes,
            acta.get_firmas_completadas(),
            acta.get_total_firmas(),
            acta.compromisos.count(),
            acta.fecha_creacion.strftime('%d/%m/%Y %H:%M')
        ])
    
    return response
