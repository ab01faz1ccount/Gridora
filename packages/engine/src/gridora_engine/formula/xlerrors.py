"""Excel error values as first-class Python objects (never raised; they flow as values)."""
from __future__ import annotations


class XlError:
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code

    def __repr__(self) -> str:
        return self.code

    def __eq__(self, other: object) -> bool:
        return isinstance(other, XlError) and other.code == self.code

    def __hash__(self) -> int:
        return hash(self.code)


DIV0 = XlError("#DIV/0!")
NA = XlError("#N/A")
NAME = XlError("#NAME?")
NULL = XlError("#NULL!")
NUM = XlError("#NUM!")
REF = XlError("#REF!")
VALUE = XlError("#VALUE!")
SPILL = XlError("#SPILL!")
CALC = XlError("#CALC!")

BY_CODE = {e.code: e for e in (DIV0, NA, NAME, NULL, NUM, REF, VALUE, SPILL, CALC)}
