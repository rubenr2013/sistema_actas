"""
Migration 0011: Añade campo tipo_acta al modelo Acta para prompts IA especializados.
El campo es opcional (default='reunion_general') para no afectar actas existentes.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('actas', '0010_anexoacta'),
    ]

    operations = [
        migrations.AddField(
            model_name='acta',
            name='tipo_acta',
            field=models.CharField(
                choices=[
                    ('comite_academico',   'Comité Académico'),
                    ('comite_evaluacion',  'Comité de Evaluación y Seguimiento'),
                    ('comite_convivencia', 'Comité de Convivencia'),
                    ('reunion_coordinacion', 'Reunión de Coordinación'),
                    ('reunion_instructores', 'Reunión de Instructores'),
                    ('reunion_general',    'Reunión General'),
                ],
                default='reunion_general',
                max_length=25,
                help_text='Tipo de acta para generación de contenido especializado con IA',
            ),
        ),
    ]
