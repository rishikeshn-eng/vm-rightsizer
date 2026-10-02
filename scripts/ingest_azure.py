"""Build a VM sample matrix from the Azure Public Dataset V2, then run: python -m rightsize.run --npz data/sample.npz

    R=https://github.com/Azure/AzurePublicDataset/releases/download/dataset-v2   # file list: AzurePublicDatasetLinksV2.txt
    curl -LO $R/trace_data_vmtable_vmtable.csv.gz                                 # 437 MB
    curl -LO $R/trace_data_vm_cpu_readings_vm_cpu_readings-file-1-of-195.csv.gz   # 856 MB each; shards are TIME slices
    python scripts/ingest_azure.py trace_data_vmtable_vmtable.csv.gz trace_data_vm_cpu_readings_*.csv.gz --sample-mod 200 --days 14

14 days needs ~100 consecutive shards (~85 GB). For what one shard supports, use scripts/azure_real_report.py.
"""
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from rightsize.ingest import build_matrix

ap = argparse.ArgumentParser()
ap.add_argument("vmtable"); ap.add_argument("readings", nargs="+")
ap.add_argument("--sample-mod", type=int, default=200); ap.add_argument("--days", type=int, default=14)
ap.add_argument("--out", default="data/sample.npz")
a = ap.parse_args()
d, rep = build_matrix(a.vmtable, a.readings, a.sample_mod, a.days)
os.makedirs(os.path.dirname(a.out), exist_ok=True)
np.savez_compressed(a.out, **d)
print(rep, "->", a.out)
