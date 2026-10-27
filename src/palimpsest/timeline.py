"""Deletion timeline: when things died, and whether they died together."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import Artifact


def build(artifacts: list[Artifact]) -> list[dict[str, Any]]:
    groups: dict[str, list[Artifact]] = defaultdict(list)
    for artifact in artifacts:
        stamp = artifact.deleted_at
        if not stamp:
            continue
        groups[stamp[:10]].append(artifact)

    events = []
    for date, members in groups.items():
        kinds: dict[str, int] = {}
        for member in members:
            kinds[member.kind] = kinds.get(member.kind, 0) + 1
        events.append(
            {
                "date": date,
                "count": len(members),
                "kinds": kinds,
                "ids": [m.id for m in members],
                "mass": len(members) >= 5,
            }
        )
    return sorted(events, key=lambda e: (e["date"], e["count"]), reverse=True)


def range_label(events: list[dict[str, Any]]) -> str:
    dates = sorted(e["date"] for e in events)
    if not dates:
        return "unknown"
    if dates[0] == dates[-1]:
        return dates[0]
    return f"{dates[0]} to {dates[-1]}"
