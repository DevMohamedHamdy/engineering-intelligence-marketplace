#!/usr/bin/env python3
"""EI performance — compare a baseline run with a candidate run. Prints/writes JSON; never judges without data.

  perf_compare.py <baseline-run> <candidate-run> [--project <root>] [--store <dir>] [--out comparison.json]
                  [--noise-pct 5] [--min-iterations 3]

Per (scenario, metric): n, median, mean, min, max, stdev per side; delta and % of medians; verdict:
  IMPROVED / REGRESSED   change exceeds noise AND both sides have >= min-iterations AND ranges do not overlap
  UNCHANGED              |change| within noise
  INCONCLUSIVE           too few iterations, or change exceeds noise but ranges overlap
  ONE-SIDED              metric only present on one side
Different platform / device / app build_type / git-dirty state are returned as `warnings` (comparability).
"""
import argparse, json, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf_lib as L  # noqa: E402


def summarize(vals):
    return {"n": len(vals), "median": statistics.median(vals), "mean": statistics.fmean(vals) if hasattr(statistics, "fmean") else sum(vals) / len(vals),
            "min": min(vals), "max": max(vals), "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0}


def group(metrics):
    g = {}
    for m in metrics:
        g.setdefault((m["scenario"], m["metric"]), {"unit": m["unit"], "lib": m["lower_is_better"], "v": []})["v"].append(m["value"])
    return g


def verdict(b, c, lib, noise, min_n):
    base = b["median"]
    pct = (c["median"] - base) / abs(base) * 100.0 if base else (0.0 if c["median"] == base else float("inf"))
    if abs(pct) <= noise:
        return "UNCHANGED", pct
    if b["n"] < min_n or c["n"] < min_n:
        return "INCONCLUSIVE", pct
    overlap = not (c["max"] < b["min"] or c["min"] > b["max"])
    if overlap:
        return "INCONCLUSIVE", pct
    better = (pct < 0) if lib else (pct > 0)
    return ("IMPROVED" if better else "REGRESSED"), pct


def compare(base_dir, cand_dir, noise=None, min_n=None):
    br, cr = L.load_json(base_dir / "run.json"), L.load_json(cand_dir / "run.json")
    noise = L.DEFAULT_THRESHOLDS["noise_pct"] if noise is None else noise
    min_n = L.DEFAULT_THRESHOLDS["min_iterations"] if min_n is None else min_n
    warn = []
    if br["role"] != "baseline" or cr["role"] != "candidate":
        warn.append("roles are %s vs %s (expected baseline vs candidate)" % (br["role"], cr["role"]))
    for r, n in ((br, "baseline"), (cr, "candidate")):
        if r["status"] != "complete": warn.append("%s run is not complete" % n)
        if (r.get("git") or {}).get("dirty"): warn.append("%s was recorded from a dirty working tree" % n)
    if br["platform"] != cr["platform"]: warn.append("platform differs: %s vs %s" % (br["platform"], cr["platform"]))
    if br["device"].get("id") != cr["device"].get("id"): warn.append("device differs: %s vs %s" % (br["device"].get("id"), cr["device"].get("id")))
    if br["app"].get("build_type") != cr["app"].get("build_type"): warn.append("build_type differs: %s vs %s" % (br["app"].get("build_type"), cr["app"].get("build_type")))
    bg, cg = group(L.read_metrics(base_dir)), group(L.read_metrics(cand_dir))
    rows = []
    for key in sorted(set(bg) | set(cg)):
        scenario, name = key
        if key not in bg or key not in cg:
            side = bg.get(key) or cg.get(key)
            rows.append({"scenario": scenario, "metric": name, "unit": side["unit"], "verdict": "ONE-SIDED",
                         "side": "baseline" if key in bg else "candidate"})
            continue
        b, c = summarize(bg[key]["v"]), summarize(cg[key]["v"])
        if bg[key]["unit"] != cg[key]["unit"]:
            warn.append("unit differs for %s/%s" % key); continue
        v, pct = verdict(b, c, bg[key]["lib"], noise, min_n)
        rows.append({"scenario": scenario, "metric": name, "unit": bg[key]["unit"], "lower_is_better": bg[key]["lib"],
                     "baseline": b, "candidate": c, "delta": c["median"] - b["median"], "delta_pct": pct, "verdict": v})
    counts = {}
    for r in rows: counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"schema": "ei.perf.comparison/1", "created_at": L.now(), "thresholds": {"noise_pct": noise, "min_iterations": min_n},
            "baseline": {"run_id": br["run_id"], "git": br.get("git"), "device": br["device"], "app": br["app"], "platform": br["platform"]},
            "candidate": {"run_id": cr["run_id"], "git": cr.get("git"), "device": cr["device"], "app": cr["app"], "platform": cr["platform"]},
            "warnings": warn, "summary": counts, "results": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline"); ap.add_argument("candidate")
    ap.add_argument("--project"); ap.add_argument("--store"); ap.add_argument("--out")
    ap.add_argument("--noise-pct", type=float); ap.add_argument("--min-iterations", type=int)
    a = ap.parse_args()
    store = L.store_root(a.project, a.store)
    res = compare(L.resolve_run(store, a.baseline), L.resolve_run(store, a.candidate), a.noise_pct, a.min_iterations)
    if a.out: L.write_json(a.out, res)
    else: print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
