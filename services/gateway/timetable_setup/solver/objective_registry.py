from __future__ import annotations

from dataclasses import dataclass


PRIORITY_ORDER = ("critical", "high", "normal", "low")


@dataclass(frozen=True, slots=True)
class WeightedTerm:
    key: str
    priority: str
    coefficient: int
    max_penalty: int


def build_priority_coefficients(max_penalty_by_priority: dict[str, int]) -> dict[str, int]:
    total = sum(max(0, int(value)) for value in max_penalty_by_priority.values())
    base = max(2, total + 1)

    coeffs: dict[str, int] = {}
    for index, priority in enumerate(PRIORITY_ORDER):
        exponent = len(PRIORITY_ORDER) - index - 1
        coeffs[priority] = base**exponent
    return coeffs


def normalize_priority(value: str) -> str:
    lowered = (value or "normal").strip().lower()
    if lowered not in PRIORITY_ORDER:
        return "normal"
    return lowered
