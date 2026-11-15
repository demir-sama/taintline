"""Reproducible benchmark. Run: PYTHONPATH=. python -m taintline.bench [--hydra]"""
from __future__ import annotations

import argparse
import json
import random
import statistics as st
import time
from pathlib import Path

from .context import taintline_context, tokens, vector_context
from .engine import Taintline, exhaustive
from .store import HydraStore, MemoryStore
from .world import World

ROOT = Path(__file__).resolve().parent.parent
ROUND = 100
SEEDS = [0, 1, 2, 3, 4]
BUDGET = 3

STRATEGIES = {
    "cold": dict(persist=False, learn=False, priority="random"),
    "memory_random": dict(learn=False, priority="random"),
    "taintline": dict(),
    "taintline_verdict": dict(priority="verdict"),
}


def order(world: World, seed: int) -> list[int]:
    qs = list(world.questions)
    random.Random(seed).shuffle(qs)
    return qs


def curve(correct: list[bool]) -> list[float]:
    return [round(sum(correct[i:i + ROUND]) / len(correct[i:i + ROUND]), 4)
            for i in range(0, len(correct), ROUND)]


def run_strategy(world, store, seed, budget=BUDGET, **kw):
    world.reset_meter()
    eng = Taintline(world, store, budget=budget, seed=seed, **kw)
    answers = []
    t0 = time.perf_counter()
    for q in order(world, seed):
        answers.append(eng.answer(q))
    return answers, time.perf_counter() - t0, world.fetches


def score(world, answers):
    truth = [world.is_tainted(a.q) for a in answers]
    pred = [a.tainted for a in answers]
    tp = sum(p and t for p, t in zip(pred, truth))
    fp = sum(p and not t for p, t in zip(pred, truth))
    fn = sum(t and not p for p, t in zip(pred, truth))
    correct = [p == t for p, t in zip(pred, truth)]
    return {
        "accuracy": round(sum(correct) / len(correct), 4),
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "curve": curve(correct),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hydra", action="store_true", help="also run Taintline on a live HydraDB node")
    args = ap.parse_args()
    world = World.load(ROOT / "data/raw")
    n_t = sum(world.is_tainted(q) for q in world.questions)
    out: dict = {
        "dataset": {
            "works": len(world.works), "retracted": len(world.retracted),
            "questions": len(world.questions), "tainted_questions": n_t,
            "clean_questions": len(world.questions) - n_t,
            "edges": sum(len(w.refs) for w in world.works.values()),
            "source": "OpenAlex snapshot fetched 2026-11-15 (CC0)",
        },
        "budget": BUDGET, "round_size": ROUND, "seeds": SEEDS,
    }

    # --- graph strategies (MemoryStore: same semantics, fast, used for ablations)
    strat = {}
    for name, kw in STRATEGIES.items():
        runs = []
        for s in SEEDS:
            answers, secs, fetches = run_strategy(world, MemoryStore(), s, **kw)
            r = score(world, answers)
            r["fetches_per_q"] = round(fetches / len(answers), 3)
            runs.append(r)
        curves = list(zip(*[r["curve"] for r in runs]))
        strat[name] = {
            "accuracy_mean": round(st.mean(r["accuracy"] for r in runs), 4),
            "accuracy_min": min(r["accuracy"] for r in runs),
            "accuracy_max": max(r["accuracy"] for r in runs),
            "recall_mean": round(st.mean(r["recall"] for r in runs), 4),
            "precision_min": min(r["precision"] for r in runs if r["precision"] is not None),
            "fetches_per_q": round(st.mean(r["fetches_per_q"] for r in runs), 3),
            "curve_mean": [round(st.mean(c), 4) for c in curves],
            "curve_min": [min(c) for c in curves],
            "curve_max": [max(c) for c in curves],
        }
        print(name, strat[name]["accuracy_mean"], strat[name]["curve_mean"], flush=True)
    out["strategies"] = strat

    # --- budget sweep
    sweep = []
    for b in [0, 1, 2, 3, 4, 6, 8]:
        answers, _, fetches = run_strategy(world, MemoryStore(), 0, budget=b)
        r = score(world, answers)
        sweep.append({"budget": b, "accuracy": r["accuracy"], "last_round": r["curve"][-1],
                      "fetches_per_q": round(fetches / len(answers), 3)})
    out["budget_sweep"] = sweep

    # --- exhaustive crawl (correct by construction)
    world.reset_meter()
    for q in world.questions:
        exhaustive(world, q)
    out["exhaustive"] = {"accuracy": 1.0, "fetches_per_q": round(world.fetches / len(world.questions), 2)}

    # --- vector baseline
    from .vector import VectorIndex
    idx = VectorIndex(world, ROOT / "data/emb.npz")
    vec = {}
    tl_answers, _, _ = run_strategy(world, MemoryStore(), 0)
    by_q = {a.q: a for a in tl_answers}
    for k in [5, 10]:
        correct, ev_ok, flagged, tok, tl_tok = [], 0, 0, [], []
        tp = fp = fn = 0
        for q in world.questions:
            hits = idx.topk(q, k)
            d, two = world.truth(q)
            chain = d | {r for _, r in two}
            ret = [h for h, _ in hits if h in world.retracted]
            pred, truth = bool(ret), bool(chain)
            correct.append(pred == truth)
            tp += pred and truth; fp += pred and not truth; fn += truth and not pred
            if ret:
                flagged += 1
                ev_ok += any(h in chain for h in ret)
            tok.append(tokens(vector_context(world, hits)))
            tl_tok.append(tokens(taintline_context(world, by_q[q])))
        vec[f"top{k}"] = {
            "accuracy": round(sum(correct) / len(correct), 4),
            "recall": round(tp / (tp + fn), 4), "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "evidence_correct_when_flagged": round(ev_ok / flagged, 4) if flagged else None,
            "tokens_mean": round(st.mean(tok), 1),
        }
        print("vector", k, vec[f"top{k}"], flush=True)
    out["vector"] = vec
    out["always_tainted"] = {"accuracy": round(n_t / len(world.questions), 4), "recall": 1.0,
                             "precision": round(n_t / len(world.questions), 4)}
    out["taintline_tokens_mean"] = round(st.mean(tl_tok), 1)

    # --- live HydraDB run + parity with the in-memory reference
    if args.hydra:
        store = HydraStore()
        answers, secs, fetches = run_strategy(world, store, 0)
        r = score(world, answers)
        ref = {a.q: (a.tainted, a.direct, a.two_hop) for a in tl_answers}
        mismatch = sum(ref[a.q] != (a.tainted, a.direct, a.two_hop) for a in answers)
        out["hydra_run"] = {**r, "seconds": round(secs, 1), "questions": len(answers),
                            "fetches_per_q": round(fetches / len(answers), 3),
                            "parity_mismatches_vs_memory": mismatch,
                            "graph": store.counts()}
        print("hydra", out["hydra_run"], flush=True)
        # export answers for the UI
        rows = []
        for i, a in enumerate(answers):
            w = world.works[a.q]
            d, two = world.truth(a.q)
            rows.append({
                "q": a.q, "title": w.title, "year": w.year, "venue": w.venue, "round": i // ROUND + 1,
                "tainted": a.tainted, "truth": bool(d or two), "fetches": a.fetches,
                "context": taintline_context(world, a),
                "vector_top5": [{"id": h, "s": round(s, 3), "title": world.works[h].title,
                                  "retracted": h in world.retracted} for h, s in idx.topk(a.q, 5)],
                "path": ([[a.q, a.direct[0]]] if a.direct else [[a.q, *a.two_hop[0]]] if a.two_hop else []),
                "ctx_tokens": tokens(taintline_context(world, a)),
                "vec_tokens": tokens(vector_context(world, idx.topk(a.q, 5))),
                "chain": sorted(d | {r for _, r in two}),
            })
        titles = {i: world.works[i].title for row in rows for p in row["path"] for i in p if i in world.works}
        (ROOT / "results/answers.json").write_text(json.dumps({"answers": rows, "titles": titles}))
    (ROOT / "results/bench.json").write_text(json.dumps(out, indent=1))
    print("wrote results/bench.json")


if __name__ == "__main__":
    main()
