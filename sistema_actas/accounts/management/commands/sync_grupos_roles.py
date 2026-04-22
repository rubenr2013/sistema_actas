from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from accounts.models import User


ROL_A_GROUP = {
    'aprendiz':    'Aprendiz',
    'instructor':  'Instructor',
    'invitado':    'Invitado',
    'funcionario': 'Funcionario',
    'coordinador': 'Coordinador',
    'director':    'Director',
    'admin':       'Administrador',
}


class Command(BaseCommand):
    help = 'Sincroniza todos los usuarios al Group de Django correspondiente a su rol.'

    def handle(self, *args, **options):
        nombres_roles = set(ROL_A_GROUP.values())

        # Asegurar que existan los grupos
        for nombre in nombres_roles:
            Group.objects.get_or_create(name=nombre)

        usuarios = User.objects.all()
        actualizados = 0

        for user in usuarios:
            nombre_grupo = ROL_A_GROUP.get(user.rol)
            if not nombre_grupo:
                continue

            # Quitar de todos los grupos de rol
            user.groups.remove(*user.groups.filter(name__in=nombres_roles))

            # Agregar al grupo correcto
            grupo = Group.objects.get(name=nombre_grupo)
            user.groups.add(grupo)
            actualizados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Sincronización completada: {actualizados} usuario(s) actualizados.'
            )
        )
