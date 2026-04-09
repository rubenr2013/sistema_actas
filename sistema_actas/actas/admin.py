from notifications.models import Notification
from django.contrib import admin
from .models import Acta, Participante, Firma, Compromiso, ComentarioActa, ArchivoAdjunto, AnexoActa, PlantillaActa, ParticipanteNoRegistrado


class AnexoActaInline(admin.TabularInline):
    model = AnexoActa
    extra = 0
    fields = ('archivo', 'nombre_archivo', 'orden', 'cargado_por', 'fecha_carga')
    readonly_fields = ('fecha_carga',)
    ordering = ('orden', 'fecha_carga')


@admin.register(Acta)
class ActaAdmin(admin.ModelAdmin):
    list_display = ('numero_acta', 'titulo', 'tipo_reunion', 'fecha_reunion', 'estado', 'creador', 'ciclo_revision')
    list_filter = ('estado', 'tipo_reunion', 'fecha_reunion')
    search_fields = ('numero_acta', 'titulo', 'desarrollo')
    inlines = [AnexoActaInline]

@admin.register(Participante)
class ParticipanteAdmin(admin.ModelAdmin):
    list_display = ('acta', 'usuario', 'rol_en_reunion', 'obligatorio_firma')
    list_filter = ('acta', 'obligatorio_firma')
    search_fields = ('acta__numero_acta', 'usuario__email')

@admin.register(Firma)
class FirmaAdmin(admin.ModelAdmin):
    list_display = ('acta', 'usuario', 'firmado', 'fecha_firma')
    list_filter = ('firmado', 'fecha_firma')
    search_fields = ('acta__numero_acta', 'usuario__email')

@admin.register(Compromiso)
class CompromisoAdmin(admin.ModelAdmin):
    list_display = ('acta', 'descripcion', 'responsable', 'fecha_limite', 'estado')
    list_filter = ('estado', 'fecha_limite')
    search_fields = ('acta__numero_acta', 'descripcion', 'responsable__email')

@admin.register(ComentarioActa)
class ComentarioActaAdmin(admin.ModelAdmin):
    list_display = ('acta', 'autor', 'fecha')
    search_fields = ('acta__numero_acta', 'autor__email')

@admin.register(ArchivoAdjunto)
class ArchivoAdjuntoAdmin(admin.ModelAdmin):
    list_display = ('nombre_original', 'acta', 'tipo_archivo', 'tamaño_legible', 'subido_por', 'fecha_subida')
    list_filter = ('tipo_archivo', 'fecha_subida')
    search_fields = ('nombre_original', 'acta__numero_acta', 'subido_por__email', 'descripcion')
    readonly_fields = ('tamaño_bytes', 'fecha_subida')


@admin.register(AnexoActa)
class AnexoActaAdmin(admin.ModelAdmin):
    list_display = ('nombre_archivo', 'acta', 'orden', 'cargado_por', 'fecha_carga')
    list_filter = ('fecha_carga',)
    search_fields = ('nombre_archivo', 'acta__numero_acta', 'cargado_por__email')
    readonly_fields = ('fecha_carga',)
    ordering = ('acta', 'orden')


@admin.register(PlantillaActa)
class PlantillaActaAdmin(admin.ModelAdmin):
    list_display = ('tipo_reunion', 'nombre', 'activa', 'creada_por', 'fecha_creacion', 'fecha_modificacion')
    list_filter = ('activa', 'tipo_reunion')
    search_fields = ('nombre', 'descripcion')
    readonly_fields = ('fecha_creacion', 'fecha_modificacion', 'creada_por')

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.creada_por = request.user
        super().save_model(request, obj, form, change)

@admin.register(ParticipanteNoRegistrado)
class ParticipanteNoRegistradoAdmin(admin.ModelAdmin):
    list_display = ('nombre_completo', 'email', 'acta', 'cargo_rol', 'pdf_enviado', 'email_rebotado', 'fecha_envio')
    list_filter = ('pdf_enviado', 'email_rebotado')
    search_fields = ('nombre_completo', 'email', 'acta__numero_acta')
    readonly_fields = ('fecha_creacion', 'fecha_envio')
