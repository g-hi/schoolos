"""
duty_agent.py
─────────────
LLM-powered duty roster assignment using Groq (llama-3.1-8b-instant).

Batches all slot-location combos for a single day into ONE LLM call
to avoid Render timeout (35 individual calls → 5 batched calls).
"""

import asyncio
import json
import re

import httpx

from shared.config import get_settings

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_PROMPT = """You are a smart school duty roster agent. Your job is to assign teachers to supervise specific locations during non-teaching times (morning arrival, break, lunch, closing).

You will receive a JSON object with:
- "day": the day of the week
- "duties": list of duty slots that need coverage, each with slot_name, time, and location
- "teachers": list of teachers with their availability and stats

For each teacher you see:
- name: their name
- weekly_periods: how many timetable periods they teach per week
- max_weekly_hours: their maximum weekly hours
- duties_so_far: how many duties they already have this week
- busy_slots: list of slot names during which they are TEACHING (cannot be assigned)

RULES (strict):
1. NEVER assign a teacher to a slot listed in their busy_slots — they are teaching a class
2. You MUST assign a teacher to every duty if any teacher is free for that slot
3. Prefer teachers with FEWER duties_so_far (spread fairly)
4. Prefer teachers with LOWER overall workload (more headroom)
5. NEVER assign the SAME teacher to TWO different locations in the SAME slot — they can only be in ONE place at a time
6. Spread duties across teachers — don't give one teacher all the duties

Return ONLY valid JSON — no markdown, no explanation, just a JSON array:
[
  {"slot": "<slot_name>", "location": "<location>", "chosen": "<teacher name>", "reasoning": "<short reason>"},
  ...
]

One entry per duty. Set "chosen" to null ONLY when no free teacher exists for that slot.
"""


async def pick_duty_teachers_batch(
    day: str,
    duties: list[dict],
    teachers: list[dict],
) -> list[dict]:
    """
    Ask the LLM to assign teachers to ALL duty slots for a single day.
    Retries up to 3 times with exponential backoff on rate-limit (429).
    """
    settings = get_settings()

    context = json.dumps({
        "day": day,
        "duties": duties,
        "teachers": teachers,
    }, indent=2)

    api_key = settings.groq_api_key.strip()
    last_err = ""

    for attempt in range(3):
        try:
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
                        "max_tokens": 2048,
                    },
                )
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1)  # 2, 4, 8 seconds
                    await asyncio.sleep(wait)
                    last_err = "429 Too Many Requests"
                    continue
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"].strip()
                break
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                wait = 2 ** (attempt + 1)
                await asyncio.sleep(wait)
                last_err = "429 Too Many Requests"
                continue
            return _fallback_batch(duties, teachers, str(e))
        except Exception as e:
            return _fallback_batch(duties, teachers, str(e))
    else:
        # All retries exhausted
        return _fallback_batch(duties, teachers, last_err)

    # Parse JSON array from response
    try:
        cleaned = re.sub(r"```json?\s*", "", text)
        cleaned = re.sub(r"```", "", cleaned).strip()
        result = json.loads(cleaned)
        if not isinstance(result, list):
            return _fallback_batch(duties, teachers, "LLM returned non-list")
    except (json.JSONDecodeError, ValueError):
        return _fallback_batch(duties, teachers, f"LLM unparseable: {text[:200]}")

    # Validate: ensure all duties have an entry, fill gaps
    result_map = {}
    for r in result:
        key = f"{r.get('slot', '')}|{r.get('location', '')}"
        result_map[key] = r

    final = []
    for d in duties:
        key = f"{d['slot_name']}|{d['location']}"
        if key in result_map:
            entry = result_map[key]
            # Safety: if LLM says null but someone is free, fallback pick
            if not entry.get("chosen"):
                fb = _pick_one(d, teachers)
                final.append(fb)
            else:
                final.append({
                    "slot": d["slot_name"],
                    "location": d["location"],
                    "chosen": entry.get("chosen"),
                    "reasoning": entry.get("reasoning", ""),
                })
        else:
            # LLM missed this duty, use fallback
            fb = _pick_one(d, teachers)
            final.append(fb)

    return final


def _pick_one(duty: dict, teachers: list[dict], used_in_slot: set[str] | None = None) -> dict:
    """Fallback pick for a single duty, excluding teachers already used in this slot."""
    slot_name = duty["slot_name"]
    free = [t for t in teachers if slot_name not in t.get("busy_slots", [])]
    if used_in_slot:
        free = [t for t in free if t["name"] not in used_in_slot]
    if not free:
        return {"slot": slot_name, "location": duty["location"], "chosen": None,
                "reasoning": "No free teachers for this slot"}
    best = min(free, key=lambda c: (c.get("duties_so_far", 0), c.get("weekly_periods", 0)))
    return {"slot": slot_name, "location": duty["location"], "chosen": best["name"],
            "reasoning": f"Fallback: fewest duties ({best.get('duties_so_far', 0)})"}


def _fallback_batch(duties: list[dict], teachers: list[dict], reason: str) -> list[dict]:
    """Rule-based fallback for the entire day batch."""
    results = []
    temp_counts: dict[str, int] = {t["name"]: t.get("duties_so_far", 0) for t in teachers}
    # Track which teachers are already assigned to a slot (one teacher per slot)
    slot_assigned: dict[str, set[str]] = {}  # slot_name -> set of teacher names

    for d in duties:
        slot_name = d["slot_name"]
        already_in_slot = slot_assigned.setdefault(slot_name, set())
        free = [t for t in teachers
                if slot_name not in t.get("busy_slots", [])
                and t["name"] not in already_in_slot]
        if not free:
            # Allow reuse if all teachers are used (small school)
            free = [t for t in teachers if slot_name not in t.get("busy_slots", [])]
        if not free:
            results.append({"slot": slot_name, "location": d["location"],
                            "chosen": None, "reasoning": f"No free teachers. {reason}"})
            continue
        best = min(free, key=lambda c: (temp_counts.get(c["name"], 0), c.get("weekly_periods", 0)))
        temp_counts[best["name"]] = temp_counts.get(best["name"], 0) + 1
        already_in_slot.add(best["name"])
        results.append({"slot": slot_name, "location": d["location"],
                        "chosen": best["name"],
                        "reasoning": f"Fallback pick (fewest duties). {reason}"})
    return results
