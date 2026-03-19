# Panel del Profesor - SisacademiChat

## Vision General

El **Panel del Profesor** convierte a SisacademiChat en una herramienta de analitica academica completa que funciona **100% offline**. El profesor tiene acceso a estadisticas, calificaciones, predicciones, ejercicios personalizados y planes de mejora generados con inteligencia artificial — sin necesidad de conexion a internet.

### Como funciona

```
                    CON INTERNET                          SIN INTERNET
              ________________________          ________________________________
             |                        |        |                                |
  Sistema    |   POST /sync/knowledge |        |  GET /professor/dashboard      |
  Academico --> SisacademiServer      |        |  GET /professor/analytics/...  |
  (notas,   |   (procesa todo)       |        |  GET /professor/prediction/... |
  students) |        |               |        |  GET /professor/improvement/...|
             |        v               |        |  GET /professor/exercises/...  |
             |   knowledge.db ------->|------->|                                |
             |   (descarga al chat)   |        |  SisacademiChat lee la BD      |
             |________________________|        |  + genera texto con IA (Ollama)|
                                               |________________________________|
```

1. El **sistema academico externo** envia notas y estudiantes al servidor central
2. El servidor **procesa y almacena** todo en `knowledge.db`
3. SisacademiChat **descarga** esa BD cuando hay internet (`POST /api/v1/sync/knowledge`)
4. Los endpoints del profesor **leen directamente** de la BD local — sin procesar nada
5. Los endpoints con IA **generan texto personalizado** usando el modelo local (Ollama)

---

## Endpoints Disponibles

**URL base:** `http://localhost:8090/api/v1`

Todos los endpoints son **GET** (solo lectura) y no requieren conexion a internet.
Los endpoints marcados con **(IA)** generan texto adicional con Ollama si esta activo.

| # | Endpoint | Descripcion |
|---|----------|-------------|
| 1 | `GET /professor/dashboard` | Dashboard global con resumen narrativo **(IA)** |
| 2 | `GET /professor/grades/student/{id}` | Calificaciones de un estudiante |
| 3 | `GET /professor/analytics/student/{id}` | Resumen academico completo |
| 4 | `GET /professor/analytics/source/{name}` | Estadisticas de una materia |
| 5 | `GET /professor/analytics/group/{name}` | Estadisticas de un grupo |
| 6 | `GET /professor/analytics/groups/compare` | Comparar grupos con analisis **(IA)** |
| 7 | `GET /professor/student/{id}/improvement-plan` | Plan de mejora completo **(IA)** |
| 8 | `GET /professor/student/{id}/prediction` | Prediccion de rendimiento |
| 9 | `GET /professor/student/{id}/practice-exercises` | Ejercicios de practica **(IA)** |

---

### 1. Dashboard Global (con Resumen Narrativo IA)

```
GET /professor/dashboard
```

Panel de control con la **radiografia completa** de todos los estudiantes. Incluye un **resumen narrativo** generado por IA que analiza la situacion y ofrece recomendaciones al profesor.

**Respuesta del sistema:**
```json
{
  "total_estudiantes": 120,
  "total_evaluaciones": 1450,
  "promedio_general": 7.24,
  "nota_minima": 2.0,
  "nota_maxima": 10.0,
  "distribucion": {
    "reprobado": 18,
    "suficiente": 25,
    "bien": 32,
    "notable": 30,
    "sobresaliente": 15
  },
  "rendimiento_por_materia": [
    {"source_name": "Matematicas", "promedio": 6.1, "estudiantes": 120, "evaluaciones": 360},
    {"source_name": "Quimica", "promedio": 6.8, "estudiantes": 120, "evaluaciones": 240},
    {"source_name": "Biologia", "promedio": 7.5, "estudiantes": 120, "evaluaciones": 360},
    {"source_name": "Historia", "promedio": 8.2, "estudiantes": 120, "evaluaciones": 480}
  ],
  "estudiantes_en_riesgo": [
    {"id": 45, "name": "Miguel Torres", "group_name": "3ro-B", "promedio": 3.8, "evaluaciones": 12},
    {"id": 23, "name": "Laura Diaz", "group_name": "3ro-A", "promedio": 4.5, "evaluaciones": 11},
    {"id": 78, "name": "Carlos Ruiz", "group_name": "3ro-C", "promedio": 4.9, "evaluaciones": 10}
  ],
  "generado_con_ia": true,
  "resumen_narrativo": "RESUMEN ACADEMICO - 17/02/2026\n\nSe registran 120 estudiantes con un total de 1,450 evaluaciones aplicadas. El promedio general institucional se ubica en 7.24, lo cual es aceptable pero con areas de atencion inmediata.\n\nSITUACION DE ALERTA: Se identifican 18 evaluaciones en rango reprobatorio (por debajo de 6.0), lo que representa un 1.2% del total. Sin embargo, se detectan 3 estudiantes en situacion critica: Miguel Torres (3ro-B) con promedio 3.8, Laura Diaz (3ro-A) con 4.5 y Carlos Ruiz (3ro-C) con 4.9. Estos casos requieren intervencion inmediata mediante tutorias personalizadas.\n\nMATERIA PRIORITARIA: Matematicas presenta el promedio mas bajo con 6.1, seguida de Quimica con 6.8. Se recomienda: (1) programar sesiones de refuerzo en Matematicas esta semana, (2) revisar la metodologia de evaluacion en Quimica, y (3) compartir las practicas exitosas de Historia (promedio 8.2) con los demas departamentos.\n\nACCIONES SUGERIDAS: Convocar a los profesores de Matematicas y Quimica para analizar estrategias. Citar a los padres de los 3 estudiantes en riesgo critico antes del viernes. Considerar asignar material de repaso personalizado a traves del chatbot."
}
```

**Ejemplo real:**
> La profesora Maria abre la app el lunes por la manana. El dashboard le muestra los numeros clave pero ademas el **resumen narrativo** le dice exactamente que hacer:
>
> *"Se identifican 3 estudiantes en situacion critica... Matematicas presenta el promedio mas bajo con 6.1... Se recomienda programar sesiones de refuerzo esta semana..."*
>
> En lugar de analizar tabla por tabla, Maria tiene un diagnostico listo para actuar. Programa la tutoria para el miercoles y cita a los padres de Miguel Torres para el jueves.
>
> **Si Ollama no esta activo:** Se retorna toda la informacion estructurada con `generado_con_ia: false` y `resumen_narrativo: null`. Los datos son exactamente los mismos, solo falta el texto narrativo.

---

### 2. Calificaciones por Estudiante

```
GET /professor/grades/student/{student_id}
GET /professor/grades/student/{student_id}?source_name=Matematicas
```

Historial completo de calificaciones, con filtro opcional por materia.

**Respuesta del sistema:**
```json
{
  "student": {"id": 1, "name": "Ana Rodriguez", "group_name": "3ro-A"},
  "total": 4,
  "grades": [
    {
      "id": 10,
      "source_name": "Matematicas",
      "topic": "Ecuaciones cuadraticas",
      "grade": 8.5,
      "max_grade": 10.0,
      "evaluation_type": "quiz",
      "notes": null,
      "created_at": "2025-11-15"
    },
    {
      "id": 8,
      "source_name": "Matematicas",
      "topic": "Fracciones algebraicas",
      "grade": 6.5,
      "max_grade": 10.0,
      "evaluation_type": "examen",
      "notes": "Necesita refuerzo en denominadores",
      "created_at": "2025-10-20"
    },
    {
      "id": 5,
      "source_name": "Matematicas",
      "topic": "Algebra basica",
      "grade": 9.0,
      "max_grade": 10.0,
      "evaluation_type": "tarea",
      "notes": null,
      "created_at": "2025-10-05"
    },
    {
      "id": 2,
      "source_name": "Matematicas",
      "topic": "Numeros enteros",
      "grade": 7.0,
      "max_grade": 10.0,
      "evaluation_type": "examen",
      "notes": null,
      "created_at": "2025-09-15"
    }
  ]
}
```

**Ejemplo real:**
> La mama de Ana quiere saber como va su hija en Matematicas. El profesor filtra con `?source_name=Matematicas` y ve de inmediato:
>
> - **Quiz Ecuaciones**: 8.5 (bien)
> - **Examen Fracciones**: 6.5 (bajo, con nota "Necesita refuerzo en denominadores")
> - **Tarea Algebra**: 9.0 (excelente)
> - **Examen Numeros enteros**: 7.0 (regular)
>
> **Patron detectado:** En tareas y quizzes va bien (8.5-9.0) pero en examenes baja (6.5-7.0). Ana entiende la materia pero tiene dificultad con la presion de los examenes formales.
>
> **Recomendacion:** Practicar con simulacros de examen cronometrados para reducir la ansiedad.

---

### 3. Resumen Academico de un Estudiante

```
GET /professor/analytics/student/{student_id}
```

Analisis estadistico completo: promedios generales, desglose por materia y por tipo de evaluacion.

**Respuesta del sistema:**
```json
{
  "student": {"id": 15, "name": "Diego Herrera", "group_name": "3ro-A"},
  "total_evaluaciones": 18,
  "promedio_general": 7.2,
  "nota_minima": 4.0,
  "nota_maxima": 9.5,
  "porcentaje_promedio": 72.0,
  "por_materia": [
    {"source_name": "Matematicas", "promedio": 5.9, "evaluaciones": 6, "minima": 4.0, "maxima": 7.5},
    {"source_name": "Quimica", "promedio": 7.0, "evaluaciones": 4, "minima": 6.0, "maxima": 8.0},
    {"source_name": "Historia", "promedio": 8.8, "evaluaciones": 8, "minima": 7.5, "maxima": 9.5}
  ],
  "por_tipo": [
    {"evaluation_type": "examen", "promedio": 6.0, "cantidad": 8},
    {"evaluation_type": "tarea", "promedio": 8.1, "cantidad": 6},
    {"evaluation_type": "quiz", "promedio": 7.5, "cantidad": 4}
  ]
}
```

**Ejemplo real:**
> En la reunion de padres, el profesor muestra el resumen de Diego en su tablet:
>
> **Mejor materia:** Historia (8.8) — destaca significativamente, nunca baja de 7.5
> **Peor materia:** Matematicas (5.9) — por debajo del aprobatorio, con nota minima de 4.0
>
> **Patron por tipo de evaluacion:**
> - Tareas: 8.1 (excelente en trabajo practico)
> - Quizzes: 7.5 (bien en evaluaciones rapidas)
> - Examenes: 6.0 (cae en evaluaciones formales)
>
> **Conclusion:** Diego comprende los temas y rinde bien cuando trabaja en casa o en evaluaciones cortas, pero tiene dificultad en examenes largos. Se recomienda practicar con simulacros de examen y tecnicas de manejo del tiempo.

---

### 4. Estadisticas de una Materia

```
GET /professor/analytics/source/{source_name}
```

Analisis profundo de una materia completa: distribucion, estudiantes en riesgo y mejores estudiantes.

**Respuesta del sistema:**
```json
{
  "total_evaluaciones": 360,
  "total_estudiantes": 90,
  "promedio_general": 6.8,
  "nota_minima": 1.5,
  "nota_maxima": 10.0,
  "porcentaje_promedio": 68.0,
  "distribucion": [
    {"rango": "Reprobado (0-5.9)", "cantidad": 22},
    {"rango": "Suficiente (6-6.9)", "cantidad": 18},
    {"rango": "Bien (7-7.9)", "cantidad": 25},
    {"rango": "Notable (8-8.9)", "cantidad": 15},
    {"rango": "Sobresaliente (9-10)", "cantidad": 10}
  ],
  "estudiantes_en_riesgo": [
    {"student_id": 45, "name": "Miguel Torres", "group_name": "3ro-B", "promedio": 3.2, "evaluaciones": 4},
    {"student_id": 67, "name": "Rosa Jimenez", "group_name": "3ro-C", "promedio": 4.8, "evaluaciones": 4},
    {"student_id": 23, "name": "Laura Diaz", "group_name": "3ro-A", "promedio": 5.1, "evaluaciones": 4}
  ],
  "top_estudiantes": [
    {"student_id": 12, "name": "Sofia Lopez", "group_name": "3ro-A", "promedio": 9.8, "evaluaciones": 4},
    {"student_id": 3, "name": "Juan Ramirez", "group_name": "3ro-A", "promedio": 9.5, "evaluaciones": 4},
    {"student_id": 56, "name": "Maria Fernandez", "group_name": "3ro-B", "promedio": 9.2, "evaluaciones": 4}
  ]
}
```

**Ejemplo real:**
> El director solicita un reporte del estado de Matematicas para la junta. El profesor consulta este endpoint y obtiene todo lo que necesita:
>
> **Panorama general:** 90 estudiantes evaluados, promedio 6.8 — por debajo del objetivo institucional de 7.0
>
> **Distribucion preocupante:**
> - 22 estudiantes reprobando (24.4% del total)
> - Solo 10 sobresalientes (11.1%)
> - La mayor concentracion esta en "Bien" (25 alumnos) — hay potencial de mejora
>
> **Casos urgentes:** Miguel Torres con 3.2 de promedio — necesita atencion inmediata
> **Referentes positivos:** Sofia Lopez con 9.8 — puede funcionar como tutora par
>
> El profesor genera un grafico de barras con la distribucion para la presentacion y propone un programa de tutorias donde los sobresalientes apoyen a los que estan en riesgo.

---

### 5. Estadisticas de un Grupo

```
GET /professor/analytics/group/{group_name}
```

Rendimiento academico de un grupo completo: promedio, desglose por materia y ranking interno.

**Respuesta del sistema:**
```json
{
  "total_estudiantes": 30,
  "total_evaluaciones": 360,
  "promedio_general": 7.4,
  "nota_minima": 2.0,
  "nota_maxima": 10.0,
  "por_materia": [
    {"source_name": "Quimica", "promedio": 6.1, "estudiantes": 30},
    {"source_name": "Matematicas", "promedio": 7.2, "estudiantes": 30},
    {"source_name": "Biologia", "promedio": 7.8, "estudiantes": 30},
    {"source_name": "Historia", "promedio": 8.2, "estudiantes": 30}
  ],
  "ranking": [
    {"student_id": 12, "name": "Sofia Lopez", "promedio": 9.1, "evaluaciones": 12},
    {"student_id": 3, "name": "Juan Ramirez", "promedio": 8.7, "evaluaciones": 12},
    {"student_id": 28, "name": "Andrea Gomez", "promedio": 7.5, "evaluaciones": 12},
    {"student_id": 45, "name": "Miguel Torres", "promedio": 4.8, "evaluaciones": 12}
  ]
}
```

**Ejemplo real:**
> La coordinadora quiere un reporte del grupo "3ro-A" para la reunion con padres de familia:
>
> **Vision general:** 30 estudiantes, promedio 7.4 — buen rendimiento general
>
> **Por materia:**
> - Quimica (6.1) — la materia mas debil del grupo, necesita refuerzo
> - Matematicas (7.2) — aceptable pero mejorable
> - Biologia (7.8) — buen nivel
> - Historia (8.2) — la fortaleza del grupo
>
> **Ranking:**
> - 1er lugar: Sofia Lopez (9.1) — candidata a reconocimiento
> - Ultimo lugar: Miguel Torres (4.8) — requiere plan de mejora urgente
>
> La coordinadora decide asignar un profesor adjunto para Quimica en este grupo y programar tutoria para Miguel.

---

### 6. Comparar Grupos (con Analisis IA)

```
GET /professor/analytics/groups/compare?groups=3ro-A,3ro-B
GET /professor/analytics/groups/compare?groups=Matutino,Vespertino
GET /professor/analytics/groups/compare?groups=3ro-A,3ro-B,3ro-C
```

Compara rendimiento entre 2 o mas grupos lado a lado. Incluye un **analisis narrativo** generado por IA con patrones, causas posibles y recomendaciones.

**Respuesta del sistema:**
```json
{
  "grupos_comparados": ["3ro-A", "3ro-B"],
  "ranking": [
    {"group_name": "3ro-A", "promedio": 7.8, "estudiantes": 32, "evaluaciones": 384},
    {"group_name": "3ro-B", "promedio": 7.1, "estudiantes": 28, "evaluaciones": 336}
  ],
  "por_materia": [
    {
      "source_name": "Matematicas",
      "3ro-A": {"promedio": 7.5, "estudiantes": 32},
      "3ro-B": {"promedio": 6.3, "estudiantes": 28},
      "mejor_grupo": "3ro-A",
      "diferencia": 1.2
    },
    {
      "source_name": "Quimica",
      "3ro-A": {"promedio": 7.0, "estudiantes": 32},
      "3ro-B": {"promedio": 6.2, "estudiantes": 28},
      "mejor_grupo": "3ro-A",
      "diferencia": 0.8
    },
    {
      "source_name": "Historia",
      "3ro-A": {"promedio": 8.2, "estudiantes": 32},
      "3ro-B": {"promedio": 8.0, "estudiantes": 28},
      "mejor_grupo": "3ro-A",
      "diferencia": 0.2
    },
    {
      "source_name": "Educacion Fisica",
      "3ro-A": {"promedio": 8.0, "estudiantes": 32},
      "3ro-B": {"promedio": 8.5, "estudiantes": 28},
      "mejor_grupo": "3ro-B",
      "diferencia": 0.5
    }
  ],
  "resumen": "3ro-A lidera con promedio 7.8 y es mejor en 3 de 4 materias.",
  "generado_con_ia": true,
  "analisis_narrativo": "ANALISIS COMPARATIVO: 3ro-A vs 3ro-B\n\nVISION GENERAL\nEl grupo 3ro-A presenta un rendimiento superior con promedio general de 7.8 frente al 7.1 de 3ro-B, una diferencia de 0.7 puntos. 3ro-A cuenta con 32 estudiantes y 384 evaluaciones, mientras que 3ro-B tiene 28 estudiantes con 336 evaluaciones.\n\nDISPARIDADES SIGNIFICATIVAS\nLa brecha mas preocupante se encuentra en Matematicas, donde 3ro-A obtiene 7.5 frente al 6.3 de 3ro-B (diferencia de 1.2 puntos). Esta es una brecha considerable que sugiere diferencias metodologicas o de ritmo en la ensenanza. Quimica presenta una situacion similar con 0.8 puntos de diferencia.\n\nEn contraste, Historia muestra promedios practicamente iguales (8.2 vs 8.0), lo que indica que en esta materia ambos grupos reciben una ensenanza efectiva y comparable.\n\nFORTALEZAS POR GRUPO\n3ro-A destaca en las materias exactas (Matematicas 7.5, Quimica 7.0) y mantiene un rendimiento consistente. 3ro-B tiene su punto fuerte en Educacion Fisica (8.5 vs 8.0), superando a 3ro-A en esta area.\n\nRECOMENDACIONES\n1. Intercambio de practicas: El profesor de Matematicas de 3ro-A deberia compartir su metodologia con el de 3ro-B, especialmente en los temas donde se presenta la mayor brecha.\n2. Plan de nivelacion: Implementar sesiones de refuerzo en Matematicas para 3ro-B, posiblemente usando material del chatbot.\n3. Analisis profundo: Investigar si la diferencia en Quimica se relaciona con prerequisitos matematicos que 3ro-B no domina.\n4. Aprovechar la fortaleza de 3ro-B en Educacion Fisica para actividades interdisciplinarias que motiven al grupo."
}
```

**Ejemplo real:**
> El director prepara la junta de consejo tecnico y necesita comparar los dos grupos de tercer grado. El sistema no solo le da los numeros sino un **analisis completo**:
>
> El resumen rapido dice: *"3ro-A lidera con promedio 7.8 y es mejor en 3 de 4 materias"*
>
> Pero el analisis narrativo va mas alla:
> - Identifica que la **mayor brecha esta en Matematicas** (1.2 puntos)
> - Sugiere que puede haber **diferencias metodologicas** entre profesores
> - Nota que en **Historia ambos van parejo** (buena senal)
> - Recomienda **intercambio de practicas** entre profesores
> - Propone investigar si los problemas de Quimica en 3ro-B estan relacionados con falencias en Matematicas
>
> El director presenta estos datos en la junta con recomendaciones concretas ya formuladas por el sistema.
>
> **Si Ollama no esta activo:** Retorna los datos estructurados y el resumen estadistico, con `generado_con_ia: false` y `analisis_narrativo: null`.

---

### 7. Plan de Mejora Completo (Generado con IA)

```
GET /professor/student/{student_id}/improvement-plan
```

Genera un **plan de mejora academica completo y personalizado** usando inteligencia artificial.
El sistema analiza calificaciones, identifica temas criticos, busca material de estudio relevante en la base de conocimiento (RAG) y genera un documento profesional listo para **imprimir y entregar**.

**Respuesta del sistema:**
```json
{
  "student": {"id": 23, "name": "Andrea Gomez", "group": "3ro-B"},
  "promedio_general": 5.8,
  "total_evaluaciones": 15,
  "materias_debiles": [
    {"source_name": "Matematicas", "promedio": 4.5, "evaluaciones": 5, "tendencia": "empeorando"},
    {"source_name": "Quimica", "promedio": 5.2, "evaluaciones": 4, "tendencia": "mejorando"}
  ],
  "materias_fuertes": [
    {"source_name": "Historia", "promedio": 8.5},
    {"source_name": "Literatura", "promedio": 8.2}
  ],
  "materias_detalle": [
    {
      "source_name": "Matematicas",
      "promedio": 4.5,
      "evaluaciones": 5,
      "tendencia": "empeorando",
      "temas_criticos": [
        {"topic": "Ecuaciones cuadraticas", "grade": 3.0, "max_grade": 10.0, "evaluation_type": "examen", "created_at": "2025-11-10"},
        {"topic": "Fracciones algebraicas", "grade": 4.5, "max_grade": 10.0, "evaluation_type": "quiz", "created_at": "2025-10-25"}
      ],
      "material_estudio": [
        {
          "texto": "Para resolver ecuaciones cuadraticas se utiliza la formula general: x = (-b +/- sqrt(b^2 - 4ac)) / 2a. Ejemplo: resolver x^2 - 5x + 6 = 0. Identificamos a=1, b=-5, c=6...",
          "fuente": "Matematicas.pdf",
          "pagina": 23,
          "relevancia": 0.87
        },
        {
          "texto": "Las fracciones algebraicas se simplifican factorizando numerador y denominador. Ejemplo: (x^2 - 4)/(x + 2) = (x+2)(x-2)/(x+2) = x - 2...",
          "fuente": "Matematicas.pdf",
          "pagina": 31,
          "relevancia": 0.82
        }
      ]
    }
  ],
  "tipos_debiles": [
    {"evaluation_type": "examen", "promedio": 4.8, "cantidad": 6}
  ],
  "recomendaciones": [
    "Reforzar estudio en: Matematicas, Quimica. Estas son las materias con menor rendimiento.",
    "Mejorar preparacion para examenes. Considerar sesiones de repaso y simulacros."
  ],
  "generado_con_ia": true,
  "plan_imprimible": "PLAN DE MEJORA ACADEMICA\n========================\nEstudiante: Andrea Gomez\nGrupo: 3ro-B\nFecha: 17/02/2026\nPromedio General: 5.8\n\nDIAGNOSTICO GENERAL\nAndrea presenta un rendimiento por debajo del promedio esperado (5.8 sobre 10.0). Se identifican dos materias en situacion critica: Matematicas con promedio 4.5 en tendencia descendente, y Quimica con 5.2 pero en tendencia de mejora. Es importante intervenir de manera inmediata en Matematicas antes de que la brecha se amplíe.\n\nMATERIA: MATEMATICAS (Promedio: 4.5 - Tendencia: Empeorando)\nTemas a reforzar:\n  - Ecuaciones cuadraticas: nota 3.0/10.0 en examen (10/11/2025)\n  - Fracciones algebraicas: nota 4.5/10.0 en quiz (25/10/2025)\nMaterial de repaso:\n  - Matematicas.pdf, pagina 23: Formula general de ecuaciones cuadraticas con ejemplos resueltos\n  - Matematicas.pdf, pagina 31: Simplificacion de fracciones algebraicas por factorizacion\nPlan de accion:\n  - Semana 1-2: Repasar ecuaciones cuadraticas. Resolver los ejercicios de las paginas 24-27 del material.\n  - Semana 3-4: Practicar fracciones algebraicas con los problemas de las paginas 31-35.\n  - Semanal: Realizar un simulacro de examen (los examenes son su punto mas debil con promedio 4.8).\n  - Diario: Resolver minimo 5 ecuaciones como ejercicio de calentamiento.\n\nMATERIA: QUIMICA (Promedio: 5.2 - Tendencia: Mejorando)\nNota positiva: la tendencia es ascendente, lo que indica que el esfuerzo esta dando frutos.\nPlan de accion:\n  - Mantener el ritmo actual de estudio\n  - Reforzar los temas donde obtuvo notas mas bajas\n  - Continuar con las practicas que estan funcionando\n\nESTRATEGIA POR TIPO DE EVALUACION\nLos examenes formales son el punto mas debil de Andrea (promedio 4.8). Se recomienda:\n  - Realizar simulacros semanales con tiempo cronometrado\n  - Practicar tecnicas de manejo de ansiedad (respiracion, organizacion del tiempo)\n  - Revisar examenes anteriores para familiarizarse con el formato\n\nFORTALEZAS Y MOTIVACION\nAndrea destaca notablemente en Historia (8.5) y Literatura (8.2). Estas fortalezas demuestran que tiene la capacidad y la disciplina para alcanzar buenos resultados. El objetivo es trasladar esos habitos de estudio a las materias exactas.\n\nCOMPROMISOS\n1. Asistir a tutoria semanal de Matematicas (lunes y miercoles, 1 hora)\n2. Completar los ejercicios asignados del material antes de cada sesion\n3. Realizar un simulacro de examen cada viernes y revisar errores\n4. Dedicar 30 minutos diarios al repaso de los temas criticos\n5. Reunirse con el profesor cada dos semanas para revisar avances\n\n___________________________\nFirma del profesor\n\n___________________________\nFirma del estudiante/tutor\n\n___________________________\nFirma del padre de familia"
}
```

**Ejemplo real:**
> El tutor de Andrea genera el plan con un clic. El sistema:
> 1. **Detecta** que falla en Ecuaciones cuadraticas (3.0) y Fracciones algebraicas (4.5)
> 2. **Encuentra** en el PDF del profesor el material exacto: paginas 23 y 31 de Matematicas.pdf
> 3. **Genera** un plan completo con diagnostico, acciones semanales, material con paginas y compromisos
>
> El campo `plan_imprimible` contiene el documento completo. El tutor lo **imprime**, lo firma junto con Andrea y sus padres. Queda un compromiso formal con:
> - Diagnostico por materia con temas especificos
> - Material de repaso con paginas exactas del curso
> - Acciones concretas con plazos semanales
> - Estrategia para mejorar en examenes (su punto debil)
> - Compromisos firmables
>
> **Si Ollama no esta activo:** El endpoint retorna todos los datos estructurados (temas criticos, material de estudio, recomendaciones) con `generado_con_ia: false` y `plan_imprimible: null`. El profesor aun tiene la informacion para crear el plan manualmente.

---

### 8. Prediccion de Rendimiento

```
GET /professor/student/{student_id}/prediction
```

Predice el rendimiento futuro del estudiante usando **regresion lineal** sobre su historial de calificaciones.

**Respuesta del sistema:**
```json
{
  "student": {"id": 8, "name": "Luis Martinez", "group": "3ro-A"},
  "riesgo_global": "alto",
  "promedio_general": 6.3,
  "predicciones_por_materia": [
    {
      "source_name": "Fisica",
      "promedio_actual": 4.5,
      "tendencia": "empeorando",
      "pendiente": -0.4,
      "nota_predicha": 3.8,
      "probabilidad_aprobar": 0.35,
      "evaluaciones": 5
    },
    {
      "source_name": "Matematicas",
      "promedio_actual": 5.8,
      "tendencia": "mejorando",
      "pendiente": 0.3,
      "nota_predicha": 6.5,
      "probabilidad_aprobar": 0.72,
      "evaluaciones": 6
    },
    {
      "source_name": "Historia",
      "promedio_actual": 8.2,
      "tendencia": "estable",
      "pendiente": 0.05,
      "nota_predicha": 8.3,
      "probabilidad_aprobar": 0.95,
      "evaluaciones": 7
    }
  ],
  "materias_criticas": ["Fisica"],
  "mensaje": "Tendencia positiva en Matematicas. Fisica requiere atencion urgente."
}
```

**Ejemplo real:**
> El sistema analiza el historial de Luis y proyecta su rendimiento futuro:
>
> | Materia | Promedio Actual | Tendencia | Proxima Nota | Prob. Aprobar |
> |---------|----------------|-----------|-------------|---------------|
> | Fisica | 4.5 | Empeorando (-0.4/eval) | **3.8** | **35%** |
> | Matematicas | 5.8 | Mejorando (+0.3/eval) | 6.5 | 72% |
> | Historia | 8.2 | Estable | 8.3 | 95% |
>
> **Riesgo global: ALTO**
>
> El sistema le dice al profesor: *"Tendencia positiva en Matematicas. Fisica requiere atencion urgente."*
>
> **Interpretacion:** Si no se actua, la prediccion indica que Luis obtendra 3.8 en su proximo examen de Fisica (solo 35% de probabilidad de aprobar). En cambio, Matematicas va mejorando — si mantiene el ritmo llegara a 6.5.
>
> **Accion del profesor:** Programa tutoria extra de Fisica para Luis, asigna material de repaso a traves del chatbot, y notifica a los padres. Dos meses despues, la pendiente de Fisica cambia de -0.4 a +0.1 (estable) — la intervencion temprana funciono.

---

### 9. Ejercicios de Practica Personalizados (Generados con IA)

```
GET /professor/student/{student_id}/practice-exercises
```

Genera **ejercicios de practica personalizados** para las materias debiles del estudiante. El sistema busca contenido real del curso (RAG) y usa el LLM para crear ejercicios graduados con respuestas.

**Respuesta del sistema:**
```json
{
  "student": {"id": 23, "name": "Andrea Gomez", "group": "3ro-B"},
  "promedio_general": 5.8,
  "materias_detalle": [
    {
      "source_name": "Matematicas",
      "promedio": 4.5,
      "evaluaciones": 5,
      "tendencia": "empeorando",
      "temas_criticos": [
        {"topic": "Ecuaciones cuadraticas", "grade": 3.0, "max_grade": 10.0, "evaluation_type": "examen", "created_at": "2025-11-10"},
        {"topic": "Fracciones algebraicas", "grade": 4.5, "max_grade": 10.0, "evaluation_type": "quiz", "created_at": "2025-10-25"}
      ],
      "material_estudio": [
        {
          "texto": "Para resolver ecuaciones cuadraticas se utiliza la formula general: x = (-b +/- sqrt(b^2 - 4ac)) / 2a...",
          "fuente": "Matematicas.pdf",
          "pagina": 23,
          "relevancia": 0.87
        }
      ]
    }
  ],
  "generado_con_ia": true,
  "ejercicios_generados": "EJERCICIOS DE PRACTICA PERSONALIZADOS\nEstudiante: Andrea Gomez | Fecha: 17/02/2026\n\n---\nMATEMATICAS (Tu promedio actual: 4.5)\n---\n\nTEMA: Ecuaciones Cuadraticas (nota actual: 3.0)\nReferencia: Matematicas.pdf, pagina 23\n\nNivel Basico:\n1. Resuelve la ecuacion: x^2 - 9 = 0\n   Pista: Piensa en que numero multiplicado por si mismo da 9. Tambien puedes factorizarlo como diferencia de cuadrados: (x+3)(x-3) = 0\n   Respuesta: x = 3 y x = -3\n\n2. Resuelve: x^2 - 5x = 0\n   Pista: Saca factor comun x.\n   Respuesta: x(x - 5) = 0, entonces x = 0 y x = 5\n\nNivel Intermedio:\n3. Resuelve usando la formula general: x^2 - 5x + 6 = 0\n   Identifica: a = 1, b = -5, c = 6\n   Respuesta: x = [5 +/- sqrt(25-24)] / 2 = [5 +/- 1] / 2\n   x = 3 y x = 2\n\n4. Resuelve: 2x^2 + 3x - 2 = 0\n   Respuesta: Usando formula general con a=2, b=3, c=-2:\n   x = [-3 +/- sqrt(9+16)] / 4 = [-3 +/- 5] / 4\n   x = 1/2 y x = -2\n\nNivel Avanzado:\n5. Un rectangulo tiene un area de 24 cm^2. Si el largo es 2 cm mayor que el ancho, encuentra las dimensiones.\n   Planteamiento: x(x + 2) = 24 -> x^2 + 2x - 24 = 0\n   Respuesta: x = 4 (ancho = 4 cm, largo = 6 cm)\n\n---\n\nTEMA: Fracciones Algebraicas (nota actual: 4.5)\nReferencia: Matematicas.pdf, pagina 31\n\nNivel Basico:\n1. Simplifica: (6x) / (3x)\n   Pista: Divide numerador y denominador entre el factor comun.\n   Respuesta: 2\n\n2. Simplifica: (x^2 - 4) / (x + 2)\n   Pista: Factoriza el numerador como diferencia de cuadrados.\n   Respuesta: (x+2)(x-2) / (x+2) = x - 2\n\nNivel Intermedio:\n3. Simplifica: (x^2 - 9) / (x^2 - x - 6)\n   Respuesta: (x+3)(x-3) / (x-3)(x+2) = (x+3) / (x+2)\n\nNivel Avanzado:\n4. Suma las fracciones: 1/(x+1) + 1/(x-1)\n   Respuesta: [(x-1) + (x+1)] / [(x+1)(x-1)] = 2x / (x^2 - 1)\n\n---\n\nAUTOEVALUACION\n- Si resolviste todos los basicos correctamente: Vas por buen camino. Los conceptos fundamentales estan claros. Continua con los intermedios.\n- Si resolviste los intermedios: Excelente progreso. Ya manejas la formula general y la factorizacion. Intenta los avanzados.\n- Si resolviste los avanzados: Dominas el tema. Estas lista para el proximo examen. Practica con problemas de aplicacion similares al ejercicio 5.\n\nRecuerda: practica 5 ecuaciones diarias y revisa tus errores. La constancia es la clave."
}
```

**Ejemplo real:**
> El profesor de Andrea necesita darle tarea de repaso personalizada. En lugar de buscar ejercicios genericos en internet, genera ejercicios basados en el **material real del curso**:
>
> 1. El sistema detecta que Andrea falla en **Ecuaciones cuadraticas** (3.0) y **Fracciones algebraicas** (4.5)
> 2. Busca en Matematicas.pdf las paginas relevantes (23 y 31)
> 3. Genera **9 ejercicios graduados** (basico → intermedio → avanzado) basados en ese material
> 4. Incluye **pistas** en los basicos para que Andrea no se frustre
> 5. Incluye **respuestas** completas para autoevaluacion
> 6. Termina con una **guia de autoevaluacion** motivadora
>
> El profesor imprime el campo `ejercicios_generados` y se lo entrega a Andrea como tarea para la semana. Los ejercicios son progresivos: empiezan con `x^2 - 9 = 0` (basico) y terminan con problemas de aplicacion (avanzado).
>
> **Si Ollama no esta activo:** Retorna los datos estructurados (temas criticos + material encontrado) con `generado_con_ia: false` y `ejercicios_generados: null`. El profesor puede usar los temas criticos y las paginas del material para crear los ejercicios manualmente.

---

## Como se sincronizan los datos

```
POST /api/v1/sync/knowledge
```

Este endpoint descarga `knowledge.db` desde el servidor central. La BD incluye:

| Tabla | Contenido |
|-------|-----------|
| `chunks` | Fragmentos de texto de los documentos procesados |
| `vec_chunks` | Embeddings vectoriales (384 dimensiones) para busqueda semantica |
| `sources` | Fuentes/documentos procesados |
| `students` | Estudiantes sincronizados del sistema academico |
| `grades` | Calificaciones sincronizadas del sistema academico |

Usa **ETag** para descargas incrementales: si la BD no cambio, no se descarga de nuevo (HTTP 304).

---

## Requisitos Tecnicos

- **Sin dependencias externas** para analytics: toda la logica (regresion lineal, estadisticas) esta implementada en Python puro.
- **Sin conexion requerida** despues del sync: los endpoints `/professor/*` leen directamente de SQLite local.
- **Rendimiento:** las consultas SQL estan optimizadas con indices en `student_id`, `source_name`, `group_name` y `evaluation_type`.
- **Compatible** con la BD del servidor: usa el mismo esquema de tablas que SisacademiServer v1.5.0+.
- **IA local (Ollama):** los endpoints con IA usan el modelo configurado (qwen2.5:3b por defecto). Si Ollama no esta activo, retornan datos estructurados sin texto generado (`generado_con_ia: false`).

---

## Codigos de Error

| Codigo | Significado |
|--------|-------------|
| `200` | Exito |
| `400` | Parametros invalidos (ej: menos de 2 grupos para comparar) |
| `404` | Estudiante no encontrado o sin datos academicos |
| `503` | Datos academicos no disponibles — necesita sincronizar primero |

---

## Documentacion Interactiva

Toda esta informacion esta disponible de forma interactiva en:

```
http://localhost:8090/docs
```

Cada endpoint incluye descripciones detalladas, parametros documentados y ejemplos directamente en la interfaz Swagger UI.
