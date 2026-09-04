"""The pre-model gate.

THE HARD INVARIANT under test:

    For every evaluation the gate denies:
        provider.calls == 0
        propose.calls  == 0

Proven by recording the actual call SEQUENCE, not by inference. A test that
only asserted "propose was not called" could pass because the pipeline crashed
before reaching either component, so every denial test is paired with an
allowed path asserting provider==1 and propose==1.
"""

import ast
import copy
import json
import pathlib
import socket
import sqlite3

import pytest

from pramaan.core.pipeline import build_gate_context, evaluate
from pramaan.core.verify.schema import Disposition
from pramaan.fixtures import scenarios as fx
from pramaan.policy.gate import (ATTEMPT_CAP, BAD_TIMESTAMP, COOLDOWN,
                                 SUPPRESSED, evaluate_post_state,
                                 evaluate_pre_state)
from pramaan.policy.loader import (load_default_policy, parse_policy,
                                   policy_hash)
from pramaan.policy.schema import GateContext, GateDecision
from pramaan.state.contract import StateRequest
from pramaan.state.fixture import FixtureStateProvider, SequenceProvider
from pramaan.storage import db

NOW = "2026-09-04T10:00:00+00:00"
POLICY = load_default_policy()
RAW = json.loads(
    (pathlib.Path("pramaan/policy/default_policy.json")).read_text(encoding="utf-8"))


class CallLog:
    """Records the exact order in which collaborators were invoked."""

    def __init__(self):
        self.sequence: list[str] = []


class SpyProvider:
    name = "spy"

    def __init__(self, log, inner=None):
        self._log, self._inner = log, inner or FixtureStateProvider()
        self.calls = 0

    def get_state(self, request):
        self.calls += 1
        self._log.sequence.append("provider")
        return self._inner.get_state(request)


class SpyPropose:
    def __init__(self, log, proposal=None):
        self._log, self._proposal = log, proposal
        self.calls = 0
        self.received: list[tuple] = []

    def __call__(self, draft, state):
        self.calls += 1
        self._log.sequence.append("propose")
        self.received.append((draft, state))
        return fx.mock_model(draft, state, self._proposal)


@pytest.fixture()
def conn(tmp_path):
    return db.connect(tmp_path / "gate.db")


def ctx(**over):
    base = dict(merchant_id="m", customer_id="c", now=NOW,
                suppressed=False, last_send_at=None)
    base.update(over)
    return GateContext(**base)


# --- pure gate: suppression -------------------------------------------------

def test_suppressed_context_denies():
    r = evaluate_pre_state(ctx(suppressed=True), POLICY)
    assert r.decision is GateDecision.DENY
    assert r.reason_code == SUPPRESSED
    assert r.rule_id == "opt_out"


def test_unsuppressed_context_allows():
    assert evaluate_pre_state(ctx(), POLICY).allowed


# --- pure gate: cooldown boundaries (injected time only) --------------------

@pytest.mark.parametrize("last,expect_allowed,label", [
    ("2026-09-03T10:00:01+00:00", False, "1s inside the window"),
    ("2026-09-03T10:00:00+00:00", True, "exactly at expiry"),
    ("2026-09-03T09:59:59+00:00", True, "1s past expiry"),
    ("2026-09-04T10:00:00+00:00", False, "sent this instant"),
])
def test_cooldown_boundaries(last, expect_allowed, label):
    """86400s window. elapsed < window blocks; elapsed == window allows."""
    r = evaluate_pre_state(ctx(last_send_at=last), POLICY)
    assert r.allowed is expect_allowed, f"{label}: {r.reason_code} {r.detail}"
    if not expect_allowed:
        assert r.reason_code == COOLDOWN


def test_never_contacted_passes_cooldown():
    assert evaluate_pre_state(ctx(last_send_at=None), POLICY).allowed


def test_unparseable_timestamp_fails_closed():
    """A naive timestamp must not read as 'cooldown elapsed'."""
    r = evaluate_pre_state(ctx(last_send_at="2026-09-03T10:00:00"), POLICY)
    assert not r.allowed
    assert r.reason_code == BAD_TIMESTAMP


def test_gate_never_reads_a_clock():
    """Same context, same answer, regardless of wall time."""
    c = ctx(last_send_at="2026-09-04T09:00:00+00:00")
    assert len({evaluate_pre_state(c, POLICY).model_dump_json()
                for _ in range(20)}) == 1


# --- pure gate: attempt limit (post-state) ---------------------------------

@pytest.mark.parametrize("attempt,expect_allowed", [
    (3, True), (4, True), (5, False)])
def test_attempt_limit_boundaries(attempt, expect_allowed):
    """max_attempts=4: attempt 4 of 4 allowed, attempt 5 blocked."""
    state = fx.state_final_attempt()
    state["subscription"]["attempt_index"] = attempt
    r = evaluate_post_state(state, POLICY)
    assert r.allowed is expect_allowed
    if not expect_allowed:
        assert r.reason_code == ATTEMPT_CAP


def test_attempt_limit_skips_states_without_a_subscription():
    assert evaluate_post_state({"now": NOW}, POLICY).allowed


def test_attempt_limit_rejects_non_integer_attempt():
    state = fx.state_final_attempt()
    state["subscription"]["attempt_index"] = True
    assert not evaluate_post_state(state, POLICY).allowed


# --- policy is DATA: behaviour follows the document ------------------------

def test_disabling_a_rule_in_policy_data_changes_behaviour():
    doc = copy.deepcopy(RAW)
    doc["rules"][0]["enabled"] = False              # opt_out off
    relaxed = parse_policy(doc)
    assert not evaluate_pre_state(ctx(suppressed=True), POLICY).allowed
    assert evaluate_pre_state(ctx(suppressed=True), relaxed).allowed


def test_changing_the_window_in_policy_data_changes_behaviour():
    doc = copy.deepcopy(RAW)
    doc["rules"][1]["min_seconds_between_sends"] = 60
    short = parse_policy(doc)
    c = ctx(last_send_at="2026-09-04T09:00:00+00:00")   # 1 hour ago
    assert not evaluate_pre_state(c, POLICY).allowed     # 24h window blocks
    assert evaluate_pre_state(c, short).allowed          # 60s window allows


# --- pipeline ordering and zero-leakage ------------------------------------

def test_allowed_request_calls_provider_then_propose_exactly_once(conn):
    """The paired positive case. Without this, the denial tests below could
    pass simply because nothing was wired up."""
    log = CallLog()
    prov, prop = SpyProvider(log), SpyPropose(log)
    r = evaluate(fx.DRAFT, StateRequest("m", "ok", "final_attempt"),
                 prov, prop, conn, policy=POLICY, now=NOW)
    assert r["disposition"] is Disposition.SEND
    assert (prov.calls, prop.calls) == (1, 1)
    assert log.sequence == ["provider", "propose"]


def test_suppressed_request_touches_neither_provider_nor_model(conn):
    log = CallLog()
    prov, prop = SpyProvider(log), SpyPropose(log)
    db.suppress(conn, "m", "gone", NOW, "test")
    r = evaluate(fx.DRAFT, StateRequest("m", "gone", "final_attempt"),
                 prov, prop, conn, policy=POLICY, now=NOW)

    assert r["disposition"] is Disposition.BLOCK
    assert r["gate"].reason_code == SUPPRESSED
    assert (prov.calls, prop.calls) == (0, 0)
    assert log.sequence == []
    assert r["proof"]["snapshot_hash"] is None      # no state was fabricated


def test_cooldown_blocked_request_touches_neither(conn):
    """Cooldown is seeded through the REAL lifecycle - evaluate, then commit a
    successful send. Phase 6 removed the raw record_send() backdoor, so this
    test now exercises the production path rather than a fixture insert."""
    from pramaan.delivery import SimulatedSender, deliver_and_commit
    log = CallLog()
    seed = evaluate(fx.DRAFT, StateRequest("m", "recent", "final_attempt"),
                    FixtureStateProvider(), fx.mock_model, conn,
                    policy=POLICY, now="2026-09-04T09:00:00+00:00")
    assert seed["disposition"] is Disposition.SEND
    _, status = deliver_and_commit(conn, seed, SimulatedSender(),
                                   "2026-09-04T09:00:00+00:00",
                                   "2026-09-04T09:00:00+00:00")
    assert status == "created"

    prov, prop = SpyProvider(log), SpyPropose(log)
    r = evaluate(fx.DRAFT, StateRequest("m", "recent", "final_attempt"),
                 prov, prop, conn, policy=POLICY, now=NOW)

    assert r["disposition"] is Disposition.BLOCK
    assert r["gate"].reason_code == COOLDOWN
    assert (prov.calls, prop.calls) == (0, 0)
    assert log.sequence == []


def test_attempt_cap_acquires_state_but_never_calls_the_model(conn):
    """attempt_index is authoritative state, so this rule CANNOT be pre-state.
    It still runs before the model, so a capped request costs no model call."""
    log = CallLog()
    over = fx.state_final_attempt()
    over["subscription"]["attempt_index"] = 5

    class OverCap:
        name = "overcap"

        def get_state(self, request):
            from pramaan.state.contract import (AuthoritativeState, StateSource)
            log.sequence.append("provider")
            self.calls = getattr(self, "calls", 0) + 1
            return AuthoritativeState(state=copy.deepcopy(over),
                                      source=StateSource.SIMULATED,
                                      provider="overcap", retrieved_at=NOW)

    prov, prop = OverCap(), SpyPropose(log)
    r = evaluate(fx.DRAFT, StateRequest("m", "capped", "final_attempt"),
                 prov, prop, conn, policy=POLICY, now=NOW)

    assert r["disposition"] is Disposition.BLOCK
    assert r["gate"].reason_code == ATTEMPT_CAP
    assert prop.calls == 0
    assert log.sequence == ["provider"]           # acquired, never proposed


def test_propose_receives_only_draft_and_state(conn):
    """The model must not be handed gate or storage internals."""
    log = CallLog()
    prop = SpyPropose(log)
    evaluate(fx.DRAFT, StateRequest("m", "ok2", "final_attempt"),
             SpyProvider(log), prop, conn, policy=POLICY, now=NOW)
    draft, state = prop.received[0]
    assert draft == fx.DRAFT
    assert set(state) <= {"now", "offers", "subscription", "customer",
                          "payment", "cart", "inventory"}
    assert "suppressed" not in state and "last_send_at" not in state


def test_no_refetch_invariant_still_holds(conn):
    """Phase 2 invariant must survive the gate insertion."""
    p = SequenceProvider([fx.state_final_attempt(), fx.state_first_attempt()])
    r = evaluate(fx.DRAFT, StateRequest("m", "seq", "final_attempt"),
                 p, fx.mock_model, conn, policy=POLICY, now=NOW)
    assert p.calls == 1
    assert r["disposition"] is Disposition.SEND


def test_state_acquisition_failure_never_reaches_the_model(conn):
    from pramaan.state.errors import ProviderFailure
    log = CallLog()

    class Broken:
        name = "broken"
        calls = 0

        def get_state(self, request):
            log.sequence.append("provider")
            raise ProviderFailure("503")

    prop = SpyPropose(log)
    r = evaluate(fx.DRAFT, StateRequest("m", "brk", "final_attempt"),
                 Broken(), prop, conn, policy=POLICY, now=NOW)
    assert r["disposition"] is Disposition.ESCALATE
    assert prop.calls == 0
    assert log.sequence == ["provider"]


def test_gate_denial_is_distinguishable_from_model_and_provider_failure(conn):
    from pramaan.state.errors import ProviderFailure

    class Broken:
        name = "broken"

        def get_state(self, request):
            raise ProviderFailure("503")

    def boom(draft, state):
        raise TimeoutError("model timeout")

    db.suppress(conn, "m", "sup", NOW)
    gated = evaluate(fx.DRAFT, StateRequest("m", "sup", "final_attempt"),
                     FixtureStateProvider(), fx.mock_model, conn,
                     policy=POLICY, now=NOW)
    provider_fail = evaluate(fx.DRAFT, StateRequest("m", "p", "final_attempt"),
                             Broken(), fx.mock_model, conn, policy=POLICY, now=NOW)
    model_fail = evaluate(fx.DRAFT, StateRequest("m", "q", "final_attempt"),
                          FixtureStateProvider(), boom, conn,
                          policy=POLICY, now=NOW)

    assert gated["disposition"] is Disposition.BLOCK
    assert gated["proof"]["gate_reason"] == SUPPRESSED
    assert gated["proof"]["failure_reason"] == ""
    assert provider_fail["proof"]["failure_reason"] == "STATE_ACQUISITION_FAILED"
    assert model_fail["proof"]["failure_reason"] == "MODEL_CALL_FAILED"


# --- proof carries policy identity -----------------------------------------

def test_proof_records_the_actual_policy_identity(conn):
    r = evaluate(fx.DRAFT, StateRequest("m", "pid", "final_attempt"),
                 FixtureStateProvider(), fx.mock_model, conn,
                 policy=POLICY, now=NOW)
    assert r["proof"]["policy_hash"] == policy_hash(POLICY)
    row = db.get_proof(conn, r["proof"]["proof_id"])
    assert row["policy_hash"] == policy_hash(POLICY)
    assert row["policy_canonical"]
    assert row["gate_decision"] == "ALLOW"


def test_policy_identity_in_proof_cannot_be_rewritten(conn):
    r = evaluate(fx.DRAFT, StateRequest("m", "imm", "final_attempt"),
                 FixtureStateProvider(), fx.mock_model, conn,
                 policy=POLICY, now=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE proof SET policy_hash='x' WHERE proof_id=?",
                     (r["proof"]["proof_id"],))


# --- replay -----------------------------------------------------------------

def test_replay_reruns_the_gate_from_the_recorded_policy(conn, monkeypatch):
    from recheck import recheck_one
    db.suppress(conn, "m", "rep", NOW)
    r = evaluate(fx.DRAFT, StateRequest("m", "rep", "final_attempt"),
                 FixtureStateProvider(), fx.mock_model, conn,
                 policy=POLICY, now=NOW)

    def blocked(*a, **k):
        raise AssertionError("replay attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    ok, problems = recheck_one(conn, r["proof"]["proof_id"])
    assert ok, problems


def test_replay_detects_policy_drift(conn):
    """A historical proof must not silently re-adjudicate under new policy."""
    doc = copy.deepcopy(RAW)
    doc["rules"][1]["min_seconds_between_sends"] = 60
    old_policy = parse_policy(doc)

    from recheck import recheck_one
    r = evaluate(fx.DRAFT, StateRequest("m", "drift", "final_attempt"),
                 FixtureStateProvider(), fx.mock_model, conn,
                 policy=old_policy, now=NOW)

    ok, problems = recheck_one(conn, r["proof"]["proof_id"])
    assert not ok
    assert any("policy drift" in p for p in problems), problems

    ok2, problems2 = recheck_one(conn, r["proof"]["proof_id"],
                                 allow_policy_drift=True)
    assert ok2, problems2


def test_replay_detects_tampered_policy_artifact(tmp_path):
    from recheck import recheck_one
    path = tmp_path / "t.db"
    c = db.connect(path)
    r = evaluate(fx.DRAFT, StateRequest("m", "tam", "final_attempt"),
                 FixtureStateProvider(), fx.mock_model, c,
                 policy=POLICY, now=NOW)
    pid = r["proof"]["proof_id"]
    assert recheck_one(c, pid)[0]

    c.close()
    raw = db.connect(path)
    raw.execute("DROP TRIGGER proof_no_update")
    doc = json.loads(raw.execute(
        "SELECT policy_canonical FROM proof").fetchone()["policy_canonical"])
    doc["rules"][1]["min_seconds_between_sends"] = 1
    raw.execute("UPDATE proof SET policy_canonical=? WHERE proof_id=?",
                (json.dumps(doc, sort_keys=True, separators=(",", ":")), pid))
    raw.commit()

    ok, problems = recheck_one(raw, pid, allow_policy_drift=True)
    assert not ok
    assert any("policy artifact mismatch" in p for p in problems), problems


# --- boundary purity --------------------------------------------------------

@pytest.mark.parametrize("mod", ["pramaan/policy/gate.py",
                                 "pramaan/policy/schema.py"])
def test_policy_decision_modules_are_pure(mod):
    tree = ast.parse(pathlib.Path(mod).read_text(encoding="utf-8"))
    banned = {"socket", "sqlite3", "requests", "httpx", "anthropic", "os",
              "importlib", "subprocess", "urllib", "random"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned, f"{mod}: {a.name}"
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert (node.module or "").split(".")[0] not in banned, \
                f"{mod}: {node.module}"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"eval", "exec", "compile", "__import__"}, \
                f"{mod}: dynamic execution"


def test_gate_module_reads_no_clock():
    src = pathlib.Path("pramaan/policy/gate.py").read_text(encoding="utf-8")
    assert "datetime.now" not in src and "time.time" not in src


def test_gate_decides_with_database_and_network_disabled(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("pure gate attempted I/O")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(sqlite3, "connect", boom)
    assert evaluate_pre_state(ctx(suppressed=True), POLICY).reason_code == SUPPRESSED
    assert evaluate_post_state(fx.state_final_attempt(), POLICY).allowed


def test_build_gate_context_without_a_connection_is_permissive_but_explicit():
    """No storage -> no local facts. Must not silently invent suppression."""
    c = build_gate_context(StateRequest("m", "c", "final_attempt"), NOW, None)
    assert c.suppressed is False and c.last_send_at is None
