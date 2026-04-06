import pickle
from typing import List, Dict
import os
import sys

cur_dir = os.getcwd()
parent_dir = os.path.realpath(os.path.join(os.path.dirname(cur_dir)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
    sys.path.append(cur_dir)
sys.path.insert(1, ".")

from app.redis_client import redis_client
from app.config import DEFAULT_USECASE_ID


def _chat_key(chat_id: str, usecase_id: str = DEFAULT_USECASE_ID) -> str:
    return f"chat:{usecase_id}:{chat_id}"


def load_chat_memory(chat_id: str, usecase_id: str = DEFAULT_USECASE_ID) -> List[Dict]:
    key = _chat_key(chat_id, usecase_id)
    data = redis_client.get(key)

    if data:
        return pickle.loads(data)
    return []


def save_chat_memory(chat_id: str, history: List[Dict], usecase_id: str = DEFAULT_USECASE_ID):
    key = _chat_key(chat_id, usecase_id)
    redis_client.set(key, pickle.dumps(history))


def clear_chat_memory(chat_id: str, usecase_id: str = DEFAULT_USECASE_ID):
    redis_client.delete(_chat_key(chat_id, usecase_id))
