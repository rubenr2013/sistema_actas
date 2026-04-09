"""
Management command: crear_roles_sistema
Crea los grupos (roles) del sistema si no existen.
Ejecutar después de migrate en un despliegue nuevo.

Uso:
    python manage.py crear_roles_sistema
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group


ROLES_SISTEMA = [
    'Administrador',
    'Coordinador',
    'Instructor',
    'Funcionario',
    'Director',
    'Invitado',
]


class Command(BaseCommand):
    help = 'Crea los grupos (roles) del sistema si no existen.'

    def handle(self, *args, **options):
        creados = []
        for nombre in ROLES_SISTEMA:
            _, created = Group.objects.get_or_create(name=nombre)
            if created:
                creados.append(nombre)

        if creados:
            self.stdout.write(self.style.SUCCESS(f"Roles creados: {', '.join(creados)}"))
        else:
            self.stdout.write("Todos los roles del sistema ya existen.")
