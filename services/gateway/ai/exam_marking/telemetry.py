"""
Processing telemetry for every provider execution in the Marking Studio.

Each ProviderTelemetry record is appended to SchoolOSAIState.execution_trace
via .to_trace_event() so the existing observability_node picks it up
automatically — no new infrastructure required.

Fields:
    provider_name     — e.g. "deterministic_omr", "groq_rubric_ai"
    strategy_name     — e.g. "scantron_omr", "open_ended"
    operation         — granular step, e.g. "bubble_detection", "ocr_extraction"
    question_number   — None for page-level operations
    started_at_iso    — ISO-8601 UTC timestamp
    finished_at_iso   — ISO-8601 UTC timestamp
    duration_ms       — wall-clock ms
    confidence        — provider-reported confidence (0.0–1.0) or None
    retry_count       — how many times this specific call was retried
    token_usage       — {prompt_tokens, completion_tokens, total_tokens}
    estimated_cost_usd — estimated USD cost (0.0 for deterministic providers)
    status            — success | failed | retried | skipped
    error_message     — sanitised message, no PII or raw student content
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any


@dataclass
class ProviderTelemetry:
    provider_name: str
    strategy_name: str
    operation: str
    question_number: int | None
    started_at_iso: str
    finished_at_iso: str
    duration_ms: float
    confidence: float | None
    retry_count: int
    token_usage: dict[str, int]
    estimated_cost_usd: float
    status: str  # success | failed | retried | skipped
    error_message: str | None  # sanitised — never contains raw student answers

    def to_trace_event(self) -> dict[str, Any]:
        """Convert to a trace event dict compatible with SchoolOSAIState.execution_trace."""
        return {
            "node": f"provider:{self.provider_name}:{self.operation}",
            "latency_ms": self.duration_ms,
            "provider_telemetry": asdict(self),
        }


class TelemetryCollector:
    """
    Context-manager–style helper that records start/finish times and
    returns a ProviderTelemetry instance.

    Usage:
        collector = TelemetryCollector("deterministic_omr", "scantron_omr", "bubble_detection")
        collector.start()
        # ... do work ...
        telemetry = collector.finish(confidence=0.98)
    """

    def __init__(
        self,
        provider_name: str,
        strategy_name: str,
        operation: str,
        question_number: int | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.strategy_name = strategy_name
        self.operation = operation
        self.question_number = question_number
        self._started_at: float | None = None
        self._started_iso: str | None = None

    def start(self) -> "TelemetryCollector":
        self._started_at = perf_counter()
        self._started_iso = datetime.now(timezone.utc).isoformat()
        return self

    def finish(
        self,
        confidence: float | None = None,
        retry_count: int = 0,
        token_usage: dict[str, int] | None = None,
        estimated_cost_usd: float = 0.0,
        status: str = "success",
        error_message: str | None = None,
    ) -> ProviderTelemetry:
        if self._started_at is None:
            raise RuntimeError("TelemetryCollector.start() must be called before finish()")

        finished_iso = datetime.now(timezone.utc).isoformat()
        duration_ms = round((perf_counter() - self._started_at) * 1000, 2)

        return ProviderTelemetry(
            provider_name=self.provider_name,
            strategy_name=self.strategy_name,
            operation=self.operation,
            question_number=self.question_number,
            started_at_iso=self._started_iso,  # type: ignore[arg-type]
            finished_at_iso=finished_iso,
            duration_ms=duration_ms,
            confidence=confidence,
            retry_count=retry_count,
            token_usage=token_usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            estimated_cost_usd=estimated_cost_usd,
            status=status,
            error_message=error_message,
        )
