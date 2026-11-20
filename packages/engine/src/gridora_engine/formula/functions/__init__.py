from .registry import REGISTRY, FuncSpec, fn  # noqa: F401

# Importing the modules registers their functions.
from . import logical, mathfn, info, stats, datefn, text, lookup, financial  # noqa: F401,E402
