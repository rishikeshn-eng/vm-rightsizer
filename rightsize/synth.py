"""Synthetic VM fleet shaped like the Azure Public Dataset V2 CPU readings.

NOT real data. Per-VM 5-minute *max* CPU % matrix (VMs x steps). Most VMs are over-provisioned
(low mean utilisation), some have a daily cycle, some run batch bursts, and all can have
unforecastable spikes, mirroring the qualitative picture in the Azure trace paper (Cortez et al.,
SOSP'17). Any result measured on it reflects this generator.
"""
from __future__ import annotations

import numpy as np

CORE_LADDER = [1, 2, 4, 8, 16, 24]
STEPS_PER_DAY = 288  # 5-minute readings


def generate(n_vms: int = 800, days: int = 14, seed: int = 11):
    rng = np.random.default_rng(seed)
    n = days * STEPS_PER_DAY
    t = np.arange(n)
    hour = (t % STEPS_PER_DAY) / STEPS_PER_DAY * 24
    dow = (t // STEPS_PER_DAY) % 7
    cores = rng.choice(CORE_LADDER, n_vms, p=[0.12, 0.30, 0.28, 0.17, 0.08, 0.05])
    kind = rng.choice(["interactive", "batch", "flat"], n_vms, p=[0.4, 0.25, 0.35])
    base = rng.beta(1.2, 7.0, n_vms) * 100  # mean util %, skewed low
    X = np.zeros((n_vms, n), dtype=np.float32)
    for i in range(n_vms):
        phase = rng.uniform(0, 24)
        if kind[i] == "interactive":
            day_curve = 0.5 + 0.5 * np.sin((hour - phase) / 24 * 2 * np.pi)
            weekend = np.where(dow >= 5, rng.uniform(0.3, 0.8), 1.0)
            level = base[i] * (0.4 + 1.2 * day_curve) * weekend
        elif kind[i] == "batch":
            level = np.full(n, base[i] * 0.4)
            for d in range(days):
                if rng.random() < 0.7:
                    s = d * STEPS_PER_DAY + int(rng.uniform(0, 0.8) * STEPS_PER_DAY)
                    L = int(rng.uniform(6, 60))
                    level[s:s + L] = base[i] * rng.uniform(2, 5)
        else:
            level = np.full(n, base[i])
        drift = 1 + 0.01 * rng.normal() * (t / STEPS_PER_DAY)  # slow trend
        avg = level * drift * rng.lognormal(0, 0.15, n)
        peak = avg * (1 + np.abs(rng.normal(0, 0.35, n)))  # 5-min max sits above the 5-min average
        # rare unforecastable spikes
        k = rng.poisson(rng.uniform(0, 6))
        for _ in range(k):
            s = rng.integers(0, n - 4)
            peak[s:s + rng.integers(1, 4)] = rng.uniform(60, 100)
        X[i] = np.clip(peak, 0.5, 100)
    return {"maxcpu": X, "cores": cores, "kind": kind, "days": days,
            "vmid": np.array([f"vm{i:05d}" for i in range(n_vms)])}
