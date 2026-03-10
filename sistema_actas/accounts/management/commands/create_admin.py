"""
Management command para crear o restablecer el usuario administrador.
Lee las credenciales desde variables de entorno ADMIN_EMAIL y ADMIN_PASSWORD.

Se ejecuta automáticamente al iniciar el contenedor Docker (ver Dockerfile CMD).

Uso manual:
    python manage.py create_admin
    ADMIN_EMAIL=admin@sena.edu.co ADMIN_PASSWORD=MiClave123 python manage.py create_admin
"""
import os
from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    help = 'Crea o actualiza el usuario administrador desde variables de entorno'

    def handle(self, *args, **options):
        email = os.environ.get('ADMIN_EMAIL', '').strip()
        password = os.environ.get('ADMIN_PASSWORD', '').strip()

        if not email or not password:
            self.stdout.write(
                self.style.WARNING(
                    'ADMIN_EMAIL y ADMIN_PASSWORD no están configuradas. '
                    'Saltando creación de admin.'
                )
            )
            return

        reset_password = os.environ.get('RESET_ADMIN_PASSWORD', '').strip().lower() == 'true'

        try:
            user = User.objects.get(email=email)
            update_fields = dict(
                is_active=True,
                is_staff=True,
                is_superuser=True,
                rol='admin',
                email_verificado=True,
                cuenta_aprobada=True,
                activo=True,
            )
            if reset_password:
                user.set_password(password)
                update_fields['password'] = user.password
                self.stdout.write(self.style.SUCCESS(f'Contraseña reseteada: {email}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Admin ya existe, permisos verificados: {email}'))
            User.objects.filter(pk=user.pk).update(**update_fields)

        except User.DoesNotExist:
            # El usuario no existe — crearlo
            user = User(
                email=email,
                username='Admin SENA',
                first_name='Admin',
                last_name='SENA',
                is_active=True,
                is_staff=True,
                is_superuser=True,
                rol='admin',
                email_verificado=True,
                cuenta_aprobada=True,
                activo=True,
            )
            user.set_password(password)
            # Usar update_or_create en caso de colisión de username
            counter = 1
            while User.objects.filter(username=user.username).exists():
                user.username = f'Admin SENA {counter}'
                counter += 1
            # Guardar directamente sin pasar por clean() para evitar validación de rol
            User.objects.bulk_create([user])
            self.stdout.write(
                self.style.SUCCESS(f'Admin creado correctamente: {email}')
            )
