from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta, datetime, date
import uuid
import os
from django.conf import settings
from accounts.models import User


# =============================================================================
# VALIDADORES DE ARCHIVOS
# =============================================================================

# Extensiones permitidas para archivos adjuntos (whitelist)
ALLOWED_FILE_EXTENSIONS = [
    # Documentos
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp',
    # Imágenes
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp',
    # Comprimidos
    'zip', 'rar', '7z',
    # Texto
    'txt', 'csv', 'rtf',
]

# Tamaño máximo de archivo en bytes (10 MB)
MAX_FILE_SIZE = 10 * 1024 * 1024

# Magic bytes (firmas de archivo) para validación de contenido real
# Esto previene que un .exe renombrado a .pdf pase la validación
MAGIC_BYTES = {
    # PDFs
    b'%PDF': ['pdf'],
    # Imágenes
    b'\xff\xd8\xff': ['jpg', 'jpeg'],  # JPEG
    b'\x89PNG\r\n\x1a\n': ['png'],  # PNG
    b'GIF87a': ['gif'],  # GIF87
    b'GIF89a': ['gif'],  # GIF89
    b'BM': ['bmp'],  # BMP
    b'RIFF': ['webp'],  # WebP (parte de RIFF)
    # Documentos Office (ZIP-based: docx, xlsx, pptx, odt, ods, odp)
    b'PK\x03\x04': ['docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp', 'zip'],
    # Documentos Office antiguos
    b'\xd0\xcf\x11\xe0': ['doc', 'xls', 'ppt'],  # OLE Compound
    # Comprimidos
    b'Rar!\x1a\x07': ['rar'],  # RAR
    b"7z\xbc\xaf'": ['7z'],  # 7z
}

# Extensiones que no tienen magic bytes consistentes (texto plano)
TEXT_EXTENSIONS = ['txt', 'csv', 'rtf']


def validar_extension_archivo(archivo):
    """
    Valida que el archivo tenga una extensión permitida.
    """
    if archivo:
        nombre = archivo.name.lower()
        extension = nombre.rsplit('.', 1)[-1] if '.' in nombre else ''

        if extension not in ALLOWED_FILE_EXTENSIONS:
            raise ValidationError(
                f'Tipo de archivo no permitido: .{extension}. '
                f'Extensiones permitidas: {", ".join(ALLOWED_FILE_EXTENSIONS)}'
            )


def validar_contenido_archivo(archivo):
    """
    Valida que el contenido real del archivo coincida con su extensión.
    Previene que archivos maliciosos (ej: .exe) se disfracen de otros tipos.
    """
    if not archivo:
        return

    nombre = archivo.name.lower()
    extension = nombre.rsplit('.', 1)[-1] if '.' in nombre else ''

    # Los archivos de texto no tienen magic bytes consistentes, solo validar extensión
    if extension in TEXT_EXTENSIONS:
        return

    # Leer los primeros bytes del archivo para verificar su tipo real
    try:
        # Guardar posición actual
        pos = archivo.tell()
        archivo.seek(0)
        header = archivo.read(16)  # Leer primeros 16 bytes
        archivo.seek(pos)  # Restaurar posición
    except Exception:
        # Si no podemos leer el archivo, permitirlo (validación básica ya pasó)
        return

    # Verificar si el contenido coincide con la extensión declarada
    extension_valida = False

    for magic, extensiones_permitidas in MAGIC_BYTES.items():
        if header.startswith(magic):
            if extension in extensiones_permitidas:
                extension_valida = True
                break
            else:
                # El contenido real no coincide con la extensión
                tipo_real = extensiones_permitidas[0].upper()
                raise ValidationError(
                    f'El contenido del archivo no coincide con su extensión. '
                    f'El archivo parece ser un {tipo_real}, no un {extension.upper()}. '
                    f'Por seguridad, este archivo ha sido rechazado.'
                )

    # Si no encontramos magic bytes conocidos pero la extensión está permitida,
    # es posible que sea un formato válido que no tenemos en nuestra lista
    # En ese caso, solo alertamos si detectamos ejecutables
    if not extension_valida:
        # Verificar que NO sea un ejecutable disfrazado
        dangerous_signatures = [
            b'MZ',  # Windows EXE/DLL
            b'\x7fELF',  # Linux ELF executable
            b'#!',  # Shell script
            b'<?php',  # PHP script
        ]
        for sig in dangerous_signatures:
            if header.startswith(sig):
                raise ValidationError(
                    'Archivo potencialmente peligroso detectado. '
                    'No se permiten ejecutables ni scripts.'
                )


def validar_tamaño_archivo(archivo):
    """
    Valida que el archivo no exceda el tamaño máximo permitido.
    """
    if archivo and archivo.size > MAX_FILE_SIZE:
        max_mb = MAX_FILE_SIZE / (1024 * 1024)
        actual_mb = archivo.size / (1024 * 1024)
        raise ValidationError(
            f'El archivo es demasiado grande ({actual_mb:.2f} MB). '
            f'Tamaño máximo permitido: {max_mb:.0f} MB'
        )


# Tamaño máximo para plantillas Word (5 MB)
MAX_PLANTILLA_SIZE = 5 * 1024 * 1024


def validar_plantilla_docx(archivo):
    """
    Valida que el archivo subido sea un .docx válido y no exceda 5 MB.
    Comprueba: extensión, tamaño, magic bytes (PK = ZIP) y que python-docx pueda abrirlo.
    """
    if not archivo:
        return

    nombre = archivo.name.lower()
    extension = nombre.rsplit('.', 1)[-1] if '.' in nombre else ''

    if extension != 'docx':
        raise ValidationError(
            'Solo se permiten archivos Word (.docx). '
            f'El archivo proporcionado tiene extensión .{extension}.'
        )

    if archivo.size > MAX_PLANTILLA_SIZE:
        actual_mb = archivo.size / (1024 * 1024)
        raise ValidationError(
            f'El archivo es demasiado grande ({actual_mb:.2f} MB). '
            'El tamaño máximo para plantillas es 5 MB.'
        )

    # Verificar magic bytes PK (ZIP) — todos los .docx son ZIP internamente
    try:
        pos = archivo.tell()
        archivo.seek(0)
        header = archivo.read(4)
        archivo.seek(pos)
    except Exception:
        return

    if not header.startswith(b'PK\x03\x04'):
        raise ValidationError(
            'El archivo no parece ser un .docx válido. '
            'Asegúrese de guardar el archivo desde Microsoft Word o LibreOffice.'
        )

    # Intentar abrirlo con python-docx para confirmar que es un Word real
    try:
        from docx import Document as DocxDocument
        import io
        pos = archivo.tell()
        archivo.seek(0)
        contenido = archivo.read()
        archivo.seek(pos)
        DocxDocument(io.BytesIO(contenido))
    except Exception:
        raise ValidationError(
            'El archivo .docx está corrupto o no se puede leer. '
            'Verifique que el archivo esté en buen estado.'
        )

User = get_user_model()

class Acta(models.Model):
    ESTADOS = [
        ('borrador', 'Borrador'),
        ('en_revision', 'En Revisión'),
        ('finalizada', 'Finalizada'),
        ('archivada', 'Archivada'),
        ('cerrada_por_vencimiento', 'Cerrada por Vencimiento'),
    ]

    TIPOS_REUNION = [
        ('consejo_academico', 'Consejo Académico'),
        ('comite_evaluacion', 'Comité de Evaluación'),
        ('coordinacion', 'Coordinación'),
        ('administrativa', 'Administrativa'),
        ('tecnica', 'Técnica'),
        ('otra', 'Otra'),
    ]

    # Tipos de acta para la generación especializada con IA
    # (importados desde actas.prompts para mantener una única fuente de verdad)
    from actas.prompts import TIPOS_ACTA as _TIPOS_ACTA
    TIPOS_ACTA = _TIPOS_ACTA
    
    # ========================================
    # CAMPOS BÁSICOS (YA EXISTENTES)
    # ========================================
    numero_acta = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Número de Acta',
        help_text='Número oficial asignado por la subdirección. Ej: ACT-2026-COORD-001',
    )
    titulo = models.CharField(max_length=200)
    tipo_reunion = models.CharField(max_length=30, choices=TIPOS_REUNION)
    tipo_reunion_otro = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Tipo de reunión personalizado',
        help_text='Solo se usa cuando tipo_reunion="otra". Especifique el tipo exacto.',
    )
    fecha_reunion = models.DateTimeField()
    lugar_reunion = models.CharField(max_length=200)
    modalidad = models.CharField(max_length=20, choices=[
        ('presencial', 'Presencial'),
        ('virtual', 'Virtual'),
        ('hibrida', 'Híbrida')
    ], default='presencial')
    
    # Estado y control
    estado = models.CharField(max_length=25, choices=ESTADOS, default='borrador')
    # Tipo de acta para prompts IA especializados
    tipo_acta = models.CharField(
        max_length=25,
        choices=_TIPOS_ACTA,
        default='reunion_general',
        help_text='Tipo de acta para generación de contenido especializado con IA',
    )
    creador = models.ForeignKey(User, on_delete=models.CASCADE, related_name='actas_creadas')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    
    # Contenido
    orden_dia = models.TextField(help_text='Orden del día de la reunión')
    desarrollo = models.TextField(help_text='Desarrollo de la reunión')
    resumen_ia = models.TextField(blank=True, help_text='Resumen generado por IA')
    observaciones = models.TextField(blank=True)
    
    # Control de firmas
    fecha_limite_firmas = models.DateTimeField(null=True, blank=True)
    silencio_administrativo = models.BooleanField(default=False)
    aplicar_silencio_dias = models.IntegerField(default=7)
    
    # ========================================
    # CAMPOS FORMATO OFICIAL GOR-F-084 V02
    # ========================================
    ciudad = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Ciudad',
        help_text='Ej: Sogamoso, Boyacá',
    )
    hora_inicio = models.TimeField(
        null=True,
        blank=True,
        verbose_name='Hora de inicio',
        help_text='Hora de inicio de la reunión (HH:MM)',
    )
    hora_fin = models.TimeField(
        null=True,
        blank=True,
        verbose_name='Hora de fin',
        help_text='Hora de finalización de la reunión (HH:MM)',
    )
    lugar_enlace = models.TextField(
        blank=True,
        default='',
        verbose_name='Lugar y/o enlace',
        help_text='Dirección física o enlace virtual (Teams, Zoom, Google Meet)',
    )
    direccion = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name='Dirección',
        help_text='Dirección física. Ej: Cra 9 #14-109',
    )
    regional = models.CharField(
        max_length=100,
        blank=True,
        default='Boyacá',
        verbose_name='Regional',
    )
    centro = models.CharField(
        max_length=150,
        blank=True,
        default='Centro Minero',
        verbose_name='Centro',
    )
    objetivos = models.TextField(
        blank=True,
        default='',
        verbose_name='Objetivo(s) de la reunión',
        help_text='Verbos en infinitivo. Ej: 1. Revisar... 2. Evaluar...',
    )

    # Archivos adjuntos (campo legacy)
    archivo_adjunto = models.FileField(
        upload_to='actas/adjuntos/',
        blank=True,
        null=True,
        validators=[validar_extension_archivo, validar_contenido_archivo, validar_tamaño_archivo]
    )
    
    # ========================================
    # CAMPOS NUEVOS PARA OLLAMA/IA
    # ========================================
    # Indicador de si fue generada con IA
    generada_con_ia = models.BooleanField(
        default=False,
        help_text='Indica si el acta fue generada usando Ollama',
        db_index=True  # Índice para búsquedas rápidas
    )
    
    # Prompt original enviado a Ollama
    prompt_original = models.TextField(
        blank=True,
        null=True,
        help_text='Resumen breve que el usuario proporcionó para generar el acta'
    )
    
    # Modelo de IA usado
    modelo_ia_usado = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='Ejemplo: llama3:8b, llama3:70b, etc.'
    )
    
    # Tiempo que tomó generar (en segundos)
    tiempo_generacion = models.FloatField(
        blank=True,
        null=True,
        help_text='Tiempo en segundos que tomó Ollama en generar el acta'
    )
    
    # Si fue editada después de generar
    editada_despues_ia = models.BooleanField(
        default=False,
        help_text='Indica si el acta fue modificada manualmente después de ser generada por IA'
    )
    
    # Fecha de la última edición manual (si aplica)
    fecha_ultima_edicion_manual = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Última vez que se editó manualmente después de generar con IA'
    )
    
    # Versión del acta (para tracking de cambios)
    version = models.IntegerField(
        default=1,
        help_text='Número de versión del acta (incrementa con cada edición)'
    )

    # ========================================
    # CAMPOS PARA EL PROCESO DE REVISIÓN COLABORATIVA
    # ========================================
    # Fecha límite para que los participantes aprueben/rechacen el acta
    fecha_limite_revision = models.DateTimeField(
        null=True, blank=True,
        help_text='Fecha límite para que los participantes respondan en el ciclo actual'
    )

    # Número de ciclo de revisión (incrementa cada vez que el acta vuelve a borrador)
    ciclo_revision = models.IntegerField(
        default=1,
        help_text='Número de ciclo de revisión (1 = primera vez en revisión)'
    )

    # Historial de cambios en formato JSON
    # Formato: [{"ciclo": 1, "fecha": "...", "accion": "...", "usuario": "...", "detalle": "..."}]
    historial_cambios = models.JSONField(
        default=list, blank=True,
        help_text='Historial de cambios y eventos del acta en formato JSON'
    )

    # Observaciones de los participantes por ciclo en formato JSON
    # Formato: {"ciclo_1": [{"usuario": "...", "observacion": "...", "fecha": "..."}]}
    observaciones_participantes = models.JSONField(
        default=dict, blank=True,
        help_text='Observaciones de los participantes organizadas por ciclo de revisión'
    )

    # Quién cerró el acta (por vencimiento u otra causa)
    cerrada_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='actas_cerradas',
        help_text='Usuario (o sistema) que cerró el acta por vencimiento'
    )

    # Fecha en que se cerró el acta
    fecha_cierre = models.DateTimeField(
        null=True, blank=True,
        help_text='Fecha en que el acta fue cerrada por vencimiento'
    )

    # Motivo del cierre
    motivo_cierre = models.TextField(
        blank=True,
        help_text='Motivo del cierre del acta (vencimiento de plazos, etc.)'
    )

    class Meta:
        verbose_name = 'Acta'
        verbose_name_plural = 'Actas'
        ordering = ['-fecha_creacion']
        permissions = [
            ("can_finalize_acta", "Puede finalizar actas"),
            ("can_archive_acta", "Puede archivar actas"),
            ("can_generate_with_ia", "Puede generar actas con IA"),
            ("aprobar_acta", "Puede aprobar actas"),
            ("rechazar_acta", "Puede rechazar actas"),
            ("enviar_a_revision", "Puede enviar actas a revisión"),
            ("generar_pdf_acta", "Puede generar PDF de actas"),
            ("firmar_acta", "Puede firmar actas"),
        ]
        
        # ÍNDICES PARA OPTIMIZACIÓN
        indexes = [
            models.Index(fields=['fecha_creacion']),
            models.Index(fields=['estado']),
            models.Index(fields=['fecha_reunion']),
            models.Index(fields=['generada_con_ia']),
            models.Index(fields=['creador', 'fecha_creacion']),
        ]
    
    def save(self, *args, **kwargs):
        # Establecer fecha límite de firmas (7 días en producción)
        if not self.fecha_limite_firmas and self.estado == 'en_revision':
            self.fecha_limite_firmas = timezone.now() + timedelta(days=7)

        # Detectar si fue editada después de generar con IA
        if self.pk and self.generada_con_ia:
            # Si el acta ya existe y fue generada con IA
            try:
                acta_anterior = Acta.objects.get(pk=self.pk)
                if (acta_anterior.desarrollo != self.desarrollo or
                    acta_anterior.orden_dia != self.orden_dia):
                    # Si cambió el contenido, marcar como editada
                    self.editada_despues_ia = True
                    self.fecha_ultima_edicion_manual = timezone.now()
                    self.version += 1
            except Acta.DoesNotExist:
                pass

        super().save(*args, **kwargs)
    
    def get_participantes(self):
        return self.participantes.all()
    
    def get_firmas_completadas(self):
        return self.firmas.filter(firmado=True).count()
    
    def get_total_firmas(self):
        return self.participantes.count()
    
    def get_porcentaje_firmas(self):
        total = self.get_total_firmas()
        if total == 0:
            return 0
        return (self.get_firmas_completadas() / total) * 100
    
    def puede_aplicar_silencio_administrativo(self):
        if not self.fecha_limite_firmas:
            return False
        # Solo aplicar si: pasó la fecha límite, está en revisión Y hay firmas pendientes
        tiene_firmas_pendientes = self.firmas.filter(firmado=False).exists()
        return (
            timezone.now() > self.fecha_limite_firmas
            and self.estado == 'en_revision'
            and tiene_firmas_pendientes
        )
    
    def aplicar_silencio_admin(self):
        if self.puede_aplicar_silencio_administrativo():
            self.estado = 'finalizada'
            self.silencio_administrativo = True
            self.save()

            # Marcar firmas pendientes como firmadas automáticamente
            firmas_pendientes = self.firmas.filter(firmado=False)
            for firma in firmas_pendientes:
                firma.firmado = True
                firma.fecha_firma = timezone.now()
                firma.firmado_por_silencio = True
                # Copiar la firma digital del usuario si la tiene cargada
                if firma.usuario.firma_digital:
                    firma.firma_imagen = firma.usuario.firma_digital
                firma.save()
    
    # NUEVO MÉTODO: Información sobre IA
    def info_generacion_ia(self):
        """
        Retorna un diccionario con información sobre la generación con IA
        """
        if not self.generada_con_ia:
            return None
        
        return {
            'generada_con_ia': True,
            'modelo_usado': self.modelo_ia_usado or 'Desconocido',
            'tiempo_generacion': f"{self.tiempo_generacion:.1f}s" if self.tiempo_generacion else 'N/A',
            'editada_manualmente': self.editada_despues_ia,
            'version': self.version,
            'fecha_ultima_edicion': self.fecha_ultima_edicion_manual
        }
    
    def get_tipo_reunion_label(self):
        """Devuelve el tipo de reunión para mostrar al usuario, usando tipo_reunion_otro si aplica."""
        if self.tipo_reunion == 'otra' and self.tipo_reunion_otro:
            return self.tipo_reunion_otro
        return self.get_tipo_reunion_display()

    def __str__(self):
        return f"{self.numero_acta} - {self.titulo}"


class Participante(models.Model):
    ESTADO_APROBACION_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Rechazado'),
    ]

    acta = models.ForeignKey(Acta, on_delete=models.CASCADE, related_name='participantes')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    rol_en_reunion = models.CharField(max_length=100, blank=True)
    dependencia_empresa = models.CharField(
        max_length=200,
        blank=True,
        default='SENA - CENTRO MINERO',
        verbose_name='Dependencia / Empresa',
        help_text='Ej: SENA - CENTRO MINERO, Alcaldía de Sogamoso',
    )
    obligatorio_firma = models.BooleanField(default=True)
    fecha_agregado = models.DateTimeField(auto_now_add=True)

    # ── Campos para el proceso de revisión colaborativa ──────────────────────
    # Estado de aprobación del participante en el ciclo actual
    estado_aprobacion = models.CharField(
        max_length=15,
        choices=ESTADO_APROBACION_CHOICES,
        default='pendiente',
        help_text='Respuesta del participante al acta en el ciclo de revisión actual'
    )

    # Fecha en que el participante respondió (aprobó o rechazó)
    fecha_respuesta = models.DateTimeField(
        null=True, blank=True,
        help_text='Fecha en que el participante aprobó o rechazó el acta'
    )

    # Observaciones del participante al rechazar o aprobar con comentarios
    observaciones = models.TextField(
        blank=True,
        help_text='Observaciones del participante (motivo del rechazo o comentarios de aprobación)'
    )

    # Ciclo de revisión en que se registró esta respuesta
    ciclo_revision = models.IntegerField(
        default=1,
        help_text='Ciclo de revisión al que corresponde el estado_aprobacion actual'
    )

    class Meta:
        verbose_name = 'Participante'
        verbose_name_plural = 'Participantes'
        unique_together = ['acta', 'usuario']
        indexes = [
            models.Index(fields=['acta', 'usuario']),
            models.Index(fields=['acta', 'estado_aprobacion']),
        ]

    def __str__(self):
        return f"{self.usuario.get_full_name()} - {self.acta.numero_acta}"


class Firma(models.Model):
    acta = models.ForeignKey(Acta, on_delete=models.CASCADE, related_name='firmas')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    firmado = models.BooleanField(default=False)
    fecha_firma = models.DateTimeField(null=True, blank=True)
    firma_imagen = models.ImageField(upload_to='firmas/', null=True, blank=True)
    firma_datos = models.TextField(null=True, blank=True)  # base64 de la firma, persiste aunque se pierda el archivo
    firmado_por_silencio = models.BooleanField(default=False)
    comentarios = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Firma'
        verbose_name_plural = 'Firmas'
        unique_together = ['acta', 'usuario']
        # NUEVO: Índices para optimización
        indexes = [
            models.Index(fields=['acta', 'firmado']),
            models.Index(fields=['usuario', 'firmado']),
        ]
    
    def firmar(self, request=None):
        self.firmado = True
        self.fecha_firma = timezone.now()
        if self.usuario.firma_digital:
            self.firma_imagen = self.usuario.firma_digital
        if request:
            self.ip_address = self.get_client_ip(request)
        self.save()
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def __str__(self):
        return f"Firma de {self.usuario.get_full_name()} - {self.acta.numero_acta}"


class Compromiso(models.Model):
    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('en_progreso', 'En Progreso'),
        ('completado', 'Completado'),
        ('vencido', 'Vencido'),
    ]
    
    acta = models.ForeignKey(Acta, on_delete=models.CASCADE, related_name='compromisos')
    descripcion = models.TextField()
    responsable = models.ForeignKey(User, on_delete=models.CASCADE, related_name='compromisos_asignados')
    fecha_limite = models.DateField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')
    porcentaje_avance = models.IntegerField(default=0)
    observaciones = models.TextField(blank=True)
    fecha_completado = models.DateTimeField(null=True, blank=True)
    reporte_cumplimiento = models.TextField(
        blank=True, 
        verbose_name="Reporte/Justificación del Responsable", 
        help_text="Descripción del avance o justificación del estado/cumplimiento."
    )
    
    class Meta:
        verbose_name = 'Compromiso'
        verbose_name_plural = 'Compromisos'
        ordering = ['fecha_limite']
        # NUEVO: Índices para optimización
        indexes = [
            models.Index(fields=['fecha_limite', 'estado']),
            models.Index(fields=['responsable', 'estado']),
            models.Index(fields=['acta']),
        ]
    
    def save(self, *args, **kwargs):
        # Asegurar que fecha_limite sea un objeto date
        if isinstance(self.fecha_limite, str):
            try:
                self.fecha_limite = datetime.strptime(self.fecha_limite, '%Y-%m-%d').date()
            except (ValueError, AttributeError):
                pass
        
        # Marcar como completado si alcanza 100%
        if self.porcentaje_avance == 100 and self.estado != 'completado':
            self.estado = 'completado'
            self.fecha_completado = timezone.now()
        
        # Marcar como vencido si pasó la fecha límite
        elif self.fecha_limite and isinstance(self.fecha_limite, date):
            if self.fecha_limite < timezone.now().date() and self.estado not in ['completado']:
                self.estado = 'vencido'
        
        super().save(*args, **kwargs)
    
    def dias_restantes(self):
        if self.estado == 'completado':
            return 0
        delta = self.fecha_limite - timezone.now().date()
        return delta.days
    
    def esta_vencido(self):
        return self.dias_restantes() < 0 and self.estado != 'completado'
    
    def __str__(self):
        return f"Compromiso {self.id} - {self.acta.numero_acta}"


class ComentarioActa(models.Model):
    acta = models.ForeignKey('Acta', on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey('accounts.User', on_delete=models.CASCADE)
    texto = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        # NUEVO: Índice para optimización
        indexes = [
            models.Index(fields=['acta', 'fecha']),
        ]

    def __str__(self):
        return f"Comentario de {self.autor.get_full_name()} en {self.acta.numero_acta}"


class ArchivoAdjunto(models.Model):
    """
    Archivos adjuntos de las actas (permite múltiples archivos por acta)

    Este modelo complementa el campo 'archivo_adjunto' existente en Acta,
    permitiendo adjuntar múltiples archivos a una misma acta con metadata completa.
    """
    acta = models.ForeignKey(
        'Acta',
        on_delete=models.CASCADE,
        related_name='archivos_adjuntos',
        help_text='Acta a la que pertenece el archivo'
    )

    archivo = models.FileField(
        upload_to='actas/adjuntos/%Y/%m/',
        help_text='Archivo adjunto',
        validators=[validar_extension_archivo, validar_contenido_archivo, validar_tamaño_archivo]
    )

    nombre_original = models.CharField(
        max_length=255,
        help_text='Nombre original del archivo'
    )

    tipo_archivo = models.CharField(
        max_length=100,
        help_text='Extensión: pdf, docx, xlsx, jpg, png, zip, etc.'
    )

    tamaño_bytes = models.BigIntegerField(
        help_text='Tamaño del archivo en bytes'
    )

    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='archivos_subidos',
        help_text='Usuario que subió el archivo'
    )

    fecha_subida = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha y hora de subida'
    )

    descripcion = models.TextField(
        blank=True,
        help_text='Descripción opcional del archivo'
    )

    class Meta:
        ordering = ['-fecha_subida']
        verbose_name = 'Archivo Adjunto'
        verbose_name_plural = 'Archivos Adjuntos'
        indexes = [
            models.Index(fields=['acta', 'fecha_subida']),
        ]

    def __str__(self):
        return f"{self.nombre_original} - Acta {self.acta.numero_acta}"

    def delete(self, *args, **kwargs):
        """Eliminar archivo físico al eliminar registro"""
        if self.archivo and os.path.isfile(self.archivo.path):
            try:
                os.remove(self.archivo.path)
            except Exception as e:
                # Log el error pero continuar con la eliminación del registro
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f'Error al eliminar archivo físico: {str(e)}')
        super().delete(*args, **kwargs)

    @property
    def tamaño_legible(self):
        """Retorna el tamaño en formato legible (KB, MB)"""
        if self.tamaño_bytes < 1024:
            return f"{self.tamaño_bytes} B"
        elif self.tamaño_bytes < 1024 * 1024:
            return f"{self.tamaño_bytes / 1024:.2f} KB"
        else:
            return f"{self.tamaño_bytes / (1024 * 1024):.2f} MB"


# =============================================================================
# ANEXO DE ACTA (PDF únicamente, fusionado al generar el PDF del acta)
# =============================================================================

MAX_ANEXO_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_ANEXOS_POR_ACTA = 10


def validar_pdf_anexo(archivo):
    """
    Valida que el archivo sea un PDF real:
    1. Extensión .pdf
    2. Tamaño ≤ 10 MB
    3. Magic bytes %PDF al inicio
    """
    if not archivo:
        return

    nombre = archivo.name.lower()
    if not nombre.endswith('.pdf'):
        raise ValidationError('Solo se permiten archivos PDF como anexos.')

    if archivo.size > MAX_ANEXO_SIZE:
        mb = archivo.size / (1024 * 1024)
        raise ValidationError(f'El anexo es demasiado grande ({mb:.2f} MB). Máximo 10 MB.')

    # Verificar magic bytes reales
    try:
        pos = archivo.tell()
        archivo.seek(0)
        header = archivo.read(5)
        archivo.seek(pos)
    except Exception:
        return

    if not header.startswith(b'%PDF'):
        raise ValidationError('El archivo no es un PDF válido (contenido incorrecto).')


class AnexoActa(models.Model):
    """
    Anexos en PDF que se fusionan al generar el PDF del acta.
    Solo se permiten PDFs; máximo 10 anexos por acta.
    Solo se pueden agregar/eliminar mientras el acta esté en estado 'borrador'.
    """
    acta = models.ForeignKey(
        'Acta',
        on_delete=models.CASCADE,
        related_name='anexos',
        help_text='Acta a la que pertenece el anexo',
    )
    archivo = models.FileField(
        upload_to='actas/anexos/%Y/%m/',
        validators=[validar_pdf_anexo],
        help_text='Archivo PDF del anexo (máx. 10 MB)',
    )
    nombre_archivo = models.CharField(
        max_length=255,
        help_text='Nombre original del archivo PDF',
    )
    orden = models.IntegerField(
        default=0,
        help_text='Posición del anexo dentro del PDF consolidado (0 = primero)',
    )
    fecha_carga = models.DateTimeField(auto_now_add=True)
    cargado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='anexos_cargados',
        help_text='Usuario que subió el anexo',
    )

    class Meta:
        verbose_name = 'Anexo de Acta'
        verbose_name_plural = 'Anexos de Acta'
        ordering = ['orden', 'fecha_carga']
        indexes = [
            models.Index(fields=['acta', 'orden']),
        ]

    def __str__(self):
        return f"Anexo '{self.nombre_archivo}' — Acta {self.acta.numero_acta}"

    def delete(self, *args, **kwargs):
        """Eliminar el archivo físico al borrar el registro."""
        if self.archivo:
            try:
                path = self.archivo.path
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass
        super().delete(*args, **kwargs)


# =============================================================================
# PLANTILLAS DE ACTA (sistema de formatos Word por tipo de reunión)
# =============================================================================

class PlantillaActa(models.Model):
    """
    Plantilla Word (.docx) para un tipo de reunión específico.
    El sistema rellena los {{marcadores}} con los datos del acta y genera el PDF.
    Si no hay plantilla para un tipo, se usa el generador ReportLab como fallback.

    Marcadores soportados en el documento Word:
        {{numero_acta}}, {{titulo}}, {{tipo_reunion}}, {{fecha_reunion}},
        {{lugar}}, {{objetivo}}, {{orden_dia}}, {{desarrollo}}, {{conclusiones}},
        {{compromisos_tabla}}, {{participantes_tabla}},
        {{creador_nombre}}, {{creador_cargo}}, {{fecha_generacion}}
    """

    TIPOS_REUNION = [
        ('consejo_academico', 'Consejo Académico'),
        ('comite_evaluacion', 'Comité de Evaluación'),
        ('coordinacion', 'Coordinación'),
        ('administrativa', 'Administrativa'),
        ('tecnica', 'Técnica'),
        ('otra', 'Otra'),
    ]

    tipo_reunion = models.CharField(
        max_length=30,
        choices=TIPOS_REUNION,
        unique=True,
        verbose_name='Tipo de reunión',
        help_text='Solo puede haber una plantilla activa por tipo de reunión.',
    )
    nombre = models.CharField(
        max_length=200,
        verbose_name='Nombre de la plantilla',
        help_text='Nombre descriptivo para identificar la plantilla (ej: "Formato Consejo v2").',
    )
    archivo = models.FileField(
        upload_to='plantillas_actas/%Y/%m/',
        validators=[validar_plantilla_docx],
        verbose_name='Archivo Word (.docx)',
        help_text='Suba un archivo .docx con los {{marcadores}} en las posiciones deseadas.',
    )
    activa = models.BooleanField(
        default=True,
        verbose_name='Activa',
        help_text='Solo las plantillas activas se usan para generar PDFs.',
    )
    descripcion = models.TextField(
        blank=True,
        verbose_name='Descripción',
        help_text='Notas sobre esta plantilla (opcional).',
    )
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='plantillas_creadas',
        verbose_name='Creada por',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')
    fecha_modificacion = models.DateTimeField(auto_now=True, verbose_name='Última modificación')

    class Meta:
        verbose_name = 'Plantilla de Acta'
        verbose_name_plural = 'Plantillas de Acta'
        ordering = ['tipo_reunion']

    def __str__(self):
        estado = 'activa' if self.activa else 'inactiva'
        return f"{self.get_tipo_reunion_display()} — {self.nombre} ({estado})"

    def delete(self, *args, **kwargs):
        """Eliminar el archivo físico al borrar el registro."""
        if self.archivo:
            try:
                path = self.archivo.path
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass
        super().delete(*args, **kwargs)

# =============================================================================
# PARTICIPANTES NO REGISTRADOS
# =============================================================================

class ParticipanteNoRegistrado(models.Model):
    """
    Persona que asistió a la reunión pero NO tiene cuenta en el sistema.
    No puede firmar digitalmente. Recibe el PDF del acta por email al finalizarla.
    """
    acta = models.ForeignKey(
        Acta,
        on_delete=models.CASCADE,
        related_name='participantes_no_registrados',
    )
    nombre_completo = models.CharField(max_length=200, verbose_name='Nombre completo')
    email = models.EmailField(verbose_name='Correo electrónico')
    cargo_rol = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Cargo / Rol',
        help_text='Ej: Aprendiz, Invitado externo, Contratista',
    )
    dependencia_empresa = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name='Dependencia / Empresa',
        help_text='Ej: Alcaldía de Sogamoso, Empresa XYZ S.A.S.',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    # Estado de envío del PDF
    pdf_enviado = models.BooleanField(default=False)
    fecha_envio = models.DateTimeField(null=True, blank=True)
    email_rebotado = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Participante No Registrado'
        verbose_name_plural = 'Participantes No Registrados'
        unique_together = [('acta', 'email')]
        ordering = ['nombre_completo']

    def __str__(self):
        return f"{self.nombre_completo} ({self.email})"
