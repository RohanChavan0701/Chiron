"""Run 6 estimator: how much of a selected edit's reported gain is real, proxy bias, or noise.

Data: n edits, each scored on the same m tasks, plus a baseline on those tasks.
  t[i][j]  truth for edit i on task j (0/1)
  p[i][j]  proxy for edit i on task j (0/1 or a score)
  t0[j], p0[j]  baseline (may be means over repeated baseline runs)

Per task, an edit's proxy gain splits exactly into
  a = t - t0                    true gain
  b = (p - t) - (p0 - t0)       change in proxy error (bias)
so that proxy gain c = a + b.

Each of a, b is a two-way table (edit x task). Edits share the tasks, so the task effect
moves all edits together and does not create spread between them. What does create spread
between edit means is the edit effect (signal) and the edit-by-task residual (noise):
  Var_i(mean_j x_ij) = signal_xx + resid_xx / m
The residual mean square estimates resid_xx, so signal_xx = between - resid_xx / m.
The same identity holds for the cross term between a and b.

Selecting the edit with the largest proxy gain on m' tasks returns, in expectation, a
winner whose reported gain splits in proportion to each component's covariance with the
selection score (exact for jointly normal components, an approximation otherwise):
  real  share = (s_aa + s_ab) / D
  bias  share = (s_bb + s_ab) / D        <- the Goodhart share G
  noise share = (r_cc / m')    / D
  D = s_aa + s_bb + 2 s_ab + r_cc / m'
When true gain and bias are uncorrelated across edits this is the formula in RUN6_DESIGN.md.
"""
from __future__ import annotations

import random
from statistics import fmean


def _two_way(x: list[list[float]], y: list[list[float]]) -> tuple[float, float]:
    """Return (between-edit covariance of row means, residual cross mean square)."""
    n, m = len(x), len(x[0])
    xr, yr = [fmean(r) for r in x], [fmean(r) for r in y]
    xc = [fmean(x[i][j] for i in range(n)) for j in range(m)]
    yc = [fmean(y[i][j] for i in range(n)) for j in range(m)]
    xg, yg = fmean(xr), fmean(yr)
    between = sum((xr[i] - xg) * (yr[i] - yg) for i in range(n)) / (n - 1)
    resid = sum((x[i][j] - xr[i] - xc[j] + xg) * (y[i][j] - yr[i] - yc[j] + yg)
                for i in range(n) for j in range(m)) / ((n - 1) * (m - 1))
    return between, resid


def components(t, p, t0, p0) -> dict:
    """Noise-corrected spread of true gain (a) and bias (b) across edits. Needs n >= 2, m >= 2."""
    n, m = len(t), len(t[0])
    a = [[t[i][j] - t0[j] for j in range(m)] for i in range(n)]
    b = [[(p[i][j] - t[i][j]) - (p0[j] - t0[j]) for j in range(m)] for i in range(n)]
    c = [[a[i][j] + b[i][j] for j in range(m)] for i in range(n)]
    out = {"n_edits": n, "n_tasks": m,
           "mean_true_gain": fmean(fmean(r) for r in a), "mean_bias": fmean(fmean(r) for r in b)}
    for name, (x, y) in {"aa": (a, a), "bb": (b, b), "ab": (a, b), "cc": (c, c)}.items():
        between, resid = _two_way(x, y)
        out[f"s_{name}"] = between - resid / m
        out[f"r_{name}"] = resid
    return out


def shares(comp: dict, m_select: int) -> dict:
    """Expected split of the winner's reported gain when selecting on the proxy over m_select tasks.
    Negative variance estimates are floored at zero; the cross term is kept as estimated."""
    s_aa, s_bb, s_ab = max(comp["s_aa"], 0.0), max(comp["s_bb"], 0.0), comp["s_ab"]
    noise = comp["r_cc"] / m_select
    d = s_aa + s_bb + 2 * s_ab + noise
    if d <= 0:
        return {"real": None, "goodhart": None, "noise": None}
    return {"real": (s_aa + s_ab) / d, "goodhart": (s_bb + s_ab) / d, "noise": noise / d}


def simulate(n_edits: int, n_tasks: int, sd_true: float, sd_bias: float, base_acc: float,
             false_pos: float, false_neg: float, rng: random.Random):
    """Synthetic binary data with known spreads, for tests and the stage-0 power check.

    Each edit shifts accuracy by N(0, sd_true) and the proxy's false-positive rate by
    N(0, sd_bias) / (1 - accuracy), so its bias moves by about N(0, sd_bias). Tasks vary
    in difficulty. The baseline is edit-free.
    """
    clip = lambda v: min(max(v, 0.0), 1.0)
    diff = [rng.uniform(-0.3, 0.3) for _ in range(n_tasks)]

    def episode(acc_shift: float, fp_shift: float):
        ts, ps = [], []
        for d in diff:
            t = rng.random() < clip(base_acc + d + acc_shift)
            wrong_rate = max(1 - clip(base_acc + acc_shift), 0.05)
            p = (rng.random() >= false_neg) if t else (rng.random() < clip(false_pos + fp_shift / wrong_rate))
            ts.append(float(t)); ps.append(float(p))
        return ts, ps

    t0, p0 = episode(0.0, 0.0)
    t, p = [], []
    for _ in range(n_edits):
        ti, pi = episode(rng.gauss(0, sd_true), rng.gauss(0, sd_bias))
        t.append(ti); p.append(pi)
    return t, p, t0, p0


def power(n_edits: int, n_tasks: int, sd_true: float, sd_bias: float, base_acc: float, false_pos: float,
          false_neg: float, m_select: int = 50, sims: int = 200, seed: int = 0) -> dict:
    """Spread of the estimates over repeated synthetic banks of this size."""
    rng = random.Random(seed)
    sb, g = [], []
    for _ in range(sims):
        comp = components(*simulate(n_edits, n_tasks, sd_true, sd_bias, base_acc, false_pos, false_neg, rng))
        sb.append(max(comp["s_bb"], 0.0) ** 0.5)
        sh = shares(comp, m_select)["goodhart"]
        if sh is not None:
            g.append(sh)
    q = lambda v, f: sorted(v)[int(f * (len(v) - 1))]
    return {"sd_bias_true": sd_bias, "sd_bias_est_median": q(sb, 0.5), "sd_bias_est_p10": q(sb, 0.1),
            "sd_bias_est_p90": q(sb, 0.9), "goodhart_median": q(g, 0.5), "goodhart_p10": q(g, 0.1),
            "goodhart_p90": q(g, 0.9), "sims": sims}
