from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, PasswordResetCode


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # Columnas visibles en el listado de usuarios
    list_display = [
        'email', 'get_full_name', 'rol', 'estado_cuenta',
        'email_verificado', 'activo', 'fecha_registro',
    ]

    # Filtros en la barra lateral
    list_filter = ['rol', 'estado_cuenta', 'email_verificado', 'activo']

    # Campos por los que se puede buscar
    search_fields = ['email', 'first_name', 'last_name', 'numero_documento']

    # Ordenar por nombre
    ordering = ['first_name', 'last_name']

    # Permite cambiar 'activo' directamente desde el listado
    list_editable = ['activo']

    # Campos de solo lectura
    readonly_fields = ['fecha_registro', 'fecha_aprobacion', 'aprobado_por']

    # Formulario de edición: extiende los fieldsets de Django por defecto
    fieldsets = UserAdmin.fieldsets + (
        ('Datos SENA', {
            'fields': (
                'rol', 'centro', 'telefono',
                'tipo_documento', 'numero_documento',
                'ficha', 'firma_digital', 'activo',
            )
        }),
        ('Verificación y estado de cuenta', {
            'fields': (
                'email_verificado', 'cuenta_aprobada',
                'estado_cuenta', 'fecha_aprobacion',
                'aprobado_por', 'observaciones_aprobacion',
            )
        }),
    )

    # Formulario de creación de nuevo usuario
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Datos adicionales', {
            'fields': ('email', 'first_name', 'last_name', 'rol'),
        }),
    )


@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = ['user', 'code', 'created_at', 'expires_at', 'used']
    list_filter = ['used', 'created_at']
    search_fields = ['user__email', 'code']
    readonly_fields = ['created_at']
