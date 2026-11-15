"""Vector-store baseline: embed every paper (title + abstract) and retrieve top-k.

A RAG agent asked "does this paper rest on retracted work?" gets the k nearest
papers. We count it as flagging contamination when a retracted paper is among
them, and as *correct evidence* only when that retracted paper is actually in the
question's citation chain.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .world import World

MODEL = "BAAI/bge-small-en-v1.5"


def doc_text(w) -> str:
    return (w.title + ". " + w.abstract).strip() or f"W{w.id}"


class VectorIndex:
    def __init__(self, world: World, cache: Path) -> None:
        self.ids = sorted(world.works)
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            z = np.load(cache)
            if list(z["ids"]) == self.ids:
                self.emb = z["emb"]
                return
        from fastembed import TextEmbedding
        model = TextEmbedding(MODEL)
        texts = [doc_text(world.works[i])[:2000] for i in self.ids]
        emb = np.array(list(model.embed(texts, batch_size=32)), dtype=np.float32)
        emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
        np.savez(cache, ids=np.array(self.ids), emb=emb)
        self.emb = emb

    def topk(self, q: int, k: int = 5) -> list[tuple[int, float]]:
        if not hasattr(self, "_pos"):
            self._pos = {i: n for n, i in enumerate(self.ids)}
        qi = self._pos[q]
        sims = self.emb @ self.emb[qi]
        sims[qi] = -1
        top = np.argsort(-sims)[:k]
        return [(self.ids[t], float(sims[t])) for t in top]
