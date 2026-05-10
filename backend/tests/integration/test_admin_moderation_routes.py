"""Tests intégration : LoggingModeration persistence + services + routes admin moderation.

Requiert Postgres (TEST_DATABASE_URL ou DATABASE_URL).
Skip propre si non disponible.

Couvre (Tasks 4-5 persistence + Tasks 6-11 routes) :
- LoggingModeration : refused persiste, egress phase, truncation 80, detector fallback, None text
- svc.list_events : empty, seeded, filtres phase/detector, pagination
- svc.aggregate_stats : total_refused, by_detector, by_phase, timeline
- GET /api/admin/moderation/events : empty, 401, avec data
- GET /api/admin/moderation/stats : 24h, window validation, 401
- GET/DELETE /api/admin/moderation/bans : list, clear, idempotent, bad hash
- Sécurité : member cookie rejeté
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from shugu.services import moderation_events as svc

# ─── LoggingModeration persistence tests (nécessitent PG + session_scope) ────


@pytest.mark.asyncio
async def test_logging_moderation_refused_persists_event(db_session, patch_session_scope):
    """refused verdict → INSERT dans moderation_events via session_scope patché."""
    from shugu.adapters.moderation_logging import LoggingModeration
    from shugu.core.identity import VisitorIdentity
    from shugu.core.protocols import ModerationLayer, ModerationVerdict
    from shugu.db.models import ModerationEvent

    class FakeInner(ModerationLayer):
        async def check_ingress(self, text, identity):
            return ModerationVerdict(
                allowed=False, reason="langage inapproprié", detector="profanity"
            )
        async def check_egress(self, text, identity):
            return ModerationVerdict(allowed=True)

    visitor = VisitorIdentity(ip_hash="a" * 64, session_id="sess-1")
    layer = LoggingModeration(FakeInner())

    result = await layer.check_ingress("texte interdit", visitor)

    assert result.allowed is False
    rows = (await db_session.execute(select(ModerationEvent))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.phase == "ingress"
    assert row.detector == "profanity"
    assert row.verdict == "refused"
    assert row.details["reason"] == "langage inapproprié"
    assert row.details["identity_kind"] == "visitor"
    assert row.details["ip_hash"] == "a" * 64
    assert row.details["text_excerpt"] == "texte interdit"
    assert row.details["text_len"] == 14


@pytest.mark.asyncio
async def test_logging_moderation_egress_phase(db_session, patch_session_scope):
    """egress refused → phase == 'egress'."""
    from shugu.adapters.moderation_logging import LoggingModeration
    from shugu.core.identity import VisitorIdentity
    from shugu.core.protocols import ModerationLayer, ModerationVerdict
    from shugu.db.models import ModerationEvent

    class FakeInner(ModerationLayer):
        async def check_ingress(self, text, identity):
            return ModerationVerdict(allowed=True)
        async def check_egress(self, text, identity):
            return ModerationVerdict(allowed=False, reason="too long", detector="egress_length")

    layer = LoggingModeration(FakeInner())
    visitor = VisitorIdentity(ip_hash="b" * 64, session_id="sess-2")

    await layer.check_egress("réponse IA trop longue", visitor)

    rows = (await db_session.execute(select(ModerationEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].phase == "egress"


@pytest.mark.asyncio
async def test_logging_moderation_truncates_excerpt_at_80(db_session, patch_session_scope):
    """text > 80 chars → text_excerpt tronqué à 80."""
    from shugu.adapters.moderation_logging import LoggingModeration
    from shugu.core.identity import VisitorIdentity
    from shugu.core.protocols import ModerationLayer, ModerationVerdict
    from shugu.db.models import ModerationEvent

    class FakeInner(ModerationLayer):
        async def check_ingress(self, text, identity):
            return ModerationVerdict(allowed=False, detector="length", reason="too long")
        async def check_egress(self, text, identity):
            return ModerationVerdict(allowed=True)

    long_text = "x" * 200
    layer = LoggingModeration(FakeInner())
    visitor = VisitorIdentity(ip_hash="c" * 64, session_id="sess-3")

    await layer.check_ingress(long_text, visitor)

    row = (await db_session.execute(select(ModerationEvent))).scalars().one()
    assert row.details["text_excerpt"] == "x" * 80
    assert row.details["text_len"] == 200


@pytest.mark.asyncio
async def test_logging_moderation_detector_fallback_unknown(db_session, patch_session_scope):
    """detector=None → row.detector == 'unknown'."""
    from shugu.adapters.moderation_logging import LoggingModeration
    from shugu.core.identity import VisitorIdentity
    from shugu.core.protocols import ModerationLayer, ModerationVerdict
    from shugu.db.models import ModerationEvent

    class FakeInner(ModerationLayer):
        async def check_ingress(self, text, identity):
            return ModerationVerdict(allowed=False, reason="???", detector=None)
        async def check_egress(self, text, identity):
            return ModerationVerdict(allowed=True)

    layer = LoggingModeration(FakeInner())
    visitor = VisitorIdentity(ip_hash="d" * 64, session_id="sess-4")

    await layer.check_ingress("foo", visitor)

    row = (await db_session.execute(select(ModerationEvent))).scalars().one()
    assert row.detector == "unknown"


@pytest.mark.asyncio
async def test_logging_moderation_none_text_handled(db_session, patch_session_scope):
    """text=None → text_excerpt == '' et text_len == 0."""
    from shugu.adapters.moderation_logging import LoggingModeration
    from shugu.core.identity import VisitorIdentity
    from shugu.core.protocols import ModerationLayer, ModerationVerdict
    from shugu.db.models import ModerationEvent

    class FakeInner(ModerationLayer):
        async def check_ingress(self, text, identity):
            return ModerationVerdict(allowed=False, reason="empty", detector="length")
        async def check_egress(self, text, identity):
            return ModerationVerdict(allowed=True)

    layer = LoggingModeration(FakeInner())
    visitor = VisitorIdentity(ip_hash="e" * 64, session_id="sess-5")

    await layer.check_ingress(None, visitor)  # type: ignore[arg-type]

    row = (await db_session.execute(select(ModerationEvent))).scalars().one()
    assert row.details["text_excerpt"] == ""
    assert row.details["text_len"] == 0


# ─── svc.list_events tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_events_returns_empty_when_no_data(db_session):
    result = await svc.list_events(db_session)
    assert result["total"] == 0
    assert result["items"] == []


@pytest.mark.asyncio
async def test_list_events_returns_seeded(db_session, seed_events):
    result = await svc.list_events(db_session, limit=50)
    assert result["total"] == 20
    assert len(result["items"]) == 20
    # Le plus récent en premier
    assert result["items"][0]["created_at"] >= result["items"][-1]["created_at"]


@pytest.mark.asyncio
async def test_list_events_filters_by_phase(db_session, seed_events):
    result = await svc.list_events(db_session, phase="ingress", limit=50)
    assert all(it["phase"] == "ingress" for it in result["items"])


@pytest.mark.asyncio
async def test_list_events_filters_by_detector(db_session, seed_events):
    result = await svc.list_events(db_session, detector="profanity", limit=50)
    assert all(it["detector"] == "profanity" for it in result["items"])


@pytest.mark.asyncio
async def test_list_events_pagination(db_session, seed_events):
    page1 = await svc.list_events(db_session, limit=10, offset=0)
    page2 = await svc.list_events(db_session, limit=10, offset=10)
    assert len(page1["items"]) == 10
    assert len(page2["items"]) == 10
    ids_p1 = {it["id"] for it in page1["items"]}
    ids_p2 = {it["id"] for it in page2["items"]}
    assert ids_p1.isdisjoint(ids_p2)


# ─── svc.aggregate_stats tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_24h_total_refused(db_session, seed_events):
    stats = await svc.aggregate_stats(db_session, window="24h")
    assert stats["total_refused"] == 20
    assert stats["window"] == "24h"


@pytest.mark.asyncio
async def test_stats_groups_by_detector(db_session, seed_events):
    stats = await svc.aggregate_stats(db_session, window="24h")
    assert set(stats["by_detector"].keys()) == {"profanity", "injection", "rate_limit"}
    assert sum(stats["by_detector"].values()) == 20


@pytest.mark.asyncio
async def test_stats_groups_by_phase(db_session, seed_events):
    stats = await svc.aggregate_stats(db_session, window="24h")
    assert sum(stats["by_phase"].values()) == 20
    assert set(stats["by_phase"].keys()) == {"ingress", "egress"}


@pytest.mark.asyncio
async def test_stats_timeline_buckets(db_session, seed_events):
    stats = await svc.aggregate_stats(db_session, window="24h")
    # 24h → buckets 'hour' → max 24 buckets
    assert len(stats["timeline"]) <= 24
    assert all("bucket" in b and "count" in b for b in stats["timeline"])
    total_in_timeline = sum(b["count"] for b in stats["timeline"])
    assert total_in_timeline == 20


# ─── Route GET /api/admin/moderation/events ──────────────────────────────────


@pytest.mark.asyncio
async def test_route_list_events_empty(api_client, operator_cookie):
    r = await api_client.get("/api/admin/moderation/events", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body == {"total": 0, "items": []}


@pytest.mark.asyncio
async def test_route_list_events_requires_operator(api_client):
    r = await api_client.get("/api/admin/moderation/events")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_route_list_events_with_data(api_client, operator_cookie, seed_events):
    r = await api_client.get(
        "/api/admin/moderation/events?limit=5",
        cookies=operator_cookie,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 20
    assert len(body["items"]) == 5


# ─── Route GET /api/admin/moderation/stats ───────────────────────────────────


@pytest.mark.asyncio
async def test_route_stats_24h(api_client, operator_cookie, seed_events):
    r = await api_client.get(
        "/api/admin/moderation/stats?window=24h", cookies=operator_cookie
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_refused"] == 20
    assert body["window"] == "24h"


@pytest.mark.asyncio
async def test_route_stats_window_validation(api_client, operator_cookie):
    r = await api_client.get(
        "/api/admin/moderation/stats?window=invalid", cookies=operator_cookie
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_route_stats_requires_operator(api_client):
    r = await api_client.get("/api/admin/moderation/stats")
    assert r.status_code == 401


# ─── Routes GET/DELETE /api/admin/moderation/bans ────────────────────────────


@pytest.mark.asyncio
async def test_route_list_bans_returns_redis_keys(api_client, operator_cookie, seed_redis_bans):
    r = await api_client.get("/api/admin/moderation/bans", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    ip_hashes = {item["ip_hash"] for item in body["items"]}
    assert ip_hashes == {seed_redis_bans["ttl_60min"], seed_redis_bans["perma"]}


@pytest.mark.asyncio
async def test_route_clear_ban_deletes_redis_key(
    api_client, operator_cookie, redis_client, seed_redis_bans
):
    target = seed_redis_bans["ttl_60min"]
    r = await api_client.delete(
        f"/api/admin/moderation/bans/{target}", cookies=operator_cookie
    )
    assert r.status_code == 204
    assert await redis_client.get(f"ban:{target}") is None


@pytest.mark.asyncio
async def test_route_clear_ban_idempotent(api_client, operator_cookie):
    fake = "f" * 64
    r1 = await api_client.delete(
        f"/api/admin/moderation/bans/{fake}", cookies=operator_cookie
    )
    r2 = await api_client.delete(
        f"/api/admin/moderation/bans/{fake}", cookies=operator_cookie
    )
    assert r1.status_code == 204
    assert r2.status_code == 204


@pytest.mark.asyncio
async def test_route_clear_ban_rejects_invalid_hash(api_client, operator_cookie):
    r = await api_client.delete(
        "/api/admin/moderation/bans/not_a_sha256", cookies=operator_cookie
    )
    assert r.status_code == 422


# ─── Sécurité non-régression ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_list_events_rejects_member_cookie(api_client, member_cookie):
    """Sécurité : un member authentifié NE DOIT PAS accéder aux events admin (PII)."""
    r = await api_client.get(
        "/api/admin/moderation/events", cookies=member_cookie
    )
    assert r.status_code in (401, 403)
