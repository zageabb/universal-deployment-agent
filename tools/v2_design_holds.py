"""Source-tracked DEV-020 special design-only holds for the Approval Centre.

Human review inventory only. Do not interpret these entries as executable
manifests, deployment permissions or runtime discovery of installed apps.
"""
from __future__ import annotations

DESIGN_ONLY_HOLDS = (
    {
        "application": "ScreenCraft",
        "repository": "zageabb/ScreenCraft",
        "reference": "draft PR #38",
        "gates": (
            "PIN_POSTGRES_IMAGE",
            "STARTUP_ALEMBIC_MIGRATION_APPROVAL",
            "SSO_PROXY_ASSERTION_AND_VOLUME_BACKUP",
        ),
    },
    {
        "application": "Camper Power Studio",
        "repository": "zageabb/camper-power-studio",
        "reference": "draft PR #1",
        "gates": (
            "SUPERVISOR_TWO_PROCESS_OWNERSHIP",
            "HOST_PORT_AND_NEXT_SUBPATH_RECONCILIATION",
            "SQLITE_BACKUP_AND_RUNTIME_SOURCE_REVIEW",
        ),
    },
    {
        "application": "DB Migration",
        "repository": "zageabb/DB_Migration",
        "reference": "draft PR #68",
        "gates": (
            "SEPARATE_READ_ONLY_RUNNER_AND_WRITE_TARGETS",
            "PRODUCTION_DDL_DML_OWNER_APPROVAL",
            "DB_BACKUP_RESTORE_AND_HOST_RECONCILIATION",
        ),
    },
    {
        "application": "ShadowPrompt Lab",
        "repository": "zageabb/shadowprompt_lab",
        "reference": "draft PR #1",
        "gates": (
            "HTTP_AUTH_CSRF_AND_EXTERNAL_EXPOSURE",
            "MAIL_AGENT_APPROVAL_AND_LLM_TRUST",
            "PERSISTENT_UPLOAD_AUDIT_AND_WSGI_RUNTIME",
        ),
    },
    {
        "application": "UDA protected platform self-upgrade",
        "repository": "zageabb/universal-deployment-agent",
        "reference": "docs/v2-dev020-platform-ownership-review.md",
        "gates": (
            "EXTERNAL_BOOTSTRAP_AND_ROLLBACK_OWNER",
            "PROTECTED_PLATFORM_COMPONENT_GRAPH",
            "HOST_SYSTEMD_TIMER_REGISTRY_RECONCILIATION",
        ),
    },
    {
        "application": "Application Home",
        "repository": "zageabb/universal-deployment-agent",
        "reference": "docs/v2-dev020-platform-ownership-review.md",
        "gates": (
            "SHARED_UDA_LIFECYCLE_OWNER",
            "PORTAL_IDENTITY_AND_GROUP_DB_BOUNDARY",
            "AUTHENTICATION_AND_SERVICE_UNIT_RECONCILIATION",
        ),
    },
)
