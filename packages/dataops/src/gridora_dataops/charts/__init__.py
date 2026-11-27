"""Chart data: ChartSpec + a frame -> plain categories and series (ChartData).

Layers (docs/DESIGN.md "charts"): common.py (column lookup, filters, null-aware aggregation, date axes) ->
transform.py (order, Top N, Other) -> adapters.py (one function per chart type). `build_chart_data` is the only entry."""
from __future__ import annotations

import polars as pl
from gridora_contracts.models import ChartData, ChartSpec

from ..errors import DataOpsError, pointer
from .adapters import ADAPTERS
from .common import MAX_CATEGORIES, MAX_SCATTER_POINTS, MAX_SERIES, apply_filters

__all__ = ["MAX_CATEGORIES", "MAX_SCATTER_POINTS", "MAX_SERIES", "build_chart_data"]


def build_chart_data(spec: ChartSpec, frame: pl.DataFrame) -> ChartData:
    if not spec.series:
        raise DataOpsError("invalid_param", "a chart needs at least one series", path=pointer("series"))
    adapter = ADAPTERS.get(spec.type)
    if adapter is None:  # a type the contract knows but this build has no adapter for
        raise DataOpsError("not_implemented", f"chart type '{spec.type}'", path=pointer("type"))
    return adapter(spec, apply_filters(frame, spec.filters))
