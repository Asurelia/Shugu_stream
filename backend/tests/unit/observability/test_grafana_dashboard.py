"""Tests de validation du dashboard Grafana voice-body pipeline.

Spec : docs/superpowers/specs/2026-05-13-d10c-grafana-dashboard-design.md
Plan : docs/superpowers/plans/2026-05-13-d10c-grafana-dashboard-plan.md

Ces tests garantissent que le dashboard JSON :
1. Est valide (parseable).
2. Contient le schéma minimum (title, panels, schemaVersion, version, 7 rows).
3. Référence UNIQUEMENT des métriques existantes dans pipeline_metrics.py + metrics.py.
4. Inclut les threshold lines SLO §7.2 sur les panels critiques.

TDD strict — ces tests sont écrits AVANT la création du dashboard (Phase RED).
NE JAMAIS modifier ces tests pour les faire passer. Si un test est rouge,
c'est le dashboard qui est faux, pas le test.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Imports depuis les modules source — source de vérité des whitelists labels.
# NOTE : _VALID_* ne sont pas dans __all__ mais l'import explicite fonctionne.
# ---------------------------------------------------------------------------
from shugu.voice.pipeline_metrics import (
    _VALID_AUDIO_AT_MS_KINDS,
    _VALID_CANCEL_REASONS,
    _VALID_REFRESH_OUTCOMES,
    _VALID_SKIP_REASONS,
    _VALID_WS_DISCONNECT_REASONS,
)
from shugu.voice.metrics import _VALID_INTENT_LABELS

# ---------------------------------------------------------------------------
# Chemin vers le dashboard — parents[4] car le fichier est en :
# backend/tests/unit/observability/test_grafana_dashboard.py
# parents[0] = observability/
# parents[1] = unit/
# parents[2] = tests/
# parents[3] = backend/
# parents[4] = repo root  ← infra/ vit ici
# ---------------------------------------------------------------------------
DASHBOARD_PATH = (
    Path(__file__).resolve().parents[4]
    / "infra"
    / "grafana"
    / "dashboards"
    / "voice-body-pipeline.json"
)

# ---------------------------------------------------------------------------
# Whitelist exhaustive des métriques — DOIT correspondre exactement aux
# métriques exposées dans pipeline_metrics.py + metrics.py.
# NE PAS modifier cette whitelist pour faire passer un test — si un nom
# de métrique est absent ici, il n'existe pas dans le code source.
# ---------------------------------------------------------------------------
ALLOWED_METRICS: frozenset[str] = frozenset({
    # Counters (pipeline_metrics.py)
    "voice_publisher_chunks_published_total",
    "voice_publisher_chunks_dropped_total",
    "voice_bridge_sentences_published_total",
    "voice_bridge_sentences_skipped_total",
    "voice_cancel_speaking_total",
    "viewer_ws_connections_total",
    "viewer_ws_disconnects_total",
    "viewer_token_refresh_total",
    # Histograms (pipeline_metrics.py) — les expr PromQL utilisent _bucket/_count/_sum
    "voice_publisher_publish_duration_ms",
    "voice_bridge_publish_sentence_duration_ms",
    "voice_cancel_speaking_duration_ms",
    "director_audio_at_ms_distribution",
    # Histogram (metrics.py)
    "voice_turn_latency_seconds",
})

# Suffixes PromQL des histograms — à striper pour identifier la métrique de base.
_HISTOGRAM_SUFFIXES = ("_bucket", "_count", "_sum")

# Mots-clés PromQL à ignorer lors du cross-check (évitent les faux positifs).
_PROMQL_KEYWORDS: frozenset[str] = frozenset({
    "sum", "rate", "histogram_quantile", "by", "on", "le",
    "avg", "max", "min", "count", "without", "ignoring",
    "and", "or", "unless", "bool", "offset", "topk", "bottomk",
    "increase", "irate", "delta", "deriv", "predict_linear",
    "floor", "ceil", "round", "abs", "sqrt", "exp", "ln",
    "label_replace", "label_join", "vector", "scalar",
    "time", "day_of_week", "day_of_month", "days_in_month",
    "hour", "minute", "month", "year",
})

# Préfixes spécifiques aux métriques du projet — tout identifiant avec l'un
# de ces préfixes DOIT être dans ALLOWED_METRICS.
_METRIC_PREFIXES = ("voice_", "viewer_", "director_")


def _strip_histogram_suffix(name: str) -> str:
    """Retire le suffixe Prometheus histogram (_bucket, _count, _sum)."""
    for suffix in _HISTOGRAM_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _walk_exprs(panels: list[dict]) -> list[str]:
    """Collecte récursivement toutes les target.expr du dashboard JSON."""
    exprs: list[str] = []
    for panel in panels:
        for target in panel.get("targets", []):
            expr = target.get("expr")
            if expr:
                exprs.append(expr)
        # Récursion sur les sub-panels (rows Grafana v10 nested)
        sub = panel.get("panels")
        if sub:
            exprs.extend(_walk_exprs(sub))
    return exprs


# ---------------------------------------------------------------------------
# Test 1 — JSON parse OK
# ---------------------------------------------------------------------------


def test_dashboard_json_parses() -> None:
    """Le fichier dashboard doit exister et être un JSON valide."""
    assert DASHBOARD_PATH.exists(), (
        f"Dashboard absent : {DASHBOARD_PATH}\n"
        "Créer infra/grafana/dashboards/voice-body-pipeline.json (Phase GREEN)."
    )
    data = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "Le JSON de premier niveau doit être un objet."


# ---------------------------------------------------------------------------
# Test 2 — Schéma minimum
# ---------------------------------------------------------------------------


def test_dashboard_schema_minimum() -> None:
    """Top-level keys obligatoires + 7 rows minimum."""
    data = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))

    for key in ("title", "panels", "schemaVersion", "version"):
        assert key in data, f"Clé obligatoire absente du dashboard : {key!r}"

    assert isinstance(data["panels"], list), "panels doit être une liste."
    assert len(data["panels"]) >= 7, (
        f"7 rows obligatoires minimum, trouvé {len(data['panels'])}. "
        "Ajouter les rows Pipeline Health / Audio / TTS / Barge-in / Sync / WS / Turns."
    )
    assert data["schemaVersion"] == 39, (
        f"schemaVersion doit être 39 (Grafana 10+), trouvé {data['schemaVersion']}."
    )


# ---------------------------------------------------------------------------
# Test 3 — Cross-check métriques
# ---------------------------------------------------------------------------


def test_all_exprs_reference_known_metrics() -> None:
    """Aucune expr PromQL ne doit référencer une métrique inconnue.

    Identifie tous les identifiants avec préfixe voice_/viewer_/director_ et
    vérifie qu'ils sont dans ALLOWED_METRICS. Les keywords PromQL et valeurs
    de labels sont ignorés.
    """
    data = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    exprs = _walk_exprs(data["panels"])

    assert len(exprs) > 0, (
        "Aucune expr PromQL trouvée dans le dashboard. "
        "Ajouter des targets avec des expressions dans les panels."
    )

    unknown: list[tuple[str, str]] = []
    for expr in exprs:
        candidates = re.findall(r"\b([a-z_][a-z0-9_]*)\b", expr)
        for cand in candidates:
            if cand in _PROMQL_KEYWORDS:
                continue
            base = _strip_histogram_suffix(cand)
            # Vérification uniquement sur les identifiants avec préfixe métrique
            if any(base.startswith(p) for p in _METRIC_PREFIXES):
                if base not in ALLOWED_METRICS:
                    unknown.append((cand, expr))

    assert not unknown, (
        "Métriques inconnues référencées dans le dashboard :\n"
        + "\n".join(f"  - {cand!r} (base={_strip_histogram_suffix(cand)!r}) dans: {expr!r}"
                    for cand, expr in unknown[:10])
        + (f"\n  ... et {len(unknown) - 10} autres" if len(unknown) > 10 else "")
    )


# ---------------------------------------------------------------------------
# Test 4 — Threshold lines SLO §7.2
# ---------------------------------------------------------------------------


def test_slo_threshold_lines_present() -> None:
    """Les panels SLO critiques doivent avoir des threshold lines configurées.

    - Panel cancel_speaking p95 (Row 4) : threshold rouge à 200ms (SLO §7.2)
    - Panel audio_at_ms drift p95 (Row 5) : threshold rouge à 100ms (SLO §7.2)

    Les panels sont identifiés par le titre (sous-chaîne insensible à la casse).
    """
    data = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))

    found_cancel_slo = False
    found_drift_slo = False

    def _check_panels(panels: list[dict]) -> None:
        nonlocal found_cancel_slo, found_drift_slo
        for panel in panels:
            title = panel.get("title", "").lower()
            steps = (
                panel.get("fieldConfig", {})
                .get("defaults", {})
                .get("thresholds", {})
                .get("steps", [])
            )
            threshold_values = {s.get("value") for s in steps}

            # Panel Row 4 : cancel speaking, SLO 200ms
            if "cancel" in title and 200 in threshold_values:
                found_cancel_slo = True

            # Panel Row 5 : audio drift, SLO 100ms
            if ("drift" in title or "audio_at_ms" in title) and 100 in threshold_values:
                found_drift_slo = True

            # Récursion sur sub-panels
            sub = panel.get("panels")
            if sub:
                _check_panels(sub)

    _check_panels(data["panels"])

    assert found_cancel_slo, (
        "Panel cancel_speaking p95 avec threshold 200ms introuvable. "
        "Row 4 doit contenir un panel dont le titre contient 'cancel' "
        "et fieldConfig.defaults.thresholds.steps inclut {value: 200}."
    )
    assert found_drift_slo, (
        "Panel audio_at_ms drift p95 avec threshold 100ms introuvable. "
        "Row 5 doit contenir un panel dont le titre contient 'drift' ou 'audio_at_ms' "
        "et fieldConfig.defaults.thresholds.steps inclut {value: 100}."
    )
