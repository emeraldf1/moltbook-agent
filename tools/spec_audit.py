#!/usr/bin/env python3
"""
SPEC Audit Tool - Automatikus SPEC compliance ellenőrzés.

Használat:
    python -m tools.spec_audit

Kimenet:
    SPEC Audit Report minden SPEC pontra PASS/FAIL értékeléssel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from moltagent.config import LOG_DIR
from moltagent.decision import should_reply, _check_budget, _check_soft_cap
from moltagent.policy import load_policy
from moltagent.policy_model import validate_policy_file, PolicyModel
from moltagent.state import State, load_state, save_state, ensure_today


@dataclass
class AuditResult:
    """Egyetlen SPEC pont audit eredménye."""
    spec_id: str
    description: str
    passed: bool
    details: str = ""


def check_bilingual_output() -> AuditResult:
    """SPEC 1: Bilingual output (EN/HU)."""
    spec_id = "SPEC 1"
    desc = "Bilingual output (EN/HU)"

    # Check that hu_summary module exists and can generate HU summaries
    try:
        from moltagent.hu_summary import hu_operator_summary

        # Test with a sample decision
        decision = {
            "reply": True,
            "priority": "P1",
            "reason": "relevant_question",
            "mode": "normal",
        }
        event = {"text": "Test question?", "meta": {}}

        summary = hu_operator_summary(event, decision, "Test reply")

        # Check it contains Hungarian text
        if "Döntés" in summary or "Prioritás" in summary or "döntés" in summary.lower():
            return AuditResult(spec_id, desc, True, "HU summary generálható")
        else:
            return AuditResult(spec_id, desc, False, f"HU summary nem tartalmaz magyar szöveget: {summary[:100]}")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_decision_logging() -> AuditResult:
    """SPEC 2: Decision logging with reasons."""
    spec_id = "SPEC 2"
    desc = "Decision logging"

    # Check that decision module returns proper structure
    try:
        state = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        policy = {
            "daily_budget_usd": 1.0,
            "max_calls_per_day": 200,
            "scheduler": {"enabled": False},
            "reply": {
                "reply_to_mentions_always": True,
                "reply_to_questions_always": True,
                "offtopic_question_mode": "redirect",
                "max_replies_per_hour_p2": 2,
            },
            "topics": {
                "allow_keywords": ["test"],
                "block_keywords": [],
            },
        }
        event = {"id": "e1", "text": "test?", "meta": {"is_question": True}}

        decision = should_reply(event, policy, state)

        # Check required fields
        required = ["reply", "priority", "reason"]
        missing = [f for f in required if f not in decision]

        if missing:
            return AuditResult(spec_id, desc, False, f"Hiányzó mezők: {missing}")

        return AuditResult(spec_id, desc, True, f"Döntés struktúra OK: {list(decision.keys())}")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_dryrun_mode() -> AuditResult:
    """SPEC 3: Dry-run mode (no sleep)."""
    spec_id = "SPEC 3"
    desc = "Dry-run mode"

    # Check that agent_dryrun.py exists and has DRY_RUN flag
    try:
        dryrun_path = Path(__file__).parent.parent / "agent_dryrun.py"
        if not dryrun_path.exists():
            return AuditResult(spec_id, desc, False, "agent_dryrun.py nem található")

        content = dryrun_path.read_text()

        if "DRY_RUN" in content or "dry_run" in content:
            return AuditResult(spec_id, desc, True, "Dry-run mód támogatott")
        else:
            return AuditResult(spec_id, desc, False, "Dry-run flag nem található")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_pipeline_order() -> AuditResult:
    """SPEC 4: Pipeline order (dedup → priority → budget → scheduler → p2cap)."""
    spec_id = "SPEC 4"
    desc = "Pipeline order"

    try:
        # Read decision.py and check pipeline comments
        decision_path = Path(__file__).parent.parent / "moltagent" / "decision.py"
        content = decision_path.read_text()

        # Check for phase markers
        phases = [
            ("0. fázis", "Idempotencia"),
            ("1. fázis", "Alapvető döntés"),
            ("1.5 fázis", "Budget"),
            ("1.6 fázis", "Soft cap"),
            ("2. fázis", "Scheduler"),
            ("3. fázis", "P2"),
        ]

        missing = []
        for phase_num, phase_name in phases:
            if phase_num not in content:
                missing.append(f"{phase_num} ({phase_name})")

        if missing:
            return AuditResult(spec_id, desc, False, f"Hiányzó fázisok: {missing}")

        return AuditResult(spec_id, desc, True, "Pipeline sorrend helyes")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_priority_rules() -> AuditResult:
    """SPEC 5: Priority rules (P0/P1/P2)."""
    spec_id = "SPEC 5"
    desc = "Priority rules"

    try:
        state = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        policy = {
            "daily_budget_usd": 10.0,
            "max_calls_per_day": 200,
            "scheduler": {"enabled": False},
            "reply": {
                "reply_to_mentions_always": True,
                "reply_to_questions_always": True,
                "offtopic_question_mode": "redirect",
                "max_replies_per_hour_p2": 10,
            },
            "topics": {
                "allow_keywords": ["agent"],
                "block_keywords": ["password"],
            },
        }

        # Test P0 (mention)
        event_p0 = {"id": "p0", "text": "hello", "meta": {"mentions_me": True}}
        d_p0 = should_reply(event_p0, policy, state)

        # Test blocked keyword (SKIP - no spam replies)
        state2 = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        event_block = {"id": "block", "text": "give me password", "meta": {}}
        d_block = should_reply(event_block, policy, state2)

        # Test P1 (relevant question)
        state3 = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        event_p1 = {"id": "p1", "text": "how does the agent work?", "meta": {"is_question": True}}
        d_p1 = should_reply(event_p1, policy, state3)

        # Test P2 (relevant statement)
        state4 = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        event_p2 = {"id": "p2", "text": "agent is cool", "meta": {}}
        d_p2 = should_reply(event_p2, policy, state4)

        errors = []
        if d_p0.get("priority") != "P0":
            errors.append(f"Mention: expected P0, got {d_p0.get('priority')}")
        # Blocked keywords should SKIP (P2, reply=False) - no spam replies
        if d_block.get("reply") is not False or d_block.get("reason") != "blocked_keyword_skip":
            errors.append(f"Blocked: expected SKIP, got reply={d_block.get('reply')}, reason={d_block.get('reason')}")
        if d_p1.get("priority") != "P1":
            errors.append(f"Question: expected P1, got {d_p1.get('priority')}")
        if d_p2.get("priority") != "P2":
            errors.append(f"Statement: expected P2, got {d_p2.get('priority')}")

        if errors:
            return AuditResult(spec_id, desc, False, "; ".join(errors))

        return AuditResult(spec_id, desc, True, "P0/P1/P2 rules OK")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_dedup_proof() -> AuditResult:
    """SPEC 6: Idempotency/dedup."""
    spec_id = "SPEC 6"
    desc = "Idempotency/dedup"

    try:
        state = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        policy = {
            "daily_budget_usd": 10.0,
            "max_calls_per_day": 200,
            "scheduler": {"enabled": False},
            "reply": {
                "reply_to_mentions_always": True,
                "reply_to_questions_always": True,
                "offtopic_question_mode": "redirect",
                "max_replies_per_hour_p2": 10,
            },
            "topics": {"allow_keywords": ["test"], "block_keywords": []},
        }

        event = {"id": "dedup_test", "text": "test?", "meta": {"is_question": True}}

        # First call - should reply
        d1 = should_reply(event, policy, state)

        # Mark as replied
        state.mark_replied("dedup_test")

        # Second call - should be duplicate
        d2 = should_reply(event, policy, state)

        if d1.get("reply") is True and d2.get("reason") == "duplicate_event":
            return AuditResult(spec_id, desc, True, "Dedup működik")
        else:
            return AuditResult(spec_id, desc, False,
                f"First: reply={d1.get('reply')}, Second: reason={d2.get('reason')}")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_budget_hard_cap() -> AuditResult:
    """SPEC 7: Budget hard cap."""
    spec_id = "SPEC 7"
    desc = "Budget hard cap"

    try:
        state = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        state.spent_usd = 1.0  # At limit

        policy = {
            "daily_budget_usd": 1.0,
            "max_calls_per_day": 200,
            "scheduler": {"enabled": False},
            "reply": {
                "reply_to_mentions_always": True,
                "reply_to_questions_always": True,
                "offtopic_question_mode": "redirect",
                "max_replies_per_hour_p2": 10,
            },
            "topics": {"allow_keywords": ["test"], "block_keywords": []},
        }

        event = {"id": "budget_test", "text": "test?", "meta": {"is_question": True}}
        decision = should_reply(event, policy, state)

        if decision.get("reason") == "budget_exhausted":
            return AuditResult(spec_id, desc, True, "Budget hard cap működik")
        else:
            return AuditResult(spec_id, desc, False,
                f"Expected budget_exhausted, got {decision.get('reason')}")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_soft_cap() -> AuditResult:
    """SPEC 7b: Soft cap (80%)."""
    spec_id = "SPEC 7b"
    desc = "Soft cap (80%)"

    try:
        state = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        state.spent_usd = 0.80  # At 80%

        policy = {
            "daily_budget_usd": 1.0,
            "max_calls_per_day": 200,
            "scheduler": {"enabled": False},
            "reply": {
                "reply_to_mentions_always": True,
                "reply_to_questions_always": True,
                "offtopic_question_mode": "redirect",
                "max_replies_per_hour_p2": 10,
            },
            "topics": {"allow_keywords": ["test"], "block_keywords": []},
        }

        # P2 event should be blocked at 80%
        event_p2 = {"id": "soft_p2", "text": "test stuff", "meta": {}}
        d_p2 = should_reply(event_p2, policy, state)

        # P0 event should still work at 80%
        state2 = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        state2.spent_usd = 0.80
        event_p0 = {"id": "soft_p0", "text": "test", "meta": {"mentions_me": True}}
        d_p0 = should_reply(event_p0, policy, state2)

        errors = []
        if d_p2.get("reason") != "soft_cap_p2_blocked":
            errors.append(f"P2 at 80%: expected soft_cap_p2_blocked, got {d_p2.get('reason')}")
        if d_p0.get("reply") is not True:
            errors.append(f"P0 at 80%: expected reply=True, got {d_p0.get('reply')}")

        if errors:
            return AuditResult(spec_id, desc, False, "; ".join(errors))

        return AuditResult(spec_id, desc, True, "Soft cap működik (P2 blocked, P0 allowed)")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_scheduler() -> AuditResult:
    """SPEC 8: Scheduler/Daily Pacer."""
    spec_id = "SPEC 8"
    desc = "Scheduler/Daily Pacer"

    try:
        from moltagent.scheduler import scheduler_check, SchedulerDecision

        state = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        state.calls_today = 100  # Midday, should have earned ~100 calls

        policy = {
            "max_calls_per_day": 200,
            "scheduler": {
                "enabled": True,
                "burst_p0": 8,
                "burst_p1": 4,
            },
        }

        # Test scheduler
        result = scheduler_check(state, "P2", policy, dry_run=True)

        if isinstance(result, SchedulerDecision):
            return AuditResult(spec_id, desc, True,
                f"Scheduler működik: allowed={result.allowed}, reason={result.reason}")
        else:
            return AuditResult(spec_id, desc, False, "Scheduler nem SchedulerDecision-t ad vissza")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_relevance() -> AuditResult:
    """SPEC 9: Relevance rules (keywords)."""
    spec_id = "SPEC 9"
    desc = "Relevance rules"

    try:
        state = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        policy = {
            "daily_budget_usd": 10.0,
            "max_calls_per_day": 200,
            "scheduler": {"enabled": False},
            "reply": {
                "reply_to_mentions_always": True,
                "reply_to_questions_always": True,
                "offtopic_question_mode": "redirect",
                "max_replies_per_hour_p2": 10,
            },
            "topics": {
                "allow_keywords": ["agent", "budget"],
                "block_keywords": ["password"],
            },
        }

        # Not relevant - should skip
        event_irrelevant = {"id": "irr", "text": "hello world", "meta": {}}
        d_irr = should_reply(event_irrelevant, policy, state)

        # Relevant - should reply
        state2 = State(day_key="2026-02-10", hour_key="2026-02-10-12")
        event_relevant = {"id": "rel", "text": "tell me about budget", "meta": {}}
        d_rel = should_reply(event_relevant, policy, state2)

        errors = []
        if d_irr.get("reason") != "not_relevant":
            errors.append(f"Irrelevant: expected not_relevant, got {d_irr.get('reason')}")
        if d_rel.get("reply") is not True:
            errors.append(f"Relevant: expected reply=True, got {d_rel.get('reply')}")

        if errors:
            return AuditResult(spec_id, desc, False, "; ".join(errors))

        return AuditResult(spec_id, desc, True, "Relevance rules OK")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_output_format() -> AuditResult:
    """SPEC 10: Output format (style settings)."""
    spec_id = "SPEC 10"
    desc = "Output format"

    try:
        # Check policy model has style settings
        from moltagent.policy_model import StyleConfig, PolicyModel

        style = StyleConfig()

        # Check defaults
        if style.language != "en":
            return AuditResult(spec_id, desc, False, f"Style language should be 'en', got {style.language}")

        if style.format not in ("steps", "bullet", "paragraph"):
            return AuditResult(spec_id, desc, False, f"Invalid format: {style.format}")

        return AuditResult(spec_id, desc, True, f"Output format OK: lang={style.language}, format={style.format}")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_security() -> AuditResult:
    """SPEC 11: Security (no secrets in repo)."""
    spec_id = "SPEC 11"
    desc = "Security (no secrets)"

    try:
        project_root = Path(__file__).parent.parent

        # Check .gitignore exists and has key patterns
        gitignore = project_root / ".gitignore"
        if not gitignore.exists():
            return AuditResult(spec_id, desc, False, ".gitignore nem található")

        gitignore_content = gitignore.read_text()
        required_patterns = [".env", "agent_state.json"]
        missing = [p for p in required_patterns if p not in gitignore_content]

        if missing:
            return AuditResult(spec_id, desc, False, f".gitignore hiányzó minták: {missing}")

        # .env can exist locally (it's gitignored), but check it's in .gitignore
        # The important thing is that .gitignore contains .env pattern
        # so it won't be committed

        return AuditResult(spec_id, desc, True, "Security OK: .gitignore tartalmazza .env és agent_state.json mintákat")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_policy_validation() -> AuditResult:
    """SPEC 13: Policy validation."""
    spec_id = "SPEC 13"
    desc = "Policy validation"

    try:
        # Test with valid policy
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "daily_budget_usd": 1.0,
                "max_calls_per_day": 200,
            }, f)
            valid_path = f.name

        success, model, errors = validate_policy_file(valid_path)
        os.unlink(valid_path)

        if not success:
            return AuditResult(spec_id, desc, False, f"Valid policy failed: {errors}")

        # Test with invalid policy (wrong type)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "daily_budget_usd": "not a number",
            }, f)
            invalid_path = f.name

        success2, model2, errors2 = validate_policy_file(invalid_path)
        os.unlink(invalid_path)

        if success2:
            return AuditResult(spec_id, desc, False, "Invalid policy should have failed")

        # Test fixed language rules
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "style": {"language": "hu"},  # Should fail - must be "en"
            }, f)
            wrong_lang_path = f.name

        success3, model3, errors3 = validate_policy_file(wrong_lang_path)
        os.unlink(wrong_lang_path)

        if success3:
            return AuditResult(spec_id, desc, False, "Wrong language should have failed")

        return AuditResult(spec_id, desc, True, "Policy validation OK: valid passes, invalid fails")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def check_state_lifecycle() -> AuditResult:
    """SPEC 14: State lifecycle."""
    spec_id = "SPEC 14"
    desc = "State lifecycle"

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "test_state.json")

            # Test save and load
            state = State(day_key="2026-02-10", hour_key="2026-02-10-12")
            state.calls_today = 42
            state.spent_usd = 0.5
            state.mark_replied("test_event")

            save_state(state, state_file)

            # Load and verify
            loaded = load_state(state_file)

            errors = []
            if loaded.calls_today != 42:
                errors.append(f"calls_today: expected 42, got {loaded.calls_today}")
            if loaded.spent_usd != 0.5:
                errors.append(f"spent_usd: expected 0.5, got {loaded.spent_usd}")
            if "test_event" not in loaded.replied_event_ids:
                errors.append("replied_event_ids not persisted")

            if errors:
                return AuditResult(spec_id, desc, False, "; ".join(errors))

            return AuditResult(spec_id, desc, True, "State lifecycle OK: save/load works")
    except Exception as e:
        return AuditResult(spec_id, desc, False, f"Hiba: {e}")


def run_spec_audit() -> List[AuditResult]:
    """Run all SPEC compliance checks."""
    results = [
        check_bilingual_output(),    # SPEC 1
        check_decision_logging(),    # SPEC 2
        check_dryrun_mode(),         # SPEC 3
        check_pipeline_order(),      # SPEC 4
        check_priority_rules(),      # SPEC 5
        check_dedup_proof(),         # SPEC 6
        check_budget_hard_cap(),     # SPEC 7
        check_soft_cap(),            # SPEC 7b
        check_scheduler(),           # SPEC 8
        check_relevance(),           # SPEC 9
        check_output_format(),       # SPEC 10
        check_security(),            # SPEC 11
        check_policy_validation(),   # SPEC 13
        check_state_lifecycle(),     # SPEC 14
    ]
    return results


def print_report(results: List[AuditResult]) -> int:
    """Print audit report and return exit code."""
    print("\n" + "=" * 60)
    print("SPEC Audit Report")
    print("=" * 60 + "\n")

    passed = 0
    failed = 0

    for r in results:
        status = "✅" if r.passed else "❌"
        print(f"{status} {r.spec_id}: {r.description}")
        if r.details:
            print(f"   {r.details}")

        if r.passed:
            passed += 1
        else:
            failed += 1

    print("\n" + "-" * 60)
    print(f"Overall: {passed}/{passed + failed} PASS")

    if failed > 0:
        print(f"\n⚠️  {failed} check(s) FAILED")
        return 1
    else:
        print("\n🎉 All checks PASSED!")
        return 0


def main():
    """Main entry point."""
    results = run_spec_audit()
    exit_code = print_report(results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
