"""Secret redaction — Phase 2.6.

Bank de regex appliquee au texte avant `MemoryAgent.store()` pour eviter
qu'un secret (API key, token, SSH key, email perso) n'atterrisse dans la
memoire long-terme (pgvector) ou dans les logs. Inspire de
detect-secrets / gitleaks / trufflehog.

Signature publique :

    from shugu.memory.redaction import redact

    clean_text, categories = redact("my key is sk-ant-api03-...")
    # clean_text  -> "my key is [REDACTED:ANTHROPIC_API_KEY]"
    # categories  -> ["ANTHROPIC_API_KEY"]

`MemoryAgent.store()` appelle `redact()` sur `item.text` avant embedding +
INSERT. Si `categories` est non vide, on log un WARNING sans jamais logger
le secret lui-meme.

Ordre d'evaluation : **most-specific first**. PEM -> AWS ID -> Stripe ->
Anthropic (avant OpenAI car `sk-ant-*` est un prefixe de `sk-*`) -> OpenAI
-> GitHub -> Google -> Slack -> JWT -> AWS secret (context-gated) ->
generic assignment -> email -> credit card (Luhn-checked) -> phone.

Performance : tous les patterns sont pre-compiles au module load.
Une iteration `re.sub` par pattern, sur text < 10 KB typiquement
-> sub-milliseconde. Pas de catastrophic backtracking (quantifiers bornes
ou suivis d'ancres litterales).

Flags :
  - `redact_emails=True`  (default) : un viewer qui colle son email perso
    ne doit pas le voir atterrir en memoire. Opt-out pour les contextes
    streamer-promo (biz@channel.com legitime).
  - `redact_phones=False` (default) : high-FP sur ID/timestamps/versions.
    Opt-in si on a un cas concret.
  - `redact_credit_cards=True` (default) : regex + Luhn check cote Python
    pour rejeter les faux positifs (order numbers, hashes longs).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Pattern:
    """Un pattern de redaction unitaire.

    `post_filter` est une validation optionnelle cote Python (p.ex. Luhn
    check pour les CC). Si fournie et retourne False sur le match, on
    **ne redige pas** — evite les faux positifs.
    """
    name: str           # UPPER_SNAKE_CASE, devient le tag [REDACTED:NAME]
    regex: re.Pattern[str]
    post_filter: Optional[Callable[[str], bool]] = None


# ---------------------------------------------------------------------------
# Post-filters
# ---------------------------------------------------------------------------

def _luhn_valid(digits_with_sep: str) -> bool:
    """Luhn check (mod 10) apres avoir strip les separateurs."""
    digits = [int(c) for c in digits_with_sep if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    # Double every second digit from the right.
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------------------------------------------------------------------------
# Pattern bank
#
# Ordre : most-specific first. First-match-wins a un offset donne.
# Apres une redaction, le remplacement `[REDACTED:*]` n'est plus matchable
# par les patterns suivants (safe).
# ---------------------------------------------------------------------------

# Multi-line : PEM + OpenSSH. DOTALL pour matcher les newlines.
_PEM_PRIVATE_KEY = _Pattern(
    name="PRIVATE_KEY",
    regex=re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |ENCRYPTED |PGP )?PRIVATE KEY-----"
        r"[\s\S]{10,8192}?"
        r"-----END (?:RSA |EC |DSA |ENCRYPTED |PGP )?PRIVATE KEY-----",
        re.DOTALL,
    ),
)

_OPENSSH_PRIVATE_KEY = _Pattern(
    name="OPENSSH_PRIVATE_KEY",
    regex=re.compile(
        r"-----BEGIN OPENSSH PRIVATE KEY-----"
        r"[\s\S]{10,8192}?"
        r"-----END OPENSSH PRIVATE KEY-----",
        re.DOTALL,
    ),
)

_SSH_PUBLIC_KEY = _Pattern(
    name="SSH_PUBLIC_KEY",
    # ssh-rsa/ssh-ed25519/ssh-dss/ecdsa-sha2-nistp256/384/521 + base64 >=20 + optional comment.
    regex=re.compile(
        r"\b(?:ssh-rsa|ssh-ed25519|ssh-dss|ecdsa-sha2-nistp(?:256|384|521))"
        r"\s+AAAA[0-9A-Za-z+/=]{20,}(?:\s+\S+)?"
    ),
)

_AWS_ACCESS_KEY_ID = _Pattern(
    name="AWS_ACCESS_KEY",
    regex=re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|AIPA|ANPA|ANVA|ABIA|ACCA)[0-9A-Z]{16}\b"),
)

_STRIPE_KEY = _Pattern(
    name="STRIPE_KEY",
    regex=re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[0-9A-Za-z]{24,99}\b"),
)

# Anthropic BEFORE OpenAI (prefix `sk-ant-*` overlap avec `sk-*`).
_ANTHROPIC_API_KEY = _Pattern(
    name="ANTHROPIC_API_KEY",
    regex=re.compile(r"\bsk-ant-(?:api\d{2}|admin\d{2})-[A-Za-z0-9_\-]{80,}\b"),
)

_OPENAI_API_KEY = _Pattern(
    name="OPENAI_API_KEY",
    # Accepts variants: sk-proj-*, sk-svcacct-*, sk-admin-*, bare sk-*.
    # Min 32 chars de suffix pour eviter les false positives type "sk-12".
    regex=re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{32,}\b"),
)

_GITHUB_TOKEN = _Pattern(
    name="GITHUB_TOKEN",
    regex=re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})\b"),
)

_GOOGLE_API_KEY = _Pattern(
    name="GOOGLE_API_KEY",
    regex=re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
)

_SLACK_TOKEN = _Pattern(
    name="SLACK_TOKEN",
    regex=re.compile(r"\bxox[abpors]-(?:\d+-)+[A-Za-z0-9]{24,}\b"),
)

_JWT = _Pattern(
    name="JWT",
    # Trois segments base64url separes par `.`, le premier debute par
    # eyJ (base64 de `{"` du JSON header).
    regex=re.compile(
        r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
    ),
)

# Context-gated : requires the word "aws" within 20 chars before the secret.
_AWS_SECRET_ACCESS_KEY = _Pattern(
    name="AWS_SECRET_KEY",
    regex=re.compile(
        r"(?i)aws(?:.{0,20})?(?:secret|access)?(?:.{0,20})?[:=]\s*['\"]?"
        r"([A-Za-z0-9/+=]{40})['\"]?"
    ),
)

# Generic "api_key: <value>" / "token=<value>" / "password=<value>".
_GENERIC_SECRET = _Pattern(
    name="GENERIC_SECRET",
    regex=re.compile(
        r"(?i)(?:api[_\-]?key|secret|token|passwd|password|bearer)\s*[:=]\s*"
        r"['\"]?([A-Za-z0-9+/=_\-]{20,})['\"]?"
    ),
)

_EMAIL = _Pattern(
    name="EMAIL",
    # Local-part + @ + domain + TLD (2-24 chars). Laisse les handles sociaux
    # (@alice sans .tld) tranquilles.
    regex=re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}\b"),
)

# Credit card : regex permissive + Luhn check en post-filter.
_CREDIT_CARD = _Pattern(
    name="CREDIT_CARD",
    # Optionnel : 13-19 digits separes par `.`, `-`, ou espaces. Guard avant
    # / apres pour eviter de couper dans un run plus long.
    regex=re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)"),
    post_filter=_luhn_valid,
)

# E.164 + national formats. Exclusivement opt-in (high FP).
_PHONE = _Pattern(
    name="PHONE",
    regex=re.compile(
        r"(?<!\d)"
        r"(?:\+?\d{1,3}[ .\-]?)?"
        r"(?:\(\d{2,4}\)[ .\-]?)?"
        r"\d{2,4}[ .\-]?\d{2,4}[ .\-]?\d{2,4}(?:[ .\-]?\d{2,4})?"
        r"(?!\d)"
    ),
)

# Patterns toujours actifs (core security).
_CORE_PATTERNS: tuple[_Pattern, ...] = (
    _PEM_PRIVATE_KEY,
    _OPENSSH_PRIVATE_KEY,
    _SSH_PUBLIC_KEY,
    _AWS_ACCESS_KEY_ID,
    _STRIPE_KEY,
    _ANTHROPIC_API_KEY,
    _OPENAI_API_KEY,
    _GITHUB_TOKEN,
    _GOOGLE_API_KEY,
    _SLACK_TOKEN,
    _JWT,
    _AWS_SECRET_ACCESS_KEY,
    _GENERIC_SECRET,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def redact(
    text: str,
    *,
    redact_emails: bool = True,
    redact_phones: bool = False,
    redact_credit_cards: bool = True,
) -> tuple[str, list[str]]:
    """Redige les secrets detectes dans `text`.

    Retourne `(clean_text, sorted_unique_categories)`.
    `categories` est une liste triee, sans doublon, des noms de patterns
    qui ont matche au moins une fois. Utile pour le log-warn cote caller.

    Si `text` est None ou vide, retourne `("", [])`.

    Les flags controlent les patterns high-FP :
      - `redact_emails`      : EMAIL
      - `redact_phones`      : PHONE (off par defaut)
      - `redact_credit_cards`: CREDIT_CARD (avec Luhn post-filter)
    """
    if not text:
        return "", []

    patterns: list[_Pattern] = list(_CORE_PATTERNS)
    if redact_emails:
        patterns.append(_EMAIL)
    if redact_credit_cards:
        patterns.append(_CREDIT_CARD)
    if redact_phones:
        patterns.append(_PHONE)

    found: set[str] = set()
    clean = text

    for pat in patterns:
        def _replace(match: re.Match[str], name: str = pat.name,
                     post: Optional[Callable[[str], bool]] = pat.post_filter) -> str:
            matched = match.group(0)
            if post is not None and not post(matched):
                # Post-filter rejected (e.g. Luhn fail) -> keep original.
                return matched
            found.add(name)
            return f"[REDACTED:{name}]"

        clean = pat.regex.sub(_replace, clean)

    return clean, sorted(found)


__all__ = ["redact"]
