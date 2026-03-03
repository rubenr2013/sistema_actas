from django.contrib import admin
from .models import Programa, Ficha


@admin.register(Programa)
class ProgramaAdmin(admin.ModelAdmin):
    # Columnas visibles en el listado
    list_display = ['nombre', 'codigo', 'total_fichas', 'activo', 'fecha_creacion']

    # Filtros en la barra lateral derecha
    list_filter = ['activo']

    # Campos por los que se puede buscar
    search_fields = ['nombre', 'codigo']

    # Permite editar 'activo' directamente desde el listado
    list_editable = ['activo']

    # Acciones masivas disponibles en el desplegable "Acción"
    actions = ['activar_programas', 'desactivar_programas']

    def total_fichas(self, obj):
        """Muestra cuántas fichas tiene el programa en el listado del admin."""
        return obj.fichas.count()
    total_fichas.short_description = 'Total fichas'

    def activar_programas(self, request, queryset):
        """Activa todos los programas seleccionados de una sola vez."""
        cantidad = queryset.update(activo=True)
        self.message_user(request, f'{cantidad} programa(s) activado(s).')
    activar_programas.short_description = 'Activar programas seleccionados'

    def desactivar_programas(self, request, queryset):
        """Desactiva todos los programas seleccionados de una sola vez."""
        cantidad = queryset.update(activo=False)
        self.message_user(request, f'{cantidad} programa(s) desactivado(s).')
    desactivar_programas.short_description = 'Desactivar programas seleccionados'


@admin.register(Ficha)
class FichaAdmin(admin.ModelAdmin):
    # Columnas visibles en el listado
    list_display = ['numero', 'programa', 'fecha_inicio', 'fecha_fin', 'activa']

    # Filtros en la barra lateral derecha
    list_filter = ['activa', 'programa']

    # Campos por los que se puede buscar
    search_fields = ['numero', 'programa__nombre', 'programa__codigo']

    # Permite editar 'activa' directamente desde el listado
    list_editable = ['activa']

    # Acciones masivas disponibles en el desplegable "Acción"
    actions = ['activar_fichas', 'desactivar_fichas']

    def activar_fichas(self, request, queryset):
        """Activa todas las fichas seleccionadas de una sola vez."""
        cantidad = queryset.update(activa=True)
        self.message_user(request, f'{cantidad} ficha(s) activada(s).')
    activar_fichas.short_description = 'Activar fichas seleccionadas'

    def desactivar_fichas(self, request, queryset):
        """Desactiva todas las fichas seleccionadas de una sola vez."""
        cantidad = queryset.update(activa=False)
        self.message_user(request, f'{cantidad} ficha(s) desactivada(s).')
    desactivar_fichas.short_description = 'Desactivar fichas seleccionadas'
