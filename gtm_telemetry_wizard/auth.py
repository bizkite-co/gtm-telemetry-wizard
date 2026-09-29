"""Canonical OAuth scopes gtw needs, and gcloud multi-account auth helpers.

Single source of truth for the scopes this tool requires. Past incidents
adjusted scopes ad hoc (a string literal buried inside
TelemetryProvider._access_token, with the actionable fix only ever typed by
hand into a terminal), which drifted out of sync with what commands
actually need and left every "add a scope" a manual, non-repeatable step
across every machine/account. Add a scope here once; `gtw auth login`
re-grants it for whichever accounts are missing it, and nothing else in
this package should hardcode a scope string again.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

# Needed to read GA4 report/admin data and GTM containers (pull_from_ga4,
# `gtw query`, `gtw accounts discover`, `gtw wizard`'s status check).
READ_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/tagmanager.readonly",
)

# Needed to create/modify GA4 properties and GTM containers (`gtw
# provision`, `gtw deploy`).
WRITE_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/analytics.edit",
    "https://www.googleapis.com/auth/tagmanager.edit.containers",
)

# Always requested alongside the above - identity + general GCP API access.
BASE_SCOPES: tuple[str, ...] = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/cloud-platform",
)

ALL_SCOPES: tuple[str, ...] = BASE_SCOPES + READ_SCOPES + WRITE_SCOPES


def scopes_arg(scopes: tuple[str, ...] = ALL_SCOPES) -> str:
    """Comma-joined scope list, as `gcloud auth login --scopes=` expects."""
    return ",".join(scopes)


@dataclass
class AccountScopeStatus:
    account: str
    granted_scopes: frozenset[str] = field(default_factory=frozenset)
    missing: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.missing and not self.error


def list_gcloud_accounts() -> list[str]:
    """All accounts gcloud already knows about locally (`gcloud auth list`)."""
    result = subprocess.run(
        ["gcloud", "auth", "list", "--format=json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    try:
        entries = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [str(e["account"]) for e in entries if e.get("account")]


def _print_access_token(account: str) -> Optional[str]:
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token", f"--account={account}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[0]


def check_account_scopes(
    account: str, required: tuple[str, ...] = ALL_SCOPES
) -> AccountScopeStatus:
    """Query which of `required` scopes `account`'s current gcloud token actually carries.

    Read-only - never triggers a login. Use this to decide whether
    `ensure_account_scopes` needs to prompt at all.
    """
    token = _print_access_token(account)
    if not token:
        return AccountScopeStatus(account, error="No gcloud credentials for this account.")

    try:
        with urllib.request.urlopen(
            f"https://www.googleapis.com/oauth2/v1/tokeninfo?access_token={token}",
            timeout=10,
        ) as resp:
            info = json.load(resp)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return AccountScopeStatus(account, error=f"Could not verify token scopes: {exc}")

    granted = frozenset((info.get("scope") or "").split())
    missing = tuple(s for s in required if s not in granted)
    return AccountScopeStatus(account, granted_scopes=granted, missing=missing)


def ensure_account_scopes(
    account: str, required: tuple[str, ...] = ALL_SCOPES, force: bool = False
) -> AccountScopeStatus:
    """Idempotent: only runs the interactive `gcloud auth login` if scopes
    are actually missing (or `force=True`). Safe to call every time - a
    fully-scoped account is a no-op, so this is the one command to re-run
    whenever `ALL_SCOPES` above gains a new entry."""
    status = check_account_scopes(account, required)
    if status.ok and not force:
        return status

    subprocess.run(
        ["gcloud", "auth", "login", account, f"--scopes={scopes_arg(required)}"],
        check=True,
    )
    return check_account_scopes(account, required)
