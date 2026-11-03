"""Figures for docs/writeup/post.md. Run from the repo root:

    python docs/writeup/make_figures.py

rsi_pilot numbers are parsed from their run outputs. Coding and GSM8K numbers live only in
the findings docs' prose, so they are listed below with the section each comes from.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#5c5b55"
GRID = "#e4e3de"
TUNED = "#2a78d6"     # categorical slot 1
HELD = "#eb6834"      # categorical slot 2

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.edgecolor": GRID, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE, "svg.fonttype": "none",
})


def pooled_net(path: Path) -> dict[tuple[str, str], int]:
    """(comparison, set) -> net tasks, from rsi_pilot/runs_pooled_v2v3.md's pooled table."""
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"\|\s*(arm_\w+ vs \w+)\s*\|\s*([EHB])\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*([+-]?\d+)\s*\|", line)
        if m:
            out[(m.group(1), m.group(2))] = int(m.group(3))
    return out


def figure_transfer() -> None:
    net = pooled_net(ROOT / "rsi_pilot/runs_pooled_v2v3.md")
    n = 200  # 4 runs x 50 tasks per set
    rows = [
        # label, gain where tuned (pp), held-out gain (pp), source
        ("Coding, Llama-3.2-3B", 18.2, -6.9, "FINDINGS_CODING A and C"),
        ("Coding, mistral-nemo 12B", 17.2, 0.0, "FINDINGS_CODING E and F (4-repeat mean)"),
        ("GSM8K, Llama-3.2-3B", 8.3, -14.3, "FINDINGS_REASONING curriculum and ablation"),
        ("Harness evolution, unconstrained", 100 * net[("arm_A vs baseline", "E")] / n,
         100 * net[("arm_A vs baseline", "H")] / n, "runs_pooled_v2v3.md"),
        ("Harness evolution, regularized", 100 * net[("arm_B vs baseline", "E")] / n,
         100 * net[("arm_B vs baseline", "H")] / n, "runs_pooled_v2v3.md"),
    ]
    fig, ax = plt.subplots(figsize=(7.6, 3.4))
    ys = list(range(len(rows)))[::-1]
    for y, (label, tuned, held, _) in zip(ys, rows):
        ax.plot([held, tuned], [y, y], color=GRID, lw=2, zorder=1, solid_capstyle="round")
        ax.scatter([tuned], [y], s=64, color=TUNED, zorder=3, edgecolors=SURFACE, linewidths=2)
        ax.scatter([held], [y], s=64, color=HELD, zorder=3, edgecolors=SURFACE, linewidths=2, marker="D")
        ax.annotate(f"{tuned:+.1f}", (tuned, y), xytext=(8, 0), textcoords="offset points", va="center",
                    fontsize=9, color=INK)
        ax.annotate(f"{held:+.1f}" if held else "0.0", (held, y), xytext=(-8, 0), textcoords="offset points", va="center",
                    ha="right", fontsize=9, color=INK)
    ax.axvline(0, color=INK2, lw=1, zorder=0)
    ax.set_yticks(ys, [r[0] for r in rows])
    ax.set_xlim(-22, 26)
    ax.set_xlabel("Accuracy change vs. no memory / baseline harness (percentage points)")
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    h1 = ax.scatter([], [], s=64, color=TUNED, label="Where it was built or tuned")
    h2 = ax.scatter([], [], s=64, color=HELD, marker="D", label="Frozen, held out")
    ax.legend(handles=[h1, h2], loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False,
              fontsize=9)
    fig.tight_layout()
    for ext in ("svg", "png"):
        fig.savefig(OUT / f"fig1_transfer.{ext}", dpi=200)
    plt.close(fig)


def figure_audit() -> None:
    a = json.loads((ROOT / "rsi_pilot/runs/audit.json").read_text())
    names = [("baseline", "Baseline"), ("arm_A", "Arm A\nunconstrained"), ("arm_B", "Arm B\nregularized")]
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.0), sharey=True)
    for ax, split, title in zip(axes, ("E", "H"), ("Tuning set E", "Held-out Spider H")):
        xs = range(len(names))
        before = [a[f"{k}/{split}"]["passes"] for k, _ in names]
        after = [a[f"{k}/{split}"]["passes"] - a[f"{k}/{split}"]["testsuite_false_positives"] for k, _ in names]
        w = 0.36
        b1 = ax.bar([x - w / 2 - 0.01 for x in xs], before, w, color=TUNED, label="Pass (single database)")
        b2 = ax.bar([x + w / 2 + 0.01 for x in xs], after, w, color=HELD, label="Also passes test suite")
        for bars in (b1, b2):
            for r in bars:
                ax.annotate(str(int(r.get_height())), (r.get_x() + r.get_width() / 2, r.get_height()),
                            xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9, color=INK)
        ax.set_xticks(list(xs), [lab for _, lab in names], fontsize=9)
        ax.set_title(title, fontsize=10, color=INK, loc="left")
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(axis="x", length=0)
    axes[0].set_ylabel("Tasks passed (of 50)")
    axes[0].set_ylim(0, 36)
    axes[0].legend(loc="lower left", bbox_to_anchor=(0, 1.08), ncol=2, frameon=False, fontsize=9)
    fig.tight_layout()
    for ext in ("svg", "png"):
        fig.savefig(OUT / f"fig2_audit.{ext}", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    figure_transfer()
    figure_audit()
    print("wrote", sorted(p.name for p in OUT.glob("fig*")))
