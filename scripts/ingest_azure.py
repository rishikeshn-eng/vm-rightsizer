"""Build a VM sample matrix from the Azure Public Dataset V2, then run: python -m rightsize.run --npz data/sample.npz

    BASE=https://azurepublicdatasetv2.blob.core.windows.net/azurepublicdatasetv2/azure_v2
    curl -O $BASE/vmtable.csv.gz
    curl -O $BASE/vm_cpu_readings-file-1-of-125.csv.gz        # add more shards for more coverage
    python scripts/ingest_azure.py vmtable.csv.gz vm_cpu_readings-file-*.csv.gz --sample-mod 200 --days 14

The full readings set is ~156 GB uncompressed; this takes a stated sample (hash(vmid) % sample_mod == 0).
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
