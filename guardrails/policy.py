"""
Guardrails: allowlist enforcement, risky-action confirmation, and secret
redaction. Deliberately small and readable -- these are policy decisions
a human reviewer should be able to read in one pass, not opaque logic
buried inside the executor.
"""

import re
from urllib.parse import urlparse

ALLOWED_HOSTS = {"127.0.0.1:5001"}

SENSITIVE_LABEL_PATTERNS = [
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"\bpin\b", re.IGNORECASE),
    re.compile(r"ssn", re.IGNORECASE),
    re.compile(r"social security", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"\btoken\b", re.IGNORECASE),
    re.compile(r"cvv", re.IGNORECASE),
]

REDACTED = "***REDACTED***"


class PolicyViolation(Exception):
    """Raised when an action would step outside the configured allowlist."""


def check_allowlist(url: str) -> None:
    """Raises PolicyViolation if url's host isn't in ALLOWED_HOSTS.
    Called before every navigation/action, in both discovery and replay --
    the agent must not act outside this, full stop, not just be logged
    doing so."""
    host = urlparse(url).netloc
    if host not in ALLOWED_HOSTS:
        raise PolicyViolation(
            f"URL '{url}' has host '{host}', which is not in the allowlist "
            f"{sorted(ALLOWED_HOSTS)}. Refusing to proceed."
        )


def is_sensitive_label(label_text: str) -> bool:
    if not label_text:
        return False
    return any(p.search(label_text) for p in SENSITIVE_LABEL_PATTERNS)


def redact_action_args(action_name: str, args: dict) -> dict:
    """Returns a COPY of args with sensitive values replaced by a redaction
    marker. Never mutates the original -- the real value is still needed
    to actually execute the action; only the logged/persisted copy is
    redacted."""
    redacted = dict(args)
    label = args.get("label_text", "")
    if action_name in ("type_text", "select_option") and is_sensitive_label(label):
        if "value" in redacted:
            redacted["value"] = REDACTED
        if "option_text" in redacted:
            redacted["option_text"] = REDACTED
    return redacted