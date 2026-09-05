# Demo runbook

Every command here was executed and its output copied from the real run.
Nothing below is illustrative.

**The entire demo is offline.** No API key, no Razorpay credentials, no network.

---

## 1. Pre-recording setup

```bash
cd <repo root>
rm -f demo.db                       # start from a clean database

# prove no credentials are involved
unset ANTHROPIC_API_KEY RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET   # bash
# PowerShell: Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue

python -m pytest tests/ -q          # preflight: expect "422 passed"
```

**Use repo-local paths.** A `/tmp/...` path is translated by Git Bash but not by
a bare `python -c`, which silently creates a second empty database. This cost me
a confusing minute during preparation.

Terminal: ~110 columns, large font. Several outputs are aligned tables.

---

## 2. Demo commands

### C1 — The whole system, one command

```
COMMAND:
python -m attest --db demo.db demo

EXPECTED RESULT:
MODE   state=SIMULATED model=MOCK
db     demo.db
policy attest-default@v1+c21eed9764f6f018

BEAT 1  same message, one authoritative state field changed
  final_attempt  -> SEND
  first_attempt  -> BLOCK

BEAT 2  forged evidence (well-formed but absent offer id)
  -> ESCALATE

BEAT 3  model silently omits the deadline claim
  -> BLOCK  coverage_passed=False

COOLDOWN LIFECYCLE
  evaluate only     -> SEND, commit=not_attempted
  deliver + commit  -> created
  re-evaluate +1h   -> BLOCK (COOLDOWN_NOT_ELAPSED)

WHAT THIS PROVES:
- The same message produces different dispositions when one authoritative
  state field changes.
- A well-formed but nonexistent evidence id cannot become SUPPORTED.
- A silently omitted claim is caught by coverage, independently of the proposer.
- An approved evaluation does NOT consume cooldown; a committed send does.

WHAT IT DOES NOT PROVE:
- Nothing about a real LLM. The banner says model=MOCK: the default proposer is
  a deterministic fixture, not Claude.
- Nothing about Razorpay. State is SIMULATED fixture data.
- No delivery occurred; the sender is simulated.
```

### C2 — Offline replay

```
COMMAND:
python -m attest --db demo.db recheck --all

EXPECTED RESULT (tail):
7/7 proofs re-verified (no model calls, no network)
1 recorded send(s), structural integrity OK
send-log integrity is STRUCTURAL only: it does not prove any transport delivered anything.
exit code 0

WHAT THIS PROVES:
Every recorded decision was RECOMPUTED - snapshot hash, adjudication, coverage
and disposition - from stored bytes, with no model and no network.

WHAT IT DOES NOT PROVE:
That any message was delivered. Send-log integrity is structural only, and the
tool says so itself.
```

### C3 — Tamper detection (the strongest moment)

```
COMMAND:
python scripts/tamper_demo.py demo.db
python -m attest --db demo.db recheck --all

EXPECTED RESULT:
tampered snapshot 58d07e42141e5059...
  subscription.attempt_index: 4 -> 1

MISMATCH prf_681f82f0bb4b
         - snapshot hash mismatch: stored bytes do not hash to the hash this proof cites
         - verdict mismatch: recomputed adjudication differs from the recorded one
         - disposition mismatch: recomputed=BLOCK stored=SEND
exit code 1

WHAT THIS PROVES:
One changed field in one stored snapshot produces three independent mismatches,
and replay names the exact flip: what was recorded as SEND recomputes as BLOCK.

WHAT IT DOES NOT PROVE:
Tamper *resistance*. The script has to drop a trigger to make the edit, which is
the honest point: ordinary SQL is blocked, file-level writes are not. This is
detection, not prevention.
```

### C4 — Zero-call gating

```
COMMAND:
python -m pytest tests/test_gate.py -k "touches_neither or calls_provider_then_propose" -v --no-header

EXPECTED RESULT:
tests/test_gate.py::test_allowed_request_calls_provider_then_propose_exactly_once PASSED
tests/test_gate.py::test_suppressed_request_touches_neither_provider_nor_model PASSED
tests/test_gate.py::test_cooldown_blocked_request_touches_neither PASSED
3 passed, 31 deselected

WHAT THIS PROVES:
A gated request costs zero provider calls and zero proposer calls, asserted on a
recorded call SEQUENCE. The first test is the control: without it, the other two
could pass simply because nothing was wired up.

WHAT IT DOES NOT PROVE:
Anything about live provider or live model behaviour.
```

### C5 — The trust boundary holds against hostile input

```
COMMAND:
python -m pytest tests/test_rules.py -k "crafted or absent_record" -v --no-header

EXPECTED RESULT:
tests/test_rules.py::test_absent_record_is_malformed_not_supported PASSED
tests/test_rules.py::test_crafted_object_cannot_reach_comparison PASSED
tests/test_rules.py::test_snapshot_with_crafted_value_is_rejected PASSED
3 passed, 9 deselected

WHAT THIS PROVES:
A crafted object with an overloaded __eq__ raises instead of executing inside
the comparison path, and a cited record absent from the snapshot is MALFORMED
rather than SUPPORTED. FAILURES.md #1 is the version of the code where this
was exploitable.

WHAT IT DOES NOT PROVE:
Security in general. These are two specific, named properties.
```

### C6 — Append-only storage

```
COMMAND:
python -m pytest tests/test_storage.py -k "append_only or raw_sql_cannot" -q --no-header

EXPECTED RESULT:
13 passed

WHAT THIS PROVES:
UPDATE and DELETE on proof, snapshot and send_log raise IntegrityError, and raw
SQL cannot record a send against a non-SEND proof or a mismatched customer -
the database trigger refuses, not an application `if`.

WHAT IT DOES NOT PROVE:
Protection from someone who can rewrite the database file. See C3.
```

### C7 — Full suite

```
COMMAND:
python -m pytest tests/ -q

EXPECTED RESULT:
422 passed in ~20s

WHAT THIS PROVES:
The whole suite runs offline with no credentials.

WHAT IT DOES NOT PROVE:
No test here exercises a live Anthropic or Razorpay call. None exists.
```

---

### C8 — The web UI (same engine, zero new decisions)

```
COMMAND:
python -m attest --db demo.db serve

THEN, in the browser at http://127.0.0.1:8000 :
  1. Paste the draft, choose "final attempt", press Verify  -> SEND
  2. Change ONLY the scenario to "first attempt", press Verify -> BLOCK
  3. Open the proof panel, press Re-check

EXPECTED RESULT:
Same message, one state field different, opposite dispositions.
The two proofs carry different snapshot hashes. Re-check recomputes and passes.

WHAT THIS PROVES:
The UI is a rendering layer over the same evaluation path. The browser
computes no verdict: tests/test_web.py compares every /api/verify response
against a direct Attest.evaluate() call across three scenarios that reach
three different dispositions, and rejects by AST any decision logic in the
web layer.

WHAT IT DOES NOT PROVE:
This proves nothing about the model, and no live Razorpay call happens
here. The badges in the top bar read MODEL: MOCK and STATE: SIMULATED for
exactly that reason. The page serves no route that can modify a stored
proof or snapshot.
```

---

## 3. Recovery plan

| If this fails | Likely reason | Safe reset | Changes evidence? |
|---|---|---|---|
| `demo` | stale `demo.db` from an older schema | `rm -f demo.db` and rerun | No — the demo is deterministic given injected timestamps |
| `recheck --all` says `no proofs` | `demo.db` never created, or a `/tmp` path was used | `rm -f demo.db && python -m attest --db demo.db demo` | No |
| `tamper_demo.py` says "no suitable snapshot" | ran before `demo` | run `demo` first | No |
| `recheck` exits 0 after tampering | you tampered a *different* database file | check the path; use repo-local `demo.db` | No |
| Any pytest failure | genuine regression | **stop recording** — do not proceed | Yes. Investigate, do not paper over |

`demo.db` is disposable and regenerable. Deleting and recreating it never
invalidates anything, because every timestamp in the demo is injected rather
than read from the clock.

---

## 4. Claim guard

| SAFE TO SAY | DO NOT SAY | WHY |
|---|---|---|
| "The deterministic core is exercised offline by fixtures and 422 tests." | "422 tests prove the system works in production." | No live path is exercised by any test. |
| "The UI renders what the engine returned." | "The UI verifies the message." | The browser computes nothing; every value shown came from `Attest.evaluate()` or from storage. |
| "The live Anthropic adapter is implemented and unit-tested against a fake transport, but has never been called." | "Validated with Claude." / "AI-powered verification." | Zero live model calls have been made. |
| "Razorpay acquisition is a boundary skeleton and is not demonstrated live." | "Integrated with Razorpay." | 9 of 12 field mappings are unresolved TODOs; `get_state` raises. |
| "Replay detects the tampering class demonstrated here." | "Tamper-proof." / "Immutable audit log." | Ordinary SQL is blocked; file-level writes are not. |
| "The benchmark has not been run, so I make no accuracy claim." | "More accurate than an LLM." / "Outperforms the baseline." | Dev and held-out are both unrun. |
| "A committed send consumes cooldown; an approved evaluation does not." | "Exactly-once delivery." | Single-connection SQLite; no concurrency testing. |
| "In this demo the proposer is a deterministic mock." | "Watch the AI extract claims." | The banner says `model=MOCK`. Say it out loud. |
| "The model cannot represent a verdict — `ProposedClaim` has no status field." | "The AI decides whether to send." | Verifiable in `attest/core/verify/schema.py`. |

**If a judge asks "did you run it against a real model?" the answer is: "No. The
adapter is built and tested against a fake transport; the benchmark is frozen
and ready, and I have not spent the API budget or seen a result."**
