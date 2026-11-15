"""What each approach hands to an agent's context window, and its token cost."""
from __future__ import annotations

import json

import tiktoken

from .engine import Answer
from .world import World

_enc = tiktoken.get_encoding("cl100k_base")


def tokens(text: str) -> int:
    return len(_enc.encode(text))


def _t(world: World, i: int, n: int = 90) -> str:
    w = world.works.get(i)
    return (w.title[:n] if w and w.title else f"W{i}")


def taintline_context(world: World, a: Answer) -> str:
    """Compact, verifiable evidence: the shortest citation path to a retraction."""
    out: dict = {"paper": f"W{a.q}", "verdict": "tainted" if a.tainted else "no retracted ancestor found"}
    if a.direct:
        r = a.direct[0]
        out["path"] = [f"W{a.q}", f"W{r} RETRACTED: {_t(world, r)}"]
    elif a.two_hop:
        x, r = a.two_hop[0]
        out["path"] = [f"W{a.q}", f"W{x}: {_t(world, x)}", f"W{r} RETRACTED: {_t(world, r)}"]
    n = len(a.direct) + len(a.two_hop)
    if n > 1:
        out["more_paths"] = n - 1
    return json.dumps(out, ensure_ascii=False)


def vector_context(world: World, hits: list[tuple[int, float]]) -> str:
    parts = []
    for i, s in hits:
        w = world.works[i]
        flag = " [RETRACTED]" if w.retracted else ""
        parts.append(f"W{i}{flag} ({s:.2f}): {w.title}. {w.abstract}")
    return "\n\n".join(parts)
