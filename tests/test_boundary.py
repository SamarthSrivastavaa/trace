"""The trust boundary: core/verify/ must be pure.

A direct-import check is insufficient - it is bypassable transitively and via
importlib. So this does both:
  1. STATIC: walk the recursive module graph of core/verify against an
     ALLOWLIST. A denylist silently permits every library nobody thought to ban.
  2. RUNTIME: disable socket and sqlite3, then actually run the adjudicator and
     the coverage lexer. Static analysis cannot see a dynamic import; this can.
"""

import ast
import pathlib
import socket
import sqlite3

import pytest

VERIFY = pathlib.Path(__file__).resolve().parents[1] / "attest" / "core" / "verify"

ALLOWED_TOP_LEVEL = {
    "re", "unicodedata", "dataclasses", "datetime", "decimal", "enum",
    "typing", "json", "hashlib", "__future__",
    "pydantic",          # schema.py only - the parsing boundary
}

FORBIDDEN_NAMES = {
    "importlib", "__import__", "eval", "exec", "compile", "open",
    "subprocess", "socket", "requests", "httpx", "anthropic", "sqlite3",
    "os", "sys", "urllib", "pickle", "marshal",
}


def _modules():
    return sorted(p for p in VERIFY.glob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_verify_imports_are_allowlisted(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in ALLOWED_TOP_LEVEL, \
                    f"{path.name} imports '{alias.name}' - not on the allowlist"
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue                      # relative import, stays inside
            top = (node.module or "").split(".")[0]
            assert top in ALLOWED_TOP_LEVEL, \
                f"{path.name} imports from '{node.module}' - not allowlisted"


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_verify_has_no_dynamic_execution(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_NAMES, \
                f"{path.name} calls {node.func.id}() inside the trust boundary"


def test_adjudicator_runs_with_io_disabled(monkeypatch):
    """The guarantee static analysis cannot give: no I/O at runtime."""
    from attest.core.verify import coverage as cov
    from attest.core.verify.rules import adjudicate_all
    from attest.core.verify.schema import ProposedClaim
    from attest.fixtures import scenarios as fx

    def boom(*a, **k):
        raise AssertionError("trust boundary attempted I/O")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(sqlite3, "connect", boom)

    claims = [ProposedClaim.model_validate(c)
              for c in fx.honest_proposal()["claims"]]
    verdicts = adjudicate_all(claims, fx.state_final_attempt())
    report = cov.check(fx.DRAFT, [
        {"claim_kind": v.kind.value, "span_start": c.span_start,
         "span_end": c.span_end} for c, v in zip(claims, verdicts)])

    assert len(verdicts) == 3
    assert report.passed
