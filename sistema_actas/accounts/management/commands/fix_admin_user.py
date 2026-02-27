"""
Management command para corregir usuarios administradores en producción.

Uso:
    python manage.py fix_admin_user
    python manage.py fix_admin_user --email admin@sena.edu.co
    python manage.py fix_admin_user --email admin@sena.edu.co --password NuevaContraseña123

Este comando busca todos los superusuarios (is_superuser=True) y corrige
sus campos: email_verificado=True, cuenta_aprobada=True, rol='admin', activo=True.
"""
from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    help = 'Corrige los campos de acceso de los usuarios administradores'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            help='Email del admin específico a corregir (por defecto corrige todos los superusuarios)',
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Nueva contraseña para el admin (opcional)',
        )

    def handle(self, *args, **options):
        email = options.get('email')
        password = options.get('password')

        if email:
            usuarios = User.objects.filter(email=email)
            if not usuarios.exists():
                self.stdout.write(self.style.ERROR(f'No se encontró ningún usuario con email: {email}'))
                return
        else:
            # Corregir todos los superusuarios
            usuarios = User.objects.filter(is_superuser=True)
            if not usuarios.exists():
                self.stdout.write(self.style.WARNING('No se encontraron superusuarios en la base de datos.'))
                return

        for user in usuarios:
            cambios = []

            if not user.email_verificado:
                user.email_verificado = True
                cambios.append('email_verificado=True')

            if not user.cuenta_aprobada:
                user.cuenta_aprobada = True
                cambios.append('cuenta_aprobada=True')

            if user.rol != 'admin':
                user.rol = 'admin'
                cambios.append('rol=admin')

            if not user.activo:
                user.activo = True
                cambios.append('activo=True')

            if not user.is_active:
                user.is_active = True
                cambios.append('is_active=True')

            if password:
                user.set_password(password)
                cambios.append('contraseña actualizada')

            # Guardar sin llamar clean() para evitar problemas de validación
            User.objects.filter(pk=user.pk).update(
                email_verificado=user.email_verificado,
                cuenta_aprobada=user.cuenta_aprobada,
                rol=user.rol,
                activo=user.activo,
                is_active=user.is_active,
                is_staff=True,
                is_superuser=True,
            )

            if password:
                # set_password requiere save() para actualizar el hash
                u = User.objects.get(pk=user.pk)
                u.set_password(password)
                User.objects.filter(pk=user.pk).update(password=u.password)

            if cambios:
                self.stdout.write(
                    self.style.SUCCESS(f'Usuario {user.email} corregido: {", ".join(cambios)}')
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f'Usuario {user.email} ya estaba configurado correctamente.')
                )

        self.stdout.write(self.style.SUCCESS('\nProceso completado. Ahora puedes iniciar sesión desde Flutter.'))
