from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from gridora_contracts.models import CompatibilityReport, CompatItem, CompatSummary

from .registry import REGISTRY


def build_report(
    source: Literal["import", "export"], hits: Mapping[str, int]
) -> CompatibilityReport:
    """hits: registry code -> count (>0). Unknown codes are a programming error (KeyError)."""
    items: list[CompatItem] = []
    summary = CompatSummary()
    for code, count in hits.items():
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
            )
        )
        setattr(summary, status, getattr(summary, status) + 1)
    return CompatibilityReport(
        source=source, generated_at=datetime.now(UTC), items=items, summary=summary
    )
