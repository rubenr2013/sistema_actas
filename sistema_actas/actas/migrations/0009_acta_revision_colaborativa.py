"""
Migration 0009: Revisión colaborativa de actas.

Cambios:
- Acta: nuevo estado 'cerrada_por_vencimiento', campos para el proceso de
  revisión colaborativa (fecha_limite_revision, ciclo_revision,
  historial_cambios, observaciones_participantes, cerrada_por,
  fecha_cierre, motivo_cierre).
- Participante: nuevos campos para registrar la respuesta por ciclo
  (estado_aprobacion, fecha_respuesta, observaciones, ciclo_revision).

Data migration:
- Actas existentes en estado 'en_revision': se registra un evento inicial
  en historial_cambios.
- Participantes existentes: estado_aprobacion='pendiente' (ya es el default).
"""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def inicializar_historial_actas(apps, schema_editor):
    """
    Para las actas que ya están en revisión, agrega un evento inicial en
    historial_cambios para que el historial no aparezca vacío.
    """
    Acta = apps.get_model('actas', 'Acta')
    now = django.utils.timezone.now().isoformat()

    for acta in Acta.objects.filter(estado='en_revision'):
        if not acta.historial_cambios:
            acta.historial_cambios = [
                {
                    "ciclo": 1,
                    "fecha": now,
                    "accion": "migración",
                    "usuario": "sistema",
                    "detalle": "Acta migrada al nuevo sistema de revisión colaborativa.",
                }
            ]
            acta.save(update_fields=['historial_cambios'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('actas', '0008_alter_acta_archivo_adjunto_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── Acta: nuevo estado + ampliar max_length (23 chars) ───────────────
        migrations.AlterField(
            model_name='acta',
            name='estado',
            field=models.CharField(
                choices=[
                    ('borrador', 'Borrador'),
                    ('en_revision', 'En Revisión'),
                    ('finalizada', 'Finalizada'),
                    ('archivada', 'Archivada'),
                    ('cerrada_por_vencimiento', 'Cerrada por Vencimiento'),
                ],
                default='borrador',
                max_length=25,
            ),
        ),

        # ── Acta: campos de revisión colaborativa ────────────────────────────
        migrations.AddField(
            model_name='acta',
            name='fecha_limite_revision',
            field=models.DateTimeField(
                blank=True, null=True,
                help_text='Fecha límite para que los participantes respondan en el ciclo actual',
            ),
        ),
        migrations.AddField(
            model_name='acta',
            name='ciclo_revision',
            field=models.IntegerField(
                default=1,
                help_text='Número de ciclo de revisión (1 = primera vez en revisión)',
            ),
        ),
        migrations.AddField(
            model_name='acta',
            name='historial_cambios',
            field=models.JSONField(
                blank=True, default=list,
                help_text='Historial de cambios y eventos del acta en formato JSON',
            ),
        ),
        migrations.AddField(
            model_name='acta',
            name='observaciones_participantes',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Observaciones de los participantes organizadas por ciclo de revisión',
            ),
        ),
        migrations.AddField(
            model_name='acta',
            name='cerrada_por',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='actas_cerradas',
                to=settings.AUTH_USER_MODEL,
                help_text='Usuario (o sistema) que cerró el acta por vencimiento',
            ),
        ),
        migrations.AddField(
            model_name='acta',
            name='fecha_cierre',
            field=models.DateTimeField(
                blank=True, null=True,
                help_text='Fecha en que el acta fue cerrada por vencimiento',
            ),
        ),
        migrations.AddField(
            model_name='acta',
            name='motivo_cierre',
            field=models.TextField(
                blank=True,
                help_text='Motivo del cierre del acta (vencimiento de plazos, etc.)',
            ),
        ),

        # ── Participante: campos de revisión colaborativa ────────────────────
        migrations.AddField(
            model_name='participante',
            name='estado_aprobacion',
            field=models.CharField(
                choices=[
                    ('pendiente', 'Pendiente'),
                    ('aprobado', 'Aprobado'),
                    ('rechazado', 'Rechazado'),
                ],
                default='pendiente',
                max_length=15,
                help_text='Respuesta del participante al acta en el ciclo de revisión actual',
            ),
        ),
        migrations.AddField(
            model_name='participante',
            name='fecha_respuesta',
            field=models.DateTimeField(
                blank=True, null=True,
                help_text='Fecha en que el participante aprobó o rechazó el acta',
            ),
        ),
        migrations.AddField(
            model_name='participante',
            name='observaciones',
            field=models.TextField(
                blank=True,
                help_text='Observaciones del participante (motivo del rechazo o comentarios)',
            ),
        ),
        migrations.AddField(
            model_name='participante',
            name='ciclo_revision',
            field=models.IntegerField(
                default=1,
                help_text='Ciclo de revisión al que corresponde el estado_aprobacion actual',
            ),
        ),

        # ── Participante: nuevo índice ────────────────────────────────────────
        migrations.AddIndex(
            model_name='participante',
            index=models.Index(
                fields=['acta', 'estado_aprobacion'],
                name='actas_parti_acta_id_estado_idx',
            ),
        ),

        # ── Data migration ────────────────────────────────────────────────────
        migrations.RunPython(inicializar_historial_actas, noop),
    ]
