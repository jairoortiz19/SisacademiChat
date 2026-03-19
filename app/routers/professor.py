"""
Endpoints del profesor - Solo lectura desde knowledge.db.

Todos los datos son pre-procesados por SisacademiServer y descargados
via POST /sync/knowledge. Estos endpoints solo leen la BD local.
Funcionan completamente OFFLINE despues de la primera sincronizacion.
"""
import json
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.repositories import knowledge_reader
from app.services.llm_client import ollama_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Profesor"])


def _check_tables():
    """Verifica que las tablas academicas existan en knowledge.db."""
    if not knowledge_reader._has_academic_tables():
        raise HTTPException(
            status_code=503,
            detail="Datos academicos no disponibles. Sincronice primero con POST /api/v1/sync/knowledge",
        )


# ==========================================
#  Dashboard
# ==========================================

@router.get(
    "/professor/dashboard",
    summary="Dashboard global del profesor",
    description="""
Panel de control integral que presenta al profesor una **radiografia completa**
de todos sus estudiantes en una sola vista.

**Que incluye:**

*   **Metricas generales:** total de estudiantes, total de evaluaciones aplicadas,
    promedio general de la institucion, nota minima y maxima registradas.
*   **Distribucion de calificaciones:** cuantos estudiantes caen en cada rango
    (reprobado, suficiente, bien, notable, sobresaliente), ideal para graficar
    un histograma o un grafico de pastel.
*   **Rendimiento por materia:** ranking de materias ordenadas de menor a mayor
    promedio — permite identificar de inmediato cuales necesitan atencion.
*   **Estudiantes en riesgo:** lista de los 20 estudiantes con promedio mas bajo
    (< 6.0), para intervencion inmediata.

**Caso de uso real:**
> La profesora Maria abre la app el lunes por la manana y ve el dashboard.
> Nota que Matematicas tiene promedio 5.2 (el mas bajo) y que 8 estudiantes estan
> en riesgo. Decide programar una sesion de refuerzo para el miercoles.
>
> El campo `resumen_narrativo` le dice:
> "Se identifican 18 estudiantes en situacion de riesgo academico. Matematicas
> requiere atencion prioritaria con promedio 6.1..."

**Funciona offline** — los datos se descargan del servidor central y se consultan localmente.
**Resumen narrativo** generado por IA si Ollama esta activo.
    """,
    response_description="Objeto JSON con metricas globales, distribucion, rendimiento por materia, estudiantes en riesgo y resumen narrativo.",
)
async def global_dashboard():
    _check_tables()
    dashboard = knowledge_reader.get_global_dashboard()

    # Generar resumen narrativo con LLM
    narrative = None
    try:
        if await ollama_client.is_available():
            prompt_data = _build_dashboard_narrative_prompt(dashboard)
            narrative = await _generate_with_llm(prompt_data)
    except Exception as e:
        logger.warning("No se pudo generar resumen narrativo: %s", e)

    dashboard["resumen_narrativo"] = narrative
    dashboard["generado_con_ia"] = narrative is not None
    return dashboard


def _build_dashboard_narrative_prompt(dashboard: dict) -> dict:
    """Construye prompt para generar resumen narrativo del dashboard."""
    system_prompt = """Eres un analista educativo. Genera un resumen ejecutivo breve (3-5 parrafos)
del estado academico general. El resumen sera leido por el profesor al iniciar su jornada.

REGLAS:
- Maximo 300 palabras
- Destaca lo MAS IMPORTANTE primero (alertas, riesgos)
- Incluye recomendaciones accionables
- Usa datos concretos (numeros, porcentajes)
- Escribe en espanol profesional pero claro
- NO uses formato markdown, solo texto plano"""

    materias_text = "\n".join(
        f"  - {m['source_name']}: promedio {m['promedio']:.1f} ({m['estudiantes']} estudiantes)"
        for m in dashboard.get("rendimiento_por_materia", [])
    )

    riesgo_text = "\n".join(
        f"  - {e['name']} ({e.get('group_name', 'Sin grupo')}): promedio {e['promedio']:.1f}"
        for e in dashboard.get("estudiantes_en_riesgo", [])[:10]
    )

    dist = dashboard.get("distribucion", {})
    total_eval = dashboard.get("total_evaluaciones", 0)
    reprobados_pct = (dist.get("reprobado", 0) / total_eval * 100) if total_eval else 0

    user_message = f"""Genera el resumen ejecutivo de este dashboard academico:

METRICAS GENERALES:
- Total estudiantes: {dashboard.get('total_estudiantes', 0)}
- Total evaluaciones: {dashboard.get('total_evaluaciones', 0)}
- Promedio general: {dashboard.get('promedio_general', 'N/A')}
- Nota minima: {dashboard.get('nota_minima', 'N/A')} | Nota maxima: {dashboard.get('nota_maxima', 'N/A')}

DISTRIBUCION:
- Reprobados: {dist.get('reprobado', 0)} ({reprobados_pct:.1f}% de evaluaciones)
- Suficiente: {dist.get('suficiente', 0)}
- Bien: {dist.get('bien', 0)}
- Notable: {dist.get('notable', 0)}
- Sobresaliente: {dist.get('sobresaliente', 0)}

RENDIMIENTO POR MATERIA (de menor a mayor):
{materias_text}

ESTUDIANTES EN RIESGO (top 10):
{riesgo_text}

Fecha: {date.today().strftime('%d/%m/%Y')}"""

    return {"system": system_prompt, "user": user_message}


# ==========================================
#  Grades
# ==========================================

@router.get(
    "/professor/grades/student/{student_id}",
    summary="Calificaciones de un estudiante",
    description="""
Historial completo de **calificaciones** de un estudiante, ordenado del mas
reciente al mas antiguo. Se puede filtrar opcionalmente por materia.

**Cada calificacion incluye:**
*   `source_name` — Materia (ej: "Matematicas", "Biologia")
*   `grade` / `max_grade` — Nota obtenida y nota maxima posible
*   `evaluation_type` — Tipo: examen, tarea, quiz, proyecto
*   `topic` — Tema especifico evaluado (si aplica)
*   `notes` — Observaciones del profesor
*   `created_at` — Fecha de la evaluacion

**Caso de uso real:**
> La mama de Ana quiere saber como va su hija en Matematicas.
> El profesor filtra con `?source_name=Matematicas` y ve:
> Quiz 1: 8.5, Tarea 2: 9.0, Examen parcial: 6.5, Tarea 3: 7.0.
> Nota que en examenes baja pero en tareas va bien.
    """,
    response_description="Objeto con datos del estudiante, lista de calificaciones y total.",
)
async def student_grades(
    student_id: int,
    source_name: Optional[str] = Query(None, description="Filtrar por materia (ej: 'Matematicas')"),
):
    _check_tables()
    student = knowledge_reader.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    grades = knowledge_reader.get_student_grades(student_id, source_name=source_name)
    return {"student": student, "grades": grades, "total": len(grades)}


# ==========================================
#  Analytics
# ==========================================

@router.get(
    "/professor/analytics/student/{student_id}",
    summary="Resumen academico de un estudiante",
    description="""
**Analisis estadistico completo** del rendimiento de un estudiante:

*   **General:** promedio global, nota minima/maxima, porcentaje promedio, total de evaluaciones.
*   **Por materia:** desglose del promedio en cada materia, ordenado de peor a mejor.
    Permite ver donde destaca y donde tiene dificultades.
*   **Por tipo de evaluacion:** promedio en examenes vs tareas vs quizzes.
    Revela si el estudiante es mejor en trabajos practicos que en examenes teoricos.

**Caso de uso real:**
> En la reunion de padres, el profesor muestra el resumen de Diego:
> - Promedio general: 7.2
> - Mejor materia: Historia (8.8)
> - Peor materia: Matematicas (5.9)
> - En tareas saca 8.1 pero en examenes solo 6.0
> Conclusion: Diego entiende los temas pero tiene dificultad con los examenes.
> Recomendacion: practicar con examenes de prueba.
    """,
    response_description="Resumen con promedios generales, desglose por materia y por tipo de evaluacion.",
)
async def student_summary(student_id: int):
    _check_tables()
    student = knowledge_reader.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    summary = knowledge_reader.get_student_summary(student_id)
    summary["student"] = student
    return summary


@router.get(
    "/professor/analytics/source/{source_name}",
    summary="Estadisticas completas de una materia",
    description="""
**Analisis profundo** de una materia/asignatura completa:

*   **Resumen:** total de evaluaciones, estudiantes evaluados, promedio, min/max.
*   **Distribucion de notas:** cuantos estudiantes en cada rango
    (Reprobado 0-5.9, Suficiente 6-6.9, Bien 7-7.9, Notable 8-8.9, Sobresaliente 9-10).
    Perfecto para generar un histograma.
*   **Estudiantes en riesgo:** los que tienen promedio < 7.0 en esta materia.
*   **Top estudiantes:** los 10 mejores de la materia.

**Caso de uso real:**
> El director pide un reporte de como va Matematicas. El profesor consulta este endpoint y ve:
> - 45 estudiantes evaluados, promedio 6.8
> - Distribucion: 12 reprobados, 10 suficientes, 8 bien, 10 notables, 5 sobresalientes
> - 12 estudiantes en riesgo (los reprobados)
> Con estos datos genera un informe visual en 5 minutos.
    """,
    response_description="Estadisticas con distribucion de notas, estudiantes en riesgo y top estudiantes.",
)
async def source_analytics(source_name: str):
    _check_tables()
    return knowledge_reader.get_source_analytics(source_name)


@router.get(
    "/professor/analytics/group/{group_name}",
    summary="Estadisticas de un grupo/seccion",
    description="""
Rendimiento academico de un **grupo completo** (seccion, salon, turno):

*   **Resumen del grupo:** total de estudiantes, evaluaciones, promedio general, min/max.
*   **Rendimiento por materia:** en que materias el grupo va bien y en cuales necesita refuerzo.
*   **Ranking interno:** clasificacion de todos los estudiantes del grupo de mejor a peor promedio.

**Caso de uso real:**
> La coordinadora quiere saber como va el grupo "2do-A":
> - 30 estudiantes, promedio general 7.4
> - Mejor materia del grupo: Historia (8.2)
> - Peor materia del grupo: Quimica (6.1)
> - Primer lugar: Sofia Lopez (9.1), Ultimo: Miguel Torres (4.8)
> Decide asignar un profesor adjunto para Quimica en este grupo.
    """,
    response_description="Estadisticas del grupo con desglose por materia y ranking de estudiantes.",
)
async def group_analytics(group_name: str):
    _check_tables()
    return knowledge_reader.get_group_analytics(group_name)


@router.get(
    "/professor/analytics/groups/compare",
    summary="Comparar rendimiento entre grupos",
    description="""
**Compara el rendimiento academico** de 2 o mas grupos lado a lado.

**Que incluye:**
*   **Ranking de grupos:** ordenados por promedio general. Muestra cantidad de estudiantes
    y evaluaciones de cada grupo.
*   **Comparacion por materia:** para cada materia, muestra el promedio de cada grupo,
    identifica cual es mejor y calcula la diferencia. Ordenado por mayor diferencia
    (las materias con mayor disparidad aparecen primero).
*   **Resumen textual:** frase generada automaticamente con el ranking.
*   **Analisis narrativo (IA):** si Ollama esta activo, genera un analisis profundo con
    patrones, causas posibles y recomendaciones concretas para cerrar brechas.

**Caso de uso real:**
> El director quiere comparar los turnos matutino y vespertino.
> Llama con `?groups=Matutino,Vespertino` y descubre:
> - Matutino: promedio 7.8, mejor en Matematicas (+1.2) y Ciencias (+0.8)
> - Vespertino: promedio 7.1, mejor en Educacion Fisica (+0.5)
>
> El analisis narrativo le dice:
> "La diferencia mas significativa se encuentra en Matematicas (1.2 puntos).
> Se recomienda que el profesor del turno matutino comparta su metodologia..."
>
> Con estos datos y el analisis, presenta un plan concreto en la junta de consejo tecnico.
    """,
    response_description="Ranking de grupos, comparacion por materia, resumen y analisis narrativo generado por IA.",
)
async def compare_groups(
    groups: str = Query(
        ...,
        description="Nombres de grupos separados por coma (ej: A1,A2,B1)",
        examples=["A1,A2", "Matutino,Vespertino", "3ro-A,3ro-B,3ro-C"],
    ),
):
    _check_tables()
    group_names = [g.strip() for g in groups.split(",") if g.strip()]
    if len(group_names) < 2:
        raise HTTPException(status_code=400, detail="Se requieren al menos 2 grupos para comparar")
    comparison = knowledge_reader.compare_groups(group_names)

    # Generar analisis narrativo con LLM
    narrative = None
    try:
        if await ollama_client.is_available():
            prompt_data = _build_comparison_narrative_prompt(comparison)
            narrative = await _generate_with_llm(prompt_data)
    except Exception as e:
        logger.warning("No se pudo generar analisis de comparacion: %s", e)

    comparison["analisis_narrativo"] = narrative
    comparison["generado_con_ia"] = narrative is not None
    return comparison


def _build_comparison_narrative_prompt(comparison: dict) -> dict:
    """Construye prompt para generar analisis narrativo de comparacion de grupos."""
    system_prompt = """Eres un analista educativo experto. Genera un analisis comparativo profundo
entre los grupos academicos. El analisis sera usado por directivos para tomar decisiones.

REGLAS:
- Maximo 400 palabras
- Identifica patrones y diferencias significativas
- Sugiere acciones concretas para cerrar brechas
- Usa datos concretos (promedios, diferencias, porcentajes)
- Destaca tanto fortalezas como areas de mejora de cada grupo
- Escribe en espanol profesional
- NO uses formato markdown, solo texto plano"""

    ranking_text = "\n".join(
        f"  {i+1}. {g['group_name']}: promedio {g['promedio']}, {g['estudiantes']} estudiantes, {g['evaluaciones']} evaluaciones"
        for i, g in enumerate(comparison.get("ranking", []))
    )

    materias_text = ""
    for m in comparison.get("por_materia", []):
        materias_text += f"\n  {m['source_name']}:"
        for gn in comparison.get("grupos_comparados", []):
            if gn in m and isinstance(m[gn], dict):
                materias_text += f" {gn}={m[gn]['promedio']}"
        mejor = m.get("mejor_grupo", "N/A")
        diff = m.get("diferencia", 0)
        materias_text += f" | Mejor: {mejor} (+{diff})"

    user_message = f"""Genera un analisis comparativo de estos grupos:

GRUPOS COMPARADOS: {', '.join(comparison.get('grupos_comparados', []))}

RANKING GENERAL:
{ranking_text}

COMPARACION POR MATERIA:
{materias_text}

RESUMEN ESTADISTICO: {comparison.get('resumen', '')}

Genera un analisis que incluya:
1. Vision general de la comparacion
2. Materias con mayor disparidad y posibles causas
3. Fortalezas de cada grupo
4. Recomendaciones concretas para cerrar brechas
5. Sugerencias de intercambio de practicas entre grupos"""

    return {"system": system_prompt, "user": user_message}


# ==========================================
#  Plan de mejora y prediccion
# ==========================================

@router.get(
    "/professor/student/{student_id}/improvement-plan",
    summary="Plan de mejora completo generado con IA",
    description="""
Genera un **plan de mejora academica completo y personalizado** listo para
imprimir y entregar al estudiante o a sus padres.

**El proceso:**
1. Analiza calificaciones e identifica materias y temas criticos
2. Busca material de estudio relevante en la base de conocimiento (RAG)
3. Envia todo al modelo de IA local (Ollama) para generar un plan en lenguaje natural

**El plan incluye:**
*   **Encabezado formal** con datos del estudiante, grupo, fecha y promedio
*   **Diagnostico por materia** con temas especificos donde falla
*   **Material de repaso** extraido de los documentos del profesor (paginas exactas)
*   **Acciones concretas** por materia con plazos sugeridos
*   **Estrategias** segun el tipo de evaluacion donde mas falla
*   **Fortalezas** del estudiante como factor motivacional
*   **Firma** del profesor para formalizar el documento

**Caso de uso real:**
> El tutor de Andrea genera el plan y obtiene un documento completo:
>
> PLAN DE MEJORA ACADEMICA
> Estudiante: Andrea Gomez | Grupo: 3ro-B | Fecha: 2026-02-17
>
> MATEMATICAS (Promedio: 4.5 - Empeorando)
>   Temas criticos: Ecuaciones cuadraticas (3.0), Fracciones (4.5)
>   Material de repaso: Ver paginas 23-28 de Matematicas.pdf
>   Accion: Tutoria semanal enfocada en ecuaciones, resolver 10 ejercicios diarios
>
> FORTALEZAS: Historia (8.5), Literatura (8.2)
>
> El tutor imprime el plan, lo firma y lo entrega a los padres de Andrea.

**Requiere Ollama activo** para generar el texto. Si Ollama no esta disponible,
retorna los datos estructurados sin el texto generado.
    """,
    response_description="Plan completo con datos estructurados y texto generado por IA listo para imprimir.",
)
async def improvement_plan(student_id: int):
    _check_tables()
    student = knowledge_reader.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    # Obtener datos detallados (con temas y material RAG)
    detailed_data = knowledge_reader.get_detailed_improvement_data(student_id)
    if not detailed_data:
        raise HTTPException(status_code=404, detail="No hay datos academicos para este estudiante")

    # Tambien obtener el plan basico (para datos estructurados)
    basic_plan = knowledge_reader.get_improvement_plan(student_id)

    # Construir prompt para el LLM
    prompt_data = _build_improvement_prompt(detailed_data)

    # Intentar generar con Ollama
    plan_text = None
    try:
        if await ollama_client.is_available():
            plan_text = await _generate_with_llm(prompt_data)
    except Exception as e:
        logger.warning("No se pudo generar plan con LLM: %s", e)

    return {
        **basic_plan,
        "materias_detalle": detailed_data["materias_detalle"],
        "plan_imprimible": plan_text,
        "generado_con_ia": plan_text is not None,
    }


def _build_improvement_prompt(data: dict) -> dict:
    """Construye el system prompt y user message para generar el plan."""
    student = data["student"]
    today = date.today().strftime("%d/%m/%Y")

    system_prompt = """Eres un asesor educativo experto. Tu tarea es generar un PLAN DE MEJORA ACADEMICA
completo, profesional y listo para imprimir. El plan sera entregado al estudiante y a sus padres.

REGLAS:
- Escribe en espanol formal pero cercano
- Se especifico: menciona temas exactos, paginas del material, acciones concretas con plazos
- Usa el material de estudio proporcionado para recomendar paginas y contenido exacto
- Incluye las fortalezas del estudiante como motivacion
- El documento debe tener formato limpio para imprimir
- NO inventes datos: usa SOLO la informacion proporcionada
- Si hay material de estudio disponible, citalo con fuente y pagina"""

    # Construir contexto detallado
    materias_text = ""
    for m in data["materias_detalle"]:
        materias_text += f"\n--- {m['source_name']} ---\n"
        materias_text += f"Promedio: {m['promedio']} | Evaluaciones: {m['evaluaciones']} | Tendencia: {m['tendencia']}\n"

        if m["temas_criticos"]:
            materias_text += "Temas con peores notas:\n"
            for t in m["temas_criticos"]:
                materias_text += f"  - {t['topic']}: nota {t['grade']}/{t['max_grade']} ({t['evaluation_type']})\n"

        if m["material_estudio"]:
            materias_text += "Material de estudio disponible:\n"
            for mat in m["material_estudio"]:
                page_info = f", pagina {mat['pagina']}" if mat["pagina"] else ""
                materias_text += f"  - [{mat['fuente']}{page_info}]: \"{mat['texto'][:300]}...\"\n"

    fuertes_text = ""
    if data["materias_fuertes"]:
        fuertes_text = "Materias fuertes: " + ", ".join(
            f"{s['source_name']} ({s['promedio']})" for s in data["materias_fuertes"]
        )

    tipos_text = ""
    if data["tipos_debiles"]:
        tipos_text = "Tipos de evaluacion problematicos: " + ", ".join(
            f"{t['evaluation_type']} (promedio {t['promedio']:.1f})" for t in data["tipos_debiles"]
        )

    por_tipo_text = "Rendimiento por tipo de evaluacion: " + ", ".join(
        f"{t['evaluation_type']}: {t['promedio']:.1f}" for t in data["por_tipo"]
    )

    user_message = f"""Genera el plan de mejora completo para este estudiante:

DATOS DEL ESTUDIANTE:
- Nombre: {student['name']}
- Grupo: {student.get('group') or 'Sin grupo'}
- Fecha: {today}
- Promedio general: {data['promedio_general']}
- Total de evaluaciones: {data['total_evaluaciones']}

MATERIAS DEBILES (promedio < 7.0):
{materias_text}

{fuertes_text}
{tipos_text}
{por_tipo_text}

Genera el plan completo con este formato:

PLAN DE MEJORA ACADEMICA
========================
[Encabezado con datos del estudiante]

DIAGNOSTICO GENERAL
[Parrafo resumen de la situacion actual]

[Para cada materia debil:]
MATERIA: [nombre] (Promedio: X, Tendencia: Y)
  Temas a reforzar:
    - [tema especifico con nota]
  Material de repaso:
    - [fuente, pagina, descripcion breve del contenido]
  Plan de accion:
    - [acciones concretas con plazos semanales]

ESTRATEGIA POR TIPO DE EVALUACION
[Recomendaciones segun donde mas falla: examenes, tareas, quizzes]

FORTALEZAS Y MOTIVACION
[Destacar materias fuertes como base de confianza]

COMPROMISOS
[3-5 compromisos concretos que el estudiante puede firmar]

___________________________
Firma del profesor

___________________________
Firma del estudiante/tutor"""

    return {"system": system_prompt, "user": user_message}


async def _generate_with_llm(prompt_data: dict) -> str:
    """Genera texto usando Ollama a partir de un system/user prompt."""
    messages = [
        {"role": "system", "content": prompt_data["system"]},
        {"role": "user", "content": prompt_data["user"]},
    ]

    full_response = []
    async for token, stats in ollama_client.stream_chat(messages):
        if token:
            full_response.append(token)

    return "".join(full_response)


# ==========================================
#  Ejercicios de practica (LLM)
# ==========================================

@router.get(
    "/professor/student/{student_id}/practice-exercises",
    summary="Ejercicios de practica personalizados con IA",
    description="""
Genera **ejercicios de practica personalizados** para las materias debiles del estudiante,
utilizando el material real del curso (busqueda semantica en la base de conocimiento) y el
modelo de IA local (Ollama).

**El proceso:**
1. Identifica materias y temas donde el estudiante tiene bajo rendimiento
2. Busca contenido relevante en los documentos del profesor (RAG)
3. Envia el material al LLM para generar ejercicios adaptados al nivel del estudiante

**Los ejercicios incluyen:**
*   **Ejercicios graduados** de menor a mayor dificultad
*   **Basados en material real** del curso (no inventados)
*   **Con respuestas** para autoevaluacion
*   **Organizados por materia** y tema critico
*   **Nivel adaptado** segun el promedio actual del estudiante

**Caso de uso real:**
> El profesor genera ejercicios para Pedro que tiene 4.2 en Matematicas.
> El sistema detecta que falla en "Ecuaciones cuadraticas" y "Fracciones".
> Busca en el PDF de Matematicas del profesor y genera:
>
> MATEMATICAS - Ejercicios de Repaso
>
> TEMA: Ecuaciones cuadraticas (nota actual: 3.5)
> Basado en: Matematicas.pdf, paginas 23-28
>
> Nivel Basico:
> 1. Resuelve: x^2 - 4 = 0
>    Pista: Factoriza como diferencia de cuadrados.
>    Respuesta: x = 2, x = -2
>
> Nivel Intermedio:
> 2. Resuelve usando la formula general: 2x^2 - 5x + 3 = 0
>    Respuesta: x = 3/2, x = 1
>
> El profesor imprime los ejercicios y los entrega como tarea personalizada.

**Requiere Ollama activo.** Si no esta disponible, retorna los datos
estructurados (temas criticos + material encontrado) sin ejercicios generados.
    """,
    response_description="Ejercicios de practica generados por IA, organizados por materia y tema.",
)
async def practice_exercises(student_id: int):
    _check_tables()
    student = knowledge_reader.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    detailed_data = knowledge_reader.get_detailed_improvement_data(student_id, top_k=5)
    if not detailed_data or not detailed_data["materias_detalle"]:
        raise HTTPException(
            status_code=404,
            detail="No hay materias debiles para generar ejercicios o no hay datos academicos.",
        )

    prompt_data = _build_exercises_prompt(detailed_data)

    exercises_text = None
    try:
        if await ollama_client.is_available():
            exercises_text = await _generate_with_llm(prompt_data)
    except Exception as e:
        logger.warning("No se pudo generar ejercicios con LLM: %s", e)

    return {
        "student": detailed_data["student"],
        "promedio_general": detailed_data["promedio_general"],
        "materias_detalle": detailed_data["materias_detalle"],
        "ejercicios_generados": exercises_text,
        "generado_con_ia": exercises_text is not None,
    }


def _build_exercises_prompt(data: dict) -> dict:
    """Construye prompt para generar ejercicios de practica."""
    student = data["student"]

    system_prompt = """Eres un profesor experto generando ejercicios de practica personalizados.
Tu tarea es crear ejercicios de repaso basandote ESTRICTAMENTE en el material de estudio proporcionado.

REGLAS:
- Genera ejercicios GRADUADOS: basico, intermedio, avanzado
- Cada ejercicio debe incluir respuesta para autoevaluacion
- Usa SOLO el material proporcionado como referencia (no inventes contenido nuevo)
- Adapta la dificultad al nivel actual del estudiante (basado en su promedio)
- Para cada tema, genera entre 3 y 5 ejercicios
- Incluye pistas en los ejercicios basicos
- Formato limpio y listo para imprimir
- Escribe en espanol"""

    materias_text = ""
    for m in data["materias_detalle"]:
        materias_text += f"\n=== {m['source_name']} (Promedio: {m['promedio']}) ===\n"

        if m["temas_criticos"]:
            materias_text += "Temas con bajo rendimiento:\n"
            for t in m["temas_criticos"]:
                materias_text += f"  - {t['topic']}: nota {t['grade']}/{t['max_grade']} ({t['evaluation_type']})\n"

        if m["material_estudio"]:
            materias_text += "Material de referencia del curso:\n"
            for mat in m["material_estudio"]:
                page_info = f", pagina {mat['pagina']}" if mat["pagina"] else ""
                materias_text += f"  - [{mat['fuente']}{page_info}]: \"{mat['texto'][:500]}\"\n"

    user_message = f"""Genera ejercicios de practica para:

ESTUDIANTE: {student['name']}
GRUPO: {student.get('group') or 'Sin grupo'}
PROMEDIO GENERAL: {data['promedio_general']}

MATERIAS Y TEMAS A REFORZAR:
{materias_text}

Genera ejercicios con este formato:

EJERCICIOS DE PRACTICA PERSONALIZADOS
Estudiante: {student['name']} | Fecha: {date.today().strftime('%d/%m/%Y')}

[Para cada materia debil:]
---
MATERIA: [nombre] (Tu promedio: X)
Tema: [tema critico]
Referencia: [fuente, pagina]

Nivel Basico:
1. [ejercicio]
   Pista: [ayuda]
   Respuesta: [solucion]

Nivel Intermedio:
2. [ejercicio]
   Respuesta: [solucion]

Nivel Avanzado:
3. [ejercicio de aplicacion]
   Respuesta: [solucion]
---

AUTOEVALUACION
- Si resolviste todos los basicos: Vas por buen camino, sigue con intermedios.
- Si resolviste los intermedios: Excelente, intenta los avanzados.
- Si resolviste los avanzados: Dominas el tema, pasa al siguiente."""

    return {"system": system_prompt, "user": user_message}


# ==========================================
#  Prediccion
# ==========================================

@router.get(
    "/professor/student/{student_id}/prediction",
    summary="Prediccion de rendimiento con IA",
    description="""
**Predice el rendimiento futuro** del estudiante utilizando **regresion lineal**
sobre su historial de calificaciones. Analiza la tendencia de cada materia para
anticipar resultados y permitir intervencion preventiva.

**Metodologia:**
Para cada materia con 3 o mas evaluaciones, el sistema:
1. Aplica regresion lineal sobre las notas en orden cronologico
2. Calcula la pendiente (velocidad de mejora o deterioro)
3. Extrapola la nota del proximo examen
4. Estima la probabilidad de aprobar

**Clasificacion de tendencia:**
*   Pendiente > 0.1 = **Mejorando**
*   Pendiente < -0.1 = **Empeorando**
*   Intermedio = **Estable**

**Nivel de riesgo global:**
*   **Bajo:** promedio >= 8.0 y sin materias criticas
*   **Medio:** promedio >= 7.0 con maximo 1 materia critica
*   **Alto:** promedio >= 5.0
*   **Critico:** promedio < 5.0

**Caso de uso real:**
> El sistema predice para Luis (promedio 6.3):
>
> | Materia | Promedio | Tendencia | Prediccion | Prob. Aprobar |
> |---------|----------|-----------|------------|---------------|
> | Matematicas | 5.8 | Mejorando (+0.3) | 6.5 | 72% |
> | Fisica | 4.5 | Empeorando (-0.4) | 3.8 | 35% |
> | Historia | 8.2 | Estable | 8.3 | 95% |
>
> **Riesgo global: ALTO**
> **Materias criticas:** Fisica
> **Mensaje:** "Tendencia positiva en Matematicas. Fisica requiere atencion urgente."
>
> El profesor decide actuar ANTES de que Luis repruebe Fisica:
> asigna tutoria extra y material de repaso del chatbot.
    """,
    response_description="Prediccion con riesgo global, tendencia por materia, nota predicha, probabilidad de aprobar y materias criticas.",
)
async def performance_prediction(student_id: int):
    _check_tables()
    student = knowledge_reader.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    return knowledge_reader.get_performance_prediction(student_id)
