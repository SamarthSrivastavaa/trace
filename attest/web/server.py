"""Thin HTTP boundary over the existing application.

WHAT THIS MODULE MAY DO
    accept input, build existing application inputs, invoke existing
    application functions, serialise what they returned, read persisted
    artifacts, invoke the existing replay implementation.

WHAT IT MAY NOT DO
    decide anything. There is no verdict comparison, no disposition rule, no
    policy evaluation, no coverage computation and no hashing in this file.
    Every value it returns was produced by attest.app.Attest.evaluate() or
    read back from storage. tests/test_web.py enforces this by AST.

Standard library only - no FastAPI, no framework, no new dependency. A local
single-user demo does not need one, and this project's credibility rests on
running offline on pydantic + pytest alone.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ..app import Attest
from ..config import AppConfig
from ..state.fixture import FixtureStateProvider, RecordingProvider
from ..storage import db

INDEX = Path(__file__).parent / "index.html"

# ONE authoritative source for the limitation disclosures. The UI renders this
# verbatim; nothing restates it. tests/test_docs.py cross-checks it against
# README so the two cannot drift into disagreeing.
LIMITATIONS = {
    "mode": {
        "model": "MOCK",
        "state": "SIMULATED",
        "note": "The offline demo runs a deterministic mock proposer over "
                "hand-written fixture state. No LLM is in the loop here.",
    },
    "not_proven": [
        "The Anthropic adapter is implemented and unit-tested against a fake "
        "transport. No live model call has ever been made.",
        "The Razorpay provider is a boundary skeleton. 9 of 12 field mappings "
        "are unresolved; it raises rather than fetching.",
        "The frozen benchmark is unrun. No accuracy claim is made.",
        "There is no real delivery transport. The sender is simulated.",
        "No exactly-once delivery guarantee.",
        "No concurrency or multi-writer safety guarantee.",
        "No file-level tamper resistance. Ordinary SQL is blocked; a process "
        "that can write the database file can rewrite it.",
        "Coverage catches numeric and temporal claims only. A silently "
        "omitted qualitative claim is not detected.",
    ],
}


class _CountingProposer:
    """Counts calls so the UI can show that a gated request costs nothing.

    Observability only - it forwards to the real proposer unchanged.
    """

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0

    def __call__(self, draft, state):
        self.calls += 1
        return self._inner(draft, state)


def _snapshot_state(conn, snapshot_hash):
    """The exact bytes recorded for this evaluation.

    Read back from storage rather than re-acquiring, so displaying state cannot
    perturb the one-acquisition invariant.
    """
    if not snapshot_hash:
        return None
    row = db.get_snapshot(conn, snapshot_hash)
    return json.loads(row["canonical"]) if row else None


def serialise(result: dict, app: Attest, calls: dict) -> dict:
    """Pure serialisation of what the application already returned."""
    proof = result["proof"]
    coverage = result["coverage"]
    return {
        "disposition": result["disposition"].value,
        "gate": {
            "decision": result["gate"].decision.value,
            "reason_code": result["gate"].reason_code,
            "rule_id": result["gate"].rule_id,
            "detail": result["gate"].detail,
        },
        "verdicts": [v.model_dump(mode="json") for v in result["verdicts"]],
        "claims": json.loads(proof["claims_json"]),
        "coverage": {
            "passed": coverage.passed,
            "reason": coverage.reason(),
            "spans": [{"kind": s.kind, "start": s.start, "end": s.end,
                       "text": s.text, "covered_by": s.covered_by}
                      for s in coverage.spans],
        },
        "proof": {
            "proof_id": proof["proof_id"],
            "snapshot_hash": proof["snapshot_hash"],
            "policy_version": proof["policy_version"],
            "policy_hash": proof["policy_hash"],
            "state_source": proof["state_source"],
            "state_provider": proof["state_provider"],
            "model_id": proof["model_id"],
            "failure_reason": proof["failure_reason"],
            "failure_detail": proof["failure_detail"],
            "message": proof["normalised_message"],
            "created_at": proof["created_at"],
        },
        "snapshot": _snapshot_state(app.conn, proof["snapshot_hash"]),
        "mode": {"label": app.mode, **LIMITATIONS["mode"]},
        "calls": calls,
    }


def run_evaluation(app: Attest, draft: str, merchant_id: str,
                   customer_id: str, scenario: str, now: str | None) -> dict:
    """Invoke the REAL evaluation path and serialise the result.

    Wraps Attest.evaluate() - the full-detail path - not process(), whose
    Outcome drops the coverage spans the UI needs.
    """
    provider = RecordingProvider(app.provider)
    proposer = _CountingProposer(app.proposer)
    app.provider, app.proposer = provider, proposer
    try:
        result = app.evaluate(draft, merchant_id, customer_id, scenario, now)
    finally:
        app.provider, app.proposer = provider._inner, proposer._inner
    return serialise(result, app,
                     {"provider": provider.calls, "proposer": proposer.calls})


class Handler(BaseHTTPRequestHandler):
    server_version = "attest"

    # Routes. GET is read-only; the only POSTs invoke the ordinary application
    # lifecycle (an evaluation creates a new proof) or the read-only replay.
    # There is deliberately NO route that mutates a stored snapshot or proof -
    # tampering lives in scripts/tamper_demo.py, outside the package.
    GET_ROUTES = ("/", "/api/limitations", "/api/proof/")
    POST_ROUTES = ("/api/verify", "/api/recheck")

    def log_message(self, fmt, *args):
        pass                                    # no request logging: no leakage

    # -- helpers ---------------------------------------------------------

    def _json(self, payload, status=200):
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _app(self) -> Attest:
        return self.server.ensure_app()

    # -- routes ----------------------------------------------------------

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = INDEX.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/limitations":
            self._json(LIMITATIONS)
            return

        if self.path.startswith("/api/proof/"):
            proof_id = self.path[len("/api/proof/"):]
            row = db.get_proof(self._app().conn, proof_id)
            if row is None:
                self._json({"error": f"no such proof: {proof_id}"}, 404)
                return
            self._json({k: row[k] for k in row.keys()})
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            payload = self._body()
        except json.JSONDecodeError as exc:
            self._json({"error": f"malformed JSON: {exc}"}, 400)
            return

        if self.path == "/api/verify":
            self._verify(payload)
        elif self.path == "/api/recheck":
            self._recheck(payload)
        else:
            self._json({"error": "not found"}, 404)

    def _verify(self, payload):
        draft = payload.get("draft")
        scenario = payload.get("scenario")
        if not isinstance(draft, str) or not draft.strip():
            self._json({"error": "draft is required"}, 400)
            return
        try:
            self._json(run_evaluation(
                self._app(), draft,
                str(payload.get("merchant_id") or "m_web"),
                str(payload.get("customer_id") or "cus_web"),
                scenario, payload.get("now")))
        except Exception as exc:                        # surfaced, never hidden
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _recheck(self, payload):
        """Invokes the EXISTING replay implementation. No logic of its own."""
        import recheck as replay

        conn = self._app().conn
        proof_id = payload.get("proof_id")
        ids = [proof_id] if proof_id else db.all_proof_ids(conn)
        results = []
        for pid in ids:
            ok, problems = replay.recheck_one(conn, pid)
            results.append({"proof_id": pid, "ok": ok, "problems": problems})
        send_ok, send_problems = replay.check_send_log(conn)
        self._json({
            "results": results,
            "send_log": {"ok": send_ok, "problems": send_problems},
            "note": "Replay recomputes the decision from the recorded policy "
                    "and snapshot. It does not re-ask the model and makes no "
                    "network call. Send-log integrity is structural only.",
        })


def build_server(config: AppConfig | None = None, host: str = "127.0.0.1",
                 port: int = 8000, app: Attest | None = None):
    """Construct the server without starting it - lets tests drive it."""
    # SINGLE-THREADED on purpose. ThreadingHTTPServer hands each request to a
    # new thread, and SQLite connections are thread-bound - the alternative fix
    # (check_same_thread=False) would mean editing storage/db.py for UI
    # convenience, which is not allowed. A single-user local demo needs no
    # concurrency, and this matches the project's standing position that it
    # makes no multi-writer safety claim.
    httpd = HTTPServer((host, port), Handler)
    cfg = config or AppConfig()
    httpd.attest_app = app

    def ensure_app() -> Attest:
        """Build the app on FIRST USE, inside the serving thread.

        The SQLite connection is thread-bound, so constructing it eagerly here
        would bind it to whichever thread called build_server() - fine for
        `serve()`, broken for a test that runs serve_forever in a background
        thread. Deferring construction keeps the connection and its user in the
        same thread without touching storage/db.py.
        """
        if httpd.attest_app is None:
            httpd.attest_app = Attest(cfg)
        return httpd.attest_app

    httpd.ensure_app = ensure_app
    return httpd


def serve(config: AppConfig | None = None, host: str = "127.0.0.1",
          port: int = 8000) -> int:
    httpd = build_server(config, host, port)
    app = httpd.ensure_app()
    print(f"MODE   {app.mode}")
    print(f"db     {app.config.db_path}")
    print(f"policy {app.policy_identity()}")
    print(f"\nAttest UI on http://{host}:{port}  (Ctrl-C to stop)")
    print("offline: no credentials read, no network calls made\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
        app.close()
    return 0
