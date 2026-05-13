# D-10C — Grafana Dashboard pour voice-body pipeline

> **Type** : Spec design — sub-project bornée, déléguée à ruflo-autopilot.
> **Date** : 2026-05-13
> **Auteur** : Claude chef d'orchestre (mode `feedback_chef_orchestre`)
> **Statut** : Spec validée par utilisateur (option B du readiness report).

---

## 1. Périmètre

### 1.1. Dans le scope

- 1 dashboard Grafana versionné en JSON : `infra/grafana/dashboards/voice-body-pipeline.json`
- 1 README d'installation : `infra/grafana/README.md`
- 1 test pytest de validation : `backend/tests/unit/observability/test_grafana_dashboard.py`
- Le dashboard couvre les **13 métriques exposées** par `voice/pipeline_metrics.py` + `voice/metrics.py` (inventaire exact §3).

### 1.2. Hors scope (différé)

- ❌ Tests Playwright frontend E2E (l'audit 2026-05-08 les couplait à D-10C — on découple, sprint séparé)
- ❌ Provisioning automatique via Helm/Kustomize (manuel uniquement pour MVP)
- ❌ Alerting Grafana / Prometheus Alertmanager (sprint observabilité dédié plus tard)
- ❌ Métriques agent-loop legacy (`observability/metrics.py`) — c'est un autre bounded context, dashboard séparé

### 1.3. Effort estimé

**2-3h** : 30 min spec → 1.5h dev TDD → 30 min review/PR.

---

## 2. Sources de vérité (à lire AVANT d'écrire le moindre fichier)

Le dashboard DOIT référencer **uniquement** des métriques qui existent dans ces 2 fichiers. Toute `expr` PromQL pointant vers une métrique inexistante = test rouge = bug.

| Fichier | Contenu | Lecture obligatoire |
|---|---|---|
| `backend/shugu/voice/pipeline_metrics.py` | 12 métriques : publisher, bridge, cancel, audio_at_ms, viewer_ws | ✅ Lire intégralement |
| `backend/shugu/voice/metrics.py` | `voice_turn_latency_seconds` + 8 stages constants | ✅ Lire intégralement |
| `docs/specs/2026-05-08-voice-body-pipeline-design.md` (§7.2) | Cibles SLO : barge-in <200ms p95, drift <100ms p95, TTFB 0.2-0.3s | ✅ Lire §7.2 |
| `docs/ops/voice-body-readiness-report-2026-05-13.md` (§2) | Inventaire récap des 13 métriques avec labels et buckets | ✅ Lire §2 |

---

## 3. Inventaire des 13 métriques (récap pour briefing)

### 3.1. `pipeline_metrics.py` — 12 métriques

| Métrique | Type | Labels | SLO |
|---|---|---|---|
| `voice_publisher_chunks_published_total` | Counter | — | — |
| `voice_publisher_chunks_dropped_total` | Counter | — | drop rate <1% |
| `voice_publisher_publish_duration_ms` | Histogram | — | p95 <100ms |
| `voice_bridge_sentences_published_total` | Counter | — | — |
| `voice_bridge_sentences_skipped_total` | Counter | `reason` (8 valeurs whitelist) | skip rate <5% |
| `voice_bridge_publish_sentence_duration_ms` | Histogram | — | p95 <3s |
| `voice_cancel_speaking_total` | Counter | `reason` (4 valeurs whitelist) | — |
| `voice_cancel_speaking_duration_ms` | Histogram | — | **p95 <200ms (SLO §7.2)** |
| `director_audio_at_ms_distribution` | Histogram | `kind` (3 valeurs whitelist) | **p95 <100ms (SLO §7.2)** |
| `viewer_ws_connections_total` | Counter | — | — |
| `viewer_ws_disconnects_total` | Counter | `reason` (5 valeurs whitelist) | — |
| `viewer_token_refresh_total` | Counter | `outcome` (5 valeurs whitelist) | — |

### 3.2. `metrics.py` — 1 métrique

| Métrique | Type | Labels | SLO |
|---|---|---|---|
| `voice_turn_latency_seconds` | Histogram | `stage` (7 valeurs), `intent` (5 valeurs whitelist) | **TTFB p50 0.2-0.3s (SLO §7.2)**, label `stage="audio_first"` |

---

## 4. Structure du dashboard (7 rows obligatoires)

Le dashboard DOIT comporter au minimum les 7 rows suivantes. Le ruflo peut ajouter des variantes (sparklines, gauges) mais pas en enlever.

### Row 1 — Pipeline Health Overview

| Panel | Type | PromQL principal |
|---|---|---|
| TTFB voice (p50/p95/p99) | Time series | `histogram_quantile(0.5\|0.95\|0.99, sum(rate(voice_turn_latency_seconds_bucket{stage="audio_first"}[5m])) by (le))` |
| Turn rate (turns/min) | Stat | `sum(rate(voice_turn_latency_seconds_count{stage="audio_first"}[1m])) * 60` |
| Bridge sentence success rate | Stat (%) | `100 * sum(rate(voice_bridge_sentences_published_total[5m])) / (sum(rate(voice_bridge_sentences_published_total[5m])) + sum(rate(voice_bridge_sentences_skipped_total[5m])))` |
| Chunk drop rate | Stat (%) | `100 * sum(rate(voice_publisher_chunks_dropped_total[5m])) / sum(rate(voice_publisher_chunks_published_total[5m]))` |

### Row 2 — Audio Pipeline (Publisher D-1)

| Panel | Type | PromQL |
|---|---|---|
| Chunks published/sec | Time series | `sum(rate(voice_publisher_chunks_published_total[1m]))` |
| Publish duration (p50/p95) | Time series | `histogram_quantile(0.5\|0.95, sum(rate(voice_publisher_publish_duration_ms_bucket[5m])) by (le))` + **threshold line à 100ms (SLO)** |
| Drop counter | Time series | `sum(rate(voice_publisher_chunks_dropped_total[1m]))` |

### Row 3 — TTS Bridge (D-2)

| Panel | Type | PromQL |
|---|---|---|
| Sentences published/min | Time series | `sum(rate(voice_bridge_sentences_published_total[1m])) * 60` |
| Skipped breakdown by reason | Time series stacked | `sum(rate(voice_bridge_sentences_skipped_total[5m])) by (reason)` |
| Publish sentence duration (p50/p95) | Time series | `histogram_quantile(0.5\|0.95, sum(rate(voice_bridge_publish_sentence_duration_ms_bucket[5m])) by (le))` |

### Row 4 — Barge-in (D-4) ⚠️ SLO panel

| Panel | Type | PromQL |
|---|---|---|
| Cancel duration p95 vs SLO | Gauge | `histogram_quantile(0.95, sum(rate(voice_cancel_speaking_duration_ms_bucket[5m])) by (le))` + **threshold rouge à 200ms (SLO §7.2)** |
| Cancel/min by reason | Time series stacked | `sum(rate(voice_cancel_speaking_total[1m])) by (reason) * 60` |

### Row 5 — Audio↔Expression Sync (D-5) ⚠️ SLO panel

| Panel | Type | PromQL |
|---|---|---|
| audio_at_ms drift p95 by kind | Time series | `histogram_quantile(0.95, sum(rate(director_audio_at_ms_distribution_bucket[5m])) by (le, kind))` + **threshold à 100ms (SLO §7.2)** |
| Drift heatmap | Heatmap | `sum(rate(director_audio_at_ms_distribution_bucket[5m])) by (le)` |

### Row 6 — Viewer WS (D-3)

| Panel | Type | PromQL |
|---|---|---|
| Connections opened | Time series | `sum(rate(viewer_ws_connections_total[1m]))` |
| Disconnects by reason | Time series stacked | `sum(rate(viewer_ws_disconnects_total[5m])) by (reason)` |
| Token refresh outcomes | Pie | `sum(rate(viewer_token_refresh_total[5m])) by (outcome)` |

### Row 7 — Turn Pipeline Stages

| Panel | Type | PromQL |
|---|---|---|
| TTFB cumulé par stage (p95) | Time series stacked | `histogram_quantile(0.95, sum(rate(voice_turn_latency_seconds_bucket[5m])) by (le, stage))` filtré sur stages = {stt, intent, llm_first_token, tts_first_frame, audio_first} |
| Turns by intent | Pie | `sum(rate(voice_turn_latency_seconds_count{stage="audio_first"}[5m])) by (intent)` |

---

## 5. Test de validation — invariants à respecter

Le fichier `backend/tests/unit/observability/test_grafana_dashboard.py` DOIT garantir :

1. **JSON parse OK** : `json.loads(Path(dashboard_path).read_text())` ne raise pas.
2. **Schéma minimum** : top-level keys `title`, `panels`, `schemaVersion`, `version` présents.
3. **Toutes les `expr` référencent des métriques connues** :
   - Parser tous les `target.expr` récursivement.
   - Extraire les noms de métriques via regex `[a-z_]+_(?:total|count|bucket|sum|_seconds|_ms|_distribution)` ou plus simplement `[a-z][a-z0-9_]*` filtrés.
   - Cross-check vs whitelist en dur dans le test (les 13 métriques + suffixes `_total`, `_count`, `_bucket`, `_sum` pour les histograms).
4. **Tous les labels utilisés existent** : pour chaque `{label=...}`, vérifier qu'il fait partie des whitelists des modules source (`_VALID_CANCEL_REASONS`, `_VALID_SKIP_REASONS`, `_VALID_INTENT_LABELS`, etc.). Idéalement, **importer** ces whitelists depuis `pipeline_metrics.py` et `metrics.py` pour ne pas dupliquer la source de vérité.
5. **Threshold lines SLO** : panels Row 4 (cancel_speaking p95) et Row 5 (audio_at_ms p95) DOIVENT avoir un `thresholds` array avec valeur 200 et 100 respectivement.
6. **Coverage** : ≥ 90% sur le module de validation (cross-check + label invariants).

---

## 6. Contraintes non négociables (TDD ruflo)

Suivre `feedback_workflow_discipline.md` :

- ✅ **TDD strict** : RED (test) → GREEN (impl minimale) → REFACTOR. Jamais l'inverse.
- ✅ **Modulaire** : pas de dashboard monolithique en 1 fichier de 1500 lignes. Si le JSON dépasse 500 lignes, splitter les rows en panels-builders Python qui assemblent le JSON via tests (pattern data-as-code). Sinon JSON direct OK.
- ✅ **Documenté** : README explique import manuel (UI Grafana → Import JSON) + import automatique (Grafana provisioning `/etc/grafana/provisioning/dashboards/`).
- ✅ **Lire avant écrire** : lire les 2 fichiers source (`pipeline_metrics.py` + `metrics.py`) intégralement avant d'écrire un seul `expr` PromQL.
- ✅ **Jamais modifier un test pour qu'il passe** : si le cross-check rouge, c'est la `expr` qui est fausse, pas le test.
- ✅ **STOP si bloqué après 3 tentatives** : remonter pour décision humaine.

---

## 7. Livrables attendus

| Path | Contenu |
|---|---|
| `infra/grafana/dashboards/voice-body-pipeline.json` | Dashboard JSON avec 7 rows obligatoires |
| `infra/grafana/README.md` | Comment importer (manuel + provisioning) + screenshot expected (laisser placeholder) |
| `backend/tests/unit/observability/test_grafana_dashboard.py` | Tests pytest (JSON parse, schéma, cross-check métriques, threshold SLO) — ≥ 90% coverage |
| Commit message format | `📊 feat(observability): D-10C Grafana dashboard voice-body pipeline` |
| PR title | `feat(observability): D-10C — Grafana dashboard voice-body pipeline + cross-check tests` |

---

## 8. PR finale — template attendu

```markdown
## Summary

- Ajoute le dashboard Grafana `voice-body-pipeline.json` couvrant les 13 métriques Prometheus du pipeline voice ↔ body
- Tests pytest cross-check garantissent que toutes les `expr` PromQL référencent des métriques exposées (anti-drift)
- README explique l'import manuel + automatique (Grafana provisioning)

## Couverture SLO §7.2

- ✅ Cancel speaking p95 <200ms — Gauge Row 4 avec threshold
- ✅ Audio-at-ms drift p95 <100ms — Time series Row 5 avec threshold
- ✅ TTFB voice p50 0.2-0.3s — Row 1 + Row 7

## Test plan

- [ ] `pytest backend/tests/unit/observability/test_grafana_dashboard.py -v` GREEN
- [ ] Import manuel du JSON dans une instance Grafana locale → tous les panels affichent (même vides sans données)
- [ ] `curl localhost:8000/metrics | grep -E "(voice_|director_audio_at_ms|viewer_)"` doit lister toutes les métriques référencées

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## 9. Anti-patterns à éviter

- ❌ Inventer des métriques qui n'existent pas (`voice_response_quality_score`, etc.)
- ❌ Dupliquer les whitelists de labels dans le test au lieu d'importer depuis les modules source
- ❌ Mettre les threshold SLO en valeur arbitraire (200, 100) sans commentaire référençant §7.2
- ❌ Skipper le README (orphelin = dashboard non importable)
- ❌ Ajouter Playwright dans la même PR (out of scope, sprint séparé)
