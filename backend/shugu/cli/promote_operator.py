"""CLI: promote a user_account to operator.

Usage:
    python -m shugu.cli.promote_operator <username>

Sets `is_operator=True` on the user_account identified by <username>.
Exits with code 0 on success, non-zero on failure (user not found, DB error).

This command:
  - Requires no authentication (run locally on the server only)
  - Connects to the real DB (reads ops/env/.env or SHUGU_ENV_FILE)
  - Is idempotent: promoting an already-operator user is a no-op (exit 0)
  - Does NOT send any notification

Bootstrap problem solution:
  When starting fresh (no operator at all), the legacy OPERATOR_PASSWORD_HASH
  env var is still available for the first login. Once the admin has registered
  a user_account (via /account/register + /account/verify-email), they run:

      python -m shugu.cli.promote_operator <username>

  Then log in at /account/login. They receive dual cookies and voice-body
  activates immediately.

Examples:
    python -m shugu.cli.promote_operator spoukie
    # Output: [ok] spoukie is now an operator.

    python -m shugu.cli.promote_operator nonexistent
    # Output: [error] User 'nonexistent' not found.
    # Exit code: 1
"""
from __future__ import annotations

import asyncio
import sys


async def promote_operator(
    username: str,
    *,
    session_scope_override=None,
) -> None:
    """Set is_operator=True on user_account identified by username.

    Args:
        username: The canonical (lowercased) username to promote.
        session_scope_override: Optional async context manager to use instead
            of the real DB session. Used by tests to inject a mock DB.

    Raises:
        SystemExit(1): If the user is not found.
        SystemExit(2): If a DB error occurs.
    """
    username = username.strip().lower()

    if session_scope_override is not None:
        scope = session_scope_override
    else:
        from ..db.session import session_scope as _real_scope
        scope = _real_scope

    try:
        async with scope() as db:
            from sqlalchemy import select

            from ..db.models import UserAccount

            stmt = select(UserAccount).where(UserAccount.username == username)
            account = (await db.execute(stmt)).scalars().first()

            if account is None:
                print(f"[error] User '{username}' not found.", file=sys.stderr)
                sys.exit(1)

            if account.is_operator:
                print(f"[ok] '{username}' is already an operator. No change.")
                return

            account.is_operator = True
            print(f"[ok] '{username}' is now an operator.")
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[error] DB error: {exc}", file=sys.stderr)
        sys.exit(2)


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m shugu.cli.promote_operator <username>")
        print()
        print("  Sets is_operator=True on the user_account identified by <username>.")
        print("  Run locally (no auth required). Requires DB access.")
        print()
        print("  Exit codes:")
        print("    0 — success (or already an operator)")
        print("    1 — user not found")
        print("    2 — DB error")
        sys.exit(0 if "--help" in sys.argv else 1)

    username = sys.argv[1]
    asyncio.run(promote_operator(username))


if __name__ == "__main__":
    main()
