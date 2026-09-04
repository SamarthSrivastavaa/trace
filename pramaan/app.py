"""The composition root.

Everything in this project existed as a component; nothing assembled them. This
module is the single place where the chain is wired:

    request -> gate -> state -> model -> verification -> proof
            -> delivery -> send commit -> replay

It CONTAINS NO BUSINESS LOGIC. It selects implementations from AppConfig and
calls the existing pipeline, delivery and storage boundaries. Every rule,
verdict, disposition and invariant stays where it already lives - duplicating
any of it here would create a second trust boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .config import AppConfig, ProposerChoice, StateProviderChoice
from .core.pipeline import evaluate
from .core.verify.schema import Disposition
from .delivery import SimulatedSender, deliver_and_commit
from .policy.loader import load_default_policy, load_policy, policy_identity
from .state.contract import StateRequest
from .storage import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Outcome:
    """One request's journey through the whole chain."""
    disposition: Disposition
    gate_reason: str
    proof_id: str
    snapshot_hash: str | None
    state_source: str
    mode: str
    delivered: bool
    commit_status: str          # created | already_committed | not_approved
                                # | delivery_failed | not_attempted
    failure_reason: str
    verdicts: tuple = ()
    coverage_passed: bool = True

    @property
    def sent(self) -> bool:
        return self.commit_status in ("created", "already_committed")


def build_state_provider(config: AppConfig):
    """Credentials are read by the component, not by config."""
    if config.state_provider is StateProviderChoice.FIXTURE:
        from .state.fixture import FixtureStateProvider
        return FixtureStateProvider()
    from .integrations.razorpay.provider import RazorpayStateProvider
    return RazorpayStateProvider()


def build_proposer(config: AppConfig):
    if config.proposer is ProposerChoice.FIXTURE:
        from .fixtures.scenarios import mock_model
        return mock_model
    from .llm.propose import ClaudeProposer
    return ClaudeProposer()


def build_policy(config: AppConfig):
    return (load_policy(config.policy_path) if config.policy_path
            else load_default_policy())


class Pramaan:
    """The application. Construct once, call `process` per request."""

    def __init__(self, config: AppConfig | None = None, *, provider=None,
                 proposer=None, policy=None, conn=None, sender=None):
        self.config = config or AppConfig()
        # Components are built LAZILY. Constructing a live component validates
        # its credentials and raises, so eager construction made it impossible
        # to ask "what is my configuration missing?" - `status` crashed instead
        # of reporting. Injected components are used as given.
        self._provider = provider
        self._proposer = proposer
        self._policy = policy
        self.conn = conn if conn is not None else db.connect(self.config.db_path)
        self.sender = sender or SimulatedSender()

    @property
    def provider(self):
        if self._provider is None:
            self._provider = build_state_provider(self.config)
        return self._provider

    @provider.setter
    def provider(self, value):
        self._provider = value

    @property
    def proposer(self):
        if self._proposer is None:
            self._proposer = build_proposer(self.config)
        return self._proposer

    @proposer.setter
    def proposer(self, value):
        self._proposer = value

    @property
    def policy(self):
        if self._policy is None:
            self._policy = build_policy(self.config)
        return self._policy

    @property
    def mode(self) -> str:
        return self.config.mode_label

    def policy_identity(self) -> str:
        return policy_identity(self.policy)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # -- the chain ---------------------------------------------------------

    def evaluate(self, draft: str, merchant_id: str, customer_id: str,
                 scenario: str | None = None, now: str | None = None) -> dict:
        """request -> gate -> state -> model -> verification -> proof."""
        return evaluate(draft,
                        StateRequest(merchant_id, customer_id, scenario),
                        self.provider, self.proposer, self.conn,
                        policy=self.policy, now=now or _now_iso())

    def process(self, draft: str, merchant_id: str, customer_id: str,
                scenario: str | None = None, now: str | None = None,
                deliver: bool = False) -> Outcome:
        """The full chain. `deliver=False` stops at the proof.

        Delivery is opt-in because an approved evaluation is NOT a delivery -
        that distinction is the whole point of the send-commit boundary.
        """
        stamp = now or _now_iso()
        result = self.evaluate(draft, merchant_id, customer_id, scenario, stamp)
        proof = result["proof"]

        outcome_delivered, status = None, "not_attempted"
        if deliver:
            outcome_delivered, status = deliver_and_commit(
                self.conn, result, self.sender, stamp, _now_iso())

        return Outcome(
            disposition=result["disposition"],
            gate_reason=result["gate"].reason_code,
            proof_id=proof["proof_id"],
            snapshot_hash=proof["snapshot_hash"],
            state_source=proof["state_source"],
            mode=self.mode,
            delivered=bool(outcome_delivered and outcome_delivered.success),
            commit_status=status,
            failure_reason=proof["failure_reason"],
            verdicts=tuple(result["verdicts"]),
            coverage_passed=result["coverage"].passed)

    # -- audit -------------------------------------------------------------

    def get_proof(self, proof_id: str):
        return db.get_proof(self.conn, proof_id)

    def suppress(self, merchant_id: str, customer_id: str,
                 source: str = "cli") -> None:
        db.suppress(self.conn, merchant_id, customer_id, _now_iso(), source)
