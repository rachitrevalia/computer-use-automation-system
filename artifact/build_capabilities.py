"""
Builds the two capability artifacts from the real discovery evidence in
/evidence/discovery_run_1 and /evidence/discovery_run_2.
"""

from schema import (
    Capability, CapabilityInput, CapabilityOutput, ArtifactStep,
    ExtractionLocator, SuccessCheckpoint, RiskLevel, ActionType,
)
from store import save_capability


def build_lookup_member_balance() -> Capability:
    return Capability(
        capability_id="legacybank.lookup_member_balance",
        name="Look up member savings balance",
        version=1,
        created_from_run_id="discovery_run_1",
        description=(
            "Logs into LegacyBank, searches for a member by ID, and reads their "
            "current savings balance. Read-only -- no state is changed."
        ),
        risk_level=RiskLevel.SAFE,
        start_url="http://127.0.0.1:5001/login",
        inputs=[
            CapabilityInput(
                name="member_id", type="string", required=True,
                description="The member ID to look up, e.g. '12345'.",
            ),
        ],
        outputs=[
            CapabilityOutput(
                name="savings_balance", type="string",
                description="The member's current savings balance as displayed, including the '$' sign.",
                extraction=ExtractionLocator(
                    source="frame_text",
                    frame_url_contains="/balance_frame",
                    near_text="Account Balance:",
                    extraction_pattern=r"\$[\d,]+\.\d{2}",
                ),
            ),
        ],
        steps=[
            ArtifactStep(
                step_number=1, action=ActionType.TYPE_TEXT,
                label_text="Username", value="{{secret:teller_username}}",
                locator_strategy="tier2_table_adjacent",
                locator_rationale=(
                    "No <label> element exists for this field in the legacy markup; "
                    "the visible 'Username' text is a plain table cell, not a real label. "
                    "Targeting via the adjacent-cell structural match is the only viable strategy."
                ),
                is_login_step=True,
            ),
            ArtifactStep(
                step_number=2, action=ActionType.TYPE_TEXT,
                label_text="Password", value="{{secret:teller_password}}",
                locator_strategy="tier2_table_adjacent",
                locator_rationale="Same reasoning as the Username field -- no real <label> exists.",
                is_login_step=True,
            ),
            ArtifactStep(
                step_number=3, action=ActionType.CLICK,
                target_text="Sign In",
                locator_strategy="tier1_role_button",
                locator_rationale=(
                    "This is a real <button>/submit control; its visible text IS its "
                    "accessible name, so role+name targeting is robust here."
                ),
                is_login_step=True,
            ),
            ArtifactStep(
                step_number=4, action=ActionType.TYPE_TEXT,
                label_text="Member ID", value="{member_id}",
                locator_strategy="tier2_table_adjacent",
                locator_rationale="No real <label> exists for the search field, same as the login fields.",
            ),
            ArtifactStep(
                step_number=5, action=ActionType.CLICK,
                target_text="Look Up",
                locator_strategy="tier1_role_button",
                locator_rationale="Real button control; visible text is its accessible name.",
            ),
        ],
        success_checkpoint=SuccessCheckpoint(
            checkpoint_type="page_contains_text",
            expected_text="Member Record",
            description=(
                "This heading only appears on a successfully rendered member detail "
                "page. The not-found, permission-denied, and session-expired pages "
                "each render distinct text instead, so this heading's presence "
                "reliably distinguishes real success from every other outcome we've "
                "observed."
            ),
        ),
    )


def build_open_subaccount() -> Capability:
    return Capability(
        capability_id="legacybank.open_subaccount",
        name="Open a new sub-account for a member",
        version=1,
        created_from_run_id="discovery_run_2",
        description=(
            "Logs into LegacyBank, looks up a member, opens a new sub-account of a "
            "specified type with an initial deposit, and reaches the confirmation "
            "screen. This is a WRITE action -- it creates a real sub-account record."
        ),
        risk_level=RiskLevel.RISKY,
        start_url="http://127.0.0.1:5001/login",
        inputs=[
            CapabilityInput(
                name="member_id", type="string", required=True,
                description="The member ID to open the sub-account for, e.g. '12345'.",
            ),
            CapabilityInput(
                name="account_type", type="string", required=True,
                description=(
                    "Visible dropdown option text for the account type, e.g. "
                    "'Money Market Account' or 'Certificate of Deposit'."
                ),
            ),
            CapabilityInput(
                name="initial_deposit", type="number", required=True,
                description="Initial deposit amount in USD, e.g. 500.",
            ),
        ],
        outputs=[
            CapabilityOutput(
                name="confirmation_number", type="string",
                description="The generated sub-account confirmation number, e.g. 'SUB-12345-1'.",
                extraction=ExtractionLocator(
                    source="main_tree",
                    near_text="Confirmation Number:",
                ),
            ),
            CapabilityOutput(
                name="deposit_amount", type="string",
                description="The confirmed initial deposit amount as displayed, including the '$' sign.",
                extraction=ExtractionLocator(
                    source="main_tree",
                    near_text="Initial Deposit:",
                    extraction_pattern=r"\$[\d,]+\.\d{2}",
                ),
            ),
        ],
        steps=[
            ArtifactStep(
                step_number=1, action=ActionType.TYPE_TEXT,
                label_text="Username", value="{{secret:teller_username}}",
                locator_strategy="tier2_table_adjacent",
                locator_rationale="No real <label> exists for this legacy login field.",
                is_login_step=True,
            ),
            ArtifactStep(
                step_number=2, action=ActionType.TYPE_TEXT,
                label_text="Password", value="{{secret:teller_password}}",
                locator_strategy="tier2_table_adjacent",
                locator_rationale="Same reasoning as the Username field.",
                is_login_step=True,
            ),
            ArtifactStep(
                step_number=3, action=ActionType.CLICK,
                target_text="Sign In",
                locator_strategy="tier1_role_button",
                locator_rationale="Real button control; visible text is its accessible name.",
                is_login_step=True,
            ),
            ArtifactStep(
                step_number=4, action=ActionType.TYPE_TEXT,
                label_text="Member ID", value="{member_id}",
                locator_strategy="tier2_table_adjacent",
                locator_rationale="No real <label> exists for the search field.",
            ),
            ArtifactStep(
                step_number=5, action=ActionType.CLICK,
                target_text="Look Up",
                locator_strategy="tier1_role_button",
                locator_rationale="Real button control; visible text is its accessible name.",
            ),
            ArtifactStep(
                step_number=6, action=ActionType.CLICK,
                target_text="Open New Sub-Account »",
                locator_strategy="tier1_role_link",
                locator_rationale=(
                    "This is an <a> link, not a button -- its visible text is still its "
                    "accessible name, so role=link targeting is robust."
                ),
            ),
            ArtifactStep(
                step_number=7, action=ActionType.SELECT_OPTION,
                label_text="Account Type", option_text="{account_type}",
                locator_strategy="tier2_table_adjacent",
                locator_rationale="The <select> has no real <label>; targeted via the adjacent table cell.",
            ),
            ArtifactStep(
                step_number=8, action=ActionType.TYPE_TEXT,
                label_text="Initial Deposit", value="{initial_deposit}",
                locator_strategy="tier2_table_adjacent",
                locator_rationale="No real <label> exists for this field either.",
            ),
            ArtifactStep(
                step_number=9, action=ActionType.CLICK,
                target_text="Continue »",
                locator_strategy="tier1_role_button",
                locator_rationale="Real submit-button control; visible text is its accessible name.",
            ),
        ],
        success_checkpoint=SuccessCheckpoint(
            checkpoint_type="page_contains_text",
            expected_text="Sub-Account Opened Successfully",
            description=(
                "This exact heading only renders after a real, successful sub-account "
                "creation. Note the URL alone can't be used as a checkpoint here: our "
                "target app renders the confirmation page directly on the form's POST "
                "response without a redirect, so the URL is identical to the form page's "
                "URL both before and after success. Content is the only reliable signal."
            ),
        ),
    )


if __name__ == "__main__":
    cap1 = build_lookup_member_balance()
    save_capability(cap1, "../capabilities/lookup_member_balance.v1.json")
    print(f"Saved: capabilities/lookup_member_balance.v1.json ({cap1.capability_id})")

    cap2 = build_open_subaccount()
    save_capability(cap2, "../capabilities/open_subaccount.v1.json")
    print(f"Saved: capabilities/open_subaccount.v1.json ({cap2.capability_id})")