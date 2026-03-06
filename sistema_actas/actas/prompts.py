"""
Prompts especializados por tipo de acta para la generación con IA (Groq).

Cada entrada de CONTEXTOS_POR_TIPO es un bloque de texto en inglés que se
inyecta en el prompt base de generar_acta_con_ia() para orientar al modelo
hacia el contexto específico de la reunión.

Si el tipo_acta no existe, se usa 'reunion_general' como fallback.
"""

# ---------------------------------------------------------------------------
# Choices del campo tipo_acta en el modelo Acta
# ---------------------------------------------------------------------------
TIPOS_ACTA = [
    ('comite_academico',   'Comité Académico'),
    ('comite_evaluacion',  'Comité de Evaluación y Seguimiento'),
    ('comite_convivencia', 'Comité de Convivencia'),
    ('reunion_coordinacion', 'Reunión de Coordinación'),
    ('reunion_instructores', 'Reunión de Instructores'),
    ('reunion_general',    'Reunión General'),
]

TIPOS_ACTA_DICT = dict(TIPOS_ACTA)


# ---------------------------------------------------------------------------
# Contextos especializados (en inglés para mayor precisión con el modelo LLM)
# ---------------------------------------------------------------------------
CONTEXTOS_POR_TIPO = {

    'comite_academico': """
MEETING TYPE: ACADEMIC COMMITTEE (Comite Academico - SENA)

SPECIALIZED CONTEXT:
This Academic Committee is focused on the academic performance of apprentices. It deals
with competency evaluations, learning outcomes, improvement plans, and pedagogical decisions.

GENERATE CONTENT THAT COVERS:
- Review of specific academic cases (apprentice groups, competency status, grades)
- Analysis of pending competencies and current qualification results
- Pedagogical action plans for underperforming apprentices
- Teaching strategies and methodological adjustments proposed
- Academic improvement commitments with clear deadlines
- Follow-up dates for each case or cohort reviewed

USE THIS TERMINOLOGY (without accents):
competencias, evidencias, resultados de aprendizaje, plan de mejoramiento,
seguimiento academico, rendimiento, aprendices, formacion, programa de formacion,
instructores de area, ficha de formacion, ruta de aprendizaje.
""",

    'comite_evaluacion': """
MEETING TYPE: EVALUATION AND MONITORING COMMITTEE (Comite de Evaluacion y Seguimiento)

SPECIALIZED CONTEXT:
This committee reviews the progress of previously established commitments and institutional
objectives. It is data-driven: indicators, compliance percentages, corrective measures.

GENERATE CONTENT THAT COVERS:
- Updated progress indicators for each commitment tracked
- Compliance percentage achieved vs. targets established
- Root cause analysis of gaps or deviations detected
- Corrective and preventive actions agreed upon
- Reassignment or adjustment of responsibilities and deadlines
- Documentation of results achieved in the current period

USE THIS TERMINOLOGY (without accents):
indicadores, porcentaje de cumplimiento, plan de accion, seguimiento, brecha,
medida correctiva, avance, resultado, responsable, fecha limite, meta.
""",

    'comite_convivencia': """
MEETING TYPE: COEXISTENCE COMMITTEE (Comite de Convivencia)

SPECIALIZED CONTEXT:
This committee addresses coexistence situations and conflict resolution in the SENA
training environment. It focuses on dialogue, institutional agreements, and follow-up.

GENERATE CONTENT THAT COVERS:
- Presentation of coexistence situations addressed (respectful and general, no personal data)
- Dialogue and mediation processes applied in each case
- Agreements and commitments reached between parties involved
- Preventive strategies for similar future situations
- Psychosocial support and institutional accompaniment actions
- Follow-up mechanisms and review dates for each case

USE THIS TERMINOLOGY (without accents):
convivencia, mediacion, acuerdos, seguimiento, resolucion de conflictos,
reglamento interno, ambiente de aprendizaje, bienestar, conducta, proceso disciplinario.
""",

    'reunion_coordinacion': """
MEETING TYPE: COORDINATION MEETING (Reunion de Coordinacion)

SPECIALIZED CONTEXT:
This is an administrative and operational coordination meeting between areas, instructors,
or departments. It focuses on planning, logistics, resource assignment, and process alignment.

GENERATE CONTENT THAT COVERS:
- Current status of pending administrative tasks and activities
- Coordination between different areas, instructors, or departments
- Scheduling and calendar of upcoming institutional activities
- Assignment of resources, spaces, and materials required
- Resolution of operational bottlenecks or inter-area conflicts
- Administrative decisions and their institutional justification

USE THIS TERMINOLOGY (without accents):
cronograma, asignacion, recursos, responsabilidades, coordinacion, actividades,
logistica, planeacion, seguimiento administrativo, areas de gestion, tarea.
""",

    'reunion_instructores': """
MEETING TYPE: INSTRUCTORS MEETING (Reunion de Instructores)

SPECIALIZED CONTEXT:
This meeting gathers instructors to discuss pedagogy, technical updates, share teaching
experiences, and plan training activities. It is both pedagogical and collegial in nature.

GENERATE CONTENT THAT COVERS:
- Pedagogical and methodological aspects of current training programs
- Technical updates, regulatory changes, or new competency requirements
- Sharing of teaching experiences and innovative approaches
- Planning of upcoming practical activities, field visits, or workshops
- Resolution of common challenges in the training environment
- Pedagogical commitments and professional development goals

USE THIS TERMINOLOGY (without accents):
metodologia, competencias tecnicas, estrategia pedagogica, materiales de formacion,
practica, evidencias de aprendizaje, ruta metodologica, instructor, guia de aprendizaje.
""",

    'reunion_general': """
MEETING TYPE: GENERAL INSTITUTIONAL MEETING (Reunion General)

SPECIALIZED CONTEXT:
This is a general institutional meeting addressing diverse topics of broad interest
to the SENA center. It covers communication of guidelines, general commitments, and
cross-functional coordination.

GENERATE CONTENT THAT COVERS:
- Communication of institutional guidelines, news, or directives
- General follow-up on cross-functional commitments
- Topics of broad interest affecting multiple areas or the entire center
- Coordination of joint activities or institutional events
- General decisions with institutional scope

USE THIS TERMINOLOGY (without accents):
lineamientos, directrices, compromisos, seguimiento, coordinacion institucional,
actividades, comunicacion oficial, decision institucional, acuerdos generales.
""",
}


def get_contexto_prompt(tipo_acta: str) -> str:
    """
    Retorna el bloque de contexto especializado para el tipo de acta dado.
    Fallback a 'reunion_general' si el tipo no existe.

    Args:
        tipo_acta: valor del campo tipo_acta del modelo Acta.

    Returns:
        Cadena de texto con el contexto especializado para el prompt de IA.
    """
    return CONTEXTOS_POR_TIPO.get(tipo_acta, CONTEXTOS_POR_TIPO['reunion_general'])
