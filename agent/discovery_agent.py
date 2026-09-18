"""
The discovery agent: observe -> decide (Gemini) -> act loop.
"""

import concurrent.futures
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "guardrails"))
from policy import check_allowlist, redact_action_args, is_sensitive_label, PolicyViolation, REDACTED  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "handoff"))
from control import HandoffController, InterventionRequest  # noqa: E402

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from browser_controller import BrowserController, LocatorFailure
from action_schema import ACTION_TOOL

MODEL_NAME = "gemini-3.1-flash-lite"  # far higher free-tier daily quota than 3.6-flash (20 req/day was unworkable for iterative dev)
MAX_STEPS = 15
MAX_API_RETRIES = 4  # transient 503/429/hangs from Gemini are common on the free tier under load
DECIDE_TIMEOUT_SECONDS = 25  # application-level bound; see module docstring

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

SYSTEM_INSTRUCTION = """You are an automation agent operating a real web application on behalf of a bank operator. You can only interact with the page through the provided functions -- you have no other way to act.

Each turn you will be shown:
- the GOAL you are trying to accomplish
- the ACTION HISTORY so far (what you've already done, including any failures)
- the CURRENT PAGE STATE (an accessibility tree plus any embedded frame text)

You must call exactly one function per turn. Choose the single best next action.

Rules:
- Only interact with elements that are actually visible in the current page state. Do not guess at elements that aren't shown.
- If a page shows content inside "EMBEDDED FRAMES", that content is real and readable, even though it's not part of the main accessibility tree.
- If an action in your history is marked FAILED, do not blindly repeat it -- look at the current page state and adjust.
- If you reach the goal, call done() with the requested outputs, extracted exactly as shown on the page.
- If you hit something you don't recognize, or the same action fails repeatedly, call stuck() rather than guessing wildly.
- Never call done() unless the current page state actually shows the goal was achieved.
"""


@dataclass
class StepLog:
    step_number: int
    url: str
    action_name: str
    action_args: dict
    locator_tier: Optional[str] = None
    error: Optional[str] = None
    page_state_excerpt: str = ""


@dataclass
class DiscoveryResult:
    success: bool
    outputs: dict = field(default_factory=dict)
    summary: str = ""
    stuck_reason: Optional[str] = None
    steps: list = field(default_factory=list)


class DiscoveryAgent:
    def __init__(self, browser: BrowserController, evidence_dir: str):
        self.browser = browser
        self.client = genai.Client()  # reads GOOGLE_API_KEY from the environment automatically
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.history: list[str] = []
        self._all_logs: list[StepLog] = []
        self._sensitive_values: dict[str, str] = {}  # label_text -> value, for scrubbing the tree snapshot too
        self.handoff = HandoffController(evidence_dir=evidence_dir)
        self._escalation_used = False  # bounded: at most one escalation attempt per run
        (self.evidence_dir / "discovery_steps.jsonl").write_text("")

    def _build_prompt(self, goal: str, page_text: str) -> str:
        history_text = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(self.history)) or "(no actions yet)"
        return f"GOAL: {goal}\n\nACTION HISTORY:\n{history_text}\n\nCURRENT PAGE STATE:\n{page_text}\n"

    def _call_gemini(self, prompt: str):
        """Runs in a worker thread so we can bound our wait on it, regardless
        of whether the SDK's own timeout actually works (see module docstring)."""
        return self.client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=[ACTION_TOOL],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode="ANY")
                ),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                temperature=0.0,
            ),
        )

    def _decide(self, goal: str, page_text: str):
        prompt = self._build_prompt(goal, page_text)

        last_error = None
        for attempt in range(1, MAX_API_RETRIES + 1):
            future = _executor.submit(self._call_gemini, prompt)
            try:
                response = future.result(timeout=DECIDE_TIMEOUT_SECONDS)

            except concurrent.futures.TimeoutError:
                last_error = f"no response within {DECIDE_TIMEOUT_SECONDS}s (known SDK hang issue)"
                wait_seconds = 2 ** attempt
                print(
                    f"  [Gemini call exceeded {DECIDE_TIMEOUT_SECONDS}s with no response "
                    f"(known upstream SDK issue), attempt {attempt}/{MAX_API_RETRIES}. "
                    f"Retrying in {wait_seconds}s...]",
                    flush=True,
                )
                time.sleep(wait_seconds)
                continue

            except genai_errors.ServerError as e:
                last_error = e
                wait_seconds = 2 ** attempt
                print(
                    f"  [Gemini API transient error, attempt {attempt}/{MAX_API_RETRIES}: {e}. "
                    f"Retrying in {wait_seconds}s...]",
                    flush=True,
                )
                time.sleep(wait_seconds)
                continue

            except genai_errors.ClientError as e:
                if getattr(e, "code", None) == 429:
                    last_error = e
                    wait_seconds = 2 ** attempt
                    print(
                        f"  [Gemini API rate limited, attempt {attempt}/{MAX_API_RETRIES}. "
                        f"Retrying in {wait_seconds}s...]",
                        flush=True,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise  # any other 4xx (bad request, auth, etc.) is a real bug -- don't hide it

            else:
                calls = response.function_calls
                if not calls:
                    raise RuntimeError(f"Model returned no function call. Raw response: {response}")
                call = calls[0]
                return call.name, dict(call.args)

        raise RuntimeError(
            f"Gemini API still unavailable after {MAX_API_RETRIES} attempts. Last error: {last_error}"
        )

    def _redact_text(self, text: str) -> str:
        """Scrubs any previously-typed sensitive value out of arbitrary text
        (specifically, the accessibility tree snapshot, which echoes back
        whatever was typed into a field on subsequent observations -- a
        second leak channel beyond action_args)."""
        for value in self._sensitive_values.values():
            if value:
                text = text.replace(value, REDACTED)
        return text

    def _save_step(self, log: StepLog, screenshot: bool = False):
        self._all_logs.append(log)
        log_path = self.evidence_dir / "discovery_steps.jsonl"
        safe_args = redact_action_args(log.action_name, log.action_args)
        with open(log_path, "a") as f:
            f.write(
                json.dumps(
                    {
                        "step_number": log.step_number,
                        "url": log.url,
                        "action_name": log.action_name,
                        "action_args": safe_args,
                        "locator_tier": log.locator_tier,
                        "error": log.error,
                        "page_state_excerpt": self._redact_text(log.page_state_excerpt[:1500]),
                    }
                )
                + "\n"
            )
        if screenshot:
            try:
                self.browser.screenshot(str(self.evidence_dir / f"step_{log.step_number:02d}.png"))
            except Exception:
                pass

    def run(self, goal: str, start_url: str) -> DiscoveryResult:
        print(f"Starting discovery: navigating to {start_url}...", flush=True)
        check_allowlist(start_url)
        self.browser.navigate(start_url)
        print("Navigation complete.", flush=True)

        step_num = 0
        for step_num in range(1, MAX_STEPS + 1):
            print(f"[step {step_num}] observing page ({self.browser.page.url})...", flush=True)
            try:
                check_allowlist(self.browser.page.url)
            except PolicyViolation as e:
                return DiscoveryResult(success=False, stuck_reason=f"guardrail violation: {e}", steps=self._all_logs)

            state = self.browser.observe()
            page_text = state.to_prompt_text()

            print(f"[step {step_num}] asking Gemini for the next action...", flush=True)
            action_name, args = self._decide(goal, page_text)
            reasoning = args.get("reasoning", "")
            print(f"[step {step_num}] model chose: {action_name}({args})", flush=True)

            # Track sensitive values as they're typed, so later observations
            # of the same field (which echo the typed value back in the
            # accessibility tree) can be scrubbed before being saved.
            if action_name in ("type_text", "select_option"):
                label = args.get("label_text", "")
                if is_sensitive_label(label):
                    val = args.get("value") or args.get("option_text")
                    if val:
                        self._sensitive_values[label] = val

            log = StepLog(
                step_number=step_num,
                url=state.url,
                action_name=action_name,
                action_args=args,
                page_state_excerpt=page_text,
            )

            try:
                if action_name == "navigate":
                    self.browser.navigate(args["url"])
                    log.locator_tier = self.browser.last_locator_tier
                    self.history.append(f"navigate('{args['url']}') -- {reasoning}")

                elif action_name == "click":
                    self.browser.click(args["target_text"])
                    log.locator_tier = self.browser.last_locator_tier
                    self.history.append(f"click('{args['target_text']}') -- {reasoning}")

                elif action_name == "type_text":
                    self.browser.type_text(args["label_text"], args["value"])
                    log.locator_tier = self.browser.last_locator_tier
                    self.history.append(f"type_text('{args['label_text']}', '{args['value']}') -- {reasoning}")

                elif action_name == "select_option":
                    self.browser.select_option(args["label_text"], args["option_text"])
                    log.locator_tier = self.browser.last_locator_tier
                    self.history.append(
                        f"select_option('{args['label_text']}', '{args['option_text']}') -- {reasoning}"
                    )

                elif action_name == "done":
                    outputs = {}
                    raw_outputs = args.get("outputs_json", "{}")
                    try:
                        outputs = json.loads(raw_outputs)
                        if not isinstance(outputs, dict):
                            outputs = {"value": outputs}
                    except (json.JSONDecodeError, TypeError):
                        outputs = {"_unparsed": raw_outputs}
                    self._save_step(log, screenshot=True)
                    return DiscoveryResult(
                        success=True,
                        outputs=outputs,
                        summary=args.get("summary", ""),
                        steps=self._all_logs,
                    )

                elif action_name == "stuck":
                    self._save_step(log, screenshot=True)
                    if not self._escalation_used:
                        self._escalation_used = True
                        resumed = self.handoff.request_intervention(
                            self.browser,
                            InterventionRequest(
                                capability_or_goal=goal,
                                step_number=step_num,
                                reason=args.get("reason", ""),
                            ),
                        )
                        if resumed:
                            # Human fixed whatever was blocking progress; let the
                            # model see the current (human-modified) state and
                            # decide the next action normally.
                            self.history.append(
                                f"stuck({args.get('reason', '')}) -- escalated to a human, who resumed the run"
                            )
                            continue
                    return DiscoveryResult(
                        success=False,
                        stuck_reason=args.get("reason", ""),
                        steps=self._all_logs,
                    )

                else:
                    raise RuntimeError(f"Unknown action returned by model: {action_name}")

            except LocatorFailure as e:
                log.error = str(e)
                self._save_step(log, screenshot=True)
                self.history.append(f"{action_name}({args}) FAILED -- {e}")
                continue  # let the model see the failure next turn and adapt

            self._save_step(log)

        try:
            self.browser.screenshot(str(self.evidence_dir / f"step_{step_num:02d}_maxsteps.png"))
        except Exception:
            pass
        return DiscoveryResult(success=False, stuck_reason="max steps exceeded", steps=self._all_logs)