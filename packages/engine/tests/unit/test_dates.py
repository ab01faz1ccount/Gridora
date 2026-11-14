import pytest

from gridora_engine.model.dates import is_date_format, iso_to_serial, serial_to_iso


@pytest.mark.parametrize(
    "serial,iso",
    [
        (1, "1900-01-01"), (59, "1900-02-28"), (60, "1900-02-29"), (61, "1900-03-01"),
        (36526, "2000-01-01"), (45292, "2024-01-01"), (45292.5, "2024-01-01T12:00:00"),
        (0.5, "12:00:00"), (2958465, "9999-12-31"),
    ],
)
def test_1900_system(serial, iso):
    assert serial_to_iso(serial) == iso
    if serial >= 1 and serial != 0.5:
        assert iso_to_serial(iso) == pytest.approx(serial)


def test_1904_system():
    assert serial_to_iso(0, "1904") == "1904-01-01"
    assert serial_to_iso(1461, "1904") == "1908-01-01"
    assert iso_to_serial("1908-01-01", "1904") == 1461


@pytest.mark.parametrize("bad", [-1, 0, 2958466, float("nan")])
def test_not_representable(bad):
    assert serial_to_iso(bad) is None


def test_rounding_carries_into_next_day():
    assert serial_to_iso(45292.999999999) == "2024-01-02"


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("yyyy-mm-dd", True), ("h:mm AM/PM", True), ('[$-F800]dddd, mmmm dd, yyyy', True),
        ("[h]:mm:ss", True), ("General", False), ("0.00", False), ("#,##0", False),
        ('0.0 "m"', False), ('#,##0 "days"', False), (r"0\d", False), ("0.00E+00", False),
        ("[Red]0.00;[Blue]-0.00", False), (None, False), ("", False),
    ],
)
def test_is_date_format(fmt, expected):
    assert is_date_format(fmt) is expected


def test_builtin_ids():
    assert is_date_format(None, 14) and is_date_format(None, 22) and not is_date_format(None, 2)
