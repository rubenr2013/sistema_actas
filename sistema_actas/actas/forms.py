from django import forms
from .models import Compromiso

# actas/forms.py

from django import forms
from .models import Compromiso

class ReporteCompromisoForm(forms.ModelForm):
    class Meta:
        model = Compromiso
        fields = ['estado', 'porcentaje_avance', 'reporte_cumplimiento']
        widgets = {
            # Aplicar la clase para que se vea como el input de Bootstrap
            'estado': forms.Select(attrs={'class': 'form-select'}), 
            
            # Aplicar 'form-control' para inputs de texto y números
            'porcentaje_avance': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            
            # Aplicar 'form-control' para textarea, y filas para el tamaño
            'reporte_cumplimiento': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }