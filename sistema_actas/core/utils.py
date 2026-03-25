from django.conf import settings
from django.core.mail import send_mail
from actas.services.ia_service import GroqService
import json
import logging
import re

logger = logging.getLogger(__name__)


def extract_json_from_string(text):
    """
    Limpia el texto de la IA buscando el objeto JSON entre {}.
    MEJORADO: Ahora limpia caracteres de control inválidos
    """
    try:
        # Limpiar markdown code blocks si existen
        text = text.replace('```json', '').replace('```', '').strip()
        
        # Busca el inicio de la primera llave de apertura y la última de cierre
        start_index = text.find('{')
        end_index = text.rfind('}')
        
        if start_index == -1 or end_index == -1:
            raise ValueError("No se encontró el inicio o fin de un objeto JSON.")
        
        json_string = text[start_index : end_index + 1]
        
        # ✅ LIMPIEZA ADICIONAL: Remover caracteres de control inválidos
        # Mantener solo saltos de línea (\n), tabs (\t) y espacios normales
        # Remover otros caracteres de control (0x00-0x1F excepto \n, \t, \r)
        json_string = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', json_string)
        
        return json.loads(json_string)
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decodificando JSON: {e}")
        logger.error(f"JSON problemático: {json_string[:500]}...")
        raise ValueError(f"Error al parsear JSON: {e}")
    except Exception as e:
        raise ValueError(f"Error al limpiar y parsear JSON: {e}")


def generar_acta_con_ia(resumen, usuario, tipo_acta='reunion_general'):
    """
    Genera contenido de acta usando Groq.
    Usa prompts especializados por tipo de acta para mayor precisión y relevancia.

    Args:
        resumen (str): Descripción breve de la reunión.
        usuario: Instancia del User que solicita la generación.
        tipo_acta (str): Tipo de acta ('comite_academico', 'reunion_coordinacion', etc.)
                         Fallback a 'reunion_general' si el tipo no existe.
    """
    try:
        # Obtener contexto especializado para el tipo de acta
        from actas.prompts import get_contexto_prompt, TIPOS_ACTA_DICT
        contexto_especializado = get_contexto_prompt(tipo_acta)
        tipo_label = TIPOS_ACTA_DICT.get(tipo_acta, 'Reunion General')
        logger.info(f'Generando acta con IA. Tipo: {tipo_acta} ({tipo_label}). Usuario: {usuario}')

        # Crear instancia del servicio Groq
        servicio_groq = GroqService()

        # Verificar conexión
        if not servicio_groq.verificar_conexion():
            raise Exception("No se pudo conectar con el servicio de IA (Groq)")

        # PROMPT CON CONTEXTO ESPECIALIZADO POR TIPO DE ACTA
        prompt_content = f"""You are a specialized assistant for generating SENA institutional meeting minutes in Spanish.

{contexto_especializado}

CRITICAL RULES:
- Response MUST be ONLY a valid JSON object
- NO accents (a,e,i,o,u instead of á,é,í,ó,ú)
- NO special characters or symbols
- NO quotes inside text values
- Use formal institutional language
- Write in Spanish without accents

Generate a JSON with these exact keys:

1. "orden_dia": Detailed numbered agenda (4-7 specific items)
   - Each item should be concrete and specific
   - Use institutional terminology
   - Format: "1. Item description\\n2. Next item\\n3. Another item..."

2. "desarrollo": EXTENSIVE and DETAILED meeting development (MINIMUM 300-400 words, 4-5 paragraphs)
   - First paragraph: Meeting opening, attendance verification, context
   - Second paragraph: Main topic presentation and initial discussions
   - Third paragraph: Detailed analysis, arguments presented, considerations discussed
   - Fourth paragraph: Decisions made, agreements reached, justifications
   - Fifth paragraph: Task assignments, commitments, follow-up actions, closure
   
DEVELOPMENT REQUIREMENTS:
- MUST be at least 300-400 words
- MUST have 4-5 well-developed paragraphs
- Use formal institutional language appropriate for SENA
- Mention specific details about points discussed
- Include discussions, arguments, and important considerations
- Describe decisions made and their justifications
- Reference institutional processes and procedures
- Use technical and professional terminology
- Each paragraph MUST be separated by \\n\\n

Example JSON structure:
{{
  "orden_dia": "1. Apertura de sesion y verificacion de asistencia\\n2. Presentacion del contexto y objetivos de la reunion\\n3. Analisis detallado de la propuesta presentada\\n4. Discusion de alternativas y consideraciones tecnicas\\n5. Toma de decisiones y aprobacion de acuerdos\\n6. Asignacion de responsabilidades y compromisos\\n7. Cierre y proximos pasos",
  "desarrollo": "La reunion dio inicio a la hora programada con la verificacion de asistencia de todos los participantes convocados. El director del comite realizo la apertura oficial presentando el orden del dia y los objetivos especificos a alcanzar durante la sesion. Se destaco la importancia de la tematica a tratar en el marco de los lineamientos institucionales del SENA y las politicas vigentes de la entidad.\\n\\nPosteriormente, se procedio a la presentacion detallada del tema principal por parte del coordinador designado. Se expusieron los antecedentes, el contexto actual y las implicaciones que el asunto tiene para los diferentes procesos formativos y administrativos del centro. Los asistentes tuvieron la oportunidad de plantear preguntas de clarificacion sobre aspectos especificos de la propuesta presentada.\\n\\nDurante la fase de analisis, se genero un debate constructivo donde cada participante aporto su perspectiva desde las diferentes areas de desempeno. Se evaluaron minuciosamente las ventajas y desventajas de las alternativas propuestas, considerando factores tecnicos, economicos, operativos y pedagogicos. Se destacaron aspectos como la viabilidad de implementacion, los recursos necesarios, los plazos estimados y el impacto esperado en la comunidad educativa.\\n\\nDespues de un analisis exhaustivo y la consideracion de todos los puntos de vista expresados, el comite procedio a la toma de decisiones mediante consenso. Se aprobo la propuesta principal con algunas modificaciones sugeridas durante la discusion, las cuales fueron incorporadas al documento final. Se establecieron los criterios de seguimiento y evaluacion que permitiran verificar el cumplimiento de los objetivos establecidos.\\n\\nFinalmente, se asignaron las responsabilidades especificas a cada uno de los miembros del equipo de trabajo, definiendo claramente las tareas, los plazos de entrega y los indicadores de cumplimiento. Se acordo realizar una reunion de seguimiento en un plazo determinado para evaluar el avance de las actividades programadas. El director del comite agradecio la participacion activa de todos los asistentes y declaro formalmente cerrada la sesion."
}}

Meeting information:
{resumen}

CRITICAL REMINDERS:
- The desarrollo MUST be 300-400 words minimum
- MUST have 4-5 complete paragraphs
- NO accents anywhere
- NO special characters
- Use only simple Spanish text
- Each paragraph separated by \\n\\n
- Be specific and detailed
- Use institutional SENA terminology

Generate the JSON now:"""

        # ⚡ GENERAR CON CONFIGURACIÓN MEJORADA
        contenido_json_str = servicio_groq.generar_texto(
            prompt=prompt_content,
            modelo=getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant'),
            max_tokens=2500,        # ✅ AUMENTADO para desarrollo extenso
            temperature=0.7         # ✅ Balance entre creatividad y coherencia
        )
        
        # 🔍 LOG PARA DEBUG (opcional)
        logger.info(f"=== RESPUESTA DE GROQ (primeros 300 chars) ===")
        logger.info(contenido_json_str[:300])
        
        # Limpiar y parsear la respuesta JSON
        data_ia = extract_json_from_string(contenido_json_str)
        
        # Validar claves
        if "orden_dia" not in data_ia or "desarrollo" not in data_ia:
            raise ValueError(f"JSON no contiene las claves esperadas: {data_ia.keys()}")
        
        # Devolver resultado
        return {
            "orden_dia": data_ia.get("orden_dia", "No generado"),
            "desarrollo": data_ia.get("desarrollo", "No generado"),
        }

    except ValueError as e:
        logger.error(f"Error de formato JSON: {e}")
        raise ValueError(f"Error de formato JSON: {e}")
    
    except Exception as e:
        logger.error(f"Error al generar con IA: {e}")
        raise Exception(f"Error al generar con IA: {e}")


def enviar_notificacion_participantes(participantes, asunto, mensaje):
    """
    Envía una notificación (por correo) a los participantes del acta.
    """
    try:
        destinatarios = [p.email for p in participantes if p.email]
        if destinatarios:
            send_mail(
                subject=asunto,
                message=mensaje,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=destinatarios,
                fail_silently=True,
            )
    except Exception as e:
        logger.error('Error al enviar notificacion por email: %s', e, exc_info=True)