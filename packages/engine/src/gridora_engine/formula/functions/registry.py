"""Function registry and decorator. Function bodies raise XlRaise to return an error."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class FuncSpec:
    name: str
    fn: Callable
    min_args: int
    max_args: int  # -1 = unlimited
    lazy: bool = False  # receives (ctx, nodes) instead of evaluated args
    arr: bool = False  # arguments are evaluated in array context (no implicit intersection)
    volatile: bool = False


REGISTRY: dict[str, FuncSpec] = {}


def fn(name: str, min_args: int = 0, max_args: int | None = None, *, lazy: bool = False,
       arr: bool = False, volatile: bool = False, aliases: tuple[str, ...] = ()):
    mx = min_args if max_args is None else max_args

    def deco(f: Callable) -> Callable:
        for n in (name, *aliases):
            REGISTRY[n] = FuncSpec(n, f, min_args, mx, lazy, arr, volatile)
        return f

    return deco
