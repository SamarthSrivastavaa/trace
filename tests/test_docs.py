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
