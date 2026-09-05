#!/usr/bin/env python
"""ONE live model call. Integration proof only - NOT an accuracy measurement.

Deliberately not collected by pytest: it costs money and needs credentials.

    pip install anthropic
    set ANTHROPIC_API_KEY=...
    python scripts/smoke_live.py

Uses one fixed draft and one fixed SIMULATED fixture state. No customer data,
no live Razorpay state. A single call cannot establish accuracy, schema-valid
rate, latency or cost - it establishes only that the request is accepted and
that the response either parses through the production schema or fails through
a typed path.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from attest.core.pipeline import evaluate                       # noqa: E402
from attest.fixtures import scenarios as fx                     # noqa: E402
from attest.llm.errors import ProposerError                     # noqa: E402
from attest.llm.propose import ClaudeProposer                   # noqa: E402
from attest.llm.prompt import prompt_identity                   # noqa: E402
from attest.state.contract import StateRequest                  # noqa: E402
from attest.state.fixture import FixtureStateProvider           # noqa: E402


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. This is the only blocker - the "
              "offline suite needs no credentials.")
        return 2

    try:
        proposer = ClaudeProposer()
    except ProposerError as exc:
        print(f"NOT CONFIGURED: {type(exc).__name__}: {exc}")
        return 2

    print(f"model            {proposer.identity['model']}")
    print(f"prompt           {prompt_identity()}")
    print(f"state            SIMULATED fixture 'final_attempt'")
    print(f"draft            {fx.DRAFT!r}\n")

    started = time.monotonic()
    result = evaluate(fx.DRAFT, StateRequest("m_smoke", "cus_smoke",
                                             "final_attempt"),
                      FixtureStateProvider(), proposer, conn=None)
    elapsed = time.monotonic() - started

    proof = result["proof"]
    schema_valid = proof["failure_reason"] != "MODEL_OUTPUT_SCHEMA_INVALID"
    print(f"schema-valid     {schema_valid}")
    print(f"adjudicated      {bool(result['verdicts'])}")
    print(f"disposition      {result['disposition'].value}")
    print(f"gate             {result['gate'].reason_code}")
    if proof["failure_reason"]:
        print(f"failure          {proof['failure_reason']}: "
              f"{proof['failure_detail'][:160]}")
    for v in result["verdicts"]:
        print(f"  {v.claim_id} {v.kind.value:<18} {v.status.value:<13} {v.reason_code}")
    print(f"\nelapsed          {elapsed:.1f}s")
    print("\nThis proves INTEGRATION only. One call establishes nothing about "
          "accuracy, schema-valid rate, latency or cost.")
    return 0 if not proof["failure_reason"] else 1


if __name__ == "__main__":
    sys.exit(main())
