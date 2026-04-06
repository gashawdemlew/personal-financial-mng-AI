# app/embeddings.py
from sentence_transformers import SentenceTransformer
import os
import sys
import numpy as np

cur_dir = os.getcwd()
parent_dir = os.path.realpath(os.path.join(os.path.dirname(cur_dir)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
    sys.path.append(cur_dir)
sys.path.insert(1, ".")

from app.config import EMBEDDING_MODEL
from app.cache import get_cached_embedding, cache_embedding

model = SentenceTransformer(EMBEDDING_MODEL)

def embed_text(texts):
    """
    texts: str or List[str]
    Returns embeddings as List[List[float]]
    """
    # if single string, wrap as list
    single_input = False
    if isinstance(texts, str):
        texts = [texts]
        single_input = True

    embeddings = []
    uncached_texts = []
    uncached_indices = []

    # Check cache for each chunk
    for i, t in enumerate(texts):
        cached = get_cached_embedding(t)
        if cached is not None:
            embeddings.append(cached)
        else:
            embeddings.append(None)
            uncached_texts.append(t)
            uncached_indices.append(i)

    # Embed uncached texts
    if uncached_texts:
        new_embeddings = model.encode(uncached_texts).tolist()
        # Save in cache & fill embeddings
        for idx, emb in zip(uncached_indices, new_embeddings):
            embeddings[idx] = emb
            cache_embedding(uncached_texts[uncached_indices.index(idx)], emb)

    if single_input:
        return embeddings[0]  # return single embedding if input was str
    return embeddings

