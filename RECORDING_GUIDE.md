# Recording Attest — a complete guide for someone seeing this for the first time

You do not need to know Python, and you do not need to have seen this project
before. Everything you type is copy-paste. Everything you say is written out for
you. This guide tells you what to expect on screen at every step, so you always
know whether a take is good.

**Total time:** about 90 minutes including setup and rehearsal.
**Final video:** roughly 5 minutes.

---

## Part 1 — What this app actually does

Read this once. It takes two minutes and it will make your narration sound like
you understand it, because you will.

### The problem

Companies now use AI to write messages to customers. Here is a real example:

> *"This is our final attempt. Your 15% offer expires in 24 hours."*

Read that sentence and ask yourself: **is it true?**

You cannot tell. Not from the sentence. Three separate factual promises are
buried in it:

1. This is the *final* attempt — is it? Or is it the first?
2. There is a *15%* offer — does that offer exist?
3. It expires in *24 hours* — does it?

The answers are not in the text. They are in the company's database. The AI that
wrote the sentence has every incentive to sound urgent and no ability to prove
any of it.

### What Attest does

Attest sits between the AI and the customer, and refuses to let the message
through until every factual claim in it has been checked against the company's
real records.

It works in a specific order, and the order is the whole point:

| Step | What happens |
|---|---|
| 1 | The message arrives |
| 2 | A policy gate checks basic rules — is this customer opted out? Did we message them yesterday? If so, **stop here** |
| 3 | Fetch the company's real data **once**, then freeze it and fingerprint it |
| 4 | Ask the AI **one question only**: what does this message claim? |
| 5 | Ordinary, boring, non-AI code checks each claim against the frozen data |
| 6 | A separate scan re-reads the message to catch anything the AI quietly skipped |
| 7 | A verdict: **SEND**, **BLOCK**, or **ESCALATE** — plus a permanent record |

### The one idea you must understand

> **The AI is allowed to say what the message claims. It is never allowed to say whether those claims are true.**

That is not a rule someone typed into a prompt asking the AI to behave. It is
built into the structure. The form the AI has to fill in **has no box for a
verdict**. If the AI tries to write one, the form is rejected outright.

Deciding "is 15% equal to 15%?" is a comparison. Comparisons should be done by
code that gives the same answer every time — not by an AI that is right most of
the time.

If you only remember one sentence from this guide, remember that one. Most of
your narration is just restating it in different ways.

### The three possible verdicts

- **SEND** — every claim checked out.
- **BLOCK** — something in the message is not supported by the records.
- **ESCALATE** — the AI itself misbehaved (for example, it cited a discount that
  does not exist). That is a different problem from the message being wrong, so
  it gets a different answer.

---

## Part 2 — Setup

### 2.1 What you need

- The project folder on this computer
- Python (already installed — you will confirm this in a second)
- A screen recorder (OBS, or whatever you normally use)
- A microphone. **Phone earbuds are much better than a laptop's built-in mic.**

You do **not** need an internet connection. Nothing in this demo goes online.
That is deliberate and you will say so on camera.

### 2.2 Open a terminal in the project folder

On Windows, open **Git Bash** (or PowerShell) and run:

```bash
cd c:/Users/HP/OneDrive/Desktop/rzr
```

### 2.3 Confirm everything works

Type this and press Enter:

```bash
python -m pytest tests/ -q
```

Wait about 30 seconds. **You should see:**

```
422 passed in 25.13s
```

If you see `422 passed`, everything is fine and you can record.
If you see anything else, stop and go to **Part 6 — Troubleshooting**.

> **If `python` is not recognised,** use `py -3.11` in place of `python` for every
> command in this guide. Do **not** use plain `py` — on this machine that is a
> different Python installation without the required library, and it will fail
> with a confusing error.

### 2.4 Make the screen recordable

This matters more than people expect. A brilliant demo in tiny grey text is a
bad demo.

- [ ] **Terminal font size 18pt or larger.** You should read it easily from an
      arm's length away.
- [ ] **Terminal window about 1920×1080.** Do not use fullscreen on a very large
      monitor — the text ends up microscopic after upload.
- [ ] **High contrast colours.** Dark background, bright text.
- [ ] **Turn on Do Not Disturb.** Close Slack, email, everything that pops up.
- [ ] **Hide desktop icons and browser bookmarks.**
- [ ] **Record a 20-second audio test and listen back on headphones.** If it
      echoes, close the windows and turn off any fan or AC. Do this before
      anything else — bad audio ruins good content and you cannot fix it later.

### 2.5 Windows you will need open

| Window | What for |
|---|---|
| **Terminal A** | Runs the web app. Start it once, then leave it alone. |
| **Terminal B** | Where you type commands. Clear it between shots. |
| **Browser** | The web interface, at the address Terminal A prints. |

---

## Part 3 — The shots

Record these as **nine separate clips**. Do not attempt one continuous take. Nine
short clips that are each good will beat one long take that is nearly good.

Shoot them **in this order**. It is arranged so you warm up on the easy ones and
the risky one comes last.

Between every shot, type `clear` in the terminal.

---

### SHOT 1 — The AI is not allowed to decide

**Type this:**

```bash
python -m attest.core.verify.schema
```

**What you should see:** one green-ish `ACCEPT` line, then about a dozen `REJECT`
lines. The last few look like this:

```
  REJECT  percent out of range               less_than_equal: Input should be less than or equal to 100
  REJECT  model states a verdict             extra_forbidden: Extra inputs are not permitted
  REJECT  duplicate claim_id                 Value error, duplicate claim_id
```

**The line that matters:** `REJECT  model states a verdict`

**Say this:**

> This isn't a prompt politely asking the AI to behave. It's a type system. The
> form the model has to fill in has no field for a verdict. Watch what gets
> rejected — a made-up field name. A path that tries to escape into somewhere it
> shouldn't reach. And right here: a model attempting to state its own verdict.
> Rejected. It isn't trusted not to decide. It's structurally unable to.

**Editing note:** after you finish speaking, hold on the screen for two seconds
so the editor can zoom in on that one line.

---

### SHOT 2 — The AI can't hide a claim by not mentioning it

**Type this:**

```bash
python -m attest.core.verify.coverage
```

**What you should see:** a sample message, a list of things found in it, then
three results. The important two:

```
COMPLETE           passed=True
  ok - all 4 checkable spans adjudicated

DEADLINE OMITTED   passed=False
  uncovered span(s): DURATION '24 hours' at offset 56
```

**Say this:**

> Here's the loophole most people miss. If you only check the claims the AI
> reported, the AI can sneak one past you by simply not mentioning it. Asking it
> "did you cover everything?" is asking it to audit its own blind spot.
>
> So there's a second scan that reads the message text directly and never sees
> the AI's answer at all. Drop the deadline claim, and the phrase "24 hours" is
> still sitting right there at character fifty-six, unaccounted for. Blocked.
>
> This catches numbers and dates. It does not catch a vaguer promise like "you
> qualify" — and that gap is written down in our documentation.

**Important:** say that last sentence at normal speed. Do not mumble it or rush
past it. Admitting the gap is what makes everything else believable.

---

### SHOT 3 — A blocked message costs nothing

**Type this** (it is long — copy and paste it):

```bash
python -m pytest tests/test_gate.py -k "touches_neither or calls_provider_then_propose" -v --no-header
```

**What you should see:** three lines ending in `PASSED`, then `3 passed`.

```
tests/test_gate.py::test_allowed_request_calls_provider_then_propose_exactly_once PASSED
tests/test_gate.py::test_suppressed_request_touches_neither_provider_nor_model PASSED
tests/test_gate.py::test_cooldown_blocked_request_touches_neither PASSED
```

**Say this:**

> The policy here isn't advice, it's a gate in the road. If a customer has opted
> out, or we already messaged them yesterday, it stops before fetching any data
> and before calling the AI at all. Zero data lookups. Zero model calls. These
> three tests are named after exactly that, and they run in under a second.

**Note:** the test names on screen are the evidence. Do not zoom past them — let
them stay readable.

---

### SHOT 4 — The centrepiece, in the browser

This is the most important shot in the video. Take your time.

**First, start the app.** In **Terminal A**:

```bash
python -m attest --db demo.db serve
```

**You should see:**

```
MODE   state=SIMULATED model=MOCK
db     demo.db
policy attest-default@v1+c21eed9764f6f018

Attest UI on http://127.0.0.1:8000  (Ctrl-C to stop)
offline: no credentials read, no network calls made
```

Open **http://127.0.0.1:8000** in the browser. Leave Terminal A running for the
rest of the shoot — do not close it, do not type in it.

**On the page:** scroll down to the section headed **"One field, opposite
outcome."** Click **Run both scenarios**.

**What you should see:** two panels appear side by side.

| Left panel | Right panel |
|---|---|
| **SEND** (green) | **BLOCK** (red) |
| `attempt_index  4` | `attempt_index  1` |
| a long code starting `58d07e42…` | a **different** long code starting `6b5579ba…` |

Above them, a line confirms the message sent to both runs was character-for-character identical.

**Say this** — and note the pause, it matters:

> Same message. Word for word identical — the page prints it so you can check.
> Two real evaluations. In the first one, the company's records say this is
> attempt four out of four. So "this is our final attempt" is true. Send.
>
> Now I change one single field. Attempt four becomes attempt one. Same words.
> Same AI output.
>
> *(STOP TALKING. Count to two in your head.)*
>
> Blocked. Those two long codes are fingerprints of the company's data — they're
> different, so the data really did change. Nothing else moved.
>
> **The message never changed. The database did.**

**Editing note:** that silence before "Blocked" is the most important 1.5 seconds
in the video. Do not fill it. If you rush it, do the take again.

---

### SHOT 5 — The same thing, in the terminal

This is the forensic version of Shot 4, and it shows detail the browser doesn't.
Open **two terminal panes side by side** if you can. If not, run them one after
the other in the same window.

**Left pane / first command:**

```bash
python -m attest --db demo.db evaluate --draft "This is our final attempt. Your 15% offer expires in 24 hours." --customer alice --scenario final_attempt --now 2026-09-04T10:00:00+00:00
```

**Right pane / second command:**

```bash
python -m attest --db demo.db evaluate --draft "This is our final attempt. Your 15% offer expires in 24 hours." --customer bob --scenario first_attempt --now 2026-09-04T10:00:00+00:00
```

The message text is **identical** in both. Only the word after `--scenario`
differs. That is the entire experiment.

**What you should see:**

```
disposition   SEND                     disposition   BLOCK
snapshot      58d07e42...              snapshot      6b5579ba...
  c1 is_final_attempt   SUPPORTED        c1 is_final_attempt   CONTRADICTED
  c2 discount_percent   SUPPORTED        c2 discount_percent   SUPPORTED
  c3 deadline_within    SUPPORTED        c3 deadline_within    SUPPORTED
```

**Say this:**

> Same sentence, twice. Three claims were pulled out of it: is this the final
> attempt, is the discount fifteen percent, does it expire within twenty-four
> hours. On the left, all three check out. On the right, exactly one flips —
> the final-attempt claim — and the other two don't move at all. The discount is
> still fifteen percent, because that part was always true.

---

### SHOT 6 — Don't trust the stored answer

Back in the browser. Scroll to **"Proof and offline replay."** Click **Replay
offline**.

**What you should see:** a green result reading **all proofs re-verified**, with
a count like `2/2 recomputed`.

**Say this:**

> Every decision writes a permanent record. But storing an answer proves nothing
> — anyone can store an answer.
>
> So re-checking doesn't read the old answer back. It recalculates it from
> scratch, using the frozen data and the exact rules that were in force at the
> time. It never re-asks the AI, and it makes no network call.

**Do not close anything.** The next shot depends on this state.

---

### SHOT 7 — The attack

**This one is permanent. Record it last. Read the warning below first.**

> **WARNING:** this command permanently damages `demo.db`. There is no undo. If
> you need to re-record anything afterwards, you must delete the file and start
> from Shot 4 again. See Part 5.

Leave the browser open. In **Terminal B**:

```bash
python scripts/tamper_demo.py demo.db
```

**What you should see:**

```
tampered snapshot 58d07e42141e5059...
  subscription.attempt_index: 4 -> 1
  (one field, in one stored snapshot; the proof row is untouched)
```

Now go **back to the browser** and click **Replay offline** again.

**What you should see:** the panel turns red.

```
integrity check failed
  snapshot hash mismatch: stored bytes do not hash to the hash this proof cites
  verdict mismatch: recomputed adjudication differs from the recorded one
  disposition mismatch: recomputed=BLOCK stored=SEND
```

**Say this:**

> Now let's attack it. This script reaches into the stored records and edits one
> single field. It has to disable a database protection first, because normal
> attempts to edit these records are refused outright.
>
> Re-check again.
>
> The fingerprint no longer matches. The verdicts no longer match. And here it is
> — **recomputed BLOCK, stored SEND.** The record claims we approved this
> message. Recalculating says we should not have.
>
> That's tamper *evidence*, not tamper prevention. We had to disable a protection
> to get in, and anyone who can edit the file can edit the file. We don't pretend
> otherwise.

**Editing note:** hold on the line `recomputed=BLOCK stored=SEND` for a full two
seconds. This is the second most important moment in the video.

---

### SHOT 8 — What we did not fake

Scroll the browser to the **top** first, so the two labels in the corner are
clearly visible: **MODEL MOCK** and **STATE SIMULATED**. Then scroll slowly down
to the black section headed **"What this does not prove."**

**Say this** — slow down noticeably here, and sound confident rather than
apologetic:

> Now the part most demos skip. These two labels have been on screen the entire
> video. The AI here is a stand-in — a fixed, predictable script, not a real
> language model. The company data is hand-written, not a live connection.
>
> The real AI connection is built and tested, but has never once been called for
> real. The payment-provider connection is a skeleton with nine of its twelve
> data mappings still unresolved — it refuses to run rather than guess. We built
> a seventy-case benchmark and have not run it, so we make no claim about how
> often this is right.
>
> We haven't proven what we haven't measured. Everything you *did* just see was
> real.

**This is not a weakness section. It is the strongest section in the video.**
Anyone can claim things work. Stating precisely where your evidence stops is what
makes a technical judge believe the rest.

---

### SHOT 9 — Opening and closing (voice only)

Record these last, when your voice is warmed up and you have said the ideas
several times already.

#### The opening (this becomes the first 13 seconds)

On screen the editor will place plain text on black. You just record the voice:

> An AI wrote this message to a customer. Is it true? You can't tell. Not from
> the sentence. Every fact in it — final attempt, fifteen percent, twenty-four
> hours — lives somewhere else. In the company's database.

#### The closing (this becomes the last 15 seconds)

> Let the AI write the message. But the moment that message makes a factual
> promise to a customer, the AI should not be the thing that decides whether it's
> true. Attest makes that decision predictable, recorded, and something anyone
> can recalculate without taking our word for it.
>
> Same words. Different truth.

---

## Part 4 — Things you must never say

This is the most important section in this guide.

The people judging this will check. Every one of the phrases on the right is
**false** for this project, and saying one on camera does more damage than a
fumbled take.

| Say this | Never say this | Why |
|---|---|---|
| "The AI here is a stand-in — a fixed script." | "Powered by Claude." / "AI-powered verification." | No real AI model has ever been called. Not once. |
| "The payment-provider connection is a skeleton and isn't demonstrated." | "Integrated with Razorpay." | Nine of twelve data mappings are unresolved. It refuses to run. |
| "Re-checking detects the kind of tampering shown here." | "Tamper-proof." / "Unhackable." | The demo script disables a protection to get in. It proves *detection*, not prevention. |
| "The records are append-only — edits are refused." | "The records are permanent and unchangeable." | Normal edits are blocked. Someone with file access can still edit the file. |
| "We make no claim about how often it's right." | "More accurate than an AI." / "99% accurate." | The benchmark exists but has never been run. There is no number. |
| "SEND means no reason to block was found." | "It sends the message." / "Guaranteed delivery." | It never actually delivers anything. That is somebody else's job. |
| "422 tests run offline." | "Production-ready." | No live connection is exercised by any test. |

**If you are unsure whether something is safe to say — don't say it.** The
written script above is already checked and safe. Sticking to it is always the
right call.

---

## Part 5 — Resetting between takes

The tampering in Shot 7 is permanent. To start clean:

```bash
rm -f demo.db
```

Then re-run Shot 4 onwards.

**If that command says `Device or resource busy`,** the app is still running and
holding the file. Fix it like this:

```bash
taskkill //F //IM python.exe
rm -f demo.db
```

Then start the app again with `python -m attest --db demo.db serve`.

**Never record over a damaged database.** If you skip the reset, your clean
re-check in Shot 6 will fail and you will waste time hunting for why.

---

## Part 6 — Troubleshooting

| What you see | What it means | Fix |
|---|---|---|
| `422 passed` | Everything is fine | Carry on |
| Any number other than 422, or `failed` | Something is genuinely wrong | Stop. Tell the project owner before recording. |
| `python: command not found` | Python isn't on the path | Use `py -3.11` everywhere instead of `python` |
| `No module named 'pydantic'` | You're on the wrong Python version | Use `py -3.11` instead of `python`. Plain `py` is a different install and will not work. |
| `No module named attest` | You're in the wrong folder | `cd c:/Users/HP/OneDrive/Desktop/rzr` |
| `Device or resource busy` | The app is still running | See Part 5 |
| `Address already in use` | Port 8000 is taken | `python -m attest --db demo.db serve --port 8080`, then browse to that port |
| Browser page is blank | The app isn't running | Check Terminal A is still going |
| `no proofs to recheck` | No evaluation has run yet | Click **Run both scenarios** first |
| Re-check is red when you expected green | The database was already tampered with | Reset — see Part 5 |
| `recheck --all` says `policy drift` | Old database from before a change | `rm -f demo.db` and start again |

---

## Part 7 — Editing checklist

- [ ] Cut every pause where nothing happens and nobody is talking
- [ ] **Keep** the deliberate silence before "Blocked" in Shot 4
- [ ] **Keep** the two-second hold on `recomputed=BLOCK stored=SEND` in Shot 7
- [ ] Zoom in on these four things, since a viewer will not find them alone:
  - `REJECT model states a verdict`
  - the two different fingerprint codes (`58d07e42…` and `6b5579ba…`)
  - `uncovered span(s): DURATION '24 hours'`
  - `recomputed=BLOCK stored=SEND`
- [ ] Add captions on those four — many judges watch muted first
- [ ] Music quiet or absent. Never over the narration.
- [ ] Export 1080p
- [ ] **Check the submission platform's time limit before exporting**
- [ ] Watch it once with Part 4 open. If you improvised any line that resembles
      the right-hand column, cut it.

---

## Quick reference card

Print this or keep it on a second screen.

```
SETUP
  cd c:/Users/HP/OneDrive/Desktop/rzr
  python -m pytest tests/ -q                  ->  expect "422 passed"

APP (Terminal A, leave running)
  python -m attest --db demo.db serve         ->  browse 127.0.0.1:8000

SHOT 1   python -m attest.core.verify.schema
         land on:  REJECT  model states a verdict

SHOT 2   python -m attest.core.verify.coverage
         land on:  uncovered span(s): DURATION '24 hours' at offset 56

SHOT 3   python -m pytest tests/test_gate.py -k "touches_neither or calls_provider_then_propose" -v --no-header
         land on:  3 passed

SHOT 4   browser -> "Run both scenarios"
         land on:  SEND / BLOCK, two different fingerprints
         PAUSE 1.5s before saying "Blocked"

SHOT 5   two panes, the two evaluate commands (see Shot 5 above)
         land on:  c1 SUPPORTED  vs  c1 CONTRADICTED

SHOT 6   browser -> "Replay offline"
         land on:  all proofs re-verified

SHOT 7   python scripts/tamper_demo.py demo.db     <-- PERMANENT, DO LAST
         then browser -> "Replay offline" again
         land on:  recomputed=BLOCK stored=SEND

SHOT 8   scroll to top (MODEL MOCK / STATE SIMULATED), then to limitations

SHOT 9   record opening and closing voice

RESET    taskkill //F //IM python.exe  &&  rm -f demo.db
```

---

## One last thing

You are not selling this. You are showing it working and then being straight
about where it stops.

Three things separate a good recording from a great one, and none of them are
technical:

1. **The silence before "Blocked."** Do not fill it.
2. **Delivering the limitations section with confidence.** Most submissions
   overclaim. This one states exactly where the evidence ends, and that is what
   makes a judge trust everything before it.
3. **Not explaining the architecture.** Show it working. The screen does the
   explaining.

Good luck.
