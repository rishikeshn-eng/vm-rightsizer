# vm-rightsizer

Forecast each VM's CPU peak, recommend a smaller size, and backtest how often that recommendation would have throttled.

**Live UI:** https://rishikeshn-eng.github.io/vm-rightsizer/ (savings-vs-risk frontier, per-VM forecast vs reality)

> **Status: the forecasting backtest is on a synthetic fleet; there is also a real-data section from the actual Azure trace.**
> The synthetic generator (`rightsize/synth.py`) produces 800 VMs x 14 days of 5-minute max-CPU readings with the qualitative shape reported for Azure. The real section (`rightsize/azure_real.py`) uses the actual `vmtable` (all 2,695,548 VMs) plus one readings shard (3.75 hours). A multi-day real backtest would need ~100 readings shards (~85 GB), which I did not download.

## Real Azure results

From the real `vmtable` (lifetime max / avg / p95-of-max CPU per VM; VMs living at least a day for the savings rows):

- Real fleets are less idle than my synthetic fleet assumed: median VM p95-of-max CPU is **48.5%**, 25% of VMs sit under 10%, 10% are above 96%.
- **Hindsight** sizing (each VM sized from its own lifetime stats, 85% ceiling; an upper bound, not a backtest): sizing to lifetime **p95** removes **38.4%** of cores (36.1% of core-hours) and downsizes 61% of VMs; sizing to lifetime **max** removes only **4.4%**.
- **Short real backtest** (1,743 sampled VMs; size from the first 110 min of the shard, replay the next 115 min; 85% ceiling): "history max" removes 35.0% of cores and 5.2% of VMs throttle at least once; "history p95" removes 40.4% and 7.5% throttle. With so little history, "history max" looks far cheaper than lifetime data supports (4.4%), which is the failure a longer history prevents. This window has no daily cycle, so it checks the throttling arithmetic rather than forecasting skill.
- The real core buckets are 2/4/8/24/>24 (`>24` treated as 32); my synthetic ladder used 1/2/4/8/16/24.

## Method

- **Forecast** (`forecast.py`): per VM, the q-quantile of 5-minute max CPU for each (weekday/weekend, hour-of-day) slot in history, rescaled by the VM's last two days relative to what the profile implied (clipped to 0.7-1.5x so a trending VM is tracked without trusting one noisy day).
- **Recommend** (`recommend.py`): smallest size on the ladder 1/2/4/8/16/24 cores such that forecast peak cores / new size <= a ceiling (default 85%). Downsize only, never up. CPU only: memory is ignored, so a real deployment must also check memory fit.
- **Backtest**: rolling origins at days 6, 8, 10. Size from history only, then replay the next 3 real days against the smaller size. An interval is *throttled* if real peak demand in cores exceeds the new size. A VM *breaches* if more than 0.5% of its intervals are throttled.

## Results on the synthetic fleet

| policy | cores removed | VMs breaching SLO |
|---|---|---|
| baseline: size to history max | 8.1% | 0.2% |
| forecast, q=0.999, ceiling 85% | 8.1% | 0.3% |
| **forecast, q=0.99, ceiling 85%** | **11.1%** | **0.6%** |
| forecast, q=0.95, ceiling 85% | 28.6% | 2.8% |
| baseline: size to history p95 | 43.4% | 13.9% |

(Full 14-point frontier in the UI.) Takeaways, all conditional on the generator:
- You can buy savings with risk and the frontier is smooth; q is the dial. Sizing to the historical p95 (as one might from Azure's `p95maxcpu` column) removes the most cores but breaches the SLO on 1 in 7 VMs.
- The profile forecast's 99th-percentile pinball loss is 0.63 vs 2.61 for repeating yesterday.
- Against the cautious "size to history max" baseline the forecast is roughly even at the same risk; its value is the choice of operating point, not a free lunch.
- Spikes the generator injects are unforecastable by construction. The UI's top recommendation is such a case (6% historical peak, 95% the next day): the backtest counts it as a breach.
- ₹ savings use a placeholder ₹2,500 per core-month (`recommend.INR_PER_CORE_MONTH`). Replace it with your rate.

## Run

```bash
pip install numpy duckdb pytest
python -m pytest -q
python -m rightsize.run            # synthetic, ~3 s
python scripts/build_site.py
```

### On the real Azure trace

```bash
R=https://github.com/Azure/AzurePublicDataset/releases/download/dataset-v2   # links: AzurePublicDatasetLinksV2.txt
curl -LO $R/trace_data_vmtable_vmtable.csv.gz                                 # 437 MB
curl -LO $R/trace_data_vm_cpu_readings_vm_cpu_readings-file-1-of-195.csv.gz   # 856 MB; shards are TIME slices
python scripts/azure_real_report.py trace_data_vmtable_vmtable.csv.gz trace_data_vm_cpu_readings_vm_cpu_readings-file-1-of-195.csv.gz   # -> docs/azure_real.json, ~10 s
```

For a multi-day per-VM matrix, `scripts/ingest_azure.py` unions consecutive shards (14 days needs ~100) and feeds `python -m rightsize.run --npz`. That path is tested on a tiny file in the real layout, not on real multi-day data. (An earlier version of this README gave a wrong host, `-of-125` shard names, and assumed shards split by VM; all three are corrected here after checking the real files.)
