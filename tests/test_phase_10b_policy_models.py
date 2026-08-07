from __future__ import annotations

from shared.db.models import (
    TimetablePolicyConstraint,
    TimetablePolicyConstraintVersion,
    TimetablePolicyException,
    TimetablePolicySet,
    TimetablePolicySetVersion,
)


def test_phase_10b_models_have_expected_table_names() -> None:
    assert TimetablePolicySet.__tablename__ == "timetable_policy_sets"
    assert TimetablePolicySetVersion.__tablename__ == "timetable_policy_set_versions"
    assert TimetablePolicyConstraint.__tablename__ == "timetable_policy_constraints"
    assert TimetablePolicyConstraintVersion.__tablename__ == "timetable_policy_constraint_versions"
    assert TimetablePolicyException.__tablename__ == "timetable_policy_exceptions"


def test_phase_10b_models_expose_expected_columns() -> None:
    policy_columns = TimetablePolicySet.__table__.columns
    assert "lifecycle_status" in policy_columns
    assert "version_number" in policy_columns
    assert "is_active" in policy_columns

    constraint_columns = TimetablePolicyConstraint.__table__.columns
    assert "constraint_type" in constraint_columns
    assert "enforcement_level" in constraint_columns
    assert "scope_type" in constraint_columns
    assert "parameters_json" in constraint_columns

    exception_columns = TimetablePolicyException.__table__.columns
    assert "approval_state" in exception_columns
    assert "expires_at" in exception_columns


def test_phase_10b_models_include_indexed_lookup_columns() -> None:
    policy_index_names = {idx.name for idx in TimetablePolicySet.__table__.indexes}
    assert "uq_timetable_policy_sets_active_scope" in policy_index_names

    constraint_index_names = {idx.name for idx in TimetablePolicyConstraint.__table__.indexes}
    assert "ix_timetable_policy_constraints_constraint_type" in constraint_index_names
    assert "ix_timetable_policy_constraints_scope_type" in constraint_index_names
