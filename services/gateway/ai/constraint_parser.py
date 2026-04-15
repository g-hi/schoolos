"""
constraint_parser.py
────────────────────
Converts a plain-English scheduling constraint into structured JSON using
the Groq LLM (llama-3.1-8b-instant) via LangChain.

Why LangChain instead of raw requests?
  - Output parsing is built-in (JsonOutputParser).
  - Easy to swap models later (Groq → OpenAI → Ollama).
  - We only need one simple chain, no LangGraph needed for this step.

How it works:
  1. Admin types: "Teacher John should not teach in Period 4 on Mondays"
  2. We send it to the LLM with a system prompt listing all valid constraint types.
  3. LLM responds with JSON like:
       {
         "constraint_type": "teacher_unavailable",
         "data": {"teacher_name": "John", "day_of_week": 0, "period_order": 4},
         "confidence": "high"
       }
  4. We return both the constraint_type and data dict to the caller.

Supported constraint_type values:
  teacher_unavailable   — block a teacher from a specific slot
  teacher_max_daily     — teacher can teach at most N periods per day
  class_unavailable     — block a whole class from a period (e.g., sports day)
  subject_first_period  — a subject must be scheduled in period 1
  no_back_to_back       — a teacher or class can't have the same subject twice in a row
  unknown               — LLM couldn't parse into any known type (returned as-is)
"""

import json
import re

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from shared.config import get_settings

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are a school timetable constraint parser.
Convert the user's plain English scheduling rule into a JSON object.

Return ONLY valid JSON — no markdown, no explanation, just the JSON object.

JSON format:
{
  "constraint_type": "<one of the types below>",
  "data": { <type-specific fields below> },
  "confidence": "<high|medium|low>"
}

Constraint types and their data fields:

teacher_unavailable:
  teacher_name (string), day_of_week (0=Mon,1=Tue,2=Wed,3=Thu,4=Fri, or null for all days), period_order (integer, 1-based, or null for all periods)

teacher_max_daily:
  teacher_name (string), max_periods (integer, how many periods per day maximum)

class_unavailable:
  class_name (string, e.g. "Grade 5 Section A"), day_of_week (0-4 or null), period_order (integer or null)

subject_first_period:
  subject_name (string)

no_back_to_back:
  entity_type ("teacher" or "class"), entity_name (string), subject_name (string or null)

unknown:
  raw (string, exactly what the user typed)

Rules:
- If day is not mentioned, set day_of_week to null (meaning every day).
- Period numbers are 1-based (Period 1, Period 2, ...).
- If you cannot parse it, use constraint_type "unknown".
"""


def _build_llm() -> ChatGroq:
    settings = get_settings()
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.llm_model,
        max_tokens=512,
        temperature=0,         # deterministic parsing
    )


def parse_constraint(raw_text: str) -> dict:
    """
    Takes a plain-English constraint and returns:
      {
        "constraint_type": "teacher_unavailable",
        "data": {...},
        "confidence": "high"
      }

    Raises ValueError if the LLM returns non-JSON or an unrecognised structure.

    This function is synchronous — it's called from an async FastAPI handler
    using asyncio.run_in_executor (see timetable router).
    """
    llm = _build_llm()

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=raw_text),
    ]

    response = llm.invoke(messages)
    raw_response = response.content.strip()

    # Strip markdown code fences if the LLM added them despite instructions
    raw_response = re.sub(r"^```(?:json)?\s*", "", raw_response, flags=re.MULTILINE)
    raw_response = re.sub(r"\s*```$", "", raw_response, flags=re.MULTILINE)
    raw_response = raw_response.strip()

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned non-JSON response: {raw_response!r}"
        ) from exc

    # Basic structure validation
    if "constraint_type" not in parsed or "data" not in parsed:
        raise ValueError(
            f"LLM response missing required keys: {parsed}"
        )

    return parsed
