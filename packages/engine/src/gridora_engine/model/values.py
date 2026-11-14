"""Internal tagged value storage and conversion to contract CellValue."""
from __future__ import annotations

from gridora_contracts.models import BoolValue, CellValue, ErrValue, NumValue, StrValue

EMPTY, NUM, STR, BOOL, ERR = 0, 1, 2, 3, 4

# Index order is part of the in-memory format only (never persisted).
ERR_CODES: tuple[str, ...] = (
    "#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!",
    "#SPILL!", "#CALC!", "#GETTING_DATA",
)


class StringTable:
    """Interned strings shared by all sheets of a workbook. Indices are stable (append-only)."""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._index: dict[str, int] = {}

    def intern(self, s: str) -> int:
        i = self._index.get(s)
        if i is None:
            i = len(self._items)
            self._items.append(s)
            self._index[s] = i
        return i

    def get(self, i: int) -> str:
        return self._items[i]

    def __len__(self) -> int:
        return len(self._items)


def to_contract_value(tag: int, val: float, strings: StringTable) -> CellValue | None:
    """Build a contract value. model_construct skips re-validation: internal data is trusted."""
    if tag == NUM:
        return NumValue.model_construct(k="num", n=val)
    if tag == STR:
        return StrValue.model_construct(k="str", s=strings.get(int(val)))
    if tag == BOOL:
        return BoolValue.model_construct(k="bool", b=bool(val))
    if tag == ERR:
        return ErrValue.model_construct(k="err", e=ERR_CODES[int(val)])  # type: ignore[arg-type]
    return None
