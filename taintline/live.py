"""Live mode: the same engine against the real OpenAlex API and a running HydraDB.

    PYTHONPATH=. python -m taintline.live W3088370573 [--budget 3] [--memory]

Set OPENALEX_API_KEY (free) for your own daily budget; without it OpenAlex shares a
small anonymous budget per IP. The graph is seeded with the snapshot's retraction
list and learns any `is_retracted` flag it sees while ingesting.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from .context import taintline_context
from .engine import Taintline
from .store import HydraStore, MemoryStore
from .world import Work, World, wid

API = "https://api.openalex.org/works"
ROOT = Path(__file__).resolve().parent.parent


class LiveWorld(World):
    """World whose fetch() calls OpenAlex. Fetched records are cached on disk."""

    def __init__(self, base: World, cache_dir: Path) -> None:
        super().__init__(works=dict(base.works), retracted=set(base.retracted), questions=[])
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, work_id: int) -> dict:
        path = self.cache_dir / f"W{work_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        params = {"select": "id,display_name,publication_year,is_retracted,referenced_works"}
        key = os.environ.get("OPENALEX_API_KEY")
        if key:
            params["api_key"] = key
        url = f"{API}/W{work_id}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "taintline (+https://github.com/demir-sama)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        path.write_text(json.dumps(data))
        return data

    def fetch(self, work_id: int) -> list[int]:
        self.fetches += 1
        try:
            d = self._get(work_id)
        except Exception:
            return []
        refs = [wid(x) for x in (d.get("referenced_works") or [])]
        self.works[work_id] = Work(work_id, d.get("display_name") or "", d.get("publication_year"),
                                   bool(d.get("is_retracted")), refs)
        if d.get("is_retracted"):
            self.retracted.add(work_id)
        return refs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("work", help="OpenAlex work id, e.g. W3088370573")
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--memory", action="store_true", help="use the in-memory store instead of HydraDB")
    a = ap.parse_args()
    q = wid(a.work)
    world = LiveWorld(World.load(ROOT / "data/raw"), ROOT / ".cache/openalex")
    store = MemoryStore() if a.memory else HydraStore()
    eng = Taintline.__new__(Taintline)
    # attach to an existing graph without wiping it: seed retractions idempotently
    eng.w, eng.s, eng.budget, eng.learn, eng.persist, eng.priority = world, store, a.budget, True, True, "degree"
    import random
    eng.rng, eng.fetched = random.Random(0), set()
    store.add_works({"id": r, "retracted": 1} for r in sorted(world.retracted))
    ans = eng.answer(q)
    print(taintline_context(world, ans))
    print(f"# reference lists read: {ans.fetches}")


if __name__ == "__main__":
    main()
