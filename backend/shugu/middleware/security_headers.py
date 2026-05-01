"""Security headers middleware — Helmet-style defense in depth.

Audit Pass 2 P1.D : sans middleware de security headers, les réponses HTTP
de l'API n'ont AUCUN header défensif (CSP, X-Frame-Options, X-Content-Type-
Options, Referrer-Policy, Permissions-Policy). Cf. recommandation hook
``awesome-secure-defaults`` qui pointe Helmet (Node) / secure_headers (Ruby)
comme gold standard — l'équivalent Python pragmatique est un middleware
minimaliste qui pose ces 5+ headers.

Ce qu'on défend
---------------
- **CSP** (Content-Security-Policy) : limite les sources scripts/connexions
  pour mitiger un XSS résiduel (le frontend Next.js a un CSP propre, mais
  pour l'API on garde un défaut strict — les seules réponses HTML du backend
  sont les templates emails déjà gardés par le validator
  `public_site_url`).
- **X-Frame-Options: DENY** : anti-clickjacking. Le backend ne devrait
  jamais être iframé (le viewer 3D est servi par Next.js séparément).
- **X-Content-Type-Options: nosniff** : empêche les browsers de deviner
  le content-type → contre des attaques où un upload est interprété
  comme HTML/JS.
- **Referrer-Policy: strict-origin-when-cross-origin** : limite la fuite
  d'URL avec query strings (potentiellement contiennent des tokens).
- **Permissions-Policy** : désactive les APIs browser sensibles
  (geolocation, camera, microphone, USB, etc.) que l'API n'a pas
  besoin d'autoriser.
- **Strict-Transport-Security** (HSTS) : en prod uniquement, force HTTPS
  pour 1 an + subdomains. Skippé en dev/test.

Headers volontairement NON ajoutés
-----------------------------------
- `X-XSS-Protection` : déprécié et contre-productif sur browsers modernes.
- `X-Powered-By` : on ne pose pas → on ne révèle pas la stack.
- `Cross-Origin-Opener-Policy` / `COEP` : trop strict pour l'agent VIP
  LiveKit qui partage des origins. À ajouter en P2 si nécessaire.

Usage
-----
    from shugu.middleware import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger(__name__)

# CSP par défaut — strict mais compatible avec les réponses templates emails.
# Le frontend Next.js a son propre CSP via next.config.js / metadata, plus
# permissif. Pour les routes API JSON, ce CSP n'est de toute façon pas
# enforcé par le browser (pas de contexte HTML).
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "  # emails Jinja autorisent inline styles
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' https: wss:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

_PROD_ENVS = frozenset({"production", "prod"})


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Pose les security headers sur toutes les réponses.

    Le middleware n'altère pas les réponses existantes (n'écrase pas un
    header déjà set par un endpoint qui aurait des besoins spécifiques).
    """

    def __init__(
        self,
        app,
        *,
        env: str = "production",
        csp: str | None = None,
    ):
        super().__init__(app)
        self._env = env
        self._csp = csp or _DEFAULT_CSP
        self._is_prod = env in _PROD_ENVS

    def _apply_headers(self, response: Response) -> None:
        """Pose les headers défensifs (idempotent via setdefault)."""
        response.headers.setdefault("Content-Security-Policy", self._csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), camera=(), microphone=(), usb=(), payment=(), "
            "interest-cohort=()",
        )
        # HSTS uniquement en prod (le browser cache la directive 1 an —
        # poser ça en dev empoisonnerait localhost).
        if self._is_prod:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Audit Pass 2 review : si une exception remonte hors d'une route,
        # l'outer error middleware Starlette générerait un 500 brut SANS nos
        # headers défensifs (le call_next aurait raise avant qu'on touche la
        # response). On wrap donc l'appel et on construit explicitement une
        # 500 avec headers en cas d'exception non gérée.
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 — on doit attraper toute exc
            log.exception(
                "security_headers.unhandled_exception",
                extra={"path": str(request.url.path), "error": str(exc)},
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal server error"},
            )

        self._apply_headers(response)
        return response


__all__ = ["SecurityHeadersMiddleware"]
