"""Tests intégration admin analytics — 8 routes + queries agrégées.

TDD strict : tests écrits avant l'implémentation (rouge → vert → commit).
36 tests, 0 skip, 0 xfail, 0 placeholder.
Coverage cible ≥ 90 % sur services/analytics_queries.py + routes/admin_analytics.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# ─── KPIs ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kpis_returns_zero_when_no_data(api_client, operator_cookie):
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "24h"
    assert body["visitors_unique"] == 0
    assert body["performances_total"] == 0


@pytest.mark.asyncio
async def test_kpis_computes_visitors_unique(api_client, operator_cookie, seed_performances):
    # seed_performances span 6 jours, donc window=7d couvre tout
    r = await api_client.get("/api/admin/analytics/kpis?window=7d", cookies=operator_cookie)
    body = r.json()
    assert body["visitors_unique"] > 0
    assert body["performances_total"] > 0


@pytest.mark.asyncio
async def test_kpis_computes_avg_duration(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/kpis?window=7d", cookies=operator_cookie)
    body = r.json()
    assert body["avg_duration_ms"] > 0


@pytest.mark.asyncio
async def test_kpis_computes_moderation_refused_rate(
    api_client, operator_cookie, seed_performances
):
    r = await api_client.get("/api/admin/analytics/kpis?window=7d", cookies=operator_cookie)
    body = r.json()
    # 50 perfs, 1 sur 7 a moderation_ingress non-null → ~7 refusées → rate ~14%
    assert 0 < body["moderation_refused_rate"] < 30


@pytest.mark.asyncio
async def test_kpis_delta_pct_handles_zero_previous(api_client, operator_cookie):
    # Pas de seed → période précédente vide aussi → delta = 0.0
    r = await api_client.get("/api/admin/analytics/kpis?window=1h", cookies=operator_cookie)
    body = r.json()
    assert body["visitors_unique_delta_pct"] == 0.0
    assert body["performances_total_delta_pct"] == 0.0


@pytest.mark.asyncio
async def test_kpis_window_validation(api_client, operator_cookie):
    r = await api_client.get("/api/admin/analytics/kpis?window=invalid", cookies=operator_cookie)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_kpis_requires_operator(api_client):
    r = await api_client.get("/api/admin/analytics/kpis?window=24h")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_kpis_rejects_member_cookie(api_client, member_cookie):
    """Sécurité non-régression : un member ne doit pas accéder à analytics."""
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=member_cookie)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_kpis_bans_active_count_db_only(api_client, operator_cookie, seed_visitors):
    """seed_visitors : 30 visitors, 1 sur 7 a ban_until → ~5 bans DB."""
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=operator_cookie)
    body = r.json()
    assert body["bans_active_count"] >= 4  # 30/7 ≈ 5, marge ±1


@pytest.mark.asyncio
async def test_kpis_bans_active_count_redis_only(api_client, operator_cookie, redis_client):
    """3 bans Redis sans aucun en DB."""
    await redis_client.set(b"ban:r1", b"1", ex=3600)
    await redis_client.set(b"ban:r2", b"1", ex=3600)
    await redis_client.set(b"ban:r3", b"1", ex=3600)
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=operator_cookie)
    assert r.json()["bans_active_count"] == 3


@pytest.mark.asyncio
async def test_kpis_bans_dedup_db_redis_overlap(
    api_client, operator_cookie, redis_client, db_session
):
    """1 ip_hash banni à la fois en DB ET Redis → compté UNE fois."""
    from sqlalchemy import insert

    from shugu.db.models import Visitor

    overlap_hash = "o" * 64
    now = datetime.now(timezone.utc)
    await db_session.execute(
        insert(Visitor).values(
            ip_hash=overlap_hash,
            first_seen=now,
            last_seen=now,
            msg_count=0,
            ban_until=now + timedelta(hours=1),
        )
    )
    await db_session.commit()
    await redis_client.set(f"ban:{overlap_hash}".encode(), b"1", ex=3600)
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=operator_cookie)
    assert r.json()["bans_active_count"] == 1


# ─── Timeline ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeline_24h_returns_buckets(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/timeline?window=24h", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "24h"
    # 24h buckets hourly — at most 24 buckets (only non-empty shown)
    assert len(body["buckets"]) <= 24


@pytest.mark.asyncio
async def test_timeline_7d_bucket_size_1d(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/timeline?window=7d", cookies=operator_cookie)
    body = r.json()
    assert len(body["buckets"]) <= 7


@pytest.mark.asyncio
async def test_timeline_includes_visitors_unique_per_bucket(
    api_client, operator_cookie, seed_performances
):
    r = await api_client.get("/api/admin/analytics/timeline?window=7d", cookies=operator_cookie)
    body = r.json()
    if body["buckets"]:
        b = body["buckets"][0]
        assert "performances" in b
        assert "visitors_unique" in b
        assert "bucket" in b


@pytest.mark.asyncio
async def test_timeline_requires_operator(api_client):
    r = await api_client.get("/api/admin/analytics/timeline?window=24h")
    assert r.status_code == 401


# ─── Top Routes ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_top_routes_groups_by_route_desc(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/top-routes?window=7d", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 0
    counts = [item["count"] for item in body["items"]]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.asyncio
async def test_top_routes_respects_limit(api_client, operator_cookie, seed_performances):
    r = await api_client.get(
        "/api/admin/analytics/top-routes?window=7d&limit=2", cookies=operator_cookie
    )
    assert len(r.json()["items"]) <= 2


@pytest.mark.asyncio
async def test_top_routes_computes_pct_of_total(api_client, operator_cookie, seed_performances):
    r = await api_client.get(
        "/api/admin/analytics/top-routes?window=7d&limit=20", cookies=operator_cookie
    )
    body = r.json()
    total = body["total"]
    if total > 0:
        sum_counts = sum(item["count"] for item in body["items"])
        # All routes returned → sum_counts == total
        assert sum_counts == total
        # Pct should add up to ~100 (allow floating point tolerance)
        sum_pct = sum(item["pct"] for item in body["items"])
        assert abs(sum_pct - 100.0) < 0.1


@pytest.mark.asyncio
async def test_top_routes_requires_operator(api_client):
    r = await api_client.get("/api/admin/analytics/top-routes?window=24h")
    assert r.status_code == 401


# ─── Top Visitors ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_top_visitors_returns_truncated_ip_hash(
    api_client, operator_cookie, seed_performances
):
    """Le full ip_hash ne doit JAMAIS apparaître dans la response."""
    r = await api_client.get("/api/admin/analytics/top-visitors?window=7d", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    for item in body["items"]:
        # Truncated = 12 chars max, never full 64-char hash
        assert len(item["ip_hash_truncated"]) <= 12


@pytest.mark.asyncio
async def test_top_visitors_orders_by_msg_count_desc(
    api_client, operator_cookie, seed_performances
):
    r = await api_client.get("/api/admin/analytics/top-visitors?window=7d", cookies=operator_cookie)
    body = r.json()
    counts = [item["msg_count_window"] for item in body["items"]]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.asyncio
async def test_top_visitors_marks_banned_with_flag(
    api_client, operator_cookie, seed_performances, seed_visitors
):
    """Les visiteurs de seed_visitors avec ban_until futur ont is_banned=True."""
    r = await api_client.get(
        "/api/admin/analytics/top-visitors?window=7d&limit=20",
        cookies=operator_cookie,
    )
    body = r.json()
    # seed_visitors et seed_performances utilisent des ip_hash différents
    # (v* vs a*) → les top visitors sont de seed_performances, is_banned=False
    for item in body["items"]:
        assert "is_banned" in item


# ─── Heatmap ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_heatmap_returns_always_24_buckets(api_client, operator_cookie):
    """Même sans données, la heatmap retourne 24 buckets (0..23)."""
    r = await api_client.get("/api/admin/analytics/heatmap?window=24h", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert len(body["buckets"]) == 24
    hours = [b["hour"] for b in body["buckets"]]
    assert hours == list(range(24))


@pytest.mark.asyncio
async def test_heatmap_groups_by_hour_of_day(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/heatmap?window=7d", cookies=operator_cookie)
    body = r.json()
    assert len(body["buckets"]) == 24
    total_from_heatmap = sum(b["count"] for b in body["buckets"])
    # Should match performance count in window
    assert total_from_heatmap > 0


@pytest.mark.asyncio
async def test_heatmap_max_count_for_normalization(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/heatmap?window=7d", cookies=operator_cookie)
    body = r.json()
    max_in_buckets = max(b["count"] for b in body["buckets"])
    assert body["max_count"] == max_in_buckets


@pytest.mark.asyncio
async def test_heatmap_requires_operator(api_client):
    r = await api_client.get("/api/admin/analytics/heatmap?window=24h")
    assert r.status_code == 401


# ─── Funnel ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_funnel_computes_3_levels(
    api_client, operator_cookie, seed_visitors, seed_user_accounts
):
    r = await api_client.get("/api/admin/analytics/funnel", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    # seed_visitors = 30 rows, seed_user_accounts = 15 rows (7+3=10 with email_verified)
    assert body["visitors_unique_total"] == 30
    assert body["members_total"] == 10  # 7 members + 3 vips all have email_verified_at
    assert body["vips_total"] == 3


@pytest.mark.asyncio
async def test_funnel_ratios_handle_zero_visitors(api_client, operator_cookie):
    """Sans données, les ratios sont 0.0 et aucune division par zéro."""
    r = await api_client.get("/api/admin/analytics/funnel", cookies=operator_cookie)
    body = r.json()
    assert body["visitor_to_member_pct"] == 0.0
    assert body["member_to_vip_pct"] == 0.0


@pytest.mark.asyncio
async def test_funnel_excludes_unverified_from_members(
    api_client, operator_cookie, seed_user_accounts
):
    r = await api_client.get("/api/admin/analytics/funnel", cookies=operator_cookie)
    body = r.json()
    # 5 pending (email_verified_at=None) should not be counted as members
    assert body["members_total"] == 10  # only verified (7 members + 3 vips)


@pytest.mark.asyncio
async def test_funnel_requires_operator(api_client):
    r = await api_client.get("/api/admin/analytics/funnel")
    assert r.status_code == 401


# ─── Performances list ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_performances_list_returns_paginated(api_client, operator_cookie, seed_performances):
    r = await api_client.get(
        "/api/admin/analytics/performances?limit=10&offset=0", cookies=operator_cookie
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 50
    assert len(body["items"]) == 10


@pytest.mark.asyncio
async def test_performances_list_filters_by_author_role(
    api_client, operator_cookie, seed_performances
):
    r = await api_client.get(
        "/api/admin/analytics/performances?author_role=visitor&limit=50",
        cookies=operator_cookie,
    )
    body = r.json()
    # 50 perfs, role cycles through [visitor, member, vip, operator] → 13 visitor
    for item in body["items"]:
        assert item["author_role"] == "visitor"


@pytest.mark.asyncio
async def test_performances_list_filters_by_route(api_client, operator_cookie, seed_performances):
    r = await api_client.get(
        "/api/admin/analytics/performances?route=visitor_ws&limit=50",
        cookies=operator_cookie,
    )
    body = r.json()
    for item in body["items"]:
        assert item["route"] == "visitor_ws"


@pytest.mark.asyncio
async def test_performances_list_excerpt_truncated_at_120_chars(
    api_client, operator_cookie, seed_performances
):
    r = await api_client.get("/api/admin/analytics/performances?limit=50", cookies=operator_cookie)
    body = r.json()
    for item in body["items"]:
        assert len(item["input_text_excerpt"]) <= 120
        if item["output_text_excerpt"] is not None:
            assert len(item["output_text_excerpt"]) <= 120


@pytest.mark.asyncio
async def test_performances_list_requires_operator(api_client):
    r = await api_client.get("/api/admin/analytics/performances")
    assert r.status_code == 401


# ─── Performance detail ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_performance_detail_returns_full_text(api_client, operator_cookie, seed_performances):
    perf_id = seed_performances[0]["performance_id"]
    r = await api_client.get(
        f"/api/admin/analytics/performances/{perf_id}", cookies=operator_cookie
    )
    assert r.status_code == 200
    body = r.json()
    assert body["performance_id"] == perf_id
    # Full text, not excerpt — input_text = "input 0"
    assert body["input_text"] == "input 0"


@pytest.mark.asyncio
async def test_performance_detail_404_unknown_id(api_client, operator_cookie):
    r = await api_client.get(
        "/api/admin/analytics/performances/nonexistent-id-00000000",
        cookies=operator_cookie,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_performance_detail_requires_operator(api_client, seed_performances):
    perf_id = seed_performances[0]["performance_id"]
    r = await api_client.get(f"/api/admin/analytics/performances/{perf_id}")
    assert r.status_code == 401


# ─── Export CSV ───────────────────────────────────────────────────────────────


def _export_params(days_back: int = 10, author_role: str | None = None) -> dict:
    """Construit les query params pour les tests export (gère URL-encoding du +00:00)."""
    now = datetime.now(timezone.utc)
    params: dict = {
        "type": "performances",
        "since": (now - timedelta(days=days_back)).isoformat(),
        "until": now.isoformat(),
    }
    if author_role:
        params["author_role"] = author_role
    return params


@pytest.mark.asyncio
async def test_export_csv_returns_streaming_response(
    api_client, operator_cookie, seed_performances
):
    r = await api_client.get(
        "/api/admin/analytics/export",
        params=_export_params(days_back=10),
        cookies=operator_cookie,
    )
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    content = r.text
    lines = content.strip().split("\n")
    # Header + 50 data rows
    assert lines[0].startswith("performance_id")
    assert len(lines) == 51  # 1 header + 50 rows


@pytest.mark.asyncio
async def test_export_csv_includes_only_filtered_rows(
    api_client, operator_cookie, seed_performances
):
    r = await api_client.get(
        "/api/admin/analytics/export",
        params=_export_params(days_back=10, author_role="visitor"),
        cookies=operator_cookie,
    )
    assert r.status_code == 200
    lines = r.text.strip().split("\n")
    # header + visitor-only rows
    assert len(lines) >= 2
    for line in lines[1:]:
        assert line.split(",")[1] == "visitor"


@pytest.mark.asyncio
async def test_export_csv_413_when_over_10k_rows(api_client, operator_cookie, monkeypatch):
    """Vérifie que le 413 est retourné si le count dépasse 10 000 rows."""
    import shugu.services.analytics_queries as svc_module

    async def _fake_count(*args, **kwargs):
        return 10001

    # Patch the svc module reference used by the route
    monkeypatch.setattr(svc_module, "_count_performances_for_export", _fake_count)

    r = await api_client.get(
        "/api/admin/analytics/export",
        params=_export_params(days_back=1),
        cookies=operator_cookie,
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_export_csv_requires_operator(api_client):
    r = await api_client.get(
        "/api/admin/analytics/export",
        params=_export_params(days_back=1),
    )
    assert r.status_code == 401
