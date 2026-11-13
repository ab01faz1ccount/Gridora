"""i18n catalog (flat key -> text). Persian is the primary locale; English falls back to Persian per key."""
from __future__ import annotations

import json
from functools import cache
from importlib import resources


@cache
def _load(locale: str) -> dict[str, str]:
    path = resources.files("gridora_dataops").joinpath("i18n", f"{locale}.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def catalog(locale: str) -> dict[str, str]:
    """`fa` (default) or `en`; region suffixes (`fa-IR`) are ignored. Unknown locales get `fa`."""
    lang = (locale or "fa").split("-")[0].split("_")[0].lower()
    fa = _load("fa")
    return {**fa, **_load("en")} if lang == "en" else dict(fa)
