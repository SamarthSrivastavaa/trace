"""The web boundary.

The invariant that matters most: there is ONE decision system. The browser and
the HTTP layer render what the application returned and compute nothing.

Everything here runs offline with no credentials.
"""

import ast
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

from pramaan.app import Pramaan
from pramaan.core.pipeline import FAILURE_STATE_ACQUISITION
from pramaan.config import AppConfig
from pramaan.storage import db
from pramaan.web import server as web

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER_SRC = (ROOT / "pramaan" / "web" / "server.py").read_text(encoding="utf-8")
INDEX_SRC = (ROOT / "pramaan" / "web" / "index.html").read_text(encoding="utf-8")
DRAFT = "This is our final attempt. Your 15% offer expires in 24 hours."


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read())

    def get(self, path):
        try:
            raw = urllib.request.urlopen(self.base + path).read()
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read())
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode("utf-8")

    def status(self, path):
        try:
            return urllib.request.urlopen(self.base + path).status
        except urllib.error.HTTPError as exc:
            return exc.code


@pytest.fixture()
def live(tmp_path):
    """A real server on a free port, app built lazily in the serving thread."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    db_path = str(tmp_path / "web.db")
    httpd = web.build_server(AppConfig(db_path=db_path), port=port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    # Hand back the PATH, not httpd.pramaan_app.conn: that connection is created
    # in - and bound to - the serving thread. A test that borrowed it would get
    # a ProgrammingError. Tests open their own connection to the same file.
    yield Client(port), db_path
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


# --- 1. ONE EXECUTION PATH -------------------------------------------------

# The fixture provider defines exactly two scenarios. Anything else fails state
# acquisition and escalates - which is itself a path the UI must render
# correctly, so it is included here under its real name rather than under an
# invented one that would imply a fixture that does not exist.
SCENARIOS = ["final_attempt", "first_attempt", "unknown_scenario"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_api_verify_matches_a_direct_evaluate_call(live, tmp_path, scenario):
    """The single most important UI invariant.

    Parametrized across scenarios that reach DIFFERENT dispositions on purpose.
    A single-scenario check is weak: an implementation that hardcoded the
    disposition it happened to see would still agree on that one input.
    """
    client, _ = live
    api = client.post("/api/verify", {"draft": DRAFT, "scenario": scenario,
                                      "customer_id": "cmp", "now": None})

    direct_app = Pramaan(AppConfig(db_path=str(tmp_path / "direct.db")))
    try:
        direct = direct_app.evaluate(DRAFT, "m_web", "cmp", scenario)
    finally:
        direct_app.close()

    assert api["disposition"] == direct["disposition"].value
    assert api["gate"]["reason_code"] == direct["gate"].reason_code
    assert api["proof"]["snapshot_hash"] == direct["proof"]["snapshot_hash"]
    assert api["proof"]["failure_reason"] == direct["proof"]["failure_reason"]
    assert api["coverage"]["passed"] == direct["coverage"].passed
    assert [(v["claim_id"], v["status"], v["reason_code"]) for v in api["verdicts"]] \
        == [(v.claim_id, v.status.value, v.reason_code) for v in direct["verdicts"]]


def test_the_equivalence_scenarios_reach_three_different_dispositions(live):
    """Guards the test above: if every scenario returned the same disposition,
    the parametrisation would prove nothing."""
    client, _ = live
    got = {s: client.post("/api/verify",
                          {"draft": DRAFT, "scenario": s, "customer_id": f"d_{s}"})
           for s in SCENARIOS}
    assert got["final_attempt"]["disposition"] == "SEND"
    assert got["first_attempt"]["disposition"] == "BLOCK"
    # and the third is genuinely the state-acquisition failure path
    esc = got["unknown_scenario"]
    assert esc["disposition"] == "ESCALATE"
    assert esc["proof"]["failure_reason"] == FAILURE_STATE_ACQUISITION
    assert esc["proof"]["snapshot_hash"] is None


def test_run_evaluation_delegates_to_the_app(monkeypatch, tmp_path):
    """Spy on the boundary: the web layer must call Pramaan.evaluate()."""
    app = Pramaan(AppConfig(db_path=str(tmp_path / "spy.db")))
    seen = {}
    real = app.evaluate

    def spy(*a, **k):
        seen["called"] = True
        return real(*a, **k)

    monkeypatch.setattr(app, "evaluate", spy)
    try:
        web.run_evaluation(app, DRAFT, "m", "c", "final_attempt", None)
    finally:
        app.close()
    assert seen.get("called"), "web layer bypassed Pramaan.evaluate()"


# --- 2. NO DECISION LOGIC IN THE WEB LAYER ---------------------------------

def _calls(src: str) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def test_server_calls_no_verification_primitive():
    forbidden = {"adjudicate", "adjudicate_all", "decide", "find_spans",
                 "canonicalise", "snapshot_hash", "content_hash",
                 "evaluate_pre_state", "evaluate_post_state", "normalise"}
    assert not (_calls(SERVER_SRC) & forbidden), _calls(SERVER_SRC) & forbidden


def test_server_imports_no_verification_module():
    mods = set()
    for node in ast.walk(ast.parse(SERVER_SRC)):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    bad = [m for m in mods if any(x in m for x in
                                  ("verify", "policy", "rules", "coverage"))]
    assert not bad, bad


def test_server_serialisers_contain_no_comparisons():
    """serialise() and run_evaluation() must not branch on values."""
    tree = ast.parse(SERVER_SRC)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in ("serialise",
                                                           "run_evaluation"):
            for node in ast.walk(fn):
                assert not isinstance(node, ast.Compare), \
                    f"{fn.name} compares values - that is a decision"


def test_browser_does_not_compare_asserted_against_observed():
    """The classic way a UI would silently become a second verifier."""
    script = INDEX_SRC[INDEX_SRC.index("<script>"):]
    for pattern in (r"asserted\s*===?\s*", r"observed\s*===?\s*",
                    r"asserted.*[=!]==.*observed", r"observed.*[=!]==.*asserted"):
        assert not re.search(pattern, script), f"browser compares values: {pattern}"


def test_browser_never_computes_a_disposition():
    """The page may DISPLAY a disposition; it may never derive one.

    Checked structurally: `disposition` is only ever read as a property off the
    response object, and is never assigned or bound to a local.
    """
    script = INDEX_SRC[INDEX_SRC.index("<script>"):]
    assert not re.search(r"\bdisposition\s*=[^=]", script), "disposition assigned"
    assert not re.search(r"\b(let|var|const|function)\s+disposition\b", script), \
        "disposition bound to a local - it must stay a backend value"
    reads = re.findall(r"(\w+)\.disposition\b", script)
    assert reads, "page never displays a backend disposition"
    assert set(reads) <= {"d"}, f"disposition read off an unexpected object: {reads}"


# --- 3. REAL STATE FLIP ----------------------------------------------------

def test_state_flip_is_two_real_evaluations(live):
    client, db_path = live
    a = client.post("/api/verify", {"draft": DRAFT, "scenario": "final_attempt",
                                    "customer_id": "flipA"})
    b = client.post("/api/verify", {"draft": DRAFT, "scenario": "first_attempt",
                                    "customer_id": "flipB"})

    assert a["disposition"] == "SEND"
    assert b["disposition"] == "BLOCK"
    # identical message
    assert a["proof"]["message"] == b["proof"]["message"] == DRAFT
    # genuinely different acquired state
    assert a["proof"]["snapshot_hash"] != b["proof"]["snapshot_hash"]
    assert a["snapshot"]["subscription"]["attempt_index"] == 4
    assert b["snapshot"]["subscription"]["attempt_index"] == 1
    # and exactly one claim flipped
    flipped = [(x["claim_id"], x["status"], y["status"])
               for x, y in zip(a["verdicts"], b["verdicts"])
               if x["status"] != y["status"]]
    assert len(flipped) == 1 and flipped[0][1:] == ("SUPPORTED", "CONTRADICTED")
    # both proofs really exist in the database
    conn = db.connect(db_path)
    for r in (a, b):
        assert db.get_proof(conn, r["proof"]["proof_id"]) is not None
    conn.close()


# --- 4. SUPPRESSION COSTS ZERO ---------------------------------------------

def test_suppressed_request_through_the_api_costs_zero_calls(live):
    client, db_path = live
    conn = db.connect(db_path)
    db.suppress(conn, "m_web", "gone", "2026-09-04T10:00:00+00:00", "test")
    conn.close()

    r = client.post("/api/verify", {"draft": DRAFT, "scenario": "final_attempt",
                                    "customer_id": "gone"})
    assert r["disposition"] == "BLOCK"
    assert r["gate"]["reason_code"] == "CUSTOMER_SUPPRESSED"
    assert r["calls"] == {"provider": 0, "proposer": 0}
    assert r["proof"]["snapshot_hash"] is None
    assert r["snapshot"] is None

    allowed = client.post("/api/verify", {"draft": DRAFT,
                                          "scenario": "final_attempt",
                                          "customer_id": "here"})
    assert allowed["calls"] == {"provider": 1, "proposer": 1}


# --- 5. PROOF EXPLORER READS REAL DATA -------------------------------------

def test_proof_endpoint_returns_the_persisted_row(live):
    client, db_path = live
    r = client.post("/api/verify", {"draft": DRAFT, "scenario": "final_attempt",
                                    "customer_id": "pf"})
    pid = r["proof"]["proof_id"]
    served = client.get(f"/api/proof/{pid}")
    conn = db.connect(db_path)
    stored = db.get_proof(conn, pid)
    assert served["proof_id"] == stored["proof_id"]
    assert served["content_hash"] == stored["content_hash"]
    assert served["verdicts_json"] == stored["verdicts_json"]
    conn.close()


def test_unknown_proof_returns_404(live):
    client, _ = live
    assert client.status("/api/proof/prf_nope") == 404


# --- 6. REAL RECHECK -------------------------------------------------------

def test_recheck_endpoint_invokes_the_real_replay(live, monkeypatch):
    import recheck as replay
    client, _db = live
    client.post("/api/verify", {"draft": DRAFT, "scenario": "final_attempt",
                                "customer_id": "rc"})
    seen = {"n": 0}
    real = replay.recheck_one

    def spy(conn, pid, *a, **k):
        seen["n"] += 1
        return real(conn, pid, *a, **k)

    monkeypatch.setattr(replay, "recheck_one", spy)
    out = client.post("/api/recheck", {})
    assert seen["n"] >= 1, "endpoint did not call recheck.recheck_one"
    assert all(x["ok"] for x in out["results"])


def test_recheck_reports_real_failure_after_tampering(live):
    client, db_path = live
    r = client.post("/api/verify", {"draft": DRAFT, "scenario": "final_attempt",
                                    "customer_id": "tam"})
    assert client.post("/api/recheck", {})["results"][0]["ok"]

    conn = db.connect(db_path)
    conn.execute("DROP TRIGGER snapshot_no_update")
    row = conn.execute("SELECT hash, canonical FROM snapshot LIMIT 1").fetchone()
    state = json.loads(row["canonical"])
    state["subscription"]["attempt_index"] = 1
    conn.execute("UPDATE snapshot SET canonical=? WHERE hash=?",
                 (json.dumps(state, sort_keys=True, separators=(",", ":")),
                  row["hash"]))
    conn.commit()
    conn.close()

    out = client.post("/api/recheck", {})
    bad = [x for x in out["results"] if not x["ok"]]
    assert bad, "replay did not detect the tampering"
    assert any("snapshot hash mismatch" in p for p in bad[0]["problems"])


# --- 7. NO MUTATION ROUTES -------------------------------------------------

def test_no_route_can_mutate_stored_evidence():
    """Creating a new proof is the lifecycle; editing one is tampering."""
    assert web.Handler.GET_ROUTES == ("/", "/api/limitations", "/api/proof/")
    assert web.Handler.POST_ROUTES == ("/api/verify", "/api/recheck")
    for verb in ("do_PUT", "do_DELETE", "do_PATCH"):
        assert not hasattr(web.Handler, verb), f"{verb} exists"
    # Structural, not substring: the word "tamper" legitimately appears in the
    # LIMITATIONS prose ("no file-level tamper resistance"). What must not exist
    # is a ROUTE or a SQL mutation.
    tree = ast.parse(SERVER_SRC)
    routes = [n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and n.value.startswith("/api/")]
    assert all(r in ("/api/limitations", "/api/proof/", "/api/verify",
                     "/api/recheck") for r in routes), routes
    for sql in ("UPDATE ", "DELETE FROM", "DROP TRIGGER", "INSERT INTO"):
        assert sql not in SERVER_SRC, f"server.py issues SQL: {sql!r}"
    assert "def do_tamper" not in SERVER_SRC


def test_mutating_verbs_are_rejected(live):
    client, _ = live
    req = urllib.request.Request(client.base + "/api/proof/x", b"{}",
                                 {"Content-Type": "application/json"},
                                 method="DELETE")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code in (400, 501)


def test_tamper_stays_a_script_outside_the_package():
    assert (ROOT / "scripts" / "tamper_demo.py").is_file()
    assert not (ROOT / "pramaan" / "web" / "tamper.py").exists()


# --- 8. NO SECRET LEAKAGE --------------------------------------------------

def test_no_endpoint_leaks_a_credential(live, monkeypatch):
    client, _ = live
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-LEAKCANARY111")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp-LEAKCANARY222")

    bodies = [
        json.dumps(client.post("/api/verify", {"draft": DRAFT,
                                               "scenario": "final_attempt",
                                               "customer_id": "leak"})),
        json.dumps(client.post("/api/recheck", {})),
        json.dumps(client.get("/api/limitations")),
        str(client.get("/")),
    ]
    for body in bodies:
        assert "LEAKCANARY111" not in body
        assert "LEAKCANARY222" not in body
        assert "sk-ant" not in body


def test_server_does_not_log_requests():
    """Silencing log_message keeps drafts and ids out of stdout."""
    assert "def log_message" in SERVER_SRC


# --- 9. OFFLINE STARTUP ----------------------------------------------------

def test_server_starts_and_serves_with_no_credentials(tmp_path):
    code = (
        "import json,sys,threading,urllib.request\n"
        "from pramaan.config import AppConfig\n"
        "from pramaan.web.server import build_server\n"
        "import socket\n"
        "s=socket.socket(); s.bind(('127.0.0.1',0)); port=s.getsockname()[1]; s.close()\n"
        f"h=build_server(AppConfig(db_path=r'{tmp_path / 'off.db'}'), port=port)\n"
        "threading.Thread(target=h.serve_forever, daemon=True).start()\n"
        "page=urllib.request.urlopen(f'http://127.0.0.1:{port}/').read().decode()\n"
        "assert 'PRAMAAN' in page\n"
        "r=json.loads(urllib.request.urlopen(\n"
        "    urllib.request.Request(f'http://127.0.0.1:{port}/api/verify',\n"
        "    json.dumps({'draft':'Only 2 left.','scenario':'final_attempt',\n"
        "                'customer_id':'x'}).encode(),\n"
        "    {'Content-Type':'application/json'})).read())\n"
        "assert r['disposition'] in ('SEND','BLOCK','ESCALATE')\n"
        "h.shutdown(); print('ok')\n")
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "RAZORPAY_KEY_ID",
                        "RAZORPAY_KEY_SECRET")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=120, cwd=str(ROOT), env=env)
    assert out.returncode == 0, out.stderr
    assert "ok" in out.stdout


def test_cli_exposes_serve_without_breaking_existing_commands():
    from pramaan.cli import build_parser
    subs = build_parser()._subparsers._group_actions[0].choices
    assert "serve" in subs
    for existing in ("status", "evaluate", "send", "proof", "suppress",
                     "recheck", "demo"):
        assert existing in subs, f"{existing} disappeared"


# --- honesty ---------------------------------------------------------------

def test_limitations_endpoint_is_the_single_source(live):
    client, _ = live
    lim = client.get("/api/limitations")
    assert lim["mode"] == {"model": "MOCK", "state": "SIMULATED",
                           **{"note": lim["mode"]["note"]}}
    joined = " ".join(lim["not_proven"]).lower()
    for disclosure in ("no live model call has ever been made",
                       "boundary skeleton", "unrun", "no accuracy claim",
                       "no exactly-once", "no concurrency",
                       "no file-level tamper resistance",
                       "numeric and temporal claims only"):
        assert disclosure in joined, f"missing disclosure: {disclosure!r}"


def test_page_shows_mode_badges_and_no_fake_ai_language():
    assert "MODEL" in INDEX_SRC and "STATE" in INDEX_SRC
    lowered = INDEX_SRC.lower()
    # "immutable" was on the runbook's DO-NOT-SAY list but missing here,
    # and the page shipped an "Immutable proof" heading because of it.
    for banned in ("confidence", "hallucination meter", "ai thinks",
                   "powered by claude", "razorpay integration",
                   "tamper-proof", "immutable", "exactly-once",
                   "guaranteed", "production-ready", "accuracy"):
        assert banned not in lowered, f"page contains {banned!r}"


def test_page_has_no_external_asset_or_cdn():
    for pattern in ("http://", "https://", "cdn.", "<script src", "<link "):
        assert pattern not in INDEX_SRC, f"page references {pattern!r}"
