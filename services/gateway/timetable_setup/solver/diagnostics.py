from __future__ import annotations

from services.gateway.timetable_setup.solver.contracts import SolverDiagnostic


def unsupported_hard_rule(*, entity_id: str, rule_type: str) -> SolverDiagnostic:
    return SolverDiagnostic(
        code="unsupported_hard_rule",
        message="A hard scheduling rule is unsupported by the current solver adapter registry.",
        severity="blocker",
        entity_type="rule",
        entity_id=entity_id,
        details={"rule_type": rule_type},
    )


def infeasible_result_hint() -> SolverDiagnostic:
    return SolverDiagnostic(
        code="infeasible_model",
        message="Model is infeasible under current hard constraints.",
        severity="blocker",
    )
