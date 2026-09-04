"""The four demo beats, as executable invariants.

A change that breaks a beat fails CI. The demo IS the deliverable, so it gets
test coverage like anything else.
"""

import json
import socket
import sqlite3

import pytest

from pramaan.core.pipeline import evaluate
from pramaan.core.verify.schema import Disposition, Status
from pramaan.fixtures import scenarios as fx
from pramaan.state.contract import StateRequest
from pramaan.state.fixture import FixtureStateProvider
from pramaan.storage import db
from recheck import recheck_one

PROVIDER = FixtureStateProvider()
FINAL = StateRequest("m_demo", "cus_demo", "final_attempt")
FIRST = StateRequest("m_demo", "cus_demo", "first_attempt")


@pytest.fixture()
def conn(tmp_path):
    return db.connect(tmp_path / "test.db")


def _status(result, claim_id):
    return next(v.status for v in result["verdicts"] if v.claim_id == claim_id)


# --------------------------------------------------------------------------
# BEAT A - state flip
# --------------------------------------------------------------------------

def test_beat_a_state_flip(conn):
    """Same message. One field changed. The verdict flips."""
    a = evaluate(fx.DRAFT, FINAL, PROVIDER, fx.mock_model, conn)
    b = evaluate(fx.DRAFT, FIRST, PROVIDER, fx.mock_model, conn)

    assert a["disposition"] is Disposition.SEND
    assert b["disposition"] is Disposition.BLOCK
    assert _status(a, "c1") is Status.SUPPORTED
    assert _status(b, "c1") is Status.CONTRADICTED
    # the message really was identical
    assert a["proof"]["message_hash"] == b["proof"]["message_hash"]
    # ...and the snapshots really did differ
    assert a["proof"]["snapshot_hash"] != b["proof"]["snapshot_hash"]


def test_beat_a_snapshots_differ_in_exactly_one_field():
    """Guards the demo's honesty: a two-variable change would prove nothing."""
    a, b = fx.state_final_attempt(), fx.state_first_attempt()

    def flat(d, prefix=""):
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out.update(flat(v, f"{prefix}{k}."))
            elif isinstance(v, list):
                out[f"{prefix}{k}"] = json.dumps(v, sort_keys=True)
            else:
                out[f"{prefix}{k}"] = v
        return out

    fa, fb = flat(a), flat(b)
    diff = [k for k in fa if fa[k] != fb[k]]
    assert diff == ["subscription.attempt_index"], f"expected 1 field, got {diff}"


# --------------------------------------------------------------------------
# BEAT B - forged evidence
# --------------------------------------------------------------------------

def test_beat_b_forged_evidence_cannot_be_supported(conn):
    """A well-formed but nonexistent offer id must not become SUPPORTED."""
    r = evaluate(fx.DRAFT, FINAL, PROVIDER,
                 lambda d, s: fx.forged_evidence_proposal(), conn)

    assert _status(r, "c2") is Status.MALFORMED
    assert _status(r, "c2") is not Status.SUPPORTED
    reason = next(v.reason_code for v in r["verdicts"] if v.claim_id == "c2")
    assert reason == "EVIDENCE_ABSENT"
    assert r["disposition"] is Disposition.ESCALATE


def test_beat_b_forged_finding_cannot_satisfy_coverage(conn):
    """A rejected citation must not cover its span either."""
    r = evaluate(fx.DRAFT, FINAL, PROVIDER,
                 lambda d, s: fx.forged_evidence_proposal(), conn)
    covered = {s.text: s.covered_by for s in r["coverage"].spans}
    assert covered["15%"] is None, "a malformed claim covered its own span"


# --------------------------------------------------------------------------
# BEAT C - silent omission
# --------------------------------------------------------------------------

def test_beat_c_silent_omission_blocks(conn):
    """The model drops one claim. Coverage catches it independently."""
    r = evaluate(fx.DRAFT, FINAL, PROVIDER,
                 lambda d, s: fx.omitted_deadline_proposal(), conn)

    assert not r["coverage"].passed
    uncovered = [s.text for s in r["coverage"].uncovered]
    assert "24 hours" in uncovered
    assert r["disposition"] is Disposition.BLOCK
    # every surviving claim was fine - only the omission blocked the send
    assert all(v.status is Status.SUPPORTED for v in r["verdicts"])


# --------------------------------------------------------------------------
# BEAT D - offline replay
# --------------------------------------------------------------------------

def test_beat_d_replay_with_no_network(conn, monkeypatch):
    """Recompute the decision with sockets disabled."""
    r = evaluate(fx.DRAFT, FINAL, PROVIDER, fx.mock_model, conn)
    pid = r["proof"]["proof_id"]

    def no_network(*a, **k):
        raise AssertionError("replay attempted network I/O")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    ok, problems = recheck_one(conn, pid)
    assert ok, problems


def test_beat_d_replay_detects_tampering(tmp_path):
    """Corrupt the stored snapshot; replay must fail."""
    path = tmp_path / "tamper.db"
    conn = db.connect(path)
    r = evaluate(fx.DRAFT, FINAL, PROVIDER, fx.mock_model, conn)
    pid = r["proof"]["proof_id"]
    assert recheck_one(conn, pid)[0]

    # triggers block the honest path...
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE snapshot SET canonical = '{}'")

    # ...so simulate an attacker with file access, which we do NOT defend against
    conn.close()
    raw = db.connect(path)
    raw.execute("DROP TRIGGER snapshot_no_update")
    tampered = json.loads(raw.execute(
        "SELECT canonical FROM snapshot").fetchone()["canonical"])
    tampered["subscription"]["attempt_index"] = 1
    raw.execute("UPDATE snapshot SET canonical = ?",
                (json.dumps(tampered, sort_keys=True, separators=(",", ":")),))
    raw.commit()

    ok, problems = recheck_one(raw, pid)
    assert not ok
    assert any("snapshot hash mismatch" in p for p in problems), problems


def test_beat_d_replay_is_deterministic(conn):
    """Same proof, twenty rechecks, identical result."""
    r = evaluate(fx.DRAFT, FINAL, PROVIDER, fx.mock_model, conn)
    pid = r["proof"]["proof_id"]
    assert {recheck_one(conn, pid)[0] for _ in range(20)} == {True}
