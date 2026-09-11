"""
One-off cleanup: redact sensitive field values in discovery evidence
files that were captured BEFORE the redaction guardrail existed
(discovery_run_1 and discovery_run_2's discovery_steps.jsonl both
contain the plaintext login password the LLM chose, e.g. "admin" /
"password" -- fake credentials, but the same pattern that would leak a
real one).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from policy import redact_action_args, is_sensitive_label, REDACTED  # noqa: E402

EVIDENCE_ROOT = Path(__file__).resolve().parent.parent / "evidence"


def redact_file(path: Path) -> int:
    lines = path.read_text().splitlines()
    if not lines:
        return 0

    # First pass: collect every sensitive value that was ever typed in this
    # run, so we can scrub it out of page_state_excerpt wherever it echoes
    # back (the same "tree leaks the typed value" issue fixed in the agent).
    sensitive_values = set()
    records = []
    for line in lines:
        rec = json.loads(line)
        records.append(rec)
        args = rec.get("action_args", {})
        label = args.get("label_text", "")
        if is_sensitive_label(label):
            val = args.get("value") or args.get("option_text")
            if val:
                sensitive_values.add(val)

    changed = 0
    out_lines = []
    for rec in records:
        original = json.dumps(rec)
        rec["action_args"] = redact_action_args(rec.get("action_name", ""), rec.get("action_args", {}))
        excerpt = rec.get("page_state_excerpt", "")
        for val in sensitive_values:
            if val and val in excerpt:
                excerpt = excerpt.replace(val, REDACTED)
        rec["page_state_excerpt"] = excerpt
        new_line = json.dumps(rec)
        if new_line != original:
            changed += 1
        out_lines.append(new_line)

    path.write_text("\n".join(out_lines) + "\n")
    return changed


def main():
    if not EVIDENCE_ROOT.exists():
        print(f"No evidence directory found at {EVIDENCE_ROOT}")
        return

    total_files = 0
    total_changed_lines = 0
    for jsonl_path in EVIDENCE_ROOT.rglob("discovery_steps.jsonl"):
        changed = redact_file(jsonl_path)
        total_files += 1
        total_changed_lines += changed
        print(f"{jsonl_path.relative_to(EVIDENCE_ROOT.parent)}: {changed} line(s) redacted")

    print(f"\nDone. {total_files} file(s) checked, {total_changed_lines} line(s) modified.")


if __name__ == "__main__":
    main()