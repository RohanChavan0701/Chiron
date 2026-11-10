"""Run 6: replay selection over a stored edit bank. No model calls.

One round: draw k candidate edits and m selection tasks; the rest of the tasks are fresh.
The keep rule picks a winner from proxy scores on the selection tasks. The winner's
reported gain then splits exactly into
  reported   = proxy gain on selection tasks
  real       = true gain on fresh tasks
  bias       = proxy gain on fresh tasks - true gain on fresh tasks   (persistent proxy error:
               the Goodhart part; measured on fresh tasks so selection cannot inflate it)
  noise      = proxy gain on selection tasks - proxy gain on fresh tasks   (the winner's curse)
             = noise_true (true gain, selection minus fresh)
             + noise_bias (proxy error, selection minus fresh: judge luck on the selection tasks)
Averaging over rounds gives the empirical counterpart of rsi.goodhart.shares. An earlier version
took bias on the selection tasks, which counted noise_bias as Goodhart.

Keep rules:
  greedy         best proxy gain, kept if above zero (run 5's arms A and C)
  threshold:t    best proxy gain, kept only if at least t
  random         a random candidate (selection switched off; the control)
  audit:n        best proxy gain among candidates whose true gain on n labelled selection
                 tasks is not negative (spend n labels per candidate)
A round that keeps nothing reports zeros, as a loop that keeps its current harness would.
"""
from __future__ import annotations

import random
from statistics import fmean


def _gain(row: list[float], base: list[float], idx: list[int]) -> float:
    return fmean(row[j] - base[j] for j in idx)


def replay(t, p, t0, p0, k: int, m: int, rule: str = "greedy", rounds: int = 2000, seed: int = 0) -> dict:
    n, n_tasks = len(t), len(t[0])
    if not 1 <= m < n_tasks:
        raise ValueError(f"m must leave fresh tasks: 1 <= m < {n_tasks}")
    rng = random.Random(seed)
    name, _, arg = rule.partition(":")
    out = {"reported": [], "bias": [], "noise": [], "noise_true": [], "noise_bias": [], "real": [], "kept": []}
    for _ in range(rounds):
        order = rng.sample(range(n_tasks), n_tasks)
        sel, fresh = order[:m], order[m:]
        cands = rng.sample(range(n), min(k, n))
        proxy = {i: _gain(p[i], p0, sel) for i in cands}
        if name == "random":
            w = rng.choice(cands)
        else:
            pool = cands
            if name == "audit":
                lab = sel[:int(arg)]
                pool = [i for i in cands if _gain(t[i], t0, lab) >= 0]
            w = max(pool, key=proxy.get) if pool else None
            if w is not None:
                keep = proxy[w] >= float(arg) if name == "threshold" else proxy[w] > 0
                w = w if keep else None
        if w is None:
            for key in out:
                out[key].append(0.0)
            continue
        true_sel, true_fresh = _gain(t[w], t0, sel), _gain(t[w], t0, fresh)
        bias_fresh = _gain(p[w], p0, fresh) - true_fresh
        out["reported"].append(proxy[w]); out["real"].append(true_fresh); out["bias"].append(bias_fresh)
        out["noise_true"].append(true_sel - true_fresh)
        out["noise_bias"].append(proxy[w] - true_sel - bias_fresh)
        out["noise"].append(proxy[w] - true_fresh - bias_fresh)
        out["kept"].append(1.0)
    mean = {key: fmean(v) for key, v in out.items()}
    rep = mean["reported"]
    return {**mean, "k": k, "m": m, "rule": rule, "rounds": rounds,
            "share_real": mean["real"] / rep if rep > 0 else None,
            "share_goodhart": mean["bias"] / rep if rep > 0 else None,
            "share_noise": mean["noise"] / rep if rep > 0 else None}
