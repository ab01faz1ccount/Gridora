import inspect

import pytest
from gridora_contracts.protocols import FormattingEngine, StructureEngine, WorkbookEngine

from gridora_engine import create_engine
from gridora_engine.engine import GridoraEngine, Handle
from gridora_engine.errors import EngineNotImplementedError, GridoraEngineError


def test_create_engine_satisfies_protocol():
    assert isinstance(create_engine({}), WorkbookEngine)


def test_import_signatures_accept_file_id_keyword_only():
    for name in ("import_xlsx", "import_csv"):
        p = inspect.signature(getattr(GridoraEngine, name)).parameters["file_id"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY
        assert p.default is None


def test_optional_extensions_are_not_claimed_yet():
    e = create_engine({})
    assert not isinstance(e, FormattingEngine)
    assert not isinstance(e, StructureEngine)


def test_unimplemented_methods_raise_typed_error():
    e = create_engine({})
    with pytest.raises(EngineNotImplementedError):
        e.recalculate(Handle("x"))


def test_close_unknown_handle_is_noop():
    create_engine({}).close(Handle("nope"))


@pytest.mark.parametrize("cfg", [{"nope": 1}, {"limits": {"nope": 1}}, {"csv_export_encoding": "x"}])
def test_bad_config_rejected_without_leaking_values(cfg):
    with pytest.raises(GridoraEngineError) as ei:
        create_engine(cfg)
    assert ei.value.code == "bad_request"
    assert "nope" not in str(ei.value)


def test_error_requires_contract_code():
    with pytest.raises(ValueError):
        GridoraEngineError("made_up", "x", "y")
