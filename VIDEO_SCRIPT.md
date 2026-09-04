# Video script — Pramaan (~5:00)

Read this word for word. Every technical sentence maps to code or a test in the
Claim Evidence Map at the end.

**Say `model=MOCK` out loud when the banner appears.** The demo uses a
deterministic mock proposer, and pretending otherwise would be the one
dishonest thing in an otherwise honest submission.

---

## 0:00 – 0:25 · Hook

**On screen:** a single sentence in a text editor.

> "This is our final attempt. Your 15% offer expires in 24 hours."

**Narration:**

"Here's a message an AI agent wants to send a customer. Is it true?

You can't tell. Nobody can. Not from the text.

If this really is the fourth of four retry attempts, it's a legitimate notice.
If it's the first, the same sentence is a fabricated deadline — which under
India's dark-pattern guidelines is an enumerated offence, currently being fined.

Same words. Different truth. The difference isn't in the sentence — it's in the
merchant's database."

---

## 0:25 – 0:55 · The core idea

**On screen:** `pramaan/core/verify/schema.py`, `ProposedClaim` fields visible.

**Narration:**

"That's what Pramaan is for. It sits between an AI agent and the customer.

The model proposes what a message claims. It does not get to decide whether
those claims are true.

Look at the type the model has to answer in. It has a claim kind, a text span,
an asserted value, and a pointer to the record that settles it. There is no
status field. No verdict. No send-or-block.

The model literally cannot express a decision. That's not a rule I wrote in a
prompt and hoped it followed — it's a shape it can't fill in."

---

## 0:55 – 1:20 · Architecture in one breath

**On screen:** the architecture block from README.md.

**Narration:**

"The flow is: freeze the merchant's state and hash it. Run a policy gate before
anything expensive. Make one model call for claims only. Then deterministic code
resolves each claim against that frozen snapshot, a separate pass checks nothing
was silently left out, and only then is a disposition computed.

Authoritative snapshot, plus explicit claims, plus deterministic rules, equals
the decision. The model contributes to the middle term and nothing else."

---

## 1:20 – 2:30 · The lifecycle, live

**Command:** `python -m pramaan --db demo.db demo`

**Narration:**

"Everything you're about to see runs offline. No API key, no Razorpay
credentials, no network. And note the banner — `model=MOCK`. The proposer here
is a deterministic fixture, not Claude. I'll come back to that.

Beat one. Same message, twice. The only thing I change is one field of
authoritative state: attempt index four-of-four, then one-of-four. SEND, then
BLOCK. The text never changed.

Beat two. The proposer cites an offer id that looks perfectly well-formed but
isn't in the snapshot. It doesn't become supported — it escalates, because a
citation to a record that doesn't exist is a malformed citation, not an
unverifiable claim. Those route differently on purpose.

Beat three. The proposer silently drops one claim — it just doesn't mention the
deadline. Nothing to validate, because there's no finding to check. A separate
pass lexes the original draft and notices an un-adjudicated numeric span, and
blocks. That's the failure mode I'd have missed if I'd only validated what the
model chose to tell me.

And the lifecycle at the bottom: an approved evaluation writes no send record.
Only a committed successful delivery does. Then the same customer, an hour
later, is blocked by cooldown. Approval is not delivery."

---

## 2:30 – 3:05 · What happens before the model

**Command:** `python -m pytest tests/test_gate.py -k "touches_neither or calls_provider_then_propose" -v --no-header`

**Narration:**

"The policy gate runs before state acquisition and before the model. When it
denies a request, I claim it costs zero provider calls and zero model calls.

That's not documentation, it's a recorded call sequence. A suppressed customer:
empty. A cooldown-blocked customer: empty. And the first test is the control —
an allowed request, provider once, proposer once, in that order. Without that
one, the other two could pass just because nothing was wired up.

The policy itself is a JSON document with a content hash. Change the cooldown
window in data, and behaviour changes with no code change — and the proof
records which policy version decided."

---

## 3:05 – 4:00 · Proof, replay, tampering

**Commands:** `recheck --all`, then `tamper_demo.py`, then `recheck --all`

**Narration:**

"Every decision is stored as a proof. Let me re-verify all of them.

Seven of seven recomputed — snapshot hash, adjudication, coverage, disposition —
with no model calls and no network. It doesn't replay the stored answer; it
recomputes it and compares. Replaying the answer would prove nothing.

Now let me attack it. This script changes exactly one field inside one stored
snapshot. Note it has to drop a database trigger first — ordinary SQL is
refused.

Replay again. Three independent mismatches from one edited field, and it names
the flip: what was recorded as SEND now recomputes as BLOCK. Exit code one.

I want to be precise about what that is. This is tamper *evidence*, not tamper
*proofing*. Anyone who can write the file can rewrite it. What they can't do is
make the record stay internally consistent."

---

## 4:00 – 4:30 · Why the model isn't trusted

**Command:** `python -m pytest tests/test_rules.py -k "crafted or absent_record" -v --no-header`

**Narration:**

"One more, because this is the part I got wrong first.

An earlier version of my verifier compared arbitrary Python values. I fed it an
object with a custom equality method, and it executed the attacker's code inside
the trusted comparison path — and returned SUPPORTED. That's failure number one
in FAILURES.md.

I deleted that file rather than patching it. Now the comparison path accepts
primitives only, and evidence pointers are a closed union where field names are
literal types — so a fabricated field name doesn't get rejected, it fails to
parse. The attack became unrepresentable rather than defended against."

---

## 4:30 – 5:00 · Honest limitations, and close

**On screen:** the "What Pramaan does NOT prove" section of README.md.

**Narration:**

"So what's actually missing.

I have never made a live model call. The Anthropic adapter is built and tested
against a fake transport, and the benchmark is frozen and ready — but I haven't
spent the budget or seen a result, so I'm making no accuracy claim at all.

Razorpay acquisition is a boundary skeleton. Eight of twelve field mappings are
unresolved, and I left them as TODOs rather than guessing endpoint shapes and
shipping something that looks finished and fails on first contact.

And the biggest hole in the design itself: coverage catches numeric and temporal
claims. A silently omitted qualitative claim — 'you qualify', 'exclusive to you'
— still gets through.

What I'll stand behind is narrow and I think it's the right narrow thing. This
claim was, or was not, supported by this authoritative state, at this recorded
snapshot — and you can check that yourself, offline, without trusting me or
re-running the model."

---

# CLAIM EVIDENCE MAP

| Script claim | Evidence | Command / test |
|---|---|---|
| "The model literally cannot express a decision" | `ProposedClaim` has fields `claim_id, kind, span_start, span_end, asserted, evidence` — no `status` | `pramaan/core/verify/schema.py`; `tests/test_llm_adapter.py::test_production_schema_rejects_invalid_proposals` (model-issued verdict rejected) |
| "Same message, one state field, SEND then BLOCK" | Demo beat 1 | `python -m pramaan --db demo.db demo`; `tests/test_demo_beats.py::test_beat_a_state_flip`, `test_beat_a_snapshots_differ_in_exactly_one_field` |
| "A nonexistent offer id escalates rather than becoming supported" | `EVIDENCE_ABSENT` → MALFORMED → ESCALATE | `tests/test_demo_beats.py::test_beat_b_forged_evidence_cannot_be_supported` |
| "A forged citation can't satisfy coverage either" | Coverage consumes accepted findings only | `tests/test_demo_beats.py::test_beat_b_forged_finding_cannot_satisfy_coverage` |
| "A silently dropped claim is caught by a separate pass" | Coverage lexes the draft independently | `tests/test_demo_beats.py::test_beat_c_silent_omission_blocks` |
| "Approval is not delivery" | `SEND` writes no `send_log` row | `tests/test_storage.py::test_send_disposition_alone_writes_no_send_log`, `test_approved_but_undelivered_does_not_consume_cooldown` |
| "A committed send consumes cooldown" | Full lifecycle | `tests/test_storage.py::test_cooldown_lifecycle_end_to_end` |
| "Gated requests cost zero provider and zero model calls" | Recorded call sequence, with an allowed control | `tests/test_gate.py::test_suppressed_request_touches_neither_provider_nor_model`, `test_cooldown_blocked_request_touches_neither`, `test_allowed_request_calls_provider_then_propose_exactly_once` |
| "Policy is data; change the window, behaviour changes" | `default_policy.json` + content hash | `tests/test_gate.py::test_changing_the_window_in_policy_data_changes_behaviour`; `tests/test_policy.py::test_identity_changes_when_a_bound_changes` |
| "Replay recomputes, it doesn't replay the answer" | `recheck.py` re-runs adjudicator, coverage, disposition | `python -m pramaan --db demo.db recheck --all`; `tests/test_demo_beats.py::test_beat_d_replay_with_no_network` |
| "No model calls and no network during replay" | Socket blocked in test | `tests/test_demo_beats.py::test_beat_d_replay_with_no_network`; `tests/test_state_provider.py::test_replay_does_not_invoke_the_provider` |
| "One edited field → three mismatches → exit 1" | Tamper run | `python scripts/tamper_demo.py demo.db`; `tests/test_storage.py::test_replay_exits_non_zero_when_a_send_is_forged` |
| "Ordinary SQL is refused" | Append-only triggers | `tests/test_storage.py::test_proof_is_append_only`, `test_snapshot_is_append_only`, `test_raw_sql_cannot_bypass_the_send_disposition_rule` |
| "A crafted `__eq__` executed inside the comparison path" | Reproduced, then the file was deleted | `FAILURES.md` #1; `tests/test_rules.py::test_crafted_object_cannot_reach_comparison` |
| "Field names are literal types, so a fabricated field fails to parse" | Closed discriminated union | `tests/test_llm_adapter.py::test_production_schema_rejects_invalid_proposals[invented field]` |
| "I have never made a live model call" | No credential anywhere; adapter tested via fake transport | `tests/test_llm_adapter.py::test_adapter_modules_import_without_credentials_or_sdk` |
| "Razorpay is a skeleton, 8 of 12 mappings unresolved" | `REQUIRED_RESOURCE_MAPPING` | `pramaan/integrations/razorpay/provider.py`; `tests/test_state_provider.py::test_razorpay_provider_does_not_pretend_to_be_integrated` |
| "Coverage catches numeric and temporal claims only" | Documented boundary | `README.md` Limitations; `pramaan/core/verify/coverage.py` docstring |
| "You can check it yourself, offline" | Whole demo runs credential-free | `tests/test_docs.py::test_readme_commands_run` |

## Verified wording note

The submission brief proposed this sentence:

> "Pramaan does not ask an LLM to be the trusted decision-maker. It uses model
> output as structured proposals that pass through explicit deterministic
> verification against an authoritative snapshot before a final disposition is
> produced."

**Checked against the code: accurate.** `ProposedClaim` has no `status` field;
`Verdict` is produced only by `core.verify.rules.adjudicate`; `Disposition` only
by `core.pipeline.decide(verdicts, coverage_report)`, neither of which takes
model output directly.

**One caveat that must be said aloud:** in this demo the proposer is
`mock_model`, a deterministic fixture. The architecture is what's being shown,
exercised by a mock — not an LLM in the loop.
