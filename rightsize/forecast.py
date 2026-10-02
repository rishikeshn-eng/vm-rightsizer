"""Per-VM peak-load forecast: hour-of-day x weekday-type quantile profile, rescaled to recent level."""
from __future__ import annotations

import numpy as np

STEPS_PER_DAY = 288


def _slot(idx: np.ndarray, hour_buckets: int = 24):
    step_in_day = idx % STEPS_PER_DAY
    hour = step_in_day * hour_buckets // STEPS_PER_DAY
    weekend = ((idx // STEPS_PER_DAY) % 7 >= 5).astype(int)
    return weekend * hour_buckets + hour


def profile(history: np.ndarray, q: float) -> np.ndarray:
    """(n_vms, 48) quantile of 5-min max CPU % per (weekday-type, hour). Empty slots fall back to the VM's overall q."""
    n_vms, n = history.shape
    slots = _slot(np.arange(n))
    out = np.empty((n_vms, 48), dtype=np.float32)
    overall = np.quantile(history, q, axis=1)
    for s in range(48):
        m = slots == s
        out[:, s] = np.quantile(history[:, m], q, axis=1) if m.sum() >= 12 else overall
    return out


def forecast_peak(history: np.ndarray, horizon_steps: int, q: float = 0.99, recency_days: int = 2,
                  clip=(0.7, 1.5)) -> np.ndarray:
    """Forecast of the q-quantile of 5-min max CPU % for each future step, shape (n_vms, horizon_steps).

    Scales the profile by (mean of last `recency_days` days) / (profile-implied mean for those days),
    clipped, so a VM trending up or down is tracked without trusting a single noisy day.
    """
    n_vms, n = history.shape
    prof = profile(history, q)
    mean_prof = profile(history, 0.5)
    rec = history[:, -recency_days * STEPS_PER_DAY:]
    rec_slots = _slot(np.arange(n - rec.shape[1], n))
    implied = np.take_along_axis(mean_prof, np.broadcast_to(rec_slots, (n_vms, len(rec_slots))), axis=1).mean(1)
    scale = np.clip(rec.mean(1) / np.maximum(implied, 1e-3), *clip)[:, None]
    fut_slots = _slot(np.arange(n, n + horizon_steps))
    return np.minimum(100.0, prof[:, fut_slots] * scale)
