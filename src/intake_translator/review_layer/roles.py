"""Per-tenant roles. Rank order is the whole authorization model."""

from __future__ import annotations

from ..core import IntakeError

ROLES = ("viewer", "reviewer", "approver", "admin")
RANK = {role: index for index, role in enumerate(ROLES)}

# Minimum role for each action. Overrides need an approver only when the tenant
# contract sets two_person_override.
ACTIONS = {
    "view": "viewer",
    "decide": "reviewer",
    "amend": "reviewer",
    "override_two_person": "approver",
    "audit_verify": "admin",
}


def validate_role(role: str) -> str:
    if role not in RANK:
        raise IntakeError("invalid_role", "role must be viewer, reviewer, approver or admin")
    return role


def allowed(role: str | None, action: str) -> bool:
    return role in RANK and action in ACTIONS and RANK[role] >= RANK[ACTIONS[action]]


def require(role: str | None, action: str) -> None:
    if not allowed(role, action):
        raise IntakeError("forbidden", f"role {role or 'none'} cannot {action}")
