import inspect

import pytest
from gridora_contracts.protocols import FormattingEngine, StructureEngine, WorkbookEngine

from gridora_engine import create_engine
from gridora_engine.engine import GridoraEngine, Handle
from gridora_engine.errors import GridoraEngineError


def test_create_engine_satisfies_protocol():
    assert isinstance(create_engine({}), WorkbookEngine)


def test_import_signatures_accept_file_id_keyword_only():
    for name in ("import_xlsx", "import_csv"):
        p = inspect.signature(getattr(GridoraEngine, name)).parameters["file_id"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY
        assert p.default is None


def test_optional_extensions_claimed_and_not_claimed():
    e = create_engine({})
    assert not isinstance(e, FormattingEngine)
    assert isinstance(e, StructureEngine)  # insert/delete rows and columns (src/gridora_engine/structure.py)


def test_recalculate_unknown_handle_is_a_typed_error():
    e = create_engine({})
    with pytest.raises(GridoraEngineError) as ei:
        e.recalculate(Handle("x"))
    assert ei.value.reason == "handle.unknown"


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


def test_create_engine_accepts_the_optional_blob_store_of_contracts_0_4_0():
    import inspect

    from gridora_engine import create_engine as ce

    p = inspect.signature(ce).parameters["blobs"]
    assert p.default is None

    class Blobs:
        def put(self, data: bytes) -> str:
            return "ref"

        def get(self, ref: str) -> bytes:
            return b""

    assert create_engine({}, Blobs()).blobs is not None and create_engine({}).blobs is None
