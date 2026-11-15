"""Concurrent read load against a populated HydraDB node.

Each request is one of Taintline's two hot-path traversals (two-hop path to a
retraction, or the ranked frontier) for a random benchmark question.
Run after `python -m taintline.bench --hydra`:  PYTHONPATH=. python -m taintline.loadtest
"""
from __future__ import annotations

import argparse
import json
import random
import statistics as st
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .store import HydraStore
from .world import World

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--seconds", type=float, default=30)
    a = ap.parse_args()
    world = World.load(ROOT / "data/raw")
    store = HydraStore(pool=a.workers)
    qs = world.questions
    lat: list[float] = []
    errors = 0
    lock = threading.Lock()
    stop = time.perf_counter() + a.seconds

    def worker(seed: int) -> None:
        nonlocal errors
        rng = random.Random(seed)
        while time.perf_counter() < stop:
            q = rng.choice(qs)
            t = time.perf_counter()
            try:
                if rng.random() < 0.5:
                    store.taint_paths(q)
                else:
                    store.frontier(q)
                ok = True
            except Exception:
                ok = False
            dt = (time.perf_counter() - t) * 1000
            with lock:
                if ok:
                    lat.append(dt)
                else:
                    errors += 1

    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(worker, range(a.workers)))
    wall = time.perf_counter() - t0
    lat.sort()
    q = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))]
    # taint_paths issues 2 HTTP queries, frontier 1; count HTTP queries honestly
    out = {
        "workers": a.workers, "seconds": round(wall, 1), "operations": len(lat), "errors": errors,
        "queries": int(len(lat) * 1.5), "ops_per_s": round(len(lat) / wall, 1),
        "qps": round(len(lat) * 1.5 / wall, 1),
        "p50_ms": round(q(0.50), 2), "p95_ms": round(q(0.95), 2), "p99_ms": round(q(0.99), 2),
        "mean_ms": round(st.mean(lat), 2),
        "graph": "single local graph-node (release build), ~45k nodes / ~53k CITES edges, 8 vCPU box",
    }
    out["note"] = (f"{a.workers} concurrent clients for {out['seconds']}s on one local graph-node "
                   f"(~45k nodes, ~53k edges, 8 vCPU). Latency is per operation; a path check is 2 queries.")
    (ROOT / "results/load.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
