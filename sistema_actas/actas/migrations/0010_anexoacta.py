"""
Migration 0010: AnexoActa — Anexos PDF que se fusionan al generar el PDF del acta.
"""

import actas.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('actas', '0009_acta_revision_colaborativa'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AnexoActa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('archivo', models.FileField(
                    help_text='Archivo PDF del anexo (máx. 10 MB)',
                    upload_to='actas/anexos/%Y/%m/',
                    validators=[actas.models.validar_pdf_anexo],
                )),
                ('nombre_archivo', models.CharField(
                    help_text='Nombre original del archivo PDF',
                    max_length=255,
                )),
                ('orden', models.IntegerField(
                    default=0,
                    help_text='Posición del anexo dentro del PDF consolidado (0 = primero)',
                )),
                ('fecha_carga', models.DateTimeField(auto_now_add=True)),
                ('acta', models.ForeignKey(
                    help_text='Acta a la que pertenece el anexo',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='anexos',
                    to='actas.acta',
                )),
                ('cargado_por', models.ForeignKey(
                    help_text='Usuario que subió el anexo',
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='anexos_cargados',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Anexo de Acta',
                'verbose_name_plural': 'Anexos de Acta',
                'ordering': ['orden', 'fecha_carga'],
            },
        ),
        migrations.AddIndex(
            model_name='anexoacta',
            index=models.Index(fields=['acta', 'orden'], name='actas_anexo_acta_id_orden_idx'),
        ),
    ]
