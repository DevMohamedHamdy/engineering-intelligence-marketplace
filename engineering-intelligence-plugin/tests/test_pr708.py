"""PR #708 regression scenarios: would the improved Feature / Fix workflow have caught what reached the reviewers?

Each scenario replays the PR on a reduced copy of its code (pr708_fixture) and checks script behavior — discovery,
validation, state transitions, gate verdicts, the edit hook — not wording in prompt files.
"""
import json, pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pr708_fixture import CRITERIA, Fixture, hook, run  # noqa: E402

SHEET = "src/components/PaymentMethodsSheet/index.tsx"
CHECKOUT = "src/screens/Checkout/index.tsx"
HOOKF = "src/hooks/usePayments.ts"

DECISION = {
    "title": "Add New row: radio for no-card users", "category": "Design", "phase": "planning",
    "context": "Figma shows a radio on the Add New row in the COD-unavailable frames; today the row opens Add Card directly.",
    "question": "Where should the Add New row become select-first?",
    "alternatives": [
        {"id": "A", "name": "Keep as is", "scope": "keep", "description": "Tap still opens Add Card directly; disabled kept",
         "evaluated": True, "verdict": "rejected", "reason": "the COD-unavailable frame needs a selectable Add New row"},
        {"id": "B", "name": "Radio for every no-card user", "scope": "global", "description": "select-first everywhere",
         "evaluated": True, "verdict": "rejected", "reason": "changes Wallet and every no-card checkout, removes disabled"},
        {"id": "C", "name": "Radio only when COD is unavailable", "scope": "conditional",
         "description": "select-first only under the new condition; existing users keep direct Add Card",
         "evaluated": True, "verdict": "selected"}],
    "selected": "C",
    "rationale": "Only the COD-unavailable frame changes; users with COD available keep the direct tap and the disabled state.",
    "side_effects": ["removes the row's disabled state when adding a card is not allowed",
                     "tap selects instead of opening Add Card", "Wallet hosts the same sheet"],
    "approval_required": True, "changes_behavior": True, "changes_shared_behavior": True,
}

SHEET_SYMBOL = {
    "name": "PaymentMethodsSheet", "file": SHEET, "kind": "component", "labels": ["Add New"],
    "before": "Add New row: tap (onPress) opens Add Card directly when there is no saved card; the row is disabled when addCardDisabled",
    "after": "Add New row shows a radio; tap (onPress) only selects it and Add opens Add Card; the row is no longer disabled",
    "consumers": [
        {"ref": CHECKOUT, "targeted": True},
        {"ref": "src/screens/Wallet/index.tsx", "targeted": False,
         "impact": "no-card users in Wallet get select-first and lose the disabled row at 5 cards",
         "check": "Wallet, no saved card: tap Add New opens Add Card; 5 cards: row disabled"}],
    "behavior_to_preserve": ["no card, COD available: tap goes straight to Add Card", "row disabled when addCardDisabled"],
    "decision": "D-001",
}

HOOK_SYMBOL = {
    "name": "usePayments", "file": HOOKF, "kind": "hook",
    "before": "select returns the method list; cash removed only for pickup orders",
    "after": "select returns {codAvailable, methods}; cash removed when codAvailable is false; query is enabled: false",
    "consumers": [
        {"ref": CHECKOUT, "targeted": True},
        {"ref": SHEET, "targeted": True},
        {"ref": "src/screens/OrderTracking/index.tsx", "targeted": False,
         "impact": "UNKNOWN: whether payment-methods can return codAvailable false on the tracking screen; a cash order's method would not be found",
         "question": "Q-002"},
        {"ref": "src/screens/OrderTracking/OrderTrackingRevamp.tsx", "targeted": False,
         "impact": "UNKNOWN: same cash filter as OrderTracking", "question": "Q-002"}],
    "behavior_to_preserve": ["tracking shows the order's payment method name"],
}

GUARD_ENTRIES = [
    {"ref": f"{CHECKOUT}:16", "chain": "Place order CTA → handleMainCta → continueReviewedOrder", "enforced": "yes",
     "evidence": f"{CHECKOUT}:25 disabled={{mainButtonDisabled}}"},
    {"ref": f"{CHECKOUT}:25", "chain": "Button onPress → handleMainCta", "enforced": "yes", "evidence": f"{CHECKOUT}:25 disabled"},
    {"ref": f"{CHECKOUT}:19-21", "chain": "PickupSheet onContinue → onPickupContinue → continueReviewedOrder", "enforced": "yes",
     "evidence": f"{CHECKOUT}:20 if (mainButtonDisabled) return"},
    {"ref": f"{CHECKOUT}:26", "chain": "PickupSheet onContinue prop", "enforced": "yes", "evidence": f"{CHECKOUT}:20 re-check"},
    {"ref": f"{CHECKOUT}:28", "chain": "PlacingOrderSheet onPlaceNow → continueReviewedOrder", "enforced": "no",
     "evidence": f"{CHECKOUT}:28 calls it with no mainButtonDisabled check"},
    {"ref": f"{CHECKOUT}:29", "chain": "PlacingOrderSheet onCountdownComplete → continueReviewedOrder", "enforced": "no",
     "evidence": f"{CHECKOUT}:29 calls it with no mainButtonDisabled check"},
]
GUARD = {"action": "continueReviewedOrder", "action_file": CHECKOUT, "guard": "mainButtonDisabled (paymentMethodsFetching)",
         "guard_location": f"{CHECKOUT}:11", "criteria": ["AC-2"], "entry_points": GUARD_ENTRIES}

Q_CONTRACT = {"title": "COD decision source", "kind": "contract", "owner": "backend team",
              "question": "The ticket puts the COD decision in the checkout response, computed on the final total with the "
                          "delivery fee; the app reads codAvailable from payment-methods, which sends no total. Is "
                          "codAvailable computed on the final total including the delivery fee?"}
Q_TRACKING = {"title": "codAvailable on tracking", "kind": "backend", "owner": "backend team",
              "question": "Can payment-methods return codAvailable false when called from the order tracking screen?"}


class Base(unittest.TestCase):
    task = "feature"

    def setUp(self):
        self.fx = Fixture()
        self.S, self.D = self.fx.session, self.fx.decisions

    def tearDown(self):
        self.fx.cleanup()

    def ok(self, script, *args, payload=None, code=0):
        c, out = run(script, *args, payload=payload)
        self.assertEqual(c, code, out)
        return out

    def intake(self, comments="history.json"):
        """Intake and discovery: task, criteria, conventions profile, type/lint baseline, open questions."""
        self.ok("impact_check.py", "start", self.S, "--project", self.fx.repo, "--task", self.task)
        self.ok("impact_check.py", "criteria", self.S, "--json", "-", payload=CRITERIA)
        self.ok("conventions.py", "collect", self.S, "--project", self.fx.repo, "--comments-json", self.fx.root / comments)
        self.ok("verify_baseline.py", "run", self.S, "--project", self.fx.repo, "--name", "tsc", "--phase", "baseline",
                "--cmd", self.fx.tsc_cmd("baseline"))
        self.ok("verify_baseline.py", "not-run", self.S, "--name", "eslint", "--phase", "baseline",
                "--reason", "fixture project has no ESLint installed")
        self.ok("decision_records.py", "ask", self.D, "--json", "-", payload=Q_CONTRACT)
        self.ok("decision_records.py", "ask", self.D, "--json", "-", payload=Q_TRACKING)

    def plan_records(self):
        self.ok("decision_records.py", "add", self.D, "--json", "-", "--project", self.fx.repo, payload=DECISION)
        self.ok("impact_check.py", "symbol", self.S, "--json", "-", payload=SHEET_SYMBOL)
        self.ok("impact_check.py", "symbol", self.S, "--json", "-", payload=HOOK_SYMBOL)
        self.ok("impact_check.py", "guard", self.S, "--json", "-", payload=GUARD)

    def gate(self, stage):
        c, out = run("impact_check.py", "gate", self.S, "--stage", stage)
        return c, out


class ScenarioA_SharedRow(Base):
    def test_consumers_of_the_sheet_are_discovered(self):
        self.intake()
        out = self.ok("impact_check.py", "consumers", self.S, "--symbol", "PaymentMethodsSheet")
        self.assertIn("src/screens/Wallet/index.tsx", out["consumer_files"])
        self.assertIn(CHECKOUT, out["consumer_files"])
        self.assertNotIn(SHEET, out["consumer_files"], "its own definition / export is not a consumer")

    def test_unclassified_consumer_and_missing_decision_are_refused(self):
        self.intake()
        rec = dict(SHEET_SYMBOL, consumers=[{"ref": CHECKOUT, "targeted": True}], decision=None)
        c, out = run("impact_check.py", "symbol", self.S, "--json", "-", payload=rec)
        self.assertEqual(c, 1)
        self.assertTrue(any("Wallet" in e for e in out["errors"]), out)
        rec = dict(SHEET_SYMBOL, decision=None)
        c, out = run("impact_check.py", "symbol", self.S, "--json", "-", payload=rec)
        self.assertEqual(c, 1)
        self.assertTrue(any("scoped design decision" in e for e in out["errors"]), out)

    def test_binary_question_without_the_scoped_option_is_refused(self):
        binary = dict(DECISION, alternatives=[a for a in DECISION["alternatives"] if a["scope"] != "conditional"]
                      + [], selected="B")
        binary["alternatives"] = [dict(a, verdict="selected") if a["id"] == "B" else a for a in binary["alternatives"]]
        binary["alternatives"] = [dict(a, verdict="rejected", reason=a.get("reason") or "x" * 12) if a["id"] == "A" else a
                                  for a in binary["alternatives"]]
        c, out = run("decision_records.py", "add", self.D, "--json", "-", payload=binary)
        self.assertEqual(c, 1)
        self.assertTrue(any("only under the new condition" in e for e in out["errors"]), out)
        c, out = run("decision_records.py", "add", self.D, "--json", "-", payload=dict(DECISION, side_effects=[]))
        self.assertEqual(c, 1)
        self.assertTrue(any("side_effects" in e for e in out["errors"]), out)

    def test_removed_disabled_and_changed_press_are_detected_after_the_edit(self):
        self.intake()
        self.ok("change_log.py", "start", self.S, "--project", self.fx.repo)
        self.fx.apply_pr()
        det = self.ok("impact_check.py", "detect", self.S)
        props = {(p["prop"], p["change"]) for p in det["prop_changes"]}
        self.assertIn(("disabled", "removed"), props)
        self.assertIn(("onPress", "changed"), props)
        self.assertIn("PaymentMethodsSheet", [m["name"] for m in det["unrecorded"]])
        # a symbol record that doesn't mention the removed disabled state is a blocker at the Review Gate
        self.ok("decision_records.py", "add", self.D, "--json", "-", payload=DECISION)
        vague = dict(SHEET_SYMBOL, before="Add New row opens Add Card", after="Add New row shows a radio",
                     behavior_to_preserve=["no card, COD available: tap goes straight to Add Card"])
        self.ok("impact_check.py", "symbol", self.S, "--json", "-", payload=vague)
        c, g = self.gate("review")
        self.assertEqual(c, 1)
        self.assertTrue(any("prop `disabled` removed" in b for b in g["blockers"]), g["blockers"])

    def test_review_gate_requires_the_developer_approval(self):
        self.intake()
        self.plan_records()
        self.ok("change_log.py", "start", self.S, "--project", self.fx.repo)
        self.fx.apply_pr()
        c, g = self.gate("review")
        self.assertTrue(any("D-001 is PROPOSED" in b for b in g["blockers"]), g["blockers"])


class ScenarioB_GuardBypass(Base):
    def test_every_entry_point_is_found_and_must_be_classified(self):
        self.intake()
        out = self.ok("impact_check.py", "callers", self.S, "--action", "continueReviewedOrder")
        props = {x["via_prop"] for x in out["call_sites"]}
        self.assertTrue({"onPlaceNow", "onCountdownComplete", "onPress", "onContinue"} <= props, out["call_sites"])
        cta_only = dict(GUARD, entry_points=GUARD_ENTRIES[:2])
        c, res = run("impact_check.py", "guard", self.S, "--json", "-", payload=cta_only)
        self.assertEqual(c, 1)
        unclassified = [e for e in res["errors"] if e.startswith("call site not classified")]
        self.assertTrue(any(":28" in e for e in unclassified) and any(":29" in e for e in unclassified), res["errors"])

    def test_unguarded_paths_are_flagged_and_coverage_is_not_complete(self):
        self.intake()
        out = self.ok("impact_check.py", "guard", self.S, "--json", "-", payload=GUARD)
        self.assertEqual(out["coverage"], "INCOMPLETE")
        self.assertEqual(sorted(out["unguarded"]), [f"{CHECKOUT}:28", f"{CHECKOUT}:29"])

    def test_every_path_criterion_requires_the_analysis(self):
        self.intake()
        c, out = run("impact_check.py", "declare", self.S, "--none", "guards", "--reason", "no guard is added by this ticket")
        self.assertEqual(c, 1)
        self.assertIn("AC-2", out["reason"])
        c, g = self.gate("plan")
        self.assertTrue(any(b.startswith("AC-2 is an every-path criterion") for b in g["blockers"]), g["blockers"])

    def test_pr_text_cannot_claim_every_path(self):
        self.intake()
        self.ok("impact_check.py", "guard", self.S, "--json", "-", payload=GUARD)
        (self.S / "bad.md").write_text("## Reviewer Notes\n\nThe new guard covers every submission path. Q-001 Q-002\n")
        c, out = run("final_report.py", "pr-check", self.S, "--text", self.S / "bad.md")
        self.assertEqual(c, 1)
        self.assertTrue(any("claims every path" in p for p in out["problems"]), out)


class ScenarioC_ContractQuestion(Base):
    def test_developer_preference_does_not_close_a_backend_contract_question(self):
        self.intake()
        pref = {"text": "Use codAvailable from the payment-methods API as is", "addresses_question": True,
                "evidence": [{"kind": "HUMAN", "source": "developer (chat 11-17 13:17)", "role": "developer",
                              "quote": "when ever i have a codAvailable from payment method api set its value"}]}
        c, out = run("decision_records.py", "answer", self.D, "Q-001", "--json", "-", payload=pref)
        self.assertEqual(c, 1)
        self.assertEqual(out["state"], "OPEN")
        self.assertTrue(any("developer preference is not evidence" in e for e in out["errors"]), out)
        app_code = {"text": "The app reads codAvailable in usePayments select", "addresses_question": True,
                    "evidence": [{"kind": "VERIFIED", "ref": f"{HOOKF}:4"}]}
        c, out = run("decision_records.py", "answer", self.D, "Q-001", "--json", "-", "--project", self.fx.repo, payload=app_code)
        self.assertEqual(c, 1, "code in the app shows what the app does, not what the backend guarantees")
        md = run("decision_records.py", "questions", self.D)[1]
        self.assertIn("**OPEN**", md)
        self.assertIn("answer(s) refused", md)

    def test_owner_answer_closes_it_and_deferral_keeps_it_visible(self):
        self.intake()
        self.ok("decision_records.py", "defer", self.D, "Q-001", "--actor", "developer", "--via", "Plan Gate",
                "--reason", "backend answer pending; shipping with payment-methods value")
        c, out = run("decision_records.py", "defer", self.D, "Q-002", "--actor", "claude", "--via", "x", "--reason", "x" * 12)
        self.assertEqual(c, 1, "only the developer defers")
        owner = {"text": "codAvailable is evaluated on the final total including the delivery fee", "addresses_question": True,
                 "evidence": [{"kind": "HUMAN", "source": "Ahmed (backend), #payments 11-18", "role": "backend team lead",
                               "quote": "yes, codAvailable uses the final total incl. delivery fee"}]}
        self.ok("decision_records.py", "answer", self.D, "Q-001", "--json", "-", payload=owner)
        val = self.ok("decision_records.py", "validate", self.D)
        self.assertEqual(val["open_questions"], ["Q-002"])

    def test_coderabbit_finding_cannot_be_dismissed_on_disagreement(self):
        self.intake()
        k1 = {"source": "coderabbit", "ref": f"{CHECKOUT}:11", "title": "COD may be decided before delivery fees",
              "severity": "HIGH", "classification": "FALSE_POSITIVE", "disposition": "DISMISSED",
              "evidence": [{"kind": "HUMAN", "source": "developer", "note": "trust codAvailable"}]}
        c, out = run("decision_records.py", "finding", self.D, "--json", "-", payload=k1)
        self.assertEqual(c, 1)
        self.assertTrue(any("disagreement or a preference is not evidence" in e for e in out["errors"]), out)
        c, out = run("decision_records.py", "finding", self.D, "--json", "-",
                     payload=dict(k1, classification="CONTRACT_QUESTION", disposition="FIXED", fix_ref=f"{CHECKOUT}:11", question="Q-001"))
        self.assertEqual(c, 1, "a contract question can't be marked fixed while its question is OPEN")
        self.ok("decision_records.py", "finding", self.D, "--json", "-",
                payload=dict(k1, classification="CONTRACT_QUESTION", disposition="OPEN", question="Q-001", evidence=[]))


class ScenarioD_TypeBaseline(Base):
    def test_new_error_in_an_unchanged_consumer_is_reported(self):
        self.intake()
        self.ok("verify_baseline.py", "run", self.S, "--project", self.fx.repo, "--name", "tsc", "--phase", "after",
                "--cmd", self.fx.tsc_cmd("after"))
        c, out = run("verify_baseline.py", "compare", self.S)
        self.assertEqual(c, 1)
        r = out["checks"]["tsc"]
        self.assertEqual((r["status"], r["existing"], r["new"], r["resolved"]), ("REGRESSION", 3, 1, 0))
        self.assertEqual(r["new_in_files"], ["src/screens/Checkout/CheckoutContainer.tsx"],
                         "the error is in a file the PR did not change — no changed-file filtering")
        self.assertIn("Type 'QueryObserverResult", r["new_items"][0]["message"], "continuation lines are kept")

    def test_pre_existing_errors_are_not_regressions(self):
        self.intake()
        self.ok("verify_baseline.py", "run", self.S, "--project", self.fx.repo, "--name", "tsc", "--phase", "after",
                "--cmd", self.fx.tsc_cmd("baseline"))
        out = self.ok("verify_baseline.py", "compare", self.S)
        self.assertEqual((out["checks"]["tsc"]["status"], out["checks"]["tsc"]["existing"]), ("PASS", 3))
        self.assertEqual(out["checks"]["eslint"]["status"], "NOT RUN")

    def test_loosened_type_is_a_review_blocker(self):
        self.intake()
        self.ok("change_log.py", "start", self.S, "--project", self.fx.repo)
        self.fx.apply_pr()
        det = self.ok("impact_check.py", "detect", self.S)
        self.assertEqual([x["ref"] for x in det["loosened_types"]], ["src/screens/Checkout/useCheckoutEffects.ts:3"])
        c, g = self.gate("review")
        self.assertTrue(any(b.startswith("type loosened at src/screens/Checkout/useCheckoutEffects.ts") for b in g["blockers"]))

    def test_missing_command_is_recorded_not_claimed(self):
        self.intake()
        out = self.ok("verify_baseline.py", "run", self.S, "--project", self.fx.repo, "--name", "lint2", "--phase", "baseline",
                      "--cmd", "definitely-not-a-command --x")
        self.assertFalse(out["ran"])
        self.assertIn("command not found", out["reason"])


class ScenarioE_Conventions(Base):
    def conv(self):
        return {c["id"]: c for c in json.loads((self.S / "conventions.json").read_text())["conventions"]}

    def test_scaled_sheet_enforced_from_review_history_and_code(self):
        self.intake()
        c = self.conv()
        self.assertEqual(c["scaled-sheet-units"]["level"], "ENFORCED")
        self.assertIn("#689", " ".join(c["scaled-sheet-units"]["basis"]))
        prs = {x["pr"] for x in c["scaled-sheet-units"]["evidence"]["review_comments"]}
        self.assertNotIn(700, prs, "bot comments are excluded")
        self.ok("change_log.py", "start", self.S, "--project", self.fx.repo)
        self.fx.apply_pr()
        c2, out = run("conventions.py", "check", self.S)
        self.assertEqual(c2, 1)
        refs = {v["ref"] for v in out["blocking"]}
        self.assertTrue(any(r.startswith("src/screens/PayWith/index.tsx") for r in refs), out)

    def test_figma_rule_only_with_evidence(self):
        self.intake()
        c = self.conv()
        self.assertEqual(c["no-figma-refs-in-comments"]["level"], "ADVISORY",
                         "two existing Figma comments and no request on record: not a rule")
        self.ok("change_log.py", "start", self.S, "--project", self.fx.repo)
        self.fx.apply_pr()
        out = self.ok("conventions.py", "check", self.S, code=1)
        self.assertFalse([v for v in out["violations"] if v["convention"] == "no-figma-refs-in-comments"])

    def test_figma_rule_enforced_when_reviewers_asked_on_two_prs(self):
        self.fx2 = Fixture()
        try:
            S = self.fx2.session
            run("conventions.py", "collect", S, "--project", self.fx2.repo, "--comments-json", self.fx2.root / "history-figma.json")
            c = {x["id"]: x for x in json.loads((S / "conventions.json").read_text())["conventions"]}
            self.assertEqual(c["no-figma-refs-in-comments"]["level"], "ENFORCED")
            run("change_log.py", "start", S, "--project", self.fx2.repo)
            self.fx2.apply_pr()
            code, out = run("conventions.py", "check", S)
            self.assertTrue([v for v in out["blocking"] if v["convention"] == "no-figma-refs-in-comments"], out)
        finally:
            self.fx2.cleanup()

    def test_mixed_naming_stays_advisory(self):
        self.intake()
        self.assertEqual(self.conv()["loading-flag-naming"]["level"], "ADVISORY")
        bad = {"id": "naming", "title": "isXFetching", "rule": "use isXFetching", "level": "ENFORCED", "kind": "naming",
               "evidence": {"review_comments": [{"pr": 681}, {"pr": 708}]}}
        c, out = run("conventions.py", "add", self.S, "--json", "-", payload=bad)
        self.assertEqual(c, 1, "naming is enforced only by lint or a written standard")

    def test_without_review_history_the_limitation_is_recorded(self):
        self.ok("conventions.py", "collect", self.S, "--project", self.fx.repo)  # no GitHub remote in the fixture
        prof = json.loads((self.S / "conventions.json").read_text())
        self.assertTrue(prof["limitations"])
        self.assertEqual(prof["sources"]["review_comments"]["count"], 0)
        self.assertFalse((self.fx.repo / "conventions.json").exists(), "never written into the project")


class ScenarioF_SharedHook(Base):
    def test_tracking_consumers_are_required_and_unknown_stays_unknown(self):
        self.intake()
        partial = dict(HOOK_SYMBOL, consumers=HOOK_SYMBOL["consumers"][:2])
        c, out = run("impact_check.py", "symbol", self.S, "--json", "-", payload=partial)
        self.assertEqual(c, 1)
        missing = " ".join(out["errors"])
        self.assertIn("OrderTracking/index.tsx", missing)
        self.assertIn("OrderTrackingRevamp.tsx", missing)
        out = self.ok("impact_check.py", "symbol", self.S, "--json", "-", payload=HOOK_SYMBOL)
        imp = json.loads((self.S / "impact.json").read_text())
        s = next(x for x in imp["symbols"] if x["name"] == "usePayments")
        self.assertEqual(len(s["unknown_impacts"]), 2)
        self.assertEqual(s["affected_untargeted"], [], "an unknown impact is not turned into a regression")


class ScenarioG_ReviewerFindings(Base):
    def add(self, payload, code=0):
        c, out = run("decision_records.py", "finding", self.D, "--json", "-", "--project", self.fx.repo, payload=payload)
        self.assertEqual(c, code, out)
        return out

    def test_each_kind_of_finding_needs_its_own_basis(self):
        self.intake()
        base = {"source": "human-reviewer", "ref": f"{CHECKOUT}:28"}
        self.add(dict(base, title="K2 sheet bypasses the guard", classification="VALID", kind="defect",
                      disposition="FIXED", fix_ref=f"{CHECKOUT}:13"))
        self.add(dict(base, title="H2 ScaledSheet suffixes", classification="VALID", kind="convention", disposition="FIXED",
                      fix_ref="src/screens/PayWith/index.tsx:13"))
        self.add(dict(base, title="H6 rename flag", classification="PREFERENCE", disposition="LEFT_AS_IS",
                      reason="matches its sibling paymentMethodsLoading"), code=1)
        self.add(dict(base, title="H6 rename flag", classification="PREFERENCE", disposition="LEFT_AS_IS",
                      reason="matches its sibling paymentMethodsLoading", convention_ref="loading-flag-naming (ADVISORY)"))
        self.add(dict(base, title="H8 why not invalidate", classification="EXPLANATION_REQUEST", disposition="EXPLAINED",
                      explanation="invalidateQueries does not refetch an enabled:false query", explained_in="reviewer-notes"))
        self.add(dict(base, title="H9 disable the label", classification="FALSE_POSITIVE", disposition="DISMISSED",
                      evidence=[{"kind": "HUMAN", "source": "developer"}]), code=1)
        self.add(dict(base, title="H9 disable the label", classification="FALSE_POSITIVE", disposition="DISMISSED",
                      evidence=[{"kind": "VERIFIED", "ref": f"{CHECKOUT}:25", "note": "disabled={mainButtonDisabled}"}]))
        self.add(dict(base, title="K1 COD timing", classification="CONTRACT_QUESTION", disposition="DISMISSED",
                      question="Q-001"), code=1)
        self.add(dict(base, title="K1 COD timing", classification="CONTRACT_QUESTION", disposition="DEFERRED",
                      question="Q-001", reason="needs the backend answer", actor="claude"), code=1)
        self.add(dict(base, title="K1 COD timing", classification="CONTRACT_QUESTION", disposition="DEFERRED",
                      question="Q-001", reason="needs the backend answer", actor="developer"))
        md = run("decision_records.py", "report", self.D)[1]
        self.assertIn("Review findings and dispositions", md)
        self.assertIn("Open-question ledger", md)


class WorkflowIntegration(Base):
    """Feature: intake → plan checkpoint (edit hook) → implement → review records → Review Gate → PR."""

    def finish_review_records(self, guard_fixed):
        # implementation: the PR, plus the fixes the gate asks for
        self.fx.apply_pr()
        eff = self.fx.repo / "src/screens/Checkout/useCheckoutEffects.ts"
        eff.write_text(eff.read_text().replace("import {ICreditCard} from '../../types';\n",
                                               "import {QueryObserverResult} from '@tanstack/react-query';\nimport {IPaymentMethods} from '../../types';\n")
                       .replace("Promise<unknown>", "Promise<QueryObserverResult<IPaymentMethods>>"))
        pw = self.fx.repo / "src/screens/PayWith/index.tsx"
        pw.write_text(pw.read_text().replace("  // COD off with no card (Figma 7766:24478)\n", "")
                      .replace("addButton: {paddingHorizontal: 16,\n    height: 24}", "addButton: {paddingHorizontal: '16@s',\n    height: '24@vs'}"))
        if guard_fixed:  # implement the approved option C: select-first only when COD is unavailable
            sh = self.fx.repo / SHEET
            sh.write_text(sh.read_text().replace("({hasSavedCards, addCardDisabled, onSelect, onAddCard})",
                                                 "({hasSavedCards, addCardDisabled, codUnavailable, onSelect, onAddCard})")
                          .replace("        showRadio\n        onPress={handleSelectAddNew}\n",
                                   "        showRadio={codUnavailable}\n"
                                   "        onPress={codUnavailable || hasSavedCards ? handleSelectAddNew : handleAddNewCard}\n"
                                   "        disabled={!codUnavailable && addCardDisabled}\n"))
            self.ok("impact_check.py", "symbol", self.S, "--json", "-", payload=dict(
                SHEET_SYMBOL, after="Add New row: when codUnavailable, a radio and tap (onPress) selects it; otherwise unchanged, "
                                    "including disabled when addCardDisabled",
                consumers=[SHEET_SYMBOL["consumers"][0], dict(SHEET_SYMBOL["consumers"][1],
                           impact="none — Wallet does not pass codUnavailable, so its tap and disabled state are unchanged")]))
            co = self.fx.repo / CHECKOUT
            co.write_text(co.read_text().replace("  const continueReviewedOrder = () => {\n",
                                                 "  const continueReviewedOrder = () => {\n    if (mainButtonDisabled) return;\n"))
            src = co.read_text().splitlines()
            refs = [i + 1 for i, l in enumerate(src) if "continueReviewedOrder()" in l or "handleMainCta}" in l or "onPickupContinue}" in l]
            eps = [{"ref": f"{CHECKOUT}:{n}", "chain": src[n - 1].strip()[:60], "enforced": "yes",
                    "evidence": f"{CHECKOUT}:14 if (mainButtonDisabled) return inside continueReviewedOrder"} for n in refs]
            self.ok("impact_check.py", "guard", self.S, "--json", "-", payload=dict(GUARD, entry_points=eps))
            self.ok("impact_check.py", "symbol", self.S, "--json", "-", payload={
                "name": "continueReviewedOrder", "file": CHECKOUT, "kind": "handler",
                "before": "places the order whenever called", "after": "returns without placing while mainButtonDisabled",
                "consumers": [{"ref": CHECKOUT, "targeted": True}]})
        for sym in ({"name": "Checkout", "file": CHECKOUT, "kind": "component", "before": "submits while COD re-checks",
                     "after": "CTA and continueReviewedOrder blocked while payment methods re-check", "consumers": []},
                    {"name": "useCheckoutEffects", "file": "src/screens/Checkout/useCheckoutEffects.ts", "kind": "hook",
                     "before": "refetch typed as ICreditCard[] (wrong)", "after": "refetch typed as the {codAvailable, methods} result",
                     "consumers": []},
                    {"name": "styles", "file": "src/screens/PayWith/index.tsx", "kind": "style", "changes_contract": False,
                     "before": "-", "after": "-", "no_change_reason": "adds the addButton style; existing keys untouched",
                     "consumers": []}):
            self.ok("impact_check.py", "symbol", self.S, "--json", "-", payload=sym)
        self.ok("verify_baseline.py", "run", self.S, "--project", self.fx.repo, "--name", "tsc", "--phase", "after",
                "--cmd", self.fx.tsc_cmd("baseline"))
        self.ok("verify_baseline.py", "not-run", self.S, "--name", "eslint", "--phase", "after",
                "--reason", "fixture project has no ESLint installed")
        chk = self.ok("change_log.py", "check", self.S, code=1)
        entries = [{"what": f"change in {h['file']}", "where": f"{h['file']}:{h['lines']}", "change": "CHANGED",
                    "why": {"source": "ticket", "ref": "AC-1", "text": "COD availability handling"}}
                   for h in chk["uncovered_hunks"]]
        self.ok("change_log.py", "add", self.S, "--json", "-", payload=entries)
        self.ok("impact_check.py", "review", self.S, "--json", "-",
                payload={"reviewer": "coderabbit", "scope": "full-diff", "fresh": True, "findings": []})
        rv = self.ok("impact_check.py", "review", self.S, "--json", "-",
                     payload={"reviewer": "system-subagent", "scope": "full-diff", "agent": "fresh read-only subagent",
                              "findings": [{"id": "SR1", "severity": "minor", "ref": f"{SHEET}:16", "title": "Wallet row behavior"}]})
        self.ok("decision_records.py", "finding", self.D, "--json", "-",
                payload={"source": "system-review", "review_ref": f"{rv['id']}/SR1", "ref": f"{SHEET}:16",
                         "title": "Wallet row behavior", "classification": "VALID", "kind": "test-gap", "disposition": "DEFERRED",
                         "reason": "regression test for Wallet follows in TK-4310", "actor": "developer"})
        self.ok("final_report.py", "pr", self.S)

    def test_feature_end_to_end(self):
        self.intake()
        target = self.fx.repo / SHEET
        deny = hook("pre", target)
        self.assertEqual(deny["hookSpecificOutput"]["permissionDecision"], "deny", "no edit before the plan checkpoint")
        c, g = self.gate("plan")
        self.assertEqual(c, 1)
        self.assertTrue(any("changed-symbol consumer analysis missing" in b for b in g["blockers"]))
        self.plan_records()
        c, g = self.gate("plan")
        self.assertEqual(c, 0, g["blockers"])
        self.assertTrue(any("UNGUARDED path" in w for w in g["warnings"]), "unguarded paths are shown at the plan")
        self.assertIsNone(hook("pre", target), "edits allowed once the checkpoint passed")
        self.ok("decision_records.py", "transition", self.D, "D-001", "UNDER_REVIEW", "--actor", "claude")
        self.ok("decision_records.py", "transition", self.D, "D-001", "APPROVED", "--actor", "developer", "--via", "Decision question")
        self.ok("change_log.py", "start", self.S, "--project", self.fx.repo)
        # post-edit hook: an existing symbol modified outside the analysis is flagged right away
        co = self.fx.repo / CHECKOUT
        co.write_text(co.read_text().replace("placeOrder(cart);", "placeOrder(cart, {source: 'checkout'});"))
        post = hook("post", co)
        self.assertIn("continueReviewedOrder", post["hookSpecificOutput"]["additionalContext"])
        co.write_text(co.read_text().replace("placeOrder(cart, {source: 'checkout'});", "placeOrder(cart);"))
        # implementation with the guard bypass left in → NOT READY
        self.finish_review_records(guard_fixed=False)
        c, g = self.gate("review")
        self.assertEqual((c, g["readiness"]), (1, "NOT READY"))
        self.assertTrue(any("UNGUARDED path" in b and ":28" in b for b in g["blockers"]), g["blockers"])
        # fix the bypass; the earlier reviews no longer match the diff → re-review the final diff
        co.write_text(co.read_text().replace("  const continueReviewedOrder = () => {\n",
                                             "  const continueReviewedOrder = () => {\n    if (mainButtonDisabled) return;\n"))
        c, g = self.gate("review")
        self.assertTrue(any("final full-diff review missing" in b for b in g["blockers"]), g["blockers"])
        co.write_text(co.read_text().replace("    if (mainButtonDisabled) return;\n", "", 1))
        self.fx2_reset_reviews()
        self.finish_review_records(guard_fixed=True)
        c, g = self.gate("review")
        self.assertEqual(c, 0, g["blockers"])
        self.assertEqual(g["readiness"], "READY WITH OPEN QUESTIONS")
        pr = (self.S / "pr.md").read_text()
        for needle in ("## Reviewer Notes", "Q-001", "Q-002", "Not chosen: Radio for every no-card user", "Wallet"):
            self.assertIn(needle, pr)
        rep = self.ok("final_report.py", "build", self.S, "--out", self.S / "report", "--project", self.fx.repo)
        self.assertTrue(rep["final_recommendation"].startswith("READY WITH OPEN QUESTIONS"), rep["final_recommendation"])
        md = (self.S / "report" / "report.md").read_text()
        self.assertIn("Guarded actions → all entry points → enforcement", md)
        self.assertIn("Type check and lint against the baseline", md)

    def fx2_reset_reviews(self):
        imp = json.loads((self.S / "impact.json").read_text())
        imp["reviews"] = []
        (self.S / "impact.json").write_text(json.dumps(imp))
        dec = json.loads(self.D.read_text())
        dec["findings"] = []
        self.D.write_text(json.dumps(dec))

    def test_misleading_pr_description_is_rejected(self):
        self.intake()
        self.plan_records()
        text = ("## Summary\n\n'Add New' keeps its radio behavior in PaymentMethodsSheet. This only affects COD users.\n\n"
                "## Reviewer Notes\n\nnone\n")
        (self.S / "pr-bad.md").write_text(text)
        c, out = run("final_report.py", "pr-check", self.S, "--text", self.S / "pr-bad.md")
        self.assertEqual(c, 1)
        joined = " ".join(out["problems"])
        self.assertIn("reads as preserved", joined)
        self.assertIn("limits the scope", joined)
        self.assertIn("Q-001", joined, "open questions must be listed")


class FixWorkflow(Base):
    task = "fix"

    def test_fix_has_no_plan_gate_but_the_same_checkpoint_before_the_first_edit(self):
        self.intake()
        deny = hook("pre", self.fx.repo / CHECKOUT)
        self.assertIn("before the first edit", deny["hookSpecificOutput"]["permissionDecisionReason"])
        self.ok("impact_check.py", "guard", self.S, "--json", "-", payload=GUARD)
        self.ok("impact_check.py", "declare", self.S, "--none", "symbols", "--reason", "the fix only adds a check inside continueReviewedOrder")
        c, g = self.gate("plan")
        self.assertEqual(c, 0, g["blockers"])
        self.assertIsNone(hook("pre", self.fx.repo / CHECKOUT))
        self.ok("impact_check.py", "finish", self.S)
        self.assertIsNone(hook("pre", self.fx.repo / CHECKOUT), "released at the end")


if __name__ == "__main__":
    unittest.main()
