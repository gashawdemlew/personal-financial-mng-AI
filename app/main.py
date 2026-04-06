from fastapi import FastAPI, UploadFile, File, Form, Body, APIRouter, Query
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse, HTMLResponse
import base64
import requests
import time
import json
import re
import io
import traceback
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
import asyncio
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import uuid
from fastapi.responses import StreamingResponse
try:
    import psutil
except Exception:
    psutil = None


cur_dir = os.getcwd()
parent_dir = os.path.realpath(os.path.join(os.path.dirname(cur_dir)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
    sys.path.append(cur_dir)
sys.path.insert(1, ".")

from app.vectorstore import vector_store
from app.redis_client import redis_client
from app.rag_pipeline import (
    ingest_document,
    delete_document,
    query_rag,
    ingest_document_path,
)
from app.watchdoc import watchdoc_service
from app.config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME, DEFAULT_USECASE_ID, FINANCE_USECASE_ID, TTS_OUTPUT_DIR, VISION_CHAT_URL, DB_BACKEND, DATABASE_URL, CHAT_DAILY_LIMIT, CHAT_DAILY_LIMITS, APP_TIMEZONE
from app.db import run_migrations
from app.finance.repository import (
    acknowledge_nudge,
    append_chat_messages,
    delete_chat_messages,
    find_chat_ids_by_prefix,
    find_usecases_by_chat_id,
    get_chat_messages,
    init_finance_db,
    ingest_transactions,
    list_goals,
    list_goals_for_scope,
    list_linked_accounts,
    list_monthly_budgets,
    list_nudges,
    list_all_transactions,
    list_transactions,
    transaction_storage_stats,
    upsert_monthly_budget,
    upsert_goal,
)
from app.finance.router import answer_finance_question
from app.finance.engine import goal_based_savings_plan
from app.finance.budget_intelligence import suggest_budget
from app.finance.nudges import run_phase1_nudges
from app.translation import normalize_text_to_english, back_translate_answer_if_needed
from app.tts import cleanup_expired_tts_files, generate_tts_audio
from app.speech import transcribe_audio_with_gemini, is_rate_limited_error
from app.chat_repository import (
    init_chat_db,
    create_chat_session,
    append_chat_messages as append_global_chat_messages,
    get_chat_quota_config,
    get_chat_session,
    get_chat_messages as get_global_chat_messages,
    get_chat_messages_page as get_global_chat_messages_page,
    get_recent_chat_messages as get_global_recent_chat_messages,
    find_chat_ids_by_prefix as find_global_chat_ids_by_prefix,
    list_chat_quota_configs,
    list_chat_sessions as list_global_chat_sessions,
    upsert_chat_quota_config,
    update_chat_session_title,
    delete_chat_messages as delete_global_chat_messages,
)

# ---------------------------------------------------
# Config
# ---------------------------------------------------

VLLM_URL = "http://172.16.70.95:8000/v1/chat/completions"
MODEL_NAME = "Qwen/Qwen2.5-VL-7B-Instruct"

APP_START_TIME = time.time()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _run_startup():
    if DB_BACKEND == "postgres":
        run_migrations()
    else:
        init_finance_db()
        init_chat_db()
    tts_cleanup = cleanup_expired_tts_files()
    print(
        f"[startup] Chroma persist dir: {CHROMA_PERSIST_DIR} | "
        f"collection: {CHROMA_COLLECTION_NAME} | default_usecase: {DEFAULT_USECASE_ID} | "
        f"finance_usecase: {FINANCE_USECASE_ID} | db_backend: {DB_BACKEND} | database_url: {DATABASE_URL}"
    )
    print(
        f"[startup] TTS cleanup deleted {tts_cleanup.get('deleted_count', 0)} expired files "
        f"(ttl_seconds={tts_cleanup.get('ttl_seconds')})"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _run_startup()
    except Exception as e:
        print(f"[startup] failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        raise
    yield


app = FastAPI(title="Kacha AI RAG System", version="1.0", lifespan=lifespan)

# ---------------------------------------------------
# CORS
# ---------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------
# Utilities
# ---------------------------------------------------

def extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON found")
    return json.loads(match.group())


def resolve_usecase_id(value: Optional[str]) -> str:
    return vector_store.normalize_usecase_id(value)


def chat_history_key(usecase_id: str, chat_id: str) -> str:
    return f"chat:{usecase_id}:{chat_id}"


def ensure_usecase_registered(usecase_id: str):
    if vector_store.usecase_exists(usecase_id):
        return None
    return JSONResponse(
        status_code=404,
        content={
            "success": False,
            "message": (
                f"Usecase '{usecase_id}' is not registered. "
                "Create it using POST /rag/usecases/register."
            ),
        },
    )


def _validate_budget_month(month: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}$", str(month or "").strip()))


def normalize_linked_account_id(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def maybe_generate_chat_audio(answer_text: str, with_audio: bool) -> Dict:
    if not with_audio:
        return {"enabled": False}
    try:
        tts_result = generate_tts_audio(answer_text)
        return {
            "enabled": True,
            "success": True,
            "audio_id": tts_result["audio_id"],
            "audio_url": f"/rag/audio/{tts_result['audio_id']}",
            "language_detected": tts_result.get("language_detected"),
            "language_used": tts_result.get("language_used"),
            "provider": tts_result.get("provider"),
            "fallback_used": bool(tts_result.get("fallback_used", False)),
            "gemini_error": tts_result.get("gemini_error"),
        }
    except Exception as e:
        return {"enabled": True, "success": False, "error": str(e)}


def infer_audio_mime(upload: UploadFile) -> str:
    content_type = str(upload.content_type or "").strip().lower()
    if content_type.startswith("audio/"):
        return content_type
    filename = str(upload.filename or "").lower()
    if filename.endswith(".wav"):
        return "audio/wav"
    if filename.endswith(".mp3"):
        return "audio/mpeg"
    if filename.endswith(".m4a") or filename.endswith(".mp4"):
        return "audio/mp4"
    if filename.endswith(".webm"):
        return "audio/webm"
    return "audio/webm"


def parse_with_audio(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _chat_quota_key(usecase_id: str, identifier: str, local_date: str) -> str:
    return f"chat-quota:{usecase_id}:{identifier}:{local_date}"


def _parse_chat_daily_limits() -> Dict[str, int]:
    items: Dict[str, int] = {}
    for raw in str(CHAT_DAILY_LIMITS or "").split(","):
        part = raw.strip()
        if not part or ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        try:
            items[key] = int(value)
        except Exception:
            continue
    return items


def get_chat_daily_limit_for_usecase(usecase_id: str) -> int:
    normalized = resolve_usecase_id(usecase_id)
    stored = get_chat_quota_config(normalized)
    if stored is not None:
        return int(stored.get("daily_limit", CHAT_DAILY_LIMIT))
    per_usecase = _parse_chat_daily_limits()
    if normalized in per_usecase:
        return per_usecase[normalized]
    if "default" in per_usecase:
        return per_usecase["default"]
    return CHAT_DAILY_LIMIT


def _seconds_until_next_local_day() -> int:
    now = datetime.now(ZoneInfo(APP_TIMEZONE))
    tomorrow = (now + timedelta(days=1)).date()
    next_midnight = datetime.combine(tomorrow, datetime.min.time(), tzinfo=ZoneInfo(APP_TIMEZONE))
    return max(int((next_midnight - now).total_seconds()), 1)


def consume_daily_chat_quota(usecase_id: str, user_id: Optional[str] = None, chat_id: Optional[str] = None) -> Dict:
    limit = get_chat_daily_limit_for_usecase(usecase_id)
    if limit <= 0:
        return {"allowed": True, "limit": limit, "used": 0, "remaining": None}

    identifier = str(user_id or chat_id or "").strip()
    if not identifier:
        return {"allowed": True, "limit": limit, "used": 0, "remaining": limit}

    now = datetime.now(ZoneInfo(APP_TIMEZONE))
    local_date = now.date().isoformat()
    key = _chat_quota_key(usecase_id=usecase_id, identifier=identifier, local_date=local_date)
    used = int(redis_client.incr(key))
    if used == 1:
        redis_client.expire(key, _seconds_until_next_local_day())
    allowed = used <= limit
    return {
        "allowed": allowed,
        "limit": limit,
        "used": used,
        "remaining": max(limit - used, 0),
        "identifier": identifier,
        "reset_on": local_date,
    }


def chat_limit_response(usecase_id: str, quota: Dict) -> Dict:
    return {
        "success": False,
        "usecase_id": usecase_id,
        "message": f"Daily chat limit reached. You can ask up to {quota.get('limit', CHAT_DAILY_LIMIT)} questions per day for this usecase.",
        "quota": quota,
    }


def get_daily_chat_quota_status(usecase_id: str, user_id: Optional[str] = None, chat_id: Optional[str] = None) -> Dict:
    limit = get_chat_daily_limit_for_usecase(usecase_id)
    identifier = str(user_id or chat_id or "").strip()
    if not identifier:
        return {"allowed": True, "limit": limit, "used": 0, "remaining": limit, "identifier": ""}
    now = datetime.now(ZoneInfo(APP_TIMEZONE))
    local_date = now.date().isoformat()
    key = _chat_quota_key(usecase_id=usecase_id, identifier=identifier, local_date=local_date)
    raw = redis_client.get(key)
    used = int((raw.decode() if isinstance(raw, bytes) else str(raw or "0")).strip() or "0")
    return {
        "allowed": used < limit,
        "limit": limit,
        "used": used,
        "remaining": max(limit - used, 0),
        "identifier": identifier,
        "reset_on": local_date,
    }


def out_of_context_message(usecase_id: str) -> str:
    normalized = resolve_usecase_id(usecase_id)
    if normalized == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
        return "It's out of context, I am here to help you with Personal Financial Managment"
    if normalized == "kacha-wallet":
        return "It's out of context, I am here to help you with kacha- general information, services, process, and soon"
    if normalized in {"superapp-guidance", "super"} or "superapp" in normalized:
        return "It's out of context, I am here to help you with superapp- general information, services, process, and soon"
    return "It's out of context, I am here to help you with general information, services, and process"


def normalize_chatbot_answer(usecase_id: str, answer: str) -> str:
    text = str(answer or "").strip()
    if text == "Not found in provided documents":
        return out_of_context_message(usecase_id)
    return text


def summary_history_window(history: List[Dict], keep_total: int = 12, keep_head: int = 2) -> List[Dict]:
    if len(history) <= keep_total:
        return history
    keep_tail = min(6, keep_total - keep_head)
    remaining = max(keep_total - keep_head - keep_tail, 0)
    head = history[:keep_head]
    tail = history[-keep_tail:] if keep_tail else []
    middle_source = history[keep_head:len(history) - keep_tail]
    middle = []
    if remaining > 0 and middle_source:
        step = max(len(middle_source) / remaining, 1)
        seen = set()
        for idx in range(remaining):
            pos = int(idx * step)
            pos = min(pos, len(middle_source) - 1)
            candidate = middle_source[pos]
            marker = (candidate.get("role"), candidate.get("content"))
            if marker in seen:
                continue
            seen.add(marker)
            middle.append(candidate)
    return head + middle + tail


def append_history_tail(usecase_id: str, chat_id: str, messages: List[Dict], max_messages: int = 12):
    history_key = chat_history_key(usecase_id, chat_id)
    cached = _decode_history(redis_client.get(history_key))
    cached.extend(messages)
    if len(cached) > max_messages:
        cached = cached[-max_messages:]
    redis_client.set(history_key, json.dumps(cached))


def load_recent_history(usecase_id: str, chat_id: str, limit: int = 12) -> List[Dict]:
    redis_history = _decode_history(redis_client.get(chat_history_key(usecase_id, chat_id)))
    if redis_history:
        return redis_history[-limit:]
    recent = get_global_recent_chat_messages(usecase_id=usecase_id, chat_id=chat_id, limit=limit)
    if recent:
        return recent
    if usecase_id == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
        finance_history = get_chat_messages(usecase_id=usecase_id, chat_id=chat_id)
        return finance_history[-limit:]
    return []


def generate_chat_title(question: str, usecase_id: str) -> str:
    fallback = str(question or "").strip().replace("\n", " ")[:80] or "New chat"
    system_prompt = (
        "Generate a very short chat title from the user's first message. "
        "Return only the title. Keep it under 8 words. Do not use quotes."
    )
    user_prompt = (
        f"Usecase: {usecase_id}\n"
        f"First user message: {question}"
    )
    try:
        response = requests.post(
            VLLM_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
            },
            timeout=20,
        )
        if response.status_code != 200:
            return fallback
        title = response.json()["choices"][0]["message"]["content"].strip().strip('"').strip("'")
        if not title:
            return fallback
        return title[:80]
    except Exception:
        return fallback


def maybe_autogenerate_chat_title(usecase_id: str, chat_id: str, first_user_message: str):
    session = get_chat_session(usecase_id=usecase_id, chat_id=chat_id)
    if not session:
        return
    current_title = str(session.get("title") or "").strip()
    if current_title and current_title != "New chat":
        return
    generated = generate_chat_title(first_user_message, usecase_id=usecase_id)
    update_chat_session_title(usecase_id=usecase_id, chat_id=chat_id, title=generated)


def resolve_chat_usecase(chat_id: str, usecase_id: Optional[str]) -> Dict:
    if usecase_id:
        normalized = resolve_usecase_id(usecase_id)
        return {"ok": True, "usecase_id": normalized}

    candidates = redis_client.keys(f"chat:*:{chat_id}")
    if not candidates:
        finance_candidates = find_usecases_by_chat_id(chat_id)
        if len(finance_candidates) == 1:
            return {"ok": True, "usecase_id": finance_candidates[0]}
        if len(finance_candidates) > 1:
            return {
                "ok": False,
                "error": "Ambiguous chat_id across multiple usecases; please provide usecase_id explicitly.",
                "candidates": finance_candidates,
            }
        return {"ok": True, "usecase_id": resolve_usecase_id(None)}
    parsed = []
    for key in candidates:
        key_s = key.decode() if isinstance(key, bytes) else str(key)
        parts = key_s.split(":")
        if len(parts) >= 3 and parts[0] == "chat":
            parsed.append(parts[1])
    parsed = sorted(set(parsed))
    if len(parsed) == 1:
        return {"ok": True, "usecase_id": parsed[0]}
    return {
        "ok": False,
        "error": "Ambiguous chat_id across multiple usecases; please provide usecase_id explicitly.",
        "candidates": parsed,
    }


def resolve_effective_chat_id(usecase_id: str, chat_id: str) -> Dict:
    # Exact key first.
    exact_key = chat_history_key(usecase_id, chat_id)
    exact_raw = redis_client.get(exact_key)
    if exact_raw:
        return {"ok": True, "chat_id": chat_id}

    if usecase_id == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
        exact_fin = get_chat_messages(usecase_id=usecase_id, chat_id=chat_id)
        if exact_fin:
            return {"ok": True, "chat_id": chat_id}
    exact_global = get_global_chat_messages(usecase_id=usecase_id, chat_id=chat_id)
    if exact_global:
        return {"ok": True, "chat_id": chat_id}

    # Prefix-based alias resolution.
    candidates = set()
    for key in redis_client.keys(f"chat:{usecase_id}:{chat_id}*"):
        key_s = key.decode() if isinstance(key, bytes) else str(key)
        parts = key_s.split(":", 2)
        if len(parts) == 3:
            candidates.add(parts[2])

    if usecase_id == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
        for c in find_chat_ids_by_prefix(usecase_id=usecase_id, chat_id_prefix=chat_id):
            candidates.add(c)
    for c in find_global_chat_ids_by_prefix(usecase_id=usecase_id, chat_id_prefix=chat_id):
        candidates.add(c)

    if len(candidates) == 1:
        return {"ok": True, "chat_id": sorted(candidates)[0]}
    if len(candidates) > 1:
        return {
            "ok": False,
            "error": "Multiple chats match this chat_id prefix; provide exact chat_id.",
            "candidates": sorted(candidates),
        }

    return {"ok": True, "chat_id": chat_id}


def _decode_history(raw) -> List[Dict]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def load_best_history(usecase_id: str, chat_id: str) -> List[Dict]:
    redis_history = _decode_history(redis_client.get(chat_history_key(usecase_id, chat_id)))
    global_history = get_global_chat_messages(usecase_id=usecase_id, chat_id=chat_id)
    if usecase_id == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
        finance_history = get_chat_messages(usecase_id=usecase_id, chat_id=chat_id)
    else:
        finance_history = []
    if global_history:
        return global_history
    if finance_history:
        return finance_history
    return redis_history

@app.get("/redis-test")
def redis_test():
    try:
        info = redis_client.info() if hasattr(redis_client, "info") else {}
        mode = info.get("mode", "redis")
        return {"status": "OK", "ping": redis_client.ping(), "mode": mode}
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}

# ---------------------------------------------------
# RAG SYSTEM ENDPOINTS
# ---------------------------------------------------

@app.get("/rag/system/status")
async def rag_system_status(usecase_id: Optional[str] = Query(None)):
    try:
        usecase = resolve_usecase_id(usecase_id)
        not_found = ensure_usecase_registered(usecase)
        if not_found:
            return not_found
        uptime_seconds = int(time.time() - APP_START_TIME)
        docs = vector_store.list_documents(usecase_id=usecase)
        document_count = len(docs)
        vector_count = vector_store.vector_count(usecase_id=usecase)

        redis_ok = True
        redis_memory = None

        try:
            info = redis_client.info()
            redis_memory = info.get("used_memory_human")
        except Exception:
            redis_ok = False

        if psutil:
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent()
            memory_percent = memory.percent
            available_memory_mb = round(memory.available / 1024 / 1024, 2)
        else:
            cpu_percent = None
            memory_percent = None
            available_memory_mb = None

        return {
            "status": "ok",
            "uptime_seconds": uptime_seconds,
            "vector_store": {
                "provider": "chromadb",
                "usecase_id": usecase,
                "known_usecases": vector_store.list_usecases(),
                "index_size": vector_count,
                "vector_count": vector_count,
                "document_count": document_count,
            },
            "redis": {
                "connected": redis_ok,
                "used_memory": redis_memory,
            },
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "available_memory_mb": available_memory_mb,
            }
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

# ---------------------------------------------------

@app.get("/rag/system/metrics", response_class=PlainTextResponse)
async def rag_metrics(usecase_id: Optional[str] = Query(None)):
    """
    Prometheus-style metrics
    """
    try:
        usecase = resolve_usecase_id(usecase_id)
        not_found = ensure_usecase_registered(usecase)
        if not_found:
            return not_found
        uptime_seconds = int(time.time() - APP_START_TIME)
        vector_count = vector_store.vector_count(usecase_id=usecase)
        document_count = len(vector_store.list_documents(usecase_id=usecase))

        if psutil:
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent()
            memory_percent = memory.percent
        else:
            cpu_percent = 0
            memory_percent = 0

        metrics = f"""
            # HELP rag_uptime_seconds API uptime
            # TYPE rag_uptime_seconds counter
            rag_uptime_seconds {uptime_seconds}

            # HELP rag_vector_count Number of vectors in ChromaDB
            # TYPE rag_vector_count gauge
            rag_vector_count{{usecase_id="{usecase}"}} {vector_count}

            # HELP rag_document_count Number of indexed documents
            # TYPE rag_document_count gauge
            rag_document_count{{usecase_id="{usecase}"}} {document_count}

            # HELP rag_cpu_percent CPU usage
            # TYPE rag_cpu_percent gauge
            rag_cpu_percent {cpu_percent}

            # HELP rag_memory_percent Memory usage
            # TYPE rag_memory_percent gauge
            rag_memory_percent {memory_percent}
            """
        return metrics.strip()

    except Exception as e:
        return PlainTextResponse(f"# ERROR {str(e)}", status_code=500)

# ---------------------------------------------------

@app.post("/rag/system/reset")
async def rag_system_reset(payload: dict = Body(default={})):
    """
    Clears:
    - Chroma collection vectors per usecase (or all if omitted)
    - Redis chat memory
    """
    try:
        usecase = resolve_usecase_id(payload.get("usecase_id")) if payload.get("usecase_id") else None
        if usecase:
            not_found = ensure_usecase_registered(usecase)
            if not_found:
                return not_found
        vector_store.reset(usecase_id=usecase)

        key_pattern = f"chat:{usecase}:*" if usecase else "chat:*"
        keys = redis_client.keys(key_pattern)
        if keys:
            redis_client.delete(*keys)

        return {
            "success": True,
            "usecase_id": usecase,
            "message": "RAG system reset completed"
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

# ---------------------------------------------------

@app.post("/rag/system/compact-index")
async def compact_faiss_index():
    """
    No-op compatibility endpoint.
    """
    try:
        vector_store.compact()

        return {
            "success": True,
            "message": "ChromaDB handles compaction internally"
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

# ---------------------------------------------------
# DOCUMENT MANAGEMENT
# ---------------------------------------------------

@app.post("/rag/upload")
async def upload_document(file: UploadFile = File(...), usecase_id: Optional[str] = Form(None)):
    usecase = resolve_usecase_id(usecase_id)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    result = ingest_document(file, usecase_id=usecase)
    return result


@app.delete("/rag/document/{doc_id}")
async def remove_document(doc_id: str, usecase_id: Optional[str] = Query(None)):
    usecase = resolve_usecase_id(usecase_id)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    result = delete_document(doc_id, usecase_id=usecase)
    return result

@app.get("/rag/documents")
async def list_documents(usecase_id: Optional[str] = Query(None)):
    try:
        usecase = resolve_usecase_id(usecase_id)
        not_found = ensure_usecase_registered(usecase)
        if not_found:
            return not_found
        docs = vector_store.list_documents(usecase_id=usecase)
        return {
            "success": True,
            "usecase_id": usecase,
            "count": len(docs),
            "documents": docs,
        }
    except Exception as e:
        return {"success": False, "count": 0, "documents": [], "error": str(e)}


@app.get("/rag/usecases")
async def list_usecases():
    return {"success": True, "usecases": vector_store.list_usecases()}


@app.post("/rag/usecases/register")
async def register_usecase(payload: dict = Body(...)):
    usecase_id = payload.get("usecase_id")
    if not usecase_id:
        return {"success": False, "message": "usecase_id required"}
    name = payload.get("name", "")
    description = payload.get("description", "")
    usecase = vector_store.register_usecase(usecase_id, name=name, description=description)
    return {"success": True, "usecase": usecase}


@app.delete("/rag/usecases/{usecase_id}")
async def delete_usecase(usecase_id: str):
    normalized = resolve_usecase_id(usecase_id)
    try:
        deleted = vector_store.delete_usecase(normalized)
        if not deleted:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": f"Usecase '{normalized}' not found."},
            )

        keys = redis_client.keys(f"chat:{normalized}:*")
        if keys:
            redis_client.delete(*keys)

        return {"success": True, "usecase_id": normalized, "message": "Usecase deleted"}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})


@app.post("/rag/watchdoc/start")
async def watchdoc_start(payload: dict = Body(...)):
    path = payload.get("path")
    if not path:
        return {"success": False, "message": "path required"}
    usecase = resolve_usecase_id(payload.get("usecase_id"))
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    return watchdoc_service.start(path, usecase_id=usecase)


@app.post("/rag/watchdoc/stop")
async def watchdoc_stop():
    return watchdoc_service.stop()


@app.get("/rag/watchdoc/status")
async def watchdoc_status():
    return {"success": True, **watchdoc_service.status()}


@app.post("/rag/watchdoc/scan")
async def watchdoc_scan(payload: dict = Body(...)):
    path = payload.get("path")
    if not path:
        return {"success": False, "message": "path required"}
    if not os.path.isdir(path):
        return {"success": False, "message": "path must be a valid directory"}
    usecase = resolve_usecase_id(payload.get("usecase_id"))
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found

    processed = []
    failed = []

    for root, _, files in os.walk(path):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in {".pdf", ".docx", ".txt"}:
                continue
            file_path = os.path.join(root, name)
            result = ingest_document_path(file_path, usecase_id=usecase)
            if result.get("success"):
                processed.append(
                    {
                        "doc_id": result.get("doc_id"),
                        "filename": result.get("filename"),
                        "chunks_indexed": result.get("chunks_indexed"),
                    }
                )
            else:
                failed.append({"path": file_path, "error": result.get("message")})

    return {
        "success": True,
        "usecase_id": usecase,
        "path": os.path.abspath(path),
        "processed_count": len(processed),
        "failed_count": len(failed),
        "processed": processed,
        "failed": failed,
    }


@app.get("/rag/audio/{audio_id}")
async def rag_get_audio(audio_id: str):
    if not re.match(r"^[a-zA-Z0-9\-]+$", audio_id):
        return JSONResponse(status_code=400, content={"success": False, "message": "invalid audio_id"})
    mp3_path = os.path.join(TTS_OUTPUT_DIR, f"{audio_id}.mp3")
    wav_path = os.path.join(TTS_OUTPUT_DIR, f"{audio_id}.wav")
    if os.path.exists(mp3_path):
        return FileResponse(mp3_path, media_type="audio/mpeg", filename=f"{audio_id}.mp3")
    if os.path.exists(wav_path):
        return FileResponse(wav_path, media_type="audio/wav", filename=f"{audio_id}.wav")
    if not os.path.exists(mp3_path) and not os.path.exists(wav_path):
        return JSONResponse(status_code=404, content={"success": False, "message": "audio not found"})
    return JSONResponse(status_code=404, content={"success": False, "message": "audio not found"})


@app.post("/rag/speech-to-text")
async def rag_speech_to_text(
    audio: UploadFile = File(...),
    language_hint: Optional[str] = Form(None),
):
    try:
        audio_bytes = await audio.read()
        mime_type = infer_audio_mime(audio)
        print(f"Received audio file '{audio.filename}' with inferred MIME type '{mime_type}' and size {len(audio_bytes)} bytes")
        
        result = transcribe_audio_with_gemini(audio_bytes=audio_bytes, mime_type=mime_type)
        return {
            "success": True,
            "text": result.get("text", "").strip(),
            "language_hint": language_hint,
            "mime_type": mime_type,
        }
    except Exception as e:
        msg = str(e)
        print(f"Error during speech-to-text: {msg}")
        if is_rate_limited_error(msg):
            return {
                "success": False,
                "message": "The system is not listening rather ask your question by typing",
            }
        return {"success": False, "message": msg}


@app.post("/rag/chat/audio")
async def rag_chat_audio(
    chat_id: str = Form(...),
    usecase_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    with_audio: Optional[str] = Form(None),
    audio: UploadFile = File(...),
):
    stt_result = await rag_speech_to_text(audio=audio)
    if not stt_result.get("success"):
        return stt_result
    question = stt_result.get("text", "").strip()
    if not question:
        return {"success": False, "message": "empty transcription"}

    payload = {
        "chat_id": chat_id,
        "question": question,
        "usecase_id": usecase_id,
        "user_id": user_id,
        "with_audio": with_audio,
    }
    chat_result = await rag_chat(payload)
    if isinstance(chat_result, dict):
        chat_result["transcription"] = {
            "success": True,
            "text": question,
            "mime_type": stt_result.get("mime_type"),
        }
    return chat_result


@app.get("/rag/voice/test", response_class=HTMLResponse)
async def rag_voice_test_page():
    html = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>Voice Chat Test</title>
      <style>
        body { font-family: sans-serif; margin: 24px; }
        button { margin-right: 8px; padding: 8px 12px; }
        pre { background: #f5f5f5; padding: 12px; white-space: pre-wrap; }
      </style>
    </head>
    <body>
      <h2>Voice Chat Test</h2>
      <p>Record voice locally and send to <code>/rag/chat/audio</code>.</p>
      <label>Chat ID: <input id="chatId" value="voice-user-1"/></label><br/><br/>
      <label>Usecase ID: <input id="usecaseId" value="financial-guide"/></label><br/><br/>
      <label>User ID: <input id="userId" value="user_123"/></label><br/><br/>
      <button id="startBtn">Start Recording</button>
      <button id="stopBtn" disabled>Stop Recording</button>
      <input id="fileInput" type="file" accept="audio/*" />
      <button id="sendFileBtn">Send Selected Audio File</button>
      <audio id="player" controls></audio>
      <pre id="out"></pre>
      <script>
        let recorder, chunks = [], stream;
        const startBtn = document.getElementById('startBtn');
        const stopBtn = document.getElementById('stopBtn');
        const fileInput = document.getElementById('fileInput');
        const sendFileBtn = document.getElementById('sendFileBtn');
        const out = document.getElementById('out');
        const player = document.getElementById('player');

        function selectedMimeType() {
          if (typeof MediaRecorder === "undefined") return "";
          const cands = [
            "audio/webm;codecs=opus",
            "audio/webm",
            "audio/mp4",
            "audio/mpeg"
          ];
          for (const c of cands) {
            if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(c)) return c;
          }
          return "";
        }

        async function sendBlob(blob, filename) {
          const fd = new FormData();
          fd.append('audio', blob, filename);
          fd.append('chat_id', document.getElementById('chatId').value);
          fd.append('usecase_id', document.getElementById('usecaseId').value);
          fd.append('user_id', document.getElementById('userId').value);
          fd.append('with_audio', 'true');
          const res = await fetch('/rag/chat/audio', { method: 'POST', body: fd });
          const data = await res.json();
          out.textContent = JSON.stringify(data, null, 2);
          if (data.audio && data.audio.success && data.audio.audio_url) {
            player.src = data.audio.audio_url;
          }
        }

        async function getAudioStream() {
          if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            return navigator.mediaDevices.getUserMedia({ audio: true });
          }
          const legacyGetUserMedia =
            navigator.getUserMedia ||
            navigator.webkitGetUserMedia ||
            navigator.mozGetUserMedia ||
            navigator.msGetUserMedia;
          if (!legacyGetUserMedia) {
            throw new Error("Microphone API unavailable in this browser runtime.");
          }
          return new Promise((resolve, reject) => {
            legacyGetUserMedia.call(navigator, { audio: true }, resolve, reject);
          });
        }

        startBtn.onclick = async () => {
          try {
            if (typeof MediaRecorder === "undefined") {
              out.textContent = "MediaRecorder not supported in this browser. Use file upload fallback.";
              return;
            }
            out.textContent = "Recording...";
            stream = await getAudioStream();
            const mime = selectedMimeType();
            recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
            chunks = [];
            recorder.ondataavailable = e => {
              if (e.data && e.data.size > 0) chunks.push(e.data);
            };
            recorder.onerror = (e) => {
              out.textContent = "Recorder error: " + (e.error ? e.error.message : "unknown");
            };
            recorder.onstop = async () => {
              try {
                const m = recorder.mimeType || mime || 'audio/webm';
                const ext = m.includes('mp4') ? 'm4a' : (m.includes('mpeg') ? 'mp3' : 'webm');
                const blob = new Blob(chunks, { type: m });
                await sendBlob(blob, 'voice.' + ext);
              } catch (err) {
                out.textContent = "Upload error: " + err;
              } finally {
                if (stream) stream.getTracks().forEach(t => t.stop());
              }
            };
            recorder.start();
            startBtn.disabled = true;
            stopBtn.disabled = false;
          } catch (err) {
            out.textContent = "Cannot start recording: " + err;
          }
        };

        stopBtn.onclick = () => {
          if (recorder && recorder.state !== "inactive") recorder.stop();
          stopBtn.disabled = true;
          startBtn.disabled = false;
        };

        sendFileBtn.onclick = async () => {
          const f = fileInput.files && fileInput.files[0];
          if (!f) {
            out.textContent = "Select an audio file first.";
            return;
          }
          out.textContent = "Uploading selected file...";
          await sendBlob(f, f.name || "voice_upload");
        };
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/rag/chat/image")
async def rag_chat_image(
    image: UploadFile = File(...),
    prompt: str = Form(...),
    with_audio: Optional[str] = Form(None),
    chat_id: Optional[str] = Form(None),
    usecase_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
):
    usecase = resolve_usecase_id(usecase_id)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    if not prompt:
        return {"success": False, "message": "prompt required"}

    try:
        image_bytes = await image.read()
        files = {
            "image": (image.filename or "image.jpg", image_bytes, image.content_type or "image/jpeg")
        }
        data = {"prompt": prompt}
        r = requests.post(VISION_CHAT_URL, files=files, data=data, timeout=120)
        if r.status_code != 200:
            return {"success": False, "message": r.text}
        result = r.json()

        extracted_text = ""
        if isinstance(result, dict):
            extracted_text = result.get("answer") or result.get("response") or result.get("text") or ""
        if not extracted_text:
            extracted_text = str(result)
        extracted_text = extracted_text.strip()
        if not extracted_text:
            return {"success": False, "message": "No text extracted from image"}

        final_question = f'Here is the error: "{extracted_text}". Please suggest a fix.'

        effective_chat_id = str(chat_id or user_id or "image-chat")
        chat_payload = {
            "chat_id": effective_chat_id,
            "question": final_question,
            "usecase_id": usecase,
            "with_audio": with_audio,
        }
        if user_id:
            chat_payload["user_id"] = user_id

        chat_result = await rag_chat(chat_payload)
        if isinstance(chat_result, dict):
            chat_result["image_ocr"] = {
                "prompt": prompt,
                "extracted_text": extracted_text,
                "raw": result,
            }
        return chat_result
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/rag/chat/new")
async def rag_chat_new(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id"))
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    user_id = str(payload.get("user_id") or "").strip()
    title = str(payload.get("title") or "").strip()
    suffix = str(uuid.uuid4())[:8]
    if user_id:
        chat_id = f"{user_id}-{usecase}-{suffix}"
    else:
        chat_id = f"{usecase}-{suffix}"
    redis_client.set(chat_history_key(usecase, chat_id), json.dumps([]))
    create_chat_session(usecase_id=usecase, chat_id=chat_id, user_id=user_id, title=title)
    return {
        "success": True,
        "usecase_id": usecase,
        "chat_id": chat_id,
        "history": [],
    }


@app.get("/rag/chat/quota")
async def rag_chat_quota(
    usecase_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
):
    usecase = resolve_usecase_id(usecase_id)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    if not user_id and not chat_id:
        return {"success": False, "message": "user_id or chat_id required"}
    quota = get_daily_chat_quota_status(
        usecase_id=usecase,
        user_id=str(user_id or ""),
        chat_id=str(chat_id or ""),
    )
    return {
        "success": True,
        "usecase_id": usecase,
        "user_id": str(user_id or ""),
        "chat_id": str(chat_id or ""),
        "quota": quota,
    }


@app.get("/admin/chat/quota-config")
async def admin_list_chat_quota_config(usecase_id: Optional[str] = Query(None)):
    if usecase_id:
        usecase = resolve_usecase_id(usecase_id)
        not_found = ensure_usecase_registered(usecase)
        if not_found:
            return not_found
        stored = get_chat_quota_config(usecase)
        return {
            "success": True,
            "usecase_id": usecase,
            "config": stored,
            "effective_daily_limit": get_chat_daily_limit_for_usecase(usecase),
            "source": "database" if stored else "env",
        }
    rows = list_chat_quota_configs()
    enriched = []
    for row in rows:
        enriched.append(
            {
                **row,
                "effective_daily_limit": get_chat_daily_limit_for_usecase(row["usecase_id"]),
                "source": "database",
            }
        )
    return {"success": True, "count": len(enriched), "configs": enriched}


@app.post("/admin/chat/quota-config")
async def admin_set_chat_quota_config(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id"))
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    daily_limit = payload.get("daily_limit")
    if daily_limit is None:
        return {"success": False, "message": "daily_limit required"}
    try:
        daily_limit_i = int(daily_limit)
    except Exception:
        return {"success": False, "message": "daily_limit must be integer"}
    if daily_limit_i < 0:
        return {"success": False, "message": "daily_limit must be non-negative"}
    saved = upsert_chat_quota_config(usecase, daily_limit_i)
    return {
        "success": True,
        "usecase_id": usecase,
        "config": saved,
        "effective_daily_limit": get_chat_daily_limit_for_usecase(usecase),
        "source": "database",
    }


@app.get("/rag/chats")
async def rag_list_chats(
    usecase_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
):
    usecase = resolve_usecase_id(usecase_id)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    sessions = list_global_chat_sessions(
        usecase_id=usecase,
        user_id=str(user_id or ""),
        limit=limit,
        offset=offset,
    )
    return {
        "success": True,
        "usecase_id": usecase,
        "user_id": str(user_id or ""),
        "count": len(sessions),
        "chats": sessions,
    }


@app.post("/finance/transactions/ingest")
async def finance_ingest_transactions(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id") or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found

    user_id = payload.get("user_id")
    if not user_id:
        return {"success": False, "message": "user_id required"}

    transactions = payload.get("transactions") or []
    if not isinstance(transactions, list) or not transactions:
        return {"success": False, "message": "transactions must be a non-empty list"}

    inserted, failed, retention = ingest_transactions(usecase, str(user_id), transactions)
    return {
        "success": True,
        "usecase_id": usecase,
        "user_id": str(user_id),
        "inserted": inserted,
        "failed_count": len(failed),
        "failed": failed[:50],
        "retention": retention,
    }


@app.get("/finance/transactions")
async def finance_list_transactions(
    user_id: str,
    usecase_id: Optional[str] = Query(None),
    linked_account_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(200),
):
    usecase = resolve_usecase_id(usecase_id or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found

    rows = list_transactions(
        usecase_id=usecase,
        user_id=user_id,
        linked_account_id=normalize_linked_account_id(linked_account_id),
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    normalized_account_id = normalize_linked_account_id(linked_account_id)
    return {
        "success": True,
        "usecase_id": usecase,
        "user_id": user_id,
        "linked_account_id": normalized_account_id,
        "account_scope": "account" if normalized_account_id else "portfolio",
        "count": len(rows),
        "transactions": rows,
    }


@app.get("/finance/accounts")
async def finance_list_accounts(
    user_id: str,
    usecase_id: Optional[str] = Query(None),
):
    usecase = resolve_usecase_id(usecase_id or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    account_ids = list_linked_accounts(usecase_id=usecase, user_id=user_id, include_archive=True)
    return {
        "success": True,
        "usecase_id": usecase,
        "user_id": user_id,
        "count": len(account_ids),
        "linked_accounts": account_ids,
    }


@app.get("/admin/finance/transactions/stats")
async def admin_finance_transaction_stats(
    usecase_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    linked_account_id: Optional[str] = Query(None),
):
    usecase = resolve_usecase_id(usecase_id or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    normalized_account_id = normalize_linked_account_id(linked_account_id)
    stats = transaction_storage_stats(
        usecase_id=usecase,
        user_id=str(user_id or "") or None,
        linked_account_id=normalized_account_id,
    )
    totals = {
        "active_count": sum(item["active_count"] for item in stats),
        "archived_count": sum(item["archived_count"] for item in stats),
    }
    return {
        "success": True,
        "usecase_id": usecase,
        "user_id": str(user_id or ""),
        "linked_account_id": normalized_account_id,
        "account_scope": "account" if normalized_account_id else "portfolio",
        "count": len(stats),
        "totals": totals,
        "users": stats,
    }


@app.post("/finance/ask")
async def finance_ask(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id") or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    user_id = payload.get("user_id")
    question = payload.get("question")
    chat_id = payload.get("chat_id")
    linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
    if not user_id:
        return {"success": False, "message": "user_id required"}
    if not question:
        return {"success": False, "message": "question required"}
    quota = consume_daily_chat_quota(usecase_id=usecase, user_id=str(user_id), chat_id=str(chat_id or user_id))
    if not quota.get("allowed", True):
        return chat_limit_response(usecase, quota)
    question_en, q_meta = normalize_text_to_english(question)
    result = answer_finance_question(
        usecase_id=usecase,
        user_id=str(user_id),
        question=question_en,
        linked_account_id=linked_account_id,
    )
    user_answer, a_meta = back_translate_answer_if_needed(
        result.get("answer", ""),
        q_meta.get("source_language", "unknown"),
    )
    result["answer"] = user_answer

    effective_chat_id = str(chat_id or user_id)
    to_append = [
        {"role": "user", "content": question},
        {"role": "assistant", "content": user_answer},
    ]
    append_history_tail(usecase_id=usecase, chat_id=effective_chat_id, messages=to_append)
    append_global_chat_messages(usecase_id=usecase, chat_id=effective_chat_id, messages=to_append, user_id=str(user_id))
    maybe_autogenerate_chat_title(usecase_id=usecase, chat_id=effective_chat_id, first_user_message=question)
    append_chat_messages(
        usecase_id=usecase,
        user_id=str(user_id),
        chat_id=effective_chat_id,
        messages=to_append,
    )
    result["chat_id"] = effective_chat_id
    result["question_language"] = q_meta.get("source_language", "unknown")
    result["question_translated_to_english"] = bool(q_meta.get("translated", False))
    result["response_translated_from_english"] = bool(a_meta.get("translated", False))
    result["linked_account_id"] = linked_account_id
    result["account_scope"] = "account" if linked_account_id else "portfolio"

    return result


@app.post("/finance/savings/goal")
async def finance_goal_savings(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id") or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found

    user_id = payload.get("user_id")
    goal_amount = payload.get("goal_amount")
    target_months = payload.get("target_months")
    linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
    if not user_id:
        return {"success": False, "message": "user_id required"}
    if goal_amount is None:
        return {"success": False, "message": "goal_amount required"}
    if target_months is None:
        return {"success": False, "message": "target_months required"}

    try:
        rows = list_all_transactions(
            usecase_id=usecase,
            user_id=str(user_id),
            linked_account_id=linked_account_id,
        )
        result = goal_based_savings_plan(rows, goal_amount=float(goal_amount), target_months=int(target_months))
        return {
            "success": True,
            "usecase_id": usecase,
            "user_id": str(user_id),
            "linked_account_id": linked_account_id,
            "account_scope": "account" if linked_account_id else "portfolio",
            "goal": result,
            "answer": result.get("answer", ""),
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/finance/budget/set")
async def finance_set_monthly_budget(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id") or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    user_id = payload.get("user_id")
    budget_month = payload.get("budget_month")
    total_budget = payload.get("total_budget")
    linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
    if not user_id:
        return {"success": False, "message": "user_id required"}
    if not budget_month or not _validate_budget_month(str(budget_month)):
        return {"success": False, "message": "budget_month must be YYYY-MM"}
    if total_budget is None:
        return {"success": False, "message": "total_budget required"}

    category_allocations = payload.get("category_allocations") or {}
    if not isinstance(category_allocations, dict):
        return {"success": False, "message": "category_allocations must be an object"}

    try:
        total_budget_f = float(total_budget)
        if total_budget_f < 0:
            return {"success": False, "message": "total_budget must be non-negative"}
        cleaned_allocations = {}
        allocation_sum = 0.0
        for k, v in category_allocations.items():
            key = str(k or "").strip().lower()
            if not key:
                continue
            amount = float(v)
            if amount < 0:
                return {"success": False, "message": "category allocation must be non-negative"}
            cleaned_allocations[key] = round(amount, 2)
            allocation_sum += amount
        if cleaned_allocations and round(allocation_sum, 2) > round(total_budget_f, 2):
            return {"success": False, "message": "sum(category_allocations) cannot exceed total_budget"}

        saved = upsert_monthly_budget(
            usecase_id=usecase,
            user_id=str(user_id),
            linked_account_id=linked_account_id,
            budget_month=str(budget_month),
            total_budget=total_budget_f,
            currency=str(payload.get("currency") or "ETB"),
            category_allocations=cleaned_allocations,
        )
        return {
            "success": True,
            "usecase_id": usecase,
            "user_id": str(user_id),
            "linked_account_id": linked_account_id,
            "account_scope": "account" if linked_account_id else "portfolio",
            "budget": saved,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/finance/budget/history")
async def finance_budget_history(
    user_id: str,
    usecase_id: Optional[str] = Query(None),
    linked_account_id: Optional[str] = Query(None),
    limit: int = Query(12),
    up_to_month: Optional[str] = Query(None),
):
    usecase = resolve_usecase_id(usecase_id or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    if up_to_month and not _validate_budget_month(up_to_month):
        return {"success": False, "message": "up_to_month must be YYYY-MM"}
    normalized_account_id = normalize_linked_account_id(linked_account_id)
    rows = list_monthly_budgets(
        usecase_id=usecase,
        user_id=user_id,
        linked_account_id=normalized_account_id,
        limit=limit,
        up_to_month=up_to_month,
    )
    return {
        "success": True,
        "usecase_id": usecase,
        "user_id": user_id,
        "linked_account_id": normalized_account_id,
        "account_scope": "account" if normalized_account_id else "portfolio",
        "count": len(rows),
        "budgets": rows,
    }


@app.post("/finance/budget/suggest")
async def finance_budget_suggest(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id") or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    user_id = payload.get("user_id")
    target_month = payload.get("target_month")
    linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
    if not user_id:
        return {"success": False, "message": "user_id required"}
    if not target_month or not _validate_budget_month(str(target_month)):
        return {"success": False, "message": "target_month must be YYYY-MM"}

    transactions = list_all_transactions(
        usecase_id=usecase,
        user_id=str(user_id),
        linked_account_id=linked_account_id,
    )
    budgets = list_monthly_budgets(
        usecase_id=usecase,
        user_id=str(user_id),
        linked_account_id=linked_account_id,
        limit=24,
        up_to_month=str(target_month),
    )
    result = suggest_budget(transactions=transactions, monthly_budgets=budgets, target_month=str(target_month))
    result["usecase_id"] = usecase
    result["user_id"] = str(user_id)
    result["linked_account_id"] = linked_account_id
    result["account_scope"] = "account" if linked_account_id else "portfolio"
    return result


@app.get("/finance/budget/suggest")
async def finance_budget_suggest_get(
    user_id: str,
    target_month: str,
    usecase_id: Optional[str] = Query(None),
    linked_account_id: Optional[str] = Query(None),
):
    payload = {
        "user_id": user_id,
        "target_month": target_month,
        "usecase_id": usecase_id,
        "linked_account_id": linked_account_id,
    }
    return await finance_budget_suggest(payload)


@app.post("/finance/goals/set")
async def finance_set_goal(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id") or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found

    user_id = payload.get("user_id")
    goal_amount = payload.get("goal_amount")
    target_months = payload.get("target_months")
    linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
    if not user_id:
        return {"success": False, "message": "user_id required"}
    if goal_amount is None:
        return {"success": False, "message": "goal_amount required"}
    if target_months is None:
        return {"success": False, "message": "target_months required"}

    try:
        goal = upsert_goal(
            usecase_id=usecase,
            user_id=str(user_id),
            linked_account_id=linked_account_id,
            goal_name=str(payload.get("goal_name") or "primary"),
            goal_amount=float(goal_amount),
            target_months=int(target_months),
            start_date=payload.get("start_date"),
            status=str(payload.get("status") or "active"),
        )
        return {
            "success": True,
            "usecase_id": usecase,
            "user_id": str(user_id),
            "linked_account_id": linked_account_id,
            "account_scope": "account" if linked_account_id else "portfolio",
            "goal": goal,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/finance/goals")
async def finance_get_goals(
    user_id: str,
    usecase_id: Optional[str] = Query(None),
    linked_account_id: Optional[str] = Query(None),
    status: Optional[str] = Query("active"),
):
    usecase = resolve_usecase_id(usecase_id or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    normalized_account_id = normalize_linked_account_id(linked_account_id)
    goals = list_goals_for_scope(
        usecase_id=usecase,
        user_id=user_id,
        linked_account_id=normalized_account_id,
        status=status,
    )
    return {
        "success": True,
        "usecase_id": usecase,
        "user_id": user_id,
        "linked_account_id": normalized_account_id,
        "account_scope": "account" if normalized_account_id else "portfolio",
        "count": len(goals),
        "goals": goals,
    }


@app.post("/finance/nudges/run")
async def finance_run_nudges(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id") or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    user_id = payload.get("user_id")
    linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
    if not user_id:
        return {"success": False, "message": "user_id required"}
    try:
        result = run_phase1_nudges(
            usecase_id=usecase,
            user_id=str(user_id),
            linked_account_id=linked_account_id,
        )
        return {
            "success": True,
            "usecase_id": usecase,
            "user_id": str(user_id),
            "linked_account_id": linked_account_id,
            "account_scope": "account" if linked_account_id else "portfolio",
            "result": result,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/finance/nudges")
async def finance_get_nudges(
    user_id: str,
    usecase_id: Optional[str] = Query(None),
    linked_account_id: Optional[str] = Query(None),
    include_acknowledged: bool = Query(False),
    limit: int = Query(50),
):
    usecase = resolve_usecase_id(usecase_id or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    normalized_account_id = normalize_linked_account_id(linked_account_id)
    rows = list_nudges(
        usecase_id=usecase,
        user_id=user_id,
        linked_account_id=normalized_account_id,
        include_acknowledged=include_acknowledged,
        limit=limit,
    )
    return {
        "success": True,
        "usecase_id": usecase,
        "user_id": user_id,
        "linked_account_id": normalized_account_id,
        "account_scope": "account" if normalized_account_id else "portfolio",
        "count": len(rows),
        "nudges": rows,
    }


@app.post("/finance/nudges/ack")
async def finance_ack_nudge(payload: dict = Body(...)):
    usecase = resolve_usecase_id(payload.get("usecase_id") or FINANCE_USECASE_ID)
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    user_id = payload.get("user_id")
    nudge_id = payload.get("nudge_id")
    linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
    if not user_id:
        return {"success": False, "message": "user_id required"}
    if nudge_id is None:
        return {"success": False, "message": "nudge_id required"}
    try:
        updated = acknowledge_nudge(
            usecase_id=usecase,
            user_id=str(user_id),
            nudge_id=int(nudge_id),
            linked_account_id=linked_account_id,
        )
        return {
            "success": updated,
            "usecase_id": usecase,
            "user_id": str(user_id),
            "linked_account_id": linked_account_id,
            "account_scope": "account" if linked_account_id else "portfolio",
            "nudge_id": int(nudge_id),
            "message": "acknowledged" if updated else "nudge not found",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}

# ---------------------------------------------------
@app.post("/rag/query")
async def rag_query(payload: dict = Body(...)):
    question = payload.get("question")
    if not question:
        return {"success": False, "message": "Question required"}
    usecase = resolve_usecase_id(payload.get("usecase_id"))
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    request_user_id = payload.get("user_id")
    linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
    if usecase == vector_store.normalize_usecase_id(FINANCE_USECASE_ID) and not request_user_id:
        return {"success": False, "message": "user_id required for financial-guide usecase"}
    quota = consume_daily_chat_quota(
        usecase_id=usecase,
        user_id=str(request_user_id or ""),
        chat_id=str(payload.get("chat_id") or ""),
    )
    if not quota.get("allowed", True):
        return chat_limit_response(usecase, quota)

    question_en, q_meta = normalize_text_to_english(question)
    if usecase == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
        user_id = request_user_id
        if not user_id:
            return {"success": False, "message": "user_id required for financial-guide usecase"}
        result = answer_finance_question(
            usecase_id=usecase,
            user_id=str(user_id),
            question=question_en,
            linked_account_id=linked_account_id,
        )
        user_answer, a_meta = back_translate_answer_if_needed(
            result.get("answer", ""),
            q_meta.get("source_language", "unknown"),
        )
        result["answer"] = user_answer
        effective_chat_id = str(payload.get("chat_id") or user_id)
        to_append = [
            {"role": "user", "content": question},
            {"role": "assistant", "content": user_answer},
        ]
        append_history_tail(usecase_id=usecase, chat_id=effective_chat_id, messages=to_append)
        append_global_chat_messages(usecase_id=usecase, chat_id=effective_chat_id, messages=to_append, user_id=str(user_id))
        maybe_autogenerate_chat_title(usecase_id=usecase, chat_id=effective_chat_id, first_user_message=question)
        append_chat_messages(
            usecase_id=usecase,
            user_id=str(user_id),
            chat_id=effective_chat_id,
            messages=to_append,
        )
        result["chat_id"] = effective_chat_id
        result["response_translated_from_english"] = bool(a_meta.get("translated", False))
        result["linked_account_id"] = linked_account_id
        result["account_scope"] = "account" if linked_account_id else "portfolio"
    else:
        result = query_rag(question_en, usecase_id=usecase)
        if result.get("success"):
            chunks = result.get("chunks") or []
            if not chunks:
                result["answer"] = out_of_context_message(usecase)
    if isinstance(result, dict):
        result["question_language"] = q_meta.get("source_language", "unknown")
        result["question_translated_to_english"] = bool(q_meta.get("translated", False))
    return result

@app.post("/rag/chat")
async def rag_chat(payload: dict = Body(...)):
    chat_id = payload.get("chat_id")
    question = payload.get("question")
    usecase = resolve_usecase_id(payload.get("usecase_id"))
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found

    if not chat_id:
        return {"success": False, "message": "chat_id required"}

    if not question:
        return {"success": False, "message": "question required"}

    try:
        request_user_id = payload.get("user_id")
        linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
        if usecase == vector_store.normalize_usecase_id(FINANCE_USECASE_ID) and not request_user_id:
            return {"success": False, "message": "user_id required for financial-guide usecase"}
        quota = consume_daily_chat_quota(
            usecase_id=usecase,
            user_id=str(request_user_id or ""),
            chat_id=str(chat_id or ""),
        )
        if not quota.get("allowed", True):
            return chat_limit_response(usecase, quota)
        with_audio = parse_with_audio(payload.get("with_audio"), default=True)
        question_en, q_meta = normalize_text_to_english(question)
        if usecase == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
            user_id = request_user_id
            if not user_id:
                return {"success": False, "message": "user_id required for financial-guide usecase"}
            finance_result = answer_finance_question(
                usecase_id=usecase,
                user_id=str(user_id),
                question=question_en,
                linked_account_id=linked_account_id,
            )
            user_answer, a_meta = back_translate_answer_if_needed(
                finance_result.get("answer", ""),
                q_meta.get("source_language", "unknown"),
            )
            user_answer = normalize_chatbot_answer(usecase, user_answer)
            to_append = [
                {"role": "user", "content": question},
                {"role": "assistant", "content": user_answer},
            ]
            append_history_tail(usecase_id=usecase, chat_id=str(chat_id), messages=to_append)
            append_global_chat_messages(usecase_id=usecase, chat_id=str(chat_id), messages=to_append, user_id=str(user_id))
            maybe_autogenerate_chat_title(usecase_id=usecase, chat_id=str(chat_id), first_user_message=question)
            append_chat_messages(
                usecase_id=usecase,
                user_id=str(user_id),
                chat_id=str(chat_id),
                messages=to_append,
            )
            audio = maybe_generate_chat_audio(user_answer, with_audio=with_audio)
            return {
                "success": True,
                "usecase_id": usecase,
                "chat_id": chat_id,
                "answer": user_answer,
                "audio": audio,
                "intent": finance_result.get("intent"),
                "data": finance_result.get("data"),
                "linked_account_id": linked_account_id,
                "account_scope": "account" if linked_account_id else "portfolio",
                "question_language": q_meta.get("source_language", "unknown"),
                "question_translated_to_english": bool(q_meta.get("translated", False)),
                "response_translated_from_english": bool(a_meta.get("translated", False)),
            }

        history = load_recent_history(usecase_id=usecase, chat_id=str(chat_id), limit=12)

        retrieved_chunks = vector_store.search(question_en, k=5, usecase_id=usecase)
        context = "\n".join([c.get("text", "") for c in retrieved_chunks])

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a retrieval-augmented assistant.\n"
                    "Behavior rules:\n"
                    "- If the user's message is ONLY a brief greeting (e.g., 'hi', 'hello') or a short expression of thanks (e.g., 'thanks', 'thank you'), reply politely and concisely (for example: 'Hello! How can I help?' or 'You're welcome!').\n"
                    "- For all other user questions, answer strictly using ONLY the provided context below.\n"
                    "- If the answer is not explicitly contained in the provided context, respond exactly with:\n"
                    f"\"{out_of_context_message(usecase)}\"\n"
                    "- Do NOT use prior knowledge. Do NOT guess or invent answers.\n"
                    "- Keep responses concise and on-topic."
                )
            }
        ] + history + [
            {
                "role": "user",
                "content": f"""
                Context:
                {context}

                Question:
                {question_en}
                """
            }
        ]

        r = requests.post(
            VLLM_URL,
            json={
                "model": MODEL_NAME,
                "messages": messages,
                "temperature": 0.2
            },
            timeout=120
        )

        if r.status_code != 200:
            return {"success": False, "message": r.text}

        answer = r.json()["choices"][0]["message"]["content"]
        answer = normalize_chatbot_answer(usecase, answer)
        user_answer, a_meta = back_translate_answer_if_needed(
            answer,
            q_meta.get("source_language", "unknown"),
        )

        to_append = [
            {"role": "user", "content": question},
            {"role": "assistant", "content": user_answer},
        ]
        append_history_tail(usecase_id=usecase, chat_id=str(chat_id), messages=to_append)
        append_global_chat_messages(
            usecase_id=usecase,
            chat_id=str(chat_id),
            messages=to_append,
            user_id=str(request_user_id or ""),
        )
        maybe_autogenerate_chat_title(usecase_id=usecase, chat_id=str(chat_id), first_user_message=question)
        audio = maybe_generate_chat_audio(user_answer, with_audio=with_audio)

        return {
            "success": True,
            "usecase_id": usecase,
            "chat_id": chat_id,
            "answer": user_answer,
            "audio": audio,
            "question_language": q_meta.get("source_language", "unknown"),
            "question_translated_to_english": bool(q_meta.get("translated", False)),
            "response_translated_from_english": bool(a_meta.get("translated", False)),
            # "sources": retrieved_chunks
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/rag/chat/stream")
async def rag_chat_stream(payload: dict = Body(...)):
    chat_id = payload.get("chat_id")
    question = payload.get("question")
    usecase = resolve_usecase_id(payload.get("usecase_id"))
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found

    if not chat_id:
        return {"success": False, "message": "chat_id required"}

    if not question:
        return {"success": False, "message": "question required"}
    with_audio = parse_with_audio(payload.get("with_audio"), default=True)
    question_en, q_meta = normalize_text_to_english(question)
    request_user_id = payload.get("user_id")
    linked_account_id = normalize_linked_account_id(payload.get("linked_account_id"))
    if usecase == vector_store.normalize_usecase_id(FINANCE_USECASE_ID) and not request_user_id:
        return {"success": False, "message": "user_id required for financial-guide usecase"}
    quota = consume_daily_chat_quota(
        usecase_id=usecase,
        user_id=str(request_user_id or ""),
        chat_id=str(chat_id or ""),
    )
    if not quota.get("allowed", True):
        return chat_limit_response(usecase, quota)

    async def event_generator():
        try:
            if usecase == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
                user_id = request_user_id
                if not user_id:
                    yield "data: ERROR: user_id required for financial-guide usecase\n\n"
                    return
                finance_result = answer_finance_question(
                    usecase_id=usecase,
                    user_id=str(user_id),
                    question=question_en,
                    linked_account_id=linked_account_id,
                )
                answer, _ = back_translate_answer_if_needed(
                    finance_result.get("answer", ""),
                    q_meta.get("source_language", "unknown"),
                )
                answer = normalize_chatbot_answer(usecase, answer)
                yield f"data: {answer}\n\n"
                to_append = [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ]
                append_history_tail(usecase_id=usecase, chat_id=str(chat_id), messages=to_append)
                append_global_chat_messages(usecase_id=usecase, chat_id=str(chat_id), messages=to_append, user_id=str(user_id))
                maybe_autogenerate_chat_title(usecase_id=usecase, chat_id=str(chat_id), first_user_message=question)
                append_chat_messages(
                    usecase_id=usecase,
                    user_id=str(user_id),
                    chat_id=str(chat_id),
                    messages=to_append,
                )
                if with_audio:
                    audio = maybe_generate_chat_audio(answer, with_audio=True)
                    yield f"event: audio\ndata: {json.dumps(audio)}\n\n"
                return

            history = load_recent_history(usecase_id=usecase, chat_id=str(chat_id), limit=12)

            retrieved_chunks = vector_store.search(question_en, k=5, usecase_id=usecase)
            context = "\n".join([c.get("text", "") for c in retrieved_chunks])

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a retrieval-augmented assistant.\n"
                        "Behavior rules:\n"
                        "- If the user's message is ONLY a brief greeting (e.g., 'hi', 'hello') or a short expression of thanks (e.g., 'thanks', 'thank you'), reply politely and concisely (for example: 'Hello! How can I help?' or 'You're welcome!').\n"
                        "- For all other user questions, answer strictly using ONLY the provided context below.\n"
                        "- If the answer is not explicitly contained in the provided context, respond exactly with:\n"
                        f"\"{out_of_context_message(usecase)}\"\n"
                        "- Do NOT use prior knowledge. Do NOT guess or invent answers.\n"
                        "- Keep responses concise and on-topic."
                    )
                }
            ] + history + [
                {
                    "role": "user",
                    "content": f"""
                    Context:
                    {context}

                    Question:
                    {question_en}
                    """
                }
            ]

            with requests.post(
                VLLM_URL,
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.2
                },
                stream=True,
                timeout=120
            ) as r:

                if r.status_code != 200:
                    yield f"data: ERROR: {r.text}\n\n"
                    return

                full_answer = ""

                for line in r.iter_lines():
                    if not line:
                        continue

                    decoded = line.decode("utf-8")

                    if decoded.startswith("data: "):
                        decoded = decoded.replace("data: ", "")

                    if decoded == "[DONE]":
                        break

                    try:
                        chunk = json.loads(decoded)
                        token = chunk["choices"][0]["delta"].get("content", "")
                        full_answer += token
                        if q_meta.get("source_language", "unknown") != "am":
                            yield f"data: {token}\n\n"
                    except Exception:
                        continue

                if q_meta.get("source_language", "unknown") == "am":
                    translated_answer, _ = back_translate_answer_if_needed(full_answer, "am")
                    full_answer = translated_answer
                    yield f"data: {translated_answer}\n\n"

                full_answer = normalize_chatbot_answer(usecase, full_answer)

            to_append = [
                {"role": "user", "content": question},
                {"role": "assistant", "content": full_answer},
            ]
            append_history_tail(usecase_id=usecase, chat_id=str(chat_id), messages=to_append)
            append_global_chat_messages(
                usecase_id=usecase,
                chat_id=str(chat_id),
                messages=to_append,
                user_id=str(payload.get("user_id") or ""),
            )
            maybe_autogenerate_chat_title(usecase_id=usecase, chat_id=str(chat_id), first_user_message=question)
            if with_audio:
                audio = maybe_generate_chat_audio(full_answer, with_audio=True)
                yield f"event: audio\ndata: {json.dumps(audio)}\n\n"

        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/rag/chat/history/{chat_id}")
async def rag_chat_history(
    chat_id: str,
    usecase_id: Optional[str] = Query(None),
    limit: int = Query(20),
    before_id: Optional[int] = Query(None),
):
    try:
        resolved = resolve_chat_usecase(chat_id=chat_id, usecase_id=usecase_id)
        if not resolved.get("ok"):
            return {"success": False, "message": resolved.get("error"), "candidates": resolved.get("candidates", [])}
        usecase = resolved["usecase_id"]
        resolved_chat = resolve_effective_chat_id(usecase_id=usecase, chat_id=chat_id)
        if not resolved_chat.get("ok"):
            return {"success": False, "message": resolved_chat.get("error"), "candidates": resolved_chat.get("candidates", [])}
        effective_chat_id = resolved_chat["chat_id"]
        not_found = ensure_usecase_registered(usecase)
        if not_found:
            return not_found
        page = get_global_chat_messages_page(
            usecase_id=usecase,
            chat_id=effective_chat_id,
            limit=limit,
            before_id=before_id,
        )
        history = page.get("messages", [])
        if not history and usecase == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
            history = get_chat_messages(usecase_id=usecase, chat_id=effective_chat_id)
            if before_id is not None:
                history = [m for m in history if int(m.get("id", 0) or 0) < before_id]
            history = history[-limit:]
            page = {"messages": history, "has_more": False, "next_before_id": None}
        if not history:
            return {
                "success": True,
                "usecase_id": usecase,
                "chat_id": effective_chat_id,
                "history": [],
                "has_more": False,
                "next_before_id": None,
            }

        return {
            "success": True,
            "usecase_id": usecase,
            "chat_id": effective_chat_id,
            "history": history,
            "has_more": page.get("has_more", False),
            "next_before_id": page.get("next_before_id"),
        }

    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/rag/chat/summary")
async def rag_chat_summary(payload: dict = Body(...)):
    chat_id = payload.get("chat_id")
    resolved = resolve_chat_usecase(chat_id=str(chat_id or ""), usecase_id=payload.get("usecase_id"))
    if not resolved.get("ok"):
        return {"success": False, "message": resolved.get("error"), "candidates": resolved.get("candidates", [])}
    usecase = resolved["usecase_id"]
    resolved_chat = resolve_effective_chat_id(usecase_id=usecase, chat_id=str(chat_id or ""))
    if not resolved_chat.get("ok"):
        return {"success": False, "message": resolved_chat.get("error"), "candidates": resolved_chat.get("candidates", [])}
    effective_chat_id = resolved_chat["chat_id"]
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found

    if not chat_id:
        return {"success": False, "message": "chat_id required"}

    try:
        history = load_best_history(usecase_id=usecase, chat_id=effective_chat_id)
        if not history:
            return {"success": False, "message": "No conversation found"}
        bounded_history = summary_history_window(history)
        transcript_lines = []
        for idx, item in enumerate(bounded_history, start=1):
            role = str(item.get("role", "unknown")).strip().upper()
            content = str(item.get("content", "")).strip()
            transcript_lines.append(f"{idx}. {role}: {content}")
        transcript = "\n".join(transcript_lines)

        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "Summarize the conversation briefly using the supplied transcript window only. "
                    "Cover the main user needs, decisions, and outcomes across the window. "
                    "Do not focus only on the last message."
                )
            },
            {
                "role": "user",
                "content": f"Conversation transcript:\n{transcript}",
            },
        ]

        response = requests.post(
            VLLM_URL,
            json={
                "model": MODEL_NAME,
                "messages": summary_prompt,
                "temperature": 0.3
            },
            timeout=60
        )

        if response.status_code != 200:
            return {"success": False, "message": response.text}

        summary = response.json()["choices"][0]["message"]["content"]

        return {
            "success": True,
            "usecase_id": usecase,
            "chat_id": effective_chat_id,
            "summary": summary
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


def _delete_chat_session(usecase: str, effective_chat_id: str) -> Dict:
    redis_client.delete(chat_history_key(usecase, effective_chat_id))
    delete_global_chat_messages(usecase_id=usecase, chat_id=effective_chat_id)
    if usecase == vector_store.normalize_usecase_id(FINANCE_USECASE_ID):
        delete_chat_messages(usecase_id=usecase, chat_id=effective_chat_id)
    return {
        "success": True,
        "usecase_id": usecase,
        "chat_id": effective_chat_id,
        "message": "Chat session and history deleted",
    }


@app.delete("/rag/chat/{chat_id}")
async def clear_chat(chat_id: str, usecase_id: Optional[str] = Query(None)):
    resolved = resolve_chat_usecase(chat_id=chat_id, usecase_id=usecase_id)
    if not resolved.get("ok"):
        return {"success": False, "message": resolved.get("error"), "candidates": resolved.get("candidates", [])}
    usecase = resolved["usecase_id"]
    resolved_chat = resolve_effective_chat_id(usecase_id=usecase, chat_id=chat_id)
    if not resolved_chat.get("ok"):
        return {"success": False, "message": resolved_chat.get("error"), "candidates": resolved_chat.get("candidates", [])}
    effective_chat_id = resolved_chat["chat_id"]
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    return _delete_chat_session(usecase=usecase, effective_chat_id=effective_chat_id)


@app.delete("/rag/chats/{chat_id}")
async def delete_chat_session(chat_id: str, usecase_id: Optional[str] = Query(None)):
    resolved = resolve_chat_usecase(chat_id=chat_id, usecase_id=usecase_id)
    if not resolved.get("ok"):
        return {"success": False, "message": resolved.get("error"), "candidates": resolved.get("candidates", [])}
    usecase = resolved["usecase_id"]
    resolved_chat = resolve_effective_chat_id(usecase_id=usecase, chat_id=chat_id)
    if not resolved_chat.get("ok"):
        return {"success": False, "message": resolved_chat.get("error"), "candidates": resolved_chat.get("candidates", [])}
    effective_chat_id = resolved_chat["chat_id"]
    not_found = ensure_usecase_registered(usecase)
    if not_found:
        return not_found
    return _delete_chat_session(usecase=usecase, effective_chat_id=effective_chat_id)

# ---------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
