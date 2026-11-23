# Importing the modules registers their functions.
from . import (  # noqa: F401
    arrays2,
    datefn,
    financial,
    financial2,
    info,
    lambdas,
    logical,
    lookup,
    mathfn,
    mathx,
    stats,
    stats2,
    text,
)
from .registry import REGISTRY, FuncSpec, fn

__all__ = ["REGISTRY", "FuncSpec", "fn"]
