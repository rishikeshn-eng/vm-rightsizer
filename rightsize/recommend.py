"""Pick the smallest core size whose forecast peak stays under a utilisation ceiling; backtest throttling."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .forecast import STEPS_PER_DAY, forecast_peak
from .synth import CORE_LADDER

# Placeholder price. Replace with your own committed-use rate.
INR_PER_CORE_MONTH = 2500.0


@dataclass(frozen=True)
class Policy:
    name: str
    q: float = 0.99          # forecast quantile of 5-min max CPU
    ceiling: float = 0.85    # target peak utilisation of the new size
    min_cores: int = 1


def recommend_cores(peak_pct: np.ndarray, cores: np.ndarray, ceiling: float, min_cores: int = 1) -> np.ndarray:
    """peak_pct: (n_vms, steps) forecast max CPU % of the CURRENT size. Downsize only, never up."""
    demand = peak_pct.max(axis=1) / 100.0 * cores          # cores needed at forecast peak
    need = demand / ceiling
    new = cores.copy()
    for i, (c, nd) in enumerate(zip(cores, need)):
        for size in CORE_LADDER:
            if size >= max(nd, min_cores) and size <= c:
                new[i] = size
                break
    return new


def baseline_cores(history: np.ndarray, cores: np.ndarray, how: str, ceiling: float) -> np.ndarray:
    stat = history.max(axis=1) if how == "hist_max" else np.quantile(history, 0.95, axis=1)
    return recommend_cores(stat[:, None], cores, ceiling)


def backtest(X: np.ndarray, cores: np.ndarray, policy: Policy | None, baseline: str | None = None,
             origins=(6, 8, 10), horizon_days: int = 3, slo_share: float = 0.005):
    """Rolling-origin backtest. For each origin, size from history only, then replay the next
    `horizon_days` of real 5-minute peaks against the smaller size.

    A throttled interval = real peak demand (cores) exceeds the new size. A VM violates its SLO when more
    than `slo_share` of intervals are throttled.
    """
    rows = []
    for o in origins:
        hist = X[:, : o * STEPS_PER_DAY]
        fut = X[:, o * STEPS_PER_DAY:(o + horizon_days) * STEPS_PER_DAY]
        if baseline:
            new = baseline_cores(hist, cores, baseline, 0.85)
        else:
            fc = forecast_peak(hist, fut.shape[1], q=policy.q)
            new = recommend_cores(fc, cores, policy.ceiling, policy.min_cores)
        demand = fut / 100.0 * cores[:, None]
        throttled = (demand > new[:, None]).mean(axis=1)
        rows.append({"cores_before": int(cores.sum()), "cores_after": int(new.sum()),
                     "downsized": float((new < cores).mean()),
                     "viol": float((throttled > slo_share).mean()),
                     "mean_throttled_share": float(throttled.mean())})
    agg = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
    agg["core_savings"] = 1 - agg["cores_after"] / agg["cores_before"]
    agg["inr_saved_per_month"] = (agg["cores_before"] - agg["cores_after"]) * INR_PER_CORE_MONTH
    return agg
