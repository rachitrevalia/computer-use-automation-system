"""
Human-in-the-loop escalation & handoff.

"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class InterventionRequest:
    capability_or_goal: str
    step_number: Optional[int]
    reason: str


class HandoffController:
    def __init__(self, evidence_dir: str, poll_interval_seconds: float = 1.0, timeout_seconds: float = 600.0):
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.evidence_dir / "control_state.json"
        self.events_path = self.evidence_dir / "handoff_events.jsonl"
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._write_state({"status": "automated"})

    def _write_state(self, state: dict):
        self.state_path.write_text(json.dumps(state, indent=2))

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except Exception:
            return {"status": "automated"}

    def request_intervention(self, browser, request: InterventionRequest) -> bool:
        """Pauses automation and blocks until a human signals resume (via
        the operator console or resume.py), or until timeout_seconds
        elapses. Returns True if resumed in time, False on timeout --
        callers should treat a timeout as a hard failure, not wait forever."""
        try:
            browser.screenshot(str(self.evidence_dir / "handoff_before.png"))
        except Exception:
            pass

        state = {
            "status": "paused_for_human",
            "capability_or_goal": request.capability_or_goal,
            "step_number": request.step_number,
            "reason": request.reason,
            "screenshot_before": "handoff_before.png",
            "requested_at": time.time(),
        }
        self._write_state(state)

        print("\n" + "=" * 70)
        print("HUMAN INTERVENTION REQUESTED")
        print(f"  Capability/goal : {request.capability_or_goal}")
        print(f"  Step            : {request.step_number}")
        print(f"  Reason          : {request.reason}")
        print(f"  Screenshot      : {self.evidence_dir / 'handoff_before.png'}")
        print("  The browser window is still open -- operate it directly to fix the issue.")
        print(f"  To resume: run `python resume.py {self.evidence_dir}` from the handoff/ folder,")
        print("  or open the operator console (operator_console.py) and click Resume.")
        print("=" * 70 + "\n")

        waited = 0.0
        resumed = False
        while waited < self.timeout_seconds:
            current = self._read_state()
            if current.get("status") == "resumed":
                resumed = True
                break
            time.sleep(self.poll_interval_seconds)
            waited += self.poll_interval_seconds

        if not resumed:
            self._log_event(state, resumed=False)
            return False

        try:
            browser.screenshot(str(self.evidence_dir / "handoff_after.png"))
        except Exception:
            pass
        self._log_event(state, resumed=True)
        self._write_state({"status": "automated"})
        print("[handoff] Resumed -- automation is back in control.\n")
        return True

    def _log_event(self, state: dict, resumed: bool):
        with open(self.events_path, "a") as f:
            f.write(
                json.dumps({**state, "resumed": resumed, "resumed_at": time.time() if resumed else None}) + "\n"
            )