"""Review-quality checks from the PR #716 analysis: rule sites for availability flags, review stamps, the push guard,
the PR review sync parser, the review context, and the PR description notes. Synthetic repo — no product code."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "skills" / "run" / "scripts"))
sys.path.insert(0, str(ROOT / "hooks"))
import rule_sites as RSITES  # noqa: E402
import review_stamp as RS  # noqa: E402
import pr_sync as PS  # noqa: E402
import impact_check as IC  # noqa: E402
import final_report as FR  # noqa: E402
import push_guard as PG  # noqa: E402

TYPES_BEFORE = "export interface IPaymentMethod {\n  id: number;\n  name: string;\n}\n"
TYPES_AFTER = "export interface IPaymentMethod {\n  id: number;\n  name: string;\n  isAvailable?: boolean;\n}\n"
EFFECTS = ("import { IPaymentMethod } from './types';\n\nexport function useDefault(paymentMethods: IPaymentMethod[], setSelectedPaymentMethod: any) {\n"
           "  setSelectedPaymentMethod(paymentMethods[0]);\n}\n")
SHEET_BEFORE = ("import { IPaymentMethod } from './types';\n\nexport function rows(paymentMethods: IPaymentMethod[]) {\n"
                "  return paymentMethods;\n}\n")
SHEET_AFTER = ("import { IPaymentMethod } from './types';\n\nexport function rows(paymentMethods: IPaymentMethod[]) {\n"
               "  return paymentMethods.filter(m => m.isAvailable !== false);\n}\n")
SUBMIT = "export function submit(store: any) {\n  return { paymentMethodId: store.selectedPaymentMethod?.id || 1 };\n}\n"
STYLES = "import { ScaledSheet } from 'react-native-size-matters';\nexport const styles = ScaledSheet.create({\n  a: { height: '24@vs' },\n});\n"
STYLES_RAW = ("import { ScaledSheet } from 'react-native-size-matters';\nexport const styles = ScaledSheet.create({\n  a: { height: '24@vs' },\n"
              "  b: { height: 24 },\n});\n")


def sh(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


class Repo:
    def __init__(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="ei-rq-"))
        sh(self.dir, "init", "-q", "-b", "main")
        sh(self.dir, "config", "user.email", "t@example.com")
        sh(self.dir, "config", "user.name", "t")
        self.write({"src/types.ts": TYPES_BEFORE, "src/effects.ts": EFFECTS, "src/sheet.ts": SHEET_BEFORE,
                    "src/submit.ts": SUBMIT, "src/styles.ts": STYLES})
        sh(self.dir, "add", "-A")
        sh(self.dir, "commit", "-qm", "base")
        self.base = sh(self.dir, "rev-parse", "HEAD")
        sh(self.dir, "update-ref", "refs/remotes/origin/main", self.base)

    def write(self, files):
        for rel, text in files.items():
            p = self.dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def change(self):
        self.write({"src/types.ts": TYPES_AFTER, "src/sheet.ts": SHEET_AFTER})

    def diff(self):
        return RS.branch_diff(self.dir, self.base)[1]

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class RuleSitesTest(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.r.change()

    def tearDown(self):
        self.r.cleanup()

    def test_new_flag_lists_unchecked_paths_including_repo_wide_literal_fallback(self):
        res = RSITES.analyze(self.r.dir, self.r.diff())
        self.assertEqual([f["flag"] for f in res["flags"]], ["isAvailable"])
        self.assertIn("IPaymentMethod", res["flags"][0]["types"])
        un = {s["ref"]: s["kind"] for s in res["unchecked"]}
        self.assertEqual(un.get("src/effects.ts:4"), "pick-first")
        self.assertEqual(un.get("src/submit.ts:2"), "literal-id-fallback")  # file never names the type

    def test_flag_mode_before_any_diff(self):
        res = RSITES.sites_for(self.r.dir, "isAvailable")
        self.assertEqual(sorted(res["types"]), ["IPaymentMethod"])
        self.assertTrue(any(s["ref"] == "src/submit.ts:2" for s in res["unchecked"]))

    def test_site_next_to_the_flag_counts_as_checked_and_predicates_count(self):
        self.r.write({"src/effects.ts": EFFECTS.replace("paymentMethods[0]", "paymentMethods.filter(isMethodAvailable)[0]")
                      + "\nexport const isMethodAvailable = (m: IPaymentMethod) =>\n  m.isAvailable !== false;\n"})
        res = RSITES.analyze(self.r.dir, self.r.diff())
        site = next(s for s in res["sites"] if s["ref"] == "src/effects.ts:4")
        self.assertTrue(site["checks_flag"])
        self.assertIn("isMethodAvailable", res["flags"][0]["predicates"])

    def test_inline_rule_in_several_files_is_reported(self):
        self.r.write({"src/other.ts": "import { IPaymentMethod } from './types';\nexport const ok = (m: IPaymentMethod) => m.isAvailable === true;\n"})
        res = RSITES.analyze(self.r.dir, self.r.diff())
        self.assertEqual(res["inline_rule_files"][0]["files"], ["src/other.ts", "src/sheet.ts"])

    def test_no_flag_no_sites(self):
        self.r.write({"src/types.ts": TYPES_BEFORE, "src/sheet.ts": SHEET_BEFORE.replace("return paymentMethods;", "return [...paymentMethods];")})
        self.assertEqual(RSITES.analyze(self.r.dir, self.r.diff())["sites"], [])

    def test_base_is_the_closest_default_like_branch(self):
        sh(self.r.dir, "checkout", "-qb", "feature")
        sh(self.r.dir, "commit", "-qam", "feature work")
        sh(self.r.dir, "checkout", "-q", "--orphan", "dev-root")
        sh(self.r.dir, "commit", "-qm", "unrelated", "--allow-empty")
        sh(self.r.dir, "update-ref", "refs/remotes/origin/develop", sh(self.r.dir, "rev-parse", "HEAD"))
        sh(self.r.dir, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
        sh(self.r.dir, "checkout", "-q", "feature")
        self.assertEqual(RSITES.default_base(self.r.dir), self.r.base)


class StampAndPushGuardTest(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.store = pathlib.Path(tempfile.mkdtemp(prefix="ei-store-"))
        self._store, RS.STORE = RS.STORE, self.store
        self._which = PG.shutil.which
        PG.shutil.which = lambda name: "/usr/bin/true"

    def tearDown(self):
        RS.STORE = self._store
        PG.shutil.which = self._which
        shutil.rmtree(self.store, ignore_errors=True)
        self.r.cleanup()

    def event(self, cmd="git push origin HEAD"):
        return {"tool_input": {"command": cmd}, "cwd": str(self.r.dir)}

    def test_content_key_tracks_working_tree_without_touching_the_index(self):
        idx = self.r.dir / ".git" / "index"
        before = idx.read_bytes()
        k1 = RS.content_key(self.r.dir)
        self.r.write({"src/new.ts": "export const x = 1;\n"})
        k2 = RS.content_key(self.r.dir)
        self.assertNotEqual(k1, k2)
        self.assertEqual(idx.read_bytes(), before)
        self.assertEqual(sh(self.r.dir, "status", "--porcelain"), "?? src/new.ts")

    def test_not_a_push_is_silent_and_nothing_to_push_is_silent(self):
        self.assertIsNone(PG.check(self.event("git status")))
        self.assertIsNone(PG.check(self.event()))  # no diff from the base

    def test_unreviewed_push_lists_review_conventions_and_rule_sites(self):
        self.r.change()
        self.r.write({"src/styles.ts": STYLES_RAW})
        reason = PG.check(self.event(f"cd {self.r.dir} && git add -A && git commit -qm x && git push"))
        self.assertIn("No local CodeRabbit review of this exact code", reason)
        self.assertIn("src/styles.ts:4 — raw 24 in ScaledSheet.create", reason)
        self.assertIn("starts honoring `isAvailable`", reason)
        self.assertLess(reason.index("submit.ts:2"), reason.index("effects.ts:4"))  # riskiest kind first

    def test_matching_deep_fresh_connected_stamp_clears_the_review_item(self):
        self.r.write({"src/styles.ts": STYLES.replace("'24@vs'", "'20@vs'")})
        key = RS.content_key(self.r.dir)
        RS.record(self.r.dir, {"key": key, "deep": True, "fresh": True, "scope": "default", "org_connected": True,
                               "head": self.r.base})
        self.assertIsNone(PG.check(self.event()))

    def test_partial_stamps_are_explained(self):
        sh(self.r.dir, "commit", "-qam", "noop", "--allow-empty")
        self.r.write({"src/styles.ts": STYLES.replace("'24@vs'", "'20@vs'")})
        key = RS.content_key(self.r.dir)
        RS.record(self.r.dir, {"key": key, "deep": True, "fresh": False, "scope": "--uncommitted", "org_connected": False,
                               "head": sh(self.r.dir, "rev-parse", "HEAD")})
        reason = PG.check(self.event())
        for part in ("not --fresh", "not connected", "covered only uncommitted changes"):
            self.assertIn(part, reason)

    def test_hook_output_is_ask_never_deny(self):
        self.r.change()
        p = subprocess.run([sys.executable, "-I", str(ROOT / "hooks" / "push_guard.py")], input=json.dumps(self.event()),
                           capture_output=True, text=True, env={**os.environ, "TMPDIR": str(self.store)})
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "ask")
        p = subprocess.run([sys.executable, "-I", str(ROOT / "hooks" / "push_guard.py")], input=json.dumps(self.event()),
                           capture_output=True, text=True, env={**os.environ, "EI_PUSH_GUARD": "off"})
        self.assertEqual(p.stdout.strip(), "")

    def test_hook_is_registered_for_bash(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
        self.assertTrue(any(h["matcher"] == "Bash" and "push_guard.py" in h["hooks"][0]["command"] for h in hooks))


OUTSIDE_BODY = """**Actionable comments posted: 1**
> **⚠️ Outside diff range comments (1)**
> <details>
> <summary><strong>🟠 Major</strong> · Block submission of an unavailable selected method. · <code>effects.ts:256-257</code></summary>
> `src/hooks/effects.ts:256-257`
> **Block submission of an unavailable selected method.**
> </details>
"""
INLINE_BODY = ("**<picture><img alt=\"\"></picture> Major** · **Functional Correctness** · **Quick win**\n\n"
               "**Keep the top-level flag as a fallback.**\n\nThe selector no longer reads it.\n")


class PrSyncTest(unittest.TestCase):
    def test_outside_diff_block_parsed_with_full_path(self):
        items = PS.outside_items({"body": OUTSIDE_BODY, "commit_id": "abcdef123", "submitted_at": "t"})
        self.assertEqual(items, [{"kind": "outside-diff", "severity": "major", "ref": "src/hooks/effects.ts:256-257",
                                  "title": "Block submission of an unavailable selected method.", "commit": "abcdef1", "at": "t"}])

    def test_inline_title_skips_the_category_header(self):
        self.assertEqual(PS.title_of(INLINE_BODY), "Keep the top-level flag as a fallback.")
        self.assertEqual(PS.severity_of(INLINE_BODY), "major")

    def test_major_without_decision_blocks_until_recorded(self):
        items = [{"id": "gh-outside:1", "severity": "major", "github": "NO THREAD"},
                 {"id": "gh:2", "severity": "major", "github": "RESOLVED"},
                 {"id": "gh:3", "severity": "minor", "github": "OPEN"}]
        self.assertEqual([i["id"] for i in PS.blocking(PS.apply_records(items, None))], ["gh-outside:1"])
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            (tmp / "d.json").write_text(json.dumps({"schema": "ei.decision-records/1", "decisions": [], "questions": [],
                                                    "findings": [{"id": "F-001", "review_ref": "gh-outside:1",
                                                                  "classification": "VALID", "disposition": "FIXED"}]}))
            self.assertEqual(PS.blocking(PS.apply_records(items, tmp / "d.json")), [])
        finally:
            shutil.rmtree(tmp)


class GuardContextPrTest(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.r.change()
        self.session = pathlib.Path(tempfile.mkdtemp(prefix="ei-sess-"))
        (self.session / "impact.json").write_text(json.dumps({
            "schema": IC.SCHEMA, "project": str(self.r.dir), "task": "fix", "criteria": [{"id": "AC-1", "text": "Unavailable methods can't be chosen", "every_path": False, "triggers": []}],
            "symbols": [], "guards": [], "declarations": {}, "reviews": [], "gates": {}, "log": []}))
        (self.session / "decisions.json").write_text(json.dumps({"schema": "ei.decision-records/1", "decisions": [], "questions": [
            {"id": "Q-001", "kind": "contract", "title": "COD", "owner": "backend team", "status": "ANSWERED",
             "question": "Is COD always returned, with isAvailable?", "answer": {"text": "Yes; a missing isAvailable means available",
             "evidence": [{"kind": "TEST", "ref": "observed response 2026-11-19"}]}}],
            "findings": [{"id": "F-001", "classification": "OUT_OF_SCOPE", "disposition": "LEFT_AS_IS", "title": "Legacy path shows unavailable methods",
                          "ref": "src/legacy.ts:10", "reason": "existed before this PR; legacy screen is being removed"}]}))
        (self.session / "changes.json").write_text(json.dumps({"entries": [
            {"what": "getPaymentMethods prop type", "where": "src/effects.ts:3", "change": "CHANGED",
             "why": {"source": "standard", "ref": "§3", "text": "the old type was copied from fetchSavedCards"}}]}))

    def tearDown(self):
        shutil.rmtree(self.session, ignore_errors=True)
        self.r.cleanup()

    def test_flag_guard_requires_every_site_classified(self):
        rec = {"action": "select a payment method", "guard": "isMethodAvailable", "guard_location": "src/sheet.ts:4",
               "flag": "isAvailable", "entry_points": [
                   {"ref": "src/effects.ts:4", "chain": "default → setSelectedPaymentMethod", "enforced": "no", "evidence": "no availability check"}]}
        e, _ = IC.check_guard(rec, str(self.r.dir))
        self.assertTrue(any("src/submit.ts:2" in m and "literal-id-fallback" in m for m in e))
        rec["entry_points"].append({"ref": "src/submit.ts:2", "chain": "submit → paymentMethodId", "enforced": "no",
                                    "evidence": "falls back to id 1"})
        e, _ = IC.check_guard(rec, str(self.r.dir))
        self.assertFalse([m for m in e if "site not classified" in m])
        self.assertEqual(sorted(rec["unguarded"]), ["src/effects.ts:4", "src/submit.ts:2"])

    def test_review_context_carries_contract_and_out_of_scope(self):
        md = IC.context_md(str(self.session))
        self.assertIn("Q-001 Is COD always returned, with isAvailable? → **Yes; a missing isAvailable means available** (TEST: observed response 2026-11-19)", md)
        self.assertIn("Legacy path shows unavailable methods — existed before this PR", md)
        self.assertIn("AC-1: Unavailable methods can't be chosen", md)

    def test_pr_description_states_contract_extra_changes_and_known_issues(self):
        md = FR.pr_markdown(str(self.session))
        self.assertIn("**API contract this change relies on**", md)
        self.assertIn("Q-001", md)
        self.assertIn("**Changes the ticket didn't ask for**", md)
        self.assertIn("the old type was copied from fetchSavedCards", md)
        self.assertIn("**Known issues outside this PR**", md)
        self.assertTrue(FR.pr_check(str(self.session), md)["passed"] or
                        not any("Q-001" in p for p in FR.pr_check(str(self.session), md)["problems"]))
        self.assertTrue(any("Q-001" in p for p in FR.pr_check(str(self.session), "## Reviewer Notes\n- none\n")["problems"]))


if __name__ == "__main__":
    unittest.main()
