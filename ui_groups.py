"""Shared presentation helpers for UDA application grouping."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

DEFAULT_GROUP = "Other"


def application_group(entry: dict[str, Any]) -> str:
    """Return the configured display group, falling back for older entries."""
    value = entry.get("group")
    if not isinstance(value, str):
        return DEFAULT_GROUP
    return value.strip() or DEFAULT_GROUP


def group_summary(applications: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return alphabetic group counts with the default catch-all group last."""
    counts = Counter(application_group(app) for app in applications)
    names = sorted(counts, key=lambda name: (name == DEFAULT_GROUP, name.casefold()))
    return [{"name": name, "count": counts[name]} for name in names]
