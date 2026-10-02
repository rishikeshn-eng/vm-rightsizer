"""python scripts/azure_real_report.py vmtable.csv.gz vm_cpu_readings-file-1-of-195.csv.gz  -> docs/azure_real.json"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rightsize import azure_real

vmtable, shard = sys.argv[1], sys.argv[2]
out = {"source": "Azure Public Dataset V2 (vmtable + readings shard 1 of 195)",
       "fleet": azure_real.fleet_stats(vmtable), "micro_backtest": azure_real.micro_backtest(vmtable, shard)}
json.dump(out, open("docs/azure_real.json", "w"), indent=1)
f = out["fleet"]
print(f["vms"], "VMs; p95 quantiles", f["p95_quantiles"])
for h in f["hindsight"]: print(h)
print(json.dumps(out["micro_backtest"], indent=1))
