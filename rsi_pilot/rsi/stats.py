"""Paired statistics on per-task pass/fail vectors."""
from __future__ import annotations

import random
from math import comb


def discordant(base: dict[str, bool], new: dict[str, bool]) -> tuple[int, int]:
    """(improved, regressed): tasks failed by base and passed by new, and the reverse."""
    if set(base) != set(new):
        raise ValueError("vectors cover different tasks")
    improved = sum(1 for k in base if not base[k] and new[k])
    regressed = sum(1 for k in base if base[k] and not new[k])
    return improved, regressed


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value (binomial test on discordant pairs, p=0.5)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, p)


def paired_bootstrap_ci(base: dict[str, bool], new: dict[str, bool], iters: int = 10_000,
                        seed: int = 0, alpha: float = 0.05) -> tuple[float, float]:
    """Percentile CI for accuracy(new) - accuracy(base), resampling tasks."""
    keys = sorted(base)
    d = [int(new[k]) - int(base[k]) for k in keys]
    n = len(d)
    rng = random.Random(seed)
    stats = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(iters))
    return stats[int(alpha / 2 * iters)], stats[int((1 - alpha / 2) * iters) - 1]


def transfer_ratio(gain_heldout: float, gain_e: float, min_gain_e: float) -> float | None:
    """Held-out gain / E gain. None when E gain is too small for the ratio to mean anything."""
    if gain_e < min_gain_e:
        return None
    return gain_heldout / gain_e


def compare(base: dict[str, bool], new: dict[str, bool], seed: int = 0) -> dict:
    imp, reg = discordant(base, new)
    n = len(base)
    acc_b = sum(base.values()) / n
    acc_n = sum(new.values()) / n
    lo, hi = paired_bootstrap_ci(base, new, seed=seed)
    return {"acc_base": acc_b, "acc_new": acc_n, "delta": acc_n - acc_b,
            "improved": imp, "regressed": reg, "p_mcnemar": mcnemar_exact(imp, reg),
            "ci95": [lo, hi]}
