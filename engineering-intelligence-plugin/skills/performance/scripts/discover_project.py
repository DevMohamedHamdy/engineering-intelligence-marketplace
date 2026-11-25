#!/usr/bin/env python3
"""EI performance — detect a project's performance-relevant settings from its repository. Read-only.

  discover_project.py <project-root> [--json] [--write-config [--store <dir>]]

Nothing project-specific is hardcoded in EI: app ids, schemes, flavors, RN/Hermes/New-Architecture flags and existing
perf tooling are read from the repo (each value carries `source`). Missing values stay null — never guessed.
`--write-config` writes the detected values into the run store (outside the project), where scenarios,
thresholds and device choices are then added by the developer.
"""
import json, os, pathlib, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf_lib as L  # noqa: E402

PERF_TOOLS = {"react-native-performance": "RN performance marks", "reassure": "Reassure render perf tests",
              "@shopify/flash-list": "FlashList", "react-native-reanimated": "Reanimated", "@shopify/react-native-skia": "Skia",
              "react-native-flipper": "Flipper", "@perf-profiler/profiler": "Flashlight", "react-native-fast-image": "FastImage",
              "@sentry/react-native": "Sentry performance", "@react-native-firebase/perf": "Firebase Performance",
              "react-native-mmkv": "MMKV", "@shopify/react-native-performance": "Shopify RN performance"}


def read(p):
    try:
        return pathlib.Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def val(v, source):
    return {"value": v, "source": source} if v is not None else {"value": None, "source": None}


def rel(root, p):
    return str(pathlib.Path(p).relative_to(root))


def block(t, name):
    """Body of `name { ... }` by brace matching, or ''."""
    m = re.search(r"\b%s\s*\{" % name, t)
    if not m: return ""
    i, depth = m.end(), 1
    while i < len(t) and depth:
        depth += {"{": 1, "}": -1}.get(t[i], 0); i += 1
    return t[m.end():i - 1]


def top_names(body):
    """Names of the direct children `name {` of a block body."""
    names, depth, line = [], 0, ""
    for ch in body:
        if ch == "\n":
            m = re.match(r"\s*(\w+)\s*\{\s*$", line) if depth == 0 else None
            if m: names.append(m.group(1))
            line = ""
        else: line += ch
        depth += {"{": 1, "}": -1}.get(ch, 0)
        if ch == "{" and depth == 1:
            m = re.match(r"\s*(\w+)\s*\{$", line)
            if m: names.append(m.group(1)); line = ""
    return sorted(set(names))


def pkg_info(root):
    p = root / "package.json"
    t = read(p)
    if not t: return {}
    d = json.loads(t)
    deps = {**d.get("dependencies", {}), **d.get("devDependencies", {})}
    out = {"name": val(d.get("name"), "package.json"), "react_native": val(deps.get("react-native"), "package.json"),
           "react": val(deps.get("react"), "package.json"), "expo": val(deps.get("expo"), "package.json"),
           "perf_libraries": {k: {"version": deps[k], "what": w} for k, w in PERF_TOOLS.items() if k in deps},
           "scripts": sorted((d.get("scripts") or {}).keys())}
    out["package_manager"] = next((n for f, n in (("yarn.lock", "yarn"), ("pnpm-lock.yaml", "pnpm"), ("package-lock.json", "npm"), ("bun.lockb", "bun")) if (root / f).exists()), None)
    return out


def android_info(root):
    out = {"present": False}
    adir = next((root / d for d in ("android", ".") if (root / d / "app").is_dir() and any((root / d / "app" / n).exists() for n in ("build.gradle", "build.gradle.kts"))), None)
    if not adir: return out
    out["present"] = True
    out["dir"] = rel(root, adir) if adir != root else "."
    g = next((adir / "app" / n for n in ("build.gradle", "build.gradle.kts") if (adir / "app" / n).exists()), None)
    t = read(g) or ""
    src = rel(root, g)
    m = re.search(r'applicationId\s*=?\s*["\']([^"\']+)["\']', t)
    out["application_id"] = val(m.group(1) if m else None, src)
    m = re.search(r'namespace\s*=?\s*["\']([^"\']+)["\']', t)
    out["namespace"] = val(m.group(1) if m else None, src)
    out["build_types"] = top_names(block(t, "buildTypes"))
    out["flavors"] = top_names(block(t, "productFlavors"))
    out["debuggable_hint"] = bool(re.search(r"debuggable\s*=?\s*true", t))
    out["profileable_hint"] = bool(re.search(r"profileable", read(adir / "app/src/main/AndroidManifest.xml") or ""))
    gp = read(adir / "gradle.properties") or ""
    for key, name in (("hermesEnabled", "hermes_enabled"), ("newArchEnabled", "new_architecture"), ("reactNativeArchitectures", "abis")):
        m = re.search(r"^\s*%s\s*=\s*(.+)$" % key, gp, re.M)
        out[name] = val(m.group(1).strip() if m else None, rel(root, adir / "gradle.properties"))
    return out


def ios_info(root):
    out = {"present": False}
    idir = next((root / d for d in ("ios", ".") if list((root / d).glob("*.xcodeproj")) or list((root / d).glob("*.xcworkspace"))), None)
    if not idir: return out
    out["present"] = True
    out["dir"] = rel(root, idir) if idir != root else "."
    out["workspace"] = [p.name for p in idir.glob("*.xcworkspace")]
    projs = [p for p in idir.glob("*.xcodeproj")]
    out["project"] = [p.name for p in projs]
    schemes = set()
    for p in projs:
        for s in (p / "xcshareddata/xcschemes").glob("*.xcscheme") if (p / "xcshareddata/xcschemes").is_dir() else []:
            schemes.add(s.stem)
    out["shared_schemes"] = sorted(schemes)
    ids, cfgs = {}, set()
    for p in projs:
        t = read(p / "project.pbxproj") or ""
        for m in re.finditer(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*\"?([^\";]+)\"?;", t):
            ids[m.group(1)] = rel(root, p / "project.pbxproj")
        cfgs |= set(re.findall(r"/\* (\w+) \*/ = \{\s*isa = XCBuildConfiguration", t))
    out["bundle_ids"] = [{"value": k, "source": v} for k, v in sorted(ids.items())]
    out["build_configurations"] = sorted(cfgs)
    pod = read(idir / "Podfile") or ""
    m = re.search(r":hermes_enabled\s*=>\s*(\w+)", pod)
    out["hermes_enabled"] = val(m.group(1) if m else None, rel(root, idir / "Podfile"))
    m = re.search(r"RCT_NEW_ARCH_ENABLED\W+(\w+)", pod)
    out["new_architecture"] = val(m.group(1) if m else None, rel(root, idir / "Podfile"))
    return out


def discover(root):
    root = pathlib.Path(root).resolve()
    if not root.is_dir(): sys.exit("not a directory: %s" % root)
    pkg = pkg_info(root)
    return {"schema": "ei.perf.project/1", "detected_at": L.now(), "root": str(root), "git": L.git_state(str(root)),
            "package": pkg, "android": android_info(root), "ios": ios_info(root),
            "metro_config": [n for n in ("metro.config.js", "metro.config.ts") if (root / n).exists()],
            "cross_platform_note": "values are detected from files only; release/profileable build setup is not inferred"}


def to_config(det):
    return {"schema": "ei.perf.config/1", "project": det, "thresholds": dict(L.DEFAULT_THRESHOLDS),
            "defaults": {"iterations": 5, "warmup_iterations": 1, "duration_s": 30},
            "android": {"device": None, "app_id": det["android"].get("application_id", {}).get("value") if det["android"]["present"] else None, "build_type": None},
            "ios": {"device": None, "bundle_id": (det["ios"]["bundle_ids"][0]["value"] if det["ios"].get("bundle_ids") else None), "scheme": None, "configuration": None},
            "scenarios": [], "_note": "Fill device, build_type, scheme/configuration and scenarios yourself; detected values are suggestions to confirm."}


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args or "-h" in argv: print(__doc__); return 2
    det = discover(args[0])
    if "--write-config" in argv:
        store = pathlib.Path(argv[argv.index("--store") + 1]) if "--store" in argv else None
        d = L.store_root(args[0], str(store) if store else None)
        p = d / "ei-performance.config.json"
        if p.exists(): print("config exists, not overwritten:", p)
        else: L.write_json(p, to_config(det)); print("wrote", p)
        return 0
    print(json.dumps(det, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
