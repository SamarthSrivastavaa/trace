"""Append-only proof store.

SQLite, deliberately: one file a reviewer can open, no server, and recheck.py
reads it with the network off.

Immutability, split honestly:
  - ENGINE-ENFORCED: BEFORE UPDATE / BEFORE DELETE triggers that RAISE(ABORT).
    An application bug that tries to alter a recorded proof fails the write.
  - NOT GUARANTEED: anyone able to write the database FILE can rewrite it.
    Detection is partial - recheck catches a decision inconsistent with its own
    recorded evidence, but not a consistent rewrite of both rows.
Never describe this as tamper-proof.
"""

import re
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    hash         TEXT PRIMARY KEY,
    captured_at  TEXT NOT NULL,
    canonical    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proof (
    proof_id           TEXT PRIMARY KEY,
    -- NULL when the gate denied before acquisition: no state exists to cite.
    -- SQLite permits NULL under a foreign key, so the reference stays enforced
    -- for every proof that DID acquire state.
    snapshot_hash      TEXT REFERENCES snapshot(hash),
    -- Identity as real columns, not buried in gate_context_json. A send
    -- commit must be checkable against the proof by the DATABASE, and SQLite
    -- cannot join into a JSON blob from a trigger.
    merchant_id        TEXT NOT NULL DEFAULT '',
    customer_id        TEXT NOT NULL DEFAULT '',
    policy_version     TEXT NOT NULL,
    normalised_message TEXT NOT NULL,
    message_hash       TEXT NOT NULL,
    disposition        TEXT NOT NULL
                       CHECK (disposition IN ('SEND','BLOCK','ESCALATE')),
    claims_json        TEXT NOT NULL,
    verdicts_json      TEXT NOT NULL,
    coverage_json      TEXT NOT NULL,
    model_id           TEXT NOT NULL,
    state_source       TEXT NOT NULL DEFAULT '',
    state_provider     TEXT NOT NULL DEFAULT '',
    state_retrieved_at TEXT NOT NULL DEFAULT '',
    failure_reason     TEXT NOT NULL DEFAULT '',
    failure_detail     TEXT NOT NULL DEFAULT '',
    policy_hash        TEXT NOT NULL DEFAULT '',
    policy_canonical   TEXT NOT NULL DEFAULT '',
    gate_context_json  TEXT NOT NULL DEFAULT '',
    gate_decision      TEXT NOT NULL DEFAULT '',
    gate_reason        TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL,
    content_hash       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS proof_by_time ON proof(created_at DESC);

-- Local records the PRE-STATE gate reads. Deliberately Attest-side: they must
-- be readable without acquiring authoritative state, which is what makes
-- "a gated request costs zero provider calls" enforceable.
CREATE TABLE IF NOT EXISTS suppression (
    merchant_id   TEXT NOT NULL,
    customer_id   TEXT NOT NULL,
    suppressed_at TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (merchant_id, customer_id)
);

-- A send_log row means: Attest received a SUCCESSFUL-SEND COMMIT for this
-- approved proof. It does NOT mean a transport delivered anything - Attest
-- never observes the transport. It is the fact that consumes cooldown.
--
-- proof_id is the PRIMARY KEY, which makes idempotency structural: one
-- approved evaluation is one delivery event, so a retried commit collides
-- instead of creating a second cooldown-consuming fact. A timestamp would be
-- an unsafe retry identity because retries carry different clocks.
CREATE TABLE IF NOT EXISTS send_log (
    proof_id    TEXT PRIMARY KEY REFERENCES proof(proof_id),
    merchant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    sent_at     TEXT NOT NULL,          -- ISO-8601 WITH offset
    committed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS send_log_by_customer
    ON send_log(merchant_id, customer_id, sent_at DESC);

-- Enforced by the ENGINE, not by an application `if`. A caller reaching
-- around the storage API with raw SQL still cannot record a send for a
-- non-SEND proof or for the wrong customer.
CREATE TRIGGER IF NOT EXISTS send_log_requires_send_proof
BEFORE INSERT ON send_log
BEGIN
    SELECT RAISE(ABORT, 'send_log requires a proof whose disposition is SEND')
    WHERE (SELECT disposition FROM proof WHERE proof_id = NEW.proof_id)
          IS NOT 'SEND';

    SELECT RAISE(ABORT, 'send_log identity does not match the referenced proof')
    WHERE NOT EXISTS (
        SELECT 1 FROM proof
        WHERE proof_id = NEW.proof_id
          AND merchant_id = NEW.merchant_id
          AND customer_id = NEW.customer_id);
END;

CREATE TRIGGER IF NOT EXISTS send_log_no_update BEFORE UPDATE ON send_log
    BEGIN SELECT RAISE(ABORT, 'send_log rows are append-only'); END;
CREATE TRIGGER IF NOT EXISTS send_log_no_delete BEFORE DELETE ON send_log
    BEGIN SELECT RAISE(ABORT, 'send_log rows are append-only'); END;

CREATE TRIGGER IF NOT EXISTS proof_no_update BEFORE UPDATE ON proof
    BEGIN SELECT RAISE(ABORT, 'proof rows are append-only'); END;
CREATE TRIGGER IF NOT EXISTS proof_no_delete BEFORE DELETE ON proof
    BEGIN SELECT RAISE(ABORT, 'proof rows are append-only'); END;
CREATE TRIGGER IF NOT EXISTS snapshot_no_update BEFORE UPDATE ON snapshot
    BEGIN SELECT RAISE(ABORT, 'snapshot rows are append-only'); END;
CREATE TRIGGER IF NOT EXISTS snapshot_no_delete BEFORE DELETE ON snapshot
    BEGIN SELECT RAISE(ABORT, 'snapshot rows are append-only'); END;
"""


REQUIRED_PROOF_COLUMNS = {"merchant_id", "customer_id", "policy_hash",
                          "policy_canonical", "gate_decision"}
REQUIRED_SEND_LOG_COLUMNS = {"proof_id", "merchant_id", "customer_id",
                             "sent_at", "committed_at"}


class SchemaOutOfDate(RuntimeError):
    """An existing database predates the current schema.

    CREATE TABLE IF NOT EXISTS does NOT add columns to an existing table, so a
    database created by an earlier phase silently lacks the identity columns
    the send-commit triggers rely on. This project has no supported persistent
    upgrade path - databases are demo artifacts, recreated from scratch. Rather
    than ship a fake migration, connect() detects the drift and refuses.
    """


def _assert_current_schema(conn: sqlite3.Connection) -> None:
    for table, required in (("proof", REQUIRED_PROOF_COLUMNS),
                            ("send_log", REQUIRED_SEND_LOG_COLUMNS)):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not cols:
            continue                       # table absent; SCHEMA will create it
        missing = required - cols
        if missing:
            raise SchemaOutOfDate(
                f"{table} is missing {sorted(missing)}. This database was "
                "created by an earlier schema and cannot be migrated in place; "
                "delete it and re-run. Demo databases are disposable.")


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    # Must precede executescript(). A declared foreign key is inert unless
    # enforcement is on, and tests/test_storage.py verifies this EMPIRICALLY
    # by attempting a bad insert rather than trusting the pragma read-back.
    conn.execute("PRAGMA foreign_keys = ON")
    _assert_current_schema(conn)
    conn.executescript(SCHEMA)
    # executescript() commits and can reset connection state; re-assert.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def foreign_keys_enforced(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])


def put_snapshot(conn: sqlite3.Connection, hash_: str, captured_at: str,
                 canonical: str) -> None:
    """Idempotent: the same content hash is the same snapshot."""
    conn.execute(
        "INSERT OR IGNORE INTO snapshot(hash, captured_at, canonical) "
        "VALUES (?,?,?)", (hash_, captured_at, canonical))
    conn.commit()


def put_proof(conn: sqlite3.Connection, row: dict) -> None:
    cols = ("proof_id", "snapshot_hash", "policy_version", "normalised_message",
            "message_hash", "disposition", "claims_json", "verdicts_json",
            "coverage_json", "model_id", "state_source", "state_provider",
            "merchant_id", "customer_id",
            "state_retrieved_at", "failure_reason", "failure_detail",
            "policy_hash", "policy_canonical", "gate_context_json",
            "gate_decision", "gate_reason", "created_at", "content_hash")
    conn.execute(
        f"INSERT INTO proof({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(row[c] for c in cols))
    conn.commit()


def get_proof(conn: sqlite3.Connection, proof_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM proof WHERE proof_id = ?",
                        (proof_id,)).fetchone()


def get_snapshot(conn: sqlite3.Connection, hash_: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM snapshot WHERE hash = ?",
                        (hash_,)).fetchone()


def all_proof_ids(conn: sqlite3.Connection) -> list[str]:
    return [r["proof_id"] for r in
            conn.execute("SELECT proof_id FROM proof ORDER BY created_at")]


# --- gate inputs -----------------------------------------------------------
# Read here, decided in attest.policy.gate. Database I/O never happens inside
# the pure decision function.

def is_suppressed(conn: sqlite3.Connection, merchant_id: str,
                  customer_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM suppression WHERE merchant_id=? AND customer_id=?",
        (merchant_id, customer_id)).fetchone()
    return row is not None


def suppress(conn: sqlite3.Connection, merchant_id: str, customer_id: str,
             suppressed_at: str, source: str = "") -> None:
    """Idempotent. There is deliberately no un-suppress."""
    conn.execute(
        "INSERT OR IGNORE INTO suppression(merchant_id, customer_id, "
        "suppressed_at, source) VALUES (?,?,?,?)",
        (merchant_id, customer_id, suppressed_at, source))
    conn.commit()


def last_send_at(conn: sqlite3.Connection, merchant_id: str,
                 customer_id: str) -> str | None:
    """Most recent send for this customer, or None.

    Ordered by sent_at DESC then rowid DESC so identical timestamps resolve
    deterministically instead of by storage order.
    """
    row = conn.execute(
        "SELECT sent_at FROM send_log WHERE merchant_id=? AND customer_id=? "
        "ORDER BY sent_at DESC, rowid DESC LIMIT 1",
        (merchant_id, customer_id)).fetchone()
    return row["sent_at"] if row else None


class SendCommitRejected(Exception):
    """A successful-send commit failed validation."""


_OFFSET_ISO = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def commit_send(conn: sqlite3.Connection, proof_id: str, merchant_id: str,
                customer_id: str, sent_at: str, committed_at: str) -> str:
    """Record that a delivery boundary reported a SUCCESSFUL send.

    This is the ONLY way a send_log row is created. Returns "created" or
    "already_committed".

    Idempotency identity is proof_id: one approved evaluation is one delivery
    event. Retrying the same commit is a no-op success; committing DIFFERENT
    facts under the same proof_id is a conflict and is rejected.

    What this does NOT mean: that a transport delivered anything. Attest never
    observes the transport. It records that a caller reported success.
    """
    for label, value in (("proof_id", proof_id), ("merchant_id", merchant_id),
                         ("customer_id", customer_id)):
        if not isinstance(value, str) or not value:
            raise SendCommitRejected(f"{label} must be a non-empty string")
    for label, value in (("sent_at", sent_at), ("committed_at", committed_at)):
        if not isinstance(value, str) or not _OFFSET_ISO.match(value):
            raise SendCommitRejected(
                f"{label} must be ISO-8601 with an explicit UTC offset; "
                f"a naive timestamp cannot anchor a cooldown window")

    existing = conn.execute(
        "SELECT merchant_id, customer_id, sent_at FROM send_log WHERE proof_id=?",
        (proof_id,)).fetchone()
    if existing is not None:
        if (existing["merchant_id"], existing["customer_id"],
                existing["sent_at"]) != (merchant_id, customer_id, sent_at):
            raise SendCommitRejected(
                f"conflicting commit for {proof_id}: already recorded "
                f"{existing['merchant_id']}/{existing['customer_id']} at "
                f"{existing['sent_at']}")
        return "already_committed"

    try:
        with conn:                      # one transaction; triggers may ABORT
            conn.execute(
                "INSERT INTO send_log(proof_id, merchant_id, customer_id, "
                "sent_at, committed_at) VALUES (?,?,?,?,?)",
                (proof_id, merchant_id, customer_id, sent_at, committed_at))
    except sqlite3.IntegrityError as exc:
        raise SendCommitRejected(str(exc)) from exc
    return "created"


def get_send(conn: sqlite3.Connection, proof_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM send_log WHERE proof_id=?",
                        (proof_id,)).fetchone()


def all_send_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM send_log ORDER BY committed_at"))
