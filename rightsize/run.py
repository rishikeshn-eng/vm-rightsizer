from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from . import synth
from .forecast import STEPS_PER_DAY, forecast_peak
from .recommend import INR_PER_CORE_MONTH, Policy, backtest, recommend_cores


def pinball(y, f, q):
    d = y - f
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def load(args):
    if args.npz:
        z = np.load(args.npz, allow_pickle=True)
        return {"maxcpu": z["maxcpu"], "cores": z["cores"], "vmid": z["vmid"], "kind": np.array(["?"] * len(z["cores"])),
                "days": z["maxcpu"].shape[1] // STEPS_PER_DAY}, False
    return synth.generate(args.vms), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz", help="matrix from scripts/ingest_azure.py (real data)")
    ap.add_argument("--vms", type=int, default=800)
    ap.add_argument("--out", default="docs/results.json")
    a = ap.parse_args()
    d, is_synth = load(a)
    X, cores = d["maxcpu"], d["cores"]

    policies = [Policy(f"forecast q={q} ceil={c}", q, c) for q in (0.9, 0.95, 0.99, 0.999) for c in (0.7, 0.85, 1.0)]
    pareto = []
    for p in policies:
        r = backtest(X, cores, p)
        pareto.append({"name": p.name, "kind": "forecast", "q": p.q, "ceiling": p.ceiling, **r})
    for b, label in (("hist_p95", "baseline: p95 of history"), ("hist_max", "baseline: max of history")):
        pareto.append({"name": label, "kind": "baseline", **backtest(X, cores, None, baseline=b)})
    for r in pareto:
        print(f"{r['name']:32s} savings={r['core_savings']:.1%} violating_vms={r['viol']:.1%} "
              f"throttled={r['mean_throttled_share']:.2%}")

    # forecast accuracy at the origin used for the example VMs (q=0.99 pinball vs seasonal-naive-last-day)
    o, h = 10, 3 * STEPS_PER_DAY
    hist, fut = X[:, : o * STEPS_PER_DAY], X[:, o * STEPS_PER_DAY:o * STEPS_PER_DAY + h]
    f = forecast_peak(hist, h, 0.99)
    naive = np.tile(hist[:, -STEPS_PER_DAY:], 3)
    acc = {"pinball_q99_profile": pinball(fut, f, 0.99), "pinball_q99_naive_last_day": pinball(fut, naive, 0.99)}
    print(acc)

    chosen = Policy("forecast q=0.99 ceil=0.85", 0.99, 0.85)
    new = recommend_cores(f, cores, chosen.ceiling)
    order = np.argsort(-(cores - new))[:40]
    hr = lambda m: m.reshape(m.shape[0], -1, 12).max(axis=2)  # 5-min -> hourly max
    ex = []
    for i in order:
        ex.append({"vmid": str(d["vmid"][i]), "cores": int(cores[i]), "rec": int(new[i]),
                   "peak_hist": float(hist[i].max()), "peak_future": float(fut[i].max()),
                   "hist": np.round(hr(hist[i:i + 1])[0][-96:], 1).tolist(),
                   "actual": np.round(hr(fut[i:i + 1])[0], 1).tolist(),
                   "fc": np.round(hr(f[i:i + 1])[0], 1).tolist()})
    payload = {"synthetic": is_synth, "vms": int(len(cores)), "days": int(d["days"]), "inr_per_core_month": INR_PER_CORE_MONTH,
               "pareto": pareto, "accuracy": acc, "examples": ex, "slo_share": 0.005}
    Path(a.out).write_text(json.dumps(payload))


if __name__ == "__main__":
    main()
