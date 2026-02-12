import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.models import ChatRequest, ChatResponse, SourceRef
from app.security import verify_api_key, check_rate_limit
from app.services import rag_engine

router = APIRouter(tags=["Chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    _auth=Depends(verify_api_key),
    _rate=Depends(check_rate_limit),
):
    """
    Envia una pregunta y recibe la respuesta completa en JSON.

    Retorna la respuesta del LLM basada en la base de conocimiento,
    junto con las fuentes utilizadas y metricas.
    """
    sources = []
    answer_parts = []
    conversation_id = ""
    tokens_in = 0
    tokens_out = 0
    latency_ms = 0

    async for event in rag_engine.query(
        message=request.message,
        conversation_id=request.conversation_id,
        top_k=request.top_k,
    ):
        event_type = event.get("type")

        if event_type == "sources":
            conversation_id = event.get("conversation_id", "")
            sources = [
                SourceRef(
                    source_name=s["source_name"],
                    chunk_text=s["chunk_text"],
                    page_number=s.get("page_number"),
                    section=s.get("section"),
                    score=s.get("score", 0.0),
                )
                for s in event.get("sources", [])
            ]

        elif event_type == "token":
            answer_parts.append(event.get("content", ""))

        elif event_type == "done":
            tokens_in = event.get("tokens_in", 0)
            tokens_out = event.get("tokens_out", 0)
            latency_ms = event.get("latency_ms", 0)
            conversation_id = event.get("conversation_id", conversation_id)

        elif event_type == "error":
            return ChatResponse(
                answer=event.get("error", "Error procesando la consulta"),
                sources=[],
                conversation_id=conversation_id,
            )

    return ChatResponse(
        answer="".join(answer_parts),
        sources=sources,
        conversation_id=conversation_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
    )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    _auth=Depends(verify_api_key),
    _rate=Depends(check_rate_limit),
):
    """
    Envia una pregunta y recibe la respuesta en streaming (SSE).

    El stream retorna eventos JSON line-delimited:
    - {"type": "sources", "sources": [...], "conversation_id": "..."}
    - {"type": "token", "content": "..."}
    - {"type": "done", "conversation_id": "...", "tokens_in": N, "tokens_out": N, "latency_ms": N}
    - {"type": "error", "error": "..."}
    """

    async def event_stream():
        async for event in rag_engine.query(
            message=request.message,
            conversation_id=request.conversation_id,
            top_k=request.top_k,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
