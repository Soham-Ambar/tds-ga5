from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel


router = APIRouter()


class RunControlResponse(BaseModel):
    decision: str
    reason: str


# ============================================================
# Response helpers
# ============================================================

def continue_run(reason: str) -> dict[str, str]:
    return {
        "decision": "continue",
        "reason": reason,
    }


def halt_run(reason: str) -> dict[str, str]:
    return {
        "decision": "halt",
        "reason": reason,
    }


# ============================================================
# Argument canonicalisation
# ============================================================

def normalize_string(value: str) -> str:
    """
    Ignore whitespace-only differences inside string values.

    Examples:
        " hello   world "
        "hello world"

    Both become:
        "hello world"
    """

    return re.sub(r"\s+", " ", value).strip()


def canonicalize_value(value: Any) -> Any:
    """
    Recursively canonicalise JSON-compatible data.

    Rules:
    - Ignore dictionary key order.
    - Remove every field literally named trace_id.
    - Normalise whitespace inside strings.
    - Preserve meaningful differences in numbers, booleans, arrays, etc.
    """

    if isinstance(value, dict):
        canonical_dictionary: dict[str, Any] = {}

        for key in sorted(value.keys()):
            # Only the exact field name trace_id is ignored.
            if key == "trace_id":
                continue

            canonical_dictionary[key] = canonicalize_value(
                value[key]
            )

        return canonical_dictionary

    if isinstance(value, list):
        # Array order can affect tool behaviour, so preserve it.
        return [
            canonicalize_value(item)
            for item in value
        ]

    if isinstance(value, str):
        return normalize_string(value)

    # Preserve numbers, booleans and null.
    return value


def canonicalize_args(args: Any) -> str:
    """
    Turn canonicalised arguments into a deterministic string.

    json.dumps with sort_keys=True ensures stable dictionary ordering.
    """

    canonical_value = canonicalize_value(args)

    return json.dumps(
        canonical_value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def step_signature(step: dict[str, Any]) -> tuple[str, str]:
    """
    A tool call is identified by:
      1. its tool name
      2. its canonicalised arguments

    step_number and tokens_used do not affect what action was performed.
    """

    tool = step.get("tool")
    args = step.get("args", {})

    normalized_tool = (
        tool.strip()
        if isinstance(tool, str)
        else str(tool)
    )

    return (
        normalized_tool,
        canonicalize_args(args),
    )


# ============================================================
# Loop detection
# ============================================================

def has_three_identical_calls_in_a_row(
    steps: list[dict[str, Any]],
) -> bool:
    """
    Detect a trailing run of at least three functionally identical calls.

    The policy asks us to examine trailing steps. Therefore, only the
    repeated sequence at the end of the current history determines whether
    the agent is presently stuck.
    """

    if len(steps) < 3:
        return False

    final_signature = step_signature(steps[-1])
    consecutive_count = 1

    for index in range(len(steps) - 2, -1, -1):
        current_signature = step_signature(steps[index])

        if current_signature != final_signature:
            break

        consecutive_count += 1

        if consecutive_count >= 3:
            return True

    return False


def has_trailing_two_step_cycle(
    steps: list[dict[str, Any]],
) -> bool:
    """
    Detect a trailing alternating cycle:

        A, B, A, B, A, B

    Six trailing calls are sufficient. A and B must be different; otherwise
    the pattern is a one-call repeat handled by the three-identical rule.
    """

    if len(steps) < 6:
        return False

    signatures = [
        step_signature(step)
        for step in steps
    ]

    # The last six must alternate.
    last_six = signatures[-6:]

    pattern_a = last_six[0]
    pattern_b = last_six[1]

    if pattern_a == pattern_b:
        return False

    expected = [
        pattern_a,
        pattern_b,
        pattern_a,
        pattern_b,
        pattern_a,
        pattern_b,
    ]

    return last_six == expected


# ============================================================
# Budget calculation
# ============================================================

def calculate_tokens_used(
    steps: list[dict[str, Any]],
) -> int:
    total = 0

    for step in steps:
        tokens_used = step.get("tokens_used", 0)

        # The assignment specifies integers, but this prevents malformed
        # values from crashing the service.
        if isinstance(tokens_used, bool):
            continue

        if isinstance(tokens_used, int):
            total += tokens_used

    return total


# ============================================================
# Main policy engine
# ============================================================

def evaluate_run(
    budget_tokens: Any,
    steps: Any,
) -> dict[str, str]:
    if not isinstance(budget_tokens, int) or isinstance(
        budget_tokens,
        bool,
    ):
        return halt_run(
            "A valid integer token budget is required."
        )

    if not isinstance(steps, list):
        return halt_run(
            "The run history must be supplied as a list of steps."
        )

    valid_steps = [
        step
        for step in steps
        if isinstance(step, dict)
    ]

    cumulative_tokens = calculate_tokens_used(valid_steps)

    # Budget and looping are independent. Either condition is sufficient
    # to halt. Checking budget first gives the clearest reason when spent.
    if cumulative_tokens >= budget_tokens:
        return halt_run(
            f"Cumulative tokens_used ({cumulative_tokens}) has reached "
            f"the budget ({budget_tokens})."
        )

    if has_three_identical_calls_in_a_row(valid_steps):
        return halt_run(
            "The same tool call has repeated at least three times "
            "consecutively without meaningful argument changes."
        )

    if has_trailing_two_step_cycle(valid_steps):
        return halt_run(
            "The trailing run history contains a repeated two-step "
            "A/B cycle of at least six steps."
        )

    if not valid_steps:
        return continue_run(
            "The run is under budget and has no prior steps."
        )

    return continue_run(
        f"Cumulative tokens_used ({cumulative_tokens}) is below the "
        f"budget ({budget_tokens}), and no tool-call loop was detected."
    )


@router.post(
    "/run-control",
    response_model=RunControlResponse,
)
def run_control(
    payload: dict[str, Any] = Body(...),
) -> dict[str, str]:
    return evaluate_run(
        budget_tokens=payload.get("budget_tokens"),
        steps=payload.get("steps"),
    )
