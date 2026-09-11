"""
Load, save, and validate capability artifacts against the schema.
"""

import json
from pathlib import Path

from schema import Capability


def load_capability(path: str) -> Capability:
    """Read and validate a capability JSON file. Raises pydantic.ValidationError
    if the file doesn't conform to the schema -- fail loudly, not silently."""
    raw = Path(path).read_text()
    return Capability.model_validate_json(raw)


def save_capability(capability: Capability, path: str) -> None:
    """Write a capability to disk as pretty-printed, schema-valid JSON."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(capability.model_dump_json(indent=2))