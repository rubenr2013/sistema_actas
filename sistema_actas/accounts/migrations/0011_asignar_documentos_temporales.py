"""
Migración de datos: asigna un número de documento temporal a los usuarios
que existían antes de que se agregara el campo numero_documento.

Formato: TEMP0001, TEMP0002, TEMP0003...

Los administradores del sistema deben actualizar estos valores
ingresando al panel de administración y editando cada usuario.
"""

from django.db import migrations


def asignar_documentos_temporales(apps, schema_editor):
    """
    Recorre todos los usuarios que no tienen numero_documento
    y les asigna un valor temporal único para que sigan pudiendo
    usar el sistema mientras completan su perfil.
    """
    User = apps.get_model('accounts', 'User')

    # Filtrar solo los usuarios sin documento asignado
    usuarios_sin_documento = User.objects.filter(numero_documento__isnull=True)

    contador = 1
    for usuario in usuarios_sin_documento:
        # Formato: TEMP0001, TEMP0002, etc. (rellena con ceros a la izquierda)
        documento_temporal = f'TEMP{contador:04d}'

        # Asegurar que el temporal no colisione si ya existiera por alguna razón
        while User.objects.filter(numero_documento=documento_temporal).exists():
            contador += 1
            documento_temporal = f'TEMP{contador:04d}'

        usuario.numero_documento = documento_temporal
        usuario.save()
        contador += 1


def revertir_documentos_temporales(apps, schema_editor):
    """
    Si se revierte la migración, volvemos a dejar los documentos temporales
    como null para que la migración anterior los pueda eliminar limpiamente.
    """
    User = apps.get_model('accounts', 'User')
    # Solo revertir los que empiecen con TEMP (los que pusimos nosotros)
    User.objects.filter(numero_documento__startswith='TEMP').update(numero_documento=None)


class Migration(migrations.Migration):

    dependencies = [
        # Depende de la migración anterior que creó los campos
        ('accounts', '0010_add_documento_fields'),
    ]

    operations = [
        migrations.RunPython(
            asignar_documentos_temporales,
            revertir_documentos_temporales,
        ),
    ]
