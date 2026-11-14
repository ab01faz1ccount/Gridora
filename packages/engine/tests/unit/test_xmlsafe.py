import pytest

from gridora_engine.errors import GridoraEngineError
from gridora_engine.package import xmlsafe

MARK = "SECRETMARK"


def run(data: bytes, **kw):
    events: list[str] = []
    xmlsafe.parse(data, start=lambda n, a: events.append(n), **kw)
    return events


def test_valid_xml_with_and_without_bom_and_namespaces():
    assert run(b'<?xml version="1.0" encoding="UTF-8"?><a xmlns="urn:x"><b/></a>') == ["urn:x a", "urn:x b"]
    assert run(b"\xef\xbb\xbf<a/>") == ["a"]
    assert xmlsafe.local("urn:x a") == "a" and xmlsafe.local("a") == "a"


BAD = {
    "doctype": b"<!DOCTYPE a><a/>",
    "internal_entity": b'<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>',
    "external_entity": b'<!DOCTYPE a [<!ENTITY e SYSTEM "file:///etc/passwd">]><a>&e;</a>',
    "parameter_entity": b'<!DOCTYPE a [<!ENTITY % p SYSTEM "http://127.0.0.1/x"> %p;]><a/>',
    "billion_laughs": (b'<!DOCTYPE a [<!ENTITY a0 "x">' + b"".join(
        b'<!ENTITY a%d "&a%d;&a%d;&a%d;&a%d;&a%d;&a%d;&a%d;&a%d;&a%d;&a%d;">' % ((i,) + (i - 1,) * 10)
        for i in range(1, 8)) + b"]><a>&a7;</a>"),
    "deep": b"<a>" * 200 + b"</a>" * 200,
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_forbidden_constructs_rejected_with_fixed_message(name):
    with pytest.raises(GridoraEngineError) as e:
        run(BAD[name])
    assert e.value.code == "import_failed" and e.value.reason == "xml.forbidden_construct"
    assert "passwd" not in str(e.value) and "127.0.0.1" not in str(e.value)


@pytest.mark.parametrize(
    "data",
    ["<a>".encode("utf-16"), b'<?xml version="1.0" encoding="ISO-8859-1"?><a/>',
     b'<?xml version="1.0" encoding="utf-16"?><a/>', "<?xml version='1.0'?><a/>".encode("utf-16-le")],
)
def test_non_utf8_encodings_rejected(data):
    with pytest.raises(GridoraEngineError) as e:
        run(data)
    assert e.value.reason == "xml.encoding_unsupported"


@pytest.mark.parametrize("data", [b"<a>", b"<a></b>", b"not xml " + MARK.encode(), b"", b"<a b=1/>"])
def test_malformed_rejected_without_echoing_input(data):
    with pytest.raises(GridoraEngineError) as e:
        run(data)
    assert e.value.reason == "xml.malformed" and MARK not in str(e.value)


def test_custom_depth_limit():
    with pytest.raises(GridoraEngineError):
        run(b"<a><b><c/></b></a>", max_depth=2)
    assert run(b"<a><b/></a>", max_depth=2) == ["a", "b"]
