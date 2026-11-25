"""Shared helpers for the EI performance engine (stdlib only, Python 3.8+)."""
import csv, datetime, hashlib, json, os, pathlib, re, subprocess

RUN_SCHEMA = "ei.perf.run/1"
METRICS_SCHEMA = "ei.perf.metrics/1"
ROLES = ("baseline", "candidate")
PLATFORMS = ("ios", "android")
CSV_FIELDS = ["metric", "value", "unit", "platform", "scenario", "iteration", "lower_is_better", "source"]
DEFAULT_THRESHOLDS = {"noise_pct": 5.0, "min_iterations": 3}


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(s):
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", s).strip("-").lower() or "project"


def sh(cmd, cwd=None, timeout=20):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_state(project):
    if not project:
        return None
    sha = sh(["git", "rev-parse", "HEAD"], project)
    if not sha:
        return None
    return {"sha": sha, "branch": sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], project),
            "dirty": bool(sh(["git", "status", "--porcelain"], project))}


def store_root(project=None, override=None):
    """Run storage lives OUTSIDE the project (EI never writes files into the target repo)."""
    base = override or os.environ.get("EI_PERF_HOME") or str(pathlib.Path.home() / ".ei-performance")
    return pathlib.Path(base).expanduser() / (slug(pathlib.Path(project).resolve().name) if project else "default")


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json(p, data):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def metric(name, value, unit, platform, scenario, iteration=1, lower_is_better=True, source=None):
    return {"metric": name, "value": float(value), "unit": unit, "platform": platform, "scenario": scenario,
            "iteration": int(iteration), "lower_is_better": lower_is_better, "source": source}


def read_metrics(run_dir):
    p = pathlib.Path(run_dir) / "metrics.json"
    if not p.exists():
        return []
    return load_json(p).get("metrics", [])


def write_metrics(run_dir, metrics):
    run_dir = pathlib.Path(run_dir)
    write_json(run_dir / "metrics.json", {"schema": METRICS_SCHEMA, "metrics": metrics})
    with open(run_dir / "metrics.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for m in metrics:
            w.writerow({k: m.get(k) for k in CSV_FIELDS})


def validate_metric(m):
    errs = []
    for k in ("metric", "value", "unit", "platform", "scenario", "iteration", "lower_is_better"):
        if k not in m:
            errs.append("missing " + k)
    if m.get("platform") not in PLATFORMS:
        errs.append("platform must be ios|android")
    if not isinstance(m.get("value"), (int, float)) or isinstance(m.get("value"), bool):
        errs.append("value must be a number")
    return errs


def run_dir_of(store, role, run_id):
    return pathlib.Path(store) / "runs" / role / run_id


def list_runs(store, role=None):
    out = []
    for r in (ROLES if role is None else (role,)):
        base = pathlib.Path(store) / "runs" / r
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if (d / "run.json").exists():
                    out.append((r, d.name, d))
    return out


def resolve_run(store, ref):
    """ref = '<role>/<run-id>', a path, or '<role>:latest' (latest complete run of that role)."""
    p = pathlib.Path(ref).expanduser()
    if (p / "run.json").exists():
        return p
    if ref.endswith(":latest"):
        role = ref.split(":")[0]
        runs = [d for _, _, d in list_runs(store, role) if load_json(d / "run.json").get("status") == "complete"]
        if not runs:
            raise SystemExit("no complete %s run in %s" % (role, store))
        return runs[-1]
    if "/" in ref:
        role, rid = ref.split("/", 1)
        d = run_dir_of(store, role, rid)
        if (d / "run.json").exists():
            return d
    raise SystemExit("run not found: %s" % ref)
