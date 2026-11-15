"""Render the accuracy-over-rounds chart for the README: python -m taintline.plot"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    b = json.loads((ROOT / "results/bench.json").read_text())
    S = b["strategies"]
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=160)
    fig.patch.set_facecolor("#f4f1ea")
    ax.set_facecolor("#fbf9f4")
    n = len(S["taintline"]["curve_mean"])
    xs = list(range(1, n + 1))
    for key, color, label, ls in [
        ("taintline", "#c2361c", "Taintline (HydraDB)", "-"),
        ("memory_random", "#857d70", "Graph memory, random reads", "-"),
        ("cold", "#16130f", "No memory (reset per question)", "--"),
    ]:
        s = S[key]
        ax.fill_between(xs, s["curve_min"], s["curve_max"], color=color, alpha=0.12, lw=0)
        ax.plot(xs, s["curve_mean"], ls, color=color, lw=2.8 if key == "taintline" else 1.8, marker="o", ms=4, label=label)
    v = b["vector"]["top5"]["accuracy"]
    ax.axhline(v, color="#3a5a8c", ls=":", lw=2, label=f"Vector store top-5 ({v:.0%})")
    a = b["always_tainted"]["accuracy"]
    ax.axhline(a, color="#a49a88", ls="-.", lw=1, label=f"Always say tainted ({a:.0%}, no evidence)")
    ax.set_ylim(0, 1)
    ax.set_xticks(xs, [f"R{i}" for i in xs])
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0%}")
    ax.set_xlabel("Round of 100 questions (budget: 3 reference-list reads per question)")
    ax.set_ylabel("Accuracy in round")
    ax.set_title("Taintline gets sharper every round", loc="left", fontsize=13, fontweight="bold")
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    ax.grid(axis="y", color="#d6cfc1")
    ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    fig.tight_layout()
    fig.savefig(ROOT / "docs/accuracy_curve.png")
    plt.rcParams["svg.fonttype"] = "none"
    fig.savefig(ROOT / "docs/accuracy_curve.svg")
    print("wrote docs/accuracy_curve.png and .svg")


if __name__ == "__main__":
    main()
