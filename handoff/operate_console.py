"""
Minimal mock operator console: a single local Flask page showing the
current intervention request (if any) for a given evidence directory,
with a Resume button. Deliberately bare -- the brief explicitly allows
mocking the operator UI. What has to be real is the underlying
control_state.json handoff mechanism this console reads and writes,
which is the exact same file resume.py uses from a terminal.

Usage: python operator_console.py ../evidence/discovery_run_X
Then open http://127.0.0.1:5050 in a browser.
"""
import json
import sys
from pathlib import Path

from flask import Flask, redirect, send_file

app = Flask(__name__)
EVIDENCE_DIR = None


def state_path():
    return EVIDENCE_DIR / "control_state.json"


@app.route("/")
def index():
    try:
        state = json.loads(state_path().read_text())
    except Exception:
        state = {"status": "automated"}

    if state.get("status") != "paused_for_human":
        return f"<h2>No intervention currently requested.</h2><p>Status: {state.get('status')}</p>"

    screenshot_tag = '<img src="/screenshot" width="700">' if state.get("screenshot_before") else ""
    return f"""
    <h2>Human Intervention Requested</h2>
    <p><b>Capability/goal:</b> {state.get('capability_or_goal')}</p>
    <p><b>Step:</b> {state.get('step_number')}</p>
    <p><b>Reason:</b> {state.get('reason')}</p>
    {screenshot_tag}
    <p>The automation's browser window is still open on the host machine --
    operate it directly to fix the issue, then click Resume.</p>
    <form method="post" action="/resume"><button type="submit">Resume</button></form>
    """


@app.route("/screenshot")
def screenshot():
    return send_file(EVIDENCE_DIR / "handoff_before.png")


@app.route("/resume", methods=["POST"])
def resume():
    try:
        state = json.loads(state_path().read_text())
    except Exception:
        state = {}
    state["status"] = "resumed"
    state_path().write_text(json.dumps(state, indent=2))
    return redirect("/")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python operator_console.py <evidence_dir>")
        sys.exit(1)
    EVIDENCE_DIR = Path(sys.argv[1])
    app.run(host="127.0.0.1", port=5050)