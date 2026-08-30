
import argparse
import json
import os
import sys
from pathlib import Path

from browser_controller import BrowserController
from discovery_agent import DiscoveryAgent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True, help="Natural language goal for the agent to accomplish.")
    parser.add_argument("--start-url", required=True, help="Entry point URL for the target app.")
    parser.add_argument(
        "--evidence-dir",
        default="../evidence/discovery_run_1",
        help="Where to save step logs and screenshots.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser invisibly (default: visible, so you can watch it work).",
    )
    args = parser.parse_args()

    if not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY is not set in the environment. See README.md for setup.", file=sys.stderr)
        sys.exit(1)

    browser = BrowserController(headless=args.headless).start()
    agent = DiscoveryAgent(browser, evidence_dir=args.evidence_dir)

    try:
        result = agent.run(goal=args.goal, start_url=args.start_url)
    finally:
        browser.close()

    result_path = Path(args.evidence_dir) / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "goal": args.goal,
                "success": result.success,
                "outputs": result.outputs,
                "summary": result.summary,
                "stuck_reason": result.stuck_reason,
                "num_steps": len(result.steps),
            },
            indent=2,
        )
    )

    print()
    if result.success:
        print("SUCCESS")
        print(f"Summary: {result.summary}")
        print(f"Outputs: {result.outputs}")
    else:
        print("STOPPED (not successful)")
        print(f"Reason: {result.stuck_reason}")
    print(f"Steps taken: {len(result.steps)}")
    print(f"Evidence saved to: {args.evidence_dir}")


if __name__ == "__main__":
    main()