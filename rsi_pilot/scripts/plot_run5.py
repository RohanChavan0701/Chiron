"""Run 5 headline figure: held-out Spider gain per seed (left) and harness cost (right)."""
import csv
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE, INK, INK2, GRID = "#fcfcfb", "#1f1f1e", "#5f5e58", "#e4e3de"
ARMS = [("arm_A", "A  unregularized", "#2a78d6"),
        ("arm_B", "B  RRSI-regularized", "#eb6834"),
        ("arm_C", "C  random edits", "#1baf7a")]
rows = list(csv.DictReader(open("runs_v5/summary.csv")))
seeds = sorted({r["seed"] for r in rows})
val = {(r["seed"], r["harness"]): r for r in rows}
gain = {a: [int(val[(s, a)]["H"]) - int(val[(s, "baseline")]["H"]) for s in seeds] for a, _, _ in ARMS}
tok = {a: [int(val[(s, a)]["tokens_per_task_H"]) for s in seeds] for a, _, _ in ARMS}
tok["baseline"] = [int(val[(s, "baseline")]["tokens_per_task_H"]) for s in seeds]
n_h = int(rows[0]["n_H"])

plt.rcParams.update({"font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK})
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4), facecolor=SURFACE)
for ax in (ax1, ax2):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)

ys = [2, 1, 0]
for (a, label, c), y in zip(ARMS, ys):
    xs = gain[a]
    ax1.scatter(xs, [y + (i - 2.5) * 0.06 for i in range(len(xs))], s=42, color=c,
                edgecolor=SURFACE, linewidth=1.5, zorder=3)
    m = sum(xs) / len(xs)
    ax1.plot([m, m], [y - 0.3, y + 0.3], color=INK, lw=2, zorder=4)
    ax1.text(m, y + 0.36, f"mean +{m:.1f} ({100 * m / n_h:.0f} pts)", ha="center", va="bottom",
             fontsize=9.5, color=INK)
ax1.axvline(0, color=INK2, lw=1)
ax1.set_yticks(ys, [l for _, l, _ in ARMS])
ax1.set_xlim(-2, 38)
ax1.set_ylim(-0.6, 2.75)
ax1.set_xlabel(f"Held-out Spider: tasks gained over baseline (of {n_h})")
ax1.set_title("Every arm transfers in all 6 seeds", loc="left", fontsize=12, color=INK)

for (a, label, c), y in zip(ARMS, ys):
    xs = tok[a]
    ax2.scatter(xs, [y + (i - 2.5) * 0.06 for i in range(len(xs))], s=42, color=c,
                edgecolor=SURFACE, linewidth=1.5, zorder=3)
    m = sum(xs) / len(xs)
    ax2.plot([m, m], [y - 0.3, y + 0.3], color=INK, lw=2, zorder=4)
    ax2.text(m, y + 0.36, f"mean {m:,.0f}", ha="center", va="bottom", fontsize=9.5, color=INK)
bm = sum(tok["baseline"]) / len(tok["baseline"])
ax2.axvline(bm, color=INK2, lw=1, ls="--")
ax2.text(bm, -0.55, f" baseline {bm:,.0f}", color=INK2, fontsize=9.5, va="bottom")
ax2.set_yticks(ys, ["A", "B", "C"])
ax2.set_xlim(1000, 7000)
ax2.set_ylim(-0.6, 2.75)
ax2.set_xlabel("Harness cost: tokens per held-out task")
ax2.set_title("Regularization keeps the harness at baseline cost", loc="left", fontsize=12, color=INK)

fig.text(0.01, 0.01, "Run 5: 7B SQL agent, 32B local proposer, 6 seeds. Dots = seeds, bar = mean.",
         fontsize=9, color=INK2)
fig.tight_layout(rect=(0, 0.04, 1, 1))
out = sys.argv[1] if len(sys.argv) > 1 else "figures/run5_headline.png"
fig.savefig(out, dpi=160, facecolor=SURFACE)
print(out)
