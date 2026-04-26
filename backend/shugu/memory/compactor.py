"""Compactor — résumé LLM des facts mémoire par sujet — Mémoire PR 4.

## Rôle

Quand un sujet accumule plus de `threshold` facts actifs dans `memory_facts`,
le Compactor :

1. Sélectionne tous les facts actifs non-summary du sujet.
2. Soumet la liste au LLM (`DirectorBrain` — MiniMax default, Anthropic fallback)
   pour obtenir un résumé condensé en N facts.
3. Crée les nouveaux facts résumés via `MemoryAgent.commit_compaction()`.
4. Archive les facts sources atomiquement (soft-archive — jamais supprimés,
   conservés pour audit et rollback éventuel).

## Design

- **Single-writer rule** : ZERO INSERT/UPDATE/DELETE direct sur `memory_facts`.
  Tout passe par `MemoryAgent`.
- **Multi-provider** : utilise `DirectorBrain` protocol (MiniMax default via
  `brain_provider.py` E2.5). Testable en mockant l'interface.
- **Idempotence** : un 2e run sur le même sujet skip si le count actif passe
  sous threshold (les sources ont déjà `compacted_at` set).
- **Robustesse** : si le LLM échoue ou retourne du non-JSON, `CompactionResult`
  porte l'erreur — pas de side-effect partiel.
- **Atomicité** : Mémoire PR 4 — commit_compaction() garantit que ou TOUT
  persiste (summaries + sources archivées), ou RIEN.

## Prompt LLM

Format strict JSON demandé :
    {"summary_facts": [{"predicate": "...", "object": "...", "confidence": 0.x}, ...]}

Un parse robuste avec fallback log + skip en cas de réponse invalide.
Voir `compactor_parsing.py` pour les détails.

## Configuration

Mémoire PR 4 — Seuils configurables via env (shugu.config.Settings) :
- `SHUGU_COMPACTOR_THRESHOLD` (défaut 20) : nombre minimum de facts actifs
  pour déclencher le compactage.
- `SHUGU_COMPACTOR_SUMMARY_COUNT` (défaut 6) : nombre cible de facts résumés.

## Usage

    from shugu.config import get_settings
    from shugu.memory import MemoryCompactor

    settings = get_settings()
    brain = make_director_brain(settings, http_client)
    compactor = MemoryCompactor(
        memory_agent=agent,
        brain=brain,
        threshold=settings.compactor_threshold,
        target_summary_count=settings.compactor_summary_count,
    )

    # Compacter un sujet spécifique
    result = await compactor.compact_subject("viewer:alice")

    # Pipeline complet : tous les sujets éligibles
    results = await compactor.compact_all_eligible()
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog
from ulid import ULID

from .agent import MemoryAgent
from .compactor_parsing import (
    ParseError,
    build_system_prompt,
    build_user_prompt,
    parse_summary_response,
)
from .types import MemoryItem

# Limite le nombre de facts par sujet dans un seul prompt LLM
# pour éviter de dépasser la fenêtre de contexte (chaque fact ~ 50-80 tokens).
_MAX_FACTS_PER_PROMPT = 100

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class CompactionResult:
    """Résultat d'un run de compactage pour un subject_key.

    Attributes:
        subject_key:    Sujet compacté (ex: `viewer:alice`).
        source_count:   Nombre de facts sources archivés.
        summary_count:  Nombre de facts résumés créés.
        skipped:        True si le sujet a été ignoré (threshold non atteint
                        ou déjà compacté depuis le dernier check).
        error:          Message d'erreur si le compactage a échoué
                        (LLM error, parse error, etc.). None = succès.
    """

    subject_key: str
    source_count: int = 0
    summary_count: int = 0
    skipped: bool = False
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """True si le compactage s'est terminé sans erreur."""
        return self.error is None and not self.skipped


class MemoryCompactor:
    """Compactor déterministe pour memory_facts.

    Trigger : >threshold facts actifs sur un subject_key.
    Action : LLM summary → nouveaux facts compactés + soft-archive sources.

    Voir docstring du module pour le design complet.
    """

    def __init__(
        self,
        *,
        memory_agent: MemoryAgent,
        brain: object,  # DirectorBrain protocol — évite import circulaire
        threshold: int = 20,
        target_summary_count: int = 6,
    ) -> None:
        """Initialise le Compactor.

        Args:
            memory_agent:         Agent mémoire (single-writer).
            brain:                Brain LLM (DirectorBrain protocol).
                                  MiniMax default via brain_provider.py.
            threshold:            Nombre de facts actifs déclenchant le
                                  compactage (défaut 20).
            target_summary_count: Nombre de facts résumés cibles après
                                  compactage (défaut 6).
        """
        if threshold <= 0:
            raise ValueError(f"threshold doit être > 0, reçu {threshold}")
        if target_summary_count <= 0:
            raise ValueError(
                f"target_summary_count doit être > 0, reçu {target_summary_count}"
            )

        self._agent = memory_agent
        self._brain = brain
        self._threshold = threshold
        self._target = target_summary_count

    # ── API publique ──────────────────────────────────────────────────────────

    async def compact_subject(self, subject_key: str) -> CompactionResult:
        """Lance le compactage pour un subject_key donné.

        Pipeline :
        1. Récupère les facts actifs non-summary du sujet.
        2. Vérifie le threshold — skip si count <= threshold.
        3. Appelle le LLM pour obtenir le résumé condensé.
        4. Parse le JSON de sortie — erreur si non-JSON.
        5. Crée les summary facts via MemoryAgent.store_compacted_summary().
        6. Archive les sources via MemoryAgent.mark_facts_compacted().

        Args:
            subject_key: Identifiant du sujet (ex: `viewer:alice`, `vip:bob`).

        Returns:
            CompactionResult avec source_count, summary_count, error si applicable.
        """
        if not subject_key or not subject_key.strip():
            return CompactionResult(
                subject_key=subject_key,
                skipped=True,
                error="subject_key vide",
            )

        # 1) Récupère les facts actifs.
        active_facts = await self._agent.list_active_facts(subject_key)

        # 2) Threshold check — idempotence naturelle.
        if len(active_facts) <= self._threshold:
            log.debug(
                "compactor.skip_below_threshold",
                subject=subject_key,
                count=len(active_facts),
                threshold=self._threshold,
            )
            return CompactionResult(subject_key=subject_key, skipped=True)

        # Tronque si trop de facts pour un seul prompt (protection fenêtre).
        facts_to_compact = active_facts[:_MAX_FACTS_PER_PROMPT]

        # 3) Appel LLM.
        try:
            raw_response = await self._call_brain(subject_key, facts_to_compact)
        except Exception as exc:
            log.error(
                "compactor.brain_error",
                subject=subject_key,
                error=repr(exc),
            )
            return CompactionResult(
                subject_key=subject_key,
                source_count=len(facts_to_compact),
                error=f"LLM error: {exc}",
            )

        # 4) Parse JSON.
        try:
            summary_specs = parse_summary_response(raw_response)
        except ParseError as exc:
            log.error(
                "compactor.parse_error",
                subject=subject_key,
                raw_head=raw_response[:200],
                error=str(exc),
            )
            return CompactionResult(
                subject_key=subject_key,
                source_count=len(facts_to_compact),
                error=f"Parse error: {exc}",
            )

        if not summary_specs:
            log.warning(
                "compactor.empty_summary",
                subject=subject_key,
                source_count=len(facts_to_compact),
            )
            return CompactionResult(
                subject_key=subject_key,
                source_count=len(facts_to_compact),
                error="LLM a retourné 0 facts résumés",
            )

        # 5+6) Crée les summaries ET archive les sources en UNE SEULE transaction.
        # Mémoire PR 4 — CRITICAL Atomicité : commit_compaction() garantit que
        # soit TOUT persiste (summaries + sources archivées), soit RIEN.
        source_ids = [f.id for f in facts_to_compact]
        now = datetime.now(timezone.utc)

        # Construit les summaries à partir des specs.
        summaries = []
        for spec in summary_specs:
            summary_item = MemoryItem(
                id=str(ULID()),
                kind="fact",
                subject=subject_key,
                text=f"{spec['predicate']}: {spec['object']}",
                confidence=float(spec.get("confidence", 0.75)),
                source="compaction_llm",
                created_at=now,
            )
            summaries.append(summary_item)

        if not summaries:
            return CompactionResult(
                subject_key=subject_key,
                source_count=len(facts_to_compact),
                error="Aucun summary fact à créer",
            )

        # Appel atomique unique.
        try:
            archived_count = await self._agent.commit_compaction(
                summaries=summaries,
                source_ids=source_ids,
            )
        except Exception as exc:
            log.error(
                "compactor.commit_compaction_error",
                subject=subject_key,
                source_count=len(source_ids),
                summary_count=len(summaries),
                error=repr(exc),
            )
            return CompactionResult(
                subject_key=subject_key,
                source_count=len(facts_to_compact),
                error=f"Compaction atomique échouée (0 persistence garantie): {exc}",
            )

        log.info(
            "compactor.compacted",
            subject=subject_key,
            source_count=archived_count,
            summary_count=len(summaries),
        )
        return CompactionResult(
            subject_key=subject_key,
            source_count=archived_count,
            summary_count=len(summaries),
        )

    async def list_subjects_above_threshold(self) -> list[str]:
        """Query subjects ayant > threshold facts actifs.

        Délègue à MemoryAgent pour respecter la single-writer rule (query DB).

        Returns:
            Liste de subject_key éligibles, ordre alphabétique.
        """
        return await self._agent.list_subjects_above_threshold(self._threshold)

    async def compact_all_eligible(self) -> list[CompactionResult]:
        """Pipeline complet : liste les sujets éligibles → compacte chacun.

        Traitement séquentiel (pas de parallélisme) — le Compactor est un
        job de maintenance, pas un chemin temps-réel. Les erreurs sur un sujet
        n'interrompent pas les suivants.

        Returns:
            Liste de CompactionResult (un par sujet éligible).
            Liste vide si aucun sujet n'est au-dessus du threshold.
        """
        subjects = await self.list_subjects_above_threshold()

        if not subjects:
            log.debug("compactor.no_eligible_subjects", threshold=self._threshold)
            return []

        log.info(
            "compactor.starting_batch",
            eligible_count=len(subjects),
            threshold=self._threshold,
        )

        results: list[CompactionResult] = []
        for subject_key in subjects:
            result = await self.compact_subject(subject_key)
            results.append(result)
            if result.error:
                log.warning(
                    "compactor.subject_error",
                    subject=subject_key,
                    error=result.error,
                )

        successes = sum(1 for r in results if r.success)
        log.info(
            "compactor.batch_done",
            total=len(results),
            successes=successes,
            errors=len(results) - successes,
        )
        return results

    # ── privé ─────────────────────────────────────────────────────────────────

    async def _call_brain(
        self,
        subject_key: str,
        facts: list[MemoryItem],
    ) -> str:
        """Formate le prompt et appelle le LLM.

        Retourne la réponse brute (string) du LLM.
        Lève une exception si le LLM échoue (propagée vers compact_subject).
        Voir compactor_parsing.py pour build_system_prompt / build_user_prompt.
        """
        system_prompt = build_system_prompt(self._target)
        user_prompt = build_user_prompt(subject_key, facts)
        return await self._brain.complete(system=system_prompt, user=user_prompt)


__all__ = ["CompactionResult", "MemoryCompactor"]
