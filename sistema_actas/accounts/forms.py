from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import Group, Permission
from .models import User, TIPO_DOCUMENTO_CHOICES

class CustomUserCreationForm(UserCreationForm):
    firma_digital = forms.ImageField(
        required=True,
        label="Firma Digital",
        help_text="Sube una imagen de tu firma (PNG, JPG o JPEG, máx. 2 MB). Es obligatoria.",
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/png,image/jpeg'})
    )

    # Choices con opción vacía inicial para la validación del select
    tipo_documento = forms.ChoiceField(
        choices=[('', 'Selecciona el tipo de documento...')] + TIPO_DOCUMENTO_CHOICES,
        required=True,
        label="Tipo de Documento",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    numero_documento = forms.CharField(
        max_length=50,
        required=True,
        label="Número de Documento",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ingresa tu número de documento',
            'autocomplete': 'off',
        })
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'telefono', 'tipo_documento', 'numero_documento', 'firma_digital']

    def clean_tipo_documento(self):
        tipo = self.cleaned_data.get('tipo_documento', '').strip()
        if not tipo:
            raise forms.ValidationError("Selecciona el tipo de documento.")
        return tipo

    def clean_numero_documento(self):
        numero = self.cleaned_data.get('numero_documento', '').strip()
        if not numero:
            raise forms.ValidationError("El número de documento es obligatorio.")
        # Verificar que no esté ya registrado
        if User.objects.filter(numero_documento=numero).exists():
            raise forms.ValidationError("Este número de documento ya está registrado.")
        return numero

    def clean_email(self):
        email = self.cleaned_data.get("email", "").lower()

        # Validar que el email no esté ya registrado
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Este correo ya está registrado.")

        # Validar formato de dominios permitidos
        dominios_validos = ['@soy.sena.edu.co', '@sena.edu.co', '@gmail.com', '@hotmail.com', '@outlook.com']
        if not any(email.endswith(d) for d in dominios_validos):
            raise forms.ValidationError(
                "El correo debe ser @soy.sena.edu.co, @sena.edu.co o un correo externo válido (gmail, hotmail, outlook)"
            )

        return email

    def clean_telefono(self):
        telefono = self.cleaned_data.get("telefono", "").strip()

        # Si está vacío, es opcional
        if not telefono:
            return telefono

        # Validar que solo contenga números
        if not telefono.isdigit():
            raise forms.ValidationError("El teléfono debe contener solo números.")

        # Validar que tenga exactamente 10 dígitos
        if len(telefono) != 10:
            raise forms.ValidationError("El teléfono debe tener exactamente 10 dígitos.")

        return telefono

    def clean_firma_digital(self):
        firma = self.cleaned_data.get("firma_digital")
        if not firma:
            raise forms.ValidationError("La firma digital es obligatoria para registrarse.")
        if firma.size > 2 * 1024 * 1024:
            raise forms.ValidationError("La firma no debe superar los 2 MB.")
        if not firma.name.lower().endswith((".png", ".jpg", ".jpeg")):
            raise forms.ValidationError("Solo se permiten archivos PNG, JPG o JPEG.")
        return firma

class CustomAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Correo Institucional",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "id": "email",
            "placeholder": "usuario@sena.edu.co o usuario@gmail.com",
        })
    )
    password = forms.CharField(
        label="Contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "id": "password",
            "placeholder": "Contraseña",
        }),
    )

    def confirm_login_allowed(self, user):
        if not user.activo:
            raise forms.ValidationError("La cuenta está inactiva", code="inactive")
        

class ProfileUpdateForm(forms.ModelForm):
    password = forms.CharField(
        label="Nueva Contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Deja vacío si no deseas cambiarla'
        }),
        required=False
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'telefono', 'firma_digital', 'password']  # 👈 agregamos 'password'
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'firma_digital': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password and len(password) < 8:
            raise forms.ValidationError("La contraseña debe tener al menos 8 caracteres.")
        return password


    def clean_email(self):
        email = self.cleaned_data.get('email').lower()
        dominios_validos = ['@sena.edu.co', '@soy.sena.edu.co', '@gmail.com']

        # ✅ Solo valida si el usuario cambió el correo
        if email != self.instance.email:
            if not any(email.endswith(d) for d in dominios_validos):
                raise forms.ValidationError("El correo debe ser institucional @sena.edu.co o @gmail.com")
        return email


    def clean_firma_digital(self):
        firma = self.cleaned_data.get("firma_digital")
        if not firma:
            return firma
        # Solo validar si es un archivo recién subido (tiene método read)
        if hasattr(firma, 'read'):
            if firma.size > 2 * 1024 * 1024:
                raise forms.ValidationError("El archivo no debe superar los 2 MB.")
            if not firma.name.lower().endswith((".png", ".jpg", ".jpeg")):
                raise forms.ValidationError("Solo se permiten imágenes PNG, JPG o JPEG.")
        # Si es un FieldFile existente no tocamos .size (el archivo puede no estar en disco)
        return firma


# Permisos visibles y sus etiquetas amigables en la UI de gestión de roles
PERMISOS_UI = {
    'Actas': [
        ('actas.view_acta', 'Ver actas'),
        ('actas.add_acta', 'Crear actas'),
        ('actas.change_acta', 'Editar actas'),
        ('actas.delete_acta', 'Eliminar actas'),
        ('actas.aprobar_acta', 'Aprobar actas'),
        ('actas.rechazar_acta', 'Rechazar actas'),
        ('actas.enviar_a_revision', 'Enviar actas a revisión'),
        ('actas.generar_pdf_acta', 'Generar PDF de actas'),
        ('actas.firmar_acta', 'Firmar actas'),
        ('actas.can_finalize_acta', 'Finalizar actas'),
        ('actas.can_archive_acta', 'Archivar actas'),
        ('actas.can_generate_with_ia', 'Generar actas con IA'),
    ],
    'Compromisos': [
        ('actas.view_compromiso', 'Ver compromisos'),
        ('actas.add_compromiso', 'Crear compromisos'),
        ('actas.change_compromiso', 'Editar compromisos'),
        ('actas.delete_compromiso', 'Eliminar compromisos'),
    ],
    'Plantillas': [
        ('actas.view_plantillaacta', 'Ver plantillas de acta'),
        ('actas.add_plantillaacta', 'Crear plantillas de acta'),
        ('actas.change_plantillaacta', 'Editar plantillas de acta'),
        ('actas.delete_plantillaacta', 'Eliminar plantillas de acta'),
    ],
    'Usuarios': [
        ('accounts.view_user', 'Ver usuarios'),
        ('accounts.change_user', 'Editar usuarios'),
        ('accounts.delete_user', 'Eliminar usuarios'),
    ],
}


def get_permission_obj(app_label, codename):
    """Retorna el objeto Permission dado app_label y codename, o None."""
    try:
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)
    except Permission.DoesNotExist:
        return None


class RolForm(forms.ModelForm):
    """Formulario para crear/editar un rol (Group) con selección visual de permisos."""

    descripcion = forms.CharField(
        required=False,
        label="Descripción",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Descripción opcional del rol...',
        })
    )

    class Meta:
        model = Group
        fields = ['name']
        labels = {'name': 'Nombre del rol'}
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Revisor de actas',
            })
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError("El nombre es obligatorio.")
        qs = Group.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ya existe un rol con ese nombre.")
        return name