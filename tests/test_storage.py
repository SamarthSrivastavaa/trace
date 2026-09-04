"""Storage integrity, send-commit semantics, and the cooldown lifecycle.

The objective this file defends:

    A SEND decision does not consume cooldown.
    A recorded successful send does.

Every invariant is attacked with raw SQL as well as through the API, because
an application-layer `if` is not an invariant.
"""

import sqlite3

import pytest

from pramaan.core.pipeline import evaluate
from pramaan.core.verify.schema import Disposition
from pramaan.delivery import (SimulatedSender, commit_successful_send,
                              deliver_and_commit)
from pramaan.fixtures import scenarios as fx
from pramaan.policy.gate import COOLDOWN
from pramaan.policy.loader import load_default_policy
from pramaan.state.contract import StateRequest
from pramaan.state.fixture import FixtureStateProvider
from pramaan.storage import db
from recheck import check_send_log

POLICY = load_default_policy()
T0 = "2026-09-04T10:00:00+00:00"
T_PLUS_1H = "2026-09-04T11:00:00+00:00"
T_PLUS_24H = "2026-09-05T10:00:00+00:00"


@pytest.fixture()
def conn(tmp_path):
    return db.connect(tmp_path / "s.db")


def approve(conn, customer="cus", now=T0, scenario="final_attempt"):
    r = evaluate(fx.DRAFT, StateRequest("m", customer, scenario),
                 FixtureStateProvider(), fx.mock_model, conn,
                 policy=POLICY, now=now)
    return r


def blocked(conn, customer="cus_b"):
    return evaluate(fx.DRAFT, StateRequest("m", customer, "first_attempt"),
                    FixtureStateProvider(), fx.mock_model, conn,
                    policy=POLICY, now=T0)


def escalated(conn, customer="cus_e"):
    return evaluate(fx.DRAFT, StateRequest("m", customer, "final_attempt"),
                    FixtureStateProvider(),
                    lambda d, s: fx.forged_evidence_proposal(), conn,
                    policy=POLICY, now=T0)


# --- FK enforcement (empirical, not a pragma read-back) --------------------

def test_foreign_keys_are_actually_enforced(conn):
    assert db.foreign_keys_enforced(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO proof(proof_id,snapshot_hash,policy_version,"
            "normalised_message,message_hash,disposition,claims_json,"
            "verdicts_json,coverage_json,model_id,created_at,content_hash) "
            "VALUES ('x','NOPE','v','m','h','SEND','[]','[]','{}','mid',?,'c')",
            (T0,))


def test_schema_drift_is_refused_not_silently_migrated(tmp_path):
    """CREATE TABLE IF NOT EXISTS does not add columns. An old database must
    fail loudly rather than run without the identity columns the send-commit
    triggers depend on."""
    path = tmp_path / "old.db"
    raw = sqlite3.connect(str(path))
    raw.execute("CREATE TABLE proof (proof_id TEXT PRIMARY KEY)")
    raw.commit()
    raw.close()
    with pytest.raises(db.SchemaOutOfDate):
        db.connect(path)


# --- append-only, re-verified against the CURRENT schema -------------------

@pytest.mark.parametrize("sql", [
    "UPDATE proof SET disposition='SEND'",
    "UPDATE proof SET policy_hash='forged'",
    "UPDATE proof SET gate_decision='ALLOW'",
    "UPDATE proof SET gate_reason='ALLOWED'",
    "UPDATE proof SET policy_canonical='{}'",
    "UPDATE proof SET merchant_id='other'",
    "DELETE FROM proof",
])
def test_proof_is_append_only(conn, sql):
    approve(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


@pytest.mark.parametrize("sql", ["UPDATE snapshot SET canonical='{}'",
                                 "DELETE FROM snapshot"])
def test_snapshot_is_append_only(conn, sql):
    approve(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


@pytest.mark.parametrize("sql", ["UPDATE send_log SET sent_at='2020-01-01T00:00:00+00:00'",
                                 "DELETE FROM send_log"])
def test_send_log_is_append_only(conn, sql):
    r = approve(conn)
    commit_successful_send(conn, r["proof"], T0, T0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


# --- only SEND proofs may commit -------------------------------------------

def test_commit_rejects_block_proof(conn):
    r = blocked(conn)
    assert r["disposition"] is Disposition.BLOCK
    with pytest.raises(db.SendCommitRejected):
        commit_successful_send(conn, r["proof"], T0, T0)


def test_commit_rejects_escalate_proof(conn):
    r = escalated(conn)
    assert r["disposition"] is Disposition.ESCALATE
    with pytest.raises(db.SendCommitRejected):
        commit_successful_send(conn, r["proof"], T0, T0)


def test_commit_rejects_nonexistent_proof(conn):
    with pytest.raises(db.SendCommitRejected):
        db.commit_send(conn, "prf_nope", "m", "c", T0, T0)


def test_raw_sql_cannot_bypass_the_send_disposition_rule(conn):
    """The trigger enforces this, not an application `if`."""
    r = blocked(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO send_log(proof_id,merchant_id,customer_id,sent_at,"
            "committed_at) VALUES (?,?,?,?,?)",
            (r["proof"]["proof_id"], "m", "cus_b", T0, T0))


def test_raw_sql_cannot_bypass_identity_matching(conn):
    r = approve(conn, customer="real")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO send_log(proof_id,merchant_id,customer_id,sent_at,"
            "committed_at) VALUES (?,?,?,?,?)",
            (r["proof"]["proof_id"], "m", "impostor", T0, T0))


def test_commit_rejects_customer_mismatch(conn):
    r = approve(conn, customer="real")
    with pytest.raises(db.SendCommitRejected):
        db.commit_send(conn, r["proof"]["proof_id"], "m", "impostor", T0, T0)


def test_commit_rejects_merchant_mismatch(conn):
    r = approve(conn, customer="real")
    with pytest.raises(db.SendCommitRejected):
        db.commit_send(conn, r["proof"]["proof_id"], "other_m", "real", T0, T0)


@pytest.mark.parametrize("bad", ["2026-09-04T10:00:00", "not-a-time", "", None,
                                 "2026-09-04"])
def test_commit_rejects_bad_timestamps(conn, bad):
    r = approve(conn)
    with pytest.raises(db.SendCommitRejected):
        db.commit_send(conn, r["proof"]["proof_id"], "m", "cus", bad, T0)


# --- idempotency ------------------------------------------------------------

def test_retried_commit_is_idempotent(conn):
    r = approve(conn)
    assert commit_successful_send(conn, r["proof"], T0, T0) == "created"
    for _ in range(5):
        assert commit_successful_send(conn, r["proof"], T0, T0) == "already_committed"
    assert len(db.all_send_rows(conn)) == 1


def test_conflicting_commit_under_same_proof_is_rejected(conn):
    r = approve(conn)
    commit_successful_send(conn, r["proof"], T0, T0)
    with pytest.raises(db.SendCommitRejected):
        db.commit_send(conn, r["proof"]["proof_id"], "m", "cus", T_PLUS_1H, T0)


def test_two_different_proofs_produce_two_send_facts(conn):
    a = approve(conn, customer="c1")
    b = approve(conn, customer="c2")
    commit_successful_send(conn, a["proof"], T0, T0)
    commit_successful_send(conn, b["proof"], T0, T0)
    assert len(db.all_send_rows(conn)) == 2


# --- SEND is not delivery ---------------------------------------------------

def test_send_disposition_alone_writes_no_send_log(conn):
    """The core distinction of this phase."""
    r = approve(conn)
    assert r["disposition"] is Disposition.SEND
    assert db.all_send_rows(conn) == []
    assert db.last_send_at(conn, "m", "cus") is None


def test_approved_but_undelivered_does_not_consume_cooldown(conn):
    approve(conn, customer="undelivered", now=T0)          # no commit
    again = evaluate(fx.DRAFT, StateRequest("m", "undelivered", "final_attempt"),
                     FixtureStateProvider(), fx.mock_model, conn,
                     policy=POLICY, now=T_PLUS_1H)
    assert again["gate"].reason_code == "ALLOWED"


def test_failed_delivery_does_not_consume_cooldown(conn):
    r = approve(conn, customer="failed")
    outcome, status = deliver_and_commit(conn, r, SimulatedSender(succeed=False),
                                         T0, T0)
    assert outcome.success is False
    assert status == "delivery_failed"
    assert db.all_send_rows(conn) == []

    again = evaluate(fx.DRAFT, StateRequest("m", "failed", "final_attempt"),
                     FixtureStateProvider(), fx.mock_model, conn,
                     policy=POLICY, now=T_PLUS_1H)
    assert again["gate"].reason_code == "ALLOWED"


def test_deliver_and_commit_refuses_unapproved(conn):
    r = blocked(conn)
    outcome, status = deliver_and_commit(conn, r, SimulatedSender(), T0, T0)
    assert (outcome, status) == (None, "not_approved")
    assert db.all_send_rows(conn) == []


# --- THE end-to-end cooldown lifecycle -------------------------------------

def test_cooldown_lifecycle_end_to_end(conn):
    """eligible -> SEND -> no send_log -> commit -> one row -> BLOCK, 0 calls."""
    calls = {"provider": 0, "propose": 0}

    class CountingProvider:
        name = "counting"

        def get_state(self, request):
            calls["provider"] += 1
            return FixtureStateProvider().get_state(request)

    def counting_propose(draft, state):
        calls["propose"] += 1
        return fx.mock_model(draft, state)

    # 1. eligible -> SEND, provider 1, propose 1
    r = evaluate(fx.DRAFT, StateRequest("m", "life", "final_attempt"),
                 CountingProvider(), counting_propose, conn,
                 policy=POLICY, now=T0)
    assert r["disposition"] is Disposition.SEND
    assert (calls["provider"], calls["propose"]) == (1, 1)

    # 2. approval alone consumes nothing
    assert db.all_send_rows(conn) == []

    # 3. successful delivery -> exactly one send fact
    outcome, status = deliver_and_commit(conn, r, SimulatedSender(), T0, T0)
    assert outcome.success and status == "created"
    assert len(db.all_send_rows(conn)) == 1
    assert db.last_send_at(conn, "m", "life") == T0

    # 4. second evaluation inside the window -> BLOCK, zero calls
    before = dict(calls)
    r2 = evaluate(fx.DRAFT, StateRequest("m", "life", "final_attempt"),
                  CountingProvider(), counting_propose, conn,
                  policy=POLICY, now=T_PLUS_1H)
    assert r2["disposition"] is Disposition.BLOCK
    assert r2["gate"].reason_code == COOLDOWN
    assert calls == before, "gated request touched provider or model"

    # 5. exactly at the window boundary -> allowed again
    r3 = evaluate(fx.DRAFT, StateRequest("m", "life", "final_attempt"),
                  CountingProvider(), counting_propose, conn,
                  policy=POLICY, now=T_PLUS_24H)
    assert r3["gate"].reason_code == "ALLOWED"


# --- replay: send-log structural integrity ---------------------------------

def test_send_log_integrity_passes_for_a_clean_lifecycle(conn):
    r = approve(conn)
    commit_successful_send(conn, r["proof"], T0, T0)
    ok, problems = check_send_log(conn)
    assert ok, problems


def test_send_proof_without_a_send_row_is_structurally_valid(conn):
    approve(conn)
    ok, problems = check_send_log(conn)
    assert ok, problems


def test_tampered_send_row_against_blocked_proof_fails_replay(tmp_path):
    """Direct file tampering is not defended against - only detected."""
    path = tmp_path / "t.db"
    c = db.connect(path)
    r = blocked(c)
    c.close()

    raw = db.connect(path)
    raw.execute("DROP TRIGGER send_log_requires_send_proof")
    raw.execute(
        "INSERT INTO send_log(proof_id,merchant_id,customer_id,sent_at,"
        "committed_at) VALUES (?,?,?,?,?)",
        (r["proof"]["proof_id"], "m", "cus_b", T0, T0))
    raw.commit()

    ok, problems = check_send_log(raw)
    assert not ok
    assert any("only SEND proofs may be delivered" in p for p in problems), problems


def test_tampered_send_identity_fails_replay(tmp_path):
    path = tmp_path / "t2.db"
    c = db.connect(path)
    r = approve(c, customer="real")
    c.close()

    raw = db.connect(path)
    raw.execute("DROP TRIGGER send_log_requires_send_proof")
    raw.execute(
        "INSERT INTO send_log(proof_id,merchant_id,customer_id,sent_at,"
        "committed_at) VALUES (?,?,?,?,?)",
        (r["proof"]["proof_id"], "m", "impostor", T0, T0))
    raw.commit()

    ok, problems = check_send_log(raw)
    assert not ok
    assert any("does not match proof" in p for p in problems), problems


# --- replay EXIT CODE, not just printed output -----------------------------

def _recheck_exit(db_path) -> int:
    """Runs the CLI as a subprocess. An earlier check piped output through
    `head`, so `$?` reported head's status and a forged send row appeared to
    exit 0 while the failure was actually being printed. Assert the real code.
    """
    import subprocess
    import sys
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in ("ANTHROPIC_API_KEY", "RAZORPAY_KEY_ID",
                        "RAZORPAY_KEY_SECRET")}
    out = subprocess.run([sys.executable, "recheck.py", "--db", str(db_path),
                          "--all"], capture_output=True, text=True,
                         timeout=90, env=env,
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    return out.returncode


def test_replay_exits_zero_for_a_clean_lifecycle(tmp_path):
    path = tmp_path / "clean.db"
    c = db.connect(path)
    r = approve(c)
    commit_successful_send(c, r["proof"], T0, T0)
    c.close()
    assert _recheck_exit(path) == 0


def test_replay_exits_non_zero_when_a_send_is_forged(tmp_path):
    path = tmp_path / "forged.db"
    c = db.connect(path)
    r = blocked(c)
    c.close()

    raw = db.connect(path)
    raw.execute("DROP TRIGGER send_log_requires_send_proof")
    raw.execute("INSERT INTO send_log(proof_id,merchant_id,customer_id,"
                "sent_at,committed_at) VALUES (?,?,?,?,?)",
                (r["proof"]["proof_id"], "m", "cus_b", T0, T0))
    raw.commit()
    raw.close()

    assert _recheck_exit(path) == 1
