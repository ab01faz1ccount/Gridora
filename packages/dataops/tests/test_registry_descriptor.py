from __future__ import annotations

import json

import pytest
from gridora_contracts.protocols import OperationExecutor
from jsonschema import Draft202012Validator
from ops_for_tests import CaseOp, build_registry

from gridora_dataops import DataOpsExecutor, catalog, create_executor
from gridora_dataops.errors import ERROR_CODES
from gridora_dataops.registry import OperationRegistry, default_registry
from gridora_dataops.schema import required_i18n_keys


def test_executor_satisfies_the_contract_protocol() -> None:
    assert isinstance(DataOpsExecutor(), OperationExecutor)
    assert isinstance(create_executor({}), OperationExecutor)


def test_duplicate_registration_is_rejected() -> None:
    reg = OperationRegistry()
    reg.register(CaseOp())
    with pytest.raises(ValueError):
        reg.register(CaseOp())


def test_describe_all_is_deterministic_and_sorted() -> None:
    a = [d.type for d in DataOpsExecutor(build_registry()).describe_all()]
    assert a == sorted(a)
    assert DataOpsExecutor(build_registry()).describe_all() == DataOpsExecutor(build_registry()).describe_all()


@pytest.mark.parametrize("desc", DataOpsExecutor(build_registry()).describe_all(), ids=lambda d: d.type)
def test_descriptor_schema_is_valid_json_schema_with_vocab_and_i18n_keys(desc) -> None:  # type: ignore[no-untyped-def]
    Draft202012Validator.check_schema(desc.params_schema)
    s = desc.params_schema
    assert s["x-gridora-vocab"] == 1 and s["additionalProperties"] is False
    assert desc.label == f"ops.{desc.type}.label" and desc.description == f"ops.{desc.type}.description"
    props = s["properties"]
    assert props["column"]["title"] == f"ops.{desc.type}.params.column.title"
    assert props["column"]["x-gridora-column"] is True
    json.dumps(s)  # serialisable


def test_enum_values_get_label_keys() -> None:
    d = CaseOp().descriptor()
    assert d.params_schema["properties"]["mode"]["x-gridora-enum-labels"] == {
        "upper": "ops.t_case.params.mode.options.upper", "lower": "ops.t_case.params.mode.options.lower"}


def test_production_registry_is_sorted_and_unique() -> None:
    types = [s.type for s in default_registry().all()]
    assert types == sorted(set(types))


def test_required_keys_listing_includes_category_and_enums() -> None:
    keys = required_i18n_keys(CaseOp().descriptor())
    assert "ops.categories.clean" in keys and "ops.t_case.params.mode.options.upper" in keys


# ------------------------------------------------------------ catalog
def test_every_error_code_has_persian_and_english_text() -> None:
    fa, en = catalog("fa"), catalog("en")
    for code in ERROR_CODES:
        assert fa[f"errors.{code}.message"].strip(), code
        assert en[f"errors.{code}.message"].strip(), code


def test_persian_is_default_and_english_falls_back_per_key() -> None:
    assert catalog("fa-IR") == catalog("fa") == catalog("unknown")
    assert catalog("en")["ops.categories.order"] == "Order"
    assert set(catalog("fa")) <= set(catalog("en"))


def test_persian_texts_contain_persian_letters_only_where_expected() -> None:
    for k, v in catalog("fa").items():
        assert any("\u0600" <= ch <= "\u06ff" for ch in v), k
        assert "ي" not in v and "ك" not in v, f"Arabic letter variants in {k}"  # ي / ك
