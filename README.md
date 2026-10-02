# vm-rightsizer

Forecast each VM's CPU peak, recommend a smaller size, and backtest how often that recommendation would have throttled.

**Live UI:** https://rishikeshn-eng.github.io/vm-rightsizer/ (savings-vs-risk frontier, per-VM forecast vs reality)

> **Status: published numbers are from a synthetic fleet, not the Azure trace.**
> The generator (`rightsize/synth.py`) produces 800 VMs x 14 days of 5-minute max-CPU readings with the qualitative shape reported for Azure (mostly over-provisioned, some daily cycles, some batch bursts, rare spikes). It demonstrates the method and the backtest. The Azure ingest path (`rightsize/ingest.py`) is tested on a tiny file in the Azure V2 layout, but I have not run it on the real trace, which is 156 GB.

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
BASE=https://azurepublicdatasetv2.blob.core.windows.net/azurepublicdatasetv2/azure_v2
curl -O $BASE/vmtable.csv.gz
curl -O $BASE/vm_cpu_readings-file-1-of-125.csv.gz        # add shards for more coverage
python scripts/ingest_azure.py vmtable.csv.gz vm_cpu_readings-file-*.csv.gz --sample-mod 200 --days 14
python -m rightsize.run --npz data/sample.npz
```

`ingest.py` takes the stated sample `hash(vmid) % sample_mod == 0`, keeps VMs with >= 98% of the window's readings, and reports how many it kept. Check that report: if readings are sharded across files in a way I misread, coverage will be low and you'll see it. The URLs and column order come from the dataset's documentation as I know it; verify them against the dataset page before a long download.
