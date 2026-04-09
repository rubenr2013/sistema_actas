"""
Validador de variables en plantillas Word (.docx).
Detecta variables usadas en el documento, las compara con la lista oficial
y retorna advertencias si hay variables desconocidas o mal escritas.
"""
import re
import logging

logger = logging.getLogger(__name__)

# Variables oficiales reconocidas por el sistema
VARIABLES_OFICIALES = {
    'numero_acta',
    'titulo',
    'tipo_reunion',
    'fecha_reunion',
    'lugar',
    'objetivo',
    'orden_dia',
    'desarrollo',
    'conclusiones',
    'creador_nombre',
    'creador_cargo',
    'fecha_generacion',
    'participantes_tabla',
    'compromisos_tabla',
}

# Sugerencias automáticas para errores comunes
SUGERENCIAS = {
    'numero': 'numero_acta',
    'no_acta': 'numero_acta',
    'n_acta': 'numero_acta',
    'acta': 'numero_acta',
    'title': 'titulo',
    'nombre': 'titulo',
    'fecha': 'fecha_reunion',
    'fecha_reunion': 'fecha_reunion',
    'lugar_reunion': 'lugar',
    'site': 'lugar',
    'objetivo_reunion': 'objetivo',
    'puntos': 'orden_dia',
    'agenda': 'orden_dia',
    'desarrollo_reunion': 'desarrollo',
    'conclusion': 'conclusiones',
    'observaciones': 'conclusiones',
    'autor': 'creador_nombre',
    'creador': 'creador_nombre',
    'cargo': 'creador_cargo',
    'fecha_creacion': 'fecha_generacion',
    'participantes': 'participantes_tabla',
    'tabla_participantes': 'participantes_tabla',
    'compromisos': 'compromisos_tabla',
    'tabla_compromisos': 'compromisos_tabla',
    'actividades': 'compromisos_tabla',
}

# Patrón para encontrar cualquier cosa entre {{ }}
_PATRON = re.compile(r'\{\{([^}]+)\}\}')


def _extraer_texto_docx(archivo_o_bytes):
    """
    Extrae todo el texto del documento Word.
    Acepta un objeto de archivo Django o bytes.
    """
    try:
        from docx import Document
        import io
        if hasattr(archivo_o_bytes, 'read'):
            archivo_o_bytes.seek(0)
            data = archivo_o_bytes.read()
            archivo_o_bytes.seek(0)
        else:
            data = archivo_o_bytes
        doc = Document(io.BytesIO(data))
        partes = []
        for para in doc.paragraphs:
            partes.append(para.text)
        for tabla in doc.tables:
            for fila in tabla.rows:
                for celda in fila.cells:
                    partes.append(celda.text)
        return '\n'.join(partes)
    except Exception as e:
        logger.warning('plantilla_validator: no se pudo leer el docx: %s', e)
        return ''


def extraer_variables(archivo_o_bytes):
    """
    Retorna un set con los nombres de las variables encontradas en el documento.
    Ej: {'titulo', 'fecha_reunion', 'Titulo'} (sin normalizar)
    """
    texto = _extraer_texto_docx(archivo_o_bytes)
    variables = set()
    for match in _PATRON.finditer(texto):
        variables.add(match.group(1).strip())
    return variables


def _sugerir(variable_raw):
    """Sugiere la variable oficial más cercana dado un nombre en bruto."""
    norm = variable_raw.lower().replace(' ', '_')
    # Coincidencia exacta normalizada
    if norm in VARIABLES_OFICIALES:
        return norm
    # Tabla de sugerencias
    if norm in SUGERENCIAS:
        return SUGERENCIAS[norm]
    # Búsqueda parcial: si el nombre contiene alguna variable oficial
    for oficial in VARIABLES_OFICIALES:
        if oficial in norm or norm in oficial:
            return oficial
    return None


def validar_variables(archivo_o_bytes):
    """
    Valida las variables del documento.

    Retorna un dict:
    {
        'valido': True/False,
        'variables_encontradas': ['titulo', 'fecha_reunion', ...],
        'variables_invalidas': [
            {'variable': 'Titulo', 'sugerencia': 'titulo'},
            ...
        ],
        'variables_validas': ['titulo', 'fecha_reunion', ...],
        'advertencia': str or None,
    }
    """
    variables_raw = extraer_variables(archivo_o_bytes)

    validas = []
    invalidas = []

    for var in sorted(variables_raw):
        norm = var.lower().replace(' ', '_')
        if norm in VARIABLES_OFICIALES:
            validas.append(norm)
        else:
            sugerencia = _sugerir(var)
            invalidas.append({'variable': var, 'sugerencia': sugerencia})

    advertencia = None
    if invalidas:
        nombres = ', '.join(f'{{{{ {i["variable"]} }}}}' for i in invalidas)
        advertencia = (
            f"Se encontraron {len(invalidas)} variable(s) no reconocida(s): {nombres}. "
            "No serán reemplazadas. Revisa la guía de variables."
        )

    return {
        'valido': len(invalidas) == 0,
        'variables_encontradas': sorted(variables_raw),
        'variables_validas': validas,
        'variables_invalidas': invalidas,
        'advertencia': advertencia,
    }
