"""Tool inputs: `{"$input": "<name>"}` placeholders in pipeline step params (bind and validate)."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Optional

from gridora_contracts.models import (
    Operation,
    Pipeline,
    PipelineStep,
    Range,
    SheetRangeTarget,
    Target,
    Tool,
    ValidationError,
)
from gridora_contracts.protocols import ExecContext
from pydantic import ValidationError as PydanticValidationError

from .errors import DataOpsError, pointer, verr

PLACEHOLDER = "$input"
SCALARS = {"string", "integer", "number", "boolean"}


def is_placeholder(v: Any) -> bool:
    return isinstance(v, dict) and set(v) == {PLACEHOLDER} and isinstance(v[PLACEHOLDER], str)


def placeholders(node: Any, ptr: str = "") -> Iterator[tuple[str, str]]:
    """Yield (json_pointer, input_name) for every placeholder inside `node`."""
    if is_placeholder(node):
        yield ptr, node[PLACEHOLDER]
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from placeholders(v, ptr + pointer(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from placeholders(v, ptr + pointer(i))


def _substitute(node: Any, values: dict[str, Any], missing_optional: set[str]) -> Any:
    if is_placeholder(node):
        return values.get(node[PLACEHOLDER], _MISSING)
    if isinstance(node, dict):
        out = {k: _substitute(v, values, missing_optional) for k, v in node.items()}
        return {k: v for k, v in out.items() if v is not _MISSING}  # an unbound optional input drops its key
    if isinstance(node, list):
        return [x for x in (_substitute(v, values, missing_optional) for v in node) if x is not _MISSING]
    return node


_MISSING = object()


def _check_value(kind: str, v: Any) -> Optional[str]:
    if kind == "column":
        return None if isinstance(v, str) and v else "a column input must be a non-empty column name"
    if kind == "value":
        return None if isinstance(v, (bool, int, float, str)) else "a value input must be a text, number or yes/no value"
    try:
        Range.model_validate(v)
    except (PydanticValidationError, ValueError):
        return "a range input must be a range object"
    return None


def bind_tool(tool: Tool, inputs: dict[str, Any]) -> Pipeline:
    """Replace every placeholder with its bound value. An unbound OPTIONAL input removes the parameter it stood for
    (so the operation's default applies). Errors are collected and raised together (`validation_failed`)."""
    errs: list[ValidationError] = []
    declared = {i.name: i for i in tool.inputs}
    for name in inputs:
        if name not in declared:
            errs.append(verr("invalid_param", pointer("inputs", name), f"unknown input '{name}'"))
    values: dict[str, Any] = {}
    for name, decl in declared.items():
        if name not in inputs or inputs[name] is None:
            if decl.required:
                errs.append(verr("invalid_param", pointer("inputs", name), f"required input '{name}' is missing"))
            continue
        problem = _check_value(decl.kind, inputs[name])
        if problem:
            errs.append(verr("invalid_param", pointer("inputs", name), problem))
        else:
            values[name] = inputs[name]
    steps = []
    for i, st in enumerate(tool.pipeline.steps):
        for ptr, name in placeholders(st.params):
            if name not in declared:
                errs.append(verr("invalid_param", pointer("pipeline", "steps", i) + "/params" + ptr,
                                 f"step uses undeclared input '{name}'"))
        steps.append(PipelineStep(type=st.type, schema_version=st.schema_version, label=st.label,
                                  params=_substitute(st.params, values, set(declared) - set(values))))
    if errs:
        raise DataOpsError("validation_failed", "the tool inputs are invalid", errors=errs)
    return Pipeline(id=tool.pipeline.id, name=tool.pipeline.name, input_kind=tool.pipeline.input_kind, steps=steps)


# ------------------------------------------------------------------ design-time validation
def _resolve(node: Any, defs: dict[str, Any]) -> Any:
    while isinstance(node, dict) and isinstance(node.get("$ref"), str):
        node = defs.get(node["$ref"].split("/")[-1], {})
    return node


def _candidates(node: Any, part: str, defs: dict[str, Any], column_parent: bool) -> list[tuple[Any, bool]]:
    node = _resolve(node, defs)
    if not isinstance(node, dict):
        return []
    out: list[tuple[Any, bool]] = []
    flag = bool(node.get("x-gridora-column")) or column_parent
    if part.isdigit() and "items" in node:
        out.append((node["items"], flag))
    if part in node.get("properties", {}):
        out.append((node["properties"][part], False))
    for branch in node.get("anyOf", []):
        out.extend(_candidates(branch, part, defs, column_parent))
    return out


def _types(node: Any, defs: dict[str, Any]) -> set[str]:
    node = _resolve(node, defs)
    if not isinstance(node, dict):
        return set()
    t = node.get("type")
    found = {t} if isinstance(t, str) else set(t or [])
    for b in node.get("anyOf", []):
        found |= _types(b, defs)
    return found


def position(schema: dict[str, Any], parts: list[str]) -> tuple[bool, set[str], Optional[Any]]:
    """(is a column position, scalar JSON types allowed there, first enum value) for a params pointer."""
    defs = schema.get("$defs", {})
    cur: list[tuple[Any, bool]] = [(schema, False)]
    for part in parts:
        nxt: list[tuple[Any, bool]] = []
        for node, flag in cur:
            nxt.extend(_candidates(node, part, defs, flag))
        cur = nxt
    is_col = any(bool(_resolve(n, defs).get("x-gridora-column")) or f for n, f in cur if isinstance(_resolve(n, defs), dict))
    types: set[str] = set()
    enum = None
    for n, _ in cur:
        types |= _types(n, defs) & SCALARS
        r = _resolve(n, defs)
        if isinstance(r, dict) and r.get("enum") and enum is None:
            enum = r["enum"][0]
    return is_col, types, enum


def _dummy(kind: str, types: set[str], enum: Any) -> Any:
    if kind == "column":
        return "__column__"
    if enum is not None:
        return enum
    for t, v in (("boolean", False), ("integer", 1), ("number", 1.0), ("string", "x")):
        if t in types:
            return v
    return "x"


def _set(node: Any, parts: list[str], value: Any) -> None:
    for p in parts[:-1]:
        node = node[int(p)] if isinstance(node, list) else node[p]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def validate_tool(ex: Any, tool: Tool, target: Target, ctx: Optional[ExecContext] = None) -> list[ValidationError]:
    """Design-time checks. Column values are only known at run time, so existing-column checks cover the first
    step's literal columns (when a context is given); later steps see columns produced by earlier steps."""
    import copy

    errs: list[ValidationError] = []
    pl_ = tool.pipeline
    if pl_.input_kind != target.kind:
        errs.append(verr("invalid_param", pointer("pipeline", "input_kind"),
                         f"the tool expects a {pl_.input_kind}, the target is a {target.kind}"))
    names = [i.name for i in tool.inputs]
    for i, n in enumerate(names):
        if names.count(n) > 1 and names.index(n) != i:
            errs.append(verr("invalid_param", pointer("inputs", i, "name"), f"input '{n}' is declared twice"))
    declared = {i.name: i for i in tool.inputs}
    used: set[str] = set()
    for i, st in enumerate(pl_.steps):
        base = pointer("pipeline", "steps", i)
        spec = ex.registry.get(st.type)
        if spec is None:
            errs.append(verr("unknown_operation", base + "/type", f"unknown operation '{st.type}'"))
            continue
        if spec.extra_inputs:
            errs.append(verr("invalid_param", base + "/type", f"'{st.type}' needs extra targets and cannot be a pipeline step"))
            continue
        params = copy.deepcopy(st.params)
        schema = spec.descriptor().params_schema
        skip: list[str] = []
        for ptr, name in placeholders(st.params):
            parts = [p.replace("~1", "/").replace("~0", "~") for p in ptr.split("/")[1:]]
            used.add(name)
            skip.append(ptr)
            decl = declared.get(name)
            if decl is None:
                errs.append(verr("invalid_param", base + "/params" + ptr, f"step uses undeclared input '{name}'"))
                continue
            is_col, types, enum = position(schema, parts)
            if decl.kind == "column" and not is_col:
                errs.append(verr("invalid_param", base + "/params" + ptr, f"'{name}' is a column input but this parameter is not a column"))
            elif decl.kind == "value" and (is_col or not types):
                errs.append(verr("invalid_param", base + "/params" + ptr, f"'{name}' is a value input but this parameter takes no plain value"))
            elif decl.kind == "range":
                errs.append(verr("invalid_param", base + "/params" + ptr, "range inputs are not accepted by any v1 operation parameter"))
            if parts:
                _set(params, parts, _dummy(decl.kind, types, enum))
        op = Operation(type=st.type, schema_version=st.schema_version, target=target, params=params)
        _spec, resolved, e2 = ex._resolve(op)
        for e in e2:
            if not any(e.path == "/params" + s or e.path.startswith("/params" + s + "/") for s in skip):
                errs.append(verr(e.code, base + e.path, e.message, e.hint))
        if i == 0 and ctx is not None and resolved is not None and not e2:
            try:
                src = ex._load_target(target, ctx, has_header=spec.has_header(resolved), allow_formulas=True)
            except DataOpsError as load_err:
                errs.extend(verr(x.code, base + x.path, x.message, x.hint) for x in load_err.errors)
            else:
                for ce in ex._check_columns(spec, resolved, src.names):
                    if not any(ce.path == s2 or ce.path.startswith(s2 + "/") for s2 in ["/params" + s for s in skip]):
                        errs.append(verr(ce.code, base + ce.path, ce.message, ce.hint))
    for n, decl in declared.items():
        if n not in used:
            errs.append(verr("invalid_param", pointer("inputs", n), f"input '{n}' is never used by a step"))
    _ = SheetRangeTarget
    return errs
