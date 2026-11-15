"""Graph stores. HydraStore talks to a HydraDB graph-node over its HTTP Cypher API.

MemoryStore implements the same contract with dictionaries. It is used for unit
tests and as the honest "no graph database" comparison in the benchmark.
"""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from typing import Iterable, Protocol

import requests

BATCH = 1000  # HydraDB admission control caps batches at 1024 items
PAGE = 4096   # max page size; results beyond it arrive via next_cursor


class Store(Protocol):
    def reset(self) -> None: ...
    def add_works(self, rows: Iterable[dict]) -> None: ...
    def add_cites(self, src: int, dsts: Iterable[int]) -> None: ...
    def mark_fetched(self, wid: int) -> None: ...
    def set_verdict(self, wid: int, verdict: int) -> None: ...
    def taint_paths(self, q: int) -> tuple[list[int], list[tuple[int, int]]]: ...
    def frontier(self, q: int) -> list[tuple[int, int, int]]: ...
    def counts(self) -> dict: ...


class MemoryStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.nodes: dict[int, dict] = {}
        self.out: dict[int, set[int]] = defaultdict(set)
        self.inc: dict[int, set[int]] = defaultdict(set)

    def add_works(self, rows: Iterable[dict]) -> None:
        for r in rows:
            n = self.nodes.setdefault(r["id"], {"retracted": 0, "fetched": 0, "verdict": 0})
            n["retracted"] = max(n["retracted"], int(r.get("retracted", 0)))

    def add_cites(self, src: int, dsts: Iterable[int]) -> None:
        for d in dsts:
            self.out[src].add(d)
            self.inc[d].add(src)

    def mark_fetched(self, wid: int) -> None:
        self.nodes[wid]["fetched"] = 1

    def set_verdict(self, wid: int, verdict: int) -> None:
        self.nodes[wid]["verdict"] = verdict

    def taint_paths(self, q):
        direct = sorted(r for r in self.out[q] if self.nodes[r]["retracted"])
        two = sorted(
            (x, r) for x in self.out[q] for r in self.out[x] if self.nodes[r]["retracted"]
        )
        return direct, two

    def frontier(self, q):
        res = []
        for x in self.out[q]:
            if self.nodes[x]["fetched"]:
                continue
            citers = self.inc[x]
            res.append((x, sum(self.nodes[p]["verdict"] for p in citers), len(citers)))
        return sorted(res)

    def counts(self) -> dict:
        return {
            "nodes": len(self.nodes),
            "edges": sum(len(v) for v in self.out.values()),
            "fetched": sum(n["fetched"] for n in self.nodes.values()),
        }


class HydraError(RuntimeError):
    pass


class HydraStore:
    """Cypher over HydraDB's HTTP API. The token is read from a file, never logged."""

    def __init__(self, url: str | None = None, token_file: str | None = None,
                 graph: str = "default", cell: str = "cell-0", pool: int = 64) -> None:
        self.url = (url or os.environ.get("HYDRA_URL", "http://127.0.0.1:8443")).rstrip("/")
        tf = token_file or os.environ.get("HYDRA_TOKEN_FILE", ".hydradb/auth-token")
        with open(tf) as fh:
            token = fh.read().strip()
        self.graph, self.cell = graph, cell
        self._local = threading.local()
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self._pool = pool
        self._known: set[int] = set()  # client-side cache of node existence only

    def _session(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            a = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=self._pool)
            s.mount("http://", a)
            s.mount("https://", a)
            s.headers.update(self._headers)
            self._local.s = s
        return s

    def q(self, query: str, params: dict | None = None) -> list[dict]:
        """Run one Cypher statement, following HydraDB's server-side result cursor."""
        body = {"cell_id": self.cell, "query": query, "page_size": PAGE}
        if params:
            body["parameters"] = params
        out: list[dict] = []
        while True:
            r = self._session().post(f"{self.url}/v1/graphs/{self.graph}/query", json=body, timeout=60)
            if r.status_code >= 400:
                raise HydraError(f"{r.status_code}: {r.text[:300]}")
            payload = r.json()
            out.extend(_rows(payload))
            cur = payload.get("next_cursor") if isinstance(payload, dict) else None
            if cur is None:
                return out
            body = {**body, "cursor": cur, "query_id": payload.get("query_id")}

    def reset(self) -> None:
        ids = [{"id": i} for i in self._all_ids()]
        for i in range(0, len(ids), BATCH):
            self.q("UNWIND $rows AS row MATCH (n {id: row.id}) DETACH DELETE n", {"rows": ids[i:i + BATCH]})
        self._known.clear()

    def _all_ids(self) -> list[int]:
        return [int(r["id"]) for r in self.q("MATCH (n:Work) RETURN n.id AS id")]

    def add_works(self, rows: Iterable[dict]) -> None:
        new = [
            {"id": r["id"], "r": int(r.get("retracted", 0)), "z": 0}
            for r in rows if r["id"] not in self._known
        ]
        for i in range(0, len(new), BATCH):
            self.q(
                "UNWIND $rows AS row MERGE (n {id: row.id}) "
                "SET n:Work, n.retracted = row.r, n.fetched = row.z, n.verdict = row.z",
                {"rows": new[i:i + BATCH]},
            )
        flagged = [{"id": r["id"]} for r in new if r["r"]]
        for i in range(0, len(flagged), BATCH):
            # a label, not just a property: HydraDB filters labelled endpoints far faster
            self.q("UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Retracted",
                   {"rows": flagged[i:i + BATCH]})
        self._known.update(r["id"] for r in new)

    def add_cites(self, src: int, dsts: Iterable[int]) -> None:
        rows = [{"s": src, "d": d} for d in dsts]
        for i in range(0, len(rows), BATCH):
            self.q("UNWIND $rows AS row CREATE (a {id: row.s})-[:CITES]->(b {id: row.d})",
                   {"rows": rows[i:i + BATCH]})

    def mark_fetched(self, wid: int) -> None:
        self.q("MATCH (n:Work {id: $id}) SET n.fetched = 1", {"id": wid})

    def set_verdict(self, wid: int, verdict: int) -> None:
        self.q("MATCH (n:Work {id: $id}) SET n.verdict = $v", {"id": wid, "v": verdict})

    def taint_paths(self, q):
        direct = self.q(
            "MATCH (q:Work {id: $q})-[:CITES]->(r:Retracted) RETURN r.id AS rid",
            {"q": q})
        two = self.q(
            "MATCH (q:Work {id: $q})-[:CITES]->(x:Work)-[:CITES]->(r:Retracted) "
            "RETURN x.id AS via, r.id AS rid", {"q": q})
        return (sorted(int(r["rid"]) for r in direct),
                sorted((int(r["via"]), int(r["rid"])) for r in two))

    def frontier(self, q):
        rows = self.q(
            "MATCH (q:Work {id: $q})-[:CITES]->(x:Work)<-[:CITES]-(p:Work) WHERE x.fetched = 0 "
            "RETURN x.id AS id, sum(p.verdict) AS score, count(*) AS citers", {"q": q})
        return sorted((int(r["id"]), int(r["score"]), int(r["citers"])) for r in rows)

    def counts(self) -> dict:
        n = self.q("MATCH (n:Work) RETURN count(*) AS c")
        e = self.q("MATCH (:Work)-[r:CITES]->(:Work) RETURN count(*) AS c")
        f = self.q("MATCH (n:Work) WHERE n.fetched = 1 RETURN count(*) AS c")
        return {"nodes": int(n[0]["c"]) if n else 0, "edges": int(e[0]["c"]) if e else 0,
                "fetched": int(f[0]["c"]) if f else 0}


def _scalar(v):
    if isinstance(v, dict) and "value" in v:
        return v["value"]
    return v


def _rows(payload) -> list[dict]:
    """Normalise HydraDB's JSON result into a list of {column: python value}."""
    if isinstance(payload, dict):
        cols = payload.get("columns")
        rows = payload.get("rows", payload.get("data", []))
        out = []
        for row in rows:
            if isinstance(row, dict):
                out.append({k: _scalar(v) for k, v in row.items()})
            elif cols:
                out.append({c: _scalar(v) for c, v in zip(cols, row)})
        return out
    return []
