"""Conformance with contracts/ (v0.3.x): every protocol method exists with compatible parameters.

`isinstance(x, Protocol)` only checks that names exist; this also checks the signature shape, so a contract change
that adds or reorders a parameter fails here instead of at integration time.
"""
from __future__ import annotations

import inspect

import pytest
from gridora_contracts import models
from gridora_contracts.protocols import ExecContext, OperationExecutor, TableStore
from typing_extensions import get_protocol_members

from gridora_dataops import DataOpsExecutor, ParquetTableStore


def _params(fn: object) -> list[inspect.Parameter]:
    return [p for n, p in inspect.signature(fn).parameters.items() if n != "self"]  # type: ignore[arg-type]


def test_written_against_contract_0_4() -> None:
    assert models.CONTRACT_VERSION.startswith(("0.4.", "0.5.", "0.6.")), "contracts/ changed: re-read the CHANGELOG and update dataops"


@pytest.mark.parametrize(("proto", "impl"), [(OperationExecutor, DataOpsExecutor), (TableStore, ParquetTableStore)])
def test_every_protocol_method_is_implemented_with_a_compatible_signature(proto: type, impl: type) -> None:
    members = sorted(get_protocol_members(proto))
    assert members, "protocol has no members?"
    for name in members:
        assert hasattr(impl, name), f"{impl.__name__} is missing {name}"
        want, have = _params(getattr(proto, name)), _params(getattr(impl, name))
        assert [p.name for p in have][: len(want)] == [p.name for p in want], f"{name}: parameter names/order differ"
        for p in have[len(want):]:
            assert p.default is not inspect.Parameter.empty, f"{name}: extra parameter '{p.name}' must have a default"
        for w, h in zip(want, have, strict=False):
            if w.default is not inspect.Parameter.empty:
                assert h.default is not inspect.Parameter.empty, f"{name}: '{h.name}' must keep its default"


def test_the_exec_context_members_dataops_relies_on_exist() -> None:
    assert {"user_id", "workspace_id", "read_range", "write_range", "table_store"} <= set(get_protocol_members(ExecContext))


def test_runtime_checks_pass_for_the_factories() -> None:
    from gridora_dataops import create_executor, create_table_store
    assert isinstance(create_executor({}), OperationExecutor)
    assert isinstance(create_table_store(lambda o, t, v: None), TableStore)  # type: ignore[arg-type,return-value]
