"""
Entry point: replay a saved capability artifact with no LLM involved.

"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "artifact"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
from store import load_capability  # noqa: E402
from browser_controller import BrowserController  # noqa: E402
from executor import CapabilityReplayer, ReplayOutcome
from schema import RiskLevel


def parse_inputs(pairs: list[str]) -> dict:
    result = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--input must be key=value, got: {pair}")
        key, value = pair.split("=", 1)
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", required=True, help="Path to a capability JSON artifact.")
    parser.add_argument("--input", action="append", default=[], help="key=value, repeatable.")
    parser.add_argument("--evidence-dir", default="../evidence/replay_run_1")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--confirm-risky",
        action="store_true",
        help="Required to execute a capability whose risk_level is 'risky' (e.g. anything that writes/mutates state).",
    )
    args = parser.parse_args()

    capability = load_capability(args.capability)
    inputs = parse_inputs(args.input)

    if capability.risk_level == RiskLevel.RISKY and not args.confirm_risky:
        print(
            f"REFUSING TO RUN: '{capability.capability_id}' is flagged risk_level=risky "
            f"(it writes/mutates state and may be hard to reverse). "
            f"Re-run with --confirm-risky to proceed. No browser was launched.",
            file=sys.stderr,
        )
        sys.exit(2)

    browser = BrowserController(headless=args.headless).start()
    replayer = CapabilityReplayer(browser, evidence_dir=args.evidence_dir)

    try:
        result = replayer.replay(capability, inputs)
    finally:
        browser.close()

    result_dict = {
        "capability_id": capability.capability_id,
        "inputs": inputs,
        "outcome": result.outcome.value,
        "outputs": result.outputs,
        "business_outcome_type": result.business_outcome_type,
        "business_outcome_detail": result.business_outcome_detail,
        "failed_step": result.failed_step,
        "expected": result.expected,
        "observed": result.observed,
        "recovered_from": result.recovered_from,
    }
    Path(args.evidence_dir).mkdir(parents=True, exist_ok=True)
    Path(args.evidence_dir, "result.json").write_text(json.dumps(result_dict, indent=2))

    print()
    print(f"OUTCOME: {result.outcome.value.upper()}")
    if result.outcome == ReplayOutcome.SUCCESS:
        print(f"Outputs: {result.outputs}")
    elif result.outcome == ReplayOutcome.BUSINESS_OUTCOME:
        print(f"Type: {result.business_outcome_type} -- {result.business_outcome_detail}")
    else:
        print(f"Failed at step: {result.failed_step}")
        print(f"Expected: {result.expected}")
        print(f"Observed: {result.observed}")
    if result.recovered_from:
        print(f"(recovered from: {result.recovered_from})")
    print(f"Evidence saved to: {args.evidence_dir}")


if __name__ == "__main__":
    main()