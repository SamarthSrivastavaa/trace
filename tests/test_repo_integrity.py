"""Repository coherence: no stale trusted-validation paths, one implementation
of each core concern, and the benchmark adapter's unit handling.

The exploitable killtest/validator.py was deleted. These tests make its return
a build failure rather than a code-review catch.
"""

import ast
import importlib
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = [p for p in ROOT.rglob("*.py")
           if "__pycache__" not in p.parts and ".pytest_cache" not in p.parts]

sys.path.insert(0, str(ROOT / "killtest"))


def _imported_modules(path: pathlib.Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_source_imports_the_retired_validator(path):
    """The deleted module was exploitable through a crafted __eq__."""
    assert "validator" not in _imported_modules(path), \
        f"{path.relative_to(ROOT)} imports the retired validator module"


def test_retired_validator_file_is_gone():
    assert not (ROOT / "killtest" / "validator.py").exists()


def test_run_arms_imports():
    """The kill-test harness must load without an API key."""
    mod = importlib.import_module("run_arms")
    assert mod.MODEL
    assert set(mod.LABELS) == {"SUPPORTED", "CONTRADICTED", "UNVERIFIABLE"}


def _defines(name: str) -> list[str]:
    """Files defining a top-level function with this name."""
    out = []
    for path in SOURCES:
        if "tests" in path.parts:
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                out.append(str(path.relative_to(ROOT)))
    return out


@pytest.mark.parametrize("func", [
    "canonicalise", "snapshot_hash", "normalise", "require_normalised",
    "adjudicate", "find_spans"])
def test_exactly_one_implementation_of_each_deterministic_primitive(func):
    """A second copy of any of these is a second trust boundary.

    Asserted on FUNCTION DEFINITIONS, not filenames: attest/policy/schema.py
    and attest/core/verify/schema.py legitimately share a filename while being
    different concerns (policy documents vs claim types). A stem-based check
    flagged that as duplication, which was a brittle test, not a real finding.
    """
    hits = _defines(func)
    assert len(hits) == 1, f"{func}: expected 1 definition, found {hits}"


def test_policy_reuses_the_single_canonicalisation():
    """Policy identity must not grow its own hasher.

    Checks RELATIVE imports too - _imported_modules() only reports absolute
    ones, and the real import here is `from ..core.verify.canonical import
    canonicalise`, which that helper cannot see.
    """
    tree = ast.parse((ROOT / "attest" / "policy" / "loader.py")
                     .read_text(encoding="utf-8"))
    modules = [node.module or "" for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom)]
    assert any("canonical" in m for m in modules), \
        f"policy/loader.py does not import the shared canonicaliser: {modules}"


def test_deterministic_core_runs_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from attest.core.pipeline import evaluate
    from attest.fixtures import scenarios as fx
    from attest.state.contract import StateRequest
    from attest.state.fixture import FixtureStateProvider
    r = evaluate(fx.DRAFT, StateRequest("m", "c", "final_attempt"),
                 FixtureStateProvider(), fx.mock_model)
    assert r["disposition"].value == "SEND"


def test_recheck_cli_help_runs_without_key():
    out = subprocess.run([sys.executable, "recheck.py", "--help"],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr


# --- benchmark adapter -----------------------------------------------------

def test_adapter_converts_rupees_to_paise_for_flat_offers():
    """The frozen dataset stores offer flat amounts in RUPEES while payment and
    cart totals are already in PAISE. Verified against its own gold labels."""
    from adapt import dataset_state_to_snapshot
    snap = dataset_state_to_snapshot(
        {"now": "2026-09-04T10:00:00+05:30",
         "offers": [{"offer_id": "o1", "flat_amount": 500, "active": True}]})
    assert snap["offers"][0]["flat_amount_minor"] == 50000


def test_adapter_leaves_already_minor_units_alone():
    from adapt import dataset_state_to_snapshot
    snap = dataset_state_to_snapshot(
        {"payment": {"amount": 249900, "status": "failed"},
         "cart": {"item_count": 2, "total": 499900}})
    assert snap["payment"]["amount_minor"] == 249900
    assert snap["cart"]["total_minor"] == 499900


def test_adapter_preserves_inventory_for_arm_fairness():
    """No EvidenceRef can cite inventory, but 9 dataset cases have gold labels
    that depend on it. Dropping it would penalise the competing arm for OUR
    schema's limitation."""
    from adapt import dataset_state_to_snapshot
    snap = dataset_state_to_snapshot({"inventory": {"sku_88": 2}})
    assert snap["inventory"] == {"sku_88": 2}


def test_adapter_is_pure():
    from adapt import dataset_state_to_snapshot
    src = {"cart": {"item_count": 2, "total": 499900}}
    before = repr(src)
    dataset_state_to_snapshot(src)
    assert repr(src) == before


def test_adapter_output_is_canonicalisable():
    """Whatever the adapter emits must be hashable by the production canon."""
    import json

    from adapt import dataset_state_to_snapshot
    from attest.core.verify.canonical import snapshot_hash
    cases = json.loads((ROOT / "killtest" / "dataset.json").read_text(encoding="utf-8"))
    for c in cases:
        snapshot_hash(dataset_state_to_snapshot(c["state"]))


def test_b3_label_rolls_up_with_contradicted_precedence():
    import run_arms
    assert run_arms.aggregate([]) == "UNVERIFIABLE"
    assert run_arms.aggregate(["SUPPORTED"]) == "SUPPORTED"
    assert run_arms.aggregate(["SUPPORTED", "CONTRADICTED"]) == "CONTRADICTED"
    assert run_arms.aggregate(["SUPPORTED", "UNVERIFIABLE"]) == "UNVERIFIABLE"
    assert run_arms.aggregate(["MALFORMED"]) == "UNVERIFIABLE"
    assert run_arms.aggregate(["CONTRADICTED", "MALFORMED"]) == "CONTRADICTED"


def test_b3_label_uses_production_schema_and_rules():
    """End-to-end through the real contract, no model involved.

    Phase 9 moved schema validation into the production adapter
    (attest.llm.propose.to_proposal), so b3_label now receives an already
    validated Proposal. The invariant is unchanged - production schema, then
    production rules - only the seam moved.
    """
    import run_arms
    from adapt import dataset_state_to_snapshot
    from attest.llm.propose import to_proposal
    snap = dataset_state_to_snapshot(
        {"now": "2026-09-04T10:00:00+05:30",
         "subscription": {"status": "active", "attempt_index": 1,
                          "max_attempts": 4, "next_action": "retry"}})
    proposal = to_proposal({"claims": [{
        "claim_id": "c1", "kind": "is_final_attempt",
        "span_start": 0, "span_end": 5,
        "asserted": {"kind": "bool", "value": True},
        "evidence": {"ref": "subscription", "field": "attempt_index"}}]})
    label, malformed = run_arms.b3_label(proposal, snap)
    assert label == "CONTRADICTED"      # attempt 1 of 4 is not the final one
    assert malformed == 0


def test_b3_label_counts_fabricated_citation_separately():
    import run_arms
    from attest.llm.propose import to_proposal
    snap = {"now": "2026-09-04T10:00:00+05:30", "offers": []}
    proposal = to_proposal({"claims": [{
        "claim_id": "c1", "kind": "discount_percent",
        "span_start": 0, "span_end": 3,
        "asserted": {"kind": "percent", "value": "15.00"},
        "evidence": {"ref": "offer", "offer_id": "ofr_ZZ9", "field": "percent"}}]})
    label, malformed = run_arms.b3_label(proposal, snap)
    assert label == "UNVERIFIABLE"
    assert malformed == 1


def test_production_validation_raises_on_schema_violation():
    """Must raise so the harness books a SCHEMA failure, not a reasoning error.

    The raise now comes from the production adapter, which is exactly where the
    live B3 arm hits it.
    """
    from attest.llm.errors import ProposerSchemaViolation
    from attest.llm.propose import to_proposal
    with pytest.raises(ProposerSchemaViolation):
        to_proposal({"claims": [{"claim_id": "c1", "kind": "vibes",
                                 "span_start": 0, "span_end": 1,
                                 "asserted": {"kind": "count", "value": 1}}]})


# --- architectural boundaries (Phase 2) ------------------------------------

def _module_imports(rel: str) -> set[str]:
    return _imported_modules(ROOT / rel)


def test_pipeline_does_not_import_razorpay():
    """The pipeline depends on the provider abstraction, not on a vendor."""
    imports = _module_imports("attest/core/pipeline.py")
    assert not any("razorpay" in m.lower() for m in imports), imports


def test_pipeline_does_not_import_a_concrete_provider():
    """Providers are injected. Importing one would hardwire the boundary."""
    imports = _module_imports("attest/core/pipeline.py")
    assert not any("state.fixture" in m or "integrations" in m for m in imports), \
        imports


@pytest.mark.parametrize("mod", [
    "attest/core/verify/rules.py", "attest/core/verify/coverage.py",
    "attest/core/verify/canonical.py", "attest/core/verify/normalise.py",
    "attest/core/verify/schema.py"])
def test_verify_modules_do_not_import_providers_or_storage(mod):
    """The trust boundary must not reach for state or a database."""
    imports = _module_imports(mod)
    banned = ("state", "storage", "integrations", "sqlite3", "socket",
              "anthropic", "httpx", "requests")
    hits = [m for m in imports if any(b in m for b in banned)]
    assert not hits, f"{mod} imports {hits}"


@pytest.mark.parametrize("mod", [
    "attest/state/fixture.py", "attest/integrations/razorpay/provider.py"])
def test_providers_do_not_import_adjudication(mod):
    """A provider fetches state. It never decides what that state supports."""
    imports = _module_imports(mod)
    hits = [m for m in imports if "rules" in m or "coverage" in m]
    assert not hits, f"{mod} imports adjudication: {hits}"


def test_razorpay_provider_is_confined_to_its_package():
    """Vendor SDK/API surface must not leak outside integrations/razorpay/."""
    offenders = []
    for p in SOURCES:
        if "integrations" in p.parts or "tests" in p.parts:
            continue
        if any("razorpay" in m.lower() for m in _imported_modules(p)):
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, offenders


# --- delivery/storage boundaries (Phase 6) ---------------------------------

def test_pipeline_does_not_write_send_log():
    """SEND is a decision. Recording a send is a separate, later fact."""
    src = (ROOT / "attest" / "core" / "pipeline.py").read_text(encoding="utf-8")
    for forbidden in ("commit_send", "send_log", "record_send"):
        assert forbidden not in src, f"pipeline references {forbidden}"


def test_policy_gate_does_not_write_storage():
    src = (ROOT / "attest" / "policy" / "gate.py").read_text(encoding="utf-8")
    for forbidden in ("INSERT", "UPDATE", "commit", "sqlite3", "conn"):
        assert forbidden not in src, f"gate.py references {forbidden}"


def test_only_storage_inserts_into_send_log():
    """One narrow boundary creates send facts."""
    offenders = []
    for path in SOURCES:
        if "tests" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        if "INSERT INTO send_log" in src and path.name != "db.py":
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, offenders


def test_delivery_module_has_no_network_or_vendor_imports():
    imports = _module_imports("attest/delivery.py")
    banned = ("socket", "requests", "httpx", "anthropic", "razorpay", "urllib",
              "smtplib", "twilio")
    hits = [m for m in imports if any(b in m.lower() for b in banned)]
    assert not hits, f"delivery.py imports {hits}"


def test_recheck_does_not_import_a_delivery_sender():
    imported = _module_imports("recheck.py")
    assert not any("delivery" in m for m in imported), imported


def test_verify_modules_do_not_import_storage_or_delivery():
    for mod in ("rules", "coverage", "canonical", "normalise", "schema"):
        imports = _module_imports(f"attest/core/verify/{mod}.py")
        hits = [m for m in imports if "storage" in m or "delivery" in m]
        assert not hits, f"{mod}.py imports {hits}"
