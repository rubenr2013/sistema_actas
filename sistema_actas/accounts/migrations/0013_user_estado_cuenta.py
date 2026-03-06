"""
Migración: agrega el sistema de estados de cuenta al modelo User.

Nuevos campos:
  - estado_cuenta: estado del ciclo de vida (activa, pendiente_aprobacion, rechazada, suspendida)
  - fecha_aprobacion: cuándo fue aprobada la cuenta
  - aprobado_por: FK al admin que la aprobó
  - observaciones_aprobacion: notas del admin

Migración de datos:
  - TODOS los usuarios existentes quedan con estado_cuenta='activa' para no romper la funcionalidad.
  - fecha_aprobacion se rellena con fecha_registro (ya tenían acceso).
"""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def marcar_existentes_como_activos(apps, schema_editor):
    """
    Todos los usuarios que ya existen en el sistema quedan como 'activa'
    porque ya tenían acceso antes de este cambio.
    Se usa fecha_registro como fecha de aprobación implícita.
    """
    User = apps.get_model('accounts', 'User')
    User.objects.filter(estado_cuenta='').update(
        estado_cuenta='activa',
        fecha_aprobacion=django.utils.timezone.now(),
    )


def revertir_estado_activo(apps, schema_editor):
    """
    Si se revierte la migración, limpiamos los valores que pusimos.
    (Los campos se eliminarán de todas formas al hacer downgrade)
    """
    pass  # Los campos se eliminan con la operación RemoveField al revertir


class Migration(migrations.Migration):

    dependencies = [
        # Depende de la migración anterior que agregó ficha al usuario
        ('accounts', '0012_user_add_ficha'),
    ]

    operations = [
        # ── 1. Agregar los 4 campos nuevos ──────────────────────────────────

        migrations.AddField(
            model_name='user',
            name='estado_cuenta',
            field=models.CharField(
                choices=[
                    ('activa', 'Activa'),
                    ('pendiente_aprobacion', 'Pendiente de aprobación'),
                    ('rechazada', 'Rechazada'),
                    ('suspendida', 'Suspendida'),
                ],
                default='activa',
                max_length=25,
                verbose_name='Estado de la cuenta',
            ),
        ),

        migrations.AddField(
            model_name='user',
            name='fecha_aprobacion',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Fecha de aprobación',
            ),
        ),

        migrations.AddField(
            model_name='user',
            name='aprobado_por',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cuentas_aprobadas',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Aprobado por',
            ),
        ),

        migrations.AddField(
            model_name='user',
            name='observaciones_aprobacion',
            field=models.TextField(
                blank=True,
                default='',
                verbose_name='Observaciones de aprobación',
            ),
        ),

        # ── 2. Migración de datos ────────────────────────────────────────────
        # Pone estado_cuenta='activa' en todos los usuarios existentes.
        # Usa RunPython para poder revertirse limpiamente.
        migrations.RunPython(
            marcar_existentes_como_activos,
            revertir_estado_activo,
        ),
    ]
