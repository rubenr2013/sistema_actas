"""
Comando Django para enviar recordatorios de compromisos próximos a vencer
Ejecutar diariamente con: python manage.py enviar_recordatorios
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from actas.models import Compromiso
from actas.email_service import enviar_email_recordatorio_compromiso
import logging

logger = logging.getLogger('actas.email_service')


class Command(BaseCommand):
    help = 'Envía recordatorios por email de compromisos próximos a vencer (24 horas)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias',
            type=int,
            default=1,
            help='Días de anticipación para enviar recordatorios (default: 1)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula la ejecución sin enviar emails reales'
        )

    def handle(self, *args, **options):
        dias_anticipacion = options['dias']
        dry_run = options['dry_run']

        self.stdout.write(self.style.SUCCESS(f'\n{"="*60}'))
        self.stdout.write(self.style.SUCCESS('Iniciando envío de recordatorios de compromisos'))
        self.stdout.write(self.style.SUCCESS(f'{"="*60}\n'))

        if dry_run:
            self.stdout.write(self.style.WARNING('MODO DRY-RUN: No se enviarán emails reales\n'))

        # Calcular la fecha objetivo (hoy + días de anticipación)
        fecha_objetivo = (datetime.now().date() + timedelta(days=dias_anticipacion))

        self.stdout.write(f'Buscando compromisos que vencen el: {fecha_objetivo.strftime("%d/%m/%Y")}\n')

        # Buscar compromisos que:
        # 1. Vencen en la fecha objetivo
        # 2. NO están completados
        # 3. Tienen un responsable asignado
        compromisos_pendientes = Compromiso.objects.filter(
            fecha_limite=fecha_objetivo,
            responsable__isnull=False
        ).exclude(
            estado__in=['completado', 'cumplido', 'finalizado']
        ).select_related('responsable', 'acta')

        total_compromisos = compromisos_pendientes.count()

        if total_compromisos == 0:
            self.stdout.write(self.style.WARNING('No se encontraron compromisos pendientes para enviar recordatorios.\n'))
            return

        self.stdout.write(f'Se encontraron {total_compromisos} compromiso(s) pendiente(s):\n')

        emails_enviados = 0
        emails_fallidos = 0

        for compromiso in compromisos_pendientes:
            responsable = compromiso.responsable

            # Mostrar información del compromiso
            self.stdout.write(f'\n  • ID: {compromiso.id}')
            self.stdout.write(f'    Descripción: {compromiso.descripcion[:60]}...')
            self.stdout.write(f'    Responsable: {responsable.get_full_name()} ({responsable.email})')
            self.stdout.write(f'    Vencimiento: {compromiso.fecha_limite.strftime("%d/%m/%Y")}')
            self.stdout.write(f'    Estado: {compromiso.get_estado_display() if hasattr(compromiso, "get_estado_display") else compromiso.estado}')

            if not responsable.email:
                self.stdout.write(self.style.WARNING(f'    ⚠ Responsable no tiene email configurado'))
                emails_fallidos += 1
                continue

            if dry_run:
                self.stdout.write(self.style.WARNING(f'    [DRY-RUN] Email que se enviaría a: {responsable.email}'))
                emails_enviados += 1
            else:
                # Enviar el email de recordatorio
                resultado = enviar_email_recordatorio_compromiso(compromiso)

                if resultado:
                    self.stdout.write(self.style.SUCCESS(f'    ✓ Email enviado exitosamente'))
                    emails_enviados += 1
                else:
                    self.stdout.write(self.style.ERROR(f'    ✗ Error al enviar email'))
                    emails_fallidos += 1

        # Resumen final
        self.stdout.write(f'\n{"="*60}')
        self.stdout.write(self.style.SUCCESS(f'Resumen de envío de recordatorios:'))
        self.stdout.write(f'{"="*60}')
        self.stdout.write(f'Total de compromisos encontrados: {total_compromisos}')
        self.stdout.write(self.style.SUCCESS(f'Emails enviados exitosamente: {emails_enviados}'))

        if emails_fallidos > 0:
            self.stdout.write(self.style.ERROR(f'Emails fallidos: {emails_fallidos}'))

        if dry_run:
            self.stdout.write(self.style.WARNING('\nNOTA: Esta fue una ejecución de prueba (dry-run)'))
            self.stdout.write(self.style.WARNING('Para enviar emails reales, ejecute sin el flag --dry-run'))

        self.stdout.write(f'{"="*60}\n')

        # Logging
        logger.info(f'Recordatorios enviados: {emails_enviados}, Fallidos: {emails_fallidos}, Total: {total_compromisos}')
