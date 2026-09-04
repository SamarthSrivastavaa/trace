"""Runnable entrypoint.

    python -m pramaan status
    python -m pramaan evaluate --draft "..." --customer c1 --scenario final_attempt
    python -m pramaan send     --draft "..." --customer c1 --scenario final_attempt
    python -m pramaan proof <proof_id>
    python -m pramaan suppress --customer c1
    python -m pramaan recheck --all
    python -m pramaan demo

Defaults are fully simulated: no credentials, no network. Every command prints
a MODE banner so simulated state can never be mistaken for live.

`recheck` delegates to the existing recheck.py rather than reimplementing
replay - there is exactly one replay implementation.
"""

from __future__ import annotations

import argparse
import json
import sys

from .app import Pramaan
from .config import AppConfig, ConfigError, ProposerChoice, StateProviderChoice
from .storage import db


def _banner(app: Pramaan) -> None:
    print(f"MODE   {app.mode}")
    print(f"db     {app.config.db_path}")
    print(f"policy {app.policy_identity()}")
    missing = app.config.missing_credentials()
    if missing:
        print(f"WARNING missing credentials: {', '.join(missing)}")
    print()


def _build(args) -> Pramaan:
    cfg = AppConfig.from_env(
        db_path=args.db,
        state_provider=args.state_provider,
        proposer=args.proposer,
        policy_path=args.policy)
    return Pramaan(cfg)


def _print_outcome(o) -> None:
    print(f"disposition   {o.disposition.value}")
    print(f"gate          {o.gate_reason}")
    print(f"state source  {o.state_source or '(none acquired)'}")
    print(f"proof         {o.proof_id}")
    print(f"snapshot      {o.snapshot_hash or '(none - denied before acquisition)'}")
    if o.failure_reason:
        print(f"failure       {o.failure_reason}")
    for v in o.verdicts:
        print(f"  {v.claim_id} {v.kind.value:<18} "
              f"{v.status.value:<13} {v.reason_code}")
    if not o.coverage_passed:
        print("  coverage      FAILED - an un-adjudicated span would have shipped")
    suffix = "  (send recorded - cooldown consumed)" if o.sent else ""
    print(f"delivery      {o.commit_status}{suffix}")


def cmd_status(args) -> int:
    app = _build(args)
    _banner(app)
    print(f"proofs stored {len(db.all_proof_ids(app.conn))}")
    print(f"sends stored  {len(db.all_send_rows(app.conn))}")
    need = app.config.requires_credentials()
    print(f"credentials required by this configuration: {need or 'none'}")
    app.close()
    return 0


def _run(args, deliver: bool) -> int:
    app = _build(args)
    _banner(app)
    try:
        outcome = app.process(args.draft, args.merchant, args.customer,
                              args.scenario, now=args.now, deliver=deliver)
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}")
        app.close()
        return 1
    _print_outcome(outcome)
    app.close()
    return 0 if outcome.disposition.value != "ESCALATE" else 1


def cmd_evaluate(args) -> int:
    return _run(args, deliver=False)


def cmd_send(args) -> int:
    return _run(args, deliver=True)


def cmd_proof(args) -> int:
    app = _build(args)
    row = app.get_proof(args.proof_id)
    if row is None:
        print(f"no such proof: {args.proof_id}")
        app.close()
        return 1
    print(json.dumps({k: row[k] for k in row.keys()}, indent=2, sort_keys=True))
    app.close()
    return 0


def cmd_suppress(args) -> int:
    app = _build(args)
    app.suppress(args.merchant, args.customer)
    print(f"suppressed {args.merchant}/{args.customer} - permanent, no un-suppress")
    app.close()
    return 0


def cmd_recheck(args) -> int:
    """Delegates to the single replay implementation."""
    import recheck
    argv = ["--db", args.db or "pramaan.db"]
    argv += ["--all"] if args.all else ["--proof", args.proof_id or ""]
    if args.allow_policy_drift:
        argv.append("--allow-policy-drift")
    return recheck.main(argv)


def cmd_demo(args) -> int:
    """The four beats plus the cooldown lifecycle. Fully simulated."""
    from .fixtures import scenarios as fx
    args.state_provider, args.proposer = "fixture", "fixture"
    app = _build(args)
    _banner(app)
    T0, T1 = "2026-09-04T10:00:00+00:00", "2026-09-04T11:00:00+00:00"

    print("BEAT 1  same message, one authoritative state field changed")
    for scen in ("final_attempt", "first_attempt"):
        o = app.process(fx.DRAFT, "m_demo", f"beat1_{scen}", scen, now=T0)
        print(f"  {scen:<14} -> {o.disposition.value}")

    print("\nBEAT 2  forged evidence (well-formed but absent offer id)")
    app.proposer = lambda d, s: fx.forged_evidence_proposal()
    o = app.process(fx.DRAFT, "m_demo", "beat2", "final_attempt", now=T0)
    print(f"  -> {o.disposition.value}")

    print("\nBEAT 3  model silently omits the deadline claim")
    app.proposer = lambda d, s: fx.omitted_deadline_proposal()
    o = app.process(fx.DRAFT, "m_demo", "beat3", "final_attempt", now=T0)
    print(f"  -> {o.disposition.value}  coverage_passed={o.coverage_passed}")

    print("\nCOOLDOWN LIFECYCLE")
    app.proposer = fx.mock_model
    a = app.process(fx.DRAFT, "m_demo", "life", "final_attempt", now=T0)
    print(f"  evaluate only     -> {a.disposition.value}, commit={a.commit_status}")
    b = app.process(fx.DRAFT, "m_demo", "life", "final_attempt", now=T0,
                    deliver=True)
    print(f"  deliver + commit  -> {b.commit_status}")
    c = app.process(fx.DRAFT, "m_demo", "life", "final_attempt", now=T1)
    print(f"  re-evaluate +1h   -> {c.disposition.value} ({c.gate_reason})")

    print(f"\nBEAT 4  replay:  python -m pramaan recheck --db "
          f"{app.config.db_path} --all")
    app.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pramaan", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=None)
    p.add_argument("--state-provider", default=None,
                   choices=[m.value for m in StateProviderChoice])
    p.add_argument("--proposer", default=None,
                   choices=[m.value for m in ProposerChoice])
    p.add_argument("--policy", default=None)
    sub = p.add_subparsers(dest="command", required=True)

    def msg_args(sp):
        sp.add_argument("--draft", required=True)
        sp.add_argument("--merchant", default="m_default")
        sp.add_argument("--customer", required=True)
        sp.add_argument("--scenario", default=None)
        sp.add_argument("--now", default=None,
                        help="ISO-8601 with offset; injected so gate decisions "
                             "are replayable")

    sub.add_parser("status").set_defaults(func=cmd_status)

    sp = sub.add_parser("evaluate")
    msg_args(sp)
    sp.set_defaults(func=cmd_evaluate)

    sp = sub.add_parser("send")
    msg_args(sp)
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser("proof")
    sp.add_argument("proof_id")
    sp.set_defaults(func=cmd_proof)

    sp = sub.add_parser("suppress")
    sp.add_argument("--merchant", default="m_default")
    sp.add_argument("--customer", required=True)
    sp.set_defaults(func=cmd_suppress)

    sp = sub.add_parser("recheck")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--proof-id", dest="proof_id")
    sp.add_argument("--allow-policy-drift", action="store_true")
    sp.set_defaults(func=cmd_recheck)

    sub.add_parser("demo").set_defaults(func=cmd_demo)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"CONFIG ERROR {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
