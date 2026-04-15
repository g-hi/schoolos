"""
Component 10 – Social Media Analytics Router
=============================================
Marketing intelligence: sentiment analysis, topic extraction, crisis detection.

Endpoints
---------
POST /social/import        – bulk import mentions (JSON array)
POST /social/analyze       – run Groq sentiment + topic analysis on unprocessed mentions
GET  /social/report        – weekly/period sentiment summary, top topics, trends
POST /social/crisis-check  – detect negative spikes and alert via messenger
GET  /social/mentions      – browse raw mentions with filters
"""

import asyncio
import uuid
from datetime import datetime, date as date_type, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.tenant import resolve_tenant
from shared.config import settings
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import SocialMention, Tenant, User

router = APIRouter(prefix="/social", tags=["Social Media"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class MentionImportItem(BaseModel):
    platform: str                    # instagram/facebook/twitter/tiktok/linkedin/other
    text: str
    author: str | None = None
    url: str | None = None
    posted_at: str                   # ISO datetime
    is_competitor: bool = False
    competitor_name: str | None = None
    engagement: int | None = None    # likes + comments + shares


class MentionImportRequest(BaseModel):
    mentions: list[MentionImportItem]


class CrisisCheckRequest(BaseModel):
    hours_back: int = 1              # window to check for spikes
    negative_threshold: int = 5      # how many negative mentions triggers a crisis
    alert_role: str = "principal"    # who to alert


# ─────────────────────────────────────────────────────────────────────────────
# POST /social/import  —  bulk import mentions
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/import", summary="Bulk import social media mentions")
async def import_mentions(
    body: MentionImportRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    imported = 0
    errors = []

    for i, item in enumerate(body.mentions):
        try:
            posted_at = datetime.fromisoformat(item.posted_at)
        except ValueError:
            errors.append({"index": i, "error": "posted_at must be ISO format"})
            continue

        valid_platforms = {"instagram", "facebook", "twitter", "tiktok", "linkedin", "other"}
        if item.platform.lower() not in valid_platforms:
            errors.append({"index": i, "error": f"platform must be one of {valid_platforms}"})
            continue

        mention = SocialMention(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            platform=item.platform.lower(),
            author=item.author,
            text=item.text,
            url=item.url,
            posted_at=posted_at,
            is_competitor=item.is_competitor,
            competitor_name=item.competitor_name,
            engagement=item.engagement,
            processed=False,
        )
        db.add(mention)
        imported += 1

    if imported > 0:
        await log_action(
            db=db, tenant_id=tenant.id,
            action="social.imported",
            entity_type="SocialMention",
            details={"imported": imported, "errors": len(errors)},
        )

    await db.commit()
    return {"imported": imported, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# POST /social/analyze  —  Groq sentiment + topic extraction
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/analyze", summary="Run AI sentiment analysis on unprocessed mentions")
async def analyze_mentions(
    batch_size: int = 20,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    # Fetch unprocessed mentions
    q = await db.execute(
        select(SocialMention)
        .where(
            SocialMention.tenant_id == tenant.id,
            SocialMention.processed.is_(False),
        )
        .order_by(SocialMention.posted_at.desc())
        .limit(min(batch_size, 50))
    )
    mentions = q.scalars().all()

    if not mentions:
        return {"analyzed": 0, "message": "No unprocessed mentions found."}

    # Build batch prompt for Groq
    texts = []
    for i, m in enumerate(mentions):
        texts.append(f"[{i}] {m.text[:500]}")

    prompt = (
        "You are a social media analyst for a school. "
        "Analyze each numbered mention below. For each, return a JSON object with:\n"
        '  "index": the number,\n'
        '  "sentiment": "positive" or "negative" or "neutral",\n'
        '  "sentiment_score": float from -1.0 (very negative) to 1.0 (very positive),\n'
        '  "topics": list of 1-3 short topic labels (e.g. "bus delays", "new playground", "fee increase")\n\n'
        "Return a JSON array of objects. No other text.\n\n"
        "Mentions:\n" + "\n".join(texts)
    )

    try:
        parsed = await _call_groq_json(prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Groq analysis failed: {exc}")

    # Apply results
    analyzed = 0
    result_map = {}
    if isinstance(parsed, list):
        for item in parsed:
            idx = item.get("index")
            if idx is not None:
                result_map[idx] = item

    for i, m in enumerate(mentions):
        result = result_map.get(i)
        if result:
            m.sentiment = result.get("sentiment", "neutral")
            m.sentiment_score = result.get("sentiment_score", 0.0)
            m.topics = result.get("topics", [])
        else:
            m.sentiment = "neutral"
            m.sentiment_score = 0.0
            m.topics = []
        m.processed = True
        analyzed += 1

    await log_action(
        db=db, tenant_id=tenant.id,
        action="social.analyzed",
        entity_type="SocialMention",
        details={"analyzed": analyzed, "batch_size": batch_size},
    )

    await db.commit()
    return {"analyzed": analyzed, "message": f"Processed {analyzed} mentions."}


# ─────────────────────────────────────────────────────────────────────────────
# GET /social/report  —  sentiment summary + top topics
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/report", summary="Marketing intelligence report")
async def social_report(
    days_back: int = 7,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    since = datetime.utcnow() - timedelta(days=days_back)

    base_filter = [
        SocialMention.tenant_id == tenant.id,
        SocialMention.posted_at >= since,
        SocialMention.processed.is_(True),
    ]
    own_filter = base_filter + [SocialMention.is_competitor.is_(False)]
    comp_filter = base_filter + [SocialMention.is_competitor.is_(True)]

    # ── Our mentions ─────────────────────────────────────────────────────────
    total_q = await db.execute(select(func.count(SocialMention.id)).where(*own_filter))
    total = total_q.scalar() or 0

    # Sentiment breakdown
    sentiment_q = await db.execute(
        select(SocialMention.sentiment, func.count(SocialMention.id))
        .where(*own_filter)
        .group_by(SocialMention.sentiment)
    )
    sentiment_counts = {r[0]: r[1] for r in sentiment_q.all()}

    # Average sentiment score
    avg_q = await db.execute(
        select(func.avg(SocialMention.sentiment_score)).where(*own_filter)
    )
    avg_sentiment = avg_q.scalar()

    # Platform breakdown
    platform_q = await db.execute(
        select(SocialMention.platform, func.count(SocialMention.id))
        .where(*own_filter)
        .group_by(SocialMention.platform)
        .order_by(func.count(SocialMention.id).desc())
    )
    platforms = {r[0]: r[1] for r in platform_q.all()}

    # Top topics (from JSON array)
    topic_mentions_q = await db.execute(
        select(SocialMention.topics).where(*own_filter, SocialMention.topics.isnot(None))
    )
    topic_counter: dict[str, int] = {}
    for (topics,) in topic_mentions_q.all():
        if isinstance(topics, list):
            for t in topics:
                topic_counter[t] = topic_counter.get(t, 0) + 1
    top_topics = sorted(topic_counter.items(), key=lambda x: x[1], reverse=True)[:10]

    # Top performing posts (by engagement)
    top_posts_q = await db.execute(
        select(SocialMention)
        .where(*own_filter, SocialMention.engagement.isnot(None))
        .order_by(SocialMention.engagement.desc())
        .limit(5)
    )
    top_posts = [
        {
            "platform": m.platform,
            "text": m.text[:200],
            "author": m.author,
            "engagement": m.engagement,
            "sentiment": m.sentiment,
            "posted_at": str(m.posted_at),
        }
        for m in top_posts_q.scalars().all()
    ]

    # ── Competitor mentions ──────────────────────────────────────────────────
    comp_total_q = await db.execute(select(func.count(SocialMention.id)).where(*comp_filter))
    comp_total = comp_total_q.scalar() or 0

    comp_sentiment_q = await db.execute(
        select(func.avg(SocialMention.sentiment_score)).where(*comp_filter)
    )
    comp_avg = comp_sentiment_q.scalar()

    comp_top_q = await db.execute(
        select(SocialMention)
        .where(*comp_filter, SocialMention.engagement.isnot(None))
        .order_by(SocialMention.engagement.desc())
        .limit(3)
    )
    comp_top = [
        {
            "competitor": m.competitor_name,
            "platform": m.platform,
            "text": m.text[:200],
            "engagement": m.engagement,
            "sentiment": m.sentiment,
        }
        for m in comp_top_q.scalars().all()
    ]

    # ── Daily trend (last N days) ────────────────────────────────────────────
    trend_q = await db.execute(
        select(
            func.date(SocialMention.posted_at).label("day"),
            func.count(SocialMention.id),
            func.avg(SocialMention.sentiment_score),
            func.sum(
                func.cast(SocialMention.sentiment == "negative", Integer)
            ),
        )
        .where(*own_filter)
        .group_by(func.date(SocialMention.posted_at))
        .order_by(func.date(SocialMention.posted_at))
    )
    from sqlalchemy import Integer as SAInt  # already imported above
    daily_trend = [
        {
            "date": str(r[0]),
            "mentions": r[1],
            "avg_sentiment": round(float(r[2]), 2) if r[2] else None,
            "negative_count": int(r[3]) if r[3] else 0,
        }
        for r in trend_q.all()
    ]

    return {
        "period": f"last {days_back} days",
        "our_school": {
            "total_mentions": total,
            "sentiment": {
                "positive": sentiment_counts.get("positive", 0),
                "neutral": sentiment_counts.get("neutral", 0),
                "negative": sentiment_counts.get("negative", 0),
            },
            "avg_sentiment_score": round(float(avg_sentiment), 2) if avg_sentiment else None,
            "by_platform": platforms,
            "top_topics": [{"topic": t, "count": c} for t, c in top_topics],
            "top_posts": top_posts,
        },
        "competitors": {
            "total_mentions": comp_total,
            "avg_sentiment_score": round(float(comp_avg), 2) if comp_avg else None,
            "top_posts": comp_top,
        },
        "daily_trend": daily_trend,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /social/crisis-check  —  detect negative spikes + alert
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/crisis-check", summary="Detect negative mention spikes and alert leadership")
async def crisis_check(
    body: CrisisCheckRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    window_start = datetime.utcnow() - timedelta(hours=body.hours_back)

    # Count negative mentions in the window
    neg_q = await db.execute(
        select(func.count(SocialMention.id)).where(
            SocialMention.tenant_id == tenant.id,
            SocialMention.posted_at >= window_start,
            SocialMention.sentiment == "negative",
            SocialMention.is_competitor.is_(False),
        )
    )
    negative_count = neg_q.scalar() or 0

    crisis = negative_count >= body.negative_threshold

    # Gather the negative mentions for context
    neg_mentions_q = await db.execute(
        select(SocialMention)
        .where(
            SocialMention.tenant_id == tenant.id,
            SocialMention.posted_at >= window_start,
            SocialMention.sentiment == "negative",
            SocialMention.is_competitor.is_(False),
        )
        .order_by(SocialMention.posted_at.desc())
        .limit(10)
    )
    neg_mentions = neg_mentions_q.scalars().all()

    # Collect top negative topics
    neg_topics: dict[str, int] = {}
    for m in neg_mentions:
        if m.topics and isinstance(m.topics, list):
            for t in m.topics:
                neg_topics[t] = neg_topics.get(t, 0) + 1
    top_neg_topics = sorted(neg_topics.items(), key=lambda x: x[1], reverse=True)[:5]

    alert_sent = False
    if crisis:
        # Alert leadership
        from services.gateway.ai.messenger import send_to_users

        alert_q = await db.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                User.role == body.alert_role,
                User.is_active.is_(True),
            )
        )
        alert_users = alert_q.scalars().all()

        if alert_users:
            topic_summary = ", ".join(t for t, _ in top_neg_topics[:3]) if top_neg_topics else "various concerns"
            alert_msg = (
                f"[SchoolOS] CRISIS ALERT: {negative_count} negative mentions detected "
                f"in the last {body.hours_back} hour(s). "
                f"Top concerns: {topic_summary}. "
                "Please review immediately at /social/report"
            )
            await send_to_users(
                alert_users,
                alert_msg,
                "crisis_alert",
                db,
                email_subject="[SchoolOS] Social Media Crisis Alert",
            )
            alert_sent = True

        await log_action(
            db=db, tenant_id=tenant.id,
            action="social.crisis_detected",
            entity_type="SocialMention",
            details={
                "negative_count": negative_count,
                "threshold": body.negative_threshold,
                "hours_back": body.hours_back,
                "top_topics": [t for t, _ in top_neg_topics[:3]],
                "alerted_role": body.alert_role,
            },
        )
        await db.commit()

    return {
        "crisis_detected": crisis,
        "negative_count": negative_count,
        "threshold": body.negative_threshold,
        "window_hours": body.hours_back,
        "top_negative_topics": [{"topic": t, "count": c} for t, c in top_neg_topics],
        "recent_negative": [
            {"text": m.text[:200], "platform": m.platform, "author": m.author, "posted_at": str(m.posted_at)}
            for m in neg_mentions[:5]
        ],
        "alert_sent": alert_sent,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /social/mentions  —  browse mentions with filters
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mentions", summary="Browse social mentions with filters")
async def list_mentions(
    platform: str | None = None,
    sentiment: str | None = None,
    is_competitor: bool | None = None,
    days_back: int = 30,
    limit: int = 100,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    since = datetime.utcnow() - timedelta(days=days_back)

    query = (
        select(SocialMention)
        .where(
            SocialMention.tenant_id == tenant.id,
            SocialMention.posted_at >= since,
        )
        .order_by(SocialMention.posted_at.desc())
        .limit(min(limit, 500))
    )

    if platform:
        query = query.where(SocialMention.platform == platform.lower())
    if sentiment:
        query = query.where(SocialMention.sentiment == sentiment.lower())
    if is_competitor is not None:
        query = query.where(SocialMention.is_competitor.is_(is_competitor))

    result = await db.execute(query)
    mentions = result.scalars().all()

    return [
        {
            "id": str(m.id),
            "platform": m.platform,
            "author": m.author,
            "text": m.text[:300],
            "url": m.url,
            "posted_at": str(m.posted_at),
            "sentiment": m.sentiment,
            "sentiment_score": m.sentiment_score,
            "topics": m.topics,
            "is_competitor": m.is_competitor,
            "competitor_name": m.competitor_name,
            "engagement": m.engagement,
            "processed": m.processed,
        }
        for m in mentions
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Internal: Groq JSON call
# ─────────────────────────────────────────────────────────────────────────────

async def _call_groq_json(prompt: str) -> list | dict:
    """Call Groq LLM and parse the response as JSON."""
    import json
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=settings.groq_api_key,
        temperature=0.1,
    )

    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: llm.invoke(prompt),
    )

    raw = response.content.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)

    return json.loads(raw)
