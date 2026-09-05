"""The kill-test harness.

Two things are defended here:

  1. EQUIVALENCE - the B3 arm is the shipped Attest path, not a harness-local
     lookalike. Measuring a variant would produce a number about a system that
     does not exist.
  2. ACCOUNTING - instrumentation observes and never influences. A recorded
     call must be byte-identical to an unrecorded one.

No live API call. No credentials.
"""

import ast
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "killtest"))

import run_arms                                          # noqa: E402
from instrument import (CallRecord, Ledger, RecordingTransport,   # noqa: E402
                        classify, summarise)
from attest.llm.client import MAX_TOKENS, MODEL, TransportResponse  # noqa: E402
from attest.llm.errors import (ProposerMalformedOutput,          # noqa: E402
                                ProposerNotConfigured,
                                ProposerSchemaViolation, ProposerTimeout,
                                ProposerTransportFailure)
from attest.llm.prompt import SYSTEM_PROMPT, prompt_identity     # noqa: E402


# --- B. equivalence proof ---------------------------------------------------

def test_b3_gate_passes_and_reports_production_identity():
    ident = run_arms.assert_b3_is_production()
    assert ident["prompt_identity"] == prompt_identity()
    assert ident["proposer"] == "attest.llm.propose.ClaudeProposer"
    assert ident["extractor"] == "attest.llm.propose.extract_json_object"


def test_harness_has_no_local_b3_prompt():
    assert not hasattr(run_arms, "B3_SYS"), "harness reintroduced a B3 prompt"
    src = (ROOT / "killtest" / "run_arms.py").read_text(encoding="utf-8")
    assert "B3_SYS = " not in src


def test_b3_prompt_is_the_production_prompt_object():
    """Identity, not equality - a copied string would drift silently."""
    from attest.llm import propose as prod
    assert prod.SYSTEM_PROMPT is SYSTEM_PROMPT


def test_harness_does_not_redeclare_the_model():
    """The production adapter owns the model identifier."""
    assert run_arms.MODEL is MODEL
    assert run_arms.MAX_TOKENS is MAX_TOKENS
    tree = ast.parse((ROOT / "killtest" / "run_arms.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in ("MODEL", "MAX_TOKENS"):
                    pytest.fail(f"harness assigns its own {t.id}")


def test_b3_adjudicates_with_production_rules():
    import inspect
    src = inspect.getsource(run_arms.b3_label)
    assert "adjudicate_all" in src
    assert run_arms.adjudicate_all.__module__ == "attest.core.verify.rules"
    assert run_arms.Proposal.__module__ == "attest.core.verify.schema"


def test_b3_gate_fails_if_the_prompt_drifts(monkeypatch):
    """The assertion must actually bite."""
    from attest.llm import propose as prod
    monkeypatch.setattr(prod, "SYSTEM_PROMPT", "a different prompt")
    with pytest.raises(AssertionError):
        run_arms.assert_b3_is_production()


def test_only_baselines_use_a_raw_client_call():
    """B3 must go through the adapter; B1/B2 legitimately do not."""
    src = (ROOT / "killtest" / "run_arms.py").read_text(encoding="utf-8")
    assert src.count("client.messages.create") == 1
    tree = ast.parse(src)
    owners = [n.name for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and "client.messages.create" in ast.unparse(n)]
    assert owners == ["baseline_call"], owners


def test_both_state_aware_arms_receive_the_same_snapshot():
    src = (ROOT / "killtest" / "run_arms.py").read_text(encoding="utf-8")
    assert src.count("dataset_state_to_snapshot(c[\"state\"])") == 1, \
        "state must be adapted once per case and shared by B2 and B3"


# --- C. instrumentation -----------------------------------------------------

class FakeInner:
    name = "fake"
    model = "fake-model"

    def __init__(self, response=None, raises=None):
        self._response, self._raises = response, raises
        self.seen: list[tuple[str, str]] = []

    def send(self, system, user):
        self.seen.append((system, user))
        if self._raises:
            raise self._raises
        return self._response or TransportResponse(
            text='{"claims": []}', model=self.model,
            input_tokens=120, output_tokens=45, latency_ms=250.0)


def test_recording_transport_forwards_input_unchanged():
    inner = FakeInner()
    RecordingTransport(inner, Ledger(), "B3").send("SYS", "USR")
    assert inner.seen == [("SYS", "USR")]


def test_recording_transport_returns_the_response_unchanged():
    """Accounting must not alter an arm's output."""
    inner = FakeInner()
    ledger = Ledger()
    direct = inner.send("SYS", "USR")
    wrapped = RecordingTransport(inner, ledger, "B3").send("SYS", "USR")
    assert wrapped == direct


def test_successful_call_is_recorded_with_usage_and_latency():
    ledger = Ledger()
    t = RecordingTransport(FakeInner(), ledger, "B3")
    t.case_id, t.split = "c_abc", "dev"
    t.send("SYS", "USR")
    (rec,) = ledger.records
    assert (rec.arm, rec.case_id, rec.split, rec.ok) == ("B3", "c_abc", "dev", True)
    assert (rec.input_tokens, rec.output_tokens, rec.total_tokens) == (120, 45, 165)
    assert rec.latency_ms == 250.0
    assert rec.retries is None          # UNAVAILABLE - SDK does not expose it


def test_missing_usage_is_recorded_as_none_not_estimated():
    ledger = Ledger()
    inner = FakeInner(TransportResponse(text="{}", model="m"))
    RecordingTransport(inner, ledger, "B3").send("S", "U")
    (rec,) = ledger.records
    assert rec.input_tokens is None and rec.output_tokens is None
    assert rec.total_tokens is None


def test_failed_call_is_recorded_and_reraised():
    ledger = Ledger()
    inner = FakeInner(raises=ProposerTransportFailure("503"))
    t = RecordingTransport(inner, ledger, "B3")
    t.case_id = "c_fail"
    with pytest.raises(ProposerTransportFailure):
        t.send("S", "U")
    (rec,) = ledger.records
    assert rec.ok is False and rec.failure_class == "TRANSPORT"
    assert rec.latency_ms is not None


@pytest.mark.parametrize("exc,expected", [
    (ProposerSchemaViolation("x"), "SCHEMA"),
    (ProposerMalformedOutput("x"), "PARSE"),
    (ProposerTimeout("x"), "TIMEOUT"),
    (ProposerNotConfigured("x"), "NOT_CONFIGURED"),
    (ProposerTransportFailure("x"), "TRANSPORT"),
    (ValueError("x"), "OTHER"),
])
def test_failure_classes_stay_distinct(exc, expected):
    """Schema failures must never be counted as transport failures."""
    assert classify(exc) == expected


def test_timeout_is_not_collapsed_into_transport():
    """ProposerTimeout subclasses ProposerTransportFailure - order matters."""
    assert classify(ProposerTimeout("t")) == "TIMEOUT"


def test_p95_is_unavailable_below_twenty_samples():
    assert summarise([1.0] * 19)["p95"] is None
    assert summarise([1.0] * 20)["p95"] is not None
    assert summarise([])["n"] == 0


def test_summarise_median_and_mean():
    s = summarise([10.0, 20.0, 30.0])
    assert s["median"] == 20.0 and s["mean"] == 20.0


def test_ledger_writes_every_record_verbatim(tmp_path):
    ledger = Ledger()
    ledger.add(CallRecord(arm="B3", case_id="c1", split="dev", model="m",
                          ok=True, input_tokens=10, output_tokens=5))
    ledger.add(CallRecord(arm="B1", case_id="c1", split="dev", model="m",
                          ok=False, failure_class="PARSE"))
    path = tmp_path / "ledger.json"
    ledger.write(path)
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert len(rows) == 2
    assert rows[0]["total_tokens"] == 15
    assert rows[1]["total_tokens"] is None
    assert not any("api_key" in k.lower() or "key" == k.lower() for r in rows for k in r)


def test_ledger_totals_are_none_when_provider_gave_nothing():
    ledger = Ledger()
    ledger.add(CallRecord(arm="B3", case_id="c", split="dev", model="m", ok=True))
    assert ledger.token_total("B3", "input_tokens") is None
    assert ledger.latencies("B3") == []


def test_instrumentation_never_touches_prompt_or_case_order():
    """Structural: the module must not import prompts, datasets or rules."""
    tree = ast.parse((ROOT / "killtest" / "instrument.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    assert not any(m.endswith(("prompt", "rules", "coverage", "schema"))
                   for m in mods), mods


def test_no_api_key_appears_in_recorded_fields():
    rec = CallRecord(arm="B3", case_id="c", split="dev", model=MODEL, ok=True)
    blob = json.dumps(rec.__dict__)
    assert "sk-ant" not in blob and "ANTHROPIC_API_KEY" not in blob
