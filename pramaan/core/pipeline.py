"""The evaluation pipeline. The only module that imports both the model side
and the deterministic side.

HARD INVARIANT: one evaluation performs exactly ONE authoritative state
acquisition, and the state from that single call is the only state used for
canonicalisation, evidence resolution, coverage and the proof. Verification
never refetches.
"""

import json
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from ..llm.errors import ProposerSchemaViolation
from ..policy.gate import evaluate_post_state, evaluate_pre_state
from ..policy.loader import (canonical_policy, load_default_policy,
                             policy_hash, policy_identity)
from ..policy.schema import GateContext, GateResult, Policy
from ..state.contract import AuthoritativeState, StateRequest, StateSource
from ..state.errors import StateProviderError
from .verify import coverage as cov
from .verify.canonical import canonicalise, content_hash, snapshot_hash
from .verify.normalise import normalise
from .verify.rules import adjudicate_all
from .verify.schema import Disposition, Proposal, Status

MODEL_ID = "mock-deterministic-v1"

# Why an evaluation ended where it did. Distinguishes infrastructure failure
# from model failure from message content - collapsing them would hide an
# outage behind "the model was unreliable".
FAILURE_NONE = ""
FAILURE_STATE_ACQUISITION = "STATE_ACQUISITION_FAILED"
FAILURE_MODEL_SCHEMA = "MODEL_OUTPUT_SCHEMA_INVALID"
FAILURE_MODEL_CALL = "MODEL_CALL_FAILED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def decide(verdicts, coverage_report) -> Disposition:
    """Fail closed. Only an all-SUPPORTED, fully-covered message may send.

    ESCALATE outranks BLOCK: a malformed citation means the MODEL is
    unreliable, which is a different operational signal from this message
    being unsupported.
    """
    if any(v.status is Status.MALFORMED for v in verdicts):
        return Disposition.ESCALATE
    if not coverage_report.passed:
        return Disposition.BLOCK
    if any(v.status is not Status.SUPPORTED for v in verdicts):
        return Disposition.BLOCK
    if not verdicts:
        return Disposition.BLOCK
    return Disposition.SEND


def _policy_evidence(policy: Policy) -> dict:
    """Everything a replay needs to re-derive this policy decision."""
    return {"policy_hash": policy_hash(policy),
            "policy_canonical": canonical_policy(policy),
            "policy_version": policy_identity(policy)}


def build_gate_context(request: StateRequest, now: str, conn=None) -> GateContext:
    """Read the local facts the pre-state gate needs.

    Database I/O happens HERE, in the coordination layer - never inside the
    pure decision function. These are Pramaan's own records, so reading them
    costs no provider call, which is what makes the zero-acquisition guarantee
    achievable at all.
    """
    suppressed, last_send = False, None
    if conn is not None:
        from ..storage import db
        suppressed = db.is_suppressed(conn, request.merchant_id, request.customer_id)
        last_send = db.last_send_at(conn, request.merchant_id, request.customer_id)
    return GateContext(merchant_id=request.merchant_id,
                       customer_id=request.customer_id, now=now,
                       suppressed=suppressed, last_send_at=last_send)


def evaluate(raw_draft: str, request: StateRequest, provider, propose,
             conn=None, policy: Policy | None = None,
             now: str | None = None) -> dict:
    """raw draft + a state request -> disposition + proof.

    `provider` is any AuthoritativeStateProvider.
    `propose` is any callable (draft, state) -> dict.
    `policy` defaults to the validated default policy document.
    `now` is injected so cooldown decisions are replayable.
    """
    # 0. one canonical coordinate system, before anything computes an offset
    draft = normalise(raw_draft)

    policy = policy or load_default_policy()
    now = now or _now_iso()
    pol = _policy_evidence(policy)

    # 1. THE PRE-STATE GATE. A denial here returns before the provider or the
    #    model is touched: no authoritative state is acquired and the model
    #    receives nothing at all.
    gate_ctx = build_gate_context(request, now, conn)
    gate = evaluate_pre_state(gate_ctx, policy)
    if not gate.allowed:
        return _finish(draft, None, None, [], [], cov.check(draft, []),
                       Disposition.BLOCK, conn, provenance=None, policy=pol,
                       gate_ctx=gate_ctx, gate=gate, request=request)

    # 2. THE single authoritative state acquisition. Acquisition failure is an
    #    infrastructure outcome and can never become SEND.
    try:
        acquired: AuthoritativeState = provider.get_state(request)
    except StateProviderError as exc:
        return _finish(draft, None, None, [], [], cov.check(draft, []),
                       Disposition.ESCALATE, conn, provenance=None, policy=pol,
                       gate_ctx=gate_ctx, gate=gate, request=request,
                       failure_reason=FAILURE_STATE_ACQUISITION,
                       failure_detail=f"{type(exc).__name__}: {exc}")

    state = acquired.state          # primitives, validated at the boundary

    # 2. frozen and identified BEFORE the model sees it, so the state the model
    #    read and the state the adjudicator used cannot diverge
    canonical = canonicalise(state)
    snap_hash = snapshot_hash(state)

    # 3. POST-STATE gate. attempt_index is authoritative state, so an attempt
    #    cap cannot be a pre-state rule without acquiring state first. It runs
    #    here - still before the model, so a capped request costs no model call.
    post_gate = evaluate_post_state(state, policy)
    if not post_gate.allowed:
        return _finish(draft, snap_hash, canonical, [], [],
                       cov.check(draft, []), Disposition.BLOCK, conn,
                       provenance=acquired, policy=pol, gate_ctx=gate_ctx,
                       gate=post_gate, request=request)

    # 4. the one model call
    try:
        raw_proposal = propose(draft, state)
    except ProposerSchemaViolation as exc:
        # The model answered but its payload was rejected by the production
        # schema. That is a MODEL failure, not infrastructure - keeping them
        # apart is what lets benchmark reporting separate parse failures from
        # reasoning errors.
        return _finish(draft, snap_hash, canonical, [], [],
                       cov.check(draft, []), Disposition.ESCALATE, conn,
                       provenance=acquired, policy=pol, gate_ctx=gate_ctx,
                       gate=gate, request=request,
                       failure_reason=FAILURE_MODEL_SCHEMA,
                       failure_detail=f"{type(exc).__name__}: {exc}")
    except Exception as exc:                       # provider/model transport
        return _finish(draft, snap_hash, canonical, [], [],
                       cov.check(draft, []), Disposition.ESCALATE, conn,
                       provenance=acquired, policy=pol, gate_ctx=gate_ctx,
                       gate=gate, request=request, failure_reason=FAILURE_MODEL_CALL,
                       failure_detail=f"{type(exc).__name__}: {exc}")

    # 4. strict schema. Unparseable output escalates; it never partially applies.
    try:
        proposal = Proposal.model_validate(raw_proposal)
    except ValidationError as exc:
        return _finish(draft, snap_hash, canonical, [], [],
                       cov.check(draft, []), Disposition.ESCALATE, conn,
                       provenance=acquired, policy=pol, gate_ctx=gate_ctx,
                       gate=gate, request=request, failure_reason=FAILURE_MODEL_SCHEMA,
                       failure_detail=exc.errors()[0]["msg"])

    # 5. adjudicate against THAT snapshot's state - no refetch
    verdicts = adjudicate_all(list(proposal.claims), state)

    # 6. coverage, over ADJUDICATED findings only. A claim whose citation did
    #    not resolve must not be able to satisfy coverage for its span.
    adjudicated = [
        {"claim_id": v.claim_id, "claim_kind": v.kind.value,
         "span_start": c.span_start, "span_end": c.span_end}
        for c, v in zip(proposal.claims, verdicts)
        if v.status is not Status.MALFORMED
    ]
    report = cov.check(draft, adjudicated)

    return _finish(draft, snap_hash, canonical, list(proposal.claims), verdicts,
                   report, decide(verdicts, report), conn, provenance=acquired,
                   policy=pol, gate_ctx=gate_ctx, gate=gate, request=request)


def _finish(draft, snap_hash, canonical, claims, verdicts, report,
            disposition, conn, provenance: AuthoritativeState | None,
            policy: dict, gate_ctx: GateContext, gate: GateResult,
            request: StateRequest,
            failure_reason: str = FAILURE_NONE, failure_detail: str = "") -> dict:
    proof = {
        "proof_id": "prf_" + uuid.uuid4().hex[:12],
        "snapshot_hash": snap_hash,
        "merchant_id": request.merchant_id,
        "customer_id": request.customer_id,
        "policy_version": policy["policy_version"],
        "policy_hash": policy["policy_hash"],
        # the exact validated policy bytes, so replay re-derives this decision
        # from the policy that made it rather than from today's policy
        "policy_canonical": policy["policy_canonical"],
        "gate_context_json": canonicalise(gate_ctx.model_dump(mode="json")),
        "gate_decision": gate.decision.value,
        "gate_reason": gate.reason_code,
        "normalised_message": draft,
        "message_hash": content_hash(draft),
        "disposition": disposition.value,
        "claims_json": json.dumps([c.model_dump(mode="json") for c in claims],
                                  sort_keys=True),
        "verdicts_json": json.dumps([v.model_dump(mode="json") for v in verdicts],
                                    sort_keys=True),
        "coverage_json": json.dumps(
            {"passed": report.passed,
             "spans": [{"kind": s.kind, "start": s.start, "end": s.end,
                        "text": s.text, "covered_by": s.covered_by}
                       for s in report.spans],
             "reason": report.reason()}, sort_keys=True),
        "model_id": MODEL_ID,
        # provenance travels into the proof. Fixture state is never labelled LIVE.
        "state_source": provenance.source.value if provenance else "",
        "state_provider": provenance.provider if provenance else "",
        "state_retrieved_at": provenance.retrieved_at if provenance else "",
        "failure_reason": failure_reason,
        "failure_detail": failure_detail,
        "created_at": _now_iso(),
    }
    proof["content_hash"] = content_hash(
        canonicalise({k: v for k, v in proof.items() if k != "content_hash"}))

    if conn is not None:
        from ..storage import db
        # A gate denial still produces an audit record. Only the SNAPSHOT row
        # is conditional - there is no state to store when nothing was fetched.
        if snap_hash:
            db.put_snapshot(conn, snap_hash, proof["created_at"], canonical)
        db.put_proof(conn, proof)

    return {"disposition": disposition, "verdicts": verdicts,
            "coverage": report, "proof": proof, "gate": gate,
            "state_source": StateSource(provenance.source) if provenance else None}
