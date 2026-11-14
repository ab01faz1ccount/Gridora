"""Params JSON Schema generation and schema-driven checks (see docs/PARAMS_SCHEMA.md)."""
from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

from gridora_contracts.models import OperationDescriptor

from .errors import pointer
from .spec import VOCAB_VERSION, OperationSpec


def _inline_refs(node: Any, defs: dict[str, Any], stack: tuple[str, ...] = ()) -> Any:
    """Inline non-recursive local $refs; recursive ones stay as $ref (rendered by builder widgets)."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.split("/")[-1]
            if name in stack:
                return node
            merged = {**_inline_refs(copy.deepcopy(defs[name]), defs, stack + (name,)),
                      **{k: v for k, v in node.items() if k != "$ref"}}
            return merged
        return {k: _inline_refs(v, defs, stack) for k, v in node.items() if k != "$defs" or stack}
    if isinstance(node, list):
        return [_inline_refs(v, defs, stack) for v in node]
    return node


def _apply_keys(node: dict[str, Any], base: str) -> None:
    """Replace auto-generated English titles with i18n keys and add enum label keys."""
    node["title"] = f"{base}.title"
    if "description" in node or node.get("type") in ("object", "array") or "enum" in node:
        node["description"] = f"{base}.description"
    if "enum" in node and "x-gridora-enum-labels" not in node:
        node["x-gridora-enum-labels"] = {str(v): f"{base}.options.{v}" for v in node["enum"]}
    for name, sub in node.get("properties", {}).items():
        if isinstance(sub, dict):
            _apply_keys(sub, f"{base}.{name}")
    items = node.get("items")
    if isinstance(items, dict):
        _apply_keys(items, f"{base}.items")
    for branch in node.get("anyOf", []):
        if isinstance(branch, dict) and "$ref" not in branch and branch.get("type") != "null":
            _apply_keys(branch, base)


def build_params_schema(spec: OperationSpec) -> dict[str, Any]:
    raw = spec.Params.model_json_schema()
    schema: dict[str, Any] = _inline_refs(raw, raw.get("$defs", {}))
    schema.pop("$defs", None) if "$ref" not in str(schema) else None
    schema["x-gridora-vocab"] = VOCAB_VERSION
    schema["additionalProperties"] = False
    base = f"ops.{spec.type}.params"
    schema.pop("title", None)
    for name, sub in schema.get("properties", {}).items():
        if isinstance(sub, dict):
            _apply_keys(sub, f"{base}.{name}")
    return schema


def required_i18n_keys(desc: OperationDescriptor) -> set[str]:
    keys = {desc.label, desc.description, f"ops.categories.{desc.category}"}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k in ("title", "description", "x-gridora-group", "x-gridora-unit"):
                v = node.get(k)
                if isinstance(v, str) and v.startswith("ops."):
                    keys.add(v)
            labels = node.get("x-gridora-enum-labels")
            if isinstance(labels, dict):
                keys.update(v for v in labels.values() if isinstance(v, str))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(desc.params_schema)
    return keys


def column_refs(schema: dict[str, Any], params: Any, base: str = "/params") -> Iterator[tuple[str, str, str]]:
    """Yield (json_pointer, column_name, column_of) for every `x-gridora-column` value in `params`."""

    def walk(node: Any, value: Any, ptr: str) -> Iterator[tuple[str, str, str]]:
        if not isinstance(node, dict):
            return
        if node.get("x-gridora-column"):
            of = str(node.get("x-gridora-column-of", "target"))
            if isinstance(value, str):
                yield ptr, value, of
            elif isinstance(value, list):  # an array marked x-gridora-column is a list of column names
                for i, v in enumerate(value):
                    if isinstance(v, str):
                        yield ptr + pointer(i), v, of
        if isinstance(value, dict):
            for key, sub in node.get("properties", {}).items():
                if key in value:
                    yield from walk(sub, value[key], ptr + pointer(key))
        elif isinstance(value, list):
            items = node.get("items")
            for i, v in enumerate(value):
                yield from walk(items, v, ptr + pointer(i))
        for branch in node.get("anyOf", []):
            yield from walk(branch, value, ptr)

    yield from walk(schema, params, base)
