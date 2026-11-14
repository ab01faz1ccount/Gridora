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
    """The production registry: every operation the package ships."""
    from .ops.change_type import ChangeTypeOp
    from .ops.clean_text import CleanTextOp
    from .ops.fill import FillOp
    from .ops.filter import FilterOp
    from .ops.find_replace import FindReplaceOp
    from .ops.merge_columns import MergeColumnsOp
    from .ops.remove_duplicates import RemoveDuplicatesOp
    from .ops.sort import SortOp
    from .ops.split_column import SplitColumnOp

    reg = OperationRegistry()
    for spec in (SortOp(), FilterOp(), RemoveDuplicatesOp(), ChangeTypeOp(), FindReplaceOp(), FillOp(), CleanTextOp(),
                 SplitColumnOp(), MergeColumnsOp()):
        reg.register(spec)
    return reg
