"""
Capability artifact schema.
"""

from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    SAFE = "safe"        # read-only, fully reversible (e.g. looking up a balance)
    RISKY = "risky"       # writes/mutates state, may be hard to reverse (e.g. opening an account)


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE_TEXT = "type_text"
    SELECT_OPTION = "select_option"


class CapabilityInput(BaseModel):
    """A typed input the caller must supply per invocation."""
    name: str
    type: Literal["string", "number", "boolean"]
    required: bool = True
    description: str


class ExtractionLocator(BaseModel):
    """
    Where an output value lives on the page, declared explicitly rather
    than left to free-form model reading. `source` distinguishes the two
    real channels our perception layer has (see browser_controller.py):
    the main ARIA tree, or an embedded frame's extracted text (since the
    ARIA tree can't cross into iframes).
    """
    source: Literal["main_tree", "frame_text"]
    frame_url_contains: Optional[str] = None  # only used when source == "frame_text"
    near_text: str  # visible text near/labeling the value (e.g. "Account Balance:")
    extraction_pattern: Optional[str] = None  # optional regex if the value needs pulling out of surrounding text


class CapabilityOutput(BaseModel):
    """A typed output the caller receives back, with a deterministic
    rule for where it comes from -- not just a name and a hope."""
    name: str
    type: Literal["string", "number", "boolean"]
    description: str
    extraction: ExtractionLocator


class ArtifactStep(BaseModel):
    """
    One recorded action. `value_ref` / `target_text_ref` etc. use "{param}"
    syntax to reference a declared CapabilityInput, or "{{secret:name}}"
    for a credential resolved from the environment at replay time. Fixed
    literal values (e.g. clicking a button whose text never changes)
    are stored as plain strings with no braces.
    """
    step_number: int
    action: ActionType

    # Only the fields relevant to this action's type are populated.
    url: Optional[str] = None                 # navigate
    target_text: Optional[str] = None          # click (literal or "{param}"/"{{secret:x}}")
    label_text: Optional[str] = None           # type_text / select_option (usually literal -- it's a UI label, not user data)
    value: Optional[str] = None                # type_text ("{param}" or "{{secret:x}}")
    option_text: Optional[str] = None          # select_option ("{param}" or literal)

    locator_strategy: str  # e.g. "tier1_role_button", "tier2_table_adjacent" -- from discovery evidence
    locator_rationale: str  # human-readable justification, for the reviewer
    is_login_step: bool = False 


class SuccessCheckpoint(BaseModel):
    """
    Content-based assertion that the goal was actually reached --
    deliberately NOT URL-based (see design note 4 above).
    """
    checkpoint_type: Literal["page_contains_text"]
    expected_text: str
    description: str  # why this text proves success, for a human reviewer


class Capability(BaseModel):
    """The complete, versioned, reviewable capability artifact."""

    schema_version: str = "1.0"
    capability_id: str
    name: str
    version: int = 1
    created_from_run_id: str  # e.g. "discovery_run_1" -- points at /evidence/
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    description: str  # human-readable: what this capability does
    risk_level: RiskLevel

    inputs: list[CapabilityInput]
    outputs: list[CapabilityOutput]
    steps: list[ArtifactStep]
    success_checkpoint: SuccessCheckpoint

    # Where a replay run should start -- the entry point URL.
    start_url: str