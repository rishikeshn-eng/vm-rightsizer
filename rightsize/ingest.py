"""Azure Public Dataset V2 -> (maxcpu matrix, cores) for a stated sample of VMs.

Files (no headers), per https://github.com/Azure/AzurePublicDataset/blob/master/AzurePublicDatasetV2.md:
  vmtable.csv.gz:  vmid, subscriptionid, deploymentid, vmcreated, vmdeleted, maxcpu, avgcpu, p95maxcpu,
                   vmcategory, vmcorecountbucket, vmmemorybucket
  vm_cpu_readings-file-N-of-195.csv.gz: timestamp(s), vmid, mincpu, maxcpu, avgcpu   (5-minute readings)

Verified on the real files: shards are TIME slices (shard 1 = timestamps 0..13200 s for ~241k VMs), so a multi-day
per-VM matrix needs many consecutive shards (~100 for 14 days). `build_matrix` unions whatever shards you pass.
"""
from __future__ import annotations

import duckdb
import numpy as np

STEP = 300


def build_matrix(vmtable: str, readings: list[str], sample_mod: int = 200, days: int = 14,
                 min_coverage: float = 0.98):
    """Sample VMs with hash(vmid) % sample_mod == 0 that are present for >= min_coverage of `days`.

    Returns dict(maxcpu, cores, vmid) and a report with how many VMs were sampled / kept.
    Coverage is computed from the files you pass: if readings are sharded across files, pass all shards.
    """
    con = duckdb.connect()
    files = ", ".join("'" + r.replace("'", "''") + "'" for r in readings)
    con.execute(f"""
      CREATE TABLE vms AS
      SELECT vmid, CASE WHEN vmcorecountbucket LIKE '>%' THEN 32 ELSE CAST(vmcorecountbucket AS INT) END AS cores
      FROM read_csv('{vmtable}', header=false, columns={{'vmid':'VARCHAR','sub':'VARCHAR','dep':'VARCHAR',
        'created':'BIGINT','deleted':'BIGINT','maxcpu':'DOUBLE','avgcpu':'DOUBLE','p95':'DOUBLE',
        'category':'VARCHAR','vmcorecountbucket':'VARCHAR','mem':'VARCHAR'}})
      WHERE hash(vmid) % {sample_mod} = 0""")
    con.execute(f"""
      CREATE TABLE r AS
      SELECT vmid, CAST(timestamp / {STEP} AS BIGINT) AS step, max(maxcpu) AS maxcpu
      FROM read_csv([{files}], header=false, columns={{'timestamp':'BIGINT','vmid':'VARCHAR','mincpu':'DOUBLE',
        'maxcpu':'DOUBLE','avgcpu':'DOUBLE'}})
      WHERE vmid IN (SELECT vmid FROM vms) GROUP BY 1, 2""")
    n_steps = days * 288
    t0 = con.execute("SELECT min(step) FROM r").fetchone()[0]
    keep = con.execute(f"""SELECT vmid FROM r WHERE step >= {t0} AND step < {t0 + n_steps}
                           GROUP BY 1 HAVING count(*) >= {int(min_coverage * n_steps)} ORDER BY 1""").fetchall()
    ids = [k[0] for k in keep]
    X = np.zeros((len(ids), n_steps), dtype=np.float32)
    idx = {v: i for i, v in enumerate(ids)}
    for vmid, step, m in con.execute(f"SELECT vmid, step, maxcpu FROM r WHERE step >= {t0} AND step < {t0 + n_steps}").fetchall():
        if vmid in idx:
            X[idx[vmid], step - t0] = m
    cores = np.array([con.execute("SELECT cores FROM vms WHERE vmid = ?", [v]).fetchone()[0] for v in ids])
    sampled = con.execute("SELECT count(*) FROM vms").fetchone()[0]
    return {"maxcpu": X, "cores": cores, "vmid": np.array(ids)}, {"sampled_vms": sampled, "kept_vms": len(ids)}
