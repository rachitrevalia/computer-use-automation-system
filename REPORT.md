# REPORT.md

## 1. Architecture

The system is a single Python process, deliberately not split into
services — the brief explicitly warns against building scaling
infrastructure prematurely, and a thin-but-real vertical slice doesn't
need queues or microservices to prove the design works. It has six
components, each with one job:

- **`target_app/`** — a deliberately legacy-styled Flask app (no test
  IDs, table-based layout, an `<iframe>` panel, a short session TTL,
  and deterministic `?simulate=` triggers) standing in for a real
  bank back-office screen with no API.
- **`agent/`** — the discovery loop: `browser_controller.py` (Playwright
  perception/action wrapper) and `discovery_agent.py` (the Gemini
  observe→decide→act loop).
- **`artifact/`** — the capability schema (`schema.py`, Pydantic) and a
  load/save/validate layer (`store.py`).
- **`replay/`** — `executor.py`, which loads a capability and drives the
  browser deterministically, with zero LLM calls.
- **`guardrails/`** — allowlist enforcement, a risky-action confirmation
  gate, and label-based secret redaction.
- **`handoff/`** — the human escalation and control-transfer mechanism.

**Key trade-off:** perception uses Playwright's ARIA accessibility
snapshot (`page.aria_snapshot()`) rather than raw HTML, because our
target app has no test IDs and messy table markup — the accessibility
tree is far more semantically stable. This snapshot doesn't cross into
`<iframe>` content (a real Playwright/browser limitation), so we add a
second channel: extracted text from every embedded frame, clearly
labeled as such. This two-channel perception model is the seam that
would extend to a desktop app later (Section 4).

**Locator strategy** is two-tier: accessible role+name first (works for
buttons/links, whose visible text *is* their accessible name), falling
back to a structural "find the table cell with this label text, grab
the adjacent input" match for form fields, since our legacy markup has
no real `<label>` elements. Discovery tries both tiers live; replay
skips straight to whichever tier the artifact recorded, since re-trying
tier 1 (which we already know fails) wastes a full timeout on every
label-less field — a real bug we found and fixed while testing.

**Model choice:** Gemini (`gemini-3.1-flash-lite`), chosen
purely for a genuinely free API tier with no credit card. Mid-build we
also had to swap from `gemini-3.6-flash` after discovering its free
tier caps at 20 requests/day — an example of a real constraint (rate
limits, SDK hangs — see Section 3) surfacing during actual use rather
than being anticipated up front.

## 2. Artifact schema

The `Capability` schema (`artifact/schema.py`) is the contract between
discovery and replay. Design decisions:

- **Steps store parameters, not literal values.** Where discovery typed
  `"12345"`, the artifact stores `"{member_id}"`, resolved from a
  declared `CapabilityInput` at replay time. This is what makes an
  artifact reusable rather than a frozen replay of one run — verified
  directly: our `open_subaccount` capability replayed successfully with
  a different member, account type, and deposit amount than discovery
  ever saw.
- **Credentials are never literal, even for this mock app's fake login.**
  A step needing a credential references `"{{secret:name}}"`, resolved
  from an environment variable at replay time, never written to the
  artifact JSON. This is the correct pattern regardless of whether
  today's secret is real.
- **Output extraction is declarative.** Each `CapabilityOutput` carries
  an `ExtractionLocator` — which perception channel (main tree vs. a
  named frame), an anchor text, and an optional regex — rather than
  trusting free-form re-reading on every future run.
- **Every step's locator strategy carries its own rationale**
  (`locator_rationale`), captured from the actual discovery evidence,
  so a human reviewer can see *why* each targeting choice is expected
  to be robust, not just *what* it is.
- **Versioned and traceable**: `schema_version`, `version`, and
  `created_from_run_id` point straight back to the `/evidence/` folder
  that produced the artifact, so "was this genuinely discovered live?"
  is always answerable.

## 3. Determinism & error handling

Replay (`replay/executor.py`) makes zero LLM calls. Determinism comes
from: recorded locator tiers (no live fallback search), parameter
substitution instead of free-text generation, and a content-based
success checkpoint.

**The checkpoint is deliberately content-based, not URL-based** — we
found a real case where these disagree: our target app renders the
sub-account confirmation page directly on the form's POST response
without a redirect, so the URL is identical before and after success.
A URL checkpoint would misreport success as failure.

**The three-way outcome split** (`ReplayOutcome`: `SUCCESS`,
`BUSINESS_OUTCOME`, `HARD_FAILURE`) is a small, auditable marker table
matched against visible page text — e.g. `"No member record found"` →
`member_not_found`, a legitimate result, not a crash. Verified live:
member `00000` (doesn't exist) and member `99999` (locked) both
correctly return `BUSINESS_OUTCOME`, not failures.

**Session expiry gets a real, bounded recovery**, not just a label: on
detection, the replayer re-runs the capability's login steps (flagged
`is_login_step`) and retries the rest of the flow once from scratch. A
full restart-after-relogin was chosen over resuming mid-flow because
the app gives no guarantee partial form state survives a session
reset — restarting is the conservative, correct choice given that
uncertainty. Verified live with an artificially shortened session TTL.

**Real infrastructure problems surfaced and were fixed during
development, not hidden:** Gemini's SDK has a documented, open bug
where a request can hang indefinitely even with its own timeout
configured — fixed by running each call in a worker thread and bounding
our *wait* on it instead of trusting the SDK's timeout. Transient
503/429 errors get exponential-backoff retry. These are the same class
of "transient slowness" problem the brief describes for replay, just
occurring one layer up, at the model call during discovery.

## 4. Heterogeneity & multi-tenant

**Surface abstraction.** The seam between "how we perceive/act on a
surface" and "the recorded flow" is exactly the `BrowserController`
interface: `observe()` → `PageState`, and typed actions
(`click`/`type_text`/`select_option`). A legacy web app with framesets
instead of iframes would need `observe()` extended to walk `<frame>`
elements the same way it already walks `<iframe>`s — the artifact
schema doesn't change. A desktop app would need a different
`BrowserController` implementation entirely (backed by an OS
accessibility API instead of Playwright), but the *same* schema: OS
accessibility trees expose the same role/name model as ARIA, and
"click by accessible name" is a native desktop concept too.

**Multi-tenant reuse.** Right now, literal values like the target host
(`127.0.0.1:5001`) live in `start_url`; a real multi-tenant version
would canonicalize routes into patterns (e.g. `/member/:id`) and store
per-tenant config (host, branding-specific label text if it differs)
separately from the capability's step logic, with the artifact
referencing a tenant profile rather than a hardcoded host. Detecting
drift across tenants running the same vendor product would mean
replaying the *same* artifact against each tenant's instance
periodically and flagging locator failures — since our locator
strategy already reports which tier succeeded, a tenant where tier 1
suddenly fails and falls back to tier 2 is itself a drift signal worth
surfacing, even before a hard failure occurs.

## 5. Escalation & handoff

**The control-transfer model exploits a fact we already have:**
discovery and replay run with `headless=False` by default, so a real,
visible browser window sits on screen the entire time. "Ceding control"
means our own script simply stops calling actions and blocks — the
human can click directly into that *same* window, which was never
closed or replaced. "Resuming" means the script starts calling
`.observe()`/actions on that same `Page` object again, picking up
whatever state the human left it in.

**Who's in control** is tracked explicitly in `control_state.json`
(`automated` / `paused_for_human` / `resumed`) — not implicit. Resume
signaling has two equivalent paths: a CLI command (`resume.py`) or a
minimal mock operator console (`operator_console.py`, a bare Flask
page with the escalation context and a Resume button) — the brief
explicitly allows mocking the operator UI; what has to be real is the
underlying file both paths write to.

**Verified live, end to end, in both directions:** a discovery run was
given an impossible goal, correctly called `stuck()`, paused, printed
full context (goal, step, reason, screenshot), and genuinely blocked
until a separate terminal ran `resume.py` — then continued the loop.
Replay was tested the same way: a step's locator was made to fail once
(simulating something unexpected blocking it), escalation triggered,
and after resume the *same step* was retried and succeeded, completing
the capability with `escalated: true` recorded in the result.

**Documented limitation:** we capture a screenshot immediately before
and after the pause as a proxy for "what the human did," since we
can't introspect their actual clicks without a much heavier
co-browsing/session-recording layer. Escalation is also bounded to one
attempt per run — a deliberate safety property, not an oversight; an
escalation mechanism that can loop indefinitely is worse than none.

## 6. Safety

**Allowlist** (`guardrails/policy.py`) is host-based, checked before
the initial navigation and after every subsequent step in both
discovery and replay — not logged after the fact. Verified: a
deliberately constructed artifact pointing at `evil.example.com` was
blocked before any browser action ran.

**Risky actions require explicit confirmation, checked before the
browser even launches.** `open_subaccount` is flagged `risk_level:
risky` (it writes/mutates state); replay refuses to run it without
`--confirm-risky`, exiting with no browser launched at all. Verified
both directions: blocked without the flag, succeeds with it.

**Redaction is label-based, not value-based** — we can't reliably
detect "this looks like a secret" from a value alone, but we know which
UI fields are inherently sensitive by their label ("Password", "PIN",
"SSN", etc.). This caught a real leak during development: discovery
evidence originally logged the LLM's typed login password in plaintext
in two places — the action log itself, *and* the accessibility tree
snapshot on the *next* observation (since the browser echoes back what
was just typed). Both channels are now scrubbed, and the
already-committed evidence from before the fix was retroactively
redacted with a one-off script, documented rather than quietly patched
over.

## 7. Cuts

- **Artifact authoring from a discovery trace is semi-automated, not
  fully automatic.** Deciding which literal values become parameters,
  secrets, or fixed literals is a genuine judgment call; a developer
  reviews the evidence and authors the parameterization deliberately
  (`artifact/build_capabilities.py`), the same way a human would clean
  up a macro recording before shipping it. Fully automating this from
  one example run is closer to a research problem than a thin-but-real
  addition.
- **Multi-tenant and desktop support are designed for, not built** —
  per the brief's explicit guidance not to prematurely build scaling
  infrastructure. Section 4 above is the design answer.
- **The operator console is intentionally bare** — a single Flask page
  with no styling, no auth, no real-time co-browsing. What's real is
  the handoff mechanism it reads/writes, not its polish.
- **Escalation retries exactly once per run.** A human-fixes-and-retry
  loop that could recurse indefinitely is a worse failure mode than a
  single bounded attempt that then reports a clear hard failure.
- **What we'd build next with more time:** the agent-facing capability
  interface (a small catalog/invoke API an AI agent could call by
  name) — the most natural stretch goal given the whole system's
  framing; a smarter post-escalation prompt for discovery (right now,
  resuming just re-enters the normal loop with no special "you were
  just stuck" signal beyond one history line, which we saw lead to a
  repeat-until-max-steps outcome on a genuinely impossible goal during
  testing); and cross-tenant drift detection using the already-recorded
  locator tier as an early signal, described in Section 4.