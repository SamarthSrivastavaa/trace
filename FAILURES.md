# FAILURES

What actually went wrong while building Attest.

Every entry below happened. Nothing here is invented to look rigorous, and
nothing has been rewritten to make an earlier decision look smarter than it
was. Three of these were found by tests catching defects in my own code; two
were claims I had written down as true and later had to withdraw.

Each entry ends with the regression test that keeps it fixed.

---

## 1. The deterministic verifier could execute attacker code

**Assumption.** The first validator (`killtest/validator.py`) was the trusted
comparison path, so its inputs were safe.

**Test.** Passed it a crafted object with an overloaded `__eq__`.

**Result.**

```
>>> ATTACKER CODE EXECUTED inside the trusted comparison path
accepted=True  reason=ok - verdict recomputed from cited evidence
```

**What was wrong.** The validator compared arbitrary Python values. An object
with `__eq__` ran its own code *inside the trust boundary* and drove a false
claim to `SUPPORTED`. `isinstance(True, int)` is also `True`, so booleans were
smuggling through as integers.

**What changed.** The file was **deleted, not patched** — it also used dotted
string evidence paths, which is a fabricated-path and traversal surface. It was
replaced by a closed discriminated union where field names are `Literal`s, so a
non-existent field fails to parse. The adjudicator now asserts every compared
value is `int | str | bool | Decimal`.

**Evidence.** `tests/test_rules.py::test_crafted_object_cannot_reach_comparison`,
`test_snapshot_with_crafted_value_is_rejected`, and
`tests/test_repo_integrity.py::test_no_source_imports_the_retired_validator`
(parametrised over every source file, so its return is a build failure).

**Conclusion.** Path traversal and type confusion are now *unrepresentable*
rather than defended against.

---

## 2. Coverage had a total bypass

**Assumption.** Requiring an accepted finding to *overlap* a detected span was
enough to prove the model had adjudicated it.

**Test.** One finding spanning the entire draft.

**Result.** `4 spans found, 0 uncovered, passed=True`.

**What was wrong.** A single bogus span satisfied every token. This defeated
coverage completely — and coverage is the *only* defence against the model
silently omitting a claim.

**What changed.** Overlap → containment, plus a bound: a finding may be at most
3× the length of the token it covers. Matching is by span position, never by
value, so `"2 items, only 2 left"` needs two findings.

**Evidence.** `tests/test_coverage.py::test_whole_draft_span_cannot_cover_everything`,
`test_repeated_values_need_separate_findings`.

---

## 3. Unicode normalisation silently shifted every span offset

**Assumption.** NFC normalisation was a hashing concern only.

**Test.** The same visible text in NFD and precomposed form.

**Result.** `PERCENT` at offset 12 in one form, 11 in the other.

**What was wrong.** NFC changes string length. If the model computed spans on
one form while the lexer ran on another, coverage misaligned *silently* — a
merchant product name with a combining accent was enough.

**What changed.** One canonical NFC form established at intake, used by model
input, lexing, offsets and hashing alike. `require_normalised()` raises rather
than drifting.

**Evidence.** `tests/test_normalise.py::test_nfd_and_nfc_inputs_yield_identical_spans`,
plus `test_raw_nfd_and_nfc_offsets_actually_differ`, which proves the first test
is testing something real.

---

## 4. My own leakage check was statistically invalid

**Assumption.** A label-pure hash bucket in the benchmark dataset indicated
leakage.

**Test.** Ran the audit after an unrelated dataset fix.

**Result.** `FAIL — no hash-prefix bucket is label-pure (worst purity 100%)`.

**What was wrong.** **The check, not the data.** It bucketed 70 cases into 16
buckets (~4 each) and flagged any label-pure bucket of ≥4. At a 44% majority
label that fires by chance roughly **45% of the time**. Worse, `case_id` is a
SHA-1 of `message||state_key` — a pure function of the model's own input — so it
*cannot* leak anything the input lacks.

**What changed.** Replaced with a run-length test over id-sorted labels, which
detects the failure mode that would actually matter (ids assigned in label
order). **The dataset was not edited.** Editing clean data to satisfy a broken
test would have been the real error.

**Evidence.** `killtest/audit_dataset.py` check [4], with the miscalibration
documented in the source.

---

## 5. The architecture claim was untestable by the benchmark built to test it

**Assumption.** The paired-case dataset — same message, different state,
different correct label — would show whether deterministic verification beats
an LLM given the same state.

**Test.** Examined what the design can actually separate.

**Result.** It cannot separate them at all.

**What was wrong.** Paired cases isolate exactly one variable: *access to
state*. The text-only arm lacks it; both state-aware arms have it, byte-for-byte
identically. The instrument that decisively separates text-only from
state-aware is **structurally incapable** of separating the other two.

**What changed.** Two pipeline stages were deleted, along with a hash chain and
an entire evidence-path validation layer. The claim was re-specified: the
difference between "LLM with state" and Attest is not intelligence, it is the
**output contract** — a prose verdict is an assertion; a typed claim with an
evidence pointer is recomputable. Require the baseline to emit typed findings
and it *becomes* Attest.

**Conclusion.** The accuracy claim was dropped before any measurement existed
to support it.

---

## 6. "Reproducible" was two different claims, and one of them was false

**Assumption.** Attest is reproducible.

**Test.** Asked what exactly reproduces.

**Result.** Two claims had been conflated:

- **Audit determinism** — a *recorded* decision re-derives identically forever.
  True, architecturally guaranteed.
- **End-to-end determinism** — the same draft yields the same decision every
  run. **False.** Extraction is an LLM call.

**What was wrong.** Earlier documents compared "the baseline's verdicts are
unstable across repeats" against "the validator's re-derivation is
bit-identical". That pits the baseline's end-to-end variance against Attest's
*replay* determinism. Unfair, and withdrawn.

**What changed.** The claim was narrowed to audit determinism everywhere,
including the README. One genuinely good property survives: variance is
**asymmetric** — a dropped claim leaves an uncovered span, so the system
degrades toward `BLOCK`, never toward a wrongful send.

---

## 7. The architecture was not novel

**Assumption.** Typed claims validated deterministically was a differentiated
mechanism.

**Test.** Searched by mechanism rather than by name, before building further.

**Result.** **ProvenanceGuard** (arXiv 2606.18037, June 2026): a fail-closed
post-generation verification layer for MCP agents that decomposes answers into
atomic claims preserving exact values, routes them to source-specific evidence,
and runs a repair loop. Published three months earlier. The wider attribution
literature describes the pattern as the working default.

**What changed.** Novelty was re-scored 6.5 → 4.5 and the paper is cited in
README paragraph three, not an appendix. A separate planned feature —
"verified claims become binding commitments" — was killed the same day on
discovering AP2's Cart Mandate already is *"the merchant's formal commitment to
the specific terms of a transaction."*

**Conclusion.** Better to find this before building than to have a judge find
it after.

---

## 8. `temperature` would have killed the first live benchmark call

**Assumption.** The kill-test harness was ready to run.

**Test.** Checked the request parameters against current model behaviour.

**Result.** `claude-opus-5` **removed the sampling parameters**. Sending
`temperature` returns a 400.

**What was wrong.** `run_arms.py` passed `temperature=` on every call. The
first live run would have failed on every case in every arm, identically — and
would have looked like a transport problem rather than a request-shape bug.
`budget_tokens` is likewise rejected on this model.

**What changed.** No arm sends sampling parameters. The `--temperature` flag is
kept for compatibility and never put on the wire. The adapter sends no
`thinking` block.

**Evidence.** `tests/test_llm_adapter.py::test_request_params_omit_sampling_and_thinking_budget`.

---

## 9. Gate-denied evaluations were never persisted

**Assumption.** Every evaluation produces an audit record.

**Test.** A replay test on a suppressed customer.

**Result.** `prf_7cb1127879c6: no such proof`.

**What was wrong.** `_finish` had `if conn is not None and snap_hash:`. A gate
denial acquires no state, so `snap_hash` was `None` and the proof was silently
dropped. Exactly the decisions most worth auditing were the ones not recorded.

**What changed.** The proof is always persisted; only the *snapshot row* is
conditional. `snapshot_hash` became nullable — "no state acquired" is `NULL`,
not `""`, because an empty string is not a hash.

**Evidence.** `tests/test_gate.py::test_replay_reruns_the_gate_from_the_recorded_policy`.

---

## 10. Replay detected forged sends and exited 0 anyway

**Assumption.** Replay failed on structural inconsistency.

**Test.** Forged a `send_log` row against a `BLOCK` proof, then checked the exit
code — without a pipe.

**Result.** The failure was **printed**, and the process exited **0**.

**What was wrong.** Two things. The exit-code change had not applied to
`main()`. And my first check piped output through `head`, so `$?` reported
*head's* status — the bug was invisible behind my own verification.

**What changed.** `return 1 if (failed or not send_ok) else 0`, and both exit
codes are now asserted by subprocess tests rather than read by eye.

**Evidence.** `tests/test_storage.py::test_replay_exits_non_zero_when_a_send_is_forged`,
`test_replay_exits_zero_for_a_clean_lifecycle`.

**Conclusion.** A verification step that hides the thing it verifies is worse
than no verification step.

---

## 11. The benchmark measured a system that does not ship

**Assumption.** The kill-test harness exercised the production path.

**Test.** Grepped the harness for production adapter references, during the
pre-run audit and before any live call.

**Result.** **Zero** references to `ClaudeProposer`, `AnthropicTransport`,
`SYSTEM_PROMPT` or `extract_json_object`. The harness had its own prompt (2,577
chars vs production's 2,833, not identical), its own parser and its own model
constant.

**What was wrong.** B3 would have been measured through a lookalike. The result
would have described a system that does not exist, and no prompt identity could
have been honestly reported.

**What changed.** B3 now runs the production path exactly. The harness-local
prompt, parser and model constant are deleted, and `assert_b3_is_production()`
fails the run if that ever drifts — checked by object *identity*, since a copied
string would drift silently.

**Evidence.** `tests/test_killtest_harness.py::test_b3_prompt_is_the_production_prompt_object`,
`test_b3_gate_fails_if_the_prompt_drifts` (proving the assertion bites).

**Conclusion.** Caught during a pre-run audit, before spending anything.

---

## 12. Two fairness bugs in the benchmark, caught before running

**Assumption.** The competing arms received equivalent inputs.

**Test.** Reviewed arm inputs against the frozen dataset.

**Result.** Two defects, both of which would have silently rigged the result.

1. **Field-name mismatch.** B3's prompt names production fields
   (`flat_amount_minor`), but the runner showed it raw dataset JSON
   (`flat_amount`). B3 would have been penalised for a mismatch I created.
2. **Dropping `inventory` would have rigged it the other way.** The adapter
   discarded inventory because no `EvidenceRef` can cite it — but **9 dataset
   cases have gold labels that depend on it**. The competing arm would have
   answered `UNVERIFIABLE` where gold says `SUPPORTED`, losing points for *my
   schema's* limitation.

**What changed.** Both state-aware arms receive one identical adapted snapshot,
and inventory passes through. B3 now loses those cases *honestly*, because its
architecture genuinely cannot express the claim. That is a real limitation being
measured, not an artefact — and it is reported, not hidden.

**Evidence.** `tests/test_repo_integrity.py::test_adapter_preserves_inventory_for_arm_fairness`.

---

## 13. The frozen dataset mixes money units

**Assumption.** The benchmark dataset used consistent units.

**Test.** Cross-read the gold labels against the messages.

**Result.** `offers[].flat_amount: 500` means ₹500 (rupees), while
`payment.amount: 249900` and `cart.total: 499900` are paise. Inconsistent
*inside* the hash-frozen dataset.

**What changed.** Nothing in the dataset — it is frozen and pre-registered, and
editing it would void the freeze. The reconciliation lives in
`killtest/adapt.py`, documented, with the rupee→paise conversion applied only
where the labels prove it belongs.

**Evidence.** `tests/test_repo_integrity.py::test_adapter_converts_rupees_to_paise_for_flat_offers`,
`test_adapter_leaves_already_minor_units_alone`.

---

## 14. `Disposition.REWRITE` was a branch that could never execute

**Assumption.** The disposition enum reflected reachable states.

**Test.** Traced `decide()` against the database constraint.

**Result.** `decide()` never returned `REWRITE`, and the `proof` table's
`CHECK` constraint only permitted `SEND`, `BLOCK`, `ESCALATE`. The enum admitted
a value the database would have rejected.

**What changed.** Deleted. A fake branch is worse than a missing feature.

---

## Two smaller ones, for completeness

**Pydantic does not refuse `bool` → `int`.** A code comment I wrote asserted it
does. `{"kind": "count", "value": true}` was accepted as count `1`. Found by the
adversarial schema test, fixed with an explicit `type(v) is bool` guard —
`isinstance` is useless here.

**`status` crashed instead of reporting.** Selecting the live proposer without
credentials made `Attest.__init__` construct it eagerly and raise, so the one
command whose job is to say *"you are missing a credential"* died before
printing. Components now build lazily.

---

## What this list is

Fourteen entries, of which:

- **3** were defects the tests found in my own code (#1 reachable via the old
  prototype, #2, #3)
- **2** were checks or tests of mine that were themselves wrong (#4, #10)
- **3** were claims I had written down and had to withdraw (#5, #6, #7)
- **3** were caught in a pre-run audit before spending money (#8, #11, #12)

The pattern worth noting is #4 and #10: twice, the thing that failed was the
verification rather than the code. Distrusting your own tooling is harder than
debugging, and both times the tempting move — editing clean data, or believing a
piped exit code — would have been the actual error.
