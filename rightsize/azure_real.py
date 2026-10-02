"""Real Azure Public Dataset V2 analysis from two files: vmtable and ONE cpu-readings shard.

What the real files do and do not support (checked on the downloaded files):
- vmtable.csv.gz: all 2.7M VMs with lifetime max / avg / p95-of-max CPU, core bucket and category, but NO time series.
- vm_cpu_readings shards are TIME slices, not VM slices: shard 1 covers timestamps 0..13200 s (3.7 h) for ~241k VMs.
  A 14-day per-VM history therefore needs ~100 shards (~85 GB). One shard supports only a short-window sanity check.
"""
from __future__ import annotations

import duckdb
import numpy as np

LADDER = [1, 2, 4, 8, 16, 24, 32]  # '>24' bucket is treated as 32 cores
VM_COLS = ("{'vmid':'VARCHAR','sub':'VARCHAR','dep':'VARCHAR','created':'BIGINT','deleted':'BIGINT','maxcpu':'DOUBLE',"
           "'avgcpu':'DOUBLE','p95':'DOUBLE','category':'VARCHAR','cores':'VARCHAR','mem':'VARCHAR'}")


def _vm(con, vmtable):
    con.execute(f"""CREATE TABLE vm AS SELECT vmid, created, deleted, maxcpu, avgcpu, p95, category,
        CASE WHEN cores LIKE '>%' THEN 32 ELSE CAST(cores AS INT) END AS cores
        FROM read_csv('{vmtable}', header=false, columns={VM_COLS})""")


def _size_sql(stat: str, ceiling: float) -> str:
    need = f"({stat} / 100.0 * cores / {ceiling})"
    cases = " ".join(f"WHEN {s} >= {need} AND {s} <= cores THEN {s}" for s in LADDER)
    return f"CASE {cases} ELSE cores END"


def fleet_stats(vmtable: str, min_life_s: int = 86400) -> dict:
    con = duckdb.connect()
    _vm(con, vmtable)
    n, = con.execute("SELECT count(*) FROM vm").fetchone()
    out = {"vms": n, "vms_min_life": con.execute(f"SELECT count(*) FROM vm WHERE deleted-created >= {min_life_s}").fetchone()[0]}
    out["by_cores"] = [dict(zip(("cores", "vms", "mean_p95", "mean_avg"), r)) for r in con.execute(
        "SELECT cores, count(*), round(avg(p95),1), round(avg(avgcpu),1) FROM vm GROUP BY 1 ORDER BY 1").fetchall()]
    out["by_category"] = [dict(zip(("category", "vms", "mean_p95", "mean_avg"), r)) for r in con.execute(
        "SELECT category, count(*), round(avg(p95),1), round(avg(avgcpu),1) FROM vm GROUP BY 1 ORDER BY 2 DESC").fetchall()]
    qs = con.execute("SELECT quantile_cont(p95, [0.1,0.25,0.5,0.75,0.9]) FROM vm").fetchone()[0]
    out["p95_quantiles"] = dict(zip(("p10", "p25", "p50", "p75", "p90"), [round(q, 1) for q in qs]))
    out["share_p95_below"] = {str(t): con.execute(f"SELECT avg((p95 < {t})::INT) FROM vm").fetchone()[0] for t in (10, 25, 50)}
    out["hindsight"] = []
    for stat, label in (("p95", "lifetime p95 of max CPU"), ("maxcpu", "lifetime max CPU")):
        for ceiling in (0.7, 0.85, 1.0):
            sz = _size_sql(stat, ceiling)
            r = con.execute(f"""SELECT sum(cores), sum({sz}), sum(cores*(deleted-created)), sum(({sz})*(deleted-created)),
                                      avg((({sz}) < cores)::INT) FROM vm WHERE deleted-created >= {min_life_s}""").fetchone()
            out["hindsight"].append({"sized_to": label, "ceiling": ceiling, "core_savings": 1 - r[1] / r[0],
                                     "core_hour_savings": 1 - r[3] / r[2], "share_vms_downsized": r[4]})
    return out


def micro_backtest(vmtable: str, shard: str, sample_mod: int = 10, ceiling: float = 0.85) -> dict:
    """Size each VM from the first half of the shard's 3.7 h window, replay the second half. Real data, short window:
    no daily cycle is visible, so this is a sanity check of the throttling arithmetic, not a forecasting benchmark."""
    con = duckdb.connect()
    _vm(con, vmtable)
    con.execute(f"""CREATE TABLE r AS SELECT CAST(ts/300 AS INT) step, vmid, maxcpu FROM read_csv('{shard}', header=false,
        columns={{'ts':'BIGINT','vmid':'VARCHAR','mincpu':'DOUBLE','maxcpu':'DOUBLE','avgcpu':'DOUBLE'}})
        WHERE hash(vmid) % {sample_mod} = 0""")
    steps = con.execute("SELECT max(step)+1 FROM r").fetchone()[0]
    full = con.execute(f"SELECT vmid FROM r GROUP BY 1 HAVING count(*) = {steps}").fetchall()
    ids = [f[0] for f in full]
    idx = {v: i for i, v in enumerate(ids)}
    X = np.zeros((len(ids), steps), dtype=np.float32)
    for vmid, step, m in con.execute("SELECT vmid, step, maxcpu FROM r").fetchall():
        if vmid in idx:
            X[idx[vmid], step] = m
    core_of = dict(con.execute("SELECT vmid, cores FROM vm WHERE vmid IN (SELECT vmid FROM r)").fetchall())
    cores = np.array([core_of[v] for v in ids])
    h = steps // 2
    hist, fut = X[:, :h], X[:, h:]

    def size(stat):
        need = stat / 100 * cores / ceiling
        new = cores.copy()
        for i, (c, nd) in enumerate(zip(cores, need)):
            for s in LADDER:
                if s >= nd and s <= c:
                    new[i] = s
                    break
        return new
    rows = []
    for name, stat in (("history max", hist.max(1)), ("history p95", np.quantile(hist, 0.95, axis=1))):
        new = size(stat)
        thr = (fut / 100 * cores[:, None] > new[:, None]).mean(axis=1)
        rows.append({"policy": name, "core_savings": 1 - new.sum() / cores.sum(), "vms_with_any_throttle": float((thr > 0).mean()),
                     "mean_throttled_share": float(thr.mean())})
    return {"vms_sampled": int(len(ids)), "steps": int(steps), "history_steps": int(h), "test_steps": int(steps - h),
            "window_hours": steps * 5 / 60, "ceiling": ceiling, "policies": rows}
