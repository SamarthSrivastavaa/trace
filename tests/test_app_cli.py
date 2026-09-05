"""The composition root and the runnable entrypoint.

Two things defended here:

  1. The composition root COMPOSES. It must contain no rule, verdict, policy or
     persistence logic of its own - a second implementation of any of those
     would be a second trust boundary.
  2. Configuration holds NO SECRETS, so it cannot leak one through repr, logs,
     a manifest or a proof.

Everything runs offline with no credentials.
"""

import ast
import json
import pathlib
import subprocess
import sys

import pytest

from attest.app import Outcome, Attest, build_proposer, build_state_provider
from attest.config import (AppConfig, ConfigError, ProposerChoice,
                            StateProviderChoice)
from attest.core.verify.schema import Disposition
from attest.fixtures import scenarios as fx
from attest.storage import db

ROOT = pathlib.Path(__file__).resolve().parents[1]
T0 = "2026-09-04T10:00:00+00:00"
T1 = "2026-09-04T11:00:00+00:00"


@pytest.fixture()
def app(tmp_path):
    cfg = AppConfig(db_path=str(tmp_path / "app.db"))
    a = Attest(cfg)
    yield a
    a.close()


def cli(*args, cwd=ROOT, env_extra=None):
    """Run the CLI as a subprocess with every credential stripped."""
    import os
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "RAZORPAY_KEY_ID",
                        "RAZORPAY_KEY_SECRET", "ATTEST_PROPOSER",
                        "ATTEST_STATE_PROVIDER", "ATTEST_DB")}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "attest", *args],
                          capture_output=True, text=True, timeout=120,
                          cwd=str(cwd), env=env)


# --- configuration ----------------------------------------------------------

def test_default_config_is_fully_simulated():
    cfg = AppConfig()
    assert cfg.is_fully_simulated
    assert cfg.requires_credentials() == []
    assert "SIMULATED" in cfg.mode_label and "MOCK" in cfg.mode_label


def test_live_selectors_declare_their_credentials():
    cfg = AppConfig(state_provider=StateProviderChoice.RAZORPAY,
                    proposer=ProposerChoice.CLAUDE)
    assert set(cfg.requires_credentials()) == {
        "ANTHROPIC_API_KEY", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"}
    assert not cfg.is_fully_simulated
    assert "LIVE" in cfg.mode_label


def test_config_holds_no_secret_even_when_env_is_set(monkeypatch):
    """The whole point: there is nothing in this object to redact."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET123")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp-SECRET456")
    monkeypatch.setenv("ATTEST_PROPOSER", "claude")
    cfg = AppConfig.from_env()
    blob = repr(cfg) + json.dumps(cfg.__dict__, default=str)
    assert "SECRET123" not in blob and "SECRET456" not in blob
    assert cfg.proposer is ProposerChoice.CLAUDE


def test_selecting_a_live_component_does_not_read_a_credential(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = AppConfig.from_env(proposer="claude")     # must not raise
    assert cfg.missing_credentials() == ["ANTHROPIC_API_KEY"]


def test_invalid_selector_is_rejected():
    with pytest.raises(ConfigError):
        AppConfig.from_env(proposer="gpt")
    with pytest.raises(ConfigError):
        AppConfig.from_env(state_provider="stripe")


def test_missing_policy_file_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        AppConfig.from_env(policy_path=str(tmp_path / "nope.json"))


def test_env_selects_components(monkeypatch):
    monkeypatch.setenv("ATTEST_STATE_PROVIDER", "fixture")
    monkeypatch.setenv("ATTEST_PROPOSER", "fixture")
    monkeypatch.setenv("ATTEST_DB", "custom.db")
    cfg = AppConfig.from_env()
    assert cfg.db_path == "custom.db" and cfg.is_fully_simulated


# --- component construction -------------------------------------------------

def test_fixture_components_need_no_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = AppConfig()
    assert build_state_provider(cfg).name == "fixture"
    assert callable(build_proposer(cfg))


def test_live_proposer_construction_fails_typed_without_credentials(monkeypatch):
    from attest.llm.errors import ProposerNotConfigured
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProposerNotConfigured):
        build_proposer(AppConfig(proposer=ProposerChoice.CLAUDE))


def test_live_state_provider_construction_fails_typed_without_credentials(monkeypatch):
    from attest.state.errors import ProviderNotConfigured
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    with pytest.raises(ProviderNotConfigured):
        build_state_provider(AppConfig(state_provider=StateProviderChoice.RAZORPAY))


# --- the chain --------------------------------------------------------------

def test_process_runs_the_chain_and_returns_a_typed_outcome(app):
    o = app.process(fx.DRAFT, "m", "alice", "final_attempt", now=T0)
    assert isinstance(o, Outcome)
    assert o.disposition is Disposition.SEND
    assert o.gate_reason == "ALLOWED"
    assert o.state_source == "SIMULATED"
    assert o.proof_id.startswith("prf_") and o.snapshot_hash


def test_evaluate_alone_does_not_deliver(app):
    """SEND is a decision; it is not a delivery."""
    o = app.process(fx.DRAFT, "m", "alice", "final_attempt", now=T0)
    assert o.commit_status == "not_attempted"
    assert o.sent is False
    assert db.all_send_rows(app.conn) == []


def test_deliver_true_commits_and_consumes_cooldown(app):
    o = app.process(fx.DRAFT, "m", "bob", "final_attempt", now=T0, deliver=True)
    assert o.commit_status == "created" and o.sent
    assert len(db.all_send_rows(app.conn)) == 1
    later = app.process(fx.DRAFT, "m", "bob", "final_attempt", now=T1)
    assert later.disposition is Disposition.BLOCK
    assert later.gate_reason == "COOLDOWN_NOT_ELAPSED"


def test_state_flip_through_the_composition_root(app):
    a = app.process(fx.DRAFT, "m", "c1", "final_attempt", now=T0)
    b = app.process(fx.DRAFT, "m", "c2", "first_attempt", now=T0)
    assert (a.disposition, b.disposition) == (Disposition.SEND, Disposition.BLOCK)


def test_suppressed_customer_denied_before_acquisition(app):
    app.suppress("m", "gone")
    o = app.process(fx.DRAFT, "m", "gone", "final_attempt", now=T0)
    assert o.disposition is Disposition.BLOCK
    assert o.gate_reason == "CUSTOMER_SUPPRESSED"
    assert o.snapshot_hash is None, "state was acquired for a gated request"


def test_blocked_proof_cannot_be_delivered(app):
    o = app.process(fx.DRAFT, "m", "c3", "first_attempt", now=T0, deliver=True)
    assert o.disposition is Disposition.BLOCK
    assert o.commit_status == "not_approved"
    assert db.all_send_rows(app.conn) == []


# --- architecture: the root composes, it does not decide -------------------

def _code(path: str) -> str:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _called_names(path: str) -> set[str]:
    """Function names actually CALLED in a module.

    A substring scan is wrong here: it flagged `snapshot_hash` as a dataclass
    FIELD carrying a value, and `adjudicate` inside the English word
    "un-adjudicated" in a user-facing message. Carrying a verdict is composing;
    computing one is not.
    """
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


@pytest.mark.parametrize("path", ["attest/app.py", "attest/cli.py"])
def test_composition_layer_calls_no_verification_primitive(path):
    called = _called_names(path)
    for forbidden in ("adjudicate", "adjudicate_all", "find_spans",
                      "canonicalise", "snapshot_hash", "content_hash",
                      "evaluate_pre_state", "evaluate_post_state",
                      "put_proof", "put_snapshot", "commit_send"):
        assert forbidden not in called, f"{path} calls {forbidden}()"


@pytest.mark.parametrize("path", ["attest/app.py", "attest/cli.py"])
def test_composition_layer_writes_no_sql(path):
    assert "INSERT INTO" not in _code(path)
    assert "UPDATE " not in _code(path)


def test_cli_delegates_replay_rather_than_reimplementing_it():
    code = _code("attest/cli.py")
    assert "recheck.main" in code
    for forbidden in ("recheck_one", "check_send_log"):
        assert forbidden not in code, f"cli.py reimplements {forbidden}"


def test_config_module_reads_no_secret():
    """It may read selector env vars, never a credential."""
    src = (ROOT / "attest" / "config.py").read_text(encoding="utf-8")
    for secret in ("ANTHROPIC_API_KEY\")", "RAZORPAY_KEY_ID\")",
                   "RAZORPAY_KEY_SECRET\")"):
        assert f"environ.get({secret}" not in src, \
            "config read a credential; it must only name them"


# --- CLI (subprocess, credentials stripped) --------------------------------

def test_cli_status_runs_offline(tmp_path):
    r = cli("--db", str(tmp_path / "c.db"), "status")
    assert r.returncode == 0, r.stderr
    assert "state=SIMULATED" in r.stdout and "model=MOCK" in r.stdout
    assert "credentials required by this configuration: none" in r.stdout


def test_cli_demo_shows_all_beats(tmp_path):
    r = cli("--db", str(tmp_path / "d.db"), "demo")
    assert r.returncode == 0, r.stderr
    for expected in ("final_attempt  -> SEND", "first_attempt  -> BLOCK",
                     "BEAT 2", "-> ESCALATE", "coverage_passed=False",
                     "deliver + commit  -> created", "COOLDOWN_NOT_ELAPSED"):
        assert expected in r.stdout, f"demo missing {expected!r}\n{r.stdout}"


def test_cli_evaluate_then_recheck(tmp_path):
    dbp = str(tmp_path / "e.db")
    r = cli("--db", dbp, "evaluate", "--draft", fx.DRAFT, "--customer", "alice",
            "--scenario", "final_attempt", "--now", T0)
    assert r.returncode == 0, r.stderr
    assert "disposition   SEND" in r.stdout
    rr = cli("--db", dbp, "recheck", "--all")
    assert rr.returncode == 0, rr.stdout + rr.stderr
    assert "re-verified" in rr.stdout


def test_cli_warns_when_a_live_selector_lacks_credentials(tmp_path):
    r = cli("--db", str(tmp_path / "w.db"), "--proposer", "claude", "status")
    assert "WARNING missing credentials: ANTHROPIC_API_KEY" in r.stdout
    assert "model=LIVE" in r.stdout


def test_cli_rejects_an_unknown_selector(tmp_path):
    r = cli("--db", str(tmp_path / "z.db"), "--proposer", "gpt", "status")
    assert r.returncode != 0
    assert "invalid choice" in (r.stderr + r.stdout)


def test_cli_unknown_proof_exits_non_zero(tmp_path):
    r = cli("--db", str(tmp_path / "p.db"), "proof", "prf_nope")
    assert r.returncode == 1 and "no such proof" in r.stdout


def test_cli_never_prints_a_credential(tmp_path):
    r = cli("--db", str(tmp_path / "s.db"), "--proposer", "claude", "status",
            env_extra={"ANTHROPIC_API_KEY": "sk-ant-SUPERSECRET"})
    assert "SUPERSECRET" not in r.stdout and "SUPERSECRET" not in r.stderr


def test_cli_send_records_a_send_and_second_call_is_gated(tmp_path):
    dbp = str(tmp_path / "snd.db")
    first = cli("--db", dbp, "send", "--draft", fx.DRAFT, "--customer", "carol",
                "--scenario", "final_attempt", "--now", T0)
    assert "delivery      created" in first.stdout, first.stdout
    second = cli("--db", dbp, "evaluate", "--draft", fx.DRAFT,
                 "--customer", "carol", "--scenario", "final_attempt",
                 "--now", T1)
    assert "COOLDOWN_NOT_ELAPSED" in second.stdout
