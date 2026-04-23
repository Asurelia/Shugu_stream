"""Unit tests — `shugu.memory.redaction` (Phase 2.6).

Couvre :
  - chaque pattern positif (un secret canonique est detecte + tag correct)
  - negatifs (false-positives courants : "I'm Alice", "visit https://...",
    timestamps, order numbers sans Luhn)
  - flags `redact_emails` / `redact_phones` / `redact_credit_cards`
  - ordre d'evaluation : Anthropic avant OpenAI, pas de double redaction
  - Luhn post-filter pour CC
  - return shape : `(str, list[str])` avec tag unique + trie
  - pas de catastrophic backtracking (timeout loose)
"""
from __future__ import annotations

import pytest

from shugu.memory.redaction import redact

# ---------------------------------------------------------------------------
# Empty / noop
# ---------------------------------------------------------------------------

def test_redact_empty_text_returns_empty_tuple() -> None:
    clean, cats = redact("")
    assert clean == ""
    assert cats == []


def test_redact_no_secrets_returns_text_unchanged() -> None:
    text = "I'm Alice, j'aime le cafe matcha. I live in Paris."
    clean, cats = redact(text)
    assert clean == text
    assert cats == []


# ---------------------------------------------------------------------------
# Positive tests (patterns toujours actifs)
# ---------------------------------------------------------------------------

# Note : les fixtures construisent les "shapes" de secret via concatenation
# pour eviter que les scanners de secrets (semgrep, trufflehog) les flaguent
# comme de vrais credentials hardcodes. Aucun de ces tokens n'est valide
# sur le service correspondant — ce sont des patterns synthetiques.
_STRIPE_LIVE_FIXTURE = "sk" + "_live_" + "51H8sKjLpQrStUvWxYzABCDEFghIjKlMnOpQrSt"
_STRIPE_TEST_FIXTURE = "sk" + "_test_" + "51H8sKjLpQrStUvWxYzABCDEF"
_ANTHROPIC_FIXTURE = "sk" + "-ant-api03-" + ("A" * 100)
_OPENAI_FIXTURE = "sk" + "-proj-" + ("B" * 48)
_GITHUB_CLASSIC_FIXTURE = "gh" + "p_" + ("A" * 36)
_GITHUB_FINE_GRAINED_FIXTURE = "github" + "_pat_" + ("A" * 82)
_GOOGLE_FIXTURE = "AI" + "zaSyD" + ("A" * 32)
_SLACK_FIXTURE = "xo" + "xb-123456789012-1234567890123-" + ("A" * 24)
_AWS_ACCESS_FIXTURE = "AK" + "IAIOSFODNN7EXAMPLE"  # AWS docs canonical example
_JWT_FIXTURE = (
    "ey" + "JhbGciOiJIUzI1NiJ9."
    "ey" + "JzdWIiOiJ1c2VyIn0."
    "sig-ABC-XYZ-123"
)


@pytest.mark.parametrize(
    "text, expected_tag",
    [
        # AWS access key
        (f"key={_AWS_ACCESS_FIXTURE} end", "AWS_ACCESS_KEY"),
        # Stripe (live + test)
        (f"use {_STRIPE_LIVE_FIXTURE} here", "STRIPE_KEY"),
        (f"test key {_STRIPE_TEST_FIXTURE} here", "STRIPE_KEY"),
        # Anthropic (must match BEFORE OpenAI)
        (f"export KEY={_ANTHROPIC_FIXTURE}", "ANTHROPIC_API_KEY"),
        # OpenAI
        (f"key {_OPENAI_FIXTURE} done", "OPENAI_API_KEY"),
        # GitHub (classic PAT: ghp_ + 36 chars)
        (f"use {_GITHUB_CLASSIC_FIXTURE} now", "GITHUB_TOKEN"),
        # GitHub fine-grained PAT
        (f"my {_GITHUB_FINE_GRAINED_FIXTURE} ok", "GITHUB_TOKEN"),
        # Google API
        (f"config {_GOOGLE_FIXTURE} end", "GOOGLE_API_KEY"),
        # Slack bot token
        (f"{_SLACK_FIXTURE} end", "SLACK_TOKEN"),
        # JWT
        (f"cookie={_JWT_FIXTURE} end", "JWT"),
    ],
)
def test_redact_each_core_pattern(text: str, expected_tag: str) -> None:
    clean, cats = redact(text)
    assert expected_tag in cats, f"{expected_tag} not detected in {text!r}"
    assert f"[REDACTED:{expected_tag}]" in clean


def test_redact_pem_private_key_multiline() -> None:
    text = (
        "header\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEAvQ==\n" * 5
        + "-----END RSA PRIVATE KEY-----\n"
        "footer"
    )
    clean, cats = redact(text)
    assert "PRIVATE_KEY" in cats
    assert "[REDACTED:PRIVATE_KEY]" in clean
    assert "-----BEGIN" not in clean
    assert "footer" in clean


def test_redact_openssh_private_key_multiline() -> None:
    text = (
        "pasted:\n"
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAA" * 5 + "\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    clean, cats = redact(text)
    assert "OPENSSH_PRIVATE_KEY" in cats
    assert "[REDACTED:OPENSSH_PRIVATE_KEY]" in clean


def test_redact_ssh_public_key_with_comment() -> None:
    text = "my key ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAbc" + "X" * 30 + " user@host end"
    clean, cats = redact(text)
    assert "SSH_PUBLIC_KEY" in cats
    assert "[REDACTED:SSH_PUBLIC_KEY]" in clean


def test_redact_aws_secret_key_context_gated() -> None:
    # Context-gated : the word "aws" must be nearby.
    text = 'aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
    clean, cats = redact(text)
    assert "AWS_SECRET_KEY" in cats


def test_redact_generic_secret_assignment() -> None:
    text = 'config api_key: "abcdefgh12345678ijklmnop"'
    clean, cats = redact(text)
    assert "GENERIC_SECRET" in cats


# ---------------------------------------------------------------------------
# Anthropic / OpenAI order: Anthropic must win on `sk-ant-*`
# ---------------------------------------------------------------------------

def test_anthropic_key_not_tagged_as_openai() -> None:
    text = f"export K={_ANTHROPIC_FIXTURE}"
    clean, cats = redact(text)
    assert "ANTHROPIC_API_KEY" in cats
    assert "OPENAI_API_KEY" not in cats
    assert "[REDACTED:ANTHROPIC_API_KEY]" in clean


# ---------------------------------------------------------------------------
# Email flag
# ---------------------------------------------------------------------------

def test_redact_email_default_on() -> None:
    text = "ping me at rafaillac.sylvain@gmail.com thanks"
    clean, cats = redact(text)
    assert "EMAIL" in cats
    assert "[REDACTED:EMAIL]" in clean


def test_redact_email_opt_out() -> None:
    text = "ping me at biz@mychannel.com thanks"
    clean, cats = redact(text, redact_emails=False)
    assert "EMAIL" not in cats
    assert "biz@mychannel.com" in clean


def test_social_handle_without_tld_not_redacted() -> None:
    """`@alice` sans domaine ne doit pas matcher le pattern email."""
    text = "follow @alice on twitter"
    clean, cats = redact(text)
    assert "EMAIL" not in cats
    assert "@alice" in clean


# ---------------------------------------------------------------------------
# Credit card + Luhn
# ---------------------------------------------------------------------------

def test_redact_credit_card_valid_luhn() -> None:
    # Visa test card — passe le Luhn check.
    text = "charge 4111 1111 1111 1111 please"
    clean, cats = redact(text)
    assert "CREDIT_CARD" in cats
    assert "[REDACTED:CREDIT_CARD]" in clean


def test_redact_credit_card_invalid_luhn_not_redacted() -> None:
    # Order number that looks like a CC but fails Luhn -> not redacted.
    text = "order 1234 5678 9012 3456 pending"
    clean, cats = redact(text)
    assert "CREDIT_CARD" not in cats
    assert "1234 5678 9012 3456" in clean


def test_redact_credit_card_opt_out() -> None:
    text = "charge 4111 1111 1111 1111 please"
    clean, cats = redact(text, redact_credit_cards=False)
    assert "CREDIT_CARD" not in cats
    assert "4111 1111 1111 1111" in clean


# ---------------------------------------------------------------------------
# Phone flag (off par defaut)
# ---------------------------------------------------------------------------

def test_redact_phone_default_off() -> None:
    text = "call me at +33 6 12 34 56 78 anytime"
    clean, cats = redact(text)
    assert "PHONE" not in cats
    assert "+33 6 12 34 56 78" in clean


def test_redact_phone_opt_in() -> None:
    text = "call me at +33 6 12 34 56 78 anytime"
    clean, cats = redact(text, redact_phones=True)
    assert "PHONE" in cats


# ---------------------------------------------------------------------------
# Return shape invariants
# ---------------------------------------------------------------------------

def test_redact_returns_sorted_unique_categories() -> None:
    # Two secrets in text -> two categories, sorted.
    text = f"{_GITHUB_CLASSIC_FIXTURE} and {_AWS_ACCESS_FIXTURE}"
    _, cats = redact(text)
    assert cats == sorted(cats)
    assert len(cats) == len(set(cats))
    assert "GITHUB_TOKEN" in cats
    assert "AWS_ACCESS_KEY" in cats


def test_redact_same_category_twice_reported_once() -> None:
    second_github = "gh" + "p_" + ("B" * 36)
    text = f"{_GITHUB_CLASSIC_FIXTURE} and another {second_github}"
    _, cats = redact(text)
    assert cats.count("GITHUB_TOKEN") == 1
    # Both occurrences redacted
    text_redacted = redact(text)[0]
    assert text_redacted.count("[REDACTED:GITHUB_TOKEN]") == 2


# ---------------------------------------------------------------------------
# Performance / robustness smoke (no catastrophic backtracking)
# ---------------------------------------------------------------------------

def test_redact_long_input_under_reasonable_time() -> None:
    """Large input that stresses each pattern shouldn't time out (<1s)."""
    import time
    text = ("lorem ipsum " * 500) + _AWS_ACCESS_FIXTURE + " " + ("dolor sit " * 500)
    t0 = time.perf_counter()
    clean, cats = redact(text)
    elapsed = time.perf_counter() - t0
    assert "AWS_ACCESS_KEY" in cats
    assert elapsed < 1.0, f"redact took {elapsed:.3f}s on 10KB input"
