"""Documentation is a claim surface, so it gets tests.

README.md and FAILURES.md assert specific numbers, commands, identifiers and
test names. Every one of those is checked here against the real repository, so
the docs cannot drift into being wrong - which for this project would be worse
than having no docs, since honesty about limits is the point.
"""

import ast
import hashlib
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
FAILURES = (ROOT / "FAILURES.md").read_text(encoding="utf-8")


def run(*args, timeout=180):
    import os
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "RAZORPAY_KEY_ID",
                        "RAZORPAY_KEY_SECRET", "PRAMAAN_DB",
                        "PRAMAAN_PROPOSER", "PRAMAAN_STATE_PROVIDER")}
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout, cwd=str(ROOT), env=env)


# --- the docs exist and lead with the right things -------------------------

def test_required_files_exist():
    assert (ROOT / "README.md").is_file()
    assert (ROOT / "FAILURES.md").is_file()


def test_readme_states_limits_before_features():
    """'What Pramaan does NOT prove' must appear above the quickstart."""
    not_proven = README.index("does NOT prove")
    quickstart = README.index("## Quickstart")
    assert not_proven < quickstart, "limitations are buried below the features"


def test_readme_cites_prior_art_early():
    """ProvenanceGuard must not be hidden in an appendix."""
    idx = README.index("ProvenanceGuard")
    assert idx / len(README) < 0.35, "prior art is buried"
    assert "arXiv 2606.18037" in README


def test_readme_answers_the_six_required_questions():
    for phrase in ("checks every factual claim",          # what is it
                   "cannot tell from the text",           # why it exists
                   "final_attempt  -> SEND",              # state-flip example
                   "What Pramaan proves",                 # scoped guarantee
                   "does NOT prove",                      # limits
                   "recheck"):                            # independent check
        assert phrase in README, f"README does not answer: {phrase!r}"


# --- claimed numbers match reality -----------------------------------------

def test_claimed_test_count_matches_reality():
    r = run(sys.executable, "-m", "pytest", "tests/", "-q", "--collect-only")
    actual = int(re.search(r"(\d+) tests collected", r.stdout).group(1))
    claimed = {int(m) for m in re.findall(r"\b(\d{3})\s+(?:offline\s+)?tests", README)}
    assert claimed, "README states no test count"
    assert actual in claimed, f"README claims {claimed}, repository has {actual}"


def test_claimed_ceilings_match_the_computed_values():
    """The 57.1% / 50.0% / 45.7% figures are computed, not measured."""
    r = run(sys.executable, "killtest/audit_dataset.py")
    assert r.returncode == 0, r.stderr
    for figure in ("57.1%", "50.0%", "45.7%"):
        assert figure in r.stdout, f"{figure} not produced by the audit"
        assert figure in README, f"{figure} claimed nowhere in README"


def test_claimed_frozen_identifiers_are_real():
    dataset = (ROOT / "killtest" / "dataset.json").read_text(encoding="utf-8")
    digest = hashlib.sha256(dataset.encode()).hexdigest()
    assert digest.startswith("f3b65c56"), "dataset changed since the freeze"
    assert "f3b65c56" in README

    from pramaan.llm.prompt import prompt_identity
    assert prompt_identity() == "proposer-v1+e9521f9d39fd97eb"
    assert "proposer-v1+e9521f9d39fd97eb" in README

    commit = run("git", "rev-parse", "phase3-freeze^{commit}").stdout.strip()
    assert commit.startswith("8b0d3753"), commit
    assert "8b0d3753" in README


def test_claimed_per_area_test_counts_are_plausible():
    """Every module named in the README's test table must exist."""
    for area in ("test_repo_integrity", "test_llm_adapter", "test_storage",
                 "test_gate", "test_app_cli", "test_killtest_harness",
                 "test_policy", "test_state_provider"):
        assert (ROOT / "tests" / f"{area}.py").is_file(), area


# --- every command in the README actually runs -----------------------------

@pytest.mark.parametrize("cmd", [
    ("demo",),
    ("status",),
    ("recheck", "--all"),
])
def test_readme_commands_run(tmp_path, cmd):
    db = str(tmp_path / "doc.db")
    if cmd[0] == "recheck":
        run(sys.executable, "-m", "pramaan", "--db", db, "demo")
    r = run(sys.executable, "-m", "pramaan", "--db", db, *cmd)
    assert r.returncode == 0, f"{cmd} failed:\n{r.stdout}\n{r.stderr}"


def test_readme_evaluate_example_runs(tmp_path):
    r = run(sys.executable, "-m", "pramaan", "--db", str(tmp_path / "e.db"),
            "evaluate", "--draft",
            "This is our final attempt. Your 15% offer expires in 24 hours.",
            "--customer", "alice", "--scenario", "final_attempt",
            "--now", "2026-09-04T10:00:00+00:00")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "disposition   SEND" in r.stdout


def test_readme_demo_output_matches_what_is_documented(tmp_path):
    r = run(sys.executable, "-m", "pramaan", "--db", str(tmp_path / "d.db"), "demo")
    for line in ("final_attempt  -> SEND", "first_attempt  -> BLOCK"):
        assert line in r.stdout, f"README shows {line!r}, demo does not print it"
        assert line in README


# --- FAILURES.md is verifiable ---------------------------------------------

def _all_test_names() -> set[str]:
    names = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                names.add(node.name)
    return names


def test_every_test_referenced_by_failures_md_exists():
    """A failure log citing tests that do not exist is worthless."""
    referenced = set(re.findall(r"::(test_\w+)", FAILURES))
    referenced |= {m for m in re.findall(r"`(test_\w+)`", FAILURES)}
    assert referenced, "FAILURES.md cites no tests"
    missing = referenced - _all_test_names()
    assert not missing, f"FAILURES.md cites non-existent tests: {sorted(missing)}"


def test_failures_md_has_substantive_entries():
    entries = re.findall(r"^## \d+\.", FAILURES, re.MULTILINE)
    assert len(entries) >= 10, f"only {len(entries)} numbered entries"
    for required in ("What was wrong", "What changed"):
        assert FAILURES.count(required) >= 10, f"entries lack '{required}'"


def test_retired_validator_is_described_as_deleted_not_fixed():
    assert "deleted, not patched" in FAILURES


# --- the docs must not overclaim -------------------------------------------

def test_readme_does_not_claim_a_live_integration():
    """Scans only NON-NEGATED occurrences.

    A naive substring scan flagged "tamper-proof" inside the sentence "Not
    tamper-proof" - a disclaimer, which is the opposite of an overclaim. The
    term appearing in a denial is exactly what this project wants.
    """
    negations = ("not ", "never ", "no ", "does not", "cannot", "is not")
    for overclaim in ("razorpay integrated", "live integration works",
                      "production-ready", "exactly-once", "tamper-proof",
                      "guarantees delivery", "eliminates hallucination"):
        for raw_line in README.splitlines():
            line = raw_line.lower()
            if overclaim not in line:
                continue
            before = line[:line.index(overclaim)]
            negated = any(n in before for n in negations)
            assert negated, f"README overclaims (unnegated): {raw_line.strip()!r}"


def test_readme_says_the_kill_test_has_not_been_run():
    assert "has not been run" in README
    assert "no accuracy result" in README.lower()


def test_readme_marks_razorpay_as_a_skeleton():
    assert "skeleton" in README.lower()
    assert "No live call has ever been made" in README


def test_docs_contain_no_secrets():
    for doc in (README, FAILURES):
        assert "sk-ant" not in doc
        assert "rzp_live" not in doc
        assert not re.search(r"rzp_test_[A-Za-z0-9]{6,}", doc)


# --- demo artifacts: every runbook command must actually run ---------------

RUNBOOK = (ROOT / "DEMO_RUNBOOK.md").read_text(encoding="utf-8")
SCRIPT = (ROOT / "VIDEO_SCRIPT.md").read_text(encoding="utf-8")


def test_demo_artifacts_exist():
    assert (ROOT / "DEMO_RUNBOOK.md").is_file()
    assert (ROOT / "VIDEO_SCRIPT.md").is_file()
    assert (ROOT / "scripts" / "tamper_demo.py").is_file()


def test_full_demo_sequence_runs_offline(tmp_path):
    """C1 -> C2 -> C3: demo, clean replay, tamper, failing replay."""
    db = str(tmp_path / "runbook.db")

    demo = run(sys.executable, "-m", "pramaan", "--db", db, "demo")
    assert demo.returncode == 0, demo.stderr
    for line in ("model=MOCK", "final_attempt  -> SEND",
                 "first_attempt  -> BLOCK", "-> ESCALATE",
                 "coverage_passed=False", "deliver + commit  -> created",
                 "COOLDOWN_NOT_ELAPSED"):
        assert line in demo.stdout, f"demo missing {line!r}"

    clean = run(sys.executable, "-m", "pramaan", "--db", db, "recheck", "--all")
    assert clean.returncode == 0, clean.stdout
    assert "re-verified (no model calls, no network)" in clean.stdout

    tamper = run(sys.executable, "scripts/tamper_demo.py", db)
    assert tamper.returncode == 0, tamper.stderr
    assert "attempt_index" in tamper.stdout

    after = run(sys.executable, "-m", "pramaan", "--db", db, "recheck", "--all")
    assert after.returncode == 1, "replay did not fail after tampering"
    assert "snapshot hash mismatch" in after.stdout
    assert "disposition mismatch" in after.stdout


def test_tamper_script_refuses_without_a_prepared_database(tmp_path):
    from pramaan.storage import db as storage
    path = tmp_path / "empty.db"
    storage.connect(path).close()
    r = run(sys.executable, "scripts/tamper_demo.py", str(path))
    assert r.returncode == 2 and "no suitable snapshot" in r.stdout


@pytest.mark.parametrize("selection,expect_passed", [
    ("touches_neither or calls_provider_then_propose", 3),
    ("crafted or absent_record", 3),
])
def test_runbook_test_selections_pass(selection, expect_passed):
    """C4 and C5 quote exact pass counts; verify them."""
    target = ("tests/test_gate.py" if "touches" in selection
              else "tests/test_rules.py")
    r = run(sys.executable, "-m", "pytest", target, "-k", selection,
            "-q", "--no-header")
    assert r.returncode == 0, r.stdout
    assert f"{expect_passed} passed" in r.stdout, r.stdout


def test_runbook_storage_selection_count_is_accurate():
    r = run(sys.executable, "-m", "pytest", "tests/test_storage.py", "-k",
            "append_only or raw_sql_cannot", "-q", "--no-header")
    assert r.returncode == 0
    claimed = re.search(r"^13 passed$", RUNBOOK, re.MULTILINE)
    actual = re.search(r"(\d+) passed", r.stdout).group(1)
    assert claimed, "runbook does not state a count for C6"
    assert actual == "13", f"runbook claims 13, actual {actual}"


def test_script_says_the_proposer_is_a_mock():
    """The one dishonest move available; guard against it."""
    assert "model=MOCK" in SCRIPT
    assert "deterministic fixture, not Claude" in SCRIPT
    assert "deterministic mock" in SCRIPT.lower()


def _prose_lines(doc: str) -> list[str]:
    """Lines that are actually assertions, excluding the claim-guard section.

    That section's entire purpose is to ENUMERATE forbidden phrases in a
    "DO NOT SAY" column, so scanning it for those phrases flags the guard
    itself. Excluded by section heading, not by guessing at table syntax.
    """
    out, in_guard = [], False
    for raw in doc.splitlines():
        if raw.startswith("#"):
            in_guard = "claim guard" in raw.lower()
        if not in_guard:
            out.append(raw)
    return out


def test_the_claim_guard_actually_lists_forbidden_phrases():
    """The exclusion above must not be able to hide an empty guard."""
    guard = RUNBOOK[RUNBOOK.lower().index("## 4. claim guard"):]
    for phrase in ("Tamper-proof", "Exactly-once", "Integrated with Razorpay"):
        assert phrase in guard, f"claim guard omits {phrase!r}"
    assert "DO NOT SAY" in guard


def test_script_and_runbook_do_not_overclaim():
    negations = ("not ", "never ", "no ", "does not", "cannot", "is not",
                 "rather than")
    for name, doc in (("VIDEO_SCRIPT", SCRIPT), ("DEMO_RUNBOOK", RUNBOOK)):
        for overclaim in ("tamper-proof", "production-ready", "exactly-once",
                          "live razorpay", "outperforms", "guaranteed",
                          "npci compliant", "fraud prevention"):
            for raw in _prose_lines(doc):
                line = raw.lower()
                if overclaim not in line:
                    continue
                before = line[:line.index(overclaim)]
                assert any(n in before for n in negations), \
                    f"{name} overclaims: {raw.strip()!r}"


def test_script_evidence_map_cites_real_tests():
    referenced = set(re.findall(r"::(test_\w+)", SCRIPT))
    assert len(referenced) >= 15, f"only {len(referenced)} tests cited"
    missing = referenced - _all_test_names()
    assert not missing, f"script cites non-existent tests: {sorted(missing)}"


def test_script_discloses_every_live_limitation():
    lowered = SCRIPT.lower()
    for disclosure in ("never made a live model call", "boundary skeleton",
                       "no accuracy claim", "tamper *evidence*"):
        assert disclosure in lowered or disclosure in SCRIPT, \
            f"script omits disclosure: {disclosure!r}"
