"""
Repositorio de solo lectura para datos academicos de knowledge.db.

Los datos (students, grades) son procesados por SisacademiServer
y descargados via POST /sync/knowledge. Este modulo solo los lee.
"""
import logging
from collections import defaultdict

from app.database import open_knowledge_db as get_knowledge_db

logger = logging.getLogger(__name__)


# ==========================================
#  Utilidades
# ==========================================

def _linear_regression(values: list[float]) -> tuple[float, float]:
    """Regresion lineal simple. Retorna (pendiente, intercepto)."""
    n = len(values)
    if n < 2:
        return 0.0, values[0] if values else 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = numerator / denominator if denominator != 0 else 0.0
    intercept = y_mean - slope * x_mean
    return slope, intercept


def _has_academic_tables() -> bool:
    """Verifica si knowledge.db tiene las tablas de students y grades."""
    conn = get_knowledge_db()
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('students', 'grades')"
        ).fetchall()
        return len(tables) == 2
    except Exception:
        return False
    finally:
        conn.close()


# ==========================================
#  Students (solo lectura)
# ==========================================

def get_student(student_id: int) -> dict | None:
    conn = get_knowledge_db()
    try:
        row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_students(group_name: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
    conn = get_knowledge_db()
    try:
        if group_name:
            rows = conn.execute(
                "SELECT * FROM students WHERE group_name = ? ORDER BY name LIMIT ? OFFSET ?",
                (group_name, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM students ORDER BY name LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def count_students(group_name: str | None = None) -> int:
    conn = get_knowledge_db()
    try:
        if group_name:
            return conn.execute(
                "SELECT COUNT(*) FROM students WHERE group_name = ?", (group_name,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    finally:
        conn.close()


def list_groups() -> list[dict]:
    conn = get_knowledge_db()
    try:
        rows = conn.execute(
            """SELECT group_name, COUNT(*) as student_count
               FROM students WHERE group_name IS NOT NULL
               GROUP BY group_name ORDER BY group_name"""
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ==========================================
#  Grades (solo lectura)
# ==========================================

def get_student_grades(student_id: int, source_name: str | None = None) -> list[dict]:
    conn = get_knowledge_db()
    try:
        if source_name:
            rows = conn.execute(
                """SELECT * FROM grades
                   WHERE student_id = ? AND source_name = ?
                   ORDER BY created_at DESC""",
                (student_id, source_name),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM grades WHERE student_id = ? ORDER BY created_at DESC",
                (student_id,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_grades_by_source(source_name: str) -> list[dict]:
    conn = get_knowledge_db()
    try:
        rows = conn.execute(
            """SELECT g.*, s.name as student_name, s.group_name
               FROM grades g JOIN students s ON s.id = g.student_id
               WHERE g.source_name = ?
               ORDER BY s.name""",
            (source_name,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ==========================================
#  Analytics (solo lectura)
# ==========================================

def get_student_summary(student_id: int) -> dict:
    conn = get_knowledge_db()
    try:
        row = conn.execute(
            """SELECT
                   COUNT(*) as total_evaluaciones,
                   AVG(grade) as promedio_general,
                   MIN(grade) as nota_minima,
                   MAX(grade) as nota_maxima,
                   AVG(grade / max_grade * 100) as porcentaje_promedio
               FROM grades WHERE student_id = ?""",
            (student_id,),
        ).fetchone()
        summary = dict(row)

        rows = conn.execute(
            """SELECT source_name, AVG(grade) as promedio, COUNT(*) as evaluaciones,
                      MIN(grade) as minima, MAX(grade) as maxima
               FROM grades WHERE student_id = ?
               GROUP BY source_name ORDER BY promedio ASC""",
            (student_id,),
        ).fetchall()
        summary["por_materia"] = [dict(r) for r in rows]

        rows = conn.execute(
            """SELECT evaluation_type, AVG(grade) as promedio, COUNT(*) as cantidad
               FROM grades WHERE student_id = ?
               GROUP BY evaluation_type""",
            (student_id,),
        ).fetchall()
        summary["por_tipo"] = [dict(r) for r in rows]

        return summary
    finally:
        conn.close()


def get_source_analytics(source_name: str) -> dict:
    conn = get_knowledge_db()
    try:
        row = conn.execute(
            """SELECT
                   COUNT(*) as total_evaluaciones,
                   COUNT(DISTINCT student_id) as total_estudiantes,
                   AVG(grade) as promedio_general,
                   MIN(grade) as nota_minima,
                   MAX(grade) as nota_maxima,
                   AVG(grade / max_grade * 100) as porcentaje_promedio
               FROM grades WHERE source_name = ?""",
            (source_name,),
        ).fetchone()
        analytics = dict(row)

        ranges = [
            ("Reprobado (0-5.9)", 0, 5.9),
            ("Suficiente (6-6.9)", 6, 6.9),
            ("Bien (7-7.9)", 7, 7.9),
            ("Notable (8-8.9)", 8, 8.9),
            ("Sobresaliente (9-10)", 9, 10),
        ]
        distribution = []
        for label, low, high in ranges:
            count = conn.execute(
                "SELECT COUNT(*) FROM grades WHERE source_name = ? AND grade >= ? AND grade <= ?",
                (source_name, low, high),
            ).fetchone()[0]
            distribution.append({"rango": label, "cantidad": count})
        analytics["distribucion"] = distribution

        rows = conn.execute(
            """SELECT s.id as student_id, s.name, s.group_name,
                      AVG(g.grade) as promedio, COUNT(g.id) as evaluaciones
               FROM grades g JOIN students s ON s.id = g.student_id
               WHERE g.source_name = ?
               GROUP BY s.id HAVING promedio < 7.0
               ORDER BY promedio ASC LIMIT 20""",
            (source_name,),
        ).fetchall()
        analytics["estudiantes_en_riesgo"] = [dict(r) for r in rows]

        rows = conn.execute(
            """SELECT s.id as student_id, s.name, s.group_name,
                      AVG(g.grade) as promedio, COUNT(g.id) as evaluaciones
               FROM grades g JOIN students s ON s.id = g.student_id
               WHERE g.source_name = ?
               GROUP BY s.id ORDER BY promedio DESC LIMIT 10""",
            (source_name,),
        ).fetchall()
        analytics["top_estudiantes"] = [dict(r) for r in rows]

        return analytics
    finally:
        conn.close()


def get_group_analytics(group_name: str) -> dict:
    conn = get_knowledge_db()
    try:
        row = conn.execute(
            """SELECT
                   COUNT(DISTINCT g.student_id) as total_estudiantes,
                   COUNT(g.id) as total_evaluaciones,
                   AVG(g.grade) as promedio_general,
                   MIN(g.grade) as nota_minima,
                   MAX(g.grade) as nota_maxima
               FROM grades g JOIN students s ON s.id = g.student_id
               WHERE s.group_name = ?""",
            (group_name,),
        ).fetchone()
        analytics = dict(row)

        rows = conn.execute(
            """SELECT g.source_name, AVG(g.grade) as promedio,
                      COUNT(DISTINCT g.student_id) as estudiantes
               FROM grades g JOIN students s ON s.id = g.student_id
               WHERE s.group_name = ?
               GROUP BY g.source_name ORDER BY promedio ASC""",
            (group_name,),
        ).fetchall()
        analytics["por_materia"] = [dict(r) for r in rows]

        rows = conn.execute(
            """SELECT s.id as student_id, s.name, AVG(g.grade) as promedio,
                      COUNT(g.id) as evaluaciones
               FROM grades g JOIN students s ON s.id = g.student_id
               WHERE s.group_name = ?
               GROUP BY s.id ORDER BY promedio DESC""",
            (group_name,),
        ).fetchall()
        analytics["ranking"] = [dict(r) for r in rows]

        return analytics
    finally:
        conn.close()


def get_improvement_plan(student_id: int) -> dict:
    student = get_student(student_id)
    if not student:
        return {"error": "Estudiante no encontrado"}

    summary = get_student_summary(student_id)

    weak_subjects = [
        m for m in summary["por_materia"]
        if m["promedio"] is not None and m["promedio"] < 7.0
    ]

    strong_subjects = [
        m for m in summary["por_materia"]
        if m["promedio"] is not None and m["promedio"] >= 8.0
    ]

    conn = get_knowledge_db()
    try:
        trends = []
        for subject in weak_subjects:
            grades = conn.execute(
                """SELECT grade, created_at FROM grades
                   WHERE student_id = ? AND source_name = ?
                   ORDER BY created_at ASC""",
                (student_id, subject["source_name"]),
            ).fetchall()
            grades_list = [dict(g) for g in grades]
            if len(grades_list) >= 2:
                first_half = grades_list[:len(grades_list) // 2]
                second_half = grades_list[len(grades_list) // 2:]
                avg_first = sum(g["grade"] for g in first_half) / len(first_half)
                avg_second = sum(g["grade"] for g in second_half) / len(second_half)
                trend = "mejorando" if avg_second > avg_first else "empeorando" if avg_second < avg_first else "estable"
            else:
                trend = "sin datos suficientes"

            trends.append({
                "source_name": subject["source_name"],
                "promedio": round(subject["promedio"], 2),
                "evaluaciones": subject["evaluaciones"],
                "tendencia": trend,
            })
    finally:
        conn.close()

    weak_types = [
        t for t in summary["por_tipo"]
        if t["promedio"] is not None and t["promedio"] < 7.0
    ]

    recommendations = []
    if weak_subjects:
        topics_str = ", ".join(s["source_name"] for s in weak_subjects[:3])
        recommendations.append(
            f"Reforzar estudio en: {topics_str}. Estas son las materias con menor rendimiento."
        )

    for weak in weak_types:
        if weak["evaluation_type"] == "examen":
            recommendations.append(
                "Mejorar preparacion para examenes. Considerar sesiones de repaso y simulacros."
            )
        elif weak["evaluation_type"] == "tarea":
            recommendations.append(
                "Dedicar mas tiempo a las tareas. Revisar la calidad de entregas."
            )
        elif weak["evaluation_type"] == "quiz":
            recommendations.append(
                "Practicar con quizzes cortos para mejorar respuesta rapida."
            )

    if summary["promedio_general"] is not None and summary["promedio_general"] < 6.0:
        recommendations.append(
            "ALERTA: Promedio general critico. Considerar tutoria personalizada."
        )

    if not recommendations:
        recommendations.append("El estudiante tiene un rendimiento satisfactorio. Mantener el ritmo actual.")

    return {
        "student": {
            "id": student["id"],
            "name": student["name"],
            "group": student.get("group_name"),
        },
        "promedio_general": round(summary["promedio_general"], 2) if summary["promedio_general"] else None,
        "total_evaluaciones": summary["total_evaluaciones"],
        "materias_debiles": trends,
        "materias_fuertes": [
            {"source_name": s["source_name"], "promedio": round(s["promedio"], 2)}
            for s in strong_subjects
        ],
        "tipos_debiles": weak_types,
        "recomendaciones": recommendations,
    }


def get_detailed_improvement_data(student_id: int, top_k: int = 3) -> dict | None:
    """
    Recopila datos detallados para generar un plan de mejora completo con LLM.
    Incluye: temas especificos donde falla + material de estudio relevante (RAG).
    """
    from app.infrastructure import embedder
    from app.repositories import vector_store

    student = get_student(student_id)
    if not student:
        return None

    summary = get_student_summary(student_id)
    if not summary["total_evaluaciones"]:
        return None

    weak_subjects = [
        m for m in summary["por_materia"]
        if m["promedio"] is not None and m["promedio"] < 7.0
    ]
    strong_subjects = [
        m for m in summary["por_materia"]
        if m["promedio"] is not None and m["promedio"] >= 8.0
    ]

    conn = get_knowledge_db()
    try:
        materias_detalle = []
        for subject in weak_subjects:
            sn = subject["source_name"]

            # Temas especificos con peor nota
            topic_rows = conn.execute(
                """SELECT topic, grade, max_grade, evaluation_type, created_at
                   FROM grades
                   WHERE student_id = ? AND source_name = ? AND topic IS NOT NULL
                   ORDER BY grade ASC LIMIT 10""",
                (student_id, sn),
            ).fetchall()
            temas_criticos = [dict(r) for r in topic_rows]

            # Todas las notas para tendencia
            all_grades = conn.execute(
                """SELECT grade, created_at FROM grades
                   WHERE student_id = ? AND source_name = ?
                   ORDER BY created_at ASC""",
                (student_id, sn),
            ).fetchall()
            grades_list = [dict(g) for g in all_grades]

            if len(grades_list) >= 2:
                first_half = grades_list[:len(grades_list) // 2]
                second_half = grades_list[len(grades_list) // 2:]
                avg_first = sum(g["grade"] for g in first_half) / len(first_half)
                avg_second = sum(g["grade"] for g in second_half) / len(second_half)
                tendencia = "mejorando" if avg_second > avg_first else "empeorando" if avg_second < avg_first else "estable"
            else:
                tendencia = "sin datos suficientes"

            # Buscar material de estudio relevante (RAG)
            material = []
            try:
                if temas_criticos:
                    query = f"explicacion y ejercicios de {', '.join(t['topic'] for t in temas_criticos[:3])} en {sn}"
                else:
                    query = f"conceptos fundamentales y explicacion de {sn}"
                query_embedding = embedder.embed_query(query)
                search_results = vector_store.search(query_embedding, top_k=top_k)
                material = [
                    {
                        "texto": r["chunk_text"][:600],
                        "fuente": r["source_name"],
                        "pagina": r["page_number"],
                        "relevancia": round(r["score"], 3),
                    }
                    for r in search_results
                    if r["score"] > 0.2
                ]
            except Exception as e:
                logger.warning("Error buscando material para %s: %s", sn, e)

            materias_detalle.append({
                "source_name": sn,
                "promedio": round(subject["promedio"], 2),
                "evaluaciones": subject["evaluaciones"],
                "tendencia": tendencia,
                "temas_criticos": temas_criticos,
                "material_estudio": material,
            })

        # Tipos de evaluacion problematicos
        weak_types = [
            t for t in summary["por_tipo"]
            if t["promedio"] is not None and t["promedio"] < 7.0
        ]

        return {
            "student": {
                "id": student["id"],
                "name": student["name"],
                "group": student.get("group_name"),
            },
            "promedio_general": round(summary["promedio_general"], 2) if summary["promedio_general"] else None,
            "total_evaluaciones": summary["total_evaluaciones"],
            "materias_detalle": materias_detalle,
            "materias_fuertes": [
                {"source_name": s["source_name"], "promedio": round(s["promedio"], 2)}
                for s in strong_subjects
            ],
            "tipos_debiles": weak_types,
            "por_tipo": summary["por_tipo"],
        }
    finally:
        conn.close()


def get_performance_prediction(student_id: int) -> dict:
    student = get_student(student_id)
    if not student:
        return {"error": "Estudiante no encontrado"}

    conn = get_knowledge_db()
    try:
        rows = conn.execute(
            "SELECT * FROM grades WHERE student_id = ? ORDER BY created_at ASC",
            (student_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "student": {"id": student["id"], "name": student["name"], "group": student.get("group_name")},
            "riesgo_global": "sin datos",
            "predicciones_por_materia": [],
            "materias_criticas": [],
            "mensaje": "No hay calificaciones registradas para este estudiante.",
        }

    by_source = defaultdict(list)
    for row in rows:
        by_source[dict(row)["source_name"]].append(dict(row))

    predicciones = []
    materias_criticas = []

    for source_name, grades in by_source.items():
        values = [g["grade"] for g in grades]
        promedio = sum(values) / len(values)

        if len(values) >= 3:
            slope, intercept = _linear_regression(values)
            nota_predicha = slope * len(values) + intercept
            nota_predicha = max(0.0, min(10.0, nota_predicha))

            if slope > 0.1:
                tendencia = "mejorando"
            elif slope < -0.1:
                tendencia = "empeorando"
            else:
                tendencia = "estable"

            prob = min(1.0, max(0.0, (nota_predicha - 3.0) / 7.0))
        else:
            slope = 0.0
            nota_predicha = promedio
            tendencia = "sin datos suficientes"
            prob = min(1.0, max(0.0, (promedio - 3.0) / 7.0))

        predicciones.append({
            "source_name": source_name,
            "promedio_actual": round(promedio, 2),
            "tendencia": tendencia,
            "pendiente": round(slope, 3),
            "nota_predicha": round(nota_predicha, 2),
            "probabilidad_aprobar": round(prob, 2),
            "evaluaciones": len(values),
        })

        if promedio < 6.0 or (tendencia == "empeorando" and promedio < 7.0):
            materias_criticas.append(source_name)

    promedio_general = sum(p["promedio_actual"] for p in predicciones) / len(predicciones)
    if promedio_general >= 8.0 and not materias_criticas:
        riesgo = "bajo"
    elif promedio_general >= 7.0 and len(materias_criticas) <= 1:
        riesgo = "medio"
    elif promedio_general >= 5.0:
        riesgo = "alto"
    else:
        riesgo = "critico"

    partes = []
    mejorando = [p["source_name"] for p in predicciones if p["tendencia"] == "mejorando"]
    empeorando = [p["source_name"] for p in predicciones if p["tendencia"] == "empeorando"]
    if mejorando:
        partes.append(f"Tendencia positiva en {', '.join(mejorando)}")
    if empeorando:
        partes.append(f"{', '.join(empeorando)} requiere atencion urgente")
    if materias_criticas and not empeorando:
        partes.append(f"Materias criticas: {', '.join(materias_criticas)}")
    mensaje = ". ".join(partes) if partes else "Rendimiento estable."

    return {
        "student": {"id": student["id"], "name": student["name"], "group": student.get("group_name")},
        "riesgo_global": riesgo,
        "promedio_general": round(promedio_general, 2),
        "predicciones_por_materia": sorted(predicciones, key=lambda p: p["promedio_actual"]),
        "materias_criticas": materias_criticas,
        "mensaje": mensaje,
    }


def compare_groups(group_names: list[str]) -> dict:
    conn = get_knowledge_db()
    try:
        ranking = []
        for gn in group_names:
            row = conn.execute(
                """SELECT COUNT(DISTINCT g.student_id) as estudiantes,
                          COUNT(g.id) as evaluaciones,
                          AVG(g.grade) as promedio
                   FROM grades g JOIN students s ON s.id = g.student_id
                   WHERE s.group_name = ?""",
                (gn,),
            ).fetchone()
            ranking.append({
                "group_name": gn,
                "promedio": round(row["promedio"], 2) if row["promedio"] else 0.0,
                "estudiantes": row["estudiantes"],
                "evaluaciones": row["evaluaciones"],
            })

        ranking.sort(key=lambda r: r["promedio"], reverse=True)

        all_sources = conn.execute(
            """SELECT DISTINCT g.source_name
               FROM grades g JOIN students s ON s.id = g.student_id
               WHERE s.group_name IN ({})""".format(",".join("?" * len(group_names))),
            group_names,
        ).fetchall()

        por_materia = []
        for source_row in all_sources:
            sn = source_row["source_name"]
            materia_data = {"source_name": sn}
            promedios = {}
            for gn in group_names:
                row = conn.execute(
                    """SELECT AVG(g.grade) as promedio, COUNT(DISTINCT g.student_id) as estudiantes
                       FROM grades g JOIN students s ON s.id = g.student_id
                       WHERE s.group_name = ? AND g.source_name = ?""",
                    (gn, sn),
                ).fetchone()
                avg = round(row["promedio"], 2) if row["promedio"] else 0.0
                materia_data[gn] = {"promedio": avg, "estudiantes": row["estudiantes"]}
                promedios[gn] = avg

            if promedios:
                mejor = max(promedios, key=promedios.get)
                peor = min(promedios, key=promedios.get)
                materia_data["mejor_grupo"] = mejor
                materia_data["diferencia"] = round(promedios[mejor] - promedios[peor], 2)

            por_materia.append(materia_data)

        por_materia.sort(key=lambda m: m.get("diferencia", 0), reverse=True)

        if len(ranking) >= 2:
            mejor = ranking[0]
            wins = sum(1 for m in por_materia if m.get("mejor_grupo") == mejor["group_name"])
            total = len(por_materia)
            resumen = (
                f"{mejor['group_name']} lidera con promedio {mejor['promedio']} "
                f"y es mejor en {wins} de {total} materias."
            )
        else:
            resumen = "Se necesitan al menos 2 grupos para comparar."

        return {
            "grupos_comparados": group_names,
            "ranking": ranking,
            "por_materia": por_materia,
            "resumen": resumen,
        }
    finally:
        conn.close()


def get_global_dashboard() -> dict:
    conn = get_knowledge_db()
    try:
        total_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        total_grades = conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0]

        avg_row = conn.execute(
            "SELECT AVG(grade) as avg, MIN(grade) as min, MAX(grade) as max FROM grades"
        ).fetchone()

        rows = conn.execute(
            """SELECT source_name, AVG(grade) as promedio,
                      COUNT(DISTINCT student_id) as estudiantes, COUNT(*) as evaluaciones
               FROM grades GROUP BY source_name ORDER BY promedio ASC"""
        ).fetchall()
        by_source = [dict(r) for r in rows]

        rows = conn.execute(
            """SELECT s.id, s.name, s.group_name, AVG(g.grade) as promedio,
                      COUNT(g.id) as evaluaciones
               FROM grades g JOIN students s ON s.id = g.student_id
               GROUP BY s.id HAVING promedio < 6.0
               ORDER BY promedio ASC LIMIT 20"""
        ).fetchall()
        at_risk = [dict(r) for r in rows]

        distribution = {}
        for label, low, high in [("reprobado", 0, 5.9), ("suficiente", 6, 6.9),
                                  ("bien", 7, 7.9), ("notable", 8, 8.9), ("sobresaliente", 9, 10)]:
            count = conn.execute(
                "SELECT COUNT(*) FROM grades WHERE grade >= ? AND grade <= ?", (low, high)
            ).fetchone()[0]
            distribution[label] = count

        return {
            "total_estudiantes": total_students,
            "total_evaluaciones": total_grades,
            "promedio_general": round(avg_row["avg"], 2) if avg_row["avg"] else None,
            "nota_minima": avg_row["min"],
            "nota_maxima": avg_row["max"],
            "distribucion": distribution,
            "rendimiento_por_materia": by_source,
            "estudiantes_en_riesgo": at_risk,
        }
    finally:
        conn.close()
