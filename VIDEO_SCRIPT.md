# ATTEST — Demo Video Production Package

**Target runtime: 4:58** · Fully offline · Zero paid API calls · Every output in this
document was captured by running the command against this repository.

Written against commit state: **422 tests passing**, trust boundary unmodified,
frozen benchmark unchanged.

---

## Contents

1. [Repository fact check](#1-repository-fact-check)
2. [The final video script](#2-the-final-video-script)
3. [Shot list](#3-shot-list)
4. [Commands to run](#4-commands-to-run)
5. [Screen recording plan](#5-screen-recording-plan)
6. [Best opening — first 15 seconds](#6-best-opening--first-15-seconds)
7. [Best final 15 seconds](#7-best-final-15-seconds)
8. [Claim guard — risk audit and evidence map](#8-claim-guard--risk-audit-and-evidence-map)

---

# 1. Repository fact check

## 1.1 Corrections made during inspection

Three claims that circulated in planning notes were wrong. All were corrected in the
repository before this script was written.

| Claim as stated | Repository reality | Action taken |
|---|---|---|
| "8 of 12 Razorpay field mappings unresolved" | **9 of 12.** `REQUIRED_RESOURCE_MAPPING` holds 9 `TODO` entries and 3 resolved. The error *understated* the limitation — the direction that flatters the project — so nothing complained. | Corrected in `README.md`, `DEMO_RUNBOOK.md`, this file, and `attest/web/server.py::LIMITATIONS`. Pinned by `tests/test_docs.py::test_razorpay_unresolved_count_matches_the_code`, which reads the count from the code. |
| "421 passing tests" | **422** after the corrections above added a test. | Counts updated in every document. |
| "The web UI can demonstrate zero-call gating" | **It cannot.** `attest/web/index.html` sends `customer_id: "cus_" + Date.now()` on every click, so each evaluation is a brand-new customer. Suppression and cooldown can never fire from the browser. | The zero-call proof is delivered from the terminal instead. |

A fourth defect was found in the UI itself: the proof card carried the heading
**"Immutable proof"**, a phrase this project's own claim guard lists as DO-NOT-SAY.
The web test's banned-word list did not contain `immutable`, so it passed through.
The heading now reads **"Append-only proof"**, and three further forbidden
phrases were added to the page's banned-word check,
`tests/test_web.py::test_page_shows_mode_badges_and_no_fake_ai_language`.

## 1.2 Precision points that change the narration

- **The flip is a verdict flip, not a gate block.** `is_final_attempt` moves
  SUPPORTED → CONTRADICTED. Never say "policy blocked it."
- **There are two gates, not one.** `evaluate_pre_state` handles suppression and
  cooldown; `evaluate_post_state` handles the attempt cap, which needs authoritative
  state and therefore runs after acquisition — still before the model.
- **The deadline claim is a bound, not an equality.** The snapshot has 20.00 hours
  remaining; the message asserts "within 24"; the rule is `0 <= 20 <= 24` → SUPPORTED.
  Never say "expires in exactly 24 hours."
- **The attempt cap does not fire in the demo.** `attempt_index 4 > max_attempts 4`
  is false, so the SEND path reaches the model normally.

## 1.3 Verified claims

| Proposed video claim | Verified? | Exact evidence |
|---|---|---|
| Same message, one state field, SEND → BLOCK | YES | Captured live: `A SEND attempt_index=4`, `B BLOCK attempt_index=1` |
| Exactly one field differs between snapshots | YES | `attest/fixtures/scenarios.py`; `tests/test_demo_beats.py::test_beat_a_snapshots_differ_in_exactly_one_field` |
| Snapshot hashes genuinely differ | YES | `58d07e42141e5059` vs `6b5579ba1de9ddca` |
| The flipped claim is `is_final_attempt` | YES | `('is_final_attempt','SUPPORTED',True,True)` → `('is_final_attempt','CONTRADICTED',False,True)`; `tests/test_demo_beats.py::test_beat_a_state_flip` |
| The model cannot state a verdict | YES | `ProposedClaim` has no `status` field; `python -m attest.core.verify.schema` prints `REJECT model states a verdict / extra_forbidden`; `tests/test_llm_adapter.py::test_production_schema_rejects_invalid_proposals` |
| Evidence field names are Literals, not strings | YES | Closed discriminated union in `attest/core/verify/schema.py`; prints `REJECT path traversal in field` and `REJECT fabricated field name` |
| The adjudicator is pure — no network, DB, model, clock | YES | `tests/test_boundary.py::test_adjudicator_runs_with_io_disabled`, `tests/test_boundary.py::test_verify_imports_are_allowlisted` |
| A crafted object cannot reach the comparison path | YES | `tests/test_rules.py::test_crafted_object_cannot_reach_comparison` |
| Disposition is computed from verdicts + coverage only | YES | `attest/core/pipeline.py::decide` takes no model output |
| Coverage is an independent lexical pass | YES | `find_spans(draft)` reads only the draft text |
| Silent omission is caught | YES | `python -m attest.core.verify.coverage` → `DEADLINE OMITTED passed=False`; `tests/test_demo_beats.py::test_beat_c_silent_omission_blocks` |
| A forged citation cannot satisfy coverage | YES | `tests/test_demo_beats.py::test_beat_b_forged_finding_cannot_satisfy_coverage` |
| Coverage catches numeric and temporal claims only | YES — **LIMITATION** | Stated in the `coverage.py` docstring; must be said aloud |
| Forged offer id escalates rather than supporting | YES | Demo beat 2 → `ESCALATE`; `tests/test_rules.py::test_absent_record_is_malformed_not_supported`; `tests/test_demo_beats.py::test_beat_b_forged_evidence_cannot_be_supported` |
| Gate denial costs zero provider and zero model calls | YES | `tests/test_gate.py::test_suppressed_request_touches_neither_provider_nor_model`, `tests/test_gate.py::test_cooldown_blocked_request_touches_neither`, `tests/test_gate.py::test_allowed_request_calls_provider_then_propose_exactly_once` |
| The same invariant holds through the HTTP layer | YES | `tests/test_web.py::test_suppressed_request_through_the_api_costs_zero_calls` |
| Policy is data; changing a bound changes behaviour | YES | `tests/test_gate.py::test_changing_the_window_in_policy_data_changes_behaviour`; `tests/test_policy.py::test_identity_changes_when_a_bound_changes` |
| Append-only enforced by database triggers | YES | `RAISE(ABORT)` triggers in `attest/storage/db.py`; `tests/test_storage.py::test_proof_is_append_only`, `tests/test_storage.py::test_snapshot_is_append_only`, `tests/test_storage.py::test_raw_sql_cannot_bypass_the_send_disposition_rule` |
| Replay recomputes rather than re-reading | YES | `recheck.py` recomputes snapshot hash, message hash, verdicts, coverage and disposition |
| Replay needs no model and no network | YES | `tests/test_demo_beats.py::test_beat_d_replay_with_no_network`; `tests/test_state_provider.py::test_replay_does_not_invoke_the_provider` |
| Tampering is detected and exits non-zero | YES | Captured live: `disposition mismatch: recomputed=BLOCK stored=SEND`, exit code 1; `tests/test_storage.py::test_replay_exits_non_zero_when_a_send_is_forged`; `tests/test_web.py::test_recheck_reports_real_failure_after_tampering` |
| One edited field breaks 5 of 7 stored proofs | YES | Snapshots are content-addressed, so every proof citing `58d07e42…` fails |
| SEND is not delivery | YES | `evaluate only -> SEND, commit=not_attempted`; `tests/test_storage.py::test_send_disposition_alone_writes_no_send_log`, `tests/test_storage.py::test_approved_but_undelivered_does_not_consume_cooldown` |
| A committed send consumes cooldown | YES | `tests/test_storage.py::test_cooldown_lifecycle_end_to_end` |
| The UI computes nothing | YES | `tests/test_web.py::test_api_verify_matches_a_direct_evaluate_call`, `tests/test_web.py::test_server_calls_no_verification_primitive`, `tests/test_web.py::test_browser_never_computes_a_disposition`, `tests/test_web.py::test_state_flip_is_two_real_evaluations`, `tests/test_web.py::test_the_equivalence_scenarios_reach_three_different_dispositions` |
| No route can modify stored evidence | YES | `tests/test_web.py::test_no_route_can_mutate_stored_evidence`, `tests/test_web.py::test_mutating_verbs_are_rejected` |
| The whole demo runs credential-free | YES | `tests/test_docs.py::test_readme_commands_run` |
| The proposer is a deterministic mock | YES — **LIMITATION** | `MODE state=SIMULATED model=MOCK`; a deterministic fixture, not Claude |
| No live model call has ever been made | YES — **LIMITATION** | `tests/test_llm_adapter.py::test_adapter_modules_import_without_credentials_or_sdk` |
| Razorpay is a boundary skeleton | YES — **LIMITATION** | `tests/test_state_provider.py::test_razorpay_provider_does_not_pretend_to_be_integrated` |
| The frozen benchmark is unrun | YES — **LIMITATION** | No results file exists in `killtest/` |

---

# 2. The final video script

## `0:00–0:13` — THE HOOK

**ON SCREEN**
Black. One line of white text, large, centred:
`This is our final attempt. Your 15% offer expires in 24 hours.`
At 0:05 a second line fades in beneath it, amber: `Is this true?`
At 0:10 a third, grey: `You cannot answer that from the sentence.`

**NARRATION**
> An AI wrote this message to a customer. Is it true? You can't tell. Not from the
> sentence. Every fact in it — final attempt, fifteen percent, twenty-four hours —
> lives somewhere else. In the merchant's database.

**EDITING / PACING**
No music yet. Let the first line sit in silence for two seconds. Text only, so it
reads with the sound off.

**PROOF ON SCREEN**
None required. This is the problem statement.

---

## `0:13–0:38` — THE INSIGHT

**ON SCREEN**
Cut to the Attest UI at the top of the page. Hero headline visible: *"An AI wrote
this message. It cannot prove its own facts."* Then the pipeline strip. Slowly zoom
until the gold-edged boxes fill the frame:
`DRAFT · GATE · FREEZE STATE · PROPOSE CLAIMS · VERIFY EVIDENCE · COVERAGE · DECIDE · PROOF`

**NARRATION**
> Attest sits between the AI and the customer. It freezes the merchant's
> authoritative state, then asks the model for one thing only: what does this message
> claim? Not whether the claims are true. Just what they are. Everything gold on this
> strip is deterministic code. Only one box involves a model at all.

**EDITING / PACING**
Hard cut from black. Hold on the strip. Pulse `PROPOSE CLAIMS` for half a second as
the single non-gold box. No animation flourish.

**PROOF ON SCREEN**
The strip's own legend: *"Boxes with a gold edge are deterministic code."*

---

## `0:38–1:04` — THE MODEL CANNOT DECIDE

**ON SCREEN**
Terminal, full screen, large font:

```
python -m attest.core.verify.schema
```

Output scrolls. Freeze and highlight the final line:

```
REJECT  model states a verdict             extra_forbidden: Extra inputs are not permitted
```

**NARRATION**
> This isn't a prompt asking the model to behave. It's a type system. The schema the
> model must answer in has no field for a verdict. If it tries to send one, parsing
> fails. Watch — a fabricated field name: rejected. A path traversal in a citation:
> rejected. And a model attempting to state its own verdict: rejected. It isn't
> trusted not to decide. It is structurally unable to.

**EDITING / PACING**
Let the REJECT lines land as a block, then zoom to the last line. Pause one second
on it.

**PROOF ON SCREEN**
Live parser output. `ProposedClaim` genuinely has no `status` field.

---

## `1:04–2:06` — THE STATE FLIP *(the centrepiece)*

**ON SCREEN**
Back to the UI. Scroll to *"The signature demonstration — one field, opposite
outcome."* Click **Run both scenarios**. Two panels render side by side:

| Panel A | Panel B |
|---|---|
| `SEND` | `BLOCK` |
| `attempt_index 4` | `attempt_index 1` |
| `snapshot 58d07e42…` | `snapshot 6b5579ba…` |

Then scroll up to the verdict table and run each scenario individually so the three
claim rows are visible.

**NARRATION**
> Same message. Byte-identical — the page prints it so you can check. Two
> evaluations, through the same API. In the first, the subscription says attempt four
> of four. The claim "this is our final attempt" is supported. Send.
>
> Now I change one field. One. Attempt index becomes one instead of four. Same words.
> Same model output.
>
> *(pause)*
>
> Block. And look at which claim moved — `is_final_attempt`, supported to
> contradicted. The snapshot hashes differ, so the state genuinely differed. The other
> two claims never moved; fifteen percent is still fifteen percent.
>
> **The message never changed. The database did.**

**EDITING / PACING**
This is the emotional peak. Do not rush it. Hard pause of 1.5 seconds of silence
between "Same model output." and "Block." Highlight *only* the `attempt_index` row in
each panel — the UI already applies a `.diff` class to it. On the final line, cut to
the two dispositions side by side with nothing else on screen.

**PROOF ON SCREEN**
Two different `snapshot_hash` values, one changed field, one flipped verdict row —
all rendered from values returned by `Attest.evaluate()`.

---

## `2:06–2:34` — SILENT OMISSION

**ON SCREEN**
Terminal:

```
python -m attest.core.verify.coverage
```

Highlight, in sequence:

```
COMPLETE           passed=True
DEADLINE OMITTED   passed=False
  uncovered span(s): DURATION '24 hours' at offset 56
```

**NARRATION**
> Here's the bypass everyone misses. If you only check the claims the model reported,
> the model can slip a claim past you by simply not mentioning it. Asking it "did you
> cover everything?" is asking it to audit its own blind spot.
>
> So coverage is computed from the message text, by code that never sees the model's
> answer. Drop the deadline claim, and the span is still sitting there at offset
> fifty-six, unadjudicated. Blocked.
>
> This catches numeric and temporal claims. It does not catch a vaguer one like "you
> qualify." That hole is open, and it's in our docs.

**EDITING / PACING**
Split-screen the two outputs. Highlight `passed=False` in red. Deliver the limitation
sentence at normal pace — not buried, not apologetic.

**PROOF ON SCREEN**
Live output, plus the module docstring stating the limit.

---

## `2:34–3:00` — POLICY CONTROLS EXECUTION

**ON SCREEN**
Terminal:

```
python -m pytest tests/test_gate.py -k "touches_neither or calls_provider_then_propose" -v --no-header
```

Three test names visible, all PASSED.

**NARRATION**
> Policy here isn't advice, it's control flow. If a customer opted out, or we
> contacted them yesterday, the gate denies before any state is fetched and before the
> model is called. Zero provider calls. Zero model calls. The test names say exactly
> that, and they run in under a second.

**EDITING / PACING**
Let the three test names be readable — they are the evidence. No zoom needed.

**PROOF ON SCREEN**
`test_suppressed_request_touches_neither_provider_nor_model` ·
`test_cooldown_blocked_request_touches_neither` ·
`test_allowed_request_calls_provider_then_propose_exactly_once` — 3 passed.

---

## `3:00–4:06` — THE CLIMAX: DON'T TRUST THE STORED ANSWER

**ON SCREEN**
UI, *Proof & replay* card. Show the proof fields. Click **Replay offline** → green
`ALL PROOFS RE-VERIFIED`.

Cut to a terminal beside the browser:

```
python scripts/tamper_demo.py demo.db
```

```
tampered snapshot 58d07e42141e5059...
  subscription.attempt_index: 4 -> 1
  (one field, in one stored snapshot; the proof row is untouched)
```

Cut back to the browser. Click **Replay offline** again. Red panel:

```
INTEGRITY CHECK FAILED
  snapshot hash mismatch: stored bytes do not hash to the hash this proof cites
  verdict mismatch: recomputed adjudication differs from the recorded one
  disposition mismatch: recomputed=BLOCK stored=SEND
```

**NARRATION**
> Every decision writes a proof. But storing an answer isn't proof of anything —
> anyone can store an answer.
>
> So replay doesn't read the verdict back. It recomputes it. From the snapshot bytes,
> under the policy recorded with that proof, through the same adjudicator. No model.
> No network.
>
> Now let's attack it. This script edits one field inside one stored snapshot. It has
> to drop a database trigger first, because ordinary SQL updates are refused outright.
>
> Replay again.
>
> Snapshot hash no longer matches. Verdicts no longer match. And there it is —
> **recomputed BLOCK, stored SEND.** The record says we approved this message.
> Recomputation says we shouldn't have. The exit code is one.
>
> That is tamper *evidence*, not tamper prevention. It is not tamper-proof — we had to
> drop a trigger to get in, and anyone who can write the file can write the file. We
> don't claim otherwise.

**EDITING / PACING**
Split-screen the browser and the terminal for the tamper command, so it is obvious no
browser action caused it. Zoom on the `recomputed=BLOCK stored=SEND` line and hold for
1.5 seconds. This is the second peak — give it room.

**PROOF ON SCREEN**
Exact replay output, captured live from this repository.

---

## `4:06–4:36` — WHAT WE DID NOT FAKE

**ON SCREEN**
Scroll the UI to the top — `MODEL MOCK` and `STATE SIMULATED` badges large in frame.
Then scroll to *"What this does not prove"* and let the list render.

**NARRATION**
> Now the part most demos skip. These badges have been on screen the entire video. The
> mode banner says `model=MOCK` — the proposer is a deterministic fixture, not Claude.
> The state is hand-written, not Razorpay.
>
> The Anthropic adapter is built and unit-tested against a fake transport, and has
> never made a live model call. The Razorpay provider is a boundary skeleton with nine
> of twelve field mappings unresolved; it raises rather than guessing. We froze a
> seventy-case benchmark and have not run it, so we make no accuracy claim at all.
>
> We haven't proven what we haven't measured. Everything you *did* see was real.

**EDITING / PACING**
Slow down noticeably. No cuts during the limitations list — one continuous scroll.
Confident tone, not apologetic.

**PROOF ON SCREEN**
The badges, and the limitations list served from `attest/web/server.py::LIMITATIONS`.

---

## `4:36–4:58` — CLOSE

**ON SCREEN**
Cut to the two dispositions side by side once more — `SEND` / `BLOCK` — with the
identical message above them. Hold. Then fade to black; `ATTEST` wordmark and
`Proof before send.`

**NARRATION**
> Let the AI write the message. But the moment that message makes a factual promise to
> a customer, the AI should not be the thing that decides whether it's true.
>
> Attest makes that decision deterministic, recorded, and something anyone can
> recompute without asking us to be trusted.
>
> Same words. Different truth. That's the whole idea.

**EDITING / PACING**
Music out under the final sentence. Last frame silent for one second.

---

# 3. Shot list

| # | Duration | Screen | Action | Narration goal | Exact value to capture |
|---|---|---|---|---|---|
| 1 | 13s | Black + text | Three lines fade in | Problem understood in 10s, legible with sound off | The draft sentence verbatim |
| 2 | 25s | Browser, top | Scroll hero, zoom pipeline strip | Model proposes, code decides | Gold-edge legend |
| 3 | 26s | Terminal | `python -m attest.core.verify.schema` | Structural, not prompted | `REJECT model states a verdict` |
| 4 | 22s | Browser, flip section | Click *Run both scenarios* | Setup for the flip | `attempt_index 4` / `attempt_index 1` |
| 5 | 40s | Browser, panels + verdict table | Reveal A then B | **The punch** | `SEND`/`BLOCK`; `58d07e42…`/`6b5579ba…`; `is_final_attempt` SUPPORTED→CONTRADICTED |
| 6 | 28s | Terminal, split | `python -m attest.core.verify.coverage` | Omission is the real bypass | `uncovered span(s): DURATION '24 hours' at offset 56` |
| 7 | 26s | Terminal | Gate pytest selection | Policy is control flow | Three test names, `3 passed` |
| 8 | 20s | Browser, proof card | Click *Replay offline* | Clean baseline | `ALL PROOFS RE-VERIFIED` |
| 9 | 18s | Terminal + browser split | `python scripts/tamper_demo.py demo.db` | The attack is external to the product | `attempt_index: 4 -> 1` |
| 10 | 28s | Browser | Click *Replay offline* again | **Second punch** | `recomputed=BLOCK stored=SEND` |
| 11 | 30s | Browser top, then limitations | Scroll, no cuts | Honesty as credibility | `MODEL MOCK`, `STATE SIMULATED`, 8 list items |
| 12 | 22s | Two dispositions, then wordmark | Hold, fade | Thesis | Identical message above opposite outcomes |

---

# 4. Commands to run

Recording order. All paths are repo-local. **Never use `/tmp`** — Git Bash translates
it and a bare `python -c` does not, which previously created a second empty database
mid-demo.

```bash
# --- SETUP (before recording) ---
cd /c/Users/HP/OneDrive/Desktop/rzr
rm -f demo.db                                   # clean slate
python -m pytest tests/ -q                      # preflight: expect "422 passed"

# --- SHOT 3 ---
python -m attest.core.verify.schema

# --- SHOTS 4, 5, 8, 10 — leave this running in its own pane ---
python -m attest --db demo.db serve
# then browse to http://127.0.0.1:8000

# --- SHOT 6 ---
python -m attest.core.verify.coverage

# --- SHOT 7 ---
python -m pytest tests/test_gate.py -k "touches_neither or calls_provider_then_propose" -v --no-header

# --- SHOT 9 --- MUTATES demo.db. IRREVERSIBLE. RECORD LAST.
python scripts/tamper_demo.py demo.db

# --- RESET (only if you must re-shoot) ---
# Ctrl-C the server, then:
rm -f demo.db && python -m attest --db demo.db serve
```

## Ordering constraints (both verified)

1. **Tamper must be the last action against `demo.db`.** Snapshots are
   content-addressed and `put_snapshot` uses `INSERT OR IGNORE`. Once `58d07e42…`
   holds tampered bytes, every *future* `final_attempt` evaluation cites that same
   hash and will also fail replay. There is no un-tamper; delete the database.
2. **Press *Run both scenarios* before *Replay offline*,** so replay has proofs to
   verify.

## Fallback if the browser misbehaves

The entire story is available from the CLI in two commands:

```bash
python -m attest --db demo.db demo
python -m attest --db demo.db recheck --all
```

Expected output of the first:

```
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
```

---

# 5. Screen recording plan

## Panes to open before starting

- **Browser** at `http://127.0.0.1:8000`, zoomed to about 125%. Scroll so the
  `MODEL MOCK` and `STATE SIMULATED` badges stay visible in most frames — they do
  honesty work for free.
- **Terminal A — server pane.** Start it first. The banner is worth two seconds of
  B-roll:

  ```
  MODE   state=SIMULATED model=MOCK
  db     demo.db
  policy attest-default@v1+c21eed9764f6f018

  Attest UI on http://127.0.0.1:8000  (Ctrl-C to stop)
  offline: no credentials read, no network calls made
  ```

  Then leave it alone.
- **Terminal B — command pane**, large font (18pt or more), for shots 3, 6, 7 and 9.
  Clear between commands.

## Pre-positioning

- Pre-scroll the browser to the flip section before shot 4 so no hunting appears on
  camera.
- The draft textarea already contains the right sentence by default. **Do not retype
  it**, and say so on camera: it is the same string in both runs.
- Run `pytest` once off-camera first so import cost is warm.

## Live versus pre-recorded

- Shots 3, 6, 7 and 9 all complete in under a second. **Record them live.** Nothing
  here is slow enough to need faking.
- The full suite takes about 30 seconds. If you show it, speed-ramp the middle and
  land on `422 passed`. Do not cut straight to the last line — that looks edited.
- Everything else is instant.

## Coherence

Keep one continuous `demo.db` across the whole shoot, so the proof IDs shown passing
in shot 8 are the same ones failing in shot 10. Do not reset mid-video: a judge who
notices different proof IDs will assume the tamper was staged.

---

# 6. Best opening — first 15 seconds

**Frames**

| Time | Content |
|---|---|
| `0:00` | Black. White text, centred, 48pt: `This is our final attempt. Your 15% offer expires in 24 hours.` |
| `0:05` | Amber below it: `Is this true?` |
| `0:10` | Grey below that: `You cannot answer that from the sentence.` |

**Spoken**

> An AI wrote this message to a customer. Is it true? You can't tell. Not from the
> sentence. Every fact in it — final attempt, fifteen percent, twenty-four hours —
> lives somewhere else. In the merchant's database.

**Why this wins.** The judge understands the problem before the project is named, and
it reads perfectly with the sound off. No logo, no team introduction, no tech stack.

---

# 7. Best final 15 seconds

**Frames.** The identical message across the top; `SEND` and `BLOCK` side by side
beneath it. Hold four seconds. Fade to `ATTEST — Proof before send.`

**Spoken**

> Let the AI write the message. But the moment that message makes a factual promise to
> a customer, the AI should not be the thing that decides whether it's true. Attest
> makes that decision deterministic, recorded, and something anyone can recompute
> without asking us to be trusted.
>
> Same words. Different truth.

**Rejected alternatives and why**

| Candidate | Why cut |
|---|---|
| "Trust, but verify — deterministically." | Cliché. |
| "We made hallucination a type error." | False. The schema stops fabricated *structure*, not every false claim. |
| "The model proposes, the system disposes." | Clever, but a judge has to decode it. |

The chosen close contains no unsupported claim: "recompute" is exactly what
`recheck.py` does, and "without asking us to be trusted" is the honest form of the
replay property.

---

# 8. Claim guard — risk audit and evidence map

## 8.1 Every technical sentence, classified

| Sentence in the script | Class | Evidence |
|---|---|---|
| "An AI wrote this message to a customer." | ASSUMPTION | Framing device. In this demo the proposer is a fixture, disclosed at 4:06. |
| "Every fact in it lives somewhere else." | PROVEN | `EvidenceRef` resolves against snapshot records only |
| "Everything gold on this strip is deterministic code." | PROVEN | `tests/test_boundary.py::test_verify_imports_are_allowlisted`, `tests/test_boundary.py::test_adjudicator_runs_with_io_disabled` |
| "The schema has no field for a verdict." | PROVEN | `ProposedClaim` fields are `claim_id, kind, span_start, span_end, asserted, evidence` |
| "It is structurally unable to." | PROVEN | `extra="forbid"` plus `Literal` discriminators; live `REJECT` output; `tests/test_llm_adapter.py::test_production_schema_rejects_invalid_proposals` |
| "Same message. Byte-identical." | DEMONSTRATED | The page prints the shared draft; both runs post the same string |
| "The snapshot hashes differ." | DEMONSTRATED | `58d07e42…` versus `6b5579ba…`, observed live |
| "One field. Attempt index." | PROVEN | `tests/test_demo_beats.py::test_beat_a_snapshots_differ_in_exactly_one_field` |
| "`is_final_attempt`, supported to contradicted." | DEMONSTRATED | `tests/test_demo_beats.py::test_beat_a_state_flip` |
| "Coverage is computed by code that never sees the model's answer." | PROVEN | `find_spans(draft)` takes only the draft |
| "It does not catch a vaguer one like 'you qualify'." | **LIMITATION** | Stated in the `coverage.py` docstring |
| "Zero provider calls. Zero model calls." | PROVEN | `tests/test_gate.py::test_suppressed_request_touches_neither_provider_nor_model`, `tests/test_gate.py::test_cooldown_blocked_request_touches_neither` |
| "The gate denies before any state is fetched." | PROVEN | Control flow in `pipeline.evaluate`; `tests/test_gate.py::test_allowed_request_calls_provider_then_propose_exactly_once` |
| "Replay recomputes. No model. No network." | PROVEN | `recheck.py` recomputes five quantities; `tests/test_demo_beats.py::test_beat_d_replay_with_no_network`, `tests/test_state_provider.py::test_replay_does_not_invoke_the_provider` |
| "Ordinary SQL updates are refused outright." | PROVEN | `tests/test_storage.py::test_proof_is_append_only`, `tests/test_storage.py::test_snapshot_is_append_only`, `tests/test_storage.py::test_raw_sql_cannot_bypass_the_send_disposition_rule` |
| "Recomputed BLOCK, stored SEND." | DEMONSTRATED | Verbatim replay output; `tests/test_web.py::test_recheck_reports_real_failure_after_tampering` |
| "The exit code is one." | PROVEN | `tests/test_storage.py::test_replay_exits_non_zero_when_a_send_is_forged` |
| "That is tamper evidence, not tamper prevention." | **LIMITATION** | `scripts/tamper_demo.py` must `DROP TRIGGER` first |
| "The proposer is a deterministic fixture, not Claude." | **LIMITATION** | Mode banner reads `model=MOCK` |
| "Has never made a live model call." | **LIMITATION** | `tests/test_llm_adapter.py::test_adapter_modules_import_without_credentials_or_sdk` |
| "Nine of twelve field mappings unresolved." | **LIMITATION** | Counted from `REQUIRED_RESOURCE_MAPPING`; `tests/test_state_provider.py::test_razorpay_provider_does_not_pretend_to_be_integrated`, `tests/test_docs.py::test_razorpay_unresolved_count_matches_the_code` |
| "We make no accuracy claim at all." | **LIMITATION** | No results file exists in `killtest/` |
| "Something anyone can recompute without asking us to be trusted." | PROVEN | `recheck.py` runs offline from the database alone |
| "The UI computes nothing." | PROVEN | `tests/test_web.py::test_api_verify_matches_a_direct_evaluate_call`, `tests/test_web.py::test_server_calls_no_verification_primitive`, `tests/test_web.py::test_browser_never_computes_a_disposition` |

## 8.2 Claim guard — sentences written, then cut

| SAFE TO SAY | DO NOT SAY | WHY |
|---|---|---|
| "Replay detects the tampering class demonstrated here." | "Tamper-proof." / "Immutable audit log." | Ordinary SQL is blocked; file-level writes are not. The demo script drops a trigger to get in. |
| "Coverage catches numeric and temporal claims." | "Attest guarantees no false claim reaches a customer." | Coverage misses qualitative claims, and `UNVERIFIABLE` exists precisely because some claims cannot be settled. |
| "The state is a hand-written fixture, labelled SIMULATED." | "Verified against Razorpay's live state." | No live acquisition exists; `get_state` raises. |
| "The proof table is append-only, enforced by triggers." | "The audit log is immutable." | Append-only is not immutable. This phrasing had actually shipped in the UI and was removed. |
| "The policy document declares an attempt cap." | "NPCI compliant." | The rule is *named* `npci_attempt_cap`. A name is not a certification. |
| "A committed send consumes cooldown." | "Exactly-once delivery." | Attest never observes a transport; `tests/test_storage.py::test_send_disposition_alone_writes_no_send_log` |
| "Single connection, single writer, untested beyond that." | "Concurrency-safe." | No multi-writer safety is claimed or tested. |
| "422 offline tests exercise the deterministic core." | "Production-ready." | No live path is exercised by any test. |

## 8.3 Standing disclosures

These eight are served from `attest/web/server.py::LIMITATIONS` and rendered by the
page. The video must not contradict any of them:

1. The Anthropic adapter is implemented and unit-tested against a fake transport. No
   live model call has ever been made.
2. The Razorpay provider is a boundary skeleton. 9 of 12 field mappings are
   unresolved; it raises rather than fetching.
3. The frozen benchmark is unrun. No accuracy claim is made.
4. There is no real delivery transport. The sender is simulated.
5. No exactly-once delivery guarantee.
6. No concurrency or multi-writer safety guarantee.
7. No file-level tamper resistance. Ordinary SQL is blocked; a process that can write
   the database file can rewrite it.
8. Coverage catches numeric and temporal claims only. A silently omitted qualitative
   claim is not detected.
