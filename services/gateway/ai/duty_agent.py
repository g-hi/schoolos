"""
duty_agent.py
─────────────
LLM-powered duty roster assignment using Groq (llama-3.1-8b-instant).

For each (duty_slot, location, day), asks the LLM to pick the fairest teacher
based on their timetable load, existing duty count, and availability.
"""

import json
import re

import httpx

from shared.config import get_settings

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_PROMPT = """You are a smart school duty roster agent. Your job is to assign teachers to supervise specific locations during non-teaching times (morning arrival, break, lunch, closing).

You will receive a JSON object with:
- "duty": the duty slot and location that need coverage (name, time, location, day)
- "candidates": list of available teachers with their details

For each candidate you see:
- name: their name
- weekly_periods: how many timetable periods they teach per week
- max_weekly_hours: their maximum weekly hours
- duties_this_week: how many duties they already have this week
- is_free: whether they are free (not teaching) during this duty slot time

RULES (strict):
1. NEVER assign a teacher who is NOT free (is_free=false) — they are teaching a class
2. You MUST always pick a teacher if there is at least one free candidate
3. Prefer teachers with FEWER duties this week (spread fairly)
4. Prefer teachers with LOWER overall workload (more headroom)
5. Among equal candidates, vary the pick to spread duties

Return ONLY valid JSON — no markdown, no explanation, just the JSON object:
{
  "chosen": "<teacher name — MUST be set if any free candidates exist>",
  "reasoning": "<1-2 sentence explanation of why this teacher was chosen>"
}

Set "chosen" to null ONLY when no free candidates exist.
"""


async def pick_duty_teacher(
    duty: dict,
    candidates: list[dict],
) -> dict:
    """
    Ask the LLM to pick the best teacher for a duty slot+location.

    Args:
        duty: {"slot_name", "start_time", "end_time", "location", "day"}
        candidates: list of candidate dicts with stats

    Returns:
        {"chosen": str|None, "reasoning": str}
    """
    settings = get_settings()

    free_candidates = [c for c in candidates if c.get("is_free", True)]

    if not free_candidates:
        return {
            "chosen": None,
            "reasoning": "No teachers are free during this duty slot.",
        }

    context = json.dumps({
        "duty": duty,
        "candidates": free_candidates,
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
                    "temperature": 0.2,
                    "max_tokens": 256,
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return _fallback_pick(free_candidates, str(e))

    # Parse JSON from response
    try:
        # Strip markdown fences if present
        cleaned = re.sub(r"```json?\s*", "", text)
        cleaned = re.sub(r"```", "", cleaned).strip()
        result = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return _fallback_pick(free_candidates, f"LLM returned unparseable response: {text[:100]}")

    # Safety net: if LLM returns null but there are candidates, force pick
    if not result.get("chosen") and free_candidates:
        return _fallback_pick(free_candidates, "LLM returned null despite available candidates")

    return {
        "chosen": result.get("chosen"),
        "reasoning": result.get("reasoning", ""),
    }


def _fallback_pick(candidates: list[dict], reason: str) -> dict:
    """Rule-based fallback: pick teacher with fewest duties, then lowest workload."""
    if not candidates:
        return {"chosen": None, "reasoning": reason}

    best = min(candidates, key=lambda c: (c.get("duties_this_week", 0), c.get("weekly_periods", 0)))
    return {
        "chosen": best["name"],
        "reasoning": f"Fallback pick (fewest duties, lowest load). {reason}",
    }
