"""Named reviewer re-authentication for Approval Centre write actions.

Never accepts identity from a caller-supplied username/header without checking
a separately stored password hash. Shared dashboard Basic auth still gates all
routes, but does not identify the human for approval audit purposes.
"""
from __future__ import annotations

import re
from werkzeug.security import check_password_hash

NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{1,127}$")
ROLES = {"reviewer", "approver"}


class ReviewerAuthError(ValueError):
    pass


def reviewer_for_action(config: dict, username: str, password: str,
                        *, decision: bool = False) -> str:
    if not isinstance(username, str) or not NAME.fullmatch(username):
        raise ReviewerAuthError("Named reviewer authentication required")
    if not isinstance(password, str) or not password or len(password) > 512:
        raise ReviewerAuthError("Named reviewer authentication required")
    identities = config.get("approval_reviewer_accounts")
    if not isinstance(identities, list):
        raise ReviewerAuthError("Named review identities are not configured")
    for record in identities:
        if not isinstance(record, dict):
            continue
        if record.get("username") != username or record.get("role") not in ROLES:
            continue
        digest = record.get("password_hash")
        if not isinstance(digest, str) or not digest or len(digest) > 500:
            continue
        if check_password_hash(digest, password):
            if decision and record["role"] != "approver":
                raise ReviewerAuthError("Only named approvers may decide or revoke")
            return username
    raise ReviewerAuthError("Invalid named reviewer credentials")
