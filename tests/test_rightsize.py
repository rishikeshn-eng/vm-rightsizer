import gzip

import numpy as np

from rightsize import synth
from rightsize.forecast import STEPS_PER_DAY, forecast_peak
from rightsize.ingest import build_matrix
from rightsize.recommend import Policy, backtest, recommend_cores


def test_recommend_only_downsizes_and_respects_ladder():
    cores = np.array([8, 8, 4, 1])
    peak = np.array([[10.0], [90.0], [50.0], [100.0]])
    new = recommend_cores(peak, cores, ceiling=0.85)
    assert list(new) == [1, 8, 4, 1]  # 0.8 cores -> size 1; 7.2 cores needs 8.5 -> no upsize, stays 8


def test_forecast_tracks_a_daily_cycle():
    day = np.concatenate([np.full(144, 10.0), np.full(144, 50.0)])
    hist = np.tile(day, 8)[None, :]
    f = forecast_peak(hist, STEPS_PER_DAY, q=0.9)
    assert abs(f[0, :144].mean() - 10) < 2 and abs(f[0, 144:].mean() - 50) < 5


def test_backtest_flat_load_downsizes_without_throttling():
    X = np.full((20, 14 * STEPS_PER_DAY), 5.0, dtype=np.float32)
    cores = np.full(20, 8)
    r = backtest(X, cores, Policy("p", 0.99, 0.85))
    assert r["core_savings"] > 0.5 and r["viol"] == 0.0


def test_backtest_catches_unforecast_spike():
    X = np.full((10, 14 * STEPS_PER_DAY), 5.0, dtype=np.float32)
    X[:, 10 * STEPS_PER_DAY + 5: 10 * STEPS_PER_DAY + 60] = 100.0  # spike in the held-out window
    cores = np.full(10, 8)
    r = backtest(X, cores, Policy("p", 0.99, 0.85), origins=(10,))
    assert r["viol"] == 1.0


def test_synth_shape():
    d = synth.generate(50, 7)
    assert d["maxcpu"].shape == (50, 7 * 288) and d["maxcpu"].max() <= 100


def test_ingest_parses_azure_v2_layout(tmp_path):
    vmt = tmp_path / "vmtable.csv.gz"
    rd = tmp_path / "vm_cpu_readings-file-1-of-125.csv.gz"
    vm_rows, rd_rows = [], []
    for i in range(30):
        vm_rows.append(f"vm{i},s,d,0,86400,50,20,40,Interactive,{'>24' if i == 0 else 4},8")
        for step in range(2 * 288):
            rd_rows.append(f"{step * 300},vm{i},1,{10 + i % 5},5")
    vmt.write_bytes(gzip.compress("\n".join(vm_rows).encode()))
    rd.write_bytes(gzip.compress("\n".join(rd_rows).encode()))
    d, rep = build_matrix(str(vmt), [str(rd)], sample_mod=1, days=2)
    assert rep == {"sampled_vms": 30, "kept_vms": 30}
    assert d["maxcpu"].shape == (30, 576) and set(d["cores"]) == {4, 32}


def test_azure_real_analysis_on_tiny_real_layout_files(tmp_path):
    from rightsize import azure_real
    vm_rows, rd_rows = [], []
    for i in range(40):
        p95 = 10.0 if i % 2 == 0 else 95.0
        life = 2 * 86400
        vm_rows.append(f"vm{i},s,d,0,{life},{p95},5,{p95},Interactive,{'>24' if i == 0 else 8},32")
        for step in range(45):
            rd_rows.append(f"{step * 300},vm{i},1,{p95},5")
    vmt, rd = tmp_path / "vmtable.csv.gz", tmp_path / "shard.csv.gz"
    vmt.write_bytes(gzip.compress("\n".join(vm_rows).encode()))
    rd.write_bytes(gzip.compress("\n".join(rd_rows).encode()))
    f = azure_real.fleet_stats(str(vmt))
    assert f["vms"] == 40
    h = {(x["sized_to"], x["ceiling"]): x for x in f["hindsight"]}
    assert h[("lifetime p95 of max CPU", 0.85)]["core_savings"] > 0.3   # idle half of the fleet is downsized
    assert h[("lifetime max CPU", 1.0)]["core_savings"] > 0.3          # here max == p95
    m = azure_real.micro_backtest(str(vmt), str(rd), sample_mod=1)
    assert m["vms_sampled"] == 40 and m["steps"] == 45 and m["policies"][0]["vms_with_any_throttle"] == 0.0
