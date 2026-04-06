import os
import sys
import traceback
import uuid
from pathlib import Path

cur_dir = os.getcwd()
parent_dir = os.path.realpath(os.path.join(os.path.dirname(cur_dir)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
    sys.path.append(cur_dir)
sys.path.insert(1, ".")

# app/rag_pipeline.py

from app.vectorstore import vector_store
from app.utils import extract_text_from_upload, extract_text_from_path, chunk_text, clean_text
from app.translation import normalize_text_to_english


# -----------------------------
# INGEST DOCUMENT
# -----------------------------
def ingest_document(file, usecase_id: str | None = None) -> dict:
    """
    Extract → Chunk → Embed → Store
    """
    try:
        raw_text = extract_text_from_upload(file)
        text_en, lang_meta = normalize_text_to_english(raw_text)
        text = clean_text(text_en)

        if not text.strip():
            return {"success": False, "message": "Empty document"}

        doc_id = str(uuid.uuid4())
        filename = file.filename or f"{doc_id}.txt"

        chunks = chunk_text(text)
        chunk_ids = [f"{doc_id}:{idx}" for idx in range(len(chunks))]

        resolved_usecase = vector_store.normalize_usecase_id(usecase_id)
        metadatas = [
            {
                "doc_id": doc_id,
                "usecase_id": resolved_usecase,
                "source_language": lang_meta.get("source_language", "unknown"),
                "translated_to_english": bool(lang_meta.get("translated", False)),
                "filename": filename,
                "source_path": "",
                "chunk_index": idx,
            }
            for idx, _ in enumerate(chunks)
        ]

        vector_store.add_documents(
            chunks=chunks,
            metadatas=metadatas,
            ids=chunk_ids,
            usecase_id=resolved_usecase,
        )

        return {
            "success": True,
            "doc_id": doc_id,
            "usecase_id": resolved_usecase,
            "source_language": lang_meta.get("source_language", "unknown"),
            "translated_to_english": bool(lang_meta.get("translated", False)),
            "filename": filename,
            "chunks_indexed": len(chunks)
        }

    except Exception as e:
        return {
        "success": False,
        "message": repr(e),   # shows real error type
        "trace": traceback.format_exc()
    }


def ingest_document_path(path: str, usecase_id: str | None = None) -> dict:
    try:
        raw_text = extract_text_from_path(path)
        text_en, lang_meta = normalize_text_to_english(raw_text)
        text = clean_text(text_en)
        if not text:
            return {"success": False, "message": "Empty document"}

        doc_id = str(uuid.uuid4())
        filename = Path(path).name
        chunks = chunk_text(text)
        chunk_ids = [f"{doc_id}:{idx}" for idx in range(len(chunks))]

        resolved_usecase = vector_store.normalize_usecase_id(usecase_id)
        metadatas = [
            {
                "doc_id": doc_id,
                "usecase_id": resolved_usecase,
                "source_language": lang_meta.get("source_language", "unknown"),
                "translated_to_english": bool(lang_meta.get("translated", False)),
                "filename": filename,
                "source_path": str(Path(path).resolve()),
                "chunk_index": idx,
            }
            for idx, _ in enumerate(chunks)
        ]

        vector_store.add_documents(
            chunks=chunks,
            metadatas=metadatas,
            ids=chunk_ids,
            usecase_id=resolved_usecase,
        )
        return {
            "success": True,
            "doc_id": doc_id,
            "usecase_id": resolved_usecase,
            "source_language": lang_meta.get("source_language", "unknown"),
            "translated_to_english": bool(lang_meta.get("translated", False)),
            "filename": filename,
            "source_path": str(Path(path).resolve()),
            "chunks_indexed": len(chunks),
        }
    except Exception as e:
        return {
            "success": False,
            "message": repr(e),
            "trace": traceback.format_exc(),
        }



# -----------------------------
# DELETE DOCUMENT
# -----------------------------
def delete_document(doc_id: str, usecase_id: str | None = None) -> dict:
    try:
        deleted = vector_store.delete_document(doc_id, usecase_id=usecase_id)
        if not deleted:
            return {"success": False, "message": "Document not found"}
        return {"success": True, "usecase_id": vector_store.normalize_usecase_id(usecase_id)}
    except Exception as e:
        return {"success": False, "message": str(e)}


# -----------------------------
# QUERY RAG
# -----------------------------

def query_rag(question: str, top_k: int = 3, usecase_id: str | None = None) -> dict:
    try:
        resolved_usecase = vector_store.normalize_usecase_id(usecase_id)
        docs = vector_store.retriever(k=top_k, usecase_id=resolved_usecase).invoke(question)
        retrieved_chunks = []
        for doc in docs:
            meta = dict(doc.metadata or {})
            meta["text"] = doc.page_content
            retrieved_chunks.append(meta)

        context = "\n".join([
            chunk.get("text", "") for chunk in retrieved_chunks
        ])

        return {
            "success": True,
            "usecase_id": resolved_usecase,
            "context": context,
            "chunks": retrieved_chunks
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }
