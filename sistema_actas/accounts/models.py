from django.contrib.auth.models import AbstractUser, BaseUserManager #Importacion del modelo base de usrio de Django
from django.db import models #Importacion de utilidades de modelos Django
from django.core.validators import validate_email # Validar emails de Django
from django.contrib.auth.validators import UnicodeUsernameValidator
from PIL import Image #Libreria pillow para trabajar con imagenes (Para firma digital)
import os
import logging
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def validar_firma_digital(archivo):
    """Valida que la firma digital sea una imagen válida (JPG/PNG/WEBP) de máximo 2MB."""
    extensiones_permitidas = ['jpg', 'jpeg', 'png', 'webp']
    ext = os.path.splitext(archivo.name)[1].lower().lstrip('.')
    if ext not in extensiones_permitidas:
        raise ValidationError(f'Solo se permiten imágenes JPG, PNG o WEBP. Formato recibido: {ext}')
    if archivo.size > 2 * 1024 * 1024:
        raise ValidationError('La imagen de firma no puede superar 2 MB.')


class UsernameValidator(UnicodeUsernameValidator):
    """Validador de username que permite espacios además de los caracteres estándar."""
    regex = r'^[\w\s.@+-]+$'
    message = 'El nombre de usuario solo puede contener letras, números, espacios y los caracteres @/./+/-/_'


# Opciones de tipo de documento de identidad en Colombia
TIPO_DOCUMENTO_CHOICES = [
    ('CC', 'Cédula de Ciudadanía'),
    ('TI', 'Tarjeta de Identidad'),
    ('CE', 'Cédula de Extranjería'),
    ('PA', 'Pasaporte'),
    ('OTRO', 'Otro'),
]

# Estados posibles para una cuenta de usuario
ESTADO_CUENTA_CHOICES = [
    ('activa', 'Activa'),
    ('pendiente_aprobacion', 'Pendiente de aprobación'),
    ('rechazada', 'Rechazada'),
    ('suspendida', 'Suspendida'),
]


class UserManager(BaseUserManager):
    """Manager personalizado que garantiza campos correctos para superusuarios."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('El correo electrónico es obligatorio.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Crea un superusuario con todos los campos de acceso correctos."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('rol', 'admin')
        extra_fields.setdefault('email_verificado', True)
        extra_fields.setdefault('cuenta_aprobada', True)
        extra_fields.setdefault('activo', True)
        extra_fields.setdefault('estado_cuenta', 'activa')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('El superusuario debe tener is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('El superusuario debe tener is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


#Modelo personalizado de usuario
class User (AbstractUser) :
    username = models.CharField(
        max_length=150,
        unique=True,
        validators=[UsernameValidator()],
        error_messages={'unique': 'Ya existe un usuario con ese nombre de usuario.'},
    )
    ROLES = [
        ('aprendiz', 'Aprendiz'),
        ('instructor', 'Instructor'),
        ('invitado', 'Invitado'),
        ('funcionario', 'Funcionario'),
        ('coordinador', 'Coordinador'),
        ('director', 'Director'),
        ('admin', 'Administrador'),
    ]

    #Sobreescribimos algunos campos de AbstractUser y agrego nuevos campos
    email = models.EmailField (unique=True, validators=[validate_email])
    rol = models.CharField (max_length=20, choices=ROLES, default='invitado')
    centro = models.CharField(max_length=100, default='Centro Minero')
    telefono = models.CharField (max_length=15, blank=True)
    firma_digital = models.ImageField(upload_to='firmas/', blank=True, null=True, validators=[validar_firma_digital])
    fecha_registro = models.DateTimeField(auto_now_add=True) #Fecha de creacion automatica
    activo = models.BooleanField (default=True) #Estado del usuario activo/inactivo

    # Documento de identidad — identificador institucional único
    tipo_documento = models.CharField(
        max_length=10,
        choices=TIPO_DOCUMENTO_CHOICES,
        blank=True,
        default='',
        verbose_name='Tipo de documento',
    )
    numero_documento = models.CharField(
        max_length=50,
        unique=True,
        null=True,       # null=True permite que usuarios existentes no tengan documento aún
        blank=True,
        verbose_name='Número de documento',
        help_text='Número único de identificación (CC, TI, CE, etc.). Es el identificador de login.',
    )

    # Ficha de formación — solo aplica para aprendices
    # 'formacion.Ficha' es una referencia en texto para evitar importaciones circulares
    ficha = models.ForeignKey(
        'formacion.Ficha',
        on_delete=models.SET_NULL,   # Si se elimina la ficha, el usuario queda sin ficha (no se borra)
        null=True,
        blank=True,
        related_name='aprendices',
        verbose_name='Ficha de formación',
        help_text='Solo para aprendices. Ficha (grupo) a la que pertenece.',
    )

    # Nuevos campos para verificación y aprobación
    email_verificado = models.BooleanField(default=False, help_text='Indica si el usuario verificó su email')
    cuenta_aprobada = models.BooleanField(default=False, help_text='Indica si la cuenta está aprobada para uso')

    # Estado de la cuenta con trazabilidad de aprobación
    estado_cuenta = models.CharField(
        max_length=25,
        choices=ESTADO_CUENTA_CHOICES,
        default='activa',
        verbose_name='Estado de la cuenta',
    )
    fecha_aprobacion = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de aprobación',
        help_text='Se rellena automáticamente cuando el admin aprueba la cuenta',
    )
    # ForeignKey a sí mismo: guarda quién fue el admin que aprobó
    aprobado_por = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cuentas_aprobadas',
        verbose_name='Aprobado por',
    )
    observaciones_aprobacion = models.TextField(
        blank=True,
        default='',
        verbose_name='Observaciones de aprobación',
        help_text='Notas del administrador sobre la aprobación o rechazo',
    )

    objects = UserManager()

    #Configuracion de login: se usara el email en lugar de username
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name'] #Campos obligatorios
    
    #Metadatos del proyecto
    class Meta:
        verbose_name = 'Usuario' #Nombre singular del admin
        verbose_name_plural = 'Usuarios' #Nombre plural en el admin
        ordering = ['first_name', 'last_name'] #Orden por nombre y apellido
        indexes = [
            models.Index(fields=['rol'], name='accounts_user_rol_idx'),
        ]

    #Validaciones personalizadas segun el rol
    def clean(self):
        super().clean()

        # Validación para aprendices
        if self.rol == 'aprendiz':
            if not self.email.endswith('@soy.sena.edu.co'):
                raise ValidationError(
                    "El correo del aprendiz debe ser institucional @soy.sena.edu.co"
                )

        # Validación para instructores
        elif self.rol == 'instructor':
            if not self.email.endswith('@sena.edu.co'):
                raise ValidationError(
                    "El correo del instructor debe ser institucional @sena.edu.co"
                )

        # Validación para funcionarios, coordinadores y directores
        elif self.rol in ['funcionario', 'coordinador', 'director']:
            dominios_validos = ['@sena.edu.co', '@gmail.com']
            if not any(self.email.endswith(d) for d in dominios_validos):
                raise ValidationError(
                    "El correo debe ser institucional @sena.edu.co o @gmail.com"
                )

        # Validación especial para administradores
        elif self.rol == 'admin' and not (self.is_staff and self.is_superuser):
            raise ValidationError(
                "Solo los superusuarios pueden tener el rol de Administrador"
            )

        # Rol invitado puede tener cualquier email (sin restricciones)
    #Guardado Personalizado
    def save (self, *args, **kwargs):
        #Redimensionar firma digital si es muy grade
        super().save(*args, **kwargs)

        if self.rol == 'admin':
            self.is_staff = True
            self.is_superuser = True
            super().save(*args, **kwargs)
        else:
            # Si el rol ya no es admin, revocar permisos de Django admin
            if self.is_staff or self.is_superuser:
                self.is_staff = False
                self.is_superuser = False
                super().save(*args, **kwargs)

        if self.firma_digital:
            import os
            if os.path.exists(self.firma_digital.path):
                img = Image.open(self.firma_digital.path)
                if img.height > 200 or img.width > 400:
                    img.thumbnail((400, 200))
                    img.save(self.firma_digital.path)
    
    #Retorna nombre completo del usuario
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    
    #Representacion en texto del usuario
    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"
    
class PasswordResetCode(models.Model):
    """
    Modelo para almacenar códigos de recuperación de contraseña
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_codes')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']

    def is_valid(self):
        """Verifica si el código aún es válido"""
        from django.utils import timezone
        return not self.used and timezone.now() < self.expires_at

    def __str__(self):
        return f"Código {self.code} para {self.user.email}"


class CodigoVerificacion(models.Model):
    """
    Modelo para almacenar códigos de verificación de email
    Usado tanto para registro como para recuperación de contraseña
    """
    TIPO_CHOICES = [
        ('registro', 'Registro'),
        ('recuperacion', 'Recuperación de contraseña'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='codigos_verificacion')
    codigo = models.CharField(max_length=6, help_text='Código de 6 dígitos numéricos')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='registro')
    usado = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_expiracion = models.DateTimeField()

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Código de Verificación'
        verbose_name_plural = 'Códigos de Verificación'

    def is_valid(self):
        """Verifica si el código aún es válido (no usado y no expirado)"""
        from django.utils import timezone
        return not self.usado and timezone.now() < self.fecha_expiracion

    def marcar_usado(self):
        """Marca el código como usado"""
        self.usado = True
        self.save()

    def __str__(self):
        return f"Código {self.codigo} ({self.tipo}) para {self.user.email}"