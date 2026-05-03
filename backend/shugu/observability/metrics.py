"""Métriques Prometheus — Phase 8.2 observabilité.

Fournit un Protocol ``MetricsRecorder`` avec deux implémentations :

- ``NullMetricsRecorder`` : no-op, utilisé par défaut pour backward-compat.
  Aucun import prometheus_client requis quand metrics_enabled=False.
- ``PrometheusMetricsRecorder`` : compteurs réels, registre isolé par instance
  (évite les leaks entre tests et entre workers indépendants).

Pattern Null Object
-------------------
Tous les layers qui reçoivent un MetricsRecorder appellent ses méthodes sans
garde ``if recorder is not None``. NullMetricsRecorder absorbe silencieusement
tous les appels. Identique au pattern NullSender dans adapters/smtp_resend.py.

Isolation registre
------------------
``PrometheusMetricsRecorder`` accepte un ``CollectorRegistry`` en paramètre
(injection). Chaque instance de test injecte ``CollectorRegistry()`` frais →
aucune fuite de compteurs entre tests. En production, app.py injecte un seul
registre global partagé (ou None → registry par défaut prometheus_client).

Compteurs exposés
-----------------
- ``agent_runner_ticks_total``                 (Counter, sans label)
- ``agent_runner_actions_applied_total``        (Counter, label=action_kind)
- ``agent_runner_tools_dispatched_total``       (Counter, label=tool_name)
- ``agent_runner_policy_denials_total``         (Counter, labels=mode,capability)
- ``world_delta_published_total``               (Counter, sans label)
- ``sense_events_received_total``               (Counter, label=kind)
- ``tts_fallback_total``                        (Counter, labels=from,to) — Sprint 4 P1.C1
- ``event_bus_drop_total``                      (Counter, label=topic) — Sprint 4 P1.C4
- ``memory_recall_failed_total``                (Counter, label=error_kind) — Sprint 4 P1.C6
- ``moderation_ban_check_failed_total``         (Counter, label=error_kind) — Sprint 5 P1.B7
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from prometheus_client import (
    CollectorRegistry,
    Counter,
    generate_latest,
)

# ---------------------------------------------------------------------------
# Protocol — contrat commun (structural typing, pas d'héritage requis)
# ---------------------------------------------------------------------------


@runtime_checkable
class MetricsRecorder(Protocol):
    """Contrat minimal pour l'enregistrement de métriques runtime.

    Toutes les méthodes sont synchrones (compteurs in-memory, thread-safe).
    Aucun layer ne dépend de l'implémentation concrète — seul ce Protocol
    est importé depuis L1/L2/L3.
    """

    def record_tick(self) -> None:
        """Incrémente agent_runner_ticks_total."""
        ...

    def record_action(self, kind: str) -> None:
        """Incrémente agent_runner_actions_applied_total{action_kind=kind}."""
        ...

    def record_tool(self, name: str) -> None:
        """Incrémente agent_runner_tools_dispatched_total{tool_name=name}."""
        ...

    def record_policy_deny(self, mode: str, capability: str) -> None:
        """Incrémente agent_runner_policy_denials_total{mode,capability}."""
        ...

    def record_world_delta(self) -> None:
        """Incrémente world_delta_published_total."""
        ...

    def record_sense_event(self, kind: str) -> None:
        """Incrémente sense_events_received_total{kind=kind}."""
        ...

    def record_tts_fallback(self, from_provider: str, to_provider: str) -> None:
        """Incrémente tts_fallback_total{from,to} — Sprint 4 P1.C1.

        Posé quand le primary TTS (ex: ElevenLabs) crash et le secondary
        (Edge-TTS) prend le relais. Permet d'alerter si la primary claque
        souvent.
        """
        ...

    def record_event_bus_drop(self, topic: str) -> None:
        """Incrémente event_bus_drop_total{topic} — Sprint 4 P1.C4.

        Posé sur drop-oldest dans InProcessEventBus.publish quand un
        subscriber est lent (queue saturée). Permet de détecter les slow
        consumers en prod.
        """
        ...

    def record_memory_recall_failed(self, error_kind: str) -> None:
        """Incrémente memory_recall_failed_total{error_kind} — Sprint 4 P1.C6.

        Posé quand director/orchestrator.recall() crash. Sans cette métrique,
        un memory agent en panne (deadlock pgvector, embedder OOM) reste
        invisible — le director continue avec mémoire vide, qualité dégradée
        silencieusement.
        """
        ...

    def record_moderation_ban_check_failed(self, error_kind: str) -> None:
        """Incrémente moderation_ban_check_failed_total{error_kind} — Sprint 5 P1.B7.

        Posé quand le ban check Postgres crash dans BasicModeration.
        Politique fail-open : on accepte le visiteur (service > sécu) MAIS on
        veut visibilité sur ces incidents (Postgres down = bans plus enforced).
        Sans métrique, un trou de moderation reste invisible côté admin.
        """
        ...


# ---------------------------------------------------------------------------
# NullMetricsRecorder — no-op, backward-compat par défaut
# ---------------------------------------------------------------------------


class NullMetricsRecorder:
    """Implémentation no-op du MetricsRecorder.

    Utilisé quand metrics_enabled=False (défaut). Toutes les méthodes sont
    des no-ops — aucune dépendance sur prometheus_client à l'exécution.
    Satisfait le Protocol MetricsRecorder par structural typing.
    """

    def record_tick(self) -> None:
        pass

    def record_action(self, kind: str) -> None:
        pass

    def record_tool(self, name: str) -> None:
        pass

    def record_policy_deny(self, mode: str, capability: str) -> None:
        pass

    def record_world_delta(self) -> None:
        pass

    def record_sense_event(self, kind: str) -> None:
        pass

    def record_tts_fallback(self, from_provider: str, to_provider: str) -> None:
        pass

    def record_event_bus_drop(self, topic: str) -> None:
        pass

    def record_memory_recall_failed(self, error_kind: str) -> None:
        pass

    def record_moderation_ban_check_failed(self, error_kind: str) -> None:
        pass


# Singleton global — injecté dans les layers quand metrics_enabled=False.
# Évite d'allouer un objet par call site.
_NULL_RECORDER = NullMetricsRecorder()


def get_null_recorder() -> NullMetricsRecorder:
    """Retourne le singleton NullMetricsRecorder global."""
    return _NULL_RECORDER


# ---------------------------------------------------------------------------
# PrometheusMetricsRecorder — implémentation Prometheus réelle
# ---------------------------------------------------------------------------


class PrometheusMetricsRecorder:
    """Implémentation Prometheus du MetricsRecorder.

    Chaque instance possède son propre ``CollectorRegistry`` (injection via
    paramètre). Cela garantit l'isolation entre tests et entre instances
    indépendantes (ex: workers multi-process futurs).

    Paramètres
    ----------
    registry :
        Registre Prometheus à utiliser. Si None, crée un ``CollectorRegistry()``
        frais (isolation garantie). En production, passer le registre partagé.

    Exemple d'usage
    ---------------
    >>> from prometheus_client import CollectorRegistry
    >>> rec = PrometheusMetricsRecorder(registry=CollectorRegistry())
    >>> rec.record_tick()
    >>> print(rec.generate_latest().decode())
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()

        self._ticks = Counter(
            "agent_runner_ticks_total",
            "Nombre total de ticks de la boucle AgentRunner.",
            registry=self.registry,
        )
        self._actions = Counter(
            "agent_runner_actions_applied_total",
            "Nombre d'actions L3 appliquées sur le WorldStateStore.",
            ["action_kind"],
            registry=self.registry,
        )
        self._tools = Counter(
            "agent_runner_tools_dispatched_total",
            "Nombre de ToolCalls dispatchés par le runner.",
            ["tool_name"],
            registry=self.registry,
        )
        self._denials = Counter(
            "agent_runner_policy_denials_total",
            "Nombre de refus policy (mode × capability).",
            ["mode", "capability"],
            registry=self.registry,
        )
        self._world_deltas = Counter(
            "world_delta_published_total",
            "Nombre de world.delta publiés par WorldStateStore.",
            registry=self.registry,
        )
        self._sense_events = Counter(
            "sense_events_received_total",
            "Nombre de SenseEvents reçus sur le bus, par kind.",
            ["kind"],
            registry=self.registry,
        )
        # Sprint 4 P1.C1/C4/C2/C6 — observabilité fallbacks Cat C.
        self._tts_fallback = Counter(
            "tts_fallback_total",
            "Nombre de bascules TTS primary → secondary (audit C1).",
            ["from_provider", "to_provider"],
            registry=self.registry,
        )
        self._event_bus_drop = Counter(
            "event_bus_drop_total",
            "Nombre d'events droppés par drop-oldest sur queue pleine (audit C4).",
            ["topic"],
            registry=self.registry,
        )
        self._memory_recall_failed = Counter(
            "memory_recall_failed_total",
            "Nombre d'échecs MemoryAgent.recall (deadlock pgvector, OOM, etc.) (audit C6).",
            ["error_kind"],
            registry=self.registry,
        )
        # Sprint 5 P1.B7 — observabilité fail-open de BasicModeration ban check.
        self._moderation_ban_check_failed = Counter(
            "moderation_ban_check_failed_total",
            "Nombre d'échecs ban check Postgres (politique fail-open) (audit B7).",
            ["error_kind"],
            registry=self.registry,
        )

    def record_tick(self) -> None:
        """Incrémente agent_runner_ticks_total."""
        self._ticks.inc()

    def record_action(self, kind: str) -> None:
        """Incrémente agent_runner_actions_applied_total{action_kind=kind}."""
        self._actions.labels(action_kind=kind).inc()

    def record_tool(self, name: str) -> None:
        """Incrémente agent_runner_tools_dispatched_total{tool_name=name}."""
        self._tools.labels(tool_name=name).inc()

    def record_policy_deny(self, mode: str, capability: str) -> None:
        """Incrémente agent_runner_policy_denials_total{mode,capability}."""
        self._denials.labels(mode=mode, capability=capability).inc()

    def record_world_delta(self) -> None:
        """Incrémente world_delta_published_total."""
        self._world_deltas.inc()

    def record_sense_event(self, kind: str) -> None:
        """Incrémente sense_events_received_total{kind=kind}."""
        self._sense_events.labels(kind=kind).inc()

    def record_tts_fallback(self, from_provider: str, to_provider: str) -> None:
        """Incrémente tts_fallback_total{from,to}."""
        self._tts_fallback.labels(
            from_provider=from_provider, to_provider=to_provider,
        ).inc()

    def record_event_bus_drop(self, topic: str) -> None:
        """Incrémente event_bus_drop_total{topic}."""
        self._event_bus_drop.labels(topic=topic).inc()

    def record_memory_recall_failed(self, error_kind: str) -> None:
        """Incrémente memory_recall_failed_total{error_kind}."""
        self._memory_recall_failed.labels(error_kind=error_kind).inc()

    def record_moderation_ban_check_failed(self, error_kind: str) -> None:
        """Incrémente moderation_ban_check_failed_total{error_kind}."""
        self._moderation_ban_check_failed.labels(error_kind=error_kind).inc()

    def generate_latest(self) -> bytes:
        """Sérialise les métriques au format texte Prometheus 0.0.4 (bytes).

        Utilisé par l'endpoint GET /metrics pour exposer les métriques
        à Prometheus/Grafana.
        """
        return generate_latest(self.registry)


__all__ = [
    "MetricsRecorder",
    "NullMetricsRecorder",
    "PrometheusMetricsRecorder",
    "get_null_recorder",
]
