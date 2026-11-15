"""The citation 'world': a frozen OpenAlex snapshot that stands in for the live API.

Every fetch against the world is counted, so the benchmark measures how much
ingestion each strategy pays for its answers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

RAW_FILES = ["retracted", "c1_0", "c1_1", "q_0", "q_1", "q_2", "controls"]
QUESTION_FILES = ["q_0", "q_1", "q_2", "controls"]


def wid(url_or_id: str) -> int:
    """'https://openalex.org/W3010930696' -> 3010930696 (HydraDB ids are integers)."""
    s = url_or_id.rsplit("/", 1)[-1]
    if not s or s[0] not in "Ww" or not s[1:].isdigit():
        raise ValueError(f"not an OpenAlex work id: {url_or_id!r}")
    return int(s[1:])


def abstract_text(inv: dict | None) -> str:
    if not inv:
        return ""
    pos: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            pos.append((i, word))
    return " ".join(w for _, w in sorted(pos))


@dataclass
class Work:
    id: int
    title: str
    year: int | None
    retracted: bool
    refs: list[int]
    abstract: str = ""
    venue: str = ""


@dataclass
class World:
    works: dict[int, Work]
    retracted: set[int]
    questions: list[int]
    fetches: int = 0
    _fetched_log: list[int] = field(default_factory=list)

    @classmethod
    def load(cls, raw_dir: Path) -> "World":
        works: dict[int, Work] = {}
        qids: list[int] = []
        for name in RAW_FILES:
            data = json.loads((raw_dir / f"{name}.json").read_text())
            for r in data["results"]:
                i = wid(r["id"])
                loc = (r.get("primary_location") or {}).get("source") or {}
                works[i] = Work(
                    id=i,
                    title=(r.get("display_name") or "").strip(),
                    year=r.get("publication_year"),
                    retracted=bool(r.get("is_retracted")),
                    refs=[wid(x) for x in (r.get("referenced_works") or [])],
                    abstract=abstract_text(r.get("abstract_inverted_index")),
                    venue=loc.get("display_name") or "",
                )
                if name in QUESTION_FILES:
                    qids.append(i)
        retracted = {i for i, w in works.items() if w.retracted}
        questions = [q for q in dict.fromkeys(qids) if q not in retracted]
        return cls(works=works, retracted=retracted, questions=questions)

    # -- the only way a strategy may learn a paper's references --------------
    def fetch(self, work_id: int) -> list[int]:
        """Simulated OpenAlex GET /works/{id}: returns reference ids, costs 1."""
        self.fetches += 1
        self._fetched_log.append(work_id)
        w = self.works.get(work_id)
        return list(w.refs) if w else []

    def reset_meter(self) -> None:
        self.fetches = 0
        self._fetched_log.clear()

    # -- ground truth (never visible to strategies) -----------------------------
    def truth(self, q: int) -> tuple[set[int], set[tuple[int, int]]]:
        """Return (direct retracted refs, {(bridge, retracted)}) within the snapshot."""
        refs = self.works[q].refs
        direct = {r for r in refs if r in self.retracted}
        two: set[tuple[int, int]] = set()
        for x in refs:
            wx = self.works.get(x)
            if wx is None or x in self.retracted:
                continue
            for r in wx.refs:
                if r in self.retracted:
                    two.add((x, r))
        return direct, two

    def is_tainted(self, q: int) -> bool:
        d, t = self.truth(q)
        return bool(d or t)
