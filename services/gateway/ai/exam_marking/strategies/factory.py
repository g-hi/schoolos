"""
ProcessingStrategyFactory — decouples LangGraph from provider details.

The pipeline_processing LangGraph node calls only:

    strategy = ProcessingStrategyFactory.get_strategy(paper_type)
    result   = await strategy.process(inp, registry)

To add a new paper type or provider (Math OCR, Arabic OCR, Diagram
Recognition, online-submission handler):
    1. Create a new ProcessingStrategy implementation.
    2. Call ProcessingStrategyFactory.register("my_type", MyStrategy()).
    Zero LangGraph node changes required.
"""
from __future__ import annotations

from services.gateway.ai.exam_marking.strategies.base import ProcessingStrategy
from services.gateway.ai.exam_marking.strategies.mixed_paper import MixedPaperStrategy
from services.gateway.ai.exam_marking.strategies.open_ended import OpenEndedStrategy
from services.gateway.ai.exam_marking.strategies.printed_mcq import PrintedMCQStrategy
from services.gateway.ai.exam_marking.strategies.scantron_omr import ScantronOMRStrategy


class ProcessingStrategyFactory:
    _registry: dict[str, ProcessingStrategy] = {
        "scantron": ScantronOMRStrategy(),
        "printed_mcq": PrintedMCQStrategy(),
        "mixed": MixedPaperStrategy(),
        "open_ended": OpenEndedStrategy(),
    }

    @classmethod
    def get_strategy(cls, paper_type: str) -> ProcessingStrategy:
        """Return the strategy for the given paper type.
        Defaults to open_ended for unknown types (safest fallback)."""
        return cls._registry.get((paper_type or "").strip().lower(), cls._registry["open_ended"])

    @classmethod
    def register(cls, paper_type: str, strategy: ProcessingStrategy) -> None:
        """Register a custom strategy.  Call this at application startup."""
        cls._registry[paper_type.strip().lower()] = strategy

    @classmethod
    def registered_types(cls) -> list[str]:
        return list(cls._registry.keys())
