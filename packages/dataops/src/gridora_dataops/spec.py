"""Operation specification base classes."""
from __future__ import annotations

import builtins
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import polars as pl
from gridora_contracts.models import OperationDescriptor, ValidationError, Warning_
from pydantic import BaseModel, ConfigDict, Field

VOCAB_VERSION = 1
TargetKind = Literal["sheet_range", "data_table"]


class ParamsModel(BaseModel):
    """Base for every operation's params. Unknown fields are rejected (JSON Schema additionalProperties:false)."""

    model_config = ConfigDict(extra="forbid")


def column_field(*, column_of: str = "target", types: list[str] | None = None, **kwargs: Any) -> Any:
    """Pydantic field for a parameter that holds a column name (`x-gridora-column`)."""
    extra: dict[str, Any] = {"x-gridora-column": True}
    if column_of != "target":
        extra["x-gridora-column-of"] = column_of
    if types:
        extra["x-gridora-column-types"] = types
    return Field(json_schema_extra=extra, **kwargs)


@dataclass
class PlanEnv:
    """Read-only context for `plan` (no I/O handles on purpose: plans are pure)."""

    has_header: bool = True
    column_names: list[str] = field(default_factory=list)


@dataclass
class OpOutput:
    frame: pl.DataFrame
    warnings: list[Warning_] = field(default_factory=list)


class OperationSpec:
    """One registered operation. `plan` must be a pure function: frame + params -> frame."""

    type: ClassVar[str]
    category: ClassVar[str]
    destructive: ClassVar[bool] = False
    supports_preview: ClassVar[bool] = True
    targets: ClassVar[tuple[TargetKind, ...]] = ("sheet_range", "data_table")
    schema_version: ClassVar[int] = 1
    # True when the operation rewrites existing cells (so formulas in the range would be lost).
    rewrites_cells: ClassVar[bool] = True
    Params: ClassVar[builtins.type[ParamsModel]]

    def validate_static(self, params: ParamsModel) -> list[ValidationError]:
        """Cross-field rules that need no data."""
        return []

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        raise NotImplementedError

    def migrate(self, params: dict[str, Any], from_version: int) -> dict[str, Any]:
        """Upgrade params saved with an older `schema_version`. Default: no migrations exist yet."""
        return params

    def has_header(self, params: ParamsModel) -> bool:
        return bool(getattr(params, "has_header", True))

    def descriptor(self) -> OperationDescriptor:
        from .schema import build_params_schema

        return OperationDescriptor(
            type=self.type,
            label=f"ops.{self.type}.label",
            category=self.category,
            description=f"ops.{self.type}.description",
            params_schema=build_params_schema(self),
            targets=list(self.targets),
            destructive=self.destructive,
            supports_preview=self.supports_preview,
        )
