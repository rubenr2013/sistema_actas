from django.db import models
from django.core.exceptions import ValidationError


class Programa(models.Model):
    """
    Representa una carrera técnica o tecnológica del SENA.
    Ejemplo: "Análisis y Desarrollo de Software", código "228106"
    """
    nombre = models.CharField(
        max_length=200,
        unique=True,
        verbose_name="Nombre del programa",
        help_text="Ej: Análisis y Desarrollo de Software"
    )
    codigo = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Código del programa",
        help_text="Ej: 228106"
    )
    descripcion = models.TextField(
        blank=True,
        verbose_name="Descripción",
        help_text="Descripción breve del programa (opcional)"
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="¿Activo?",
        help_text="Desactívalo para que no aparezca en el registro de nuevos aprendices"
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Programa de Formación'
        verbose_name_plural = 'Programas de Formación'

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"


class Ficha(models.Model):
    """
    Representa un grupo específico de un programa.
    El número de ficha es único en todo el sistema (como un número de documento).
    Ejemplo: ficha 2898734 del programa ADSO
    """
    numero = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Número de ficha",
        help_text="Número único de la ficha. Ej: 2898734"
    )
    programa = models.ForeignKey(
        Programa,
        on_delete=models.PROTECT,  # Protege: no deja borrar un programa si tiene fichas
        related_name='fichas',
        verbose_name="Programa de formación"
    )
    fecha_inicio = models.DateField(verbose_name="Fecha de inicio")
    fecha_fin = models.DateField(verbose_name="Fecha de fin proyectada")
    activa = models.BooleanField(
        default=True,
        verbose_name="¿Activa?",
        help_text="Desactívala cuando el grupo se gradúe"
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")

    class Meta:
        ordering = ['-fecha_inicio']
        verbose_name = 'Ficha'
        verbose_name_plural = 'Fichas'

    def __str__(self):
        return f"Ficha {self.numero} - {self.programa.nombre}"

    def clean(self):
        """Validaciones del modelo antes de guardar."""
        # El número de ficha solo puede tener dígitos
        if self.numero and not self.numero.isdigit():
            raise ValidationError({
                'numero': 'El número de ficha solo puede contener dígitos (sin letras ni espacios).'
            })

        # La fecha de inicio debe ser antes de la fecha de fin
        if self.fecha_inicio and self.fecha_fin:
            if self.fecha_inicio >= self.fecha_fin:
                raise ValidationError({
                    'fecha_fin': 'La fecha de fin debe ser posterior a la fecha de inicio.'
                })
