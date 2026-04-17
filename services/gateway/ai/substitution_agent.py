"""
substitution_agent.py
─────────────────────
LLM-powered substitute teacher assignment using Groq (llama-3.1-8b-instant).

Instead of hardcoded scoring, we:
1. Gather structured context about each candidate (qualifications, load,
   recent sub history, the absent teacher's class/subject).
2. Ask the LLM to reason about the best pick and return a ranked list
   with explanations.
3. Parse the JSON response and return the top pick.

The LLM also enforces rules the old algorithm missed — e.g. never assigning
an absent teacher as a substitute.
"""

import json
import re

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from shared.config import get_settings

_SYSTEM_PROMPT = """You are a smart school substitution agent. Your job is to pick the best substitute teacher for a class when the regular teacher is absent.

You will receive a JSON object with:
- "slot": the class that needs covering (subject, class, period, time)
- "absent_teachers": list of ALL absent teacher names today (NEVER pick any of these)
- "candidates": list of available teachers with their details

For each candidate you see:
- name: their name
- is_subject_qualified: whether they teach this subject
- weekly_periods: how many periods they teach per week
- max_weekly_hours: their maximum weekly hours
- subs_this_week: how many substitutions they've done this week
- max_subs_per_week: their substitution limit

RULES (strict):
1. NEVER assign a teacher who is in the absent_teachers list
2. Prefer subject-qualified teachers
3. Prefer teachers with lower workload (more headroom)
4. Prefer teachers who have done fewer substitutions this week
5. Consider fairness — spread substitutions across teachers

Return ONLY valid JSON — no markdown, no explanation, just the JSON object:
{
  "chosen": "<teacher name or null if no suitable candidate>",
  "confidence": <integer 0-100>,
  "reasoning": "<1-2 sentence explanation of why this teacher was chosen>",
  "ranking": [
    {"name": "<teacher>", "score": <0-100>, "reason": "<brief>"}
  ]
}

If no candidates are available or all are unsuitable, set "chosen" to null.
"""


async def pick_substitute(
    slot: dict,
    absent_teacher_names: list[str],
    candidates: list[dict],
) -> dict:
    """
    Ask the LLM to pick the best substitute.

    Args:
        slot: {"subject": str, "class": str, "period": str, "time": str}
        absent_teacher_names: all absent teacher names today (lowercase-safe)
        candidates: list of candidate dicts with stats

    Returns:
        {"chosen": str|None, "confidence": int, "reasoning": str, "ranking": list}
    """
    settings = get_settings()

    # Filter out absent teachers from candidates before sending to LLM
    absent_lower = {n.lower() for n in absent_teacher_names}
    safe_candidates = [c for c in candidates if c["name"].lower() not in absent_lower]

    if not safe_candidates:
        return {
            "chosen": None,
            "confidence": 0,
            "reasoning": "No available teachers after excluding absent teachers.",
            "ranking": [],
        }

    context = json.dumps({
        "slot": slot,
        "absent_teachers": absent_teacher_names,
        "candidates": safe_candidates,
    }, indent=2)

    try:
        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            api_key=settings.groq_api_key,
            temperature=0,
            max_tokens=512,
        )

        response = await llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ])
    except Exception as e:
        # LLM failed — fall back to simple rule-based pick
        return _fallback_pick(safe_candidates, absent_lower, str(e))

    # Parse JSON from response
    text = response.content.strip()
    # Try to extract JSON from possible markdown wrapping
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            result = json.loads(json_match.group())
            # Safety net: double-check LLM didn't pick an absent teacher
            if result.get("chosen") and result["chosen"].lower() in absent_lower:
                result["chosen"] = None
                result["confidence"] = 0
                result["reasoning"] = "LLM suggested an absent teacher — overridden to null."
            return result
        except json.JSONDecodeError:
            pass

    # Fallback if LLM response is unparseable
    return _fallback_pick(safe_candidates, absent_lower, f"Unparseable LLM response: {text[:100]}")


def _fallback_pick(candidates: list[dict], absent_lower: set[str], reason: str) -> dict:
    """Simple rule-based fallback when LLM is unavailable."""
    # Pick the candidate with lowest workload who is subject-qualified
    qualified = [c for c in candidates if c.get("is_subject_qualified") and c["name"].lower() not in absent_lower]
    pool = qualified or [c for c in candidates if c["name"].lower() not in absent_lower]

    if not pool:
        return {"chosen": None, "confidence": 0, "reasoning": f"Fallback: no candidates. {reason}", "ranking": []}

    # Sort by lowest load
    pool.sort(key=lambda c: c.get("weekly_periods", 99))
    best = pool[0]
    return {
        "chosen": best["name"],
        "confidence": 55,
        "reasoning": f"Fallback pick (LLM unavailable: {reason[:80]}). Chose {best['name']} — {'subject-qualified, ' if best.get('is_subject_qualified') else ''}lowest workload.",
        "ranking": [{"name": c["name"], "score": 50, "reason": "fallback"} for c in pool],
    }
