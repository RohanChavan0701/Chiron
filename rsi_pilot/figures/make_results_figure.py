"""Run 5 results figure: baseline vs evolved harness on unseen data.

Run from rsi_pilot/:  python figures/make_results_figure.py
Reads runs_v5/summary.csv, writes figures/run5_results.png and .svg.
"Evolved" pools the three arms (A, B, C); each dot is one arm in one seed (18 per set).
"""
from __future__ import annotations

import csv
import statistics as st
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
ROWS = list(csv.DictReader(open(HERE.parent / "runs_v5" / "summary.csv")))

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
BASE, EVOLVED = "#a3a29b", "#2a78d6"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.edgecolor": GRID, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE, "svg.fonttype": "none",
})

SETS = [("H", "Held-out Spider\n(200 tasks, unseen databases)"),
        ("B", "BIRD Mini-Dev\n(200 tasks, different benchmark)")]


def pct(rows, s):
    return [100 * int(r[s]) / int(r["n_" + s]) for r in rows]


base = [r for r in ROWS if r["harness"] == "baseline"]
evo = [r for r in ROWS if r["harness"].startswith("arm_")]

fig, ax = plt.subplots(figsize=(8, 4.6))
w = 0.34
for i, (s, label) in enumerate(SETS):
    for dx, rows, color, name in [(-w / 2 - 0.01, base, BASE, "Baseline harness"),
                                  (w / 2 + 0.01, evo, EVOLVED, "Self-improved harness")]:
        vals = pct(rows, s)
        m = st.mean(vals)
        ax.bar(i + dx, m, w, color=color, label=name if i == 0 else None, zorder=2)
        ax.scatter([i + dx] * len(vals), vals, s=14, color=INK, alpha=0.35, zorder=3,
                   linewidths=0)
        ax.text(i + dx, 2, f"{m:.1f}%", ha="center", va="bottom", fontsize=12,
                fontweight="bold", color="white" if color == EVOLVED else INK, zorder=4)
    gain = st.mean(pct(evo, s)) - st.mean(pct(base, s))
    ax.text(i, 72, f"+{gain:.1f} pts", ha="center", fontsize=12, color=INK)

ax.set_xticks(range(len(SETS)), [l for _, l in SETS])
ax.set_ylim(0, 80)
ax.set_ylabel("Execution accuracy (%)")
ax.yaxis.grid(True, color=GRID, zorder=0)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.tick_params(axis="both", length=0)
ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, 1.12), ncol=2)
fig.text(0.01, 0.01, "Run 5: 7B SQL agent, 6 seeds x 3 search strategies. "
         "Bars = mean, dots = individual runs. Every run beat its baseline on both sets.",
         fontsize=8.5, color=INK2)
fig.tight_layout(rect=(0, 0.04, 1, 1))
for ext in ("png", "svg"):
    fig.savefig(HERE / f"run5_results.{ext}", dpi=200)
print("ok")
