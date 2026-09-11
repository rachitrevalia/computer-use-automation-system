"""
Action schema for the discovery agent's decision step.
"""

from google.genai import types

_REASONING_PARAM = {
    "type": "string",
    "description": "One or two sentences: why this action, given the current page state and the goal.",
}

ACTION_DECLARATIONS = [
    types.FunctionDeclaration(
        name="navigate",
        description="Go directly to a URL. Use only for the initial entry point or recovering from a dead end.",
        parameters={
            "type": "object", #type:ignore
            "properties": {
                "url": {"type": "string", "description": "Full URL to navigate to."},
                "reasoning": _REASONING_PARAM,
            },
            "required": ["url", "reasoning"],
        },
    ),
    types.FunctionDeclaration(
        name="click",
        description="Click a button or link identified by its visible text.",
        parameters={
            "type": "object", #type:ignore
            "properties": {
                "target_text": {
                    "type": "string",
                    "description": "The visible text of the button/link to click, exactly as shown.",
                },
                "reasoning": _REASONING_PARAM,
            },
            "required": ["target_text", "reasoning"],
        },
    ),
    types.FunctionDeclaration(
        name="type_text",
        description="Type a value into a form field identified by its visible label text.",
        parameters={
            "type": "object", #type:ignore
            "properties": {
                "label_text": {
                    "type": "string",
                    "description": "The visible label text next to the field, exactly as shown.",
                },
                "value": {"type": "string", "description": "The text to type into the field."},
                "reasoning": _REASONING_PARAM,
            },
            "required": ["label_text", "value", "reasoning"],
        },
    ),
    types.FunctionDeclaration(
        name="select_option",
        description="Choose an option in a dropdown identified by its visible label text.",
        parameters={
            "type": "object",  #type:ignore
            "properties": {
                "label_text": {
                    "type": "string",
                    "description": "The visible label text next to the dropdown.",
                },
                "option_text": {
                    "type": "string",
                    "description": "The visible text of the option to select.",
                },
                "reasoning": _REASONING_PARAM,
            },
            "required": ["label_text", "option_text", "reasoning"],
        },
    ),
    types.FunctionDeclaration(
        name="done",
        description="Call this when the goal has been fully accomplished. Provide the outputs the goal asked for.",
        parameters={
            "type": "object",  #type:ignore
            "properties": {
                "outputs": {
                    "type": "object",
                    "description": 'Key/value pairs of data the goal asked to extract, e.g. {"balance": "4210.55"}.',
                },
                "summary": {"type": "string", "description": "One sentence describing what was accomplished."},
                "reasoning": _REASONING_PARAM,
            },
            "required": ["outputs", "summary", "reasoning"],
        },
    ),
    types.FunctionDeclaration(
        name="stuck",
        description=(
            "Call this if you cannot safely proceed -- e.g. an unexpected error, a state "
            "you don't recognize, or an action that has failed repeatedly."
        ),
        parameters={
            "type": "object",  #type:ignore
            "properties": {
                "reason": {"type": "string", "description": "Clear description of what's blocking progress."},
                "reasoning": _REASONING_PARAM,
            },
            "required": ["reason", "reasoning"],
        },
    ),
]

ACTION_TOOL = types.Tool(function_declarations=ACTION_DECLARATIONS)