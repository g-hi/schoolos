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

import httpx

from shared.config import get_settings

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

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
2. You MUST always pick a substitute if there is at least one candidate — a class must never be left without a teacher
3. Prefer subject-qualified teachers, but if none are subject-qualified, pick the best non-qualified candidate
4. Prefer teachers with lower workload (more headroom)
5. Prefer teachers who have done fewer substitutions this week
6. Consider fairness — spread substitutions across teachers

Return ONLY valid JSON — no markdown, no explanation, just the JSON object:
{
  "chosen": "<teacher name — MUST be set if any candidates exist>",
  "confidence": <integer 0-100>,
  "reasoning": "<1-2 sentence explanation of why this teacher was chosen>",
  "ranking": [
    {"name": "<teacher>", "score": <0-100>, "reason": "<brief>"}
  ]
}

Set "chosen" to null ONLY when the candidates list is completely empty.
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
        api_key = settings.groq_api_key.strip()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _GROQ_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": context},
                    ],
                    "temperature": 0,
                    "max_tokens": 512,
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        # LLM failed — fall back to simple rule-based pick
        return _fallback_pick(safe_candidates, absent_lower, str(e))

    # Parse JSON from response
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
            # Safety net: if LLM returned null but candidates exist, force-pick
            if not result.get("chosen") and safe_candidates:
                return _fallback_pick(safe_candidates, absent_lower,
                    "LLM returned null despite available candidates")
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
