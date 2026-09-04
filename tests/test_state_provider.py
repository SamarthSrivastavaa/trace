"""The authoritative-state boundary.

Central invariant under test:

    ONE evaluation performs exactly ONE state acquisition, and that state is
    the only state used for canonicalisation, evidence resolution, coverage
    and the proof.

Plus the safety property that outranks everything: state acquisition failure
can never become SEND.
"""

import socket
import subprocess
import sys

import pytest

from pramaan.core.pipeline import (FAILURE_MODEL_CALL, FAILURE_MODEL_SCHEMA,
                                   FAILURE_STATE_ACQUISITION, evaluate)
from pramaan.core.verify.canonical import snapshot_hash
from pramaan.core.verify.schema import Disposition
from pramaan.fixtures import scenarios as fx
from pramaan.state.contract import (AuthoritativeState, StateRequest,
                                    StateSource, require_primitive_state)
from pramaan.state.errors import (MalformedProviderState, ProviderFailure,
                                  ProviderNotConfigured, StateUnavailable)
from pramaan.state.fixture import (FixtureStateProvider, RecordingProvider,
                                   SequenceProvider)
from pramaan.storage import db

REQ = StateRequest("m_test", "cus_test", "final_attempt")


@pytest.fixture()
def conn(tmp_path):
    return db.connect(tmp_path / "t.db")


# --- provider contract ------------------------------------------------------

def test_fixture_state_is_primitive_only():
    got = FixtureStateProvider().get_state(REQ)
    require_primitive_state(got.state)          # must not raise


def test_fixture_marks_source_simulated():
    got = FixtureStateProvider().get_state(REQ)
    assert got.source is StateSource.SIMULATED
    assert got.provider == "fixture"


def test_missing_fixture_raises_typed_error():
    """Missing state is an ACQUISITION failure, never UNVERIFIABLE and never {}."""
    with pytest.raises(StateUnavailable):
        FixtureStateProvider().get_state(StateRequest("m", "c", "no_such"))


def test_caller_mutation_cannot_affect_future_reads():
    p = FixtureStateProvider()
    first = p.get_state(REQ).state
    first["subscription"]["attempt_index"] = 999
    first["offers"].clear()
    second = p.get_state(REQ).state
    assert second["subscription"]["attempt_index"] == 4
    assert len(second["offers"]) == 1


def test_non_primitive_state_is_rejected_at_the_boundary():
    class Evil:
        def __eq__(self, other):
            raise AssertionError("reached a comparison")

    with pytest.raises(MalformedProviderState):
        AuthoritativeState(state={"x": Evil()}, source=StateSource.SIMULATED,
                           provider="bad", retrieved_at="2026-01-01T00:00:00+00:00")


def test_float_is_rejected_in_authoritative_state():
    with pytest.raises(MalformedProviderState):
        AuthoritativeState(state={"amount": 1.5}, source=StateSource.SIMULATED,
                           provider="bad", retrieved_at="2026-01-01T00:00:00+00:00")


def test_non_string_key_is_rejected():
    with pytest.raises(MalformedProviderState):
        require_primitive_state({1: "x"})


# --- single acquisition -----------------------------------------------------

def test_provider_called_exactly_once_per_evaluation(conn):
    p = RecordingProvider(FixtureStateProvider())
    evaluate(fx.DRAFT, REQ, p, fx.mock_model, conn)
    assert p.calls == 1


def test_evidence_resolution_never_refetches(conn):
    """If the pipeline fetched twice, the SECOND state would silently be used.

    SequenceProvider hands back final_attempt then first_attempt. The proof
    must reflect only the first: SEND, not BLOCK.
    """
    p = SequenceProvider([fx.state_final_attempt(), fx.state_first_attempt()])
    r = evaluate(fx.DRAFT, REQ, p, fx.mock_model, conn)
    assert p.calls == 1
    assert r["disposition"] is Disposition.SEND
    assert r["proof"]["snapshot_hash"] == snapshot_hash(fx.state_final_attempt())
    assert r["proof"]["snapshot_hash"] != snapshot_hash(fx.state_first_attempt())


def test_snapshot_hash_is_the_hash_of_the_acquired_state(conn):
    p = FixtureStateProvider()
    acquired = p.get_state(REQ)
    r = evaluate(fx.DRAFT, REQ, p, fx.mock_model, conn)
    assert r["proof"]["snapshot_hash"] == snapshot_hash(acquired.state)


# --- acquisition failure can never SEND -------------------------------------

class _Unavailable:
    name = "unavailable"

    def get_state(self, request):
        raise StateUnavailable("no state for this merchant")


class _Broken:
    name = "broken"

    def get_state(self, request):
        raise ProviderFailure("upstream 503")


class _Malformed:
    name = "malformed"

    def get_state(self, request):
        return AuthoritativeState(state={"x": object()},
                                  source=StateSource.SIMULATED,
                                  provider="malformed",
                                  retrieved_at="2026-01-01T00:00:00+00:00")


@pytest.mark.parametrize("provider", [_Unavailable(), _Broken()],
                         ids=["state_unavailable", "provider_failure"])
def test_acquisition_failure_never_sends(provider, conn):
    r = evaluate(fx.DRAFT, REQ, provider, fx.mock_model, conn)
    assert r["disposition"] is Disposition.ESCALATE
    assert r["disposition"] is not Disposition.SEND
    assert r["proof"]["failure_reason"] == FAILURE_STATE_ACQUISITION


def test_malformed_provider_state_never_sends(conn):
    r = evaluate(fx.DRAFT, REQ, _Malformed(), fx.mock_model, conn)
    assert r["disposition"] is Disposition.ESCALATE
    assert r["proof"]["failure_reason"] == FAILURE_STATE_ACQUISITION


def test_state_failure_is_distinguishable_from_model_failure(conn):
    """An outage must not be recorded as model unreliability."""
    state_fail = evaluate(fx.DRAFT, REQ, _Broken(), fx.mock_model, conn)

    def exploding_model(draft, state):
        raise TimeoutError("model timed out")

    model_fail = evaluate(fx.DRAFT, REQ, FixtureStateProvider(),
                          exploding_model, conn)

    def bad_schema_model(draft, state):
        return {"claims": [{"claim_id": "c1", "kind": "vibes",
                            "span_start": 0, "span_end": 1,
                            "asserted": {"kind": "count", "value": 1}}]}

    schema_fail = evaluate(fx.DRAFT, REQ, FixtureStateProvider(),
                           bad_schema_model, conn)

    assert state_fail["proof"]["failure_reason"] == FAILURE_STATE_ACQUISITION
    assert model_fail["proof"]["failure_reason"] == FAILURE_MODEL_CALL
    assert schema_fail["proof"]["failure_reason"] == FAILURE_MODEL_SCHEMA
    for r in (state_fail, model_fail, schema_fail):
        assert r["disposition"] is Disposition.ESCALATE


def test_acquisition_failure_records_no_snapshot(conn):
    """Nothing was acquired, so nothing may be presented as a snapshot."""
    r = evaluate(fx.DRAFT, REQ, _Unavailable(), fx.mock_model, conn)
    assert r["proof"]["snapshot_hash"] is None
    assert r["proof"]["state_source"] == ""


# --- provenance -------------------------------------------------------------

def test_fixture_evaluation_proof_says_simulated(conn):
    r = evaluate(fx.DRAFT, REQ, FixtureStateProvider(), fx.mock_model, conn)
    assert r["proof"]["state_source"] == "SIMULATED"
    row = db.get_proof(conn, r["proof"]["proof_id"])
    assert row["state_source"] == "SIMULATED"
    assert row["state_provider"] == "fixture"


def test_provenance_cannot_be_rewritten_by_ordinary_sql(conn):
    import sqlite3
    r = evaluate(fx.DRAFT, REQ, FixtureStateProvider(), fx.mock_model, conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE proof SET state_source='LIVE' WHERE proof_id=?",
                     (r["proof"]["proof_id"],))
    assert db.get_proof(conn, r["proof"]["proof_id"])["state_source"] == "SIMULATED"


# --- replay independence ----------------------------------------------------

def test_replay_does_not_invoke_the_provider(conn, monkeypatch):
    from recheck import recheck_one
    p = RecordingProvider(FixtureStateProvider())
    r = evaluate(fx.DRAFT, REQ, p, fx.mock_model, conn)
    calls_after_eval = p.calls

    def _blocked(*a, **k):
        raise AssertionError("replay attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    ok, problems = recheck_one(conn, r["proof"]["proof_id"])
    assert ok, problems
    assert p.calls == calls_after_eval == 1


def test_recheck_module_does_not_import_a_provider():
    """Replay must not depend on state acquisition, even transitively."""
    import ast
    import pathlib
    src = pathlib.Path("recheck.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("state.fixture" in m or "integrations" in m for m in imported), \
        f"recheck imports a provider: {imported}"


# --- razorpay boundary ------------------------------------------------------

def test_importing_razorpay_provider_needs_no_credentials(monkeypatch):
    """Import must not read or require credentials. Network-at-import is
    covered separately by the subprocess test, because monkeypatching cannot
    un-import an already-loaded module."""
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    import importlib
    mod = importlib.import_module("pramaan.integrations.razorpay.provider")
    assert mod.API_BASE.startswith("https://")


def test_razorpay_provider_refuses_without_config(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    from pramaan.integrations.razorpay.provider import RazorpayStateProvider
    with pytest.raises(ProviderNotConfigured):
        RazorpayStateProvider()


def test_razorpay_provider_refuses_live_keys(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_abc123")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    from pramaan.integrations.razorpay.provider import RazorpayStateProvider
    with pytest.raises(ProviderNotConfigured):
        RazorpayStateProvider()


def test_razorpay_provider_does_not_pretend_to_be_integrated(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc123")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    from pramaan.integrations.razorpay.provider import RazorpayStateProvider
    p = RazorpayStateProvider()
    assert p.unresolved_mappings(), "skeleton claims a complete mapping"
    with pytest.raises(ProviderFailure):
        p.get_state(REQ)


def test_razorpay_mapper_rejects_non_primitives():
    from pramaan.integrations.razorpay.provider import RazorpayStateProvider
    with pytest.raises(MalformedProviderState):
        RazorpayStateProvider.to_primitive_state({"amount": 1.5})


# --- offline guarantees -----------------------------------------------------

def test_full_offline_import_makes_no_network_calls():
    """Subprocess so the guard covers import time, not just call time.

    Block connect() rather than replacing socket.socket. ssl.py does
    `class SSLSocket(socket)` at import, so socket.socket must remain a class -
    replacing it with a function made this test fail on the stdlib rather than
    on our code. Blocking connect is also the stricter check: it catches an
    actual dial-out, not merely object construction.
    """
    code = (
        "import socket\n"
        "def _blocked(*a, **k):\n"
        "    raise AssertionError('network I/O at import time')\n"
        "socket.socket.connect = _blocked\n"
        "socket.socket.connect_ex = _blocked\n"
        "socket.create_connection = _blocked\n"
        "import pramaan.core.pipeline, pramaan.state.contract, "
        "pramaan.state.fixture, pramaan.integrations.razorpay.provider, recheck\n"
        "print('ok')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=90)
    assert out.returncode == 0, out.stderr
    assert "ok" in out.stdout
