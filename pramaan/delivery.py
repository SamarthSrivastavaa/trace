"""The delivery boundary.

WHERE PRAMAAN'S RESPONSIBILITY ENDS
-----------------------------------
Pramaan decides whether a message is supported by recorded state and policy.
It returns SEND, BLOCK or ESCALATE. That is the whole of its verification
responsibility.

SEND means: "given the recorded policy and the recorded snapshot, no
deterministic reason to block or escalate was found."

SEND does NOT mean the message was delivered. Pramaan never observes a
transport. Delivery is somebody else's job and somebody else's failure mode:
the process can crash after evaluation, the transport can reject the message,
the caller can abandon the result.

So a SEND proof does not write send_log. A caller that actually achieved
delivery calls commit_successful_send(), and THAT writes the fact which
consumes cooldown.

    result = evaluate(...)                       # Pramaan
    if result.disposition is SEND:
        outcome = deliver(...)                   # NOT Pramaan
        if outcome.success:
            commit_successful_send(...)          # Pramaan records the fact

No real transport exists in this repository. SimulatedSender below is a
deterministic stand-in and is labelled SIMULATED wherever it is shown.
"""

from __future__ import annotations

from dataclasses import dataclass

from .core.verify.schema import Disposition
from .storage import db


@dataclass(frozen=True)
class DeliveryOutcome:
    """What a transport reports back. `success` is the caller's assertion."""
    success: bool
    transport: str
    detail: str = ""


class SimulatedSender:
    """SIMULATED. Never touches a network. Deterministic by construction.

    Exists so the evaluate -> deliver -> commit lifecycle can be exercised and
    tested end to end without inventing a vendor integration.
    """

    name = "simulated"

    def __init__(self, succeed: bool = True, detail: str = ""):
        self._succeed, self._detail = succeed, detail

    def deliver(self, proof: dict) -> DeliveryOutcome:
        return DeliveryOutcome(success=self._succeed, transport=self.name,
                               detail=self._detail)


def commit_successful_send(conn, proof: dict, sent_at: str,
                           committed_at: str) -> str:
    """Record a successful-send fact for an approved proof.

    Refuses anything that is not a SEND proof. Storage re-validates and the
    database triggers re-validate again, so a caller reaching around this
    function with raw SQL still cannot record a send for a BLOCK proof.

    Returns "created" or "already_committed" - retries are idempotent because
    proof_id is the identity.
    """
    if proof.get("disposition") != Disposition.SEND.value:
        raise db.SendCommitRejected(
            f"cannot commit a send for a {proof.get('disposition')} proof; "
            "only SEND proofs may be delivered")
    return db.commit_send(conn, proof_id=proof["proof_id"],
                          merchant_id=proof["merchant_id"],
                          customer_id=proof["customer_id"],
                          sent_at=sent_at, committed_at=committed_at)


def deliver_and_commit(conn, result: dict, sender, sent_at: str,
                       committed_at: str) -> tuple[DeliveryOutcome | None, str]:
    """The full lifecycle, for demos and tests.

    Returns (outcome, commit_status). commit_status is one of
    "created", "already_committed", "not_approved", "delivery_failed".
    """
    proof = result["proof"]
    if proof["disposition"] != Disposition.SEND.value:
        return None, "not_approved"

    outcome = sender.deliver(proof)
    if not outcome.success:
        return outcome, "delivery_failed"

    return outcome, commit_successful_send(conn, proof, sent_at, committed_at)
