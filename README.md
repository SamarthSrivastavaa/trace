# Pramaan

**Pramaan checks every factual claim in an AI agent's customer message against a frozen snapshot of the merchant's real data, and records a proof that anyone can re-verify later without re-running the model.**

*Pramāṇa* — in Indian epistemology, the means by which a claim becomes valid knowledge. Here: no claim ships without proof.

---

## The problem, in one example

An AI recovery agent drafts this message:

> "This is our final attempt. Your 15% offer expires in 24 hours."

Is it true? **You cannot tell from the text.** Run it through Pramaan twice, changing exactly one field of authoritative state:

```
$ python -m pramaan demo

BEAT 1  same message, one authoritative state field changed
  final_attempt  -> SEND      # subscription.attempt_index = 4 of 4
  first_attempt  -> BLOCK     # subscription.attempt_index = 1 of 4
```

Same sentence. Different truth. Under India's CCPA dark-pattern guidelines the second version is an enumerated offence — and no text classifier, however good, can separate them, because **falsity is not a property of text.** It requires joining the claim to live merchant state.

## What Pramaan proves — exact wording

> *This claim was, or was not, supported by this authoritative state at this recorded snapshot.*

## What Pramaan does NOT prove

Read this before the features.

- **Not legal compliance.** It produces evidence usable in a CCPA self-audit. Whether a message is lawful is a legal judgement this system does not make.
- **Not future truth.** A claim true at the snapshot can be false a second later. The guarantee is scoped to the recorded snapshot.
- **Not real-world truth.** It verifies consistency with *recorded state*. If a merchant fabricates an offer record, the message verifies.
- **Not hallucination elimination.** The model can still be wrong. It cannot be wrong *undetectably*.
- **Not end-to-end determinism.** Claim extraction is an LLM call and varies between runs. Only *replay of a recorded decision* is deterministic. (See `FAILURES.md` #6 — this claim was wrong once and was narrowed.)
- **Not tamper-proof.** Tamper-*evident*, narrowly. Anyone who can write the database file can rewrite it.
- **Not more accurate than an LLM.** No accuracy comparison has been run. See *Kill test* below.

## Prior work — stated up front, not buried

The closest published system is **ProvenanceGuard** ([arXiv 2606.18037](https://arxiv.org/abs/2606.18037), June 2026): a post-generation verification layer for MCP tool-using agents that decomposes answers into atomic claims, routes them to source-specific evidence, and fails closed. **That architectural pattern is theirs and the wider attribution literature's, not mine.** Structured claims validated deterministically is described in that literature as the working default, not as an invention.

Pramaan differs in what it verifies *against*: ProvenanceGuard checks attribution to static retrieved documents and states explicitly that proving a source correct is out of scope. Pramaan checks truth against **live, mutable transactional state owned by the party that benefits from the claim being believed**. Same shape, harder trust model, different domain.

Honest novelty score for the mechanism: low. The domain transfer and trust model are where the work is.

---

## Quickstart — no credentials, no network

```bash
pip install -r requirements.txt
python -m pramaan demo                       # all four beats + cooldown lifecycle
python -m pramaan recheck --db pramaan.db --all
python -m pytest tests/ -q                   # 391 tests, fully offline
```

The default configuration is fully simulated. `python -m pramaan status` prints the mode banner; simulated state is never displayed as live.

```bash
python -m pramaan evaluate \
  --draft "This is our final attempt. Your 15% offer expires in 24 hours." \
  --customer alice --scenario final_attempt --now 2026-09-04T10:00:00+00:00
```

## The four demo beats

| Beat | What it shows | Command |
|---|---|---|
| **1 — State flip** | Same message, one state field changed, verdict flips | `python -m pramaan demo` |
| **2 — Forged evidence** | Model cites a well-formed but nonexistent offer id → `ESCALATE` | same |
| **3 — Silent omission** | Model drops a claim; *independent* coverage catches it → `BLOCK` | same |
| **4 — Offline replay** | Every decision re-derived with no model and no network | `python -m pramaan recheck --all` |

Beat 4 is the one to try yourself. Unset every credential, disconnect the network, and it still exits 0 — then corrupt one snapshot byte and it exits 1.

## Architecture

```
  raw draft + request
        │
   ⓪ NORMALISE ──── NFC once. THE canonical form: model input, lexing,
        │            offsets and hashing all use it. A guard raises on drift.
   ① GATE ───────── deterministic · suppression · cooldown · NPCI attempt cap
        │            A denial costs ZERO provider calls and ZERO model calls.
   ② SNAPSHOT ───── acquired ONCE → projected → canonicalised (RFC 8785,
        │            NFC, no floats) → sha256. Frozen before the model sees it.
   ③ PROPOSE ────── ONE model call. Typed claims only. The model has no
        │            verdict field — a verdict is unrepresentable in its output.
        ├──────────────┬──────────────────────┐
        ▼              ▼                      ▼
   ④ SCHEMA      ⑤ RESOLVE EVIDENCE     ⑥ COVERAGE
   closed enums   record must exist       lexes the draft independently
   Literal fields in THIS snapshot        of anything the model said
        └──────────────┴──────────────────────┘
                       │  all three must pass
              ┌────────┴────────┐
           FAIL              PASS
              │                 │
      ESCALATE / BLOCK    ⑦ PURE ADJUDICATOR   (no I/O, no clock, no model)
                                │
                          ⑧ PROOF → append-only SQLite
                                │
              ┌─────────────────┴──────────────────┐
              ▼                                    ▼
     DELIVERY HANDOFF                    recheck.py (offline, no key)
     (caller's transport)
              │ success
              ▼
     ⑨ SEND COMMIT ──── the fact that consumes cooldown
```

**The design decision that carries the project:** stages ①④⑤⑥⑦ are deterministic; ③ is the only LLM call. Extraction and tone are language problems. Suppression, frequency, retry caps and numeric comparison are policy and arithmetic — delegating arithmetic to a stochastic system is how you get an unauditable compliance layer.

## What happens when the model is wrong

| Failure | Caught by | Outcome |
|---|---|---|
| Fabricates an offer id | Evidence resolution against the snapshot | `ESCALATE` |
| Emits a verdict | Schema — `ProposedClaim` has no `status` field | Unrepresentable |
| Invents a field name | Closed `EvidenceRef` union with `Literal` fields | Parse failure |
| Silently omits a claim | Coverage, computed from the draft independently | `BLOCK` |
| Returns malformed JSON | Production `Proposal` schema | `ESCALATE` |
| Times out / API down | Typed transport errors | `ESCALATE`, never `SEND` |

**Fail closed everywhere.** A blocked message costs one conversion; a false claim costs a regulatory finding.

## SEND is not delivery

An approved evaluation is **not** a delivery. Pramaan never observes a transport.

```
evaluate → SEND          → no send_log row, cooldown untouched
deliver  → success       → commit_successful_send() → one row → cooldown consumed
retry commit             → already_committed, still one row
```

`send_log.proof_id` is the primary key, so idempotency is structural. Database triggers — not an application `if` — reject a send against a non-`SEND` proof or a mismatched customer; raw SQL cannot bypass them.

## Trust boundaries

| Boundary | Enforcement |
|---|---|
| Model output | Closed schema; no verdict field; production `Proposal` is the sole authority |
| Evidence | Must resolve in *this* snapshot; `Literal` field names make traversal unrepresentable |
| Adjudicator | Pure: no network, no DB, no clock, no dynamic import. Enforced by a recursive AST allowlist **and** a runtime guard that patches `socket`/`sqlite3` |
| Comparison | Primitives only — a crafted `__eq__` raises rather than executing |
| Storage | Append-only triggers on `proof`, `snapshot`, `send_log` |
| Secrets | `AppConfig` holds selectors only. Each integration reads its own credential, so config has nothing to redact |

## Live integration status

| Component | Status |
|---|---|
| Deterministic core | **Working**, 391 offline tests |
| Fixture state provider | **Working**, SIMULATED, no credentials |
| Anthropic proposer | **Adapter complete, tested against a fake transport. No live call has ever been made.** |
| Razorpay state provider | **Boundary skeleton only.** 8 of 12 field mappings unresolved; `get_state` raises rather than guessing endpoint shapes |
| Delivery transport | **`SimulatedSender` only.** No vendor integration exists |

## Kill test

`killtest/` holds a frozen 70-case benchmark (35 dev / 35 held-out) comparing three arms: text-only LLM (B1), LLM with state (B2), and Pramaan's shipped path (B3).

**It has not been run. There is no accuracy result.** The harness asserts that B3 is the production `ClaudeProposer` + production prompt + production adjudicator, so it cannot silently measure a lookalike.

Two things *are* established without any model call, computed from the frozen dataset:

```
majority-class baseline                     45.7%
PROVEN ceiling for ANY text-only system     57.1% held-out · 50.0% on paired cases
```

28 of 42 messages carry two different correct labels depending only on state. A text-only function returns one label per message, so it is *bounded* — this is a proof, not a measurement.

Known limits before running: only 2 of 8 held-out categories reach n≥8; 4 held-out cases depend on inventory, which no `EvidenceRef` can express, so B3 should lose them.

Frozen at `phase3-freeze` = `8b0d3753`, dataset `f3b65c56…`, prompt `proposer-v1+e9521f9d39fd97eb`, model `claude-opus-5`.

## Limitations

- **Coverage catches numeric and temporal claims only.** A silently omitted *qualitative* claim ("you qualify", "exclusive to you") is not caught. This is the largest open hole.
- **Scarcity is unverifiable.** Razorpay holds no inventory, so `quantity` claims always resolve `UNVERIFIABLE` and are stripped rather than guessed.
- **TOCTOU window remains.** Snapshot is re-verified past 60 seconds; the window is narrowed, not closed.
- **Extraction varies run to run.** Mitigated: variance degrades toward `BLOCK`, never toward a wrongful send.
- **No concurrency guarantees.** Single connection, single writer. No multi-process safety claimed or tested.

## Testing

```bash
python -m pytest tests/ -q          # 391 tests, ~17s, no credentials, no network
```

| Area | Tests |
|---|---|
| Repo integrity & architecture boundaries | 91 |
| LLM adapter | 43 |
| Storage & send lifecycle | 39 |
| Policy gate | 34 |
| App & CLI | 30 |
| Kill-test harness | 26 |
| Policy loading & identity | 25 |
| State provider | 25 |
| Rules, coverage, boundary, normalise, demo beats | 45 |

`FAILURES.md` records what went wrong while building this, including three defects the tests found in my own code.

## Layout

```
pramaan/
  app.py          composition root — wires the chain, decides nothing
  cli.py          python -m pramaan {status,evaluate,send,proof,suppress,recheck,demo}
  config.py       selectors only, holds no secrets
  core/
    pipeline.py   the six stages
    verify/       normalise · canonical · schema · rules · coverage  (the trust boundary)
  policy/         policy-as-data: schema, loader, pure gate, default_policy.json
  state/          AuthoritativeStateProvider contract + fixture provider
  llm/            Anthropic proposal adapter: prompt · client · propose · errors
  storage/db.py   append-only SQLite
  delivery.py     the SEND-is-not-delivery boundary
recheck.py        offline replay — the only replay implementation
killtest/         frozen benchmark (do not modify)
```
