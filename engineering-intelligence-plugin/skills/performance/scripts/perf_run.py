#!/usr/bin/env python3
"""EI performance — run metadata and baseline/candidate run storage.

  perf_run.py init     --role baseline|candidate --platform ios|android --scenario <name> [--project <root>]
                       [--device <id>] [--app-id <id>] [--build-type <text>] [--label <text>] [--notes <text>] [--store <dir>]
  perf_run.py add      <run> --metrics <file.json|csv>        # append validated metric rows
  perf_run.py add-one  <run> --metric N --value V --unit U --scenario S [--iteration I] [--higher-is-better]
  perf_run.py complete <run>                                  # marks complete, rewrites metrics.csv, records checksums
  perf_run.py list     [--store <dir>] [--project <root>]
  perf_run.py show     <run>

<run> is '<role>/<run-id>', '<role>:latest', or a run directory. `init` prints the run directory.
Runs are stored OUTSIDE the project: $EI_PERF_HOME or ~/.ei-performance/<project-name>/runs/<role>/<run-id>/
  run.json  metrics.json  metrics.csv  artifacts/ (raw traces, dumps)
"""
import argparse, csv, hashlib, json, os, pathlib, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf_lib as L  # noqa: E402


def cmd_init(a):
    store = L.store_root(a.project, a.store)
    rid = "%s-%s" % (L.now().replace(":", "").replace("-", ""), uuid.uuid4().hex[:6])
    d = L.run_dir_of(store, a.role, rid)
    (d / "artifacts").mkdir(parents=True)
    run = {"schema": L.RUN_SCHEMA, "run_id": rid, "role": a.role, "platform": a.platform, "scenario": a.scenario,
           "label": a.label, "created_at": L.now(), "status": "collecting",
           "project": str(pathlib.Path(a.project).resolve()) if a.project else None,
           "git": L.git_state(a.project), "device": {"id": a.device}, "app": {"id": a.app_id, "build_type": a.build_type},
           "notes": a.notes, "checksums": {}}
    L.write_json(d / "run.json", run)
    L.write_metrics(d, [])
    print(d)


def cmd_add(a):
    d = L.resolve_run(L.store_root(a.project, a.store), a.run)
    p = pathlib.Path(a.metrics)
    if p.suffix == ".csv":
        rows = []
        for r in csv.DictReader(open(p, encoding="utf-8")):
            rows.append({"metric": r["metric"], "value": float(r["value"]), "unit": r["unit"], "platform": r["platform"],
                         "scenario": r["scenario"], "iteration": int(r["iteration"] or 1),
                         "lower_is_better": r["lower_is_better"].strip().lower() in ("true", "1", "yes"),
                         "source": r.get("source") or None})
    else:
        data = L.load_json(p)
        rows = data["metrics"] if isinstance(data, dict) else data
    return _append(d, rows)


def _append(d, rows):
    errs = [(i, e) for i, m in enumerate(rows) for e in L.validate_metric(m)]
    if errs:
        sys.exit("invalid metrics: " + "; ".join("row %d: %s" % x for x in errs[:10]))
    if L.load_json(d / "run.json")["status"] == "complete":
        sys.exit("run is complete; create a new run instead of editing it")
    L.write_metrics(d, L.read_metrics(d) + rows)
    print("%d metric rows added (%d total)" % (len(rows), len(L.read_metrics(d))))


def cmd_add_one(a):
    d = L.resolve_run(L.store_root(a.project, a.store), a.run)
    run = L.load_json(d / "run.json")
    _append(d, [L.metric(a.metric, a.value, a.unit, run["platform"], a.scenario, a.iteration, not a.higher_is_better, "manual")])


def cmd_complete(a):
    d = L.resolve_run(L.store_root(a.project, a.store), a.run)
    run = L.load_json(d / "run.json")
    metrics = L.read_metrics(d)
    if not metrics:
        sys.exit("refusing to complete a run with no metrics")
    L.write_metrics(d, metrics)
    run["status"], run["completed_at"] = "complete", L.now()
    run["checksums"] = {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in ("metrics.json", "metrics.csv")}
    run["iterations"] = len({(m["scenario"], m["iteration"]) for m in metrics})
    L.write_json(d / "run.json", run)
    print("complete:", d)


def cmd_list(a):
    store = L.store_root(a.project, a.store)
    runs = L.list_runs(store)
    if not runs:
        print("no runs in %s" % store)
    for role, rid, d in runs:
        r = L.load_json(d / "run.json")
        sha = (r.get("git") or {}).get("sha", "")[:9]
        print("%-9s %-28s %-8s %-18s %-10s %s%s" % (role, rid, r["platform"], r["scenario"], r["status"], sha,
                                                    " (dirty)" if (r.get("git") or {}).get("dirty") else ""))


def cmd_show(a):
    d = L.resolve_run(L.store_root(a.project, a.store), a.run)
    print(json.dumps(L.load_json(d / "run.json"), indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(p):
        p.add_argument("--project"); p.add_argument("--store")
    p = sub.add_parser("init"); common(p)
    p.add_argument("--role", required=True, choices=L.ROLES); p.add_argument("--platform", required=True, choices=L.PLATFORMS)
    p.add_argument("--scenario", required=True); p.add_argument("--device"); p.add_argument("--app-id")
    p.add_argument("--build-type"); p.add_argument("--label"); p.add_argument("--notes"); p.set_defaults(f=cmd_init)
    p = sub.add_parser("add"); common(p); p.add_argument("run"); p.add_argument("--metrics", required=True); p.set_defaults(f=cmd_add)
    p = sub.add_parser("add-one"); common(p); p.add_argument("run")
    p.add_argument("--metric", required=True); p.add_argument("--value", type=float, required=True)
    p.add_argument("--unit", required=True); p.add_argument("--scenario", required=True)
    p.add_argument("--iteration", type=int, default=1); p.add_argument("--higher-is-better", action="store_true")
    p.set_defaults(f=cmd_add_one)
    p = sub.add_parser("complete"); common(p); p.add_argument("run"); p.set_defaults(f=cmd_complete)
    p = sub.add_parser("list"); common(p); p.set_defaults(f=cmd_list)
    p = sub.add_parser("show"); common(p); p.add_argument("run"); p.set_defaults(f=cmd_show)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
