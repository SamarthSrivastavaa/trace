"""Policy loading, validation and content identity.

A policy document is untrusted configuration. Every test below is a way an
invalid or hostile document could otherwise become live policy.
"""

import copy
import json

import pytest

from pramaan.policy.loader import (DEFAULT_POLICY_PATH, InvalidPolicy,
                                   PolicyNotFound, canonical_policy,
                                   load_default_policy, load_policy,
                                   parse_policy, policy_hash, policy_identity)
from pramaan.policy.schema import Stage

RAW = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))


def mutate(**changes):
    doc = copy.deepcopy(RAW)
    doc.update(changes)
    return doc


def with_rule(rule):
    doc = copy.deepcopy(RAW)
    doc["rules"] = [rule]
    return doc


# --- A. valid policy --------------------------------------------------------

def test_default_policy_loads():
    p = load_default_policy()
    assert [r.id for r in p.rules] == ["opt_out", "min_gap_between_sends",
                                       "npci_attempt_cap"]


def test_stage_classification_is_explicit():
    """The pre/post split is what makes zero-acquisition enforceable."""
    p = load_default_policy()
    assert {r.id for r in p.enabled_rules(Stage.PRE_STATE)} == {
        "opt_out", "min_gap_between_sends"}
    assert {r.id for r in p.enabled_rules(Stage.POST_STATE)} == {"npci_attempt_cap"}


def test_identity_is_deterministic():
    assert len({policy_hash(load_default_policy()) for _ in range(20)}) == 1


def test_identity_is_invariant_to_key_order():
    """Formatting-only change must not create a different policy."""
    def shuffle(o):
        if isinstance(o, dict):
            return {k: shuffle(o[k]) for k in reversed(list(o))}
        if isinstance(o, list):
            return [shuffle(x) for x in o]
        return o

    reformatted = shuffle(RAW)
    assert list(reformatted) != list(RAW)
    assert policy_hash(parse_policy(reformatted)) == policy_hash(load_default_policy())


def test_identity_changes_when_a_bound_changes():
    doc = copy.deepcopy(RAW)
    doc["rules"][1]["min_seconds_between_sends"] = 3600
    assert policy_hash(parse_policy(doc)) != policy_hash(load_default_policy())


def test_identity_changes_when_a_rule_is_disabled():
    doc = copy.deepcopy(RAW)
    doc["rules"][0]["enabled"] = False
    assert policy_hash(parse_policy(doc)) != policy_hash(load_default_policy())


def test_rule_order_is_semantic_and_changes_identity():
    """The gate returns on the FIRST matching deny, so order decides which
    reason_code is produced. Reordering is therefore a semantic change."""
    doc = copy.deepcopy(RAW)
    doc["rules"] = list(reversed(doc["rules"]))
    assert policy_hash(parse_policy(doc)) != policy_hash(load_default_policy())


def test_identity_label_is_bound_to_the_hash():
    p = load_default_policy()
    assert policy_hash(p)[:16] in policy_identity(p)


def test_canonical_policy_is_valid_json_and_reloadable():
    p = load_default_policy()
    assert policy_hash(parse_policy(json.loads(canonical_policy(p)))) == policy_hash(p)


# --- B. invalid policy ------------------------------------------------------

def test_unknown_top_level_key_rejected():
    with pytest.raises(InvalidPolicy):
        parse_policy(mutate(surprise=1))


def test_unknown_rule_key_rejected():
    r = copy.deepcopy(RAW["rules"][0]); r["surprise"] = 1
    with pytest.raises(InvalidPolicy):
        parse_policy(with_rule(r))


def test_unknown_rule_type_rejected():
    with pytest.raises(InvalidPolicy):
        parse_policy(with_rule({"type": "launch_missiles", "id": "x",
                                "stage": "pre_state", "enabled": True}))


def test_missing_required_field_rejected():
    with pytest.raises(InvalidPolicy):
        parse_policy(with_rule({"type": "cooldown", "id": "c",
                                "stage": "pre_state", "enabled": True}))


def test_bool_where_integer_expected_rejected():
    """True must not silently become a cooldown of 1 second."""
    with pytest.raises(InvalidPolicy):
        parse_policy(with_rule({"type": "cooldown", "id": "c",
                                "stage": "pre_state", "enabled": True,
                                "min_seconds_between_sends": True}))


def test_float_where_integer_expected_rejected():
    with pytest.raises(InvalidPolicy):
        parse_policy(with_rule({"type": "cooldown", "id": "c",
                                "stage": "pre_state", "enabled": True,
                                "min_seconds_between_sends": 1.5}))


def test_negative_and_zero_counts_rejected():
    for bad in (-1, 0):
        with pytest.raises(InvalidPolicy):
            parse_policy(with_rule({"type": "attempt_limit", "id": "a",
                                    "stage": "post_state", "enabled": True,
                                    "max_attempts": bad}))


def test_wrong_stage_for_rule_type_rejected():
    """attempt_limit needs authoritative state; declaring it pre_state would
    break the zero-acquisition guarantee, so the schema refuses it."""
    with pytest.raises(InvalidPolicy):
        parse_policy(with_rule({"type": "attempt_limit", "id": "a",
                                "stage": "pre_state", "enabled": True,
                                "max_attempts": 4}))


def test_duplicate_rule_ids_rejected():
    doc = copy.deepcopy(RAW)
    doc["rules"][1]["id"] = doc["rules"][0]["id"]
    with pytest.raises(InvalidPolicy):
        parse_policy(doc)


def test_contradictory_duplicate_rule_types_rejected():
    """Two cooldowns with different windows have no defined precedence."""
    doc = copy.deepcopy(RAW)
    second = copy.deepcopy(doc["rules"][1])
    second["id"] = "other_gap"
    second["min_seconds_between_sends"] = 60
    doc["rules"].append(second)
    with pytest.raises(InvalidPolicy):
        parse_policy(doc)


def test_empty_rule_list_rejected():
    with pytest.raises(InvalidPolicy):
        parse_policy(mutate(rules=[]))


def test_non_object_policy_rejected():
    for bad in ([], "policy", 3, None):
        with pytest.raises(InvalidPolicy):
            parse_policy(bad)


def test_malformed_json_rejected(tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(InvalidPolicy):
        load_policy(bad)


def test_missing_file_raises_not_found(tmp_path):
    with pytest.raises(PolicyNotFound):
        load_policy(tmp_path / "absent.json")


def test_path_traversal_is_refused(tmp_path):
    """Policy paths may come from configuration; ../../ must not resolve."""
    with pytest.raises(InvalidPolicy):
        load_policy("../../etc/passwd", base_dir=tmp_path)


def test_policy_cannot_execute_code():
    """No eval, no dynamic import: a rule type is a Literal, not a callable."""
    with pytest.raises(InvalidPolicy):
        parse_policy(with_rule({"type": "__import__('os').system",
                                "id": "x", "stage": "pre_state"}))
