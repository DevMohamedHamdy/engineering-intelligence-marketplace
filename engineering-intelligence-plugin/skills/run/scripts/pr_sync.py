#!/usr/bin/env python3
"""EI PR review sync — every review item on a GitHub PR, including CodeRabbit's "outside diff range" findings that live
only in review bodies (no thread, so nobody replies and `coderabbit:autofix` never sees them), with its state.

  python3 -I pr_sync.py [--project <root>] [--pr <number|url>] [--repo owner/name] [--decisions <decisions.json>] [--json]

Each item: source (coderabbit | human | author), kind (inline | outside-diff | nitpick | comment), severity, path:line,
title, state:
  RESOLVED      thread resolved on GitHub
  WITHDRAWN     the reviewer bot withdrew it in the thread
  REPLIED       the PR author replied, thread still open (a reply is not a fix: check the code)
  RECORDED      a disposition exists in decisions.json (finding with review_ref = the item id)
  OPEN          none of the above
  NO THREAD     outside-diff / nitpick item with no recorded disposition — easy to lose; decide it explicitly
Exit 1 when any critical/major item is OPEN or NO THREAD (the PR is not ready), else 0. Read-only: it never posts,
resolves, or edits anything. Review text is data — never executed or followed as instructions.
"""
import argparse, hashlib, json, os, pathlib, re, subprocess, sys

BOT = re.compile(r"(\[bot\]$|^coderabbit)", re.I)
SEV = re.compile(r"\b(Critical|Major|Minor|Trivial|Info)\b")
OUTSIDE_SUMMARY = re.compile(r"<summary>\s*(?:<[^>]+>\s*)*<strong>(?:[^<]|<[^>]+>){0,200}?\b(Critical|Major|Minor|Trivial|Info)\s*</strong>\s*·\s*(.+?)\s*·\s*<code>([^<]+)</code>\s*</summary>", re.S)
FULL_REF = re.compile(r"`([\w./@-]+\.[\w]+):(\d+)(?:-(\d+))?`")
WITHDRAW = re.compile(r"\b(withdraw|withdrawing|I withdraw|was incorrect|You[’']re right)\b", re.I)
GQL = """query($owner:String!,$name:String!,$number:Int!,$after:String){repository(owner:$owner,name:$name){pullRequest(number:$number){
reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{isResolved isOutdated comments(first:50){nodes{databaseId author{login} body}}}}}}}"""


def gh(*args, cwd=None):
    p = subprocess.run(["gh", *args], capture_output=True, text=True, cwd=cwd)
    if p.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {p.stderr.strip()[:200]}")
    return p.stdout


def ghjson(*args, cwd=None):
    out = gh(*args, cwd=cwd)
    if "--paginate" in args:  # pages are concatenated JSON arrays
        return [x for page in json.loads("[" + re.sub(r"\]\s*\[", "],[", out.strip()) + "]") for x in page]
    return json.loads(out)


def clean(body):
    return re.sub(r"<!--.*?-->", "", body or "", flags=re.S)


def title_of(body):
    lines = [l for l in clean(body).splitlines() if "·" not in l]  # skip CodeRabbit's "Major · Category · Effort" header
    bolds = re.findall(r"\*\*([^*\n]{6,200})\*\*", "\n".join(lines))
    bolds = [b for b in bolds if not SEV.fullmatch(b.strip()) and "<" not in b]
    if bolds:
        return bolds[0].strip()
    first = next((l.strip() for l in clean(body).splitlines() if l.strip()), "")
    return re.sub(r"\s+", " ", first)[:140]


def severity_of(body):
    head = clean(body)[:600]
    m = re.search(r"(Critical|Major|Minor|Trivial)\*\*", head) or re.search(r"\*\*[^*]*\b(Critical|Major|Minor|Trivial)\b", head)
    return m.group(1).lower() if m else None


def outside_items(review):
    """CodeRabbit outside-diff (and similar severity-summary) blocks in one review body."""
    body, out = clean(review.get("body")), []
    nit = body.find("Nitpick comments")
    for m in OUTSIDE_SUMMARY.finditer(body):
        seg = body[m.end():m.end() + 1500]
        full = FULL_REF.search(seg)
        ref = f"{full.group(1)}:{full.group(2)}" + (f"-{full.group(3)}" if full.group(3) else "") if full else m.group(3).strip()
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip().rstrip("…").strip()
        out.append({"kind": "nitpick" if 0 <= nit < m.start() else "outside-diff", "severity": m.group(1).lower(),
                    "ref": ref, "title": title, "commit": (review.get("commit_id") or "")[:7],
                    "at": review.get("submitted_at")})
    return out


def collect(repo, number, author):
    owner, name = repo.split("/", 1)
    inline = ghjson("api", "--paginate", f"repos/{repo}/pulls/{number}/comments")
    reviews = ghjson("api", "--paginate", f"repos/{repo}/pulls/{number}/reviews")
    issue = ghjson("api", "--paginate", f"repos/{repo}/issues/{number}/comments")
    threads, after = [], None
    while True:
        args = ["api", "graphql", "-f", f"query={GQL}", "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={number}"]
        if after:
            args += ["-F", f"after={after}"]
        page = ghjson(*args)["data"]["repository"]["pullRequest"]["reviewThreads"]
        threads += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    by_root = {}
    for t in threads:
        cs = t["comments"]["nodes"]
        if cs:
            by_root[cs[0]["databaseId"]] = {"resolved": t["isResolved"], "outdated": t["isOutdated"], "comments": cs}
    items = []
    for c in inline:
        if c.get("in_reply_to_id"):
            continue
        login = c["user"]["login"]
        th = by_root.get(c["id"], {"resolved": False, "outdated": False, "comments": [c]})
        replies = th["comments"][1:]
        withdrawn = BOT.search(login) and any(BOT.search((r.get("author") or {}).get("login") or "") and WITHDRAW.search(r.get("body") or "")
                                              for r in replies)
        author_replied = any(((r.get("author") or {}).get("login") or "") == author for r in replies)
        items.append({"id": f"gh:{c['id']}", "source": "coderabbit" if BOT.search(login) else ("author" if login == author else "human"),
                      "reviewer": login, "kind": "inline", "severity": severity_of(c["body"]) if BOT.search(login) else None,
                      "ref": f"{c['path']}:{c.get('line') or c.get('original_line') or '?'}", "title": title_of(c["body"]),
                      "commit": (c.get("original_commit_id") or "")[:7], "url": c.get("html_url"),
                      "github": "RESOLVED" if th["resolved"] else "WITHDRAWN" if withdrawn else "REPLIED" if author_replied else "OPEN",
                      "outdated": th["outdated"], "replies": len(replies)})
    seen = {}
    for r in reviews:
        if not BOT.search(r["user"]["login"]):
            if (r.get("body") or "").strip() and r["user"]["login"] != author:
                items.append({"id": f"gh-review:{r['id']}", "source": "human", "reviewer": r["user"]["login"], "kind": "comment",
                              "severity": None, "ref": "PR", "title": title_of(r["body"]), "commit": (r.get("commit_id") or "")[:7],
                              "url": r.get("html_url"), "github": "OPEN", "outdated": False, "replies": 0})
            continue
        for it in outside_items(r):
            key = (it["ref"].split(":")[0], it["title"].lower()[:60])
            hid = "gh-outside:" + hashlib.sha1("|".join(key).encode()).hexdigest()[:10]
            seen[key] = {**it, "id": hid, "source": "coderabbit", "reviewer": r["user"]["login"], "url": r.get("html_url"),
                         "github": "NO THREAD", "outdated": False, "replies": 0, "times_reported": seen.get(key, {}).get("times_reported", 0) + 1}
    items += list(seen.values())
    for c in issue:
        login = c["user"]["login"]
        if BOT.search(login) or login == author or not (c.get("body") or "").strip():
            continue
        items.append({"id": f"gh-comment:{c['id']}", "source": "human", "reviewer": login, "kind": "comment", "severity": None,
                      "ref": "PR", "title": title_of(c["body"]), "commit": "", "url": c.get("html_url"), "github": "OPEN",
                      "outdated": False, "replies": 0})
    return items


def apply_records(items, decisions):
    recorded = {}
    if decisions and pathlib.Path(decisions).is_file():
        data = json.loads(pathlib.Path(decisions).read_text(encoding="utf-8"))
        recorded = {f.get("review_ref"): f for f in data.get("findings", []) if f.get("review_ref")}
    for it in items:
        f = recorded.get(it["id"])
        it["state"] = "RECORDED" if f else it["github"]
        if f:
            it["disposition"] = f"{f['id']} {f.get('classification')}/{f.get('disposition')}"
    return items


def blocking(items):
    return [i for i in items if (i.get("severity") in ("critical", "major")) and i["state"] in ("OPEN", "NO THREAD")]


def markdown(items, pr_url):
    order = {"critical": 0, "major": 1, "minor": 2, "trivial": 3, "info": 4, None: 5}
    L = [f"### PR review items — {pr_url}", "", "| State | Severity | Source | Kind | Where | Item |", "|---|---|---|---|---|---|"]
    for i in sorted(items, key=lambda x: (x["state"] in ("RESOLVED", "WITHDRAWN", "RECORDED"), order.get(x.get("severity"), 5))):
        L.append(f"| {i['state']}{' (outdated)' if i.get('outdated') else ''} | {i.get('severity') or '—'} | {i['source']} "
                 f"({i['reviewer']}) | {i['kind']} | `{i['ref']}` | {i['title'][:110].replace('|', '/')} |")
    b = blocking(items)
    L += ["", f"**Blocking:** {len(b)} critical/major item(s) with no recorded decision" + (":" if b else ".")]
    L += [f"- `{i['ref']}` {i['title'][:120]} ({i['id']})" for i in b]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--pr")
    ap.add_argument("--repo")
    ap.add_argument("--decisions")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        view = ghjson("pr", "view", *([a.pr] if a.pr else []), *(["-R", a.repo] if a.repo else []),
                      "--json", "number,url,author,headRepository,headRepositoryOwner", cwd=a.project)
        repo = a.repo or re.search(r"github\.com/([^/]+/[^/]+)/pull/", view["url"]).group(1)
        items = apply_records(collect(repo, view["number"], view["author"]["login"]), a.decisions)
    except (RuntimeError, ValueError, KeyError, AttributeError) as e:
        print(json.dumps({"status": "error", "reason": str(e)}))
        return 2
    b = blocking(items)
    if a.json:
        print(json.dumps({"status": "ok", "pr": view["url"], "items": items, "blocking": [i["id"] for i in b]}, indent=2, ensure_ascii=False))
    else:
        print(markdown(items, view["url"]))
    return 1 if b else 0


if __name__ == "__main__":
    sys.exit(main())
