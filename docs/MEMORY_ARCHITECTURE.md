# Architecture Mémoire — Shugu

## Vue d'ensemble

Le sous-système mémoire de Shugu permet au streamer IA de mémoriser durablement
les viewers (noms, préférences, événements) pour personnaliser chaque interaction.

## Pipeline complet (PR 1 → PR 3)

```
                                      [Viewer chat / Operator voice]
                                                    │
                                          sense.raw (EventBus)
                                                    │
                                         IngestionWorker (PR 1+2)
                                                    │
                                    MemoryAgent.record_episode()
                                                    │
                                      INSERT memory_episodes (DB)
                                                    │
                              publish memory.episode_stored (EventBus)
                                                    │
                                      ExtractionWorker (PR 3)
                                                    │
                             FactExtractor.extract(text, subject=...)
                              ┌────────────────────┴─────────────────────┐
                      RegexFactExtractor                          LlmFactExtractor
                   (haute confiance, 0 coût)              (fallback, opt-in, coûteux)
                              └────────────────────┬─────────────────────┘
                                                   │
                                   [list[MemoryItem] — déjà formés]
                                                   │
                                      MemoryAgent.store() ← single-writer rule
                                                   │
                               INSERT/UPSERT memory_facts (DB + pgvector)
                                                   │
                             Director.recall(RecallQuery(subject=...))
                                                   │
                              Cosine similarity pgvector (Phase 2.2+)
                                          OU ILIKE fallback
                                                   │
                                   Director répond avec contexte viewer
```

## Composants

### IngestionWorker (`pipeline/ingestion_worker.py`)
- Subscribe `sense.raw`
- Construit `MemoryEpisode` depuis l'event
- Appelle `MemoryAgent.record_episode()` → INSERT + publish `memory.episode_stored`
- Best-effort : swallow exceptions, reste up

### ExtractionWorker (`pipeline/extraction_worker.py`) — PR 3
- Subscribe `memory.episode_stored`
- Filtre `event_type ∈ {chat_in, voice_in, response_out}`
- Lit le texte depuis `redacted_payload.text` (prioritaire) ou `payload.text`
- Appelle `FactExtractor.extract(text, subject=...)`
- Loop `MemoryAgent.store(item)` pour chaque fact extrait
- Best-effort : swallow exceptions, reste up

### FactExtractor (`memory/extractors/pipeline.py`) — Phase 2.3
- Pipeline regex-first → LLM-fallback
- `RegexFactExtractor` : patterns bilingues FR/EN, confidence 0.6, source `extraction_regex`
- `LlmFactExtractor` : wrapper fin sur `MemoryExtractorBrain`, opt-in via
  `fact_extractor_llm_fallback_enabled=True`

### MemoryAgent (`memory/agent.py`)
- **Single-writer rule** : seul point d'entrée pour INSERT `memory_facts`
- `store(item)` : auto-embed via FastEmbed si embedder configuré
- `recall(query)` : cosine search pgvector (Phase 2.2+) ou ILIKE fallback
- `record_episode(ep)` : INSERT `memory_episodes` + publish `memory.episode_stored`
- `maintenance()` : decay + hard-delete + dedupe sémantique (Phase 2.7)

## Flags de configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `memory_enabled` | `True` | Active l'ensemble du sous-système mémoire |
| `fact_extractor_enabled` | `True` | Active l'ExtractionWorker (PR 3) |
| `fact_extractor_llm_fallback_enabled` | `False` | Active le fallback LLM (coûteux, opt-in) |

## Règles de design

1. **Single-writer rule** : SEUL `MemoryAgent.store()` INSERT `memory_facts`.
   Les workers ne construisent jamais de row ORM directement.
2. **MemoryAgent LLM-free** : l'agent ne fait jamais d'appel LLM lui-même.
   L'extraction LLM est déléguée à `FactExtractor` / `MemoryExtractorBrain`.
3. **Best-effort** : les workers (Ingestion, Extraction) swallowent les exceptions —
   un crash DB ou LLM ne casse pas la pipeline de streaming.
4. **Privacy** : `redact()` (Phase 2.6) est appliqué sur le payload AVANT
   l'INSERT et AVANT l'extraction des facts. Le texte nettoyé est transmis
   dans `redacted_payload` de l'event `memory.episode_stored`.

## Concurrent safety

- `IngestionWorker` et `ExtractionWorker` subscribent sur des topics distincts
  → queues asyncio indépendantes, pas de contention.
- Chaque worker est une unique `asyncio.Task` séquentielle → pas de race
  condition interne.
- Race de doublons : deux events proches pour le même subject peuvent créer
  deux facts "name: Alice". Les IDs sont des ULID distincts → deux rows
  séparées. La maintenance Phase 2.7 (dedupe sémantique) harmonise.

## Compactor (Mémoire PR 4)

### Rôle

Quand un sujet (`subject_key`) accumule plus de **20 facts actifs** dans
`memory_facts`, le Compactor les condense via LLM en un résumé compact.

### Pipeline

```
MemoryCompactor.compact_all_eligible()
  └─ list_subjects_above_threshold(threshold=20)  ← MemoryAgent (read)
       └─ pour chaque sujet éligible :
            compact_subject(subject_key)
              ├─ list_active_facts(subject_key)    ← MemoryAgent (read)
              ├─ _call_brain(facts)                ← DirectorBrain (LLM)
              ├─ _parse_summary_response(raw)      ← JSON robuste
              ├─ store_compacted_summary(...)      ← MemoryAgent (write, single-writer)
              └─ mark_facts_compacted(ids)         ← MemoryAgent (write, single-writer)
```

### Provider LLM

Utilise `DirectorBrain` protocol (même provider que le Director) :
- **Default** : MiniMax via `brain_provider.py` E2.5
- **Fallback** : Anthropic (configuré via `settings.director_llm_provider`)

### Soft-archive vs delete

Les facts sources sont **soft-archivés** (`compacted_at = now()`) — jamais
supprimés. Avantages :
- **Audit** : retrouver les facts originaux si le résumé LLM est erroné.
- **Rollback** : remettre `compacted_at = NULL` pour annuler une compaction.
- **Traçabilité** : chaque summary fact porte `compact_origin_ids = [ids sources]`.

### Garantie single-writer

Le Compactor n'accède jamais à la DB directement. Toutes les opérations
passent par `MemoryAgent` :
- `list_active_facts()` — SELECT actifs (WHERE compacted_at IS NULL AND is_compacted_summary IS NOT TRUE)
- `store_compacted_summary()` — INSERT summary avec flag `is_compacted_summary=True`
- `mark_facts_compacted()` — UPDATE `compacted_at = now()` sur les sources

Vérifié par `test_single_writer_enforcement_compactor_uses_only_agent_methods`
(scan AST des imports de `compactor.py`).

### Idempotence

Un 2e run sur le même sujet skip automatiquement : les sources ont déjà
`compacted_at` non-null, donc `list_active_facts()` retourne < threshold facts.

### Champs DB ajoutés (migration 0011)

| Colonne | Type | Description |
|---------|------|-------------|
| `compacted_at` | TIMESTAMPTZ NULL | Timestamp soft-archive (NULL = actif) |
| `compact_origin_ids` | TEXT[] NULL | IDs sources du summary |
| `is_compacted_summary` | BOOLEAN NOT NULL DEFAULT false | Flag summary Compactor |

Index partiel `idx_memory_facts_active_subject (subject, created_at DESC) WHERE
compacted_at IS NULL AND is_compacted_summary IS NOT TRUE`.

## Phases à venir

- **PR 5** — OutcomeDetector : lie les outcomes aux facts (pinning)
- **PR 6** — Maintenance scheduler (cron) : decay + dedupe automatique
- **PR 7** — Pinning : boost confidence des facts corrélés à des outcomes positifs
