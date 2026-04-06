import httpx
import os
import sys

cur_dir = os.getcwd()
parent_dir = os.path.realpath(os.path.join(os.path.dirname(cur_dir)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
    sys.path.append(cur_dir)
sys.path.insert(1, ".")

from app.config import VLLM_URL


async def ask_vllm(messages):

    payload = {
        "model": "Qwen/Qwen2.5-VL-7B-Instruct",
        "messages": messages
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(VLLM_URL, json=payload)

    r.raise_for_status()

    return r.json()["choices"][0]["message"]["content"]
