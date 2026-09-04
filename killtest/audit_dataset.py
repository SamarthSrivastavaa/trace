"""
Phase 4 fairness / degeneracy audit. Run BEFORE any arm is executed.

Every check here is a way the experiment could be rigged in Pramaan's favour.
A dataset that fails these makes all downstream numbers worthless.
"""

import collections
import hashlib
import json
import pathlib

D = pathlib.Path(__file__).parent
cases = json.loads((D / "dataset.json").read_text(encoding="utf-8"))
LABELS = ["SUPPORTED", "CONTRADICTED", "UNVERIFIABLE"]

fails, warns = [], []


def check(ok, msg, hard=True):
    if ok:
        print(f"  PASS  {msg}")
    else:
        print(f"  {'FAIL' if hard else 'WARN'}  {msg}")
        (fails if hard else warns).append(msg)


print(f"\nDATASET  n={len(cases)}  sha256={hashlib.sha256(json.dumps(cases, indent=2, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}...")

# --- 1. label balance -------------------------------------------------------
dist = collections.Counter(c["label"] for c in cases)
print("\n[1] LABEL BALANCE")
for l in LABELS:
    print(f"      {l:<14} {dist[l]:>3}  ({dist[l]/len(cases):.0%})")
check(min(dist[l] for l in LABELS) >= 0.15 * len(cases),
      "no label below 15% (majority-class baseline stays weak)")
maj = max(dist.values()) / len(cases)
print(f"      majority-class baseline accuracy = {maj:.1%}")

# --- 2. constant-label categories ------------------------------------------
print("\n[2] CONSTANT-LABEL CATEGORIES (claim_type -> label)")
bytype = collections.defaultdict(collections.Counter)
for c in cases:
    for t in c["claim_types"]:
        bytype[t][c["label"]] += 1
const = [t for t, ct in bytype.items() if len(ct) == 1 and sum(ct.values()) > 2]
for t, ct in sorted(bytype.items()):
    print(f"      {t:<26} {dict(ct)}")
check(not const, f"no claim_type is constant-label (offenders: {const})")

# --- 3. state_key leakage ---------------------------------------------------
print("\n[3] STATE-KEY LEAKAGE (does state alone determine the label?)")
bystate = collections.defaultdict(collections.Counter)
for c in cases:
    bystate[c["state_key"]][c["label"]] += 1
multi = [s for s, ct in bystate.items() if sum(ct.values()) > 1]
deterministic = [s for s in multi if len(bystate[s]) == 1]
print(f"      state keys used >1x: {len(multi)}   of those single-label: {len(deterministic)}")
check(len(deterministic) <= len(multi) * 0.5,
      "state key alone does not determine label for most reused states")

# --- 4. case_id cannot predict label ---------------------------------------
# NOTE: an earlier version of this check bucketed by hash prefix and flagged any
# label-pure bucket of >=4. With 70 cases over 16 buckets and a 44% majority
# label that fires ~45% of the time by chance - it was measuring noise, not
# leakage. case_id is sha1(message||state_key), a pure function of the model's
# own input, so it cannot carry information the input lacks. The real failure
# mode is IDs assigned in label order (e.g. all SUPPORTED first), so test that.
print("\n[4] ID PREDICTABILITY")
ordered = sorted(cases, key=lambda c: c["case_id"])
runs = 1
for a, b in zip(ordered, ordered[1:]):
    if a["label"] != b["label"]:
        runs += 1
# Under random ordering the expected number of runs is high; label-sorted data
# collapses to ~3 runs (one per label).
print(f"      label runs across id-sorted order: {runs} (label-sorted would be ~3)")
check(runs >= 20, f"labels are not ordered by case_id (runs={runs})")
buckets = collections.defaultdict(collections.Counter)
for c in cases:
    buckets[c["case_id"][2]][c["label"]] += 1
big = [ct for ct in buckets.values() if sum(ct.values()) >= 8]
worst = max((max(ct.values()) / sum(ct.values())) for ct in big) if big else 0.0
check(worst < 0.95, f"no adequately-sized hash bucket is label-pure (worst {worst:.0%}, n_buckets={len(big)})")

# --- 5. duplicates ----------------------------------------------------------
print("\n[5] DUPLICATE CASES")
seen = collections.Counter((c["message"], c["state_key"]) for c in cases)
dupes = [k for k, v in seen.items() if v > 1]
check(not dupes, f"no duplicate (message, state) pairs ({len(dupes)} found)")

# --- 6. pair integrity ------------------------------------------------------
print("\n[6] PAIR INTEGRITY  (the heart of the experiment)")
pairs = collections.defaultdict(list)
for c in cases:
    if c["pair_id"]:
        pairs[c["pair_id"]].append(c)
bad_text = [p for p, cs in pairs.items() if len({c["message"] for c in cs}) != 1]
bad_label = [p for p, cs in pairs.items() if len({c["label"] for c in cs}) != 2]
bad_size = [p for p, cs in pairs.items() if len(cs) != 2]
bad_split = [p for p, cs in pairs.items() if len({c["split"] for c in cs}) != 1]
print(f"      pairs: {len(pairs)}   paired cases: {sum(len(v) for v in pairs.values())}")
check(not bad_size, "every pair has exactly 2 members")
check(not bad_text, "paired messages are byte-identical")
check(not bad_label, "paired labels differ")
check(not bad_split, "no pair straddles the dev/held-out split")

# --- 7. split -------------------------------------------------------------
print("\n[7] SPLIT")
sp = collections.Counter(c["split"] for c in cases)
print(f"      dev={sp['dev']}  heldout={sp['heldout']}")
hl = collections.Counter(c["label"] for c in cases if c["split"] == "heldout")
print(f"      heldout labels: {dict(hl)}")
check(len(hl) == 3, "held-out split contains all three labels")
check(sp["heldout"] >= 25, "held-out split is at least 25 cases")

# --- 8. THE CEILING FOR ANY TEXT-ONLY SYSTEM -------------------------------
print("\n[8] TEXT-ONLY CEILING  (this is a proof, not a measurement)")
bymsg = collections.defaultdict(set)
for c in cases:
    bymsg[c["message"]].add(c["label"])
ambiguous = {m for m, ls in bymsg.items() if len(ls) > 1}
amb_cases = [c for c in cases if c["message"] in ambiguous]
print(f"      distinct messages: {len(bymsg)}")
print(f"      messages with >1 correct label depending on state: {len(ambiguous)}")
print(f"      cases affected: {len(amb_cases)} of {len(cases)}")
# A text-only function f(message) returns ONE label per message. For an
# ambiguous message with k cases spread over its labels, the best any such
# function can do is pick the most common label for that message.
best = 0
for m in bymsg:
    grp = [c for c in cases if c["message"] == m]
    best += max(collections.Counter(c["label"] for c in grp).values())
print(f"      => BEST POSSIBLE text-only accuracy on full set: {best/len(cases):.1%}")
hgrp = [c for c in cases if c["split"] == "heldout"]
hbest = 0
for m in {c["message"] for c in hgrp}:
    grp = [c for c in hgrp if c["message"] == m]
    hbest += max(collections.Counter(c["label"] for c in grp).values())
print(f"      => BEST POSSIBLE text-only accuracy on HELD-OUT:  {hbest/len(hgrp):.1%}")
pairs_only = [c for c in hgrp if c["pair_id"]]
print(f"      => BEST POSSIBLE text-only accuracy on HELD-OUT PAIRS: 50.0%  (n={len(pairs_only)})")
check(best / len(cases) < 0.85, "text-only is provably capped well below ceiling")

# --- summary ---------------------------------------------------------------
print("\n" + "=" * 62)
print(f"HARD FAILURES: {len(fails)}   WARNINGS: {len(warns)}")
for f in fails:
    print(f"  FAIL {f}")
for w in warns:
    print(f"  WARN {w}")
print("=" * 62)
