import hashlib
import pickle
import os
import sys

cur_dir = os.getcwd()
parent_dir = os.path.realpath(os.path.join(os.path.dirname(cur_dir)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
    sys.path.append(cur_dir)
sys.path.insert(1, ".")

from app.redis_client import redis_client
from app.config import CACHE_TTL_SECONDS


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def get_cached_embedding(text: str):
    key = f"embed:{_hash_text(text)}"
    data = redis_client.get(key)

    if data:
        return pickle.loads(data)
    return None


def cache_embedding(text: str, embedding):
    key = f"embed:{_hash_text(text)}"
    redis_client.setex(key, CACHE_TTL_SECONDS, pickle.dumps(embedding))
