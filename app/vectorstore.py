import os
import re
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from langchain_chroma import Chroma
from chromadb.config import Settings
from langchain_core.embeddings import Embeddings

from app.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_ANONYMIZED_TELEMETRY,
    CHROMA_PERSIST_DIR,
    DEFAULT_USECASE_ID,
    EMBEDDING_MODEL,
    USECASE_REGISTRY_PATH,
)


class LazyHuggingFaceEmbeddings(Embeddings):
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._backend: Any = None

    def _get_backend(self):
        if self._backend is None:
            from langchain_huggingface import HuggingFaceEmbeddings
            self._backend = HuggingFaceEmbeddings(model_name=self.model_name)
        return self._backend

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._get_backend().embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._get_backend().embed_query(text)


class VectorStore:
    def __init__(self):
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        self.embedding_fn = LazyHuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        self._stores: Dict[str, Chroma] = {}
        os.makedirs(os.path.dirname(USECASE_REGISTRY_PATH), exist_ok=True)
        self._usecases = self._load_usecases()
        self._bootstrap_usecases_from_disk()
        if DEFAULT_USECASE_ID not in self._usecases:
            self.register_usecase(DEFAULT_USECASE_ID, name="Default")

    def normalize_usecase_id(self, usecase_id: str | None) -> str:
        value = (usecase_id or DEFAULT_USECASE_ID).strip().lower()
        value = re.sub(r"[^a-z0-9_-]+", "-", value)
        value = re.sub(r"-{2,}", "-", value).strip("-")
        return value or DEFAULT_USECASE_ID

    def _load_usecases(self) -> Dict[str, Dict]:
        if not os.path.exists(USECASE_REGISTRY_PATH):
            return {}
        try:
            with open(USECASE_REGISTRY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save_usecases(self):
        with open(USECASE_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(self._usecases, f, indent=2, sort_keys=True)

    def _bootstrap_usecases_from_disk(self):
        if not os.path.isdir(CHROMA_PERSIST_DIR):
            return
        changed = False
        for name in os.listdir(CHROMA_PERSIST_DIR):
            path = os.path.join(CHROMA_PERSIST_DIR, name)
            if not os.path.isdir(path):
                continue
            normalized = self.normalize_usecase_id(name)
            if normalized not in self._usecases:
                self._usecases[normalized] = {
                    "id": normalized,
                    "name": normalized,
                    "description": "",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                changed = True
        if changed:
            self._save_usecases()

    def usecase_exists(self, usecase_id: str | None) -> bool:
        normalized = self.normalize_usecase_id(usecase_id)
        return normalized in self._usecases

    def register_usecase(self, usecase_id: str, name: str = "", description: str = "") -> Dict:
        normalized = self.normalize_usecase_id(usecase_id)
        existing = self._usecases.get(normalized)
        if existing:
            updated = dict(existing)
            if name:
                updated["name"] = name
            if description:
                updated["description"] = description
            self._usecases[normalized] = updated
        else:
            self._usecases[normalized] = {
                "id": normalized,
                "name": name or normalized,
                "description": description or "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            os.makedirs(os.path.join(CHROMA_PERSIST_DIR, normalized), exist_ok=True)
        self._save_usecases()
        return self._usecases[normalized]

    def get_usecase(self, usecase_id: str | None) -> Dict | None:
        normalized = self.normalize_usecase_id(usecase_id)
        return self._usecases.get(normalized)

    def delete_usecase(self, usecase_id: str) -> bool:
        normalized = self.normalize_usecase_id(usecase_id)
        if normalized == DEFAULT_USECASE_ID:
            raise ValueError(f"Cannot delete default usecase '{DEFAULT_USECASE_ID}'.")
        if normalized not in self._usecases:
            return False

        if normalized in self._stores:
            del self._stores[normalized]

        usecase_dir = os.path.join(CHROMA_PERSIST_DIR, normalized)
        if os.path.isdir(usecase_dir):
            shutil.rmtree(usecase_dir)

        del self._usecases[normalized]
        self._save_usecases()
        return True

    def _store_for(self, usecase_id: str | None) -> Chroma:
        normalized = self.normalize_usecase_id(usecase_id)
        if normalized not in self._usecases:
            raise ValueError(
                f"Usecase '{normalized}' is not registered. "
                "Create it first using POST /rag/usecases/register."
            )
        if normalized in self._stores:
            return self._stores[normalized]

        persist_dir = os.path.join(CHROMA_PERSIST_DIR, normalized)
        os.makedirs(persist_dir, exist_ok=True)
        collection_name = f"{CHROMA_COLLECTION_NAME}_{normalized}"
        store = Chroma(
            collection_name=collection_name,
            embedding_function=self.embedding_fn,
            persist_directory=persist_dir,
            client_settings=Settings(
                is_persistent=True,
                persist_directory=persist_dir,
                anonymized_telemetry=CHROMA_ANONYMIZED_TELEMETRY,
            ),
        )
        self._stores[normalized] = store
        return store

    def _sanitize_metadata(self, metadata: Dict) -> Dict:
        cleaned: Dict = {}
        for key, value in (metadata or {}).items():
            if value is None:
                cleaned[key] = ""
            elif isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            else:
                cleaned[key] = str(value)
        return cleaned

    def add_documents(
        self,
        chunks: List[str],
        metadatas: List[Dict],
        ids: List[str],
        usecase_id: str | None = None,
    ):
        store = self._store_for(usecase_id)
        safe_metadatas = [self._sanitize_metadata(m) for m in metadatas]
        store.add_texts(texts=chunks, metadatas=safe_metadatas, ids=ids)

    def search(self, query: str, k: int = 5, usecase_id: str | None = None) -> List[Dict]:
        docs = self._store_for(usecase_id).as_retriever(search_kwargs={"k": k}).invoke(query)
        results = []
        for doc in docs:
            meta = dict(doc.metadata or {})
            meta["text"] = doc.page_content
            results.append(meta)
        return results

    def retriever(self, k: int = 5, usecase_id: str | None = None):
        return self._store_for(usecase_id).as_retriever(search_kwargs={"k": k})

    def delete_document(self, doc_id: str, usecase_id: str | None = None) -> bool:
        store = self._store_for(usecase_id)
        payload = store.get(where={"doc_id": doc_id})
        ids = payload.get("ids") or []
        if not ids:
            return False
        store.delete(ids=ids)
        return True

    def list_documents(self, usecase_id: str | None = None) -> List[Dict]:
        normalized = self.normalize_usecase_id(usecase_id)
        payload = self._store_for(normalized).get(include=["metadatas"])
        metadatas = payload.get("metadatas") or []
        grouped = defaultdict(lambda: {"chunk_count": 0})

        for meta in metadatas:
            meta = meta or {}
            doc_id = meta.get("doc_id")
            if not doc_id:
                continue

            grouped[doc_id]["id"] = doc_id
            grouped[doc_id]["filename"] = meta.get("filename", "unknown")
            grouped[doc_id]["source_path"] = meta.get("source_path", "")
            grouped[doc_id]["usecase_id"] = normalized
            grouped[doc_id]["chunk_count"] += 1

        return sorted(grouped.values(), key=lambda d: (d.get("filename") or "", d["id"]))

    def reset(self, usecase_id: str | None = None):
        if usecase_id:
            store = self._store_for(usecase_id)
            payload = store.get()
            ids = payload.get("ids") or []
            if ids:
                store.delete(ids=ids)
            return

        for current_id in self.list_usecases():
            store = self._store_for(current_id["id"])
            payload = store.get()
            ids = payload.get("ids") or []
            if ids:
                store.delete(ids=ids)

    def compact(self):
        # Chroma handles storage compaction internally.
        return

    def vector_count(self, usecase_id: str | None = None) -> int:
        return self._store_for(usecase_id)._collection.count()

    def list_usecases(self) -> List[Dict]:
        return sorted(self._usecases.values(), key=lambda u: u["id"])


vector_store = VectorStore()
