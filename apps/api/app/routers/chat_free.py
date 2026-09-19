"""Chat livre do AI Hub — conversa comum com o modelo escolhido, sem tools.

Regra central: o endpoint de mensagens chama o modelo SEM enviar o campo
`tools`. É isso que garante que o chat livre nunca escreve no sistema — não
cria, edita nem lê planos, tasks, ADRs ou Knowledge. As tabelas próprias
(`chat_conversations`, `chat_free_messages`) também não têm FK para nenhuma
tabela do sistema.

Reaproveita os providers já cadastrados no AI Hub (OpenRouter, Ollama Cloud,
llama.cpp local via runtime_id), todos OpenAI-compatíveis. Resposta em SSE.
O modelo pode ser trocado no meio da conversa; cada mensagem registra qual
modelo a respondeu.
"""
import json
import os
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.chat_free import ChatConversation, ChatFreeMessage
from app.services import agent_runtimes, ai_cost_guard
from app.routers.ai import COMPAT_PROVIDERS

router = APIRouter()

# Contexto efetivo do modelo local (llama.cpp workdev-qwen27b roda com 16k).
# Usado para o aviso de ~80% e para o truncamento do histórico antigo.
LOCAL_FALLBACK_CONTEXT = int(os.getenv("CHAT_LIVRE_LOCAL_CONTEXT", "16384"))
CONTEXT_WARN_RATIO = 0.8
# Reserva de saída dentro da janela: o histórico truncado precisa deixar
# espaço para a resposta do modelo.
OUTPUT_RESERVE_TOKENS = 1024
SYSTEM_PROMPT = (
    "Você é um assistente de conversa livre dentro do WorkDev. Responda em "
    "português do Brasil. Você NÃO tem acesso aos dados do WorkDev "
    "(projetos, backlog, planos, ADRs): não invente números do sistema e "
    "deixe claro quando uma pergunta exigir consulta a eles."
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_conversation(db: Session, conversation_id: str) -> ChatConversation:
    try:
        conv_uuid = UUID(str(conversation_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    conv = db.query(ChatConversation).filter(
        ChatConversation.id == conv_uuid).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    return conv


def conversation_out(conv: ChatConversation) -> dict:
    return {
        "id": str(conv.id),
        "title": conv.title,
        "input_tokens": conv.input_tokens or 0,
        "output_tokens": conv.output_tokens or 0,
        "cost_usd": float(conv.cost_usd or 0),
        "created_at": str(conv.created_at),
        "updated_at": str(conv.updated_at),
    }


def message_out(msg: ChatFreeMessage) -> dict:
    return {
        "id": str(msg.id),
        "role": msg.role,
        "content": msg.content,
        "provider": msg.provider,
        "model": msg.model,
        "input_tokens": msg.input_tokens,
        "output_tokens": msg.output_tokens,
        "cost_usd": float(msg.cost_usd) if msg.cost_usd is not None else None,
        "created_at": str(msg.created_at),
    }


def estimate_tokens(messages: list[dict]) -> int:
    """Estimativa conservadora (~4 chars/token), mesma régua do AI Hub."""
    serialized = json.dumps(messages, ensure_ascii=False)
    return max(1, (len(serialized) + 3) // 4)


def truncate_history(messages: list[dict], context_limit: int) -> list[dict]:
    """Descarta as mensagens mais antigas até caber na janela do modelo.

    Em vez de estourar o contexto do modelo local, o histórico antigo sai e a
    conversa segue. A última mensagem do usuário nunca é descartada.
    """
    budget = context_limit - OUTPUT_RESERVE_TOKENS
    kept = list(messages)
    while len(kept) > 1 and estimate_tokens(kept) > budget:
        kept.pop(0)
    return kept


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class MessageSend(BaseModel):
    content: str = Field(min_length=1)
    provider: str
    model: str | None = None
    runtime_id: str | None = None


@router.get("/chat-livre/conversations")
def list_conversations(q: str | None = None, db: Session = Depends(get_db)):
    """Conversas mais recentes primeiro, com busca por título ou conteúdo."""
    query = db.query(ChatConversation)
    if q and q.strip():
        termo = f"%{q.strip()}%"
        matching = db.query(ChatFreeMessage.conversation_id).filter(
            ChatFreeMessage.content.ilike(termo)).subquery()
        query = query.filter(
            ChatConversation.title.ilike(termo)
            | ChatConversation.id.in_(matching)
        )
    convs = query.order_by(ChatConversation.updated_at.desc()).limit(100).all()
    return [conversation_out(c) for c in convs]


@router.post("/chat-livre/conversations", status_code=201)
def create_conversation(payload: ConversationCreate,
                        db: Session = Depends(get_db)):
    conv = ChatConversation(title=(payload.title or "Nova conversa")[:255])
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conversation_out(conv)


@router.get("/chat-livre/conversations/{conversation_id}")
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = _get_conversation(db, conversation_id)
    msgs = (db.query(ChatFreeMessage)
            .filter(ChatFreeMessage.conversation_id == conv.id)
            .order_by(ChatFreeMessage.created_at.asc())
            .all())
    return {**conversation_out(conv), "messages": [message_out(m) for m in msgs]}


@router.patch("/chat-livre/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, payload: ConversationRename,
                        db: Session = Depends(get_db)):
    conv = _get_conversation(db, conversation_id)
    conv.title = payload.title.strip()[:255]
    conv.title_locked = True
    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conv)
    return conversation_out(conv)


@router.delete("/chat-livre/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = _get_conversation(db, conversation_id)
    db.delete(conv)
    db.commit()
    return {"deleted": True, "id": str(conv.id)}


def _resolve_provider(req: MessageSend) -> tuple[str, str, str | None]:
    provider = (req.provider or "").lower()
    if req.runtime_id is not None:
        try:
            if provider != "ollama" or not req.model:
                raise ValueError("Selecione um modelo local válido")
            agent_runtimes.local_chat_runtime(req.runtime_id)
        except Exception:
            raise HTTPException(
                409,
                "Modelo ou runtime local indisponível. "
                "Atualize a seleção e tente novamente.",
            ) from None
        return provider, req.model, req.runtime_id
    if provider not in COMPAT_PROVIDERS:
        raise HTTPException(422, f"Provider não suportado no chat livre: {provider}")
    return provider, req.model or COMPAT_PROVIDERS[provider]["default_model"], None


def _endpoint_for(provider: str, runtime_id: str | None) -> tuple[str, str]:
    """URL do endpoint OpenAI-compatível e a api_key, sem logar segredos."""
    if runtime_id is not None:
        runtime = agent_runtimes.local_chat_runtime(runtime_id)
        base = agent_runtimes.base_url(runtime)
        return f"{base}/v1/chat/completions", agent_runtimes.api_key(runtime) or "ollama"
    cfg = COMPAT_PROVIDERS[provider]
    base = cfg["base_url"] or "https://api.openai.com/v1"
    return f"{base.rstrip('/')}/chat/completions", os.getenv(cfg["env_key"]) or ""


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _stream_chat(req: MessageSend, conv: ChatConversation,
                 history: list[dict], db: Session):
    # Qualquer falha aqui dentro vira `event: error` no SSE — propagar uma
    # exceção depois que a resposta streaming começou derruba a conexão com
    # "response already started" e o cliente não recebe nada legível.
    try:
        provider, model, runtime_id = _resolve_provider(req)
        url, api_key = _endpoint_for(provider, runtime_id)
    except HTTPException as exc:
        yield _sse("error", {"message": str(exc.detail)})
        return
    except Exception as exc:
        yield _sse("error", {"message": f"Falha ao preparar o provider: "
                                        f"{type(exc).__name__}"})
        return

    context_limit = None
    if runtime_id is not None:
        try:
            context_limit = agent_runtimes.local_chat_context(runtime_id, model)
        except Exception:
            context_limit = LOCAL_FALLBACK_CONTEXT

    outgoing = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    truncated = False
    if context_limit is not None:
        fitted = truncate_history(outgoing, context_limit)
        truncated = len(fitted) < len(outgoing)
        outgoing = fitted

    # REGRA CENTRAL DO CHAT LIVRE: a requisição ao modelo NÃO inclui o campo
    # `tools`. Sem tools expostas, o modelo não tem como escrever no sistema.
    payload = {
        "model": model,
        "messages": outgoing,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    yield _sse("start", {"provider": provider, "model": model,
                         "truncated": truncated,
                         "context_limit": context_limit})

    content_parts: list[str] = []
    input_tokens = output_tokens = None
    cost = None
    usage_cost = None

    try:
        with httpx.stream(
            "POST", url, json=payload, headers=headers,
            timeout=float(os.getenv("CHAT_LIVRE_TIMEOUT", "900")),
        ) as resp:
            if resp.status_code != 200:
                resp.read()
                yield _sse("error", {
                    "message": f"Provider respondeu HTTP {resp.status_code}",
                    "detail": resp.text[:500],
                })
                return
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = chunk.get("usage")
                if usage:
                    input_tokens = usage.get("prompt_tokens", input_tokens)
                    output_tokens = usage.get("completion_tokens", output_tokens)
                    # OpenRouter devolve o custo no campo `usage.cost`.
                    if usage.get("cost") is not None:
                        usage_cost = Decimal(str(usage["cost"]))
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        content_parts.append(delta)
                        yield _sse("delta", {"content": delta})
    except httpx.HTTPError as exc:
        yield _sse("error", {"message": f"Falha ao falar com o provider: "
                                        f"{type(exc).__name__}"})
        return

    content = "".join(content_parts)
    if not content:
        yield _sse("error", {"message": "O modelo respondeu vazio"})
        return

    if usage_cost is not None:
        cost = usage_cost
    else:
        try:
            policy = ai_cost_guard.policy_for(provider, model, db)
            estimated = ai_cost_guard.estimate_cost(
                policy, input_tokens or estimate_tokens(outgoing),
                output_tokens or 0)
            cost = estimated if estimated is not None else None
        except Exception:
            cost = None

    msg = ChatFreeMessage(
        conversation_id=conv.id, role="assistant", content=content,
        provider=provider, model=model,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=cost,
    )
    db.add(msg)
    conv.input_tokens = (conv.input_tokens or 0) + (input_tokens or 0)
    conv.output_tokens = (conv.output_tokens or 0) + (output_tokens or 0)
    if cost is not None:
        conv.cost_usd = (conv.cost_usd or 0) + cost
    conv.updated_at = datetime.utcnow()
    db.commit()

    tokens_now = conv.input_tokens
    yield _sse("done", {
        "message": message_out(msg),
        "conversation_tokens": tokens_now,
        "context_limit": context_limit,
        "context_warning": bool(
            context_limit and tokens_now >= context_limit * CONTEXT_WARN_RATIO
        ),
        "truncated": truncated,
        "cost_usd": float(cost) if cost is not None else None,
    })


@router.post("/chat-livre/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, req: MessageSend,
                 db: Session = Depends(get_db)):
    """Grava a mensagem do usuário e responde em SSE, sem tools."""
    conv = _get_conversation(db, conversation_id)

    user_msg = ChatFreeMessage(
        conversation_id=conv.id, role="user", content=req.content,
    )
    db.add(user_msg)
    # Título automático a partir da primeira mensagem, só enquanto o usuário
    # não tiver renomeado manualmente.
    is_first = not db.query(ChatFreeMessage).filter(
        ChatFreeMessage.conversation_id == conv.id,
        ChatFreeMessage.role == "user",
    ).first()
    if is_first and not conv.title_locked:
        conv.title = req.content[:80]
    conv.updated_at = datetime.utcnow()
    db.commit()

    history = [
        {"role": m.role, "content": m.content}
        for m in db.query(ChatFreeMessage)
        .filter(ChatFreeMessage.conversation_id == conv.id)
        .order_by(ChatFreeMessage.created_at.asc())
        .all()
        if m.role in {"user", "assistant"}
    ]

    return StreamingResponse(
        _stream_chat(req, conv, history, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
