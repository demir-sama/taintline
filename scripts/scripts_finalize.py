"""Fill README numbers from results/*.json and copy data into web/data."""
import json, shutil
from pathlib import Path
R = Path(__file__).resolve().parent.parent
b = json.loads((R / "results/bench.json").read_text())
L = json.loads((R / "results/load.json").read_text())
S, V = b["strategies"], b["vector"]
p = lambda x: f"{x*100:.1f}%"
rows = [
 ("**Taintline (HydraDB)**", S["taintline"], None),
 ("Graph memory, random reads", S["memory_random"], None),
 ("No memory (reset per question)", S["cold"], None),
 ("Taintline + own-verdict ranking (ablation)", S["taintline_verdict"], None),
]
t = ["| Approach | Accuracy | Final round | Recall (tainted) | Precision | Reference lists read / q | Context tokens / answer |", "|---|---:|---:|---:|---:|---:|---:|"]
for name, s, _ in rows:
    tok = f"{b['taintline_tokens_mean']:.0f}" if "Taintline (" in name else "≈ same"
    t.append(f"| {name} | {p(s['accuracy_mean'])} | {p(s['curve_mean'][-1])} | {p(s['recall_mean'])} | {p(s['precision_min'])} | {s['fetches_per_q']:.2f} | {tok} |")
for k in ["top5", "top10"]:
    v = V[k]
    t.append(f"| Vector store, {k.replace('top','top-')} (bge-small) | {p(v['accuracy'])} | — | {p(v['recall'])} | {p(v['precision'])} | 0 | {v['tokens_mean']:,.0f} |")
a = b["always_tainted"]
t.append(f"| Always say \"tainted\" | {p(a['accuracy'])} | — | 100% | {p(a['precision'])} | 0 | no evidence |")
t.append(f"| Full crawl, no budget | 100% | 100% | 100% | 100% | {b['exhaustive']['fetches_per_q']:.1f} | — |")
h = b.get("hydra_run", {})
hydra = (f"the same 790 questions on a local HydraDB node built **{h['graph']['nodes']:,} nodes / {h['graph']['edges']:,} CITES edges**, "
         f"accuracy {p(h['accuracy'])}, with **{h['parity_mismatches_vs_memory']} answer mismatches** against the in-memory reference ({h['seconds']:.0f} s end to end, writes included).") if h else "n/a"
load = (f"{L['workers']} concurrent clients for {L['seconds']:.0f} s against one local graph-node: **{L['qps']:.0f} queries/s**, "
        f"p50 {L['p50_ms']:.0f} ms, p95 {L['p95_ms']:.0f} ms, p99 {L['p99_ms']:.0f} ms per operation, **{L['errors']} errors** in {L['operations']:,} operations "
        f"(an operation is the 2-query path check or the frontier query; 8 vCPU box, dev build settings).")
md = (R / "README.md").read_text()
for k, v in {
    "RESULTS_TABLE": "\n".join(t), "ROUND1": p(S["taintline"]["curve_mean"][0]), "ROUND8": p(S["taintline"]["curve_mean"][-1]),
    "HYDRA_RUN": hydra, "LOAD_LINE": load, "VEC_EVIDENCE": f"{V['top5']['evidence_correct_when_flagged']*100:.0f}%",
    "VEC_TOKENS": f"{V['top5']['tokens_mean']:,.0f}", "TL_TOKENS": f"{b['taintline_tokens_mean']:.0f}",
    "EXH": f"{b['exhaustive']['fetches_per_q']:.0f}", "TL_FETCH": f"{S['taintline']['fetches_per_q']:.1f}",
}.items():
    md = md.replace(k, v)
(R / "README.md").write_text(md)
(R / "web/data").mkdir(exist_ok=True)
for f in ["bench.json", "answers.json", "load.json"]:
    shutil.copy(R / "results" / f, R / "web/data" / f)
print("ok")
