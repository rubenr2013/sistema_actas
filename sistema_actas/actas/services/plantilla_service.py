"""
Servicio de generación de documentos a partir de plantillas Word (.docx).

Flujo:
  1. Se busca una PlantillaActa activa para el tipo_reunion del acta.
  2. Se abre el .docx y se reemplazan los {{marcadores}} en párrafos y tablas.
  3. Se convierten a PDF con LibreOffice headless (si está disponible) o
     se devuelve el .docx como BytesIO para que la vista lo entregue directamente.
  4. Si no hay plantilla configurada se devuelve None y la vista usa el
     generador ReportLab como fallback.

Marcadores soportados (case-insensitive, con o sin espacios):
  {{numero_acta}}         {{titulo}}              {{tipo_reunion}}
  {{fecha_reunion}}       {{lugar}}               {{objetivo}}
  {{orden_dia}}           {{desarrollo}}          {{conclusiones}}
  {{creador_nombre}}      {{creador_cargo}}       {{fecha_generacion}}
  {{participantes_tabla}} {{compromisos_tabla}}
"""

import io
import logging
import os
import subprocess
import tempfile
import base64

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _texto_seguro(valor, fallback='—'):
    """Devuelve el valor como string o el fallback si está vacío."""
    if valor is None:
        return fallback
    s = str(valor).strip()
    return s if s else fallback


def _construir_marcadores(acta):
    """
    Construye el diccionario {marcador: valor} con los datos del acta.
    Las claves NO incluyen las llaves dobles; se reemplazan en el texto buscando
    {{clave}} con y sin espacios internos (ej: {{ numero_acta }}).
    """
    from django.utils.formats import date_format

    creador = acta.creador
    creador_nombre = creador.get_full_name() if creador else '—'
    creador_cargo = getattr(creador, 'cargo', None) or getattr(creador, 'rol', None) or '—'

    fecha_reunion = acta.fecha_reunion
    if fecha_reunion:
        try:
            fecha_str = date_format(fecha_reunion, 'd/m/Y H:i')
        except Exception:
            fecha_str = str(fecha_reunion)
    else:
        fecha_str = '—'

    return {
        'numero_acta': _texto_seguro(acta.numero_acta),
        'titulo': _texto_seguro(acta.titulo),
        'tipo_reunion': _texto_seguro(acta.get_tipo_reunion_display()),
        'fecha_reunion': fecha_str,
        'lugar': _texto_seguro(getattr(acta, 'lugar', None) or getattr(acta, 'lugar_reunion', None)),
        'objetivo': _texto_seguro(getattr(acta, 'objetivo', None)),
        'orden_dia': _texto_seguro(acta.orden_dia),
        'desarrollo': _texto_seguro(acta.desarrollo),
        'conclusiones': _texto_seguro(getattr(acta, 'conclusiones', None)),
        'creador_nombre': creador_nombre,
        'creador_cargo': str(creador_cargo),
        'fecha_generacion': timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M'),
    }


def _reemplazar_en_parrafo(parrafo, marcadores):
    """
    Reemplaza {{marcadores}} dentro de un párrafo de python-docx preservando el
    formato original del run. Trabaja sobre el texto completo del párrafo para
    evitar que Word fragmente los marcadores en varios runs.
    """
    texto_completo = ''.join(run.text for run in parrafo.runs)

    nuevo_texto = texto_completo
    for clave, valor in marcadores.items():
        # Soportar variantes con espacios: {{clave}}, {{ clave }}, {{  clave  }}
        import re
        patron = r'\{\{\s*' + re.escape(clave) + r'\s*\}\}'
        nuevo_texto = re.sub(patron, valor, nuevo_texto, flags=re.IGNORECASE)

    if nuevo_texto == texto_completo:
        return  # Sin cambios

    # Escribir el texto reemplazado en el primer run y limpiar el resto
    if parrafo.runs:
        parrafo.runs[0].text = nuevo_texto
        for run in parrafo.runs[1:]:
            run.text = ''


def _reemplazar_marcadores_simples(doc, marcadores):
    """Recorre todos los párrafos y celdas de tablas del documento."""
    # Párrafos de cuerpo
    for parrafo in doc.paragraphs:
        _reemplazar_en_parrafo(parrafo, marcadores)

    # Párrafos dentro de tablas
    for tabla in doc.tables:
        for fila in tabla.rows:
            for celda in fila.cells:
                for parrafo in celda.paragraphs:
                    _reemplazar_en_parrafo(parrafo, marcadores)


# ---------------------------------------------------------------------------
# Construcción de tablas dinámicas
# ---------------------------------------------------------------------------

def _insertar_tabla_participantes(doc, acta):
    """
    Busca el marcador {{participantes_tabla}} en el documento y lo reemplaza
    por una tabla Word con los datos y la firma (imagen o texto) de cada
    participante.
    """
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    import re

    patron = re.compile(r'\{\{\s*participantes_tabla\s*\}\}', re.IGNORECASE)

    # Buscar en párrafos del cuerpo
    for i, parrafo in enumerate(doc.paragraphs):
        if patron.search(parrafo.text):
            _reemplazar_parrafo_por_tabla_participantes(doc, parrafo, acta)
            return

    # Buscar en celdas de tablas
    for tabla in doc.tables:
        for fila in tabla.rows:
            for celda in fila.cells:
                for parrafo in celda.paragraphs:
                    if patron.search(parrafo.text):
                        # En celda: limpiar texto y agregar sub-tabla
                        parrafo.clear()
                        _agregar_tabla_participantes_en_celda(celda, acta)
                        return


def _agregar_tabla_participantes_en_celda(celda, acta):
    """Agrega la tabla de participantes dentro de una celda."""
    from docx.shared import Inches, Pt
    from docx.oxml.ns import qn
    import lxml.etree as etree

    participantes = acta.participantes.select_related('usuario').all()
    if not participantes.exists():
        celda.paragraphs[0].text = 'Sin participantes registrados.'
        return

    tabla = celda.add_table(rows=1, cols=4)
    tabla.style = 'Table Grid'
    encabezados = ['Nombre', 'Cargo / Rol', 'Aprueba', 'Firma']
    for j, enc in enumerate(encabezados):
        tabla.rows[0].cells[j].text = enc

    for participante in participantes:
        fila = tabla.add_row()
        usuario = participante.usuario
        fila.cells[0].text = usuario.get_full_name()
        fila.cells[1].text = str(participante.rol_en_reunion or getattr(usuario, 'cargo', '') or '—')

        firma_obj = acta.firmas.filter(usuario=usuario).first()
        if firma_obj and firma_obj.firmado:
            fila.cells[2].text = 'Sí'
            _insertar_firma_en_celda(fila.cells[3], firma_obj)
        else:
            fila.cells[2].text = 'No'
            fila.cells[3].text = 'Pendiente'


def _reemplazar_parrafo_por_tabla_participantes(doc, parrafo, acta):
    """
    Inserta la tabla de participantes justo después del párrafo que contiene
    el marcador y luego elimina ese párrafo.
    """
    from docx.oxml.ns import qn
    from docx.shared import Pt

    participantes = acta.participantes.select_related('usuario').all()
    p_element = parrafo._element

    tabla = doc.add_table(rows=1, cols=4)
    tabla.style = 'Table Grid'
    encabezados = ['Nombre', 'Cargo / Rol', 'Aprueba', 'Firma']
    for j, enc in enumerate(encabezados):
        tabla.rows[0].cells[j].text = enc

    for participante in participantes:
        fila = tabla.add_row()
        usuario = participante.usuario
        fila.cells[0].text = usuario.get_full_name()
        fila.cells[1].text = str(participante.rol_en_reunion or getattr(usuario, 'cargo', '') or '—')

        firma_obj = acta.firmas.filter(usuario=usuario).first()
        if firma_obj and firma_obj.firmado:
            fila.cells[2].text = 'Sí'
            _insertar_firma_en_celda(fila.cells[3], firma_obj)
        else:
            fila.cells[2].text = 'No'
            fila.cells[3].text = 'Pendiente'

    # Mover la tabla al cuerpo del doc justo después del párrafo marcador
    p_element.addnext(tabla._tbl)
    # Eliminar el párrafo marcador
    p_element.getparent().remove(p_element)


def _insertar_firma_en_celda(celda, firma_obj):
    """
    Inserta la imagen de la firma en una celda. Intenta: archivo en disco,
    base64 en DB, y como último recurso texto "✓ Firmado".
    """
    from docx.shared import Inches

    imagen_bytes = None

    # 1. Archivo en disco
    if firma_obj.firma_imagen:
        try:
            firma_path = os.path.join(settings.MEDIA_ROOT, str(firma_obj.firma_imagen))
            if os.path.isfile(firma_path):
                with open(firma_path, 'rb') as f:
                    imagen_bytes = f.read()
        except Exception as e:
            logger.warning('plantilla_service: error leyendo firma_imagen: %s', e)

    # 2. Base64 en BD
    if not imagen_bytes and firma_obj.firma_datos:
        try:
            imagen_bytes = base64.b64decode(firma_obj.firma_datos)
        except Exception as e:
            logger.warning('plantilla_service: error decodificando firma_datos: %s', e)

    # 3. firma_digital del usuario
    if not imagen_bytes and hasattr(firma_obj.usuario, 'firma_digital') and firma_obj.usuario.firma_digital:
        try:
            firma_path = os.path.join(settings.MEDIA_ROOT, str(firma_obj.usuario.firma_digital))
            if os.path.isfile(firma_path):
                with open(firma_path, 'rb') as f:
                    imagen_bytes = f.read()
        except Exception as e:
            logger.warning('plantilla_service: error leyendo firma_digital: %s', e)

    if imagen_bytes:
        try:
            parrafo = celda.paragraphs[0]
            run = parrafo.add_run()
            run.add_picture(io.BytesIO(imagen_bytes), width=Inches(1.2))
            return
        except Exception as e:
            logger.warning('plantilla_service: error insertando imagen de firma: %s', e)

    # Fallback texto
    fecha = ''
    if firma_obj.fecha_firma:
        fecha = firma_obj.fecha_firma.strftime(' (%d/%m/%Y)')
    celda.paragraphs[0].text = f'✓ Firmado{fecha}'


def _insertar_tabla_compromisos(doc, acta):
    """
    Busca el marcador {{compromisos_tabla}} y lo reemplaza por una tabla
    con los compromisos del acta.
    """
    import re

    patron = re.compile(r'\{\{\s*compromisos_tabla\s*\}\}', re.IGNORECASE)

    for parrafo in doc.paragraphs:
        if patron.search(parrafo.text):
            _reemplazar_parrafo_por_tabla_compromisos(doc, parrafo, acta)
            return

    for tabla in doc.tables:
        for fila in tabla.rows:
            for celda in fila.cells:
                for parrafo in celda.paragraphs:
                    if patron.search(parrafo.text):
                        parrafo.clear()
                        _agregar_tabla_compromisos_en_celda(celda, acta)
                        return


def _reemplazar_parrafo_por_tabla_compromisos(doc, parrafo, acta):
    compromisos = acta.compromisos.select_related('responsable').all()
    p_element = parrafo._element

    tabla = doc.add_table(rows=1, cols=4)
    tabla.style = 'Table Grid'
    for j, enc in enumerate(['Descripción', 'Responsable', 'Fecha límite', 'Estado']):
        tabla.rows[0].cells[j].text = enc

    if compromisos.exists():
        for c in compromisos:
            fila = tabla.add_row()
            fila.cells[0].text = _texto_seguro(c.descripcion)
            resp = c.responsable
            fila.cells[1].text = resp.get_full_name() if resp else '—'
            fila.cells[2].text = c.fecha_limite.strftime('%d/%m/%Y') if c.fecha_limite else '—'
            fila.cells[3].text = _texto_seguro(c.get_estado_display() if hasattr(c, 'get_estado_display') else c.estado)
    else:
        fila = tabla.add_row()
        fila.cells[0].text = 'Sin compromisos registrados.'
        fila.cells[1].text = ''
        fila.cells[2].text = ''
        fila.cells[3].text = ''

    p_element.addnext(tabla._tbl)
    p_element.getparent().remove(p_element)


def _agregar_tabla_compromisos_en_celda(celda, acta):
    compromisos = acta.compromisos.select_related('responsable').all()

    tabla = celda.add_table(rows=1, cols=4)
    tabla.style = 'Table Grid'
    for j, enc in enumerate(['Descripción', 'Responsable', 'Fecha límite', 'Estado']):
        tabla.rows[0].cells[j].text = enc

    if compromisos.exists():
        for c in compromisos:
            fila = tabla.add_row()
            fila.cells[0].text = _texto_seguro(c.descripcion)
            resp = c.responsable
            fila.cells[1].text = resp.get_full_name() if resp else '—'
            fila.cells[2].text = c.fecha_limite.strftime('%d/%m/%Y') if c.fecha_limite else '—'
            fila.cells[3].text = _texto_seguro(c.get_estado_display() if hasattr(c, 'get_estado_display') else c.estado)
    else:
        fila = tabla.add_row()
        fila.cells[0].text = 'Sin compromisos registrados.'


# ---------------------------------------------------------------------------
# Conversión docx → PDF con LibreOffice
# ---------------------------------------------------------------------------

def _docx_a_pdf_libreoffice(docx_bytes):
    """
    Convierte bytes de .docx a bytes de .pdf usando LibreOffice headless.
    Retorna bytes del PDF o None si LibreOffice no está disponible o falla.
    Solo se activa si LIBREOFFICE_ENABLED=true en settings/env.
    """
    if not getattr(settings, 'LIBREOFFICE_ENABLED', False):
        return None

    libreoffice_path = getattr(settings, 'LIBREOFFICE_PATH', 'libreoffice')

    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = os.path.join(tmpdir, 'acta.docx')
        with open(docx_path, 'wb') as f:
            f.write(docx_bytes)

        try:
            resultado = subprocess.run(
                [
                    libreoffice_path,
                    '--headless',
                    '--convert-to', 'pdf',
                    '--outdir', tmpdir,
                    docx_path,
                ],
                capture_output=True,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning('plantilla_service: LibreOffice no disponible: %s', e)
            return None

        if resultado.returncode != 0:
            logger.warning(
                'plantilla_service: LibreOffice falló (código %d): %s',
                resultado.returncode,
                resultado.stderr.decode(errors='replace'),
            )
            return None

        pdf_path = os.path.join(tmpdir, 'acta.pdf')
        if not os.path.isfile(pdf_path):
            logger.warning('plantilla_service: LibreOffice no generó el PDF esperado.')
            return None

        with open(pdf_path, 'rb') as f:
            return f.read()


# ---------------------------------------------------------------------------
# Punto de entrada público
# ---------------------------------------------------------------------------

def generar_documento_desde_plantilla(acta):
    """
    Intenta generar un documento a partir de la plantilla Word configurada
    para el tipo de reunión del acta.

    Retorna un dict con:
        {
            'tipo': 'pdf' | 'docx',   # qué se pudo generar
            'bytes': <bytes>,          # contenido del archivo
            'nombre': <str>,           # nombre sugerido para descarga
        }
    o None si no hay plantilla activa para el tipo de reunión (usa ReportLab).
    """
    from actas.models import PlantillaActa
    from docx import Document as DocxDocument

    # Buscar plantilla activa
    try:
        plantilla = PlantillaActa.objects.get(
            tipo_reunion=acta.tipo_reunion,
            activa=True,
        )
    except PlantillaActa.DoesNotExist:
        logger.debug(
            'plantilla_service: sin plantilla para tipo_reunion=%s, usando ReportLab.',
            acta.tipo_reunion,
        )
        return None

    # Cargar el .docx
    try:
        plantilla.archivo.open('rb')
        docx_bytes_original = plantilla.archivo.read()
        plantilla.archivo.close()
    except Exception as e:
        logger.error('plantilla_service: error leyendo archivo de plantilla (id=%d): %s', plantilla.pk, e)
        return None

    # Abrir con python-docx
    try:
        doc = DocxDocument(io.BytesIO(docx_bytes_original))
    except Exception as e:
        logger.error('plantilla_service: no se puede abrir el docx (id=%d): %s', plantilla.pk, e)
        return None

    # Reemplazar marcadores simples (texto)
    marcadores = _construir_marcadores(acta)
    _reemplazar_marcadores_simples(doc, marcadores)

    # Insertar tablas dinámicas
    _insertar_tabla_participantes(doc, acta)
    _insertar_tabla_compromisos(doc, acta)

    # Serializar el docx modificado
    docx_buffer = io.BytesIO()
    doc.save(docx_buffer)
    docx_bytes = docx_buffer.getvalue()

    nombre_base = f"Acta_{acta.numero_acta}"

    # Intentar convertir a PDF con LibreOffice
    pdf_bytes = _docx_a_pdf_libreoffice(docx_bytes)
    if pdf_bytes:
        return {
            'tipo': 'pdf',
            'bytes': pdf_bytes,
            'nombre': f"{nombre_base}.pdf",
        }

    # Sin LibreOffice: devolver el .docx
    return {
        'tipo': 'docx',
        'bytes': docx_bytes,
        'nombre': f"{nombre_base}.docx",
    }
