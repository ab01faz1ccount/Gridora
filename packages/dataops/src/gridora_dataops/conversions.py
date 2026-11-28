"""Column type conversion (used by `change_type` and by dtype overrides in the sheet->table bridge).

Text -> number understands Persian/Arabic-Indic digits, thousands separators (`,` `٬` `،`), Arabic decimal
separator (`٫`) and spaces. The decimal separator is `.` unless the caller says `,` (never guessed: "1,5" is
ambiguous).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import polars as pl
from gridora_contracts.models import Warning_

from .errors import DataOpsError, pointer
from .persian.chars import variant_fold

TypeName = Literal["int64", "float64", "bool", "string", "date", "datetime", "decimal"]
POLARS_DTYPES: dict[str, pl.DataType | type[pl.DataType]] = {
    "int64": pl.Int64, "float64": pl.Float64, "bool": pl.Boolean, "string": pl.String,
    "date": pl.Date, "datetime": pl.Datetime("us"), "decimal": pl.Decimal(38, 10),
}
BOOL_TRUE = ["true", "1", "yes", "y", "بله", "آری", "درست", "صحیح"]
BOOL_FALSE = ["false", "0", "no", "n", "خیر", "نه", "غلط", "نادرست"]
INT_LIMIT = 2**53


@dataclass
class Conversion:
    frame: pl.DataFrame
    bad: int = 0
    examples: list[str] = field(default_factory=list)
    warnings: list[Warning_] = field(default_factory=list)


def number_to_text(e: pl.Expr) -> pl.Expr:
    """A number as a person reads it, ONE definition for `change_type` and computed columns: whole numbers without
    ".0", at most 15 significant digits (0.1 + 0.2 -> 0.3, as a spreadsheet shows it), and integers from 10^15 up in
    full (a 16-digit id must never be rounded)."""
    f = e.cast(pl.Float64)
    whole = f.is_finite() & (f == f.floor()) & (f.abs() < 1e15)
    return (pl.when(whole).then(f.cast(pl.Int64).cast(pl.String))
            .when(f.abs() >= 1e15).then(e.cast(pl.String))
            .otherwise(f.round_sig_figs(15).cast(pl.String)))


def number_text(e: pl.Expr, decimal_separator: str = ".") -> pl.Expr:
    e = variant_fold(e.str.strip_chars())
    e = e.str.replace_all(r"[\s\u00a0\u202f]", "")
    if decimal_separator == ",":
        e = e.str.replace_all(r"[.\u066c]", "").str.replace_all(r"[,\u066b]", ".")
    else:
        e = e.str.replace_all(r"[,\u066c\u060c]", "").str.replace_all(r"\u066b", ".")
    return pl.when(e == "").then(None).otherwise(e)


JALALI_YEARS = (1300, 1500)  # the years persian/jalali.py supports; as a Gregorian year they are not plausible data


def _not_jalali(parsed: pl.Expr) -> pl.Expr:
    """A text date such as 1403/01/01 is a Jalali date, not the year 1403: never store it as one. It counts as
    unconvertible (see `looks_jalali`), so on_error decides; convert_calendar(from_jalali) is the way to read it."""
    return pl.when(parsed.dt.year().is_between(*JALALI_YEARS)).then(None).otherwise(parsed)


def looks_jalali(col: pl.Expr) -> pl.Expr:
    year = variant_fold(col.str.strip_chars()).str.extract(r"^(\d{4})[/.\-]\d{1,2}[/.\-]\d{1,2}", 1).cast(pl.Int64, strict=False)
    return year.is_between(*JALALI_YEARS)


def _text_to(col: pl.Expr, to: str, decimal_separator: str, date_format: str | None) -> pl.Expr:
    if to in ("float64", "int64", "decimal"):
        t = number_text(col, decimal_separator)
        if to == "float64":
            f = t.cast(pl.Float64, strict=False)
            return pl.when(f.is_finite()).then(f)
        if to == "decimal":
            return t.cast(POLARS_DTYPES["decimal"], strict=False)
        as_int = t.cast(pl.Int64, strict=False)
        f = t.cast(pl.Float64, strict=False)
        via_float = pl.when(f.is_finite() & (f == f.floor()) & (f.abs() < INT_LIMIT)).then(f.cast(pl.Int64))
        return pl.coalesce(as_int, via_float)
    if to == "bool":
        key = variant_fold(col.str.strip_chars()).str.to_lowercase()
        return pl.when(key.is_in(BOOL_TRUE)).then(True).when(key.is_in(BOOL_FALSE)).then(False)
    if to in ("date", "datetime"):
        t = variant_fold(col.str.strip_chars())
        if to == "date":
            fmt = date_format or "%Y-%m-%d"
            t = t if date_format else t.str.replace_all(r"[/.]", "-")
            return _not_jalali(t.str.to_date(fmt, strict=False))
        if date_format:
            return t.str.to_datetime(date_format, strict=False)
        t = t.str.replace_all(r"[/.]", "-").str.replace("T", " ")
        return pl.coalesce(t.str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False),
                           t.str.to_datetime("%Y-%m-%d %H:%M", strict=False),
                           t.str.to_date("%Y-%m-%d", strict=False).cast(pl.Datetime("us")))
    raise AssertionError(to)


def _numeric_to(col: pl.Expr, to: str) -> pl.Expr:
    if to == "string":
        return number_to_text(col)
    if to == "int64":
        f = col.cast(pl.Float64)
        return pl.when(f.is_finite() & (f == f.floor()) & (f.abs() < INT_LIMIT)).then(f.cast(pl.Int64))
    if to == "float64":
        return col.cast(pl.Float64)
    if to == "decimal":
        return col.cast(POLARS_DTYPES["decimal"], strict=False)
    if to == "bool":
        return pl.when(col == 0).then(False).when(col == 1).then(True)
    raise DataOpsError("type_mismatch", f"cannot convert number to {to}")


def _expr(col: pl.Expr, src: pl.DataType, to: str, decimal_separator: str, date_format: str | None) -> pl.Expr:
    if src == pl.String:
        if to == "string":
            return col
        return _text_to(col, to, decimal_separator, date_format)
    if src.is_numeric():
        return _numeric_to(col, to)
    if src == pl.Boolean:
        if to == "string":
            return pl.when(col).then(pl.lit("true")).when(~col).then(pl.lit("false"))  # an empty cell stays empty
        if to in ("int64", "float64"):
            return col.cast(pl.Int64 if to == "int64" else pl.Float64)
    if src == pl.Date:
        if to == "string":
            return col.dt.to_string("%Y-%m-%d")
        if to == "datetime":
            return col.cast(pl.Datetime("us"))
    if isinstance(src, pl.Datetime):
        if to == "string":
            return col.dt.to_string("%Y-%m-%d %H:%M:%S")
        if to == "date":
            return col.dt.date()
    raise DataOpsError("type_mismatch", f"cannot convert {src} to {to}")


def convert_column(df: pl.DataFrame, column: str, to: str, *, on_error: str = "fail",
                   decimal_separator: str = ".", date_format: str | None = None,
                   path: str = pointer("params", "to")) -> Conversion:
    """Convert one column. Values that cannot be converted are an error (`fail`) or become empty (`null`)."""
    src = df.schema[column]
    target = POLARS_DTYPES[to]
    if src == target or (to == "datetime" and isinstance(src, pl.Datetime)):
        return Conversion(df)
    try:
        new = _expr(pl.col(column), src, to, decimal_separator, date_format)
    except DataOpsError as e:
        raise DataOpsError(e.code, e.message, path=path) from None
    work = df.with_columns(new.alias("__new"))
    orig_has = pl.col(column).is_not_null()
    if src == pl.String:
        orig_has = orig_has & (pl.col(column).str.strip_chars() != "")
    bad_df = work.filter(orig_has & pl.col("__new").is_null())
    bad = bad_df.height
    examples = [str(x) for x in bad_df[column].head(3).to_list()]
    jalali = 0
    if bad and src == pl.String and to in ("date", "datetime"):
        jalali = bad_df.filter(looks_jalali(pl.col(column))).height
    hint = "e.g. " + "; ".join(examples)
    if jalali:
        hint += f" ({jalali} look like Jalali dates: use convert_calendar from_jalali)"
    if bad and on_error == "fail":
        raise DataOpsError("type_mismatch", f"{bad} value(s) in '{column}' cannot be converted to {to}",
                           path=pointer("params", "column"), hint=hint)
    out = work.with_columns(pl.col("__new").alias(column)).drop("__new")
    warnings = []
    if bad:
        warnings.append(Warning_(code="values_set_to_null", severity="warn", location=column,
                                 message=f"{bad} value(s) could not be converted to {to} and were left empty"))
        if jalali:
            warnings.append(Warning_(code="dates_look_jalali", severity="warn", location=column,
                                     message=f"{jalali} value(s) look like Jalali dates (year 1300-1500) and were not read "
                                             "as Gregorian: use convert_calendar from_jalali"))
    return Conversion(out, bad, examples, warnings)
