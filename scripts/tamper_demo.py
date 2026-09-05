#!/usr/bin/env python
"""Corrupt one field in one stored snapshot, so replay can be seen catching it.

    python scripts/tamper_demo.py demo.db

WHY THIS SCRIPT EXISTS
----------------------
No `python -m attest` command can do this, deliberately: production must not
ship an attack command. But the tamper-detection property cannot be shown
without actually tampering, so the attack lives here, clearly labelled, outside
the package.

It does not touch production code, fabricates nothing, and changes no verdict -
it edits stored bytes and lets `recheck` reach its own conclusion. Offline and
deterministic.

WHAT IT SIMULATES
-----------------
An attacker with write access to the database FILE. Attest does not defend
against that and does not claim to; the triggers stop ordinary SQL, which is
why this script has to drop one first. What is being demonstrated is
DETECTION, not prevention.
"""

import json
import sqlite3
import sys


def tamper(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT hash, canonical FROM snapshot "
        "WHERE canonical LIKE '%attempt_index%' LIMIT 1").fetchone()
    if row is None:
        print(f"no suitable snapshot in {db_path}; run `python -m attest "
              f"--db {db_path} demo` first")
        return 2

    # The append-only trigger blocks this through ordinary SQL. Dropping it is
    # the point: it shows the guarantee is "tamper-evident", not "tamper-proof".
    conn.execute("DROP TRIGGER IF EXISTS snapshot_no_update")

    state = json.loads(row["canonical"])
    before = state["subscription"]["attempt_index"]
    state["subscription"]["attempt_index"] = 1 if before != 1 else 4
    after = state["subscription"]["attempt_index"]

    conn.execute("UPDATE snapshot SET canonical = ? WHERE hash = ?",
                 (json.dumps(state, sort_keys=True, separators=(",", ":")),
                  row["hash"]))
    conn.commit()

    print(f"tampered snapshot {row['hash'][:16]}...")
    print(f"  subscription.attempt_index: {before} -> {after}")
    print("  (one field, in one stored snapshot; the proof row is untouched)")
    print(f"\nnow run:  python -m attest --db {db_path} recheck --all")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(tamper(sys.argv[1]))
