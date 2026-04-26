"""
Benchmark avanzado de SisacademiChat contra la base de conocimiento.

Ejecuta cada pregunta de `preguntas_bd_conocimiento.json` contra el endpoint
POST /api/v1/chat y registra metricas detalladas de calidad, rendimiento y
cobertura por fuente.

Salidas:
  - benchmark_full_raw.json      : datos crudos por pregunta
  - benchmark_full_report.md     : reporte legible en Markdown
  - benchmark_full_progress.log  : log en vivo del progreso

Uso:
    python benchmark_full_kb.py [--limit N] [--start N] [--top-k N]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------- Configuracion ----------------
BASE_URL = "http://127.0.0.1:8090/api/v1/chat"
HEALTH_URL = "http://127.0.0.1:8090/api/v1/health"
API_KEY = "uoemm2mEzkGwxVS_6T7WPvOdgwB5kyyHScOdssq-zfI"

INPUT_PATH = Path("preguntas_bd_conocimiento.json")
RAW_OUT = Path("benchmark_full_raw.json")
REPORT_OUT = Path("benchmark_full_report.md")
PROGRESS_LOG = Path("benchmark_full_progress.log")

REQUEST_TIMEOUT = 1800  # segundos (30 min por pregunta, rara vez se acerca)
DELAY_BETWEEN_REQUESTS_S = 2.1  # rate limit servidor: 30 req/min
TOP_K_DEFAULT = 5

# Frases que delatan que el chatbot no pudo responder
NO_ANSWER_PATTERNS = [
    r"no\s+(tengo|encontr[eé]|dispongo|se)\b",
    r"no\s+aparece\b",
    r"no\s+hay\s+informaci[oó]n",
    r"no\s+puedo\s+responder",
    r"no\s+se\s+encontr",
    r"informaci[oó]n\s+no\s+(disponible|suficiente)",
    r"documentos?\s+no\s+contienen",
    r"sin\s+informaci[oó]n\s+suficiente",
    r"lo\s+siento[,.]?\s+no",
]
NO_ANSWER_RE = re.compile("|".join(NO_ANSWER_PATTERNS), re.IGNORECASE)

# Indicadores heuristicos de respuesta "generica" o "hallucinated"
HEDGING_PATTERNS = [
    r"en\s+general\b",
    r"podr[ií]a\s+(ser|incluir)",
    r"tipicamente\b",
    r"normalmente\b",
]
HEDGING_RE = re.compile("|".join(HEDGING_PATTERNS), re.IGNORECASE)


# ---------------- Utilidades ----------------
def strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def tokenize(text: str) -> set[str]:
    cleaned = strip_accents(text).lower()
    return {t for t in re.findall(r"[a-z0-9]+", cleaned) if len(t) >= 4}


STOPWORDS = {
    "como", "cual", "cuales", "cuando", "donde", "porque", "para",
    "sobre", "entre", "desde", "hasta", "hacia", "sino", "pero",
    "mucho", "mucha", "muchos", "muchas", "unos", "unas", "otro",
    "otra", "otros", "otras", "este", "esta", "estos", "estas",
    "ese", "esa", "esos", "esas", "aquel", "aquella", "tanto",
    "tanta", "tantos", "tantas", "estar", "haber", "hacer", "tiene",
    "tienen", "puede", "pueden", "debe", "deben", "forma", "manera",
    "cosa", "cosas", "cada", "todos", "todas", "papel", "parte",
}


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with PROGRESS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def call_chat(message: str, top_k: int) -> tuple[int, dict[str, Any] | None, str | None, float]:
    """Llama al endpoint /chat y devuelve (status, body, error, elapsed_ms)."""
    payload = json.dumps({"message": message, "top_k": top_k}).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY,
        },
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            elapsed = (time.perf_counter() - start) * 1000
            return resp.status, json.loads(body), None, elapsed
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - start) * 1000
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, None, f"HTTPError {e.code}: {body[:200]}", elapsed
    except Exception as e:  # noqa: BLE001
        elapsed = (time.perf_counter() - start) * 1000
        return 0, None, f"{type(e).__name__}: {e}", elapsed


# ---------------- Analisis por respuesta ----------------
def classify_grade(question: str, sources: list[dict[str, Any]]) -> str | None:
    """Intenta inferir el grado escolar a partir de pregunta y fuentes."""
    blob = strip_accents((question + " " + " ".join(s.get("source_name", "") for s in sources))).lower()
    match = re.search(r"grado\s*(\d{1,2})", blob)
    if match:
        return f"grado_{match.group(1)}"
    for g in range(6, 12):
        if re.search(rf"\b{g}\b", blob) and "grado" in blob:
            return f"grado_{g}"
    return None


def analyze_response(question: str, response: dict[str, Any] | None, client_ms: float) -> dict[str, Any]:
    if response is None:
        return {
            "ok": False,
            "answer": "",
            "answer_words": 0,
            "answer_chars": 0,
            "sources_count": 0,
            "unique_sources": 0,
            "top_source": None,
            "top_score": 0.0,
            "avg_score": 0.0,
            "min_score": 0.0,
            "max_score": 0.0,
            "no_answer_pattern": False,
            "hedging": False,
            "question_coverage": 0.0,
            "source_query_overlap": 0.0,
            "accuracy_heuristic": 0.0,
            "tokens_in": 0,
            "tokens_out": 0,
            "server_latency_ms": 0,
            "client_latency_ms": round(client_ms, 2),
            "tokens_per_sec": 0.0,
            "grade_detected": None,
            "sources_preview": [],
        }

    answer = (response.get("answer") or "").strip()
    sources = response.get("sources") or []
    server_latency = int(response.get("latency_ms", 0))
    tokens_in = int(response.get("tokens_in", 0))
    tokens_out = int(response.get("tokens_out", 0))

    scores = [float(s.get("score", 0.0)) for s in sources]
    unique_names = {s.get("source_name", "") for s in sources if s.get("source_name")}

    # Cobertura: cuantas palabras clave de la pregunta aparecen en la respuesta
    q_tokens = {t for t in tokenize(question) if t not in STOPWORDS}
    a_tokens = tokenize(answer)
    coverage = (len(q_tokens & a_tokens) / len(q_tokens)) if q_tokens else 0.0

    # Overlap de pregunta con los textos de las fuentes (indicador de buen retrieval)
    src_blob = " ".join(s.get("chunk_text", "") for s in sources)
    s_tokens = tokenize(src_blob)
    src_overlap = (len(q_tokens & s_tokens) / len(q_tokens)) if q_tokens else 0.0

    no_answer = bool(NO_ANSWER_RE.search(answer))
    hedging = bool(HEDGING_RE.search(answer))

    # Heuristica compuesta de "exactitud"
    #   40% top_score normalizado (clip 0..1)
    #   20% overlap fuentes-pregunta
    #   15% cobertura respuesta-pregunta
    #   15% longitud razonable (40-400 palabras ideal)
    #   10% penalizacion por no_answer
    top_score = max(scores) if scores else 0.0
    score_norm = max(0.0, min(1.0, top_score))
    words = len(answer.split())
    length_score = 0.0
    if 40 <= words <= 400:
        length_score = 1.0
    elif 20 <= words < 40 or 400 < words <= 600:
        length_score = 0.6
    elif words > 0:
        length_score = 0.3

    accuracy = (
        0.40 * score_norm
        + 0.20 * src_overlap
        + 0.15 * coverage
        + 0.15 * length_score
        + 0.10 * (0.0 if no_answer else 1.0)
    )
    accuracy = round(accuracy, 4)

    tps = (tokens_out / (server_latency / 1000.0)) if server_latency > 0 else 0.0

    preview = [
        {
            "source_name": s.get("source_name"),
            "page_number": s.get("page_number"),
            "section": s.get("section"),
            "score": round(float(s.get("score", 0.0)), 3),
            "chunk_excerpt": (s.get("chunk_text", "") or "")[:180],
        }
        for s in sources[:3]
    ]

    return {
        "ok": True,
        "answer": answer,
        "answer_words": words,
        "answer_chars": len(answer),
        "sources_count": len(sources),
        "unique_sources": len(unique_names),
        "top_source": next((s.get("source_name") for s in sources), None),
        "top_score": round(top_score, 4),
        "avg_score": round(statistics.mean(scores), 4) if scores else 0.0,
        "min_score": round(min(scores), 4) if scores else 0.0,
        "max_score": round(max(scores), 4) if scores else 0.0,
        "no_answer_pattern": no_answer,
        "hedging": hedging,
        "question_coverage": round(coverage, 4),
        "source_query_overlap": round(src_overlap, 4),
        "accuracy_heuristic": accuracy,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "server_latency_ms": server_latency,
        "client_latency_ms": round(client_ms, 2),
        "tokens_per_sec": round(tps, 2),
        "grade_detected": classify_grade(question, sources),
        "sources_preview": preview,
    }


# ---------------- Reporte Markdown ----------------
def pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "0.0%"


def fmt_ms(ms: float) -> str:
    if ms >= 60_000:
        return f"{ms/1000:.1f}s ({ms/60_000:.1f}m)"
    return f"{ms/1000:.1f}s"


def quantile(data: list[float], q: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def write_report(meta: dict[str, Any], results: list[dict[str, Any]]) -> None:
    total = len(results)
    successes = [r for r in results if r["analysis"]["ok"]]
    failures = [r for r in results if not r["analysis"]["ok"]]

    client_ms = [r["analysis"]["client_latency_ms"] for r in successes]
    server_ms = [r["analysis"]["server_latency_ms"] for r in successes if r["analysis"]["server_latency_ms"] > 0]
    acc = [r["analysis"]["accuracy_heuristic"] for r in successes]
    tps = [r["analysis"]["tokens_per_sec"] for r in successes if r["analysis"]["tokens_per_sec"] > 0]
    tok_in = [r["analysis"]["tokens_in"] for r in successes]
    tok_out = [r["analysis"]["tokens_out"] for r in successes]
    no_answer = [r for r in successes if r["analysis"]["no_answer_pattern"]]
    hedging = [r for r in successes if r["analysis"]["hedging"]]

    # Clasificacion por tier
    high = [r for r in successes if r["analysis"]["accuracy_heuristic"] >= 0.65]
    mid = [r for r in successes if 0.40 <= r["analysis"]["accuracy_heuristic"] < 0.65]
    low = [r for r in successes if r["analysis"]["accuracy_heuristic"] < 0.40]

    # Top/worst
    by_acc_desc = sorted(successes, key=lambda r: r["analysis"]["accuracy_heuristic"], reverse=True)
    by_acc_asc = sorted(successes, key=lambda r: r["analysis"]["accuracy_heuristic"])
    slowest = sorted(successes, key=lambda r: r["analysis"]["client_latency_ms"], reverse=True)[:5]
    fastest = sorted(successes, key=lambda r: r["analysis"]["client_latency_ms"])[:5]

    # Cobertura por fuente
    source_counter: dict[str, int] = {}
    for r in successes:
        for s in r["analysis"]["sources_preview"]:
            name = s.get("source_name") or "unknown"
            source_counter[name] = source_counter.get(name, 0) + 1
    top_sources = sorted(source_counter.items(), key=lambda kv: kv[1], reverse=True)[:15]

    # Distribucion por grado detectado
    grade_counter: dict[str, int] = {}
    for r in successes:
        g = r["analysis"]["grade_detected"] or "no_detectado"
        grade_counter[g] = grade_counter.get(g, 0) + 1

    lines: list[str] = []
    lines.append("# Benchmark SisacademiChat - Base de Conocimiento\n")
    lines.append(f"**Generado:** {meta['generated_at']}  ")
    lines.append(f"**Preguntas totales:** {total}  ")
    lines.append(f"**Base URL:** {meta['base_url']}  ")
    lines.append(f"**Modelo Ollama:** {meta.get('ollama_model', 'desconocido')}  ")
    lines.append(f"**Chunks indexados:** {meta.get('knowledge_chunks', 'n/a')}  ")
    lines.append(f"**Fuentes indexadas:** {meta.get('knowledge_sources', 'n/a')}  ")
    lines.append(f"**top_k:** {meta.get('top_k', TOP_K_DEFAULT)}  ")
    lines.append(f"**Tiempo total benchmark:** {fmt_ms(meta['total_elapsed_ms'])}\n")

    lines.append("## Resumen ejecutivo\n")
    lines.append(f"- **Exitos:** {len(successes)}/{total} ({pct(len(successes), total)})")
    lines.append(f"- **Fallos (HTTP / excepciones):** {len(failures)}")
    lines.append(f"- **Respuestas 'no se' detectadas:** {len(no_answer)} ({pct(len(no_answer), len(successes))})")
    lines.append(f"- **Respuestas con hedging:** {len(hedging)} ({pct(len(hedging), len(successes))})")
    lines.append("")
    lines.append("**Exactitud heuristica (0..1):**")
    if acc:
        lines.append(f"- media: {statistics.mean(acc):.3f} | mediana: {statistics.median(acc):.3f} | min: {min(acc):.3f} | max: {max(acc):.3f}")
    lines.append(f"- Alta (>=0.65): {len(high)} ({pct(len(high), total)})")
    lines.append(f"- Media (0.40-0.65): {len(mid)} ({pct(len(mid), total)})")
    lines.append(f"- Baja (<0.40): {len(low)} ({pct(len(low), total)})")
    lines.append("")
    lines.append("**Latencia cliente:**")
    if client_ms:
        lines.append(f"- media: {fmt_ms(statistics.mean(client_ms))} | mediana: {fmt_ms(statistics.median(client_ms))}")
        lines.append(f"- p90: {fmt_ms(quantile(client_ms, 0.9))} | p95: {fmt_ms(quantile(client_ms, 0.95))} | p99: {fmt_ms(quantile(client_ms, 0.99))}")
        lines.append(f"- min: {fmt_ms(min(client_ms))} | max: {fmt_ms(max(client_ms))}")
    lines.append("")
    lines.append("**Tokens:**")
    if tok_in:
        lines.append(f"- promedio entrada: {statistics.mean(tok_in):.0f} | salida: {statistics.mean(tok_out):.0f}")
        lines.append(f"- total entrada: {sum(tok_in)} | salida: {sum(tok_out)}")
    if tps:
        lines.append(f"- tokens/seg (salida): media {statistics.mean(tps):.2f} | mediana {statistics.median(tps):.2f} | max {max(tps):.2f}")
    lines.append("")

    lines.append("## Distribucion por grado escolar detectado\n")
    lines.append("| Grado | Preguntas | % |")
    lines.append("|---|---|---|")
    for g, n in sorted(grade_counter.items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"| {g} | {n} | {pct(n, total)} |")
    lines.append("")

    lines.append("## Top 15 fuentes recuperadas\n")
    lines.append("| # | Fuente | Apariciones |")
    lines.append("|---|---|---|")
    for i, (name, n) in enumerate(top_sources, 1):
        lines.append(f"| {i} | {name} | {n} |")
    lines.append("")

    lines.append("## Top 10 mejores respuestas (por exactitud heuristica)\n")
    lines.append("| # | Q# | Exactitud | top_score | Latencia | Pregunta |")
    lines.append("|---|---|---|---|---|---|")
    for r in by_acc_desc[:10]:
        a = r["analysis"]
        lines.append(f"| {r['index']} | Q{r['index']} | {a['accuracy_heuristic']:.3f} | {a['top_score']:.3f} | {fmt_ms(a['client_latency_ms'])} | {r['question'][:90]} |")
    lines.append("")

    lines.append("## Top 10 peores respuestas (por exactitud heuristica)\n")
    lines.append("| # | Q# | Exactitud | top_score | no_answer | Pregunta |")
    lines.append("|---|---|---|---|---|---|")
    for r in by_acc_asc[:10]:
        a = r["analysis"]
        lines.append(f"| {r['index']} | Q{r['index']} | {a['accuracy_heuristic']:.3f} | {a['top_score']:.3f} | {'si' if a['no_answer_pattern'] else 'no'} | {r['question'][:90]} |")
    lines.append("")

    lines.append("## Preguntas mas lentas\n")
    lines.append("| # | Latencia | Tokens out | Pregunta |")
    lines.append("|---|---|---|---|")
    for r in slowest:
        a = r["analysis"]
        lines.append(f"| Q{r['index']} | {fmt_ms(a['client_latency_ms'])} | {a['tokens_out']} | {r['question'][:90]} |")
    lines.append("")

    lines.append("## Preguntas mas rapidas\n")
    lines.append("| # | Latencia | Tokens out | Pregunta |")
    lines.append("|---|---|---|---|")
    for r in fastest:
        a = r["analysis"]
        lines.append(f"| Q{r['index']} | {fmt_ms(a['client_latency_ms'])} | {a['tokens_out']} | {r['question'][:90]} |")
    lines.append("")

    if failures:
        lines.append("## Fallos\n")
        lines.append("| Q# | Error | Pregunta |")
        lines.append("|---|---|---|")
        for r in failures:
            lines.append(f"| Q{r['index']} | {r.get('error', '')[:80]} | {r['question'][:80]} |")
        lines.append("")

    lines.append("## Detalle por pregunta\n")
    for r in results:
        a = r["analysis"]
        lines.append(f"### Q{r['index']}. {r['question']}\n")
        if not a["ok"]:
            lines.append(f"- **Estado:** FALLO ({r.get('error', '')})")
            lines.append("")
            continue
        lines.append(f"- **HTTP:** {r['http_status']} | **Exactitud:** {a['accuracy_heuristic']:.3f} | **top_score:** {a['top_score']:.3f}")
        lines.append(f"- **Latencia cliente:** {fmt_ms(a['client_latency_ms'])} | **servidor:** {fmt_ms(a['server_latency_ms'])}")
        lines.append(f"- **Tokens:** in={a['tokens_in']} out={a['tokens_out']} ({a['tokens_per_sec']:.1f} tok/s)")
        lines.append(f"- **Fuentes:** {a['sources_count']} ({a['unique_sources']} unicas) | **avg_score:** {a['avg_score']:.3f}")
        lines.append(f"- **Cobertura pregunta->respuesta:** {a['question_coverage']*100:.0f}% | **pregunta->fuentes:** {a['source_query_overlap']*100:.0f}%")
        lines.append(f"- **No-answer detectado:** {'si' if a['no_answer_pattern'] else 'no'} | **Hedging:** {'si' if a['hedging'] else 'no'}")
        if a["sources_preview"]:
            lines.append("- **Top fuentes:**")
            for s in a["sources_preview"]:
                page = f" p.{s['page_number']}" if s.get("page_number") else ""
                lines.append(f"  - `{s['source_name']}`{page} [{s['score']}] - {s['chunk_excerpt']}...")
        lines.append("")
        lines.append("**Respuesta del chatbot:**\n")
        lines.append("> " + a["answer"].replace("\n", "\n> "))
        lines.append("")

    REPORT_OUT.write_text("\n".join(lines), encoding="utf-8")
    log(f"Reporte escrito: {REPORT_OUT}")


# ---------------- Main ----------------
def fetch_health() -> dict[str, Any]:
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"X-API-Key": API_KEY})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="limitar a N preguntas (0 = todas)")
    parser.add_argument("--start", type=int, default=0, help="empezar desde indice N (0-based)")
    parser.add_argument("--top-k", type=int, default=TOP_K_DEFAULT)
    parser.add_argument("--delay", type=float, default=DELAY_BETWEEN_REQUESTS_S)
    args = parser.parse_args()

    if PROGRESS_LOG.exists():
        PROGRESS_LOG.unlink()

    log("=" * 60)
    log("Benchmark SisacademiChat - iniciando")
    log("=" * 60)

    if not INPUT_PATH.exists():
        log(f"ERROR: no existe {INPUT_PATH}")
        return 1

    questions: list[str] = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    if args.start:
        questions = questions[args.start:]
    if args.limit:
        questions = questions[: args.limit]
    log(f"Preguntas a ejecutar: {len(questions)}")

    health = fetch_health()
    log(f"Servidor: {health.get('status', '?')} | modelo: {health.get('ollama_model')}")
    log(f"Base de conocimiento: {health.get('knowledge_chunks')} chunks / {health.get('knowledge_sources')} fuentes")

    benchmark_started = time.perf_counter()
    results: list[dict[str, Any]] = []

    for i, question in enumerate(questions, start=1 + args.start):
        log(f"[{i}/{args.start + len(questions)}] enviando: {question[:80]}")
        status, body, err, elapsed = call_chat(question, args.top_k)
        analysis = analyze_response(question, body, elapsed)
        rec = {
            "index": i,
            "question": question,
            "http_status": status,
            "error": err,
            "analysis": analysis,
            "raw_response": body,
        }
        results.append(rec)

        if analysis["ok"]:
            log(
                f"  ok {fmt_ms(elapsed)} | acc={analysis['accuracy_heuristic']:.3f} "
                f"top={analysis['top_score']:.3f} src={analysis['sources_count']} "
                f"tok_out={analysis['tokens_out']}"
            )
        else:
            log(f"  FALLO {fmt_ms(elapsed)} | {err}")

        # Guardado incremental para no perder progreso si se interrumpe
        RAW_OUT.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "base_url": BASE_URL,
                    "top_k": args.top_k,
                    "health": health,
                    "in_progress": i < args.start + len(questions),
                    "completed": i,
                    "total": args.start + len(questions),
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if i < args.start + len(questions):
            time.sleep(args.delay)

    total_ms = (time.perf_counter() - benchmark_started) * 1000
    log(f"Benchmark completo en {fmt_ms(total_ms)}")

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": BASE_URL,
        "top_k": args.top_k,
        "total_elapsed_ms": total_ms,
        "ollama_model": health.get("ollama_model"),
        "knowledge_chunks": health.get("knowledge_chunks"),
        "knowledge_sources": health.get("knowledge_sources"),
    }

    # Grabar raw final con completed=total y sin in_progress
    RAW_OUT.write_text(
        json.dumps(
            {
                **meta,
                "in_progress": False,
                "completed": len(results),
                "total": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log(f"Raw escrito: {RAW_OUT}")

    write_report(meta, results)
    log("Listo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
