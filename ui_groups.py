"""Shared presentation helpers for UDA application grouping."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Sequence

DEFAULT_GROUP = "Other"


def clean_group_name(value: Any) -> str:
    """Normalize and validate a user-facing group name."""
    if not isinstance(value, str):
        raise ValueError("Group name must be text")
    name = value.strip()
    if not name or any(character in name for character in "\x00\n\r"):
        raise ValueError("Group name must be a non-empty single-line value")
    if len(name) > 80:
        raise ValueError("Group name must be 80 characters or fewer")
    return name


def application_group(entry: dict[str, Any]) -> str:
    """Return the configured display group, falling back for older entries."""
    value = entry.get("group")
    if not isinstance(value, str):
        return DEFAULT_GROUP
    return value.strip() or DEFAULT_GROUP


def configured_groups(config: dict[str, Any]) -> list[str]:
    """Return managed groups in display order, importing legacy app group values."""
    names: list[str] = []
    seen: set[str] = set()

    for value in config.get("groups", []):
        name = clean_group_name(value)
        key = name.casefold()
        if name != DEFAULT_GROUP and key not in seen:
            names.append(name)
            seen.add(key)

    for entry in config.get("applications", []):
        name = application_group(entry)
        key = name.casefold()
        if name != DEFAULT_GROUP and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def group_summary(applications: Iterable[dict[str, Any]], groups: Sequence[str] | None = None,
                  include_empty: bool = False) -> list[dict[str, Any]]:
    """Return group counts, respecting managed group order when supplied."""
    applications = list(applications)
    counts = Counter(application_group(app) for app in applications)

    if groups is None:
        names = sorted((name for name in counts if name != DEFAULT_GROUP), key=str.casefold)
    else:
        names = []
        seen: set[str] = set()
        for name in groups:
            key = name.casefold()
            if name != DEFAULT_GROUP and key not in seen:
                if include_empty or counts.get(name, 0):
                    names.append(name)
                seen.add(key)
        extras = sorted((name for name in counts if name != DEFAULT_GROUP and name.casefold() not in seen),
                        key=str.casefold)
        names.extend(extras)

    rows = [{"name": name, "count": counts.get(name, 0)} for name in names]
    if counts.get(DEFAULT_GROUP, 0):
        rows.append({"name": DEFAULT_GROUP, "count": counts[DEFAULT_GROUP]})
    return rows
