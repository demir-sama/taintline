import os
import socket
from pathlib import Path

import pytest

from taintline.context import taintline_context, tokens
from taintline.engine import Taintline, exhaustive
from taintline.store import MemoryStore
from taintline.world import Work, World, abstract_text, wid

ROOT = Path(__file__).resolve().parent.parent


def tiny_world() -> World:
    # 100 -> 10 -> 1(R);  101 -> 11 -> 2(R);  102 -> 1(R) directly;  103 -> 12 (clean)
    # 104 -> 10 (shares the bridge with 100);  105 cites many decoys + 10
    W = {
        1: Work(1, "Retracted A", 2020, True, []),
        2: Work(2, "Retracted B", 2020, True, []),
        10: Work(10, "Bridge X", 2021, False, [1, 50]),
        11: Work(11, "Bridge Y", 2021, False, [2]),
        12: Work(12, "Clean Z", 2021, False, [51]),
        100: Work(100, "Q0", 2022, False, [10, 60, 61]),
        101: Work(101, "Q1", 2022, False, [11]),
        102: Work(102, "Q2", 2022, False, [1, 62]),
        103: Work(103, "Q3", 2022, False, [12, 63]),
        104: Work(104, "Q4", 2022, False, [10, 64]),
        105: Work(105, "Q5", 2022, False, [70, 71, 72, 73, 74, 10]),
    }
    return World(works=W, retracted={1, 2}, questions=[100, 101, 102, 103, 104, 105])


def test_wid_parses_and_rejects():
    assert wid("https://openalex.org/W3010930696") == 3010930696
    for bad in ["https://openalex.org/A123", "W", "Wabc", ""]:
        with pytest.raises(ValueError):
            wid(bad)


def test_abstract_reconstruction():
    assert abstract_text({"world": [1], "hello": [0]}) == "hello world"
    assert abstract_text(None) == ""


def test_truth_counts_direct_and_two_hop():
    w = tiny_world()
    assert w.truth(100) == (set(), {(10, 1)})
    assert w.truth(102)[0] == {1}
    assert not w.is_tainted(103)


@pytest.mark.parametrize("priority", ["degree", "verdict", "random"])
def test_never_flags_without_a_real_path(priority):
    w = tiny_world()
    t = Taintline(w, MemoryStore(), budget=10, priority=priority)
    for q in w.questions:
        a = t.answer(q)
        if a.tainted:
            d, two = w.truth(q)
            assert set(a.direct) <= d and set(a.two_hop) <= two


def test_budget_zero_only_sees_direct():
    w = tiny_world()
    t = Taintline(w, MemoryStore(), budget=0)
    assert t.answer(102).tainted and t.answer(102).fetches == 0  # second time: cached
    assert not t.answer(100).tainted


def test_memory_makes_later_questions_cheaper():
    w = tiny_world()
    t = Taintline(w, MemoryStore(), budget=3)
    first = t.answer(100)
    assert first.tainted
    w.reset_meter()
    again = t.answer(104)  # shares bridge 10, already ingested
    assert again.tainted and again.expansions == 0 and again.fetches == 1


def test_degree_priority_finds_bridge_among_decoys():
    w = tiny_world()
    t = Taintline(w, MemoryStore(), budget=1, priority="degree")
    t.answer(100)  # ingests 10 via the only frontier reach
    t.answer(104)
    a = t.answer(105)  # 10 already fetched -> path is free
    assert a.tainted and a.expansions == 0


def test_cold_mode_resets_graph_each_question():
    w = tiny_world()
    t = Taintline(w, MemoryStore(), budget=3, persist=False, learn=False, priority="random")
    t.answer(100)
    w.reset_meter()
    a = t.answer(104)
    assert a.fetches >= 1 and (a.expansions >= 1 or not a.tainted)


def test_exhaustive_matches_truth():
    w = tiny_world()
    for q in w.questions:
        assert exhaustive(w, q).tainted == w.is_tainted(q)


def test_context_is_compact_and_cites_path():
    w = tiny_world()
    a = Taintline(w, MemoryStore(), budget=3).answer(100)
    ctx = taintline_context(w, a)
    assert "RETRACTED" in ctx and "W10" in ctx and tokens(ctx) < 120


def test_bad_priority_rejected():
    with pytest.raises(ValueError):
        Taintline(tiny_world(), MemoryStore(), priority="magic")


def _hydra_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", 8443), timeout=0.3).close()
        return (ROOT / ".hydradb/auth-token").exists()
    except OSError:
        return False


@pytest.mark.skipif(not _hydra_up() or os.environ.get("SKIP_HYDRA") == "1", reason="no local HydraDB")
def test_hydra_store_matches_memory_store():
    from taintline.store import HydraStore
    h = HydraStore(token_file=str(ROOT / ".hydradb/auth-token"))
    h.graph = os.environ.get("HYDRA_TEST_GRAPH", "default")
    # use ids far from OpenAlex ranges so a shared node is never touched
    base = 9_000_000_000_000
    rows = [{"id": base + i, "retracted": int(i in (3, 6))} for i in range(1, 7)]
    for s in (h, MemoryStore()):
        if isinstance(s, MemoryStore):
            s.reset()
        s.add_works(rows)
        s.add_cites(base + 1, [base + 2, base + 4, base + 6])
        s.add_cites(base + 2, [base + 3])
        s.add_cites(base + 5, [base + 4])
        s.mark_fetched(base + 1)
        s.mark_fetched(base + 2)
        s.set_verdict(base + 5, 3)
        assert s.taint_paths(base + 1) == ([base + 6], [(base + 2, base + 3)])
        assert s.frontier(base + 1) == [(base + 4, 3, 2), (base + 6, 0, 1)]
    h.q("UNWIND $rows AS row MATCH (n {id: row.id}) DETACH DELETE n", {"rows": [{"id": r["id"]} for r in rows]})
