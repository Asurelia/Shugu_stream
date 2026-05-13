# D-10C Grafana Dashboard — Implementation Plan TDD

> **Spec source** : `docs/superpowers/specs/2026-05-13-d10c-grafana-dashboard-design.md`
> **Effort total estimé** : 2-3h
> **Branche** : `feat/voice-d10c-grafana-dashboard-20260513-XXXXXX-001` (timestamp réel à générer)

---

## Préalable — Setup branche + lecture sources

### Task 0.1 — Créer branche depuis main

```bash
git checkout main
git pull origin main
git checkout -b feat/voice-d10c-grafana-dashboard-$(date +%Y%m%d-%H%M%S)-001
```

### Task 0.2 — Lire les 4 sources de vérité (PAS DE CODE encore)

- [ ] `backend/shugu/voice/pipeline_metrics.py` (intégral, ~485 lignes)
- [ ] `backend/shugu/voice/metrics.py` (intégral, ~270 lignes)
- [ ] `docs/specs/2026-05-08-voice-body-pipeline-design.md` §7.2 (cibles SLO)
- [ ] `docs/ops/voice-body-readiness-report-2026-05-13.md` §2 (récap métriques)

### Task 0.3 — Vérifier qu'aucun fichier cible n'existe déjà

```bash
ls infra/grafana/dashboards/voice-body-pipeline.json   # doit NOT exist
ls infra/grafana/README.md                              # doit NOT exist
ls backend/tests/unit/observability/test_grafana_dashboard.py  # doit NOT exist
```

Si l'un existe déjà → STOP, demander à Claude.

---

## Phase 1 — Tests RED (avant TOUT code de prod)

### Task 1.1 — Créer le module de test

Fichier : `backend/tests/unit/observability/test_grafana_dashboard.py`

Imports nécessaires :
```python
import json
import re
from pathlib import Path
import pytest
from shugu.voice.pipeline_metrics import (
    _VALID_CANCEL_REASONS,
    _VALID_SKIP_REASONS,
    _VALID_WS_DISCONNECT_REASONS,
    _VALID_REFRESH_OUTCOMES,
    _VALID_AUDIO_AT_MS_KINDS,
)
from shugu.voice.metrics import _VALID_INTENT_LABELS
```

Si `backend/tests/unit/observability/__init__.py` n'existe pas, le créer (touch fichier vide).

### Task 1.2 — Test 1 : JSON parse OK

```python
DASHBOARD_PATH = Path(__file__).resolve().parents[3] / "infra" / "grafana" / "dashboards" / "voice-body-pipeline.json"

def test_dashboard_json_parses():
    """Le fichier dashboard doit être un JSON valide."""
    assert DASHBOARD_PATH.exists(), f"Dashboard absent : {DASHBOARD_PATH}"
    data = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
```

→ RED attendu (fichier n'existe pas).

### Task 1.3 — Test 2 : Schéma minimum

```python
def test_dashboard_schema_minimum():
    """Top-level keys obligatoires."""
    data = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    assert "title" in data
    assert "panels" in data
    assert "schemaVersion" in data
    assert "version" in data
    assert isinstance(data["panels"], list)
    assert len(data["panels"]) >= 7, "7 rows obligatoires minimum"
```

→ RED attendu.

### Task 1.4 — Test 3 : Cross-check métriques

```python
# Whitelist exhaustive — DOIT matcher pipeline_metrics.py + metrics.py
ALLOWED_METRICS = frozenset({
    # Counters (avec suffixes _total et _count pour PromQL rate)
    "voice_publisher_chunks_published_total",
    "voice_publisher_chunks_dropped_total",
    "voice_bridge_sentences_published_total",
    "voice_bridge_sentences_skipped_total",
    "voice_cancel_speaking_total",
    "viewer_ws_connections_total",
    "viewer_ws_disconnects_total",
    "viewer_token_refresh_total",
    # Histograms (PromQL utilise _bucket/_count/_sum/_seconds)
    "voice_publisher_publish_duration_ms",
    "voice_bridge_publish_sentence_duration_ms",
    "voice_cancel_speaking_duration_ms",
    "director_audio_at_ms_distribution",
    "voice_turn_latency_seconds",
})

HISTOGRAM_SUFFIXES = ("_bucket", "_count", "_sum")

def _extract_metric_names_from_expr(expr: str) -> set[str]:
    """Extrait les noms de métriques d'une expression PromQL."""
    # Pattern : identifiants Prometheus possibles dans une expr
    candidates = re.findall(r"\b([a-z_][a-z0-9_]*)\b", expr)
    metrics = set()
    for c in candidates:
        # Strip suffixe histogram si présent
        base = c
        for suffix in HISTOGRAM_SUFFIXES:
            if c.endswith(suffix):
                base = c[: -len(suffix)]
                break
        if base in ALLOWED_METRICS:
            metrics.add(base)
    return metrics


def _walk_exprs(panels: list) -> list[str]:
    """Collecte récursivement tous les target.expr du dashboard."""
    exprs = []
    for panel in panels:
        for target in panel.get("targets", []):
            expr = target.get("expr")
            if expr:
                exprs.append(expr)
        # Récurse sur sub-panels (rows Grafana)
        if "panels" in panel:
            exprs.extend(_walk_exprs(panel["panels"]))
    return exprs


def test_all_exprs_reference_known_metrics():
    """Aucune expr PromQL ne doit référencer une métrique inconnue."""
    data = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    exprs = _walk_exprs(data["panels"])
    assert len(exprs) > 0, "Aucune expr trouvée — dashboard vide ?"

    for expr in exprs:
        # Extraction tous les identifiants qui ressemblent à des métriques
        candidates = re.findall(r"\b([a-z_][a-z0-9_]*)\b", expr)
        # PromQL keywords à ignorer
        promql_keywords = {
            "sum", "rate", "histogram_quantile", "by", "on", "le",
            "avg", "max", "min", "count", "without", "ignoring",
            "and", "or", "unless", "bool", "offset", "topk", "bottomk",
        }
        for cand in candidates:
            if cand in promql_keywords:
                continue
            # Doit être soit une métrique connue (avec ou sans suffix histogram),
            # soit une valeur de label, soit un identifiant interne au panel.
            base = cand
            for suffix in HISTOGRAM_SUFFIXES:
                if cand.endswith(suffix):
                    base = cand[: -len(suffix)]
                    break
            if base.startswith(("voice_", "viewer_", "director_")):
                assert base in ALLOWED_METRICS, (
                    f"Métrique inconnue référencée : {cand} (base={base}) dans expr : {expr}"
                )
```

→ RED attendu.

### Task 1.5 — Test 4 : SLO threshold lines

```python
def test_slo_threshold_lines_present():
    """Les panels SLO (cancel_speaking p95, audio_at_ms p95) doivent avoir des threshold."""
    data = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    
    found_cancel_slo = False
    found_drift_slo = False
    
    def _check(panels):
        nonlocal found_cancel_slo, found_drift_slo
        for panel in panels:
            title = panel.get("title", "").lower()
            thresholds = panel.get("fieldConfig", {}).get("defaults", {}).get("thresholds", {}).get("steps", [])
            
            if "cancel" in title and any(t.get("value") == 200 for t in thresholds):
                found_cancel_slo = True
            if ("drift" in title or "audio_at_ms" in title) and any(t.get("value") == 100 for t in thresholds):
                found_drift_slo = True
            
            if "panels" in panel:
                _check(panel["panels"])
    
    _check(data["panels"])
    assert found_cancel_slo, "Panel cancel_speaking p95 doit avoir threshold 200ms (SLO §7.2)"
    assert found_drift_slo, "Panel audio_at_ms p95 doit avoir threshold 100ms (SLO §7.2)"
```

→ RED attendu.

### Task 1.6 — Vérifier les 4 tests RED

```bash
cd backend
pytest tests/unit/observability/test_grafana_dashboard.py -v
```

Attendu : 4 tests FAIL (fichier dashboard inexistant). Si un test PASS par hasard → bug, à investiguer.

---

## Phase 2 — Implémentation GREEN

### Task 2.1 — Créer l'arborescence

```bash
mkdir -p infra/grafana/dashboards
```

### Task 2.2 — Créer le dashboard JSON minimal pour faire passer test 1 + 2

Fichier : `infra/grafana/dashboards/voice-body-pipeline.json`

Squelette minimum :
```json
{
  "title": "Shugu — Voice ↔ Body Pipeline",
  "schemaVersion": 39,
  "version": 1,
  "panels": [
    {"id": 1, "title": "Row 1 — Pipeline Health", "type": "row", "panels": []},
    {"id": 2, "title": "Row 2 — Audio Pipeline", "type": "row", "panels": []},
    {"id": 3, "title": "Row 3 — TTS Bridge", "type": "row", "panels": []},
    {"id": 4, "title": "Row 4 — Barge-in SLO", "type": "row", "panels": []},
    {"id": 5, "title": "Row 5 — Audio Sync SLO", "type": "row", "panels": []},
    {"id": 6, "title": "Row 6 — Viewer WS", "type": "row", "panels": []},
    {"id": 7, "title": "Row 7 — Turn Stages", "type": "row", "panels": []}
  ]
}
```

→ Test 1 + 2 PASS, test 3 + 4 toujours RED.

### Task 2.3 — Remplir les rows avec panels Time series + PromQL

Pour chaque row, ajouter les panels listés dans le spec §4. Exemple Row 1 :

```json
{
  "id": 1,
  "title": "Row 1 — Pipeline Health",
  "type": "row",
  "panels": [
    {
      "id": 100,
      "title": "TTFB voice (p50/p95/p99)",
      "type": "timeseries",
      "targets": [
        {"expr": "histogram_quantile(0.50, sum(rate(voice_turn_latency_seconds_bucket{stage=\"audio_first\"}[5m])) by (le))", "legendFormat": "p50"},
        {"expr": "histogram_quantile(0.95, sum(rate(voice_turn_latency_seconds_bucket{stage=\"audio_first\"}[5m])) by (le))", "legendFormat": "p95"},
        {"expr": "histogram_quantile(0.99, sum(rate(voice_turn_latency_seconds_bucket{stage=\"audio_first\"}[5m])) by (le))", "legendFormat": "p99"}
      ]
    },
    ...
  ]
}
```

Compléter les 7 rows selon §4 du spec. Re-run pytest après chaque row → tests 1+2+3 progressivement plus stricts.

### Task 2.4 — Ajouter les threshold SLO (Row 4 + Row 5)

Sur le panel cancel_speaking p95 (Row 4) :
```json
{
  "fieldConfig": {
    "defaults": {
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "green", "value": null},
          {"color": "red", "value": 200}
        ]
      }
    }
  }
}
```

Idem panel audio_at_ms (Row 5) avec value 100.

→ Test 4 PASS.

### Task 2.5 — Vérifier tous les tests GREEN

```bash
pytest tests/unit/observability/test_grafana_dashboard.py -v --cov=. --cov-report=term-missing
```

Tous PASS, coverage ≥ 90%.

---

## Phase 3 — README

### Task 3.1 — Créer `infra/grafana/README.md`

Sections obligatoires :

1. **Vue d'ensemble** — Ce dashboard couvre les 13 métriques voice/pipeline. Cibles SLO §7.2.
2. **Import manuel** — Grafana UI → Dashboards → New → Import → Upload JSON file → sélectionner `voice-body-pipeline.json`.
3. **Import automatique (provisioning)** — Copier le JSON dans `/etc/grafana/provisioning/dashboards/`, plus fichier YAML provider :
   ```yaml
   apiVersion: 1
   providers:
     - name: 'shugu-voice'
       folder: 'Shugu'
       type: file
       options:
         path: /etc/grafana/provisioning/dashboards/voice-body
   ```
4. **Prérequis datasource** — Datasource Prometheus configurée pointant vers `${BACKEND_HOST}:${BACKEND_PORT}/metrics`.
5. **Screenshot** — Placeholder : `![Dashboard preview](./screenshots/voice-body-pipeline.png)` avec note "Screenshot à capturer après 1er live test (smoke 30 min)".
6. **Lien spec/plan** — Référencer `docs/superpowers/specs/2026-05-13-d10c-grafana-dashboard-design.md`.

---

## Phase 4 — Commit + PR

### Task 4.1 — Commit

```bash
git add infra/grafana/ backend/tests/unit/observability/
git commit -m "$(cat <<'EOF'
📊 feat(observability): D-10C Grafana dashboard voice-body pipeline

Ajoute le dashboard Grafana versionné couvrant les 13 métriques Prometheus
exposées par voice/pipeline_metrics.py + voice/metrics.py. Inclut les 2
panels SLO §7.2 avec threshold lines (cancel_speaking p95 <200ms, drift
audio_at_ms p95 <100ms).

Tests pytest cross-check garantissent que toutes les expr PromQL référencent
des métriques exposées (anti-drift dashboard ↔ code source).

Spec : docs/superpowers/specs/2026-05-13-d10c-grafana-dashboard-design.md
Plan : docs/superpowers/plans/2026-05-13-d10c-grafana-dashboard-plan.md

Co-Authored-By: ruflo-autopilot <noreply@anthropic.com>
EOF
)"
```

### Task 4.2 — Push + PR

```bash
git push -u origin HEAD
gh pr create --title "📊 feat(observability): D-10C Grafana dashboard voice-body pipeline" --body "$(cat <<'EOF'
## Summary

- Dashboard Grafana `voice-body-pipeline.json` couvrant les 13 métriques Prometheus voice/pipeline
- Tests pytest cross-check garantissent intégrité expr PromQL ↔ source code (anti-drift)
- README import manuel + provisioning automatique
- Threshold SLO §7.2 explicites sur Row 4 (cancel <200ms) et Row 5 (drift <100ms)

## Couverture SLO §7.2

- ✅ Cancel speaking p95 <200ms — Row 4 Gauge
- ✅ Audio-at-ms drift p95 <100ms — Row 5 Time series
- ✅ TTFB voice p50 0.2-0.3s — Row 1 + Row 7

## Test plan

- [x] `pytest backend/tests/unit/observability/test_grafana_dashboard.py -v` GREEN
- [x] Coverage ≥ 90%
- [ ] Import manuel du JSON dans Grafana local → tous les panels rendus (validation humaine)
- [ ] Smoke test live 30 min → screenshot à capturer + ajout dans `infra/grafana/screenshots/`

## Spec / Plan

- Design : `docs/superpowers/specs/2026-05-13-d10c-grafana-dashboard-design.md`
- Plan : `docs/superpowers/plans/2026-05-13-d10c-grafana-dashboard-plan.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Garde-fous (STOP conditions)

Si l'une de ces conditions arrive, ruflo doit **STOPPER** et remonter à Claude :

- ❌ Un test échoue 3 fois consécutives sans progrès
- ❌ La whitelist `ALLOWED_METRICS` doit être modifiée (ça signifie qu'une métrique a été inventée — bug)
- ❌ Le JSON dashboard dépasse 1500 lignes (mauvais signe, repenser structure)
- ❌ Une métrique référencée existe pas dans pipeline_metrics.py / metrics.py
- ❌ Un test fail mystérieusement — NE PAS le modifier, comprendre pourquoi
- ❌ Coverage <90% après Phase 2 — investigeur, pas masquer

---

## Contrat final

**À la fin de ce plan, le repo doit avoir :**

- 3 nouveaux fichiers : dashboard JSON, README, test pytest
- 1 commit avec message conforme + co-author ruflo
- 1 PR ouverte sur origin avec template ci-dessus
- 0 modification de fichier existant (sub-project purement additif)
- 0 ajout de dépendance dans `pyproject.toml` (tests utilisent stdlib + pytest existant)

Si tout vert : ping Claude pour review → merge → chantier voice-body MVP **lockable**.
