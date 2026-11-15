from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from gridora_contracts.models import CompatibilityReport, CompatItem, CompatSummary

from .registry import REGISTRY


@dataclass
class Hit:
    count: int
    locations: list[str] = field(default_factory=list)


def _location(locs: list[str]) -> str | None:
    if not locs:
        return None
    head = ", ".join(locs[:5])
    return head + (f" (+{len(locs) - 5} more)" if len(locs) > 5 else "")


def build_report(
    source: Literal["import", "export"], hits: Mapping[str, int | Hit]
) -> CompatibilityReport:
    """hits: registry code -> count (>0). Unknown codes are a programming error (KeyError)."""
    items: list[CompatItem] = []
    summary = CompatSummary()
    for code, raw in hits.items():
        count = raw.count if isinstance(raw, Hit) else raw
        locs = raw.locations if isinstance(raw, Hit) else []
        if count <= 0:
            continue
        f = REGISTRY[code]
        preserved = f.tier == "preserved"
        status: Literal["supported", "partial", "unsupported"] = (
            "supported" if f.tier == "supported"
            else "partial" if f.tier == "partial" else "unsupported"
        )
        items.append(
            CompatItem(
                code=code, status=status, preserved=preserved,
                editable=f.editable and not preserved,
                message=f.message.format(count=count),
                location=_location(locs),
            )
        )
        setattr(summary, status, getattr(summary, status) + 1)
    return CompatibilityReport(
        source=source, generated_at=datetime.now(UTC), items=items, summary=summary
    )
