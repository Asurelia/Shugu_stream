# Grafana Dashboard — Shugu Voice ↔ Body Pipeline

> **Spec** : `docs/superpowers/specs/2026-05-13-d10c-grafana-dashboard-design.md`
> **Plan** : `docs/superpowers/plans/2026-05-13-d10c-grafana-dashboard-plan.md`
> **Version** : 1 (schemaVersion 39 — Grafana 10+)

---

## Vue d'ensemble

Ce dashboard couvre les **13 métriques Prometheus** exposées par le pipeline voice ↔ body Shugu via `GET /metrics`.

| Source | Métriques |
|--------|-----------|
| `backend/shugu/voice/pipeline_metrics.py` | 12 métriques : publisher, bridge, cancel, audio_at_ms, viewer_ws |
| `backend/shugu/voice/metrics.py` | `voice_turn_latency_seconds` (7 stages, 5 intents) |

### Cibles SLO §7.2

| Panel | Métrique | SLO | Threshold |
|-------|----------|-----|-----------|
| Row 4 — Cancel speaking p95 | `voice_cancel_speaking_duration_ms` | p95 < 200ms | Gauge rouge à 200ms |
| Row 5 — Audio drift p95 | `director_audio_at_ms_distribution` | p95 < 100ms | Série rouge à 100ms |
| Row 1 — TTFB voice p50 | `voice_turn_latency_seconds{stage="audio_first"}` | p50 dans 0.2-0.3s | Time series |

### 7 Rows du dashboard

| Row | Contenu |
|-----|---------|
| 1 — Pipeline Health Overview | TTFB p50/p95/p99, turn rate, success/drop/skip rate |
| 2 — Audio Pipeline (D-1) | Chunks published, publish duration, drops |
| 3 — TTS Bridge (D-2) | Sentences published/skipped, sentence duration |
| 4 — Barge-in SLO (D-4) | Cancel p95 gauge avec threshold 200ms |
| 5 — Audio Sync SLO (D-5) | Drift p95 par kind + heatmap avec threshold 100ms |
| 6 — Viewer WebSocket (D-3) | Connexions, déconnexions, token refresh |
| 7 — Turn Pipeline Stages | TTFB stacked par stage, répartition par intent |

---

## Prérequis

- Grafana 10+ (schemaVersion 39)
- Une datasource **Prometheus** configurée pointant vers `${BACKEND_HOST}:${BACKEND_PORT}/metrics`
- Variables d'env backend actives :
  - `SHUGU_METRICS_ENABLED=true`
  - `SHUGU_VOICE_METRICS_ENABLED=true`

---

## Import manuel (Grafana UI)

1. Ouvrir Grafana → **Dashboards** → **New** → **Import**
2. Cliquer **Upload dashboard JSON file**
3. Sélectionner `infra/grafana/dashboards/voice-body-pipeline.json`
4. Sélectionner la datasource Prometheus dans le menu déroulant
5. Cliquer **Import**

Les panels s'affichent (vides si aucune métrique n'est encore collectée).

---

## Import automatique (Grafana Provisioning)

Pour automatiser le chargement au démarrage de Grafana :

### 1. Copier le dashboard JSON

```bash
cp infra/grafana/dashboards/voice-body-pipeline.json \
   /etc/grafana/provisioning/dashboards/voice-body/voice-body-pipeline.json
```

### 2. Créer le fichier provider YAML

Créer `/etc/grafana/provisioning/dashboards/shugu-voice.yaml` :

```yaml
apiVersion: 1
providers:
  - name: 'shugu-voice'
    orgId: 1
    folder: 'Shugu'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards/voice-body
```

### 3. Redémarrer Grafana

```bash
systemctl restart grafana-server
# ou avec Docker :
docker restart grafana
```

Grafana chargera automatiquement le dashboard au démarrage et le mettra à jour toutes les 30 secondes si le fichier change.

---

## Vérification des métriques disponibles

Pour vérifier que les métriques voice sont bien exposées :

```bash
curl -s localhost:8000/metrics | grep -E "^(voice_|director_audio_at_ms|viewer_)"
```

Les 13 métriques suivantes doivent apparaître (au moins une fois chacune) :

```
voice_publisher_chunks_published_total
voice_publisher_chunks_dropped_total
voice_publisher_publish_duration_ms_bucket
voice_bridge_sentences_published_total
voice_bridge_sentences_skipped_total
voice_bridge_publish_sentence_duration_ms_bucket
voice_cancel_speaking_total
voice_cancel_speaking_duration_ms_bucket
director_audio_at_ms_distribution_bucket
viewer_ws_connections_total
viewer_ws_disconnects_total
viewer_token_refresh_total
voice_turn_latency_seconds_bucket
```

---

## Validation des tests

```bash
cd backend
pytest tests/unit/observability/test_grafana_dashboard.py -v
```

Les 4 tests pytest garantissent :

1. **JSON parse OK** — dashboard valide et parseable
2. **Schéma minimum** — 7 rows obligatoires, schemaVersion 39
3. **Cross-check métriques** — toutes les `expr` PromQL référencent des métriques existantes (anti-drift)
4. **Threshold SLO** — panels Row 4 et Row 5 avec threshold lines à 200ms et 100ms

---

## Screenshot

![Dashboard preview](./screenshots/voice-body-pipeline.png)

> **Note** : Screenshot à capturer après le premier live test (smoke 30 min).
> Chemin attendu : `infra/grafana/screenshots/voice-body-pipeline.png`

---

## Mise à jour du dashboard

Pour modifier le dashboard :

1. Éditer `infra/grafana/dashboards/voice-body-pipeline.json`
2. Incrémenter le champ `"version"` dans le JSON
3. Vérifier que `pytest tests/unit/observability/test_grafana_dashboard.py` reste GREEN
4. Committer et merger — le provisioning auto rechargera le fichier

**Contrainte** : ne jamais ajouter de métriques qui n'existent pas dans
`backend/shugu/voice/pipeline_metrics.py` ou `backend/shugu/voice/metrics.py`.
Le test 3 (cross-check) échouera si une `expr` PromQL référence une métrique inconnue.
