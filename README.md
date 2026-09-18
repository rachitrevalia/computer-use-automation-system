# Computer-Use Automation System

A system where an LLM discovers how to complete a task inside a real
web UI with no API — by looking at the screen and clicking/typing like
a human would — and the successful run becomes a typed, versioned,
reusable capability. That capability then replays deterministically
afterward, with **no model in the loop**: it handles real runtime
errors (not-found results, permission denials, session timeouts), stays
inside an explicit safety allowlist, and escalates to a human when it
genuinely can't proceed on its own.

The through-line: **the model discovers, the artifact becomes a
reusable capability, deterministic replay is how it gets invoked
afterward** — cheaply, reliably, and without re-reasoning about the UI
every time.

This matters most for software with no clean automation surface: no
API, no test IDs, messy legacy markup, content buried in iframes. A
target app in this repo is deliberately built to be exactly that kind
of hostile surface, so every part of the system has to earn its
robustness rather than assume a friendly DOM.

See **REPORT.md** for the full design write-up — architecture, the
artifact schema, how determinism and error handling work, how the
design would extend to more heterogeneous surfaces and multiple
tenants, the escalation/handoff mechanism, the safety model, and what
was deliberately left out.

## Project layout

```
target_app/     Mock "LegacyBank" app the agent automates (Flask, deliberately legacy-styled)
agent/          Discovery: Playwright perception/action layer + Gemini-driven decision loop
artifact/       Capability schema (Pydantic) + load/save/validate + the two built artifacts' source
capabilities/   The two saved capability artifacts (JSON)
replay/         Deterministic replay engine -- no LLM involved
guardrails/     Allowlist enforcement, risky-action confirmation, secret redaction
handoff/        Human-in-the-loop escalation: pause/cede/resume control transfer
evidence/       Logs, screenshots, and results from real discovery/replay/escalation runs
```

## Setup

Requires Python 3.11+.

```bash
git clone <this repo>
cd computer-use-automation-system
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install flask playwright pydantic google-genai
playwright install chromium
```

### API key (free, no credit card)

1. Go to [Google AI Studio](https://aistudio.google.com), sign in with
   any Google account, and create an API key.
2. Set it as an environment variable:
   ```bash
   export GOOGLE_API_KEY="your-key-here"
   ```
   (Add this to `~/.zshrc`/`~/.bashrc` to persist it across sessions.)

The discovery agent uses `gemini-3.1-flash-lite`, chosen for its
free-tier daily quota — an earlier choice, `gemini-3.6-flash`, turned
out to cap free usage at 20 requests/day, which isn't workable for
iterative development.

### Mock credentials (for the target app's login)

```bash
export TELLER_USERNAME=teller1
export TELLER_PASSWORD=pass1
```
These get substituted into a capability's `{{secret:...}}` placeholders
at replay time — never hardcoded in any file. Any non-empty values work
against the mock app.

## Running everything (in order)

**Terminal 1 — start the target app, and leave it running:**
```bash
cd target_app
python app.py
```
Serves at `http://127.0.0.1:5001`. Manual walkthrough: log in with any
non-empty username/password, look up member `12345` (Alice Johnson,
$4210.55) or `67890` (Bob Martinez), or `99999` (a locked account,
always returns Access Denied).

**Terminal 2 — run the demo path below.**

### 1. Discovery — a genuine LLM-driven run against a live surface

```bash
cd agent

# Goal 1: read-only balance lookup
python run_discovery.py \
  --goal "look up member 12345 and read their savings balance" \
  --start-url http://127.0.0.1:5001/login \
  --evidence-dir ../evidence/discovery_run_1

# Goal 2: multi-step form + confirmation (a write action)
python run_discovery.py \
  --goal "Look up member 12345, open a new sub-account for them using account type Money Market Account with an initial deposit of 500, and reach the confirmation screen. Extract the confirmation number and the deposit amount from the confirmation page." \
  --start-url http://127.0.0.1:5001/login \
  --evidence-dir ../evidence/discovery_run_2
```
A real Chrome window opens and drives itself. Evidence (step-by-step
log, a screenshot, and a result summary) is saved to each `--evidence-dir`.
Add `--headless` to run invisibly.

### 2. Build the capability artifacts from that evidence

```bash
cd ../artifact
python build_capabilities.py
```
Writes `capabilities/lookup_member_balance.v1.json` and
`capabilities/open_subaccount.v1.json` — typed, versioned, reviewable
contracts (see REPORT.md for the schema design).

### 3. Replay — the production execution path, zero LLM calls

```bash
cd ../replay

# Success
python run_replay.py \
  --capability ../capabilities/lookup_member_balance.v1.json \
  --input member_id=12345 \
  --evidence-dir ../evidence/replay_run_success

# Business outcome: member doesn't exist (not a crash -- a legitimate result)
python run_replay.py \
  --capability ../capabilities/lookup_member_balance.v1.json \
  --input member_id=00000 \
  --evidence-dir ../evidence/replay_run_notfound

# Business outcome: locked account
python run_replay.py \
  --capability ../capabilities/lookup_member_balance.v1.json \
  --input member_id=99999 \
  --evidence-dir ../evidence/replay_run_denied

# Success with DIFFERENT parameters than discovery ever saw -- proves reuse
python run_replay.py \
  --capability ../capabilities/open_subaccount.v1.json \
  --input member_id=67890 --input account_type="Certificate of Deposit" --input initial_deposit=750 \
  --evidence-dir ../evidence/replay_run_subaccount \
  --confirm-risky

# Business outcome: validation error
python run_replay.py \
  --capability ../capabilities/open_subaccount.v1.json \
  --input member_id=67890 --input account_type="Money Market Account" --input initial_deposit=-5 \
  --evidence-dir ../evidence/replay_run_validation \
  --confirm-risky
```

Note: `open_subaccount` is flagged `risk_level: risky` (it writes
state) and refuses to run at all without `--confirm-risky` — try it
without the flag to see the guardrail block it before any browser
launches.

### 4. Human escalation, live

Trigger a real escalation with an impossible goal:
```bash
cd ../agent
python run_discovery.py \
  --goal "log in and then find a button labeled 'Launch Nuclear Codes' and click it" \
  --start-url http://127.0.0.1:5001/login \
  --evidence-dir ../evidence/discovery_run_escalation_demo
```
It will genuinely pause and print `HUMAN INTERVENTION REQUESTED`. In a
**second terminal**:
```bash
cd handoff
python resume.py ../evidence/discovery_run_escalation_demo
```
Switch back to the first terminal — it prints `[handoff] Resumed` and
continues on the *same* browser session. (Or, instead of the CLI, run
`python operator_console.py ../evidence/discovery_run_escalation_demo`
and open `http://127.0.0.1:5050` for a minimal web-based Resume button.)

### 5. Guardrails cleanup utility (one-off)

```bash
cd ../guardrails
python redact_existing_evidence.py
```
Scrubs any plaintext sensitive field values from discovery evidence
files that predate the redaction fix (see REPORT.md). New evidence is
redacted automatically at write time; this is only needed once, for
historical files.

## Running without live services

The only external dependency is the Gemini API (discovery only).
Replay, guardrails checks, and the target app all run fully locally
with no network access beyond `127.0.0.1`. There's no offline mode for
discovery itself — an LLM genuinely deciding what to do against a live
surface is the one thing that can't be simulated or skipped.

## Why this design

Legacy business software is everywhere, and most of it will never get
an API. The alternative to automating it well is either paying humans
to do repetitive UI work forever, or automating it badly (brittle
scripts that break on the first validation error or session timeout).
This project is a small, honest attempt at the middle path: pay an
LLM's cost once, during discovery, to figure out how a task works —
then never pay that cost again, because the result is a deterministic,
typed, reviewable capability that a much simpler system can run
reliably from then on.