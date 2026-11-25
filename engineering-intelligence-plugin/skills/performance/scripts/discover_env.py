#!/usr/bin/env python3
"""EI performance — read-only environment discovery. Installs nothing, starts nothing, changes nothing.

  python3 -I discover_env.py [android|ios|tools|all] [--json]

Android: SDK root, adb, emulator, avds, connected devices (+ model, API level, ABI, debuggable-ness not probed).
iOS:     Xcode, xctrace + its templates, simctl runtimes/devices, physical devices (xctrace list devices).
Tools:   perfetto, trace_processor, simpleperf, idb, ios-deploy, node, watchman, flamegraph helpers.
Every item is {found, path, version, note}; a missing tool is reported, never an error.
"""
import json, os, pathlib, platform, shutil, subprocess, sys

HOME = pathlib.Path.home()


def run(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def item(found, path=None, version=None, note=None):
    return {"found": bool(found), "path": path, "version": version, "note": note}


def first_line(text):
    for ln in text.splitlines():
        if ln.strip():
            return ln.strip()
    return None


def sdk_roots():
    seen = []
    for v in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
              str(HOME / "Library/Android/sdk"), str(HOME / "Android/Sdk")):
        if v:
            p = pathlib.Path(v).expanduser().resolve()
            if p.is_dir() and p not in seen:
                seen.append(p)
    return seen


def find_tool(name, extra_dirs=()):
    p = shutil.which(name)
    if p:
        return p
    for d in extra_dirs:
        c = pathlib.Path(d) / name
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def android():
    out = {"sdk_roots": [str(r) for r in sdk_roots()]}
    dirs = []
    for r in sdk_roots():
        dirs += [r / "platform-tools", r / "emulator", r / "cmdline-tools/latest/bin", r / "tools/bin"]
    adb = find_tool("adb", dirs)
    if adb:
        _, v = run([adb, "version"])
        out["adb"] = item(True, adb, first_line(v), None if shutil.which("adb") else "not on PATH (found in SDK)")
    else:
        out["adb"] = item(False, note="install Android platform-tools")
    emu = find_tool("emulator", dirs)
    if emu:
        _, v = run([emu, "-version"])
        ver = next((l.strip() for l in v.splitlines() if "emulator version" in l.lower()), first_line(v))
        out["emulator"] = item(True, emu, ver, None if shutil.which("emulator") else "not on PATH (found in SDK)")
        _, a = run([emu, "-list-avds"])
        out["avds"] = [l.strip() for l in a.splitlines() if l.strip() and " " not in l.strip()]
    else:
        out["emulator"] = item(False)
        out["avds"] = []
    sm = find_tool("sdkmanager", dirs)
    out["sdkmanager"] = item(bool(sm), sm)
    out["devices"] = []
    if adb:
        _, d = run([adb, "devices", "-l"])
        for ln in d.splitlines()[1:]:
            parts = ln.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            dev = {"serial": serial, "state": state, "kind": "emulator" if serial.startswith("emulator-") else "physical"}
            if state == "device":
                for key, prop in (("model", "ro.product.model"), ("android", "ro.build.version.release"),
                                  ("api", "ro.build.version.sdk"), ("abi", "ro.product.cpu.abi"),
                                  ("build_type", "ro.build.type")):
                    _, v = run([adb, "-s", serial, "shell", "getprop", prop], 10)
                    dev[key] = v.strip() or None
            out["devices"].append(dev)
    return out


def ios():
    out = {"supported_host": platform.system() == "Darwin"}
    if not out["supported_host"]:
        return out
    rc, p = run(["xcode-select", "-p"])
    out["developer_dir"] = p.strip() if rc == 0 else None
    xb = shutil.which("xcodebuild")
    if xb:
        rc, v = run([xb, "-version"])
        out["xcode"] = item(rc == 0, xb, " ".join(v.split("\n")[:2]).strip() if rc == 0 else None,
                            None if rc == 0 else first_line(v))
    else:
        out["xcode"] = item(False)
    xt = shutil.which("xctrace")
    if xt:
        _, v = run([xt, "version"])
        out["xctrace"] = item(True, xt, first_line(v))
        _, t = run([xt, "list", "templates"], 30)
        names = [l.strip() for l in t.splitlines() if l.strip() and not l.startswith("==")]
        out["xctrace_templates"] = names
        out["template_check"] = {n: any(n.lower() == x.lower() for x in names)
                                 for n in ("Time Profiler", "Allocations", "Animation Hitches")}
        _, d = run([xt, "list", "devices"], 30)
        section, devs, sims = None, [], []
        for ln in d.splitlines():
            s = ln.strip()
            if s.startswith("== "):
                section = s.strip("= ").lower()
            elif s and section:
                (sims if "simulator" in section else devs).append(s)
        out["devices"] = [x for x in devs]
        out["simulators"] = sims
    else:
        out["xctrace"] = item(False)
    xr = shutil.which("xcrun")
    if xr:
        rc, v = run([xr, "simctl", "list", "devices", "booted"], 20)
        out["booted_simulators"] = [l.strip() for l in v.splitlines() if "(Booted)" in l] if rc == 0 else []
        rc, v = run([xr, "devicectl", "list", "devices"], 20)
        out["devicectl_devices"] = [l.rstrip() for l in v.splitlines() if l.strip()][:20] if rc == 0 else []
    for t in ("ios-deploy", "idb", "idevice_id"):
        p = shutil.which(t)
        out[t] = item(bool(p), p)
    return out


def tools():
    dirs = []
    for r in sdk_roots():
        dirs += [r / "platform-tools", r / "ndk-bundle", r / "cmake"]
    out = {}
    for name in ("perfetto", "trace_processor", "traceconv", "simpleperf", "python3", "node", "watchman",
                 "flamegraph.pl", "speedscope", "hermes", "gradle"):
        p = find_tool(name, dirs)
        v = None
        if p and name in ("node", "python3", "gradle"):
            _, o = run([p, "--version"])
            v = first_line(o)
        out[name] = item(bool(p), p, v)
    # on-device Perfetto is part of Android 9+ (checked per device by android scripts); host perfetto is optional
    out["notes"] = ["perfetto on-device binary ships with Android 9+; host `perfetto` is only needed for local capture helpers",
                    "trace_processor is needed to extract metrics from .perfetto-trace files"]
    return out


def main(argv):
    what = next((a for a in argv if not a.startswith("-")), "all")
    if what not in ("android", "ios", "tools", "all"):
        print(__doc__); return 2
    res = {}
    if what in ("android", "all"): res["android"] = android()
    if what in ("ios", "all"): res["ios"] = ios()
    if what in ("tools", "all"): res["tools"] = tools()
    if "--json" in argv:
        print(json.dumps(res, indent=2)); return 0
    for sec, data in res.items():
        print("== %s ==" % sec)
        for k, v in data.items():
            if isinstance(v, dict) and "found" in v:
                print("  %-14s %s %s %s" % (k, "FOUND  " if v["found"] else "MISSING", v["path"] or "", v["version"] or ""))
                if v.get("note"): print("                 note: %s" % v["note"])
            elif isinstance(v, list):
                print("  %s: %s" % (k, "(none)" if not v else ""))
                for x in v: print("    - %s" % (json.dumps(x) if isinstance(x, dict) else x))
            else:
                print("  %s: %s" % (k, json.dumps(v) if isinstance(v, dict) else v))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
