"""EmailSender — abstraction mince sur Resend HTTP API.

Pourquoi pas SMTP direct ? Resend déconseille SMTP (rate limits plus sévères,
pas de tracking, pas de retries managed). L'API HTTP est idiomatique, Web3-clean,
et même leur SDK officiel Python n'ajoute rien de significatif par-dessus une
simple requête `POST /emails` avec httpx. Donc on l'évite = moins de surface.

Deux implémentations :
  - `ResendSender` → envoie vraiment via api.resend.com.
  - `NullSender`   → ne fait rien (log console). Utile en dev local sans
    domaine vérifié, ou quand on veut tester le flow sans polluer une inbox.

Le choix se fait dans `app.py` lifespan selon `settings.resend_api_key` :
  clé vide → NullSender, sinon ResendSender.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import httpx
import jinja2
import structlog

log = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "email_templates"


def _build_jinja_env() -> jinja2.Environment:
    # Sécurité XSS : `autoescape` actif pour les .html/.htm/.xml — équivaut à
    # render_template() de Flask. Toute variable injectée (username, email)
    # est HTML-escapée par défaut. Ne pas passer `|safe` sur une donnée
    # user-controlled. Les URLs (`verify_url`, `site_url`) sont construites
    # côté serveur depuis `public_site_url` + JWT ; pas d'input user dedans.
    # nosemgrep: python.flask.security.xss.audit.direct-use-of-jinja2.direct-use-of-jinja2
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(["html", "htm", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


class EmailSender(ABC):
    """Protocole minimal pour envoyer un email transactionnel."""

    @abstractmethod
    async def send(
        self,
        *,
        to: str,
        subject: str,
        template: str,
        context: dict,
    ) -> None: ...


class NullSender(EmailSender):
    """Dev-only : log l'email au lieu d'envoyer. Aucun crédit consommé."""

    def __init__(self) -> None:
        self._env = _build_jinja_env()

    async def send(self, *, to: str, subject: str, template: str, context: dict) -> None:
        try:
            html = self._env.get_template(f"{template}.html").render(**context)
        except jinja2.TemplateNotFound:
            html = f"[NullSender] template '{template}' introuvable — context={context!r}"
        log.warning(
            "email.null_send",
            to=to,
            subject=subject,
            template=template,
            html_len=len(html),
            context_keys=sorted(context.keys()),
        )


class ResendSender(EmailSender):
    """Envoie via Resend HTTP API. Nécessite clé + domaine vérifié."""

    API_URL = "https://api.resend.com/emails"

    def __init__(
        self,
        *,
        api_key: str,
        from_addr: str,
        http: httpx.AsyncClient,
    ) -> None:
        if not api_key:
            raise ValueError("ResendSender requires a non-empty api_key")
        if "@" not in from_addr:
            raise ValueError(f"from_addr not a valid email: {from_addr!r}")
        self._api_key = api_key
        self._from_addr = from_addr
        self._http = http
        self._env = _build_jinja_env()

    async def send(self, *, to: str, subject: str, template: str, context: dict) -> None:
        html = self._env.get_template(f"{template}.html").render(**context)
        body = {
            "from": f"Shugu <{self._from_addr}>",
            "to": [to],
            "subject": subject,
            "html": html,
        }
        resp = await self._http.post(
            self.API_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30.0,
        )
        if resp.status_code >= 400:
            # Ne pas leak la clé API dans les logs : juste le code + body.
            log.error(
                "email.resend_failed",
                to=to,
                template=template,
                status=resp.status_code,
                body=resp.text[:500],
            )
            resp.raise_for_status()
        payload = resp.json()
        log.info(
            "email.sent",
            to=to,
            template=template,
            message_id=payload.get("id"),
        )
