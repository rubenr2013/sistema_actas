from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont
import io 

User = get_user_model()

class Command(BaseCommand):
    help = 'Crear usuarios de demostración para el sistema'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Eliminar usuarios existentes primero',
        )
    
    def handle(self, *args, **options):
        if options['reset']:
            User.objects.filter(email__endswith='@sena.edu.co').exclude(is_superuser=True).delete()
            self.stdout.write(self.style.SUCCESS('Usuarios anteriores eliminados'))
        
        usuarios_demo = [
            {
                'email': 'coordinador.minero@sena.edu.co',
                'username': 'coordinador.minero',
                'first_name': 'Carlos',
                'last_name': 'Rodríguez',
                'rol': 'coordinador',
                'password': 'Demo2024!'
            },
            {
                'email': 'instructor.geologia@sena.edu.co',
                'username': 'instructor.geologia',
                'first_name': 'María',
                'last_name': 'García',
                'rol': 'funcionario',
                'password': 'Demo2024!'
            },
            {
                'email': 'instructor.seguridad@sena.edu.co',
                'username': 'instructor.seguridad',
                'first_name': 'Juan',
                'last_name': 'Pérez',
                'rol': 'funcionario',
                'password': 'Demo2024!'
            },
            {
                'email': 'director.centro@sena.edu.co',
                'username': 'director.centro',
                'first_name': 'Ana',
                'last_name': 'Martínez',
                'rol': 'director',
                'password': 'Demo2024!'
            },
            {
                'email': 'admin.sistema@sena.edu.co',
                'username': 'admin.sistema',
                'first_name': 'Luis',
                'last_name': 'Torres',
                'rol': 'admin',
                'password': 'Demo2024!',
                'is_staff': True
            }
        ]
        
        for user_data in usuarios_demo:
            user, created = User.objects.get_or_create(
                email=user_data['email'],
                defaults={
                    'username': user_data['username'],
                    'first_name': user_data['first_name'],
                    'last_name': user_data['last_name'],
                    'rol': user_data['rol'],
                    'is_staff': user_data.get('is_staff', False),
                    'activo': True
                }
            )
            
            if created:
                user.set_password(user_data['password'])
                
                # Generar firma digital simple
                firma_image = self.generar_firma_digital(f"{user_data['first_name']} {user_data['last_name']}")
                user.firma_digital.save(
                    f'firma_{user.username}.png',
                    ContentFile(firma_image),
                    save=False
                )
                
                user.save()
                
                self.stdout.write(
                    self.style.SUCCESS(f'Usuario creado: {user.email} (contraseña: {user_data["password"]})')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Usuario ya existe: {user.email}')
                )
        
        self.stdout.write(self.style.SUCCESS('\n¡Usuarios de demostración creados exitosamente!'))
    
    def generar_firma_digital(self, nombre):
        """Genera una imagen de firma digital simple"""
        # Crear imagen
        width, height = 300, 100
        image = Image.new('RGBA', (width, height), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        
        # Intentar usar una fuente cursiva, si no usar la por defecto
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except:
            font = ImageFont.load_default()
        
        # Dibujar el nombre en estilo cursiva
        text_width, text_height = draw.textsize(nombre, font=font)
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        draw.text((x, y), nombre, fill=(0, 0, 139), font=font)
        
        # Añadir una línea debajo
        draw.line([(x, y + text_height + 5), (x + text_width, y + text_height + 5)], 
                fill=(0, 0, 139), width=2)
        
        # Convertir a bytes
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()