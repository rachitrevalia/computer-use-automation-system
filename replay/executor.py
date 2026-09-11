"""
Deterministic replay engine -- the production execution path.

"""

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from browser_controller import BrowserController, LocatorFailure
from schema import Capability, ArtifactStep, ExtractionLocator, ActionType


BUSINESS_OUTCOME_MARKERS = [
    ("No member record found for ID", "member_not_found"),
    ("Access Denied.", "permission_denied"),
    ("Initial deposit must be a positive amount.", "validation_error"),
    ("Account type is required.", "validation_error"),
    ("Initial deposit must be a number.", "validation_error"),
]

RECOVERABLE_MARKERS = [
    ("Your session has expired.", "session_expired"),
]


class ReplayOutcome(str, Enum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    HARD_FAILURE = "hard_failure"


@dataclass
class ReplayResult:
    outcome: ReplayOutcome
    outputs: dict = field(default_factory=dict)
    business_outcome_type: Optional[str] = None
    business_outcome_detail: Optional[str] = None
    failed_step: Optional[int] = None
    expected: Optional[str] = None
    observed: Optional[str] = None
    screenshot_path: Optional[str] = None
    recovered_from: Optional[str] = None


def resolve_value(raw: Optional[str], inputs: dict) -> Optional[str]:
    """Substitute a "{param}" or "{{secret:name}}" placeholder with its real
    value. Anything else is a fixed literal and passes through unchanged."""
    if raw is None:
        return None

    secret_match = re.fullmatch(r"\{\{secret:([a-zA-Z0-9_]+)\}\}", raw)
    if secret_match:
        secret_name = secret_match.group(1)
        env_var = secret_name.upper()
        value = os.environ.get(env_var)
        if value is None:
            raise RuntimeError(
                f"Missing required secret '{secret_name}' -- set environment variable {env_var}"
            )
        return value

    param_match = re.fullmatch(r"\{([a-zA-Z0-9_]+)\}", raw)
    if param_match:
        name = param_match.group(1)
        if name not in inputs:
            raise RuntimeError(f"Missing required input parameter '{name}'")
        return str(inputs[name])

    return raw


def extract_output(browser: BrowserController, extraction: ExtractionLocator) -> str:
    """Deterministically pull one declared output's value from the current
    page, using its declared anchor text and optional regex -- not free-form
    model reading."""
    if extraction.source == "main_tree":
        text = browser.page.inner_text("body")
    else:  # frame_text
        text = ""
        for frame in browser.page.frames:
            if frame == browser.page.main_frame:
                continue
            if extraction.frame_url_contains and extraction.frame_url_contains in frame.url:
                text = frame.locator("body").inner_text()
                break

    idx = text.find(extraction.near_text)
    if idx == -1:
        raise ValueError(f"Could not find anchor text '{extraction.near_text}' while extracting output")

    window = text[idx: idx + 200]
    if extraction.extraction_pattern:
        m = re.search(extraction.extraction_pattern, window)
        if not m:
            raise ValueError(
                f"Anchor '{extraction.near_text}' found but pattern {extraction.extraction_pattern!r} "
                f"did not match nearby text: {window!r}"
            )
        return m.group(0)
    else:
        after = window[len(extraction.near_text):]
        return after.strip().split("\n")[0].strip()


class StepExecutionError(Exception):
    """Wraps a LocatorFailure with the step number it occurred on, so the
    top-level replay() call can report accurate 'failed at step N' detail."""
    def __init__(self, step_number: int, message: str):
        self.step_number = step_number
        super().__init__(message)


class CapabilityReplayer:
    def __init__(self, browser: BrowserController, evidence_dir: str):
        self.browser = browser
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._log_lines: list[str] = []

    def _log(self, line: str):
        self._log_lines.append(line)
        print(line, flush=True)

    def _current_page_text(self) -> str:
        try:
            return self.browser.page.inner_text("body")
        except Exception:
            return ""

    def _check_known_outcomes(self):
        text = self._current_page_text()
        for marker, outcome_type in BUSINESS_OUTCOME_MARKERS:
            if marker in text:
                return ("business_outcome", outcome_type, marker)
        for marker, outcome_type in RECOVERABLE_MARKERS:
            if marker in text:
                return ("recoverable", outcome_type, marker)
        return None

    def _execute_step(self, step: ArtifactStep, inputs: dict):
        if step.action == ActionType.NAVIGATE:
            self.browser.navigate(resolve_value(step.url, inputs))
        elif step.action == ActionType.CLICK:
            self.browser.click_via_tier(step.locator_strategy, resolve_value(step.target_text, inputs))
        elif step.action == ActionType.TYPE_TEXT:
            self.browser.type_text_via_tier(step.locator_strategy, step.label_text, resolve_value(step.value, inputs))
        elif step.action == ActionType.SELECT_OPTION:
            self.browser.select_option_via_tier(step.locator_strategy, step.label_text, resolve_value(step.option_text, inputs))
        else:
            raise RuntimeError(f"Unknown action type in artifact: {step.action}")

    def _run_steps(self, steps: list[ArtifactStep], inputs: dict):
        """Runs a sequence of steps. Returns None if all completed cleanly,
        or (kind, outcome_type, marker_text, step_number) if a known
        business/recoverable condition was hit mid-flow."""
        for step in steps:
            self._log(f"[replay] step {step.step_number}: {step.action.value}")
            try:
                self._execute_step(step, inputs)
            except LocatorFailure as e:
                self._save_failure_evidence(step.step_number)
                raise StepExecutionError(step.step_number, str(e)) from e

            outcome = self._check_known_outcomes()
            if outcome:
                return (*outcome, step.step_number)
        return None

    def _save_failure_evidence(self, step_number: int):
        try:
            self.browser.screenshot(str(self.evidence_dir / f"replay_failure_step_{step_number:02d}.png"))
        except Exception:
            pass

    def replay(self, capability: Capability, inputs: dict) -> ReplayResult:
        self._log(f"Replaying '{capability.capability_id}' v{capability.version} with inputs={inputs}")
        self.browser.navigate(capability.start_url)

        try:
            result_marker = self._run_steps(capability.steps, inputs)
        except StepExecutionError as e:
            return ReplayResult(
                outcome=ReplayOutcome.HARD_FAILURE,
                failed_step=e.step_number,
                expected="element to be found using the recorded locator strategy",
                observed=str(e),
                screenshot_path=str(self.evidence_dir / f"replay_failure_step_{e.step_number:02d}.png"),
            )

        recovered_from = None

        if result_marker is not None:
            kind, outcome_type, marker_text, step_number = result_marker

            if kind == "business_outcome":
                self._log(f"[replay] business outcome detected: {outcome_type} ({marker_text!r})")
                return ReplayResult(
                    outcome=ReplayOutcome.BUSINESS_OUTCOME,
                    business_outcome_type=outcome_type,
                    business_outcome_detail=marker_text,
                )

            elif kind == "recoverable" and outcome_type == "session_expired":
                self._log("[replay] session expiry detected -- attempting one-time recovery (re-login + restart)")
                login_steps = [s for s in capability.steps if s.is_login_step]
                non_login_steps = [s for s in capability.steps if not s.is_login_step]

                self.browser.navigate(capability.start_url)
                try:
                    self._run_steps(login_steps, inputs)
                    retry_marker = self._run_steps(non_login_steps, inputs)
                except StepExecutionError as e:
                    return ReplayResult(
                        outcome=ReplayOutcome.HARD_FAILURE,
                        failed_step=e.step_number,
                        expected="successful recovery after re-login",
                        observed=str(e),
                        screenshot_path=str(self.evidence_dir / f"replay_failure_step_{e.step_number:02d}.png"),
                        recovered_from="session_expired",
                    )

                recovered_from = "session_expired"
                if retry_marker is not None:
                    kind2, outcome_type2, marker_text2, step_number2 = retry_marker
                    if kind2 == "business_outcome":
                        return ReplayResult(
                            outcome=ReplayOutcome.BUSINESS_OUTCOME,
                            business_outcome_type=outcome_type2,
                            business_outcome_detail=marker_text2,
                            recovered_from=recovered_from,
                        )
                    else:
                        self._save_failure_evidence(step_number2)
                        return ReplayResult(
                            outcome=ReplayOutcome.HARD_FAILURE,
                            failed_step=step_number2,
                            expected="no interruption after recovery",
                            observed=f"recoverable condition recurred: {marker_text2}",
                            screenshot_path=str(self.evidence_dir / f"replay_failure_step_{step_number2:02d}.png"),
                            recovered_from=recovered_from,
                        )

            else:
                self._save_failure_evidence(step_number)
                return ReplayResult(
                    outcome=ReplayOutcome.HARD_FAILURE,
                    failed_step=step_number,
                    expected="no unrecognized interruption",
                    observed=marker_text,
                    screenshot_path=str(self.evidence_dir / f"replay_failure_step_{step_number:02d}.png"),
                )

        final_text = self._current_page_text()
        if capability.success_checkpoint.expected_text not in final_text:
            self._save_failure_evidence(len(capability.steps))
            return ReplayResult(
                outcome=ReplayOutcome.HARD_FAILURE,
                expected=f"page to contain '{capability.success_checkpoint.expected_text}'",
                observed=final_text[:300],
                screenshot_path=str(self.evidence_dir / f"replay_failure_step_{len(capability.steps):02d}.png"),
                recovered_from=recovered_from,
            )

        try:
            outputs = {out.name: extract_output(self.browser, out.extraction) for out in capability.outputs}
        except ValueError as e:
            return ReplayResult(
                outcome=ReplayOutcome.HARD_FAILURE,
                expected="declared outputs to be extractable from the final page",
                observed=str(e),
                screenshot_path=str(self.evidence_dir / "replay_failure.png"),
                recovered_from=recovered_from,
            )

        self.browser.screenshot(str(self.evidence_dir / "replay_success.png"))
        return ReplayResult(outcome=ReplayOutcome.SUCCESS, outputs=outputs, recovered_from=recovered_from)