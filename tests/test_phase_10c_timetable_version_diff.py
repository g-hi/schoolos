from __future__ import annotations

from services.gateway.timetable_setup.timetable_versions import compute_version_diff


def _row(
    *,
    key: str,
    occurrence_id: str,
    class_id: str = "class_8a",
    teacher_id: str | None = "teacher_a",
    room_id: str | None = "r101",
    period_key: str = "d1:p3",
    occupied: list[str] | None = None,
    parallel_block_id: str | None = None,
    parallel_child_id: str | None = None,
) -> dict:
    return {
        "assignment_key": key,
        "occurrence_id": occurrence_id,
        "requirement_id": None,
        "class_id": class_id,
        "subject_id": "math",
        "teacher_id": teacher_id,
        "room_id": room_id,
        "day_key": "d1",
        "period_key": period_key,
        "periods_per_session": len(occupied or [period_key]),
        "occupied_period_keys": occupied or [period_key],
        "parallel_block_id": parallel_block_id,
        "parallel_child_id": parallel_child_id,
        "fixed": False,
        "lock_state": None,
    }


def test_diff_counts_single_occurrence_move_and_teacher_room_changes() -> None:
    left = [_row(key="occ1|", occurrence_id="occ1", teacher_id="teacher_a", room_id="r101", period_key="d1:p3")]
    right = [_row(key="occ1|", occurrence_id="occ1", teacher_id="teacher_b", room_id="r102", period_key="d1:p4")]

    payload = compute_version_diff(left, right)

    assert payload["counts"]["moved_period_or_span"] == 1
    assert payload["counts"]["teacher_changes"] == 1
    assert payload["counts"]["room_changes"] == 1


def test_diff_treats_multi_period_span_shift_as_one_move() -> None:
    left = [_row(key="occ2|", occurrence_id="occ2", period_key="d1:p3", occupied=["d1:p3", "d1:p4"])]
    right = [_row(key="occ2|", occurrence_id="occ2", period_key="d1:p4", occupied=["d1:p4", "d1:p5"])]

    payload = compute_version_diff(left, right)

    assert payload["counts"]["moved_period_or_span"] == 1
    assert payload["counts"]["unchanged"] == 0


def test_diff_parallel_block_class_facing_move_counted_once() -> None:
    left = [
        _row(key="occ_fl_french|child1", occurrence_id="occ_fl_french", parallel_block_id="pb1", parallel_child_id="child1", period_key="d1:p3"),
        _row(key="occ_fl_german|child2", occurrence_id="occ_fl_german", parallel_block_id="pb1", parallel_child_id="child2", period_key="d1:p3"),
        _row(key="occ_fl_spanish|child3", occurrence_id="occ_fl_spanish", parallel_block_id="pb1", parallel_child_id="child3", period_key="d1:p3"),
    ]
    right = [
        _row(key="occ_fl_french|child1", occurrence_id="occ_fl_french", parallel_block_id="pb1", parallel_child_id="child1", period_key="d1:p4"),
        _row(key="occ_fl_german|child2", occurrence_id="occ_fl_german", parallel_block_id="pb1", parallel_child_id="child2", period_key="d1:p4"),
        _row(key="occ_fl_spanish|child3", occurrence_id="occ_fl_spanish", parallel_block_id="pb1", parallel_child_id="child3", period_key="d1:p4"),
    ]

    payload = compute_version_diff(left, right)

    assert payload["counts"]["parallel_block_moves"] == 1
