"""
Image quality validation for scanned exam pages.

The quality checker returns a QualityResult for every uploaded page.
Low-quality pages ask the teacher to retake — they are never silently
accepted for processing.

Warning codes (quality_warnings list):
    blur                    — image is out of focus
    glare                   — reflective glare obscures content
    low_lighting            — image is too dark
    cropped_page            — page edges are cut off
    wrong_orientation       — page is rotated
    incomplete_page         — not all expected content is visible
    obstruction             — fingers or objects covering content
    perspective_distortion  — excessive keystone / skew

V1 uses a deterministic simulation for all checks.
Future: swap ImageQualityChecker for a computer-vision implementation
(OpenCV Laplacian variance for blur, histogram for lighting, etc.)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QualityResult:
    quality_score: float            # 0.0 – 1.0
    warnings: list[str]             # list of warning codes above
    retake_required: bool           # True if quality_score < threshold
    accepted_for_processing: bool   # False if retake_required
    threshold_used: float


# Configurable thresholds
_DEFAULT_THRESHOLD = 0.60
_RETAKE_THRESHOLD = 0.40


class ImageQualityChecker:
    """
    Validates a scanned image for processing suitability.

    V1: deterministic simulation — accepts all images with storage_key
        containing "low_quality" as a smoke-test trigger; accepts everything else.

    Future: replace _run_checks() with computer-vision analysis.
    """

    def __init__(self, retake_threshold: float = _RETAKE_THRESHOLD) -> None:
        self._threshold = retake_threshold

    def check(self, storage_key: str, source: str = "upload") -> QualityResult:
        warnings = self._run_checks(storage_key)
        score = self._compute_score(warnings)
        retake = score < self._threshold
        return QualityResult(
            quality_score=round(score, 3),
            warnings=warnings,
            retake_required=retake,
            accepted_for_processing=not retake,
            threshold_used=self._threshold,
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    def _run_checks(self, storage_key: str) -> list[str]:
        """
        V1 deterministic checks.

        Trigger keywords in storage_key allow tests to exercise each path:
            "low_quality"  → blur + low_lighting  (retake required)
            "glare"        → glare warning
            "cropped"      → cropped_page warning
        """
        key_lower = storage_key.lower()
        warnings: list[str] = []

        if "low_quality" in key_lower:
            warnings.extend(["blur", "low_lighting"])
        if "glare" in key_lower:
            warnings.append("glare")
        if "cropped" in key_lower:
            warnings.append("cropped_page")

        return warnings

    @staticmethod
    def _compute_score(warnings: list[str]) -> float:
        # Each warning reduces quality score.
        penalty_map = {
            "blur": 0.30,
            "low_lighting": 0.25,
            "glare": 0.20,
            "cropped_page": 0.20,
            "wrong_orientation": 0.15,
            "incomplete_page": 0.25,
            "obstruction": 0.30,
            "perspective_distortion": 0.20,
        }
        total_penalty = sum(penalty_map.get(w, 0.10) for w in warnings)
        return max(0.0, 1.0 - total_penalty)
