"""Taintline's agent loop: budgeted, gap-driven ingestion with priorities learned
from its own verdicts.

For a question paper q the engine
  1. ingests q's reference list (one fetch),
  2. asks the graph for a path q -> retracted or q -> x -> retracted,
  3. if none, expands the most promising unfetched reference (one fetch) and asks
     again, up to `budget` expansions,
  4. writes its verdict back onto q. Future frontiers are ranked by the verdicts of
     the papers that cite each candidate, so the graph's own answers steer what it
     ingests next.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .store import Store
from .world import World

TAINTED, CLEAN = 3, 0  # verdict weights written to the graph (a miss is not evidence of cleanliness)


@dataclass
class Answer:
    q: int
    tainted: bool
    direct: list[int]
    two_hop: list[tuple[int, int]]
    fetches: int
    expansions: int
    order: list[int] = field(default_factory=list)


class Taintline:
    def __init__(self, world: World, store: Store, *, budget: int = 3,
                 learn: bool = True, persist: bool = True, priority: str = "degree",
                 seed: int = 0) -> None:
        if priority not in {"verdict", "degree", "random"}:
            raise ValueError(priority)
        self.w, self.s = world, store
        self.budget, self.learn, self.persist, self.priority = budget, learn, persist, priority
        self.rng = random.Random(seed)
        self.fetched: set[int] = set()
        self._boot()

    def _boot(self) -> None:
        """Seed the graph with the public retraction list (Retraction Watch via OpenAlex)."""
        self.s.reset()
        self.fetched.clear()
        self.s.add_works({"id": r, "retracted": 1} for r in sorted(self.w.retracted))

    def ingest(self, wid: int) -> None:
        if wid in self.fetched:
            return
        refs = self.w.fetch(wid)
        rows = [{"id": wid, "retracted": int(wid in self.w.retracted)}]
        rows += [{"id": r, "retracted": int(r in self.w.retracted)} for r in refs]
        self.s.add_works(rows)
        self.s.add_cites(wid, refs)
        self.s.mark_fetched(wid)
        self.fetched.add(wid)

    def _pick(self, frontier: list[tuple[int, int, int]]) -> int:
        if self.priority == "random":
            return self.rng.choice(frontier)[0]
        jitter = {x: self.rng.random() for x, _, _ in frontier}
        if self.priority == "degree":
            # how many papers this graph has already ingested cite the candidate
            return max(frontier, key=lambda t: (t[2], jitter[t[0]]))[0]
        # verdict: degree plus the verdict mass of those citers (+3 per citer this
        # graph already judged tainted). Kept as an ablation; see README.
        return max(frontier, key=lambda t: (t[1] + t[2], jitter[t[0]]))[0]

    def answer(self, q: int) -> Answer:
        if not self.persist:
            self._boot()
        start = self.w.fetches
        self.ingest(q)
        direct, two = self.s.taint_paths(q)
        spent, order = 0, []
        while not (direct or two) and spent < self.budget:
            frontier = self.s.frontier(q)
            if not frontier:
                break
            x = self._pick(frontier)
            order.append(x)
            self.ingest(x)
            spent += 1
            direct, two = self.s.taint_paths(q)
        tainted = bool(direct or two)
        if self.learn:
            self.s.set_verdict(q, TAINTED if tainted else CLEAN)
        return Answer(q, tainted, direct, two, self.w.fetches - start, spent, order)


def exhaustive(world: World, q: int) -> Answer:
    """The no-budget crawl: fetch q and every reference. Correct by construction, costly."""
    start = world.fetches
    refs = world.fetch(q)
    direct = sorted(r for r in refs if r in world.retracted)
    two = []
    for x in refs:
        if x in world.retracted:
            continue
        for r in world.fetch(x):
            if r in world.retracted:
                two.append((x, r))
    return Answer(q, bool(direct or two), direct, sorted(two), world.fetches - start, len(refs))
