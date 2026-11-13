"""Operation registry. Adding an operation = registering a spec; no UI change needed."""
from __future__ import annotations

from typing import TypeVar

from .spec import OperationSpec

S = TypeVar("S", bound=OperationSpec)


class OperationRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, OperationSpec] = {}

    def register(self, spec: OperationSpec) -> OperationSpec:
        if spec.type in self._specs:
            raise ValueError(f"operation type already registered: {spec.type}")
        self._specs[spec.type] = spec
        return spec

    def get(self, type_: str) -> OperationSpec | None:
        return self._specs.get(type_)

    def all(self) -> list[OperationSpec]:
        return [self._specs[k] for k in sorted(self._specs)]  # sorted: deterministic order


def default_registry() -> OperationRegistry:
    """The production registry. Operations are added in M1+ (sort, filter, ...); empty in M0."""
    return OperationRegistry()
