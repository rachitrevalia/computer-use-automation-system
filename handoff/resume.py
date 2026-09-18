"""
CLI resume signal: flips control_state.json to "resumed" for a given
evidence directory. Equivalent to clicking "Resume" in operator_console.py
-- both just write the same file.

Usage: python resume.py ../evidence/discovery_run_X
"""
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print("Usage: python resume.py <evidence_dir>")
        sys.exit(1)
    state_path = Path(sys.argv[1]) / "control_state.json"
    if not state_path.exists():
        print(f"No control_state.json found at {state_path} -- is anything currently paused?")
        sys.exit(1)
    state = json.loads(state_path.read_text())
    if state.get("status") != "paused_for_human":
        print(f"Nothing is currently paused (status: {state.get('status')}). Nothing to resume.")
        sys.exit(1)
    state["status"] = "resumed"
    state_path.write_text(json.dumps(state, indent=2))
    print(f"Signaled resume for {sys.argv[1]}")


if __name__ == "__main__":
    main()