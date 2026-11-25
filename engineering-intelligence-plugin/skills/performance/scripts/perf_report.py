#!/usr/bin/env python3
"""EI performance — Markdown report from a comparison (or a single run). Reports measured numbers only.

  perf_report.py <baseline-run> <candidate-run> [--project <root>] [--store <dir>] [--out report.md] [--noise-pct N] [--min-iterations N]
  perf_report.py --comparison comparison.json [--out report.md]
  perf_report.py --run <run> [--out report.md]            # single-run summary, no comparison

Without --out the report is printed. EI never writes reports into the target project unless you pass a path there.
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf_lib as L, perf_compare as C  # noqa: E402

ICON = {"IMPROVED": "improved", "REGRESSED": "REGRESSED", "UNCHANGED": "unchanged", "INCONCLUSIVE": "inconclusive", "ONE-SIDED": "one-sided"}


def f(x):
    return "%.2f" % x if abs(x) < 1000 else "%.0f" % x


def side(s):
    g = s.get("git") or {}
    return "`%s` %s%s" % ((g.get("sha") or "no-git")[:9], g.get("branch") or "", " (dirty)" if g.get("dirty") else "")


def render(res):
    o = ["# Performance comparison", "",
         "| | Baseline | Candidate |", "|---|---|---|",
         "| Run | %s | %s |" % (res["baseline"]["run_id"], res["candidate"]["run_id"]),
         "| Git | %s | %s |" % (side(res["baseline"]), side(res["candidate"])),
         "| Platform | %s | %s |" % (res["baseline"]["platform"], res["candidate"]["platform"]),
         "| Device | %s | %s |" % (res["baseline"]["device"].get("id"), res["candidate"]["device"].get("id")),
         "| Build | %s | %s |" % (res["baseline"]["app"].get("build_type"), res["candidate"]["app"].get("build_type")), ""]
    t = res["thresholds"]
    o.append("Noise threshold: %s%% · minimum iterations: %s · values are medians across iterations." % (t["noise_pct"], t["min_iterations"]))
    o.append("")
    o.append("**Summary:** " + (", ".join("%d %s" % (n, ICON[k]) for k, n in sorted(res["summary"].items())) or "no metrics"))
    o.append("")
    if res["warnings"]:
        o += ["## Comparability warnings", ""] + ["- " + w for w in res["warnings"]] + [""]
    for scenario in sorted({r["scenario"] for r in res["results"]}):
        o += ["## Scenario: %s" % scenario, "", "| Metric | Unit | Baseline (n) | Candidate (n) | Δ | Δ % | Verdict |", "|---|---|---|---|---|---|---|"]
        for r in (x for x in res["results"] if x["scenario"] == scenario):
            if r["verdict"] == "ONE-SIDED":
                o.append("| %s | %s | – | – | – | – | one-sided (%s only) |" % (r["metric"], r["unit"], r["side"])); continue
            b, c = r["baseline"], r["candidate"]
            o.append("| %s | %s | %s (%d) [%s–%s] | %s (%d) [%s–%s] | %s | %+.1f%% | %s |" % (
                r["metric"], r["unit"], f(b["median"]), b["n"], f(b["min"]), f(b["max"]),
                f(c["median"]), c["n"], f(c["min"]), f(c["max"]), ("%+.2f" % r["delta"]), r["delta_pct"], ICON[r["verdict"]]))
        o.append("")
    o += ["## How to read this", "",
          "- *improved* / *REGRESSED*: change beyond the noise threshold, enough iterations on both sides, and the min–max ranges do not overlap.",
          "- *inconclusive*: change beyond noise but too few iterations or overlapping ranges — repeat the runs before concluding anything.",
          "- Only metrics that were measured appear here; nothing is estimated. Debug builds, emulators and dirty trees are not comparable to release/device numbers.", ""]
    return "\n".join(o)


def render_run(d):
    r = L.load_json(d / "run.json")
    o = ["# Performance run %s" % r["run_id"], "", "- Role: %s · Platform: %s · Scenario: %s · Status: %s" % (r["role"], r["platform"], r["scenario"], r["status"]),
         "- Git: %s" % (side(r) if r.get("git") else "n/a"), "- Device: %s · Build: %s" % (r["device"].get("id"), r["app"].get("build_type")), "",
         "| Metric | Unit | n | Median | Min | Max |", "|---|---|---|---|---|---|"]
    for (sc, name), g in sorted(C.group(L.read_metrics(d)).items()):
        s = C.summarize(g["v"])
        o.append("| %s / %s | %s | %d | %s | %s | %s |" % (sc, name, g["unit"], s["n"], f(s["median"]), f(s["min"]), f(s["max"])))
    return "\n".join(o) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline", nargs="?"); ap.add_argument("candidate", nargs="?")
    ap.add_argument("--comparison"); ap.add_argument("--run"); ap.add_argument("--project"); ap.add_argument("--store")
    ap.add_argument("--out"); ap.add_argument("--noise-pct", type=float); ap.add_argument("--min-iterations", type=int)
    a = ap.parse_args()
    store = L.store_root(a.project, a.store)
    if a.run: text = render_run(L.resolve_run(store, a.run))
    elif a.comparison: text = render(L.load_json(a.comparison))
    elif a.baseline and a.candidate:
        text = render(C.compare(L.resolve_run(store, a.baseline), L.resolve_run(store, a.candidate), a.noise_pct, a.min_iterations))
    else: ap.error("give <baseline> <candidate>, --comparison, or --run")
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w", encoding="utf-8").write(text); print("wrote", a.out)
    else: print(text)


if __name__ == "__main__":
    main()
