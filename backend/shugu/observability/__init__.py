"""Package observability — Phase 8.2.

Fournit :
- ``MetricsRecorder`` : Protocol commun pour l'enregistrement de métriques.
- ``NullMetricsRecorder`` : implémentation no-op (backward-compat, défaut).
- ``PrometheusMetricsRecorder`` : implémentation Prometheus réelle.
- ``configure_logging`` : configure structlog en mode JSON ou pretty.
"""
from .log_config import configure_logging
from .metrics import MetricsRecorder, NullMetricsRecorder, PrometheusMetricsRecorder

__all__ = [
    "MetricsRecorder",
    "NullMetricsRecorder",
    "PrometheusMetricsRecorder",
    "configure_logging",
]
