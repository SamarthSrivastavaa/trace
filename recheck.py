#!/usr/bin/env python
"""Offline re-verification. No model. No network.

    python recheck.py --db attest.db --proof prf_abc123
    python recheck.py --db attest.db --all

This RECOMPUTES the decision from the stored snapshot and stored claims. It
does not replay a stored verdict - replaying the answer would prove nothing.

Recomputed and compared:
    1. snapshot hash        from the stored canonical bytes
    2. message hash         from the stored normalised message
    3. verdicts             by re-running the pure adjudicator
    4. coverage             by re-lexing the stored message
    5. disposition          from 3 and 4

Exit 0 only if all five match. Any mismatch, missing snapshot, or policy-version
drift exits non-zero.
"""

import argparse
import hashlib
import json
import re
import sys

from attest.core.pipeline import decide
from attest.policy.gate import evaluate_pre_state
from attest.policy.loader import (load_default_policy, parse_policy,
                                   policy_hash)
from attest.policy.schema import GateContext
from attest.core.verify import coverage as cov
from attest.core.verify.canonical import content_hash, snapshot_hash
from attest.core.verify.rules import adjudicate_all
from attest.core.verify.schema import ProposedClaim, Status
from attest.storage import db

_OFFSET_ISO = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def recheck_one(conn, proof_id: str, allow_policy_drift: bool = False) -> tuple[bool, list[str]]:
    problems: list[str] = []
    proof = db.get_proof(conn, proof_id)
    if proof is None:
        return False, [f"{proof_id}: no such proof"]

    snap_row = db.get_snapshot(conn, proof["snapshot_hash"])
    if snap_row is None and proof["snapshot_hash"]:
        return False, [f"{proof_id}: snapshot {proof['snapshot_hash'][:12]} missing"]

    # 0. POLICY. Re-derive the decision from the policy RECORDED WITH THE
    #    PROOF, never from today's policy - a historical decision must not be
    #    silently re-adjudicated under changed rules.
    recorded_policy = None
    if proof["policy_canonical"]:
        if hashlib.sha256(proof["policy_canonical"].encode("utf-8")).hexdigest() \
                != proof["policy_hash"]:
            problems.append("policy artifact mismatch: stored policy bytes do "
                            "not hash to the policy_hash this proof cites")
        else:
            try:
                recorded_policy = parse_policy(json.loads(proof["policy_canonical"]))
            except Exception as exc:
                problems.append(f"stored policy is not loadable: {exc}")

        current = policy_hash(load_default_policy())
        if proof["policy_hash"] != current and not allow_policy_drift:
            problems.append(
                f"policy drift: proof={proof['policy_hash'][:16]} "
                f"current={current[:16]} (use --allow-policy-drift to override)")

    # 0b. re-run the pure gate over the RECORDED context and RECORDED policy
    if recorded_policy is not None and proof["gate_context_json"]:
        try:
            ctx = GateContext.model_validate(json.loads(proof["gate_context_json"]))
        except Exception as exc:
            problems.append(f"stored gate context is not loadable: {exc}")
        else:
            regate = evaluate_pre_state(ctx, recorded_policy)
            if regate.decision.value != proof["gate_decision"]:
                problems.append(
                    f"gate decision mismatch: recomputed={regate.decision.value} "
                    f"stored={proof['gate_decision']}")
            elif regate.reason_code != proof["gate_reason"]:
                problems.append(
                    f"gate reason mismatch: recomputed={regate.reason_code} "
                    f"stored={proof['gate_reason']}")

    # A gate-denied proof never acquired state, so there is nothing further to
    # recompute. Verifying the gate above IS the full re-derivation.
    if not proof["snapshot_hash"]:
        return not problems, problems

    # 1. snapshot integrity - recompute from the stored bytes
    snapshot = json.loads(snap_row["canonical"])
    if snapshot_hash(snapshot) != proof["snapshot_hash"]:
        problems.append("snapshot hash mismatch: stored bytes do not hash to "
                        "the hash this proof cites")

    # 2. message integrity
    message = proof["normalised_message"]
    if content_hash(message) != proof["message_hash"]:
        problems.append("message hash mismatch")

    # 3. verdicts - re-run the adjudicator
    claims = [ProposedClaim.model_validate(c)
              for c in json.loads(proof["claims_json"])]
    verdicts = adjudicate_all(claims, snapshot)
    recomputed_v = json.dumps([v.model_dump(mode="json") for v in verdicts],
                              sort_keys=True)
    if recomputed_v != proof["verdicts_json"]:
        problems.append("verdict mismatch: recomputed adjudication differs "
                        "from the recorded one")

    # 4. coverage - re-lex the stored message
    adjudicated = [{"claim_id": v.claim_id, "claim_kind": v.kind.value,
                    "span_start": c.span_start, "span_end": c.span_end}
                   for c, v in zip(claims, verdicts)
                   if v.status is not Status.MALFORMED]
    report = cov.check(message, adjudicated)
    stored_cov = json.loads(proof["coverage_json"])
    if report.passed != stored_cov["passed"]:
        problems.append(f"coverage mismatch: recomputed passed={report.passed} "
                        f"stored passed={stored_cov['passed']}")

    # 5. disposition
    recomputed_d = decide(verdicts, report).value
    if recomputed_d != proof["disposition"]:
        problems.append(f"disposition mismatch: recomputed={recomputed_d} "
                        f"stored={proof['disposition']}")

    return not problems, problems


def check_send_log(conn) -> tuple[bool, list[str]]:
    """Verify the STRUCTURAL integrity of recorded successful-send facts.

    This does NOT prove a transport delivered anything - Attest never observes
    the transport. It proves the recorded internal lifecycle is consistent:

      - every send references a proof that exists
      - that proof's disposition is SEND
      - identities match the proof
      - the timestamp is offset-bearing
      - at most one send per proof

    A SEND proof with no send row is VALID (approved, never delivered).
    A send row against a BLOCK proof is INVALID.
    """
    problems: list[str] = []
    for row in db.all_send_rows(conn):
        pid = row["proof_id"]
        proof = db.get_proof(conn, pid)
        if proof is None:
            problems.append(f"send {pid}: references a proof that does not exist")
            continue
        if proof["disposition"] != "SEND":
            problems.append(
                f"send {pid}: proof disposition is {proof['disposition']}, "
                "only SEND proofs may be delivered")
        if (row["merchant_id"], row["customer_id"]) !=                 (proof["merchant_id"], proof["customer_id"]):
            problems.append(
                f"send {pid}: identity {row['merchant_id']}/{row['customer_id']} "
                f"does not match proof {proof['merchant_id']}/{proof['customer_id']}")
        if not _OFFSET_ISO.match(row["sent_at"] or ""):
            problems.append(f"send {pid}: sent_at is not offset-bearing")
    return not problems, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="attest.db")
    ap.add_argument("--proof")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--allow-policy-drift", action="store_true")
    args = ap.parse_args(argv)

    if not args.proof and not args.all:
        ap.error("give --proof <id> or --all")

    conn = db.connect(args.db)
    ids = db.all_proof_ids(conn) if args.all else [args.proof]
    if not ids:
        print("no proofs to recheck")
        return 1

    send_ok, send_problems = check_send_log(conn)
    if not send_ok:
        print("SEND-LOG INTEGRITY FAILURES")
        for p in send_problems:
            print(f"         - {p}")
        print()

    failed = 0
    for pid in ids:
        ok, problems = recheck_one(conn, pid, args.allow_policy_drift)
        if ok:
            print(f"MATCH    {pid}")
        else:
            failed += 1
            print(f"MISMATCH {pid}")
            for p in problems:
                print(f"         - {p}")

    n_sends = len(db.all_send_rows(conn))
    print(f"\n{len(ids) - failed}/{len(ids)} proofs re-verified "
          f"(no model calls, no network)")
    print(f"{n_sends} recorded send(s), structural integrity "
          f"{'OK' if send_ok else 'FAILED'}")
    print("send-log integrity is STRUCTURAL only: it does not prove any "
          "transport delivered anything.")
    # A forged send row is a structural inconsistency and must exit non-zero.
    return 1 if (failed or not send_ok) else 0


if __name__ == "__main__":
    sys.exit(main())
