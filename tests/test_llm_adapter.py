"""The LLM proposal adapter.

Central invariant: the model is an UNTRUSTED proposal generator. It cannot
decide any verdict or disposition, its output is authorised only by the
production Proposal schema, and no failure of it can produce SEND.

Every test here runs offline. None requires credentials or the anthropic SDK.
"""

import ast
import json
import pathlib
import socket
import subprocess
import sys

import pytest

from attest.core.pipeline import (FAILURE_MODEL_CALL, FAILURE_MODEL_SCHEMA,
                                   evaluate)
from attest.core.verify.schema import Disposition, Proposal
from attest.fixtures import scenarios as fx
from attest.llm.client import TransportResponse
from attest.llm.errors import (ProposerMalformedOutput, ProposerNotConfigured,
                                ProposerSchemaViolation, ProposerTimeout,
                                ProposerTransportFailure)
from attest.llm.propose import ClaudeProposer, extract_json_object, to_proposal
from attest.llm.prompt import SYSTEM_PROMPT, prompt_identity
from attest.state.contract import StateRequest
from attest.state.fixture import FixtureStateProvider
from attest.storage import db

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = "2026-09-04T10:00:00+00:00"
REQ = StateRequest("m", "cus", "final_attempt")


class FakeTransport:
    """The narrow seam. Records what was sent; returns canned text."""

    name = "fake"
    model = "fake-model"

    def __init__(self, text="", raises=None):
        self._text, self._raises = text, raises
        self.calls = 0
        self.sent: list[tuple[str, str]] = []

    def send(self, system, user):
        self.calls += 1
        self.sent.append((system, user))
        if self._raises:
            raise self._raises
        return TransportResponse(text=self._text, model=self.model)


def honest_json() -> str:
    return json.dumps(fx.honest_proposal())


@pytest.fixture()
def conn(tmp_path):
    return db.connect(tmp_path / "llm.db")


# --- A. no credentials required for import ---------------------------------

def test_adapter_modules_import_without_credentials_or_sdk():
    code = ("import attest.llm.propose, attest.llm.client, "
            "attest.llm.prompt, attest.llm.errors\n"
            "import sys\n"
            "assert 'anthropic' not in sys.modules, 'SDK imported eagerly'\n"
            "print('ok')\n")
    env = {k: v for k, v in __import__("os").environ.items()
           if k != "ANTHROPIC_API_KEY"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=90, cwd=str(ROOT), env=env)
    assert out.returncode == 0, out.stderr
    assert "ok" in out.stdout


def test_pipeline_does_not_import_the_anthropic_sdk():
    """core.pipeline imports the error taxonomy only - never the SDK."""
    tree = ast.parse((ROOT / "attest" / "core" / "pipeline.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    assert not any("anthropic" in m for m in mods), mods


# --- B. missing configuration ----------------------------------------------

def test_live_proposer_without_credentials_raises_typed_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProposerNotConfigured):
        ClaudeProposer()


def test_unconfigured_proposer_never_sends(conn, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def unconfigured(draft, state):
        raise ProposerNotConfigured("no key")

    r = evaluate(fx.DRAFT, REQ, FixtureStateProvider(), unconfigured, conn, now=NOW)
    assert r["disposition"] is Disposition.ESCALATE
    assert r["proof"]["failure_reason"] == FAILURE_MODEL_CALL


# --- C. exact boundary ------------------------------------------------------

def test_transport_receives_only_the_draft_and_state():
    t = FakeTransport(honest_json())
    ClaudeProposer(transport=t)(fx.DRAFT, fx.state_final_attempt())
    system, user = t.sent[0]
    assert fx.DRAFT in user
    for leak in ("suppressed", "last_send_at", "send_log", "policy",
                 "cooldown", "proof_id", "ANTHROPIC", "rzp_", "sqlite"):
        assert leak not in user, f"{leak!r} leaked into the model prompt"
        assert leak not in system, f"{leak!r} leaked into the system prompt"


def test_proposer_receives_no_connection_or_policy_object(conn):
    seen = {}

    def spy(draft, state):
        seen["args"] = (draft, state)
        return fx.honest_proposal()

    evaluate(fx.DRAFT, REQ, FixtureStateProvider(), spy, conn, now=NOW)
    draft, state = seen["args"]
    assert isinstance(draft, str) and isinstance(state, dict)
    assert set(state) <= {"now", "offers", "subscription", "customer",
                          "payment", "cart", "inventory"}


def test_prompt_encodes_no_policy_rules():
    """The prompt must not become a second verification or policy engine.

    NOTE: `max_attempts` is deliberately NOT forbidden. It is an EvidenceRef
    FIELD NAME the model must be able to cite (subscription.max_attempts) -
    schema vocabulary, not a policy bound. An earlier version of this test
    conflated the two and failed on correct code.
    """
    lowered = SYSTEM_PROMPT.lower()
    for concept in ("cooldown", "suppress", "opt-out", "opt out",
                    "send the message", "block the message", "escalate"):
        assert concept not in lowered, f"prompt encodes policy concept {concept!r}"
    for verdict in ("supported", "contradicted", "unverifiable"):
        assert verdict not in lowered, f"prompt names verdict {verdict!r}"
    # no policy BOUND may be baked into the prompt
    for bound in ("86400", "3600", " 4 attempts", "24 hours between"):
        assert bound not in lowered, f"prompt hardcodes policy bound {bound!r}"


def test_prompt_identity_is_stable_and_content_bound():
    assert prompt_identity() == prompt_identity()
    assert prompt_identity().startswith("proposer-v1+")


# --- D. the production schema is authoritative -----------------------------

def test_adapter_returns_a_real_production_proposal():
    """Not a mock object - the actual production type, parsed from raw text."""
    result = ClaudeProposer(transport=FakeTransport(honest_json()))(
        fx.DRAFT, fx.state_final_attempt())
    assert isinstance(result, Proposal)
    assert [c.claim_id for c in result.claims] == ["c1", "c2", "c3"]


@pytest.mark.parametrize("wrapper", [
    "{body}",
    "Here is the result:\n{body}",
    "```json\n{body}\n```",
    "```\n{body}\n```\nHope that helps.",
])
def test_json_is_extracted_from_realistic_response_shapes(wrapper):
    text = wrapper.format(body=honest_json())
    assert len(to_proposal(extract_json_object(text)).claims) == 3


# --- E. invalid output fails closed ----------------------------------------

@pytest.mark.parametrize("text,exc", [
    ("", ProposerMalformedOutput),
    ("I cannot help with that.", ProposerMalformedOutput),
    ("{not json", ProposerMalformedOutput),
    ("[1,2,3]", ProposerMalformedOutput),
])
def test_unparseable_responses_raise_malformed(text, exc):
    with pytest.raises(exc):
        extract_json_object(text)


@pytest.mark.parametrize("payload,label", [
    ({"claims": [{"claim_id": "c1", "kind": "vibes", "span_start": 0,
                  "span_end": 1, "asserted": {"kind": "count", "value": 1}}]},
     "invalid claim kind"),
    ({"claims": [{"claim_id": "c1", "kind": "quantity", "span_start": 0,
                  "span_end": 1}]}, "missing required field"),
    ({"claims": [{"claim_id": "c1", "kind": "quantity", "span_start": 0,
                  "span_end": 1, "asserted": {"kind": "count", "value": 1},
                  "status": "SUPPORTED"}]}, "model issues a verdict"),
    ({"claims": [{"claim_id": "c1", "kind": "quantity", "span_start": 0,
                  "span_end": 1, "asserted": {"kind": "count", "value": 1},
                  "disposition": "SEND"}]}, "model issues a disposition"),
    ({"claims": [{"claim_id": "c1", "kind": "discount_percent", "span_start": 0,
                  "span_end": 1, "asserted": {"kind": "percent", "value": "15.00"},
                  "evidence": {"ref": "database", "query": "SELECT 1"}}]},
     "invalid EvidenceRef variant"),
    ({"claims": [{"claim_id": "c1", "kind": "discount_percent", "span_start": 0,
                  "span_end": 1, "asserted": {"kind": "percent", "value": "15.00"},
                  "evidence": {"ref": "offer", "offer_id": "o1",
                               "field": "../../secret"}}]}, "invented field"),
    ({"claims": [{"claim_id": "c1", "kind": "quantity", "span_start": 9,
                  "span_end": 2, "asserted": {"kind": "count", "value": 1}}]},
     "malformed span"),
    ({"claims": [{"claim_id": "c1", "kind": "quantity", "span_start": 0,
                  "span_end": 1, "asserted": {"kind": "count", "value": True}}]},
     "bool smuggled as count"),
    ({"claims": []}, None),          # legitimately valid - the control case
])
def test_production_schema_rejects_invalid_proposals(payload, label):
    if label is None:
        assert isinstance(to_proposal(payload), Proposal)
        return
    with pytest.raises(ProposerSchemaViolation):
        to_proposal(payload)


def test_schema_violation_never_sends_and_is_labelled_as_a_model_failure(conn):
    bad = json.dumps({"claims": [{"claim_id": "c1", "kind": "vibes",
                                  "span_start": 0, "span_end": 1,
                                  "asserted": {"kind": "count", "value": 1}}]})
    proposer = ClaudeProposer(transport=FakeTransport(bad))
    r = evaluate(fx.DRAFT, REQ, FixtureStateProvider(), proposer, conn, now=NOW)
    assert r["disposition"] is Disposition.ESCALATE
    assert r["proof"]["failure_reason"] == FAILURE_MODEL_SCHEMA


@pytest.mark.parametrize("exc,expected_reason", [
    (ProposerTimeout("deadline"), FAILURE_MODEL_CALL),
    (ProposerTransportFailure("503"), FAILURE_MODEL_CALL),
    (ProposerNotConfigured("no key"), FAILURE_MODEL_CALL),
    (ProposerMalformedOutput("garbage"), FAILURE_MODEL_CALL),
])
def test_infrastructure_failures_never_send(conn, exc, expected_reason):
    proposer = ClaudeProposer(transport=FakeTransport(raises=exc))
    r = evaluate(fx.DRAFT, REQ, FixtureStateProvider(), proposer, conn, now=NOW)
    assert r["disposition"] is Disposition.ESCALATE
    assert r["disposition"] is not Disposition.SEND
    assert r["proof"]["failure_reason"] == expected_reason


# --- F. no silent fallback --------------------------------------------------

def test_failed_adapter_does_not_fall_back_to_the_mock(conn):
    mock_calls = {"n": 0}

    def counting_mock(draft, state):
        mock_calls["n"] += 1
        return fx.honest_proposal()

    import attest.fixtures.scenarios as scen
    original = scen.mock_model
    scen.mock_model = counting_mock
    try:
        proposer = ClaudeProposer(
            transport=FakeTransport(raises=ProposerTransportFailure("503")))
        r = evaluate(fx.DRAFT, REQ, FixtureStateProvider(), proposer, conn, now=NOW)
    finally:
        scen.mock_model = original

    assert r["disposition"] is Disposition.ESCALATE
    assert mock_calls["n"] == 0, "adapter silently fell back to the mock"


# --- G. deterministic verification unchanged -------------------------------

def test_adapter_proposal_flows_through_the_production_verifier(conn):
    proposer = ClaudeProposer(transport=FakeTransport(honest_json()))
    good = evaluate(fx.DRAFT, REQ, FixtureStateProvider(), proposer, conn, now=NOW)
    assert good["disposition"] is Disposition.SEND
    assert {v.status.value for v in good["verdicts"]} == {"SUPPORTED"}

    flipped = evaluate(fx.DRAFT, StateRequest("m", "c2", "first_attempt"),
                       FixtureStateProvider(),
                       ClaudeProposer(transport=FakeTransport(honest_json())),
                       conn, now=NOW)
    assert flipped["disposition"] is Disposition.BLOCK


def test_adapter_forged_evidence_still_escalates(conn):
    forged = json.dumps(fx.forged_evidence_proposal())
    r = evaluate(fx.DRAFT, REQ, FixtureStateProvider(),
                 ClaudeProposer(transport=FakeTransport(forged)), conn, now=NOW)
    assert r["disposition"] is Disposition.ESCALATE


def test_adapter_silent_omission_still_blocks(conn):
    omitted = json.dumps(fx.omitted_deadline_proposal())
    r = evaluate(fx.DRAFT, REQ, FixtureStateProvider(),
                 ClaudeProposer(transport=FakeTransport(omitted)), conn, now=NOW)
    assert r["disposition"] is Disposition.BLOCK
    assert not r["coverage"].passed


def _code_without_docstrings(path: pathlib.Path) -> str:
    """Source with docstrings and comments removed.

    A substring scan over raw text flags a docstring that EXPLAINS the module
    has no verdict logic - which is documentation, not logic. Strip prose and
    test the executable code.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_adapter_contains_no_verdict_logic():
    code = _code_without_docstrings(ROOT / "attest" / "llm" / "propose.py")
    for forbidden in ("SUPPORTED", "CONTRADICTED", "UNVERIFIABLE",
                      "Disposition", "adjudicate", "coverage", "Status"):
        assert forbidden not in code, f"propose.py CODE references {forbidden}"


def test_adapter_imports_no_verdict_machinery():
    """Structural companion to the scan above: the adapter may import the
    production Proposal schema, and nothing that computes a verdict."""
    tree = ast.parse((ROOT / "attest" / "llm" / "propose.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(m.endswith(("rules", "coverage", "pipeline")) for m in imported),         imported


# --- H. gate invariants hold against the REAL adapter ----------------------

def test_gated_requests_never_reach_the_real_adapter(conn):
    from attest.policy.gate import COOLDOWN, SUPPRESSED
    from attest.delivery import SimulatedSender, deliver_and_commit

    db.suppress(conn, "m", "gone", NOW, "test")
    t1 = FakeTransport(honest_json())
    r1 = evaluate(fx.DRAFT, StateRequest("m", "gone", "final_attempt"),
                  FixtureStateProvider(), ClaudeProposer(transport=t1),
                  conn, now=NOW)
    assert r1["gate"].reason_code == SUPPRESSED
    assert t1.calls == 0

    seed = evaluate(fx.DRAFT, StateRequest("m", "recent", "final_attempt"),
                    FixtureStateProvider(), fx.mock_model, conn,
                    now="2026-09-04T09:00:00+00:00")
    deliver_and_commit(conn, seed, SimulatedSender(),
                       "2026-09-04T09:00:00+00:00", "2026-09-04T09:00:00+00:00")
    t2 = FakeTransport(honest_json())
    r2 = evaluate(fx.DRAFT, StateRequest("m", "recent", "final_attempt"),
                  FixtureStateProvider(), ClaudeProposer(transport=t2),
                  conn, now=NOW)
    assert r2["gate"].reason_code == COOLDOWN
    assert t2.calls == 0


def test_attempt_cap_acquires_state_but_never_calls_the_real_adapter(conn):
    import copy

    from attest.state.contract import AuthoritativeState, StateSource

    over = fx.state_final_attempt()
    over["subscription"]["attempt_index"] = 5

    class OverCap:
        name = "overcap"
        calls = 0

        def get_state(self, request):
            OverCap.calls += 1
            return AuthoritativeState(state=copy.deepcopy(over),
                                      source=StateSource.SIMULATED,
                                      provider="overcap", retrieved_at=NOW)

    t = FakeTransport(honest_json())
    r = evaluate(fx.DRAFT, StateRequest("m", "cap", "final_attempt"), OverCap(),
                 ClaudeProposer(transport=t), conn, now=NOW)
    assert r["disposition"] is Disposition.BLOCK
    assert OverCap.calls == 1 and t.calls == 0


# --- I. one acquisition survives -------------------------------------------

def test_adapter_does_not_trigger_a_second_acquisition(conn):
    from attest.state.fixture import RecordingProvider
    p = RecordingProvider(FixtureStateProvider())
    evaluate(fx.DRAFT, REQ, p, ClaudeProposer(transport=FakeTransport(honest_json())),
             conn, now=NOW)
    assert p.calls == 1


# --- J. secrets never reach the proof --------------------------------------

def test_credentials_do_not_enter_the_persisted_proof(conn, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRETVALUE123")
    r = evaluate(fx.DRAFT, REQ, FixtureStateProvider(),
                 ClaudeProposer(transport=FakeTransport(honest_json())),
                 conn, now=NOW)
    row = db.get_proof(conn, r["proof"]["proof_id"])
    blob = " ".join(str(row[k]) for k in row.keys())
    assert "SECRETVALUE123" not in blob
    assert "sk-ant" not in blob


# --- K. request shape is testable without credentials ----------------------

def test_request_params_omit_sampling_and_thinking_budget(monkeypatch):
    """claude-opus-5 rejects temperature/top_p/top_k and budget_tokens with a
    400. This is why killtest/run_arms.py stopped sending temperature."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from attest.llm.client import AnthropicTransport
    params = AnthropicTransport().request_params("sys", "usr")
    assert params["model"] == "claude-opus-5"
    for banned in ("temperature", "top_p", "top_k", "thinking"):
        assert banned not in params, f"{banned} would 400 on this model"
    assert params["output_config"] == {"effort": "medium"}
    assert params["messages"][0]["role"] == "user"


def test_ordinary_suite_opens_no_sockets(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("adapter opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    result = ClaudeProposer(transport=FakeTransport(honest_json()))(
        fx.DRAFT, fx.state_final_attempt())
    assert isinstance(result, Proposal)
