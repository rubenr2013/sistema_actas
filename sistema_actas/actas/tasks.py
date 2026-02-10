from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import Acta, Compromiso
from notifications.models import Notification


@shared_task
def verificar_silencio_administrativo():
    """
    Tarea que se ejecuta periódicamente para aplicar silencio administrativo
    a las actas que han superafo el tiempo límite
    """

    actas_vencidas = Acta.objects.filter(
        estado="en_revision",
        fecha_limite_firmas__lte=timezone.now(),
        silencio_administrativo=False,
    )

    for acta in actas_vencidas:
        acta.aplicar_silencio_admin()

        # Notificar al creador
        Notification.objects.create(
            usuario=acta.creador,
            tipo="silencio_administrativo",
            titulo="Silencio administrativo aplicado",
            mensaje=f"Se aplico silencio administrativo al acta {acta.numero_acta}",
            enlace=f"/actas/{acta.id}/",
        )

    return f"Se aplico silencio administrativoa {actas_vencidas.count()} actas"


@shared_task
def notificar_compromisos_proximos():
    """
    Notifica sobre compromisos que estan proximos a vencer
    """
    fecha_limite = timezone.now() + timedelta(days=3)

    compromisos_proximos = Compromiso.objects.filter(
        estado__in=["pendiente", "en_progreso"],
        fecha_limite__lte=fecha_limite,
        fecha_limite__gte=timezone.now().date(),
    ).select_related("responsable", "acta")

    for compromiso in compromisos_proximos:
        # Verificar si ya se notificó hoy
        notificacion_existente = Notification.objects.filter(
            usuario=compromiso.responsable,
            tipo="compromiso_proximo",
            fecha_creacion__date=timezone.now().date(),
            mensaje__contains=str(compromiso.id),
        ).exists()

        if not notificacion_existente:
            Notification.objects.create(
                usuario=compromiso.responsable,
                tipo="compromiso_proximo",
                titulo="Compromiso próximo a vencer",
                mensaje=f"El compromiso del acta {compromiso.acta.numero_acta} vence en {compromiso.dias_restantes()} días.",
                enlace=f"/compromisos/{compromiso.id}/",
            )
    return f"Se enviaron {compromisos_proximos.count()} notificaciones de compromisos próximos"


@shared_task
def marcar_compromisos_vencidos():
    """
    Marca los compromisos como vencidos si han pasado su fecha limite
    """
    compromisos_vencidos = Compromiso.objects.filter(
        fecha_limite__lte=timezone.now(), estado__in=["pendiente", "en_progreso"]
    )

    count = 0
    for compromiso in compromisos_vencidos:
        compromiso.estado = "vencido"
        compromiso.save()
        count += 1

        # Notificar al responsable
        Notification.objects.create(
            usuario=compromiso.responsable,
            tipo="compromiso_vencido",
            titulo="Compromiso vencido",
            mensaje=f"El compromiso del acta {compromiso.acta.numero_acta} ha pasado su fecha límite y ha sido vencido.",
            enlace=f"/compromisos/{compromiso.id}/",
        )

    return f"Se marcaron como vencidos {count} compromisos"
